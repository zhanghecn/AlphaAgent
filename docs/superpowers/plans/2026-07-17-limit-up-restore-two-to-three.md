# Limit-up Restore Two-to-three Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore two-to-three signals to the single formal limit-up recommendation and two-position account while retaining the v7 two-window entry and D+1 official-close exit contract.

**Architecture:** Promote the shared scheduled product contract to v8 and the live snapshot contract to v11. Evaluate every relay variant after applying the frozen first-board profitability filter, so the gate measures the exact orders that formal execution would use; configure first-board plus two-to-three as the single product, then consume the same lane set in live recommendations and the existing UI.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/PostgreSQL, React/TypeScript, pytest, Vitest, Docker Compose.

---

Repository policy overrides generic plan templates: preserve the shared dirty worktree and do not commit or push unless the user explicitly asks.

### Task 1: Freeze the v8 shared product scope

**Files:**
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`

- [x] **Step 1: Write failing version and lane assertions**

Require the product to contain exactly first-board and two-to-three while leaving the windows and exit unchanged:

```python
assert scheduled_execution.SCHEDULED_EXECUTION_VERSION == "limit-up-scheduled-v8"
assert scheduled_execution.PRODUCT_EXECUTION_LANES == (
    "first_board",
    "two_to_three",
)
assert scheduled_execution.ENTRY_WINDOWS == (
    ("10:00:00", "11:30:00"),
    ("13:30:00", "14:00:00"),
)
assert scheduled_execution.EXIT_MODE == "next_close"
assert versions.LIVE_STRATEGY_VERSION == "limit-up-live-v11"
```

- [x] **Step 2: Run the focused tests and require failure**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_scheduled_execution.py \
  tests/alphaagent/test_limit_up_history.py -q
```

- [x] **Step 3: Implement the versioned product contract**

Set:

```python
SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v8"
PRODUCT_EXECUTION_LANES = ("first_board", "two_to_three")
LIVE_STRATEGY_VERSION = "limit-up-live-v11"
```

Do not change `ENTRY_WINDOWS`, `EXIT_MODE`, `EXIT_TIME`, first-board thresholds, position count, costs, or high-board scope.

- [x] **Step 4: Run the Task 1 tests and require pass**

Run the Task 1 command.

### Task 2: Make the relay gate evaluate executable orders

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`

- [x] **Step 1: Write failing formal replay assertions**

Extend the existing scheduled portfolio test to require:

```python
assert report["portfolio_policy"]["included_lanes"] == [
    "first_board",
    "two_to_three",
]
assert report["portfolio_policy"]["excluded_lanes"] == ["high_board"]
assert report["profitability_filter"]["audit"]["reason_counts"] == {
    "not_first_board": 1,
    "qualified": 2,
}
assert report["relay_comparison"]["configured_variant"] == (
    "first_board_two_to_three"
)
assert report["relay_comparison"]["configuration_matches_gate"] is True
```

Also add a regression where weak first-board orders make the unfiltered relay drawdown fail but the filtered first-board-plus-two-to-three orders pass; the relay comparison must use the filtered bundle.

- [x] **Step 2: Run the focused history test and require failure**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q \
  -k "portfolio_backtest or profitability or relay"
```

- [x] **Step 3: Filter each replay variant before its gate**

Build `qualified_variant_orders` from every evidence-attached variant:

```python
qualified_variant_orders = {
    name: scheduled_execution.filter_profitability_qualified_orders(orders)[0]
    for name, orders in variant_orders.items()
}
variant_bundles = {
    name: _scheduled_variant_bundle(
        qualified_variant_orders[name],
        bars,
        trade_dates,
        config,
        double_cost_config,
    )
    for name in variant_orders
}
```

Keep the selected variant's unfiltered bundle as a separate profitability comparison. Define `configuration_matches_gate` from the configured variant's own `gate.passed` value; keep `gate_selected_variant` only as the highest-return passing research comparison. Do not dynamically replace the configured product.

- [x] **Step 4: Run lane, cash, history, and schedule tests**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_lanes.py \
  tests/alphaagent/test_limit_up_cash_backtest.py \
  tests/alphaagent/test_limit_up_history.py \
  tests/alphaagent/test_limit_up_scheduled_execution.py -q
```

### Task 3: Restore two-to-three in live recommendations and UI

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Write failing live and UI assertions**

Require the shared two-position live portfolio to prefer a ready two-to-three signal and then the first-board signal when both are selected. Require the unlimited formal recommendation list to retain both lanes while still excluding high-board and one-to-two:

```python
assert [row["board_lane"] for row in portfolio] == [
    "two_to_three",
    "first_board",
]
assert validations["two_to_three"]["status"] == "portfolio_gate_passed"
```

```typescript
expect(liveSignalsForScope(snapshot({ portfolio }), "portfolio").map(
  (row) => row.vt_symbol,
)).toEqual(["600010.SSE", "600011.SSE"]);
```

- [x] **Step 2: Run focused live and frontend tests and require failure**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q
pnpm --dir frontend test -- --run frontend/src/features/limitUp/livePortfolio.spec.ts
```

- [x] **Step 3: Consume the shared two-lane product**

Add `two_to_three` to the frontend `PORTFOLIO_LANES`; the backend already derives its live product set from `PRODUCT_EXECUTION_LANES`. Change the backtest caption from `综合首板` to `首板 + 二进三`. Keep first-board-specific joint-rate rendering and two-to-three-specific TBOX, historical win-rate, D+1 average, quality tier, and risk rendering unchanged.

- [x] **Step 4: Run live, next-session, and all frontend tests**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_next_session_plan.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
```

### Task 4: Replay, rebuild, and preserve durable evidence

**Files:**
- Create: `memory/06_backtests/limit_up_two_window_next_close_two_to_three_20260717.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/06_backtests/limit_up_two_window_next_close_20260717.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run all regressions and static checks**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
uv run python -m compileall -q \
  alphaagent/server/services/limit_up alphaagent/server/services/data_sync.py
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
git diff --check
```

- [x] **Step 2: Rebuild local services**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps alphaagent-api alphaagent-web
```

- [x] **Step 3: Run the formal v8 API replay**

Call `GET /api/limit-up/history/backtest?lane=portfolio` through the Compose network. Record account and all-recommendation metrics, double-cost stress, close coverage, phase validation, lane counts, `configuration_matches_gate`, and the v8/v11 versions.

- [x] **Step 4: Compare v8 against the frozen v7 first-board result**

Use the frozen v7 values of 65 account trades, 67.6923% win rate, +2.0653% average return, +88.7314% compound return, -6.2464% drawdown, and 2.7918 profit factor. Do not change thresholds after reading v8.

- [x] **Step 5: Update current memory and preserve v7 as historical evidence**

Mark the v7 report as superseded without rewriting its measurements. Make v8 the current index and decision baseline, explicitly state that high-board remains research-only, then verify API health, zero running sync jobs, and `git diff --check`.
