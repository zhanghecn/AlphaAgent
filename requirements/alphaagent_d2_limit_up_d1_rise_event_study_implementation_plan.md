# D-2 Limit-up D-1 Rise Event Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a no-lookahead A-share event study for buying the D-2 limit-up/D-1 positive non-limit pattern at the D-1 close and exiting at the D close.

**Architecture:** Add one isolated quant research module with pure pandas transformations and summaries, plus a database loader and Markdown CLI. Keep it outside the active limit-up UI and existing D+1 research files, then store the real-data evidence under `memory/06_backtests/`.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy, pytest, PostgreSQL.

---

Project rules prohibit unrequested commits, so the commit steps normally required by the planning skill are intentionally omitted.

### Task 1: Lock the event definition with failing tests

**Files:**

- Create: `tests/alphaagent/services/quant/test_d2_limit_up_d1_rise_research.py`

- [x] Add fixtures that build four consecutive market dates for valid and invalid symbols.
- [x] Assert that only a Shanghai/Shenzhen main-board, non-ST symbol with a D-2 closing limit-up and a positive non-limit D-1 is selected.
- [x] Assert exact entry/outcome dates and D open/high/low/close returns.
- [x] Assert that changing only D prices changes labels but not event membership.
- [x] Assert that a stock missing an intervening market date is rejected.
- [x] Assert that `6.05 * 1.10` becomes a `6.66` limit price using half-up rounding.
- [x] Assert that two same-day trades are equal-weighted before daily returns are compounded and that the default `0.31%` cost is deducted.
- [x] Run:

```bash
uv run pytest tests/alphaagent/services/quant/test_d2_limit_up_d1_rise_research.py -q
```

Expected result: collection fails because `d2_limit_up_d1_rise_research` does not exist.

### Task 2: Implement pure event detection and portfolio statistics

**Files:**

- Create: `alphaagent/server/services/quant/d2_limit_up_d1_rise_research.py`
- Test: `tests/alphaagent/services/quant/test_d2_limit_up_d1_rise_research.py`

- [x] Define the public research surface:

```python
DEFAULT_COMMISSION_RATE = 0.0003
DEFAULT_STAMP_TAX_RATE = 0.0005
DEFAULT_SLIPPAGE_BPS = 10.0
DEFAULT_TOTAL_COST_RATE = 0.0031
```

  Public functions are `main_board_limit_price(previous_close)`,
  `build_event_frame(daily_bars, total_cost_rate=DEFAULT_TOTAL_COST_RATE)`, and
  `summarize_event_frame(events)` with the return types specified by their names
  and module annotations.

- [x] Normalize and sort numeric/date columns, filter current main-board non-ST names, and derive per-symbol previous/next bars.
- [x] Build a global trading-day previous/next map and require D-2, D-1, D continuity.
- [x] Calculate each row's exact limit price from the prior close; select `lag1_is_limit_up & D-1 return > 0 & not D-1 limit-up`.
- [x] Label D open/high/low/close gross returns, net close return, D limit-up, and equal-weight market excess return without using D fields in signal selection.
- [x] Summarize trade win rates, average/median returns, path distributions, yearly stability, and best/worst samples.
- [x] Group events by entry date, average same-day returns, build gross/net equity curves, and calculate cumulative return, equity multiple, annualized return, maximum drawdown, signal-day win rate, and position counts.
- [x] Run the target test and require all assertions to pass.

### Task 3: Add reproducible database execution and evidence rendering

**Files:**

- Modify: `alphaagent/server/services/quant/d2_limit_up_d1_rise_research.py`
- Create: `memory/06_backtests/d2_limit_up_d1_rise_event_study.md`

- [x] Add a read-only loader over `stock_daily_bars` joined to `stocks`, with optional inclusive `--start` and `--end` dates.
- [x] Add `run_d2_limit_up_d1_rise_research(*, start=None, end=None)` returning
  the complete report dictionary and `render_markdown_report(report)` returning
  the Chinese Markdown evidence text.

- [x] Add `python -m alphaagent.server.services.quant.d2_limit_up_d1_rise_research`
  CLI arguments for date bounds and an optional output path.
- [x] Render the definition, data coverage, gross/net D results, D path, equal-weight compounding, yearly rows, representative best/worst samples, and limitations.
- [x] Run the module inside the Compose network against the real PostgreSQL data and write the evidence report.
- [x] Check that sample counts are nonzero, dates are ordered, all return values are finite, and gross/net arithmetic is consistent.

### Task 4: Verify the focused change and maintain project memory

**Files:**

- Modify: `memory/06_backtests/README.md`
- Modify: `requirements/alphaagent_d2_limit_up_d1_rise_event_study_implementation_plan.md`

- [x] Run:

```bash
uv run pytest tests/alphaagent/services/quant/test_d2_limit_up_d1_rise_research.py tests/alphaagent/services/quant/test_d1_event_feature_research.py -q
uv run python -m compileall alphaagent/server/services/quant/d2_limit_up_d1_rise_research.py
```

- [x] Link the new evidence report from the backtest index without copying its full metrics into the overview.
- [x] Mark completed checkboxes in this plan and inspect `git diff --check` plus a scoped diff.
- [x] Report the actual sample range, sample count, D net win rate/return, equal-weight net compound return, maximum drawdown, and limitations to the user.
