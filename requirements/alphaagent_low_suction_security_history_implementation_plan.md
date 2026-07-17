# AlphaAgent Low-Suction Security History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Build an auditable historical listing, delisting, ST, suspension, and board-status dataset without allowing reconstructed data to qualify the strict low-suction research gate.

**Architecture:** Membership and security history are imported through separate validation boundaries. A security batch is validated against explicit date/symbol pairs, then one PostgreSQL transaction replaces the provider scope; reconstructed BaoStock rows are retained for survivorship analysis but strict coverage counts only rows whose evidence level is `strict` and whose `known_at` is no later than the research cutoff.

**Tech Stack:** Python 3.11+, SQLAlchemy Core, PostgreSQL 16, BaoStock 0.9.3 as a bounded reconstruction source, pytest.

---

## Fixed Evidence Boundary

```python
SECURITY_EVIDENCE_LEVELS = ("strict", "reconstructed", "invalid")
RESEARCH_OPEN_CUTOFF = time(9, 25)
```

- `strict` requires a documented point-in-time field and `known_at <= D 09:25 Asia/Shanghai`.
- `reconstructed` is useful for finding missing delisted stocks and historical ST/suspension rows, but it never satisfies `security_is_valid_at_open` and never contributes to formal coverage.
- BaoStock is currently `reconstructed`: its APIs expose `ipoDate`, `outDate`, daily `tradestatus`, and daily `isST`, but no verified publication-time promise proves that a historical row was known by D 09:25.
- Required security scope is an explicit set of `(trade_date, vt_symbol)` pairs. A dates-by-symbols Cartesian product is invalid because a stock need not exist before listing or after delisting.
- Provider rows are parsed and completely validated before any delete or insert begins.

## File Map

- `alphaagent/server/services/low_suction/historical_inputs.py`: immutable records, explicit scope contracts, and fail-closed validation.
- `alphaagent/server/db/schema.py`: low-suction security-history and validated-scope tables; neither has a foreign key to the current `stocks` table, so historical delisted securities can be retained.
- `alphaagent/server/services/low_suction/security_history_repository.py`: one-transaction provider/symbol and validated-scope replacement.
- `alphaagent/server/services/low_suction/baostock_security_source.py`: bounded provider adapter and normalization to reconstructed records.
- `alphaagent/server/services/low_suction/data_quality_repository.py`: strict coverage plus separately labelled reconstructed inventory.
- `tests/alphaagent/services/low_suction/test_historical_inputs.py`: pure contract tests.
- `tests/alphaagent/services/low_suction/test_security_history_repository.py`: transaction-shape and serialization tests.
- `tests/alphaagent/services/low_suction/test_baostock_security_source.py`: fake-client adapter tests with no network dependency.
- `tests/alphaagent/services/low_suction/test_data_quality.py`: strict-gate regression tests.

### Task 1: Split Security and Membership Validation

**Files:**
- Modify: `alphaagent/server/services/low_suction/historical_inputs.py`
- Modify: `tests/alphaagent/services/low_suction/test_historical_inputs.py`

- [x] **Step 1: Write failing tests for explicit security pairs and evidence levels**

```python
def test_security_scope_does_not_require_pre_listing_pairs() -> None:
    report = import_historical_securities(
        security_rows=[_security(evidence_level="strict")],
        required_pairs=[(date(2026, 7, 1), "600001.SSE")],
        dry_run=True,
    )
    assert report.status == "ready_for_atomic_replace"


def test_reconstructed_security_never_qualifies_at_open() -> None:
    record = HistoricalSecurityRecord.from_mapping(
        _security(evidence_level="reconstructed")
    )
    assert security_is_valid_at_open(record, date(2026, 7, 1)) is False
```

- [x] **Step 2: Run the focused tests and verify the new API is absent**

Run: `uv run --group server pytest tests/alphaagent/services/low_suction/test_historical_inputs.py -q`

Expected: failure because `import_historical_securities` and `evidence_level` do not exist.

- [x] **Step 3: Add independent batches and reports**

```python
@dataclass(frozen=True)
class HistoricalSecurityBatch:
    records: tuple[HistoricalSecurityRecord, ...]
    required_pairs: tuple[tuple[date, str], ...]
    source: str
    evidence_level: str


SecurityHistoryWriter = Callable[[HistoricalSecurityBatch], None]
```

`import_historical_securities` accepts `security_rows`, explicit `required_pairs`, an
optional `SecurityHistoryWriter`, and `dry_run`. It rejects empty scope, duplicate
source IDs, mixed providers, missing pairs, overlapping active rows for the same pair,
and `dry_run=False` without a writer. It invokes the writer exactly once only after
every row and pair passes.

- [x] **Step 4: Add a membership response manifest**

```python
@dataclass(frozen=True)
class HistoricalMembershipScope:
    trade_date: date
    sector_id: str
    expected_member_count: int
    returned_member_count: int
    pagination_complete: bool
    known_at: datetime
    source: str
    source_request_id: str
```

For each required date/sector pair, require exactly one on-time manifest, `pagination_complete=True`, equal expected/returned counts, and an equal number of distinct active symbols. A one-row truncated response must fail when the manifest expects more than one member.

- [x] **Step 5: Run the contract tests**

Run: `uv run --group server pytest tests/alphaagent/services/low_suction/test_historical_inputs.py -q`

Expected: all tests pass; no database is accessed.

### Task 2: Add Atomic Security-History Persistence

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/low_suction/security_history_repository.py`
- Create: `tests/alphaagent/services/low_suction/test_security_history_repository.py`

- [x] **Step 1: Add the table contract**

```python
low_suction_security_history = Table(
    "low_suction_security_history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("vt_symbol", String(32), nullable=False),
    Column("symbol", String(16), nullable=False),
    Column("exchange", String(16), nullable=False),
    Column("name", String(80), nullable=False),
    Column("status", String(32), nullable=False),
    Column("board", String(32), nullable=False),
    Column("listed_on", Date, nullable=False),
    Column("delisted_on", Date, nullable=True),
    Column("valid_from", Date, nullable=False),
    Column("valid_to", Date, nullable=False),
    Column("suspended", Boolean, nullable=False),
    Column("risk_warning", Boolean, nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_record_id", String(240), nullable=False),
    UniqueConstraint("source", "source_record_id", name="uq_low_suction_security_source_record"),
)
```

Add indexes on `(vt_symbol, valid_from, valid_to)`, `(evidence_level, valid_from)`, and `delisted_on`. Do not reference `stocks.vt_symbol` with a foreign key.

Add `low_suction_security_history_scopes` with `(source, trade_date, vt_symbol)` as
its unique key plus `evidence_level`. These rows persist the validated denominator;
coverage may never infer its denominator from whatever status rows happened to arrive.

- [x] **Step 2: Test the transaction shape**

The test monkeypatches `session_scope`, captures SQL statements, and proves one scope emits provider/symbol deletes for status and scope tables followed by bulk inserts for both tables in the same session. A raised insert exception must escape so `session_scope` can roll the transaction back.

- [x] **Step 3: Implement scoped replacement**

```python
def replace_security_history(batch: HistoricalSecurityBatch) -> int:
    table = schema.low_suction_security_history
    scope_table = schema.low_suction_security_history_scopes
    with session_scope() as session:
        session.execute(
            delete(table).where(
                table.c.source == batch.source,
                table.c.vt_symbol.in_(sorted({pair[1] for pair in batch.required_pairs})),
            )
        )
        session.execute(
            delete(scope_table).where(
                scope_table.c.source == batch.source,
                scope_table.c.vt_symbol.in_(sorted({pair[1] for pair in batch.required_pairs})),
            )
        )
        session.execute(insert(table), [_record_values(row) for row in batch.records])
        session.execute(
            insert(scope_table),
            [
                {
                    "trade_date": trade_date,
                    "vt_symbol": vt_symbol,
                    "evidence_level": batch.evidence_level,
                    "source": batch.source,
                }
                for trade_date, vt_symbol in batch.required_pairs
            ],
        )
    return len(batch.records)
```

- [x] **Step 4: Run schema and repository tests**

Run: `uv run --group server pytest tests/alphaagent/services/low_suction/test_security_history_repository.py tests/alphaagent/test_db_schema.py -q`

Expected: all collected tests pass. If `test_db_schema.py` is absent, run the repository test plus `python -m compileall` and inspect the generated PostgreSQL DDL in the repository test.

### Task 3: Add the BaoStock Reconstruction Adapter

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `alphaagent/server/services/low_suction/baostock_security_source.py`
- Create: `tests/alphaagent/services/low_suction/test_baostock_security_source.py`

- [x] **Step 1: Pin the server dependency**

Add `baostock>=0.9.3` to `[dependency-groups].server`, then run `uv lock`.

- [x] **Step 2: Test full master enumeration and daily normalization**

The fake BaoStock client must cover a listed main-board stock, a delisted main-board stock, a ChiNext stock, one suspended day, and one ST day. Assert that board filtering retains both main-board records, daily rows use `[D, D+1)`, and every emitted row has `evidence_level="reconstructed"` and `known_at=observed_at`.

- [x] **Step 3: Implement bounded provider calls**

```python
def fetch_security_master(client: BaoStockClient) -> SecurityMasterResult:
    """Return all type=1 SSE/SZSE stocks, including status=0 delisted rows."""


def fetch_reconstructed_security_history(
    vt_symbols: Sequence[str],
    *,
    start_date: date,
    end_date: date,
    observed_at: datetime,
    client: BaoStockClient | None = None,
) -> tuple[dict[str, Any], ...]:
    """Fetch only the requested symbols; never scan all symbols for daily bars."""
```

Check every BaoStock `error_code`; call `logout()` in `finally`; reject unsupported exchanges; do not interpolate missing daily rows; do not convert `observed_at` into a historical timestamp.

- [x] **Step 4: Run adapter tests without network access**

Run: `uv run --group server pytest tests/alphaagent/services/low_suction/test_baostock_security_source.py -q`

Expected: all tests pass using only fake query results.

### Task 4: Expose Strict and Reconstructed Coverage Separately

**Files:**
- Modify: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `tests/alphaagent/services/low_suction/test_data_quality.py`
- Modify: `tests/alphaagent/services/low_suction/test_reporting.py`

- [x] **Step 1: Test fail-closed coverage**

Given 720 reconstructed dates and zero strict dates, assert `security_status.mode == "reconstructed"`, `strict_ready is False`, `historical_security_status` remains in `blocking_gaps`, and `formal_metrics is None`.

- [x] **Step 2: Query only strict rows for formal coverage**

Strict rows must satisfy `evidence_level="strict"`; reconstructed rows are reported under inventory with row, symbol, date, delisted-symbol, risk-warning-row, and suspension-row counts. Never merge the two counts.

- [x] **Step 3: Add survivorship diagnostics**

Report current `stocks` rows with parseable listing/delisting fields, reconstructed main-board master counts, historical delisted main-board counts, and how many reconstructed symbols are absent from `stocks`. The diagnostic is evidence of a gap, not a formal return metric.

- [x] **Step 4: Run audit regressions**

Run: `uv run --group server pytest tests/alphaagent/services/low_suction/test_data_quality.py tests/alphaagent/services/low_suction/test_reporting.py -q`

Expected: all tests pass and every non-strict fixture leaves formal metrics `null`.

### Task 5: Verify and Record Evidence

**Files:**
- Modify: `memory/06_backtests/low_suction_data_quality_20260716.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/README.md`

- [x] **Step 1: Run the complete low-suction suite**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
uv run python -m compileall alphaagent/server/services/low_suction
git diff --check
```

- [x] **Step 2: Run the database audit**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format markdown
```

Expected: `blocked_by_data_quality`; reconstructed BaoStock rows, if imported, are visible only as supporting inventory; formal metrics remain `null`.

- [x] **Step 3: Record the measured master-universe result**

Record the 2026-07-16 read-only BaoStock observation: 8,845 master rows, 5,537 `type=1` stock rows, 3,483 main-board-prefix stock rows, of which 291 have delisted status or `outDate`. Preserve the qualification that BaoStock timing semantics remain unverified.

## Completion Boundary

This plan closes the security-history software gap but does not, by itself, close the strict data-quality gate. Formal research remains blocked until a documented point-in-time source supplies at least 720 trade days and 1,095 calendar days of strict security status with at least 90% coverage.
