# D+1 Event Feature Research Set

## Dataset

- rows: `1104278`
- symbols: `3046`
- days: `367`
- range: `2025-01-02` .. `2026-07-10`
- historical_turnover_rate_coverage_pct: `99.9995`

## Baseline

- n: `1104278`
- win_rate: `48.0153`
- avg_return: `0.0602`
- median_return: `0.0`
- d1_limit_rate: `1.9148`
- d1_big_up7_rate: `2.481`
- d1_big_down7_rate: `1.321`

## Feature Flags

| flag | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_up7_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hot_reacceleration_exhaustion | 1102 | 56.7151 | 1.2558 | 1.4215 | 25.6806 | 30.9437 | 18.0581 |
| deep_low_first_sun_confirm | 4873 | 56.6181 | 0.6388 | 0.5329 | 3.5502 | 4.5557 | 1.2928 |
| active_source_compressed_high_close | 8369 | 51.0097 | 0.6341 | 0.1516 | 9.3321 | 11.2319 | 4.1104 |
| deep_low_close_rebound_absorption | 20362 | 52.0136 | 0.0863 | 0.1826 | 2.0332 | 2.9123 | 2.6962 |
| weak_repair_high_close_no_source | 120005 | 46.9097 | 0.0352 | 0.0 | 0.6308 | 0.8383 | 0.4941 |
| active_source_breakdown | 18347 | 44.2143 | -0.3776 | -0.5245 | 6.3662 | 7.7996 | 7.8596 |
| extreme_volume_intraday_fade | 7829 | 41.7806 | -0.6001 | -0.9822 | 8.6984 | 10.3078 | 11.6107 |

## Stacked Feature Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_up7_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| high_momentum::ordinary::contracted_low_turnover_proxy::multi_limit_source | 158 | 79.7468 | 6.125 | 9.9812 | 62.0253 | 63.9241 | 3.1646 |
| high_momentum::ordinary::contracted_low_turnover_proxy::no_limit_source | 159 | 82.3899 | 3.3583 | 4.9808 | 9.434 | 10.0629 | 0.0 |
| high_momentum::ordinary::contracted::single_limit_source | 199 | 66.8342 | 3.216 | 2.0442 | 37.1859 | 37.1859 | 4.0201 |
| high_momentum::ordinary::contracted::multi_limit_source | 358 | 63.6872 | 3.1062 | 2.662 | 36.5922 | 39.9441 | 7.8212 |
| high_momentum::first_sun_or_strong_close::contracted::crowded_active_source | 143 | 65.7343 | 2.6163 | 3.1208 | 24.4755 | 28.6713 | 6.2937 |
| high_momentum::first_sun_or_strong_close::contracted::multi_limit_source | 179 | 60.8939 | 2.0759 | 1.3177 | 21.7877 | 24.0223 | 6.1453 |
| deep_oversold::panic_low_close::active::no_limit_source | 994 | 72.1328 | 2.031 | 2.4747 | 1.1066 | 3.8229 | 1.1066 |
| deep_oversold::high_close::active::no_limit_source | 213 | 72.77 | 1.9823 | 2.1266 | 1.8779 | 5.1643 | 0.0 |
| deep_oversold::first_sun_or_strong_close::active::no_limit_source | 283 | 73.1449 | 1.5972 | 1.8587 | 2.4735 | 4.2403 | 0.3534 |
| high_momentum::first_sun_or_strong_close::normal::crowded_active_source | 211 | 50.7109 | 1.5122 | 0.4208 | 22.7488 | 26.5403 | 5.6872 |
| deep_oversold::intraday_fade::normal::no_limit_source | 136 | 76.4706 | 1.5059 | 1.5546 | 2.9412 | 5.1471 | 0.7353 |
| high_momentum::ordinary::contracted::crowded_active_source | 234 | 55.1282 | 1.4781 | 1.1081 | 28.6325 | 31.6239 | 13.2479 |
| deep_oversold::high_close::contracted_low_turnover_proxy::no_limit_source | 537 | 68.7151 | 1.4578 | 1.1173 | 1.3035 | 2.4209 | 0.0 |
| deep_oversold::panic_low_close::hot::no_limit_source | 195 | 70.2564 | 1.3973 | 1.4341 | 1.5385 | 3.0769 | 1.5385 |
| deep_oversold::first_sun_or_strong_close::normal::no_limit_source | 695 | 67.482 | 1.2361 | 1.1692 | 3.0216 | 4.0288 | 0.1439 |
| extreme_hot::first_sun_or_strong_close::active_high_turnover_proxy::crowded_active_source | 242 | 56.6116 | 1.1949 | 1.1478 | 21.9008 | 26.0331 | 13.6364 |
| deep_oversold::low_close::contracted_high_turnover_proxy::crowded_active_source | 149 | 62.4161 | 1.1445 | 0.8638 | 7.3826 | 8.7248 | 1.3423 |
| high_momentum::ordinary::normal::multi_limit_source | 713 | 55.6802 | 1.137 | 0.5168 | 13.4642 | 16.129 | 2.9453 |
| high_momentum::first_sun_or_strong_close::hot::multi_limit_source | 410 | 54.878 | 1.1263 | 0.3233 | 13.4146 | 16.5854 | 5.3659 |
| deep_oversold::high_close::normal_low_turnover_proxy::no_limit_source | 224 | 65.625 | 1.0781 | 1.0652 | 0.8929 | 1.3393 | 0.0 |
| high_momentum::first_sun_or_strong_close::normal::multi_limit_source | 614 | 52.7687 | 1.0664 | 0.3177 | 12.7036 | 15.6352 | 3.5831 |
| deep_oversold::high_close::normal::no_limit_source | 743 | 67.0256 | 1.0477 | 1.3333 | 2.1534 | 2.5572 | 0.5384 |
| high_momentum::first_sun_or_strong_close::extreme::no_limit_source | 1563 | 49.968 | 0.985 | 0.0 | 12.0921 | 13.9475 | 1.8554 |
| high_momentum::first_sun_or_strong_close::extreme::multi_limit_source | 261 | 49.8084 | 0.9832 | 0.0 | 24.1379 | 27.2031 | 11.8774 |
| high_momentum::low_close::hot::multi_limit_source | 149 | 56.3758 | 0.9824 | 0.6482 | 6.0403 | 8.0537 | 1.3423 |
| high_momentum::first_sun_or_strong_close::normal::single_limit_source | 591 | 52.4535 | 0.9648 | 0.2724 | 9.8139 | 13.0288 | 3.2149 |
| deep_oversold::first_sun_or_strong_close::contracted::multi_limit_source | 260 | 59.6154 | 0.9255 | 0.7263 | 3.8462 | 4.2308 | 0.0 |
| deep_oversold::ordinary::active::no_limit_source | 586 | 62.4573 | 0.9197 | 0.7178 | 2.2184 | 3.413 | 0.6826 |
| low_repair::panic_low_close::hot::no_limit_source | 588 | 62.585 | 0.9143 | 1.1361 | 2.381 | 3.7415 | 1.3605 |
| high_momentum::intraday_fade::active::multi_limit_source | 125 | 48.0 | 0.8968 | 0.0 | 10.4 | 15.2 | 2.4 |
| high_momentum::first_sun_or_strong_close::normal_high_turnover_proxy::crowded_active_source | 383 | 52.4804 | 0.8653 | 0.5435 | 15.9269 | 18.2768 | 9.1384 |
| high_momentum::low_close::active::touched_but_not_closed_limit | 230 | 53.0435 | 0.8492 | 0.3193 | 8.2609 | 10.4348 | 0.8696 |
| deep_oversold::first_sun_or_strong_close::contracted::touched_but_not_closed_limit | 344 | 61.3372 | 0.8445 | 0.6565 | 3.4884 | 4.0698 | 0.8721 |
| low_repair::panic_low_close::active_low_turnover_proxy::no_limit_source | 145 | 64.1379 | 0.8199 | 0.8333 | 0.0 | 0.0 | 2.7586 |
| deep_oversold::high_close::contracted::single_limit_source | 754 | 56.6313 | 0.8039 | 0.5747 | 1.7241 | 2.9178 | 0.2653 |
| deep_oversold::panic_low_close::normal::no_limit_source | 1366 | 59.5168 | 0.7868 | 1.0136 | 1.4641 | 2.2694 | 1.3177 |
| high_momentum::first_sun_or_strong_close::hot::single_limit_source | 1017 | 49.9508 | 0.774 | 0.0 | 10.2262 | 12.6844 | 3.7365 |
| neutral::low_close::active_low_turnover_proxy::single_limit_source | 125 | 59.2 | 0.7714 | 0.4167 | 1.6 | 2.4 | 0.0 |
| deep_oversold::high_close::contracted::touched_but_not_closed_limit | 485 | 58.9691 | 0.7512 | 0.6289 | 0.6186 | 1.2371 | 0.2062 |
| high_momentum::first_sun_or_strong_close::active::single_limit_source | 1246 | 49.3579 | 0.7473 | 0.0 | 9.3098 | 12.2793 | 2.8892 |

## Event Pattern Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- |
| hot_reacceleration_exhaustion | 844 | 54.1469 | 0.8074 | 0.973 | 24.0521 | 20.2607 |
| active_source_compressed_high_close | 8062 | 50.9799 | 0.6427 | 0.1463 | 9.5014 | 4.1429 |
| deep_low_first_sun_confirm | 4873 | 56.6181 | 0.6388 | 0.5329 | 3.5502 | 1.2928 |
| multi_day_contraction_base | 236536 | 49.31 | 0.1035 | 0.0 | 1.5592 | 0.9297 |
| deep_low_close_absorption | 20362 | 52.0136 | 0.0863 | 0.1826 | 2.0332 | 2.6962 |
| mixed | 437117 | 47.0936 | 0.0781 | -0.0515 | 2.3248 | 1.2226 |
| no_source_controlled_repair | 289541 | 47.6095 | 0.0361 | 0.0 | 0.6079 | 0.479 |
| low_position_no_source_low_close_repair | 65793 | 51.6605 | 0.0097 | 0.1254 | 0.6216 | 0.839 |
| active_source_breakdown | 14996 | 45.092 | -0.2547 | -0.4122 | 5.7015 | 6.2617 |
| crowded_high_turnover_momentum | 18325 | 43.3506 | -0.299 | -0.9608 | 11.0996 | 11.678 |
| extreme_volume_intraday_fade | 7829 | 41.7806 | -0.6001 | -0.9822 | 8.6984 | 11.6107 |

## Volume And Turnover Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- |
| volume_rising_three_day::hot_low_turnover_proxy | 1897 | 50.0264 | 0.3735 | 0.0059 | 1.845 | 0.5271 |
| sudden_volume_expansion::extreme | 2943 | 44.6823 | 0.3316 | -0.3106 | 6.524 | 1.7329 |
| sudden_volume_expansion::hot_low_turnover_proxy | 516 | 50.0 | 0.2433 | 0.0177 | 0.969 | 0.5814 |
| volume_contracting_three_day::active_low_turnover_proxy | 3580 | 49.1061 | 0.2167 | 0.0 | 1.257 | 0.3631 |
| volume_rising_three_day::hot | 16097 | 45.7601 | 0.2125 | -0.1658 | 3.1807 | 1.0188 |
| volume_rising_three_day::extreme_low_turnover_proxy | 282 | 44.6809 | 0.1841 | -0.2662 | 2.8369 | 1.4184 |
| mixed_volume::contracted_low_turnover_proxy | 20580 | 51.4189 | 0.1838 | 0.0996 | 0.7483 | 0.6948 |
| sudden_volume_expansion::hot | 5331 | 45.3011 | 0.1831 | -0.1776 | 3.5828 | 1.088 |
| mixed_volume::hot | 20590 | 45.9543 | 0.1816 | -0.1516 | 3.3366 | 1.1802 |
| volume_rising_three_day::extreme | 7681 | 43.1194 | 0.1567 | -0.4283 | 5.8065 | 1.7706 |
| volume_contracting_three_day::hot | 4112 | 45.8414 | 0.1557 | -0.2292 | 4.2072 | 1.9698 |
| mixed_volume::active_low_turnover_proxy | 21678 | 48.4916 | 0.1454 | 0.0 | 0.7565 | 0.4382 |
| volume_contracting_three_day::extreme | 599 | 46.2437 | 0.1443 | -0.2188 | 6.8447 | 3.6728 |
| volume_contracting_three_day::active | 21767 | 48.2657 | 0.1432 | 0.0 | 2.4533 | 1.2955 |
| volume_rising_three_day::active_low_turnover_proxy | 10643 | 49.394 | 0.1427 | 0.0 | 0.6389 | 0.2913 |
| turnover_rate_2_6::turnover_ratio_gt_1_15 | 124689 | 46.9448 | 0.1372 | -0.0955 | 2.5672 | 1.0683 |
| volume_contracting_three_day::contracted_low_turnover_proxy | 27326 | 49.5718 | 0.1361 | 0.0 | 0.8783 | 0.505 |
| mixed_volume::extreme | 5236 | 43.8503 | 0.1316 | -0.3676 | 5.7869 | 2.3682 |
| multi_day_contraction::contracted_low_turnover_proxy | 79048 | 50.7236 | 0.1315 | 0.0731 | 0.6629 | 0.8476 |
| mixed_volume::hot_low_turnover_proxy | 1845 | 44.8238 | 0.1309 | -0.1214 | 1.1382 | 0.4878 |
| volume_rising_three_day::active | 37285 | 47.7511 | 0.129 | 0.0 | 1.7111 | 0.7912 |
| mixed_volume::active | 83752 | 47.3254 | 0.1234 | 0.0 | 2.0095 | 0.9301 |
| volume_contracting_three_day::normal_low_turnover_proxy | 32138 | 49.2408 | 0.1206 | 0.0 | 0.585 | 0.3205 |
| mixed_volume::normal_low_turnover_proxy | 76389 | 49.371 | 0.1136 | 0.0 | 0.4831 | 0.3705 |
| volume_rising_three_day::normal_low_turnover_proxy | 14526 | 49.3047 | 0.1111 | 0.0 | 0.5163 | 0.296 |
| volume_contracting_three_day::normal | 67264 | 48.2933 | 0.094 | 0.0 | 1.7781 | 0.7909 |
| mixed_volume::contracted | 27336 | 49.0416 | 0.0928 | 0.0 | 1.9571 | 1.1779 |
| turnover_rate_lt_2::turnover_ratio_lt_0_70 | 211471 | 49.6215 | 0.0916 | 0.0 | 0.8569 | 0.7656 |
| multi_day_contraction::normal_low_turnover_proxy | 19418 | 48.5683 | 0.0882 | 0.0 | 0.5253 | 0.3965 |
| turnover_rate_lt_2::turnover_ratio_gt_1_15 | 91968 | 47.4187 | 0.0846 | 0.0 | 0.7774 | 0.4306 |
| turnover_rate_2_6::turnover_ratio_0_70_0_90 | 76258 | 48.4487 | 0.0817 | 0.0 | 1.9919 | 1.0963 |
| turnover_rate_6_12::turnover_ratio_lt_0_70 | 14311 | 48.5361 | 0.0802 | -0.0564 | 4.0109 | 2.4806 |
| turnover_rate_2_6::turnover_ratio_0_90_1_15 | 76808 | 48.1369 | 0.079 | 0.0 | 1.9152 | 1.0559 |
| turnover_rate_2_6::turnover_ratio_lt_0_70 | 105234 | 49.2217 | 0.0639 | 0.0 | 1.8226 | 1.2429 |
| mixed_volume::normal | 142829 | 48.2262 | 0.063 | 0.0 | 1.4871 | 0.8136 |
| turnover_rate_lt_2::turnover_ratio_0_90_1_15 | 118118 | 48.4905 | 0.06 | 0.0 | 0.5935 | 0.3886 |
| volume_contracting_three_day::contracted | 39555 | 48.0672 | 0.0598 | 0.0 | 1.9669 | 1.1301 |
| turnover_rate_gt_12::turnover_ratio_lt_0_70 | 2012 | 47.4155 | 0.0516 | -0.1929 | 5.8648 | 4.7217 |
| turnover_rate_lt_2::turnover_ratio_0_70_0_90 | 155577 | 48.5091 | 0.0513 | 0.0 | 0.5856 | 0.3998 |
| volume_rising_three_day::normal | 33254 | 48.2378 | 0.0337 | 0.0 | 1.4134 | 0.851 |

## Target Feature Mix

| target | feature | n | share_in_target | avg_return | median_return |
| --- | --- | --- | --- | --- | --- |
| d1_limit_up | event_pattern_group=mixed | 10162 | 48.0586 | 9.9933 | 10.0 |
| d1_limit_up | event_pattern_group=multi_day_contraction_base | 3688 | 17.4415 | 9.9957 | 10.0 |
| d1_limit_up | event_pattern_group=crowded_high_turnover_momentum | 2034 | 9.6193 | 9.9956 | 10.0 |
| d1_limit_up | event_pattern_group=no_source_controlled_repair | 1760 | 8.3235 | 9.9979 | 10.0 |
| d1_limit_up | event_pattern_group=active_source_breakdown | 855 | 4.0435 | 9.9957 | 10.0 |
| d1_limit_up | event_pattern_group=active_source_compressed_high_close | 766 | 3.6226 | 9.9889 | 10.0 |
| d1_limit_up | event_pattern_group=extreme_volume_intraday_fade | 681 | 3.2206 | 10.0013 | 10.0 |
| d1_limit_up | event_pattern_group=deep_low_close_absorption | 414 | 1.9579 | 9.9894 | 10.0 |
| d1_limit_up | event_pattern_group=low_position_no_source_low_close_repair | 409 | 1.9343 | 10.0015 | 10.0 |
| d1_limit_up | event_pattern_group=hot_reacceleration_exhaustion | 203 | 0.96 | 9.9914 | 10.0 |
| d1_limit_up | event_pattern_group=deep_low_first_sun_confirm | 173 | 0.8182 | 9.9883 | 10.0 |
| d1_limit_up | position_group=neutral | 9245 | 43.7219 | 9.9958 | 10.0 |
| d1_limit_up | position_group=high_momentum | 7025 | 33.223 | 9.9929 | 10.0 |
| d1_limit_up | position_group=low_repair | 3054 | 14.4431 | 9.9963 | 10.0 |
| d1_limit_up | position_group=deep_oversold | 1281 | 6.0582 | 9.993 | 10.0 |
| d1_limit_up | position_group=extreme_hot | 540 | 2.5538 | 9.9869 | 10.0 |
| d1_limit_up | price_action_group=first_sun_or_strong_close | 5878 | 27.7985 | 9.9948 | 10.0 |
| d1_limit_up | price_action_group=ordinary | 4687 | 22.166 | 9.9934 | 10.0 |
| d1_limit_up | price_action_group=low_close | 3328 | 15.7389 | 9.9947 | 10.0 |
| d1_limit_up | price_action_group=balanced_mid_close | 1864 | 8.8153 | 9.9939 | 10.0 |
| d1_limit_up | price_action_group=compressed_mid_close | 1759 | 8.3188 | 9.9931 | 10.0 |
| d1_limit_up | price_action_group=high_close | 1464 | 6.9236 | 9.9994 | 10.0 |
| d1_limit_up | price_action_group=panic_low_close | 1221 | 5.7744 | 9.9937 | 10.0 |
| d1_limit_up | price_action_group=intraday_fade | 944 | 4.4644 | 9.9954 | 10.0 |
| d1_limit_up | volume_turnover_group=normal | 4222 | 19.9669 | 9.9952 | 10.0 |
| d1_limit_up | volume_turnover_group=contracted | 3179 | 15.0343 | 9.9947 | 10.0 |
| d1_limit_up | volume_turnover_group=active | 2860 | 13.5257 | 9.9888 | 10.0 |
| d1_limit_up | volume_turnover_group=extreme_high_turnover_proxy | 1930 | 9.1275 | 9.9991 | 10.0 |
| d1_limit_up | volume_turnover_group=hot | 1565 | 7.4013 | 9.996 | 10.0 |
| d1_limit_up | volume_turnover_group=active_high_turnover_proxy | 1538 | 7.2736 | 9.9956 | 10.0 |
| d1_limit_up | volume_turnover_group=hot_high_turnover_proxy | 1429 | 6.7581 | 9.9949 | 10.0 |
| d1_limit_up | volume_turnover_group=normal_high_turnover_proxy | 1014 | 4.7955 | 9.9909 | 10.0 |
| d1_limit_up | volume_turnover_group=extreme | 982 | 4.6441 | 10.0016 | 10.0 |
| d1_limit_up | volume_turnover_group=contracted_low_turnover_proxy | 918 | 4.3415 | 9.9954 | 10.0 |
| d1_limit_up | volume_turnover_group=normal_low_turnover_proxy | 734 | 3.4713 | 9.9925 | 10.0 |
| d1_limit_up | volume_turnover_group=contracted_high_turnover_proxy | 400 | 1.8917 | 9.993 | 10.0 |
| d1_limit_up | volume_turnover_group=active_low_turnover_proxy | 279 | 1.3195 | 9.9885 | 10.0 |
| d1_limit_up | volume_turnover_group=hot_low_turnover_proxy | 65 | 0.3074 | 9.9805 | 10.0024 |
| d1_limit_up | volume_turnover_group=extreme_low_turnover_proxy | 22 | 0.104 | 10.0131 | 10.009 |
| d1_limit_up | volume_turnover_group=unknown_turnover | 8 | 0.0378 | 9.9962 | 10.0017 |
| d1_limit_up | active_source_group=no_limit_source | 7648 | 36.1693 | 9.9964 | 10.0 |
| d1_limit_up | active_source_group=single_limit_source | 4687 | 22.166 | 9.9941 | 10.0 |
| d1_limit_up | active_source_group=multi_limit_source | 4096 | 19.371 | 9.9946 | 10.0 |
| d1_limit_up | active_source_group=crowded_active_source | 2385 | 11.2793 | 9.9939 | 10.0 |
| d1_limit_up | active_source_group=touched_but_not_closed_limit | 2329 | 11.0144 | 9.9899 | 10.0 |
| d1_limit_up | pre_volume_pattern=mixed_volume | 6047 | 28.5978 | 9.9931 | 10.0 |
| d1_limit_up | pre_volume_pattern=volume_contracting_three_day | 4515 | 21.3526 | 9.9954 | 10.0 |
| d1_limit_up | pre_volume_pattern=volume_rising_three_day | 3669 | 17.3516 | 9.9942 | 10.0 |
| d1_limit_up | pre_volume_pattern=multi_day_contraction | 3228 | 15.266 | 9.9944 | 10.0 |
| d1_limit_up | pre_volume_pattern=high_turnover_proxy_latest | 2917 | 13.7952 | 9.9954 | 10.0 |
| d1_limit_up | pre_volume_pattern=sudden_volume_expansion | 759 | 3.5895 | 9.9997 | 10.0 |
| d1_limit_up | pre_volume_pattern=volume_history_unknown | 10 | 0.0473 | 9.998 | 10.0017 |
| d1_limit_up | flag=active_source_compressed_high_close | 781 | 3.6935 | 9.9879 | 10.0 |
| d1_limit_up | flag=deep_low_close_rebound_absorption | 414 | 1.9579 | 9.9894 | 10.0 |
| d1_limit_up | flag=deep_low_first_sun_confirm | 173 | 0.8182 | 9.9883 | 10.0 |
| d1_limit_up | flag=extreme_volume_intraday_fade | 681 | 3.2206 | 10.0013 | 10.0 |
| d1_limit_up | flag=active_source_breakdown | 1168 | 5.5238 | 9.9983 | 10.0 |
| d1_limit_up | flag=hot_reacceleration_exhaustion | 283 | 1.3384 | 9.9864 | 10.0 |
| d1_limit_up | flag=weak_repair_high_close_no_source | 757 | 3.58 | 10.0001 | 10.0 |
| d1_big_up7 | event_pattern_group=mixed | 13227 | 48.279 | 9.4842 | 9.995 |
| d1_big_up7 | event_pattern_group=multi_day_contraction_base | 4880 | 17.8122 | 9.4439 | 9.9934 |
| d1_big_up7 | event_pattern_group=crowded_high_turnover_momentum | 2437 | 8.8951 | 9.6359 | 10.0 |
| d1_big_up7 | event_pattern_group=no_source_controlled_repair | 2409 | 8.7929 | 9.396 | 9.9913 |
| d1_big_up7 | event_pattern_group=active_source_breakdown | 1067 | 3.8946 | 9.5709 | 9.9967 |
| d1_big_up7 | event_pattern_group=active_source_compressed_high_close | 922 | 3.3653 | 9.6371 | 9.9987 |
| d1_big_up7 | event_pattern_group=extreme_volume_intraday_fade | 807 | 2.9456 | 9.6628 | 10.0 |
| d1_big_up7 | event_pattern_group=deep_low_close_absorption | 593 | 2.1645 | 9.3288 | 9.9878 |
| d1_big_up7 | event_pattern_group=low_position_no_source_low_close_repair | 586 | 2.1389 | 9.2928 | 9.9906 |
| d1_big_up7 | event_pattern_group=hot_reacceleration_exhaustion | 247 | 0.9016 | 9.6635 | 10.0 |
| d1_big_up7 | event_pattern_group=deep_low_first_sun_confirm | 222 | 0.8103 | 9.5102 | 9.9908 |
| d1_big_up7 | position_group=neutral | 12093 | 44.1399 | 9.4722 | 9.994 |
| d1_big_up7 | position_group=high_momentum | 8674 | 31.6604 | 9.5868 | 9.9983 |
| d1_big_up7 | position_group=low_repair | 4167 | 15.2097 | 9.389 | 9.9923 |
| d1_big_up7 | position_group=deep_oversold | 1808 | 6.5993 | 9.3424 | 9.989 |
| d1_big_up7 | position_group=extreme_hot | 655 | 2.3908 | 9.6239 | 10.0 |
| d1_big_up7 | price_action_group=first_sun_or_strong_close | 7089 | 25.8751 | 9.6292 | 10.0 |
| d1_big_up7 | price_action_group=ordinary | 6053 | 22.0937 | 9.4986 | 9.9951 |
| d1_big_up7 | price_action_group=low_close | 4617 | 16.8522 | 9.3634 | 9.9913 |
| d1_big_up7 | price_action_group=balanced_mid_close | 2557 | 9.3331 | 9.3974 | 9.9918 |
| d1_big_up7 | price_action_group=compressed_mid_close | 2366 | 8.636 | 9.414 | 9.9924 |
| d1_big_up7 | price_action_group=high_close | 1921 | 7.0117 | 9.4594 | 9.9948 |
| d1_big_up7 | price_action_group=panic_low_close | 1596 | 5.8255 | 9.4822 | 9.9948 |
| d1_big_up7 | price_action_group=intraday_fade | 1198 | 4.3727 | 9.5385 | 10.0 |
| d1_big_up7 | volume_turnover_group=normal | 5701 | 20.8088 | 9.4177 | 9.9945 |
| d1_big_up7 | volume_turnover_group=contracted | 4139 | 15.1075 | 9.4672 | 9.9936 |
| d1_big_up7 | volume_turnover_group=active | 3933 | 14.3556 | 9.4009 | 9.9932 |
| d1_big_up7 | volume_turnover_group=extreme_high_turnover_proxy | 2225 | 8.1213 | 9.715 | 10.0 |
| d1_big_up7 | volume_turnover_group=hot | 2015 | 7.3548 | 9.5221 | 9.996 |
| d1_big_up7 | volume_turnover_group=active_high_turnover_proxy | 1963 | 7.165 | 9.5191 | 9.9959 |
| d1_big_up7 | volume_turnover_group=hot_high_turnover_proxy | 1716 | 6.2635 | 9.6313 | 10.0 |
| d1_big_up7 | volume_turnover_group=normal_high_turnover_proxy | 1275 | 4.6538 | 9.5378 | 9.997 |
| d1_big_up7 | volume_turnover_group=contracted_low_turnover_proxy | 1211 | 4.4202 | 9.4562 | 9.9934 |
| d1_big_up7 | volume_turnover_group=extreme | 1175 | 4.2888 | 9.6375 | 10.0 |
| d1_big_up7 | volume_turnover_group=normal_low_turnover_proxy | 1052 | 3.8398 | 9.3142 | 9.9896 |
| d1_big_up7 | volume_turnover_group=contracted_high_turnover_proxy | 490 | 1.7885 | 9.5738 | 9.999 |
| d1_big_up7 | volume_turnover_group=active_low_turnover_proxy | 384 | 1.4016 | 9.3758 | 9.9941 |
| d1_big_up7 | volume_turnover_group=hot_low_turnover_proxy | 84 | 0.3066 | 9.5193 | 9.9938 |
| d1_big_up7 | volume_turnover_group=extreme_low_turnover_proxy | 25 | 0.0913 | 9.7024 | 10.0063 |
| d1_big_up7 | volume_turnover_group=unknown_turnover | 9 | 0.0329 | 9.7962 | 10.0014 |
| d1_big_up7 | active_source_group=no_limit_source | 10312 | 37.6392 | 9.4188 | 9.9923 |
| d1_big_up7 | active_source_group=single_limit_source | 6112 | 22.309 | 9.4809 | 9.9953 |
| d1_big_up7 | active_source_group=multi_limit_source | 5001 | 18.2538 | 9.6052 | 9.9989 |
| d1_big_up7 | active_source_group=touched_but_not_closed_limit | 3121 | 11.3918 | 9.4328 | 9.9917 |
| d1_big_up7 | active_source_group=crowded_active_source | 2851 | 10.4062 | 9.6363 | 10.0 |
| d1_big_up7 | pre_volume_pattern=mixed_volume | 8144 | 29.7259 | 9.4258 | 9.9942 |
| d1_big_up7 | pre_volume_pattern=volume_contracting_three_day | 5788 | 21.1264 | 9.5101 | 9.995 |
| d1_big_up7 | pre_volume_pattern=volume_rising_three_day | 4684 | 17.0968 | 9.5216 | 9.9965 |
| d1_big_up7 | pre_volume_pattern=multi_day_contraction | 4274 | 15.6002 | 9.4408 | 9.993 |
| d1_big_up7 | pre_volume_pattern=high_turnover_proxy_latest | 3613 | 13.1876 | 9.5731 | 9.9979 |
| d1_big_up7 | pre_volume_pattern=sudden_volume_expansion | 881 | 3.2157 | 9.7068 | 10.0 |
| d1_big_up7 | pre_volume_pattern=volume_history_unknown | 13 | 0.0475 | 9.6339 | 9.9948 |
| d1_big_up7 | flag=active_source_compressed_high_close | 940 | 3.431 | 9.6399 | 9.9985 |
| d1_big_up7 | flag=deep_low_close_rebound_absorption | 593 | 2.1645 | 9.3288 | 9.9878 |
| d1_big_up7 | flag=deep_low_first_sun_confirm | 222 | 0.8103 | 9.5102 | 9.9908 |
| d1_big_up7 | flag=extreme_volume_intraday_fade | 807 | 2.9456 | 9.6628 | 10.0 |
| d1_big_up7 | flag=active_source_breakdown | 1431 | 5.2232 | 9.6062 | 9.9981 |
| d1_big_up7 | flag=hot_reacceleration_exhaustion | 341 | 1.2447 | 9.6507 | 9.9993 |
| d1_big_up7 | flag=weak_repair_high_close_no_source | 1006 | 3.6719 | 9.4331 | 9.9936 |
| d1_big_down7 | event_pattern_group=mixed | 5344 | 36.6354 | -8.7858 | -8.8207 |
| d1_big_down7 | event_pattern_group=multi_day_contraction_base | 2199 | 15.0751 | -8.9424 | -9.5477 |
| d1_big_down7 | event_pattern_group=crowded_high_turnover_momentum | 2140 | 14.6706 | -9.0336 | -9.6301 |
| d1_big_down7 | event_pattern_group=no_source_controlled_repair | 1387 | 9.5085 | -9.3854 | -9.9631 |
| d1_big_down7 | event_pattern_group=active_source_breakdown | 939 | 6.4372 | -8.9922 | -9.3827 |
| d1_big_down7 | event_pattern_group=extreme_volume_intraday_fade | 909 | 6.2316 | -9.097 | -9.772 |
| d1_big_down7 | event_pattern_group=low_position_no_source_low_close_repair | 552 | 3.7842 | -8.7925 | -8.6742 |
| d1_big_down7 | event_pattern_group=deep_low_close_absorption | 549 | 3.7636 | -8.6137 | -8.3946 |
| d1_big_down7 | event_pattern_group=active_source_compressed_high_close | 334 | 2.2897 | -8.9134 | -9.2882 |
| d1_big_down7 | event_pattern_group=hot_reacceleration_exhaustion | 171 | 1.1723 | -9.5524 | -9.9865 |
| d1_big_down7 | event_pattern_group=deep_low_first_sun_confirm | 63 | 0.4319 | -8.8521 | -8.9249 |
| d1_big_down7 | position_group=high_momentum | 4969 | 34.0646 | -8.9432 | -9.2664 |
| d1_big_down7 | position_group=neutral | 4957 | 33.9823 | -8.9052 | -9.2033 |
| d1_big_down7 | position_group=low_repair | 2770 | 18.9895 | -8.9724 | -9.8066 |
| d1_big_down7 | position_group=deep_oversold | 1352 | 9.2685 | -8.7934 | -8.8013 |
| d1_big_down7 | position_group=extreme_hot | 539 | 3.6951 | -9.4711 | -9.9872 |
| d1_big_down7 | price_action_group=ordinary | 3103 | 21.2724 | -8.8959 | -9.1324 |
| d1_big_down7 | price_action_group=first_sun_or_strong_close | 2673 | 18.3245 | -8.9801 | -9.4714 |
| d1_big_down7 | price_action_group=panic_low_close | 2216 | 15.1916 | -9.0179 | -9.4771 |
| d1_big_down7 | price_action_group=low_close | 2105 | 14.4307 | -8.668 | -8.4899 |
| d1_big_down7 | price_action_group=compressed_mid_close | 1326 | 9.0903 | -9.2147 | -9.9559 |
| d1_big_down7 | price_action_group=balanced_mid_close | 1160 | 7.9523 | -8.8388 | -8.9312 |
| d1_big_down7 | price_action_group=intraday_fade | 1068 | 7.3216 | -8.933 | -9.2151 |
| d1_big_down7 | price_action_group=high_close | 936 | 6.4167 | -9.1655 | -9.8964 |
| d1_big_down7 | volume_turnover_group=contracted | 2278 | 15.6166 | -8.9786 | -9.7853 |
| d1_big_down7 | volume_turnover_group=normal | 2230 | 15.2876 | -8.7347 | -8.6499 |
| d1_big_down7 | volume_turnover_group=extreme_high_turnover_proxy | 1968 | 13.4915 | -9.1299 | -9.8983 |
| d1_big_down7 | volume_turnover_group=active_high_turnover_proxy | 1489 | 10.2077 | -8.9362 | -9.2166 |
| d1_big_down7 | volume_turnover_group=active | 1358 | 9.3097 | -8.7574 | -8.7356 |
| d1_big_down7 | volume_turnover_group=hot_high_turnover_proxy | 1329 | 9.1109 | -8.9565 | -9.316 |
| d1_big_down7 | volume_turnover_group=normal_high_turnover_proxy | 1062 | 7.2805 | -8.8442 | -8.8773 |
| d1_big_down7 | volume_turnover_group=contracted_low_turnover_proxy | 951 | 6.5195 | -9.4523 | -9.9755 |
| d1_big_down7 | volume_turnover_group=hot | 546 | 3.7431 | -8.8006 | -8.816 |
| d1_big_down7 | volume_turnover_group=normal_low_turnover_proxy | 506 | 3.4688 | -9.0551 | -9.8029 |
| d1_big_down7 | volume_turnover_group=extreme | 333 | 2.2829 | -8.8004 | -8.8508 |
| d1_big_down7 | volume_turnover_group=contracted_high_turnover_proxy | 332 | 2.276 | -8.6812 | -8.6891 |
| d1_big_down7 | volume_turnover_group=active_low_turnover_proxy | 139 | 0.9529 | -9.0319 | -9.5445 |
| d1_big_down7 | volume_turnover_group=unknown_turnover | 35 | 0.2399 | -8.7773 | -8.7726 |
| d1_big_down7 | volume_turnover_group=hot_low_turnover_proxy | 24 | 0.1645 | -9.021 | -9.2004 |
| d1_big_down7 | volume_turnover_group=extreme_low_turnover_proxy | 7 | 0.048 | -9.5822 | -10.0 |
| d1_big_down7 | active_source_group=no_limit_source | 4312 | 29.5606 | -8.9993 | -9.7654 |
| d1_big_down7 | active_source_group=multi_limit_source | 3311 | 22.6983 | -8.8907 | -9.1196 |
| d1_big_down7 | active_source_group=single_limit_source | 2993 | 20.5183 | -8.7842 | -8.7789 |
| d1_big_down7 | active_source_group=crowded_active_source | 2523 | 17.2962 | -9.1579 | -9.9206 |
| d1_big_down7 | active_source_group=touched_but_not_closed_limit | 1448 | 9.9266 | -8.8329 | -9.048 |
| d1_big_down7 | pre_volume_pattern=mixed_volume | 3162 | 21.6768 | -8.8813 | -9.146 |
| d1_big_down7 | pre_volume_pattern=volume_contracting_three_day | 2939 | 20.1481 | -8.8794 | -9.1062 |
| d1_big_down7 | pre_volume_pattern=high_turnover_proxy_latest | 2917 | 19.9973 | -8.9764 | -9.417 |
| d1_big_down7 | pre_volume_pattern=multi_day_contraction | 2770 | 18.9895 | -9.0793 | -9.9145 |
| d1_big_down7 | pre_volume_pattern=volume_rising_three_day | 2310 | 15.836 | -8.8568 | -9.0345 |
| d1_big_down7 | pre_volume_pattern=sudden_volume_expansion | 452 | 3.0986 | -9.1408 | -9.9326 |
| d1_big_down7 | pre_volume_pattern=volume_history_unknown | 37 | 0.2537 | -8.764 | -8.7726 |
| d1_big_down7 | flag=active_source_compressed_high_close | 344 | 2.3583 | -8.9158 | -9.2882 |
| d1_big_down7 | flag=deep_low_close_rebound_absorption | 549 | 3.7636 | -8.6137 | -8.3946 |
| d1_big_down7 | flag=deep_low_first_sun_confirm | 63 | 0.4319 | -8.8521 | -8.9249 |
| d1_big_down7 | flag=extreme_volume_intraday_fade | 909 | 6.2316 | -9.097 | -9.772 |
| d1_big_down7 | flag=active_source_breakdown | 1442 | 9.8855 | -9.0262 | -9.4943 |
| d1_big_down7 | flag=hot_reacceleration_exhaustion | 199 | 1.3642 | -9.5481 | -9.9879 |
| d1_big_down7 | flag=weak_repair_high_close_no_source | 593 | 4.0653 | -9.3936 | -9.9578 |
| d1_limit_down | event_pattern_group=mixed | 2364 | 31.4028 | -9.9145 | -9.9915 |
| d1_limit_down | event_pattern_group=crowded_high_turnover_momentum | 1176 | 15.6217 | -9.929 | -9.9925 |
| d1_limit_down | event_pattern_group=multi_day_contraction_base | 1158 | 15.3826 | -9.9421 | -9.9926 |
| d1_limit_down | event_pattern_group=no_source_controlled_repair | 1010 | 13.4166 | -9.9525 | -9.9903 |
| d1_limit_down | event_pattern_group=extreme_volume_intraday_fade | 526 | 6.9872 | -9.9219 | -9.994 |
| d1_limit_down | event_pattern_group=active_source_breakdown | 496 | 6.5887 | -9.8984 | -9.9889 |
| d1_limit_down | event_pattern_group=low_position_no_source_low_close_repair | 264 | 3.5069 | -9.9542 | -9.9954 |
| d1_limit_down | event_pattern_group=deep_low_close_absorption | 203 | 2.6966 | -9.9187 | -9.994 |
| d1_limit_down | event_pattern_group=active_source_compressed_high_close | 169 | 2.245 | -9.9421 | -9.9944 |
| d1_limit_down | event_pattern_group=hot_reacceleration_exhaustion | 134 | 1.78 | -9.9595 | -9.9991 |
| d1_limit_down | event_pattern_group=deep_low_first_sun_confirm | 28 | 0.3719 | -9.9231 | -9.9867 |
| d1_limit_down | position_group=high_momentum | 2524 | 33.5282 | -9.9222 | -9.9924 |
| d1_limit_down | position_group=neutral | 2482 | 32.9702 | -9.9186 | -9.9884 |
| d1_limit_down | position_group=low_repair | 1505 | 19.992 | -9.9504 | -9.9942 |
| d1_limit_down | position_group=deep_oversold | 613 | 8.1429 | -9.922 | -9.9921 |
| d1_limit_down | position_group=extreme_hot | 404 | 5.3666 | -9.9574 | -10.0 |
| d1_limit_down | price_action_group=ordinary | 1523 | 20.2311 | -9.9314 | -9.995 |
| d1_limit_down | price_action_group=first_sun_or_strong_close | 1416 | 18.8098 | -9.9277 | -9.9916 |
| d1_limit_down | price_action_group=panic_low_close | 1195 | 15.8741 | -9.9082 | -9.9902 |
| d1_limit_down | price_action_group=compressed_mid_close | 865 | 11.4904 | -9.9505 | -9.9919 |
| d1_limit_down | price_action_group=low_close | 859 | 11.4107 | -9.9317 | -9.9932 |
| d1_limit_down | price_action_group=high_close | 582 | 7.7311 | -9.9378 | -9.9885 |
| d1_limit_down | price_action_group=balanced_mid_close | 551 | 7.3193 | -9.9254 | -9.9898 |
| d1_limit_down | price_action_group=intraday_fade | 537 | 7.1334 | -9.92 | -9.9952 |
| d1_limit_down | volume_turnover_group=contracted | 1239 | 16.4586 | -9.9526 | -9.9931 |
| d1_limit_down | volume_turnover_group=extreme_high_turnover_proxy | 1172 | 15.5685 | -9.9366 | -9.9925 |
| d1_limit_down | volume_turnover_group=normal | 976 | 12.9649 | -9.9229 | -9.9936 |
| d1_limit_down | volume_turnover_group=active_high_turnover_proxy | 750 | 9.9628 | -9.9177 | -9.9931 |
| d1_limit_down | volume_turnover_group=contracted_low_turnover_proxy | 715 | 9.4979 | -9.9575 | -9.9939 |
| d1_limit_down | volume_turnover_group=hot_high_turnover_proxy | 689 | 9.1525 | -9.9181 | -9.9933 |
| d1_limit_down | volume_turnover_group=active | 580 | 7.7046 | -9.9068 | -9.9908 |
| d1_limit_down | volume_turnover_group=normal_high_turnover_proxy | 479 | 6.3629 | -9.9166 | -9.989 |
| d1_limit_down | volume_turnover_group=normal_low_turnover_proxy | 299 | 3.9718 | -9.9136 | -9.9819 |
| d1_limit_down | volume_turnover_group=hot | 241 | 3.2014 | -9.9094 | -9.9921 |
| d1_limit_down | volume_turnover_group=extreme | 153 | 2.0324 | -9.8836 | -9.9898 |
| d1_limit_down | volume_turnover_group=contracted_high_turnover_proxy | 127 | 1.687 | -9.8678 | -9.9853 |
| d1_limit_down | volume_turnover_group=active_low_turnover_proxy | 77 | 1.0228 | -9.9297 | -9.9862 |
| d1_limit_down | volume_turnover_group=unknown_turnover | 13 | 0.1727 | -10.0898 | -9.9974 |
| d1_limit_down | volume_turnover_group=hot_low_turnover_proxy | 12 | 0.1594 | -9.9659 | -9.9888 |
| d1_limit_down | volume_turnover_group=extreme_low_turnover_proxy | 6 | 0.0797 | -9.9073 | -10.0021 |
| d1_limit_down | active_source_group=no_limit_source | 2373 | 31.5223 | -9.9437 | -9.9919 |
| d1_limit_down | active_source_group=multi_limit_source | 1624 | 21.5728 | -9.9151 | -9.9912 |
| d1_limit_down | active_source_group=crowded_active_source | 1516 | 20.1382 | -9.9359 | -9.9951 |
| d1_limit_down | active_source_group=single_limit_source | 1324 | 17.5877 | -9.9163 | -9.9912 |
| d1_limit_down | active_source_group=touched_but_not_closed_limit | 691 | 9.1791 | -9.9147 | -9.9913 |
| d1_limit_down | pre_volume_pattern=multi_day_contraction | 1623 | 21.5595 | -9.9526 | -9.9932 |
| d1_limit_down | pre_volume_pattern=mixed_volume | 1568 | 20.8289 | -9.9249 | -9.9918 |
| d1_limit_down | pre_volume_pattern=high_turnover_proxy_latest | 1520 | 20.1913 | -9.9303 | -9.993 |
| d1_limit_down | pre_volume_pattern=volume_contracting_three_day | 1432 | 19.0223 | -9.9105 | -9.9883 |
| d1_limit_down | pre_volume_pattern=volume_rising_three_day | 1090 | 14.4793 | -9.9198 | -9.9935 |
| d1_limit_down | pre_volume_pattern=sudden_volume_expansion | 281 | 3.7327 | -9.9171 | -9.9922 |
| d1_limit_down | pre_volume_pattern=volume_history_unknown | 14 | 0.186 | -10.0836 | -9.9987 |
| d1_limit_down | flag=active_source_compressed_high_close | 174 | 2.3114 | -9.9393 | -9.994 |
| d1_limit_down | flag=deep_low_close_rebound_absorption | 203 | 2.6966 | -9.9187 | -9.994 |
| d1_limit_down | flag=deep_low_first_sun_confirm | 28 | 0.3719 | -9.9231 | -9.9867 |
| d1_limit_down | flag=extreme_volume_intraday_fade | 526 | 6.9872 | -9.9219 | -9.994 |
| d1_limit_down | flag=active_source_breakdown | 783 | 10.4012 | -9.9096 | -9.9912 |
| d1_limit_down | flag=hot_reacceleration_exhaustion | 155 | 2.059 | -9.9633 | -9.9988 |
| d1_limit_down | flag=weak_repair_high_close_no_source | 432 | 5.7386 | -9.9578 | -9.9839 |

## Samples


### d1_limit_up_examples

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-15 | 2026-06-16 | 000564.SZSE | 供销大集 | 10.3448 | -0.6849 | deep_oversold | ordinary | contracted | multi_day_contraction | single_limit_source | 1.5181 | 1.4955 | 1.4453 | 1.62 | 0.6754 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.6741 | 0.6688 | 0.6485 |
| 2025-09-17 | 2025-09-18 | 600157.SSE | 永泰能源 | 10.3226 | -0.641 | neutral | balanced_mid_close | active | mixed_volume | no_limit_source | 4.0375 | 6.2755 | 5.3295 | 4.0 | 1.2486 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.2497 | 2.0888 | 1.9142 |
| 2025-04-09 | 2025-04-10 | 002269.SZSE | 美邦服饰 | 10.303 | 0.6098 | deep_oversold | high_close | active | volume_rising_three_day | no_limit_source | 6.8297 | 6.4619 | 4.0068 | 5.71 | 1.5689 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.5682 | 1.4999 | 0.8684 |
| 2025-06-06 | 2025-06-09 | 600881.SSE | 亚泰集团 | 10.2857 | 0.0 | neutral | compressed_mid_close | contracted | multi_day_contraction | multi_limit_source | 1.5153 | 2.6093 | 2.9472 | 1.43 | 0.3911 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.3914 | 0.6829 | 0.7846 |
| 2025-09-12 | 2025-09-15 | 002146.SZSE | 荣盛发展 | 10.2857 | 10.0629 | high_momentum | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 12.9897 | 6.1328 | 7.9728 | 9.09 | 1.6918 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 1.6951 | 0.8763 | 1.1786 |
| 2025-03-25 | 2025-03-26 | 002146.SZSE | 荣盛发展 | 10.274 | 0.0 | low_repair | compressed_mid_close | contracted | mixed_volume | no_limit_source | 1.632 | 4.0287 | 1.84 | 1.34 | 0.4944 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.4931 | 1.185 | 0.5027 |
| 2026-02-03 | 2026-02-04 | 000517.SZSE | 荣安地产 | 10.2703 | 2.2099 | neutral | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 1.1578 | 1.5426 | 1.2335 | 1.37 | 1.1322 | turnover_rate_lt_2 | turnover_ratio_0_90_1_15 | 1.1313 | 1.5588 | 1.2965 |
| 2025-02-25 | 2025-02-26 | 600076.SSE | 康欣新材 | 10.2439 | -0.9662 | neutral | ordinary | normal | mixed_volume | no_limit_source | 1.0361 | 1.1342 | 0.8481 | 1.52 | 1.1201 | turnover_rate_lt_2 | turnover_ratio_0_90_1_15 | 1.1206 | 1.2633 | 0.9404 |
| 2026-03-23 | 2026-03-24 | 002663.SZSE | 普邦股份 | 10.2439 | -6.8182 | low_repair | panic_low_close | normal | mixed_volume | no_limit_source | 4.719 | 4.8591 | 3.8688 | 4.15 | 1.2236 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.2224 | 1.2232 | 0.9713 |
| 2025-01-13 | 2025-01-14 | 000882.SZSE | 华联股份 | 10.2326 | -1.8265 | low_repair | compressed_mid_close | normal_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 13.5505 | 17.7151 | 29.2922 | 8.42 | 0.8014 | turnover_rate_6_12 | turnover_ratio_0_70_0_90 | 0.8011 | 0.9456 | 1.4504 |
| 2025-05-29 | 2025-05-30 | 002310.SZSE | 东方新能 | 10.2326 | 0.4673 | neutral | ordinary | extreme | sudden_volume_expansion | no_limit_source | 3.5924 | 0.6108 | 0.7309 | 4.82 | 5.1195 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 5.1324 | 0.9002 | 1.1025 |
| 2025-03-11 | 2025-03-12 | 002638.SZSE | 勤上股份 | 10.2326 | 2.381 | neutral | ordinary | hot | sudden_volume_expansion | no_limit_source | 2.2514 | 0.9808 | 1.169 | 4.12 | 2.1085 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 2.1085 | 0.9293 | 1.1192 |
| 2026-01-09 | 2026-01-12 | 601992.SSE | 金隅集团 | 10.2273 | -1.676 | neutral | ordinary | active | mixed_volume | no_limit_source | 1.5198 | 2.444 | 0.8642 | 1.49 | 1.6338 | turnover_rate_lt_2 | turnover_ratio_gt_1_15 | 1.6387 | 2.9159 | 1.0842 |
| 2025-01-06 | 2025-01-07 | 000981.SZSE | 山子高科 | 10.2222 | -7.0248 | low_repair | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 10.1496 | 0.5032 | 1.0976 | 17.22 | 1.302 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 1.3021 | 0.0596 | 0.1352 |
| 2026-01-13 | 2026-01-14 | 002310.SZSE | 东方新能 | 10.2222 | -1.3158 | low_repair | low_close | normal_low_turnover_proxy | volume_contracting_three_day | touched_but_not_closed_limit | 0.9496 | 1.4081 | 1.4256 | 1.23 | 0.7647 | turnover_rate_lt_2 | turnover_ratio_0_70_0_90 | 0.7627 | 1.1623 | 1.2183 |
| 2026-01-21 | 2026-01-22 | 601992.SSE | 金隅集团 | 10.2151 | -1.0638 | neutral | compressed_mid_close | normal | volume_contracting_three_day | multi_limit_source | 2.0258 | 2.7459 | 3.5353 | 1.9 | 0.8037 | turnover_rate_lt_2 | turnover_ratio_0_70_0_90 | 0.8055 | 1.1202 | 1.559 |

### d1_big_down_examples

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-03-31 | 2025-04-01 | 002271.SZSE | 东方雨虹 | -11.2821 | 0.1467 | neutral | balanced_mid_close | normal | volume_rising_three_day | no_limit_source | 1.85 | 1.325 | 1.3187 | 1.79 | 0.8842 | turnover_rate_lt_2 | turnover_ratio_0_70_0_90 | 0.8692 | 0.5787 | 0.5746 |
| 2026-05-27 | 2026-05-28 | 002032.SZSE | 苏 泊 尔 | -11.271 | 0.6639 | neutral | high_close | active_low_turnover_proxy | volume_rising_three_day | no_limit_source | 0.3606 | 0.2818 | 0.2421 | 0.31 | 1.2757 | turnover_rate_lt_2 | turnover_ratio_gt_1_15 | 1.2761 | 0.9803 | 0.8525 |
| 2025-06-04 | 2025-06-05 | 002345.SZSE | 潮宏基 | -11.2708 | 9.9937 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 11.5048 | 12.9595 | 12.6447 | 6.71 | 1.1318 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 1.1322 | 1.4054 | 1.4071 |
| 2026-05-25 | 2026-05-26 | 002612.SZSE | 朗姿股份 | -11.1976 | 1.2121 | neutral | high_close | normal | volume_contracting_three_day | no_limit_source | 2.5158 | 2.7299 | 3.2482 | 2.93 | 0.9806 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9796 | 1.0828 | 1.3312 |
| 2025-08-01 | 2025-08-04 | 001221.SZSE | 悍高集团 | -11.154 | -0.947 | neutral | intraday_fade | unknown_turnover | volume_history_unknown | no_limit_source | 7.6148 | 11.1519 | 11.9575 | 51.7 | None | turnover_rate_gt_12 | turnover_ratio_missing | None | None | None |
| 2025-06-20 | 2025-06-23 | 600295.SSE | 鄂尔多斯 | -10.9948 | 1.2725 | neutral | balanced_mid_close | hot_low_turnover_proxy | mixed_volume | no_limit_source | 0.4685 | 0.1843 | 0.2685 | 0.79 | 1.9128 | turnover_rate_lt_2 | turnover_ratio_gt_1_15 | 1.916 | 0.7765 | 1.145 |
| 2025-06-13 | 2025-06-16 | 600232.SSE | 金鹰股份 | -10.962 | 7.3229 | high_momentum | first_sun_or_strong_close | extreme_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 42.6752 | 46.1354 | 41.3785 | 28.88 | 5.4337 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 5.4332 | 8.2919 | 13.99 |
| 2025-04-17 | 2025-04-18 | 603120.SSE | 肯特催化 | -10.878 | -5.4397 | neutral | high_close | unknown_turnover | volume_history_unknown | no_limit_source | 13.1588 | 18.5279 | None | 65.88 | None | turnover_rate_gt_12 | turnover_ratio_missing | None | None | None |
| 2025-03-26 | 2025-03-27 | 001382.SZSE | 新亚电缆 | -10.6143 | 0.8627 | neutral | balanced_mid_close | unknown_turnover | volume_history_unknown | no_limit_source | 11.6769 | 14.9737 | 15.5627 | 47.0 | None | turnover_rate_gt_12 | turnover_ratio_missing | None | None | None |
| 2026-06-11 | 2026-06-12 | 600378.SSE | 昊华科技 | -10.5494 | 10.0034 | high_momentum | first_sun_or_strong_close | hot | mixed_volume | multi_limit_source | 7.1832 | 5.0409 | 7.6474 | 7.44 | 1.5985 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 1.5994 | 1.2985 | 2.3804 |
| 2026-06-24 | 2026-06-25 | 601083.SSE | 锦江航运 | -10.5448 | 0.0 | neutral | low_close | active_low_turnover_proxy | mixed_volume | no_limit_source | 0.8505 | 0.431 | 0.47 | 5.06 | 1.4869 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.487 | 0.7337 | 0.8127 |
| 2026-05-28 | 2026-05-29 | 002669.SZSE | 康达新材 | -10.5293 | 10.0188 | high_momentum | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 22.6271 | 27.7705 | 10.9848 | 16.62 | 2.2609 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 2.2602 | 3.4784 | 1.5222 |
| 2025-09-08 | 2025-09-09 | 603508.SSE | 思维列控 | -10.4974 | 1.648 | neutral | balanced_mid_close | active | volume_rising_three_day | touched_but_not_closed_limit | 4.7778 | 3.6152 | 3.7634 | 2.86 | 1.1619 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.1621 | 0.8613 | 0.8398 |
| 2026-05-25 | 2026-05-26 | 002457.SZSE | 青龙管业 | -10.4906 | -1.1194 | high_momentum | low_close | hot_high_turnover_proxy | volume_contracting_three_day | no_limit_source | 13.8704 | 13.3132 | 14.6729 | 14.51 | 1.635 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 1.6349 | 1.6828 | 1.9844 |
| 2025-07-22 | 2025-07-23 | 600444.SSE | 国机通用 | -10.4749 | 2.432 | high_momentum | intraday_fade | extreme_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 65.7767 | 11.7136 | 15.3336 | 37.06 | 10.958 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 10.961 | 2.2362 | 3.7987 |
| 2025-06-12 | 2025-06-13 | 002088.SZSE | 鲁阳节能 | -10.4305 | 0.0 | neutral | balanced_mid_close | hot | mixed_volume | no_limit_source | 2.2747 | 1.3835 | 1.8971 | 1.41 | 2.0781 | turnover_rate_lt_2 | turnover_ratio_gt_1_15 | 2.0759 | 1.2705 | 1.7628 |

### active_source_compressed_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-01-22 | 2026-01-23 | 002506.SZSE | 协鑫集成 | 10.1754 | 3.2609 | neutral | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 5.6959 | 3.4372 | 7.0008 | 4.99 | 0.9455 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9457 | 0.5887 | 1.2097 |
| 2026-02-25 | 2026-02-26 | 002470.SZSE | 金正大 | 10.1562 | 9.8712 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | multi_limit_source | 4.0866 | 12.0798 | 6.5652 | 2.98 | 0.6566 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6565 | 2.3227 | 1.3948 |
| 2025-04-01 | 2025-04-02 | 603188.SSE | 亚邦股份 | 10.1333 | 9.9707 | neutral | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 1.989 | 2.8602 | 4.4888 | 2.03 | 0.7808 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.779 | 1.2383 | 1.962 |
| 2025-02-05 | 2025-02-06 | 002526.SZSE | 山东矿机 | 10.1333 | 5.042 | neutral | first_sun_or_strong_close | normal_high_turnover_proxy | multi_day_contraction | single_limit_source | 11.8854 | 10.3884 | 11.0297 | 8.01 | 0.7345 | turnover_rate_6_12 | turnover_ratio_0_70_0_90 | 0.7347 | 0.6537 | 0.6767 |
| 2025-04-14 | 2025-04-15 | 002793.SZSE | 罗欣药业 | 10.1299 | 4.6196 | neutral | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 1.4137 | 0.9161 | 1.4211 | 1.7 | 0.9038 | turnover_rate_lt_2 | turnover_ratio_0_90_1_15 | 0.9034 | 0.5921 | 0.8595 |
| 2025-04-24 | 2025-04-25 | 600744.SSE | 华银电力 | 10.1299 | 10.0 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 2.714 | 2.291 | 3.3297 | 3.8 | 0.9097 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9094 | 0.8376 | 1.2109 |
| 2025-09-29 | 2025-09-30 | 000981.SZSE | 山子高科 | 10.1299 | 10.0 | high_momentum | first_sun_or_strong_close | contracted_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 13.1038 | 23.2881 | 27.8284 | 9.24 | 0.5161 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.5161 | 0.9925 | 1.1391 |
| 2025-04-24 | 2025-04-25 | 600828.SSE | 茂业商业 | 10.1266 | 10.0279 | high_momentum | first_sun_or_strong_close | contracted | volume_contracting_three_day | multi_limit_source | 1.1629 | 2.4043 | 2.8653 | 1.04 | 0.5513 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.5523 | 1.2817 | 1.5524 |
| 2025-05-16 | 2025-05-19 | 002471.SZSE | 中超控股 | 10.1266 | 10.0279 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 8.88 | 16.0201 | 22.6857 | 12.57 | 0.9234 | turnover_rate_gt_12 | turnover_ratio_0_90_1_15 | 0.9233 | 1.8976 | 2.6968 |
| 2026-03-24 | 2026-03-25 | 600433.SSE | 冠豪高新 | 10.119 | 4.3478 | low_repair | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 2.6667 | 4.0319 | 4.4141 | 2.45 | 0.7861 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.7873 | 1.215 | 1.2703 |
| 2026-01-05 | 2026-01-06 | 600936.SSE | 北投科技 | 10.1149 | 3.0806 | high_momentum | first_sun_or_strong_close | contracted | multi_day_contraction | crowded_active_source | 3.1355 | 3.4375 | 3.2907 | 3.24 | 0.6087 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6089 | 0.6873 | 0.6715 |
| 2025-08-29 | 2025-09-01 | 601929.SSE | 吉视传媒 | 10.1099 | 9.9034 | extreme_hot | first_sun_or_strong_close | normal_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 26.4195 | 52.6712 | 56.2789 | 12.91 | 0.6389 | turnover_rate_gt_12 | turnover_ratio_lt_0_70 | 0.6387 | 1.4488 | 1.6784 |
| 2025-09-25 | 2025-09-26 | 601218.SSE | 吉鑫科技 | 10.0971 | 10.0427 | neutral | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 6.8274 | 4.6474 | 7.2429 | 5.38 | 0.6329 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6324 | 0.464 | 0.7271 |
| 2025-11-04 | 2025-11-05 | 600815.SSE | 厦工股份 | 10.089 | 10.1307 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | multi_limit_source | 4.7843 | 5.9654 | 6.8187 | 3.5 | 0.7487 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.7492 | 1.0459 | 1.2706 |
| 2025-05-21 | 2025-05-22 | 600149.SSE | 廊坊发展 | 10.0885 | 9.9222 | high_momentum | first_sun_or_strong_close | active | mixed_volume | single_limit_source | 6.9843 | 12.8831 | 7.1614 | 5.61 | 0.9961 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9965 | 2.1408 | 1.2892 |
| 2025-01-09 | 2025-01-10 | 600601.SSE | 方正科技 | 10.084 | 9.9307 | neutral | first_sun_or_strong_close | normal | volume_contracting_three_day | multi_limit_source | 1.2721 | 2.3072 | 2.4578 | 3.34 | 0.6617 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6609 | 1.355 | 1.4838 |

### active_source_compressed_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-10 | 2026-07-13 | 603211.SSE | XD晋拓股 | -10.1901 | 9.9884 | neutral | first_sun_or_strong_close | normal | volume_contracting_three_day | crowded_active_source | 4.7238 | 4.8518 | 7.5381 | 4.42 | 0.8857 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.8852 | 0.9486 | 1.4493 |
| 2026-05-14 | 2026-05-15 | 001267.SZSE | 汇绿生态 | -10.0745 | 9.9937 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 12.7781 | 8.1534 | 10.5633 | 10.32 | 0.9961 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 0.9972 | 0.6549 | 0.8349 |
| 2025-09-30 | 2025-10-09 | 002723.SZSE | 小崧股份 | -10.0406 | 4.0084 | neutral | first_sun_or_strong_close | normal_high_turnover_proxy | volume_rising_three_day | single_limit_source | 8.7734 | 6.6415 | 4.1902 | 7.64 | 1.0227 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 1.0228 | 0.7889 | 0.5027 |
| 2026-03-03 | 2026-03-04 | 603616.SSE | 韩建河山 | -10.0367 | 9.9596 | high_momentum | first_sun_or_strong_close | contracted_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 9.9772 | 12.1524 | 19.9579 | 6.45 | 0.4881 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.4882 | 0.6344 | 1.0292 |
| 2026-07-10 | 2026-07-13 | 600293.SSE | 三峡新材 | -10.0358 | 9.8425 | deep_oversold | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 4.3016 | 3.3885 | 2.8321 | 3.88 | 0.4795 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.4795 | 0.3941 | 0.301 |
| 2025-03-27 | 2025-03-28 | 600610.SSE | 中毅达 | -10.0343 | 10.0 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | crowded_active_source | 7.3757 | 17.1868 | 10.1874 | 5.91 | 0.608 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6078 | 1.653 | 1.1387 |
| 2025-09-01 | 2025-09-02 | 000676.SZSE | 智度股份 | -10.0313 | 10.0 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | volume_contracting_three_day | single_limit_source | 15.0467 | 22.3937 | 25.1925 | 6.12 | 0.9397 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 0.9397 | 1.6212 | 1.9701 |
| 2026-05-28 | 2026-05-29 | 002918.SZSE | 蒙娜丽莎 | -10.0267 | 10.0 | high_momentum | first_sun_or_strong_close | contracted | volume_contracting_three_day | crowded_active_source | 5.8709 | 9.6764 | 13.9759 | 6.67 | 0.5323 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.5322 | 0.9913 | 1.461 |
| 2025-01-02 | 2025-01-03 | 603777.SSE | 来伊份 | -10.0236 | 9.987 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | crowded_active_source | 6.248 | 22.4447 | 19.5102 | 5.36 | 0.6174 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6173 | 2.781 | 2.7535 |
| 2025-03-12 | 2025-03-13 | 603166.SSE | 福达股份 | -10.0213 | 10.0078 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 8.2629 | 9.2705 | 13.2461 | 6.26 | 0.77 | turnover_rate_6_12 | turnover_ratio_0_70_0_90 | 0.7706 | 0.9222 | 1.2718 |
| 2026-07-01 | 2026-07-02 | 605006.SSE | 山东玻纤 | -10.0183 | 3.651 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 14.8032 | 16.9704 | 3.7063 | 11.04 | 0.9381 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 0.962 | 1.1091 | 0.2133 |
| 2026-07-06 | 2026-07-07 | 002403.SZSE | 爱仕达 | -10.017 | 9.9907 | high_momentum | first_sun_or_strong_close | active | volume_contracting_three_day | single_limit_source | 2.7573 | 4.2264 | 4.6773 | 2.55 | 1.0018 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 1.0032 | 1.7896 | 2.2532 |
| 2026-05-19 | 2026-05-20 | 603178.SSE | 圣龙股份 | -10.0168 | 10.0 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 15.4862 | 14.8858 | 22.3629 | 10.15 | 0.826 | turnover_rate_6_12 | turnover_ratio_0_70_0_90 | 0.8257 | 0.8929 | 1.3947 |
| 2026-07-10 | 2026-07-13 | 002989.SZSE | 中天精装 | -10.0128 | 9.993 | low_repair | first_sun_or_strong_close | contracted | volume_contracting_three_day | crowded_active_source | 3.6912 | 5.9638 | 6.5487 | 3.46 | 0.5552 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.5855 | 1.0855 | 1.2231 |
| 2026-01-12 | 2026-01-13 | 600879.SSE | 航天电子 | -10.0127 | 10.0035 | extreme_hot | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 17.8331 | 25.5182 | 14.0484 | 12.24 | 0.6952 | turnover_rate_gt_12 | turnover_ratio_lt_0_70 | 0.6951 | 1.1308 | 0.6977 |
| 2025-06-03 | 2025-06-04 | 002633.SZSE | 申科股份 | -10.0118 | 9.9741 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 3.4675 | 3.9776 | 5.9161 | 2.92 | 0.6588 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6593 | 0.8379 | 1.4148 |

### deep_low_close_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-01-10 | 2025-01-13 | 000631.SZSE | 顺发恒能 | 10.1449 | -2.4735 | deep_oversold | low_close | contracted_low_turnover_proxy | multi_day_contraction | no_limit_source | 0.6095 | 0.48 | 0.5026 | 0.58 | 0.6532 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.6494 | 0.4742 | 0.4864 |
| 2026-06-12 | 2026-06-15 | 000980.SZSE | 众泰汽车 | 10.1382 | -4.8246 | deep_oversold | intraday_fade | normal | mixed_volume | single_limit_source | 5.5453 | 2.7653 | 5.5121 | 3.94 | 1.1527 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.1519 | 0.5533 | 1.0677 |
| 2026-06-26 | 2026-06-29 | 002638.SZSE | 勤上股份 | 10.137 | -4.9479 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.981 | 4.1769 | 2.8743 | 3.15 | 0.9946 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9954 | 1.2691 | 0.87 |
| 2025-01-13 | 2025-01-14 | 600545.SSE | 卓郎智能 | 10.1322 | -9.9206 | deep_oversold | panic_low_close | contracted | mixed_volume | single_limit_source | 2.6185 | 4.3812 | 2.6173 | 5.52 | 0.7639 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.7638 | 1.1152 | 0.6381 |
| 2025-04-24 | 2025-04-25 | 002298.SZSE | 中电鑫龙 | 10.1124 | -3.6797 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.2565 | 3.172 | 1.5489 | 3.79 | 1.0389 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 1.0383 | 1.4546 | 0.6503 |
| 2025-01-03 | 2025-01-06 | 002480.SZSE | 新筑股份 | 10.1075 | -5.6795 | deep_oversold | panic_low_close | contracted | multi_day_contraction | single_limit_source | 1.8033 | 1.7712 | 1.1898 | 1.89 | 0.5351 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.5359 | 0.4843 | 0.3042 |
| 2026-07-07 | 2026-07-08 | 002467.SZSE | 二六三 | 10.0939 | -3.6199 | deep_oversold | low_close | normal | multi_day_contraction | no_limit_source | 2.4698 | 2.4242 | 2.2311 | 2.55 | 0.8232 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.8218 | 0.7679 | 0.6757 |
| 2025-04-10 | 2025-04-11 | 000670.SZSE | 盈方微 | 10.0885 | 1.6187 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.7518 | 3.8284 | 3.2078 | 3.66 | 1.0691 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 1.0691 | 1.6302 | 1.351 |
| 2026-04-03 | 2026-04-07 | 600227.SSE | 赤天化 | 10.0865 | -8.4433 | deep_oversold | panic_low_close | contracted_high_turnover_proxy | multi_day_contraction | crowded_active_source | 15.8259 | 19.0581 | 20.3172 | 14.47 | 0.556 | turnover_rate_gt_12 | turnover_ratio_lt_0_70 | 0.5558 | 0.6122 | 0.6464 |
| 2025-04-10 | 2025-04-11 | 002453.SZSE | 华软科技 | 10.084 | 0.0 | deep_oversold | low_close | normal | volume_contracting_three_day | single_limit_source | 2.8062 | 3.6959 | 4.5189 | 3.03 | 0.9912 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9923 | 1.391 | 1.7133 |
| 2026-05-27 | 2026-05-28 | 002263.SZSE | 大东南 | 10.084 | -4.0323 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 5.3832 | 4.6468 | 4.7155 | 4.04 | 0.5682 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.5676 | 0.4239 | 0.3877 |
| 2025-12-18 | 2025-12-19 | 002596.SZSE | 海南瑞泽 | 10.0823 | -6.8966 | deep_oversold | panic_low_close | contracted_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 24.6797 | 22.2138 | 34.5226 | 13.42 | 0.7905 | turnover_rate_gt_12 | turnover_ratio_0_70_0_90 | 0.7905 | 0.6622 | 0.9401 |
| 2025-01-03 | 2025-01-06 | 000702.SZSE | 正虹科技 | 10.0813 | -7.6577 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 3.459 | 3.1917 | 3.3349 | 3.55 | 0.8737 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.8737 | 0.756 | 0.7771 |
| 2025-10-24 | 2025-10-27 | 600376.SSE | 首开股份 | 10.08 | -3.2508 | deep_oversold | low_close | contracted_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 13.7134 | 14.8734 | 19.6309 | 7.16 | 0.6374 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.6373 | 0.6657 | 0.8635 |
| 2025-01-03 | 2025-01-06 | 600173.SSE | 卧龙新能 | 10.0796 | -3.5806 | deep_oversold | low_close | normal_low_turnover_proxy | mixed_volume | no_limit_source | 0.7364 | 0.8286 | 0.7195 | 1.07 | 0.8118 | turnover_rate_lt_2 | turnover_ratio_0_70_0_90 | 0.8135 | 0.8933 | 0.7573 |
| 2025-01-06 | 2025-01-07 | 003037.SZSE | 三和管桩 | 10.0787 | -5.9259 | deep_oversold | panic_low_close | contracted | multi_day_contraction | multi_limit_source | 2.8667 | 4.3388 | 4.2022 | 7.37 | 0.5417 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.5419 | 0.7847 | 0.7265 |

### deep_low_close_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-01 | 2026-06-02 | 605056.SSE | 咸亨国际 | -10.4245 | -2.7077 | deep_oversold | low_close | contracted | multi_day_contraction | touched_but_not_closed_limit | 2.4034 | 2.6928 | 2.2038 | 1.62 | 0.6418 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.6411 | 0.6959 | 0.5265 |
| 2025-01-23 | 2025-01-24 | 600892.SSE | 大晟文化 | -10.119 | 0.0 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 2.4157 | 2.7649 | 2.6792 | 2.28 | 0.6482 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.6493 | 0.6956 | 0.6378 |
| 2026-05-20 | 2026-05-21 | 600208.SSE | 衢州发展 | -10.1124 | -10.101 | deep_oversold | panic_low_close | normal | mixed_volume | crowded_active_source | 5.1643 | 0.1937 | 0.2908 | 4.07 | 1.1293 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 1.1302 | 0.0379 | 0.0509 |
| 2025-04-03 | 2025-04-07 | 002520.SZSE | 日发精机 | -10.0629 | -4.5045 | deep_oversold | low_close | contracted_high_turnover_proxy | volume_contracting_three_day | touched_but_not_closed_limit | 8.3447 | 9.7237 | 13.9895 | 8.2 | 0.62 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.6197 | 0.6904 | 0.9599 |
| 2025-01-22 | 2025-01-23 | 002848.SZSE | 高斯贝尔 | -10.043 | -2.5175 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.97 | 3.555 | 2.9756 | 5.71 | 0.9047 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.9041 | 0.9407 | 0.7669 |
| 2026-06-05 | 2026-06-08 | 001330.SZSE | 博纳影业 | -10.0386 | -5.3593 | deep_oversold | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 11.4565 | 10.1651 | 13.0992 | 8.31 | 0.918 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 0.9175 | 0.7401 | 0.9418 |
| 2025-04-07 | 2025-04-08 | 002973.SZSE | 侨银股份 | -10.0375 | -9.9662 | deep_oversold | panic_low_close | contracted_low_turnover_proxy | multi_day_contraction | no_limit_source | 0.7467 | 0.8228 | 0.6608 | 1.3 | 0.6082 | turnover_rate_lt_2 | turnover_ratio_lt_0_70 | 0.6626 | 0.621 | 0.4745 |
| 2025-04-03 | 2025-04-07 | 605069.SSE | 正和生态 | -10.0338 | -4.315 | deep_oversold | low_close | contracted | volume_contracting_three_day | crowded_active_source | 6.0324 | 7.9703 | 10.7065 | 19.68 | 0.6821 | turnover_rate_gt_12 | turnover_ratio_lt_0_70 | 0.6822 | 0.9168 | 1.2822 |
| 2025-04-03 | 2025-04-07 | 002184.SZSE | 海得控制 | -10.0324 | -1.3567 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 5.5191 | 7.8702 | 7.419 | 5.75 | 0.5634 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.5632 | 0.8073 | 0.7808 |
| 2026-07-10 | 2026-07-13 | 002068.SZSE | 黑猫股份 | -10.0273 | -5.1038 | deep_oversold | panic_low_close | contracted | multi_day_contraction | crowded_active_source | 5.3859 | 7.5017 | 6.2725 | 4.69 | 0.5707 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.5705 | 0.816 | 0.6522 |
| 2025-03-24 | 2025-03-25 | 600126.SSE | 杭钢股份 | -10.0269 | -6.5272 | deep_oversold | panic_low_close | contracted_high_turnover_proxy | multi_day_contraction | multi_limit_source | 12.9855 | 20.0305 | 16.0828 | 6.42 | 0.5458 | turnover_rate_6_12 | turnover_ratio_lt_0_70 | 0.5454 | 0.8122 | 0.5968 |
| 2026-03-20 | 2026-03-23 | 600331.SSE | 宏达股份 | -10.026 | -4.5963 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 4.5488 | 5.5519 | 3.1039 | 3.71 | 0.9261 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 0.926 | 1.121 | 0.5951 |
| 2026-07-10 | 2026-07-13 | 002388.SZSE | 新亚制程 | -10.0223 | 0.4474 | deep_oversold | low_close | normal | volume_contracting_three_day | no_limit_source | 7.3712 | 7.3548 | 8.0222 | 6.57 | 0.9244 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 0.9237 | 0.9442 | 0.98 |
| 2025-04-03 | 2025-04-07 | 000887.SZSE | 中鼎股份 | -10.0218 | -3.3175 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 3.2276 | 3.0875 | 3.7062 | 3.45 | 0.5502 | turnover_rate_2_6 | turnover_ratio_lt_0_70 | 0.5497 | 0.4975 | 0.5809 |
| 2025-04-03 | 2025-04-07 | 605060.SSE | 联德股份 | -10.0214 | -7.7151 | deep_oversold | panic_low_close | active_low_turnover_proxy | mixed_volume | touched_but_not_closed_limit | 0.8456 | 0.2063 | 0.2202 | 1.98 | 1.6459 | turnover_rate_lt_2 | turnover_ratio_gt_1_15 | 1.6448 | 0.3591 | 0.3733 |
| 2025-04-03 | 2025-04-07 | 603328.SSE | 依顿电子 | -10.0211 | -5.859 | deep_oversold | panic_low_close | active | mixed_volume | no_limit_source | 2.3023 | 0.7673 | 1.0242 | 2.38 | 1.4691 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.4716 | 0.4612 | 0.6125 |

### deep_low_first_sun_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-04-09 | 2025-04-10 | 002494.SZSE | 华斯股份 | 10.1333 | 2.459 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 3.4496 | 3.6309 | 2.0041 | 5.65 | 1.279 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.2788 | 1.3615 | 0.7125 |
| 2025-12-19 | 2025-12-22 | 002596.SZSE | 海南瑞泽 | 10.0935 | 10.0823 | low_repair | first_sun_or_strong_close | normal_high_turnover_proxy | volume_rising_three_day | crowded_active_source | 35.3669 | 24.6797 | 22.2138 | 18.99 | 1.1068 | turnover_rate_gt_12 | turnover_ratio_0_90_1_15 | 1.1068 | 0.7905 | 0.6622 |
| 2025-04-08 | 2025-04-09 | 002133.SZSE | 广宇集团 | 10.084 | 2.5862 | low_repair | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.2704 | 2.5861 | 1.3266 | 2.4 | 1.2229 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.2224 | 1.3945 | 0.6401 |
| 2025-04-09 | 2025-04-10 | 000626.SZSE | 远大控股 | 10.0806 | 4.8626 | low_repair | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 1.342 | 1.1684 | 0.7057 | 1.8 | 1.8663 | turnover_rate_lt_2 | turnover_ratio_gt_1_15 | 1.8637 | 1.677 | 0.9669 |
| 2025-04-09 | 2025-04-10 | 603500.SSE | 祥和实业 | 10.0719 | 2.6588 | deep_oversold | first_sun_or_strong_close | normal | volume_rising_three_day | touched_but_not_closed_limit | 2.211 | 2.1424 | 1.9378 | 3.14 | 1.164 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.1626 | 1.0939 | 0.9747 |
| 2025-02-27 | 2025-02-28 | 600693.SSE | 东百集团 | 10.0649 | 10.0 | low_repair | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 10.825 | 3.9313 | 5.3445 | 14.14 | 1.5827 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 1.5826 | 0.5607 | 0.715 |
| 2025-01-14 | 2025-01-15 | 600358.SSE | 国旅联合 | 10.0559 | 10.1538 | deep_oversold | first_sun_or_strong_close | normal | multi_day_contraction | no_limit_source | 2.0411 | 0.8704 | 1.1097 | 3.05 | 0.8379 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.8385 | 0.3647 | 0.4201 |
| 2025-04-10 | 2025-04-11 | 600207.SSE | 安彩高科 | 10.0515 | 4.0214 | low_repair | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 1.3549 | 1.4015 | 1.3871 | 1.49 | 1.0167 | turnover_rate_lt_2 | turnover_ratio_0_90_1_15 | 1.0137 | 1.1281 | 1.0517 |
| 2025-12-19 | 2025-12-22 | 000955.SZSE | 欣龙控股 | 10.0494 | 5.5652 | deep_oversold | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 14.2051 | 7.9827 | 10.2682 | 9.91 | 0.9416 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 0.9417 | 0.4987 | 0.5892 |
| 2026-01-22 | 2026-01-23 | 603878.SSE | 武进不锈 | 10.049 | 2.5126 | low_repair | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 6.6321 | 3.779 | 4.6387 | 3.88 | 0.8343 | turnover_rate_2_6 | turnover_ratio_0_70_0_90 | 0.8333 | 0.4843 | 0.5912 |
| 2026-07-01 | 2026-07-02 | 600156.SSE | 华升股份 | 10.0462 | 4.0865 | low_repair | first_sun_or_strong_close | normal | volume_rising_three_day | no_limit_source | 5.5148 | 5.2788 | 3.7117 | 5.01 | 1.0693 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 1.0702 | 1.04 | 0.6935 |
| 2026-07-10 | 2026-07-13 | 600629.SSE | 华建集团 | 10.0392 | 10.0086 | low_repair | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 2.1046 | 1.0353 | 1.2911 | 2.39 | 1.2141 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.3271 | 0.7015 | 0.8705 |
| 2025-04-09 | 2025-04-10 | 002404.SZSE | 嘉欣丝绸 | 10.0365 | 6.2016 | deep_oversold | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 3.304 | 2.6295 | 1.7883 | 4.34 | 1.6027 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.6008 | 1.3321 | 0.8618 |
| 2025-04-09 | 2025-04-10 | 002803.SZSE | 吉宏股份 | 10.0355 | 4.0665 | deep_oversold | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 1.136 | 1.2091 | 0.74 | 3.66 | 1.5031 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.5124 | 1.6327 | 0.9331 |
| 2026-07-01 | 2026-07-02 | 000908.SZSE | 石药景峰 | 10.0352 | 2.8986 | deep_oversold | first_sun_or_strong_close | active | mixed_volume | single_limit_source | 1.3263 | 1.1186 | 1.6134 | 3.26 | 1.2825 | turnover_rate_2_6 | turnover_ratio_gt_1_15 | 1.2808 | 1.1245 | 1.7546 |
| 2026-07-09 | 2026-07-10 | 600410.SSE | 华胜天成 | 10.0332 | 2.5903 | low_repair | first_sun_or_strong_close | normal | volume_rising_three_day | touched_but_not_closed_limit | 6.0789 | 5.6093 | 3.8211 | 6.46 | 1.0076 | turnover_rate_6_12 | turnover_ratio_0_90_1_15 | 1.0071 | 0.928 | 0.6371 |

### risk_flag_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | turnover_rate | turnover_rate_ratio_20d | turnover_rate_group | turnover_rate_ratio_group | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-07-22 | 2025-07-23 | 600444.SSE | 国机通用 | -10.4749 | 2.432 | high_momentum | intraday_fade | extreme_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 65.7767 | 11.7136 | 15.3336 | 37.06 | 10.958 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 10.961 | 2.2362 | 3.7987 |
| 2025-07-03 | 2025-07-04 | 605151.SSE | 西上海 | -10.322 | -10.0128 | high_momentum | panic_low_close | extreme_high_turnover_proxy | volume_rising_three_day | crowded_active_source | 14.4757 | 1.3879 | 1.1228 | 11.97 | 3.4328 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 3.4322 | 0.2893 | 0.241 |
| 2025-10-30 | 2025-10-31 | 002269.SZSE | 美邦服饰 | -10.1626 | 2.5 | neutral | intraday_fade | extreme_high_turnover_proxy | volume_rising_three_day | no_limit_source | 46.8818 | 12.3652 | 6.7685 | 24.42 | 4.885 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 4.8852 | 1.3468 | 0.687 |
| 2025-10-30 | 2025-10-31 | 000620.SZSE | 盈新发展 | -10.1449 | -9.2105 | high_momentum | panic_low_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 13.5901 | 17.5811 | 0.8621 | 19.22 | 6.0717 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 6.0721 | 10.6495 | 0.5135 |
| 2026-06-01 | 2026-06-02 | 001259.SZSE | 利仁科技 | -10.1354 | -10.0024 | extreme_hot | panic_low_close | active_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 10.1835 | 9.4353 | 8.8836 | 10.99 | 1.4047 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 1.4047 | 1.3515 | 1.417 |
| 2025-02-28 | 2025-03-03 | 600076.SSE | 康欣新材 | -10.1215 | -0.8032 | high_momentum | intraday_fade | extreme_high_turnover_proxy | volume_rising_three_day | multi_limit_source | 14.2778 | 3.4146 | 1.1282 | 16.47 | 10.5712 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 10.5735 | 3.0096 | 1.1242 |
| 2026-03-19 | 2026-03-20 | 002470.SZSE | 金正大 | -10.119 | -6.4067 | high_momentum | panic_low_close | active_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 40.2489 | 55.5703 | 50.8924 | 21.05 | 1.2243 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 1.2243 | 1.7938 | 1.8937 |
| 2026-05-20 | 2026-05-21 | 600208.SSE | 衢州发展 | -10.1124 | -10.101 | deep_oversold | panic_low_close | normal | mixed_volume | crowded_active_source | 5.1643 | 0.1937 | 0.2908 | 4.07 | 1.1293 | turnover_rate_2_6 | turnover_ratio_0_90_1_15 | 1.1302 | 0.0379 | 0.0509 |
| 2025-12-11 | 2025-12-12 | 002133.SZSE | 广宇集团 | -10.1093 | -2.9178 | neutral | intraday_fade | extreme_high_turnover_proxy | volume_rising_three_day | single_limit_source | 37.3513 | 6.1174 | 3.2505 | 23.03 | 9.8167 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 9.8137 | 1.8096 | 1.0643 |
| 2025-01-09 | 2025-01-10 | 002397.SZSE | 梦洁股份 | -10.1064 | -6.4677 | high_momentum | intraday_fade | extreme_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 22.7185 | 31.9262 | 18.5528 | 27.0 | 3.2409 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 3.2414 | 5.5059 | 3.6838 |
| 2025-01-03 | 2025-01-06 | 002798.SZSE | 帝欧水华 | -10.1036 | -10.0233 | deep_oversold | panic_low_close | hot | mixed_volume | single_limit_source | 5.3628 | 8.9935 | 2.7478 | 11.88 | 2.0938 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 2.1449 | 3.529 | 1.1425 |
| 2026-06-09 | 2026-06-10 | 600255.SSE | 鑫科材料 | -10.0897 | -3.2538 | high_momentum | low_close | hot_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 34.9904 | 45.0075 | 53.2846 | 21.69 | 2.5985 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 2.598 | 3.859 | 5.7488 |
| 2025-01-06 | 2025-01-07 | 600530.SSE | 交大昂立 | -10.076 | -9.9315 | high_momentum | panic_low_close | hot_high_turnover_proxy | high_turnover_proxy_latest | crowded_active_source | 9.7938 | 17.4725 | 2.8713 | 9.44 | 2.0948 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 2.0956 | 4.1048 | 0.7134 |
| 2025-04-25 | 2025-04-28 | 600794.SSE | 保税科技 | -10.076 | -9.9315 | high_momentum | panic_low_close | extreme_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 38.5201 | 57.8916 | 67.2625 | 20.6 | 3.0772 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 3.068 | 5.621 | 9.1517 |
| 2025-03-24 | 2025-03-25 | 000890.SZSE | 法尔胜 | -10.0756 | -5.0239 | neutral | intraday_fade | extreme_high_turnover_proxy | volume_rising_three_day | single_limit_source | 12.0141 | 8.0725 | 2.8693 | 20.53 | 5.6909 | turnover_rate_gt_12 | turnover_ratio_gt_1_15 | 5.6892 | 4.3614 | 1.6529 |
| 2026-07-06 | 2026-07-07 | 600376.SSE | 首开股份 | -10.0756 | 4.1995 | high_momentum | intraday_fade | extreme_high_turnover_proxy | sudden_volume_expansion | single_limit_source | 13.2711 | 1.6439 | 3.8793 | 11.08 | 4.2879 | turnover_rate_6_12 | turnover_ratio_gt_1_15 | 4.2892 | 0.5308 | 1.3317 |

## Notes

- turnover_rate 读取 stock_daily_bars 的 D 日历史换手率；只有该字段缺失时，旧的 turnover_proxy 分组仍使用 D 日成交额 / 当前 market_cap 代理。
- volume_ratio/amount_ratio 使用 D 日成交量或成交额相对前 20 日均值，前 20 日均值不包含 D 日。
- 所有正向/负向 flag 都只使用 D 日收盘前可见信息；D+1 只作为标签。
- 主样本仅包含沪深主板，并剔除 ST/退市、非连续 D+1、新股/除权或数据异常导致的超涨跌幅样本。
