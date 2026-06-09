"""Market overview and live data endpoints."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.data_sources.akshare_adapter import AkShareAdapter
from alphaagent.market.providers import RealMarketDataClient
from alphaagent.server.core.config import get_settings
from alphaagent.server.core.responses import fail, ok

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview", response_model=None)
def market_overview():
    settings = get_settings()
    try:
        return ok(RealMarketDataClient(timeout=settings.market_timeout_seconds).market_overview())
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("MARKET_DATA_SOURCE_UNAVAILABLE", "市场概览暂时不可用。", {"reason": exc.__class__.__name__}),
        )


@router.get("/fund-flow")
def market_fund_flow(
    sector_type: str = Query("concept", description="concept|industry"),
    top_n: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Return sector-level fund flow ranking from live AkShare."""
    adapter = AkShareAdapter()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        data = adapter.sector_fund_flows(sector_type, period="即时")
        items = data.get("items") or []
        # Enrich and limit
        enriched: list[dict[str, Any]] = []
        for row in items:
            name = str(row.get("名称") or row.get("name") or "")
            code = str(row.get("代码") or row.get("code") or "")
            net = row.get("主力净流入-净额") or row.get("main_net_inflow")
            net_ratio = row.get("主力净流入-净占比") or row.get("main_net_inflow_ratio")
            change_pct = row.get("涨跌幅") or row.get("change_pct")
            enriched.append({
                "code": code,
                "name": name,
                "change_pct": change_pct,
                "main_net_inflow": net,
                "main_net_inflow_ratio": net_ratio,
                "super_large_net_inflow": row.get("超级大户净流入-净额") or row.get("super_large_net_inflow"),
                "large_net_inflow": row.get("大户净流入-净额") or row.get("large_net_inflow"),
                "medium_net_inflow": row.get("中户净流入-净额") or row.get("medium_net_inflow"),
                "small_net_inflow": row.get("散户净流入-净额") or row.get("small_net_inflow"),
            })
        # Sort by |main_net_inflow| desc
        enriched.sort(key=lambda x: -(abs(x.get("main_net_inflow") or 0)))
        return {
            "items": enriched[:top_n],
            "total": len(enriched),
            "sector_type": sector_type,
            "status": "ready",
            "updated_at": now_iso,
        }
    except Exception as exc:
        return {
            "items": [],
            "total": 0,
            "sector_type": sector_type,
            "status": "unavailable",
            "message": str(exc),
            "updated_at": now_iso,
        }


@router.get("/hot-ranks")
def market_hot_ranks(
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Return stock hot rank (东方财富人气榜) from live AkShare."""
    adapter = AkShareAdapter()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        data = adapter.stock_hot_ranks(limit=limit)
        items = data.get("items") or []
        return {
            "items": items[:limit],
            "total": len(items),
            "status": "ready",
            "updated_at": now_iso,
        }
    except Exception as exc:
        return {
            "items": [],
            "total": 0,
            "status": "unavailable",
            "message": str(exc),
            "updated_at": now_iso,
        }


@router.get("/limit-pools")
def market_limit_pools(
    trade_date: str | None = Query(None, description="YYYYMMDD, defaults to today"),
) -> dict[str, Any]:
    """Return limit-up/down/strong pools from live AkShare."""
    adapter = AkShareAdapter()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        data = adapter.limit_up_pools(trade_date=trade_date)
        return {
            **data,
            "status": "ready",
            "updated_at": now_iso,
        }
    except Exception as exc:
        return {
            "trade_date": trade_date or date.today().strftime("%Y%m%d"),
            "pools": {},
            "status": "unavailable",
            "message": str(exc),
            "updated_at": now_iso,
        }
