# First-board Actionable Profitability Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the frozen scheduled baseline into an actionable live product by admitting only fully triggered first boards with at least five prior same-stock D+1 samples and a joint rate of at least 30%, while keeping observations out of the buy list.

**Architecture:** Reuse the v8 prior-only same-stock evidence, add one shared execution-gate contract for historical orders and live signals, and keep two-to-three unchanged. The scheduled v5 account will report the filtered portfolio and retain the unfiltered v4-equivalent account as a comparison; the frontend primary list will consume only the backend actionable portfolio while the existing trace remains the observation surface.

**Tech Stack:** Python 3.13, FastAPI, PostgreSQL `limit-up-history-v15`, existing cash ledger, React/TypeScript, pytest, Vitest.

---

## Frozen Contracts

- First-board execution gate: `stock_d1_sample_count >= 5` and `same-stock joint rate >= 30%`.
- Joint rate remains `prior_seal_success_rate_126 * prior same-stock sealed first-board D+1 close-net win rate`.
- Every historical D+1 event must satisfy `result_date < signal_date`; the history window remains 252 replay trade days.
- The threshold is selected on the design sample only: among the fixed 5-sample grid, 30% had at least 20 design trades, drawdown within 10%, and the highest design cash return. The `2026-04-14..2026-07-15` time-validation segment is evaluation only.
- Two-to-three gates, evidence, and admission remain unchanged.
- Live direct recommendations require: final `action == buy_now`, `portfolio_selected == true`, current schedule entry permission, fresh snapshot, and the profitability gate for first boards.
- Watchlist/observation rows never appear in the primary actionable list. They remain available in the trace and backend diagnostics.
- Historical selected account uses 10万元, two 50% positions, D+1 14:30 exit, existing costs, and the existing conservative locked-limit retry.
- Keep `limit-up-history-v15` and `limit-up-cash-v4`; bump live to v9 and scheduled execution to v5.
- Do not commit or push without explicit user authorization.

### Task 1: Share Prior-only Evidence With Scheduled Orders

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_stock_gene_research.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

- [x] **Step 1: Add a failing causal enrichment test**

Add a test with two matured same-stock events, one same-day/future event, and a two-to-three order. Assert only prior sealed first-board events enrich the first-board order and the relay is unchanged.

```python
enriched = attach_prior_stock_gene_evidence_to_orders(days, orders)
first = enriched[0]
assert first["stock_d1_sample_count"] == 2
assert first["stock_d1_win_rate"] == 50.0
assert first["stock_gene_combined_win_rate"] == 40.0
assert "stock_d1_sample_count" not in enriched[1]
```

- [x] **Step 2: Implement chronological order enrichment**

Add `attach_prior_stock_gene_evidence_to_orders()` using the module's existing pending-event queue and `_stock_evidence(..., min_d1_samples=1)`. Preserve input order and attach no first-board fields to other lanes.

```python
def attach_prior_stock_gene_evidence_to_orders(days, orders, *, history_window_days=252):
    """Attach same-stock evidence available strictly before each order date."""
```

- [x] **Step 3: Run focused tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_first_board_stock_gene_research.py -q
```

Expected: all prior-only, future-mutation, and order-ordering tests pass.

### Task 2: Freeze One Shared Execution Gate

**Files:**
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`

- [x] **Step 1: Add failing gate tests**

Cover first-board pass at exactly 5 samples/30%, rejection for 4 samples or 29.9999%, unavailable evidence, and unconditional two-to-three pass-through.

```python
decision = first_board_profitability_gate({
    "lane": "first_board",
    "stock_d1_sample_count": 5,
    "stock_gene_combined_win_rate": 30.0,
})
assert decision["passed"] is True
```

- [x] **Step 2: Implement gate metadata and filtering**

Set `SCHEDULED_EXECUTION_VERSION = "limit-up-scheduled-v5"`, add filter version `first-board-profitability-gate-v1`, constants 5/30, a gate evaluator that accepts both flat historical fields and live `historical_evidence`, and `filter_profitability_qualified_orders()` that returns passing orders plus reason counts.

- [x] **Step 3: Run scheduled execution tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_scheduled_execution.py -q
```

Expected: v5 contract, boundaries, chronological extraction, and first-board filter pass.

### Task 3: Make The Formal Cash Report Match The Filter

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`

- [x] **Step 1: Add failing report-contract tests**

Assert the selected portfolio applies the profitability filter after the frozen relay comparison, exposes filter thresholds/reason counts, keeps the unfiltered account comparison, and does not filter two-to-three.

- [x] **Step 2: Build filtered and comparison accounts**

Enrich scheduled orders before cash simulation. Keep relay variants unfiltered for the existing lane-selection proof, then apply the shared gate to the configured `first_board + two_to_three` orders for the selected v5 account. Apply the same filtered orders to phase, double-cost, validation, and position-size reports.

- [x] **Step 3: Expose explicit comparison fields**

Return:

```python
"profitability_filter": {
    "version": scheduled_execution.FIRST_BOARD_PROFITABILITY_FILTER_VERSION,
    "minimum_d1_samples": 5,
    "minimum_combined_rate": 30.0,
    "selected_summary": summary,
    "unfiltered_summary": unfiltered_bundle["summary"],
    "reason_counts": reason_counts,
}
```

- [x] **Step 4: Reproduce the PostgreSQL account**

Expected full-account evidence:

- unfiltered: 307 signals, 149 trades, 63.0872% win rate, +266.4491%, -8.0275% drawdown;
- filtered: 168 signals, 97 trades, 68.0412% win rate, +183.3290%, -8.3083% drawdown, PF 3.1838;
- filtered double cost: +156.2700%, -8.6908% drawdown;
- filtered time validation: 43 trades, 65.1163% win rate, +56.2064%, -5.7502% drawdown.

### Task 4: Make Live Portfolio Strictly Actionable

**Files:**
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_profitability.py`

- [x] **Step 1: Add failing live gate tests**

Assert a selected `buy_now` first board is excluded below 5/30 and included at the boundary; a selected observation is not a direct recommendation; a post-validation `action=pass` cannot be revived through `research_action`; two-to-three remains admitted.

- [x] **Step 2: Attach gate decisions before portfolio construction**

Bump live to `limit-up-live-v9`. Annotate lane signals with filter version, pass state, thresholds, and reason. Exclude failed static profitability evidence from `_can_transition_to_live_buy()`.

- [x] **Step 3: Require final actionability**

Change `_build_live_portfolio()` and `_scheduled_live_signal()` to use final `action`, not the pre-veto `research_action`. Only current `buy_now` signals enter the live portfolio; stale/schedule checks may still invalidate them after selection.

- [x] **Step 4: Update the typed API contract**

Add typed profitability-gate fields and v9 assertions without changing two-to-three evidence fields.

- [x] **Step 5: Run live regressions**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_first_board_profitability.py tests/alphaagent/test_limit_up_forward_validation.py -q
```

### Task 5: Separate Buy Recommendations From Observations

**Files:**
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Change tests to reject watchlist mixing**

The portfolio scope must return only backend `recommendations.portfolio`, at most two rows. A non-empty watchlist with an empty portfolio must produce no direct recommendation; a high-rate watchlist row must never reorder or displace a portfolio row.

- [x] **Step 2: Implement the strict primary list**

Remove watchlist concatenation from `liveSignalsForScope(..., "portfolio")`. Preserve board-lane fallback behavior only for old responses that have no `portfolio` field.

- [x] **Step 3: Clarify compact operational copy**

In active mode show `正式买点 N / 2`; when empty show `当前没有通过正式门禁和历史赚钱过滤的买点，保持现金`. Keep observation evidence in the existing trace instead of adding cards, banners, or instructional panels.

- [x] **Step 4: Run frontend verification**

Run:

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend build
```

### Task 6: Durable Evidence And Runtime Verification

**Files:**
- Create: `memory/06_backtests/limit_up_first_board_actionable_filter_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-16-first-board-actionable-profitability-filter.md`

- [x] **Step 1: Document threshold selection and tradeoff**

Record that the filter improves win rate by `4.9540` percentage points and reduces historical wrong trades, while total return falls by `83.1201` percentage points because 52 closed trades disappear/change under cash constraints. Do not describe +183% as guaranteed live performance.

- [x] **Step 2: Run full regressions and static checks**

Run all `test_limit_up_*.py`, Ruff, compileall, `git diff --check`, all frontend tests, and the production build.

- [x] **Step 3: Rebuild and smoke test**

Rebuild API/Web, authenticate through the gateway, verify scheduled v5 and live v9, confirm current live primary rows are only actionable, verify first-board gate metadata and two-to-three isolation using a read-only persisted intraday replay if the market is closed.

- [x] **Step 4: Mark the plan complete**

Record exact outcomes and limitations. Do not commit or push.
