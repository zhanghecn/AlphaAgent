# 首板提前联合触发 v3 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 研究版本：`limit-up-preboard-joint-trigger-v3`；正式策略修改：`False`。
- 共用规则后股票日：962；可评分分钟前缀：22821。
- 日期切分指纹：`sha256:92673999e5c5af1d1e9d7d118ba385bc59acd56ed94ae6cb9c757fb64dfdc0c1`；行动策略指纹：`sha256:72f48bd453ac8f3455cf0ed92945da3bf523e6547d4800bc41f6e8ac13146917`。

## Frozen models

| 模型 | 状态 | 训练股票日 | 指纹 |
| --- | --- | ---: | --- |
| 5分钟准备 | `ready` | 235 | `dad05e19169d9b24` |
| 3分钟联合行动 | `ready` | 235 | `0fa5bf1592cbe59c` |

- 联合行动阈值：0.1500；状态：`ready`。

## Same-account validation

| 信号 | 候选身份精度 | 3分钟命中 | 联合标签精度 | 原账户身份精度 | 原账户召回 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 34 | 61.76% | 26.47% | 14.71% | 30.43% | 33.33% |

| 账户 | 成交 | 胜率 | 复利 | 回撤 | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 当前触板基线 | 23 | 73.91% | +36.73% | -4.44% | 4.2555 |
| v3联合行动 | 25 | 44.00% | -16.84% | -26.25% | 0.6451 |
| v3双倍成本 | 25 | 44.00% | -19.51% | -27.66% | 0.5944 |
| v3保守成交 | 25 | 44.00% | -17.85% | -26.98% | 0.6294 |

## Validation blocks

| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2026-06-04..2026-06-11 | 7 | 5 | 80.00% | +7.71% | -1.36% |
| 2 | 2026-06-12..2026-06-22 | 8 | 5 | 20.00% | -5.22% | -5.22% |
| 3 | 2026-06-23..2026-06-30 | 6 | 5 | 40.00% | -1.87% | -6.97% |
| 4 | 2026-07-01..2026-07-08 | 7 | 5 | 20.00% | -15.71% | -16.01% |
| 5 | 2026-07-09..2026-07-16 | 6 | 6 | 33.33% | -7.11% | -7.41% |

## Decision

- 历史门禁：`FAIL`。
- `baseline_parity`：通过。
- `both_models_ready`：通过。
- `calibration_threshold_ready`：通过。
- `minimum_30_validation_actions`：通过。
- `minimum_70pct_formal_precision`：未通过。
- `minimum_70pct_original_account_identity_precision`：未通过。
- `minimum_30pct_reachable_recall`：通过。
- `positive_normal_account_return`：未通过。
- `positive_double_cost_account_return`：未通过。
- `maximum_drawdown_no_worse_than_10pct`：未通过。
- `d1_win_rate_within_2pct_of_touch_baseline`：未通过。
- `minimum_3_of_5_positive_validation_blocks`：未通过。

## Forward validation

- 状态：`collecting_forward_overlay`；交易日 0，雷达帧 0。

## Limitations

- 89日中的后30日已被此前研究查看，只能称扩展历史时间反证，不是新的锁定留出。
- TDX一分钟K线不是Tick/L2，不能证明主动大单方向、排队、撤单或秒级成交。
- 历史没有完整点时动态概念、行业扩散、资金流和快照新鲜度，这些字段只允许前向保存。
- 历史门通过也只允许冻结前向影子；正式v9/v15保持不变。
