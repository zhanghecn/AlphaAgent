# Quant Feature Table Validation Report - 2026-06-19

## Baseline

- Product baseline API ids: `[203, 194]`
- Strategy: `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26..2026-06-18`
- Return: `+82.99%`
- Max drawdown: `-15.59%`
- Baseline reason: `implicit_common_start_date`
- Baseline warning: `存在更长起点的默认参数回测，当前按同结束日中最常见起点选择产品基线。`

No default buy/sell rule changed in this validation slice.

## Candidate Signal Feature Audit

- Factor audit status: `ready`
- Candidate coverage: `100` / original `100`
- Excluding strong-market candidate coverage: `50`, excluded `50`

| Setup | Samples | Win | Avg | PF |
| --- | --- | --- | --- | --- |
| dragon_pullback | 45 | 71.11% | +66.48% | 43.72 |
| low_position_reclaim | 15 | 86.67% | +25.38% | 49.07 |
| unknown | 40 | 52.50% | +5.99% | 3.67 |

## Candidate Execution Attribution

- Top execution rank: `20`
- Candidate count: `22`
- Filled / missed: `10` / `12`
- Missed positive 20d count: `8`
- Missed average 20d return: `+122.34%`
- Missed opportunity rows: `44`
- Same-symbol pseudo opportunities: `0`

| Subreason | Samples | Missed | Win | Avg 20d |
| --- | --- | --- | --- | --- |
| none | 10 | 0 | 70.00% | +45.66% |
| already_theoretical_holding | 9 | 9 | 77.78% | +162.45% |
| planned_not_ordered | 3 | 3 | 33.33% | +2.01% |

Conclusion: capacity and plan-chain attribution is now visible. The current top20 sample still has high missed-candidate opportunity, but the audit no longer counts an already-held same symbol as a rotation opportunity.

## Exit Path And Replacement Quality

- Closed trade sample: `214`
- Replacement trades: `214`
- Bad / strong replacements: `98` / `42`
- Average replacement return: `+2.22%`
- Average replacement delta: `-1.03%`

| Problem | Trades | Win | Avg | Bad repl |
| --- | --- | --- | --- | --- |
| 替换交易变差 | 80 | 43.75% | +7.17% | 66 |
| 卖早反弹 | 48 | 6.25% | -6.85% | 21 |
| 买点问题 | 26 | 0.00% | -7.12% | 0 |
| 趋势赢家 | 26 | 100.00% | +29.47% | 0 |
| 卖点回撤问题 | 21 | 0.00% | -6.43% | 11 |
| 未归类 | 13 | 38.46% | -1.39% | 0 |

| Support context | Trades | Win | Avg | Sold rebound |
| --- | --- | --- | --- | --- |
| 真失败启动止损 | 49 | 2.04% | -7.84% | 0 |
| 止损后反弹 | 41 | 4.88% | -6.94% | 41 |
| 有承接但后续破支撑 | 14 | 7.14% | -5.36% | 0 |
| 浮盈回吐后破位 | 13 | 0.00% | -8.87% | 0 |
| 高浮盈后止损又反弹 | 7 | 14.29% | -6.30% | 7 |
| 其他支撑止损 | 1 | 0.00% | -5.78% | 0 |

Conclusion: sell-side problems remain mixed. `support_stop` must stay split into failed launch, rebound after stop, follow-through lost support and float-profit giveback; a single broad sell rule is still not supported.

## Market Context Validation

- Excluding strong-market trades: `195`
- Excluding strong-market win rate / avg return: `33.33%` / `+3.46%`
- Fund-flow insufficient-data count: `214`

| Market | Trades | Win | Avg | Bad repl |
| --- | --- | --- | --- | --- |
| 震荡轮动 | 142 | 33.10% | +2.37% | 73 |
| 假强势 | 53 | 33.96% | +6.38% | 18 |
| 普涨强势 | 19 | 21.05% | -0.12% | 7 |

Conclusion: market context is now exposed, but fund-flow long-history coverage is still insufficient for historical trading rules. Market/mainline data remains audit-only.

## Factor Interaction And Opportunity Cost

- Removed-winner proxy count/sum: `47` / `+3733.97%`
- Avoided-loser proxy count/sum: `22` / `-147.16%`
- Note: 这里是候选后验机会成本基线；具体实验的 removed/added/replacement delta 必须在实验对比报告中按真实组合路径计算。

| Factor | Samples | Win | Avg | PF |
| --- | --- | --- | --- | --- |
| unknown|strong_broad | 25 | 40.00% | +7.57% | 3.30 |
| dragon_pullback|choppy_rotation | 21 | 71.43% | +73.45% | 35.90 |
| dragon_pullback|strong_broad | 18 | 61.11% | +34.52% | 25.05 |
| unknown|choppy_rotation | 12 | 66.67% | +3.98% | 7.37 |
| low_position_reclaim|strong_broad | 7 | 85.71% | +13.27% | 20.30 |
| dragon_pullback|false_bull | 6 | 100.00% | +137.96% | 999.00 |
| low_position_reclaim|choppy_rotation | 6 | 83.33% | +15.88% | 31.70 |
| unknown|false_bull | 3 | 100.00% | +0.92% | 999.00 |

Conclusion: the current interaction table is enough for audit and UI comparison, but experiment-level removed/added trade opportunity cost still must be computed per experiment before any promotion.

## Focus Symbol Smoke

| Symbol | Status | Signals | BUY | Best date | Best score | Timeline | Segments |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 东山精密 002384.SZSE | ready | 16 | 16 | 2026-03-20 | 98.53 | 36 | 14 |
| 康强电子 002119.SZSE | ready | 21 | 21 | 2026-02-05 | 100.00 | 17 | 8 |
| 金洲管道 002443.SZSE | ready | 20 | 20 | 2026-05-13 | 98.20 | 21 | 10 |
| 中国西电 601179.SSE | ready | 15 | 15 | 2026-02-03 | 99.34 | 20 | 10 |
| 浙江龙盛 600352.SSE | ready | 16 | 16 | 2026-03-10 | 95.68 | 22 | 10 |
| 盛新锂能 002240.SZSE | ready | 19 | 19 | 2025-11-06 | 100.00 | 28 | 11 |
| 贵州三力 603439.SSE | ready | 9 | 9 | 2026-06-17 | 91.94 | 16 | 3 |

## Promotion Decision

Do not promote any rule from this report. The validation added visibility and fixed an attribution error, but it does not yet prove a default trading-rule improvement. The next step is to run one narrow default-off experiment only if it can be tied to a specific bucket and checked against replacement quality and excluding-strong-market performance.

## Verification

- API health: ok
- Baseline API: ids `[203, 194]`, `baseline_only=true` excludes experiments
- Factor audit API: ready, same-symbol missed opportunity rows `0`
- Setup-market-exit audit API: ready, `exit_path_replacement_quality` and `market_context_validation` present
- Strategy timeline API for `002384.SZSE`: ready, lifecycle segments present
