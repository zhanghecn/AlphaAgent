# Backtest 62 Validation Grid Recheck

## Current State

- Backtest: `#62`
- Strategy: `mainline_leader_pullback / 0.1.1`
- Execution: `strict_1430 / 1m / 14:30`
- Grid endpoint: `GET /api/backtests/62/validation-grid?max_variants=54`
- Grid status: `ready`
- Variant count: `54`

## Parameter Sensitivity

- Positive variants: `0`
- Positive ratio: `0.0%`
- Out-of-sample positive variants: `0`
- Out-of-sample positive ratio: `0.0%`
- Sample-equal-weight excess positive variants: `0`
- Sample-equal-weight excess positive ratio: `0.0%`
- High-friction positive variants: `0`
- High-friction positive ratio: `0.0%`
- Base variant id: `27`
- Base total return: `-5.081985865099958%`
- Base out-of-sample return: `-5.081985865099958%`
- Base total rank: `44/54`
- Base out-of-sample rank: `44/54`
- Best total variant id: `8`
- Best out-of-sample variant id: `8`

Interpretation:

- The 54-variant grid did not find a single positive-return parameter combination in this strict sample.
- The current base parameters ranked `44/54`, so the default parameters are not robust within this grid.
- This directly contradicts any claim that the current low-pullback strategy is already profitable or anti-overfit.

## Diagnostics

- `grid_positive_ratio`: `warning`, value `0.0`; 盈利依赖少数组合，参数敏感性偏高。
- `grid_out_sample_positive_ratio`: `fail`, value `0.0`; 样本外稳定性不足，不能认为策略已抗过拟合。
- `grid_sample_excess_ratio`: `fail`, value `0.0`; 多数参数未跑赢样本等权，选股优势仍不足。
- `grid_high_friction_ratio`: `warning`, value `0.0`; 交易成本压力下收益容易被吃掉。
- `base_out_sample_rank`: `warning`, value `44`; 当前参数不是样本外最稳组合，需谨慎使用默认值。

## Walk Forward

- Status: `ready`
- Fold count: `1`
- Positive test ratio: `0.0%`
- Excess positive ratio: `0.0%`
- Test return average: `-4.737121623289964%`
- Test excess average: `-22.078588394485735%`
- Most selected variant id: `1`

Walk-forward diagnostics:

- `walk_forward_fold_count`: `warning`, value `1`; 折叠数量不足，只能作烟测。
- `walk_forward_positive_ratio`: `fail`, value `0.0`; 未来测试窗口盈利稳定性不足。
- `walk_forward_excess_ratio`: `fail`, value `0.0`; 多数未来测试窗口未跑赢样本等权。
- `walk_forward_avg_excess`: `fail`, value `-22.078588394485735`; 未来测试窗口平均超额为负。

Interpretation:

- Only one fold was available in the current short sample, so walk-forward is a smoke check rather than a full market-cycle proof.
- That one future test window was negative and underperformed sample equal-weight by about `22.08%`.

## Reality Conclusion

- Execution realism for `#62` is strong for filled buys: 21/21 buys use real execution-day 14:30 1-minute snapshots, with zero close proxy and zero missing-snapshot rejection.
- Strategy robustness is weak: strict execution, parameter grid, out-of-sample split, high-friction stress, and walk-forward all fail to support profitability.
- Next work should focus on strategy design/thresholds and broader multi-year all-A validation, not on claiming the current strategy is ready.

## Verification

- `GET /api/backtests/62/validation-grid?max_variants=54`: `status=ready`, `variant_count=54`.
