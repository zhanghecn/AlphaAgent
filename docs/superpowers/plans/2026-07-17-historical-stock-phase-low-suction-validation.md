# Historical Stock-Phase Low-Suction Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Immediately test historical low-suction trades after joining the actual intraday entry ledger to causal stock-level main-rise phases, then identify only time-split-stable win-rate, expectation, and compounding cohorts.

**Architecture:** Reuse the existing historical outcome-group loader for the frozen entry/exit execution and the daily-phase loader for features known at D-1 close. Join once on unique `(vt_symbol, entry_date)`, enumerate a frozen set of phase plus one-condition cohorts, and compare development blocks 1-3 with validation blocks 4-5. Keep strict historical concept Top3 claims false because the source identity remains the historical event-recognition Top3 proxy.

**Tech Stack:** Python 3.11+, pandas, existing AlphaAgent PostgreSQL research loaders, pytest, Ruff, JSON/Markdown evidence.

**Execution rule:** Work inline without subagents and do not commit or push.

---

## Frozen Contract

- Historical sample: existing event-recognition Rank1-3 proxy days at offsets S+1 through S+4 that have both a complete stock phase and a complete 5-minute entry path.
- Feature cutoff: D-1 official close for stock phase, daily volume, relative strength, historical rank, and GOLD/SILVER state; intraday signal fields stop at the observed 5-minute bar.
- Entry: first 5-minute close at or below D-1 close, buy at the next 5-minute bar open.
- Exit: D+1 official close under A-share T+1 and existing normal/double-cost execution.
- Eligible stock phases: `first_launch`, `divergence_restart`, `healthy_pullback`, and `trend_continuation`.
- Explicit risk phases: `continuous_acceleration`, `climax_risk`, `decay`, and `unclassified`.
- Frozen one-condition dimensions within each phase:
  - `daily_volume_class`
  - `relative_strength_state`
  - `leader_rank_group`
  - `market_regime`
  - `intraday_volume_class`
  - `signal_time_bucket`: `opening_30`, `morning_31_120`, `afternoon_121_plus`
  - `pullback_depth_bucket`: `shallow_0_1`, `moderate_1_3`, `deep_3_plus`
- No phase plus two-condition or fitted numeric search is allowed in this plan.
- Development: chronological blocks 1-3. Validation: blocks 4-5.
- Development candidate gate: at least 30 closed trades and 20 source days, win rate greater than 55%, positive mean, profit factor greater than 1, and positive double-cost mean.
- Validation confirmation gate: at least 20 closed trades and 15 source days with the same four performance signs. `high_win_confirmed` additionally requires win rate greater than 60% in both development and validation.
- Compounding diagnostic: compound equal-weight daily cohort returns; report return and maximum drawdown separately for development and validation. It is comparative research evidence, not a production cash ledger.
- Outcome columns may be attached only after cohort identities are built from causal fields.
- The report must retain `strict_historical_top3_claim=false`, `formal_rule_selected=false`, and `formal_metrics=null`.

### Task 1: Join Historical Intraday Trades to Stock Phases

**Files:**
- Create: `alphaagent/server/services/low_suction/historical_phase_low_suction_study.py`
- Create: `tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py`

- [x] **Step 1: Add failing join and leakage tests**

Test that the join is one-to-one on `(vt_symbol, entry_date)`, retains unmatched outcome rows as coverage evidence, rejects duplicate phase identities, and rejects outcome/future columns in the causal phase input.

```python
merged, coverage = join_historical_phase_trades(outcome_trades, phase_panel)
assert coverage == {"outcome_trades": 3, "matched_phase_trades": 2, "unmatched_phase_trades": 1}
assert merged.loc[merged["phase_matched"], "phase"].notna().all()
```

- [x] **Step 2: Run the new focused test and confirm the module is missing**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py -q
```

- [x] **Step 3: Implement the minimal causal join**

Normalize dates, validate unique keys, select an explicit allowlist of phase fields, merge without dropping outcome trades, and return deterministic coverage counts.

- [x] **Step 4: Run the focused tests**

Expected: the join and leakage tests pass.

### Task 2: Freeze Buckets, Metrics, and Time-Split Evaluation

**Files:**
- Modify: `alphaagent/server/services/low_suction/historical_phase_low_suction_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py`

- [x] **Step 1: Add failing bucket and cohort tests**

Prove boundary behavior for signal time and pullback depth, and prove cohort identities use phase plus at most one frozen dimension.

```python
assert classify_signal_time(30) == "opening_30"
assert classify_signal_time(31) == "morning_31_120"
assert classify_pullback_depth(-1.0) == "shallow_0_1"
assert classify_pullback_depth(-1.01) == "moderate_1_3"
```

- [x] **Step 2: Add failing performance and stability tests**

Use synthetic blocks to prove that a high development cohort is rejected when validation loses money, and that a cohort is confirmed only when sample, win rate, mean, profit factor, and double-cost gates all pass. Verify daily equal-weight compounding and maximum drawdown.

- [x] **Step 3: Implement frozen cohort enumeration and metrics**

Build phase-only and phase-plus-one-condition identities before reading `net_return_pct`. Attach outcomes afterward, summarize `all/development/validation/block_1..5`, and calculate deterministic daily compounding.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py -q
uvx ruff check alphaagent/server/services/low_suction/historical_phase_low_suction_study.py tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py
```

### Task 3: Load Existing Historical Evidence and Render a Reproducible Report

**Files:**
- Modify: `alphaagent/server/services/low_suction/historical_phase_low_suction_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py`

- [x] **Step 1: Test loader orchestration and report boundaries**

Mock `load_daily_phase_study_data()` and `load_outcome_group_study_data()` and require the report to expose match coverage, phase baselines, winner/loser profiles, cohort metrics, development candidates, validation confirmations, and best validation cohort while keeping all formal fields closed.

- [x] **Step 2: Implement the loader and report renderers**

Add `v2-historical-phase-low-suction-study --format json|markdown`. The command must read only existing historical data and must not mutate forward Top3 tables.

- [x] **Step 3: Run all focused tests**

Expected: all historical phase low-suction tests pass.

### Task 4: Execute the Historical Study and Preserve Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.md`
- Create: `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Rebuild the API and run the study once**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-historical-phase-low-suction-study --format markdown
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-historical-phase-low-suction-study --format json
```

- [x] **Step 2: Save exact outputs and record JSON SHA256**

Parse the JSON and ensure the Markdown and JSON agree on sample counts and candidate status.

- [x] **Step 3: Run complete verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
git diff --check
```

- [x] **Step 4: Update durable memory with the actual conclusion**

Record the best confirmed historical cohort if one exists. If none exists, record the strongest positive but unconfirmed phase and the stable risk exclusions; do not manufacture a high-win rule.

### Task 5: Test Frozen Intraday Recovery Transitions by Stock Phase

**Files:**
- Modify: `alphaagent/server/services/low_suction/historical_phase_low_suction_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_historical_phase_low_suction_study.py`
- Regenerate: `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.md`
- Regenerate: `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.json`

- [x] **Step 1: Add failing transition-ledger tests**

Require causal transition identities to join to phases before normal and double-cost outcomes. Only the four pre-existing frozen rules are allowed: VWAP reclaim, open reclaim, previous-close reclaim, and two higher closes after an open break.

- [x] **Step 2: Implement transition loading and phase metrics**

Reuse the complete outcome-group 5-minute candidate pairs, existing point-in-time transition extraction, and D+1 execution. Add `phase_x_transition_rule` as one phase plus one condition; do not introduce new thresholds.

- [x] **Step 3: Report stable positive expectation separately from high win rate**

A sufficiently sampled cohort is `stable_positive_expectation` only when development and validation both have positive mean, profit factor above 1, and positive double-cost mean. It remains unconfirmed as a high-win rule unless both win rates exceed 60%.

- [x] **Step 4: Re-run evidence and verification**

The report must include transition counts, development/validation metrics, daily compounding, drawdown, and the `17/0/0` first-touch gate result plus the expanded transition gate result.

## Self-Review

- Spec coverage: historical rather than forward validation, causal D-1 features, actual intraday low-suction execution, D+1 close exit, stock main-rise phases, volume, leader rank, GOLD/SILVER, win/loss groups, time split, and compounding are all explicit.
- Placeholder scan: all thresholds, buckets, sample gates, fields, commands, and failure behavior are fixed.
- Type consistency: join keys are `(vt_symbol, entry_date)`; phase features precede outcomes; report and tests share the same cohort names.
