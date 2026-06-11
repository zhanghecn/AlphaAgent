# 2026-06-11 Quant MVP Backtest

## Context

- Strategy: `mainline_leader_pullback`
- Version: `0.1.0`
- Backtest IDs: `1`, `2`, `3`
- Data source: local PostgreSQL `stock_daily_bars`
- Backtest `1`/`2` sample: 20 symbols, 2400 daily bars, 2025-12-05 to 2026-06-08, 120 equity days.
- Backtest `3` sample: 120 symbols, 18,008 in-range daily bars, 2025-10-14 to 2026-06-11, 161 equity days.
- Execution model: D close signal, D+1 open simulated fill
- This is a daily-bar simulation, not a minute-level tail-session entry validation.

## Parameters

- Initial cash: 1,000,000
- Max symbols: 20 for backtest `1`/`2`; 120 for backtest `3`
- Max positions: 8
- Max position pct: 12.5%
- Commission: 0.03%
- Stamp tax: 0.05%
- Slippage: 10 bps
- Stop loss: 7%
- Take profit: 18%
- Trailing stop: 8%
- Time stop: 15 trading days approximation
- Min entry score: 68
- Strict entry: true

## Metrics

### Backtest 3

- Initial cash: 1,000,000
- Final equity: 1,340,134.971836903
- Total return: 34.01349718369029%
- Annual return: 58.130304417871685%
- Max drawdown: -10.12822078500223%
- Closed trades: 119
- Win rate: 0.5798319327731093
- Profit factor: 2.342646981081279
- Average win: 8,875.479296150736
- Average loss: -5,228.342779599988
- Sharpe: 2.733971699184399
- Total trade rows: 243
- Orders: 249 total, 243 filled, 6 rejected
- Average holding days: 6.2100840336134455
- Median holding days: 5
- Estimated turnover: 2783.6194407%
- Average exposure: 31.13443836486215%
- Max positions: 8
- Sample coverage: 120 of 463 local stocks, 25.917926565874733%
- Sample equal-weight benchmark return: 77.76845921227711%
- Excess return vs sample equal-weight benchmark: -43.75496202858682%
- 60/40 time split: in-sample excess -15.127664777730642%, out-of-sample excess -20.21223573597142%.

### Backtest 1/2

- Final equity: 1,063,272.4069739003
- Total return: 6.327240697390035%
- Annual return: 13.750559537035656%
- Max drawdown: -1.3770780020216145%
- Closed trades: 10
- Win rate: 0.6
- Profit factor: 4.10191552336235
- Average win: 13,728.275193333342
- Average loss: -5,020.194265999989
- Sharpe: 2.3393242927847915

## Persistence

- Latest checked `backtest_id`: `3`
- `backtest_orders`: 26 rows per persisted strict run
- `backtest_trades`: 21 rows per persisted strict run
- `backtest_daily_equity`: 120 rows per persisted strict run
- `backtest_metrics`: 11 rows per persisted strict run
- `backtest_id=3`: 249 orders, 243 trades, 161 equity rows.

## Expanded Report Verification

- `/api/backtests/3/report` returns sample coverage, `extended_metrics`, `benchmark`, `period_analysis`, `monthly_returns`, `symbol_performance`, `worst_trades`, `order_stats`, `equity_tail`, and `data_quality`.
- Persistent expanded report table: `memory/06_backtests/2026-06-11_backtest_3_expanded_report.md`.
- Page `/quant` renders those sections: 基准对比、样本内/样本外、月度收益、个股贡献、最差交易、成交约束、数据质量和限制.
- Playwright screenshots: `/tmp/alphaagent-quant-expanded-report.png`, `/tmp/alphaagent-quant-benchmark-report.png`.
- 2026-06-11 verification: `uv run pytest tests/alphaagent -q` -> 123 passed, 1 warning; `npm run build` -> passed with Vite chunk size warning only.

## Quant / Simulation Verification

- Latest strict current-day screen on 2026-06-08 produced 3 `WATCH` candidates and 0 `BUY` candidates.
- Quant candidate group contained 3 synced items after screening.
- Historical screen on 2026-05-29 produced one `BUY` candidate: `300502.SZSE`.
- Auto simulation buy filled one order into account `量化模拟账户`: `300502.SZSE`, 100 shares, cost price 725.00.
- `/api/backtests/3/report` returned sample, metrics, expanded report sections, and trades for frontend rendering.

## Limitations

- Current expanded dataset covers 120 of 463 local stocks, not full A-share universe.
- Strategy return is positive but underperforms the local sample equal-weight benchmark in backtest `3`.
- `sector_period_scores` is empty, so sector mainline scoring falls back to neutral.
- No minute data; the MA5 pullback entry is daily close proxy plus next-open execution.
- No fund-flow, hot-rank, or LHB data yet; "probe" and "washout" are price-volume proxies only.
- Financial reports are used only when `publish_date <= trade_date`.
