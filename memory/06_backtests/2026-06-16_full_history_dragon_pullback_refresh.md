# Dragon Pullback Full-history Refresh

## Current State

- Local daily bars currently cover `2025-03-26` to `2026-06-15`.
- `mainline_dragon_pullback / 0.1.0` candidate runs were refreshed for the latest missing segment `2026-03-31` to `2026-06-15`.
- The latest candidate run is `quant_signal_runs.id=1736`, `trade_date=2026-06-15`, `recommendation_count=10`.
- The latest global buy/sell record is `strategy_replay_runs.id=3`, covering `2026-03-31` to `2026-06-15`, status `ready`, `attempt_count=7255`, `filled_count=2631`, `rejected_count=8`.
- The latest full-history portfolio backtest is `backtests.id=116`, covering `2025-03-26` to `2026-06-15`, status `succeeded`.

## Key Results

Backtest `#116`:

- Strategy: `mainline_dragon_pullback / 0.1.0`
- Execution model: `legacy_next_open`
- Range: `2025-03-26` to `2026-06-15`
- Total return: `+66.7789%`
- Annual return: `+54.5682%`
- Max drawdown: `-30.2248%`
- Trade rows: `394`
- Buy / sell rows: `201 / 193`
- Open positions: `8`
- Win rate: `21.2435%`
- Profit factor: `1.5511`

Latest `2026-06-15` candidates:

1. `600522.SSE` 中天科技 `BUY` score `98.92`
2. `603311.SSE` 金海高科 `BUY` score `97.72`
3. `600246.SSE` 万通发展 `BUY` score `97.60`
4. `002585.SZSE` 双星新材 `WATCH` score `97.54`
5. `603663.SSE` 三祥新材 `BUY` score `97.02`
6. `605006.SSE` 山东玻纤 `BUY` score `96.70`
7. `605566.SSE` 福莱蒽特 `BUY` score `96.46`
8. `600487.SSE` 亨通光电 `BUY` score `96.16`
9. `603773.SSE` 沃格光电 `BUY` score `95.85`
10. `002484.SZSE` 江海股份 `BUY` score `95.82`

## 603629.SSE Verification

`GET /api/quant/symbols/603629.SSE/latest-state?strategy=mainline_dragon_pullback` now returns:

- `process.source = replay`
- `process.start_date = 2026-03-31`
- `process.end_date = 2026-06-15`
- `process.latest_available_trade_date = 2026-06-15`
- `process.is_stale = false`
- state: `buy_filled`
- events: `24`
- closed trades: `2`

This fixes the stale-detail problem where the stock page previously mixed in old `2025-12-30 ~ 2026-02-02` replay data after later candidate runs already existed.

## How To Recheck

```bash
curl -s 'http://localhost:8000/api/quant/trading-dates?limit=5'
curl -s 'http://localhost:8000/api/quant/screen-runs?limit=5&strategy=mainline_dragon_pullback'
curl -s 'http://localhost:8000/api/quant/replay-runs?limit=3&strategy=mainline_dragon_pullback'
curl -s 'http://localhost:8000/api/backtests?limit=3&run_type=portfolio&strategy=mainline_dragon_pullback'
curl -s 'http://localhost:8000/api/quant/symbols/603629.SSE/latest-state?strategy=mainline_dragon_pullback'
```

Build/test checks run after the code changes:

```bash
python -m py_compile alphaagent/server/services/quant/screening.py alphaagent/server/services/quant/symbol_quant_state.py
pnpm --dir frontend build
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
git diff --check
```

## Open Risks

- The strategy still has high drawdown (`-30.22%`) despite improved return; this is not yet a robust profitability conclusion.
- Long range candidate generation and full-history backtest are still synchronous HTTP requests. They work, but the UI can feel blocked for several minutes. The next engineering step should be a background job/progress API.
- Remaining strategy work: reduce repeated BUY signals during one active setup, strengthen sell/stop logic, and validate the six user-specified stocks after the fresh `2026-06-15` replay.
