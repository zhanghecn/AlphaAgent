# Top20 Fixed Holding Path Audit

Date: 2026-06-22

## Scope

- Source: persisted `quant_recommendations` for `mainline_dragon_pullback / 0.1.21`.
- Candidate set: BUY rows with `rank <= 20`.
- Range: `2025-08-06..2026-06-18`.
- Rows: `3600` candidate rows; `3580` had a D+1 execution bar.
- Entry model: D signal date close-visible candidate, D+1 daily open entry.
- Measurement: fixed close path after entry. `entry_day_close` is the D+1 execution-day close; `hold2_close` is the second holding-day close. This is an audit-only hindsight label and is not used for scoring, buy, sell or position sizing.

## Overall Path

| Horizon | Win Rate | Avg Return | Median | P25 | P75 | Loss Rate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| entry-day close | `48.72%` | `+0.3092%` | `-0.0209%` | `-1.8657%` | `+2.0988%` | `51.28%` |
| hold 2 close | `48.52%` | `+0.3846%` | `-0.1158%` | `-3.0714%` | `+3.1026%` | `51.48%` |
| hold 3 close | `48.88%` | `+0.5051%` | `-0.1167%` | `-3.9714%` | `+4.1392%` | `51.12%` |
| hold 5 close | `46.54%` | `+0.8534%` | `-0.6242%` | `-5.3382%` | `+5.4545%` | `53.46%` |
| hold 10 close | `47.40%` | `+1.7988%` | `-0.7687%` | `-7.2881%` | `+7.6271%` | `52.60%` |
| hold 20 close | `46.37%` | `+3.1133%` | `-1.3572%` | `-9.7806%` | `+10.4286%` | `53.63%` |

Drawdown path:

| Horizon | Avg MAE | Median MAE | Worst MAE |
| --- | ---: | ---: | ---: |
| hold 5 | `-5.7844%` | `-4.7552%` | `-33.8290%` |
| hold 20 | `-10.3857%` | `-9.1130%` | `-50.3599%` |

## Interpretation

The user's concern is valid. The Top20 candidate set is not "next-day high win-rate" stable:

- Entry-day and hold-2 close win rates are both below `50%`.
- Median return stays negative from entry day through hold 20.
- Longer holding improves average return only because a right tail of large winners pulls the mean up.
- Typical candidate experience remains loss-prone, and drawdown expands materially when held longer.

This explains the mismatch between average-return reports and real trading feel: the pool has right-tail payoff, but the ordinary candidate often goes red quickly and can stay underwater.

## Rank Quality

| Rank Window | N | Hold2 Win | Hold2 Avg | Hold2 Median | Hold20 Win | Hold20 Avg | Hold20 Median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1-5 | `928` | `50.65%` | `+0.6994%` | `+0.0698%` | `49.46%` | `+6.3876%` | `-0.2913%` |
| 6-10 | `894` | `48.55%` | `+0.4779%` | `-0.0463%` | `47.54%` | `+3.0112%` | `-0.7440%` |
| 11-15 | `883` | `48.92%` | `+0.2678%` | `-0.0907%` | `43.71%` | `+1.7143%` | `-1.8578%` |
| 16-20 | `875` | `45.83%` | `+0.0735%` | `-0.4149%` | `44.57%` | `+1.1568%` | `-1.9257%` |

The first five ranks are materially better than ranks `16-20`, but even ranks `1-5` have negative hold-20 median. Top20 quality weakens as ranks expand, so the next optimization should target marginal rank `11-20` and bad interaction buckets instead of simply buying wider.

## Weak Buckets

Bad near-term / path buckets with at least 30 samples:

| Bucket | N | Hold2 Win | Hold2 Avg | Hold20 Win | Hold20 Avg | Hold20 Median | Avg Hold20 MAE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `thin_volume_launch + high close` | `106` | `41.51%` | `-0.7713%` | `39.62%` | `-1.8563%` | `-1.8760%` | `-8.8779%` |
| `high_close_launch + normal volume` | `264` | `47.35%` | `-0.1773%` | `38.64%` | `-0.7133%` | `-2.4972%` | `-8.9475%` |
| `repeated_launch + high close` | `219` | `45.21%` | `-0.1813%` | `42.92%` | `+2.2933%` | `-3.1289%` | `-10.0759%` |
| `unconfirmed_buildup + normal volume` | `161` | `45.96%` | `-0.3745%` | `42.86%` | `+4.1881%` | `-2.4341%` | `-11.4667%` |
| `not_low_suction + expanded volume` | `108` | `45.37%` | `+0.6449%` | `35.19%` | `-0.0577%` | `-5.3717%` | `-11.4322%` |
| `choppy_rotation + thin_volume_launch + high close` | `78` | `46.15%` | `-0.7810%` | `38.46%` | `-2.3157%` | `-3.1953%` | `-9.5909%` |
| `choppy_rotation + unconfirmed_buildup + middle close` | `65` | `43.08%` | `-0.7127%` | `35.38%` | `+0.1134%` | `-2.8551%` | `-10.8544%` |
| `strong_broad + high_close_launch + high close` | `31` | `48.39%` | `-0.9136%` | `35.48%` | `-4.8166%` | `-9.8961%` | `-12.1713%` |

Working interpretation:

- High close is not automatically strength. When paired with weak volume, repeated launch, or weak/choppy market context, it often means the entry is already crowded.
- Some "confirmed" or repeated launches still lack follow-through. They need context, not blanket promotion.
- Marginal ranks `11-20` are much weaker than `1-5`; a Top20 pool can have positive mean while still producing poor ordinary trade experience.

## Stronger Buckets

Useful contrast buckets:

| Bucket | N | Hold2 Win | Hold2 Avg | Hold20 Win | Hold20 Avg | Hold20 Median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `rank 1-5` | `928` | `50.65%` | `+0.6994%` | `49.46%` | `+6.3876%` | `-0.2913%` |
| `not_low_suction + low close` | `442` | `50.68%` | `+0.9579%` | `51.81%` | `+5.5903%` | `+0.4241%` |
| `false_bull + low close` | `153` | `46.41%` | `+0.8203%` | `58.82%` | `+10.7512%` | `+5.9145%` |
| `late_pullback_launch + thin volume` | `285` | `46.67%` | `+0.4486%` | `52.28%` | `+1.8726%` | `+0.6218%` |
| `weekly_top_fractal_risk` | `154` | `50.00%` | `+1.1590%` | `53.25%` | `+3.2656%` | `+1.5550%` |

The stronger buckets support a narrower idea: prefer better asymmetry and context, not more generic buy signals. `weekly_top_fractal_risk` again does not appear to be a bad label by itself.

## Worst Hold2 Examples

| Date | Symbol | Rank | Score | Entry Day | Hold2 | Hold20 | Regime | Launch | Close | Volume | MA |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `2026-05-29` | `003018.SZSE` | 9 | `94.62` | `-10.1615%` | `-19.1379%` | `-2.3552%` | false_bull | not_low_suction | low | normal | >10 |
| `2026-03-27` | `600722.SSE` | 9 | `94.33` | `-9.3904%` | `-18.3416%` | `-28.0615%` | choppy_rotation | not_low_suction | low | normal | >10 |
| `2026-03-24` | `600590.SSE` | 7 | `97.17` | `-12.1019%` | `-17.2611%` | `+10.0000%` | choppy_rotation | unconfirmed_buildup | middle | normal | 3-6 |
| `2026-05-28` | `002222.SZSE` | 2 | `98.34` | `-8.5818%` | `-16.9636%` | `-6.3636%` | false_bull | unconfirmed_buildup | high | normal | 6-10 |
| `2026-03-16` | `600860.SSE` | 13 | `95.73` | `-10.2839%` | `-16.6562%` | `-25.1104%` | choppy_rotation | not_low_suction | high | normal | 6-10 |

These are not low-score random names. They show that high score alone does not guarantee immediate follow-through. Some recover later, but often only after deep MAE, so they are poor candidates for a high-win-rate Top20 unless entry confirmation or risk demotion improves.

## Next Test Hypotheses

Do not promote a strategy change from this report alone. The next default-off tests should be narrow:

1. Top20 marginal-rank quality gate:
   - More severe demotion for rank-eligible rows in `11-20` when they also have weak launch/close/volume context.
   - Compare against same-day Top20 candidate acceptance, not portfolio cash.

2. High-close weak-follow-through demotion:
   - Penalize `high_close_launch`, `thin_volume_launch + high close`, `repeated_launch + high close`, and `unconfirmed_buildup + normal volume` only when market context is weak/choppy or MA/volume evidence is not supportive.

3. Delayed follow-through entry experiment:
   - Signal D remains visible at D close.
   - Do not enter at D+1 open immediately; enter at D+2 open only if D+1 did not break support/key low and close/volume are not weak.
   - This must be treated as a different entry model, because D+1 close cannot be used for a D+1 open buy. Compare avoided losers versus missed right-tail winners.

4. Keep `weekly_top_fractal_risk` out of the bad-bucket list:
   - It does not explain the low next-day win rate. The calendar-week fix stays; weekly relief remains default-off.
