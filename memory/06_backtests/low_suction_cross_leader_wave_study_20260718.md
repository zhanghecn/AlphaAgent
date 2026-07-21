# AlphaAgent 跨龙头主升波浪与均线低吸研究

结论边界：动态 cohort 使用当前成员生存偏差代理，正式 Top3 尚未通过身份门。
正式胜率、收益、复利：`null`。以下比例只描述固定历史代理路径。

## Coverage

- 动态非重叠 episode：`1977`；股票：`1278`；锚点日期：`235`。
- 波浪：`4443`；已决波浪：`4167`；再创新高：`2466`；终止：`1701`。
- 已决波浪描述性续浪比例：`59.1793%`。
- 支撑路径：`8184`；同一 episode 内不同均线可以重叠，不能当作独立账户交易复利。

## Primary Non-overlapping Path

- 每浪最早且顺序不重叠：`4274` 笔，闭合 `4024` 笔；成本后为正比例 `43.1412%`。
- 单笔均值/中位数：`-1.4416%` / `-2.2885%`；MAE 中位数 `-5.8600%`。
- 单 episode 顺序复合收益中位数：`-4.5249%`；正复合 episode 比例 `27.0612%`。
- 两日跌破 MA20 后退出、后来又创新高：`584` 笔。

## MA Support

| Support | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ma10` | 1798 | 2862 | 40.6359% | 55.3110% | -3.2303% | -5.9304% | 410 |
| `ma20` | 1977 | 2827 | 29.6427% | 42.5186% | -2.3711% | -4.2236% | 584 |
| `ma5` | 1399 | 2031 | 48.5475% | 61.7922% | -0.6058% | -6.8389% | 205 |

## Pullback Volume

| Volume | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `contraction` | 1680 | 3530 | 38.3853% | 50.8499% | -2.5628% | -5.0917% | 566 |
| `expansion` | 624 | 683 | 40.8492% | 54.4656% | -1.9086% | -4.9422% | 106 |
| `explosion` | 681 | 771 | 38.2620% | 52.9183% | -2.8408% | -5.9937% | 102 |
| `normal` | 1501 | 2736 | 38.6696% | 53.5453% | -2.3914% | -5.4434% | 425 |

## Wave Maturity

| Wave | Episodes | Resolved | Continued | Terminal | Continuation share |
| --- | ---: | ---: | ---: | ---: | ---: |
| `wave_1` | 1977 | 1977 | 1270 | 707 | 64.2387% |
| `wave_2` | 1270 | 1183 | 674 | 509 | 56.9738% |
| `wave_3` | 674 | 598 | 326 | 272 | 54.5151% |
| `wave_4_plus` | 326 | 409 | 196 | 213 | 47.9218% |

## Primary Path By Wave

| Wave | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `wave_1` | 1949 | 1949 | 44.4330% | 63.7250% | -1.7964% | -5.4167% | 346 |
| `wave_2` | 1220 | 1140 | 41.0526% | 57.4561% | -2.9450% | -6.1022% | 157 |
| `wave_3` | 640 | 567 | 44.2681% | 55.9083% | -2.0868% | -6.2827% | 55 |
| `wave_4_plus` | 300 | 368 | 41.0326% | 50.2717% | -3.3538% | -6.4532% | 26 |

## Xuguang Climax Test

固定条件为涨幅至少 50%、至少 3 个接近涨停日、最大量比至少 3x，三项必须同时成立。

| Climax | Episodes | Resolved | Continued | Terminal | Continuation share |
| --- | ---: | ---: | ---: | ---: | ---: |
| `False` | 1960 | 4132 | 2451 | 1681 | 59.3175% |
| `True` | 38 | 35 | 15 | 20 | 42.8571% |

## Chronological Blocks

| Block | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `block_1` | 313 | 573 | 35.6021% | 49.9127% | -3.8559% | -5.8414% | 71 |
| `block_2` | 325 | 713 | 42.6367% | 60.7293% | -2.5256% | -5.6330% | 106 |
| `block_3` | 462 | 799 | 32.5407% | 54.6934% | -4.2501% | -6.2992% | 161 |
| `block_4` | 517 | 1173 | 50.4689% | 62.9156% | 0.2902% | -6.4368% | 132 |
| `block_5` | 360 | 766 | 49.0862% | 65.9269% | -0.6060% | -4.6726% | 114 |

## Retrospective Leader Diagnosis

该分组需要完整 40 日后才知道，只用于解释身份问题，不能成为实时过滤器。

| Outcome class | Episodes | Closed | Positive share | Higher-high share | Median net | Median MAE | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `confirmed_multi_wave` | 674 | 2245 | 59.8218% | 80.7127% | 2.5129% | -4.5397% | 387 |
| `no_continuation` | 707 | 707 | 2.8289% | 0.0000% | -7.2907% | -8.9560% | 0 |
| `single_continuation` | 596 | 1072 | 34.7948% | 54.7575% | -3.9463% | -6.4276% | 197 |

## Reference Leaders

参考个股已经被查看过，只作逐股解释，不与动态 cohort 混合。

| Stock | Anchor | Waves | Resolved | Continued | Terminal | Entries | Positive | Median net | Median MAE |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 上海建工 `600170.SSE` | 2025-09-15 | 1 | 1 | 0 | 1 | 3 | 0 | -9.1231% | -11.0769% |
| 金安国纪 `002636.SZSE` | 2026-01-15 | 16 | 16 | 15 | 1 | 22 | 17 | 5.6506% | -3.0909% |
| 生益科技 `600183.SSE` | 2026-05-13 | 6 | 6 | 5 | 1 | 7 | 5 | 3.4715% | -8.2702% |

## Hypothesis Results

- `ma20_vs_ma5`：`mixed`；`ma20_has_lower_median_mae=True, ma20_has_higher_median_net=False, ma20_entries=2942, ma5_entries=2204`。
- `normal_vs_explosion_volume`：`supported`；`normal_has_higher_median_net=True, normal_has_higher_higher_high_share=True, normal_entries=2894, explosion_entries=825`。
- `two_close_ma20_exit`：`false_exits_observed`；`false_exit_paths_before_later_higher_high=1199, primary_path_false_exits_before_later_higher_high=584`。
- `xuguang_climax_terminal_risk`：`supported`；`climax_has_lower_continuation_share=True, climax_resolved_waves=35, non_climax_resolved_waves=4132`。

## Boundaries

- 候选身份、均线位置、回踩量能和买入日字段只读当日及以前。
- 后来再创新高、终止浪和收益是事后标签，不参与 episode 选择。
- 动态 episode 同股 40 个交易时段不重叠；均线支撑路径仍可能重叠。
- 本轮未读取分钟线、金银环境或旧低吸结果，不能回答 D+1 10:30 精确成交。

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-cross-leader-wave-study --format markdown
```
