# Limit-up Full-history Replay Implementation Plan

> **For agentic workers:** This plan has been implemented and verified; completed steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a point-in-time 600-trading-day limit-up replay, historical analog inference, corrected entry-route backtests, and date-by-date product validation.

**Architecture:** Keep the existing `limit_up` feature boundary. A pure replay engine derives candidates and outcomes from complete main-board daily bars; a repository persists versioned daily payloads; a service exposes status/day/backtest operations; the React page reads those typed REST endpoints while the existing realtime scanner remains unchanged.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/PostgreSQL JSONB, pandas for bounded batch derivation, React 19, TypeScript, TanStack Query, Vitest, pytest, Docker Compose.

---

### Task 1: Versioned replay storage

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `alphaagent/server/services/limit_up/history_repository.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] Add `limit_up_history_replays` with `(trade_date, strategy_version)` primary key, `payload`, `coverage`, and timestamps.
- [x] Add `load_reliable_history_rows`, `replace_history_replays`, `load_history_dates`, `load_history_day`, and `load_history_range`. The persisted day lookup must use the composite key directly:

```python
def load_history_day(version: str, trade_date: date) -> dict[str, object] | None:
    with session_scope() as session:
        row = session.execute(
            select(schema.limit_up_history_replays.c.payload).where(
                schema.limit_up_history_replays.c.strategy_version == version,
                schema.limit_up_history_replays.c.trade_date == trade_date,
            )
        ).scalar_one_or_none()
    return dict(row) if isinstance(row, Mapping) else None
```

- [x] Verify reliable history starts only when daily coverage is at least 3000 symbols and includes 35 lookback plus 2 outcome bars.
- [x] Run `uv run pytest tests/alphaagent/test_limit_up_history.py -q` and expect the repository tests to pass.

### Task 2: Point-in-time replay engine

**Files:**
- Create: `alphaagent/server/services/limit_up/history_engine.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] Write failing tests proving `auction` uses D open with prior streak 0 and `next_auction` uses D-1 board 1/2 with D open.
- [x] Write failing tests proving D final seal and D+1 return cannot change D 09:25 ranking.
- [x] Implement the engine entrypoint:

```python
HISTORY_STRATEGY_VERSION = "limit-up-history-v3"

def build_history_replays(
    rows: list[dict[str, object]],
    *,
    commission_rate: float = 0.0003,
    stamp_tax_rate: float = 0.0005,
    slippage_bps: float = 10.0,
) -> list[dict[str, object]]:
    frame = _build_daily_feature_frame(rows)
    return _build_chronological_replays(
        frame,
        total_cost_rate=commission_rate * 2 + stamp_tax_rate + slippage_bps * 2 / 10_000,
    )
```

- [x] Derive previous close, limit touch/seal, prior streak, gap, 5/20-day returns, turnover/amount ratios, D-1 market breadth and board ladder without using future columns in the feature payload.
- [x] Produce separate `auction`, `sweep`, `tail`, and `next_auction` lanes with explicit `signal_date`, `plan_date`, `entry_date`, `result_date`, target board and execution confidence.
- [x] Run focused tests and expect no-lookahead and route-separation assertions to pass.

### Task 3: Prior-only analog inference and Top5

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_engine.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] Add a chronological accumulator that only matures samples when `result_date < signal_date`.
- [x] Add hierarchical analog lookup:

```python
@dataclass
class AnalogStats:
    sample_count: int
    effective_sample_count: int
    smoothed_win_rate: float | None
    average_return_pct: float | None
    hard_loss_rate: float | None
    touch_rate: float | None
    seal_rate: float | None
    confidence: str
```

- [x] Rank each lane using only analog expectation and pretrade fields, keep Top5, and store favorable/risk factor explanations.
- [x] Keep the first 120 dates as warmup and mark the final 120 dates as `locked_holdout`.
- [x] Test that changing a future outcome does not alter any earlier Top5 or analog statistics.

### Task 4: Persistence service and corrected backtest

**Files:**
- Create: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/services/limit_up/entry_backtest.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] Implement a single-flight rebuild that retains the prior version on failure and persists the complete new version only after construction succeeds.
- [x] Implement status, dates, day and range report functions.
- [x] Build per-route summaries from persisted Top5 only, including expanding OOS, locked holdout, monthly and board-level buckets.
- [x] Remove the historical branch that assigns `entry_offset=1` to both `auction` and `next_auction`; legacy 19-day proxy must no longer drive product backtest results.
- [x] Verify costs, entry/exit dates and compounded equity with unit tests.

### Task 5: REST API contract

**Files:**
- Modify: `alphaagent/server/api/limit_up.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] Add the five `/limit-up/history/*` endpoints with FastAPI `date` and literal route validation.
- [x] Return `202 building` from rebuild start, `409` when already building, `404` for dates outside reliable history, and the existing structured failure envelope for operational errors.
- [x] Ensure `/history/dates` reports full daily coverage separately from recent event/fund-flow coverage.
- [x] Run API tests and expect valid responses plus invalid-range rejection.

### Task 6: Historical day validation UI

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Create: `frontend/src/features/limitUp/HistoricalReplayPanel.tsx`
- Create: `frontend/src/features/limitUp/HistoricalReplayPanel.spec.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] Add TypeScript types and fetchers for status, dates, day and history backtest.
- [x] Render a date navigator and route tabs labelled `当日竞价·首板`, `盘中扫/回封`, `尾盘确认`, `明早竞价·二三板`.
- [x] For each selected Top5 candidate show known-at fields, target board, action, analog sample/win/return/hard-loss metrics and actual D/D+1 result.
- [x] Display warmup, expanding OOS, locked holdout and survivorship/data-quality badges without presenting proxy fills as actual fills.
- [x] Test route switching and result/feature separation with Vitest.

### Task 7: Full-history backtest UI

**Files:**
- Modify: `frontend/src/features/limitUp/EntryBacktestPanel.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `frontend/src/features/limitUp/HistoricalReplayPanel.spec.tsx`

- [x] Replace the 19-day entry backtest request with `/history/backtest` and default to all reliable dates.
- [x] Show total reliable days, evaluated days, Top5 signals, expanding OOS and holdout summaries.
- [x] Keep detailed rows pageable/limited in the response so the browser does not render all 600 days at once.
- [x] Run `pnpm --dir frontend test -- --run` and `pnpm --dir frontend run build` and expect both to pass.

### Task 8: Build real ledger and verify the product

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/limit_up_short_term_factor_research.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] Rebuild API, trigger the real 600-day ledger, and verify the persisted date count and start/end dates.
- [x] Record actual per-route OOS and holdout metrics without claiming stability when they are negative or sparse.
- [x] Run all limit-up/data-sync tests, frontend tests and production build.
- [x] Rebuild Docker API/Web and verify health.
- [x] Use Playwright at desktop and 390x844 to validate date changes, four routes, backtest range, overflow, console and network errors.

### Task 9: Audit successful boards and direct breakdowns

**Files:**
- Create: `alphaagent/server/services/limit_up/factor_audit.py`
- Modify: `alphaagent/server/api/limit_up.py`
- Create: `frontend/src/features/limitUp/FactorAuditPanel.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [x] Classify D+1 continuation, open/close premium, intraday repair, high-open fade, direct breakdown and no-premium outcomes for all four entry paths.
- [x] Keep the audit scope explicit as Top5 candidate outcomes rather than fills or executable trades.
- [x] Rank factors only on expanding OOS samples and use locked holdout solely to validate direction.
- [x] Prove that changing holdout outcomes cannot alter expanding OOS statistics or factor ordering.
- [x] Add `/limit-up/history/factors` and a shared-date/shared-entry/shared-exit frontend panel with winner and breakdown examples.
- [x] Verify all four paths, D+1 open/close linkage, local table overflow, desktop/mobile layout, console/network, backend tests, frontend tests and production build.

No git commit steps are included because repository instructions prohibit commits unless the user explicitly requests one.
