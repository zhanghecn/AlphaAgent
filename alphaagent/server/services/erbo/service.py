"""二波反包(erbo) API 门面:实时推荐 / 回测报告 / 交割单 / 规则契约。"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from alphaagent.server.services.erbo import (
    backtest as backtest_mod,
    contracts,
    repository,
)

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_rebuild_lock = threading.Lock()
_rebuild_running = False


class BacktestAlreadyRunningError(RuntimeError):
    """二波反包回测重算已有任务在执行。"""


# ── 实时推荐 ──

def get_live(trade_date: date | None = None) -> dict[str, object]:
    """今日池 × 触发状态;指定日期可回看。"""
    now = datetime.now(SHANGHAI)
    target = trade_date or now.date()
    pool = repository.load_pool(target)
    stale = False
    if not pool and trade_date is None:
        latest = repository.latest_pool_date()
        if latest is not None:
            pool = repository.load_pool(latest)
            target = latest
            stale = True
    signals = repository.load_signal_map(target)
    entries = []
    pool_vts = {str(e["vt_symbol"]) for e in pool}
    for entry in pool:
        entries.append(_live_row(entry, signals.get(str(entry["vt_symbol"]))))
    for vt, sig in signals.items():
        if vt not in pool_vts:
            entries.append(_live_row(None, sig))
    entries.sort(key=_live_sort_key)

    status_counts: dict[str, int] = {}
    point_counts: dict[str, int] = {}
    actionable_count = 0
    for e in entries:
        sk = str(e["status"])
        status_counts[sk] = status_counts.get(sk, 0) + 1
    for e in pool:
        pk = str(e.get("point") or "—")
        if pk != "—":
            point_counts[pk] = point_counts.get(pk, 0) + 1
        actionable_count += int(bool(e.get("actionable")))
    mkt_lim_tm1 = None  # erbo 池行不带该列(情绪冰点在 cold_market 字段)
    last_scan = repository.latest_scan_run(target)
    return {
        "status": "ok",
        "trade_date": target.isoformat(),
        "stale": stale,
        "session_stage": _session_stage(now),
        "rules_version": contracts.ERBO_RULES_VERSION,
        "counts": {
            "pool": len(pool), "actionable": actionable_count,
            "signals": len(signals), "by_point": point_counts,
            "by_status": status_counts,
        },
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "last_scan": {
            "finished_at": _iso(last_scan.get("finished_at")) if last_scan else None,
            "status": last_scan.get("status") if last_scan else None,
            "message": last_scan.get("message") if last_scan else None,
        },
        "entries": entries,
    }


def get_live_dates() -> list[str]:
    return repository.list_pool_dates()


def _live_row(entry: dict[str, object] | None,
              sig: dict[str, object] | None) -> dict[str, object]:
    row: dict[str, object] = {}
    if entry is not None:
        row.update({
            "vt_symbol": entry["vt_symbol"], "name": entry.get("name"),
            "gap": entry.get("gap"), "gain30_pct": entry.get("gain30_pct"),
            "dd_pct": entry.get("dd_pct"), "ma20gap_pct": entry.get("ma20gap_pct"),
            "lim30": entry.get("lim30"), "yin_yang": entry.get("yin_yang"),
            "last_open_pct": entry.get("last_open_pct"),
            "point": entry.get("point"), "level": entry.get("level"),
            "actionable": bool(entry.get("actionable")),
            "avoid_static": entry.get("avoid_static"),
            "cold_market": bool(entry.get("cold_market")),
            "prev_close": entry.get("prev_close"),
            "limit_price": entry.get("limit_price"),
        })
    if sig:
        row.update({
            "vt_symbol": sig["vt_symbol"],
            "gap": sig.get("gap") or row.get("gap"),
            "point": sig.get("point") or row.get("point"),
            "level": sig.get("level") or row.get("level"),
            "name": row.get("name") or sig.get("name"),
            "prev_close": sig.get("prev_close") or row.get("prev_close"),
            "limit_price": sig.get("limit_price") or row.get("limit_price"),
            "status": sig.get("status"),
            "auction_pct": sig.get("auction_pct"),
            "opened": sig.get("opened"),
            "touched_at": _iso(sig.get("touched_at")),
            "entry_price": sig.get("entry_price"),
            "entry_time": _iso(sig.get("entry_time")),
            "last_price": sig.get("last_price"),
            "change_pct": sig.get("change_pct"),
            "sealed": sig.get("sealed"),
            "streak_h": sig.get("streak_h"),
            "exit_date": _date_iso(sig.get("exit_date")),
            "exit_price": sig.get("exit_price"),
            "exit_reason": sig.get("exit_reason"),
            "ret_pct": sig.get("ret_pct"),
            "bad_ticket": sig.get("bad_ticket"),
        })
    row.setdefault("status", "watching")
    row.setdefault("actionable", False)
    row.setdefault("point", "—")
    row.setdefault("level", "—")
    return row


def _live_sort_key(row: dict[str, object]) -> tuple:
    order = {"holding": 0, "entered": 0, "sealed_watch": 1, "watching": 2,
             "pending_exit": 3, "closed": 4, "no_trigger": 5, "skipped_gap": 6}
    point_order = {pk: i for i, pk in enumerate(contracts.POINT_KEYS)}
    return (0 if row.get("actionable") else 1,
            order.get(str(row.get("status")), 8),
            point_order.get(str(row.get("point")), 9),
            str(row.get("vt_symbol")))


def _session_stage(now: datetime) -> str:
    current = now.timetz().replace(tzinfo=None)
    if current < time(9, 15):
        return "preopen"
    if current < time(9, 30):
        return "auction"
    if current <= time(11, 30) or time(13, 0) <= current <= time(15, 0):
        return "intraday"
    return "closed"


# ── 回测 ──

def get_backtest_report() -> dict[str, object] | None:
    return repository.load_backtest_report(contracts.ERBO_RULES_VERSION)


def run_backtest_sync(source: str = "manual") -> dict[str, object]:
    """同步执行重建(手动触发与调度同轨;已有任务在跑则拒绝)。"""
    global _rebuild_running
    with _rebuild_lock:
        if _rebuild_running:
            raise BacktestAlreadyRunningError
        _rebuild_running = True
    try:
        return _execute_rebuild(repository.create_rebuild_run(
            source, contracts.ERBO_RULES_VERSION))
    finally:
        with _rebuild_lock:
            _rebuild_running = False


def _execute_rebuild(run_id: int) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    repository.update_rebuild_run(run_id, status="running", stage="全量回放", started_at=now)
    try:
        payload = backtest_mod.run_backtest()
    except Exception as exc:  # noqa: BLE001
        logger.warning("erbo backtest rebuild failed: %s", exc, exc_info=True)
        repository.update_rebuild_run(
            run_id, status="failed", stage="失败",
            finished_at=datetime.now(timezone.utc),
            error=f"{exc.__class__.__name__}: {exc}")
        raise
    repository.update_rebuild_run(run_id, status="running", stage="写库")
    repository.save_backtest_report(contracts.ERBO_RULES_VERSION, payload)
    summary = payload.get("summary") or {}
    repository.update_rebuild_run(
        run_id, status="done", stage="完成",
        finished_at=datetime.now(timezone.utc),
        message="; ".join(f"{pk}: n={(summary.get(pk) or {}).get('n')}"
                          for pk in contracts.POINT_KEYS),
        metrics={"summary": summary,
                 "anchor_check": payload.get("anchor_check") or {}})
    return payload


def get_rebuild_status() -> dict[str, object] | None:
    return repository.latest_rebuild_run()


# ── 交割单 ──

def get_ledger(month: str | None = None) -> dict[str, object]:
    """回测模拟交割单(全历史物化;month=YYYY-MM 切片,默认最新月)。"""
    payload = get_backtest_report()
    if payload is None:
        return {"status": "unavailable", "ledger_days": [], "months": []}
    days = list(payload.get("ledger_days") or [])
    months = _month_summaries(days)
    selected = month or (months[0]["month"] if months else None)
    if selected:
        days = [d for d in days if str(d.get("trade_date") or "").startswith(selected)]
    return {"status": "ok", "is_backtest": True,
            "coverage": payload.get("coverage"), "caliber": payload.get("caliber"),
            "month": selected, "months": months, "ledger_days": days}


def _month_summaries(days: list[dict[str, object]]) -> list[dict[str, object]]:
    acc: dict[str, dict[str, float]] = {}
    for day in days:
        key = str(day.get("trade_date") or "")[:7]
        if not key:
            continue
        bucket = acc.setdefault(key, {"count": 0, "win": 0, "sum_ret": 0.0})
        for t in day.get("trades") or []:
            ret = t.get("ret_pct")
            if ret is None:
                continue
            bucket["count"] += 1
            bucket["sum_ret"] += float(ret)
            if float(ret) > 0:
                bucket["win"] += 1
    return [{"month": m, "count": int(v["count"]),
             "win_rate": round(v["win"] / v["count"] * 100, 1) if v["count"] else None,
             "avg_ret_pct": round(v["sum_ret"] / v["count"], 2) if v["count"] else None,
             "total_ret_pct": round(v["sum_ret"], 2)}
            for m, v in sorted(acc.items(), reverse=True)]


def get_forward_ledger(trade_date: date) -> dict[str, object]:
    """前推交割单(产品上线后的实时模拟成交)。"""
    entered = repository.load_entered_signals(trade_date)
    for row in entered:
        row["point_label"] = contracts.POINT_LABELS.get(str(row.get("point")), "")
    return {"status": "ok", "is_backtest": False,
            "trade_date": trade_date.isoformat(), "trades": entered}


# ── 规则契约 ──

def get_rules() -> dict[str, object]:
    return {
        "rules_version": contracts.ERBO_RULES_VERSION,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "point_desc": contracts.POINT_DESC,
        "rules": contracts.RULES,
        "falsified_rules": contracts.FALSIFIED_RULES,
        "risk_notes": contracts.RISK_NOTES,
        "intraday_playbook": contracts.INTRADAY_PLAYBOOK,
    }


def _iso(v) -> str | None:
    return v.isoformat() if isinstance(v, (datetime, time)) else None


def _date_iso(v) -> str | None:
    return v.isoformat() if isinstance(v, date) else None
