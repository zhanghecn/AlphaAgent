# Low-Suction Forward Top3 Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an immutable, strict forward ledger that freezes all three return-independent leader identity modes after each completed A-share session and evaluates them only with later identity retention, strong-event lead time, and capacity.

**Architecture:** Keep the ranking calculation inside the independent low-suction package. A source session `S` may freeze ranks only when the same-date membership and security scopes are complete and strict, canonical concept indices and complete stock daily bars end at `S`, and all ranking features use values through `S` only. The ledger stores `target_session=next_trading_session` without guessing a calendar date; a later completed market session binds the real target date. Low-suction returns, entry prices, exits, GOLD/SILVER filters, minute rules, and mode selection remain unavailable while the forward sample is immature.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy/PostgreSQL, pytest, Ruff, existing AlphaAgent EOD scheduler and low-suction research contracts.

**Execution rule:** Work inline without subagents and do not commit or push, per repository instructions.

---

## Frozen Contract

- Ranking version: `low-suction-forward-top3-v1`.
- Main-rise definition: existing frozen `breakout_trend` with common `trend_order` sustain and three-session hysteresis.
- Membership evidence: exact `S` `concept_tradable` scope from `eastmoney.push2.board.forward`, `complete=true`, `evidence_level=strict`.
- Security evidence: exact `S` scope from `baostock.query_all_stock.forward`, `complete=true`, `evidence_level=strict`.
- Universe: SSE/SZSE main board only; ST, delisting/delisted, suspended, and fewer than 60 listed sessions are excluded before rank assignment.
- Features through `S` close only:
  - `cycle_relative_return`: stock return from the session before the active concept cycle start through `S`, minus concept return over the same interval.
  - `strong_day_count_cycle`: count of stock daily returns `>=5%` from cycle start through `S`.
  - `sessions_since_strong`: completed market sessions since the latest stock daily return `>=5%`.
  - `turnover_median_20d`: median stock turnover over the latest 20 completed sessions.
  - `capacity_passed`: `turnover_median_20d >= 100,000,000 CNY`; it is a tie-breaker and evaluation field, not a trade filter.
- Modes: existing `cycle_relative_strength`, `market_recognition_lexicographic`, and `recognition_consensus`; no weighted score and no low-suction outcome.
- Target binding: `target_trade_date` remains null until the first complete local market date strictly after `S` exists. Weekends and holidays are never inferred from `S + 1 calendar day`.
- Immutability: a retry with the same version and input fingerprint is idempotent; a different fingerprint for an already frozen source date is rejected.
- Selection gate: report partial diagnostics immediately, but keep `selected_mode=null` until at least 60 bound source sessions exist and one mode wins at least three of five chronological folds. No production rule is created by this plan.

### Task 1: Share One Ranking Core Without Weakening Point-in-Time Validation

**Files:**
- Modify: `alphaagent/server/services/low_suction/leader_identity.py`
- Modify: `tests/alphaagent/services/low_suction/test_leader_identity.py`

- [x] **Step 1: Add failing tests for prevalidated forward ranking**

Add tests that call a new `rank_prevalidated_leader_identities()` with `session_column="source_trade_date"`. Prove all three modes match the existing ordering, preserve an explicit `excluded_reason`, reject outcome/future columns, reject duplicate `(source_trade_date, sector_id, vt_symbol)` rows, and never assign a rank to excluded rows.

```python
ranked = rank_prevalidated_leader_identities(
    features,
    mode=LeaderIdentityMode.MARKET_RECOGNITION,
    session_column="source_trade_date",
)
assert ranked.loc[ranked["excluded_reason"].notna(), "rank"].isna().all()
assert ranked.loc[ranked["rank"].le(3), "is_top3"].all()
```

- [x] **Step 2: Run the focused tests and confirm the new symbol is missing**

Run:

```bash
uv run pytest tests/alphaagent/services/low_suction/test_leader_identity.py -q
```

Expected: the new tests fail because `rank_prevalidated_leader_identities` does not exist.

- [x] **Step 3: Extract the deterministic rank core**

Implement the new function as the single sorter used by `rank_leader_identities()`. It must validate the session identity, four numeric rank features, explicit exclusion values, and prohibited outcome fields. Generalize the private relative-strength, market-recognition, consensus, and group-rank helpers to use the supplied session column. Keep all existing D-09:25 membership/security validation in `rank_leader_identities()` unchanged.

- [x] **Step 4: Run the focused tests**

Run the command from Step 2. Expected: all leader identity tests pass.

### Task 2: Define the Immutable Forward Rank Schema

**Files:**
- Modify: `alphaagent/server/db/schema.py`
- Create: `tests/alphaagent/services/low_suction/test_forward_leader_identity_repository.py`

- [x] **Step 1: Add schema contract tests**

Assert the rank table primary key is `(source_trade_date, ranking_version, identity_mode, sector_id, vt_symbol)` and the scope key is `(source_trade_date, ranking_version, identity_mode)`. Require nullable `target_trade_date`, fixed `target_session`, `known_at`, `feature_cutoff`, cycle identity, all four rank features, both base ranks, selected rank, `is_top3`, `excluded_reason`, `capacity_passed`, `input_fingerprint`, `complete`, `selected_mode`, and JSON evidence.

- [x] **Step 2: Run the schema test and verify failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_forward_leader_identity_repository.py -q
```

Expected: failure because the two tables are absent.

- [x] **Step 3: Add low-suction-owned tables and indexes**

Create `low_suction_forward_leader_rank_snapshots` and `low_suction_forward_leader_rank_snapshot_scopes` without foreign keys to mutable current-product tables. Add indexes for `(target_trade_date, identity_mode, is_top3)`, `(vt_symbol, source_trade_date)`, and `(complete, source_trade_date)`.

- [x] **Step 4: Re-run the schema test**

Expected: the schema contract test passes.

### Task 3: Build Strict Source-Date Features and All Three Captures

**Files:**
- Create: `alphaagent/server/services/low_suction/forward_leader_identity.py`
- Create: `tests/alphaagent/services/low_suction/test_forward_leader_identity.py`

- [x] **Step 1: Test strict source gates and no-lookahead behavior**

Use synthetic concept, benchmark, membership, security, and stock frames to prove:

```python
capture = build_forward_leader_capture(inputs)
assert capture.source_trade_date == date(2026, 7, 16)
assert {scope.identity_mode for scope in capture.scopes} == set(LeaderIdentityMode)
assert all(scope.selected_mode is None for scope in capture.scopes)
assert all(row.target_trade_date is None for row in capture.rows)
```

Mutating bars after `S` must not change the fingerprint or ranks. A partial/wrong-date membership scope, partial/wrong-date security scope, missing canonical concept `S` row, missing eligible stock `S` bar, or feature timestamp after `S` must produce a closed capture with no rank rows. Non-main-board members must be counted as board exclusions and never enter the rank denominator.

- [x] **Step 2: Run the focused test and verify failure**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_forward_leader_identity.py -q
```

Expected: failure because the forward builder is absent.

- [x] **Step 3: Implement dataclasses and validation**

Add immutable input, row, scope, and capture dataclasses plus `ForwardLeaderIdentityError`. Normalize source times to Asia/Shanghai, require same-date post-close strict scopes, and reject all prohibited future/outcome columns.

- [x] **Step 4: Calculate the frozen concept and stock features**

Reuse `build_market_returns()`, `build_cycle_candidates()`, `FROZEN_MAIN_RISE_DEFINITION`, main-board eligibility, and the shared prevalidated sorter. Keep only active `breakout_trend` concepts present in the strict tradable membership scope. Calculate the frozen feature definitions above from real completed-session order, retain every eligible/excluded main-board membership row, and build one input fingerprint before running all three modes.

- [x] **Step 5: Close incomplete days instead of falling back**

A closed capture must create three `complete=false` scopes with a shared blocking reason and zero rows. It must never use `sector_memberships`, `stock_sector_memberships`, a previous snapshot, current stock names, or a calendar-day guess.

- [x] **Step 6: Run the focused tests**

Expected: all forward builder tests pass.

### Task 4: Load, Freeze, Bind, and Evaluate the Ledger

**Files:**
- Create: `alphaagent/server/services/low_suction/forward_leader_identity_repository.py`
- Modify: `tests/alphaagent/services/low_suction/test_forward_leader_identity_repository.py`

- [x] **Step 1: Add loader tests for exact same-date strict inputs**

Compile and inspect SQL to prove membership rows/scopes, security rows/scopes, canonical concept bars, benchmark bars, and member stock bars are selected by exact `source_trade_date` and never from current membership tables. Require the stock/concept history query to stop at `S`.

- [x] **Step 2: Add immutable persistence tests**

Test one transaction inserts all three scopes and their rows, a same-fingerprint retry performs no replacement, a changed fingerprint raises, and a closed retry cannot overwrite a complete freeze.

- [x] **Step 3: Add real-session binding tests**

With completed daily dates `2026-07-16` and `2026-07-20`, bind a `2026-07-16` source scope to `2026-07-20`, not `2026-07-17`. A second attempt must be idempotent; a conflicting rebind must fail.

- [x] **Step 4: Implement repository loading and atomic writes**

Load base inputs first, derive active concepts, then load only their main-board member stock histories. Save the first complete fingerprint immutably and preserve closed-scope evidence without replacing a complete capture.

- [x] **Step 5: Implement outcome-independent evaluation**

Build per-mode metrics from bound rows only: next-session Top3 retention, five-session strong-event lead score (`0..5`, with `6` for a fully observed five-session window with no strong day), and Top3 capacity pass rate. Do not select with fewer than 60 bound sessions. Split mature sessions chronologically into five folds, pick fold winners lexicographically by retention descending, strong-event lead ascending, capacity descending, and require one mode to win at least three folds.

- [x] **Step 6: Run repository tests**

Run:

```bash
uv run pytest tests/alphaagent/services/low_suction/test_forward_leader_identity_repository.py -q
```

Expected: all repository, binding, and evaluation tests pass.

### Task 5: Add Reproducible CLI Evidence

**Files:**
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Modify: `tests/alphaagent/services/low_suction/test_forward_leader_identity.py`

- [x] **Step 1: Add CLI parser and rendering tests**

Add `v2-forward-top3-freeze --source-date YYYY-MM-DD` and read-only `v2-forward-top3-report --format json|markdown`. Assert reports expose source/target coverage, per-mode Top3 counts, overlaps, retention/strong-event/capacity metrics, `selected_mode=null` while immature, `formal_metrics=null`, and `low_suction_outcomes_read=false`.

- [x] **Step 2: Implement orchestration and renderers**

The freeze command must load exact strict inputs, build the capture, persist it, bind any earlier pending session from completed daily evidence, and return the immutable fingerprint. The report command must not mutate the ledger.

- [x] **Step 3: Run CLI-focused tests**

```bash
uv run pytest tests/alphaagent/services/low_suction/test_forward_leader_identity.py -q
```

Expected: all parser, rendering, and domain tests pass.

### Task 6: Connect the EOD Dependency Chain

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`

- [x] **Step 1: Add failing schedule-order tests**

Register `sync_low_suction_forward_top3` and require both 19:00 and 21:30 chains to order completed stock/index bars, canonical sector daily bars, sector members, security snapshot, then forward Top3. Assert a holiday, a lagging concept index, or either incomplete strict scope returns `status=skipped` and writes no ranks.

- [x] **Step 2: Keep concept indices dynamic after the historical backfill**

Add the existing `sync_sector_daily_bars` job to both EOD chains before sector scores and forward Top3. Keep its explicit 800-session manual/bootstrap contract; scheduled execution passes an incremental 30-session request so the already acquired history is updated rather than rebuilt concept-by-concept from scratch.

- [x] **Step 3: Implement and register the runner**

The runner uses `_latest_complete_daily_date_for_research()`, binds previous sessions, freezes the current source only after every dependency is exact and complete, and reports scope/rank/Top3 counts. It must not import or execute limit-up recommendations, legacy quant backtests, minute entries, or performance code.

- [x] **Step 4: Run schedule tests**

```bash
uv run pytest tests/alphaagent/test_data_sync_schedule.py -q
```

Expected: all existing and new schedule tests pass.

### Task 7: Freeze the First Real Source Session and Record Evidence

**Files:**
- Create: `memory/06_backtests/low_suction_forward_top3_ledger_20260717.md`
- Create: `memory/06_backtests/low_suction_forward_top3_ledger_20260717.json`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run all low-suction tests and static checks**

```bash
uv run pytest tests/alphaagent/services/low_suction -q
uv run ruff check alphaagent/server/services/low_suction alphaagent/server/services/data_sync.py tests/alphaagent/services/low_suction tests/alphaagent/test_data_sync_schedule.py
uv run python -m compileall -q alphaagent/server/services/low_suction
git diff --check
```

Expected: all commands pass.

Verification note: the low-suction suite passes with 428 tests, the schedule suite
passes with 114 tests, compileall and `git diff --check` pass, and Ruff passes for
the new low-suction source/tests. The broader command still reports 10 pre-existing
warnings in `data_sync.py` and the older schedule-test helpers; they are outside this
plan's changes and were not auto-fixed.

- [x] **Step 2: Rebuild the API and create missing tables**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-forward-top3-freeze --source-date 2026-07-16
```

Expected: one immutable strict source-date capture is created for all three modes; its real target date stays null until a later complete market session is present.

- [x] **Step 3: Export the first report**

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-forward-top3-report --format markdown
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-forward-top3-report --format json
```

Write the exact outputs to the two evidence files, parse the JSON, and record its SHA256. The report must say `selected_mode=null`, `formal_metrics=null`, and no low-suction win rate or compounded return.

- [x] **Step 4: Update durable project memory in place**

Link the new evidence from the backtest index and replace the stale “forward Top3 loader/persistence absent” decision text with the current truth: one or more strict forward source sessions are accumulating, no identity mode is selected, and minute low-suction research stays closed until the pre-registered sample gate is met.

- [x] **Step 5: Final verification**

Run the focused tests again after the container migration, query the two new scope/rank tables for source `2026-07-16`, verify all three fingerprints agree, verify each `(mode, sector)` has at most three Top3 rows, verify no target calendar date was guessed, and run `git diff --check`.

## Self-Review

- Spec coverage: strict same-date sources, main-board exclusions, frozen main rise, all three return-independent modes, immutable rows, real-session binding, retention/strong-event/capacity evaluation, null selection, dynamic index refresh, scheduler ordering, and durable evidence are each assigned to a task.
- Placeholder scan: the plan contains no deferred implementation markers; concrete constants, table keys, commands, failure behavior, and selection gates are fixed above.
- Type consistency: `source_trade_date`, nullable `target_trade_date`, `target_session`, `ranking_version`, `identity_mode`, `input_fingerprint`, `complete`, and `selected_mode` use the same names in domain, repository, schema, CLI, and tests.
