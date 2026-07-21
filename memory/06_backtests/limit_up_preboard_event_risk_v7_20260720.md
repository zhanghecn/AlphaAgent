# 首板事件竞争风险 v7 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 研究版本：`limit-up-preboard-event-risk-v7`；正式策略修改：`False`。
- 逐笔覆盖：股票日 962/962；分钟前缀 22804/22821。

## Deterministic rerun

- 三次 89 日完整回放除 `performance` 耗时外整份 JSON 逐字段一致；总耗时分别为
  1601.870 秒、652.963 秒和 654.897 秒。最后一次使用补齐证据元数据后的最终代码。
- validation/oracle 隔离回归证明，改动验证段未来标签不会改变 fit 模型指纹、校准阈值
  或动作身份；相关 v4-v7 回归、`compileall` 与 `git diff --check` 均通过。

## Event-risk models

- 市场三分钟事件模型：`ready`，训练分钟 2689，指纹 `sha256:bdb3960776fd0aabe9a29886ec1f02bd646ce7f6cd6d925cfa003ab7e47768a2`。
- 候选 LambdaRank：`ready`，混合风险集 41，指纹 `sha256:6e78dae9a67291576d3889995c64ff2e26ae73a7c2d4d3bdc9a0267257a7fc4a`。
- 校准状态：`calibration_precision_gate_failed`；冻结市场概率阈值 `None`。
- 至少 10 次选择时，最好为阈值 0.25 的 `4/10=40.00%`，要求 70.00%。
- 验证事件分钟 Top1 命中：81.76%；原 rank Top1：50.00%。
- 验证段提前首板成交 0 笔；联合账户复利 +9.27% 来自未改动二进三，不能解释为 v7 收益。

## Same-account validation

| 方案 | 信号 | 原账户身份精度 | 原账户召回 | 成交 | 胜率 | 复利 | 回撤 | PF |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| v3分钟模型 | 34 | 30.43% | 33.33% | 25 | 44.00% | -16.84% | -26.25% | 0.6451 |
| v7事件竞争风险 | 0 | - | 0.00% | 3 | 100.00% | +9.27% | -0.67% | - |

## Validation blocks

| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 2026-06-04..2026-06-11 | 0 | 1 | 100.00% | +4.02% | -0.67% |
| 2 | 2026-06-12..2026-06-22 | 0 | 0 | - | +0.00% | +0.00% |
| 3 | 2026-06-23..2026-06-30 | 0 | 2 | 100.00% | +5.09% | -0.02% |
| 4 | 2026-07-01..2026-07-08 | 0 | 0 | - | +0.00% | +0.00% |
| 5 | 2026-07-09..2026-07-16 | 0 | 0 | - | +0.00% | +0.00% |

## Incremental attribution

- `v3_false_momentum_removed_by_v7`：26 个股票日。
- `v3_original_account_identity_retained`：0 个股票日。
- `v3_original_account_identity_killed_by_v7`：8 个股票日。
- `v7_new_original_account_identity`：0 个股票日。
- `v7_new_false_positive`：0 个股票日。

## Causal no-action attribution

- 全样本 17 个分钟、14 个股票日；验证段 7 个分钟、6 个股票日。
- 验证段与正式候选身份交集 1；与原两仓实际成交身份交集 1。

## Interpretation

- v7 动态跟踪正式质量门内所有涨幅 `>=3%` 且尚未首次触板的股票，不是在 3% 时直接买入。
- LambdaRank 的 `81.76%` 是“已知该分钟确有股票即将触板”后的条件 Top1 命中，证明
  “同刻买谁”有明显增量；它不能回答实时未知的“现在是否该买”。
- 市场模型虽有验证 AUC `0.8305`，但按时间顺序执行时无法在足够样本上达到 70% 精度。
  当前未解决的是第一次动作时点；没有可靠提前买入方案。
- ranker 主要依赖涨幅相对强度、涨幅、support 和短时收益；逐笔大单份额、成交加速度等
  多数资金代理增益为 0。现有分钟逐笔不能替代秒级成交方向、委托队列和撤单数据。

## Point-in-time context boundary

- 概念快照 4 日，板块资金快照 6 日，3%雷达有效观察 2 日。
- 这些覆盖不足的数据不得进入 v7 历史模型、阈值或验收，只允许冻结后作为新前向扩展层。

## Decision

- 历史门禁：`FAIL`。
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
- 历史概念强度、板块资金和雷达观察覆盖不足，明确排除在v7模型、阈值和验收之外。
- v7历史段已经被此前研究查看；即使历史通过，也只能冻结后累计新的60日只读前向证据。
