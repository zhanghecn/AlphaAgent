"""Frozen transaction-flow extension of the v3 pre-board trigger model."""

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
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    ACTION_SCORE_FIELD as V3_ACTION_SCORE_FIELD,
    ACTION_TARGET_FIELD,
    DEFAULT_ACTION_THRESHOLDS,
    JointThresholdSelection,
    calibrate_joint_threshold,
)
from alphaagent.server.services.limit_up.preboard_transaction_features import (
    TRANSACTION_FEATURE_NAMES,
    TRANSACTION_FEATURE_VERSION,
)


TRANSACTION_TRIGGER_MODEL_VERSION = "limit-up-preboard-transaction-trigger-v4"
TRANSACTION_PREPARE_SCORE_FIELD = "transaction_prepare_probability"
TRANSACTION_ACTION_SCORE_FIELD = "transaction_action_probability"
TRANSACTION_TRIGGER_FEATURE_NAMES = (
    *COMPETING_FEATURE_NAMES,
    *TRANSACTION_FEATURE_NAMES,
)


@dataclass(frozen=True)
class TransactionTriggerModelFit:
    status: str
    pipeline: Any | None
    target_field: str
    feature_version: str
    transaction_feature_names: tuple[str, ...]
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
        vector = transaction_trigger_feature_vector(row)
        if self.pipeline is None or vector is None:
            return None
        return float(
            self.pipeline.predict_proba(np.asarray([vector], dtype=float))[0, 1]
        )


def transaction_trigger_feature_vector(
    row: Mapping[str, object],
) -> list[float] | None:
    """Return all 29 frozen features, failing closed on any transaction gap."""

    core = competing_feature_vector(row)
    transaction = row.get("transaction_features")
    if core is None or not isinstance(transaction, Mapping):
        return None
    flow = [_number(transaction.get(name)) for name in TRANSACTION_FEATURE_NAMES]
    if any(value is None for value in flow):
        return None
    return [*core, *(float(value) for value in flow if value is not None)]


def transaction_training_batch(
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
        vector = transaction_trigger_feature_vector(row)
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
        else np.empty((0, len(TRANSACTION_TRIGGER_FEATURE_NAMES)))
    )
    labels = np.asarray([item[1] for item in prepared], dtype=int)
    pairs = tuple(item[2] for item in prepared)
    weights = np.asarray(
        [1.0 / pair_counts[pair] for pair in pairs],
        dtype=float,
    )
    return matrix, labels, weights, pairs


def fit_transaction_trigger_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    target_field: str = ACTION_TARGET_FIELD,
) -> TransactionTriggerModelFit:
    """Fit the deterministic natural-prevalence Logistic v4 head."""

    matrix, labels, weights, pairs = transaction_training_batch(
        rows,
        allowed_dates=fit_dates,
        target_field=target_field,
    )
    common = {
        "target_field": target_field,
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "transaction_feature_names": tuple(TRANSACTION_FEATURE_NAMES),
        "training_row_count": len(labels),
        "training_pair_count": len(set(pairs)),
        "class_counts": {
            str(label): int(count)
            for label, count in sorted(Counter(labels.tolist()).items())
        },
        "fit_dates": tuple(value.isoformat() for value in sorted(fit_dates)),
    }
    if len(labels) < 2 or len(set(labels.tolist())) < 2:
        return TransactionTriggerModelFit(
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
    return TransactionTriggerModelFit(
        status="ready",
        pipeline=pipeline,
        scaler_mean_by_feature=means,
        scaler_scale_by_feature=scales,
        coefficient_by_feature=coefficients,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def score_transaction_trigger_rows(
    rows: Sequence[Mapping[str, object]],
    model: TransactionTriggerModelFit,
    *,
    score_field: str = TRANSACTION_ACTION_SCORE_FIELD,
) -> list[dict[str, object]]:
    """Score every finite row in one sklearn matrix call."""

    if model.status != "ready" or model.pipeline is None:
        return []
    prepared = [
        (dict(row), vector)
        for row in rows
        if (vector := transaction_trigger_feature_vector(row)) is not None
    ]
    if not prepared:
        return []
    matrix = np.asarray([vector for _, vector in prepared], dtype=float)
    probabilities = model.pipeline.predict_proba(matrix)[:, 1]
    return [
        {**row, score_field: round(float(probability), 8)}
        for (row, _), probability in zip(prepared, probabilities, strict=True)
    ]


def calibrate_transaction_threshold(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = DEFAULT_ACTION_THRESHOLDS,
    minimum_selection_count: int = 10,
    confirmation_minutes: int = 2,
    max_daily_actions: int = 2,
) -> JointThresholdSelection:
    """Freeze a v4 threshold using calibration dates and the existing policy."""

    aliased = [
        {
            **dict(row),
            V3_ACTION_SCORE_FIELD: row.get(TRANSACTION_ACTION_SCORE_FIELD),
        }
        for row in rows
    ]
    return calibrate_joint_threshold(
        aliased,
        calibration_dates=calibration_dates,
        thresholds=thresholds,
        minimum_selection_count=minimum_selection_count,
        confirmation_minutes=confirmation_minutes,
        max_daily_actions=max_daily_actions,
    )


def score_frozen_transaction_probability(
    row: Mapping[str, object],
    model: TransactionTriggerModelFit,
) -> float | None:
    """Reconstruct one probability from archived numeric parameters."""

    vector = transaction_trigger_feature_vector(row)
    if vector is None or model.intercept is None:
        return None
    logit = float(model.intercept)
    for field, value in zip(
        TRANSACTION_TRIGGER_FEATURE_NAMES,
        vector,
        strict=True,
    ):
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


def _feature_mapping(values: Sequence[object]) -> dict[str, float]:
    return {
        field: _canonical_float(value)
        for field, value in zip(
            TRANSACTION_TRIGGER_FEATURE_NAMES,
            values,
            strict=True,
        )
    }


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
        "model_version": TRANSACTION_TRIGGER_MODEL_VERSION,
        "feature_version": TRANSACTION_FEATURE_VERSION,
        "features": list(TRANSACTION_TRIGGER_FEATURE_NAMES),
        "transaction_features": list(TRANSACTION_FEATURE_NAMES),
        "fit_dates": list(fit_dates),
        "target_field": target_field,
        "scaler_mean_by_feature": dict(scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(scaler_scale_by_feature),
        "coefficient_by_feature": dict(coefficient_by_feature),
        "intercept": intercept,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


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


def _canonical_float(value: object) -> float:
    rounded = round(float(value), 10)
    return 0.0 if rounded == 0 else rounded
