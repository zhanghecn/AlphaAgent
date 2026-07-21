# 首板雷达原生序列触发 v8 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 正式策略修改：`False`；执行影响：`none_research_only`。
- 主窗口：2026-03-09..2026-07-16，89 日、15921 个股票日。
- 排除扩展：692 个股票日，缺失 139，状态 `excluded_training_extension_provider_unavailable`。

## Models and calibration

- 第一层：`ready`，训练 5378 行，指纹 `sha256:15f4554dde2b1e513b8ee1f78981f1a4c7d4a78bc6f005e5e9112724ee01d012`。
- 第二层：`ready`，OOF Top1 训练 1703 行，指纹 `sha256:9eb453cc6e942d27aded45e21a83bb26645643db5a62b65389b892c01f24ff31`。
- 校准：`calibration_precision_gate_failed`，阈值 `None`；最低 10 个股票日且精度至少 70.00%。

## Validation

| 方案 | 动作/成交 | 胜率 | 复利 | 回撤 | PF |
| --- | ---: | ---: | ---: | ---: | ---: |
| 当前触板基线 | 23 | 73.91% | +36.73% | -4.44% | 4.2555 |
| v8 联合账户 | 0/3 | 100.00% | +9.27% | -0.67% | - |

- 三分钟触板精度：-；正式身份精度：-；可达召回：0.00%。

## Decision

- `baseline_parity`：通过。
- `both_models_ready`：通过。
- `calibration_threshold_ready`：未通过。
- `minimum_30_validation_actions`：未通过。
- `minimum_70pct_formal_precision`：未通过。
- `minimum_70pct_original_account_identity_precision`：未通过。
- `minimum_30pct_reachable_recall`：未通过。
- `positive_normal_account_return`：通过。
- `positive_double_cost_account_return`：通过。
- `maximum_drawdown_no_worse_than_10pct`：通过。
- `d1_win_rate_within_2pct_of_touch_baseline`：通过。
- `minimum_1_2_normal_account_profit_factor`：未通过。
- `minimum_3_of_5_positive_validation_blocks`：未通过。

后 30 日是已查看历史反证；即使全部历史门通过，也只能进入冻结后只读前向。
