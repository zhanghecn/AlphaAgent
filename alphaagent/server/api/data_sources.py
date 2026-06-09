"""Data source integration endpoints."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.server.core.responses import fail, ok

router = APIRouter(prefix="/data-sources", tags=["data-sources"])


def akshare() -> AkShareAdapter:
    return AkShareAdapter()


@router.get("/akshare", response_model=None)
def akshare_info():
    try:
        return ok(akshare().info().to_api())
    except Exception as exc:
        return _akshare_error("AKSHARE_SOURCE_UNAVAILABLE", "AkShare 源码集成不可用。", exc)


@router.get("/akshare/smoke", response_model=None)
def akshare_smoke():
    try:
        return ok(akshare().probe())
    except Exception as exc:
        return _akshare_error("AKSHARE_SMOKE_FAILED", "AkShare 真实数据烟测失败。", exc)


@router.get("/akshare/stocks/spot", response_model=None)
def akshare_a_share_spot(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return ok(akshare().a_share_spot(limit=limit))
    except Exception as exc:
        return _akshare_error("AKSHARE_STOCK_SPOT_UNAVAILABLE", "AkShare A 股实时行情暂时不可用。", exc)


@router.get("/akshare/boards", response_model=None)
def akshare_boards(
    type: str = Query(default="concept"),
    limit: int = Query(default=20, ge=1, le=100),
):
    try:
        return ok(akshare().board_names(type, limit=limit))
    except Exception as exc:
        return _akshare_error("AKSHARE_BOARD_LIST_UNAVAILABLE", "AkShare 板块列表暂时不可用。", exc)


@router.get("/akshare/boards/{board_type}/{symbol}/members", response_model=None)
def akshare_board_members(
    board_type: str,
    symbol: str,
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        return ok(akshare().board_members(board_type, symbol=symbol, limit=limit))
    except Exception as exc:
        return _akshare_error("AKSHARE_BOARD_MEMBERS_UNAVAILABLE", "AkShare 板块成分股暂时不可用。", exc)


@router.get("/akshare/stocks/{symbol}/news", response_model=None)
def akshare_stock_news(
    symbol: str,
    limit: int = Query(default=10, ge=1, le=50),
):
    try:
        return ok(akshare().stock_news(symbol=symbol, limit=limit))
    except Exception as exc:
        return _akshare_error("AKSHARE_STOCK_NEWS_UNAVAILABLE", "AkShare 个股新闻暂时不可用。", exc)


@router.get("/akshare/stocks/{vt_symbol}/business-segments", response_model=None)
def akshare_business_segments(
    vt_symbol: str,
    limit: int = Query(default=30, ge=1, le=100),
):
    symbol, exchange = _parse_vt_symbol(vt_symbol)
    try:
        return ok(akshare().stock_business_segments(symbol=symbol, exchange=exchange, limit=limit))
    except Exception as exc:
        return _akshare_error("AKSHARE_BUSINESS_SEGMENTS_UNAVAILABLE", "AkShare 主营构成暂时不可用。", exc)


def _parse_vt_symbol(vt_symbol: str) -> tuple[str, str | None]:
    if "." in vt_symbol:
        symbol, exchange = vt_symbol.split(".", 1)
        return symbol.strip(), exchange.strip()
    return vt_symbol.strip(), None


def _akshare_error(code: str, message: str, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail(code, message, {"reason": exc.__class__.__name__, "message": str(exc)[:300]}),
    )
