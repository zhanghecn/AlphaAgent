# AlphaAgent Legacy Quant Removal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not dispatch subagents. Do not commit unless the user explicitly requests it.

**Goal:** Completely remove the old quant, generic backtest, portfolio, and simulation products while preserving raw market data, market timing, mainline research, limit-up research, and a working AlphaAgent deployment.

**Architecture:** Move the two genuinely shared capabilities out of legacy namespaces first: transaction-cost cash math goes to `services/execution`, and gold/silver market timing goes to `services/market_timing`. Then detach legacy routers, schedules, schema objects, frontend routes, tests, and documents. Finally run the destructive PostgreSQL migration only after static imports, focused tests, frontend build, and limit-up regression checks pass.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy Core, PostgreSQL 16, React 18, TypeScript, Vite, Vitest, pytest, Docker Compose.

---

## Plan Discipline

- The working tree contains pre-existing changes in `data_sync.py`, limit-up history files, tests, and memory. Re-read every overlapping file immediately before editing and preserve those changes.
- Use `apply_patch` for source edits and file deletion.
- Do not modify `vnpy/` or official examples.
- Do not run `git commit` or `git push`.
- Replace commit steps with `git diff --check`, focused tests, and a status checkpoint.
- Do not drop PostgreSQL tables until Task 8.

### Task 1: Freeze Deletion And Limit-Up Baselines

**Files:**
- Read: `alphaagent/server/services/limit_up/cash_backtest.py`
- Read: `alphaagent/server/services/limit_up/history_service.py`
- Read: `alphaagent/server/services/data_sync.py`
- Create: `memory/06_backtests/legacy_quant_removal_baseline_20260716.md`

- [x] **Step 1: Capture the dirty-worktree boundary**

Run:

```bash
git status --short
git diff -- alphaagent/server/services/data_sync.py \
  alphaagent/server/services/limit_up/history_repository.py \
  alphaagent/server/services/limit_up/history_service.py \
  tests/alphaagent/test_data_sync_schedule.py \
  tests/alphaagent/test_limit_up_history.py
```

Expected: existing edits are visible and are treated as user-owned input, not reverted.

- [x] **Step 2: Capture the current database inventory**

Run read-only PostgreSQL queries for row counts of all tables that will be dropped and all preserved `limit_up_*`, market, stock, sector, and timing tables. Record only counts and date ranges, never credentials.

Expected report shape:

```text
legacy tables: table_name, row_count
preserved tables: table_name, row_count, min_date, max_date
```

- [x] **Step 3: Capture the limit-up execution fingerprint**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_cash_backtest.py -q
uv run --group server pytest tests/alphaagent/test_limit_up_history.py -q
```

Query the current `limit-up-history-v14` product account summary and record strategy version, closed trades, win rate, compounded return, max drawdown, and final equity.

Expected: focused tests pass; the fingerprint is written to the baseline report.

- [x] **Step 4: Write the evidence file**

The file must use the following headings and replace every metric with the exact
value captured by Steps 2-3; empty metric fields are forbidden:

```markdown
# Legacy Quant Removal Baseline

## Preserved Product Fingerprint

Record the exact strategy version, closed-trade count, win rate, compounded
return, maximum drawdown, and final equity returned by the current v14 query.

## Legacy Table Counts
| Table | Rows |
| --- | ---: |

## Preserved Table Coverage
| Table | Rows | Minimum date | Maximum date |
| --- | ---: | --- | --- |
```

- [x] **Step 5: Checkpoint**

Run:

```bash
git diff --check
git status --short
```

Expected: only the approved design/plan, the baseline report, and pre-existing user changes are present.

### Task 2: Extract Shared Execution And Market-Timing Modules

**Files:**
- Create: `alphaagent/server/services/execution/__init__.py`
- Create: `alphaagent/server/services/execution/cash_ledger.py`
- Modify: `alphaagent/server/services/limit_up/cash_backtest.py`
- Create: `alphaagent/server/services/market_timing/__init__.py`
- Move content from: `alphaagent/server/services/quant/market_timing/*.py`
- Create by move: `alphaagent/server/services/market_context.py`
- Move content from: `alphaagent/server/services/quant/market_context.py`
- Modify: `alphaagent/server/api/market_timing.py`
- Modify: `alphaagent/server/main.py`
- Modify: `scripts/market_timing_eval.py`
- Modify: `tests/alphaagent/services/quant/test_market_timing_*.py`
- Test: `tests/alphaagent/test_limit_up_cash_backtest.py`

- [x] **Step 1: Write import-boundary tests**

Add assertions that preserved modules no longer import a legacy package:

```python
def test_limit_up_cash_backtest_uses_neutral_cash_ledger() -> None:
    source = Path("alphaagent/server/services/limit_up/cash_backtest.py").read_text()
    assert "services.execution import cash_ledger" in source
    assert "services.backtest" not in source


def test_market_timing_imports_do_not_use_quant_namespace() -> None:
    roots = [
        Path("alphaagent/server/api/market_timing.py"),
        Path("alphaagent/server/main.py"),
        Path("alphaagent/server/services/market_context.py"),
        Path("alphaagent/server/services/market_timing"),
    ]
    text = "\n".join(
        path.read_text()
        for root in roots
        for path in ([root] if root.is_file() else root.rglob("*.py"))
    )
    assert "services.quant" not in text
```

- [x] **Step 2: Verify the tests fail before the move**

Run the two new tests directly.

Expected: FAIL because current imports use `services.backtest` and `services.quant.market_timing`.

- [x] **Step 3: Move the cash ledger without behavior changes**

Copy the dataclasses and functions from legacy `backtest/ledger.py` verbatim into `services/execution/cash_ledger.py`. Export only the public types and functions:

```python
from .cash_ledger import (
    BuyExecution,
    SellExecution,
    calculate_buy_execution,
    calculate_sell_execution,
)

__all__ = [
    "BuyExecution",
    "SellExecution",
    "calculate_buy_execution",
    "calculate_sell_execution",
]
```

Update limit-up usage to:

```python
from alphaagent.server.services.execution import cash_ledger
```

- [x] **Step 4: Move market timing out of the quant namespace**

Move `backtest.py`, `factors.py`, `panel.py`, `series.py`, `signal.py`, and package exports to `services/market_timing/`. Replace imports such as:

```python
from alphaagent.server.services.quant.market_timing import series as ser
```

with:

```python
from alphaagent.server.services.market_timing import series as ser
```

Relocate the three market-timing test files to `tests/alphaagent/services/market_timing/` and update imports.

Move `quant/market_context.py` to `services/market_context.py`. It owns the
seven-index weights, point-in-time market contexts, breadth calculation, and
phase classification required by market timing and the future low-suction
research; it contains no dependency on a legacy quant strategy. Update market
timing and `scripts/market_timing_eval.py` to use the neutral path.

- [x] **Step 5: Run preserved-domain tests**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_cash_backtest.py -q
uv run --group server pytest tests/alphaagent/services/market_timing -q
uv run python -m compileall alphaagent/server/services/execution alphaagent/server/services/market_timing alphaagent/server/services/limit_up
```

Expected: all pass; no preserved module imports `services.backtest` or `services.quant`.

- [x] **Step 6: Checkpoint**

Run `git diff --check` and compare the limit-up unit fingerprint with Task 1.

Expected: fee, lot-size, slippage, and cash assertions are identical.

### Task 3: Remove Legacy Backend Routes And Startup Hooks

**Files:**
- Create: `tests/alphaagent/test_legacy_product_removal.py`
- Modify: `alphaagent/server/api/router.py`
- Modify: `alphaagent/server/main.py`
- Modify: `alphaagent/server/api/stocks.py`
- Modify: `alphaagent/server/api/vnpy_status.py`
- Delete: `alphaagent/server/api/quant.py`
- Delete: `alphaagent/server/api/backtests.py`
- Delete: `alphaagent/server/api/portfolios.py`
- Delete: `alphaagent/server/api/simulation.py`

- [x] **Step 1: Write route-removal tests**

```python
from alphaagent.server.main import create_app


def test_legacy_product_routes_are_absent() -> None:
    paths = {route.path for route in create_app().routes}
    assert not any(path.startswith("/api/quant") for path in paths)
    assert not any(path.startswith("/api/backtests") for path in paths)
    assert not any(path.startswith("/api/portfolios") for path in paths)
    assert not any(path.startswith("/api/simulation") for path in paths)


def test_preserved_research_routes_remain() -> None:
    paths = {route.path for route in create_app().routes}
    assert any(path.startswith("/api/limit-up") for path in paths)
    assert any(path.startswith("/api/market-timing") for path in paths)
    assert any(path.startswith("/api/mainline-replay") for path in paths)
```

- [x] **Step 2: Verify the first test fails**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_legacy_product_removal.py -q
```

Expected: FAIL because legacy routers are registered.

- [x] **Step 3: Detach routers and startup hooks**

Remove legacy router imports/includes from `api/router.py`. Remove `ensure_default_groups()` and its import from `main.py`. Preserve data sync, limit-up warmup, market cache warmup, next-session planning, and relocated market timing refresh.

- [x] **Step 4: Remove stock and vn.py response fields owned by legacy quant**

Delete stock-detail endpoints and capability fields that import quant/backtest services. Preserve stock quote, daily bars, financial visibility, concept membership, and raw-data diagnostics.

- [x] **Step 5: Delete the four legacy API modules**

Use `apply_patch` file deletion after all imports have been removed.

- [x] **Step 6: Verify routes and imports**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_legacy_product_removal.py tests/alphaagent/test_api.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/main.py
rg -n 'api\.(quant|backtests|portfolios|simulation)|services\.(quant|backtest|portfolio|simulation)' alphaagent/server --glob '*.py'
```

Expected: tests pass; remaining matches are limited to files scheduled for deletion in later tasks, not preserved API/startup code.

### Task 4: Remove Quant Scheduling And Backtest-Specific Data Management

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/api/data_sync.py`
- Modify: `alphaagent/server/services/minute_provider_imports.py`
- Modify: `tests/alphaagent/test_data_sync_schedule.py`
- Modify: `tests/alphaagent/test_data_health.py`

- [x] **Step 1: Add schedule-boundary tests**

```python
def test_default_schedules_exclude_legacy_quant_actions() -> None:
    schedules = {row["id"]: row for row in data_sync.DEFAULT_BATCH_SCHEDULES}
    assert "tail_quant_1430" not in schedules
    all_jobs = {job for row in schedules.values() for job in row["job_ids"]}
    assert "eod_quant_research" not in all_jobs
    assert schedules["limit_up_live_scan"]["enabled"] is True
    assert "limit_up_history_rebuild" in schedules["eod_finalize_2130"]["job_ids"]


def test_schedule_actions_reject_removed_quant_actions() -> None:
    with pytest.raises(data_sync.DataSyncError):
        data_sync._schedule_action({"action": "quant_research"})
    with pytest.raises(data_sync.DataSyncError):
        data_sync._schedule_action({"action": "tail_preview"})
```

- [x] **Step 2: Verify tests fail**

Run the two tests directly.

Expected: FAIL because both schedules and actions still exist.

- [x] **Step 3: Remove quant imports and internal jobs**

Remove `research_jobs`, `screening`, `TAIL_PREVIEW_BATCH_JOB_ID`, `EOD_QUANT_RESEARCH_BATCH_JOB_ID`, `tail_quant_1430`, all `quant_research/tail_preview` action branches, candidate-symbol injection, latest quant summaries, and catch-up logic. Keep generic minute synchronization and all limit-up internal jobs.

- [x] **Step 4: Remove API endpoints and minute-gap behavior tied to a backtest ID**

Remove `run-tail-quant`, strict backtest gap generation, and lazy imports of `services.backtest.engine`. Keep generic recent-minute synchronization and internal limit-up event-minute backfill paths that operate on database-discovered structured symbol/date gaps. Remove CSV, file-path and manifest import routes.

- [x] **Step 5: Remove stale seeded schedules**

Extend schedule reconciliation so existing database rows with IDs/actions `tail_quant_1430`, `quant_research`, or `tail_preview` are deleted during `ensure_sync_schema()`. Do not delete limit-up schedules.

- [x] **Step 6: Verify data management and limit-up scheduling**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_data_health.py -q
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_history.py -q
rg -n 'tail_quant|eod_quant|quant_research|tail_preview|services\.backtest' alphaagent/server/services/data_sync.py alphaagent/server/api/data_sync.py alphaagent/server/services/minute_provider_imports.py
```

Expected: tests pass; search returns no legacy action/import implementation.

### Task 5: Remove Legacy Schema Objects And Add The Destructive Migration

**Files:**
- Create: `alphaagent/server/db/legacy_product_cleanup.py`
- Modify: `alphaagent/server/db/schema.py`
- Test: `tests/alphaagent/test_legacy_product_removal.py`

- [x] **Step 1: Write schema-boundary tests**

```python
LEGACY_TABLES = {
    "quant_strategy_templates", "quant_signal_runs", "quant_stock_signals",
    "quant_recommendations", "quant_tail_preview_cache", "backtest_runs",
    "backtest_orders", "backtest_trades", "backtest_signal_events",
    "backtest_factor_snapshots", "backtest_factor_outcomes",
    "backtest_daily_equity", "backtest_daily_positions", "backtest_metrics",
    "strategy_replay_runs", "strategy_replay_attempts", "portfolio_groups",
    "portfolio_group_items", "simulation_accounts", "simulation_orders",
    "simulation_trades", "simulation_positions", "risk_events",
}


def test_legacy_tables_are_not_in_metadata() -> None:
    assert LEGACY_TABLES.isdisjoint(schema.metadata.tables)


def test_cleanup_manifest_matches_schema_test() -> None:
    assert set(legacy_product_cleanup.LEGACY_TABLES) == LEGACY_TABLES
```

- [x] **Step 2: Verify tests fail**

Run the schema tests.

Expected: FAIL because legacy tables are still registered.

- [x] **Step 3: Add a fixed cleanup manifest**

Create a hard-coded, dependency-safe child-first tuple and execute quoted names only:

```python
from sqlalchemy import text

LEGACY_TABLES = (
    "risk_events", "simulation_positions", "simulation_trades",
    "simulation_orders", "simulation_accounts", "portfolio_group_items",
    "portfolio_groups", "strategy_replay_attempts", "strategy_replay_runs",
    "backtest_factor_outcomes", "backtest_factor_snapshots",
    "backtest_signal_events", "backtest_daily_positions",
    "backtest_daily_equity", "backtest_metrics", "backtest_trades",
    "backtest_orders", "backtest_runs", "quant_tail_preview_cache",
    "quant_recommendations", "quant_stock_signals", "quant_signal_runs",
    "quant_strategy_templates",
)


def drop_legacy_product_tables(engine) -> None:
    with engine.begin() as connection:
        for table_name in LEGACY_TABLES:
            connection.execute(text(f'DROP TABLE IF EXISTS "{table_name}" CASCADE'))
```

- [x] **Step 4: Remove legacy SQLAlchemy table declarations**

Delete all declarations listed in the manifest from `schema.py`. Import and call `drop_legacy_product_tables(engine)` once at the start of `create_schema()`, before `metadata.create_all(engine)`.

- [x] **Step 5: Verify metadata without touching PostgreSQL**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_legacy_product_removal.py -q
uv run python -m compileall alphaagent/server/db
```

Expected: tests pass; preserved tables remain registered.

- [x] **Step 6: Checkpoint before destructive execution**

Run the Task 1 read-only table inventory again and compare preserved counts. Do not execute `create_schema()` against PostgreSQL yet.

### Task 6: Remove Legacy Frontend And Establish The Short-Term Route

**Files:**
- Create: `frontend/src/pages/ShortTermResearchPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppShell.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/pages/DataManagementPage.tsx`
- Modify: `frontend/src/api/dataSync.ts`
- Delete: `frontend/src/pages/QuantTradingPage.tsx`
- Delete: `frontend/src/pages/PortfolioPage.tsx`
- Delete: `frontend/src/features/quant/`
- Delete: `frontend/src/features/portfolio/`
- Delete: `frontend/src/api/quant.ts`
- Delete: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- Delete if unreferenced: `frontend/src/lib/backtest-utils.ts`
- Delete if unreferenced: `frontend/src/lib/portfolio-risk.ts`
- Delete if unreferenced: `frontend/src/lib/portfolio-states.ts`

- [x] **Step 1: Add route and navigation tests**

Create a small source-level Vitest test asserting:

```ts
expect(appSource).toContain('path="/short-term"');
expect(appSource).not.toContain('path="/quant"');
expect(appSource).not.toContain('path="/portfolio"');
expect(shellSource).toContain('label: "短线研究"');
expect(shellSource).not.toContain('label: "量化交易"');
expect(shellSource).not.toContain('label: "持仓"');
```

- [x] **Step 2: Verify the test fails**

Run the new Vitest test.

Expected: FAIL on current routes/navigation.

- [x] **Step 3: Add the short-term page without inventing low-suction UI early**

The cleanup-phase page wraps the preserved limit-up page and keeps the future tab boundary explicit:

```tsx
import { LimitUpPage } from "@/pages/LimitUpPage";

export function ShortTermResearchPage() {
  return <LimitUpPage />;
}
```

Route `/short-term` to this page and redirect legacy `/limit-up` to `/short-term`. Rename the nav item to “短线研究”. The low-suction Tab is added only after the research report exists.

- [x] **Step 4: Remove quant/portfolio UI and cross-page imports**

Delete the legacy feature trees and pages. Remove stock quant audit queries/markers, data-management backtest-ID controls, tail-quant status, and portfolio group actions. Preserve generic stock charts, raw minute import, limit-up data-quality controls, and market timing.

- [x] **Step 5: Verify frontend**

Run:

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
rg -n '/quant|/portfolio|api/quant|features/quant|features/portfolio|backtestId' frontend/src
```

Expected: tests and build pass; remaining `backtest` wording belongs only to preserved limit-up research internals, not deleted generic endpoints.

### Task 7: Delete Legacy Service Code, Tests, And Documentation

**Files:**
- Delete: `alphaagent/server/services/quant/` after market timing has moved
- Delete: `alphaagent/server/services/backtest/` after cash ledger has moved
- Delete: `alphaagent/server/services/portfolio/`
- Delete: `alphaagent/server/services/simulation/`
- Delete quant-only tests listed by dependency search
- Delete: `requirements/alphaagent_d2_limit_up_d1_rise_event_study_design.md`
- Delete: `requirements/alphaagent_d2_limit_up_d1_rise_event_study_implementation_plan.md`
- Delete: `requirements/alphaagent_dragon_pullback_implementation_plan.md`
- Delete: `requirements/alphaagent_dragon_pullback_signal_dedupe_plan.md`
- Delete: `requirements/alphaagent_low_suction_factor_validation_plan.md`
- Delete: `requirements/alphaagent_pullback_low_suction_strategy_research.md`
- Delete: `requirements/alphaagent_quant_backtest_portfolio_plan.md`
- Delete: `requirements/alphaagent_quant_feature_drilldown_next_execution_plan.md`
- Delete: `requirements/alphaagent_quant_feature_table_execution_plan.md`
- Delete: `requirements/alphaagent_quant_feature_validation_execution_plan.md`
- Delete: `requirements/alphaagent_quant_next_experiment_execution_plan.md`
- Delete: `requirements/alphaagent_quant_strategy_next_execution_plan.md`
- Delete: `requirements/alphaagent_tail_sync_quant_plan.md`
- Delete: `memory/06_backtests/d1_event_feature_research_2025_01_01.md`
- Delete: `memory/06_backtests/d1_event_feature_research_2026_03_01.md`
- Delete: `memory/06_backtests/d2_limit_up_d1_rise_event_study.md`
- Delete: `memory/06_backtests/quant_overlay_d1_event_features_2025_08_06.md`
- Delete: `memory/06_backtests/strategy_optimization_ledger.md`
- Delete quant-only evidence reports from `memory/06_backtests/`
- Modify: `requirements/README.md`
- Modify: `memory/00_index/README.md`
- Modify: `memory/02_source/core_entrypoints.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Generate an exact deletion manifest**

Run:

```bash
rg -l '/quant|services/quant|services/backtest|mainline_dragon_pullback|quant_' requirements memory/06_backtests tests/alphaagent | sort
```

Classify each file as delete, rewrite, or preserve. Preserve every limit-up and market-timing report even when it contains the generic word “backtest”.

- [x] **Step 2: Delete service packages and quant-only tests**

Use `apply_patch` deletion. Retain relocated market-timing tests and all limit-up tests. Remove tests whose only subject is the deleted strategy, generic backtest, portfolio, or simulation service.

- [x] **Step 3: Remove superseded documents and rewrite current memory**

Current memory must state:

```text
- /quant and /portfolio no longer exist.
- generic backtest and simulation products were removed.
- /short-term currently preserves the independent limit-up research product.
- low-suction research is governed by the 2026-07-16 reset design and is not yet a validated strategy.
```

Do not erase limit-up or market-timing evidence.

- [x] **Step 4: Run the orphan scan**

Run:

```bash
rg -n 'services\.(quant|backtest|portfolio|simulation)|schema\.(quant_|backtest_|portfolio_|simulation_|risk_events)|/api/(quant|backtests|portfolios|simulation)' alphaagent frontend/src tests
```

Expected: no executable-code references. Historical terms may remain only in the approved reset design and git history.

- [x] **Step 5: Checkpoint**

Run:

```bash
git diff --check
git status --short
```

Expected: no unrelated user changes were reverted.

### Task 8: Execute The Database Cleanup And Verify The Preserved Product

**Files:**
- Verify: files modified by Tasks 1-7
- Update: `memory/06_backtests/legacy_quant_removal_baseline_20260716.md`

- [x] **Step 1: Run all static and focused gates before the drop**

Run:

```bash
uv run python -m compileall alphaagent/server alphaagent/market alphaagent/data_sources
uv run --group server pytest tests/alphaagent/test_legacy_product_removal.py -q
uv run --group server pytest tests/alphaagent/test_limit_up_cash_backtest.py tests/alphaagent/test_limit_up_history.py -q
uv run --group server pytest tests/alphaagent/services/market_timing -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
git diff --check
```

Expected: every command passes. If any fail, do not drop tables.

- [x] **Step 2: Rebuild the API and invoke schema cleanup**

Run:

```bash
docker compose up -d --build alphaagent-api alphaagent-web
```

The API startup calls `create_schema()`, which drops the approved legacy tables and recreates only preserved metadata.

Expected: API, gateway, PostgreSQL, and Redis are healthy.

- [x] **Step 3: Verify physical deletion and preserved counts**

Query PostgreSQL `to_regclass()` for every manifest table and assert all are `NULL`. Re-run preserved table counts from Task 1.

Expected:

```text
legacy tables present: 0
preserved table count regressions: 0
```

- [x] **Step 4: Verify HTTP and browser behavior**

Check:

```text
GET /api/limit-up/history/status -> 200
GET /api/market-timing/panel   -> 200
GET /api/mainline-replay/timeline -> 200
GET /api/quant/strategies       -> 404
GET /api/backtests              -> 404
GET /api/portfolios/groups      -> 404
GET /api/simulation/account     -> 404
```

Open `http://localhost:8080/short-term` at desktop and `390x844`. Confirm limit-up data renders, no full-page overflow, and browser console has no errors.

- [x] **Step 5: Compare the limit-up fingerprint**

Re-run the Task 1 account query. Strategy version, closed-trade count, win rate, compounded return, max drawdown, and final equity must match exactly unless pre-existing user changes deliberately altered the baseline; any such difference must be explained from the preserved diff before continuing.

- [x] **Step 6: Update the baseline report with final evidence**

Add verification commands, physical deletion count, preserved-count comparison, HTTP status, browser viewports, and the final limit-up fingerprint.

- [x] **Step 7: Final checkpoint**

Run:

```bash
git diff --check
git status --short
```

Expected: cleanup phase is complete, deployment is healthy, and no commit has been created.

## Completion Boundary

This plan is complete only when the old product code and PostgreSQL tables are absent, limit-up and market timing still pass regression checks, and `/short-term` is the working user entry. It does not implement low-suction research; that begins in the next plan after this cleanup is verified.
