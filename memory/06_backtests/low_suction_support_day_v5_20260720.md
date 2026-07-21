# AlphaAgent 主升龙头支撑日低吸 V5

规则版本：`causal-leader-support-day-v5`
开发期冻结规则：`none`
历史代理门：`False`
正式策略：`false`

## 开发期规则冻结

| 规则 | D1 成交 | 胜率 | 均值 | PF | 稳定块 | 四仓复利 | 入围 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| support_day_exact_hold | 2251 | 38.6051% | -0.8088% | 0.6007 | 0 | -84.7056% | False |
| support_day_exact_bullish_reversal | 753 | 36.5206% | -0.8867% | 0.5827 | 0 | -74.1565% | False |
| support_day_ma5_then_ma10_band_reclaim | 1621 | 37.0759% | -0.8943% | 0.5869 | 0 | -82.5899% | False |

## 开发期高胜率分组

| 规则 | 特征 | 分组 | 成交 | 胜率 | 均值 | PF | 正向块 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| - | - | 无满足稳定性门的分组 | 0 | - | - | - | 0 |

## 开发期低胜率分组

| 规则 | 特征 | 分组 | 成交 | 胜率 | 均值 | PF | 负向块 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| support_day_exact_bullish_reversal | dynamic_rank_group+volume_class+signal_return_group | rank_1|normal|negative | 31 | 19.3548% | -3.0770% | 0.1131 | 3 |
| support_day_ma5_then_ma10_band_reclaim | wave_group+dynamic_rank_group+signal_return_group | wave_2|rank_3|0_to_3 | 35 | 20.0000% | -1.4131% | 0.2956 | 3 |
| support_day_ma5_then_ma10_band_reclaim | dynamic_rank_group+volume_class+signal_return_group | rank_3|contraction|negative | 60 | 21.6667% | -1.7180% | 0.2713 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+dynamic_rank_group | negative|rank_1 | 65 | 23.0769% | -2.4860% | 0.2054 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+dynamic_rank_group | 3_to_6|rank_3 | 35 | 25.7143% | -1.7446% | 0.2287 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+close_location_group | negative|middle | 130 | 26.9231% | -2.1210% | 0.2209 | 3 |
| support_day_ma5_then_ma10_band_reclaim | wave_group+dynamic_rank_group+signal_return_group | wave_2|rank_2|0_to_3 | 39 | 28.2051% | -1.1100% | 0.5277 | 3 |
| support_day_exact_bullish_reversal | wave_group+dynamic_rank_group+signal_return_group | wave_2|rank_3|0_to_3 | 46 | 28.2609% | -0.7323% | 0.5308 | 3 |
| support_day_ma5_then_ma10_band_reclaim | dynamic_rank_group+volume_class+signal_return_group | rank_1|expansion|negative | 77 | 28.5714% | -1.8718% | 0.3408 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+volume_class | negative|normal | 73 | 28.7671% | -2.0081% | 0.3037 | 3 |
| support_day_ma5_then_ma10_band_reclaim | signal_return_group+wave_group | negative|wave_2 | 52 | 28.8462% | -1.3530% | 0.4614 | 3 |
| support_day_ma5_then_ma10_band_reclaim | wave_group+support_geometry+volume_class | wave_2|ma5_ma10_band_reclaim|contraction | 79 | 29.1139% | -1.3617% | 0.4227 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+active_direction | negative|GOLD | 183 | 29.5082% | -1.5976% | 0.3418 | 3 |
| support_day_exact_bullish_reversal | signal_return_group | negative | 189 | 29.6296% | -1.6134% | 0.3380 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+wave_group | negative|wave_2 | 54 | 29.6296% | -1.2193% | 0.4388 | 3 |
| support_day_ma5_then_ma10_band_reclaim | signal_return_group+dynamic_rank_group | 0_to_3|rank_3 | 127 | 29.9213% | -1.0549% | 0.4587 | 3 |
| support_day_ma5_then_ma10_band_reclaim | signal_return_group+wave_group | 0_to_3|wave_2 | 137 | 29.9270% | -1.0128% | 0.5591 | 3 |
| support_day_exact_hold | signal_return_group+close_location_group | 3_to_6|middle | 50 | 30.0000% | -1.4097% | 0.5065 | 3 |
| support_day_exact_bullish_reversal | signal_return_group+wave_group | negative|wave_1 | 106 | 30.1887% | -1.7118% | 0.2960 | 3 |
| support_day_exact_hold | signal_return_group+wave_group | 0_to_3|wave_2 | 159 | 30.1887% | -1.1840% | 0.4885 | 3 |

## 冻结行情策略


## 最终 D+1 与四仓

- 成交：`0`
- 胜率：`-`
- 单笔均值：`-`
- PF：`-`
- 四仓复利：`-`
- 四仓最大回撤：`-`

## 资格结论

- 失败门：`no_development_rule_nominated`
- 正式阻断：`strict_historical_membership_missing, executable_preclose_price_missing`

## 参考龙头

- 东山精密 `002384.SZSE`：campaign `32`，波次 `116`，信号 `154`，成交 `0`。
- 金安国纪 `002636.SZSE`：campaign `5`，波次 `19`，信号 `8`，成交 `0`。
- 亨通光电 `600487.SSE`：campaign `26`，波次 `75`，信号 `107`，成交 `0`。

## 研究边界

- Only blocks 1-3 can nominate the rule and freeze the environment map.
- Blocks 4-5 are evaluated once for the frozen rule and never create new filters.
- Winner/loser and named-stock comparisons are attribution only.
- Current concept membership replay retains survivorship bias.
- The D close is a research price proxy until a pre-close executable price exists.

## Reproduce

```bash
docker compose --profile research run --rm -T --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace -e PYTHONPATH=/workspace:/app/third_party/akshare alphaagent-research python -m alphaagent.server.services.low_suction.cli v5-support-day-study --format json
```
