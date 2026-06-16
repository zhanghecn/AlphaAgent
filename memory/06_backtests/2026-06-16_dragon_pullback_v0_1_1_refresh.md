# Dragon Pullback 0.1.1 Refresh

## Current State

- Strategy: `mainline_dragon_pullback / 0.1.1`.
- Research job: `bdb5ab71823c49a7a43878ef70d75047`.
- Candidate range: `2025-03-26` to `2026-06-16`.
- Signal runs: `297` trading dates processed, latest run `#2267` on `2026-06-16`.
- Replay run: `strategy_replay_runs #7`, `2025-03-26` to `2026-06-16`.
- Portfolio backtest: `backtests #120`, `2025-03-26` to `2026-06-16`, `legacy_next_open`.

## Key Metrics

- Total return: `+44.45%`.
- Annual return: `+36.62%`.
- Max drawdown: `-29.61%`.
- Buy / sell / open: `199 / 189 / 10`.
- Win rate: `23.81%`.
- Profit factor: `1.31`.

## 603629.SSE Check

- Persisted `0.1.1` BUY signals in the inspected window:
  - `2026-01-19`
  - `2026-03-09`
  - `2026-03-18`
- `2026-01-20` and `2026-03-10` are no longer BUY; both carry `repeat_tail_buy_setup`.
- `/stocks/603629.SSE` now reads portfolio backtest `#120` and overlays same-backtest theoretical signal events on the K-line, so `2026-03-09` appears as a signal even though it is not the latest actual portfolio trade marker.

## Verification

- API:
  - `GET /api/quant/strategies` returns `mainline_dragon_pullback / 0.1.1`.
  - `GET /api/quant/trading-dates?limit=5` returns latest local date `2026-06-16`.
  - `GET /api/quant/screen-runs?limit=5&strategy=mainline_dragon_pullback` returns `0.1.1` runs through `2026-06-16`.
  - `GET /api/backtests?limit=5&run_type=portfolio&strategy=mainline_dragon_pullback` returns `#120` as the latest portfolio run.
- Browser:
  - `/quant` candidate tab shows `2026-06-16`, strategy version `0.1.1`, and only the single `刷新候选并回测` main action.
  - `/quant` backtest tab shows `#120`, readonly current method, and then the report after the slower report API returns.
  - `/stocks/603629.SSE` shows `#120`, K-line marker count `9`, including `2026-01-19 信号`, `2026-03-09 信号`, actual `2026-05-22 买`, and `2026-06-09 卖`.
- Tests:
  - `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `189 passed`.
  - `pnpm --dir frontend build`: passed.
  - `git diff --check`: passed.

## Known Risk

- `stock_daily_bars` has `2026-06-16`, but local bars for that date cover `1302` symbols, below normal full-market coverage. The strategy date is current, but same-day candidate coverage reflects available local data.
- `#120` is an improved operational baseline, not proof of stable profitability; it still needs broader walk-forward, friction, market-regime, and data-completeness validation.
