# 首板双阶段竞争风险触发研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 研究版本：`limit-up-preboard-competing-risk-v2`；正式策略修改：`False`。
- 验证性质：`viewed_expanded_historical_time_validation`。
- 一分钟完整覆盖：15921/15921（100.00%）。
- 共用规则后股票日：962；每日中位 8，最多 71。
- 同刻多股竞争分钟：4084；同刻最多 52 只。
- 分钟/日线数值一致：15921/15921（100.00%）。

## Frozen models

| 模型 | 状态 | 训练股票日 | 指纹 |
| --- | --- | ---: | --- |
| 正式身份 | `ready` | 235 | `08e4e9edc2139605` |
| 3分钟到板 | `ready` | 235 | `73ad238eb49436d8` |
- 正式身份主要正向标准化系数：`gain_pct` +1.7177、`gain_strength_pct` +0.2423、`return_1m_pct` +0.2033、`history_combined_rate` +0.1329、`entry_quality_score` +0.1274；主要负向：`minute_of_window` -0.4595、`prior_30m_floor_pct` -0.4166、`prior_30m_floor_strength_pct` -0.2571、`history_sample_count_log1p` -0.2463、`bar_close_location` -0.2154。
- 3分钟到板主要正向标准化系数：`gain_pct` +0.9397、`support_score` +0.9085、`prior_30m_floor_strength_pct` +0.7175、`active_candidate_count_log1p` +0.5685、`session_drawdown_pct` +0.5393；主要负向：`minute_of_window` -0.9192、`turnover_acceleration_1m` -0.4346、`history_sample_count_log1p` -0.4202、`return_5m_pct` -0.2214、`history_combined_rate` -0.1515。

- 校准阈值：0.9000；状态：`ready`。

## Same-account validation

| 方案 | 信号 | 身份精度 | 3分钟命中 | 可达召回 | 成交 | 胜率 | 复利 | 回撤 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 当前触板基线 | - | - | - | - | 23 | 73.91% | +36.73% | -4.44% |
| 双阶段确认行动 | 34 | 70.59% | 26.47% | 36.36% | 23 | 43.48% | -10.36% | -20.65% |
| 双阶段行动-双倍成本 | 34 | 70.59% | 26.47% | 36.36% | 23 | 43.48% | -13.15% | -22.08% |
| 双阶段行动-保守成交 | 34 | 70.59% | 26.47% | 36.36% | 23 | 43.48% | -11.41% | -21.37% |

- 原账户成交身份精度/召回：40.91%/42.86%。

## Account-path attribution

| 类别 | 股票日 | 触板/封板 | 闭合 | 胜率 | 平均收益 | 净损益 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `matched_original_account` | 9 | 9/7 | 9 | 66.67% | +2.69% | +12242.83 |
| `formal_identity_true_but_not_original_account` | 4 | 4/2 | 4 | 25.00% | -1.90% | -3839.40 |
| `formal_identity_false_positive` | 9 | 2/1 | 8 | 12.50% | -4.84% | -19352.19 |

| 类别 | 涨幅中位 | identity P | timing P | action score | support | 原Rank | 3分钟收益 | 30分钟底部 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `matched_original_account` | +8.73% | 0.9909 | 0.9974 | 0.9848 | 82.3575 | 75.4869 | +2.93% | +1.68% |
| `formal_identity_true_but_not_original_account` | +8.07% | 0.9804 | 0.9709 | 0.9471 | 74.7899 | 67.5945 | +2.63% | +0.41% |
| `formal_identity_false_positive` | +8.79% | 0.9793 | 0.9932 | 0.9689 | 77.8297 | 71.4856 | +1.34% | +3.84% |

- 原账户已成交但提前账户未成交：12 个股票日；归因 `{"action_signal_blocked_by_position_limit": 1, "no_eligible_preboard_prefix": 5, "threshold_not_confirmed_two_minutes": 6}`。
- 提前首板因仓位上限跳过：11；其中正式候选 10，原账户身份 1。
- 同一账户身份闭合 9 笔；提前相对触板平均收益差 +1.16%。

### Filled divergence ledger

| 日期 | 股票 | 类别 | D+1净收益 |
| --- | --- | --- | ---: |
| 2026-06-24 | 000417.SZSE | `filled_formal_identity_false_positive` | -5.53% |
| 2026-07-06 | 000703.SZSE | `filled_formal_identity_false_positive` | -11.43% |
| 2026-06-11 | 002025.SZSE | `filled_formal_identity_false_positive` | -5.64% |
| 2026-06-22 | 002155.SZSE | `filled_formal_identity_false_positive` | -12.07% |
| 2026-07-02 | 002378.SZSE | `filled_formal_identity_not_original_account` | -7.13% |
| 2026-07-09 | 002409.SZSE | `filled_formal_identity_not_original_account` | -0.01% |
| 2026-06-15 | 002859.SZSE | `filled_formal_identity_false_positive` | +7.88% |
| 2026-07-14 | 601101.SSE | `filled_formal_identity_not_original_account` | +2.77% |
| 2026-07-16 | 603011.SSE | `filled_formal_identity_false_positive` | - |
| 2026-06-17 | 603026.SSE | `filled_formal_identity_false_positive` | -6.68% |
| 2026-07-02 | 603031.SSE | `filled_formal_identity_not_original_account` | -3.21% |
| 2026-07-13 | 603031.SSE | `filled_formal_identity_false_positive` | -2.70% |
| 2026-06-26 | 603806.SSE | `filled_formal_identity_false_positive` | -2.52% |

### Missed original-account ledger

| 日期 | 股票 | 原因 | 最高action score | 首次确认 | 原触板账户收益 |
| --- | --- | --- | ---: | --- | ---: |
| 2026-07-02 | 000506.SZSE | `threshold_not_confirmed_two_minutes` | 0.9611 | - | +9.76% |
| 2026-06-18 | 000534.SZSE | `threshold_not_confirmed_two_minutes` | 0.9310 | - | -2.74% |
| 2026-06-24 | 000703.SZSE | `threshold_not_confirmed_two_minutes` | 0.9428 | - | +3.73% |
| 2026-07-14 | 001389.SZSE | `no_eligible_preboard_prefix` | - | - | +5.42% |
| 2026-07-02 | 002196.SZSE | `threshold_not_confirmed_two_minutes` | 0.9563 | - | +3.49% |
| 2026-06-11 | 002378.SZSE | `no_eligible_preboard_prefix` | - | - | +2.79% |
| 2026-07-14 | 600183.SSE | `no_eligible_preboard_prefix` | - | - | +2.84% |
| 2026-07-06 | 600246.SSE | `threshold_not_confirmed_two_minutes` | 0.9002 | - | +9.76% |
| 2026-07-08 | 600488.SSE | `no_eligible_preboard_prefix` | - | - | -3.85% |
| 2026-07-16 | 603496.SSE | `no_eligible_preboard_prefix` | - | - | -2.52% |
| 2026-07-08 | 603881.SSE | `threshold_not_confirmed_two_minutes` | 0.9927 | - | +0.65% |
| 2026-06-15 | 603989.SSE | `action_signal_blocked_by_position_limit` | 0.9820 | - | +8.18% |

## Validation blocks

| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2026-06-04..2026-06-11 | 7 | 5 | 80.00% | +7.71% | -1.36% |
| 2 | 2026-06-12..2026-06-22 | 8 | 5 | 40.00% | +1.48% | -5.38% |
| 3 | 2026-06-23..2026-06-30 | 7 | 6 | 33.33% | -2.50% | -4.91% |
| 4 | 2026-07-01..2026-07-08 | 5 | 3 | 0.00% | -10.36% | -10.36% |
| 5 | 2026-07-09..2026-07-16 | 7 | 4 | 50.00% | -4.41% | -4.99% |

## Decision

- 历史门禁：`FAIL`。
- `baseline_parity`：通过。
- `both_models_ready`：通过。
- `calibration_threshold_ready`：通过。
- `minimum_30_validation_actions`：通过。
- `minimum_70pct_formal_precision`：通过。
- `minimum_70pct_original_account_identity_precision`：未通过。
- `minimum_30pct_reachable_recall`：通过。
- `positive_normal_account_return`：未通过。
- `positive_double_cost_account_return`：未通过。
- `maximum_drawdown_no_worse_than_10pct`：未通过。
- `d1_win_rate_within_2pct_of_touch_baseline`：未通过。
- `minimum_3_of_5_positive_validation_blocks`：未通过。

## Forward validation

- 状态：`collecting_forward_overlay`；交易日 0，雷达帧 0。
- 正式执行影响固定为 `none_research_only`。

## Limitations

- 89日中的后30日已被此前研究查看，只能称扩展历史时间验证，不是新的锁定留出。
- TDX一分钟K线不是Tick/L2，不能证明主动大单方向、排队、撤单或秒级成交。
- 历史没有完整点时动态概念、行业扩散、资金流和快照新鲜度，这些字段只允许前向保存。
- 历史门通过也只允许冻结前向影子；正式v9/v15保持不变。
