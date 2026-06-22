# Candidate Loss And Missed Winner Audit

Date: 2026-06-22

## Scope

- Strategy/run: `mainline_dragon_pullback / 0.1.21`, product baseline `#203`.
- Range: `2025-03-26..2026-06-18`.
- Main lens: no-position Top20 candidate quality. Each candidate cluster is independently bought at D+1 open and exited by current sell logic; cash, max positions, full portfolio and replacement are ignored.
- Supporting lens: whole-market 20-trading-day forward winner scan, used only to generate missed-winner hypotheses. This is hindsight and must not enter scoring without a no-future rule.

## Candidate Quality Summary

- Top20 candidate clusters: `2330`; evaluated: `2316`.
- Average return: `+1.8149%`; median return: `-5.8553%`.
- Win rate: `38.73%`; average max drawdown: `-7.9208%`.
- Interpretation: the candidate pool has positive right-tail payoff, but most individual trades still lose. Optimization should target bad buckets and drawdown tails, not simply expand buy frequency.

## Worst Candidate Samples

| Symbol | Name | Signal | Rank | Score | Return | Max DD | MFE | Exit | Setup | Phase | Launch |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| `605117.SSE` | 德业股份 | `2026-05-18` | 11 | 93.85 | `-25.83%` | `-28.48%` | `+9.46%` | support_stop | dragon_pullback | choppy_rotation | high_close_launch |
| `600745.SSE` | *ST闻泰 | `2025-09-17` | 3 | 90.23 | `-23.15%` | `-23.15%` | `+13.17%` | support_stop | low_position_reclaim | strong_broad | late_pullback_launch |
| `605117.SSE` | 德业股份 | `2026-04-29` | 1 | 99.39 | `-21.14%` | `-23.96%` | `+16.37%` | support_stop | dragon_pullback | choppy_rotation | late_pullback_launch |
| `002181.SZSE` | 粤传媒 | `2026-05-12` | 6 | 96.87 | `-21.09%` | `-23.17%` | `+15.09%` | support_stop | dragon_pullback | choppy_rotation | not_low_suction |
| `002208.SZSE` | 合肥城建 | `2026-03-11` | 3 | 97.49 | `-20.73%` | `-23.66%` | `+1.10%` | support_stop | low_position_reclaim | choppy_rotation | repeated_launch |
| `002962.SZSE` | 五方光电 | `2026-06-10` | 4 | 96.34 | `-20.68%` | `-20.68%` | `+0.98%` | support_stop | low_position_reclaim | false_bull | not_low_suction |

Common pattern: these are not mostly low-score random stocks. They are high-score candidates that fail follow-through and then hit support stops, especially in `choppy_rotation` or `false_bull` contexts.

## Low-Quality Candidate Buckets

| Bucket | N | Win Rate | Avg Return | Median | Avg DD | Loss <= -8% |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| dragon_pullback + high_close_launch | 43 | `27.91%` | `-2.65%` | `-8.33%` | `-10.10%` | `53.49%` |
| low_position_reclaim + unconfirmed_buildup | 50 | `34.00%` | `-1.43%` | `-5.46%` | `-7.67%` | `32.00%` |
| low_position_reclaim + balanced_first_lift | 81 | `38.27%` | `-0.69%` | `-5.69%` | `-7.44%` | `25.93%` |
| choppy_rotation + high_close_launch | 147 | `34.01%` | `-0.43%` | `-5.03%` | `-7.61%` | `29.25%` |
| choppy_rotation + thin_volume_launch | 98 | `37.76%` | `-0.12%` | `-4.61%` | `-7.04%` | `29.59%` |
| choppy_rotation + unconfirmed_buildup | 122 | `31.15%` | `+0.22%` | `-7.29%` | `-8.27%` | `37.70%` |
| dragon_pullback + close > 0.75 + normal volume | 276 | `33.33%` | `+0.68%` | `-7.34%` | `-9.20%` | `45.65%` |
| dragon_pullback + MA convergence 6-10 + close > 0.75 | 137 | `32.85%` | `-1.33%` | `-7.44%` | `-9.27%` | `41.61%` |
| low_position_reclaim + MA convergence 3-6 + close > 0.75 | 177 | `38.42%` | `-0.89%` | `-5.99%` | `-7.47%` | `30.51%` |

Working explanation:

- High close is not always bullish. In weak/choppy contexts it often means the entry is closer to short-term consensus than to asymmetry.
- `high_close_launch`, `thin_volume_launch`, `unconfirmed_buildup` and some `balanced_first_lift` rows need stricter context. They are not all bad, but their drawdown tails are bad.
- Dragon-pullback candidates with high close and medium/wide MA dispersion are especially vulnerable to next-day failed follow-through.

## MFE Giveback Samples

Some candidates had large unrealized runup but ended flat or negative:

| Symbol | Name | Signal | Return | MFE | Exit | Setup | Phase |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `603162.SSE` | 海通发展 | `2026-04-15` | `-10.91%` | `+40.70%` | support_stop | low_position_reclaim | choppy_rotation |
| `605303.SSE` | 园林股份 | `2026-05-14` | `-1.14%` | `+38.26%` | profit_protection_stop | dragon_pullback | choppy_rotation |
| `600301.SSE` | 华锡有色 | `2026-01-20` | `-0.47%` | `+37.88%` | profit_protection_stop | dragon_pullback | strong_broad |
| `600343.SSE` | 航天动力 | `2025-12-23` | `-0.83%` | `+35.68%` | profit_protection_stop | dragon_pullback | false_bull |
| `000890.SZSE` | 法尔胜 | `2026-03-25` | `-1.58%` | `+32.31%` | profit_protection_stop | dragon_pullback | choppy_rotation |

Do not directly tighten all profit-protection exits. Prior broad early-exit experiments hurt trend winners. The better next step is a read-only `large_mfe_giveback` marker split by mainline/phase, then a default-off non-mainline trailing experiment.

## Missed Winner Scan

Refined hindsight scan:

- Forward window: D+1 open to next 20 trading days.
- Winner definition: max runup `>=35%` and day-20 close return `>=12%`.
- Filters: exclude BSE; exclude D+1 one-price limit-up opens; require D+1 volume at least `20,000`.

Result:

- Refined winner observations: `1033`.
- Not in persisted Top100 candidates: `990`.
- In candidates but not Top20: `25`.
- In Top20 but score/rank not strong enough: `16`.

This does not mean the current strategy should chase all 990. Many are continuous-board or extreme speculative paths that a pullback/reclaim strategy is not designed to trade. It does show a missing internal lane: `mainline momentum / acceleration`.

### Candidate But Not Top20

| Date | Symbol | Name | Max20 | Close20 | Rank | Score | Setup | Phase | Launch | Recent Limit-Up | Large Bull 20d |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | ---: |
| `2025-12-04` | `002931.SZSE` | 锋龙股份 | `+192.55%` | `+192.55%` | 55 | 84.89 | dragon_pullback | choppy_rotation | not_low_suction | true | 3 |
| `2025-09-11` | `605178.SSE` | 时空科技 | `+189.51%` | `+189.51%` | n/a | 76.75 | low_position_reclaim | strong_broad | not_low_suction | false | 0 |
| `2025-09-18` | `605178.SSE` | 时空科技 | `+186.69%` | `+174.31%` | n/a | 84.04 | dragon_pullback | choppy_rotation | not_low_suction | true | 2 |
| `2025-10-13` | `000592.SZSE` | 平潭发展 | `+165.75%` | `+136.46%` | 72 | 84.37 | low_position_reclaim | choppy_rotation | high_close_launch | false | 1 |
| `2026-05-07` | `000636.SZSE` | 风华高科 | `+160.44%` | `+156.05%` | 47 | 89.23 | dragon_pullback | strong_broad | not_low_suction | false | 1 |
| `2026-04-27` | `002552.SZSE` | 宝鼎科技 | `+158.51%` | `+158.51%` | 26 | 89.51 | dragon_pullback | choppy_rotation | not_low_suction | false | 1 |
| `2026-05-26` | `002636.SZSE` | 金安国纪 | `+123.62%` | `+121.77%` | 25 | 90.00 | dragon_pullback | false_bull | late_pullback_launch | false | 3 |
| `2026-02-05` | `002378.SZSE` | 章源钨业 | `+114.91%` | `+63.87%` | 26 | 90.18 | dragon_pullback | choppy_rotation | not_low_suction | true | 5 |

Common features among candidate-but-not-Top20 winners:

- `dragon_pullback`: 17 / 25.
- `choppy_rotation`: 14 / 25.
- `not_low_suction`: 15 / 25.
- `recent_limit_up_20d=true`: 13 / 25.
- MA convergence `>10`: 10 / 25.

Interpretation: the current score under-ranks some strong-trend/active-money candidates because they look extended, not like clean low-suction entries. This can be intentional risk control, but the opportunity cost is visible.

### In Top20 But Not Strongly Ranked

| Date | Symbol | Name | Max20 | Close20 | Rank | Score | Setup | Phase | Launch | Recent Limit-Up | Large Bull 20d |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | ---: |
| `2025-12-11` | `002931.SZSE` | 锋龙股份 | `+356.51%` | `+356.51%` | 11 | 88.28 | low_position_reclaim | false_bull | unconfirmed_buildup | true | 3 |
| `2026-02-03` | `001896.SZSE` | 豫能控股 | `+170.92%` | `+168.01%` | 10 | 90.76 | low_position_reclaim | choppy_rotation | thin_volume_launch | true | 2 |
| `2025-10-28` | `002083.SZSE` | 孚日股份 | `+140.86%` | `+62.59%` | 18 | 92.52 | dragon_pullback | choppy_rotation | not_low_suction | true | 2 |
| `2025-11-05` | `002083.SZSE` | 孚日股份 | `+133.22%` | `+62.44%` | 13 | 96.91 | low_position_reclaim | choppy_rotation | repeated_launch | true | 2 |
| `2026-05-22` | `002636.SZSE` | 金安国纪 | `+129.37%` | `+127.47%` | 14 | 95.20 | dragon_pullback | choppy_rotation | unconfirmed_buildup | true | 4 |
| `2026-05-22` | `603773.SSE` | 沃格光电 | `+116.24%` | `+105.87%` | 16 | 94.50 | dragon_pullback | choppy_rotation | not_low_suction | true | 7 |
| `2026-02-04` | `002378.SZSE` | 章源钨业 | `+114.72%` | `+81.91%` | 18 | 94.10 | dragon_pullback | choppy_rotation | not_low_suction | true | 5 |
| `2026-06-03` | `002636.SZSE` | 金安国纪 | `+110.56%` | `+108.82%` | 14 | 93.77 | dragon_pullback | false_bull | not_low_suction | true | 3 |

Note: some historical snapshot payloads have missing `rank` even when the table-level rank puts the row into Top20. UI/reporting should prefer the database snapshot rank column when payload rank is absent.

## Why Some High Winners Had No Buy Point

Observed causes:

- Current strategy is a pullback/reclaim/low-suction system. It does not have a dedicated first-board, acceleration-board or continuous-board lane.
- Many missed winners start from a "not clean enough" state: already extended, recent limit-up, high MA dispersion, or not enough low-suction structure.
- Some opportunities are not realistically buyable at D+1 open because they enter one-price boards or extremely thin liquidity soon after. These must be excluded from promotion evidence.
- Historical theme/fund-flow coverage remains weak. Most candidate trades still show `fund_flow_state=unknown`, so the strategy cannot reliably distinguish active mainline speculation from random high-volatility rebounds.

## Youzi-Style Mapping

Public reposts of "炒股养家心法" consistently emphasize market emotion, risk/reward, money-making effect, panic effect, mainline/hotspot focus, and adapting position aggressiveness to the cycle. These are useful hypothesis sources, not executable rules.

References:

- TaoGuBa repost: https://www.tgb.cn/follow/1P01ngeOMBa_1PatOBA1xpQ_1
- Xueqiu repost: https://xueqiu.com/6483678008/30470457
- Xiarj repost collection: https://www.xiarj.com/8378.html

Quant translation for AlphaAgent:

- Emotion cycle: measure limit-up count, limit-down count, broken-board ratio, consecutive-board height, breadth and fund flow. Use it to decide which setup families are allowed, not to blindly add score.
- Mainline first: add read-only theme alignment and leader persistence evidence before changing buy rules.
- Strong market: protect trend winners and admit true mainline pullbacks/acceleration candidates.
- Weak/choppy market: avoid high-close consensus launches unless there is clear mainline/volume confirmation; prefer panic-reclaim/low-suction only after visible support repair.
- "Buy opportunity, sell uncertainty": report exits should reason about whether uncertainty increased, not only whether a fixed stop/target was hit.

## Candidate Strategy Hypotheses

Default-off tests only:

1. Top20 risk-tail penalty:
   - Penalize or demote `dragon_pullback + high_close_launch`, especially with `close_location > 0.75`, `ma_convergence 6-10`, and `choppy_rotation/false_bull`.
   - Penalize `choppy_rotation + unconfirmed_buildup/thin_volume_launch/high_close_launch`.
   - Validate with no-position Top20 acceptance first.

2. Mainline momentum admission lane:
   - Add an internal lane, still under the one public strategy, for recent-limit-up / large-bull / active-theme candidates.
   - Must exclude one-price board opens, BSE for now, illiquid rows and obvious unbuyable paths.
   - Candidate examples: 金安国纪, 沃格光电, 章源钨业, 宝鼎科技, 风华高科.

3. Large-MFE giveback review:
   - Add read-only markers for `MFE >= 20%` and final return `<= 0`.
   - Test tighter trailing only for non-mainline or non-leader paths. Do not apply a broad early exit before proving it preserves trend winners.

4. Narrow weak-holding replacement:
   - Only research replacement when held position is still `<= -5%` at D+1 open and the missed candidate has mainline/momentum evidence.
   - Existing broad rotation experiments failed, so this must stay default-off.

5. Data/reporting fix before strategy promotion:
   - Prefer table-level rank if payload rank is missing.
   - Improve historical sector/theme/fund-flow coverage; current `fund_flow_state=unknown` is too common for a real mainline model.

