# Backtest 62 Strict 14:30 Recheck

## Current State

- Source gap run: `#60`
- New strict run: `#62`
- Strategy: `mainline_leader_pullback / 0.1.1`
- Range: `2026-02-02` to `2026-06-13`
- Universe: main board, `max_symbols=80`
- Execution: `strict_1430`, `minute_interval=1m`, `tail_entry_start=14:30`, `tail_entry_end=14:30`
- Initial cash: `1,000,000`
- Final equity: `949,180.1413490004`
- Total return: `-5.081985865099958%`
- Max drawdown: `-9.57783253422486%`
- Closed trade count: `18`
- Win rate: `33.33333333333333%`

## Gap Fill

`#60` had 5 missing strict `14:30` snapshots:

- `000988.SZSE` on `2026-05-18`
- `002281.SZSE` on `2026-05-27`
- `601869.SSE` on `2026-05-27`
- `002281.SZSE` on `2026-05-28`
- `601869.SSE` on `2026-05-28`

Provider checks:

- TDX dry-run: covered `5/5`, `rows_read=5`.
- AkShare dry-run: `rows_read=0`, source unavailable for those historical dates.
- Tushare dry-run: unavailable, `TUSHARE_TOKEN not configured`.
- vn.py gap import: unavailable in current API container due `ModuleNotFoundError`.

TDX import:

- `POST /api/data-sync/imports/minute-bars/tdx-gaps`
- Payload: `{"backtest_id":60,"tail_entry_start":"14:30","tail_entry_end":"14:30","dry_run":false,"max_gaps":20,"max_pages_per_symbol":32,"timeout_seconds":3}`
- Result: `rows_read=5`, `rows_written=5`, `audit_after.status=ready`, `coverage_pct=100.0`.

## Execution Quality

`GET /api/backtests/62/minute-coverage`:

- Status: `strategy_not_triggered`
- Buy count: `21`
- Real 14:30 minute buys: `21`
- Real 14:30 ratio: `100.0%`
- Daily close proxy buys: `0`
- Strict 14:30 rejected orders: `83`
- Minute gap rejected orders: `0`
- Tail entry rejected orders: `83`
- Tail exit rejected orders: `0`

Interpretation:

- Filled buys can be read as real execution-day `14:30` 1-minute snapshots.
- There is no daily-close proxy in filled buys.
- The previous missing-snapshot problem is closed for this same `max_symbols=80` universe.
- Remaining strict rejected orders are tail-entry condition failures, not missing minute data.

## Reality Audit

`GET /api/backtests/62/report?trade_limit=5`:

- Candidate data visibility: pass, uses signal day and earlier daily/factor data.
- Financial publish-date constraint: pass, uses `publish_date <= trade_date`.
- Execution after signal: pass, D close signal then next trading day `14:30`.
- Strict minute gap: pass, `0` missing `14:30` snapshot rejections.
- Overfit scope: warning, multi-year all-A walk-forward and parameter grid are still not proven.

Report assumption now says:

> Strict 14:30 model uses D-day close-visible daily data to create next-day plans; execution only fills at the 14:30 1-minute snapshot when it exists and satisfies the tail condition.

## 金安国纪复核

`002636.SZSE` still has historical signals:

- Low-pullback strategy: `entry_signal_count=23`.
- Breakout strategy: `entry_signal_count=18`.
- Financial coverage: local reports `20`, usable reports `20`, missing publish dates `0`, future publish dates `0`, latest publish date `2026-04-29`.

Additional focused check after the quant cleanup refactor:

- Endpoint: `GET /api/quant/symbols/002636.SZSE/signal-history?start=2026-02-02&end=2026-06-13&strategy=mainline_leader_pullback&limit=5`
- Result: `scored_date_count=85`, `entry_signal_count=16`, `watch_count=69`.
- Best entry / best total score: `2026-02-09`, `total_score=84.4645`.
- `GET /api/backtests/62/symbols/002636.SZSE` returned no trades or positions for this backtest.
- Interpretation: 金安国纪不是完全筛不出来；在 `#62` 组合回测里没有实际成交，需要按组合排序、仓位/资金竞争和严格 `14:30` 执行约束解释。

Focused diagnostics after the P0 diagnostics update:

- Endpoint: `GET /api/quant/symbols/002636.SZSE/diagnostics?start=2026-02-02&end=2026-06-13&backtest_id=62&signal_date=2026-02-09&limit=5`
- Status: `entry_signal_not_traded`
- Main reason: `candidate_not_planned` / `候选未进入组合计划`
- Candidate action/rank/score: `BUY`, rank `2`, score `84.4645`
- Signal-day equity: cash `1,000,000`, market value `0`, total equity `1,000,000`, position count `0`
- Interpretation: this specific signal day had a valid BUY candidate and available cash, but there was no matching theoretical buy plan in `#62`; the next check is why the historical candidate trace did not enter the portfolio plan for that run's persisted signal plan.

## Strict Rejection Reason Split

Current code now separates strict `14:30` rejections into:

- `missing_1430_snapshot`: execution day has no target `14:30` 1-minute snapshot.
- `tail_entry_not_triggered`: target snapshot exists, but tail-entry conditions such as MA5 distance are not satisfied.

Real API verification after the split:

- `GET /api/backtests/62/minute-coverage`
  - Buy count: `21`
  - Real 14:30 buys: `21`
  - Daily close proxy: `0`
  - Strict rejected: `83`
  - Missing snapshot rejected: `0`
  - Tail-entry rejected: `83`
- Strategy comparison for `2026-02-02` to `2026-06-13`, main board, `max_symbols=80`, `strict_1430`:
  - `mainline_leader_pullback`: `tail_entry_rejected_count=83`, `minute_gap_rejected_count=0`, return `-5.081985865099958%`
  - `breakout_confirmation`: `tail_entry_rejected_count=8`, `minute_gap_rejected_count=24`, return `0.0%`

Interpretation:

- `#62` low-pullback result is still a complete strict `14:30` run for this universe; its rejected orders are strategy-condition failures, not missing-minute-data failures.
- The breakout comparison still has missing `14:30` data under the same date range, so its `0.0%` result means "no strict fills with missing snapshot rejections present", not evidence of a profitable strategy.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `139 passed, 1 warning`
- After `quant/strategies`, `screening_loaders`, `screening_payloads`, and `screening_persistence` refactors: `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `139 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/services/quant/factors.py alphaagent/server/services/quant/strategy_registry.py alphaagent/server/services/quant/strategies alphaagent/server/services/quant/screening.py alphaagent/server/services/quant/screening_loaders.py alphaagent/server/services/quant/screening_payloads.py alphaagent/server/services/quant/screening_persistence.py`: passed
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "candidate_trace or audit_api or drilldown or trades_api or day_detail or symbol_detail or persist or strict_entry or signal_events or validation_grid or walk_forward or report or execution_quality or minute_gap or minute_bars or vendor_manifest or backtest_gaps or tdx or tushare or akshare or obsolete_10m" -q`: `59 passed, 80 deselected, 1 warning`
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strict_minute_pipeline" -q`: `5 passed, 134 deselected, 1 warning`
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "audit_minute_gap or minute_gap_audit or minute_gap_vendor or minute_bars or tdx_gap or tushare or akshare or vnpy_gap_import or strict_minute_pipeline" -q`: `31 passed, 108 deselected, 1 warning`
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api`: passed
- `uv run python -m compileall alphaagent/server/services/minute_gaps.py alphaagent/server/services/data_sync.py alphaagent/server/services/data_providers alphaagent/server/services/vnpy_integration/database_import.py alphaagent/server/api/data_sync.py`: passed
- `pnpm --dir frontend run build`: passed, Vite chunk-size warning only
- `docker compose up -d --build alphaagent-api alphaagent-web`: API healthy, web running
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_comparison or run_backtest_returns_signal_events" -q`: `6 passed, 140 deselected, 1 warning`
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "symbol_diagnostics or candidate_trace or strategy_comparison or run_backtest_returns_signal_events" -q`: `14 passed, 132 deselected, 1 warning`
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strict_1430 or signal_events or minute_gap_csv or execution_quality or strategy_comparison or drilldown_options" -q`: `16 passed, 131 deselected, 1 warning`
- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `146 passed, 1 warning`
- After strict rejection reason split: `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `147 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest alphaagent/server/api`: passed
- `pnpm --dir frontend run build`: passed, Vite chunk-size warning only
- `docker compose up --build -d alphaagent-api alphaagent-web`: API healthy, web running
- After P0/P1 quant UI updates and candidate BUY/WATCH run-count fix:
  - `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `156 passed, 1 warning`
  - `uv run python -m compileall alphaagent/server/services/quant alphaagent/server/api/quant.py`: passed
  - `pnpm --dir frontend run build`: passed, Vite chunk-size warning only
  - `docker compose up -d --build alphaagent-api alphaagent-web`: API healthy, web running
  - `GET /api/quant/screen-runs?strategy=mainline_leader_pullback&limit=1` now returns `buy_recommendation_count` and `watch_recommendation_count`; latest `2026-06-12` run `#177` returned `recommendation_count=20`, `buy_recommendation_count=13`, `watch_recommendation_count=7`.

Real browser smoke with Chromium no-sandbox:

- `/quant`: loads.
- `/quant` backtest tab: strict/14:30 content visible.
- `/quant` data tab: strict 14:30 backtest ID gap flow visible.
- `/quant` data tab after `MinuteDataWizard` refactor: fixed `1分钟 / 14:30快照` visible; server gap file path and external minute CSV are only visible after expanding the advanced area.
- `/quant` data tab strict pipeline guard: source backtest ID path can run without extra confirmation; advanced CSV/file_path path disables strict run until the explicit confirmation checkbox is checked.
- `/quant` data tab after minute-gaps refactor: strict panel still renders with fixed `1分钟 / 14:30快照`, backtest ID field, and provider selector.
- `http://localhost:5173/quant` and `http://127.0.0.1:5173/quant`: both reachable in this Compose run.
- `/stocks/002636.SZSE`: 金安国纪 page loads with quant audit and financial coverage.
- Console errors: `0`
- Failed browser requests: `0`

Additional headless Chrome smoke after latest refactors:

- `/quant`: candidate tab loads.
- `/quant -> 回测`: `运行组合回测`, `1分钟 / 14:30快照`, strict `1m / 14:30` copy and trade attribution pagination visible.
- `/quant -> 数据`: backtest ID source, provider flow, strict audit/run path, advanced CSV fallback and `14:30` copy visible.
- `/data`: data management page loads with `14:30` strict gap copy.
- `/stocks/002636.SZSE`: 金安国纪 page loads with quant audit, BUY count and financial policy copy.
- Console errors: `0`
- Failed browser requests: `0`
- Ordinary quant/data paths do not show `10m` or `10分钟`.
- Strategy comparison UI after running comparison shows `breakout_confirmation` / `平台放量突破确认` with `0.00%` as the best strategy when compared with negative low-pullback return.
- Backtest page now separately shows `入场未触发` and `缺14:30快照`; browser smoke after the split had no console errors and no failed requests.
- Stock detail diagnostics for `002636.SZSE` after entering backtest ID `62` and signal date `2026-02-09` show candidate action, rank, score, signal-day cash, signal-day market value, total equity, and the main reason `候选未进入组合计划`.
- `/quant -> 候选` after the candidate coverage update shows 候选运行覆盖, BUY候选 and WATCH候选; no console errors or failed requests.
- `/quant -> 回测 -> 交易归因` after the decision timeline extraction still shows 决策时间线; no console errors or failed requests.
- `/stocks/002636.SZSE` single-stock backtest defaults to `strict_1430 / 1m / 14:30` and shows strict 14:30 wording after running the page smoke.

Screenshots:

- `/tmp/alphaagent-quant-after-strict62.png`
- `/tmp/alphaagent-quant-backtest-after-strict62.png`
- `/tmp/alphaagent-quant-data-after-strict62.png`
- `/tmp/alphaagent-stock-002636-after-strict62.png`
- `/tmp/alphaagent-real-browser/quant_data_tab_refactor.png`
- `/tmp/alphaagent-real-browser/quant_data_tab_expanded_precise_refactor.png`
- `/tmp/alphaagent-real-browser/quant_strict_pipeline_confirmation.png`
- `/tmp/alphaagent-real-browser/quant_data_after_minute_gaps_refactor.png`
- `/tmp/alphaagent-real-browser/stock_002636_refactor.png`
- `/tmp/alphaagent-real-browser/quant_backtest_expanded_strategy_comparison.png`
- `/tmp/alphaagent-real-browser/stock_002636_diagnostics_summary_fields_filled.png`
- `/tmp/alphaagent-real-browser/quant_backtest_reason_split_strategy_comparison.png`

## Open Risks

- `#62` is a complete strict `14:30` run for the `max_symbols=80` universe, but return is still negative.
- The strategy did not beat sample equal-weight, major indices, random sample average, or high-friction stress in this short run.
- Overfitting is not proven solved. A multi-year all-A walk-forward, parameter sensitivity, market-regime split, and benchmark excess test are still required before treating the strategy as robust.
