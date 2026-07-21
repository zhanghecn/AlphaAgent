"""Causal prediction of current formal touch-baseline membership."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any

import numpy as np


BASELINE_MODEL_VERSION = "limit-up-baseline-precursor-v1"
BASELINE_THRESHOLDS = tuple(round(value / 100, 2) for value in range(50, 100, 5))
IGNITION_FEATURE_NAMES = (
    "gain_pct",
    "return_5m_pct",
    "return_15m_pct",
    "acceleration_pct",
    "distance_to_limit_pct",
    "session_drawdown_pct",
    "bar_close_location",
    "volume_ratio_30m",
    "amount_ratio_30m",
    "amount_acceleration_ratio",
    "support_score",
    "entry_quality_score",
    "rank_score",
)
PREFIX_FEATURE_NAMES = (
    "return_30m_pct",
    "prior_30m_range_pct",
    "prior_30m_floor_pct",
    "breakout_margin_pct",
    "opening_gap_pct",
    "minute_of_window",
)
BASELINE_FEATURE_NAMES = (*IGNITION_FEATURE_NAMES, *PREFIX_FEATURE_NAMES)


@dataclass(frozen=True)
class BaselineModelFit:
    status: str
    target_field: str
    pipeline: Any | None
    training_row_count: int
    training_pair_count: int
    class_counts: dict[str, int]
    fit_dates: tuple[str, ...]
    coefficient_by_feature: dict[str, float]
    intercept: float | None

    def probability(self, row: Mapping[str, object]) -> float | None:
        vector = baseline_candidate_vector(row)
        if self.pipeline is None or vector is None:
            return None
        matrix = np.asarray([vector], dtype=float)
        return float(self.pipeline.predict_proba(matrix)[0, 1])


@dataclass(frozen=True)
class BaselineThresholdSelection:
    status: str
    prepare_threshold: float | None
    action_threshold: float | None
    minimum_signal_count: int
    calibration_dates: tuple[str, ...]
    prepare_metrics: dict[str, object] | None
    action_metrics: dict[str, object] | None
    metrics_by_threshold: tuple[dict[str, object], ...]


def attach_formal_baseline_targets(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Return copied prefixes labeled by current formal first-board membership."""

    positive_pairs = formal_first_board_pairs(formal_orders)
    return [
        {
            **dict(row),
            "formal_touch_baseline_target": _row_pair(row) in positive_pairs,
        }
        for row in rows
    ]


def attach_baseline_account_targets(
    rows: Sequence[Mapping[str, object]],
    account_orders: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Label prefixes selected by filled first-board buys in the touch account."""

    filled_pairs = formal_first_board_pairs(
        [
            order
            for order in account_orders
            if str(order.get("side") or "") == "BUY"
            and str(order.get("status") or "") == "filled"
        ]
    )
    return [
        {
            **dict(row),
            "formal_touch_account_target": _row_pair(row) in filled_pairs,
        }
        for row in rows
    ]


def formal_first_board_pairs(
    formal_orders: Sequence[Mapping[str, object]],
) -> set[tuple[str, str]]:
    return {
        (
            str(order.get("vt_symbol") or ""),
            str(
                order.get("entry_date")
                or order.get("signal_date")
                or order.get("trade_date")
                or ""
            )[:10],
        )
        for order in formal_orders
        if str(order.get("lane") or order.get("board_lane") or "") == "first_board"
        and str(order.get("vt_symbol") or "")
        and str(
            order.get("entry_date")
            or order.get("signal_date")
            or order.get("trade_date")
            or ""
        )[:10]
    }


def baseline_reachability(
    rows: Sequence[Mapping[str, object]],
    formal_orders: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    formal_pairs = formal_first_board_pairs(formal_orders)
    reachable_pairs = {
        _row_pair(row)
        for row in rows
        if baseline_candidate_vector(row) is not None
    }
    reachable_formal = formal_pairs & reachable_pairs
    return {
        "formal_first_board_pair_count": len(formal_pairs),
        "reachable_formal_pair_count": len(reachable_formal),
        "unreachable_formal_pair_count": len(formal_pairs - reachable_formal),
        "model_eligible_pair_count": len(reachable_pairs),
        "reachable_formal_examples": sorted(reachable_formal)[:20],
        "unreachable_formal_examples": sorted(formal_pairs - reachable_formal)[:20],
    }


def baseline_candidate_vector(row: Mapping[str, object]) -> list[float] | None:
    ignition = row.get("ignition_features")
    ignition = ignition if isinstance(ignition, Mapping) else {}
    prefix = row.get("features")
    prefix = prefix if isinstance(prefix, Mapping) else {}
    gain = _number(ignition.get("gain_pct"))
    if not (
        row.get("shared_strategy_passed") is True
        and row.get("before_first_limit_touch") is True
        and gain is not None
        and gain >= 3.0
    ):
        return None
    values = [
        *(_number(ignition.get(name)) for name in IGNITION_FEATURE_NAMES),
        *(_number(prefix.get(name)) for name in PREFIX_FEATURE_NAMES),
    ]
    if any(value is None or not isfinite(value) for value in values):
        return None
    return [float(value) for value in values if value is not None]


def fit_baseline_model(
    rows: Sequence[Mapping[str, object]],
    *,
    fit_dates: set[date],
    target_field: str = "formal_touch_baseline_target",
) -> BaselineModelFit:
    selected: list[tuple[tuple[str, str], list[float], int]] = []
    used_dates: set[date] = set()
    pair_counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        signal_date = _as_date(row.get("signal_date"))
        vector = baseline_candidate_vector(row)
        pair = _row_pair(row)
        if signal_date not in fit_dates or vector is None or not all(pair):
            continue
        selected.append(
            (
                pair,
                vector,
                int(bool(row.get(target_field))),
            )
        )
        pair_counts[pair] += 1
        used_dates.add(signal_date)

    targets = [target for _, _, target in selected]
    counts = Counter(targets)
    metadata = {
        "status": "blocked_by_training_classes",
        "target_field": target_field,
        "pipeline": None,
        "training_row_count": len(selected),
        "training_pair_count": len(pair_counts),
        "class_counts": {
            "negative": int(counts.get(0, 0)),
            "positive": int(counts.get(1, 0)),
        },
        "fit_dates": tuple(value.isoformat() for value in sorted(used_dates)),
        "coefficient_by_feature": {},
        "intercept": None,
    }
    if not selected or len(counts) < 2:
        return BaselineModelFit(**metadata)

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
    matrix = np.asarray([vector for _, vector, _ in selected], dtype=float)
    labels = np.asarray(targets, dtype=int)
    weights = np.asarray(
        [1.0 / pair_counts[pair] for pair, _, _ in selected],
        dtype=float,
    )
    pipeline.fit(matrix, labels, logistic__sample_weight=weights)
    logistic = pipeline.named_steps["logistic"]
    return BaselineModelFit(
        **{
            **metadata,
            "status": "ready",
            "pipeline": pipeline,
            "coefficient_by_feature": {
                name: round(float(value), 12)
                for name, value in zip(
                    BASELINE_FEATURE_NAMES,
                    logistic.coef_[0],
                    strict=True,
                )
            },
            "intercept": round(float(logistic.intercept_[0]), 12),
        }
    )


def calibrate_baseline_thresholds(
    rows: Sequence[Mapping[str, object]],
    model: BaselineModelFit,
    *,
    calibration_dates: set[date],
    minimum_signal_count: int,
    target_field: str = "formal_touch_baseline_target",
    thresholds: Sequence[float] = BASELINE_THRESHOLDS,
) -> BaselineThresholdSelection:
    minimum = max(int(minimum_signal_count), 1)
    date_texts = tuple(value.isoformat() for value in sorted(calibration_dates))
    if model.status != "ready":
        return BaselineThresholdSelection(
            status="blocked_by_model",
            prepare_threshold=None,
            action_threshold=None,
            minimum_signal_count=minimum,
            calibration_dates=date_texts,
            prepare_metrics=None,
            action_metrics=None,
            metrics_by_threshold=(),
        )

    groups = _groups_for_dates(rows, calibration_dates)
    eligible_positives = sum(
        any(bool(row.get("formal_touch_baseline_target")) for row in group)
        if target_field == "formal_touch_baseline_target"
        else any(bool(row.get(target_field)) for row in group)
        for group in groups.values()
        if any(baseline_candidate_vector(row) is not None for row in group)
    )
    metrics = tuple(
        _threshold_metrics(
            groups.values(),
            model,
            threshold=float(threshold),
            eligible_positive_count=eligible_positives,
            minimum_signal_count=minimum,
            target_field=target_field,
        )
        for threshold in sorted({round(float(value), 6) for value in thresholds})
    )
    qualified = [row for row in metrics if row["sample_qualified"] is True]
    if not qualified:
        return BaselineThresholdSelection(
            status="blocked_by_calibration_sample",
            prepare_threshold=None,
            action_threshold=None,
            minimum_signal_count=minimum,
            calibration_dates=date_texts,
            prepare_metrics=None,
            action_metrics=None,
            metrics_by_threshold=metrics,
        )

    prepare = max(
        qualified,
        key=lambda row: (
            float(row["f1"]),
            float(row["recall_pct"]),
            float(row["precision_pct"]),
            int(row["prediction_count"]),
            -float(row["threshold"]),
        ),
    )
    action_candidates = [
        row
        for row in qualified
        if float(row["threshold"]) >= float(prepare["threshold"])
    ]
    action = max(
        action_candidates,
        key=lambda row: (
            float(row["f0_5"]),
            float(row["precision_pct"]),
            float(row["recall_pct"]),
            int(row["prediction_count"]),
            float(row["threshold"]),
        ),
    )
    return BaselineThresholdSelection(
        status="ready",
        prepare_threshold=float(prepare["threshold"]),
        action_threshold=float(action["threshold"]),
        minimum_signal_count=minimum,
        calibration_dates=date_texts,
        prepare_metrics=dict(prepare),
        action_metrics=dict(action),
        metrics_by_threshold=metrics,
    )


def first_baseline_signal(
    rows: Sequence[Mapping[str, object]],
    model: BaselineModelFit,
    *,
    threshold: float,
    stage: str,
) -> dict[str, object] | None:
    if stage not in {"prepare", "action"}:
        raise ValueError(f"unsupported baseline signal stage: {stage}")
    if model.status != "ready":
        return None
    for raw in sorted(rows, key=lambda row: str(row.get("signal_at") or "")):
        if baseline_candidate_vector(raw) is None:
            continue
        probability = model.probability(raw)
        if probability is None or probability < threshold:
            continue
        return {
            **dict(raw),
            "algorithm": "formal_touch_baseline_precursor",
            "baseline_state": f"baseline_{stage}",
            "model_probability": round(probability, 6),
            "model_threshold": round(float(threshold), 6),
            "rank_score": round(probability * 100, 6),
            "baseline_model_version": BASELINE_MODEL_VERSION,
        }
    return None


def _threshold_metrics(
    groups: Sequence[Sequence[Mapping[str, object]]] | Any,
    model: BaselineModelFit,
    *,
    threshold: float,
    eligible_positive_count: int,
    minimum_signal_count: int,
    target_field: str,
) -> dict[str, object]:
    signals = [
        signal
        for rows in groups
        if (
            signal := first_baseline_signal(
                rows,
                model,
                threshold=threshold,
                stage="action",
            )
        )
        is not None
    ]
    true_positives = sum(
        bool(signal.get(target_field)) for signal in signals
    )
    precision = true_positives / len(signals) if signals else 0.0
    recall = (
        true_positives / eligible_positive_count if eligible_positive_count else 0.0
    )
    return {
        "threshold": threshold,
        "prediction_count": len(signals),
        "true_positive_count": true_positives,
        "false_positive_count": len(signals) - true_positives,
        "eligible_positive_count": eligible_positive_count,
        "precision_pct": round(precision * 100, 4),
        "recall_pct": round(recall * 100, 4),
        "f1": round(_f_beta(precision, recall, beta=1.0), 6),
        "f0_5": round(_f_beta(precision, recall, beta=0.5), 6),
        "sample_qualified": len(signals) >= minimum_signal_count,
    }


def _groups_for_dates(
    rows: Sequence[Mapping[str, object]],
    allowed_dates: set[date],
) -> dict[tuple[str, str], list[Mapping[str, object]]]:
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        if _as_date(row.get("signal_date")) not in allowed_dates:
            continue
        pair = _row_pair(row)
        if all(pair):
            groups[pair].append(row)
    return dict(groups)


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("vt_symbol") or ""),
        str(row.get("signal_date") or row.get("entry_date") or "")[:10],
    )


def _f_beta(precision: float, recall: float, *, beta: float) -> float:
    beta_squared = beta * beta
    denominator = beta_squared * precision + recall
    if denominator <= 0:
        return 0.0
    return (1 + beta_squared) * precision * recall / denominator


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
