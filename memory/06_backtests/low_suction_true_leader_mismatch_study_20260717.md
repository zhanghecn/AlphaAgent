# AlphaAgent 真龙头漏抓审计

结论：`active_consensus_not_improved`。正式模式：`null`；低吸结果读取：`false`。

本报告冻结既有 1,087 周期真值，只审计概念关系风险与因果排序漏抓。
缺少涨停原因证据只表示未知，不表示当前成员关系已经被证明错误。

## Coverage

- 审计周期：`1087`；原有因果 Top3 捕获：`391`。
- 漏抓：`696`；关系/板块数据风险：`694`；关系基本可信的排序失败：`2`。
- 原报告因未来完整性过滤少写原有因果身份的周期：`30`；已按冻结数据指纹重建并复核原指标。
- 冻结输入 SHA256：`c0aeca850a7b58ef651497a6dd2a24751cedfc3c210a9e5c172acff5ad82b48f`。

## Candidate Breadth

| Candidate count | Cycles | Captured | Capture rate | Data-risk misses | Credible rank misses |
| --- | ---: | ---: | ---: | ---: | ---: |
| `3-5` | 108 | 73 | 67.5926% | 35 | 0 |
| `6-10` | 317 | 160 | 50.4732% | 157 | 0 |
| `11-20` | 309 | 102 | 33.0097% | 206 | 1 |
| `21-50` | 278 | 48 | 17.2662% | 229 | 1 |
| `51+` | 75 | 8 | 10.6667% | 67 | 0 |

## Mismatch Classes

| Class | Count |
| --- | ---: |
| `credible_relation_ranking_failure` | 2 |
| `relation_or_board_data_risk` | 694 |

## Decisive Rank Reasons

每个原因都将真值 Top1 与原有因果第 3 名准入边界比较。

| First disadvantage | Misses |
| --- | ---: |
| `truth_fewer_strong_days_10` | 46 |
| `truth_ignited_later` | 247 |
| `truth_ignition_not_precycle` | 39 |
| `truth_lower_precycle_excess` | 33 |
| `truth_main_rise_not_alive` | 331 |

## Confirmed Relation Rank Misses

| Date | Concept | Truth leader | Causal rank | Cutoff | First disadvantage | Active rank |
| --- | --- | --- | ---: | --- | --- | ---: |
| `2025-07-10` | 创新药 | 京新药业 `002020.SZSE` | 12 | `603456.SSE` | `truth_ignited_later` | 12 |
| `2025-07-10` | 可控核聚变 | 旭光电子 `600353.SSE` | 7 | `002735.SZSE` | `truth_main_rise_not_alive` | 5 |

- 京新药业：原因关系于 `2025-07-04` 确认；真龙头/第 3 名边界的主升状态为 `true/true`，首次强势领先 `4.0000/8.0000` 个交易日，10 日强势次数 `1.0000/1.0000`。
- 旭光电子：原因关系于 `2025-07-09` 确认；真龙头/第 3 名边界的主升状态为 `false/true`，首次强势领先 `8.0000/3.0000` 个交易日，10 日强势次数 `3.0000/2.0000`。

## Identity Modes

| Segment | Mode | Cycles | Top1 exact | Top3 captures truth Top1 | Top3 overlap |
| --- | --- | ---: | ---: | ---: | ---: |
| `all` | `causal_leadership` | 1087 | 15.5474% | 35.9706% | 33.7013% |
| `all` | `active_consensus` | 1087 | 11.6835% | 33.4867% | 31.2174% |
| `all` | `ten_day_excess_baseline` | 1087 | 10.3956% | 31.7387% | 30.2975% |
| `block_1` | `causal_leadership` | 179 | 17.8771% | 39.1061% | 34.0782% |
| `block_1` | `active_consensus` | 179 | 12.8492% | 41.8994% | 33.3333% |
| `block_1` | `ten_day_excess_baseline` | 179 | 11.7318% | 35.1955% | 31.0987% |
| `block_2` | `causal_leadership` | 198 | 14.1414% | 32.8283% | 30.6397% |
| `block_2` | `active_consensus` | 198 | 9.5960% | 29.7980% | 28.4512% |
| `block_2` | `ten_day_excess_baseline` | 198 | 8.5859% | 29.2929% | 28.7879% |
| `block_3` | `causal_leadership` | 225 | 16.4444% | 35.5556% | 36.7407% |
| `block_3` | `active_consensus` | 225 | 12.0000% | 34.6667% | 34.8148% |
| `block_3` | `ten_day_excess_baseline` | 225 | 9.7778% | 30.2222% | 32.1481% |
| `block_4` | `causal_leadership` | 306 | 16.6667% | 37.2549% | 33.2244% |
| `block_4` | `active_consensus` | 306 | 11.4379% | 30.3922% | 29.0850% |
| `block_4` | `ten_day_excess_baseline` | 306 | 9.4771% | 28.1046% | 27.8867% |
| `block_5` | `causal_leadership` | 179 | 11.7318% | 34.6369% | 33.7058% |
| `block_5` | `active_consensus` | 179 | 12.8492% | 32.9609% | 31.2849% |
| `block_5` | `ten_day_excess_baseline` | 179 | 13.4078% | 39.1061% | 32.9609% |

## Active Consensus

- 五块胜数：`1/5`；要求：`3`。
- 全体绝对身份门：`false`。
- 关系基本可信排序失败组：`2`；新 Top3 找回 `0`，找回率 `0.0000%`。
- 该子组只作漏抓解释；正式模式仍为 `null`。

## Board And Relation Risk

- 同日同一真龙头对应多个概念的漏抓周期：`183`。
- 当前成员 Jaccard 不低于 0.80 的漏抓周期：`0`。
- 涨停原因来源覆盖：`2025-06-27..2025-11-17`。

## Boundary

- current concept membership is a survivorship proxy, not historical point-in-time membership
- reason-event coverage starts late; absence before source coverage is unknown
- same-day overlapping concepts can describe one stock with several labels
- all five chronological blocks have already been inspected
- active_consensus is exploratory and cannot become a formal identity mode here
- identity accuracy does not establish a low-suction entry, win rate, return or compounding

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-true-leader-mismatch-study --format markdown
```
