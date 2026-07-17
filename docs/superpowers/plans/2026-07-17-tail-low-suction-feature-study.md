# Tail Low-suction Feature Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine which causally observable support, position, momentum and volume features distinguish successful from unsuccessful D-tail entries in main-rise leader-spell observation days when exiting just after D+1 10:30.

**Architecture:** Reuse the 369 event-recognized leader spells and their outcome-neutral S+1..S+4 main-rise observation days. A feature builder reads only D bars through the 14:50 close and D-1 daily support values; a separate cash executor enters at the 14:55 5-minute bar open and exits at the D+1 10:35 bar open, the first 5-minute execution proxy strictly after 10:30. A descriptive analyzer compares winners and losers and checks frozen single-feature groups across chronological development and validation blocks without selecting a combined trading rule.

**Tech Stack:** Python 3.11+, pandas, NumPy, SQLAlchemy, existing AlphaAgent event-neutral candidate and 5-minute data loaders, cash ledger, pytest, Ruff.

---

## Frozen Contract

- This is a feature-discovery study for tail entries, not a production rule search.
- The mother sample is every locally reconstructed event-neutral leader-spell observation day with `spell_session_offset` 1 through 4:
  - the stock was previously event-recognized inside the same `breakout_trend` concept cycle;
  - the D-1 concept cycle guard is still active;
  - no D return, D tail state or D+1 outcome selects the candidate;
  - the identity remains `event_recognition_proxy`, not strict historical concept Top3.
- Offset 5 is excluded before outcomes because its D+1 path falls outside the already complete S+1..S+5 minute window. Current coverage is 1,383 complete D/D+1 pairs out of 1,396 offset-1..4 candidates; incomplete pairs are reported and excluded without backfilling or outcome-dependent substitution.
- Five-minute timestamps are bar-close timestamps:
  - feature cutoff: D 14:50 close;
  - entry: D 14:55 bar open, after all features are fixed;
  - exit: D+1 10:35 bar open, the first 5-minute execution proxy after 10:30;
  - no D close, D+1 09:35..10:30 path or D+1 outcome may enter features.
- A D 14:55 entry at the reconstructed 10% limit-up price is `queue_unknown_without_l2` and is not counted as filled. Zero-volume/invalid entry bars are rejected.
- A D+1 10:35 exit at a one-price limit-down or zero-volume/invalid bar is unclosed; no later price replaces the fixed exit.
- Cash execution uses 100,000 yuan per independent signal, 100-share lots, 10 bps slippage, commission/minimum commission, transfer fee and sell stamp tax. Every filled trade is recomputed with double costs.
- `tail_success` means normal-cost net return strictly above zero. Zero and negative returns are failures. This label is attached only after the feature panel is frozen.
- Frozen causal numeric features:
  - D-1 distance to MA5/MA10/MA20 and D-1 distance from the 20-session high;
  - D 14:50 return from D-1 close, distance from D session high, day-range position, distance from D open, cumulative VWAP and MA5/MA10/MA20;
  - afternoon low distance from the morning low;
  - last-15-minute return and last-15-minute volume versus the prior afternoon mean.
- Frozen support/state fields:
  - above/below VWAP, MA5, MA10 and MA20;
  - morning low `held`, `false_break_reclaimed` or `broken_unrecovered`;
  - hierarchical support zone `above_vwap_and_ma5`, `below_vwap_above_ma5`, `ma5_to_ma10`, `ma10_to_ma20`, `below_ma20`;
  - count of broken supports among VWAP, MA5, MA10, MA20 and morning low;
  - fixed buckets for tail return, session drawdown, day-range position, late momentum, late volume, recognition rank, spell offset and GOLD/SILVER danger regime.
- Candidate dates use the existing five chronological blocks. Blocks 1-3 are descriptive development and blocks 4-5 are confirmation. No combined feature rule or threshold is selected in this study.
- A single feature group is `stable_positive` only when it has at least 30 trades/20 dates in development and 20 trades/15 dates in validation, beats the segment baseline win rate and mean return in both segments, and has positive double-cost mean in both. `high_win` additionally requires win rate above 55% in both segments.
- Reports preserve all groups, including low-win and failed groups, plus the largest winners and losers. GOLD/SILVER and rank are attribution only.
- Blocks 4-5 are reused history. Historical membership/security state remain incomplete. Formal rule, formal win rate, formal compounding and production eligibility remain `null`.
- No price after the frozen discovery end `2025-11-17` is read.

### Task 1: Causal 14:50 support feature panel

**Files:**
- Create: `alphaagent/server/services/low_suction/tail_feature_study.py`
- Create: `tests/alphaagent/services/low_suction/test_tail_feature_study.py`

- [x] **Step 1: Write failing feature and leakage tests**

Create synthetic D/D+1 5-minute paths and D-1 daily supports. Assert that the feature cutoff is exactly 14:50, the entry bar is absent from the feature values, morning support states distinguish held/false-break/unrecovered paths, support zones are hierarchical, and mutating 14:55 onward or all D+1 bars cannot change any feature.

```python
def test_tail_features_stop_at_1450_and_classify_support() -> None:
    features = build_tail_feature_panel(candidates, daily_bars, minute_bars)
    assert features.loc[0, "feature_cutoff_time"] == "14:50"
    assert features.loc[0, "morning_support_state"] == "false_break_reclaimed"
    assert features.loc[0, "support_zone"] == "below_vwap_above_ma5"

def test_1455_and_d1_mutations_cannot_change_tail_features() -> None:
    baseline = build_tail_feature_panel(candidates, daily_bars, minute_bars)
    changed = mutate_bars_at_or_after_1455_and_on_d1(minute_bars)
    repeated = build_tail_feature_panel(candidates, daily_bars, changed)
    pd.testing.assert_frame_equal(baseline, repeated)
```

- [x] **Step 2: Run the feature tests and confirm failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
```

Expected: collection fails because `tail_feature_study` does not exist.

- [x] **Step 3: Implement the frozen feature builder**

```python
TAIL_NUMERIC_FEATURES = (
    "context_distance_to_ma5_pct",
    "context_distance_to_ma10_pct",
    "context_distance_to_ma20_pct",
    "context_distance_from_20d_high_pct",
    "tail_return_from_previous_close_pct",
    "tail_drawdown_from_session_high_pct",
    "tail_range_position_pct",
    "tail_vs_open_pct",
    "tail_vs_vwap_pct",
    "tail_vs_ma5_pct",
    "tail_vs_ma10_pct",
    "tail_vs_ma20_pct",
    "afternoon_low_vs_morning_low_pct",
    "last_15m_return_pct",
    "last_15m_volume_ratio",
)

def build_tail_feature_panel(
    candidates: pd.DataFrame,
    daily_bars: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Freeze D-tail features at the completed 14:50 five-minute bar."""
```

Reject duplicate identities, incomplete D days and any input outcome columns. Attach five chronological blocks only after features are complete.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
uvx ruff check alphaagent/server/services/low_suction/tail_feature_study.py tests/alphaagent/services/low_suction/test_tail_feature_study.py
```

Expected: all pass.

### Task 2: Fixed tail entry and D+1 10:30 exit ledger

**Files:**
- Modify: `alphaagent/server/services/low_suction/tail_feature_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_tail_feature_study.py`

- [x] **Step 1: Write failing execution tests**

Assert entry uses the D 14:55 bar open, exit uses the D+1 10:35 bar open, normal and double costs are both present, limit-up entry is queue-unknown, one-price limit-down exit is unclosed, and success/failure is determined only from normal net return.

```python
def test_tail_execution_uses_1455_entry_and_first_bar_after_1030() -> None:
    ledger = execute_tail_trades(features, minute_bars)
    assert ledger.loc[0, "entry_time"].strftime("%H:%M") == "14:55"
    assert ledger.loc[0, "exit_time"].strftime("%H:%M") == "10:35"
    assert ledger.loc[0, "tail_success"] == (ledger.loc[0, "net_return_pct"] > 0)
```

- [x] **Step 2: Implement conservative cash execution**

```python
def execute_tail_trades(
    features: pd.DataFrame,
    daily_bars: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Enter at D 14:55 open and exit at D+1 10:35 open under fixed costs."""
```

Keep rejected, unclosed and closed rows in one ledger with explicit reasons. Never delay the fixed exit.

- [x] **Step 3: Prove outcome separation**

Add a spy/test that calls only `build_tail_feature_panel` and verifies D+1 prices are never accessed. Then call `execute_tail_trades` separately and verify the labels appear only in the returned ledger.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
uvx ruff check alphaagent/server/services/low_suction/tail_feature_study.py tests/alphaagent/services/low_suction/test_tail_feature_study.py
```

Expected: all pass.

### Task 3: Winner/loser profiles and single-feature confirmation

**Files:**
- Modify: `alphaagent/server/services/low_suction/tail_feature_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_tail_feature_study.py`

- [x] **Step 1: Write failing profile tests**

Assert continuous winner/loser medians retain both groups, categorical tables include every frozen group and time segment, segment baselines are explicit, stable-positive evaluation uses both segments, and no combined rule is selected.

```python
def test_feature_profiles_keep_successes_failures_and_rejected_groups() -> None:
    report = build_tail_feature_report(features, ledger, metadata)
    assert {row["outcome_group"] for row in report["numeric_profiles"]} == {
        "success",
        "failure",
    }
    assert report["formal_rule_selected"] is False
    assert report["formal_metrics"] is None
```

- [x] **Step 2: Implement descriptive feature tables**

```python
def build_numeric_success_failure_profiles(ledger: pd.DataFrame) -> pd.DataFrame:
    """Compare frozen continuous features without choosing thresholds."""

def build_categorical_feature_metrics(ledger: pd.DataFrame) -> pd.DataFrame:
    """Summarize every frozen state over all/development/validation/blocks."""

def evaluate_single_feature_groups(metrics: pd.DataFrame) -> dict[str, Any]:
    """Confirm only pre-bucketed single groups across both reused-history segments."""
```

Metrics include signals, closed trades, dates, win rate, mean/median, profit factor, double-cost mean, daily equal-weight compound return and maximum drawdown.

- [x] **Step 3: Add exhaustive report renderers**

```python
def build_tail_feature_report(
    features: pd.DataFrame,
    ledger: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Preserve coverage, profiles, all feature groups and winner/loser cases."""

def render_tail_feature_json(report: Mapping[str, Any]) -> str:
    return json.dumps(
        _json_safe(dict(report)),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"

def render_tail_feature_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# AlphaAgent 龙头尾盘低吸特征研究",
            "",
            f"结论：`{report['overall_conclusion']}`",
            f"正式规则/绩效：`null/null`",
            "",
        ]
    )
```

The Markdown lists baseline results, support-break results, stable/failed feature groups, the 20 largest winners and 20 largest failures, fingerprints and all proxy limitations.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_tail_feature_study.py -q
uvx ruff check alphaagent/server/services/low_suction/tail_feature_study.py tests/alphaagent/services/low_suction/test_tail_feature_study.py
```

Expected: all pass.

### Task 4: Real loader, CLI, evidence and durable conclusions

**Files:**
- Modify: `alphaagent/server/services/low_suction/tail_feature_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_tail_feature_study.py`
- Create: `memory/06_backtests/low_suction_tail_feature_study_20260717.md`
- Create: `memory/06_backtests/low_suction_tail_feature_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Implement discovery-boundary loader**

```python
def load_tail_feature_study_data() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Load S+1..S+4 candidates and exact D/D+1 5m pairs inside discovery."""

def run_tail_feature_study() -> dict[str, Any]:
    return build_tail_feature_report(*load_tail_feature_study_data())
```

Reuse `load_event_neutral_inputs`, query only exact candidate D and planned D+1 pairs, retain only pairs with all 48 bars on both days, record all exclusions, and assert maximum daily/minute date is no later than `2025-11-17`.

- [x] **Step 2: Register a parameter-free CLI**

Register `v2-tail-feature-study` with only `--format {json,markdown}` and `--output`. Do not expose entry/exit time, support threshold, feature or grouping switches.

- [x] **Step 3: Run real study and inspect all evidence**

```bash
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-tail-feature-study --format json \
  --output memory/06_backtests/low_suction_tail_feature_study_20260717.json
uv run python -m alphaagent.server.services.low_suction.cli \
  v2-tail-feature-study --format markdown \
  --output memory/06_backtests/low_suction_tail_feature_study_20260717.md
```

Inspect coverage, rejection reasons, baseline trade result, success/failure numeric profiles, every support state, development/validation consistency, GOLD/SILVER attribution and top/bottom cases before drawing a conclusion.

- [x] **Step 4: Update durable memory**

Record the report links and JSON SHA256. State which support features separated winners from failures, which failed confirmation, and that no formal rule exists. Replace the tail-feature open item rather than appending conflicting status.

- [x] **Step 5: Run full verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_tail_feature_study_20260717.json >/dev/null
git diff --check
```

Expected: all pass. Do not commit, push, restart the healthy API or read any price after the frozen discovery end.

## Self-Review

- Candidate selection is complete before D tail features or D+1 outcomes are read.
- Features stop at the 14:50 close; entry starts at the 14:55 open.
- The 10:30 request is represented as the first executable 5-minute open after 10:30, not a same-bar close lookahead.
- Support held, false-break/reclaim and unrecovered break are separate states.
- Winners and failures stay in the report; no winning-only filter becomes a rule.
- Offset 5 and incomplete D/D+1 paths are excluded by a data contract, not by return.
- Reused historical confirmation and proxy Top3 cannot become formal performance.
