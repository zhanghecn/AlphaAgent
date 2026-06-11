"""Data sync management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, Response

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services import data_sync as service
from alphaagent.server.services.data_providers.tdx_minute_import import import_tdx_minute_bars_for_gaps
from alphaagent.server.services.data_providers.tushare_minute_import import import_tushare_minute_bars_for_gaps

router = APIRouter(prefix="/data-sync", tags=["data-sync"])


@router.get("/sources")
def sources():
    try:
        return ok(service.list_sources())
    except Exception as exc:
        return _sync_error(exc)


@router.get("/jobs")
def jobs():
    try:
        return ok(service.list_jobs())
    except Exception as exc:
        return _sync_error(exc)


@router.post("/jobs/{job_id}/run")
def run_job(job_id: str, params: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(service.run_job(job_id, params))
    except Exception as exc:
        return _sync_error(exc)


@router.post("/jobs/{job_id}/schedule")
def schedule_job(job_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(service.update_job_schedule(job_id, payload.get("schedule_cron")))
    except Exception as exc:
        return _sync_error(exc)


@router.get("/runs")
def runs(limit: int = Query(default=20, ge=1, le=100)):
    try:
        return ok(service.list_runs(limit=limit))
    except Exception as exc:
        return _sync_error(exc)


@router.get("/coverage")
def coverage():
    try:
        return ok(service.coverage())
    except Exception as exc:
        return _sync_error(exc)


@router.get("/usage")
def usage():
    try:
        return ok(service.usage())
    except Exception as exc:
        return _sync_error(exc)


@router.get("/imports/minute-bars/template.csv")
def minute_bars_template():
    try:
        return Response(
            content=service.minute_csv_template(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="alphaagent_minute_bars_template.csv"'},
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars")
def import_minute_bars(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        csv_text = str(payload.get("csv_text") or "")
        file_path = str(payload.get("file_path") or "").strip()
        if file_path:
            return ok(
                service.import_stock_minute_bars_file(
                    file_path,
                    interval=str(payload.get("interval") or "1m"),
                    source=str(payload.get("source") or "manual_csv_file"),
                    dry_run=bool(payload.get("dry_run") or False),
                )
            )
        return ok(
            service.import_stock_minute_bars_csv(
                csv_text,
                interval=str(payload.get("interval") or "1m"),
                source=str(payload.get("source") or "manual_csv"),
                dry_run=bool(payload.get("dry_run") or False),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/audit-gaps")
def audit_minute_bar_gaps(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        file_path = str(payload.get("file_path") or "").strip()
        if file_path:
            return ok(
                service.audit_minute_gap_file(
                    file_path,
                    interval=str(payload.get("interval") or "1m"),
                    tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                    tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
                    min_tail_bars=int(payload.get("min_tail_bars") or 1),
                )
            )
        return ok(
            service.audit_minute_gap_csv(
                str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                interval=str(payload.get("interval") or "1m"),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
                min_tail_bars=int(payload.get("min_tail_bars") or 1),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/gap-template.csv")
def minute_gap_import_template(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return Response(
            content=service.minute_gap_import_template(
                str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                sample_limit=int(payload.get("sample_limit") or 200),
            ),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="alphaagent_minute_gap_import_template.csv"'},
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/vendor-manifest")
def minute_gap_vendor_manifest(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            service.minute_gap_vendor_manifest(
                str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                file_path=str(payload.get("file_path") or payload.get("gap_file_path") or ""),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
                sample_limit=int(payload.get("sample_limit") or 20),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/vendor-manifest.csv")
def minute_gap_vendor_manifest_csv(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return Response(
            content=service.minute_gap_vendor_manifest_csv(
                str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                file_path=str(payload.get("file_path") or payload.get("gap_file_path") or ""),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
            ),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="alphaagent_minute_gap_vendor_manifest.csv"'},
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/tushare-gaps")
def import_minute_bar_gaps_from_tushare(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            import_tushare_minute_bars_for_gaps(
                gap_csv_text=str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                gap_file_path=str(payload.get("gap_file_path") or payload.get("file_path") or ""),
                interval=str(payload.get("interval") or "1m"),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
                dry_run=bool(payload.get("dry_run") if payload.get("dry_run") is not None else True),
                max_gaps=int(payload.get("max_gaps") or 200),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/tdx-gaps")
def import_minute_bar_gaps_from_tdx(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(
            import_tdx_minute_bars_for_gaps(
                gap_csv_text=str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                gap_file_path=str(payload.get("gap_file_path") or payload.get("file_path") or ""),
                interval=str(payload.get("interval") or "1m"),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:57"),
                dry_run=bool(payload.get("dry_run") if payload.get("dry_run") is not None else True),
                max_gaps=int(payload.get("max_gaps") or 2000),
                max_pages_per_symbol=int(payload.get("max_pages_per_symbol") or 32),
                timeout_seconds=float(payload.get("timeout_seconds") or 3),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


def _sync_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail(
            "DATA_SYNC_UNAVAILABLE",
            "本地数据同步模块暂时不可用，请检查 DATABASE_URL 和 PostgreSQL 连接。",
            {"reason": exc.__class__.__name__},
        ),
    )
