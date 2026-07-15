"""Persisted observations prepared for the next A-share trading session."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta
from typing import Literal, Mapping
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.db.session import DatabaseUnavailable
from alphaagent.server.services.limit_up.live_repository import (
    load_latest_daily_trade_date,
    load_latest_next_session_plan,
    load_live_context,
    save_snapshot,
)
from alphaagent.server.services.limit_up import scheduled_execution
from alphaagent.server.services.limit_up.versions import LIVE_STRATEGY_VERSION

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
PLAN_MODES = {
    "preliminary": "next_session_preliminary",
    "final": "next_session_final",
}
PLAN_LANE_LIMIT = 4
_NEXT_SESSION_WATCH_BLOCKERS = frozenset(
    {
        "market_retreat",
        "market_failed_rate_high",
        "auction_gap_out_of_range",
        "third_board_setup_unconfirmed",
        "two_to_three_risk_stack",
        "high_board_requires_l2",
        "one_to_two_removed",
    }
)

_WARMUP_LOCK = threading.Lock()
_WARMUP_THREAD: threading.Thread | None = None


def build_next_session_plan_snapshot(
    source_snapshot: Mapping[str, object],
    *,
    source_trade_date: date,
    captured_at: datetime,
    phase: Literal["preliminary", "final"],
) -> dict[str, object]:
    local_at = _local_datetime(captured_at)
    recommendations = source_snapshot.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    raw_rows = lanes.get("next_auction")
    raw_rows = raw_rows if isinstance(raw_rows, list) else []
    plan_sources = _plan_sources(raw_rows, source_snapshot.get("candidates"))
    rows = [_plan_signal(row, local_at) for row in plan_sources]
    quality = source_snapshot.get("data_quality")
    quality = dict(quality) if isinstance(quality, Mapping) else {}
    plan_metadata = {
        "source_trade_date": source_trade_date.isoformat(),
        "target_session": "next_trading_session",
        "plan_phase": phase,
    }
    snapshot = {
        "status": "ready" if rows else "empty",
        "trade_date": source_trade_date.isoformat(),
        "source_trade_date": source_trade_date.isoformat(),
        "target_session": "next_trading_session",
        "plan_phase": phase,
        "captured_at": local_at.isoformat(),
        "session_stage": "closed",
        "strategy_version": LIVE_STRATEGY_VERSION,
        "mode": PLAN_MODES[phase],
        "source": str(source_snapshot.get("source") or "unknown"),
        "source_updated_at": source_snapshot.get("source_updated_at"),
        "market_context": dict(source_snapshot.get("market_context") or {}),
        "candidates": list(source_snapshot.get("candidates") or []),
        "recommendations": {
            "captured_at": local_at.isoformat(),
            "session_stage": "closed",
            "market_gate": dict(recommendations.get("market_gate") or {}),
            "lanes": {"now": [], "tail": [], "next_auction": rows},
            "plan": plan_metadata,
            "execution_schedule": scheduled_execution.next_session_execution_clock(),
        },
        "data_quality": {
            **quality,
            "status": "ready" if rows else "empty",
            "is_stale": False,
            "execution_confidence": "research_only_without_l2",
            "snapshot_age_seconds": 0,
            "plan": plan_metadata,
            "limitations": [
                "盘后计划只形成观察资格，必须等待10:00后的首次触板或可观察回封。",
                "Tick/L2和冻结后前向证据未完成，执行许可保持research_only。",
            ],
        },
    }
    return jsonable_encoder(snapshot)


def refresh_next_session_plan(
    phase: Literal["preliminary", "final"],
    *,
    source_trade_date: date | None = None,
    captured_at: datetime | None = None,
    adapter: AkShareAdapter | None = None,
) -> dict[str, object]:
    local_at = _local_datetime(captured_at or datetime.now(SHANGHAI))
    live_adapter = adapter or AkShareAdapter()
    source_date = source_trade_date or load_latest_daily_trade_date(local_at.date())
    pools: Mapping[str, object] | None = None
    if (
        source_trade_date is None
        and local_at.weekday() < 5
        and local_at.time() >= time(15, 0)
        and (source_date is None or source_date < local_at.date())
    ):
        current_pools = live_adapter.limit_up_pools(local_at.strftime("%Y%m%d"))
        from alphaagent.server.services.limit_up.live_service import _parsed_date

        if _parsed_date(current_pools.get("trade_date")) == local_at.date():
            source_date = local_at.date()
            pools = current_pools
    if source_date is None:
        return {"status": "empty", "reason": "daily_history_unavailable"}
    existing = load_latest_next_session_plan(
        source_date,
        phase=phase,
        strategy_version=LIVE_STRATEGY_VERSION,
    )
    if existing is not None and _has_observations(existing):
        return existing

    if pools is None:
        pools = live_adapter.limit_up_pools(source_date.strftime("%Y%m%d"))
    source_snapshot = _source_snapshot_from_pools(pools, source_date)
    plan = build_next_session_plan_snapshot(
        source_snapshot,
        source_trade_date=source_date,
        captured_at=local_at,
        phase=phase,
    )
    return save_snapshot(plan)


def get_latest_next_session_plan() -> dict[str, object] | None:
    try:
        return load_latest_next_session_plan(strategy_version=LIVE_STRATEGY_VERSION)
    except DatabaseUnavailable:
        return None


def start_next_session_plan_warmup() -> dict[str, object]:
    global _WARMUP_THREAD
    latest_date = load_latest_daily_trade_date()
    if latest_date is None:
        return {"status": "skipped", "reason": "daily_history_unavailable"}
    existing = load_latest_next_session_plan(
        latest_date,
        phase="final",
        strategy_version=LIVE_STRATEGY_VERSION,
    )
    if existing is not None and _has_observations(existing):
        return {"status": "skipped", "reason": "plan_ready"}
    with _WARMUP_LOCK:
        if _WARMUP_THREAD is not None and _WARMUP_THREAD.is_alive():
            return {"status": "running", "already_running": True}
        _WARMUP_THREAD = threading.Thread(
            target=_warmup,
            name="limit-up-next-session-plan",
            daemon=True,
        )
        _WARMUP_THREAD.start()
    return {"status": "started", "source_trade_date": latest_date.isoformat()}


def _source_snapshot_from_pools(
    pools: Mapping[str, object],
    source_trade_date: date,
) -> dict[str, object]:
    from alphaagent.server.services.limit_up.live_service import (
        _candidate_symbols,
        build_live_snapshot,
    )

    source_at = datetime.combine(
        source_trade_date,
        time(14, 57),
        tzinfo=SHANGHAI,
    )
    symbols = _candidate_symbols({}, pools)
    context = load_live_context(symbols, source_trade_date + timedelta(days=1))
    return build_live_snapshot({}, pools, source_at, context)


def _plan_signal(signal: Mapping[str, object], captured_at: datetime) -> dict[str, object]:
    selection_reasons = signal.get("selection_reasons")
    if not isinstance(selection_reasons, list) or not selection_reasons:
        selection_reasons = [str(signal.get("reason") or "进入次交易时段观察")]
    return {
        **dict(signal),
        "action": "observe",
        "research_action": "observe",
        "execution_state": "watch",
        "signal_state": "observing",
        "execution_permission": "research_only",
        "strategy_name": str(signal.get("strategy_name") or "次日盘中观察"),
        "selection_reasons": selection_reasons[:4],
        "trigger_checks": [
            {
                "code": "auction_gap",
                "label": "盘前资格",
                "status": "pending",
                "observed": None,
                "required": "D-1结构与盘前可见硬门保持通过",
                "evidence_time": None,
            },
            {
                "code": "market_gate",
                "label": "市场环境",
                "status": "pending",
                "observed": None,
                "required": "次交易时段市场门保持通过",
                "evidence_time": None,
            },
        ],
        "buy_instruction": "次交易日10:00后仅在首次触板或可观察回封时进入综合候选",
        "sell_instruction": str(signal.get("sell_condition") or "D+1动态评估竞价兑现，否则15:00退出"),
        "cancel_checks": [
            "盘前资格或对应板位硬门失效",
            "跌出动态Top5",
            "板块或市场门关闭",
        ],
        "reason": "盘后已进入观察，等待次交易时段盘中触发",
        "state_updated_at": captured_at.isoformat(),
        "valid_at": captured_at.isoformat(),
        "valid_until": "下一交易日14:30",
    }


def _plan_sources(
    raw_rows: object,
    candidates: object,
) -> list[dict[str, object]]:
    strict: list[dict[str, object]] = []
    if isinstance(raw_rows, list):
        strict = [
            dict(row)
            for row in raw_rows
            if isinstance(row, Mapping)
            and str(row.get("action") or "") in {"observe", "next_auction"}
            and str(row.get("entry_kind") or "")
            in {"next_session_watch", "next_auction"}
            and _integer(row.get("board_level"), 0) >= 3
        ]

    fallback: list[dict[str, object]] = []
    if isinstance(candidates, list):
        fallback = [
            source
            for row in candidates
            if isinstance(row, Mapping)
            if (source := _candidate_plan_source(row)) is not None
        ]
        fallback.sort(key=_plan_source_sort_key)

    selected: list[dict[str, object]] = []
    selected_symbols: set[str] = set()
    lane_counts: dict[str, int] = {}
    for row in [*strict, *fallback]:
        symbol = str(row.get("vt_symbol") or "")
        lane = str(row.get("board_lane") or "")
        if (
            not symbol
            or symbol in selected_symbols
            or not lane
            or lane_counts.get(lane, 0) >= PLAN_LANE_LIMIT
        ):
            continue
        selected.append(row)
        selected_symbols.add(symbol)
        lane_counts[lane] = lane_counts.get(lane, 0) + 1
    return selected


def _candidate_plan_source(candidate: Mapping[str, object]) -> dict[str, object] | None:
    if str(candidate.get("state") or "") not in {"sealed", "resealed"}:
        return None
    blockers = {
        str(value)
        for value in candidate.get("lane_blockers") or []
        if value
    }
    if blockers - _NEXT_SESSION_WATCH_BLOCKERS:
        return None

    source_board = _integer(candidate.get("board_level"), 1)
    classified_board = {
        "first_board": 1,
        "two_to_three": 3,
        "high_board": 4,
    }.get(str(candidate.get("board_lane") or ""), source_board)
    target_board = max(source_board + 1, classified_board)
    if target_board == 2:
        return None
    target_lane = _board_lane(target_board)
    favorable = [str(value) for value in candidate.get("lane_favorable_factors") or [] if value]
    return {
        **dict(candidate),
        "source_board_level": source_board,
        "board_level": target_board,
        "board_lane": target_lane,
        "action": "observe",
        "entry_kind": "next_session_watch",
        "strategy_name": f"{_lane_label(target_lane)}盘中观察",
        "selection_reasons": favorable[:4] or ["D日封板进入次日接力观察池"],
        "reason": "D日结构入选，等待次日10:00后盘中触发",
    }


def _plan_source_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    quality = str(candidate.get("lane_quality_tier") or "")
    return (
        0 if quality == "A" else 1 if quality == "B" else 2,
        -(_number(candidate.get("lane_rank_score")) or 0.0),
        _integer(candidate.get("market_dragon_rank"), 999),
        str(candidate.get("vt_symbol") or ""),
    )


def _has_observations(snapshot: Mapping[str, object]) -> bool:
    recommendations = snapshot.get("recommendations")
    recommendations = recommendations if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    rows = lanes.get("next_auction")
    return isinstance(rows, list) and bool(rows)


def _board_lane(board_level: int) -> str:
    if board_level <= 1:
        return "first_board"
    if board_level == 2:
        return "one_to_two"
    if board_level == 3:
        return "two_to_three"
    return "high_board"


def _lane_label(lane: str) -> str:
    return {
        "first_board": "首板",
        "two_to_three": "二进三",
        "high_board": "高板",
    }.get(lane, "接力")


def _integer(value: object, default: int) -> int:
    try:
        return int(float(value)) if value not in (None, "", "-") else default
    except (TypeError, ValueError):
        return default


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _warmup() -> None:
    try:
        refresh_next_session_plan("final")
    except Exception as exc:  # noqa: BLE001
        logger.warning("next-session plan warmup failed: %s", exc)


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)
