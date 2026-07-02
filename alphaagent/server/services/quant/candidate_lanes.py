"""Candidate lane ordering for the public dragon-pullback strategy."""

from __future__ import annotations

from typing import Any

from alphaagent.server.services.quant.factors import DRAGON_PULLBACK_STRATEGY_ID


STEALTH_LOW_SUCTION_LANE = "stealth_low_suction"
DRAGON_PULLBACK_LANE = "dragon_pullback"


def dragon_candidate_lane(candidate: Any) -> str:
    evidence = getattr(candidate, "evidence", {}) or {}
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if setup == STEALTH_LOW_SUCTION_LANE:
        return STEALTH_LOW_SUCTION_LANE
    return DRAGON_PULLBACK_LANE


def select_dragon_pullback_execution_pool(candidates: list[Any], candidate_limit: int, strategy_id: str | None) -> list[Any]:
    """Return the execution pool without reserving slots for any setup lane.

    Low-suction setups compete in the same list as dragon-pullback setups. The
    execution rank does not apply a generic low-suction lifecycle bonus; only
    verified clean-watch profiles receive a narrow opportunity bonus.
    """

    limit = max(int(candidate_limit or 0), 0)
    if limit <= 0:
        return []
    if strategy_id != DRAGON_PULLBACK_STRATEGY_ID:
        return list(candidates[:limit])

    selected = sorted(candidates, key=dragon_pullback_opportunity_key)[:limit]
    return [candidate for candidate in selected if not dragon_pullback_quality_filter_reason(candidate)]


def execution_pool_context(candidates: list[Any], candidate_limit: int, strategy_id: str | None) -> dict[str, dict[str, Any]]:
    limit = max(int(candidate_limit or 0), 0)
    pre_filter_pool = (
        sorted(candidates, key=dragon_pullback_opportunity_key)[:limit]
        if strategy_id == DRAGON_PULLBACK_STRATEGY_ID and limit > 0
        else list(candidates[:limit])
    )
    filtered = {
        str(getattr(candidate, "vt_symbol", ""))
        for candidate in pre_filter_pool
        if strategy_id == DRAGON_PULLBACK_STRATEGY_ID and dragon_pullback_quality_filter_reason(candidate)
    }
    filter_reasons = {
        str(getattr(candidate, "vt_symbol", "")): dragon_pullback_quality_filter_reason(candidate)
        for candidate in pre_filter_pool
        if strategy_id == DRAGON_PULLBACK_STRATEGY_ID and dragon_pullback_quality_filter_reason(candidate)
    }
    pool = [candidate for candidate in pre_filter_pool if str(getattr(candidate, "vt_symbol", "")) not in filtered]
    selected = {str(getattr(candidate, "vt_symbol", "")): index for index, candidate in enumerate(pool, start=1)}
    context: dict[str, dict[str, Any]] = {}
    for raw_rank, candidate in enumerate(candidates, start=1):
        vt_symbol = str(getattr(candidate, "vt_symbol", ""))
        lane = dragon_candidate_lane(candidate) if strategy_id == DRAGON_PULLBACK_STRATEGY_ID else "score"
        context[vt_symbol] = {
            "execution_lane": lane,
            "raw_signal_rank": raw_rank,
            "execution_opportunity_score": round(dragon_pullback_opportunity_score(candidate), 4)
            if strategy_id == DRAGON_PULLBACK_STRATEGY_ID
            else float(getattr(candidate, "total_score", 0) or 0),
            "execution_opportunity_bonus": round(default_clean_watch_entry_opportunity_bonus(candidate), 4)
            if strategy_id == DRAGON_PULLBACK_STRATEGY_ID
            else 0.0,
            "execution_volume_preparation_adjustment": 0.0,
            "execution_candidate_rank": selected.get(vt_symbol),
            "execution_candidate_selected": vt_symbol in selected,
            "execution_quality_filtered": vt_symbol in filtered,
            "execution_quality_filter_reason": filter_reasons.get(vt_symbol),
            "execution_candidate_limit": int(candidate_limit or 0),
        }
    return context


def dragon_pullback_opportunity_key(candidate: Any) -> tuple[float, float, str]:
    return (
        -dragon_pullback_opportunity_score(candidate),
        0.0 if dragon_candidate_lane(candidate) == DRAGON_PULLBACK_LANE else 1.0,
        str(getattr(candidate, "vt_symbol", "")),
    )


def dragon_pullback_opportunity_score(candidate: Any) -> float:
    return float(getattr(candidate, "total_score", 0) or 0) + default_clean_watch_entry_opportunity_bonus(candidate)


def dragon_pullback_lane_key(candidate: Any) -> tuple[float, str]:
    return (-float(getattr(candidate, "total_score", 0) or 0), str(getattr(candidate, "vt_symbol", "")))


def stealth_low_suction_lane_key(candidate: Any) -> tuple[float, ...]:
    evidence = getattr(candidate, "evidence", {}) or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    latest_change = _float_or_default(evidence.get("latest_change_pct"), 0.0)
    ma5_distance = _float_or_default(evidence.get("ma5_distance_pct"), 999.0)
    ma10_distance = _float_or_default(evidence.get("ma10_distance_pct"), 999.0)
    ma_convergence = _float_or_default(evidence.get("ma_convergence_pct"), 999.0)
    volume_ratio = _float_or_default(evidence.get("volume_ratio_5d_20d"), 999.0)
    ma20_distance = _float_or_default(evidence.get("ma20_distance_pct"), 999.0)
    fresh = bool(evidence.get("fresh_stealth_low_suction"))
    startup_shape = (
        3 <= low_suction_days <= 5
        and 0.4 <= latest_change <= 6.5
        and -0.8 <= ma5_distance <= 3.2
        and -1.0 <= ma10_distance <= 4.5
        and ma_convergence <= 4.5
        and 0.5 <= volume_ratio <= 1.55
        and -2.5 <= ma20_distance <= 8.0
    )
    return (
        0.0 if fresh else 1.0,
        0.0 if startup_shape else 1.0,
        abs(low_suction_days - 3.5),
        abs(latest_change - 2.6),
        abs(ma5_distance - 1.2),
        abs(ma10_distance - 1.4),
        ma_convergence,
        abs(volume_ratio - 0.9),
        -float(getattr(candidate, "total_score", 0) or 0),
        str(getattr(candidate, "vt_symbol", "")),
    )


def default_clean_watch_entry_opportunity_bonus(candidate: Any) -> float:
    evidence = getattr(candidate, "evidence", {}) or {}
    if not evidence.get("default_executable_entry_signal"):
        return 0.0
    if evidence.get("support_divergence_entry_observation_only") or evidence.get("strong_trend_ma_pullback_entry_observation_only"):
        return 0.0
    profile = str(evidence.get("default_clean_watch_entry_profile") or "")
    if profile == "clean_low_liquidity_first_lift":
        return 11.0
    if profile == "clean_low_liquidity_accumulation":
        return 9.0
    if profile == "clean_active_support_divergence":
        return 3.5
    return 0.0


def stale_active_weak_decay_pullback(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    fresh_lift = bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed"))
    recent_limit_source = bool(evidence.get("recent_limit_up_20d")) or _float_or_default(
        evidence.get("near_limit_up_count_20d"),
        0.0,
    ) > 0
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    return bool(
        low_suction_days >= 6.0
        and not fresh_lift
        and recent_limit_source
        and close_location is not None
        and close_location > 0.25
        and volume_ratio is not None
        and volume_ratio <= 1.05
        and (pullback_days >= 6.0 or strong_leg >= 96.0)
    )


def old_low_suction_strong_leg_normal_volume(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        low_suction_days >= 5.0
        and strong_leg >= 96.0
        and volume_ratio is not None
        and 0.85 <= volume_ratio <= 1.15
    )


def large_bull_no_limit_ma20_stretch(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    large_bull_count = _float_or_default(evidence.get("large_bull_count_20d"), 0.0)
    recent_limit_source = bool(evidence.get("recent_limit_up_20d")) or _float_or_default(
        evidence.get("near_limit_up_count_20d"),
        0.0,
    ) > 0
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    return bool(
        large_bull_count >= 3.0
        and not recent_limit_source
        and ma20_distance is not None
        and ma20_distance >= 7.0
    )


def crowded_large_bull_no_limit_high_close_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    large_bull_count = _float_or_default(evidence.get("large_bull_count_20d"), 0.0)
    recent_limit_source = bool(evidence.get("recent_limit_up_20d")) or _float_or_default(
        evidence.get("near_limit_up_count_20d"),
        0.0,
    ) > 0
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        large_bull_count >= 3.0
        and not recent_limit_source
        and close_location is not None
        and close_location >= 0.78
    )


def old_ma10_support_no_limit_normal_volume_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    support_type = str(evidence.get("support_type") or "")
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    recent_limit_source = bool(evidence.get("recent_limit_up_20d")) or _float_or_default(
        evidence.get("near_limit_up_count_20d"),
        0.0,
    ) > 0
    return bool(
        low_suction_days >= 5.0
        and support_type in {"ma10_support", "ma10_reclaim"}
        and (pullback_days >= 6.0 or strong_leg >= 96.0)
        and ma10_distance is not None
        and -1.0 <= ma10_distance <= 3.5
        and not recent_limit_source
        and volume_ratio is not None
        and volume_ratio >= 0.85
    )


def old_ma10_support_ma5_stretch_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    support_type = str(evidence.get("support_type") or "")
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    return bool(
        low_suction_days >= 5.0
        and support_type in {"ma10_support", "ma10_reclaim"}
        and (pullback_days >= 6.0 or strong_leg >= 96.0)
        and ma10_distance is not None
        and -1.0 <= ma10_distance <= 3.5
        and ma5_distance is not None
        and ma5_distance > 3.5
    )


def strong_leg_long_pullback_ma10_far_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    return bool(
        strong_leg >= 96.0
        and pullback_days >= 6.0
        and ma10_distance is not None
        and ma10_distance >= 5.0
    )


def core_active_strong_leg_shrink_ma10_upper_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        _core_active_support_candidate(evidence)
        and strong_leg >= 96.0
        and ma10_distance is not None
        and 2.5 < ma10_distance <= 5.5
        and volume_ratio is not None
        and 0.55 < volume_ratio <= 0.85
    )


def wide_ma10_high_turnover_normal_volume_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    support_type = str(evidence.get("support_type") or "")
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    turnover20 = _float_or_none(evidence.get("turnover20"))
    return bool(
        support_type in {"ma10_support", "ma10_reclaim"}
        and ma_convergence is not None
        and ma_convergence >= 14.0
        and low_suction_days < 3.0
        and close_location is not None
        and 0.58 <= close_location <= 0.78
        and ma5_distance is not None
        and ma5_distance < 0.5
        and volume_ratio is not None
        and volume_ratio <= 1.25
        and turnover20 is not None
        and turnover20 >= 1_000_000_000.0
    )


def wide_ma_no_low_suction_high_close_volume_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        ma_convergence is not None
        and ma_convergence >= 14.0
        and low_suction_days < 3.0
        and close_location is not None
        and close_location >= 0.82
        and volume_ratio is not None
        and volume_ratio <= 1.35
    )


def overheated_ma5_reclaim_ma10_far_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    support_type = str(evidence.get("support_type") or "")
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    return_20d = _float_or_none(evidence.get("return_20d"))
    return bool(
        low_suction_days <= 0.0
        and support_type in {"ma5_support", "ma5_reclaim"}
        and strong_leg >= 96.0
        and 3.0 <= pullback_days <= 4.0
        and ma10_distance is not None
        and ma10_distance >= 8.0
        and return_20d is not None
        and return_20d >= 55.0
    )


def core_active_short_pullback_strong_leg_lift_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return bool(
        _core_active_support_candidate(evidence)
        and strong_leg >= 96.0
        and 3.0 <= pullback_days <= 5.0
        and ma5_distance is not None
        and -2.0 < ma5_distance <= 1.0
        and latest_change is not None
        and 2.0 < latest_change <= 5.5
    )


def dragon_pullback_quality_filter_reason(candidate: Any) -> str | None:
    if stale_active_weak_decay_pullback(candidate):
        return "stale_active_weak_decay_pullback"
    if old_low_suction_strong_leg_normal_volume(candidate):
        return "old_low_suction_strong_leg_normal_volume"
    if large_bull_no_limit_ma20_stretch(candidate):
        return "large_bull_no_limit_ma20_stretch"
    if crowded_large_bull_no_limit_high_close_decay(candidate):
        return "crowded_large_bull_no_limit_high_close_decay"
    if old_ma10_support_no_limit_normal_volume_decay(candidate):
        return "old_ma10_support_no_limit_normal_volume_decay"
    if old_ma10_support_ma5_stretch_decay(candidate):
        return "old_ma10_support_ma5_stretch_decay"
    if strong_leg_long_pullback_ma10_far_decay(candidate):
        return "strong_leg_long_pullback_ma10_far_decay"
    if core_active_strong_leg_shrink_ma10_upper_decay(candidate):
        return "core_active_strong_leg_shrink_ma10_upper_decay"
    if wide_ma10_high_turnover_normal_volume_decay(candidate):
        return "wide_ma10_high_turnover_normal_volume_decay"
    if wide_ma_no_low_suction_high_close_volume_decay(candidate):
        return "wide_ma_no_low_suction_high_close_volume_decay"
    if core_active_short_pullback_strong_leg_lift_decay(candidate):
        return "core_active_short_pullback_strong_leg_lift_decay"
    if overheated_ma5_reclaim_ma10_far_decay(candidate):
        return "overheated_ma5_reclaim_ma10_far_decay"
    return None


def stale_active_long_weak_pullback(candidate: Any) -> bool:
    return stale_active_weak_decay_pullback(candidate)


def _float_or_default(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _active_source(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence.get("recent_limit_up_20d")
        or _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0) > 0
        or _float_or_default(evidence.get("large_bull_count_20d"), 0.0) >= 1.0
    )


def _active_controlled_ma5_candidate(evidence: dict[str, Any]) -> bool:
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    return bool(
        _active_source(evidence)
        and close_location is not None
        and close_location < 0.78
        and ma5_distance is not None
        and -2.0 <= ma5_distance <= 4.8
    )


def _strong_ma5_pullback(evidence: dict[str, Any]) -> bool:
    support_type = str(evidence.get("support_type") or "")
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        strong_leg >= 78.0
        and (
            support_type in {"ma5_reclaim", "ma5_support"}
            or (ma5_distance is not None and -2.0 <= ma5_distance <= 2.8)
        )
        and pullback_days >= 2.0
        and close_location is not None
        and close_location <= 0.78
    )


def _strong_ma10_pullback(evidence: dict[str, Any]) -> bool:
    support_type = str(evidence.get("support_type") or "")
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    return bool(
        strong_leg >= 78.0
        and (
            support_type in {"ma10_reclaim", "ma10_support"}
            or (ma10_distance is not None and -3.0 <= ma10_distance <= 3.5)
        )
        and (ma5_distance is None or ma5_distance <= 5.5)
        and pullback_days >= 3.0
    )


def _high_level_support_divergence(evidence: dict[str, Any]) -> bool:
    drawdown = _float_or_none(evidence.get("drawdown_from_pivot_pct"))
    support_hold_days = _float_or_default(evidence.get("support_hold_days"), 0.0)
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        _active_source(evidence)
        and drawdown is not None
        and -18.0 <= drawdown <= -3.0
        and support_hold_days >= 2.0
        and (
            (ma10_distance is not None and -4.0 <= ma10_distance <= 4.5)
            or (ma20_distance is not None and -4.0 <= ma20_distance <= 7.0)
        )
        and close_location is not None
        and close_location <= 0.78
    )


def _core_active_support_candidate(evidence: dict[str, Any]) -> bool:
    return bool(
        _active_controlled_ma5_candidate(evidence)
        and (
            _high_level_support_divergence(evidence)
            or _strong_ma5_pullback(evidence)
            or _strong_ma10_pullback(evidence)
        )
    )
