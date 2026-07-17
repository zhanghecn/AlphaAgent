# AlphaAgent 龙头尾盘低吸特征研究

结论：`no_stable_tail_feature_group`\
正式规则/绩效：`null/null`\
成交：D 14:50 完成观察，14:55 bar 开盘买；D+1 10:30 后首个可执行代理为 10:35 bar 开盘卖。

## 覆盖

候选/完整双日路径/特征：`1396/1383/1383`\
股票/日期：`317/93`\
闭合/成功/失败：`1204/436/768`\
拒绝/未闭合：`176/3`

### 未成交与未闭合原因

| Reason | Count |
| --- | ---: |
| `entry_limit_up_queue_unknown_without_l2` | 176 |
| `exit_limit_down_queue_unknown_without_l2` | 3 |

## 总体结果

| Segment | Closed | Days | Win | Mean | Median | PF | 2x mean | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | 1204 | 93 | 36.2126% | -0.5416% | -0.9117% | 0.6765 | -0.8471% | -48.7325% | -48.7325% |
| `block_1` | 332 | 19 | 33.7349% | -0.8251% | -1.0851% | 0.5499 | -1.1309% | -16.4068% | -16.4068% |
| `block_2` | 339 | 19 | 35.3982% | -0.5359% | -0.8855% | 0.6582 | -0.8431% | -11.1050% | -11.1181% |
| `block_3` | 250 | 19 | 40.8000% | -0.0106% | -0.6175% | 0.9922 | -0.3136% | -8.5124% | -16.0414% |
| `block_4` | 151 | 18 | 32.4503% | -0.8929% | -1.1515% | 0.5360 | -1.1994% | -10.0562% | -15.1887% |
| `block_5` | 132 | 18 | 40.1515% | -0.4467% | -0.8544% | 0.7581 | -0.7513% | -16.1581% | -16.1581% |
| `development` | 921 | 57 | 36.2649% | -0.4976% | -0.8742% | 0.6906 | -0.8031% | -32.0154% | -35.0807% |
| `validation` | 283 | 36 | 36.0424% | -0.6848% | -1.0475% | 0.6373 | -0.9903% | -24.5894% | -26.0776% |

复利为同日全部闭合信号等权后的历史诊断曲线，不是正式现金账户绩效。

## 支撑位置

| Feature | State | Segment | Closed | Days | Win | Mean | 2x mean |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `morning_support_state` | `broken_unrecovered` | `all` | 229 | 63 | 41.0480% | -0.2203% | -0.5266% |
| `morning_support_state` | `broken_unrecovered` | `development` | 179 | 42 | 41.3408% | -0.0699% | -0.3760% |
| `morning_support_state` | `broken_unrecovered` | `validation` | 50 | 21 | 40.0000% | -0.7589% | -1.0658% |
| `morning_support_state` | `false_break_reclaimed` | `all` | 157 | 60 | 37.5796% | -0.5783% | -0.8847% |
| `morning_support_state` | `false_break_reclaimed` | `development` | 117 | 40 | 38.4615% | -0.5577% | -0.8645% |
| `morning_support_state` | `false_break_reclaimed` | `validation` | 40 | 20 | 35.0000% | -0.6386% | -0.9437% |
| `morning_support_state` | `held` | `all` | 818 | 90 | 34.5966% | -0.6244% | -0.9297% |
| `morning_support_state` | `held` | `development` | 625 | 57 | 34.4000% | -0.6088% | -0.9140% |
| `morning_support_state` | `held` | `validation` | 193 | 33 | 35.2332% | -0.6751% | -0.9805% |
| `support_break_count` | `0` | `all` | 359 | 81 | 33.7047% | -0.7141% | -1.0176% |
| `support_break_count` | `0` | `development` | 269 | 53 | 33.0855% | -0.7424% | -1.0455% |
| `support_break_count` | `0` | `validation` | 90 | 28 | 35.5556% | -0.6295% | -0.9342% |
| `support_break_count` | `1` | `all` | 470 | 84 | 36.8085% | -0.5953% | -0.9012% |
| `support_break_count` | `1` | `development` | 358 | 55 | 36.8715% | -0.5751% | -0.8812% |
| `support_break_count` | `1` | `validation` | 112 | 29 | 36.6071% | -0.6601% | -0.9652% |
| `support_break_count` | `2` | `all` | 267 | 72 | 35.9551% | -0.3507% | -0.6577% |
| `support_break_count` | `2` | `development` | 217 | 47 | 37.3272% | -0.2629% | -0.5696% |
| `support_break_count` | `2` | `validation` | 50 | 25 | 30.0000% | -0.7320% | -1.0402% |
| `support_break_count` | `3` | `all` | 87 | 44 | 41.3793% | -0.2884% | -0.5961% |
| `support_break_count` | `3` | `development` | 68 | 31 | 42.6471% | 0.0326% | -0.2758% |
| `support_break_count` | `3` | `validation` | 19 | 13 | 36.8421% | -1.4375% | -1.7422% |
| `support_break_count` | `4` | `all` | 15 | 14 | 40.0000% | -0.5137% | -0.8186% |
| `support_break_count` | `4` | `development` | 8 | 8 | 25.0000% | -0.9257% | -1.2294% |
| `support_break_count` | `4` | `validation` | 7 | 6 | 57.1429% | -0.0428% | -0.3490% |
| `support_break_count` | `5` | `all` | 6 | 5 | 66.6667% | 1.7616% | 1.4488% |
| `support_break_count` | `5` | `development` | 1 | 1 | 100.0000% | 9.5537% | 9.2275% |
| `support_break_count` | `5` | `validation` | 5 | 4 | 60.0000% | 0.2032% | -0.1069% |
| `support_zone` | `above_vwap_and_ma5` | `all` | 359 | 81 | 33.7047% | -0.7141% | -1.0176% |
| `support_zone` | `above_vwap_and_ma5` | `development` | 269 | 53 | 33.0855% | -0.7424% | -1.0455% |
| `support_zone` | `above_vwap_and_ma5` | `validation` | 90 | 28 | 35.5556% | -0.6295% | -0.9342% |
| `support_zone` | `below_ma20` | `all` | 22 | 19 | 40.9091% | 0.1345% | -0.1709% |
| `support_zone` | `below_ma20` | `development` | 13 | 12 | 38.4615% | 0.8238% | 0.5189% |
| `support_zone` | `below_ma20` | `validation` | 9 | 7 | 44.4444% | -0.8612% | -1.1671% |
| `support_zone` | `below_vwap_above_ma5` | `all` | 557 | 86 | 38.2406% | -0.5550% | -0.8604% |
| `support_zone` | `below_vwap_above_ma5` | `development` | 434 | 55 | 38.9401% | -0.5111% | -0.8165% |
| `support_zone` | `below_vwap_above_ma5` | `validation` | 123 | 31 | 35.7724% | -0.7099% | -1.0153% |
| `support_zone` | `ma10_to_ma20` | `all` | 35 | 27 | 40.0000% | -0.4609% | -0.7677% |
| `support_zone` | `ma10_to_ma20` | `development` | 23 | 17 | 39.1304% | -0.3315% | -0.6382% |
| `support_zone` | `ma10_to_ma20` | `validation` | 12 | 10 | 41.6667% | -0.7090% | -1.0159% |
| `support_zone` | `ma5_to_ma10` | `all` | 231 | 66 | 34.1991% | -0.3176% | -0.6268% |
| `support_zone` | `ma5_to_ma10` | `development` | 182 | 42 | 34.0659% | -0.2188% | -0.5284% |
| `support_zone` | `ma5_to_ma10` | `validation` | 49 | 24 | 34.6939% | -0.6848% | -0.9923% |

## 单特征跨段确认

| Feature | State | Status | Dev N/Win/Mean/2x | Val N/Win/Mean/2x |
| --- | --- | --- | --- | --- |
| `late_momentum_bucket` | `falling` | `not_better_than_segment_baseline` | 289/36.3322%/-0.7383%/-1.0401% | 97/36.0825%/-0.7209%/-1.0276% |
| `late_momentum_bucket` | `flat` | `double_cost_not_positive` | 460/38.6957%/-0.2002%/-0.5080% | 118/36.4407%/-0.3570%/-0.6637% |
| `late_momentum_bucket` | `rising` | `not_better_than_segment_baseline` | 172/29.6512%/-0.8883%/-1.1942% | 68/35.2941%/-1.2019%/-1.5041% |
| `late_volume_bucket` | `contraction` | `validation_insufficient` | 57/36.8421%/-0.0560%/-0.3569% | 13/46.1538%/-0.3412%/-0.6425% |
| `late_volume_bucket` | `expansion` | `not_better_than_segment_baseline` | 536/36.3806%/-0.4874%/-0.7946% | 166/33.1325%/-0.7708%/-1.0766% |
| `late_volume_bucket` | `normal` | `not_better_than_segment_baseline` | 328/35.9756%/-0.5909%/-0.8945% | 104/39.4231%/-0.5905%/-0.8961% |
| `market_regime` | `GOLD/DANGER` | `development_insufficient` | 0.0/-/-/- | 2/50.0000%/3.3158%/3.0003% |
| `market_regime` | `GOLD/NORMAL` | `not_better_than_segment_baseline` | 921/36.2649%/-0.4976%/-0.8031% | 149/32.2148%/-0.9494%/-1.2557% |
| `market_regime` | `SILVER/DANGER` | `development_insufficient` | 0.0/-/-/- | 1/0.0000%/-3.4636%/-3.7681% |
| `market_regime` | `SILVER/NORMAL` | `development_insufficient` | 0.0/-/-/- | 131/40.4580%/-0.4237%/-0.7282% |
| `morning_support_state` | `broken_unrecovered` | `not_better_than_segment_baseline` | 179/41.3408%/-0.0699%/-0.3760% | 50/40.0000%/-0.7589%/-1.0658% |
| `morning_support_state` | `false_break_reclaimed` | `not_better_than_segment_baseline` | 117/38.4615%/-0.5577%/-0.8645% | 40/35.0000%/-0.6386%/-0.9437% |
| `morning_support_state` | `held` | `not_better_than_segment_baseline` | 625/34.4000%/-0.6088%/-0.9140% | 193/35.2332%/-0.6751%/-0.9805% |
| `recognition_rank_bucket` | `rank1` | `not_better_than_segment_baseline` | 228/40.7895%/-0.5687%/-0.8744% | 59/35.5932%/-0.9005%/-1.2061% |
| `recognition_rank_bucket` | `rank2_3` | `not_better_than_segment_baseline` | 693/34.7763%/-0.4742%/-0.7797% | 224/36.1607%/-0.6279%/-0.9335% |
| `spell_offset_bucket` | `S+1` | `not_better_than_segment_baseline` | 207/34.2995%/-0.9291%/-1.2348% | 71/40.8451%/-0.1937%/-0.5003% |
| `spell_offset_bucket` | `S+2` | `not_better_than_segment_baseline` | 235/37.4468%/-0.5908%/-0.8928% | 72/31.9444%/-0.9751%/-1.2809% |
| `spell_offset_bucket` | `S+3` | `not_better_than_segment_baseline` | 238/31.5126%/-0.8880%/-1.1934% | 72/29.1667%/-1.2813%/-1.5832% |
| `spell_offset_bucket` | `S+4` | `double_cost_not_positive` | 241/41.4938%/0.3496%/0.0406% | 68/42.6471%/-0.2584%/-0.5667% |
| `support_break_count` | `0` | `not_better_than_segment_baseline` | 269/33.0855%/-0.7424%/-1.0455% | 90/35.5556%/-0.6295%/-0.9342% |
| `support_break_count` | `1` | `not_better_than_segment_baseline` | 358/36.8715%/-0.5751%/-0.8812% | 112/36.6071%/-0.6601%/-0.9652% |
| `support_break_count` | `2` | `not_better_than_segment_baseline` | 217/37.3272%/-0.2629%/-0.5696% | 50/30.0000%/-0.7320%/-1.0402% |
| `support_break_count` | `3` | `validation_insufficient` | 68/42.6471%/0.0326%/-0.2758% | 19/36.8421%/-1.4375%/-1.7422% |
| `support_break_count` | `4` | `development_insufficient` | 8/25.0000%/-0.9257%/-1.2294% | 7/57.1429%/-0.0428%/-0.3490% |
| `support_break_count` | `5` | `development_insufficient` | 1/100.0000%/9.5537%/9.2275% | 5/60.0000%/0.2032%/-0.1069% |
| `support_zone` | `above_vwap_and_ma5` | `not_better_than_segment_baseline` | 269/33.0855%/-0.7424%/-1.0455% | 90/35.5556%/-0.6295%/-0.9342% |
| `support_zone` | `below_ma20` | `development_insufficient` | 13/38.4615%/0.8238%/0.5189% | 9/44.4444%/-0.8612%/-1.1671% |
| `support_zone` | `below_vwap_above_ma5` | `not_better_than_segment_baseline` | 434/38.9401%/-0.5111%/-0.8165% | 123/35.7724%/-0.7099%/-1.0153% |
| `support_zone` | `ma10_to_ma20` | `development_insufficient` | 23/39.1304%/-0.3315%/-0.6382% | 12/41.6667%/-0.7090%/-1.0159% |
| `support_zone` | `ma5_to_ma10` | `not_better_than_segment_baseline` | 182/34.0659%/-0.2188%/-0.5284% | 49/34.6939%/-0.6848%/-0.9923% |
| `tail_above_ma10` | `false` | `validation_insufficient` | 31/38.7097%/-0.0968%/-0.4022% | 20/45.0000%/-0.6968%/-1.0033% |
| `tail_above_ma10` | `true` | `not_better_than_segment_baseline` | 890/36.1798%/-0.5115%/-0.8171% | 263/35.3612%/-0.6839%/-0.9894% |
| `tail_above_ma20` | `false` | `development_insufficient` | 13/38.4615%/0.8238%/0.5189% | 9/44.4444%/-0.8612%/-1.1671% |
| `tail_above_ma20` | `true` | `not_better_than_segment_baseline` | 908/36.2335%/-0.5165%/-0.8221% | 274/35.7664%/-0.6790%/-0.9845% |
| `tail_above_ma5` | `false` | `not_better_than_segment_baseline` | 206/34.9515%/-0.1950%/-0.5043% | 69/37.6812%/-0.5981%/-0.9055% |
| `tail_above_ma5` | `true` | `not_better_than_segment_baseline` | 715/36.6434%/-0.5847%/-0.8892% | 214/35.5140%/-0.7127%/-1.0177% |
| `tail_above_vwap` | `false` | `not_better_than_segment_baseline` | 604/38.2450%/-0.4142%/-0.7206% | 174/36.7816%/-0.7143%/-1.0203% |
| `tail_above_vwap` | `true` | `not_better_than_segment_baseline` | 317/32.4921%/-0.6564%/-0.9604% | 109/34.8624%/-0.6376%/-0.9425% |
| `tail_drawdown_bucket` | `1_to_3` | `not_better_than_segment_baseline` | 315/34.9206%/-0.3550%/-0.6598% | 84/38.0952%/-0.5793%/-0.8854% |
| `tail_drawdown_bucket` | `3_to_5` | `not_better_than_segment_baseline` | 255/37.6471%/-0.5378%/-0.8443% | 85/35.2941%/-0.4926%/-0.7998% |
| `tail_drawdown_bucket` | `below_5` | `not_better_than_segment_baseline` | 277/38.6282%/-0.5958%/-0.9004% | 95/37.8947%/-0.7182%/-1.0240% |
| `tail_drawdown_bucket` | `within_1` | `validation_insufficient` | 74/28.3784%/-0.5980%/-0.9069% | 19/21.0526%/-1.8437%/-2.1383% |
| `tail_range_bucket` | `20_to_50` | `not_better_than_segment_baseline` | 260/35.3846%/-0.7461%/-1.0530% | 82/31.7073%/-0.9359%/-1.2410% |
| `tail_range_bucket` | `50_to_80` | `double_cost_not_positive` | 252/36.9048%/-0.3002%/-0.6043% | 71/40.8451%/-0.0567%/-0.3640% |
| `tail_range_bucket` | `bottom_20` | `double_cost_not_positive` | 346/37.8613%/-0.3289%/-0.6348% | 103/39.8058%/-0.4597%/-0.7669% |
| `tail_range_bucket` | `top_20` | `validation_insufficient` | 63/28.5714%/-1.1875%/-1.4916% | 27/22.2222%/-2.4324%/-2.7287% |
| `tail_return_bucket` | `0_to_3` | `double_cost_not_positive` | 217/39.6313%/-0.2996%/-0.6025% | 55/40.0000%/-0.3021%/-0.6091% |
| `tail_return_bucket` | `3_to_5` | `not_better_than_segment_baseline` | 92/38.0435%/-0.7017%/-1.0068% | 32/25.0000%/-1.3822%/-1.6852% |
| `tail_return_bucket` | `5_to_7` | `validation_insufficient` | 34/32.3529%/-1.4704%/-1.7676% | 16/50.0000%/0.2286%/-0.0873% |
| `tail_return_bucket` | `7_plus` | `development_insufficient` | 23/52.1739%/0.3627%/0.0426% | 8/12.5000%/-4.1188%/-4.3975% |
| `tail_return_bucket` | `below_0` | `not_better_than_segment_baseline` | 555/34.2342%/-0.5172%/-0.8238% | 172/36.6279%/-0.6026%/-0.9085% |

## 成功与失败连续特征

| Feature | Group | N | Median | Q25 | Q75 |
| --- | --- | ---: | ---: | ---: | ---: |
| `context_distance_to_ma5_pct` | `success` | 436 | 6.1675 | 2.2993 | 9.7622 |
| `context_distance_to_ma5_pct` | `failure` | 768 | 6.4063 | 2.3362 | 9.9275 |
| `context_distance_to_ma10_pct` | `success` | 436 | 11.0563 | 6.5888 | 16.9005 |
| `context_distance_to_ma10_pct` | `failure` | 768 | 10.5084 | 6.1576 | 16.4558 |
| `context_distance_to_ma20_pct` | `success` | 436 | 15.5552 | 9.9501 | 23.4343 |
| `context_distance_to_ma20_pct` | `failure` | 768 | 14.7652 | 9.4379 | 22.1904 |
| `context_distance_from_20d_high_pct` | `success` | 436 | -0.0166 | -3.7524 | 0.0000 |
| `context_distance_from_20d_high_pct` | `failure` | 768 | -0.0863 | -4.4901 | 0.0000 |
| `tail_return_from_previous_close_pct` | `success` | 436 | -0.7331 | -3.6403 | 1.6550 |
| `tail_return_from_previous_close_pct` | `failure` | 768 | -1.0375 | -3.3129 | 1.5079 |
| `tail_drawdown_from_session_high_pct` | `success` | 436 | -3.8606 | -5.8205 | -2.2643 |
| `tail_drawdown_from_session_high_pct` | `failure` | 768 | -3.5498 | -5.6199 | -2.0319 |
| `tail_range_position_pct` | `success` | 436 | 27.2727 | 11.3843 | 56.0552 |
| `tail_range_position_pct` | `failure` | 768 | 32.3667 | 12.4173 | 60.5263 |
| `tail_vs_open_pct` | `success` | 436 | -1.0221 | -3.7763 | 1.2617 |
| `tail_vs_open_pct` | `failure` | 768 | -1.1226 | -3.4110 | 1.2340 |
| `tail_vs_vwap_pct` | `success` | 436 | -0.6584 | -1.7830 | 0.4323 |
| `tail_vs_vwap_pct` | `failure` | 768 | -0.5039 | -1.5652 | 0.5520 |
| `tail_vs_ma5_pct` | `success` | 436 | 4.8123 | 0.3363 | 9.9850 |
| `tail_vs_ma5_pct` | `failure` | 768 | 5.0585 | 0.2965 | 9.5298 |
| `tail_vs_ma10_pct` | `success` | 436 | 9.7343 | 4.7418 | 16.5443 |
| `tail_vs_ma10_pct` | `failure` | 768 | 9.0606 | 4.8966 | 15.6430 |
| `tail_vs_ma20_pct` | `success` | 436 | 14.9496 | 8.4957 | 22.9157 |
| `tail_vs_ma20_pct` | `failure` | 768 | 13.4884 | 8.3743 | 21.5943 |
| `afternoon_low_vs_morning_low_pct` | `success` | 436 | 0.3942 | -0.5880 | 1.7546 |
| `afternoon_low_vs_morning_low_pct` | `failure` | 768 | 0.5161 | -0.2666 | 1.9465 |
| `last_15m_return_pct` | `success` | 436 | -0.0989 | -0.4570 | 0.1735 |
| `last_15m_return_pct` | `failure` | 768 | -0.0373 | -0.4236 | 0.2529 |
| `last_15m_volume_ratio` | `success` | 436 | 1.3765 | 1.0802 | 1.8275 |
| `last_15m_volume_ratio` | `failure` | 768 | 1.4065 | 1.0922 | 1.7860 |

## 成功案例

| Date | Stock | Concept | Rank/Offset | Support | Morning | Tail return | Drawdown | Entry | Exit | Net | 2x |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2025-08-26 | 章源钨业 (002378.SZSE) | 军工 | 2/S+1 | `above_vwap_and_ma5` | `held` | 3.8117% | -2.5263% | 13.8900 | 15.6200 | 11.9531% | 11.6234% |
| 2025-08-22 | 智微智能 (001339.SZSE) | 人形机器人 | 3/S+4 | `above_vwap_and_ma5` | `held` | 3.2397% | -1.8850% | 62.4800 | 70.2700 | 11.3715% | 11.0581% |
| 2025-08-08 | 北纬科技 (002148.SZSE) | 无人机 | 1/S+2 | `below_vwap_above_ma5` | `broken_unrecovered` | -10.0289% | -15.1818% | 9.3300 | 10.4100 | 11.2237% | 10.7897% |
| 2025-11-12 | 顺钠股份 (000533.SZSE) | 可控核聚变 | 2/S+4 | `below_vwap_above_ma5` | `false_break_reclaimed` | -6.0545% | -7.2709% | 9.3000 | 10.3700 | 11.1179% | 10.7868% |
| 2025-08-25 | 华胜天成 (600410.SSE) | 华为概念 | 1/S+4 | `above_vwap_and_ma5` | `held` | 8.0416% | -1.7634% | 22.8300 | 25.3600 | 10.5531% | 10.2273% |
| 2025-08-14 | 可立克 (002782.SZSE) | 机器人概念 | 1/S+1 | `below_vwap_above_ma5` | `held` | -6.8886% | -9.8889% | 16.2200 | 18.0000 | 10.5297% | 10.2015% |
| 2025-11-07 | 顺钠股份 (000533.SZSE) | 可控核聚变 | 2/S+1 | `below_vwap_above_ma5` | `held` | 2.6346% | -6.6667% | 8.9700 | 9.9400 | 10.4369% | 10.1070% |
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
| 2025-10-23 | 海鸥住工 (002084.SZSE) | 一带一路 | 2/S+1 | `ma5_to_ma10` | `held` | -10.0000% | -7.5472% | 4.4100 | 4.8500 | 9.6151% | 9.2863% |

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
| 2025-11-11 | 京泉华 (002885.SZSE) | 数据中心 | 1/S+4 | `below_vwap_above_ma5` | `held` | -0.9807% | -5.8491% | 33.3200 | 30.3600 | -8.8699% | -9.1557% |
| 2025-09-22 | 丰山集团 (603810.SSE) | 固态电池 | 1/S+1 | `below_ma20` | `broken_unrecovered` | -5.4897% | -8.2930% | 15.1600 | 13.8900 | -8.5475% | -8.8398% |
| 2025-07-15 | 京运通 (601908.SSE) | 稀土永磁 | 1/S+2 | `below_vwap_above_ma5` | `held` | -8.1897% | -12.5257% | 4.2600 | 3.9100 | -8.4861% | -8.7822% |
| 2025-08-20 | 卧龙电驱 (600580.SSE) | 人形机器人 | 2/S+3 | `below_vwap_above_ma5` | `held` | 3.2059% | -4.6467% | 35.0900 | 32.1900 | -8.4118% | -8.7035% |
| 2025-08-07 | 能科科技 (603859.SSE) | AI智能体 | 1/S+3 | `below_vwap_above_ma5` | `false_break_reclaimed` | -2.4605% | -3.8710% | 43.2100 | 39.7600 | -8.2307% | -8.5263% |
| 2025-07-14 | 日发精机 (002520.SZSE) | 人形机器人 | 1/S+3 | `above_vwap_and_ma5` | `held` | 3.4483% | -2.0408% | 7.2100 | 6.6400 | -8.1622% | -8.4582% |

## 输入指纹

| Input | Rows | Columns | Digest |
| --- | ---: | ---: | --- |
| `tail_candidates` | 1383 | 27 | `sha256:4739a655109f7f51df137f8c5accc5ddde7741859b904b7fa71cca8e9e11dcf3` |
| `tail_features` | 1383 | 73 | `sha256:06511fbbafa5af463a48c712aabbb5dfa63b013e3492658b9f207140761d537f` |
| `tail_minutes` | 83664 | 11 | `sha256:cfc13cc9f272b2ea5ce9898835181c5af64d0d4451907594a4bd5f3779db40b9` |
| `tail_trade_ledger` | 1383 | 86 | `sha256:fbf2a973ed92d460d49845271a303aba1e042da44002dbeb430587a8528cc554` |

## 边界

本报告先保留全部成功与失败案例，再比较事前特征。事件认可 Top3 不是严格历史成员 Top3，后两块也是复用历史；任何局部高胜率都不能直接成为正式规则。
