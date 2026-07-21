# AlphaAgent Main-Rise Structural-Exit Low-Suction Study

Research status: `no_structural_rule_cleared_nomination_gates`.
Historical gates passed: `false`; production ready: `false`.

## Contract

- Entry: D completed close after the unchanged dynamic Top3 weak-to-strong signal.
- Target: first later high above D-known prior high20, sold at that close.
- Defense: second stock close below MA20 or first entry-concept structure break, sold at the first available stock close.
- Entry and exit both use completed-close research prices; neither is an executable same-close fill.
- D+1 is diagnostic only; no minute bars, fund flow, maximum holding, or data-end price fallback.

## Coverage

- Range: `2024-07-16` to `2026-07-17`.
- Features: `56164`; structural stock/concept bars: `127791/75807`.
- Membership: `current_proxy`; minute/fund rows: `0/0`.
- Nomination outcome cutoffs: development `< 2025-09-30`; validation `< 2026-02-26`.

## Nomination

- No rule passed the blocks 1..4 structural nomination gates; block 5 was not evaluated.
- Failed gates: `no_rule_passed_structural_nomination_gates`.

## 32-Rule Nomination Grid

| Rule | Qualified | Dev Closed | Dev Censored | Dev Positive | Dev Mean | Dev PF | Val Closed | Val Censored | Val Positive | Val Mean | Val PF |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `wts-r6020-top4-nh2-vol8-op2` | `false` | 71 | 2 | 53.5211% | -0.3431% | 0.8942 | 9 | 0 | 33.3333% | -2.1980% | 0.4459 |
| `wts-r6020-top4-nh2-vol8-opall` | `false` | 103 | 4 | 52.4272% | -0.2537% | 0.9241 | 16 | 0 | 37.5000% | -2.6061% | 0.4460 |
| `wts-r6020-top4-nh2-vol12-op2` | `false` | 151 | 4 | 56.2914% | 0.4020% | 1.1406 | 24 | 2 | 29.1667% | -4.4198% | 0.2559 |
| `wts-r6020-top4-nh2-vol12-opall` | `false` | 218 | 7 | 54.5872% | -0.0119% | 0.9964 | 43 | 2 | 46.5116% | -2.3062% | 0.5097 |
| `wts-r6020-top4-nh3-vol8-op2` | `false` | 64 | 2 | 53.1250% | -0.4373% | 0.8748 | 8 | 0 | 37.5000% | -1.5253% | 0.5661 |
| `wts-r6020-top4-nh3-vol8-opall` | `false` | 95 | 4 | 52.6316% | -0.2763% | 0.9214 | 15 | 0 | 40.0000% | -2.2746% | 0.4959 |
| `wts-r6020-top4-nh3-vol12-op2` | `false` | 138 | 4 | 56.5217% | 0.4573% | 1.1557 | 23 | 2 | 30.4348% | -4.2824% | 0.2703 |
| `wts-r6020-top4-nh3-vol12-opall` | `false` | 204 | 7 | 54.9020% | 0.0162% | 1.0048 | 42 | 2 | 47.6190% | -2.1806% | 0.5295 |
| `wts-r6020-top6-nh2-vol8-op2` | `false` | 56 | 1 | 57.1429% | 0.0529% | 1.0174 | 7 | 0 | 42.8571% | -1.0248% | 0.6894 |
| `wts-r6020-top6-nh2-vol8-opall` | `false` | 87 | 3 | 55.1724% | 0.1023% | 1.0322 | 14 | 0 | 42.8571% | -2.0779% | 0.5357 |
| `wts-r6020-top6-nh2-vol12-op2` | `false` | 120 | 3 | 58.3333% | 0.6309% | 1.2226 | 20 | 2 | 35.0000% | -3.2929% | 0.3565 |
| `wts-r6020-top6-nh2-vol12-opall` | `false` | 185 | 6 | 56.2162% | 0.1829% | 1.0562 | 39 | 2 | 51.2821% | -1.5115% | 0.6362 |
| `wts-r6020-top6-nh3-vol8-op2` | `false` | 52 | 1 | 57.6923% | 0.0248% | 1.0078 | 6 | 0 | 50.0000% | 0.0677% | 1.0262 |
| `wts-r6020-top6-nh3-vol8-opall` | `false` | 82 | 3 | 56.0976% | 0.1309% | 1.0399 | 13 | 0 | 46.1538% | -1.6547% | 0.6095 |
| `wts-r6020-top6-nh3-vol12-op2` | `false` | 114 | 3 | 59.6491% | 0.7514% | 1.2638 | 19 | 2 | 36.8421% | -3.0673% | 0.3850 |
| `wts-r6020-top6-nh3-vol12-opall` | `false` | 178 | 6 | 57.3034% | 0.2657% | 1.0811 | 38 | 2 | 52.6316% | -1.3518% | 0.6674 |
| `wts-r6035-top4-nh2-vol8-op2` | `false` | 47 | 2 | 57.4468% | 0.4177% | 1.1302 | 6 | 0 | 33.3333% | -1.3807% | 0.6429 |
| `wts-r6035-top4-nh2-vol8-opall` | `false` | 74 | 4 | 55.4054% | 0.1900% | 1.0550 | 12 | 0 | 41.6667% | -1.7545% | 0.6073 |
| `wts-r6035-top4-nh2-vol12-op2` | `false` | 100 | 4 | 60.0000% | 0.9546% | 1.3328 | 17 | 1 | 29.4118% | -4.3432% | 0.2800 |
| `wts-r6035-top4-nh2-vol12-opall` | `false` | 159 | 7 | 55.9748% | 0.1070% | 1.0303 | 33 | 1 | 48.4848% | -1.9838% | 0.5724 |
| `wts-r6035-top4-nh3-vol8-op2` | `false` | 44 | 2 | 56.8182% | 0.3298% | 1.0969 | 6 | 0 | 33.3333% | -1.3807% | 0.6429 |
| `wts-r6035-top4-nh3-vol8-opall` | `false` | 70 | 4 | 55.7143% | 0.1777% | 1.0496 | 12 | 0 | 41.6667% | -1.7545% | 0.6073 |
| `wts-r6035-top4-nh3-vol12-op2` | `false` | 95 | 4 | 60.0000% | 0.9873% | 1.3328 | 17 | 1 | 29.4118% | -4.3432% | 0.2800 |
| `wts-r6035-top4-nh3-vol12-opall` | `false` | 153 | 7 | 56.2092% | 0.1232% | 1.0341 | 33 | 1 | 48.4848% | -1.9838% | 0.5724 |
| `wts-r6035-top6-nh2-vol8-op2` | `false` | 38 | 1 | 60.5263% | 0.8866% | 1.3081 | 5 | 0 | 40.0000% | -0.1206% | 0.9611 |
| `wts-r6035-top6-nh2-vol8-opall` | `false` | 64 | 3 | 57.8125% | 0.5598% | 1.1736 | 11 | 0 | 45.4545% | -1.2158% | 0.7088 |
| `wts-r6035-top6-nh2-vol12-op2` | `false` | 82 | 3 | 62.1951% | 1.2261% | 1.4254 | 15 | 1 | 33.3333% | -2.7643% | 0.4091 |
| `wts-r6035-top6-nh2-vol12-opall` | `false` | 139 | 6 | 57.5540% | 0.3131% | 1.0891 | 31 | 1 | 51.6129% | -1.0676% | 0.7259 |
| `wts-r6035-top6-nh3-vol8-op2` | `false` | 36 | 1 | 61.1111% | 0.8219% | 1.2731 | 5 | 0 | 40.0000% | -0.1206% | 0.9611 |
| `wts-r6035-top6-nh3-vol8-opall` | `false` | 61 | 3 | 59.0164% | 0.5775% | 1.1745 | 11 | 0 | 45.4545% | -1.2158% | 0.7088 |
| `wts-r6035-top6-nh3-vol12-op2` | `false` | 79 | 3 | 63.2911% | 1.2713% | 1.4341 | 15 | 1 | 33.3333% | -2.7643% | 0.4091 |
| `wts-r6035-top6-nh3-vol12-opall` | `false` | 135 | 6 | 58.5185% | 0.3475% | 1.0977 | 31 | 1 | 51.6129% | -1.0676% | 0.7259 |

## Structural Trade Metrics

| Segment | Entries | Closed | Censored | Positive | Mean | PF | Compound | Drawdown | Hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |

## Four-Position Cash

- No nominated rule, so no block-5 cash account was constructed.

## D+1 Diagnostic

- Closed D+1 rows: `261`; D+1 positive: `45.5939%`.
- D+1 non-positive but structural exit positive: `41`.
- D+1 positive but structural exit non-positive: `21`.

## Reference Cases

| Date | Stock | Concept | Status | Rank | Opportunity | Support | D+1 | Exit | Reason | Net |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | --- | --- | ---: |
| 2025-07-08 | 东山精密 `002384.SZSE` | MiniLED | `structural_signal` | 2 | 2.0 | ma10 | 6.6354% | 2025-07-09 | higher_high_confirmed | 6.6354% |
| 2025-08-22 | 亨通光电 `600487.SSE` | 6G概念 | `structural_signal` | 3 | 2.0 | ma5 | 7.7552% | 2025-08-25 | higher_high_confirmed | 7.7552% |
| 2025-09-22 | 东山精密 `002384.SZSE` | OLED | `structural_signal` | 1 | 2.0 | ma10 | -4.5511% | - | split_boundary_censored | - |
| 2026-01-30 | 金安国纪 `002636.SZSE` | PCB | `rejected_reference_case` | 3 | 1.0 | ma10 | - | - | first_pullback_did_not_hold_ma5 | - |
| 2026-02-06 | 亨通光电 `600487.SSE` | 一带一路 | `structural_signal` | 1 | 3.0 | ma10 | 5.2223% | 2026-02-09 | higher_high_confirmed | 5.2223% |

## Input Fingerprints

| Input | Rows | Digest |
| --- | ---: | --- |
| `broad_gold_leader_features` | 56164 | `sha256:9f841a251908c1332239472036b84ab6ed88a35accf8416cb2c4701bb10f47b8` |
| `close_outcomes` | 56164 | `sha256:f2d19bb2f5283f2e3e276e23a061ba6afed4455565d8e94bb2626544fec474b2` |
| `eligible_reason_relations` | 7014 | `sha256:34c4446304883ed86f4e4ab635ccc359d52cacdf96dc5c622562051e45c7e063` |
| `structural_concept_bars` | 75807 | `sha256:2bfd3e68b81a1ecd8823601533808c77ef6aedd30715bb95fdaa21b2fe845e7c` |
| `structural_stock_bars` | 127791 | `sha256:0f0d69521e90e2266d1555ab668fab85aa25cba65e242f76504c2184bca1b264` |

## Boundaries

- entry rules and thresholds are unchanged from the D+1 v6 study
- all five historical blocks have prior research exposure
- D-close confirmation and D-close entry pricing are not executable fills
- each structural exit is confirmed by that completed bar and priced at the same close
- current concept memberships retain survivorship and point-in-time bias
- block 5 is read only after blocks 1..4 nominate one structural rule
- a historical pass still requires a new strict forward block
- no API, frontend, paper portfolio, or live strategy is changed

## Reproduce

```bash
python -m alphaagent.server.services.low_suction.cli v2-main-rise-structural-exit-study --format markdown
```
