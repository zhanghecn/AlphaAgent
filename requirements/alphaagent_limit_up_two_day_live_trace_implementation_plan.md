# AlphaAgent Two-Trade-Day Limit-Up Live Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents unless the user explicitly authorizes delegation.

**Goal:** Preserve every intraday scan for the latest two trading days, capture first-board candidates from 5% as observation-only radar data, and expose a compact per-stock timeline without changing official recommendation or backtest semantics.

**Architecture:** Add an append-only PostgreSQL diagnostic table beside the existing minute-upsert official snapshot table. Build a 5% trace radar independently from the existing 7% recommendation universe, write trace failures without blocking official snapshots, and derive date/stock timelines on the read side. The existing `/limit-up` screen remains the product entry and adds a compact today/previous-trading-day trace below current opportunities.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2, PostgreSQL JSONB, pytest, React 18, TypeScript, TanStack Query, Vitest, Tailwind CSS.

**Commit policy:** The repository `AGENTS.md` forbids commits without explicit user authorization. Commit steps below are checkpoints only; skip them unless the user explicitly requests commits during execution.

**Status (2026-07-14):** Implementation and verification complete; commit checkpoints were intentionally skipped. The delivered implementation additionally projects trace rows to diagnostic-only fields, incrementally aggregates rows by database ID, and fixes the existing mobile shell positioning bug found during browser acceptance. Verification: 498 related backend tests, 38 frontend tests, TypeScript production build, scoped Ruff checks, Compose deployment, and desktop/mobile Playwright acceptance.

---

## File Structure

- Create `alphaagent/server/services/limit_up/live_trace_repository.py`: append-only trace persistence, two-trading-day retention, and bounded date reads.
- Create `alphaagent/server/services/limit_up/live_trace_service.py`: trace payload normalization, event derivation, day summaries, and per-symbol timelines.
- Modify `alphaagent/server/db/schema.py`: declare `limit_up_live_trace_snapshots` and compatible indexes.
- Modify `alphaagent/server/services/limit_up/live_service.py`: build the independent 5% radar and record every scan/error without changing official candidates.
- Modify `alphaagent/server/services/data_sync.py`: add the idempotent EOD retention compensation job.
- Modify `alphaagent/server/api/limit_up.py`: add authenticated read-only trace endpoints.
- Create `tests/alphaagent/test_limit_up_live_trace.py`: repository/service retention and timeline tests.
- Modify `tests/alphaagent/test_limit_up_live.py`: radar isolation and live-scan integration tests.
- Modify `tests/alphaagent/test_api.py`: endpoint contract/error tests.
- Modify `frontend/src/api/limitUp.ts`: trace response types and API calls.
- Create `frontend/src/features/limitUp/liveTrace.ts`: small presentation helpers with no network or component state.
- Create `frontend/src/features/limitUp/liveTrace.spec.ts`: trace sorting/status tests.
- Modify `frontend/src/pages/LimitUpPage.tsx`: date selector, compact day trace, and on-demand symbol event expansion.
- Modify `memory/03_data/data_flow.md`: record the final retention and verification path.

### Task 1: Add Append-Only Trace Storage

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/limit_up/live_trace_repository.py`
- Create: `tests/alphaagent/test_limit_up_live_trace.py`

- [ ] **Step 1: Write failing schema and retention tests**

Add tests that require the new table and pure retention cutoff:

```python
from datetime import date

from alphaagent.server.db import schema
from alphaagent.server.services.limit_up import live_trace_repository


def test_live_trace_table_is_registered() -> None:
    assert "limit_up_live_trace_snapshots" in schema.metadata.tables


def test_retention_cutoff_keeps_two_latest_trade_dates() -> None:
    dates = [date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14)]

    assert live_trace_repository.retention_cutoff(dates, retain_trade_days=2) == date(2026, 7, 13)
    assert live_trace_repository.retention_cutoff(dates[:1], retain_trade_days=2) is None
```

Add a fake-session test that calls `save_live_trace_snapshot()` twice with captured times in the same minute and asserts two independent insert executions rather than an upsert.

- [ ] **Step 2: Run the focused test and verify failure**

Run:

```bash
uv run pytest -q tests/alphaagent/test_limit_up_live_trace.py
```

Expected: failure because the table and repository module do not exist.

- [ ] **Step 3: Declare the table and indexes**

Add the following SQLAlchemy table near `limit_up_signal_snapshots`:

```python
limit_up_live_trace_snapshots = Table(
    "limit_up_live_trace_snapshots",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("trade_date", Date, nullable=False),
    Column("source_trade_date", Date, nullable=True),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("session_stage", String(32), nullable=False),
    Column("strategy_version", String(40), nullable=False),
    Column("mode", String(32), nullable=False, server_default="live_trace"),
    Column("source", String(160), nullable=False),
    Column("source_updated_at", DateTime(timezone=True), nullable=True),
    Column("market_context", JSONB, nullable=False, server_default="{}"),
    Column("radar_candidates", JSONB, nullable=False, server_default="[]"),
    Column("ranked_candidates", JSONB, nullable=False, server_default="[]"),
    Column("recommendations", JSONB, nullable=False, server_default="{}"),
    Column("data_quality", JSONB, nullable=False, server_default="{}"),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)
Index(
    "ix_limit_up_live_trace_date_time",
    limit_up_live_trace_snapshots.c.trade_date,
    limit_up_live_trace_snapshots.c.captured_at,
)
Index(
    "ix_limit_up_live_trace_version_date_time",
    limit_up_live_trace_snapshots.c.strategy_version,
    limit_up_live_trace_snapshots.c.trade_date,
    limit_up_live_trace_snapshots.c.captured_at,
)
```

`metadata.create_all()` creates the table for existing deployments; no destructive migration is required.

- [ ] **Step 4: Implement focused repository functions**

Implement these public functions in `live_trace_repository.py` using the existing `session_scope()` transaction boundary:

```python
from datetime import date, datetime
from typing import Mapping, Sequence

from sqlalchemy import delete, desc, insert, select

from alphaagent.server.db import schema
from alphaagent.server.db.session import session_scope


TRACE_RETAIN_TRADE_DAYS = 2
_last_pruned_trade_date: date | None = None


def retention_cutoff(
    trade_dates: Sequence[date],
    *,
    retain_trade_days: int = TRACE_RETAIN_TRADE_DAYS,
) -> date | None:
    ordered = sorted(set(trade_dates), reverse=True)
    return ordered[retain_trade_days - 1] if len(ordered) >= retain_trade_days else None


def save_live_trace_snapshot(snapshot: Mapping[str, object]) -> dict[str, object]:
    captured_at = _as_datetime(snapshot["captured_at"])
    trade_date = captured_at.date()
    source_trade_date = _optional_date(snapshot.get("trade_date"))
    values = {
        "trade_date": trade_date,
        "source_trade_date": source_trade_date,
        "captured_at": captured_at,
        "session_stage": str(snapshot.get("session_stage") or "closed"),
        "strategy_version": str(snapshot.get("strategy_version") or "unknown"),
        "mode": "live_trace",
        "source": str(snapshot.get("source") or "unknown"),
        "source_updated_at": _optional_datetime(snapshot.get("source_updated_at")),
        "market_context": dict(snapshot.get("market_context") or {}),
        "radar_candidates": list(snapshot.get("trace_radar_candidates") or []),
        "ranked_candidates": list(snapshot.get("candidates") or []),
        "recommendations": dict(snapshot.get("recommendations") or {}),
        "data_quality": dict(snapshot.get("data_quality") or {}),
    }
    with session_scope() as session:
        row = session.execute(
            insert(schema.limit_up_live_trace_snapshots)
            .values(**values)
            .returning(schema.limit_up_live_trace_snapshots)
        ).mappings().one()
    _prune_once_for_trade_date(trade_date)
    return dict(row)


def save_live_trace_error(
    captured_at: datetime,
    error: Exception,
    *,
    strategy_version: str,
) -> dict[str, object]:
    values = {
        "trade_date": captured_at.date(),
        "source_trade_date": None,
        "captured_at": captured_at,
        "session_stage": "scan_error",
        "strategy_version": strategy_version,
        "mode": "scan_error",
        "source": "unavailable",
        "market_context": {},
        "radar_candidates": [],
        "ranked_candidates": [],
        "recommendations": {},
        "data_quality": {"status": "error", "error": str(error)[:500]},
    }
    with session_scope() as session:
        row = session.execute(
            insert(schema.limit_up_live_trace_snapshots)
            .values(**values)
            .returning(schema.limit_up_live_trace_snapshots)
        ).mappings().one()
    return dict(row)


def load_live_trace_dates(limit: int = TRACE_RETAIN_TRADE_DAYS) -> list[date]:
    with session_scope() as session:
        rows = session.execute(
            select(schema.limit_up_live_trace_snapshots.c.trade_date)
            .where(schema.limit_up_live_trace_snapshots.c.mode == "live_trace")
            .distinct()
            .order_by(desc(schema.limit_up_live_trace_snapshots.c.trade_date))
            .limit(max(limit, 1))
        ).scalars().all()
    return list(rows)


def load_live_trace_rows(trade_date: date) -> list[dict[str, object]]:
    with session_scope() as session:
        rows = session.execute(
            select(schema.limit_up_live_trace_snapshots)
            .where(schema.limit_up_live_trace_snapshots.c.trade_date == trade_date)
            .order_by(schema.limit_up_live_trace_snapshots.c.captured_at)
        ).mappings().all()
    return [dict(row) for row in rows]


def prune_live_trace_snapshots(retain_trade_days: int = TRACE_RETAIN_TRADE_DAYS) -> int:
    dates = load_live_trace_dates(limit=max(retain_trade_days + 1, 3))
    cutoff = retention_cutoff(dates, retain_trade_days=retain_trade_days)
    if cutoff is None:
        return 0
    with session_scope() as session:
        result = session.execute(
            delete(schema.limit_up_live_trace_snapshots).where(
                schema.limit_up_live_trace_snapshots.c.trade_date < cutoff
            )
        )
    return max(int(result.rowcount or 0), 0)
```

Add these conversion and pruning helpers in the same module:

```python
def _as_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("captured_at must include a timezone")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    return None if value in (None, "") else _as_datetime(value)


def _optional_date(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _prune_once_for_trade_date(trade_date: date) -> None:
    global _last_pruned_trade_date
    if _last_pruned_trade_date == trade_date:
        return
    prune_live_trace_snapshots()
    _last_pruned_trade_date = trade_date
```

Use a plain `insert(table).returning(table)` for every successful scan; never call PostgreSQL upsert for this table.

- [ ] **Step 5: Run repository tests**

Run:

```bash
uv run pytest -q tests/alphaagent/test_limit_up_live_trace.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 6: Conditional commit checkpoint**

If and only if commit authorization exists:

```bash
git add alphaagent/server/db/schema.py alphaagent/server/services/limit_up/live_trace_repository.py tests/alphaagent/test_limit_up_live_trace.py
git commit -m "feat(limit-up): add two-day live trace storage"
```

### Task 2: Capture a 5% Radar Without Changing Buy Candidates

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `tests/alphaagent/test_limit_up_live.py`

- [ ] **Step 1: Write a failing radar-isolation test**

Create a quote payload with one 5.5% stock and one 9.2% stock, both with valid sector context:

```python
def test_trace_radar_starts_at_five_percent_without_expanding_official_candidates() -> None:
    quotes = {
        "items": [
            {"vt_symbol": "600001.SSE", "name": "预热股", "change_pct": 5.5, "last_price": 10.55, "previous_close": 10.0},
            {"vt_symbol": "600002.SSE", "name": "临板股", "change_pct": 9.2, "last_price": 10.92, "previous_close": 10.0},
        ]
    }
    context = {
        "by_symbol": {
            "600001.SSE": {"sector_id": "BK1", "sector_name": "机器人"},
            "600002.SSE": {"sector_id": "BK2", "sector_name": "算力"},
        }
    }

    snapshot = build_live_snapshot(
        quotes,
        {"trade_date": "20260714", "pools": {}},
        datetime(2026, 7, 14, 10, 5, tzinfo=SHANGHAI),
        context,
    )

    assert {row["vt_symbol"] for row in snapshot["trace_radar_candidates"]} == {
        "600001.SSE",
        "600002.SSE",
    }
    assert {row["vt_symbol"] for row in snapshot["candidates"]} == {"600002.SSE"}
```

- [ ] **Step 2: Run the test and verify failure**

Run:

```bash
uv run pytest -q tests/alphaagent/test_limit_up_live.py::test_trace_radar_starts_at_five_percent_without_expanding_official_candidates
```

Expected: failure because `trace_radar_candidates` is absent.

- [ ] **Step 3: Separate radar and recommendation thresholds**

Add constants and a threshold argument to the existing function. Preserve its body and make only the shown comparison replacement:

```python
NEAR_LIMIT_MIN_CHANGE_PCT = 7.0
TRACE_RADAR_MIN_CHANGE_PCT = 5.0

# Add this keyword-only argument to _merge_source_rows:
min_change_pct: float = NEAR_LIMIT_MIN_CHANGE_PCT

# Replace the current hard-coded quote filter with:
change_pct < min_change_pct
```

Build and enrich the 5% radar first, then derive the existing 7% recommendation rows independently. Do not pass 5%-7% rows to `rank_live_candidates()`, `_attach_lane_decisions()`, `rank_live_opportunities()`, or `build_live_recommendations()`.

Update `_candidate_symbols()` to request context for the 5% trace universe so first-board sector and prior-gene evidence are available in the diagnostic cache.

- [ ] **Step 4: Preserve every scan and every total-source failure**

After `_apply_live_risk_gates()` and before official `save_snapshot()`, call trace persistence inside its own `try/except`:

```python
try:
    save_live_trace_snapshot(snapshot)
except Exception as trace_exc:  # noqa: BLE001
    logger.warning("limit-up live trace write failed: %s", trace_exc)
```

In the outer provider exception branch, call `save_live_trace_error()` before returning the official stale fallback. A trace write failure must never skip `save_snapshot()` for a valid official snapshot.

- [ ] **Step 5: Add integration tests for trace isolation**

Cover all of these assertions:

- valid current-date scan calls both `save_live_trace_snapshot()` and `save_snapshot()` once;
- stale provider date writes a diagnostic row but does not write an official snapshot;
- trace repository exception still permits official `save_snapshot()`;
- complete provider failure records `scan_error` and returns the previous official snapshot;
- official recommendation inputs remain unchanged when a 5.5% radar stock is present.

- [ ] **Step 6: Run live scan tests**

Run:

```bash
uv run pytest -q tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_live_trace.py
```

Expected: all tests pass.

- [ ] **Step 7: Conditional commit checkpoint**

If authorized:

```bash
git add alphaagent/server/services/limit_up/live_service.py tests/alphaagent/test_limit_up_live.py
git commit -m "feat(limit-up): capture first-board preheat traces"
```

### Task 3: Derive Stable Day and Symbol Timelines

**Files:**
- Create: `alphaagent/server/services/limit_up/live_trace_service.py`
- Modify: `tests/alphaagent/test_limit_up_live_trace.py`

- [ ] **Step 1: Write failing transition tests**

Build three synthetic snapshots in the same minute:

```python
rows = [
    trace_row("10:05:05", radar=[candidate("600001.SSE", 5.2, "near_limit")], ranked=[]),
    trace_row("10:05:20", radar=[candidate("600001.SSE", 9.3, "near_limit")], ranked=[signal("600001.SSE", "approaching_trigger")]),
    trace_row("10:05:42", radar=[candidate("600001.SSE", 10.0, "sealed")], ranked=[]),
]

events = build_symbol_trace(rows, "600001.SSE")

assert [event["event"] for event in events] == [
    "radar_entered",
    "recommended",
    "approaching_trigger",
    "dropped_from_top5",
    "missed",
    "sealed",
]
assert not any(event["event"] == "trigger_ready" for event in events)
```

Add separate tests for:

- a real `trigger_ready` event followed by `invalidated`, preserving `triggered_at`;
- a symbol absent in the next scan producing one `source_missing` transition;
- consecutive identical scans being compressed;
- `build_day_trace()` returning first/last seen, highest state, final state, lane, `ever_recommended`, and `ever_triggered`;
- hard-block reasons remaining attached to the event that caused invalidation.

- [ ] **Step 2: Run transition tests and verify failure**

Run:

```bash
uv run pytest -q tests/alphaagent/test_limit_up_live_trace.py -k "trace or transition"
```

Expected: failure because the trace service does not exist.

- [ ] **Step 3: Implement pure event derivation**

Implement the read-side wrappers exactly around repository reads:

```python
def get_live_trace_dates() -> dict[str, object]:
    dates = live_trace_repository.load_live_trace_dates()
    values = [value.isoformat() for value in dates]
    return {"status": "ready" if values else "empty", "dates": values, "latest": values[0] if values else None}


def get_live_trace_day(trade_date: date) -> dict[str, object]:
    rows = live_trace_repository.load_live_trace_rows(trade_date)
    if not rows:
        return {"status": "not_found", "trade_date": trade_date.isoformat(), "items": []}
    return build_day_trace(rows)


def get_live_trace_symbol(trade_date: date, vt_symbol: str) -> dict[str, object]:
    rows = live_trace_repository.load_live_trace_rows(trade_date)
    events = build_symbol_trace(rows, vt_symbol.upper())
    if not events:
        return {
            "status": "not_found",
            "trade_date": trade_date.isoformat(),
            "vt_symbol": vt_symbol.upper(),
            "events": [],
        }
    return {
        "status": "ready",
        "trade_date": trade_date.isoformat(),
        "vt_symbol": vt_symbol.upper(),
        "events": events,
    }
```

Use this transition helper as the single event vocabulary boundary:

```python
def transition_events(
    previous: Mapping[str, object] | None,
    current: Mapping[str, object] | None,
) -> list[str]:
    if previous is None and current is None:
        return []
    if current is None:
        return ["source_missing"] if previous is not None else []
    events: list[str] = []
    if previous is None:
        events.append("radar_entered")
    previous_ranked = bool(previous and previous.get("in_top5"))
    current_ranked = bool(current.get("in_top5"))
    if current_ranked and not previous_ranked:
        events.append("recommended")
    if previous_ranked and not current_ranked:
        events.append("dropped_from_top5")
    signal_state = str(current.get("signal_state") or "")
    previous_signal_state = str(previous.get("signal_state") or "") if previous else ""
    if signal_state == "approaching_trigger" and signal_state != previous_signal_state:
        events.append("approaching_trigger")
    if signal_state == "trigger_ready" and signal_state != previous_signal_state:
        events.append("trigger_ready")
    state = str(current.get("state") or "")
    previous_state = str(previous.get("state") or "") if previous else ""
    if state in {"sealed", "resealed"} and state != previous_state:
        if not bool(current.get("ever_triggered")):
            events.append("missed")
        events.append(state)
    if state == "failed" and state != previous_state:
        events.append("failed")
    if signal_state == "invalidated" and signal_state != previous_signal_state:
        events.append("invalidated")
    return events
```

`build_symbol_trace()` must create one normalized per-symbol state per snapshot, call `transition_events(previous, current)`, attach the current snapshot time/price/distance/market gate/blockers to each returned event, and update `ever_triggered` only after a real `trigger_ready`. `build_day_trace()` calls `build_symbol_trace()` for every symbol and returns stable summaries sorted by active state priority, then first-seen time and symbol.

Keep event derivation read-only and prior-to-current: each event may only use the current row and earlier rows. Use explicit event priority instead of sorting by Chinese labels. Return `status="not_found"` for unavailable dates/symbols.

- [ ] **Step 4: Run trace service tests**

Run:

```bash
uv run pytest -q tests/alphaagent/test_limit_up_live_trace.py
```

Expected: all repository and service tests pass.

- [ ] **Step 5: Conditional commit checkpoint**

If authorized:

```bash
git add alphaagent/server/services/limit_up/live_trace_service.py tests/alphaagent/test_limit_up_live_trace.py
git commit -m "feat(limit-up): derive intraday stock traces"
```

### Task 4: Expose Read-Only Trace APIs

**Files:**
- Modify: `alphaagent/server/api/limit_up.py`
- Modify: `tests/alphaagent/test_api.py`

- [ ] **Step 1: Write failing API contract tests**

Monkeypatch the trace service and assert the envelope and parameters for:

```python
GET /api/limit-up/live-traces/dates
GET /api/limit-up/live-traces/day?date=2026-07-14
GET /api/limit-up/live-traces/symbol?date=2026-07-14&vt_symbol=600001.SSE
```

Also assert `404` with `LIVE_TRACE_DATE_NOT_FOUND` or `LIVE_TRACE_SYMBOL_NOT_FOUND`, and retain the existing `503 DATABASE_UNAVAILABLE` behavior.

- [ ] **Step 2: Run the endpoint tests and verify failure**

Run:

```bash
uv run pytest -q tests/alphaagent/test_api.py -k "live_trace"
```

Expected: 404 because routes are absent.

- [ ] **Step 3: Add three authenticated routes**

Import the service functions and add routes beside `/live`:

```python
@router.get("/live-traces/dates", response_model=None)
def live_trace_dates():
    if not is_database_configured():
        return JSONResponse(status_code=503, content=fail("DATABASE_UNAVAILABLE", "数据库未配置"))
    try:
        return ok(get_live_trace_dates())
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/live-traces/day", response_model=None)
def live_trace_day(trade_date: date = Query(alias="date")):
    if not is_database_configured():
        return JSONResponse(status_code=503, content=fail("DATABASE_UNAVAILABLE", "数据库未配置"))
    try:
        result = get_live_trace_day(trade_date)
        if result.get("status") == "not_found":
            return JSONResponse(status_code=404, content=fail("LIVE_TRACE_DATE_NOT_FOUND", "没有该日实时轨迹"))
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)


@router.get("/live-traces/symbol", response_model=None)
def live_trace_symbol(
    trade_date: date = Query(alias="date"),
    vt_symbol: str = Query(min_length=8, max_length=32),
):
    if not is_database_configured():
        return JSONResponse(status_code=503, content=fail("DATABASE_UNAVAILABLE", "数据库未配置"))
    try:
        result = get_live_trace_symbol(trade_date, vt_symbol.upper())
        if result.get("status") == "not_found":
            return JSONResponse(status_code=404, content=fail("LIVE_TRACE_SYMBOL_NOT_FOUND", "没有该股实时轨迹"))
        return ok(result)
    except Exception as exc:  # noqa: BLE001
        return _service_error(exc)
```

Normalize `vt_symbol` to uppercase. Do not add a mutation or manual backfill endpoint.

- [ ] **Step 4: Run API and service tests**

Run:

```bash
uv run pytest -q tests/alphaagent/test_api.py -k "limit_up and (live or trace)" tests/alphaagent/test_limit_up_live_trace.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Conditional commit checkpoint**

If authorized:

```bash
git add alphaagent/server/api/limit_up.py tests/alphaagent/test_api.py
git commit -m "feat(limit-up): expose two-day trace API"
```

### Task 5: Add EOD Retention Compensation

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [ ] **Step 1: Write failing schedule tests**

Assert that `limit_up_live_trace_prune` is an internal batch job present at the end of both `eod_1900` and `eod_finalize_2130`. Monkeypatch `prune_live_trace_snapshots()` to return 321 and assert the batch wrapper reports `rows_read=321`, `rows_written=321`, and a two-trading-day retention message.

- [ ] **Step 2: Run focused scheduler tests and verify failure**

Run:

```bash
uv run pytest -q tests/alphaagent/test_data_sync_schedule.py -k "live_trace or default_batch_schedules"
```

Expected: failure because the internal job is unknown.

- [ ] **Step 3: Register the cleanup job**

Add:

```python
LIMIT_UP_LIVE_TRACE_PRUNE_BATCH_JOB_ID = "limit_up_live_trace_prune"
```

Include it in `INTERNAL_BATCH_JOB_IDS`, both EOD `job_ids`, `_assert_known_jobs()` allowance, and `_run_sync_batch()` dispatch. Implement the wrapper:

```python
def _run_limit_up_live_trace_prune_batch_job() -> dict[str, Any]:
    deleted = prune_live_trace_snapshots()
    return {
        "rows_read": deleted,
        "rows_written": deleted,
        "status": "succeeded",
        "message": f"实时打板诊断缓存保留最近2个交易日，清理 {deleted} 行",
    }
```

- [ ] **Step 4: Run scheduler and trace tests**

Run:

```bash
uv run pytest -q tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_limit_up_live_trace.py
```

Expected: all selected tests pass.

- [ ] **Step 5: Conditional commit checkpoint**

If authorized:

```bash
git add alphaagent/server/services/data_sync.py tests/alphaagent/test_data_sync_schedule.py
git commit -m "chore(limit-up): prune live traces after close"
```

### Task 6: Add the Compact Two-Day Trace to `/limit-up`

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Create: `frontend/src/features/limitUp/liveTrace.ts`
- Create: `frontend/src/features/limitUp/liveTrace.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [ ] **Step 1: Define trace API types and failing helper tests**

Add types for dates, day summaries, and symbol events. Test deterministic sorting and labels:

```typescript
expect(sortLiveTraceItems([
  trace("600001.SSE", "sealed", false),
  trace("600002.SSE", "approaching_trigger", false),
  trace("600003.SSE", "invalidated", true),
]).map((row) => row.vt_symbol)).toEqual([
  "600002.SSE",
  "600003.SSE",
  "600001.SSE",
]);

expect(liveTraceStatusLabel("missed")).toBe("已封板，错过不追");
expect(liveTraceStatusLabel("dropped_from_top5")).toBe("已跌出当前 Top5");
```

- [ ] **Step 2: Run helper tests and verify failure**

Run:

```bash
pnpm --dir frontend test -- src/features/limitUp/liveTrace.spec.ts
```

Expected: failure because the module does not exist.

- [ ] **Step 3: Add API functions**

Add:

```typescript
export function fetchLimitUpLiveTraceDates(): Promise<LimitUpLiveTraceDates> {
  return apiClient.get("/limit-up/live-traces/dates");
}

export function fetchLimitUpLiveTraceDay(date: string): Promise<LimitUpLiveTraceDay> {
  return apiClient.get(`/limit-up/live-traces/day?date=${encodeURIComponent(date)}`);
}

export function fetchLimitUpLiveTraceSymbol(date: string, vtSymbol: string): Promise<LimitUpLiveTraceSymbol> {
  const query = new URLSearchParams({ date, vt_symbol: vtSymbol });
  return apiClient.get(`/limit-up/live-traces/symbol?${query.toString()}`);
}
```

- [ ] **Step 4: Implement the compact single-page interaction**

In `LimitUpPage.tsx`:

- fetch trace dates while the live view is active;
- default to the latest trace date and retain a valid user selection across refetches;
- render a two-option segmented control for today/previous trading day;
- keep current opportunities above the trace;
- render a full-width, compact `LiveTraceTable` with stock, lane, first/last time, highest state, final/current state, and one concise reason;
- use a chevron icon button with a tooltip/accessible label to expand one symbol;
- fetch detailed symbol events only while expanded;
- show event time, state, price/distance, market gate, and blocker reason in unframed rows;
- do not create nested cards, a new primary navigation tab, or a marketing-style explanation block.

- [ ] **Step 5: Run frontend tests and build**

Run:

```bash
pnpm --dir frontend test -- src/features/limitUp/liveTrace.spec.ts src/features/limitUp/livePortfolio.spec.ts src/features/limitUp/nextSessionPlan.spec.ts
pnpm --dir frontend build
```

Expected: tests pass and Vite production build succeeds.

- [ ] **Step 6: Conditional commit checkpoint**

If authorized:

```bash
git add frontend/src/api/limitUp.ts frontend/src/features/limitUp/liveTrace.ts frontend/src/features/limitUp/liveTrace.spec.ts frontend/src/pages/LimitUpPage.tsx
git commit -m "feat(limit-up): show two-day live stock traces"
```

### Task 7: Full Verification, Deployment Check, and Project Memory

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Verify: all files changed in Tasks 1-6

- [ ] **Step 1: Run backend regression tests**

Run:

```bash
uv run pytest -q \
  tests/alphaagent/test_limit_up_live_trace.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_api.py \
  tests/alphaagent/test_data_sync_schedule.py
```

Expected: all selected tests pass with no new warnings caused by this feature.

- [ ] **Step 2: Run frontend regression tests and build**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend build
```

Expected: all Vitest suites pass and the production build succeeds.

- [ ] **Step 3: Rebuild the local product and verify schema**

Run:

```bash
docker compose up -d --build alphaagent-api alphaagent-web alphaagent-gateway
docker compose ps
```

Expected: API and gateway become healthy. Verify the diagnostic table exists and official table constraints remain unchanged:

```bash
docker compose exec -T alphaagent-api python -c \
'from alphaagent.server.db import schema; print("limit_up_live_trace_snapshots" in schema.metadata.tables)'
```

Expected output: `True`.

- [ ] **Step 4: Verify retention and same-minute append behavior**

During an active session, wait for at least two completed scans in one minute, then query through the repository or database and confirm both `captured_at` values exist. Verify `/api/limit-up/live-traces/dates` returns no more than two dates and that a traced symbol retains `dropped_from_top5` or `missed` instead of disappearing.

Outside an active session, run the repository/service tests as the deterministic substitute; do not fabricate live rows and present them as real market evidence.

- [ ] **Step 5: Update durable project memory**

Add a concise current-state bullet to `memory/03_data/data_flow.md` covering:

- official minute snapshot versus append-only diagnostic trace separation;
- 5% trace-only radar versus unchanged 7% recommendation universe;
- latest-two-trading-day retention;
- three read-only API routes and `/limit-up` trace location.

- [ ] **Step 6: Audit the final diff**

Run:

```bash
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors; only the approved feature, tests, requirements, and memory files are changed.

- [ ] **Step 7: Conditional final commit**

Only with explicit authorization:

```bash
git add alphaagent frontend tests requirements memory/03_data/data_flow.md
git commit -m "feat(limit-up): retain two-day live recommendation traces"
```
