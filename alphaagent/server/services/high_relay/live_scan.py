"""高位接力打板盘中每分钟扫描:首刻触板买(09:30~09:45) + 竞价门 + T字排板。

口径(高位接力规则.md v1.3 盘中规则):
- 扫描窗口 09:30~15:00 全日(状态跟踪);买入触发只在首刻窗 09:30~09:45
- 只对 actionable(命中方案点且非静态回避)的池票触发;雷达票只展示不写信号
- 竞价门(9:30 首跳开盘价定型):
    A2(三接四阴)竞价<0 或 ≥9.5% → skipped_auction(回避,当日终态)
    B2(二接三阳)竞价不在 4~7% → skipped_auction(点定义的一部分)
- 一字开(开盘价≥涨停价)→ sealed_watch(T字观察):
    盘中打开(现价<涨停价)→ 按涨停价排板成交,entered(研究口径:T字可买,
    买价=涨停价;一字全天不开买不进);全天不开 → EOD 判 skipped_gap
- 首刻触发:09:30~09:45 内现价首次 ≥ 涨停价 → entered,买入价=涨停价
- 迟到:09:45 之后才首次触板 → late_touch(放弃,当日终态)
- 卖出由 EOD 定版(E3:炸板当日收盘走;封住→断板日收盘,15 日兜底)
- 现货快照 freshness 以 trade_time 日期兜底(节假日不交易不产生假信号)
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import text

from alphaagent.server.db.session import get_engine
from alphaagent.server.services.high_relay import contracts, repository

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_ADVISORY_LOCK_KEY = 726103
MIN_SPOT_FRESH_SYMBOLS = 3000    # 现货新鲜度门槛(全市场应有量级)

_TERMINAL_STATUSES = {"skipped_auction", "skipped_gap", "late_touch",
                      "no_trigger", "closed"}


class LiveScanAlreadyRunningError(RuntimeError):
    """高位接力盘中扫描已有任务在执行。"""


def in_scan_window(now: datetime) -> bool:
    """是否处于扫描窗口(工作日 09:30~15:00)。"""
    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    return time(*contracts.SCAN_START) <= current <= time(*contracts.SCAN_END)


def _in_first_touch_window(now: datetime) -> bool:
    """首刻窗 09:30~09:45(09:45:xx 的 tick 仍属首刻段,09:46 起算迟到)。"""
    current = now.timetz().replace(tzinfo=None)
    return current < time(9, 46)


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
        logger.warning("hpr live scan failed: %s", exc, exc_info=True)
        _save_run(today, started, status="failed", error=f"{exc.__class__.__name__}: {exc}",
                  pool_count=len(pool))
        return {"status": "failed", "message": f"{exc.__class__.__name__}"}
    return result


def _auction_gate_fail(gate: str | None, auction_pct: float) -> bool:
    """竞价门判定:落窗外=回避。"""
    if gate == "a2_0_9.5":
        return not (contracts.A2_AUCTION_LO <= auction_pct < contracts.A2_AUCTION_HI)
    if gate == "b2_4_7":
        return not (contracts.B2_AUCTION_LO <= auction_pct < contracts.B2_AUCTION_HI)
    return False


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
    touched = entered = auction_skipped = 0
    writes: list[tuple[str, dict[str, object]]] = []
    first_window = _in_first_touch_window(now)

    for entry in pool:
        if not bool(entry.get("actionable")):
            continue  # 雷达票(未命中/静态回避)只展示不触发,不写信号
        vt = str(entry["vt_symbol"])
        sig = signals.get(vt)
        status = str(sig.get("status")) if sig else "watching"
        if status in _TERMINAL_STATUSES:
            continue
        patch: dict[str, object] = {
            "name": entry.get("name"), "group4": entry.get("group4"),
            "point": entry.get("point"), "level": entry.get("level"),
            "prev_close": entry.get("prev_close"),
            "limit_price": entry.get("limit_price"),
            "rules_version": contracts.HPR_RULES_VERSION,
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
        limit_price = float(entry["limit_price"])   # 触发价=涨停价
        patch["last_price"] = last_price
        patch["change_pct"] = round((last_price / prev_close - 1) * 100, 3)

        # 首跳:竞价涨幅定型 + 竞价门判定 + 一字开分流
        if status == "watching" and (sig is None or sig.get("auction_pct") is None):
            if open_price and open_price > 0:
                auction_pct = round((open_price / prev_close - 1) * 100, 2)
                patch["auction_pct"] = auction_pct
                if _auction_gate_fail(entry.get("auction_gate"), auction_pct):
                    patch["status"] = "skipped_auction"
                    auction_skipped += 1
                    writes.append((vt, patch))
                    continue
                if open_price >= limit_price - 1e-6:
                    # 一字开 → T字观察(不判死刑;打开=排板成交,全天不开=买不进)
                    patch["status"] = "sealed_watch"
                    patch["opened"] = False
                    writes.append((vt, patch))
                    continue

        if status == "sealed_watch" or patch.get("status") == "sealed_watch":
            # T字观察:打开(现价<涨停价)=排板成交(研究口径:买价=涨停价)
            if last_price < limit_price - 1e-6:
                patch["opened"] = True
                patch["status"] = "entered"
                patch["touched_at"] = (sig or {}).get("touched_at") or now
                patch["entry_price"] = limit_price
                patch["entry_time"] = now
                entered += 1
                touched += 1
            writes.append((vt, patch))
            continue

        if status == "watching":
            # 首刻触板:现价首次 ≥ 涨停价 → 按涨停价打
            if last_price >= limit_price - 1e-6:
                if first_window:
                    patch["status"] = "entered"
                    patch["touched_at"] = now
                    patch["entry_price"] = limit_price
                    patch["entry_time"] = now
                    touched += 1
                    entered += 1
                else:
                    patch["status"] = "late_touch"
                    patch["touched_at"] = now
        writes.append((vt, patch))

    for vt, patch in writes:
        repository.upsert_signal(today, vt, **patch)
    _save_run(today, now, status="ok", pool_count=len(pool),
              touched_count=touched, entered_count=entered, spot_active_symbols=fresh,
              message=f"池 {len(pool)} / 新触发 {touched} / 新买入 {entered} / "
                      f"竞价回避 {auction_skipped} / 写 {len(writes)}")
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
        rules_version=contracts.HPR_RULES_VERSION, message=message, error=error,
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
