# Low-suction / Dragon Boundary Context Audit

## Current State

- Baseline: `mainline_dragon_pullback / 0.1.21`, portfolio backtest `#203/#194`.
- Range: `2025-03-26` to `2026-06-18`.
- Execution model: `legacy_next_open`, daily close-visible signal and next trading day open execution.
- This audit adds read-only boundary diagnostics between "低吸洗盘" and "龙回头". It does not change default scoring, BUY/WATCH decisions, sell rules, ranking, max positions, or product baseline.

New fields:

- `low_suction_dragon_state`
- `low_suction_dragon_label`
- `low_suction_dragon_conflict`
- `low_suction_dragon_conflict_level`
- `low_suction_dragon_notes`

The goal is to make the conflict visible:

- 低吸蓄势 is not automatically a buy point.
- 龙回头 can be too early when it lacks repeated low-suction support.
- A dragon-pullback row can overlap with low-suction buildup, but it should be labelled separately from a confirmed low-suction launch.
- Path diagnostics can later show whether a confirmed low-suction entry actually got follow-through, but post-entry follow-through is audit-only and cannot be used as a signal-day trading rule.

## Verification

Commands already run after this read-side change:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest
pnpm -C frontend build
git diff --check
docker compose up -d --build alphaagent-api
```

Results:

- Quant/backtest tests: `327 passed, 1 warning`.
- `compileall`: passed.
- Frontend build: passed.
- `git diff --check`: passed.
- API container rebuilt.
- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=2` still returns `#203/#194` with unchanged metrics: return about `+82.99%`, max drawdown about `-15.59%`, buy/sell/open `224 / 214 / 10`.

APIs exposing the fields:

- `GET /api/quant/recommendations`
- `GET /api/quant/symbols/{vt_symbol}/latest-state`
- `GET /api/quant/symbols/{vt_symbol}/signal-history`
- `GET /api/backtests/203/path-diagnostics?lookahead_days=10`
- `GET /api/backtests/203/setup-market-exit-audit?lookahead_days=10`

Frontend display:

- Quant candidates: "为什么这个分数".
- Stock detail latest score card.
- Stock detail path fact cards.
- Backtest path diagnostics environment/startup column.

## Global Buckets

`#203` path-diagnostics main buckets:

| State | Label | Trades | Win Rate | Avg Return | Read |
| --- | --- | ---: | ---: | ---: | --- |
| `standard_dragon_pullback` | 标准龙回头 | `106` | `37.74%` | `+5.57%` | Still the main positive-return setup class. |
| `low_suction_confirmed_failed_follow` | 低吸确认后无承接 | `28` | `3.57%` | `-7.36%` | Core failure bucket, but uses post-entry path evidence, so it is audit-only. |
| `low_suction_confirmed_followed` | 低吸确认且买后承接 | `26` | `65.38%` | `+13.08%` | Confirms the user's idea that low-suction plus the first real lift can be high quality when follow-through appears. |
| `low_suction_waiting_launch` | 低吸蓄势等待上拉 | `24` | `12.50%` | `-3.14%` | Shows why pure buildup should not be drawn as a key buy point every day. |
| `early_dragon_without_buildup` | 龙回头偏早缺低吸蓄势 | `16` | `31.25%` | `+2.22%` | Real risk bucket, but prior hard-reject experiments were globally weak. |
| `dragon_overlap_waiting_low_suction` | 龙回头叠加低吸蓄势未启动 | `9` | `0.00%` | `-5.91%` | Strong warning bucket for the current sample; still needs default-off validation before trading use. |

## Focus Samples

| Symbol | Observation | Boundary Read |
| --- | --- | --- |
| `600352.SSE` | User questioned why the 2026-03-10/03-12 low-suction buy failed. | Classified as `低吸确认后无承接`; the issue is not missing low-suction detection, but weak follow-through after confirmation. |
| `002240.SZSE` | 2026-03-13 old persisted candidate looked like a buy, but trend failed. | Current read-side action resolves to `WATCH`; boundary/path label shows `低吸确认后无承接`. |
| `601179.SSE` | 2026-02-03 looked too early; user pointed to 2/24 buildup and 2/25 MA5 breakout. | 2/3 is `龙回头偏早缺低吸蓄势`; the later 2/24-2/25 idea is a different low-suction launch window. |
| `002119.SZSE` | There was a signal but no buy, then a later bad buy. | Boundary label exposes high/repeated dragon risk such as `龙回头偏早缺低吸蓄势`; hard-reject experiments still failed globally, so it remains diagnostic. |

## Conclusion

This is a useful explanation layer, not a trading-rule promotion.

The current evidence supports the user's direction: low-suction and dragon-pullback share some support/MA context, but they are not the same factor and should not be merged by blindly adding points. The better model is:

- Low-suction buildup accumulates evidence while waiting.
- The first controlled lift is the possible key signal.
- Dragon-pullback stays valid, but early dragon entries without buildup or overlapping unlaunched low-suction state need warning labels.
- Post-entry failed follow-through is a sell/hold research problem, not a signal-day feature.

Next trading experiments must stay default-off and context-aware:

- Failed-launch exit only when low-suction/dragon boundary warning, weak or non-warming market context, no reclaim, and acceptable replacement quality all align.
- Profit-giveback exit only when there is visible distribution/support loss and no current buy/hold protection.
- Do not revive broad low-suction hard gates, repeated-dragon hard rejects, or broad early-exit stops; previous experiments `#195/#196/#197/#198/#199/#200/#201/#207` failed globally.
