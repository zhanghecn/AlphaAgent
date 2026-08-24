"""潜龙首板盘中每分钟扫描:触及 +8% 检测 → 收住确认 → 不爆量校验 → 模拟买入。

口径(与定稿 v6 盘中规则对应):
- 只在 09:30~11:30 产生新触发;11:29 的触发允许在 11:30/11:31 完成确认
- 高开 ≥ +8% → skipped_gap 禁做;B 类(小阳建仓)→ priority 优先标记
- 首次 现价 ≥ 昨收×1.08 → touched;下一分钟扫描时现价仍 ≥ 触发价
  且 当时累计量 ÷ 前5日均量 < 1.0(不爆量)→ holding 并模拟买入
  (买入价 = 确认现价 ×(1+0.5% 滑点));
  跌回触发价下 或 已爆量 → unconfirmed(放弃,当日不再跟踪)
- 现货快照 freshness 以 trade_time 日期兜底(节假日不交易不产生假信号)
- 现货为新浪快照,volume 单位为股;日线库 volume 单位为手(差 100 倍,
  见 spot-volume-unit-mismatch 事故记录),换算后计算量比
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
from alphaagent.server.services.qianlong import contracts, repository

logger = logging.getLogger(__name__)
SHANGHAI = ZoneInfo("Asia/Shanghai")
_ADVISORY_LOCK_KEY = 726101
_SCAN_LATEST = time(11, 31)       # 扫描最晚时刻(只用于完成 11:30 前触发的确认)
_NEW_TOUCH_LATEST = time(11, 30)  # 新触发截止
MIN_SPOT_FRESH_SYMBOLS = 3000     # 现货新鲜度门槛(全市场应有量级)
SPOT_VOLUME_PER_LOT = 100.0       # 新浪现货 volume=股 → ÷100 = 手(日线库单位)


class LiveScanAlreadyRunningError(RuntimeError):
    """潜龙首板盘中扫描已有任务在执行。"""


def in_scan_window(now: datetime) -> bool:
    """是否处于扫描窗口(工作日 09:30~11:31)。"""
    if now.weekday() >= 5:
        return False
    current = now.timetz().replace(tzinfo=None)
    return time(*contracts.SESSION_START) <= current <= _SCAN_LATEST


def run_live_scan_tick(now: datetime | None = None) -> dict[str, object]:
    """执行一次分钟扫描(调度每分钟触发;窗口外直接跳过)。"""
    started = datetime.now(SHANGHAI)
    if not in_scan_window(started):
        return {"status": "skipped", "message": "不在扫描窗口(09:30~11:31 工作日)"}
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
        logger.warning("qianlong live scan failed: %s", exc, exc_info=True)
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
    allow_new_touch = now.timetz().replace(tzinfo=None) <= _NEW_TOUCH_LATEST
    touched = entered = 0
    writes: list[tuple[str, dict[str, object]]] = []

    for entry in pool:
        vt = str(entry["vt_symbol"])
        item = items.get(vt)
        sig = signals.get(vt)
        status = str(sig.get("status")) if sig else "watching"
        if status in {"unconfirmed", "skipped_gap", "no_trigger"}:
            continue  # 终态不再跟踪
        if item is None:
            continue
        last_price = _num(item.get("last_price"))
        open_price = _num(item.get("open_price"))
        volume = _num(item.get("volume")) or 0.0
        if volume <= 0 or last_price is None or last_price <= 0:
            continue  # 停牌/未交易
        prev_close = float(entry["prev_close"])
        trigger = float(entry["trigger_price"])
        patch: dict[str, object] = {
            "name": entry.get("name"), "prev_close": prev_close, "trigger_price": trigger,
            "rules_version": contracts.QIANLONG_RULES_VERSION,
            "chassis_tag": entry.get("chassis_tag"),
            "last_price": last_price,
            "change_pct": round((last_price / prev_close - 1) * 100, 3),
        }
        gap_open = (open_price / prev_close - 1) if open_price and open_price > 0 else None
        if gap_open is not None:
            patch["gap_open"] = round(gap_open, 5)
            patch["priority"] = "B" in str(entry.get("chassis_tag") or "")
            if status == "watching" and gap_open >= contracts.GAP_SKIP:
                patch["status"] = "skipped_gap"
                writes.append((vt, patch))
                continue
        if status == "watching" and allow_new_touch and last_price >= trigger:
            patch["status"] = "touched"
            patch["touched_at"] = now
            touched += 1
        elif status == "touched":
            touched_at = sig.get("touched_at") if sig else None
            elapsed = (now - touched_at).total_seconds() if isinstance(touched_at, datetime) else 999
            if elapsed >= 55:  # 下一分钟:验证"收住" + 不爆量
                vol_ma5 = _num(entry.get("vol_ma5"))
                vol_ratio = ((volume / SPOT_VOLUME_PER_LOT) / vol_ma5
                             if vol_ma5 and vol_ma5 > 0 else None)
                if vol_ratio is not None:
                    patch["vol_ratio_touch"] = round(vol_ratio, 3)
                if last_price < trigger:
                    patch["status"] = "unconfirmed"  # 没收住
                elif vol_ratio is not None and vol_ratio >= contracts.TOUCH_VOL_RATIO_MAX:
                    patch["status"] = "unconfirmed"  # 已爆量(有人借板出货)
                else:
                    patch["status"] = "holding"  # 已买入,持有中(EOD 定版封板/连板)
                    patch["entry_price"] = round(last_price * (1 + contracts.ENTRY_SLIPPAGE), 4)
                    patch["entry_time"] = now
                    entered += 1
        writes.append((vt, patch))

    for vt, patch in writes:
        repository.upsert_signal(today, vt, **patch)
    _save_run(today, now, status="ok", pool_count=len(pool),
              touched_count=touched, entered_count=entered, spot_active_symbols=fresh,
              message=f"池 {len(pool)} / 新触及 {touched} / 新买入 {entered} / 写 {len(writes)}")
    return {"status": "ok", "pool": len(pool), "touched": touched,
            "entered": entered, "writes": len(writes)}


def _count_fresh_items(items: dict[str, dict[str, object]], today: date) -> int:
    """统计 trade_time 属于今日的现货行数。

    Sina ticktime 为完整日期时间;严格要求日期前缀等于今日——
    节假日快照整体为上一交易日数据,此时新鲜数为 0,扫描整体跳过,
    不会产生假信号。
    """
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
        rules_version=contracts.QIANLONG_RULES_VERSION, message=message, error=error,
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
