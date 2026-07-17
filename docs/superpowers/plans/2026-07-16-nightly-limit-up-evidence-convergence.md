# Nightly Limit-up Evidence Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing 19:00/21:30 incremental chain retry the close-time inputs used by limit-up recommendations and fetch exact D+1 14:30 prices for every persisted formal live recommendation.

**Architecture:** Keep the existing `sync_limit_up_exit_minutes` job and its TDX retry ledger. Add a compact read of persisted `actionable_recommendations`, map each signal date to the next trading date already present in local daily bars, and union those requests with the historical candidate pool before gap selection. Add only the inexpensive close-time fund-flow and limit-pool retries to the existing schedules; intraday concept frames and Tick/L2 remain intraday-only evidence.

**Tech Stack:** Python 3.11+, SQLAlchemy/PostgreSQL JSONB, AlphaAgent data-sync scheduler, pytest.

---

Repository policy forbids commits unless the user explicitly requests them. The shared worktree contains required user changes, so execution stays inline and touches only the files listed below.

### Task 1: Freeze the nightly contracts in tests

**Files:**
- Modify: `tests/alphaagent/test_limit_up_data_quality.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Add a failing live recommendation exit-request test**

Add a test in which two saved `actionable_recommendations` from one signal date map to the next locally available trading date, while an unfinished current date has no result-date request.

```python
monkeypatch.setattr(
    data_quality.live_repository,
    "load_actionable_recommendation_snapshots",
    lambda _version: live_rows,
)
monkeypatch.setattr(
    data_quality.live_repository,
    "list_daily_trade_dates",
    lambda: ["2026-07-16", "2026-07-17"],
)

assert data_quality._live_recommendation_exit_minute_requests() == [
    ("600000.SSE", date(2026, 7, 17)),
    ("600001.SSE", date(2026, 7, 17)),
]
```

- [x] **Step 2: Add failing schedule assertions**

Require `sync_stock_fund_flows` in both nightly chains. Require `sync_sector_fund_flows` and `sync_limit_up_pools` in the 21:30 retry chain, with fund flows before `sync_sector_period_scores` and the limit pool before historical evidence/rebuild.

- [x] **Step 3: Run the focused tests and verify failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_data_quality.py tests/alphaagent/test_data_sync_schedule.py -q -k "live_recommendation_exit or eod_schedule_runs_market or eod_finalize_schedule"
```

Expected: failures because the compact live repository read and expanded schedule contracts do not exist yet.

### Task 2: Include formal live recommendations in exact exit backfill

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_repository.py`
- Modify: `alphaagent/server/services/limit_up/data_quality.py`
- Test: `tests/alphaagent/test_limit_up_data_quality.py`

- [x] **Step 1: Add the compact repository projection**

Implement `load_actionable_recommendation_snapshots(strategy_version)` by selecting only `trade_date` and `recommendations.actionable_recommendations` from persisted `live_snapshot` rows. Do not load candidates, market context, or full recommendation payloads.

```python
actionable = schema.limit_up_signal_snapshots.c.recommendations[
    "actionable_recommendations"
].label("actionable_recommendations")
```

- [x] **Step 2: Derive only mature live exit requests**

Implement `_live_recommendation_exit_minute_requests()` using the local trading calendar. A signal is eligible only when `min(trade_date > signal_date)` already exists, so D-day nightly runs do not guess holidays or create future result dates.

- [x] **Step 3: Union historical and live request sets**

Keep `_scheduled_exit_minute_requests()` as the single caller contract and return the sorted union of history-candidate and live-recommendation pairs. Existing exact-14:30 coverage checks, 200-pair limit, scoped retry ledger, and TDX importer remain unchanged.

- [x] **Step 4: Run the focused data-quality tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_data_quality.py -q -k "scheduled_exit or live_recommendation_exit or exit_minute"
```

Expected: all selected tests pass.

### Task 3: Expand close-time incremental retries

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Add the 19:00 stock-flow retry**

Place `sync_stock_fund_flows` immediately after `sync_sector_fund_flows`, before daily bars and period scores.

- [x] **Step 2: Add the 21:30 close-input retries**

Place `sync_sector_fund_flows` and `sync_stock_fund_flows` before `sync_sector_period_scores`. Place `sync_limit_up_pools` before `sync_limit_up_ths_evidence`, event minutes, exit minutes, and history rebuild.

- [x] **Step 3: Run scheduler tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "intraday_schedule or eod_schedule or eod_finalize or exit_minute"
```

Expected: all selected tests pass and the intraday 15/30-second schedules remain unchanged.

### Task 4: Verify runtime and durable state

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/limit_up_intraday_concept_forward_pilot_20260716.md`

- [x] **Step 1: Run focused regression and static checks**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_data_quality.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_cash_backtest.py -q
uv run python -m compileall alphaagent/server/services/limit_up alphaagent/server/services/data_sync.py
uv run ruff check alphaagent/server/services/limit_up/live_repository.py alphaagent/server/services/limit_up/data_quality.py alphaagent/server/services/data_sync.py tests/alphaagent/test_limit_up_data_quality.py tests/alphaagent/test_data_sync_schedule.py
git diff --check
```

Expected: tests and compilation pass. Any pre-existing lint findings outside changed lines remain untouched and are reported separately.

- [x] **Step 2: Rebuild the API and reconcile schedules**

Run:

```bash
docker compose up -d --build alphaagent-api
docker compose ps alphaagent-api
```

The API startup lifespan calls `ensure_sync_schema()` before starting the scheduler. Do not invoke it
again from a second process while the API is running, because its interrupted-run recovery would mark
the live API process's active batch as stale. Expected: API is healthy and persisted
`eod_1900/eod_finalize_2130` rows match the new default job order.

- [x] **Step 3: Execute and inspect one incremental exit run**

Run the existing `sync_limit_up_exit_minutes` job through the service runner. Accept `ready`, provider failure, or truthful cooldown as runtime outcomes; never claim missing Tick/L2 has been backfilled.

- [x] **Step 4: Update current-state memory**

Record the schedule order, formal live recommendation coverage, exact exit coverage, provider cooldowns, and the explicit boundary that Tick/L2 cannot be reconstructed at night.
