# Individual Main-rise Leader Spell Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible, stock-by-stock evidence ledger for every event-recognized leader spell, inspect real main-rise trajectories and same-day/same-concept contrasts, and report bounded structural findings before defining another low-suction rule.

**Architecture:** Keep point-in-time identity/features physically separate from future trajectory labels. Use one `(sector_id, cycle_id, vt_symbol)` leader spell as the research unit, preserve every real stock name/date/concept, then attach S+1..S+5 outcomes only in a downstream attribution step. The current event-recognition universe remains an explicitly incomplete Top3 proxy; the study can discover hypotheses but cannot promote a formal strategy or claim strict historical leader coverage.

**Tech Stack:** Python 3.13, pandas, NumPy, existing AlphaAgent low-suction loaders, pytest, Ruff, Docker Compose.

---

## Fixed Research Contract

- Research unit: earliest raw recognition candidate for each `(sector_id, cycle_id, vt_symbol)`; `leader_spell_id` is built from that exact identity before neutral-day collision removal.
- Recognition date: `recognition_source_date` (`S`), known after that session closes.
- Point-in-time feature cutoff: `S` close. No S+1 price, old low-suction outcome, D+1 return, or winner/loser label may enter feature construction.
- Individual history window: `S-20..S`; descriptive future path: `S+1..S+5`.
- Universe: all event-recognized leader spells, not only spells that later produce the old 09:50 pullback signal.
- Identity evidence: `vt_symbol`, `stock_name`, `sector_id`, `concept_name`, `recognition_rank`, recognition date, spell ID and regime known at S close.
- Structural descriptors: stock returns, return acceleration, MA separation, distance from prior high, volume ratio, near-limit-up count, close location, concept-relative return and market-relative return.
- Outcome labels: forward close return, forward maximum close return and forward maximum drawdown. Labels are attribution only.
- Case selection: deterministic top/bottom outcome tails plus same-recognition-date/same-concept winner-loser pairs. No hand-picked examples.
- Formal Top3, production entry, formal performance, compounding, position sizing and outer holdout remain closed.
- Repository instruction overrides the skill's normal commit cadence: do not run `git commit` or `git push`.

### Task 1: Freeze Real Leader-spell Identities

**Files:**
- Create: `alphaagent/server/services/low_suction/individual_leader_study.py`
- Create: `tests/alphaagent/services/low_suction/test_individual_leader_study.py`

- [ ] **Step 1: Write failing identity tests**

```python
def test_build_spell_identities_keeps_one_real_stock_per_spell() -> None:
    rows = build_spell_identities(_recognition_candidates())
    assert rows["leader_spell_id"].is_unique
    assert rows.loc[0, "vt_symbol"] == "600001.SSE"
    assert rows.loc[0, "stock_name"] == "甲公司"
    assert rows.loc[0, "recognition_source_date"] == pd.Timestamp("2025-01-10")


def test_build_spell_identities_uses_earliest_raw_recognition() -> None:
    rows = build_spell_identities(_recognition_candidates())
    assert rows.loc[0, "recognition_event_id"] == 10
    assert rows.loc[0, "recognition_source_date"] == pd.Timestamp("2025-01-10")


def test_spell_identity_rejects_conflicting_stock_names() -> None:
    candidates = _recognition_candidates()
    candidates.loc[1, "stock_name"] = "错误名称"
    with pytest.raises(ValueError, match="conflicting spell identity"):
        build_spell_identities(candidates)
```

- [ ] **Step 2: Run the identity tests and verify they fail**

Run:

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  pytest tests/alphaagent/services/low_suction/test_individual_leader_study.py -q
```

Expected: collection or import failure because `individual_leader_study.py` does not exist.

- [ ] **Step 3: Implement identity construction**

Create these public constants and function:

```python
SPELL_IDENTITY_COLUMNS = (
    "leader_spell_id",
    "recognition_event_id",
    "recognition_source_date",
    "sector_id",
    "concept_name",
    "cycle_id",
    "vt_symbol",
    "stock_name",
    "recognition_rank",
    "relative_percentile",
    "limit_times",
    "limit_up_suc_rate",
    "seal_strength",
    "amount",
    "active_direction",
    "danger_state",
    "market_phase",
    "rank_mode",
    "evidence_level",
)


def build_spell_identities(candidates: pd.DataFrame) -> pd.DataFrame:
    """Return the earliest raw recognition row for every leader spell."""
```

Implementation requirements:

- Validate required columns and prohibit outcome/future columns.
- Normalize dates and identity strings.
- Build `leader_spell_id` as `sector_id:cycle_id:vt_symbol` before any cross-concept neutral-day collision logic.
- Verify every repeated identity has identical stock/concept/cycle identity, then select the earliest `(source_date, event_id)` row and require one row per spell.
- Sort by recognition date, concept, recognition rank and symbol.

- [ ] **Step 4: Run the identity tests and verify they pass**

Run the command from Step 2. Expected: all identity tests pass.

### Task 2: Build Point-in-time Stock and Concept Trajectories

**Files:**
- Modify: `alphaagent/server/services/low_suction/individual_leader_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_individual_leader_study.py`

- [ ] **Step 1: Add failing causality and trajectory tests**

```python
def test_pre_recognition_features_use_only_bars_through_s_close() -> None:
    baseline = build_spell_feature_ledger(
        _spell_identities(), _stock_bars(), _concept_bars(), _market_returns(),
        trading_dates=_calendar(),
    )
    mutated = _stock_bars()
    mutated.loc[mutated["trade_date"] > date(2025, 1, 10), "close_price"] = 999
    changed = build_spell_feature_ledger(
        _spell_identities(), mutated, _concept_bars(), _market_returns(),
        trading_dates=_calendar(),
    )
    pd.testing.assert_frame_equal(baseline, changed)


def test_trajectory_keeps_real_daily_rows_and_offsets() -> None:
    trajectory = build_spell_trajectories(
        _spell_identities(), _stock_bars(), _concept_bars(), _market_returns(),
        trading_dates=_calendar(), history_sessions=20, future_sessions=5,
    )
    assert trajectory["session_offset"].tolist() == list(range(-20, 6))
    assert trajectory.loc[trajectory["session_offset"].eq(0), "known_at_s_close"].item()
    assert not trajectory.loc[trajectory["session_offset"].gt(0), "known_at_s_close"].any()
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run the Task 1 test command. Expected: failures for missing feature and trajectory functions.

- [ ] **Step 3: Implement the S-close feature ledger**

Add:

```python
def build_spell_feature_ledger(
    spells: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach only S-close and earlier structural descriptors to each spell."""
```

For each spell, calculate without outcome-driven thresholds:

- `stock_return_3d_pct`, `stock_return_5d_pct`, `stock_return_10d_pct`, `stock_return_20d_pct`.
- `prior_5d_return_pct` and `return_acceleration_5d_pct`.
- `ma5_gap_pct`, `ma10_gap_pct`, `ma20_gap_pct`, `ma5_over_ma10_pct`, `ma10_over_ma20_pct`.
- `distance_from_prior_20d_high_pct`; the prior high must exclude S close.
- `volume_to_prior_5d_ratio` and `volume_to_prior_20d_ratio`; both denominators exclude S volume.
- `near_limit_up_days_10d` using prior-close return `>=9.5%`, only as a main-board descriptive proxy.
- `days_since_near_limit_up` within the available 20-session history.
- `close_location_value` for S: `(close-low)/(high-low)`, null when the range is zero.
- `concept_return_5d_pct`, `concept_return_10d_pct` and stock-minus-concept excess returns.
- `market_return_5d_pct`, `market_return_10d_pct` and stock-minus-market excess returns.
- `feature_complete` and a concrete `feature_status` reason.

Reject duplicate stock/date and concept/date rows. Preserve actual identity columns in every output row.

- [ ] **Step 4: Implement full individual trajectories**

Add:

```python
def build_spell_trajectories(
    spells: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
    history_sessions: int = 20,
    future_sessions: int = 5,
) -> pd.DataFrame:
    """Return S-20..S+5 rows for charting and individual inspection."""
```

Each row must contain spell identity, actual date, session offset, stock OHLCV, daily return, cumulative return from S close, concept and market daily/cumulative returns, and `known_at_s_close`. Missing calendar rows must remain explicit with `row_status="missing_bar"`.

- [ ] **Step 5: Run the tests and verify they pass**

Run the Task 1 test command. Expected: all tests pass.

### Task 3: Attach Future Labels and Deterministic Individual Comparisons

**Files:**
- Modify: `alphaagent/server/services/low_suction/individual_leader_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_individual_leader_study.py`

- [ ] **Step 1: Add failing label-boundary and pairing tests**

```python
def test_outcome_labels_are_built_after_feature_ledger() -> None:
    labels = build_spell_outcome_labels(_spell_identities(), _trajectory())
    assert labels.columns.tolist() == [
        "leader_spell_id", "future_5d_close_return_pct",
        "future_5d_max_close_return_pct", "future_5d_max_drawdown_pct",
        "future_sessions_available", "outcome_status",
    ]


def test_matched_pairs_require_same_recognition_date_and_concept() -> None:
    pairs = build_matched_spell_pairs(_labeled_cases())
    assert pairs.loc[0, "winner_stock_name"] == "甲公司"
    assert pairs.loc[0, "loser_stock_name"] == "乙公司"
    assert pairs.loc[0, "recognition_source_date"] == pd.Timestamp("2025-01-10")
    assert pairs.loc[0, "sector_id"] == "BK0001"


def test_pairing_is_deterministic_under_input_shuffle() -> None:
    baseline = build_matched_spell_pairs(_labeled_cases())
    shuffled = build_matched_spell_pairs(_labeled_cases().sample(frac=1, random_state=7))
    pd.testing.assert_frame_equal(baseline, shuffled)
```

- [ ] **Step 2: Run the tests and verify they fail**

Run the Task 1 test command. Expected: failures for missing label and pairing functions.

- [ ] **Step 3: Implement downstream outcome labels**

Add:

```python
def build_spell_outcome_labels(
    spells: pd.DataFrame,
    trajectories: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize S+1..S+5 paths without exposing them to feature construction."""
```

Require five future sessions for a complete label. Compute returns from S close and the maximum peak-to-trough drawdown within S..S+5. Do not create a buy rule or tune a success threshold.

- [ ] **Step 4: Implement deterministic comparisons**

Add:

```python
def build_matched_spell_pairs(cases: pd.DataFrame) -> pd.DataFrame:
    """Pair strongest and weakest future paths within the same S date/concept."""
```

Within each `(recognition_source_date, sector_id)`, require at least two distinct symbols and both positive and non-positive S+5 returns. Select the maximum-return and minimum-return case with stable tie breakers `(recognition_rank, vt_symbol)`. Preserve both actual stock identities, their S-close descriptors and the outcome spread.

- [ ] **Step 5: Run the tests and verify they pass**

Run the Task 1 test command. Expected: all tests pass.

### Task 4: Add Reproducible Loader, Machine Report and CLI

**Files:**
- Modify: `alphaagent/server/services/low_suction/individual_leader_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_individual_leader_study.py`

- [ ] **Step 1: Add failing report and CLI tests**

```python
def test_report_contains_actual_case_rows_not_only_aggregates() -> None:
    report = build_individual_leader_report(_features(), _labels(), _pairs(), _trajectory(), {})
    assert report["formal_rule_selected"] is False
    assert report["strict_top3_claim"] is False
    assert report["individual_cases"][0]["stock_name"] == "甲公司"
    assert report["matched_pairs"][0]["winner_stock_name"] == "甲公司"


def test_cli_registers_individual_leader_study() -> None:
    args = build_parser().parse_args(["v2-individual-leader-study"])
    assert args.command == "v2-individual-leader-study"
```

- [ ] **Step 2: Run tests and verify they fail**

Run the Task 1 test command. Expected: missing report function and parser command failures.

- [ ] **Step 3: Implement the real-data loader**

Add:

```python
def load_individual_leader_study_data() -> tuple[
    pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]
]:
    """Load frozen proxy spells and build features, labels, pairs and trajectories."""
```

Reuse `load_event_falsification_inputs()` and `load_cycle_research_inputs()` once each. Start from raw recognition candidates so all 369 source spells remain available before neutral-day collision removal. The loader must not load minute bars, old low-suction trades, outer holdout values, current membership rows or the limit-up production strategy. Add fingerprints for identities, features, labels, pairs and trajectories.

- [ ] **Step 4: Implement JSON and Markdown reports**

Add `build_individual_leader_report`, `run_individual_leader_study`, `render_individual_leader_json` and `render_individual_leader_markdown`.

The machine report must contain:

- Coverage and fingerprints.
- Every spell's real identity, point-in-time descriptors and downstream labels.
- Deterministic top 20 and bottom 20 S+5 paths.
- Every matched same-date/same-concept pair.
- Repeated-stock summaries without treating repeated rows as independent proof.
- Gold/Silver descriptive counts, never a promoted environment rule.
- Boundaries: proxy ranking, no strict Top3, no formal strategy, no outer holdout.

The Markdown report must show real stock names for top/bottom paths and at least 20 matched pairs, with links to the JSON as the complete ledger.

- [ ] **Step 5: Register the CLI command**

Add parser command `v2-individual-leader-study` with `json/markdown` formats and an optional output path. Route it through the four renderer/run functions without changing other commands.

- [ ] **Step 6: Run tests and static checks**

Run:

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  pytest tests/alphaagent/services/low_suction/test_individual_leader_study.py -q
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  ruff check alphaagent/server/services/low_suction/individual_leader_study.py \
    alphaagent/server/services/low_suction/cli.py \
    tests/alphaagent/services/low_suction/test_individual_leader_study.py
```

Expected: all tests pass and Ruff reports no errors.

### Task 5: Run the Real Individual Study and Record Bounded Findings

**Files:**
- Create: `memory/06_backtests/low_suction_individual_leader_study_20260717.json`
- Create: `memory/06_backtests/low_suction_individual_leader_study_20260717.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: Generate the complete machine ledger and readable report**

Run:

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-individual-leader-study --format json \
  --output memory/06_backtests/low_suction_individual_leader_study_20260717.json
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-individual-leader-study --format markdown \
  --output memory/06_backtests/low_suction_individual_leader_study_20260717.md
sha256sum memory/06_backtests/low_suction_individual_leader_study_20260717.json
```

Expected: both artifacts are non-empty, the JSON contains actual stock names and the Markdown records its hash.

- [ ] **Step 2: Inspect deterministic real cases**

Use the complete ledger to review:

- At least 10 largest positive and 10 largest negative S+5 paths.
- At least 20 same-date/same-concept matched pairs.
- Every spell for the five most repeated stocks.
- Gold and Silver cases separately, while preserving their date/block confounding.

For each reviewed case, compare the actual S-20..S+5 path and record only recurring structural observations visible in multiple independent spells. Do not convert an observation into a threshold in this task.

- [ ] **Step 3: Record the bounded conclusion**

The report conclusion must distinguish:

- Observed recurring individual-stock structures.
- Structures contradicted by matched cases.
- Missing evidence caused by incomplete historical Top3 membership.
- Candidate phase hypotheses for a later frozen `launch/acceleration/climax/decay` contract.
- Explicitly rejected claims and the next data gate.

- [ ] **Step 4: Update durable project memory**

Link the report from `memory/06_backtests/README.md`. Rewrite the relevant low-suction bullets in `memory/09_decisions/decisions.md` so the current state says the aggregate proxy search is stopped and the individual spell evidence ledger is the active discovery surface.

- [ ] **Step 5: Run the full focused verification**

Run:

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  pytest tests/alphaagent/services/low_suction -q
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m compileall -q alphaagent/server/services/low_suction
git diff --check
```

Expected: focused tests pass, compilation succeeds and `git diff --check` produces no output.

## Self-review

- Spec coverage: the plan changes the unit from aggregate trades to real stock spells, includes actual identities, full paths, matched cases, Gold/Silver context and causal boundaries.
- Placeholder scan: no implementation step depends on an unspecified threshold or unnamed function.
- Type consistency: identity, feature, label, pair and report function names remain identical across tasks.
- Scope boundary: strict historical Top3 remains blocked; this study cannot revive the rejected proxy entry rule or read the outer holdout.
