"""二波反包盘中每分钟扫描:触板即买(无首刻窗)+ T字排板(镜像 fanbao 状态机)。

- 扫描窗口 09:30~15:00 全日;触发=现价首次≥涨停价,任意时刻都算
- 只对 actionable(A/B 档)池票触发;雷达票(死格/未命中)只展示不写信号
- 一字开(开盘价≥涨停价)→ sealed_watch(T字观察):盘中打开=按涨停价排板成交;
  全天不开 → EOD 判 skipped_gap
- 卖出由 EOD 定版(T+1:炸板次日收盘走一字顺延;封住→断板日收盘,15日兜底)
- 现货快照 freshness 以 trade_time 日期兜底(东财/降级源同 fanbao)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from alphaagent.server.services.erbo import contracts, repository

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_ADVISORY_LOCK_KEY = 726120          # 与 fanbao 726110 错开
MIN_SPOT_FRESH_SYMBOLS = 3000

_TERMINAL_STATUSES = {"skipped_gap", "no_trigger", "closed"}


class LiveScanAlreadyRunningError(RuntimeError):
    """二波反包盘中扫描已有任务在执行。"""


def in_scan_window(now: datetime) -> bool:
    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    return time(9, 30) <= current <= time(15, 0)


def run_live_scan_tick(now: datetime | None = None) -> dict[str, object]:
    """每分钟入口;窗口外直接跳过。"""
    started = now or datetime.now(SHANGHAI)
    if not in_scan_window(started):
        return {"status": "skipped", "message": "不在扫描窗口(09:30~15:00 工作日)"}
    today = started.date()
    pool = repository.load_pool(today)
    if not pool:
        return {"status": "skipped", "message": f"{today} 无盘前池(等待盘后计算)"}
    try:
        with _scan_lock():
            return _scan_once(today, pool, started)
    except LiveScanAlreadyRunningError:
        return {"status": "skipped", "message": "上一次扫描仍在执行,跳过"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("erbo live scan failed: %s", exc, exc_info=True)
        repository.save_scan_run(today, started, status="failed",
                                 message=f"{exc.__class__.__name__}: {exc}")
        return {"status": "failed", "message": exc.__class__.__name__}


def _scan_once(today: date, pool: list[dict[str, object]], now: datetime) -> dict[str, object]:
    from alphaagent.data_sources.akshare_adapter import (AkShareAdapter,
                                                         count_fresh_spot_items)

    spot = AkShareAdapter().all_stock_ohlcv_spot(force_refresh=True)
    items = {
        str(it.get("vt_symbol") or "").upper(): it
        for it in (spot.get("items") or []) if isinstance(it, dict)
    }
    fresh = count_fresh_spot_items(items, today, now)
    if fresh < MIN_SPOT_FRESH_SYMBOLS:
        repository.save_scan_run(today, now, status="stale_spot",
                                 stats={"pool": len(pool), "fresh": fresh},
                                 message=f"现货快照非今日数据(新鲜 {fresh}),跳过")
        return {"status": "skipped", "message": "现货快照非今日数据"}

    signals = repository.load_signal_map(today)
    touched = entered = 0
    writes: list[tuple[str, dict[str, object]]] = []

    for entry in pool:
        if not bool(entry.get("actionable")):
            continue  # 雷达票只展示不触发
        vt = str(entry["vt_symbol"])
        sig = signals.get(vt)
        status = str(sig.get("status")) if sig else "watching"
        if status in _TERMINAL_STATUSES or status in ("entered", "holding"):
            continue
        patch: dict[str, object] = {
            "name": entry.get("name"), "gap": entry.get("gap"),
            "point": entry.get("point"), "level": entry.get("level"),
            "prev_close": entry.get("prev_close"),
            "limit_price": entry.get("limit_price"),
        }
        item = items.get(vt)
        if item is None:
            continue
        last_price = _num(item.get("last_price"))
        open_price = _num(item.get("open_price"))
        volume = _num(item.get("volume")) or 0.0
        if volume <= 0 or last_price is None or last_price <= 0:
            continue  # 停牌/未交易
        prev_close = float(entry["prev_close"])
        limit_price = float(entry["limit_price"])
        patch["last_price"] = last_price
        patch["change_pct"] = round((last_price / prev_close - 1) * 100, 3)

        # 首跳:竞价涨幅记录展示;一字开 → T字观察(打开=排板成交)
        if status == "watching" and (sig is None or sig.get("auction_pct") is None):
            if open_price and open_price > 0:
                patch["auction_pct"] = round((open_price / prev_close - 1) * 100, 2)
                if open_price >= limit_price - 1e-6:
                    patch["status"] = "sealed_watch"
                    patch["opened"] = False
                    writes.append((vt, patch))
                    continue

        if status == "sealed_watch" or patch.get("status") == "sealed_watch":
            if last_price < limit_price - 1e-6:   # 打开=排板成交,买价=涨停价
                patch.update({"opened": True, "status": "entered",
                              "touched_at": (sig or {}).get("touched_at") or now,
                              "entry_price": limit_price, "entry_time": now})
                entered += 1
                touched += 1
            writes.append((vt, patch))
            continue

        if status == "watching":
            if last_price >= limit_price - 1e-6:  # 触板即买,无首刻窗
                patch.update({"status": "entered", "touched_at": now,
                              "entry_price": limit_price, "entry_time": now})
                touched += 1
                entered += 1
        writes.append((vt, patch))

    for vt, patch in writes:
        repository.upsert_signal(today, vt, **patch)
    repository.save_scan_run(
        today, now, status="ok",
        stats={"pool": len(pool), "touched": touched, "entered": entered,
               "fresh": fresh, "writes": len(writes)},
        message=f"池 {len(pool)} / 新触发 {touched} / 新买入 {entered} / 写 {len(writes)}")
    return {"status": "ok", "pool": len(pool), "touched": touched,
            "entered": entered, "writes": len(writes)}


def _num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


# ── 咨询锁(与 fanbao 同款:pg_try_advisory_lock 防重入) ──

def _scan_lock():
    from contextlib import contextmanager

    from sqlalchemy import text

    from alphaagent.server.db.session import get_engine

    @contextmanager
    def _ctx():
        engine = get_engine()
        with engine.connect() as conn:
            got = conn.execute(
                text("SELECT pg_try_advisory_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
            ).scalar_one()
            if not got:
                raise LiveScanAlreadyRunningError
            try:
                yield
            finally:
                conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_LOCK_KEY})
                conn.commit()

    return _ctx()

