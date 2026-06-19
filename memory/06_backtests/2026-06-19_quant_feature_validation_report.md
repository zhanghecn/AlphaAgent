# Quant Feature Validation Report

日期：2026-06-19
基线：`#203 / mainline_dragon_pullback / 0.1.21`
区间：`2025-03-26..2026-06-18`
口径：`legacy_next_open`，候选观察前 100，组合执行 BUY 前 20，最大持仓 10。

## 摘要

本报告执行 `requirements/alphaagent_quant_feature_validation_execution_plan.md` 的 Task 4。结论是：当前特征表已经能更清楚地区分买点、卖点、卖早反弹、替换交易和趋势赢家，但证据仍不足以直接修改默认交易规则。

当前产品基线收益 `+82.99%`，最大回撤 `-15.59%`，买入/卖出/持仓中 `224 / 214 / 10`。`baseline_reason=implicit_common_start_date`，并提示：存在更长起点的默认参数回测，当前按同结束日中最常见起点选择产品基线。。

## 因子审计总览

| 审计 | 样本 | 胜率 | 平均观察收益 | 排除强势数 |
| --- | ---: | ---: | ---: | ---: |
| `factor_10` | 10 | +90.00% | +205.34% | 0 |
| `factor_20` | 20 | +65.00% | +121.03% | 0 |
| `factor_100` | 100 | +66.00% | +36.12% | 0 |
| `factor_20_exstrong` | 9 | +100.00% | +229.15% | 11 |
| `factor_100_exstrong` | 50 | +78.00% | +54.17% | 50 |

注意：当前 `factor-audit` 是固定持有后验口径，不是组合真实成交口径。Top10/Top20 样本存在极端大收益，不能单独作为默认规则依据。

## Top100 关键分桶

### 入场类型

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `dragon_pullback` | 45 | +71.11% | +66.48% |
| `low_position_reclaim` | 15 | +86.67% | +25.38% |
| `unknown` | 40 | +52.50% | +5.99% |

### 低位承接类型

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `ma_support_reclaim` | 7 | +85.71% | +5.30% |
| `none` | 85 | +62.35% | +38.01% |
| `platform_accumulation_launch` | 8 | +87.50% | +42.94% |

### 市场环境

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `choppy_rotation` | 39 | +71.79% | +43.22% |
| `false_bull` | 11 | +100.00% | +93.00% |
| `strong_broad` | 50 | +54.00% | +18.07% |

### 低吸天数

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `0` | 26 | +88.46% | +110.97% |
| `1-2` | 19 | +47.37% | +4.33% |
| `3-5` | 43 | +60.47% | +13.34% |
| `6-10` | 12 | +66.67% | +5.90% |

### 启动质量

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `high_close_launch` | 6 | +83.33% | +24.74% |
| `late_pullback_launch` | 2 | +100.00% | +67.31% |
| `not_low_suction` | 45 | +71.11% | +65.94% |
| `repeated_launch` | 1 | +0.00% | -3.10% |
| `unconfirmed_buildup` | 46 | +58.70% | +7.92% |

## 排除强势行情后的 Top100

| 分桶 | 样本 | 胜率 | 平均观察收益 |
| --- | ---: | ---: | ---: |
| `dragon_pullback` | 27 | +77.78% | +87.78% |
| `low_position_reclaim` | 8 | +87.50% | +35.97% |
| `unknown` | 15 | +73.33% | +3.37% |

排除强势后样本从 100 降到 50，胜率 `+78.00%`，平均观察收益 `+54.17%`。这说明候选在非强势窗口仍有正后验，但当前资金流长期全为 `unknown`，还不能证明已稳定识别科技主线或非科技轮动主线。

## 买卖问题矩阵

| 问题 | 样本 | 胜率 | 平均收益 | 卖早数 | 坏替换数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 替换交易变差 (`replacement_bad`) | 80 | +43.75% | +7.17% | 12 | 66 |
| 卖早反弹 (`sold_too_early`) | 48 | +6.25% | -6.85% | 48 | 21 |
| 买点问题 (`buy_point_bad`) | 26 | +0.00% | -7.12% | 0 | 0 |
| 趋势赢家 (`healthy_trend_winner`) | 26 | +100.00% | +29.47% | 16 | 0 |
| 卖点回撤问题 (`sell_giveback`) | 21 | +0.00% | -6.43% | 3 | 11 |
| 未归类 (`None`) | 13 | +38.46% | -1.39% | 2 | 0 |

解释：

- `replacement_bad` 样本最多，说明不能只看“该不该卖”，还必须看卖出后释放仓位买到了什么。
- `sold_too_early` 有 48 笔，均值为负，说明支撑止损后反弹是真问题，但不能直接推导为“不卖”。
- `sell_giveback` 有 21 笔，主要对应已有浮盈后回撤到亏损的路径。
- `buy_point_bad` 有 26 笔，全部亏损，说明假启动/买后无承接仍需买点侧窄处罚或观察标签。

## Support Stop 拆分

| 上下文 | 样本 | 平均收益 | 平均 MFE | 卖后反弹数 |
| --- | ---: | ---: | ---: | ---: |
| 真失败启动止损 (`true_failed_launch_stop`) | 49 | -7.84% | -2.63% | 0 |
| 止损后反弹 (`stopped_then_rebounded`) | 41 | -6.94% | +0.82% | 41 |
| 有承接但后续破支撑 (`had_follow_through_but_lost_support`) | 14 | -5.36% | +4.34% | 0 |
| 浮盈回吐后破位 (`clean_float_profit_giveback`) | 13 | -8.87% | +11.41% | 0 |
| 高浮盈后止损又反弹 (`high_mfe_then_rebound_after_stop`) | 7 | -6.30% | +12.25% | 7 |
| 其他支撑止损 (`other_support_stop`) | 1 | -5.78% | +5.89% | 0 |

`support_stop` 不是一个问题：真失败启动、止损后反弹、浮盈回吐和有承接后破支撑混在一起。下一步如果做卖点实验，必须按这些上下文拆开，不能用一个通用回撤止盈或通用延迟止损替代。

## 重点股票复核

### `603439.SSE`

当前 #203 timeline 在 `2026-05-01..2026-05-20` 没有候选/计划/成交行，说明当前产品基线无法直接证明 `2026-05-11` 的低吸过程是否被识别。可见行集中在 2025 年和 2026-06-17/18；`2026-06-17` 被聚合为低吸蓄势观察簇，`2026-06-18` 是 BUY_SIGNAL。下一步需要用 signal-history 或重建该日期候选缓存单独补证。

### `002384.SZSE`

`2026-03-20` 是龙回头 BUY_SIGNAL 并在 `2026-03-23` BUY_FILLED，`2026-03-25` support_stop 卖出；`2026-04-01` 是低位承接转强 BUY_SIGNAL，rank 3，score 97.57，但没有真实成交。`2026-06-03` 被聚合为低吸蓄势观察，`2026-06-09` 是 BUY_SIGNAL，`2026-06-15` BUY_FILLED。说明策略能识别 4/1 和 6/9 低吸/转强，但组合执行与持仓路径导致并非每个关键点都买。

### `002119.SZSE`

`2026-02-04/05` 连续龙回头 BUY_SIGNAL，`2026-02-06` BUY_FILLED，`2026-02-10` support_stop 卖出。更像重复/高位龙回头风险叠加卖点亏损，而不是低吸蓄势首启。此前重复龙回头硬拒实验已失败，因此先保留为诊断桶。

### `601179.SSE`

`2026-02-02/03/04` 都是龙回头 BUY_SIGNAL，`2026-02-03` 成交，`2026-02-06` support_stop 卖出；`2026-02-25` 仍显示龙回头 BUY_SIGNAL，low_suction_days=3，rank 48，未成交。当前口径支持用户判断：2/3 偏早，2/25 更像后续低吸蓄力点，但策略主标签仍归为龙回头，需要后续低位承接 subtype 细化。

### `600352.SSE`

`2026-03-10` 是 BUY_REJECTED，low_suction_days=5，`2026-03-11` 才 BUY_SIGNAL，`2026-03-12` BUY_FILLED，`2026-03-16` support_stop 卖出。说明“等待上拉趋势”已经被 timeline 部分表达，但 3/11 仍进入真实买入并失败，后续需要买点/市场上下文窄处罚审计。

### `002240.SZSE`

`2026-03-09`、`2026-03-11` 都是低位承接转强 BUY_SIGNAL，`2026-03-12` BUY_FILLED，`2026-03-19` support_stop 卖出。当前 #203 没有显示 3/13 旧 BUY；这支持读侧已不直接复用旧 persisted action，但这笔真实亏损仍属于弱市场假启动/买点质量问题样本。

### `002443.SZSE`

`2026-05-13` 是 BUY_SIGNAL，`2026-05-14` BUY_FILLED，`2026-06-04` support_stop 卖出。该样本仍是“买点可能可以，卖点/浮盈回撤有问题”的重点样本，应进入 sell_giveback/support_stop_context 审计，而不是直接修改买点。

## 决策

结论：

- 买点问题占比：`buy_point_bad` 26 / 214，约 `12.15%`；另有假启动路径和 no-follow-through 仍需继续细分。
- 卖点/回撤问题占比：`sell_giveback` 21 / 214，`sold_too_early` 48 / 214，合计约 `32.24%`。
- 满仓/替换问题占比：闭仓路径里 `replacement_bad` 80 / 214，约 `37.38%`；候选未成交的 `portfolio_capacity_miss` 还需要结合 candidate-trace/top20 missed candidates 做下一轮审计。
- 排除强势行情后 top20/top100 是否仍有效：固定持有后验显示仍为正，但样本小且资金流长期 unknown，不能作为默认规则修改依据。
- 当前不进入默认规则修改。可以继续执行 Task 5 的“是否允许默认关闭实验”评估，但本报告建议先补 candidate-trace/top20 missed candidates 和更长历史资金/主线覆盖。

## 验证

本轮已执行：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "fixed_horizon_outcome or current_strategy_return or current_strategy_trade or factor_audit_cache" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "setup_market_exit or buy_sell_problem" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_timeline or lifecycle_cluster" -q
uv run python -m compileall alphaagent/server/services/backtest/factor_audit.py alphaagent/server/services/backtest/engine.py alphaagent/server/services/backtest/queries.py
pnpm --dir frontend run build
```

API 抽样：

- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5` 返回 `#203/#194`。
- `GET /api/backtests/203/factor-audit?top_limit=100` 返回 ready。
- `GET /api/backtests/203/factor-audit?top_limit=100&exclude_strong_market=true` 返回 ready。
- `GET /api/backtests/203/setup-market-exit-audit?lookahead_days=10` 返回 ready，并包含 `buy_sell_problem_matrix`。
- `GET /api/backtests/203/strategy-timeline?vt_symbol=002384.SZSE` 返回 ready，并包含 `display_markers` / `buildup_cluster`。
