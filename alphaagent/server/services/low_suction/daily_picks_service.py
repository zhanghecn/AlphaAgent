"""低吸日线实时推荐服务：30 分钟缓存 + 盘中现货合成当日虚拟 K 线。

盘中（09:25-15:30 工作日）用全市场现货快照给每只股票合成一根今日虚拟
日线（最新价当收盘），与历史日线拼接后走同一套研究票规则扫描和诊断评分；
盘后等 stock_daily_bars 统一同步落地后自动切换为确认日线。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import func, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope
from alphaagent.server.services.low_suction.daily_factor_repository import (
    load_daily_factor_inputs,
)
from alphaagent.server.services.low_suction.daily_picks_backtest import (
    BACKTEST_VERSION,
    build_backtest_payload,
)
from alphaagent.server.services.low_suction.daily_picks_repository import (
    load_daily_backtest_run,
    save_daily_backtest_run,
)
from alphaagent.server.services.low_suction.daily_picks_scanner import (
    LowSuctionCandidate,
    candidate_ranking_key,
    scan_low_suction_candidates,
)
from alphaagent.server.services.low_suction.daily_picks_scoring import SCORE_VERSION


SHANGHAI = ZoneInfo("Asia/Shanghai")
LIVE_CACHE_TTL_SECONDS = 30 * 60  # 交易日内每半小时重算一次缓存
LIVE_LOOKBACK_CALENDAR_DAYS = 10  # 加载日历窗口；特征 warmup 由加载器另加 120 天
LIVE_MAX_ITEMS_PER_FAMILY = 100
LIVE_PAGE_SIZE = 20
SPOT_MERGE_START = time(9, 25)
SPOT_MERGE_END = time(15, 30)
MIN_SPOT_ACTIVE_SYMBOLS = 3_000

_logger = logging.getLogger(__name__)
_cache_lock = threading.Lock()
_cache: dict[str, object] = {"expires_at": None, "payload": None}
# 日线输入按“最新可靠交易日”缓存：盘中 30 分钟重算只重扫不重读库
_inputs_cache: dict[str, object] = {"key": None, "inputs": None}
_warm_thread: threading.Thread | None = None


def start_low_suction_live_warmup() -> None:
    """Warm the day-level inputs cache at startup so the first live hit is fast."""

    global _warm_thread
    with _cache_lock:
        if _warm_thread is not None and _warm_thread.is_alive():
            return

        def _warm() -> None:
            try:
                get_live_recommendations()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("low-suction live warmup failed: %s", exc)

        _warm_thread = threading.Thread(
            target=_warm,
            name="low-suction-live-warmup",
            daemon=True,
        )
        _warm_thread.start()



def get_live_recommendations(
    *,
    trend_page: int = 1,
    oversold_page: int = 1,
) -> dict[str, object]:
    """Read cached live recommendations and return independent family pages."""

    now = datetime.now(SHANGHAI)
    with _cache_lock:
        expires_at = _cache.get("expires_at")
        payload = _cache.get("payload")
        if payload is not None and expires_at is not None and now < expires_at:  # type: ignore[operator]
            return _paginate_live_payload(
                payload, trend_page=trend_page, oversold_page=oversold_page
            )  # type: ignore[arg-type]
    payload = _compute_live_payload(now)
    with _cache_lock:
        _cache["payload"] = payload
        _cache["expires_at"] = now + timedelta(seconds=LIVE_CACHE_TTL_SECONDS)
    return _paginate_live_payload(
        payload, trend_page=trend_page, oversold_page=oversold_page
    )


def get_daily_backtest_report() -> dict[str, object] | None:
    """Read the materialized backtest payload (CLI 写库，API 读库）。"""

    payload = load_daily_backtest_run()
    if payload is None:
        return None
    return payload if payload.get("version") == BACKTEST_VERSION else None


# 回测物化：后台线程 + 状态（仿 limit_up history_service 的 rebuild 模式）。
# 全量扫描 ~69 万候选耗时数分钟，不能在 API 请求线程同步跑。
_REBUILD_LOCK = threading.RLock()
_REBUILD_THREAD: threading.Thread | None = None
_REBUILD_STATE: dict[str, object] = {"status": "idle"}


def run_daily_backtest_sync(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, object]:
    """Synchronously rebuild and persist the daily backtest payload."""

    inputs = load_daily_factor_inputs(
        start_date=start_date,
        end_date=end_date,
        price_basis="raw_unadjusted",
    )
    candidates = scan_low_suction_candidates(
        inputs.bars,
        inputs.market_calendar,
        inputs.security_status.to_dict(orient="records"),
    )
    names = _load_stock_names({item.vt_symbol for item in candidates})
    candidates = _exclude_current_st_candidates(candidates, names)
    payload = build_backtest_payload(
        candidates,
        inputs.market_calendar,
        names=names,
        market_regimes=_load_market_regimes(inputs.market_calendar),
    )
    save_daily_backtest_run(BACKTEST_VERSION, payload)
    return payload


def start_daily_backtest_rebuild() -> dict[str, object]:
    """Launch the backtest rebuild in a background thread (returns immediately)."""

    global _REBUILD_THREAD
    with _REBUILD_LOCK:
        if _REBUILD_THREAD is not None and _REBUILD_THREAD.is_alive():
            return {**_REBUILD_STATE, "already_running": True}
        _set_rebuild_state(status="building", started_at=_utc_now_iso(), error=None)
        _REBUILD_THREAD = threading.Thread(
            target=_background_daily_backtest_rebuild,
            name="low-suction-backtest-rebuild",
            daemon=True,
        )
        _REBUILD_THREAD.start()
        return dict(_REBUILD_STATE)


def _background_daily_backtest_rebuild() -> None:
    try:
        payload = run_daily_backtest_sync()
        coverage = payload.get("coverage") or {}
        _set_rebuild_state(
            status="ready",
            finished_at=_utc_now_iso(),
            error=None,
            trade_days=coverage.get("trade_days"),
            labeled=coverage.get("labeled"),
        )
    except Exception as exc:  # noqa: BLE001
        _set_rebuild_state(
            status="failed",
            finished_at=_utc_now_iso(),
            error={"type": exc.__class__.__name__, "message": str(exc)},
        )


def get_daily_backtest_rebuild_status() -> dict[str, object]:
    """Read the current rebuild state for frontend polling."""

    with _REBUILD_LOCK:
        return dict(_REBUILD_STATE)


def _set_rebuild_state(**values: object) -> None:
    with _REBUILD_LOCK:
        _REBUILD_STATE.update(values)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _live_inputs(now: datetime):
    """Load daily inputs once per latest reliable trade date (day-level cache)."""

    probe_start = now.date() - timedelta(days=LIVE_LOOKBACK_CALENDAR_DAYS)
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date, func.count())
            .where(schema.stock_daily_bars.c.trade_date >= probe_start)
            .group_by(schema.stock_daily_bars.c.trade_date)
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()
    reliable = [row[0] for row in rows if int(row[1] or 0) >= 3_000]
    latest = reliable[-1] if reliable else None
    with _cache_lock:
        if latest is not None and _inputs_cache.get("key") == latest:
            return _inputs_cache["inputs"]
    inputs = load_daily_factor_inputs(
        start_date=probe_start,
        end_date=None,
        price_basis="raw_unadjusted",
    )
    with _cache_lock:
        _inputs_cache["key"] = latest
        _inputs_cache["inputs"] = inputs
    return inputs


def _compute_live_payload(now: datetime) -> dict[str, object]:
    inputs = _live_inputs(now)
    calendar = list(inputs.market_calendar)
    bars = inputs.bars
    provisional = False
    merge_note = None
    if not calendar:
        return {
            "status": "unavailable",
            "message": "无可靠市场日历，请检查日线数据同步",
            "asof": now.isoformat(timespec="seconds"),
        }

    latest_bar_date = calendar[-1]
    if _should_merge_spot(now, latest_bar_date):
        merged, active = _merge_spot_bars(bars, now.date())
        if active >= MIN_SPOT_ACTIVE_SYMBOLS:
            bars = merged
            calendar = [*calendar, now.date()]
            provisional = now.time() < time(15, 5)
            merge_note = (
                f"盘中虚拟K线（{active} 只有成交股票，最新价当收盘）"
                if provisional
                else "盘后现货快照合成当日K线（等待日线同步确认）"
            )
        else:
            merge_note = f"现货快照有效股票不足（{active} 只），沿用最近完整日线"

    target_date = calendar[-1]
    # 单日扫描：日历只放目标日，候选特征只算当日（全量 K 线历史仍在 bars 里供 warmup）
    candidates = scan_low_suction_candidates(
        bars,
        [target_date],
        inputs.security_status.to_dict(orient="records"),
        target_dates={target_date},
    )
    names = _load_stock_names({item.vt_symbol for item in candidates})
    trend = _family_payload(candidates, "trend_pullback", names)
    oversold = _family_payload(candidates, "oversold_rebound", names)
    return {
        "status": "ok",
        "asof": now.isoformat(timespec="seconds"),
        "trade_date": target_date.isoformat(),
        "provisional": provisional,
        "merge_note": merge_note,
        "cache_ttl_seconds": LIVE_CACHE_TTL_SECONDS,
        "score_version": SCORE_VERSION,
        "backtest_version": BACKTEST_VERSION,
        "trend": trend,
        "oversold": oversold,
        "label_convention": "raw_unadjusted 探索级 · D+1 收盘到收盘口径 · 未扣费",
    }


def _family_payload(
    candidates: list[LowSuctionCandidate],
    setup_type: str,
    names: dict[str, str],
) -> dict[str, object]:
    pool = [item for item in candidates if item.setup_type == setup_type]
    pool = [item for item in pool if not _is_st_name(names.get(item.vt_symbol))]
    # 与回测同一决胜键：分数 → 连续小 K 线数 → 换手率(低优先) → 代码
    pool.sort(key=candidate_ranking_key)
    items: list[dict[str, object]] = []
    for rank, candidate in enumerate(pool[:LIVE_MAX_ITEMS_PER_FAMILY], start=1):
        row = candidate.as_dict()
        row["stock_name"] = names.get(candidate.vt_symbol)
        row["rank"] = rank
        row.pop("d1_close_return_pct", None)
        row.pop("d1_trade_date", None)
        items.append(row)
    return {
        "total": len(pool),
        "limit": LIVE_MAX_ITEMS_PER_FAMILY,
        "items": items,
    }


def _exclude_current_st_candidates(
    candidates: list[LowSuctionCandidate],
    names: dict[str, str],
) -> list[LowSuctionCandidate]:
    """Keep the exploratory historical pool consistent with the live ST screen."""

    return [
        candidate
        for candidate in candidates
        if not _is_st_name(names.get(candidate.vt_symbol))
    ]


def _paginate_live_payload(
    payload: dict[str, object],
    *,
    trend_page: int,
    oversold_page: int,
) -> dict[str, object]:
    """Page a cached top-100 payload without rerunning the market scan."""

    result = dict(payload)
    for setup_type, requested_page in (
        ("trend", trend_page),
        ("oversold", oversold_page),
    ):
        family = payload.get(setup_type)
        if not isinstance(family, dict):
            continue
        all_items = list(family.get("items") or [])
        pages = max(1, (len(all_items) + LIVE_PAGE_SIZE - 1) // LIVE_PAGE_SIZE)
        page = min(max(1, requested_page), pages)
        start = (page - 1) * LIVE_PAGE_SIZE
        result[setup_type] = {
            **family,
            "items": all_items[start : start + LIVE_PAGE_SIZE],
            "page": page,
            "page_size": LIVE_PAGE_SIZE,
            "pages": pages,
        }
    return result


def _load_market_regimes(calendar: tuple[date, ...]) -> dict[date, str]:
    """Classify signal days by same-day Shanghai Composite close versus MA20."""

    if not calendar:
        return {}
    start = calendar[0] - timedelta(days=45)
    with session_scope() as session:
        rows = session.execute(
            select(schema.stock_daily_bars.c.trade_date, schema.stock_daily_bars.c.close_price)
            .where(
                schema.stock_daily_bars.c.vt_symbol == "000001.SSE",
                schema.stock_daily_bars.c.trade_date >= start,
                schema.stock_daily_bars.c.trade_date <= calendar[-1],
            )
            .order_by(schema.stock_daily_bars.c.trade_date)
        ).all()
    closes: list[tuple[date, float]] = [
        (row[0], float(row[1])) for row in rows if row[1] is not None
    ]
    regimes: dict[date, str] = {}
    for index in range(19, len(closes)):
        trade_date, close_price = closes[index]
        ma20 = sum(value for _, value in closes[index - 19 : index + 1]) / 20
        regimes[trade_date] = "above_ma20" if close_price >= ma20 else "below_ma20"
    return regimes


def _should_merge_spot(now: datetime, latest_bar_date: date) -> bool:
    if now.date() <= latest_bar_date:
        return False
    if now.weekday() >= 5:
        return False
    return SPOT_MERGE_START <= now.time() <= SPOT_MERGE_END


def _merge_spot_bars(bars: pd.DataFrame, today: date) -> tuple[pd.DataFrame, int]:
    """Append synthetic today bars from the full-market spot snapshot."""

    try:
        from alphaagent.data_sources.akshare_adapter import (
            AkShareAdapter,
            _stock_row_to_api,
        )

        raw_rows = AkShareAdapter()._all_stock_spot_rows()  # noqa: SLF001
        rows = [_stock_row_to_api(row) for row in raw_rows]
    except Exception as exc:  # noqa: BLE001
        _logger.warning("low-suction live spot snapshot unavailable: %s", exc)
        return bars, 0
    existing = (
        set(bars.loc[bars["trade_date"] == today, "vt_symbol"]) if not bars.empty else set()
    )
    synthetic: list[dict[str, object]] = []
    for row in rows:
        vt_symbol = str(row.get("vt_symbol") or "")
        if not vt_symbol or vt_symbol in existing or not _is_main_board(vt_symbol):
            continue
        last = _float(row.get("last_price"))
        open_price = _float(row.get("open_price"))
        high = _float(row.get("high_price"))
        low = _float(row.get("low_price"))
        volume = _float(row.get("volume"))
        if not last or not open_price or not high or not low or not volume:
            continue
        synthetic.append(
            {
                "vt_symbol": vt_symbol,
                "trade_date": today,
                "open_price": open_price,
                "close_price": last,
                "high_price": max(high, open_price, last),
                "low_price": min(low, open_price, last),
                "volume": volume,
                "turnover": _float(row.get("turnover")),
                "turnover_rate": _float(row.get("turnover_rate")),
                "source": "akshare_spot_intraday",
                "updated_at": None,
            }
        )
    if not synthetic:
        return bars, 0
    frame = pd.concat([bars, pd.DataFrame(synthetic)], ignore_index=True)
    return frame, len(synthetic)


def _load_stock_names(vt_symbols: set[str]) -> dict[str, str]:
    if not vt_symbols:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(schema.stocks.c.vt_symbol, schema.stocks.c.name).where(
                schema.stocks.c.vt_symbol.in_(tuple(vt_symbols))
            )
        ).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _is_st_name(name: str | None) -> bool:
    return bool(name) and "ST" in name.upper()


def _is_main_board(vt_symbol: str) -> bool:
    symbol, _, exchange = vt_symbol.partition(".")
    if exchange == "SSE":
        return symbol.startswith(("600", "601", "603", "605"))
    if exchange == "SZSE":
        return symbol.startswith(("000", "001", "002", "003"))
    return False


def _float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
