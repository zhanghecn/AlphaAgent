# AlphaAgent 低吸支撑合同 v4 对照

版本：`causal-leader-pullback-support-contract-v4`；正式策略：`false`。

## 两种独立规则

- `cross_regime_deep_reclaim`：minimum required depth: wave 1 tests at least MA5 and later waves test at least MA10; a deeper MA10/MA20 test controls confirmation
- `cross_regime_exact_ma5_ma10`：exact required depth: wave 1 deepest tested support must be MA5 and later-wave deepest tested support must be MA10

## 总体与四仓

| 规则 | 成交 | 胜率 | 均值 | PF | 四仓复利 | 四仓回撤 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | 107 | 67.29% | +2.32% | 2.868 | +82.03% | -4.09% |
| cross_regime_exact_ma5_ma10 | 43 | 62.79% | +1.97% | 2.383 | +23.01% | -4.19% |

## 五个时间块

| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | block_1 | 22 | 72.73% | +3.77% | 5.893 |
| cross_regime_deep_reclaim | block_2 | 18 | 61.11% | +1.68% | 1.818 |
| cross_regime_deep_reclaim | block_3 | 19 | 68.42% | +1.57% | 2.151 |
| cross_regime_deep_reclaim | block_4 | 21 | 66.67% | +2.22% | 3.464 |
| cross_regime_deep_reclaim | block_5 | 27 | 66.67% | +2.15% | 2.720 |
| cross_regime_exact_ma5_ma10 | block_1 | 8 | 75.00% | +4.59% | 7.013 |
| cross_regime_exact_ma5_ma10 | block_2 | 7 | 42.86% | -0.76% | 0.740 |
| cross_regime_exact_ma5_ma10 | block_3 | 7 | 71.43% | +2.26% | 3.123 |
| cross_regime_exact_ma5_ma10 | block_4 | 10 | 70.00% | +2.54% | 4.049 |
| cross_regime_exact_ma5_ma10 | block_5 | 11 | 54.55% | +1.11% | 1.642 |

## 行情阶段

| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | rotation | 42 | 69.05% | +1.68% | 2.305 |
| cross_regime_deep_reclaim | warming | 65 | 66.15% | +2.73% | 3.256 |
| cross_regime_exact_ma5_ma10 | rotation | 18 | 66.67% | +1.10% | 1.791 |
| cross_regime_exact_ma5_ma10 | warming | 25 | 60.00% | +2.61% | 2.787 |

## 支撑路径

| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | ma10->ma10 | 29 | 65.52% | +2.40% | 2.875 |
| cross_regime_deep_reclaim | ma10->ma20 | 8 | 87.50% | +3.25% | 5.644 |
| cross_regime_deep_reclaim | ma5->ma10 | 44 | 68.18% | +2.25% | 2.634 |
| cross_regime_deep_reclaim | ma5->ma20 | 15 | 66.67% | +3.10% | 5.357 |
| cross_regime_deep_reclaim | ma5->ma5 | 11 | 54.55% | +0.63% | 1.368 |
| cross_regime_exact_ma5_ma10 | ma10->ma10 | 32 | 65.62% | +2.44% | 2.830 |
| cross_regime_exact_ma5_ma10 | ma5->ma5 | 11 | 54.55% | +0.63% | 1.368 |

## 年份

| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | 2024 | 19 | 68.42% | +3.82% | 5.284 |
| cross_regime_deep_reclaim | 2025 | 53 | 66.04% | +1.55% | 2.076 |
| cross_regime_deep_reclaim | 2026 | 35 | 68.57% | +2.65% | 3.368 |
| cross_regime_exact_ma5_ma10 | 2024 | 8 | 75.00% | +4.59% | 7.013 |
| cross_regime_exact_ma5_ma10 | 2025 | 21 | 61.90% | +1.03% | 1.643 |
| cross_regime_exact_ma5_ma10 | 2026 | 14 | 57.14% | +1.89% | 2.229 |

## 主要个股贡献

| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | 000962.SZSE|东方钽业 | 3 | 100.00% | +6.09% | - |
| cross_regime_deep_reclaim | 000833.SZSE|粤桂股份 | 2 | 50.00% | +0.54% | 59.615 |
| cross_regime_deep_reclaim | 002178.SZSE|延华智能 | 2 | 50.00% | +4.61% | 16.664 |
| cross_regime_deep_reclaim | 000158.SZSE|常山北明 | 1 | 100.00% | +9.81% | - |
| cross_regime_deep_reclaim | 000409.SZSE|云鼎科技 | 1 | 0.00% | -3.13% | 0.000 |
| cross_regime_deep_reclaim | 000533.SZSE|顺钠股份 | 1 | 100.00% | +9.77% | - |
| cross_regime_deep_reclaim | 000536.SZSE|华映科技 | 1 | 0.00% | -5.60% | 0.000 |
| cross_regime_deep_reclaim | 000554.SZSE|泰山石油 | 1 | 0.00% | -10.24% | 0.000 |
| cross_regime_deep_reclaim | 000572.SZSE|海马汽车 | 1 | 0.00% | -4.64% | 0.000 |
| cross_regime_deep_reclaim | 000603.SZSE|盛达资源 | 1 | 100.00% | +4.42% | - |

## 主要概念贡献

| 规则 | 分组 | 成交 | 胜率 | 均值 | PF |
| --- | --- | ---: | ---: | ---: | ---: |
| cross_regime_deep_reclaim | BK1010|磷化工 | 4 | 75.00% | +1.72% | 377.716 |
| cross_regime_deep_reclaim | BK1138|液冷概念 | 4 | 0.00% | -2.84% | 0.000 |
| cross_regime_deep_reclaim | BK0679|超导概念 | 3 | 100.00% | +6.09% | - |
| cross_regime_deep_reclaim | BK1145|机器人执行器 | 3 | 100.00% | +4.74% | - |
| cross_regime_deep_reclaim | BK0574|锂电池概念 | 2 | 100.00% | +8.76% | - |
| cross_regime_deep_reclaim | BK0577|核能核电 | 2 | 100.00% | +6.82% | - |
| cross_regime_deep_reclaim | BK0637|互联网金融 | 2 | 100.00% | +5.87% | - |
| cross_regime_deep_reclaim | BK0877|PCB | 2 | 100.00% | +9.78% | - |
| cross_regime_deep_reclaim | BK0896|白酒 | 2 | 50.00% | +1.48% | 3.505 |
| cross_regime_deep_reclaim | BK0925|北交所概念 | 2 | 50.00% | -2.69% | 0.193 |

## 参考个股波段

| 规则 | 个股 | 龙头区间 | 波段 | 信号 | 成交 |
| --- | --- | --- | ---: | ---: | ---: |
| cross_regime_deep_reclaim | 东山精密 `002384.SZSE` | 2024-06-18..2026-06-12 | 116 | 0 | 0 |
| cross_regime_deep_reclaim | 金安国纪 `002636.SZSE` | 2025-07-09..2026-07-03 | 19 | 0 | 0 |
| cross_regime_deep_reclaim | 亨通光电 `600487.SSE` | 2024-10-11..2026-03-16 | 75 | 8 | 1 |
| cross_regime_exact_ma5_ma10 | 东山精密 `002384.SZSE` | 2024-06-18..2026-06-12 | 116 | 0 | 0 |
| cross_regime_exact_ma5_ma10 | 金安国纪 `002636.SZSE` | 2025-07-09..2026-07-03 | 19 | 0 | 0 |
| cross_regime_exact_ma5_ma10 | 亨通光电 `600487.SSE` | 2024-10-11..2026-03-16 | 75 | 8 | 1 |

### 参考个股逐浪

| 规则 | 个股 | 浪次 | 区间 | 最深支撑 | 新高 | 终态 |
| --- | --- | ---: | --- | --- | --- | --- |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-17..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-17..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-12 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-11-05..2024-11-18 | - | False | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-10-31..2024-11-04 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2024-11-05..2024-11-19 | - | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-03-18..2025-03-26 | ma20 | False | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-06-17..2024-06-21 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2024-06-24..2024-06-26 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2024-06-27..2024-07-02 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2024-07-03..2024-07-04 | - | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-06-18..2025-06-26 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-10-20 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-14..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-12 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-10..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-12 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-07-15..2025-07-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-07-30..2025-11-19 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-12-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-03-13..2026-03-24 | ma5 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-12-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-03-13..2026-03-23 | ma5 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-16..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-10 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-13..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-07-06 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-14..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-02-26..2026-03-09 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-03-13..2026-03-19 | ma5 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-06-24..2026-03-09 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-07-03..2026-03-12 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-09..2026-03-19 | ma5 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-30..2025-12-11 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-06-16..2025-06-26 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-10-16 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-05-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-05-21..2026-03-12 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2026-03-23 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-12-11 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-05-12..2025-06-26 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-05-21..2025-07-02 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-09-05 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-06-18..2025-06-26 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-11-24 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-06-25..2025-07-02 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-30..2025-11-24 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-12-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-03-13..2026-03-23 | ma5 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-06-17..2024-06-21 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2024-06-24..2024-06-26 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2024-06-27..2024-07-02 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2024-07-03..2024-07-04 | - | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-06-18..2025-06-26 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-10-16 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2025-05-12..2025-06-26 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2025-05-21..2025-07-02 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 6 | 2025-07-30..2025-11-25 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-13..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-16..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2026-04-17..2026-04-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-10-22..2024-10-24 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2024-10-25..2024-10-28 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 3 | 2024-10-29..2024-11-04 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 东山精密 | 4 | 2024-11-05..2024-11-18 | - | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-10-30..2024-11-04 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2024-11-05..2024-11-19 | - | True | terminated |
| cross_regime_deep_reclaim | 东山精密 | 1 | 2024-10-30..2024-11-04 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 东山精密 | 2 | 2024-11-05..2024-11-18 | - | True | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 1 | 2025-08-15..2026-03-23 | ma10 | False | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 2 | 2025-08-26..2026-03-17 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 3 | 2025-08-28..2025-11-07 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 4 | 2025-11-10..2026-01-14 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 1 | 2026-06-05..2026-06-17 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 2 | 2026-06-18..2026-06-23 | ma5 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 3 | 2026-06-24..2026-06-29 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 4 | 2026-06-30..2026-07-06 | - | True | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 1 | 2025-07-03..2025-08-25 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 2 | 2025-08-26..2025-08-27 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 3 | 2025-08-28..2025-10-16 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 1 | 2025-10-29..2025-10-30 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 2 | 2025-10-31..2025-11-05 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 3 | 2025-11-06..2025-11-07 | - | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 4 | 2025-11-10..2025-11-18 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 金安国纪 | 1 | 2025-08-15..2025-10-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 2 | 2025-08-26..2025-11-05 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 3 | 2025-08-28..2025-11-07 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 金安国纪 | 4 | 2025-11-10..2025-12-15 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2026-02-06 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-20 | ma10 | False | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-21 | ma10 | False | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-09-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-11-24 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-09-04 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-23..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-19 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-25..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-18 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-02 | - | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-30..2026-01-29 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-05 | - | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-19 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2024-10-08..2024-10-11 | ma5 | False | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-21 | ma10 | False | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-22..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-02 | - | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-09-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-11-20 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-20..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2026-02-06 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-05 | - | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-09-04 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2026-01-05..2026-01-22 | - | False | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2026-01-26..2026-01-29 | ma5 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-24 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-09-18..2025-09-30 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-10-09..2025-10-20 | ma10 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_deep_reclaim | 亨通光电 | 1 | 2025-08-08..2026-01-29 | ma10 | False | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 2 | 2025-08-28..2026-02-06 | ma20 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_deep_reclaim | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-17..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-17..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-12 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-11-05..2024-11-18 | - | False | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-10-31..2024-11-04 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2024-11-05..2024-11-19 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-03-18..2025-03-26 | ma20 | False | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-06-17..2024-06-21 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2024-06-24..2024-06-26 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2024-06-27..2024-07-02 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2024-07-03..2024-07-04 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-06-18..2025-06-26 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-10-20 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-14..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-12 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-10..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-12 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-07-15..2025-07-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-07-30..2025-11-19 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-12-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-03-13..2026-03-24 | ma5 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-12-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-03-13..2026-03-23 | ma5 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-16..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-10 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-13..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-07-06 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-14..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-02-26..2026-03-09 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-03-13..2026-03-19 | ma5 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-06-24..2026-03-09 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-07-03..2026-03-12 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-09..2026-03-19 | ma5 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-30..2025-12-11 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-06-16..2025-06-26 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-10-16 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-05-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-05-21..2026-03-12 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2026-03-23 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-12-11 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-05-12..2025-06-26 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-05-21..2025-07-02 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-09-05 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-06-18..2025-06-26 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-11-24 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-06-25..2025-07-02 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-30..2025-11-24 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-12-12..2026-03-09 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-03-10..2026-03-12 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-03-13..2026-03-23 | ma5 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-06-17..2024-06-21 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2024-06-24..2024-06-26 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2024-06-27..2024-07-02 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2024-07-03..2024-07-04 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-06-18..2025-06-26 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-06-27..2025-07-02 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-10-16 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2025-05-12..2025-06-26 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2025-05-21..2025-07-02 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2025-07-03..2025-07-08 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2025-07-09..2025-07-11 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 5 | 2025-07-14..2025-07-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 6 | 2025-07-30..2025-11-25 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-13..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-16..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2026-04-17..2026-04-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2026-05-06..2026-05-26 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2026-05-27..2026-06-02 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-10-22..2024-10-24 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2024-10-25..2024-10-28 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 3 | 2024-10-29..2024-11-04 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 4 | 2024-11-05..2024-11-18 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-10-30..2024-11-04 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2024-11-05..2024-11-19 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 东山精密 | 1 | 2024-10-30..2024-11-04 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 东山精密 | 2 | 2024-11-05..2024-11-18 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 1 | 2025-08-15..2026-03-23 | ma10 | False | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 2 | 2025-08-26..2026-03-17 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 3 | 2025-08-28..2025-11-07 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 4 | 2025-11-10..2026-01-14 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 1 | 2026-06-05..2026-06-17 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 2 | 2026-06-18..2026-06-23 | ma5 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 3 | 2026-06-24..2026-06-29 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 4 | 2026-06-30..2026-07-06 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 1 | 2025-07-03..2025-08-25 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 2 | 2025-08-26..2025-08-27 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 3 | 2025-08-28..2025-10-16 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 1 | 2025-10-29..2025-10-30 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 2 | 2025-10-31..2025-11-05 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 3 | 2025-11-06..2025-11-07 | - | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 4 | 2025-11-10..2025-11-18 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 1 | 2025-08-15..2025-10-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 2 | 2025-08-26..2025-11-05 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 3 | 2025-08-28..2025-11-07 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 金安国纪 | 4 | 2025-11-10..2025-12-15 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2026-02-06 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-20 | ma10 | False | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-21 | ma10 | False | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-09-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-11-24 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-09-04 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-23..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-19 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-25..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-18 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-02 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-30..2026-01-29 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-05 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-19 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2024-10-08..2024-10-11 | ma5 | False | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-21 | ma10 | False | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-22..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-02 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-12-17..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-09-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-11-20 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-20..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2026-02-06 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-05 | - | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-09-04 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2026-01-05..2026-01-22 | - | False | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2026-01-26..2026-01-29 | ma5 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2026-01-30..2026-02-06 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-24 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-09-18..2025-09-30 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-10-09..2025-10-20 | ma10 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2025-08-27 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2025-09-05 | ma20 | True | terminated |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 1 | 2025-08-08..2026-01-29 | ma10 | False | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2 | 2025-08-28..2026-02-06 | ma20 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 3 | 2026-02-09..2026-02-25 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 4 | 2026-02-26..2026-03-10 | ma10 | True | pullback |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 5 | 2026-03-11..2026-03-23 | ma20 | True | terminated |

### 参考个股已选成交

| 规则 | 个股 | 买入 | 支撑 | 卖出 | 原因 | 净收益 |
| --- | --- | --- | --- | --- | --- | ---: |
| cross_regime_deep_reclaim | 亨通光电 | 2026-02-24 | ma10->ma10 | 2026-02-25 | d1_loss_stop | -4.77% |
| cross_regime_exact_ma5_ma10 | 亨通光电 | 2026-02-24 | ma10->ma10 | 2026-02-25 | d1_loss_stop | -4.77% |

## 资格结论

- `cross_regime_deep_reclaim`：历史代理门=`True`；失败门=`none`；正式阻断=`strict_historical_membership_missing, same_close_execution_is_research_proxy`。
- `cross_regime_exact_ma5_ma10`：历史代理门=`False`；失败门=`closed_trades<100, stable_time_blocks<3, cash_compound<=60pct, qualified_market_phases<2`；正式阻断=`strict_historical_membership_missing, same_close_execution_is_research_proxy`。

## 边界

- The exact-support result is produced by an independent state-machine replay, not a post-hoc trade filter.
- The deep-reclaim contract permits MA10/MA20 after the minimum required support and is not an exact MA5/MA10 rule.
- Current concept memberships are replayed backward and retain survivorship bias.
- D close simultaneously confirms and prices the signal, so the result remains a same-close research proxy.
- All five chronological blocks have already been viewed and are not a fresh holdout.

## Reproduce

```bash
docker compose --profile research run --rm -T --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare alphaagent-research python -m alphaagent.server.services.low_suction.cli v4-support-contract-study --format json
```
