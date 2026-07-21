"""Causal quality-gated prediction of a D-day final first-board seal."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_momentum import (
    SEAL_MODEL_FEATURE_NAMES,
)


PRIMARY_ALGORITHM = "quality_gated_seal_logistic"
MINIMUM_D1_SAMPLES = 5
MINIMUM_COMBINED_RATE = 30.0
CALIBRATION_THRESHOLDS = tuple(round(0.50 + index * 0.05, 2) for index in range(10))
MINIMUM_CALIBRATION_SIGNALS = 30


@dataclass(frozen=True)
class SealModelFit:
    """Fitted seal classifier and its reproducible training fingerprint."""

    status: str
    pipeline: Any | None
    training_row_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    coefficient_by_feature: dict[str, float]
    intercept: float | None


@dataclass(frozen=True)
class SealThresholdSelection:
    """Threshold selected only from the fixed calibration sessions."""

    status: str
    threshold: float | None
    minimum_signal_count: int
    calibration_dates: tuple[str, ...]
    selected_metrics: dict[str, object]
    metrics_by_threshold: tuple[dict[str, object], ...]


def fit_quality_gated_seal_model(
    prefix_rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
) -> SealModelFit:
    """Fit a final-seal classifier without consulting D+1 outcome fields."""

    vectors: list[list[float]] = []
    targets: list[int] = []
    used_dates: set[date] = set()
    for row in prefix_rows:
        signal_date = _as_date(row.get("signal_date"))
        vector = _seal_feature_vector(row)
        if signal_date not in fit_dates or vector is None:
            continue
        vectors.append(vector)
        targets.append(int(bool(row.get("sealed_limit"))))
        used_dates.add(signal_date)
    matrix = (
        np.asarray(vectors, dtype=float)
        if vectors
        else np.empty((0, len(SEAL_MODEL_FEATURE_NAMES)))
    )
    return fit_quality_gated_seal_arrays(
        matrix,
        np.asarray(targets, dtype=int),
        fit_dates=used_dates,
    )


def fit_quality_gated_seal_arrays(
    matrix: np.ndarray,
    targets: np.ndarray,
    *,
    fit_dates: set[date],
) -> SealModelFit:
    """Fit the fixed logistic model from already filtered causal arrays."""

    counts = Counter(int(value) for value in targets.tolist())
    class_counts = {"negative": counts.get(0, 0), "positive": counts.get(1, 0)}
    date_texts = tuple(value.isoformat() for value in sorted(fit_dates))
    if len(matrix) == 0 or len(counts) < 2:
        return SealModelFit(
            status="blocked_by_training_classes",
            pipeline=None,
            training_row_count=int(len(matrix)),
            class_counts=class_counts,
            fit_dates=date_texts,
            coefficient_by_feature={},
            intercept=None,
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
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=0,
                ),
            ),
        ]
    )
    pipeline.fit(matrix, targets)
    logistic = pipeline.named_steps["logistic"]
    coefficients = {
        name: round(float(value), 12)
        for name, value in zip(
            SEAL_MODEL_FEATURE_NAMES,
            logistic.coef_[0],
            strict=True,
        )
    }
    return SealModelFit(
        status="ready",
        pipeline=pipeline,
        training_row_count=int(len(matrix)),
        class_counts=class_counts,
        fit_dates=date_texts,
        coefficient_by_feature=coefficients,
        intercept=round(float(logistic.intercept_[0]), 12),
    )


def seal_model_training_batch(
    rows: Sequence[Mapping[str, object]],
) -> tuple[np.ndarray, np.ndarray]:
    """Return quality-gated feature vectors and final-seal targets."""

    vectors: list[list[float]] = []
    targets: list[int] = []
    for row in rows:
        vector = _seal_feature_vector(row)
        if vector is None:
            continue
        vectors.append(vector)
        targets.append(int(bool(row.get("sealed_limit"))))
    matrix = (
        np.asarray(vectors, dtype=float)
        if vectors
        else np.empty((0, len(SEAL_MODEL_FEATURE_NAMES)))
    )
    return matrix, np.asarray(targets, dtype=int)


def first_quality_gated_seal_signal(
    rows: Sequence[Mapping[str, object]],
    model: SealModelFit,
    *,
    threshold: float,
) -> dict[str, object] | None:
    """Return the first causal, fillable prefix crossing the seal threshold."""

    candidates, probabilities = _scored_candidates(rows, model)
    for row, probability in zip(candidates, probabilities, strict=True):
        if probability >= threshold:
            return {
                **row,
                "algorithm": PRIMARY_ALGORITHM,
                "model_probability": round(float(probability), 6),
                "model_threshold": round(float(threshold), 6),
                "rank_score": round(float(probability) * 100, 6),
            }
    return None


def calibrate_seal_threshold(
    prefix_groups: Iterable[Sequence[Mapping[str, object]]],
    model: SealModelFit,
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = CALIBRATION_THRESHOLDS,
    minimum_signal_count: int = MINIMUM_CALIBRATION_SIGNALS,
) -> SealThresholdSelection:
    """Choose a signal threshold from calibration dates by signal-level F0.5."""

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
        outcome = quality_candidate_outcome(rows)
        if outcome["eligible"] is not True:
            continue
        eligible_positive_count += int(outcome["sealed"] is True)
        candidates, probabilities = _scored_candidates(rows, model)
        for threshold in ordered_thresholds:
            predicted = any(probability >= threshold for probability in probabilities)
            if not predicted:
                continue
            counters[threshold]["prediction_count"] += 1
            counters[threshold]["true_positive_count"] += int(outcome["sealed"] is True)

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
    return SealThresholdSelection(
        status="ready" if selected is not None else "blocked_by_calibration_sample",
        threshold=float(selected["threshold"]) if selected is not None else None,
        minimum_signal_count=max(int(minimum_signal_count), 1),
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def quality_candidate_outcome(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, bool]:
    """Return one stock-day quality scope and final seal outcome."""

    eligible = any(_seal_feature_vector(row) is not None for row in rows)
    sealed = bool(rows and rows[0].get("sealed_limit"))
    return {"eligible": eligible, "sealed": sealed}


def _scored_candidates(
    rows: Sequence[Mapping[str, object]],
    model: SealModelFit,
) -> tuple[list[dict[str, object]], np.ndarray]:
    if model.status != "ready" or model.pipeline is None:
        return [], np.empty(0, dtype=float)
    candidates: list[dict[str, object]] = []
    vectors: list[list[float]] = []
    for raw in sorted(rows, key=lambda row: str(row.get("signal_at") or "")):
        vector = _seal_feature_vector(raw)
        if vector is None:
            continue
        candidates.append(dict(raw))
        vectors.append(vector)
    if not vectors:
        return [], np.empty(0, dtype=float)
    probabilities = model.pipeline.predict_proba(np.asarray(vectors, dtype=float))[:, 1]
    return candidates, probabilities


def _seal_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    features = row.get("features")
    features = features if isinstance(features, Mapping) else {}
    gain = _number(features.get("gain_pct"))
    samples = _number(features.get("stock_d1_sample_count"))
    combined_rate = _number(features.get("stock_gene_combined_win_rate"))
    if not (
        row.get("fillable") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
        and samples is not None
        and samples >= MINIMUM_D1_SAMPLES
        and combined_rate is not None
        and combined_rate >= MINIMUM_COMBINED_RATE
    ):
        return None
    values = [_number(features.get(name)) for name in SEAL_MODEL_FEATURE_NAMES]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


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
    recall = (
        true_positives / eligible_positive_count if eligible_positive_count else 0.0
    )
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
