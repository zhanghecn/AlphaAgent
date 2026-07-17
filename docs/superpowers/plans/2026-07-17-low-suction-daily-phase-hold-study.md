# Low-suction Daily Leader Phase Hold Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze a causal daily lifecycle contract for real event-recognized leader spells and determine which phase, if any, has a stable D-open-to-D+1-close edge before another intraday low-suction rule is studied.

**Architecture:** Rebuild the outcome-neutral leader-spell day panel from the frozen discovery inputs, retain only context dates `S..S+3`, and attach stock, concept and market features known at each context close. Assign one mutually exclusive lifecycle phase without reading returns after the context date, execute every phase through the existing cash ledger under normal and double costs, and report early/late/block/regime/volume/relative-strength stability with complete stock-level trade rows. The event-recognition universe remains a proxy rather than strict historical Top3, so the study may select a phase for later minute research but cannot select a production strategy.

**Tech Stack:** Python 3.11+, pandas, NumPy, existing AlphaAgent discovery loaders and cash ledger, pytest, Ruff, Docker Compose/PostgreSQL.

---

## Frozen Research Contract

- Universe: earliest event-recognized `(sector_id, cycle_id, vt_symbol)` leader spells, after the existing deterministic same-stock/same-entry-date concept collision rule.
- Board scope: Shanghai/Shenzhen 10cm main board only; reject ChiNext, STAR, Beijing and unknown symbol formats.
- Observation context: `spell_session_offset` 1 through 4, whose D-1 context dates are `S..S+3`; D entry and D+1 exit therefore remain within `S+1..S+5`.
- Feature cutoff: D-1 close. Mutating any later stock, concept or market row must not change the phase.
- Concept guard: the exact frozen `breakout_trend` cycle identity must still be active at D-1 close. A broken concept cycle is `decay`, never a positive phase.
- Daily strong-day proxy: main-board close-to-close return at least `9.5%`.
- Phase precedence:
  1. `unclassified` when causal history is incomplete.
  2. `decay` when the exact concept cycle has ended or stock close is below MA10 or MA5 is not above MA10.
  3. `climax_risk` when the current strong-day run is at least three sessions.
  4. `continuous_acceleration` when the current strong-day run is exactly two sessions.
  5. `divergence_restart` when today is a strong day, yesterday was not, and at least one strong day exists in the previous 10 sessions.
  6. `first_launch` when today is a strong day and no strong day exists in the previous 10 sessions.
  7. `healthy_pullback` when the exact concept cycle remains active, today is non-positive but not a strong day, close remains at or above MA5, a strong day exists in the previous five sessions, and volume is below the prior-five-session mean.
  8. `trend_continuation` when the exact concept cycle remains active and `close >= MA5 > MA10 > MA20`.
  9. `unclassified` for the remaining observations; do not force ambiguous days into a tradable phase.
- Volume taxonomy is descriptive only: `contraction <0.8`, `normal [0.8,1.5)`, `expansion [1.5,2.5)`, `explosion >=2.5` versus prior-five-session mean.
- Relative-strength taxonomy is descriptive only: `improving_positive` requires positive stock-minus-concept three-day return and a positive one-day change in that excess; otherwise `positive_not_improving`, `non_positive`, or `missing`.
- Entry/exit: D open buy, D+1 official daily close sell, 100,000 CNY, 100-share lots, existing fees/slippage, suspension/limit-up entry rejection and one-price limit-down exit rejection.
- Cost stress: identical trades at 2x fees and slippage.
- Time diagnostics: five deterministic blocks. Blocks 1-3 are `early_1_3`; blocks 4-5 are `late_4_5`. All five have appeared in prior studies, so `late_4_5` is a reused stability segment, not an untouched validation set.
- A phase-level `high_win_candidate` requires at least 30 closed trades, 20 entry dates, win rate strictly above 60%, positive mean, PF above 1 and positive double-cost mean.
- A stable phase candidate must meet that gate in both early and late segments, have at least four positive time blocks, and have no stock, concept or month contribute more than 20% of positive profit.
- Gold/silver, danger state, volume and relative strength are complete attribution tables. They cannot become switches in this study.
- Complete trade rows must preserve actual stock, date, concept, phase, causal features, execution status and normal/double-cost return.
- Formal Top3, production entry, cash compounding, position sizing, outer holdout and formal performance remain `null`/closed.
- Repository instruction overrides skill commit cadence: do not commit or push.

### Task 1: Build The Causal Daily Phase Panel

**Files:**
- Create: `alphaagent/server/services/low_suction/daily_phase_study.py`
- Create: `tests/alphaagent/services/low_suction/test_daily_phase_study.py`

- [x] **Step 1: Write failing scope and causality tests**

Add fixtures with two main-board stocks, one ChiNext stock, stock bars, concept bars, market returns and outcome-neutral spell-day candidates. Assert that only offsets 1-4 and main-board symbols remain, event IDs are unique, and future mutations do not alter existing rows:

```python
baseline = build_daily_phase_panel(
    candidates,
    stock_bars,
    concept_bars,
    market_returns,
    trading_dates=calendar,
)
mutated = stock_bars.copy()
mutated.loc[mutated["trade_date"] > context_date, "close_price"] = 999.0
changed = build_daily_phase_panel(
    candidates,
    mutated,
    concept_bars,
    market_returns,
    trading_dates=calendar,
)
pd.testing.assert_frame_equal(baseline, changed)
assert baseline["spell_session_offset"].between(1, 4).all()
assert not baseline["vt_symbol"].str.startswith(("300", "301", "688", "689")).any()
```

- [x] **Step 2: Run the new test and verify import failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_daily_phase_study.py -q
```

Expected: collection fails because `daily_phase_study.py` does not exist.

- [x] **Step 3: Implement point-in-time feature panels**

Create these public constants and function:

```python
PHASES = (
    "first_launch",
    "divergence_restart",
    "continuous_acceleration",
    "climax_risk",
    "healthy_pullback",
    "trend_continuation",
    "decay",
    "unclassified",
)
STUDY_OFFSETS = (1, 2, 3, 4)

def build_daily_phase_panel(
    candidates: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
    market_returns: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> pd.DataFrame:
    """Attach D-1 causal features and one mutually exclusive leader phase."""
```

Reindex every stock and concept to the frozen calendar before rolling calculations. Compute daily return, MA5/10/20, 3/5-day returns, current strong-day run, previous 5/10-session strong-day counts, prior-five volume ratio, stock-minus-concept and stock-minus-market three-day returns, and the one-day change in concept excess. Reject future/outcome columns and duplicate stock/concept/date identities.

- [x] **Step 4: Implement the frozen classifier and attribution fields**

Add one private classifier that applies the exact precedence in the frozen contract. Emit `phase_reason`, `phase_feature_complete`, `volume_class`, `relative_strength_state`, `market_regime`, `feature_cutoff_date`, and a stable string event ID from `(leader_spell_id, context_date)`. Assert exactly one phase per row and no duplicate `(vt_symbol, entry_date)` rows survive.

- [x] **Step 5: Add exact boundary and precedence tests**

Build separate rows for first launch, restart, two-day acceleration, three-day climax, healthy pullback, trend continuation, decay and incomplete history. Test the 9.5%, volume 0.8/1.5/2.5 and MA equality boundaries. Prove that a three-day run is climax rather than acceleration and a broken concept cycle is decay rather than launch.

- [x] **Step 6: Run scoped tests**

Run the Task 1 command. Expected: all phase panel tests pass.

### Task 2: Execute Normal And Double-cost Daily Holds

**Files:**
- Modify: `alphaagent/server/services/low_suction/daily_phase_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_daily_phase_study.py`

- [x] **Step 1: Write failing execution tests**

Use deterministic bars to prove the signal date equals context D-1, entry is D open, exit is D+1 close, 2x costs never improve returns, and limit-up entry is rejected:

```python
normal, stressed = execute_daily_phase_holds(
    phase_panel,
    daily_bars,
    trading_dates=calendar,
)
assert normal.iloc[0]["entry_date"] == pd.Timestamp(d_date)
assert normal.iloc[0]["exit_date"] == pd.Timestamp(d_plus_1)
assert stressed.iloc[0]["net_return_pct"] < normal.iloc[0]["net_return_pct"]
```

- [x] **Step 2: Implement the execution adapter**

Add:

```python
def execute_daily_phase_holds(
    phase_panel: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    trading_dates: Sequence[date],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Execute D-open/D+1-close outcomes under normal and double costs."""
```

Reuse `execute_stock_main_rise_hold()` rather than duplicate cash arithmetic. Keep only `entry_plus_1_close` outcomes and require one normal/stressed row per phase event.

- [x] **Step 3: Join the complete stock-level trade ledger**

Add `build_daily_phase_trade_ledger(panel, normal, stressed)` and retain phase identity, actual stock/concept/date fields, causal features, block, normal/stressed status and reason, raw/executed prices, fees and returns. Do not remove rejected or unclosed observations.

- [x] **Step 4: Run scoped tests**

Expected: all phase and execution tests pass.

### Task 3: Build Stability, Volume, Relative-strength And Regime Metrics

**Files:**
- Modify: `alphaagent/server/services/low_suction/daily_phase_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_daily_phase_study.py`

- [x] **Step 1: Write failing metric-gate tests**

Construct synthetic early/late rows at exact 50%/60% boundaries and test strictness, minimum trades/dates, double-cost failure, four-positive-block requirement and 20% concentration failure.

- [x] **Step 2: Implement reusable metric summaries**

Add:

```python
def build_daily_phase_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize every phase over all, early/late and block 1-5 segments."""

def build_daily_phase_attribution_metrics(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarize phase x volume, relative-strength and market-regime cohorts."""
```

Report observations, closed trades, entry dates, spells, stocks, concepts, win rate, mean, median, PF, 5% tail, double-cost win/mean, positive profit and maximum stock/concept/month positive-profit shares. Attribution segments are `all`, `early_1_3`, and `late_4_5`; do not select a winning cohort.

- [x] **Step 3: Implement stable phase evaluation**

Add `evaluate_daily_phase_candidates(metrics)` returning every phase's early/late labels, positive block count, concentration checks and `stable_high_win_candidate`. Risk/control phases (`climax_risk`, `decay`, `unclassified`) remain reportable but never become eligible minute-research phases.

- [x] **Step 4: Test chronological and shuffle invariance**

Assign five blocks from unique entry dates with `chronological_event_blocks()`. Prove input row shuffling does not change metrics and that each date belongs to exactly one block.

- [x] **Step 5: Run scoped tests**

Expected: all daily phase tests pass.

### Task 4: Loader, Report And CLI

**Files:**
- Modify: `alphaagent/server/services/low_suction/daily_phase_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_daily_phase_study.py`

- [x] **Step 1: Build one bounded discovery loader**

Load event recognition, cycle inputs and timing once; rebuild the comparison spell days with `build_event_neutral_comparison_days()`, then build phases, blocks, normal/stressed outcomes and the complete ledger. Fingerprint candidates, phase panel, both outcome sets and ledger. Assert `discovery_end`, no outer holdout reads, no current-member reads, no minute rows, no old low-suction trades and no limit-up strategy rows.

- [x] **Step 2: Build JSON and Markdown reports**

Add:

```python
def run_daily_phase_study() -> dict[str, Any]: ...
def render_daily_phase_json(report: Mapping[str, Any]) -> str: ...
def render_daily_phase_markdown(report: Mapping[str, Any]) -> str: ...
```

The machine report must include the frozen contract, coverage, input fingerprints, phase prevalence, stage metrics, candidate evaluation, all attribution metrics, complete individual trade ledger, deterministic best/worst stock cases, limitations and one bounded conclusion: `stable_high_win_phase_candidate_found`, `positive_phase_only`, or `no_stable_daily_phase_edge`.

- [x] **Step 3: Register a frozen CLI**

Add `v2-daily-phase-study` with only `--format {json,markdown}` and `--output`. Tests must prove there are no phase thresholds, date ranges, entry prices, exits, costs, regime switches or selection parameters.

- [x] **Step 4: Run scoped tests**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_daily_phase_study.py \
  tests/alphaagent/services/low_suction/test_individual_leader_study.py \
  tests/alphaagent/services/low_suction/test_stock_main_rise_audit.py -q
```

Expected: all tests pass.

### Task 5: Real Historical Run And Durable Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_daily_phase_hold_study_20260717.json`
- Create: `memory/06_backtests/low_suction_daily_phase_hold_study_20260717.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `docs/superpowers/plans/2026-07-17-low-suction-daily-phase-hold-study.md`

- [x] **Step 1: Run the real study once in the API container**

Run JSON and Markdown from the same code revision:

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-daily-phase-study --format json \
  --output memory/06_backtests/low_suction_daily_phase_hold_study_20260717.json

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-daily-phase-study --format markdown \
  --output memory/06_backtests/low_suction_daily_phase_hold_study_20260717.md
```

- [x] **Step 2: Inspect individual winners and losers before accepting aggregates**

Verify at least the largest positive and negative trades for each eligible phase against the ledger's actual stock name, context date, entry/exit prices, phase features and source bars. Record whether a result is broad or concentrated; do not create stock whitelists.

- [x] **Step 3: Record the next decision**

If exactly one eligible phase is a stable high-win candidate, freeze it only as the mother sample for a separate 5-minute pullback/acceptance study. If no phase qualifies, stop minute-entry work on this proxy and move to a separately preregistered pre-breakout/emotion-anticipation study or wait for strict historical Top3. Gold/silver and volume may explain outcomes but cannot rescue a failed phase by post-hoc filtering.

- [x] **Step 4: Update durable memory in place**

Add one concise evidence-index entry and replace the prior open-work item with the verified phase result. Keep full tables in the two new artifacts rather than duplicating them in overview memory.

### Task 6: Final Verification And Evidence Integrity

**Files:**
- Modify: `docs/superpowers/plans/2026-07-17-low-suction-daily-phase-hold-study.md`

- [x] **Step 1: Run the full low-suction test suite**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
```

- [x] **Step 2: Run static and syntax checks**

```bash
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
git diff --check
```

- [x] **Step 3: Verify machine evidence and immutable boundaries**

Parse the new JSON, calculate its SHA256, and confirm:

- `formal_metrics` and cash compounding are `null`.
- `formal_rule_selected`, `strict_top3_claim` and `holdout_price_values_read` are false.
- current-member, minute, old-low-suction-trade and limit-up-strategy row reads are zero.
- only main-board symbols and offsets 1-4 exist in the phase ledger.
- normal and double-cost outcomes have identical event identities.
- the previous individual leader JSON retains SHA256 `85f7b033e14bad875c879d4e9d350fda8b850633594038fbd6750cd30751a8d3`.

- [x] **Step 4: Mark every completed plan checkbox**

Only mark a step complete after its command or artifact has been verified. Do not commit or push.

## Completion Boundary

Completion means AlphaAgent has a reproducible, stock-level, daily lifecycle study that answers whether any causal leader phase materially improves D+1 win rate and expectation in the current event-recognition proxy, with actual stock evidence and all required stability diagnostics. It does not mean a low-suction entry, strict Top3 identity, gold/silver switch, portfolio, compounding result or production strategy has been selected.
