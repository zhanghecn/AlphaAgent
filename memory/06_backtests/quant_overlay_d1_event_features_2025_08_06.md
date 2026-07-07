# Quant Overlay D+1 Event Features From 2025

## Dataset

- feature_rows: `1083821`
- feature_range: `2025-08-06` .. `2026-07-03`
- recommendation_rows: `4002`
- joined_rows: `3860`
- strategy: `mainline_dragon_pullback / 0.1.63`

## Current Quant Baseline

| action | rank_limit | n | win% | avg% | med% | limit% | up7% | down7% | down_limit% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BUY | 5 | 968 | 48.8636 | 0.3153 | 0.0 | 6.095 | 7.438 | 2.5826 | 0.9298 |
| BUY | 10 | 1874 | 49.1996 | 0.3886 | 0.0 | 5.8698 | 7.4707 | 2.3479 | 0.8004 |
| BUY | 20 | 2992 | 49.0307 | 0.3442 | 0.0 | 5.3142 | 6.885 | 2.4398 | 0.7687 |
| ALL | 5 | 1003 | 49.0528 | 0.3485 | 0.0 | 6.68 | 7.9761 | 2.7916 | 0.8973 |
| ALL | 10 | 1956 | 48.8753 | 0.3624 | 0.0 | 6.0327 | 7.5665 | 2.6074 | 0.818 |
| ALL | 20 | 3860 | 47.7202 | 0.2299 | -0.1375 | 4.9741 | 6.4767 | 2.487 | 0.7513 |

## BUY TopN Feature Overlay

| rank_limit | feature | n | win% | avg% | med% | limit% | up7% | down7% | down_limit% |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | BASE_BUY | 968 | 48.8636 | 0.3153 | 0.0 | 6.095 | 7.438 | 2.5826 | 0.9298 |
| 5 | active_source_compressed_high_close | 74 | 50.0 | 0.3654 | 0.1063 | 5.4054 | 6.7568 | 1.3514 | 0.0 |
| 5 | active_compressed_no_overheat | 59 | 52.5424 | 0.245 | 0.2747 | 3.3898 | 5.0847 | 1.6949 | 0.0 |
| 5 | deep_low_close_rebound_absorption | 1 | 100.0 | 0.7466 | 0.7466 | 0.0 | 0.0 | 0.0 | 0.0 |
| 5 | deep_low_core_group | 0 | None | None | None | None | None | None | None |
| 5 | deep_low_first_sun_confirm | 6 | 0.0 | -1.2749 | -0.6786 | 0.0 | 0.0 | 0.0 | 0.0 |
| 5 | deep_first_sun_clean | 4 | 0.0 | -1.668 | -1.7146 | 0.0 | 0.0 | 0.0 | 0.0 |
| 5 | positive_core_any | 63 | 49.2063 | 0.1235 | -0.1717 | 3.1746 | 4.7619 | 1.5873 | 0.0 |
| 5 | extreme_volume_intraday_fade | 0 | None | None | None | None | None | None | None |
| 5 | active_source_breakdown | 6 | 83.3333 | 5.543 | 7.9326 | 50.0 | 50.0 | 0.0 | 0.0 |
| 5 | hot_reacceleration_exhaustion | 0 | None | None | None | None | None | None | None |
| 5 | overheat_crowded_high_turnover | 125 | 53.6 | 0.5677 | 0.2682 | 11.2 | 13.6 | 5.6 | 2.4 |
| 5 | fade_or_breakdown_risk | 6 | 83.3333 | 5.543 | 7.9326 | 50.0 | 50.0 | 0.0 | 0.0 |
| 5 | risk_core_any | 127 | 53.5433 | 0.603 | 0.2682 | 11.811 | 14.1732 | 5.5118 | 2.3622 |
| 5 | weak_repair_high_close_no_source | 34 | 52.9412 | 0.409 | 0.3774 | 0.0 | 2.9412 | 2.9412 | 2.9412 |
| 10 | BASE_BUY | 1874 | 49.1996 | 0.3886 | 0.0 | 5.8698 | 7.4707 | 2.3479 | 0.8004 |
| 10 | active_source_compressed_high_close | 132 | 44.697 | 0.1276 | -0.6917 | 5.303 | 6.8182 | 2.2727 | 0.0 |
| 10 | active_compressed_no_overheat | 100 | 48.0 | 0.2841 | -0.3797 | 5.0 | 7.0 | 2.0 | 0.0 |
| 10 | deep_low_close_rebound_absorption | 1 | 100.0 | 0.7466 | 0.7466 | 0.0 | 0.0 | 0.0 | 0.0 |
| 10 | deep_low_core_group | 0 | None | None | None | None | None | None | None |
| 10 | deep_low_first_sun_confirm | 13 | 23.0769 | -0.7597 | -0.8681 | 0.0 | 0.0 | 0.0 | 0.0 |
| 10 | deep_first_sun_clean | 8 | 12.5 | -1.4118 | -1.0431 | 0.0 | 0.0 | 0.0 | 0.0 |
| 10 | positive_core_any | 108 | 45.3704 | 0.1585 | -0.565 | 4.6296 | 6.4815 | 1.8519 | 0.0 |
| 10 | extreme_volume_intraday_fade | 1 | 0.0 | -6.8273 | -6.8273 | 0.0 | 0.0 | 0.0 | 0.0 |
| 10 | active_source_breakdown | 16 | 56.25 | 2.1385 | 1.4023 | 25.0 | 25.0 | 6.25 | 0.0 |
| 10 | hot_reacceleration_exhaustion | 0 | None | None | None | None | None | None | None |
| 10 | overheat_crowded_high_turnover | 219 | 50.6849 | 0.6316 | 0.1585 | 12.7854 | 14.1553 | 5.9361 | 1.3699 |
| 10 | fade_or_breakdown_risk | 17 | 52.9412 | 1.6111 | 1.3831 | 23.5294 | 23.5294 | 5.8824 | 0.0 |
| 10 | risk_core_any | 224 | 50.4464 | 0.6495 | 0.1094 | 13.3929 | 14.7321 | 5.8036 | 1.3393 |
| 10 | weak_repair_high_close_no_source | 69 | 52.1739 | 0.4604 | 0.2034 | 1.4493 | 2.8986 | 1.4493 | 1.4493 |
| 20 | BASE_BUY | 2992 | 49.0307 | 0.3442 | 0.0 | 5.3142 | 6.885 | 2.4398 | 0.7687 |
| 20 | active_source_compressed_high_close | 187 | 41.1765 | -0.0565 | -0.6962 | 4.2781 | 6.4171 | 3.2086 | 0.0 |
| 20 | active_compressed_no_overheat | 144 | 43.75 | 0.0078 | -0.565 | 4.1667 | 6.25 | 2.7778 | 0.0 |
| 20 | deep_low_close_rebound_absorption | 1 | 100.0 | 0.7466 | 0.7466 | 0.0 | 0.0 | 0.0 | 0.0 |
| 20 | deep_low_core_group | 0 | None | None | None | None | None | None | None |
| 20 | deep_low_first_sun_confirm | 26 | 26.9231 | -0.0206 | -0.2375 | 3.8462 | 3.8462 | 0.0 | 0.0 |
| 20 | deep_first_sun_clean | 18 | 16.6667 | -0.5817 | -0.3671 | 0.0 | 0.0 | 0.0 | 0.0 |
| 20 | positive_core_any | 162 | 40.7407 | -0.0577 | -0.4647 | 3.7037 | 5.5556 | 2.4691 | 0.0 |
| 20 | extreme_volume_intraday_fade | 4 | 0.0 | -3.6295 | -3.4968 | 0.0 | 0.0 | 0.0 | 0.0 |
| 20 | active_source_breakdown | 26 | 38.4615 | 0.6215 | -1.0592 | 15.3846 | 19.2308 | 3.8462 | 0.0 |
| 20 | hot_reacceleration_exhaustion | 0 | None | None | None | None | None | None | None |
| 20 | overheat_crowded_high_turnover | 294 | 47.2789 | 0.3319 | -0.3544 | 11.9048 | 13.6054 | 6.4626 | 1.7007 |
| 20 | fade_or_breakdown_risk | 30 | 33.3333 | 0.0547 | -1.4209 | 13.3333 | 16.6667 | 3.3333 | 0.0 |
| 20 | risk_core_any | 309 | 45.9547 | 0.2856 | -0.6711 | 11.9741 | 13.9159 | 6.1489 | 1.6181 |
| 20 | weak_repair_high_close_no_source | 127 | 55.9055 | 0.4051 | 0.2418 | 0.7874 | 2.3622 | 0.7874 | 0.7874 |

## Full-Market Feature Capture By Current BUY Top20

| feature | all_n | all_win% | all_avg% | buy_top20_n | capture% | captured_win% | captured_avg% |
| --- | --- | --- | --- | --- | --- | --- | --- |
| deep_low_core_group | 4557 | 72.5477 | 1.8405 | 0 | 0.0 | None | None |
| deep_low_close_rebound_absorption | 25003 | 57.7251 | 0.5832 | 1 | 0.004 | 100.0 | 0.7466 |
| deep_first_sun_clean | 4320 | 51.088 | 0.2122 | 18 | 0.4167 | 16.6667 | -0.5817 |
| active_compressed_no_overheat | 4297 | 50.4305 | 0.5817 | 144 | 3.3512 | 43.75 | 0.0078 |
| overheat_crowded_high_turnover | 16669 | 43.2239 | -0.3718 | 294 | 1.7638 | 47.2789 | 0.3319 |

## BUY Top20 High-Return Feature Groups n>=5

| feature_group | n | win% | avg% | med% | limit% | up7% | down7% |
| --- | --- | --- | --- | --- | --- | --- | --- |
| high_momentum::first_sun_or_strong_close::active_high_turnover_proxy::multi_limit_source | 8 | 87.5 | 4.2846 | 3.6885 | 25.0 | 25.0 | 0.0 |
| neutral::ordinary::active::multi_limit_source | 10 | 80.0 | 3.6765 | 2.9451 | 20.0 | 20.0 | 0.0 |
| high_momentum::ordinary::normal::touched_but_not_closed_limit | 5 | 80.0 | 2.8133 | 1.4876 | 0.0 | 0.0 | 0.0 |
| low_repair::ordinary::active::no_limit_source | 12 | 58.3333 | 2.7604 | 0.8602 | 16.6667 | 25.0 | 0.0 |
| high_momentum::ordinary::active_high_turnover_proxy::single_limit_source | 12 | 66.6667 | 2.7321 | 1.7264 | 25.0 | 25.0 | 0.0 |
| high_momentum::low_close::normal_high_turnover_proxy::multi_limit_source | 5 | 40.0 | 2.665 | -0.3436 | 20.0 | 20.0 | 0.0 |
| high_momentum::low_close::normal::multi_limit_source | 26 | 61.5385 | 2.5546 | 1.4722 | 26.9231 | 26.9231 | 0.0 |
| neutral::ordinary::active::no_limit_source | 21 | 71.4286 | 2.4506 | 1.1978 | 14.2857 | 19.0476 | 0.0 |
| neutral::balanced_mid_close::active::single_limit_source | 13 | 46.1538 | 2.4337 | -0.2092 | 23.0769 | 23.0769 | 0.0 |
| high_momentum::low_close::normal::crowded_active_source | 5 | 100.0 | 2.3427 | 2.1658 | 0.0 | 0.0 | 0.0 |
| neutral::low_close::active::multi_limit_source | 5 | 60.0 | 2.3249 | 5.5725 | 20.0 | 20.0 | 20.0 |
| high_momentum::ordinary::normal::multi_limit_source | 29 | 68.9655 | 2.2154 | 1.4529 | 13.7931 | 24.1379 | 0.0 |
| neutral::low_close::contracted_low_turnover_proxy::no_limit_source | 5 | 80.0 | 2.195 | 2.259 | 0.0 | 0.0 | 0.0 |
| high_momentum::first_sun_or_strong_close::normal::single_limit_source | 15 | 66.6667 | 2.183 | 3.2049 | 6.6667 | 13.3333 | 0.0 |
| high_momentum::balanced_mid_close::active_high_turnover_proxy::crowded_active_source | 8 | 62.5 | 2.1659 | 2.0597 | 12.5 | 12.5 | 0.0 |
| neutral::high_close::contracted::no_limit_source | 6 | 83.3333 | 2.0213 | 1.4428 | 0.0 | 0.0 | 0.0 |
| high_momentum::high_close::normal::multi_limit_source | 10 | 60.0 | 1.9945 | 0.976 | 20.0 | 20.0 | 0.0 |
| neutral::low_close::active::single_limit_source | 12 | 75.0 | 1.9902 | 1.2675 | 8.3333 | 16.6667 | 0.0 |
| high_momentum::balanced_mid_close::active::single_limit_source | 17 | 64.7059 | 1.9408 | 1.3333 | 5.8824 | 17.6471 | 0.0 |
| high_momentum::ordinary::hot::multi_limit_source | 5 | 60.0 | 1.7319 | 2.2305 | 20.0 | 20.0 | 0.0 |
| high_momentum::compressed_mid_close::normal::touched_but_not_closed_limit | 7 | 57.1429 | 1.7165 | 2.1531 | 14.2857 | 14.2857 | 0.0 |
| neutral::first_sun_or_strong_close::active_high_turnover_proxy::single_limit_source | 9 | 55.5556 | 1.707 | 1.8217 | 11.1111 | 11.1111 | 0.0 |
| high_momentum::compressed_mid_close::normal_high_turnover_proxy::multi_limit_source | 5 | 40.0 | 1.6805 | -0.885 | 20.0 | 20.0 | 0.0 |
| high_momentum::balanced_mid_close::active::no_limit_source | 5 | 60.0 | 1.6471 | 1.6384 | 0.0 | 0.0 | 0.0 |
| high_momentum::ordinary::active::single_limit_source | 26 | 65.3846 | 1.5995 | 0.9138 | 11.5385 | 11.5385 | 3.8462 |
| low_repair::compressed_mid_close::contracted::no_limit_source | 6 | 100.0 | 1.5662 | 1.1822 | 0.0 | 0.0 | 0.0 |
| neutral::low_close::normal::single_limit_source | 32 | 68.75 | 1.5576 | 1.0765 | 6.25 | 12.5 | 6.25 |
| high_momentum::low_close::active::single_limit_source | 5 | 60.0 | 1.555 | 1.7062 | 0.0 | 0.0 | 0.0 |
| neutral::compressed_mid_close::normal::single_limit_source | 31 | 54.8387 | 1.5471 | 0.948 | 9.6774 | 9.6774 | 0.0 |
| neutral::compressed_mid_close::normal::no_limit_source | 17 | 58.8235 | 1.5457 | 0.3177 | 5.8824 | 11.7647 | 0.0 |

## BUY Top20 High-Risk Feature Groups n>=5

| feature_group | n | win% | avg% | med% | limit% | up7% | down7% |
| --- | --- | --- | --- | --- | --- | --- | --- |
| high_momentum::first_sun_or_strong_close::normal_high_turnover_proxy::multi_limit_source | 5 | 20.0 | -2.3832 | -3.3306 | 0.0 | 0.0 | 20.0 |
| neutral::low_close::active::multi_limit_source | 5 | 60.0 | 2.3249 | 5.5725 | 20.0 | 20.0 | 20.0 |
| neutral::first_sun_or_strong_close::active::touched_but_not_closed_limit | 6 | 33.3333 | -3.0265 | -2.98 | 0.0 | 0.0 | 16.6667 |
| high_momentum::intraday_fade::active_high_turnover_proxy::multi_limit_source | 6 | 50.0 | -0.0122 | -0.1886 | 16.6667 | 16.6667 | 16.6667 |
| high_momentum::balanced_mid_close::active::crowded_active_source | 6 | 50.0 | 1.2343 | 0.1784 | 33.3333 | 33.3333 | 16.6667 |
| high_momentum::ordinary::active_high_turnover_proxy::crowded_active_source | 20 | 45.0 | 0.0668 | -2.0971 | 15.0 | 15.0 | 15.0 |
| neutral::balanced_mid_close::normal::multi_limit_source | 21 | 42.8571 | -1.5998 | -1.148 | 4.7619 | 4.7619 | 14.2857 |
| neutral::compressed_mid_close::normal_high_turnover_proxy::single_limit_source | 8 | 37.5 | -0.8285 | -2.4989 | 12.5 | 12.5 | 12.5 |
| high_momentum::ordinary::active::crowded_active_source | 9 | 33.3333 | -1.1708 | -1.1167 | 0.0 | 0.0 | 11.1111 |
| high_momentum::compressed_mid_close::contracted::crowded_active_source | 9 | 55.5556 | -0.7894 | 0.6276 | 0.0 | 0.0 | 11.1111 |
| neutral::ordinary::contracted::multi_limit_source | 9 | 66.6667 | 0.7727 | 1.5152 | 11.1111 | 11.1111 | 11.1111 |
| neutral::high_close::normal_high_turnover_proxy::multi_limit_source | 9 | 55.5556 | 1.5092 | 1.7673 | 22.2222 | 22.2222 | 11.1111 |
| neutral::ordinary::normal_high_turnover_proxy::single_limit_source | 19 | 52.6316 | -0.5543 | 0.4779 | 5.2632 | 5.2632 | 10.5263 |
| high_momentum::ordinary::normal_high_turnover_proxy::crowded_active_source | 19 | 42.1053 | 0.3919 | -0.5925 | 15.7895 | 21.0526 | 10.5263 |
| neutral::high_close::active::no_limit_source | 11 | 63.6364 | -0.9622 | 0.7812 | 0.0 | 0.0 | 9.0909 |
| high_momentum::compressed_mid_close::normal_high_turnover_proxy::crowded_active_source | 11 | 45.4545 | 0.0079 | -0.3651 | 9.0909 | 9.0909 | 9.0909 |
| high_momentum::ordinary::active_high_turnover_proxy::multi_limit_source | 34 | 41.1765 | -1.104 | -1.939 | 2.9412 | 5.8824 | 8.8235 |
| high_momentum::balanced_mid_close::normal_high_turnover_proxy::multi_limit_source | 12 | 25.0 | -1.6981 | -3.4879 | 8.3333 | 8.3333 | 8.3333 |
| neutral::balanced_mid_close::normal_high_turnover_proxy::single_limit_source | 12 | 41.6667 | -0.7242 | -1.8272 | 0.0 | 0.0 | 8.3333 |
| neutral::balanced_mid_close::active::no_limit_source | 13 | 53.8462 | -0.6627 | 0.4982 | 0.0 | 0.0 | 7.6923 |
| high_momentum::intraday_fade::active_high_turnover_proxy::crowded_active_source | 13 | 46.1538 | -0.0448 | -0.9404 | 15.3846 | 15.3846 | 7.6923 |
| neutral::compressed_mid_close::normal::touched_but_not_closed_limit | 13 | 38.4615 | 0.0639 | -0.8511 | 7.6923 | 15.3846 | 7.6923 |
| neutral::low_close::normal::no_limit_source | 13 | 61.5385 | 0.5498 | 0.7589 | 0.0 | 7.6923 | 7.6923 |
| neutral::first_sun_or_strong_close::active_high_turnover_proxy::multi_limit_source | 14 | 64.2857 | 0.3851 | 0.4516 | 0.0 | 7.1429 | 7.1429 |
| neutral::ordinary::active::single_limit_source | 28 | 64.2857 | 1.2384 | 1.6673 | 0.0 | 3.5714 | 7.1429 |
| high_momentum::compressed_mid_close::normal::multi_limit_source | 30 | 40.0 | -0.8766 | -1.4915 | 0.0 | 0.0 | 6.6667 |
| neutral::first_sun_or_strong_close::active::single_limit_source | 30 | 46.6667 | -0.6096 | -0.0952 | 3.3333 | 3.3333 | 6.6667 |
| neutral::balanced_mid_close::normal::no_limit_source | 30 | 53.3333 | 0.0859 | 0.1161 | 0.0 | 0.0 | 6.6667 |
| high_momentum::balanced_mid_close::active::multi_limit_source | 16 | 50.0 | 0.5594 | -0.1745 | 6.25 | 18.75 | 6.25 |
| neutral::low_close::normal::single_limit_source | 32 | 68.75 | 1.5576 | 1.0765 | 6.25 | 12.5 | 6.25 |

## BUY Top20 Positive Feature Big Up Samples

| trade_date | vt_symbol | name | rank | action | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | ret20 | ma20_dist_pct | vol_vs_ma20 | amount_vs_ma20 | turnover_to_market_cap_pct | prior_limit_up_20d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-15 | 600888.SSE | 新疆众和 | 6 | BUY | 10.0441 | 3.9377 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 34.4787 | 4.248 | 0.8973 | 0.9238 | 5.1865 | 1.0 |
| 2026-02-03 | 002810.SZSE | 山东赫达 | 6 | BUY | 10.0167 | 5.5817 | neutral | first_sun_or_strong_close | normal | mixed_volume | multi_limit_source | 23.3356 | 9.6869 | 0.997 | 1.0718 | 3.9042 | 2.0 |
| 2026-03-18 | 603629.SSE | DR利通电 | 6 | BUY | 10.0032 | 6.4327 | neutral | first_sun_or_strong_close | normal | multi_day_contraction | crowded_active_source | 19.1604 | 5.2802 | 0.6983 | 0.711 | 3.7262 | 4.0 |
| 2026-06-10 | 603991.SSE | 领先股份 | 5 | BUY | 10.0018 | 3.8783 | low_repair | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | -13.9934 | -4.0579 | 0.9219 | 0.8582 | 1.1501 | 1.0 |
| 2026-06-09 | 002409.SZSE | 雅克科技 | 2 | BUY | 9.9991 | 5.4819 | neutral | first_sun_or_strong_close | contracted | multi_day_contraction | multi_limit_source | 18.6981 | -1.8306 | 0.6674 | 0.6397 | 2.6014 | 2.0 |
| 2026-06-09 | 600206.SSE | 有研新材 | 15 | BUY | 9.9966 | 5.6216 | neutral | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | -8.1767 | -0.9396 | 0.7529 | 0.7122 | 3.5097 | 1.0 |
| 2025-10-24 | 601138.SSE | 工业富联 | 14 | BUY | 8.1933 | 5.0945 | neutral | first_sun_or_strong_close | normal_low_turnover_proxy | mixed_volume | single_limit_source | 4.4904 | 2.3732 | 0.9304 | 0.9345 | 0.9391 | 1.0 |
| 2026-06-16 | 002787.SZSE | 华源控股 | 10 | BUY | 7.9005 | 4.7108 | neutral | first_sun_or_strong_close | contracted | volume_contracting_three_day | multi_limit_source | 6.7135 | 3.5057 | 0.6579 | 0.6692 | 4.1202 | 3.0 |
| 2026-05-25 | 002134.SZSE | 天津普林 | 5 | BUY | 7.2549 | 3.2389 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 30.7692 | 9.0987 | 0.8656 | 0.9449 | 5.2484 | 1.0 |

## BUY Top20 Positive Feature Failure Samples

| trade_date | vt_symbol | name | rank | action | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | ret20 | ma20_dist_pct | vol_vs_ma20 | amount_vs_ma20 | turnover_to_market_cap_pct | prior_limit_up_20d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-12-17 | 603067.SSE | 振华股份 | 13 | BUY | -8.2787 | 4.1682 | neutral | first_sun_or_strong_close | contracted | volume_contracting_three_day | single_limit_source | 2.2214 | 3.8714 | 0.6842 | 0.69 | 2.0954 | 1.0 |
| 2026-05-28 | 603375.SSE | 盛景微 | 11 | BUY | -7.6807 | 3.4038 | neutral | first_sun_or_strong_close | normal | volume_contracting_three_day | multi_limit_source | 24.9055 | 8.9908 | 0.8951 | 0.9709 | 5.3272 | 2.0 |
| 2026-06-24 | 603931.SSE | 格林达 | 3 | BUY | -7.4564 | 3.2883 | neutral | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | -0.6988 | 1.3294 | 0.8339 | 0.8041 | 4.7756 | 1.0 |
| 2026-05-28 | 603285.SSE | 键邦股份 | 9 | BUY | -7.2481 | 4.8141 | neutral | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 22.1013 | 5.9755 | 0.7449 | 0.7709 | 2.6025 | 1.0 |

## BUY Top20 Risk Feature Big Down Samples

| trade_date | vt_symbol | name | rank | action | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | ret20 | ma20_dist_pct | vol_vs_ma20 | amount_vs_ma20 | turnover_to_market_cap_pct | prior_limit_up_20d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-11-20 | 603396.SSE | 金辰股份 | 15 | BUY | -10.0 | -2.8278 | high_momentum | ordinary | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 36.4621 | 14.8884 | 1.5816 | 1.7082 | 17.1826 | 2.0 |
| 2026-03-25 | 000890.SZSE | 法尔胜 | 4 | BUY | -9.9927 | 6.4113 | extreme_hot | ordinary | active_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 86.6941 | 27.7395 | 0.8623 | 1.1601 | 39.5411 | 8.0 |
| 2025-12-30 | 002682.SZSE | 龙洲股份 | 11 | BUY | -9.979 | -0.5225 | high_momentum | intraday_fade | active_high_turnover_proxy | volume_rising_three_day | crowded_active_source | 60.8108 | 3.2986 | 1.4179 | 1.5294 | 89.2898 | 9.0 |
| 2026-05-29 | 603083.SSE | 剑桥科技 | 1 | BUY | -9.9663 | 2.2951 | high_momentum | intraday_fade | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 33.8359 | 8.7255 | 1.1923 | 1.3309 | 11.1474 | 3.0 |
| 2025-10-17 | 002716.SZSE | 湖南白银 | 4 | BUY | -9.9502 | 4.2802 | high_momentum | ordinary | active_high_turnover_proxy | volume_rising_three_day | multi_limit_source | 33.777 | 15.2523 | 1.2802 | 1.4631 | 12.2328 | 2.0 |
| 2026-06-17 | 001896.SZSE | 豫能控股 | 2 | BUY | -8.7776 | -1.3599 | high_momentum | intraday_fade | normal_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 46.2366 | 13.567 | 0.9635 | 1.1097 | 21.1582 | 4.0 |
| 2026-06-04 | 000600.SZSE | 建投能源 | 7 | BUY | -8.6714 | 0.9639 | high_momentum | balanced_mid_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 25.7 | 16.2651 | 1.4153 | 1.6205 | 10.1871 | 2.0 |
| 2026-03-20 | 002015.SZSE | 协鑫能科 | 10 | BUY | -8.6538 | 3.1746 | high_momentum | ordinary | hot_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 65.0794 | 23.3287 | 1.9071 | 2.1668 | 32.3745 | 4.0 |
| 2026-07-03 | 600110.SSE | 诺德股份 | 1 | BUY | -8.6349 | 8.3964 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 36.4818 | 8.5758 | 1.2603 | 1.4823 | 14.4422 | 4.0 |
| 2026-02-04 | 603212.SSE | 赛伍技术 | 19 | BUY | -7.6797 | 4.4963 | high_momentum | ordinary | active_high_turnover_proxy | volume_rising_three_day | multi_limit_source | 26.6207 | 15.8652 | 1.4562 | 1.6566 | 28.8526 | 2.0 |
| 2025-12-08 | 000566.SZSE | 海南海药 | 5 | BUY | -7.6741 | 4.0541 | high_momentum | ordinary | normal_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 33.3858 | 9.8716 | 1.0344 | 1.098 | 24.9673 | 4.0 |
| 2026-07-02 | 603399.SSE | 永杉锂业 | 6 | BUY | -7.2786 | -5.0616 | high_momentum | panic_low_close | normal_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 28.3929 | 7.1242 | 0.7285 | 0.7932 | 16.0996 | 3.0 |
| 2026-03-02 | 603138.SSE | 海量数据 | 13 | BUY | -7.2646 | -2.193 | high_momentum | ordinary | active_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 24.3032 | 14.597 | 1.0263 | 1.1526 | 19.2955 | 4.0 |
| 2026-06-04 | 600172.SSE | 黄河旋风 | 1 | BUY | -7.2514 | -3.7234 | high_momentum | ordinary | active_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 63.8009 | 19.704 | 1.2054 | 1.4034 | 14.8834 | 7.0 |
| 2025-11-20 | 000555.SZSE | 神州信息 | 9 | BUY | -7.1888 | 2.6432 | high_momentum | ordinary | normal_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 30.807 | 0.0322 | 0.7437 | 0.7424 | 21.1734 | 4.0 |
| 2025-11-17 | 605188.SSE | 国光连锁 | 10 | BUY | -7.1511 | 0.8922 | high_momentum | compressed_mid_close | normal_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 40.5946 | 10.6173 | 0.77 | 0.8434 | 14.0256 | 5.0 |
| 2025-12-08 | 600272.SSE | XD开开实 | 13 | BUY | -7.0414 | 0.2372 | high_momentum | balanced_mid_close | normal_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 23.9003 | 11.06 | 1.0472 | 1.1449 | 14.6638 | 2.0 |
| 2026-01-27 | 000681.SZSE | 视觉中国 | 12 | BUY | -7.0332 | 3.9718 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 28.6633 | 2.9931 | 0.9468 | 0.915 | 20.8162 | 3.0 |
| 2025-11-20 | 002255.SZSE | 海陆重工 | 7 | BUY | -7.0149 | -3.7356 | high_momentum | ordinary | active_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 48.3942 | 13.5497 | 1.4223 | 1.4826 | 31.855 | 6.0 |

## BUY Top20 Missed Deep Low Core Winners Nearby

| trade_date | vt_symbol | name | rank | action | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | ret20 | ma20_dist_pct | vol_vs_ma20 | amount_vs_ma20 | turnover_to_market_cap_pct | prior_limit_up_20d |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-08 | 688711.SSE | 宏微科技 | None | None | 20.0067 | -11.3033 | deep_oversold | panic_low_close | normal | volume_contracting_three_day | no_limit_source | -3.0007 | -12.1405 | 0.7911 | 0.7171 | 5.7851 | 0.0 |
| 2026-05-29 | 301236.SZSE | 软通动力 | None | None | 20.0061 | -6.3227 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -16.6498 | -16.3195 | 1.1503 | 0.9783 | 2.217 | 0.0 |
| 2026-03-03 | 688525.SSE | 佰维存储 | None | None | 19.9986 | -8.6231 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | -18.7929 | -13.4639 | 1.2098 | 1.0543 | 2.3163 | 0.0 |
| 2026-06-08 | 688500.SSE | 慧辰股份 | None | None | 19.9955 | -8.5892 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -10.1916 | -19.7282 | 0.8959 | 0.7225 | 5.5977 | 0.0 |
| 2026-06-26 | 688336.SSE | 三生国健 | None | None | 19.9952 | -6.8315 | deep_oversold | panic_low_close | active | volume_contracting_three_day | no_limit_source | -30.0725 | -21.7078 | 1.404 | 1.1732 | 1.0946 | 0.0 |
| 2026-04-09 | 300561.SZSE | 汇金科技 | None | None | 19.9823 | -20.0141 | deep_oversold | panic_low_close | active | volume_rising_three_day | no_limit_source | -11.5023 | -13.177 | 1.5216 | 1.5882 | 4.1234 | 0.0 |
| 2026-04-03 | 300165.SZSE | 天瑞仪器 | None | None | 19.9557 | -5.2521 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -18.5921 | -14.5267 | 1.0715 | 0.9249 | 2.8278 | 0.0 |
| 2025-12-23 | 300225.SZSE | 金力泰 | None | None | 19.0583 | -5.3079 | deep_oversold | panic_low_close | active | volume_contracting_three_day | no_limit_source | -26.8852 | -15.8967 | 1.7586 | 1.5655 | 2.7275 | 0.0 |
| 2026-04-03 | 301024.SZSE | 霍普股份 | None | None | 16.8764 | -5.1133 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -22.3892 | -14.1694 | 0.9469 | 0.8137 | 1.6722 | 0.0 |
| 2026-03-23 | 301183.SZSE | 东田微 | None | None | 16.4591 | -7.544 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -13.6904 | -11.5981 | 1.0649 | 0.9465 | 4.7886 | 0.0 |
| 2026-03-23 | 301357.SZSE | 北方长龙 | None | None | 16.4388 | -9.1547 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -24.2229 | -20.9964 | 0.9617 | 0.7398 | 3.8142 | 0.0 |
| 2026-06-08 | 688556.SSE | 高测股份 | None | None | 16.1694 | -5.4595 | deep_oversold | panic_low_close | contracted | multi_day_contraction | no_limit_source | -31.0093 | -19.7993 | 0.7831 | 0.618 | 4.5207 | 0.0 |
| 2026-06-08 | 300316.SZSE | 晶盛机电 | None | None | 16.1495 | -6.4021 | deep_oversold | panic_low_close | contracted | multi_day_contraction | no_limit_source | -4.047 | -11.4817 | 0.6518 | 0.5831 | 2.2563 | 0.0 |
| 2026-05-27 | 688661.SSE | 和林微纳 | None | None | 16.0733 | -9.0171 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | -2.7854 | -12.4794 | 1.0831 | 0.9929 | 3.7633 | 0.0 |
| 2026-06-12 | 688261.SSE | 东微半导 | None | None | 15.7548 | -5.6592 | deep_oversold | panic_low_close | contracted | multi_day_contraction | no_limit_source | -8.8998 | -10.2234 | 0.6142 | 0.5637 | 3.5433 | 0.0 |
| 2026-03-03 | 301308.SZSE | 江波龙 | None | None | 14.8688 | -7.0959 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | -27.0735 | -14.2181 | 0.9366 | 0.7948 | 1.2308 | 0.0 |
| 2026-05-29 | 301395.SZSE | 仁信新材 | None | None | 14.7857 | -5.2239 | deep_oversold | panic_low_close | contracted | multi_day_contraction | no_limit_source | -11.6009 | -17.2638 | 0.5877 | 0.4846 | 1.3601 | 0.0 |
| 2026-03-23 | 688603.SSE | 天承科技 | None | None | 14.4322 | -8.4369 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | -14.9654 | -19.212 | 0.8753 | 0.7119 | 1.1117 | 0.0 |
| 2026-06-08 | 300606.SZSE | 金太阳 | None | None | 14.1827 | -5.1582 | deep_oversold | panic_low_close | contracted | mixed_volume | no_limit_source | -17.0075 | -11.5446 | 0.6793 | 0.594 | 5.6241 | 0.0 |
| 2026-04-24 | 300469.SZSE | 信息发展 | None | None | 13.5943 | -5.6581 | deep_oversold | panic_low_close | active | volume_rising_three_day | no_limit_source | -23.3177 | -14.3089 | 1.4554 | 1.252 | 4.3216 | 0.0 |
| 2026-06-26 | 688117.SSE | 圣诺生物 | None | None | 13.5227 | -5.1849 | deep_oversold | panic_low_close | active | mixed_volume | no_limit_source | -31.1442 | -8.8573 | 1.3465 | 1.287 | 1.7267 | 0.0 |
| 2026-03-23 | 300713.SZSE | 英可瑞 | None | None | 12.935 | -8.0314 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | -16.1344 | -17.7001 | 0.9664 | 0.8063 | 5.4966 | 0.0 |
| 2026-03-31 | 688025.SSE | 杰普特 | None | None | 12.8806 | -8.994 | deep_oversold | panic_low_close | active | mixed_volume | no_limit_source | -21.9264 | -7.2356 | 1.445 | 1.3244 | 4.4651 | 0.0 |
| 2026-06-03 | 300382.SZSE | 斯莱克 | None | None | 12.6712 | -8.5786 | deep_oversold | panic_low_close | active | mixed_volume | no_limit_source | -9.0909 | -10.0348 | 1.4258 | 1.3097 | 4.7636 | 0.0 |
