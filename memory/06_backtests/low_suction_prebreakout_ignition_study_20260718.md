# AlphaAgent 突破前点火与扩散研究

## 结论

研究状态：`exploratory_not_frozen`，所有点火、宽度、量能和龙头阈值均未冻结。
正样本读取概念 20 日突破前 D-10/D-5/D-3/D-1；反例采用同概念匹配对照。
观察日特征与早期龙头身份先固定，再读取等长后续扩散；这属于历史条件比较，不是低吸收益回测。

## 本轮发现

- D-10 已出现板块级信号：概念 10 日涨幅正样本/对照中位数为 `1.6946%/-3.0669%`，AUC `0.7663`；成交额扩张为 `1.0420/0.8698`，AUC `0.6980`。
- D-10 成员 5 日上涨宽度为 `56.0976%/41.2698%`，AUC `0.6116`；板块扩散在正式突破前已经存在。
- 反例同样清楚：D-10 成员强势日点火占比 AUC 仅 `0.5592`，配对中位差 `0.0000%`；Top3 成交额占比和 Top3 正收益集中度 AUC 仅 `0.5238/0.4377`。单日爆发或少数股票集中不是当前数据里的早期主信号。
- 观察日 5 日涨幅龙头后续保持 Top3 仅 `17.8814..22.6160%`，对照也有 `19.1040..22.6160%`；因此它只能作为时点排名，不能冻结为整段行情龙头，排名必须动态更新。
- 跟随股相对对照的中位收益差在 +3/+5 为 `0.4116..2.0970%`，到 +10 收敛为 `-0.3009..0.1122%`；当前证据更像短期扩散，不是长期龙头带动。
- D-1 概念 10 日涨幅 AUC 升至 `0.9116`，但它紧邻机械定义的 20 日突破；D-10 结果才是更严格的早期证据，二者都只能进入未见时段复验。

## 数据与匹配

- 概念指数：`2022-12-26..2026-07-17`，`324822` 行 / `446` 个概念。
- 突破转折：`20856` 个；完整匹配对：`4745` 对。
- 当前成员幸存者代理：`34623` 行；严格历史成员：`0` 行。
- 主板个股日线：`2387027` 行 / `3034` 只。

## 突破前特征

AUC 和正样本更高比例只衡量区分度；候选标签仍需未见时段前向复验。

| 提前日 | 特征 | 配对 | 正中位 | 对照中位 | 配对差 | 正样本更高 | AUC | 稳定块 | 状态 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| D-1 | `concept_return_1d_pct` | 1187 | 0.0946 | -0.0151 | 0.2837 | 56.9503% | 0.5682 | 3 | `exploratory_not_selected` |
| D-1 | `concept_return_3d_pct` | 1187 | 0.9651 | -0.1331 | 1.2790 | 64.5324% | 0.6580 | 4 | `candidate_for_forward_validation` |
| D-1 | `concept_return_5d_pct` | 1187 | 1.7441 | -0.5738 | 2.5509 | 74.0522% | 0.7506 | 5 | `candidate_for_forward_validation` |
| D-1 | `concept_return_10d_pct` | 1187 | 3.3866 | -3.4053 | 6.9503 | 89.1323% | 0.9116 | 5 | `candidate_for_forward_validation` |
| D-1 | `relative_gain_5d_percentile` | 1187 | 0.6273 | 0.4482 | 0.1309 | 63.0160% | 0.6447 | 5 | `candidate_for_forward_validation` |
| D-1 | `concept_turnover_expansion` | 1187 | 1.1116 | 0.8574 | 0.2637 | 78.7700% | 0.7982 | 5 | `candidate_for_forward_validation` |
| D-1 | `same_day_positive_breadth_pct` | 1187 | 48.5294 | 43.4783 | 5.0847 | 55.4760% | 0.5543 | 3 | `exploratory_not_selected` |
| D-1 | `positive_breadth_5d_pct` | 1187 | 63.6364 | 37.5691 | 22.0269 | 71.2721% | 0.7195 | 5 | `candidate_for_forward_validation` |
| D-1 | `breadth_5d_change_pct_points` | 1187 | 0.0000 | 13.0435 | -8.6957 | 44.4819% | 0.4324 | 0 | `exploratory_not_selected` |
| D-1 | `ignition_share_5d_pct` | 1187 | 15.7895 | 13.0435 | 1.6129 | 58.0034% | 0.5800 | 3 | `exploratory_not_selected` |
| D-1 | `leader_return_5d_pct` | 1187 | 17.0213 | 13.0407 | 3.5689 | 65.2064% | 0.6099 | 5 | `candidate_for_forward_validation` |
| D-1 | `top3_mean_return_5d_pct` | 1187 | 12.8661 | 8.9563 | 3.2420 | 67.9865% | 0.6237 | 5 | `candidate_for_forward_validation` |
| D-1 | `top3_turnover_share_pct` | 1187 | 17.1004 | 14.4543 | 1.1611 | 55.0126% | 0.5425 | 2 | `exploratory_not_selected` |
| D-1 | `top3_mean_turnover_expansion` | 1187 | 2.0682 | 1.5817 | 0.4035 | 66.8913% | 0.6330 | 5 | `candidate_for_forward_validation` |
| D-1 | `top3_positive_gain_concentration_pct` | 1133 | 40.8322 | 55.5983 | -9.2286 | 34.4219% | 0.3758 | 0 | `exploratory_not_selected` |
| D-3 | `concept_return_1d_pct` | 1187 | 0.5034 | 0.0107 | 0.5268 | 60.0674% | 0.5945 | 3 | `exploratory_not_selected` |
| D-3 | `concept_return_3d_pct` | 1187 | 1.1328 | -0.0686 | 1.3870 | 64.7009% | 0.6476 | 5 | `candidate_for_forward_validation` |
| D-3 | `concept_return_5d_pct` | 1187 | 1.7849 | -0.4758 | 2.3040 | 69.6714% | 0.7133 | 5 | `candidate_for_forward_validation` |
| D-3 | `concept_return_10d_pct` | 1187 | 3.0710 | -3.3424 | 6.3645 | 86.1837% | 0.8781 | 5 | `candidate_for_forward_validation` |
| D-3 | `relative_gain_5d_percentile` | 1187 | 0.6194 | 0.4507 | 0.1243 | 61.8787% | 0.6378 | 5 | `candidate_for_forward_validation` |
| D-3 | `concept_turnover_expansion` | 1187 | 1.1029 | 0.8588 | 0.2283 | 77.8433% | 0.7755 | 5 | `candidate_for_forward_validation` |
| D-3 | `same_day_positive_breadth_pct` | 1187 | 56.4516 | 44.9438 | 8.3333 | 58.4246% | 0.5861 | 4 | `exploratory_not_selected` |
| D-3 | `positive_breadth_5d_pct` | 1187 | 64.5614 | 38.4615 | 17.3913 | 67.7759% | 0.6921 | 5 | `candidate_for_forward_validation` |
| D-3 | `breadth_5d_change_pct_points` | 1187 | 4.1096 | 13.0435 | -4.9020 | 46.4617% | 0.4406 | 0 | `exploratory_not_selected` |
| D-3 | `ignition_share_5d_pct` | 1187 | 16.0714 | 13.0435 | 1.9608 | 58.2982% | 0.5760 | 2 | `exploratory_not_selected` |
| D-3 | `leader_return_5d_pct` | 1187 | 17.1123 | 13.0365 | 3.5818 | 63.5215% | 0.6008 | 5 | `candidate_for_forward_validation` |
| D-3 | `top3_mean_return_5d_pct` | 1187 | 12.9210 | 8.9688 | 2.9323 | 66.1331% | 0.6131 | 5 | `candidate_for_forward_validation` |
| D-3 | `top3_turnover_share_pct` | 1187 | 16.9498 | 14.6553 | 1.0690 | 55.4339% | 0.5313 | 2 | `exploratory_not_selected` |
| D-3 | `top3_mean_turnover_expansion` | 1187 | 1.9561 | 1.5740 | 0.2880 | 61.2468% | 0.6150 | 5 | `candidate_for_forward_validation` |
| D-3 | `top3_positive_gain_concentration_pct` | 1132 | 42.3421 | 55.0754 | -6.7660 | 36.9700% | 0.3959 | 0 | `exploratory_not_selected` |
| D-5 | `concept_return_1d_pct` | 1186 | 0.3926 | 0.0539 | 0.3771 | 57.0826% | 0.5707 | 4 | `exploratory_not_selected` |
| D-5 | `concept_return_3d_pct` | 1186 | 0.9613 | -0.0206 | 0.8857 | 59.3592% | 0.6138 | 3 | `exploratory_not_selected` |
| D-5 | `concept_return_5d_pct` | 1186 | 1.6158 | -0.4265 | 1.9746 | 68.2125% | 0.6896 | 5 | `candidate_for_forward_validation` |
| D-5 | `concept_return_10d_pct` | 1186 | 2.6719 | -3.2961 | 5.8525 | 84.5700% | 0.8482 | 5 | `candidate_for_forward_validation` |
| D-5 | `relative_gain_5d_percentile` | 1186 | 0.6129 | 0.4511 | 0.1151 | 62.4789% | 0.6284 | 5 | `candidate_for_forward_validation` |
| D-5 | `concept_turnover_expansion` | 1184 | 1.0796 | 0.8594 | 0.1927 | 75.9291% | 0.7546 | 5 | `candidate_for_forward_validation` |
| D-5 | `same_day_positive_breadth_pct` | 1186 | 52.3810 | 45.6109 | 4.5299 | 55.0590% | 0.5490 | 2 | `exploratory_not_selected` |
| D-5 | `positive_breadth_5d_pct` | 1186 | 60.0000 | 39.5360 | 14.2857 | 63.1535% | 0.6546 | 5 | `candidate_for_forward_validation` |
| D-5 | `breadth_5d_change_pct_points` | 1186 | 0.0000 | 13.8733 | -9.7727 | 43.7184% | 0.4221 | 0 | `exploratory_not_selected` |
| D-5 | `ignition_share_5d_pct` | 1186 | 15.0735 | 12.9331 | 0.0219 | 55.0169% | 0.5621 | 2 | `exploratory_not_selected` |
| D-5 | `leader_return_5d_pct` | 1186 | 16.9177 | 13.0060 | 2.8361 | 61.6358% | 0.5903 | 4 | `exploratory_not_selected` |
| D-5 | `top3_mean_return_5d_pct` | 1186 | 12.5945 | 8.9785 | 2.4006 | 61.7201% | 0.5992 | 5 | `exploratory_not_selected` |
| D-5 | `top3_turnover_share_pct` | 1186 | 15.9837 | 14.4956 | 1.0532 | 55.3120% | 0.5273 | 0 | `exploratory_not_selected` |
| D-5 | `top3_mean_turnover_expansion` | 1186 | 1.8955 | 1.5459 | 0.2868 | 60.7926% | 0.6020 | 5 | `candidate_for_forward_validation` |
| D-5 | `top3_positive_gain_concentration_pct` | 1131 | 43.8336 | 54.4388 | -5.0013 | 40.9372% | 0.4181 | 0 | `exploratory_not_selected` |
| D-10 | `concept_return_1d_pct` | 1185 | 0.3524 | 0.0974 | 0.1784 | 52.9114% | 0.5443 | 3 | `exploratory_not_selected` |
| D-10 | `concept_return_3d_pct` | 1185 | 0.5400 | 0.1181 | 0.2689 | 53.5021% | 0.5584 | 3 | `exploratory_not_selected` |
| D-10 | `concept_return_5d_pct` | 1185 | 1.1108 | -0.3169 | 0.8309 | 59.4937% | 0.6261 | 5 | `candidate_for_forward_validation` |
| D-10 | `concept_return_10d_pct` | 1185 | 1.6946 | -3.0669 | 3.9955 | 77.8059% | 0.7663 | 5 | `candidate_for_forward_validation` |
| D-10 | `relative_gain_5d_percentile` | 1185 | 0.5550 | 0.4515 | 0.0615 | 57.8481% | 0.5860 | 4 | `exploratory_not_selected` |
| D-10 | `concept_turnover_expansion` | 1181 | 1.0420 | 0.8698 | 0.0991 | 71.9729% | 0.6980 | 5 | `candidate_for_forward_validation` |
| D-10 | `same_day_positive_breadth_pct` | 1185 | 52.1739 | 47.3684 | 0.0000 | 51.8565% | 0.5286 | 2 | `exploratory_not_selected` |
| D-10 | `positive_breadth_5d_pct` | 1185 | 56.0976 | 41.2698 | 6.2500 | 59.6624% | 0.6116 | 5 | `candidate_for_forward_validation` |
| D-10 | `breadth_5d_change_pct_points` | 1185 | 0.0000 | 14.7309 | -9.5745 | 40.1266% | 0.4218 | 0 | `exploratory_not_selected` |
| D-10 | `ignition_share_5d_pct` | 1185 | 14.8148 | 12.6316 | 0.0000 | 54.3038% | 0.5592 | 3 | `exploratory_not_selected` |
| D-10 | `leader_return_5d_pct` | 1185 | 15.6871 | 12.7747 | 1.6837 | 57.8059% | 0.5689 | 5 | `exploratory_not_selected` |
| D-10 | `top3_mean_return_5d_pct` | 1185 | 11.5147 | 8.9467 | 1.0975 | 58.3966% | 0.5753 | 5 | `exploratory_not_selected` |
| D-10 | `top3_turnover_share_pct` | 1185 | 16.4438 | 14.4543 | 0.3567 | 52.8270% | 0.5238 | 0 | `exploratory_not_selected` |
| D-10 | `top3_mean_turnover_expansion` | 1185 | 1.8418 | 1.5415 | 0.2057 | 62.3629% | 0.5930 | 4 | `exploratory_not_selected` |
| D-10 | `top3_positive_gain_concentration_pct` | 1124 | 46.7167 | 54.2520 | -2.4860 | 42.3488% | 0.4377 | 0 | `exploratory_not_selected` |

## 五时段稳定性

以下仅列达到预注册门槛的候选；每格为 `完整配对数 / AUC`，不是生产规则。

| 提前日 | 特征 | B1 | B2 | B3 | B4 | B5 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| D-1 | `concept_return_10d_pct` | 239 / 0.9612 | 249 / 0.8652 | 241 / 0.9208 | 220 / 0.9220 | 238 / 0.9050 |
| D-1 | `concept_return_3d_pct` | 239 / 0.7672 | 249 / 0.6671 | 241 / 0.6269 | 220 / 0.5009 | 238 / 0.6911 |
| D-1 | `concept_return_5d_pct` | 239 / 0.8286 | 249 / 0.7058 | 241 / 0.7210 | 220 / 0.7274 | 238 / 0.7818 |
| D-1 | `concept_turnover_expansion` | 239 / 0.8097 | 249 / 0.7062 | 241 / 0.8281 | 220 / 0.7973 | 238 / 0.8584 |
| D-1 | `leader_return_5d_pct` | 239 / 0.6186 | 249 / 0.6206 | 241 / 0.6265 | 220 / 0.5740 | 238 / 0.6157 |
| D-1 | `positive_breadth_5d_pct` | 239 / 0.8096 | 249 / 0.6736 | 241 / 0.7018 | 220 / 0.6769 | 238 / 0.7368 |
| D-1 | `relative_gain_5d_percentile` | 239 / 0.7169 | 249 / 0.6380 | 241 / 0.5858 | 220 / 0.6734 | 238 / 0.6254 |
| D-1 | `top3_mean_return_5d_pct` | 239 / 0.6650 | 249 / 0.6117 | 241 / 0.6412 | 220 / 0.5882 | 238 / 0.6190 |
| D-1 | `top3_mean_turnover_expansion` | 239 / 0.6351 | 249 / 0.6251 | 241 / 0.6433 | 220 / 0.6447 | 238 / 0.6145 |
| D-3 | `concept_return_10d_pct` | 239 / 0.9278 | 249 / 0.8184 | 241 / 0.8960 | 220 / 0.8991 | 238 / 0.8719 |
| D-3 | `concept_return_3d_pct` | 239 / 0.7714 | 249 / 0.6212 | 241 / 0.5858 | 220 / 0.5775 | 238 / 0.6991 |
| D-3 | `concept_return_5d_pct` | 239 / 0.8040 | 249 / 0.6615 | 241 / 0.6809 | 220 / 0.7102 | 238 / 0.7276 |
| D-3 | `concept_turnover_expansion` | 239 / 0.7786 | 249 / 0.6832 | 241 / 0.8104 | 220 / 0.7673 | 238 / 0.8469 |
| D-3 | `leader_return_5d_pct` | 239 / 0.6258 | 249 / 0.6054 | 241 / 0.6153 | 220 / 0.5547 | 238 / 0.6050 |
| D-3 | `positive_breadth_5d_pct` | 239 / 0.7985 | 249 / 0.6377 | 241 / 0.6663 | 220 / 0.6694 | 238 / 0.6913 |
| D-3 | `relative_gain_5d_percentile` | 239 / 0.6923 | 249 / 0.6170 | 241 / 0.5909 | 220 / 0.6696 | 238 / 0.6307 |
| D-3 | `top3_mean_return_5d_pct` | 239 / 0.6620 | 249 / 0.5969 | 241 / 0.6215 | 220 / 0.5742 | 238 / 0.6153 |
| D-3 | `top3_mean_turnover_expansion` | 239 / 0.6105 | 249 / 0.5971 | 241 / 0.6346 | 220 / 0.6270 | 238 / 0.5989 |
| D-5 | `concept_return_10d_pct` | 238 / 0.8875 | 249 / 0.7815 | 241 / 0.8855 | 220 / 0.8633 | 238 / 0.8484 |
| D-5 | `concept_return_5d_pct` | 238 / 0.7928 | 249 / 0.6014 | 241 / 0.6730 | 220 / 0.6814 | 238 / 0.7362 |
| D-5 | `concept_turnover_expansion` | 237 / 0.7484 | 249 / 0.6792 | 240 / 0.7899 | 220 / 0.7415 | 238 / 0.8216 |
| D-5 | `positive_breadth_5d_pct` | 238 / 0.7728 | 249 / 0.5733 | 241 / 0.6263 | 220 / 0.6273 | 238 / 0.6819 |
| D-5 | `relative_gain_5d_percentile` | 238 / 0.6942 | 249 / 0.5860 | 241 / 0.6186 | 220 / 0.6406 | 238 / 0.6144 |
| D-5 | `top3_mean_turnover_expansion` | 238 / 0.5771 | 249 / 0.6024 | 241 / 0.6199 | 220 / 0.6340 | 238 / 0.5794 |
| D-10 | `concept_return_10d_pct` | 237 / 0.7452 | 249 / 0.7141 | 241 / 0.8089 | 220 / 0.8660 | 238 / 0.7539 |
| D-10 | `concept_return_5d_pct` | 237 / 0.6828 | 249 / 0.5936 | 241 / 0.5698 | 220 / 0.6444 | 238 / 0.6289 |
| D-10 | `concept_turnover_expansion` | 234 / 0.6740 | 249 / 0.6218 | 240 / 0.7354 | 220 / 0.7252 | 238 / 0.7406 |
| D-10 | `positive_breadth_5d_pct` | 237 / 0.6793 | 249 / 0.5980 | 241 / 0.5616 | 220 / 0.6103 | 238 / 0.5878 |

## 龙头保持与跟随扩散

早期龙头在观察日冻结；后续龙头保持和跟随扩散是关联，不能证明因果带动。

| 提前日 | 未来日 | 配对 | 正跟随收益 | 对照跟随收益 | 配对差 | 正宽度 | 对照宽度 | 正龙头保持 Top3 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D-1 | +3 | 1185 | 1.0141% | -0.3778% | 1.4827% | 66.0377% | 42.8571% | 22.6160% |
| D-1 | +5 | 1185 | 0.9040% | -0.4292% | 1.2223% | 60.6557% | 43.3962% | 22.0253% |
| D-1 | +10 | 1184 | 0.6601% | 1.1842% | -0.3009% | 55.5556% | 60.0000% | 19.5101% |
| D-3 | +3 | 1185 | 1.3889% | -0.2541% | 1.7656% | 67.6471% | 45.6522% | 20.5907% |
| D-3 | +5 | 1185 | 1.3054% | 0.0000% | 1.4678% | 63.6364% | 50.0000% | 18.7342% |
| D-3 | +10 | 1183 | 1.0309% | 1.4515% | -0.1465% | 57.8947% | 61.5385% | 18.4277% |
| D-5 | +3 | 1183 | 2.0979% | 0.1547% | 2.0970% | 71.2871% | 50.0000% | 20.0338% |
| D-5 | +5 | 1183 | 1.9361% | 0.4325% | 1.5636% | 68.2927% | 54.5455% | 19.6957% |
| D-5 | +10 | 1185 | 1.7050% | 1.9686% | -0.0265% | 61.5385% | 65.9091% | 17.8903% |
| D-10 | +3 | 1181 | 3.0164% | 2.1454% | 0.7307% | 73.6842% | 69.4268% | 20.7451% |
| D-10 | +5 | 1183 | 2.9443% | 2.6326% | 0.4116% | 70.3704% | 70.0000% | 19.0194% |
| D-10 | +10 | 1180 | 2.8115% | 2.7403% | 0.1122% | 66.6667% | 67.3691% | 17.8814% |

## 近期真实资金覆盖

- 板块资金覆盖：`21` 个交易日 / `0` 个完整匹配对。
- 早期龙头资金覆盖：`27` 个交易日 / `0` 个完整匹配对。
- 联合覆盖：`0` 对；至少 `30` 对才单独分析，本报告不使用净流入数值选择历史特征。

## 限制与下一步

- 当前成员幸存者代理不能还原历史点时成员，个股身份结论不能正式冻结。
- 同概念匹配对照降低部分混杂，但仍不能把相关性解释成因果预测。
- 下一步只把达到预注册门槛的候选带到未见时间块复验；未通过则保留为否证。
- 身份和扩散稳定前，不读取低吸买卖收益。
