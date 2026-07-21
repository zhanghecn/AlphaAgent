"""Causal prediction of a later D-day limit touch from pre-board prefixes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from math import isfinite
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_momentum import (
    FEATURE_NAMES,
    HISTORY_FEATURE_NAMES,
)


MODEL_VARIANTS = (
    "intraday_only_logistic",
    "history_gate_intraday_logistic",
    "history_gate_full_logistic",
    "intraday_only_lightgbm",
    "history_gate_intraday_lightgbm",
    "history_gate_full_lightgbm",
)
PRIMARY_VARIANT = "history_gate_full_lightgbm"
MINIMUM_D1_SAMPLES = 5
MINIMUM_COMBINED_RATE = 30.0
CALIBRATION_THRESHOLDS = tuple(round(0.50 + index * 0.05, 2) for index in range(10))
MINIMUM_CALIBRATION_SIGNALS = 30


@dataclass(frozen=True)
class TouchModelFit:
    """One fitted touch classifier and its auditable training metadata."""

    status: str
    variant: str
    estimator_kind: str
    pipeline: Any | None
    training_row_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    feature_names: tuple[str, ...]
    importance_by_feature: dict[str, float]
    intercept: float | None
    training_fingerprint: str | None = None


@dataclass(frozen=True)
class TouchThresholdSelection:
    """A probability threshold selected only from calibration stock-days."""

    status: str
    threshold: float | None
    minimum_signal_count: int
    calibration_dates: tuple[str, ...]
    selected_metrics: dict[str, object]
    metrics_by_threshold: tuple[dict[str, object], ...]


def attach_later_touch_targets(
    prefix_rows: Sequence[Mapping[str, object]],
    bars: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Label whether the exact limit is reached after each completed prefix."""

    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
    )
    index_by_time = {
        value.isoformat(): index
        for index, bar in enumerate(ordered)
        if (value := _as_datetime(bar.get("bar_time"))) is not None
    }
    labeled: list[dict[str, object]] = []
    for raw in prefix_rows:
        row = dict(raw)
        current_index = index_by_time.get(str(row.get("signal_at") or ""))
        limit_price = _number(row.get("limit_price"))
        touch_index = _first_later_touch_index(
            ordered,
            current_index=current_index,
            limit_price=limit_price,
        )
        bars_to_touch = (
            touch_index - current_index
            if touch_index is not None and current_index is not None
            else None
        )
        touch_at = (
            _as_datetime(ordered[touch_index].get("bar_time"))
            if touch_index is not None
            else None
        )
        row.update(
            later_touch=touch_index is not None,
            bars_to_touch=bars_to_touch,
            trading_minutes_to_touch=(bars_to_touch * 5 if bars_to_touch else None),
            first_touch_at=touch_at.isoformat() if touch_at is not None else None,
        )
        labeled.append(row)
    return labeled


def touch_training_batch(
    rows: Sequence[Mapping[str, object]],
    variant: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Return causal candidate vectors and later-touch targets."""

    feature_names = _variant_feature_names(variant)
    vectors: list[list[float]] = []
    targets: list[int] = []
    for row in rows:
        vector = _candidate_vector(row, variant)
        if vector is None:
            continue
        vectors.append(vector)
        targets.append(int(bool(row.get("later_touch"))))
    matrix = (
        np.asarray(vectors, dtype=float)
        if vectors
        else np.empty((0, len(feature_names)), dtype=float)
    )
    return matrix, np.asarray(targets, dtype=int)


def fit_touch_model(
    rows: Sequence[Mapping[str, object]],
    *,
    variant: str,
    fit_dates: set[date],
) -> TouchModelFit:
    """Fit one frozen variant using rows from fit dates only."""

    selected = [
        row for row in rows if _as_date(row.get("signal_date")) in fit_dates
    ]
    matrix, targets = touch_training_batch(selected, variant)
    used_dates = {
        parsed
        for row in selected
        if _candidate_vector(row, variant) is not None
        and (parsed := _as_date(row.get("signal_date"))) is not None
    }
    return fit_touch_arrays(
        matrix,
        targets,
        variant=variant,
        fit_dates=used_dates,
    )


def fit_touch_arrays(
    matrix: np.ndarray,
    targets: np.ndarray,
    *,
    variant: str,
    fit_dates: set[date],
) -> TouchModelFit:
    """Fit a deterministic Logistic or shallow LightGBM touch classifier."""

    feature_names = _variant_feature_names(variant)
    estimator_kind = _variant_estimator_kind(variant)
    if matrix.ndim != 2 or matrix.shape[1] != len(feature_names):
        raise ValueError(
            f"{variant} expects {len(feature_names)} features, got {matrix.shape}"
        )
    counts = Counter(int(value) for value in targets.tolist())
    class_counts = {"negative": counts.get(0, 0), "positive": counts.get(1, 0)}
    date_texts = tuple(value.isoformat() for value in sorted(fit_dates))
    fingerprint = _training_fingerprint(variant, matrix, targets, date_texts)
    if len(matrix) == 0 or len(counts) < 2:
        return TouchModelFit(
            status="blocked_by_training_classes",
            variant=variant,
            estimator_kind=estimator_kind,
            pipeline=None,
            training_row_count=int(len(matrix)),
            class_counts=class_counts,
            fit_dates=date_texts,
            feature_names=feature_names,
            importance_by_feature={},
            intercept=None,
            training_fingerprint=fingerprint,
        )

    if estimator_kind == "logistic":
        pipeline, importance, intercept = _fit_logistic(
            matrix,
            targets,
            feature_names,
        )
    else:
        pipeline, importance, intercept = _fit_lightgbm(
            matrix,
            targets,
            feature_names,
        )
    return TouchModelFit(
        status="ready",
        variant=variant,
        estimator_kind=estimator_kind,
        pipeline=pipeline,
        training_row_count=int(len(matrix)),
        class_counts=class_counts,
        fit_dates=date_texts,
        feature_names=feature_names,
        importance_by_feature=importance,
        intercept=intercept,
        training_fingerprint=fingerprint,
    )


def first_touch_signal(
    rows: Sequence[Mapping[str, object]],
    model: TouchModelFit,
    *,
    threshold: float,
) -> dict[str, object] | None:
    """Return the first observable prefix crossing a frozen touch threshold."""

    candidates, probabilities = _scored_candidates(rows, model)
    for row, probability in zip(candidates, probabilities, strict=True):
        if probability >= threshold:
            return {
                **row,
                "algorithm": model.variant,
                "model_probability": round(float(probability), 6),
                "model_threshold": round(float(threshold), 6),
                "rank_score": round(float(probability) * 100, 6),
            }
    return None


def calibrate_touch_threshold(
    prefix_groups: Iterable[Sequence[Mapping[str, object]]],
    model: TouchModelFit,
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = CALIBRATION_THRESHOLDS,
    minimum_signal_count: int = MINIMUM_CALIBRATION_SIGNALS,
) -> TouchThresholdSelection:
    """Select a threshold by stock-day F0.5 without reading later dates."""

    ordered_thresholds = tuple(sorted({round(float(value), 6) for value in thresholds}))
    counters = {
        threshold: {"prediction_count": 0, "true_positive_count": 0}
        for threshold in ordered_thresholds
    }
    eligible_positive_count = 0
    for rows in prefix_groups:
        signal_date = _group_signal_date(rows)
        if signal_date not in calibration_dates:
            continue
        outcome = touch_candidate_outcome(rows, model.variant)
        if outcome["eligible"] is not True:
            continue
        eligible_positive_count += int(outcome["touched"] is True)
        candidates, probabilities = _scored_candidates(rows, model)
        for threshold in ordered_thresholds:
            signal_index = next(
                (
                    index
                    for index, probability in enumerate(probabilities)
                    if probability >= threshold
                ),
                None,
            )
            if signal_index is None:
                continue
            counters[threshold]["prediction_count"] += 1
            counters[threshold]["true_positive_count"] += int(
                candidates[signal_index].get("later_touch") is True
            )

    metrics = tuple(
        _threshold_metrics(
            threshold,
            counters[threshold],
            eligible_positive_count=eligible_positive_count,
            minimum_signal_count=minimum_signal_count,
        )
        for threshold in ordered_thresholds
    )
    eligible = [row for row in metrics if row["sample_qualified"] is True]
    selected = max(eligible, key=_threshold_sort_key) if eligible else None
    return TouchThresholdSelection(
        status="ready" if selected is not None else "blocked_by_calibration_sample",
        threshold=float(selected["threshold"]) if selected is not None else None,
        minimum_signal_count=max(int(minimum_signal_count), 1),
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def touch_candidate_outcome(
    rows: Sequence[Mapping[str, object]],
    variant: str,
) -> dict[str, bool]:
    """Return whether one stock-day is model-eligible and later touches."""

    eligible_rows = [row for row in rows if _candidate_vector(row, variant) is not None]
    return {
        "eligible": bool(eligible_rows),
        "touched": any(row.get("later_touch") is True for row in eligible_rows),
    }


def _first_later_touch_index(
    bars: Sequence[Mapping[str, object]],
    *,
    current_index: int | None,
    limit_price: float | None,
) -> int | None:
    if current_index is None or limit_price is None:
        return None
    for index in range(current_index + 1, len(bars)):
        high = _number(bars[index].get("high_price"))
        if high is not None and high >= limit_price - 0.001:
            return index
    return None


def _scored_candidates(
    rows: Sequence[Mapping[str, object]],
    model: TouchModelFit,
) -> tuple[list[dict[str, object]], np.ndarray]:
    if model.status != "ready" or model.pipeline is None:
        return [], np.empty(0, dtype=float)
    candidates: list[dict[str, object]] = []
    vectors: list[list[float]] = []
    for raw in sorted(rows, key=lambda row: str(row.get("signal_at") or "")):
        vector = _candidate_vector(raw, model.variant)
        if vector is None:
            continue
        candidates.append(dict(raw))
        vectors.append(vector)
    if not vectors:
        return [], np.empty(0, dtype=float)
    matrix: Any = np.asarray(vectors, dtype=float)
    if model.estimator_kind == "lightgbm":
        import pandas as pd

        matrix = pd.DataFrame(matrix, columns=model.feature_names)
    probabilities = model.pipeline.predict_proba(matrix)[:, 1]
    return candidates, probabilities


def _candidate_vector(
    row: Mapping[str, object],
    variant: str,
) -> list[float] | None:
    feature_names = _variant_feature_names(variant)
    features = row.get("features")
    features = features if isinstance(features, Mapping) else {}
    gain = _number(features.get("gain_pct"))
    if not (
        row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
    ):
        return None
    if _variant_has_history_gate(variant) and not _passes_history_gate(features):
        return None
    values = [_number(features.get(name)) for name in feature_names]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


def _passes_history_gate(features: Mapping[str, object]) -> bool:
    samples = _number(features.get("stock_d1_sample_count"))
    combined_rate = _number(features.get("stock_gene_combined_win_rate"))
    return bool(
        samples is not None
        and samples >= MINIMUM_D1_SAMPLES
        and combined_rate is not None
        and combined_rate >= MINIMUM_COMBINED_RATE
    )


def _variant_feature_names(variant: str) -> tuple[str, ...]:
    _validate_variant(variant)
    if variant.startswith("history_gate_full_"):
        return (*FEATURE_NAMES, *HISTORY_FEATURE_NAMES)
    return FEATURE_NAMES


def _variant_has_history_gate(variant: str) -> bool:
    _validate_variant(variant)
    return variant.startswith("history_gate_")


def _variant_estimator_kind(variant: str) -> str:
    _validate_variant(variant)
    return "lightgbm" if variant.endswith("_lightgbm") else "logistic"


def _validate_variant(variant: str) -> None:
    if variant not in MODEL_VARIANTS:
        raise ValueError(f"unsupported touch model variant: {variant}")


def _fit_logistic(
    matrix: np.ndarray,
    targets: np.ndarray,
    feature_names: Sequence[str],
) -> tuple[Any, dict[str, float], float]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=0,
                ),
            ),
        ]
    )
    pipeline.fit(matrix, targets)
    logistic = pipeline.named_steps["logistic"]
    importance = {
        name: round(float(value), 12)
        for name, value in zip(feature_names, logistic.coef_[0], strict=True)
    }
    return pipeline, importance, round(float(logistic.intercept_[0]), 12)


def _fit_lightgbm(
    matrix: np.ndarray,
    targets: np.ndarray,
    feature_names: Sequence[str],
) -> tuple[Any, dict[str, float], None]:
    from lightgbm import LGBMClassifier
    import pandas as pd

    model = LGBMClassifier(
        n_estimators=120,
        learning_rate=0.04,
        num_leaves=7,
        max_depth=3,
        min_child_samples=max(20, min(80, len(matrix) // 200)),
        subsample=0.85,
        subsample_freq=1,
        colsample_bytree=0.85,
        reg_alpha=0.2,
        reg_lambda=2.0,
        class_weight="balanced",
        random_state=0,
        n_jobs=1,
        verbosity=-1,
        deterministic=True,
        force_col_wise=True,
    )
    model.fit(pd.DataFrame(matrix, columns=feature_names), targets)
    importance = {
        name: round(float(value), 12)
        for name, value in zip(feature_names, model.feature_importances_, strict=True)
    }
    return model, importance, None


def _training_fingerprint(
    variant: str,
    matrix: np.ndarray,
    targets: np.ndarray,
    fit_dates: Sequence[str],
) -> str:
    digest = sha256()
    digest.update(variant.encode("ascii"))
    digest.update("|".join(fit_dates).encode("ascii"))
    digest.update(np.ascontiguousarray(matrix, dtype="<f8").tobytes())
    digest.update(np.ascontiguousarray(targets, dtype="<i8").tobytes())
    return digest.hexdigest()


def _threshold_metrics(
    threshold: float,
    counts: Mapping[str, int],
    *,
    eligible_positive_count: int,
    minimum_signal_count: int,
) -> dict[str, object]:
    predictions = int(counts["prediction_count"])
    true_positives = int(counts["true_positive_count"])
    precision = true_positives / predictions if predictions else 0.0
    recall = true_positives / eligible_positive_count if eligible_positive_count else 0.0
    beta_squared = 0.25
    denominator = beta_squared * precision + recall
    f_half = (
        (1 + beta_squared) * precision * recall / denominator if denominator else 0.0
    )
    return {
        "threshold": threshold,
        "prediction_count": predictions,
        "true_positive_count": true_positives,
        "false_positive_count": predictions - true_positives,
        "eligible_positive_count": eligible_positive_count,
        "precision_pct": round(precision * 100, 4),
        "recall_pct": round(recall * 100, 4),
        "f0_5": round(f_half, 6),
        "sample_qualified": predictions >= max(int(minimum_signal_count), 1),
    }


def _threshold_sort_key(row: Mapping[str, object]) -> tuple[float, float, int, float]:
    return (
        float(row.get("f0_5") or 0.0),
        float(row.get("precision_pct") or 0.0),
        int(row.get("prediction_count") or 0),
        float(row.get("threshold") or 0.0),
    )


def _group_signal_date(rows: Sequence[Mapping[str, object]]) -> date | None:
    return _as_date(rows[0].get("signal_date")) if rows else None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
