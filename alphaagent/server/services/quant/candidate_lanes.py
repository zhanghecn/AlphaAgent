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

    Low-suction setups compete in the same list as dragon-pullback setups. They
    receive an opportunity bonus only after enough absorption days and early
    upward confirmation, so a fresh low-suction shape cannot force its way into
    the pool merely because it belongs to a separate lane.
    """

    limit = max(int(candidate_limit or 0), 0)
    if limit <= 0:
        return []
    if strategy_id != DRAGON_PULLBACK_STRATEGY_ID:
        return list(candidates[:limit])

    return sorted(candidates, key=dragon_pullback_opportunity_key)[:limit]


def execution_pool_context(candidates: list[Any], candidate_limit: int, strategy_id: str | None) -> dict[str, dict[str, Any]]:
    pool = select_dragon_pullback_execution_pool(candidates, candidate_limit, strategy_id)
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
            "execution_opportunity_bonus": round(stealth_low_suction_opportunity_bonus(candidate), 4)
            if strategy_id == DRAGON_PULLBACK_STRATEGY_ID
            else 0.0,
            "execution_candidate_rank": selected.get(vt_symbol),
            "execution_candidate_selected": vt_symbol in selected,
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
    return float(getattr(candidate, "total_score", 0) or 0) + stealth_low_suction_opportunity_bonus(candidate)


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


def stealth_low_suction_opportunity_bonus(candidate: Any) -> float:
    if dragon_candidate_lane(candidate) != STEALTH_LOW_SUCTION_LANE:
        return 0.0
    evidence = getattr(candidate, "evidence", {}) or {}
    low_suction_days = _float_or_default(evidence.get("low_suction_days"), 0.0)
    latest_change = _float_or_default(evidence.get("latest_change_pct"), 0.0)
    ma5_distance = _float_or_default(evidence.get("ma5_distance_pct"), 999.0)
    ma10_distance = _float_or_default(evidence.get("ma10_distance_pct"), 999.0)
    ma5_slope = _float_or_default(evidence.get("ma5_slope_pct"), -999.0)
    ma5_vs_ma10 = _float_or_default(evidence.get("ma5_vs_ma10_pct"), -999.0)
    ma_convergence = _float_or_default(evidence.get("ma_convergence_pct"), 999.0)
    volume_ratio = _float_or_default(evidence.get("volume_ratio_5d_20d"), 999.0)
    close_location = _float_or_default(evidence.get("close_location_in_range"), 0.0)
    return_60d = _float_or_default(evidence.get("return_60d"), 0.0)

    bonus = 0.0
    if low_suction_days >= 7:
        bonus += 4.5
    elif low_suction_days >= 6:
        bonus += 3.5
    elif low_suction_days >= 5:
        bonus += 1.5
    elif low_suction_days >= 4:
        bonus += 0.5

    rising_confirmed = False
    if 0.4 <= latest_change <= 3.8:
        bonus += 1.5
        rising_confirmed = True
    elif 0.0 < latest_change < 0.4:
        bonus += 0.5
        rising_confirmed = True
    elif 3.8 < latest_change <= 5.5:
        bonus += 0.5
        rising_confirmed = ma5_distance <= 2.8
    elif latest_change < -1.0:
        bonus -= 1.0
    if ma5_slope >= 0.15:
        bonus += 1.3 if ma5_slope <= 0.9 else 0.5
        rising_confirmed = True
    elif ma5_slope >= 0:
        bonus += 0.5
    else:
        bonus -= 0.8
    if 0.0 <= ma5_distance <= 2.8:
        bonus += 1.0
        rising_confirmed = True
    elif 2.8 < ma5_distance <= 3.2:
        bonus += 0.2
    elif ma5_distance > 3.2:
        bonus -= 2.0
    if 0.0 <= ma10_distance <= 3.2:
        bonus += 0.7
    elif ma10_distance > 4.0:
        bonus -= 1.0
    if ma5_vs_ma10 >= 0:
        bonus += 0.5
    if close_location >= 0.58:
        bonus += 0.5
    if 0.55 <= volume_ratio <= 0.90:
        bonus += 1.0
    elif 0.90 < volume_ratio <= 1.15:
        bonus += 0.2
    elif volume_ratio > 1.20:
        bonus -= 1.0
    if ma_convergence <= 3.0:
        bonus += 0.8
    elif ma_convergence <= 4.0:
        bonus += 0.4

    if low_suction_days < 6:
        bonus = min(bonus, 2.0)
    if low_suction_days < 5:
        bonus = min(bonus, 1.0)
    if not rising_confirmed:
        bonus = min(bonus, 0.5)
    if ma5_distance > 3.2 or ma10_distance > 5.0:
        bonus = min(bonus, 0.5)
    if volume_ratio > 1.20:
        bonus = min(bonus, 2.0)
    if volume_ratio > 1.45:
        bonus = min(bonus, 0.5)
    if return_60d >= 90:
        bonus = min(bonus, 2.0)
    return max(min(bonus, 6.0), -6.0)


def _float_or_default(value: Any, default: float) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
