# AlphaAgent 低吸 V2 主升周期研究

协议：`low-suction-research-v2`\
周期合同：`entry-gate-common-trend-sustain-v1`\
协议哈希：`sha256:3c96f32f6693b657e230ac5f63dfc8d392098b6d64a8b86f549d7082c36d878c`\
周期阶段：`selected_main_rise_definition`\
冻结定义：`breakout_trend`\
整体结论：`blocked_by_data_quality`，正式交易绩效：`null`

## Research Contract

本阶段只读取概念指数和宽基指数，不读取股票交易收益、低吸结果或锁定留出价格。

三种方案只比较进入条件：

- `trend_order`：`close > MA10 > MA20`，且 MA10、MA20 的 5 日斜率为正。
- `breakout_trend`：`trend_order` 成立，且概念收盘达到 20 日新高。
- `relative_trend`：`trend_order` 成立，且 10 日相对强度位于同日概念前 20%。

进入后统一由 `trend_order` 续期，连续失效 3 日后在第三日退出。持续率每个 concept
cycle 起点只计一次；假启动定义为已结束周期的共同趋势续期不足 3 日。次日持续率因
三日退出迟滞机械性为 100%，只作审计，不参与排序。

最初把三种进入条件同时当作每日续期条件，会机械性偏向最宽松的 `trend_order`；该输出
已拒绝，未写入正式选择。修正后的进入/续期分离合同在读取第二次结果前冻结。

## Data Split

- 可靠日期：`800`，`2023-03-28..2026-07-16`。
- 发现段：`640`，`2023-03-28..2025-11-17`。
- 锁定留出：`160`，`2025-11-18..2026-07-16`；只读取日期边界，未查询价格。
- 发现段概念指数：`260,548` 行、`433` 个概念。
- 宽基原始行：`1,920`；沪深300、中证500、中证1000日度等权复合。
- 输入指纹：`sha256:57eb502bfd6d4d32f8e0190b2ea59dd56bae9fdd88d8c50af4fe413803f8b2e4`。

## Discovery Metrics

| Definition | Cycle starts | Active states | 3-day persistence | False starts | Median cycle days | Monthly std |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `breakout_trend` | 5,134 | 81,731 | 98.53% | 5.35% | 12.0 | 2.25% |
| `relative_trend` | 4,074 | 55,812 | 93.26% | 14.55% | 11.0 | 9.23% |
| `trend_order` | 6,752 | 95,069 | 89.10% | 19.45% | 11.0 | 9.27% |

`breakout_trend` 的三日持续率在 5 个滚动折分别为 `97.54%`、`98.82%`、`97.81%`、
`99.27%`、`98.33%`，5/5 折均排名第一；假启动率分别为 `7.75%`、`4.03%`、
`7.23%`、`2.66%`、`6.49%`。

因此冻结的概念主升周期是：概念先满足多头排列和双均线上行，并在收盘确认 20 日新高；
进入后不要求每天继续创新高，只要共同趋势仍成立就保持主升状态，连续失效 3 日退出。

## Boundary

`98.53%` 是概念周期起点的三日状态持续率，不是股票交易胜率，更不是低吸收益。当前仍
缺三年点时概念成员和历史证券状态，无法公平选择当时的 Top3；分钟路径也尚未达到正式
研究门槛。因此低吸胜率、期望、复利、利润因子和最大回撤继续为 `null`，锁定留出未开启。

最终策略资格已按用户目标补充为：锁定留出胜率严格大于 `60%`、现金复利严格大于
`60%`，并至少在两个有足够样本的市场环境中分别达到胜率大于 `60%`；本报告的概念
持续率不能用于满足这些交易门槛。

## Reproduce

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-protocol --format json
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-cycle-study --format markdown
```
