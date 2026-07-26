# 正式打板回测入场价格审计（2026-07-25）

## Current state

这是 A+B 接入前的归档入场口径审计。当前 `limit-up-core-ab-v1` 继承相同执行语义：
首板只在正式双窗口内的首次触板，或10点前触板后的首次可观察回封时形成候选，账面
入场价固定为涨停价；本报告的 239 笔旧基线只用于证明价格口径，不是当前正式分母。

截至 `2026-07-24` 的已核实基线：

| 检查 | 结果 |
|---|---:|
| 首板质量合格候选 | 572 |
| 入场价等于涨停价 | 572 / 572 |
| 正式双窗口候选 | 545 |
| 双窗口内入场价等于涨停价 | 545 / 545 |
| 首次触板触发 | 498 |
| 10点前触板、窗口内回封触发 | 47 |
| 盈利门后正式推荐 | 243 |
| 已闭合独立推荐 | 239 |
| 两仓已成交 | 127 |
| 两仓原始价等于账面成交价 | 127 / 127 |

当前全量推荐为239笔、胜率 `54.8117%`、平均D+1净收益 `+0.5687%`、逐日等权复利
`+101.5433%`、最大回撤 `-30.6303%`。两仓账户为127笔、胜率 `58.2677%`、复利
`+54.7953%`、最大回撤 `-20.6187%`。

## How to verify/run

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_lanes.py \
  tests/alphaagent/test_limit_up_scheduled_execution.py \
  tests/alphaagent/test_limit_up_cash_backtest.py
npm --prefix frontend test -- --run src/pages/LimitUpPage.spec.tsx
```

回归测试锁定：

- `first_touch` 买入时间等于首次触板时间，`entry_price == limit_price`。
- 10点前触板票使用窗口内第一次可观察 `reseal`，仍按涨停价记账。
- 正式订单只读取完整首板/二进三质量候选池，不读取板前观察表。
- 现金滑点不能突破涨停价。
- 页面全量质量读取 `recommendation_quality`，两仓账户读取 `summary`。

## Evidence boundary

本审计证明代码和账面候选代理口径，不证明缺少 Tick/L2 时所有涨停价排队订单真实可成交。
