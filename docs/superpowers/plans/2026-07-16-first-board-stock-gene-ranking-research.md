# First-board Stock Gene Ranking Research Implementation Plan

**Status correction (2026-07-16):** The implementation work was completed, but
the daily completed-candidate-set Top1 comparison contains candidate-availability
lookahead and is invalid for execution. Its original promotion conclusion is
superseded by `2026-07-16-causal-first-board-high-confidence-recommendation.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether stock-specific limit-up gene quality and the same stock's prior first-board D+1 premium can produce a clearer and better daily `Top1` choice than the existing signal-time order.

**Architecture:** Add an isolated prior-only research module under `services/limit_up`; do not change the live ranker, execution portfolio, strategy versions, or two-to-three lane. The module reads persisted v15 replay candidates, maintains a 252-trading-day per-stock history of matured first-board outcomes, combines the candidate's point-in-time 126-day seal gene with its own historical D+1 win rate, and compares equal-universe `Top1` variants plus cash-account outcomes.

**Tech Stack:** Python 3.13, `limit-up-history-v15`, pytest, PostgreSQL-backed history repository, existing `cash_backtest` simulator.

---

## Frozen Research Contract

- Target universe: `lane_portfolio.candidate_pool.first_board` rows with `decision == eligible` and a mature D+1 result.
- Gene source: `prior_limit_count_126`, `prior_touch_count_126`, and `prior_seal_success_rate_126` already attached at signal time.
- D+1 source: same-stock historical first-board rows from the replay first-board pool, never generic `lanes.sweep` rows.
- History cutoff: use an event only when `result_date < signal_date`.
- D+1 event: touched, finally sealed, and `next_close_return_pct` is valid. A win is net return greater than zero.
- Primary history window: 252 replay trading days. Primary minimum D+1 sample count: 5. Fixed sensitivity checks: 3 and 8.
- Combined rate: `stock 126-day seal rate * same-stock first-board D+1 win rate` in percentage form.
- Ranking universe: rows meeting the same D+1 sample threshold. Every variant selects from this identical universe.
- Selection: at most one stock per day. Ties retain earlier `signal_time`, then `vt_symbol`. Historical signal-point涨幅 is excluded because rows are not common-time snapshots.
- Product behavior: unchanged until locked-holdout and cash evidence pass the frozen gate.
- Git behavior: do not commit or push without explicit user authorization.

### Task 1: Lock Formula and Ranking

**Files:**
- Create: `alphaagent/server/services/limit_up/first_board_stock_gene_research.py`
- Create: `tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

- [x] **Step 1: Write failing formula and ranking tests**

```python
def test_combined_stock_gene_win_rate_multiplies_stock_rates() -> None:
    assert combined_stock_gene_win_rate(70.0, 60.0) == 42.0
    assert combined_stock_gene_win_rate(None, 60.0) is None


def test_stock_gene_rank_uses_rate_then_earlier_signal() -> None:
    rows = [
        _candidate("600001.SSE", "10:20:00", combined_rate=48.0),
        _candidate("600002.SSE", "10:10:00", combined_rate=48.0),
        _candidate("600003.SSE", "10:05:00", combined_rate=40.0),
    ]
    assert [row["vt_symbol"] for row in rank_stock_gene_candidates(rows)] == [
        "600002.SSE",
        "600001.SSE",
        "600003.SSE",
    ]
```

- [x] **Step 2: Run the test and confirm collection failure**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_first_board_stock_gene_research.py -q`

Expected: collection fails because the module does not exist.

- [x] **Step 3: Implement minimal pure helpers**

```python
def combined_stock_gene_win_rate(
    seal_gene_rate: object,
    d1_win_rate: object,
) -> float | None:
    seal = _percentage(seal_gene_rate)
    d1 = _percentage(d1_win_rate)
    if seal is None or d1 is None:
        return None
    return round(seal * d1 / 100, 4)


def rank_stock_gene_candidates(
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    return sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda candidate: (
            _number(candidate.get("stock_gene_combined_win_rate")) is None,
            -(_number(candidate.get("stock_gene_combined_win_rate")) or 0.0),
            str(candidate.get("signal_time") or "99:99:99"),
            str(candidate.get("vt_symbol") or ""),
        ),
    )
```

- [x] **Step 4: Re-run the focused tests**

Expected: formula validation and deterministic ranking pass.

### Task 2: Build Prior-only Same-stock Evidence

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_stock_gene_research.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

- [x] **Step 1: Add failing isolation tests**

Create synthetic replay days for two symbols. Assert that only the same symbol's rows with `result_date < signal_date` contribute, future or same-day outcome mutation does not alter historical evidence, and another symbol's profitable events never enter the score.

```python
report = build_first_board_stock_gene_ranking_report(
    days,
    history_window_days=252,
    min_d1_samples=1,
    top_n=1,
)
selection = report["variants"]["combined"]["selections"][0]
assert selection["stock_d1_sample_count"] == 2
assert selection["stock_d1_win_rate"] == 100.0
```

- [x] **Step 2: Implement a bounded matured-event index**

```python
@dataclass(frozen=True)
class _StockD1Event:
    signal_day_index: int
    result_date: str
    won: bool
    return_pct: float
```

Queue every replay first-board candidate by `result_date`. Before scoring day `D`, mature only queued rows whose result date is strictly earlier than `D`. Store an event only when it touched, sealed, and has a finite D+1 close net return. Filter the stock's events to `signal_day_index >= current_day_index - history_window_days`.

- [x] **Step 3: Attach transparent evidence**

```python
{
    "stock_gene_touch_count": prior_touch_count_126,
    "stock_gene_seal_count": prior_limit_count_126,
    "stock_gene_seal_rate": prior_seal_success_rate_126 * 100,
    "stock_d1_sample_count": len(events),
    "stock_d1_win_count": sum(event.won for event in events),
    "stock_d1_win_rate": win_count / sample_count * 100,
    "stock_d1_average_return_pct": mean(event.return_pct for event in events),
    "stock_gene_combined_win_rate": combined_rate,
}
```

Keep raw evidence for insufficient rows but set the combined rate to `None` and exclude them from the common ranking universe.

- [x] **Step 4: Re-run isolation and minimum-sample tests**

Expected: same-stock isolation, cutoff, mutation resistance, 252-day expiry, and sample threshold all pass.

### Task 3: Compare Equal-universe Top1 Variants

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_stock_gene_research.py`
- Modify: `tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

- [x] **Step 1: Add failing report-contract tests**

```python
assert set(report["variants"]) == {
    "baseline",
    "gene_only",
    "d1_only",
    "combined",
}
assert {
    payload["summary"]["trade_count"]
    for payload in report["variants"].values()
} == {2}
assert report["ranking_contract"]["top_n"] == 1
assert report["ranking_contract"]["secondary"] == "signal_time_asc"
```

- [x] **Step 2: Implement four frozen sort keys**

Baseline uses `pool_rank ASC`; gene-only uses `stock_gene_seal_rate DESC`; D1-only uses `stock_d1_win_rate DESC`; combined uses `stock_gene_combined_win_rate DESC`. Every tie uses `signal_time ASC, vt_symbol ASC`. Do not add current涨幅, entry-quality score, concept score, or generic analog evidence.

- [x] **Step 3: Implement comparable summaries**

Return for every variant: trade and day counts, win rate, average return, daily compounded return, drawdown, seal rate, hard-loss rate, profit factor proxy, validation-phase summaries, and compact selections. Coverage must report eligible candidates, five-sample-qualified candidates, evaluated days, no-pick days, and score distribution.

- [x] **Step 4: Run all new unit tests**

Expected: every variant selects the same count from the same daily universe and all tests pass.

### Task 4: Run Frozen Historical and Cash Research

**Files:**
- Create: `memory/06_backtests/limit_up_first_board_stock_gene_ranking_20260716.md`

- [x] **Step 1: Run primary and sensitivity reports**

Inside `alphaagent-api`, load `limit-up-history-v15` and run 252-day reports for minimum samples 5, 3, and 8. Use the five-sample run as primary; never switch the primary threshold after seeing outcomes.

- [x] **Step 2: Run equal-rule 14:30 cash accounts**

Use each primary variant's selections with `_account_market_data()`, `_attach_scheduled_exit_prices()`, and `CashBacktestConfig(initial_cash=100_000, max_positions=2)`. Run `simulate_limit_up_account(..., "next_1430", config)` and report fills, win rate, average return, total return, drawdown, hard-loss rate, and profit factor.

- [x] **Step 3: Apply the pre-frozen acceptance gate**

Promote only if the primary combined variant satisfies every condition:

- Locked-holdout Top1 win rate is not below equal-universe baseline.
- Locked-holdout average and compounded returns both exceed baseline.
- Locked-holdout drawdown is not worse by more than 2 percentage points.
- 14:30 total return and profit factor both exceed baseline.
- Direction does not reverse under both three-sample and eight-sample sensitivities.

Otherwise retain the evidence only and leave live execution order unchanged.

- [x] **Step 4: Write the evidence report**

Record the contract, coverage, variant and phase tables, sensitivities, 14:30 cash comparison, replacement attribution, limitations, and explicit promote/reject decision.

### Task 5: Verify and Maintain Project Memory

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run regressions**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_first_board_stock_gene_research.py tests/alphaagent/test_limit_up_first_board_profitability.py tests/alphaagent/test_limit_up_forward_validation.py -q`

Expected: all tests pass and existing live-v7 behavior remains unchanged.

- [x] **Step 2: Run static checks**

Run: `uv run --group server ruff check alphaagent/server/services/limit_up/first_board_stock_gene_research.py tests/alphaagent/test_limit_up_first_board_stock_gene_research.py`

Run: `python -m compileall -q alphaagent/server/services/limit_up/first_board_stock_gene_research.py`

Run: `git diff --check`

Expected: all commands exit successfully.

- [x] **Step 3: Update durable conclusions in place**

Link the new report from `memory/06_backtests/README.md`. Update `memory/09_decisions/decisions.md` with the frozen-gate decision, without erasing the earlier generic-analog experiment or claiming production promotion after a failed check.

- [x] **Step 4: Confirm production isolation**

Use `git diff --name-only` and verify no frontend file, live service, strategy version, scheduled execution module, or two-to-three code changed.
