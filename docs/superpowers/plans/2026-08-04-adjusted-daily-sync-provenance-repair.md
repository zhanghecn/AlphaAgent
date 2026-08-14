# Adjusted Daily Sync Provenance Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure a bounded nightly qfq sync can accumulate audited rows across runs without making valid partial writes unreadable to the fail-closed research reader.

**Architecture:** `sync_job_runs.status` represents whether the controlled import executed and persisted its evidence, while daily-scope completeness remains the separate gate for research use. The importer must only treat rows from a prior successful qfq job or from its own active run as usable; it must not reuse rows attached to a failed run.

**Tech Stack:** Python 3.11, SQLAlchemy/PostgreSQL, pytest.

---

### Task 1: Reproduce the provenance trap

**Files:**
- Modify: `tests/alphaagent/test_adjusted_daily_sync.py`

- [x] **Step 1: Add a run-status contract test**

```python
result = svc.run_job(ADJUSTED_JOB_ID, {"max_symbols": 50})

assert result["status"] == "incomplete"
assert finished_status == "succeeded"
assert finished_error_type is None
```

The test proves that an operationally successful bounded import preserves
`incomplete` coverage in its result while remaining a valid producer for rows it
has already persisted.

- [x] **Step 2: Add a canonical-row selection test**

```python
source, eligible = adjusted_daily_import._eligible_adjusted_row_source(
    current_sync_run_id=319,
)

assert "sync_job_runs.status = succeeded" in str(eligible)
assert "319" in str(eligible)
```

The test verifies that an active producer can audit its own writes but an older
failed producer cannot satisfy later coverage.

- [x] **Step 3: Reject an unbounded manual full backfill**

```python
with pytest.raises(AdjustedDailyImportError, match="explicit start_date and end_date"):
    sync_adjusted_daily_bars(sync_run_id=1, max_symbols=0)
```

The scheduled bounded job remains allowed. A manual all-symbol request must
name its date range before it can make provider calls.

### Task 2: Separate execution success from coverage completeness

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/services/data_providers/adjusted_daily_import.py`
- Test: `tests/alphaagent/test_adjusted_daily_sync.py`

- [x] **Step 1: Pass the active run id through importer coverage queries**

```python
adjusted_source, eligible_adjusted_row = _eligible_adjusted_row_source(
    current_sync_run_id=sync_run_id,
)
```

Use this predicate in both missing-target selection and scope collection. It
accepts the active run plus rows linked to a succeeded
`sync_low_suction_adjusted_daily_bars` run.

- [x] **Step 2: Mark a non-exceptional bounded qfq import as succeeded**

```python
coverage_incomplete = str(result.get("status") or "") == "incomplete"
run_status = "succeeded" if job_id == ADJUSTED_DAILY_SYNC_JOB_ID else (
    "failed" if coverage_incomplete else "succeeded"
)
```

Keep `result["status"] == "incomplete"` and its scope evidence intact. An
exception still marks the run failed and is excluded by the importer predicate.

- [x] **Step 3: Enforce an explicit range for `max_symbols=0`**

```python
if max_symbols == 0 and (start_date is None or end_date is None):
    raise AdjustedDailyImportError(
        "an unbounded qfq backfill requires explicit start_date and end_date"
    )
```

- [x] **Step 4: Keep an empty raw calendar as a failed run**

```python
adjusted_scope_persisted = (
    job_id == ADJUSTED_DAILY_SYNC_JOB_ID
    and _has_adjusted_daily_scope_evidence(result)
)
if coverage_incomplete and not adjusted_scope_persisted:
    run_status = "failed"
```

An incomplete qfq result is reusable only when its daily scope audit was
actually persisted. An empty input cannot create a canonical producer run.

- [x] **Step 5: Run focused tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_adjusted_daily_sync.py tests/alphaagent/test_data_sync_schedule.py -k 'adjusted or eod_schedule'`

Expected: PASS.

### Task 3: Record the corrected contract

**Files:**
- Modify: `memory/03_data/data_flow.md`

- [x] **Step 1: State the two independent statuses**

```markdown
qfq job-run success means the controlled importer persisted its bounded audit;
daily scope completeness alone decides whether research can read the snapshot.
```

- [x] **Step 2: State failed-run exclusion**

```markdown
Rows from a failed qfq run are never reused as canonical coverage by a later run.
```

- [x] **Step 3: Run source integrity checks**

Run: `uv run python -m compileall -q alphaagent/server/services/data_sync.py alphaagent/server/services/data_providers/adjusted_daily_import.py && git diff --check`

Expected: PASS.
