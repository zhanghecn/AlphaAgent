# AlphaAgent Quant Feature Drilldown Next Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This is a follow-up plan after `requirements/alphaagent_quant_feature_validation_execution_plan.md`; do not change default trading behavior until the promotion gate in this plan is satisfied.

**Goal:** 用全局回测之外的细粒度特征表，判断策略优化到底提升了买点、卖点、回撤、仓位替换、弱市适应性还是只吃到了科技窄牛样本。

**Architecture:** 保持一个公开策略和简单 UI，内部增加只读特征快照、固定持有后验、真实组合归因、市场/主线画像、低吸/龙回头生命周期和替换质量矩阵。所有后验字段只用于审计报告，不能进入信号日评分、排序、买卖、卖点或仓位逻辑。

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, existing `backtest_*` / `quant_*` tables, React/TypeScript, pytest, Vite, evidence reports under `memory/06_backtests/`.

---

## 1. 当前基线和边界

### 当前产品基线

- 公开策略：`mainline_dragon_pullback / 0.1.21`。
- 产品基线：`#203/#194`，区间 `2025-03-26..2026-06-18`。
- 当前结果：收益约 `+82.99%`，最大回撤约 `-15.59%`，买入/卖出/持仓中约 `224 / 214 / 10`。
- 候选观察：默认前 `100`，分页每页 `20`。
- 组合执行：只执行 BUY 候选前 `20`，最大持仓 `10`。
- 历史执行：`legacy_next_open`，即 D 日收盘生成信号，D+1 日线开盘撮合买卖。
- 历史默认流程不再依赖 `14:30` 分钟数据；尾盘实时缓存是独立能力。

### 不可违反的规则

- 不新增第二个公开策略。
- 不强行给低吸保留名额。
- 不把低吸蓄势每一天都画成 BUY。
- 不用后验收益、MFE、MAE、卖后反弹、当前策略结果参与信号日评分、排序、买卖或卖点。
- 不因为单只股票肉眼很好就直接修改默认规则。
- 不先改规则再找理由；必须先出特征报告，再决定是否允许默认关闭实验。
- 不把资金流缺失解释成资金正常；历史资金流不足时必须显示 `资金流数据不足`。

## 2. 这次要解决的问题

用户关心的核心不是“全局回测收益是多少”，而是：

- 买点是否真的更准，还是只是强势行情把错误买点也带起来了？
- 低吸洗盘和龙回头到底是两套因子、共用哪些因子、冲突时谁主导？
- 低吸蓄势很久后，第一个有效上拉是否才是关键 BUY，而不是蓄势期每天 BUY？
- 卖点是否因为按买点位置或支撑位卖，导致有浮盈后回吐到亏损？
- 破位连续下跌的亏损是买点错、卖点慢、还是大盘/主线退潮？
- 满仓时错过的 top20 候选是否比真实持仓更好？
- 卖出释放仓位后买入的替换交易是否更差？
- 排除科技窄牛、强势市场后，前 10 / 前 20 候选胜率是否仍成立？
- 如果科技跌是主线龙回头，动态大盘算法会不会误伤后续启动？
- 如果市场突然切到震荡轮动、非科技低吸、熊市少数独立强票，策略能否识别？

## 3. 最终要产出的特征表

这些表可以先作为 API 聚合 JSON 和 Markdown 报告，不急着新建物理表。只有性能超过阈值时才把结果写入 `backtest_factor_snapshots` / `backtest_factor_outcomes` 或新增内部缓存表。

### 3.1 候选信号日特征表

一行代表一个候选在信号日可见的信息，只能使用 `trade_date` 当天及以前的数据。

必备字段：

- 身份：`trade_date`, `vt_symbol`, `name`, `board`, `industry`, `concepts`。
- 动作：`persisted_action`, `entry_action`, `raw_entry_signal`, `executable_entry_signal`, `action_mismatch_resolved`。
- 排名：`total_score`, `rank`, `rank_bucket`, `execution_pool_rank`。
- 入场家族：`entry_family`, `entry_family_label`, `low_position_reclaim_type`, `low_suction_dragon_state`, `entry_family_conflict`。
- 评分拆解：`dragon_entry_score`, `low_reclaim_entry_score`, `shared_quality_score`, `risk_penalty`, `market_context_penalty`。
- 低吸生命周期：`low_suction_days`, `support_hold_days`, `low_suction_stage_label`, `first_effective_lift`, `launch_confirmed`, `low_suction_launch_quality_bucket`。
- 均线和支撑：`ma_convergence_pct`, `ma5_distance_pct`, `ma10_distance_pct`, `ma20_distance_pct`, `ma30_distance_pct`, `ma5_slope_pct`, `ma10_slope_pct`, `ma20_slope_pct`, `ma30_slope_pct`, `support_price`, `support_distance_pct`。
- 量能和流动性：`volume_ratio_5d_20d`, `turnover_percentile_60d`, `turnover`, `amount`, `liquidity_score`, `persistent_volume_expansion`。
- K 线：`close_location_in_range`, `body_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `gap_up_pct`, `intraday_range_pct`。
- 涨停/强势代理：`recent_limit_up_20d`, `near_limit_up_count_20d`, `large_bull_count_20d`, `consecutive_bull_closes`。
- 风险：`drawdown_from_pivot_pct`, `max_drawdown_60d`, `overhead_pressure_pct`, `high_level_sideways_distribution_risk`, `volume_stall_risk`, `key_support_break_risk`, `spiky_churn_risk`, `illiquid_forgotten_risk`, `weekly_top_fractal_risk`。
- 市场/主线：`dynamic_market_regime`, `market_warning_level`, `market_recovery_level`, `fund_flow_state`, `fund_flow_streak_days`, `fund_flow_coverage_label`, `dominant_theme`, `theme_strength`, `stock_theme_alignment`。
- 审计元数据：`feature_window_end`, `uses_future_for_label_only=false`, `not_used_for_signal_score=true`。

要回答的问题：

- 哪些信号日可见特征对应更高胜率、更高 MFE、更低 MAE？
- 低吸蓄势天数在什么区间有效，是否存在“蓄势太久反而弱”？
- `first_effective_lift=true` 是否明显优于纯蓄势观察日？
- `dragon_pullback` 和 `low_position_reclaim` 重叠时，是增强还是冲突？

### 3.2 固定持有后验表

一行代表一个候选按统一口径买入后的后验路径，独立于组合满仓和换仓。

必备字段：

- 执行假设：`signal_date`, `execute_date`, `execute_open_price`。
- 收益：`return_3d`, `return_5d`, `return_10d`, `return_20d`。
- 浮盈：`mfe_3d`, `mfe_5d`, `mfe_10d`, `mfe_20d`。
- 浮亏：`mae_3d`, `mae_5d`, `mae_10d`, `mae_20d`。
- 阈值：`hit_profit_5_pct`, `hit_profit_8_pct`, `hit_profit_10_pct`, `hit_loss_3_pct`, `hit_loss_5_pct`, `hit_loss_7_pct`, `first_hit`。
- 路径标签：`failed_launch`, `support_stop_like`, `first_5pct_profit_date`, `first_5pct_loss_date`。
- 当前策略对照：`current_strategy_entry_date`, `current_strategy_exit_date`, `current_strategy_return_pct`, `current_strategy_exit_reason`。
- 审计元数据：`uses_future_for_label_only=true`, `not_used_for_signal_score=true`。

要回答的问题：

- 固定 20 日收益为正但当前策略亏损，优先归因卖点/回撤/替换。
- 固定 20 日收益为负且当前策略亏损，优先归因买点/假启动/弱市。
- 固定 20 日收益为正但组合没买，优先归因满仓、排名、换仓阈值。

### 3.3 真实组合执行归因表

一行代表候选进入组合约束后的真实命运。

必备字段：

- 候选：`signal_date`, `execute_date`, `vt_symbol`, `rank`, `score`, `entry_family`。
- 计划链路：`planned`, `ordered`, `filled`, `not_filled_reason`。
- 仓位：`position_count_before`, `max_positions`, `execution_pool_rank`, `held_symbols_before`。
- 换仓：`rotation_candidate`, `rotation_reason`, `rotation_score_gap`, `replaced_symbol`。
- 真实交易：`buy_price`, `sell_price`, `sell_reason`, `closed_return_pct`, `holding_days`。
- 错过候选后验：`missed_return_10d`, `missed_return_20d`, `missed_mfe_20d`, `missed_mae_20d`。

要回答的问题：

- 前 20 里有多少高质量候选因为满仓错过？
- 错过候选是否明显强于当时持仓？
- 当前最大持仓 10 是收益瓶颈，还是回撤保护？

### 3.4 卖点路径和替换质量表

一行代表一笔闭合交易。

必备字段：

- 入场：`entry_date`, `entry_family`, `entry_rank`, `entry_score`, `entry_market_context`。
- 路径：`holding_days`, `mfe_pct`, `mae_pct`, `highest_profit_pct`, `giveback_from_peak_pct`。
- 卖点：`exit_date`, `exit_reason`, `exit_return_pct`, `support_stop_context`。
- 卖后：`rebound_5d`, `rebound_10d`, `rebound_20d`, `sold_before_rebound`。
- 替换：`next_buy_vt_symbol`, `next_buy_date`, `replacement_return_pct`, `replacement_quality`。
- 归因：`trade_problem_type`，取值为 `buy_point_bad`, `sell_giveback`, `sold_too_early`, `portfolio_capacity_miss`, `replacement_bad`, `healthy_trend_winner`, `unknown`。

要回答的问题：

- `support_stop` 里到底是真失败启动、卖后反弹、浮盈回吐，还是有承接后破支撑？
- 高位浮盈后回撤多少才是出货风险，而不是正常龙回头？
- 卖出后释放的仓位是否买入了更差交易？

### 3.5 市场/主线动态画像表

一行代表一个交易日，也可 join 到候选日或买入日。

输入字段：

- 指数趋势：核心指数 `5d/10d/20d/60d` 收益、MA 斜率、距离 20 日高点回撤。
- 全市场宽度：上涨家数占比、强于 MA5/MA10/MA20/MA60 占比、涨停/跌停家数。
- 波动和恐慌：跌停扩散、长阴数量、连续风险日、风险释放后反弹天数。
- 板块主线：板块涨幅集中度、龙头板块持续天数、板块资金流入/流出、股票与主线板块对齐。
- 资金流覆盖：`fund_flow_source`, `fund_flow_start_date`, `fund_flow_end_date`, `fund_flow_coverage_label`。

输出字段：

- `dynamic_market_regime`: `strong_broad`, `narrow_mainline_bull`, `mainline_pullback`, `choppy_rotation`, `weak_rebound`, `risk_off`, `false_bull`, `unknown`。
- `market_warning_level`: `0..4`，0 正常，4 退潮/恐慌。
- `market_recovery_level`: `0..4`，0 未回暖，4 明确修复。
- `fund_flow_state`: `inflow`, `recovery`, `outflow`, `panic_outflow`, `insufficient_data`。
- `dominant_theme`, `theme_strength`, `stock_theme_alignment`。

要回答的问题：

- 科技主线回踩时是否应降低全市场风险处罚，避免误伤龙回头？
- 科技退潮但非科技轮动低吸变强时，是否能通过主线切换识别？
- 熊市里少数独立强票是否还保留候选强度，还是被市场过滤过度压制？
- 排除强势市场后，前 10 / 前 20 候选胜率是否仍成立？

### 3.6 低吸/龙回头生命周期表

一行代表一个生命周期段，不是一堆逐日 BUY。

必备字段：

- `vt_symbol`, `cluster_start_date`, `cluster_end_date`, `key_signal_date`。
- `cluster_type`: `low_suction_buildup`, `first_effective_lift`, `dragon_pullback`, `dragon_low_suction_overlap`。
- `buildup_days`, `support_hold_days`, `ma_convergence_start`, `ma_convergence_end`。
- `first_effective_lift`, `launch_quality_bucket`, `launch_confirmed`。
- `key_signal_rank`, `key_signal_score`, `key_signal_action`。
- `cluster_return_10d`, `cluster_return_20d`, `cluster_mfe_20d`, `cluster_mae_20d`。

要回答的问题：

- 低吸蓄势是否应该持续加证据，但只在首个有效上拉时给关键 BUY？
- 从 MA30/MA20/MA10 低位重新冲上 MA5 的动能，是否是 `low_position_reclaim` 的 subtype？
- 龙回头和低吸重叠时，是否由 `low_position_reclaim` 主导解释，还是仍是经典龙回头？

### 3.7 因子交互和机会成本表

一行代表一个因子组合或一次规则变化的机会成本。

必备字段：

- `factor_group`, `factor_value`, `sample_count`, `win_rate`, `avg_return_20d`, `median_return_20d`, `profit_factor_proxy`。
- `mfe_8pct_hit_ratio`, `mae_5pct_hit_ratio`, `failed_launch_ratio`, `support_stop_like_ratio`。
- `removed_winner_count`, `removed_winner_return_sum`, `avoided_loser_count`, `avoided_loser_return_sum`。
- `added_loser_count`, `added_loser_return_sum`, `replacement_quality_delta`。

要回答的问题：

- 某个扣分/过滤因子到底是减少亏损，还是误杀趋势大肉？
- 某个低吸加分因子到底提高胜率，还是只把更多低质量票推到前 20？
- 动态大盘过滤收益来自避险，还是来自换入了更差替代品？

## 4. 执行任务

### Task 0: 冻结基线和证据入口

**目的：** 每次后续执行前先确认比较对象，避免 `#213`、短区间实验或局部缓存 run 顶掉产品基线。

**Files:**

- Read: `memory/06_backtests/README.md`
- Read: `memory/06_backtests/strategy_optimization_ledger.md`
- Read: `memory/09_decisions/decisions.md`
- Update only if facts change: `memory/06_backtests/README.md`

- [x] Step 1: 检查工作区。

Run:

```bash
git status --short
```

Expected:

- 记录当前已有 dirty files。
- 不 revert、不 reset、不 checkout 用户或前序改动。

- [x] Step 2: 确认产品基线。

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5' \
  | jq '.items[] | {id, strategy_version, start_date, end_date, total_return_pct, max_drawdown_pct, baseline_reason, baseline_warning}'
```

Expected:

- 返回 `#203/#194` 或带明确解释的当前产品基线。
- 不返回 `#195/#196/#197/#198/#199/#200/#201/#207/#208/#211` 等研究开关实验。

- [x] Step 3: 把基线写入本轮报告开头。

Report header must include:

```text
基线：#203/#194
策略：mainline_dragon_pullback / 0.1.21
区间：2025-03-26..2026-06-18
执行：legacy_next_open
收益：+82.99%
最大回撤：-15.59%
买入/卖出/持仓中：224 / 214 / 10
```

### Task 1: 生成候选信号日特征矩阵

**目的：** 先证明哪些信号日可见特征有效，再讨论是否改分数。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 为候选特征加测试。

Add or extend tests to assert:

```python
def test_factor_candidate_snapshot_marks_audit_only_fields_without_future_labels():
    row = build_factor_candidate_snapshot(sample_candidate_row())

    assert row["uses_future_for_label_only"] is False
    assert row["not_used_for_signal_score"] is True
    assert "return_20d" not in row
    assert "mfe_20d" not in row
    assert row["entry_family"] in {"dragon_pullback", "low_position_reclaim", "unknown"}
```

- [x] Step 2: 扩展 `factor-candidates` payload。

Required output groups:

- `identity`
- `action_rank`
- `setup_family`
- `score_parts`
- `low_suction_lifecycle`
- `ma_support`
- `volume_liquidity`
- `candle`
- `strength_proxy`
- `risk_flags`
- `market_context`
- `audit_metadata`

- [x] Step 3: 验证前 100 候选。

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-candidates?limit=100' \
  > /tmp/alphaagent_factor_candidates_top100.json
```

Expected:

- `items` 至少包含 `rank <= 100` 的候选。
- 每行都带 `not_used_for_signal_score=true`。
- 每行都没有后验收益字段。

### Task 2: 补固定持有后验和当前策略对照

**目的：** 判断候选本身好不好，和真实策略为什么没赚到钱。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 为固定持有后验加测试。

Required assertions:

```python
def test_fixed_horizon_outcome_is_label_only_and_uses_next_open():
    outcome = build_fixed_horizon_outcome(sample_bars(), signal_date=date(2026, 4, 1))

    assert outcome["execute_date"] == "2026-04-02"
    assert "return_20d" in outcome
    assert outcome["uses_future_for_label_only"] is True
    assert outcome["not_used_for_signal_score"] is True
```

- [x] Step 2: join 当前策略真实交易 outcome。

Required fields:

```json
{
  "current_strategy_entry_date": "2026-05-14",
  "current_strategy_exit_date": "2026-06-04",
  "current_strategy_return_pct": -4.86,
  "current_strategy_exit_reason": "support_stop"
}
```

- [x] Step 3: 运行 API。

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100' \
  > /tmp/alphaagent_factor_audit_top100.json
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100&exclude_strong_market=true' \
  > /tmp/alphaagent_factor_audit_top100_exstrong.json
```

Expected:

- summary 里有 top100 固定持有胜率。
- 排除强势市场后有单独样本数和胜率。
- current-strategy comparison 只出现在 outcome/audit 区域。

### Task 3: 补真实组合执行归因和错过候选表

**目的：** 回答“有信号为什么没买”“不该买为什么买了”“前 20 错过是否更好”。

**Files:**

- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 增加 missed top20 attribution。

Required buckets:

- `filled`
- `already_holding`
- `full_position_no_rotation`
- `score_gap_not_enough`
- `limit_up_open_blocked`
- `no_execute_bar`
- `lower_than_execution_pool`

- [x] Step 2: 输出 `top20_missed_quality`。

Output shape:

```json
{
  "top20_missed_quality": {
    "missed_count": 0,
    "missed_positive_20d_count": 0,
    "missed_avg_return_20d": 0.0,
    "missed_avg_mfe_20d": 0.0,
    "missed_avg_mae_20d": 0.0,
    "by_reason": []
  }
}
```

- [x] Step 3: 验证重点票。

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/candidate-trace?vt_symbol=002384.SZSE&signal_date=2026-04-01'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/candidate-trace?vt_symbol=601179.SSE&signal_date=2026-02-25'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/candidate-trace?vt_symbol=603439.SSE&signal_date=2026-05-11'
```

Expected:

- 能解释当日是否有候选。
- 能解释是否进入执行前 20。
- 能解释没买原因，不用猜。

### Task 4: 补卖点路径、浮盈回撤和替换质量矩阵

**目的：** 判断收益降低到底是买点错，还是卖点/回撤/替换错。

**Files:**

- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 扩展 closed-trade path rows。

Required fields:

- `mfe_pct`
- `mae_pct`
- `highest_profit_pct`
- `giveback_from_peak_pct`
- `support_stop_context`
- `rebound_5d`
- `rebound_10d`
- `rebound_20d`
- `replacement_return_pct`
- `replacement_quality`
- `trade_problem_type`

- [x] Step 2: 分类问题矩阵。

Classification rules:

```python
BUY_POINT_BAD = "buy_point_bad"
SELL_GIVEBACK = "sell_giveback"
SOLD_TOO_EARLY = "sold_too_early"
PORTFOLIO_CAPACITY_MISS = "portfolio_capacity_miss"
REPLACEMENT_BAD = "replacement_bad"
HEALTHY_TREND_WINNER = "healthy_trend_winner"
UNKNOWN = "unknown"
```

Initial rule order:

- fixed 20d `< -3%` and actual return `< 0`: `buy_point_bad`
- fixed 20d `> +5%` and actual return `< 0`: `sell_giveback`
- support stop followed by 10d rebound `>= +8%`: `sold_too_early`
- fixed 20d `> +5%`, no order, full position/no rotation: `portfolio_capacity_miss`
- replacement trade return `< -3%`: `replacement_bad`
- actual return `> +10%` or MFE `> +15%`: `healthy_trend_winner`
- otherwise: `unknown`

- [x] Step 3: 重点检查 `002443.SZSE`。

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002443.SZSE'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/setup-market-exit-audit?lookahead_days=10'
```

Expected:

- `2026-05-14` 买入路径能显示 MFE、最高浮盈回撤和 `support_stop_context`。
- 如果是卖点问题，报告必须归到 `sell_giveback` 或相关 support-stop 子类，而不是归咎于买点。

### Task 5: 补动态大盘/主线画像审计

**目的：** 让策略可以解释科技窄牛、主线回踩、震荡轮动、弱市和熊市，而不是固定用一个市场标签。

**Files:**

- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/market/*` only if existing market context helpers live there.
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 定义动态市场状态函数。

Required signature:

```python
def classify_dynamic_market_context(
    *,
    index_trend: dict[str, float | str | None],
    breadth: dict[str, float | int | None],
    sector_flow: dict[str, float | str | None],
    stock_theme_alignment: str | None,
) -> dict[str, object]:
    ...
```

Required output:

```json
{
  "dynamic_market_regime": "mainline_pullback",
  "market_warning_level": 2,
  "market_recovery_level": 1,
  "fund_flow_state": "insufficient_data",
  "dominant_theme": "technology",
  "theme_strength": "strong",
  "stock_theme_alignment": "aligned",
  "explain": ["指数回踩", "主线仍强", "资金流历史不足"]
}
```

- [x] Step 2: 分桶不能直接改变策略。

Tests must assert:

```python
def test_market_context_is_audit_only_for_factor_rows():
    row = build_factor_candidate_snapshot(sample_candidate_row_with_market_context())

    assert row["market_context"]["not_used_for_signal_score"] is True
    assert row["score_parts"]["total_score_after_market_context"] == row["total_score"]
```

- [x] Step 3: 生成市场分层报告。

Required buckets:

- `strong_broad`
- `narrow_mainline_bull`
- `mainline_pullback`
- `choppy_rotation`
- `weak_rebound`
- `risk_off`
- `false_bull`
- `unknown`

Metrics:

- 候选固定 20 日胜率。
- 真实组合闭仓胜率。
- 平均 MFE / MAE。
- `support_stop` 比例。
- 前 10 / 前 20 / 前 100 对比。
- 排除强势行情后的结果。

### Task 6: 补低吸/龙回头生命周期和显示语义

**目的：** 把低吸蓄势和关键启动点分开，避免 K 线密集 BUY，也避免低吸和龙回头互相抢解释。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/api/quant.ts`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 生命周期聚合。

Rules:

- 连续 `low_suction_stage=buildup` 且未启动的行聚成一个 `buildup_cluster`。
- `buildup_cluster` 可显示为观察/买拒，不显示为 BUY。
- 首个 `first_effective_lift=true` 且 `executable_entry_signal=true` 的行显示 `BUY_SIGNAL`。
- 真实组合成交显示 `BUY_FILLED`。
- 真实卖出显示 `SELL_FILLED`。

- [x] Step 2: 输出 lifecycle summary。

Output shape:

```json
{
  "lifecycle_segments": [
    {
      "vt_symbol": "002384.SZSE",
      "cluster_start_date": "2026-03-27",
      "cluster_end_date": "2026-04-07",
      "key_signal_date": "2026-04-08",
      "cluster_type": "low_suction_buildup",
      "buildup_days": 6,
      "key_signal_action": "BUY",
      "cluster_return_20d": 0.0
    }
  ]
}
```

- [x] Step 3: 重点股票回归。

Must inspect:

- `002384.SZSE`: `2026-03-27..2026-04-08`
- `603439.SSE`: `2026-05-08..2026-05-11`
- `601179.SSE`: `2026-02-03` vs `2026-02-24/25`
- `600352.SSE`: `2026-03-10..2026-03-12`
- `002240.SZSE`: `2026-03-13`
- `002119.SZSE`: repeated dragon risk
- `002443.SZSE`: sell/giveback sample

### Task 7: 生成细粒度特征校验报告

**目的：** 每次策略优化前都有统一证据，不再只看全局回测。

**Files:**

- Create: `memory/06_backtests/YYYY-MM-DD_quant_feature_drilldown_report.md`
- Update: `memory/06_backtests/README.md`
- Update only if a real experiment/backtest is run: `memory/06_backtests/strategy_optimization_ledger.md`
- Update only if durable decision changes: `memory/09_decisions/decisions.md`

- [x] Step 1: 报告必须包含基线。

Required fields:

- baseline id
- strategy/version
- date range
- execution model
- return
- max drawdown
- buy/sell/open
- data coverage warnings

- [x] Step 2: 报告必须包含特征分桶。

Required sections:

- setup family
- low-position reclaim type
- low-suction days
- launch quality
- MA convergence
- volume/liquidity
- close location
- risk flags
- dynamic market regime
- fund-flow coverage
- rank bucket

- [x] Step 3: 报告必须包含真实组合归因。

Required sections:

- buy/sell problem matrix
- support-stop context
- top20 missed candidates
- replacement quality
- trend-winner opportunity cost
- focus-symbol conclusions

- [x] Step 4: 报告结论格式。

Use this exact structure:

```text
结论：
- 买点问题占比：...
- 卖点/回撤问题占比：...
- 满仓/替换问题占比：...
- 低吸首个有效上拉是否优于纯蓄势：...
- 龙回头/低吸重叠是否增强或冲突：...
- 排除强势行情后 top10/top20 是否仍有效：...
- 大盘/主线画像是否足以进入动态规则：...
- 当前不进入默认规则修改 / 可以进入某个默认关闭实验：...
```

### Task 8: 前端展示整合

**目的：** 用户界面保持简单，复杂性留在内部特征表和解释字段。

**Files:**

- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Modify: `frontend/src/features/quant/BacktestPanel.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/api/quant.ts`

- [x] Step 1: `/quant` 不新增主按钮。

Visible flow:

- 候选观察：前 100，分页 20。
- 回测结果：默认显示收益、回撤、年度分段、市场分段、前 10/20 审计。
- 高级证据折叠显示：问题归因、替换质量、排除强势行情。

- [x] Step 2: 股票详情只保留一个时间线。

Timeline modes:

- `真实成交`: BUY_FILLED / SELL_FILLED / rejected execution。
- `理论信号`: BUY_SIGNAL / BUY_REJECTED / buildup observation。

Rules:

- 默认显示真实成交并叠加关键理论信号。
- 不显示低吸蓄势每日 BUY。
- 每个标记点击后显示分数、低吸阶段、龙回头/低吸状态、没买原因或卖出原因。

- [x] Step 3: 候选评分解释。

Candidate row must show:

- 总分。
- 入场家族。
- 低吸阶段。
- 启动质量。
- 风险扣分。
- 大盘/资金流标记。
- 为什么买 / 为什么拒买 / 为什么没买。

### Task 9: 默认关闭实验晋升门槛

**目的：** 防止再出现直觉规则降低全局收益。

**Files:**

- Modify only after gate passes:
  - `alphaagent/server/services/backtest/schemas.py`
  - `alphaagent/server/services/backtest/simulation.py`
  - `alphaagent/server/services/quant/strategies/dragon_pullback.py`
  - `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 检查晋升条件。

A default-off experiment is allowed only if all are true:

- 全局样本至少 `50`，或窄桶样本至少 `20`。
- 排除强势行情后 top10/top20 胜率不下降。
- 至少两个市场桶不恶化。
- 至少一个弱市/震荡/主线回踩桶改善。
- 趋势大肉机会成本已量化。
- 卖出后替换质量已量化。
- 重点股票能解释，但没有对股票代码特判。
- 规则只使用信号日或卖出日可见字段。

- [x] Step 2: 一次只允许一个实验。

Allowed experiment families:

- 买点侧：只对“低吸蓄势未确认 + 弱启动 + 未回暖市场 + 量能/收盘异常”的窄桶做降权或观察。
- 卖点侧：只对“止损后高概率反弹 + 没有更好替换候选”的窄桶做延迟确认。
- 回撤侧：只对“已有浮盈后高位收益处突然回撤 + 主线/资金转弱”的窄桶做浮盈保护。
- 仓位侧：只在 top20 missed candidates 明显优于持仓时调整换仓阈值。

- [x] Step 3: 默认参数必须保持关闭。

Example:

```python
enable_contextual_support_stop_reclaim_review: bool = False
```

Required:

- 默认参数完全复现 `#203/#194`。
- `baseline_only=true` 排除实验参数为 true 的回测。
- 参数名描述窄场景，不能叫 `enable_better_sell` 这类泛化名字。

- [x] Step 4: 实验报告必须包含机会成本。

Required comparison:

- baseline vs experiment return / max drawdown。
- buy/sell/open count。
- win rate / profit factor。
- yearly split。
- market-regime split。
- top10/top20/top100 candidate audit。
- excluding strong market audit。
- focus-symbol before/after。
- removed winners and avoided losers。
- added losers and replacement quality。
- default remains false / allowed to promote。

### Task 10: 最终验证命令

**目的：** 每次执行完该计划的一部分，都能确认产品没有进入不一致状态。

- [x] Step 1: 后端测试。

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

- [x] Step 2: 编译检查。

Run:

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

- [x] Step 3: 前端构建。

Run:

```bash
pnpm --dir frontend run build
```

- [x] Step 4: diff whitespace check。

Run:

```bash
git diff --check
```

- [x] Step 5: Docker API 冒烟。

Run:

```bash
docker compose up -d --build alphaagent-api
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/factor-audit?top_limit=100&exclude_strong_market=true'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/setup-market-exit-audit?lookahead_days=10'
curl -sS 'http://localhost:8000/api/backtests/{BASELINE_ID}/strategy-timeline?vt_symbol=002384.SZSE'
```

Expected:

- API 都返回 ready。
- baseline 不漂移。
- `factor-audit` 有 top100 和排除强势版本。
- `setup-market-exit-audit` 有 `buy_sell_problem_matrix`。
- `strategy-timeline` 有 `display_markers` 和低吸簇信息。

## 5. 第一轮执行优先级

按这个顺序执行，不能跳过报告直接改策略：

1. Task 0：冻结产品基线。
2. Task 1：候选信号日特征矩阵。
3. Task 2：固定持有后验和当前策略对照。
4. Task 3：真实组合执行归因和错过候选。
5. Task 4：卖点路径、浮盈回撤和替换质量。
6. Task 5：动态大盘/主线画像。
7. Task 6：低吸/龙回头生命周期显示语义。
8. Task 7：生成 `memory/06_backtests/YYYY-MM-DD_quant_feature_drilldown_report.md`。
9. Task 8：把报告摘要以简单方式接入 `/quant` 和股票详情。
10. Task 9：只有报告通过晋升门槛，才进入默认关闭实验。
11. Task 10：最终验证。

## 6. 本计划的成功标准

完成后必须能回答：

- `002384.SZSE` 为什么 2026-03-27 到 2026-04-08 的低吸过程是否形成关键启动点。
- `603439.SSE` 2026-05-11 是否是低吸蓄势后启动，还是当前缓存缺证。
- `601179.SSE` 2026-02-03 为什么偏早，2026-02-24/25 为什么更像低吸蓄力点。
- `600352.SSE` 和 `002240.SZSE` 的失败是大盘、买点、启动质量还是卖点问题。
- `002119.SZSE` 有信号但没买/不该买却买的链路原因。
- `002443.SZSE` 2026-05-14 是否属于买点可接受但卖点/浮盈回撤失败。
- 排除强势行情后，前 10 / 前 20 候选胜率是否仍成立。
- 动态大盘/主线画像是只适合审计，还是足以进入默认关闭实验。
- 新实验如果存在，收益提升来自避免亏损还是错过大肉后的替换偶然。

如果这些问题不能用表格和报告回答，就不能进入默认交易规则修改。
