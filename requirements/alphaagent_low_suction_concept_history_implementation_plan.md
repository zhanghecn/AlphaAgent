# AlphaAgent Low-Suction Shared Concept Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Reuse AlphaAgent's existing Eastmoney concept-index history, backfill at least 800 sessions, and let the independent low-suction package dynamically calculate main-rise states and Top3 leaders without creating a second index ontology.

**Architecture:** `sector_daily_bars` remains the only official board-index table shared by limit-up, mainline, and low-suction research. The shared sync job fetches a bounded 800-session canonical history and bulk-upserts it; low-suction reads the raw table and computes main-rise state from data visible through D. Index history and constituent history remain separate contracts: forward D uses the frozen D-1 member snapshot, while a formal historical Top3 backtest requires point-in-time historical members.

**Tech Stack:** Python 3.11+, Eastmoney board K-line API, pandas, SQLAlchemy Core, PostgreSQL 16, pytest.

---

## Verified Baseline And Result

- `sector_daily_bars` currently stores `eastmoney.board_kline`, not an internally synthesized concept series.
- Before this plan, raw concept coverage was 253 sessions from `2025-06-17` through `2026-07-01`; only 72 dates met the fixed-catalog 90% cross-section gate.
- Before this plan, the sync job defaulted to `limit=250` and the adapter deliberately tailed the response to that limit.
- A read-only live request for `BK0490` with `limit=800` returned 800 canonical rows from `2023-03-28` through `2026-07-16`.
- `services/low_suction/main_rise.py` already derives MA10/MA20 slopes, 5-day returns, cycle IDs, and state using only current and earlier concept bars.
- `services/low_suction/leader_rank.py` already ranks members at each cutoff. It must still receive the member set valid for that date; an index bar cannot prove stock membership by itself.
- The completed backfill read and wrote 334,283 rows across 495 boards, with 0 failures, 3 empty boards, and 0 fallback boards.
- Through the completed-session cutoff `2026-07-15`, the dynamic audit has 799 complete dates from `2023-03-28`, a 1,205-day calendar span, and `99.7567%` minimum coverage. `concept_index_history` is no longer blocking.
- Dynamic main-rise calculation completed for 333,871 canonical rows and 498 indexed boards. It produced 94,503 confirmed state rows; 44 boards were in main rise on `2026-07-15`.
- Eastmoney labels both real themes and event-style boards such as "昨日连板" as `concept`. Coverage keeps the canonical catalog intact; product eligibility needs a separate evidence-backed rule.

## Fixed Boundary

```python
SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS = 800
SECTOR_DAILY_MAX_HISTORY_SESSIONS = 1_000
STRICT_MIN_TRADE_DAYS = 720
STRICT_MIN_CALENDAR_DAYS = 1_095
```

- Do not create a low-suction concept-index table.
- Do not map JQData `SC/GN` codes to Eastmoney `BK` codes by name.
- Do not call an internal member-stock aggregation an official concept index.
- D-close main-rise state can produce a candidate no earlier than D+1.
- Forward D intraday ranking uses the most recent complete member snapshot with `snapshot_date < D`.
- Historical Top3 remains `membership_proxy` unless the D-day member set is point-in-time historical evidence.

### Task 1: Extend the Shared Index Sync Safely

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/data_sources/akshare_adapter.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `tests/alphaagent/test_akshare_adapter.py`

- [x] **Step 1: Write failing default-history and filter tests**

```python
def test_sector_index_history_defaults_to_800_sessions() -> None:
    job = next(item for item in svc.DEFAULT_JOBS if item.id == "sync_sector_daily_bars")
    assert job.default_params["limit"] == 800


def test_sector_daily_sync_can_target_concept_types(monkeypatch) -> None:
    runner = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)
    runner._run_sync_sector_daily_bars(
        {"limit": 800, "sector_types": ["concept", "theme"]}
    )
    assert seen_types == {"concept", "theme"}
```

- [x] **Step 2: Bound and propagate the requested history length**

Add `SECTOR_DAILY_DEFAULT_HISTORY_SESSIONS = 800` and
`SECTOR_DAILY_MAX_HISTORY_SESSIONS = 1_000`. `DataSyncRunner` clamps `limit` to this
range and filters only when `sector_types` is explicitly supplied. The adapter uses the
same default and keeps the canonical `eastmoney.board_kline` source check.

- [x] **Step 3: Replace per-row reads with one PostgreSQL upsert per sector**

```python
statement = postgresql_insert(schema.sector_daily_bars).values(values)
statement = statement.on_conflict_do_update(
    index_elements=["sector_id", "trade_date"],
    set_={
        column: getattr(statement.excluded, column)
        for column in (
            "open_price",
            "close_price",
            "high_price",
            "low_price",
            "volume",
            "turnover",
            "change_pct",
            "source",
            "raw",
        )
    }
    | {"updated_at": func.now()},
)
session.execute(statement)
```

Normalize duplicate provider dates before creating the statement, keeping the last
valid row. The canonical source may delete non-canonical rows only for the same sector.

- [x] **Step 4: Run focused sync tests**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_akshare_adapter.py \
  tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: all tests pass, including canonical-source rejection and full-sector coverage.

### Task 2: Backfill and Measure the Shared History

**Files:**
- Create: `alphaagent/server/services/low_suction/concept_index_coverage.py`
- Create: `tests/alphaagent/services/low_suction/test_concept_index_coverage.py`
- Modify: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `alphaagent/server/services/low_suction/repository.py`
- Modify: `memory/06_backtests/low_suction_data_quality_20260716.md`
- Create: `memory/06_backtests/low_suction_concept_index_backfill_20260716.md`

- [x] **Step 1: Rebuild and verify the API container**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c \
  "import baostock, urllib.request; print(urllib.request.urlopen('http://localhost:8000/api/health').status)"
```

Expected: HTTP `200` and no startup/schema error.

- [x] **Step 2: Run the bounded concept/theme backfill**

```bash
docker compose exec -T alphaagent-api python -c \
  "from alphaagent.server.services.data_sync import DataSyncRunner; print(DataSyncRunner(concurrency=8)._run_sync_sector_daily_bars({'limit': 800, 'sector_types': ['concept', 'theme']}))"
```

The runner must keep existing rows when a board request fails and reject non-canonical
fallback rows. The strict data-quality gate, rather than the network runner, decides
whether historical daily cross-sections reach 90%.

- [x] **Step 3: Replace the fixed current-catalog denominator**

```python
@dataclass(frozen=True)
class ConceptDateCoverage:
    trade_date: date
    actual_concepts: int
    expected_active_concepts: int
    coverage_pct: float
    qualifies: bool
```

For each date, expected concepts are canonical Eastmoney boards satisfying
`first_bar_date <= D <= last_bar_date`. A date qualifies only when at least 300 concepts
are active and `actual / expected >= 90%`. This excludes the one-board tail before the
common 800-session window while avoiding the future-catalog error of requiring concepts
before their first index bar. Both the data-quality audit and research repository call
the same pure helper.

- [x] **Step 4: Re-run the low-suction data audit**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli audit --format json
```

Record raw and 90%-complete trade days, range, sector count, failed/empty boards, and
whether `concept_index_history` clears the 720-session/1,095-day gate. Do not change the
gate after seeing the result.

### Task 3: Keep Historical and Forward Membership Modes Separate

**Files:**
- Modify when a historical source exists: `alphaagent/server/services/low_suction/repository.py`
- Test when a historical source exists: `tests/alphaagent/services/low_suction/test_daily_discovery.py`

- [ ] **Step 1: Forward dynamic mode**

For a live or forward D calculation, load exactly one complete snapshot with
`snapshot_date < D`, freeze its member digest for the session, calculate current stock
features, and call `rank_concept_leaders(..., membership_mode="strict")`. Missing or
incomplete snapshots block Top3 rather than falling back to current members.

- [ ] **Step 2: Historical strict mode**

For a historical D calculation, load interval or snapshot evidence valid at D open.
Current `stock_sector_memberships` remains `current_proxy`; it cannot fill a missing
historical date. Tests must prove changing a later member snapshot cannot change an
earlier D ranking.

- [x] **Step 3: Preserve dynamic calculation ownership**

`main_rise.py` and `leader_rank.py` remain pure low-suction calculations. They read the
shared raw index/member inputs but do not import limit-up strategy rules, candidates,
cash ledgers, or performance results.

### Task 4: Strict Retest After Both Inputs Qualify

**Files:**
- Modify after Tasks 2 and 3 qualify: `alphaagent/server/services/low_suction/repository.py`
- Create after qualification: `memory/06_backtests/low_suction_strict_retest_<as_of>.md`

- [ ] Use only main-rise concepts and point-in-time Top3 main-board leaders.
- [ ] Freeze `first_bearish_or_break_repair` as the first retest family; keep Rank 4-10 and non-main-rise controls.
- [ ] Fill only candidate minute windows and compare the pre-registered D+1/D+3/D+5 exits.
- [ ] Emit exactly one result: `blocked_by_data_quality`, `no_qualified_strategy`, or `qualified_research_rule`.

## Completion Boundary

Task 2 can clear the concept-index-history gap without another provider. It cannot by
itself clear `historical_concept_membership`: an official index says how the concept
moved, but not which stocks belonged to it on every historical date. Forward dynamic
research can start from accumulated D-1 snapshots; formal historical Top3 metrics wait
for point-in-time member evidence.
