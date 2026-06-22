# Candidate Launch Path Report

Date: 2026-06-22

## Scope

- Test channel: `test_current_strategy_candidate_launch_path_report`.
- Strategy code: current `mainline_dragon_pullback / 0.1.21` candidate generation.
- No real strategy promotion. This is a read-only explanation report.
- Window: `2026-02-24..2026-06-22`.
- Quick universe: `ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500`.
- Candidate set: each signal date's current-code Top20, selected from a Top80 context pool.
- Execution model: D signal visible after close; D+1 open independent entry; current sell logic exit.
- Data-quality view: conclusions below use the clean set excluding suspected unadjusted price discontinuities.

## Overall Launch Path

Clean evaluated rows: `1535`.

| Metric | Value |
| --- | ---: |
| Average final return | `-1.0516%` |
| Median final return | `-4.4808%` |
| Final win rate | `25.99%` |
| Average max runup | `+10.0463%` |
| Average max drawdown | `-6.9417%` |
| First hit `+8%` before `-3%` | `23.26%` |
| First hit `+5%` before `-3%` | `34.20%` |
| First hit `-3%` before `+5%` | `60.85%` |
| First hit `-5%` before `+8%` | `47.04%` |
| 3D / 5D / 10D average close return | `+0.06% / -0.37% / -0.83%` |
| 10D average MFE / MAE | `+8.94% / -8.21%` |

Interpretation:

- The current Top20 is not short of right-tail opportunities: `34.20%` can lift `+5%` before `-3%`, and `23.26%` can lift `+8%` before `-3%`.
- The ordinary path is still poor: `60.85%` first break `-3%` before `+5%`, and almost half first break `-5%` before `+8%`.
- This explains the user's observation that buying Top20 often feels weak by the next day or shortly after entry. The pool has winners, but the median candidate is still losing.

## Path Buckets

| Path order | N | Final Avg | Win | 10D Avg Close | 10D MFE / MAE | Read |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `up8_before_down3` | `357` | `+7.78%` | `62.75%` | `+8.28%` | `+19.24% / -3.98%` | Good launch, but `36.97%` still give back to non-positive final result. |
| `up5_before_down3` | `168` | `-3.13%` | `23.81%` | `-1.31%` | `+8.87% / -7.74%` | Only hitting `+5%` is not enough; many later fail. |
| `down3_before_up5` | `212` | `+0.69%` | `31.13%` | `+1.88%` | `+9.96% / -5.72%` | Some shakeout repairs later, but entry experience is weak. |
| `down5_before_up8` | `722` | `-5.59%` | `4.43%` | `-6.15%` | `+4.20% / -11.81%` | Main pure-loss source. |
| `no_5pct_move` | `76` | `+0.34%` | `48.68%` | `+0.41%` | `+2.81% / -1.90%` | Low-volatility neutral bucket. |

## Bad Visible Setups

These are signal-day-visible signatures that should be demoted in the next default-off experiment, not hard-deleted from the real strategy yet.

| Signature | N | Avg Ret | First `+5` | First `-3` | Pure Loss | Note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ma5_overextended_6pct_plus` | `27` | `-3.76%` | `29.63%` | `70.37%` | `40.74%` | Entry is too far from MA5; asymmetry is poor. |
| `tight_quiet_no_activation` | `284` | `-1.85%` | `27.46%` | `59.51%` | `43.66%` | Quiet compression without activation. |
| `high_close_crowded_launch` | `270` | `-2.16%` | `33.70%` | `62.59%` | `41.85%` | High close often means crowded consensus, not low-risk strength. |
| `false_bull_warning_without_low_support` | `177` | `-1.18%` | `37.85%` | `60.45%` | `37.85%` | Market line should be an interaction with weak setup, not a standalone filter. |
| `confirmed_but_no_active_money` | `15` | `-5.35%` | `40.00%` | `60.00%` | `33.33%` | Confirmation without active money is low quality. |
| `stale_6_10d_low_suction_no_lift` | `97` | `-0.46%` | `20.62%` | `65.98%` | `54.64%` | Low suction days alone are not bad, but stale low suction without lift is weak. |

Important nuance:

- `stale_6_10d_low_suction_no_lift` is mixed. The whole bucket is weak, but a fast-lift subset of `20` rows averaged `+7.91%` with `75.00%` win rate.
- Therefore the next factor change must not punish "low suction for many days" broadly. It should demote only the cases lacking fresh lift, active money, and tradable MA5/MA10 support.

## Better Launch Signatures

These are not enough by themselves for promotion, but they explain what a useful startup tends to look like.

| Signature | N | Avg Ret | First `+5` | First `+8` | Win | Note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `ma5_turning_low_mid` fast-lift subset | `32` | `+6.53%` | `100.00%` | `75.00%` | `56.25%` | MA5 turning up from a low/mid close is close to the user's "gradual startup" idea. |
| `balanced_first_lift` fast-lift subset | `39` | `+8.07%` | `100.00%` | `69.23%` | `48.72%` | First balanced lift is useful, but still needs profit protection. |
| `trend_10_18` fast-lift subset | `80` | `+7.80%` | `100.00%` | `78.75%` | `47.50%` | Wider MA trend can carry right-tail energy when entry is still tradable. |
| `strong_broad` fast-lift subset | `50` | `+7.92%` | `100.00%` | `76.00%` | `52.00%` | Broad market strength helps, but does not protect all weak setups. |

Support-lift alone is not sufficient:

- `active_low_mid_fresh_lift` overall still averaged `-0.36%`, with first `+5` before `-3` at `40.00%` and first `-3` before `+5` at `59.31%`.
- `active_mid_live_trend` overall averaged `-0.48%`, with first `+5` before `-3` at `45.24%` and first `-3` before `+5` at `54.76%`.
- So the next rule should combine support-lift with bad-bucket exclusion and day-level crowding context.

## Working Diagnosis

- `突破 MA5` is a visual symptom, not a sufficient quant rule.
- A better startup description is: D day remains near MA5/MA10, MA5 begins to turn up, close is low/lower-mid or controlled mid, MA spread still has trend energy, and recent active-money evidence exists.
- Top20 quality is currently dragged down by too many rows that first break support before any tradable lift.
- Sell logic is a separate problem: even the `up8_before_down3` bucket has `36.97%` MFE giveback to non-positive final return.

## Next Test-Channel Direction

Default-off only:

1. Build a V4 candidate postprocess experiment that combines:
   - positive support-lift score for `ma5_turning_low_mid`, controlled `3-5d` low-suction lift, and active low/lower-mid support;
   - demotion for `ma5_overextended_6pct_plus`, `tight_quiet_no_activation`, `high_close_crowded_launch`, `confirmed_but_no_active_money`, and stale `6-10d` low-suction without lift;
   - interaction demotion for `false_bull/warning` only when setup support is weak.
2. Keep the profit-protection experiment separate:
   - `up8_before_down3` has strong positive return but still high giveback.
   - Candidate scoring should first reduce `down5_before_up8`; sell logic should then reduce MFE giveback.
3. Add a reusable candidate-score snapshot/cache for the unified test channel before broad full-market sweeps.

## Verification

```bash
DATABASE_URL='postgresql+psycopg://alphaagent:zhangxuan66.@172.25.0.5:5432/alphaagent' \
ALPHAAGENT_RUN_CANDIDATE_LAUNCH_PATH_REPORT=1 \
ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500 \
uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_launch_path_report -q -s
```

Latest run passed in about `3:25`.
