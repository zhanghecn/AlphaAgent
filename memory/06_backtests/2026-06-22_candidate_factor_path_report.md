# Candidate Factor Path Report

Date: 2026-06-22

## Scope

- Test channel: `test_current_strategy_candidate_factor_path_report`.
- Strategy code: current `mainline_dragon_pullback / 0.1.21` candidate generation, no real strategy promotion.
- Window: `2026-02-24..2026-06-22`.
- Quick universe: `ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500`.
- Candidate set: each signal date's current-code Top20 selected independently from a Top80 context pool.
- Execution model: D signal is visible after close; D+1 open independent entry; current sell logic exit.
- Position model: no cash, max-position, existing-holding, replacement, or portfolio constraints.
- Data-quality handling: metrics below use the clean set excluding suspected unadjusted price discontinuities unless noted.

## Overall Path

Raw evaluated rows: `1557`. Suspected unadjusted price discontinuities: `22`.
Clean evaluated rows: `1535`.

| Metric | Value |
| --- | ---: |
| Average return | `-1.0516%` |
| Median return | `-4.4808%` |
| Win rate | `25.99%` |
| Average max drawdown | `-6.9417%` |
| Worst max drawdown | `-20.8241%` |
| Average max runup | `+10.0463%` |
| Surge rate: MFE or final return `>=8%` | `34.92%` |
| Decline rate: final `<=-5%` or DD `<=-8%` | `47.30%` |
| Pure loss: MFE `<3%` and final `<0` | `38.63%` |
| Giveback: MFE `>=8%` and final `<=0` | `13.03%` |
| Deep DD: DD `<=-10%` | `21.43%` |

Interpretation:

- The current Top20 still has right-tail alpha: about one third of candidates can produce `>=8%` MFE.
- The ordinary candidate is weak: median return is deeply negative and nearly 39% of rows are pure loss.
-收益低 is not explained by only one bad sell rule. It is both candidate-quality and path-protection: too many candidates never start, while some right-tail candidates give back tradable MFE.

## Data Quality

The raw sample still includes suspected unadjusted ex-rights/ex-dividend gaps.

- Discontinuity rows: `22 / 1557`, rate `1.41%`.
- Their average return was `-19.68%`, average max drawdown `-22.48%`, worst drawdown `-34.13%`.
- Examples include `001207.SZSE`, `001332.SZSE`, `001316.SZSE`.

Conclusion: strategy factor analysis should use the clean view, but the data layer still needs an adjusted-price migration plan before any product-grade full-market conclusion.

## What Tends To Surge

Stronger signal-day buckets in this quick sample:

| Bucket | N | Avg Ret | Surge | Pure Loss | Note |
| --- | ---: | ---: | ---: | ---: | --- |
| `active + low close` | 25 | `+3.47%` | `72.00%` | `16.00%` | Small sample, strongest MFE asymmetry. |
| `active + MA convergence 3-6` | 46 | `+4.82%` | `54.35%` | `13.04%` | Better support-lift shape. |
| `balanced_first_lift + strong_broad` | 14 | `+4.68%` | `50.00%` | `28.57%` | Small sample, cleaner drawdown. |
| `unconfirmed_buildup + strong_broad` | 31 | `+2.48%` | `45.16%` | `22.58%` | Not all unconfirmed buildup is bad. |
| `trend_10_18 + lower_mid close` | 39 | `+2.32%` | `48.72%` | `25.64%` | Wide MA can be live trend energy if close is controlled. |

Working rule:

- 猛拉 is not simply "突破 5 日线".
- Better description: active-money evidence plus low/lower-mid or controlled close, enough MA spread to retain trend energy, and a still-tradable distance from MA5.
- Low-suction buildup should be rewarded only when it looks like support is lifting, not just because it has been quiet for many days.

## What Tends To Decline

Weak buckets in the clean Top20:

| Bucket | N | Avg Ret | Decline | Pure Loss | Note |
| --- | ---: | ---: | ---: | ---: | --- |
| `MA5 distance >6%` | 27 | `-3.76%` | `74.07%` | `40.74%` | Too far from MA5, poor entry asymmetry. |
| `other_confirmed_launch` | 55 | `-3.66%` | `63.64%` | `40.00%` | "Confirmed" but not enough active support. |
| `repeated_launch` | 52 | `-3.32%` | `61.54%` | `42.31%` | Repeated start often becomes crowding. |
| `active_mid_trend` | 81 | `-0.46%` | `60.49%` | `35.80%` | Can surge, but path is unstable and drawdown-heavy. |
| `MA convergence 6-10` | 243 | `-2.31%` | `58.02%` | `37.45%` | Current score over-admits weak mid-wide structures. |
| `high_close_other` | 162 | `-0.95%` | `58.02%` | `33.95%` | High close is often consensus, not low-risk strength. |
| `not_low_suction` | 360 | `-0.75%` | `57.22%` | `31.94%` | Strong trend lane has right tail but too many failed paths. |

Pure-loss buckets:

- `stale_low_suction_no_active`: pure-loss rate `48.94%`.
- `unknown entry_family`: pure-loss rate `46.81%`.
- `MA convergence <3` tight quiet: pure-loss rate `46.20%`.
- `warning level 2`: pure-loss rate `46.10%`.
- `false_bull`: pure-loss rate `44.65%`.

Working rule:

- 买后下跌 often comes from three distinct cases:
  - High-close or repeated launch where entry is already crowded.
  - 6-10 day low-suction that has no active-money evidence or fresh lift.
  - Very tight/quiet structure that has not actually started.
- Market context matters only through interaction. `false_bull` alone is not a hard reject, but `false_bull + warning + no active low support` is a bad pure-loss signature.

## Current Scoring Diagnosis

The current code still rewards strength, relative trend, low-suction days, support/reclaim, and liquidity. The missing separation is:

- Healthy active pullback vs high-close crowding.
- Support-lift low-suction vs stale low-suction.
- Live wide-MA trend vs far-from-MA5 exhaustion.
- Strong candidate day structure vs weak Top20 crowding day.

The current lane bonus in `candidate_lanes.py` can give large opportunity credit to longer low-suction setups. That matches the user's concern: "上拉是加分，而不是低吸很多天的时候扣分". The fix should not punish quiet low-suction broadly. It should only demote stale low-suction when there is no active-money evidence, no fresh lift, or poor MA5 entry asymmetry.

## Test-Channel Next Step

Default-off experiment only:

1. Add a support-lift quality overlay in the unified test channel:
   - Add score for active low/lower-mid support, controlled close, near/acceptable MA5 distance, and MA convergence `3-10` or trend `10-18`.
   - Add smaller score for 3-5 day low-suction if MA is tightening and there is fresh lift.

2. Add a stale/crowded demotion:
   - Demote 6-10 day low-suction only when inactive and without fresh lift.
   - Demote MA5 distance `>6%`, repeated/high-close launch, and other-confirmed launch without active low support.
   - Demote warning/false-bull only as an interaction with weak setup quality.

3. Keep profit protection separate:
   - MFE `>=8%` giveback rate is `13.03%`, but previous broad trailing experiments were not enough.
   - Candidate ranking quality must improve before tightening exits broadly.

No real strategy update is justified yet. The next promotion candidate must improve average return and win rate without worsening average/worst drawdown against the existing Top20 test channel.

## V3 Support-Lift Follow-Up

Implemented only in the unified postprocess test channel:

- `v3_support_lift_cap10_mfe8_keep6_giveback5`
- `v3_support_lift_cap8_mfe8_keep6_giveback5`

The V3 overlay uses only signal-day evidence. It rewards active low/lower-mid support lift, controlled low-suction lift, and tradable MA5 distance. It demotes inactive stale low-suction, high/repeated/other-confirmed crowded launches, MA5 overextension, and weak-day crowded/stale interactions.

Latest quick result, same window `2026-02-24..2026-06-22`, `max_symbols=500`:

| Variant | Candidates | Raw Avg / Win / DD / Worst | Clean Avg / Win / DD / Worst |
| --- | ---: | ---: | ---: |
| default Top20 | `1557` | `-1.3148% / 25.69% / -7.1613% / -34.1282%` | `-1.0516% / 25.99% / -6.9417% / -20.8241%` |
| V2 cap8 + MFE keep6 | `845` | `+0.2057% / 33.14% / -7.0588% / -32.8267%` | `+0.3884% / 33.33% / -6.9106% / -21.9124%` |
| V3 support-lift cap10 + MFE keep6 | `963` | `-0.3659% / 32.09% / -6.9782% / -32.8267%` | `-0.1730% / 32.32% / -6.8197% / -21.9124%` |
| V3 support-lift cap8 + MFE keep6 | `845` | `-0.2339% / 32.54% / -7.0017% / -32.8267%` | `-0.0122% / 32.81% / -6.8211% / -21.9124%` |

Conclusion:

- V3 is directionally better than default: it improves return, win rate and average drawdown in the same test channel.
- V3 is still weaker than V2 cap8 on return and win rate. Its cleaner average drawdown is slightly better, but not enough to compensate.
- V3 should not be promoted. Keep it as evidence that support-lift logic is useful, but the current scoring weights need further tuning before any real strategy update.
