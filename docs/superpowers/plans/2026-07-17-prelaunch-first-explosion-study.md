# Prelaunch First Explosion Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether D-1 stock trend, position, volume, turnover and volatility can identify a verified first strong explosion on D across the full main-board stock-day universe, then conditionally evaluate D-open to D+1-close returns without selecting on trade outcomes.

**Architecture:** A universe module builds one causal D-1 feature row for every eligible main-board stock and event-covered date, with no future event or return columns. A separate study module attaches exact active-main-rise event labels, fits one bounded sklearn classification tree on blocks 1-3, freezes one development leaf, validates it on blocks 4-5, and only calls the existing cash execution path when the label gate passes.

**Tech Stack:** Python 3.11+, pandas, NumPy, scikit-learn `DecisionTreeClassifier`, SQLAlchemy, existing AlphaAgent concept-cycle, event-reason, timing, chronological-block, daily cash execution and report helpers, pytest, Ruff.

---

## Frozen Contract

- This is an independent prelaunch/pre-positioning proxy study, not another recognized-leader pullback rule.
- The candidate denominator is every locally available沪深主板 stock-day on dates with observed limit-pool reason coverage. It does not start from future winners or current concept members.
- Current stock names are used only as a reconstructed ST/delisting exclusion. Historical security state and D-1 concept membership remain unavailable, so no result is strict Top3 or formal performance.
- A target day D is eligible only when:
  - the symbol is SSE/SZSE main board under the shared universe prefixes;
  - at least 60 prior stock sessions exist;
  - the prior 10 completed sessions contain no daily return at or above 5%;
  - all frozen D-1 features are complete;
  - a D official daily bar exists for outcome availability, but no D field enters the feature table.
- Frozen D-1 features:
  - 1/3/5/10-session return;
  - distance to MA5/MA10/MA20;
  - distance from the 20-session high;
  - D-1 volume divided by the preceding five-session mean;
  - five-session mean volume divided by 20-session mean volume;
  - log of 20-session median real turnover;
  - 10-session daily-return volatility.
- The positive label is `verified_first_explosion`:
  - D has an exact stock-event reason relation to a `breakout_trend` concept active on D;
  - D daily return is at least 5%;
  - the universe precondition already proves no prior 5% day in ten sessions.
- All other rows mean `not_verified_by_available_event_evidence`, not proven true negatives. Reports must state this label-noise boundary.
- D-1 GOLD/SILVER/NORMAL and danger state are attribution fields only, never tree features or separate rules.
- Chronological split is the existing five equal event-date blocks. Blocks 1-3 are development; blocks 4-5 are validation. No outer holdout is read.
- Discovery uses exactly one `DecisionTreeClassifier` with:
  - `max_depth=2`;
  - `min_samples_leaf=1000`;
  - `class_weight="balanced"`;
  - `random_state=0`;
  - the 12 frozen numeric features and no parameter CLI.
- Persist every leaf attempt. A development leaf is eligible only with at least 1,000 rows, 30 verified positives, 30 dates, positive recall at least 5%, precision lift at least 2.0 and universe coverage no greater than 10%. Select exactly one by precision lift descending, positive count descending, coverage ascending, leaf id ascending.
- The frozen leaf passes validation only with at least 500 rows, 15 verified positives, 20 dates, positive recall at least 2.5%, precision above the validation base rate, precision lift at least 1.5 and coverage no greater than 10%.
- If no development leaf or validation fails, stop before D-open/D+1-close execution and set `trade_outcomes_read=false`.
- If validation passes, apply the same frozen leaf to all universe rows, buy at D official open and exit at the first sellable D+1 official close under normal and double costs. Do not select or modify the leaf using these returns.
- Blocks 4-5 and any conditional trade results are reused historical diagnostics, not untouched validation or formal strategy performance.

### Task 1: Full-universe causal D-1 features

**Files:**
- Create: `alphaagent/server/services/low_suction/prelaunch_universe.py`
- Create: `tests/alphaagent/services/low_suction/test_prelaunch_universe.py`

- [x] **Step 1: Write failing universe tests**

Construct main-board and excluded-board symbols across a synthetic calendar. Assert one row per eligible `(entry_date, vt_symbol)`, 60-session and prior-strong guards, exact feature values, current-name proxy exclusions, and absence of D OHLCV/event/return outcome fields.

- [x] **Step 2: Confirm the module is missing**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_prelaunch_universe.py -q
```

Expected: collection fails because `prelaunch_universe` does not exist.

- [x] **Step 3: Implement the feature panel**

```python
PRELAUNCH_FEATURES = (
    "return_1d_pct",
    "return_3d_pct",
    "return_5d_pct",
    "return_10d_pct",
    "distance_to_ma5_pct",
    "distance_to_ma10_pct",
    "distance_to_ma20_pct",
    "distance_from_20d_high_pct",
    "volume_ratio_1d_to_prior5",
    "volume_ratio_5d_to_20d",
    "log_turnover_median_20d",
    "volatility_10d_pct",
)

def build_prelaunch_feature_panel(
    stock_bars: pd.DataFrame,
    *,
    target_dates: Sequence[date],
) -> pd.DataFrame:
    """Build full-universe D-1 features with no D market values exposed."""
```

The returned identity includes `event_id`, `context_date`, `entry_date`, `vt_symbol`, current-name evidence level, prior-session count, prior strong-day count and the 12 features. Every feature row is computed at D-1 and then mapped to D.

- [x] **Step 4: Prove no future leakage**

Mutate all D and later OHLCV/turnover values for one target date and assert that date's feature row is unchanged. Add prohibited columns and assert the builder rejects them.

- [x] **Step 5: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_prelaunch_universe.py -q
uvx ruff check alphaagent/server/services/low_suction/prelaunch_universe.py tests/alphaagent/services/low_suction/test_prelaunch_universe.py
```

Expected: all pass.

### Task 2: Exact main-rise first-explosion labels

**Files:**
- Create: `alphaagent/server/services/low_suction/prelaunch_first_explosion_study.py`
- Create: `tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py`

- [x] **Step 1: Write failing separated-label tests**

Build exact event relations, active/inactive concept cycles and D returns. Assert only exact active `breakout_trend` relations with D return at least 5% become positive, duplicate concepts collapse to one stock-day, negative rows are named `not_verified_by_available_event_evidence`, and feature inputs cannot contain label/outcome fields.

- [x] **Step 2: Implement label attachment**

```python
def attach_verified_first_explosion_labels(
    features: pd.DataFrame,
    exact_relations: pd.DataFrame,
    cycle_states: pd.DataFrame,
    stock_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Attach post-D verified event labels after causal features are frozen."""
```

Add `verified_first_explosion`, `label_status`, verified concept count/names and D return only to the labeled ledger, never the feature builder output.

- [x] **Step 3: Add chronological blocks and D-1 timing attribution**

```python
def attach_prelaunch_context(
    labels: pd.DataFrame,
    timing_context: pd.DataFrame,
) -> pd.DataFrame:
    """Attach five blocks and D-1 market regime fields for attribution only."""
```

- [x] **Step 4: Run focused label tests**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py -q
```

Expected: all pass.

### Task 3: Bounded tree discovery and frozen validation gate

**Files:**
- Modify: `alphaagent/server/services/low_suction/prelaunch_first_explosion_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py`

- [x] **Step 1: Write failing tree and leaf-ledger tests**

Assert depth at most two, conditions at most two, validation extremes cannot change thresholds, every leaf is persisted, only one development leaf can be selected, and rejected leaves retain explicit reasons.

- [x] **Step 2: Implement deterministic discovery**

```python
@dataclass(frozen=True)
class PrelaunchCondition:
    feature: str
    operator: str
    threshold: float

@dataclass(frozen=True)
class PrelaunchRule:
    rule_id: str
    conditions: tuple[PrelaunchCondition, ...]

def discover_prelaunch_rule(labels: pd.DataFrame) -> PrelaunchDiscoveryResult:
    """Fit on blocks 1-3 and freeze at most one eligible leaf."""
```

- [x] **Step 3: Write failing validation-gate tests**

Assert validation applies the frozen conditions without refitting, uses validation base prevalence for lift, and returns `validated_prelaunch_label_edge` only when every frozen validation gate passes.

- [x] **Step 4: Implement rule application and evaluation**

```python
def apply_prelaunch_rule(labels: pd.DataFrame, rule: PrelaunchRule) -> pd.DataFrame:
    """Apply the frozen conjunction without reading trade outcomes."""

def evaluate_prelaunch_rule(
    labels: pd.DataFrame,
    discovery: PrelaunchDiscoveryResult,
) -> dict[str, Any]:
    """Evaluate the selected leaf on blocks 4-5 and decide the trade gate."""
```

- [x] **Step 5: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py -q
uvx ruff check alphaagent/server/services/low_suction/prelaunch_first_explosion_study.py tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py
```

Expected: all pass.

### Task 4: Conditional D-open/D+1-close trade diagnostic and report

**Files:**
- Modify: `alphaagent/server/services/low_suction/prelaunch_first_explosion_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py`

- [x] **Step 1: Write failing conditional execution tests**

Use a spy runner to prove trade execution is not called when discovery or validation fails. When it passes, assert all rule hits, including non-positive labels, enter the same D-open/D+1-close cash path under normal and double costs.

- [x] **Step 2: Implement conditional trade diagnostics**

```python
def execute_prelaunch_trade_gate(
    labels: pd.DataFrame,
    discovery: PrelaunchDiscoveryResult,
    evaluation: Mapping[str, Any],
    stock_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> dict[str, Any]:
    """Read trade outcomes only after the label-validation gate passes."""
```

Return all/development/validation/block metrics with signals, closed trades, days, win rate, mean/median, profit factor, double-cost mean, daily compound return and maximum drawdown. The rule remains selected by label lift, never by these metrics.

- [x] **Step 3: Implement real-data loader, deterministic report and CLI**

```python
def run_prelaunch_first_explosion_study() -> dict[str, Any]:
    """Run the full-universe prelaunch study inside the discovery boundary."""

def render_prelaunch_first_explosion_json(report: Mapping[str, Any]) -> str:
    ...

def render_prelaunch_first_explosion_markdown(report: Mapping[str, Any]) -> str:
    ...
```

Register `v2-prelaunch-first-explosion-study` with only `--format` and `--output`. Persist coverage, label prevalence, all leaf attempts, selected rule, validation metrics, GOLD/SILVER attribution, optional trade metrics, fingerprints, the feature/label boundary and explicit proxy limitations.

- [x] **Step 4: Run focused report and CLI tests**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_prelaunch_universe.py tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py -q
uvx ruff check alphaagent/server/services/low_suction/prelaunch_universe.py alphaagent/server/services/low_suction/prelaunch_first_explosion_study.py alphaagent/server/services/low_suction/cli.py tests/alphaagent/services/low_suction/test_prelaunch_universe.py tests/alphaagent/services/low_suction/test_prelaunch_first_explosion_study.py
```

Expected: all pass.

### Task 5: Execute real study and preserve evidence

**Files:**
- Create: `memory/06_backtests/low_suction_prelaunch_first_explosion_study_20260717.md`
- Create: `memory/06_backtests/low_suction_prelaunch_first_explosion_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Generate Markdown and JSON**

```bash
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-prelaunch-first-explosion-study --format markdown \
  --output memory/06_backtests/low_suction_prelaunch_first_explosion_study_20260717.md
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-prelaunch-first-explosion-study --format json \
  --output memory/06_backtests/low_suction_prelaunch_first_explosion_study_20260717.json
```

- [x] **Step 2: Inspect before concluding**

Report universe rows/days/symbols, verified positives and base rate by block, every leaf's development statistics and rejection reason, the frozen rule, validation signals/positives/days/precision/recall/lift/coverage, timing-regime attribution, whether trade outcomes were read, and conditional trade metrics if present.

- [x] **Step 3: Update durable memory**

Link both artifacts, record JSON SHA256, replace the prelaunch open-work item with the current evidence, and preserve the non-strict-member, current-name and event-label-noise limitations.

- [x] **Step 4: Run full verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_prelaunch_first_explosion_study_20260717.json >/dev/null
git diff --check
```

Expected: all pass. Do not commit, push, restart the healthy API or read prices after the frozen discovery end.

## Self-Review

- The denominator is full main-board stock-days, not future event winners.
- The absence of a verified event means unverified, not a proven negative.
- D and later values cannot enter the 12 feature columns.
- Development chooses one leaf before validation; validation cannot select a backup leaf.
- Trade outcomes are behind the label-validation gate and cannot choose or alter the leaf.
- Historical concept membership is not reconstructed from future event reasons; positive relations are outcome labels only.
