# Entry Context Marker Audit

Date: 2026-06-19

## Scope

- Product baseline: `#203/#194`
- Strategy: `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Endpoint checked after rebuild: `GET /api/backtests/203/path-diagnostics?lookahead_days=10`

This is a read-only explanation improvement. It does not change buy score,
candidate ranking, portfolio execution, sell rules, or backtest return.

## What Changed

Path diagnostics now enrich each closed trade with three user-facing labels:

- `entry_context_label`: entry-day market context, such as `震荡但未回暖`, `市场广度弱`, `环境向下/强风险`, or `止跌观察`.
- `entry_launch_diagnostic_label`: launch quality, such as `启动后立即失败`, `低吸启动后有跟随`, `经典龙回头偏早`, or `买后资金跟随`.
- `fund_flow_coverage_label`: whether market fund-flow data was available for that entry date.

The same labels are grouped in path-diagnostic summary buckets:

- `by_entry_context`
- `by_entry_launch_diagnostic`
- `by_fund_flow_coverage`

Stock detail and backtest drilldown show these labels inside the existing path
diagnostic cards/tables. No new product entry or extra user workflow was added.

## Verified API Findings

Focused samples from `#203`:

| Symbol | Entry | Setup | Return | Entry Context | Launch Diagnostic | Fund Flow Coverage | Interpretation |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| `601179.SSE` | `2026-02-03` | `dragon_pullback` | `-9.60%` | `回暖确认` | `启动后立即失败` | `资金流数据不足` | Early classic dragon-pullback entry failed immediately; not the later low-suction buildup the user expected. |
| `600352.SSE` | `2026-03-12` | `stealth_low_suction` | `-8.56%` | `震荡但未回暖` | `启动后立即失败` | `资金流数据不足` | Low-suction launch confirmation alone was not enough; the first holding snapshots failed. |
| `002240.SZSE` | `2026-03-12` | `stealth_low_suction` | `-9.69%` | `震荡但未回暖` | `启动后立即失败` | `资金流数据不足` | Both problems appeared: false launch first, then sold-before-rebound behavior. |
| `002384.SZSE` | `2026-05-27` | `dragon_pullback` | `-7.92%` | `市场广度弱` | `买后弱跟随` | `资金流数据不足` | More sell/hold timing plus weak market breadth than pure low-suction recognition. |
| `002443.SZSE` | `2026-05-14` | `dragon_pullback` | `-4.86%` | `止跌观察` | `买后资金跟随` | `资金流数据不足` | Clean float-profit giveback sample; better suited to sell-side research than entry rejection. |

Summary buckets from `#203`:

| Bucket | Trades | Win Rate | Avg Return | Total PnL |
| --- | ---: | ---: | ---: | ---: |
| `entry_context=震荡但未回暖` | `19` | `10.53%` | `-6.84%` | `-128,457` |
| `entry_launch=启动后立即失败` | `87` | `9.20%` | `-5.47%` | `-459,455` |
| `entry_launch=低吸启动后有跟随` | `26` | `65.38%` | `+13.08%` | `+333,081` |
| `fund_flow_coverage=资金流数据不足` | `214` | `32.24%` | `+3.14%` | `+658,856` |

## Data Coverage Note

Container database check on 2026-06-19:

- `sector_fund_flows`: `2,970` rows, only `2026-06-18`.
- `stock_fund_flows`: `2,137` rows, `2026-06-12` to `2026-06-18`.
- `stock_daily_bars`: `1,030,339` rows, `2024-05-28` to `2026-06-18`.
- `sector_period_scores`: `900` rows, `2026-06-12` to `2026-06-17`.

Therefore, February/March focused samples cannot be judged by real historical
fund-flow state yet. Their `资金流数据不足` label is accurate and should not be
read as "fund flow was safe". For long-history market-adaptive trading rules,
fund-flow and sector-theme history must be backfilled first.

## Conclusion

The low-suction problem is now better separated:

- Low-suction buildup and launch confirmation identify candidate structure.
- The first post-entry path tells whether funds actually followed.
- Market context distinguishes `震荡但未回暖` and weak breadth from broad risk-off.
- Fund-flow labels expose data coverage rather than pretending unknown data is neutral.

Do not promote a trading rule from this alone. The next candidate experiment, if
any, should stay default-off and focus on the narrow intersection of:

- low-suction confirmed but `震荡但未回暖` / weak breadth;
- launch day high close location or dead volume;
- no fund-flow coverage or confirmed outflow once history is available;
- replacement opportunity cost versus missed trend winners.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `314 passed, 1 warning`.
- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py -q`: `60 passed, 1 warning`.
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api`: passed.
- `pnpm --dir frontend run build`: passed, with existing large chunk warning.
- `git diff --check`: passed.
- `docker compose up -d --build alphaagent-api`: API rebuilt and healthy.
