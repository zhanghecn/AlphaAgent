"""Background batch boundary for Tonghuashun historical event evidence."""

from __future__ import annotations

from typing import Any

from alphaagent.server.services import data_sync
from alphaagent.server.services.limit_up.historical_evidence_import import (
    THS_HISTORY_TRADING_DAYS,
)


JOB_ID = data_sync.LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID
MIN_DATE_BATCH_SIZE = 1
MAX_DATE_BATCH_SIZE = THS_HISTORY_TRADING_DAYS


class ThsEvidenceBatchBusyError(RuntimeError):
    """Raised when another global data-sync batch owns the worker."""

    def __init__(self, batch: dict[str, Any]) -> None:
        super().__init__("another data-sync batch is already running")
        self.batch = batch


class ThsEvidenceBatchNotFoundError(LookupError):
    """Raised when a batch is missing or belongs to another workflow."""

    def __init__(self, batch_id: str) -> None:
        super().__init__(f"Tonghuashun evidence batch not found: {batch_id}")
        self.batch_id = batch_id


def start_ths_evidence_batch(
    *,
    max_dates: int = MAX_DATE_BATCH_SIZE,
    only_missing: bool = True,
) -> dict[str, Any]:
    """Start the one-job evidence import without blocking the HTTP request."""

    _validate_date_batch_size(max_dates)
    batch = data_sync.start_sync_batch(
        job_ids=[JOB_ID],
        params={
            "jobs": {
                JOB_ID: {
                    "max_dates": max_dates,
                    "only_missing": bool(only_missing),
                }
            }
        },
        concurrency=1,
        source="manual",
    )
    if not _is_ths_evidence_batch(batch):
        raise ThsEvidenceBatchBusyError(batch)
    return batch


def get_ths_evidence_batch(batch_id: str) -> dict[str, Any]:
    """Return only batches owned by this import workflow."""

    try:
        batch = data_sync.get_sync_batch(batch_id)
    except data_sync.DataSyncError as exc:
        raise ThsEvidenceBatchNotFoundError(batch_id) from exc
    if not _is_ths_evidence_batch(batch):
        raise ThsEvidenceBatchNotFoundError(batch_id)
    return batch


def _validate_date_batch_size(max_dates: int) -> None:
    if not MIN_DATE_BATCH_SIZE <= max_dates <= MAX_DATE_BATCH_SIZE:
        raise ValueError(
            f"max_dates must be between {MIN_DATE_BATCH_SIZE} and {MAX_DATE_BATCH_SIZE}"
        )


def _is_ths_evidence_batch(batch: dict[str, Any]) -> bool:
    jobs = batch.get("jobs")
    if not isinstance(jobs, list):
        return False
    return any(
        isinstance(job, dict) and job.get("job_id") == JOB_ID
        for job in jobs
    )
