# Backtest Evidence Index

这个目录保存回测报告、缺口清单、参数网格和验证证据。目录中的日期文件是证据，不是长期状态；判断当前状态时先读本文件，再按链接打开具体报告。

## Current Baselines

| Backtest | Purpose | Status | Key Result |
| --- | --- | --- | --- |
| `#62` | 当前严格 14:30 低吸基线 | 可作为 `max_symbols=80` 样本的主要复核对象 | 收益约 `-5.08%`，21/21 买入是真实 14:30，无收盘代理，无缺快照拒单 |
| `#70` | 预热窗口修复后的候选追踪复核 | 诊断用，不替代 `#62` | 金安国纪早期理论计划恢复，但大量早期订单缺 14:30 快照 |
| `#66` | 涨停后回踩策略严格样本 | 策略链路可用，收益和覆盖不达标 | 收益约 `-1.06%`，2 笔真实 14:30 买入，仍有缺快照拒单 |
| `#42` | 长区间严格尾盘覆盖对照 | 历史覆盖问题证据 | 严格成交极少，说明长区间分钟覆盖不足 |
| `#9/#10/#12` | 旧执行模型和早期分钟补数排查 | 历史材料 | 受 `0.1.0` 卖出时序或分钟覆盖限制，不作为当前绩效结论 |

## Current Evidence Files

- `2026-06-14_backtest_62_strict_1430_recheck.md`: 当前严格基线、14:30 覆盖、金安国纪复核、真实浏览器验证。
- `2026-06-14_backtest_62_validation_grid_recheck.md`: `#62` 参数网格、walk-forward 和反过拟合复核。
- `2026-06-14_backtest_70_warmup_candidate_trace_recheck.md`: 预热窗口修复和金安国纪 `2026-02-09` 候选到拒单链路。
- `2026-06-14_backtest_66_limit_up_pullback_strict_1430.md`: 涨停后回踩策略严格 14:30 复核。
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

- 先看回测的 `strategy_version` 和执行模型。`strategy_version < 0.1.1` 的收益不作为当前结论。
- 严格回测必须同时看 `minute_1430_count`、`daily_close_proxy_count`、`missing_1430_snapshot` 和 `tail_entry_not_triggered`。
- `0%` 收益不一定好。无成交或缺快照导致的 `0%` 不能解释为策略有效。
- 单股有 BUY 信号不等于组合会买入，还要看排名、资金、持仓上限、执行日快照、尾盘条件和订单拒单原因。

## Open Risks

- 当前严格基线收益为负，策略仍需重做多年全 A、walk-forward、参数敏感性、市场分层、基准超额和高摩擦验证。
- 金安国纪等强势股能被策略识别出历史信号，但组合是否买入取决于当日组合竞争和严格执行约束。
- 长区间历史 14:30 快照覆盖仍不完整，必须按缺口补齐后再解释完整严格收益。
