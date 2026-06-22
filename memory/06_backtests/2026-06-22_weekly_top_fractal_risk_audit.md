# Weekly Top Fractal Risk Audit

Date: 2026-06-22

Purpose: verify whether `weekly_top_fractal_risk` hurts or helps candidate quality before changing the strategy.

## Method

- No strategy change.
- Candidate quality uses the unified no-position path:
  - signal visible at D close,
  - independent D+1 open entry,
  - current sell logic for exit,
  - no cash, max-position, full-position, holding, or replacement constraints.
- Two checks were run:
  - current-code quick window: `2026-02-13..2026-06-18`, `max_symbols=120`;
  - persisted `mainline_dragon_pullback / 0.1.21` recommendations: `2025-08-06..2026-06-18`, Top10/Top20/Top100.
- A counterfactual persisted rerank added back the `4` point weekly-top-fractal penalty to flagged rows, then reselected daily Top20 from persisted Top100.

## Findings

Current-code quick Top20 (`max_symbols=120`):

- All Top20: win rate `19.76%`, average return `-2.3281%`, average max drawdown `-6.3516%`.
- `weekly_top_fractal_risk=true`: `50` samples, win rate `32.00%`, average return `+1.0255%`, average max drawdown `-6.1017%`.
- `weekly_top_fractal_risk=false`: `1124` samples, win rate `19.22%`, average return `-2.4772%`, average max drawdown `-6.3627%`.

Persisted `0.1.21` Top20:

- All Top20: `3580` evaluated, win rate `32.43%`, average return `+1.5762%`, average max drawdown `-6.9079%`.
- `weekly_top_fractal_risk=true`: `154` evaluated, win rate `36.36%`, average return `+1.5916%`, average max drawdown `-6.8477%`.
- `weekly_top_fractal_risk=false`: `3426` evaluated, win rate `32.25%`, average return `+1.5755%`, average max drawdown `-6.9107%`.

Persisted `0.1.21` Top100:

- `weekly_top_fractal_risk=true`: `975` evaluated, win rate `30.67%`, average return `+0.7838%`, average max drawdown `-6.8309%`.
- `weekly_top_fractal_risk=false`: `15386` evaluated, win rate `31.24%`, average return `+0.4610%`, average max drawdown `-6.1317%`.

Counterfactual daily Top20 rerank from persisted Top100:

- Current with penalty: win rate `32.43%`, average return `+1.5762%`, average max drawdown `-6.9079%`.
- Add back `+2` to flagged rows: win rate `33.04%`, average return `+2.0542%`, average max drawdown `-7.0667%`.
- Add back full `+4` to flagged rows: win rate `32.99%`, average return `+1.9692%`, average max drawdown `-7.0727%`.

## Conclusion

`weekly_top_fractal_risk` should not be treated as a hard bad-candidate factor. In Top20, flagged candidates have at least comparable and often better return/win-rate quality, but with a slightly fatter loss tail and worse drawdown after reranking more of them into the pool.

The safer optimization direction is not deleting the factor. Prefer a default-off ranking experiment that partially relaxes the `4` point penalty for strong-trend, well-supported dragon-pullback candidates while keeping or tightening it for low-suction/high-close/weak-confirmation cases.

## Follow-up Fix

This audit exposed a deeper stability issue: `_weekly_bars()` previously grouped daily bars by fixed 5-row windows from the loaded lookback start, so `weekly_top_fractal_risk` could change when the backtest/screening lookback start changed. It is now grouped by ISO calendar week.

For `000725.SZSE` on `2026-06-15`, the factor is stable across different lookback starts and no longer has `weekly_top_fractal_risk`; current full-market recomputation ranks it about `#13` with score `95.1727`.

Quick matrix after the calendar-week fix (`2026-02-13..2026-06-18`, `max_symbols=120`, Top20):

- default: average return `-2.3216%`, win rate `19.88%`, average max drawdown `-6.3531%`;
- `weekly_relief`: no additional change versus default in this quick sample;
- tail-only: small improvement to `-2.3122% / 19.88% / -6.3362%`;
- momentum-only still worsens return and drawdown despite a win-rate lift.

Decision: keep the calendar-week fix. Keep `enable_weekly_top_fractal_relief` default-off and do not promote it based on this quick sample.
