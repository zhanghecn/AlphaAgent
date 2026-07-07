"""Data sync management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse, Response

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services import data_sync as service
from alphaagent.server.services.data_providers.akshare_minute_import import import_akshare_minute_bars_for_gaps
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


@router.post("/batches/run-all")
def run_all(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        job_ids = payload.get("job_ids")
        return ok(
            service.start_sync_batch(
                profile=str(payload.get("profile") or "core"),
                job_ids=job_ids if isinstance(job_ids, list) and job_ids else None,
                params=payload.get("params") if isinstance(payload.get("params"), dict) else {},
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.get("/batches/latest")
def latest_batch():
    try:
        return ok(service.get_latest_sync_batch())
    except Exception as exc:
        return _sync_error(exc)


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: str):
    try:
        return ok(service.get_sync_batch(batch_id))
    except Exception as exc:
        return _sync_error(exc)


@router.post("/jobs/{job_id}/schedule")
def schedule_job(job_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(service.update_job_schedule(job_id, payload.get("schedule_cron")))
    except Exception as exc:
        return _sync_error(exc)


@router.get("/schedules")
def list_schedules():
    try:
        return ok(service.list_schedules())
    except Exception as exc:
        return _sync_error(exc)


@router.post("/schedules")
def create_schedule(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(service.create_schedule(payload))
    except Exception as exc:
        return _sync_error(exc)


@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        return ok(service.update_schedule(schedule_id, payload))
    except Exception as exc:
        return _sync_error(exc)


@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str):
    try:
        return ok(service.delete_schedule(schedule_id))
    except Exception as exc:
        return _sync_error(exc)


@router.post("/schedules/{schedule_id}/run")
def run_schedule(schedule_id: str):
    try:
        return ok(service.run_schedule_now(schedule_id))
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


@router.get("/health")
def data_health():
    try:
        return ok(service.data_health())
    except Exception as exc:
        return _sync_error(exc)


@router.get("/tail-workflow")
def tail_workflow():
    try:
        return ok(service.tail_workflow_status())
    except Exception as exc:
        return _sync_error(exc)


@router.post("/tail-workflow/run-tail-quant")
def run_tail_quant():
    try:
        return ok(service.run_tail_quant_now())
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
        if payload.get("backtest_id") not in (None, ""):
            requirements = service.minute_gap_requirements_from_params(payload)
            return ok(
                service._audit_minute_gap_requirements(
                    requirements,
                    interval="1m",
                    tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                    tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                    min_tail_bars=int(payload.get("min_tail_bars") or 1),
                )
            )
        file_path = str(payload.get("file_path") or "").strip()
        if file_path:
            return ok(
                service.audit_minute_gap_file(
                    file_path,
                    interval="1m",
                    tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                    tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                    min_tail_bars=int(payload.get("min_tail_bars") or 1),
                )
            )
        return ok(
            service.audit_minute_gap_csv(
                str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                interval="1m",
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                min_tail_bars=int(payload.get("min_tail_bars") or 1),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/gap-template.csv")
def minute_gap_import_template(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        if payload.get("backtest_id") not in (None, ""):
            requirements = service.minute_gap_requirements_from_params(payload)
            gap_csv_text = _requirements_to_gap_csv(requirements)
        else:
            gap_csv_text = str(payload.get("gap_csv_text") or payload.get("csv_text") or "")
        return Response(
            content=service.minute_gap_import_template(
                gap_csv_text,
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
        if payload.get("backtest_id") not in (None, ""):
            requirements = service.minute_gap_requirements_from_params(payload)
            return ok(
                service.minute_gap_vendor_manifest(
                    _requirements_to_gap_csv(requirements),
                    tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                    tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                    sample_limit=int(payload.get("sample_limit") or 20),
                )
            )
        return ok(
            service.minute_gap_vendor_manifest(
                str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
                file_path=str(payload.get("file_path") or payload.get("gap_file_path") or ""),
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                sample_limit=int(payload.get("sample_limit") or 20),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/vendor-manifest.csv")
def minute_gap_vendor_manifest_csv(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        if payload.get("backtest_id") not in (None, ""):
            requirements = service.minute_gap_requirements_from_params(payload)
            gap_csv_text = _requirements_to_gap_csv(requirements)
            gap_file_path = ""
        else:
            gap_csv_text = str(payload.get("gap_csv_text") or payload.get("csv_text") or "")
            gap_file_path = str(payload.get("file_path") or payload.get("gap_file_path") or "")
        return Response(
            content=service.minute_gap_vendor_manifest_csv(
                gap_csv_text,
                file_path=gap_file_path,
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
            ),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="alphaagent_minute_gap_vendor_manifest.csv"'},
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/tushare-gaps")
def import_minute_bar_gaps_from_tushare(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        gap_csv_text, gap_file_path = _gap_payload_source(payload)
        return ok(
            import_tushare_minute_bars_for_gaps(
                gap_csv_text=gap_csv_text,
                gap_file_path=gap_file_path,
                interval="1m",
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                dry_run=bool(payload.get("dry_run") if payload.get("dry_run") is not None else True),
                max_gaps=int(payload.get("max_gaps") or 200),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/tdx-gaps")
def import_minute_bar_gaps_from_tdx(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        gap_csv_text, gap_file_path = _gap_payload_source(payload)
        return ok(
            import_tdx_minute_bars_for_gaps(
                gap_csv_text=gap_csv_text,
                gap_file_path=gap_file_path,
                interval="1m",
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                dry_run=bool(payload.get("dry_run") if payload.get("dry_run") is not None else True),
                max_gaps=int(payload.get("max_gaps") or 2000),
                max_pages_per_symbol=int(payload.get("max_pages_per_symbol") or 32),
                timeout_seconds=float(payload.get("timeout_seconds") or 3),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


@router.post("/imports/minute-bars/akshare-gaps")
def import_minute_bar_gaps_from_akshare(payload: dict[str, Any] = Body(default_factory=dict)):
    try:
        gap_csv_text, gap_file_path = _gap_payload_source(payload)
        return ok(
            import_akshare_minute_bars_for_gaps(
                gap_csv_text=gap_csv_text,
                gap_file_path=gap_file_path,
                interval="1m",
                tail_entry_start=str(payload.get("tail_entry_start") or "14:30"),
                tail_entry_end=str(payload.get("tail_entry_end") or "14:30"),
                dry_run=bool(payload.get("dry_run") if payload.get("dry_run") is not None else True),
                max_gaps=int(payload.get("max_gaps") or 200),
            )
        )
    except Exception as exc:
        return _sync_error(exc)


def _gap_payload_source(payload: dict[str, Any]) -> tuple[str, str]:
    if payload.get("backtest_id") not in (None, ""):
        requirements = service.minute_gap_requirements_from_params(payload)
        return _requirements_to_gap_csv(requirements), ""
    return (
        str(payload.get("gap_csv_text") or payload.get("csv_text") or ""),
        str(payload.get("gap_file_path") or payload.get("file_path") or ""),
    )


def _requirements_to_gap_csv(requirements: dict[str, Any]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["trade_date", "vt_symbol", "reference_date", "window", "ma5"])
    for item in requirements.get("items") or []:
        trade_date = item.get("trade_date")
        reference_date = item.get("reference_date")
        writer.writerow(
            [
                trade_date.isoformat() if hasattr(trade_date, "isoformat") else trade_date,
                item.get("vt_symbol") or "",
                reference_date.isoformat() if hasattr(reference_date, "isoformat") else (reference_date or ""),
                item.get("window") or "",
                item.get("ma5") if item.get("ma5") is not None else "",
            ]
        )
    return buffer.getvalue()


def _sync_error(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content=fail(
            "DATA_SYNC_UNAVAILABLE",
            "本地数据同步模块暂时不可用，请检查 DATABASE_URL 和 PostgreSQL 连接。",
            {"reason": exc.__class__.__name__},
        ),
    )
