"""Sector endpoints."""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.market.providers import RealMarketDataClient
from alphaagent.server.api.industry_chains import build_sector_search
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok

router = APIRouter(prefix="/sectors", tags=["sectors"])


def client() -> RealMarketDataClient:
    settings = get_settings()
    return RealMarketDataClient(timeout=settings.market_timeout_seconds)


@router.get("", response_model=None)
def list_sectors(type: str = Query(default="")):
    try:
        return ok(client().list_sectors(type))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "SECTOR_DATA_SOURCE_UNAVAILABLE",
                "真实板块列表暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/search", response_model=None)
def search_sectors(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
):
    try:
        return ok(build_sector_search(client(), q, limit=limit))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "SECTOR_SEARCH_UNAVAILABLE",
                "真实板块搜索暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/{sector_id}", response_model=None)
def sector_detail(sector_id: str):
    try:
        stocks = client().sector_stocks(sector_id, page=1, page_size=20)
        return ok({"sector_id": sector_id, "stocks": stocks["items"], "source": stocks["source"]})
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "SECTOR_DATA_SOURCE_UNAVAILABLE",
                "真实板块详情暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/{sector_id}/stocks", response_model=None)
def sector_stocks(
    sector_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    sort: str = Query(default="changepercent"),
    with_returns: bool = Query(default=False),
    q: str = Query(default=""),
):
    try:
        return ok(client().sector_stocks(sector_id, page=page, page_size=page_size, sort=sort, with_returns=with_returns, q=q))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "SECTOR_DATA_SOURCE_UNAVAILABLE",
                "真实板块成分股暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )


@router.get("/{sector_id}/trend", response_model=None)
def sector_trend(
    sector_id: str,
    page_size: int = Query(default=100, ge=10, le=100),
    pages: int = Query(default=3, ge=1, le=5),
):
    try:
        return ok(client().sector_trend(sector_id, page_size=page_size, pages=pages))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail(
                "SECTOR_TREND_SOURCE_UNAVAILABLE",
                "真实板块趋势暂时不可用。",
                {"reason": exc.__class__.__name__},
            ),
        )
