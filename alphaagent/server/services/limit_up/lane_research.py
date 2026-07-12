"""Independent rules and portfolio selection for each board-height lane."""

from __future__ import annotations

from collections import defaultdict
from datetime import time
from typing import Mapping, Sequence

BOARD_LANES = ("first_board", "one_to_two", "two_to_three", "high_board")
BOARD_LANE_LABELS = {
    "first_board": "首板",
    "one_to_two": "一进二",
    "two_to_three": "二进三",
    "high_board": "高板",
}
FIRST_BOARD_MIN_SUPPORT_SCORE = 35.0
FIRST_BOARD_MIN_TOUCH_COUNT = 6
FIRST_BOARD_MIN_NET_PROFIT_YOY = 10.0
FIRST_BOARD_MIN_PRIOR_FAILED_RATE = 0.35
TWO_TO_THREE_RISK_LIMIT = 4


def classify_board_lane(candidate: Mapping[str, object]) -> str:
    """Classify both consecutive and recent non-consecutive board structure."""

    prior_streak = _integer(candidate.get("prior_streak"))
    recent_limits = _integer(candidate.get("prior_limit_count_5"))
    target = max(_integer(candidate.get("target_board")), prior_streak + 1, recent_limits + 1)
    if target >= 4:
        return "high_board"
    if target == 3:
        return "two_to_three"
    if target == 2:
        return "one_to_two"
    return "first_board"


def evaluate_lane_candidate(candidate: Mapping[str, object]) -> dict[str, object]:
    """Apply lane-specific hard gates without consulting close or D+1 outcomes."""

    result = dict(candidate)
    lane = classify_board_lane(candidate)
    blockers = _shared_blockers(candidate, lane)
    favorable: list[str] = []
    setup_type: str | None = None
    two_to_three_quality: dict[str, object] = {
        "two_to_three_quality_tier": None,
        "two_to_three_risk_count": 0,
        "two_to_three_risk_flags": [],
    }

    if lane == "first_board":
        lane_blockers, favorable = _first_board_rules(candidate)
        blockers.extend(lane_blockers)
    elif lane == "one_to_two":
        lane_blockers, favorable = _one_to_two_rules(candidate)
        blockers.extend(lane_blockers)
    elif lane == "two_to_three":
        lane_blockers, favorable, setup_type = _two_to_three_rules(candidate)
        blockers.extend(lane_blockers)
        two_to_three_quality = _two_to_three_quality(candidate)
        if two_to_three_quality["two_to_three_risk_count"] >= TWO_TO_THREE_RISK_LIMIT:
            blockers.append("two_to_three_risk_stack")
    else:
        lane_blockers, favorable, setup_type = _high_board_rules(candidate)
        blockers.extend(lane_blockers)

    blockers = list(dict.fromkeys(blockers))
    l2_only = blockers == ["high_board_requires_l2"]
    if blockers:
        decision = "watch" if lane == "high_board" and l2_only else "blocked"
    else:
        decision = "eligible"
    support_score = first_board_support_score(candidate) if lane == "first_board" else None
    entry_quality_score = (
        first_board_entry_quality_score(candidate, support_score=support_score)
        if lane == "first_board"
        else None
    )
    result.update(
        {
            "lane": lane,
            "lane_label": BOARD_LANE_LABELS[lane],
            "decision": decision,
            "action": _action(lane, decision, candidate),
            "blockers": blockers,
            "favorable_factors": favorable,
            "setup_type": setup_type,
            "support_score": support_score,
            "seal_gate_passed": (
                support_score is not None
                and support_score >= FIRST_BOARD_MIN_SUPPORT_SCORE
            )
            if lane == "first_board"
            else None,
            "premium_gate_passed": _first_board_premium_gate_passed(candidate)
            if lane == "first_board"
            else None,
            "entry_quality_score": entry_quality_score,
            "rank_score": _lane_rank_score(candidate, lane, setup_type),
            **two_to_three_quality,
        }
    )
    return result


def select_daily_lane_portfolio(
    candidates: Sequence[Mapping[str, object]],
    *,
    max_total: int = 4,
    max_per_industry: int = 2,
) -> dict[str, object]:
    """Select a diversified portfolio first, then fill remaining ranked slots."""

    selection_limit = max(max_total, 0)
    evaluated = [evaluate_lane_candidate(candidate) for candidate in candidates]
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for candidate in evaluated:
        grouped[str(candidate["lane"])].append(candidate)

    candidate_pool: dict[str, list[dict[str, object]]] = {}
    displayed: dict[str, list[dict[str, object]]] = {}
    for lane in BOARD_LANES:
        rows = grouped.get(lane, [])
        rows.sort(key=lambda row: _display_sort_key(row, lane))
        candidate_pool[lane] = [
            {**row, "pool_rank": rank}
            for rank, row in enumerate(rows, start=1)
        ]
        displayed[lane] = [
            {**row, "lane_rank": rank, "pool_rank": rank}
            for rank, row in enumerate(rows[:selection_limit], start=1)
        ]

    selected: list[dict[str, object]] = []
    industry_counts: dict[str, int] = defaultdict(int)
    selected_symbols: set[str] = set()
    for lane in BOARD_LANES:
        for candidate in displayed[lane]:
            if _append_if_allowed(
                selected,
                candidate,
                max_total=selection_limit,
                max_per_industry=max_per_industry,
                industry_counts=industry_counts,
                selected_symbols=selected_symbols,
            ):
                break
        if len(selected) >= selection_limit:
            break

    remaining = [
        candidate
        for lane in BOARD_LANES
        for candidate in displayed[lane]
        if str(candidate.get("vt_symbol") or "") not in selected_symbols
    ]
    remaining.sort(key=_portfolio_fill_sort_key)
    for candidate in remaining:
        _append_if_allowed(
            selected,
            candidate,
            max_total=selection_limit,
            max_per_industry=max_per_industry,
            industry_counts=industry_counts,
            selected_symbols=selected_symbols,
        )

    selected_counts_by_lane: dict[str, int] = defaultdict(int)
    for candidate in selected:
        selected_counts_by_lane[str(candidate.get("lane") or "unknown")] += 1
    return {
        "action": "normal" if selected else "empty",
        "selection_policy": "diversified_then_ranked_v1",
        "selected_count": len(selected),
        "max_candidates": selection_limit,
        "max_per_industry": max_per_industry,
        "selected": selected,
        "selected_counts_by_lane": dict(selected_counts_by_lane),
        "selected_counts_by_industry": dict(industry_counts),
        "lanes": displayed,
        "candidate_pool": candidate_pool,
        "candidate_count": len(evaluated),
        "blocked_count": sum(row.get("decision") == "blocked" for row in evaluated),
        "watch_count": sum(row.get("decision") == "watch" for row in evaluated),
    }


def _append_if_allowed(
    selected: list[dict[str, object]],
    candidate: Mapping[str, object],
    *,
    max_total: int,
    max_per_industry: int,
    industry_counts: dict[str, int],
    selected_symbols: set[str],
) -> bool:
    if len(selected) >= max_total or candidate.get("decision") != "eligible":
        return False
    symbol = str(candidate.get("vt_symbol") or "")
    industry = str(
        candidate.get("industry_id") or candidate.get("industry_name") or ""
    )
    if not symbol or symbol in selected_symbols:
        return False
    if industry and industry_counts[industry] >= max_per_industry:
        return False
    selected.append(dict(candidate))
    selected_symbols.add(symbol)
    if industry:
        industry_counts[industry] += 1
    return True


def _portfolio_fill_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    quality_order = 0 if candidate.get("two_to_three_quality_tier") == "A" else 1
    return (
        quality_order,
        -float(candidate.get("rank_score") or 0),
        _integer(candidate.get("lane_rank")),
        str(candidate.get("vt_symbol") or ""),
    )


def _shared_blockers(
    candidate: Mapping[str, object],
    lane: str,
) -> list[str]:
    blockers: list[str] = []
    if lane != "first_board":
        phase = str(candidate.get("prior_market_phase") or "unknown")
        if phase in {"retreat", "ice", "decline"}:
            blockers.append("market_retreat")
        failed_rate = _number(candidate.get("prior_market_failed_rate"))
        if failed_rate is not None and failed_rate > 0.45:
            blockers.append("market_failed_rate_high")
    financial = candidate.get("financial_risk")
    if isinstance(financial, Mapping) and bool(financial.get("blocked")):
        blockers.append("fundamental_risk")
    heat = _number(candidate.get("prior_industry_heat_score"))
    if lane != "first_board" and heat is not None and heat < 50:
        blockers.append("industry_not_hot")
    if lane != "first_board":
        heat_rank = _integer_or_none(candidate.get("prior_industry_heat_rank"))
        industry_count = _integer_or_none(candidate.get("prior_industry_count"))
        if heat_rank is not None and industry_count and heat_rank > max(8, round(industry_count * 0.3)):
            blockers.append("industry_not_front")
        leader_rank = _integer_or_none(candidate.get("prior_industry_leader_rank"))
        if leader_rank is None:
            blockers.append("industry_leader_rank_unverified")
        elif leader_rank > 2:
            blockers.append("stock_not_industry_top2")
    return blockers


def _first_board_rules(candidate: Mapping[str, object]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    favorable: list[str] = []
    gene_count = _integer(candidate.get("prior_limit_count_126"))
    if gene_count < 1:
        blockers.append("limit_up_gene_missing")
    else:
        favorable.append("half_year_limit_up_gene")
    touch_count = _integer(candidate.get("prior_touch_count_126"))
    if touch_count < FIRST_BOARD_MIN_TOUCH_COUNT:
        blockers.append("first_board_touch_gene_weak")
    else:
        favorable.append("half_year_strong_touch_gene")
    recent_limits = _integer(candidate.get("prior_limit_count_5"))
    if recent_limits > 0:
        blockers.append("not_first_board_after_cooling")
    position = _number(candidate.get("prior_position_120"))
    pullback = _number(candidate.get("pullback_from_prior_limit_pct"))
    days_since = _number(candidate.get("trade_days_since_prior_limit"))
    low_position = position is not None and position <= 0.55
    cooled_pullback = (
        pullback is not None
        and pullback <= -8
        and days_since is not None
        and days_since >= 5
    )
    if not (low_position or cooled_pullback):
        blockers.append("low_position_missing")
    else:
        favorable.append("low_position_or_cooled_pullback")
    signal_time = _time_value(candidate.get("signal_time"))
    if signal_time is None or signal_time < time(10, 0):
        blockers.append("first_touch_too_early")
    elif signal_time > time(14, 45):
        blockers.append("first_touch_too_late")
    else:
        favorable.append("post_ten_first_touch")
    success_rate = _number(candidate.get("prior_seal_success_rate_126"))
    if success_rate is not None and success_rate < 0.35:
        blockers.append("historical_seal_gene_weak")
    heat = _number(candidate.get("prior_industry_heat_score"))
    if heat is None:
        blockers.append("industry_heat_unavailable")
    support_score = first_board_support_score(candidate)
    if support_score is None:
        blockers.append("intraday_support_unavailable")
    elif support_score < FIRST_BOARD_MIN_SUPPORT_SCORE:
        blockers.append("intraday_support_breakdown")
    else:
        favorable.extend(
            ["intraday_support_confirmed", "first_board_seal_gate_confirmed"]
        )
    financial = candidate.get("financial_snapshot")
    net_profit_yoy = (
        _number(financial.get("net_profit_yoy"))
        if isinstance(financial, Mapping)
        else None
    )
    if net_profit_yoy is None:
        blockers.append("financial_report_unavailable")
    elif net_profit_yoy < FIRST_BOARD_MIN_NET_PROFIT_YOY:
        blockers.append("first_board_profit_growth_weak")
    else:
        favorable.append("point_in_time_profit_growth")
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    if failed_rate is None or failed_rate < FIRST_BOARD_MIN_PRIOR_FAILED_RATE:
        blockers.append("first_board_repair_setup_missing")
    else:
        favorable.append("prior_divergence_repair_setup")
    return blockers, favorable


def _first_board_premium_gate_passed(candidate: Mapping[str, object]) -> bool:
    financial = candidate.get("financial_snapshot")
    net_profit_yoy = (
        _number(financial.get("net_profit_yoy"))
        if isinstance(financial, Mapping)
        else None
    )
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    return bool(
        _integer(candidate.get("prior_touch_count_126")) >= FIRST_BOARD_MIN_TOUCH_COUNT
        and net_profit_yoy is not None
        and net_profit_yoy >= FIRST_BOARD_MIN_NET_PROFIT_YOY
        and failed_rate is not None
        and failed_rate >= FIRST_BOARD_MIN_PRIOR_FAILED_RATE
    )


def first_board_support_score(candidate: Mapping[str, object]) -> float | None:
    """Return a bounded, signal-time support score without using D-day outcomes."""

    path = candidate.get("path_prefix")
    if isinstance(path, Mapping):
        point_count = _integer(path.get("point_count"))
        recent_floor = _number(path.get("recent_15m_min_pct"))
        recent_change = _number(path.get("recent_15m_change_pct"))
        recent_drawdown = _number(path.get("recent_15m_drawdown_pct"))
        approach = _number(path.get("approach_3point_pct"))
        if (
            point_count >= 6
            and recent_floor is not None
            and recent_change is not None
            and recent_drawdown is not None
        ):
            score = 45.0
            score += _clamp(recent_change, -4.0, 6.0) * 4.0
            score += _clamp(recent_floor, -2.0, 6.0) * 2.0
            score += _clamp(approach or 0.0, -3.0, 4.0) * 3.0
            score -= abs(min(recent_drawdown, 0.0)) * 8.0
            score += min(_integer(path.get("reseal_count")), 1) * 4.0
            return round(_clamp(score, 0.0, 100.0), 4)

    session_floor = _number(candidate.get("session_low_change_pct"))
    current_change = _number(candidate.get("change_pct"))
    if session_floor is None or current_change is None:
        return None
    opening_change = _number(candidate.get("auction_gap_pct"))
    starting_change = opening_change if opening_change is not None else session_floor
    intraday_high_change = _price_change_pct(
        candidate.get("high_price"),
        candidate.get("previous_close"),
    )
    drawdown = (
        current_change - intraday_high_change
        if intraday_high_change is not None
        else 0.0
    )
    score = 35.0
    score += _clamp(current_change - starting_change, -4.0, 6.0) * 4.0
    score += _clamp(session_floor, -2.0, 6.0)
    score -= abs(min(drawdown, 0.0)) * 8.0
    return round(_clamp(score, 0.0, 100.0), 4)


def first_board_entry_quality_score(
    candidate: Mapping[str, object],
    *,
    support_score: float | None = None,
) -> float | None:
    """Combine support, sector, gene, position and volume into one entry score."""

    support = (
        support_score
        if support_score is not None
        else first_board_support_score(candidate)
    )
    heat = _number(candidate.get("prior_industry_heat_score"))
    if heat is None:
        heat = _number(candidate.get("sector_heat"))
    if support is None or heat is None:
        return None
    gene = min(_integer(candidate.get("prior_limit_count_126")), 5) / 5 * 100
    seal_rate = _number(candidate.get("prior_seal_success_rate_126"))
    seal_score = _clamp((seal_rate or 0.0) * 100, 0.0, 100.0)
    position = _number(candidate.get("prior_position_120"))
    pullback = _number(candidate.get("pullback_from_prior_limit_pct"))
    if position is not None:
        structure_score = _clamp((1 - position) * 100, 0.0, 100.0)
    else:
        structure_score = _clamp(abs(min(pullback or 0.0, 0.0)) * 4, 0.0, 100.0)
    amount_ratio = _number(candidate.get("prior_amount_ratio_5d"))
    amount_score = _amount_structure_score(amount_ratio)
    score = (
        support * 0.45
        + _clamp(heat, 0.0, 100.0) * 0.20
        + gene * 0.10
        + seal_score * 0.10
        + structure_score * 0.10
        + amount_score * 0.05
    )
    return round(_clamp(score, 0.0, 100.0), 4)


def _amount_structure_score(value: float | None) -> float:
    if value is None:
        return 50.0
    if value < 0.5 or value > 5.0:
        return 10.0
    return _clamp(100 - abs(value - 1.8) * 25, 35.0, 100.0)


def _price_change_pct(price: object, previous_close: object) -> float | None:
    current = _number(price)
    previous = _number(previous_close)
    if current is None or previous is None or previous <= 0:
        return None
    return (current / previous - 1) * 100


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(max(value, minimum), maximum)


def _one_to_two_rules(candidate: Mapping[str, object]) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    favorable: list[str] = []
    gap = _number(candidate.get("auction_gap_pct"))
    if gap is None or not 1 <= gap <= 7:
        blockers.append("auction_gap_out_of_range")
    elif 2 <= gap <= 5.5:
        favorable.append("auction_strength_balanced")
    turnover = _number(candidate.get("prior_turnover_rate"))
    if turnover is not None and not 3 <= turnover <= 28:
        blockers.append("prior_turnover_extreme")
    amount_ratio = _number(candidate.get("prior_amount_ratio_5d"))
    if amount_ratio is not None and not 0.7 <= amount_ratio <= 4:
        blockers.append("prior_volume_structure_extreme")
    prior_board = candidate.get("prior_board")
    evidence_blocker = _prior_board_evidence_blocker(prior_board)
    if evidence_blocker:
        blockers.append(evidence_blocker)
    elif isinstance(prior_board, Mapping):
        if prior_board.get("is_sealed") is False:
            blockers.append("prior_board_failed")
        open_times = _number(prior_board.get("open_times"))
        if open_times is not None and open_times > 6:
            blockers.append("prior_board_reseal_too_many")
        if open_times is not None and 1 <= open_times <= 4:
            favorable.append("prior_board_changed_hands_and_resealed")
    return blockers, favorable


def _prior_board_evidence_blocker(prior_board: object) -> str | None:
    if not isinstance(prior_board, Mapping):
        return "prior_board_evidence_missing"
    first_time = _time_value(prior_board.get("first_limit_time"))
    open_times = _number(prior_board.get("open_times"))
    sealed = prior_board.get("is_sealed")
    if not isinstance(sealed, bool) or first_time is None or open_times is None:
        return "prior_board_path_incomplete"
    if open_times > 0 and _time_value(prior_board.get("last_limit_time")) is None:
        return "prior_board_path_incomplete"
    return None


def _two_to_three_rules(
    candidate: Mapping[str, object],
) -> tuple[list[str], list[str], str]:
    blockers, favorable = _one_to_two_rules(candidate)
    gap = _number(candidate.get("auction_gap_pct"))
    if gap is not None and gap > 6:
        blockers.append("third_board_consensus_overheated")
    amplitude = _number(candidate.get("prior_amplitude_pct"))
    prior_low = _number(candidate.get("prior_low_change_pct"))
    prior_board = candidate.get("prior_board")
    open_times = _number(prior_board.get("open_times")) if isinstance(prior_board, Mapping) else None
    first_time = (
        _time_value(prior_board.get("first_limit_time"))
        if isinstance(prior_board, Mapping)
        else None
    )
    weak_to_strong = bool(
        (amplitude is not None and amplitude >= 6)
        or (prior_low is not None and prior_low < 0)
        or (open_times is not None and open_times >= 1)
    ) and gap is not None and gap >= 1.5
    strong_consensus = bool(
        first_time is not None
        and first_time <= time(10, 0)
        and (open_times is None or open_times == 0)
        and gap is not None
        and 1 <= gap <= 5
    )
    if weak_to_strong:
        setup_type = "weak_to_strong"
        favorable.append("third_board_weak_to_strong")
    elif strong_consensus:
        setup_type = "strong_consensus"
        favorable.append("third_board_strong_consensus")
    else:
        setup_type = "unconfirmed_divergence"
        blockers.append("third_board_setup_unconfirmed")
    promotion = _number(candidate.get("prior_market_two_to_three_rate"))
    if promotion is not None and promotion < 0.12:
        blockers.append("two_to_three_market_success_low")
    amount = _number(candidate.get("prior_amount_ratio_5d"))
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    if open_times is not None and 3 <= open_times <= 6:
        favorable.append("prior_board_full_turnover_reseal")
    if amount is not None and 1.2 <= amount < 2:
        favorable.append("prior_amount_ratio_balanced")
    if isinstance(candidate.get("financial_snapshot"), Mapping):
        favorable.append("financial_snapshot_available")
    if prior_low is not None and prior_low >= 0:
        favorable.append("prior_low_held_positive")
    if failed_rate is not None and failed_rate < 0.35:
        favorable.append("prior_market_failed_rate_controlled")
    if promotion is not None and promotion >= 0.30:
        favorable.append("prior_market_two_to_three_active")
    return blockers, favorable, setup_type


def _high_board_rules(
    candidate: Mapping[str, object],
) -> tuple[list[str], list[str], str]:
    blockers: list[str] = []
    favorable: list[str] = []
    leader_rank = _integer_or_none(candidate.get("prior_industry_leader_rank"))
    if leader_rank is not None and leader_rank != 1:
        blockers.append("high_board_not_sector_core")
    prior_board = candidate.get("prior_board")
    open_times = _number(prior_board.get("open_times")) if isinstance(prior_board, Mapping) else None
    signal_kind = str(candidate.get("signal_kind") or "")
    if signal_kind == "auction":
        gap = _number(candidate.get("auction_gap_pct"))
        weak_to_strong = bool(
            isinstance(prior_board, Mapping)
            and prior_board.get("is_sealed") is True
            and open_times is not None
            and 1 <= open_times <= 4
            and gap is not None
            and 1 <= gap <= 5
        )
        setup_type = "high_board_weak_to_strong"
        if not weak_to_strong:
            blockers.append("high_board_prior_divergence_missing")
        else:
            favorable.append("prior_divergence_next_auction_strength")
    else:
        setup_type = "high_board_intraday_core"
        if not bool(candidate.get("has_l2")):
            blockers.append("high_board_requires_l2")
    if not blockers:
        favorable.extend(["sector_core", setup_type])
    return blockers, favorable, setup_type


def _two_to_three_quality(candidate: Mapping[str, object]) -> dict[str, object]:
    gap = _number(candidate.get("auction_gap_pct"))
    turnover = _number(candidate.get("prior_turnover_rate"))
    amount = _number(candidate.get("prior_amount_ratio_5d"))
    prior_low = _number(candidate.get("prior_low_change_pct"))
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    risks = [
        code
        for code, passed in (
            ("auction_gap_outside_core", gap is not None and 2 <= gap < 5),
            (
                "prior_turnover_outside_core",
                turnover is not None and 10 <= turnover < 20,
            ),
            (
                "prior_amount_ratio_outside_core",
                amount is not None and 1.2 <= amount < 2,
            ),
            (
                "financial_snapshot_missing",
                isinstance(candidate.get("financial_snapshot"), Mapping),
            ),
            ("prior_low_below_zero", prior_low is not None and prior_low >= 0),
            (
                "prior_market_failed_rate_high",
                failed_rate is not None and failed_rate < 0.35,
            ),
        )
        if not passed
    ]
    core_gap = gap is not None and 2 <= gap < 5
    core_turnover = turnover is not None and 10 <= turnover < 20
    return {
        "two_to_three_quality_tier": "A" if core_gap and core_turnover else "B",
        "two_to_three_risk_count": len(risks),
        "two_to_three_risk_flags": risks,
    }


def _two_to_three_rank_adjustment(candidate: Mapping[str, object]) -> float:
    quality = _two_to_three_quality(candidate)
    prior_board = candidate.get("prior_board")
    board = prior_board if isinstance(prior_board, Mapping) else {}
    open_times = _number(board.get("open_times"))
    amount = _number(candidate.get("prior_amount_ratio_5d"))
    prior_low = _number(candidate.get("prior_low_change_pct"))
    failed_rate = _number(candidate.get("prior_market_failed_rate"))
    promotion = _number(candidate.get("prior_market_two_to_three_rate"))
    score = 30.0 if quality["two_to_three_quality_tier"] == "A" else 0.0
    score += 12.0 if open_times is not None and 3 <= open_times <= 6 else 0.0
    score += 8.0 if amount is not None and 1.2 <= amount < 2 else 0.0
    score += 6.0 if isinstance(candidate.get("financial_snapshot"), Mapping) else 0.0
    score += 6.0 if prior_low is not None and prior_low >= 0 else 0.0
    score += 6.0 if failed_rate is not None and failed_rate < 0.35 else 0.0
    score += 6.0 if promotion is not None and promotion >= 0.30 else 0.0
    score -= float(quality["two_to_three_risk_count"]) * 8.0
    return score


def _lane_rank_score(
    candidate: Mapping[str, object],
    lane: str,
    setup_type: str | None,
) -> float:
    heat = _number(candidate.get("prior_industry_heat_score")) or 0
    leader_rank = _number(candidate.get("prior_industry_leader_rank")) or 10
    gene = min(_number(candidate.get("prior_limit_count_126")) or 0, 6)
    position = _number(candidate.get("prior_position_120"))
    pullback = abs(min(_number(candidate.get("pullback_from_prior_limit_pct")) or 0, 0))
    gap = _number(candidate.get("auction_gap_pct")) or 0
    amount = _number(candidate.get("prior_amount_ratio_5d")) or 0
    if lane == "first_board":
        entry_quality = first_board_entry_quality_score(candidate)
        score = entry_quality if entry_quality is not None else 0.0
    elif lane == "one_to_two":
        score = heat * 0.35 - leader_rank * 4 + min(amount, 3) * 6
        score += max(0, 8 - abs(gap - 3.5) * 2)
    elif lane == "two_to_three":
        score = heat * 0.4 - leader_rank * 5 + min(amount, 3) * 5
        score += 12 if setup_type == "weak_to_strong" else 7
        score += _two_to_three_rank_adjustment(candidate)
    else:
        score = heat * 0.45 - leader_rank * 7 + min(gene, 5) * 3
        score += 8 if setup_type == "high_board_weak_to_strong" else 4
    return round(score, 4)


def _display_sort_key(candidate: Mapping[str, object], lane: str) -> tuple[object, ...]:
    decision_order = {"eligible": 0, "watch": 1, "blocked": 2}
    if lane == "first_board":
        return (
            decision_order.get(str(candidate.get("decision")), 3),
            str(candidate.get("signal_time") or "99:99:99"),
            -float(candidate.get("rank_score") or 0),
            str(candidate.get("vt_symbol") or ""),
        )
    return (
        decision_order.get(str(candidate.get("decision")), 3),
        -float(candidate.get("rank_score") or 0),
        str(candidate.get("vt_symbol") or ""),
    )


def _action(lane: str, decision: str, candidate: Mapping[str, object]) -> str:
    if decision == "blocked":
        return "pass"
    if decision == "watch":
        return "observe"
    if lane == "first_board":
        path = candidate.get("path_prefix")
        reseals = _integer(path.get("reseal_count")) if isinstance(path, Mapping) else 0
        return "buy_reseal" if reseals else "buy_first_board"
    return "buy_auction"


def _time_value(value: object) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return time.fromisoformat(text[:8])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _integer(value: object) -> int:
    number = _number(value)
    return int(number) if number is not None else 0


def _integer_or_none(value: object) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None
