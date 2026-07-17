# Cycle Leader Pullback Moment Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enumerate the leaders in every observed concept main-rise period, then locate and analyze all frozen intraday pullback-recovery moments for oracle and causally identifiable leaders.

**Architecture:** Separate period identity from entry analysis. A cycle-level module builds all observed concept periods, retrospective period leader labels and D-1 dynamic leader ranks; a second module attaches those identities to complete candidate-only 5-minute paths, extracts outcome-independent pullback moments, applies the existing D+1 cash execution, and reports oracle descriptions separately from causal evidence.

**Tech Stack:** Python 3.11, pandas, NumPy, SQLAlchemy, pytest, existing AlphaAgent concept-cycle, event-neutral minute and cash execution contracts.

---

## Frozen Contract

- `period` means one frozen `breakout_trend` concept cycle, keyed by `(sector_id, cycle_id)`.
- Historical member completeness is unavailable. The period candidate set is every main-board stock actually observed by the existing event-recognition evidence during that cycle. Reports must say `event_candidate_pool`, never strict concept-member Top3.
- Every observed period is retained. Periods with fewer than three candidates or still active at the discovery boundary are listed with an explicit status rather than silently dropped.
- Retrospective identities are labels only:
  - `realized_market_rank`: maximum consecutive near-limit-up days, total near-limit-up days, full-period excess return, then symbol.
  - `realized_return_rank`: full-period excess return, full-period stock return, strong-day count, then symbol.
  - These ranks use the completed period and cannot generate historical orders.
- Causal dynamic identity uses only stocks recognized by D-1 and bars through D-1:
  - maximum consecutive near-limit-up days to date;
  - cumulative near-limit-up days to date;
  - stock-minus-concept return since cycle start;
  - trailing 20-session traded-value proxy;
  - stable symbol tie-break.
  - Dynamic Top3 is qualified only when at least three candidates were already recognized.
- Frozen pullback moments, each selected once per candidate day and rule:
  - `ma5_touch_hold`: completed 5m low touches D-1 MA5 and closes at/above it.
  - `ma10_touch_hold`: completed 5m low touches D-1 MA10 and closes at/above it.
  - `vwap_reclaim`: prior completed close below prior VWAP, current completed close at/above current VWAP.
  - `drawdown_1_reversal`: at least 1% below the running session high, after a non-rising bar, then first higher close.
  - `drawdown_3_reversal`: the same transition after at least 3% drawdown.
- Buy at the next 5m open and exit at the existing first sellable D+1 official close with normal and double costs.
- Oracle leader outcomes are descriptive selection-bias diagnostics. Only qualified D-1 dynamic Top1/Top3 rows enter causal metrics.
- Blocks 1-3 remain development diagnostics and blocks 4-5 reused chronological validation diagnostics. No outer holdout or production selection occurs.

### Task 1: Period and realized-leader ledgers

**Files:**
- Create: `alphaagent/server/services/low_suction/cycle_leader_study.py`
- Create: `tests/alphaagent/services/low_suction/test_cycle_leader_study.py`

- [x] **Step 1: Write failing period tests**

Build two synthetic `breakout_trend` cycles, one completed and one censored. Assert `build_observed_cycle_periods()` returns every candidate-bearing cycle with start/end, active sessions, candidate count and status.

- [x] **Step 2: Write failing realized-rank tests**

Use three stocks with different strong-day runs and full-period returns. Assert `build_realized_cycle_leaders()` produces both deterministic ranks, retains all candidates and never exposes the realized columns to a causal ranking function.

- [x] **Step 3: Run the focused file and confirm import failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_study.py -q
```

Expected: collection fails because `cycle_leader_study` does not exist.

- [x] **Step 4: Implement period and realized ledgers**

Add:

```python
def build_observed_cycle_periods(
    cycle_states: pd.DataFrame,
    candidate_spells: pd.DataFrame,
) -> pd.DataFrame:
    """Return every observed candidate-bearing breakout-trend period."""

def build_realized_cycle_leaders(
    periods: pd.DataFrame,
    candidate_spells: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Attach retrospective market and return ranks for period analysis."""
```

Reject future/outcome columns from period construction, require unique stock/date bars and use explicit `realized_` names for all retrospective fields.

- [x] **Step 5: Run focused tests**

Expected: period and realized-rank tests pass.

### Task 2: D-1 dynamic leader ledger

**Files:**
- Modify: `alphaagent/server/services/low_suction/cycle_leader_study.py`
- Modify: `tests/alphaagent/services/low_suction/test_cycle_leader_study.py`

- [x] **Step 1: Write failing dynamic-rank tests**

Assert candidates are unavailable before their recognition date, every feature cutoff is D-1, fewer than three recognized stocks leaves Top3 unqualified, and mutating D or later prices cannot change D's dynamic rank.

- [x] **Step 2: Implement causal dynamic ranking**

Add:

```python
def build_dynamic_cycle_leaders(
    periods: pd.DataFrame,
    candidate_spells: pd.DataFrame,
    target_sessions: pd.DataFrame,
    stock_bars: pd.DataFrame,
    concept_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Rank the recognized event-candidate pool using D-1 evidence only."""
```

Return one row per `(cycle_id, entry_date, vt_symbol)` with feature values, pool size, rank, Top1/Top3 flags and qualification status.

- [x] **Step 3: Add period summary tests and implementation**

`build_cycle_leader_summary()` must list all periods, realized market/return Top3 names, the number of dynamic sessions, distinct dynamic Top1 stocks and realized-market-Top1 retention inside qualified dynamic Top3.

- [x] **Step 4: Run focused tests and Ruff**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_study.py -q
uvx ruff check alphaagent/server/services/low_suction/cycle_leader_study.py tests/alphaagent/services/low_suction/test_cycle_leader_study.py
```

Expected: all pass.

### Task 3: Complete minutes and frozen pullback moments

**Files:**
- Modify: `alphaagent/server/services/low_suction/event_neutral_minutes.py`
- Create: `alphaagent/server/services/low_suction/leader_pullback_moment_study.py`
- Create: `tests/alphaagent/services/low_suction/test_leader_pullback_moment_study.py`

- [x] **Step 1: Write failing complete-minute loader test**

Assert the public loader returns all OHLCV/turnover fields only when every candidate pair has exactly 48 bars, and fails closed for an incomplete manifest.

- [x] **Step 2: Implement the complete-minute loader**

Add `load_complete_event_neutral_5m_bars(candidates)` to `event_neutral_minutes.py`; reuse its manifest contract and filter exact stock/date pairs.

- [x] **Step 3: Write failing moment tests**

Construct complete 48-bar paths and assert all five frozen moments use only completed bars, select the first event/rule timestamp, enter at the next bar open, and do not change when later bars mutate.

- [x] **Step 4: Implement identity attachment and moments**

Add:

```python
def attach_cycle_leader_identities(
    candidates: pd.DataFrame,
    dynamic_leaders: pd.DataFrame,
    realized_leaders: pd.DataFrame,
) -> pd.DataFrame:
    """Attach causal and oracle identities without mixing their columns."""

def build_leader_pullback_moments(
    identified_candidates: pd.DataFrame,
    minute_bars: pd.DataFrame,
) -> pd.DataFrame:
    """Extract the first executable moment for each frozen pullback rule."""
```

- [x] **Step 5: Reuse D+1 labels and run focused tests**

Normal and double-cost labels must attach only after moment identity is frozen. Expected: all moment tests pass.

### Task 4: Metrics, complete period report and CLI

**Files:**
- Modify: `alphaagent/server/services/low_suction/leader_pullback_moment_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_leader_pullback_moment_study.py`

- [x] **Step 1: Write failing metric/report tests**

Assert causal and oracle tables are separate, dynamic Top3 metrics exclude pools below three, time splits and daily compounding are present, all period rows survive Markdown/JSON rendering, and formal metrics/rule selection remain null/false.

- [x] **Step 2: Implement membership and metrics**

Produce causal rule tables for qualified dynamic Top1/Top3 and descriptive tables for realized market/return Top1/Top3. Add causal one-dimension attribution for time bucket, drawdown bucket, signal volume and GOLD/SILVER; attribution cannot select a rule.

- [x] **Step 3: Implement real-data loader and deterministic report**

Load event-neutral candidates, cycle states, stock/concept bars and complete 5m paths once per command. Persist every period summary and every pullback moment in JSON; Markdown must print all observed periods plus causal and oracle metric tables.

- [x] **Step 4: Register the read-only CLI**

Add `v2-cycle-leader-pullback-study` with only `--format` and `--output` controls.

- [x] **Step 5: Run focused verification**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_cycle_leader_study.py tests/alphaagent/services/low_suction/test_leader_pullback_moment_study.py -q
uvx ruff check alphaagent/server/services/low_suction/cycle_leader_study.py alphaagent/server/services/low_suction/leader_pullback_moment_study.py alphaagent/server/services/low_suction/event_neutral_minutes.py tests/alphaagent/services/low_suction/test_cycle_leader_study.py tests/alphaagent/services/low_suction/test_leader_pullback_moment_study.py alphaagent/server/services/low_suction/cli.py
```

Expected: all pass.

### Task 5: Run the 53-period study and preserve evidence

**Files:**
- Create: `memory/06_backtests/low_suction_cycle_leader_pullback_moment_study_20260717.md`
- Create: `memory/06_backtests/low_suction_cycle_leader_pullback_moment_study_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Generate both artifacts**

```bash
uv run python -m alphaagent.server.services.low_suction.cli v2-cycle-leader-pullback-study --format markdown --output memory/06_backtests/low_suction_cycle_leader_pullback_moment_study_20260717.md
uv run python -m alphaagent.server.services.low_suction.cli v2-cycle-leader-pullback-study --format json --output memory/06_backtests/low_suction_cycle_leader_pullback_moment_study_20260717.json
```

- [x] **Step 2: Inspect before concluding**

Report how many periods have three candidates, how often the realized leader was inside qualified dynamic Top3, every rule's development/validation trades, days, win rate, ordinary/double-cost mean, profit factor, compound return and drawdown. State whether any apparent oracle edge disappears under causal identity.

- [x] **Step 3: Update durable memory**

Link the evidence and record only current conclusions, identity limitations and the next actionable data/research step.

- [x] **Step 4: Run full regression verification**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
uvx ruff check alphaagent/server/services/low_suction tests/alphaagent/services/low_suction
uv run python -m compileall -q alphaagent/server/services/low_suction
uv run python -m json.tool memory/06_backtests/low_suction_cycle_leader_pullback_moment_study_20260717.json >/dev/null
git diff --check
```

Expected: all pass. Do not commit or push without explicit user authorization.

## Self-Review

- Coverage: every observed candidate-bearing concept cycle is preserved, not only profitable cycles or cycles with a pullback signal.
- Identity separation: `realized_*` columns are outcome labels; only D-1 `dynamic_*` ranks enter causal metrics.
- Entry causality: every moment uses completed 5m bars and buys at the next bar open.
- Search boundary: five moment definitions and all depth thresholds are frozen before reading outcomes.
- Claim boundary: incomplete historical membership prevents a strict all-member concept Top3 claim regardless of observed metrics.
