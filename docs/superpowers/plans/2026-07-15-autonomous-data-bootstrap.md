# Autonomous Market Data Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a fresh or underfilled AlphaAgent deployment autonomously backfill the historical inputs required by `/limit-up`, then rebuild the versioned history ledger without copying a database.

**Architecture:** Keep the existing unified EOD scheduler. The full-market daily-bar job detects an underfilled reliable history window and temporarily switches from incremental refresh to a bounded 700-bar bootstrap. The 21:30 chain runs the existing idempotent Tonghuashun evidence importer, bounded minute backfill, and a forced history rebuild when an upstream historical input changed.

**Tech Stack:** Python 3.11+, SQLAlchemy, PostgreSQL, pytest, AlphaAgent data-sync scheduler and limit-up services.

---

Repository policy forbids commits unless the user explicitly requests them, so this plan omits commit commands.

### Task 1: Reliable daily-history bootstrap

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`
- Test: `tests/alphaagent/test_data_health.py`

- [x] **Step 1: Write failing bootstrap tests**

Add a runner test proving that an underfilled full-universe incremental job calls the adapter with `limit=700` and `start_date=None`. Add controls proving that ready history and targeted jobs remain incremental.

```python
def test_stock_daily_sync_bootstraps_underfilled_full_market_history(monkeypatch):
    monkeypatch.setattr(svc, "_stock_daily_history_bootstrap_needed", lambda **_kwargs: True)
    # Run the fake adapter and assert limit=700, start_date=None.
```

- [x] **Step 2: Run the tests and confirm failure**

Run `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "stock_daily_sync_bootstraps_underfilled"`.

Expected: failure because the bootstrap helper and result metadata do not exist.

- [x] **Step 3: Implement the bounded bootstrap**

Add `STOCK_DAILY_HISTORY_TARGET_DAYS = 600`, `STOCK_DAILY_HISTORY_BOOTSTRAP_LIMIT = 700`, and `STOCK_DAILY_HISTORY_MIN_UNIVERSE = 3000`. Query the number of dates with at least 3,000 symbols. For a non-targeted full-market job below 600 reliable days, ignore existing per-symbol last dates for that run and request 700 bars. Return `history_bootstrap` metadata. Retain normal incremental behavior after reaching the target.

- [x] **Step 4: Expose longitudinal health**

Extend stock daily coverage with reliable history start/end/count, target days, and `history_depth_ready`. Make `_stock_daily_incomplete_health()` return `stale=True` when the latest date is fresh but historical depth is below 600.

- [x] **Step 5: Verify daily sync and health**

Run `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_data_health.py -q -k "stock_daily or daily_bars"`.

Expected: all selected tests pass.

### Task 2: Automatic THS evidence and rebuild invalidation

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] **Step 1: Write failing schedule tests**

Require `LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID` immediately before `sync_limit_up_event_minutes` in `eod_finalize_2130`. Assert that normal sync schedules accept that internal job.

- [x] **Step 2: Write failing forced-rebuild tests**

```python
def test_history_refresh_force_rebuilds_current_ledger(monkeypatch):
    result = history_service.refresh_history_if_needed(date(2026, 7, 10), force=True)
    assert result["status"] == "ready"
```

Also assert that `_run_limit_up_history_rebuild_batch_job(force=True)` forwards the flag.

- [x] **Step 3: Run the tests and confirm failure**

Run `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_limit_up_history.py -q -k "eod_finalize or ths_evidence or force_rebuild"`.

Expected: schedule and function-signature assertions fail.

- [x] **Step 4: Wire the importer and conditional rebuild**

Insert the existing `max_dates=252, only_missing=True` THS job into the 21:30 chain. Track whether daily bootstrap, THS import, or event-minute backfill wrote historical inputs. Pass that state to `_run_limit_up_history_rebuild_batch_job(force=...)`. Add a keyword-only `force=False` argument to `refresh_history_if_needed()` so existing callers keep their behavior.

- [x] **Step 5: Verify scheduler and history behavior**

Run `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_evidence_import.py -q`.

Expected: all tests pass.

### Task 3: Documentation and final checks

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/limit_up_production_local_parity_20260715.md`

- [x] **Step 1: Update current-state documentation**

Document the autonomous 600-day daily bootstrap, 252-day THS import, bounded minute backfill, and conditional ledger rebuild. Preserve the fact that missing Tick/L2 and forward evidence keep `simulation_eligible=false`.

- [x] **Step 2: Run focused regression checks**

```bash
uv run ruff check alphaagent/server/services/data_sync.py alphaagent/server/services/limit_up/history_service.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_data_health.py tests/alphaagent/test_limit_up_history.py
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_data_health.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_evidence_import.py -q
git diff --check
```

Expected: lint, tests, and whitespace checks pass.

- [x] **Step 3: Verify the local runtime contract**

Inspect `data_health()` and `DEFAULT_BATCH_SCHEDULES` in the API container. The health payload must expose the 600-day target, and the 21:30 schedule must order THS evidence before minute backfill and history rebuild.

Verified locally on 2026-07-16: 163 focused tests passed; the rebuilt API container reported 603/600 reliable daily dates with `history_depth_ready=true`; the persisted 21:30 schedule ordered THS evidence before event-minute backfill and history rebuild; the 5,878-stock full-market plan remained incremental.
