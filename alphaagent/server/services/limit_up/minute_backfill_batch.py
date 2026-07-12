"""Background batch boundary for limit-up event minute backfills."""

from __future__ import annotations

from typing import Any

from alphaagent.server.services import data_sync


JOB_ID = "sync_limit_up_event_minutes"
MIN_GAP_BATCH_SIZE = 1
MAX_GAP_BATCH_SIZE = 200


class MinuteBackfillBatchBusyError(RuntimeError):
    """Raised when another global data-sync batch already owns the worker."""

    def __init__(self, batch: dict[str, Any]) -> None:
        super().__init__("another data-sync batch is already running")
        self.batch = batch


class MinuteBackfillBatchNotFoundError(LookupError):
    """Raised when a batch is missing or does not belong to this workflow."""

    def __init__(self, batch_id: str) -> None:
        super().__init__(f"limit-up minute backfill batch not found: {batch_id}")
        self.batch_id = batch_id


def start_minute_backfill_batch(*, max_gaps: int = MAX_GAP_BATCH_SIZE) -> dict[str, Any]:
    """Start the single target job without blocking the HTTP request."""

    _validate_gap_batch_size(max_gaps)
    batch = data_sync.start_sync_batch(
        job_ids=[JOB_ID],
        params={
            "jobs": {
                JOB_ID: {
                    "max_gaps": max_gaps,
                    "dry_run": False,
                }
            }
        },
        concurrency=1,
        source="manual",
    )
    if not _is_minute_backfill_batch(batch):
        raise MinuteBackfillBatchBusyError(batch)
    return batch


def get_minute_backfill_batch(batch_id: str) -> dict[str, Any]:
    """Return only batches owned by the limit-up minute backfill workflow."""

    try:
        batch = data_sync.get_sync_batch(batch_id)
    except data_sync.DataSyncError as exc:
        raise MinuteBackfillBatchNotFoundError(batch_id) from exc
    if not _is_minute_backfill_batch(batch):
        raise MinuteBackfillBatchNotFoundError(batch_id)
    return batch


def _validate_gap_batch_size(max_gaps: int) -> None:
    if not MIN_GAP_BATCH_SIZE <= max_gaps <= MAX_GAP_BATCH_SIZE:
        raise ValueError(
            f"max_gaps must be between {MIN_GAP_BATCH_SIZE} and {MAX_GAP_BATCH_SIZE}"
        )


def _is_minute_backfill_batch(batch: dict[str, Any]) -> bool:
    jobs = batch.get("jobs")
    if not isinstance(jobs, list):
        return False
    return any(
        isinstance(job, dict) and job.get("job_id") == JOB_ID
        for job in jobs
    )
