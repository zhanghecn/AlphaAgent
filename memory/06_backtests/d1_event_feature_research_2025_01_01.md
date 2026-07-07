# D+1 Event Feature Research Set

## Dataset

- rows: `1298035`
- symbols: `4997`
- days: `363`
- range: `2025-01-02` .. `2026-07-06`

## Baseline

- n: `1298035`
- win_rate: `48.0503`
- avg_return: `0.0935`
- median_return: `0.0`
- d1_limit_rate: `1.3466`
- d1_big_up7_rate: `2.8133`
- d1_big_down7_rate: `1.2034`

## Feature Flags

| flag | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_up7_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hot_reacceleration_exhaustion | 1474 | 52.6459 | 0.7504 | 0.488 | 15.8073 | 23.8806 | 16.5536 |
| active_source_compressed_high_close | 7340 | 50.7902 | 0.6193 | 0.1238 | 8.5559 | 12.0163 | 5.1907 |
| deep_low_close_rebound_absorption | 25796 | 57.3771 | 0.5565 | 0.5457 | 1.256 | 3.4114 | 1.4925 |
| deep_low_first_sun_confirm | 5601 | 49.4912 | 0.1536 | 0.0 | 1.6961 | 3.7672 | 1.1962 |
| weak_repair_high_close_no_source | 130034 | 46.9016 | 0.0271 | 0.0 | 0.4714 | 1.0459 | 0.2269 |
| active_source_breakdown | 16115 | 44.5734 | -0.1844 | -0.5089 | 5.3553 | 8.1601 | 6.4722 |
| extreme_volume_intraday_fade | 9124 | 43.3363 | -0.2643 | -0.7831 | 5.5677 | 9.6449 | 8.6256 |

## Stacked Feature Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_up7_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| high_momentum::ordinary::contracted_low_turnover_proxy::no_limit_source | 156 | 75.641 | 3.522 | 4.876 | 12.1795 | 13.4615 | 0.0 |
| high_momentum::first_sun_or_strong_close::contracted::crowded_active_source | 123 | 65.8537 | 2.9677 | 3.7594 | 26.8293 | 30.8943 | 5.6911 |
| deep_oversold::panic_low_close::active::no_limit_source | 1307 | 76.2816 | 2.4201 | 3.0392 | 0.5356 | 4.7437 | 1.3007 |
| high_momentum::ordinary::contracted::multi_limit_source | 307 | 56.3518 | 2.0433 | 1.1138 | 27.6873 | 30.2932 | 7.8176 |
| deep_oversold::panic_low_close::normal_low_turnover_proxy::no_limit_source | 140 | 79.2857 | 2.0003 | 2.2829 | 0.0 | 2.8571 | 0.0 |
| high_momentum::first_sun_or_strong_close::contracted::multi_limit_source | 158 | 58.8608 | 1.9861 | 1.3653 | 20.2532 | 24.6835 | 6.3291 |
| deep_oversold::panic_low_close::normal::no_limit_source | 2385 | 70.8595 | 1.6329 | 1.9249 | 0.7128 | 3.3962 | 1.2579 |
| high_momentum::first_sun_or_strong_close::normal::crowded_active_source | 175 | 53.1429 | 1.6255 | 0.6282 | 23.4286 | 27.4286 | 8.0 |
| high_momentum::ordinary::contracted::single_limit_source | 269 | 53.1599 | 1.5644 | 0.2618 | 18.9591 | 20.8178 | 1.8587 |
| high_momentum::panic_low_close::normal::single_limit_source | 203 | 56.1576 | 1.5477 | 0.3766 | 3.4483 | 14.2857 | 2.4631 |
| deep_oversold::panic_low_close::contracted::no_limit_source | 917 | 69.1385 | 1.3663 | 1.5699 | 0.7634 | 4.4711 | 1.4177 |
| deep_oversold::intraday_fade::normal::no_limit_source | 280 | 56.7857 | 1.3569 | 0.5919 | 1.7857 | 12.1429 | 2.8571 |
| deep_oversold::panic_low_close::normal::touched_but_not_closed_limit | 265 | 58.8679 | 1.2795 | 1.0934 | 3.0189 | 7.9245 | 1.8868 |
| high_momentum::ordinary::contracted::crowded_active_source | 153 | 52.9412 | 1.2581 | 0.7547 | 26.7974 | 30.0654 | 13.0719 |
| high_momentum::first_sun_or_strong_close::extreme::multi_limit_source | 191 | 53.4031 | 1.2206 | 0.4021 | 23.5602 | 27.2251 | 10.4712 |
| deep_oversold::low_close::contracted::crowded_active_source | 135 | 63.7037 | 1.2104 | 1.2329 | 5.9259 | 7.4074 | 0.7407 |
| low_repair::panic_low_close::normal_low_turnover_proxy::no_limit_source | 213 | 66.6667 | 1.2088 | 0.8534 | 0.0 | 3.7559 | 0.939 |
| high_momentum::ordinary::active_low_turnover_proxy::no_limit_source | 170 | 53.5294 | 1.1986 | 0.1711 | 4.7059 | 11.7647 | 1.7647 |
| high_momentum::intraday_fade::normal::no_limit_source | 149 | 55.7047 | 1.185 | 1.0893 | 0.6711 | 14.094 | 6.0403 |
| high_momentum::first_sun_or_strong_close::active::crowded_active_source | 123 | 50.4065 | 1.18 | 0.1047 | 19.5122 | 26.0163 | 9.7561 |
| high_momentum::ordinary::normal_low_turnover_proxy::no_limit_source | 180 | 48.8889 | 1.1747 | -0.046 | 4.4444 | 10.5556 | 0.5556 |
| high_momentum::first_sun_or_strong_close::normal::multi_limit_source | 594 | 54.2088 | 1.1152 | 0.4625 | 12.6263 | 16.33 | 4.2088 |
| high_momentum::first_sun_or_strong_close::normal_low_turnover_proxy::no_limit_source | 200 | 53.5 | 1.1038 | 0.2443 | 1.5 | 7.0 | 1.0 |
| deep_oversold::panic_low_close::contracted::touched_but_not_closed_limit | 233 | 60.9442 | 1.0502 | 0.9352 | 3.4335 | 7.2961 | 2.5751 |
| high_momentum::intraday_fade::active::multi_limit_source | 141 | 49.6454 | 1.0428 | 0.0 | 7.8014 | 15.6028 | 2.1277 |
| high_momentum::first_sun_or_strong_close::contracted::single_limit_source | 141 | 46.8085 | 1.0163 | -0.1134 | 11.3475 | 18.4397 | 3.5461 |
| high_momentum::first_sun_or_strong_close::extreme::no_limit_source | 2486 | 49.638 | 1.0048 | 0.0 | 7.2003 | 12.9928 | 2.856 |
| high_momentum::first_sun_or_strong_close::normal_high_turnover_proxy::crowded_active_source | 258 | 53.1008 | 1.0042 | 0.5872 | 15.8915 | 18.6047 | 8.5271 |
| extreme_hot::first_sun_or_strong_close::active_high_turnover_proxy::crowded_active_source | 196 | 54.5918 | 1.0 | 0.7153 | 18.8776 | 23.4694 | 12.7551 |
| high_momentum::first_sun_or_strong_close::extreme::single_limit_source | 564 | 48.5816 | 0.9967 | -0.1315 | 15.4255 | 20.3901 | 6.0284 |
| high_momentum::first_sun_or_strong_close::hot::multi_limit_source | 346 | 54.0462 | 0.9785 | 0.2921 | 13.2948 | 17.9191 | 6.9364 |
| high_momentum::ordinary::normal::touched_but_not_closed_limit | 528 | 50.7576 | 0.9597 | 0.1453 | 3.2197 | 12.1212 | 3.9773 |
| high_momentum::compressed_mid_close::normal_low_turnover_proxy::no_limit_source | 193 | 54.9223 | 0.9484 | 0.5515 | 0.5181 | 6.7358 | 1.0363 |
| deep_oversold::intraday_fade::active::no_limit_source | 178 | 52.809 | 0.9402 | 0.5887 | 2.2472 | 6.1798 | 0.5618 |
| high_momentum::intraday_fade::active::no_limit_source | 402 | 49.2537 | 0.9308 | -0.1066 | 2.4876 | 12.6866 | 4.9751 |
| low_repair::intraday_fade::normal::no_limit_source | 455 | 52.7473 | 0.9215 | 0.5471 | 2.1978 | 10.989 | 3.5165 |
| deep_oversold::panic_low_close::contracted::multi_limit_source | 185 | 57.2973 | 0.9026 | 0.5882 | 5.4054 | 7.5676 | 3.2432 |
| low_repair::intraday_fade::normal::single_limit_source | 127 | 50.3937 | 0.8999 | 0.1399 | 5.5118 | 11.0236 | 3.1496 |
| low_repair::panic_low_close::contracted::touched_but_not_closed_limit | 161 | 56.5217 | 0.8772 | 0.5753 | 3.1056 | 6.2112 | 1.2422 |
| high_momentum::balanced_mid_close::normal_high_turnover_proxy::single_limit_source | 132 | 51.5152 | 0.8712 | 0.2062 | 4.5455 | 12.1212 | 2.2727 |

## Volume And Turnover Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- |
| volume_history_unknown::normal_high_turnover_proxy | 126 | 75.3968 | 2.5631 | 1.2962 | 7.9365 | 0.7937 |
| volume_history_unknown::contracted | 504 | 74.4048 | 1.2503 | 0.8924 | 0.7937 | 0.1984 |
| mixed_volume::extreme_low_turnover_proxy | 136 | 50.0 | 1.1758 | 0.0938 | 4.4118 | 1.4706 |
| volume_history_unknown::normal | 1339 | 72.4421 | 0.9471 | 0.7015 | 1.1202 | 0.2987 |
| volume_history_unknown::contracted_low_turnover_proxy | 182 | 67.033 | 0.9261 | 0.5869 | 0.5495 | 0.0 |
| volume_history_unknown::normal_low_turnover_proxy | 841 | 65.6361 | 0.7059 | 0.463 | 0.5945 | 0.0 |
| volume_history_unknown::active | 830 | 62.7711 | 0.6808 | 0.4363 | 0.3614 | 0.3614 |
| volume_history_unknown::hot | 265 | 52.0755 | 0.491 | 0.1269 | 0.7547 | 0.0 |
| sudden_volume_expansion::extreme | 3277 | 46.506 | 0.4816 | -0.2114 | 4.8215 | 1.4037 |
| volume_rising_three_day::extreme_low_turnover_proxy | 219 | 45.2055 | 0.4158 | -0.2508 | 2.7397 | 0.9132 |
| volume_contracting_three_day::hot_low_turnover_proxy | 215 | 50.6977 | 0.3993 | 0.0378 | 0.4651 | 0.4651 |
| volume_contracting_three_day::extreme | 741 | 45.614 | 0.3315 | -0.4545 | 5.3981 | 5.3981 |
| volume_history_unknown::active_low_turnover_proxy | 416 | 57.6923 | 0.3241 | 0.2029 | 0.0 | 0.0 |
| volume_rising_three_day::hot_low_turnover_proxy | 1676 | 48.0907 | 0.3221 | 0.0 | 1.611 | 0.4177 |
| mixed_volume::extreme | 6150 | 45.6911 | 0.3112 | -0.2656 | 3.8537 | 2.3902 |
| mixed_volume::hot_low_turnover_proxy | 1834 | 47.4918 | 0.3109 | -0.0114 | 1.3086 | 0.3272 |
| volume_contracting_three_day::active_low_turnover_proxy | 3497 | 50.7578 | 0.3042 | 0.0698 | 1.0295 | 0.4003 |
| mixed_volume::active_low_turnover_proxy | 20010 | 50.8196 | 0.266 | 0.0651 | 0.6297 | 0.1999 |
| mixed_volume::hot | 26493 | 46.484 | 0.2483 | -0.1536 | 2.3893 | 1.4721 |
| volume_contracting_three_day::hot | 5167 | 45.8874 | 0.2446 | -0.2755 | 2.7289 | 2.2644 |
| mixed_volume::contracted_low_turnover_proxy | 19722 | 51.9521 | 0.2396 | 0.1125 | 0.649 | 0.2485 |
| volume_rising_three_day::active_low_turnover_proxy | 8831 | 49.3602 | 0.2372 | 0.0 | 0.6228 | 0.2604 |
| volume_rising_three_day::extreme | 8448 | 44.1051 | 0.2085 | -0.4044 | 3.7879 | 1.8348 |
| multi_day_contraction::contracted_low_turnover_proxy | 72477 | 51.3377 | 0.2083 | 0.0901 | 0.5022 | 0.1849 |
| volume_rising_three_day::hot | 19036 | 45.7291 | 0.2074 | -0.2006 | 2.1853 | 1.3028 |
| sudden_volume_expansion::hot_low_turnover_proxy | 411 | 48.1752 | 0.1952 | 0.0 | 0.4866 | 0.0 |
| volume_contracting_three_day::active | 27932 | 48.5321 | 0.1944 | 0.0 | 1.6683 | 1.4607 |
| mixed_volume::active | 107205 | 48.1237 | 0.1868 | 0.0 | 1.4356 | 1.1268 |
| volume_contracting_three_day::normal_low_turnover_proxy | 28350 | 50.0917 | 0.1834 | 0.0223 | 0.5291 | 0.2222 |
| mixed_volume::normal_low_turnover_proxy | 67542 | 50.3968 | 0.1801 | 0.0439 | 0.4501 | 0.2221 |
| sudden_volume_expansion::hot | 6043 | 45.8051 | 0.1727 | -0.1873 | 2.3829 | 0.9432 |
| volume_rising_three_day::active | 44469 | 47.6512 | 0.1572 | -0.0378 | 1.2705 | 1.0052 |
| volume_rising_three_day::normal_low_turnover_proxy | 12119 | 49.179 | 0.1481 | 0.0 | 0.3218 | 0.2145 |
| volume_contracting_three_day::contracted_low_turnover_proxy | 24359 | 49.3165 | 0.1468 | 0.0 | 0.7061 | 0.2833 |
| multi_day_contraction::normal_low_turnover_proxy | 16859 | 48.4548 | 0.13 | 0.0 | 0.4508 | 0.2017 |
| volume_contracting_three_day::normal | 85456 | 47.9194 | 0.0893 | -0.0342 | 1.1971 | 0.9841 |
| mixed_volume::normal | 185584 | 48.3043 | 0.0827 | 0.0 | 0.9807 | 0.8481 |
| multi_day_contraction::contracted | 173776 | 49.1938 | 0.0795 | 0.0 | 0.8022 | 0.5444 |
| mixed_volume::contracted | 34939 | 48.2899 | 0.0634 | 0.0 | 1.1592 | 0.7413 |
| volume_rising_three_day::normal | 41001 | 48.0159 | 0.0599 | 0.0 | 0.9414 | 0.8975 |

## Target Feature Mix

| target | feature | n | share_in_target | avg_return | median_return |
| --- | --- | --- | --- | --- | --- |
| d1_limit_up | position_group=neutral | 7775 | 44.4819 | 11.1371 | 10.005 |
| d1_limit_up | position_group=high_momentum | 5968 | 34.1438 | 11.3586 | 10.0036 |
| d1_limit_up | position_group=low_repair | 2409 | 13.7823 | 11.1686 | 10.0039 |
| d1_limit_up | position_group=deep_oversold | 863 | 4.9374 | 11.1139 | 10.0031 |
| d1_limit_up | position_group=extreme_hot | 464 | 2.6546 | 11.6575 | 10.0021 |
| d1_limit_up | price_action_group=first_sun_or_strong_close | 4813 | 27.5359 | 11.1232 | 10.0038 |
| d1_limit_up | price_action_group=ordinary | 3906 | 22.3468 | 11.3994 | 10.0048 |
| d1_limit_up | price_action_group=low_close | 2777 | 15.8876 | 11.0052 | 10.0031 |
| d1_limit_up | price_action_group=balanced_mid_close | 1640 | 9.3827 | 11.3379 | 10.0043 |
| d1_limit_up | price_action_group=compressed_mid_close | 1286 | 7.3574 | 11.0174 | 10.0029 |
| d1_limit_up | price_action_group=high_close | 1182 | 6.7624 | 10.9622 | 10.0057 |
| d1_limit_up | price_action_group=panic_low_close | 997 | 5.704 | 11.3055 | 10.0021 |
| d1_limit_up | price_action_group=intraday_fade | 878 | 5.0232 | 12.1528 | 10.0064 |
| d1_limit_up | volume_turnover_group=normal | 3593 | 20.5561 | 11.2089 | 10.0038 |
| d1_limit_up | volume_turnover_group=active | 2583 | 14.7777 | 11.39 | 10.0031 |
| d1_limit_up | volume_turnover_group=contracted | 2403 | 13.7479 | 10.8538 | 10.0022 |
| d1_limit_up | volume_turnover_group=extreme_high_turnover_proxy | 1458 | 8.3414 | 11.3617 | 10.0068 |
| d1_limit_up | volume_turnover_group=hot | 1339 | 7.6606 | 11.3658 | 10.0051 |
| d1_limit_up | volume_turnover_group=active_high_turnover_proxy | 1258 | 7.1972 | 11.1737 | 10.0037 |
| d1_limit_up | volume_turnover_group=hot_high_turnover_proxy | 1137 | 6.5049 | 11.2493 | 10.0041 |
| d1_limit_up | volume_turnover_group=normal_high_turnover_proxy | 784 | 4.4854 | 11.0472 | 10.0041 |
| d1_limit_up | volume_turnover_group=extreme | 764 | 4.371 | 11.4185 | 10.0082 |
| d1_limit_up | volume_turnover_group=contracted_low_turnover_proxy | 665 | 3.8046 | 11.044 | 10.0024 |
| d1_limit_up | volume_turnover_group=normal_low_turnover_proxy | 574 | 3.2839 | 11.4505 | 10.0035 |
| d1_limit_up | volume_turnover_group=unknown_turnover | 341 | 1.9509 | 11.4903 | 10.0089 |
| d1_limit_up | volume_turnover_group=contracted_high_turnover_proxy | 285 | 1.6305 | 11.0107 | 10.004 |
| d1_limit_up | volume_turnover_group=active_low_turnover_proxy | 222 | 1.2701 | 11.8061 | 10.0064 |
| d1_limit_up | volume_turnover_group=hot_low_turnover_proxy | 54 | 0.3089 | 12.0216 | 10.0037 |
| d1_limit_up | volume_turnover_group=extreme_low_turnover_proxy | 19 | 0.1087 | 13.169 | 10.0346 |
| d1_limit_up | active_source_group=no_limit_source | 7159 | 40.9577 | 12.1036 | 10.011 |
| d1_limit_up | active_source_group=single_limit_source | 3691 | 21.1168 | 10.8568 | 10.0028 |
| d1_limit_up | active_source_group=multi_limit_source | 3084 | 17.644 | 10.3539 | 10.0 |
| d1_limit_up | active_source_group=touched_but_not_closed_limit | 1903 | 10.8874 | 11.0582 | 10.0017 |
| d1_limit_up | active_source_group=crowded_active_source | 1642 | 9.3941 | 10.1019 | 10.0 |
| d1_limit_up | pre_volume_pattern=mixed_volume | 5222 | 29.8759 | 11.3144 | 10.0042 |
| d1_limit_up | pre_volume_pattern=volume_contracting_three_day | 3608 | 20.6419 | 11.1496 | 10.0037 |
| d1_limit_up | pre_volume_pattern=volume_rising_three_day | 2910 | 16.6485 | 11.3957 | 10.0047 |
| d1_limit_up | pre_volume_pattern=multi_day_contraction | 2419 | 13.8395 | 10.9902 | 10.0021 |
| d1_limit_up | pre_volume_pattern=high_turnover_proxy_latest | 2308 | 13.2044 | 11.1336 | 10.0047 |
| d1_limit_up | pre_volume_pattern=sudden_volume_expansion | 610 | 3.4899 | 11.2156 | 10.0051 |
| d1_limit_up | pre_volume_pattern=volume_history_unknown | 402 | 2.2999 | 11.6632 | 10.0119 |
| d1_limit_up | flag=active_source_compressed_high_close | 628 | 3.5929 | 10.3896 | 10.0 |
| d1_limit_up | flag=deep_low_close_rebound_absorption | 324 | 1.8537 | 11.0267 | 10.0017 |
| d1_limit_up | flag=deep_low_first_sun_confirm | 95 | 0.5435 | 11.028 | 10.0 |
| d1_limit_up | flag=extreme_volume_intraday_fade | 508 | 2.9063 | 11.3218 | 10.006 |
| d1_limit_up | flag=active_source_breakdown | 863 | 4.9374 | 10.4783 | 10.0 |
| d1_limit_up | flag=hot_reacceleration_exhaustion | 233 | 1.333 | 11.4142 | 10.0016 |
| d1_limit_up | flag=weak_repair_high_close_no_source | 613 | 3.5071 | 11.068 | 10.0065 |
| d1_big_up7 | position_group=neutral | 16405 | 44.9243 | 10.1716 | 9.9896 |
| d1_big_up7 | position_group=high_momentum | 11360 | 31.1088 | 10.5857 | 10.0 |
| d1_big_up7 | position_group=low_repair | 5670 | 15.527 | 10.0258 | 9.9797 |
| d1_big_up7 | position_group=deep_oversold | 2204 | 6.0355 | 10.0187 | 9.9758 |
| d1_big_up7 | position_group=extreme_hot | 878 | 2.4044 | 11.0885 | 10.0 |
| d1_big_up7 | price_action_group=ordinary | 8399 | 23.0002 | 10.3975 | 9.9936 |
| d1_big_up7 | price_action_group=first_sun_or_strong_close | 8224 | 22.521 | 10.4869 | 10.0 |
| d1_big_up7 | price_action_group=low_close | 6459 | 17.6877 | 9.9384 | 9.9804 |
| d1_big_up7 | price_action_group=balanced_mid_close | 3710 | 10.1597 | 10.2027 | 9.9855 |
| d1_big_up7 | price_action_group=compressed_mid_close | 3042 | 8.3304 | 9.9661 | 9.9776 |
| d1_big_up7 | price_action_group=high_close | 2440 | 6.6818 | 10.1893 | 9.9937 |
| d1_big_up7 | price_action_group=panic_low_close | 2199 | 6.0219 | 10.3196 | 9.9922 |
| d1_big_up7 | price_action_group=intraday_fade | 2044 | 5.5974 | 10.9063 | 10.0 |
| d1_big_up7 | volume_turnover_group=normal | 8546 | 23.4028 | 10.1464 | 9.9883 |
| d1_big_up7 | volume_turnover_group=active | 6067 | 16.6142 | 10.2901 | 9.9898 |
| d1_big_up7 | volume_turnover_group=contracted | 5185 | 14.1989 | 9.9434 | 9.9834 |
| d1_big_up7 | volume_turnover_group=hot | 2732 | 7.4814 | 10.5288 | 10.0 |
| d1_big_up7 | volume_turnover_group=active_high_turnover_proxy | 2308 | 6.3203 | 10.4825 | 10.0 |
| d1_big_up7 | volume_turnover_group=extreme_high_turnover_proxy | 2234 | 6.1177 | 10.8205 | 10.0 |
| d1_big_up7 | volume_turnover_group=hot_high_turnover_proxy | 1968 | 5.3893 | 10.6045 | 10.0 |
| d1_big_up7 | volume_turnover_group=normal_high_turnover_proxy | 1468 | 4.02 | 10.2036 | 9.9945 |
| d1_big_up7 | volume_turnover_group=contracted_low_turnover_proxy | 1452 | 3.9762 | 10.0152 | 9.9821 |
| d1_big_up7 | volume_turnover_group=normal_low_turnover_proxy | 1426 | 3.905 | 10.101 | 9.9769 |
| d1_big_up7 | volume_turnover_group=extreme | 1307 | 3.5792 | 10.6745 | 10.0 |
| d1_big_up7 | volume_turnover_group=unknown_turnover | 673 | 1.843 | 10.6311 | 10.0 |
| d1_big_up7 | volume_turnover_group=active_low_turnover_proxy | 508 | 1.3911 | 10.4314 | 9.9975 |
| d1_big_up7 | volume_turnover_group=contracted_high_turnover_proxy | 498 | 1.3637 | 10.3884 | 10.0 |
| d1_big_up7 | volume_turnover_group=hot_low_turnover_proxy | 111 | 0.304 | 10.6363 | 9.9931 |
| d1_big_up7 | volume_turnover_group=extreme_low_turnover_proxy | 34 | 0.0931 | 11.7084 | 10.0313 |
| d1_big_up7 | active_source_group=no_limit_source | 20012 | 54.8019 | 10.4586 | 9.9824 |
| d1_big_up7 | active_source_group=single_limit_source | 6548 | 17.9314 | 10.2013 | 9.996 |
| d1_big_up7 | active_source_group=multi_limit_source | 4257 | 11.6576 | 9.9765 | 9.999 |
| d1_big_up7 | active_source_group=touched_but_not_closed_limit | 3652 | 10.0008 | 10.2168 | 9.9922 |
| d1_big_up7 | active_source_group=crowded_active_source | 2048 | 5.6083 | 9.7184 | 10.0 |
| d1_big_up7 | pre_volume_pattern=mixed_volume | 11991 | 32.8368 | 10.2491 | 9.9908 |
| d1_big_up7 | pre_volume_pattern=volume_contracting_three_day | 7491 | 20.5137 | 10.2685 | 9.9931 |
| d1_big_up7 | pre_volume_pattern=volume_rising_three_day | 5873 | 16.0829 | 10.4476 | 9.9959 |
| d1_big_up7 | pre_volume_pattern=multi_day_contraction | 5389 | 14.7575 | 10.0208 | 9.9835 |
| d1_big_up7 | pre_volume_pattern=high_turnover_proxy_latest | 4040 | 11.0633 | 10.4351 | 10.0 |
| d1_big_up7 | pre_volume_pattern=sudden_volume_expansion | 936 | 2.5632 | 10.6057 | 10.0 |
| d1_big_up7 | pre_volume_pattern=volume_history_unknown | 797 | 2.1825 | 10.6868 | 10.0 |
| d1_big_up7 | flag=active_source_compressed_high_close | 882 | 2.4153 | 10.0445 | 9.998 |
| d1_big_up7 | flag=deep_low_close_rebound_absorption | 880 | 2.4098 | 9.9346 | 9.9708 |
| d1_big_up7 | flag=deep_low_first_sun_confirm | 211 | 0.5778 | 10.3425 | 9.9906 |
| d1_big_up7 | flag=extreme_volume_intraday_fade | 880 | 2.4098 | 10.7355 | 10.0 |
| d1_big_up7 | flag=active_source_breakdown | 1315 | 3.6011 | 10.0377 | 9.9968 |
| d1_big_up7 | flag=hot_reacceleration_exhaustion | 352 | 0.9639 | 10.9094 | 10.0 |
| d1_big_up7 | flag=weak_repair_high_close_no_source | 1360 | 3.7243 | 10.059 | 9.9823 |
| d1_big_down7 | position_group=high_momentum | 6441 | 41.233 | -9.1009 | -8.8945 |
| d1_big_down7 | position_group=neutral | 5205 | 33.3205 | -8.8319 | -8.3864 |
| d1_big_down7 | position_group=low_repair | 2352 | 15.0567 | -8.4904 | -8.002 |
| d1_big_down7 | position_group=deep_oversold | 881 | 5.6398 | -8.7345 | -8.1663 |
| d1_big_down7 | position_group=extreme_hot | 742 | 4.75 | -10.1842 | -9.9906 |
| d1_big_down7 | price_action_group=ordinary | 3669 | 23.4876 | -9.0256 | -8.6061 |
| d1_big_down7 | price_action_group=first_sun_or_strong_close | 3560 | 22.7898 | -9.1756 | -8.9339 |
| d1_big_down7 | price_action_group=low_close | 2402 | 15.3767 | -8.5108 | -8.0035 |
| d1_big_down7 | price_action_group=panic_low_close | 1715 | 10.9788 | -9.0173 | -8.9192 |
| d1_big_down7 | price_action_group=balanced_mid_close | 1350 | 8.6422 | -8.8458 | -8.3259 |
| d1_big_down7 | price_action_group=intraday_fade | 1305 | 8.3541 | -9.1328 | -8.842 |
| d1_big_down7 | price_action_group=compressed_mid_close | 837 | 5.3582 | -8.8155 | -8.2516 |
| d1_big_down7 | price_action_group=high_close | 783 | 5.0125 | -8.7908 | -8.31 |
| d1_big_down7 | volume_turnover_group=normal | 3153 | 20.1844 | -8.6955 | -8.1752 |
| d1_big_down7 | volume_turnover_group=active | 2072 | 13.2642 | -8.8872 | -8.4003 |
| d1_big_down7 | volume_turnover_group=extreme_high_turnover_proxy | 1869 | 11.9647 | -9.3615 | -9.598 |
| d1_big_down7 | volume_turnover_group=active_high_turnover_proxy | 1792 | 11.4717 | -9.1548 | -9.0018 |
| d1_big_down7 | volume_turnover_group=contracted | 1604 | 10.2682 | -8.6178 | -8.0991 |
| d1_big_down7 | volume_turnover_group=hot_high_turnover_proxy | 1501 | 9.6089 | -9.2214 | -8.9932 |
| d1_big_down7 | volume_turnover_group=normal_high_turnover_proxy | 1204 | 7.7076 | -8.9788 | -8.6975 |
| d1_big_down7 | volume_turnover_group=hot | 813 | 5.2045 | -8.9609 | -8.5513 |
| d1_big_down7 | volume_turnover_group=extreme | 390 | 2.4966 | -8.9048 | -8.5383 |
| d1_big_down7 | volume_turnover_group=unknown_turnover | 305 | 1.9525 | -9.3796 | -8.6235 |
| d1_big_down7 | volume_turnover_group=contracted_high_turnover_proxy | 298 | 1.9077 | -8.7227 | -8.486 |
| d1_big_down7 | volume_turnover_group=normal_low_turnover_proxy | 273 | 1.7476 | -8.5645 | -7.9777 |
| d1_big_down7 | volume_turnover_group=contracted_low_turnover_proxy | 252 | 1.6132 | -8.8488 | -8.103 |
| d1_big_down7 | volume_turnover_group=active_low_turnover_proxy | 77 | 0.4929 | -8.4934 | -8.0733 |
| d1_big_down7 | volume_turnover_group=hot_low_turnover_proxy | 14 | 0.0896 | -8.8455 | -8.3191 |
| d1_big_down7 | volume_turnover_group=extreme_low_turnover_proxy | 4 | 0.0256 | -9.376 | -9.7158 |
| d1_big_down7 | active_source_group=no_limit_source | 6606 | 42.2892 | -8.8382 | -8.1967 |
| d1_big_down7 | active_source_group=single_limit_source | 3189 | 20.4148 | -8.9847 | -8.5873 |
| d1_big_down7 | active_source_group=multi_limit_source | 2610 | 16.7083 | -9.0776 | -9.015 |
| d1_big_down7 | active_source_group=crowded_active_source | 1642 | 10.5115 | -9.1373 | -9.81 |
| d1_big_down7 | active_source_group=touched_but_not_closed_limit | 1574 | 10.0762 | -8.9432 | -8.5358 |
| d1_big_down7 | pre_volume_pattern=mixed_volume | 3825 | 24.4863 | -8.8041 | -8.2984 |
| d1_big_down7 | pre_volume_pattern=volume_contracting_three_day | 3353 | 21.4647 | -8.93 | -8.5813 |
| d1_big_down7 | pre_volume_pattern=high_turnover_proxy_latest | 3214 | 20.5749 | -9.1883 | -9.0472 |
| d1_big_down7 | pre_volume_pattern=volume_rising_three_day | 2800 | 17.9246 | -9.0107 | -8.6386 |
| d1_big_down7 | pre_volume_pattern=multi_day_contraction | 1736 | 11.1132 | -8.6372 | -8.0811 |
| d1_big_down7 | pre_volume_pattern=sudden_volume_expansion | 370 | 2.3686 | -9.195 | -9.2953 |
| d1_big_down7 | pre_volume_pattern=volume_history_unknown | 323 | 2.0677 | -9.3939 | -8.6887 |
| d1_big_down7 | flag=active_source_compressed_high_close | 381 | 2.439 | -9.1249 | -9.0595 |
| d1_big_down7 | flag=deep_low_close_rebound_absorption | 385 | 2.4646 | -8.5155 | -7.9681 |
| d1_big_down7 | flag=deep_low_first_sun_confirm | 67 | 0.4289 | -9.0051 | -9.0858 |
| d1_big_down7 | flag=extreme_volume_intraday_fade | 787 | 5.0381 | -9.1733 | -9.2409 |
| d1_big_down7 | flag=active_source_breakdown | 1043 | 6.6769 | -9.0008 | -9.0993 |
| d1_big_down7 | flag=hot_reacceleration_exhaustion | 244 | 1.562 | -10.3088 | -9.9955 |
| d1_big_down7 | flag=weak_repair_high_close_no_source | 295 | 1.8885 | -8.7371 | -8.0227 |
| d1_limit_down | position_group=high_momentum | 1779 | 50.4681 | -10.0604 | -9.9938 |
| d1_limit_down | position_group=neutral | 1018 | 28.8794 | -10.2971 | -9.9864 |
| d1_limit_down | position_group=low_repair | 294 | 8.3404 | -10.3699 | -9.9908 |
| d1_limit_down | position_group=extreme_hot | 287 | 8.1418 | -10.634 | -10.0 |
| d1_limit_down | position_group=deep_oversold | 147 | 4.1702 | -10.737 | -9.9928 |
| d1_limit_down | price_action_group=first_sun_or_strong_close | 1011 | 28.6809 | -10.1921 | -9.993 |
| d1_limit_down | price_action_group=ordinary | 772 | 21.9007 | -10.2925 | -9.9959 |
| d1_limit_down | price_action_group=panic_low_close | 601 | 17.0496 | -10.1186 | -9.9908 |
| d1_limit_down | price_action_group=low_close | 316 | 8.9645 | -10.3297 | -9.9888 |
| d1_limit_down | price_action_group=intraday_fade | 300 | 8.5106 | -10.1372 | -9.998 |
| d1_limit_down | price_action_group=balanced_mid_close | 258 | 7.3191 | -10.195 | -9.99 |
| d1_limit_down | price_action_group=compressed_mid_close | 137 | 3.8865 | -10.6477 | -9.9892 |
| d1_limit_down | price_action_group=high_close | 130 | 3.6879 | -10.2565 | -9.9948 |
| d1_limit_down | volume_turnover_group=extreme_high_turnover_proxy | 733 | 20.7943 | -10.1413 | -9.9936 |
| d1_limit_down | volume_turnover_group=active_high_turnover_proxy | 506 | 14.3546 | -10.0751 | -9.994 |
| d1_limit_down | volume_turnover_group=normal | 444 | 12.5957 | -10.4068 | -9.9922 |
| d1_limit_down | volume_turnover_group=hot_high_turnover_proxy | 443 | 12.5674 | -10.1689 | -9.9947 |
| d1_limit_down | volume_turnover_group=active | 329 | 9.3333 | -10.2616 | -9.9916 |
| d1_limit_down | volume_turnover_group=normal_high_turnover_proxy | 286 | 8.1135 | -10.11 | -9.989 |
| d1_limit_down | volume_turnover_group=contracted | 286 | 8.1135 | -10.3809 | -9.9934 |
| d1_limit_down | volume_turnover_group=hot | 163 | 4.6241 | -10.0844 | -9.9921 |
| d1_limit_down | volume_turnover_group=extreme | 85 | 2.4113 | -10.2103 | -9.9899 |
| d1_limit_down | volume_turnover_group=contracted_high_turnover_proxy | 75 | 2.1277 | -9.9892 | -9.9853 |
| d1_limit_down | volume_turnover_group=contracted_low_turnover_proxy | 62 | 1.7589 | -10.6517 | -9.9968 |
| d1_limit_down | volume_turnover_group=unknown_turnover | 60 | 1.7021 | -11.4135 | -10.0 |
| d1_limit_down | volume_turnover_group=normal_low_turnover_proxy | 37 | 1.0496 | -10.7617 | -9.9581 |
| d1_limit_down | volume_turnover_group=active_low_turnover_proxy | 10 | 0.2837 | -10.099 | -9.9698 |
| d1_limit_down | volume_turnover_group=hot_low_turnover_proxy | 4 | 0.1135 | -10.0613 | -9.993 |
| d1_limit_down | volume_turnover_group=extreme_low_turnover_proxy | 2 | 0.0567 | -10.0052 | -10.0052 |
| d1_limit_down | active_source_group=multi_limit_source | 1002 | 28.4255 | -10.0657 | -9.9922 |
| d1_limit_down | active_source_group=crowded_active_source | 913 | 25.9007 | -9.9456 | -9.9968 |
| d1_limit_down | active_source_group=single_limit_source | 712 | 20.1986 | -10.1884 | -9.991 |
| d1_limit_down | active_source_group=no_limit_source | 591 | 16.766 | -11.0157 | -9.9912 |
| d1_limit_down | active_source_group=touched_but_not_closed_limit | 307 | 8.7092 | -10.1904 | -9.9899 |
| d1_limit_down | pre_volume_pattern=high_turnover_proxy_latest | 1005 | 28.5106 | -10.2025 | -9.9941 |
| d1_limit_down | pre_volume_pattern=volume_contracting_three_day | 760 | 21.5603 | -10.1227 | -9.9908 |
| d1_limit_down | pre_volume_pattern=mixed_volume | 649 | 18.4113 | -10.2401 | -9.9911 |
| d1_limit_down | pre_volume_pattern=volume_rising_three_day | 641 | 18.1844 | -10.1208 | -9.9942 |
| d1_limit_down | pre_volume_pattern=multi_day_contraction | 262 | 7.4326 | -10.6034 | -9.9897 |
| d1_limit_down | pre_volume_pattern=sudden_volume_expansion | 143 | 4.0567 | -10.1848 | -9.9925 |
| d1_limit_down | pre_volume_pattern=volume_history_unknown | 65 | 1.844 | -11.4523 | -10.0 |
| d1_limit_down | flag=active_source_compressed_high_close | 133 | 3.773 | -10.0142 | -9.9944 |
| d1_limit_down | flag=deep_low_close_rebound_absorption | 59 | 1.6738 | -10.7904 | -10.0 |
| d1_limit_down | flag=deep_low_first_sun_confirm | 16 | 0.4539 | -9.9049 | -9.9837 |
| d1_limit_down | flag=extreme_volume_intraday_fade | 288 | 8.1702 | -10.0373 | -9.9919 |
| d1_limit_down | flag=active_source_breakdown | 441 | 12.5106 | -9.9444 | -9.9909 |
| d1_limit_down | flag=hot_reacceleration_exhaustion | 107 | 3.0355 | -10.8842 | -10.0 |
| d1_limit_down | flag=weak_repair_high_close_no_source | 29 | 0.8227 | -10.7879 | -9.9853 |

## Samples


### d1_limit_up_examples

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-01 | 2026-06-02 | 300197.SZSE | 节能铁汉 | 20.2073 | 19.8758 | high_momentum | first_sun_or_strong_close | extreme | volume_rising_three_day | no_limit_source | 5.3691 | 1.2682 | 0.9793 | 2.8841 | 0.8116 | 0.6072 |
| 2025-07-01 | 2025-07-02 | 300094.SZSE | 国联水产 | 20.1102 | 0.0 | neutral | balanced_mid_close | normal | mixed_volume | no_limit_source | 4.918 | 7.2232 | 5.4362 | 0.9195 | 1.3868 | 1.0631 |
| 2025-09-25 | 2025-09-26 | 300080.SZSE | 易成新能 | 20.098 | -0.4878 | low_repair | low_close | contracted | volume_contracting_three_day | no_limit_source | 1.2185 | 1.4936 | 1.8045 | 0.6639 | 0.8316 | 1.0217 |
| 2025-10-20 | 2025-10-21 | 688509.SSE | 正元地信 | 20.0946 | 1.1962 | low_repair | balanced_mid_close | normal | volume_contracting_three_day | no_limit_source | 1.2714 | 1.3849 | 1.4945 | 1.0028 | 1.083 | 1.156 |
| 2025-10-30 | 2025-10-31 | 300071.SZSE | 福石控股 | 20.0946 | -1.3986 | neutral | low_close | normal | mixed_volume | no_limit_source | 1.7978 | 1.6182 | 2.1453 | 0.8647 | 0.7375 | 0.93 |
| 2025-11-18 | 2025-11-19 | 300094.SZSE | 国联水产 | 20.0893 | 6.1611 | high_momentum | first_sun_or_strong_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 47.4369 | 62.6498 | 18.7201 | 6.1408 | 11.8642 | 4.9514 |
| 2025-07-10 | 2025-07-11 | 300066.SZSE | 三川智慧 | 20.0873 | 3.8549 | neutral | first_sun_or_strong_close | hot | sudden_volume_expansion | no_limit_source | 5.0831 | 1.5497 | 1.7625 | 2.4553 | 0.6768 | 0.7552 |
| 2026-06-30 | 2026-07-01 | 300175.SZSE | 朗源股份 | 20.0864 | 0.4338 | deep_oversold | ordinary | normal | mixed_volume | no_limit_source | 2.3593 | 1.8015 | 1.7945 | 1.085 | 0.8854 | 0.8879 |
| 2026-04-23 | 2026-04-24 | 300422.SZSE | 博世科 | 20.0864 | 0.0 | neutral | balanced_mid_close | normal | mixed_volume | no_limit_source | 1.6455 | 1.1069 | 1.4108 | 0.9425 | 0.6081 | 0.7571 |
| 2026-06-23 | 2026-06-24 | 300506.SZSE | 名家汇 | 20.0846 | -2.6749 | neutral | low_close | active_low_turnover_proxy | volume_contracting_three_day | single_limit_source | 0.9667 | 1.1289 | None | 1.2616 | 1.5286 | 1.6818 |
| 2026-01-12 | 2026-01-13 | 300078.SZSE | 思创智联 | 20.0846 | 3.956 | high_momentum | ordinary | active_high_turnover_proxy | volume_rising_three_day | no_limit_source | 19.8051 | 18.2755 | 14.3593 | 1.4616 | 1.4204 | 1.1545 |
| 2026-04-02 | 2026-04-03 | 300006.SZSE | 莱美药业 | 20.0737 | 5.2326 | neutral | ordinary | extreme_high_turnover_proxy | volume_rising_three_day | no_limit_source | 9.815 | 3.2616 | 1.9259 | 3.6148 | 1.281 | 0.7346 |
| 2025-07-01 | 2025-07-02 | 300160.SZSE | 秀强股份 | 20.0723 | -1.6014 | neutral | balanced_mid_close | hot | volume_rising_three_day | no_limit_source | 3.3619 | 2.3873 | 1.1691 | 2.6472 | 2.0654 | 1.025 |
| 2026-02-13 | 2026-02-24 | 300157.SZSE | 新锦动力 | 20.071 | -2.4263 | neutral | low_close | contracted_high_turnover_proxy | multi_day_contraction | no_limit_source | 11.3193 | 13.9322 | 14.9213 | 0.5171 | 0.6231 | 0.6485 |
| 2025-12-09 | 2025-12-10 | 300189.SZSE | 神农种业 | 20.0698 | -6.8293 | neutral | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 26.2375 | 23.1849 | 26.0155 | 0.9168 | 0.7674 | 0.8903 |
| 2025-11-17 | 2025-11-18 | 300071.SZSE | 福石控股 | 20.068 | 7.2993 | high_momentum | ordinary | active_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 32.6082 | 18.3068 | 19.7525 | 1.6796 | 1.0329 | 1.1346 |

### d1_big_down_examples

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-12 | 2026-06-15 | 688662.SSE | 富信科技 | -22.5 | 17.8125 | high_momentum | first_sun_or_strong_close | extreme_high_turnover_proxy | volume_rising_three_day | single_limit_source | 20.1234 | 12.8934 | 8.4899 | 2.1947 | 1.7574 | 1.4347 |
| 2026-04-21 | 2026-04-22 | 688678.SSE | 福立旺 | -22.4918 | -2.6803 | high_momentum | ordinary | active | volume_contracting_three_day | no_limit_source | 7.5228 | 14.8852 | 13.3227 | 1.2787 | 2.6101 | 2.6535 |
| 2025-07-11 | 2025-07-14 | 301093.SZSE | 华兰股份 | -22.4615 | 0.0 | neutral | compressed_mid_close | contracted_low_turnover_proxy | mixed_volume | no_limit_source | 0.4002 | 0.5736 | 0.5215 | 0.6106 | 0.8741 | 0.7875 |
| 2025-06-06 | 2025-06-09 | 300394.SZSE | 天孚通信 | -22.4481 | 3.0393 | neutral | ordinary | unknown_turnover | volume_history_unknown | no_limit_source | 0.9652 | 0.9416 | 0.9524 | None | None | None |
| 2025-06-17 | 2025-06-18 | 688372.SSE | 伟测科技 | -22.3688 | 0.35 | neutral | compressed_mid_close | normal_low_turnover_proxy | mixed_volume | no_limit_source | 0.504 | 0.3769 | 0.6775 | 0.7361 | 0.5242 | 0.9256 |
| 2026-05-22 | 2026-05-25 | 688168.SSE | 安博通 | -22.3162 | 1.2113 | low_repair | high_close | normal | mixed_volume | no_limit_source | 1.9456 | 2.2427 | 1.547 | 0.8713 | 0.957 | 0.6489 |
| 2025-08-11 | 2025-08-12 | 301099.SZSE | 雅创电子 | -22.0681 | 3.4214 | neutral | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 2.1119 | 1.3796 | 1.796 | 1.4966 | 1.0195 | 1.3407 |
| 2025-06-11 | 2025-06-12 | 300553.SZSE | 集智股份 | -21.9497 | 4.6097 | neutral | ordinary | unknown_turnover | volume_history_unknown | no_limit_source | 2.3635 | 1.5559 | 1.4161 | None | None | None |
| 2026-05-21 | 2026-05-22 | 301266.SZSE | 宇邦新材 | -21.9357 | -6.7253 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | 4.9737 | 4.133 | 4.005 | 1.2461 | 1.0095 | 0.9768 |
| 2026-06-02 | 2026-06-03 | 688479.SSE | 友车科技 | -21.8788 | 1.3709 | neutral | compressed_mid_close | normal_low_turnover_proxy | volume_contracting_three_day | no_limit_source | 0.8924 | 1.087 | 2.3703 | 0.7533 | 0.9163 | 1.918 |
| 2026-05-27 | 2026-05-28 | 301158.SZSE | 德石股份 | -21.8323 | -3.7719 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 3.3898 | 4.04 | 4.8927 | 0.5951 | 0.6624 | 0.7659 |
| 2025-06-05 | 2025-06-06 | 301150.SZSE | 中一科技 | -21.6995 | -0.1917 | neutral | high_close | unknown_turnover | volume_history_unknown | no_limit_source | 0.1738 | 0.2254 | None | None | None | None |
| 2025-07-08 | 2025-07-09 | 688592.SSE | 司南导航 | -21.4239 | 1.6652 | neutral | compressed_mid_close | normal | volume_contracting_three_day | no_limit_source | 1.6739 | 1.9541 | 3.0256 | 0.7414 | 0.8647 | 1.3869 |
| 2025-06-05 | 2025-06-06 | 300619.SZSE | 金银河 | -21.2258 | -1.219 | neutral | low_close | unknown_turnover | volume_history_unknown | no_limit_source | 0.6273 | 0.8588 | None | None | None | None |
| 2026-06-10 | 2026-06-11 | 301669.SZSE | 高特电子 | -21.1435 | -1.8129 | neutral | intraday_fade | unknown_turnover | volume_history_unknown | no_limit_source | 15.8287 | 21.4905 | None | None | None | None |
| 2026-05-28 | 2026-05-29 | 301468.SZSE | 博盈特焊 | -20.9854 | 8.903 | neutral | first_sun_or_strong_close | normal | volume_rising_three_day | no_limit_source | 5.4853 | 4.7217 | 3.1729 | 1.1086 | 0.9432 | 0.6068 |

### active_source_compressed_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-08-18 | 2025-08-19 | 688098.SSE | 申联生物 | 20.0312 | 20.0187 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | multi_limit_source | 4.4016 | 11.5127 | 4.6493 | 0.6181 | 2.2216 | 1.0145 |
| 2025-07-28 | 2025-07-29 | 300528.SZSE | 幸福蓝海 | 20.0228 | 20.0 | high_momentum | first_sun_or_strong_close | active | mixed_volume | single_limit_source | 6.6009 | 20.0772 | 12.8977 | 0.8396 | 3.4653 | 2.6092 |
| 2025-06-24 | 2025-06-25 | 300368.SZSE | 汇金股份 | 20.0177 | 7.2175 | neutral | first_sun_or_strong_close | normal_high_turnover_proxy | volume_rising_three_day | multi_limit_source | 29.2235 | 21.3175 | 13.8689 | 0.9839 | 0.7724 | 0.5156 |
| 2026-04-28 | 2026-04-29 | 300209.SZSE | 行云科技 | 20.0141 | 7.5 | high_momentum | first_sun_or_strong_close | active | volume_rising_three_day | single_limit_source | 6.2627 | 4.2895 | 4.0219 | 1.0444 | 0.7394 | 0.7039 |
| 2026-06-02 | 2026-06-03 | 688655.SSE | 迅捷兴 | 20.0082 | 4.2662 | deep_oversold | first_sun_or_strong_close | contracted_high_turnover_proxy | multi_day_contraction | single_limit_source | 8.9622 | 6.4187 | 9.864 | 0.6373 | 0.4352 | 0.6411 |
| 2026-06-17 | 2026-06-18 | 688485.SSE | 九州一轨 | 20.0071 | 8.5155 | neutral | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 5.3143 | 3.3951 | 3.4471 | 1.0482 | 0.7068 | 0.7221 |
| 2026-01-22 | 2026-01-23 | 300102.SZSE | 乾照光电 | 20.0061 | 4.9518 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | multi_day_contraction | multi_limit_source | 18.5776 | 14.2945 | 20.1679 | 0.6754 | 0.5234 | 0.7089 |
| 2026-04-10 | 2026-04-13 | 301667.SZSE | 纳百川 | 20.0044 | 10.3882 | neutral | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 10.2021 | 4.2787 | 7.3448 | 0.9835 | 0.4434 | 0.7553 |
| 2026-03-24 | 2026-03-25 | 300658.SZSE | 延江股份 | 20.0 | 6.3879 | low_repair | first_sun_or_strong_close | contracted_high_turnover_proxy | multi_day_contraction | single_limit_source | 12.7068 | 13.5525 | 20.6779 | 0.5628 | 0.5917 | 0.8069 |
| 2025-11-28 | 2025-12-01 | 300903.SZSE | 科翔股份 | 20.0 | 3.936 | low_repair | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 1.7555 | 0.9097 | 0.9195 | 0.8161 | 0.4198 | 0.4134 |
| 2026-01-22 | 2026-01-23 | 300751.SZSE | 迈为股份 | 20.0 | 9.6107 | high_momentum | first_sun_or_strong_close | active | mixed_volume | single_limit_source | 5.1806 | 3.5792 | 4.8496 | 0.9457 | 0.684 | 0.9323 |
| 2025-11-10 | 2025-11-11 | 688585.SSE | 上纬新材 | 20.0 | 3.7087 | low_repair | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 1.5095 | 1.8627 | 0.9633 | 0.9008 | 1.0234 | 0.5692 |
| 2026-04-30 | 2026-05-06 | 688813.SSE | 泰金新能 | 20.0 | 6.8579 | extreme_hot | first_sun_or_strong_close | active | volume_rising_three_day | multi_limit_source | 2.7667 | 2.4933 | 2.5374 | 0.8978 | 0.8147 | 0.7996 |
| 2025-09-05 | 2025-09-08 | 688577.SSE | 浙海德曼 | 20.0 | 11.5119 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 3.8143 | 3.7675 | 6.7155 | 0.7439 | 0.7864 | 1.3915 |
| 2026-05-15 | 2026-05-18 | 301666.SZSE | 大普微 | 20.0 | 7.7655 | high_momentum | first_sun_or_strong_close | active | multi_day_contraction | multi_limit_source | 1.724 | 1.9955 | 1.592 | 0.6355 | 0.7215 | 0.6565 |
| 2026-06-15 | 2026-06-16 | 300964.SZSE | 本川智能 | 19.9958 | 7.9143 | neutral | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 5.5033 | 5.7075 | 5.3733 | 0.612 | 0.6371 | 0.5897 |

### active_source_compressed_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-06-18 | 2025-06-19 | 300255.SZSE | 常山药业 | -20.0 | 14.605 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | volume_rising_three_day | single_limit_source | 15.8956 | 12.4391 | 10.6221 | 0.997 | 0.8489 | 0.716 |
| 2026-07-01 | 2026-07-02 | 688056.SSE | 莱伯泰科 | -16.1765 | 5.3447 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 7.5607 | 6.2693 | 8.4132 | 0.8107 | 0.6956 | 0.9678 |
| 2025-08-28 | 2025-08-29 | 688448.SSE | 磁谷科技 | -15.8065 | 6.2008 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 7.1374 | 7.3805 | 5.4087 | 0.9031 | 0.9201 | 0.6659 |
| 2025-12-02 | 2025-12-03 | 300300.SZSE | 海峡创新 | -15.3846 | 13.5301 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 79.6032 | 72.3327 | 70.7182 | 0.941 | 0.916 | 0.9972 |
| 2025-11-17 | 2025-11-18 | 301292.SZSE | 海科新源 | -14.3672 | 6.0798 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 13.377 | 14.4976 | 11.9067 | 0.9202 | 1.0039 | 0.9141 |
| 2026-06-22 | 2026-06-23 | 688056.SSE | 莱伯泰科 | -14.1278 | 10.56 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | volume_contracting_three_day | single_limit_source | 8.1019 | None | 8.7225 | 0.9758 | 1.0614 | 1.2842 |
| 2026-04-17 | 2026-04-20 | 688308.SSE | 欧科亿 | -13.9737 | 9.6154 | high_momentum | first_sun_or_strong_close | active | volume_rising_three_day | single_limit_source | 6.1607 | 5.1891 | 4.7833 | 0.9295 | 0.8703 | 0.8384 |
| 2026-06-25 | 2026-06-26 | 301013.SZSE | 利和兴 | -13.9442 | 13.2889 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 31.1195 | 27.5017 | 29.6096 | 0.9704 | 0.8931 | 0.9951 |
| 2026-01-23 | 2026-01-26 | 300503.SZSE | 昊志机电 | -13.887 | 6.5269 | extreme_hot | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 11.0832 | 8.5474 | 9.0631 | 0.8929 | 0.7354 | 0.7986 |
| 2026-06-11 | 2026-06-12 | 688146.SSE | 中船特气 | -13.665 | 19.7945 | extreme_hot | first_sun_or_strong_close | hot | volume_rising_three_day | multi_limit_source | 4.0198 | 2.9863 | 2.6704 | 0.9929 | 0.8146 | 0.8029 |
| 2026-01-23 | 2026-01-26 | 301306.SZSE | 西测测试 | -12.9591 | 7.3312 | neutral | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 12.1607 | 7.2409 | 7.6631 | 0.9538 | 0.5808 | 0.6067 |
| 2025-08-19 | 2025-08-20 | 300588.SZSE | 熙菱信息 | -12.4494 | 7.8526 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | volume_rising_three_day | single_limit_source | 11.6897 | 8.834 | 3.4253 | 1.0493 | 0.8516 | 0.3532 |
| 2025-07-15 | 2025-07-16 | 688656.SSE | 浩欧博 | -11.9807 | 3.6667 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | multi_limit_source | 4.3633 | 6.7172 | 10.7952 | 0.8442 | 1.3247 | 2.254 |
| 2026-02-03 | 2026-02-04 | 301232.SZSE | 飞沃科技 | -11.9792 | 3.2814 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 11.0859 | 8.544 | 9.6507 | 1.0487 | 0.768 | 0.8223 |
| 2026-05-20 | 2026-05-21 | 688661.SSE | 和林微纳 | -11.9479 | 4.8039 | high_momentum | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 3.9392 | 3.3149 | 2.9194 | 0.7873 | 0.6969 | 0.6221 |
| 2026-01-23 | 2026-01-26 | 300885.SZSE | 海昌新材 | -11.9311 | 3.6039 | high_momentum | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 7.6536 | 4.774 | 4.7723 | 0.5683 | 0.3644 | 0.3652 |

### deep_low_close_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-18 | 2026-06-22 | 300561.SZSE | 汇金科技 | 20.0314 | -3.997 | deep_oversold | low_close | normal | volume_contracting_three_day | no_limit_source | None | 3.9459 | 4.7361 | 0.7653 | 0.7719 | 0.9535 |
| 2026-02-03 | 2026-02-04 | 301119.SZSE | 正强股份 | 20.0083 | 0.5858 | deep_oversold | low_close | contracted | mixed_volume | no_limit_source | 2.503 | 3.276 | 2.698 | 0.6895 | 0.9094 | 0.7328 |
| 2026-06-08 | 2026-06-09 | 688711.SSE | 宏微科技 | 20.0067 | -11.3033 | deep_oversold | panic_low_close | normal | volume_contracting_three_day | no_limit_source | 5.7563 | 6.1077 | 7.2609 | 0.7911 | 0.7964 | 0.9244 |
| 2026-05-29 | 2026-06-01 | 301236.SZSE | 软通动力 | 20.0061 | -6.3227 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 2.2229 | 2.841 | 2.1898 | 1.1503 | 1.4068 | 0.9788 |
| 2026-06-08 | 2026-06-09 | 688596.SSE | 正帆科技 | 20.0053 | -7.2372 | deep_oversold | panic_low_close | contracted | mixed_volume | single_limit_source | 2.7455 | 4.5522 | 2.8782 | 0.6692 | 1.0981 | 0.7303 |
| 2026-07-02 | 2026-07-03 | 300779.SZSE | 惠城环保 | 20.004 | -0.9625 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.3976 | 2.5694 | 1.9827 | 0.9169 | 1.0388 | 0.7941 |
| 2026-04-07 | 2026-04-08 | 300475.SZSE | 香农芯创 | 20.0032 | 1.2297 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 1.9321 | 1.8328 | 2.0104 | 0.6348 | 0.5687 | 0.5968 |
| 2026-06-26 | 2026-06-29 | 300204.SZSE | 舒泰神 | 20.0 | -7.619 | deep_oversold | panic_low_close | normal | volume_contracting_three_day | touched_but_not_closed_limit | 4.6474 | 6.0404 | 7.6221 | 0.9037 | 1.1637 | 1.482 |
| 2026-06-01 | 2026-06-02 | 301419.SZSE | 阿莱德 | 20.0 | -2.4008 | deep_oversold | low_close | normal | volume_contracting_three_day | no_limit_source | 3.8495 | 5.8441 | 6.6422 | 1.0482 | 1.6138 | 1.9649 |
| 2026-06-26 | 2026-06-29 | 301520.SZSE | 万邦医药 | 20.0 | -2.7663 | deep_oversold | low_close | normal_low_turnover_proxy | volume_contracting_three_day | no_limit_source | 0.4217 | 0.702 | 0.7157 | 0.9597 | 1.6077 | 1.6097 |
| 2025-10-22 | 2025-10-23 | 300528.SZSE | 幸福蓝海 | 20.0 | -0.1022 | deep_oversold | low_close | contracted_high_turnover_proxy | multi_day_contraction | no_limit_source | 8.2636 | 4.4473 | 7.4939 | 0.7255 | 0.3631 | 0.5535 |
| 2026-06-26 | 2026-06-29 | 300436.SZSE | 广生堂 | 20.0 | -3.173 | deep_oversold | low_close | contracted | volume_contracting_three_day | no_limit_source | 3.0727 | 3.9617 | 4.4676 | 0.7339 | 0.9635 | 1.0804 |
| 2026-06-12 | 2026-06-15 | 688170.SSE | 德龙激光 | 20.0 | -3.8216 | deep_oversold | intraday_fade | contracted | multi_day_contraction | no_limit_source | 7.1911 | 6.1332 | 8.1705 | 0.666 | 0.5597 | 0.7011 |
| 2026-04-02 | 2026-04-03 | 300812.SZSE | 易天股份 | 20.0 | -0.4425 | deep_oversold | low_close | normal | multi_day_contraction | no_limit_source | 7.4442 | 4.3321 | 4.9296 | 0.8416 | 0.4519 | 0.4943 |
| 2026-06-03 | 2026-06-04 | 300897.SZSE | 山科智能 | 20.0 | -3.866 | deep_oversold | intraday_fade | normal | volume_contracting_three_day | no_limit_source | 2.47 | 4.3392 | 4.0963 | 1.3989 | 2.7325 | 2.8071 |
| 2026-07-02 | 2026-07-03 | 301379.SZSE | 天山电子 | 20.0 | -7.8721 | deep_oversold | panic_low_close | normal | mixed_volume | single_limit_source | 7.7651 | 13.7362 | 10.8253 | 1.0215 | 1.7998 | 1.5632 |

### deep_low_close_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-21 | 2026-05-22 | 301266.SZSE | 宇邦新材 | -21.9357 | -6.7253 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | 4.9737 | 4.133 | 4.005 | 1.2461 | 1.0095 | 0.9768 |
| 2026-05-27 | 2026-05-28 | 301158.SZSE | 德石股份 | -21.8323 | -3.7719 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 3.3898 | 4.04 | 4.8927 | 0.5951 | 0.6624 | 0.7659 |
| 2026-05-29 | 2026-06-01 | 300427.SZSE | 红相股份 | -19.978 | -4.1053 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 5.4426 | 5.6831 | 4.9293 | 0.6784 | 0.6913 | 0.6 |
| 2025-10-28 | 2025-10-29 | 688108.SSE | 赛诺医疗 | -18.5788 | -9.3885 | deep_oversold | panic_low_close | active_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 14.4935 | 7.1492 | 9.8958 | 1.6363 | 0.7305 | 1.0011 |
| 2026-05-21 | 2026-05-22 | 688543.SSE | 国科军工 | -18.1112 | -4.106 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.8445 | 3.4925 | 2.3122 | 0.8693 | 1.0621 | 0.6925 |
| 2026-03-31 | 2026-04-01 | 301302.SZSE | 华如科技 | -15.5513 | -3.8743 | deep_oversold | low_close | contracted | multi_day_contraction | single_limit_source | 6.6043 | 6.182 | 5.8893 | 0.5019 | 0.4685 | 0.439 |
| 2026-02-24 | 2026-02-25 | 688228.SSE | 开普云 | -14.7787 | -3.6 | deep_oversold | low_close | normal_high_turnover_proxy | volume_rising_three_day | no_limit_source | 11.3723 | 9.0855 | 7.2264 | 1.2908 | 0.9744 | 0.7647 |
| 2026-04-02 | 2026-04-03 | 301137.SZSE | 哈焊华通 | -14.1086 | -3.7449 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 4.3668 | 6.3174 | 5.8084 | 0.5299 | 0.7687 | 0.6998 |
| 2025-10-09 | 2025-10-10 | 300779.SZSE | 惠城环保 | -13.0912 | -6.3714 | deep_oversold | panic_low_close | active_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 8.36 | 14.8996 | 6.4984 | 1.7231 | 3.4579 | 1.2996 |
| 2025-09-25 | 2025-09-26 | 688166.SSE | 博瑞医药 | -12.5734 | -8.4 | deep_oversold | panic_low_close | active_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 11.9228 | 9.7441 | 18.7316 | 1.5963 | 1.2558 | 2.5271 |
| 2026-07-01 | 2026-07-02 | 300394.SZSE | 天孚通信 | -12.0105 | -5.8412 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 6.129 | 4.818 | 5.9581 | 1.1508 | 0.8667 | 1.07 |
| 2026-05-29 | 2026-06-01 | 300965.SZSE | 恒宇信通 | -11.9799 | -4.9547 | deep_oversold | low_close | contracted | multi_day_contraction | multi_limit_source | 4.9204 | 4.2614 | 4.6752 | 0.6724 | 0.5715 | 0.6323 |
| 2025-09-04 | 2025-09-05 | 300204.SZSE | 舒泰神 | -11.9435 | -5.0515 | deep_oversold | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 9.1619 | 9.3921 | 17.8802 | 0.8205 | 0.8149 | 1.5908 |
| 2026-04-29 | 2026-04-30 | 688280.SSE | 精进电动 | -11.8644 | -19.9612 | deep_oversold | panic_low_close | contracted | volume_contracting_three_day | no_limit_source | 4.5318 | 7.1867 | 9.6144 | 0.872 | 1.1086 | 1.5118 |
| 2026-05-12 | 2026-05-13 | 301310.SZSE | 鑫宏业 | -11.8581 | -20.0063 | deep_oversold | panic_low_close | active | volume_rising_three_day | no_limit_source | 4.6292 | 3.4303 | 3.1592 | 1.1665 | 0.7926 | 0.7455 |
| 2026-03-20 | 2026-03-23 | 688282.SSE | 理工导航 | -11.5982 | -2.9718 | deep_oversold | low_close | normal | multi_day_contraction | no_limit_source | 1.2908 | 1.1534 | 1.4304 | 0.8096 | 0.7001 | 0.8418 |

### deep_low_first_sun_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-09 | 2026-06-10 | 300264.SZSE | 佳创视讯 | 20.0514 | 6.7215 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 5.1641 | 4.0593 | 5.2073 | 1.0162 | 0.7876 | 0.9678 |
| 2026-06-29 | 2026-06-30 | 300270.SZSE | 中威电子 | 20.0185 | 4.8356 | low_repair | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 5.7354 | 5.0396 | 5.1237 | 1.764 | 1.565 | 1.5948 |
| 2026-06-15 | 2026-06-16 | 300780.SZSE | 德恩精工 | 20.0149 | 7.6769 | low_repair | first_sun_or_strong_close | normal | volume_rising_three_day | no_limit_source | 5.4691 | 4.6087 | 3.8275 | 1.0819 | 0.9083 | 0.7136 |
| 2026-06-22 | 2026-06-23 | 300085.SZSE | 银之杰 | 20.0 | 19.9926 | low_repair | first_sun_or_strong_close | active_high_turnover_proxy | sudden_volume_expansion | no_limit_source | 14.5388 | None | 4.7549 | 2.0061 | 0.5568 | 0.6937 |
| 2026-05-22 | 2026-05-25 | 300779.SZSE | 惠城环保 | 20.0 | 3.9177 | deep_oversold | ordinary | normal | volume_rising_three_day | no_limit_source | 2.7972 | 2.1723 | 1.3675 | 1.0972 | 0.8623 | 0.5363 |
| 2025-11-10 | 2025-11-11 | 688585.SSE | 上纬新材 | 20.0 | 3.7087 | low_repair | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 1.5095 | 1.8627 | 0.9633 | 0.9008 | 1.0234 | 0.5692 |
| 2026-06-22 | 2026-06-23 | 300961.SZSE | 深水海纳 | 19.982 | 2.5854 | low_repair | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.7697 | 2.1587 | 3.0193 | 1.2073 | 0.9195 | 1.2553 |
| 2026-06-30 | 2026-07-01 | 300287.SZSE | 飞利信 | 19.9377 | 3.2154 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.3855 | 2.0848 | 2.3135 | 1.2314 | 1.112 | 1.2038 |
| 2026-07-01 | 2026-07-02 | 300071.SZSE | 福石控股 | 19.891 | 4.8571 | low_repair | ordinary | active | volume_rising_three_day | no_limit_source | 5.4977 | 3.9769 | 2.5523 | 1.5926 | 1.1237 | 0.7337 |
| 2026-07-01 | 2026-07-02 | 300069.SZSE | 金利华电 | 18.021 | 4.7754 | deep_oversold | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 13.2395 | 5.0914 | 7.9813 | 1.151 | 0.4337 | 0.6658 |
| 2026-06-18 | 2026-06-22 | 301160.SZSE | 翔楼新材 | 17.5569 | 6.3122 | deep_oversold | first_sun_or_strong_close | hot | mixed_volume | no_limit_source | None | 2.7314 | 2.8689 | 2.0825 | 1.2772 | 1.3863 |
| 2026-06-15 | 2026-06-16 | 301312.SZSE | 智立方 | 17.0059 | 16.4818 | deep_oversold | first_sun_or_strong_close | normal | volume_rising_three_day | single_limit_source | 5.0644 | 2.3247 | 1.6531 | 1.4429 | 0.7209 | 0.4848 |
| 2025-11-27 | 2025-11-28 | 688275.SSE | 万润新能 | 16.8773 | 4.3009 | low_repair | ordinary | normal | multi_day_contraction | touched_but_not_closed_limit | 4.2498 | 2.4994 | 2.8275 | 0.8031 | 0.4812 | 0.5221 |
| 2026-06-02 | 2026-06-03 | 688498.SSE | 源杰科技 | 16.413 | 12.4339 | deep_oversold | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 4.3555 | 2.906 | 2.8998 | 1.6837 | 1.2119 | 1.2006 |
| 2026-06-15 | 2026-06-16 | 300870.SZSE | 欧陆通 | 16.1198 | 17.2892 | deep_oversold | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 5.8024 | 3.9587 | 2.1854 | 1.7368 | 1.3241 | 0.7603 |
| 2026-06-15 | 2026-06-16 | 300450.SZSE | 先导智能 | 15.9624 | 3.4232 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.9796 | 3.9579 | 2.5389 | 0.8311 | 1.1 | 0.7005 |

### risk_flag_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-07-24 | 2025-07-25 | 301038.SZSE | 深水规院 | -20.012 | 19.9856 | extreme_hot | first_sun_or_strong_close | extreme_high_turnover_proxy | sudden_volume_expansion | multi_limit_source | 32.4477 | 10.5938 | 17.3383 | 3.0777 | 1.107 | 2.2303 |
| 2026-01-29 | 2026-01-30 | 300139.SZSE | 晓程科技 | -20.0047 | 19.5184 | extreme_hot | first_sun_or_strong_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 76.1399 | 39.8723 | 44.6014 | 1.9809 | 1.258 | 1.7025 |
| 2025-08-05 | 2025-08-06 | 688585.SSE | 上纬新材 | -20.0036 | 19.9957 | extreme_hot | first_sun_or_strong_close | extreme | mixed_volume | crowded_active_source | 3.7565 | 2.8013 | 3.5327 | 2.1754 | 1.9745 | 2.9584 |
| 2026-01-14 | 2026-01-15 | 300785.SZSE | 值得买 | -20.0024 | 19.9971 | extreme_hot | first_sun_or_strong_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 52.5182 | 56.9648 | 26.0292 | 2.0933 | 2.8567 | 1.6234 |
| 2026-01-14 | 2026-01-15 | 688365.SSE | 光云科技 | -20.0 | 20.0 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 14.9632 | 36.1511 | 14.7271 | 1.1867 | 3.8799 | 2.0312 |
| 2025-04-23 | 2025-04-24 | 300225.SZSE | 金力泰 | -20.0 | -8.0645 | deep_oversold | intraday_fade | extreme_high_turnover_proxy | sudden_volume_expansion | no_limit_source | 17.1216 | 2.8283 | 4.9097 | 6.278 | 0.9489 | 1.7376 |
| 2026-01-14 | 2026-01-15 | 300111.SZSE | 向日葵 | -20.0 | -10.0145 | low_repair | panic_low_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 33.8468 | 21.9325 | 32.1793 | 2.945 | 1.8504 | 2.9713 |
| 2025-09-03 | 2025-09-04 | 301357.SZSE | 北方长龙 | -19.9987 | -19.9989 | low_repair | panic_low_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 25.8947 | 23.8692 | 32.1499 | 1.1363 | 0.9395 | 1.2389 |
| 2026-01-14 | 2026-01-15 | 301230.SZSE | 泓博医药 | -19.997 | 16.1017 | extreme_hot | first_sun_or_strong_close | extreme_high_turnover_proxy | sudden_volume_expansion | multi_limit_source | 45.7035 | 6.2877 | 29.1088 | 6.4527 | 0.972 | 7.5545 |
| 2025-10-15 | 2025-10-16 | 301209.SZSE | 联合化学 | -19.9965 | -9.0317 | high_momentum | panic_low_close | active | mixed_volume | single_limit_source | 5.4107 | 3.5731 | 4.2027 | 1.5678 | 0.9542 | 1.1515 |
| 2026-01-14 | 2026-01-15 | 301408.SZSE | 华人健康 | -19.9933 | 20.0 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 38.3075 | 26.3182 | 24.4533 | 1.7207 | 1.3546 | 1.4641 |
| 2025-12-02 | 2025-12-03 | 300456.SZSE | 赛微电子 | -19.5619 | 15.2693 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 35.1349 | 29.3254 | 28.4226 | 1.6315 | 1.5607 | 1.6522 |
| 2026-01-14 | 2026-01-15 | 688568.SSE | 中科星图 | -19.0873 | 13.9228 | extreme_hot | first_sun_or_strong_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 21.9352 | 21.1521 | 12.2065 | 1.828 | 2.0525 | 1.3452 |
| 2025-12-12 | 2025-12-15 | 688109.SSE | 品茗科技 | -18.6718 | -12.2021 | neutral | intraday_fade | hot_high_turnover_proxy | volume_rising_three_day | touched_but_not_closed_limit | 13.247 | 6.3879 | 4.3242 | 2.2464 | 0.9313 | 0.6225 |
| 2026-01-23 | 2026-01-26 | 688387.SSE | 信科移动 | -18.1527 | 18.4082 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | volume_rising_three_day | multi_limit_source | 8.5797 | 5.1792 | 4.2484 | 1.4141 | 0.9884 | 0.7969 |
| 2025-06-23 | 2025-06-24 | 300483.SZSE | 首华燃气 | -18.0027 | -0.8754 | high_momentum | intraday_fade | extreme_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 15.5751 | 15.0558 | 8.1524 | 3.1606 | 3.9022 | 2.9066 |

## Notes

- stock_daily_bars 没有历史换手率字段；turnover_proxy 使用 D 日成交额 / 当前 market_cap 近似，只能作为成交活跃度代理，不是严格点位历史换手率。
- volume_ratio/amount_ratio 使用 D 日成交量或成交额相对前 20 日均值，前 20 日均值不包含 D 日。
- 所有正向/负向 flag 都只使用 D 日收盘前可见信息；D+1 只作为标签。
- 主样本剔除北交所、ST/退市、非连续 D+1、新股/除权或数据异常导致的超涨跌幅样本。
