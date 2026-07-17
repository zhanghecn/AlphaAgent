"""Local vn.py object adapter endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.vnpy_integration.local_data import query_local_daily_bars
from alphaagent.server.services.vnpy_integration.database_import import (
    import_vnpy_minute_bars,
)

router = APIRouter(prefix="/vnpy", tags=["vnpy"])


@router.get("/local-bars")
def get_local_bars(
    vt_symbol: str = Query(...),
    start: date = Query(...),
    end: date | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=5000),
):
    try:
        return ok(query_local_daily_bars(vt_symbol, start, end, limit=limit))
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_VT_SYMBOL", str(exc)),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("VNPY_LOCAL_DATA_UNAVAILABLE", "vn.py 本地数据适配暂时不可用。", {"reason": exc.__class__.__name__}),
        )

@router.post("/import-minute-bars")
def import_minute_bars_from_vnpy(payload: dict = None):
    payload = payload or {}
    try:
        return ok(
            import_vnpy_minute_bars(
                str(payload.get("vt_symbol") or ""),
                payload.get("start"),
                payload.get("end"),
                interval=str(payload.get("interval") or "1m"),
                dry_run=bool(payload.get("dry_run") or False),
            )
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_VNPY_IMPORT_REQUEST", str(exc)),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("VNPY_DATABASE_IMPORT_UNAVAILABLE", "vn.py 数据库分钟线导入暂时不可用。", {"reason": exc.__class__.__name__}),
        )
