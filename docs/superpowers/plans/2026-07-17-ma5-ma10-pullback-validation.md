# MA5/MA10 Pullback Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Validate whether a causal "first pullback uses D-1 MA5, second pullback uses D-1 MA10" entry has stable D+1 win rate and return inside stock-level main-rise event-leader spells.

**Architecture:** Add one isolated research module that labels pullback rounds from completed daily bars, extracts the first completed 5-minute touch-and-reclaim signal, reuses the existing cash/T+1 outcome engine, and compares the requested adaptive rule with three frozen moving-average controls. Keep strict Top3 and production metrics closed because the historical identity remains event-recognition Rank1-3 proxy evidence and blocks 4-5 have appeared in earlier research.

**Tech Stack:** Python 3.11, pandas, NumPy, SQLAlchemy, pytest, existing AlphaAgent low-suction loaders and cash execution.

---

## Frozen Research Contract

- Universe before the intraday signal:
  - Shanghai/Shenzhen main board only, inherited from the comparison-day builder.
  - Exact concept cycle is still in `main_rise` at D-1.
  - Historical leader identity is event-recognition Rank1-3 proxy, not strict point-in-time concept-member Top3.
  - Primary stock-level main-rise universe is D-1 `stock_trend_order`: `close >= MA5 > MA10 > MA20` inside concept main rise.
  - `concept_main_rise` and `stock_strong_main_rise` are nested sensitivity tables, not alternative rules selected after outcomes.
- Pullback-round state machine within one `leader_spell_id`:
  - Ignore the recognition day itself when counting pullbacks.
  - The first completed negative-return run after recognition is round 1.
  - A positive completed daily return is required to establish a rebound after a pullback; a zero return does not create a new round.
  - The next negative run after that rebound is round 2.
  - On a candidate day, an active completed negative run remains the same round; otherwise the next possible intraday decline is the next round.
  - Only rounds 1 and 2 enter this study. Round 3+ remains coverage evidence.
- Signal and execution:
  - All moving averages come from D-1 official close data.
  - A completed 5-minute bar must have `low_price <= reference_ma` and `close_price >= reference_ma`.
  - Buy at the next 5-minute bar open; never use the signal-bar close as an executable price.
  - Sell at the first sellable D+1 official close under the existing T+1, one-price-limit-down, fee, slippage, lot-size and double-cost contracts.
- Frozen arms:
  - `adaptive_ma5_ma10`: round 1 MA5, round 2 MA10.
  - `always_ma5`: both rounds MA5.
  - `always_ma10`: both rounds MA10.
  - `reversed_ma10_ma5`: round 1 MA10, round 2 MA5.
- Time split:
  - Blocks 1-3 are development diagnostics.
  - Blocks 4-5 are chronological validation diagnostics, but explicitly not untouched outer holdout.
- No threshold search, exit search, position sizing, market-regime filtering, or multi-factor combination is allowed in this task.

### Task 1: Pullback-round state and signal tests

**Files:**
- Create: `tests/alphaagent/services/low_suction/test_ma_pullback_study.py`

- [x] **Step 1: Write failing causal-round tests**

Test `build_pullback_round_panel()` with one spell whose completed post-recognition returns are negative, positive, negative, positive. Assert candidate rounds are `1, 1, 2, 2, 3`, the recognition-day return is ignored, zero return does not establish a rebound, and changing returns after a candidate context date cannot change that candidate's round.

- [x] **Step 2: Write failing 5-minute signal tests**

Construct complete 48-bar candidate days. Assert the adaptive arm uses MA5 for round 1 and MA10 for round 2, requires both touch and completed-bar reclaim, enters at the next bar open, emits at most one signal per event/arm, and does not change when later bars mutate.

- [x] **Step 3: Run focused tests and confirm failure**

Run:

```bash
uv run pytest tests/alphaagent/services/low_suction/test_ma_pullback_study.py -q
```

Expected: collection fails because `ma_pullback_study` does not exist.

### Task 2: Causal round and signal implementation

**Files:**
- Create: `alphaagent/server/services/low_suction/ma_pullback_study.py`
- Test: `tests/alphaagent/services/low_suction/test_ma_pullback_study.py`

- [x] **Step 1: Implement daily pullback-round labeling**

Add:

```python
def build_pullback_round_panel(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach D-1 stock trend features and a causal current pullback round."""
```

Use `build_stock_main_rise_features()` for D-1 trend gates. Compute daily return and D-1 volume-to-prior-five ratio from the full frozen calendar, merge only on `(vt_symbol, context_date)`, then run the frozen state machine independently within each `leader_spell_id`.

- [x] **Step 2: Implement frozen moving-average arms**

Add:

```python
ARM_REFERENCES = {
    "adaptive_ma5_ma10": {1: "ma5", 2: "ma10"},
    "always_ma5": {1: "ma5", 2: "ma5"},
    "always_ma10": {1: "ma10", 2: "ma10"},
    "reversed_ma10_ma5": {1: "ma10", 2: "ma5"},
}

def build_ma_pullback_signals(
    pullback_panel: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Extract the first causal touch-and-reclaim for each frozen arm."""
```

Build the existing point-in-time 5-minute panel, attach round/trend context after the base panel is frozen, calculate signal-time volume from the completed current bar and three completed prior bars, and select the first executable signal per event/arm.

- [x] **Step 3: Run focused round and signal tests**

Run the focused test file and expect all causal-round and signal tests to pass.

### Task 3: D+1 labels, metrics and hypothesis decision

**Files:**
- Modify: `alphaagent/server/services/low_suction/ma_pullback_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_ma_pullback_study.py`

- [x] **Step 1: Write failing outcome and metric tests**

Assert labels reuse the existing normal and double-cost D+1 cash execution. Assert metrics include all/development/validation/five individual blocks, equal-weight daily compounding and maximum drawdown, and preserve sample days independently from trade count.

- [x] **Step 2: Implement cohort membership and metrics**

Add fixed tables for arm comparison, pullback round, nested main-rise definition, daily volume, intraday volume, leader rank and GOLD/SILVER regime. Attribution tables may combine the already-frozen round with one attribution dimension, but must not feed back into rule selection.

- [x] **Step 3: Implement the decision gate**

Require minimum `30 trades/20 days` in development and `20 trades/15 days` in validation. A high-win historical candidate requires both segments to exceed 55% win rate, positive ordinary and double-cost means, and profit factor above 1. The requested adaptive arm must also beat all three frozen controls on validation win rate and double-cost mean before the report can claim an adaptive advantage.

- [x] **Step 4: Run focused tests**

Run the focused test file and expect all tests to pass.

### Task 4: Real-data loader, CLI and deterministic report

**Files:**
- Modify: `alphaagent/server/services/low_suction/ma_pullback_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_ma_pullback_study.py`

- [x] **Step 1: Write failing loader/report/CLI tests**

Assert JSON rejects NaN, Markdown states the causal definition and proxy boundary, the runner is injectable, and parser command `v2-ma-pullback-study` exposes only format/output controls.

- [x] **Step 2: Implement the loader**

Load the existing event-neutral comparison inputs and complete 5-minute candidate pairs. Validate exactly 48 bars per candidate day, assign chronological blocks, create normal/double-cost labels, and fingerprint candidates, rounds, minutes, signals and outcomes.

- [x] **Step 3: Implement report renderers and CLI**

Add `run_ma_pullback_study()`, deterministic JSON, concise Chinese Markdown, and the CLI branch. Keep `formal_metrics=None`, `formal_rule_selected=False`, `strict_historical_top3_claim=False`, and `late_segment_is_unseen_validation=False` regardless of historical result.

- [x] **Step 4: Run focused tests, Ruff and compile checks**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_ma_pullback_study.py -q
uvx ruff check alphaagent/server/services/low_suction/ma_pullback_study.py tests/alphaagent/services/low_suction/test_ma_pullback_study.py alphaagent/server/services/low_suction/cli.py
uv run python -m compileall -q alphaagent/server/services/low_suction/ma_pullback_study.py
```

Expected: all pass.

### Task 5: Execute study and preserve evidence

**Files:**
- Create: `memory/06_backtests/low_suction_ma5_ma10_pullback_study_20260717.md`
- Create: `memory/06_backtests/low_suction_ma5_ma10_pullback_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Generate deterministic artifacts**

```bash
uv run python -m alphaagent.server.services.low_suction.cli v2-ma-pullback-study --format markdown --output memory/06_backtests/low_suction_ma5_ma10_pullback_study_20260717.md
uv run python -m alphaagent.server.services.low_suction.cli v2-ma-pullback-study --format json --output memory/06_backtests/low_suction_ma5_ma10_pullback_study_20260717.json
```

- [x] **Step 2: Inspect the result before writing conclusions**

Compare adaptive vs all controls in development and validation, then compare round 1 vs round 2. Treat volume, rank and GOLD/SILVER as attribution only. Explicitly report sample size, days, win rate, ordinary/double-cost mean, profit factor, compound return and drawdown.

- [x] **Step 3: Update durable memory in place**

Add only current conclusions, evidence links, rule status and actionable next work. Do not duplicate raw tables from the artifacts.

- [x] **Step 4: Run full low-suction regression checks**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/services/scheduler -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_ma5_ma10_pullback_study_20260717.json >/dev/null
git diff --check
```

Expected: all pass. Commits are intentionally omitted because repository instructions require explicit user authorization.

## Self-Review

- Spec coverage: first/second pullback, MA5/MA10, stock main rise, main-board/Top3 proxy, D+1 outcome, volume, GOLD/SILVER and leader rank are all represented.
- Leakage boundary: round labels use only completed D-1 daily bars; signals use only the completed 5-minute bar; outcomes attach after signal identity is frozen.
- Search boundary: four arms and all thresholds are frozen before real outcomes are loaded; attribution cannot select the rule.
- Known limitation: the available historical identity is not strict point-in-time concept-member Top3 and blocks 4-5 are reused diagnostics, so no production rule can be promoted in this task.
