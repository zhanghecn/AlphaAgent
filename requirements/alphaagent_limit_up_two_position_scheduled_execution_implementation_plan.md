# AlphaAgent Two-Position Scheduled Limit-Up Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/limit-up` use one no-lookahead first-board strategy with two 50% positions, fixed 10:00-10:15 and 10:30-10:45 entry windows, D+1 14:30 exit, and no one-to-two execution exposure.

**Architecture:** Add a small pure scheduled-policy module for the shared clock and historical signal extraction. Extend the existing cash simulator with an explicit D+1 14:30 exit mode, then build one cached scheduled portfolio report from the complete first-board candidate pool rather than the end-of-day selected Top4. Keep one-to-two data and rules internally, but exclude it from product execution and expose a fixed ablation audit proving the decision.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy/PostgreSQL, pytest, React 19, TypeScript, TanStack Query, Vitest.

---

### Task 1: Freeze the scheduled policy in pure code

**Files:**
- Create: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Test: `tests/alphaagent/test_limit_up_scheduled_execution.py`

- [x] **Step 1: Write failing clock and signal-selection tests**

Cover the left-closed/right-open entry boundaries, five-minute reminders, two positions, and extraction from `lane_portfolio.candidate_pool.first_board`. The test must add a contradictory `lane_portfolio.selected` item and prove it cannot affect selected scheduled signals.

```python
def test_scheduled_entry_window_boundaries() -> None:
    assert scheduled_execution.is_entry_time("10:00:00") is True
    assert scheduled_execution.is_entry_time("10:14:59") is True
    assert scheduled_execution.is_entry_time("10:15:00") is False
    assert scheduled_execution.is_entry_time("10:30:00") is True
    assert scheduled_execution.is_entry_time("10:44:59") is True
    assert scheduled_execution.is_entry_time("10:45:00") is False


def test_scheduled_orders_ignore_end_of_day_selected_top_four() -> None:
    rows = [history_day(candidate_pool=[eligible("600001.SSE", "10:05:00")], selected=[future_winner()])]
    orders = scheduled_execution.extract_scheduled_orders(rows)
    assert [row["vt_symbol"] for row in orders] == ["600001.SSE"]
```

- [x] **Step 2: Run tests and verify they fail**

Run: `uv run pytest tests/alphaagent/test_limit_up_scheduled_execution.py -q`

Expected: collection fails because `scheduled_execution` does not exist.

- [x] **Step 3: Implement the policy constants and pure helpers**

Implement:

```python
SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v1"
MAX_POSITIONS = 2
TARGET_POSITION_PCT = 50.0
EXIT_TIME = "14:30:00"
ENTRY_WINDOWS = (("10:00:00", "10:15:00"), ("10:30:00", "10:45:00"))
VALIDATION_START = date(2026, 4, 14)
```

`extract_scheduled_orders()` must only accept `decision == "eligible"`, `lane == "first_board"`, an allowed `buy_time`, and one earliest event per date/symbol. Sort by entry date, signal time, rank score, pool rank, then symbol. It must never read `lane_portfolio.selected`, final seal state, close, or D+1 return.

- [x] **Step 4: Run the pure policy tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_scheduled_execution.py -q`

Expected: all policy tests pass.

### Task 2: Add explicit D+1 14:30 cash execution

**Files:**
- Modify: `alphaagent/server/services/limit_up/cash_backtest.py`
- Modify: `alphaagent/server/services/limit_up/history_repository.py`
- Test: `tests/alphaagent/test_limit_up_cash_backtest.py`
- Test: `tests/alphaagent/test_limit_up_scheduled_execution.py`

- [x] **Step 1: Write failing 14:30 execution tests**

Prove that an entry on D exits on D+1 at `14:30:00`, that morning D+1 buys cannot reuse the later sale cash, that missing 14:30 data remains explicitly identified, and that price source is retained as either `minute_1430` or `daily_close_proxy`.

```python
result = simulate_limit_up_account(
    signals,
    bars_with_price_1430,
    trade_dates,
    "next_1430",
    CashBacktestConfig(max_positions=2),
)
assert result["executed_trades"][0]["sell_time"] == "14:30:00"
assert result["executed_trades"][0]["exit_price_source"] == "minute_1430"
```

- [x] **Step 2: Run focused tests and verify failure**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_scheduled_execution.py -q`

Expected: `next_1430` is rejected or the new fields are absent.

- [x] **Step 3: Extend the simulator and add a batched minute-price loader**

Add `next_1430` to supported exits. On the planned result date use `price_1430`, record `14:30:00`, `exit_price_source`, and do not release cash before the exit fill. Add one repository query that loads the exact 14:30 one-minute close for all requested symbol/result-date pairs; do not issue one query per stock.

- [x] **Step 4: Run focused tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_scheduled_execution.py -q`

Expected: all focused tests pass.

### Task 3: Build the scheduled two-position report and one-to-two ablation

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/api/limit_up.py`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `tests/alphaagent/test_api.py`

- [x] **Step 1: Write failing report-contract tests**

Assert that portfolio backtest mode is `scheduled_first_board_cash_replay`, account config is two positions, entry windows and 14:30 exit are returned, candidate source is `complete_first_board_candidate_pool`, and one-to-two is excluded. Assert the report includes exact/proxy exit coverage, double-cost stress, adverse-fill stress, design/time-validation summaries, and the one-to-two include/exclude account comparison.

- [x] **Step 2: Run report tests and verify failure**

Run: `uv run pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_api.py -q -k 'scheduled or portfolio_backtest or one_to_two'`

Expected: old dynamic four-position report fails the new contract.

- [x] **Step 3: Implement and cache the scheduled report**

For `lane=portfolio`, load full replay payloads, extract chronological first-board events, join exact D+1 14:30 prices in one query, and use an explicitly labelled daily close proxy only where historical minute data is missing. Run:

```python
CashBacktestConfig(initial_cash=100_000, max_positions=2)
CashBacktestConfig(initial_cash=100_000, max_positions=2, commission_rate=0.0006,
                   minimum_commission=10, stamp_tax_rate=0.001,
                   transfer_fee_rate=0.00002, slippage_bps=20)
```

The one-to-two audit must use the same 100,000 yuan/two-position account for independent, included, and excluded comparisons. It is diagnostic only and must not alter scheduled selection.

- [x] **Step 4: Run report/API tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_api.py -q -k 'scheduled or portfolio_backtest or one_to_two'`

Expected: focused report and API tests pass.

### Task 4: Apply the shared clock to realtime recommendations

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `tests/alphaagent/test_limit_up_live.py`

- [x] **Step 1: Write failing realtime schedule tests**

Prove that only first-board candidates can enter the product portfolio, at most two are returned, a candidate becomes `trigger_ready` only inside an entry window with age no greater than 20 seconds, and the same candidate is observation-only outside the windows. Verify the response includes the five-minute reminder and fixed D+1 14:30 sell instruction.

- [x] **Step 2: Run focused live tests and verify failure**

Run: `uv run pytest tests/alphaagent/test_limit_up_live.py -q -k 'scheduled or portfolio'`

Expected: old multi-lane/four-position portfolio behavior fails.

- [x] **Step 3: Build the scheduled live portfolio after research evaluation**

Preserve lane research fields and `research_only` permission, but do not let the legacy lane-validation veto hide a time-window trigger. Return `execution_schedule` from the same pure clock helper. A trigger can later disappear from the current ranking, but the existing two-day trace must retain its recorded `trigger_ready` event.

- [x] **Step 4: Run live and trace tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_live_trace.py -q`

Expected: realtime schedule and immutable trace tests pass.

### Task 5: Simplify `/limit-up` to the one product strategy

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Write failing frontend tests**

Assert portfolio display is capped at two first-board signals and never renders one-to-two. Extend API types for `scheduled_1430`, schedule metadata, stress summaries, proxy coverage, and the one-to-two removal audit.

- [x] **Step 2: Run frontend tests and verify failure**

Run: `pnpm --dir frontend test -- --run frontend/src/features/limitUp/livePortfolio.spec.ts`

Expected: old four-item/multi-lane behavior fails.

- [x] **Step 3: Remove user-facing lane/scope selectors and render the fixed rule**

Keep the three primary views: realtime, historical ledger, and backtest. Show one compact schedule line, `10万元 / 两仓各50% / D+1 14:30`, exact/proxy price coverage, and double-cost result. Keep the one-to-two audit in the backend research response, but do not render its negative-control metrics in the product UI. Do not add strategy controls.

- [x] **Step 4: Run frontend tests and build**

Run: `pnpm --dir frontend test -- --run`

Run: `pnpm --dir frontend build`

Expected: tests and production build pass.

### Task 6: Re-run evidence, update durable memory, and verify the page

**Files:**
- Modify: `requirements/alphaagent_limit_up_scheduled_execution_design.md`
- Modify: `memory/06_backtests/limit_up_scheduled_execution_feasibility.md`
- Modify: `memory/06_backtests/README.md`

- [x] **Step 1: Run the database-backed report on all available history**

Rebuild/restart the local API if required, then call the product portfolio report and save only summarized evidence. Record sample dates, signals, trades, win rate, final equity, compound return, maximum drawdown, profit factor, double-cost result, exact 14:30 count, close-proxy count, and adverse-fill result.

- [x] **Step 2: Update the approved design and evidence in place**

Replace every four-position reference with two positions at 50% each. State that one-to-two remains in internal raw research but is removed from execution because independent expanding-OOS, locked-holdout, and account ablation are negative.

- [x] **Step 3: Run backend regression tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_live_trace.py tests/alphaagent/test_api.py -q`

Expected: all selected backend tests pass.

- [x] **Step 4: Check formatting and rendered product**

Run: `git diff --check`

Rebuild affected Compose services and verify `http://localhost:8080/limit-up` at desktop and mobile widths. Confirm there is one strategy, two-position wording, schedule guidance, no one-to-two execution selector, and backtest values match the API.
