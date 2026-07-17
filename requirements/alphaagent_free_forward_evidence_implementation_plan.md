# AlphaAgent Free Forward Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Turn the existing free Eastmoney membership collector and BaoStock daily security universe into complete, atomic, D-1 point-in-time evidence that can accumulate toward the low-suction strict data gates.

**Architecture:** Keep current market rows in the shared snapshot tables, add explicit per-date completeness scopes, and reject a snapshot whenever any expected board or security is absent. Capture only a completed trading session, retry the entire chain at 21:30, and dynamically map source session S to the next reliable research session D without copying current data backward.

**Tech Stack:** Python 3.11+, SQLAlchemy Core, PostgreSQL 16, BaoStock 0.9.3, existing Eastmoney/AkShare adapters, pytest, Docker Compose.

---

## Fixed Boundaries

```python
FORWARD_MEMBERSHIP_SOURCE = "eastmoney.push2.board"
FORWARD_SECURITY_SOURCE = "baostock.query_all_stock.forward"
FORWARD_EVIDENCE_LEVEL = "strict"
MEMBERSHIP_SCOPE_TYPES = ("concept", "industry")
MIN_FORWARD_MAIN_BOARD_SYMBOLS = 3_000
MIN_FORWARD_CONCEPT_SECTORS = 300
```

- A scheduled run writes only when the latest reliable stock date equals the Shanghai capture date.
- Concept scope combines local `concept` and `theme` types; industry remains separate.
- One failed board request rejects the scheduled membership snapshot. Previous dates remain unchanged.
- A same-day retry atomically replaces both snapshot rows and completeness scopes.
- BaoStock historical reconstruction remains `reconstructed`; only a response actually observed after source session S can be strict for the next session D.
- No snapshot may be copied to an earlier date or silently forward-filled across a missing trading session.
- Existing limit-up candidates, ledgers, versions, and performance remain unchanged.

### Task 1: Add Atomic Membership Completeness Scopes

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Modify: `alphaagent/server/services/market_snapshot_repository.py`
- Modify: `tests/alphaagent/test_market_snapshot_repository.py`

- [x] **Step 1: Write failing scope and atomicity tests**

Cover exact concept/industry inventories, concept+theme normalization, missing expected sectors,
mixed providers, duplicate keys, and same-date atomic replacement:

```python
def test_membership_snapshot_requires_every_expected_sector() -> None:
    with pytest.raises(IncompleteMembershipSnapshotError):
        build_membership_snapshot_scopes(
            rows=[_membership("BK0001", "concept")],
            expected_sectors=[_sector("BK0001", "concept"), _sector("BK0002", "concept")],
            snapshot_date=date(2026, 7, 16),
            captured_at=_captured_at(),
        )


def test_complete_scope_combines_concept_and_theme() -> None:
    scopes = build_membership_snapshot_scopes(
        rows=[_membership("BK0001", "concept"), _membership("BK0002", "theme")],
        expected_sectors=[_sector("BK0001", "concept"), _sector("BK0002", "theme")],
        snapshot_date=date(2026, 7, 16),
        captured_at=_captured_at(),
    )
    assert scopes[0]["scope_type"] == "concept"
    assert scopes[0]["expected_sector_count"] == 2
    assert scopes[0]["captured_sector_count"] == 2
    assert scopes[0]["complete"] is True
```

- [x] **Step 2: Run the focused tests and verify the scope API is absent**

```bash
uv run --group server pytest tests/alphaagent/test_market_snapshot_repository.py -q
```

- [x] **Step 3: Add the scope table**

```python
stock_sector_membership_snapshot_scopes = Table(
    "stock_sector_membership_snapshot_scopes",
    metadata,
    Column("snapshot_date", Date, primary_key=True),
    Column("scope_type", String(24), primary_key=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("expected_sector_count", Integer, nullable=False),
    Column("captured_sector_count", Integer, nullable=False),
    Column("row_count", Integer, nullable=False),
    Column("symbol_count", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
)
```

- [x] **Step 4: Validate and replace rows plus scopes in one transaction**

`save_current_stock_sector_membership_snapshot()` must read `sectors` and
`stock_sector_memberships`, build both scopes, reject missing sectors or mixed sources, then delete
and insert that date's rows and scopes in one `session_scope`. Keep the existing integer return type.

- [x] **Step 5: Run repository tests**

Expected: all market snapshot tests pass.

### Task 2: Fail Closed And Retry The Full Membership Chain

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Write failure-propagation and schedule tests**

```python
def test_one_failed_sector_blocks_reverse_snapshot(monkeypatch) -> None:
    with pytest.raises(DataSyncError):
        _run_sector_members_with_one_provider_failure(monkeypatch)
    assert _depends_on("sync_stock_sector_memberships", "sync_sector_members") is True


def test_2130_retries_complete_membership_chain() -> None:
    schedule = _default_schedule("eod_finalize_2130")
    sequence = schedule["job_ids"]
    assert sequence.index("sync_sector_list") < sequence.index("sync_sector_members")
    assert sequence.index("sync_sector_members") < sequence.index("sync_stock_sector_memberships")
```

- [x] **Step 2: Track failed board requests**

Extend `_run_sync_sector_members()` counters with `failed` and bounded `failed_sector_ids`. After all
workers finish, raise `DataSyncError` when `failed > 0`; successful sector updates may remain current,
but no dated snapshot is allowed from the partial run.

- [x] **Step 3: Treat sector members as an upstream dependency**

Add `sync_sector_members` to `_BASE_SYNC_JOBS` and make only
`sync_stock_sector_memberships` depend on it. The batch continues with unrelated work while the
dated snapshot job becomes `skipped`.

- [x] **Step 4: Add the three membership jobs to the 21:30 retry**

Insert `sync_sector_list`, `sync_sector_members`, and `sync_stock_sector_memberships` in that order
before limit-up evidence jobs. Registry reconciliation updates the stored default schedule.

- [x] **Step 5: Reject non-trading-day captures**

Before rebuilding the reverse index, require the latest reliable stock date with at least 3,000
symbols to equal `captured_at.date()`. Otherwise return `status="skipped"` and write no snapshot.

- [x] **Step 6: Run schedule and sync regression tests**

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_market_snapshot_repository.py -q
```

### Task 3: Add A Free Point-in-time BaoStock Security Source

**Files:**
- Modify: `alphaagent/server/services/low_suction/baostock_security_source.py`
- Create: `tests/alphaagent/services/low_suction/test_forward_security_snapshot.py`

- [x] **Step 1: Write provider contract tests**

Fixtures must cover non-stock BaoStock rows, main-board filtering, full expected coverage, one missing
active stock, suspension, `ST/*ST/退` names, delisted master rows, duplicate codes, wrong provider date,
and timezone-aware observation time.

```python
def test_forward_snapshot_keeps_st_and_suspended_rows() -> None:
    result = fetch_forward_security_snapshot(
        source_trade_date=date(2026, 7, 16),
        observed_at=_observed_at(),
        client=_client_with_complete_daily_rows(),
    )
    assert result.missing_symbols == ()
    assert any(row.risk_warning for row in result.records)
    assert any(row.suspended for row in result.records)
```

- [x] **Step 2: Extend the BaoStock protocol**

Add `day: str` to `BaoStockQuery`, add `query_all_stock(day: str)` to `BaoStockClient`, and query it
in the same authenticated session as `query_stock_basic()`. Require returned `query.day` to match
the requested source session.

- [x] **Step 3: Normalize one complete active main-board snapshot**

Build the expected set from stock-master records where `listed_on <= S` and
`delisted_on is None or delisted_on >= S`. Join `code/tradeStatus/code_name`, require every expected
code exactly once, classify `tradeStatus=0` as suspended, and mark observed names containing `ST`
or `退` as risk warning. Do not discard those rows; filtering happens later.

- [x] **Step 4: Run provider tests without live network**

Expected: all forward security fixtures pass.

### Task 4: Persist And Schedule Daily Security Snapshots

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/low_suction/forward_security_repository.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `tests/alphaagent/services/low_suction/test_forward_security_snapshot.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Add snapshot and scope tables**

Create `low_suction_security_snapshots` keyed by `(source_trade_date, vt_symbol, source)` and
`low_suction_security_snapshot_scopes` keyed by `(source_trade_date, source)`. Store observation
time, expected/returned counts, complete flag, listing/delisting dates, ST/suspension flags, source,
evidence level, and raw provenance.

- [x] **Step 2: Write atomic repository tests**

Reject empty, partial, duplicate, mixed-date, mixed-source, and naive-time batches before SQL.
Assert one transaction replaces only the selected source date and writes scope plus records.

- [x] **Step 3: Implement `replace_forward_security_snapshot()`**

Validate the provider result first, delete the same date/source records and scope, then insert the
complete replacement. Never delete BaoStock reconstructed history or another provider.

- [x] **Step 4: Register `sync_low_suction_security_snapshot`**

The job selects only today's reliable completed stock session, fetches the free BaoStock snapshot,
and atomically writes it. Add it after the membership chain in both 19:00 and 21:30 schedules.
Same-day retry replaces the first capture.

- [x] **Step 5: Run job and repository tests**

Expected: missing provider rows fail closed, holiday runs skip, and complete runs report exact
ST/suspended/total counts.

### Task 5: Let Forward Evidence Accumulate Toward Strict Gates

**Files:**
- Modify: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `tests/alphaagent/services/low_suction/test_data_quality.py`

- [x] **Step 1: Write D-1 effective-date tests**

For reliable sessions `(S, D)`, a complete membership/security snapshot captured after S close is
effective on D only. Missing S, incomplete scopes, capture after D 09:25, mixed providers, and
weekend calendar arithmetic must not qualify.

- [x] **Step 2: Add provider-isolated forward coverage**

Aggregate complete forward scopes by source, map each source date to the next reliable session, and
report effective trade days, start/end, required/covered pairs, entities, ST and suspension counts.
Do not combine Eastmoney forward snapshots with Tushare DC history or BaoStock reconstruction.

- [x] **Step 3: Preserve the existing gates**

Forward providers may become `mode="strict"` only after their own complete D-1 coverage reaches the
existing 720-session and 1,095-day requirements. Before that, keep
`historical_concept_membership` and `historical_security_status` blocked and formal metrics `null`.

- [x] **Step 4: Run low-suction tests**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
```

### Task 6: Runtime Validation And Durable Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_free_forward_capture_20260716.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/README.md`

- [x] **Step 1: Run all relevant regressions**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_market_snapshot_repository.py -q
uvx ruff check alphaagent/server/services/low_suction alphaagent/server/services/market_snapshot_repository.py tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent
git diff --check
```

- [x] **Step 2: Rebuild the API and reconcile schedules**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c \
  "from alphaagent.server.services.data_sync import ensure_sync_schema; ensure_sync_schema()"
```

- [x] **Step 3: Execute bounded real captures**

Run the membership and security jobs only when the latest reliable date is today. Verify both scope
tables are complete, exact row counts are plausible, and same-day retry does not duplicate rows. If
the market session is not complete, verify both jobs skip without writes.

- [x] **Step 4: Re-run the low-suction audit**

Expected immediately: forward providers appear in inventory with only the newly observed effective
sessions; the three-year gates remain closed and `formal_metrics` remains `null`.

- [x] **Step 5: Update durable evidence**

Record current schedule IDs, scope counts, provider source dates, exact verification commands, and
the distinction between free forward accumulation and unavailable historical backfill.

## Completion Boundary

This plan completes reliable free forward evidence collection. It does not claim three years of
history, tune low-suction rules, calculate formal performance, add a UI Tab, simulate positions, or
place orders. Those steps remain gated by accumulated coverage and candidate-directed minute paths.
