# AlphaAgent 主升龙头低吸代理探索

> 状态：`superseded_proxy_snapshot`。本报告基于回补前 72 个完整概念日。后续固定窗口
> 结构消融否定了宽泛家族，V2 又取消了所有预设买点家族；本报告不再产生复测优先级。
> 失败归因见 `low_suction_structure_ablation_and_shared_evidence_20260716.md`。
> 本文样本数、胜率和分钟清单不得视为当前全窗结果，更不是正式绩效。

研究版本：`low-suction-membership-proxy-v1`\
结论：`blocked_by_data_quality`\
证据层级：`exploratory_membership_proxy`

本报告使用当前概念成员回填历史，只能发现待严格复测的假设，不能作为正式胜率或复利，
不构成投资建议。正式胜率、复利、最大回撤和策略资格均为 `null`。

## Data Window

- 完整概念信号日：`72` 天，`2026-03-13..2026-06-29`。
- 概念：`494`；当前成员代理：`41,342` 条。
- 当前主板非 ST 代理股票：`3,045` 只；股票日线：`372,803` 行。
- 事件：`22,794`；闭合退出：`68,047`。

## Time Splits

| Split | Dates | Range |
| --- | ---: | --- |
| `development` | 43 | 2026-03-13..2026-05-18 |
| `validation` | 14 | 2026-05-19..2026-06-05 |
| `holdout` | 15 | 2026-06-08..2026-06-29 |

## Product Cohort Fixed Exits

以下仅为 `main_rise_top3 / membership_proxy` 探索结果。

| Exit | Closed | Win rate | Mean | Median | Profit factor |
| --- | ---: | ---: | ---: | ---: | ---: |
| `entry_plus_1_close` | 1923 | 47.5819% | 0.1233% | -0.3105% | 1.0570 |
| `entry_plus_3_close` | 1924 | 45.4782% | 0.2484% | -0.6400% | 1.0785 |
| `entry_plus_5_close` | 1922 | 47.1384% | 0.4460% | -0.6120% | 1.1122 |

## Falsification Cohorts

| Cohort | Exit | Closed | Win rate | Mean | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: |
| `main_rise_rank_4_10` | `entry_plus_1_close` | 9276 | 46.1945% | 0.1724% | 1.0833 |
| `main_rise_rank_4_10` | `entry_plus_3_close` | 9268 | 44.5188% | 0.2300% | 1.0767 |
| `main_rise_rank_4_10` | `entry_plus_5_close` | 9264 | 46.0276% | 0.3889% | 1.1013 |
| `main_rise_top3` | `entry_plus_1_close` | 1923 | 47.5819% | 0.1233% | 1.0570 |
| `main_rise_top3` | `entry_plus_3_close` | 1924 | 45.4782% | 0.2484% | 1.0785 |
| `main_rise_top3` | `entry_plus_5_close` | 1922 | 47.1384% | 0.4460% | 1.1122 |
| `non_main_rise_top3` | `entry_plus_1_close` | 11481 | 45.7974% | 0.0708% | 1.0289 |
| `non_main_rise_top3` | `entry_plus_3_close` | 11497 | 43.7244% | -0.3232% | 0.9129 |
| `non_main_rise_top3` | `entry_plus_5_close` | 11492 | 44.6223% | -0.2275% | 0.9494 |

## Three Event Families

同一事件可同时属于多个家族，因此下表家族样本不能相加。

| Family | Exit | Closed | Win rate | Mean | Profit factor |
| --- | --- | ---: | ---: | ---: | ---: |
| `first_bearish_or_break_repair` | `entry_plus_1_close` | 851 | 47.7086% | 0.3612% | 1.1528 |
| `first_bearish_or_break_repair` | `entry_plus_3_close` | 851 | 45.5934% | 0.5206% | 1.1519 |
| `first_bearish_or_break_repair` | `entry_plus_5_close` | 852 | 48.8263% | 0.8200% | 1.1955 |
| `first_divergence` | `entry_plus_1_close` | 1337 | 48.5415% | 0.2136% | 1.1047 |
| `first_divergence` | `entry_plus_3_close` | 1336 | 45.1347% | 0.1967% | 1.0632 |
| `first_divergence` | `entry_plus_5_close` | 1335 | 47.1910% | 0.4614% | 1.1205 |
| `second_wave_pullback` | `entry_plus_1_close` | 530 | 50.0000% | 0.1593% | 1.0770 |
| `second_wave_pullback` | `entry_plus_3_close` | 530 | 47.5472% | 0.7744% | 1.2838 |
| `second_wave_pullback` | `entry_plus_5_close` | 529 | 47.8261% | 0.8361% | 1.2264 |

## Gold And Silver Fingers

金手指、银手指和危险状态只做分层，不作为入场开关。

| Active state | Risk | Exit | Closed | Win rate | Mean | Profit factor |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| `GOLD` | `DANGER` | `entry_plus_1_close` | 56 | 14.2857% | -4.7570% | 0.1109 |
| `GOLD` | `DANGER` | `entry_plus_3_close` | 56 | 12.5000% | -6.3288% | 0.1048 |
| `GOLD` | `DANGER` | `entry_plus_5_close` | 56 | 12.5000% | -10.4315% | 0.0629 |
| `GOLD` | `NORMAL` | `entry_plus_1_close` | 1731 | 49.2779% | 0.4002% | 1.2046 |
| `GOLD` | `NORMAL` | `entry_plus_3_close` | 1732 | 47.6328% | 0.7402% | 1.2620 |
| `GOLD` | `NORMAL` | `entry_plus_5_close` | 1730 | 49.0173% | 0.9940% | 1.2762 |
| `SILVER` | `DANGER` | `entry_plus_1_close` | 120 | 40.0000% | -1.4479% | 0.5963 |
| `SILVER` | `DANGER` | `entry_plus_3_close` | 120 | 30.0000% | -3.5386% | 0.4068 |
| `SILVER` | `DANGER` | `entry_plus_5_close` | 120 | 35.0000% | -2.4034% | 0.6009 |
| `SILVER` | `NORMAL` | `entry_plus_1_close` | 16 | 37.5000% | -0.9720% | 0.6234 |
| `SILVER` | `NORMAL` | `entry_plus_3_close` | 16 | 43.7500% | -1.5623% | 0.7010 |
| `SILVER` | `NORMAL` | `entry_plus_5_close` | 16 | 56.2500% | 0.6334% | 1.1454 |

## Strict Retest Priorities

优先级只由验证段产生；留出段和双倍成本只用于随后检查，不反向选择。

| Family | Exit | Validation n/win/mean/PF | Holdout n/win/mean/PF | Double-cost holdout n/win/mean/PF | Stock/concept/month concentration |
| --- | --- | --- | --- | --- | --- |
| `first_bearish_or_break_repair` | `entry_plus_1_close` | 111 / 43.2432% / 0.2274% / 1.0787 | 107 / 62.6168% / 3.0718% / 2.7963 | 107 / 59.8131% / 2.7554% / 2.5118 | 6.4349% / 6.0372% / 100.0000% |

## Execution Gaps

- `entry_at_limit_up`：159
- `exit_at_limit_down`：101
- `insufficient_cash`：18
- `missing_entry_bar`：33
- `missing_exit_bar`：24

## Candidate Minute Coverage

对 1,930 个 `main_rise_top3` 代理事件逐一读取股票/日期分钟线，不请求全市场多年分钟数据：

- 候选股票/日期对：1,930；必要时段清单：7,720 行（每对 4 个时段）。
- 完整时段：196（2.5389%）；不完整时段：60；完全缺失时段：7,464。
- 必要分钟数：453,550；必要时段内已有分钟数：14,355（3.1650%）。
- 候选查询共读到 14,494 条一分钟记录；有数据的 256 个时段来自 AkShare 20、
  Eastmoney 144、TDX 92。

该清单仍是 `membership_proxy` 候选覆盖审计，不是严格分钟回测。分钟路径远未完整，
不能据此计算正式胜率、复利或选择盘中入场方式。

## Limits

- current concept members are backfilled across history
- historical ST/listing/delist status is unavailable
- daily proxy observes D close and enters D+1 open
- entry+1/3/5 close exits are not the strict intraday D+1 exits
- concept correlation is neutral in the proxy leader block
- formal compounding and maximum drawdown remain null

## Decision

本轮只保留上表组合为严格数据复测优先级，不选择生产规则。只有补齐三年点时成员、
历史证券状态和候选分钟路径，并通过至少 300 笔锁定留出交易、10% 回撤及双倍成本
门禁后，才可能产生 `qualified_research_rule`。

## Reproduce

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli proxy-discovery --format markdown
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli minute-manifest --format json
```
