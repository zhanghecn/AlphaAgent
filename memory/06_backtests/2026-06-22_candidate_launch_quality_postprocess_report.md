# Candidate Launch Quality Postprocess Report

Date: 2026-06-22

## Scope

- Test channel: `test_current_strategy_candidate_quality_postprocess_report`.
- Strategy source: current `mainline_dragon_pullback / 0.1.21` candidate generation.
- No real strategy promotion. All variants below are test-channel postprocess experiments.
- Window: `2026-02-24..2026-06-22`.
- Quick universe: `ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500`.
- Candidate set: each signal date's current Top80 context pool, postprocessed to Top20.
- Entry: D signal visible after close, D+1 open independent entry, current sell logic exit.
- Clean view excludes suspected unadjusted price-discontinuity rows.

## Formal Quick Result

| Variant | Candidates | Raw Avg / Win / DD / Worst | Clean Avg / Win / DD / Worst | Read |
| --- | ---: | ---: | ---: | --- |
| `default_top20` | `1557` | `-1.3148% / 25.69% / -7.1613% / -34.1282%` | `-1.0516% / 25.99% / -6.9417% / -20.8241%` | Current candidate quality is weak. |
| `default + mfe8_keep6` | `1557` | `-1.0944% / 28.64% / -6.9328% / -34.1282%` | `-0.8450% / 28.97% / -6.7252% / -20.8241%` | Profit protection helps but does not solve pure-loss candidates. |
| `v2_cap10 + mfe8_keep6` | `963` | `-0.0083% / 32.40% / -7.0093% / -32.8267%` | `+0.1690% / 32.60% / -6.8646% / -21.9124%` | Stronger than default, weaker than cap8 on return. |
| `v2_cap8 + mfe8_keep6` | `845` | `+0.2057% / 33.14% / -7.0588% / -32.8267%` | `+0.3884% / 33.33% / -6.9106% / -21.9124%` | Best current test-channel direction. |
| `v3_support_lift_cap8 + mfe8_keep6` | `845` | `-0.2339% / 32.54% / -7.0017% / -32.8267%` | `-0.0122% / 32.81% / -6.8211% / -21.9124%` | Support-lift evidence useful, but weaker than V2. |
| `v4_launch_quality_cap8 + mfe8_keep6` | `845` | `-0.5872% / 31.36% / -7.1599% / -33.9155%` | `-0.2964% / 31.65% / -6.9156% / -20.8241%` | Improves default, fails versus V2/V3. |
| `v5_v2_lift_guard_cap10 + mfe8_keep6` | `963` | `-0.0596% / 32.92% / -6.9990% / -32.8267%` | `+0.1173% / 33.12% / -6.8542% / -21.9124%` | Higher win than V2 cap10, lower return. |
| `v5_v2_lift_guard_cap8 + mfe8_keep6` | `845` | `+0.0375% / 32.90% / -7.0593% / -32.8267%` | `+0.1852% / 33.05% / -6.9380% / -21.9124%` | Directional, but weaker than V2 cap8. |

Conclusion:

- V2 cap8 remains the best current test-channel candidate-quality variant.
- V4 and V5 improve default but do not beat V2 cap8 on the combined return/win/drawdown gate.
- Do not update the real strategy from V4 or V5.

## Why V4 Failed

V4 tried to preserve more support-lift / MA5-turning candidates while demoting first-down signatures. It correctly removed weak candidates, but the added replacement rows were still weak:

| Variant | Removed Avg / Win / DD | Added Avg / Win / DD |
| --- | ---: | ---: |
| `v4_cap10` | `-1.7346% / 25.76% / -6.6489%` | `-0.8012% / 28.36% / -6.4802%` |
| `v4_cap8` | `-1.5797% / 25.76% / -6.6563%` | `-0.8033% / 28.04% / -6.6099%` |

This means V4's support-lift preservation was too broad. It found fewer bad rows than V2 and admitted too many replacement candidates whose expected return was still negative.

## Why V5 Did Not Beat V2

V5 used V2 as the strict base and added a narrow lift guard for low/lower-mid close, MA5 turning or fresh lift, near MA5/MA10, and reclaimed MA20.

| Variant | Removed Avg / Win / DD | Added Avg / Win / DD |
| --- | ---: | ---: |
| `v2_cap8` | `-2.1692% / 25.00% / -6.7573%` | `+0.2114% / 33.57% / -6.6254%` |
| `v5_cap8` | `-2.0032% / 25.09% / -6.7535%` | `+0.2548% / 32.85% / -6.6014%` |
| `v2_cap10` | `-2.1901% / 24.55% / -6.7602%` | `+0.0544% / 31.25% / -6.5958%` |
| `v5_cap10` | `-2.2221% / 24.12% / -6.7827%` | `-0.2892% / 32.54% / -6.6320%` |

V5 cap8 added slightly better-return replacements than V2 cap8, but it also protected some rows that V2 removed. The net result is weaker average return and slightly weaker win/drawdown than V2 cap8.

## Factor Diagnosis

What tends to lift hard:

- Active-money evidence plus low/lower-mid close.
- Price still near MA5/MA10, with MA5 beginning to turn up.
- MA convergence roughly `3..18`: tight enough for support, wide enough to retain trend energy.
- Recent large-bull / limit-up evidence when close is still controlled, not crowded high close.
- Controlled `3-5d` low-suction with fresh lift.

What tends to fall after entry:

- High-close crowded launch: `high_close_launch`, `repeated_launch`, `other_confirmed_launch`, `thin_volume_launch` with close location above `0.75`.
- Low-suction `6-10d` without active money or fresh lift.
- MA5 distance above about `6%`.
- Very tight MA structure without activation.
- False-bull/warning context only when combined with weak setup, not as a standalone filter.

Interpretation:

- `突破 5 日线` is a symptom, not a sufficient buy rule.
- A better startup pattern is gradual support lift: still near MA5/MA10, MA5 turning up, close not crowded, and recent activity visible.
- Current收益低 is mainly because too many Top20 candidates first break support before producing a tradable lift. Sell/profit protection is a separate second problem.

## Next Work

1. Keep V2 cap8 as the current best test-channel direction, but do not promote it because coverage drops and data quality still affects raw worst drawdown.
2. Narrow the lift guard further before another V5/V6:
   - preserve only lift candidates that also have active evidence or a controlled `3-5d` low-suction structure;
   - do not protect `6-10d` low-suction unless fresh lift is strong and same-day Top20 structure is not crowded.
3. Add a reusable candidate-score snapshot/cache for Top80 daily candidates. The formal quick postprocess report still takes about `3:33`, which is too slow for repeated factor iteration.
4. Keep profit protection separate from candidate ranking. `mfe8_keep6` improves default, but it cannot fix pure-loss entries.

## Verification

Smoke:

```bash
DATABASE_URL='postgresql+psycopg://alphaagent:zhangxuan66.@172.25.0.5:5432/alphaagent' \
ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT=1 \
ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=120 \
ALPHAAGENT_CANDIDATE_COHORT_MAX_DATES=20 \
uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_quality_postprocess_report -q -s
```

Formal quick:

```bash
DATABASE_URL='postgresql+psycopg://alphaagent:zhangxuan66.@172.25.0.5:5432/alphaagent' \
ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT=1 \
ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500 \
uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_quality_postprocess_report -q -s
```

Latest formal quick passed in about `3:33`.
