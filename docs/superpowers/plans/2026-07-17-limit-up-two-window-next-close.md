# Limit-up Two-window Next-close Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the single formal limit-up product buy only during 10:00-11:30 and 13:30-14:00, then sell every filled position at the official D+1 close.

**Architecture:** Keep the existing point-in-time candidate generation, profitability ranking, two-position cash account, fees, slippage, and risk gates. Change the shared scheduled execution contract and all formal live/backtest consumers to `next_close`; keep old 14:30 helpers only for explicitly requested historical research, and remove their backfill job from the default nightly product chain.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/PostgreSQL, React/TypeScript, pytest, Vitest, Docker Compose.

---

Repository policy forbids commits unless the user explicitly requests one. Work in the shared tree, preserve unrelated changes, and do not commit or push.

### Task 1: Freeze the shared time contract

**Files:**
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`

- [x] **Step 1: Write failing schedule tests**

Require the version, mode, exit time, entry windows, and clock states to match the new contract:

```python
assert scheduled_execution.SCHEDULED_EXECUTION_VERSION == "limit-up-scheduled-v7"
assert scheduled_execution.EXIT_MODE == "next_close"
assert scheduled_execution.EXIT_TIME == "15:00:00"
assert scheduled_execution.ENTRY_WINDOWS == (
    ("10:00:00", "11:30:00"),
    ("13:30:00", "14:00:00"),
)
assert scheduled_execution.is_entry_time("13:15:00") is False
assert scheduled_execution.is_entry_time("13:30:00") is True
assert scheduled_execution.is_entry_time("14:00:00") is False
```

- [x] **Step 2: Run the focused tests and require failure**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_scheduled_execution.py -q
```

- [x] **Step 3: Implement the shared clock**

Set `ENTRY_WINDOWS` to the two frozen windows, add `EXIT_MODE = "next_close"`, set `EXIT_TIME = "15:00:00"`, and change the clock so 11:30-13:30 is a pause, 14:00-14:55 is waiting for close, 14:55-15:00 is the close-exit reminder, and no buy is allowed after 14:00.

- [x] **Step 4: Run the focused tests and require pass**

Run the Task 1 command.

### Task 2: Use D+1 close in the formal cash replay

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`

- [x] **Step 1: Write failing formal-account tests**

The portfolio report must ignore its generic query `exit_mode`, use the shared formal contract, and not call the 14:30 repository:

```python
assert report["exit_mode"] == "next_close"
assert report["execution_schedule"]["entry_windows"] == [
    "10:00-11:30",
    "13:30-14:00",
]
assert report["execution_schedule"]["exit_time"] == "15:00"
assert report["coverage"]["daily_close_count"] == 2
assert report["coverage"]["daily_close_missing_count"] == 0
assert report["exit_summary"]["mode"] == "next_close"
```

- [x] **Step 2: Run the formal-account test and require failure**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q -k "portfolio_backtest or scheduled_backtest"
```

- [x] **Step 3: Switch every formal calculation to the shared exit mode**

Use `scheduled_execution.EXIT_MODE` in the selected variant, phase summaries, double-cost stress, independent recommendation quality, and position-size audit. Do not attach 14:30 prices in `_build_scheduled_history_backtest`. Add close coverage based on an order's `result_date` and a positive `close_price`; missing close rows remain excluded from formal statistics rather than using another price.

- [x] **Step 4: Make the report contract explicit**

Return `exit_mode="next_close"`, `exit_rule="D+1 official close"`, a close-price exit summary, and a limitation stating that the official daily close is an explicit closing-auction fill assumption with configured slippage, not a 14:30 fallback.

- [x] **Step 5: Run lane, cash, history, and scheduled tests**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_scheduled_execution.py -q
```

### Task 3: Align live recommendations and plans

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `tests/alphaagent/test_limit_up_next_session_plan.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `alphaagent/server/services/limit_up/next_session_plan.py`

- [x] **Step 1: Write failing live-contract assertions**

```python
assert signal["buy_instruction"] == (
    "仅在10:00-11:30或13:30-14:00满足全部条件时买入"
)
assert signal["sell_instruction"] == "D+1尾盘按官方收盘价统一卖出"
assert next_plan["valid_until"] == "下一交易日14:00"
```

Also require a 13:15 snapshot to produce no actionable portfolio and a 13:35 snapshot to allow an otherwise valid signal.

- [x] **Step 2: Run live tests and require failure**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_next_session_plan.py -q
```

- [x] **Step 3: Implement one public buy/sell instruction**

Use the two shared entry windows in `live_service`; make `live_policy` return the same D+1 official-close sell condition for every board lane; make tail-only states observation-only; and end intraday buy validity at 14:00. Update the next-session plan to the same instruction and validity boundary.

- [x] **Step 4: Run live tests and require pass**

Run the Task 3 command.

### Task 4: Remove obsolete product backfill and update the existing UI

**Files:**
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/nextSessionPlan.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Write failing schedule and UI assertions**

Require `sync_limit_up_exit_minutes` to remain a manual registered research job but not appear in `eod_finalize_2130` or the recommended product profile. Update existing page tests or source assertions to require `D+1收盘` and `官方收盘价`, not `D+1 14:30`.

- [x] **Step 2: Run focused tests and require failure**

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "exit_minutes or default_schedule"
pnpm --dir frontend test -- --run
```

- [x] **Step 3: Remove only the default product dependency**

Keep the job definition and runner for old research, but remove `sync_limit_up_exit_minutes` from `_RECOMMENDED_PRIORITY` and `eod_finalize_2130`.

- [x] **Step 4: Update existing UI text and types**

Add optional `daily_close_count` and `daily_close_missing_count` coverage fields. Show the two entry windows, `D+1 15:00` exit, and `官方收盘价`; do not add new cards, panels, colors, or layout.

- [x] **Step 5: Run backend and frontend tests**

Run the Task 4 commands and `pnpm --dir frontend run build`.

### Task 5: Real replay, deployment, and durable evidence

**Files:**
- Create: `memory/06_backtests/limit_up_two_window_next_close_20260717.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run all regressions and static checks**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
uv run python -m compileall -q alphaagent/server/services/limit_up alphaagent/server/services/data_sync.py
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
git diff --check
```

- [x] **Step 2: Rebuild and verify the API**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps alphaagent-api alphaagent-web
```

- [x] **Step 3: Run the formal API replay**

Call `GET /api/limit-up/history/backtest?lane=portfolio` through the Compose service network. Record account trades, win rate, average return, compound return, drawdown, profit factor, all-recommendation quality, morning/afternoon signal counts, close coverage, validation phases, and strategy version.

- [x] **Step 4: Compare against v6 without retuning**

Use the frozen v6 strict baseline of 58 account trades, 63.7931% win rate, +66.9032% compound return, -5.7239% drawdown, and 2.7224 profit factor. Attribute changes separately to the new afternoon window and the new exit rule; do not change ranking thresholds after seeing results.

- [x] **Step 5: Update memory and verify idle runtime**

Replace current-product 14:30 descriptions with v7 close-exit facts, link the detailed report, and verify API health plus zero `running` sync jobs. Preserve the v6 report as historical evidence rather than rewriting its measured result.
