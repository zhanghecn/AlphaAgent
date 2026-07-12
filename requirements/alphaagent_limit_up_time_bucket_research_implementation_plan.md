# Limit-up Time Bucket Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a reproducible first-touch-time study of main-board limit-up seal success and D+1 premiums.

**Architecture:** Add one isolated research module with pure time-bucketing and aggregation functions plus a read-only database loader and Markdown renderer. Reuse existing event normalization/deduplication, leave strategy selection/API/frontend untouched, and archive the real-data evidence under `memory/06_backtests/`.

**Tech Stack:** Python 3.11+, pandas, SQLAlchemy, PostgreSQL, pytest.

---

Project rules prohibit unrequested commits, so no commit steps are included.

### Task 1: Lock time boundaries and denominators with failing tests

**Files:**

- Create: `tests/alphaagent/test_limit_up_time_bucket_research.py`

- [x] Test the six configured buckets at every inclusive/exclusive boundary and classify midday/invalid values as excluded.
- [x] Test that all touched events enter the seal-rate denominator while only final sealed events with valid adjacent D+1 bars enter premium metrics.
- [x] Test gross and `0.31%` net open/close win rates and average returns.
- [x] Test that the conservative reseal subset contains only final sealed events with `open_times > 0`.
- [x] Test that changing D+1 prices changes outcome metrics but not time bucket, touch count, sealed count, or seal rate.
- [x] Run `uv run pytest tests/alphaagent/test_limit_up_time_bucket_research.py -q` and confirm collection fails because the module is absent.

### Task 2: Implement pure bucket observations and summaries

**Files:**

- Create: `alphaagent/server/services/limit_up/time_bucket_research.py`
- Test: `tests/alphaagent/test_limit_up_time_bucket_research.py`

- [x] Define `classify_first_limit_time(value)`, returning a stable bucket key/label pair or an excluded result.
- [x] Define `build_time_bucket_observations(events, daily_bars, trading_dates)` to attach the exact next market date and D+1 path without altering event status.
- [x] Define `summarize_time_buckets(observations)` to produce all-touch seal metrics, sealed-board premium metrics, reseal-proxy metrics, yearly rows, exclusions, and best-bucket conclusions.
- [x] Keep functions focused: normalization, observation building, return metrics, bucket aggregation, ranking, and rendering remain separate.
- [x] Run the target test and require all assertions to pass.

### Task 3: Add read-only real-data execution and report rendering

**Files:**

- Modify: `alphaagent/server/services/limit_up/time_bucket_research.py`
- Create: `memory/06_backtests/limit_up_time_bucket_research.md`

- [x] Load only `limit_pool_zt/limit_pool_zbgc` rows, merge duplicate versions with `merge_rich_event_rows`, and filter current main-board non-ST symbols.
- [x] Load the Shanghai Composite trading calendar and only the D/D+1 daily bars needed for event symbols.
- [x] Record source coverage, raw rows, deduplicated events, trustworthy date range, missing D/D+1 bars, invalid paths, and out-of-session times.
- [x] Add a CLI entrypoint supporting an optional output path and render the Chinese evidence report.
- [x] Run the study inside the Compose network and write `memory/06_backtests/limit_up_time_bucket_research.md`.

### Task 4: Cross-check and maintain durable memory

**Files:**

- Modify: `memory/06_backtests/README.md`
- Modify: `requirements/alphaagent_limit_up_time_bucket_research_implementation_plan.md`

- [x] Independently aggregate PostgreSQL event rows by the same time boundaries and compare touch counts, sealed counts, seal rates, D+1 open sample counts, win rates, and averages.
- [x] Add one concise current-state conclusion and one report link to the backtest evidence index.
- [x] Run the target test plus related limit-up domain/lane tests, Ruff, compileall, and scoped `git diff --check`.
- [x] Mark every completed checkbox and report the trustworthy data range, full table, ranking, fillability caveat, and missing-history limitation to the user.
