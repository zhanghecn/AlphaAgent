# First-board Profitability Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents and do not commit unless the user explicitly requests it.

**Goal:** Rank live first-board recommendations by a transparent historical probability that combines D-day seal success with D+1 strategy profitability, then verify whether that ranking improves historical win rate and return.

**Architecture:** Extend the existing prior-only analog accumulator with separate first-board labels: `P(seal | touch)` and `P(D+1 net profit | sealed)`. Their product is the displayed and ranked historical win rate; live sorting applies only to first-board candidates and uses current change percentage as the second key. A dedicated walk-forward research function compares the existing first-board order with the new order without changing two-to-three rules or claiming that a daily proxy is a historical intraday snapshot.

**Tech Stack:** Python 3.13, FastAPI service modules, pytest, React 18, TypeScript, Vitest, existing PostgreSQL history ledger and cash-account simulator.

---

### Task 1: Lock the first-board probability contract

**Files:**
- Create: `alphaagent/server/services/limit_up/first_board_profitability.py`
- Create: `tests/alphaagent/test_limit_up_first_board_profitability.py`

- [x] **Step 1: Add failing probability tests**

Add tests for the exact product formula, missing components, percentage bounds, and the sort order `historical_win_rate DESC, change_pct DESC, vt_symbol ASC`.

```python
assert combined_historical_win_rate(60.0, 80.0) == 48.0
assert combined_historical_win_rate(None, 80.0) is None
assert [row["vt_symbol"] for row in rank_first_board_signals(rows)] == [
    "600002.SSE",
    "600001.SSE",
    "600003.SSE",
]
```

- [x] **Step 2: Run the focused test and confirm failure**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_first_board_profitability.py -q`

Expected: collection fails because the module does not exist.

- [x] **Step 3: Implement the pure metric and ranking helpers**

Implement:

```python
def combined_historical_win_rate(
    d1_money_effect_win_rate: object,
    seal_success_rate: object,
) -> float | None:
    d1_rate = _bounded_percentage(d1_money_effect_win_rate)
    seal_rate = _bounded_percentage(seal_success_rate)
    if d1_rate is None or seal_rate is None:
        return None
    return round(d1_rate * seal_rate / 100, 4)
```

`rank_first_board_signals()` must preserve non-first-board relative order and only reorder first-board rows by ready evidence, combined rate, change percentage, then symbol.

- [x] **Step 4: Re-run the focused test**

Expected: all tests pass.

### Task 2: Produce prior-only D+1 money-effect and seal evidence

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_engine.py`
- Modify: `alphaagent/server/services/limit_up/live_evidence.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_profitability.py`

- [x] **Step 1: Add failing accumulator tests**

Create sealed winners, sealed losers, failed boards, and same-day immature outcomes. Assert:

```python
assert analog["seal_success_rate"] == 75.0
assert analog["d1_money_effect_win_rate"] == 66.6667
assert analog["historical_win_rate"] == 50.0
assert analog["d1_money_effect_sample_count"] == 3
assert analog["seal_sample_count"] == 4
```

The D+1 label uses net `next_close_return_pct` only after final seal; the seal denominator contains every touched first-board sample. Same-day results must remain excluded by `result_before`.

- [x] **Step 2: Extend the analog accumulator minimally**

Track sealed D+1 close sample/win counts and calculate both components with the existing hierarchical prior shrinkage. Keep `smoothed_win_rate` and existing gates for compatibility; add the explicit fields rather than silently changing their meaning.

- [x] **Step 3: Attach the composite evidence to live first-board signals**

For `target_board == 1`, expose:

```python
{
    "historical_win_rate": combined_rate,
    "historical_win_rate_method": "seal_success_x_d1_close_net_profit",
    "d1_money_effect_win_rate": d1_rate,
    "d1_money_effect_sample_count": d1_count,
    "seal_success_rate": seal_rate,
    "seal_sample_count": seal_count,
    "d1_exit_proxy": "next_close",
}
```

For other board levels, do not synthesize this first-board metric.

- [x] **Step 4: Run focused backend tests**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_first_board_profitability.py tests/alphaagent/test_limit_up_live.py -q`

Expected: all tests pass without changing two-to-three assertions.

### Task 3: Apply the requested live ordering

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_profitability.py`
- Modify: `tests/alphaagent/test_limit_up_live.py`

- [x] **Step 1: Add failing portfolio and watchlist order tests**

Use first-board signals where old TBOX/concept ranks disagree with the new metric. Assert that the backend portfolio and watchlist order is combined historical win rate first and change percentage second. Add a mixed-lane assertion proving two-to-three retains its existing lane behavior.

- [x] **Step 2: Rank after historical evidence is attached**

Call `rank_first_board_signals()` for recommendation lanes and the watchlist, then apply the same first-board ordering to the combined frontend display. Preserve the backend execution portfolio order, action eligibility, structural blockers, lane validation, `portfolio_selected`, diversification, stale-snapshot handling, and execution permissions. A failed historical comparison must not promote or reorder rows in the execution portfolio.

- [x] **Step 3: Bump only the live behavior version**

Change `LIVE_STRATEGY_VERSION` from `limit-up-live-v6` to `limit-up-live-v7`. Do not bump the history strategy because historical candidate generation and outcomes are unchanged.

- [x] **Step 4: Run live regressions**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_first_board_profitability.py tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_forward_validation.py -q`

Expected: all tests pass and the changed version assertions report v7.

### Task 4: Present the transparent components

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Add failing client sort tests**

Add three first-board observations with conflicting concept rank, combined win rate, and change percentage. Assert the same ordering as the backend, and retain an existing two-to-three ordering assertion.

- [x] **Step 2: Extend the TypeScript evidence contract**

Add nullable typed fields for `historical_win_rate`, `d1_money_effect_win_rate`, `seal_success_rate`, both sample counts, method, and exit proxy.

- [x] **Step 3: Replace the opaque metric cells**

Keep the existing four-cell compact grid and replace `TBOX`/generic `历史胜率` with:

```tsx
<Metric label="综合历史胜率" value={formatPct(evidence?.historical_win_rate)} />
<Metric label="D+1赚钱率" value={formatPct(evidence?.d1_money_effect_win_rate)} />
<Metric label="封停成功率" value={formatPct(evidence?.seal_success_rate)} />
<Metric label="平均 D+1" value={formatPct(evidence?.average_return_pct)} />
```

Do not add cards, explanatory banners, strategy controls, or decorative styling.

- [x] **Step 4: Run frontend verification**

Run: `pnpm --dir frontend test -- --run frontend/src/features/limitUp/livePortfolio.spec.ts`

Run: `pnpm --dir frontend run build`

Expected: tests and production build pass.

### Task 5: Run a prior-only ranking audit and cash-account comparison

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_profitability.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_profitability.py`
- Create: `memory/06_backtests/limit_up_first_board_profitability_ranking_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Add a prior-only comparison test**

Build synthetic chronological replay days where later outcomes cannot affect earlier rankings. Compare the existing first-board order with the new combined-rate order using identical candidate days and selection counts.

- [x] **Step 2: Implement the research comparison**

The report must include:

```python
{
    "status": "ready" | "insufficient_data",
    "mode": "daily_candidate_ranking_proxy",
    "baseline": {...},
    "profitability_ranking": {...},
    "delta": {...},
    "coverage": {...},
    "limitations": [...],
}
```

At each signal date, build analog evidence only from outcomes with `result_date < signal_date`. Compare equal daily Top-N counts, report D+1 close net win rate, average return, compounded return, maximum drawdown, and seal rate. Explicitly state that the daily candidate proxy cannot reproduce missing historical 15-second near-limit snapshots.

- [x] **Step 3: Run the comparison against the current v15 ledger**

Use the service module directly against `limit-up-history-v15`. Also run the unchanged formal `next_1430` cash backtest and record its baseline so a display-order change is not misreported as an execution improvement.

- [x] **Step 4: Record evidence and decision**

Write exact sample coverage, old/new metrics, deltas, phase results, and limitations. Only state that the ranking improves results if both walk-forward evidence and the account comparison support that conclusion; otherwise retain the requested display order but do not promote it into historical candidate eligibility or automatic execution.

### Task 6: Full verification and runtime check

**Files:**
- Modify: `memory/05_runtime/run_debug.md` only if a new durable verification command is needed.

- [x] **Step 1: Run focused and broad regressions**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_first_board_profitability.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_history.py \
  tests/alphaagent/test_limit_up_cash_backtest.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
uv run python -m compileall alphaagent/server/services/limit_up
git diff --check
```

- [x] **Step 2: Rebuild the affected services**

Run: `docker compose up -d --build alphaagent-api alphaagent-web`

Expected: API, gateway, PostgreSQL, and Redis are healthy; `/limit-up` returns HTTP 200.

- [x] **Step 3: Verify desktop and mobile rendering**

Use the existing Playwright workflow at desktop and `390x844`. Confirm the four metrics fit, no text overlaps, no horizontal page overflow appears, and the browser console has no error.

- [x] **Step 4: Final memory hygiene**

Keep only the current conclusion and link to the detailed report in overview memory. Do not copy raw test logs into memory and do not create a Git commit.
