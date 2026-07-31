# Leader First-Board Backtest

## Boundary

- 状态：研究版本 `leader-first-board-backtest-v1`；``execution_valid`` 恒为 False。
- 本报告只读 `stock_events`/`stock_daily_bars`，不修改 `limit-up-core-abc-v2`、C、实时推荐或账户。
- 每天 5 因子 expanding 校准选 TOP3 首板，涨停价打板买入。
- D+1 起：开盘高开就拿、低开/平盘走；涨停减半留、不涨停收盘走。
- 连板阈值 `>= 3`；max_positions `3`；train 前 3 月。

## Coverage

- 结算范围：`2025-06-27` 至 `2026-07-31`。
- 首板样本：11134；信号数：660；成交笔数：643。
- 输入指纹：`d19f2f713d9d2f6e`。

## Summary

- 初始资金：`100000.0000`；最终权益：`1466647.5034`。
- **总收益（复利）**：`1366.6475%`；**胜率**：`57.0762%`（367/643）。
- 最大回撤：`-35.6121%`；利润因子：`2.3549`；平均收益：`5.0530%`；总费用：`70011.7510`。

## Exit Reason Distribution

- `close_not_limit`：281 笔
- `open_below_prev_close`：212 笔
- `limit_half`：147 笔
- `final_close`：3 笔

## Decision

- 本报告为只读回测证据，不产出可执行信号，不改变正式门或实时推荐。
- 回测假设涨停价成交（偏乐观）、D+1 用开盘价代理竞价；实盘须扣减成交不确定性。
- 13 个月单市场段，复利结果不可外推为普适规律。

## Evidence Boundary

- JSON 含 equity_curve 与全部 closed_trades 明细；Markdown 只显示汇总，避免事后最高被误读为可交易规则。
