# Backtest 59 Strict 14:30 Recheck

Current state:

- Backtest ID: `#59`
- Strategy: `mainline_leader_pullback / 0.1.1`
- Date range: `2026-02-02` to `2026-06-13`; local trading data ends at `2026-06-12`.
- Universe: local main-board sample, `max_symbols=80`, `candidate_limit=20`, `max_positions=8`.
- Execution model: `strict_1430`, `1m`, `14:30-14:30`.
- Signal timing: D-day close-visible signal, next trading day 14:30 execution. This rerun uses the fixed sell timing; old `#58` should not be used as the current performance result.

Result:

- Final equity: `990,530.15`
- Total return: `-0.9470%`
- Annual return: `-2.7815%`
- Max drawdown: `-5.3325%`
- Closed trades: `16`
- Win rate: `25.00%`
- Profit factor: `0.8238`
- Sharpe: `-0.1120`

Execution coverage:

- Filled buys: `20`
- Filled buys using real 14:30 minute snapshot: `20 / 20`, `100.00%`
- Daily close proxy buys: `0`
- Strict 14:30 rejected orders: `79`
- Minute-snapshot gap rejections: `12`
- Tail-entry condition rejections: `67`
- Tail-exit condition or snapshot rejections: `12`

Benchmark and robustness:

- Local sample equal-weight benchmark return: `-1.2662%`
- Excess vs local sample equal-weight: `+0.3192%`
- Random sample baseline average return: `+0.5088%`; strategy did not beat this average.
- High-friction stress return: `-2.2863%`.

Interpretation:

- This is the current strict 14:30 rerun after fixing the sell timing future-function risk. It is much less negative than old `#58` because sells are no longer allowed to use the same execution day full daily bar and sell at that day's 14:30.
- The filled buy side is fully backed by real 14:30 minute snapshots and does not use close proxy.
- The path is still not fully complete because 12 strict rejected orders are caused by missing 14:30 snapshots. The next data task is to use the stock minute sync job with `mode=backtest_gaps` and `backtest_id=59`, then rerun.

Gold An Guo Ji / 金安国纪 `002636.SZSE` check:

- `mainline_leader_pullback` signal history from `2025-01-01` to `2026-06-13` has `entry_signal_count=26`.
- `breakout_confirmation` signal history over the same range has `entry_signal_count=18`.
- In `#59`, examples:
  - Signal date `2026-05-20`, execute date `2026-05-21`: theoretical low-pullback signal exists, but 14:30 price was outside the allowed MA5 tail-entry band, so no order/trade.
  - Signal date `2026-06-03`, execute date `2026-06-04`: theoretical signal exists, but the execution day 14:30 snapshot is missing in the strict model, so no order/trade.

Verification:

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `126 passed, 1 warning`.
- `pnpm --dir frontend run build`: passed, Vite chunk-size warning only.
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api`: passed.
- `docker compose up -d --build alphaagent-api alphaagent-web`: API and web healthy.
- API checks:
  - `GET /api/backtests/59/minute-coverage`
  - `GET /api/backtests/59/report?trade_limit=3`
  - `GET /api/backtests/59/candidate-trace?vt_symbol=002636.SZSE&signal_date=2026-05-20`
  - `GET /api/backtests/59/candidate-trace?vt_symbol=002636.SZSE&signal_date=2026-06-03`
- Browser checks:
  - `/quant` shows backtest `#59`, the new `14:30覆盖` panel, missing snapshot status, and no failed network requests.
  - `http://localhost:5173/quant` and `http://127.0.0.1:5173/quant` both work.
  - `/stocks/002636.SZSE` loads Gold Anki / 金安国纪 and quant strategy content.
- Screenshots:
  - `/tmp/alphaagent-quant-minute-coverage-59.png`
  - `/tmp/alphaagent-stock-002636-current.png`
