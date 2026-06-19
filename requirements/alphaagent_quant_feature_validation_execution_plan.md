# AlphaAgent Quant Feature Validation Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is a follow-up execution slice for `requirements/alphaagent_quant_strategy_next_execution_plan.md`; do not change default trading behavior until the promotion gate in this plan is satisfied.

**Goal:** Build a feature-table validation pipeline that can explain whether future strategy changes improve收益、胜率、回撤 because of better买点、卖点、仓位容量、替换交易质量 or market-context filtering, instead of relying only on global backtest return.

**Architecture:** Keep one public strategy (`mainline_dragon_pullback`) and one simple user workflow. Internally create read-only feature/outcome/attribution tables, join them to real portfolio execution, aggregate by setup/market/rank/path buckets, and produce an evidence report before any default-off experiment is allowed.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, existing `backtest_*` and `quant_*` tables, React/TypeScript, pytest, Vite, evidence reports under `memory/06_backtests/`.

---

## 1. Current Baseline And Boundaries

### Current Baseline

- Product strategy: `mainline_dragon_pullback / 0.1.21`.
- Product baseline: `#203/#194`, range `2025-03-26..2026-06-18`, return about `+82.99%`, max drawdown about `-15.59%`, buy/sell/open `224 / 214 / 10`.
- Longer audit sample: `#213`, range `2024-05-28..2026-06-18`, not the product baseline unless the baseline policy explicitly says so.
- Candidate observation: top `100`, paged `20` per page.
- Portfolio execution: BUY candidates top `20`, max positions `10`.
- Historical execution model: `D` close-visible signal, `D+1` daily open execution (`legacy_next_open`).

### Non-Negotiable Rules

- Do not add a second public strategy.
- Do not force low-suction reserved slots.
- Do not restore historical `14:30` dependency.
- Do not use future-looking outcome labels in signal-day score, rank, buy, sell, rotation or position logic.
- Do not treat every low-suction buildup day as a BUY marker. Buildup is context; the visible key buy marker is the first effective lift/reclaim.
- Do not promote any trading rule unless it passes global, yearly, market-regime, rank-bucket, focus-symbol, no-future and replacement-quality checks.

## 2. Why This Plan Exists

Global return is necessary but not enough. A higher or lower backtest result can come from several different causes:

- The buy point is genuinely better or worse.
- The buy point is good, but the sell rule gives back profit.
- The strategy correctly found a candidate, but max position/capacity prevented execution.
- A sell rule frees a slot, but the replacement trade is worse.
- The result only works in a strong theme/bull window and fails after excluding strong-market periods.
- A low-suction signal and dragon-pullback signal overlap, and shared factors are double-counted or misinterpreted.

Therefore the next validation must compare feature tables before strategy rules are changed.

## 3. Feature Tables To Validate

These are logical tables. They can be implemented as cached JSON payloads in `backtest_factor_snapshots` / `backtest_factor_outcomes`, API-computed summaries, or later physical tables if performance requires it.

### 3.1 Candidate Feature Snapshot

One row per candidate/signal date, using only data visible at `trade_date`.

Required columns:

- Identity: `trade_date`, `vt_symbol`, `name`, `board`, `industry`, `concepts`.
- Setup: `entry_family`, `entry_family_label`, `low_position_reclaim_type`, `low_position_reclaim_label`, `entry_family_conflict`, `low_suction_dragon_state`.
- Action/rank: `persisted_action`, `entry_action`, `raw_entry_signal`, `executable_entry_signal`, `action_mismatch_resolved`, `total_score`, `rank`, `rank_bucket`.
- Score parts: `dragon_entry_score`, `low_reclaim_entry_score`, `shared_quality_score`, `risk_penalty`.
- Low-suction lifecycle: `low_suction_days`, `support_hold_days`, `low_suction_stage_label`, `low_suction_launch_quality_bucket`, `first_effective_lift`, `launch_confirmed`.
- MA/support: `ma_convergence_pct`, `ma5_distance_pct`, `ma10_distance_pct`, `ma20_distance_pct`, `ma30_distance_pct`, MA slopes if present.
- Volume/liquidity: `volume_ratio_5d_20d`, `turnover_percentile_60d`, `turnover`, `amount`, `liquidity_score`.
- Candle: `close_location_in_range`, `body_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `gap_up_pct`.
- Strength proxies: `recent_limit_up_20d`, `near_limit_up_count_20d`, `large_bull_count_20d`, `consecutive_bull_closes`, `persistent_volume_expansion`.
- Risk: `drawdown_from_pivot_pct`, `max_drawdown_60d`, `overhead_pressure_pct`, `high_level_sideways_distribution_risk`, `volume_stall_risk`, `key_support_break_risk`, `spiky_churn_risk`, `illiquid_forgotten_risk`, `weekly_top_fractal_risk`.
- Market: `dynamic_market_regime`, `market_warning_level`, `fund_flow_state`, `fund_flow_streak_days`, `recovery_state`, `dominant_theme`, `theme_strength`, `fund_flow_source`.
- Audit metadata: `as_of_date`, `feature_window_end`, `uses_future_for_label_only=false`, `not_used_for_signal_score=true`.

Validation questions:

- 哪些信号日可见特征对应更高胜率和更低 MAE？
- 低吸蓄势多久后才真正有胜率，而不是简单“越久越好”？
- 首个有效上拉是否比纯蓄势日明显更好？
- 龙回头和低吸重叠时，是增强信号还是冲突信号？

### 3.2 Fixed-Horizon Candidate Outcome

One row per candidate/signal date, independent from portfolio capacity.

Required columns:

- Execution assumption: `signal_date`, `execute_date`, `execute_open_price`.
- Returns: `return_3d`, `return_5d`, `return_10d`, `return_20d`.
- MFE/MAE: `mfe_3d`, `mfe_5d`, `mfe_10d`, `mfe_20d`, `mae_3d`, `mae_5d`, `mae_10d`, `mae_20d`.
- Thresholds: `hit_profit_5_pct`, `hit_profit_8_pct`, `hit_profit_10_pct`, `hit_loss_3_pct`, `hit_loss_5_pct`, `hit_loss_7_pct`, `first_hit`.
- Path labels: `failed_launch`, `support_stop_like`.
- Current strategy comparison: `current_strategy_entry_date`, `current_strategy_exit_date`, `current_strategy_return_pct`, `current_strategy_exit_reason` when a real trade exists.
- Audit metadata: `uses_future_for_label_only=true`, `not_used_for_signal_score=true`.

Validation questions:

- 固定 20 日为正但当前策略为负，优先看卖点/回撤问题。
- 固定 20 日为负且当前策略也为负，优先看买点/排序问题。
- 固定 20 日为正但没有买，优先看满仓、排名或换仓约束问题。

### 3.3 Real Portfolio Execution Attribution

One row per candidate after portfolio constraints.

Required columns:

- Candidate identity: `signal_date`, `execute_date`, `vt_symbol`, `rank`, `score`.
- Execution chain: `planned`, `ordered`, `filled`, `not_filled_reason`.
- Capacity: `position_count_before`, `execution_pool_rank`, `rotation_candidate`, `rotation_reason`.
- Real trade: `buy_price`, `sell_price`, `sell_reason`, `closed_return_pct`, `holding_days`.
- Replacement: `next_buy_vt_symbol`, `next_buy_date`, `replacement_return_pct`, `replacement_quality`.

Validation questions:

- 是否有大量 top20 高质量候选因为满仓错过？
- 卖出后释放的仓位是否买入更差交易？
- 当前最大持仓 10 是否是收益瓶颈，还是保护了回撤？

### 3.4 Market And Theme Context Snapshot

One row per candidate date or trade entry date.

Required columns:

- Broad market: `dynamic_market_regime`, `market_warning_level`, `index_trend_state`, `breadth_state`, `market_source`.
- Theme: `dominant_theme`, `theme_strength`, `theme_state`, `stock_theme_alignment`.
- Fund flow: `fund_flow_state`, `fund_flow_streak_days`, `fund_flow_source`, `fund_flow_coverage_label`.
- Recovery/risk: `recovery_state`, `risk_off_state`, `panic_outflow_state`.

Validation questions:

- 排除强势行情后，top10/top20 候选胜率是否仍成立？
- 科技窄牛、震荡轮动、弱市防守、快速杀跌里因子表现是否不同？
- 当前资金流历史不足时，系统是否明确显示 `资金流数据不足`，而不是伪造结论？

### 3.5 Low-Suction / Dragon Lifecycle Table

One row per symbol lifecycle segment, not one row per raw candidate only.

Required columns:

- `vt_symbol`, `cluster_start_date`, `cluster_end_date`, `key_signal_date`.
- `cluster_type`: `low_suction_buildup`, `first_effective_lift`, `dragon_pullback`, `dragon_low_suction_overlap`.
- `buildup_days`, `support_hold_days`, `ma_convergence_start`, `ma_convergence_end`.
- `first_effective_lift`, `launch_quality_bucket`, `launch_confirmed`.
- `key_signal_rank`, `key_signal_score`, `key_signal_action`.
- `cluster_outcome_20d`, `cluster_mfe_20d`, `cluster_mae_20d`.

Validation questions:

- 低吸蓄势应该作为簇证据，而不是每天画 BUY，这个簇是否能提升关键启动日解释力？
- 低吸和龙回头重叠时，应该由哪个 setup 主导？
- 从 MA30/MA20/MA10 等低位重新冲上 MA5 的动能，是否只是低位承接转强的一种 subtype？

### 3.6 Exit Path And Replacement Table

One row per closed trade.

Required columns:

- Entry: `entry_date`, `entry_family`, `entry_rank`, `entry_score`, `entry_market_context`.
- Path: `holding_days`, `mfe_pct`, `mae_pct`, `highest_profit_pct`, `giveback_from_peak_pct`.
- Exit: `exit_date`, `exit_reason`, `exit_return_pct`, `support_stop_context`.
- Rebound: `rebound_5d`, `rebound_10d`, `rebound_20d`, `sold_before_rebound`.
- Replacement: `replacement_symbol`, `replacement_return_pct`, `replacement_quality`.
- Classification: `trade_problem_type`.

Validation questions:

- `support_stop` 里到底是真失败启动、卖后反弹、浮盈回吐，还是有承接后破支撑？
- 高位浮盈后回撤是否需要动态卖点，而不是按买点高度卖出？
- 卖出是否释放仓位买入了更差标的？

## 4. Problem Classification Matrix

Every candidate or closed trade should be assigned to one primary problem bucket when possible.

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

Initial classification rules:

- Fixed 20d return `< -3%` and actual return `< 0`: `buy_point_bad`.
- Fixed 20d return `> +5%` and actual return `< 0`: `sell_giveback`.
- `support_stop` followed by 10d rebound `>= +8%`: `sold_too_early`.
- Fixed 20d return `> +5%`, no real order, and reason is full position/no rotation: `portfolio_capacity_miss`.
- Sell is followed by replacement trade return `< -3%`: `replacement_bad`.
- Actual return `> +10%` or MFE `> +15%`: `healthy_trend_winner`.
- Otherwise: `unknown`.

Output shape:

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

This belongs in `GET /api/backtests/{backtest_id}/setup-market-exit-audit`.

## 5. Execution Tasks

### Task 1: Complete Current Strategy Outcome Join

**Purpose:** Let fixed-horizon candidate outcomes compare against actual strategy trades.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add a helper to pair real BUY/SELL trades FIFO per symbol.

Required behavior:

- Use `backtest_trades` ordered by `trade_date`, `id`.
- Pair BUY and SELL chronologically for each `vt_symbol`.
- Prefer BUY raw field `execution.signal_date` when present to map a candidate `signal_date` to a real trade.
- Fall back to matching candidate signal date to the nearest BUY whose raw signal date or trade date is compatible with D+1 execution.

- [x] Step 2: Add fields to outcome payload.

Required fields:

```python
{
    "current_strategy_entry_date": "2026-05-15",
    "current_strategy_exit_date": "2026-06-04",
    "current_strategy_return_pct": -4.86,
    "current_strategy_exit_reason": "support_stop",
}
```

- [x] Step 3: Increment factor cache schema version.

If the cached outcome payload changes, increment `FACTOR_AUDIT_CACHE_SCHEMA_VERSION` so stale rows rebuild.

- [x] Step 4: Add tests.

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "fixed_horizon_outcome or current_strategy_return or factor_audit_cache" -q
```

Expected: pass.

### Task 2: Build Buy/Sell Problem Matrix

**Purpose:** Attribute return loss to buy-side, sell-side, capacity, replacement or unknown.

**Files:**

- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Implement classification helper.

The helper should accept a candidate/outcome/trade path row and return one category from Section 4.

- [x] Step 2: Extend `setup-market-exit-audit`.

Add `buy_sell_problem_matrix` to the existing endpoint. Do not create a new user operation.

- [x] Step 3: Add frontend display.

Show compact labels:

- `买点问题`
- `卖点回撤问题`
- `卖早反弹`
- `满仓错过`
- `替换交易变差`
- `趋势赢家`

- [x] Step 4: Run tests and build.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "setup_market_exit or buy_sell_problem" -q
pnpm --dir frontend run build
```

Expected: pass. Existing Vite chunk-size warning is acceptable.

### Task 3: Build Lifecycle Cluster Audit

**Purpose:** Validate low-suction buildup and first effective lift without drawing every buildup day as BUY.

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/api/quant.ts`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add cluster builder for strategy timeline.

Rules:

- Consecutive low-suction buildup rows without launch become one `buildup_cluster`.
- The first effective lift/reclaim is the visible `BUY_SIGNAL` candidate.
- WATCH rows are shown as `BUY_REJECTED` or observation, not BUY.
- Raw buildup rows stay available in detail payload.

- [x] Step 2: Map visible K-line markers.

Allowed visible markers:

- `BUY_SIGNAL`
- `BUY_REJECTED`
- `BUY_FILLED`
- `SELL_FILLED`

- [x] Step 3: Add tests for focus cases.

At minimum cover:

- `603439.SSE` around `2026-05-08..2026-05-11`.
- `002384.SZSE` around `2026-03-27..2026-04-08`.
- A repeated dragon-pullback row for `002119.SZSE`.

- [x] Step 4: Run tests and build.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_timeline or lifecycle_cluster" -q
pnpm --dir frontend run build
```

Expected: pass.

### Task 4: Produce Feature Bucket Evidence Report

**Purpose:** Make the next decision from data tables, not single-stock visual impressions.

**Files:**

- Create: `memory/06_backtests/YYYY-MM-DD_quant_feature_validation_report.md`
- Update only if a new run or experiment is executed: `memory/06_backtests/strategy_optimization_ledger.md`
- Update only if durable decision changes: `memory/09_decisions/decisions.md`

- [ ] Step 1: Resolve baseline ID from API.

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
```

Record the actual baseline ID and warning/reason in the report.

- [ ] Step 2: Query factor audits.

Run for top 10, 20 and 100:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=10'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=20'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=20&exclude_strong_market=true'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100&exclude_strong_market=true'
```

Report required buckets:

- Setup family.
- Low-position reclaim type.
- Rank bucket.
- Market regime.
- Market warning level.
- Fund-flow state.
- Low-suction days.
- MA convergence.
- Volume.
- Close location.
- Launch quality.
- Support-stop context.

- [ ] Step 3: Query problem matrix and path audit.

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/setup-market-exit-audit?lookahead_days=10'
```

Report:

- Problem category counts and return contribution.
- Support-stop context counts.
- Sold-before-rebound count.
- Replacement quality after sells.
- Trend-winner opportunity cost.

- [ ] Step 4: Query focus-symbol timelines.

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=603439.SSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002384.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002119.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=601179.SSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=600352.SSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002240.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002443.SZSE'
```

Report required conclusions:

- `603439.SSE`: whether `2026-05-11` is buildup followed by launch.
- `002384.SZSE`: whether `2026-03-27..2026-04-08` and `2026-06-09..2026-06-12` show buildup plus key lift, and why the portfolio did or did not buy.
- `002119.SZSE`: whether the loss is repeated dragon risk, sell issue, or bad replacement.
- `601179.SSE`: whether `2026-02-03` is early dragon and `2026-02-24/25` is later low-position reclaim.
- `600352.SSE`: whether `2026-03-10/12` is false low-suction launch under weak or not-recovered market.
- `002240.SZSE`: whether `2026-03-13` is old persisted BUY but current normalized WATCH/risk, or still a real bad buy.
- `002443.SZSE`: whether `2026-05-14` is a good buy with sell/giveback problem.

- [ ] Step 5: Write the report conclusion in this format.

```text
结论：
- 买点问题占比：...
- 卖点/回撤问题占比：...
- 满仓/替换问题占比：...
- 排除强势行情后 top10/top20 是否仍有效：...
- 当前不进入默认规则修改 / 可以进入某个默认关闭实验：...
```

### Task 5: Decide Whether A Default-Off Experiment Is Allowed

**Purpose:** Prevent another broad rule from reducing global return.

**Files:**

- Modify only if the evidence supports it:
  - `alphaagent/server/services/backtest/schemas.py`
  - `alphaagent/server/services/backtest/simulation.py`
  - `alphaagent/server/services/quant/strategies/dragon_pullback.py`
  - `tests/alphaagent/test_quant_backtest_portfolio.py`

- [ ] Step 1: Apply promotion criteria.

A default-off experiment is allowed only if all are true:

- Sample size at least `50` globally or at least `20` in a narrow high-confidence bucket.
- Top 10 or top 20 candidate audit improves after excluding strong-market windows.
- Weak/false-bull/choppy markets do not degrade.
- Trend-winner opportunity cost is measured.
- Replacement quality is measured.
- Focus symbols are explained without special-casing.
- No future-looking field is used in signal-day or sell-day decisions.

- [ ] Step 2: Choose only one narrow experiment.

Allowed experiment families, depending on evidence:

- Buy-side: narrow penalty for unconfirmed low-suction first lift under weak/not-recovered market and weak volume/close location.
- Sell-side: contextual support-stop modification only when rebound-prone features and no better replacement are visible.
- Giveback-side: peak-profit drawdown stop only for clean float-profit giveback, not for all winners.
- Capacity-side: rotation threshold adjustment only if top20 missed candidates consistently beat held positions and replacements.

Do not implement more than one experiment in the same iteration.

- [ ] Step 3: Add a default-false parameter.

Example:

```python
enable_contextual_support_stop_reclaim_review: bool = False
```

Rules:

- Default params must preserve current product baseline exactly.
- Product-baseline filter must exclude runs where the experiment flag is true.
- The parameter name must describe the narrow context, not a broad promise.

- [ ] Step 4: Run one full comparison and write evidence.

Required comparison:

- Baseline return and max drawdown.
- Experiment return and max drawdown.
- Buy/sell/open counts.
- Win rate and profit factor.
- Year split.
- Market-regime split.
- Top 10/20/100 candidate audit.
- Excluding-strong-market audit.
- Focus-symbol before/after.
- Removed profitable trades and added losing trades.
- Replacement quality after changed sells.
- Whether default remains false.

### Task 6: Final Verification

**Purpose:** Make the plan executable without leaving the product in an inconsistent state.

- [ ] Step 1: Backend tests.

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

- [ ] Step 2: Compile check.

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

- [ ] Step 3: Frontend build.

```bash
pnpm --dir frontend run build
```

- [ ] Step 4: Diff whitespace check.

```bash
git diff --check
```

- [ ] Step 5: Docker API rebuild when backend endpoint code changed.

```bash
docker compose up -d --build alphaagent-api
```

- [ ] Step 6: Runtime API smoke checks.

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100&exclude_strong_market=true'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/setup-market-exit-audit?lookahead_days=10'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002384.SZSE'
```

Expected:

- All endpoints return `status=ready` or a clear documented empty state.
- Baseline is `#203/#194` unless a newer explicit current-product baseline exists.
- Factor rows preserve `not_used_for_signal_score=true`.
- Outcome rows preserve `uses_future_for_label_only=true`.

## 6. Acceptance Criteria

This plan is complete only when all are true:

- Every top candidate can be explained by signal-day features, fixed-horizon outcome and real portfolio execution status.
- Buy/sell/capacity/replacement problem matrix is visible in backtest analysis.
- Stock detail uses one unified timeline and no longer shows every low-suction buildup day as BUY.
- Focus-symbol report exists under `memory/06_backtests/`.
- Any proposed strategy change is default-off and backed by the feature-table report.
- If evidence is weak, the documented decision is "do not change default trading rules."

## 7. Expected Decision After Execution

The likely next decision is not known in advance. The report must choose one:

- **No rule change:** feature tables show weak, unstable, small-sample or strong-market-only evidence.
- **Buy-side default-off experiment:** false launches are visible before entry and avoiding them does not remove trend winners.
- **Sell-side default-off experiment:** fixed-horizon outcomes are good but current strategy exits badly, and replacement quality supports holding or delaying exit.
- **Capacity/rotation experiment:** missed top20 candidates consistently beat held positions and replacement quality is positive.

Until one of those is proven, the product remains `mainline_dragon_pullback / 0.1.21` with read-only diagnostics.
