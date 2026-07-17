# Low-suction Forward Tradable Scope Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist an auditable Eastmoney forward concept-membership scope for low-suction research when every failed board is an exact-ID non-tradable manifest exclusion, without weakening the shared full-catalog/limit-up sync contract.

**Architecture:** Keep the shared `sector_memberships` and full-catalog job unchanged as raw input. Build a low-suction-only capture from the exact sector inventory and the member pages fetched in the current run, then atomically persist dedicated tradable rows plus separate `concept_catalog` and `concept_tradable` scopes. Only a complete, post-close, current-session `concept_tradable` scope using the current manifest version may enter V2 coverage.

**Tech Stack:** Python 3.13, SQLAlchemy Core, PostgreSQL JSONB, pytest, existing AlphaAgent scheduler and low-suction data-quality audit.

**Repository constraint:** Do not commit or push. The project `AGENTS.md` forbids commits unless the user explicitly requests one.

---

### Task 1: Define Exact-ID Capture Semantics

**Files:**
- Create: `alphaagent/server/services/low_suction/forward_membership.py`
- Create: `tests/alphaagent/services/low_suction/test_forward_membership.py`
- Modify: `alphaagent/server/services/low_suction/theme_reference_cohorts.py`

- [x] **Step 1: Write failing exact-ID and fail-closed tests**

```python
def test_report_failures_allow_tradable_scope_by_exact_id_only() -> None:
    capture = build_forward_membership_capture(
        sectors=_sectors("BK1677", "BK1678", "BK1679", "BK9000"),
        members_by_sector={"BK9000": _members("BK9000")},
        failed_sector_ids=("BK1677", "BK1678", "BK1679"),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )
    assert capture.tradable_scope.complete is True
    assert capture.tradable_scope.expected_sector_count == 1
    assert capture.tradable_scope.returned_sector_count == 1
    assert [row["sector_id"] for row in capture.tradable_scope.raw["excluded_sectors"]] == [
        "BK1677", "BK1678", "BK1679"
    ]


def test_name_does_not_exclude_an_unlabelled_id() -> None:
    capture = build_forward_membership_capture(
        sectors=[{"id": "BK9999", "name": "2025年报预增", "type": "theme"}],
        members_by_sector={},
        failed_sector_ids=("BK9999",),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )
    assert capture.tradable_scope.complete is False
    assert capture.tradable_scope.raw["missing_sector_ids"] == ["BK9999"]


@pytest.mark.parametrize("sector_id", ["BK0963", "BK9999"])
def test_narrative_or_unlabelled_failure_closes_tradable_scope(sector_id: str) -> None:
    capture = build_forward_membership_capture(
        sectors=[{"id": sector_id, "name": "题材", "type": "theme"}],
        members_by_sector={},
        failed_sector_ids=(sector_id,),
        source_trade_date=SOURCE_DATE,
        observed_at=OBSERVED_AT,
    )
    assert capture.tradable_scope.complete is False
    assert capture.records == ()
```

- [x] **Step 2: Run the focused test and verify it fails**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_forward_membership.py -q
```

Expected: import failure because `forward_membership.py` does not exist.

- [x] **Step 3: Implement the immutable capture builder**

```python
EXCLUDED_MANIFEST_CLASSES = frozenset(
    {"mechanical_event", "style_universe", "report_event", "ambiguous"}
)
CATALOG_SCOPE_TYPE = "concept_catalog"
TRADABLE_SCOPE_TYPE = "concept_tradable"
FORWARD_MEMBERSHIP_SOURCE = "eastmoney.push2.board.forward"
RAW_PROVIDER_SOURCE = "eastmoney.push2.board"


@dataclass(frozen=True)
class ForwardMembershipScope:
    scope_type: str
    source_trade_date: date
    observed_at: datetime
    expected_sector_count: int
    returned_sector_count: int
    row_count: int
    symbol_count: int
    complete: bool
    evidence_level: str
    source: str
    manifest_version: str
    raw: dict[str, object]


@dataclass(frozen=True)
class ForwardMembershipCapture:
    records: tuple[dict[str, object], ...]
    catalog_scope: ForwardMembershipScope
    tradable_scope: ForwardMembershipScope


def build_forward_membership_capture(
    *,
    sectors: Sequence[Mapping[str, object]],
    members_by_sector: Mapping[str, Sequence[Mapping[str, object]]],
    failed_sector_ids: Sequence[str],
    source_trade_date: date,
    observed_at: datetime,
    manifest: Mapping[str, ThemeManifestRecord] = REFERENCE_MANIFEST,
    manifest_version: str = MANIFEST_VERSION,
) -> ForwardMembershipCapture:
    """Build one post-close capture; names never participate in exclusions."""
```

The implementation must normalize exact IDs, reject duplicate catalog IDs, require an aware Shanghai post-close observation on `source_trade_date`, retain both `concept` and `theme`, and ignore industry rows. A sector is excluded only when its exact manifest record has one of `EXCLUDED_MANIFEST_CLASSES`; `narrative_theme` and `unlabeled` remain in the tradable denominator. Each included sector must have a non-empty, unique member list whose item source is `eastmoney.push2.board`. When any included sector is missing, produce an incomplete tradable scope and no records. Both scopes must write sorted failed IDs, sorted exact exclusions with class/reason, manifest version, and original catalog count to `raw`.

- [x] **Step 4: Run exact-ID tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_forward_membership.py -q
```

Expected: all tests pass.

### Task 2: Add Dedicated Atomic Persistence

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/low_suction/forward_membership_repository.py`
- Create: `tests/alphaagent/services/low_suction/test_forward_membership_repository.py`

- [x] **Step 1: Write failing table-shape and transaction tests**

```python
def test_forward_membership_tables_are_low_suction_owned() -> None:
    rows = schema.low_suction_forward_membership_snapshots
    scopes = schema.low_suction_forward_membership_snapshot_scopes
    assert [column.name for column in rows.primary_key.columns] == [
        "source_trade_date", "sector_id", "vt_symbol", "source"
    ]
    assert [column.name for column in scopes.primary_key.columns] == [
        "source_trade_date", "scope_type", "source"
    ]
    assert not rows.foreign_keys
    assert not scopes.foreign_keys


def test_complete_capture_replaces_rows_and_both_scopes_in_one_transaction(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)
    written = save_forward_membership_capture(_complete_capture())
    assert written == 1
    assert [statement_kind(call) for call in session.calls] == [
        "delete_rows", "delete_scopes", "insert_rows", "insert_scopes"
    ]


def test_partial_retry_does_not_delete_an_existing_strict_scope(monkeypatch) -> None:
    session = FakeSession()
    _patch_session(monkeypatch, session)
    written = save_forward_membership_capture(_partial_capture())
    assert written == 0
    assert [statement_kind(call) for call in session.calls] == [
        "delete_catalog_scope", "insert_catalog_scope"
    ]


def test_insert_failure_escapes_the_single_transaction(monkeypatch) -> None:
    session = FakeSession(fail_on_call=4)
    _patch_session(monkeypatch, session)
    with pytest.raises(RuntimeError, match="insert failed"):
        save_forward_membership_capture(_complete_capture())
    assert len(session.calls) == 4
```

- [x] **Step 2: Add source-isolated tables**

```python
low_suction_forward_membership_snapshots = Table(
    "low_suction_forward_membership_snapshots",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("sector_id", String(64), primary_key=True),
    Column("vt_symbol", String(32), primary_key=True),
    Column("source", String(160), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("sector_name", String(160), nullable=False),
    Column("sector_type", String(40), nullable=False),
    Column("manifest_class", String(40), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)

low_suction_forward_membership_snapshot_scopes = Table(
    "low_suction_forward_membership_snapshot_scopes",
    metadata,
    Column("source_trade_date", Date, primary_key=True),
    Column("scope_type", String(32), primary_key=True),
    Column("source", String(160), primary_key=True),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("expected_sector_count", Integer, nullable=False),
    Column("returned_sector_count", Integer, nullable=False),
    Column("row_count", Integer, nullable=False),
    Column("symbol_count", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("evidence_level", String(40), nullable=False),
    Column("manifest_version", String(120), nullable=False),
    Column("raw", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
```

- [x] **Step 3: Implement complete replace and partial catalog-only persistence**

```python
def save_forward_membership_capture(capture: ForwardMembershipCapture) -> int:
    schema.ensure_schema_once(get_engine())
    if capture.tradable_scope.complete:
        with session_scope() as session:
            session.execute(delete(rows).where(_same_capture(rows, capture)))
            session.execute(delete(scopes).where(_same_capture(scopes, capture)))
            session.execute(insert(rows), list(capture.records))
            session.execute(insert(scopes), [_scope_values(scope) for scope in capture.scopes])
        return len(capture.records)
    with session_scope() as session:
        session.execute(delete(scopes).where(_same_catalog_scope(scopes, capture)))
        session.execute(insert(scopes), [_scope_values(capture.catalog_scope)])
    return 0
```

The complete path must require non-empty records, one complete strict tradable scope, exact record/scope counts, and the same source/date/observation/manifest version. The partial path may update only `concept_catalog`; it must never delete or downgrade a previously stored strict tradable scope or its records.

- [x] **Step 4: Verify repository tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_forward_membership_repository.py -q
```

Expected: all tests pass.

### Task 3: Capture the Current Sync Run Without Weakening Shared Failure

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:784`
- Modify: `tests/alphaagent/test_data_sync_schedule.py:1640`

- [x] **Step 1: Write failing integration tests**

```python
def test_exact_report_failures_save_low_suction_scope_but_shared_job_still_fails(monkeypatch) -> None:
    saved = []
    _patch_sector_catalog(monkeypatch, failures={"BK1677", "BK1678", "BK1679"})
    monkeypatch.setattr(svc, "_save_low_suction_forward_membership", saved.append)
    with pytest.raises(svc.DataSyncError, match="BK1677"):
        svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_sector_members({})
    assert len(saved) == 1
    assert saved[0].tradable_scope.complete is True
    assert svc._depends_on("sync_stock_sector_memberships", "sync_sector_members") is True


def test_unlabelled_failure_saves_only_rejected_capture(monkeypatch) -> None:
    saved = []
    _patch_sector_catalog(monkeypatch, failures={"BK9999"})
    monkeypatch.setattr(svc, "_save_low_suction_forward_membership", saved.append)
    with pytest.raises(svc.DataSyncError):
        svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=1)._run_sync_sector_members({})
    assert saved[0].tradable_scope.complete is False
    assert saved[0].records == ()
```

- [x] **Step 2: Make pagination completeness explicit**

Keep `_fetch_all_sector_stocks()` returning a list for existing callers and tests, but raise `DataSyncError` when the provider reports `total` and a later empty page or the page cap leaves `len(items) < total`. Reject duplicate `(symbol, exchange)` identities across pages before the sector can enter the captured denominator.

- [x] **Step 3: Collect only this run's successful member pages**

Inside `_run_sync_sector_members`, add `members_by_sector: dict[str, tuple[dict[str, Any], ...]]`. Write to it under the existing lock only after `_fetch_all_sector_stocks()` and `_upsert_sector_memberships()` both succeed and only when the sector was not marked timed out. After `_bounded_parallel_map`, call:

```python
capture = build_forward_membership_capture(
    sectors=sector_rows,
    members_by_sector=members_by_sector,
    failed_sector_ids=tuple(sorted(failed_sector_id_set)),
    source_trade_date=reliable_date,
    observed_at=observed_at,
)
save_forward_membership_capture(capture)
```

Only attempt this when `reliable_date == observed_at.date()` and the Shanghai time is at or after 15:00. A low-suction validation/persistence error must be logged and leave its scope closed, but must not change whether the shared catalog job succeeds or fails. Preserve the existing `DataSyncError` when any board failed so the downstream shared snapshot remains skipped.

- [x] **Step 4: Verify sync tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: existing shared dependency tests and new low-suction tests pass.

### Task 4: Read Only the Dedicated Tradable Scope

**Files:**
- Modify: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `alphaagent/server/services/low_suction/v2_audit.py`
- Modify: `tests/alphaagent/services/low_suction/test_data_quality.py`
- Modify: `tests/alphaagent/services/low_suction/test_v2_audit.py`

- [x] **Step 1: Write failing source/version/count tests**

```python
def test_forward_membership_requires_current_manifest_version() -> None:
    providers = _build_forward_membership_provider_inventory(
        [_forward_membership_row(manifest_version="stale")],
        reliable_stock_dates=(SOURCE_DATE, NEXT_DATE),
    )
    assert providers[0]["trade_days"] == 0


def test_v2_audit_reads_low_suction_tradable_tables() -> None:
    source = Path("alphaagent/server/services/low_suction/v2_audit.py").read_text()
    assert "low_suction_forward_membership_snapshot_scopes" in source
    assert "low_suction_forward_membership_snapshots" in source
    assert 'scope_type == "concept_tradable"' in source
```

- [x] **Step 2: Switch forward provider aggregation**

Build actual row/sector/symbol/capture-time aggregates from `low_suction_forward_membership_snapshots`. Join only `low_suction_forward_membership_snapshot_scopes.scope_type == "concept_tradable"`. `_complete_forward_membership_capture()` must additionally require `manifest_version == MANIFEST_VERSION`; it must continue requiring strict evidence, complete scope, at least 300 tradable sectors, exact declared/actual row and symbol counts, and one observation timestamp.

- [x] **Step 3: Switch V2 accumulation counts**

Count complete strict dates only from `low_suction_forward_membership_snapshot_scopes` where `scope_type == "concept_tradable"` and `manifest_version == MANIFEST_VERSION`. Count forward rows only from `low_suction_forward_membership_snapshots` with strict evidence. Keep historical strict counts and current-proxy counts separate.

- [x] **Step 4: Verify low-suction audit tests**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_data_quality.py \
  tests/alphaagent/services/low_suction/test_v2_audit.py -q
```

Expected: all tests pass and formal metrics remain `null`.

### Task 5: Real Capture, Audit, and Durable Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_forward_tradable_scope_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-16-low-suction-forward-tradable-scope.md`

- [x] **Step 1: Run the full focused suite and static checks**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_market_snapshot_repository.py -q
uvx ruff check alphaagent/server/services/low_suction alphaagent/server/services/data_sync.py tests/alphaagent/services/low_suction tests/alphaagent/test_data_sync_schedule.py
uv run python -m compileall -q alphaagent/server/services/low_suction alphaagent/server/services/data_sync.py
git diff --check
```

Expected: tests pass, Ruff is clean, compileall is silent, and `git diff --check` is silent.

- [x] **Step 2: Confirm no sync job or schedule is running before rebuilding**

```bash
docker compose exec -T alphaagent-api python -c "from sqlalchemy import select; from alphaagent.server.db import schema; from alphaagent.server.db.session import session_scope; s=session_scope(); x=s.__enter__(); print('jobs', x.execute(select(schema.sync_job_runs.c.id, schema.sync_job_runs.c.job_id).where(schema.sync_job_runs.c.status == 'running')).all()); print('schedules', x.execute(select(schema.sync_batch_schedules.c.id).where(schema.sync_batch_schedules.c.last_status == 'running')).all()); s.__exit__(None,None,None)"
```

Expected: both lists are `[]`. Do not rebuild during a between-job gap while a real schedule remains active.

- [x] **Step 3: Rebuild API, run one member sync, and retain shared failure**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c "from alphaagent.server.services.data_sync import DataSyncRunner; DataSyncRunner(concurrency=8)._run_sync_sector_members({'page_size': 200})"
```

Expected: the command still raises `DataSyncError` for `BK1677/BK1678/BK1679`, preserving shared full-catalog semantics, after writing one complete low-suction `concept_tradable` scope.

- [x] **Step 4: Query scopes and run the V2 audit**

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-audit --format json
```

Expected: forward membership accumulation increases from 0 to 1 actual source day, forward security remains at least 1 day, leader research remains blocked until 720 strict days, locked holdout access remains 0, and formal metrics remain `null`.

- [x] **Step 5: Record evidence and update the plan checkboxes**

Write the exact catalog/tradable counts, failed exact IDs, manifest version, row/symbol counts, timestamps, test totals, and current V2 audit conclusion into `memory/06_backtests/low_suction_forward_tradable_scope_20260716.md`. Update the backtest index and replace stale forward-scope status in `memory/09_decisions/decisions.md`; do not append a chat transcript or claim a trading win rate.

## Self-review

- Spec coverage: exact-ID exclusions, report-board tolerance, narrative/unlabelled fail-closed behavior, manifest metadata, atomicity, non-downgrade, shared job behavior, and strict reader isolation each have a named test and implementation task.
- Placeholder scan: no `TBD`, `TODO`, or unspecified error-handling step remains.
- Type consistency: all tasks use `source_trade_date`, `observed_at`, `expected_sector_count`, `returned_sector_count`, `concept_catalog`, `concept_tradable`, and `MANIFEST_VERSION` consistently.
