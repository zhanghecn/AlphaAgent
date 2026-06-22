# Postprocess Stock Audit Report

Date: 2026-06-22

## Scope

- Test channel: `test_current_strategy_postprocess_stock_audit_report`.
- Strategy source: current `mainline_dragon_pullback / 0.1.21` candidate generation.
- No real strategy promotion.
- Window: `2026-02-24..2026-06-22`.
- Quick universe: `ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500`.
- Audit method: compare default Top20 plus `mfe8_keep6_giveback5` sell audit with V2/V5 postprocess changes. Drill into removed and added stocks with signal-day visible factors, MA/pressure, market context, and entry path.

## Summary

Base clean postprocess sell audit:

- `default_top20_mfe8_keep6`: `-0.8450% / 28.97% / DD -6.7252%`.

V2 and V5 stock-level change quality:

| Variant | Clean Avg / Win / DD | Removed | Removed Avg / Win / DD | Added | Added Avg / Win / DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| `v2_cap8 + mfe8_keep6` | `+0.3884% / 33.33% / -6.9106%` | `852` | `-2.1692% / 25.00% / -6.7573%` | `140` | `+0.2114% / 33.57% / -6.6254%` |
| `v5_cap8 + mfe8_keep6` | `+0.1852% / 33.05% / -6.9380%` | `849` | `-2.0032% / 25.09% / -6.7535%` | `137` | `+0.2548% / 32.85% / -6.6014%` |

Interpretation:

- V2 improves because it removes a large weak group and replaces it with slightly positive candidates.
- V5's low-lift guard improves some replacement quality, but it also preserves too many middling rows. Net return and drawdown are weaker than V2.
- Candidate-quality gains are not yet "large enough"; the best tested path is still only around `+0.39%` average per independent candidate after clean filtering.

## Removed Losers

V2/V5 correctly removed many first-down failures:

| Date | Symbol | Name | Return / MFE / DD | Visible Read |
| --- | --- | --- | ---: | --- |
| `2026-06-02` | `000960.SZSE` | 锡业股份 | `-17.84% / +2.58% / -20.12%` | Extreme high close `1.00`, MA5 distance `+9.18%`, warning `3`, path `down5_before_up8`; this is MA5 overextension, not a low-risk startup. |
| `2026-03-18` | `002092.SZSE` | 中泰化学 | `-14.79% / +1.21% / -15.15%` | False-bull warning `2`, MA5 slope negative, active-mid label but no low support; first breaks down. |
| `2026-06-17` | `000722.SZSE` | 湖南发展 | `-13.99% / +1.16% / -14.64%` | High close `1.00`, warning `2`, unconfirmed buildup; high-close weak launch failed. |

Bad removed buckets:

- `other_confirmed_launch`: average `-5.16%`, win `12.8%`.
- `very_far_6+` from MA5: average `-3.67%`.
- `false_bull`: average `-3.26%`, pure-loss rate above `50%`.
- `repeated_launch`: average `-3.05%`.

This confirms the current low win rate is mainly caused by first-down/pure-loss candidates, not by a lack of potential winners.

## Removed Winners

V2 also removed some right-tail winners:

| Date | Symbol | Name | Return / MFE / DD | Visible Read |
| --- | --- | --- | ---: | --- |
| `2026-04-16` | `000811.SZSE` | 冰轮环境 | `+81.90% / +101.78% / -0.68%` | High close `0.97`, but MA5 distance only `+2.54%`, MA5 slope positive, warning `0`, strong active tradable MA. High close was momentum confirmation, not crowding failure. |
| `2026-05-06` | `000823.SZSE` | 超声电子 | `+50.09% / +50.09% / -4.11%` | Balanced first lift, strong broad market, MA5 distance `+2.47%`, warning `0`. |
| `2026-03-24` | `000967.SZSE` | 盈峰环境 | `+43.28% / +67.39% / -2.41%` | High close but near MA5 and later right-tail run. Warning was high, so this remains harder to protect safely. |

Implication:

- A high-close rule cannot be a broad hard reject.
- It needs a right-tail exception: high close can be acceptable when active strength is real, MA5 distance is still tradable, warning is low, and MA structure has trend energy.

## Added Winners

Strong added candidates mostly match the user's "低吸蓄势拉上去" intuition:

| Date | Symbol | Name | Return / MFE / DD | Visible Read |
| --- | --- | --- | ---: | --- |
| `2026-04-15` | `000811.SZSE` | 冰轮环境 | `+85.60% / +105.89% / -1.39%` | Active low-mid support, close `0.11`, MA5 distance `-0.13%`, MA5 slope positive, path `up8_before_down3`. |
| `2026-04-23` | `001211.SZSE` | 双枪科技 | `+76.11% / +99.87% / -1.94%` | Active low-mid support, near/below MA5, strong active tradable MA. |
| `2026-03-06` | `002082.SZSE` | ST万邦 | `+66.06% / +99.34% / -5.34%` | Active low-mid support, close `0.46`, near MA5, path `up8_before_down3`. |

Good pattern:

- Low/lower-mid close.
- Near MA5, often not yet extended.
- Active-money proxy or recent active structure.
- Path reaches `+8%` before breaking support.

## Added Losers

The added losers explain why V5/V6 still cannot be promoted:

| Date | Symbol | Name | Return / MFE / DD | Visible Read |
| --- | --- | --- | ---: | --- |
| `2026-03-19` | `000555.SZSE` | 神州信息 | `-17.68% / 0.00% / -21.91%` | Looks like controlled low-suction lift, but warning `3`, MA5 slope negative, pressure only `+3.62%` away; immediately breaks down. |
| `2026-03-16` | `001376.SZSE` | 百通能源 | `-14.57% / +0.52% / -20.88%` | Low close but MA5 slope only flat and no clear support-lift signature; low-suction days `6` can be stale, not startup. |
| `2026-03-19` | `000547.SZSE` | 航天发展 | `-12.10% / +0.59% / -18.80%` | Low-mid close, but warning `3` and MA5 slope negative. |
| `2026-06-09` | `000727.SZSE` | 冠捷科技 | `-11.45% / +0.34% / -16.84%` | False-bull warning `2`, active controlled close but first breaks `-5%`; active alone is not enough. |

Rule implication:

- Low close alone is not enough.
- Low-suction/stored energy needs MA5 turning up or active strength. If warning is high and MA5 slope is negative/flat, the setup is often a trap.

## V6 Follow-Up

V6 was tested after this audit:

- Idea: V2 strict base plus right-tail high-close exception and weak-warning rejection.
- Formal quick result:
  - V2 cap8 clean: `+0.3884% / 33.33% / DD -6.9106%`, `845` candidates.
  - V6 cap8 clean: `+0.3846% / 32.97% / DD -6.9534%`, `746` candidates.

V6 did not beat V2. It nearly matched return but had lower win rate, worse average drawdown, and fewer candidates. It is not promotable.

## V7 Follow-Up

V7 tested a softer version after V6:

- Idea: keep V2's hard block and coverage, add larger score relief only for low-warning high-close right-tail candidates, plus soft penalty for weak warning traps.
- Formal quick result:
  - V2 cap8 clean: `+0.3884% / 33.33% / DD -6.9106%`, `845` candidates.
  - V7 cap8 clean: `+0.1843% / 32.97% / DD -6.9339%`, `845` candidates.
- Change quality:
  - V2 added rows averaged `+0.2114%`.
  - V7 added rows averaged only `+0.0573%`.

V7 failed. Keeping coverage while softly rescuing right-tail candidates admitted too many mediocre replacements. This implies V2's missed right-tail winners cannot be fixed by broad score relief alone; they need a more precise exception based on stock-level features, or the work should first speed up the snapshot/replay loop.

## Next Rule Direction

Keep V2 cap8 as the current best test-channel reference. Next experiment should be narrower:

1. Right-tail exception:
   - protect high-close candidates only when warning is low, MA5 distance is tradable, MA5 slope is positive, and active evidence is stronger than the current proxy.
   - do not protect all high-close/repeated launches.
2. Low-lift guard:
   - require either active evidence or `3-5d` low-suction plus MA5 slope turning up.
   - reject warning `>=3` if MA5 slope is negative/flat, even when close is low.
3. Pressure filter:
   - use computed resistance from the drilldown path. If near pressure is within about `2-3%`, a high-close setup needs stronger confirmation.
4. Infrastructure:
   - add candidate Top80 score snapshots so repeated factor tests do not require full rescoring.
   - this is now the preferred next step before V8, because postprocess and stock-audit reports take roughly `3-4` minutes per iteration.

## Verification

Postprocess stock audit:

```bash
DATABASE_URL='postgresql+psycopg://alphaagent:zhangxuan66.@172.25.0.5:5432/alphaagent' \
ALPHAAGENT_RUN_POSTPROCESS_STOCK_AUDIT=1 \
ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500 \
ALPHAAGENT_STOCK_DRILLDOWN_SAMPLE_LIMIT=5 \
uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_postprocess_stock_audit_report -q -s
```

V6 formal quick:

```bash
DATABASE_URL='postgresql+psycopg://alphaagent:zhangxuan66.@172.25.0.5:5432/alphaagent' \
ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT=1 \
ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500 \
uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_quality_postprocess_report -q -s
```

Both passed on 2026-06-22.
