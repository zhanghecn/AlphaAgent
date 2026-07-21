# AlphaAgent Daily Leader Spell Date Study

Research status: `reused_history_incomplete_event_denominator`.
Formal Top3/metrics/strategy: `false/null/false`.

## Coverage

- Fixed concept campaigns/event candidate campaigns: `3930/449`.
- Candidate spells/confirmation rows/complete truth: `2280/1153/1150`.
- Membership/minute/fund-cycle/prior-outcome rows read: `0/0/0/0`.

## Concept Restart Audit

- Legacy PCB campaign: `2026-04-13` to `2026-07-06`.
- Restart-aware PCB impulse: `2026-05-25` to `2026-06-16`.
- Split rule: a 3% reset followed by a new anchor rising edge.

## Mode Comparison

| Mode | Segment | Spells | Complete | Pullback then higher high | D+5 positive | Mean D+5 | Median D+5 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ignition_gain_top3 | all | 587 | 586 | 66.5529% | 49.4881% | 2.6563% | -0.0789% |
| two_strong_gain_top3 | all | 300 | 299 | 66.8896% | 47.1572% | 1.7054% | -1.3252% |
| two_strong_gain_top3_early_phase | all | 266 | 265 | 66.7925% | 47.1698% | 2.3805% | -1.2833% |
| ignition_gain_top3 | block_1 | 189 | 189 | 59.7884% | 50.2646% | 2.5773% | 0.6061% |
| two_strong_gain_top3 | block_1 | 91 | 91 | 60.4396% | 49.4505% | 4.0604% | -0.0581% |
| two_strong_gain_top3_early_phase | block_1 | 84 | 84 | 60.7143% | 51.1905% | 4.9769% | 0.4210% |
| ignition_gain_top3 | block_2 | 114 | 114 | 70.1754% | 37.7193% | 0.2925% | -2.5984% |
| two_strong_gain_top3 | block_2 | 41 | 41 | 70.7317% | 43.9024% | 0.0348% | -3.3351% |
| two_strong_gain_top3_early_phase | block_2 | 36 | 36 | 75.0000% | 44.4444% | 0.4499% | -3.3342% |
| ignition_gain_top3 | block_3 | 108 | 108 | 70.3704% | 54.6296% | 4.5172% | 0.5752% |
| two_strong_gain_top3 | block_3 | 70 | 70 | 68.5714% | 52.8571% | 2.8599% | 0.3541% |
| two_strong_gain_top3_early_phase | block_3 | 56 | 56 | 67.8571% | 57.1429% | 5.1313% | 1.9393% |
| ignition_gain_top3 | block_4 | 76 | 75 | 64.0000% | 49.3333% | 1.0927% | 0.0000% |
| two_strong_gain_top3 | block_4 | 44 | 43 | 58.1395% | 30.2326% | -4.6439% | -3.2527% |
| two_strong_gain_top3_early_phase | block_4 | 42 | 41 | 58.5366% | 29.2683% | -4.6254% | -3.2527% |
| ignition_gain_top3 | block_5 | 100 | 100 | 73.0000% | 56.0000% | 4.6632% | 1.6783% |
| two_strong_gain_top3 | block_5 | 54 | 54 | 79.6296% | 51.8519% | 2.5647% | 1.0400% |
| two_strong_gain_top3_early_phase | block_5 | 48 | 48 | 77.0833% | 45.8333% | 2.0596% | -0.6546% |

## Continuation Winners And Failures

| Outcome group | Spells | D+5 positive | Mean D+5 | Confirmation gain | Rank1 share | Future max | Future drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| no_pullback_rebreak | 88 | 12.5000% | -8.2032% | 34.3199% | 48.8636% | 10.2565% | -21.4343% |
| pullback_then_higher_high | 177 | 64.4068% | 7.6425% | 31.9612% | 35.5932% | 33.7737% | -19.4300% |

## Post-hoc Continuation Slice

This same-history slice is not frozen and is not an entry rule.

| Segment | Slice | Spells | Pullback then higher high | D+5 positive | Mean D+5 | Median D+5 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| all | complement | 215 | 64.6512% | 46.0465% | 2.3292% | -1.3529% |
| all | gain_20_25_rank_2_3 | 50 | 76.0000% | 52.0000% | 2.6011% | 0.9045% |
| block_1 | complement | 74 | 59.4595% | 48.6486% | 5.0477% | -0.7055% |
| block_1 | gain_20_25_rank_2_3 | 10 | 70.0000% | 70.0000% | 4.4528% | 5.0580% |
| block_2 | complement | 28 | 75.0000% | 42.8571% | 0.0946% | -3.4948% |
| block_2 | gain_20_25_rank_2_3 | 8 | 75.0000% | 50.0000% | 1.6936% | -1.3875% |
| block_3 | complement | 45 | 64.4444% | 53.3333% | 4.7573% | 0.6206% |
| block_3 | gain_20_25_rank_2_3 | 11 | 81.8182% | 72.7273% | 6.6616% | 3.6468% |
| block_4 | complement | 33 | 54.5455% | 30.3030% | -5.6524% | -3.6329% |
| block_4 | gain_20_25_rank_2_3 | 8 | 75.0000% | 25.0000% | -0.3892% | -2.1450% |
| block_5 | complement | 35 | 77.1429% | 48.5714% | 2.7727% | -0.0743% |
| block_5 | gain_20_25_rank_2_3 | 13 | 76.9231% | 38.4615% | 0.1396% | -1.8211% |

## Zhongjing Electronics 2026

| Mode | Concept anchor | Ignition | Confirmation | Rank | Peak | Warning | End confirmed | Continued after pullback |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| ignition_gain_top3 | 2026-05-25 | 2026-05-26 | 2026-05-26 | 2 | 2026-06-02 | 2026-06-05 | 2026-06-08 | True |
| two_strong_gain_top3 | 2026-05-25 | 2026-05-26 | 2026-05-27 | 1 | 2026-06-02 | 2026-06-05 | 2026-06-08 | True |
| two_strong_gain_top3_early_phase | 2026-05-25 | 2026-05-26 | 2026-05-27 | 1 | 2026-06-02 | 2026-06-05 | 2026-06-08 | True |

### Daily Path

| Date | Close | Return | MA5 | MA10 | Event boards | Causal rank | Role |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2026-05-22 | 13.4600 | 5.4033% | 13.1440 | 13.2840 | - | - |  |
| 2026-05-25 | 13.6700 | 1.5602% | 13.2220 | 13.3050 | - | - | concept_campaign_anchor |
| 2026-05-26 | 15.0400 | 10.0219% | 13.5740 | 13.4670 | 1 | 2 | leader_ignition |
| 2026-05-27 | 16.5400 | 9.9734% | 14.2960 | 13.7360 | 2 | 1 | leader_confirmation |
| 2026-05-28 | 18.1900 | 9.9758% | 15.3800 | 14.2220 | 3 | 1 |  |
| 2026-05-29 | 17.1500 | -5.7174% | 16.1180 | 14.6310 | - | 1 | five_pct_pullback |
| 2026-06-01 | 18.8700 | 10.0292% | 17.1580 | 15.1900 | 4 | 1 | higher_high_recovery |
| 2026-06-02 | 20.7600 | 10.0159% | 18.3020 | 15.9380 | 5 | 1 | realized_peak_not_known_same_day |
| 2026-06-03 | 19.4500 | -6.3102% | 18.8840 | 16.5900 | - | 1 |  |
| 2026-06-04 | 20.6100 | 5.9640% | 19.3680 | 17.3740 | - | 1 |  |
| 2026-06-05 | 18.6900 | -9.3159% | 19.6760 | 17.8970 | - | 1 | first_close_below_ma5_warning |
| 2026-06-08 | 16.8200 | -10.0054% | 19.2660 | 18.2120 | - | 1 | second_close_below_ma5_end_confirmation |

## Boundary

- Peak date is descriptive; it was not known on that date.
- End confirmation requires two consecutive completed closes below MA5.
- The 20%-25% gain and rank 2/3 slice was discovered on this same history and requires forward validation.
- Exact event reasons do not contain every concept member, so formal Top3 remains disabled.
- No minute data, fund cycle, current membership, or prior low-suction outcome was read.

## Reproduce

```bash
python -m alphaagent.server.services.low_suction.cli v2-daily-leader-spell-date-study --format markdown
```
