# Low-suction Event-neutral State Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether outcome-neutral S+1..S+5 minute states of event-recognized main-rise leader spells contain a simple, validation-stable low-suction direction worth retesting with strict historical Top3 data.

**Architecture:** Collapse repeated recognition events into one `(sector_id, cycle_id, vt_symbol)` spell, then retain every next-five-session observation day whose previous close still belongs to the same frozen `breakout_trend` cycle. Build a point-in-time 5m state panel without shape labels, fit train-only response bins and one depth-2 tree on blocks 1-3, and evaluate readable false-to-true transitions once on blocks 4-5. This remains an `event_recognition_falsification` proxy and never reads the outer holdout.

**Tech Stack:** Python 3.11+, pandas, NumPy, scikit-learn `DecisionTreeRegressor`, SQLAlchemy/PostgreSQL, existing TDX category-0 5m importer, existing cash execution helpers, pytest.

**Repository constraints:** No commits, no outer-holdout prices, no current-member fallback, no modifications to `vnpy/`, official examples,打板 strategies,打板 ledgers or打板 minute rows.

---

## Frozen Research Contract

- Spell identity: `(sector_id, cycle_id, vt_symbol)`; keep the earliest recognition event.
- Neutral observation days: S+1 through S+5, with no stock-return, candle, final-low or recovery filter.
- Point-in-time main-rise guard: the previous reliable session must still have the same active `breakout_trend cycle_id`; the observation day's concept close is prohibited.
- Observation and D+1 planned exit must both be no later than `2025-11-17`.
- Same stock/day collision: previous-day concept relative percentile descending, original recognition date ascending, sector ID ascending.
- Minute contract: exactly 48 unique TDX 5m bars from 09:35 through 15:00.
- Feature rows start only when three prior 5m closes and three prior volumes exist; the 15:00 row is excluded because no next bar can fill it.
- Entry: predicate closes false-to-true at bar t; fill at the next 5m open with normal A-share costs and 10 bps slippage.
- Discovery exit: D+1 first sellable close only. Other exits remain unread until an entry rule qualifies.
- Time split: chronological candidate dates in five equal blocks; blocks 1-3 fit bins/tree, blocks 4-5 are validation and never alter thresholds.
- Tree: `DecisionTreeRegressor(max_depth=2, min_samples_leaf=100, random_state=0)` using only normal-cost D+1 net log return and inverse `(trade_date, cycle_id)` block weights.
- Maximum five readable candidates; each condition is only `<=` or `>` and each rule has at most two conditions.
- Validation nomination gate: at least 100 closed transitions, win rate strictly above 60%, positive mean, PF above 1, positive double-cost mean, and both validation blocks positive with PF above 1.
- Nomination still means only `worth_strict_top3_retest`; formal win rate, cash compounding, drawdown and holdout stay null.

## Frozen Feature Schema

```python
NEUTRAL_STATE_FEATURES = (
    "drawdown_from_session_high_pct",
    "distance_to_previous_close_pct",
    "distance_to_open_pct",
    "distance_to_vwap_pct",
    "distance_to_previous_high_pct",
    "distance_to_ma5_pct",
    "distance_to_ma10_pct",
    "return_1bar_pct",
    "return_3bar_pct",
    "volume_ratio_prior_3bars",
    "minutes_from_open",
    "cycle_relative_percentile",
    "spell_session_offset",
)
```

The exact response surfaces are:

```python
NEUTRAL_SURFACES = (
    ("drawdown_from_session_high_pct", "cycle_relative_percentile"),
    ("distance_to_vwap_pct", "volume_ratio_prior_3bars"),
    ("minutes_from_open", "distance_to_previous_close_pct"),
    ("return_3bar_pct", "drawdown_from_session_high_pct"),
)
```

Quantile edges are 20/40/60/80 percentiles fit on blocks 1-3 only. Each cell reports raw states,
independent `(trade_date, cycle_id)` blocks, normal/double-cost win, mean, median, PF and 5% tail;
no cell itself is a strategy.

### Task 1: Build Outcome-neutral Spell Days

**Files:**
- Create: `alphaagent/server/services/low_suction/event_neutral_days.py`
- Create: `tests/alphaagent/services/low_suction/test_event_neutral_days.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] Test earliest-spell deduplication, exact S+1..S+5 offsets, previous-day same-cycle eligibility, no same-day cycle read, discovery boundary, support values using D-1 or earlier, cross-concept collision order and outcome-column rejection.
- [x] Implement `build_event_neutral_days()` as a pure function and `load_event_neutral_inputs()` as a discovery-only loader.
- [x] Add `v2-event-neutral-audit` with only `--format/--output`; report the candidate funnel, offset counts, regimes, input fingerprints and `holdout_price_values_read=false`.
- [x] Run the audit before loading minute bars or outcomes; stop only if fewer than 100 candidate days exist.

### Task 2: Build And Fill The Exact 5m Manifest

**Files:**
- Create: `alphaagent/server/services/low_suction/event_neutral_minutes.py`
- Create: `tests/alphaagent/services/low_suction/test_event_neutral_minutes.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] Test reuse of the exact 48-bar manifest contract and manifest-only TDX gap requests.
- [x] Add `v2-event-neutral-5m-manifest` and `v2-event-neutral-5m-backfill`; expose no dates, windows or offsets.
- [x] Run the initial manifest, backfill only missing pairs, then rerun until every available pair is complete or explicitly reported missing.
- [x] Record rows read/written and verify existing 1m row count is unchanged.

### Task 3: Build The Outcome-free State Panel

**Files:**
- Create: `alphaagent/server/services/low_suction/event_neutral_panel.py`
- Create: `tests/alphaagent/services/low_suction/test_event_neutral_panel.py`

- [x] Test cumulative VWAP, session high, D-1 MA5/MA10/supports, returns, prior-three-bar volume ratio and minutes-from-open against manual calculations.
- [x] Prove changing future 5m bars cannot alter an earlier state row and reject any future/outcome columns.
- [x] Implement `build_event_neutral_state_panel()` using only complete candidate days and `<=bar_time` data.
- [x] Assign `independence_block_id = trade_date + ':' + cycle_id` and inverse block weights summing to one per block.
- [x] Exclude incomplete feature rows and rows without a next 5m bar with explicit coverage counts, not silent data repair.

### Task 4: Label Only The Frozen D+1 Outcome

**Files:**
- Create: `alphaagent/server/services/low_suction/event_neutral_outcomes.py`
- Create: `tests/alphaagent/services/low_suction/test_event_neutral_outcomes.py`

- [x] Test next-5m-open fill, 100-share lots, minimum commission, limit-up rejection, D+1 sellable-close exit and double-cost monotonicity.
- [x] Implement labels by adapting panel rows to the existing `execute_event_5m_transitions()` contract; do not duplicate cash arithmetic.
- [x] Keep state and outcome frames separate until discovery joins them by immutable `observation_id`.
- [x] Prove the panel module never imports the outcome module.

### Task 5: Fit Train-only Surfaces And A Bounded Tree

**Files:**
- Create: `alphaagent/server/services/low_suction/event_neutral_discovery.py`
- Create: `tests/alphaagent/services/low_suction/test_event_neutral_discovery.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] Test validation extremes cannot change development quantile edges or tree thresholds.
- [x] Test the four exact surfaces, empty/duplicate quantile edges, deterministic ordering and independent-block counts.
- [x] Test tree depth, five-candidate cap, two-condition cap, rejected-leaf retention and absence of order-generation methods.
- [x] Test a predicate true at the first eligible bar is not a false-to-true transition; keep only the first transition per candidate day.
- [x] Implement development gates for leaves: at least 100 independent blocks, positive normal mean/PF and positive double-cost mean; retain every rejected leaf with its reason.
- [x] Evaluate frozen candidates once on validation blocks 4-5 and produce full rule/block/regime tables.
- [x] Add `v2-event-neutral-state-study` with only `--format/--output` and run it once.

### Task 6: Evidence And Safety Gate

**Files:**
- Create after the real run: `memory/06_backtests/low_suction_event_neutral_state_discovery_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: this plan's checkboxes

- [x] Record candidate/minute/state fingerprints, coverage exclusions, all response cells, every accepted/rejected tree leaf, validation metrics and non-qualifying high-win cells.
- [x] Conclude only `no_event_neutral_state_edge`, `event_neutral_direction_only` or `worth_strict_top3_retest`; formal metrics remain null.
- [x] Run all low-suction tests, scoped Ruff through the project `uvx`, compileall and `git diff --check`.
- [x] Confirm outer holdout values, current-member rows and打板 strategy/ledger rows read are all zero.

## Completion Boundary

Completion means the event-recognition proxy has one reproducible, outcome-neutral state-discovery result
with thresholds trained only on blocks 1-3 and evaluated once on blocks 4-5. It does not select the formal
Top3 identity mode, unlock the outer holdout, compute production cash compounding or create a low-suction UI.
