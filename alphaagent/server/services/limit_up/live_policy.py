"""Pure live recommendation rules for the limit-up execution desk."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.domain import is_eligible_main_board
from alphaagent.server.services.limit_up.lane_research import (
    FIRST_BOARD_MOMENTUM_MIN_SCORE,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
MIN_SEAL_AMOUNT_RETENTION_RATIO = 0.7
MAX_CONSECUTIVE_SNAPSHOT_GAP_MINUTES = 2
BASE_MIN_SECTOR_HEAT = 45.0
BASE_MIN_SECTOR_TOUCH_COUNT = 2
SWEEP_MAX_DISTANCE_PCT = 1.0
SWEEP_MIN_SECTOR_HEAT = 60.0
SWEEP_MIN_SECTOR_TOUCH_COUNT = 3
MIN_TURNOVER_RATE = 2.0
MAX_TURNOVER_RATE = 30.0
CONCEPT_MAX_AGE_SECONDS = 45
CONCEPT_MIN_COVERAGE_RATIO = 0.90
CONCEPT_MIN_STRONG_5_COUNT = 2
CONCEPT_MAX_LEADER_RANK = 3
MATERIAL_NEGATIVE_FLOW_RATIO = -5.0
MATERIAL_NEGATIVE_FLOW_AMOUNT = -100_000_000.0
ACTIVE_TIMING_STATES = {
    "GOLD_ACTIVE",
    "SILVER_ACTIVE",
    "GOLD_FADING",
    "SILVER_FADING",
}
_FACTOR_LABELS = {
    "weak_market_theme_attack_setup": "强题材龙一/龙二承接",
    "sector_core": "板块核心",
    "prior_board_changed_hands_and_resealed": "前板换手回封",
    "prior_board_full_turnover_reseal": "前板充分换手回封",
    "prior_amount_ratio_balanced": "前板温和放量",
    "third_board_weak_to_strong": "三板弱转强",
    "prior_divergence_next_auction_strength": "前日分歧次日转强",
    "high_board_weak_to_strong": "高板弱转强",
}
_SETUP_LABELS = {
    "weak_market_theme_attack": "弱市题材进攻",
    "sandwich_board": "夹板",
    "return_board": "回马板",
    "weak_to_strong_breakout": "弱转强突破",
    "dragon_first_negative_relay": "龙首阴接力",
    "dragon_weak_to_strong": "龙头弱转强",
    "anti_nuclear_board": "反核板",
}
_LANE_LABELS = {
    "first_board": "首板",
    "one_to_two": "一进二",
    "two_to_three": "二进三",
    "high_board": "高板",
}
_DYNAMIC_LANE_BLOCKERS = {
    "first_touch_too_early",
    "industry_heat_unavailable",
    "intraday_support_unavailable",
    "intraday_support_breakdown",
    "first_board_local_setup_unconfirmed",
    "intraday_support_out_of_range",
    "auction_gap_out_of_range",
}


def session_stage(captured_at: datetime) -> str:
    local = _local_datetime(captured_at)
    if local.weekday() >= 5:
        return "closed"
    minute = local.hour * 60 + local.minute
    if minute < 9 * 60 + 15:
        return "preopen"
    if minute < 9 * 60 + 20:
        return "auction_watch"
    if minute < 9 * 60 + 30:
        return "auction"
    if minute <= 11 * 60 + 30:
        return "morning"
    if minute < 13 * 60:
        return "lunch"
    if minute < 14 * 60 + 30:
        return "afternoon"
    if minute <= 14 * 60 + 57:
        return "tail"
    if minute < 15 * 60:
        return "close_auction"
    return "closed"


def rank_live_candidates(
    candidates: Sequence[Mapping[str, object]],
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Rank every eligible candidate; ``limit`` only bounds the returned view."""

    eligible: list[dict[str, object]] = []
    for raw in candidates:
        candidate = dict(raw)
        symbol = str(candidate.get("vt_symbol") or "")
        name = str(candidate.get("name") or "")
        if not is_eligible_main_board(symbol, name):
            continue
        eligible.append(candidate)

    _attach_relative_ranks(eligible)
    by_sector: dict[str, list[dict[str, object]]] = defaultdict(list)
    for candidate in eligible:
        candidate["leadership_score"] = round(_leadership_score(candidate), 4)
        group_id = str(
            candidate.get("concept_id")
            or candidate.get("sector_id")
            or "unclassified"
        )
        by_sector[group_id].append(candidate)

    for sector_rows in by_sector.values():
        ordered = sorted(sector_rows, key=_rank_key)
        for sector_rank, candidate in enumerate(ordered, start=1):
            candidate["sector_dragon_rank"] = sector_rank

    market_front = sorted(eligible, key=_rank_key)[: max(int(limit), 0)]
    for market_rank, candidate in enumerate(market_front, start=1):
        candidate["market_dragon_rank"] = market_rank
    return market_front


def rank_live_opportunities(
    candidates: Sequence[Mapping[str, object]],
    *,
    limit: int = 5,
) -> list[dict[str, object]]:
    """Prefer candidates that can still be acted on over already sealed boards."""

    ranked = sorted(
        (dict(candidate) for candidate in candidates),
        key=_opportunity_rank_key,
    )[: max(int(limit), 0)]
    for market_rank, candidate in enumerate(ranked, start=1):
        candidate["market_dragon_rank"] = market_rank
    return ranked


def build_live_recommendations(
    candidates: Sequence[Mapping[str, object]],
    market_context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None = None,
    *,
    market_gate: Mapping[str, object] | None = None,
) -> dict[str, object]:
    stage = session_stage(captured_at)
    resolved_market_gate = dict(
        market_gate
        or build_live_market_gate(
            market_context,
            captured_at,
            previous_snapshot,
        )
    )
    previous_by_symbol = _previous_candidates(previous_snapshot)
    lanes: dict[str, list[dict[str, object]]] = {
        "now": [],
        "tail": [],
        "next_auction": [],
    }

    for raw in candidates:
        candidate = dict(raw)
        symbol = str(candidate.get("vt_symbol") or "")
        stable_minutes = _stable_minutes(
            candidate,
            previous_by_symbol.get(symbol),
            captured_at,
            previous_snapshot,
        )
        lanes["now"].append(
            _now_signal(
                candidate,
                stage,
                resolved_market_gate,
                captured_at,
                stable_minutes,
            )
        )
        lanes["tail"].append(
            _tail_signal(
                candidate,
                stage,
                resolved_market_gate,
                captured_at,
                stable_minutes,
            )
        )
        lanes["next_auction"].append(
            _auction_plan(
                candidate,
                resolved_market_gate,
                captured_at,
                stable_minutes,
            )
        )

    return {
        "captured_at": _local_datetime(captured_at).isoformat(),
        "session_stage": stage,
        "market_gate": resolved_market_gate,
        "lanes": lanes,
    }


def build_live_market_gate(
    context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build the same-day market gate shared by lane ranking and live signals."""

    return _market_gate(
        context,
        session_stage(captured_at),
        captured_at,
        previous_snapshot,
    )


def _leadership_score(candidate: Mapping[str, object]) -> float:
    state = str(candidate.get("state") or "")
    state_score = {
        "resealed": 32.0,
        "sealed": 24.0,
        "near_limit": 15.0,
        "opened": 6.0,
        "failed": 2.0,
    }.get(state, 0.0)
    board_level = _integer(candidate.get("board_level"), 1)
    board_score = {1: 12.0, 2: 14.0, 3: 8.0}.get(board_level, 4.0)
    open_times = max(_integer(candidate.get("open_times"), 0), 0)
    reseal_score = _reseal_path_score(open_times) if state == "resealed" else 0.0
    sector_touch = min(max(_integer(candidate.get("sector_touch_count"), 0), 0), 6)
    sector_heat = min(max(_number(candidate.get("sector_heat")) or 0.0, 0.0), 100.0)
    concept_strength = min(
        max(_number(candidate.get("concept_strength_score")) or 0.0, 0.0),
        100.0,
    )
    concept_state_score = {
        "launch": 14.0,
        "warming": 8.0,
        "observe": 1.0,
        "ebb": -12.0,
    }.get(str(candidate.get("concept_state") or ""), 0.0)
    concept_leader_rank = _integer(candidate.get("concept_leader_rank"), 0)
    concept_leader_score = (
        max(CONCEPT_MAX_LEADER_RANK + 1 - concept_leader_rank, 0) * 3.0
        if concept_leader_rank > 0
        else 0.0
    )
    change_pct = min(max(_number(candidate.get("change_pct")) or 0.0, 0.0), 10.0)
    turnover_rate = _number(candidate.get("turnover_rate"))
    turnover_score = 5.0 if turnover_rate is not None and 2 <= turnover_rate <= 20 else 1.0
    volume_ratio = _number(candidate.get("volume_ratio"))
    volume_score = 3.0 if volume_ratio is not None and 1 <= volume_ratio <= 3 else 0.0
    seal_ratio = _number(candidate.get("seal_to_turnover_ratio")) or 0.0
    seal_score = min(max(seal_ratio * 100, 0.0), 6.0)
    return (
        state_score
        + board_score
        + reseal_score
        + sector_touch * 3.0
        + sector_heat * 0.12
        + concept_strength * 0.18
        + concept_state_score
        + concept_leader_score
        + change_pct * 1.5
        + turnover_score
        + volume_score
        + float(candidate.get("sector_flow_rank") or 0.0) * 8.0
        + float(candidate.get("stock_flow_rank") or 0.0) * 8.0
        + seal_score
    )


def _market_gate(
    context: Mapping[str, object],
    stage: str,
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None,
) -> dict[str, object]:
    sealed_count = _integer(context.get("sealed_count"), 0)
    failed_count = _integer(context.get("failed_count"), 0)
    failed_rate = _number(context.get("failed_rate"))
    if failed_rate is None and sealed_count + failed_count:
        failed_rate = failed_count / (sealed_count + failed_count)
    timing = context.get("timing")
    timing = timing if isinstance(timing, Mapping) else {}
    timing_state = str(timing.get("signal_state") or "NONE")
    timing_used = timing_state in ACTIVE_TIMING_STATES
    sentiment = context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    sentiment_phase = str(sentiment.get("phase") or "unknown")
    sealed_change = _integer(context.get("sealed_change"), 0)
    failed_change = _integer(context.get("failed_change"), 0)
    prior_weak = sentiment_phase in {"ice", "ebb", "retreat", "decline"}
    auction_stage = stage in {"auction_watch", "auction"}
    health_reasons: list[str] = []
    if not auction_stage and sealed_count < 5:
        health_reasons.append("主板封板家数不足5只")

    current_at = _local_datetime(captured_at).isoformat()
    previous_gate = _same_day_previous_gate(previous_snapshot, captured_at)
    previous_state = str(previous_gate.get("repair_state") or "")
    if not previous_state:
        previous_state = (
            "repair_confirmed"
            if previous_gate.get("repair_confirmed") is True
            else "pending_repair"
        )
    previous_confirmed = previous_state == "repair_confirmed"
    instant_repair = bool(
        prior_weak
        and not auction_stage
        and not health_reasons
        and sealed_change > 0
        and failed_change < 0
    )

    if not prior_weak:
        repair_state = "not_required"
    elif instant_repair:
        repair_state = "repair_confirmed"
    elif previous_confirmed and health_reasons:
        repair_state = "repair_revoked"
    elif previous_confirmed:
        repair_state = "repair_confirmed"
    elif previous_state == "repair_revoked":
        repair_state = "repair_revoked"
    else:
        repair_state = "pending_repair"

    repair_confirmed = repair_state in {"not_required", "repair_confirmed"}
    repair_confirmed_at = (
        current_at
        if instant_repair
        else previous_gate.get("repair_confirmed_at")
    )
    repair_evidence_at = (
        current_at
        if instant_repair
        else previous_gate.get("repair_evidence_at")
        or repair_confirmed_at
    )
    repair_revoked_reason = (
        "；".join(health_reasons)
        if previous_confirmed and health_reasons
        else previous_gate.get("repair_revoked_reason")
        if repair_state == "repair_revoked"
        else None
    )

    reasons: list[str] = []
    if stage == "closed":
        reasons.append("当前为非交易时段")
    reasons.extend(health_reasons)
    return {
        "passed": not reasons,
        "sealed_count": sealed_count,
        "failed_count": failed_count,
        "failed_rate": round(failed_rate, 4) if failed_rate is not None else None,
        "sealed_change": sealed_change,
        "failed_change": failed_change,
        "repair_confirmed": repair_confirmed,
        "repair_state": repair_state,
        "repair_confirmed_at": repair_confirmed_at,
        "repair_evidence_at": repair_evidence_at,
        "repair_revoked_reason": repair_revoked_reason,
        "timing_state": timing_state,
        "timing_used": timing_used,
        "sentiment_phase": sentiment_phase,
        "reasons": reasons,
    }


def _same_day_previous_gate(
    previous_snapshot: Mapping[str, object] | None,
    captured_at: datetime,
) -> Mapping[str, object]:
    if not isinstance(previous_snapshot, Mapping):
        return {}
    try:
        previous_at = _local_datetime(
            datetime.fromisoformat(str(previous_snapshot.get("captured_at") or ""))
        )
    except (TypeError, ValueError):
        return {}
    if previous_at.date() != _local_datetime(captured_at).date():
        return {}
    recommendations = previous_snapshot.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    gate = recommendations.get("market_gate")
    return gate if isinstance(gate, Mapping) else {}


def _now_signal(
    candidate: Mapping[str, object],
    stage: str,
    market_gate: Mapping[str, object],
    captured_at: datetime,
    stable_minutes: int,
) -> dict[str, object]:
    action = "pass"
    entry_kind = "none"
    reason = "当前买点不成立"
    signal_state: str | None = None
    blocking_scope = "none"
    pending_reasons: list[str] = []
    board_level = _integer(candidate.get("board_level"), 1)
    state = str(candidate.get("state") or "")
    hard_lane_reasons, dynamic_lane_reasons = _lane_execution_reason_groups(candidate)
    auction_stage = stage in {"auction_watch", "auction"}
    first_board_momentum_state = (
        board_level == 1
        and state in {"near_limit", "sealed", "resealed"}
        and stage in {"morning", "afternoon"}
    )
    if auction_stage:
        evaluated_entry_kind = "auction"
    elif first_board_momentum_state:
        evaluated_entry_kind = "momentum"
    elif stage in {"morning", "afternoon"} and state == "near_limit":
        evaluated_entry_kind = "sweep"
    elif stage in {"morning", "afternoon"} and state == "resealed":
        evaluated_entry_kind = "reseal"
    elif stage == "tail":
        evaluated_entry_kind = "tail_seal"
    else:
        evaluated_entry_kind = "base"
    execution_checks = _candidate_execution_checks(
        candidate,
        require_expansion=not auction_stage,
        entry_kind=evaluated_entry_kind,
    )
    execution_reasons = _blocking_execution_reasons(execution_checks)
    board_allowed = board_level == 1 or (
        board_level >= 3 and candidate.get("lane_decision") == "eligible"
    )
    structural_reasons = list(hard_lane_reasons)
    if not board_allowed:
        structural_reasons.append("三板及以上盘中接力缺少L2队列证据")
    market_reasons = [str(item) for item in market_gate.get("reasons") or []]
    dynamic_reasons = [*dynamic_lane_reasons, *execution_reasons]

    if structural_reasons:
        reason = "；".join(structural_reasons)
        signal_state = "rejected"
        blocking_scope = "structural"
    elif market_reasons:
        reason = "；".join(market_reasons)
        blocking_scope = "market"
        pending_reasons = market_reasons
        if (state == "near_limit" or first_board_momentum_state) and stage in {
            "auction_watch",
            "auction",
            "morning",
            "afternoon",
        }:
            action = "observe"
            entry_kind = evaluated_entry_kind
            signal_state = _pretrigger_signal_state(candidate)
        elif state in {"sealed", "resealed"} and stage in {"morning", "afternoon"}:
            signal_state = "missed"
        else:
            signal_state = "observing"
    elif dynamic_reasons:
        reason = "；".join(dynamic_reasons)
        blocking_scope = "dynamic"
        pending_reasons = dynamic_reasons
        if (state == "near_limit" or first_board_momentum_state) and stage in {
            "auction_watch",
            "auction",
            "morning",
            "afternoon",
        }:
            action = "observe"
            entry_kind = evaluated_entry_kind
            signal_state = _pretrigger_signal_state(candidate)
        elif state in {"sealed", "resealed"} and stage in {"morning", "afternoon"}:
            signal_state = "missed"
        elif stage == "tail" and state in {"sealed", "resealed"}:
            action = "observe"
            entry_kind = "tail_watch"
            signal_state = "observing"
    elif stage == "auction_watch":
        gap = _number(candidate.get("auction_gap_pct"))
        entry_kind = "auction"
        if gap is None:
            action, reason = "observe", "竞价数据待确认"
        elif 1 <= gap <= 7:
            action, reason = "observe", "竞价强度接近触发区间，09:20后再确认"
        else:
            reason = "竞价涨幅不在1%-7%观察区间"
    elif stage == "auction":
        gap = _number(candidate.get("auction_gap_pct"))
        if gap is not None and 1 <= gap <= 7:
            action, entry_kind = "observe", "auction"
            reason = "竞价只确认观察资格，10:00后等待盘中触板或回封"
            signal_state = "approaching_trigger"
        else:
            reason = "竞价涨幅不在1%-7%观察区间"
    elif stage in {"morning", "afternoon"}:
        if board_level >= 3 and candidate.get("relay_trigger_status") == "ready":
            entry_kind = str(candidate.get("relay_trigger_kind") or "first_touch")
            trigger_label = "首次触板" if entry_kind == "first_touch" else "首次可观察回封"
            action, reason = "buy_now", f"{trigger_label}触发接力候选"
        elif board_level >= 3 and state == "near_limit":
            action, entry_kind = "observe", "sweep"
            reason = "接力资格已通过，等待窗口内首次触板"
            signal_state = "approaching_trigger"
        elif board_level >= 3 and state == "failed":
            action, entry_kind = "observe", "reseal"
            reason = "已经触板开板，等待窗口内首次可观察回封"
            signal_state = "observing"
        elif board_level >= 3:
            action, entry_kind = "observe", "wait"
            reason = "没有新的窗口内首次触板或回封，不追已经封住的板"
            signal_state = "observing"
        elif first_board_momentum_state:
            action, entry_kind = "buy_now", "momentum"
            reason = _momentum_entry_reason(candidate)
    elif stage == "tail" and stable_minutes >= 2 and state in {"sealed", "resealed"}:
        action, entry_kind, reason = "buy_now", "tail_seal", f"尾盘连续封住{stable_minutes}分钟"

    return _signal(
        candidate,
        action,
        entry_kind,
        reason,
        captured_at,
        stable_minutes,
        stage,
        market_gate,
        signal_state=signal_state,
        blocking_scope=blocking_scope,
        pending_reasons=pending_reasons,
        execution_checks=execution_checks,
        lane_gate_passed=not hard_lane_reasons,
    )


def _tail_signal(
    candidate: Mapping[str, object],
    stage: str,
    market_gate: Mapping[str, object],
    captured_at: datetime,
    stable_minutes: int,
) -> dict[str, object]:
    state = str(candidate.get("state") or "")
    board_level = _integer(candidate.get("board_level"), 1)
    hard_lane_reasons, dynamic_lane_reasons = _lane_execution_reason_groups(candidate)
    execution_checks = _candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="tail_seal",
    )
    execution_reasons = _blocking_execution_reasons(execution_checks)
    eligible = (
        bool(market_gate.get("passed"))
        and board_level <= 2
        and state in {"sealed", "resealed"}
        and not hard_lane_reasons
        and not dynamic_lane_reasons
        and not execution_reasons
    )
    if stage == "tail" and eligible and stable_minutes >= 2:
        return _signal(
            candidate,
            "buy_now",
            "tail_seal",
            f"尾盘连续封住{stable_minutes}分钟",
            captured_at,
            stable_minutes,
            stage,
            market_gate,
            execution_checks=execution_checks,
            lane_gate_passed=True,
        )
    if eligible:
        return _signal(
            candidate,
            "wait_tail",
            "tail_watch",
            "等待14:30后连续快照确认",
            captured_at,
            stable_minutes,
            stage,
            market_gate,
            execution_checks=execution_checks,
            lane_gate_passed=True,
        )
    market_reasons = [str(item) for item in market_gate.get("reasons") or []]
    structural_reasons = list(hard_lane_reasons)
    if board_level > 2:
        structural_reasons.append("三板及以上不走低板尾盘通道")
    pending_reasons = [
        *market_reasons,
        *dynamic_lane_reasons,
        *execution_reasons,
    ]
    reasons = structural_reasons or pending_reasons
    return _signal(
        candidate,
        "pass",
        "none",
        "；".join(reasons) if reasons else "不满足尾盘低板封住条件",
        captured_at,
        stable_minutes,
        stage,
        market_gate,
        signal_state="rejected" if structural_reasons else "observing",
        blocking_scope=(
            "structural"
            if structural_reasons
            else "market"
            if market_reasons
            else "dynamic"
        ),
        pending_reasons=pending_reasons,
        execution_checks=execution_checks,
        lane_gate_passed=not hard_lane_reasons,
    )


def _auction_plan(
    candidate: Mapping[str, object],
    market_gate: Mapping[str, object],
    captured_at: datetime,
    stable_minutes: int,
) -> dict[str, object]:
    state = str(candidate.get("state") or "")
    board_level = _integer(candidate.get("board_level"), 1)
    hard_lane_reasons, dynamic_lane_reasons = _lane_execution_reason_groups(candidate)
    execution_checks = _candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="next_auction",
    )
    execution_reasons = _blocking_execution_reasons(execution_checks)
    active_hard_reasons = [
        reason for reason in hard_lane_reasons if reason != "one_to_two_removed"
    ]
    if (
        board_level >= 2
        and state in {"sealed", "resealed"}
        and not active_hard_reasons
    ):
        target_board = board_level + 1
        target_candidate = {
            **dict(candidate),
            "source_board_level": board_level,
            "board_level": target_board,
            "board_lane": _board_lane(target_board),
        }
        return _signal(
            target_candidate,
            "observe",
            "next_session_watch",
            f"保留为下一交易日{target_board}板观察，10:00后等待盘中触板或回封",
            captured_at,
            stable_minutes,
            session_stage(captured_at),
            market_gate,
            execution_checks=execution_checks,
            lane_gate_passed=True,
        )
    market_reasons = [str(item) for item in market_gate.get("reasons") or []]
    structural_reasons = list(active_hard_reasons)
    if board_level < 2:
        structural_reasons.append("首板不生成一进二观察计划")
    pending_reasons = [
        *market_reasons,
        *dynamic_lane_reasons,
        *execution_reasons,
    ]
    reasons = structural_reasons or pending_reasons
    return _signal(
        candidate,
        "pass",
        "none",
        "；".join(reasons) if reasons else "未形成次日竞价计划",
        captured_at,
        stable_minutes,
        session_stage(captured_at),
        market_gate,
        signal_state="rejected" if structural_reasons else "observing",
        blocking_scope=(
            "structural"
            if structural_reasons
            else "market"
            if market_reasons
            else "dynamic"
        ),
        pending_reasons=pending_reasons,
        execution_checks=execution_checks,
        lane_gate_passed=not hard_lane_reasons,
    )


def _signal(
    candidate: Mapping[str, object],
    action: str,
    entry_kind: str,
    reason: str,
    captured_at: datetime,
    stable_minutes: int,
    stage: str,
    market_gate: Mapping[str, object],
    *,
    signal_state: str | None = None,
    blocking_scope: str = "none",
    pending_reasons: Sequence[str] = (),
    execution_checks: Sequence[Mapping[str, object]] = (),
    lane_gate_passed: bool | None = None,
) -> dict[str, object]:
    trigger_price = (
        _number(candidate.get("last_price"))
        if entry_kind in {"auction", "momentum"}
        else _number(candidate.get("limit_price"))
    )
    valid_at = _local_datetime(captured_at).isoformat()
    buy_instruction = _buy_condition(entry_kind, action)
    sell_instruction = _sell_condition(candidate)
    signal = {
        "vt_symbol": candidate.get("vt_symbol"),
        "name": candidate.get("name"),
        "sector_id": candidate.get("sector_id"),
        "sector_name": candidate.get("sector_name"),
        "market_dragon_rank": candidate.get("market_dragon_rank"),
        "sector_dragon_rank": candidate.get("sector_dragon_rank"),
        "board_level": _integer(candidate.get("board_level"), 1),
        "board_lane": candidate.get("board_lane")
        or _board_lane(_integer(candidate.get("board_level"), 1)),
        "lane_decision": candidate.get("lane_decision"),
        "lane_setup_type": candidate.get("lane_setup_type"),
        "first_board_route": candidate.get("first_board_route"),
        "setup_tags": list(candidate.get("setup_tags") or []),
        "setup_confidence": candidate.get("setup_confidence"),
        "lane_blockers": list(candidate.get("lane_blockers") or []),
        "lane_blocker_reasons": _lane_execution_reasons(candidate),
        "lane_favorable_factors": list(candidate.get("lane_favorable_factors") or []),
        "lane_quality_tier": candidate.get("lane_quality_tier"),
        "lane_risk_count": candidate.get("lane_risk_count"),
        "lane_risk_flags": list(candidate.get("lane_risk_flags") or []),
        "lane_rank_score": _number(candidate.get("lane_rank_score")),
        "lane_support_score": _number(candidate.get("lane_support_score")),
        "lane_entry_quality_score": _number(
            candidate.get("lane_entry_quality_score")
        ),
        "portfolio_selected": candidate.get("portfolio_selected") is True,
        "seal_gate_passed": candidate.get("lane_seal_gate_passed"),
        "momentum_gate_passed": (
            (_number(candidate.get("lane_support_score")) or 0.0)
            >= FIRST_BOARD_MOMENTUM_MIN_SCORE
        )
        if _integer(candidate.get("board_level"), 1) == 1
        else None,
        "premium_gate_passed": candidate.get("lane_premium_gate_passed"),
        "state": candidate.get("state"),
        "open_times": _integer(candidate.get("open_times"), 0),
        "leadership_score": _number(candidate.get("leadership_score")),
        "first_limit_time": candidate.get("first_limit_time"),
        "last_limit_time": candidate.get("last_limit_time"),
        "last_price": _number(candidate.get("last_price")),
        "limit_price": _number(candidate.get("limit_price")),
        "change_pct": _number(candidate.get("change_pct")),
        "session_low_change_pct": _number(candidate.get("session_low_change_pct")),
        "distance_to_limit_pct": _number(candidate.get("distance_to_limit_pct")),
        "prior_limit_count_126": candidate.get("prior_limit_count_126"),
        "prior_industry_turnover_ratio_5d": _number(
            candidate.get("prior_industry_turnover_ratio_5d")
        ),
        "sector_touch_count": _integer(candidate.get("sector_touch_count"), 0),
        "sector_heat": _number(candidate.get("sector_heat")),
        "sector_main_net_inflow": _number(candidate.get("sector_main_net_inflow")),
        "stock_main_net_inflow": _number(candidate.get("stock_main_net_inflow")),
        "concept_id": candidate.get("concept_id"),
        "concept_name": candidate.get("concept_name"),
        "concept_state": candidate.get("concept_state"),
        "concept_launch_confirmed": candidate.get("concept_state") == "launch",
        "concept_strength_score": _number(candidate.get("concept_strength_score")),
        "concept_strength_rank": candidate.get("concept_strength_rank"),
        "concept_strength_percentile": _number(
            candidate.get("concept_strength_percentile")
        ),
        "concept_leader_rank": candidate.get("concept_leader_rank"),
        "concept_coverage_ratio": _number(candidate.get("concept_coverage_ratio")),
        "concept_strong_5_count": candidate.get("concept_strong_5_count"),
        "concept_near_limit_count": candidate.get("concept_near_limit_count"),
        "concept_sealed_count": candidate.get("concept_sealed_count"),
        "concept_failed_count": candidate.get("concept_failed_count"),
        "concept_change_acceleration_3m": _number(
            candidate.get("concept_change_acceleration_3m")
        ),
        "concept_turnover_acceleration_3m": _number(
            candidate.get("concept_turnover_acceleration_3m")
        ),
        "concept_snapshot_age_seconds": _number(
            candidate.get("concept_snapshot_age_seconds")
        ),
        "sector_route": _selected_sector_route(execution_checks),
        "turnover_rate": _number(candidate.get("turnover_rate")),
        "volume_ratio": _number(candidate.get("volume_ratio")),
        "seal_amount": _number(candidate.get("seal_amount")),
        "seal_to_turnover_ratio": _number(candidate.get("seal_to_turnover_ratio")),
        "seal_amount_retention_ratio": _number(
            candidate.get("seal_amount_retention_ratio")
        ),
        "seal_amount_change_pct": _number(candidate.get("seal_amount_change_pct")),
        "action": action,
        "entry_kind": entry_kind,
        "trigger_price": trigger_price,
        "valid_at": valid_at,
        "valid_until": _valid_until(captured_at, entry_kind),
        "execution_state": _execution_state(action),
        "signal_state": signal_state
        or _signal_state(candidate, action, entry_kind, stage),
        "blocking_scope": blocking_scope,
        "pending_reasons": list(pending_reasons),
        "seen_before_seal": candidate.get("seen_before_seal") is True,
        "missed_preseal_entry": candidate.get("missed_preseal_entry") is True,
        "execution_permission": "research_only",
        "strategy_name": _strategy_name(candidate),
        "selection_reasons": _selection_reasons(candidate, reason),
        "trigger_checks": _trigger_checks(
            candidate,
            market_gate,
            entry_kind,
            valid_at,
            execution_checks,
            lane_gate_passed,
        ),
        "buy_condition": buy_instruction,
        "sell_condition": sell_instruction,
        "buy_instruction": buy_instruction,
        "sell_instruction": sell_instruction,
        "state_updated_at": valid_at,
        "stable_minutes": stable_minutes,
        "reason": reason,
        "cancel_condition": _cancel_condition(entry_kind),
        "cancel_checks": _cancel_checks(entry_kind),
        "execution_confidence": "proxy_without_l2",
    }
    if str(signal["board_lane"]) == "first_board" and candidate.get("warmup_group"):
        signal.update(
            {
                "warmup_group": candidate.get("warmup_group"),
                "warmup_group_name": candidate.get("warmup_group_name"),
                "warmup_state": candidate.get("warmup_state"),
                "warmup_score": _number(candidate.get("warmup_score")),
                "warmup_confidence": candidate.get("warmup_confidence"),
                "warmup_leader_rank": candidate.get("warmup_leader_rank"),
                "warmup_main_net_inflow": _number(
                    candidate.get("warmup_main_net_inflow")
                ),
                "warmup_main_net_inflow_ratio": _number(
                    candidate.get("warmup_main_net_inflow_ratio")
                ),
                "warmup_trend_state": candidate.get("warmup_trend_state"),
                "warmup_flow_trade_date": candidate.get("warmup_flow_trade_date"),
                "warmup_touch_count": candidate.get("warmup_touch_count"),
                "warmup_execution_effect": "none_research_only",
            }
        )
    if str(signal["board_lane"]) == "first_board" and candidate.get(
        "rotation_shadow_state"
    ):
        signal.update(
            {
                "rotation_shadow_state": candidate.get("rotation_shadow_state"),
                "rotation_shadow_passed": candidate.get("rotation_shadow_passed")
                is True,
                "rotation_shadow_reason_codes": list(
                    candidate.get("rotation_shadow_reason_codes") or []
                ),
                "rotation_shadow_reason": candidate.get("rotation_shadow_reason"),
                "rotation_shadow_signal_time": candidate.get(
                    "rotation_shadow_signal_time"
                ),
                "rotation_shadow_entry_price": _number(
                    candidate.get("rotation_shadow_entry_price")
                ),
                "rotation_shadow_execution_effect": "none_research_only",
            }
        )
    return signal


def _signal_state(
    candidate: Mapping[str, object],
    action: str,
    entry_kind: str,
    stage: str,
) -> str:
    if action == "buy_now":
        return "trigger_ready"
    if (
        candidate.get("missed_preseal_entry") is True
        and stage in {"morning", "afternoon"}
        and entry_kind != "momentum"
    ):
        return "missed"
    if action == "observe":
        return (
            "approaching_trigger"
            if entry_kind in {"auction", "momentum", "sweep", "reseal"}
            else "observing"
        )
    if action in {"wait_tail", "next_auction"}:
        return "pending_auction" if action == "next_auction" else "observing"
    if stage in {"preopen", "auction_watch"} and entry_kind == "auction":
        return "pending_auction"
    return "invalidated"


def _strategy_name(candidate: Mapping[str, object]) -> str:
    lane = str(candidate.get("board_lane") or _board_lane(_integer(candidate.get("board_level"), 1)))
    label = _LANE_LABELS.get(lane, "接力")
    setups = [
        _SETUP_LABELS.get(str(value), str(value))
        for value in candidate.get("setup_tags") or []
    ]
    return f"{label}·{'/'.join(setups)}" if setups else label


def _selection_reasons(
    candidate: Mapping[str, object],
    fallback_reason: str,
) -> list[str]:
    raw_factors = [str(value) for value in candidate.get("lane_favorable_factors") or []]
    priority = [
        value
        for value in ("weak_market_theme_attack_setup",)
        if value in raw_factors
    ]
    factors = [
        _FACTOR_LABELS.get(value, value)
        for value in [*priority, *(value for value in raw_factors if value not in priority)][:4]
    ]
    return factors or [fallback_reason or "等待交易条件确认"]


def _trigger_checks(
    candidate: Mapping[str, object],
    market_gate: Mapping[str, object],
    entry_kind: str,
    evidence_time: str,
    execution_checks: Sequence[Mapping[str, object]] = (),
    lane_gate_passed: bool | None = None,
) -> list[dict[str, object]]:
    market_passed = bool(market_gate.get("passed"))
    market_reasons = [str(value) for value in market_gate.get("reasons") or []]
    lane_passed = (
        lane_gate_passed
        if lane_gate_passed is not None
        else candidate.get("lane_decision") in (None, "eligible")
    )
    checks: list[dict[str, object]] = [
        {
            "code": "market_gate",
            "label": "市场环境",
            "status": "passed" if market_passed else "failed",
            "observed": "允许出手" if market_passed else "；".join(market_reasons),
            "required": "市场门保持通过",
            "evidence_time": evidence_time,
        },
        {
            "code": "lane_gate",
            "label": "板位结构",
            "status": "passed" if lane_passed else "failed",
            "observed": "战法硬门通过" if lane_passed else "战法硬门未通过",
            "required": "对应板位硬门通过",
            "evidence_time": evidence_time,
        },
    ]
    if entry_kind == "auction":
        gap = _number(candidate.get("auction_gap_pct"))
        status = "pending" if gap is None else "passed" if 1 <= gap <= 7 else "failed"
        checks.append(
            {
                "code": "auction_gap",
                "label": "竞价强度",
                "status": status,
                "observed": None if gap is None else f"{gap:.2f}%",
                "required": "1%-7%",
                "evidence_time": evidence_time if gap is not None else None,
            }
        )
    for raw_check in execution_checks:
        check = {
            key: raw_check.get(key)
            for key in ("code", "label", "status", "observed", "required")
        }
        check["evidence_time"] = (
            evidence_time if raw_check.get("observed") is not None else None
        )
        checks.append(check)
    return checks


def _execution_state(action: str) -> str:
    if action == "buy_now":
        return "actionable"
    if action == "observe":
        return "watch"
    if action in {"wait_tail", "next_auction"}:
        return "waiting"
    return "cancelled"


def _buy_condition(entry_kind: str, action: str) -> str:
    if entry_kind == "auction":
        if action == "observe":
            return "竞价仅形成观察资格，10:00后等待盘中首次触板或可观察回封"
        return "09:25竞价强度、板位、板块和情绪硬门保持通过后执行"
    if entry_kind == "momentum":
        return "盘中动能、板块、历史质量和风险门保持通过；已封板时仅尝试涨停价排队"
    if entry_kind in {"sweep", "reseal"}:
        return "价格触及涨停且封单、换手、回封稳定性保持通过后执行"
    if entry_kind in {"tail_seal", "tail_watch"} or action == "wait_tail":
        return "尾盘形态仅观察，不执行买入；下一交易日按正式窗口重新评估"
    if entry_kind == "next_auction" or action == "next_auction":
        return "次日09:25竞价强度、板块和情绪硬门通过后执行"
    return "当前条件不成立，不执行买入"


def _sell_condition(candidate: Mapping[str, object]) -> str:
    del candidate
    return "D+1尾盘按官方收盘价统一卖出"


def _cancel_checks(entry_kind: str) -> list[str]:
    if entry_kind in {"auction", "next_auction"}:
        return ["竞价低于1%或高于7%", "跌出动态Top5", "市场门关闭"]
    if entry_kind in {"momentum", "sweep", "reseal", "tail_seal", "tail_watch", "wait"}:
        return ["再次开板", "封单一分钟缩水超过30%", "板块扩散转弱或市场门关闭"]
    return ["买点未成立"]


def _momentum_entry_reason(candidate: Mapping[str, object]) -> str:
    support_score = _number(candidate.get("lane_support_score"))
    quality_score = _number(candidate.get("lane_entry_quality_score"))
    state = str(candidate.get("state") or "")
    if state in {"sealed", "resealed"}:
        state_text = "已回封" if state == "resealed" else "已封板"
        return (
            f"动能{support_score:.0f}分，{state_text}且全部质量门通过，"
            "可尝试涨停价排队"
            if support_score is not None
            else f"{state_text}且全部质量门通过，可尝试涨停价排队"
        )
    if "weak_market_theme_attack" in set(candidate.get("setup_tags") or []):
        concept_name = str(candidate.get("concept_name") or candidate.get("sector_name") or "强题材")
        leader_rank = _integer(candidate.get("concept_leader_rank"), 0)
        leader_text = f"龙{leader_rank}" if leader_rank in {1, 2} else "前排"
        support_text = f"，承接{support_score:.0f}分" if support_score is not None else ""
        return f"弱市题材进攻，{concept_name}{leader_text}{support_text}"
    if (
        candidate.get("board_lane") == "first_board"
        and support_score is not None
    ):
        quality_text = (
            f"、综合{quality_score:.0f}分" if quality_score is not None else ""
        )
        return f"盘中动能{support_score:.0f}分{quality_text}，强触板基因与利润增长通过"
    return "盘中动能、板块扩散与历史质量同步通过"


def _lane_execution_reasons(candidate: Mapping[str, object]) -> list[str]:
    hard_reasons, dynamic_reasons = _lane_execution_reason_groups(candidate)
    return [*hard_reasons, *dynamic_reasons]


def _lane_execution_reason_groups(
    candidate: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    decision = candidate.get("lane_decision")
    if decision in (None, "eligible"):
        return [], []
    blockers = candidate.get("lane_blockers")
    blockers = (
        blockers
        if isinstance(blockers, Sequence) and not isinstance(blockers, (str, bytes))
        else []
    )
    labels = {
        "high_board_prior_divergence_missing": "高板只做前日分歧回封后的竞价弱转强",
        "high_board_not_sector_core": "高板不是板块龙一",
        "high_board_requires_l2": "高板盘中接力缺少L2队列证据",
        "limit_up_gene_missing": "半年内缺少涨停基因",
        "first_board_touch_gene_weak": "半年触板不足6次",
        "financial_report_unavailable": "本地财报数据未覆盖",
        "first_board_profit_growth_weak": "点时净利润同比低于10%",
        "first_board_repair_setup_missing": "D-1炸板率未达到分歧修复观察条件",
        "low_position_missing": "不属于低位或充分回调后的首次涨停",
        "first_touch_too_early": "10点前仅观察，等待10点后确认",
        "industry_heat_unavailable": "首板缺少实时板块热度",
        "intraday_support_unavailable": "首板缺少信号时点盘中承接路径",
        "intraday_support_breakdown": "首板临近触板路径出现明显失速或回落",
        "first_board_local_setup_unconfirmed": "首板触板前15分钟承接或首次触板结构未确认",
        "first_board_quality_below_threshold": "首板局部承接、板块和涨停基因综合分不足",
        "intraday_support_out_of_range": "旧版首板盘中承接区间未通过",
        "auction_gap_out_of_range": "竞价强度不在战法区间",
        "third_board_setup_unconfirmed": "三板分歧转强结构未确认",
        "two_to_three_risk_stack": "二进三可见风险达到4项",
        "fundamental_risk": "已披露基本面风险未通过",
        "lane_features_unavailable": "战法前置证据未就绪",
        "prior_board_evidence_missing": "缺少前一板盘口证据",
        "prior_board_path_incomplete": "前一板首封、开板或回封证据不完整",
        "industry_leader_rank_unverified": "行业龙位未确认",
        "stock_not_industry_top2": "不属于行业龙一或龙二",
    }
    hard_reasons: list[str] = []
    dynamic_reasons: list[str] = []
    for blocker in blockers:
        code = str(blocker)
        reason = labels.get(code, code)
        target = dynamic_reasons if code in _DYNAMIC_LANE_BLOCKERS else hard_reasons
        target.append(reason)
    if not hard_reasons and not dynamic_reasons:
        hard_reasons.append("该板位战法硬门未通过")
    return hard_reasons, dynamic_reasons


def _board_lane(board_level: int) -> str:
    if board_level <= 1:
        return "first_board"
    if board_level == 2:
        return "one_to_two"
    if board_level == 3:
        return "two_to_three"
    return "high_board"


def _sweep_ready(candidate: Mapping[str, object]) -> bool:
    return not _candidate_execution_reasons(
        candidate,
        require_expansion=True,
        entry_kind="sweep",
    )


def _candidate_execution_reasons(
    candidate: Mapping[str, object],
    *,
    require_expansion: bool,
    entry_kind: str = "base",
) -> list[str]:
    return _blocking_execution_reasons(
        _candidate_execution_checks(
            candidate,
            require_expansion=require_expansion,
            entry_kind=entry_kind,
        )
    )


def build_first_board_execution_checks_at_time(
    candidate: Mapping[str, object],
) -> list[dict[str, object]]:
    """Return the formal first-board checks for one visible market frame."""

    return _candidate_execution_checks(
        {**dict(candidate), "board_lane": "first_board", "board_level": 1},
        require_expansion=True,
        entry_kind="momentum",
    )


def _blocking_execution_reasons(
    checks: Sequence[Mapping[str, object]],
) -> list[str]:
    return [
        str(check.get("reason") or check.get("label") or "执行条件未满足")
        for check in checks
        if check.get("blocking", True) is not False
        and check.get("status") in {"pending", "failed"}
    ]


def _candidate_execution_checks(
    candidate: Mapping[str, object],
    *,
    require_expansion: bool,
    entry_kind: str,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    lane = str(
        candidate.get("board_lane")
        or _board_lane(_integer(candidate.get("board_level"), 1))
    )
    momentum = entry_kind == "momentum" and lane == "first_board"
    sweep = entry_kind == "sweep"
    if momentum:
        momentum_score = _number(candidate.get("lane_support_score"))
        momentum_passed = bool(
            momentum_score is not None
            and momentum_score >= FIRST_BOARD_MOMENTUM_MIN_SCORE
        )
        checks.append(
            {
                "code": "stock_momentum",
                "label": "个股动能",
                "status": "passed" if momentum_passed else "pending",
                "observed": (
                    None if momentum_score is None else f"{momentum_score:.1f}分"
                ),
                "required": f">={FIRST_BOARD_MOMENTUM_MIN_SCORE:g}分",
                "reason": (
                    "盘中动能数据缺失"
                    if momentum_score is None
                    else (
                        f"盘中动能{momentum_score:.1f}/"
                        f"{FIRST_BOARD_MOMENTUM_MIN_SCORE:g}分"
                    )
                ),
            }
        )
    if sweep:
        distance = _number(candidate.get("distance_to_limit_pct"))
        distance_passed = bool(
            distance is not None and 0 <= distance <= SWEEP_MAX_DISTANCE_PCT
        )
        checks.append(
            {
                "code": "limit_distance",
                "label": "距涨停",
                "status": "passed" if distance_passed else "pending",
                "observed": None if distance is None else f"{distance:.2f}%",
                "required": f"0%-{SWEEP_MAX_DISTANCE_PCT:g}%",
                "reason": (
                    "距涨停数据缺失"
                    if distance is None
                    else f"距涨停约{distance:.2f}%，等待进入{SWEEP_MAX_DISTANCE_PCT:g}%扫板触发区"
                ),
            }
        )

    stock_flow = _number(candidate.get("stock_main_net_inflow"))
    stock_flow_ratio = _number(candidate.get("stock_main_net_inflow_ratio"))
    turnover_rate = _number(candidate.get("turnover_rate"))
    seal_retention = _number(candidate.get("seal_amount_retention_ratio"))
    seal_change = _number(candidate.get("seal_amount_change_pct"))
    momentum_or_sweep = momentum or sweep
    heat_required = (
        SWEEP_MIN_SECTOR_HEAT if momentum_or_sweep else BASE_MIN_SECTOR_HEAT
    )
    touch_required = (
        SWEEP_MIN_SECTOR_TOUCH_COUNT
        if momentum_or_sweep
        else BASE_MIN_SECTOR_TOUCH_COUNT
    )
    uses_realtime_concept = "concept_state" in candidate
    if lane == "first_board":
        _append_realtime_sector_route_checks(
            checks,
            candidate,
            heat_required=heat_required,
            touch_required=touch_required,
            require_expansion=require_expansion,
        )
    elif uses_realtime_concept:
        _append_realtime_concept_checks(checks, candidate)
        checks.append(_sector_flow_check(candidate))
    else:
        checks.extend(
            _legacy_sector_route_checks(
                candidate,
                heat_required=heat_required,
                touch_required=touch_required,
                require_expansion=require_expansion,
            )
        )
    checks.append(
        {
            "code": "stock_flow",
            "label": "个股资金",
            "status": _flow_check_status(stock_flow, stock_flow_ratio),
            "observed": stock_flow,
            "required": "严重净流出时否决",
            "reason": _flow_check_reason("个股", stock_flow, stock_flow_ratio),
        }
    )
    turnover_passed = bool(
        turnover_rate is not None
        and MIN_TURNOVER_RATE <= turnover_rate <= MAX_TURNOVER_RATE
    )
    checks.append(
        {
            "code": "turnover_rate",
            "label": "换手率",
            "status": "passed" if turnover_passed else "pending",
            "observed": None if turnover_rate is None else f"{turnover_rate:.2f}%",
            "required": f"{MIN_TURNOVER_RATE:g}%-{MAX_TURNOVER_RATE:g}%",
            "reason": f"换手率不在{MIN_TURNOVER_RATE:g}%-{MAX_TURNOVER_RATE:g}%",
        }
    )
    if seal_retention is not None:
        shrink_pct = abs(seal_change) if seal_change is not None else (1 - seal_retention) * 100
        checks.append(
            {
                "code": "seal_retention",
                "label": "封单稳定",
                "status": (
                    "passed"
                    if seal_retention >= MIN_SEAL_AMOUNT_RETENTION_RATIO
                    else "failed"
                ),
                "observed": f"{seal_retention * 100:.1f}%",
                "required": f">={MIN_SEAL_AMOUNT_RETENTION_RATIO * 100:.0f}%",
                "reason": f"封单较上一快照缩水{shrink_pct:.1f}%",
            }
        )
    return [_execution_check_contract(check, candidate) for check in checks]


def _execution_check_contract(
    check: Mapping[str, object],
    candidate: Mapping[str, object],
) -> dict[str, object]:
    code = str(check.get("code") or "unknown_execution_check")
    raw_parity = candidate.get("execution_check_parity")
    parity = raw_parity if isinstance(raw_parity, Mapping) else {}
    known_at = (
        candidate.get("decision_at")
        or candidate.get("evaluation_time")
        or candidate.get("signal_time")
    )
    return {
        **dict(check),
        "code": code,
        "known_at": known_at,
        "parity_status": str(parity.get(code) or "shared"),
        "blocking": check.get("blocking", True) is not False,
    }


def _append_realtime_sector_route_checks(
    checks: list[dict[str, object]],
    candidate: Mapping[str, object],
    *,
    heat_required: float,
    touch_required: int,
    require_expansion: bool,
) -> tuple[bool, bool]:
    industry_checks = _realtime_industry_route_checks(
        candidate,
        touch_required=touch_required,
        require_expansion=require_expansion,
    )
    concept_checks = _realtime_concept_launch_route_checks(candidate)
    industry_passed = _route_passed(industry_checks)
    concept_passed = _route_passed(concept_checks)
    checks.append(_d1_sector_heat_diagnostic(candidate, heat_required))
    checks.extend(_diagnostic_checks(industry_checks))
    checks.extend(_diagnostic_checks(concept_checks))

    if industry_passed:
        observed = "盘中行业路径通过"
    elif concept_passed:
        observed = "概念启动路径通过"
    else:
        observed = "两条实时路径均未通过"
    failed_checks = [
        check
        for check in [*industry_checks, *concept_checks]
        if check.get("status") not in {"passed", "informational"}
    ]
    checks.append(
        {
            "code": "sector_route",
            "label": "板块路径",
            "status": (
                "passed"
                if industry_passed or concept_passed
                else "failed"
                if any(check.get("status") == "failed" for check in failed_checks)
                else "pending"
            ),
            "observed": observed,
            "required": "盘中行业或概念启动任一路径通过",
            "reason": "；".join(
                str(check.get("reason") or check.get("label") or "板块条件未满足")
                for check in failed_checks[:4]
            )
            or "板块路径未通过",
            "blocking": True,
        }
    )
    return industry_passed, concept_passed


def _realtime_industry_route_checks(
    candidate: Mapping[str, object],
    *,
    touch_required: int,
    require_expansion: bool,
) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    if require_expansion:
        touch_count = _integer(candidate.get("sector_touch_count"), 0)
        checks.append(
            {
                "code": "sector_expansion",
                "label": "盘中行业扩散",
                "status": "passed" if touch_count >= touch_required else "pending",
                "observed": f"{touch_count}只",
                "required": f">={touch_required}只",
                "reason": f"盘中行业触板{touch_count}/{touch_required}只",
            }
        )

    flow_check = _sector_flow_check(candidate)
    if candidate.get("sector_flow_current") is not True:
        flow_check.update(
            {
                "status": "pending",
                "reason": "当日行业资金尚未就绪",
            }
        )
    elif _number(candidate.get("sector_main_net_inflow")) is None:
        flow_check.update(
            {
                "status": "pending",
                "reason": "当日行业资金数据缺失",
            }
        )
    flow_check["label"] = "盘中行业资金"
    checks.append(flow_check)
    return checks


def _realtime_concept_launch_route_checks(
    candidate: Mapping[str, object],
) -> list[dict[str, object]]:
    if "concept_state" not in candidate:
        return []
    checks = _realtime_concept_route_checks(candidate)
    state = str(candidate.get("concept_state") or "unavailable")
    for check in checks:
        if check.get("code") != "concept_state":
            continue
        check.update(
            {
                "label": "概念实时状态",
                "status": (
                    "passed"
                    if state == "launch"
                    else "failed"
                    if state == "ebb"
                    else "pending"
                ),
                "required": "launch",
                "reason": (
                    "概念正在退潮"
                    if state == "ebb"
                    else "概念实时状态不可用"
                    if state == "unavailable"
                    else "概念尚未从预热转为启动"
                    if state != "launch"
                    else "概念已全面启动"
                ),
            }
        )
        break
    return checks


def _d1_sector_heat_diagnostic(
    candidate: Mapping[str, object],
    heat_required: float,
) -> dict[str, object]:
    sector_heat = _number(candidate.get("sector_heat"))
    diagnostic_status = (
        "passed"
        if sector_heat is not None and sector_heat >= heat_required
        else "pending"
    )
    return {
        "code": "sector_heat",
        "label": "D-1行业热度",
        "status": "informational",
        "diagnostic_status": diagnostic_status,
        "observed": None if sector_heat is None else f"{sector_heat:.2f}",
        "required": "仅用于排序，不作为盘中买点门",
        "reason": (
            "D-1行业热度缺失"
            if sector_heat is None
            else f"D-1行业热度{sector_heat:.1f}，仅作先验参考"
        ),
        "blocking": False,
    }


def _legacy_sector_route_checks(
    candidate: Mapping[str, object],
    *,
    heat_required: float,
    touch_required: int,
    require_expansion: bool,
) -> list[dict[str, object]]:
    sector_heat = _number(candidate.get("sector_heat"))
    heat_passed = sector_heat is not None and sector_heat >= heat_required
    route_checks: list[dict[str, object]] = [
        {
            "code": "sector_heat",
            "label": "板块热度",
            "status": "passed" if heat_passed else "pending",
            "observed": None if sector_heat is None else f"{sector_heat:.2f}",
            "required": f">={heat_required:g}",
            "reason": (
                f"板块热度缺失（要求{heat_required:g}）"
                if sector_heat is None
                else f"板块热度{sector_heat:.1f}/{heat_required:g}"
            ),
        }
    ]
    if require_expansion:
        touch_count = _integer(candidate.get("sector_touch_count"), 0)
        route_checks.append(
            {
                "code": "sector_expansion",
                "label": "板块扩散",
                "status": "passed" if touch_count >= touch_required else "pending",
                "observed": f"{touch_count}只",
                "required": f">={touch_required}只",
                "reason": f"板块触板{touch_count}/{touch_required}只",
            }
        )
    route_checks.append(_sector_flow_check(candidate))
    return route_checks


def _sector_flow_check(candidate: Mapping[str, object]) -> dict[str, object]:
    sector_flow = _number(candidate.get("sector_main_net_inflow"))
    sector_flow_ratio = _number(candidate.get("sector_main_net_inflow_ratio"))
    return {
        "code": "sector_flow",
        "label": "板块资金",
        "status": _flow_check_status(sector_flow, sector_flow_ratio),
        "observed": sector_flow,
        "required": "严重净流出时否决",
        "reason": _flow_check_reason("板块", sector_flow, sector_flow_ratio),
    }


def _realtime_concept_route_checks(
    candidate: Mapping[str, object],
) -> list[dict[str, object]]:
    if "concept_state" not in candidate:
        return []
    route_checks: list[dict[str, object]] = []
    _append_realtime_concept_checks(route_checks, candidate)
    return route_checks


def _route_passed(checks: Sequence[Mapping[str, object]]) -> bool:
    return bool(checks) and all(
        check.get("status") in {"passed", "informational"}
        for check in checks
    )


def _diagnostic_checks(
    checks: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return [
        {
            **dict(check),
            "diagnostic_status": check.get("status"),
            "status": "informational",
            "blocking": False,
        }
        for check in checks
    ]


def _selected_sector_route(
    checks: Sequence[Mapping[str, object]],
) -> str | None:
    route = next(
        (check for check in checks if check.get("code") == "sector_route"),
        None,
    )
    observed = str(route.get("observed") or "") if route else ""
    return {
        "盘中行业路径通过": "realtime_industry",
        "概念启动路径通过": "realtime_concept_launch",
    }.get(observed)


def _append_realtime_concept_checks(
    checks: list[dict[str, object]],
    candidate: Mapping[str, object],
) -> None:
    if "concept_trigger_allowed" in candidate:
        source_ready = candidate.get("concept_trigger_allowed") is True
        checks.append(
            {
                "code": "concept_source_quality",
                "label": "概念全市场行情",
                "status": "passed" if source_ready else "failed",
                "observed": "通过" if source_ready else "未通过",
                "required": "来源交易日正确且全市场覆盖达标",
                "reason": "概念完整行情未通过交易日或全市场覆盖检查",
            }
        )
    age = _number(candidate.get("concept_snapshot_age_seconds"))
    coverage = _number(candidate.get("concept_coverage_ratio"))
    freshness_status = (
        "pending"
        if age is None or coverage is None
        else "failed"
        if age > CONCEPT_MAX_AGE_SECONDS
        else "pending"
        if coverage < CONCEPT_MIN_COVERAGE_RATIO
        else "passed"
    )
    checks.append(
        {
            "code": "concept_freshness",
            "label": "概念行情",
            "status": freshness_status,
            "observed": (
                None
                if age is None or coverage is None
                else f"{age:.0f}秒 / {coverage * 100:.1f}%"
            ),
            "required": (
                f"<={CONCEPT_MAX_AGE_SECONDS}秒且覆盖"
                f">={CONCEPT_MIN_COVERAGE_RATIO * 100:.0f}%"
            ),
            "reason": (
                "概念行情数据缺失"
                if age is None or coverage is None
                else f"概念行情已超过{CONCEPT_MAX_AGE_SECONDS}秒"
                if age > CONCEPT_MAX_AGE_SECONDS
                else f"概念行情覆盖率仅{coverage * 100:.1f}%"
            ),
        }
    )
    state = str(candidate.get("concept_state") or "unavailable")
    checks.append(
        {
            "code": "concept_state",
            "label": "概念共振",
            "status": (
                "passed"
                if state == "launch"
                else "failed"
                if state == "ebb"
                else "pending"
            ),
            "observed": state,
            "required": "launch",
            "reason": (
                "概念正在退潮"
                if state == "ebb"
                else "概念尚未从预热转为启动"
            ),
        }
    )
    strong_count = _integer(candidate.get("concept_strong_5_count"), 0)
    checks.append(
        {
            "code": "concept_diffusion",
            "label": "概念扩散",
            "status": "passed" if strong_count >= CONCEPT_MIN_STRONG_5_COUNT else "pending",
            "observed": f"{strong_count}只涨超5%",
            "required": f">={CONCEPT_MIN_STRONG_5_COUNT}只",
            "reason": (
                f"概念仅{strong_count}只涨超5%，"
                f"至少需要{CONCEPT_MIN_STRONG_5_COUNT}只"
            ),
        }
    )
    leader_rank = _integer(candidate.get("concept_leader_rank"), 0)
    checks.append(
        {
            "code": "concept_leader",
            "label": "概念龙头",
            "status": (
                "passed"
                if 1 <= leader_rank <= CONCEPT_MAX_LEADER_RANK
                else "pending"
            ),
            "observed": leader_rank or None,
            "required": f"龙1-龙{CONCEPT_MAX_LEADER_RANK}",
            "reason": (
                "概念龙头排名缺失"
                if leader_rank <= 0
                else f"当前为概念龙{leader_rank}，只观察前{CONCEPT_MAX_LEADER_RANK}"
            ),
        }
    )


def _flow_check_status(value: float | None, ratio: float | None) -> str:
    if value is None:
        return "informational"
    if (
        ratio is not None and ratio <= MATERIAL_NEGATIVE_FLOW_RATIO
    ) or value <= MATERIAL_NEGATIVE_FLOW_AMOUNT:
        return "failed"
    return "passed" if value >= 0 else "informational"


def _flow_check_reason(
    label: str,
    value: float | None,
    ratio: float | None,
) -> str:
    if value is None:
        return f"{label}资金数据缺失，仅作提示"
    if ratio is not None and ratio <= MATERIAL_NEGATIVE_FLOW_RATIO:
        return f"{label}主力净流出比例{ratio:.1f}%"
    if value <= MATERIAL_NEGATIVE_FLOW_AMOUNT:
        return f"{label}主力净流出{abs(value) / 100_000_000:.1f}亿元"
    return f"{label}资金为负但未达到否决阈值" if value < 0 else "资金方向正常"


def _pretrigger_signal_state(candidate: Mapping[str, object]) -> str:
    lane = str(
        candidate.get("board_lane")
        or _board_lane(_integer(candidate.get("board_level"), 1))
    )
    momentum_score = _number(candidate.get("lane_support_score"))
    if (
        lane == "first_board"
        and momentum_score is not None
        and momentum_score >= FIRST_BOARD_MOMENTUM_MIN_SCORE
    ):
        return "approaching_trigger"
    if lane == "first_board":
        if str(candidate.get("concept_state") or "") in {"warming", "launch"}:
            return "concept_warming"
        return "observing"
    distance = _number(candidate.get("distance_to_limit_pct"))
    if distance is not None and distance <= SWEEP_MAX_DISTANCE_PCT:
        return "approaching_trigger"
    if str(candidate.get("concept_state") or "") in {"warming", "launch"}:
        return "concept_warming"
    return "observing"


def _attach_relative_ranks(candidates: list[dict[str, object]]) -> None:
    sector_ranks = _relative_ranks(candidates, "sector_main_net_inflow")
    stock_ranks = _relative_ranks(candidates, "stock_main_net_inflow")
    for candidate in candidates:
        symbol = str(candidate.get("vt_symbol") or "")
        candidate["sector_flow_rank"] = sector_ranks.get(symbol, 0.0)
        candidate["stock_flow_rank"] = stock_ranks.get(symbol, 0.0)


def _relative_ranks(
    candidates: Sequence[Mapping[str, object]],
    field: str,
) -> dict[str, float]:
    values = sorted(
        {
            value
            for candidate in candidates
            if (value := _number(candidate.get(field))) is not None
        }
    )
    if not values:
        return {}
    denominator = max(len(values) - 1, 1)
    rank_by_value = {
        value: index / denominator if len(values) > 1 else 1.0
        for index, value in enumerate(values)
    }
    return {
        str(candidate.get("vt_symbol") or ""): rank_by_value.get(
            _number(candidate.get(field)),
            0.0,
        )
        for candidate in candidates
    }


def _reseal_path_score(open_times: int) -> float:
    if open_times <= 0:
        return 0.0
    if open_times <= 2:
        return 1.0
    if open_times <= 4:
        return 3.0
    if open_times <= 7:
        return 8.0
    if open_times <= 10:
        return 10.0
    return 6.0


def _previous_candidates(
    previous_snapshot: Mapping[str, object] | None,
) -> dict[str, Mapping[str, object]]:
    if not previous_snapshot:
        return {}
    rows = previous_snapshot.get("candidates")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return {}
    return {
        str(row.get("vt_symbol") or ""): row
        for row in rows
        if isinstance(row, Mapping) and row.get("vt_symbol")
    }


def _stable_minutes(
    current: Mapping[str, object],
    previous: Mapping[str, object] | None,
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None,
) -> int:
    explicit = _integer(current.get("stable_minutes"), -1)
    if explicit >= 0:
        return explicit
    if not previous or not previous_snapshot:
        return 0
    if str(current.get("state") or "") not in {"sealed", "resealed"}:
        return 0
    if str(previous.get("state") or "") not in {"sealed", "resealed"}:
        return 0
    previous_at = previous_snapshot.get("captured_at")
    try:
        parsed = datetime.fromisoformat(str(previous_at))
    except (TypeError, ValueError):
        return 0
    elapsed = _local_datetime(captured_at) - _local_datetime(parsed)
    elapsed_minutes = int(elapsed.total_seconds() // 60)
    if not 0 <= elapsed_minutes <= MAX_CONSECUTIVE_SNAPSHOT_GAP_MINUTES:
        return 0
    return elapsed_minutes


def _valid_until(captured_at: datetime, entry_kind: str) -> str:
    local = _local_datetime(captured_at)
    if entry_kind == "auction":
        return local.replace(hour=9, minute=30, second=0, microsecond=0).isoformat()
    if entry_kind == "next_auction":
        return "下一交易日09:30"
    cutoff = scheduled_execution.ENTRY_CUTOFF_TIME
    return local.replace(
        hour=cutoff.hour,
        minute=cutoff.minute,
        second=0,
        microsecond=0,
    ).isoformat()


def _cancel_condition(entry_kind: str) -> str:
    if entry_kind in {"momentum", "sweep", "reseal", "tail_seal", "tail_watch", "wait"}:
        return "再次开板、封单一分钟缩水超过30%、跌出动态Top5或板块扩散转弱"
    if entry_kind in {"auction", "next_auction"}:
        return "竞价低于1%、高于7%、跌出动态Top5或市场门关闭"
    return "买点未成立"


def _rank_key(candidate: Mapping[str, object]) -> tuple[float, str]:
    return (-float(candidate.get("leadership_score") or 0.0), str(candidate.get("vt_symbol") or ""))


def _opportunity_rank_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    state = str(candidate.get("state") or "")
    state_priority = {
        "near_limit": 0,
        "failed": 1,
        "resealed": 1,
        "sealed": 3,
    }.get(state, 4)
    decision_priority = {
        "eligible": 0,
        "watch": 1,
        "blocked": 3,
    }.get(str(candidate.get("lane_decision") or ""), 2)
    distance = _number(candidate.get("distance_to_limit_pct"))
    concept_state_priority = {
        "launch": 0,
        "warming": 1,
        "observe": 2,
        "unavailable": 3,
        "ebb": 4,
    }.get(str(candidate.get("concept_state") or "unavailable"), 3)
    return (
        state_priority + decision_priority,
        concept_state_priority,
        0 if candidate.get("portfolio_selected") is True else 1,
        _integer(candidate.get("concept_strength_rank"), 1_000_000),
        _integer(candidate.get("concept_leader_rank"), 1_000_000),
        distance if state == "near_limit" and distance is not None else 99.0,
        -(_number(candidate.get("lane_rank_score")) or 0.0),
        -(_number(candidate.get("leadership_score")) or 0.0),
        str(candidate.get("vt_symbol") or ""),
    )


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _integer(value: object, default: int) -> int:
    try:
        return int(float(value)) if value not in (None, "", "-") else default
    except (TypeError, ValueError):
        return default
