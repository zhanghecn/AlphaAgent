"""断板反包打板 API 门面:实时推荐 / 回测报告 / 交割单 / 规则契约。"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from alphaagent.server.services.fanbao import (
    backtest as backtest_mod,
    contracts,
    repository,
)

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_rebuild_lock = threading.Lock()
_rebuild_running = False


class BacktestAlreadyRunningError(RuntimeError):
    """断板反包回测重算已有任务在执行。"""


# ── 实时推荐 ──

def get_live(trade_date: date | None = None) -> dict[str, object]:
    """今日池 × 触发状态;指定日期可回看。盘前/盘后均可读(盘后为定版)。"""
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
    group_counts: dict[str, int] = {}
    gap_counts: dict[str, int] = {}
    point_counts: dict[str, int] = {}
    actionable_count = 0
    for e in entries:
        sk = str(e["status"])
        status_counts[sk] = status_counts.get(sk, 0) + 1
    for e in pool:
        gk = str(e["group6"])
        group_counts[gk] = group_counts.get(gk, 0) + 1
        gap_counts[str(e["gap"])] = gap_counts.get(str(e["gap"]), 0) + 1
        pk = str(e.get("point") or "—")
        if pk != "—":
            point_counts[pk] = point_counts.get(pk, 0) + 1
        actionable_count += int(bool(e.get("actionable")))
    mkt_lim_tm1 = next((e.get("mkt_lim_tm1") for e in pool
                        if e.get("mkt_lim_tm1") is not None), None)
    last_scan = repository.latest_scan_run(target)
    return {
        "status": "ok",
        "trade_date": target.isoformat(),
        "stale": stale,
        "session_stage": _session_stage(now),
        "rules_version": contracts.FANBAO_RULES_VERSION,
        "counts": {
            "pool": len(pool),
            "actionable": actionable_count,
            "signals": len(signals),
            "by_group": group_counts,
            "by_gap": gap_counts,
            "by_point": point_counts,
            "by_status": status_counts,
        },
        "mkt_lim_tm1": mkt_lim_tm1,
        "group6_labels": contracts.GROUP6_LABELS,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "last_scan": {
            "finished_at": _iso(last_scan.get("finished_at")),
            "status": last_scan.get("status"),
            "message": last_scan.get("message"),
        } if last_scan else None,
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
            "group6": entry.get("group6"),
            "n_board": entry.get("n_board"),
            "seg": entry.get("seg"),
            "gap": entry.get("gap"),
            "yin_yang": entry.get("yin_yang"),
            "point": entry.get("point"),
            "level": entry.get("level"),
            "actionable": bool(entry.get("actionable")),
            "avoid_static": entry.get("avoid_static"),
            "prev_close": entry.get("prev_close"),
            "limit_price": entry.get("limit_price"),
            "break_end": _date_iso(entry.get("break_end")),
            "wave_start": _date_iso(entry.get("wave_start")),
            "break_days": entry.get("break_days"),
            "break_yin_count": entry.get("break_yin_count"),
            "break_zha_days": entry.get("break_zha_days"),
            "break_drop_pct": entry.get("break_drop_pct"),
            "pit_depth_pct": entry.get("pit_depth_pct"),
            "last_entity": entry.get("last_entity"),
            "last_open_pct": entry.get("last_open_pct"),
            "high_var": bool(str(entry.get("point") or "") == "S2"
                             and contracts.is_high_var_open(entry.get("last_open_pct"))),
            "dist_ma5": entry.get("dist_ma5"),
            "dist_h60": entry.get("dist_h60"),
            "ma_state": entry.get("ma_state"),
            "dist_ma10": entry.get("dist_ma10"),
            "chain": entry.get("chain"),
            "prev_wave60": entry.get("prev_wave60"),
            "prev_wave120": entry.get("prev_wave120"),
        })
    if sig:
        row.update({
            "vt_symbol": sig["vt_symbol"],
            "group6": sig.get("group6") or row.get("group6"),
            "point": sig.get("point") or row.get("point"),
            "level": sig.get("level") or row.get("level"),
            "name": row.get("name") or sig.get("name"),
            "prev_close": row.get("prev_close") or sig.get("prev_close"),
            "limit_price": row.get("limit_price") or sig.get("limit_price"),
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
    if current < time(9, 25):
        return "preopen"
    if current < time(9, 30):
        return "auction"
    if current < time(9, 46):
        return "first_window"
    if current <= time(11, 30):
        return "morning"
    if current < time(13, 0):
        return "lunch"
    if current <= time(15, 0):
        return "afternoon"
    return "closed"


# ── 回测 ──

def get_backtest_report() -> dict[str, object] | None:
    return repository.load_backtest_report(contracts.FANBAO_RULES_VERSION)


def get_rebuild_status() -> dict[str, object]:
    run = repository.latest_rebuild_run()
    if run is None:
        return {"status": "idle", "rules_version": contracts.FANBAO_RULES_VERSION}
    return {
        "status": run.get("status"),
        "stage": run.get("stage"),
        "source": run.get("source"),
        "rules_version": run.get("rules_version"),
        "requested_at": _iso(run.get("requested_at")),
        "started_at": _iso(run.get("started_at")),
        "finished_at": _iso(run.get("finished_at")),
        "message": run.get("message"),
        "error": run.get("error"),
        "metrics": run.get("metrics") or {},
    }


def start_backtest_rebuild(source: str = "manual") -> dict[str, object]:
    """409 去重:已有 queued/running 任务则拒绝。"""
    global _rebuild_running
    with _rebuild_lock:
        if _rebuild_running:
            return {"already_running": True}
        _rebuild_running = True
    run_id = repository.create_rebuild_run(source, contracts.FANBAO_RULES_VERSION)
    thread = threading.Thread(
        target=_background_rebuild, args=(run_id,), daemon=True,
        name="fbb-backtest-rebuild",
    )
    thread.start()
    return {"run_id": run_id, "status": "queued"}


def run_backtest_sync(source: str = "scheduler") -> dict[str, object]:
    """调度链同步执行(内部也走重建轨道,供批次读取状态)。"""
    global _rebuild_running
    with _rebuild_lock:
        if _rebuild_running:
            raise BacktestAlreadyRunningError
        _rebuild_running = True
    run_id = repository.create_rebuild_run(source, contracts.FANBAO_RULES_VERSION)
    try:
        return _execute_rebuild(run_id)
    finally:
        with _rebuild_lock:
            _rebuild_running = False


def _background_rebuild(run_id: int) -> None:
    global _rebuild_running
    try:
        _execute_rebuild(run_id)
    finally:
        with _rebuild_lock:
            _rebuild_running = False


def _execute_rebuild(run_id: int) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    repository.update_rebuild_run(run_id, status="running", stage="全量回放", started_at=now)
    try:
        payload = backtest_mod.run_backtest()
    except Exception as exc:  # noqa: BLE001
        logger.warning("fbb backtest rebuild failed: %s", exc, exc_info=True)
        repository.update_rebuild_run(
            run_id, status="failed", stage="失败",
            finished_at=datetime.now(timezone.utc), error=f"{exc.__class__.__name__}: {exc}")
        raise
    repository.update_rebuild_run(run_id, status="running", stage="写库")
    repository.save_backtest_report(contracts.FANBAO_RULES_VERSION, payload)
    summary = payload.get("summary") or {}
    repository.update_rebuild_run(
        run_id, status="done", stage="完成",
        finished_at=datetime.now(timezone.utc),
        message="; ".join(f"{pk}: n={(summary.get(pk) or {}).get('n')}"
                          for pk in contracts.POINT_KEYS),
        metrics={"summary": summary,
                 "anchor_check": payload.get("anchor_check") or {}},
    )
    return payload


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
    return {
        "status": "ok",
        "is_backtest": True,
        "coverage": payload.get("coverage"),
        "caliber": payload.get("caliber"),
        "month": selected,
        "months": months,
        "ledger_days": days,
    }


def _month_summaries(days: list[dict[str, object]]) -> list[dict[str, object]]:
    """按月汇总交割单(笔数/胜率/坏票/平均每笔/累计等权),最新在前。"""
    acc: dict[str, dict[str, float]] = {}
    for day in days:
        key = str(day.get("trade_date") or "")[:7]
        if not key:
            continue
        bucket = acc.setdefault(key, {"count": 0, "win": 0, "bad": 0, "sum_ret": 0.0})
        for t in day.get("trades") or []:
            ret = t.get("ret_pct")
            if ret is None:
                continue
            bucket["count"] += 1
            bucket["sum_ret"] += float(ret)
            if float(ret) > 0:
                bucket["win"] += 1
            if t.get("is_bad"):
                bucket["bad"] += 1
    return [
        {"month": m, "count": int(v["count"]), "bad": int(v["bad"]),
         "win_rate": round(v["win"] / v["count"] * 100, 1) if v["count"] else None,
         "avg_ret_pct": round(v["sum_ret"] / v["count"], 2) if v["count"] else None,
         "total_ret_pct": round(v["sum_ret"], 2)}
        for m, v in sorted(acc.items(), reverse=True)
    ]


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
        "rules_version": contracts.FANBAO_RULES_VERSION,
        "group6_labels": contracts.GROUP6_LABELS,
        "point_labels": contracts.POINT_LABELS,
        "point_levels": contracts.POINT_LEVELS,
        "point_desc": contracts.POINT_DESC,
        "rules": contracts.RULES,
        "falsified_rules": contracts.FALSIFIED_RULES,
        "risk_notes": contracts.RISK_NOTES,
        "ths_pool_conditions": contracts.THS_POOL_CONDITIONS,
        "ths_pool_note": contracts.THS_POOL_NOTE,
        "intraday_playbook": contracts.INTRADAY_PLAYBOOK,
        "anchors": contracts.BACKTEST_ANCHORS,
        "anchor_tolerances": contracts.ANCHOR_TOLERANCES,
        "matrix_anchors": contracts.MATRIX_ANCHORS,
        "case_gates": contracts.CASE_GATES,
    }


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (
        str(value) if value else None)


def _date_iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, date) else (
        str(value) if value else None)
