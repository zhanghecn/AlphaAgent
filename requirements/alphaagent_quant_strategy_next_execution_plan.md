# AlphaAgent Quant Strategy Next Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not change default trading behavior until this plan explicitly reaches the default-off experiment gate.

**Goal:** Build the next validation layer for AlphaAgent's single public low-buy strategy so future changes can prove whether they improve收益、胜率、回撤 and weak-market robustness before entering trading rules.

**Architecture:** Keep one public strategy and one simple user workflow. Internally add a baseline policy gate, read-only factor tables, outcome labels, market/path attribution, and a narrow promotion process for default-off experiments. Feature/outcome labels are audit-only and must never feed signal-day score, rank, buy/sell, or position logic.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, existing `backtest_*` and `quant_*` tables, React/TypeScript, pytest, Vite, existing AlphaAgent memory reports under `memory/06_backtests/`.

---

## Current Starting Point

Current useful facts:

- Public strategy: `mainline_dragon_pullback / 0.1.21`.
- Intended product baseline in existing reports: `#203/#194`, range `2025-03-26..2026-06-18`, return about `+82.99%`, max drawdown about `-15.59%`, buy/sell/open `224 / 214 / 10`.
- Latest rebuilt API once returned `#213`, range `2024-05-28..2026-06-18`, return about `+45.17%`, max drawdown about `-23.83%`. This is a baseline selection drift until the product start-date and data completeness rule is explicit.
- Existing read-only endpoints already exist or are partially implemented:
  - `GET /api/backtests/{id}/factor-candidates`
  - `GET /api/backtests/{id}/factor-audit`
  - `GET /api/backtests/{id}/strategy-timeline`
  - `GET /api/backtests/{id}/setup-market-exit-audit`
  - `GET /api/backtests/{id}/path-diagnostics`
  - `GET /api/backtests/{id}/top-candidate-audit`
- Existing evidence says broad hard gates failed: repeated dragon hard reject, low-suction launch hard gate, low-suction quality hard gate, broad launch-quality score, launch-risk penalty, market-risk penalty, failed-launch early exit, and broad profit-giveback stop all failed or reduced return.

Do not treat `#213` and `#203/#194` as the same baseline. Task 1 must resolve that before any new experiment comparison.

## Product Rules

- Keep only one public strategy in UI: `主线低吸转强策略` / `mainline_dragon_pullback`.
- Internally keep `dragon_pullback` and `low_position_reclaim` as separate setup families.
- Shared factors such as MA convergence, support hold, controlled volume, close location, and first effective lift can be used for audit buckets, but must not be double-counted when both setup families overlap.
- Low-suction buildup days are context, not repeated buy points. The key buy marker is the first effective lift/reclaim after buildup.
- Candidate observation remains top `100` with pagination. Portfolio execution remains BUY top `20`, max positions `10`.
- Historical default remains daily D+1 open execution. Historical strategy validation must not depend on missing historical `14:30` data.
- Outcome labels, MFE/MAE, failed-launch labels, support-stop-like labels, sell-after-rebound labels, and fixed-horizon returns are future-looking audit fields only.

## Files By Responsibility

- Modify: `alphaagent/server/services/backtest/engine.py`
  - Baseline selection wrapper, factor audit service wrappers, and existing API service entrypoints.
- Create: `alphaagent/server/services/backtest/baseline_policy.py`
  - Product baseline eligibility and selection explanation.
- Modify: `alphaagent/server/services/backtest/factor_audit.py`
  - Candidate feature rows, fixed-horizon outcomes, bucket metrics, and strategy timeline helpers.
- Modify: `alphaagent/server/services/backtest/queries.py`
  - Existing path diagnostics and setup/market/exit attribution extensions.
- Modify: `alphaagent/server/api/backtests.py`
  - API endpoints and query parameters.
- Modify: `alphaagent/server/db/schema.py`
  - Only if persistent audit cache tables are needed after Task 2 performance check.
- Modify: `frontend/src/api/quant.ts`
  - Type definitions and API calls.
- Modify: `frontend/src/features/quant/BacktestPanel.tsx`
  - Baseline warning, factor audit panel, and first-screen evidence.
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
  - Factor bucket and market/regime audit display.
- Modify: `frontend/src/pages/StockDetailPage.tsx`
  - Unified strategy timeline markers.
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`
  - Unit and API tests for baseline policy, audit fields, no-future labels, and timeline merge.
- Update: `memory/06_backtests/strategy_optimization_ledger.md`
  - Only after a verified run or experiment produces durable evidence.
- Create evidence reports under `memory/06_backtests/`
  - One report per completed validation batch.

## Task 1: Fix Product Baseline Selection

**Purpose:** Make `/quant` and stock detail always use a clearly explainable product baseline, not whichever default run has the earliest start date.

**Files:**

- Create: `alphaagent/server/services/backtest/baseline_policy.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add a baseline-policy unit test.

Add a test that builds three fake rows:

```python
def test_product_baseline_prefers_complete_current_policy_over_longer_drift_run() -> None:
    from alphaagent.server.services.backtest.baseline_policy import select_product_baselines

    rows = [
        {
            "id": 213,
            "run_type": "portfolio",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.21",
            "start_date": "2024-05-28",
            "end_date": "2026-06-18",
            "params": {
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "baseline_policy": "long_unconfirmed",
            },
        },
        {
            "id": 203,
            "run_type": "portfolio",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.21",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "baseline_policy": "current_product",
            },
        },
        {
            "id": 208,
            "run_type": "portfolio",
            "strategy_id": "mainline_dragon_pullback",
            "strategy_version": "0.1.21",
            "start_date": "2025-03-26",
            "end_date": "2026-06-18",
            "params": {
                "execution_model": "legacy_next_open",
                "candidate_limit": 20,
                "max_positions": 10,
                "require_low_suction_launch_for_low_suction_context": True,
            },
        },
    ]

    selected = select_product_baselines(rows)

    assert [row["id"] for row in selected] == [203]
    assert selected[0]["baseline_reason"] == "current_product_policy"
```

- [x] Step 2: Implement baseline policy helper.

Required public functions:

```python
def is_product_baseline_params(params: dict[str, object]) -> bool:
    ...

def baseline_policy_name(params: dict[str, object]) -> str:
    ...

def select_product_baselines(items: list[dict[str, object]]) -> list[dict[str, object]]:
    ...
```

Required first policy:

- Reject `exclude_from_product_baseline=true`.
- Reject any research switches that are true.
- Require `execution_model` empty or `legacy_next_open`.
- Require `candidate_limit` empty or `20`.
- Require `max_positions` empty or `10`.
- Prefer rows with `params.baseline_policy == "current_product"` when present.
- If no explicit policy exists, choose latest `end_date`, then the most common complete `start_date` among default rows, not blindly the earliest start date.
- Add `baseline_reason` and `baseline_warning` to selected rows.

- [x] Step 3: Replace `_filter_product_baseline_backtests`.

In `engine.py`, make `_filter_product_baseline_backtests(items)` call `select_product_baselines(items)` from the new helper. Keep the existing function name as a compatibility wrapper for tests and callers.

- [x] Step 4: Add API smoke check.

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
```

Expected:

- Returns a `ready` payload.
- Does not return research experiments.
- If `#213` is returned, the response includes a warning explaining why it is accepted as the product baseline.
- If `#203/#194` is returned, the response explains it is the current product policy baseline.

- [x] Step 5: Update evidence if behavior changes.

If the selected baseline changes, update:

- `memory/06_backtests/README.md`
- `memory/06_backtests/strategy_optimization_ledger.md`

Do not run a new trading experiment in this task.

## Task 2: Decide Whether Factor Rows Need Persistent Cache

**Purpose:** Keep UI simple while avoiding slow repeated factor/audit recomputation.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify only if needed: `alphaagent/server/db/schema.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Measure current endpoint cost.

Run:

```bash
time curl -sS 'http://localhost:8000/api/backtests/203/factor-candidates?limit=2000' >/tmp/factor_candidates_203.json
time curl -sS 'http://localhost:8000/api/backtests/203/factor-audit?top_limit=100' >/tmp/factor_audit_203.json
```

Decision rule:

- If both calls finish within `3s` on the local Docker API, keep read-through computation and do not add tables.
- If either call exceeds `3s`, add an internal cache table.

- [x] Step 2: If caching is needed, add two tables.

Add these tables in `alphaagent/server/db/schema.py`:

```python
backtest_factor_snapshots = Table(
    "backtest_factor_snapshots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("backtest_id", Integer, index=True, nullable=False),
    Column("trade_date", Date, index=True, nullable=False),
    Column("vt_symbol", String(32), index=True, nullable=False),
    Column("rank", Integer, nullable=True),
    Column("entry_family", String(64), nullable=True),
    Column("payload", JSON, nullable=False, default=dict),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)

backtest_factor_outcomes = Table(
    "backtest_factor_outcomes",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("backtest_id", Integer, index=True, nullable=False),
    Column("signal_date", Date, index=True, nullable=False),
    Column("vt_symbol", String(32), index=True, nullable=False),
    Column("payload", JSON, nullable=False, default=dict),
    Column("created_at", DateTime, nullable=False, default=datetime.utcnow),
)
```

- [x] Step 3: Add an internal build function only if caching is needed.

Required signature:

```python
def ensure_factor_audit_cache(backtest_id: int, *, limit: int = 2000) -> dict[str, object]:
    ...
```

Rules:

- This function is called internally by `GET /factor-audit`.
- Do not add a new user-facing button.
- Cache rows must include `not_used_for_signal_score=true`.
- Cache rows must be rebuilt when strategy version, backtest ID, or candidate payload changes.

- [x] Step 4: Add tests for cache neutrality if cache is added.

Expected assertions:

```python
assert cached_row["payload"]["not_used_for_signal_score"] is True
assert cached_row["payload"]["uses_future_for_label_only"] is False
assert cached_outcome["payload"]["uses_future_for_label_only"] is True
```

- [x] Step 5: Keep UI unchanged.

The user should still only see factor audit inside the existing backtest review. No extra "generate audit table" operation should appear.

## Task 3: Expand Candidate Feature Snapshot

**Purpose:** Let later analysis answer which visible features explain success/failure, without using future data.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/quant/screening_payloads.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add test for required visible fields.

Use a fake recommendation row with a rich `reason` dict and assert:

```python
assert row["entry_family"] in {"dragon_pullback", "low_position_reclaim", "unknown"}
assert row["low_position_reclaim_type"] in {
    "platform_accumulation_launch",
    "ma_support_reclaim",
    "deep_reclaim",
    "none",
}
assert row["ma_convergence_pct"] == 4.2
assert row["volume_ratio_5d_20d"] == 1.15
assert row["close_location_in_range"] == 0.62
assert row["dynamic_market_regime"] == "choppy_rotation"
assert row["uses_future_for_label_only"] is False
assert row["not_used_for_signal_score"] is True
```

- [x] Step 2: Expand `candidate_feature_row`.

It must include these groups:

- Identity: `trade_date`, `vt_symbol`, `name`, `board`, `industry`, `concepts`.
- Setup: `entry_family`, `entry_family_label`, `low_position_reclaim_type`, `low_position_reclaim_label`, `entry_family_conflict`.
- Rank/action: `entry_action`, `raw_entry_signal`, `executable_entry_signal`, `total_score`, `rank`, `rank_bucket`.
- Score parts: `dragon_entry_score`, `low_reclaim_entry_score`, `shared_quality_score`, `risk_penalty`.
- Low-suction lifecycle: `low_suction_days`, `support_hold_days`, `low_suction_stage_label`, `low_suction_launch_quality_label`, `first_effective_lift`, `launch_confirmed`.
- MA/support: `ma5_distance_pct`, `ma10_distance_pct`, `ma20_distance_pct`, `ma30_distance_pct`, `ma_convergence_pct`, and MA slopes when present.
- Volume/liquidity: `volume_ratio_5d_20d`, `turnover_percentile_60d`, `turnover`, `amount`, `liquidity_score`.
- Candle: `close_location_in_range`, `body_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `gap_up_pct`.
- Strength proxies: `recent_limit_up_20d`, `near_limit_up_count_20d`, `large_bull_count_20d`, `consecutive_bull_closes`, `persistent_volume_expansion`.
- Risk: `drawdown_from_pivot_pct`, `max_drawdown_60d`, `overhead_pressure_pct`, `high_level_sideways_distribution_risk`, `volume_stall_risk`, `key_support_break_risk`, `spiky_churn_risk`, `illiquid_forgotten_risk`, `weekly_top_fractal_risk`.
- Market: `dynamic_market_regime`, `market_warning_level`, `fund_flow_state`, `fund_flow_streak_days`, `recovery_state`, `dominant_theme`, `theme_strength`, `fund_flow_source`.
- Audit metadata: `as_of_date`, `feature_window_end`, `uses_future_for_label_only=false`, `not_used_for_signal_score=true`.

- [x] Step 3: Normalize old persisted rows.

`candidate_feature_row` must call `normalize_quant_evidence(dict(reason))` before extraction. If a persisted row has old `action=BUY` but normalized evidence says `WATCH`, include:

```python
{
    "persisted_action": "BUY",
    "entry_action": "WATCH",
    "action_mismatch_resolved": True
}
```

- [x] Step 4: Run targeted tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "factor_candidate or entry_family or action_mismatch" -q
```

Expected: pass.

## Task 4: Expand Fixed-Horizon Outcome Labels

**Purpose:** Separate candidate quality from portfolio capacity and current sell rules.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add no-future tests.

Construct bars where signal date is `2026-05-08`, execute date is `2026-05-11`, and later bars contain a known high/low path.

Expected assertions:

```python
assert outcome["execute_date"] == date(2026, 5, 11)
assert outcome["execute_open_price"] == 10.0
assert outcome["return_5d"] == 6.0
assert outcome["mfe_5d"] == 12.0
assert outcome["mae_5d"] == -4.0
assert outcome["uses_future_for_label_only"] is True
assert outcome["not_used_for_signal_score"] is True
```

- [x] Step 2: Keep execution assumption explicit.

`fixed_horizon_outcome_row` must use:

- Signal date D.
- Execute date = next available trading day after D.
- Execute price = D+1 open.
- Horizon close = Nth trading day after execute date or final available close.
- MFE/MAE = high/low after execute date only.

- [ ] Step 3: Add current-strategy comparison fields when a real trade exists.

For candidates that became real portfolio trades, join:

```python
{
    "current_strategy_entry_date": "...",
    "current_strategy_exit_date": "...",
    "current_strategy_return_pct": 0.0,
    "current_strategy_exit_reason": "support_stop"
}
```

Interpretation rules:

- Fixed horizon positive, current strategy negative = likely sell/path problem.
- Fixed horizon negative, current strategy negative = likely buy/rank problem.
- Fixed horizon positive, not filled = likely ranking/capacity/rotation problem.

- [x] Step 4: Run targeted tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "fixed_horizon_outcome or no_future or current_strategy_return" -q
```

Expected: pass.

## Task 5: Build Fine-Grained Factor Bucket Audit

**Purpose:** Answer "which features actually improve win rate and return" before changing scores.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add bucket tests.

Expected bucket helpers:

```python
assert rank_bucket(1) == "top_10"
assert rank_bucket(17) == "top_20"
assert rank_bucket(75) == "top_100"
assert ma_convergence_bucket(2.9) == "<3"
assert ma_convergence_bucket(4.2) == "3-6"
assert low_suction_days_bucket(4) == "3-5"
assert volume_bucket(0.7) == "shrinking"
assert volume_bucket(1.3) == "normal"
assert close_location_bucket(0.62) == "middle"
```

- [x] Step 2: Extend `factor_audit_summary`.

It must aggregate by:

- `entry_family`
- `entry_family_conflict`
- `low_position_reclaim_type`
- `rank_bucket`
- `dynamic_market_regime`
- `market_warning_level`
- `fund_flow_state`
- `low_suction_days_bucket`
- `ma_convergence_bucket`
- `volume_bucket`
- `close_location_bucket`
- `launch_quality_bucket`
- `support_stop_context`

Each bucket row must include:

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
    "support_stop_like_ratio": 0.0,
}
```

- [x] Step 3: Add top-N and exclude-strong options.

Endpoint:

```text
GET /api/backtests/{backtest_id}/factor-audit?top_limit=100&exclude_strong_market=false
```

Rules:

- `top_limit=10` tests front-rank candidate quality.
- `top_limit=20` tests execution-pool quality.
- `top_limit=100` tests observation-pool quality.
- `exclude_strong_market=true` removes `strong_broad` and clearly strong-theme windows from candidate-outcome metrics.

- [x] Step 4: Add compact UI panel.

In `BacktestAnalysis.tsx`, display:

- Setup family buckets.
- Rank buckets.
- Market buckets.
- Low-suction days buckets.
- MA convergence buckets.
- Launch quality buckets.

Do not add a new main tab. Put this inside the existing backtest analysis area as "因子验证".

- [x] Step 5: Run tests and frontend build.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "factor_audit" -q
pnpm --dir frontend run build
```

Expected: pytest passes; Vite build passes. Existing chunk-size warnings are acceptable.

## Task 6: Build Buy/Sell Problem Attribution Matrix

**Purpose:** Decide whether losses come from bad buy points, bad sell points, portfolio capacity, or replacement quality.

**Files:**

- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [ ] Step 1: Add attribution classification helper.

Required categories:

```python
BUY_POINT_BAD = "buy_point_bad"
SELL_GIVEBACK = "sell_giveback"
SOLD_TOO_EARLY = "sold_too_early"
PORTFOLIO_CAPACITY_MISS = "portfolio_capacity_miss"
REPLACEMENT_BAD = "replacement_bad"
HEALTHY_TREND_WINNER = "healthy_trend_winner"
UNKNOWN = "unknown"
```

Classification rules:

- Candidate fixed 20d return `< -3%` and actual return `< 0`: `buy_point_bad`.
- Candidate fixed 20d return `> +5%` and actual return `< 0`: `sell_giveback`.
- Actual support stop followed by 10d rebound `>= +8%`: `sold_too_early`.
- Candidate fixed 20d return `> +5%`, no real order, and reason is full position/no rotation: `portfolio_capacity_miss`.
- Sell is followed by replacement trade return `< -3%`: `replacement_bad`.
- Actual return `> +10%` or MFE `> +15%`: `healthy_trend_winner`.

- [ ] Step 2: Add API endpoint or extend existing audit.

Prefer extending:

```text
GET /api/backtests/{backtest_id}/setup-market-exit-audit
```

Add:

```json
{
  "buy_sell_problem_matrix": {
    "by_problem": [],
    "by_setup_problem": [],
    "by_market_problem": [],
    "focused_symbols": []
  }
}
```

- [ ] Step 3: Add tests for matrix buckets.

Use synthetic rows to assert:

```python
assert matrix["by_problem"]["sell_giveback"]["sample_count"] == 1
assert matrix["by_problem"]["buy_point_bad"]["sample_count"] == 1
assert matrix["by_problem"]["portfolio_capacity_miss"]["sample_count"] == 1
```

- [ ] Step 4: Show matrix in backtest first screen.

UI copy should be direct:

- `买点问题`
- `卖点回撤问题`
- `卖早反弹`
- `满仓错过`
- `替换交易变差`
- `趋势赢家`

This is an explanation panel, not an operation.

## Task 7: Improve Unified Strategy Timeline For Stock Detail

**Purpose:** Let single-stock review show one coherent timeline: key buy candidate, buy rejection, actual buy, sell, and return.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/api/quant.ts`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [ ] Step 1: Add timeline merge tests.

Expected merged row:

```python
assert row["date"] == "2026-05-11"
assert row["vt_symbol"] == "603439.SSE"
assert row["candidate"]["action"] in {"BUY", "WATCH"}
assert row["plan"]["status"] in {"planned", "already_holding", "skipped"}
assert row["execution"]["status"] in {"filled", "planned_not_ordered", "rejected"}
assert "candidate" in row["markers"]
```

- [ ] Step 2: Collapse repeated buildup rows.

Rules:

- Consecutive low-suction buildup rows without launch become one `buildup_cluster`.
- First effective lift is the visible key buy candidate.
- Raw buildup evidence remains available in row details.
- WATCH rows are drawn as rejection/observation, not BUY.

- [ ] Step 3: Map K-line markers.

Visible markers:

- `BUY_SIGNAL`: executable key candidate, no actual fill yet.
- `BUY_REJECTED`: WATCH or planned but not filled.
- `BUY_FILLED`: actual portfolio buy.
- `SELL_FILLED`: actual portfolio sell.

Do not draw every low-suction buildup day as a BUY marker.

- [ ] Step 4: Keep UI simple.

Stock detail should have one strategy timeline source. It can have a small filter:

- `全部`
- `实际交易`
- `关键候选`

Do not restore separate "生成执行复盘" or manual single-stock strategy run buttons.

- [ ] Step 5: Run tests and build.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_timeline" -q
pnpm --dir frontend run build
```

Expected: pass.

## Task 8: Validate Focus Symbols With The New Tables

**Purpose:** Prove the new audit can explain the user-named stocks before any rule change.

**Files:**

- Create: `memory/06_backtests/YYYY-MM-DD_quant_strategy_feature_table_audit.md`
- No source edits unless a read-only audit field is missing.

- [ ] Step 1: Query baseline and focus symbols.

Use the selected product baseline from Task 1. Then query:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=603439.SSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002384.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002119.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=601179.SSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=600352.SSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002240.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002443.SZSE'
```

Use the actual ID returned by Task 1. Record the ID in the report; do not mix `#203/#194` and `#213` without explanation.

- [ ] Step 2: Required focus conclusions.

The report must answer:

- `603439.SSE`: whether `2026-05-11` is low-position buildup followed by launch, and whether the timeline marks the key lift instead of every buildup day.
- `002384.SZSE`: whether `2026-03-27..2026-04-08` and `2026-06-09..2026-06-12` are recognized as buildup plus key lift, and if not bought, whether the reason is rank/capacity/already-held.
- `002119.SZSE`: whether the loss is repeated dragon risk, sell issue, or bad replacement.
- `601179.SSE`: whether `2026-02-03` is early dragon and `2026-02-24/25` is later low-position reclaim.
- `600352.SSE`: whether `2026-03-10/12` is a false low-suction launch under weak/未回暖 market.
- `002240.SZSE`: whether `2026-03-13` was old persisted BUY but current normalized WATCH/risk, or still a true bad buy.
- `002443.SZSE`: whether `2026-05-14` is a good buy with sell/giveback problem.

- [ ] Step 3: Add global tables to the report.

Include:

- Factor audit top 10, top 20, top 100.
- Same audits with `exclude_strong_market=true`.
- Yearly split.
- Market-regime split.
- Buy/sell problem matrix.
- Top 20 missed candidates because of full positions.
- Replacement quality after support-stop sells.

- [ ] Step 4: State whether next work is buy-side or sell-side.

Use this exact decision format:

```text
结论：
- 买点问题占比：...
- 卖点/回撤问题占比：...
- 满仓/替换问题占比：...
- 当前不进入默认规则修改 / 可以进入某个默认关闭实验。
```

## Task 9: Default-Off Experiment Gate

**Purpose:** Only create trading-rule experiments after feature tables prove a narrow rule deserves testing.

**Files:**

- Modify only if Task 8 supports it:
  - `alphaagent/server/services/backtest/schemas.py`
  - `alphaagent/server/services/backtest/simulation.py`
  - `alphaagent/server/services/quant/strategies/dragon_pullback.py`
  - `tests/alphaagent/test_quant_backtest_portfolio.py`

- [ ] Step 1: Check promotion criteria.

A new default-off experiment is allowed only if all are true:

- Sample size at least `50` globally or at least `20` in a narrowly defined high-confidence bucket.
- Top 10 or top 20 candidate audit improves after excluding strong-market windows.
- Weak/false-bull/choppy markets do not degrade.
- Trend-winner opportunity cost is measured.
- Replacement quality is measured.
- Focus symbols are explained without special-casing them.
- No future-looking field is used in signal, score, rank, buy, sell, or position logic.

- [ ] Step 2: Add a default-false parameter.

Example shape:

```python
@dataclass(slots=True)
class BacktestParams:
    enable_contextual_support_stop_reclaim_review: bool = False
```

Rules:

- Default must preserve baseline exactly.
- Parameter name must describe the context, not a broad promise like `improve_low_suction`.
- Add it to product-baseline exclusion if it changes trades.

- [ ] Step 3: Add baseline-preservation test.

Expected:

```python
default_params = BacktestParams(start=date(2025, 3, 26), end=date(2026, 6, 18))
experiment_params = replace(default_params, enable_contextual_support_stop_reclaim_review=True)

assert default_params.enable_contextual_support_stop_reclaim_review is False
assert _is_product_baseline_params(default_params.__dict__) is True
assert _is_product_baseline_params(experiment_params.__dict__) is False
```

- [ ] Step 4: Run one full experiment and write evidence.

Required comparison:

- Baseline return and max drawdown.
- Experiment return and max drawdown.
- Buy/sell/open counts.
- Win rate and profit factor.
- Year split.
- Market-regime split.
- Top 10/20/100 candidate audit.
- Focus-symbol before/after.
- Removed profitable trades and added losing trades.
- Whether default should remain false.

If return drops materially or drawdown worsens, reject the experiment and record it in the ledger.

## Task 10: Verification Checklist

**Purpose:** Prevent future source changes from landing without evidence.

- [ ] Step 1: Run backend tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

Expected: all tests pass.

- [ ] Step 2: Run compile check.

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

Expected: no compile errors.

- [ ] Step 3: Run frontend build.

```bash
pnpm --dir frontend run build
```

Expected: build passes. Existing large chunk warning is acceptable.

- [ ] Step 4: Run whitespace check.

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] Step 5: Rebuild API only when endpoint code changed.

```bash
docker compose up -d --build alphaagent-api
```

Expected: API container healthy.

- [ ] Step 6: API smoke checks.

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=603439.SSE'
```

Expected: all return `status=ready`. Use the baseline ID selected by Task 1.

## Final Deliverables

The execution is complete only when these artifacts exist:

- A deterministic baseline selection result with explanation.
- Factor candidate and factor audit endpoints that are fast enough for UI use or internally cached.
- Stock detail timeline that shows key buy, rejection, actual buy, and sell markers without drawing every buildup day as BUY.
- A new evidence report under `memory/06_backtests/`.
- Updated `memory/06_backtests/strategy_optimization_ledger.md` if any new run or experiment is executed.
- A clear decision: no trade-rule change, or exactly one default-off experiment with evidence.

Do not create a new public strategy, new user operation, or default-on rule as part of this plan.
