# Causal First-board High-confidence Recommendation Implementation Plan

**Status (2026-07-16):** Causal research and evidence correction completed. The
frozen production gate failed because the primary rule produced only 13 closed
recommendations and did not exceed the `first_sampled` total cash return. Task 4
was therefore skipped; live recommendations, versions, frontend, execution, and
two-to-three were not changed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove candidate-availability lookahead, replay first-board recommendations in true signal-time order, and directly promote only a high-win-rate recommendation rule that passes frozen return and risk gates.

**Architecture:** Extend the isolated stock-gene research module with a causal event selector. On each day, candidates arrive by `signal_time`; the strategy may skip a candidate using only its already-known stock history, locks the first passing candidate, and can never replace it with a later stock. If the frozen primary gate passes, attach the same stock-specific evidence to live first boards and expose only one locked high-confidence first-board recommendation; otherwise leave production unchanged.

**Tech Stack:** Python 3.13, `limit-up-history-v15`, existing cash simulator, FastAPI live service, PostgreSQL live traces, React/TypeScript, pytest/Vitest.

---

## Frozen Contract

- Historical evidence remains stock-specific and prior-only: 252 trade-day window, same-stock sealed first-board D+1 close outcomes, `result_date < signal_date`.
- Primary sample gate: at least 5 same-stock D+1 outcomes.
- Primary recommendation gate: combined stock seal/D+1 win rate at least 50%.
- Fixed threshold sensitivities: 45% and 55%. Fixed sample sensitivities at the 50% threshold: 3 and 8.
- Daily processing: sort eligible candidates by `signal_time`; group exact equal timestamps; select the highest score only inside the first timestamp group containing a passing candidate; stop for the day.
- A later candidate may be selected only when every earlier candidate failed the frozen gate. It may never replace an earlier passing recommendation.
- Baselines: `first_eligible` selects the first v15 eligible candidate; `first_sampled` selects the first candidate meeting the primary sample gate regardless of score.
- Primary recommendation semantics: inspect only the first eligible signal-time group. If no row in that first group passes the score/sample gate, make no recommendation for the day; never wait for a later group. Fixed variants are `first_combined_45/50/55`, with `first_combined_50` primary.
- No historical `change_pct` tie-break because candidates lack a common snapshot. Live equal-time ties may use current snapshot change after the historical score.
- Primary acceptance requires at least 30 closed recommendations, win rate at least 60%, 14:30 profit factor at least 2.0, 14:30 maximum drawdown no worse than -10%, positive double-cost return, and improvement over `first_sampled` in win rate, average return, total cash return, and profit factor without more than 2 percentage points of extra drawdown.
- The 45%/55% and 3/8 sensitivity variants must remain profitable with profit factor above 1.5; otherwise do not change production.
- Two-to-three, history v15, and scheduled execution remain unchanged.
- Do not commit or push without explicit user authorization.

### Task 1: Lock Causal Selection

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_stock_gene_research.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

- [x] **Step 1: Add failing causal-order tests**

```python
def test_causal_selector_keeps_earlier_passing_candidate() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", 52.0, samples=5),
        _scored("600002.SSE", "13:10:00", 90.0, samples=20),
    ]
    selected = select_causal_first_board_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )
    assert selected["vt_symbol"] == "600001.SSE"


def test_causal_selector_can_skip_earlier_failed_candidate() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", 49.0, samples=5),
        _scored("600002.SSE", "13:10:00", 60.0, samples=5),
    ]
    selected = select_causal_first_board_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )
    assert selected["vt_symbol"] == "600002.SSE"
```

Add a mutation test proving that changing or adding any later candidate cannot alter an already passing earlier selection. Add an equal-`signal_time` test proving only simultaneous rows are ranked against each other.

- [x] **Step 2: Run the tests and confirm missing-function failure**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_first_board_stock_gene_research.py -q`

Expected: tests fail because the causal selector does not exist.

- [x] **Step 3: Implement the selector**

```python
def select_causal_first_board_candidate(
    candidates: Sequence[Mapping[str, object]],
    *,
    min_d1_samples: int,
    min_combined_rate: float,
) -> dict[str, object] | None:
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda row: (
            str(row.get("signal_time") or "99:99:99"),
            str(row.get("vt_symbol") or ""),
        ),
    )
    for _, same_time in groupby(
        ordered,
        key=lambda row: str(row.get("signal_time") or "99:99:99"),
    ):
        passing = [
            row
            for row in same_time
            if _integer(row.get("stock_d1_sample_count"), 0) >= min_d1_samples
            and (_percentage(row.get("stock_gene_combined_win_rate")) or 0.0)
            >= min_combined_rate
        ]
        if passing:
            return rank_stock_gene_candidates(passing)[0]
    return None
```

- [x] **Step 4: Re-run causal-order tests**

Expected: all future-candidate mutation and equal-time tests pass.

### Task 2: Build Causal Historical Variants

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_stock_gene_research.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

- [x] **Step 1: Add failing report tests**

```python
report = build_causal_first_board_recommendation_report(
    days,
    history_window_days=252,
    min_d1_samples=5,
    thresholds=(45.0, 50.0, 55.0),
)
assert set(report["variants"]) == {
    "first_eligible",
    "first_sampled",
    "first_combined_45",
    "first_combined_50",
    "first_combined_55",
    "combined_45",
    "combined_50",
    "combined_55",
}
assert report["ranking_contract"]["candidate_availability"] == "signal_time_causal"
```

Mutate every outcome and score belonging to candidates after the selected signal time and assert the selected date/symbol/time remains unchanged.

- [x] **Step 2: Implement chronological report construction**

Reuse the existing matured per-stock event index. Enrich all current-day eligible candidates with prior-only evidence, then select independently for each variant. `first_eligible` ignores sample and score; `first_sampled` uses only the sample gate; `first_combined_*` evaluates only the first signal-time group and returns no recommendation when that group fails; `combined_*` remains a diagnostic that may skip failed early groups. Compact selections must include `signal_date`, `signal_time`, evidence, and explicit pass reason.

- [x] **Step 3: Return comparable performance and coverage**

Return trade count, win rate, average D+1 close return, compounded return, drawdown, hard-loss rate, seal rate, profit factor, phase summaries, no-recommendation days, and selections for every causal variant.

- [x] **Step 4: Run all research tests**

Expected: all causal and prior-only tests pass.

### Task 3: Run Frozen Causal Validation

**Files:**
- Create: `memory/06_backtests/limit_up_first_board_causal_high_confidence_20260716.md`

- [x] **Step 1: Run primary and threshold sensitivity reports**

Run the causal report on all 603 v15 replay days with thresholds 45/50/55 and the primary five-sample gate. Print overall, expanding OOS, locked holdout, trade frequency, and replacement/skip reasons.

- [x] **Step 2: Run sample sensitivities**

Run the fixed 50% gate with minimum samples 3 and 8. Do not select a different primary rule after observing results.

- [x] **Step 3: Run 14:30 cash accounts and double-cost pressure**

For every frozen variant, reconstruct selected candidate orders and run `next_1430` with `CashBacktestConfig(initial_cash=100_000, max_positions=2)`. Re-run the primary rule with doubled commission, tax, transfer fee, and slippage.

- [x] **Step 4: Apply the frozen acceptance gate**

Create a machine-readable pass/fail table for every acceptance condition. Production changes are allowed only when every primary and sensitivity check passes.

### Task 4: Directly Improve Live Recommendations Only If Accepted

**Skipped by the frozen gate:** the primary rule had 13 closed recommendations
against the required 30 and failed the total-cash-return comparison. None of the
following live or frontend steps were authorized by the plan after that failure.

**Files:**
- Modify if accepted: `alphaagent/server/services/limit_up/live_evidence.py`
- Modify if accepted: `alphaagent/server/services/limit_up/live_service.py`
- Modify if accepted: `alphaagent/server/services/limit_up/live_trace_repository.py`
- Modify if accepted: `alphaagent/server/services/limit_up/versions.py`
- Modify if accepted: `frontend/src/api/limitUp.ts`
- Modify if accepted: `frontend/src/pages/LimitUpPage.tsx`
- Modify if accepted: relevant backend and frontend tests

- [ ] **Step 1: Add failing live evidence and gate tests**

Assert a first board is recommendation-eligible only when sample count is at least 5 and combined rate is at least 50%. Assert later snapshots preserve the first passing selection for the trading day, while below-gate rows remain plain observations. Assert two-to-three signals are unchanged.

- [ ] **Step 2: Attach stock-specific evidence to current candidates**

Build a cached 252-day same-stock index from v15 replays and attach the exact research fields. Do not expose the old generic analog joint rate as the first-board selection score.

- [ ] **Step 3: Lock one high-confidence first-board recommendation**

Use persisted current-day live traces to retain the earliest passing first-board selection. On the first passing snapshot choose the highest combined rate among simultaneous rows, then current `change_pct`; later rows cannot replace it. Below-gate candidates remain visible but cannot carry buy wording or enter the first-board live portfolio.

- [ ] **Step 4: Present one clear recommendation**

Display one `今日首选` row with historical touch/seal counts, same-stock D+1 samples, win rate, average premium, and the recommendation reason. Display all remaining rows under `观察`, never `观察买入`. Bump only the live strategy version.

- [ ] **Step 5: Run backend/frontend tests and build**

Run the focused backend live suites, frontend Vitest suite, TypeScript/Vite build, and authenticated API smoke check.

### Task 5: Correct Evidence and Finish

**Files:**
- Modify: `memory/06_backtests/limit_up_first_board_stock_gene_ranking_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-16-first-board-stock-gene-ranking-research.md`

- [x] **Step 1: Mark the old daily Top1 result invalid for execution**

State explicitly that selecting from the completed daily candidate set and buying at the selected signal time contains candidate-availability lookahead. Remove `promising_not_promoted` as an execution conclusion and retain the table only as invalidated diagnostic evidence.

- [x] **Step 2: Write the causal report and decision**

Record the exact chronological selection rule, all frozen variants, cash and cost results, acceptance checks, and whether live production was changed.

- [x] **Step 3: Run final verification**

Run focused causal/live tests, Ruff, compileall, `git diff --check`, and container health checks. Confirm no two-to-three or history-version behavior changed.

Verified with 192 focused causal, first-board, live, trace, history, and
two-to-three regression tests; Ruff, compileall, and `git diff --check` passed.
The rebuilt API loaded `limit-up-history-v15`, and both gateway and authenticated
API health checks returned healthy.
