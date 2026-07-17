# Low-suction First-divergence 5-minute Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether a main-rise event-recognized leader becomes a viable low-suction cohort only after completing its first daily divergence.

**Architecture:** Reuse the frozen event-recognition identities but collapse repeated events into one stock-concept-cycle leader spell. Find the first negative close inside the next five reliable sessions while the exact same `breakout_trend` cycle remains active, then use the following session as the 5m observation day. Reuse the already-tested four 5m recovery transitions, costs, D+1 exit and reporting gates unchanged.

**Tech Stack:** Python, pandas, SQLAlchemy/PostgreSQL, pytdx 5m, pytest, existing event 5m state/execution helpers.

**Repository constraint:** No commits, no outer holdout prices, no current-member fallback, no打板 strategy/ledger changes and no parameter search after outcomes.

---

## Frozen Contract

- Spell identity: `(sector_id, cycle_id, vt_symbol)`; keep the earliest recognition source event in that spell.
- Divergence search: sessions S+1 through S+5 only; select the first stock close strictly below its previous close.
- Concept guard: divergence date must retain the same frozen `breakout_trend` `cycle_id`; otherwise reject the spell.
- Observation date: first reliable session after divergence; planned exit: next reliable session. Both must be no later than `2025-11-17`.
- Cross-concept collision: same stock/observation date keeps the concept with highest divergence-date concept relative percentile, then earliest original event and sector ID.
- Security scope remains main-board, non-ST event-date proxy with at least 60 prior sessions from the upstream recognition cohort.
- 5m transitions, next-bar execution, D+1 first sellable close, normal/double costs and qualification gates are byte-for-byte the same as the completed event-next-day study.
- This is still `event_recognition_falsification`, not strict membership Top3 or formal performance.

### Task 1: Build And Test First-divergence Candidates

**Files:**
- Create: `alphaagent/server/services/low_suction/first_divergence.py`
- Create: `tests/alphaagent/services/low_suction/test_first_divergence.py`

- [x] Test earliest spell deduplication, exact five-session horizon, first negative close, same-cycle guard, cross-concept dedupe and discovery-bound exit.
- [x] Implement pure candidate construction and a read-only loader using only V2 discovery prices.
- [x] Add an immutable candidate-audit CLI and run coverage without reading transition outcomes.

### Task 2: Candidate-only 5m Manifest And Backfill

**Files:**
- Create: `alphaagent/server/services/low_suction/first_divergence_minutes.py`
- Create: `tests/alphaagent/services/low_suction/test_first_divergence_minutes.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] Reuse the 48-bar manifest contract for divergence observation pairs.
- [x] Add manifest and manifest-only TDX backfill CLI commands with no custom dates/windows.
- [x] Backfill until every available pair is complete or explicitly permanent-missing.

### Task 3: Reuse Frozen 5m Transitions And Run

**Files:**
- Create: `alphaagent/server/services/low_suction/first_divergence_5m_study.py`
- Create: `tests/alphaagent/services/low_suction/test_first_divergence_5m_study.py`
- Modify: `alphaagent/server/services/low_suction/cli.py`

- [x] Feed divergence candidates through `build_event_5m_state_panel`, `extract_frozen_transitions`, execution and the unchanged summary gates.
- [x] Prove CLI exposes no divergence horizon, rule, threshold or exit flags.
- [x] Run all four rules once and preserve complete rule/block/regime tables.

### Task 4: Evidence And Safety Gate

**Files:**
- Create after real run: `memory/06_backtests/low_suction_first_divergence_5m_study_20260716.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] Record data coverage, fingerprints, all failures and any non-qualifying >60% cells.
- [x] Decide only `no edge`, `direction only` or `worth strict retest`; formal metrics remain null.
- [x] Run low-suction tests, scoped Ruff, compileall and `git diff --check`.

## Completion Boundary

Completion means the first-divergence cohort and all four unchanged 5m recovery rules have a reproducible
development-only result. It does not unlock the outer holdout, cash portfolio or production UI.
