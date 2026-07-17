# AlphaAgent 真龙头与多波主升识别研究

结论：`stable_relative_improvement_but_identity_accuracy_insufficient`。正式 Top3：`false`；正式绩效：`null`。

本研究先识别龙头，不研究买点。广泛验证只使用发现段；2026 三只个股是已经看过的
描述性案例，不参与特征选择或样本外主张。波次必须满足不同交易日上的
`记录高点 -> 至少 5% 回调 -> 更高记录高点`。

## Coverage

- 发现段：`2023-03-28..2025-11-17`。
- 原始概念周期起点：`5134`；情绪周期：`1219`；完整真值周期：`1087`。
- 因果候选：`24492` 行 / `2611` 股。
- 当前成员代理：`32713` 行；严格历史成员：`0` 行。

## Identity Validation

| Segment | Mode | Cycles | Top1 exact | Top3 captures truth Top1 | Top3 overlap | Wave delta vs rest | Max excess delta |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `all` | `causal_leadership` | 1087 | 15.5474% | 35.9706% | 33.7013% | 0.4463 | 1.2396 |
| `all` | `ten_day_excess_baseline` | 1087 | 10.3956% | 31.7387% | 30.2975% | 0.1558 | 4.1519 |
| `block_1` | `causal_leadership` | 179 | 17.8771% | 39.1061% | 34.0782% | 0.5770 | 1.3777 |
| `block_1` | `ten_day_excess_baseline` | 179 | 11.7318% | 35.1955% | 31.0987% | 0.3486 | 2.2397 |
| `block_2` | `causal_leadership` | 198 | 14.1414% | 32.8283% | 30.6397% | 0.3042 | 0.7703 |
| `block_2` | `ten_day_excess_baseline` | 198 | 8.5859% | 29.2929% | 28.7879% | 0.0577 | 3.9349 |
| `block_3` | `causal_leadership` | 225 | 16.4444% | 35.5556% | 36.7407% | 0.3812 | 0.3512 |
| `block_3` | `ten_day_excess_baseline` | 225 | 9.7778% | 30.2222% | 32.1481% | 0.0905 | 0.8726 |
| `block_4` | `causal_leadership` | 306 | 16.6667% | 37.2549% | 33.2244% | 0.6187 | 4.1473 |
| `block_4` | `ten_day_excess_baseline` | 306 | 9.4771% | 28.1046% | 27.8867% | 0.1485 | 8.2216 |
| `block_5` | `causal_leadership` | 179 | 11.7318% | 34.6369% | 33.7058% | 0.3264 | -0.9879 |
| `block_5` | `ten_day_excess_baseline` | 179 | 13.4078% | 39.1061% | 32.9609% | 0.2336 | 4.6094 |

五块胜负：因果模式 `4`，基线 `1`，平局 `0`。
相对改善：`true`；绝对准确率门：`false`。

## Stock Leads, Concept Follows

| Cohort | Rows | Pre-cycle ignition | Median lead sessions | Stock return to cycle | Concept response to cycle | Concept next 5d |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `truth_top1` | 1087 | 91.3523% | 6.0000 | 6.4622% | 4.8121% | 1.5577% |
| `truth_top3` | 3261 | 89.9724% | 5.0000 | 6.1387% | 4.7129% | 1.5577% |
| `other_candidates` | 18320 | 87.3362% | 4.0000 | 4.6804% | 4.4691% | 1.7321% |

## Reference Campaigns

| Stock | Anchor | Waves | Confirmed higher highs | Final high | Final state |
| --- | --- | ---: | ---: | ---: | --- |
| 上海建工 `600170.SSE` | `2025-09-15` | 1 | 0 | 3.8800 | `terminal_failure_observed` |
| ↳ 第 1 波 | 峰 `2025-09-18` | 3.8800 | 回调 `2026-06-29` | 支撑 `below_ma20` | `terminal_failure_observed` |
| 金安国纪 `002636.SZSE` | `2026-01-15` | 16 | 15 | 124.3800 | `terminal_failure_observed` |
| ↳ 第 1 波 | 峰 `2026-01-20` | 22.4100 | 回调 `2026-01-21` | 支撑 `above_ma5` | `continued_to_higher_high` |
| ↳ 第 2 波 | 峰 `2026-01-27` | 27.5400 | 回调 `2026-02-06` | 支撑 `ma10` | `continued_to_higher_high` |
| ↳ 第 3 波 | 峰 `2026-02-26` | 27.8800 | 回调 `2026-02-27` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 4 波 | 峰 `2026-03-03` | 29.4500 | 回调 `2026-03-09` | 支撑 `below_ma20` | `continued_to_higher_high` |
| ↳ 第 5 波 | 峰 `2026-03-11` | 30.3000 | 回调 `2026-03-13` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 6 波 | 峰 `2026-03-18` | 35.0000 | 回调 `2026-03-24` | 支撑 `below_ma20` | `continued_to_higher_high` |
| ↳ 第 7 波 | 峰 `2026-04-10` | 38.8800 | 回调 `2026-04-13` | 支撑 `above_ma5` | `continued_to_higher_high` |
| ↳ 第 8 波 | 峰 `2026-04-15` | 39.7900 | 回调 `2026-04-16` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 9 波 | 峰 `2026-04-23` | 47.3700 | 回调 `2026-04-24` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 10 波 | 峰 `2026-04-28` | 48.5100 | 回调 `2026-05-06` | 支撑 `ma10` | `continued_to_higher_high` |
| ↳ 第 11 波 | 峰 `2026-05-07` | 50.2200 | 回调 `2026-05-19` | 支撑 `below_ma20` | `continued_to_higher_high` |
| ↳ 第 12 波 | 峰 `2026-05-29` | 56.8000 | 回调 `2026-06-02` | 支撑 `below_ma20` | `continued_to_higher_high` |
| ↳ 第 13 波 | 峰 `2026-06-16` | 102.9000 | 回调 `2026-06-17` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 14 波 | 峰 `2026-06-22` | 114.8500 | 回调 `2026-06-23` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 15 波 | 峰 `2026-06-25` | 120.0000 | 回调 `2026-06-29` | 支撑 `ma10` | `continued_to_higher_high` |
| ↳ 第 16 波 | 峰 `2026-07-01` | 124.3800 | 回调 `2026-07-17` | 支撑 `below_ma20` | `terminal_failure_observed` |
| 生益科技 `600183.SSE` | `2026-05-13` | 6 | 5 | 191.8800 | `terminal_failure_observed` |
| ↳ 第 1 波 | 峰 `2026-05-14` | 100.5000 | 回调 `2026-05-15` | 支撑 `ma5` | `continued_to_higher_high` |
| ↳ 第 2 波 | 峰 `2026-05-27` | 140.0000 | 回调 `2026-05-28` | 支撑 `above_ma5` | `continued_to_higher_high` |
| ↳ 第 3 波 | 峰 `2026-06-01` | 147.9000 | 回调 `2026-06-08` | 支撑 `ma10` | `continued_to_higher_high` |
| ↳ 第 4 波 | 峰 `2026-06-10` | 154.5000 | 回调 `2026-06-11` | 支撑 `above_ma5` | `continued_to_higher_high` |
| ↳ 第 5 波 | 峰 `2026-06-17` | 191.0000 | 回调 `2026-06-18` | 支撑 `above_ma5` | `continued_to_higher_high` |
| ↳ 第 6 波 | 峰 `2026-06-22` | 191.8800 | 回调 `2026-07-17` | 支撑 `below_ma20` | `terminal_failure_observed` |

## Boundary

当前成员表不是历史点时成分，旧留出也已被查看，所以本报告只能比较身份代理，
不能给出正式 Top3、低吸胜率、收益或复利。上海建工的未创新高路径被保留为
终止反例；金安国纪和生益科技的多波路径只用于检查状态机是否理解真实个股。

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-true-leader-wave-study --format markdown
```
