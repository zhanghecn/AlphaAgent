"""Model fitting and candidate scoring for limit-up walk-forward research."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import isfinite
from statistics import mean
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

from alphaagent.server.services.limit_up.walk_forward_contract import (
    FEATURE_NAMES,
    ModelSample,
    WalkForwardConfig,
    WalkForwardWindow,
)


@dataclass
class ProbabilityEstimator:
    model: LGBMClassifier
    calibrator: LogisticRegression | None
    raw_brier: float
    calibrated_brier: float
    auc: float | None

    def predict_raw(self, features: pd.DataFrame) -> np.ndarray:
        return np.clip(self.model.predict_proba(features)[:, 1], 1e-6, 1 - 1e-6)

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        raw = self.predict_raw(features)
        if self.calibrator is None:
            return raw
        logits = np.log(raw / (1 - raw)).reshape(-1, 1)
        return self.calibrator.predict_proba(logits)[:, 1]


@dataclass
class ReturnEstimator:
    model: LGBMRegressor
    calibration_bias: float
    bin_boundaries: tuple[float, ...]
    bin_lower_bounds: tuple[float, ...]

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        return self.model.predict(features) + self.calibration_bias

    def confidence_lower(self, expected_return_pct: float) -> float:
        if not self.bin_lower_bounds:
            return float("-inf")
        index = int(np.searchsorted(self.bin_boundaries, expected_return_pct, side="right"))
        return self.bin_lower_bounds[min(index, len(self.bin_lower_bounds) - 1)]


@dataclass
class ModelBundle:
    status: str
    fill: ProbabilityEstimator | None
    seal: ProbabilityEstimator | None
    profit: ProbabilityEstimator | None
    returns: ReturnEstimator | None
    calibration: dict[str, object]
    reason: str | None = None


def fit_model_bundle(
    window: WalkForwardWindow,
    *,
    entry_mode: str,
    config: WalkForwardConfig,
) -> ModelBundle:
    training = list(window.training_samples)
    calibration = list(window.calibration_samples)
    if len(training) < config.min_training_samples:
        return ModelBundle(
            status="insufficient_training",
            fill=None,
            seal=None,
            profit=None,
            returns=None,
            calibration={},
            reason=f"训练样本{len(training)}少于{config.min_training_samples}",
        )
    seal = _fit_probability_estimator(
        training,
        calibration,
        label=lambda sample: sample.sealed,
        config=config,
        seed_offset=11,
    )
    conditional_training = _conditional_return_samples(training, entry_mode)
    conditional_calibration = _conditional_return_samples(calibration, entry_mode)
    profit = _fit_probability_estimator(
        conditional_training,
        conditional_calibration,
        label=lambda sample: sample.profitable,
        config=config,
        seed_offset=23,
    )
    returns = _fit_return_estimator(
        conditional_training,
        conditional_calibration,
        config=config,
    )
    fill = None
    if entry_mode == "sweep":
        fill = _fit_probability_estimator(
            training,
            calibration,
            label=lambda sample: sample.fill_proxy,
            config=config,
            seed_offset=37,
        )
    # Board-event samples are already conditioned on a touch, so fill can be one-class.
    required = [seal, profit, returns]
    if any(item is None for item in required):
        return ModelBundle(
            status="insufficient_training",
            fill=fill,
            seal=seal,
            profit=profit,
            returns=returns,
            calibration={},
            reason="训练或校准区间缺少足够的正负样本",
        )
    return ModelBundle(
        status="ready",
        fill=fill,
        seal=seal,
        profit=profit,
        returns=returns,
        calibration={
            "fill": _probability_metrics(fill),
            "seal": _probability_metrics(seal),
            "profit": _probability_metrics(profit),
            "return_bootstrap_bins": len(returns.bin_lower_bounds),
        },
    )


def score_window(
    window: WalkForwardWindow,
    bundle: ModelBundle,
    *,
    entry_mode: str,
    config: WalkForwardConfig,
) -> list[dict[str, object]]:
    if bundle.status != "ready" or not window.test_samples:
        return []
    assert bundle.seal is not None
    assert bundle.profit is not None
    assert bundle.returns is not None
    features = _feature_matrix(window.test_samples)
    raw_seal_probabilities = bundle.seal.predict_raw(features)
    seal_probabilities = bundle.seal.predict(features)
    raw_profit_probabilities = bundle.profit.predict_raw(features)
    profit_probabilities = bundle.profit.predict(features)
    expected_returns = bundle.returns.predict(features)
    if entry_mode == "sweep":
        if bundle.fill is not None:
            raw_fill_probabilities: Sequence[float | None] = bundle.fill.predict_raw(features)
            fill_probabilities: Sequence[float | None] = bundle.fill.predict(features)
        else:
            raw_fill_probabilities = [None] * len(window.test_samples)
            fill_probabilities = [None] * len(window.test_samples)
    elif entry_mode == "tail":
        raw_fill_probabilities = [None] * len(window.test_samples)
        fill_probabilities = [None] * len(window.test_samples)
    else:
        raw_fill_probabilities = [1.0] * len(window.test_samples)
        fill_probabilities = [1.0] * len(window.test_samples)
    rows: list[dict[str, object]] = []
    for index, sample in enumerate(window.test_samples):
        fill_probability = fill_probabilities[index]
        fill_weight = 1.0 if fill_probability is None else float(fill_probability)
        expected = float(expected_returns[index])
        lower = bundle.returns.confidence_lower(expected)
        rejection_reasons = _model_rejection_reasons(
            fill_weight,
            float(seal_probabilities[index]),
            float(profit_probabilities[index]),
            expected,
            lower,
            config=config,
        )
        rows.append(
            {
                "signal_date": sample.signal_date.isoformat(),
                "result_date": sample.result_date.isoformat(),
                "validation_phase": window.phase,
                "window_sequence": window.sequence,
                "vt_symbol": sample.vt_symbol,
                "name": sample.name,
                "industry_name": sample.industry_name,
                "rank": sample.rank,
                "target_board": sample.target_board,
                "raw_fill_probability": _rounded(raw_fill_probabilities[index]),
                "fill_probability": _rounded(fill_probability),
                "raw_seal_probability": _rounded(raw_seal_probabilities[index]),
                "seal_probability": _rounded(seal_probabilities[index]),
                "raw_profit_probability": _rounded(raw_profit_probabilities[index]),
                "profit_probability": _rounded(profit_probabilities[index]),
                "expected_return_pct": _rounded(expected),
                "confidence_lower_pct": _rounded(lower),
                "model_ev_pct": _rounded(fill_weight * expected),
                "model_eligible": not rejection_reasons,
                "simulation_eligible": False,
                "execution_status": _execution_status(entry_mode),
                "execution_confidence": sample.execution_confidence,
                "rejection_reasons": rejection_reasons,
                "fill_proxy": sample.fill_proxy,
                "sealed": sample.sealed,
                "realized_return_pct": sample.return_pct,
            }
        )
    return rows


def _fit_probability_estimator(
    training: Sequence[ModelSample],
    calibration: Sequence[ModelSample],
    *,
    label: Callable[[ModelSample], bool | None],
    config: WalkForwardConfig,
    seed_offset: int,
) -> ProbabilityEstimator | None:
    train_rows = [(sample, label(sample)) for sample in training]
    train_rows = [(sample, value) for sample, value in train_rows if value is not None]
    calibration_rows = [(sample, label(sample)) for sample in calibration]
    calibration_rows = [
        (sample, value) for sample, value in calibration_rows if value is not None
    ]
    minimum = max(8, min(config.min_training_samples, 40))
    if len(train_rows) < minimum or len(calibration_rows) < 4:
        return None
    train_labels = np.asarray([bool(value) for _, value in train_rows], dtype=int)
    calibration_labels = np.asarray(
        [bool(value) for _, value in calibration_rows],
        dtype=int,
    )
    if len(np.unique(train_labels)) < 2 or len(np.unique(calibration_labels)) < 2:
        return None
    train_features = _feature_matrix([sample for sample, _ in train_rows])
    calibration_features = _feature_matrix([sample for sample, _ in calibration_rows])
    model = LGBMClassifier(
        n_estimators=config.estimator_count,
        learning_rate=0.04,
        num_leaves=7,
        max_depth=3,
        min_child_samples=max(5, min(40, len(train_rows) // 12)),
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.2,
        reg_lambda=2.0,
        class_weight="balanced",
        random_state=config.random_seed + seed_offset,
        n_jobs=1,
        verbosity=-1,
    )
    model.fit(train_features, train_labels)
    raw = np.clip(model.predict_proba(calibration_features)[:, 1], 1e-6, 1 - 1e-6)
    logits = np.log(raw / (1 - raw)).reshape(-1, 1)
    calibrator = LogisticRegression(C=1.0, solver="lbfgs", random_state=config.random_seed)
    calibrator.fit(logits, calibration_labels)
    calibrated = calibrator.predict_proba(logits)[:, 1]
    return ProbabilityEstimator(
        model=model,
        calibrator=calibrator,
        raw_brier=float(brier_score_loss(calibration_labels, raw)),
        calibrated_brier=float(brier_score_loss(calibration_labels, calibrated)),
        auc=_safe_auc(calibration_labels, calibrated),
    )


def _fit_return_estimator(
    training: Sequence[ModelSample],
    calibration: Sequence[ModelSample],
    *,
    config: WalkForwardConfig,
) -> ReturnEstimator | None:
    minimum = max(8, min(config.min_training_samples, 40))
    if len(training) < minimum or len(calibration) < 4:
        return None
    train_features = _feature_matrix(training)
    train_returns = np.asarray([sample.return_pct for sample in training], dtype=float)
    calibration_features = _feature_matrix(calibration)
    calibration_returns = np.asarray([sample.return_pct for sample in calibration], dtype=float)
    model = LGBMRegressor(
        n_estimators=config.estimator_count,
        learning_rate=0.04,
        num_leaves=7,
        max_depth=3,
        min_child_samples=max(5, min(40, len(training) // 12)),
        subsample=0.85,
        colsample_bytree=0.85,
        reg_alpha=0.2,
        reg_lambda=2.0,
        random_state=config.random_seed + 51,
        n_jobs=1,
        verbosity=-1,
    )
    model.fit(train_features, train_returns)
    raw_calibration = model.predict(calibration_features)
    bias = float(np.mean(calibration_returns - raw_calibration))
    boundaries, lower_bounds = _bootstrap_return_bins(
        calibration,
        raw_calibration + bias,
        config=config,
    )
    return ReturnEstimator(
        model=model,
        calibration_bias=bias,
        bin_boundaries=boundaries,
        bin_lower_bounds=lower_bounds,
    )


def _bootstrap_return_bins(
    calibration: Sequence[ModelSample],
    predictions: np.ndarray,
    *,
    config: WalkForwardConfig,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    bin_count = max(1, min(5, len(calibration) // 10))
    if bin_count == 1:
        groups = [np.arange(len(calibration))]
        boundaries: tuple[float, ...] = ()
    else:
        quantiles = np.quantile(predictions, np.linspace(0, 1, bin_count + 1))
        internal = np.unique(quantiles[1:-1])
        assignments = np.searchsorted(internal, predictions, side="right")
        groups = [np.flatnonzero(assignments == index) for index in range(len(internal) + 1)]
        boundaries = tuple(float(value) for value in internal)
    lower_bounds: list[float] = []
    for group_index, indexes in enumerate(groups):
        daily: dict[date, list[float]] = defaultdict(list)
        for index in indexes:
            daily[calibration[int(index)].signal_date].append(
                calibration[int(index)].return_pct
            )
        daily_returns = np.asarray([mean(values) for values in daily.values()], dtype=float)
        if not len(daily_returns):
            lower_bounds.append(float("-inf"))
            continue
        rng = np.random.default_rng(config.random_seed + 100 + group_index)
        bootstrap_means = [
            float(np.mean(rng.choice(daily_returns, size=len(daily_returns), replace=True)))
            for _ in range(config.bootstrap_samples)
        ]
        lower_bounds.append(float(np.quantile(bootstrap_means, 0.10)))
    return boundaries, tuple(lower_bounds)


def _model_rejection_reasons(
    fill_probability: float,
    seal_probability: float,
    profit_probability: float,
    expected_return_pct: float,
    confidence_lower_pct: float,
    *,
    config: WalkForwardConfig,
) -> list[str]:
    reasons: list[str] = []
    if fill_probability < config.minimum_fill_probability:
        reasons.append("成交概率不足")
    if seal_probability < config.minimum_seal_probability:
        reasons.append("封板概率不足")
    if profit_probability < config.minimum_profit_probability:
        reasons.append("盈利概率不足")
    if expected_return_pct <= config.minimum_expected_return_pct:
        reasons.append("净期望不为正")
    if confidence_lower_pct <= config.minimum_confidence_lower_pct:
        reasons.append("训练期80%置信下界不为正")
    return reasons


def _conditional_return_samples(
    samples: Sequence[ModelSample],
    entry_mode: str,
) -> list[ModelSample]:
    if entry_mode == "tail":
        return list(samples)
    return [sample for sample in samples if sample.fill_proxy is True]


def _feature_matrix(samples: Sequence[ModelSample]) -> pd.DataFrame:
    return pd.DataFrame(
        [sample.features for sample in samples],
        columns=FEATURE_NAMES,
        dtype=float,
    )


def _probability_metrics(
    estimator: ProbabilityEstimator | None,
) -> dict[str, float | None] | None:
    if estimator is None:
        return None
    return {
        "raw_brier": _rounded(estimator.raw_brier),
        "calibrated_brier": _rounded(estimator.calibrated_brier),
        "auc": _rounded(estimator.auc),
    }


def _safe_auc(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    try:
        return float(roc_auc_score(labels, probabilities))
    except ValueError:
        return None


def _execution_status(entry_mode: str) -> str:
    return {
        "auction": "daily_open_proxy_without_point_in_time_membership",
        "next_auction": "daily_open_proxy_without_point_in_time_membership",
        "sweep": "daily_touch_proxy_without_l2",
        "tail": "tail_fill_unverifiable",
    }[entry_mode]


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _rounded(value: object, digits: int = 4) -> float | None:
    number = _number(value)
    return round(number, digits) if number is not None else None
