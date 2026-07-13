"""Tests for the unified incremental batch-sync scheduler.

Covers the ``sync_batch_schedules`` table, default schedules, batch execution
(failure isolation / concurrency), incremental bar sync, and the
schedule-driven scheduler. Implementation plan:
requirements/alphaagent_unified_schedule_execution_plan.md
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any

import pytest

from alphaagent.server.db import schema
from alphaagent.server.services import data_sync as svc


def test_sync_batch_schedules_table_defined():
    """Task 1: a sync_batch_schedules table exists with the required columns."""
    table = schema.sync_batch_schedules
    assert table.name == "sync_batch_schedules"
    cols = {c.name for c in table.columns}
    assert {"id", "name", "cron", "job_ids", "enabled", "concurrency"}.issubset(cols)
    assert {"last_status", "last_started_at", "last_finished_at"}.issubset(cols)


def test_schema_patches_continue_when_one_patch_hits_lock_timeout():
    executed: list[str] = []

    class FakeConnection:
        def exec_driver_sql(self, sql: str):
            executed.append(sql)
            if sql.startswith("ALTER TABLE stocks"):
                raise TimeoutError("lock timeout")

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    schema._apply_compatible_schema_patches(FakeEngine())

    assert any(sql.startswith("ALTER TABLE stocks") for sql in executed)
    assert any("sync_batch_schedules" in sql for sql in executed)
    assert any("quant_tail_preview_cache" in sql for sql in executed)


def test_schema_patches_raise_unexpected_errors():
    class FakeConnection:
        def exec_driver_sql(self, sql: str):
            if not sql.startswith("SET LOCAL"):
                raise RuntimeError("syntax failure")

    class FakeBegin:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeEngine:
        def begin(self):
            return FakeBegin()

    try:
        schema._apply_compatible_schema_patches(FakeEngine())
    except RuntimeError as exc:
        assert "syntax failure" in str(exc)
    else:
        raise AssertionError("unexpected schema patch errors must not be swallowed")


# ── Task 2: default schedules + clear single-job crons ───────────────────


def test_default_batch_schedules_defined():
    ids = {s["id"] for s in svc.DEFAULT_BATCH_SCHEDULES}
    assert ids == {
        "auction_0926",
        "limit_up_live_scan",
        "intraday_hourly",
        "tail_quant_1430",
        "limit_up_plan_1505",
        "eod_1900",
        "eod_finalize_2130",
    }


def test_auction_schedule_captures_the_finished_call_auction_before_continuous_trading():
    auction = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "auction_0926")
    job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_stock_auction_snapshots")

    assert auction["action"] == "sync"
    assert auction["cron"] == "26 9 * * 1-5"
    assert auction["job_ids"] == ["sync_stock_auction_snapshots"]
    assert auction["concurrency"] == 1
    assert job.target_table == "stock_auction_snapshots"
    assert svc.JOB_CADENCES[job.id].freshness_table == "stock_auction_snapshots"


def test_stock_sector_rebuild_saves_a_daily_point_in_time_snapshot(monkeypatch):
    captured: list[tuple[date, datetime]] = []
    now = datetime.fromisoformat("2026-07-13T19:08:00+08:00")

    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(svc, "_rebuild_stock_sector_memberships", lambda: 86_701)
    monkeypatch.setattr(
        svc.market_snapshot_repository,
        "save_current_stock_sector_membership_snapshot",
        lambda *, snapshot_date, captured_at: captured.append((snapshot_date, captured_at)) or 86_701,
    )

    result = svc.DataSyncRunner()._run_sync_stock_sector_memberships({})

    assert result["rows_written"] == 86_701
    assert result["snapshot_rows_written"] == 86_701
    assert captured == [(date(2026, 7, 13), now)]


def test_stock_sector_rebuild_keeps_the_previous_index_when_source_is_empty(monkeypatch):
    replaced: list[list[dict[str, Any]]] = []

    monkeypatch.setattr(svc, "_load_stock_sector_membership_items", lambda: [])
    monkeypatch.setattr(
        svc,
        "_replace_stock_sector_memberships",
        lambda items: replaced.append(items) or len(items),
    )

    with pytest.raises(svc.DataSyncError, match="板块成员为空"):
        svc._rebuild_stock_sector_memberships()

    assert replaced == []


def test_sector_fund_flow_sync_passes_the_real_capture_time_to_snapshot_writer(monkeypatch):
    captured: list[datetime] = []
    source_time = "2026-07-13T02:30:42+00:00"

    class FakeAdapter:
        def sector_fund_flows(self, sector_type, period):
            return {
                "items": [{"id": f"{sector_type}-1", "trade_date": "2026-07-13"}],
                "updated_at": source_time,
            }

    def fake_upsert(items, period, sector_type, *, captured_at):
        del items, period, sector_type
        captured.append(captured_at)
        return 1

    monkeypatch.setattr(svc, "_upsert_sector_fund_flows", fake_upsert)

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_sector_fund_flows(
        {"periods": ["即时"]}
    )

    assert result["rows_read"] == 2
    assert result["rows_written"] == 2
    assert captured == [
        datetime(2026, 7, 13, 2, 30, 42, tzinfo=timezone.utc),
        datetime(2026, 7, 13, 2, 30, 42, tzinfo=timezone.utc),
    ]


def test_auction_sync_filters_to_main_board_and_requires_a_current_market_clock(monkeypatch):
    now = datetime.fromisoformat("2026-07-13T09:26:00+08:00")
    saved: list[dict[str, Any]] = []

    class FakeAdapter:
        def stock_detail(self, symbol, exchange):
            del symbol, exchange
            return {"trade_time": "2026-07-13 09:25:05"}

        def list_stocks(self, page, page_size, sort):
            del page_size, sort
            if page > 1:
                return {"items": [], "total": 2}
            return {
                "items": [
                    {"vt_symbol": "600000.SSE", "name": "浦发银行", "open_price": 10.2},
                    {"vt_symbol": "300001.SZSE", "name": "特锐德", "open_price": 20.1},
                ],
                "total": 2,
            }

    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc.market_snapshot_repository,
        "save_stock_auction_snapshots",
        lambda items, *, trade_date, captured_at: saved.extend(items) or len(items),
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_auction_snapshots({})

    assert result["rows_read"] == 2
    assert result["rows_written"] == 1
    assert [row["vt_symbol"] for row in saved] == ["600000.SSE"]


def test_auction_sync_rejects_a_stale_market_date(monkeypatch):
    now = datetime.fromisoformat("2026-07-13T09:26:00+08:00")

    class FakeAdapter:
        def stock_detail(self, symbol, exchange):
            del symbol, exchange
            return {"trade_time": "2026-07-10 15:00:00"}

    monkeypatch.setattr(svc, "_now_china", lambda: now)

    with pytest.raises(svc.DataSyncError, match="行情日期"):
        svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_auction_snapshots({})


def test_auction_sync_rejects_duplicate_pages_that_hide_missing_symbols(monkeypatch):
    now = datetime.fromisoformat("2026-07-13T09:26:00+08:00")

    class FakeAdapter:
        def stock_detail(self, symbol, exchange):
            del symbol, exchange
            return {"trade_time": "2026-07-13 09:25:05"}

        def list_stocks(self, page, page_size, sort):
            del page, page_size, sort
            duplicate = {"vt_symbol": "600000.SSE", "name": "浦发银行"}
            return {"items": [duplicate, duplicate], "total": 2}

    monkeypatch.setattr(svc, "_now_china", lambda: now)

    with pytest.raises(svc.DataSyncError, match="去重后"):
        svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_auction_snapshots({})


def test_seed_default_registry_deletes_disabled_non_default_schedules(monkeypatch):
    default_ids = {s["id"] for s in svc.DEFAULT_BATCH_SCHEDULES}
    rows: dict[str, dict[str, Any]] = {
        "legacy_disabled_slot": {"id": "legacy_disabled_slot", "enabled": False, "last_status": "disabled"},
        "custom_enabled": {"id": "custom_enabled", "enabled": True, "last_status": None},
        "custom_failed_disabled": {
            "id": "custom_failed_disabled",
            "enabled": False,
            "last_status": "failed",
        },
    }

    class FakeResult:
        def __init__(self, row=object()):
            self.row = row

        def first(self):
            return self.row

    class FakeSession:
        def execute(self, statement):
            table = getattr(getattr(statement, "table", None), "name", None)

            if getattr(statement, "is_select", False) and "FROM sync_batch_schedules" in str(statement):
                params = statement.compile().params
                return FakeResult(rows.get(params["id_1"]))

            if table == "sync_batch_schedules" and statement.is_insert:
                params = statement.compile().params
                rows[str(params["id"])] = dict(params)
                return FakeResult()

            if table == "sync_batch_schedules" and statement.is_delete:
                for schedule_id, row in list(rows.items()):
                    if (
                        schedule_id not in default_ids
                        and row.get("enabled") is False
                        and row.get("last_status") == "disabled"
                    ):
                        del rows[schedule_id]
                return FakeResult()

            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    svc.seed_default_registry()

    assert "legacy_disabled_slot" not in rows
    assert default_ids.issubset(rows)
    assert "custom_enabled" in rows
    assert "custom_failed_disabled" in rows


def test_seed_default_registry_clears_stale_partial_summary(monkeypatch):
    current_partial = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_finalize_2130")
    rows: dict[str, dict[str, Any]] = {
        "eod_1900": {
            "id": "eod_1900",
            "job_ids": ["old_job"] * 11,
            "last_status": "partial",
            "last_started_at": datetime(2026, 7, 7, 19, 0),
            "last_finished_at": datetime(2026, 7, 7, 19, 30),
            "last_message": "10 成功 / 1 失败",
        },
        "eod_finalize_2130": {
            "id": "eod_finalize_2130",
            "job_ids": current_partial["job_ids"],
            "last_status": "partial",
            "last_started_at": datetime(2026, 7, 7, 21, 30),
            "last_finished_at": datetime(2026, 7, 7, 21, 40),
            "last_message": "6 成功 / 1 失败",
        },
    }

    class FakeResult:
        def __init__(self, row=object()):
            self.row = row

        def first(self):
            return self.row

    class FakeSession:
        def execute(self, statement):
            table = getattr(getattr(statement, "table", None), "name", None)

            if getattr(statement, "is_select", False) and "FROM sync_batch_schedules" in str(statement):
                params = statement.compile().params
                return FakeResult(rows.get(params["id_1"]))

            if table == "sync_batch_schedules" and statement.is_insert:
                params = statement.compile().params
                rows[str(params["id"])] = dict(params)
                return FakeResult()

            if table == "sync_batch_schedules" and statement.is_update:
                params = statement.compile().params
                schedule_id = str(params["id_1"])
                rows.setdefault(schedule_id, {}).update(
                    {key: value for key, value in params.items() if key != "id_1"}
                )
                return FakeResult()

            if table == "sync_batch_schedules" and statement.is_delete:
                return FakeResult()

            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    svc.seed_default_registry()

    assert rows["eod_1900"]["last_status"] is None
    assert rows["eod_1900"]["last_started_at"] is None
    assert rows["eod_1900"]["last_finished_at"] is None
    assert rows["eod_1900"]["last_message"] is None
    assert rows["eod_finalize_2130"]["last_status"] == "partial"
    assert rows["eod_finalize_2130"]["last_message"] == "6 成功 / 1 失败"


def test_seed_default_registry_deletes_legacy_eod_18h(monkeypatch):
    rows: dict[str, dict[str, Any]] = {
        "eod_18h": {"id": "eod_18h", "enabled": True, "last_status": "succeeded"},
    }

    class FakeResult:
        def __init__(self, row=object()):
            self.row = row

        def first(self):
            return self.row

    class FakeSession:
        def execute(self, statement):
            table = getattr(getattr(statement, "table", None), "name", None)

            if getattr(statement, "is_select", False) and "FROM sync_batch_schedules" in str(statement):
                params = statement.compile().params
                return FakeResult(rows.get(params["id_1"]))

            if table == "sync_batch_schedules" and statement.is_insert:
                params = statement.compile().params
                rows[str(params["id"])] = dict(params)
                return FakeResult()

            if table == "sync_batch_schedules" and statement.is_update:
                params = statement.compile().params
                schedule_id = str(params["id_1"])
                rows.setdefault(schedule_id, {}).update(
                    {key: value for key, value in params.items() if key != "id_1"}
                )
                return FakeResult()

            if table == "sync_batch_schedules" and statement.is_delete:
                rows.pop("eod_18h", None)
                return FakeResult()

            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    svc.seed_default_registry()

    assert "eod_18h" not in rows
    assert "eod_1900" in rows


def test_default_jobs_have_no_cron():
    # After dropping single-job schedules, every DEFAULT_JOBS entry has no cron.
    for job in svc.DEFAULT_JOBS:
        assert job.schedule_cron is None, f"{job.id} still has schedule_cron"


def test_intraday_schedule_contains_intraday_jobs():
    hourly = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "intraday_hourly")
    assert hourly["action"] == "sync"
    assert hourly["cron"] == "30 9,10,11,13,14 * * 1-5"
    assert "sync_sector_fund_flows" in hourly["job_ids"]
    assert "sync_stock_fund_flows" in hourly["job_ids"]
    assert "sync_stock_hot_ranks" in hourly["job_ids"]
    assert "sync_stock_daily_bars" not in hourly["job_ids"]

    intraday = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "tail_quant_1430")
    assert intraday["action"] == "tail_preview"
    assert "sync_stock_minute_bars" in intraday["job_ids"]
    assert "sync_sector_fund_flows" in intraday["job_ids"]
    assert "sync_limit_up_pools" not in intraday["job_ids"]
    # Daily bars are not available at 14:30, so they must NOT be in the realtime tail slot.
    assert "sync_stock_daily_bars" not in intraday["job_ids"]


def test_limit_up_live_scan_is_a_separate_append_only_schedule():
    live_scan = next(
        schedule
        for schedule in svc.DEFAULT_BATCH_SCHEDULES
        if schedule["id"] == "limit_up_live_scan"
    )

    assert live_scan["action"] == "limit_up_live_scan"
    assert live_scan["cron"] == "* 9-14 * * 1-5"
    assert live_scan["job_ids"] == []
    assert "sync_limit_up_pools" not in live_scan["job_ids"]


def test_next_session_plan_has_preliminary_and_final_schedule_paths():
    preliminary = next(
        schedule
        for schedule in svc.DEFAULT_BATCH_SCHEDULES
        if schedule["id"] == "limit_up_plan_1505"
    )
    eod = next(schedule for schedule in svc.DEFAULT_BATCH_SCHEDULES if schedule["id"] == "eod_1900")
    finalize = next(
        schedule
        for schedule in svc.DEFAULT_BATCH_SCHEDULES
        if schedule["id"] == "eod_finalize_2130"
    )

    assert preliminary["cron"] == "5 15 * * 1-5"
    assert preliminary["action"] == "sync"
    assert preliminary["job_ids"] == [svc.LIMIT_UP_NEXT_SESSION_PLAN_PRELIMINARY_BATCH_JOB_ID]
    assert eod["job_ids"][-1] == svc.LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID
    assert finalize["job_ids"][-1] == svc.LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID


def test_next_session_plan_batch_job_uses_persisted_quality_status(monkeypatch):
    monkeypatch.setattr(
        svc,
        "refresh_next_session_plan",
        lambda _phase: {
            "recommendations": {"lanes": {"next_auction": [{"vt_symbol": "600001.SSE"}]}},
            "data_quality": {"status": "ready"},
        },
    )

    result = svc._run_limit_up_next_session_plan_batch_job("final")

    assert result["status"] == "ready"
    assert result["rows_written"] == 1


def test_limit_up_live_scan_window_starts_at_0915():
    tz = timezone.utc

    assert not svc._limit_up_live_scan_window_open(datetime(2026, 7, 13, 9, 14, tzinfo=tz))
    assert svc._limit_up_live_scan_window_open(datetime(2026, 7, 13, 9, 15, tzinfo=tz))


def test_tail_quant_schedule_triggers_quant_research():
    tail_quant = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "tail_quant_1430")
    assert tail_quant["action"] == "tail_preview"
    assert tail_quant["cron"] == "30 14 * * 1-5"
    assert tail_quant["concurrency"] <= 6
    assert "sync_stock_list" not in tail_quant["job_ids"]
    assert "sync_stock_minute_bars" in tail_quant["job_ids"]
    assert "sync_sector_fund_flows" in tail_quant["job_ids"]
    assert "sync_limit_up_pools" not in tail_quant["job_ids"]
    assert "sync_stock_daily_bars" not in tail_quant["job_ids"]


def test_eod_schedule_runs_unified_post_close_chain():
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_1900")
    assert eod["action"] == "sync"
    assert eod["cron"] == "0 19 * * 1-5"
    assert "sync_stock_daily_bars" in eod["job_ids"]
    assert "sync_index_daily_bars" in eod["job_ids"]
    assert "sync_sector_period_scores" in eod["job_ids"]
    assert svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID in eod["job_ids"]
    assert "sync_limit_up_pools" in eod["job_ids"]
    assert "sync_stock_lhb_records" in eod["job_ids"]
    assert "sync_stock_financial_quarterly" in eod["job_ids"]


def test_eod_schedule_runs_formal_quant_before_slow_enrichment():
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_1900")
    jobs = eod["job_ids"]
    assert jobs == [
        "sync_stock_list",
        "sync_sector_fund_flows",
        "sync_stock_daily_bars",
        "sync_index_daily_bars",
        "sync_sector_period_scores",
        svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID,
        "sync_sector_list",
        "sync_sector_members",
        "sync_stock_sector_memberships",
        "sync_limit_up_pools",
        "sync_stock_lhb_records",
        "sync_stock_notices",
        "sync_stock_financial_quarterly",
        "sync_stock_financial_indicators",
        "sync_stock_business_segments_history",
        svc.LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID,
    ]


def test_eod_finalize_schedule_retries_daily_bars_late_without_slow_jobs():
    finalize = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_finalize_2130")
    jobs = finalize["job_ids"]

    assert finalize["action"] == "sync"
    assert finalize["cron"] == "30 21 * * 1-5"
    assert jobs == [
        "sync_stock_daily_bars",
        "sync_index_daily_bars",
        "sync_sector_period_scores",
        svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID,
        "sync_limit_up_event_minutes",
        svc.LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID,
        svc.LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID,
    ]
    assert "sync_stock_financial_quarterly" not in jobs
    assert "sync_stock_lhb_records" not in jobs
    assert "sync_stock_notices" not in jobs


def test_limit_up_event_minute_backfill_job_is_limited_and_registered(monkeypatch):
    job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_limit_up_event_minutes")
    captured: dict[str, object] = {}

    assert job.source_id == "tdx_public_hq"
    assert job.target_table == "stock_minute_bars"
    assert job.default_params == {"max_gaps": 200, "dry_run": False}
    assert svc.JOB_RUNNERS[job.id] == "_run_sync_limit_up_event_minutes"
    assert svc.JOB_CADENCES[job.id].freshness_table == "limit_up_minute_backfill_attempts"

    def fake_backfill(*, max_gaps: int, dry_run: bool):
        captured.update({"max_gaps": max_gaps, "dry_run": dry_run})
        return {
            "status": "ready",
            "rows_read": 12_000,
            "rows_written": 12_000,
            "requested_gap_count": 200,
            "covered_gap_count": 200,
        }

    monkeypatch.setattr(svc, "backfill_limit_up_event_minutes", fake_backfill)

    result = svc.DataSyncRunner(adapter=object())._run_sync_limit_up_event_minutes(job.default_params)

    assert captured == {"max_gaps": 200, "dry_run": False}
    assert result["rows_written"] == 12_000
    assert result["backfill_status"] == "ready"
    assert "status" not in result
    assert "覆盖 200 / 200" in result["message"]


def test_limit_up_event_minute_backfill_job_fails_when_provider_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        svc,
        "backfill_limit_up_event_minutes",
        lambda **_kwargs: {
            "status": "unavailable",
            "rows_read": 0,
            "rows_written": 0,
            "message": "TDX public quote server unavailable",
        },
    )

    with pytest.raises(svc.DataSyncError, match="TDX public quote server unavailable"):
        svc.DataSyncRunner(adapter=object())._run_sync_limit_up_event_minutes({"max_gaps": 50})


def test_sector_mainline_jobs_default_to_full_sector_coverage():
    bars_job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_sector_daily_bars")
    scores_job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_sector_period_scores")

    assert bars_job.default_params["sector_limit"] == 0
    assert scores_job.default_params["sector_limit"] == 0


def test_stock_list_sync_uses_total_not_legacy_40_page_cap(monkeypatch):
    seen_pages: list[int] = []
    captured_items: list[dict[str, Any]] = []

    class FakeAdapter:
        def list_stocks(self, page=1, page_size=200, sort="mktcap"):
            seen_pages.append(page)
            total = 4100
            start = (page - 1) * 100
            if start >= total:
                return {"items": [], "total": total}
            count = min(100, total - start)
            items = [
                {"symbol": f"{start + i:06d}", "exchange": "SSE", "name": f"S{start + i}"}
                for i in range(count)
            ]
            return {"items": items, "total": total}

    def fake_upsert(items):
        captured_items.extend(items)
        return len(items)

    monkeypatch.setattr(svc, "_upsert_stocks", fake_upsert)

    result = svc.DataSyncRunner(adapter=FakeAdapter())._run_sync_stock_list({"page_size": 200})

    assert result == {"rows_read": 4100, "rows_written": 4100}
    assert max(seen_pages) == 41
    assert len(captured_items) == 4100


def test_sector_period_scores_default_to_latest_complete_daily_date(monkeypatch):
    captured: dict[str, Any] = {}

    monkeypatch.setattr(svc, "_latest_complete_daily_date_for_research", lambda: date(2026, 6, 26))

    def fake_compute_and_persist(*, as_of_date, periods, sector_limit):
        captured["as_of_date"] = as_of_date
        captured["periods"] = periods
        captured["sector_limit"] = sector_limit
        return {"sectors_scored": 2, "rows_written": 2, "as_of_date": as_of_date.isoformat()}

    monkeypatch.setattr(svc.research_sector_scores, "compute_and_persist", fake_compute_and_persist)

    result = svc.DataSyncRunner(adapter=object())._run_sync_sector_period_scores({})

    assert captured == {"as_of_date": date(2026, 6, 26), "periods": ["20d"], "sector_limit": 0}
    assert result["message"] == "as_of_date=2026-06-26"


def test_compute_sector_period_scores_defaults_to_latest_complete_daily_date(monkeypatch):
    from alphaagent.server.services import research_sector_scores as scores

    captured: dict[str, Any] = {}

    monkeypatch.setattr(scores, "is_database_configured", lambda: True)
    monkeypatch.setattr(scores, "_default_score_as_of_date", lambda: date(2026, 6, 26))

    def fake_collect_score_input(sector_id, sector_type, as_of_date, trading_days, latest_complete_date=None):
        del trading_days
        captured["latest_complete_date"] = latest_complete_date
        captured["as_of_date"] = as_of_date
        return scores.SectorScoreInput(
            sector_id=sector_id,
            sector_type=sector_type,
            period="",
            as_of_date=as_of_date,
        )

    monkeypatch.setattr(scores, "_collect_score_input", fake_collect_score_input)

    class FakeRows:
        def mappings(self):
            return self

        def all(self):
            return [{"id": "BK0001", "type": "concept"}]

    class FakeSession:
        def execute(self, stmt):
            del stmt
            return FakeRows()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(scores, "session_scope", fake_session_scope)

    results = scores.compute_sector_period_scores(periods=["20d"], sector_limit=0)

    assert captured["as_of_date"] == date(2026, 6, 26)
    assert captured["latest_complete_date"] == date(2026, 6, 26)
    assert results[0].as_of_date == date(2026, 6, 26)


# ── Startup recovery: interrupted schedules are retried programmatically ──


def test_mark_interrupted_runs_queues_running_schedules(monkeypatch):
    class FakeScalarResult:
        def scalars(self):
            return self

        def all(self):
            return ["tail_quant_1430"]

    class FakeSession:
        def __init__(self):
            self.execute_count = 0

        def execute(self, stmt):
            del stmt
            self.execute_count += 1
            if self.execute_count == 1:
                return FakeScalarResult()
            return None

    fake_session = FakeSession()

    @contextmanager
    def fake_session_scope():
        yield fake_session

    queued: list[str] = []
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_queue_interrupted_schedule_recovery", lambda ids: queued.extend(ids), raising=False)

    assert svc.mark_interrupted_runs() == ["tail_quant_1430"]
    assert queued == ["tail_quant_1430"]


def test_recover_interrupted_schedules_runs_only_still_interrupted(monkeypatch):
    rows = {
        "tail_quant_1430": {
            "id": "tail_quant_1430",
            "cron": "30 14 * * 1-5",
            "enabled": True,
            "action": "tail_preview",
            "job_ids": ["sync_stock_list", "sync_stock_minute_bars"],
            "concurrency": 8,
            "last_status": "failed",
            "last_message": svc.INTERRUPTED_SCHEDULE_MESSAGE,
        },
        "eod_1900": None,
    }
    recovered: list[str] = []

    monkeypatch.setattr(svc, "_load_recoverable_interrupted_schedule", lambda schedule_id: rows.get(schedule_id), raising=False)
    monkeypatch.setattr(svc, "_run_schedule_action", lambda row: recovered.append(row["id"]))

    svc._recover_interrupted_schedules(["tail_quant_1430", "eod_1900"])

    assert recovered == ["tail_quant_1430"]


def test_start_interrupted_schedule_recovery_drains_queue(monkeypatch):
    started: list[tuple[list[str], int]] = []

    class FakeThread:
        def __init__(self, *, target, args, name, daemon):
            started.append((list(args[0]), args[1]))
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon

        def is_alive(self):
            return False

        def start(self):
            return None

    monkeypatch.setattr(svc.threading, "Thread", FakeThread)
    svc._interrupted_recovery_thread = None
    svc._INTERRUPTED_SCHEDULE_RECOVERY_IDS.clear()

    svc._queue_interrupted_schedule_recovery(["eod_1900", "tail_quant_1430"])
    svc.start_interrupted_schedule_recovery(delay_seconds=0)

    assert started == [(["eod_1900", "tail_quant_1430"], 0)]
    assert not svc._INTERRUPTED_SCHEDULE_RECOVERY_IDS
    svc._interrupted_recovery_thread = None


# ── Task 3: start_sync_batch accepts custom job_ids / concurrency / source ─


def test_start_sync_batch_accepts_custom_job_ids(monkeypatch):
    captured = {}

    def fake_run_batch(batch_id, params, *, concurrency=8, source="manual", schedule_id=None):
        captured["concurrency"] = concurrency
        captured["source"] = source
        captured["schedule_id"] = schedule_id
        captured["job_ids"] = params.get("_job_ids")
        # mark finished so the in-memory batch is stable
        b = svc._SYNC_BATCHES[batch_id]
        b["status"] = "succeeded"
        for j in b["jobs"]:
            j["status"] = "succeeded"

    monkeypatch.setattr(svc, "_run_sync_batch", fake_run_batch)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)

    svc.start_sync_batch(
        job_ids=["sync_stock_list", "sync_stock_daily_bars"],
        concurrency=12,
        source="schedule",
        schedule_id="eod_1900",
    )
    assert captured["concurrency"] == 12
    assert captured["source"] == "schedule"
    assert captured["schedule_id"] == "eod_1900"
    assert captured["job_ids"] == ["sync_stock_list", "sync_stock_daily_bars"]


def test_start_sync_batch_explicit_empty_job_ids_does_not_fallback(monkeypatch):
    captured = {}

    def fake_run_batch(batch_id, params, *, concurrency=8, source="manual", schedule_id=None):
        captured["job_ids"] = params.get("_job_ids")
        b = svc._SYNC_BATCHES[batch_id]
        b["status"] = "succeeded"

    monkeypatch.setattr(svc, "_run_sync_batch", fake_run_batch)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)

    result = svc.start_sync_batch(job_ids=[])

    assert result["total_jobs"] == 0
    assert captured["job_ids"] == []


def test_sync_schedule_requires_job_ids():
    try:
        svc._assert_schedule_jobs("sync", [])
    except svc.DataSyncError as exc:
        assert "at least one job_id" in str(exc)
    else:
        raise AssertionError("expected sync schedule without jobs to fail")


def test_sync_schedule_rejects_internal_tail_preview_cache_job():
    try:
        svc._assert_schedule_jobs("sync", [svc.TAIL_PREVIEW_BATCH_JOB_ID])
    except svc.DataSyncError as exc:
        assert svc.TAIL_PREVIEW_BATCH_JOB_ID in str(exc)
    else:
        raise AssertionError("expected sync schedule with internal cache job to fail")


def test_sync_schedule_allows_eod_quant_research_job():
    svc._assert_schedule_jobs("sync", [svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID])


def test_sync_schedule_allows_limit_up_history_rebuild_job():
    svc._assert_schedule_jobs("sync", [svc.LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID])


def test_limit_up_history_rebuild_batch_job_skips_current_ledger(monkeypatch):
    from alphaagent.server.services.limit_up import history_service

    captured: list[date | None] = []
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 7, 10),
    )
    monkeypatch.setattr(
        history_service,
        "refresh_history_if_needed",
        lambda latest: captured.append(latest)
        or {
            "status": "skipped",
            "persisted_days": 600,
            "persisted_end": "2026-07-10",
        },
    )

    result = svc._run_limit_up_history_rebuild_batch_job()

    assert captured == [date(2026, 7, 10)]
    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert "无需重建" in result["message"]


def test_tail_preview_schedule_appends_cache_job(monkeypatch):
    captured = {}

    def fake_start_sync_batch(**kwargs):
        captured.update(kwargs)
        return {"id": "tail_preview_batch"}

    monkeypatch.setattr(svc, "start_sync_batch", fake_start_sync_batch)

    result = svc._start_sync_schedule(
        {
            "id": "tail_quant_1430",
            "action": "tail_preview",
            "job_ids": ["sync_stock_minute_bars"],
            "concurrency": 12,
        },
        source="manual",
    )

    assert result["id"] == "tail_preview_batch"
    assert captured["schedule_id"] == "tail_quant_1430"
    assert captured["job_ids"] == ["sync_stock_minute_bars", svc.TAIL_PREVIEW_BATCH_JOB_ID]


def test_tail_quant_schedule_targets_latest_candidate_minutes(monkeypatch):
    captured = {}

    def fake_start_sync_batch(**kwargs):
        captured.update(kwargs)
        return {"id": "tail_preview_batch"}

    monkeypatch.setattr(svc, "start_sync_batch", fake_start_sync_batch)
    monkeypatch.setattr(
        svc,
        "_latest_quant_candidate_symbols",
        lambda limit=500: ["603955.SSE", "001390.SZSE"],
    )

    svc._start_sync_schedule(
        {
            "id": "tail_quant_1430",
            "action": "tail_preview",
            "job_ids": ["sync_stock_minute_bars"],
            "concurrency": 6,
        },
        source="schedule",
    )

    minute_params = captured["params"]["jobs"]["sync_stock_minute_bars"]
    assert minute_params["symbols"] == ["603955.SSE", "001390.SZSE"]
    assert minute_params["stock_limit"] == 2
    assert minute_params["limit"] == 240
    assert minute_params["incremental"] is True


def test_tail_preview_cache_batch_job_generates_cache(monkeypatch):
    captured = {}

    def fake_generate_tail_preview_cache(trade_date, **kwargs):
        captured["trade_date"] = trade_date
        captured.update(kwargs)
        return {
            "status": "ready",
            "trade_date": "2026-06-18",
            "recommendation_count": 12,
            "total": 80,
        }

    monkeypatch.setattr(svc.screening, "generate_tail_preview_cache", fake_generate_tail_preview_cache)

    result = svc._run_tail_preview_cache_batch_job(
        {
            "jobs": {
                svc.TAIL_PREVIEW_BATCH_JOB_ID: {
                    "trade_date": "2026-06-18",
                    "recommendation_limit": 100,
                }
            }
        },
        schedule_id="tail_quant_1430",
    )

    assert captured["trade_date"].isoformat() == "2026-06-18"
    assert captured["source_schedule_id"] == "tail_quant_1430"
    assert result["rows_read"] == 80
    assert result["rows_written"] == 12


def test_tail_preview_trade_date_requires_intraday_after_complete_daily():
    assert svc._tail_preview_trade_date(date(2026, 6, 18), date(2026, 6, 18)) is None
    assert svc._tail_preview_trade_date(datetime(2026, 6, 19, 14, 30), date(2026, 6, 18)) == date(2026, 6, 19)
    assert svc._tail_preview_trade_date("2026-06-20", "2026-06-18") == date(2026, 6, 20)


def test_tail_preview_cache_requires_intraday_evidence():
    stale_cache = {"payload": {"trade_date": "2026-06-19", "base_daily_date": "2026-06-18"}}
    ready_cache = {"payload": {"trade_date": "2026-06-19", "latest_intraday_date": "2026-06-19"}}
    bar_count_cache = {"payload": {"trade_date": "2026-06-19", "intraday_bar_count": 1}}

    assert svc._tail_preview_cache_has_intraday(stale_cache) is False
    assert svc._tail_preview_cache_has_intraday(ready_cache) is True
    assert svc._tail_preview_cache_has_intraday(bar_count_cache) is True


def test_eod_quant_research_batch_job_waits_for_completion(monkeypatch):
    calls: list[dict[str, Any]] = []
    progress_events: list[dict[str, Any]] = []

    monkeypatch.setattr(svc, "_latest_complete_daily_date_for_research", lambda: svc._parse_date("2026-06-18"))

    def fake_start_research_run(**kwargs):
        calls.append(kwargs)
        return {
            "id": "research_1",
            "status": "running",
            "stage": "screening",
            "message": "正在补齐候选",
            "progress_current": 0,
            "progress_total": 2,
        }

    poll_count = {"n": 0}

    def fake_get_research_run(run_id):
        poll_count["n"] += 1
        return {
            "id": run_id,
            "status": "succeeded",
            "screen_run": {"total": 2497, "recommendation_count": 100},
            "backtest": {"backtest_id": 191},
            "backtest_id": 191,
        }

    monkeypatch.setattr(svc.research_jobs, "start_research_run", fake_start_research_run)
    monkeypatch.setattr(svc.research_jobs, "get_research_run", fake_get_research_run)

    result = svc._run_eod_quant_research_batch_job(
        {"end": "2026-06-18", "candidate_limit": 20},
        progress=lambda patch: progress_events.append(patch),
        poll_interval_seconds=0.01,
    )

    assert calls[0]["start"].isoformat() == "2026-06-18"
    assert calls[0]["end"].isoformat() == "2026-06-18"
    assert calls[0]["candidate_limit"] == 20
    assert "initial_cash" not in calls[0]
    assert "max_positions" not in calls[0]
    assert "max_position_pct" not in calls[0]
    assert poll_count["n"] == 1
    assert result["rows_read"] == 2497
    assert result["rows_written"] == 100
    assert result["backtest_id"] == 191
    assert any(event.get("stage") == "完成" for event in progress_events)


def test_eod_quant_research_batch_job_preserves_explicit_start(monkeypatch):
    calls: list[dict[str, Any]] = []

    monkeypatch.setattr(svc, "_latest_complete_daily_date_for_research", lambda: svc._parse_date("2026-06-18"))

    def fake_start_research_run(**kwargs):
        calls.append(kwargs)
        return {"id": "research_1", "status": "succeeded", "screen_run": {}, "backtest": {}}

    monkeypatch.setattr(svc.research_jobs, "start_research_run", fake_start_research_run)

    svc._run_eod_quant_research_batch_job(
        {"start": "2026-06-01", "end": "2026-06-18"},
        poll_interval_seconds=0.01,
    )

    assert calls[0]["start"].isoformat() == "2026-06-01"
    assert calls[0]["end"].isoformat() == "2026-06-18"


def test_compact_latest_research_run_drops_full_candidate_items():
    run = {
        "id": "research_1",
        "status": "succeeded",
        "stage": "backtest",
        "message": "策略研究完成",
        "screen_run": {
            "status": "ready",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "trade_date": "2026-06-18",
            "run_id": 5766,
            "total_dates": 299,
            "recommendation_count": 100,
            "items": [{"vt_symbol": "603005.SSE", "reason": {"large": "payload"}}],
            "results": [{"trade_date": "2026-06-18"}],
            "replay_run": {"status": "ready", "replay_run_id": 26},
        },
        "backtest": {
            "status": "ready",
            "backtest_id": 194,
            "metrics": {"total_return_pct": 82.98},
            "trades": [{"vt_symbol": "603005.SSE"}],
        },
    }

    compact = svc._compact_latest_research_run(run)

    assert compact["screen_run"]["end_date"] == "2026-06-18"
    assert compact["screen_run"]["recommendation_count"] == 100
    assert compact["replay_run"]["replay_run_id"] == 26
    assert compact["backtest"]["backtest_id"] == 194
    assert compact["backtest"]["metrics"]["total_return_pct"] == 82.98
    assert "items" not in compact["screen_run"]
    assert "results" not in compact["screen_run"]
    assert "trades" not in compact["backtest"]


def test_latest_research_summary_from_db_uses_portfolio_backtest():
    candidate = {
        "id": 5766,
        "status": "succeeded",
        "strategy_id": "mainline_dragon_pullback",
        "strategy_version": "0.1.22",
        "trade_date": svc._parse_date("2026-06-18"),
        "candidate_count": 2502,
        "recommendation_count": 100,
        "message": "ready",
    }
    replay = {
        "id": 26,
        "status": "ready",
        "strategy_id": "mainline_dragon_pullback",
        "strategy_version": "0.1.22",
        "start_date": svc._parse_date("2025-03-26"),
        "end_date": svc._parse_date("2026-06-18"),
        "metrics": {"attempt_count": 121927},
    }
    backtests = [
        {
            "id": 195,
            "status": "succeeded",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.22",
            "start_date": svc._parse_date("2026-06-01"),
            "end_date": svc._parse_date("2026-06-18"),
            "params": {"symbols": ["603005.SSE"]},
            "metrics": {"total_return_pct": 12.3},
        },
        {
            "id": 194,
            "status": "succeeded",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.22",
            "start_date": svc._parse_date("2025-03-26"),
            "end_date": svc._parse_date("2026-06-18"),
            "params": {"symbols": None},
            "metrics": {"total_return_pct": 82.98},
        },
    ]

    summary = svc._latest_research_summary_from_db(candidate, replay, backtests)

    assert summary["status"] == "succeeded"
    assert summary["screen_run"]["trade_date"] == "2026-06-18"
    assert summary["screen_run"]["total"] == 2502
    assert summary["replay_run"]["replay_run_id"] == 26
    assert summary["backtest_id"] == 194
    assert summary["backtest"]["metrics"]["total_return_pct"] == 82.98


# ── Task 4: failure isolation (continue after a job fails, partial state) ─


def test_batch_continues_after_job_failure(monkeypatch):
    import time

    svc._SYNC_BATCHES.clear()
    svc._LATEST_BATCH_ID = None
    calls = []

    def fake_run_job(job_id, params=None, progress=None):
        calls.append(job_id)
        if job_id == "bad":
            raise RuntimeError("boom")
        return {"rows_read": 1, "rows_written": 1}

    monkeypatch.setattr(svc, "run_job", fake_run_job)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)

    result = svc.start_sync_batch(job_ids=["good_a", "bad", "good_b"])

    batch = svc.get_sync_batch(result["id"])
    for _ in range(200):
        if batch["status"] != "running":
            break
        time.sleep(0.01)
        batch = svc.get_sync_batch(result["id"])

    assert batch["status"] == "partial"          # 1 failed, 2 succeeded
    assert batch["failed_jobs"] == 1
    assert batch["succeeded_jobs"] == 2
    assert "good_b" in calls                      # continues after failure


# ── Task 5: per-job inner concurrency (ThreadPoolExecutor) ─


def test_daily_bars_respects_concurrency_limit(monkeypatch):
    import threading
    import time

    seen: list[str] = []
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            with lock:
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
            time.sleep(0.02)
            with lock:
                active["n"] -= 1
                seen.append(symbol)
            return {"items": []}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [
            {"symbol": f"{i:06d}", "exchange": "SSE", "name": "X"} for i in range(10)
        ],
    )
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: 0)

    runner = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=3)
    runner._run_sync_stock_daily_bars({"limit": 5, "incremental": False})

    assert active["peak"] <= 3, f"concurrency exceeded: peak={active['peak']}"
    assert len(seen) == 10


def test_stock_daily_incremental_refreshes_recent_window(monkeypatch):
    captured_start_dates: list[str | None] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            captured_start_dates.append(start_date)
            return {"items": [{"trade_date": "2026-06-26", "close": 11}]}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [{"symbol": "600000", "exchange": "SSE", "name": "A"}],
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vt_symbols: {"600000.SSE": "2026-06-26"})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: len(items))

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_daily_bars(
        {"limit": 250, "incremental": True}
    )

    assert result == {"rows_read": 1, "rows_written": 1}
    assert captured_start_dates == ["2026-06-21"]


def test_stock_daily_incremental_can_disable_refresh_window(monkeypatch):
    captured_start_dates: list[str | None] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            captured_start_dates.append(start_date)
            return {"items": []}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [{"symbol": "600000", "exchange": "SSE", "name": "A"}],
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vt_symbols: {"600000.SSE": "2026-06-26"})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: len(items))

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_daily_bars(
        {"limit": 250, "incremental": True, "refresh_days": 0}
    )

    assert captured_start_dates == ["2026-06-27"]


def test_full_stock_daily_sync_discards_incomplete_latest_cross_section(monkeypatch):
    monkeypatch.setattr(svc.screening, "MIN_COMPLETE_DAILY_SYMBOL_COUNT", 3)
    stock_rows = [{"symbol": f"{i:06d}", "exchange": "SSE", "name": "X"} for i in range(4)]
    cleanup_calls: list[int] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            return {"items": [{"trade_date": "2026-07-07", "close": 10}]}

    monkeypatch.setattr(svc, "_select_daily_bar_stocks", lambda symbols, stock_limit: stock_rows)
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vt_symbols: {})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: len(items))

    def fake_cleanup(total_stocks):
        cleanup_calls.append(total_stocks)
        return {
            "status": "discarded_incomplete",
            "discarded_trade_date": "2026-07-07",
            "discarded_symbol_count": 1446,
            "deleted_rows": 1446,
            "latest_complete_trade_date": "2026-07-06",
            "min_symbol_count": svc._daily_sync_cleanup_min_symbol_count(total_stocks, 0),
        }

    monkeypatch.setattr(svc, "_discard_incomplete_latest_daily_bars", fake_cleanup)

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=8)._run_sync_stock_daily_bars(
        {"limit": 250, "incremental": True, "stock_limit": 0}
    )

    assert cleanup_calls == [4]
    assert result["coverage_cleanup"]["status"] == "discarded_incomplete"
    assert result["coverage_cleanup"]["latest_complete_trade_date"] == "2026-07-06"


def test_daily_sync_complete_threshold_uses_strict_full_market_ratio(monkeypatch):
    monkeypatch.setattr(svc.screening, "MIN_COMPLETE_DAILY_SYMBOL_COUNT", 3000)

    assert svc._daily_sync_complete_min_symbol_count(5539) == int(5539 * 0.95)
    assert svc._daily_sync_complete_min_symbol_count(1000) == 3000
    assert svc._daily_sync_cleanup_min_symbol_count(total_stocks=5800, previous_complete_count=5524) == int(5524 * 0.95)
    assert svc._daily_sync_cleanup_min_symbol_count(total_stocks=5800, previous_complete_count=0) == int(5800 * 0.95)


def test_targeted_stock_daily_sync_does_not_cleanup_latest_cross_section(monkeypatch):
    cleanup_calls: list[int] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            return {"items": [{"trade_date": "2026-07-07", "close": 10}]}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [{"symbol": "600000", "exchange": "SSE", "name": "X"}],
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vt_symbols: {})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: len(items))
    monkeypatch.setattr(svc, "_discard_incomplete_latest_daily_bars", lambda min_count: cleanup_calls.append(min_count))

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_daily_bars(
        {"symbols": "600000.SSE", "limit": 250, "incremental": True}
    )

    assert cleanup_calls == []
    assert "coverage_cleanup" not in result


def test_timed_out_stock_daily_item_does_not_write_late(monkeypatch):
    import time

    writes: list[tuple[str, list[dict[str, Any]]]] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            time.sleep(0.12)
            return {"items": [{"trade_date": "2026-07-07", "close": 10}]}

    monkeypatch.setattr(svc, "SYNC_PER_ITEM_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [{"symbol": "600000", "exchange": "SSE", "name": "X"}],
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vt_symbols: {})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: writes.append((s, items)) or len(items))

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_daily_bars(
        {"limit": 250, "incremental": False}
    )
    time.sleep(0.18)

    assert result["timed_out"] == 1
    assert writes == []


def test_sector_members_syncs_concurrently(monkeypatch):
    """板块成分股应并发拉取(此前纯串行 1484 板块要 ~32min,拖慢盘后批次)。"""
    import threading
    import time

    active = {"n": 0, "peak": 0}
    seen: list[str] = []
    lock = threading.Lock()

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kw):
            with lock:
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
            time.sleep(0.02)
            with lock:
                active["n"] -= 1
                seen.append(sector_id)
            return {"items": [{"symbol": "000001", "exchange": "SSE"}]}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": f"BK{i:04d}", "type": "industry", "name": f"S{i}"} for i in range(12)]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_memberships", lambda sid, items: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=4)._run_sync_sector_members({"page_size": 50})

    assert active["peak"] >= 2, f"应并发执行,peak={active['peak']}"
    assert len(seen) == 12


def test_sector_members_sync_fetches_all_pages_before_prune(monkeypatch):
    calls: list[int] = []
    captured: list[tuple[str, list[dict[str, Any]]]] = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kw):
            calls.append(page)
            if page == 1:
                return {"items": [{"symbol": "000001", "exchange": "SSE"}], "total": 2}
            if page == 2:
                return {"items": [{"symbol": "000002", "exchange": "SZSE"}], "total": 2}
            return {"items": [], "total": 2}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": "BK0001", "type": "industry", "name": "S1"}]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_upsert(sector_id, items):
        captured.append((sector_id, list(items)))
        return len(items)

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_memberships", fake_upsert)

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_sector_members({"page_size": 1})

    assert calls == [1, 2]
    assert result["rows_read"] == 2
    assert [item["symbol"] for _, items in captured for item in items] == ["000001", "000002"]


def test_sector_members_sync_uses_total_when_provider_caps_page_size(monkeypatch):
    calls: list[int] = []
    captured: list[dict[str, Any]] = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=200, **kw):
            del sector_id, page_size, kw
            calls.append(page)
            if page == 1:
                return {
                    "items": [{"symbol": f"{index:06d}", "exchange": "SSE"} for index in range(100)],
                    "total": 127,
                }
            if page == 2:
                return {
                    "items": [{"symbol": f"{100 + index:06d}", "exchange": "SSE"} for index in range(27)],
                    "total": 127,
                }
            return {"items": [], "total": 127}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": "BK1137", "type": "concept", "name": "存储芯片"}]

    class FakeSession:
        def execute(self, stmt):
            del stmt
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def fake_upsert(sector_id, items):
        del sector_id
        captured.extend(items)
        return len(items)

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_memberships", fake_upsert)

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_sector_members({"page_size": 200})

    assert calls == [1, 2]
    assert result["rows_read"] == 127
    assert len(captured) == 127


def test_sector_members_sync_can_fetch_large_boards_beyond_legacy_page_cap(monkeypatch):
    calls: list[int] = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=200, **kw):
            del sector_id, page_size, kw
            calls.append(page)
            total = 2101
            start = (page - 1) * 100
            if start >= total:
                return {"items": [], "total": total}
            count = min(100, total - start)
            return {
                "items": [{"symbol": f"{start + index:06d}", "exchange": "SSE"} for index in range(count)],
                "total": total,
            }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": "BK0596", "type": "concept", "name": "融资融券"}]

    class FakeSession:
        def execute(self, stmt):
            del stmt
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_memberships", lambda sector_id, items: len(items))

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_sector_members({"page_size": 200})

    assert calls == list(range(1, 23))
    assert result["rows_read"] == 2101
    assert result["rows_written"] == 2101


def test_upsert_sector_memberships_prunes_missing_members(monkeypatch):
    executed: list[str] = []

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, stmt):
            if getattr(stmt, "is_delete", False):
                executed.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            else:
                executed.append(str(stmt))
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_sector_memberships(
        "BK0001",
        [
            {"symbol": "000001", "exchange": "SSE", "name": "A"},
            {"symbol": "000002", "exchange": "SZSE", "name": "B"},
        ],
    )

    assert written == 2
    delete_sql = [sql for sql in executed if sql.startswith("DELETE FROM sector_memberships")]
    assert delete_sql
    assert "sector_memberships.sector_id = 'BK0001'" in delete_sql[-1]
    assert "sector_memberships.vt_symbol NOT IN ('000001.SSE', '000002.SZSE')" in delete_sql[-1]


def test_upsert_shenwan_industry_members_prunes_missing_members(monkeypatch):
    executed: list[str] = []

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, stmt):
            if getattr(stmt, "is_delete", False):
                executed.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            else:
                executed.append(str(stmt))
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_shenwan_industry_members(
        "801010",
        [
            {"symbol": "600000", "exchange": "SSE", "name": "A"},
            {"symbol": "000001", "exchange": "SZSE", "name": "B"},
        ],
    )

    assert written == 2
    delete_sql = [sql for sql in executed if sql.startswith("DELETE FROM shenwan_industry_members")]
    assert delete_sql
    assert "shenwan_industry_members.industry_code = '801010'" in delete_sql[-1]
    assert "shenwan_industry_members.vt_symbol NOT IN" in delete_sql[-1]
    assert "'600000.SSE'" in delete_sql[-1]
    assert "'000001.SZSE'" in delete_sql[-1]


def test_sector_daily_bars_syncs_concurrently(monkeypatch):
    """板块历史K线应并发拉取(此前纯串行 1484 板块要 ~28min,拖慢盘后批次)。"""
    import threading
    import time

    active = {"n": 0, "peak": 0}
    seen: list[str] = []
    lock = threading.Lock()

    class FakeAdapter:
        def sector_daily_bars(self, sector_id, board_type=None, limit=250):
            with lock:
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
            time.sleep(0.02)
            with lock:
                active["n"] -= 1
                seen.append(sector_id)
            return {"items": [{"trade_date": "2026-06-23"}], "source": svc.CANONICAL_SECTOR_DAILY_SOURCE}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": f"BK{i:04d}", "type": "industry", "name": f"S{i}"} for i in range(12)]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_daily_bars", lambda *a, **k: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=4)._run_sync_sector_daily_bars({"limit": 250})

    assert active["peak"] >= 2, f"应并发执行,peak={active['peak']}"
    assert len(seen) == 12


def test_limit_up_pool_events_replace_trade_date_pool(monkeypatch):
    executed: list[str] = []
    inserted_params: list[dict[str, Any]] = []

    class FakeScalars:
        def all(self):
            return ["600000.SSE", "000001.SZSE"]

    class FakeKnownResult:
        def scalars(self):
            return FakeScalars()

    class FakeSession:
        def execute(self, stmt):
            if getattr(stmt, "is_insert", False):
                sql = str(stmt)
                inserted_params.append(dict(stmt.compile().params))
            else:
                sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            executed.append(sql)
            if sql.startswith("SELECT stocks.vt_symbol"):
                return FakeKnownResult()
            return object()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_limit_up_events(
        [
            {"vt_symbol": "600000.SSE", "name": "浦发银行", "raw": {"rank": 1}},
            {"vt_symbol": "600000.SSE", "name": "浦发银行", "raw": {"rank": 1}},
            {"vt_symbol": "999999.SSE", "name": "未知", "raw": {}},
        ],
        "zt",
        "20260626",
    )

    assert written == 1
    delete_sql = [sql for sql in executed if sql.startswith("DELETE FROM stock_events")]
    insert_sql = [sql for sql in executed if sql.startswith("INSERT INTO stock_events")]
    assert delete_sql
    assert "stock_events.source = 'akshare.stock_ztb_em'" in delete_sql[0]
    assert "stock_events.event_type = 'limit_pool_zt'" in delete_sql[0]
    assert "'20260626'" in delete_sql[0]
    assert "'2026-06-26'" in delete_sql[0]
    assert len(insert_sql) == 1
    assert inserted_params[0]["vt_symbol"] == "600000.SSE"
    assert inserted_params[0]["event_date"] == "20260626"
    assert inserted_params[0]["event_type"] == "limit_pool_zt"


def test_limit_up_pool_events_preserve_existing_rows_when_provider_returns_empty(monkeypatch):
    executed: list[str] = []

    class FakeSession:
        def execute(self, stmt):
            executed.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            return object()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_limit_up_events([], "zt", "2026-06-26")

    assert written == 0
    delete_sql = [sql for sql in executed if sql.startswith("DELETE FROM stock_events")]
    assert delete_sql == []


def test_upsert_sector_daily_bars_prunes_old_sources_for_sector(monkeypatch):
    executed: list[str] = []

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, stmt):
            if getattr(stmt, "is_delete", False):
                executed.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            else:
                executed.append(str(stmt))
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_sector_daily_bars(
        "BK0459",
        [
            {"trade_date": "2026-06-25", "open": 1, "close": 2, "high": 3, "low": 1},
            {"trade_date": "2026-06-26", "open": 2, "close": 3, "high": 4, "low": 2},
        ],
        svc.CANONICAL_SECTOR_DAILY_SOURCE,
    )

    assert written == 2
    delete_sql = [sql for sql in executed if sql.startswith("DELETE FROM sector_daily_bars")]
    assert delete_sql
    sql = delete_sql[0]
    assert "sector_daily_bars.sector_id = 'BK0459'" in sql
    assert "sector_daily_bars.source != 'eastmoney.board_kline'" in sql


def test_sector_daily_bars_sync_rejects_non_canonical_source(monkeypatch):
    class FakeAdapter:
        def sector_daily_bars(self, sector_id, board_type=None, limit=250):
            return {"items": [{"trade_date": "2026-06-23"}], "source": "akshare.stock_board_industry_index_ths"}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": f"BK{i:04d}", "type": "industry", "name": f"S{i}"} for i in range(3)]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    try:
        svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)._run_sync_sector_daily_bars({"limit": 250})
    except svc.DataSyncError as exc:
        assert "read 0 rows" in str(exc)
        assert "failed=3" in str(exc)
    else:
        raise AssertionError("expected non-canonical sector daily bars source to fail")


def test_sector_daily_bars_sync_fails_when_full_coverage_too_low(monkeypatch):
    class FakeAdapter:
        def sector_daily_bars(self, sector_id, board_type=None, limit=250):
            index = int(str(sector_id).replace("BK", ""))
            if index < 60:
                return {"items": [{"trade_date": "2026-06-23"}], "source": svc.CANONICAL_SECTOR_DAILY_SOURCE}
            return {"items": [], "source": svc.CANONICAL_SECTOR_DAILY_SOURCE}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": f"BK{i:04d}", "type": "industry", "name": f"S{i}"} for i in range(120)]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_daily_bars", lambda *a, **k: 0)

    try:
        svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=4)._run_sync_sector_daily_bars({"limit": 250})
    except svc.DataSyncError as exc:
        assert "coverage too low" in str(exc)
        assert "covered=60/120" in str(exc)
    else:
        raise AssertionError("expected low-coverage sector daily bars sync to fail")


def test_sector_daily_bars_sync_fails_when_source_reads_zero(monkeypatch):
    class FakeAdapter:
        def sector_daily_bars(self, sector_id, board_type=None, limit=250):
            raise RuntimeError("source unavailable")

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": f"BK{i:04d}", "type": "industry", "name": f"S{i}"} for i in range(3)]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    try:
        svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)._run_sync_sector_daily_bars({"limit": 250})
    except svc.DataSyncError as exc:
        assert "read 0 rows" in str(exc)
        assert "failed=3" in str(exc)
    else:
        raise AssertionError("expected zero-read sector daily bars sync to fail")


# ── Task 6: daily bars true incremental (start_date from last bar) ─


def test_daily_increment_uses_start_date_from_last_bar(monkeypatch):
    from alphaagent.market.symbols import vt_symbol as make_vts

    requested: dict[str, Any] = {}

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            requested[symbol] = start_date
            return {"items": []}

    key1 = make_vts("000001", "SSE")
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vts: {key1: "2026-06-10"})
    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [
            {"symbol": "000001", "exchange": "SSE", "name": "X"},
            {"symbol": "000002", "exchange": "SSE", "name": "Y"},
        ],
    )
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda *a, **k: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)._run_sync_stock_daily_bars(
        {"limit": 250, "incremental": True, "refresh_days": 0}
    )

    assert str(requested["000001"]).startswith("2026-06-11")  # last bar 2026-06-10 -> next day
    assert requested["000002"] in (None, "")                  # new stock -> no start_date


def test_index_daily_bars_syncs_core_indexes_incrementally(monkeypatch):
    from alphaagent.market.symbols import vt_symbol as make_vts

    requested: dict[str, Any] = {}
    written: list[tuple[str, str, list[dict[str, Any]]]] = []
    stock_items: list[dict[str, Any]] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            requested[symbol] = {
                "exchange": exchange,
                "limit": limit,
                "interval": interval,
                "start_date": start_date,
            }
            return {
                "items": [
                    {
                        "trade_date": "2026-06-18",
                        "open": 100,
                        "close": 101,
                        "high": 102,
                        "low": 99,
                        "volume": 1_000,
                        "turnover": 10_000,
                    }
                ]
            }

    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda vts: {make_vts("000001", "SSE"): "2026-06-17"})
    monkeypatch.setattr(svc, "_upsert_stocks", lambda items: stock_items.extend(items) or len(items))
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: written.append((s, e, items)) or len(items))

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)._run_sync_index_daily_bars(
        {"limit": 10, "incremental": True, "symbols": ["000001.SSE", "399006.SZSE"]}
    )

    assert result["rows_read"] == 2
    assert result["rows_written"] == 2
    assert requested["000001"]["interval"] == "1d"
    assert requested["000001"]["limit"] == 10
    assert str(requested["000001"]["start_date"]).startswith("2026-06-18")
    assert requested["399006"]["start_date"] in (None, "")
    assert [item[:2] for item in written] == [("000001", "SSE"), ("399006", "SZSE")]
    assert [(item["symbol"], item["exchange"], item["source"]) for item in stock_items] == [
        ("000001", "SSE", "index_benchmark"),
        ("399006", "SZSE", "index_benchmark"),
    ]


def test_minute_bars_respects_concurrency_limit(monkeypatch):
    import threading
    import time

    seen: list[str] = []
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1m", start_date=None, end_date=None):
            with lock:
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
            time.sleep(0.02)
            with lock:
                active["n"] -= 1
                seen.append(symbol)
            return {"items": [], "source": "akshare"}

    monkeypatch.setattr(
        svc,
        "_select_minute_bar_stocks",
        lambda *args, **kwargs: [{"symbol": f"{i:06d}", "exchange": "SSE", "name": "X"} for i in range(10)],
    )
    monkeypatch.setattr(svc, "_upsert_minute_bars", lambda *a, **k: 0)

    runner = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=3)
    runner._run_sync_stock_minute_bars({"mode": "recent", "interval": "1m", "limit": 10, "stock_limit": 10, "incremental": False})

    assert active["peak"] <= 3, f"concurrency exceeded: peak={active['peak']}"
    assert len(seen) == 10


# ── Task 7: minute bars true incremental (per-stock start_date) ─


def test_minute_increment_uses_start_date_from_last_bar(monkeypatch):
    from alphaagent.market.symbols import vt_symbol as make_vts

    requested: dict[str, Any] = {}

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1m", start_date=None, end_date=None):
            requested[symbol] = start_date
            return {"items": [], "source": "akshare"}

    key1 = make_vts("000001", "SSE")
    monkeypatch.setattr(svc, "_last_bar_dates_minute", lambda vts, interval: {key1: "2026-06-10"})
    monkeypatch.setattr(
        svc,
        "_select_minute_bar_stocks",
        lambda *args, **kwargs: [
            {"symbol": "000001", "exchange": "SSE", "name": "X"},
            {"symbol": "000002", "exchange": "SSE", "name": "Y"},
        ],
    )
    monkeypatch.setattr(svc, "_upsert_minute_bars", lambda *a, **k: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)._run_sync_stock_minute_bars(
        {"mode": "recent", "interval": "1m", "limit": 240, "stock_limit": 100, "incremental": True}
    )

    assert str(requested["000001"]).startswith("2026-06-11")
    assert requested["000002"] in (None, "")


def test_minute_increment_uses_live_window_for_current_day(monkeypatch):
    import datetime as dt
    from alphaagent.market.symbols import vt_symbol as make_vts

    requested: dict[str, Any] = {}

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1m", start_date=None, end_date=None):
            requested[symbol] = start_date
            return {"items": [], "source": "akshare"}

    key1 = make_vts("000001", "SSE")
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 7, 7, 14, 30, tzinfo=dt.timezone(dt.timedelta(hours=8))))
    monkeypatch.setattr(svc, "_last_bar_dates_minute", lambda vts, interval: {key1: "2026-07-06"})
    monkeypatch.setattr(
        svc,
        "_select_minute_bar_stocks",
        lambda *args, **kwargs: [{"symbol": "000001", "exchange": "SSE", "name": "X"}],
    )
    monkeypatch.setattr(svc, "_upsert_minute_bars", lambda *a, **k: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_minute_bars(
        {"mode": "recent", "interval": "1m", "limit": 240, "stock_limit": 100, "incremental": True}
    )

    assert requested["000001"] is None


def test_minute_increment_refreshes_live_window_when_today_already_partial(monkeypatch):
    import datetime as dt
    from alphaagent.market.symbols import vt_symbol as make_vts

    requested: dict[str, Any] = {}

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1m", start_date=None, end_date=None):
            requested[symbol] = start_date
            return {"items": [], "source": "akshare"}

    key1 = make_vts("000001", "SSE")
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 7, 7, 14, 30, tzinfo=dt.timezone(dt.timedelta(hours=8))))
    monkeypatch.setattr(svc, "_last_bar_dates_minute", lambda vts, interval: {key1: "2026-07-07"})
    monkeypatch.setattr(
        svc,
        "_select_minute_bar_stocks",
        lambda *args, **kwargs: [{"symbol": "000001", "exchange": "SSE", "name": "X"}],
    )
    monkeypatch.setattr(svc, "_upsert_minute_bars", lambda *a, **k: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_minute_bars(
        {"mode": "recent", "interval": "1m", "limit": 240, "stock_limit": 100, "incremental": True}
    )

    assert requested["000001"] is None


def test_timed_out_stock_minute_item_does_not_write_late(monkeypatch):
    import time

    writes: list[tuple[str, list[dict[str, Any]]]] = []

    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1m", start_date=None, end_date=None):
            time.sleep(0.12)
            return {"items": [{"trade_date": "2026-07-07 14:30:00", "close": 10}], "source": "akshare"}

    monkeypatch.setattr(svc, "SYNC_PER_ITEM_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(
        svc,
        "_select_minute_bar_stocks",
        lambda *args, **kwargs: [{"symbol": "600000", "exchange": "SSE", "name": "X"}],
    )
    monkeypatch.setattr(svc, "_last_bar_dates_minute", lambda vt_symbols, interval: {})
    monkeypatch.setattr(
        svc,
        "_upsert_minute_bars",
        lambda s, e, items, interval, source: writes.append((s, items)) or len(items),
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_minute_bars(
        {"mode": "recent", "interval": "1m", "limit": 240, "stock_limit": 1, "incremental": False}
    )
    time.sleep(0.18)

    assert result["timed_out"] == 1
    assert writes == []


# ── Task 8: scheduler drives batch schedules instead of per-job crons ─


def test_scheduler_triggers_matching_batch_schedule(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "x"})
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [{"id": "eod_1900", "cron": "0 19 * * 1-5", "enabled": True, "action": "sync", "job_ids": ["sync_stock_list"], "concurrency": 8, "last_started_at": None}],
    )
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 17, 19, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert triggered, "expected the matching schedule to trigger a batch"
    assert triggered[0]["job_ids"] == ["sync_stock_list"]
    assert triggered[0]["source"] == "schedule"
    assert triggered[0]["schedule_id"] == "eod_1900"


def test_scheduler_skips_weekend_for_weekday_cron(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "x"})
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [{"id": "eod_1900", "cron": "0 19 * * 1-5", "enabled": True, "action": "sync", "job_ids": ["sync_stock_list"], "concurrency": 8, "last_started_at": None}],
    )
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 20, 19, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert not triggered


def test_scheduler_triggers_tail_preview_schedule(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "tail_preview_batch"})
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [
            {
                "id": "tail_quant_1430",
                "cron": "30 14 * * 1-5",
                "enabled": True,
                "action": "tail_preview",
                "job_ids": ["sync_stock_minute_bars"],
                "concurrency": 8,
                "last_started_at": None,
            }
        ],
    )
    monkeypatch.setattr(svc, "_touch_schedule", lambda *args, **kwargs: None)
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 17, 14, 30, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert triggered, "expected tail preview schedule to start a cache batch"
    assert triggered[0]["schedule_id"] == "tail_quant_1430"
    assert triggered[0]["job_ids"] == ["sync_stock_minute_bars", svc.TAIL_PREVIEW_BATCH_JOB_ID]


def test_scheduler_saves_limit_up_snapshot_each_live_minute(monkeypatch):
    import datetime as dt

    refreshed: list[bool] = []
    monkeypatch.setattr(
        svc,
        "refresh_live_snapshot",
        lambda: refreshed.append(True)
        or {
            "mode": "live_snapshot",
            "data_quality": {"is_stale": False},
            "recommendations": {"lanes": {"now": [{"action": "buy_now"}]}},
        },
    )
    monkeypatch.setattr(svc, "_touch_schedule", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [
            {
                "id": "limit_up_live_scan",
                "cron": "* 9-14 * * 1-5",
                "enabled": True,
                "action": "limit_up_live_scan",
                "job_ids": [],
                "concurrency": 1,
                "last_started_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: dt.datetime(
            2026,
            7,
            10,
            10,
            5,
            tzinfo=dt.timezone(dt.timedelta(hours=8)),
        ),
    )

    svc._run_scheduled_jobs()

    assert refreshed == [True]


def test_scheduler_does_not_scan_limit_up_during_lunch(monkeypatch):
    import datetime as dt

    refreshed: list[bool] = []
    monkeypatch.setattr(
        svc,
        "refresh_live_snapshot",
        lambda: refreshed.append(True) or {},
    )
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [
            {
                "id": "limit_up_live_scan",
                "cron": "* 9-14 * * 1-5",
                "enabled": True,
                "action": "limit_up_live_scan",
                "job_ids": [],
                "concurrency": 1,
                "last_started_at": None,
            }
        ],
    )
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: dt.datetime(
            2026,
            7,
            10,
            12,
            0,
            tzinfo=dt.timezone(dt.timedelta(hours=8)),
        ),
    )

    svc._run_scheduled_jobs()

    assert refreshed == []


def test_live_scan_reports_stale_result_as_skipped(monkeypatch):
    touched: list[dict[str, Any]] = []
    monkeypatch.setattr(
        svc,
        "refresh_live_snapshot",
        lambda: {
            "mode": "stale_snapshot",
            "data_quality": {"is_stale": True},
            "recommendations": {"lanes": {"now": []}},
        },
    )
    monkeypatch.setattr(
        svc,
        "_touch_schedule",
        lambda _schedule_id, **fields: touched.append(fields),
    )

    result = svc._run_schedule_action(
        {"id": "limit_up_live_scan", "action": "limit_up_live_scan"}
    )

    assert result["mode"] == "stale_snapshot"
    assert touched[-1]["last_status"] == "skipped"
    assert "未保存" in touched[-1]["last_message"]


def test_run_schedule_now_executes_live_scan_action_directly(monkeypatch):
    schedule = {
        "id": "limit_up_live_scan",
        "action": "limit_up_live_scan",
        "job_ids": [],
        "concurrency": 1,
    }
    called: list[str] = []

    class FakeResult:
        def mappings(self):
            return self

        def first(self):
            return schedule

    class FakeSession:
        def execute(self, _statement):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_run_schedule_action",
        lambda row, **_kwargs: called.append(str(row["id"]))
        or {
            "captured_at": "2026-07-10T10:05:00+08:00",
            "mode": "live_snapshot",
            "data_quality": {"is_stale": False},
            "candidates": [],
            "recommendations": {"lanes": {}},
        },
    )
    monkeypatch.setattr(
        svc,
        "_start_sync_schedule",
        lambda *_args, **_kwargs: {"profile": "empty_sync_batch"},
    )

    result = svc.run_schedule_now("limit_up_live_scan")

    assert called == ["limit_up_live_scan"]
    assert result["profile"] == "limit_up_live_scan"
    assert result["status"] == "succeeded"
    assert result["rows_written"] == 1


def test_live_scan_schedule_status_marks_stale_snapshot_as_skipped():
    result = svc._live_scan_schedule_status(
        "limit_up_live_scan",
        {
            "captured_at": "2026-07-10T10:05:00+08:00",
            "session_stage": "closed",
            "mode": "stale_snapshot",
            "data_quality": {"is_stale": True},
            "candidates": [{"symbol": "600000"}],
            "recommendations": {"lanes": {}},
        },
    )

    assert result["profile"] == "limit_up_live_scan"
    assert result["status"] == "skipped"
    assert result["skipped_jobs"] == 1
    assert result["rows_written"] == 0
    assert "未保存" in result["message"]
    assert result["jobs"][0]["status"] == "skipped"


def test_scheduler_skips_non_matching_cron(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw))
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [{"id": "eod_1900", "cron": "0 19 * * 1-5", "enabled": True, "action": "sync", "job_ids": ["sync_stock_list"], "concurrency": 8, "last_started_at": None}],
    )
    # now is 14:00, does not match the 19:00 cron
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 17, 14, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert not triggered


# ── Task 9: schedules API (CRUD + run) ─


def test_schedule_endpoints_crud(monkeypatch):
    from fastapi.testclient import TestClient

    from alphaagent.server.api import data_sync as data_sync_api
    from alphaagent.server.main import create_app

    monkeypatch.setattr(data_sync_api.service, "list_schedules", lambda: [{"id": "eod_1900", "name": "盘后同步"}])
    monkeypatch.setattr(data_sync_api.service, "create_schedule", lambda payload: {"id": "new_1", **payload})
    monkeypatch.setattr(data_sync_api.service, "update_schedule", lambda sid, payload: {"id": sid, **payload})
    monkeypatch.setattr(data_sync_api.service, "delete_schedule", lambda sid: {"id": sid, "deleted": True})
    monkeypatch.setattr(data_sync_api.service, "run_schedule_now", lambda sid: {"id": "batch_x", "schedule_id": sid})

    client = TestClient(create_app())

    resp = client.get("/api/data-sync/schedules")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "eod_1900"

    resp = client.post(
        "/api/data-sync/schedules",
        json={"name": "t", "cron": "0 14 * * 1-5", "job_ids": ["sync_stock_list"], "concurrency": 8},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == "new_1"

    resp = client.patch("/api/data-sync/schedules/new_1", json={"enabled": False})
    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False

    resp = client.delete("/api/data-sync/schedules/new_1")
    assert resp.json()["data"]["deleted"] is True

    resp = client.post("/api/data-sync/schedules/eod_1900/run")
    assert resp.json()["data"]["schedule_id"] == "eod_1900"
