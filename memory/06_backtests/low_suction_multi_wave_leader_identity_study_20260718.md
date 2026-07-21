# AlphaAgent 第一浪后多浪真龙头点时识别研究

研究状态：`validation_failed`。
正式低吸胜率、收益、复利：`null`。本报告只评价身份识别，未读取交易收益。

## 样本口径

- 第一浪已重新创新高：`1270`。
- 第二浪已决：`1183`；继续创新高 `674`，终止 `509`。
- 第二浪右端未决并剔除：`87`。
- 点时特征完整：`1183`；不完整 `0`。
- 决策时点固定为第一浪回调后首次重新越过前峰的当日收盘。

## 时间块

| Block | 日期 | 决策日 | 样本 | 续浪 | 基准比例 |
| --- | --- | ---: | ---: | ---: | ---: |
| 1 | 2023-05-09..2023-10-18 | 82 | 203 | 100 | 49.2611% |
| 2 | 2023-10-19..2024-04-25 | 82 | 247 | 143 | 57.8947% |
| 3 | 2024-04-26..2024-10-24 | 82 | 229 | 130 | 56.7686% |
| 4 | 2024-10-25..2025-04-14 | 82 | 291 | 161 | 55.3265% |
| 5 | 2025-04-16..2025-11-03 | 82 | 213 | 140 | 65.7277% |

## 单变量方向

方向只由 block 1-3 决定，block 4-5 不允许反转方向。

| 特征 | 方向 | 开发 AUC | Block 4 AUC | Block 5 AUC | 两块同向 |
| --- | --- | ---: | ---: | ---: | --- |
| `candidate_pool_size` | `lower` | 0.5610 | 0.4737 | 0.5255 | `False` |
| `decision_distance_first_peak_pct` | `lower` | 0.5586 | 0.5540 | 0.4568 | `False` |
| `concept_turnover_expansion` | `higher` | 0.5463 | 0.5336 | 0.4181 | `False` |
| `member_recent_strong_5d_breadth_pct` | `higher` | 0.5440 | 0.5072 | 0.4863 | `False` |
| `stock_excess_since_anchor_pct` | `lower` | 0.5434 | 0.4890 | 0.5086 | `False` |
| `stock_gain_since_anchor_pct` | `lower` | 0.5397 | 0.5690 | 0.5011 | `True` |
| `first_wave_recovery_sessions` | `lower` | 0.5377 | 0.5694 | 0.4275 | `False` |
| `decision_return_5d_pct` | `lower` | 0.5336 | 0.5409 | 0.5043 | `True` |
| `decision_volume_ratio_prior5` | `higher` | 0.5328 | 0.4206 | 0.5245 | `False` |
| `causal_rank` | `lower` | 0.5310 | 0.4663 | 0.4237 | `False` |
| `first_trough_reclaimed_ma10` | `higher` | 0.5294 | 0.5283 | 0.4525 | `False` |
| `concept_return_5d_pct` | `higher` | 0.5283 | 0.4659 | 0.4965 | `False` |
| `decision_distance_ma20_pct` | `lower` | 0.5275 | 0.4821 | 0.6075 | `False` |
| `decision_return_10d_pct` | `lower` | 0.5272 | 0.4373 | 0.6067 | `False` |
| `first_trough_support_depth` | `lower` | 0.5268 | 0.5683 | 0.4529 | `False` |
| `decision_return_1d_pct` | `lower` | 0.5263 | 0.5038 | 0.4879 | `False` |
| `concept_return_10d_pct` | `higher` | 0.5234 | 0.4833 | 0.4068 | `False` |
| `member_positive_5d_breadth_pct` | `higher` | 0.5222 | 0.4589 | 0.5165 | `False` |
| `first_wave_pullback_depth_pct` | `lower` | 0.5211 | 0.5328 | 0.5622 | `True` |
| `first_trough_reclaimed_ma5` | `higher` | 0.5182 | 0.5220 | 0.4594 | `False` |
| `concept_gain_since_anchor_pct` | `lower` | 0.5165 | 0.5854 | 0.4825 | `False` |
| `first_wave_strong_days` | `lower` | 0.5146 | 0.5394 | 0.5534 | `True` |
| `member_main_rise_breadth_pct` | `lower` | 0.5144 | 0.5350 | 0.4913 | `False` |
| `first_wave_gain_pct` | `lower` | 0.5136 | 0.5433 | 0.5618 | `True` |
| `first_wave_median_volume_ratio` | `higher` | 0.5128 | 0.4702 | 0.4247 | `False` |
| `first_wave_max_volume_ratio` | `higher` | 0.5124 | 0.4707 | 0.4475 | `False` |
| `first_trough_volume_ratio` | `lower` | 0.5072 | 0.5191 | 0.5478 | `True` |
| `decision_turnover_expansion` | `lower` | 0.5053 | 0.5007 | 0.6093 | `True` |

## 冻结树

- 开发样本：`679`；基准续浪比例 `54.9337%`。
- 冻结叶：`member_recent_strong_5d_breadth_pct > 28.4161 and concept_return_5d_pct > 6.1770`。

| Leaf | 条件 | 样本 | 精度 | 召回 | 提升 | 状态 |
| ---: | --- | ---: | ---: | ---: | ---: | --- |
| 2 | member_recent_strong_5d_breadth_pct <= 28.4161 and decision_distance_first_peak_pct <= -1.4049 | 161 | 62.7329% | 27.0777% | 7.7992% | `eligible` |
| 3 | member_recent_strong_5d_breadth_pct <= 28.4161 and decision_distance_first_peak_pct > -1.4049 | 310 | 43.2258% | 35.9249% | -11.7079% | `precision_not_strictly_above_60pct,precision_lift_below_5pct_points` |
| 5 | member_recent_strong_5d_breadth_pct > 28.4161 and concept_return_5d_pct <= 6.1770 | 105 | 59.0476% | 16.6220% | 4.1139% | `precision_not_strictly_above_60pct,precision_lift_below_5pct_points` |
| 6 | member_recent_strong_5d_breadth_pct > 28.4161 and concept_return_5d_pct > 6.1770 | 103 | 73.7864% | 20.3753% | 18.8527% | `selected` |

## 验证结果

- 结论：`validation_failed`；身份门 `False`。
- 冻结叶验证样本：`101`；精度 `53.4653%`；召回 `17.9402%`。
- 整树验证 AUC：`0.4602`。
- 失败门：`block_4_precision_not_strictly_above_60pct, block_5_fewer_than_30_rows, block_5_precision_not_strictly_above_60pct`。

| Block | 叶样本 | 精度 | 召回 | 整树 AUC |
| ---: | ---: | ---: | ---: | ---: |
| 4 | 91 | 52.7473% | 29.8137% | 0.5030 |
| 5 | 10 | 60.0000% | 4.2857% | 0.4403 |

## 验证个股例子

以下股票都满足同一冻结叶；真阳性和假阳性同时存在，不能事后追加条件。

| 类型 | 股票 | 概念 | 决策日 | 强势宽度 | 概念 5 日 | 第一浪涨幅 | 回撤 | 支撑深度 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 续浪 | 中 关 村 `000931.SZSE` | 京津冀 | 2024-10-31 | 48.8889% | 8.5595% | 31.1111% | 15.0659% | 1.0000 |
| 续浪 | 步步高 `002251.SZSE` | 社区团购 | 2024-12-02 | 48.3871% | 12.7137% | 18.5075% | 13.3501% | 2.0000 |
| 续浪 | 税友股份 `603171.SSE` | 信创 | 2025-02-05 | 53.6842% | 8.4155% | 4.2748% | 24.7950% | 3.0000 |
| 续浪 | 南兴股份 `002757.SZSE` | VPN | 2025-02-13 | 66.6667% | 13.4991% | 10.3528% | 7.7568% | 1.0000 |
| 续浪 | 方正科技 `600601.SSE` | 光通信模块 | 2025-09-17 | 60.4167% | 9.6674% | 9.5575% | 6.3005% | 0.0000 |
| 终止 | 华控赛格 `000068.SZSE` | 低价股 | 2024-10-28 | 50.0000% | 14.3650% | 30.8442% | 21.5881% | 3.0000 |
| 终止 | 同方股份 `600100.SSE` | 参股券商 | 2024-11-08 | 38.3333% | 7.7182% | 2.2113% | 5.5288% | 2.0000 |
| 终止 | 小商品城 `600415.SSE` | 退税商店 | 2024-12-11 | 58.3333% | 7.1563% | 4.5678% | 7.9301% | 1.0000 |
| 终止 | 国新健康 `000503.SZSE` | SPD概念 | 2025-02-14 | 40.0000% | 7.3928% | 1.8364% | 7.5410% | 1.0000 |
| 终止 | 海南海药 `000566.SZSE` | 单抗概念 | 2025-07-17 | 31.0345% | 7.5298% | 2.6604% | 10.6707% | 3.0000 |

## 边界

- current concept memberships create survivorship bias
- identity precision is not low-suction trade win rate
- the 40-session episode horizon censors unresolved second waves
- daily close is the decision timestamp; no intraday execution is studied
- the old outer holdout is contaminated and is not reused

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-multi-wave-leader-identity-study --format markdown
```
