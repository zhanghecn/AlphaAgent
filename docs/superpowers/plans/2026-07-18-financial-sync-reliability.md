# Financial Sync Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the nightly quarterly-financial sync finish reliably without rotating proxies, while preventing slow or empty symbols from permanently starving the remaining stock universe.

**Architecture:** Keep AkShare/Eastmoney and the existing `DataSyncRunner` as the only data path. Fetch the three independent financial statements concurrently under a financial-specific timeout, persist per-symbol quarterly attempt state, and select never-attempted or oldest-attempted eligible stocks first. Explicit `symbols` requests continue to bypass automatic cooldown ordering so operators can target a verified gap.

**Tech Stack:** Python 3.11, SQLAlchemy/PostgreSQL, `ThreadPoolExecutor`, pytest.

---

### Task 1: Freeze The Failure Modes In Tests

**Files:**
- Modify: `tests/alphaagent/test_data_sync_parallel.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Add a failing test for the dedicated financial timeout**

Patch the existing hung-stock test to monkeypatch `FINANCIAL_SYNC_PER_ITEM_TIMEOUT_SECONDS`, and capture the timeout passed to `_bounded_parallel_map`:

```python
def capture_timeout(fn, items, *, per_item_timeout, **kwargs):
    captured["timeout"] = per_item_timeout
    for item in items:
        fn(item)

monkeypatch.setattr(svc, "FINANCIAL_SYNC_PER_ITEM_TIMEOUT_SECONDS", 180.0)
assert captured["timeout"] == 180.0
```

- [x] **Step 2: Add a failing concurrency test for the three statement requests**

Use a fake adapter whose quarterly, balance-sheet, and cash-flow methods synchronize on a three-party barrier. Run one financial item and assert all three calls overlap and the normalized report is written once.

- [x] **Step 3: Add failing pure ordering tests for automatic rotation**

Cover these cases through `_select_financial_candidates`:

```python
assert selected_symbols == ["never-attempted", "oldest-success"]
assert "cooling-down" not in selected_symbols
```

Also verify that explicit symbol targeting retains caller scope and does not depend on automatic cooldown state.

- [x] **Step 4: Run the focused tests and confirm the new assertions fail**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_data_sync_parallel.py \
  tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: failures because the dedicated timeout, concurrent bundle loader, and rotation selector do not exist yet.

### Task 2: Persist Per-Symbol Financial Attempts

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Modify: `alphaagent/server/services/data_sync.py`

- [x] **Step 1: Add the attempt table**

Define `stock_financial_sync_attempts` keyed by `vt_symbol`, with status, attempt count, last error, `last_attempt_at`, and `next_retry_at`. Add an index on `(next_retry_at, last_attempt_at)` so nightly selection remains bounded.

- [x] **Step 2: Add small repository helpers**

Implement:

```python
def _load_financial_sync_attempts(symbols: Sequence[str]) -> dict[str, dict[str, Any]]: ...

def _record_financial_sync_attempt(
    vt_symbol_value: str,
    status: str,
    *,
    error: str | None = None,
    next_retry_at: datetime | None = None,
) -> None: ...
```

Use an upsert that increments `attempt_count`; attempt telemetry failure must be logged without discarding successfully fetched financial reports.

- [x] **Step 3: Rotate automatic candidates**

Keep the existing report-count eligibility rule, but load all eligible rows, discard rows still in cooldown, and order them by never attempted first, then oldest `last_attempt_at`, then turnover and symbol. Apply `stock_limit` only after this ordering. Explicit `symbols` requests bypass cooldown and rotation.

### Task 3: Make One Financial Item Complete Within Its Budget

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/test_data_sync_parallel.py`

- [x] **Step 1: Add financial-specific limits**

Define a `180` second financial item timeout and cap outer per-stock concurrency so concurrent statement requests do not increase the provider request fan-out beyond the existing batch setting.

- [x] **Step 2: Load independent statements concurrently**

Create a helper that starts quarterly profit, balance sheet, and cash-flow calls together. The quarterly profit response is required; balance and cash-flow failures return empty enrichment inputs and do not fabricate fields.

- [x] **Step 3: Separate fetching from enrichment**

Refactor ROE and cash-flow enrichment to accept already-fetched rows. Keep calculations and point-in-time publication dates unchanged.

- [x] **Step 4: Record every terminal item outcome**

Record `succeeded`, `empty`, `failed`, or `timed_out`. Empty, failed, and timed-out symbols receive a one-day retry delay; successful partial-history symbols move behind never-attempted symbols instead of occupying the first page every night. Preserve the late-write guard after timeout.

- [x] **Step 5: Run focused tests**

Run the two focused test files and require all tests to pass.

### Task 4: Regression And Static Verification

**Files:**
- Verify: `alphaagent/server/services/data_sync.py`
- Verify: `alphaagent/server/db/schema.py`
- Verify: `tests/alphaagent/test_data_sync_parallel.py`
- Verify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Run the complete data-sync regression suite**

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_*.py -q
```

Expected: all data-sync tests pass.

- [x] **Step 2: Run syntax and diff checks**

```bash
uv run python -m compileall -q alphaagent/server/services/data_sync.py alphaagent/server/db/schema.py
git diff --check
```

Expected: both commands exit successfully.

- [x] **Step 3: Review scope**

Confirm the diff does not change recommendation rules, backtest execution, D+1 prices, public data providers, Docker topology, or unrelated dirty low-suction files. Do not commit without an explicit user request.

### Task 5: Update Durable Data-Flow Truth

**Files:**
- Modify: `memory/03_data/data_flow.md`

- [x] **Step 1: Replace the stale timeout description**

Document the financial-specific timeout, concurrent three-statement fetch, persistent per-symbol rotation, and the fact that no proxy pool was introduced.

- [x] **Step 2: Record the remaining operational acceptance boundary**

State that code and unit tests are complete locally, while the first natural production `v2.5.23+` 21:30 run remains a deployment-time acceptance item. Do not claim production deployment or natural scheduler success unless separately requested and observed.
