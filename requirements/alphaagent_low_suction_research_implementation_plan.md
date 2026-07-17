# AlphaAgent Low-Suction Historical Research Implementation Plan

> **Status: superseded V1 implementation evidence. Do not execute this plan.** It records the completed
> family-based proxy foundation that was invalidated as a research direction. The current design is
> `requirements/alphaagent_low_suction_research_reset_design.md`; the executable V2 plan is
> `docs/superpowers/plans/2026-07-16-low-suction-research-direction-v2.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Build an independent, no-lookahead research pipeline that audits whether AlphaAgent can study main-rise concept Top3 low-suction trades, runs clearly labelled exploratory analysis when strict inputs are unavailable, and only reports formal win rate or compounding when every strict data gate passes.

**Architecture:** The new `services/low_suction` package owns its data contract, main-rise state, point-in-time Top3 rank, event families, outcomes, and portfolio evaluation. It reads preserved raw tables and the neutral cash ledger but never imports limit-up strategy rules or removed quant/backtest code. Strict and proxy evidence use separate result objects: proxy events can discover hypotheses, while qualification metrics remain `null` until historical membership, security status, concept bars, and candidate minute paths are strict.

**Tech Stack:** Python 3.11+, pandas, NumPy, SQLAlchemy Core, PostgreSQL 16, pytest, existing AlphaAgent cash execution math.

---

## Research Discipline

- Do not modify `vnpy/` or official examples.
- Do not import from removed `services.quant` or `services.backtest` packages.
- Do not import signal rules from `services.limit_up`; only raw database tables and `services.execution.cash_ledger` may be shared.
- Do not create the low-suction UI until a reproducible research report exists.
- Do not write a formal win rate, compounded return, profit factor, or maximum drawdown from `membership_proxy` or `daily_discovery` samples.
- A D-day close-derived signal can execute no earlier than D+1 open. An intraday signal can execute no earlier than the next valid one-minute bar.
- Current stock names cannot prove historical non-ST status. Current sector members cannot prove historical concept membership.
- Tushare `ths_member` documents `in_date/out_date` as unavailable; it is not a strict historical-membership source unless returned data is independently shown to contain valid intervals.
- Replace commit steps with `git diff --check`, focused tests, and status checkpoints.

## Fixed Research Contract

```python
STRICT_MIN_TRADE_DAYS = 720
STRICT_MIN_CALENDAR_DAYS = 1_095
STRICT_MIN_MEMBERSHIP_COVERAGE_PCT = 90.0
STRICT_MIN_CONCEPT_BAR_COVERAGE_PCT = 90.0
STRICT_MIN_CLOSED_TRADES = 300
STRICT_MAX_DRAWDOWN_PCT = 10.0
MAIN_BOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
EVIDENCE_LEVELS = ("strict", "daily_discovery", "membership_proxy", "invalid")
DAILY_PROXY_EXIT_KEYS = ("entry_plus_1_close", "entry_plus_3_close", "entry_plus_5_close")
```

The daily proxy runner uses D close as the observation cutoff and D+1 open as its earliest entry. It is not allowed to claim intraday low-suction execution.

### Task 1: Freeze The Data-Quality Contract

**Files:**
- Create: `alphaagent/server/services/low_suction/__init__.py`
- Create: `alphaagent/server/services/low_suction/contracts.py`
- Create: `alphaagent/server/services/low_suction/data_quality.py`
- Create: `tests/alphaagent/services/low_suction/__init__.py`
- Create: `tests/alphaagent/services/low_suction/test_data_quality.py`

- [x] **Step 1: Write failing gate tests**

Cover strict readiness, proxy-only readiness, missing security history, insufficient span,
candidate minute gaps, insufficient closed trades, and zero-trade fail-closed behavior:

```python
def test_strict_metrics_are_null_when_membership_is_proxy() -> None:
    report = evaluate_data_quality(_coverage(concept_membership_mode="current_proxy"))
    assert report["status"] == "blocked_by_data_quality"
    assert report["formal_metrics"] is None
    assert "historical_concept_membership" in report["blocking_gaps"]


def test_zero_closed_trades_never_passes_drawdown_gate() -> None:
    decision = evaluate_qualification(
        closed_trades=0,
        compounded_return_pct=0.0,
        profit_factor=None,
        maximum_drawdown_pct=0.0,
        double_cost_return_pct=0.0,
    )
    assert decision["status"] == "insufficient_sample"
    assert decision["qualified"] is False
```

- [x] **Step 2: Run tests and confirm the module is missing**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_data_quality.py -q
```

Expected: FAIL during import because `services.low_suction` does not exist.

- [x] **Step 3: Implement immutable contracts and pure gates**

Define `CoverageSnapshot`, `DataQualityDecision`, and `QualificationDecision` as frozen
dataclasses. `evaluate_data_quality()` returns `strict_ready=False` if any of these are
absent: 720 reliable trade days over at least 1,095 calendar days, 90% strict concept
membership, 90% concept-bar coverage, historical ST/listing/delist status, and complete
minute paths for the evaluated candidate pairs.

`evaluate_qualification()` requires at least 300 closed strict trades, positive holdout
compounding, profit factor above 1, maximum drawdown no worse than -10%, and positive
double-cost return.

- [x] **Step 4: Run the focused tests**

Expected: all data-quality tests pass.

### Task 2: Add A Read-Only Coverage Repository

**Files:**
- Create: `alphaagent/server/services/low_suction/data_quality_repository.py`
- Modify: `tests/alphaagent/services/low_suction/test_data_quality.py`

- [x] **Step 1: Add SQL boundary tests**

```python
def test_repository_never_uses_current_members_as_strict_history() -> None:
    source = Path(
        "alphaagent/server/services/low_suction/data_quality_repository.py"
    ).read_text()
    assert "stock_sector_membership_snapshots" in source
    assert '"current_proxy"' in source
    assert "services.limit_up" not in source
    assert "services.quant" not in source
```

Add fixture-driven tests proving a D-day 19:00 membership snapshot becomes usable on
D+1, never for D intraday.

- [x] **Step 2: Implement coverage queries**

`load_coverage_snapshot()` returns exact counts/ranges for reliable stock daily bars,
theme daily bars and cross-sections, theme membership snapshots and capture times,
historical security status, candidate one-minute pairs, market timing states, 龙虎榜,
auction, and fund-flow inputs.

Current `stock_sector_memberships` must be classified as `membership_proxy`. Raw
snapshot dates and their next-session effective dates must both be exposed.

- [x] **Step 3: Verify against PostgreSQL without writing**

```bash
docker compose exec -T alphaagent-api python -c \
  'import json; from alphaagent.server.services.low_suction.data_quality_repository import load_data_quality_report; print(json.dumps(load_data_quality_report(), ensure_ascii=False))'
```

Expected on the 2026-07-16 dataset: `blocked_by_data_quality`, formal metrics `null`,
603 reliable stock dates, about 253 concept-index dates, three raw membership snapshot
dates, and zero historical security-status dates.

### Task 3: Add A Reproducible Audit CLI And Evidence Report

**Files:**
- Create: `alphaagent/server/services/low_suction/cli.py`
- Create: `alphaagent/server/services/low_suction/reporting.py`
- Create: `tests/alphaagent/services/low_suction/test_reporting.py`
- Create: `memory/06_backtests/low_suction_data_quality_20260716.md`
- Modify: `memory/06_backtests/README.md`

- [x] **Step 1: Test deterministic JSON and Markdown output**

Use a fixed snapshot and assert stable key order, explicit `null` formal metrics,
blocking-gap labels, source ranges, and a reproducible command section.

- [x] **Step 2: Implement CLI modes**

```text
audit --format json
audit --format markdown --output <path>
```

The CLI rejects output paths outside `memory/06_backtests/` unless using stdout. It
never prints database credentials. Task 8 adds `proxy-discovery`; Task 10 adds
`minute-manifest` after their service modules exist.

- [x] **Step 3: Generate the actual audit report**

```bash
docker compose exec -T alphaagent-api python -m \
  alphaagent.server.services.low_suction.cli audit --format markdown
```

Write the verified output to `memory/06_backtests/low_suction_data_quality_20260716.md`.

### Task 4: Implement No-Lookahead Main-Rise Concept States

**Files:**
- Create: `alphaagent/server/services/low_suction/main_rise.py`
- Create: `tests/alphaagent/services/low_suction/test_main_rise.py`

- [x] **Step 1: Write pure state tests**

Test the approved definition:

```python
close > ma10 > ma20
ma10 > ma10_shift_5
ma20 > ma20_shift_5
```

The state for D uses bars through D only. A D+1 mutation cannot change D. Missing
20-bar history returns `UNKNOWN`, and sparse dates are not forward filled.

- [x] **Step 2: Implement `build_main_rise_states()`**

Input columns are `sector_id`, `trade_date`, `close_price`, and optional continuous
features. Output includes state, MA values, five-session slopes, source date, and
evidence level. Keep returns, high distance, turnover acceleration, and market timing
as features rather than additional hard gates.

- [x] **Step 3: Run the focused tests**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction/test_main_rise.py -q
```

### Task 5: Implement Point-In-Time Main-Board Top3 Ranking

**Files:**
- Create: `alphaagent/server/services/low_suction/universe.py`
- Create: `alphaagent/server/services/low_suction/leader_rank.py`
- Create: `tests/alphaagent/services/low_suction/test_universe.py`
- Create: `tests/alphaagent/services/low_suction/test_leader_rank.py`

- [x] **Step 1: Test board and historical security filters**

Fixtures cover SSE `600/601/603/605`, SZSE `000/001/002/003`, ChiNext `300`, STAR
`688`, BSE `4/8/92`, ST, delisted, suspended, and stocks listed fewer than 60 sessions.
Eligibility depends on the supplied D-day security record, not current `stocks.name`.

- [x] **Step 2: Test deterministic Top3 ranking**

`rank_concept_leaders()` uses only values timestamped `<= cutoff`. It computes five
fixed 20% blocks: relative strength, active gene, drawdown resilience, liquidity, and
concept leadership. Each is a within-concept percentile. Tie-breakers are score,
turnover, then `vt_symbol`.

Tests mutate D+1 bars/outcomes and prove D ranks are unchanged. Outcome columns cause
`ValueError` if supplied to the ranker.

- [x] **Step 3: Implement strict and proxy rank modes**

Strict mode accepts only membership valid on D. Proxy mode stamps every rank
`membership_proxy`. Output contains five block scores, total, rank, cutoff, membership
source, and exclusion reason.

### Task 6: Build Three Daily Discovery Event Families

**Files:**
- Create: `alphaagent/server/services/low_suction/events.py`
- Create: `tests/alphaagent/services/low_suction/test_events.py`

- [x] **Step 1: Write event and isolation tests**

Cover `first_divergence`, `first_bearish_or_break_repair`, and
`second_wave_pullback`. Each event is a concept Top3 member in main rise. Adjacent
signals in one stock/concept/rise cycle merge into the first event. Overlap creates one
event with `family_tags`.

- [x] **Step 2: Implement close-cutoff discovery rules**

The discovery version observes D close and executes no earlier than D+1 open. Record
continuous pullback depth, MA proxies, volume contraction, prior strong days, and
concept-relative return. Do not optimize thresholds here.

- [x] **Step 3: Reject outcome leakage**

The builder rejects columns prefixed `future_`, `outcome_`, `mfe_`, `mae_`, or
`exit_`. Changing D+1..D+5 prices cannot alter D identity.

### Task 7: Generate Fixed Outcomes And Time Splits

**Files:**
- Create: `alphaagent/server/services/low_suction/outcomes.py`
- Create: `alphaagent/server/services/low_suction/time_split.py`
- Create: `tests/alphaagent/services/low_suction/test_outcomes.py`
- Create: `tests/alphaagent/services/low_suction/test_time_split.py`

- [x] **Step 1: Test executable daily outcomes**

Daily discovery enters at D+1 open plus costs. Because that position cannot be sold on
its entry date, test entry+1/entry+3/entry+5 session close exits, suspension, missing
bars, limit-up inability to buy, limit-down inability to sell, T+1, and 100-share lots.
Raw and cost-adjusted returns remain separate. The strict intraday task retains the
user-requested D+1/D+3/D+5 exit labels because its entry occurs on D.

- [x] **Step 2: Implement chronological 60/20/20 splits**

Split unique event dates. Freeze all family/exit/position choices before the last 20%.
The locked holdout accepts a frozen config and rejects a parameter grid.

- [x] **Step 3: Add grouped uncertainty**

Bootstrap by trade date plus concept rise-cycle ID. Report 95% intervals for win rate
and mean return; correlated stocks in one concept/day are not independent draws.

### Task 8: Run The Membership-Proxy Discovery Matrix

**Files:**
- Create: `alphaagent/server/services/low_suction/repository.py`
- Create: `alphaagent/server/services/low_suction/daily_discovery.py`
- Create: `tests/alphaagent/services/low_suction/test_daily_discovery.py`
- Create: `memory/06_backtests/low_suction_proxy_discovery_20260716.md`

- [x] **Step 1: Load only the reliable overlap window**

Require reliable stock dates and complete theme cross-sections. Load leading bars for
MA20 and rank features. Do not forward-fill partial sector dates after `2026-06-29`.

- [x] **Step 2: Produce the matrix and falsification groups**

Group by family, month, entry gap, pullback, concept-state age, rank, GOLD/SILVER,
DANGER, and exit. Include ranks 4-10 and non-main-rise concepts as falsification rows.
Report count, win rate, mean/median, expected return, profit factor, and concentration,
all labelled `exploratory membership_proxy`.

- [x] **Step 3: Generate the report**

State that proxy results cannot select a production rule, list survivorship risks,
identify families/exits worth strict retesting, and leave formal qualification as
`blocked_by_data_quality`.

### Task 9: Define Strict Historical Input Imports

**Files:**
- Create: `alphaagent/server/services/low_suction/historical_inputs.py`
- Create: `tests/alphaagent/services/low_suction/test_historical_inputs.py`
- Modify only if required: `alphaagent/server/db/schema.py`

- [x] **Step 1: Test membership interval semantics**

Accepted rows contain `sector_id`, `sector_name`, `vt_symbol`, `in_date`, `out_date`,
`known_at`, `source`, and `source_record_id`. Validity is
`in_date <= D < out_date` and `known_at <= D 09:25 Asia/Shanghai`. Empty or
provider-documented unavailable intervals cannot become strict.

- [x] **Step 2: Test historical security records**

Records include listing/delisting dates, name/status validity, board, suspension, and
`known_at`. The importer retains delisted securities and historical ST intervals.

- [x] **Step 3: Fail atomically on partial responses**

Existing strict data remains until replacement date/sector/symbol coverage passes.
Dry-run output reports prospective counts without writing.

### Task 10: Add Candidate-Directed Minute Research

**Files:**
- Create: `alphaagent/server/services/low_suction/minute_manifest.py`
- Create: `alphaagent/server/services/low_suction/minute_entry.py`
- Create: `tests/alphaagent/services/low_suction/test_minute_entry.py`

- [x] **Step 1: Generate candidate-only minute gaps**

Manifest rows contain event ID, symbol, date, required window, existing bars, source,
and rejection reason. Never request all-market multi-year minutes.

- [x] **Step 2: Test next-bar execution and fixed exits**

A t-minute signal fills only at the next valid minute open plus slippage. Test lunch,
14:55 cutoff, zero volume, suspension, limit prices, T+1, lots, all fees, and double
cost. Compare D+1 10:00, D+1 14:30, D+1 close, D+3 close, and D+5 close.

### Task 11: Build The Public Hot-Money Method Evidence Matrix

**Files:**
- Create: `memory/06_backtests/low_suction_hot_money_method_evidence.md`

- [x] **Step 1: Record source quality before claims**

Each row contains title, URL, publication date, access date, source type, named speaker,
first-person status, original claim, observable proxy, local sample, out-of-sample
result, failures, and disposition.

- [x] **Step 2: Separate identity from observable behavior**

Tushare `hm_list/hm_detail` and 龙虎榜 mappings do not prove a natural person's
identity. Seat labels remain stratification variables, never mandatory buy conditions.

- [x] **Step 3: Translate only testable concepts**

Allowed hypotheses are mainline status, Top3 leadership, first divergence, shrinking
sell volume, support recovery, weak-to-strong, second-wave structure, and distribution
risk. Reject slogans with no timestamped proxy.

### Task 12: Final Research Gate

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/README.md`

- [x] **Step 1: Run all low-suction tests**

```bash
uv run --group server pytest tests/alphaagent/services/low_suction -q
uv run python -m compileall alphaagent/server/services/low_suction
git diff --check
```

- [x] **Step 2: State exactly one conclusion**

The conclusion is exactly one of `blocked_by_data_quality`,
`no_qualified_strategy`, or `qualified_research_rule`. Qualification requires all
strict gates, at least 300 locked-holdout trades, drawdown within 10%, profit factor
above 1, and positive double-cost return. It remains `research_only` until 60 forward
trading days.

## Completion Boundary

This plan completes the historical research layer. It does not add alerts, automatic
orders, simulated positions, or a low-suction Tab. A product plan starts only after a
reproducible `qualified_research_rule`; otherwise `/short-term` continues to show only
the preserved limit-up research.
