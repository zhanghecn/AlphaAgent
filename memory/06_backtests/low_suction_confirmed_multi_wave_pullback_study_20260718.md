# AlphaAgent 确认多浪后的回调低吸研究

研究状态：`no_confirmed_multi_wave_pullback_edge`；验证边界：`reused_history_not_validation`。
正式 Top3、低吸胜率、收益、复利：`null`。

## Coverage

- 因果信号：`2001`；股票 `516`；信号日 `486`。
- 次日开盘路径：`1924`；入场剔除 `77`。
- 冻结主组：`187`；闭合 `167`。

## Frozen Primary

- 第二个更高高点已经确认后才开始观察。
- 先出现点时可见的 5% 回调，再等收回最深已测试均线且收盘不低于前收。
- 信号日概念主升与个股结构均完整，并排除冻结的旭光高潮组合。
- D 收盘确认，D+1 开盘买；越过前峰或连续两日收盘低于 MA20 后收盘卖。

## Primary Result

- 闭合 `167`；成本后为正比例 `53.2934%`。
- 单笔均值/中位数 `0.4458%` / `0.9513%`；利润因子 `1.1186`。
- MAE 中位数 `-4.6325%`；稳定块 `1/5`；候选门 `False`。

## Funnel

| Stage | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `wave_3_stabilized` | 512 | 461 | 45.7701% | -0.2347% | 0.9386 | 51.1719% | 41 |
| `concept_main_rise_intact` | 224 | 202 | 50.9901% | 0.6553% | 1.1810 | 55.8036% | 17 |
| `stock_and_concept_intact` | 188 | 168 | 52.9762% | 0.3849% | 1.1014 | 56.3830% | 11 |
| `primary_non_climax` | 187 | 167 | 53.2934% | 0.4458% | 1.1186 | 56.6845% | 11 |

## Time Blocks

| Block | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `block_1` | 23 | 21 | 47.6190% | -1.9727% | 0.5765 | 52.1739% | 2 |
| `block_2` | 27 | 26 | 38.4615% | -1.3965% | 0.7062 | 48.1481% | 2 |
| `block_3` | 22 | 16 | 56.2500% | 1.3149% | 1.4489 | 45.4545% | 1 |
| `block_4` | 74 | 69 | 60.8696% | 1.4457% | 1.3947 | 66.2162% | 3 |
| `block_5` | 41 | 35 | 51.4286% | 0.8969% | 1.2937 | 53.6585% | 3 |

## Support

| Support | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `ma10` | 99 | 88 | 48.8636% | -0.4992% | 0.8915 | 50.5051% | 7 |
| `ma20` | 24 | 22 | 45.4545% | 1.2992% | 1.5087 | 54.1667% | 2 |
| `ma5` | 64 | 57 | 63.1579% | 1.5753% | 1.5386 | 67.1875% | 2 |

## Support By Block

下表只检查时间集中，不能改变冻结候选门。

| Support | Block | Entries | Closed | Positive | Mean net | PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `ma10` | `block_1` | 13 | 11 | 63.6364% | -0.9500% | 0.7696 |
| `ma10` | `block_2` | 15 | 14 | 14.2857% | -4.8301% | 0.2362 |
| `ma10` | `block_3` | 10 | 6 | 50.0000% | 0.9047% | 1.2587 |
| `ma10` | `block_4` | 41 | 38 | 52.6316% | 0.1400% | 1.0279 |
| `ma10` | `block_5` | 20 | 19 | 57.8947% | 1.2313% | 1.3938 |
| `ma20` | `block_1` | 6 | 6 | 16.6667% | -3.4454% | 0.2383 |
| `ma20` | `block_2` | 2 | 2 | 50.0000% | 2.4066% | 14.6478 |
| `ma20` | `block_3` | 3 | 1 | 100.0000% | 3.5055% | - |
| `ma20` | `block_4` | 8 | 8 | 75.0000% | 6.5519% | 4.9849 |
| `ma20` | `block_5` | 5 | 5 | 20.0000% | -2.2960% | 0.2614 |
| `ma5` | `block_1` | 4 | 4 | 50.0000% | -2.5760% | 0.5930 |
| `ma5` | `block_2` | 10 | 10 | 70.0000% | 2.6500% | 1.7639 |
| `ma5` | `block_3` | 9 | 9 | 55.5556% | 1.3450% | 1.4676 |
| `ma5` | `block_4` | 25 | 23 | 69.5652% | 1.8267% | 1.8590 |
| `ma5` | `block_5` | 16 | 11 | 54.5455% | 1.7706% | 1.6102 |

## Volume

| Volume | Entries | Closed | Positive | Mean net | PF | Higher high | False exits |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `contraction` | 76 | 67 | 47.7612% | 0.9928% | 1.3011 | 53.9474% | 6 |
| `expansion` | 18 | 17 | 64.7059% | 2.5019% | 1.9483 | 77.7778% | 2 |
| `explosion` | 26 | 20 | 45.0000% | -0.9917% | 0.7997 | 46.1538% | 3 |
| `normal` | 67 | 63 | 58.7302% | -0.2344% | 0.9439 | 58.2090% | 0 |

## Volume By Block

| Volume | Block | Entries | Closed | Positive | Mean net | PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `contraction` | `block_1` | 8 | 7 | 28.5714% | -2.9426% | 0.3732 |
| `contraction` | `block_2` | 11 | 11 | 36.3636% | -0.9314% | 0.7364 |
| `contraction` | `block_3` | 13 | 8 | 50.0000% | 0.0408% | 1.0137 |
| `contraction` | `block_4` | 27 | 26 | 61.5385% | 3.4878% | 2.1667 |
| `contraction` | `block_5` | 17 | 15 | 40.0000% | 0.4232% | 1.1335 |
| `expansion` | `block_1` | 1 | 1 | 0.0000% | -5.2147% | 0.0000 |
| `expansion` | `block_2` | 2 | 2 | 0.0000% | -10.8880% | 0.0000 |
| `expansion` | `block_3` | 2 | 2 | 100.0000% | 12.1412% | - |
| `expansion` | `block_4` | 10 | 10 | 70.0000% | 3.4200% | 2.9149 |
| `expansion` | `block_5` | 3 | 2 | 100.0000% | 5.5205% | - |
| `explosion` | `block_1` | 5 | 4 | 75.0000% | 1.6775% | 2.0675 |
| `explosion` | `block_2` | 4 | 3 | 66.6667% | 4.7238% | 2.2905 |
| `explosion` | `block_3` | 1 | 1 | 0.0000% | -5.8982% | 0.0000 |
| `explosion` | `block_4` | 9 | 7 | 28.5714% | -6.5818% | 0.1907 |
| `explosion` | `block_5` | 7 | 5 | 40.0000% | 2.2511% | 1.5952 |
| `normal` | `block_1` | 9 | 9 | 55.5556% | -2.4805% | 0.5823 |
| `normal` | `block_2` | 10 | 10 | 40.0000% | -1.8458% | 0.6447 |
| `normal` | `block_3` | 6 | 5 | 60.0000% | 0.4656% | 1.1362 |
| `normal` | `block_4` | 28 | 26 | 65.3846% | 0.8054% | 1.2089 |
| `normal` | `block_5` | 14 | 13 | 61.5385% | 0.2112% | 1.0679 |

## Cases

- 成功：拓维信息 `002261.SZSE`，第 3 浪，2023-06-07 `ma10`，成本后 `12.9263%`。
- 成功：同兴达 `002845.SZSE`，第 3 浪，2023-06-13 `ma10`，成本后 `3.3207%`。
- 成功：中京电子 `002579.SZSE`，第 3 浪，2023-06-16 `ma10`，成本后 `1.1298%`。
- 成功：万润科技 `002654.SZSE`，第 3 浪，2023-06-16 `ma10`，成本后 `3.0980%`。
- 成功：博杰股份 `002975.SZSE`，第 3 浪，2023-06-16 `ma20`，成本后 `6.4667%`。
- 失败：皖能电力 `000543.SZSE`，第 3 浪，2023-06-02 `ma10`，成本后 `-5.4870%`。
- 失败：常宝股份 `002478.SZSE`，第 3 浪，2023-06-05 `ma20`，成本后 `-6.2858%`。
- 失败：特发信息 `000070.SZSE`，第 3 浪，2023-06-14 `ma5`，成本后 `-8.7968%`。
- 失败：通富微电 `002156.SZSE`，第 3 浪，2023-06-19 `ma20`，成本后 `-8.9677%`。
- 失败：拓普集团 `601689.SSE`，第 3 浪，2023-06-29 `ma10`，成本后 `-6.1262%`。

## Boundaries

- all five chronological blocks were viewed in prior wave studies
- current concept membership is a survivorship proxy
- causal Top3 failed the prior absolute identity gate
- wave outcome and trade return never select a signal
- right-censored trades are excluded from return denominators
- descriptive positive share is not formal low-suction win rate

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-confirmed-multi-wave-pullback-study --format markdown
```
