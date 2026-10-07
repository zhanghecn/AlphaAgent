"""一接二(首板次日打二板)API 门面:实时推荐 / 回测报告 / 规则契约 / EOD 池。"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from alphaagent.server.services.first_relay import (
    backtest as backtest_mod,
    contracts,
    pool as pool_mod,
    repository,
)

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_rebuild_lock = threading.Lock()
_rebuild_running = False


class BacktestAlreadyRunningError(RuntimeError):
    """一接二回测重算已有任务在执行。"""


def _session_stage(now: datetime) -> str:
    current = now.timetz().replace(tzinfo=None)
    if current < time(9, 15):
        return "preopen"
    if current < time(9, 25):
        return "auction"
    if current < time(9, 45):
        return "first_window"
    if current < time(11, 30):
        return "morning"
    if current < time(13, 0):
        return "lunch"
    if current < time(15, 0):
        return "afternoon"
    return "closed"


# ── EOD 主链 ──

def run_eod_finalize() -> dict[str, object]:
    """收盘后主链:按最新日线生成下一交易日池(幂等覆写)。"""
    data_date = pool_mod.hpr_pool.latest_daily_date()
    if data_date is None:
        return {"status": "skip", "message": "无日线数据"}
    result = pool_mod.compute_pool(data_date)
    entries = result.get("entries") or []
    exec_date = date.fromisoformat(str(result["exec_date"]))
    saved = repository.save_pool(exec_date, entries, contracts.J12_RULES_VERSION)
    stats = result["filter_stats"]
    message = (f"j12 eod: 首板池 {saved} 票(出手 {stats.get('actionable')}: "
               f"G1 {stats.get('act_G1')}/S1 {stats.get('act_S1')}, "
               f"贴顶回避 {stats.get('avoid')})")
    logger.info(message)
    return {"status": "ok", "exec_date": exec_date.isoformat(),
            "pool": saved, "stats": stats, "message": message}


# ── 实时推荐 ──

def get_live(trade_date: date | None = None) -> dict[str, object]:
    """今日池 × 触发状态;?date= 可回看。"""
    now = datetime.now(SHANGHAI)
    target = trade_date or now.date()
    pool = repository.load_pool(target)
    stale = False
    if trade_date is None:
        latest = repository.latest_pool_date()
        if not pool and latest is not None:
            pool = repository.load_pool(latest)
            target = latest
            stale = True
    signals = repository.load_signal_map(target)
    entries = []
    for e in pool:
        sig = signals.get(str(e["vt_symbol"]))
        row = dict(e)
        if sig:
            for k in ("status", "auction_pct", "touched_at", "entry_price",
                      "entry_time", "last_price", "change_pct", "sealed",
                      "exit_date", "exit_price", "exit_reason", "ret_pct"):
                if sig.get(k) is not None:
                    row[f"sig_{k}"] = sig[k]
        entries.append(row)
    # 命中的排前面, 阴在前; 未命中(雷达)按名称
    entries.sort(key=lambda r: (0 if r.get("actionable") else 1,
                                0 if r.get("point") == "G1" else 1,
                                str(r.get("name") or "")))
    counts = {"pool": len(pool),
              "actionable": sum(1 for e in pool if e.get("actionable")),
              "signals": len(signals)}
    for p in ("G1", "S1"):
        counts[f"act_{p}"] = sum(1 for e in pool if e.get("point") == p)
    return {
        "status": "ok",
        "trade_date": target.isoformat(),
        "stale": stale,
        "session_stage": _session_stage(now),
        "rules_version": contracts.J12_RULES_VERSION,
        "counts": counts,
        "koujue": contracts.RULES_TEXT["koujue"],
        "mechanism": contracts.RULES_TEXT["mechanism"],
        "entries": entries,
    }


def get_live_dates() -> list[str]:
    return repository.list_pool_dates()


# ── 回测 ──

def get_backtest_report() -> dict[str, object] | None:
    return repository.load_backtest_report(contracts.J12_RULES_VERSION)


def get_rebuild_status() -> dict[str, object]:
    latest = repository.latest_rebuild_run()
    return {"running": _rebuild_running, "latest": latest}


def start_backtest_rebuild(source: str = "manual") -> dict[str, object]:
    global _rebuild_running
    with _rebuild_lock:
        if _rebuild_running:
            raise BacktestAlreadyRunningError
        _rebuild_running = True
    run_id = repository.create_rebuild_run(source, contracts.J12_RULES_VERSION)
    try:
        repository.update_rebuild_run(run_id, status="running",
                                      started_at=datetime.now(SHANGHAI))
        result = backtest_mod.run_backtest_sync(source=source)
        repository.update_rebuild_run(
            run_id, status="ok", finished_at=datetime.now(SHANGHAI),
            message=f"{result['trades']}笔", metrics=result["summary"])
        return {"status": "ok", "run_id": run_id, **result}
    except Exception as exc:  # noqa: BLE001
        repository.update_rebuild_run(
            run_id, status="error", finished_at=datetime.now(SHANGHAI),
            error=f"{exc.__class__.__name__}: {exc}")
        logger.exception("j12 backtest rebuild failed")
        raise
    finally:
        with _rebuild_lock:
            _rebuild_running = False


# ── 规则契约 ──

def get_rules() -> dict[str, object]:
    return {
        "rules_version": contracts.J12_RULES_VERSION,
        "points": contracts.POINTS,
        "cheat_rows": contracts.CHEAT_ROWS,
        "rules_text": contracts.RULES_TEXT,
        "main_window": contracts.MAIN_WINDOW,
    }
