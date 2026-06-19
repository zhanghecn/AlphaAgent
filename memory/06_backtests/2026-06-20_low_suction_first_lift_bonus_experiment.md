# Low-suction First-lift And Market-adaptive Scoring Experiments

Date: 2026-06-20

## Objective

This report records the follow-up default-off experiments after the low-suction / dragon-pullback boundary audit. The user hypothesis was:

- low-suction buildup should not be marked as a buy every day;
- after a long buildup, the first clean lift should become the stronger executable signal;
- the market regime should influence whether the strategy prefers low-suction first lift or classic dragon-pullback.

The implementation kept one public strategy, `mainline_dragon_pullback / 0.1.21`, and added only research switches. No switch is enabled by default.

## Baseline

Product baseline remains `#203/#194`.

- Range: `2025-03-26..2026-06-18`.
- Execution: `legacy_next_open`, signal visible at daily close, execution at next daily open.
- Portfolio: BUY candidates top `20`, max positions `10`.
- Return: `+82.99%`.
- Win rate: `32.24%`.
- Max drawdown: `-15.59%`.
- Profit factor: `1.676`.
- Buy / sell / open: `224 / 214 / 10`.

## Experiments

| Run | Switch / Params | Return | Win Rate | Max DD | Decision |
| --- | --- | ---: | ---: | ---: | --- |
| `#221` | `enable_market_adaptive_setup_weighting=true` | `+38.72%` | `31.96%` | `-23.68%` | Reject |
| `#222` | `enable_contextual_failed_launch_exit_stop=true`, `rotation_min_score_gap=6` | `+55.26%` | `31.67%` | `-17.83%` | Reject |
| `#224` | `enable_low_suction_first_lift_bonus=true` | `+34.83%` | `29.03%` | `-23.93%` | Reject |

## Result

All three experiments failed the promotion gate.

`#221` proved that market-adaptive setup weighting is too broad as a direct ranking rule. It tries to rotate preference between low-suction first lifts and classic dragon-pullback by regime, but it changes the portfolio path too much and suppresses high-payoff trend opportunities.

`#222` showed that loosening the replacement gap around the otherwise best failed-launch experiment is harmful. The earlier `#211` kept `rotation_min_score_gap=8` and nearly matched the baseline, but lowering it to `6` allowed weaker replacements and reduced return materially.

`#224` tested the narrowest buy-side hypothesis: give a small score bonus only to a clean first lift after low-suction buildup. The semantics are correct, but the ranking change still displaces too many stronger later portfolio opportunities. It reduced both return and win rate, and worsened drawdown.

## Anti-future-function Review

The buy-side scoring experiments use only signal-day visible evidence:

- setup type and low-suction days calculated from bars up to the signal date;
- launch quality bucket calculated from the signal-day candle, volume and moving averages;
- market regime fields already attached as read-only signal-day context;
- no fixed-horizon return, future MFE/MAE, post-entry follow-through or post-exit rebound is used for ranking.

The experiments are therefore not future-function failures. They are portfolio-path failures.

## Interpretation

The important conclusion is not that the low-suction first-lift idea is wrong. The read-only audit still shows that `低吸首个均衡上拉` is much better than pure buildup. The problem is using that observation as a direct portfolio score bonus across the whole market.

The current strategy return depends on a small number of high-payoff trend/dragon-pullback winners. Even a small direct score adjustment can change the top-20 execution pool, full-position replacement chain and later buy sequence. These experiments confirm that the next improvement should prioritize:

- sell-side / hold-side path classification;
- replacement quality after any sell;
- preventing weak failed launches without suppressing trend winners;
- keeping market and low-suction labels as explanation and audit fields until a narrower rule proves better globally.

## Decision

Do not promote any of these switches:

- keep `enable_market_adaptive_setup_weighting=false`;
- keep `enable_low_suction_first_lift_bonus=false`;
- keep `rotation_min_score_gap=8.0` for the product baseline;
- keep `enable_contextual_failed_launch_exit_stop=false`.

The best near-miss remains `#211`, not because it should be enabled, but because it shows the right constraint: exits and replacements must be path-aware and replacement-quality-aware. Direct low-suction / dragon-pullback score reshuffling is currently too destructive.

## Verification

The code-level switches are present as default-off research parameters and are excluded from product baseline selection. Final verification for the current workspace is tracked in the task close-out rather than this report.
