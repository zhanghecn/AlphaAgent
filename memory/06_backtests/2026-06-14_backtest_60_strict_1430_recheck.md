# Backtest 60 Strict 14:30 Recheck

## Current State

- Backtest ID: `60`
- Strategy: `mainline_leader_pullback / 0.1.1`
- Range: `2026-02-02` to `2026-06-13`
- Universe: main board, `max_symbols=80`
- Execution: `strict_1430`, `minute_interval=1m`, `tail_entry_start=14:30`, `tail_entry_end=14:30`
- Initial cash: `1,000,000`
- Final equity: `964,963.6923986003`
- Total return: `-3.503630760139975%`
- Max drawdown: `-8.025032175277492%`
- Closed trade count: `18`
- Win rate: `33.33333333333333%`

## Execution Quality

`GET /api/backtests/60/minute-coverage`:

- Status: `missing_snapshots`
- Buy count: `21`
- Real 14:30 minute buys: `21`
- Real 14:30 ratio: `100.0%`
- Daily close proxy buys: `0`
- Strict 14:30 rejected orders: `83`
- Minute gap rejected orders: `5`
- Tail entry rejected orders: `78`
- Tail exit rejected orders: `5`

Interpretation:

- Filled buys can be read as real execution-day `14:30` 1-minute snapshots.
- There is no daily-close proxy in filled buys.
- The run is still not a complete strict-real backtest because 5 strict orders are missing required `14:30` snapshots.

## Gap Audit

`POST /api/data-sync/imports/minute-bars/audit-gaps` with `{"backtest_id":60,"tail_entry_start":"14:30","tail_entry_end":"14:30"}`:

- Status: `incomplete`
- Gap count: `5`
- Covered count: `0`
- Missing count: `5`
- Coverage: `0.0%`
- Symbols: `000988.SZSE`, `002281.SZSE`, `601869.SSE`
- Missing dates: `2026-05-18`, `2026-05-27`, `2026-05-28`

Missing rows:

- `000988.SZSE` on `2026-05-18`
- `002281.SZSE` on `2026-05-27`
- `601869.SSE` on `2026-05-27`
- `002281.SZSE` on `2026-05-28`
- `601869.SSE` on `2026-05-28`

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `132 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/vnpy_integration alphaagent/server/api`: passed
- `pnpm --dir frontend run build`: passed, Vite chunk-size warning only
- `docker compose up -d --build alphaagent-api alphaagent-web`: API healthy, web running

Real browser smoke with Chromium:

- `/quant` candidates: date list reaches `2025-06-13` through `2026-06-12`; no `部分就绪`.
- `/quant` backtest: strict `14:30` coverage visible.
- `/quant` advanced backtest settings: fixed `1分钟 / 14:30快照`; no editable `尾盘开始`、`尾盘结束`、`MA5允许偏离` inputs.
- `/quant` data: minute/14:30 data tools visible.
- `/stocks/002636.SZSE`: 金安国纪 detail page loads with quant context.
- No failed browser requests or console errors.

Screenshots:

- `/tmp/alphaagent-quant-candidates-real.png`
- `/tmp/alphaagent-quant-backtest-real.png`
- `/tmp/alphaagent-quant-backtest-advanced-real.png`
- `/tmp/alphaagent-quant-data-real.png`
- `/tmp/alphaagent-stock-002636-real.png`

## Open Risks

- `#60` is still negative return and still has 5 missing strict snapshots.
- Overfitting is not proven solved. Current evidence is a single short-window strict run, not a multi-year walk-forward result.
- Next validation should first fill the 5 missing 14:30 snapshots by `backtest_id=60`, rerun strict pipeline, then compare walk-forward/parameter sensitivity.
