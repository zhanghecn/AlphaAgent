# Limit-Up Dynamic Sector Entry Implementation Plan

> **Superseded:** v14 将 `observe/warming` 概念核心作为正式单路后降低闭合收益。最终
> v15 保留盘中行业路径，但概念单路必须 `launch`；证据见
> `memory/06_backtests/limit_up_sector_quality_v15_20260717.md`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the D-1 sector heat score from the live first-board execution gate, replace it with point-in-time industry and concept-core routes, and measure the rule only on saved intraday snapshots without historical backfill.

**Architecture:** Keep D-1 membership and heat as prior-only context and ranking evidence. The first-board execution gate becomes `shared gates AND (realtime industry route OR realtime concept-core route)`: the industry route uses intraday touch diffusion and same-day fund flow, while the concept route uses fresh full-market quotes, non-ebb state, strong-stock diffusion, and dynamic Top3 leadership. Historical account replay remains unchanged because it lacks full-market concept minute frames; a separate saved-snapshot counterfactual reports the limited causal evidence.

**Tech Stack:** Python 3.13, FastAPI service modules, PostgreSQL saved snapshots, pytest, Vitest/TypeScript, Docker Compose.

---

### Task 1: Freeze The Dynamic Route Contract

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`

- [x] **Step 1: Add a failing D-1 heat regression test**

Add a first-board candidate with `sector_heat=28.8`, `sector_touch_count=7`, same-day positive sector flow, `concept_state="observe"`, and otherwise valid fields. Require `sector_route` to pass through the realtime industry route and require the heat check to remain non-blocking diagnostic evidence.

```python
def test_realtime_industry_route_ignores_d1_heat() -> None:
    candidate = _candidate(
        "000037.SZSE",
        sector_heat=28.8,
        sector_touch_count=7,
        sector_main_net_inflow=1_024_881_632.0,
        sector_main_net_inflow_ratio=3.12,
        sector_flow_trade_date="2026-07-17",
        evaluation_date="2026-07-17",
        concept_state="observe",
    )
    checks = live_policy._candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="momentum",
    )
    by_code = {row["code"]: row for row in checks}
    assert by_code["sector_route"]["status"] == "passed"
    assert by_code["sector_route"]["observed"] == "盘中行业路径通过"
    assert by_code["sector_heat"]["blocking"] is False
```

- [x] **Step 2: Add concept-core boundary tests**

Require a fresh `observe` concept with two or more stocks above 5% and a Top3 candidate to pass when the industry route fails. Require `ebb`, stale coverage, weak diffusion, or leadership outside Top3 to keep a concept-only candidate blocked. A `launch` state must be exposed as a bonus, not required for route passage.

```python
def test_realtime_concept_core_does_not_require_launch() -> None:
    candidate = _candidate(
        "000037.SZSE",
        sector_touch_count=0,
        sector_main_net_inflow=-500_000_000.0,
        sector_flow_trade_date="2026-07-17",
        evaluation_date="2026-07-17",
        concept_state="observe",
        concept_trigger_allowed=True,
        concept_snapshot_age_seconds=5,
        concept_coverage_ratio=1.0,
        concept_strong_5_count=7,
        concept_leader_rank=1,
    )
    checks = live_policy._candidate_execution_checks(
        candidate,
        require_expansion=True,
        entry_kind="momentum",
    )
    route = next(row for row in checks if row["code"] == "sector_route")
    assert route["status"] == "passed"
    assert route["observed"] == "概念核心路径通过"
```

- [x] **Step 3: Run the focused tests and verify failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "realtime_industry_route or realtime_concept_core or both_dynamic_routes"
```

Expected: the new tests fail because the current code still requires D-1 heat or `concept_state=launch`.

- [x] **Step 4: Implement the minimal route split**

In `live_policy.py`, replace the first-board additive route helper with:

```python
industry_checks = _realtime_industry_route_checks(
    candidate,
    touch_required=touch_required,
    require_expansion=require_expansion,
)
concept_checks = _realtime_concept_core_route_checks(candidate)
route_passed = _route_passed(industry_checks) or _route_passed(concept_checks)
```

The industry checks must require current-session expansion and same-day non-materially-negative flow. The concept checks must require source quality, freshness, `observe/warming/launch` rather than `ebb/unavailable`, at least two members above 5%, and candidate rank 1-3. Preserve `sector_heat` as `blocking=False` diagnostic evidence and expose `launch` as `concept_launch_bonus`.

In `live_service.py`, add `evaluation_date=captured_at.date().isoformat()` to the live research candidate so same-day fund flow can be verified without reading the system clock.

- [x] **Step 5: Run focused tests and require pass**

Run the Step 3 command and then:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_concept_resonance.py -q
```

Expected: all selected tests pass, including stale-data and severe-outflow rejection tests.

### Task 2: Version And Present The New Contract

**Files:**
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `frontend/src/features/limitUp/livePortfolio.spec.ts`

- [x] **Step 1: Increment only the live strategy version**

Change `limit-up-live-v13` to `limit-up-live-v14`. Do not change the historical ledger or scheduled account version because their candidate and execution contracts are not being rewritten.

- [x] **Step 2: Make the dynamic route visible**

Expose the selected route and `concept_launch_bonus` in the existing live signal type. Display D-1 heat explicitly as prior context rather than current heat, and show the selected realtime route in the trigger evidence. Do not add a second recommendation product or user toggle.

- [x] **Step 3: Run frontend checks**

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend run typecheck
pnpm --dir frontend run build
```

Expected: all frontend tests, TypeScript, and production build pass.

### Task 3: Saved-Snapshot Counterfactual Replay

**Files:**
- Create: `memory/06_backtests/limit_up_dynamic_sector_entry_v14_20260717.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Audit available point-in-time coverage**

Query saved live snapshots and concept-strength frames by date/version. Record which signal dates have a subsequently available D+1 official close. Do not include next-session plans or synthesize historical concept frames.

- [x] **Step 2: Replay the new route on saved candidates**

For each eligible saved `live_snapshot`, use only its saved candidates, market context, captured time, and prior snapshots. Rebuild the current live recommendations, attach historical evidence with `result_before=signal_date`, apply the first-board profitability gate, and retain the first qualifying signal per stock/day inside `10:00-11:30` or `13:00-14:30`.

Use the saved signal-time `last_price` as entry price. Use only the next trading day's official `stock_daily_bars.close_price` as exit. Apply the existing cash ledger's commissions, minimum commission, transfer fee, stamp tax, 10 bp buy and sell slippage, 100-share lots, and two 50% positions. A sealed signal remains a queue-fill proxy because L2 and order acknowledgements are unavailable.

- [x] **Step 3: Report old and new rule cohorts separately**

Report snapshot days, closed signal days, unique signals, closed trades, win rate, average net return, compound return, maximum drawdown, and exclusions. Separate:

```text
old saved actionable signal
new realtime-industry route
new realtime-concept-core route
both routes
unclosed forward signals
```

If no closed v14-equivalent trades exist, preserve `null` for win rate and return rather than reporting zero.

- [x] **Step 4: State the historical boundary**

Record that the 800-day v9 account remains the historical structural baseline and cannot measure the new dynamic route. The saved-snapshot replay is causal but currently limited to dates with real concept frames; it is not a full-history performance claim.

### Task 4: Regression And Live Acceptance

**Files:**
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/03_data/data_flow.md`

- [x] **Step 1: Run backend and static regression**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
uv run python -m compileall alphaagent/server/services/limit_up
git diff --check
```

Expected: all limit-up tests, compilation, and whitespace checks pass.

- [x] **Step 2: Rebuild API and Web**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps
```

Expected: API, Gateway, PostgreSQL, and Redis are healthy; Web is running.

- [ ] **Step 3: Verify a real v14 snapshot**

Require `strategy_version=limit-up-live-v14`, fresh complete concept data, dynamic route diagnostics, and no API error logs. For the current Deep Nan Electric A case, confirm that D-1 heat is non-blocking and that the realtime industry or concept-core route is selected when the remaining shared gates pass.

- [x] **Step 4: Update durable memory**

Replace stale v13 live-contract text with v14, link the counterfactual replay, and retain the explicit L2/fill and sample-size limitations. Do not commit or tag; repository policy requires a separate explicit user request.
