"""Tests for the unified incremental batch-sync scheduler.

Covers the ``sync_batch_schedules`` table, default schedules, batch execution
(failure isolation / concurrency), incremental bar sync, and the
schedule-driven scheduler. Implementation plan:
requirements/alphaagent_unified_schedule_execution_plan.md
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from typing import Any

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
    assert {"tail_preview_14h", "tail_quant_1430", "eod_18h"}.issubset(ids)


def test_default_jobs_have_no_cron():
    # After dropping single-job schedules, every DEFAULT_JOBS entry has no cron.
    for job in svc.DEFAULT_JOBS:
        assert job.schedule_cron is None, f"{job.id} still has schedule_cron"


def test_intraday_schedule_contains_intraday_jobs():
    intraday = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "tail_preview_14h")
    assert intraday["action"] == "tail_preview"
    assert "sync_stock_minute_bars" in intraday["job_ids"]
    assert "sync_sector_fund_flows" in intraday["job_ids"]
    # Daily bars are not available at 14:00, so they must NOT be in the intraday slot.
    assert "sync_stock_daily_bars" not in intraday["job_ids"]


def test_tail_quant_schedule_triggers_quant_research():
    tail_quant = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "tail_quant_1430")
    assert tail_quant["action"] == "tail_preview"
    assert tail_quant["cron"] == "30 14 * * 1-5"
    assert "sync_stock_minute_bars" in tail_quant["job_ids"]
    assert "sync_sector_fund_flows" in tail_quant["job_ids"]
    assert "sync_stock_daily_bars" not in tail_quant["job_ids"]


def test_eod_schedule_has_daily_bars_and_lhb_last():
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_18h")
    assert eod["action"] == "sync"
    assert "sync_stock_daily_bars" in eod["job_ids"]
    assert "sync_index_daily_bars" in eod["job_ids"]
    assert svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID in eod["job_ids"]
    # LHB publishes after 18:00, so it must run after daily bars.
    assert eod["job_ids"].index("sync_stock_lhb_records") > eod["job_ids"].index("sync_stock_daily_bars")
    assert eod["job_ids"].index(svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID) > eod["job_ids"].index("sync_stock_daily_bars")
    assert eod["job_ids"].index("sync_index_daily_bars") > eod["job_ids"].index("sync_stock_daily_bars")
    assert eod["job_ids"].index(svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID) > eod["job_ids"].index("sync_index_daily_bars")


def test_eod_schedule_runs_quant_research_before_slow_enrichment_jobs():
    """候选生成应在基础数据(daily_bars+板块系列)就绪后立即跑,不等慢/晚 job(financial_quarterly/lhb/notices),
    以便候选在 daily_bars 完成后尽快出炉(约 18:15-18:20)。

    候选评分读 DB 已有财报评分(_load_financial_scores 按 as_of),不强依赖当次 financial_quarterly;
    财报季度更新,用前一日 DB 数据可接受。慢/晚 job 在候选之后跑,更新供下次候选使用。
    """
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_18h")
    jobs = eod["job_ids"]
    quant_idx = jobs.index(svc.EOD_QUANT_RESEARCH_BATCH_JOB_ID)
    # 候选硬依赖:日线 + 板块主线评分数据必须在候选之前
    assert jobs.index("sync_stock_daily_bars") < quant_idx
    assert jobs.index("sync_sector_period_scores") < quant_idx
    # 慢/晚增强 job 必须在候选之后,不阻塞候选出炉
    assert jobs.index("sync_stock_financial_quarterly") > quant_idx
    assert jobs.index("sync_stock_lhb_records") > quant_idx
    assert jobs.index("sync_stock_notices") > quant_idx


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
        "eod_18h": None,
    }
    recovered: list[str] = []

    monkeypatch.setattr(svc, "_load_recoverable_interrupted_schedule", lambda schedule_id: rows.get(schedule_id), raising=False)
    monkeypatch.setattr(svc, "_run_schedule_action", lambda row: recovered.append(row["id"]))

    svc._recover_interrupted_schedules(["tail_quant_1430", "eod_18h"])

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

    svc._queue_interrupted_schedule_recovery(["eod_18h", "tail_quant_1430"])
    svc.start_interrupted_schedule_recovery(delay_seconds=0)

    assert started == [(["eod_18h", "tail_quant_1430"], 0)]
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
        schedule_id="eod_18h",
    )
    assert captured["concurrency"] == 12
    assert captured["source"] == "schedule"
    assert captured["schedule_id"] == "eod_18h"
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


def test_tail_preview_schedule_appends_cache_job(monkeypatch):
    captured = {}

    def fake_start_sync_batch(**kwargs):
        captured.update(kwargs)
        return {"id": "tail_preview_batch"}

    monkeypatch.setattr(svc, "start_sync_batch", fake_start_sync_batch)

    result = svc._start_sync_schedule(
        {
            "id": "tail_preview_14h",
            "action": "tail_preview",
            "job_ids": ["sync_stock_list", "sync_stock_minute_bars"],
            "concurrency": 12,
        },
        source="manual",
    )

    assert result["id"] == "tail_preview_batch"
    assert captured["schedule_id"] == "tail_preview_14h"
    assert captured["job_ids"] == ["sync_stock_list", "sync_stock_minute_bars", svc.TAIL_PREVIEW_BATCH_JOB_ID]


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

    assert calls[0]["end"].isoformat() == "2026-06-18"
    assert calls[0]["candidate_limit"] == 20
    assert poll_count["n"] == 1
    assert result["rows_read"] == 2497
    assert result["rows_written"] == 100
    assert result["backtest_id"] == 191
    assert any(event.get("stage") == "完成" for event in progress_events)


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
        "strategy_version": "0.1.21",
        "trade_date": svc._parse_date("2026-06-18"),
        "candidate_count": 2502,
        "recommendation_count": 100,
        "message": "ready",
    }
    replay = {
        "id": 26,
        "status": "ready",
        "strategy_id": "mainline_dragon_pullback",
        "strategy_version": "0.1.21",
        "start_date": svc._parse_date("2025-03-26"),
        "end_date": svc._parse_date("2026-06-18"),
        "metrics": {"attempt_count": 121927},
    }
    backtests = [
        {
            "id": 195,
            "status": "succeeded",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.21",
            "start_date": svc._parse_date("2026-06-01"),
            "end_date": svc._parse_date("2026-06-18"),
            "params": {"symbols": ["603005.SSE"]},
            "metrics": {"total_return_pct": 12.3},
        },
        {
            "id": 194,
            "status": "succeeded",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.21",
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


def test_limit_up_pool_events_clear_empty_pool(monkeypatch):
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
    assert len(delete_sql) == 1
    assert "stock_events.event_type = 'limit_pool_zt'" in delete_sql[0]


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


# ── Task 8: scheduler drives batch schedules instead of per-job crons ─


def test_scheduler_triggers_matching_batch_schedule(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "x"})
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [{"id": "eod_18h", "cron": "0 18 * * 1-5", "enabled": True, "action": "sync", "job_ids": ["sync_stock_list"], "concurrency": 8, "last_started_at": None}],
    )
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 17, 18, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert triggered, "expected the matching schedule to trigger a batch"
    assert triggered[0]["job_ids"] == ["sync_stock_list"]
    assert triggered[0]["source"] == "schedule"
    assert triggered[0]["schedule_id"] == "eod_18h"


def test_scheduler_skips_weekend_for_weekday_cron(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "x"})
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [{"id": "eod_18h", "cron": "0 18 * * 1-5", "enabled": True, "action": "sync", "job_ids": ["sync_stock_list"], "concurrency": 8, "last_started_at": None}],
    )
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 20, 18, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

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
                "job_ids": ["sync_stock_list", "sync_stock_minute_bars"],
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
    assert triggered[0]["job_ids"] == ["sync_stock_list", "sync_stock_minute_bars", svc.TAIL_PREVIEW_BATCH_JOB_ID]


def test_scheduler_skips_non_matching_cron(monkeypatch):
    import datetime as dt

    triggered: list[dict[str, Any]] = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw))
    monkeypatch.setattr(
        svc,
        "_load_batch_schedules",
        lambda: [{"id": "eod_18h", "cron": "0 18 * * 1-5", "enabled": True, "action": "sync", "job_ids": ["sync_stock_list"], "concurrency": 8, "last_started_at": None}],
    )
    # now is 14:00, does not match the 18:00 cron
    monkeypatch.setattr(svc, "_now_china", lambda: dt.datetime(2026, 6, 17, 14, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))))

    svc._run_scheduled_jobs()

    assert not triggered


# ── Task 9: schedules API (CRUD + run) ─


def test_schedule_endpoints_crud(monkeypatch):
    from fastapi.testclient import TestClient

    from alphaagent.server.api import data_sync as data_sync_api
    from alphaagent.server.main import create_app

    monkeypatch.setattr(data_sync_api.service, "list_schedules", lambda: [{"id": "eod_18h", "name": "盘后同步"}])
    monkeypatch.setattr(data_sync_api.service, "create_schedule", lambda payload: {"id": "new_1", **payload})
    monkeypatch.setattr(data_sync_api.service, "update_schedule", lambda sid, payload: {"id": sid, **payload})
    monkeypatch.setattr(data_sync_api.service, "delete_schedule", lambda sid: {"id": sid, "deleted": True})
    monkeypatch.setattr(data_sync_api.service, "run_schedule_now", lambda sid: {"id": "batch_x", "schedule_id": sid})

    client = TestClient(create_app())

    resp = client.get("/api/data-sync/schedules")
    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "eod_18h"

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

    resp = client.post("/api/data-sync/schedules/eod_18h/run")
    assert resp.json()["data"]["schedule_id"] == "eod_18h"
