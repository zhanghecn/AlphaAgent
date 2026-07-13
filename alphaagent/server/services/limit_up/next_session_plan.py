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
from alphaagent.server.services.limit_up.versions import LIVE_STRATEGY_VERSION

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
PLAN_MODES = {
    "preliminary": "next_session_preliminary",
    "final": "next_session_final",
}

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
    rows = [
        _plan_signal(row, local_at)
        for row in raw_rows
        if isinstance(row, Mapping)
        and str(row.get("action") or "") == "next_auction"
    ]
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
        },
        "data_quality": {
            **quality,
            "status": "ready" if rows else "empty",
            "is_stale": False,
            "execution_confidence": "research_only_without_l2",
            "snapshot_age_seconds": 0,
            "plan": plan_metadata,
            "limitations": [
                "盘后计划只用于下一交易时段观察，必须等待竞价硬门确认。",
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
    if existing is not None:
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
    if existing is not None:
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
        "research_action": "next_auction",
        "execution_state": "watch",
        "signal_state": "observing",
        "execution_permission": "research_only",
        "strategy_name": str(signal.get("strategy_name") or "次日竞价观察"),
        "selection_reasons": selection_reasons[:4],
        "trigger_checks": [
            {
                "code": "auction_gap",
                "label": "竞价强度",
                "status": "pending",
                "observed": None,
                "required": "竞价涨幅1%-7%且对应板位硬门通过",
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
        "buy_instruction": "次交易日09:20-09:24竞价与全部硬门通过后触发研究买点",
        "sell_instruction": str(signal.get("sell_condition") or "D+1动态评估竞价兑现，否则15:00退出"),
        "cancel_checks": [
            "竞价低于1%或高于7%",
            "跌出动态Top5",
            "板块或市场门关闭",
        ],
        "reason": "盘后已进入观察，等待次交易时段竞价确认",
        "state_updated_at": captured_at.isoformat(),
        "valid_at": captured_at.isoformat(),
        "valid_until": "下一交易日09:25",
    }


def _warmup() -> None:
    try:
        refresh_next_session_plan("final")
    except Exception as exc:  # noqa: BLE001
        logger.warning("next-session plan warmup failed: %s", exc)


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)
