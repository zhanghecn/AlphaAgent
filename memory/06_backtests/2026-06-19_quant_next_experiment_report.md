# Quant Next Experiment Report

## Baseline

- Product baseline: `#203/#194`
- Strategy: `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26..2026-06-18`
- Execution: `legacy_next_open`
- Metrics: return `+82.99%`, max drawdown `-15.59%`, win rate `32.24%`, profit factor `1.676`, Sharpe `2.383`, buy/sell/open `224 / 214 / 10`
- Baseline API after experiments still returns only `#203/#194` for `baseline_only=true`.

## Experiments

All four experiments were run as default-off research switches. None is eligible for default promotion.

| Run | Switch | Return | Max DD | Win Rate | PF | Sharpe | Buy/Sell/Open | Conclusion |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `#203/#194` | baseline | `+82.99%` | `-15.59%` | `32.24%` | `1.676` | `2.383` | `224 / 214 / 10` | Current product baseline |
| `#214` | `enable_contextual_support_reclaim_delay` | `+35.15%` | `-19.36%` | `30.98%` | `1.193` | `1.249` | `194 / 184 / 10` | Reject |
| `#215` | `enable_contextual_peak_giveback_stop` | `+49.07%` | `-20.12%` | `29.30%` | `1.263` | `1.582` | `225 / 215 / 10` | Reject |
| `#216` | `enable_low_suction_false_launch_watch_gate` | `+52.09%` | `-26.46%` | `29.25%` | `1.299` | `1.617` | `222 / 212 / 10` | Reject |
| `#217` | `enable_missed_candidate_quality_rotation` | `+49.28%` | `-24.18%` | `31.10%` | `1.321` | `1.605` | `219 / 209 / 10` | Reject |

## Path Evidence

`#214` reduced `support_stop` count from `125` to `106`, but this did not improve the portfolio. Total return dropped by about `47.84` percentage points and max drawdown worsened by about `3.77` points. Setup audit shows replacement quality weakened: average replacement return changed from `+2.22%` in baseline to `-0.81%`, strong replacements fell from `42` to `25`, and bad replacements remained high at `90`.

`#215` produced `10` `contextual_peak_giveback_stop` sells, but the portfolio path still deteriorated. The run did not fix `002443.SZSE`; that stock was not bought in the changed path. The rule mostly changed portfolio composition and cut trend opportunity rather than only protecting high-profit giveback.

`#216` did not stop the named `600352.SSE` false launch: it still bought on `2026-03-12` and sold by `support_stop` on `2026-03-16`. It also introduced an earlier losing `002240.SZSE` trade in January. Top10 audit weakened from `52.17%` win rate and `+14.66%` average return in baseline to `41.67%` and `+10.95%`.

`#217` strengthened missed-candidate rotation but worsened return and drawdown. Top10 audit weakened from `52.17%` to `44.44%`; weak-market average Top10 return fell from about `+10.13%` to `+3.62%`. This confirms that missed good candidates are real, but the current replacement rule sells too many valuable holdings or changes the path into weaker trades.

## Focus Symbols

| Symbol | Baseline Path | Experiment Result |
| --- | --- | --- |
| `600352.SSE` | `2026-03-12` BUY, `2026-03-16` `support_stop`, about `-8558` | `#216/#217` still buy/sell the same failed launch; false-launch gate did not catch it. |
| `002240.SZSE` | `2026-03-12` BUY, `2026-03-19` `support_stop`, about `-9643` | `#215/#217` reduce the March loss, but `#216/#217` add a January fragile-structure loss. Net path not improved. |
| `002384.SZSE` | March profitable support stop, May losing support stop, June open buy | Experiments change timing but do not solve the original full-position/theoretical-holding execution gap. |
| `601179.SSE` | `2026-02-03` early buy, `2026-02-06` `support_stop`, about `-9671` | `#214` delays to `2026-02-09` and reduces loss, but global portfolio damage is much larger. |
| `002443.SZSE` | `2026-05-14` BUY, `2026-06-04` `support_stop`, about `-4918` | `#214/#215/#216/#217` do not hold this baseline trade, so they cannot claim to fix its high-profit giveback path. |

## Future Function And Overfit Review

- No experiment used fixed-horizon outcome, MFE/MAE labels, or post-exit rebound as signal-day scoring input.
- Sell rules use visible holding path and sell-day bars. However, some market/risk values are read from `position.reason`, which stores entry-day context rather than dynamically recomputed sell-day context. This is not a future function, but it weakens the logic as a dynamic sell model.
- The failed results show high overfit risk for simple hard filters: named losers can improve locally, but portfolio replacement quality and trend-winner opportunity cost dominate.

## Conclusion

Reject all four switches for default strategy:

- Keep `enable_contextual_support_reclaim_delay=false`.
- Keep `enable_contextual_peak_giveback_stop=false`.
- Keep `enable_low_suction_false_launch_watch_gate=false`.
- Keep `enable_missed_candidate_quality_rotation=false`.

The remaining useful direction is not to turn on these rules, but to refine signal-day factor definitions and sell-day dynamic context:

- Low suction false launch must identify weak first-lift before buying `600352.SSE`, not broadly block low-suction context.
- High-profit giveback must act on the same held trade, not change earlier portfolio path and then miss the target trade.
- Missed-candidate rotation needs a stricter replacement-quality model before it can sell existing holdings.
- Support-stop delay needs true sell-day market/support recomputation and a stronger guard against bad replacement paths.
