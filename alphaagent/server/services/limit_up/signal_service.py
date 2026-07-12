"""Strict intraday signal lookup with an explicit historical proxy fallback."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Mapping
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.live_repository import (
    list_daily_trade_dates,
    list_snapshot_dates,
    load_latest_daily_trade_date,
    load_latest_snapshot,
    load_snapshot_as_of,
)
from alphaagent.server.services.limit_up.live_evidence import attach_historical_evidence
from alphaagent.server.services.limit_up.live_policy import session_stage
from alphaagent.server.services.limit_up.live_service import downgrade_snapshot_to_stale
from alphaagent.server.services.limit_up.service import (
    get_limit_up_dashboard,
    get_limit_up_trade_dates,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")
ACTIVE_SIGNAL_STAGES = {"auction", "morning", "afternoon", "tail", "close_auction"}


def get_limit_up_signal_dates(now: datetime | None = None) -> dict[str, object]:
    local_now = _local_datetime(now or datetime.now(SHANGHAI))
    historical = get_limit_up_trade_dates()
    daily_trade_dates = set(list_daily_trade_dates())
    snapshot_dates = set(list_snapshot_dates())
    verified_current_date = _verified_current_snapshot_date(
        local_now,
        snapshot_dates,
        daily_trade_dates,
    )
    dates = sorted(
        date_text
        for date_text in {
            *[str(item) for item in historical.get("dates") or []],
            *snapshot_dates,
        }
        if date_text in daily_trade_dates or date_text == verified_current_date
    )
    return {
        **historical,
        "status": "ready" if dates else "empty",
        "dates": dates,
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "latest": dates[-1] if dates else None,
        "count": len(dates),
    }


def get_limit_up_signals(
    target_date: date,
    as_of: datetime | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    local_now = _local_datetime(now or datetime.now(SHANGHAI))
    snapshot = load_snapshot_as_of(target_date, as_of)
    resolved_trade_date = load_latest_daily_trade_date(target_date)
    if snapshot is not None:
        if _is_verified_current_snapshot(snapshot, target_date, local_now):
            if as_of is not None or _is_active_signal_session(local_now):
                return snapshot
            return downgrade_snapshot_to_stale(
                snapshot,
                target_date,
                reason="当前为非交易时段",
            )
        if resolved_trade_date != target_date:
            return downgrade_snapshot_to_stale(
                snapshot,
                resolved_trade_date or target_date,
                reason="快照日期不在已验证交易日日历",
            )
        if target_date == local_now.date() and as_of is None and not _is_active_signal_session(local_now):
            return downgrade_snapshot_to_stale(
                snapshot,
                target_date,
                reason="当前为非交易时段",
            )
        return snapshot
    proxy_date = resolved_trade_date or target_date
    dashboard = get_limit_up_dashboard(proxy_date)
    proxy = _attach_proxy_evidence(
        build_historical_signal_proxy(dashboard, proxy_date, as_of)
    )
    if resolved_trade_date != target_date:
        return downgrade_snapshot_to_stale(
            proxy,
            proxy_date,
            reason="请求日期不在已验证交易日日历",
        )
    return proxy


def _attach_proxy_evidence(proxy: Mapping[str, object]) -> dict[str, object]:
    try:
        return attach_historical_evidence(proxy)
    except Exception as exc:  # noqa: BLE001
        result = dict(proxy)
        quality = result.get("data_quality")
        quality = dict(quality) if isinstance(quality, Mapping) else {}
        source_errors = list(quality.get("source_errors") or [])
        source_errors.append(f"history_evidence:{exc.__class__.__name__}")
        quality["source_errors"] = source_errors
        limitations = list(quality.get("limitations") or [])
        limitations.append("历史相似样本暂不可用，历史代理信号仍可读取。")
        quality["limitations"] = limitations
        result["data_quality"] = quality
        return result


def _verified_current_snapshot_date(
    now: datetime,
    snapshot_dates: set[str],
    daily_trade_dates: set[str],
) -> str | None:
    today = now.date()
    today_text = today.isoformat()
    if today.weekday() >= 5 or today_text not in snapshot_dates or today_text in daily_trade_dates:
        return None
    snapshot = load_latest_snapshot(today)
    return today_text if snapshot and _is_verified_current_snapshot(snapshot, today, now) else None


def _is_verified_current_snapshot(
    snapshot: Mapping[str, object],
    target_date: date,
    now: datetime,
) -> bool:
    if target_date != now.date() or target_date.weekday() >= 5:
        return False
    if str(snapshot.get("trade_date") or "") != target_date.isoformat():
        return False
    if str(snapshot.get("mode") or "") != "live_snapshot":
        return False
    quality = snapshot.get("data_quality")
    if not isinstance(quality, Mapping) or quality.get("is_stale") is not False:
        return False
    captured_at = _snapshot_datetime(snapshot.get("captured_at"))
    return captured_at is not None and captured_at.date() == target_date


def _is_active_signal_session(now: datetime) -> bool:
    return session_stage(now) in ACTIVE_SIGNAL_STAGES


def _snapshot_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return _local_datetime(datetime.fromisoformat(str(value)))
    except ValueError:
        return None


def _local_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SHANGHAI)
    return value.astimezone(SHANGHAI)


def build_historical_signal_proxy(
    dashboard: Mapping[str, object],
    target_date: date,
    as_of: datetime | None = None,
) -> dict[str, object]:
    captured_at = _proxy_captured_at(target_date, as_of)
    candidates = [
        _proxy_candidate(row)
        for row in dashboard.get("top_dragons") or []
        if isinstance(row, Mapping)
    ]
    plans = dashboard.get("research_plan")
    plans = plans if isinstance(plans, Mapping) else {}
    plan_symbols = {
        str(row.get("vt_symbol") or "")
        for row in plans.get("plans") or []
        if isinstance(row, Mapping)
    }
    lanes = {
        "now": [_proxy_signal(row, "now", plan_symbols) for row in candidates],
        "tail": [_proxy_signal(row, "tail", plan_symbols) for row in candidates],
        "next_auction": [
            _proxy_signal(row, "next_auction", plan_symbols) for row in candidates
        ],
    }
    pretrade_market = dashboard.get("pretrade_market")
    pretrade_market = pretrade_market if isinstance(pretrade_market, Mapping) else {}
    summary = dashboard.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    market_context = {
        "sealed_count": int(summary.get("sealed_count") or 0),
        "failed_count": int(summary.get("failed_count") or 0),
        "failed_rate": _failed_rate(summary),
        "sentiment": dict(pretrade_market.get("sentiment") or {}),
        "timing": dict(pretrade_market.get("timing") or {}),
        "data_cutoff": "HISTORICAL_D1_AND_FIRST_TOUCH_PROXY",
    }
    return {
        "status": "ready" if candidates else "empty",
        "trade_date": target_date.isoformat(),
        "captured_at": captured_at.isoformat(),
        "session_stage": "closed",
        "strategy_version": "limit-up-historical-proxy-v1",
        "mode": "historical_proxy",
        "source": "stock_events,stock_daily_bars",
        "source_updated_at": dashboard.get("as_of_time"),
        "market_context": market_context,
        "candidates": candidates,
        "recommendations": {
            "captured_at": captured_at.isoformat(),
            "session_stage": "closed",
            "market_gate": {
                "passed": bool(plan_symbols),
                "reasons": [] if plan_symbols else [str(plans.get("reason") or "当日无研究计划")],
            },
            "lanes": lanes,
        },
        "data_quality": {
            "status": "proxy",
            "is_stale": False,
            "execution_confidence": "historical_proxy_unverifiable",
            "has_tick": False,
            "has_l2": False,
            "source_errors": [],
            "limitations": [
                "该日期没有保存盘中信号，当前内容由日终事件重建，不能证明当时真实发出或成交。",
                "历史代理只把D-1与首次触板字段用于候选；最终封板和D+1只用于结果展示。",
            ],
        },
    }


def _proxy_candidate(row: Mapping[str, object]) -> dict[str, object]:
    outcome = row.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    final_status = str(outcome.get("final_status") or "")
    return {
        **dict(row),
        "board_level": int(row.get("signal_board_level") or 1),
        "state": "sealed" if final_status == "sealed" else "failed",
        "sector_heat": row.get("prior_sector_heat_score"),
        "sector_main_net_inflow": row.get("prior_sector_main_net_inflow"),
        "stock_main_net_inflow": row.get("prior_stock_main_net_inflow"),
        "result": outcome,
    }


def _proxy_signal(
    candidate: Mapping[str, object],
    lane: str,
    plan_symbols: set[str],
) -> dict[str, object]:
    symbol = str(candidate.get("vt_symbol") or "")
    in_plan = symbol in plan_symbols
    board_level = int(candidate.get("board_level") or 1)
    action = "pass"
    entry_kind = "none"
    reason = "当日盘前门槛未通过"
    if lane == "now" and in_plan:
        action = "wait_tail"
        entry_kind = "reseal_proxy"
        reason = "历史只能确认条件计划，缺少当时回封队列，不能标记已买"
    elif lane == "tail" and in_plan:
        action = "wait_tail"
        entry_kind = "tail_proxy"
        reason = "等待尾盘封住；旧日期没有连续盘中快照"
    elif (
        lane == "next_auction"
        and in_plan
        and board_level <= 2
        and candidate.get("state") == "sealed"
    ):
        action = "next_auction"
        entry_kind = "next_auction"
        reason = "盘后代理计划；次日竞价仅在1%-7%区间才可执行"
    return {
        "vt_symbol": symbol,
        "name": candidate.get("name"),
        "sector_id": candidate.get("sector_id"),
        "sector_name": candidate.get("sector_name"),
        "market_dragon_rank": candidate.get("market_dragon_rank"),
        "sector_dragon_rank": candidate.get("sector_dragon_rank"),
        "board_level": board_level,
        "state": candidate.get("state"),
        "open_times": candidate.get("open_times"),
        "action": action,
        "entry_kind": entry_kind,
        "trigger_price": None,
        "valid_at": None,
        "valid_until": None,
        "stable_minutes": 0,
        "reason": reason,
        "cancel_condition": "跌出动态Top5、板块退潮、炸板率恶化或竞价不在1%-7%",
        "execution_confidence": "historical_proxy_unverifiable",
        "result": candidate.get("result"),
    }


def _proxy_captured_at(target_date: date, as_of: datetime | None) -> datetime:
    if as_of is None:
        return datetime.combine(target_date, time(15, 0), tzinfo=SHANGHAI)
    if as_of.tzinfo is None:
        return as_of.replace(tzinfo=SHANGHAI)
    return as_of.astimezone(SHANGHAI)


def _failed_rate(summary: Mapping[str, object]) -> float | None:
    sealed = int(summary.get("sealed_count") or 0)
    failed = int(summary.get("failed_count") or 0)
    return round(failed / (sealed + failed), 4) if sealed + failed else None
