"""Stock browsing endpoints for the first real-data display stage."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.market.indicators import compute_bar_indicators
from alphaagent.market.symbols import vt_symbol as build_vt_symbol
from alphaagent.market.providers import RealMarketDataClient
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok

router = APIRouter(prefix="/stocks", tags=["stocks"])


def client() -> RealMarketDataClient:
    settings = get_settings()
    return RealMarketDataClient(timeout=settings.market_timeout_seconds)


@router.get("", response_model=None)
def list_stocks(
    q: str = Query(default=""),
    industry: str = Query(default=""),
    sector: str = Query(default=""),
    market: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    sort: str = Query(default="mktcap"),
    order: str = Query(default="desc"),
):
    # Filters beyond q/sort become database-backed in the next stage.
    del industry, sector, market
    try:
        market_client = client()
        if q.strip():
            data = market_client.search_stocks(q, page_size=page_size)
        else:
            try:
                data = market_client.list_stocks(page, page_size, sort, order)
            except TypeError:
                data = market_client.list_stocks(page, page_size, sort)
        return ok(data)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实股票行情暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/search", response_model=None)
def search_stocks(
    q: str = Query(default=""),
    page_size: int = Query(default=50, ge=1, le=100),
):
    try:
        data = client().search_stocks(q, page_size=page_size) if q.strip() else {"items": [], "page": 1, "page_size": page_size, "total": 0, "source": "empty_query"}
        return ok(data)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实股票搜索暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}", response_model=None)
def stock_detail(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        return ok(client().stock_detail(symbol, exchange))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实股票详情暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}/bars", response_model=None)
def stock_bars(
    vt_symbol: str,
    interval: str = Query(default="1d"),
    start: str = Query(default=""),
    end: str = Query(default=""),
    limit: int = Query(default=120, ge=5, le=3000),
):
    del start, end
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_bars(symbol, exchange, limit=limit, interval=interval))
    except Exception as exc:
        return ok(empty_bar_series(symbol, exchange, interval, exc))


@router.get("/{vt_symbol}/indicators")
def stock_indicators(
    vt_symbol: str,
    interval: str = Query(default="1d"),
    limit: int = Query(default=120, ge=20, le=3000),
):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        bars = market_client.stock_bars(symbol, exchange, limit=limit, interval=interval)
        return ok(compute_bar_indicators(build_vt_symbol(symbol, exchange), bars["items"], source=bars.get("source")))
    except Exception as exc:
        return ok(empty_indicators(vt_symbol, exc))


@router.get("/{vt_symbol}/business")
def stock_business(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_business(symbol, exchange))
    except Exception as exc:
        return ok(empty_business(vt_symbol, exc))


@router.get("/{vt_symbol}/sectors")
def stock_sectors(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_sectors(symbol, exchange))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("SECTOR_DATA_SOURCE_UNAVAILABLE", "真实板块数据暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}/industry-chain")
def stock_industry_chain(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        market_client = client()
        symbol, exchange = resolve_symbol_exchange(market_client, symbol, exchange)
        return ok(market_client.stock_industry_chain(symbol, exchange))
    except Exception as exc:
        return ok(empty_industry_chain(vt_symbol, exc))


@router.get("/{vt_symbol}/snapshot", response_model=None)
def stock_snapshot(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    market_client = client()
    try:
        quote = market_client.stock_detail(symbol, exchange)
        symbol = str(quote.get("symbol") or symbol)
        exchange = str(quote.get("exchange") or exchange or "")
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "股票快照暂时不可用。", {"reason": exc.__class__.__name__}),
        )

    resolved_vt_symbol = build_vt_symbol(symbol, exchange)
    missing = []

    try:
        bars = market_client.stock_bars(symbol, exchange, limit=120, interval="1d")
        indicators = compute_bar_indicators(resolved_vt_symbol, bars["items"], source=bars.get("source"))
    except Exception as exc:
        bars = empty_bar_series(symbol, exchange, "1d", exc)
        indicators = empty_indicators(resolved_vt_symbol, exc)
        missing.extend(["bars", "technical_indicators"])

    try:
        business = market_client.stock_business(symbol, exchange)
    except Exception:
        business = empty_business(resolved_vt_symbol)

    try:
        sectors = market_client.stock_sectors(symbol, exchange).get("items", [])
    except Exception:
        sectors = []

    try:
        industry_chain = market_client.stock_industry_chain_from_data(symbol, exchange, business, sectors)
    except AttributeError:
        try:
            industry_chain = market_client.stock_industry_chain(symbol, exchange)
        except Exception:
            industry_chain = empty_industry_chain(resolved_vt_symbol)
    except Exception:
        industry_chain = empty_industry_chain(resolved_vt_symbol)

    if not business.get("summary") and not business.get("business_scope"):
        missing.append("business")
    if not sectors:
        missing.append("sectors")
    if not industry_chain.get("chain_name") and not industry_chain.get("midstream"):
        missing.append("industry_chain")

    return ok(
        {
            "quote": quote,
            "bars": bars["items"],
            "technical_indicators": indicators,
            "business": business,
            "sectors": sectors,
            "industry_chain": industry_chain,
            "data_quality": {
                "missing": missing,
                "sources": [quote.get("source"), bars.get("source"), business.get("source")],
            },
        }
    )


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str | None]:
    if "." in vt_symbol:
        symbol, exchange = vt_symbol.split(".", 1)
        return symbol.strip(), exchange.strip()
    return vt_symbol.strip(), None


def resolve_symbol_exchange(
    market_client: RealMarketDataClient,
    symbol: str,
    exchange: str | None,
) -> tuple[str, str | None]:
    """Use the live AkShare quote row as the source of truth for exchange."""

    try:
        detail = market_client.stock_detail(symbol, exchange)
    except Exception:
        return symbol, exchange
    return str(detail.get("symbol") or symbol), str(detail.get("exchange") or exchange or "")


def empty_bar_series(symbol: str, exchange: str | None, interval: str, exc: Exception) -> dict[str, object]:
    return {
        "symbol": symbol,
        "exchange": exchange,
        "vt_symbol": build_vt_symbol(symbol, exchange),
        "interval": interval,
        "items": [],
        "source": "unavailable",
        "message": f"AkShare 暂未返回该股票的 K 线数据: {exc.__class__.__name__}",
    }


def empty_indicators(vt_symbol: str, exc: Exception) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "status": "pending",
        "source": "unavailable",
        "sample_size": 0,
        "message": f"AkShare K 线样本不可用，暂不能计算技术指标: {exc.__class__.__name__}",
    }


def empty_business(vt_symbol: str, exc: Exception | None = None) -> dict[str, object]:
    reason = f": {exc.__class__.__name__}" if exc else ""
    return {
        "vt_symbol": vt_symbol,
        "summary": None,
        "business_scope": None,
        "main_products": [],
        "segments": [],
        "source": "unavailable",
        "message": f"AkShare 暂未返回该股票的主营业务数据{reason}",
    }


def empty_industry_chain(vt_symbol: str, exc: Exception | None = None) -> dict[str, object]:
    reason = f": {exc.__class__.__name__}" if exc else ""
    return {
        "vt_symbol": vt_symbol,
        "chain_name": None,
        "position": None,
        "upstream": [],
        "midstream": [],
        "downstream": [],
        "exposure": [],
        "sectors": [],
        "evidence": [],
        "status": "unavailable",
        "source": "unavailable",
        "message": f"AkShare 暂未返回足够的产业链线索{reason}",
    }
