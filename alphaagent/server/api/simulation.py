"""Simulation trading endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.simulation import account

router = APIRouter(prefix="/simulation", tags=["simulation"])


@router.get("/accounts")
def list_accounts():
    try:
        return ok(account.list_accounts())
    except Exception as exc:
        return _service_error(exc)


@router.post("/accounts")
def create_account(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(account.create_account(payload))
    except Exception as exc:
        return _service_error(exc)


@router.post("/auto-buy-recommendations")
def auto_buy_recommendations(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        account_id = payload.get("account_id")
        return ok(account.auto_buy_recommendations(int(account_id) if account_id else None, payload))
    except Exception as exc:
        return _service_error(exc)


@router.get("/accounts/{account_id}/positions")
def list_positions(account_id: int):
    try:
        return ok(account.list_positions(account_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/accounts/{account_id}/orders")
def list_orders(account_id: int, limit: int = Query(default=100, ge=1, le=500)):
    try:
        return ok(account.list_orders(account_id, limit))
    except Exception as exc:
        return _service_error(exc)


@router.post("/accounts/{account_id}/orders")
def place_order(account_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(account.place_order(account_id, payload))
    except Exception as exc:
        return _service_error(exc)


@router.get("/accounts/{account_id}/trades")
def list_trades(account_id: int, limit: int = Query(default=100, ge=1, le=500)):
    try:
        return ok(account.list_trades(account_id, limit))
    except Exception as exc:
        return _service_error(exc)


@router.get("/accounts/{account_id}/risk-events")
def list_risk_events(account_id: int, limit: int = Query(default=100, ge=1, le=500)):
    try:
        return ok(account.list_risk_events(account_id, limit))
    except Exception as exc:
        return _service_error(exc)


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail("SIMULATION_SERVICE_UNAVAILABLE", "模拟交易服务暂时不可用。", {"reason": exc.__class__.__name__}),
    )
