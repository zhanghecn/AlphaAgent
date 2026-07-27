# Unified Limit-up Public Quality Implementation Plan

**Goal:** 让历史正式回放、实时触板推荐和板前概率准备只消费一份 A/B/C 公共质量合同，并以分层收缩后的胜率和 D+1 预期收益统一过滤与排序。

**Architecture:** 保留 lane、财务和风险等可审计组件，但只由 `core_quality.py` 汇总为公共状态、A/B/C 层级、质量胜率和 D+1 预期收益。板前阶段把真实触板时钟表示为 `qualified_waiting_trigger`，正式触板后同一合同转为 `actionable`；触板概率模型只处理已经通过公共质量门的候选。

**Tech Stack:** Python 3.11、FastAPI service modules、PostgreSQL point-in-time evidence、pytest、React/TypeScript/Vitest。

---

### Task 1: Freeze the public A/B/C quality estimate

**Files:**
- Modify: `alphaagent/server/services/limit_up/core_quality.py`
- Test: `tests/alphaagent/test_limit_up_core_quality.py`

- [x] **Step 1: Add failing tests for A/B/C priors and shrinkage**

```python
decision = public_quality_gate(candidate, structural_gate_passed=True)
assert decision["quality_win_probability"] >= 0.50
assert decision["quality_expected_d1_net_return_pct"] > 0
assert decision["public_quality_status"] == "qualified_waiting_trigger"
```

- [x] **Step 2: Run the focused tests and confirm the new API is absent**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_core_quality.py`

Expected: FAIL because `public_quality_gate` and the public fields do not exist.

- [x] **Step 3: Implement the public contract**

Use frozen evidence `A=35/41,+3.0876%`, `C=46/72,+1.9156%`, and
`B=18/30,+1.2895%`. Blend prior-only same-stock D+1 evidence with the tier prior
using a fixed finite prior strength, fail closed below 50% or non-positive D+1
expectation, and distinguish `rejected`, `qualified_waiting_trigger`, and
`actionable`.

The 50% candidate floor is not the strategy win-rate target. Threshold sensitivity
showed that a 60% per-candidate floor reduces the frozen two-position compound return
to `+165.2255%`; the 50% floor retains `+201.9840%` while the resulting closed
strategy win rate remains above the user's 60% target.

- [x] **Step 4: Run the focused tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_core_quality.py`

Expected: PASS.

### Task 2: Make historical and live formal actions consume the public contract

**Files:**
- Modify: `alphaagent/server/services/limit_up/core_quality.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/radar_observation_repository.py`
- Test: `tests/alphaagent/test_limit_up_core_quality.py`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_radar_observation_repository.py`

- [x] **Step 1: Add failing parity tests**

```python
assert historical["public_quality_contract_version"] == live["public_quality_contract_version"]
assert historical["quality_win_probability"] == live["quality_win_probability"]
assert live["public_quality_actionable"] is True
```

- [x] **Step 2: Route history filtering, live signal annotation, live buy lists and radar rows through `public_quality_gate`**

The formal order remains eligible only when the shared lane structure passes,
the A/B or C preparation passes, the quality probability gate passes, and the
real touch/reseal clock has made the public state actionable.

- [x] **Step 3: Run formal-path tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_core_quality.py tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_radar_observation_repository.py`

Expected: PASS.

### Task 3: Replace the separate pre-board quality gate

**Files:**
- Modify: `alphaagent/server/services/limit_up/first_board_quality.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_contract.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_policy.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_service.py`
- Test: `tests/alphaagent/test_limit_up_first_board_quality.py`
- Test: `tests/alphaagent/test_limit_up_preboard_decision_policy.py`
- Test: `tests/alphaagent/test_limit_up_preboard_decision_service.py`

- [x] **Step 1: Add failing tests for C rescue and waiting-trigger semantics**

```python
assert pools.quality_pool[0]["quality_priority_tier"] == "C_capital_diffusion_rescue"
assert pools.quality_pool[0]["public_quality_status"] == "qualified_waiting_trigger"
```

- [x] **Step 2: Remove profitability as an early capture veto**

Capture only enforces universe and disclosed risk. The public A/B/C gate then
decides whether weak profitability is rejected or causally rescued by C, so the
pre-board path cannot discard a candidate the formal contract would admit.

- [x] **Step 3: Make pre-board eligibility and ranking use public quality fields**

Use `quality_win_probability` first and
`quality_expected_d1_net_return_pct` second, followed by three-minute and
eventual-touch probabilities. Do not turn research-only touch probabilities into
formal orders while historical promotion remains rejected.

- [x] **Step 4: Run pre-board tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_first_board_quality.py tests/alphaagent/test_limit_up_preboard_decision_policy.py tests/alphaagent/test_limit_up_preboard_decision_service.py`

Expected: PASS.

### Task 4: Publish one quality vocabulary

**Files:**
- Modify: `alphaagent/server/services/limit_up/strategy_guide.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/PreboardRanking.tsx`
- Modify: `frontend/src/features/limitUp/preboardRanking.spec.tsx`
- Test: `tests/alphaagent/test_limit_up_strategy_guide.py`

- [x] **Step 1: Expose quality tier, state, probability and D+1 expectation**

The UI labels the values as `质量层`, `质量胜率`, and `D+1预期`; touch
probabilities remain separate timing columns.

- [x] **Step 2: Remove wording that implies the probability table is a buy list**

Keep the explicit `research_only` state until the historical and forward action
policy passes.

- [x] **Step 3: Run backend and frontend contract tests**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_strategy_guide.py`

Run: `npm --prefix frontend test -- --run frontend/src/features/limitUp/preboardRanking.spec.tsx`

Expected: PASS.

### Task 5: Re-run history and recent-day evidence

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Create or update: `memory/06_backtests/limit_up_unified_public_quality_20260727.md`

- [x] **Step 1: Run the complete formal history replay**

Report input, selected and closed counts; A/B/C distribution; win rate; average
D+1 net return; independent compounding; one-position and two-position accounts.

- [x] **Step 2: Audit the most recent closed trading days**

List every public-quality order with its A/B/C tier, quality probability,
estimated D+1 return, actual D+1 return and pass/reject result.

- [x] **Step 3: Audit the latest saved live/pre-board day**

Compare public-quality candidates, scored probabilities, low-quality exclusions,
later physical touches and formal `buy_now` rows without treating research rows as
executed trades.

- [x] **Step 4: Run the regression suite**

Run: `uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py`

Run: `uv run python -m compileall -q alphaagent/server/services/limit_up`

Run: `npm --prefix frontend test -- --run`

Run: `npm --prefix frontend run build`

Run: `git diff --check`

Expected: all commands pass, with any external data limitation stated in the report.

### Task 6: Separate full recommendations from account capacity

**Files:**
- Modify: `alphaagent/server/services/limit_up/preboard_decision_policy.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_replay.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_service.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_repository.py`
- Modify: `frontend/src/features/limitUp/LiveSignalCard.tsx`

- [x] **Step 1: Produce an unlimited formal recommendation stream**

Evaluate every strictly pre-board row that passes public quality, execution and
probability gates. Emit at most one first recommendation per stock/day, but do not
apply one-position or two-position capacity to `actionable_recommendations`.

- [x] **Step 2: Keep a separate account projection**

Apply the existing causal capacity and A-reservation policy only to
`preboard_portfolio`. Persist `portfolio_selected` separately and allow full
recommendations to have no `daily_slot`.

- [x] **Step 3: Make full quality the promotion gate**

Historical promotion first requires at least 20 closed full recommendations,
full-recommendation D+1 win rate `>=60%`, and positive average D+1 net return.
One-position/two-position return, drawdown, stability and double-cost results then
verify account executability; they do not define the full-quality denominator.

- [x] **Step 4: Publish the distinction in API and UI**

Sort full recommendations by A/C/B, public quality win probability, expected D+1
return and touch probability. Show those fields on formal pre-board cards. Describe
position limits only as backtest/account behavior.
