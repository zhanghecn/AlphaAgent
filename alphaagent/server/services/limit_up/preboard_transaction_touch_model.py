"""Frozen transaction-flow timing model for v6 pre-board actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from math import isfinite

from alphaagent.server.services.limit_up.preboard_competing_risk_model import (
    select_confirmed_competing_signals,
)
from alphaagent.server.services.limit_up.preboard_joint_trigger_model import (
    DEFAULT_ACTION_THRESHOLDS,
    JointThresholdSelection,
)


TOUCH_ACTION_TARGET_FIELD = "formal_touch_within_3m"
TOUCH_PREPARE_TARGET_FIELD = "formal_touch_within_5m"
TOUCH_ACTION_SCORE_FIELD = "transaction_touch_3m_probability"
TOUCH_PREPARE_SCORE_FIELD = "transaction_prepare_5m_probability"
TOUCH_CONFIRMATION_MINUTES = 1
MINIMUM_CALIBRATION_SELECTIONS = 10
MINIMUM_CALIBRATION_PRECISION = 0.70
MAX_DAILY_FIRST_BOARD_ACTIONS = 2


def calibrate_touch_threshold(
    rows: Sequence[Mapping[str, object]],
    *,
    calibration_dates: set[date],
    thresholds: Sequence[float] = DEFAULT_ACTION_THRESHOLDS,
    minimum_selection_count: int = MINIMUM_CALIBRATION_SELECTIONS,
    minimum_precision: float = MINIMUM_CALIBRATION_PRECISION,
) -> JointThresholdSelection:
    """Freeze a single-frame threshold behind a hard touch-precision gate."""

    required_count = max(int(minimum_selection_count), 1)
    required_precision = float(minimum_precision)
    if not isfinite(required_precision) or not 0.0 <= required_precision <= 1.0:
        raise ValueError("minimum_precision must be between 0 and 1")
    calibration_rows = [
        dict(row)
        for row in rows
        if _as_date(row.get("signal_date")) in calibration_dates
    ]
    target_pairs = {
        _row_pair(row)
        for row in calibration_rows
        if row.get(TOUCH_ACTION_TARGET_FIELD) is True
        and _number(row.get(TOUCH_ACTION_SCORE_FIELD)) is not None
    }
    metrics = tuple(
        _threshold_metrics(
            calibration_rows,
            threshold=float(threshold),
            target_pairs=target_pairs,
        )
        for threshold in thresholds
    )
    qualified = [
        row
        for row in metrics
        if int(row.get("selection_count") or 0) >= required_count
        and (_number(row.get("touch_precision")) or 0.0) >= required_precision
    ]
    selected = max(
        qualified,
        key=lambda row: (
            float(row.get("reachable_recall") or 0.0),
            float(row.get("touch_precision") or 0.0),
            float(row.get("threshold") or 0.0),
        ),
        default=None,
    )
    return JointThresholdSelection(
        status="ready" if selected is not None else "calibration_precision_gate_failed",
        threshold=float(selected["threshold"]) if selected is not None else None,
        calibration_dates=tuple(
            value.isoformat() for value in sorted(calibration_dates)
        ),
        minimum_selection_count=required_count,
        selected_metrics=dict(selected or {}),
        metrics_by_threshold=metrics,
    )


def select_touch_action_signals(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
) -> list[dict[str, object]]:
    """Select the first complete qualifying minute without sustained confirmation."""

    return select_confirmed_competing_signals(
        rows,
        threshold=float(threshold),
        score_field=TOUCH_ACTION_SCORE_FIELD,
        confirmation_minutes=TOUCH_CONFIRMATION_MINUTES,
        max_daily_actions=MAX_DAILY_FIRST_BOARD_ACTIONS,
    )


def _threshold_metrics(
    rows: Sequence[Mapping[str, object]],
    *,
    threshold: float,
    target_pairs: set[tuple[str, str]],
) -> dict[str, float | int | None]:
    selected = select_touch_action_signals(rows, threshold=threshold)
    selected_pairs = {_row_pair(row) for row in selected}
    true_pairs = {
        _row_pair(row)
        for row in selected
        if row.get(TOUCH_ACTION_TARGET_FIELD) is True
    }
    precision = _ratio(len(true_pairs), len(selected_pairs))
    recall = _ratio(len(true_pairs), len(target_pairs))
    return {
        "threshold": round(float(threshold), 4),
        "selection_count": len(selected_pairs),
        "touch_true_positive_count": len(true_pairs),
        "touch_precision": precision,
        "reachable_recall": recall,
    }


def _row_pair(row: Mapping[str, object]) -> tuple[str, str]:
    return (
        str(row.get("vt_symbol") or ""),
        _as_date(row.get("signal_date")).isoformat(),
    )


def _as_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
