"""N型补涨打板盘中每分钟扫描:板上买触发(四组统一,无竞价过滤/停手)。

口径(N型补涨打板定稿 v4.0 盘中规则):
- 扫描窗口 09:30~15:00 全日(研究未设时段限制)
- 只对 actionable(白名单出手)的池票触发;触发池其余票是雷达,不写信号
- 一字排除:首次见到开盘价 ≥ 涨停价(一字/开盘即板)→ skipped_gap 当日不再跟踪
- 触发:现价 ≥ 涨停价(触发价=涨停价)→ 立即模拟买入,买入价 = 涨停价
- 卖出由 EOD 定版(板留断走:买入次日起首个未涨停日收盘)
- 现货快照 freshness 以 trade_time 日期兜底(节假日不交易不产生假信号)
"""

from __future__ import annotations

import logging
import math
from contextlib import contextmanager
from datetime import date, datetime, time
from typing import Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import text

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.weak_to_strong import contracts, repository

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_ADVISORY_LOCK_KEY = 726102
MIN_SPOT_FRESH_SYMBOLS = 3000    # 现货新鲜度门槛(全市场应有量级)

_TERMINAL_STATUSES = {"skipped_gap", "halted", "no_trigger", "closed"}


class LiveScanAlreadyRunningError(RuntimeError):
    """N型补涨打板盘中扫描已有任务在执行。"""


def in_scan_window(now: datetime) -> bool:
    """是否处于扫描窗口(工作日 09:30~15:00)。"""
    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    return time(*contracts.SCAN_START) <= current <= time(*contracts.SCAN_END)


def run_live_scan_tick(now: datetime | None = None) -> dict[str, object]:
    """执行一次分钟扫描(调度每分钟触发;窗口外直接跳过)。"""
    started = datetime.now(SHANGHAI)
    if not in_scan_window(started):
        return {"status": "skipped", "message": "不在扫描窗口(09:30~15:00 工作日)"}
    today = started.date()
    pool = repository.load_pool(today)
    if not pool:
        return {"status": "skipped", "message": f"{today} 无盘前池(等待盘后计算)"}
    try:
        with _scan_lock():
            result = _scan_once(today, pool, started)
    except LiveScanAlreadyRunningError:
        return {"status": "skipped", "message": "上一次扫描仍在执行,跳过"}
    except Exception as exc:  # noqa: BLE001
        logger.warning("w2s live scan failed: %s", exc, exc_info=True)
        _save_run(today, started, status="failed", error=f"{exc.__class__.__name__}: {exc}",
                  pool_count=len(pool))
        return {"status": "failed", "message": f"{exc.__class__.__name__}"}
    return result


def _scan_once(today: date, pool: list[dict[str, object]], now: datetime) -> dict[str, object]:
    from alphaagent.data_sources.akshare_adapter import AkShareAdapter

    spot = AkShareAdapter().all_stock_ohlcv_spot(force_refresh=True)
    items = {
        str(it.get("vt_symbol") or "").upper(): it
        for it in (spot.get("items") or []) if isinstance(it, dict)
    }
    fresh = _count_fresh_items(items, today)
    if fresh < MIN_SPOT_FRESH_SYMBOLS:
        _save_run(today, now, status="stale_spot", pool_count=len(pool),
                  spot_active_symbols=fresh,
                  message=f"现货快照非今日数据(新鲜 {fresh}),跳过(节假日或数据源异常)")
        return {"status": "skipped", "message": "现货快照非今日数据"}

    signals = repository.load_signal_map(today)
    touched = entered = 0
    writes: list[tuple[tuple[str, str], dict[str, object]]] = []

    for entry in pool:
        vt = str(entry["vt_symbol"])
        group_key = str(entry["group_key"])
        key = (vt, group_key)
        if not bool(entry.get("actionable")):
            continue  # 雷达票(触发池全量)只展示不触发,不写信号
        sig = signals.get(key)
        status = str(sig.get("status")) if sig else "watching"
        if status in _TERMINAL_STATUSES:
            continue
        patch: dict[str, object] = {
            "name": entry.get("name"), "prev_close": entry.get("prev_close"),
            "trigger_price": entry.get("trigger_price"),
            "rules_version": contracts.W2S_RULES_VERSION,
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
        trigger = float(entry["trigger_price"])   # = 涨停价(板上买)
        limit_price = float(entry.get("limit_price") or 0.0)
        patch["last_price"] = last_price
        patch["change_pct"] = round((last_price / prev_close - 1) * 100, 3)

        # 一字排除:首次见到开盘价即涨停 → 买不进,当日终态
        if status == "watching" and open_price and open_price > 0:
            patch["gap_open"] = round(open_price / prev_close - 1, 5)
            if limit_price > 0 and open_price >= limit_price - 1e-6:
                patch["status"] = "skipped_gap"
                writes.append((key, patch))
                continue

        if status == "watching":
            # 板上买:现价触及涨停价立即打(触及即买,无确认)
            if last_price >= trigger:
                patch["status"] = "entered"
                patch["touched_at"] = now
                patch["entry_price"] = trigger
                patch["entry_time"] = now
                touched += 1
                entered += 1
        writes.append((key, patch))

    for key, patch in writes:
        repository.upsert_signal(today, key[0], key[1], **patch)
    _save_run(today, now, status="ok", pool_count=len(pool),
              touched_count=touched, entered_count=entered, spot_active_symbols=fresh,
              message=f"池 {len(pool)} / 新触发 {touched} / 新买入 {entered} / 写 {len(writes)}")
    return {"status": "ok", "pool": len(pool), "touched": touched,
            "entered": entered, "writes": len(writes)}


def _count_fresh_items(items: dict[str, dict[str, object]], today: date) -> int:
    """统计 trade_time 属于今日的现货行数(节假日快照整体陈旧,新鲜数为 0 整体跳过)。"""
    fresh = 0
    prefix = today.isoformat()
    for it in items.values():
        trade_time = str(it.get("trade_time") or "")
        volume = _num(it.get("volume")) or 0.0
        if volume > 0 and trade_time.startswith(prefix):
            fresh += 1
    return fresh


def _save_run(trade_date: date, started: datetime, *, status: str,
              pool_count: int | None = None, touched_count: int | None = None,
              entered_count: int | None = None, spot_active_symbols: int | None = None,
              message: str | None = None, error: str | None = None) -> None:
    finished = datetime.now(SHANGHAI)
    repository.save_scan_run(
        trade_date=trade_date, started_at=started, finished_at=finished,
        duration_ms=int((finished - started).total_seconds() * 1000),
        status=status, pool_count=pool_count, touched_count=touched_count,
        entered_count=entered_count, spot_active_symbols=spot_active_symbols,
        rules_version=contracts.W2S_RULES_VERSION, message=message, error=error,
    )


@contextmanager
def _scan_lock() -> Iterator[None]:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as connection:
        acquired = bool(connection.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
        ).scalar_one())
        connection.commit()
        if not acquired:
            raise LiveScanAlreadyRunningError
        try:
            yield
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_LOCK_KEY})
            connection.commit()


def _num(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if number is not None and math.isfinite(number) else None
