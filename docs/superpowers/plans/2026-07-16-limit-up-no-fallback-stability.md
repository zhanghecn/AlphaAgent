# Limit-up No-fallback Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove stale concept-membership and daily-close exit fallbacks so production ranking and backtest statistics only use evidence that satisfies the declared point-in-time contract.

**Architecture:** A nightly membership capture may explicitly exclude sector IDs whose complete response was unavailable, while retaining an auditable exclusion list and rebuilding the remaining daily snapshot. Intraday concept strength must match the immediately prior local trading date exactly. Scheduled D+1 14:30 replay must retain only orders with an exact minute price and report excluded orders instead of synthesizing a close-price exit.

**Tech Stack:** Python 3.11+, SQLAlchemy/PostgreSQL, AlphaAgent scheduler and limit-up services, pytest.

---

Repository policy forbids commits unless the user explicitly requests one. Execution remains in the shared worktree and preserves unrelated changes.

### Task 1: Freeze failed-sector exclusion behavior

**Files:**
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `tests/alphaagent/test_market_snapshot_repository.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/services/market_snapshot_repository.py`

- [x] **Step 1: Replace the old dependency-blocking test with an exclusion test**

Require `_run_sync_sector_members()` to delete only failed sector memberships, return their IDs in `excluded_sector_ids`, and finish without raising when at least one sector completed.

```python
result = runner._run_sync_sector_members({"page_size": 50})
assert result["excluded_sector_ids"] == ["BK0002"]
assert removed == [("BK0002",)]
```

- [x] **Step 2: Add snapshot-scope audit tests**

Pass an explicit excluded sector to the current snapshot writer and require the retained scope to stay internally complete while recording the catalog denominator and exclusion IDs.

```python
assert scope["complete"] is True
assert scope["raw"]["excluded_sector_ids"] == ["BK0002"]
assert scope["raw"]["catalog_expected_sector_count"] == 3
```

- [x] **Step 3: Verify the tests fail**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_market_snapshot_repository.py -q -k "sector_member or membership_snapshot"
```

Expected: the old implementation raises and the snapshot API has no exclusion contract.

- [x] **Step 4: Implement the minimal exclusion path**

Add a small `_delete_sector_memberships()` helper, delete only the failed IDs after the capture finishes, and return an explicit exclusion audit. Extend the current snapshot writer with `excluded_sector_ids`; filter those IDs from rows and expected inventory while recording them in scope `raw`. If no sector succeeds, keep failing closed so no empty snapshot is published.

- [x] **Step 5: Run the focused tests**

Run the Task 1 command and require all selected tests to pass.

### Task 2: Require the exact prior trading-day membership snapshot

**Files:**
- Modify: `tests/alphaagent/test_limit_up_concept_live.py`
- Modify: `alphaagent/server/services/limit_up/concept_snapshot_repository.py`
- Modify: `alphaagent/server/services/limit_up/concept_live_service.py`

- [x] **Step 1: Add weekend and stale-snapshot tests**

Require the repository to resolve Friday for a Monday signal, but reject Thursday when Friday is the latest local trading date.

```python
assert required_prior_membership_date(
    [date(2026, 7, 16), date(2026, 7, 17)],
    date(2026, 7, 20),
) == date(2026, 7, 17)
```

The refresh test must return `trigger_allowed=False` and persist nothing when the loader cannot return that required date.

- [x] **Step 2: Verify the tests fail**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_concept_live.py -q -k "prior_membership or stale_membership"
```

- [x] **Step 3: Implement strict D-1 loading**

Resolve the previous local trading date from `stock_daily_bars`, load only that date's complete concept scope, and return no rows when it is absent. Include `membership_snapshot_date_valid` in data quality; concept refresh must fail closed instead of selecting an older snapshot.

- [x] **Step 4: Run all concept-live tests**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_concept_live.py tests/alphaagent/test_limit_up_concept_resonance.py -q
```

### Task 3: Remove daily-close exits from the scheduled replay

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `tests/alphaagent/test_limit_up_cash_backtest.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`

- [x] **Step 1: Add an exact-price exclusion test**

Provide three scheduled orders with one exact 14:30 row, one daily close only, and one missing result bar. Require only the exact order to enter all account and recommendation summaries.

```python
assert report["summary"]["signal_count"] == 1
assert report["coverage"]["excluded_no_exact_1430_count"] == 2
assert report["coverage"]["daily_close_proxy_count"] == 0
```

- [x] **Step 2: Verify the test fails**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_cash_backtest.py -q -k "next_1430 or daily_close_proxy"
```

- [x] **Step 3: Implement one reusable exact-order filter**

Stop assigning `price_1430` from `close_price`. Add `_filter_orders_with_exact_1430()` and apply it before lane validation, variant gates, position sizing, cash simulation, and independent recommendation-quality aggregation. Preserve the original request count and report exact/excluded counts. Keep the low-level cash engine capable of disclosing a caller-supplied proxy, but the production history service must never create one.

- [x] **Step 4: Version the changed replay contract**

Change `SCHEDULED_EXECUTION_VERSION` from `limit-up-scheduled-v5` to `limit-up-scheduled-v6` so cached and exported reports cannot mix fallback and no-fallback results.

- [x] **Step 5: Run focused replay tests**

Run the Task 3 command and require all selected tests to pass.

### Task 4: Measure impact without retuning

**Files:**
- Create: `memory/06_backtests/limit_up_no_fallback_impact_20260716.md`

- [x] **Step 1: Rebuild the unchanged candidate ledger**

Run the existing history rebuild after code tests pass. Do not change profitability thresholds, lane selection, entry windows, costs, or position count.

- [x] **Step 2: Compare the frozen baseline and strict replay**

Record account trades, win rate, average return, compound return, maximum drawdown, profit factor, recommendation-quality metrics, exact-price coverage, and excluded count. The pre-change account baseline is 97 closed trades, 67.0103% win rate, +168.1058% return, and -8.3083% drawdown; 37 executed exits use the close proxy.

- [x] **Step 3: Record sector-removal impact**

Record that BK1677/BK1678/BK1679 appear in 0 of 52,463 archived intraday candidate rows and 0 of 28 v10 candidates. Also report the retained catalog ratio; do not infer future impact from this two-day sample.

### Task 5: Regression, deployment, and durable state

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run regressions and static checks**

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_market_snapshot_repository.py tests/alphaagent/test_limit_up_concept_live.py tests/alphaagent/test_limit_up_concept_resonance.py tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_history.py -q
uv run python -m compileall alphaagent/server/services/limit_up alphaagent/server/services/data_sync.py alphaagent/server/services/market_snapshot_repository.py
git diff --check
```

- [x] **Step 2: Rebuild and verify the API**

```bash
docker compose up -d --build alphaagent-api
docker compose ps alphaagent-api
```

Do not call `ensure_sync_schema()` from a second process while the live API is running.

- [x] **Step 3: Run the membership jobs once**

Execute `sync_sector_members` followed by `sync_stock_sector_memberships`. Verify the current-date scope exists, the three unavailable event boards are absent and audited, and the next trading-day concept loader selects exactly that scope.

- [x] **Step 4: Update memory**

Replace fallback descriptions with the current no-fallback contract and link the impact report. Keep Tick/L2 absence separate; this task does not invent execution evidence.
