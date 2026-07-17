# Limit-up 3% Early Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy forbids `git commit` unless the user explicitly authorizes it, so every task ends with a diff checkpoint instead of an automatic commit.

**Goal:** Move first-board observation from 5% to 3%, preserve one formal recommendation pipeline, collect causal full-candidate evidence, and activate sub-5% buys only if the same-frame D+1 close validation passes fixed reliability gates.

**Architecture:** Keep the current v15 public recommendation behavior unchanged while the system starts evaluating all eligible main-board stocks at 3%. Persist a compact normalized point-in-time ledger instead of extending the existing two-day JSON trace tables, then backfill minute paths only for stocks actually observed above 3%. Compare exactly two frozen contracts on the same frames: current 5% entry versus 3% entry using the same market, sector, momentum, history, risk, ranking, cost, and D+1 close rules. After the fixed review gate, publish only the winning contract as the next live version; no parallel public recommendations and no separate execution algorithm remain.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy Core, PostgreSQL 16, pytest, React/TypeScript, Vitest.

## Current Implementation Status

- Tasks 1-6 are implemented and active in the local Compose stack.
- Task 7 gate code and boundary tests are implemented, but production selection remains
  `formal_5pct` while real evidence is collected.
- The 2026-07-17 implementation checkpoint passed 584 limit-up backend tests, 78 frontend
  tests, the production frontend build, Python compilation, and `git diff --check`. The
  in-container radar minute dry-run returned the expected
  `limit_up_radar_3pct_full_session` scope without writes.
- The live, concept, 19:00, and 21:30 schedules are enabled. Deployment happened after the
  session, so the persisted radar ledger is correctly still at 0 frames and 0 observations;
  the first complete evidence day must come from a subsequent full trading session.
- Scan-gap P90 includes each entry window's uncovered start and end edges as well as gaps
  between saved frames. A late-starting, early-stopping, or sparse scanner therefore cannot
  pass the 20-second cadence gate merely because its few persisted frames are close together.
  Each day must pass this cadence gate before it can enter the first-60-day cohort, so healthy
  days cannot dilute a stopped scanner on another date.
- Minute completeness requires the 240 distinct official slots from 09:31 through 11:30 and
  13:01 through 15:00. A raw row count containing pre-open, lunch, duplicate-second, or
  shifted timestamps cannot satisfy the coverage gate.
- A stock that emitted a buy decision remains quote-tracked for the 60-second fill horizon
  even if it falls below 3%. These `fill_followup` rows cannot rank, recommend, or create a
  new signal; they only prevent fast losers from disappearing as `entry_quote_missing`.
- Acceptance metrics use only the chronologically first 60 complete trade days. Once that
  cohort exists, later complete days cannot change its signals, outcomes, or metrics.
- The 60-day review remains `ready_for_review` while either contract still has a pending D+1
  close. It becomes `accepted` or `rejected` only after those settlements finish.
- The current runtime state is `collecting`; no 3% production promotion has occurred.

---

## Fixed Product Decisions

1. `3%` is the capture/evaluation boundary. It is not automatically a buy signal.
2. During evidence collection, the only public formal list remains v15. Rows from 3% to below 5% are internal point-in-time observations and never appear in `actionable_recommendations`.
3. The research comparison changes one variable only: whether a first-board candidate may use the existing momentum entry below 5%. No new score, factor, or sector rule is added.
4. The primary evaluation covers every formal candidate independently of the two-position account. The two-position arrival-order account remains a secondary execution view.
5. Entry is priced at the first valid saved quote in the same configured buy window, at least 20 seconds after the decision and no later than 60 seconds after it. A signaled stock remains quote-tracked through that horizon even after falling below 3%, without re-entering recommendation logic. A quote outside that window is not fillable. A signal already at the limit price is marked `queue_unknown_without_l2`; it is not presented as guaranteed filled.
6. Exit remains the next official trading day's daily close with the existing costs and slippage. Missing or non-positive prices are excluded, never filled from another price.
7. Process review starts after 20 complete trading days. Strategy activation uses the first 60 complete trading days, waits for both contracts' D+1 settlements, and requires every gate in Task 7.
8. The existing `limit_up_live_trace_snapshots` and `limit_up_signal_snapshots` retention and contents are not expanded. They currently consume about 693 MB and 860 MB respectively; using them for a 90-day 3% universe is not acceptable.

## File Map

**Create**

- `alphaagent/server/services/limit_up/radar_contract.py`: thresholds and pure capture/formal-state classification.
- `alphaagent/server/services/limit_up/radar_observation_repository.py`: compact frame/observation persistence, reads, coverage, and retention.
- `alphaagent/server/services/limit_up/radar_validation.py`: causal decision selection, delayed entry matching, D+1 close settlement, and acceptance gates.
- `tests/alphaagent/test_limit_up_radar_contract.py`: threshold and one-pipeline behavior.
- `tests/alphaagent/test_limit_up_radar_observation_repository.py`: normalized persistence and retention.
- `tests/alphaagent/test_limit_up_radar_validation.py`: future-function invariants, delayed entry, metrics, and activation gates.

**Modify**

- `alphaagent/server/db/schema.py`: add compact radar frame and observation tables.
- `alphaagent/server/services/limit_up/live_service.py`: build 3% capture candidates, retain 5% formal candidates, record stage timings, and persist internal observations.
- `alphaagent/server/services/limit_up/live_repository.py`: cache only D-1/static symbol context for the trading day while refreshing intraday flow and timing fields every scan.
- `alphaagent/server/services/limit_up/concept_live_service.py`: use the shared 3% capture threshold for `radar_quotes`.
- `alphaagent/server/services/limit_up/live_policy.py`: expose the existing point-in-time first-board momentum decision as a pure helper; do not add a new scoring rule.
- `alphaagent/server/services/limit_up/data_quality_repository.py`: find missing minute paths for observed 3% symbol/date pairs.
- `alphaagent/server/services/limit_up/data_quality.py`: backfill the new radar scope through the existing TDX minute importer.
- `alphaagent/server/services/data_sync.py`: register 19:00 primary and 21:30 retry jobs.
- `alphaagent/server/api/limit_up.py`: add a read-only validation endpoint.
- `alphaagent/server/services/limit_up/strategy_guide.py`: expose the frozen contract and the current evidence fingerprint.
- `alphaagent/server/services/limit_up/versions.py`: bump the live version only after Task 7 passes.
- `frontend/src/api/limitUp.ts`: type and fetch validation evidence.
- `frontend/src/features/limitUp/StrategyGuideDialog.tsx`: show coverage and the one selected contract in the existing dataset tab.
- Existing tests: `tests/alphaagent/test_limit_up_live.py`, `tests/alphaagent/test_limit_up_concept_live.py`, `tests/alphaagent/test_data_sync_schedule.py`, `tests/alphaagent/test_limit_up_strategy_guide.py`, `frontend/src/features/limitUp/StrategyGuideDialog.spec.tsx`.

### Task 1: Freeze The 3% Capture Contract Without Changing Formal Recommendations

**Files:**

- Create: `alphaagent/server/services/limit_up/radar_contract.py`
- Create: `tests/alphaagent/test_limit_up_radar_contract.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py:66-70, 97-195, 604-651`
- Modify: `alphaagent/server/services/limit_up/concept_live_service.py:18-25, 175-190`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_concept_live.py`
- Create: `tests/alphaagent/test_limit_up_live_repository.py`

- [x] **Step 1: Write failing pure-contract tests**

```python
from alphaagent.server.services.limit_up.radar_contract import (
    CAPTURE_MIN_CHANGE_PCT,
    FORMAL_MIN_CHANGE_PCT,
    capture_state,
    is_formal_candidate,
)


def test_three_percent_starts_capture_but_not_formal_execution() -> None:
    assert CAPTURE_MIN_CHANGE_PCT == 3.0
    assert FORMAL_MIN_CHANGE_PCT == 5.0
    assert capture_state(change_pct=3.2, pool_state="quote") == "pre_radar"
    assert is_formal_candidate(change_pct=3.2, state="pre_radar") is False


def test_five_percent_enters_existing_formal_state() -> None:
    assert capture_state(change_pct=5.0, pool_state="quote") == "near_limit"
    assert is_formal_candidate(change_pct=5.0, state="near_limit") is True


def test_limit_pool_state_is_always_formal() -> None:
    assert capture_state(change_pct=1.0, pool_state="sealed") == "sealed"
    assert is_formal_candidate(change_pct=1.0, state="sealed") is True
```

- [x] **Step 2: Run the pure-contract tests and verify they fail because the module does not exist**

Run:

```bash
uv run pytest tests/alphaagent/test_limit_up_radar_contract.py -q
```

Expected: collection error for `alphaagent.server.services.limit_up.radar_contract`.

- [x] **Step 3: Implement the small pure contract**

```python
"""Point-in-time capture and formal-entry boundaries for first-board radar."""

from __future__ import annotations

CAPTURE_MIN_CHANGE_PCT = 3.0
FORMAL_MIN_CHANGE_PCT = 5.0
RADAR_CONTRACT_VERSION = "limit-up-radar-contract-v1"
POOL_STATES = frozenset({"sealed", "resealed", "failed"})


def capture_state(*, change_pct: float, pool_state: str) -> str:
    if pool_state in POOL_STATES:
        return pool_state
    return "near_limit" if change_pct >= FORMAL_MIN_CHANGE_PCT else "pre_radar"


def is_formal_candidate(*, change_pct: float, state: str) -> bool:
    return state in POOL_STATES or change_pct >= FORMAL_MIN_CHANGE_PCT
```

- [x] **Step 4: Make live collection use 3% while preserving the public 5% candidate list**

In `build_live_snapshot`, build and enrich one capture universe, then filter only the existing formal path before ranking and recommendations:

```python
capture_rows = _merge_source_rows(
    radar_quote_payload,
    pool_payload,
    include_previous=session_stage(local_at) in {"auction_watch", "auction"},
    min_change_pct=CAPTURE_MIN_CHANGE_PCT,
)
capture_candidates = _enrich_candidates(
    capture_rows,
    pool_payload,
    stock_context,
    require_sector=False,
)
formal_candidates = [
    row
    for row in capture_candidates
    if is_formal_candidate(
        change_pct=float(row.get("change_pct") or -100.0),
        state=str(row.get("state") or ""),
    )
]
```

Change `_merge_source_rows` so quote rows receive `capture_state(change_pct=change_pct, pool_state="quote")` rather than unconditionally receiving `near_limit`. Keep `zbgc` and `zt` pool states authoritative. Store `capture_candidates` under the internal key `trace_capture_candidates`; keep `candidates`, `trace_radar_candidates`, and all public recommendations based only on `formal_candidates`.

- [x] **Step 5: Make the full-market concept snapshot use the shared capture threshold**

Replace the local `>= 5.0` filter with:

```python
and _float(quote.get("change_pct"), default=-100.0) >= CAPTURE_MIN_CHANGE_PCT
```

This changes only `radar_quotes`; concept aggregation already uses all full-market quotes.

- [x] **Step 6: Add integration tests proving there is still one public recommendation list**

Add cases to `tests/alphaagent/test_limit_up_live.py` that construct otherwise identical 4.9% and 5.0% candidates. Assert:

```python
assert {row["vt_symbol"] for row in snapshot["trace_capture_candidates"]} == {
    "600001.SSE",
    "600002.SSE",
}
assert [row["vt_symbol"] for row in snapshot["candidates"]] == ["600002.SSE"]
assert all(
    signal["vt_symbol"] != "600001.SSE"
    for signal in snapshot["recommendations"]["lanes"]["now"]
)
```

- [x] **Step 7: Split and cache only the context that is immutable during the session**

Refactor `load_live_context` into `_load_prior_symbol_context` and `_load_intraday_context`. The prior loader owns D-1 bars, membership, prior events, financial reports, gene fields, and concept groups; cache its per-symbol results until the trade date changes. The intraday loader owns current stock/sector fund flow rows and `market_timing_panel`; call it every scan and merge it over the cached prior rows.

Use a lock-protected cache with this contract:

```python
_prior_context_lock = Lock()
_prior_context_trade_date: date | None = None
_prior_context_by_symbol: dict[str, dict[str, object]] = {}


def clear_live_context_cache() -> None:
    global _prior_context_trade_date
    with _prior_context_lock:
        _prior_context_trade_date = None
        _prior_context_by_symbol.clear()
```

Add a test that requests symbols A/B, then B/C on the same date. Assert the prior loader receives A/B once and only C on the second call, while the intraday loader receives both complete symbol sets. Advance the trade date and assert the prior cache rebuilds. This avoids freezing live fund-flow fields while removing the history/context cold start when a tracked 3% stock accelerates.

- [x] **Step 8: Run the focused tests**

```bash
uv run pytest \
  tests/alphaagent/test_limit_up_radar_contract.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_live_repository.py \
  tests/alphaagent/test_limit_up_concept_live.py -q
```

Expected: all selected tests pass; existing 5% formal recommendation assertions remain unchanged.

- [x] **Step 9: Diff checkpoint**

```bash
git diff --check -- \
  alphaagent/server/services/limit_up/radar_contract.py \
  alphaagent/server/services/limit_up/live_service.py \
  alphaagent/server/services/limit_up/live_repository.py \
  alphaagent/server/services/limit_up/concept_live_service.py \
  tests/alphaagent/test_limit_up_radar_contract.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_live_repository.py \
  tests/alphaagent/test_limit_up_concept_live.py
```

Expected: no whitespace errors. Do not commit unless the user explicitly asks.

### Task 2: Add A Compact 90-Day Point-In-Time Ledger

**Files:**

- Modify: `alphaagent/server/db/schema.py:1006`
- Create: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Create: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [x] **Step 1: Write failing schema and projection tests**

```python
from datetime import date

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import radar_observation_repository as repo


def test_compact_radar_tables_are_registered() -> None:
    assert "limit_up_radar_frames" in schema.metadata.tables
    assert "limit_up_radar_observations" in schema.metadata.tables


def test_radar_retention_keeps_ninety_trade_days() -> None:
    dates = [date(2026, 1, 1).fromordinal(date(2026, 1, 1).toordinal() + i) for i in range(100)]
    assert repo.retention_cutoff(dates, retain_trade_days=90) == sorted(dates)[-90]


def test_projection_drops_large_nested_payloads() -> None:
    row = repo.project_observation(
        {
            "vt_symbol": "600001.SSE",
            "name": "测试股份",
            "change_pct": 3.6,
            "last_price": 10.36,
            "previous_close": 10.0,
            "state": "pre_radar",
            "lane_support_score": 61.0,
            "financial_snapshot": {"large": "payload"},
            "raw": {"large": "payload"},
        },
        formal_signal=None,
        early_signal={"action": "buy_now", "entry_kind": "momentum"},
    )
    assert row["vt_symbol"] == "600001.SSE"
    assert row["early_action"] == "buy_now"
    assert "financial_snapshot" not in row
    assert "raw" not in row
```

- [x] **Step 2: Run the repository tests and verify failure**

```bash
uv run pytest tests/alphaagent/test_limit_up_radar_observation_repository.py -q
```

Expected: missing tables/module failures.

- [x] **Step 3: Add normalized schema tables**

Add a frame header and compact child rows. Do not store full candidates or recommendation JSON in these tables.

```python
limit_up_radar_frames = Table(
    "limit_up_radar_frames",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("contract_version", String(40), nullable=False),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("source_trade_date", Date, nullable=True),
    Column("quality_status", String(24), nullable=False),
    Column("is_stale", Boolean, nullable=False),
    Column("capture_count", Integer, nullable=False),
    Column("scan_duration_ms", Integer, nullable=True),
    Column("quote_coverage_ratio", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("captured_at", "strategy_version", name="uq_limit_up_radar_frame_time_version"),
)

limit_up_radar_observations = Table(
    "limit_up_radar_observations",
    metadata,
    Column("frame_id", BigInteger, ForeignKey("limit_up_radar_frames.id", ondelete="CASCADE"), primary_key=True),
    Column("vt_symbol", String(32), ForeignKey("stocks.vt_symbol", ondelete="CASCADE"), primary_key=True),
    Column("name", String(80), nullable=False),
    Column("change_pct", Float, nullable=False),
    Column("last_price", Float, nullable=False),
    Column("previous_close", Float, nullable=False),
    Column("limit_price", Float, nullable=False),
    Column("capture_state", String(24), nullable=False),
    Column("board_lane", String(24), nullable=False),
    Column("support_score", Float, nullable=True),
    Column("entry_quality_score", Float, nullable=True),
    Column("concept_id", String(64), nullable=True),
    Column("concept_state", String(24), nullable=True),
    Column("concept_strength_score", Float, nullable=True),
    Column("concept_leader_rank", Integer, nullable=True),
    Column("concept_strong_5_count", Integer, nullable=True),
    Column("sector_id", String(64), nullable=True),
    Column("sector_heat", Float, nullable=True),
    Column("sector_touch_count", Integer, nullable=True),
    Column("history_sample_count", Integer, nullable=True),
    Column("historical_combined_rate", Float, nullable=True),
    Column("formal_action", String(24), nullable=False),
    Column("early_action", String(24), nullable=False),
    Column("early_entry_kind", String(24), nullable=False),
    Column("blocking_scope", String(24), nullable=False),
    Column("decision_reason", String(500), nullable=True),
    Column("blocker_codes", JSONB, nullable=False, server_default="[]"),
)
Index("ix_limit_up_radar_frames_date_time", limit_up_radar_frames.c.trade_date, limit_up_radar_frames.c.captured_at)
Index("ix_limit_up_radar_observations_symbol_frame", limit_up_radar_observations.c.vt_symbol, limit_up_radar_observations.c.frame_id)
```

- [x] **Step 4: Implement atomic save, bounded reads, and retention**

`save_frame` must insert the frame and its observations in one `session_scope`. `project_observation` must copy only the columns above. `prune_frames(retain_trade_days=90)` must delete complete frame days through the frame foreign key cascade. `load_observations(start, end)` must join frames to observations and order by `captured_at, vt_symbol`.

Use these exact public functions:

```python
RADAR_RETAIN_TRADE_DAYS = 90

def save_frame(
    snapshot: Mapping[str, object],
    observations: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Atomically insert one frame and its compact symbol observations."""


def load_observations(start: date, end: date) -> list[dict[str, object]]:
    """Return frame-joined observations ordered by captured_at and symbol."""


def load_frame_coverage(
    start: date | None = None,
    end: date | None = None,
) -> dict[str, object]:
    """Return valid-frame, cadence, source-date, and candidate coverage."""


def prune_frames(retain_trade_days: int = RADAR_RETAIN_TRADE_DAYS) -> int:
    """Delete complete frame days older than the latest retained trade days."""
```

- [x] **Step 5: Add a size guard test**

Serialize 200 projected observations with `json.dumps` in the test and require the payload to stay below 300 KB. This catches accidental reintroduction of `raw`, financial reports, trigger-check prose, or full concept membership arrays.

```python
encoded = json.dumps(rows, ensure_ascii=True, separators=(",", ":")).encode()
assert len(encoded) < 300_000
```

- [x] **Step 6: Run repository tests**

```bash
uv run pytest tests/alphaagent/test_limit_up_radar_observation_repository.py -q
```

Expected: all tests pass.

- [x] **Step 7: Diff checkpoint**

```bash
git diff --check -- \
  alphaagent/server/db/schema.py \
  alphaagent/server/services/limit_up/radar_observation_repository.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py
```

Expected: no whitespace errors. Do not commit unless explicitly authorized.

### Task 3: Record The Exact 3% Counterfactual At The Same Live Frame

**Files:**

- Modify: `alphaagent/server/services/limit_up/live_policy.py:402-570, 1190-1280`
- Modify: `alphaagent/server/services/limit_up/live_service.py:87-297, 1080-1270, 1770-1810`
- Modify: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [x] **Step 1: Write failing tests for the single-variable comparison**

Create one 3.8% first-board candidate whose existing lane, market, sector, concept, and momentum checks all pass. Assert the current formal decision remains absent while the internal early decision is `buy_now`. Then change only the support score below 55 and assert the internal decision is not executable.

```python
assert formal_by_symbol.get("600001.SSE") is None
assert early_by_symbol["600001.SSE"]["action"] == "buy_now"
assert early_by_symbol["600001.SSE"]["entry_kind"] == "momentum"

weak["lane_support_score"] = 54.99
assert build_early_radar_signals([weak], market_gate, captured_at)[0]["action"] != "buy_now"
```

- [x] **Step 2: Expose a pure helper that reuses the existing momentum checks**

Do not duplicate thresholds. The helper copies `pre_radar` candidates, maps only that copied state to `near_limit`, and calls the same `_now_signal` and `_candidate_execution_checks` path used by v15.

```python
def build_early_radar_signals(
    candidates: Sequence[Mapping[str, object]],
    market_gate: Mapping[str, object],
    captured_at: datetime,
) -> list[dict[str, object]]:
    stage = session_stage(captured_at)
    signals: list[dict[str, object]] = []
    for raw in candidates:
        candidate = dict(raw)
        if str(candidate.get("capture_state") or candidate.get("state") or "") == "pre_radar":
            candidate["state"] = "near_limit"
        signals.append(
            _now_signal(candidate, stage, market_gate, captured_at, stable_minutes=0)
        )
    return signals
```

Apply the existing lane validation veto and the same stale/data-quality rules before a row can be stored with `early_action="buy_now"`. This is an internal decision ledger, not a second API recommendation list.

- [x] **Step 3: Record scan-stage timings**

Capture monotonic durations for quote fetch, context load, policy evaluation, and persistence. Save only total `scan_duration_ms` in the frame table and expose the stage values in `data_quality.scan_timing_ms` for the two-day diagnostic trace.

```python
scan_timing_ms = {
    "quotes": round((quotes_done - started) * 1000),
    "context": round((context_done - quotes_done) * 1000),
    "policy": round((policy_done - context_done) * 1000),
    "persistence": round((persisted - policy_done) * 1000),
}
```

- [x] **Step 4: Persist internal observations and remove them from the public payload**

In `refresh_live_snapshot`, call `radar_observation_repository.save_frame` only for same-day, fresh, source-date-valid frames. A ledger write failure must mark `data_quality.radar_ledger_status="error"`; it must not silently claim a complete research day. It must not replace or fabricate a quote, and it must not publish `trace_capture_candidates` or `early_radar_signals` through `/api/limit-up/live`.

- [x] **Step 5: Add no-leakage API assertions**

```python
payload = refresh_live_snapshot(captured_at, adapter=fake_adapter, persist=True)
assert "trace_capture_candidates" not in payload
assert "early_radar_signals" not in payload
assert payload["recommendations"]["actionable_recommendations"] == expected_v15_rows
```

- [x] **Step 6: Run focused live tests**

```bash
uv run pytest \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_radar_observation_repository.py -q
```

Expected: all tests pass and the v15 formal list remains byte-for-byte equivalent for the existing fixtures.

- [x] **Step 7: Diff checkpoint**

```bash
git diff --check -- \
  alphaagent/server/services/limit_up/live_policy.py \
  alphaagent/server/services/limit_up/live_service.py \
  alphaagent/server/services/limit_up/radar_observation_repository.py \
  tests/alphaagent/test_limit_up_live.py
```

Expected: no whitespace errors. Do not commit unless explicitly authorized.

### Task 4: Backfill Minute Paths For Every Actually Observed 3% Candidate

**Files:**

- Modify: `alphaagent/server/services/limit_up/data_quality_repository.py`
- Modify: `alphaagent/server/services/limit_up/data_quality.py`
- Modify: `alphaagent/server/services/data_sync.py:250-275, 610-655, 1225-1270, 2080-2110`
- Test: `tests/alphaagent/test_limit_up_data_quality.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Write failing missing-pair tests**

The repository test must prove that a symbol/date observed at 3% is missing until it has all 240 distinct official one-minute slots (09:31-11:30 and 13:01-15:00), that duplicates across frames collapse to one pair, and that a 239-slot or shifted-240-row pair remains missing.

```python
assert gaps == [
    {"trade_date": "2026-07-20", "vt_symbol": "600001.SSE"},
    {"trade_date": "2026-07-20", "vt_symbol": "600002.SSE"},
]
```

- [x] **Step 2: Implement the observed-pair gap query**

Join `limit_up_radar_frames`, `limit_up_radar_observations`, and aggregated `stock_minute_bars`. Select distinct fresh-frame pairs where `interval='1m'` has fewer than 240 rows. Apply the existing retry-at ledger with provider `tdx_radar_3pct` so empty/error responses back off rather than looping.

Public repository signature and result contract:

```python
def list_missing_radar_minute_pairs(
    limit: int,
    *,
    provider: str,
    as_of: datetime,
) -> list[dict[str, object]]:
    """Return distinct observed symbol/date pairs with fewer than 240 1m bars.

    Rows are ordered by trade_date and vt_symbol and each row contains only
    trade_date and vt_symbol so it can be passed to the existing TDX importer.
    """
```

- [x] **Step 3: Add a dedicated backfill function using the existing importer**

```python
RADAR_MINUTE_BACKFILL_PROVIDER = "tdx_radar_3pct"
RADAR_MINUTE_SCOPE = "limit_up_radar_3pct_full_session"


def backfill_limit_up_radar_minutes(*, max_gaps: int = 300, dry_run: bool = True) -> dict[str, object]:
    gaps = data_quality_repository.list_missing_radar_minute_pairs(
        max_gaps,
        provider=RADAR_MINUTE_BACKFILL_PROVIDER,
        as_of=datetime.now(timezone.utc),
    )
    return minute_provider_imports.import_minute_bars_for_gaps(
        {
            "provider": "tdx",
            "gaps": gaps,
            "tail_entry_start": "09:15",
            "tail_entry_end": "15:00",
            "dry_run": dry_run,
            "max_gaps": len(gaps),
            "max_pages_per_symbol": 8,
            "timeout_seconds": 2,
        }
    )
```

Wrap this call with the existing global minute-backfill lock and persist retry outcomes exactly as `backfill_limit_up_event_minutes` does. No daily price interpolation and no alternate provider fallback are allowed.

- [x] **Step 4: Register primary and retry jobs**

Add `sync_limit_up_radar_minutes` to `DEFAULT_JOBS`, `JOB_RUNNERS`, the 19:00 primary chain, and the 21:30 retry chain. Use `max_gaps=300` at each run, giving a normal daily capacity of 600 distinct observed pairs.

- [x] **Step 5: Add schedule tests**

Assert both schedules contain the new job after the radar frames exist, and assert the runner raises `DataSyncError` for `error`, `partial`, `unavailable`, or `unsupported_interval` rather than reporting success.

- [x] **Step 6: Run focused data tests**

```bash
uv run pytest \
  tests/alphaagent/test_limit_up_data_quality.py \
  tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: all tests pass.

- [x] **Step 7: Run a dry-run against the local database**

```bash
docker compose exec -T alphaagent-api \
  python -c 'from alphaagent.server.services.limit_up.data_quality import backfill_limit_up_radar_minutes; print(backfill_limit_up_radar_minutes(max_gaps=5, dry_run=True))'
```

Expected: scope is `limit_up_radar_3pct_full_session`, no `stock_minute_bars` rows are written, and requested pairs come only from saved fresh radar frames.

- [x] **Step 8: Diff checkpoint**

```bash
git diff --check -- \
  alphaagent/server/services/limit_up/data_quality_repository.py \
  alphaagent/server/services/limit_up/data_quality.py \
  alphaagent/server/services/data_sync.py \
  tests/alphaagent/test_limit_up_data_quality.py \
  tests/alphaagent/test_data_sync_schedule.py
```

Expected: no whitespace errors. Do not commit unless explicitly authorized.

### Task 5: Build The Causal Full-Recommendation Validation

**Files:**

- Create: `alphaagent/server/services/limit_up/radar_validation.py`
- Create: `tests/alphaagent/test_limit_up_radar_validation.py`
- Reuse: `alphaagent/server/services/limit_up/entry_backtest.py`
- Reuse: `alphaagent/server/services/limit_up/cash_backtest.py`

- [x] **Step 1: Write future-function invariant tests**

Fixtures must include chronological frames, a later higher-ranked stock, a later D-day seal result, and D+1 close. Assert the selected signal is the first frame that passed at that time. Mutating later frames and D+1 outcomes must not change symbol selection or signal time.

```python
baseline = build_radar_validation_report(frames, observations, daily_bars, minute_bars)
mutated = deepcopy(observations)
mutated[-1]["entry_quality_score"] = 100.0
mutated_report = build_radar_validation_report(frames, mutated, daily_bars, minute_bars)

assert mutated_report["signals"] == baseline["signals"]
assert baseline["signals"][0]["captured_at"] == "2026-07-20T10:05:20+08:00"
```

- [x] **Step 2: Write delayed-entry tests**

```python
signal_at = datetime.fromisoformat("2026-07-20T10:05:20+08:00")
quotes = [
    {"captured_at": "2026-07-20T10:05:35+08:00", "last_price": 10.40},
    {"captured_at": "2026-07-20T10:05:42+08:00", "last_price": 10.55},
]
fill = first_delayed_quote(quotes, signal_at, delay_seconds=20, max_delay_seconds=60)
assert fill["last_price"] == 10.55
```

Also assert missing/stale quotes produce `entry_quote_missing`, and a quote at the limit price produces `queue_unknown_without_l2`.

- [x] **Step 3: Implement exact two-contract signal extraction**

```python
CONTRACTS = ("formal_5pct", "early_3pct_same_rules")
ENTRY_DELAY_SECONDS = 20
MAX_ENTRY_DELAY_SECONDS = 60


def first_signal(rows: Sequence[Mapping[str, object]], action_field: str) -> dict[str, object] | None:
    for row in sorted(rows, key=lambda item: (str(item["captured_at"]), str(item["vt_symbol"]))):
        if str(row.get(action_field) or "pass") == "buy_now":
            return dict(row)
    return None
```

Group by `trade_date, vt_symbol`; use `formal_action` for the baseline and `early_action` for the 3% contract. Never select the day's final Top1 and never replace an earlier signal with a later higher score.

- [x] **Step 4: Implement settlement and metrics**

For every signal, use the delayed saved quote as entry and the next official trading-day `stock_daily_bars.close_price` as exit. Reuse current transaction-cost functions. Produce metrics for all recommendations first, then call the existing two-position arrival-order cash backtest as a secondary section.

Required report keys:

```python
{
    "validation_version": "limit-up-radar-validation-v1",
    "contracts": {
        "formal_5pct": {"all_recommendations": {}, "two_position_account": {}},
        "early_3pct_same_rules": {"all_recommendations": {}, "two_position_account": {}},
    },
    "coverage": {},
    "reaction_time": {},
    "chronological_blocks": [],
    "acceptance": {},
    "limitations": [],
}
```

All-recommendation metrics must include signal count, closed count, win rate, average/median net return, profit factor, daily equal-weight compound return, maximum drawdown, double-cost metrics, queue-unknown count, and days with at least one recommendation.

- [x] **Step 5: Add reaction-time and concentration diagnostics**

Using full 1-minute paths, calculate first 3%, first 5%, and first limit-touch minutes with lunch excluded. Report the previous 30-minute range, lead time before touch, percentage caught at least two minutes early, profit contribution by date, and maximum single-date profit share.

- [x] **Step 6: Run validation unit tests**

```bash
uv run pytest tests/alphaagent/test_limit_up_radar_validation.py -q
```

Expected: all tests pass, including later-frame and outcome-mutation invariants.

- [x] **Step 7: Run the complete limit-up backend subset**

```bash
uv run pytest tests/alphaagent/test_limit_up*.py -q
```

Expected: all limit-up tests pass.

- [x] **Step 8: Diff checkpoint**

```bash
git diff --check -- \
  alphaagent/server/services/limit_up/radar_validation.py \
  tests/alphaagent/test_limit_up_radar_validation.py
```

Expected: no whitespace errors. Do not commit unless explicitly authorized.

### Task 6: Expose Coverage And Evidence Without Creating A Second Recommendation UI

**Files:**

- Modify: `alphaagent/server/api/limit_up.py:95-115, 410-445`
- Modify: `alphaagent/server/services/limit_up/strategy_guide.py`
- Modify: `tests/alphaagent/test_limit_up_strategy_guide.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/StrategyGuideDialog.tsx`
- Modify: `frontend/src/features/limitUp/StrategyGuideDialog.spec.tsx`

- [x] **Step 1: Write a failing read-only API test**

```python
def test_radar_validation_endpoint_is_read_only(monkeypatch) -> None:
    monkeypatch.setattr(
        limit_up,
        "get_radar_validation",
        lambda: {"status": "collecting", "coverage": {"complete_trade_days": 3}},
    )
    response = TestClient(create_app()).get("/api/limit-up/radar-validation")
    assert response.status_code == 200
    assert response.json()["data"]["coverage"]["complete_trade_days"] == 3
```

- [x] **Step 2: Add the endpoint**

```python
@router.get("/radar-validation", response_model=None)
def radar_validation():
    if not is_database_configured():
        return JSONResponse(
            status_code=503,
            content=fail("DATABASE_UNAVAILABLE", "数据库未配置，无法读取雷达验证"),
        )
    try:
        return ok(get_radar_validation())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)
```

The GET path must not fetch quotes, start backfills, or write research rows.

- [x] **Step 3: Extend the guide contract**

Add `radar_evidence` with capture threshold, current formal threshold, observed days, complete days, minute coverage, status, and the selected contract. While collecting, `selected_contract` must remain `formal_5pct` and the text must say the 3% rows are not public recommendations.

- [x] **Step 4: Add TypeScript types and render evidence in the existing dataset tab**

Do not add another recommendation panel. Add a compact table under the current dataset evidence containing only:

```ts
interface LimitUpRadarEvidence {
  status: "collecting" | "process_ready" | "ready_for_review" | "accepted" | "rejected";
  capture_min_change_pct: number;
  formal_min_change_pct: number;
  complete_trade_days: number;
  target_trade_days: number;
  minute_coverage_pct: number | null;
  selected_contract: "formal_5pct" | "early_3pct_same_rules";
}
```

- [x] **Step 5: Run backend and frontend tests**

```bash
uv run pytest \
  tests/alphaagent/test_limit_up_radar_validation.py \
  tests/alphaagent/test_limit_up_strategy_guide.py -q

cd frontend
npm test -- --run \
  src/features/limitUp/StrategyGuideDialog.spec.tsx \
  src/features/limitUp/strategyGuideApi.spec.ts
```

Expected: all selected tests pass.

- [x] **Step 6: Diff checkpoint**

```bash
git diff --check -- \
  alphaagent/server/api/limit_up.py \
  alphaagent/server/services/limit_up/strategy_guide.py \
  tests/alphaagent/test_limit_up_strategy_guide.py \
  frontend/src/api/limitUp.ts \
  frontend/src/features/limitUp/StrategyGuideDialog.tsx \
  frontend/src/features/limitUp/StrategyGuideDialog.spec.tsx
```

Expected: no whitespace errors. Do not commit unless explicitly authorized.

### Task 7: Apply Fixed Acceptance Gates And Freeze One Production Version

**Files:**

- Modify: `alphaagent/server/services/limit_up/radar_validation.py`
- Modify after acceptance only: `alphaagent/server/services/limit_up/radar_contract.py`
- Modify after acceptance only: `alphaagent/server/services/limit_up/versions.py`
- Modify after acceptance only: `alphaagent/server/services/limit_up/strategy_guide.py`
- Modify after acceptance only: `memory/09_decisions/decisions.md`
- Create after acceptance only: `memory/06_backtests/limit_up_radar_3pct_validation_final.md`
- Test: `tests/alphaagent/test_limit_up_radar_validation.py`
- Test: `tests/alphaagent/test_limit_up_live.py`

- [x] **Step 1: Encode the non-negotiable coverage gate**

```python
COVERAGE_GATE = {
    "complete_trade_days": 60,
    "closed_early_recommendations": 300,
    "minimum_signal_days": 40,
    "minute_pair_coverage_pct": 95.0,
    "valid_frame_ratio_pct": 98.0,
    "scan_gap_p90_seconds_max": 20.0,
}
```

A complete day requires same-day source dates, non-stale full-market coverage of at least 90%, frames in both configured buy windows, at least 98% valid scan frames, a per-day scan-gap P90 no greater than 20 seconds including both window edges, and at least 95% coverage of the 240 official minute slots for observed 3% pairs. A missing metric fails closed.

- [x] **Step 2: Encode the absolute reliability gate**

```python
RELIABILITY_GATE = {
    "win_rate_pct_min": 60.0,
    "average_net_return_pct_min": 1.0,
    "profit_factor_min": 1.5,
    "max_drawdown_pct_min": -15.0,
    "double_cost_profit_factor_min": 1.2,
    "positive_chronological_blocks_min": 4,
    "chronological_block_count": 5,
    "max_single_date_profit_share_pct": 15.0,
}
```

Every chronological block must contain at least 40 closed recommendations. At least four blocks must have positive average net return; no block may have profit factor below 1.0.

- [x] **Step 3: Encode the same-frame comparison gate**

The 3% contract must satisfy all of these relative to the 5% baseline on identical complete days:

```python
COMPARISON_GATE = {
    "max_win_rate_regression_pp": 2.0,
    "max_average_return_regression_pp": 0.20,
    "minimum_fast_path_caught_two_minutes_early_pct": 50.0,
    "minimum_queue_unknown_reduction_pct": 20.0,
}
```

If the 3% contract fails any absolute or comparison gate, the result is `rejected` and the 5% contract remains formal. Do not choose whichever metric looks best after seeing the outcome.

- [x] **Step 4: Add gate-boundary tests**

Test every boundary at exactly the required value and immediately below it. Also assert that `None`, missing coverage, or fewer than 60 complete days cannot produce `accepted`.

- [ ] **Step 5: Run the 20-day process review**

At 20 complete days, run:

```bash
curl -s http://localhost:8080/api/limit-up/radar-validation
```

Expected: `status="process_ready"`; execution selection remains `formal_5pct`; coverage gaps and storage growth are visible. No strategy activation is allowed at this checkpoint.

- [ ] **Step 6: Run the 60-day frozen review**

Run the same endpoint after 60 complete days and export the exact response fingerprint into `memory/06_backtests/limit_up_radar_3pct_validation_final.md`. Include dataset dates, frame and candidate counts, excluded rows by reason, all-recommendation metrics, two-position metrics, five blocks, double-cost metrics, reaction-time results, and the selected contract.

- [ ] **Step 7: Freeze only the accepted contract**

If `early_3pct_same_rules` is accepted:

```python
FORMAL_MIN_CHANGE_PCT = 3.0
LIVE_STRATEGY_VERSION = "limit-up-live-v16"
```

Remove the internal alternative-action field from newly written observations and make the one formal `actionable_recommendations` list use the accepted contract. Keep old ledger columns read-only for audit.

If it is rejected, keep:

```python
FORMAL_MIN_CHANGE_PCT = 5.0
LIVE_STRATEGY_VERSION = "limit-up-live-v15"
```

Retain 3% capture for context preloading and ongoing reaction diagnostics, but publish no 3% buy action. This is still one production algorithm.

- [ ] **Step 8: Update the strategy guide and durable decision map**

The guide must show one selected threshold and one evidence fingerprint. Replace stale v15 wording only when v16 is actually accepted. Update `memory/09_decisions/decisions.md` in place and link the detailed report rather than copying its tables.

- [ ] **Step 9: Run full verification**

```bash
uv run pytest tests/alphaagent -q

cd frontend
npm test -- --run
npm run build
```

Expected: all backend and frontend tests pass and the production build succeeds.

- [ ] **Step 10: Verify the live page and API**

Start the existing Compose stack and check:

```bash
docker compose up --build -d
curl -s http://localhost:8080/api/limit-up/strategy-guide
curl -s http://localhost:8080/api/limit-up/radar-validation
```

Open `http://localhost:8080/short-term` with Playwright at desktop and mobile sizes. Confirm the page exposes only one formal recommendation list, the strategy guide shows the selected contract, long text does not overflow, and no radar research row appears as a buy recommendation.

- [ ] **Step 11: Final diff checkpoint**

```bash
git status --short
git diff --check
git diff --stat
```

Expected: no whitespace errors; unrelated dirty-worktree changes remain untouched. Do not commit or push unless the user explicitly asks.

## Operational Result

After Tasks 1-6, users continue to see one real v15 recommendation list while the system starts computing candidates from 3%, reduces context cold-start latency, records every point-in-time alternative decision, and closes every observed candidate with minute and D+1 data. After Task 7, the system either promotes 3% into the one formal v16 contract because it passed all gates, or keeps 5% because 3% did not preserve recommendation quality. There is no permanent recommendation-A/execution-B arrangement.

The remaining same-minute path where a stock moves from below 3% to the limit between public-quote polls cannot be solved by another percentage threshold. Its explicit dependency is a broker/gateway Tick or L2 push source; until one is installed, the product must keep `queue_unknown_without_l2` and must not claim guaranteed capture or fill.
