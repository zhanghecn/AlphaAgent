# AlphaAgent Tushare DC Historical Concept Membership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Add a fail-closed, exact-code, D-1-lagged historical Eastmoney concept-membership source that can clear the low-suction membership gate only after a real Tushare DC coverage probe passes.

**Architecture:** Keep provider I/O under `services/data_providers`, pure point-in-time normalization under `services/low_suction`, and compressed membership intervals plus per-date/per-sector completeness scopes in dedicated low-suction tables. Reuse shared `sector_daily_bars` by exact `BKxxxx.DC -> BKxxxx` mapping; never fuzzy-match names or import limit-up strategy state.

**Tech Stack:** Python 3.11+, requests, SQLAlchemy Core, PostgreSQL 16, Tushare Pro `dc_index`/`dc_member`, pytest, Docker Compose.

---

## Verified Contract

- Official `dc_member` documentation supports historical constituents by `BKxxxx.DC` and trade date: https://tushare.pro/document/2?doc_id=363.
- Official `dc_index` enumerates each day's concept boards and `idx_type`: https://tushare.pro/document/2?doc_id=362.
- The local canonical index uses the identical `BKxxxx` code and `eastmoney.board_kline` bars.
- `ths_member` cannot query historical constituents and remains rejected.
- The API requires a configured token and 6,000 Tushare points. The current environment has no token, so no real coverage claim is allowed yet.
- Research date D consumes only the previous completed session S membership. S-day membership never explains S-day intraday behavior.

## Fixed Boundaries

```python
DC_INDEX_API = "dc_index"
DC_MEMBER_API = "dc_member"
DC_MEMBER_SOURCE = "tushare.dc_member.lag1"
DC_MEMBER_ROW_LIMIT = 5_000
DC_SECTOR_SUFFIX = ".DC"
MIN_EXACT_SECTOR_MAPPING_PCT = 99.0
```

- `TUSHARE_TOKEN` is read from existing settings and never returned by APIs or logs.
- A missing token returns `unconfigured`; it does not create tables or write proxy rows.
- Full backfill is forbidden until the dry-run probe passes exact mapping, date reach, response completeness, and lag checks.
- Current `stock_sector_membership_snapshots` remains a proxy source and is not overwritten.
- Formal metrics remain `null` after membership passes until security status and candidate minutes also pass.

### Task 1: Add A Read-only Tushare DC Client And Status Probe

**Files:**
- Create: `alphaagent/server/services/data_providers/tushare_dc_membership.py`
- Create: `tests/alphaagent/services/low_suction/test_tushare_dc_membership_source.py`

- [x] **Step 1: Write exact mapping and missing-token tests**

```python
def test_dc_sector_code_mapping_is_exact_and_reversible() -> None:
    assert local_sector_id("BK1184.DC") == "BK1184"
    assert tushare_sector_code("BK1184") == "BK1184.DC"
    with pytest.raises(ValueError):
        local_sector_id("880728.TDX")


def test_source_status_does_not_expose_or_use_a_missing_token() -> None:
    status = dc_membership_source_status(token="")
    assert status["status"] == "unconfigured"
    assert status["configured"] is False
    assert "token" not in json.dumps(status).lower()
```

- [x] **Step 2: Run the tests and verify they fail because the module is absent**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_tushare_dc_membership_source.py -q
```

- [x] **Step 3: Implement the minimal client contract**

```python
def local_sector_id(ts_code: str) -> str:
    normalized = str(ts_code).strip().upper()
    if not normalized.startswith("BK") or not normalized.endswith(DC_SECTOR_SUFFIX):
        raise ValueError("Tushare DC sector code must be BKxxxx.DC")
    return normalized.removesuffix(DC_SECTOR_SUFFIX)


def tushare_sector_code(sector_id: str) -> str:
    normalized = str(sector_id).strip().upper()
    if not normalized.startswith("BK") or "." in normalized:
        raise ValueError("local sector ID must be an unsuffixed BK code")
    return f"{normalized}{DC_SECTOR_SUFFIX}"


def dc_membership_source_status(*, token: str) -> dict[str, object]:
    configured = bool(token.strip())
    return {
        "status": "ready_for_probe" if configured else "unconfigured",
        "configured": configured,
        "required_points": 6_000,
        "apis": [DC_INDEX_API, DC_MEMBER_API],
        "strict_ready": False,
    }
```

The HTTP method must POST the existing Tushare payload shape
`{"api_name", "token", "params", "fields"}`, reject non-zero response codes, require
`data.fields` and `data.items`, and map fields to rows without logging the payload token.

- [x] **Step 4: Add mocked `dc_index` and `dc_member` response tests**

Assert that a non-zero provider code raises `TushareDcQueryError`, duplicate field names are rejected,
and a 5,000-row response carries `limit_reached=True` rather than being treated as complete.

- [x] **Step 5: Run the source tests**

Run the command from Step 2. Expected: all tests pass without network access.

### Task 2: Normalize D-1 Daily Snapshots Into Point-in-time Intervals

**Files:**
- Create: `alphaagent/server/services/low_suction/dc_membership_normalization.py`
- Create: `tests/alphaagent/services/low_suction/test_dc_membership_normalization.py`
- Modify: `alphaagent/server/services/low_suction/historical_inputs.py`

- [x] **Step 1: Write lag and compression tests**

```python
def test_source_session_only_becomes_effective_on_next_session() -> None:
    rows = normalize_dc_snapshot(
        source_trade_date=date(2026, 7, 14),
        effective_trade_date=date(2026, 7, 15),
        sector_id="BK1184",
        members=[{"con_code": "600001.SH", "name": "A"}],
    )
    assert rows[0]["in_date"] == date(2026, 7, 15)
    assert rows[0]["known_at"].date() == date(2026, 7, 14)
    assert rows[0]["vt_symbol"] == "600001.SSE"


def test_disappearing_member_closes_interval_at_next_effective_session() -> None:
    intervals = compress_daily_memberships(
        effective_dates=(date(2026, 7, 15), date(2026, 7, 16)),
        daily_members={
            date(2026, 7, 15): {("BK1184", "600001.SSE")},
            date(2026, 7, 16): set(),
        },
    )
    assert intervals[0].in_date == date(2026, 7, 15)
    assert intervals[0].out_date == date(2026, 7, 16)
```

- [x] **Step 2: Run the tests and verify the functions are missing**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_dc_membership_normalization.py -q
```

- [x] **Step 3: Implement exact exchange and lag normalization**

Only `.SH -> .SSE`, `.SZ -> .SZSE`, and `.BJ -> .BSE` conversions are accepted. Keep all
source rows for completeness auditing, but the later low-suction universe filters out BSE,
ChiNext, and STAR stocks. Set `known_at` to source session 23:59 Asia/Shanghai and preserve the
actual fetch time separately in raw provenance.

Extend `HistoricalMembershipRecord`, `HistoricalMembershipScope`, and
`HistoricalMembershipBatch` with one consistent `evidence_level`. Accept only `strict`,
`reconstructed`, or `invalid`; a batch with mixed levels is rejected. The DC source may emit
`strict` only after its current requested range passes the probe.

- [x] **Step 4: Compress only consecutive effective sessions**

Use the supplied trading calendar, not calendar-day arithmetic. A disappearance and later
reappearance must create two intervals. Generate deterministic source record IDs from source,
sector, symbol, interval start, and interval end.

- [x] **Step 5: Run normalization and historical-input tests**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_dc_membership_normalization.py \
  tests/alphaagent/services/low_suction/test_historical_inputs.py -q
```

### Task 3: Persist Compressed History And Complete Scopes Atomically

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/low_suction/membership_history_repository.py`
- Create: `tests/alphaagent/services/low_suction/test_membership_history_repository.py`

- [x] **Step 1: Write repository atomicity and scope tests**

Test that one provider/date range replaces both history and scopes in one transaction, records
outside the declared sector/date scope are rejected, and a duplicate `source_record_id` fails
before any SQL is executed.

- [x] **Step 2: Add dedicated tables**

```python
low_suction_concept_membership_history = Table(
    "low_suction_concept_membership_history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("sector_id", String(64), nullable=False),
    Column("sector_name", String(160), nullable=False),
    Column("vt_symbol", String(32), nullable=False),
    Column("in_date", Date, nullable=False),
    Column("out_date", Date, nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_record_id", String(240), nullable=False, unique=True),
    Column("raw", JSONB, nullable=False, server_default="{}"),
)

low_suction_concept_membership_scopes = Table(
    "low_suction_concept_membership_scopes",
    metadata,
    Column("trade_date", Date, primary_key=True),
    Column("sector_id", String(64), primary_key=True),
    Column("source_trade_date", Date, nullable=False),
    Column("expected_member_count", Integer, nullable=False),
    Column("returned_member_count", Integer, nullable=False),
    Column("pagination_complete", Boolean, nullable=False),
    Column("known_at", DateTime(timezone=True), nullable=False),
    Column("evidence_level", String(24), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_request_id", String(240), nullable=False, unique=True),
)
```

Add indexes for `(sector_id, in_date, out_date)`, `(vt_symbol, in_date, out_date)`, and
`(evidence_level, trade_date)`.

- [x] **Step 3: Implement `replace_membership_history(batch)`**

Validate through `import_historical_memberships` first. Delete and insert the selected provider's
declared range inside one `session_scope`; never delete current proxy snapshots or another provider.

- [x] **Step 4: Run repository and schema tests**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_membership_history_repository.py -q
```

### Task 4: Build A Bounded Probe And Adaptive Backfill Service

**Files:**
- Create: `alphaagent/server/services/low_suction/dc_membership_import.py`
- Create: `tests/alphaagent/services/low_suction/test_dc_membership_import.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] **Step 1: Write fail-closed probe tests**

Cover missing token, a requested source date absent from `dc_index`, a `.DC` code collision,
an active local BK code absent from DC, duplicate constituents, and a response window that still
hits 5,000 rows at one date. Every case must return `strict_ready=False` and write nothing.

- [x] **Step 2: Implement required-pair construction**

For each reliable research date D after the first, set S to the previous reliable date. Query
`dc_index(trade_date=S, idx_type="概念板块")`, strip `.DC`, and intersect by exact code with local
concepts whose canonical index bounds include D. Record unmapped and name-conflict manifests.

- [x] **Step 3: Implement adaptive member windows**

Query one sector over a bounded source-date window. If the result count reaches 5,000, split the
window in half and retry; a one-date response at 5,000 is a hard failure. Require every expected
source-date/sector pair to have a distinct-member response before normalization.

- [x] **Step 4: Add CLI commands**

```text
membership-source-status
membership-probe --start YYYY-MM-DD --end YYYY-MM-DD --format json
membership-backfill --start YYYY-MM-DD --end YYYY-MM-DD --dry-run
membership-backfill --start YYYY-MM-DD --end YYYY-MM-DD --write
```

`--write` must refuse to run unless the same requested range passes the probe in the current
process. Default maximum dates are 5 for probe and 20 for write; explicit larger runs are capped
at 800 reliable dates.

- [x] **Step 5: Run import and CLI tests**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_dc_membership_import.py \
  tests/alphaagent/services/low_suction/test_reporting.py -q
```

### Task 5: Select Strict Membership Coverage Without Mixing Proxy Rows

**Files:**
- Modify: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `tests/alphaagent/services/low_suction/test_data_quality.py`

- [x] **Step 1: Write strict-provider selection tests**

Create a 799-day strict provider and three current proxy snapshots. Assert the audit selects only
the strict provider, reports its own rows/dates/coverage, and does not lower mode because proxy rows
also exist. Add a partial strict provider and assert the proxy remains visible but the formal gate
stays closed.

- [x] **Step 2: Implement provider-isolated coverage**

Aggregate scopes and active history by `(evidence_level, source)`, calculate complete required
pairs, sector/date coverage, and choose the best qualifying strict provider. Fall back to current
proxy coverage only when no strict provider qualifies. Never sum sources into one numerator.

- [x] **Step 3: Run the full low-suction suite**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
```

### Task 6: Execute The Real Pilot Before Any Full Backfill

**Files:**
- Create after a real run: `memory/06_backtests/low_suction_dc_membership_probe_YYYYMMDD.md`
- Modify after a real run: `memory/06_backtests/low_suction_data_quality_20260716.md`
- Modify after a real run: `memory/09_decisions/decisions.md`

> Runtime status on 2026-07-16: configuration verification is complete. Steps 2-5 are
> blocked because `TUSHARE_TOKEN` is absent and the provider requires 6,000 points.
> No probe/backfill rows were written; both dedicated membership tables remain empty.

- [x] **Step 1: Verify configuration without exposing the token**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli membership-source-status
```

Expected before credentials are supplied: `status=unconfigured`, `strict_ready=false`.

- [ ] **Step 2: Probe five sentinel source dates**

Use the beginning, two interior dates, the newest completed date, and one date containing a newly
created BK concept. Require exact mapping at least 99%, no collisions, no response truncation, and
complete scope manifests. A failure ends the run without writes.

- [ ] **Step 3: Compare overlapping same-day membership**

For `2026-07-13..2026-07-15`, compare Tushare DC source snapshots with stored Eastmoney snapshots
by exact sector and symbol. Report per-board Jaccard, missing codes, and name conflicts. Do not set a
hard global match threshold until differences are inspected, but any unexplained systematic date
shift blocks full backfill.

- [ ] **Step 4: Run the bounded dry-run and then full write only if the pilot passes**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli membership-backfill \
  --start 2023-03-28 --end 2026-07-15 --dry-run
```

Repeat with `--write` only when the dry-run report is `ready_for_atomic_replace`.

- [ ] **Step 5: Re-run the strict audit**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json
```

Expected only after successful coverage: `historical_concept_membership` is absent. Security status
and candidate minutes remain blockers, and `formal_metrics` remains `null`.

## Completion Boundary

This plan ends when one exact, lagged membership provider has reproducible three-year coverage.
It does not decide eligible themes, generate Top3 candidates, fetch minutes, tune entries/exits,
or create a low-suction product tab.
