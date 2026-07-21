# 首板短时触板 Hazard 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 一分钟完整覆盖：12187/12187（100.0000%）。
- `>=3%` 只是观测母池；只有3分钟模型首次过阈且同分钟进入Top2才形成行动信号。
- 5分钟模型只做准备提醒，1分钟模型只报告紧迫度；两者均不下单。

## Frozen models

| 目标 | 状态 | 阈值 | 训练股票日 | 校准选择 | 校准精确率 | 指纹 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| 1分钟 | `ready` | 0.9500 | 234 | 27 | 3.70% | `f6e12c4dc97c91be` |
| 3分钟 | `ready` | 0.9500 | 234 | 41 | 12.20% | `9ec3151e093ea000` |
| 5分钟 | `ready` | 0.9500 | 234 | 48 | 18.75% | `7d4ae2822b788069` |

- 3分钟模型主要正向系数：`gain_pct` +1.7252、`bar_close_location` +0.5058、`return_3m_pct` +0.4689、`support_score` +0.4221。
- 3分钟模型主要负向系数：`minute_of_window` -0.7269、`turnover_acceleration_1m` -0.4550、`session_drawdown_pct` -0.1919、`prior_30m_floor_pct` -0.0275。

## Same-account validation

| 方案 | 信号 | 基线身份精确率 | 3分钟命中率 | 可达召回 | 成交 | 胜率 | 复利 | 回撤 | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 当前触板基线 | 54 | - | - | - | 16 | 68.75% | +22.08% | -4.38% | 3.6244 |
| 仅二进三 | 2 | - | - | - | 2 | 100.00% | +5.09% | -0.02% | - |
| 3分钟提前行动 | 71 | 43.66% | 18.31% | 73.17% | 17 | 47.06% | -5.01% | -10.86% | 1.0536 |
| 3分钟行动-双倍成本 | 71 | 43.66% | 18.31% | 73.17% | 17 | 47.06% | -8.00% | -13.12% | 0.9371 |
| 3分钟行动-保守成交 | 71 | 43.66% | 18.31% | 73.17% | 17 | 47.06% | -5.98% | -11.69% | 1.0187 |

- 验证段行动 71 个；正式基线身份命中 31 个，3分钟内实际触板 13 个。
- 正确触板提前量 P25/中位/P75：1.1667/6.7584/18.0625 分钟；仅剩不到1分钟才可见的正式票 3 个，其中漏掉 1 个。
- 两仓冲突：提前首板因已有仓位未成交 53 个；原因 `{'position_limit': 52, 'duplicate_position': 1}`。

## Decision

- 历史门禁：`FAIL`。
- `baseline_parity`：通过。
- `all_horizon_models_and_thresholds_ready`：通过。
- `minimum_30_validation_actions`：通过。
- `minimum_70pct_formal_precision`：未通过。
- `minimum_30pct_reachable_recall`：通过。
- `positive_normal_account_return`：未通过。
- `positive_double_cost_account_return`：未通过。
- `maximum_drawdown_no_worse_than_10pct`：未通过。
- `d1_win_rate_within_2pct_of_touch_baseline`：未通过。

## Forward overlay

- 状态：`collecting_forward_overlay`；交易日 0，雷达帧 0，可评分观测 0，动作事件 0。
- 尚无可连接的一分钟雷达轨迹；动态概念和资金字段不反向进入历史模型。

## Limitations

- TDX一分钟K线不是Tick/L2，无法验证排队、撤单和秒级成交。
- 历史核心模型不使用缺失的动态概念历史；概念加速度仅进入前向overlay。
- 最后20日已被查看，只能称历史时间验证，不是新的锁定留出。
- 历史通过也只允许影子排序，必须再积累60个交易日或300个闭合动作事件。
