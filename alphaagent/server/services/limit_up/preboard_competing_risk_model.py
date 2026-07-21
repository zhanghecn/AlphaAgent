"""Causal two-stage competing-risk model for pre-board action timing."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import exp, isfinite, log1p
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_hazard_model import (
    HAZARD_FEATURE_NAMES,
    attach_hazard_targets,
)
from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    trading_minutes_between,
)


IDENTITY_TARGET_FIELD = "formal_baseline_identity"
TIMING_TARGET_FIELD = "formal_touch_within_3m"
ACTION_SCORE_FIELD = "action_score"
DEFAULT_ACTION_THRESHOLDS = tuple(
    round(value / 100, 2) for value in range(10, 91, 5)
)
_COMPETITION_FIELDS = (
    "history_sample_count_log1p",
    "history_combined_rate",
    "gain_strength_pct",
    "return_3m_strength_pct",
    "prior_30m_floor_strength_pct",
    "rank_strength_pct",
    "active_candidate_count_log1p",
)
COMPETING_FEATURE_NAMES = (
    *HAZARD_FEATURE_NAMES,
    "rank_score",
    *_COMPETITION_FIELDS,
)


@dataclass(frozen=True)
class CompetingRiskModelFit:
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
        if self.pipeline is None:
            return None
        vector = competing_feature_vector(row)
        if vector is None:
            return None
        matrix = np.asarray([vector], dtype=float)
        return float(self.pipeline.predict_proba(matrix)[0, 1])


@dataclass(frozen=True)
class CompetingThresholdSelection:
    status: str
    threshold: float | None
    calibration_dates: tuple[str, ...]
    minimum_selection_count: int
    selected_metrics: dict[str, float | int | None]
    metrics_by_threshold: tuple[dict[str, float | int | None], ...]


def attach_competing_risk_targets(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach formal identity and three-minute timing labels."""

    formal_pairs = {
        _row_pair(order)
        for order in formal_orders
        if str(order.get("lane") or "") == "first_board"
    }
    labeled = attach_hazard_targets(rows, formal_orders, horizons=(3,))
    return [
        {
            **row,
            IDENTITY_TARGET_FIELD: _row_pair(row) in formal_pairs,
        }
        for row in labeled
    ]


def enrich_same_minute_competition(
    rows: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Add features computed only from candidates visible in the same minute."""

    result = [dict(row) for row in rows]
    groups: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(result):
        if _is_model_observation(row):
            groups[_minute_key(row)].append(index)

    for indices in groups.values():
        group_rows = [result[index] for index in indices]
        strengths = {
            "gain_strength_pct": _strength_percentiles(
                group_rows,
                "gain_pct",
            ),
            "return_3m_strength_pct": _strength_percentiles(
                group_rows,
                "return_3m_pct",
            ),
            "prior_30m_floor_strength_pct": _strength_percentiles(
                group_rows,
                "prior_30m_floor_pct",
            ),
            "rank_strength_pct": _strength_percentiles(
                group_rows,
                "rank_score",
            ),
        }
        candidate_count = len(group_rows)
        for offset, index in enumerate(indices):
            row = result[index]
            sample_count = _number(row.get("profitability_gate_sample_count"))
            combined_rate = _number(row.get("profitability_gate_combined_rate"))
            row["competing_features"] = {
                "history_sample_count_log1p": (
                    log1p(max(sample_count, 0.0))
                    if sample_count is not None
                    else None
                ),
                "history_combined_rate": combined_rate,
                "active_candidate_count_log1p": log1p(candidate_count),
                **{
                    field: values[offset]
                    for field, values in strengths.items()
                },
            }
    return result


def competing_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    """Return the frozen live-reproducible competing-risk vector."""

    values = [_feature_value(row, field) for field in COMPETING_FEATURE_NAMES]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


def competing_training_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
    target_field: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[tuple[str, str], ...]]:
    """Build finite observations with total weight one per stock-day."""

    prepared: list[tuple[list[float], int, tuple[str, str]]] = []
    pair_counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        vector = competing_feature_vector(row)
        pair = _row_pair(row)
        if (
            signal_date not in allowed_dates
            or not all(pair)
            or not _is_model_observation(row)
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


def fit_competing_risk_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    target_field: str,
) -> CompetingRiskModelFit:
    """Fit one deterministic pair-balanced Logistic head."""

    matrix, labels, weights, pairs = competing_training_batch(
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
        return CompetingRiskModelFit(
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
                    class_weight="balanced",
                    max_iter=2_000,
                    random_state=0,
                ),
            ),
        ]
    )
    pipeline.fit(matrix, labels, logistic__sample_weight=weights)
    scaler = pipeline.named_steps["scaler"]
    logistic = pipeline.named_steps["logistic"]
    scaler_mean_by_feature = {
        field: round(float(value), 10)
        for field, value in zip(
            COMPETING_FEATURE_NAMES,
            scaler.mean_,
            strict=True,
        )
    }
    scaler_scale_by_feature = {
        field: round(float(value), 10)
        for field, value in zip(
            COMPETING_FEATURE_NAMES,
            scaler.scale_,
            strict=True,
        )
    }
    coefficients = {
        field: round(float(value), 10)
        for field, value in zip(
            COMPETING_FEATURE_NAMES,
            logistic.coef_[0],
            strict=True,
        )
    }
    intercept = round(float(logistic.intercept_[0]), 10)
    fingerprint = _model_fingerprint(
        target_field=target_field,
        fit_dates=common["fit_dates"],
        scaler_mean_by_feature=scaler_mean_by_feature,
        scaler_scale_by_feature=scaler_scale_by_feature,
        coefficients=coefficients,
        intercept=intercept,
    )
    return CompetingRiskModelFit(
        status="ready",
        pipeline=pipeline,
        scaler_mean_by_feature=scaler_mean_by_feature,
        scaler_scale_by_feature=scaler_scale_by_feature,
        coefficient_by_feature=coefficients,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def score_competing_risk_rows(
    rows: Sequence[Mapping[str, object]],
    identity_model: Any,
    timing_model: Any,
) -> list[dict[str, object]]:
    """Score observable rows by identity probability times timing probability."""

    if (
        str(getattr(identity_model, "status", "")) != "ready"
        or str(getattr(timing_model, "status", "")) != "ready"
    ):
        return []
    result: list[dict[str, object]] = []
    for raw in rows:
        if not _is_model_observation(raw):
            continue
        identity_probability = identity_model.probability(raw)
        timing_probability = timing_model.probability(raw)
        if not _finite_probability(identity_probability) or not _finite_probability(
            timing_probability
        ):
            continue
        identity_value = float(identity_probability)
        timing_value = float(timing_probability)
        result.append(
            {
                **dict(raw),
                "identity_probability": round(identity_value, 8),
                "timing_probability": round(timing_value, 8),
                ACTION_SCORE_FIELD: round(identity_value * timing_value, 8),
            }
        )
    return result


def score_frozen_competing_probability(
    row: Mapping[str, object],
    model: CompetingRiskModelFit,
) -> float | None:
    """Reconstruct one probability from the numeric parameters in the report."""

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


def select_confirmed_competing_signals(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    score_field: str = ACTION_SCORE_FIELD,
    confirmation_minutes: int = 2,
    max_daily_actions: int = 2,
) -> list[dict[str, object]]:
    """Select sustained same-minute leaders without future first-crossing lockout."""

    required_streak = max(int(confirmation_minutes), 1)
    daily_limit = max(int(max_daily_actions), 1)
    by_minute: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for raw in rows:
        if _is_model_observation(raw):
            by_minute[_minute_key(raw)].append(dict(raw))

    streaks: dict[tuple[str, str], int] = defaultdict(int)
    last_pass_time: dict[tuple[str, str], str] = {}
    selected_pairs: set[tuple[str, str]] = set()
    daily_counts: Counter[str] = Counter()
    selected: list[dict[str, object]] = []
    for minute_key in sorted(by_minute):
        trade_date_text = minute_key[0]
        confirmed: list[dict[str, object]] = []
        for row in by_minute[minute_key]:
            pair = _row_pair(row)
            score = _number(row.get(score_field))
            current_time = str(row.get("signal_time") or "")
            if score is None or score < threshold:
                streaks[pair] = 0
                last_pass_time.pop(pair, None)
                continue
            previous_time = last_pass_time.get(pair)
            consecutive = (
                previous_time is not None
                and trading_minutes_between(previous_time, current_time) == 1.0
            )
            streaks[pair] = streaks[pair] + 1 if consecutive else 1
            last_pass_time[pair] = current_time
            if streaks[pair] >= required_streak and pair not in selected_pairs:
                confirmed.append(row)

        remaining = daily_limit - daily_counts[trade_date_text]
        if remaining <= 0:
            continue
        choices = sorted(confirmed, key=lambda row: _ranking_key(row, score_field))[
            :remaining
        ]
        for row in choices:
            pair = _row_pair(row)
            selected_pairs.add(pair)
            daily_counts[trade_date_text] += 1
            selected.append(row)
    return selected


def calibrate_competing_threshold(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = DEFAULT_ACTION_THRESHOLDS,
    minimum_selection_count: int = 10,
) -> CompetingThresholdSelection:
    """Freeze the confirmed-policy threshold using calibration dates only."""

    calibration_rows = [
        dict(row)
        for row in rows
        if _as_date(row.get("signal_date")) in calibration_dates
    ]
    reachable_pairs = {
        _row_pair(row)
        for row in calibration_rows
        if row.get(TIMING_TARGET_FIELD) is True
        and competing_feature_vector(row) is not None
    }
    metrics = tuple(
        _threshold_metrics(
            calibration_rows,
            threshold=float(threshold),
            reachable_pairs=reachable_pairs,
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
            float(row["formal_identity_precision"] or 0.0),
            float(row["threshold"] or 0.0),
        ),
        default=None,
    )
    return CompetingThresholdSelection(
        status="ready" if selected is not None else "insufficient_calibration_signals",
        threshold=float(selected["threshold"]) if selected is not None else None,
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        minimum_selection_count=max(minimum_selection_count, 1),
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def _threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    reachable_pairs: set[tuple[str, str]],
) -> dict[str, float | int | None]:
    selected = select_confirmed_competing_signals(rows, threshold=threshold)
    horizon_true_pairs = {
        _row_pair(row)
        for row in selected
        if row.get(TIMING_TARGET_FIELD) is True
    }
    formal_true_pairs = {
        _row_pair(row)
        for row in selected
        if row.get(IDENTITY_TARGET_FIELD) is True
    }
    horizon_precision = _ratio(len(horizon_true_pairs), len(selected))
    reachable_recall = _ratio(len(horizon_true_pairs), len(reachable_pairs))
    return {
        "threshold": round(threshold, 4),
        "selection_count": len(selected),
        "horizon_true_positive_count": len(horizon_true_pairs),
        "formal_identity_true_positive_count": len(formal_true_pairs),
        "horizon_precision": horizon_precision,
        "formal_identity_precision": _ratio(len(formal_true_pairs), len(selected)),
        "reachable_recall": reachable_recall,
        "f0_5": _f_beta(horizon_precision, reachable_recall, beta=0.5),
    }


def _strength_percentiles(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> list[float | None]:
    values = [_feature_value(row, field) for row in rows]
    finite = sorted(value for value in values if value is not None)
    if not finite:
        return [None] * len(values)
    return [
        (
            sum(candidate <= value for candidate in finite) / len(finite)
            if value is not None
            else None
        )
        for value in values
    ]


def _model_fingerprint(
    *,
    target_field: str,
    fit_dates: Sequence[str],
    scaler_mean_by_feature: Mapping[str, float],
    scaler_scale_by_feature: Mapping[str, float],
    coefficients: Mapping[str, float],
    intercept: float,
) -> str:
    payload = {
        "target_field": target_field,
        "feature_names": COMPETING_FEATURE_NAMES,
        "fit_dates": tuple(fit_dates),
        "scaler_mean_by_feature": dict(scaler_mean_by_feature),
        "scaler_scale_by_feature": dict(scaler_scale_by_feature),
        "coefficient_by_feature": dict(coefficients),
        "intercept": intercept,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()[:16]


def _ranking_key(
    row: Mapping[str, object],
    score_field: str,
) -> tuple[float, float, float, str]:
    return (
        -(_number(row.get(score_field)) or 0.0),
        -(_feature_value(row, "rank_score") or 0.0),
        -(_feature_value(row, "entry_quality_score") or 0.0),
        str(row.get("vt_symbol") or ""),
    )


def _is_model_observation(row: Mapping[str, object]) -> bool:
    gain = _feature_value(row, "gain_pct")
    return bool(
        row.get("shared_strategy_passed") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
    )


def _feature_value(row: Mapping[str, object], field: str) -> float | None:
    direct = _number(row.get(field))
    if direct is not None:
        return direct
    for container_name in (
        "features",
        "ignition_features",
        "competing_features",
    ):
        container = row.get(container_name)
        if not isinstance(container, Mapping):
            continue
        value = _number(container.get(field))
        if value is not None:
            return value
    return None


def _minute_key(row: Mapping[str, object]) -> tuple[str, str]:
    return _date_text(row), str(row.get("signal_time") or "")[:5]


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return str(row.get("vt_symbol") or ""), _date_text(row)


def _date_text(row: Mapping[str, object]) -> str:
    return str(row.get("signal_date") or row.get("entry_date") or "")[:10]


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _finite_probability(value: object) -> bool:
    parsed = _number(value)
    return parsed is not None and 0.0 <= parsed <= 1.0


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 8) if denominator else None


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
    return (
        round((1 + beta_squared) * precision * recall / denominator, 8)
        if denominator
        else 0.0
    )
