# AlphaAgent 三只主升龙头逐股逐浪审计

状态：`individual_case_audit_complete`；正式策略：`false`；正式绩效：`null`。

## 先纠正旧结论

`main-rise-weak-to-strong-v6.pullback_opportunity_ordinal` 不是完整主升波段号。
它从算法较晚的 episode 起点编号，因此金安国纪 `2026-01-30` 被误写成第一次，
实际属于从 `2026-01-15` 开始的第 2 浪。旧总体表不能继续解释真实低吸位置。

## Coverage

- 股票 `3`；主升 campaign `4`；完整波段 `41`；其中再创新高 `37`。
- 支撑站稳候选 `73`；顺序执行 `54` 笔。分钟线、资金流、旧低吸结果均未读取。
- 逐日账本 `355` 行，其中回调路径 `219` 行；每行保留当日支撑区、最深支撑和是否形成候选。

## Campaigns

| 股票 | 区间 | 波段 | 再创新高 | 终止浪 | 起点到最高 | 候选 | 交易 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 东山精密 `002384.SZSE` | 2025-06-16..2025-09-24 | 8 | 7 | 1 | +149.5087% | 15 | 12 |
| 金安国纪 `002636.SZSE` | 2026-01-15..2026-07-06 | 16 | 15 | 1 | +589.4678% | 27 | 23 |
| 亨通光电 `600487.SSE` | 2025-08-08..2025-10-14 | 4 | 3 | 1 | +44.2546% | 8 | 6 |
| 亨通光电 `600487.SSE` | 2025-12-17..2026-07-01 | 13 | 12 | 1 | +477.5727% | 23 | 13 |

亨通光电从 `2025-08-08` 连续按记录高点看共 17 浪；但 `2025-10-14` 已发生
明确结构重置，所以审计拆成前 4 浪和 `2025-12-17` 再点火后的 13 浪。

## D+1 亏损退出结果

- 闭合 `54` 笔；成本后正收益比例 `+40.7407%`；均值 `+0.1688%`。
- D+1 止损 `28` 笔；其中后来该浪仍创新高 `25` 笔。后者不是主升判断错误，而是第一次支撑站稳过早。

| 原因 | 笔数 | 均值 | 后来创新高 |
| --- | ---: | ---: | ---: |
| `entry_too_early` | 28 | -3.9192% | 28 |
| `terminal_wave` | 4 | -7.4047% | 0 |

## 波段级顺序结果

同一浪可以先 D+1 止损、后重新站稳再买；下表把这些尝试按时间复合成一个波段结果。

| 波段组 | 全部波段 | 有入场 | 盈利波段 | 有入场胜率 | 平均波段净收益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `all` | 41 | 35 | 18 | +51.4286% | +0.1989% |
| `continued_to_higher_high` | 37 | 31 | 18 | +58.0645% | +1.1800% |
| `terminal_failure_observed` | 4 | 4 | 0 | +0.0000% | -7.4047% |

## 当日特征对照

这些分组来自已经看过的三只股票，只用于提出下一轮全体历史假设。

| 维度 | 分组 | N | 胜率 | 均值 |
| --- | --- | ---: | ---: | ---: |
| `attempt_number` | `1` | 35 | +40.0000% | -0.2108% |
| `attempt_number` | `2` | 13 | +30.7692% | -0.2709% |
| `attempt_number` | `3` | 4 | +50.0000% | +2.2845% |
| `attempt_number` | `4` | 2 | +100.0000% | +5.4385% |
| `support_line` | `ma10` | 15 | +53.3333% | +0.2837% |
| `support_line` | `ma20` | 22 | +36.3636% | +0.9678% |
| `support_line` | `ma5` | 17 | +35.2941% | -0.9665% |
| `volume_class` | `contraction` | 16 | +18.7500% | -2.4345% |
| `volume_class` | `expansion` | 12 | +41.6667% | +1.3653% |
| `volume_class` | `explosion` | 4 | +50.0000% | +2.0876% |
| `volume_class` | `normal` | 22 | +54.5455% | +1.0607% |
| `signal_direction` | `flat_or_down_close` | 10 | +30.0000% | -0.6605% |
| `signal_direction` | `up_close` | 44 | +43.1818% | +0.3573% |
| `structure_transition` | `ordinary_support_hold` | 44 | +43.1818% | +0.2585% |
| `structure_transition` | `structure_reclaimed` | 10 | +30.0000% | -0.2257% |

## 案例后假设的正确重放

下面三行先过滤原始候选、再从头顺序执行，不能从基础交易结果中事后挑选。
这些股票已经被查看，只能用于确定下一轮假设，不能发布为历史胜率。

| 案例假设 | 交易 | 单次胜率 | 均值 | 入场波段 | 波段胜率 | 包含东山 07-02 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `base_support_confirmation` | 54 | +40.7407% | +0.1688% | 35 | +51.4286% | True |
| `non_contraction_confirmation` | 39 | +48.7179% | +1.1982% | 28 | +60.7143% | True |
| `up_close_non_contraction` | 35 | +51.4286% | +1.5100% | 27 | +59.2593% | False |

`up_close_non_contraction` 会排除用户确认有效的东山精密 `2025-07-02`，
即使案例内数字更高，也不能把“D 日必须收涨”定成最终规则。

## 完整波段账本

| 股票/campaign | 浪 | 峰值 | 首次 5% 回调 | 最低点/支撑 | 再创新高 | 结构破坏 | 结果 |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| 东山精密 / `dongshan_2025_main_rise` | 1 | 2025-06-19 38.3500 | 2025-06-20 | 2025-06-23 35.8000 `ma5` | 2025-06-27 | - | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 2 | 2025-07-01 41.5500 | 2025-07-02 | 2025-07-02 38.5000 `ma5` | 2025-07-03 | - | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 3 | 2025-07-04 44.9900 | 2025-07-07 | 2025-07-08 40.1700 `ma5` | 2025-07-09 | - | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 4 | 2025-07-10 47.5000 | 2025-07-11 | 2025-07-11 43.9000 `ma5` | 2025-07-14 | - | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 5 | 2025-07-18 58.5000 | 2025-07-21 | 2025-07-28 51.3000 `ma10` | 2025-07-30 | - | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 6 | 2025-07-31 61.5000 | 2025-08-01 | 2025-08-18 48.6800 `below_ma20` | 2025-08-29 | 2025-08-05 | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 7 | 2025-09-02 71.5000 | 2025-09-03 | 2025-09-05 56.4800 `below_ma20` | 2025-09-10 | - | `continued_to_higher_high` |
| 东山精密 / `dongshan_2025_main_rise` | 8 | 2025-09-17 86.3300 | 2025-09-18 | 2025-09-24 73.5800 `ma10` | - | 2025-09-24 | `terminal_failure_observed` |
| 金安国纪 / `jinan_2026_main_rise` | 1 | 2026-01-20 22.4100 | 2026-01-21 | 2026-01-21 20.1100 `above_ma5` | 2026-01-22 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 2 | 2026-01-27 27.5400 | 2026-01-28 | 2026-02-06 23.0200 `ma10` | 2026-02-26 | 2026-02-04 | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 3 | 2026-02-26 27.8800 | 2026-02-27 | 2026-02-27 26.1000 `ma5` | 2026-03-03 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 4 | 2026-03-03 29.4500 | 2026-03-04 | 2026-03-09 23.8100 `below_ma20` | 2026-03-11 | 2026-03-09 | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 5 | 2026-03-11 30.3000 | 2026-03-12 | 2026-03-13 27.5900 `ma5` | 2026-03-16 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 6 | 2026-03-18 35.0000 | 2026-03-19 | 2026-03-24 27.8800 `below_ma20` | 2026-04-09 | 2026-03-23 | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 7 | 2026-04-10 38.8800 | 2026-04-13 | 2026-04-13 36.0100 `above_ma5` | 2026-04-14 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 8 | 2026-04-15 39.7900 | 2026-04-16 | 2026-04-16 36.4300 `ma5` | 2026-04-17 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 9 | 2026-04-23 47.3700 | 2026-04-24 | 2026-04-24 40.6700 `ma5` | 2026-04-28 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 10 | 2026-04-28 48.5100 | 2026-04-29 | 2026-05-06 43.5000 `ma10` | 2026-05-07 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 11 | 2026-05-07 50.2200 | 2026-05-08 | 2026-05-19 41.8000 `below_ma20` | 2026-05-27 | 2026-05-15 | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 12 | 2026-05-29 56.8000 | 2026-06-01 | 2026-06-02 46.8000 `below_ma20` | 2026-06-05 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 13 | 2026-06-16 102.9000 | 2026-06-17 | 2026-06-17 92.0500 `ma5` | 2026-06-18 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 14 | 2026-06-22 114.8500 | 2026-06-23 | 2026-06-23 102.8000 `ma5` | 2026-06-24 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 15 | 2026-06-25 120.0000 | 2026-06-26 | 2026-06-29 101.0300 `ma10` | 2026-06-30 | - | `continued_to_higher_high` |
| 金安国纪 / `jinan_2026_main_rise` | 16 | 2026-07-01 124.3800 | 2026-07-02 | 2026-07-06 96.2600 `below_ma20` | - | 2026-07-06 | `terminal_failure_observed` |
| 亨通光电 / `hengtong_2025_first_main_rise` | 1 | 2025-08-25 20.3300 | 2025-08-27 | 2025-08-27 18.8900 `ma5` | 2025-08-28 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_first_main_rise` | 2 | 2025-09-02 22.0100 | 2025-09-03 | 2025-09-04 18.8200 `below_ma20` | 2025-09-18 | 2025-09-09 | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_first_main_rise` | 3 | 2025-09-19 23.8500 | 2025-09-22 | 2025-09-23 21.5600 `ma5` | 2025-10-09 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_first_main_rise` | 4 | 2025-10-09 24.4800 | 2025-10-10 | 2025-10-14 20.7600 `below_ma20` | - | 2025-10-14 | `terminal_failure_observed` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 1 | 2025-12-24 27.0800 | 2025-12-25 | 2026-01-13 23.7800 `below_ma20` | 2026-01-19 | 2025-12-31 | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 2 | 2026-01-21 29.1700 | 2026-01-22 | 2026-01-22 26.5800 `ma5` | 2026-01-23 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 3 | 2026-01-28 35.0000 | 2026-01-29 | 2026-01-29 31.5000 `above_ma5` | 2026-01-30 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 4 | 2026-02-04 38.0200 | 2026-02-05 | 2026-02-06 34.1700 `ma10` | 2026-02-09 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 5 | 2026-02-11 43.5500 | 2026-02-12 | 2026-02-13 38.3800 `ma5` | 2026-02-26 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 6 | 2026-03-02 52.1900 | 2026-03-03 | 2026-03-09 43.5900 `ma10` | 2026-03-11 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 7 | 2026-03-11 54.3000 | 2026-03-12 | 2026-03-23 40.9200 `below_ma20` | 2026-03-31 | 2026-03-17 | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 8 | 2026-04-07 61.5000 | 2026-04-08 | 2026-04-16 50.8900 `below_ma20` | 2026-04-22 | 2026-04-15 | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 9 | 2026-04-27 74.4900 | 2026-04-28 | 2026-04-30 63.3000 `ma10` | 2026-05-07 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 10 | 2026-05-11 79.9000 | 2026-05-12 | 2026-05-28 65.6200 `below_ma20` | 2026-06-01 | 2026-05-21 | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 11 | 2026-06-05 102.9600 | 2026-06-08 | 2026-06-08 92.5500 `ma5` | 2026-06-09 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 12 | 2026-06-10 109.9900 | 2026-06-11 | 2026-06-15 92.8800 `ma10` | 2026-06-17 | - | `continued_to_higher_high` |
| 亨通光电 / `hengtong_2025_2026_second_main_rise` | 13 | 2026-06-23 125.1600 | 2026-06-24 | 2026-07-01 100.0000 `below_ma20` | - | 2026-07-01 | `terminal_failure_observed` |

## 每次实际入场与退出

| 股票 | 浪/尝试 | D 收盘买 | 支撑 | D+1 | 退出 | 净收益 | 后来创新高 | 归因 |
| --- | --- | --- | --- | ---: | --- | ---: | --- | --- |
| 东山精密 | 1/1 | 2025-06-23 36.9800 | `ma5` | -1.7955% | 2025-06-24 `d1_loss_stop` | -1.7955% | True | `entry_too_early` |
| 东山精密 | 1/2 | 2025-06-26 36.9300 | `ma5` | +1.5601% | 2025-06-27 `higher_high_confirmed` | +1.5601% | True | `profitable` |
| 东山精密 | 2/1 | 2025-07-02 39.6000 | `ma5` | +9.1434% | 2025-07-03 `higher_high_confirmed` | +9.1434% | True | `profitable` |
| 东山精密 | 3/1 | 2025-07-08 43.4500 | `ma10` | +6.6354% | 2025-07-09 `higher_high_confirmed` | +6.6354% | True | `profitable` |
| 东山精密 | 5/1 | 2025-07-21 54.9700 | `ma5` | -1.4007% | 2025-07-22 `d1_loss_stop` | -1.4007% | True | `entry_too_early` |
| 东山精密 | 5/2 | 2025-07-23 53.5900 | `ma10` | -0.3679% | 2025-07-24 `d1_loss_stop` | -0.3679% | True | `entry_too_early` |
| 东山精密 | 5/3 | 2025-07-28 54.4300 | `ma20` | +5.2198% | 2025-07-30 `higher_high_confirmed` | +3.9889% | True | `profitable` |
| 东山精密 | 6/1 | 2025-08-04 53.3100 | `ma20` | -1.8320% | 2025-08-05 `d1_loss_stop` | -1.8320% | True | `entry_too_early` |
| 东山精密 | 6/2 | 2025-08-11 55.6400 | `ma20` | +1.5793% | 2025-08-15 `structural_break` | -6.5264% | True | `entry_too_early` |
| 东山精密 | 7/1 | 2025-09-03 64.6400 | `ma10` | -10.1938% | 2025-09-04 `d1_loss_stop` | -10.1938% | True | `entry_too_early` |
| 东山精密 | 7/2 | 2025-09-05 64.0000 | `ma20` | +2.3156% | 2025-09-10 `higher_high_confirmed` | +12.6437% | True | `profitable` |
| 东山精密 | 8/1 | 2025-09-22 79.9800 | `ma10` | -4.5511% | 2025-09-23 `d1_loss_stop` | -4.5511% | False | `terminal_wave` |
| 金安国纪 | 1/1 | 2026-01-21 21.1800 | `ma5` | +9.8094% | 2026-01-22 `higher_high_confirmed` | +9.8094% | True | `profitable` |
| 金安国纪 | 2/1 | 2026-01-28 26.4200 | `ma5` | -7.0130% | 2026-01-29 `d1_loss_stop` | -7.0130% | True | `entry_too_early` |
| 金安国纪 | 2/2 | 2026-01-30 25.4600 | `ma10` | -4.8347% | 2026-02-02 `d1_loss_stop` | -4.8347% | True | `entry_too_early` |
| 金安国纪 | 2/3 | 2026-02-03 24.4500 | `ma20` | -1.9996% | 2026-02-04 `d1_loss_stop` | -1.9996% | True | `entry_too_early` |
| 金安国纪 | 2/4 | 2026-02-10 24.8500 | `ma20` | +6.8423% | 2026-02-26 `higher_high_confirmed` | +8.5324% | True | `profitable` |
| 金安国纪 | 3/1 | 2026-02-27 27.2500 | `ma5` | -0.1266% | 2026-03-02 `d1_loss_stop` | -0.1266% | True | `entry_too_early` |
| 金安国纪 | 4/1 | 2026-03-04 27.0900 | `ma20` | -2.1934% | 2026-03-05 `d1_loss_stop` | -2.1934% | True | `entry_too_early` |
| 金安国纪 | 4/2 | 2026-03-10 27.8700 | `ma20` | +2.4193% | 2026-03-11 `higher_high_confirmed` | +2.4193% | True | `profitable` |
| 金安国纪 | 5/1 | 2026-03-13 29.0500 | `ma5` | +9.8172% | 2026-03-16 `higher_high_confirmed` | +9.8172% | True | `profitable` |
| 金安国纪 | 6/1 | 2026-03-19 33.6000 | `ma5` | -7.0452% | 2026-03-20 `d1_loss_stop` | -7.0452% | True | `entry_too_early` |
| 金安国纪 | 6/2 | 2026-03-24 30.9900 | `ma20` | +1.1230% | 2026-04-02 `structural_break` | -6.5246% | True | `entry_too_early` |
| 金安国纪 | 7/1 | 2026-04-13 36.6000 | `ma5` | +5.7836% | 2026-04-14 `higher_high_confirmed` | +5.7836% | True | `profitable` |
| 金安国纪 | 8/1 | 2026-04-16 38.7400 | `ma10` | +0.2130% | 2026-04-17 `higher_high_confirmed` | +0.2130% | True | `profitable` |
| 金安国纪 | 9/1 | 2026-04-27 44.1000 | `ma10` | +4.7433% | 2026-04-28 `higher_high_confirmed` | +4.7433% | True | `profitable` |
| 金安国纪 | 10/1 | 2026-05-06 46.5600 | `ma10` | +6.1359% | 2026-05-07 `higher_high_confirmed` | +6.1359% | True | `profitable` |
| 金安国纪 | 11/1 | 2026-05-11 48.5000 | `ma5` | -4.2619% | 2026-05-12 `d1_loss_stop` | -4.2619% | True | `entry_too_early` |
| 金安国纪 | 11/2 | 2026-05-13 46.6100 | `ma20` | -3.0320% | 2026-05-14 `d1_loss_stop` | -3.0320% | True | `entry_too_early` |
| 金安国纪 | 11/3 | 2026-05-22 46.2700 | `ma20` | -1.6264% | 2026-05-25 `d1_loss_stop` | -1.6264% | True | `entry_too_early` |
| 金安国纪 | 11/4 | 2026-05-26 47.5500 | `ma20` | +2.3447% | 2026-05-27 `higher_high_confirmed` | +2.3447% | True | `profitable` |
| 金安国纪 | 12/1 | 2026-06-02 50.6300 | `ma20` | +1.9726% | 2026-06-05 `higher_high_confirmed` | +14.6726% | True | `profitable` |
| 金安国纪 | 14/1 | 2026-06-23 108.6400 | `ma5` | +6.3998% | 2026-06-24 `higher_high_confirmed` | +6.3998% | True | `profitable` |
| 金安国纪 | 15/1 | 2026-06-26 112.1300 | `ma10` | +2.3149% | 2026-06-30 `higher_high_confirmed` | +6.7919% | True | `profitable` |
| 金安国纪 | 16/1 | 2026-07-02 111.5800 | `ma20` | -4.3495% | 2026-07-03 `d1_loss_stop` | -4.3495% | False | `terminal_wave` |
| 亨通光电 | 2/1 | 2025-09-03 20.9000 | `ma10` | -7.9033% | 2025-09-04 `d1_loss_stop` | -7.9033% | True | `entry_too_early` |
| 亨通光电 | 2/2 | 2025-09-05 20.1000 | `ma20` | -2.1403% | 2025-09-08 `d1_loss_stop` | -2.1403% | True | `entry_too_early` |
| 亨通光电 | 2/3 | 2025-09-10 20.3900 | `ma20` | +2.5464% | 2025-09-18 `higher_high_confirmed` | +8.7750% | True | `profitable` |
| 亨通光电 | 3/1 | 2025-09-22 22.8700 | `ma5` | -3.8292% | 2025-09-23 `d1_loss_stop` | -3.8292% | True | `entry_too_early` |
| 亨通光电 | 3/2 | 2025-09-24 22.6100 | `ma10` | +1.2153% | 2025-10-09 `higher_high_confirmed` | +6.4342% | False | `profitable` |
| 亨通光电 | 4/1 | 2025-10-13 22.1500 | `ma20` | -6.1594% | 2025-10-14 `d1_loss_stop` | -6.1594% | False | `terminal_wave` |
| 亨通光电 | 1/1 | 2026-01-12 25.0400 | `ma20` | -4.1537% | 2026-01-13 `d1_loss_stop` | -4.1537% | True | `entry_too_early` |
| 亨通光电 | 1/2 | 2026-01-14 24.9500 | `ma20` | -0.3603% | 2026-01-15 `d1_loss_stop` | -0.3603% | True | `entry_too_early` |
| 亨通光电 | 4/1 | 2026-02-06 36.7000 | `ma10` | +5.2223% | 2026-02-09 `higher_high_confirmed` | +5.2223% | True | `profitable` |
| 亨通光电 | 5/1 | 2026-02-12 41.8500 | `ma5` | -8.2048% | 2026-02-13 `d1_loss_stop` | -8.2048% | True | `entry_too_early` |
| 亨通光电 | 6/1 | 2026-03-04 48.3800 | `ma10` | +5.0088% | 2026-03-11 `higher_high_confirmed` | +4.8021% | True | `profitable` |
| 亨通光电 | 7/1 | 2026-03-12 51.4200 | `ma5` | -3.5839% | 2026-03-13 `d1_loss_stop` | -3.5839% | True | `entry_too_early` |
| 亨通光电 | 7/2 | 2026-03-25 48.1700 | `ma20` | -0.8020% | 2026-03-26 `d1_loss_stop` | -0.8020% | True | `entry_too_early` |
| 亨通光电 | 8/1 | 2026-04-09 59.5400 | `ma10` | -6.1792% | 2026-04-10 `d1_loss_stop` | -6.1792% | True | `entry_too_early` |
| 亨通光电 | 8/2 | 2026-04-20 60.8900 | `ma20` | -1.9901% | 2026-04-21 `d1_loss_stop` | -1.9901% | True | `entry_too_early` |
| 亨通光电 | 9/1 | 2026-04-29 67.3800 | `ma10` | -2.6933% | 2026-04-30 `d1_loss_stop` | -2.6933% | True | `entry_too_early` |
| 亨通光电 | 10/1 | 2026-05-12 75.1000 | `ma5` | +0.2394% | 2026-05-21 `structural_break` | -7.1241% | True | `entry_too_early` |
| 亨通光电 | 12/1 | 2026-06-15 99.2800 | `ma20` | +8.0796% | 2026-06-17 `higher_high_confirmed` | +11.6050% | True | `profitable` |
| 亨通光电 | 13/1 | 2026-06-24 119.0200 | `ma5` | +3.1440% | 2026-07-01 `structural_break` | -14.5589% | False | `terminal_wave` |

## 研究边界

- The named stocks and campaign boundaries were already inspected by the user.
- Campaign end and wave resolution are retrospective labels; they never select D.
- The anchor rule is diagnosed here but is not yet validated across all leaders.
- These case metrics are not a population win rate or formal compound return.
- Case-hypothesis filters were proposed after inspecting these stocks and are replayed only to prevent post-filtering bias.
- Concept Top3 and GOLD/SILVER must be reattached only after this stock chronology is frozen.

下一步：Replace the old episode ordinal with this audited wave identity, then replay the unchanged close/D+1 contract and declared case hypotheses across all calculated historical leaders.

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-individual-leader-wave-audit --format markdown
```
