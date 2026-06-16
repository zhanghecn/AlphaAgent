# Backtest Evidence Index

这个目录保存回测报告、缺口清单、参数网格和验证证据。目录中的日期文件是证据，不是长期状态；判断当前状态时先读本文件，再按链接打开具体报告。

## Current Baselines

| Backtest | Purpose | Status | Key Result |
| --- | --- | --- | --- |
| `#118` | 当前日线 D+1 全历史组合回测页面基线 | 已由后台研究任务生成并通过 API 验证 | `mainline_dragon_pullback`，2025-03-26 至 2026-06-15，收益约 `+66.78%`，最大回撤约 `-30.22%`，买入/卖出/持仓中 `201 / 193 / 8` |
| `#116` | 上一版同参数全历史组合回测 | 已被 `#118` 取代，仅作重复验证对照 | `mainline_dragon_pullback`，2025-03-26 至 2026-06-15，收益约 `+66.78%`，最大回撤约 `-30.22%`，买入/卖出/持仓中 `201 / 193 / 8` |
| `#112` | 旧日线 D+1 组合回测页面基线 | 已被 `#116` 取代，仅作历史对照 | `mainline_dragon_pullback`，2025-10-14 至 2026-02-04，收益约 `+11.62%`，最大回撤约 `-15.81%`，买入/卖出/持仓中 `99 / 89 / 10` |
| `#62` | 旧严格 14:30 低吸基线 | 历史分钟模型证据，不再是默认操作口径 | 收益约 `-5.08%`，21/21 买入是真实 14:30，无收盘代理，无缺快照拒单 |
| `#70` | 预热窗口修复后的候选追踪复核 | 诊断用，不替代 `#62` | 金安国纪早期理论计划恢复，但大量早期订单缺 14:30 快照 |
| `#66` | 涨停后回踩策略严格样本 | 策略链路可用，收益和覆盖不达标 | 收益约 `-1.06%`，2 笔真实 14:30 买入，仍有缺快照拒单 |
| `#42` | 长区间严格尾盘覆盖对照 | 历史覆盖问题证据 | 严格成交极少，说明长区间分钟覆盖不足 |
| `#9/#10/#12` | 旧执行模型和早期分钟补数排查 | 历史材料 | 受 `0.1.0` 卖出时序或分钟覆盖限制，不作为当前绩效结论 |

## Current Evidence Files

- `2026-06-14_backtest_62_strict_1430_recheck.md`: 当前严格基线、14:30 覆盖、金安国纪复核、真实浏览器验证。
- `2026-06-14_backtest_62_validation_grid_recheck.md`: `#62` 参数网格、walk-forward 和反过拟合复核。
- `2026-06-14_backtest_70_warmup_candidate_trace_recheck.md`: 预热窗口修复和金安国纪 `2026-02-09` 候选到拒单链路。
- `2026-06-14_backtest_66_limit_up_pullback_strict_1430.md`: 涨停后回踩策略严格 14:30 复核。
- `2026-06-16_dragon_pullback_v0_1_0_validation.md`: `mainline_dragon_pullback / 0.1.0` 第一版优化策略验证，含六股关键日期、组合回测和单股对比。
- `2026-06-16_daily_next_open_workflow.md`: 当前日线 D+1 主流程、`/quant` 页面级验证和回测 `#112` 证据。
- `2026-06-16_full_history_dragon_pullback_refresh.md`: 候选补齐到本地最新 `2026-06-15`、买卖记录 `#3` 和全历史组合回测 `#116` 的当前证据。
- `2026-06-12_backtest_engine_audit.md`: `0.1.1` 卖出撮合时序修复证据。
- `2026-06-12_quant_issue_audit.md`: 用户反馈的量化问题审计。
- `alphaagent_minute_gap_backtest_42_2025-10-14_2026-06-12.csv`: 长区间严格 14:30 缺口样本。

## How To Recheck

常用 API：

- `GET /api/backtests/{id}/minute-coverage`
- `GET /api/backtests/{id}/data-quality`
- `GET /api/backtests/{id}/daily-decisions`
- `GET /api/backtests/{id}/trade-attribution`
- `GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=`
- `GET /api/backtests/{id}/validation-grid`

常用命令：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
pnpm --dir frontend run build
```

## Reading Rules

- 先看回测的 `strategy_version` 和执行模型。当前默认历史研究口径是 `legacy_next_open`；`strategy_version < 0.1.1` 的收益不作为当前结论。
- 普通产品路径只看公开策略 `mainline_dragon_pullback`；旧策略只作为内部兼容/对比材料。
- 历史主流程看 `legacy_next_open` 的买入/卖出路径、收益率、最大回撤、候选排名、持仓上限、现金/仓位拒单和涨跌停约束。
- `/quant` 页面验证必须同时检查候选 tab 和回测 tab；不能只用 API 冒烟或前端 build 代替页面级验证。2026-06-16 已用 Playwright `chromiumSandbox=false` 复核：`/quant` 只有 1 个真正的“运行策略研究”按钮，日期提示说明研究截止到本地日线库最新交易日 `2026-06-15`；`/stocks/603629.SSE` 优先展示组合回测 `#118` 的同一口径，闭合 1 笔、收益 `+230.69%`、K 线标记 3 个。最新 API 验证：研究任务补生成 `133` 个交易日、跳过 `163` 个已有交易日，生成买卖记录 `#5` 和组合回测 `#118`。
- 旧严格分钟报告才需要同时看 `minute_1430_count`、`daily_close_proxy_count`、`missing_1430_snapshot` 和 `tail_entry_not_triggered`。
- `0%` 收益不一定好。无成交或缺快照导致的 `0%` 不能解释为策略有效。
- 单股有 BUY 信号不等于组合会买入，还要看排名、资金、持仓上限、执行日开盘价、涨跌停和订单拒单原因。

## Open Risks

- 当前策略仍需按日线 D+1 新主流程重做多年全 A、walk-forward、参数敏感性、市场分层、基准超额和高摩擦验证。
- 当前全历史 `#116` 虽然收益提升到 `+66.78%`，最大回撤也扩大到 `-30.22%`；不能直接宣称策略稳定盈利。
- 金安国纪等强势股能被策略识别出历史信号，但组合是否买入取决于当日组合竞争和严格执行约束。
- 长区间历史 14:30 快照覆盖仍不完整；这只影响旧严格分钟报告或未来盘中确认，不再阻塞历史日线策略研究。
