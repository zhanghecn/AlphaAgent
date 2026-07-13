"""Pure live recommendation rules for the limit-up execution desk."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.domain import is_eligible_main_board

SHANGHAI = ZoneInfo("Asia/Shanghai")
MIN_SEAL_AMOUNT_RETENTION_RATIO = 0.7
MAX_CONSECUTIVE_SNAPSHOT_GAP_MINUTES = 2
ACTIVE_TIMING_STATES = {
    "GOLD_ACTIVE",
    "SILVER_ACTIVE",
    "GOLD_FADING",
    "SILVER_FADING",
}
_FACTOR_LABELS = {
    "sector_core": "板块核心",
    "prior_board_changed_hands_and_resealed": "前板换手回封",
    "prior_board_full_turnover_reseal": "前板充分换手回封",
    "prior_amount_ratio_balanced": "前板温和放量",
    "third_board_weak_to_strong": "三板弱转强",
    "prior_divergence_next_auction_strength": "前日分歧次日转强",
    "high_board_weak_to_strong": "高板弱转强",
}
_SETUP_LABELS = {
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
    """Recompute sector leaders and market Top5 from the current snapshot."""

    eligible: list[dict[str, object]] = []
    for raw in candidates:
        candidate = dict(raw)
        symbol = str(candidate.get("vt_symbol") or "")
        name = str(candidate.get("name") or "")
        sector_id = str(candidate.get("sector_id") or "")
        if not sector_id or not is_eligible_main_board(symbol, name):
            continue
        eligible.append(candidate)

    _attach_relative_ranks(eligible)
    by_sector: dict[str, list[dict[str, object]]] = defaultdict(list)
    for candidate in eligible:
        candidate["leadership_score"] = round(_leadership_score(candidate), 4)
        by_sector[str(candidate.get("sector_id") or "")].append(candidate)

    sector_front: list[dict[str, object]] = []
    for sector_rows in by_sector.values():
        ordered = sorted(sector_rows, key=_rank_key)
        for sector_rank, candidate in enumerate(ordered[:2], start=1):
            candidate["sector_dragon_rank"] = sector_rank
            sector_front.append(candidate)

    market_front = sorted(sector_front, key=_rank_key)[: max(int(limit), 0)]
    for market_rank, candidate in enumerate(market_front, start=1):
        candidate["market_dragon_rank"] = market_rank
    return market_front


def build_live_recommendations(
    candidates: Sequence[Mapping[str, object]],
    market_context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None = None,
) -> dict[str, object]:
    stage = session_stage(captured_at)
    market_gate = _market_gate(market_context, stage)
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
            _now_signal(candidate, stage, market_gate, captured_at, stable_minutes)
        )
        lanes["tail"].append(
            _tail_signal(candidate, stage, market_gate, captured_at, stable_minutes)
        )
        lanes["next_auction"].append(
            _auction_plan(candidate, market_gate, captured_at, stable_minutes)
        )

    return {
        "captured_at": _local_datetime(captured_at).isoformat(),
        "session_stage": stage,
        "market_gate": market_gate,
        "lanes": lanes,
    }


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
        + change_pct * 1.5
        + turnover_score
        + volume_score
        + float(candidate.get("sector_flow_rank") or 0.0) * 8.0
        + float(candidate.get("stock_flow_rank") or 0.0) * 8.0
        + seal_score
    )


def _market_gate(context: Mapping[str, object], stage: str) -> dict[str, object]:
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
    repair_confirmed = bool(
        not auction_stage
        and sealed_count >= 5
        and failed_rate is not None
        and failed_rate <= 0.35
        and sealed_change > 0
        and failed_change < 0
    )
    reasons: list[str] = []
    if stage == "closed":
        reasons.append("当前为非交易时段")
    if not auction_stage and sealed_count < 5:
        reasons.append("主板封板家数不足5只")
    if not auction_stage and failed_rate is not None and failed_rate > 0.35:
        reasons.append(f"实时炸板率{failed_rate * 100:.1f}%超过35%")
    if prior_weak and not repair_confirmed:
        reasons.append("D-1情绪偏弱且盘中尚未确认修复")
    return {
        "passed": not reasons,
        "sealed_count": sealed_count,
        "failed_count": failed_count,
        "failed_rate": round(failed_rate, 4) if failed_rate is not None else None,
        "sealed_change": sealed_change,
        "failed_change": failed_change,
        "repair_confirmed": repair_confirmed,
        "timing_state": timing_state,
        "timing_used": timing_used,
        "sentiment_phase": sentiment_phase,
        "reasons": reasons,
    }


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
    board_level = _integer(candidate.get("board_level"), 1)
    state = str(candidate.get("state") or "")
    open_times = _integer(candidate.get("open_times"), 0)
    lane_reasons = _lane_execution_reasons(candidate)
    auction_stage = stage in {"auction_watch", "auction"}
    execution_reasons = _candidate_execution_reasons(
        candidate,
        require_expansion=not auction_stage,
    )
    board_allowed = board_level <= 2 or (
        auction_stage and candidate.get("lane_decision") == "eligible"
    )
    gate_passed = (
        bool(market_gate.get("passed"))
        and board_allowed
        and not lane_reasons
        and not execution_reasons
    )

    if gate_passed and stage == "auction_watch":
        gap = _number(candidate.get("auction_gap_pct"))
        entry_kind = "auction"
        if gap is None:
            action, reason = "observe", "竞价数据待确认"
        elif 1 <= gap <= 7:
            action, reason = "observe", "竞价强度接近触发区间，09:20后再确认"
        else:
            reason = "竞价涨幅不在1%-7%观察区间"
    elif gate_passed and stage == "auction":
        gap = _number(candidate.get("auction_gap_pct"))
        if gap is not None and 1 <= gap <= 7:
            reason = _auction_entry_reason(candidate)
            action, entry_kind = "buy_now", "auction"
        else:
            reason = "竞价涨幅不在1%-7%观察区间"
    elif gate_passed and stage in {"morning", "afternoon"}:
        if state == "resealed" and open_times >= 5:
            action, entry_kind, reason = "buy_now", "reseal", f"已完成{open_times}次换手回封"
        elif state == "near_limit" and _sweep_ready(candidate):
            action, entry_kind, reason = "buy_now", "sweep", _sweep_entry_reason(candidate)
        elif state in {"sealed", "resealed", "near_limit"}:
            action, entry_kind, reason = "wait_tail", "wait", "先观察回封和封单稳定性"
    elif gate_passed and stage == "tail" and stable_minutes >= 2 and state in {"sealed", "resealed"}:
        action, entry_kind, reason = "buy_now", "tail_seal", f"尾盘连续封住{stable_minutes}分钟"

    if not bool(market_gate.get("passed")):
        reason = "；".join(str(item) for item in market_gate.get("reasons") or [])
    elif lane_reasons:
        reason = "；".join(lane_reasons)
    elif board_level > 2 and not (
        auction_stage and candidate.get("lane_decision") == "eligible"
    ):
        reason = "三板及以上没有L2队列证据"
    elif execution_reasons:
        reason = "；".join(execution_reasons)
    return _signal(
        candidate,
        action,
        entry_kind,
        reason,
        captured_at,
        stable_minutes,
        stage,
        market_gate,
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
    lane_reasons = _lane_execution_reasons(candidate)
    execution_reasons = _candidate_execution_reasons(candidate, require_expansion=True)
    eligible = (
        bool(market_gate.get("passed"))
        and board_level <= 2
        and state in {"sealed", "resealed"}
        and not lane_reasons
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
        )
    return _signal(
        candidate,
        "pass",
        "none",
        "；".join([*lane_reasons, *execution_reasons])
        if lane_reasons or execution_reasons
        else "不满足尾盘低板封住条件",
        captured_at,
        stable_minutes,
        stage,
        market_gate,
    )


def _auction_plan(
    candidate: Mapping[str, object],
    market_gate: Mapping[str, object],
    captured_at: datetime,
    stable_minutes: int,
) -> dict[str, object]:
    state = str(candidate.get("state") or "")
    board_level = _integer(candidate.get("board_level"), 1)
    lane_reasons = _lane_execution_reasons(candidate)
    execution_reasons = _candidate_execution_reasons(candidate, require_expansion=True)
    if (
        bool(market_gate.get("passed"))
        and board_level <= 2
        and state in {"sealed", "resealed"}
        and not lane_reasons
        and not execution_reasons
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
            "next_auction",
            "next_auction",
            f"保留至明早竞价观察{target_board}板，竞价强度通过对应战法硬门才转买入",
            captured_at,
            stable_minutes,
            session_stage(captured_at),
            market_gate,
        )
    return _signal(
        candidate,
        "pass",
        "none",
        "；".join([*lane_reasons, *execution_reasons])
        if lane_reasons or execution_reasons
        else "未形成次日竞价计划",
        captured_at,
        stable_minutes,
        session_stage(captured_at),
        market_gate,
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
) -> dict[str, object]:
    trigger_price = (
        _number(candidate.get("last_price"))
        if entry_kind == "auction"
        else _number(candidate.get("limit_price"))
    )
    valid_at = _local_datetime(captured_at).isoformat()
    buy_instruction = _buy_condition(entry_kind, action)
    sell_instruction = _sell_condition(candidate)
    return {
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
        "setup_tags": list(candidate.get("setup_tags") or []),
        "setup_confidence": candidate.get("setup_confidence"),
        "lane_blockers": list(candidate.get("lane_blockers") or []),
        "lane_favorable_factors": list(candidate.get("lane_favorable_factors") or []),
        "lane_quality_tier": candidate.get("lane_quality_tier"),
        "lane_risk_count": candidate.get("lane_risk_count"),
        "lane_risk_flags": list(candidate.get("lane_risk_flags") or []),
        "seal_gate_passed": candidate.get("lane_seal_gate_passed"),
        "premium_gate_passed": candidate.get("lane_premium_gate_passed"),
        "state": candidate.get("state"),
        "open_times": _integer(candidate.get("open_times"), 0),
        "leadership_score": _number(candidate.get("leadership_score")),
        "first_limit_time": candidate.get("first_limit_time"),
        "last_limit_time": candidate.get("last_limit_time"),
        "session_low_change_pct": _number(candidate.get("session_low_change_pct")),
        "distance_to_limit_pct": _number(candidate.get("distance_to_limit_pct")),
        "sector_touch_count": _integer(candidate.get("sector_touch_count"), 0),
        "sector_heat": _number(candidate.get("sector_heat")),
        "sector_main_net_inflow": _number(candidate.get("sector_main_net_inflow")),
        "stock_main_net_inflow": _number(candidate.get("stock_main_net_inflow")),
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
        "signal_state": _signal_state(action, entry_kind, stage),
        "execution_permission": "research_only",
        "strategy_name": _strategy_name(candidate),
        "selection_reasons": _selection_reasons(candidate, reason),
        "trigger_checks": _trigger_checks(
            candidate,
            market_gate,
            entry_kind,
            valid_at,
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


def _signal_state(action: str, entry_kind: str, stage: str) -> str:
    if action == "buy_now":
        return "trigger_ready"
    if action == "observe":
        return "approaching_trigger" if entry_kind == "auction" else "observing"
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
    factors = [
        _FACTOR_LABELS.get(str(value), str(value))
        for value in candidate.get("lane_favorable_factors") or []
    ][:4]
    return factors or [fallback_reason or "等待交易条件确认"]


def _trigger_checks(
    candidate: Mapping[str, object],
    market_gate: Mapping[str, object],
    entry_kind: str,
    evidence_time: str,
) -> list[dict[str, object]]:
    market_passed = bool(market_gate.get("passed"))
    market_reasons = [str(value) for value in market_gate.get("reasons") or []]
    lane_passed = candidate.get("lane_decision") in (None, "eligible")
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
            return "09:20-09:24竞价强度、板位、板块和情绪硬门保持通过后触发研究买点"
        return "09:25竞价强度、板位、板块和情绪硬门保持通过后执行"
    if entry_kind in {"sweep", "reseal"}:
        return "价格触及涨停且封单、换手、回封稳定性保持通过后执行"
    if entry_kind in {"tail_seal", "tail_watch"} or action == "wait_tail":
        return "14:30后连续封板至少2分钟且封单未明显缩水后执行"
    if entry_kind == "next_auction" or action == "next_auction":
        return "次日09:25竞价强度、板块和情绪硬门通过后执行"
    return "当前条件不成立，不执行买入"


def _sell_condition(candidate: Mapping[str, object]) -> str:
    lane = str(candidate.get("board_lane") or "")
    if lane == "high_board":
        return "D+1 09:25先评估高板竞价兑现优势；未触发则15:00退出"
    return "D+1 09:25由动态退出策略评估；无竞价兑现优势则15:00退出"


def _cancel_checks(entry_kind: str) -> list[str]:
    if entry_kind in {"auction", "next_auction"}:
        return ["竞价低于1%或高于7%", "跌出动态Top5", "市场门关闭"]
    if entry_kind in {"sweep", "reseal", "tail_seal", "tail_watch", "wait"}:
        return ["再次开板", "封单一分钟缩水超过30%", "板块扩散转弱或市场门关闭"]
    return ["买点未成立"]


def _auction_entry_reason(candidate: Mapping[str, object]) -> str:
    lane = str(candidate.get("board_lane") or "")
    if lane == "high_board":
        return "前日分歧回封，今日竞价1%-5%弱转强"
    if lane == "two_to_three":
        return "二板结构通过，竞价确认三板弱转强"
    if lane == "one_to_two":
        return "首板质量通过，竞价确认一进二"
    return (
        "昨日核心板竞价强度处于可参与区间"
        if bool(candidate.get("previous_limit_up"))
        else "主线前排竞价处于首板观察区间"
    )


def _sweep_entry_reason(candidate: Mapping[str, object]) -> str:
    support_score = _number(candidate.get("lane_support_score"))
    quality_score = _number(candidate.get("lane_entry_quality_score"))
    if (
        candidate.get("board_lane") == "first_board"
        and support_score is not None
    ):
        quality_text = (
            f"、综合{quality_score:.0f}分" if quality_score is not None else ""
        )
        return f"10点后接近涨停，封板门{support_score:.0f}分{quality_text}，强触板基因与利润增长通过"
    return "接近涨停且板块扩散与热度同步"


def _lane_execution_reasons(candidate: Mapping[str, object]) -> list[str]:
    decision = candidate.get("lane_decision")
    if decision in (None, "eligible"):
        return []
    blockers = candidate.get("lane_blockers")
    blockers = blockers if isinstance(blockers, Sequence) else []
    labels = {
        "high_board_prior_divergence_missing": "高板只做前日分歧回封后的竞价弱转强",
        "high_board_not_sector_core": "高板不是板块龙一",
        "high_board_requires_l2": "高板盘中接力缺少L2队列证据",
        "limit_up_gene_missing": "半年内缺少涨停基因",
        "first_board_touch_gene_weak": "半年触板不足6次",
        "financial_report_unavailable": "缺少信号日前已披露财报",
        "first_board_profit_growth_weak": "点时净利润同比低于10%",
        "first_board_repair_setup_missing": "D-1炸板率未达到分歧修复观察条件",
        "low_position_missing": "不属于低位或充分回调后的首次涨停",
        "first_touch_too_early": "首板首次触板早于10点",
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
    result = [labels.get(str(blocker), str(blocker)) for blocker in blockers]
    return result or ["该板位战法硬门未通过"]


def _board_lane(board_level: int) -> str:
    if board_level <= 1:
        return "first_board"
    if board_level == 2:
        return "one_to_two"
    if board_level == 3:
        return "two_to_three"
    return "high_board"


def _sweep_ready(candidate: Mapping[str, object]) -> bool:
    distance = _number(candidate.get("distance_to_limit_pct"))
    return bool(
        distance is not None
        and 0 <= distance <= 1
        and _integer(candidate.get("sector_touch_count"), 0) >= 3
        and (_number(candidate.get("sector_heat")) or 0.0) >= 60
    )


def _candidate_execution_reasons(
    candidate: Mapping[str, object],
    *,
    require_expansion: bool,
) -> list[str]:
    reasons: list[str] = []
    sector_heat = _number(candidate.get("sector_heat"))
    sector_flow = _number(candidate.get("sector_main_net_inflow"))
    stock_flow = _number(candidate.get("stock_main_net_inflow"))
    turnover_rate = _number(candidate.get("turnover_rate"))
    seal_retention = _number(candidate.get("seal_amount_retention_ratio"))
    seal_change = _number(candidate.get("seal_amount_change_pct"))
    if sector_heat is None or sector_heat < 45:
        reasons.append("板块热度不足45")
    if require_expansion and _integer(candidate.get("sector_touch_count"), 0) < 2:
        reasons.append("板块触板少于2只")
    if sector_flow is None:
        reasons.append("板块资金数据缺失")
    elif sector_flow <= 0:
        reasons.append("板块主力净流出")
    if stock_flow is None:
        reasons.append("个股资金数据缺失")
    elif stock_flow <= 0:
        reasons.append("个股主力净流出")
    if turnover_rate is None or not 2 <= turnover_rate <= 30:
        reasons.append("换手率不在2%-30%")
    if seal_retention is not None and seal_retention < MIN_SEAL_AMOUNT_RETENTION_RATIO:
        shrink_pct = abs(seal_change) if seal_change is not None else (1 - seal_retention) * 100
        reasons.append(f"封单较上一快照缩水{shrink_pct:.1f}%")
    return reasons


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
    return local.replace(hour=14, minute=57, second=0, microsecond=0).isoformat()


def _cancel_condition(entry_kind: str) -> str:
    if entry_kind in {"sweep", "reseal", "tail_seal", "tail_watch", "wait"}:
        return "再次开板、封单一分钟缩水超过30%、跌出动态Top5、板块扩散转弱或实时炸板率超过35%"
    if entry_kind in {"auction", "next_auction"}:
        return "竞价低于1%、高于7%、跌出动态Top5或市场门关闭"
    return "买点未成立"


def _rank_key(candidate: Mapping[str, object]) -> tuple[float, str]:
    return (-float(candidate.get("leadership_score") or 0.0), str(candidate.get("vt_symbol") or ""))


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
