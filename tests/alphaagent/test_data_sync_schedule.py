"""Tests for the unified incremental batch-sync scheduler.

Covers the ``sync_batch_schedules`` table, default schedules, batch execution
(failure isolation / concurrency), incremental bar sync, and the
schedule-driven scheduler. Implementation plan:
requirements/alphaagent_unified_schedule_execution_plan.md
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from threading import get_ident
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


def test_primary_eod_batch_watchdog_allows_extended_runtime() -> None:
    now = datetime(2026, 8, 10, 22, 0, tzinfo=timezone.utc)
    batch = {
        "id": "primary-eod",
        "status": "running",
        "schedule_id": "eod_1900",
        "started_at": now - timedelta(hours=3),
    }

    assert svc._select_zombie_batch_ids(
        [batch], now, svc.ZOMBIE_BATCH_THRESHOLD_SECONDS
    ) == []

    batch["started_at"] = now - timedelta(hours=5, minutes=1)

    assert svc._select_zombie_batch_ids(
        [batch], now, svc.ZOMBIE_BATCH_THRESHOLD_SECONDS
    ) == ["primary-eod"]


def test_low_suction_backtest_batch_skips_when_another_process_is_running(monkeypatch) -> None:
    from alphaagent.server.services.low_suction import daily_picks_service

    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 8, 10),
    )

    def busy() -> dict[str, object]:
        raise daily_picks_service.DailyBacktestAlreadyRunningError("busy")

    monkeypatch.setattr(daily_picks_service, "run_daily_backtest_sync", busy)

    result = svc._run_low_suction_daily_backtest_rerun_batch_job()

    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert "重复触发" in str(result["message"])


def test_low_suction_live_snapshot_refresh_batch_job_saves_confirmed_snapshot(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: datetime(2026, 8, 12, 19, 30, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 8, 12),
    )
    monkeypatch.setattr(
        svc,
        "refresh_live_recommendations",
        lambda: {
            "status": "ok",
            "trade_date": "2026-08-12",
            "trend": {"total": 2},
            "oversold": {"total": 3},
        },
    )

    result = svc._run_low_suction_live_snapshot_refresh_batch_job()

    assert result == {
        "status": "succeeded",
        "rows_read": 5,
        "rows_written": 1,
        "message": "已用 2026-08-12 确认日线刷新低吸实时快照，趋势 2 只，超跌 3 只",
    }


def test_stock_financial_sync_attempts_table_defined():
    table = schema.stock_financial_sync_attempts

    assert table.name == "stock_financial_sync_attempts"
    assert {column.name for column in table.primary_key.columns} == {"vt_symbol"}
    assert {
        "status",
        "attempt_count",
        "last_error",
        "last_attempt_at",
        "next_retry_at",
    }.issubset({column.name for column in table.columns})


def test_recent_quarter_ends_include_latest_finished_quarter():
    assert svc._recent_quarter_ends(date(2026, 7, 24), count=4) == [
        "2025-09-30",
        "2025-12-31",
        "2026-03-31",
        "2026-06-30",
    ]


def test_financial_report_dates_bootstrap_missing_periods_and_refresh_latest(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_financial_batch_covered_report_dates",
        lambda report_dates: {"2025-12-31", "2026-03-31"},
    )

    report_dates = svc._financial_report_dates_for_sync(
        {"bootstrap_quarters": 4},
        today=date(2026, 7, 24),
    )

    assert report_dates == ["2025-09-30", "2026-06-30"]


def test_merge_financial_report_values_preserves_only_enrichment_fields():
    existing = {
        "net_profit_yoy": 85.91,
        "cash_flow_quality": 1.5,
        "debt_asset_ratio": 45.0,
        "raw": {"NETPROFIT_QOQ": 85.91, "legacy": True},
    }
    incoming = {
        "net_profit_yoy": 10.30,
        "cash_flow_quality": None,
        "debt_asset_ratio": None,
        "raw": {"SJLTZ": 10.30},
    }

    merged = svc._merge_financial_report_values(existing, incoming)

    assert merged["net_profit_yoy"] == 10.30
    assert merged["cash_flow_quality"] == 1.5
    assert merged["debt_asset_ratio"] == 45.0
    assert merged["raw"] == {
        "NETPROFIT_QOQ": 85.91,
        "legacy": True,
        "SJLTZ": 10.30,
    }


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
    assert any("sector_fund_flow_snapshots" in sql for sql in executed)
    assert any(
        "ix_stock_financial_reports_source_date_symbol" in sql
        for sql in executed
    )


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
        "low_suction_live_scan",
        "intraday_hourly",
        "eod_1900",
        "eod_finalize_2130",
        "low_suction_backtest_2230",
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
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: now.date(),
    )
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


def test_stock_sector_snapshot_skips_when_today_is_not_a_reliable_session(
    monkeypatch,
):
    now = datetime.fromisoformat("2026-07-16T19:08:00+08:00")
    rebuilt: list[bool] = []

    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 7, 15),
    )
    monkeypatch.setattr(
        svc,
        "_rebuild_stock_sector_memberships",
        lambda: rebuilt.append(True) or 1,
    )

    result = svc.DataSyncRunner()._run_sync_stock_sector_memberships({})

    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert rebuilt == []


def test_stock_sector_snapshot_skips_completed_automatic_session(monkeypatch):
    now = datetime.fromisoformat("2026-07-20T21:35:00+08:00")

    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: now.date(),
    )
    monkeypatch.setattr(
        svc,
        "_completed_stock_sector_membership_session_coverage",
        lambda snapshot_date: {
            "status": "complete",
            "snapshot_date": snapshot_date.isoformat(),
            "scope_count": 2,
            "row_count": 86_946,
        },
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "_rebuild_stock_sector_memberships",
        lambda: pytest.fail("completed automatic session must not rebuild"),
    )

    result = svc.DataSyncRunner()._run_sync_stock_sector_memberships(
        {"skip_complete_session": True}
    )

    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert result["snapshot_rows_written"] == 0
    assert result["session_coverage"]["row_count"] == 86_946


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


def test_sector_fund_flow_upsert_uses_two_bulk_statements(monkeypatch):
    executions = []
    saved = []

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, statement, params=None):
            executions.append((statement, params))
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc.market_snapshot_repository,
        "save_sector_fund_flow_snapshots",
        lambda items, **kwargs: saved.append((items, kwargs)),
    )
    items = [
        {
            "id": "BK0001",
            "name": "概念一",
            "trade_date": "2026-07-20",
            "main_net_inflow": 1.0,
        },
        {
            "id": "BK0002",
            "name": "概念二",
            "trade_date": "2026-07-20",
            "main_net_inflow": 2.0,
        },
    ]

    written = svc._upsert_sector_fund_flows(items, "即时", "concept")

    assert written == 2
    assert [statement.table.name for statement, _ in executions] == [
        "sectors",
        "sector_fund_flows",
    ]
    assert [len(params) for _, params in executions] == [2, 2]
    assert len(saved) == 1


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
        def __init__(self, row=None):
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
            "last_message": f"{len(current_partial['job_ids']) - 1} 成功 / 1 失败",
        },
    }

    class FakeResult:
        def __init__(self, row=None):
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
    assert rows["eod_finalize_2130"]["last_message"] == (
        f"{len(current_partial['job_ids']) - 1} 成功 / 1 失败"
    )


def test_seed_default_registry_preserves_default_schedule_enabled_setting(monkeypatch):
    rows: dict[str, dict[str, Any]] = {
        "eod_1900": {
            "id": "eod_1900",
            "enabled": False,
            "last_status": None,
        }
    }

    class FakeResult:
        def __init__(self, row=None):
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

            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    svc.seed_default_registry()

    assert rows["eod_1900"]["enabled"] is False


def test_seed_default_registry_deletes_legacy_schedules(monkeypatch):
    rows: dict[str, dict[str, Any]] = {
        "eod_18h": {"id": "eod_18h", "enabled": True, "last_status": "succeeded"},
        "tail_quant_1430": {
            "id": "tail_quant_1430",
            "action": "tail_preview",
            "enabled": True,
        },
        "custom_quant": {
            "id": "custom_quant",
            "action": "quant_research",
            "enabled": True,
        },
    }

    class FakeResult:
        def __init__(self, row=None):
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
                for schedule_id, row in list(rows.items()):
                    if (
                        schedule_id in svc.LEGACY_DEFAULT_BATCH_SCHEDULE_IDS
                        or row.get("action") in svc.LEGACY_SCHEDULE_ACTIONS
                    ):
                        rows.pop(schedule_id, None)
                return FakeResult()

            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    svc.seed_default_registry()

    assert "eod_18h" not in rows
    assert "tail_quant_1430" not in rows
    assert "custom_quant" not in rows
    assert "eod_1900" in rows


def test_default_jobs_have_no_cron():
    # After dropping single-job schedules, every DEFAULT_JOBS entry has no cron.
    for job in svc.DEFAULT_JOBS:
        assert job.schedule_cron is None, f"{job.id} still has schedule_cron"


def test_intraday_schedule_contains_intraday_jobs():
    hourly = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "intraday_hourly")
    assert hourly["action"] == "sync"
    assert hourly["cron"] == "30 9,10,11,13,14 * * 1-5"
    assert hourly["concurrency"] == 2
    assert "sync_sector_fund_flows" in hourly["job_ids"]
    assert "sync_stock_fund_flows" in hourly["job_ids"]
    assert "sync_stock_hot_ranks" in hourly["job_ids"]
    assert "sync_stock_daily_bars" not in hourly["job_ids"]


def test_scheduler_uses_slow_tick_outside_live_scan_window() -> None:
    shanghai = timezone(timedelta(hours=8))

    assert svc._scheduler_tick_seconds(
        datetime(2026, 7, 20, 10, 0, tzinfo=shanghai)
    ) == svc.SCHEDULER_TICK_SECONDS
    assert svc._scheduler_tick_seconds(
        datetime(2026, 7, 20, 12, 0, tzinfo=shanghai)
    ) == svc.SCHEDULER_IDLE_TICK_SECONDS
    assert svc._scheduler_tick_seconds(
        datetime(2026, 7, 20, 21, 30, tzinfo=shanghai)
    ) == svc.SCHEDULER_IDLE_TICK_SECONDS


def test_heavy_default_schedules_use_bounded_concurrency():
    schedules = {row["id"]: row for row in svc.DEFAULT_BATCH_SCHEDULES}

    assert schedules["eod_1900"]["concurrency"] == 1
    assert schedules["eod_finalize_2130"]["concurrency"] == 1


def test_low_suction_live_scan_is_a_separate_minute_schedule():
    schedule = next(
        item
        for item in svc.DEFAULT_BATCH_SCHEDULES
        if item["id"] == "low_suction_live_scan"
    )

    assert schedule["action"] == "low_suction_live_scan"
    assert schedule["cron"] == "* 9-15 * * 1-5"
    assert schedule["job_ids"] == []
    assert svc.LOW_SUCTION_LIVE_SCAN_INTERVAL_SECONDS == 60


def test_stock_sector_reverse_index_is_frozen_daily():
    cadence = svc.JOB_CADENCES["sync_stock_sector_memberships"]

    assert cadence.cadence == svc.CADENCE_EOD_DAILY


def test_low_suction_live_scan_window_uses_actual_trading_hours():
    tz = timezone.utc

    assert not svc._low_suction_live_scan_window_open(
        datetime(2026, 7, 13, 9, 24, tzinfo=tz)
    )
    assert svc._low_suction_live_scan_window_open(
        datetime(2026, 7, 13, 9, 25, tzinfo=tz)
    )
    assert not svc._low_suction_live_scan_window_open(
        datetime(2026, 7, 13, 12, 0, tzinfo=tz)
    )
    assert svc._low_suction_live_scan_window_open(
        datetime(2026, 7, 13, 15, 1, tzinfo=tz)
    )
    assert not svc._low_suction_live_scan_window_open(
        datetime(2026, 7, 13, 15, 2, tzinfo=tz)
    )
    assert not svc._low_suction_live_scan_window_open(
        datetime(2026, 7, 18, 10, 0, tzinfo=tz)
    )


def test_eod_schedule_runs_unified_post_close_chain():
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_1900")
    assert eod["action"] == "sync"
    assert eod["cron"] == "0 19 * * 1-5"
    assert "sync_stock_daily_bars" in eod["job_ids"]
    assert "sync_index_daily_bars" in eod["job_ids"]
    assert "sync_mainline_sentiment_history" in eod["job_ids"]
    assert "sync_stock_fund_flows" in eod["job_ids"]
    assert "sync_sector_period_scores" in eod["job_ids"]
    assert "sync_stock_lhb_records" in eod["job_ids"]
    assert "sync_stock_financial_quarterly" in eod["job_ids"]


def test_eod_schedule_runs_market_data_and_low_suction_confirmation():
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_1900")
    jobs = eod["job_ids"]
    assert jobs == [
        "sync_stock_list",
        "sync_sector_fund_flows",
        "sync_stock_fund_flows",
        "sync_stock_daily_bars",
        svc.LOW_SUCTION_LIVE_SNAPSHOT_REFRESH_BATCH_JOB_ID,
        svc.ADJUSTED_DAILY_SYNC_JOB_ID,
        "sync_index_daily_bars",
        "sync_mainline_sentiment_history",
        "sync_sector_list",
        "sync_sector_daily_bars",
        "sync_sector_period_scores",
        "sync_sector_members",
        "sync_stock_sector_memberships",
        "sync_low_suction_security_snapshot",
        "sync_stock_lhb_records",
        "sync_stock_notices",
        "sync_stock_financial_quarterly",
        "sync_stock_financial_indicators",
        "sync_stock_business_segments_history",
    ]


def test_eod_finalize_schedule_retries_daily_bars_late_without_slow_jobs():
    finalize = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_finalize_2130")
    jobs = finalize["job_ids"]

    assert finalize["action"] == "sync"
    assert finalize["cron"] == "30 21 * * 1-5"
    assert jobs == [
        "sync_stock_daily_bars",
        svc.LOW_SUCTION_LIVE_SNAPSHOT_REFRESH_BATCH_JOB_ID,
        svc.ADJUSTED_DAILY_SYNC_JOB_ID,
        "sync_index_daily_bars",
        "sync_mainline_sentiment_history",
        "sync_sector_fund_flows",
        "sync_stock_fund_flows",
        "sync_sector_list",
        "sync_sector_daily_bars",
        "sync_sector_period_scores",
        "sync_sector_members",
        "sync_stock_sector_memberships",
        "sync_low_suction_security_snapshot",
    ]
    assert "sync_stock_financial_quarterly" not in jobs
    assert "sync_stock_lhb_records" not in jobs
    assert "sync_stock_notices" not in jobs


def test_low_suction_live_snapshot_refresh_runs_after_daily_bar_sync():
    for schedule_id in ("eod_1900", "eod_finalize_2130"):
        schedule = next(
            item
            for item in svc.DEFAULT_BATCH_SCHEDULES
            if item["id"] == schedule_id
        )
        jobs = schedule["job_ids"]
        assert jobs.index("sync_stock_daily_bars") < jobs.index(
            svc.LOW_SUCTION_LIVE_SNAPSHOT_REFRESH_BATCH_JOB_ID
        )


def test_mainline_sentiment_history_job_runs_after_daily_bar_inputs():
    job = next(
        item
        for item in svc.DEFAULT_JOBS
        if item.id == "sync_mainline_sentiment_history"
    )

    assert job.source_id == "alphaagent_local"
    assert job.target_table == "mainline_sentiment_history"
    assert svc.JOB_RUNNERS[job.id] == "_run_sync_mainline_sentiment_history"
    assert svc.JOB_CADENCES[job.id].freshness_table == "mainline_sentiment_history"
    for schedule_id in ("eod_1900", "eod_finalize_2130"):
        schedule = next(
            item for item in svc.DEFAULT_BATCH_SCHEDULES if item["id"] == schedule_id
        )
        jobs = schedule["job_ids"]
        assert jobs.index("sync_index_daily_bars") < jobs.index(job.id)


def test_low_suction_security_snapshot_job_is_registered_and_scheduled():
    job = next(
        item
        for item in svc.DEFAULT_JOBS
        if item.id == "sync_low_suction_security_snapshot"
    )
    assert job.source_id == "baostock"
    assert job.target_table == "low_suction_security_snapshots"
    assert svc.JOB_RUNNERS[job.id] == "_run_sync_low_suction_security_snapshot"
    assert svc.JOB_CADENCES[job.id].freshness_table == (
        "low_suction_security_snapshot_scopes"
    )

    for schedule_id in ("eod_1900", "eod_finalize_2130"):
        schedule = next(
            item for item in svc.DEFAULT_BATCH_SCHEDULES if item["id"] == schedule_id
        )
        jobs = schedule["job_ids"]
        assert jobs.index("sync_stock_sector_memberships") < jobs.index(job.id)


def test_low_suction_security_snapshot_skips_without_today_reliable_session(
    monkeypatch,
):
    now = datetime.fromisoformat("2026-07-16T19:08:00+08:00")
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 7, 15),
    )
    monkeypatch.setattr(
        svc.baostock_security_source,
        "fetch_forward_security_snapshot",
        lambda **kwargs: pytest.fail("holiday run must not call BaoStock"),
    )
    monkeypatch.setattr(
        svc.forward_security_repository,
        "replace_forward_security_snapshot",
        lambda snapshot: pytest.fail("holiday run must not write a snapshot"),
    )

    result = svc.DataSyncRunner()._run_sync_low_suction_security_snapshot({})

    assert result["status"] == "skipped"
    assert result["rows_read"] == 0
    assert result["rows_written"] == 0


def test_low_suction_security_snapshot_writes_complete_provider_result(monkeypatch):
    now = datetime.fromisoformat("2026-07-16T19:08:00+08:00")
    captured: dict[str, Any] = {}

    class Snapshot:
        source_trade_date = now.date()
        records = tuple(range(3_192))
        expected_symbol_count = 3_192
        returned_symbol_count = 3_192
        risk_warning_count = 121
        suspended_count = 34

    def fake_fetch(**kwargs):
        captured.update(kwargs)
        return Snapshot()

    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: now.date(),
    )
    monkeypatch.setattr(
        svc.baostock_security_source,
        "fetch_forward_security_snapshot",
        fake_fetch,
    )
    monkeypatch.setattr(
        svc.forward_security_repository,
        "replace_forward_security_snapshot",
        lambda snapshot: len(snapshot.records),
    )

    result = svc.DataSyncRunner()._run_sync_low_suction_security_snapshot({})

    assert captured == {
        "source_trade_date": now.date(),
        "observed_at": now,
    }
    assert result["rows_read"] == 3_192
    assert result["rows_written"] == 3_192
    assert result["risk_warning_rows"] == 121
    assert result["suspended_rows"] == 34


def test_low_suction_security_snapshot_skips_completed_automatic_session(
    monkeypatch,
):
    now = datetime.fromisoformat("2026-07-20T21:35:00+08:00")

    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: now.date(),
    )
    monkeypatch.setattr(
        svc,
        "_completed_low_suction_security_session_coverage",
        lambda source_trade_date: {
            "status": "complete",
            "source_trade_date": source_trade_date.isoformat(),
            "expected_symbol_count": 3_191,
            "returned_symbol_count": 3_191,
        },
        raising=False,
    )
    monkeypatch.setattr(
        svc.baostock_security_source,
        "fetch_forward_security_snapshot",
        lambda **kwargs: pytest.fail("completed automatic session must not refetch"),
    )

    result = svc.DataSyncRunner()._run_sync_low_suction_security_snapshot(
        {"skip_complete_session": True}
    )

    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert result["session_coverage"]["returned_symbol_count"] == 3_191


def test_low_suction_security_snapshot_provider_gap_fails_closed(monkeypatch):
    now = datetime.fromisoformat("2026-07-16T19:08:00+08:00")
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: now.date(),
    )
    monkeypatch.setattr(
        svc.baostock_security_source,
        "fetch_forward_security_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(
            svc.baostock_security_source.BaoStockSourceError(
                "missing active main-board symbols"
            )
        ),
    )

    with pytest.raises(
        svc.baostock_security_source.BaoStockSourceError,
        match="missing active",
    ):
        svc.DataSyncRunner()._run_sync_low_suction_security_snapshot({})





def test_eod_schedule_passes_incremental_concept_index_params() -> None:
    schedule = next(
        item for item in svc.DEFAULT_BATCH_SCHEDULES if item["id"] == "eod_1900"
    )

    params = svc._schedule_batch_params(
        schedule,
        schedule["action"],
        schedule["job_ids"],
    )

    assert params == {
        "jobs": {
            "sync_stock_daily_bars": {
                "skip_complete_session": True,
            },
            svc.ADJUSTED_DAILY_SYNC_JOB_ID: {
                "max_symbols": 50,
                "max_workers": 4,
            },
            "sync_sector_daily_bars": {
                "limit": 30,
                "sector_types": ["concept", "theme"],
                "skip_complete_session": True,
            },
            "sync_sector_period_scores": {
                "skip_complete_session": True,
            },
            "sync_sector_members": {
                "skip_complete_session": True,
            },
            "sync_stock_sector_memberships": {
                "skip_complete_session": True,
            },
            "sync_low_suction_security_snapshot": {
                "skip_complete_session": True,
            },
        }
    }


def test_sector_mainline_jobs_default_to_full_sector_coverage():
    bars_job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_sector_daily_bars")
    scores_job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_sector_period_scores")

    assert bars_job.default_params["limit"] == 800
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


def test_sector_period_scores_skips_completed_automatic_session(monkeypatch):
    as_of = date(2026, 7, 20)

    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: as_of,
    )
    monkeypatch.setattr(
        svc,
        "_completed_sector_score_session_coverage",
        lambda score_date, periods: {
            "status": "complete",
            "as_of_date": score_date.isoformat(),
            "expected_sector_count": 994,
            "period_counts": {period: 994 for period in periods},
        },
        raising=False,
    )
    monkeypatch.setattr(
        svc.research_sector_scores,
        "compute_and_persist",
        lambda **kwargs: pytest.fail("completed automatic session must not recompute"),
    )

    result = svc.DataSyncRunner(adapter=object())._run_sync_sector_period_scores(
        {"periods": ["20d"], "skip_complete_session": True}
    )

    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert result["session_coverage"]["period_counts"] == {"20d": 994}


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
            return ["eod_1900"]

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

    assert svc.mark_interrupted_runs() == ["eod_1900"]
    assert queued == ["eod_1900"]


def test_recover_interrupted_schedules_runs_only_still_interrupted(monkeypatch):
    rows = {
        "eod_1900": {
            "id": "eod_1900",
            "cron": "0 19 * * 1-5",
            "enabled": True,
            "action": "sync",
            "job_ids": ["sync_stock_daily_bars"],
            "concurrency": 8,
            "last_status": "failed",
            "last_message": svc.INTERRUPTED_SCHEDULE_MESSAGE,
        },
        "eod_finalize_2130": None,
    }
    recovered: list[tuple[str, str]] = []

    monkeypatch.setattr(svc, "_load_recoverable_interrupted_schedule", lambda schedule_id: rows.get(schedule_id), raising=False)
    monkeypatch.setattr(
        svc,
        "_run_schedule_action",
        lambda row, *, source="schedule": recovered.append((row["id"], source)),
    )
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: datetime.fromisoformat("2026-07-20T19:05:00+08:00"),
    )

    svc._recover_interrupted_schedules(["eod_1900", "eod_finalize_2130"])

    assert recovered == [("eod_1900", "recovery")]


def test_interrupted_schedule_resumes_only_pending_jobs(monkeypatch):
    started_at = datetime.fromisoformat("2026-07-20T21:30:00+08:00")
    row = {
        "job_ids": ["stock_bars", "index_bars", "sector_bars", "scores"],
        "last_started_at": started_at,
    }
    captured: list[tuple[list[str], datetime]] = []

    def fake_successful_jobs(job_ids, since):
        captured.append((job_ids, since))
        return {"stock_bars", "index_bars"}

    monkeypatch.setattr(
        svc,
        "_successful_sync_job_ids_since",
        fake_successful_jobs,
        raising=False,
    )

    pending = svc._remaining_interrupted_schedule_jobs(row)

    assert pending == ["sector_bars", "scores"]
    assert captured == [
        (["stock_bars", "index_bars", "sector_bars", "scores"], started_at)
    ]


def test_recover_interrupted_eod_waits_for_its_scheduled_time(monkeypatch):
    row = {
        "id": "eod_1900",
        "cron": "0 19 * * 1-5",
        "enabled": True,
        "action": "sync",
        "job_ids": ["sync_stock_daily_bars"],
        "concurrency": 8,
        "last_status": "failed",
        "last_message": svc.INTERRUPTED_SCHEDULE_MESSAGE,
    }
    recovered: list[str] = []
    monkeypatch.setattr(
        svc,
        "_load_recoverable_interrupted_schedule",
        lambda _schedule_id: row,
    )
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: datetime.fromisoformat("2026-07-20T13:30:00+08:00"),
    )
    monkeypatch.setattr(
        svc,
        "_run_schedule_action",
        lambda value: recovered.append(str(value["id"])),
    )

    svc._recover_interrupted_schedules(["eod_1900"])

    assert recovered == []


def test_primary_eod_recovery_defers_to_2130_retry_after_2100() -> None:
    primary = {"id": "eod_1900", "cron": "0 19 * * 1-5"}
    retry = {"id": "eod_finalize_2130", "cron": "30 21 * * 1-5"}

    assert svc._interrupted_schedule_recovery_due(
        primary,
        datetime.fromisoformat("2026-07-20T20:59:00+08:00"),
    ) is True
    assert svc._interrupted_schedule_recovery_due(
        primary,
        datetime.fromisoformat("2026-07-20T21:00:00+08:00"),
    ) is False
    assert svc._interrupted_schedule_recovery_due(
        retry,
        datetime.fromisoformat("2026-07-20T21:31:00+08:00"),
    ) is True


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

    svc._queue_interrupted_schedule_recovery(["eod_1900", "eod_finalize_2130"])
    svc.start_interrupted_schedule_recovery(delay_seconds=0)

    assert started == [(["eod_1900", "eod_finalize_2130"], 0)]
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


def test_recovery_batch_preserves_original_schedule_start(monkeypatch):
    touches: list[tuple[str, dict[str, Any]]] = []

    def fake_run_batch(
        batch_id,
        params,
        *,
        concurrency=8,
        source="manual",
        schedule_id=None,
    ):
        del params, concurrency, source, schedule_id
        svc._SYNC_BATCHES[batch_id]["status"] = "succeeded"

    monkeypatch.setattr(svc, "_run_sync_batch", fake_run_batch)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(
        svc,
        "_touch_schedule",
        lambda schedule_id, **values: touches.append((schedule_id, values)),
    )
    svc._SYNC_BATCHES.clear()
    svc._LATEST_BATCH_ID = None

    svc.start_sync_batch(
        job_ids=["sync_stock_daily_bars"],
        source="recovery",
        schedule_id="eod_finalize_2130",
    )

    assert touches == [
        ("eod_finalize_2130", {"last_status": "running"})
    ]


def test_start_sync_batch_explicit_empty_job_ids_does_not_fallback(monkeypatch):
    captured = {}

    def fake_run_batch(batch_id, params, *, concurrency=8, source="manual", schedule_id=None):
        captured["job_ids"] = params.get("_job_ids")
        captured["concurrency"] = concurrency
        b = svc._SYNC_BATCHES[batch_id]
        b["status"] = "succeeded"

    monkeypatch.setattr(svc, "_run_sync_batch", fake_run_batch)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)

    result = svc.start_sync_batch(job_ids=[])

    assert result["total_jobs"] == 0
    assert captured["job_ids"] == []
    assert captured["concurrency"] == 2


def test_run_job_builds_runner_with_safe_default_concurrency(monkeypatch):
    captured = {}

    class FakeRunner:
        def __init__(self, adapter=None, progress=None, concurrency=8):
            del adapter, progress
            captured["concurrency"] = concurrency

        def _run_sync_stock_list(self, params):
            captured["params"] = params
            return {"rows_read": 0, "rows_written": 0}

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "DataSyncRunner", FakeRunner)
    monkeypatch.setattr(svc, "_create_run", lambda *_args: 1)
    monkeypatch.setattr(svc, "_finish_run", lambda *_args, **_kwargs: None)

    svc.run_job("sync_stock_list", {})

    assert captured["concurrency"] == 2


def test_run_job_records_incomplete_coverage_as_failure(monkeypatch):
    finished: dict[str, object] = {}

    class FakeRunner:
        def __init__(self, adapter=None, progress=None, concurrency=8):
            del adapter, progress, concurrency

        def _run_sync_stock_daily_bars(self, params):
            del params
            return {
                "status": "incomplete",
                "rows_read": 4_999,
                "rows_written": 4_999,
                "message": "日线仍有缺口",
            }

    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "DataSyncRunner", FakeRunner)
    monkeypatch.setattr(svc, "_create_run", lambda *_args: 1)
    monkeypatch.setattr(
        svc,
        "_finish_run",
        lambda run_id, status, **kwargs: finished.update(
            run_id=run_id,
            status=status,
            **kwargs,
        ),
    )

    result = svc.run_job("sync_stock_daily_bars", {})

    assert result["status"] == "incomplete"
    assert finished == {
        "run_id": 1,
        "status": "failed",
        "rows_read": 4_999,
        "rows_written": 4_999,
        "message": "日线仍有缺口",
        "error_type": "DataCoverageIncomplete",
    }


def test_sync_schedule_requires_job_ids():
    try:
        svc._assert_schedule_jobs("sync", [])
    except svc.DataSyncError as exc:
        assert "at least one job_id" in str(exc)
    else:
        raise AssertionError("expected sync schedule without jobs to fail")


def test_sync_schedule_rejects_removed_internal_job():
    try:
        svc._assert_schedule_jobs("sync", ["tail_preview_cache"])
    except svc.DataSyncError as exc:
        assert "tail_preview_cache" in str(exc)
    else:
        raise AssertionError("expected sync schedule with removed internal job to fail")


def test_batch_continues_after_job_failure_and_forwards_concurrency(monkeypatch):
    import time

    svc._SYNC_BATCHES.clear()
    svc._LATEST_BATCH_ID = None
    calls = []

    def fake_run_job(job_id, params=None, progress=None, *, concurrency=8):
        calls.append((job_id, concurrency))
        if job_id == "bad":
            raise RuntimeError("boom")
        return {"rows_read": 1, "rows_written": 1}

    monkeypatch.setattr(svc, "run_job", fake_run_job)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)

    result = svc.start_sync_batch(
        job_ids=["good_a", "bad", "good_b"],
        concurrency=2,
    )

    batch = svc.get_sync_batch(result["id"])
    for _ in range(200):
        if batch["status"] != "running":
            break
        time.sleep(0.01)
        batch = svc.get_sync_batch(result["id"])

    assert batch["status"] == "partial"          # 1 failed, 2 succeeded
    assert batch["failed_jobs"] == 1
    assert batch["succeeded_jobs"] == 2
    assert ("good_b", 2) in calls                 # continues after failure
    assert {concurrency for _, concurrency in calls} == {2}


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


def test_scheduled_stock_daily_sync_skips_complete_session(monkeypatch):
    stock_rows = [
        {"symbol": f"60000{index}", "exchange": "SSE", "name": "A"}
        for index in range(4)
    ]

    class FakeAdapter:
        def stock_bars(self, *args, **kwargs):
            del args, kwargs
            pytest.fail("complete session must not fetch the full market again")

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: stock_rows,
    )
    monkeypatch.setattr(
        svc,
        "_stock_daily_history_bootstrap_plan",
        lambda **_kwargs: {
            "required": False,
            "reliable_trade_days_before": 750,
            "target_trade_days": 750,
            "request_limit": 800,
        },
    )
    monkeypatch.setattr(
        svc,
        "_completed_stock_daily_session_coverage",
        lambda _total_stocks: {
            "status": "complete",
            "target_trade_date": "2026-07-20",
            "symbol_count": 4,
            "min_symbol_count": 3,
        },
        raising=False,
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda _symbols: {})

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_stock_daily_bars(
        {
            "limit": 250,
            "incremental": True,
            "skip_complete_session": True,
        }
    )

    assert result == {
        "status": "skipped",
        "rows_read": 0,
        "rows_written": 0,
        "session_coverage": {
            "status": "complete",
            "target_trade_date": "2026-07-20",
            "symbol_count": 4,
            "min_symbol_count": 3,
        },
        "message": "2026-07-20 日线已完整覆盖 4/3 只，跳过重复全市场同步",
    }


def test_scheduled_stock_daily_sync_fetches_only_missing_symbols(monkeypatch):
    stock_rows = [
        {"symbol": f"60000{index}", "exchange": "SSE", "name": "A"}
        for index in range(4)
    ]
    fetched: list[str] = []

    class FakeAdapter:
        def stock_bars(self, symbol, *args, **kwargs):
            del args, kwargs
            fetched.append(symbol)
            return {"items": []}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: stock_rows,
    )
    monkeypatch.setattr(
        svc,
        "_stock_daily_history_bootstrap_plan",
        lambda **_kwargs: {
            "required": False,
            "reliable_trade_days_before": 750,
            "target_trade_days": 750,
            "request_limit": 800,
        },
    )
    monkeypatch.setattr(
        svc,
        "_completed_stock_daily_session_coverage",
        lambda _stock_rows: {
            "status": "incomplete",
            "target_trade_date": "2026-07-20",
            "missing_vt_symbols": ["600001.SSE"],
        },
        raising=False,
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda _symbols: {})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda *args: 0)

    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_daily_bars(
        {
            "limit": 250,
            "incremental": True,
            "skip_complete_session": True,
        }
    )

    assert fetched == ["600001"]


def test_scheduled_stock_daily_sync_retains_partial_rows_for_next_retry(monkeypatch):
    stock_rows = [
        {"symbol": f"60000{index}", "exchange": "SSE", "name": "A"}
        for index in range(4)
    ]

    class FakeAdapter:
        def stock_bars(self, *args, **kwargs):
            del args, kwargs
            return {"items": []}

    monkeypatch.setattr(svc, "MIN_COMPLETE_DAILY_SYMBOL_COUNT", 3)
    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: stock_rows,
    )
    monkeypatch.setattr(
        svc,
        "_stock_daily_history_bootstrap_plan",
        lambda **_kwargs: {
            "required": False,
            "reliable_trade_days_before": 750,
            "target_trade_days": 750,
            "request_limit": 800,
        },
    )
    monkeypatch.setattr(
        svc,
        "_completed_stock_daily_session_coverage",
        lambda _stock_rows: {
            "status": "incomplete",
            "target_trade_date": "2026-07-20",
            "missing_symbol_count": 1,
            "missing_vt_symbols": ["600001.SSE"],
        },
    )
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda _symbols: {})
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda *args: 0)
    monkeypatch.setattr(
        svc,
        "_discard_incomplete_latest_daily_bars",
        lambda _total_stocks: pytest.fail("scheduled gap reconciliation must retain partial rows"),
    )

    result = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_stock_daily_bars(
        {"incremental": True, "skip_complete_session": True}
    )

    assert result["status"] == "incomplete"
    assert result["session_coverage"]["missing_vt_symbols"] == ["600001.SSE"]
    assert "保留已同步数据" in result["message"]


def test_daily_session_coverage_requires_every_expected_symbol():
    coverage = svc._daily_session_coverage_from_symbols(
        target_date=date(2026, 7, 20),
        reference_date=date(2026, 7, 17),
        expected_vt_symbols={
            "600000.SSE",
            "600001.SSE",
            "600002.SSE",
            "600003.SSE",
            "600004.SSE",
        },
        observed_vt_symbols={
            "600000.SSE",
            "600001.SSE",
            "600002.SSE",
            "600003.SSE",
        },
    )

    assert coverage["status"] == "incomplete"
    assert coverage["expected_symbol_count"] == 5
    assert coverage["missing_symbol_count"] == 1
    assert coverage["missing_vt_symbols"] == ["600004.SSE"]


def test_select_daily_bar_stocks_avoids_raw_snapshot_payload(monkeypatch):
    selected_columns: list[str] = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class FakeSession:
        def execute(self, statement):
            selected_columns.extend(column.name for column in statement.selected_columns)
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    assert svc._select_daily_bar_stocks([], 0) == []
    assert selected_columns == [
        "symbol",
        "exchange",
        "name",
        "last_price",
        "turnover",
        "created_at",
        "updated_at",
    ]


def test_daily_session_reference_prefers_widest_recent_cross_section():
    reference_date = svc._select_daily_session_reference_date(
        [
            (date(2026, 7, 16), 5_532),
            (date(2026, 7, 17), 5_530),
            (date(2026, 7, 18), 5_275),
        ]
    )

    assert reference_date == date(2026, 7, 16)


def test_completed_stock_daily_session_uses_previous_cross_section(monkeypatch):
    target_date = date(2026, 7, 20)
    reference_date = date(2026, 7, 17)
    session = object()
    stock_rows = [
        {
            "symbol": "600000",
            "exchange": "SSE",
            "last_price": 10,
            "updated_at": datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
        },
        {
            "symbol": "600001",
            "exchange": "SSE",
            "last_price": 10,
            "updated_at": datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
        },
        {
            "symbol": "600003",
            "exchange": "SSE",
            "last_price": 10,
            "updated_at": datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
        },
    ]

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "completed_daily_bar_cutoff",
        lambda _at: target_date,
    )
    monkeypatch.setattr(
        svc,
        "_daily_session_reference_date",
        lambda current_session, current_target_date: reference_date,
    )
    monkeypatch.setattr(
        svc,
        "_daily_bar_symbols_for_date",
        lambda current_session, trade_date: (
            {"600000.SSE", "600001.SSE", "600002.SSE"}
            if trade_date == reference_date
            else {"600000.SSE"}
        ),
    )

    result = svc._completed_stock_daily_session_coverage(stock_rows)

    assert result == {
        "status": "incomplete",
        "target_trade_date": "2026-07-20",
        "symbol_count": 1,
        "expected_symbol_count": 2,
        "missing_symbol_count": 1,
        "missing_vt_symbols": ["600001.SSE"],
        "reference_trade_date": "2026-07-17",
    }


def test_completed_stock_daily_session_includes_newly_discovered_symbols(monkeypatch):
    target_date = date(2026, 7, 20)
    reference_date = date(2026, 7, 17)
    session = object()
    stock_rows = [
        {"symbol": "600000", "exchange": "SSE", "last_price": 10, "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc)},
        {"symbol": "600001", "exchange": "SSE", "last_price": 10, "created_at": datetime(2026, 7, 18, tzinfo=timezone.utc)},
    ]

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "completed_daily_bar_cutoff", lambda _at: target_date)
    monkeypatch.setattr(
        svc,
        "_daily_session_reference_date",
        lambda current_session, current_target_date: reference_date,
    )
    monkeypatch.setattr(
        svc,
        "_daily_bar_symbols_for_date",
        lambda current_session, trade_date: {"600000.SSE"},
    )

    result = svc._completed_stock_daily_session_coverage(stock_rows)

    assert result["status"] == "incomplete"
    assert result["expected_symbol_count"] == 2
    assert result["missing_vt_symbols"] == ["600001.SSE"]


def test_completed_stock_daily_session_excludes_symbols_discovered_after_target(monkeypatch):
    target_date = date(2026, 7, 20)
    reference_date = date(2026, 7, 17)
    session = object()
    stock_rows = [
        {"symbol": "600000", "exchange": "SSE", "last_price": 10, "created_at": datetime(2026, 7, 1, tzinfo=timezone.utc)},
        {"symbol": "600001", "exchange": "SSE", "last_price": 10, "created_at": datetime(2026, 7, 21, tzinfo=timezone.utc)},
    ]

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "completed_daily_bar_cutoff", lambda _at: target_date)
    monkeypatch.setattr(
        svc,
        "_daily_session_reference_date",
        lambda current_session, current_target_date: reference_date,
    )
    monkeypatch.setattr(
        svc,
        "_daily_bar_symbols_for_date",
        lambda current_session, trade_date: {"600000.SSE"},
    )

    result = svc._completed_stock_daily_session_coverage(stock_rows)

    assert result["status"] == "complete"
    assert result["expected_symbol_count"] == 1
    assert result["missing_vt_symbols"] == []


def test_completed_stock_daily_session_excludes_non_trading_quotes(monkeypatch):
    target_date = date(2026, 7, 20)
    reference_date = date(2026, 7, 17)
    session = object()
    stock_rows = [
        {"symbol": "600000", "exchange": "SSE", "last_price": 10},
        {
            "symbol": "600001",
            "exchange": "SSE",
            "last_price": 10,
            "turnover": 0,
            "updated_at": datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
        },
    ]

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "completed_daily_bar_cutoff", lambda _at: target_date)
    monkeypatch.setattr(
        svc,
        "_daily_session_reference_date",
        lambda current_session, current_target_date: reference_date,
    )
    monkeypatch.setattr(
        svc,
        "_daily_bar_symbols_for_date",
        lambda current_session, trade_date: (
            {"600000.SSE", "600001.SSE"}
            if trade_date == reference_date
            else {"600000.SSE"}
        ),
    )

    result = svc._completed_stock_daily_session_coverage(stock_rows)

    assert result["status"] == "complete"
    assert result["expected_symbol_count"] == 1
    assert result["excluded_non_trading_symbol_count"] == 1


def test_completed_stock_daily_session_excludes_stale_positive_quotes(monkeypatch):
    target_date = date(2026, 7, 20)
    reference_date = date(2026, 7, 17)
    session = object()
    stock_rows = [
        {
            "symbol": "600000",
            "exchange": "SSE",
            "last_price": 10,
            "updated_at": datetime(2026, 7, 20, 10, tzinfo=timezone.utc),
        },
        {
            "symbol": "600001",
            "exchange": "SSE",
            "last_price": 10,
            "turnover": 1_000_000,
            "updated_at": datetime(2026, 7, 19, 10, tzinfo=timezone.utc),
        },
    ]

    @contextmanager
    def fake_session_scope():
        yield session

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "completed_daily_bar_cutoff", lambda _at: target_date)
    monkeypatch.setattr(
        svc,
        "_daily_session_reference_date",
        lambda current_session, current_target_date: reference_date,
    )
    monkeypatch.setattr(
        svc,
        "_daily_bar_symbols_for_date",
        lambda current_session, trade_date: (
            {"600000.SSE", "600001.SSE"}
            if trade_date == reference_date
            else {"600000.SSE"}
        ),
    )

    result = svc._completed_stock_daily_session_coverage(stock_rows)

    assert result["status"] == "complete"
    assert result["expected_symbol_count"] == 1
    assert result["missing_vt_symbols"] == []
    assert result["excluded_non_trading_symbol_count"] == 1


def test_stock_daily_history_bootstrap_targets_strict_three_year_buffer():
    assert svc.STOCK_DAILY_HISTORY_TARGET_DAYS == 750
    assert svc.STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT == 800


def test_stock_daily_sync_bootstraps_underfilled_full_market_history(monkeypatch):
    captured: list[dict[str, object]] = []

    class FakeAdapter:
        def stock_bars(
            self,
            symbol,
            exchange=None,
            limit=90,
            interval="1d",
            start_date=None,
            end_date=None,
        ):
            captured.append({"limit": limit, "start_date": start_date})
            return {"items": [{"trade_date": "2026-06-26", "close": 11}]}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [
            {"symbol": "600000", "exchange": "SSE", "name": "A"}
        ],
    )
    monkeypatch.setattr(
        svc,
        "_stock_daily_history_bootstrap_plan",
        lambda **_kwargs: {
            "required": True,
            "reliable_trade_days_before": 603,
            "target_trade_days": 750,
            "request_limit": 800,
        },
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "_reliable_stock_daily_trade_days",
        lambda: 756,
    )
    monkeypatch.setattr(
        svc,
        "_last_bar_dates_daily",
        lambda vt_symbols: {"600000.SSE": "2026-06-26"},
    )
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: len(items))

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_stock_daily_bars({"limit": 250, "incremental": True})

    assert captured == [{"limit": 800, "start_date": None}]
    assert result["history_bootstrap"] == {
        "performed": True,
        "reliable_trade_days_before": 603,
        "reliable_trade_days_after": 756,
        "target_trade_days": 750,
        "request_limit": 800,
        "target_achieved": True,
    }


def test_stock_daily_bootstrap_reports_unmet_target_without_discarding_rows(
    monkeypatch,
):
    class FakeAdapter:
        def stock_bars(
            self,
            symbol,
            exchange=None,
            limit=90,
            interval="1d",
            start_date=None,
            end_date=None,
        ):
            return {"items": [{"trade_date": "2026-06-26", "close": 11}]}

    monkeypatch.setattr(
        svc,
        "_select_daily_bar_stocks",
        lambda symbols, stock_limit: [
            {"symbol": "600000", "exchange": "SSE", "name": "A"}
        ],
    )
    monkeypatch.setattr(
        svc,
        "_stock_daily_history_bootstrap_plan",
        lambda **_kwargs: {
            "required": True,
            "reliable_trade_days_before": 603,
            "target_trade_days": 750,
            "request_limit": 800,
        },
    )
    monkeypatch.setattr(
        svc,
        "_reliable_stock_daily_trade_days",
        lambda: 744,
    )
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: len(items))

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_stock_daily_bars({"limit": 250, "incremental": True})

    assert result["rows_written"] == 1
    assert result["history_bootstrap"]["reliable_trade_days_after"] == 744
    assert result["history_bootstrap"]["target_achieved"] is False


def test_stock_daily_history_bootstrap_plan_ignores_targeted_sync(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_reliable_stock_daily_trade_days",
        lambda: (_ for _ in ()).throw(AssertionError("coverage query should not run")),
        raising=False,
    )

    plan = svc._stock_daily_history_bootstrap_plan(
        symbols=["600000.SSE"],
        stock_limit=0,
        total_stocks=5_500,
        incremental=True,
    )

    assert plan["required"] is False


def test_stock_daily_history_bootstrap_plan_requires_749_days(
    monkeypatch,
):
    monkeypatch.setattr(
        svc,
        "_reliable_stock_daily_trade_days",
        lambda: 749,
    )

    plan = svc._stock_daily_history_bootstrap_plan(
        symbols=[],
        stock_limit=0,
        total_stocks=5_500,
        incremental=True,
    )

    assert plan == {
        "required": True,
        "reliable_trade_days_before": 749,
        "target_trade_days": 750,
        "request_limit": 800,
    }


def test_stock_daily_history_bootstrap_plan_accepts_750_days(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_reliable_stock_daily_trade_days",
        lambda: 750,
    )

    plan = svc._stock_daily_history_bootstrap_plan(
        symbols=[],
        stock_limit=0,
        total_stocks=5_500,
        incremental=True,
    )

    assert plan["required"] is False
    assert plan["reliable_trade_days_before"] == 750
    assert plan["target_trade_days"] == 750


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
    monkeypatch.setattr(svc, "MIN_COMPLETE_DAILY_SYMBOL_COUNT", 3)
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


def test_daily_sync_retains_intraday_rows_without_marking_them_complete(
    monkeypatch,
):
    executed = []

    class FakeResult:
        def scalar(self):
            return date(2026, 7, 16)

    class FakeSession:
        def execute(self, statement):
            executed.append(statement)
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "completed_daily_bar_cutoff",
        lambda _at: date(2026, 7, 15),
    )
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date",
        lambda session, min_symbol_count: date(2026, 7, 15),
    )
    monkeypatch.setattr(
        svc,
        "_stock_daily_symbol_count",
        lambda session, trade_date: (
            5_531 if trade_date == date(2026, 7, 16) else 5_532
        ),
    )

    result = svc._discard_incomplete_latest_daily_bars(5_878)

    assert result == {
        "status": "intraday_retained",
        "latest_trade_date": "2026-07-16",
        "latest_symbol_count": 5_531,
        "latest_complete_trade_date": "2026-07-15",
        "latest_complete_symbol_count": 5_532,
        "completed_cutoff": "2026-07-15",
    }
    assert len(executed) == 1


def test_daily_sync_complete_threshold_uses_strict_full_market_ratio(monkeypatch):
    monkeypatch.setattr(svc, "MIN_COMPLETE_DAILY_SYMBOL_COUNT", 3000)

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


def test_sector_members_sync_reuses_fresh_members_for_forward_capture(monkeypatch):
    observed_at = datetime(2026, 7, 20, 11, 30, tzinfo=timezone.utc)
    sector_rows = [
        {
            "id": "BK0001",
            "type": "concept",
            "name": "Fresh",
            "members_refreshed_at": observed_at - timedelta(days=2),
        }
    ]
    cached_members = {
        "BK0001": (
            {
                "vt_symbol": "600000.SSE",
                "symbol": "600000",
                "exchange": "SSE",
                "source": "eastmoney.push2.board",
            },
        )
    }
    remote_calls: list[str] = []
    saved_captures: list[dict[str, object]] = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, **kwargs):
            del kwargs
            remote_calls.append(sector_id)
            raise AssertionError("fresh sector must not call the provider")

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return sector_rows

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_load_sector_rows_with_member_freshness",
        lambda: sector_rows,
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "_load_cached_sector_memberships",
        lambda sector_ids: cached_members if set(sector_ids) == {"BK0001"} else {},
        raising=False,
    )
    monkeypatch.setattr(svc, "_now_china", lambda: observed_at)
    monkeypatch.setattr(
        svc,
        "_save_low_suction_forward_membership_capture",
        lambda **kwargs: saved_captures.append(kwargs),
    )
    monkeypatch.setattr(svc, "_delete_sector_memberships", lambda sector_ids: 0)

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_sector_members({"page_size": 50})

    assert remote_calls == []
    assert result["status"] == "skipped"
    assert result["requested_sector_count"] == 0
    assert result["refreshed_sector_count"] == 0
    assert result["reused_sector_count"] == 1
    assert saved_captures[0]["members_by_sector"] == cached_members


def test_sector_members_skips_completed_automatic_session(monkeypatch):
    observed_at = datetime.fromisoformat("2026-07-20T21:35:00+08:00")

    monkeypatch.setattr(svc, "_now_china", lambda: observed_at)
    monkeypatch.setattr(
        svc,
        "_completed_forward_membership_session_coverage",
        lambda source_trade_date: {
            "status": "complete",
            "source_trade_date": source_trade_date.isoformat(),
            "expected_sector_count": 446,
            "returned_sector_count": 446,
            "row_count": 60_736,
        },
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "_load_sector_rows_with_member_freshness",
        lambda: pytest.fail("completed automatic session must not reload memberships"),
    )

    result = svc.DataSyncRunner(adapter=object())._run_sync_sector_members(
        {"skip_complete_session": True}
    )

    assert result["status"] == "skipped"
    assert result["rows_written"] == 0
    assert result["session_coverage"]["row_count"] == 60_736


def test_sector_members_sync_force_refreshes_fresh_members(monkeypatch):
    observed_at = datetime(2026, 7, 20, 11, 30, tzinfo=timezone.utc)
    sector_rows = [
        {
            "id": "BK0001",
            "type": "concept",
            "name": "Fresh",
            "members_refreshed_at": observed_at - timedelta(hours=1),
        }
    ]
    remote_calls: list[str] = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, **kwargs):
            del kwargs
            remote_calls.append(sector_id)
            return {
                "items": [
                    {
                        "vt_symbol": "600000.SSE",
                        "symbol": "600000",
                        "exchange": "SSE",
                        "source": "eastmoney.push2.board",
                    }
                ],
                "total": 1,
                "source": "eastmoney.push2.board",
            }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return sector_rows

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_load_sector_rows_with_member_freshness",
        lambda: sector_rows,
        raising=False,
    )
    monkeypatch.setattr(
        svc,
        "_load_cached_sector_memberships",
        lambda sector_ids: pytest.fail(f"unexpected cached load: {sector_ids}"),
        raising=False,
    )
    monkeypatch.setattr(svc, "_now_china", lambda: observed_at)
    monkeypatch.setattr(svc, "_upsert_sector_memberships", lambda sector_id, items: len(items))
    monkeypatch.setattr(
        svc,
        "_save_low_suction_forward_membership_capture",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(svc, "_delete_sector_memberships", lambda sector_ids: 0)

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_sector_members({"page_size": 50, "refresh_days": 0})

    assert remote_calls == ["BK0001"]
    assert result["requested_sector_count"] == 1
    assert result["refreshed_sector_count"] == 1
    assert result["reused_sector_count"] == 0


def test_sector_members_provider_failure_removes_only_the_failed_sector(monkeypatch):
    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kwargs):
            del page, page_size, kwargs
            if sector_id == "BK0002":
                raise TimeoutError("provider timeout")
            return {
                "items": [{"symbol": "000001", "exchange": "SZSE"}],
                "total": 1,
            }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {"id": "BK0001", "type": "concept", "name": "A"},
                {"id": "BK0002", "type": "concept", "name": "B"},
            ]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_upsert_sector_memberships",
        lambda sector_id, items: len(items),
    )
    removed: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        svc,
        "_delete_sector_memberships",
        lambda sector_ids: removed.append(tuple(sector_ids)) or 1,
        raising=False,
    )

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_sector_members({"page_size": 50})

    assert result["excluded_sector_ids"] == ["BK0002"]
    assert result["excluded_sector_count"] == 1
    assert removed == [("BK0002",)]


def test_sector_members_timeout_cannot_write_back_after_exclusion(monkeypatch):
    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kwargs):
            del page, page_size, kwargs
            return {
                "items": [{"symbol": "000001", "exchange": "SZSE"}],
                "total": 1,
            }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {"id": "BK0001", "type": "concept", "name": "late"},
                {"id": "BK0002", "type": "concept", "name": "ready"},
            ]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    def finish_timed_out_worker_late(fn, items, *, on_timeout, **kwargs):
        del kwargs
        on_timeout(items[0])
        fn(items[0])
        fn(items[1])

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_bounded_parallel_map", finish_timed_out_worker_late)
    monkeypatch.setattr(
        svc,
        "_save_low_suction_forward_membership_capture",
        lambda **kwargs: None,
    )
    upserted: list[str] = []
    monkeypatch.setattr(
        svc,
        "_upsert_sector_memberships",
        lambda sector_id, items: upserted.append(sector_id) or len(items),
    )
    removed: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        svc,
        "_delete_sector_memberships",
        lambda sector_ids: removed.append(tuple(sector_ids)) or 1,
    )

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=2,
    )._run_sync_sector_members({"page_size": 50})

    assert upserted == ["BK0002"]
    assert result["excluded_sector_ids"] == ["BK0001"]
    assert removed == [("BK0001",)]


def test_report_failures_save_low_suction_scope_and_are_removed_from_shared_capture(
    monkeypatch,
):
    saved = []
    removed: list[tuple[str, ...]] = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kwargs):
            del page, page_size, kwargs
            if sector_id in {"BK1677", "BK1678", "BK1679"}:
                raise TimeoutError("provider timeout")
            return {
                "items": [
                    {
                        "vt_symbol": "600000.SSE",
                        "symbol": "600000",
                        "exchange": "SSE",
                        "source": "eastmoney.push2.board",
                    }
                ],
                "total": 1,
                "source": "eastmoney.push2.board",
            }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {"id": "BK1677", "type": "theme", "name": "报告A"},
                {"id": "BK1678", "type": "theme", "name": "报告B"},
                {"id": "BK1679", "type": "theme", "name": "报告C"},
                {"id": "BK9000", "type": "theme", "name": "未分类题材"},
            ]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_upsert_sector_memberships",
        lambda sector_id, items: len(items),
    )
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 7, 16),
    )
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: datetime(2026, 7, 16, 11, 8, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        svc.forward_membership_repository,
        "save_forward_membership_capture",
        lambda capture: saved.append(capture) or len(capture.records),
    )
    monkeypatch.setattr(
        svc,
        "_delete_sector_memberships",
        lambda sector_ids: removed.append(tuple(sector_ids)) or 3,
        raising=False,
    )

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_sector_members({"page_size": 50})

    assert len(saved) == 1
    assert saved[0].catalog_scope.complete is False
    assert saved[0].tradable_scope.complete is True
    assert [record.sector_id for record in saved[0].records] == ["BK9000"]
    assert result["excluded_sector_ids"] == ["BK1677", "BK1678", "BK1679"]
    assert removed == [("BK1677", "BK1678", "BK1679")]


def test_unlabelled_failure_saves_only_a_rejected_catalog_capture(monkeypatch):
    saved = []

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kwargs):
            del sector_id, page, page_size, kwargs
            raise TimeoutError("provider timeout")

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": "BK9999", "type": "theme", "name": "未分类题材"}]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        lambda: date(2026, 7, 16),
    )
    monkeypatch.setattr(
        svc,
        "_now_china",
        lambda: datetime(2026, 7, 16, 11, 8, tzinfo=timezone.utc),
    )
    monkeypatch.setattr(
        svc.forward_membership_repository,
        "save_forward_membership_capture",
        lambda capture: saved.append(capture) or 0,
    )

    with pytest.raises(svc.DataSyncError, match="BK9999"):
        svc.DataSyncRunner(
            adapter=FakeAdapter(),
            concurrency=1,
        )._run_sync_sector_members({"page_size": 50})

    assert len(saved) == 1
    assert saved[0].tradable_scope.complete is False
    assert saved[0].records == ()


def test_sector_member_capture_rejects_short_pagination() -> None:
    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kwargs):
            del sector_id, page_size, kwargs
            if page == 1:
                return {
                    "items": [
                        {
                            "vt_symbol": "600000.SSE",
                            "source": "eastmoney.push2.board",
                        }
                    ],
                    "total": 2,
                    "source": "eastmoney.push2.board",
                }
            return {
                "items": [],
                "total": 2,
                "source": "eastmoney.push2.board",
            }

    with pytest.raises(svc.DataSyncError, match="pagination incomplete"):
        svc._fetch_sector_stock_capture(FakeAdapter(), "BK9000", 50)


def test_sector_member_capture_rejects_duplicate_pages() -> None:
    member = {
        "vt_symbol": "600000.SSE",
        "source": "eastmoney.push2.board",
    }

    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=1, **kwargs):
            del sector_id, page, page_size, kwargs
            return {
                "items": [member],
                "total": 2,
                "source": "eastmoney.push2.board",
            }

    with pytest.raises(svc.DataSyncError, match="duplicate member"):
        svc._fetch_sector_stock_capture(FakeAdapter(), "BK9000", 1)


def test_low_suction_capture_error_does_not_change_shared_sync_semantics(
    monkeypatch,
) -> None:
    def fail_reliable_date():
        raise RuntimeError("database temporarily unavailable")

    monkeypatch.setattr(
        svc,
        "_latest_complete_daily_date_for_research",
        fail_reliable_date,
    )

    assert svc._save_low_suction_forward_membership_capture(
        sector_rows=[{"id": "BK9000", "name": "题材", "type": "theme"}],
        members_by_sector={},
        failed_sector_ids=("BK9000",),
        observed_at=datetime(2026, 7, 16, 11, 8, tzinfo=timezone.utc),
    ) is None


def test_sector_members_empty_response_is_incomplete(monkeypatch):
    class FakeAdapter:
        def sector_stocks(self, sector_id, page=1, page_size=50, **kwargs):
            del sector_id, page, page_size, kwargs
            return {"items": [], "total": 0}

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": "BK0001", "type": "concept", "name": "A"}]

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    with pytest.raises(svc.DataSyncError, match="BK0001"):
        svc.DataSyncRunner(
            adapter=FakeAdapter(),
            concurrency=1,
        )._run_sync_sector_members({"page_size": 50})


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
    owner_thread_id = get_ident()

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, stmt):
            if get_ident() != owner_thread_id:
                return FakeResult()
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
    assert not [sql for sql in executed if sql.startswith("SELECT")]
    insert_sql = [sql for sql in executed if sql.startswith("INSERT INTO sector_memberships")]
    assert len(insert_sql) == 1
    assert "ON CONFLICT (sector_id, vt_symbol) DO UPDATE" in insert_sql[0]
    delete_sql = [sql for sql in executed if sql.startswith("DELETE FROM sector_memberships")]
    assert delete_sql
    assert "sector_memberships.sector_id = 'BK0001'" in delete_sql[-1]
    assert "sector_memberships.vt_symbol NOT IN ('000001.SSE', '000002.SZSE')" in delete_sql[-1]


def test_upsert_sector_memberships_bounds_batch_size(monkeypatch):
    statements: list[object] = []

    class FakeSession:
        def execute(self, statement):
            statements.append(statement)
            return object()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_sector_memberships(
        "BK0001",
        [
            {
                "symbol": f"{index:06d}",
                "exchange": "SSE",
                "name": f"S{index}",
            }
            for index in range(svc.SECTOR_MEMBERSHIP_UPSERT_BATCH_SIZE + 1)
        ],
    )

    assert written == svc.SECTOR_MEMBERSHIP_UPSERT_BATCH_SIZE + 1
    assert sum(bool(getattr(statement, "is_insert", False)) for statement in statements) == 2
    assert sum(bool(getattr(statement, "is_delete", False)) for statement in statements) == 1


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


def test_scheduled_sector_daily_sync_skips_complete_session(monkeypatch):
    sector_rows = [
        {"id": f"BK{index:04d}", "type": "concept", "name": "概念"}
        for index in range(5)
    ]

    class FakeAdapter:
        def sector_daily_bars(self, *args, **kwargs):
            del args, kwargs
            pytest.fail("complete sector session must not be fetched again")

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return sector_rows

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "_completed_sector_daily_session_coverage",
        lambda _sector_ids, _min_coverage_ratio: {
            "status": "complete",
            "target_trade_date": "2026-07-20",
            "sector_count": 5,
            "min_sector_count": 4,
            "expected_sector_count": 5,
        },
        raising=False,
    )
    monkeypatch.setattr(
        svc.market_cache,
        "clear",
        lambda: pytest.fail("skip path must not clear the shared market cache"),
    )

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=1,
    )._run_sync_sector_daily_bars(
        {
            "limit": 30,
            "sector_types": ["concept", "theme"],
            "skip_complete_session": True,
        }
    )

    assert result == {
        "status": "skipped",
        "rows_read": 0,
        "rows_written": 0,
        "session_coverage": {
            "status": "complete",
            "target_trade_date": "2026-07-20",
            "sector_count": 5,
            "min_sector_count": 4,
            "expected_sector_count": 5,
        },
        "message": "2026-07-20 板块日线已完整覆盖 5/4 个，跳过重复同步",
    }


def test_completed_sector_daily_session_uses_job_coverage_ratio(monkeypatch):
    class FakeResult:
        def scalar(self):
            return 495

    class FakeSession:
        def execute(self, statement):
            del statement
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(
        svc,
        "completed_daily_bar_cutoff",
        lambda _at: date(2026, 7, 20),
    )

    result = svc._completed_sector_daily_session_coverage(
        [f"BK{index:04d}" for index in range(498)],
        0.8,
    )

    assert result == {
        "status": "complete",
        "target_trade_date": "2026-07-20",
        "sector_count": 495,
        "min_sector_count": int(498 * 0.8),
        "expected_sector_count": 498,
    }


def test_sector_daily_bars_sync_filters_requested_sector_types(monkeypatch):
    seen: list[tuple[str, str, int]] = []

    class FakeAdapter:
        def sector_daily_bars(self, sector_id, board_type=None, limit=250):
            seen.append((sector_id, board_type, limit))
            return {
                "items": [{"trade_date": "2026-06-23"}],
                "source": svc.CANONICAL_SECTOR_DAILY_SOURCE,
            }

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [
                {"id": "BK0001", "type": "concept", "name": "C1"},
                {"id": "BK0002", "type": "theme", "name": "T1"},
                {"id": "BK0003", "type": "industry", "name": "I1"},
            ]

    class FakeSession:
        def execute(self, stmt):
            return FakeResult()

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)
    monkeypatch.setattr(svc, "_upsert_sector_daily_bars", lambda *a, **k: 1)

    result = svc.DataSyncRunner(
        adapter=FakeAdapter(),
        concurrency=2,
    )._run_sync_sector_daily_bars(
        {"limit": 800, "sector_types": ["concept", "theme"]}
    )

    assert {(sector_id, sector_type) for sector_id, sector_type, _ in seen} == {
        ("BK0001", "concept"),
        ("BK0002", "theme"),
    }
    assert {limit for _, _, limit in seen} == {800}
    assert result["rows_read"] == 2
    assert result["rows_written"] == 2


def test_upsert_daily_bars_batches_and_deduplicates_dates(monkeypatch):
    statements: list[Any] = []

    class FakeSession:
        def execute(self, statement):
            statements.append(statement)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(svc, "session_scope", fake_session_scope)

    written = svc._upsert_daily_bars(
        "600000",
        "SSE",
        [
            {"trade_date": "2026-07-10", "open": 10, "close": 11, "high": 12, "low": 9},
            {"trade_date": "2026-07-10", "open": 10, "close": 12, "high": 13, "low": 9},
            {"trade_date": "invalid", "open": 1, "close": 1, "high": 1, "low": 1},
        ],
    )

    assert written == 1
    assert len(statements) == 1
    compiled = statements[0].compile()
    assert "ON CONFLICT (vt_symbol, trade_date) DO UPDATE" in str(compiled)
    assert compiled.params["vt_symbol_m0"] == "600000.SSE"
    assert compiled.params["trade_date_m0"] == date(2026, 7, 10)
    assert compiled.params["close_price_m0"] == 12.0
    assert not any(key.endswith("_m1") for key in compiled.params)


def test_upsert_sector_daily_bars_prunes_old_sources_for_sector(monkeypatch):
    executed: list[object] = []

    class FakeResult:
        def first(self):
            return None

    class FakeSession:
        def execute(self, stmt):
            executed.append(stmt)
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
            {
                "trade_date": "2026-06-26",
                "open": 2,
                "close": 9,
                "high": 9,
                "low": 2,
                "raw": {
                    "source_detail": "eastmoney.board_quote_daily",
                    "source_timestamp": "2026-06-26T15:39:32+08:00",
                },
            },
        ],
        svc.CANONICAL_SECTOR_DAILY_SOURCE,
    )

    assert written == 2
    delete_sql = [
        str(stmt.compile(compile_kwargs={"literal_binds": True}))
        for stmt in executed
        if getattr(stmt, "is_delete", False)
    ]
    assert delete_sql
    sql = delete_sql[0]
    assert "sector_daily_bars.sector_id = 'BK0459'" in sql
    assert "sector_daily_bars.source != 'eastmoney.board_kline'" in sql
    inserts = [stmt for stmt in executed if getattr(stmt, "is_insert", False)]
    assert len(inserts) == 1
    compiled = inserts[0].compile()
    assert "ON CONFLICT (sector_id, trade_date) DO UPDATE" in str(compiled)
    assert compiled.params["close_price_m1"] == 9.0
    assert compiled.params["raw_m1"] == {
        "source_detail": "eastmoney.board_quote_daily",
        "source_timestamp": "2026-06-26T15:39:32+08:00",
    }


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



def test_due_low_suction_scan_runs_in_a_background_slot(monkeypatch) -> None:
    import threading

    scan_started = threading.Event()
    scan_release = threading.Event()
    scan_finished = threading.Event()
    scan_threads: list[str] = []
    now = datetime(2026, 7, 20, 10, 0, tzinfo=timezone(timedelta(hours=8)))
    schedules = [
        {
            "id": "low_suction_live_scan",
            "cron": "* 9-15 * * 1-5",
            "action": "low_suction_live_scan",
            "last_started_at": None,
        }
    ]

    def refresh_low_suction():
        scan_threads.append(threading.current_thread().name)
        scan_started.set()
        assert scan_release.wait(timeout=2)
        scan_finished.set()
        return {
            "status": "ok",
            "trend": {"total": 2},
            "oversold": {"total": 3},
        }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", False)
    monkeypatch.setattr(svc, "_load_batch_schedules", lambda: schedules)
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(svc, "_touch_schedule", lambda *args, **kwargs: None)
    monkeypatch.setattr(svc, "refresh_live_recommendations", refresh_low_suction)

    try:
        svc._run_scheduled_jobs()

        assert scan_started.wait(timeout=1)
        assert scan_threads == ["low-suction-live-scan"]
        svc._run_scheduled_jobs()
        assert scan_threads == ["low-suction-live-scan"]
    finally:
        scan_release.set()
        assert scan_finished.wait(timeout=2)


def test_tail_final_scan_bypasses_minute_throttle(monkeypatch) -> None:
    now = datetime(2026, 7, 20, 15, 1, tzinfo=timezone(timedelta(hours=8)))
    started: list[dict[str, object]] = []
    schedule = {
        "id": "low_suction_live_scan",
        "cron": "* 9-15 * * 1-5",
        "action": "low_suction_live_scan",
        "last_started_at": now - timedelta(seconds=1),
    }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", False)
    monkeypatch.setattr(svc, "_low_suction_tail_final_attempted_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_pending_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_retry_after", None)
    monkeypatch.setattr(svc, "_load_batch_schedules", lambda: [schedule])
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_start_low_suction_live_scan_schedule",
        lambda row, **kwargs: started.append({"row": row, **kwargs}) or True,
    )

    svc._run_scheduled_jobs()

    assert started == [
        {
            "row": schedule,
            "force_tail_final": True,
            "tail_final_date": now.date(),
        }
    ]


def test_tail_final_scan_queues_after_the_previous_minute_finishes(monkeypatch) -> None:
    now = datetime(2026, 7, 20, 15, 1, tzinfo=timezone(timedelta(hours=8)))
    schedule = {
        "id": "low_suction_live_scan",
        "cron": "* 9-15 * * 1-5",
        "action": "low_suction_live_scan",
    }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", True)
    monkeypatch.setattr(svc, "_low_suction_tail_final_attempted_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_pending_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_retry_after", None)
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(svc, "_run_schedule_action", lambda *_args, **_kwargs: None)

    assert svc._request_low_suction_tail_final_scan(schedule, now) is False
    assert svc._low_suction_tail_final_pending_date == now.date()

    svc._run_low_suction_live_scan_schedule(schedule)

    assert svc._low_suction_tail_final_pending_date == now.date()


def test_failed_tail_final_scan_is_requeued_within_the_retry_window(monkeypatch) -> None:
    now = datetime(2026, 7, 20, 15, 10, tzinfo=timezone(timedelta(hours=8)))
    schedule = {
        "id": "low_suction_live_scan",
        "cron": "* 9-15 * * 1-5",
        "action": "low_suction_live_scan",
    }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", True)
    monkeypatch.setattr(svc, "_low_suction_tail_final_attempted_date", now.date())
    monkeypatch.setattr(svc, "_low_suction_tail_final_pending_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_retry_after", None)
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(svc, "_run_schedule_action", lambda *_args, **_kwargs: None)
    svc._run_low_suction_live_scan_schedule(schedule, force_tail_final=True)

    assert svc._low_suction_tail_final_attempted_date is None
    assert svc._low_suction_tail_final_pending_date == now.date()
    assert svc._low_suction_tail_final_retry_after == now + timedelta(seconds=60)


def test_tail_final_exception_is_requeued_within_the_retry_window(monkeypatch) -> None:
    now = datetime(2026, 7, 20, 15, 10, tzinfo=timezone(timedelta(hours=8)))
    schedule = {
        "id": "low_suction_live_scan",
        "cron": "* 9-15 * * 1-5",
        "action": "low_suction_live_scan",
    }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", True)
    monkeypatch.setattr(svc, "_low_suction_tail_final_attempted_date", now.date())
    monkeypatch.setattr(svc, "_low_suction_tail_final_pending_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_retry_after", None)
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_run_schedule_action",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(RuntimeError, match="boom"):
        svc._run_low_suction_live_scan_schedule(schedule, force_tail_final=True)

    assert svc._low_suction_tail_final_attempted_date is None
    assert svc._low_suction_tail_final_pending_date == now.date()
    assert svc._low_suction_tail_final_retry_after == now + timedelta(seconds=60)


def test_tail_final_retry_waits_for_the_live_scan_interval(monkeypatch) -> None:
    now = datetime(2026, 7, 20, 15, 10, tzinfo=timezone(timedelta(hours=8)))
    started: list[dict[str, object]] = []
    schedule = {
        "id": "low_suction_live_scan",
        "cron": "* 9-15 * * 1-5",
        "action": "low_suction_live_scan",
    }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", False)
    monkeypatch.setattr(svc, "_low_suction_tail_final_attempted_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_pending_date", now.date())
    monkeypatch.setattr(
        svc,
        "_low_suction_tail_final_retry_after",
        now + timedelta(seconds=60),
    )
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc,
        "_run_low_suction_live_scan_schedule",
        lambda *_args: None,
    )

    assert svc._request_low_suction_tail_final_scan(schedule, now) is False

    ready_at = now + timedelta(seconds=60)
    monkeypatch.setattr(svc, "_now_china", lambda: ready_at)
    monkeypatch.setattr(
        svc,
        "_run_low_suction_live_scan_schedule",
        lambda row, force_tail_final: started.append(
            {"row": row, "force_tail_final": force_tail_final}
        ),
    )

    assert svc._request_low_suction_tail_final_scan(schedule, ready_at) is True
    assert started == [{"row": schedule, "force_tail_final": True}]


def test_tail_final_thread_start_failure_waits_for_the_live_scan_interval(
    monkeypatch,
) -> None:
    now = datetime(2026, 7, 20, 15, 10, tzinfo=timezone(timedelta(hours=8)))
    schedule = {
        "id": "low_suction_live_scan",
        "cron": "* 9-15 * * 1-5",
        "action": "low_suction_live_scan",
    }

    monkeypatch.setattr(svc, "_low_suction_schedule_running", False)
    monkeypatch.setattr(svc, "_low_suction_tail_final_attempted_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_pending_date", None)
    monkeypatch.setattr(svc, "_low_suction_tail_final_retry_after", None)
    monkeypatch.setattr(svc, "_now_china", lambda: now)
    monkeypatch.setattr(
        svc.threading.Thread,
        "start",
        lambda _self: (_ for _ in ()).throw(RuntimeError("thread unavailable")),
    )

    with pytest.raises(RuntimeError, match="thread unavailable"):
        svc._start_low_suction_live_scan_schedule(
            schedule,
            force_tail_final=True,
            tail_final_date=now.date(),
        )

    assert svc._low_suction_tail_final_attempted_date is None
    assert svc._low_suction_tail_final_pending_date == now.date()
    assert svc._low_suction_tail_final_retry_after == now + timedelta(seconds=60)


def test_low_suction_scan_lock_contention_is_reported_as_skipped(monkeypatch) -> None:
    touched: list[dict[str, Any]] = []
    monkeypatch.setattr(
        svc,
        "refresh_live_recommendations",
        lambda: (_ for _ in ()).throw(svc.LiveScanAlreadyRunningError("busy")),
    )
    monkeypatch.setattr(
        svc,
        "_touch_schedule",
        lambda _schedule_id, **fields: touched.append(fields),
    )

    result = svc._run_schedule_action(
        {"id": "low_suction_live_scan", "action": "low_suction_live_scan"}
    )

    assert result == {"status": "skipped", "message": "busy"}
    assert touched[-1]["last_status"] == "skipped"


def test_scheduler_catches_up_missed_default_schedule(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "eod_batch"})
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [
            {
                "id": "eod_1900",
                "cron": "0 19 * * 1-5",
                "enabled": True,
                "action": "sync",
                "job_ids": ["sync_stock_daily_bars"],
                "concurrency": 8,
                "last_started_at": dt.datetime(2026, 7, 8, 19, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))),
            }
        ],
    )
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 7, 9, 19, 20, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert triggered
    assert triggered[0]["schedule_id"] == "eod_1900"


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


def test_schema_bootstrap_only_recovers_for_scheduler_owner(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    monkeypatch.setattr(svc, "get_engine", lambda: object())
    monkeypatch.setattr(
        svc.schema,
        "ensure_schema_once",
        lambda _engine: calls.append("schema"),
    )
    monkeypatch.setattr(
        svc,
        "seed_default_registry",
        lambda: calls.append("registry"),
    )
    monkeypatch.setattr(
        svc,
        "mark_interrupted_runs",
        lambda: calls.append("recover"),
    )

    svc.ensure_sync_schema(recover_interrupted=False)
    assert calls == ["schema", "registry"]

    calls.clear()
    svc.ensure_sync_schema(recover_interrupted=True)
    assert calls == ["schema", "registry", "recover"]


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


def test_default_schedules_exclude_legacy_quant_actions():
    schedules = {row["id"]: row for row in svc.DEFAULT_BATCH_SCHEDULES}

    assert "tail_quant_1430" not in schedules
    all_jobs = {job for row in schedules.values() for job in row["job_ids"]}
    assert "eod_quant_research" not in all_jobs
    assert schedules["low_suction_live_scan"]["enabled"] is True
    assert set(svc.RETIRED_DEFAULT_JOB_IDS).isdisjoint(all_jobs)


def test_schedule_actions_reject_removed_quant_actions():
    with pytest.raises(svc.DataSyncError):
        svc._schedule_action({"action": "quant_research"})
    with pytest.raises(svc.DataSyncError):
        svc._schedule_action({"action": "tail_preview"})
