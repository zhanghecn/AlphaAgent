# Contextual Failed Launch Exit Experiment

## Objective

Test default-off plan A: identify true failed launches earlier only when a stronger same-day replacement candidate exists. The goal was to judge whether the strategy improves total return while reducing loss / drawdown versus the current product baseline.

## Implementation Tested

- New research parameter: `enable_contextual_failed_launch_exit_stop=false` by default.
- New sell reason: `contextual_failed_launch_exit_stop`.
- Applies only to `mainline_dragon_pullback` positions from `dragon_pullback` or `stealth_low_suction` setups.
- Requires at least three visible holding bars, no meaningful launch (`highest gain < 2.5%`), current loss `<= -2.5%`, support/MA reclaim failure, and no current same-stock buy/hold protection.
- Requires a same-day replacement BUY candidate in the execution pool, not already held/pending, with score at least `rotation_min_score` and at least `rotation_min_score_gap` above the replaced entry score when available.
- Anti-future note: the trigger uses only the entry evidence, current signal-day daily bar, current same-day candidate cache, current holding state and next-day execution. The replacement check uses candidates generated for the same signal day; it does not look at future returns.

## Verification

Commands run locally:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api
pnpm -C frontend build
git diff --check
```

Results:

- `333 passed`, one existing Starlette deprecation warning.
- Compileall passed.
- Frontend build passed. Existing large chunk warnings remain.
- `git diff --check` passed.

A performance issue was found in the first implementation: theoretical `signal_events` scanned replacement candidates for many simulated positions and made the experiment run about `589s`. It was fixed by keeping replacement-aware sell logic on real portfolio positions only; non-persistent verification after the fix completed in about `108s` with the same trade metrics.

## Global Result

Main comparison range: `2025-03-26` to `2026-06-18`, main board, `max_symbols=5000`, `legacy_next_open`, `strict_entry=true`, execution BUY top `20`, max positions `10`.

| Run | Switch | Return | Max DD | Buy / Sell / Open | Win Rate | Profit Factor | Decision |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| `#203/#194` | Product baseline | `+82.99%` | `-15.59%` | `224 / 214 / 10` | `32.24%` | `1.6762` | Current baseline |
| `#211` | `enable_contextual_failed_launch_exit_stop=true` | `+82.56%` | `-15.53%` | `219 / 209 / 10` | `33.97%` | `1.7150` | Reject as default |

Conclusion: return did **not** improve. Maximum drawdown improved slightly by about `0.06` percentage points, win rate and profit factor improved, but the total return fell by about `0.42` percentage points. The change is too small and too low-sample to promote.

## Year Split

| Run | Year | Return | Year Max DD |
| --- | ---: | ---: | ---: |
| `#203` | 2025 | `+32.94%` | `-15.59%` |
| `#203` | 2026 | `+34.42%` | `-14.04%` |
| `#211` | 2025 | `+35.09%` | `-15.53%` |
| `#211` | 2026 | `+32.02%` | `-13.86%` |

The experiment shifts performance: 2025 improves, 2026 weakens. This does not prove a robust improvement.

## Sell Reason Attribution

| Reason | Baseline Count / PnL | Experiment Count / PnL | Read |
| --- | ---: | ---: | --- |
| `support_stop` | `125 / -886,039.99` | `123 / -874,495.46` | Small loss reduction |
| `contextual_failed_launch_exit_stop` | `0 / 0` | `1 / -2,769.91` | Too few triggers |
| `trend_trailing_stop` | `33 / +1,442,342.35` | `33 / +1,442,342.35` | Trend winners preserved |
| `profit_protection_stop` | `26 / +170,652.73` | `25 / +164,302.69` | Slightly lower |
| `trend_break` | `5 / -17,050.99` | `2 / -8,806.49` | Improved |
| `rotation_for_stronger_signal` | `11 / -5,152.90` | `11 / +2,374.85` | Improved path |
| `fragile_structure_stop` | `8 / -47,011.67` | `7 / -43,793.80` | Slightly improved |

The loss reduction is real but small. It mostly comes from changed path / fewer support stops, not from many direct contextual exits.

## Trigger Detail

Only one direct new sell occurred:

| Date | Symbol | Name | Reason | PnL |
| --- | --- | --- | --- | ---: |
| `2025-12-10` | `600115.SSE` | 中国东航 | `contextual_failed_launch_exit_stop` | `-2,769.91` |

This confirms plan A is currently too conservative to materially address the failed-launch problem.

## Focus Symbols

The experiment did not change the key user-named failure paths:

| Symbol | Baseline Path | Experiment Path | Result |
| --- | --- | --- | --- |
| `601179.SSE` | `2026-02-03` buy, `2026-02-06` support stop, `-9,670.55` | Same | Not fixed |
| `600352.SSE` | `2026-03-12` buy, `2026-03-16` support stop, `-8,558.37` | Same | Not fixed |
| `002240.SZSE` | `2026-03-12` buy, `2026-03-19` support stop, `-9,643.23` | Same | Not fixed |
| `002443.SZSE` | `2026-05-14` buy, `2026-06-04` support stop, `-4,917.97` | Same | Not fixed; this remains a profit-giveback/sell-point sample |
| `002119.SZSE` | `2026-02-06` buy, `2026-02-10` support stop, `-1,555.15` | Same | Not fixed |
| `002384.SZSE` | same March/May/June path except final open position may differ by path capacity | Same closed path | Not fixed |

## Market / Candidate Audit Summary

`#211` setup-market-exit audit:

- Overall closed trades: `209`; win rate about `34.45%`; average return about `+3.35%`; median return `-4.06%`.
- Entry setup split: `dragon_pullback` win rate `33.85%`, `stealth_low_suction` win rate `35.44%`.
- Dynamic market split: `choppy_rotation` win rate `34.72%`, `false_bull` win rate `35.29%`, `strong_broad` win rate `28.57%`.
- Failed launch count remains high: `82` in the audit summary.

Top-10 audit for `#211`:

- Real closed top-10 evaluated count is small (`31`), win rate about `38.71%`.
- Excluding strong market, real closed top-10 win rate is about `40.00%`.
- Fixed 20-trading-day candidate observation is broader: observed top candidates `1406`, win rate about `45.73%`; excluding strong market win rate about `46.61%`.

This does not show a durable top-candidate improvement versus baseline; it mainly confirms the existing need to separate real portfolio trades from fixed-horizon candidate observation.

## Decision

Do not promote this switch to default. Keep `enable_contextual_failed_launch_exit_stop=false`.

Reasoning:

- It did not improve total return: `+82.56%` vs baseline `+82.99%`.
- It slightly reduced max drawdown: `-15.53%` vs `-15.59%`, but the improvement is too small.
- It improved win rate / PF slightly, but direct trigger count was only `1`, so the evidence is not stable.
- It did not fix the main focus stocks (`601179.SSE`, `600352.SSE`, `002240.SZSE`, `002443.SZSE`, `002119.SZSE`).
- The first implementation exposed a performance risk when replacement scanning is applied to theoretical signal events; this has been corrected, but it reinforces that replacement-aware exits must stay narrow.

## Next Work

A useful next experiment should not just require a replacement candidate. It should first make the failed-launch classifier stronger on signal-day-visible and holding-path-visible evidence:

- Add a read-only / default-off context split for `low_suction_confirmed_failed_follow`, `weak_reclaim_after_entry`, `market_not_recovered`, and `replacement_quality_available`.
- For failed launches, test an earlier exit only when the position itself has failed to reclaim MA/support and the market context is not recovering.
- For `002443.SZSE`, use a separate profit-giveback rule; this experiment is not designed to solve that sample.
- Before more full runs, rebuild early 2025 candidate cache. Current cache covers only `2025-09-17..2026-06-17`, so `2025-03-26..2025-09-16` still needs `121` computed score days and full experiments are slower than necessary.
