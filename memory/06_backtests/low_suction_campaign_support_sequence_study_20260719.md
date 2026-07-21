# AlphaAgent Campaign Support Sequence And D+1 Failure Study

Research status: `reused_history_campaign_sequence_not_formal_validation`.
Formal strategy/metrics: `false/null`.

## Coverage

- Frozen case candidates/primary causal campaigns: `35/1977`.
- Campaign waves/stabilized opportunities: `4443/3698`.
- Baseline closed/D+1 observed: `3414/3648`.
- Signal-day concept and stock main-rise opportunities: `1832`.
- Minute/fund-cycle rows read: `0/0`.

## Baseline

- Higher-high success: `54.9216%`.
- Positive return: `43.6145%`.
- Mean return/PF: `-0.8114%` / `0.7904`.
- Overlap-ignored compound/drawdown: `-100.0000%` / `-100.0000%`.

## Campaign opportunity

| Opportunity | N | Higher high | Positive | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| opportunity_1 | 1953 | 60.3175% | 44.4386% | -0.5874% | 0.8386 | -100.0000% | -100.0000% |
| opportunity_2 | 1060 | 52.2642% | 42.5000% | -1.0686% | 0.7392 | -99.9999% | -99.9999% |
| opportunity_3 | 461 | 45.7701% | 42.7110% | -1.1524% | 0.7287 | -99.7902% | -99.8652% |
| opportunity_4_plus | 224 | 39.2857% | 42.7711% | -1.0793% | 0.7494 | -91.5231% | -94.3290% |

## Support zone

| Zone | N | Higher high | Positive | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| below_ma20 | 1088 | 39.3382% | 29.6692% | -1.0783% | 0.6939 | -99.9998% | -99.9999% |
| ma10_ma20_band | 1264 | 55.6171% | 44.5643% | -0.4370% | 0.8827 | -99.9954% | -99.9998% |
| ma5_ma10_band | 1094 | 66.6362% | 53.5783% | -0.9047% | 0.7912 | -99.9999% | -99.9999% |
| ma5_near | 252 | 67.8571% | 50.4202% | -1.2501% | 0.6836 | -97.7805% | -98.4208% |

## Signal-day main rise intact

This subset requires both the concept daily cycle and the stock structure to remain intact on the completed signal day.

| Opportunity | N | Higher high | Positive | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| opportunity_1 | 1118 | 68.4258% | 51.7457% | -0.5224% | 0.8624 | -99.9970% | -99.9998% |
| opportunity_2 | 435 | 58.8506% | 50.6297% | -0.4416% | 0.8899 | -96.9327% | -99.0177% |
| opportunity_3 | 183 | 53.0055% | 50.9934% | -0.6107% | 0.8569 | -80.3105% | -85.3163% |
| opportunity_4_plus | 96 | 41.6667% | 42.8571% | -1.6465% | 0.6611 | -76.9309% | -80.2352% |

## Frozen 35-case overlay

This overlay is conditioned on campaigns that later reached the old wave-3 candidate and is not a causal win-rate estimate.

| Opportunity | N | Higher high | Positive | Mean | PF | Compound | Drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| opportunity_1 | 35 | 97.1429% | 88.5714% | 4.5515% | 5.9036 | 346.7941% | -16.9840% |
| opportunity_2 | 34 | 100.0000% | 91.1765% | 9.1689% | 17.2590 | 1707.9846% | -10.4305% |
| opportunity_3 | 33 | 63.6364% | 51.5152% | -0.7131% | 0.8399 | -32.5191% | -60.3356% |
| opportunity_4_plus | 27 | 44.4444% | 47.8261% | -0.7712% | 0.8105 | -23.9134% | -52.7415% |

## D+1 Exit Comparison

- D+1 not up: triggered `2048`, rescued losers `1118`, harmed winners `498`, false exits before later higher high `848`, mean delta `0.2216%`.
- D+1 not up and below MA5: triggered `1545`, rescued losers `891`, harmed winners `368`, false exits before later higher high `657`, mean delta `0.1476%`.

### Frozen 35-case strict D+1 by opportunity

| Opportunity | Triggered | Rescued losers | Harmed winners | False exits | Mean delta |
| --- | ---: | ---: | ---: | ---: | ---: |
| opportunity_1 | 14 | 3 | 10 | 13 | -2.7474% |
| opportunity_2 | 14 | 1 | 13 | 14 | -5.3591% |
| opportunity_3 | 12 | 8 | 1 | 4 | 1.3631% |
| opportunity_4_plus | 7 | 5 | 1 | 1 | 0.9145% |

## Zhongjing Electronics

| Signal | Opportunity | Wave | Zone | Test low | MA5 | MA10 | D+1 | D+1 below MA5 | Higher high | Baseline | D+1 strict |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: |
| 2025-06-26 | 1 | 1 | ma5_near | 11.9300 | 11.8980 | 10.3110 | 13.7700 | False | True | 9.7840% | 9.7840% |
| 2025-07-02 | 2 | 2 | ma5_ma10_band | 13.0500 | 13.8600 | 12.6180 | 15.6000 | False | True | 9.8141% | 9.8141% |
| 2025-07-08 | 3 | 3 | ma5_ma10_band | 14.7200 | 15.1480 | 14.2780 | 14.7800 | True | False | -17.1994% | -5.0294% |

### Daily path

| Date | Open | High | Low | Close | Return | MA5 | MA10 | Low/MA5 | Role |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2025-06-24 | 11.3100 | 12.6500 | 11.3100 | 12.6500 | 10.0000% | 10.7940 | 9.4900 | 4.7804% |  |
| 2025-06-25 | 13.0000 | 13.2500 | 11.8000 | 11.9200 | -5.7708% | 11.3760 | 9.8860 | 3.7271% | wave_1_reference_peak;peak_day_low_within_5pct_of_ma5_observation |
| 2025-06-26 | 11.9300 | 13.1100 | 11.9300 | 12.5200 | 5.0336% | 11.8980 | 10.3110 | 0.2690% | opportunity_1_stabilization |
| 2025-06-27 | 12.5500 | 13.7700 | 11.8600 | 13.7700 | 9.9840% | 12.4720 | 10.8660 | -4.9070% |  |
| 2025-06-30 | 14.3900 | 15.1500 | 14.1600 | 15.1500 | 10.0218% | 13.2020 | 11.5520 | 7.2565% |  |
| 2025-07-01 | 15.1500 | 15.3300 | 13.6500 | 13.6800 | -9.7030% | 13.4080 | 12.1010 | 1.8049% | wave_2_reference_peak;peak_day_low_within_5pct_of_ma5_observation |
| 2025-07-02 | 13.4300 | 14.5000 | 13.0500 | 14.1800 | 3.6550% | 13.8600 | 12.6180 | -5.8442% | opportunity_2_stabilization |
| 2025-07-03 | 13.8000 | 15.6000 | 13.8000 | 15.6000 | 10.0141% | 14.4760 | 13.1870 | -4.6698% |  |
| 2025-07-04 | 16.2400 | 16.6600 | 15.0300 | 15.5300 | -0.4487% | 14.8280 | 13.6500 | 1.3623% | wave_3_reference_peak;peak_day_low_within_5pct_of_ma5_observation |
| 2025-07-07 | 15.5400 | 16.2200 | 14.8300 | 14.9000 | -4.0567% | 14.7780 | 13.9900 | 0.3519% |  |
| 2025-07-08 | 15.1100 | 15.9900 | 14.7200 | 15.5300 | 4.2282% | 15.1480 | 14.2780 | -2.8255% | opportunity_3_stabilization |
| 2025-07-09 | 15.4400 | 15.5800 | 14.1900 | 14.7800 | -4.8294% | 15.2680 | 14.5640 | -7.0605% | opportunity_3_d1_failure |

## Boundaries

- the 35 episode selectors and their outcomes were already viewed
- same-close signal confirmation and entry is a research proxy, not a fill
- support zones describe the observed daily low relative to completed MAs
- D+1 variants were compared on winners and losers, including false exits
- current concept membership and causal Top3 identity remain proxy evidence
- no API, UI, paper portfolio, or live strategy rule is changed by this study

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-campaign-support-sequence-study --format markdown
```
