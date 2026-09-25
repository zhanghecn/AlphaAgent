"""高位接力打板盘中每分钟扫描:竞价门(今天开窗) + 触板即买。

口径(连板链组合方案 A1~D2,2026-09-25 定稿):
- 扫描窗口 09:30~15:00 全日;链条件已命中的候选票(actionable)才触发,雷达票只展示
- 竞价定型(9:30 首跳开盘价):
    开盘涨幅 ≥9.5%(顶格)→ skipped_gap(排队买不到,正常开盘口径外,终态)
    三接四阴开盘 <0% → skipped_auction(板深低开=没人接,终态)
    不在方案「今天开」窗(如 A1 要 6~9.5,B1 要 3~5)→ skipped_auction(终态)
- 触发:现价首次 ≥ 涨停价 → entered,买入价=涨停价(研究口径:触板即买,无时间窗)
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
                      "no_trigger", "closed"}   # late_touch 仅兼容历史数据


class LiveScanAlreadyRunningError(RuntimeError):
    """高位接力盘中扫描已有任务在执行。"""


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
        logger.warning("hpr live scan failed: %s", exc, exc_info=True)
        _save_run(today, started, status="failed", error=f"{exc.__class__.__name__}: {exc}",
                  pool_count=len(pool))
        return {"status": "failed", "message": f"{exc.__class__.__name__}"}
    return result


def _first_jump_status(entry: dict[str, object], auction_pct: float) -> str | None:
    """竞价定型后的终态判定;None=继续观察等触板(今天开窗命中)。"""
    if auction_pct >= contracts.TODAY_CAP:
        return "skipped_gap"        # 顶格≥9.5%,排队买不到,正常开盘口径外
    if str(entry.get("group4")) == "三接四阴" and auction_pct < 0:
        return "skipped_auction"    # 板深低开=没人接(盘中回避)
    gate = entry.get("auction_gate")            # 格式 today_{lo}_{hi}
    if gate:
        parts = str(gate).split("_")
        lo, hi = float(parts[1]), float(parts[2])
        if not (lo <= auction_pct < hi):
            return "skipped_auction"            # 不在方案「今天开」窗
    return None


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

        # 首跳:竞价涨幅定型 → 顶格/回避/今天开窗判定
        if status == "watching" and (sig is None or sig.get("auction_pct") is None):
            if open_price and open_price > 0:
                auction_pct = round((open_price / prev_close - 1) * 100, 2)
                patch["auction_pct"] = auction_pct
                term = _first_jump_status(entry, auction_pct)
                if term is not None:
                    patch["status"] = term
                    auction_skipped += 1
                    writes.append((vt, patch))
                    continue

        if status == "watching":
            # 触板即买:现价首次 ≥ 涨停价 → 按涨停价打(链式研究口径,无时间窗)
            if last_price >= limit_price - 1e-6:
                patch["status"] = "entered"
                patch["touched_at"] = now
                patch["entry_price"] = limit_price
                patch["entry_time"] = now
                touched += 1
                entered += 1
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
