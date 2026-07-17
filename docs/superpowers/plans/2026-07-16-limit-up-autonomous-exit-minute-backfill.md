# Limit-up Autonomous Exit Minute Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make AlphaAgent autonomously backfill exact D+1 14:30 minute prices for persisted limit-up candidates so a fresh deployment can converge toward the same cash backtest inputs without CSV files or database copies.

**Architecture:** Read only the versioned history candidate pools, reuse `scheduled_execution.extract_scheduled_orders()` to derive the exact candidate/result-date pairs consumed by the portfolio backtest, and query existing 14:30 bars before selecting retryable gaps. A dedicated TDX-backed sync job imports only the 14:30 bar, records scoped retry state, runs after signal-day minute backfill, and forces the existing history/cache refresh when rows are written.

**Tech Stack:** Python 3.11+, SQLAlchemy/PostgreSQL JSONB, pytdx, AlphaAgent data-sync scheduler, pytest.

---

Repository policy forbids commits unless the user explicitly requests them, so this plan omits commit steps. The current dirty workspace contains required uncommitted product changes; execution stays in the authorized shared workspace instead of creating a worktree that would omit them.

### Task 1: Derive persisted candidate exit requests

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_repository.py`
- Modify: `alphaagent/server/services/limit_up/data_quality_repository.py`
- Test: `tests/alphaagent/test_limit_up_data_quality.py`

- [x] **Step 1: Write failing request-selection tests**

Add tests proving that candidate pools are projected without loading the full replay payload and that retry filtering keeps only missing pairs whose scoped retry time is due.

```python
def test_scheduled_exit_requests_use_all_research_candidate_pools(monkeypatch):
    monkeypatch.setattr(
        data_quality.history_repository,
        "load_history_candidate_pools",
        lambda _version: history_rows,
    )

    assert data_quality._scheduled_exit_minute_requests() == [
        ("000001.SZSE", date(2026, 7, 10)),
        ("600000.SSE", date(2026, 7, 10)),
    ]
```

- [x] **Step 2: Run the focused tests and confirm failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_data_quality.py -q -k "scheduled_exit or retryable_minute"
```

Expected: failure because the candidate-pool projection and exit request helper do not exist.

- [x] **Step 3: Implement focused repository reads**

Add `load_history_candidate_pools(version)` that selects only `trade_date`, `validation_phase`, and `payload.lane_portfolio.candidate_pool`. Add `list_retryable_minute_pairs(pairs, provider, as_of, limit)` that reads the existing attempt ledger without changing event-pair coverage semantics.

```python
def load_history_candidate_pools(version: str) -> list[dict[str, object]]:
    payload = schema.limit_up_history_replays.c.payload
    statement = select(
        schema.limit_up_history_replays.c.trade_date,
        payload["validation_phase"].as_string().label("validation_phase"),
        payload["lane_portfolio"]["candidate_pool"].label("candidate_pool"),
    ).where(schema.limit_up_history_replays.c.strategy_version == version)
```

- [x] **Step 4: Verify request selection**

Run the command from Step 2. Expected: all selected tests pass.

### Task 2: Add exact 14:30 autonomous backfill

**Files:**
- Modify: `alphaagent/server/services/limit_up/data_quality.py`
- Test: `tests/alphaagent/test_limit_up_data_quality.py`

- [x] **Step 1: Write failing service tests**

Test that the new service:

- excludes pairs already containing an exact 14:30 bar;
- requests only `14:30..14:30` from TDX;
- verifies exact 14:30 persistence instead of treating any minute row as covered;
- records attempts under `tdx_exit_1430` so event-path retries remain independent;
- reports `cooling_down` when missing pairs exist but none are retryable.

```python
result = data_quality.backfill_limit_up_exit_minutes(max_gaps=2, dry_run=False)

assert captured["tail_entry_start"] == "14:30"
assert captured["tail_entry_end"] == "14:30"
assert recorded["provider"] == "tdx_exit_1430"
assert result["scope"] == "limit_up_candidate_exit_1430"
```

- [x] **Step 2: Run the tests and confirm failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_data_quality.py -q -k "exit_minute"
```

Expected: failure because `backfill_limit_up_exit_minutes()` does not exist.

- [x] **Step 3: Implement the bounded service**

Use the shared non-blocking minute lock, a maximum of 200 pairs, `scheduled_execution.RESEARCH_EXECUTION_LANES`, and the existing TDX importer. Preserve provider failures and retry cooldowns; never accept a partial day unless `load_account_1430_prices()` finds the exact bar.

- [x] **Step 4: Verify the service**

Run the command from Step 2. Expected: all selected tests pass.

### Task 3: Register and schedule the new job

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Write failing scheduler tests**

Require `sync_limit_up_exit_minutes` immediately after `sync_limit_up_event_minutes` and before `limit_up_history_rebuild` in `eod_finalize_2130`. Assert its default parameters, runner registration, result message, and history-input invalidation.

```python
assert jobs == [
    "sync_stock_daily_bars",
    "sync_index_daily_bars",
    "sync_sector_period_scores",
    svc.LIMIT_UP_THS_EVIDENCE_BATCH_JOB_ID,
    "sync_limit_up_event_minutes",
    "sync_limit_up_exit_minutes",
    svc.LIMIT_UP_HISTORY_REBUILD_BATCH_JOB_ID,
    svc.LIMIT_UP_NEXT_SESSION_PLAN_FINAL_BATCH_JOB_ID,
    svc.LIMIT_UP_LIVE_TRACE_PRUNE_BATCH_JOB_ID,
]
```

- [x] **Step 2: Run the tests and confirm failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "exit_minute or eod_finalize"
```

Expected: schedule and registry assertions fail.

- [x] **Step 3: Implement job wiring**

Add a `JobDefinition`, cadence, priority, runner method, runner registry entry, schedule entry, and `_changes_limit_up_history_inputs()` handling. Return rows and an explicit `候选D+1 14:30分钟补数` message. The following history rebuild remains the only cache-refresh boundary.

- [x] **Step 4: Verify scheduler behavior**

Run the command from Step 2. Expected: all selected tests pass.

### Task 4: Verify runtime and durable documentation

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/limit_up_production_local_parity_20260715.md`

- [x] **Step 1: Run focused backend regression**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_data_quality.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_cash_backtest.py -q
```

Expected: all tests pass.

- [x] **Step 2: Run static checks**

```bash
uv run python -m compileall alphaagent/server/services/limit_up alphaagent/server/services/data_sync.py
uv run ruff check alphaagent/server/services/limit_up/data_quality.py alphaagent/server/services/limit_up/data_quality_repository.py alphaagent/server/services/limit_up/history_repository.py alphaagent/server/services/data_sync.py tests/alphaagent/test_limit_up_data_quality.py tests/alphaagent/test_data_sync_schedule.py
git diff --check
```

Expected: compile, lint, and whitespace checks pass.

Result: compileall, `git diff --check`, and Ruff fatal rules passed. Full Ruff also
reported 14 pre-existing findings outside the added implementation lines; they were
left unchanged to preserve the dirty workspace.

- [x] **Step 3: Verify against the local PostgreSQL runtime**

Rebuild the API container, inspect the persisted schedule, dry-run the new job, and confirm the result reports database-derived pairs without any CSV/file input. A non-dry-run production execution must show exact 14:30 coverage increasing or a truthful provider/cooldown state.

- [x] **Step 4: Update current-state memory**

Record the new job order, scoped retry behavior, runtime result, and remaining provider limitations. Do not claim full parity or simulation eligibility unless the measured gates actually pass.
