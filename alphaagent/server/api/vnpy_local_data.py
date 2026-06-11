"""Local vn.py object adapter endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services.vnpy_integration.local_data import query_local_daily_bars
from alphaagent.server.services.vnpy_integration.database_import import (
    import_vnpy_minute_bars,
    import_vnpy_minute_bars_for_gaps,
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


@router.post("/import-minute-bars/gaps")
def import_gap_minute_bars_from_vnpy(payload: dict = None):
    payload = payload or {}
    try:
        return ok(
            import_vnpy_minute_bars_for_gaps(
                gap_csv_text=str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                gap_file_path=str(payload.get("gap_file_path") or payload.get("file_path") or ""),
                interval=str(payload.get("interval") or "1m"),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
                dry_run=bool(payload.get("dry_run") if payload.get("dry_run") is not None else True),
                max_gaps=int(payload.get("max_gaps") or 2000),
            )
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content=fail("INVALID_VNPY_GAP_IMPORT_REQUEST", str(exc)),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content=fail("VNPY_GAP_IMPORT_UNAVAILABLE", "vn.py 缺口分钟线批量导入暂时不可用。", {"reason": exc.__class__.__name__}),
        )
