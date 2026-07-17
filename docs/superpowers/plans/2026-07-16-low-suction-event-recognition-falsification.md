# Low-suction Event-recognition Falsification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible development-only study that tests whether next-session limit buys after point-in-time concept-recognition events show enough fee-adjusted edge to deserve later strict Top3 retesting.

**Architecture:** Keep this lane inside `services/low_suction` but separate from strict membership, Top3 selection, candidate minutes, the holdout lock and formal performance. Exact event reasons define an incomplete recognition cohort; frozen `breakout_trend` concept states provide the main-rise gate; daily OHLC executes pre-open limit orders without intraday lookahead. The report must call every result `event_recognition_falsification` and keep `formal_metrics=null`.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy, PostgreSQL, pytest, existing low-suction V2 protocol and cash execution helpers.

**Repository constraint:** Do not commit or push. Do not modify `vnpy/`, official examples,打板候选、打板策略、打板账本或打板绩效。

---

## File Structure

- Create `alphaagent/server/services/low_suction/event_recognition_falsification.py`: pure cohort construction, daily limit execution, fold metrics, read-only loader and deterministic report.
- Create `tests/alphaagent/services/low_suction/test_event_recognition_falsification.py`: timestamp, exact-match, ranking, fill, cost, holdout and report tests.
- Modify `alphaagent/server/services/low_suction/cli.py`: add one read-only `v2-event-falsification` command.
- Create only after a real run: `memory/06_backtests/low_suction_event_recognition_falsification_20260716.md`.
- Modify only after facts change: `memory/06_backtests/README.md` and `memory/09_decisions/decisions.md`.

## Frozen Research Contract

- Evidence class: `event_recognition_falsification`; never `strict_membership`, `strict_top3` or formal strategy evidence.
- Outer split: reuse protocol `low-suction-research-v2`; read only discovery prices through `2025-11-17`. Do not load any stock or concept price from the 160-date outer holdout.
- Source event S is usable only after S close; entry date D is the next reliable stock session.
- Concept gate: frozen `breakout_trend` must be active on S.
- Concept relation: split `raw['涨停原因']` only on `+` and require exact equality with the Eastmoney concept name. No aliases, fuzzy matching or current members.
- Candidate scope:沪深主板 symbol prefixes only; event-date name must not contain `ST`, `退市` or start with `退`; at least 60 prior stock sessions; at least three distinct eligible event stocks for the concept-day.
- Top3 label: `recognition_rank`, not membership Top3. Sort lexicographically by `limit_times` descending, one-year seal success rate descending, `fd_amount / float_market_cap` descending, amount descending, then symbol ascending.
- Cross-concept duplicate: for the same source date and stock keep the active concept with highest concept `relative_percentile`, then lowest recognition rank, then sector ID.
- Entry depths: `0%`, `2%`, `4%`, `6%` below S close. This grid is frozen before reading outcomes.
- Fill: pre-open limit order on D. If D open is at or below the limit, fill at open; otherwise fill at the limit only when D low touches it. Add 10 bps buy slippage capped at the limit and existing commission/minimum/transfer fee.
- Exit: D+1 close only. If D+1 is suspended or a one-price limit-down day, delay to the first sellable close. Apply 10 bps sell slippage, commission, transfer fee and stamp tax.
- Primary episode metrics: fills, fill rate, fee-adjusted win rate, mean/median net return, profit factor, 5% tail and maximum episode loss.
- Robustness: split the 96 event-available discovery dates chronologically into five fixed, non-overlapping
  blocks; the original V2 rolling folds are not reused because their first four validation windows predate
  the event source. No threshold is trained on these blocks. Also report double cost, monthly and concept
  concentration. A depth is merely `worth_strict_retest` only with at least 100 filled episodes, positive
  mean and PF above 1 in at least four blocks, and positive aggregate double-cost mean.
- No winner is promoted to a rule. Do not compute final 100,000 yuan cash compounding, position-count search, D+3/D+5 exits or market-regime switches in this falsification lane.
- Context diagnostic: join the already-frozen source-date `active_direction` and `danger_state`, then report
  every observed combination for every depth under normal and double cost. This table cannot change the
  overall retest gate or create a regime switch in the current run.

### Task 1: Pure Cohort Contract

**Files:**
- Create: `tests/alphaagent/services/low_suction/test_event_recognition_falsification.py`
- Create: `alphaagent/server/services/low_suction/event_recognition_falsification.py`

- [ ] **Step 1: Write failing exact-evidence and ranking tests**

```python
def test_reason_matching_is_exact_and_does_not_use_current_members() -> None:
    relations = build_exact_reason_relations(_events(), _concepts())
    assert set(relations['concept_name']) == {'商业航天'}
    assert 'memberships' not in relations.columns


def test_recognition_top3_requires_three_candidates_and_uses_lexicographic_order() -> None:
    candidates = build_recognition_candidates(
        _four_relations(), _active_breakout_state(), _calendar()
    )
    assert candidates['vt_symbol'].tolist() == [
        '600001.SSE', '600002.SSE', '600003.SSE'
    ]
    assert candidates['recognition_rank'].tolist() == [1, 2, 3]
    assert set(candidates['evidence_level']) == {'event_recognition_falsification'}
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_event_recognition_falsification.py -q
```

Expected: import failure because the module does not exist.

- [ ] **Step 3: Implement exact relation and cohort functions**

```python
EVIDENCE_LEVEL = 'event_recognition_falsification'
ENTRY_DEPTHS_PCT = (0.0, 2.0, 4.0, 6.0)
MIN_PRIOR_SESSIONS = 60


def build_exact_reason_relations(events: pd.DataFrame, concepts: pd.DataFrame) -> pd.DataFrame:
    frame = validate_event_columns(events).copy()
    frame['reason_token'] = frame['reason'].str.split('+')
    frame = frame.explode('reason_token')
    frame['reason_token'] = frame['reason_token'].str.strip()
    return frame.merge(
        concepts[['sector_id', 'concept_name']],
        left_on='reason_token',
        right_on='concept_name',
        how='inner',
        validate='many_to_many',
    ).drop_duplicates(['source_date', 'sector_id', 'vt_symbol'])
```

Implement `build_recognition_candidates()` with the frozen main-board/name/prior-session gates, at-least-three concept-day guard, lexicographic order and deterministic cross-concept deduplication. Reject any cycle-state frame containing return outcome columns.

- [ ] **Step 4: Re-run the focused tests**

Expected: all Task 1 tests pass.

### Task 2: Causal Daily Limit Execution

**Files:**
- Modify: `tests/alphaagent/services/low_suction/test_event_recognition_falsification.py`
- Modify: `alphaagent/server/services/low_suction/event_recognition_falsification.py`

- [ ] **Step 1: Write failing fill and no-lookahead tests**

```python
def test_limit_order_uses_next_session_low_but_not_close_to_decide_fill() -> None:
    outcomes = execute_frozen_limit_grid(_candidate(), _bars_touching_four_pct())
    assert outcomes.loc[outcomes['entry_depth_pct'].eq(4), 'status'].item() == 'closed'
    assert outcomes.loc[outcomes['entry_depth_pct'].eq(6), 'status'].item() == 'not_filled'


def test_loader_statement_stops_at_discovery_end() -> None:
    statement = stock_bar_statement(_symbols(), date(2025, 6, 27), date(2025, 11, 17))
    assert '2025-11-17' in str(statement.compile(compile_kwargs={'literal_binds': True}))


def test_double_cost_never_improves_net_return() -> None:
    normal = execute_frozen_limit_grid(_candidate(), _bars(), cost_multiplier=1.0)
    stressed = execute_frozen_limit_grid(_candidate(), _bars(), cost_multiplier=2.0)
    assert stressed['net_return_pct'].le(normal['net_return_pct']).all()
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Expected: missing execution and query functions.

- [ ] **Step 3: Implement fixed-grid execution**

Use `execution.cash_ledger.calculate_buy_execution()` and
`calculate_sell_execution()` with the existing low-suction rates:

```python
COMMISSION_RATE = 0.0003
MINIMUM_COMMISSION = 5.0
STAMP_TAX_RATE = 0.0005
TRANSFER_FEE_RATE = 0.00001
SLIPPAGE_BPS = 10.0
LOT_SIZE = 100
```

Return one row per candidate/depth, including `source_date`, `entry_date`, planned and actual exit date,
raw/fill prices, volume, fees, status/reason and net return. A missing fill remains in coverage counts but
never enters trade win rate.

- [ ] **Step 4: Re-run the focused tests**

Expected: all Task 2 tests pass.

### Task 3: Discovery-only Loader, Fold Metrics And CLI

**Files:**
- Modify: `tests/alphaagent/services/low_suction/test_event_recognition_falsification.py`
- Modify: `alphaagent/server/services/low_suction/event_recognition_falsification.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [ ] **Step 1: Write failing report-boundary tests**

```python
def test_report_never_exposes_formal_metrics_or_a_top3_claim() -> None:
    report = build_event_falsification_report(_inputs(), _outcomes(), _stressed())
    assert report['formal_metrics'] is None
    assert report['holdout_price_values_read'] is False
    assert report['cohort_label'] == 'recognition_top3_incomplete_denominator'


def test_retest_gate_requires_four_positive_folds_and_double_cost() -> None:
    decision = evaluate_retest_gate(_fold_metrics())
    assert decision.status == 'worth_strict_retest'
    assert decision.formal_rule_selected is False
```

- [ ] **Step 2: Implement the read-only loader and deterministic report**

`load_event_falsification_inputs()` must call `load_cycle_research_inputs()` and only retain
`definition == 'breakout_trend'` plus `in_cycle == True`. Query stock events and stock bars with explicit
`<= split.discovery_dates[-1]` predicates. Record SQL input fingerprints, reason coverage, eligible
concept-days and every rejection count.

`run_event_recognition_falsification()` builds normal and double-cost outcomes, evaluates all four depths
over five chronological event-date blocks and returns a report with `overall_conclusion` in:

```python
{
    'no_event_recognition_edge',
    'event_recognition_direction_only',
    'worth_strict_retest',
}
```

Every state retains `formal_metrics=None` and `next_stage='strict_point_in_time_top3_retest'`.

- [ ] **Step 3: Add the CLI command**

```python
event_falsification = subparsers.add_parser(
    'v2-event-falsification',
    help='run the discovery-only event-recognition falsification study',
)
event_falsification.add_argument('--format', choices=('json', 'markdown'), default='markdown')
event_falsification.add_argument('--output', type=Path)
```

Dispatch to the module renderers without accepting custom date, depth, filter or threshold flags.

- [ ] **Step 4: Run focused verification**

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction/test_event_recognition_falsification.py -q
uvx ruff check \
  alphaagent/server/services/low_suction/event_recognition_falsification.py \
  tests/alphaagent/services/low_suction/test_event_recognition_falsification.py
```

Expected: all tests and Ruff pass.

### Task 4: Real Run And Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_event_recognition_falsification_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: Run the immutable real command once**

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-event-falsification --format markdown
```

The command must report discovery end `2025-11-17`, holdout values read `false`, all four depths,
normal/double-cost results and fold counts.

- [ ] **Step 2: Write the exact result, including failures**

Record all depths, time-block results and complete GOLD/SILVER/NEUTRAL × NORMAL/DANGER diagnostics.
Do not retain only the best row. State explicitly that the cohort is
incomplete, current members were not used, formal performance is null, and the result can only reject or
nominate a direction for strict retest.

- [ ] **Step 3: Run the full scoped safety gate**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
uv run python -m compileall -q alphaagent/server/services/low_suction
git diff --check
```

Expected: all low-suction tests pass, compile succeeds and no whitespace errors are reported.

## Completion Boundary

This plan is complete when the immutable discovery-only event study has a reproducible report and an
explicit `no edge`, `direction only` or `worth strict retest` result. It does not unlock strict Top3,
minute-state discovery, the outer holdout, final 100,000 yuan cash compounding or production UI.
