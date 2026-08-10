"""Contract tests for the controlled front-adjusted daily-bar sync job."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from alphaagent.server.db import schema
from alphaagent.server.services import data_sync as svc
from alphaagent.server.services.data_providers import adjusted_daily_import


ADJUSTED_JOB_ID = "sync_low_suction_adjusted_daily_bars"


def test_adjusted_daily_sync_has_producer_provenance_columns() -> None:
    bars = schema.low_suction_adjusted_daily_bars
    scopes = schema.low_suction_adjusted_daily_bar_scopes

    assert "sync_run_id" in bars.c
    assert "sync_run_id" in scopes.c


def test_adjusted_daily_sync_provenance_records_the_owning_job_and_range() -> None:
    provenance = adjusted_daily_import._provenance(
        318,
        date(2026, 7, 1),
        date(2026, 7, 31),
    )

    assert provenance == {
        "job_id": ADJUSTED_JOB_ID,
        "run_id": 318,
        "requested_range": {"start": "2026-07-01", "end": "2026-07-31"},
    }


def test_adjusted_daily_sync_rejects_a_missing_run_id() -> None:
    with pytest.raises(adjusted_daily_import.AdjustedDailyImportError, match="run id"):
        adjusted_daily_import.sync_adjusted_daily_bars(sync_run_id=0)


def test_adjusted_daily_sync_rejects_an_unbounded_full_backfill() -> None:
    with pytest.raises(
        adjusted_daily_import.AdjustedDailyImportError,
        match="explicit start_date and end_date",
    ):
        adjusted_daily_import.sync_adjusted_daily_bars(
            sync_run_id=1,
            max_symbols=0,
        )


def test_adjusted_daily_sync_is_registered_after_raw_daily_bars() -> None:
    job = next(item for item in svc.DEFAULT_JOBS if item.id == ADJUSTED_JOB_ID)

    assert job.source_id == "akshare"
    assert job.target_table == "low_suction_adjusted_daily_bars"
    assert job.default_params["max_symbols"] == 50
    assert svc.JOB_RUNNERS[job.id] == "_run_sync_low_suction_adjusted_daily_bars"
    assert svc.JOB_CADENCES[job.id].freshness_table == (
        "low_suction_adjusted_daily_bar_scopes"
    )

    for schedule_id in ("eod_1900", "eod_finalize_2130"):
        jobs = next(
            item["job_ids"]
            for item in svc.DEFAULT_BATCH_SCHEDULES
            if item["id"] == schedule_id
        )
        assert jobs.index("sync_stock_daily_bars") < jobs.index(ADJUSTED_JOB_ID)


def test_adjusted_daily_sync_runner_delegates_to_controlled_importer(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_sync_adjusted_daily_bars(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "incomplete", "rows_read": 8, "rows_written": 5}

    monkeypatch.setattr(
        svc,
        "sync_adjusted_daily_bars",
        fake_sync_adjusted_daily_bars,
        raising=False,
    )

    result = svc.DataSyncRunner(adapter=object(), concurrency=2)._run_sync_low_suction_adjusted_daily_bars(
        {
            "_sync_run_id": 917,
            "symbols": "001258.SZSE,600396.SSE",
            "start_date": "2026-07-01",
            "end_date": "2026-07-31",
            "max_symbols": 3,
            "max_workers": 4,
            "retry_attempts": 2,
            "retry_delay_seconds": 0.5,
        }
    )

    assert result["status"] == "incomplete"
    assert captured == {
        "sync_run_id": 917,
        "symbols": ("001258.SZSE", "600396.SSE"),
        "start_date": date(2026, 7, 1),
        "end_date": date(2026, 7, 31),
        "max_symbols": 3,
        "max_workers": 2,
        "retry_attempts": 2,
        "retry_delay_seconds": 0.5,
        "progress": None,
    }


def test_run_job_passes_its_run_id_only_to_adjusted_daily_sync(monkeypatch) -> None:
    captured: dict[str, object] = {}
    finished: list[tuple[object, ...]] = []

    class FakeRunner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def _run_sync_low_suction_adjusted_daily_bars(
            self,
            params: dict[str, object],
        ) -> dict[str, object]:
            captured.update(params)
            return {
                "status": "incomplete",
                "rows_read": 4,
                "rows_written": 4,
                "adjusted_prices": {"scope_count": 1},
            }

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "_create_run", lambda *_args, **_kwargs: 318)
    monkeypatch.setattr(
        svc,
        "_finish_run",
        lambda *args, **kwargs: finished.append((*args, kwargs)),
    )
    monkeypatch.setattr(svc, "DataSyncRunner", FakeRunner)

    result = svc.run_job(ADJUSTED_JOB_ID, {"max_symbols": 7})

    assert result["run_id"] == 318
    assert captured["max_symbols"] == 7
    assert captured["_sync_run_id"] == 318
    assert finished
    # A bounded import may leave the total historical scope incomplete, while
    # still persisting rows that a later qfq run must be able to reuse.  The
    # run itself therefore succeeded; scope completeness remains in result.
    assert result["status"] == "incomplete"
    assert finished[-1][1] == "succeeded"
    assert finished[-1][2]["error_type"] is None


def test_run_job_rejects_an_incomplete_adjusted_sync_without_scope_evidence(
    monkeypatch,
) -> None:
    finished: list[tuple[object, ...]] = []

    class FakeRunner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def _run_sync_low_suction_adjusted_daily_bars(
            self,
            _params: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "incomplete",
                "rows_read": 0,
                "rows_written": 0,
                "adjusted_prices": {"scope_count": 0},
            }

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "_create_run", lambda *_args, **_kwargs: 319)
    monkeypatch.setattr(
        svc,
        "_finish_run",
        lambda *args, **kwargs: finished.append((*args, kwargs)),
    )
    monkeypatch.setattr(svc, "DataSyncRunner", FakeRunner)

    result = svc.run_job(ADJUSTED_JOB_ID, {})

    assert result["status"] == "incomplete"
    assert finished[-1][1] == "failed"
    assert finished[-1][2]["error_type"] == "DataCoverageIncomplete"


def test_run_job_rejects_all_failed_adjusted_targets_despite_scope_evidence(
    monkeypatch,
) -> None:
    finished: list[tuple[object, ...]] = []

    class FakeRunner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def _run_sync_low_suction_adjusted_daily_bars(
            self,
            _params: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "incomplete",
                "rows_read": 0,
                "rows_written": 0,
                "target_count": 50,
                "fetch_failure_count": 50,
                # The importer writes an incomplete all-market scope even when
                # every provider request failed. That must not mark the run
                # successful, because no qfq rows are reusable.
                "adjusted_prices": {"scope_count": 1_627},
            }

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "_create_run", lambda *_args, **_kwargs: 320)
    monkeypatch.setattr(
        svc,
        "_finish_run",
        lambda *args, **kwargs: finished.append((*args, kwargs)),
    )
    monkeypatch.setattr(svc, "DataSyncRunner", FakeRunner)

    result = svc.run_job(ADJUSTED_JOB_ID, {})

    assert result["status"] == "incomplete"
    assert finished[-1][1] == "failed"
    assert finished[-1][2]["error_type"] == "DataCoverageIncomplete"


def test_run_job_accepts_no_missing_adjusted_targets_with_scope_evidence(
    monkeypatch,
) -> None:
    finished: list[tuple[object, ...]] = []

    class FakeRunner:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def _run_sync_low_suction_adjusted_daily_bars(
            self,
            _params: dict[str, object],
        ) -> dict[str, object]:
            return {
                "status": "incomplete",
                "rows_read": 0,
                "rows_written": 0,
                "target_count": 0,
                "fetch_failure_count": 0,
                "adjusted_prices": {"scope_count": 1_627},
            }

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "_create_run", lambda *_args, **_kwargs: 321)
    monkeypatch.setattr(
        svc,
        "_finish_run",
        lambda *args, **kwargs: finished.append((*args, kwargs)),
    )
    monkeypatch.setattr(svc, "DataSyncRunner", FakeRunner)

    result = svc.run_job(ADJUSTED_JOB_ID, {})

    assert result["status"] == "incomplete"
    assert finished[-1][1] == "succeeded"
    assert finished[-1][2]["error_type"] is None


def test_adjusted_daily_import_query_accepts_active_or_successful_producer() -> None:
    source, eligible = adjusted_daily_import._eligible_adjusted_row_source(
        current_sync_run_id=319,
    )
    statement = select(schema.stock_daily_bars.c.vt_symbol).select_from(
        schema.stock_daily_bars.outerjoin(source, eligible)
    )
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))

    assert "sync_job_runs.status = 'succeeded'" in compiled
    assert "sync_job_runs.job_id = 'sync_low_suction_adjusted_daily_bars'" in compiled
    assert "low_suction_adjusted_daily_bars.sync_run_id = 319" in compiled
