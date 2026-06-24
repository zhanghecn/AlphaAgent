"""AlphaAgent market-data provider entrypoints."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from alphaagent.data_sources.akshare_adapter import AkShareAdapter


_CHINA_TZ = timezone(timedelta(hours=8))


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def _parse_bar_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _is_intraday_china(now: datetime | None = None) -> bool:
    """是否在 A 股交易时段(周一-周五 9:30-15:00,中国时间)。

    仅做时段过滤;实际"今天是否有行情"由实时 volume>0 判断(自动覆盖节假日/半天/异常停牌)。
    """
    now = now or datetime.now(_CHINA_TZ)
    if now.weekday() >= 5:  # 周六、周日
        return False
    current = now.time()
    return time(9, 30) <= current < time(15, 0)


def _china_today() -> date:
    """当前中国日期(可被测试注入)。"""
    return datetime.now(_CHINA_TZ).date()


class MarketDataError(RuntimeError):
    """Raised when real market data cannot be loaded."""


class RealMarketDataClient(AkShareAdapter):
    """Runtime market data client backed by local sync tables and AkShare."""

    def __init__(self, timeout: float = 8.0) -> None:
        super().__init__()
        self.timeout = timeout

    def stock_bars(
        self,
        symbol: str,
        exchange: str | None = None,
        limit: int = 90,
        interval: str = "1d",
    ) -> dict[str, object]:
        local = _local_stock_bars(symbol, exchange, limit=limit, interval=interval)
        if local:
            items = local.get("items") or []
            if interval == "1d":
                merged = self._with_today_realtime_bar(symbol, exchange, items)
                if merged is not items:
                    return {**local, "items": merged}
            return local
        return _mark_live_api(super().stock_bars(symbol, exchange, limit=limit, interval=interval), fallback_used=True)

    def _with_today_realtime_bar(
        self,
        symbol: str,
        exchange: str | None,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """交易时段 + DB最新<今天 + 实时volume>0 时,append 今天实时K线(同花顺式)。

        不写 DB,仅读取时合并。节假日/盘前 volume=0 自动不补;
        18:00 eod 同步今天日线后 DB 最新==今天,自动停补转正式日线。
        """
        if not items or not _is_intraday_china():
            return items
        today = _china_today()
        last_date = _parse_bar_date(items[-1].get("trade_date"))
        if last_date is None or last_date >= today:
            return items
        try:
            quote = self.stock_detail(symbol, exchange) or {}
        except Exception:
            return items
        volume = _to_float(quote.get("volume"))
        last_price = _to_float(quote.get("last_price"))
        if not volume or volume <= 0 or last_price is None:
            return items
        today_bar = {
            "trade_date": today.isoformat(),
            "open": _to_float(quote.get("open_price")) or last_price,
            "close": last_price,
            "high": _to_float(quote.get("high_price")) or last_price,
            "low": _to_float(quote.get("low_price")) or last_price,
            "volume": volume,
            "turnover": _to_float(quote.get("turnover")) or _to_float(quote.get("amount")),
            "change_pct": _to_float(quote.get("change_pct")),
        }
        return items + [today_bar]

    def market_overview(self) -> dict[str, object]:
        return _mark_live_api(super().market_overview(), fallback_used=False)

    def list_stocks(self, page: int = 1, page_size: int = 50, sort: str = "mktcap", order: str = "desc") -> dict[str, object]:
        local = _local_list_stocks(page=page, page_size=page_size, sort=sort, q="", order=order)
        if local:
            return local
        try:
            return _mark_live_api(super().list_stocks(page=page, page_size=page_size, sort=sort, order=order), fallback_used=False)
        except Exception:
            raise

    def search_stocks(self, query: str, page_size: int = 50) -> dict[str, object]:
        local = _local_list_stocks(page=1, page_size=page_size, sort="mktcap", q=query)
        if local and (query.strip() or local.get("items")):
            return local
        try:
            return _mark_live_api(super().search_stocks(query, page_size=page_size), fallback_used=False)
        except Exception:
            raise

    def stock_detail(self, symbol: str, exchange: str | None = None) -> dict[str, object]:
        return _mark_live_api(super().stock_detail(symbol, exchange), fallback_used=False)

    def list_sectors(self, sector_type: str = "") -> dict[str, object]:
        local = _local_list_sectors(sector_type)
        if local:
            return local
        return _mark_live_api(super().list_sectors(sector_type), fallback_used=True)

    def sector_stocks(
        self,
        sector_id: str,
        page: int = 1,
        page_size: int = 50,
        sort: str = "changepercent",
        with_returns: bool = False,
        q: str = "",
    ) -> dict[str, object]:
        # Local DB lacks period return data — skip when returns are requested
        skip_local = with_returns or sort.strip().lower() in ("return_5d", "return_10d", "return_20d")
        if not skip_local:
            local = _local_sector_stocks(sector_id, page=page, page_size=page_size, sort=sort, with_returns=with_returns, q=q)
            if local:
                return local
        return _mark_live_api(
            super().sector_stocks(sector_id, page=page, page_size=page_size, sort=sort, with_returns=with_returns, q=q),
            fallback_used=True,
        )

    def sector_trend(self, sector_id: str, page_size: int = 100, pages: int = 3) -> dict[str, object]:
        del page_size, pages
        local = _local_sector_trend(sector_id)
        if local:
            return local
        return _mark_live_api(super().sector_trend(sector_id), fallback_used=True)

    def stock_sectors(self, symbol: str, exchange: str | None = None) -> dict[str, object]:
        local = _local_stock_sectors(symbol, exchange)
        if local:
            return local
        return _mark_live_api(super().stock_sectors(symbol, exchange), fallback_used=True)

    # ── Shenwan Industry Classification ──

    def shenwan_industry_tree(self, level: int = 1) -> dict[str, object]:
        local = _local_shenwan_industry_tree(level)
        if local:
            return local
        return _mark_live_api(super().shenwan_industry_tree(level), fallback_used=True)

    def shenwan_industry_detail(self, code: str) -> dict[str, object]:
        local = _local_shenwan_industry_detail(code)
        if local:
            return local
        return {"code": code, "status": "unavailable", "source": "alphaagent"}

    def shenwan_industry_graph(self, code: str, level: int = 2) -> dict[str, object]:
        local = _local_shenwan_industry_graph(code, level)
        if local:
            return local
        return {"industry_code": code, "nodes": [], "edges": [], "status": "unavailable", "source": "alphaagent"}


def _mark_live_api(data: dict[str, object], fallback_used: bool) -> dict[str, object]:
    """Annotate live-source payloads so the UI can show where data came from."""

    return {
        **data,
        "data_origin": data.get("data_origin") or "live_api",
        "storage_table": data.get("storage_table"),
        "fallback_used": data.get("fallback_used") if "fallback_used" in data else fallback_used,
    }


def _local_list_stocks(page: int, page_size: int, sort: str, q: str, order: str = "desc") -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_list_stocks
    except Exception:
        return None
    return local_list_stocks(page=page, page_size=page_size, sort=sort, q=q, order=order)


def _local_list_sectors(sector_type: str) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_list_sectors
    except Exception:
        return None
    return local_list_sectors(sector_type)


def _local_sector_stocks(
    sector_id: str,
    page: int,
    page_size: int,
    sort: str,
    with_returns: bool,
    q: str,
) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_sector_stocks
    except Exception:
        return None
    return local_sector_stocks(sector_id, page=page, page_size=page_size, sort=sort, with_returns=with_returns, q=q)


def _local_sector_trend(sector_id: str) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_sector_trend
    except Exception:
        return None
    return local_sector_trend(sector_id)


def _local_stock_bars(symbol: str, exchange: str | None, limit: int, interval: str) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_stock_bars
    except Exception:
        return None
    return local_stock_bars(symbol, exchange, limit=limit, interval=interval)


def _local_stock_sectors(symbol: str, exchange: str | None) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_stock_sectors
    except Exception:
        return None
    return local_stock_sectors(symbol, exchange)


def _local_shenwan_industry_tree(level: int) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_shenwan_industry_tree
    except Exception:
        return None
    return local_shenwan_industry_tree(level)


def _local_shenwan_industry_detail(code: str) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_shenwan_industry_detail
    except Exception:
        return None
    return local_shenwan_industry_detail(code)


def _local_shenwan_industry_graph(code: str, level: int) -> dict[str, object] | None:
    try:
        from alphaagent.server.services.data_sync import local_shenwan_industry_graph
    except Exception:
        return None
    return local_shenwan_industry_graph(code, level)
