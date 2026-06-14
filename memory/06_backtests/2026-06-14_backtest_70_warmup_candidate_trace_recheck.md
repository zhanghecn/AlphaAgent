# Backtest 70 Warmup Candidate Trace Recheck

## Current State

- Source baseline: `#62`
- New strict run after warmup fix: `#70`
- Strategy: `mainline_leader_pullback / 0.1.1`
- Range: `2026-02-02` to `2026-06-13`
- Universe: main board, `max_symbols=80`
- Execution: `strict_1430`, `minute_interval=1m`, `14:30`
- Final equity: `949,180.1413490004`
- Total return: `-5.081985865099958%`
- Max drawdown: `-9.57783253422486%`

## Why This Run Exists

`#62` loaded daily bars only from the user-selected start date when it was created, so early signal dates did not have enough pre-start bars for MA60 and 60-day drawdown factors. The code now loads a pre-start warmup window while still recording equity and trades only from the requested start date.

## 金安国纪 002636.SZSE

`GET /api/backtests/70/candidate-trace?vt_symbol=002636.SZSE&signal_date=2026-02-09`:

- Status: `rejected`
- Candidate action/rank/score: `BUY`, rank `2`, score `84.4645`
- Planned execute date: `2026-02-10`
- Linked order status/reason: `rejected`, `missing_1430_snapshot`
- Interpretation: after the warmup fix, 金安国纪 does enter the theoretical buy plan for `2026-02-09`; it is not bought because the strict execution day lacks the `2026-02-10 14:30` 1-minute snapshot.

`GET /api/backtests/62/candidate-trace?vt_symbol=002636.SZSE&signal_date=2026-02-09` remains useful as an old-run diagnostic:

- Status: `candidate_not_planned`
- `not_planned_context.likely_reason`: `before_first_signal_date`
- First persisted signal date in `#62`: `2026-05-08`
- Interpretation: old `#62` has a signal-detail warmup gap for this early signal date.

## Data Quality

`GET /api/backtests/70/minute-coverage`:

- Status: `missing_snapshots`
- Buy count: `21`
- Real 14:30 minute buys: `21`
- Daily close proxy buys: `0`
- Strict rejected orders: `483`
- Missing snapshot rejected orders: `400`
- Tail-entry rejected orders: `83`

Interpretation:

- Filled buys are still real `14:30` snapshots.
- The old early-period signal gap is fixed.
- `#70` is not a complete strict baseline because many early strict orders still lack 14:30 snapshots. Use `#62` as the current complete `max_symbols=80` strict baseline until `#70` gaps are filled and rerun.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `158 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api`: passed
- `pnpm --dir frontend run build`: passed, Vite chunk-size warning only
- `docker compose up -d --build alphaagent-api alphaagent-web`: API healthy, web running
- API checks:
  - `GET /api/backtests/62/candidate-trace?vt_symbol=002636.SZSE&signal_date=2026-02-09`
  - `GET /api/backtests/70/candidate-trace?vt_symbol=002636.SZSE&signal_date=2026-02-09`
  - `GET /api/backtests/70/minute-coverage`
  - `GET /api/backtests/70/validation-grid?max_variants=54`
- Real browser checks:
  - `/quant` candidate and backtest tabs render.
  - `/stocks/002636.SZSE`组合回测复核 with `#70 / 2026-02-09` shows `缺14:30快照`.
  - `/stocks/002636.SZSE`组合回测复核 with `#62 / 2026-02-09` shows `未进计划核查` and `2026-05-08`.
  - Screenshots: `/tmp/alphaagent-real-browser/stock_002636_backtest70_verified.png`, `/tmp/alphaagent-real-browser/stock_002636_backtest62_verified.png`.
