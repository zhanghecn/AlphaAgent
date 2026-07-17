# Low-suction Daily Leader Phase Hold Study

- Conclusion: `no_stable_daily_phase_edge`
- Evidence: event-recognition proxy, not strict historical Top3
- Entry/exit: D open / D+1 official close
- Late blocks are reused diagnostics, not untouched validation
- Observations/trades/stocks/concepts: `1425/1425/318/35`

完整机器账本：
`low_suction_daily_phase_hold_study_20260717.json`\
JSON SHA256：
`78bdb2c83d6821be375bc7cec35506423d6a3989ea1390c2fc8502e5f3f6aaae`

## 结论

本轮把 505 个原始认可候选重建为逐股每日阶段，固定只观察每段认可后的
`S..S+3` 收盘状态，再按下一交易日开盘买入、再下一交易日收盘卖出。1,425 个主板
观察中 1,382 笔闭合，43 笔因 D 日开盘已涨停而拒单；没有使用不可成交涨停价，
也没有读取分钟买点、旧低吸成交、当前成员、打板账本或外层留出。

结果没有找到胜率超过 60% 且早晚稳定的阶段。首次启动 176 笔闭合，胜率
`36.9318%`、均值 `-0.5580%`；连续加速 99 笔为
`35.3535%/-2.2254%`；普通趋势延续 578 笔为
`42.3875%/-0.0630%`，双倍成本后 `-0.3676%`。仅仅确认主升、站在均线上或
刚出现启动板，都不足以形成高胜率低吸母样本。

高潮风险得到比上一轮更直接的可执行证据。连续三次以上强势日共有 77 笔闭合，胜率
`38.9610%`、均值 `-3.7985%`、利润因子 `0.3728`、5% 尾部
`-19.8584%`；早三块和后两块均值分别为 `-4.3219%/-2.7099%`。
北化股份、京运通、先锋电子和新疆火炬的 D+1 收盘损失分别达到
`-24.0362%/-21.7975%/-20.5624%/-20.4998%`。连续二次强势日也不是低风险
主升：前三块均值 `-2.9859%`，后两块普通成本勉强持平但双倍成本仍为负。

两个阶段有正均值，但都不满足胜率、样本和集中度门槛：

- 分歧再启动 98 笔，胜率 `47.9592%`、均值 `+0.8846%`、PF `1.3203`、双倍成本
  `+0.5758%`。前三块只有 `43.5484%/+0.2206%`，双倍成本转为 `-0.0866%`；
  后两块为 `55.5556%/+2.0281%`，只有 36 笔、18 日。五块中 block 1/4 为负，
  block 5 的 `70%/+5.0082%` 完全等同银手指样本。
- 健康回撤 87 笔，胜率 `41.3793%`、均值 `+0.4971%`、PF `1.2554`、双倍成本
  `+0.1889%`。早晚均值都为正，但后段只有 19 笔、13 日；block 3 为负，block 5
  双倍成本也为负。它依赖少数右尾，不能用正均值掩盖低胜率。

量能、相对强弱和金银分层也没有生成可用规则。分歧再启动且三日相对概念强度改善的
77 笔为 `51.9481%/+1.7445%`，双倍成本 `+1.4346%`；但早晚胜率只有
`47.7273%/57.5758%`，仍均低于 60%，正利润又明显集中在单月。银手指下分歧再启动
表面达到 `70%/+5.0082%`，只有 20 笔、10 日，全部位于后段，单月贡献
`85.7876%`、单一概念贡献 `44.3203%`。缩量再启动的 `61.5385%/+3.4958%`
也只有 13 笔、13 日，早段胜率仅 50%。这些只能作为待前向复核的现象，不能冻结为
“银手指 + 缩量 + 再启动”规则。

逐股对照解释了为什么日线阶段仍不够。同为分歧再启动，中油资本为 `+18.0582%`，
中电鑫龙为 `-15.9049%`；同为健康回撤，豫能控股为 `+19.7661%`，天融信为
`-15.3073%`。日线阶段可以有效排除高潮，却还不能区分次日是否出现真实承接。

因此结论固定为 `no_stable_daily_phase_edge`。当前可以确认的规律是“不追连续加速和
高潮”，而不是已经找到高胜率低吸。按预注册门槛，没有阶段有资格继续在同一代理样本上
搜索 5 分钟买点；否则只会从已看过的银手指/固态电池后段继续加条件。正式下一步只能
等待严格历史 Top3/证券状态，或另立完全独立的启动前情绪埋伏协议并使用新前向样本。

## Phase Baselines

| Phase | Segment | Closed | Days | Win | Mean | PF | 2x mean | Label |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `climax_risk` | `all` | 77 | 47 | 38.9610% | -3.7985% | 0.3728 | -4.0749% | `not_positive_candidate` |
| `climax_risk` | `early_1_3` | 52 | 30 | 40.3846% | -4.3219% | 0.3130 | -4.5986% | `not_positive_candidate` |
| `climax_risk` | `late_4_5` | 25 | 17 | 36.0000% | -2.7099% | 0.5133 | -2.9855% | `insufficient_sample` |
| `continuous_acceleration` | `all` | 99 | 52 | 35.3535% | -2.2254% | 0.5272 | -2.5084% | `not_positive_candidate` |
| `continuous_acceleration` | `early_1_3` | 74 | 36 | 31.0811% | -2.9859% | 0.4110 | -3.2702% | `not_positive_candidate` |
| `continuous_acceleration` | `late_4_5` | 25 | 16 | 48.0000% | 0.0256% | 1.0070 | -0.2532% | `insufficient_sample` |
| `decay` | `all` | 81 | 41 | 39.5062% | -1.1207% | 0.5800 | -1.4214% | `not_positive_candidate` |
| `decay` | `early_1_3` | 51 | 27 | 47.0588% | -0.5934% | 0.7775 | -0.8937% | `not_positive_candidate` |
| `decay` | `late_4_5` | 30 | 14 | 26.6667% | -2.0172% | 0.2448 | -2.3186% | `insufficient_sample` |
| `divergence_restart` | `all` | 98 | 54 | 47.9592% | 0.8846% | 1.3203 | 0.5758% | `not_positive_candidate` |
| `divergence_restart` | `early_1_3` | 62 | 36 | 43.5484% | 0.2206% | 1.0678 | -0.0866% | `not_positive_candidate` |
| `divergence_restart` | `late_4_5` | 36 | 18 | 55.5556% | 2.0281% | 2.0583 | 1.7166% | `insufficient_sample` |
| `first_launch` | `all` | 176 | 61 | 36.9318% | -0.5580% | 0.7916 | -0.8575% | `not_positive_candidate` |
| `first_launch` | `early_1_3` | 137 | 43 | 32.8467% | -0.8190% | 0.6981 | -1.1182% | `not_positive_candidate` |
| `first_launch` | `late_4_5` | 39 | 18 | 51.2821% | 0.3587% | 1.1406 | 0.0583% | `insufficient_sample` |
| `healthy_pullback` | `all` | 87 | 47 | 41.3793% | 0.4971% | 1.2554 | 0.1889% | `not_positive_candidate` |
| `healthy_pullback` | `early_1_3` | 68 | 34 | 42.6471% | 0.5329% | 1.2988 | 0.2236% | `not_positive_candidate` |
| `healthy_pullback` | `late_4_5` | 19 | 13 | 36.8421% | 0.3690% | 1.1459 | 0.0644% | `insufficient_sample` |
| `trend_continuation` | `all` | 578 | 87 | 42.3875% | -0.0630% | 0.9748 | -0.3676% | `not_positive_candidate` |
| `trend_continuation` | `early_1_3` | 437 | 55 | 41.6476% | 0.0054% | 1.0022 | -0.2986% | `not_positive_candidate` |
| `trend_continuation` | `late_4_5` | 141 | 32 | 44.6809% | -0.2748% | 0.8950 | -0.5814% | `not_positive_candidate` |
| `unclassified` | `all` | 186 | 64 | 38.7097% | -0.3768% | 0.8102 | -0.6827% | `not_positive_candidate` |
| `unclassified` | `early_1_3` | 143 | 42 | 40.5594% | -0.1767% | 0.9036 | -0.4847% | `not_positive_candidate` |
| `unclassified` | `late_4_5` | 43 | 22 | 32.5581% | -1.0422% | 0.5819 | -1.3413% | `not_positive_candidate` |

## Candidate Evaluation

| Phase | Eligible | Early | Late | Positive blocks | Concentration | Stable high-win |
| --- | --- | --- | --- | ---: | --- | --- |
| `climax_risk` | `false` | `not_positive_candidate` | `insufficient_sample` | 1 | `false` | `false` |
| `continuous_acceleration` | `true` | `not_positive_candidate` | `insufficient_sample` | 1 | `false` | `false` |
| `decay` | `false` | `not_positive_candidate` | `insufficient_sample` | 3 | `false` | `false` |
| `divergence_restart` | `true` | `not_positive_candidate` | `insufficient_sample` | 3 | `false` | `false` |
| `first_launch` | `true` | `not_positive_candidate` | `insufficient_sample` | 3 | `false` | `false` |
| `healthy_pullback` | `true` | `not_positive_candidate` | `insufficient_sample` | 4 | `false` | `false` |
| `trend_continuation` | `true` | `not_positive_candidate` | `not_positive_candidate` | 2 | `false` | `false` |
| `unclassified` | `false` | `not_positive_candidate` | `not_positive_candidate` | 3 | `false` | `false` |

## Attribution Diagnostics

These rows are complete descriptive partitions, not selected entry filters.

| Phase | Dimension | Cohort | Closed | Days | Win | Mean | PF | 2x mean | Label |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `climax_risk` | `market_regime` | `GOLD/NORMAL` | 68 | 40 | 38.2353% | -4.1772% | 0.3227 | -4.4508% | `not_positive_candidate` |
| `climax_risk` | `market_regime` | `SILVER/NORMAL` | 9 | 7 | 44.4444% | -0.9374% | 0.8202 | -1.2345% | `insufficient_sample` |
| `continuous_acceleration` | `market_regime` | `GOLD/DANGER` | 1 | 1 | 0.0000% | -5.5425% | 0.0000 | -5.8409% | `insufficient_sample` |
| `continuous_acceleration` | `market_regime` | `GOLD/NORMAL` | 83 | 42 | 33.7349% | -2.5786% | 0.4657 | -2.8584% | `not_positive_candidate` |
| `continuous_acceleration` | `market_regime` | `SILVER/DANGER` | 0 | 0 | - | - | - | - | `insufficient_sample` |
| `continuous_acceleration` | `market_regime` | `SILVER/NORMAL` | 15 | 9 | 46.6667% | -0.0499% | 0.9875 | -0.3496% | `insufficient_sample` |
| `decay` | `market_regime` | `GOLD/NORMAL` | 70 | 36 | 37.1429% | -1.3197% | 0.5457 | -1.6191% | `not_positive_candidate` |
| `decay` | `market_regime` | `SILVER/NORMAL` | 11 | 5 | 54.5455% | 0.1459% | 1.1251 | -0.1636% | `insufficient_sample` |
| `divergence_restart` | `market_regime` | `GOLD/NORMAL` | 78 | 44 | 42.3077% | -0.1727% | 0.9463 | -0.4789% | `not_positive_candidate` |
| `divergence_restart` | `market_regime` | `SILVER/NORMAL` | 20 | 10 | 70.0000% | 5.0082% | 6.0688 | 4.6894% | `insufficient_sample` |
| `first_launch` | `market_regime` | `GOLD/DANGER` | 2 | 1 | 100.0000% | 15.2799% | - | 14.9434% | `insufficient_sample` |
| `first_launch` | `market_regime` | `GOLD/NORMAL` | 155 | 50 | 33.5484% | -0.8338% | 0.7033 | -1.1326% | `not_positive_candidate` |
| `first_launch` | `market_regime` | `SILVER/NORMAL` | 19 | 10 | 57.8947% | 0.0241% | 1.0128 | -0.2760% | `insufficient_sample` |
| `healthy_pullback` | `market_regime` | `GOLD/NORMAL` | 78 | 41 | 43.5897% | 0.5505% | 1.3023 | 0.2409% | `not_positive_candidate` |
| `healthy_pullback` | `market_regime` | `SILVER/NORMAL` | 9 | 6 | 22.2222% | 0.0342% | 1.0113 | -0.2618% | `insufficient_sample` |
| `trend_continuation` | `market_regime` | `GOLD/NORMAL` | 501 | 71 | 40.7186% | -0.1890% | 0.9262 | -0.4927% | `not_positive_candidate` |
| `trend_continuation` | `market_regime` | `SILVER/DANGER` | 2 | 1 | 50.0000% | 6.5210% | 3.5571 | 6.1345% | `insufficient_sample` |
| `trend_continuation` | `market_regime` | `SILVER/NORMAL` | 75 | 15 | 53.3333% | 0.6034% | 1.2914 | 0.2951% | `insufficient_sample` |
| `unclassified` | `market_regime` | `GOLD/NORMAL` | 170 | 54 | 38.2353% | -0.4601% | 0.7752 | -0.7667% | `not_positive_candidate` |
| `unclassified` | `market_regime` | `SILVER/NORMAL` | 16 | 10 | 43.7500% | 0.5092% | 1.3842 | 0.2096% | `insufficient_sample` |
| `climax_risk` | `relative_strength_state` | `improving_positive` | 66 | 39 | 39.3939% | -3.6816% | 0.3829 | -3.9584% | `not_positive_candidate` |
| `climax_risk` | `relative_strength_state` | `positive_not_improving` | 11 | 11 | 36.3636% | -4.5002% | 0.3175 | -4.7737% | `insufficient_sample` |
| `continuous_acceleration` | `relative_strength_state` | `improving_positive` | 93 | 52 | 36.5591% | -2.2725% | 0.5270 | -2.5559% | `not_positive_candidate` |
| `continuous_acceleration` | `relative_strength_state` | `positive_not_improving` | 6 | 6 | 16.6667% | -1.4958% | 0.5312 | -1.7711% | `insufficient_sample` |
| `decay` | `relative_strength_state` | `improving_positive` | 37 | 26 | 35.1351% | -1.7140% | 0.5239 | -2.0079% | `not_positive_candidate` |
| `decay` | `relative_strength_state` | `non_positive` | 22 | 15 | 36.3636% | -1.7654% | 0.2415 | -2.0722% | `insufficient_sample` |
| `decay` | `relative_strength_state` | `positive_not_improving` | 22 | 12 | 50.0000% | 0.5219% | 1.3615 | 0.2158% | `insufficient_sample` |
| `divergence_restart` | `relative_strength_state` | `improving_positive` | 77 | 46 | 51.9481% | 1.7445% | 1.7834 | 1.4346% | `positive_candidate` |
| `divergence_restart` | `relative_strength_state` | `non_positive` | 5 | 5 | 20.0000% | -3.7694% | 0.2576 | -4.0837% | `insufficient_sample` |
| `divergence_restart` | `relative_strength_state` | `positive_not_improving` | 16 | 12 | 37.5000% | -1.7991% | 0.6102 | -2.1011% | `insufficient_sample` |
| `first_launch` | `relative_strength_state` | `improving_positive` | 173 | 60 | 36.9942% | -0.5317% | 0.8009 | -0.8316% | `not_positive_candidate` |
| `first_launch` | `relative_strength_state` | `non_positive` | 2 | 2 | 0.0000% | -4.5804% | 0.0000 | -4.8319% | `insufficient_sample` |
| `first_launch` | `relative_strength_state` | `positive_not_improving` | 1 | 1 | 100.0000% | 2.9377% | - | 2.6085% | `insufficient_sample` |
| `healthy_pullback` | `relative_strength_state` | `improving_positive` | 10 | 10 | 60.0000% | 1.0481% | 1.9423 | 0.7394% | `insufficient_sample` |
| `healthy_pullback` | `relative_strength_state` | `non_positive` | 26 | 18 | 26.9231% | -0.6444% | 0.6526 | -0.9463% | `insufficient_sample` |
| `healthy_pullback` | `relative_strength_state` | `positive_not_improving` | 51 | 38 | 45.0980% | 0.9711% | 1.4502 | 0.6596% | `not_positive_candidate` |
| `trend_continuation` | `relative_strength_state` | `improving_positive` | 182 | 69 | 46.7033% | 0.0976% | 1.0410 | -0.2077% | `not_positive_candidate` |
| `trend_continuation` | `relative_strength_state` | `non_positive` | 33 | 21 | 30.3030% | -0.6549% | 0.7031 | -0.9577% | `not_positive_candidate` |
| `trend_continuation` | `relative_strength_state` | `positive_not_improving` | 363 | 82 | 41.3223% | -0.0896% | 0.9653 | -0.3941% | `not_positive_candidate` |
| `unclassified` | `relative_strength_state` | `improving_positive` | 22 | 20 | 18.1818% | -1.1909% | 0.4851 | -1.4810% | `insufficient_sample` |
| `unclassified` | `relative_strength_state` | `missing` | 0 | 0 | - | - | - | - | `insufficient_sample` |
| `unclassified` | `relative_strength_state` | `non_positive` | 122 | 52 | 42.6230% | -0.2041% | 0.8884 | -0.5145% | `not_positive_candidate` |
| `unclassified` | `relative_strength_state` | `positive_not_improving` | 42 | 28 | 38.0952% | -0.4519% | 0.8007 | -0.7531% | `not_positive_candidate` |
| `climax_risk` | `volume_class` | `contraction` | 25 | 22 | 36.0000% | -3.2316% | 0.4629 | -3.5099% | `insufficient_sample` |
| `climax_risk` | `volume_class` | `expansion` | 18 | 16 | 44.4444% | -2.0081% | 0.5993 | -2.2817% | `insufficient_sample` |
| `climax_risk` | `volume_class` | `explosion` | 20 | 17 | 35.0000% | -5.2210% | 0.1915 | -5.4969% | `insufficient_sample` |
| `climax_risk` | `volume_class` | `normal` | 14 | 12 | 42.8571% | -5.0808% | 0.2632 | -5.3578% | `insufficient_sample` |
| `continuous_acceleration` | `volume_class` | `contraction` | 14 | 12 | 57.1429% | 0.0480% | 1.0137 | -0.1887% | `insufficient_sample` |
| `continuous_acceleration` | `volume_class` | `expansion` | 22 | 21 | 31.8182% | -3.0838% | 0.2640 | -3.3728% | `insufficient_sample` |
| `continuous_acceleration` | `volume_class` | `explosion` | 35 | 23 | 42.8571% | -1.3345% | 0.7123 | -1.6302% | `not_positive_candidate` |
| `continuous_acceleration` | `volume_class` | `normal` | 28 | 23 | 17.8571% | -3.8014% | 0.3446 | -4.0867% | `insufficient_sample` |
| `decay` | `volume_class` | `contraction` | 13 | 11 | 38.4615% | -0.8215% | 0.6009 | -1.1212% | `insufficient_sample` |
| `decay` | `volume_class` | `expansion` | 21 | 16 | 52.3810% | 0.1385% | 1.0539 | -0.1635% | `insufficient_sample` |
| `decay` | `volume_class` | `explosion` | 14 | 12 | 21.4286% | -3.1555% | 0.1890 | -3.4533% | `insufficient_sample` |
| `decay` | `volume_class` | `normal` | 33 | 21 | 39.3939% | -1.1767% | 0.5205 | -1.4781% | `not_positive_candidate` |
| `divergence_restart` | `volume_class` | `contraction` | 13 | 13 | 61.5385% | 3.4958% | 2.6724 | 3.1974% | `insufficient_sample` |
| `divergence_restart` | `volume_class` | `expansion` | 25 | 25 | 44.0000% | 1.0940% | 1.5232 | 0.7818% | `insufficient_sample` |
| `divergence_restart` | `volume_class` | `explosion` | 6 | 6 | 33.3333% | 0.2816% | 1.0612 | -0.0288% | `insufficient_sample` |
| `divergence_restart` | `volume_class` | `normal` | 54 | 35 | 48.1481% | 0.2260% | 1.0746 | -0.0835% | `not_positive_candidate` |
| `first_launch` | `volume_class` | `contraction` | 6 | 6 | 33.3333% | -2.3216% | 0.2655 | -2.5750% | `insufficient_sample` |
| `first_launch` | `volume_class` | `expansion` | 66 | 40 | 40.9091% | -0.1439% | 0.9406 | -0.4464% | `not_positive_candidate` |
| `first_launch` | `volume_class` | `explosion` | 59 | 32 | 35.5932% | -0.5894% | 0.7813 | -0.8906% | `not_positive_candidate` |
| `first_launch` | `volume_class` | `normal` | 45 | 30 | 33.3333% | -0.8891% | 0.7000 | -1.1880% | `not_positive_candidate` |
| `healthy_pullback` | `volume_class` | `contraction` | 39 | 25 | 33.3333% | 0.1727% | 1.0866 | -0.1307% | `not_positive_candidate` |
| `healthy_pullback` | `volume_class` | `normal` | 48 | 38 | 47.9167% | 0.7607% | 1.3988 | 0.4485% | `not_positive_candidate` |
| `trend_continuation` | `volume_class` | `contraction` | 12 | 11 | 41.6667% | 0.1974% | 1.1133 | -0.1121% | `insufficient_sample` |
| `trend_continuation` | `volume_class` | `expansion` | 184 | 62 | 46.7391% | 0.4742% | 1.1975 | 0.1700% | `not_positive_candidate` |
| `trend_continuation` | `volume_class` | `explosion` | 157 | 62 | 40.1274% | -0.2919% | 0.8867 | -0.5967% | `not_positive_candidate` |
| `trend_continuation` | `volume_class` | `normal` | 225 | 74 | 40.4444% | -0.3564% | 0.8610 | -0.6609% | `not_positive_candidate` |
| `unclassified` | `volume_class` | `contraction` | 55 | 32 | 34.5455% | -0.9702% | 0.5398 | -1.2738% | `not_positive_candidate` |
| `unclassified` | `volume_class` | `expansion` | 27 | 19 | 33.3333% | -1.1448% | 0.5274 | -1.4442% | `insufficient_sample` |
| `unclassified` | `volume_class` | `explosion` | 13 | 12 | 23.0769% | -1.5659% | 0.3636 | -1.8712% | `insufficient_sample` |
| `unclassified` | `volume_class` | `missing` | 1 | 1 | 100.0000% | 9.3045% | - | 9.0856% | `insufficient_sample` |
| `unclassified` | `volume_class` | `normal` | 90 | 43 | 44.4444% | 0.2805% | 1.1620 | -0.0300% | `not_positive_candidate` |

## Best Individual Trades

| Context | Stock | Concept | Phase | Entry | Exit | Net | 2x net | Regime |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 2025-08-08 | 北纬科技 (002148.SZSE) | 无人机 | `trend_continuation` | 8.9000 | 11.4500 | 28.1974% | 27.8349% | `GOLD/NORMAL` |
| 2025-08-06 | 吉视传媒 (601929.SSE) | AI智能体 | `trend_continuation` | 2.2000 | 2.7000 | 22.2981% | 21.9464% | `GOLD/NORMAL` |
| 2025-08-21 | 中天火箭 (003009.SZSE) | 无人机 | `trend_continuation` | 53.7200 | 65.6500 | 21.1335% | 20.7931% | `GOLD/NORMAL` |
| 2025-07-17 | 昂利康 (002940.SZSE) | 创新药 | `trend_continuation` | 44.9900 | 54.5600 | 20.7071% | 20.3604% | `GOLD/NORMAL` |
| 2025-09-17 | 云南旅游 (002059.SZSE) | 人形机器人 | `first_launch` | 6.0700 | 7.3500 | 20.6435% | 20.2951% | `GOLD/NORMAL` |
| 2025-08-25 | 天融信 (002212.SZSE) | 数字货币 | `trend_continuation` | 10.2400 | 12.3800 | 20.4106% | 20.0633% | `GOLD/NORMAL` |
| 2025-08-07 | 航天科技 (000901.SZSE) | 军工 | `trend_continuation` | 15.4200 | 18.6500 | 20.3267% | 19.9816% | `GOLD/NORMAL` |
| 2025-07-10 | 豫能控股 (001896.SZSE) | 绿色电力 | `healthy_pullback` | 5.6100 | 6.7400 | 19.7661% | 19.3092% | `GOLD/NORMAL` |
| 2025-08-22 | 领益智造 (002600.SZSE) | 人形机器人 | `trend_continuation` | 12.4200 | 14.9200 | 19.6539% | 19.3079% | `GOLD/NORMAL` |
| 2025-07-03 | 长城电工 (600192.SSE) | 军工 | `trend_continuation` | 9.6300 | 11.5000 | 18.9167% | 18.5726% | `GOLD/NORMAL` |
| 2025-11-12 | 丰元股份 (002805.SZSE) | 固态电池 | `healthy_pullback` | 18.1900 | 21.6800 | 18.5055% | 18.1651% | `SILVER/NORMAL` |
| 2025-09-19 | 大洋电机 (002249.SZSE) | 人形机器人 | `unclassified` | 9.8300 | 11.6900 | 18.4423% | 18.0987% | `GOLD/NORMAL` |
| 2025-10-20 | 山东墨龙 (002490.SZSE) | 氢能源 | `trend_continuation` | 7.1800 | 8.5100 | 18.1422% | 17.6695% | `SILVER/DANGER` |
| 2025-08-21 | 中油资本 (000617.SZSE) | 数字货币 | `divergence_restart` | 10.7500 | 12.7500 | 18.0582% | 17.7165% | `GOLD/NORMAL` |
| 2025-07-14 | 达 意 隆 (002209.SZSE) | 机器人概念 | `continuous_acceleration` | 15.6200 | 18.5400 | 18.0557% | 17.7156% | `GOLD/NORMAL` |
| 2025-08-12 | 特发信息 (000070.SZSE) | 军工 | `trend_continuation` | 9.2800 | 10.9900 | 17.9541% | 17.6114% | `GOLD/NORMAL` |
| 2025-11-11 | 天际股份 (002759.SZSE) | 固态电池 | `trend_continuation` | 40.8000 | 48.4200 | 17.9495% | 17.6110% | `SILVER/NORMAL` |
| 2025-08-21 | 川润股份 (002272.SZSE) | 机器人概念 | `trend_continuation` | 16.3900 | 19.4300 | 17.9002% | 17.5606% | `GOLD/NORMAL` |
| 2025-11-13 | 拓日新能 (002218.SZSE) | 钙钛矿电池 | `trend_continuation` | 4.2800 | 5.0600 | 17.8300% | 17.4862% | `SILVER/NORMAL` |
| 2025-11-10 | 天际股份 (002759.SZSE) | 固态电池 | `continuous_acceleration` | 39.5000 | 46.7100 | 17.6843% | 17.3438% | `SILVER/NORMAL` |

## Worst Individual Trades

| Context | Stock | Concept | Phase | Entry | Exit | Net | 2x net | Regime |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 2025-07-22 | 北化股份 (002246.SZSE) | 军工 | `climax_risk` | 23.6800 | 18.0000 | -24.0362% | -24.2037% | `GOLD/NORMAL` |
| 2025-07-14 | 京运通 (601908.SSE) | 稀土永磁 | `climax_risk` | 4.8700 | 3.8200 | -21.7975% | -21.9623% | `GOLD/NORMAL` |
| 2025-10-21 | 先锋电子 (002767.SZSE) | 氢能源 | `climax_risk` | 25.9100 | 20.5700 | -20.5624% | -20.8328% | `SILVER/NORMAL` |
| 2025-08-12 | 新疆火炬 (603080.SSE) | 天然气 | `climax_risk` | 28.8900 | 22.9400 | -20.4998% | -20.7696% | `GOLD/NORMAL` |
| 2025-07-16 | 达 意 隆 (002209.SZSE) | 机器人概念 | `climax_risk` | 20.3800 | 16.4100 | -19.6981% | -19.8744% | `GOLD/NORMAL` |
| 2025-08-11 | 天顺股份 (002800.SZSE) | 一带一路 | `continuous_acceleration` | 19.2600 | 15.8300 | -17.6746% | -17.8510% | `GOLD/NORMAL` |
| 2025-07-14 | 国晟科技 (603778.SSE) | 光伏概念 | `climax_risk` | 5.3700 | 4.4500 | -17.2908% | -17.4877% | `GOLD/NORMAL` |
| 2025-07-24 | 中铁工业 (600528.SSE) | 中字头 | `climax_risk` | 11.6000 | 9.6600 | -16.9650% | -17.0454% | `GOLD/NORMAL` |
| 2025-06-30 | 澳弘电子 (605058.SSE) | PCB | `continuous_acceleration` | 33.0000 | 27.6100 | -16.4496% | -16.7291% | `GOLD/NORMAL` |
| 2025-09-22 | 云南旅游 (002059.SZSE) | 人形机器人 | `climax_risk` | 7.8000 | 6.5500 | -16.1732% | -16.2441% | `GOLD/NORMAL` |
| 2025-08-19 | 中电鑫龙 (002298.SZSE) | 军工 | `divergence_restart` | 12.8400 | 10.8000 | -15.9049% | -16.1019% | `GOLD/NORMAL` |
| 2025-09-02 | 德新科技 (603032.SSE) | 固态电池 | `climax_risk` | 27.3000 | 23.0400 | -15.5320% | -15.7280% | `GOLD/NORMAL` |
| 2025-08-29 | 天融信 (002212.SZSE) | 华为概念 | `healthy_pullback` | 12.0300 | 10.2200 | -15.3073% | -15.4037% | `GOLD/NORMAL` |
| 2025-09-09 | 泰坦股份 (003036.SZSE) | 固态电池 | `continuous_acceleration` | 21.5000 | 18.2400 | -15.2774% | -15.5587% | `GOLD/NORMAL` |
| 2025-09-24 | 华菱线缆 (001208.SZSE) | 人形机器人 | `first_launch` | 14.6700 | 12.4700 | -15.2441% | -15.2998% | `GOLD/NORMAL` |
| 2025-07-03 | 博敏电子 (603936.SSE) | PCB | `divergence_restart` | 11.4500 | 9.7200 | -15.2436% | -15.4273% | `GOLD/NORMAL` |
| 2025-08-15 | 洪通燃气 (605169.SSE) | 天然气 | `divergence_restart` | 20.5300 | 17.4500 | -15.0647% | -15.3452% | `GOLD/NORMAL` |
| 2025-08-19 | 新天药业 (002873.SZSE) | 创新药 | `climax_risk` | 15.0000 | 12.8300 | -14.6049% | -14.8878% | `GOLD/NORMAL` |
| 2025-09-02 | 嵘泰股份 (605133.SSE) | 人形机器人 | `decay` | 49.1000 | 41.9400 | -14.5166% | -14.7133% | `GOLD/NORMAL` |
| 2025-10-22 | 建设机械 (600984.SSE) | 一带一路 | `continuous_acceleration` | 4.6700 | 4.0100 | -14.3429% | -14.6277% | `SILVER/NORMAL` |

## Boundary

This report freezes daily lifecycle phases and a passive hold baseline only.
Volume, relative strength and market regimes remain attribution fields. Strict
historical Top3, minute entry, cash compounding, outer holdout and production
selection remain closed.
