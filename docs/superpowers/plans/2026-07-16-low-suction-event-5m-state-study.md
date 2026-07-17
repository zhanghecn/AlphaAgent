# Low-suction Event 5-minute State Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill candidate-only public TDX 5-minute bars and test four pre-registered intraday recovery transitions for event-recognized main-rise stocks without reading the V2 outer holdout.

**Architecture:** Extend the existing TDX importer with a separate `5m -> category 0` mapping while leaving all current 1-minute jobs unchanged. Build a low-suction-only manifest from the 505 frozen recognition candidates, fetch only missing stock-entry-date pairs, then calculate point-in-time recovery transitions and next-bar executions. Results remain incomplete-denominator falsification evidence and cannot unlock strict Top3 or formal performance.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy/PostgreSQL, pytdx public quote API, pytest, existing cash execution helpers.

**Repository constraint:** No commits, no API rebuild/restart, no `vnpy/` or official example edits, and no changes to打板候选、策略、账本、绩效或 existing 1m schedule behavior.

---

## Frozen Contract

- Candidate identity and source dates are exactly the 505 rows produced by `v2-event-falsification`; both entry and planned D+1 exit must stay inside `2025-11-17`.
- Minute source is TDX category 0, stored as `interval='5m'`; a complete day is 48 unique close timestamps `09:35..15:00`.
- Manifest includes only candidate `(vt_symbol, entry_date)` pairs, never the full market.
- Existing `1m -> category 8` import, 14:30 exit backfill and打板 jobs remain byte-for-byte behavior compatible.
- Four transition names are frozen before loading 5m outcomes:
  - `vwap_reclaim`: prior 5m close below prior cumulative VWAP, current close at/above current cumulative VWAP.
  - `open_reclaim`: prior close below entry-day open, current close at/above open.
  - `previous_close_reclaim`: prior close below source-day close, current close at/above source-day close.
  - `two_higher_closes_after_open_break`: the day has traded below open and the latest two closes are strictly increasing.
- Keep only the first transition per candidate/rule. Signal uses the current 5m close; entry uses the next 5m open with 10 bps slippage and real fees. No next bar means rejection.
- Exit is the next session's first sellable daily close, with existing cost rules and a double-cost rerun.
- Report every rule overall, across the same five chronological event blocks and across all GOLD/SILVER/NEUTRAL × NORMAL/DANGER contexts.
- `worth_strict_retest` requires at least 100 closed trades, fee-adjusted win rate above 60%, positive mean, PF above 1, positive double-cost mean and positive mean/PF in at least four blocks. No rule is promoted to production.

### Task 1: Add Tested TDX 5-minute Support

**Files:**
- Modify: `alphaagent/server/services/data_providers/tdx_minute_import.py`
- Modify: `alphaagent/server/services/minute_provider_imports.py`
- Create: `tests/alphaagent/test_tdx_minute_import.py`

- [ ] **Step 1:** Write tests proving `1m` remains category 8, `5m` maps to category 0, full 5m audit requires 48 bars, and unsupported intervals still fail closed.
- [ ] **Step 2:** Run the focused tests and verify failure.
- [ ] **Step 3:** Add `SUPPORTED_INTERVALS = {'1m': 8, '5m': 0}` and a small required-bar helper; do not change existing defaults.
- [ ] **Step 4:** Run tests and Ruff.

### Task 2: Candidate-only 5-minute Manifest And Backfill

**Files:**
- Create: `alphaagent/server/services/low_suction/event_recognition_minutes.py`
- Create: `tests/alphaagent/services/low_suction/test_event_recognition_minutes.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [ ] **Step 1:** Test that the manifest contains only frozen candidate pairs, requires 48 unique bars, rejects duplicates, and reports complete/incomplete/missing separately.
- [ ] **Step 2:** Implement `load_event_5m_manifest()` from current candidate inputs and `stock_minute_bars interval='5m'`.
- [ ] **Step 3:** Implement `backfill_missing_event_5m(dry_run, max_gaps)` using only manifest-generated gaps, full-day `09:35..15:00`, at most 81 pages per symbol.
- [ ] **Step 4:** Add immutable CLI commands `v2-event-5m-manifest` and `v2-event-5m-backfill --dry-run|--write --max-gaps`.
- [ ] **Step 5:** Verify focused tests and Ruff.

### Task 3: Complete The Bounded Raw-data Backfill

**Files:**
- No source edits unless a verified provider bug is found.

- [ ] **Step 1:** Run manifest and record zero-baseline coverage.
- [ ] **Step 2:** Run write batches until no retryable missing pairs remain; do not rebuild the API container.
- [ ] **Step 3:** Re-run manifest and require 48/48 rows for every covered pair; preserve all permanent failures explicitly.

### Task 4: Point-in-time Recovery Transitions

**Files:**
- Create: `alphaagent/server/services/low_suction/event_recognition_5m_study.py`
- Create: `tests/alphaagent/services/low_suction/test_event_recognition_5m_study.py`

- [ ] **Step 1:** Test cumulative VWAP uses only rows through t, each predicate emits only its first false-to-true transition, and a future bar cannot alter an earlier signal.
- [ ] **Step 2:** Test signal-close/next-bar-open execution, T+1 exit, costs, double costs and missing/duplicate minute rejection.
- [ ] **Step 3:** Implement continuous state rows, the four frozen predicates and deterministic transition IDs.
- [ ] **Step 4:** Implement all-rule, five-block and complete market-context diagnostics; never select on a single cell.
- [ ] **Step 5:** Verify focused tests and Ruff.

### Task 5: Real Study And Evidence

**Files:**
- Modify: `alphaagent/server/services/low_suction/cli.py`
- Create after the real run: `memory/06_backtests/low_suction_event_5m_state_study_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1:** Add immutable `v2-event-5m-study --format json|markdown`; expose no threshold flags.
- [ ] **Step 2:** Run once against complete eligible pairs and record every rule, block, context, rejection and double-cost result.
- [ ] **Step 3:** Decide only `no edge`, `direction only` or `worth strict retest`; keep `formal_metrics=null` and holdout reads false.
- [ ] **Step 4:** Run all low-suction tests, compileall, scoped Ruff and `git diff --check`.

## Completion Boundary

Completion means the candidate-only 5m dataset is explicitly complete or permanently incomplete and all
four frozen recovery transitions have a reproducible development-only result. It does not choose a cash
portfolio, read the outer holdout, satisfy the user's final >60% cash-compounding target or unlock UI.
