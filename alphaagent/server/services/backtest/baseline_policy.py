"""Product-baseline selection for backtest runs.

The product UI needs one deterministic baseline run. Research experiments and
ambiguous long-range diagnostics must not silently replace that baseline.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


RESEARCH_SWITCHES = (
    "exclude_from_product_baseline",
    "require_low_suction_launch_confirmation",
    "exclude_repeated_dragon_pullback",
    "require_low_suction_launch_for_low_suction_context",
    "require_balanced_low_suction_launch_quality",
    "enable_entry_launch_quality_score",
    "enable_entry_launch_risk_penalty",
    "enable_low_suction_market_risk_penalty",
    "enable_market_adaptive_setup_weighting",
    "enable_low_suction_first_lift_bonus",
    "enable_failed_launch_exit_stop",
    "enable_contextual_failed_launch_exit_stop",
    "enable_mid_profit_giveback_stop",
    "enable_contextual_support_reclaim_delay",
    "enable_contextual_peak_giveback_stop",
    "enable_low_suction_false_launch_watch_gate",
    "enable_missed_candidate_quality_rotation",
)


def is_product_baseline_params(params: dict[str, Any]) -> bool:
    """Return true for default user-facing portfolio backtests."""

    payload = params if isinstance(params, dict) else {}
    if any(_truthy(payload.get(key, False)) for key in RESEARCH_SWITCHES):
        return False
    if _text(payload.get("execution_model") or "legacy_next_open") != "legacy_next_open":
        return False
    if _int_value(payload.get("candidate_limit"), default=20) != 20:
        return False
    if _int_value(payload.get("max_positions"), default=10) != 10:
        return False
    return (
        _float_value(payload.get("mid_profit_giveback_min_high_gain_pct"), default=0.10) == 0.10
        and _float_value(payload.get("mid_profit_giveback_max_current_gain_pct"), default=0.04) == 0.04
        and _float_value(payload.get("mid_profit_giveback_drawdown_pct"), default=0.07) == 0.07
    )


def baseline_policy_name(params: dict[str, Any]) -> str:
    """Return the persisted product-baseline policy name, if any."""

    policy = _text((params or {}).get("baseline_policy"))
    return policy or "implicit_default"


def select_product_baselines(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select deterministic product-baseline rows and annotate the reason."""

    eligible = [
        item
        for item in items
        if item.get("run_type") == "portfolio"
        and item.get("start_date")
        and item.get("end_date")
        and is_product_baseline_params(item.get("params") or {})
    ]
    if not eligible:
        return items

    latest_end = max(_date_key(item.get("end_date")) for item in eligible)
    latest_rows = [item for item in eligible if _date_key(item.get("end_date")) == latest_end]
    explicit_rows = [
        item
        for item in latest_rows
        if baseline_policy_name(item.get("params") or {}) == "current_product"
    ]
    if explicit_rows:
        return _annotated_baselines(explicit_rows, reason="current_product_policy")

    start_date = _most_common_start_date(latest_rows)
    selected = [item for item in latest_rows if _date_key(item.get("start_date")) == start_date]
    if _has_longer_latest_default(latest_rows, start_date):
        return _annotated_baselines(
            selected,
            reason="implicit_common_start_date",
            warning="存在更长起点的默认参数回测，当前按同结束日中最常见起点选择产品基线。",
        )
    return _annotated_baselines(selected, reason="implicit_common_start_date")


def _annotated_baselines(
    rows: list[dict[str, Any]],
    *,
    reason: str,
    warning: str | None = None,
) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["baseline_reason"] = reason
        if warning:
            item["baseline_warning"] = warning
        else:
            item.setdefault("baseline_warning", None)
        annotated.append(item)
    return annotated


def _most_common_start_date(rows: list[dict[str, Any]]) -> str:
    counts = Counter(_date_key(item.get("start_date")) for item in rows)
    max_count = max(counts.values())
    candidates = [start for start, count in counts.items() if count == max_count]
    return min(candidates)


def _has_longer_latest_default(rows: list[dict[str, Any]], selected_start: str) -> bool:
    return any(_date_key(item.get("start_date")) < selected_start for item in rows)


def _date_key(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value or "")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _int_value(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any, *, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
