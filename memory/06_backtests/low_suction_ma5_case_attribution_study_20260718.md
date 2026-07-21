# AlphaAgent 多浪龙头 MA5 成功/失败逐票归因

研究状态：`forward_diagnostic_candidate_found`；验证边界：`reused_history_attribution_not_validation`。
正式 Top3、胜率、收益和复利：`null`。

## Coverage

- 完整逐票记录：`57`；成功/失败：`36` / `21`。
- 股票/概念/信号日：`56` / `49` / `48`。
- 当前成员代理覆盖：`57`；金银标签覆盖：`41`。

## Parent Descriptive Result

- 57 笔闭合中成本后为正比例 `63.1579%`，均值 `1.5753%`，利润因子 `1.5386`。
- 这些是已看历史的描述值，不是正式低吸胜率。

## Pre-entry Differences

| Feature | Winner median | Loser median | Diff / pooled IQR |
| --- | ---: | ---: | ---: |
| `strong_days_ge_9_5pct` | 1.0000 | 0.0000 | 1.0000 |
| `stock_return_10d_pct` | 23.8297 | 17.9825 | 0.4987 |
| `stock_ma5_slope_3_pct` | 9.5926 | 7.2947 | 0.4912 |
| `proxy_top3_mean_return_10d_pct` | 31.8020 | 24.2701 | 0.4609 |
| `concept_return_10d_pct` | 9.5320 | 7.4081 | 0.3674 |
| `stock_ma20_slope_3_pct` | 4.8981 | 3.8994 | 0.3634 |
| `stock_excess_concept_5d_pct` | 9.2071 | 5.8120 | 0.3495 |
| `concept_return_5d_pct` | 4.2558 | 6.1677 | -0.3419 |
| `stock_return_5d_pct` | 15.0309 | 11.6183 | 0.3345 |
| `concept_ma10_slope_3_pct` | 2.2063 | 2.7722 | -0.3304 |
| `stock_excess_concept_10d_pct` | 14.7135 | 10.6889 | 0.3040 |
| `volume_ratio_impulse` | 0.8306 | 0.7344 | 0.2975 |
| `proxy_positive_breadth_5d_pct` | 73.7500 | 80.6452 | -0.2724 |
| `volume_ratio_prior5` | 0.9523 | 1.0543 | -0.2592 |
| `stock_ma5_ma10_gap_pct` | 6.7521 | 5.7335 | 0.2492 |
| `concept_ma5_ma10_gap_pct` | 2.6645 | 2.1377 | 0.2429 |
| `concept_close_location_pct` | 76.2670 | 89.0671 | -0.2215 |
| `concept_ma20_slope_3_pct` | 1.8042 | 2.2415 | -0.2200 |
| `impulse_gain_pct` | 10.7202 | 7.7357 | 0.2087 |
| `stock_ma10_slope_3_pct` | 5.9928 | 5.3922 | 0.1972 |
| `signal_daily_return_pct` | 2.3908 | 1.9411 | 0.1619 |
| `proxy_positive_breadth_10d_pct` | 86.6071 | 83.3333 | 0.1540 |
| `concept_return_10d_percentile` | 0.8264 | 0.8777 | -0.1517 |
| `concept_ma5_slope_3_pct` | 2.8187 | 3.2215 | -0.1282 |
| `stock_close_location_pct` | 66.7318 | 63.7795 | 0.1105 |
| `signal_close_to_peak_pct` | -5.3276 | -5.6140 | 0.0741 |
| `stock_ma10_ma20_gap_pct` | 6.4195 | 6.8075 | -0.0641 |
| `concept_return_5d_percentile` | 0.7515 | 0.7728 | -0.0548 |
| `pullback_confirmation_low_to_peak_pct` | -10.0880 | -9.8532 | -0.0487 |
| `line_distance_close_pct` | 2.6529 | 2.5218 | 0.0404 |
| `concept_ma10_ma20_gap_pct` | 3.4487 | 3.4842 | -0.0108 |
| `pullback_sessions_from_peak` | 2.0000 | 2.0000 | 0.0000 |
| `proxy_stock_return_10d_rank` | 3.0000 | 3.0000 | 0.0000 |

## Forward Diagnostics

- `volume_ratio_prior5`：赢家方向 `lower_in_winners`，充分块中 `4/4` 同向；只前向观察，不设阈值。
- `impulse_gain_pct`：赢家方向 `higher_in_winners`，充分块中 `4/4` 同向；只前向观察，不设阈值。
- `stock_ma5_ma10_gap_pct`：赢家方向 `higher_in_winners`，充分块中 `4/4` 同向；只前向观察，不设阈值。

## Failure Mechanisms

| Mechanism | Cases | Positive | Mean net |
| --- | ---: | ---: | ---: |
| `concept_and_stock_wave_ended` | 14 | 0.0000% | -10.5496% |
| `defensive_exit_before_later_rebreak` | 2 | 0.0000% | -5.8353% |
| `higher_high_but_entry_to_exit_loss` | 5 | 0.0000% | -1.4715% |
| `higher_high_rebreak_winner` | 36 | 100.0000% | 7.1254% |

## Concept Continuation

| Outcome | Cases | Post 1d median | Post 5d median | Post 10d median |
| --- | ---: | ---: | ---: | ---: |
| `loser` | 21 | -0.9656% | -1.9757% | -1.9868% |
| `winner` | 36 | 1.0338% | 1.6403% | 2.5648% |

概念后续涨跌属于信号后的归因：它解释为何同样的 MA5 结构分化，不能直接变成买入条件。

## Individual Cases

| Date | Stock | Concept | Result | Net | Impulse | MA5-MA10 | Volume | Concept +5d | Mechanism |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 2023-06-14 | 特发信息 `000070.SZSE` | F5G概念 | `loser` | -8.7968% | 10.9072% | 5.4051% | 0.8938 | 4.3916% | `concept_and_stock_wave_ended` |
| 2023-06-30 | 秦川机床 `000837.SZSE` | 工业母机 | `loser` | -16.5190% | 7.6693% | 8.3643% | 0.8908 | -1.9126% | `concept_and_stock_wave_ended` |
| 2023-07-27 | 中华企业 `600675.SSE` | 土地流转 | `winner` | 4.3326% | 19.9357% | 5.7966% | 3.3501 | 3.8056% | `higher_high_rebreak_winner` |
| 2023-08-09 | 首创证券 `601136.SSE` | 互联网金融 | `winner` | 10.6792% | 23.0080% | 11.9453% | 1.0804 | -1.9880% | `higher_high_rebreak_winner` |
| 2023-10-12 | 上海沿浦 `605128.SSE` | 华为汽车 | `winner` | 2.1622% | 10.0019% | 5.5375% | 0.9325 | -2.5966% | `higher_high_rebreak_winner` |
| 2023-11-01 | 利通电子 `603629.SSE` | 毫米波概念 | `winner` | 11.6797% | 30.5931% | 9.0354% | 0.9819 | 4.0207% | `higher_high_rebreak_winner` |
| 2023-11-10 | 中科金财 `002657.SZSE` | 移动支付 | `winner` | 21.0181% | 9.0909% | 4.6986% | 1.5799 | 4.4448% | `higher_high_rebreak_winner` |
| 2023-11-17 | 北特科技 `603009.SSE` | 汽车热管理 | `winner` | 5.7505% | 9.4203% | 7.2196% | 0.4483 | -2.2589% | `higher_high_rebreak_winner` |
| 2023-11-23 | 雷柏科技 `002577.SZSE` | 无线充电 | `winner` | 8.9815% | 8.2501% | 4.0466% | 0.7876 | -2.5578% | `higher_high_rebreak_winner` |
| 2023-12-11 | 力盛体育 `002858.SZSE` | Web3.0 | `winner` | 4.1350% | 14.5222% | 5.8191% | 3.6410 | -4.4005% | `higher_high_rebreak_winner` |
| 2024-03-07 | 工业富联 `601138.SSE` | HS300_ | `winner` | 7.4623% | 20.7792% | 8.6117% | 1.0894 | 1.3806% | `higher_high_rebreak_winner` |
| 2024-03-18 | 赛腾股份 `603283.SSE` | 高带宽内存 | `loser` | -18.3111% | 5.4313% | 5.9855% | 1.0543 | -5.5163% | `concept_and_stock_wave_ended` |
| 2024-03-20 | 启明信息 `002232.SZSE` | EDR概念 | `loser` | -5.3965% | 5.9594% | 2.3510% | 1.1176 | -9.6803% | `concept_and_stock_wave_ended` |
| 2024-03-25 | 中科金财 `002657.SZSE` | Web3.0 | `loser` | -10.9815% | 7.7357% | 4.5241% | 2.0940 | -3.7677% | `concept_and_stock_wave_ended` |
| 2024-05-20 | 万丰奥威 `002085.SZSE` | 通用航空 | `loser` | -9.6944% | 6.0674% | 3.3391% | 1.1851 | -6.2070% | `concept_and_stock_wave_ended` |
| 2024-05-22 | 津滨发展 `000897.SZSE` | 京津冀 | `loser` | -7.3970% | 13.0952% | 5.7335% | 1.1818 | -4.3368% | `concept_and_stock_wave_ended` |
| 2024-06-03 | 通富微电 `002156.SZSE` | AIPC | `winner` | 4.4101% | 3.1145% | 4.8041% | 0.7817 | -7.0708% | `higher_high_rebreak_winner` |
| 2024-06-14 | 盛剑科技 `603324.SSE` | 光刻机(胶) | `loser` | -5.8982% | 12.2509% | 4.4831% | 1.6011 | -1.9757% | `concept_and_stock_wave_ended` |
| 2024-08-01 | 金龙汽车 `600686.SSE` | 汽车整车 | `winner` | 10.2332% | 28.6322% | 14.4924% | 0.9867 | -9.8535% | `higher_high_rebreak_winner` |
| 2024-09-25 | 拓维信息 `002261.SZSE` | 在线教育 | `winner` | 5.7197% | 10.0216% | 6.3439% | 1.2823 | 21.9576% | `higher_high_rebreak_winner` |
| 2024-09-26 | 遥望科技 `002291.SZSE` | 网红经济 | `winner` | 1.7763% | 7.3529% | 4.2290% | 0.6577 | 10.4142% | `higher_high_rebreak_winner` |
| 2024-10-10 | 立讯精密 `002475.SZSE` | 3D摄像头 | `loser` | -2.8965% | 18.1077% | 6.6917% | 0.7793 | -3.4032% | `concept_and_stock_wave_ended` |
| 2024-10-11 | 梦网科技 `002123.SZSE` | 云计算 | `winner` | 15.2900% | 41.4602% | 12.0824% | 1.0502 | 9.7236% | `higher_high_rebreak_winner` |
| 2024-10-14 | 金固股份 `002488.SZSE` | 阿里概念 | `winner` | 0.0959% | 34.2640% | 12.0790% | 0.6150 | 5.0415% | `higher_high_rebreak_winner` |
| 2024-10-15 | 中光学 `002189.SZSE` | 3D摄像头 | `winner` | 7.0588% | 25.5596% | 9.7215% | 0.8285 | 9.8846% | `higher_high_rebreak_winner` |
| 2024-10-22 | 明星电力 `600101.SSE` | 钒电池 | `loser` | -1.1474% | 4.0254% | 6.2801% | 1.1948 | 8.2987% | `higher_high_but_entry_to_exit_loss` |
| 2024-10-24 | 欧菲光 `002456.SZSE` | 3D摄像头 | `winner` | 14.5128% | 20.9540% | 12.0973% | 0.7840 | 10.0357% | `higher_high_rebreak_winner` |
| 2024-10-24 | 泰豪科技 `600590.SSE` | 北斗导航 | `winner` | 7.3540% | 9.9815% | 8.7274% | 0.8145 | 5.5718% | `higher_high_rebreak_winner` |
| 2024-10-25 | 智度股份 `000676.SZSE` | Web3.0 | `winner` | 9.4774% | 21.5805% | 10.9259% | 1.3765 | -1.4861% | `higher_high_rebreak_winner` |
| 2024-10-25 | 苏豪汇鸿 `600981.SSE` | 参股新三板 | `winner` | 8.7552% | 9.8182% | 10.3896% | 2.6676 | 1.7596% | `higher_high_rebreak_winner` |
| 2024-10-31 | 泰达股份 `000652.SZSE` | 滨海新区 | `winner` | 0.0083% | 9.0323% | 6.8942% | 1.1341 | 5.6667% | `higher_high_rebreak_winner` |
| 2024-11-07 | 五矿资本 `600390.SSE` | 券商概念 | `loser` | -19.8850% | 10.0000% | 8.5603% | 1.1192 | -6.4537% | `concept_and_stock_wave_ended` |
| 2024-11-07 | 金证股份 `600446.SSE` | 券商概念 | `winner` | 3.1879% | 5.6476% | 3.5748% | 1.1034 | -6.4537% | `higher_high_rebreak_winner` |
| 2024-11-07 | 剑桥科技 `603083.SSE` | 边缘计算 | `winner` | 4.8868% | 36.8280% | 10.7260% | 0.9702 | 1.7650% | `higher_high_rebreak_winner` |
| 2024-11-11 | 越秀资本 `000987.SZSE` | 参股期货 | `loser` | -9.8998% | 22.0339% | 6.5529% | 0.7190 | -6.5046% | `concept_and_stock_wave_ended` |
| 2024-11-12 | 獐子岛 `002069.SZSE` | 水产概念 | `loser` | -7.8023% | 5.1429% | 4.1063% | 0.6798 | -6.3277% | `defensive_exit_before_later_rebreak` |
| 2024-11-12 | 航天机电 `600151.SSE` | HJT电池 | `winner` | 0.3417% | 3.0702% | 6.2317% | 0.9343 | -7.1975% | `higher_high_rebreak_winner` |
| 2024-12-05 | 天府文旅 `000558.SZSE` | 旅游概念 | `loser` | -0.4915% | 5.1205% | 4.0466% | 1.4190 | 5.7403% | `higher_high_but_entry_to_exit_loss` |
| 2024-12-10 | 信雅达 `600571.SSE` | IPO受益 | `loser` | -8.7390% | 20.4819% | 5.9250% | 3.6980 | -1.5239% | `concept_and_stock_wave_ended` |
| 2024-12-24 | 精达股份 `600577.SSE` | 超导概念 | `winner` | 2.3316% | 20.3704% | 6.7585% | 1.2020 | -2.9827% | `higher_high_rebreak_winner` |
| 2025-02-11 | 浪潮信息 `000977.SZSE` | 英伟达概念 | `winner` | 0.5201% | 15.7063% | 6.1048% | 1.1383 | 1.5211% | `higher_high_rebreak_winner` |
| 2025-02-11 | 凌云股份 `600480.SSE` | 传感器 | `winner` | 7.8139% | 4.1288% | 5.0787% | 0.7627 | -0.4252% | `higher_high_rebreak_winner` |
| 2025-02-19 | 联创电子 `002036.SZSE` | 3D摄像头 | `winner` | 2.3162% | 8.3584% | 3.7900% | 0.7917 | 2.9102% | `higher_high_rebreak_winner` |
| 2025-02-19 | 华勤技术 `603296.SSE` | AIPC | `winner` | 11.9347% | 3.8782% | 4.4937% | 0.7741 | 7.3664% | `higher_high_rebreak_winner` |
| 2025-02-21 | 南兴股份 `002757.SZSE` | VPN | `winner` | 10.8960% | 15.2008% | 9.3474% | 0.9804 | -8.8450% | `higher_high_rebreak_winner` |
| 2025-02-21 | XD华胜天 `600410.SSE` | 新型工业化 | `loser` | -0.9491% | 3.8961% | 4.3211% | 0.8808 | -4.6622% | `higher_high_but_entry_to_exit_loss` |
| 2025-05-06 | 中宠股份 `002891.SZSE` | 宠物经济 | `loser` | -0.7803% | 2.4044% | 6.1985% | 0.7480 | 2.3233% | `higher_high_but_entry_to_exit_loss` |
| 2025-05-20 | 金达威 `002626.SZSE` | 长寿药 | `loser` | -3.8683% | 9.3564% | 4.1141% | 1.7832 | 0.5854% | `defensive_exit_before_later_rebreak` |
| 2025-06-10 | 证通电子 `002197.SZSE` | 数字水印 | `winner` | 4.7051% | 11.4187% | 4.5409% | 1.3096 | 0.7231% | `higher_high_rebreak_winner` |
| 2025-06-30 | 海联金汇 `002537.SZSE` | 跨境支付 | `loser` | -6.5636% | 17.7543% | 9.5795% | 0.8148 | 1.4076% | `concept_and_stock_wave_ended` |
| 2025-06-30 | 安邦护卫 `603373.SSE` | 智慧政务 | `loser` | -3.9893% | 8.7184% | 3.3365% | 0.9988 | -1.3064% | `higher_high_but_entry_to_exit_loss` |
| 2025-07-08 | 中京电子 `002579.SZSE` | 无线耳机 | `loser` | -16.7155% | 6.7949% | 6.0933% | 0.9572 | -0.8793% | `concept_and_stock_wave_ended` |
| 2025-07-24 | 光电股份 `600184.SSE` | 机器视觉 | `winner` | 14.1016% | 4.9451% | 4.1971% | 0.8111 | 1.1335% | `higher_high_rebreak_winner` |
| 2025-07-29 | 盛新锂能 `002240.SZSE` | 锂矿概念 | `winner` | 12.6519% | 20.5413% | 6.7457% | 0.7752 | -3.5011% | `higher_high_rebreak_winner` |
| 2025-08-04 | 长飞光纤 `601869.SSE` | 碳化硅 | `winner` | 6.7418% | 9.9959% | 9.3606% | 0.8112 | 4.7629% | `higher_high_rebreak_winner` |
| 2025-08-11 | 夏厦精密 `001306.SZSE` | 机器人执行器 | `winner` | 10.3700% | 26.6747% | 8.5092% | 0.7220 | 3.2398% | `higher_high_rebreak_winner` |
| 2025-08-19 | 世运电路 `603920.SSE` | 英伟达概念 | `winner` | 2.8229% | 2.5953% | 5.6380% | 0.8560 | 4.9202% | `higher_high_rebreak_winner` |

## Boundaries

- all five historical blocks were already viewed
- current memberships are a survivorship proxy, not historical fact
- causal Top3 did not pass the prior absolute identity gate
- post-entry concept continuation explains outcomes but cannot trigger entry
- stable direction nominates forward diagnostics only, never a fitted rule
- formal Top3, win rate, return and compounding remain null

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-ma5-case-attribution-study --format markdown
```
