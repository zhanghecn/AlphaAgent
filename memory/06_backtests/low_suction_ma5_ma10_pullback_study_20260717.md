# AlphaAgent MA5/MA10 回调低吸验证

结论：`ma5_ma10_hypothesis_not_confirmed`\
自适应状态/对照优势：`validation_failed/False`\
身份：历史事件 Rank1-3 代理，不是严格历史概念全成员 Top3\
主升：D-1 概念仍在主升，且个股 `收盘 >= MA5 > MA10 > MA20`\
第一轮回调看 D-1 MA5；完成反弹后的第二轮回调看 D-1 MA10\
触发：完成的 5 分钟 bar 触及并收回均线，下一根 5 分钟开盘买入，D+1 收盘卖出\
候选/分钟/信号/交易：`1770/84960/978/978`

## 四种冻结规则对照

| Rule | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `adaptive_ma5_ma10` | `all` | 157 | 63 | 42.6752% | 0.5520% | 1.3007 | 0.2439% | 22.2274% | -27.4588% |
| `adaptive_ma5_ma10` | `development` | 115 | 44 | 45.2174% | 0.8070% | 1.4940 | 0.4997% | 45.0000% | -16.3181% |
| `adaptive_ma5_ma10` | `validation` | 42 | 19 | 35.7143% | -0.1464% | 0.9387 | -0.4565% | -15.7052% | -27.4588% |
| `always_ma10` | `all` | 23 | 16 | 43.4783% | -0.2996% | 0.8528 | -0.6041% | -4.2436% | -18.5863% |
| `always_ma10` | `development` | 14 | 10 | 50.0000% | 0.4819% | 1.3054 | 0.1788% | 3.7248% | -8.5736% |
| `always_ma10` | `validation` | 9 | 6 | 33.3333% | -1.5153% | 0.4487 | -1.8220% | -7.6823% | -12.9666% |
| `always_ma5` | `all` | 220 | 72 | 44.0909% | 0.8410% | 1.4726 | 0.5312% | 56.6380% | -35.8913% |
| `always_ma5` | `development` | 165 | 48 | 47.8788% | 1.1429% | 1.7263 | 0.8330% | 87.6085% | -16.1436% |
| `always_ma5` | `validation` | 55 | 24 | 32.7273% | -0.0650% | 0.9729 | -0.3742% | -16.5081% | -35.8913% |
| `reversed_ma10_ma5` | `all` | 86 | 52 | 46.5116% | 1.0635% | 1.6092 | 0.7519% | 43.1715% | -35.7393% |
| `reversed_ma10_ma5` | `development` | 64 | 36 | 53.1250% | 1.6019% | 2.0922 | 1.2887% | 76.0784% | -10.1312% |
| `reversed_ma10_ma5` | `validation` | 22 | 16 | 27.2727% | -0.5029% | 0.8034 | -0.8096% | -18.6888% | -35.7393% |

## 第一轮与第二轮

| Round | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `first` | `all` | 146 | 62 | 43.8356% | 0.6656% | 1.3778 | 0.3574% | 26.0707% | -25.6936% |
| `first` | `development` | 108 | 43 | 46.2963% | 0.8776% | 1.5533 | 0.5703% | 46.1879% | -17.9521% |
| `first` | `validation` | 38 | 19 | 36.8421% | 0.0630% | 1.0279 | -0.2476% | -13.7612% | -25.6936% |
| `second` | `all` | 11 | 9 | 27.2727% | -0.9559% | 0.6610 | -1.2621% | -3.5227% | -16.4561% |
| `second` | `development` | 7 | 6 | 28.5714% | -0.2817% | 0.8809 | -0.5888% | -1.1803% | -9.3629% |
| `second` | `validation` | 4 | 3 | 25.0000% | -2.1357% | 0.4093 | -2.4404% | -2.3704% | -7.8259% |

## 同一轮次的均线直接对照

| Round/reference | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `first|ma10` | `all` | 12 | 11 | 58.3333% | 0.3019% | 1.2292 | -0.0010% | 0.7084% | -12.1227% |
| `first|ma10` | `development` | 7 | 6 | 71.4286% | 1.2455% | 2.5756 | 0.9465% | 6.2616% | -4.6435% |
| `first|ma10` | `validation` | 5 | 5 | 40.0000% | -1.0190% | 0.5042 | -1.3274% | -5.2260% | -9.9287% |
| `first|ma5` | `all` | 146 | 62 | 43.8356% | 0.6656% | 1.3778 | 0.3574% | 26.0707% | -25.6936% |
| `first|ma5` | `development` | 108 | 43 | 46.2963% | 0.8776% | 1.5533 | 0.5703% | 46.1879% | -17.9521% |
| `first|ma5` | `validation` | 38 | 19 | 36.8421% | 0.0630% | 1.0279 | -0.2476% | -13.7612% | -25.6936% |
| `second|ma10` | `all` | 11 | 9 | 27.2727% | -0.9559% | 0.6610 | -1.2621% | -3.5227% | -16.4561% |
| `second|ma10` | `development` | 7 | 6 | 28.5714% | -0.2817% | 0.8809 | -0.5888% | -1.1803% | -9.3629% |
| `second|ma10` | `validation` | 4 | 3 | 25.0000% | -2.1357% | 0.4093 | -2.4404% | -2.3704% | -7.8259% |
| `second|ma5` | `all` | 74 | 48 | 44.5946% | 1.1870% | 1.6539 | 0.8740% | 51.7114% | -33.7924% |
| `second|ma5` | `development` | 57 | 34 | 50.8772% | 1.6457% | 2.0619 | 1.3307% | 79.6542% | -9.3760% |
| `second|ma5` | `validation` | 17 | 14 | 23.5294% | -0.3511% | 0.8702 | -0.6573% | -15.5537% | -33.7924% |

## 自适应规则五个时间块

| Rule | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `adaptive_ma5_ma10` | `block_1` | 41 | 14 | 36.5854% | 0.2660% | 1.1338 | -0.0403% | -5.4657% | -12.6097% |
| `adaptive_ma5_ma10` | `block_2` | 36 | 16 | 47.2222% | 1.2282% | 1.7438 | 0.9212% | 25.5986% | -6.8752% |
| `adaptive_ma5_ma10` | `block_3` | 38 | 14 | 52.6316% | 0.9918% | 1.8034 | 0.6831% | 22.1219% | -3.7693% |
| `adaptive_ma5_ma10` | `block_4` | 24 | 10 | 20.8333% | -2.6085% | 0.1694 | -2.9126% | -27.1588% | -27.4588% |
| `adaptive_ma5_ma10` | `block_5` | 18 | 9 | 55.5556% | 3.1364% | 3.2620 | 2.8184% | 15.7240% | -7.1902% |

## 主升口径敏感性

| Universe | Segment | Trades | Days | Win | Mean | PF | 2x mean | Compound | Drawdown |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `concept_main_rise` | `all` | 280 | 75 | 40.3571% | -0.0364% | 0.9815 | -0.3414% | -18.2667% | -40.2302% |
| `concept_main_rise` | `development` | 215 | 51 | 41.3953% | 0.0710% | 1.0394 | -0.2348% | -5.7089% | -21.5467% |
| `concept_main_rise` | `validation` | 65 | 24 | 36.9231% | -0.3915% | 0.8434 | -0.6939% | -13.3181% | -33.1713% |
| `stock_strong_main_rise` | `all` | 105 | 56 | 40.9524% | 0.3240% | 1.1944 | 0.0146% | 1.3259% | -27.7851% |
| `stock_strong_main_rise` | `development` | 71 | 39 | 42.2535% | 0.2584% | 1.1746 | -0.0499% | 8.4017% | -21.5182% |
| `stock_strong_main_rise` | `validation` | 34 | 17 | 38.2353% | 0.4609% | 1.2240 | 0.1492% | -6.5274% | -27.7851% |
| `stock_trend_order` | `all` | 157 | 63 | 42.6752% | 0.5520% | 1.3007 | 0.2439% | 22.2274% | -27.4588% |
| `stock_trend_order` | `development` | 115 | 44 | 45.2174% | 0.8070% | 1.4940 | 0.4997% | 45.0000% | -16.3181% |
| `stock_trend_order` | `validation` | 42 | 19 | 35.7143% | -0.1464% | 0.9387 | -0.4565% | -15.7052% | -27.4588% |

## 金银、量能与龙位归因

这些表只解释结果，不增加筛选条件，也不参与四种规则臂的选择。

| Dimension | Round/value | Segment | Trades | Days | Win | Mean | 2x mean |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `round_x_daily_volume_class` | `first|contraction` | `all` | 15 | 15 | 46.6667% | 1.1909% | 0.8811% |
| `round_x_daily_volume_class` | `first|contraction` | `development` | 11 | 11 | 54.5455% | 2.0971% | 1.7863% |
| `round_x_daily_volume_class` | `first|contraction` | `validation` | 4 | 4 | 25.0000% | -1.3013% | -1.6082% |
| `round_x_daily_volume_class` | `first|expansion` | `all` | 47 | 30 | 48.9362% | 1.0586% | 0.7500% |
| `round_x_daily_volume_class` | `first|expansion` | `development` | 35 | 22 | 48.5714% | 0.6766% | 0.3718% |
| `round_x_daily_volume_class` | `first|expansion` | `validation` | 12 | 8 | 50.0000% | 2.1726% | 1.8529% |
| `round_x_daily_volume_class` | `first|explosion` | `all` | 21 | 16 | 47.6190% | 1.0235% | 0.7098% |
| `round_x_daily_volume_class` | `first|explosion` | `development` | 18 | 13 | 50.0000% | 1.4098% | 1.0954% |
| `round_x_daily_volume_class` | `first|explosion` | `validation` | 3 | 3 | 33.3333% | -1.2943% | -1.6035% |
| `round_x_daily_volume_class` | `first|normal` | `all` | 63 | 43 | 38.0952% | 0.1280% | -0.1776% |
| `round_x_daily_volume_class` | `first|normal` | `development` | 44 | 30 | 40.9091% | 0.5149% | 0.2093% |
| `round_x_daily_volume_class` | `first|normal` | `validation` | 19 | 13 | 31.5789% | -0.7679% | -1.0738% |
| `round_x_daily_volume_class` | `second|contraction` | `all` | 4 | 4 | 25.0000% | -4.2065% | -4.5060% |
| `round_x_daily_volume_class` | `second|contraction` | `development` | 3 | 3 | 33.3333% | -1.8227% | -2.1279% |
| `round_x_daily_volume_class` | `second|contraction` | `validation` | 1 | 1 | 0.0000% | -11.3582% | -11.6403% |
| `round_x_daily_volume_class` | `second|expansion` | `all` | 1 | 1 | 0.0000% | -1.7340% | -2.0420% |
| `round_x_daily_volume_class` | `second|expansion` | `development` | 0 | 0 | - | - | - |
| `round_x_daily_volume_class` | `second|expansion` | `validation` | 1 | 1 | 0.0000% | -1.7340% | -2.0420% |
| `round_x_daily_volume_class` | `second|normal` | `all` | 6 | 5 | 33.3333% | 1.3409% | 1.0305% |
| `round_x_daily_volume_class` | `second|normal` | `development` | 4 | 3 | 25.0000% | 0.8740% | 0.5656% |
| `round_x_daily_volume_class` | `second|normal` | `validation` | 2 | 2 | 50.0000% | 2.2746% | 1.9604% |
| `round_x_intraday_volume_class` | `first|contraction` | `all` | 25 | 21 | 24.0000% | -1.9266% | -2.2229% |
| `round_x_intraday_volume_class` | `first|contraction` | `development` | 18 | 15 | 22.2222% | -2.3711% | -2.6643% |
| `round_x_intraday_volume_class` | `first|contraction` | `validation` | 7 | 6 | 28.5714% | -0.7838% | -1.0881% |
| `round_x_intraday_volume_class` | `first|expansion` | `all` | 22 | 21 | 50.0000% | -0.1938% | -0.4977% |
| `round_x_intraday_volume_class` | `first|expansion` | `development` | 15 | 14 | 53.3333% | 0.6945% | 0.3916% |
| `round_x_intraday_volume_class` | `first|expansion` | `validation` | 7 | 7 | 42.8571% | -2.0974% | -2.4033% |
| `round_x_intraday_volume_class` | `first|explosion` | `all` | 14 | 12 | 42.8571% | 0.5277% | 0.2244% |
| `round_x_intraday_volume_class` | `first|explosion` | `development` | 13 | 11 | 38.4615% | -0.0214% | -0.3231% |
| `round_x_intraday_volume_class` | `first|explosion` | `validation` | 1 | 1 | 100.0000% | 7.6666% | 7.3413% |
| `round_x_intraday_volume_class` | `first|missing` | `all` | 62 | 36 | 53.2258% | 2.0808% | 1.7656% |
| `round_x_intraday_volume_class` | `first|missing` | `development` | 45 | 26 | 57.7778% | 2.2845% | 1.9697% |
| `round_x_intraday_volume_class` | `first|missing` | `validation` | 17 | 10 | 41.1765% | 1.5417% | 1.2255% |
| `round_x_intraday_volume_class` | `first|normal` | `all` | 23 | 20 | 34.7826% | 0.5741% | 0.2648% |
| `round_x_intraday_volume_class` | `first|normal` | `development` | 17 | 15 | 41.1765% | 1.4423% | 1.1315% |
| `round_x_intraday_volume_class` | `first|normal` | `validation` | 6 | 5 | 16.6667% | -1.8857% | -2.1908% |
| `round_x_intraday_volume_class` | `second|expansion` | `all` | 2 | 2 | 0.0000% | -3.9434% | -4.2466% |
| `round_x_intraday_volume_class` | `second|expansion` | `development` | 2 | 2 | 0.0000% | -3.9434% | -4.2466% |
| `round_x_intraday_volume_class` | `second|expansion` | `validation` | 0 | 0 | - | - | - |
| `round_x_intraday_volume_class` | `second|explosion` | `all` | 1 | 1 | 0.0000% | -3.9951% | -4.2942% |
| `round_x_intraday_volume_class` | `second|explosion` | `development` | 1 | 1 | 0.0000% | -3.9951% | -4.2942% |
| `round_x_intraday_volume_class` | `second|explosion` | `validation` | 0 | 0 | - | - | - |
| `round_x_intraday_volume_class` | `second|missing` | `all` | 5 | 4 | 40.0000% | 0.5725% | 0.2644% |
| `round_x_intraday_volume_class` | `second|missing` | `development` | 2 | 2 | 50.0000% | 5.0181% | 4.7034% |
| `round_x_intraday_volume_class` | `second|missing` | `validation` | 3 | 2 | 33.3333% | -2.3911% | -2.6949% |
| `round_x_intraday_volume_class` | `second|normal` | `all` | 3 | 3 | 33.3333% | -0.4986% | -0.8058% |
| `round_x_intraday_volume_class` | `second|normal` | `development` | 2 | 2 | 50.0000% | -0.0632% | -0.3703% |
| `round_x_intraday_volume_class` | `second|normal` | `validation` | 1 | 1 | 0.0000% | -1.3695% | -1.6768% |
| `round_x_leader_rank_group` | `first|rank_1` | `all` | 40 | 29 | 55.0000% | 1.8982% | 1.5824% |
| `round_x_leader_rank_group` | `first|rank_1` | `development` | 34 | 23 | 58.8235% | 2.3157% | 1.9986% |
| `round_x_leader_rank_group` | `first|rank_1` | `validation` | 6 | 6 | 33.3333% | -0.4678% | -0.7758% |
| `round_x_leader_rank_group` | `first|rank_2_3` | `all` | 106 | 56 | 39.6226% | 0.2004% | -0.1049% |
| `round_x_leader_rank_group` | `first|rank_2_3` | `development` | 74 | 38 | 40.5405% | 0.2168% | -0.0860% |
| `round_x_leader_rank_group` | `first|rank_2_3` | `validation` | 32 | 18 | 37.5000% | 0.1625% | -0.1486% |
| `round_x_leader_rank_group` | `second|rank_1` | `all` | 3 | 3 | 33.3333% | 2.0137% | 1.7042% |
| `round_x_leader_rank_group` | `second|rank_1` | `development` | 3 | 3 | 33.3333% | 2.0137% | 1.7042% |
| `round_x_leader_rank_group` | `second|rank_1` | `validation` | 0 | 0 | - | - | - |
| `round_x_leader_rank_group` | `second|rank_2_3` | `all` | 8 | 7 | 25.0000% | -2.0695% | -2.3744% |
| `round_x_leader_rank_group` | `second|rank_2_3` | `development` | 4 | 4 | 25.0000% | -2.0033% | -2.3085% |
| `round_x_leader_rank_group` | `second|rank_2_3` | `validation` | 4 | 3 | 25.0000% | -2.1357% | -2.4404% |
| `round_x_market_regime` | `first|GOLD/NORMAL` | `all` | 129 | 53 | 42.6357% | 0.3615% | 0.0546% |
| `round_x_market_regime` | `first|GOLD/NORMAL` | `development` | 108 | 43 | 46.2963% | 0.8776% | 0.5703% |
| `round_x_market_regime` | `first|GOLD/NORMAL` | `validation` | 21 | 10 | 23.8095% | -2.2925% | -2.5973% |
| `round_x_market_regime` | `first|SILVER/NORMAL` | `all` | 17 | 9 | 52.9412% | 2.9727% | 2.6549% |
| `round_x_market_regime` | `first|SILVER/NORMAL` | `development` | 0 | 0 | - | - | - |
| `round_x_market_regime` | `first|SILVER/NORMAL` | `validation` | 17 | 9 | 52.9412% | 2.9727% | 2.6549% |
| `round_x_market_regime` | `second|GOLD/NORMAL` | `all` | 10 | 8 | 20.0000% | -1.6434% | -1.9480% |
| `round_x_market_regime` | `second|GOLD/NORMAL` | `development` | 7 | 6 | 28.5714% | -0.2817% | -0.5888% |
| `round_x_market_regime` | `second|GOLD/NORMAL` | `validation` | 3 | 2 | 0.0000% | -4.8206% | -5.1197% |
| `round_x_market_regime` | `second|SILVER/NORMAL` | `all` | 1 | 1 | 100.0000% | 5.9188% | 5.5976% |
| `round_x_market_regime` | `second|SILVER/NORMAL` | `development` | 0 | 0 | - | - | - |
| `round_x_market_regime` | `second|SILVER/NORMAL` | `validation` | 1 | 1 | 100.0000% | 5.9188% | 5.5976% |

## 研究边界

本报告立即检验历史因果规则，但 blocks 4-5 已在旧研究中出现，不是未读外层留出。严格历史 Top3、正式策略胜率和生产规则继续关闭。
