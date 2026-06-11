"""AlphaAgent market-data provider entrypoints."""

from __future__ import annotations

from alphaagent.data_sources.akshare_adapter import AkShareAdapter


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
            return local
        return _mark_live_api(super().stock_bars(symbol, exchange, limit=limit, interval=interval), fallback_used=True)

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
