# First-board v8 Local Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the over-restrictive full-session support gate with point-in-time local support scoring, rebuild the history ledger, and report statistically useful first-board results.

**Architecture:** Extend the existing three-minute prefix summarizer with recent-window features, keep lane evaluation outcome-blind, and isolate the new policy under `limit-up-history-v8`. Calibrate at most one entry threshold on the rolling development phase, then evaluate the frozen policy on the old holdout and retain full candidate-pool auditability.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy/PostgreSQL, pytest, FastAPI, React/Vitest.

---

Project rules prohibit unrequested commits, so no commit steps are included.

### Task 1: Lock local-prefix semantics with tests

**Files:**

- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [x] Add a path whose early values are near zero and whose final 15/30-minute windows rise steadily; assert exact local minima, changes, range, and drawdown.
- [x] Change a value after `signal_time`; assert every local feature and support score stays unchanged.
- [x] Add stable, fading, and missing-path first-board candidates; assert stable paths are eligible while fading/missing paths are blocked.
- [x] Run the focused tests and confirm they fail before implementation.

### Task 2: Implement local support and v8 policy

**Files:**

- Modify: `alphaagent/server/services/limit_up/lane_features.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `alphaagent/server/services/limit_up/walk_forward_contract.py`
- Modify: `alphaagent/server/services/limit_up/history_engine.py`
- Test: `tests/alphaagent/test_limit_up_lanes.py`
- Test: `tests/alphaagent/test_limit_up_live.py`

- [x] Add recent 15/30-minute prefix fields using only completed points at or before the signal.
- [x] Add one bounded local-support score and a separate point-in-time first-board entry-quality score.
- [x] Remove the full-session `3%-6%` and first-board heat `>=50` hard gates; retain path availability and explicit local-breakdown protection.
- [x] Select the earliest first-board signal matching the frozen local setup and keep all other candidates in the audit pool.
- [x] Add the new features to the walk-forward vector and user-facing reason mapping.
- [x] Bump history to `limit-up-history-v8` and the changed model contract to `limit-up-walk-forward-v4`; preserve v7 rows.
- [x] Run focused lane/live/history tests.

### Task 3: Rebuild and audit the full history

**Files:**

- Modify only if needed after development-segment evidence: the single first-board quality threshold in `lane_research.py`.

- [x] Rebuild all 600 reliable daily dates into v8.
- [x] Compute the first-board hard-gate funnel from all closed candidates.
- [x] On `expanding_oos` only, compare `0/50/55/60/65/70/75`; no threshold passed all three gates, so none was selected.
- [x] Freeze the simplest development-positive local setup before reading its old-holdout result; do not adjust it after the holdout failed.
- [x] Confirm 113 total closed selections, 60/53 in the two old phases, and report the failed stability gates without hiding them.

### Task 4: Verify product metrics and deployment

**Files:**

- Modify: `memory/06_backtests/limit_up_short_term_factor_research.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_limit_up_first_board_v8_implementation_plan.md`

- [x] Record D+1 open/close trade count, net win rate, average return, compounded return, maximum drawdown, hard-loss rate, and D-day seal rate for all phases.
- [x] Run all limit-up backend tests, frontend tests, frontend build, compile checks, and `git diff --check`; local Ruff executable is unavailable.
- [x] Rebuild/restart the API and web services, verify `/api/limit-up/history/status`, lane backtest, and `/limit-up` in a browser.
- [x] Update durable memory in place, mark plan checkboxes, and report both the improved sample size and remaining data/execution limitations.
