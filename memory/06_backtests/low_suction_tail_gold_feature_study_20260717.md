# AlphaAgent 金手指龙头尾盘低吸特征研究

结论：`no_stable_gold_tail_feature_group`\
正式规则/绩效：`null/null`\
成交：D 14:50 完成观察，14:55 bar 开盘买；D+1 10:30 后首个可执行代理为 10:35 bar 开盘卖。
固定母样本：`active_direction=GOLD`，状态在 `D-1 close` 已知；SILVER 不进入分钟特征、交易账本或结果分组。

## 覆盖

候选/完整双日路径/特征：`1220/1220/1220`\
股票/日期：`278/75`\
闭合/成功/失败：`1072/383/689`\
拒绝/未闭合：`146/2`
筛选前候选/金手指候选：`1396/1220`\
方向候选数：`GOLD=1220, SILVER=176`\
金手指候选占比：`87.3926%`

### 原始时间块覆盖

| Block | Feature rows | Dates |
| --- | ---: | ---: |
| `block_1` | 387 | 19 |
| `block_2` | 379 | 19 |
| `block_3` | 276 | 19 |
| `block_4` | 178 | 18 |
| `block_5` | 0 | 0 |

警示：金手指在原 `block_5` 没有候选，validation 实际只来自 `block_4`，不构成两个后段时间块确认。

### 未成交与未闭合原因

| Reason | Count |
| --- | ---: |
| `entry_limit_up_queue_unknown_without_l2` | 146 |
| `exit_limit_down_queue_unknown_without_l2` | 2 |

## 总体结果

| Segment | Closed | Days | Win | Mean | Median | PF | 2x mean | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 1072 | 75 | 35.7276% | -0.5533% | -0.9241% | 0.6652 | -0.8589% | -38.8521% | -41.1806% |
| `block_1` | 332 | 19 | 33.7349% | -0.8251% | -1.0851% | 0.5499 | -1.1309% | -16.4068% | -16.4068% |
| `block_2` | 339 | 19 | 35.3982% | -0.5359% | -0.8855% | 0.6582 | -0.8431% | -11.1050% | -11.1181% |
| `block_3` | 250 | 19 | 40.8000% | -0.0106% | -0.6175% | 0.9922 | -0.3136% | -8.5124% | -16.0414% |
| `block_4` | 151 | 18 | 32.4503% | -0.8929% | -1.1515% | 0.5360 | -1.1994% | -10.0562% | -15.1887% |
| `block_5` | 0 | 0 | - | - | - | - | - | - | - |
| `development` | 921 | 57 | 36.2649% | -0.4976% | -0.8742% | 0.6906 | -0.8031% | -32.0154% | -35.0807% |
| `validation` | 151 | 18 | 32.4503% | -0.8929% | -1.1515% | 0.5360 | -1.1994% | -10.0562% | -15.1887% |

复利为同日全部闭合信号等权后的历史诊断曲线，不是正式现金账户绩效。

## 支撑位置

| Feature | State | Segment | Closed | Days | Win | Mean | 2x mean |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `morning_support_state` | `broken_unrecovered` | `all` | 213 | 53 | 41.7840% | -0.1581% | -0.4648% |
| `morning_support_state` | `broken_unrecovered` | `development` | 179 | 42 | 41.3408% | -0.0699% | -0.3760% |
| `morning_support_state` | `broken_unrecovered` | `validation` | 34 | 11 | 44.1176% | -0.6227% | -0.9324% |
| `morning_support_state` | `false_break_reclaimed` | `all` | 139 | 51 | 35.9712% | -0.6674% | -0.9736% |
| `morning_support_state` | `false_break_reclaimed` | `development` | 117 | 40 | 38.4615% | -0.5577% | -0.8645% |
| `morning_support_state` | `false_break_reclaimed` | `validation` | 22 | 11 | 22.7273% | -1.2507% | -1.5539% |
| `morning_support_state` | `held` | `all` | 720 | 74 | 33.8889% | -0.6481% | -0.9534% |
| `morning_support_state` | `held` | `development` | 625 | 57 | 34.4000% | -0.6088% | -0.9140% |
| `morning_support_state` | `held` | `validation` | 95 | 17 | 30.5263% | -0.9067% | -1.2128% |
| `support_break_count` | `0` | `all` | 307 | 68 | 33.2248% | -0.7255% | -1.0290% |
| `support_break_count` | `0` | `development` | 269 | 53 | 33.0855% | -0.7424% | -1.0455% |
| `support_break_count` | `0` | `validation` | 38 | 15 | 34.2105% | -0.6060% | -0.9123% |
| `support_break_count` | `1` | `all` | 418 | 71 | 35.4067% | -0.6562% | -0.9621% |
| `support_break_count` | `1` | `development` | 358 | 55 | 36.8715% | -0.5751% | -0.8812% |
| `support_break_count` | `1` | `validation` | 60 | 16 | 26.6667% | -1.1405% | -1.4448% |
| `support_break_count` | `2` | `all` | 245 | 61 | 36.7347% | -0.3186% | -0.6260% |
| `support_break_count` | `2` | `development` | 217 | 47 | 37.3272% | -0.2629% | -0.5696% |
| `support_break_count` | `2` | `validation` | 28 | 14 | 32.1429% | -0.7507% | -1.0632% |
| `support_break_count` | `3` | `all` | 81 | 39 | 40.7407% | -0.2574% | -0.5649% |
| `support_break_count` | `3` | `development` | 68 | 31 | 42.6471% | 0.0326% | -0.2758% |
| `support_break_count` | `3` | `validation` | 13 | 8 | 30.7692% | -1.7744% | -2.0769% |
| `support_break_count` | `4` | `all` | 15 | 14 | 40.0000% | -0.5137% | -0.8186% |
| `support_break_count` | `4` | `development` | 8 | 8 | 25.0000% | -0.9257% | -1.2294% |
| `support_break_count` | `4` | `validation` | 7 | 6 | 57.1429% | -0.0428% | -0.3490% |
| `support_break_count` | `5` | `all` | 6 | 5 | 66.6667% | 1.7616% | 1.4488% |
| `support_break_count` | `5` | `development` | 1 | 1 | 100.0000% | 9.5537% | 9.2275% |
| `support_break_count` | `5` | `validation` | 5 | 4 | 60.0000% | 0.2032% | -0.1069% |
| `support_zone` | `above_vwap_and_ma5` | `all` | 307 | 68 | 33.2248% | -0.7255% | -1.0290% |
| `support_zone` | `above_vwap_and_ma5` | `development` | 269 | 53 | 33.0855% | -0.7424% | -1.0455% |
| `support_zone` | `above_vwap_and_ma5` | `validation` | 38 | 15 | 34.2105% | -0.6060% | -0.9123% |
| `support_zone` | `below_ma20` | `all` | 22 | 19 | 40.9091% | 0.1345% | -0.1709% |
| `support_zone` | `below_ma20` | `development` | 13 | 12 | 38.4615% | 0.8238% | 0.5189% |
| `support_zone` | `below_ma20` | `validation` | 9 | 7 | 44.4444% | -0.8612% | -1.1671% |
| `support_zone` | `below_vwap_above_ma5` | `all` | 499 | 72 | 37.4749% | -0.5872% | -0.8927% |
| `support_zone` | `below_vwap_above_ma5` | `development` | 434 | 55 | 38.9401% | -0.5111% | -0.8165% |
| `support_zone` | `below_vwap_above_ma5` | `validation` | 65 | 17 | 27.6923% | -1.0957% | -1.4016% |
| `support_zone` | `ma10_to_ma20` | `all` | 32 | 24 | 40.6250% | -0.4892% | -0.7957% |
| `support_zone` | `ma10_to_ma20` | `development` | 23 | 17 | 39.1304% | -0.3315% | -0.6382% |
| `support_zone` | `ma10_to_ma20` | `validation` | 9 | 7 | 44.4444% | -0.8921% | -1.1982% |
| `support_zone` | `ma5_to_ma10` | `all` | 212 | 56 | 33.9623% | -0.3048% | -0.6142% |
| `support_zone` | `ma5_to_ma10` | `development` | 182 | 42 | 34.0659% | -0.2188% | -0.5284% |
| `support_zone` | `ma5_to_ma10` | `validation` | 30 | 14 | 33.3333% | -0.8266% | -1.1347% |

## 单特征跨段确认

| Feature | State | Status | Dev N/Win/Mean/2x | Val N/Win/Mean/2x |
| --- | --- | --- | --- | --- |
| `late_momentum_bucket` | `falling` | `not_better_than_segment_baseline` | 289/36.3322%/-0.7383%/-1.0401% | 57/36.8421%/-0.7093%/-1.0189% |
| `late_momentum_bucket` | `flat` | `not_better_than_segment_baseline` | 460/38.6957%/-0.2002%/-0.5080% | 64/31.2500%/-0.7258%/-1.0315% |
| `late_momentum_bucket` | `rising` | `validation_insufficient` | 172/29.6512%/-0.8883%/-1.1942% | 30/26.6667%/-1.5982%/-1.9003% |
| `late_volume_bucket` | `contraction` | `validation_insufficient` | 57/36.8421%/-0.0560%/-0.3569% | 5/40.0000%/-1.2278%/-1.5269% |
| `late_volume_bucket` | `expansion` | `not_better_than_segment_baseline` | 536/36.3806%/-0.4874%/-0.7946% | 98/31.6327%/-0.8445%/-1.1513% |
| `late_volume_bucket` | `normal` | `validation_insufficient` | 328/35.9756%/-0.5909%/-0.8945% | 48/33.3333%/-0.9569%/-1.2634% |
| `market_regime` | `GOLD/DANGER` | `development_insufficient` | 0.0/-/-/- | 2/50.0000%/3.3158%/3.0003% |
| `market_regime` | `GOLD/NORMAL` | `not_better_than_segment_baseline` | 921/36.2649%/-0.4976%/-0.8031% | 149/32.2148%/-0.9494%/-1.2557% |
| `morning_support_state` | `broken_unrecovered` | `validation_insufficient` | 179/41.3408%/-0.0699%/-0.3760% | 34/44.1176%/-0.6227%/-0.9324% |
| `morning_support_state` | `false_break_reclaimed` | `validation_insufficient` | 117/38.4615%/-0.5577%/-0.8645% | 22/22.7273%/-1.2507%/-1.5539% |
| `morning_support_state` | `held` | `not_better_than_segment_baseline` | 625/34.4000%/-0.6088%/-0.9140% | 95/30.5263%/-0.9067%/-1.2128% |
| `recognition_rank_bucket` | `rank1` | `not_better_than_segment_baseline` | 228/40.7895%/-0.5687%/-0.8744% | 26/34.6154%/-0.7334%/-1.0434% |
| `recognition_rank_bucket` | `rank2_3` | `not_better_than_segment_baseline` | 693/34.7763%/-0.4742%/-0.7797% | 125/32.0000%/-0.9261%/-1.2318% |
| `spell_offset_bucket` | `S+1` | `validation_insufficient` | 207/34.2995%/-0.9291%/-1.2348% | 35/31.4286%/-0.9105%/-1.2156% |
| `spell_offset_bucket` | `S+2` | `validation_insufficient` | 235/37.4468%/-0.5908%/-0.8928% | 37/27.0270%/-1.2013%/-1.5062% |
| `spell_offset_bucket` | `S+3` | `validation_insufficient` | 238/31.5126%/-0.8880%/-1.1934% | 40/32.5000%/-0.9139%/-1.2221% |
| `spell_offset_bucket` | `S+4` | `validation_insufficient` | 241/41.4938%/0.3496%/0.0406% | 39/38.4615%/-0.5630%/-0.8705% |
| `support_break_count` | `0` | `not_better_than_segment_baseline` | 269/33.0855%/-0.7424%/-1.0455% | 38/34.2105%/-0.6060%/-0.9123% |
| `support_break_count` | `1` | `not_better_than_segment_baseline` | 358/36.8715%/-0.5751%/-0.8812% | 60/26.6667%/-1.1405%/-1.4448% |
| `support_break_count` | `2` | `validation_insufficient` | 217/37.3272%/-0.2629%/-0.5696% | 28/32.1429%/-0.7507%/-1.0632% |
| `support_break_count` | `3` | `validation_insufficient` | 68/42.6471%/0.0326%/-0.2758% | 13/30.7692%/-1.7744%/-2.0769% |
| `support_break_count` | `4` | `development_insufficient` | 8/25.0000%/-0.9257%/-1.2294% | 7/57.1429%/-0.0428%/-0.3490% |
| `support_break_count` | `5` | `development_insufficient` | 1/100.0000%/9.5537%/9.2275% | 5/60.0000%/0.2032%/-0.1069% |
| `support_zone` | `above_vwap_and_ma5` | `not_better_than_segment_baseline` | 269/33.0855%/-0.7424%/-1.0455% | 38/34.2105%/-0.6060%/-0.9123% |
| `support_zone` | `below_ma20` | `development_insufficient` | 13/38.4615%/0.8238%/0.5189% | 9/44.4444%/-0.8612%/-1.1671% |
| `support_zone` | `below_vwap_above_ma5` | `not_better_than_segment_baseline` | 434/38.9401%/-0.5111%/-0.8165% | 65/27.6923%/-1.0957%/-1.4016% |
| `support_zone` | `ma10_to_ma20` | `development_insufficient` | 23/39.1304%/-0.3315%/-0.6382% | 9/44.4444%/-0.8921%/-1.1982% |
| `support_zone` | `ma5_to_ma10` | `validation_insufficient` | 182/34.0659%/-0.2188%/-0.5284% | 30/33.3333%/-0.8266%/-1.1347% |
| `tail_above_ma10` | `false` | `validation_insufficient` | 31/38.7097%/-0.0968%/-0.4022% | 17/47.0588%/-0.7917%/-1.0976% |
| `tail_above_ma10` | `true` | `not_better_than_segment_baseline` | 890/36.1798%/-0.5115%/-0.8171% | 134/30.5970%/-0.9057%/-1.2123% |
| `tail_above_ma20` | `false` | `development_insufficient` | 13/38.4615%/0.8238%/0.5189% | 9/44.4444%/-0.8612%/-1.1671% |
| `tail_above_ma20` | `true` | `not_better_than_segment_baseline` | 908/36.2335%/-0.5165%/-0.8221% | 142/31.6901%/-0.8949%/-1.2014% |
| `tail_above_ma5` | `false` | `not_better_than_segment_baseline` | 206/34.9515%/-0.1950%/-0.5043% | 47/38.2979%/-0.6815%/-0.9891% |
| `tail_above_ma5` | `true` | `not_better_than_segment_baseline` | 715/36.6434%/-0.5847%/-0.8892% | 104/29.8077%/-0.9884%/-1.2944% |
| `tail_above_vwap` | `false` | `not_better_than_segment_baseline` | 604/38.2450%/-0.4142%/-0.7206% | 101/31.6832%/-1.0037%/-1.3101% |
| `tail_above_vwap` | `true` | `not_better_than_segment_baseline` | 317/32.4921%/-0.6564%/-0.9604% | 50/34.0000%/-0.6690%/-0.9757% |
| `tail_drawdown_bucket` | `1_to_3` | `not_better_than_segment_baseline` | 315/34.9206%/-0.3550%/-0.6598% | 42/35.7143%/-1.0670%/-1.3717% |
| `tail_drawdown_bucket` | `3_to_5` | `not_better_than_segment_baseline` | 255/37.6471%/-0.5378%/-0.8443% | 44/31.8182%/-0.2455%/-0.5528% |
| `tail_drawdown_bucket` | `below_5` | `validation_insufficient` | 277/38.6282%/-0.5958%/-0.9004% | 54/31.4815%/-1.2816%/-1.5899% |
| `tail_drawdown_bucket` | `within_1` | `validation_insufficient` | 74/28.3784%/-0.5980%/-0.9069% | 11/27.2727%/-0.9094%/-1.2104% |
| `tail_range_bucket` | `20_to_50` | `not_better_than_segment_baseline` | 260/35.3846%/-0.7461%/-1.0530% | 47/27.6596%/-0.9239%/-1.2280% |
| `tail_range_bucket` | `50_to_80` | `validation_insufficient` | 252/36.9048%/-0.3002%/-0.6043% | 32/37.5000%/-0.3323%/-0.6401% |
| `tail_range_bucket` | `bottom_20` | `double_cost_not_positive` | 346/37.8613%/-0.3289%/-0.6348% | 59/35.5932%/-0.8227%/-1.1319% |
| `tail_range_bucket` | `top_20` | `validation_insufficient` | 63/28.5714%/-1.1875%/-1.4916% | 13/23.0769%/-2.4793%/-2.7784% |
| `tail_return_bucket` | `0_to_3` | `not_better_than_segment_baseline` | 217/39.6313%/-0.2996%/-0.6025% | 32/31.2500%/-0.9537%/-1.2592% |
| `tail_return_bucket` | `3_to_5` | `validation_insufficient` | 92/38.0435%/-0.7017%/-1.0068% | 13/23.0769%/-0.7718%/-1.0739% |
| `tail_return_bucket` | `5_to_7` | `validation_insufficient` | 34/32.3529%/-1.4704%/-1.7676% | 5/60.0000%/0.5900%/0.2599% |
| `tail_return_bucket` | `7_plus` | `development_insufficient` | 23/52.1739%/0.3627%/0.0426% | 1/0.0000%/-9.3191%/-9.5800% |
| `tail_return_bucket` | `below_0` | `not_better_than_segment_baseline` | 555/34.2342%/-0.5172%/-0.8238% | 100/33.0000%/-0.8791%/-1.1857% |

## 成功与失败连续特征

| Feature | Group | N | Median | Q25 | Q75 |
| --- | --- | ---: | ---: | ---: | ---: |
| `context_distance_to_ma5_pct` | `success` | 383 | 5.6647 | 2.0870 | 9.5772 |
| `context_distance_to_ma5_pct` | `failure` | 689 | 6.1947 | 2.2273 | 9.5233 |
| `context_distance_to_ma10_pct` | `success` | 383 | 10.6498 | 6.2745 | 16.3449 |
| `context_distance_to_ma10_pct` | `failure` | 689 | 10.0655 | 5.9016 | 15.7350 |
| `context_distance_to_ma20_pct` | `success` | 383 | 15.2984 | 9.5274 | 23.2951 |
| `context_distance_to_ma20_pct` | `failure` | 689 | 14.3188 | 9.1746 | 21.6504 |
| `context_distance_from_20d_high_pct` | `success` | 383 | -0.7672 | -3.9630 | 0.0000 |
| `context_distance_from_20d_high_pct` | `failure` | 689 | -0.5301 | -4.5997 | 0.0000 |
| `tail_return_from_previous_close_pct` | `success` | 383 | -0.7273 | -3.5841 | 1.5739 |
| `tail_return_from_previous_close_pct` | `failure` | 689 | -1.0870 | -3.3755 | 1.1594 |
| `tail_drawdown_from_session_high_pct` | `success` | 383 | -3.9016 | -5.7537 | -2.2522 |
| `tail_drawdown_from_session_high_pct` | `failure` | 689 | -3.5441 | -5.6650 | -2.0229 |
| `tail_range_position_pct` | `success` | 383 | 26.9430 | 10.4580 | 55.6624 |
| `tail_range_position_pct` | `failure` | 689 | 31.0627 | 11.8577 | 60.2410 |
| `tail_vs_open_pct` | `success` | 383 | -1.0589 | -3.7997 | 1.2537 |
| `tail_vs_open_pct` | `failure` | 689 | -1.2000 | -3.4188 | 1.0588 |
| `tail_vs_vwap_pct` | `success` | 383 | -0.6909 | -1.7842 | 0.3426 |
| `tail_vs_vwap_pct` | `failure` | 689 | -0.5252 | -1.5626 | 0.5023 |
| `tail_vs_ma5_pct` | `success` | 383 | 4.7393 | 0.1366 | 9.3745 |
| `tail_vs_ma5_pct` | `failure` | 689 | 4.7730 | 0.1043 | 9.1174 |
| `tail_vs_ma10_pct` | `success` | 383 | 9.1763 | 4.6251 | 15.2721 |
| `tail_vs_ma10_pct` | `failure` | 689 | 8.5271 | 4.7397 | 14.9144 |
| `tail_vs_ma20_pct` | `success` | 383 | 14.0313 | 7.9007 | 22.2175 |
| `tail_vs_ma20_pct` | `failure` | 689 | 12.8325 | 8.0364 | 20.8292 |
| `afternoon_low_vs_morning_low_pct` | `success` | 383 | 0.3626 | -0.6394 | 1.6665 |
| `afternoon_low_vs_morning_low_pct` | `failure` | 689 | 0.4762 | -0.2786 | 1.8130 |
| `last_15m_return_pct` | `success` | 383 | -0.1015 | -0.4685 | 0.1546 |
| `last_15m_return_pct` | `failure` | 689 | -0.0354 | -0.4200 | 0.2423 |
| `last_15m_volume_ratio` | `success` | 383 | 1.3916 | 1.0966 | 1.8738 |
| `last_15m_volume_ratio` | `failure` | 689 | 1.4142 | 1.0900 | 1.7967 |

## 成功案例

| Date | Stock | Concept | Rank/Offset | Support | Morning | Tail return | Drawdown | Entry | Exit | Net | 2x |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-08-26 | 章源钨业 (002378.SZSE) | 军工 | 2/S+1 | `above_vwap_and_ma5` | `held` | 3.8117% | -2.5263% | 13.8900 | 15.6200 | 11.9531% | 11.6234% |
| 2025-08-22 | 智微智能 (001339.SZSE) | 人形机器人 | 3/S+4 | `above_vwap_and_ma5` | `held` | 3.2397% | -1.8850% | 62.4800 | 70.2700 | 11.3715% | 11.0581% |
| 2025-08-08 | 北纬科技 (002148.SZSE) | 无人机 | 1/S+2 | `below_vwap_above_ma5` | `broken_unrecovered` | -10.0289% | -15.1818% | 9.3300 | 10.4100 | 11.2237% | 10.7897% |
| 2025-08-25 | 华胜天成 (600410.SSE) | 华为概念 | 1/S+4 | `above_vwap_and_ma5` | `held` | 8.0416% | -1.7634% | 22.8300 | 25.3600 | 10.5531% | 10.2273% |
| 2025-08-14 | 可立克 (002782.SZSE) | 机器人概念 | 1/S+1 | `below_vwap_above_ma5` | `held` | -6.8886% | -9.8889% | 16.2200 | 18.0000 | 10.5297% | 10.2015% |
| 2025-07-24 | 直真科技 (003007.SZSE) | AI智能体 | 2/S+4 | `above_vwap_and_ma5` | `held` | 3.6994% | -0.7250% | 35.6000 | 39.3600 | 10.1980% | 9.8681% |
| 2025-10-10 | 天际股份 (002759.SZSE) | 固态电池 | 1/S+2 | `above_vwap_and_ma5` | `held` | -4.4721% | -7.2516% | 20.7200 | 22.9100 | 10.1827% | 9.8536% |
| 2025-07-03 | 再升科技 (603601.SSE) | 低空经济 | 3/S+3 | `below_vwap_above_ma5` | `held` | -6.9106% | -6.9106% | 4.5800 | 5.0600 | 10.1336% | 9.7584% |
| 2025-07-11 | 大丰实业 (603081.SSE) | 人形机器人 | 2/S+2 | `above_vwap_and_ma5` | `held` | -3.7067% | -1.8883% | 11.9500 | 13.2100 | 10.1297% | 9.8015% |
| 2025-08-25 | 中电鑫龙 (002298.SZSE) | 军工 | 1/S+4 | `ma5_to_ma10` | `broken_unrecovered` | -0.5515% | -4.7535% | 10.8200 | 11.9400 | 9.9748% | 9.6458% |
| 2025-07-07 | 博敏电子 (603936.SSE) | PCB | 2/S+2 | `ma5_to_ma10` | `held` | -3.1968% | -6.8269% | 9.6900 | 10.6900 | 9.9700% | 9.5466% |
| 2025-07-17 | 华宏科技 (002645.SZSE) | 稀土永磁 | 2/S+4 | `below_vwap_above_ma5` | `held` | -6.6810% | -6.5468% | 12.9900 | 14.3300 | 9.8576% | 9.5313% |
| 2025-08-21 | 群兴玩具 (002575.SZSE) | 华为概念 | 3/S+1 | `below_vwap_above_ma5` | `broken_unrecovered` | -4.4118% | -4.0863% | 8.4600 | 9.3200 | 9.8182% | 9.4082% |
| 2025-08-26 | 旭光电子 (600353.SSE) | 军工 | 3/S+2 | `below_vwap_above_ma5` | `held` | -2.2289% | -2.8144% | 16.2200 | 17.8800 | 9.7990% | 9.4722% |
| 2025-07-25 | 韩建河山 (603616.SSE) | 水利建设 | 1/S+4 | `below_vwap_above_ma5` | `broken_unrecovered` | -9.9849% | -16.8994% | 5.9500 | 6.5500 | 9.6919% | 9.3639% |
| 2025-08-22 | 凯迪股份 (605288.SSE) | 光伏概念 | 3/S+2 | `above_vwap_and_ma5` | `held` | 1.8199% | -1.9193% | 64.9000 | 71.5600 | 9.6682% | 9.3466% |
| 2025-08-22 | 新天药业 (002873.SZSE) | 创新药 | 1/S+4 | `ma5_to_ma10` | `broken_unrecovered` | -2.2603% | -5.6433% | 12.5500 | 13.8100 | 9.6267% | 9.2995% |
| 2025-07-24 | 延华智能 (002178.SZSE) | 机器人概念 | 1/S+4 | `ma5_to_ma10` | `held` | -2.7663% | -1.5406% | 7.0300 | 7.7300 | 9.6106% | 9.2160% |
| 2025-08-13 | 上海港湾 (605598.SSE) | 商业航天 | 1/S+2 | `ma5_to_ma10` | `broken_unrecovered` | -5.0982% | -8.7446% | 27.5500 | 30.3100 | 9.6086% | 9.2814% |
| 2025-08-07 | 航天科技 (000901.SZSE) | 军工 | 3/S+1 | `below_vwap_above_ma5` | `held` | -4.3505% | -6.2157% | 15.4000 | 16.9500 | 9.5946% | 9.2693% |

## 失败案例

| Date | Stock | Concept | Rank/Offset | Support | Morning | Tail return | Drawdown | Entry | Exit | Net | 2x |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-07-23 | 美邦股份 (605033.SSE) | 西部大开发 | 1/S+2 | `above_vwap_and_ma5` | `held` | -5.2352% | -13.8585% | 26.7900 | 23.7500 | -11.5369% | -11.8256% |
| 2025-07-04 | 诚邦股份 (603316.SSE) | 存储芯片 | 1/S+1 | `below_vwap_above_ma5` | `held` | 2.6734% | -6.6819% | 12.3000 | 11.0200 | -10.6600% | -10.9520% |
| 2025-07-02 | 大东南 (002263.SZSE) | 固态电池 | 1/S+3 | `below_vwap_above_ma5` | `held` | -5.7007% | -11.3839% | 3.9600 | 3.5500 | -10.6246% | -10.8738% |
| 2025-07-14 | 华光环能 (600475.SSE) | 光伏概念 | 1/S+2 | `above_vwap_and_ma5` | `held` | 1.4493% | -3.3928% | 16.8100 | 15.1200 | -10.2623% | -10.5536% |
| 2025-08-20 | 中电鑫龙 (002298.SZSE) | 军工 | 1/S+1 | `below_vwap_above_ma5` | `broken_unrecovered` | -3.3762% | -11.6176% | 12.0200 | 10.8200 | -10.2532% | -10.4058% |
| 2025-09-03 | 数据港 (603881.SSE) | 数据中心 | 2/S+2 | `below_vwap_above_ma5` | `held` | -6.1571% | -6.1326% | 35.9600 | 32.3000 | -10.1608% | -10.3587% |
| 2025-07-14 | 赫美集团 (002356.SZSE) | 氢能源 | 1/S+2 | `below_vwap_above_ma5` | `broken_unrecovered` | -7.8624% | -9.8558% | 3.7500 | 3.3900 | -9.8698% | -10.1254% |
| 2025-09-18 | 建元信托 (600816.SSE) | 低价股 | 3/S+1 | `below_vwap_above_ma5` | `false_break_reclaimed` | 3.3803% | -6.1381% | 3.6600 | 3.3100 | -9.8133% | -10.1066% |
| 2025-09-23 | 云南旅游 (002059.SZSE) | 人形机器人 | 3/S+4 | `below_vwap_above_ma5` | `held` | -10.0124% | -9.0000% | 7.2800 | 6.5900 | -9.7470% | -10.0410% |
| 2025-08-18 | 洪通燃气 (605169.SSE) | 天然气 | 1/S+4 | `below_vwap_above_ma5` | `held` | -1.2264% | -7.3346% | 19.3300 | 17.4800 | -9.7255% | -10.0158% |
| 2025-07-23 | 北化股份 (002246.SZSE) | 军工 | 1/S+2 | `below_vwap_above_ma5` | `broken_unrecovered` | -7.2922% | -15.7095% | 19.9700 | 18.1000 | -9.6446% | -9.7403% |
| 2025-07-21 | 联发股份 (002394.SZSE) | 机器人概念 | 3/S+3 | `below_vwap_above_ma5` | `held` | 2.6292% | -6.6777% | 11.3100 | 10.2600 | -9.5338% | -9.8274% |
| 2025-09-23 | 万马股份 (002276.SZSE) | 人形机器人 | 3/S+1 | `below_vwap_above_ma5` | `held` | 0.0000% | -6.2870% | 20.5900 | 18.6800 | -9.4597% | -9.7514% |
| 2025-09-23 | 上海建工 (600170.SSE) | 低价股 | 2/S+4 | `above_vwap_and_ma5` | `held` | 8.9231% | -1.1173% | 3.5400 | 3.2200 | -9.3191% | -9.5800% |
| 2025-09-22 | 丰山集团 (603810.SSE) | 固态电池 | 1/S+1 | `below_ma20` | `broken_unrecovered` | -5.4897% | -8.2930% | 15.1600 | 13.8900 | -8.5475% | -8.8398% |
| 2025-07-15 | 京运通 (601908.SSE) | 稀土永磁 | 1/S+2 | `below_vwap_above_ma5` | `held` | -8.1897% | -12.5257% | 4.2600 | 3.9100 | -8.4861% | -8.7822% |
| 2025-08-20 | 卧龙电驱 (600580.SSE) | 人形机器人 | 2/S+3 | `below_vwap_above_ma5` | `held` | 3.2059% | -4.6467% | 35.0900 | 32.1900 | -8.4118% | -8.7035% |
| 2025-08-07 | 能科科技 (603859.SSE) | AI智能体 | 1/S+3 | `below_vwap_above_ma5` | `false_break_reclaimed` | -2.4605% | -3.8710% | 43.2100 | 39.7600 | -8.2307% | -8.5263% |
| 2025-07-14 | 日发精机 (002520.SZSE) | 人形机器人 | 1/S+3 | `above_vwap_and_ma5` | `held` | 3.4483% | -2.0408% | 7.2100 | 6.6400 | -8.1622% | -8.4582% |
| 2025-08-20 | 川润股份 (002272.SZSE) | 机器人概念 | 2/S+2 | `below_vwap_above_ma5` | `held` | 5.4939% | -4.0868% | 19.0100 | 17.5000 | -8.1462% | -8.4402% |

## 输入指纹

| Input | Rows | Columns | Digest |
| --- | ---: | ---: | --- |
| `parent_tail_candidates` | 1396 | 28 | `sha256:8a563fb5603e977f57e503335dfed852c3861a45f8d6c70b8efd8b987f477dab` |
| `tail_candidates` | 1220 | 28 | `sha256:effe5163295e58cd03712c43e337587fac1d574b1acfcb8fe11d669a1a704279` |
| `tail_features` | 1220 | 73 | `sha256:ba397d9535b56a25f7fc3bd10becec8be9472fa7eb8ec6d1fad2a879ec10fcab` |
| `tail_minutes` | 73584 | 11 | `sha256:e35b2f77d964656cb8a0bf76528e0b172cfe3df753ead7d641424b35990fd74c` |
| `tail_trade_ledger` | 1220 | 86 | `sha256:3c06df9e0113198e43774f43bfc11b20faad6dc1bdc15c048ecedc02dfaaf7f0` |

## 边界

本报告先保留全部成功与失败案例，再比较事前特征。事件认可 Top3 不是严格历史成员 Top3，后两块也是复用历史；任何局部高胜率都不能直接成为正式规则。
