"""vn.py integration readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.vnpy_integration.status import vnpy_status

router = APIRouter(prefix="/vnpy", tags=["vnpy"])


@router.get("/status")
def get_vnpy_status():
    try:
        return ok(vnpy_status())
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("VNPY_STATUS_UNAVAILABLE", "vn.py 集成状态暂时不可用。", {"reason": exc.__class__.__name__}),
        )
