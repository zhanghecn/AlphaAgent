# Live Stock-gene Evidence And Blocked Top1 Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch live first-board joint rates to the user's same-stock formula, then causally replay the 134 no-eligible days to measure observation-pool Top1 and isolated blocker relaxations.

**Architecture:** Keep the existing generic analog evidence for TBOX and historical risk vetoes, but overwrite only first-board public profitability fields with a cached 252-day same-stock D+1 index and the current stock's prior 126-day seal gene. Add an isolated research module that processes persisted v15 candidate pools in signal-time order; it never changes lane gates and only reports observation Top1, blocker attribution, and leave-one-gate-out counterfactuals.

**Tech Stack:** Python 3.13, FastAPI, PostgreSQL-backed `limit-up-history-v15`, React/TypeScript, pytest, Vitest, existing cash simulator.

---

## Frozen Contracts

- Live first-board formula: `prior_seal_success_rate_126 * same-stock prior sealed first-board D+1 close net win rate`.
- Same-stock events require `result_date < signal_date`; current/future outcome availability never affects selection.
- Same-stock source window is the last 252 persisted replay trade days before the live signal date.
- Show the computed rate with any positive D+1 sample count, but expose whether at least 5 samples exist; do not claim the product is calibrated probability.
- Live first-board sorting remains joint rate descending, then current `change_pct` descending. Generic analog fields remain available for existing veto logic.
- Two-to-three evidence, sorting, gates, and versions other than `LIVE_STRATEGY_VERSION` remain unchanged.
- Blocked-day research universe starts at the first v15 first-board pool date (`2025-06-27`) and includes only days with no eligible first board.
- Observation Top1 is causal: ignore candidates before 10:00 for executable analysis, group exact equal signal times, choose only inside the earliest available group, and never replace it with a later row.
- Relaxing one blocker means selecting the first candidate whose remaining blocker set is empty after removing exactly that blocker. This is diagnostic only and never mutates `lane_research.py`.
- Do not commit or push without explicit user authorization.

### Task 1: Lock Same-stock Live Evidence

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_evidence.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_profitability.py`

- [x] **Step 1: Add failing prior-only index tests**

Add tests proving that the index includes only the same symbol's sealed first-board events with `result_date < signal_date`, excludes same-day/future results, and expires source days outside the 252-day window.

```python
index = build_same_stock_first_board_d1_index(
    replay_days,
    signal_date=date(2026, 7, 10),
    history_window_days=252,
)
assert index["600001.SSE"]["sample_count"] == 2
assert index["600001.SSE"]["win_rate"] == 50.0
```

- [x] **Step 2: Add failing live overlay tests**

Inject generic analog evidence and a same-stock index. Assert the first-board public fields come from the current stock's 126-day seal gene and same-stock D+1 rows, while TBOX/generic veto fields remain. Assert two-to-three public profitability fields are still absent.

```python
result = attach_historical_evidence(
    snapshot,
    analog_index=analog_index,
    stock_d1_index={"600001.SSE": {"sample_count": 5, "win_count": 3,
        "win_rate": 60.0, "average_return_pct": 1.2}},
)
evidence = result["recommendations"]["lanes"]["now"][0]["historical_evidence"]
assert evidence["seal_success_rate"] == 75.0
assert evidence["historical_win_rate"] == 45.0
```

- [x] **Step 3: Implement the cached same-stock index and overlay**

Add `build_same_stock_first_board_d1_index()` as a pure helper, `load_same_stock_first_board_d1_index()` as the cached repository loader, and `_same_stock_first_board_evidence()` as the field mapper. Clear both live evidence caches together. Keep `_risk_veto_reasons()` on generic analog evidence before the first-board overlay.

- [x] **Step 4: Run focused backend tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_first_board_profitability.py tests/alphaagent/test_limit_up_live.py -q
```

Expected: same-stock cutoff, formula, generic veto, and two-to-three isolation pass.

### Task 2: Expose The Correct Live Contract

**Files:**
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `tests/alphaagent/test_limit_up_forward_validation.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `frontend/src/features/limitUp/livePortfolio.spec.ts`

- [x] **Step 1: Add/adjust failing contract assertions**

Assert live version `limit-up-live-v8`, same-stock method identifier, sample qualification fields, and unchanged rate-then-change frontend ordering.

- [x] **Step 2: Bump only the live version and types**

Set `LIVE_STRATEGY_VERSION = "limit-up-live-v8"`. Add typed fields for same-stock D+1 wins, 126-day touch/seal counts, history window, and sample qualification. Do not change history, scheduled, cash, or walk-forward versions.

- [x] **Step 3: Clarify first-board metrics**

Rename the visible first-board metric to `个股联合率`; show `同股D+1` and `126日封停` with sample counts. Keep the existing compact metric layout and all two-to-three rendering unchanged.

- [x] **Step 4: Run frontend tests and build**

Run:

```bash
cd frontend && pnpm test -- src/features/limitUp/livePortfolio.spec.ts
cd frontend && pnpm build
```

Expected: Vitest, TypeScript, and Vite build pass.

### Task 3: Build Causal Blocked-day Research

**Files:**
- Create: `alphaagent/server/services/limit_up/first_board_blocker_research.py`
- Create: `tests/alphaagent/test_limit_up_first_board_blocker_research.py`

- [x] **Step 1: Add failing causal Top1 tests**

Cover: pre-10 rows excluded from executable Top1; a later higher score cannot replace the earliest post-10 group; simultaneous rows use same-stock joint rate then signal-point change; future outcome mutation cannot alter selection.

```python
report = build_first_board_blocker_research_report(days)
selection = report["variants"]["first_post_10_observation"]["selections"][0]
assert selection["signal_time"] == "10:05:00"
```

- [x] **Step 2: Add blocker attribution and relaxation tests**

Assert candidate-level blocker counts, Top1 blocker counts, exact blocker combinations, and single-gate relaxation. A row becomes selectable only when removing that gate leaves no blockers; multi-blocked rows must not leak into a single-gate result.

- [x] **Step 3: Implement the pure report builder**

Return coverage, blocker frequency, exact combinations, `first_observation`, `first_post_10_observation`, and one variant per isolated blocker relaxation. Every summary includes closed count, win rate, average return, compounded return, drawdown, seal rate, hard-loss rate, and profit factor. Selections retain date/time/symbol/blockers and same-stock evidence.

- [x] **Step 4: Run focused research tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_first_board_blocker_research.py -q
```

Expected: all causal selection and blocker-isolation tests pass.

### Task 4: Run The 134-day Cash Validation

**Files:**
- Create: `memory/06_backtests/limit_up_first_board_blocker_relaxation_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run the report on all v15 replay days**

Record the exact no-eligible-day count, post-10 coverage, blocker and combination frequencies, observation Top1 performance, and phase summaries.

- [x] **Step 2: Run 14:30 cash and double-cost accounts**

Materialize causal selections, attach exact/proxy 14:30 prices, and run `CashBacktestConfig(initial_cash=100_000, max_positions=2)`. Run double costs for observation Top1 and every relaxation with at least 30 closed trades.

- [x] **Step 3: Classify gate evidence without changing production**

Use explicit labels: `keep_hard` for sufficiently sampled negative/unsafe evidence, `relaxation_candidate_needs_validation` for positive but unproven evidence, and `insufficient_isolated_samples` where a single gate cannot be identified. Do not edit lane thresholds in this task.

- [x] **Step 4: Update durable evidence**

Document what may be researched further, what must remain blocked, data limitations, and the distinction between daily observation and daily buy recommendation.

### Task 5: Final Verification And Runtime Smoke

**Files:**
- Modify: `docs/superpowers/plans/2026-07-16-live-stock-gene-and-blocked-top1-research.md`

- [x] **Step 1: Run backend regressions and static checks**

Run focused live, first-board, history, forward-validation, cash, and two-to-three tests; run Ruff, compileall, and `git diff --check`.

- [x] **Step 2: Rebuild services and smoke test**

Rebuild API and frontend containers, verify gateway health, authenticated API health, runtime version `limit-up-live-v8`, same-stock evidence fields, and unchanged `limit-up-history-v15`.

- [x] **Step 3: Mark this plan complete**

Record exact test/build outcomes and any remaining data limitations. Do not commit or push.

## Completion Record

- Backend: all `tests/alphaagent/test_limit_up_*.py` passed, `500 passed` with one existing
  Starlette/httpx deprecation warning.
- Frontend: `16` files and `71` tests passed; TypeScript/Vite production build passed with the
  existing large-chunk warning.
- Static checks: targeted Ruff, `compileall`, and full-worktree `git diff --check` passed.
- Runtime: API and Web images rebuilt; gateway `/readyz` reported both upstreams `ok`, authenticated
  API health passed, `/short-term` returned HTTP 200, history remained `limit-up-history-v15` with
  603 persisted days through `2026-07-15`, and live reported `limit-up-live-v8`.
- The after-close live response contained no first-board row. A read-only replay of the actual
  persisted `2026-07-16T14:29:45.806653+08:00` intraday snapshot through the rebuilt v8 runtime
  produced 237 first-board rows: all 237 exposed the same-stock method and required fields, and every
  lane was ordered by joint rate then signal-point change. All 17 two-to-three rows remained free of
  first-board profitability fields. No replayed snapshot was persisted.
- Remaining evidence limitations: no Tick/L2 queue proof; very low exact 14:30 minute coverage; the
  low-position relaxation has 38 post-hoc samples, exceeds the 10% drawdown limit, and remains blocked.
- No commit or push was performed.
