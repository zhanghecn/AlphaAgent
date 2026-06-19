# Low-suction And Market Read-only Markers

Date: 2026-06-19

## Current State

This change adds readable diagnostics only. It does not change default BUY/WATCH logic, candidate ranking, portfolio execution, sell rules, position sizing, or the product baseline.

New read-side fields:

- `low_suction_stage` / `low_suction_stage_label`: classifies low-suction rows into buildup waiting for lift, mature buildup, balanced first lift, thin-volume lift, late lift, confirmed lift, or not-low-suction.
- `low_suction_launch_quality_bucket` / `low_suction_launch_quality_label`: classifies the executable/near-executable low-suction state into unconfirmed buildup, balanced first lift, thin-volume lift, high-close lift, late pullback lift, repeated lift, other confirmed lift, or not-low-suction. This uses the same bucket logic as `setup-market-exit-audit`.
- `market_context_summary`: compresses dynamic market context into `state`, `label`, `severity`, short `notes`, and a nested `fund_flow_marker`, for example `大盘向下/资金防守`, `资金连续流出 4 天`, `资金明显外逃`, or `资金回流`.

The fields are attached during fresh screening and are also normalized when reading old evidence, so old persisted candidates do not need to be invalidated just for display text.

## Verification

Commands:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest
pnpm --dir frontend run build
git diff --check
docker compose up -d --build alphaagent-api alphaagent-web
```

Results:

- Quant/backtest tests: `331 passed, 1 warning` on the final pre-commit recheck.
- `compileall`: passed.
- Frontend build: passed, with the existing chunk-size warning.
- `git diff --check`: passed.
- API and web containers rebuilt and API health returned `ok`.

2026-06-19 follow-up:

- `market_context_summary.fund_flow_marker` was added as a read-only nested marker so old and new candidate evidence can show fund-flow pressure more explicitly.
- Levels: `0` inflow/recovery, `1` balanced, `2` outflow, `3` continuous outflow, `4` panic outflow.
- The marker now also exposes `trend`, `trend_label`, `worsening_days`, `new_low`, and `recovery_from_streak_days`. This lets the UI/API say when capital outflow is expanding (`流出扩大`, level `4`) and when capital is returning after a continuous outflow streak (`连续流出 N 天后资金回流`).
- This marker is generated from existing market/fund-flow fields only. It does not change default BUY/WATCH logic, score, ranking, sell rule, or portfolio execution.
- Rechecked: `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` (`331 passed, 1 warning` on the final pre-commit recheck), `compileall`, `pnpm -C frontend build`, and `git diff --check`.

2026-06-19 latest follow-up:

- Added streak-sensitive fund-flow marker tests for worsening outflow and recovery after a streak.
- Rechecked: `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` (`331 passed, 1 warning` on the final pre-commit recheck), `uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest`, and `git diff --check`.

## API Samples

`GET /api/quant/recommendations?strategy=mainline_dragon_pullback&limit=20` returned latest candidate date `2026-06-18`, run `#5768`.

Sample returned fields:

- `603859.SSE` 能科科技: stage `非低吸蓄势`; launch quality `非低吸买点`; market summary `大盘向下/资金防守`.
- `603439.SSE` 三力制药: stage `低吸启动偏晚`; launch quality `低吸启动回踩过久`; same market risk summary.
- `603005.SSE` 晶方科技: stage `低吸蓄势等待上拉`; launch quality `低吸蓄势未确认`; same market risk summary. It is still a BUY under current default rules, which is a candidate for the next default-off experiment rather than a bug in the read-only marker.
- `603683.SSE` 晶华新材: stage `低吸上拉确认`; launch quality `低吸重复启动`; same market risk summary.

Focused symbol checks from the API container:

- `002384.SZSE` 东山精密: `2026-04-01` is still BUY, label `低吸启动买点`, stage `低吸启动偏晚`, `low_suction_days=4`, `low_suction_launch_confirmed=true`. This confirms the strategy did detect the low-suction entry; prior no-buy behavior remains a portfolio execution/full-position issue, not a missing signal.
- `600352.SSE`: `2026-03-10` is BUY but stage `低吸蓄势等待上拉`, not launch confirmation; `2026-03-11` is `低吸启动买点`, stage `低吸上拉确认`, `low_suction_days=6`. The later failure should be audited as entry follow-through/market context, not as missing low-suction detection.
- `002240.SZSE`: `2026-03-09` and `2026-03-11` are `低吸启动买点`, both stage `低吸上拉量能偏弱`. This is a useful failure marker and should remain read-only until a default-off experiment proves benefit.
- `601179.SSE`: `2026-02-02` to `2026-02-04` are classic dragon-pullback BUY rows with stage `非低吸蓄势`; `2026-02-25` is `低吸启动买点`, stage `低吸启动偏晚`, `low_suction_days=3`. This supports the current interpretation that the early February buys are not low-suction buildup entries.

## Conclusion

The new fields make the low-suction/dragon boundary visible without changing trading behavior:

- Low-suction buildup is now explicitly marked as waiting for lift instead of looking like every day is the key buy.
- The first confirmed lift, late lift, and thin-volume lift are distinguishable for later audit.
- Low-suction launch quality is now a shared read-only bucket used by candidates, stock detail, and setup/market/exit audit, avoiding separate definitions for the same idea.
- Market risk/fund-flow/recovery context is visible as warning/recovery markers, including the explicit `fund_flow_marker`, not as a trading filter.

Next experiments, if any, should remain default-off and compare global return, max drawdown, replacement quality, trend-winner opportunity cost, yearly buckets, and market-regime buckets before changing default trading rules. The cleanest next candidate is not "add low-suction score"; it is a narrow check of whether `低吸蓄势未确认`, `低吸启动回踩过久`, and `低吸启动量能偏弱` should be demoted to WATCH unless market/mainline and replacement-quality conditions are favorable.
