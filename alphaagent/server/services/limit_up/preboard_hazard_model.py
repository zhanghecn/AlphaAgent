"""Causal short-horizon hazard model for the formal first-board baseline."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
from math import isfinite
from typing import Any

import numpy as np

from alphaagent.server.services.limit_up.preboard_reverse_profile import (
    trading_minutes_between,
)


HAZARD_HORIZONS = (1, 3, 5)
HAZARD_FEATURE_NAMES = (
    "gain_pct",
    "return_1m_pct",
    "return_3m_pct",
    "return_5m_pct",
    "prior_30m_floor_pct",
    "session_drawdown_pct",
    "turnover_acceleration_1m",
    "volume_ratio_5m",
    "bar_close_location",
    "support_score",
    "entry_quality_score",
    "minute_of_window",
)
DEFAULT_THRESHOLDS = tuple(round(value / 100, 2) for value in range(50, 96, 5))


@dataclass(frozen=True)
class HazardModelFit:
    status: str
    pipeline: Any | None
    target_field: str
    training_row_count: int
    training_pair_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    coefficient_by_feature: dict[str, float]
    intercept: float | None
    fingerprint: str | None

    def probability(self, row: Mapping[str, object]) -> float | None:
        if self.pipeline is None:
            return None
        vector = hazard_feature_vector(row)
        if vector is None:
            return None
        return float(self.pipeline.predict_proba(np.asarray([vector]))[0, 1])


@dataclass(frozen=True)
class HazardThresholdSelection:
    status: str
    threshold: float | None
    target_field: str
    calibration_dates: tuple[str, ...]
    minimum_selection_count: int
    selected_metrics: dict[str, float | int | None]
    metrics_by_threshold: tuple[dict[str, float | int | None], ...]


def attach_hazard_targets(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
    *,
    horizons: Sequence[int] = HAZARD_HORIZONS,
) -> list[dict[str, object]]:
    """Attach future formal-touch labels without changing observable fields."""

    normalized_horizons = tuple(sorted({max(int(value), 1) for value in horizons}))
    touch_times = _formal_touch_times(formal_orders)
    result: list[dict[str, object]] = []
    for raw in rows:
        row = dict(raw)
        touch_time = touch_times.get(_row_pair(row))
        lead = (
            trading_minutes_between(row.get("signal_time"), touch_time)
            if touch_time
            else None
        )
        row["formal_touch_lead_minutes"] = lead
        row["formal_touch_time"] = touch_time
        for horizon in normalized_horizons:
            row[f"formal_touch_within_{horizon}m"] = bool(
                lead is not None and 0 < lead <= horizon
            )
        result.append(row)
    return result


def hazard_feature_vector(row: Mapping[str, object]) -> list[float] | None:
    """Return the frozen live-reproducible hazard vector."""

    values = [_feature_value(row, field) for field in HAZARD_FEATURE_NAMES]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


def hazard_training_batch(
    rows: Sequence[Mapping[str, object]],
    *,
    allowed_dates: set[date],
    target_field: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, tuple[tuple[str, date], ...]]:
    """Build finite rows with total weight one per stock-day."""

    prepared: list[tuple[list[float], int, tuple[str, date]]] = []
    pair_counts: Counter[tuple[str, date]] = Counter()
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        vector = hazard_feature_vector(row)
        pair = (str(row.get("vt_symbol") or ""), signal_date or date.min)
        if (
            signal_date not in allowed_dates
            or not pair[0]
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
        else np.empty((0, len(HAZARD_FEATURE_NAMES)))
    )
    labels = np.asarray([item[1] for item in prepared], dtype=int)
    pairs = tuple(item[2] for item in prepared)
    weights = np.asarray(
        [1.0 / pair_counts[pair] for pair in pairs],
        dtype=float,
    )
    return matrix, labels, weights, pairs


def fit_hazard_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    target_field: str,
) -> HazardModelFit:
    """Fit one deterministic pair-balanced logistic hazard model."""

    matrix, labels, weights, pairs = hazard_training_batch(
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
        return HazardModelFit(
            status="insufficient_training_classes",
            pipeline=None,
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
    logistic = pipeline.named_steps["logistic"]
    coefficient_by_feature = {
        field: round(float(value), 10)
        for field, value in zip(
            HAZARD_FEATURE_NAMES,
            logistic.coef_[0],
            strict=True,
        )
    }
    intercept = round(float(logistic.intercept_[0]), 10)
    fingerprint = _model_fingerprint(
        target_field=target_field,
        fit_dates=common["fit_dates"],
        coefficient_by_feature=coefficient_by_feature,
        intercept=intercept,
    )
    return HazardModelFit(
        status="ready",
        pipeline=pipeline,
        coefficient_by_feature=coefficient_by_feature,
        intercept=intercept,
        fingerprint=fingerprint,
        **common,
    )


def _model_fingerprint(
    *,
    target_field: str,
    fit_dates: Sequence[str],
    coefficient_by_feature: Mapping[str, float],
    intercept: float,
) -> str:
    payload = {
        "target_field": target_field,
        "feature_names": HAZARD_FEATURE_NAMES,
        "fit_dates": tuple(fit_dates),
        "coefficient_by_feature": dict(coefficient_by_feature),
        "intercept": intercept,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()[:16]


def calibrate_hazard_threshold(
    rows: Sequence[Mapping[str, object]],
    model: Any,
    *,
    calibration_dates: set[date],
    target_field: str,
    thresholds: Sequence[float] = DEFAULT_THRESHOLDS,
    minimum_selection_count: int = 10,
) -> HazardThresholdSelection:
    """Freeze a threshold after same-minute Top2 competition."""

    scored: list[dict[str, object]] = []
    for raw in rows:
        signal_date = _as_date(raw.get("signal_date"))
        if signal_date not in calibration_dates or not _is_model_observation(raw):
            continue
        probability = model.probability(raw)
        if probability is None or not isfinite(probability):
            continue
        scored.append({**dict(raw), "hazard_probability": float(probability)})

    reachable_pairs = {
        _row_pair(row) for row in scored if row.get(target_field) is True
    }
    metrics = tuple(
        _threshold_metrics(
            scored,
            threshold=float(threshold),
            target_field=target_field,
            reachable_pairs=reachable_pairs,
        )
        for threshold in thresholds
    )
    qualified = [
        row
        for row in metrics
        if int(row["selection_count"] or 0) >= minimum_selection_count
    ]
    selected = max(
        qualified,
        key=lambda row: (
            float(row["f0_5"] or 0.0),
            float(row["precision"] or 0.0),
            float(row["threshold"] or 0.0),
        ),
        default=None,
    )
    return HazardThresholdSelection(
        status="ready" if selected is not None else "insufficient_calibration_signals",
        threshold=float(selected["threshold"]) if selected is not None else None,
        target_field=target_field,
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        minimum_selection_count=minimum_selection_count,
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def select_top2_first_crossings(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    probability_field: str = "hazard_probability",
) -> list[dict[str, object]]:
    """Freeze each stock-day's first crossing, then keep same-minute Top2."""

    grouped_pairs: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        probability = _number(row.get(probability_field))
        if probability is not None and probability >= threshold:
            grouped_pairs[_row_pair(row)].append(row)
    first_crossings = [
        dict(min(pair_rows, key=_chronological_key))
        for pair_rows in grouped_pairs.values()
        if pair_rows
    ]
    by_minute: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in first_crossings:
        key = (_row_date_text(row), str(row.get("signal_time") or "")[:5])
        by_minute[key].append(row)
    selected: list[dict[str, object]] = []
    for key in sorted(by_minute):
        selected.extend(
            sorted(
                by_minute[key],
                key=lambda row: (
                    -(_number(row.get(probability_field)) or 0.0),
                    -(_feature_value(row, "entry_quality_score") or 0.0),
                    -(_feature_value(row, "rank_score") or 0.0),
                    str(row.get("vt_symbol") or ""),
                ),
            )[:2]
        )
    return selected


def _threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    target_field: str,
    reachable_pairs: set[tuple[str, str]],
) -> dict[str, float | int | None]:
    selected = select_top2_first_crossings(rows, threshold=threshold)
    true_positive_pairs = {
        _row_pair(row) for row in selected if row.get(target_field) is True
    }
    precision = _ratio(len(true_positive_pairs), len(selected))
    recall = _ratio(len(true_positive_pairs), len(reachable_pairs))
    return {
        "threshold": round(threshold, 4),
        "selection_count": len(selected),
        "true_positive_count": len(true_positive_pairs),
        "false_positive_count": len(selected) - len(true_positive_pairs),
        "reachable_positive_count": len(reachable_pairs),
        "precision": precision,
        "reachable_recall": recall,
        "f0_5": _f_beta(precision, recall, beta=0.5),
    }


def _formal_touch_times(
    formal_orders: Sequence[Mapping[str, object]],
) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for order in formal_orders:
        if str(order.get("lane") or "") != "first_board":
            continue
        pair = _row_pair(order)
        touch_time = str(order.get("buy_time") or order.get("signal_time") or "")
        if not all(pair) or not touch_time:
            continue
        current = result.get(pair)
        if current is None or touch_time < current:
            result[pair] = touch_time
    return result


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
    for container_name in ("features", "ignition_features"):
        container = row.get(container_name)
        if isinstance(container, Mapping):
            value = _number(container.get(field))
            if value is not None:
                return value
    return None


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return str(row.get("vt_symbol") or ""), _row_date_text(row)


def _row_date_text(row: Mapping[str, object]) -> str:
    return str(row.get("signal_date") or row.get("entry_date") or "")[:10]


def _chronological_key(row: Mapping[str, object]) -> tuple[str, str, str]:
    return (
        _row_date_text(row),
        str(row.get("signal_time") or row.get("signal_at") or ""),
        str(row.get("vt_symbol") or ""),
    )


def _as_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
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
