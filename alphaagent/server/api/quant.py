"""Quant screening endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.quant import screening

router = APIRouter(prefix="/quant", tags=["quant"])


@router.post("/screen-runs")
def create_screen_run(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            screening.screen_stocks(
                _parse_date(payload.get("trade_date")),
                strategy_id=str(payload.get("strategy") or screening.STRATEGY_ID),
                max_symbols=int(payload.get("max_symbols") or 500),
                recommendation_limit=int(payload.get("recommendation_limit") or screening.DEFAULT_RECOMMENDATION_LIMIT),
                min_recommendation_score=float(payload.get("min_recommendation_score") or 60),
                persist=bool(payload.get("persist", True)),
                auto_portfolio=bool(payload.get("auto_portfolio", True)),
            )
        )
    except Exception as exc:
        return _service_error(exc)


@router.get("/screen-runs/{run_id}")
def get_screen_run(run_id: int):
    try:
        return ok(screening.get_run(run_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/signals")
def list_signals(
    trade_date: str = Query(default=""),
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=100, ge=1, le=500),
):
    try:
        return ok(screening.list_signals(_parse_date(trade_date), strategy_id=strategy, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/recommendations")
def list_recommendations(
    trade_date: str = Query(default=""),
    strategy: str = Query(default=screening.STRATEGY_ID),
    limit: int = Query(default=50, ge=1, le=200),
):
    try:
        return ok(screening.list_recommendations(_parse_date(trade_date), strategy_id=strategy, limit=limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/recommendations/{recommendation_id}")
def get_recommendation(recommendation_id: int):
    try:
        return ok(screening.get_recommendation(recommendation_id))
    except Exception as exc:
        return _service_error(exc)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail("QUANT_SERVICE_UNAVAILABLE", "量化筛选服务暂时不可用。", {"reason": exc.__class__.__name__}),
    )
