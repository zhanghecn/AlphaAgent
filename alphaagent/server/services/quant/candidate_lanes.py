"""Candidate lane ordering for the public dragon-pullback strategy."""

from __future__ import annotations

from typing import Any

from alphaagent.server.services.quant.factors import DRAGON_PULLBACK_STRATEGY_ID


STEALTH_LOW_SUCTION_LANE = "stealth_low_suction"
DRAGON_PULLBACK_LANE = "dragon_pullback"
OVERSOLD_REBOUND_LANE = "oversold_rebound_start"
RETREAT_MOMENTUM_SOURCE_LANE = "retreat_high_low_switch_momentum"
EARLY_SILVER_LATE_DEEP_ABSORPTION_CAP = 82.0


def dragon_candidate_lane(candidate: Any) -> str:
    evidence = getattr(candidate, "evidence", {}) or {}
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if evidence.get("retreat_momentum_board_survival_source") or setup == RETREAT_MOMENTUM_SOURCE_LANE:
        return RETREAT_MOMENTUM_SOURCE_LANE
    if setup == OVERSOLD_REBOUND_LANE:
        return OVERSOLD_REBOUND_LANE
    if setup == STEALTH_LOW_SUCTION_LANE:
        return STEALTH_LOW_SUCTION_LANE
    return DRAGON_PULLBACK_LANE


def select_dragon_pullback_execution_pool(candidates: list[Any], candidate_limit: int, strategy_id: str | None) -> list[Any]:
    """Return the execution pool without reserving slots for any setup lane.

    Low-suction setups compete in the same list as dragon-pullback setups. The
    execution rank does not apply a generic low-suction lifecycle bonus. Quality
    filters are applied inside the requested TopN only; filtered slots are not
    backfilled from lower ranks, so weak buckets remain visible in evaluation.
    """

    limit = max(int(candidate_limit or 0), 0)
    if limit <= 0:
        return []
    if strategy_id != DRAGON_PULLBACK_STRATEGY_ID:
        return list(candidates[:limit])

    selected, _ = _dragon_pullback_execution_selection(candidates, limit, strategy_id)
    return selected


def execution_pool_context(candidates: list[Any], candidate_limit: int, strategy_id: str | None) -> dict[str, dict[str, Any]]:
    limit = max(int(candidate_limit or 0), 0)
    pool, selection = _dragon_pullback_execution_selection(candidates, limit, strategy_id)
    selected = {str(getattr(candidate, "vt_symbol", "")): index for index, candidate in enumerate(pool, start=1)}
    pre_filter_symbols = selection.get("pre_filter_symbols", set())
    filtered = selection.get("filtered_symbols", set())
    filter_reasons = selection.get("filter_reasons", {})
    context: dict[str, dict[str, Any]] = {}
    for raw_rank, candidate in enumerate(candidates, start=1):
        vt_symbol = str(getattr(candidate, "vt_symbol", ""))
        lane = dragon_candidate_lane(candidate) if strategy_id == DRAGON_PULLBACK_STRATEGY_ID else "score"
        default_bonus = default_clean_watch_entry_opportunity_bonus(candidate) if strategy_id == DRAGON_PULLBACK_STRATEGY_ID else 0.0
        timing_bonus = dragon_pullback_timing_opportunity_bonus(candidate) if strategy_id == DRAGON_PULLBACK_STRATEGY_ID else 0.0
        context[vt_symbol] = {
            "execution_lane": lane,
            "raw_signal_rank": raw_rank,
            "execution_opportunity_score": round(dragon_pullback_opportunity_score(candidate), 4)
            if strategy_id == DRAGON_PULLBACK_STRATEGY_ID
            else float(getattr(candidate, "total_score", 0) or 0),
            "execution_default_opportunity_bonus": round(default_bonus, 4),
            "execution_timing_opportunity_bonus": round(timing_bonus, 4),
            "execution_opportunity_bonus": round(default_bonus + timing_bonus, 4),
            "execution_opportunity_reasons": dragon_pullback_timing_opportunity_reasons(candidate)
            if strategy_id == DRAGON_PULLBACK_STRATEGY_ID
            else [],
            "execution_volume_preparation_adjustment": 0.0,
            "execution_candidate_rank": selected.get(vt_symbol),
            "execution_candidate_selected": vt_symbol in selected,
            "execution_pre_filter_selected": vt_symbol in pre_filter_symbols,
            "execution_quality_filtered": vt_symbol in filtered,
            "execution_quality_filter_reason": filter_reasons.get(vt_symbol),
            "execution_candidate_limit": int(candidate_limit or 0),
            "execution_policy": "filtered_opportunity_rank_no_backfill",
            "execution_vacancy_fill_eligible": False,
            "execution_filled_vacancy": False,
            "execution_frontrow_quality_score": frontrow_quality_score(candidate)
            if strategy_id == DRAGON_PULLBACK_STRATEGY_ID
            else 0.0,
        }
    return context


def _dragon_pullback_execution_selection(
    candidates: list[Any],
    limit: int,
    strategy_id: str | None,
) -> tuple[list[Any], dict[str, Any]]:
    if limit <= 0:
        return [], {"pre_filter_symbols": set(), "filtered_symbols": set(), "filter_reasons": {}, "vacancy_fills": set()}
    if strategy_id != DRAGON_PULLBACK_STRATEGY_ID:
        pool = list(candidates[:limit])
        return pool, {
            "pre_filter_symbols": {str(getattr(candidate, "vt_symbol", "")) for candidate in pool},
            "filtered_symbols": set(),
            "filter_reasons": {},
            "vacancy_fills": set(),
        }

    ordered = sorted(candidates, key=dragon_pullback_opportunity_key)
    pre_filter_pool = ordered[:limit]
    filter_reasons = {
        str(getattr(candidate, "vt_symbol", "")): reason
        for candidate in pre_filter_pool
        if (reason := dragon_pullback_quality_filter_reason(candidate))
    }
    selected = [candidate for candidate in pre_filter_pool if str(getattr(candidate, "vt_symbol", "")) not in filter_reasons]

    return selected, {
        "pre_filter_symbols": {str(getattr(candidate, "vt_symbol", "")) for candidate in pre_filter_pool},
        "filtered_symbols": set(filter_reasons),
        "filter_reasons": filter_reasons,
        "vacancy_fills": set(),
    }


def dragon_pullback_opportunity_key(candidate: Any) -> tuple[float, float, str]:
    lane = dragon_candidate_lane(candidate)
    return (
        -dragon_pullback_opportunity_score(candidate),
        1.0 if lane == STEALTH_LOW_SUCTION_LANE else 0.0,
        str(getattr(candidate, "vt_symbol", "")),
    )


def dragon_pullback_opportunity_score(candidate: Any) -> float:
    score = (
        float(getattr(candidate, "total_score", 0) or 0)
        + default_clean_watch_entry_opportunity_bonus(candidate)
        + dragon_pullback_timing_opportunity_bonus(candidate)
    )
    if deep_low_absorption_early_silver_late_retreat_decay(candidate):
        return min(score, EARLY_SILVER_LATE_DEEP_ABSORPTION_CAP)
    return score


def frontrow_quality_score(candidate: Any) -> float:
    evidence = getattr(candidate, "evidence", {}) or {}
    heat = _float_or_none(evidence.get("frontrow_sector_heat_score"))
    sector_score = _float_or_none(evidence.get("frontrow_sector_score"))
    rank_return = _float_or_none(evidence.get("frontrow_sector_rank_return"))
    leader = _float_or_none(evidence.get("frontrow_sector_leader_score"))
    breadth = _float_or_none(evidence.get("frontrow_sector_breadth_score"))
    continuity = _float_or_none(evidence.get("frontrow_sector_continuity_score"))
    theme_rank = _float_or_none(evidence.get("frontrow_theme_candidate_rank"))
    theme_count = _float_or_none(evidence.get("frontrow_theme_candidate_count"))
    repair_rank = _float_or_none(evidence.get("frontrow_theme_repair_candidate_rank"))
    repair_type = _secondary_subtype(evidence)
    if heat is None and sector_score is None:
        return 0.0

    score = 0.0
    if sector_score is not None:
        score += min(max(sector_score - 48.0, 0.0) * 0.75, 28.0)
    if heat is not None and heat >= 60.0:
        score += min((heat - 58.0) * 1.05, 18.0)
    if rank_return is not None:
        if rank_return <= 50:
            score += 16.0
        elif rank_return <= 100:
            score += 12.0
        elif rank_return <= 150:
            score += 8.0
        elif rank_return <= 220:
            score += 4.0
    for value, threshold, points in ((leader, 55.0, 10.0), (breadth, 45.0, 7.0), (continuity, 45.0, 7.0)):
        if value is not None and value >= threshold:
            score += min((value - threshold) * 0.25 + points, points + 5.0)
    if theme_rank is not None:
        if theme_rank <= 3:
            score += 12.0
        elif theme_rank <= 5:
            score += 8.0
        elif theme_count is not None and theme_count > 0 and theme_rank / theme_count <= 0.25:
            score += 5.0
    if repair_rank is not None:
        if repair_rank <= 1:
            score += 8.0
        elif repair_rank <= 2:
            score += 5.0
    if repair_type == "secondary_breakout_confirm" and bool(evidence.get("deep_cycle_secondary_breakout_reversal")):
        score += 5.0
    if repair_type == "bottom_reclaim" and bool(evidence.get("bottom_reclaim_silver_6_20_retreat")):
        score += 5.0
    if _controlled_repair_price_volume(evidence):
        score += 5.0
    return round(max(0.0, min(score, 100.0)), 4)


def _secondary_breakout_narrow_confirm_bonus(candidate: Any) -> float:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _secondary_subtype(evidence) != "secondary_breakout_confirm":
        return 0.0
    score = 0.0
    score_value = _secondary_score(evidence)
    repair_score = _float_or_default(evidence.get("bottom_ma_repair_strength_score"), 0.0)
    timing = str(evidence.get("timing_window") or "")
    phase = str(evidence.get("market_phase") or "")
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    rebound = _float_or_none(evidence.get("rebound_from_20d_low_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    if bool(evidence.get("deep_cycle_secondary_breakout_reversal")):
        score += 4.5
    if timing in {"after_silver_6_20", "after_silver_late"} and phase == "retreat":
        score += 2.0
    if (
        close_location is not None
        and close_location >= 0.70
        and volume_ratio is not None
        and 0.75 <= volume_ratio <= 1.80
        and ma20_distance is not None
        and -6.0 <= ma20_distance <= 6.5
    ):
        score += 1.2
    if (
        score_value >= 76.0
        and repair_score >= 70.0
        and rebound is not None
        and 6.0 <= rebound <= 16.0
        and latest_change is not None
        and 4.0 <= latest_change <= 10.5
    ):
        score += 1.0
    return round(score, 4)


def _secondary_subtype(evidence: dict[str, Any]) -> str:
    return str(
        evidence.get("oversold_rebound_candidate_subtype")
        or evidence.get("oversold_rebound_subtype")
        or evidence.get("rebound_subtype")
        or ""
    )


def _secondary_score(evidence: dict[str, Any]) -> float:
    return float(
        _float_or_none(evidence.get("oversold_rebound_candidate_score"))
        or _float_or_none(evidence.get("oversold_rebound_score"))
        or _float_or_none(evidence.get("total_score"))
        or 0.0
    )


def _controlled_repair_price_volume(evidence: dict[str, Any]) -> bool:
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma20 = _float_or_none(evidence.get("ma20_distance_pct"))
    return bool(
        close_location is not None
        and 0.62 <= close_location <= 1.0
        and volume_ratio is not None
        and 0.55 <= volume_ratio <= 1.65
        and ma20 is not None
        and -7.0 <= ma20 <= 4.0
    )


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


def dragon_pullback_timing_opportunity_bonus(candidate: Any) -> float:
    return round(sum(float(reason["points"]) for reason in dragon_pullback_timing_opportunity_reasons(candidate)), 4)


def dragon_pullback_timing_opportunity_reasons(candidate: Any) -> list[dict[str, Any]]:
    """Positive-only setup/timing opportunity bonus for the unified execution pool.

    This bonus intentionally does not subtract points. Weak gold/silver windows
    simply receive no timing bonus, leaving the lane's base score untouched.
    """

    evidence = getattr(candidate, "evidence", {}) or {}
    setup = _setup_family(evidence)
    timing = str(evidence.get("timing_window") or "unknown")
    phase = str(evidence.get("market_phase") or "unknown")
    reasons: list[dict[str, Any]] = []

    def add(key: str, label: str, points: float) -> None:
        if points <= 0:
            return
        reasons.append({"key": key, "label": label, "points": round(points, 4)})

    if setup == OVERSOLD_REBOUND_LANE and timing == "after_silver_6_20" and phase == "retreat":
        add("oversold_silver_6_20_retreat", "超跌反弹：银手指后6-20日退潮修复", 3.0)
        if _oversold_silver_repair_low_turnover(evidence, setup=setup, timing=timing, phase=phase):
            add("oversold_silver_repair_low_turnover", "超跌反弹：银后低位缩量修复", 4.0)
        if _bottom_reclaim_setup(evidence):
            add("bottom_reclaim_silver_6_20_retreat", "底部收复：银手指后6-20日退潮修复", 1.0)
            if _confirmed_bottom_reclaim_repair(evidence):
                add("bottom_reclaim_confirmed_repair", "底部收复：均线修复确认", 0.9)
        if bool(evidence.get("secondary_breakout_confirm")):
            add("secondary_breakout_silver_6_20_retreat", "二次确认：银手指后退潮转强", 0.6)
            if _confirmed_secondary_breakout_repair(evidence):
                add("secondary_breakout_confirmed_repair", "二次确认：底部修复后再转强", 0.7)

    if setup == OVERSOLD_REBOUND_LANE and timing == "after_gold_0_5" and phase == "retreat":
        add("oversold_gold_0_5_retreat_repair", "超跌反弹：金手指短窗退潮修复", 3.4)
        if _bottom_reclaim_setup(evidence):
            add("bottom_reclaim_gold_0_5_retreat", "底部收复：金手指短窗退潮修复", 0.8)
            if _confirmed_bottom_reclaim_repair(evidence):
                add("bottom_reclaim_gold_confirmed_repair", "底部收复：金手指短窗均线修复", 0.7)
        if bool(evidence.get("secondary_breakout_confirm")):
            add("secondary_breakout_gold_0_5_retreat", "二次确认：金手指短窗退潮转强", 0.6)
            if _confirmed_secondary_breakout_repair(evidence):
                add("secondary_breakout_gold_confirmed_repair", "二次确认：金手指短窗底部修复", 0.6)

    if _deep_low_absorption_reversal(evidence, setup=setup):
        if _deep_low_absorption_early_silver_late_retreat_decay(evidence, setup=setup):
            return reasons
        add("deep_low_absorption_reversal", "超跌反弹：深跌长阴低收承接", 6.8)
        if phase in {"retreat", "mixed"}:
            add("deep_low_absorption_pressure_window", "超跌反弹：退潮/分化隔日修复窗口", 1.2)
        if _controlled_latest_absorption_volume(evidence):
            add("deep_low_absorption_controlled_volume", "超跌反弹：D日量能未失控", 0.7)
        return reasons

    if setup == "low_suction_buildup" and timing == "after_silver_6_20" and phase == "retreat":
        add("low_suction_buildup_silver_6_20_retreat", "低吸蓄势：银手指后6-20日退潮修复", 2.5)

    if _low_base_buildup_safe(evidence, setup=setup):
        add("low_base_buildup_safe", "低吸蓄势：低位温和承接", 3.6)
        if timing.startswith("after_silver") and phase in {"retreat", "rotation"}:
            add("low_base_buildup_pressure_window", "低吸蓄势：银后压力窗口抗跌", 0.6)
        return reasons

    if setup == "low_suction_first_lift" and timing == "after_gold_0_5" and phase == "warming":
        add("low_suction_first_lift_gold_0_5_warming", "低吸首启：金手指后短窗回暖", 3.0)

    if setup == "low_suction_first_lift" and timing == "after_gold_6_20" and phase == "retreat":
        add("low_suction_first_lift_gold_6_20_retreat", "低吸首启：金手指后6-20日回踩", 2.5)

    gold_late_stealth_crawl = _gold_late_stealth_low_base_crawl(evidence, setup=setup, timing=timing, phase=phase)
    if gold_late_stealth_crawl is not None:
        key, label, points = gold_late_stealth_crawl
        add(key, label, points)
        return reasons

    if setup == DRAGON_PULLBACK_LANE and timing == "after_gold_6_20" and phase == "rotation":
        add("dragon_pullback_gold_6_20_rotation", "龙回头：金手指后6-20日轮动", 2.0)

    if setup == DRAGON_PULLBACK_LANE and timing == "after_gold_0_5" and phase == "warming":
        add("dragon_pullback_gold_0_5_warming", "龙回头：金手指后短窗回暖", 1.5)

    if _silver_rotation_strict_fresh_dragon(evidence, setup=setup, timing=timing, phase=phase):
        add("silver_rotation_strict_fresh_dragon", "龙回头：银手指后轮动新鲜确认", 2.8)
        return reasons

    frontrow_score = frontrow_quality_score(candidate)
    if _silver_rotation_washout_dragon(evidence, setup=setup, timing=timing, phase=phase):
        add("silver_rotation_washout_dragon", "龙回头：银后6-20轮动低收盘洗盘", 5.8)
        if frontrow_score >= 45.0:
            add("washout_dragon_frontrow_floor", "洗盘龙回头：细分题材强度达标", 0.7)
        return reasons

    if _silver_rotation_flat_base_low_suction(evidence, setup=setup, timing=timing, phase=phase) and frontrow_score >= 64.0:
        add("silver_rotation_flat_base_low_suction", "低吸：银后6-20轮动横盘蓄势", 8.1)
        add("flat_base_theme_rank_confirm", "横盘蓄势低吸：题材前三确认", 0.8)
        return reasons

    silver_pressure_low_suction_turn = _silver_pressure_fresh_low_suction_turn(evidence, setup=setup, timing=timing, phase=phase)
    if silver_pressure_low_suction_turn is not None:
        key, label, points = silver_pressure_low_suction_turn
        add(key, label, points)
        return reasons

    if _right_tail_source_context(evidence, setup=setup, timing=timing, phase=phase):
        add("right_tail_active_source_context", "活跃来源：龙回头/低吸右尾结构", 1.5)
        if _right_tail_timing_context(setup=setup, timing=timing, phase=phase):
            add("right_tail_timing_context", "历史右尾setup/timing/phase共振", 1.2)
        if _controlled_volume(evidence):
            add("right_tail_controlled_volume", "右尾结构量能温和", 0.35)

    if not reasons:
        return []

    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    if close_location is not None and 0.22 <= close_location <= 0.72:
        add("controlled_close_location", "低中位可控收盘", 0.3)
    if volume_ratio is not None and 0.55 <= volume_ratio <= 1.45:
        add("controlled_volume_ratio", "量能温和可控", 0.25)
    if _active_source(evidence):
        add("active_source", "近端活跃来源", 0.35)

    return reasons


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
    if active_washout_reclaim_confirmation(candidate):
        return False
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


def active_washout_reclaim_confirmation(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    recent_limit_source = bool(evidence.get("recent_limit_up_20d")) or _float_or_default(
        evidence.get("near_limit_up_count_20d"),
        0.0,
    ) >= 2.0
    support_type = str(evidence.get("support_type") or "")
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_5d = _float_or_none(evidence.get("return_5d"))
    return_20d = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    drawdown = _float_or_none(evidence.get("drawdown_from_pivot_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        recent_limit_source
        and support_type in {"ma5_reclaim", "ma5_support"}
        and latest_change is not None
        and latest_change >= 4.0
        and return_5d is not None
        and return_5d <= 0.0
        and return_20d is not None
        and return_20d <= 25.0
        and ma20_distance is not None
        and ma20_distance <= 8.0
        and drawdown is not None
        and drawdown <= -5.0
        and volume_ratio is not None
        and 0.65 <= volume_ratio <= 1.20
        and close_location is not None
        and close_location >= 0.82
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


def gold_late_overheated_dragon_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") not in {"retreat", "rotation", "warming"}:
        return False
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return_20d = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return bool(
        low_suction_days <= 2.0
        and return_20d is not None
        and return_20d >= 22.0
        and ma20_distance is not None
        and ma20_distance >= 8.0
        and (latest_change is None or latest_change <= 5.5)
    )


def gold_late_high_close_exhaustion_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    audited_family = _audited_setup_family(evidence)
    setup_family = _setup_family(evidence)
    if audited_family not in {DRAGON_PULLBACK_LANE, "dragon_low_suction_overlap", "low_suction_buildup"} and setup_family not in {
        DRAGON_PULLBACK_LANE,
        "dragon_low_suction_overlap",
        "low_suction_buildup",
    }:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") not in {"uptrend", "warming"}:
        return False
    return_20d = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return bool(
        return_20d is not None
        and return_20d >= 15.0
        and ma20_distance is not None
        and ma20_distance >= 6.0
        and close_location is not None
        and close_location >= 0.74
        and latest_change is not None
        and latest_change <= 4.5
    )


def gold_late_wide_ma_volume_churn_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return_20d = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        low_suction_days <= 1.0
        and return_20d is not None
        and return_20d >= 28.0
        and ma20_distance is not None
        and ma20_distance >= 12.0
        and volume_ratio is not None
        and volume_ratio >= 1.35
        and close_location is not None
        and close_location <= 0.65
    )


def gold_late_uptrend_extreme_stretch_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "uptrend":
        return False
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return_20d = _float_or_none(evidence.get("return_20d"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    near_limit_count = _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0)
    return bool(
        low_suction_days <= 1.0
        and return_20d is not None
        and return_20d >= 40.0
        and return_60d is not None
        and return_60d >= 90.0
        and ma20_distance is not None
        and ma20_distance >= 18.0
        and (bool(evidence.get("recent_limit_up_20d")) or near_limit_count >= 3.0)
    )


def gold_late_overlap_unconfirmed_highclose_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") not in {"warming", "retreat"}:
        return False
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    if launch_bucket != "unconfirmed_buildup":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    near_limit_count = _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0)
    return bool(
        latest_change is not None
        and latest_change >= 0.0
        and close_location is not None
        and close_location >= 0.62
        and ((return_60d is not None and return_60d >= 55.0) or near_limit_count >= 1.0)
    )


def gold_late_overlap_late_pullback_highclose_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "late_pullback_launch":
        return False
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return_20d = _float_or_none(evidence.get("return_20d"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    return bool(
        close_location is not None
        and close_location >= 0.70
        and ((return_60d is not None and return_60d >= 55.0) or (return_20d is not None and return_20d >= 20.0))
    )


def gold_late_first_lift_other_confirmed_exhaustion_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != "low_suction_first_lift":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") not in {"warming", "uptrend"}:
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "other_confirmed_launch":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return_60d = _float_or_none(evidence.get("return_60d"))
    return bool(
        latest_change is not None
        and latest_change <= 2.0
        and close_location is not None
        and close_location >= 0.74
        and low_suction_days <= 4.0
        and return_60d is not None
        and (return_60d >= 25.0 or return_60d <= 0.0)
    )


def gold_late_rotation_highclose_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "rotation":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_20d = _float_or_none(evidence.get("return_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        latest_change is not None
        and latest_change >= 1.0
        and return_20d is not None
        and return_20d >= 20.0
        and close_location is not None
        and close_location >= 0.72
    )


def gold_late_overlap_unconfirmed_short_reclaim_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "warming":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "unconfirmed_buildup":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return bool(
        _no_recent_active_source(evidence)
        and latest_change is not None
        and latest_change < 0.0
        and close_location is not None
        and close_location <= 0.30
        and pullback_days <= 3.0
        and low_suction_days >= 4.0
    )


def gold_late_dragon_no_active_short_reclaim_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "warming":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    return bool(
        _no_recent_active_source(evidence)
        and latest_change is not None
        and latest_change < 0.0
        and return_60d is not None
        and return_60d >= 55.0
        and ma20_distance is not None
        and ma20_distance >= 5.0
        and close_location is not None
        and close_location <= 0.40
        and pullback_days <= 3.0
    )


def gold_late_overlap_retreat_lowclose_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "retreat":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "unconfirmed_buildup":
        return False
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        _no_recent_active_source(evidence)
        and low_suction_days >= 6.0
        and close_location is not None
        and close_location <= 0.08
    )


def gold_late_overlap_rotation_weak_washout_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "rotation":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "unconfirmed_buildup":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        latest_change is not None
        and latest_change <= -4.0
        and return_60d is not None
        and return_60d <= 20.0
        and close_location is not None
        and close_location <= 0.25
    )


def gold_late_first_lift_rotation_push_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != "low_suction_first_lift":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "rotation":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "balanced_first_lift":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    return bool(
        latest_change is not None
        and latest_change >= 3.0
        and return_60d is not None
        and return_60d >= 40.0
        and pullback_days <= 3.0
    )


def gold_late_first_lift_no_active_push_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != "low_suction_first_lift":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "warming":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "other_confirmed_launch":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        _no_recent_active_source(evidence)
        and latest_change is not None
        and 2.0 <= latest_change <= 3.0
        and return_60d is not None
        and return_60d >= 25.0
        and close_location is not None
        and close_location >= 0.74
    )


def gold_late_uptrend_no_active_long_pullback_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "uptrend":
        return False
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    return_20d = _float_or_none(evidence.get("return_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        _no_recent_active_source(evidence)
        and pullback_days >= 8.0
        and return_20d is not None
        and return_20d >= 20.0
        and close_location is not None
        and close_location <= 0.35
    )


def silver_late_overlap_rotation_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    if str(evidence.get("market_phase") or "") != "rotation":
        return False
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    return_20d = _float_or_none(evidence.get("return_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    return bool(
        low_suction_days >= 3.0
        and pullback_days >= 9.0
        and (
            (return_20d is not None and return_20d >= 16.0)
            or (close_location is not None and close_location >= 0.70)
        )
        and launch_bucket in {"unconfirmed_buildup", "late_pullback_launch", "thin_volume_launch"}
    )


def silver_late_overlap_unconfirmed_midclose_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    if str(evidence.get("market_phase") or "") not in {"retreat", "rotation", "warming"}:
        return False
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    if launch_bucket != "unconfirmed_buildup" or bool(evidence.get("low_suction_launch_confirmed")):
        return False
    warning_level = _float_or_default(evidence.get("market_warning_level"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        warning_level >= 2.0
        and close_location is not None
        and 0.20 <= close_location <= 0.62
        and volume_ratio is not None
        and 0.75 <= volume_ratio <= 1.20
    )


def silver_late_midclose_ma5_reclaim_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    if str(evidence.get("market_phase") or "") != "retreat":
        return False
    support_type = str(evidence.get("support_type") or "")
    return_20d = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        support_type == "ma5_reclaim"
        and return_20d is not None
        and return_20d >= 30.0
        and ma20_distance is not None
        and ma20_distance >= 8.0
        and ma_convergence is not None
        and ma_convergence >= 14.0
        and close_location is not None
        and 0.30 <= close_location <= 0.50
        and volume_ratio is not None
        and volume_ratio <= 1.25
    )


def silver_6_20_exhausted_lowclose_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_6_20":
        return False
    if str(evidence.get("market_phase") or "") != "rotation":
        return False
    support_type = str(evidence.get("support_type") or "")
    return_20d = _float_or_none(evidence.get("return_20d"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        support_type == "ma5_reclaim"
        and return_20d is not None
        and return_20d >= 35.0
        and return_60d is not None
        and return_60d >= 55.0
        and ma20_distance is not None
        and ma20_distance >= 8.0
        and close_location is not None
        and close_location <= 0.08
    )


def gold_late_retreat_no_buildup_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    if str(evidence.get("market_phase") or "") != "retreat":
        return False
    support_type = str(evidence.get("support_type") or "")
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        support_type == "ma5_reclaim"
        and low_suction_days <= 1.0
        and ma_convergence is not None
        and ma_convergence >= 12.0
        and close_location is not None
        and close_location <= 0.70
        and volume_ratio is not None
        and volume_ratio <= 1.25
    )


def silver_late_warming_stretched_dragon_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != DRAGON_PULLBACK_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    if str(evidence.get("market_phase") or "") != "warming":
        return False
    support_type = str(evidence.get("support_type") or "")
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return_20d = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        support_type == "ma5_reclaim"
        and low_suction_days <= 2.0
        and return_20d is not None
        and return_20d >= 15.0
        and ma20_distance is not None
        and ma20_distance >= 4.5
        and ma_convergence is not None
        and ma_convergence >= 9.5
        and volume_ratio is not None
        and volume_ratio <= 1.45
    )


def silver_late_oversold_stretched_shrink_body_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != OVERSOLD_REBOUND_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    body = _float_or_none(evidence.get("body_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        ma5_distance is not None
        and ma5_distance >= 2.0
        and body is not None
        and body >= 2.0
        and (
            (volume_ratio is not None and volume_ratio <= 0.95)
            or (close_location is not None and close_location >= 0.85)
        )
    )


def silver_late_first_lift_stale_active_source_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != "low_suction_first_lift":
        return False
    if str(evidence.get("timing_window") or "") != "after_silver_late":
        return False
    timing_days = _float_or_none(evidence.get("nearest_timing_days"))
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    return bool(
        bool(evidence.get("recent_limit_up_20d"))
        and timing_days is not None
        and timing_days < 40.0
        and low_suction_days >= 5.0
    )


def gold_early_first_lift_no_active_source_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != "low_suction_first_lift":
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_0_5":
        return False
    large_bull_count = _float_or_default(evidence.get("large_bull_count_20d"), 0.0)
    return bool(_no_recent_active_source(evidence) and large_bull_count <= 1.0)


def gold_early_oversold_no_active_low_close_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != OVERSOLD_REBOUND_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_0_5":
        return False
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    return bool(
        _no_recent_active_source(evidence)
        and close_location is not None
        and close_location <= 0.35
    )


def overheated_crowded_high_turnover_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    setup = _setup_family(evidence)
    if setup == OVERSOLD_REBOUND_LANE:
        return False
    ret20 = _float_or_default(evidence.get("return_20d"), 0.0)
    ma20_distance = _float_or_default(evidence.get("ma20_distance_pct"), 0.0)
    near_limit_count = _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0)
    latest_turnover_ratio = _float_or_none(evidence.get("latest_turnover_ratio_20d"))
    turnover_percentile = _float_or_none(evidence.get("turnover_percentile_60d"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    turnover20 = _float_or_none(evidence.get("turnover20"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    high_position = ret20 >= 25.0 or ma20_distance >= 8.0
    high_turnover = bool(
        (latest_turnover_ratio is not None and latest_turnover_ratio >= 1.25)
        or (turnover_percentile is not None and turnover_percentile >= 0.82)
        or (volume_ratio is not None and volume_ratio >= 1.25 and turnover20 is not None and turnover20 >= 1_000_000_000.0)
    )
    weak_or_fade_close = bool(
        (close_location is not None and close_location <= 0.58)
        or (latest_change is not None and latest_change <= 0.0)
    )
    crowded_source = near_limit_count >= 4.0
    stale_multi_source = near_limit_count >= 2.0 and weak_or_fade_close
    return bool(high_position and high_turnover and (crowded_source or stale_multi_source))


def low_suction_hot_short_push_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) != "low_suction_first_lift":
        return False
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    if launch_bucket not in {"high_close_launch", "balanced_first_lift"}:
        return False
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ret5 = _float_or_none(evidence.get("return_5d"))
    latest_turnover_ratio = _float_or_none(evidence.get("latest_turnover_ratio_20d"))
    turnover_percentile = _float_or_none(evidence.get("turnover_percentile_60d"))
    active_turnover = bool(
        (latest_turnover_ratio is not None and latest_turnover_ratio >= 1.20)
        or (turnover_percentile is not None and turnover_percentile >= 0.85)
    )
    return bool(
        pullback_days <= 3.0
        and close_location is not None
        and close_location >= 0.70
        and ret5 is not None
        and ret5 >= 5.0
        and active_turnover
    )


def gold_late_mid_high_close_stretch_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _setup_family(evidence) == OVERSOLD_REBOUND_LANE:
        return False
    if str(evidence.get("timing_window") or "") != "after_gold_late":
        return False
    ret20 = _float_or_none(evidence.get("return_20d"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    latest_turnover_ratio = _float_or_none(evidence.get("latest_turnover_ratio_20d"))
    turnover_percentile = _float_or_none(evidence.get("turnover_percentile_60d"))
    active_turnover = bool(
        (latest_turnover_ratio is not None and latest_turnover_ratio >= 0.90)
        or (turnover_percentile is not None and turnover_percentile >= 0.75)
    )
    return bool(
        ret20 is not None
        and ret20 >= 18.0
        and ma20_distance is not None
        and ma20_distance >= 4.0
        and close_location is not None
        and close_location >= 0.62
        and latest_change is not None
        and latest_change >= 0.0
        and active_turnover
    )


def overlap_unconfirmed_fast_push_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    if _audited_setup_family(evidence) != "dragon_low_suction_overlap":
        return False
    if str(evidence.get("low_suction_launch_quality_bucket") or "") != "unconfirmed_buildup":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ret20 = _float_or_none(evidence.get("return_20d"))
    near_limit_count = _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0)
    return bool(
        latest_change is not None
        and latest_change >= 5.0
        and close_location is not None
        and close_location >= 0.75
        and ret20 is not None
        and ret20 >= 12.0
        and near_limit_count >= 1.0
    )


def deep_low_absorption_early_silver_late_retreat_decay(candidate: Any) -> bool:
    evidence = getattr(candidate, "evidence", {}) or {}
    return _deep_low_absorption_early_silver_late_retreat_decay(
        evidence,
        setup=_setup_family(evidence),
    )


def dragon_pullback_quality_filter_reason(candidate: Any) -> str | None:
    evidence = getattr(candidate, "evidence", {}) or {}
    if evidence.get("retreat_momentum_board_survival_source"):
        return None
    if low_suction_hot_short_push_decay(candidate):
        return "low_suction_hot_short_push_decay"
    if gold_late_mid_high_close_stretch_decay(candidate):
        return "gold_late_mid_high_close_stretch_decay"
    if overlap_unconfirmed_fast_push_decay(candidate):
        return "overlap_unconfirmed_fast_push_decay"
    if gold_late_overheated_dragon_decay(candidate):
        return "gold_late_overheated_dragon_decay"
    if gold_late_high_close_exhaustion_decay(candidate):
        return "gold_late_high_close_exhaustion_decay"
    if gold_late_wide_ma_volume_churn_decay(candidate):
        return "gold_late_wide_ma_volume_churn_decay"
    if gold_late_uptrend_extreme_stretch_decay(candidate):
        return "gold_late_uptrend_extreme_stretch_decay"
    if gold_late_overlap_unconfirmed_highclose_decay(candidate):
        return "gold_late_overlap_unconfirmed_highclose_decay"
    if gold_late_overlap_late_pullback_highclose_decay(candidate):
        return "gold_late_overlap_late_pullback_highclose_decay"
    if gold_late_first_lift_other_confirmed_exhaustion_decay(candidate):
        return "gold_late_first_lift_other_confirmed_exhaustion_decay"
    if gold_late_rotation_highclose_decay(candidate):
        return "gold_late_rotation_highclose_decay"
    if gold_late_overlap_unconfirmed_short_reclaim_decay(candidate):
        return "gold_late_overlap_unconfirmed_short_reclaim_decay"
    if gold_late_dragon_no_active_short_reclaim_decay(candidate):
        return "gold_late_dragon_no_active_short_reclaim_decay"
    if gold_late_overlap_retreat_lowclose_decay(candidate):
        return "gold_late_overlap_retreat_lowclose_decay"
    if gold_late_overlap_rotation_weak_washout_decay(candidate):
        return "gold_late_overlap_rotation_weak_washout_decay"
    if gold_late_first_lift_rotation_push_decay(candidate):
        return "gold_late_first_lift_rotation_push_decay"
    if gold_late_first_lift_no_active_push_decay(candidate):
        return "gold_late_first_lift_no_active_push_decay"
    if gold_late_uptrend_no_active_long_pullback_decay(candidate):
        return "gold_late_uptrend_no_active_long_pullback_decay"
    if silver_late_overlap_rotation_decay(candidate):
        return "silver_late_overlap_rotation_decay"
    if silver_late_overlap_unconfirmed_midclose_decay(candidate):
        return "silver_late_overlap_unconfirmed_midclose_decay"
    if silver_late_midclose_ma5_reclaim_decay(candidate):
        return "silver_late_midclose_ma5_reclaim_decay"
    if silver_6_20_exhausted_lowclose_decay(candidate):
        return "silver_6_20_exhausted_lowclose_decay"
    if gold_late_retreat_no_buildup_decay(candidate):
        return "gold_late_retreat_no_buildup_decay"
    if silver_late_warming_stretched_dragon_decay(candidate):
        return "silver_late_warming_stretched_dragon_decay"
    if silver_late_oversold_stretched_shrink_body_decay(candidate):
        return "silver_late_oversold_stretched_shrink_body_decay"
    if silver_late_first_lift_stale_active_source_decay(candidate):
        return "silver_late_first_lift_stale_active_source_decay"
    if gold_early_first_lift_no_active_source_decay(candidate):
        return "gold_early_first_lift_no_active_source_decay"
    if gold_early_oversold_no_active_low_close_decay(candidate):
        return "gold_early_oversold_no_active_low_close_decay"
    if overheated_crowded_high_turnover_decay(candidate):
        return "overheated_crowded_high_turnover_decay"
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


def _no_recent_active_source(evidence: dict[str, Any]) -> bool:
    return not bool(evidence.get("recent_limit_up_20d")) and _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0) <= 0.0


def _audited_setup_family(evidence: dict[str, Any]) -> str:
    setup_family = str(evidence.get("setup_family") or "")
    entry_family = str(evidence.get("entry_family") or "")
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    if setup_family == "dragon_low_suction_overlap":
        return "dragon_low_suction_overlap"
    if low_suction_days >= 3.0 and (entry_family == DRAGON_PULLBACK_LANE or setup_family == DRAGON_PULLBACK_LANE or setup == DRAGON_PULLBACK_LANE):
        return "dragon_low_suction_overlap"
    return _setup_family(evidence)


def _setup_family(evidence: dict[str, Any]) -> str:
    setup = str(evidence.get("setup_family") or evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if setup == OVERSOLD_REBOUND_LANE or _bottom_reclaim_setup(evidence) or bool(evidence.get("secondary_breakout_confirm")):
        return OVERSOLD_REBOUND_LANE
    if setup == STEALTH_LOW_SUCTION_LANE:
        low_suction_stage = str(evidence.get("low_suction_stage") or "")
        if bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed")):
            return "low_suction_first_lift"
        if low_suction_stage == "first_lift":
            return "low_suction_first_lift"
        return "low_suction_buildup"
    if setup in {"low_suction", "low_suction_buildup"}:
        return "low_suction_buildup"
    if setup == "low_suction_first_lift":
        return "low_suction_first_lift"
    if setup == "dragon_low_suction_overlap":
        return "dragon_low_suction_overlap"
    if setup == RETREAT_MOMENTUM_SOURCE_LANE:
        return RETREAT_MOMENTUM_SOURCE_LANE
    if setup == DRAGON_PULLBACK_LANE:
        return DRAGON_PULLBACK_LANE
    return setup or "other"


def _bottom_reclaim_setup(evidence: dict[str, Any]) -> bool:
    return bool(evidence.get("bottom_reclaim") or str(evidence.get("rebound_subtype") or "") == "bottom_reclaim")


def _confirmed_bottom_reclaim_repair(evidence: dict[str, Any]) -> bool:
    repair_score = _float_or_default(evidence.get("bottom_ma_repair_strength_score"), 0.0)
    repair_bucket = str(evidence.get("bottom_ma_repair_strength_bucket") or "")
    stage = str(evidence.get("bottom_ma_repair_stage") or "")
    return bool(
        repair_score >= 56.0
        or repair_bucket in {"medium_repair", "strong_repair"}
        or stage in {"ma10_reclaim", "ma5_reclaim_ma10_pending", "pre_reclaim_near_ma10"}
    )


def _confirmed_secondary_breakout_repair(evidence: dict[str, Any]) -> bool:
    repair_score = _float_or_default(evidence.get("bottom_ma_repair_strength_score"), 0.0)
    stage = str(evidence.get("bottom_ma_repair_stage") or "")
    return bool(repair_score >= 70.0 or stage == "secondary_ma10_confirm")


def _deep_low_absorption_reversal(evidence: dict[str, Any], *, setup: str) -> bool:
    return bool(
        setup == OVERSOLD_REBOUND_LANE
        and (
            bool(evidence.get("deep_low_absorption_reversal"))
            or str(evidence.get("rebound_subtype") or "") == "deep_low_absorption_reversal"
        )
    )


def _deep_low_absorption_early_silver_late_retreat_decay(evidence: dict[str, Any], *, setup: str) -> bool:
    timing = str(evidence.get("timing_window") or "")
    phase = str(evidence.get("market_phase") or "")
    nearest_days = _float_or_none(evidence.get("nearest_timing_days"))
    return bool(
        _deep_low_absorption_reversal(evidence, setup=setup)
        and timing == "after_silver_late"
        and phase == "retreat"
        and nearest_days is not None
        and nearest_days <= 25.0
    )


def _controlled_latest_absorption_volume(evidence: dict[str, Any]) -> bool:
    latest_volume = _float_or_none(evidence.get("latest_volume_ratio_20d"))
    latest_turnover = _float_or_none(evidence.get("latest_turnover_ratio_20d"))
    return bool(
        latest_volume is not None
        and 0.65 <= latest_volume <= 1.45
        and (latest_turnover is None or latest_turnover <= 1.35)
    )


def _oversold_silver_repair_low_turnover(
    evidence: dict[str, Any],
    *,
    setup: str,
    timing: str,
    phase: str,
) -> bool:
    if setup != OVERSOLD_REBOUND_LANE or timing != "after_silver_6_20" or phase != "retreat":
        return False
    ret20 = _float_or_none(evidence.get("return_20d"))
    ma20 = _float_or_none(evidence.get("ma20_distance_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_turnover = _float_or_none(evidence.get("latest_turnover_ratio_20d"))
    near_limit_count = _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0)
    if None in {ret20, ma20, latest_change, close_location}:
        return False
    return bool(
        ret20 <= -5.0
        and ma20 <= -3.0
        and -7.0 <= latest_change <= 4.0
        and close_location <= 0.75
        and (latest_turnover is None or latest_turnover <= 1.20)
        and near_limit_count <= 1.0
    )


def _low_base_buildup_safe(evidence: dict[str, Any], *, setup: str) -> bool:
    if setup != "low_suction_buildup":
        return False
    ret20 = _float_or_none(evidence.get("return_20d"))
    ma20 = _float_or_none(evidence.get("ma20_distance_pct"))
    volume = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    latest_turnover = _float_or_none(evidence.get("latest_turnover_ratio_20d"))
    low_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    if None in {ret20, ma20, volume, close_location}:
        return False
    return bool(
        0.0 <= ret20 <= 18.0
        and -2.0 <= ma20 <= 7.0
        and 0.75 <= volume <= 1.20
        and (latest_turnover is None or latest_turnover <= 1.25)
        and low_days >= 3.0
        and pullback_days >= 5.0
        and 0.30 <= close_location <= 0.85
    )


def _silver_rotation_strict_fresh_dragon(
    evidence: dict[str, Any],
    *,
    setup: str,
    timing: str,
    phase: str,
) -> bool:
    if setup != DRAGON_PULLBACK_LANE or timing != "after_silver_6_20" or phase != "rotation":
        return False
    strong_leg = _float_or_default(evidence.get("strong_leg_score"), 0.0)
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    near_limit_count = _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0)
    return bool(
        strong_leg >= 86.0
        and _strong_active_source(evidence)
        and close_location is not None
        and 0.18 <= close_location <= 0.70
        and volume_ratio is not None
        and 0.70 <= volume_ratio <= 1.30
        and ma10_distance is not None
        and ma10_distance >= 0.0
        and ma20_distance is not None
        and ma20_distance <= 8.5
        and ma_convergence is not None
        and ma_convergence <= 10.5
        and (pullback_days <= 6.0 or near_limit_count >= 3.0)
    )


def _silver_rotation_washout_dragon(
    evidence: dict[str, Any],
    *,
    setup: str,
    timing: str,
    phase: str,
) -> bool:
    if setup != DRAGON_PULLBACK_LANE or timing != "after_silver_6_20" or phase != "rotation":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ret5 = _float_or_none(evidence.get("return_5d"))
    ret20 = _float_or_none(evidence.get("return_20d"))
    ret60 = _float_or_none(evidence.get("return_60d"))
    ma20 = _float_or_none(evidence.get("ma20_distance_pct"))
    volume = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    low_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    theme_rank = _float_or_none(evidence.get("frontrow_theme_candidate_rank"))
    sector_heat = _float_or_default(evidence.get("frontrow_sector_heat_score"), 0.0)
    return bool(
        latest_change is not None
        and -1.2 <= latest_change <= 1.6
        and ret5 is not None
        and -1.0 <= ret5 <= 6.0
        and ret20 is not None
        and 12.0 <= ret20 <= 28.0
        and ret60 is not None
        and ret60 <= 42.0
        and ma20 is not None
        and 4.0 <= ma20 <= 13.0
        and volume is not None
        and 1.35 <= volume <= 1.90
        and close_location is not None
        and close_location <= 0.25
        and low_days <= 1.0
        and theme_rank is not None
        and theme_rank <= 1.0
        and sector_heat >= 52.0
    )


def _silver_rotation_flat_base_low_suction(
    evidence: dict[str, Any],
    *,
    setup: str,
    timing: str,
    phase: str,
) -> bool:
    if setup not in {"low_suction_buildup", "low_suction_first_lift"}:
        return False
    if timing != "after_silver_6_20" or phase != "rotation":
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ret5 = _float_or_none(evidence.get("return_5d"))
    ret20 = _float_or_none(evidence.get("return_20d"))
    ret60 = _float_or_none(evidence.get("return_60d"))
    ma20 = _float_or_none(evidence.get("ma20_distance_pct"))
    volume = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    low_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    theme_rank = _float_or_none(evidence.get("frontrow_theme_candidate_rank"))
    sector_heat = _float_or_default(evidence.get("frontrow_sector_heat_score"), 0.0)
    return bool(
        latest_change is not None
        and -0.8 <= latest_change <= 1.4
        and ret5 is not None
        and -1.2 <= ret5 <= 1.8
        and ret20 is not None
        and -2.0 <= ret20 <= 5.0
        and ret60 is not None
        and -5.0 <= ret60 <= 15.0
        and ma20 is not None
        and -1.5 <= ma20 <= 2.5
        and volume is not None
        and 0.80 <= volume <= 1.05
        and close_location is not None
        and 0.45 <= close_location <= 0.72
        and 6.0 <= low_days <= 7.0
        and theme_rank is not None
        and theme_rank <= 3.0
        and sector_heat >= 48.0
    )


def _silver_pressure_fresh_low_suction_turn(
    evidence: dict[str, Any],
    *,
    setup: str,
    timing: str,
    phase: str,
) -> tuple[str, str, float] | None:
    if timing not in {"after_silver_6_20", "after_silver_late"} or phase != "retreat":
        return None

    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ret20 = _float_or_none(evidence.get("return_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    low_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    pullback_days = _float_or_default(evidence.get("pullback_days"), 0.0)
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")
    frontrow_rank = _float_or_none(evidence.get("frontrow_sector_rank_return"))
    if None in {latest_change, ret20, close_location, volume}:
        return None

    if (
        setup == "low_suction_first_lift"
        and 3.0 <= low_days <= 5.0
        and 5.0 <= pullback_days <= 9.0
        and latest_change >= 2.0
        and ret20 <= 16.0
        and close_location >= 0.55
        and 0.70 <= volume <= 1.30
        and launch_bucket in {"balanced_first_lift", "repeated_launch", "high_close_launch", "thin_volume_launch"}
    ):
        return ("silver_pressure_fresh_first_lift_turn", "低吸首启：银后压力新鲜转强", 8.0)

    if (
        setup == "low_suction_buildup"
        and 3.0 <= low_days <= 4.0
        and 5.0 <= pullback_days <= 8.0
        and latest_change >= 2.0
        and ret20 <= 12.0
        and close_location >= 0.35
        and 0.80 <= volume <= 1.30
        and frontrow_rank is not None
        and frontrow_rank <= 120.0
    ):
        return ("silver_pressure_fresh_buildup_turn", "低吸蓄势：银后压力短周期转强", 7.0)

    return None


def _gold_late_stealth_low_base_crawl(
    evidence: dict[str, Any],
    *,
    setup: str,
    timing: str,
    phase: str,
) -> tuple[str, str, float] | None:
    if timing != "after_gold_late" or phase != "warming":
        return None
    raw_setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if raw_setup != STEALTH_LOW_SUCTION_LANE:
        return None

    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ret5 = _float_or_none(evidence.get("return_5d"))
    ret20 = _float_or_none(evidence.get("return_20d"))
    ret60 = _float_or_none(evidence.get("return_60d"))
    ma20 = _float_or_none(evidence.get("ma20_distance_pct"))
    volume = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    low_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    support_hold_days = _float_or_default(evidence.get("support_hold_days"), 0.0)
    if None in {latest_change, ret5, ret20, ret60, ma20, volume, close_location}:
        return None
    if support_hold_days < 5.0:
        return None

    if (
        setup == "low_suction_buildup"
        and 4.0 <= low_days <= 7.0
        and -0.7 <= latest_change <= 0.75
        and -1.0 <= ret5 <= 4.2
        and 5.5 <= ret20 <= 10.5
        and -3.0 <= ret60 <= 12.0
        and 2.2 <= ma20 <= 6.0
        and 0.84 <= volume <= 1.16
        and 0.45 <= close_location <= 0.98
    ):
        return ("gold_late_stealth_buildup_crawl", "低吸：金后期回暖底部蓄势爬升", 8.6)

    if (
        setup == "low_suction_first_lift"
        and 4.0 <= low_days <= 6.0
        and 0.75 <= latest_change <= 1.8
        and -0.5 <= ret5 <= 6.2
        and 1.5 <= ret20 < 14.0
        and -6.5 <= ret60 <= 18.0
        and 1.2 <= ma20 <= 7.4
        and 0.90 <= volume <= 1.18
        and 0.50 <= close_location <= 0.98
    ):
        return ("gold_late_stealth_first_lift_crawl", "低吸：金后期回暖首启小阳爬升", 6.8)

    return None


def _right_tail_source_context(evidence: dict[str, Any], *, setup: str, timing: str, phase: str) -> bool:
    if setup not in {DRAGON_PULLBACK_LANE, "dragon_low_suction_overlap", "low_suction_buildup", "low_suction_first_lift"}:
        return False
    if not _active_source(evidence):
        return False
    if not _right_tail_timing_context(setup=setup, timing=timing, phase=phase):
        return False
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    if volume_ratio is not None and not (0.50 <= volume_ratio <= 1.65):
        return False
    return True


def _right_tail_timing_context(*, setup: str, timing: str, phase: str) -> bool:
    timing_phase = f"{timing}|{phase}"
    buckets = {
        DRAGON_PULLBACK_LANE: {
            "after_gold_0_5|warming",
            "after_gold_6_20|rotation",
            "after_gold_6_20|warming",
        },
        "dragon_low_suction_overlap": {
            "after_gold_0_5|warming",
            "after_gold_0_5|retreat",
            "after_gold_6_20|retreat",
            "after_gold_6_20|rotation",
            "after_silver_late|warming",
            "after_silver_late|retreat",
        },
        "low_suction_buildup": {
            "after_gold_0_5|warming",
            "after_gold_6_20|retreat",
            "after_silver_6_20|retreat",
            "after_silver_late|retreat",
            "after_silver_late|uptrend",
        },
        "low_suction_first_lift": {
            "after_gold_0_5|warming",
            "after_gold_6_20|retreat",
            "after_silver_0_5|warming",
            "after_silver_6_20|retreat",
        },
    }
    return timing_phase in buckets.get(setup, set())


def _controlled_volume(evidence: dict[str, Any]) -> bool:
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(volume_ratio is not None and 0.55 <= volume_ratio <= 1.35)


def _active_source(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence.get("recent_limit_up_20d")
        or _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0) > 0
        or _float_or_default(evidence.get("large_bull_count_20d"), 0.0) >= 1.0
    )


def _strong_active_source(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence.get("recent_limit_up_20d")
        or _float_or_default(evidence.get("near_limit_up_count_20d"), 0.0) >= 2.0
        or _float_or_default(evidence.get("large_bull_count_20d"), 0.0) >= 3.0
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
