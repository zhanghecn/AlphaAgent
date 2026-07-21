# 首板逐笔资金流提前触发 v4 研究

## Current state

- 状态：`ready_historical_rejected`；结论：`historical_rejected_no_live_promotion`。
- 研究版本：`limit-up-preboard-transaction-trigger-v4`；正式策略修改：`False`。
- 逐笔覆盖：股票日 962/962；分钟前缀 22804/22821。

## Same-account validation

- 覆盖门失败后按 fail-closed 合同停止；v3/v4 模型和账户均未运行。

## Validation blocks

| 块 | 日期 | 行动 | 成交 | 胜率 | 复利 | 回撤 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |

## Incremental attribution


## Decision

- 历史门禁：`FAIL`。
- `transaction_scope_coverage_100pct`：通过。
- `transaction_prefix_coverage_100pct`：未通过。
- `historical_model_evaluation_completed`：未通过。

## Forward validation

- 状态：`not_started_historical_rejected`；交易日 0，闭合行动 0。

## Limitations

- v4要求逐笔分钟前缀100%可评分；覆盖门失败后未拟合、校准或查看验证收益。
- 正式limit-up-scheduled-v9、limit-up-live-v15、公开排序和自动动作未改变。
