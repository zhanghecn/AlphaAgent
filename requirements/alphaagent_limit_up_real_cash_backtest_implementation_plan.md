# AlphaAgent Limit-Up Real Cash Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `/limit-up` signal-average compound curve with an auditable 100,000 CNY shared-cash account whose returns and win rate come only from executable trades.

**Architecture:** Add a focused limit-up cash simulator that consumes point-in-time selected candidates plus daily prices, while reusing the repository and generic trade-ledger boundaries already present in AlphaAgent. Keep the old equal-weight calculation only as `signal_summary`; expose the real shared portfolio as the default API and UI result, with per-lane isolated accounts retained for research.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy, pytest, React, TypeScript, TanStack Query, Recharts, Docker Compose.

---

## File Map

- Create `alphaagent/server/services/limit_up/cash_backtest.py`: account configuration, positions, chronological matching, daily mark-to-market, execution summaries.
- Modify `alphaagent/server/services/backtest/ledger.py`: optional minimum commission, transfer fee, and legal price bounds while preserving all existing callers.
- Modify `alphaagent/server/services/limit_up/history_repository.py`: load selected-symbol daily prices for mark-to-market and locked-exit retries.
- Modify `alphaagent/server/services/limit_up/history_service.py`: build portfolio/per-lane cash reports, preserve signal upper bound, and validate on executed trades.
- Modify `alphaagent/server/api/limit_up.py`: accept `lane=portfolio`.
- Modify `frontend/src/api/limitUp.ts`: define real-account response types and portfolio scope.
- Modify `frontend/src/pages/LimitUpPage.tsx`: default backtest to shared portfolio and render real-account metrics.
- Create `tests/alphaagent/test_limit_up_cash_backtest.py`: deterministic account and matching tests.
- Modify `tests/alphaagent/test_limit_up_lanes.py`: history-service and API integration assertions.
- Modify `memory/06_backtests/README.md`, `memory/09_decisions/decisions.md`: current execution truth.
- Create `memory/06_backtests/limit_up_real_cash_backtest.md`: full-history evidence and old/new comparison.

### Task 1: Extend the shared transaction ledger safely

**Files:**
- Modify: `alphaagent/server/services/backtest/ledger.py`
- Test: `tests/alphaagent/test_limit_up_cash_backtest.py`

- [ ] **Step 1: Write failing fee and price-bound tests**

```python
def test_buy_execution_applies_minimum_commission_transfer_fee_and_limit_cap() -> None:
    fill = ledger.calculate_buy_execution(
        raw_price=10.0,
        cash=10_000,
        target_cash=5_000,
        commission_rate=0.0003,
        slippage_bps=10,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        max_price=10.0,
    )
    assert fill.price == 10.0
    assert fill.volume == 500
    assert fill.fee == pytest.approx(5.05)
    assert fill.cash_after == pytest.approx(4_994.95)


def test_sell_execution_applies_minimum_commission_transfer_fee_and_floor() -> None:
    fill = ledger.calculate_sell_execution(
        raw_price=9.01,
        volume=500,
        cost_price=10.0,
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        min_price=9.0,
    )
    assert fill.price == 9.00099
    assert fill.fee == pytest.approx(7.29525245)
```

- [ ] **Step 2: Run the focused tests and verify they fail on unknown keyword arguments**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py -q`

Expected: FAIL because the new optional ledger arguments are not implemented.

- [ ] **Step 3: Implement backward-compatible fee and bound arguments**

Add defaulted arguments to both ledger functions so existing callers retain the current behavior:

```python
def calculate_buy_execution(
    *,
    raw_price: float,
    cash: float,
    target_cash: float,
    commission_rate: float,
    slippage_bps: float,
    lot_size: int = 100,
    minimum_commission: float = 0.0,
    transfer_fee_rate: float = 0.0,
    max_price: float | None = None,
) -> BuyExecution:
    price = float(raw_price) * (1 + slippage_bps / 10000)
    if max_price is not None:
        price = min(price, float(max_price))
    budget = min(float(cash), float(target_cash))
    volume = _round_lot(budget / price, lot_size)
    while volume > 0:
        amount = price * volume
        fee = max(amount * commission_rate, minimum_commission) + amount * transfer_fee_rate
        if amount + fee <= cash:
            return BuyExecution(price, volume, amount, fee, -(amount + fee), cash - amount - fee)
        volume -= lot_size
    return BuyExecution(price, 0, 0.0, 0.0, 0.0, cash)
```

Apply the corresponding `minimum_commission`, `transfer_fee_rate`, and `min_price` logic to sell execution. Validate all monetary inputs and price bounds are non-negative.

- [ ] **Step 4: Run existing and new ledger tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_quant_backtest_portfolio.py -q`

Expected: all tests pass; existing ledger results remain unchanged because new defaults are zero/None.

- [ ] **Step 5: Commit only Task 1 files**

```bash
git add alphaagent/server/services/backtest/ledger.py tests/alphaagent/test_limit_up_cash_backtest.py
git commit -m "feat(limit-up): support realistic A-share transaction costs"
```

### Task 2: Implement chronological cash-account matching

**Files:**
- Create: `alphaagent/server/services/limit_up/cash_backtest.py`
- Modify: `tests/alphaagent/test_limit_up_cash_backtest.py`

- [ ] **Step 1: Add failing account invariants and overlap tests**

Build small candidate/bar fixtures and assert:

```python
def test_next_close_position_cash_cannot_fund_next_morning_buy() -> None:
    result = simulate_limit_up_account(
        signals=[first_signal, next_day_signal],
        bars=bars,
        trade_dates=dates,
        exit_mode="next_close",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=1),
    )
    assert result["execution_summary"]["buy_count"] == 1
    assert result["skipped_orders"][0]["reason"] == "position_limit"
    assert min(row["cash"] for row in result["equity_curve"]) >= 0


def test_open_sale_cash_funds_later_first_board_but_not_same_auction() -> None:
    result = simulate_limit_up_account(
        signals=[old_position_signal, auction_new_signal, intraday_new_signal],
        bars=bars,
        trade_dates=dates,
        exit_mode="next_open",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=1),
    )
    assert status_for(result, "auction-new") == "skipped_insufficient_cash"
    assert status_for(result, "intraday-new") == "filled"


def test_execution_summary_uses_only_closed_real_trades() -> None:
    result = simulate_limit_up_account(
        signals=[winning_signal, losing_signal, still_open_signal],
        bars=bars,
        trade_dates=dates,
        exit_mode="next_close",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=4),
    )
    assert result["execution_summary"]["trade_count"] == len(result["executed_trades"])
    assert result["execution_summary"]["win_rate"] == 50.0
    assert result["execution_summary"]["total_return_pct"] == pytest.approx(
        (result["execution_summary"]["final_equity"] / 100_000 - 1) * 100
    )
```

Also cover 100-share lots, duplicate symbols, T+1, first-board price cap, fee-inclusive PnL, and stable future-free ordering.

- [ ] **Step 2: Run the account test module and verify import failure**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py -q`

Expected: FAIL because `cash_backtest.py` does not exist.

- [ ] **Step 3: Add focused account data structures**

Define:

```python
@dataclass(frozen=True)
class CashBacktestConfig:
    initial_cash: float = 100_000.0
    max_positions: int = 4
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps: float = 10.0
    lot_size: int = 100


@dataclass
class CashPosition:
    position_id: str
    candidate: dict[str, object]
    volume: int
    entry_date: date
    planned_exit_date: date
    buy_price: float
    buy_amount: float
    buy_fee: float
    cash_cost: float
    last_close: float
    pending_exit: bool = False
```

Expose `simulate_limit_up_account(signals, bars, trade_dates, exit_mode, config)` and return JSON-safe mappings only.

- [ ] **Step 4: Implement time-ordered matching**

For each date:

```python
day_budget = previous_close_equity / config.max_positions
process_auction_entries(day_budget)
process_open_exits()
process_intraday_entries(day_budget)
process_close_exits_and_emergency_retries()
mark_positions_to_close()
append_equity_row()
```

Use only `two_to_three_quality_tier`, `rank_score`, lane rank, buy time, and symbol for order priority. Never read `outcome.*return_pct` while deciding fills.

The equity row must contain `result_date`, `cash`, `market_value`, `total_equity`, `position_count`, `utilization_pct`, `daily_return_pct`, `equity`, `total_return_pct`, and `drawdown_pct`.

- [ ] **Step 5: Implement conservative locked-limit exits**

Calculate the main-board lower limit from the position's previous reliable close. If planned open equals the lower limit, defer; if that day's close is above the lower limit, sell at close, otherwise retain. On following days retry the open and then close using the same rule. Open positions remain marked to the latest close and do not enter win-rate denominators.

- [ ] **Step 6: Run deterministic account tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py -q`

Expected: all account invariants pass and hand-calculated final equity matches exactly.

- [ ] **Step 7: Commit Task 2**

```bash
git add alphaagent/server/services/limit_up/cash_backtest.py tests/alphaagent/test_limit_up_cash_backtest.py
git commit -m "feat(limit-up): add chronological cash account simulator"
```

### Task 3: Connect reliable daily prices and history reports

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_repository.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [ ] **Step 1: Write failing repository and service integration tests**

Add assertions that `load_account_daily_bars()` selects only requested symbols and dates. For the service, monkeypatch history rows and bars and assert:

```python
report = history_service.get_lane_history_backtest(
    None,
    None,
    lane="portfolio",
    exit_mode="next_close",
)
assert report["account_config"]["initial_cash"] == 100_000
assert report["account_config"]["max_positions"] == 4
assert report["summary"] == report["execution_summary"]
assert report["summary"]["total_return_pct"] == report["daily_results"][-1]["total_return_pct"]
assert report["signal_summary"]["total_return_pct"] != report["summary"]["total_return_pct"]
```

Add a regression fixture with a D+1 close exit and a same-day morning entry to prove the second order cannot reuse sale proceeds.

- [ ] **Step 2: Run focused history tests and confirm failure**

Run: `uv run pytest tests/alphaagent/test_limit_up_lanes.py -q`

Expected: FAIL because `portfolio` and account summaries are unsupported.

- [ ] **Step 3: Add a selected-symbol daily-price loader**

Implement:

```python
def load_account_daily_bars(
    vt_symbols: Sequence[str],
    start: date,
    end: date,
) -> list[dict[str, object]]:
    if not vt_symbols or start > end:
        return []
    statement = (
        select(
            schema.stock_daily_bars.c.vt_symbol,
            schema.stock_daily_bars.c.trade_date,
            schema.stock_daily_bars.c.open_price,
            schema.stock_daily_bars.c.high_price,
            schema.stock_daily_bars.c.low_price,
            schema.stock_daily_bars.c.close_price,
        )
        .where(
            schema.stock_daily_bars.c.vt_symbol.in_(sorted(set(vt_symbols))),
            schema.stock_daily_bars.c.trade_date.between(start, end),
        )
        .order_by(schema.stock_daily_bars.c.trade_date, schema.stock_daily_bars.c.vt_symbol)
    )
```

Return ISO dates and numeric prices. Reuse persisted history dates as the reliable trading calendar.

- [ ] **Step 4: Split signal upper-bound and account execution summaries**

Rename the existing `_daily_equity()` to `_signal_daily_equity()` and use it only for `signal_summary`, factor research, and explicitly named research fields. Add `_cash_report_for_orders()` to call the new simulator for the requested portfolio/lane and phase.

For `lane="portfolio"`, collect all daily `lane_portfolio.selected` candidates. For a board lane, filter that same selected list. Do not read the wider displayed or candidate pools.

- [ ] **Step 5: Make validation use real closed trades and real account curves**

Build warmup, expanding OOS, locked holdout, and post-freeze subaccounts independently at 100,000 CNY. Feed executed trade count, executed win rate, account total return, and account max drawdown into `_validation_check()`. Keep the current 30-trade frozen-forward requirement and `research_only` state.

- [ ] **Step 6: Run limit-up backend tests**

Run: `uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py -q`

Expected: all pass; old generic entry-mode tests continue to use signal research semantics while lane/portfolio reports use cash semantics.

- [ ] **Step 7: Commit Task 3**

```bash
git add alphaagent/server/services/limit_up/history_repository.py alphaagent/server/services/limit_up/history_service.py tests/alphaagent/test_limit_up_lanes.py
git commit -m "fix(limit-up): report returns from shared cash execution"
```

### Task 4: Expose the shared portfolio in the product

**Files:**
- Modify: `alphaagent/server/api/limit_up.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [ ] **Step 1: Add a failing API test for `lane=portfolio`**

```python
response = TestClient(create_app()).get(
    "/api/limit-up/history/backtest",
    params={"lane": "portfolio", "exit_mode": "next_close"},
)
assert response.status_code == 200
assert response.json()["data"]["lane"] == "portfolio"
assert response.json()["data"]["account_config"]["initial_cash"] == 100_000
```

- [ ] **Step 2: Extend the FastAPI literal and run the API test**

Accept `Literal["portfolio", "first_board", "one_to_two", "two_to_three", "high_board"]` for backtests only. Ledger and model endpoints remain board-lane-only.

Run: `uv run pytest tests/alphaagent/test_limit_up_lanes.py -q`

Expected: PASS.

- [ ] **Step 3: Define frontend account types**

Add `BacktestScope = "portfolio" | BoardLaneKey` and extend summary/daily/trade types with:

```typescript
initial_cash: number;
final_equity: number;
buy_count: number;
open_position_count: number;
skipped_count: number;
average_utilization_pct: number;
peak_utilization_pct: number;
total_fees: number;
```

Add `signal_summary`, `skipped_orders`, `open_positions`, and execution metadata to `LimitUpLaneBacktest`.

- [ ] **Step 4: Make the backtest default to portfolio without changing live/ledger lanes**

Keep `lane` for live and historical ledgers. Add a separate `backtestScope` initialized to `"portfolio"`. When `view === "backtest"`, render a five-option scope selector beginning with “组合”; otherwise render the four existing lane tabs.

Disable the lane-specific model query for `portfolio`, because it has no single model lane. Replace that strip with the account assumptions “10 万元 · 最多 4 仓 · 100 股整数手 · 含费用滑点”.

- [ ] **Step 5: Replace misleading main metrics**

Render six compact main cells:

1. 期末权益
2. 实盘复利
3. 成交胜率
4. 最大回撤
5. 平均仓位
6. 跳过信号

Add a secondary signal strip showing signal count, signal win rate, average D+1 return, and “信号日等权上界”. Update the equity chart to use only the real account curve. Extend trade rows with quantity, fees, and net PnL; show skipped reasons in a compact table only when present.

- [ ] **Step 6: Build the frontend and fix all type/layout errors**

Run: `pnpm --dir frontend run build`

Expected: TypeScript compilation and Vite build succeed.

- [ ] **Step 7: Commit Task 4**

```bash
git add alphaagent/server/api/limit_up.py frontend/src/api/limitUp.ts frontend/src/pages/LimitUpPage.tsx tests/alphaagent/test_limit_up_lanes.py
git commit -m "fix(limit-up): show real account returns in backtest"
```

### Task 5: Run full history, compare sizing, and record evidence

**Files:**
- Create: `memory/06_backtests/limit_up_real_cash_backtest.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: Run the complete relevant test suite**

Run:

```bash
uv run pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_walk_forward_model.py -q
uv run python -m compileall alphaagent/server/api/limit_up.py alphaagent/server/services/limit_up alphaagent/server/services/backtest/ledger.py
pnpm --dir frontend run build
```

Expected: all commands exit zero.

- [ ] **Step 2: Run full-history 100,000 CNY reports**

Inside the API container, loop over scopes `("portfolio", "first_board", "one_to_two", "two_to_three", "high_board")` and exit modes `("next_open", "next_close")`, calling `get_lane_history_backtest(None, None, lane=scope, exit_mode=exit_mode)`. Save only summarized evidence: date range, signals, buys, closed trades, skipped orders, open positions, final equity, real return, executed win rate, drawdown, utilization, fees, and signal upper bound.

- [ ] **Step 3: Audit 2/4/6/8 positions without tuning on holdout**

Use warmup plus expanding OOS to compare max positions 2, 4, 6, and 8. Keep 4 as product default unless another value improves real return, executed win rate, and drawdown robustness across multiple periods. Report locked holdout only after the selection is frozen; do not change parameters based on holdout.

- [ ] **Step 4: Write the evidence report and update durable memory**

The report must state the old 499.1836% result was a signal upper bound, list the corrected 100,000 CNY result, and explain differences from cash overlap, position sizing, fees, lots, skips, and locked exits. Update overview memory in place instead of adding chronological duplicates.

- [ ] **Step 5: Commit evidence only**

```bash
git add memory/06_backtests/limit_up_real_cash_backtest.md memory/06_backtests/README.md memory/09_decisions/decisions.md
git commit -m "docs(limit-up): record real cash replay evidence"
```

### Task 6: Deploy and verify the visible product

**Files:**
- No planned source changes; fixes discovered by verification stay scoped to Task 1-4 files.

- [ ] **Step 1: Rebuild the API and web services**

Run: `docker compose up -d --build alphaagent-api alphaagent-web`

Expected: both services start and `docker compose ps` reports the API healthy.

- [ ] **Step 2: Verify the internal API payload**

Call the service inside the API container or through an authenticated browser. Confirm portfolio is the default scope, initial cash is 100,000, summary return equals final equity, and the corrected two-to-three result no longer reports 499.1836% as real return.

- [ ] **Step 3: Verify desktop and mobile UI with Playwright**

Open `http://localhost:8080/limit-up`, switch to 回测, and capture desktop and mobile screenshots. Check that:

- “组合” is selected.
- 10 万元/4 仓 assumptions are visible.
- real metrics fit without overlap.
- the signal upper bound is visually secondary.
- trade and skip tables remain readable horizontally.
- the equity chart is nonblank.

- [ ] **Step 4: Run final repository checks**

Run:

```bash
git diff --check
git status --short
git log -8 --oneline
```

Expected: no whitespace errors; unrelated user changes remain untouched; all limit-up implementation and evidence commits are present.

- [ ] **Step 5: Commit any verification-only corrections**

Stage only files changed for this feature and commit with `fix(limit-up): finalize real cash backtest`. Do not push.
