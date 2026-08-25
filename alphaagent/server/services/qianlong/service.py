"""潜龙首板 API 门面:实时推荐 / 回测报告 / 交割单 / 规则契约。"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from alphaagent.server.services.qianlong import (
    backtest as backtest_mod,
    contracts,
    repository,
)

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_rebuild_lock = threading.Lock()
_rebuild_running = False


class BacktestAlreadyRunningError(RuntimeError):
    """回测重算已有任务在执行。"""


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
    sig_vts = set(signals)
    entries = []
    for entry in pool:
        vt = str(entry["vt_symbol"])
        sig = signals.get(vt)
        entries.append(_live_row(entry, sig))
    # 信号里有但池里缺的(理论上不该有)兜底
    for vt, sig in signals.items():
        if vt not in {str(e["vt_symbol"]) for e in pool}:
            entries.append(_live_row(None, sig))
    entries.sort(key=_live_sort_key)

    circuit = _circuit_breaker_state(now)
    status_counts: dict[str, int] = {}
    for e in entries:
        key = str(e["status"])
        status_counts[key] = status_counts.get(key, 0) + 1
    last_scan = repository.latest_scan_run(target)
    return {
        "status": "ok",
        "trade_date": target.isoformat(),
        "stale": stale,
        "session_stage": _session_stage(now),
        "rules_version": contracts.QIANLONG_RULES_VERSION,
        "counts": {
            "pool": len(pool),
            "signals": len(sig_vts),
            **status_counts,
        },
        "circuit_breaker": circuit,
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
            "prev_close": entry.get("prev_close"),
            "trigger_price": entry.get("trigger_price"),
            "limit_price": entry.get("limit_price"),
            "chg_tm1": entry.get("chg_tm1"),
            "turnover_rate_tm1": entry.get("turnover_rate_tm1"),
            "market_cap_yi": entry.get("market_cap_yi"),
            "dist_ma20": entry.get("dist_ma20"),
            "chassis_tag": entry.get("chassis_tag"),
            "trend_days": entry.get("trend_days"),
            "lu_cnt20": entry.get("lu_cnt20"),
            "lu_cnt60": entry.get("lu_cnt60"),
        })
    if sig:
        row.update({
            "vt_symbol": sig["vt_symbol"],
            "name": row.get("name") or sig.get("name"),
            "prev_close": row.get("prev_close") or sig.get("prev_close"),
            "trigger_price": row.get("trigger_price") or sig.get("trigger_price"),
            "status": sig.get("status"),
            "gap_open_pct": _pct(sig.get("gap_open")),
            "priority": bool(sig.get("priority")),
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
        })
    row.setdefault("status", "watching")
    row.setdefault("priority", "B" in str(row.get("chassis_tag") or ""))
    return row


def _live_sort_key(row: dict[str, object]) -> tuple:
    order = {"holding": 0, "touched": 1, "watching": 2, "pending_exit": 3,
             "closed": 4, "unconfirmed": 5, "skipped_gap": 6, "no_trigger": 7}
    return (order.get(str(row.get("status")), 8),
            0 if row.get("priority") else 1,
            float(row.get("gap_open_pct") or 99.0))


def _session_stage(now: datetime) -> str:
    current = now.timetz().replace(tzinfo=None)
    if current < time(9, 30):
        return "preopen"
    if current <= time(11, 30):
        return "morning"
    if current < time(13, 0):
        return "lunch"
    if current <= time(15, 0):
        return "afternoon_closed_for_entry"  # 午后不做,仅展示
    return "closed"


def _circuit_breaker_state(now: datetime) -> dict[str, object]:
    """当月已实现盈亏(前推信号口径)≤ -5% → 熔断提示。"""
    month = now.date().isoformat()[:7]
    closed = repository.load_month_closed_signals(month)
    realized = sum(float(r.get("ret_pct") or 0.0) for r in closed)
    return {
        "month": month,
        "realized_pct": round(realized, 2),
        "threshold_pct": contracts.MONTHLY_CIRCUIT_BREAKER_PCT,
        "halted": realized <= contracts.MONTHLY_CIRCUIT_BREAKER_PCT and len(closed) > 0,
        "closed_trades": len(closed),
        "note": "口径:前推信号(产品上线后模拟成交)当月已实现收益等权求和",
    }


# ── 回测 ──

def get_backtest_report() -> dict[str, object] | None:
    return repository.load_backtest_report(contracts.QIANLONG_RULES_VERSION)


def get_rebuild_status() -> dict[str, object]:
    run = repository.latest_rebuild_run()
    if run is None:
        return {"status": "idle", "rules_version": contracts.QIANLONG_RULES_VERSION}
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
    """409 去重:已有 queued/running 任务则拒绝;执行走独立子进程。

    去重以 DB 状态为准——uvicorn --workers 2 下进程内标志跨 worker 无效;
    执行不在 worker 线程里跑(原装 worker 首次全量回放会无声崩溃,见
    rebuild_worker 模块注释),子进程与 worker 生命周期解耦;
    开头顺手 reap 僵尸(worker 崩溃后状态永远停在 running,详见 repository)。
    """
    repository.fail_stale_rebuild_runs()
    if repository.has_active_rebuild_run():
        return {"already_running": True}
    run_id = repository.create_rebuild_run(source, contracts.QIANLONG_RULES_VERSION)
    subprocess.Popen(
        [sys.executable, "-m",
         "alphaagent.server.services.qianlong.rebuild_worker", str(run_id)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return {"run_id": run_id, "status": "queued"}


def run_backtest_sync(source: str = "scheduler") -> dict[str, object]:
    """调度链同步执行(内部也走重建轨道,供批次读取状态)。"""
    global _rebuild_running
    repository.fail_stale_rebuild_runs()
    with _rebuild_lock:
        if _rebuild_running:
            raise BacktestAlreadyRunningError
        _rebuild_running = True
    run_id = repository.create_rebuild_run(source, contracts.QIANLONG_RULES_VERSION)
    try:
        return _execute_rebuild(run_id)
    finally:
        with _rebuild_lock:
            _rebuild_running = False


def _execute_rebuild(run_id: int) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    repository.update_rebuild_run(run_id, status="running", stage="全量回放", started_at=now)
    try:
        payload = backtest_mod.run_backtest()
    except Exception as exc:  # noqa: BLE001
        logger.warning("qianlong backtest rebuild failed: %s", exc, exc_info=True)
        repository.update_rebuild_run(
            run_id, status="failed", stage="失败",
            finished_at=datetime.now(timezone.utc), error=f"{exc.__class__.__name__}: {exc}")
        raise
    repository.update_rebuild_run(run_id, status="running", stage="写库")
    repository.save_backtest_report(contracts.QIANLONG_RULES_VERSION, payload)
    summary = payload.get("summary") or {}
    repository.update_rebuild_run(
        run_id, status="done", stage="完成",
        finished_at=datetime.now(timezone.utc),
        message=f"回放 {summary.get('n')} 笔,均 {summary.get('avg_pct')}%",
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
    """按月汇总交割单(笔数/胜率/平均每笔/月收益),最新在前。

    月收益与回测页月度表同口径(精确式):Σ当日全部信号等权均值——每天满仓当日
    全部信号、次日本金重置、非复利。旧「Σ每笔等权」把一天 N 笔当 N 次满仓,
    信号爆炸月虚高最狠(2024-02 单月虚 +1,431% vs 真实 +8.7%),已废。
    """
    acc: dict[str, dict[str, float]] = {}
    for day in days:
        key = str(day.get("trade_date") or "")[:7]
        if not key:
            continue
        bucket = acc.setdefault(
            key, {"count": 0, "win": 0, "sum_ret": 0.0, "day_sum": 0.0, "days": 0})
        day_avg = day.get("avg_ret_pct")
        if day_avg is not None:
            bucket["day_sum"] += float(day_avg)
            bucket["days"] += 1
        for t in day.get("trades") or []:
            ret = t.get("ret_pct")
            if ret is None:
                continue
            bucket["count"] += 1
            bucket["sum_ret"] += float(ret)
            if float(ret) > 0:
                bucket["win"] += 1
    return [
        {"month": m, "count": int(v["count"]),
         "win_rate": round(v["win"] / v["count"] * 100, 1) if v["count"] else None,
         "avg_ret_pct": round(v["sum_ret"] / v["count"], 2) if v["count"] else None,
         "month_ret_pct": round(v["day_sum"], 2),
         "signal_days": int(v["days"])}
        for m, v in sorted(acc.items(), reverse=True)
    ]


def get_forward_ledger(trade_date: date) -> dict[str, object]:
    """前推交割单(产品上线后的实时模拟成交)。"""
    entered = repository.load_entered_signals(trade_date)
    return {"status": "ok", "is_backtest": False,
            "trade_date": trade_date.isoformat(), "trades": entered}


# ── 规则契约 ──

def get_rules() -> dict[str, object]:
    return {
        "rules_version": contracts.QIANLONG_RULES_VERSION,
        "rules": contracts.RULES,
        "falsified_rules": contracts.FALSIFIED_RULES,
        "risk_notes": contracts.RISK_NOTES,
        "ths_pool_conditions": contracts.THS_POOL_CONDITIONS_A,
        "ths_pool_conditions_b": contracts.THS_POOL_CONDITIONS_B,
        "ths_pool_note": contracts.THS_POOL_NOTE,
        "intraday_playbook": contracts.INTRADAY_PLAYBOOK,
        "anchors": contracts.BACKTEST_ANCHORS,
    }


def _iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (
        str(value) if value else None)


def _date_iso(value: object) -> str | None:
    return value.isoformat() if isinstance(value, date) else (
        str(value) if value else None)


def _pct(value: object) -> float | None:
    try:
        return round(float(value) * 100, 2) if value is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
