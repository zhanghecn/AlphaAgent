"""Portfolio group endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.portfolio import groups

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("/groups")
def list_groups():
    try:
        return ok(groups.list_groups())
    except Exception as exc:
        return _service_error(exc)


@router.post("/groups")
def create_group(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(groups.create_group(payload))
    except Exception as exc:
        return _service_error(exc)


@router.patch("/groups/{group_id}")
def update_group(group_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(groups.update_group(group_id, payload))
    except Exception as exc:
        return _service_error(exc)


@router.delete("/groups/{group_id}")
def delete_group(group_id: int):
    try:
        return ok(groups.delete_group(group_id))
    except Exception as exc:
        return _service_error(exc)


@router.get("/groups/{group_id}/items")
def list_items(group_id: int):
    try:
        return ok(groups.list_items(group_id))
    except Exception as exc:
        return _service_error(exc)


@router.post("/groups/{group_id}/items")
def add_item(group_id: int, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(groups.add_item(group_id, payload))
    except Exception as exc:
        return _service_error(exc)


@router.delete("/groups/{group_id}/items/{vt_symbol}")
def delete_item(group_id: int, vt_symbol: str):
    try:
        return ok(groups.delete_item(group_id, vt_symbol))
    except Exception as exc:
        return _service_error(exc)


@router.get("/holdings")
def holdings():
    try:
        return ok(groups.holdings())
    except Exception as exc:
        return _service_error(exc)


def _service_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail("PORTFOLIO_SERVICE_UNAVAILABLE", "持仓分组服务暂时不可用。", {"reason": exc.__class__.__name__}),
    )
