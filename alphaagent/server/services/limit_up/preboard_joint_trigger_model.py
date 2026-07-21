"""Direct joint-utility model for causal pre-board action research."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import exp, isfinite
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    COMPETING_FEATURE_NAMES,
    competing_feature_vector,
    select_confirmed_competing_signals,
)
from alphaagent.server.services.limit_up.preboard_hazard_model import (
    attach_hazard_targets,
)


PREPARE_TARGET_FIELD = "formal_touch_within_5m"
ACTION_TARGET_FIELD = "profitable_formal_touch_within_3m"
PREPARE_SCORE_FIELD = "prepare_touch_probability"
ACTION_SCORE_FIELD = "joint_action_probability"
DEFAULT_ACTION_THRESHOLDS = tuple(
    round(value / 100, 2) for value in range(5, 100, 5)
)


@dataclass(frozen=True)
class JointTriggerModelFit:
    status: str
    pipeline: Any | None
    target_field: str
    training_row_count: int
    training_pair_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    scaler_mean_by_feature: dict[str, float]
    scaler_scale_by_feature: dict[str, float]
    coefficient_by_feature: dict[str, float]
    intercept: float | None
    fingerprint: str | None

    def probability(self, row: Mapping[str, object]) -> float | None:
        vector = competing_feature_vector(row)
        if self.pipeline is None or vector is None:
            return None
        matrix = np.asarray([vector], dtype=float)
        return float(self.pipeline.predict_proba(matrix)[0, 1])


@dataclass(frozen=True)
class JointThresholdSelection:
    status: str
    threshold: float | None
    calibration_dates: tuple[str, ...]
    minimum_selection_count: int
    selected_metrics: dict[str, float | int | None]
    metrics_by_threshold: tuple[dict[str, float | int | None], ...]


def attach_joint_trigger_targets(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach five-minute prepare and profitable three-minute action labels."""

    labeled = attach_hazard_targets(rows, formal_orders, horizons=(3, 5))
    result: list[dict[str, object]] = []
    for row in labeled:
        net_return = _number(row.get("net_return_pct"))
        result.append(
            {
                **row,
                ACTION_TARGET_FIELD: bool(
                    row.get("formal_touch_within_3m") is True
                    and net_return is not None
                    and net_return > 0
                ),
            }
        )
    return result


def joint_training_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
    target_field: str = ACTION_TARGET_FIELD,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[tuple[str, str], ...]]:
    """Build finite observations with total sample weight one per stock-day."""

    prepared: list[tuple[list[float], int, tuple[str, str]]] = []
    pair_counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        pair = _row_pair(row)
        vector = competing_feature_vector(row)
        if (
            signal_date not in allowed_dates
            or not all(pair)
            or vector is None
            or row.get(target_field) is None
        ):
            continue
        prepared.append((vector, int(bool(row.get(target_field))), pair))
        pair_counts[pair] += 1

    matrix = (
        np.asarray([item[0] for item in prepared], dtype=float)
        if prepared
        else np.empty((0, len(COMPETING_FEATURE_NAMES)))
    )
    labels = np.asarray([item[1] for item in prepared], dtype=int)
    pairs = tuple(item[2] for item in prepared)
    weights = np.asarray(
        [1.0 / pair_counts[pair] for pair in pairs],
        dtype=float,
    )
    return matrix, labels, weights, pairs


def fit_joint_trigger_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    target_field: str = ACTION_TARGET_FIELD,
) -> JointTriggerModelFit:
    """Fit one deterministic natural-prevalence Logistic model."""

    matrix, labels, weights, pairs = joint_training_batch(
        rows,
        allowed_dates=fit_dates,
        target_field=target_field,
    )
    class_counts = {
        str(label): int(count)
        for label, count in sorted(Counter(labels.tolist()).items())
    }
    common = {
        "target_field": target_field,
        "training_row_count": len(labels),
        "training_pair_count": len(set(pairs)),
        "class_counts": class_counts,
        "fit_dates": tuple(value.isoformat() for value in sorted(fit_dates)),
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return JointTriggerModelFit(
            status="insufficient_training_classes",
            pipeline=None,
            scaler_mean_by_feature={},
            scaler_scale_by_feature={},
            coefficient_by_feature={},
            intercept=None,
            fingerprint=None,
            **common,
        )

    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    class_weight=None,
                    max_iter=2_000,
                    random_state=0,
                ),
            ),
        ]
    )
    pipeline.fit(
        matrix,
        labels,
        scaler__sample_weight=weights,
        logistic__sample_weight=weights,
    )
    scaler = pipeline.named_steps["scaler"]
    logistic = pipeline.named_steps["logistic"]
    means = _feature_mapping(scaler.mean_)
    scales = _feature_mapping(scaler.scale_)
    coefficients = _feature_mapping(logistic.coef_[0])
    intercept = _canonical_float(logistic.intercept_[0])
    fingerprint = _model_fingerprint(
        target_field=target_field,
        fit_dates=common["fit_dates"],
        scaler_mean_by_feature=means,
        scaler_scale_by_feature=scales,
        coefficient_by_feature=coefficients,
        intercept=intercept,
    )
    return JointTriggerModelFit(
        status="ready",
        pipeline=pipeline,
        scaler_mean_by_feature=means,
        scaler_scale_by_feature=scales,
        coefficient_by_feature=coefficients,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def score_joint_trigger_rows(
    rows: Sequence[Mapping[str, object]],
    model: JointTriggerModelFit,
    *,
    score_field: str = ACTION_SCORE_FIELD,
) -> list[dict[str, object]]:
    """Score all finite rows in one sklearn matrix call."""

    if model.status != "ready" or model.pipeline is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := competing_feature_vector(row)) is not None
    ]
    if not prepared:
        return []
    matrix = np.asarray([vector for _, vector in prepared], dtype=float)
    probabilities = model.pipeline.predict_proba(matrix)[:, 1]
    return [
        {
            **row,
            score_field: round(float(probability), 8),
        }
        for (row, _), probability in zip(prepared, probabilities, strict=True)
    ]


def score_frozen_joint_probability(
    row: Mapping[str, object],
    model: JointTriggerModelFit,
) -> float | None:
    """Reconstruct one probability from archived numeric model parameters."""

    vector = competing_feature_vector(row)
    if vector is None or model.intercept is None:
        return None
    logit = float(model.intercept)
    for field, value in zip(COMPETING_FEATURE_NAMES, vector, strict=True):
        mean_value = _number(model.scaler_mean_by_feature.get(field))
        scale_value = _number(model.scaler_scale_by_feature.get(field))
        coefficient = _number(model.coefficient_by_feature.get(field))
        if (
            mean_value is None
            or scale_value is None
            or scale_value <= 0
            or coefficient is None
        ):
            return None
        logit += coefficient * (value - mean_value) / scale_value
    if logit >= 0:
        return 1.0 / (1.0 + exp(-logit))
    exponential = exp(logit)
    return exponential / (1.0 + exponential)


def calibrate_joint_threshold(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = DEFAULT_ACTION_THRESHOLDS,
    minimum_selection_count: int = 10,
    confirmation_minutes: int = 2,
    max_daily_actions: int = 2,
) -> JointThresholdSelection:
    """Freeze the action threshold from declared calibration dates only."""

    calibration_rows = [
        dict(row)
        for row in rows
        if _as_date(row.get("signal_date")) in calibration_dates
    ]
    target_pairs = {
        _row_pair(row)
        for row in calibration_rows
        if row.get(ACTION_TARGET_FIELD) is True
    }
    metrics = tuple(
        _threshold_metrics(
            calibration_rows,
            threshold=float(threshold),
            target_pairs=target_pairs,
            confirmation_minutes=confirmation_minutes,
            max_daily_actions=max_daily_actions,
        )
        for threshold in thresholds
    )
    qualified = [
        row
        for row in metrics
        if int(row["selection_count"] or 0) >= max(minimum_selection_count, 1)
    ]
    selected = max(
        qualified,
        key=lambda row: (
            float(row["f0_5"] or 0.0),
            float(row["joint_precision"] or 0.0),
            float(row["threshold"] or 0.0),
        ),
        default=None,
    )
    return JointThresholdSelection(
        status="ready" if selected is not None else "insufficient_calibration_signals",
        threshold=float(selected["threshold"]) if selected is not None else None,
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        minimum_selection_count=max(minimum_selection_count, 1),
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def probability_calibration_report(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
    score_field: str = ACTION_SCORE_FIELD,
    target_field: str = ACTION_TARGET_FIELD,
    bin_count: int = 10,
) -> dict[str, object]:
    """Summarize historical score calibration without changing the policy."""

    count = max(int(bin_count), 1)
    observations = [
        (probability, int(bool(row.get(target_field))))
        for row in rows
        if _as_date(row.get("signal_date")) in allowed_dates
        and row.get(target_field) is not None
        and (probability := _number(row.get(score_field))) is not None
        and 0 <= probability <= 1
    ]
    bins: list[list[tuple[float, int]]] = [[] for _ in range(count)]
    for probability, target in observations:
        index = min(int(probability * count), count - 1)
        bins[index].append((probability, target))
    probabilities = [probability for probability, _ in observations]
    return {
        "observation_count": len(observations),
        "positive_count": sum(target for _, target in observations),
        "base_rate_pct": _percentage(
            sum(target for _, target in observations),
            len(observations),
        ),
        "brier_score": (
            round(
                sum((probability - target) ** 2 for probability, target in observations)
                / len(observations),
                8,
            )
            if observations
            else None
        ),
        "score_distribution": {
            "p25": _percentile(probabilities, 25),
            "median": _percentile(probabilities, 50),
            "p75": _percentile(probabilities, 75),
        },
        "bins": [
            {
                "lower_bound": round(index / count, 4),
                "upper_bound": round((index + 1) / count, 4),
                "observation_count": len(values),
                "mean_predicted_pct": (
                    round(sum(value for value, _ in values) / len(values) * 100, 4)
                    if values
                    else None
                ),
                "actual_rate_pct": _percentage(
                    sum(target for _, target in values),
                    len(values),
                ),
            }
            for index, values in enumerate(bins)
        ],
    }


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    return round(float(np.percentile(np.asarray(values, dtype=float), percentile)), 8)


def _threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    target_pairs: set[tuple[str, str]],
    confirmation_minutes: int,
    max_daily_actions: int,
) -> dict[str, float | int | None]:
    selected = select_confirmed_competing_signals(
        rows,
        threshold=threshold,
        score_field=ACTION_SCORE_FIELD,
        confirmation_minutes=confirmation_minutes,
        max_daily_actions=max_daily_actions,
    )
    selected_pairs = {_row_pair(row) for row in selected}
    true_pairs = {
        _row_pair(row)
        for row in selected
        if row.get(ACTION_TARGET_FIELD) is True
    }
    precision = _ratio(len(true_pairs), len(selected_pairs))
    recall = _ratio(len(true_pairs), len(target_pairs))
    return {
        "threshold": round(threshold, 4),
        "selection_count": len(selected_pairs),
        "joint_true_positive_count": len(true_pairs),
        "joint_precision": precision,
        "reachable_recall": recall,
        "f0_5": _f_beta(precision, recall, beta=0.5),
    }


def _feature_mapping(values: Sequence[object]) -> dict[str, float]:
    return {
        field: _canonical_float(value)
        for field, value in zip(COMPETING_FEATURE_NAMES, values, strict=True)
    }


def _canonical_float(value: object) -> float:
    rounded = round(float(value), 10)
    return 0.0 if rounded == 0 else rounded


def _model_fingerprint(
    *,
    target_field: str,
    fit_dates: Sequence[str],
    scaler_mean_by_feature: Mapping[str, float],
    scaler_scale_by_feature: Mapping[str, float],
    coefficient_by_feature: Mapping[str, float],
    intercept: float,
) -> str:
    payload = {
        "target_field": target_field,
        "features": list(COMPETING_FEATURE_NAMES),
        "fit_dates": list(fit_dates),
        "scaler_mean_by_feature": dict(scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(scaler_scale_by_feature),
        "coefficient_by_feature": dict(coefficient_by_feature),
        "intercept": intercept,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()[:16]


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("vt_symbol") or ""),
        str(row.get("signal_date") or row.get("trade_date") or "")[:10],
    )


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _f_beta(
    precision: float | None,
    recall: float | None,
    *,
    beta: float,
) -> float | None:
    if precision is None or recall is None:
        return None
    beta_squared = beta * beta
    denominator = beta_squared * precision + recall
    if denominator <= 0:
        return 0.0
    return (1 + beta_squared) * precision * recall / denominator
