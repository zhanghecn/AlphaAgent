"""Data sync management endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

from alphaagent.server.core.responses import fail, ok
from alphaagent.server.services import data_sync as service

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
def coverage(force: bool = Query(default=False)):
    try:
        return ok(service.coverage(force_refresh=force))
    except Exception as exc:
        return _sync_error(exc)


@router.get("/usage")
def usage():
    try:
        return ok(service.usage())
    except Exception as exc:
        return _sync_error(exc)


@router.get("/health")
def data_health(force: bool = Query(default=False)):
    try:
        return ok(service.data_health(force_refresh=force))
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
