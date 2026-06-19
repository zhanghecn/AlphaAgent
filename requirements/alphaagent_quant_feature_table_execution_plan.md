# AlphaAgent Quant Feature Table Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to execute this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This plan is the execution entrypoint for the next validation cycle; do not change the default trading rules until the promotion gate in this document passes.

**Goal:** 用全局回测之外的特征表、后验路径、真实组合执行归因和市场分层，判断下一轮策略优化到底改善了买点、卖点、回撤、满仓换仓，还是只吃到了强势题材行情。

**Architecture:** 继续保持一个公开策略 `mainline_dragon_pullback / 0.1.21` 和简单用户流程。内部把候选信号日特征、低吸/龙回头生命周期、固定持有后验、真实执行归因、卖点路径、替换交易质量和市场/主线画像拆成只读校验表；只有特征表证明某个窄规则有效，才允许做默认关闭实验。

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, existing `backtest_*` / `quant_*` tables, React/TypeScript, pytest, Vite, Docker Compose, reports under `memory/06_backtests/`.

---

## 0. 后续执行总览

这份文件作为后续执行总入口。执行顺序必须先审计、再归因、再做默认关闭实验，最后才讨论是否晋升默认策略；不能直接把单股观察结论写进买卖规则。

### 0.1 执行顺序

1. **冻结基线**
   - 固定产品基线为 `mainline_dragon_pullback / 0.1.21` 的 `#203/#194`，区间 `2025-03-26..2026-06-18`。
   - 每次实验前都用 `baseline_only=true` 确认没有研究开关污染基线。
   - 保留 `legacy_next_open`，不恢复历史 `14:30` 依赖。

2. **补齐只读特征表**
   - 候选信号日特征表：只使用信号日及以前数据。
   - 低吸/龙回头生命周期表：低吸蓄势按簇记录，首个有效上拉才允许成为关键 BUY。
   - 固定持有后验表：只用于判断候选本身质量，不参与交易。
   - 真实组合执行归因表：解释有信号但没买、满仓、排名、换仓和执行拒单。
   - 卖点路径和替换质量表：区分买点错、卖点回撤、卖早反弹、替换变差。
   - 市场/主线动态画像表：只读提示行情向下、资金出逃、回暖、主线切换。
   - 因子交互和机会成本表：计算误杀赢家、避免亏损、替换质量变化。

3. **完成重点股票逐日复核**
   - 重点股票至少包含：`002384.SZSE`、`002119.SZSE`、`002443.SZSE`、`601179.SSE`、`600352.SSE`、`002240.SZSE`、`603439.SSE`、`603629.SSE`，以及用户前面列出的云南锗业、江海股份、剑桥科技、合肥城建、金安国纪、亨通光电、红星发展、埃斯顿、立新能源。
   - 每只股票输出关键日期前后逐日特征、候选排名、计划/下单/成交状态、没买原因、真实卖点、MFE/MAE、固定 20 日后验和最终归因。
   - 不允许把“有信号但没买”简单归为策略失败，必须先分清是候选识别、组合满仓、执行池排名、理论持有、真实持有、缓存缺口还是换仓阈值。

4. **只在证据通过后设计默认关闭实验**
   - 低吸实验只处理“蓄势后首个有效上拉”和“假启动观察/降权”，不把蓄势每天变成 BUY。
   - 龙回头实验只处理重复高位风险、弱启动和市场退潮上下文，不做宽泛硬拒。
   - 卖点实验只处理高浮盈回撤、真失败启动、卖后易反弹和替换质量，不做单一止损规则。
   - 满仓换仓实验只处理错过候选明显强于当前持仓的情况，不强行扩大持仓。
   - 市场/主线实验第一阶段只做提示和审计，除非特征表证明不会误伤主线回踩。

5. **跑分组验证，不只看总收益**
   - 全局：收益、最大回撤、胜率、profit factor、Sharpe、买入/卖出/持仓中。
   - 年度：`2025`、`2026` 分组。
   - 市场：强势、科技窄牛、主线回踩、震荡轮动、弱反弹、risk-off、假强势。
   - 候选：前 `10/20/100`，以及排除强势行情后的前 `10/20/100`。
   - 重点股票：逐日目标问题是否修复，有无制造新错误。
   - 机会成本：误杀赢家收益、避免亏损收益、替换交易质量变化。

6. **产品展示保持简单**
   - `/quant` 不增加复杂策略组合按钮。
   - 候选页默认看前 `100`，分页展示，按评分排序。
   - 股票详情只突出关键 BUY、买拒、真实买入、真实卖出和没买原因。
   - 复杂因子放在“策略体检/归因解释”，不干扰普通操作流程。

### 0.2 本轮收口状态

1. Task 9 已完成：重点股票逐日归因已写入 `memory/06_backtests/2026-06-19_quant_focus_symbol_validation.md`，不再把样本粗略归为 `portfolio_capacity_miss`。
2. Task 10/11 已关闭：特征表和重点股票归因没有证明任何新规则满足晋升门槛，因此本轮不启动新的默认关闭实验，不生成空实验表，不改变默认策略。
3. 下一轮如果用户确认继续做实验，优先顺序是：
   - 高浮盈回撤保护，目标样本 `002443.SZSE`。
   - 低吸假启动观察/降权，目标样本 `600352.SSE`、`002240.SZSE`。
   - 满仓换仓质量，目标样本 `002384.SZSE`。
   - 支撑止损延迟确认，只针对卖后高概率反弹桶。
4. 每个实验必须单独跑、单独报告、单独判断，不组合调参。

### 0.3 通过/失败判定

一个实验只有同时满足下面条件，才允许进入默认规则讨论：

- 总收益不低于 `#203/#194`。
- 最大回撤不差于 `#203/#194`。
- 年度分组不明显变差。
- 排除强势行情后，前 `10/20` 候选胜率和收益不变差。
- 至少两个市场桶改善，且没有核心市场桶明显恶化。
- 避免亏损收益大于误杀赢家收益。
- 卖出释放仓位后的替换交易质量不差。
- 重点股票目标问题被修复，且没有制造同类新错误。
- 无未来函数，后验字段只用于审计。

不满足以上条件时，结论必须写成失败实验或只读审计，不允许默认开启。

## 1. 当前基线和边界

### 当前产品基线

- 公开策略：`mainline_dragon_pullback / 0.1.21`。
- 产品基线：`#203/#194`。
- 区间：`2025-03-26..2026-06-18`。
- 执行模型：`legacy_next_open`，即 D 日收盘可见信号，D+1 日线开盘执行。
- 收益：约 `+82.99%`。
- 最大回撤：约 `-15.59%`。
- 买入/卖出/持仓中：约 `224 / 214 / 10`。
- 候选观察：评分前 `100`，分页每页 `20`。
- 组合执行：BUY 候选前 `20`，最大持仓 `10`。

### 必须遵守的边界

- 不新增第二个普通用户公开策略。
- 不恢复历史 `14:30` 依赖。
- 不给低吸强行保留名额。
- 不把低吸蓄势期每一天画成 BUY。
- 不把后验收益、MFE、MAE、卖后反弹、当前策略交易结果用于信号日评分、排序、买卖、卖点或仓位。
- 不因为单只股票肉眼好就改默认规则。
- 不按股票代码特判。
- 不让任何实验开关为 `true` 的回测进入 `baseline_only=true`。
- 不用单次总收益判断策略有效；必须同时看年度、市场分层、排除强势行情、前 `10/20/100` 候选、重点股票、机会成本和替换质量。

### 本计划和已有计划的关系

- `requirements/alphaagent_quant_feature_drilldown_next_execution_plan.md`：细粒度特征校验的详细来源。
- `requirements/alphaagent_quant_next_experiment_execution_plan.md`：默认关闭实验队列的详细来源。
- 本文件是后续执行入口：先跑特征表校验，再选择最窄实验，最后按晋升门槛判断是否保留。

## 2. 核心问题

本轮不是继续凭感觉加因子，而是用表来回答：

- 买点收益下降，是低吸/龙回头信号本身错，还是满仓没买到好票？
- 回测亏损，是买点错，还是卖点在浮盈后回吐太多？
- `support_stop` 是真失败启动、卖早反弹、浮盈回吐，还是有承接后破位？
- 低吸和龙回头是两套因子，哪些因子共用，哪些情况下互相冲突？
- 低吸蓄势很久后，首个有效上拉是否明显优于纯蓄势观察日？
- 科技主线回踩、震荡轮动、弱市防守、熊市独立强票里，策略是否还能成立？
- 动态大盘/主线算法会不会在科技回踩时误伤龙回头，或在非科技轮动时错过新主线？
- 卖出释放仓位后，替换交易是否更好，还是把原本可修复的票卖掉换成更差标的？

## 3. 要落地的特征表

这些表先按逻辑表实现，可以来自 `backtest_factor_snapshots` / `backtest_factor_outcomes` 缓存、API 聚合 JSON 或报告导出；不要为了表名先创建物理表。

### 3.1 候选信号日特征表

**用途：** 判断信号日可见因子是否真的提高胜率、降低 MAE、减少假启动。

**粒度：** 一行一个 `trade_date + vt_symbol` 候选，只能使用 `trade_date` 当天及以前数据。

**必备字段：**

- 身份：`trade_date`, `vt_symbol`, `name`, `board`, `industry`, `concepts`。
- 动作：`persisted_action`, `entry_action`, `raw_entry_signal`, `executable_entry_signal`, `action_mismatch_resolved`。
- 排名：`total_score`, `rank`, `rank_bucket`, `execution_pool_rank`。
- setup：`entry_family`, `entry_family_label`, `low_position_reclaim_type`, `low_suction_dragon_state`, `entry_family_conflict`。
- 评分拆解：`dragon_entry_score`, `low_reclaim_entry_score`, `shared_quality_score`, `risk_penalty`, `market_context_penalty`。
- 低吸生命周期：`low_suction_days`, `support_hold_days`, `low_suction_stage_label`, `first_effective_lift`, `launch_confirmed`, `low_suction_launch_quality_bucket`。
- 均线和支撑：`ma_convergence_pct`, `ma5_distance_pct`, `ma10_distance_pct`, `ma20_distance_pct`, `ma30_distance_pct`, `ma5_slope_pct`, `ma10_slope_pct`, `ma20_slope_pct`, `ma30_slope_pct`, `support_price`, `support_distance_pct`。
- 量能和流动性：`volume_ratio_5d_20d`, `turnover_percentile_60d`, `turnover`, `amount`, `liquidity_score`, `persistent_volume_expansion`。
- K 线：`close_location_in_range`, `body_pct`, `upper_shadow_pct`, `lower_shadow_pct`, `gap_up_pct`, `intraday_range_pct`。
- 强势代理：`recent_limit_up_20d`, `near_limit_up_count_20d`, `large_bull_count_20d`, `consecutive_bull_closes`。
- 风险：`drawdown_from_pivot_pct`, `max_drawdown_60d`, `overhead_pressure_pct`, `high_level_sideways_distribution_risk`, `volume_stall_risk`, `key_support_break_risk`, `spiky_churn_risk`, `illiquid_forgotten_risk`, `weekly_top_fractal_risk`。
- 市场/主线：`dynamic_market_regime`, `market_warning_level`, `market_recovery_level`, `fund_flow_state`, `fund_flow_streak_days`, `fund_flow_coverage_label`, `dominant_theme`, `theme_strength`, `stock_theme_alignment`。
- 审计元数据：`feature_window_end`, `uses_future_for_label_only=false`, `not_used_for_signal_score=true`。

**必须输出的分桶：**

- `rank_bucket`: `1-10`, `11-20`, `21-50`, `51-100`。
- `entry_family`: `dragon_pullback`, `stealth_low_suction`, `low_position_reclaim`, `overlap`, `unknown`。
- `low_suction_launch_quality_bucket`: `first_balanced_lift`, `unconfirmed_buildup`, `late_lift`, `weak_volume_lift`, `repeat_lift`, `unknown`。
- `market_bucket`: `strong_broad`, `narrow_mainline_bull`, `mainline_pullback`, `choppy_rotation`, `weak_rebound`, `risk_off`, `false_bull`, `unknown`。

### 3.2 低吸/龙回头生命周期表

**用途：** 避免把低吸蓄势每天都当买点，改成按簇识别“蓄势 -> 首个有效上拉 -> 后续验证”。

**粒度：** 一行一个股票的一段生命周期。

**必备字段：**

- `vt_symbol`, `cluster_start_date`, `cluster_end_date`, `key_signal_date`。
- `cluster_type`: `low_suction_buildup`, `first_effective_lift`, `dragon_pullback`, `dragon_low_suction_overlap`, `low_position_reclaim`。
- `buildup_days`, `support_hold_days`, `ma_convergence_start`, `ma_convergence_end`。
- `support_ma`: `ma5`, `ma10`, `ma20`, `ma30`, `mixed`。
- `reclaim_source`: `from_ma5`, `from_ma10`, `from_ma20`, `from_ma30`, `from_low_box`, `unknown`。
- `first_effective_lift`, `launch_quality_bucket`, `launch_confirmed`。
- `key_signal_rank`, `key_signal_score`, `key_signal_action`。
- `cluster_return_10d`, `cluster_return_20d`, `cluster_mfe_20d`, `cluster_mae_20d`。
- 审计元数据：`uses_future_for_label_only=true`, `not_used_for_signal_score=true`。

**必须回答：**

- 低吸蓄势多久后有效，是否存在“蓄势太久反而弱”？
- 从 MA30/MA20/MA10 低位重新冲上 MA5 的动能，是否只是 `low_position_reclaim` 的 subtype？
- 低吸和龙回头重叠时，是增强、冲突，还是应由其中一个 setup 主导解释？

### 3.3 固定持有后验表

**用途：** 把候选质量和组合持仓容量分开，判断“这个候选本身是否好”。

**粒度：** 一行一个候选，按统一假设 D+1 开盘买入，不考虑满仓。

**必备字段：**

- 执行假设：`signal_date`, `execute_date`, `execute_open_price`。
- 收益：`return_3d`, `return_5d`, `return_10d`, `return_20d`。
- 浮盈：`mfe_3d`, `mfe_5d`, `mfe_10d`, `mfe_20d`。
- 浮亏：`mae_3d`, `mae_5d`, `mae_10d`, `mae_20d`。
- 阈值：`hit_profit_5_pct`, `hit_profit_8_pct`, `hit_profit_10_pct`, `hit_loss_3_pct`, `hit_loss_5_pct`, `hit_loss_7_pct`, `first_hit`。
- 路径标签：`failed_launch`, `support_stop_like`, `first_5pct_profit_date`, `first_5pct_loss_date`。
- 当前策略对照：`current_strategy_entry_date`, `current_strategy_exit_date`, `current_strategy_return_pct`, `current_strategy_exit_reason`。
- 审计元数据：`uses_future_for_label_only=true`, `not_used_for_signal_score=true`。

**归因规则：**

- 固定 20 日收益为正、当前策略亏损：优先归因卖点/回撤/替换。
- 固定 20 日收益为负、当前策略也亏损：优先归因买点/假启动/弱市。
- 固定 20 日收益为正、组合没买：优先归因满仓、排名、换仓阈值。

### 3.4 真实组合执行归因表

**用途：** 回答“候选有信号为什么没买”和“满仓是否错过更好机会”。

**粒度：** 一行一个候选进入组合约束后的真实结果。

**必备字段：**

- 候选：`signal_date`, `execute_date`, `vt_symbol`, `rank`, `score`, `entry_family`。
- 计划链路：`planned`, `ordered`, `filled`, `not_filled_reason`, `not_filled_subreason`, `not_filled_label`。
- 仓位：`position_count_before`, `max_positions`, `execution_pool_rank`, `held_symbols_before`。
- 换仓：`rotation_candidate`, `rotation_reason`, `rotation_score_gap`, `replaced_symbol`。
- 真实交易：`buy_price`, `sell_price`, `sell_reason`, `closed_return_pct`, `holding_days`。
- 错过候选后验：`missed_return_10d`, `missed_return_20d`, `missed_mfe_20d`, `missed_mae_20d`。
- 机会成本：`held_symbol`, `held_unrealized_return_pct`, `held_support_state`, `score_gap`, `replacement_quality_delta`。
- 审计元数据：`uses_future_for_label_only=true`, `not_used_for_signal_score=true`。

**必须排除的伪机会：**

- `missed_symbol == held_symbol` 时不能算作真实换仓机会，只能算“已持有/理论持有解释”。

### 3.5 卖点路径和替换质量表

**用途：** 判断亏损来自买点错误、卖点慢、卖早反弹、浮盈回吐还是替换交易更差。

**粒度：** 一行一笔闭合交易。

**必备字段：**

- 入场：`entry_date`, `entry_family`, `entry_rank`, `entry_score`, `entry_market_context`。
- 路径：`holding_days`, `mfe_pct`, `mae_pct`, `highest_profit_pct`, `giveback_from_peak_pct`。
- 卖点：`exit_date`, `exit_reason`, `exit_return_pct`, `support_stop_context`。
- 卖后：`rebound_5d`, `rebound_10d`, `rebound_20d`, `sold_before_rebound`。
- 替换：`next_buy_vt_symbol`, `next_buy_date`, `replacement_return_pct`, `replacement_quality`。
- 归因：`trade_problem_type`。
- 审计元数据：`uses_future_for_label_only=true`, `not_used_for_signal_score=true`。

**`trade_problem_type` 取值：**

```python
BUY_POINT_BAD = "buy_point_bad"
SELL_GIVEBACK = "sell_giveback"
SOLD_TOO_EARLY = "sold_too_early"
PORTFOLIO_CAPACITY_MISS = "portfolio_capacity_miss"
REPLACEMENT_BAD = "replacement_bad"
HEALTHY_TREND_WINNER = "healthy_trend_winner"
UNKNOWN = "unknown"
```

**初始分类规则：**

- 固定 20 日收益 `< -3%` 且真实收益 `< 0`：`buy_point_bad`。
- 固定 20 日收益 `> +5%` 且真实收益 `< 0`：`sell_giveback`。
- `support_stop` 后 10 日反弹 `>= +8%`：`sold_too_early`。
- 固定 20 日收益 `> +5%`、真实未买且原因是满仓/无换仓：`portfolio_capacity_miss`。
- 卖出后的下一笔替换交易收益 `< -3%`：`replacement_bad`。
- 真实收益 `> +10%` 或 MFE `> +15%`：`healthy_trend_winner`。
- 其他：`unknown`。

### 3.6 市场/主线动态画像表

**用途：** 验证策略是否只适合当前科技窄牛，还是在震荡、弱市和主线切换中也能成立。

**粒度：** 一行一个交易日，可以 join 到候选日或买入日。

**输入字段：**

- 指数趋势：核心指数 `5d/10d/20d/60d` 收益、MA 斜率、距离 20 日高点回撤。
- 全市场宽度：上涨家数占比、强于 MA5/MA10/MA20/MA60 占比、涨停/跌停家数。
- 波动和恐慌：跌停扩散、长阴数量、连续风险日、风险释放后反弹天数。
- 板块主线：板块涨幅集中度、龙头板块持续天数、板块资金流入/流出、股票与主线板块对齐。
- 资金流覆盖：`fund_flow_source`, `fund_flow_start_date`, `fund_flow_end_date`, `fund_flow_coverage_label`。

**输出字段：**

- `dynamic_market_regime`: `strong_broad`, `narrow_mainline_bull`, `mainline_pullback`, `choppy_rotation`, `weak_rebound`, `risk_off`, `false_bull`, `unknown`。
- `market_warning_level`: `0..4`，0 正常，4 退潮/恐慌。
- `market_recovery_level`: `0..4`，0 未回暖，4 明确修复。
- `fund_flow_state`: `inflow`, `recovery`, `outflow`, `panic_outflow`, `insufficient_data`。
- `dominant_theme`, `theme_strength`, `stock_theme_alignment`。

**必须回答：**

- 科技主线回踩时，市场风险处罚是否会误伤后续龙回头启动？
- 科技退潮但非科技轮动低吸变强时，能否识别新主线切换？
- 熊市里少数独立强票是否被过度过滤？
- 排除强势行情后，前 `10/20/100` 候选胜率是否仍成立？

### 3.7 因子交互和机会成本表

**用途：** 判断因子加分/扣分到底减少亏损，还是误杀趋势赢家。

**粒度：** 一行一个因子组合或一次实验变化。

**必备字段：**

- `factor_group`, `factor_value`, `sample_count`, `win_rate`, `avg_return_20d`, `median_return_20d`, `profit_factor_proxy`。
- `mfe_8pct_hit_ratio`, `mae_5pct_hit_ratio`, `failed_launch_ratio`, `support_stop_like_ratio`。
- `removed_winner_count`, `removed_winner_return_sum`, `avoided_loser_count`, `avoided_loser_return_sum`。
- `added_loser_count`, `added_loser_return_sum`, `replacement_quality_delta`。
- `market_bucket`, `rank_bucket`, `entry_family`。

**必须回答：**

- 某个低吸加分是否只是把更多低质量票推到前 20？
- 某个风险扣分是否减少了亏损，还是错过了大肉票？
- 某个卖点提前卖出后，释放仓位买到的替换交易是否更好？

### 3.8 重点股票逐日案例表

**用途：** 防止全局指标掩盖用户肉眼确认的关键问题。

**重点股票：**

- `002384.SZSE` 东山精密。
- `002119.SZSE` 康强电子。
- `002443.SZSE` 金洲管道。
- `601179.SSE` 中国西电。
- `600352.SSE` 浙江龙盛。
- `002240.SZSE` 盛新锂能。
- `603439.SSE` 贵州三力。
- `603629.SSE` 利通电子。
- 云南锗业、江海股份、剑桥科技、合肥城建、金安国纪、亨通光电。
- 红星发展、埃斯顿、立新能源。

**每只股票必须输出：**

- 关键日期前后 `20` 个交易日逐日特征。
- 当日是否 `raw_entry_signal`。
- 当日是否 `executable_entry_signal/action=BUY`。
- 候选排名和评分拆解。
- 组合是否计划、下单、成交。
- 没买原因和子原因。
- 如果买入，真实卖点、MFE、MAE、最高浮盈回撤、最终收益。
- 固定 20 日后验收益。
- 当前结论：买点问题、卖点问题、满仓问题、市场问题、数据覆盖问题或未知。

## 4. 执行任务

### Task 0: 冻结基线和实验状态

**目的：** 确认比较对象，避免长区间 run、局部缓存 run 或研究开关污染产品基线。

**Files:**

- Read: `memory/06_backtests/README.md`
- Read: `memory/06_backtests/strategy_optimization_ledger.md`
- Read: `memory/09_decisions/decisions.md`
- Update only if facts change: `memory/06_backtests/README.md`
- Update only if facts change: `memory/06_backtests/strategy_optimization_ledger.md`

- [x] Step 1: 检查工作区。

Run:

```bash
git status --short
```

Expected:

- 记录当前 dirty files。
- 不 revert、不 reset、不 checkout 用户或前序改动。

- [x] Step 2: 确认产品基线。

Run:

```bash
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
```

Expected:

- 返回 `#203/#194` 或后续明确标记为 `current_product` 的新基线。
- 不返回任何实验开关为 `true` 的 run。
- 响应里有 `baseline_reason`；如存在更长区间样本，需要有 `baseline_warning`。

- [x] Step 3: 建立本轮报告文件。

Create:

- `memory/06_backtests/YYYY-MM-DD_quant_feature_table_validation_report.md`

Report header:

```text
基线：#203/#194
策略：mainline_dragon_pullback / 0.1.21
区间：2025-03-26..2026-06-18
执行：legacy_next_open
收益：+82.99%
最大回撤：-15.59%
买入/卖出/持仓中：224 / 214 / 10
```

### Task 1: 定义特征字段字典和未来函数边界

**目的：** 所有表先标清字段是否信号日可见，避免后续实验误用后验字段。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/api/quant.ts`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 给每个输出字段补审计元数据。

Required metadata:

```python
{
    "feature_window_end": "2026-04-01",
    "uses_future_for_label_only": False,
    "not_used_for_signal_score": True,
}
```

For outcome labels:

```python
{
    "uses_future_for_label_only": True,
    "not_used_for_signal_score": True,
}
```

- [x] Step 2: 增加未来函数防线测试。

Test names:

```text
test_factor_snapshot_marks_signal_day_features_as_no_future
test_outcome_labels_mark_future_for_audit_only
test_experiment_scoring_does_not_read_outcome_labels
```

Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "factor_snapshot or outcome_labels or no_future" -q
```

Expected:

- 所有后验字段都有 `uses_future_for_label_only=true`。
- 默认策略评分不读取任何后验字段。

### Task 2: 生成候选信号日特征矩阵

**目的：** 用信号日可见特征评估买点质量。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 扩展 `GET /api/backtests/{id}/factor-candidates`。

Required query:

```bash
curl -sS 'http://localhost:8000/api/backtests/203/factor-candidates?limit=2000'
```

Required output keys:

```json
{
  "items": [],
  "summary": {
    "by_rank_bucket": [],
    "by_entry_family": [],
    "by_low_suction_launch_quality": [],
    "by_market_bucket": []
  },
  "metadata": {
    "not_used_for_signal_score": true
  }
}
```

- [x] Step 2: 报告里输出 TopN 候选质量。

Required buckets:

- top `10`。
- top `20`。
- top `100`。
- 排除 `strong_broad` / `narrow_mainline_bull` 后的 top `10/20/100`。

### Task 3: 生成低吸/龙回头生命周期矩阵

**目的：** 把低吸蓄势作为簇证据，把关键 BUY 限定为首个有效上拉或明确龙回头回踩启动。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/quant/screening_payloads.py`
- Modify: `frontend/src/features/quant/RecommendationsPanel.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 输出生命周期 segment。

Required API shape inside `strategy-timeline` or `factor-audit`:

```json
{
  "lifecycle_segments": [
    {
      "vt_symbol": "002384.SZSE",
      "cluster_type": "low_suction_buildup",
      "cluster_start_date": "2026-03-27",
      "cluster_end_date": "2026-04-07",
      "key_signal_date": "2026-04-08",
      "first_effective_lift": true,
      "key_signal_action": "BUY"
    }
  ]
}
```

- [x] Step 2: 前端只画关键点。

Rules:

- 低吸蓄势日显示为候选簇证据，不画 BUY。
- 首个有效上拉且 `action=BUY` 才画 BUY。
- 未通过规则显示 WATCH/买拒。
- 真实买入、卖出和拒单仍按组合执行结果画。

### Task 4: 生成固定持有后验矩阵

**目的：** 判断候选本身好坏，独立于满仓和组合换仓。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 扩展后验字段。

Required output fields:

```json
{
  "return_20d": 12.3,
  "mfe_20d": 18.4,
  "mae_20d": -3.1,
  "failed_launch": false,
  "current_strategy_return_pct": -4.8,
  "current_strategy_exit_reason": "support_stop",
  "uses_future_for_label_only": true,
  "not_used_for_signal_score": true
}
```

- [x] Step 2: 输出买点/卖点初步归因。

Required summary:

```json
{
  "candidate_quality_vs_strategy": {
    "fixed_positive_strategy_negative": [],
    "fixed_negative_strategy_negative": [],
    "fixed_positive_not_bought": []
  }
}
```

### Task 5: 生成真实组合执行归因和错过候选表

**目的：** 解释候选没买、满仓错过、换仓阈值和执行拒绝。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 拆 `not_filled_subreason`。

Required subreasons:

```text
already_theoretical_holding
already_real_holding
candidate_cache_sparse_or_missing
planned_not_ordered
outside_execution_pool
full_position_no_rotation
rotation_score_gap_too_small
limit_up_open_blocked
no_execute_bar
unknown
```

- [x] Step 2: 错过候选机会成本排除同股伪机会。

Rule:

```text
missed_symbol == held_symbol 时，不计入 missed_candidate_opportunity_cost。
```

- [x] Step 3: 报告输出满仓问题结论。

Required metrics:

- top20 候选数。
- 成交数。
- 未成交数。
- 未成交后固定 20 日为正数量。
- 未成交候选平均 20 日收益。
- 当时持仓平均浮盈/浮亏。
- `score_gap` 分布。

### Task 6: 生成卖点路径和替换质量矩阵

**目的：** 判断收益降低主要来自卖点还是买点。

**Files:**

- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 扩展 `setup-market-exit-audit`。

Required output:

```json
{
  "exit_path_replacement_quality": {
    "by_trade_problem_type": [],
    "by_exit_reason": [],
    "by_support_stop_context": [],
    "replacement_quality_summary": {}
  }
}
```

- [x] Step 2: 对 `support_stop` 分桶。

Required buckets:

```text
true_failed_launch_stop
stopped_then_rebounded
had_follow_through_then_lost_support
clean_float_profit_giveback
high_mfe_stop_then_rebounded
unknown
```

- [x] Step 3: 输出替换质量。

Required fields:

```json
{
  "replacement_symbol": "002384.SZSE",
  "replacement_return_pct": -3.6,
  "replacement_quality": "bad_replacement",
  "replacement_quality_delta": -8.2
}
```

### Task 7: 生成市场/主线动态画像校验

**目的：** 验证策略是否能适应科技窄牛、主线回踩、震荡轮动、弱市和熊市独立强票。

**Files:**

- Modify: `alphaagent/server/services/quant/market_context.py`
- Modify: `alphaagent/server/services/backtest/queries.py`
- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 把市场画像 join 到候选日和买入日。

Required summary:

```json
{
  "market_context_validation": {
    "by_market_regime": [],
    "by_market_warning_level": [],
    "by_market_recovery_level": [],
    "excluding_strong_market": {},
    "fund_flow_coverage": {}
  }
}
```

- [x] Step 2: 明确资金流不足。

Rules:

- 历史资金流缺失时显示 `fund_flow_state=insufficient_data`。
- 不能把 `insufficient_data` 当成 `inflow`、`outflow` 或 `normal`。
- 报告必须写明资金流覆盖起止日期。

### Task 8: 生成因子交互和机会成本矩阵

**目的：** 判断加分/扣分因子是提高胜率，还是改变组合路径后伤害收益。

**Files:**

- Modify: `alphaagent/server/services/backtest/factor_audit.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: 输出因子组合表现。

Required combinations:

- `entry_family + rank_bucket`。
- `entry_family + market_bucket`。
- `low_suction_launch_quality + market_bucket`。
- `low_suction_days_bucket + first_effective_lift`。
- `reclaim_source + support_ma`。
- `risk_penalty_bucket + market_warning_level`。

- [x] Step 2: 输出机会成本。

Required metrics:

```json
{
  "removed_winner_return_sum": 0.0,
  "avoided_loser_return_sum": 0.0,
  "added_loser_return_sum": 0.0,
  "replacement_quality_delta": 0.0
}
```

### Task 9: 重点股票逐日复核

**目的：** 用用户反复指出的股票验证细节，不让全局均值掩盖具体错误。

**Files:**

- Read/API: `GET /api/quant/symbols/{vt_symbol}/signal-history`
- Read/API: `GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=`
- Read/API: `GET /api/backtests/{id}/strategy-timeline?vt_symbol=`
- Report: `memory/06_backtests/YYYY-MM-DD_quant_focus_symbol_validation.md`

- [x] Step 1: 对每只重点股票导出逐日信号。

Example:

```bash
curl -sS 'http://localhost:8000/api/quant/symbols/002384.SZSE/signal-history?start_date=2026-03-20&end_date=2026-04-20'
```

- [x] Step 2: 对关键日期解释“有信号但没买”。

Example:

```bash
curl -sS 'http://localhost:8000/api/backtests/203/candidate-trace?vt_symbol=002384.SZSE&signal_date=2026-04-01'
```

- [x] Step 3: 每只股票给出最终归因。

Evidence:

- `memory/06_backtests/2026-06-19_quant_focus_symbol_validation.md`

结论：

- 东山精密、合肥城建部分日期是满仓/理论持有/真实成交链路问题，不是形态识别失败。
- 康强电子、中国西电、浙江龙盛、盛新锂能、亨通光电包含买点假启动或低吸确认后无承接。
- 金洲管道是高浮盈回吐卖点样本。
- 云南锗业、剑桥科技、贵州三力是当前信号定义缺口。
- 埃斯顿是 signal-history 和 candidate-trace 对齐缺口。

Allowed conclusions:

```text
buy_point_bad
sell_giveback
sold_too_early
portfolio_capacity_miss
replacement_bad
market_context_risk
data_coverage_issue
healthy_trend_winner
unknown
```

### Task 10: 设计默认关闭实验队列

**目的：** 特征表通过后，只做最窄实验，不能把直觉规则直接改成默认策略。

**Files:**

- Modify: `alphaagent/server/services/backtest/schemas.py`
- Modify: `alphaagent/server/services/backtest/baseline_policy.py`
- Modify: `alphaagent/server/services/backtest/scoring.py`
- Modify: `alphaagent/server/services/backtest/simulation.py`
- Modify: `alphaagent/server/services/quant/strategy_replay.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**候选实验：**

1. `enable_low_suction_first_effective_lift_watch`
   - 只处理低吸蓄势久但未出现首个有效上拉的候选。
   - 不把低吸蓄势每天当 BUY。
   - 不强行抢名额。

2. `enable_contextual_failed_launch_watch_gate`
   - 只处理弱市场、弱启动、未回暖、收盘位置差、量能弱的低吸/龙回头候选。
   - 不 broad 硬拒所有低吸确认。

3. `enable_peak_giveback_with_replacement_guard`
   - 只处理已有明显最高浮盈后快速回吐，且不是当前买点/持有保护状态的交易。
   - 必须同时检查卖出后替换质量。

4. `enable_support_reclaim_delay`
   - 只处理卖出日恐慌、支撑附近、且次日可能收复的 `support_stop`。
   - 不能改成通用“支撑止损不卖”。

5. `enable_missed_candidate_quality_rotation`
   - 只在错过候选明显强于当前持仓、分差足够、当前持仓没有趋势赢家特征时换仓。
   - 必须排除同股伪机会。

6. `enable_market_context_dynamic_threshold`
   - 第一阶段只做审计，不直接交易。
   - 如果进入实验，只能调整观察阈值或仓位风险提示，不能一刀切过滤主线回踩。

- [x] Step 1: 所有实验开关默认 `False`。

- [x] Step 2: 所有实验开关加入 `RESEARCH_SWITCHES`。

- [x] Step 3: 任一实验开关为 `True`，不得进入 `baseline_only=true`。

- [x] Step 4: 每个实验必须先有定向单测，再跑全局回测。

本轮关闭方式：

- `memory/06_backtests/2026-06-19_quant_feature_table_validation_report.md` 和 `memory/06_backtests/2026-06-19_quant_focus_symbol_validation.md` 没有证明任何新规则满足晋升门槛。
- 因此本轮不启动新的默认关闭实验，不跑实验全局回测，也不生成实验 run。
- 该步骤作为实验门槛关闭：下一轮若启动任一实验，必须先补定向单测，再单独跑全局回测；不能组合调参，不能进入 `baseline_only=true`。
- 已存在的默认关闭实验继续保持关闭且被 `baseline_only=true` 排除。

### Task 11: 跑全局、年度、市场和排除强势验证

**目的：** 判断实验是否真的提升收益和降低亏损。

**Files:**

- Report: `memory/06_backtests/YYYY-MM-DD_quant_experiment_comparison_report.md`
- Update: `memory/06_backtests/strategy_optimization_ledger.md`
- Update if decision changes: `memory/09_decisions/decisions.md`

- [x] Step 1: 每个实验单独跑，不组合。

Required output table:

```text
run_id | switch | total_return_pct | max_drawdown_pct | win_rate | profit_factor | sharpe | buys/sells/open | decision
```

本轮关闭方式：

- 没有新实验通过 Task 10 的启动门槛，所以本轮没有新的 `run_id`。
- 不用空实验表冒充对比结果；有效结论是“不启动实验，不改变默认策略”。
- 下一轮任何实验必须单独跑，不允许组合多个开关。

- [x] Step 2: 对每个实验输出分组。

Required groups:

- 年度：`2025`, `2026`。
- 市场：`strong_broad`, `narrow_mainline_bull`, `mainline_pullback`, `choppy_rotation`, `weak_rebound`, `risk_off`, `false_bull`。
- 排除强势行情。
- top `10/20/100` 候选。
- 重点股票。
- removed winners vs avoided losers。
- replacement quality。

本轮关闭方式：

- 因为没有新实验 run，本轮没有实验分组表。
- 已输出特征表分组、市场分层、重点股票归因和机会成本基线；这些证据支持“不启动新实验”的决策。
- 下一轮实验 run 必须按这些分组输出后才允许讨论晋升。

- [x] Step 3: 输出不通过原因。

Required rejection reasons:

```text
return_lower
drawdown_worse
win_rate_lower
profit_factor_lower
missed_trend_winners
replacement_worse
weak_market_worse
excluding_strong_market_worse
focus_symbol_not_fixed
future_function_risk
sample_too_small
```

本轮不通过原因：

- `sample_too_small`: 多个重点问题桶仍是单股/少量样本，不能直接默认化。
- `focus_symbol_not_fixed`: 云南锗业、剑桥科技、贵州三力仍是识别缺口，埃斯顿仍是候选链路对齐缺口。
- `replacement_worse`: 浙江龙盛、亨通光电显示替换交易可能变差。
- `missed_trend_winners`: 因子机会成本表显示 removed-winner proxy 较大，任何扣分/过滤实验必须先证明不会误杀趋势赢家。
- `future_function_risk`: 高浮盈回撤、卖后反弹、MFE/MAE 只能用于审计；若进入交易规则，必须重写为信号日/卖出日可见条件。

## 5. 晋升门槛

### 5.1 允许保留为研究开关

必须全部满足：

- 默认值为 `False`。
- 不进入 `baseline_only=true`。
- 无未来函数。
- 至少修复一个明确问题桶。
- 报告能解释收益变化来源。
- 不影响普通用户主流程。

### 5.2 允许进入候选默认规则讨论

必须全部满足：

- 总收益不低于 `#203/#194`。
- 最大回撤不差于 `#203/#194`。
- profit factor 不低于基线。
- Sharpe 不低于基线。
- 年度分组至少不差。
- 排除强势行情后的 top10/top20 候选胜率不差。
- 至少两个市场桶改善，且没有核心市场桶明显恶化。
- 避免亏损收益大于误杀赢家收益。
- 卖出释放仓位后的替换质量不差。
- 重点股票中至少修复目标问题，且没有制造新的同类错误。

### 5.3 允许默认开启

必须额外满足：

- 多年全 A 或更长历史样本通过。
- walk-forward 通过。
- 参数敏感性稳定。
- 高摩擦/滑点压力测试不失效。
- 数据覆盖风险可解释。
- 用户确认接受策略语义变化。

## 6. 用户界面约束

普通用户页面保持简单：

- `/quant` 仍只保留候选和回测主路径。
- 不新增多个策略下拉或多个复杂按钮。
- 候选表显示评分、排名、BUY/WATCH/拒买、关键解释。
- 股票详情 K 线只显示关键 BUY、买拒、真实买入、真实卖出。
- 复杂特征表只放在“策略体检/归因解释”区域。
- 页面必须明确区分：
  - 候选有信号。
  - 组合计划买。
  - 实际下单。
  - 实际成交。
  - 为什么没买。
  - 为什么卖。

## 7. 最终验证命令

后续执行完成后必须跑：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
pnpm --dir frontend run build
git diff --check
```

API 冒烟：

```bash
curl -sS 'http://localhost:8000/api/health'
curl -sS 'http://localhost:8000/api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5'
curl -sS 'http://localhost:8000/api/backtests/203/factor-audit?top_limit=100'
curl -sS 'http://localhost:8000/api/backtests/203/setup-market-exit-audit?lookahead_days=10'
curl -sS 'http://localhost:8000/api/backtests/203/strategy-timeline?vt_symbol=002384.SZSE'
curl -sS 'http://localhost:8000/api/quant/symbols/002384.SZSE/signal-history?start_date=2026-03-20&end_date=2026-04-20'
```

页面烟测：

- `/quant`
- `/stocks/002384.SZSE`
- `/stocks/002443.SZSE`
- `/stocks/002119.SZSE`

Expected:

- `/quant` 不展示空候选误导用户。
- `baseline_only=true` 不返回研究实验。
- 股票详情能看到候选、真实买卖和未买原因的统一链路。
- 低吸蓄势不被密集画成 BUY。

## 8. 完成标准

本计划完成时，报告必须能回答：

- 收益变化来自买点、卖点、满仓、换仓、市场环境，还是样本强势行情。
- 排除强势行情后，前 `10/20/100` 候选是否仍有效。
- 低吸蓄势和首个有效上拉是否被区分。
- 龙回头和低吸重叠时是否有明确主导规则。
- `support_stop` 是否被拆成可行动的子问题。
- 高浮盈回吐是否能被窄规则处理，而不误杀趋势赢家。
- 卖出后的替换交易质量是否不变差。
- 重点股票的问题是否被逐日解释清楚。
- 所有后验字段是否只用于审计，不进入信号日交易逻辑。
