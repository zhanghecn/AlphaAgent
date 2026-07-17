# AlphaAgent 历史个股主升低吸验证

结论：`time_split_positive_but_regime_confounded`\
身份：历史事件 Top3 代理，不是严格历史全成员 Top3\
买卖：首次 5 分钟收盘不高于前收，下一根开盘买入，D+1 收盘卖出\
交易/匹配/未匹配：`1283/1037/246`\
匹配样本胜率/均值/双倍成本均值：`40.2122%/-0.3303%/-0.6382%`
首次触价充分样本组/两段正期望/两段胜率>50%：`17/0/0`
加入承接确认后充分样本组/两段正期望/高胜率确认：`25/1/0`

## 个股阶段基线

| Phase | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `climax_risk` | `all` | 46 | 30 | 32.6087% | -3.6321% | 0.3441 | -3.9300% | -59.6120% | -60.2683% |
| `climax_risk` | `development` | 34 | 22 | 32.3529% | -3.9320% | 0.3140 | -4.2263% | -52.0705% | -54.5767% |
| `climax_risk` | `validation` | 12 | 8 | 33.3333% | -2.7823% | 0.4419 | -3.0904% | -15.7347% | -24.4235% |
| `continuous_acceleration` | `all` | 61 | 40 | 32.7869% | -1.5697% | 0.5226 | -1.8790% | -41.8985% | -48.6190% |
| `continuous_acceleration` | `development` | 47 | 28 | 29.7872% | -2.1121% | 0.4202 | -2.4180% | -38.3954% | -48.6190% |
| `continuous_acceleration` | `validation` | 14 | 12 | 42.8571% | 0.2511% | 1.1198 | -0.0697% | -5.6865% | -11.5409% |
| `decay` | `all` | 57 | 31 | 36.8421% | -1.0227% | 0.5620 | -1.3274% | -16.9214% | -28.3424% |
| `decay` | `development` | 30 | 18 | 40.0000% | -0.8918% | 0.6678 | -1.1935% | 2.6956% | -16.1936% |
| `decay` | `validation` | 27 | 13 | 33.3333% | -1.1682% | 0.3998 | -1.4761% | -19.1021% | -19.1021% |
| `divergence_restart` | `all` | 64 | 39 | 45.3125% | 0.4653% | 1.2115 | 0.1541% | -1.7880% | -21.2462% |
| `divergence_restart` | `development` | 43 | 26 | 37.2093% | 0.0202% | 1.0087 | -0.2872% | -13.0454% | -21.2462% |
| `divergence_restart` | `validation` | 21 | 13 | 61.9048% | 1.3768% | 1.7011 | 1.0576% | 12.9464% | -15.3648% |
| `first_launch` | `all` | 108 | 53 | 37.0370% | -0.3842% | 0.7656 | -0.6907% | -21.5852% | -36.4528% |
| `first_launch` | `development` | 82 | 38 | 32.9268% | -0.4687% | 0.7156 | -0.7739% | -23.9956% | -32.0571% |
| `first_launch` | `validation` | 26 | 15 | 50.0000% | -0.1176% | 0.9270 | -0.4284% | 3.1714% | -16.3901% |
| `healthy_pullback` | `all` | 76 | 39 | 47.3684% | 0.6637% | 1.4617 | 0.3545% | -14.5647% | -32.5328% |
| `healthy_pullback` | `development` | 60 | 29 | 50.0000% | 0.9424% | 1.8282 | 0.6326% | 1.3880% | -22.2357% |
| `healthy_pullback` | `validation` | 16 | 10 | 37.5000% | -0.3815% | 0.8510 | -0.6884% | -15.7343% | -22.7885% |
| `trend_continuation` | `all` | 472 | 84 | 40.6780% | -0.0014% | 0.9993 | -0.3086% | -11.1371% | -46.2964% |
| `trend_continuation` | `development` | 361 | 53 | 41.2742% | 0.0538% | 1.0268 | -0.2535% | 28.2937% | -16.5162% |
| `trend_continuation` | `validation` | 111 | 31 | 38.7387% | -0.1813% | 0.9266 | -0.4878% | -30.7348% | -46.2964% |
| `unclassified` | `all` | 153 | 58 | 41.8301% | -0.3887% | 0.7491 | -0.7011% | -35.8341% | -40.0446% |
| `unclassified` | `development` | 117 | 39 | 39.3162% | -0.2638% | 0.8205 | -0.5780% | -28.9666% | -32.5544% |
| `unclassified` | `validation` | 36 | 19 | 50.0000% | -0.7945% | 0.5609 | -1.1011% | -9.6680% | -14.2579% |

## 开发候选与验证

| Cohort | Status | Dev trades/days | Dev win/mean | Val trades/days | Val win/mean | Val 2x mean | Val compound/drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `phase=healthy_pullback|intraday_volume_class=contraction` | `validation_insufficient` | 38/21 | 57.8947%/1.8158% | 13/8 | 38.4615%/-1.1428% | -1.4498% | -15.0474%/-20.9114% |
| `phase=trend_continuation|signal_time_bucket=morning_31_120` | `validation_insufficient` | 43/27 | 55.8140%/0.3675% | 12/9 | 50.0000%/-1.6227% | -1.9457% | -13.7691%/-18.7775% |
| `phase=healthy_pullback|transition_rule=open_reclaim` | `validation_insufficient` | 37/25 | 56.7568%/1.8049% | 13/9 | 30.7692%/-0.7353% | -1.0428% | -15.7536%/-21.5201% |

## 时间分段正期望但非高胜率

| Cohort | Dev trades/days | Dev win/mean/2x | Val trades/days | Val win/mean/2x | Val compound/drawdown |
| --- | ---: | ---: | ---: | ---: | ---: |
| `phase=divergence_restart|transition_rule=vwap_reclaim` | 47/30 | 40.4255%/0.4672%/0.1602% | 32/18 | 50.0000%/0.3626%/0.0551% | 2.7055%/-27.3704% |

## 金银环境复核

时间分段正期望候选：`1`；同环境正期望确认：`0`；环境混淆：`1`。


## 正期望候选归因（不增加筛选条件）

| Dimension | Value | Segment | Trades | Days | Win | Mean | 2x mean |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `leader_rank_group` | `rank_1` | `all` | 21 | 19 | 33.3333% | -0.4025% | -0.7021% |
| `leader_rank_group` | `rank_1` | `development` | 17 | 15 | 29.4118% | -0.5980% | -0.8982% |
| `leader_rank_group` | `rank_1` | `validation` | 4 | 4 | 50.0000% | 0.4284% | 0.1313% |
| `leader_rank_group` | `rank_2_3` | `all` | 58 | 39 | 48.2759% | 0.7243% | 0.4144% |
| `leader_rank_group` | `rank_2_3` | `development` | 30 | 22 | 46.6667% | 1.0708% | 0.7599% |
| `leader_rank_group` | `rank_2_3` | `validation` | 28 | 17 | 50.0000% | 0.3532% | 0.0442% |
| `market_regime` | `GOLD/NORMAL` | `all` | 63 | 38 | 38.0952% | -0.2670% | -0.5706% |
| `market_regime` | `GOLD/NORMAL` | `development` | 47 | 30 | 40.4255% | 0.4672% | 0.1602% |
| `market_regime` | `GOLD/NORMAL` | `validation` | 16 | 8 | 31.2500% | -2.4235% | -2.7171% |
| `market_regime` | `SILVER/NORMAL` | `all` | 16 | 10 | 68.7500% | 3.1487% | 2.8272% |
| `market_regime` | `SILVER/NORMAL` | `development` | 0 | 0 | - | - | - |
| `market_regime` | `SILVER/NORMAL` | `validation` | 16 | 10 | 68.7500% | 3.1487% | 2.8272% |
| `relative_strength_state` | `improving_positive` | `all` | 60 | 39 | 48.3333% | 0.9220% | 0.6158% |
| `relative_strength_state` | `improving_positive` | `development` | 31 | 22 | 45.1613% | 1.3627% | 1.0539% |
| `relative_strength_state` | `improving_positive` | `validation` | 29 | 17 | 51.7241% | 0.4509% | 0.1474% |
| `relative_strength_state` | `non_positive` | `all` | 4 | 4 | 25.0000% | -2.4589% | -2.7624% |
| `relative_strength_state` | `non_positive` | `development` | 3 | 3 | 33.3333% | -0.3392% | -0.6462% |
| `relative_strength_state` | `non_positive` | `validation` | 1 | 1 | 0.0000% | -8.8181% | -9.1110% |
| `relative_strength_state` | `positive_not_improving` | `all` | 15 | 12 | 33.3333% | -0.7951% | -1.1070% |
| `relative_strength_state` | `positive_not_improving` | `development` | 13 | 10 | 30.7692% | -1.4824% | -1.7848% |
| `relative_strength_state` | `positive_not_improving` | `validation` | 2 | 2 | 50.0000% | 3.6725% | 3.2988% |
| `volume_class` | `contraction` | `all` | 12 | 12 | 58.3333% | 2.4183% | 2.1103% |
| `volume_class` | `contraction` | `development` | 7 | 7 | 57.1429% | 1.3967% | 1.0950% |
| `volume_class` | `contraction` | `validation` | 5 | 5 | 60.0000% | 3.8484% | 3.5318% |
| `volume_class` | `expansion` | `all` | 21 | 21 | 47.6190% | 0.1121% | -0.1918% |
| `volume_class` | `expansion` | `development` | 13 | 13 | 46.1538% | -0.1153% | -0.4233% |
| `volume_class` | `expansion` | `validation` | 8 | 8 | 50.0000% | 0.4818% | 0.1844% |
| `volume_class` | `explosion` | `all` | 4 | 4 | 50.0000% | 4.7264% | 4.3710% |
| `volume_class` | `explosion` | `development` | 3 | 3 | 33.3333% | 1.3747% | 1.0806% |
| `volume_class` | `explosion` | `validation` | 1 | 1 | 100.0000% | 14.7813% | 14.2422% |
| `volume_class` | `normal` | `all` | 42 | 31 | 38.0952% | -0.3981% | -0.7022% |
| `volume_class` | `normal` | `development` | 24 | 18 | 33.3333% | 0.3981% | 0.0885% |
| `volume_class` | `normal` | `validation` | 18 | 13 | 44.4444% | -1.4598% | -1.7564% |

## 当前边界

本报告立即验证历史规律，但不读取前向账本。只有开发与验证同时通过的组才会列入 confirmed；严格历史概念 Top3 仍因历史成员缺失而不作虚假声明。
