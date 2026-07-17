# Low-suction Stock Main-rise Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether the prior low-suction study failed because it identified only concept main-rise rather than stock-level main-rise, by testing causal D-open-to-D+1-close hold baselines and the moving-average location of the existing intraday entries.

**Architecture:** Reuse the frozen 1,770 event-recognition comparison days and attach stock features known at D-1 close. Evaluate four nested, outcome-independent trend gates with one shared next-open/D+1-close cash execution, then join the already frozen 1,283 low-suction trades to the same D-1 features and classify their signal price relative to MA5/MA10/MA20. Development blocks 1-3 and validation blocks 4-5 remain unchanged; the outer holdout and strict historical Top3 remain unread.

**Tech Stack:** Python 3.11+, pandas, NumPy, existing low-suction daily cash outcomes, SQLAlchemy/PostgreSQL, pytest.

**Repository constraints:** Do not modify `vnpy/`, official examples,打板 strategy/ledger code, the prior low-suction entry rule, or either existing JSON evidence artifact. Do not tune MA periods, slopes, high-distance thresholds, or gates after reading outcomes. Do not commit or push without explicit user authorization.

---

## Frozen Research Contract

- Candidate identity: the existing outcome-group comparison candidate, one stock/day after collision handling.
- Feature cutoff: D-1 close (`context_date`) only.
- Required stock features: close, MA5/MA10/MA20, each MA shifted three sessions, 5/10/20-session returns, 20-session high, and distance from that high.
- Nested definitions:
  - `concept_main_rise`: exact D-1 concept cycle remains active.
  - `stock_above_ma5`: concept main-rise and D-1 stock close is at or above MA5.
  - `stock_trend_order`: previous gate plus `MA5 > MA10 > MA20`.
  - `stock_strong_main_rise`: previous gate plus MA5/MA10/MA20 each above its three-session-prior value, 10-session return above zero, and close no more than 5% below the 20-session high.
- Hold baseline: signal at D-1 close, buy D open, sell D+1 close using 100,000 CNY, 100-share lots, normal costs and 2x costs, suspension/limit-up entry checks, and limit-down exit checks.
- Baseline labels:
  - `high_win_baseline`: at least 30 closed trades and 20 dates, win rate strictly above 60%, positive mean, PF above 1, and positive 2x-cost mean.
  - `positive_baseline`: same sample gate, win rate strictly above 50%, positive mean, PF above 1, and positive 2x-cost mean.
  - otherwise `not_positive_baseline` or `insufficient_sample`.
- Time split: blocks 1-3 development and blocks 4-5 validation, plus all five block rows. A definition is stable only when the same label is at least `positive_baseline` in both development and validation.
- Existing low-suction signal MA zone uses D-1 frozen MAs and the 5m signal close:
  - `above_ma5`, `ma5_to_ma10`, `ma10_to_ma20`, `below_ma20`, or `unordered_mas`.
- The low-suction rule, fill, D+1 exit, costs, and outcomes are not recalculated or selected from MA zones; MA zones are attribution only.
- Formal strategy metrics, selected main-rise definition, cash compounding, and outer holdout remain `null`.
- Pre-breakout/emotion anticipation is a separate future plan and is prohibited from this report.

### Task 1: Build D-1 Stock Trend Features

**Files:**
- Create: `alphaagent/server/services/low_suction/stock_main_rise_audit.py`
- Create: `tests/alphaagent/services/low_suction/test_stock_main_rise_audit.py`

- [x] **Step 1: Write failing point-in-time feature tests**

Test exact MA/return/high calculations, sparse-session rejection, D-1 candidate joins, nested state monotonicity, and future mutation invariance:

```python
features = build_stock_main_rise_features(
    candidates,
    daily_bars,
    trading_dates=trading_dates,
)
row = features.iloc[0]
assert row["stock_strong_main_rise"]
assert row["stock_strong_main_rise"] <= row["stock_trend_order"]
assert row["stock_trend_order"] <= row["stock_above_ma5"]
```

- [x] **Step 2: Run the test and verify the module is missing**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_stock_main_rise_audit.py -q
```

Expected: import failure for `stock_main_rise_audit`.

- [x] **Step 3: Implement the pure feature builder**

Implement `build_stock_main_rise_features(candidates, daily_bars, *, trading_dates)` with each symbol reindexed to the frozen trading calendar before chronological rolling windows are calculated. Merge only the row whose `trade_date == context_date`, reject duplicated identities and prohibited outcome/future columns, and emit all four boolean definitions plus numeric diagnostics.

- [x] **Step 4: Run scoped tests**

Expected: all point-in-time and hierarchy tests pass.

### Task 2: Execute The Shared Hold Baseline

**Files:**
- Modify: `alphaagent/server/services/low_suction/stock_main_rise_audit.py`
- Modify: `tests/alphaagent/services/low_suction/test_stock_main_rise_audit.py`

- [x] **Step 1: Write failing causal execution tests**

Construct an event at D-1 close and prove entry occurs at D open, exit at D+1 close, normal/2x cost monotonicity, limit-up rejection, and no outcome column enters the feature builder:

```python
normal, stressed = execute_stock_main_rise_hold(features, daily_bars, trading_dates=calendar)
assert normal.iloc[0]["entry_date"] == d_date
assert normal.iloc[0]["exit_date"] == d_plus_1
assert stressed.iloc[0]["net_return_pct"] < normal.iloc[0]["net_return_pct"]
```

- [x] **Step 2: Verify the new function is missing**

Run the scoped test and expect an import/attribute failure.

- [x] **Step 3: Reuse the existing daily cash outcome contract**

Create one event per candidate at `context_date`, prepare 10cm limit prices and suspension flags from daily bars, call `generate_daily_proxy_outcomes()` for normal and 2x costs, and retain only `entry_plus_1_close`. Do not duplicate cash arithmetic.

- [x] **Step 4: Implement baseline metrics and fixed qualification labels**

Emit development, validation, all, and block 1-5 rows for each nested definition with signals, closed trades, dates, win, mean, median, PF, 5% tail and 2x-cost metrics. Test strict 50%/60% boundaries and unchanged definition identity across segments.

- [x] **Step 5: Run scoped tests**

Expected: execution and metric tests pass.

### Task 3: Attribute Existing Low-suction Entries By MA Zone

**Files:**
- Modify: `alphaagent/server/services/low_suction/outcome_group_study.py`
- Modify: `alphaagent/server/services/low_suction/stock_main_rise_audit.py`
- Modify: `tests/alphaagent/services/low_suction/test_stock_main_rise_audit.py`

- [x] **Step 1: Allow the outcome-group loader to reuse preloaded inputs**

Change the loader signature without changing default behavior:

```python
def load_outcome_group_study_data(
    inputs: EventNeutralInputs | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    selected_inputs = inputs or load_event_neutral_comparison_inputs()
```

Add a regression test or retain all existing outcome-group tests unchanged.

- [x] **Step 2: Write failing MA-zone tests**

Test every exact boundary, ensure `unordered_mas` cannot masquerade as a pullback zone, and prove future stock bars cannot alter an existing signal zone:

```python
attributed = attach_signal_ma_zones(trades, features)
assert set(attributed["signal_ma_zone"]) == {
    "above_ma5", "ma5_to_ma10", "ma10_to_ma20", "below_ma20", "unordered_mas"
}
```

- [x] **Step 3: Implement attribution and metrics**

Join by immutable `event_id`, classify with the signal 5m `close_price`, and summarize the frozen normal/2x D+1 outcomes by zone, D-1 definition, development/validation and each time block. Do not create an order-generation function.

- [x] **Step 4: Run both scoped test files**

Expected: outcome-group and stock-main-rise tests pass.

### Task 4: Report, CLI, And Real Run

**Files:**
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `alphaagent/server/services/low_suction/stock_main_rise_audit.py`
- Modify: `tests/alphaagent/services/low_suction/test_stock_main_rise_audit.py`

- [x] **Step 1: Test a frozen CLI surface**

Add `v2-stock-main-rise-audit` with only `--format` and `--output`; assert there are no MA periods, slope windows, high-distance, dates, outcome or entry parameters.

- [x] **Step 2: Build JSON and Markdown reports**

Include the frozen contract, coverage, fingerprints, definition prevalence, every hold-baseline metric, every low-suction MA-zone metric, qualification labels, safety flags and a bounded conclusion. Allowed conclusions are `stock_main_rise_baseline_confirmed`, `concept_only_not_stock_main_rise`, and `no_stock_main_rise_baseline_in_proxy`.

- [x] **Step 3: Run the real audit once**

Use the one-off `alphaagent-api` container and write `memory/06_backtests/low_suction_stock_main_rise_audit_20260717.json`. Render Markdown from the same machine report.

### Task 5: Evidence And Verification

**Files:**
- Create: `memory/06_backtests/low_suction_stock_main_rise_audit_20260717.json`
- Create: `memory/06_backtests/low_suction_stock_main_rise_audit_20260717.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-17-low-suction-stock-main-rise-baseline.md`

- [x] **Step 1: Record bounded findings**

State whether any stock definition has a stable positive/high-win hold baseline, how many prior low-suction trades entered below MA5/MA10/MA20, and whether moving-average breaks explain the prior negative result. Keep strict Top3 and formal performance `null`.

- [x] **Step 2: Define the next decision without implementing it**

If a stock definition is stable, freeze it for a separate pullback-entry plan. If none is stable, reject the proxy universe as a main-rise research base. In either case, leave pre-breakout anticipation for a separate plan with its own point-in-time emotion definition.

- [x] **Step 3: Run final verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
git diff --check
```

Verify the previous two low-suction JSON SHA256 values, 1m row count, outer-holdout flag, current-member read count and limit-up strategy read count remain unchanged.

## Completion Boundary

Completion means there is a causal answer to whether stock-level main-rise was missing and whether the old low-suction entries broke D-1 moving averages. It does not select a production main-rise definition, test a new pullback entry, implement pre-breakout anticipation, or unlock strict Top3 performance.
