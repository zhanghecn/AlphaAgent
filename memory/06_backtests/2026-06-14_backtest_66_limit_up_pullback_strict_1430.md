# Backtest 66 Limit-Up Pullback Strict 14:30

## Current State

- Backtest ID: `66`
- Strategy: `limit_up_after_pullback / 0.1.0`
- Range: `2026-02-02` to `2026-06-13`
- Universe: main board, `max_symbols=80`
- Execution: `strict_1430`, `minute_interval=1m`, `tail_entry_start=14:30`, `tail_entry_end=14:30`
- Initial cash: `1,000,000`
- Final equity: `989,377.8102800001`
- Total return: `-1.0622189719999953%`
- Max drawdown: `-1.9296010580838407%`
- Total trade rows: `2`
- Buy count: `2`
- Sell count: `0`
- Open trade count: `2`

## Execution Quality

`GET /api/backtests/66/report?trade_limit=200`:

- Filled buys: `2`
- Real 14:30 minute buys: `2`
- Real 14:30 ratio: `100.0%`
- Daily close proxy buys: `0`
- Strict 14:30 rejected orders: `30`
- Minute gap rejected orders: `11`
- Tail entry rejected orders: `19`
- Signal events persisted: `42`

Interpretation:

- The 2 filled buy orders use real execution-day `14:30` 1-minute snapshots.
- Filled buys do not use daily close proxy.
- The run is not a complete strict-opportunity sample because 11 strict candidate orders are still missing required `14:30` snapshots.
- Performance is still negative. This strategy is not proven profitable.

## Strategy Comparison

Same parameters, non-persistent strategy comparison:

- `mainline_leader_pullback`: return `-5.081985865099958%`, buy signals `251`, buys `21`, missing 14:30 rejected `0`, tail-entry rejected `83`.
- `breakout_confirmation`: return `0.0%`, buy signals `33`, buys `0`, missing 14:30 rejected `24`, tail-entry rejected `8`.
- `limit_up_after_pullback`: return `-1.0622189719999953%`, buy signals `42`, buys `2`, missing 14:30 rejected `11`, tail-entry rejected `19`.

Interpretation:

- `breakout_confirmation` showing `0.0%` is not proof of better performance; it had no fills and many missing 14:30 snapshots.
- `limit_up_after_pullback` catches additional strong-stock pullback signals, but in this sample it still loses money and has incomplete minute coverage.
- `mainline_leader_pullback` remains the only complete strict sample among these three for this specific universe, and it is negative.

## 金安国纪复核

`GET /api/quant/symbols/002636.SZSE/strategy-comparison?start=2026-02-02&end=2026-06-13&limit=80`:

- Name: `金安国纪`
- Low-pullback strategy: `entry_signal_count=16`, best entry fit `2026-02-09`, score `84.4645`.
- Breakout strategy: `entry_signal_count=9`, best entry fit `2026-06-05`, score `79.5694`.
- Limit-up pullback strategy: `entry_signal_count=17`, best entry fit `2026-04-30`, score `85.8275`.

`GET /api/backtests/66/signal-events?vt_symbol=002636.SZSE&limit=20`:

- Status: `empty`
- Returned count: `0`

`GET /api/quant/symbols/002636.SZSE/diagnostics?start=2026-02-02&end=2026-06-13&backtest_id=66&signal_date=2026-04-30&limit=80`:

- Summary status: `entry_signal_not_traded`
- Main reason: `not_selected`
- Main reason label: `未入选`
- Main reason detail: `该股票在这个信号日没有进入当前回测策略的候选或信号计划。`
- Signal-day cash: `1,000,000`
- Signal-day market value: `0`
- Signal-day total equity: `1,000,000`
- Signal-day position count: `0`

Interpretation:

- 金安国纪 is not "筛不出"; all three registered strategies have historical BUY signals in the selected range.
- In backtest `#66`, 金安国纪 did not enter the persisted portfolio signal plan. This points to universe/sample selection, ranking, daily portfolio competition, strategy parameters, or date-specific plan generation, not to missing single-stock signal recognition.

## Code Fixes Verified By This Run

- `limit_up_after_pullback` is registered in `/api/quant/strategies`.
- Persisted backtest strategy version now uses the registered strategy version; `#66` stores `limit_up_after_pullback / 0.1.0`.
- Backtest metrics now expose `total_trade_rows`, `buy_count`, `sell_count`, and `open_trade_count`, so an open-position run no longer looks like "0 trades" only because it has no closed sells.
- `not_selected` is mapped to the Chinese reason label `未入选`.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `151 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api`: passed
- `pnpm --dir frontend run build`: passed, Vite chunk-size warning only
- `docker compose up --build -d alphaagent-api alphaagent-web`: API healthy, web running
- Real API:
  - `/api/quant/strategies` returns `mainline_leader_pullback`, `breakout_confirmation`, `limit_up_after_pullback`.
  - `/api/backtests/66/report?trade_limit=200` returns the metrics and execution quality above.
  - `/api/backtests/66/signal-events?limit=5` returns ready signal-plan rows.
  - `/api/quant/symbols/002636.SZSE/diagnostics?...backtest_id=66&signal_date=2026-04-30` returns `未入选`.
- Real browser, Chromium headless no-sandbox:
  - `/quant -> 回测`: strategy comparison and `买入/卖出/持仓中` summary visible.
  - `/stocks/002636.SZSE`: `金安国纪`, `量化信号复核`, and `涨停后回踩确认` visible.
  - Console errors: `0`
  - Failed requests: `0`

Screenshots:

- `/tmp/alphaagent-real-browser/quant_backtest_metrics_strategy_final.png`
- `/tmp/alphaagent-real-browser/stock_002636_limit_up_final.png`

## Open Risks

- The limit-up pullback strategy still has negative return in this short strict run.
- It has 11 missing 14:30 snapshot rejections, so strict opportunity coverage is incomplete.
- This is not a multi-year all-A walk-forward result. Overfitting, parameter sensitivity, market-regime dependence, and benchmark excess return remain unresolved.
