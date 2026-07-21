# 首板逐笔三态触发 v5 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 研究版本：`limit-up-preboard-transaction-disposition-v5`；正式策略修改：`False`。
- 逐笔覆盖：股票日 962/962；分钟前缀 22804/22821。

## Deterministic rerun

- 连续两次完整复跑除 `performance` 耗时外，整份 JSON 逐字段完全一致；日期切分、
  覆盖、模型、阈值、信号、验证账户、五块结果、验收和结论均一致。
- 母池/逐笔输入/三态指纹分别为
  `sha256:82c0c1e3b9fa652ee20395fe93b841d3cc9554f36bf9c3087dfd3c24a0117d89`、
  `sha256:d80a97a3e7752637832b540eec65dbd063f62a1038f6c8a422314ea19284e7b1`、
  `sha256:95534acd4ac54087dc5f75636994337f13e86ec3e7be2e7f35fb3e113dd79ad4`。
- v5 动作政策/验证账户指纹分别为
  `sha256:6f0f13fe6099c5076d7ffad24af60eaf84201a0adfc2b26c8199f68a657e3eff`、
  `sha256:16ade67d43baa7e8f62692ac19ffcc199cb0ebeb3cdf00a69d8ed8ed12a320a2`。

## Same-account validation

| 方案 | 信号 | 原账户身份精度 | 原账户召回 | 成交 | 胜率 | 复利 | 回撤 | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v3分钟模型 | 34 | 30.43% | 33.33% | 25 | 44.00% | -16.84% | -26.25% | 0.6451 |
| v5逐笔模型 | 30 | 30.00% | 28.57% | 21 | 42.86% | -16.78% | -22.68% | 0.6607 |

## Validation blocks

| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2026-06-04..2026-06-11 | 6 | 4 | 75.00% | +6.03% | -1.38% |
| 2 | 2026-06-12..2026-06-22 | 8 | 5 | 20.00% | -8.24% | -12.84% |
| 3 | 2026-06-23..2026-06-30 | 4 | 5 | 40.00% | +2.92% | -2.71% |
| 4 | 2026-07-01..2026-07-08 | 6 | 4 | 25.00% | -9.43% | -10.36% |
| 5 | 2026-07-09..2026-07-16 | 6 | 5 | 60.00% | -3.37% | -5.46% |

## Incremental attribution

- `v3_false_momentum_removed_by_v4`：13 个股票日。
- `v3_original_account_identity_retained`：5 个股票日。
- `v3_original_account_identity_killed_by_v4`：3 个股票日。
- `v4_new_original_account_identity`：1 个股票日。
- `v4_new_false_positive`：11 个股票日。

## Causal no-action attribution

- 全样本 17 个分钟、14 个股票日；验证段 7 个分钟、6 个股票日。
- 验证段与正式候选身份交集 1；与原两仓实际成交身份交集 1。

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
- `v3_reference_parity`：通过。
- `transaction_scope_coverage_100pct`：通过。
- `transaction_disposition_coverage_100pct`：通过。
- `transaction_data_missing_zero`：通过。
- `minimum_95pct_scoreable_prefixes`：通过。
- `minimum_1_2_normal_account_profit_factor`：未通过。

## Forward validation

- 状态：`not_promoted_historical_rejected`；交易日 0，闭合行动 0。

## Limitations

- 后30日已经被此前研究查看，只能称扩展历史时间反证，不是新的锁定留出。
- TDX逐笔是成交记录，不包含委托队列、撤单和封单排队。
- buyorsell枚举缺少可信公开语义，方向特征只使用direction_0/1中性名称。
- 历史通过也只允许冻结前向影子；正式v9/v15保持不变。
