# Unbounded Actionable Recommendations And Quality Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show every currently actionable quality-filtered recommendation while reporting the win rate and return quality of every historical recommendation independently from the frozen two-position cash account.

**Architecture:** Keep `recommendations.portfolio` and the 100,000 CNY two-position account as the constrained execution view. Add `recommendations.actionable_recommendations` for all final `buy_now` signals that pass the existing lane and profitability gates, and add a `recommendation_quality` report that replays each filtered order in an isolated standard 50,000 CNY slot with the existing fees, slippage, T+1, 14:30 exit, and locked-limit retry. Compound the mean net return of all recommendations resolving on each day so the result measures recommendation quality without allowing the number of same-day recommendations to mechanically multiply return.

**Tech Stack:** Python 3.13, existing limit-up cash ledger, FastAPI report contract, React/TypeScript, pytest, Vitest, PostgreSQL `limit-up-history-v15`.

---

## Frozen Interpretation

- “Recommendations are not limited” removes the two-row display and `portfolio_selected` capacity restriction only from the primary recommendation list.
- Every displayed recommendation must still have final `action == buy_now`, pass the 5-sample/30% first-board profitability gate when applicable, be in an allowed product lane, be in the current entry window, and use a fresh snapshot.
- `recommendations.portfolio` remains the two-position execution subset; `actionable_recommendations` is the unbounded strict recommendation set.
- The 5-sample/30% quality gate is not removed in this task. Its effect must be judged with both unconstrained recommendation-quality metrics and the constrained cash account.
- Recommendation-quality return is a daily equal-weight research series, not a capital account and not an unlimited-capital profit claim.
- Do not commit or push.

### Task 1: Build Position-independent Recommendation Quality

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [x] **Step 1: Add a failing independent-quality test**

Create three same-day filtered orders while the shared account has two positions. Assert the cash summary closes two trades, while `recommendation_quality.summary` evaluates all three and reports its own win rate, average net return, daily equal-weight return, and drawdown.

```python
assert report["summary"]["trade_count"] == 2
quality = report["recommendation_quality"]
assert quality["position_constraints_applied"] is False
assert quality["summary"]["signal_count"] == 3
assert quality["summary"]["trade_count"] == 3
```

- [x] **Step 2: Implement isolated standard-slot replay**

Add `_recommendation_quality_report()` in `history_service.py`. Group bars by symbol, run `_simulate_account([order], symbol_bars, trade_dates, "next_1430", config)` for each order, collect closed trades and skipped orders, then reuse `_signal_daily_equity()` and `_summary()`.

```python
return {
    "mode": "independent_standard_slot_daily_equal_weight",
    "position_constraints_applied": False,
    "standard_slot_cash": config.initial_cash / config.max_positions,
    "summary": summary,
    "daily_results": daily_results,
    "skipped_reasons": dict(sorted(reason_counts.items())),
}
```

- [x] **Step 3: Make the scheduled report expose all-order quality**

Build quality from every profitability-qualified order, set `signal_summary` and `signal_daily_results` to the independent result for backward compatibility, and retain `summary`/`execution_summary` as the constrained cash account.

- [x] **Step 4: Run focused history tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q
```

Expected: the report distinguishes all recommendations from position-limited fills without changing cash-account assertions.

### Task 2: Compare Filtered And Unfiltered Recommendation Quality

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [x] **Step 1: Add failing comparison-contract assertions**

Assert `profitability_filter` includes both `selected_recommendation_quality` and `unfiltered_recommendation_quality`, and that their signal counts are independent of cash fills.

- [x] **Step 2: Build both reports with the same execution model**

Use the filtered and unfiltered order streams with identical bars, trade dates, config, fees, and exit rules. Add deltas for recommendation win rate, average return, and daily equal-weight total return.

- [x] **Step 3: Add typed frontend contracts**

Add `LimitUpRecommendationQuality` and the filtered/unfiltered comparison fields to `LimitUpLaneBacktest` without weakening existing summary types.

- [x] **Step 4: Make recommendation quality visible**

Use `recommendation_quality.summary` in the live backtest strip and backtest signal strip. Label it `全量推荐质量`; show evaluated count, win rate, average D+1 net return, and daily equal-weight compound return. Keep the two-position cash return and drawdown visibly separate.

- [x] **Step 5: Run frontend tests and build**

Run:

```bash
pnpm --dir frontend test
pnpm --dir frontend build
```

### Task 3: Remove The Recommendation Count Limit

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_profitability.py`

- [x] **Step 1: Add failing backend tests**

Create three `buy_now` signals where only two are `portfolio_selected`. Assert the constrained `portfolio` remains at two while `actionable_recommendations` includes all three in the frozen lane/joint-rate ordering. Assert observe, stale, out-of-window, and failed-profitability rows remain excluded.

- [x] **Step 2: Build the strict unbounded backend list**

Reuse the same gate and schedule transformation as the portfolio, but do not require `portfolio_selected` and do not slice to `MAX_POSITIONS`. Publish the result as `recommendations.actionable_recommendations`.

- [x] **Step 3: Add failing frontend tests**

Assert the primary scope prefers `actionable_recommendations`, returns all strict rows in backend order, never appends watchlist observations, and falls back to `portfolio` for older responses.

- [x] **Step 4: Remove frontend slicing and slot copy**

Return the full deduplicated actionable list. Change `正式买点 N / 2` to `正式买点 N` and clarify that recommendation count is unrestricted while the cash-account backtest remains two positions.

- [x] **Step 5: Run live regressions**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_first_board_profitability.py -q
pnpm --dir frontend exec vitest run src/features/limitUp/livePortfolio.spec.ts
```

### Task 4: Real-data Decision And Completion

**Files:**
- Modify: `memory/06_backtests/limit_up_first_board_actionable_filter_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-16-unbounded-recommendations-quality-backtest.md`

- [x] **Step 1: Rebuild the real PostgreSQL report**

Record filtered and unfiltered all-recommendation signal count, win rate, average net return, daily equal-weight return, drawdown, hard-loss rate, and profit factor next to the constrained two-position account.

- [x] **Step 2: Judge the gate using both views**

Keep the gate only if the independent recommendation-quality evidence supports the intended reduction in wrong recommendations. Do not optimize a new threshold on validation or forward data during this task.

- [x] **Step 3: Run all verification**

Run all `test_limit_up_*.py`, relevant Ruff, compileall, `git diff --check`, all frontend tests, and the production build.

- [x] **Step 4: Rebuild and smoke test API/Web**

Verify healthy containers, JWT gateway access, `limit-up-live-v10`, strict unbounded actionable rows, and the real recommendation-quality report.

- [x] **Step 5: Update durable evidence**

Document that recommendation-quality compounding is daily equal-weight research evidence, while the two-position cash account remains the implementable capital result. Mark all plan steps complete without committing or pushing.
