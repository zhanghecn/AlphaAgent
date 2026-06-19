# AlphaAgent Low-Suction Factor Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` or equivalent task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking. Do not change default trading behavior until this plan explicitly reaches the default-off experiment phase.

**Goal:** Build a verifiable factor-validation pipeline that separates `龙回头回踩` and `低位承接转强`, proves which factors improve win rate / return / drawdown under different market regimes, and only then promotes selected changes behind default-off experiment flags.

**Architecture:** Keep one public strategy and one simple product workflow. Internally split entry evidence into setup engines (`dragon_pullback`, `low_position_reclaim`) plus shared quality/risk/market layers. First produce read-only diagnostics and feature/outcome tables; later use those tables to decide whether any scoring, execution, or sell rule deserves a default-off experiment.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL/local DB tables already used by AlphaAgent, existing `quant_stock_signals` / `quant_recommendations` / `backtest_*` tables, React/TypeScript, pytest, Vite.

---

## 后续执行摘要

这份计划用于后续按任务执行，不直接把新因子写进默认交易规则。执行顺序是：先冻结当前 `0.1.21 / #203/#194` 产品基线，再补只读入场家族标签、候选特征表、固定持有后验表、因子分桶审计、统一策略时间线和前端简化展示；最后生成一份基线证据报告。只有报告证明某个窄规则在全局、年度、市场环境、前 10 候选、重点股票和无未来函数检查中都优于当前基线，才进入默认关闭实验。

后续执行时请遵守三条边界：

- 低吸洗盘和龙回头内部拆成两套入场因子，但用户界面仍只展示一个公开策略。
- 候选低吸蓄势天数只能作为上下文和加分证据，不能每天画成买点；关键买点应是蓄势后的首个有效上拉/转强。
- 所有 outcome、胜率、MFE/MAE、后验路径字段只能用于审计和报告，不能参与信号日评分、排序、买入、卖出或仓位。

最终验收以四类结果为准：`pytest`/编译/前端 build 通过；股票详情页能用统一策略时间线解释买入、拒买和卖出；回测页能展示因子分桶和市场分层结果；`memory/06_backtests/` 形成一份可比较的证据报告，并更新策略优化台账。

## Current State

Current product baseline:

- Public strategy: `mainline_dragon_pullback / 0.1.21`.
- Product baseline evidence: `#203/#194`, range `2025-03-26` to `2026-06-18`, main board, daily D+1 open model.
- Baseline result: return about `+82.99%`, max drawdown about `-15.59%`, buy/sell/open `224 / 214 / 10`.
- Candidate observation: top `100`, page size `20`.
- Portfolio execution: BUY candidates top `20`, max positions `10`.
- Ordinary UI should stay simple: one public strategy, one candidate pool, one backtest review path.

Important prior evidence:

- Broad low-suction launch hard gates reduced return.
- Broad entry launch quality scoring reduced return.
- Low-suction market-risk penalty did not improve global result.
- Repeated dragon hard rejection reduced return and worsened drawdown.
- Broad failed-launch / early-breakdown exits reduced total return or missed trend winners.
- Therefore the next implementation must start with read-only diagnostics and factor tables, not direct score changes.

Current local execution note:

- `alphaagent/server/services/quant/low_suction_quality.py` already has a partially started read-only `entry_family_context` implementation in the current workspace.
- `tests/alphaagent/test_quant_backtest_portfolio.py` already has early failing tests for `entry_family` normalization in the current workspace.
- The first execution task is to finish wiring and verify those tests. Do not restart from scratch unless the current diff is intentionally discarded by the user.

## Non-Negotiable Rules

- Do not modify `vnpy/` or official examples.
- Do not run `git commit` or `git push` unless the user explicitly asks.
- Do not add a second public strategy dropdown. Internal setups can be split; product remains one strategy.
- Do not reserve forced low-suction slots. Low-suction candidates must compete by score/rank.
- Do not use historical `14:30` data for the historical default strategy.
- Do not use outcome/label data for signal-day score, rank, action, or sell decisions.
- Do not let read-only audit fields change persisted score/action/failed rules.
- Do not treat low-suction buildup days as repeated buy points. Buildup is context; the key marker is the first effective lift/reclaim.
- Do not promote any rule unless it beats baseline on global, yearly, market-regime, rank-bucket, focus-symbol, and no-future-function checks.

## Final Internal Strategy Shape

Product label can stay close to:

```text
主线低吸转强策略
```

Internal entry engines:

```text
dragon_score = dragon_entry_score + shared_quality_score - risk_penalty
low_reclaim_score = low_reclaim_entry_score + shared_quality_score - risk_penalty
final_entry_score = max(dragon_score, low_reclaim_score)
```

Definitions:

- `dragon_pullback`: strong first leg exists, then pullback to MA5/MA10/MA20 or nearby support, then reclaim/weak-to-strong.
- `low_position_reclaim`: no required strong first leg; low/mid-low accumulation, support hold, MA convergence or support reclaim, and first effective lift.
- Shared quality factors: MA convergence, support hold, shrinking volume, close location, first effective lift, moderate volume expansion.
- Shared risk factors: high-level sideways distribution, volume stall, key support break, spiky churn, illiquidity, weekly top-fractal risk, overhead pressure.
- Market context: index trend, breadth, sector/theme strength, fund-flow coverage, recovery/risk-off state.

If both engines match, UI can show `龙回头叠加低吸`, but shared factors must not be counted twice.

## Focus Samples

Use these for post-task spot checks. They are review samples, not tuning targets.

| Symbol | Required Check |
| --- | --- |
| `603439.SSE` 三力制药 | Review `2026-05-08` / `2026-05-11` as low-position accumulation then launch; also review later overlap signals and portfolio constraints. |
| `002384.SZSE` 东山精密 | Review `2026-03-27..2026-04-08` and `2026-06-09..2026-06-12`: buildup context should accumulate, key marker should be first effective lift. |
| `002119.SZSE` 康强电子 | Review signal exists but wrong execution timing / repeated-risk loss. |
| `601179.SSE` 中国西电 | Separate early dragon around `2026-02-03` from later durable low-suction point `2026-02-24/25`. |
| `600352.SSE` 浙江龙盛 | Review `2026-03-10` false low-suction/launch into downtrend. |
| `002240.SZSE` 盛新锂能 | Review `2026-03-13` false start under weak market. |
| `002443.SZSE` 金洲管道 | Review buy around `2026-05-14` and sell/profit-giveback path. |
| `002208.SZSE` 合肥城建 | Review low-suction capture, false entries, and drawdown. |
| `600367.SSE` 红星发展 | Review low-suction washout before launch. |
| `002747.SZSE` 埃斯顿 | Review low-suction washout before launch. |

## Feature Tables To Build Before More Global Backtests

Global return alone cannot tell whether the buy point, sell point, market context, or portfolio capacity caused a result. Build these read-only tables first.

### 1. Candidate Feature Snapshot

One row per candidate/signal date, using only data visible at `trade_date`.

Required fields:

- Identity: `trade_date`, `vt_symbol`, `name`, `board`, `industry`, `concepts`.
- Setup: `entry_family`, `entry_family_label`, `low_position_reclaim_type`, `low_position_reclaim_label`, `setup_overlap`, `entry_family_conflict`.
- Action/rank: `entry_action`, `raw_entry_signal`, `executable_entry_signal`, `total_score`, `rank`, `rank_bucket`.
- Score parts: `dragon_entry_score`, `low_reclaim_entry_score`, `shared_quality_score`, `risk_penalty`.
- Low-suction lifecycle: `low_suction_days`, `support_hold_days`, `low_suction_stage_label`, `low_suction_launch_quality_label`, `first_effective_lift`, `launch_confirmed`.
- MA/support: `ma_convergence_pct`, `ma5_distance_pct`, `ma10_distance_pct`, `ma20_distance_pct`, `ma30_distance_pct`, `ma5_slope_pct`, `ma10_slope_pct`, `ma20_slope_pct`, `ma30_slope_pct`.
- Volume/liquidity: `volume_ratio_5d_20d`, `turnover_percentile_60d`, `turnover`, `amount`, `liquidity_score`.
- Candle: `close_location_in_range`, `body_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `gap_up_pct`.
- Strength proxies: `recent_limit_up_20d`, `near_limit_up_count_20d`, `large_bull_count_20d`, `consecutive_bull_closes`, `persistent_volume_expansion`.
- Risk: `drawdown_from_pivot_pct`, `max_drawdown_60d`, `overhead_pressure_pct`, `high_level_sideways_distribution_risk`, `volume_stall_risk`, `key_support_break_risk`, `spiky_churn_risk`, `illiquid_forgotten_risk`, `weekly_top_fractal_risk`.
- Market: `dynamic_market_regime`, `market_warning_level`, `fund_flow_state`, `fund_flow_streak_days`, `recovery_state`, `dominant_theme`, `theme_strength`, `fund_flow_source`.
- Audit metadata: `as_of_date`, `feature_window_end`, `uses_future_for_label_only=false`, `not_used_for_signal_score=true`.

### 2. Fixed-Horizon Candidate Outcome

One row per candidate/signal date, independent from portfolio capacity. These are label-only fields.

Required fields:

- `signal_date`, `execute_date`, `execute_open_price`.
- `return_3d`, `return_5d`, `return_10d`, `return_20d`.
- `mfe_3d`, `mfe_5d`, `mfe_10d`, `mfe_20d`.
- `mae_3d`, `mae_5d`, `mae_10d`, `mae_20d`.
- `hit_profit_5_pct`, `hit_profit_8_pct`, `hit_profit_10_pct`.
- `hit_loss_3_pct`, `hit_loss_5_pct`, `hit_loss_7_pct`.
- `first_hit`: `profit`, `loss`, `none`.
- `failed_launch`: no small launch and support breaks.
- `support_stop_like`: support-stop proxy would trigger.
- `current_strategy_exit_date`, `current_strategy_return_pct` when the portfolio actually traded it.
- `uses_future_for_label_only=true`, `not_used_for_signal_score=true`.

### 3. Real Portfolio Execution Attribution

One row per candidate after portfolio constraints.

Required fields:

- `signal_date`, `execute_date`, `vt_symbol`, `rank`, `score`.
- `planned`, `ordered`, `filled`.
- `not_filled_reason`: full position, no rotation, limit-up open, no execute bar, already held, lower rank, theoretical holding mismatch.
- `position_count_before`, `execution_pool_rank`, `rotation_candidate`, `rotation_reason`.
- `buy_price`, `sell_price`, `sell_reason`, `closed_return_pct`, `holding_days`.

### 4. Factor Bucket Audit

Aggregate candidate outcomes by:

- Setup family and overlap state.
- Low-suction days: `0`, `1-2`, `3-5`, `6-10`, `10+`.
- MA convergence: `<3%`, `3-6%`, `6-10%`, `>10%`.
- Volume: `shrinking`, `normal`, `moderate_expansion`, `double_volume`, `explosive`.
- Close location: low/middle/high.
- Distance-to-MA: below support, near support, reclaimed, extended.
- Market regime: strong broad, narrow theme, choppy rotation, false bull, weak/risk-off.
- Fund-flow: inflow, recovery, outflow, panic outflow, insufficient data.
- Rank: top 10, top 20, top 100, outside top 100.

Metrics:

- `sample_count`, `win_rate`, `average_return`, `median_return`, `profit_factor`.
- `mfe_8_pct_hit_ratio`, `mae_5_pct_loss_ratio`, `failed_launch_ratio`, `support_stop_like_ratio`.
- `average_time_to_first_5_pct_profit`.

### 5. Success And Failure Path Tables

Success paths:

- Launch within 3 days.
- Launch within 5 days.
- Trend along MA5.
- Shrinking pullback then second acceleration.
- Market weak but stock independently strong.
- Sector/theme co-movement.
- Low-position first launch.
- Dragon pullback relaunch.

Failure paths:

- No launch and support break.
- Launch confirmed but immediate failure.
- Low-suction unconfirmed.
- High-level distribution.
- Volume stall at high level.
- Market risk-off drag.
- Sold early then rebound.
- Profit giveback turned into loss.
- Wrong replacement after exit.

### 6. Unified Strategy Timeline

One merged event stream for stock detail:

- Candidate/signal event.
- Theoretical plan event.
- Real order/trade event.
- Rejection/not-ordered reason.
- Sell event and closed return.

Each symbol/date should be one merged row. The UI should show buy, rejected/not bought, and sell markers only.

## Task 0: Freeze Baseline And Verify Current Workspace

**Files:**

- Read: `memory/06_backtests/strategy_optimization_ledger.md`
- Read: `memory/09_decisions/decisions.md`
- Modify only if facts change: `memory/06_backtests/strategy_optimization_ledger.md`

- [x] Step 1: Inspect dirty worktree.

Run:

```bash
git status --short
```

Expected: note unrelated dirty files. Do not revert them.

- [ ] Step 2: Confirm product baseline remains `0.1.21 / #203/#194`.

Run when API is available:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
```

Expected: latest baseline items include `#203` or `#194`, `strategy_version=0.1.21`, not excluded experiments.

- [x] Step 3: Write down baseline metrics in the execution notes before testing changes.

Expected baseline comparison target:

```text
return ~= +82.99%
max_drawdown ~= -15.59%
buy/sell/open ~= 224 / 214 / 10
```

## Task 1: Finish Read-Only Setup Family Labels

**Files:**

- Modify: `alphaagent/server/services/quant/low_suction_quality.py`
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `alphaagent/server/services/quant/screening_payloads.py`
- Modify: `alphaagent/server/services/quant/strategy_registry.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Run the current failing tests for the partially started work.

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "low_position_reclaim_context or keeps_dragon_family or high_level_sideways" -q
```

Expected before wiring: failure around missing `entry_family` or missing normalized labels.

- [x] Step 2: Ensure `low_suction_quality.py` exposes these functions.

Required public helper names:

```python
def entry_family_context(evidence: dict[str, Any]) -> dict[str, Any]:
    ...

def ensure_entry_family_context(evidence: dict[str, Any]) -> None:
    ...

def low_position_reclaim_label(kind: Any) -> str:
    ...
```

Required output fields:

```python
{
    "entry_family": "dragon_pullback" | "low_position_reclaim" | "unknown",
    "entry_family_label": "龙回头回踩" | "低位承接转强" | "未归类",
    "entry_family_conflict": bool,
    "entry_family_notes": list[str],
    "low_position_reclaim_type": "platform_accumulation_launch" | "ma_support_reclaim" | "deep_reclaim" | "none",
    "low_position_reclaim_label": str,
    "is_readonly_setup_diagnostic": True,
}
```

Classification rules for the first pass:

- `dragon_pullback`: `setup_type=dragon_pullback`, `dragon_state=TAIL_BUY_READY`, or strong first-leg evidence.
- `platform_accumulation_launch`: low/mid-low position, no distribution/break risk, `low_suction_days>=3`, MA convergence, controlled volume, support not broken, and launch/first lift evidence.
- `ma_support_reclaim`: low/mid-low position, near/reclaimed MA5/MA10/MA20/MA30, close strength, support not broken, controlled volume.
- `deep_reclaim`: deeper recovery from drawdown, support reclaimed, close strength, and not a high-level distribution shape.
- High-level sideways/distribution and key support break must force `low_position_reclaim_type=none`.

- [x] Step 3: Wire read-side normalization.

In `alphaagent/server/services/quant/screening_payloads.py`, add a normalization call inside `normalize_quant_evidence()` after low-suction stage / launch quality / dragon context normalization:

```python
from alphaagent.server.services.quant.low_suction_quality import ensure_entry_family_context

def _normalize_entry_family_context(evidence: dict[str, Any]) -> None:
    ensure_entry_family_context(evidence)
```

Expected behavior: old persisted recommendation rows get labels at read time without changing persisted score/action.

- [x] Step 4: Wire live evidence generation.

In `alphaagent/server/services/quant/strategies/dragon_pullback.py`, import `ensure_entry_family_context`. In `_evidence()`, build the payload dict first, call `ensure_entry_family_context(payload)`, then return it.

Expected behavior: new `SignalScore.evidence` includes setup-family diagnostics, but `total_score`, `entry_signal`, `failed_rules`, and action are unchanged.

- [x] Step 5: Add strategy metadata labels.

In `alphaagent/server/services/quant/strategy_registry.py`, add evidence labels:

```python
"entry_family": "入场家族",
"entry_family_label": "入场类型",
"low_position_reclaim_type": "低位承接类型",
"low_position_reclaim_label": "低位承接标签",
```

- [x] Step 6: Verify focused tests.

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "low_position_reclaim_context or keeps_dragon_family or high_level_sideways" -q
```

Expected: pass.

- [x] Step 7: Verify no broad regression in nearby tests.

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "low_suction or dragon_family or entry_family" -q
```

Expected: pass.

## Task 2: Build Candidate Feature Extraction

**Files:**

- Create: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add unit tests for flat candidate feature rows.

Test expectations:

```python
assert row["setup_primary"] == "low_position_reclaim"
assert row["low_position_reclaim_type"] == "platform_accumulation_launch"
assert row["rank_bucket"] == "top_10"
assert row["ma_convergence_pct"] == 4.2
assert row["dynamic_market_regime"] == "false_bull"
assert row["uses_future_for_label_only"] is False
assert row["not_used_for_signal_score"] is True
```

- [x] Step 2: Implement pure helpers in `factor_audit.py`.

Required functions:

```python
def rank_bucket(rank: int | None) -> str:
    ...

def candidate_feature_row(row: dict[str, Any], *, stock: dict[str, Any] | None = None) -> dict[str, Any]:
    ...

def candidate_feature_rows(rows: list[dict[str, Any]], stocks: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    ...
```

Rules:

- Read `reason` first, fallback to `evidence`.
- Call `normalize_quant_evidence()` before extracting labels.
- Do not inspect future bars.
- Preserve raw `action` plus normalized `entry_action`.
- Include `as_of_date=trade_date` and `feature_window_end=trade_date`.

- [x] Step 3: Add read service wrapper.

Expose a backend service function, preferably through `alphaagent/server/services/backtest/engine.py` to match existing API imports:

```python
def backtest_factor_candidates(backtest_id: int, vt_symbol: str | None = None, limit: int = 500) -> dict[str, Any]:
    ...
```

Return shape:

```json
{
  "status": "ready",
  "backtest_id": 203,
  "items": [],
  "coverage": {
    "candidate_count": 0,
    "signal_count": 0,
    "used_signal_fallback_count": 0
  }
}
```

- [x] Step 4: Add API endpoint.

In `alphaagent/server/api/backtests.py` add:

```text
GET /api/backtests/{backtest_id}/factor-candidates?vt_symbol=&limit=
```

- [x] Step 5: Run tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "factor_candidate" -q
```

Expected: pass.

## Task 3: Build Fixed-Horizon Outcome Rows

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add no-future outcome tests.

Construct bars where signal date is D, execute date is next available trading day D+1, and all returns are computed after execution.

Expected assertions:

```python
assert row["execute_date"] == date(2026, 5, 11)
assert row["return_5d"] == expected_return
assert row["mfe_5d"] == expected_mfe
assert row["mae_5d"] == expected_mae
assert row["uses_future_for_label_only"] is True
assert row["not_used_for_signal_score"] is True
```

- [x] Step 2: Implement outcome helper.

Required function:

```python
def fixed_horizon_outcome_row(
    *,
    signal_date: date,
    bars: list[Bar],
    horizons: tuple[int, ...] = (3, 5, 10, 20),
) -> dict[str, Any]:
    ...
```

Rules:

- Execute at next available trading day open.
- If no D+1 bar exists, return `status=no_execute_bar`.
- Compute return from execute open to horizon close.
- Compute MFE/MAE from post-execution high/low.
- Mark all fields as label-only.

- [x] Step 3: Join outcomes to feature rows.

Return both `feature` and `outcome` fields in API rows, or flatten outcome fields with an `outcome_` prefix. Keep the contract stable once frontend uses it.

- [x] Step 4: Run tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "fixed_horizon_outcome or no_future" -q
```

Expected: pass.

## Task 4: Build Factor Bucket Audit

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add bucket helper tests.

Expected helpers:

```python
assert rank_bucket(1) == "top_10"
assert rank_bucket(17) == "top_20"
assert rank_bucket(75) == "top_100"
assert ma_convergence_bucket(4.2) == "3-6"
assert low_suction_days_bucket(4) == "3-5"
assert volume_bucket(1.3) == "normal"
```

- [x] Step 2: Implement bucket helpers.

Required functions:

```python
def ma_convergence_bucket(value: float | None) -> str: ...
def low_suction_days_bucket(days: int | float | None) -> str: ...
def volume_bucket(volume_ratio: float | None) -> str: ...
def close_location_bucket(value: float | None) -> str: ...
def market_regime_bucket(value: str | None) -> str: ...
def fund_flow_bucket(value: str | None) -> str: ...
```

- [x] Step 3: Implement aggregate metrics.

Required metrics for each bucket:

```python
{
    "bucket": "...",
    "sample_count": 0,
    "win_rate": 0.0,
    "average_return": 0.0,
    "median_return": 0.0,
    "profit_factor": 0.0,
    "mfe_8_pct_hit_ratio": 0.0,
    "mae_5_pct_loss_ratio": 0.0,
    "failed_launch_ratio": 0.0,
    "support_stop_like_ratio": 0.0
}
```

- [x] Step 4: Add service and API endpoint.

Service:

```python
def backtest_factor_audit(backtest_id: int, top_limit: int = 100) -> dict[str, Any]:
    ...
```

Endpoint:

```text
GET /api/backtests/{backtest_id}/factor-audit?top_limit=100
```

Response shape:

```json
{
  "status": "ready",
  "summary": {},
  "by_setup": [],
  "by_rank_bucket": [],
  "by_market_regime": [],
  "by_factor_bucket": {},
  "success_paths": [],
  "failure_paths": [],
  "coverage": {}
}
```

- [x] Step 5: Run tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "factor_audit" -q
```

Expected: pass.

## Task 5: Build Unified Strategy Timeline

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add merged timeline tests.

Expected for a same-day candidate that did not trade because the portfolio was full:

```python
assert row["date"] == "2026-06-17"
assert row["candidate"]["action"] == "BUY"
assert row["execution"]["status"] == "planned_not_ordered"
assert row["execution"]["reason_code"] == "portfolio_full_no_rotation"
```

- [x] Step 2: Implement merge helper.

Required function:

```python
def strategy_timeline_rows(
    *,
    recommendations: list[dict[str, Any]],
    signal_events: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    vt_symbol: str,
) -> list[dict[str, Any]]:
    ...
```

Rules:

- One row per symbol/date.
- Merge candidate, theoretical signal, order, trade, rejection, and sell events.
- Do not duplicate same-day candidate BUY and filled BUY marker.
- Preserve statuses: `recognized`, `planned`, `ordered`, `filled`, `not_ordered`, `rejected`, `sold`.
- Include `reason_label` and raw evidence for detail display.

- [x] Step 3: Add service and API endpoint.

Service:

```python
def backtest_strategy_timeline(backtest_id: int, vt_symbol: str) -> dict[str, Any]:
    ...
```

Endpoint:

```text
GET /api/backtests/{backtest_id}/strategy-timeline?vt_symbol=603439.SSE
```

- [x] Step 4: Run tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_timeline" -q
```

Expected: pass.

## Task 6: Frontend Integration With Simple UI

**Files:**

- Modify: `frontend/src/api/quant.ts`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/features/stocks/StockKlineChart.tsx`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`

- [x] Step 1: Add TypeScript API types.

Add:

```ts
export interface FactorAuditResponse { status: string; summary?: Record<string, unknown>; by_setup?: unknown[]; by_rank_bucket?: unknown[]; by_market_regime?: unknown[]; by_factor_bucket?: Record<string, unknown[]>; }
export interface StrategyTimelineEvent { date: string; vt_symbol: string; candidate?: Record<string, unknown>; execution?: Record<string, unknown>; sell?: Record<string, unknown>; markers?: string[]; }
export interface StrategyTimelineResponse { status: string; backtest_id: number; vt_symbol: string; items: StrategyTimelineEvent[]; }
```

Add fetchers:

```ts
export function fetchBacktestFactorAudit(backtestId: number, topLimit = 100) { ... }
export function fetchBacktestFactorCandidates(backtestId: number, params?: { vt_symbol?: string; limit?: number }) { ... }
export function fetchBacktestStrategyTimeline(backtestId: number, vtSymbol: string) { ... }
```

- [x] Step 2: Replace stock-detail `交易复盘 / 候选信号` split with `策略时间线`.

UI rules:

- One compact timeline/table.
- K-line markers only show buy, rejected/not bought, and sell.
- Detail panel shows score, rank, setup family, low-suction days, market context, and not-bought reason.
- If the endpoint is unavailable, fall back to current markers and show a small warning.

- [x] Step 3: Show audit summaries on backtest review without adding a new main workflow.

Backtest page should show:

- Setup bucket performance.
- Top 10 / top 20 fixed-horizon candidate quality.
- Market-regime split.
- Excluding-strong-market summary when available.
- Data coverage / no-future-function notice.

- [x] Step 4: Build frontend.

```bash
pnpm --dir frontend run build
```

Expected: build passes. Existing large chunk warnings are acceptable.

## Task 7: Produce Baseline Evidence Pack

**Files:**

- Create: `memory/06_backtests/YYYY-MM-DD_low_position_reclaim_factor_audit.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/06_backtests/strategy_optimization_ledger.md`
- Modify only if decision changes: `memory/09_decisions/decisions.md`

- [x] Step 1: Run baseline audit endpoints.

Use the current product baseline id:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=1'
```

Then run:

```bash
curl -sS 'http://localhost:8000/api/backtests/<id>/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/<id>/factor-candidates?vt_symbol=603439.SSE&limit=200'
curl -sS 'http://localhost:8000/api/backtests/<id>/strategy-timeline?vt_symbol=603439.SSE'
curl -sS 'http://localhost:8000/api/backtests/<id>/strategy-timeline?vt_symbol=002384.SZSE'
curl -sS 'http://localhost:8000/api/backtests/<id>/strategy-timeline?vt_symbol=002443.SZSE'
```

- [x] Step 2: Write report sections.

Required sections:

- Baseline run id, version, range, metrics.
- No-future-function statement.
- By setup family performance.
- By low-suction days / MA convergence / volume / market regime performance.
- Top 10 and top 20 candidate quality.
- Excluding strong-market result.
- Focus-symbol timeline findings.
- Whether the evidence supports an experiment, and which exact experiment.

- [x] Step 3: Update memory overview only with conclusions.

Do not paste raw API output into overview files. Put detailed evidence in the dated report and link it from `memory/06_backtests/README.md` and the ledger.

## Task 8: Add Default-Off Experiments Only If Evidence Supports Them

Do this only after Tasks 1-7 are complete and the baseline evidence pack identifies a narrow rule with measurable edge.

Current Task 7 decision:

- `memory/06_backtests/2026-06-19_low_position_reclaim_factor_audit.md` does not support a new trading-rule experiment yet.
- Reason 1: current rebuilt API `baseline_only=true` returns `#213`, a longer baseline range than the prior `#203/#194`, so promotion comparisons would mix baselines.
- Reason 2: `low_position_reclaim` top-100 fixed-horizon audit is promising but only has `15` samples, and long-range fund-flow buckets are still `unknown`.
- Therefore Task 8 must remain pending until the baseline selection drift is fixed and the audit is rerun on the intended product baseline.

**Files:**

- Modify: `alphaagent/server/services/backtest/schemas.py`
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `alphaagent/server/services/quant/candidate_lanes.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [ ] Step 1: Add default-false params.

Candidate params:

```python
enable_low_position_reclaim_entry: bool = False
enable_low_position_reclaim_score: bool = False
enable_validated_factor_weighting: bool = False
enable_contextual_reclaim_risk_penalty: bool = False
```

Only add a sell param if the evidence pack clearly supports sell-side work:

```python
enable_contextual_support_stop_review_exit: bool = False
```

- [ ] Step 2: Add tests proving defaults preserve baseline behavior.

Synthetic case:

- With all new params false, candidate ordering and entry action match current behavior.
- With a flag true, only the intended setup changes.
- Shared factors are not double-counted.

- [ ] Step 3: Implement the narrow experiment behind flags only.

Allowed experiment examples:

- Promote `low_position_reclaim` to candidate only when factor buckets show improved fixed-horizon win rate and no weak-market deterioration.
- Apply a narrow risk penalty only when weak market + failed first lift + support/reclaim weakness are all present.
- Apply sell-side experiment only when path table proves a context-specific stop/giveback class and replacement quality is acceptable.

Disallowed:

- Direct broad low-suction bonus.
- Broad low-suction launch hard gate.
- Broad repeated-dragon rejection.
- Generic early stop after three days.

- [ ] Step 4: Run full comparison and mark experiment excluded from baseline until promoted.

Expected comparison fields:

- Total return.
- Max drawdown.
- Win rate.
- Profit factor.
- Buy/sell/open count.
- Year split.
- Market-regime split.
- Top 10 real closed win rate.
- Top 10 fixed-horizon candidate win rate.
- Focus-symbol changes.
- Missed trend-winner audit.

## Promotion Criteria

A scoring/execution/sell change can become default only if all conditions hold:

1. Full global return is not lower than baseline by more than negligible noise, and preferably improves.
2. Max drawdown improves or stays flat.
3. Profit factor improves or stays flat.
4. Top-10 fixed-horizon candidate win rate improves, including when strong-market windows are excluded.
5. Yearly split does not show one year carrying all improvement while another deteriorates sharply.
6. Weak/choppy/false-bull regimes do not worsen materially.
7. Focus samples improve for the intended reason, not because of accidental portfolio path changes.
8. Existing major winners are not missed or prematurely sold.
9. No future data is used for score, rank, execution, or sell decisions.
10. `memory/06_backtests/strategy_optimization_ledger.md` is updated with run id, metrics, decision, and evidence file.

If a change improves explanation but not portfolio metrics, keep it read-only.

## Verification Commands

Run after implementation tasks:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api
pnpm --dir frontend run build
git diff --check
```

Expected:

- pytest passes.
- compileall passes.
- frontend build passes.
- `git diff --check` passes.

## Execution Order

1. Task 0: freeze baseline and workspace facts.
2. Task 1: read-only setup-family labels.
3. Task 2: candidate feature rows.
4. Task 3: fixed-horizon outcome rows.
5. Task 4: factor bucket audit.
6. Task 5: unified strategy timeline endpoint.
7. Task 6: frontend unified timeline and audit summaries.
8. Task 7: baseline evidence pack.
9. Task 8: default-off experiment only if the evidence supports a narrow rule.

This order keeps product behavior stable while building enough evidence to decide whether the low-suction/dragon boundary should affect scoring, execution, or selling.
