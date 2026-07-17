# AlphaAgent Low-Suction Stock History Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Extend the shared full-market stock-daily bootstrap from the old 600-session floor to a measured 750 reliable sessions so low-suction research can satisfy both 720 trading days and 1,095 calendar days without changing limit-up strategy behavior.

**Architecture:** Keep the normal `sync_stock_daily_bars` job incremental with its 250-row default. Only an untargeted full-market incremental run whose reliable cross-section is below 750 sessions switches to a bounded 800-row bootstrap; existing per-symbol upserts and incomplete-latest-session cleanup remain unchanged. The job reports before/after reliable coverage, while the independent low-suction audit remains the authority that decides whether the strict gate clears.

**Tech Stack:** Python 3.11+, Tencent full K-line endpoint through `AkShareAdapter`, SQLAlchemy Core, PostgreSQL 16, pytest, Docker Compose.

---

## Verified Baseline

- The strict low-suction contract requires at least 720 reliable trading days and a 1,095-day calendar span.
- Current stock coverage is 603 reliable dates from `2024-01-15` through `2026-07-15`, a 912-day span.
- The shared bootstrap currently stops at `STOCK_DAILY_HISTORY_TARGET_DAYS = 600` and requests 700 rows, so a 603-day database is incorrectly considered ready for ordinary incremental refresh.
- On the local trading calendar, 720 sessions span only 1,086 days. The first count satisfying both strict gates is 727 sessions; 750 sessions span 1,132 days and provide a 23-session buffer.
- Read-only live checks for `600000.SSE`, `000001.SZSE`, and `002432.SZSE` each returned 800 rows from `2023-03-28` through `2026-07-16` via `tencent.stock_kline_full` in 0.21-0.24 seconds.
- Tencent bounds one request at 3,000 rows, so an 800-row request stays within the existing provider contract.
- No Tushare token or historical concept-membership provider is configured. This plan clears only the stock-history gap; it cannot clear point-in-time membership or historical security status.

## Fixed Boundary

```python
STOCK_DAILY_HISTORY_TARGET_DAYS = 750
STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT = 800
MIN_COMPLETE_DAILY_SYMBOL_COUNT = 3_000
```

- Do not change the normal job default `{"limit": 250}`.
- Do not import low-suction strategy modules into shared data sync.
- Targeted symbol runs, limited-stock runs, and explicit non-incremental runs never trigger the automatic full-market bootstrap.
- Provider failures preserve existing rows. A partial run reports `target_achieved=False`; it must not claim strict readiness or lower the gate.
- Current-day partial cross-sections remain subject to the existing cleanup rule.
- Do not alter limit-up candidates, strategy versions, cash ledgers, or performance artifacts.

### Task 1: Lock The Measured Bootstrap Contract

**Files:**
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `alphaagent/server/services/data_sync.py`

- [x] **Step 1: Write failing constant and boundary tests**

```python
def test_stock_daily_history_bootstrap_targets_strict_three_year_buffer() -> None:
    assert svc.STOCK_DAILY_HISTORY_TARGET_DAYS == 750
    assert svc.STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT == 800


def test_stock_daily_history_bootstrap_plan_requires_749_days(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_reliable_stock_daily_trade_days", lambda: 749)

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


def test_stock_daily_history_bootstrap_plan_accepts_750_days(monkeypatch) -> None:
    monkeypatch.setattr(svc, "_reliable_stock_daily_trade_days", lambda: 750)

    plan = svc._stock_daily_history_bootstrap_plan(
        symbols=[],
        stock_limit=0,
        total_stocks=5_500,
        incremental=True,
    )

    assert plan["required"] is False
```

- [x] **Step 2: Run the focused tests and verify the old constants fail**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_data_sync_schedule.py \
  -k "stock_daily_history_bootstrap" -q
```

Expected: the 750/800 assertions fail against the old 600/700 implementation.

- [x] **Step 3: Change only the shared bootstrap constants**

```python
STOCK_DAILY_HISTORY_TARGET_DAYS = 750
STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT = 800
```

Keep `DEFAULT_JOBS.sync_stock_daily_bars.default_params["limit"] == 250` and every targeting guard unchanged.

- [x] **Step 4: Run the focused tests**

Run the command from Step 2. Expected: all selected tests pass.

### Task 2: Report Whether The Real Bootstrap Reached Its Target

**Files:**
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `alphaagent/server/services/data_sync.py`

- [x] **Step 1: Write a failing after-coverage result test**

Extend `test_stock_daily_sync_bootstraps_underfilled_full_market_history` so its fake bootstrap uses target 750 and request limit 800. Monkeypatch `_reliable_stock_daily_trade_days` to return 756 after the fake writes, then assert:

```python
assert result["history_bootstrap"] == {
    "performed": True,
    "reliable_trade_days_before": 603,
    "reliable_trade_days_after": 756,
    "target_trade_days": 750,
    "request_limit": 800,
    "target_achieved": True,
}
```

Add a second test returning 744 after the run and assert `target_achieved is False`. The sync must still return its row counts and preserve the imported partial data.

- [x] **Step 2: Run the two runner tests and verify the after fields are absent**

```bash
uv run --group server pytest \
  tests/alphaagent/test_data_sync_schedule.py \
  -k "bootstraps_underfilled or bootstrap_reports_unmet" -q
```

Expected: failure because `reliable_trade_days_after` and `target_achieved` are not emitted.

- [x] **Step 3: Measure post-run coverage only for an automatic bootstrap**

After all per-symbol work and latest-date cleanup complete:

```python
if history_bootstrap["required"]:
    reliable_days_after = _reliable_stock_daily_trade_days()
    result["history_bootstrap"] = {
        "performed": True,
        "reliable_trade_days_before": history_bootstrap[
            "reliable_trade_days_before"
        ],
        "reliable_trade_days_after": reliable_days_after,
        "target_trade_days": history_bootstrap["target_trade_days"],
        "request_limit": limit,
        "target_achieved": (
            reliable_days_after >= history_bootstrap["target_trade_days"]
        ),
    }
```

Do not run the extra coverage query for ordinary incremental or targeted syncs.

- [x] **Step 4: Run the full shared-sync regression**

```bash
uv run --group server pytest \
  tests/alphaagent/test_akshare_adapter.py \
  tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: all tests pass with the existing provider fallbacks, incremental refresh, and partial-latest cleanup unchanged.

### Task 2.5: Exclude Intraday Daily Bars From Research

**Files:**
- Create: `alphaagent/server/services/completed_session.py`
- Create: `tests/alphaagent/test_completed_session.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `alphaagent/server/services/low_suction/repository.py`

- [x] **Step 1: Prove 720 sessions do not guarantee the calendar-span gate**

The local calendar showed 720 sessions span 1,086 days, 725 span 1,093, and the first
count satisfying 1,095 days is 727. This is why the buffered target remains 750.

- [x] **Step 2: Add a shared completed-session cutoff**

`completed_daily_bar_cutoff()` returns the prior calendar date before 15:05 Shanghai
time and the current date from 15:05 onward. It rejects naive datetimes. Database queries
still decide whether that date is a trading day and whether its cross-section is complete.

- [x] **Step 3: Apply the cutoff to every research daily-date query**

Shared latest-complete and reliable-history queries, low-suction stock coverage, and the
proxy reliable-date loader all filter `trade_date <= completed_cutoff`. Intraday raw rows
remain stored but the cleanup result labels them `intraday_retained` rather than complete.

- [x] **Step 4: Run cutoff, sync, and low-suction tests**

```bash
uv run --group server pytest tests/alphaagent/test_completed_session.py -q
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -k "stock_daily" -q
uv run --group server pytest tests/alphaagent/services/low_suction -q
```

Expected: all tests pass and a midday current-session row cannot become the research
cutoff solely because its symbol count exceeds 3,000.

### Task 3: Execute And Audit The Full-market Backfill

**Files:**
- Create: `memory/06_backtests/low_suction_stock_history_backfill_20260716.md`
- Modify: `memory/06_backtests/low_suction_data_quality_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Rebuild and verify the API**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').status)"
```

Expected: HTTP 200.

- [x] **Step 2: Run the existing full-market sync entrypoint**

```bash
docker compose exec -T alphaagent-api python -c \
  "from alphaagent.server.services.data_sync import DataSyncRunner; print(DataSyncRunner(concurrency=8)._run_sync_stock_daily_bars({'limit': 250, 'incremental': True}))"
```

Because the measured pre-run coverage is 603 days, the runner must automatically use `incremental=False` and `limit=800`. Record rows read/written, timed-out symbols, before/after coverage, and `target_achieved`. Do not manually force a different start date or delete old rows.

- [x] **Step 3: Re-run the strict low-suction audit**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json
```

Expected stock result: at least 750 reliable trade days, at least 1,095 calendar days, and `stock_daily_history` absent from `blocking_gaps`. If the provider result falls short, record the actual gap and keep the blocker.

- [x] **Step 4: Preserve the remaining fail-closed decision**

Even after stock history qualifies, expected remaining blockers are:

```text
historical_concept_membership
historical_security_status
candidate_minute_paths
```

`formal_metrics` must remain `null`.

Actual result: the automatic bootstrap wrote 4,523,557 rows and increased reliable
coverage from 603 to 800 sessions with `target_achieved=True`. The completed-session
audit accepted 799 sessions through 2026-07-15 and excluded the retained 2026-07-16
intraday cross-section. Evidence: `memory/06_backtests/low_suction_stock_history_backfill_20260716.md`.

### Task 4: Record The Historical-membership Boundary

**Files:**
- Modify: `memory/06_backtests/low_suction_data_quality_20260716.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] Record that `stock_sector_membership_snapshots` currently has only three dates, `2026-07-13..2026-07-15`.
- [x] Record that the configured Tushare provider has no token and its existing importer is for Shenwan industry intervals, not point-in-time Eastmoney concept membership.
- [x] Keep current Eastmoney members at `membership_proxy`; do not backfill them across the expanded stock history.
- [x] Make the next research task the point-in-time concept source and eligible-theme taxonomy, not minute downloading or strategy tuning.

## Completion Boundary

This plan can remove `stock_daily_history` from the low-suction blockers using the existing shared provider. It cannot create historical concept members, strict historical security status, or formal performance. No strategy qualification or UI tab is allowed merely because stock and concept daily histories both qualify.
