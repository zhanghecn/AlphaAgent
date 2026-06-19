# Setup / Market / Exit Audit

Date: 2026-06-19

## Scope

- Backtest: `#194`
- Strategy: `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Endpoint: `GET /api/backtests/194/setup-market-exit-audit?lookahead_days=10`
- Purpose: classify closed-trade path quality by entry setup, dynamic market regime and exit reason before changing strategy rules.

## Result

The audit covers all `214` closed trades from `#194`.

| Metric | Value |
| --- | ---: |
| Closed trades | `214` |
| Win rate | `32.24%` |
| Average return | `+3.14%` |
| Median return | `-4.29%` |
| Total realized PnL | `+658,856.20` |
| Average MAE | `-4.32%` |
| Average MFE | `+13.92%` |
| Average giveback from MFE | `10.85%` |
| Sold-before-rebound count | `81` |
| Exit/giveback issue count | `48` |
| Entry follow-through issue count | `58` |
| Entry-quality issue count | `3` |
| Loss-control issue count | `14` |
| Failed launch count | `87` |
| No-follow-through count | `22` |
| Confirmed follow-through count | `77` |

## Early Follow-Through Split

This split uses the first three holding snapshots after entry. It is a read-side
diagnostic only; it does not change any buy/sell decision.

| Early Path | Trades | Win Rate | Avg Return | Sold Before Rebound | Entry Follow-Through Issue |
| --- | ---: | ---: | ---: | ---: | ---: |
| Failed launch | `87` | `9.20%` | `-5.47%` | `31` | `47` |
| Confirmed follow-through | `77` | `50.65%` | `+8.94%` | `34` | `0` |
| Weak follow-through | `28` | `46.43%` | `+14.42%` | `9` | `0` |
| No follow-through | `22` | `40.91%` | `+2.55%` | `7` | `11` |

## Visible Entry Factor Audit

The latest API response adds `summary.entry_launch_quality_audit`, which buckets
the same `214` closed trades by entry-day visible factors. It is diagnostic only.

Key result: "低吸越久、均线越近就越应该加分" is not supported by the current
closed-trade sample as a standalone rule.

| Bucket | Trades | Failed Launch | Confirmed Follow-Through | Avg Return |
| --- | ---: | ---: | ---: | ---: |
| `low_suction_days = 0` | `104` | `33.65%` | `45.19%` | `+6.20%` |
| `low_suction_days = 3-4` | `20` | `50.00%` | `25.00%` | `-5.91%` |
| `low_suction_days = 5+` | `72` | `50.00%` | `23.61%` | `+2.29%` |
| `ma_convergence <= 5%` | `42` | `50.00%` | `14.29%` | `+0.57%` |
| `ma_convergence 5-8.8%` | `46` | `50.00%` | `34.78%` | `+1.66%` |
| `ma_convergence > 13%` | `101` | `34.65%` | `44.55%` | `+5.82%` |
| `pullback_days 12+` | `20` | `65.00%` | `20.00%` | `-2.89%` |
| `close_location 0.58-0.70` | `74` | `35.14%` | `44.59%` | `+7.27%` |
| `close_location >=0.70` | `74` | `47.30%` | `29.73%` | `+2.33%` |
| `volume_ratio 1.2-1.8` | `17` | `23.53%` | `41.18%` | `+3.93%` |
| `volume_ratio <0.7` | `29` | `48.28%` | `27.59%` | `+0.16%` |

Interpretation:

- Very tight MA convergence plus long low-suction buildup is not automatically
  safer; in this sample it often means a late/weak false launch.
- The better launch context is more nuanced: entry close location in the middle
  upper area (`0.58-0.70`) and non-dead volume are healthier than "横得越久越好".
- Dragon pullback and low-suction share support/launch concepts, but should not
  be combined by blindly adding low-suction days. Low-suction evidence needs a
  "launch quality" gate or ranking context, not a permanent reserved slot.
- `pullback_days >= 12` is a visible warning bucket: it had `65%` failed launch
  and negative average return. This matches the user's concern about waiting too
  late after the actual low-suction window.

## Entry Setup Split

| Setup | Trades | Win Rate | Avg Return | Total PnL | Sold Before Rebound | Exit Giveback | Entry Quality |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `dragon_pullback` | `131` | `34.35%` | `+4.37%` | `+561,324.20` | `48` | `33` | `25` |
| `stealth_low_suction` | `83` | `28.92%` | `+1.20%` | `+97,532.00` | `33` | `15` | `20` |

## Exit Reason Split

| Exit Reason | Trades | Avg Return | Total PnL | Sold Before Rebound |
| --- | ---: | ---: | ---: | ---: |
| `support_stop` | `125` | `-7.27%` | `-886,039.99` | `48` |
| `trend_trailing_stop` | `33` | `+44.65%` | `+1,442,342.35` | `16` |
| `profit_protection_stop` | `26` | `+6.78%` | `+170,652.73` | `11` |
| `rotation_for_stronger_signal` | `11` | `-0.41%` | `-5,152.90` | `1` |

## Support Stop Context Split

The API now returns `summary.support_stop_context_audit`, a read-only split of
the `125` `support_stop` exits. It uses only the already persisted trade path:
MAE/MFE, first-three-day follow-through, giveback and the 10-day post-exit
rebound flag. It does not change the sell rule.

| Context | Trades | Avg Return | Total PnL | Avg MFE | Sold Before Rebound |
| --- | ---: | ---: | ---: | ---: | ---: |
| True failed launch stop | `49` | `-7.84%` | `-373,057` | `-2.63%` | `0` |
| Stopped then rebounded | `41` | `-6.94%` | `-278,751` | `+0.82%` | `41` |
| Had follow-through but lost support | `14` | `-5.36%` | `-74,408` | `+4.34%` | `0` |
| Clean float-profit giveback | `13` | `-8.87%` | `-110,817` | `+11.41%` | `0` |
| High MFE then rebound after stop | `7` | `-6.30%` | `-43,241` | `+12.25%` | `7` |
| Other support stop | `1` | `-5.78%` | `-5,766` | `+5.89%` | `0` |

Interpretation:

- The largest part of `support_stop` is still entry/launch failure: `49` trades
  had negative/low MFE and poor early follow-through.
- A separate large block is sell/hold timing: `41` trades stopped out and then
  rebounded at least `8%` inside the 10-trading-day lookahead.
- The clean "floating profit gave back and then broke support" bucket is only
  `13` trades. That explains why the broad mid-profit giveback stop helped
  focused samples but failed globally: the bucket is real, but not the majority
  of `support_stop`.
- Future sell-side experiments need different handling per context. A single
  support-stop replacement is unlikely to work.

## Focus Samples

- `601179.SSE`: bought `2026-02-03` as `dragon_pullback`, sold `2026-02-06` by `support_stop`, return `-9.60%`, MFE only `+0.92%`, early state `failed_launch`, path issue `entry_follow_through`. This is mainly a repeated/classic dragon-pullback buy-confirmation problem, not a missed trailing-profit case. The later `2026-02-25` low-suction BUY existed, but candidate trace says it did not enter the portfolio execution top `20`.
- `600352.SSE`: bought `2026-03-12` as `stealth_low_suction`, sold `2026-03-16` by `support_stop`, return `-8.56%`, MFE `-5.21%`, early state `failed_launch`. This is a false low-suction launch: buy signal confirmed, but the first three holding snapshots had no positive follow-through.
- `002240.SZSE`: bought `2026-03-12` as `stealth_low_suction`, sold `2026-03-19` by `support_stop`, return `-9.69%`, early state `failed_launch`, post-exit max rebound `+13.67%`. This has both problems: entry had poor immediate follow-through, then the support-stop exit was followed by a rebound.
- `002384.SZSE`: `2026-05-27` dragon-pullback trade returned `-7.92%`, MFE `+2.94%`, and rebounded `+19.02%` after exit. It is more sell/hold timing than pure buy-point quality.
- `002443.SZSE`: bought `2026-05-14`, sold `2026-06-04` by `support_stop`, return `-4.86%`, MFE `+11.82%`, early state `confirmed_follow_through`, no meaningful post-exit rebound. This remains the clean sample for highest-profit giveback control before support stop.

## Conclusion

The latest evidence says the next optimization should not be a broad buy hard-reject or a broad support-stop replacement. `support_stop` is the largest loss source, but it mixes several patterns:

- true bad entries with low MFE and failed early follow-through;
- valid low-suction/dragon signals that never receive first-three-day follow-through;
- profitable paths that gave back too much before `support_stop`;
- exits that were followed by a rebound inside the 10-day observation window.

The next experiment should be narrow and path-aware. For entries, keep early
follow-through as a diagnostic target first; prior broad launch-quality scoring
and narrow launch-risk penalties both failed globally. For exits, test only
context-specific hypotheses such as a confirmed-follow-through + high-MFE
giveback guard, or a rebound-prone stop-out marker for review. Do not revive
broad early-breakdown stops, repeated-dragon hard rejects, high-level hard
rejects, or a single support-stop replacement without a new global comparison.

## Verification

- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_quant_backtest_portfolio.py -q`: `324 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`: passed
- `pnpm --dir frontend build`: passed, with existing large chunk warning.
- `docker compose up -d --build alphaagent-api`: API healthy
