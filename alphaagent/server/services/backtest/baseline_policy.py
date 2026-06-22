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
    "enable_low_suction_lifecycle_ranking",
    "enable_low_suction_buildup_quality_lane",
    "enable_candidate_tail_risk_penalty",
    "enable_mainline_momentum_lane",
    "enable_mainline_momentum_risk_control",
    "enable_mainline_momentum_hard_filter",
    "enable_surge_quality_lane",
    "enable_top20_day_quality_gate",
    "enable_weekly_top_fractal_relief",
    "enable_pure_loss_weak_bucket_penalty",
    "enable_selective_setup_quality_lane",
    "enable_high_risk_d2_follow_through_entry",
    "enable_dynamic_failed_launch_exit_stop",
    "enable_dynamic_failed_launch_replacement_quality_gate",
    "enable_failed_launch_exit_stop",
    "enable_contextual_failed_launch_exit_stop",
    "enable_mid_profit_giveback_stop",
    "enable_contextual_support_reclaim_delay",
    "enable_contextual_peak_giveback_stop",
    "enable_low_suction_false_launch_watch_gate",
    "enable_missed_candidate_quality_rotation",
    "enable_high_quality_trend_rotation",
    "enable_weak_holding_quality_rotation",
    "enable_protected_weak_holding_rotation",
    "enable_low_suction_pullback_entry",
    "enable_low_suction_trigger_day_confirmation",
    "enable_low_suction_confirmed_branch_exit",
    "enable_low_suction_branch_replacement_quality_gate",
    "enable_low_suction_branch_replacement_strict_setup_gate",
    "enable_phase_aware_setup_selector",
    "enable_phase_replacement_quality",
    "reuse_signal_cache",
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
    if _text(payload.get("setup_family_filter")):
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
    metric_rows, metric_reason, metric_warning = _select_metric_protected_baselines(selected)
    if metric_rows:
        return _annotated_baselines(metric_rows, reason=metric_reason, warning=metric_warning)

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


def _has_explicit_disabled_signal_cache(params: dict[str, Any]) -> bool:
    payload = params if isinstance(params, dict) else {}
    return "reuse_signal_cache" in payload and not _truthy(payload.get("reuse_signal_cache"))


def _select_metric_protected_baselines(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str, str | None] | tuple[None, None, None]:
    rows_with_metrics = [row for row in rows if _performance_key(row) is not None]
    if not rows_with_metrics:
        return None, None, None

    legacy_rows = [
        row
        for row in rows_with_metrics
        if "reuse_signal_cache" not in ((row.get("params") or {}) if isinstance(row.get("params"), dict) else {})
    ]
    if not legacy_rows:
        best_key = max(_performance_key(row) for row in rows_with_metrics if _performance_key(row) is not None)
        return _rows_matching_performance(rows_with_metrics, best_key), "best_available_metric_policy", None

    incumbent_key = max(_performance_key(row) for row in legacy_rows if _performance_key(row) is not None)
    explicit_no_cache_rows = [
        row for row in rows_with_metrics if _has_explicit_disabled_signal_cache(row.get("params") or {})
    ]
    improved_rows = [
        row
        for row in explicit_no_cache_rows
        if _dominates_performance(_performance_key(row), incumbent_key)
    ]
    if improved_rows:
        best_key = max(_performance_key(row) for row in improved_rows if _performance_key(row) is not None)
        return _rows_matching_performance(improved_rows, best_key), "improved_return_win_rate_policy", None

    warning = "沿用历史高收益基线；当前重算/实验回测未同时提升收益率和胜率，仅用于分析。"
    return _rows_matching_performance(legacy_rows, incumbent_key), "historical_high_return_policy", warning


def _performance_key(row: dict[str, Any]) -> tuple[float, float] | None:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    total_return = _float_or_none(metrics.get("total_return_pct"))
    win_rate = _float_or_none(metrics.get("win_rate"))
    if total_return is None or win_rate is None:
        return None
    if win_rate > 1:
        win_rate = win_rate / 100.0
    return total_return, win_rate


def _dominates_performance(candidate: tuple[float, float] | None, incumbent: tuple[float, float]) -> bool:
    if candidate is None:
        return False
    return candidate[0] > incumbent[0] and candidate[1] > incumbent[1]


def _rows_matching_performance(rows: list[dict[str, Any]], key: tuple[float, float]) -> list[dict[str, Any]]:
    return [row for row in rows if _performance_key(row) == key]


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


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
