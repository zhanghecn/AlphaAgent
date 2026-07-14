# AlphaAgent Limit-Up Realtime Concept Resonance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a no-lookahead realtime concept-resonance pipeline that freezes D-1 stock-concept memberships, refreshes the full A-share quote universe every 30 seconds, evaluates every 5% main-board radar stock before Top5 selection, and exposes stable pre-limit states on `/limit-up`.

**Status:** Implemented and engineering-verified on 2026-07-14. Performance impact remains subject to the design's 20/60-trading-day forward validation.

**Architecture:** Add one bounded full-market quote API, a pure concept aggregation module, an append-only concept snapshot repository, and an isolated runtime refresh service. The existing 15-second limit-up scanner reads the latest atomic concept snapshot, evaluates all radar candidates, and only then applies ranking and the two-position portfolio boundary.

**Tech Stack:** Python 3.11, SQLAlchemy Core, PostgreSQL JSONB, FastAPI services, pytest, React 18, TypeScript, TanStack Query, Vitest, Docker Compose.

---

## Execution Constraints

- Preserve the existing dirty worktree. Read overlapping diffs before every edit and never revert unrelated user changes.
- Do not modify `vnpy/` or official examples.
- Do not run `git commit` or `git push` unless the user explicitly authorizes it. This project rule overrides generic plan templates; each task ends with a diff/test checkpoint instead.
- Keep the feature `research_only`. A realtime research trigger is not an automatic order or a fill guarantee.
- Do not change the existing historical cash-backtest baseline while adding the realtime concept path.
- Use the approved design in `requirements/alphaagent_limit_up_realtime_concept_resonance_design.md` as the behavioral source of truth.

## File Map

**Create**

- `alphaagent/server/services/limit_up/concept_resonance.py`: pure membership filtering, concept aggregation, percentile scoring, leader ranking, and candidate attachment.
- `alphaagent/server/services/limit_up/concept_snapshot_repository.py`: D-1 membership loading, append-only concept snapshot persistence, as-of reads, and retention.
- `alphaagent/server/services/limit_up/concept_live_service.py`: atomic in-memory runtime snapshot, 30-second refresh orchestration, stale handling, and replay read helpers.
- `tests/alphaagent/test_limit_up_concept_resonance.py`: pure calculation and no-lookahead tests.
- `tests/alphaagent/test_limit_up_concept_live.py`: runtime cache, persistence selection, and stale/failure tests.

**Modify**

- `alphaagent/data_sources/akshare_adapter.py`: bounded concurrent all-market quote fetch.
- `alphaagent/server/db/schema.py`: `limit_up_concept_strength_snapshots` table.
- `alphaagent/server/services/data_sync.py`: 30-second concept scan schedule and daily membership-version creation.
- `alphaagent/server/services/limit_up/live_repository.py`: stop selecting style labels as primary execution sectors.
- `alphaagent/server/services/limit_up/live_service.py`: consume the concept runtime snapshot and evaluate the full radar before ranking.
- `alphaagent/server/services/limit_up/live_policy.py`: replace stale static sector gates with explicit realtime concept checks.
- `alphaagent/server/services/limit_up/lane_research.py`: prefer realtime concept strength for live first-board context and separate evaluation time from first-touch time.
- `alphaagent/server/services/limit_up/live_trace_repository.py`: persist concept evidence for every radar candidate and signal.
- `alphaagent/server/services/limit_up/live_trace_service.py`: add concept warming transitions and correct Top5 semantics after all-candidate evaluation.
- `frontend/src/api/limitUp.ts`: concept evidence and new state types.
- `frontend/src/features/limitUp/livePortfolio.ts`: show the two-position portfolio plus a bounded persistent observation set.
- `frontend/src/features/limitUp/nextSessionPlan.ts`: concept-warming presentation.
- `frontend/src/features/limitUp/liveTrace.ts`: concept-warming trace label and ordering.
- `frontend/src/pages/LimitUpPage.tsx`: compact concept evidence in the existing single list.
- Relevant existing test files listed in the tasks below.
- `memory/03_data/data_flow.md`, `memory/05_runtime/run_debug.md`, `memory/06_backtests/README.md`, and `memory/09_decisions/decisions.md`: current-state documentation after verification.

### Task 1: Add a bounded concurrent full-market quote source

**Files:**
- Modify: `alphaagent/data_sources/akshare_adapter.py:35-50,201-257,902-918,2233-2246`
- Test: `tests/alphaagent/test_akshare_adapter.py`

- [x] **Step 1: Write the failing pagination and deduplication test**

```python
def test_all_stock_quotes_fetches_every_page_and_deduplicates(monkeypatch):
    import pandas as pd
    import alphaagent.data_sources.akshare_adapter as adapter_module

    pages = {
        0: ([{"code": "sh600000", "name": "浦发银行", "zxj": "10", "zdf": "1"}], 3),
        200: ([{"code": "sz000001", "name": "平安银行", "zxj": "11", "zdf": "2"}], 3),
        400: ([{"code": "sh600000", "name": "浦发银行", "zxj": "10", "zdf": "1"}], 3),
    }

    def fake_page(_module, offset, count, sort="price"):
        assert count == 200
        assert sort == "price"
        rows, total = pages[offset]
        return pd.DataFrame(rows), total

    monkeypatch.setattr(adapter_module, "_stock_zh_a_spot_tx_page", fake_page)
    payload = adapter_module.AkShareAdapter()._all_stock_quotes_uncached(max_workers=2)

    assert payload["total"] == 2
    assert {item["vt_symbol"] for item in payload["items"]} == {
        "600000.SSE",
        "000001.SZSE",
    }
    assert payload["source"] == "tencent.full_a_share_pages"
```

- [x] **Step 2: Run the focused test and verify the method is missing**

Run: `uv run --group server pytest tests/alphaagent/test_akshare_adapter.py::test_all_stock_quotes_fetches_every_page_and_deduplicates -q`

Expected: FAIL because `_all_stock_quotes_uncached` does not exist.

- [x] **Step 3: Implement the public cached method and concurrent page collector**

Add the following interface, preserving the existing page helper and `ThreadPoolExecutor` imports:

```python
FULL_MARKET_TTL_SECONDS = 20
FULL_MARKET_PAGE_SIZE = 200
FULL_MARKET_MAX_WORKERS = 6


def all_stock_quotes(self, max_workers: int = FULL_MARKET_MAX_WORKERS) -> dict[str, Any]:
    workers = min(max(int(max_workers), 1), FULL_MARKET_MAX_WORKERS)
    return market_cache.get_or_set(
        f"all_stock_quotes:{workers}",
        FULL_MARKET_TTL_SECONDS,
        lambda: self._all_stock_quotes_uncached(max_workers=workers),
    )


def _all_stock_quotes_uncached(self, *, max_workers: int) -> dict[str, Any]:
    module = importlib.import_module("akshare.stock.stock_zh_a_tx")
    first, total = _stock_zh_a_spot_tx_page(
        module,
        offset=0,
        count=FULL_MARKET_PAGE_SIZE,
        sort="price",
    )
    expected = max(int(total or len(first)), len(first))
    page_offsets = list(range(FULL_MARKET_PAGE_SIZE, expected, FULL_MARKET_PAGE_SIZE))
    frames = [first]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _stock_zh_a_spot_tx_page,
                module,
                offset,
                FULL_MARKET_PAGE_SIZE,
                "price",
            ): offset
            for offset in page_offsets
        }
        for future in as_completed(futures):
            frame, _ = future.result()
            frames.append(frame)

    rows: dict[str, dict[str, Any]] = {}
    for frame in frames:
        for raw in _all_records(frame):
            item = _stock_row_to_api(raw)
            symbol = str(item.get("vt_symbol") or "")
            if symbol:
                rows[symbol] = item
    captured_at = datetime.now(timezone.utc)
    return {
        "trade_date": captured_at.astimezone().date().isoformat(),
        "updated_at": captured_at.isoformat(),
        "items": list(rows.values()),
        "total": len(rows),
        "source": "tencent.full_a_share_pages",
    }
```

Define these as methods on `AkShareAdapter`; keep constants at module scope. If one page fails, raise the error so the runtime service keeps the previous complete snapshot instead of publishing partial coverage.

- [x] **Step 4: Add a failure-integrity test**

```python
def test_all_stock_quotes_rejects_a_partial_page_failure(monkeypatch):
    import pandas as pd
    import alphaagent.data_sources.akshare_adapter as adapter_module

    def fake_page(_module, offset, count, sort="price"):
        if offset:
            raise TimeoutError("page timed out")
        return pd.DataFrame([{"code": "sh600000", "name": "浦发银行"}]), 201

    monkeypatch.setattr(adapter_module, "_stock_zh_a_spot_tx_page", fake_page)
    with pytest.raises(TimeoutError, match="page timed out"):
        adapter_module.AkShareAdapter()._all_stock_quotes_uncached(max_workers=2)
```

- [x] **Step 5: Run adapter tests and the diff checkpoint**

Run: `uv run --group server pytest tests/alphaagent/test_akshare_adapter.py -q`

Expected: PASS.

Run: `git diff --check -- alphaagent/data_sources/akshare_adapter.py tests/alphaagent/test_akshare_adapter.py`

Expected: no output.

### Task 2: Implement pure realtime concept aggregation

**Files:**
- Create: `alphaagent/server/services/limit_up/concept_resonance.py`
- Create: `tests/alphaagent/test_limit_up_concept_resonance.py`

- [x] **Step 1: Write failing tests for style filtering, breadth, and PCB grouping**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up.concept_resonance import (
    aggregate_concept_strength,
    build_membership_index,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_membership_index_keeps_pcb_and_excludes_style_labels():
    index = build_membership_index(
        [
            {"vt_symbol": "600183.SSE", "sector_id": "BK0877", "sector_name": "PCB", "sector_type": "theme"},
            {"vt_symbol": "600183.SSE", "sector_id": "BK0821", "sector_name": "MSCI中国", "sector_type": "theme"},
            {"vt_symbol": "002463.SZSE", "sector_id": "BK0877", "sector_name": "PCB", "sector_type": "theme"},
        ],
        snapshot_date="2026-07-13",
    )

    assert index["snapshot_date"] == "2026-07-13"
    assert index["by_symbol"]["600183.SSE"] == ["BK0877"]
    assert index["by_concept"]["BK0877"]["members"] == {
        "600183.SSE",
        "002463.SZSE",
    }


def test_aggregate_concept_strength_calculates_realtime_pcb_diffusion():
    membership = build_membership_index(
        [
            {"vt_symbol": f"60000{i}.SSE", "sector_id": "BK0877", "sector_name": "PCB", "sector_type": "theme"}
            for i in range(5)
        ],
        snapshot_date="2026-07-13",
    )
    quotes = [
        {"vt_symbol": f"60000{i}.SSE", "name": f"PCB{i}", "change_pct": change, "turnover": 100_000_000 + i}
        for i, change in enumerate((9.9, 8.2, 6.5, 5.1, -1.0))
    ]

    rows = aggregate_concept_strength(
        quotes,
        membership,
        captured_at=datetime(2026, 7, 14, 13, 3, tzinfo=SHANGHAI),
        history_by_concept={},
    )

    pcb = next(row for row in rows if row["concept_id"] == "BK0877")
    assert pcb["observed_count"] == 5
    assert pcb["coverage_ratio"] == 1.0
    assert pcb["rise_count"] == 4
    assert pcb["strong_5_count"] == 4
    assert pcb["median_change_pct"] == 6.5
```

- [x] **Step 2: Run the tests and verify the module is missing**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_concept_resonance.py -q`

Expected: collection FAIL with `ModuleNotFoundError`.

- [x] **Step 3: Implement membership filtering and raw aggregation**

Create constants and pure functions with these interfaces:

```python
STYLE_CONCEPT_KEYWORDS = (
    "MSCI", "中证", "沪深300", "上证50", "深证100", "大盘股", "中盘股", "小盘股",
    "成长", "价值", "风格", "热股", "融资融券", "沪股通", "深股通", "昨日",
    "年报", "季报", "预增", "扭亏", "高振幅", "高换手",
)


def is_execution_concept(name: str) -> bool:
    value = str(name or "").strip()
    return bool(value) and not any(keyword in value for keyword in STYLE_CONCEPT_KEYWORDS)


def build_membership_index(rows, *, snapshot_date):
    by_symbol: dict[str, list[str]] = defaultdict(list)
    by_concept: dict[str, dict[str, object]] = {}
    for row in rows:
        symbol = str(row.get("vt_symbol") or "").upper()
        concept_id = str(row.get("sector_id") or "")
        concept_name = str(row.get("sector_name") or concept_id)
        if not symbol or not concept_id or not is_execution_concept(concept_name):
            continue
        if not is_eligible_main_board(symbol, str(row.get("stock_name") or "")):
            continue
        by_symbol[symbol].append(concept_id)
        concept = by_concept.setdefault(
            concept_id,
            {"concept_id": concept_id, "concept_name": concept_name, "members": set()},
        )
        concept["members"].add(symbol)
    return {
        "snapshot_date": str(snapshot_date)[:10],
        "by_symbol": {symbol: sorted(set(values)) for symbol, values in by_symbol.items()},
        "by_concept": by_concept,
    }
```

Implement `aggregate_concept_strength` by building one quote map, iterating each concept's frozen member set once, and returning numeric fields named in the approved design. Use `statistics.mean` and `statistics.median`; compute coverage as observed members divided by frozen members. A quote with `change_pct is None` is not observed.

- [x] **Step 4: Add acceleration and cross-sectional percentile tests**

```python
def test_concept_strength_uses_only_earlier_frames_for_acceleration():
    history = {
        "BK0877": [
            {"captured_at": "2026-07-14T13:00:00+08:00", "median_change_pct": 1.0, "turnover": 1_000.0},
            {"captured_at": "2026-07-14T13:02:00+08:00", "median_change_pct": 2.0, "turnover": 2_000.0},
        ]
    }
    row = _pcb_row(captured_at="2026-07-14T13:03:00+08:00", history=history)

    assert row["change_acceleration_1m"] == 1.0
    assert row["change_acceleration_3m"] == 2.0
    assert row["turnover_acceleration_1m"] > 0


def test_rank_concepts_assigns_best_strength_to_lowest_percentile():
    ranked = rank_concepts([
        _concept("A", median=4.0, rise_ratio=0.9, strong_5=5),
        _concept("B", median=1.0, rise_ratio=0.6, strong_5=1),
    ])

    assert ranked[0]["concept_id"] == "A"
    assert ranked[0]["strength_rank"] == 1
    assert ranked[0]["strength_percentile"] == 0.5
```

Define `_pcb_row` and `_concept` as local test helpers with complete quote and membership payloads.

- [x] **Step 5: Implement deterministic scoring and concept states**

Use percentile-normalized components and freeze the initial research-only weights in code:

```python
CONCEPT_WARMING_MAX_PERCENTILE = 0.05
CONCEPT_LAUNCH_MAX_PERCENTILE = 0.03
CONCEPT_MIN_COVERAGE_RATIO = 0.90


def concept_state(row):
    if row["coverage_ratio"] < CONCEPT_MIN_COVERAGE_RATIO:
        return "unavailable"
    failed_rate = row["failed_count"] / max(row["touched_count"], 1)
    if row["touched_count"] >= 3 and failed_rate > 0.35:
        return "ebb"
    if (
        row["strength_percentile"] <= CONCEPT_LAUNCH_MAX_PERCENTILE
        and row["strong_5_count"] >= 3
        and (row["near_limit_count"] >= 1 or row["strong_7_count"] >= 2)
    ):
        return "launch"
    if (
        row["strength_percentile"] <= CONCEPT_WARMING_MAX_PERCENTILE
        and row["strong_5_count"] >= 2
        and (row["change_acceleration_3m"] or 0) > 0
    ):
        return "warming"
    return "observe"
```

Score price strength, breadth, 5% diffusion, near-limit diffusion, 3-minute price acceleration, turnover acceleration, and seal quality. Keep the total bounded to `[0, 100]`; attach `strength_rank`, `strength_percentile`, and `concept_state` after sorting.

- [x] **Step 6: Add and implement candidate concept selection and leader ranks**

Test that one PCB stock assigned to both PCB and MSCI receives PCB, and that concept leader ranks follow point-in-time price/turnover evidence:

```python
def test_attach_candidate_concepts_selects_strongest_execution_concept():
    candidates = [{"vt_symbol": "600183.SSE", "change_pct": 9.2, "turnover": 5_000_000_000}]
    snapshot = {
        "membership": {"by_symbol": {"600183.SSE": ["BK0877"]}},
        "concepts_by_id": {"BK0877": {"concept_id": "BK0877", "concept_name": "PCB", "concept_state": "launch", "strength_score": 92.0}},
    }

    attach_candidate_concepts(candidates, snapshot)

    assert candidates[0]["concept_id"] == "BK0877"
    assert candidates[0]["concept_name"] == "PCB"
    assert candidates[0]["concept_leader_rank"] == 1
```

Implement `attach_candidate_concepts(candidates, snapshot)` in the pure module. It must copy all concept evidence onto candidates and leave candidates without a valid concept in `concept_state="unavailable"`.

- [x] **Step 7: Run the pure module tests and checkpoint**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_concept_resonance.py -q`

Expected: PASS.

Run: `python -m py_compile alphaagent/server/services/limit_up/concept_resonance.py`

Expected: no output.

### Task 3: Persist frozen memberships and point-in-time concept strength

**Files:**
- Modify: `alphaagent/server/db/schema.py:611-643`
- Create: `alphaagent/server/services/limit_up/concept_snapshot_repository.py`
- Test: `tests/alphaagent/test_limit_up_concept_live.py`

- [x] **Step 1: Write failing row-builder and prior-version tests**

```python
from datetime import date, datetime
from zoneinfo import ZoneInfo

from alphaagent.server.services.limit_up import concept_snapshot_repository

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_build_snapshot_rows_freezes_minute_and_membership_version():
    rows = concept_snapshot_repository.build_strength_snapshot_rows(
        [{
            "concept_id": "BK0877",
            "concept_name": "PCB",
            "strength_score": 92.0,
            "strength_rank": 1,
            "strength_percentile": 0.01,
            "concept_state": "launch",
            "coverage_ratio": 0.98,
            "radar_symbols": ["600183.SSE"],
        }],
        captured_at=datetime(2026, 7, 14, 13, 3, 27, tzinfo=SHANGHAI),
        membership_snapshot_date=date(2026, 7, 13),
        source="tencent.full_a_share_pages",
        source_updated_at=datetime(2026, 7, 14, 13, 3, 25, tzinfo=SHANGHAI),
    )

    assert rows[0]["trade_date"] == date(2026, 7, 14)
    assert rows[0]["membership_snapshot_date"] == date(2026, 7, 13)
    assert rows[0]["captured_minute"].second == 0
    assert rows[0]["metrics"]["radar_symbols"] == ["600183.SSE"]


def test_latest_prior_membership_date_never_uses_signal_day():
    assert concept_snapshot_repository.latest_prior_membership_date(
        [date(2026, 7, 13), date(2026, 7, 14)],
        date(2026, 7, 14),
    ) == date(2026, 7, 13)
```

- [x] **Step 2: Run the test and verify the repository is missing**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_concept_live.py -q`

Expected: collection FAIL with `ImportError`.

- [x] **Step 3: Add the concept strength table**

Define the table next to other limit-up snapshot tables:

```python
limit_up_concept_strength_snapshots = Table(
    "limit_up_concept_strength_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("captured_minute", DateTime(timezone=True), nullable=False),
    Column("membership_snapshot_date", Date, nullable=False),
    Column("concept_id", String(64), nullable=False),
    Column("concept_name", String(160), nullable=False),
    Column("concept_state", String(32), nullable=False),
    Column("strength_score", Float, nullable=False),
    Column("strength_rank", Integer, nullable=False),
    Column("strength_percentile", Float, nullable=False),
    Column("coverage_ratio", Float, nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("is_stale", Boolean, nullable=False, server_default="false"),
    Column("metrics", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
    UniqueConstraint(
        "trade_date", "concept_id", "captured_minute",
        name="uq_limit_up_concept_strength_minute",
    ),
)
Index(
    "ix_limit_up_concept_strength_date_time",
    limit_up_concept_strength_snapshots.c.trade_date,
    limit_up_concept_strength_snapshots.c.captured_at,
)
```

`metadata.create_all` handles new installations; no compatibility patch is needed for a new table.

- [x] **Step 4: Implement repository row builders and reads**

Create these public functions:

```python
def latest_prior_membership_date(values, trade_date):
    prior = [value for value in values if value < trade_date]
    return max(prior) if prior else None


def load_frozen_membership_rows(trade_date: date) -> tuple[date | None, list[dict[str, object]]]:
    # Query max(snapshot_date) strictly below trade_date, then load only concept/theme rows.


def build_strength_snapshot_rows(
    concepts,
    *,
    captured_at,
    membership_snapshot_date,
    source,
    source_updated_at,
):
    # Normalize UTC timestamps and move non-index fields into metrics JSONB.


def save_strength_snapshots(rows) -> int:
    # PostgreSQL upsert on trade_date + concept_id + captured_minute.


def load_strength_history(trade_date, *, before=None, minutes=6):
    # Return only rows at or before `before`, ordered by captured_at.


def prune_strength_snapshots(retain_trade_days=120) -> int:
    # Delete dates older than the newest 120 distinct trade dates.
```

Implement the bodies with SQLAlchemy Core and the existing `session_scope`/PostgreSQL insert patterns from `market_snapshot_repository.py`. The read query must use `< trade_date`, never `<=`.

- [x] **Step 5: Add a persistence-selection test**

```python
def test_select_persisted_concepts_keeps_top30_radar_and_warming():
    concepts = [
        {"concept_id": f"BK{i:04d}", "strength_rank": i, "concept_state": "observe", "radar_symbols": []}
        for i in range(1, 36)
    ]
    concepts[34]["radar_symbols"] = ["600000.SSE"]
    concepts[33]["concept_state"] = "warming"

    selected = concept_snapshot_repository.select_persisted_concepts(concepts)

    assert len(selected) == 32
    assert "BK0035" in {row["concept_id"] for row in selected}
    assert "BK0034" in {row["concept_id"] for row in selected}
```

Implement `select_persisted_concepts` as the union of strength Top30, radar-linked, and `warming/launch/ebb` concepts.

- [x] **Step 6: Run repository tests and schema checkpoint**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_concept_live.py -q`

Expected: PASS.

Run: `git diff --check -- alphaagent/server/db/schema.py alphaagent/server/services/limit_up/concept_snapshot_repository.py tests/alphaagent/test_limit_up_concept_live.py`

Expected: no output.

### Task 4: Build the atomic 30-second concept runtime service

**Files:**
- Create: `alphaagent/server/services/limit_up/concept_live_service.py`
- Modify: `tests/alphaagent/test_limit_up_concept_live.py`

- [x] **Step 1: Write failing refresh, stale, and failure-retention tests**

```python
def test_refresh_builds_atomic_runtime_snapshot(monkeypatch):
    monkeypatch.setattr(repository, "load_frozen_membership_rows", lambda _date: (
        date(2026, 7, 13),
        _pcb_memberships(),
    ))
    monkeypatch.setattr(repository, "save_strength_snapshots", lambda rows: len(rows))
    adapter = FakeAdapter(_full_market_payload("2026-07-14T13:03:20+08:00"))

    snapshot = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 25, tzinfo=SHANGHAI),
        adapter=adapter,
    )

    assert snapshot["data_quality"]["status"] == "ready"
    assert snapshot["membership_snapshot_date"] == "2026-07-13"
    assert snapshot["concepts_by_id"]["BK0877"]["concept_name"] == "PCB"
    assert len(snapshot["quotes"]) == len(_full_market_payload()["items"])


def test_runtime_snapshot_over_45_seconds_is_observation_only(monkeypatch):
    service._replace_runtime_snapshot(_runtime_snapshot("2026-07-14T13:03:00+08:00"))
    result = service.get_latest_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 46, tzinfo=SHANGHAI)
    )

    assert result["data_quality"]["is_stale"] is True
    assert result["data_quality"]["trigger_allowed"] is False


def test_failed_refresh_keeps_previous_snapshot_and_records_error(monkeypatch):
    previous = _runtime_snapshot("2026-07-14T13:03:00+08:00")
    service._replace_runtime_snapshot(previous)
    adapter = FakeAdapter(error=TimeoutError("full market timeout"))

    result = service.refresh_live_concept_snapshot(
        datetime(2026, 7, 14, 13, 3, 20, tzinfo=SHANGHAI),
        adapter=adapter,
    )

    assert result["captured_at"] == previous["captured_at"]
    assert "full market timeout" in result["data_quality"]["source_errors"][0]
```

Define `FakeAdapter`, `_pcb_memberships`, `_full_market_payload`, and `_runtime_snapshot` as deterministic test helpers in the same file.

- [x] **Step 2: Run focused tests and verify the service is missing**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_concept_live.py -q`

Expected: FAIL because `concept_live_service` is missing.

- [x] **Step 3: Implement the runtime service**

Use a process-local lock and atomic dictionary replacement:

```python
CONCEPT_REFRESH_SECONDS = 30
CONCEPT_MAX_AGE_SECONDS = 45
CONCEPT_MIN_QUOTE_COVERAGE = 0.90
_runtime_lock = Lock()
_runtime_snapshot: dict[str, object] | None = None
_history: deque[dict[str, object]] = deque(maxlen=16)


def refresh_live_concept_snapshot(captured_at=None, *, adapter=None, persist=True):
    local_at = _local_datetime(captured_at or datetime.now(SHANGHAI))
    live_adapter = adapter or AkShareAdapter()
    try:
        quote_payload = live_adapter.all_stock_quotes()
        snapshot_date, membership_rows = repository.load_frozen_membership_rows(local_at.date())
        if snapshot_date is None or not membership_rows:
            raise ConceptSnapshotUnavailable("缺少 D-1 概念成员版本")
        membership = build_membership_index(membership_rows, snapshot_date=snapshot_date)
        history = _history_by_concept(_history)
        concepts = aggregate_concept_strength(
            quote_payload.get("items") or [],
            membership,
            captured_at=local_at,
            history_by_concept=history,
        )
        snapshot = _runtime_payload(local_at, quote_payload, membership, concepts)
        if persist:
            rows = repository.build_strength_snapshot_rows(
                repository.select_persisted_concepts(concepts),
                captured_at=local_at,
                membership_snapshot_date=snapshot_date,
                source=str(quote_payload.get("source") or "unknown"),
                source_updated_at=quote_payload.get("updated_at"),
            )
            repository.save_strength_snapshots(rows)
        _replace_runtime_snapshot(snapshot)
        return snapshot
    except Exception as exc:
        return _snapshot_after_refresh_error(local_at, exc)
```

Implement `get_latest_live_concept_snapshot`, `_replace_runtime_snapshot`, `clear_runtime_snapshot`, `_runtime_payload`, `_history_by_concept`, and timestamp helpers. `trigger_allowed` is true only for same-day data, coverage at least 90%, and age at most 45 seconds.

- [x] **Step 4: Add a full-market radar test**

```python
def test_runtime_snapshot_builds_authoritative_main_board_five_percent_radar():
    snapshot = _ready_refresh_with_quotes([
        _quote("600001.SSE", 5.0),
        _quote("000001.SZSE", 7.0),
        _quote("300001.SZSE", 19.0),
        _quote("600002.SSE", 4.99),
    ])

    assert {row["vt_symbol"] for row in snapshot["radar_quotes"]} == {
        "600001.SSE",
        "000001.SZSE",
    }
```

Build `radar_quotes` from the complete payload with `is_eligible_main_board` and `change_pct >= 5`; this is the authoritative radar for each 30-second snapshot.

- [x] **Step 5: Run service tests and compile**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_concept_live.py -q`

Expected: PASS.

Run: `python -m py_compile alphaagent/server/services/limit_up/concept_live_service.py alphaagent/server/services/limit_up/concept_snapshot_repository.py`

Expected: no output.

### Task 5: Schedule concept refresh independently and freeze memberships daily

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:432-470,485-565,2302-2398,4592-4630,4720-4806`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Write failing schedule-definition and throttle tests**

```python
def test_limit_up_concept_scan_is_independent_and_throttled_to_30_seconds():
    schedule = next(
        item for item in svc.DEFAULT_BATCH_SCHEDULES
        if item["id"] == "limit_up_concept_scan"
    )
    assert schedule["action"] == "limit_up_concept_scan"
    assert schedule["cron"] == "* 9-14 * * 1-5"
    assert schedule["job_ids"] == []
    assert svc.CONCEPT_REFRESH_SECONDS == 30


def test_stock_sector_reverse_index_is_frozen_daily():
    cadence = svc.JOB_CADENCES["sync_stock_sector_memberships"]
    assert cadence.cadence == svc.CADENCE_EOD_DAILY
```

- [x] **Step 2: Run focused tests and verify failure**

Run: `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "concept_scan or reverse_index_is_frozen_daily"`

Expected: FAIL because the schedule/action does not exist and membership cadence is not daily.

- [x] **Step 3: Add the action and default schedule**

Import `refresh_live_concept_snapshot` and `CONCEPT_REFRESH_SECONDS`. Add:

```python
{
    "id": "limit_up_concept_scan",
    "name": "实时概念共振（每30秒）",
    "cron": "* 9-14 * * 1-5",
    "action": "limit_up_concept_scan",
    "enabled": True,
    "concurrency": 1,
    "job_ids": [],
}
```

Allow `limit_up_concept_scan` in `_schedule_action`. Treat it like `limit_up_live_scan` in `run_schedule_now`, `_run_scheduled_jobs`, `_run_schedule_action`, and the active-session window. Use a 29-second recent-started throttle and do not queue missed invocations.

- [x] **Step 4: Add direct-action and lunch tests**

```python
def test_scheduler_refreshes_concepts_without_blocking_live_scan(monkeypatch):
    calls = []
    monkeypatch.setattr(svc, "refresh_live_concept_snapshot", lambda: calls.append("concept") or {"data_quality": {"status": "ready"}, "concept_count": 498})
    monkeypatch.setattr(svc, "_touch_schedule", lambda *args, **kwargs: None)

    result = svc._run_schedule_action({"id": "limit_up_concept_scan", "action": "limit_up_concept_scan"})

    assert calls == ["concept"]
    assert result["concept_count"] == 498


def test_scheduler_does_not_refresh_concepts_during_lunch(monkeypatch):
    assert svc._limit_up_live_scan_window_open(
        datetime(2026, 7, 14, 12, 0, tzinfo=SHANGHAI)
    ) is False
```

- [x] **Step 5: Make the reverse-index job daily without making member crawling daily**

Change only `sync_stock_sector_memberships` to `CADENCE_EOD_DAILY`. Keep `sync_sector_list` and `sync_sector_members` on their existing slower freshness rules. The cheap reverse-index job must always rebuild from the last successful local member tables and save the current date's immutable snapshot.

- [x] **Step 6: Run scheduler tests and checkpoint**

Run: `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "limit_up_live_scan or limit_up_concept_scan or stock_sector"`

Expected: PASS.

Run: `git diff --check -- alphaagent/server/services/data_sync.py tests/alphaagent/test_data_sync_schedule.py`

Expected: no output.

### Task 6: Evaluate every radar candidate with realtime concept evidence

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_repository.py:31-52,250-450,635-655`
- Modify: `alphaagent/server/services/limit_up/live_service.py:72-183,186-234,440-779,878-1090`
- Modify: `alphaagent/server/services/limit_up/live_policy.py:12-65,86-203,386-522,691-939,1075-1219`
- Modify: `alphaagent/server/services/limit_up/lane_research.py:331-400,420-502`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_lanes.py`

- [x] **Step 1: Write a failing full-radar-before-Top5 test**

```python
def test_all_radar_candidates_receive_lane_and_concept_decisions_before_top5(monkeypatch):
    concept_snapshot = _pcb_concept_snapshot(
        symbols=[f"60000{i}.SSE" for i in range(8)],
        captured_at="2026-07-14T13:03:30+08:00",
    )
    snapshot = build_live_snapshot(
        _quote_payload([_near_limit_quote(f"60000{i}.SSE", 9.0 + i / 100) for i in range(8)]),
        _empty_pool_payload("20260714"),
        datetime(2026, 7, 14, 13, 3, 30, tzinfo=SHANGHAI),
        _stock_context_for([f"60000{i}.SSE" for i in range(8)]),
        concept_snapshot=concept_snapshot,
    )

    assert len(snapshot["candidates"]) == 8
    assert all(candidate.get("lane_decision") for candidate in snapshot["candidates"])
    assert all(candidate.get("concept_id") == "BK0877" for candidate in snapshot["candidates"])
    assert len(snapshot["recommendations"]["lanes"]["now"]) == 8
```

- [x] **Step 2: Write failing checks for concept launch, stale data, and informational stock flow**

```python
def test_sweep_requires_fresh_concept_launch_and_top3_leader():
    candidate = _eligible_first_board_candidate(
        distance_to_limit_pct=0.4,
        concept_state="launch",
        concept_leader_rank=2,
        concept_snapshot_age_seconds=12,
        concept_coverage_ratio=0.97,
        concept_strong_5_count=6,
        stock_main_net_inflow=None,
    )

    checks = live_policy._candidate_execution_checks(candidate, require_expansion=True, entry_kind="sweep")

    assert _check(checks, "concept_state")["status"] == "passed"
    assert _check(checks, "concept_leader")["status"] == "passed"
    assert _check(checks, "stock_flow")["status"] == "informational"
    assert live_policy._candidate_execution_reasons(candidate, require_expansion=True, entry_kind="sweep") == []


def test_stale_concept_snapshot_blocks_new_trigger():
    candidate = _eligible_first_board_candidate(
        concept_state="launch",
        concept_snapshot_age_seconds=46,
    )
    reasons = live_policy._candidate_execution_reasons(candidate, require_expansion=True, entry_kind="sweep")
    assert "概念行情已超过45秒" in reasons
```

- [x] **Step 3: Run focused tests and confirm current Top5/static-gate failures**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_lanes.py -q -k "full_radar or concept_launch or stale_concept"`

Expected: FAIL because `concept_snapshot` and concept checks do not exist.

- [x] **Step 4: Stop style labels from becoming execution sectors**

In `live_repository.py`, use industry only as the fallback primary context. Preserve all concept/theme membership rows for the frozen concept index, but do not let `_best_membership` select style themes. Expand `STYLE_SECTOR_KEYWORDS` to match the design and add a regression test asserting PCB is retained while MSCI and report labels are excluded.

- [x] **Step 5: Merge the authoritative full-market radar with 15-second increments**

Extend `build_live_snapshot` with an optional keyword-only concept snapshot:

```python
def build_live_snapshot(
    quote_payload,
    pool_payload,
    captured_at,
    stock_context,
    previous_snapshot=None,
    lane_validations=None,
    *,
    concept_snapshot=None,
):
```

In `refresh_live_snapshot`, call `get_latest_live_concept_snapshot(local_at)`; this read must not perform network I/O. Build the radar from `concept_snapshot["radar_quotes"]`, then overlay fresher top-200 and pool rows by `vt_symbol`. If the concept snapshot is absent or stale, keep candidates visible but set concept trigger checks to pending/failed.

- [x] **Step 6: Attach concept evidence and evaluate all candidates before ranking**

Use this order in `build_live_snapshot`:

```python
candidates = _enrich_candidates(full_radar_rows, pool_payload, stock_context, require_sector=False)
attach_candidate_concepts(candidates, concept_snapshot or {})
_attach_lane_decisions(candidates, market_context, local_at, market_gate=market_gate)
_attach_stability(candidates, previous_snapshot, local_at)
ranked_all = rank_live_opportunities(candidates, limit=len(candidates))
recommendations = build_live_recommendations(
    ranked_all,
    market_context,
    local_at,
    previous_snapshot=previous_snapshot,
    market_gate=market_gate,
)
```

Set `market_dragon_rank` only after every candidate has a signal. Keep the two-position portfolio selection later in `_build_live_portfolio`; set a separate bounded watchlist limit of 6.

- [x] **Step 7: Replace static live sector checks with explicit concept checks**

Add checks named `concept_freshness`, `concept_state`, `concept_diffusion`, and `concept_leader`. Use these internal research thresholds:

```python
CONCEPT_MAX_AGE_SECONDS = 45
CONCEPT_MIN_COVERAGE_RATIO = 0.90
CONCEPT_MIN_STRONG_5_COUNT = 2
CONCEPT_MAX_LEADER_RANK = 3
```

Remove static `sector_heat >= 60`, `sector_touch_count >= 3`, and mandatory positive sector/stock flow from the sweep decision. Preserve stock flow as `informational` when missing and `failed` only when a present, current value is materially negative under the existing risk rule. Change execution-reason collection to block only `pending` and `failed`, not `informational`.

- [x] **Step 8: Separate evaluation time from actual first-touch time**

Add `evaluation_time` to live research candidates. For an unsealed near-limit candidate, first-board timing uses evaluation time. For `sealed/resealed/failed` candidates with `first_limit_time`, timing uses the actual first touch. Add this regression test:

```python
def test_known_pre_ten_first_touch_is_not_relabelled_by_a_post_ten_scan():
    candidate = _eligible_first_board_candidate(
        state="sealed",
        first_limit_time="09:53:06",
        evaluation_time="10:05:00",
    )
    result = evaluate_lane_candidate(candidate)
    assert "first_touch_too_early" in result["blockers"]
```

- [x] **Step 9: Add the concept warming state**

When concept state is `warming/launch` but the stock is outside the 1% trigger zone, emit `action="observe"` and `signal_state="concept_warming"`. Inside the trigger zone, use `approaching_trigger` until all checks pass. `trigger_ready` remains possible only during scheduled entry windows and with fresh data.

- [x] **Step 10: Run live and lane tests**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_lanes.py -q`

Expected: PASS.

Run: `git diff --check -- alphaagent/server/services/limit_up/live_repository.py alphaagent/server/services/limit_up/live_service.py alphaagent/server/services/limit_up/live_policy.py alphaagent/server/services/limit_up/lane_research.py`

Expected: no output.

### Task 7: Preserve concept states and correct Top5 trace semantics

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_trace_repository.py:15-73,88-119`
- Modify: `alphaagent/server/services/limit_up/live_trace_service.py:12-45,211-340`
- Test: `tests/alphaagent/test_limit_up_live_trace.py`
- Test: `tests/alphaagent/test_api.py`

- [x] **Step 1: Write failing trace tests**

```python
def test_trace_records_concept_warming_before_top5_entry():
    rows = [
        _trace_row("13:02:30", signal_state="concept_warming", market_rank=12, concept_name="PCB"),
        _trace_row("13:04:00", signal_state="approaching_trigger", market_rank=7, concept_name="PCB"),
        _trace_row("13:04:20", signal_state="trigger_ready", market_rank=3, concept_name="PCB"),
    ]

    events = build_symbol_trace(rows, "002463.SZSE")

    assert [event["event"] for event in events] == [
        "radar_entered",
        "concept_warming",
        "approaching_trigger",
        "recommended",
        "trigger_ready",
    ]


def test_in_top5_uses_market_rank_not_signal_presence():
    state = _row_symbol_states(
        _trace_row("13:03:00", signal_state="concept_warming", market_rank=12),
        {},
    )["002463.SZSE"]
    assert state["in_top5"] is False
```

- [x] **Step 2: Run trace tests and verify failure**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_live_trace.py -q`

Expected: FAIL because `concept_warming` is not projected or recognized and `in_top5` currently means “has any signal”.

- [x] **Step 3: Persist concept evidence for candidates and signals**

Add these fields to both appropriate trace projection tuples:

```python
"concept_id",
"concept_name",
"concept_state",
"concept_strength_score",
"concept_strength_rank",
"concept_strength_percentile",
"concept_leader_rank",
"concept_coverage_ratio",
"concept_strong_5_count",
"concept_near_limit_count",
"concept_sealed_count",
"concept_failed_count",
"concept_change_acceleration_3m",
"concept_turnover_acceleration_3m",
"concept_snapshot_age_seconds",
```

Because all radar candidates now have lane decisions, the diagnostic table must retain blockers for candidates outside Top5.

- [x] **Step 4: Add concept transitions and Top5 rank logic**

Add `concept_warming` to event and state priorities. Emit it only when entering that state. Set:

```python
market_rank = _integer_or_none(signal.get("market_dragon_rank") or candidate.get("market_dragon_rank"))
in_top5 = market_rank is not None and market_rank <= 5
```

Do not use `bool(signal)` as Top5 membership after all candidates receive signals. Add `warming_count` to the per-lane funnel while preserving existing fields.

- [x] **Step 5: Extend API regression assertions**

In `tests/alphaagent/test_api.py`, assert `/api/limit-up/live-traces/day` and `/symbol` preserve the concept name, state, leader rank, strength rank, and `concept_warming` event without adding a separate public concept page.

- [x] **Step 6: Run trace and API tests**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_live_trace.py tests/alphaagent/test_api.py -q -k "limit_up"`

Expected: PASS.

### Task 8: Show concept preheat and persistent observations in one UI list

**Files:**
- Modify: `frontend/src/api/limitUp.ts:54-172,180-259`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/features/limitUp/nextSessionPlan.ts`
- Modify: `frontend/src/features/limitUp/nextSessionPlan.spec.ts`
- Modify: `frontend/src/features/limitUp/liveTrace.ts`
- Modify: `frontend/src/features/limitUp/liveTrace.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx:300-510,523-705`

- [x] **Step 1: Write failing presentation and bounded-list tests**

```typescript
it("shows concept warming as a pre-limit observation", () => {
  expect(signalStatePresentation({
    signal_state: "concept_warming",
    action: "observe",
    execution_permission: "research_only",
  })).toEqual({ label: "PCB板块预热", tone: "warning" });
});

it("keeps two portfolio rows plus six observations without duplicates", () => {
  const snapshot = snapshotWithPortfolioAndWatchlist(2, 8);
  const rows = liveSignalsForScope(snapshot, "portfolio");
  expect(rows).toHaveLength(8);
  expect(new Set(rows.map((row) => row.vt_symbol)).size).toBe(8);
  expect(rows.slice(0, 2).every((row) => row.portfolio_selected)).toBe(true);
});
```

Pass `concept_name` into the presentation helper or use the generic label “板块预热” when absent.

- [x] **Step 2: Run frontend unit tests and verify failure**

Run: `cd frontend && npm test -- --run src/features/limitUp/livePortfolio.spec.ts src/features/limitUp/nextSessionPlan.spec.ts src/features/limitUp/liveTrace.spec.ts`

Expected: FAIL because the new state and fields do not exist and the list is sliced to two.

- [x] **Step 3: Extend API types**

Add `concept_warming` to live and trace state unions. Add the concept evidence fields from Task 7 to `LimitUpLiveSignal`, `LimitUpLiveTraceItem`, and `LimitUpLiveTraceEvent`. Add `warming_count` to `LimitUpLiveTraceFunnel`.

- [x] **Step 4: Keep one ordered list with two actionable rows and six observations**

Update `liveSignalsForScope` to merge portfolio and watchlist, deduplicate by symbol, and return at most 8 rows. Sort by:

1. `trigger_ready`/`buy_now`.
2. selected portfolio observations.
3. `approaching_trigger`.
4. `concept_warming`.
5. rejected/missed/invalidated.

Within the same state, use concept strength rank, concept leader rank, distance to limit, and symbol. Do not add a new strategy control.

- [x] **Step 5: Render compact concept evidence in the existing row**

In `LiveSignalRow`, replace the old sector-only meta with the realtime concept when present:

```tsx
const conceptEvidence = signal.concept_name
  ? `${signal.concept_name} · 强度${signal.concept_strength_rank ?? "-"} · ${signal.concept_strong_5_count ?? 0}只涨超5% · 概念龙${signal.concept_leader_rank ?? "-"}`
  : "概念共振待确认";
```

Render this as one compact line. Show snapshot age or coverage only when degraded. Keep buy/sell/cancel discipline and existing TBOX metrics; do not add nested cards or a separate concept dashboard.

- [x] **Step 6: Add trace labels and funnel text**

Map `concept_warming` to “板块预热” and insert `预热 N` between radar and approaching in the funnel. Preserve “已跌出当前 Top5” as a trajectory event rather than deleting the row.

- [x] **Step 7: Run frontend tests and production build**

Run: `cd frontend && npm test -- --run src/features/limitUp/livePortfolio.spec.ts src/features/limitUp/nextSessionPlan.spec.ts src/features/limitUp/liveTrace.spec.ts`

Expected: PASS.

Run: `cd frontend && npm run build`

Expected: production build succeeds without TypeScript errors.

### Task 9: Replay, end-to-end verification, and durable project memory

**Files:**
- Modify: `tests/alphaagent/test_limit_up_concept_resonance.py`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Create: `memory/06_backtests/limit_up_realtime_concept_replay_20260714.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_limit_up_realtime_concept_resonance_design.md`

- [x] **Step 1: Add the no-lookahead PCB replay contract test**

```python
def test_20260714_pcb_replay_uses_prior_membership_and_preseal_frames_only():
    membership = build_membership_index(
        _pcb_memberships(snapshot_date="2026-07-13"),
        snapshot_date="2026-07-13",
    )
    frames = _pcb_preseal_frames_20260714()

    report = replay_radar_concepts(frames, membership, signal_at="2026-07-14T13:04:21+08:00")

    assert report["membership_snapshot_date"] == "2026-07-13"
    assert report["future_frame_count"] == 0
    assert report["concepts"]["BK0877"]["radar_5_count"] == 9
    assert report["concepts"]["BK0877"]["within_1pct_count"] == 7
```

Implement `replay_radar_concepts` as a pure helper in `concept_resonance.py`; it must discard frames later than `signal_at` and must not infer unavailable full-market values.

- [x] **Step 2: Run the complete backend feature suite**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_akshare_adapter.py \
  tests/alphaagent/test_limit_up_concept_resonance.py \
  tests/alphaagent/test_limit_up_concept_live.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_live_trace.py \
  tests/alphaagent/test_limit_up_lanes.py \
  tests/alphaagent/test_data_sync_schedule.py \
  tests/alphaagent/test_api.py -q
```

Expected: PASS with no skipped feature tests caused by implementation errors.

- [x] **Step 3: Run the complete frontend suite**

Run: `cd frontend && npm test -- --run`

Expected: PASS.

Run: `cd frontend && npm run build`

Expected: PASS.

- [x] **Step 4: Rebuild and start the product**

Run: `docker compose up -d --build`

Expected: `alphaagent-api`, `alphaagent-web`, `alphaagent-gateway`, PostgreSQL, and Redis become healthy/running.

Run: `docker compose ps`

Expected: API and gateway report healthy; web is running.

- [x] **Step 5: Verify runtime schedules and concept persistence**

Run database checks after one valid market refresh:

```sql
SELECT id, enabled, action, last_status, last_started_at, last_finished_at
FROM sync_batch_schedules
WHERE id IN ('limit_up_concept_scan', 'limit_up_live_scan')
ORDER BY id;

SELECT trade_date, count(*) AS rows, count(DISTINCT captured_minute) AS minutes
FROM limit_up_concept_strength_snapshots
GROUP BY trade_date
ORDER BY trade_date DESC
LIMIT 2;
```

Expected: both schedules exist; concept rows use the current trade date and multiple distinct minutes. Outside market hours, manually invoking the schedule may return skipped/stale and must not fabricate a live row.

- [x] **Step 6: Record the honest 2026-07-14 replay evidence**

Create `memory/06_backtests/limit_up_realtime_concept_replay_20260714.md` with:

- The prior membership date used.
- The eight PCB stocks and their last preseal timestamps.
- Radar/within-1%/sealed/failed counts available at each frame.
- Which candidates became visible under the new state machine.
- A statement that no full-market concept snapshot existed at 13:03, so the report validates visibility and grouping only, not exact historical concept strength or D+1 return.

- [x] **Step 7: Perform browser verification on desktop and mobile**

Open `http://localhost:8080/limit-up` with Playwright after authentication. Verify at desktop `1440x900` and mobile `390x844`:

- One realtime list, no additional strategy selector.
- Portfolio rows before concept-warming observations.
- Concept name, strength rank, 5% diffusion, and leader rank fit without overlap.
- A candidate remains in the day trace after dropping from Top5.
- Stale concept data shows observation-only language and no positive buy styling.
- No console errors or failed API requests.

Capture screenshots for inspection, then remove transient screenshots instead of adding them to Git.

- [x] **Step 8: Update current-state memory and design status**

Update the four memory files listed above in place. Replace stale statements rather than appending a transcript. Mark the design status as implemented only after all verification passes; keep the strict forward 20/60-day performance validation as an open risk.

- [x] **Step 9: Final diff audit without committing**

Run: `git diff --check`

Expected: no output.

Run: `git status --short`

Expected: only the intended feature files plus pre-existing unrelated user changes. Do not stage or commit without explicit authorization.
