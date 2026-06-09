"""Index endpoints."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.market.indicators import compute_bar_indicators
from alphaagent.market.providers import RealMarketDataClient
from alphaagent.market.symbols import INDEX_SYMBOLS, normalize_exchange
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok

router = APIRouter(prefix="/indices", tags=["indices"])


def client() -> RealMarketDataClient:
    settings = get_settings()
    return RealMarketDataClient(timeout=settings.market_timeout_seconds)


@router.get("", response_model=None)
def list_indices():
    try:
        return ok({"items": [quote.to_api() for quote in client().get_indices()]})
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "指数行情暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}", response_model=None)
def index_detail(vt_symbol: str):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        return ok(client().index_detail(symbol, exchange or normalize_exchange(symbol)))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "指数详情暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}/bars", response_model=None)
def index_bars(
    vt_symbol: str,
    interval: str = Query(default="1d"),
    limit: int = Query(default=120, ge=5, le=3000),
):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        return ok(client().stock_bars(symbol, exchange, limit=limit, interval=interval))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "指数 K 线暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/{vt_symbol}/indicators")
def index_indicators(
    vt_symbol: str,
    interval: str = Query(default="1d"),
    limit: int = Query(default=120, ge=20, le=3000),
):
    symbol, exchange = parse_vt_symbol(vt_symbol)
    try:
        bars = client().stock_bars(symbol, exchange, limit=limit, interval=interval)
        return ok(compute_bar_indicators(vt_symbol, bars["items"], source=bars.get("source")))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "真实指数指标暂时不可用。", {"reason": exc.__class__.__name__}),
        )


def parse_vt_symbol(vt_symbol: str) -> tuple[str, str | None]:
    if vt_symbol == "sh000001":
        return "000001", "SSE"
    if "." in vt_symbol:
        symbol, exchange = vt_symbol.split(".", 1)
        return symbol.strip(), exchange.strip()
    for item in INDEX_SYMBOLS:
        if item["symbol"] == vt_symbol:
            return item["symbol"], item["exchange"]
    return vt_symbol.strip(), None
