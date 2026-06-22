# Candidate Factor Surge And Decline Analysis

Date: 2026-06-22

## Scope

- Source run: clean no-cache analysis backtest `#275`, `mainline_dragon_pullback / 0.1.21`.
- Range: `2025-08-06..2026-06-18` for persisted factor snapshots/outcomes.
- Candidate set: daily Top20, rank `1..20`.
- Rows: `3,751` ready Top20 candidate rows, plus `2,889` cluster-first rows after merging consecutive same-stock candidate repeats.
- Entry/outcome labels: D signal date is visible at close; D+1 open is the audit entry. Fixed-horizon `return/mfe/mae` labels are future-data analysis only and must not enter scoring directly.
- Raw evidence: `2026-06-22_candidate_factor_surge_decline_analysis.json`.

## Main Finding

Top20 is not completely ineffective, but its payoff is right-tail driven:

| Sample | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | MAE <= -5% | Loss First |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Raw Top20 | 3,751 | `+2.30%` | `-0.46%` | `47.88%` | `49.29%` | `62.01%` | `59.26%` |
| Cluster first entries | 2,889 | `+1.69%` | `-0.73%` | `47.14%` | `48.98%` | `62.37%` | `59.16%` |

Interpretation:

- Average return is positive because a minority of large movers pulls the mean up.
- The ordinary candidate still tends to go red first, and the median 10-day return is negative.
- This matches the trading feel: second-day and short-hold win rates are not stable enough, and long holding often increases drawdown before the right-tail winner appears.

## Strict Executable Top20 Recheck

A stricter recheck used only rows that were true daily Top20 executable BUY candidates:

- Source: `backtest_factor_snapshots/outcomes` for `#275`.
- Filters: rank `1..20`, `entry_action=BUY`, `executable_entry_signal=true`.
- Evaluated rows: `3,580`, signal dates `196`, range `2025-08-06..2026-06-17`.
- Entry model remains D signal close visible, D+1 open audit entry.

| Metric | Value |
| --- | ---: |
| Avg 3D return | `+0.61%` |
| Avg 10D return | `+1.98%` |
| Median 10D return | `-0.60%` |
| 10D win rate | `47.54%` |
| Avg 20D return | `+3.09%` |
| Avg 10D MFE | `+12.52%` |
| Avg 10D MAE | `-8.24%` |
| Quick surge rate | `33.13%` |
| MFE >= 8% within 10D | `49.58%` |
| Pure loss: MFE < 3% and 10D return < 0 | `23.88%` |
| Failed launch | `27.91%` |
| MFE >= 8% but 10D return <= 0 | `12.01%` |
| First hit -3% before +5% | `59.47%` |

This confirms the core problem more precisely:

- Almost half of candidates can produce an 8% runup within 10 trading days.
- But nearly one quarter never reach even 3% MFE and still lose.
- About 12% give a tradable right-side runup and then hand it back.
- About 59% hit a -3% adverse move before hitting +5%, so immediate D+1 open entry is structurally uncomfortable even when the pool has positive right-tail expectancy.

## Short-Hold Path

The same strict Top20 executable set was measured from D+1 open to the next closes:

| Horizon | Avg | Median | Win Rate |
| --- | ---: | ---: | ---: |
| D+1 close | `+0.30%` | `-0.05%` | `48.50%` |
| D+2 close | `+0.38%` | `-0.14%` | `48.45%` |
| D+3 close | `+0.50%` | `-0.13%` | `48.81%` |

Additional labels:

- Early strong: D+1 close `>=3%` or D+2 close `>=5%`: `25.51%`.
- Early weak: D+1 close `<=-3%` or D+2 close `<=-5%`: `20.79%`.

Rank quality appears immediately:

| Rank | D+1 Avg / Win | D+2 Avg / Win | D+3 Avg / Win |
| --- | ---: | ---: | ---: |
| `1-5` | `+0.46% / 51.09%` | `+0.68% / 50.33%` | `+0.91% / 50.87%` |
| `6-10` | `+0.24% / 48.53%` | `+0.45% / 48.30%` | `+0.37% / 49.77%` |
| `11-15` | `+0.37% / 51.09%` | `+0.29% / 49.26%` | `+0.35% / 47.42%` |
| `16-20` | `+0.12% / 43.12%` | `+0.07% / 45.78%` | `+0.35% / 47.05%` |

Short-path factor buckets:

| Bucket | D+2 Avg / Win | D+3 Avg / Win | Note |
| --- | ---: | ---: | --- |
| `active + mid/lower close + wide MA` | `+0.93% / 50.38%` | `+1.13% / 52.31%` | Best near-term follow-through bucket. |
| `0.35-0.58 lower_mid close` | `+0.87% / 50.33%` | `+0.76% / 50.76%` | Better asymmetry than high close. |
| `<0.35 low close` | `+0.84% / 51.38%` | `+1.02% / 52.07%` | Pullback asymmetry helps but drawdown can still be deep. |
| `>0.75 high close` | `-0.09% / 45.72%` | `-0.06% / 44.95%` | Crowded entry; poor immediate follow-through. |
| `high close + weak launch` | `-0.14% / 46.27%` | `-0.22% / 44.10%` | Clear short-term drag. |
| `low_suction_days 6-10` | `-0.07% / 46.09%` | `+0.07% / 45.72%` | Stale buildup has weak immediate lift. |
| `stale low-suction without active money` | `-0.11% / 46.39%` | `+0.10% / 45.53%` | Low early strong rate `13.10%`. |
| `MA convergence <3 tight` | `-0.18% / 46.27%` | `-0.05% / 44.82%` | Too quiet; does not mean imminent launch. |

Interpretation:

- 猛拉 is often not a simple "break above MA5" event. It usually appears when active-money evidence already exists, then price sits in a mid/lower close-location zone with enough MA spread to still have trend energy.
- 一买就弱 often comes from high-close/weak-launch combinations, stale low-suction, or tight quiet structures that have not shown fresh activation.
- Long low-suction should not be blindly punished, but stale `6-10` day low-suction without active evidence should stop receiving large opportunity credit.
- D+2 follow-through is a plausible default-off entry experiment because D+1/D+2 weakness is measurable, but it must be modeled as a different execution model, not as a D+1 open scoring rule.

## Strict Drilldown Addendum

After the first report, a stricter read-only drilldown queried `backtest_factor_snapshots` and
`backtest_factor_outcomes` for `#275` directly inside the `alphaagent-api` container. Filters were:
rank `1..20`, `entry_action=BUY`, `executable_entry_signal=true`, outcome `status=ready`.
This excludes old `rank=0` snapshot artifacts and keeps only executable Top20 candidates.

| Sample | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | Pure loss | MFE>=8 then <=0 | Loss first |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Strict raw Top20 | `3,580` | `+1.98%` | `-0.60%` | `47.54%` | `49.58%` | `23.88%` | `12.01%` | `59.47%` |
| Cluster-first | `3,134` | `+1.66%` | `-0.73%` | `47.16%` | `49.11%` | `23.90%` | `12.19%` | `59.22%` |

Interpretation:

- Removing same-stock consecutive repeats lowers average return, so repeated right-tail winners are
  inflating the raw mean.
- Median and loss-first barely improve after cluster-first merging. The issue is not only repeated
  samples; ordinary Top20 candidates still tend to go red first.
- Candidate quality and sell/profit protection are separate: about half the pool reaches meaningful
  MFE, but roughly one eighth gives back an `>=8%` runup to non-positive 10-day return.

Visible-condition diagnostics, using only signal-day factors:

| Condition | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | Pure loss | Giveback |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Active + low/lower-mid close + MA `3..18` + near MA5 | `534` | `+3.22%` | `+0.79%` | `51.31%` | `59.55%` | `17.60%` | `14.79%` |
| High close + weak launch | `741` | `+0.45%` | `-1.36%` | `43.99%` | `39.41%` | `30.77%` | `9.04%` |
| Stale low-suction without active money | `471` | `-0.13%` | `-1.32%` | `43.10%` | `30.15%` | `35.67%` | `4.88%` |
| Tight quiet structure without active money | `364` | `+0.08%` | `-0.93%` | `43.13%` | `25.00%` | `37.91%` | `3.30%` |

This sharpens the earlier conclusion:

- 猛拉 does not mean "any recent strength"; it is strongest when active money is still in a
  low/lower-mid disagreement area and has not moved too far from MA5.
- 候选买后下跌 is most often a crowding/staleness problem: high-close weak launch, stale
  low-suction without fresh activation, or very tight quiet structures that have not actually
  started.
- 低吸蓄势 should not be punished just because it has been quiet. The penalty should focus on
  `6-10` day stale buildup without active-money evidence or fresh lift.

Same-day candidate-pool composition was also tested. Broadly filtering `false_bull` is wrong:
`2026-06-03` was `false_bull/w3` but had strict Top20 average 10D `+21.71%`, win rate `90%`,
active candidates `90%`, low/lower-mid close `60%`, high close only `15%`, weak launch only `5%`.
The weaker day signature is more specific:

| Day condition | Approx days | Candidates | Avg 10D | Median 10D | Win 10D | Pure loss |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Active `>=55%`, high close `>=55%`, weak launch `>=45%` | `11` | `220` | `-1.79%` | `-4.76%` | `33.18%` | `29.55%` |
| Active `>=65%`, low/lower-mid `>=35%`, high close `<=25%`, weak launch `<=15%` | `6` | `120` | `+9.58%` | `+3.43%` | `68.33%` | `14.17%` |

This points to a day-level quality feature for the test channel: do not simply label a day by
`false_bull` or warning level. Instead, judge whether that day's Top20 is concentrated in active,
lower-mid, low-weak-launch candidates or crowded in active high-close weak-launch candidates.

## When Candidates Tend To Surge

The strongest surge candidates usually have visible recent activity, not just quiet low-suction:

- `dragon_pullback` has higher 10-day average return and surge rate than `low_position_reclaim`: `+2.90%` average 10D and `56.42%` MFE>=8%, but with deeper average MAE `-9.11%`.
- Recent active winners matter:
  - `large_bull_count_20d = 3-4`: `+4.03%` average 10D, `57.05%` MFE>=8%, median `+0.63%`.
  - `large_bull_count_20d >= 5`: `+4.67%` average 10D, `61.08%` MFE>=8%, but average MAE worsens to `-10.67%`.
  - `recent_limit_up_20d=true`: stronger surge/return than no recent limit-up, but also higher drawdown.
- Close location is important:
  - `0.35-0.58 lower_mid`: `+3.85%` average 10D, median `+0.52%`, `58.82%` MFE>=8%, failed-launch `20.20%`.
  - `>0.75 high`: only `+1.35%` average 10D, median `-1.07%`, failed-launch `32.85%`.
- MA convergence is not linear:
  - Wide MA in active dragon/momentum names often means a live trend, not necessarily a bad setup.
  - `>14 very_wide`: `+4.43%` average 10D and `62.25%` MFE>=8%, but average MAE `-9.82%`.
  - `<3 tight`: only `+0.47%` average 10D and `27.37%` MFE>=8%, failed-launch `37.86%`.

Strong interaction buckets:

| Bucket | N | Avg 10D | Median 10D | MFE >= 8% | Failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| `10-14 wide MA + lower_mid close` | 151 | `+5.27%` | `+2.61%` | `65.56%` | `16.56%` |
| `large_bull 3-4 + lower_mid close` | 146 | `+4.74%` | `+1.22%` | `63.70%` | `22.60%` |
| `active + mid/lower close + wide MA` custom bucket | 473 | `+4.49%` | `+0.29%` | `63.21%` | `20.30%` |
| `low_suction 3-5 days + balanced close + warning<=1` custom bucket | 237 | `+3.49%` | `+0.81%` | `54.85%` | `24.05%` |

Concrete strong samples:

- `605255.SSE 天普股份`: repeated extreme winner, `dragon_pullback / not_low_suction`, recent limit-up true, large-bull count high, wide MA. It heavily pulls averages upward, so cluster-first analysis is necessary.
- `002083.SZSE 孚日股份` `2025-11-05`: `low_position_reclaim / repeated_launch`, recent limit-up true, MFE 10D `+133.22%`, MAE 10D `-0.67%`.
- `002636.SZSE 金安国纪` `2026-06-03`: `dragon_pullback / not_low_suction`, close location `0.527`, MA convergence `11.38`, recent limit-up true, return 10D `+108.82%`.
- `603773.SSE 沃格光电` `2026-05-22`: `dragon_pullback / not_low_suction`, close location `0.471`, large-bull count `7`, MFE 20D `+116.24%`.

## When Candidates Tend To Decline

Bad candidates are not mostly low-score random names. Many are high-score candidates where the score is rewarding strength but not sufficiently pricing failed follow-through.

Weak buckets:

| Bucket | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | Failed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `high_close_launch` | 307 | `-0.10%` | `-1.83%` | `41.04%` | `33.22%` | `39.09%` |
| `thin_volume_launch` | 166 | `+0.81%` | `-0.88%` | `46.39%` | `36.14%` | `39.76%` |
| `other_confirmed_launch` | 119 | `-0.23%` | `-0.62%` | `47.06%` | `40.34%` | `36.13%` |
| `low_suction_days 6-10` | 1,141 | `+0.72%` | `-0.88%` | `44.61%` | `35.23%` | `37.60%` |
| `high close + weak launch` custom bucket | 460 | `+0.74%` | `-1.43%` | `43.48%` | `45.65%` | `29.35%` |
| `long low-suction no recent limit-up` custom bucket | 769 | `+0.70%` | `-0.61%` | `45.64%` | `31.47%` | `39.66%` |
| `unknown family` | 226 raw / 122 cluster | raw avg `+0.58%` | raw median `-1.46%` | raw win `40.27%` | raw MFE>=8 `22.57%` | raw failed `44.69%` |

Worst samples:

- `600208.SSE 衢州发展` `2026-05-13`: high-score active dragon candidate, recent limit-up true, large-bull count `5`, MA convergence `28.13`; 10D return `-44.61%`, MAE `-45.91%`, failed launch. This shows strong-trend evidence alone cannot be blindly rewarded.
- `002560.SZSE 通达股份` `2026-05-06/08`: active dragon setup with recent limit-up, but 10D returns around `-40%`; wide MA and active history did not prevent breakdown.
- `001207.SZSE 联科科技` `2026-03-30/04-01`: `low_position_reclaim / late_pullback_launch`, high close (`0.97` / `0.78`), market warning `3/2`; 10D return about `-37% / -35%`, MFE near zero. This is a clear high-close late low-suction failure pattern.
- `605117.SSE 德业股份` `2026-05-18`: `dragon_pullback / high_close_launch`, close location `0.957`, weekly-top-fractal true, return 10D `-30.34%`.

## Same-Day Market Effect

Some candidate dates are broadly bad across the entire Top20, so this is not only a per-stock ranking problem.

- 185 candidate days had at least 10 ready Top20 rows.
- Only `60.00%` of candidate days had positive average 10-day Top20 return.
- Day-level median average 10D return is only `+1.02%`; p25 is `-2.52%`.
- Worst examples:
  - `2026-03-10`: Top20 avg 10D `-12.53%`, median `-14.40%`, win rate `10%`, MAE<=-5 rate `100%`.
  - `2026-03-11`: avg `-11.08%`, median `-16.72%`, win rate `20%`, loss-first `85%`.
  - `2026-05-13`: avg `-10.72%`, median `-8.36%`, win rate `15%`, loss-first `85%`.

Market labels help but are not sufficient alone:

| Regime / Warning | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | MAE <= -5% | Loss First |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `false_bull / 3` | 141 | `+9.84%` | `+2.92%` | `60.99%` | `57.45%` | `65.25%` | `65.25%` |
| `strong_broad / 0` | 590 | `+2.52%` | `-0.33%` | `48.31%` | `54.41%` | `64.41%` | `55.93%` |
| `choppy_rotation / 0` | 1,850 | `+2.30%` | `-0.53%` | `47.51%` | `50.38%` | `63.41%` | `59.51%` |
| `false_bull / 2` | 670 | `+1.34%` | `-0.86%` | `47.61%` | `42.09%` | `58.21%` | `58.36%` |
| `choppy_rotation / 2` | 160 | `+0.32%` | `-2.04%` | `40.63%` | `40.63%` | `61.88%` | `72.50%` |

Interpretation:

- `false_bull` is not always bad because some narrow speculative mainlines still run hard.
- The more useful rule is not "avoid false_bull"; it is "avoid weak launch/high-close/late low-suction unless there is fresh active-money evidence".
- Same-day Top20 collapse means the next experiment should include a market-day risk gate or delayed follow-through entry for high-risk buckets.

## Why Current Scoring Is Not Enough

The current default strategy mostly still uses base scoring. Several useful research switches are default-off and have not passed promotion.

Base dragon scoring rewards:

- relative strength;
- strong leg: recent 20/60-day return, large-bull count, near limit-up;
- pullback structure;
- MA support and reclaim;
- liquidity.

This explains why many high-score candidates can still be bad. They are genuinely strong or recently active, but the base score does not sufficiently separate:

- healthy active pullback vs late-stage collapse;
- lower-mid close with remaining asymmetry vs high close/crowded consensus;
- 3-5 day low-suction buildup vs 6-10 day stale low-suction;
- fresh trend activity vs long quiet compression without activation;
- a single-stock strong leg vs a same-day broad candidate failure.

Score bucket check:

| Score bucket | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | MAE <= -5% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `>=98` | 267 | `+4.39%` | `+1.27%` | `54.68%` | `61.05%` | `67.79%` |
| `96-98` | 535 | `+1.90%` | `-1.20%` | `46.36%` | `56.64%` | `72.71%` |
| `94-96` | 786 | `+2.29%` | `-1.34%` | `46.31%` | `53.05%` | `69.85%` |
| `92-94` | 642 | `+2.22%` | `-0.66%` | `47.82%` | `54.83%` | `65.89%` |
| `<90` | 1,101 | `+2.22%` | `-0.28%` | `48.41%` | `35.88%` | `48.50%` |

High score improves the right tail, but middle high-score buckets still have negative median returns and high drawdown rates. The problem is factor calibration, not only rank cutoff.

## Rank Cutoff

Top10 is better than ranks `11-20`, but Top10 alone does not solve the problem.

| Rank set | N | Avg 10D | Median 10D | Win 10D | MFE >= 8% | MAE <= -5% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Top10 | 1,903 | `+3.45%` | `-0.09%` | `49.40%` | `53.28%` | `64.27%` |
| Rank 11-20 | 1,848 | `+1.12%` | `-0.84%` | `46.32%` | `45.18%` | `59.69%` |

Across 185 candidate days, same-day Top10 average return beat ranks 11-20 only `57.30%` of the time. So the right fix is not simply "only buy Top10"; it is to improve factor discrimination inside Top20, especially marginal ranks and weak combinations.

## Hypotheses For The Next Default-Off Test

Do not promote a strategy change from this analysis alone. The next implementation should stay in the unified test channel and compare against the current/best baseline by same candidate dates.

1. Surge-quality lane, narrower than the first momentum lane:
   - Reward recent active evidence only when it has asymmetry:
     - recent limit-up or `large_bull_count_20d >= 3`;
     - close location preferably `0.35-0.75`, especially `0.35-0.58`;
     - MA dispersion may be wide for active momentum, but should be capped when close is extreme or same-day risk is high;
     - volume should be active but not exhaustion-like.
   - Do not broadly boost all recent limit-up / large-bull names.

2. Failed-launch / high-close risk penalty:
   - Penalize `high_close_launch`, `thin_volume_launch`, `other_confirmed_launch`, and `repeated_launch + high close` when no fresh active evidence offsets the risk.
   - Penalize `low_suction_days >= 6` without recent limit-up or clear fresh activation.
   - Penalize `late_pullback_launch + high close + market_warning >= 2`.
   - Penalize unknown setup family.

3. Same-day risk or delayed follow-through gate:
   - Because about `59%` of candidates hit loss first, immediate D+1 open entry is poor for high-risk buckets.
   - A default-off D+2 follow-through entry model was added to the unified test channel and tested on the latest quick `max_symbols=500` matrix.
   - It failed: default final return/win/DD was `-1.4597% / 24.79% / -7.0668%`, while D+2 follow-through was `-1.7868% / 23.97% / -7.5239%` with only `1210 / 1557` candidates evaluated.
   - Follow-through rejected weak names, but accepted high-risk names became worse after delayed entry. Do not promote broad D+2 confirmation; use it only as evidence that entry timing and sell/profit protection must be separated.

4. Keep low-suction precise:
   - 3-5 day balanced low-suction is useful.
   - 6-10 day low-suction without activation is weak.
   - "低吸很多天" should not be punished blindly, but it should not keep receiving stale setup credit without fresh lift/active-money evidence.

5. Keep `weekly_top_fractal_risk` out of the bad-factor list:
   - It did not explain poor win rate or poor return in the audit.
   - Calendar-week aggregation fix is valid; broad relief is not yet proven.

6. Current-sell matrix update:
   - The unified Top20 matrix was fixed so default-off experiments that read market context always receive signal-day `dynamic_market_regime / market_warning_level` even when daily score cache is reused.
   - On `2026-02-24..2026-06-22`, `max_symbols=500`, default current-sell Top20 was roughly `-1.37%` average return, `24.76%` win rate, and `-7.08%` average max drawdown.
   - `momentum_risk_control_pure_loss_plus_mfe8_giveback` was the strongest return/win-rate combination, roughly `-0.04% / 29.52%`, but average and worst drawdown were still worse than default.
   - Narrowed hard-filter variants can restore worst drawdown to default, but still leave average drawdown worse. The residual bad added candidates are mostly active mainline names in false-bull/risk contexts with extreme MA dispersion, or risk-day candidates far from MA5.
   - These are default-off test-channel findings only; they do not update the real strategy.

## Conclusion

The current收益低 is not mainly because of the old 10-position cap. The candidate pool itself has a right-tail edge but poor ordinary-trade stability:

- 猛拉 usually comes from active dragon/mainline traits: recent limit-up, multiple large bull days, wide trend structure, and lower-mid/mid close with enough disagreement.
- 下跌 usually comes from high-close weak launch, late or stale low-suction, unknown setup family, and same-day broad Top20 deterioration.
- The current score is mixing these two: it rewards visible strength but does not yet sufficiently demote crowding, stale buildup, and failed-follow-through risk.
- Latest quick fixed-path drilldown (`2026-02-13..2026-06-18`, `max_symbols=500`) sharpened this: `active>=3 + close<0.35 + MA 3-6` had `+10.86%` average 10D return and `50.00%` win rate, while `thin_volume_launch + high close`, `other_confirmed_launch + mid-high close`, `repeated_launch + high close`, and unconfirmed high/mid-high close were the weakest buckets. Some active/wide-MA names produced large MFE but weak final return, so sell/profit protection is a separate problem from candidate scoring.

Next step should stay default-off and narrow: keep mainline momentum as the alpha source, but improve drawdown control around false-bull/risk-day overextension and add better profit protection. Broad weak-bucket demotion and broad D+2 follow-through have already failed, so the next useful work is either a sharper momentum tail-risk model or faster test-channel infrastructure for repeated Top20 reranking.
