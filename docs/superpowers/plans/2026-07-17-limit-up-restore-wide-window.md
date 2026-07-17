# Limit-up Restore Wide Afternoon Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the single formal first-board-plus-two-to-three product buy during 10:00-11:30 and 13:00-14:30, then sell at the official D+1 close.

**Architecture:** Promote the scheduled contract to v9 and live snapshots to v12 so cached narrow-window results cannot mix with the restored wide window. Change only the shared clock and its live/plan consumers; retain the v8 filtered relay gate, formal lanes, two-position cash account, first-board profitability filter, official-close exit, fees, and risk thresholds.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy/PostgreSQL, React/TypeScript, pytest, Vitest, Docker Compose.

---

Repository policy overrides generic plan templates: preserve the shared dirty worktree and do not commit or push unless the user explicitly asks.

### Task 1: Freeze the v9 wide-window clock

**Files:**
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`

- [x] **Step 1: Write failing contract and clock assertions**

```python
assert scheduled_execution.SCHEDULED_EXECUTION_VERSION == "limit-up-scheduled-v9"
assert scheduled_execution.PRODUCT_EXECUTION_LANES == (
    "first_board",
    "two_to_three",
)
assert scheduled_execution.ENTRY_WINDOWS == (
    ("10:00:00", "11:30:00"),
    ("13:00:00", "14:30:00"),
)
assert scheduled_execution.is_entry_time("13:15:00") is True
assert scheduled_execution.is_entry_time("14:29:59") is True
assert scheduled_execution.is_entry_time("14:30:00") is False
assert versions.LIVE_STRATEGY_VERSION == "limit-up-live-v12"
```

Also require `execution_clock` to report lunch until 13:00, entry from 13:00 through 14:29:59, waiting for close from 14:30, and the existing 14:55 close reminder.

- [x] **Step 2: Run focused tests and require failure**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_scheduled_execution.py \
  tests/alphaagent/test_limit_up_history.py -q
```

- [x] **Step 3: Implement v9/v12 and the shared clock**

Set:

```python
SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v9"
ENTRY_WINDOWS = (("10:00:00", "11:30:00"), ("13:00:00", "14:30:00"))
LIVE_STRATEGY_VERSION = "limit-up-live-v12"
```

In `execution_clock`, end lunch at 13:00, allow entries until 14:30, wait for the close from 14:30 to 14:55, and keep the D+1 official-close reminder and 15:00 exit unchanged.

- [x] **Step 4: Run Task 1 tests and require pass**

Run the Task 1 command.

### Task 2: Align live recommendations and next-session plans

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `tests/alphaagent/test_limit_up_next_session_plan.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/next_session_plan.py`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Write failing live and plan assertions**

```python
assert signal["buy_instruction"] == (
    "仅在10:00-11:30或13:00-14:30满足全部条件时买入"
)
assert next_plan["valid_until"] == "下一交易日14:30"
```

Require a 13:15 fresh actionable signal to remain `buy_now`, a 14:29 signal to remain actionable, and a 14:30 signal to be observation-only.

- [x] **Step 2: Run focused tests and require failure**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_next_session_plan.py -q
```

- [x] **Step 3: Use the shared wide-window instruction everywhere**

Replace the live and next-session buy instruction with:

```python
"仅在10:00-11:30或13:00-14:30满足全部条件时买入"
```

Set next-session validity to `下一交易日14:30`. Change the UI lunch text to say 13:00 resumes evaluation. Do not change the formal lanes, ordering, D+1 sell instruction, first-board joint-rate display, or two-to-three evidence display.

- [x] **Step 4: Run live, plan, and frontend verification**

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_next_session_plan.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
```

### Task 3: Replay, deploy, and preserve evidence

**Files:**
- Create: `memory/06_backtests/limit_up_wide_window_next_close_two_to_three_20260717.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/06_backtests/limit_up_two_window_next_close_two_to_three_20260717.md`
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

- [x] **Step 3: Run the formal v9 API replay**

Call `GET /api/limit-up/history/backtest?lane=portfolio` through the Compose network. Record the account, all-recommendation, double-cost, phase, lane, timing, close-coverage, gate, and validation results.

- [x] **Step 4: Compare v9 against frozen v8 without retuning**

Use the v8 narrow-window values of 75 trades, 69.3333% win rate, +2.4943% average return, +141.2920% compound return, -7.4457% drawdown, and 3.0150 profit factor. Keep the wide window because the user prioritizes higher account compound return and the ordinary/double-cost drawdowns remain above the -10% floor; do not change any other rule after reading v9.

- [x] **Step 5: Update current memory and verify idle runtime**

Mark the v8 report as superseded without rewriting its measurements. Make v9 the current index and decision baseline, record that the wider window trades lower per-trade average and profit factor for higher win rate and compound return, then verify API health, zero running sync jobs, and `git diff --check`.
