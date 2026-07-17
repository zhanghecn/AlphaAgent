# Low-suction Win/Loss Group Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible proxy study that buys one outcome-neutral intraday pullback per stock-day, exits at the D+1 sellable close, and compares winning and losing trades by pre-entry volume, leader rank, main-rise status, and GOLD/SILVER market state.

**Architecture:** Extend the frozen event-recognized leader-spell universe with a point-in-time non-main-rise control without changing the existing main-rise dataset. Reuse the exact 48-bar TDX manifest and cash-execution contract, select the first eligible 5m close at or below D-1 close, and keep one trade per candidate day. Classify pre-registered cohorts on chronological blocks 1-3 and verify the same cohort keys on blocks 4-5; the outer 20% holdout remains unread and all results remain proxy evidence.

**Tech Stack:** Python 3.11+, pandas, NumPy, SQLAlchemy/PostgreSQL, existing TDX 5m importer, existing cash-ledger execution, pytest.

**Repository constraints:** Do not modify `vnpy/`, official examples, limit-up strategy or ledger code. Do not read outer-holdout prices, use current concept members, or call outcome fields while constructing candidates/features. Do not commit or push because repository instructions require explicit user authorization.

---

## Frozen Research Contract

- Universe: earliest `(sector_id, cycle_id, vt_symbol)` event-recognition spell, S+1..S+5, main-board only, proxy recognition rank 1-3.
- Main-rise label: at D-1 close, the concept must still be in the exact frozen `breakout_trend cycle_id`; otherwise the row is a non-main-rise control. The observation-day concept close is never read.
- Collision: one stock/day, preferring an exact active main-rise spell, then higher D-1 concept relative percentile, earlier recognition date, lower sector ID.
- Minute completeness: exactly 48 unique 5m bars from 09:35 through 15:00.
- Entry signal: the first row with three completed prior 5m bars, a next bar, and `close_price <= D-1 close`; buy at the next 5m open. There is at most one trade per stock-day.
- Exit: D+1 first sellable daily close under the existing T+1/limit-down/suspension cash contract.
- Costs: normal costs and 2x costs are both computed; a winner means normal-cost `net_return_pct > 0`, otherwise a closed trade is a loser.
- Daily volume ratio: D-1 volume divided by the mean volume of the five sessions before D-1.
- Intraday volume ratio: signal 5m volume divided by the mean of the three completed 5m bars before the signal.
- Both volume ratios use the same fixed classes: `contraction < 0.8`, `normal [0.8, 1.5)`, `expansion [1.5, 2.5)`, `explosion >= 2.5`.
- Leader classes: `rank_1` and `rank_2_3`; market classes use D-1 `active_direction/danger_state`; main-rise classes are `main_rise` and `non_main_rise`.
- Time split: candidate dates use the existing five chronological blocks. Blocks 1-3 are development and blocks 4-5 are validation.
- High cohort on development: at least 30 closed trades and 20 trade dates, win rate strictly above 60%, positive mean, PF above 1, and positive 2x-cost mean.
- Low cohort on development: at least 30 closed trades and 20 trade dates, win rate strictly below 45%, negative mean, and PF below 1.
- Everything else is neutral. A high or low cohort is called confirmed only if the same gates hold independently on validation.
- Pre-registered tables: each single factor; daily-volume x intraday-volume; intraday-volume x rank; intraday-volume x main-rise; intraday-volume x market regime; main-rise x rank x market regime.
- No cohort becomes a trading rule in this task. Formal win rate, compounding, drawdown, and selected rule remain `null`.

### Task 1: Add Point-in-time Main-rise Controls

**Files:**
- Modify: `alphaagent/server/services/low_suction/event_neutral_days.py`
- Modify: `tests/alphaagent/services/low_suction/test_event_neutral_days.py`

- [x] **Step 1: Write failing control-universe tests**

Add tests which call a new public function and prove a D-1 cycle mismatch is retained as `main_rise=False`, an observation-day-only cycle change does not alter the current row, and a collision prefers an exact main-rise spell:

```python
result = build_event_neutral_comparison_days(...)
row = result.loc[result["spell_session_offset"].eq(4)].iloc[0]
assert row["main_rise"] is False or not bool(row["main_rise"])
assert result.duplicated(["vt_symbol", "entry_date"]).sum() == 0
```

- [x] **Step 2: Run tests and verify the new symbol is missing**

Run:

```bash
uv run pytest tests/alphaagent/services/low_suction/test_event_neutral_days.py -q
```

Expected: failure importing `build_event_neutral_comparison_days`.

- [x] **Step 3: Implement the comparison builder without changing the strict default**

Add:

```python
def build_event_neutral_comparison_days(... ) -> pd.DataFrame:
    return _build_neutral_days(..., include_non_main_rise=True).candidates
```

Thread `include_non_main_rise` through `_build_neutral_days()` and `_build_spell_day()`. Preserve the current rejection when false; when true, retain the row, set `main_rise` from the exact D-1 cycle match, allow a nullable relative percentile, and order collisions by `main_rise DESC` before relative percentile.

- [x] **Step 4: Run the scoped tests**

Run the same pytest command. Expected: all event-neutral day tests pass and the original `build_event_neutral_days()` output remains unchanged.

### Task 2: Build The Comparison Manifest

**Files:**
- Create: `alphaagent/server/services/low_suction/outcome_group_minutes.py`
- Create: `tests/alphaagent/services/low_suction/test_outcome_group_minutes.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] **Step 1: Test exact candidate-only coverage and CLI safety**

Test that comparison candidates produce one manifest row per stock-day, preserve `context_date`, and expose only `--format/--output` for manifest and `--write/--max-gaps` for backfill. No user-selected dates, offsets, thresholds, or entry parameters are allowed.

- [x] **Step 2: Verify the tests fail**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_outcome_group_minutes.py -q
```

Expected: module/CLI commands do not exist.

- [x] **Step 3: Implement the loader and backfill wrapper**

Reuse `build_event_neutral_5m_manifest()` and the existing `stock_minute_bars` query. Load comparison inputs through one frozen loader, request only incomplete pairs via `import_tdx_minute_bars_for_gaps()`, and identify the dataset as `low_suction_outcome_group_observation_5m`.

- [x] **Step 4: Run scoped tests**

Expected: all new manifest tests pass without touching 1m rows.

### Task 3: Select One Low-suction Trade And Attach Pre-entry Features

**Files:**
- Create: `alphaagent/server/services/low_suction/outcome_group_study.py`
- Create: `tests/alphaagent/services/low_suction/test_outcome_group_study.py`

- [x] **Step 1: Write failing entry and leakage tests**

Cover the first eligible `close <= signal_close`, next-bar-open fill fields, one trade per event, no signal when the price never reaches D-1 close, exact daily/intraday volume ratios, all four boundary classes, and invariance when bars after the chosen signal are changed.

```python
signals = build_outcome_group_signals(candidates, minute_bars, daily_bars)
assert signals.groupby("event_id").size().max() == 1
assert signals.iloc[0]["entry_time"] == expected_next_bar_time
assert classify_volume_ratio(0.8) == "normal"
assert classify_volume_ratio(1.5) == "expansion"
assert classify_volume_ratio(2.5) == "explosion"
```

- [x] **Step 2: Verify failures before implementation**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_outcome_group_study.py -q
```

- [x] **Step 3: Implement point-in-time signal construction**

Build the base panel with `build_event_5m_state_panel()`, calculate the current-volume/prior-three ratio with `shift(1).rolling(3)`, select the first eligible signal, and attach D-1/prior-five daily volume from daily bars. Reject prohibited future/outcome columns before feature construction.

- [x] **Step 4: Label normal and stressed D+1 outcomes**

Adapt selected signal rows to `label_event_neutral_outcomes()` without duplicating cash arithmetic. Join outcomes only by immutable `observation_id` after the signal frame is frozen.

- [x] **Step 5: Run scoped tests**

Expected: signal, volume, execution, and no-lookahead tests pass.

### Task 4: Build Winner/Loser Profiles And Cohort Validation

**Files:**
- Modify: `alphaagent/server/services/low_suction/outcome_group_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_outcome_group_study.py`

- [x] **Step 1: Write failing metric/classification tests**

Use deterministic synthetic trades to prove strict `>60` and `<45` boundaries, minimum trade/date gates, normal and 2x-cost metrics, validation lookup by unchanged cohort identity, and retention of neutral/failed cohorts.

```python
assert classify_development_cohort(high_metrics) == "high_candidate"
assert classify_development_cohort({**high_metrics, "win_rate_pct": 60.0}) == "neutral"
assert classify_development_cohort(low_metrics) == "low_candidate"
```

- [x] **Step 2: Implement pre-registered cohort tables**

Emit development and validation rows for every observed cohort identity, including signals, closed trades, dates, win rate, mean, median, PF, 5% tail, 2x-cost win/mean, and classification/confirmation status. Build a separate descriptive winner-vs-loser profile; never use the outcome label as a candidate feature.

- [x] **Step 3: Implement machine and human reports**

The JSON report must include the frozen contract, coverage, fingerprints, rejection reasons, all cohort rows, profiles, and safety flags. Markdown must lead with the actual result and show overall, volume, rank, main-rise, and GOLD/SILVER comparisons. Set `formal_metrics=null`, `formal_rule_selected=false`, `holdout_price_values_read=false`, and `current_membership_rows_read=0`.

- [x] **Step 4: Run scoped tests**

Expected: all outcome-group study tests pass.

### Task 5: Wire The Frozen CLI And Run Real Data

**Files:**
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_outcome_group_minutes.py`

- [x] **Step 1: Add three frozen commands**

Add `v2-outcome-group-5m-manifest`, `v2-outcome-group-5m-backfill`, and `v2-outcome-group-study`. The study command accepts only `--format` and `--output`.

- [x] **Step 2: Count 1m rows and run the manifest**

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli v2-outcome-group-5m-manifest --format json
```

- [x] **Step 3: Backfill only missing comparison pairs**

Run the frozen backfill with `--write`, rerun the manifest until every available pair is complete, and prove the 1m row count is unchanged.

- [x] **Step 4: Run the study once**

Write JSON directly to `memory/06_backtests/low_suction_outcome_group_study_20260717.json`; render the Markdown from the same report object so both artifacts share one evidence fingerprint.

### Task 6: Evidence, Memory, And Verification

**Files:**
- Create: `memory/06_backtests/low_suction_outcome_group_study_20260717.md`
- Create: `memory/06_backtests/low_suction_outcome_group_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-17-low-suction-win-loss-group-study.md`

- [x] **Step 1: Record the complete evidence**

Store candidate/minute/signal/outcome fingerprints, main-rise/control counts, missing-entry and execution rejection counts, overall development/validation results, winner/loser profiles, every pre-registered cohort, and SHA256 of the JSON report.

- [x] **Step 2: State the bounded conclusion**

Use exactly one conclusion: `confirmed_high_and_low_cohorts`, `descriptive_groups_not_stable`, or `no_usable_group_separation`. Do not select an entry rule or report formal cash compounding.

- [x] **Step 3: Run proportionate verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
git diff --check
```

Confirm the existing event-neutral JSON SHA256, existing 1m row count, limit-up strategy files, and outer-holdout read flag remain unchanged.

## Completion Boundary

Completion means the user has a reproducible D+1 outcome split and a time-separated comparison of volume, leader rank, main-rise status, and GOLD/SILVER context. It does not mean a production low-suction strategy exists. Strict Top3 performance stays blocked until point-in-time historical membership and security-state coverage are complete.
