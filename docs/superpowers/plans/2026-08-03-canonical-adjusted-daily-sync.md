# Canonical Adjusted Daily Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make front-adjusted daily-bar snapshots a bounded, auditable product of the existing data-sync worker without changing raw `stock_daily_bars` semantics.

**Architecture:** Register one EOD data-sync job after raw stock daily bars. The job reads the canonical raw daily range to select a small current-session scope, obtains qfq snapshots through the designated provider, and persists rows plus a daily coverage statement carrying the producing sync-run id. The daily-factor repository remains a reader and will be wired by its owner to accept only this provenance.

**Tech Stack:** Python 3.11, SQLAlchemy/PostgreSQL, AkShare, pytest.

---

### Task 1: Add producer provenance to adjusted-price storage

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Add `sync_run_id` to both qfq tables and a compatibility patch**

```python
Column("sync_run_id", BigInteger, nullable=True)
```

The scope value must reference the `sync_job_runs` record that produced its evidence; older or manually inserted rows remain readable but are not producer-certified.

- [x] **Step 2: Verify table metadata exposes the provenance fields**

Run: `uv run --group server pytest -q tests/alphaagent/test_data_sync_schedule.py -k adjusted`
Expected: PASS.

### Task 2: Register and run the controlled qfq sync

**Files:**
- Create: `alphaagent/server/services/data_providers/adjusted_daily_import.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Write tests for registry, EOD order, and bounded no-network runner parameters**

```python
assert jobs.index("sync_stock_daily_bars") < jobs.index(
    "sync_low_suction_adjusted_daily_bars"
)
assert job.default_params["max_symbols"] == 50
```

- [x] **Step 2: Implement a provider importer with explicit `sync_run_id` and finite request bounds**

```python
def sync_adjusted_daily_bars(*, sync_run_id: int, max_symbols: int, ...) -> dict[str, object]:
    """Persist qfq snapshots and daily scope evidence for one data-sync run."""
```

The importer will reuse qfq row validation, retain original raw daily data untouched, and record request range, source, failures, and run id in its writes.

- [x] **Step 3: Add the job to `DEFAULT_JOBS`, `JOB_CADENCES`, `JOB_RUNNERS`, and both EOD schedules**

```python
JobDefinition(
    id="sync_low_suction_adjusted_daily_bars",
    source_id="akshare",
    target_table="low_suction_adjusted_daily_bars",
)
```

- [x] **Step 4: Pass the created run id only to this runner**

```python
if job_id == "sync_low_suction_adjusted_daily_bars":
    merged_params["_sync_run_id"] = run_id
```

- [x] **Step 5: Run focused tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_data_sync_schedule.py -k 'adjusted or eod_schedule or data_health'`
Expected: PASS.

### Task 3: Record the operating boundary

**Files:**
- Modify: `memory/03_data/data_flow.md`

- [x] **Step 1: State that the qfq snapshot is produced by the unified worker, not a research command**

```markdown
`sync_low_suction_adjusted_daily_bars` is the only writer for qfq snapshots;
research commands inspect persisted coverage and fail closed when it is missing.
```

- [x] **Step 2: State the operational constraint**

The normal EOD job is bounded; a historical range must be explicitly requested through the data-sync job and is never started by a study command.

- [x] **Step 3: Verify source integrity**

Run: `uv run python -m compileall -q alphaagent/server/services/data_sync.py alphaagent/server/services/data_providers && git diff --check`
Expected: PASS.
