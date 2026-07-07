# D+1 Event Feature Research Set

## Dataset

- rows: `422477`
- symbols: `4997`
- days: `85`
- range: `2026-03-02` .. `2026-07-03`

## Baseline

- n: `422477`
- win_rate: `45.2934`
- avg_return: `-0.0872`
- median_return: `-0.2666`
- d1_limit_rate: `1.517`
- d1_big_up7_rate: `3.4418`
- d1_big_down7_rate: `1.9641`

## Feature Flags

| flag | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_up7_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| hot_reacceleration_exhaustion | 544 | 56.4338 | 1.2199 | 0.7638 | 12.6838 | 23.1618 | 10.8456 |
| active_source_compressed_high_close | 3265 | 51.3936 | 0.5661 | 0.1817 | 8.2389 | 11.9449 | 5.8499 |
| deep_low_close_rebound_absorption | 20530 | 56.3614 | 0.5366 | 0.5173 | 1.359 | 3.6191 | 1.6512 |
| deep_low_first_sun_confirm | 4711 | 49.6285 | 0.1257 | 0.0 | 1.7194 | 3.6935 | 1.2099 |
| active_source_breakdown | 6758 | 43.1933 | -0.2836 | -0.6969 | 5.6378 | 8.7008 | 7.1323 |
| extreme_volume_intraday_fade | 3016 | 42.6061 | -0.3083 | -0.7834 | 4.8408 | 9.317 | 8.4218 |
| weak_repair_high_close_no_source | 31508 | 38.4569 | -0.3648 | -0.4902 | 0.4729 | 1.2092 | 0.5998 |

## Stacked Feature Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_up7_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| deep_oversold::panic_low_close::active::no_limit_source | 1169 | 77.2455 | 2.56 | 3.2984 | 0.5133 | 4.9615 | 1.3687 |
| deep_oversold::panic_low_close::normal::no_limit_source | 2069 | 70.4688 | 1.7064 | 2.0101 | 0.7733 | 3.5283 | 1.2083 |
| high_momentum::ordinary::normal::touched_but_not_closed_limit | 197 | 57.3604 | 1.6321 | 1.0221 | 3.0457 | 14.2132 | 4.0609 |
| high_momentum::intraday_fade::active::no_limit_source | 225 | 53.7778 | 1.4487 | 0.8516 | 4.0 | 16.4444 | 6.2222 |
| deep_oversold::panic_low_close::normal::touched_but_not_closed_limit | 214 | 57.9439 | 1.4385 | 1.1851 | 3.7383 | 9.3458 | 1.8692 |
| deep_oversold::intraday_fade::normal::no_limit_source | 244 | 56.1475 | 1.4137 | 0.5919 | 2.0492 | 12.2951 | 2.459 |
| deep_oversold::panic_low_close::contracted::no_limit_source | 720 | 67.0833 | 1.3091 | 1.5663 | 0.9722 | 4.8611 | 1.8056 |
| high_momentum::first_sun_or_strong_close::hot::multi_limit_source | 155 | 57.4194 | 1.2957 | 0.6842 | 14.8387 | 19.3548 | 5.1613 |
| high_momentum::first_sun_or_strong_close::normal::multi_limit_source | 269 | 57.2491 | 1.2123 | 0.8676 | 13.3829 | 17.4721 | 4.8327 |
| high_momentum::ordinary::active::touched_but_not_closed_limit | 257 | 54.0856 | 1.2078 | 0.3865 | 5.8366 | 12.4514 | 4.2802 |
| high_momentum::first_sun_or_strong_close::extreme::no_limit_source | 735 | 53.3333 | 1.1927 | 0.4093 | 6.1224 | 13.0612 | 3.1293 |
| neutral::intraday_fade::active::single_limit_source | 136 | 50.7353 | 1.1279 | 0.0428 | 6.6176 | 12.5 | 4.4118 |
| high_momentum::first_sun_or_strong_close::active::touched_but_not_closed_limit | 286 | 50.0 | 1.0848 | -0.0006 | 8.3916 | 15.035 | 3.4965 |
| deep_oversold::intraday_fade::active::no_limit_source | 160 | 54.375 | 1.0814 | 0.8433 | 2.5 | 6.875 | 0.625 |
| neutral::intraday_fade::active::no_limit_source | 368 | 51.3587 | 1.0112 | 0.219 | 2.1739 | 13.587 | 4.3478 |
| deep_oversold::panic_low_close::contracted::touched_but_not_closed_limit | 183 | 58.4699 | 1.0109 | 0.7264 | 4.3716 | 7.1038 | 2.7322 |
| high_momentum::balanced_mid_close::normal::multi_limit_source | 135 | 54.0741 | 0.9826 | 0.4699 | 8.8889 | 11.1111 | 2.2222 |
| high_momentum::low_close::active::multi_limit_source | 136 | 56.6176 | 0.9605 | 0.5781 | 8.8235 | 11.7647 | 3.6765 |
| deep_oversold::panic_low_close::contracted::single_limit_source | 371 | 59.5687 | 0.9448 | 1.0499 | 1.3477 | 2.965 | 1.6173 |
| high_momentum::first_sun_or_strong_close::extreme::single_limit_source | 193 | 48.7047 | 0.9175 | -0.1195 | 13.4715 | 18.6528 | 6.7358 |
| low_repair::intraday_fade::normal::no_limit_source | 314 | 48.7261 | 0.8964 | -0.0374 | 2.5478 | 13.3758 | 3.1847 |
| high_momentum::ordinary::extreme::no_limit_source | 327 | 50.1529 | 0.8956 | 0.0076 | 3.0581 | 11.0092 | 1.5291 |
| neutral::intraday_fade::hot::no_limit_source | 208 | 48.0769 | 0.8936 | -0.275 | 2.8846 | 10.5769 | 0.9615 |
| deep_oversold::panic_low_close::contracted::multi_limit_source | 139 | 55.3957 | 0.8602 | 0.4704 | 7.1942 | 8.6331 | 3.5971 |
| high_momentum::ordinary::extreme::single_limit_source | 154 | 50.6494 | 0.8396 | 0.1847 | 4.5455 | 9.7403 | 2.5974 |
| high_momentum::first_sun_or_strong_close::active::multi_limit_source | 348 | 55.1724 | 0.8261 | 0.4497 | 12.069 | 15.8046 | 8.908 |
| deep_oversold::first_sun_or_strong_close::contracted_low_turnover_proxy::no_limit_source | 131 | 62.5954 | 0.7888 | 0.916 | 0.0 | 0.7634 | 0.0 |
| high_momentum::balanced_mid_close::normal::single_limit_source | 196 | 52.551 | 0.7609 | 0.4746 | 2.551 | 8.6735 | 1.5306 |
| deep_oversold::panic_low_close::hot::no_limit_source | 175 | 61.1429 | 0.7567 | 1.1552 | 0.5714 | 5.1429 | 5.1429 |
| high_momentum::ordinary::active::no_limit_source | 1231 | 53.3712 | 0.7447 | 0.3842 | 1.1373 | 8.8546 | 4.4679 |
| high_momentum::ordinary::normal::multi_limit_source | 263 | 52.0913 | 0.7377 | 0.2364 | 8.7452 | 14.4487 | 3.0418 |
| high_momentum::first_sun_or_strong_close::hot::single_limit_source | 403 | 52.8536 | 0.73 | 0.2488 | 7.9404 | 13.8958 | 7.6923 |
| high_momentum::ordinary::hot::no_limit_source | 757 | 51.1229 | 0.7258 | 0.1124 | 3.1704 | 10.1717 | 2.7741 |
| high_momentum::first_sun_or_strong_close::active::single_limit_source | 554 | 49.278 | 0.6806 | 0.0 | 6.3177 | 12.9964 | 5.4152 |
| high_momentum::ordinary::active::single_limit_source | 517 | 51.8375 | 0.6707 | 0.1497 | 4.4487 | 12.3791 | 3.2882 |
| neutral::low_close::active::multi_limit_source | 155 | 54.8387 | 0.6628 | 0.4491 | 6.4516 | 7.7419 | 3.871 |
| deep_oversold::panic_low_close::normal::single_limit_source | 296 | 56.4189 | 0.6332 | 0.681 | 1.6892 | 4.3919 | 2.027 |
| deep_oversold::ordinary::normal_low_turnover_proxy::no_limit_source | 325 | 55.0769 | 0.6063 | 0.2209 | 1.2308 | 4.3077 | 0.6154 |
| high_momentum::first_sun_or_strong_close::hot::touched_but_not_closed_limit | 194 | 51.0309 | 0.5917 | 0.0802 | 3.6082 | 8.7629 | 4.1237 |
| deep_oversold::first_sun_or_strong_close::contracted::touched_but_not_closed_limit | 161 | 59.6273 | 0.5835 | 0.6887 | 3.7267 | 3.7267 | 1.2422 |

## Volume And Turnover Groups

| feature_group | n | win_rate | avg_return | median_return | d1_limit_rate | d1_big_down7_rate |
| --- | --- | --- | --- | --- | --- | --- |
| volume_contracting_three_day::extreme | 213 | 47.4178 | 0.7234 | -0.4447 | 7.0423 | 3.2864 |
| sudden_volume_expansion::extreme | 847 | 46.3991 | 0.3092 | -0.3126 | 4.8406 | 2.1251 |
| mixed_volume::extreme | 1646 | 46.294 | 0.2961 | -0.2701 | 4.5565 | 3.2807 |
| volume_rising_three_day::hot_low_turnover_proxy | 322 | 51.2422 | 0.2779 | 0.0694 | 1.8634 | 1.2422 |
| volume_rising_three_day::hot | 5985 | 47.218 | 0.2294 | -0.1702 | 2.5731 | 2.1387 |
| volume_contracting_three_day::hot | 1625 | 45.8462 | 0.1923 | -0.3527 | 2.5231 | 3.2 |
| volume_contracting_three_day::active | 9332 | 48.6069 | 0.1771 | -0.0436 | 1.9931 | 2.4646 |
| volume_contracting_three_day::active_low_turnover_proxy | 772 | 48.5751 | 0.177 | 0.0 | 0.7772 | 0.3886 |
| mixed_volume::hot | 8002 | 47.3757 | 0.1732 | -0.1645 | 2.5744 | 2.4619 |
| mixed_volume::contracted_low_turnover_proxy | 6050 | 50.5785 | 0.1631 | 0.064 | 0.7273 | 0.4298 |
| volume_rising_three_day::active | 16405 | 47.705 | 0.1345 | -0.1015 | 1.463 | 1.8531 |
| volume_rising_three_day::extreme | 2373 | 45.6384 | 0.1272 | -0.3215 | 3.4977 | 2.9077 |
| mixed_volume::hot_low_turnover_proxy | 346 | 44.5087 | 0.1119 | -0.2014 | 0.289 | 0.578 |
| volume_rising_three_day::active_low_turnover_proxy | 2289 | 47.1385 | 0.0987 | -0.0621 | 0.6116 | 0.6116 |
| mixed_volume::active_low_turnover_proxy | 4617 | 46.1988 | 0.0695 | -0.0736 | 0.4982 | 0.4548 |
| multi_day_contraction::contracted_low_turnover_proxy | 19595 | 46.5323 | 0.0472 | -0.0824 | 0.5971 | 0.4236 |
| mixed_volume::active | 37099 | 46.2331 | 0.0453 | -0.224 | 1.6793 | 1.9893 |
| mixed_volume::normal_low_turnover_proxy | 20781 | 46.4655 | 0.0009 | -0.0992 | 0.5293 | 0.4283 |
| volume_contracting_three_day::normal_low_turnover_proxy | 8340 | 44.4245 | -0.0414 | -0.2112 | 0.5036 | 0.3237 |
| mixed_volume::contracted | 13464 | 46.1378 | -0.0645 | -0.2462 | 1.4112 | 1.0992 |
| volume_rising_three_day::normal_low_turnover_proxy | 3965 | 45.6242 | -0.0684 | -0.1294 | 0.2018 | 0.5296 |
| volume_contracting_three_day::contracted_low_turnover_proxy | 7837 | 43.9837 | -0.0706 | -0.2544 | 0.5614 | 0.4466 |
| mixed_volume::normal | 74355 | 45.6607 | -0.0755 | -0.262 | 1.2185 | 1.47 |
| sudden_volume_expansion::hot | 1887 | 44.0382 | -0.0788 | -0.4492 | 2.5437 | 1.7488 |
| volume_rising_three_day::normal | 17558 | 45.9506 | -0.0822 | -0.2037 | 1.0935 | 1.589 |
| volume_contracting_three_day::normal | 31933 | 44.7938 | -0.0998 | -0.3077 | 1.3873 | 1.6409 |
| multi_day_contraction::normal_low_turnover_proxy | 4454 | 43.3543 | -0.1292 | -0.2188 | 0.5613 | 0.5388 |
| sudden_volume_expansion::extreme_high_turnover_proxy | 676 | 43.9349 | -0.1539 | -0.7947 | 7.6923 | 7.2485 |
| volume_contracting_three_day::extreme_high_turnover_proxy | 447 | 44.2953 | -0.1656 | -0.8955 | 8.0537 | 11.4094 |
| multi_day_contraction::contracted | 53595 | 44.3679 | -0.2029 | -0.3693 | 1.0822 | 1.2203 |
| volume_contracting_three_day::contracted | 17262 | 43.338 | -0.2069 | -0.4384 | 1.4251 | 1.4193 |
| multi_day_contraction::normal | 12460 | 43.7319 | -0.2277 | -0.3445 | 0.9551 | 1.862 |
| high_turnover_proxy_latest::contracted_high_turnover_proxy | 454 | 43.8326 | -0.2364 | -0.493 | 4.6256 | 4.185 |
| multi_day_contraction::contracted_high_turnover_proxy | 2099 | 44.9262 | -0.2459 | -0.4212 | 2.9538 | 3.6684 |
| volume_rising_three_day::active_high_turnover_proxy | 2222 | 43.4743 | -0.3185 | -0.7414 | 4.4104 | 7.9208 |
| volume_rising_three_day::hot_high_turnover_proxy | 2267 | 42.6114 | -0.324 | -0.7504 | 4.1906 | 7.4548 |
| volume_rising_three_day::normal_high_turnover_proxy | 975 | 45.4359 | -0.3784 | -0.5634 | 3.4872 | 6.6667 |
| high_turnover_proxy_latest::extreme_high_turnover_proxy | 2193 | 42.7269 | -0.3909 | -0.876 | 5.472 | 9.2111 |
| high_turnover_proxy_latest::hot_high_turnover_proxy | 3784 | 41.2526 | -0.4543 | -0.9439 | 4.704 | 7.7696 |
| high_turnover_proxy_latest::active_high_turnover_proxy | 6438 | 42.0317 | -0.4976 | -0.9795 | 4.0541 | 8.2168 |

## Target Feature Mix

| target | feature | n | share_in_target | avg_return | median_return |
| --- | --- | --- | --- | --- | --- |
| d1_limit_up | position_group=neutral | 2206 | 34.4203 | 10.9319 | 10.0028 |
| d1_limit_up | position_group=high_momentum | 1960 | 30.582 | 11.2844 | 10.0016 |
| d1_limit_up | position_group=low_repair | 1403 | 21.8911 | 11.1699 | 10.0037 |
| d1_limit_up | position_group=deep_oversold | 716 | 11.1718 | 11.1775 | 10.0036 |
| d1_limit_up | position_group=extreme_hot | 124 | 1.9348 | 11.2627 | 10.0 |
| d1_limit_up | price_action_group=first_sun_or_strong_close | 1666 | 25.9947 | 11.0042 | 10.0026 |
| d1_limit_up | price_action_group=ordinary | 1383 | 21.579 | 11.2951 | 10.0022 |
| d1_limit_up | price_action_group=low_close | 1116 | 17.413 | 10.8141 | 10.0015 |
| d1_limit_up | price_action_group=balanced_mid_close | 567 | 8.8469 | 11.2002 | 10.0013 |
| d1_limit_up | price_action_group=panic_low_close | 492 | 7.6767 | 11.2302 | 10.0008 |
| d1_limit_up | price_action_group=compressed_mid_close | 457 | 7.1306 | 10.8956 | 10.0 |
| d1_limit_up | price_action_group=intraday_fade | 369 | 5.7575 | 12.1294 | 10.0055 |
| d1_limit_up | price_action_group=high_close | 359 | 5.6015 | 11.005 | 10.0056 |
| d1_limit_up | volume_turnover_group=normal | 1665 | 25.9791 | 11.2824 | 10.0036 |
| d1_limit_up | volume_turnover_group=active | 1058 | 16.508 | 11.3917 | 10.0018 |
| d1_limit_up | volume_turnover_group=contracted | 1020 | 15.9151 | 10.825 | 10.0 |
| d1_limit_up | volume_turnover_group=active_high_turnover_proxy | 455 | 7.0994 | 10.7274 | 10.0 |
| d1_limit_up | volume_turnover_group=hot | 450 | 7.0214 | 11.3314 | 10.0041 |
| d1_limit_up | volume_turnover_group=hot_high_turnover_proxy | 349 | 5.4455 | 11.0877 | 10.0023 |
| d1_limit_up | volume_turnover_group=extreme_high_turnover_proxy | 333 | 5.1958 | 10.939 | 10.0 |
| d1_limit_up | volume_turnover_group=normal_high_turnover_proxy | 314 | 4.8994 | 10.7226 | 10.0012 |
| d1_limit_up | volume_turnover_group=extreme | 216 | 3.3703 | 11.4238 | 10.0 |
| d1_limit_up | volume_turnover_group=contracted_low_turnover_proxy | 205 | 3.1986 | 10.8515 | 10.0 |
| d1_limit_up | volume_turnover_group=normal_low_turnover_proxy | 185 | 2.8866 | 11.2745 | 10.0013 |
| d1_limit_up | volume_turnover_group=contracted_high_turnover_proxy | 99 | 1.5447 | 10.7881 | 10.0 |
| d1_limit_up | volume_turnover_group=active_low_turnover_proxy | 43 | 0.6709 | 11.8721 | 10.0046 |
| d1_limit_up | volume_turnover_group=hot_low_turnover_proxy | 8 | 0.1248 | 9.9241 | 10.0249 |
| d1_limit_up | volume_turnover_group=unknown_turnover | 6 | 0.0936 | 16.6674 | 20.0 |
| d1_limit_up | volume_turnover_group=extreme_low_turnover_proxy | 3 | 0.0468 | 10.0308 | 10.0406 |
| d1_limit_up | active_source_group=no_limit_source | 2446 | 38.1651 | 12.0812 | 10.0112 |
| d1_limit_up | active_source_group=single_limit_source | 1411 | 22.0159 | 10.7989 | 10.0005 |
| d1_limit_up | active_source_group=multi_limit_source | 1284 | 20.0343 | 10.2131 | 10.0 |
| d1_limit_up | active_source_group=touched_but_not_closed_limit | 674 | 10.5165 | 11.0834 | 10.0015 |
| d1_limit_up | active_source_group=crowded_active_source | 594 | 9.2682 | 9.9873 | 10.0 |
| d1_limit_up | pre_volume_pattern=mixed_volume | 2178 | 33.9835 | 11.3031 | 10.0033 |
| d1_limit_up | pre_volume_pattern=volume_contracting_three_day | 1331 | 20.7677 | 10.9149 | 10.002 |
| d1_limit_up | pre_volume_pattern=volume_rising_three_day | 1053 | 16.43 | 11.3827 | 10.0035 |
| d1_limit_up | pre_volume_pattern=multi_day_contraction | 930 | 14.5108 | 10.9392 | 10.0 |
| d1_limit_up | pre_volume_pattern=high_turnover_proxy_latest | 740 | 11.5463 | 10.8281 | 10.0 |
| d1_limit_up | pre_volume_pattern=sudden_volume_expansion | 168 | 2.6213 | 10.93 | 10.0 |
| d1_limit_up | pre_volume_pattern=volume_history_unknown | 9 | 0.1404 | 16.6666 | 20.0 |
| d1_limit_up | flag=active_source_compressed_high_close | 269 | 4.1972 | 10.4635 | 10.0 |
| d1_limit_up | flag=deep_low_close_rebound_absorption | 279 | 4.3533 | 11.0902 | 10.0033 |
| d1_limit_up | flag=deep_low_first_sun_confirm | 81 | 1.2638 | 11.0794 | 10.0 |
| d1_limit_up | flag=extreme_volume_intraday_fade | 146 | 2.278 | 11.0724 | 10.0 |
| d1_limit_up | flag=active_source_breakdown | 381 | 5.9448 | 10.3649 | 10.0 |
| d1_limit_up | flag=hot_reacceleration_exhaustion | 69 | 1.0766 | 10.8497 | 10.0 |
| d1_limit_up | flag=weak_repair_high_close_no_source | 149 | 2.3249 | 11.0427 | 10.0057 |
| d1_big_up7 | position_group=neutral | 5050 | 34.7294 | 10.0414 | 9.9886 |
| d1_big_up7 | position_group=high_momentum | 4114 | 28.2924 | 10.4573 | 9.9978 |
| d1_big_up7 | position_group=low_repair | 3295 | 22.6601 | 10.0459 | 9.9831 |
| d1_big_up7 | position_group=deep_oversold | 1781 | 12.2481 | 10.0578 | 9.9781 |
| d1_big_up7 | position_group=extreme_hot | 301 | 2.07 | 10.7876 | 10.0 |
| d1_big_up7 | price_action_group=ordinary | 3381 | 23.2515 | 10.2485 | 9.9896 |
| d1_big_up7 | price_action_group=first_sun_or_strong_close | 3054 | 21.0027 | 10.3588 | 9.9986 |
| d1_big_up7 | price_action_group=low_close | 2662 | 18.3069 | 9.8726 | 9.9823 |
| d1_big_up7 | price_action_group=balanced_mid_close | 1371 | 9.4285 | 10.0847 | 9.9816 |
| d1_big_up7 | price_action_group=panic_low_close | 1170 | 8.0462 | 10.1832 | 9.989 |
| d1_big_up7 | price_action_group=compressed_mid_close | 1121 | 7.7092 | 9.8624 | 9.9628 |
| d1_big_up7 | price_action_group=intraday_fade | 953 | 6.5539 | 10.6806 | 10.0 |
| d1_big_up7 | price_action_group=high_close | 829 | 5.7011 | 10.193 | 9.995 |
| d1_big_up7 | volume_turnover_group=normal | 4173 | 28.6982 | 10.1664 | 9.9904 |
| d1_big_up7 | volume_turnover_group=active | 2749 | 18.9052 | 10.2305 | 9.987 |
| d1_big_up7 | volume_turnover_group=contracted | 2273 | 15.6317 | 9.966 | 9.9857 |
| d1_big_up7 | volume_turnover_group=hot | 992 | 6.8221 | 10.4044 | 9.9992 |
| d1_big_up7 | volume_turnover_group=active_high_turnover_proxy | 873 | 6.0037 | 10.2246 | 9.9967 |
| d1_big_up7 | volume_turnover_group=hot_high_turnover_proxy | 635 | 4.367 | 10.4457 | 10.0 |
| d1_big_up7 | volume_turnover_group=normal_high_turnover_proxy | 579 | 3.9818 | 10.0083 | 9.9945 |
| d1_big_up7 | volume_turnover_group=extreme_high_turnover_proxy | 571 | 3.9268 | 10.3479 | 10.0 |
| d1_big_up7 | volume_turnover_group=contracted_low_turnover_proxy | 491 | 3.3767 | 9.7202 | 9.9448 |
| d1_big_up7 | volume_turnover_group=normal_low_turnover_proxy | 484 | 3.3285 | 9.9087 | 9.9469 |
| d1_big_up7 | volume_turnover_group=extreme | 384 | 2.6408 | 10.6932 | 10.0 |
| d1_big_up7 | volume_turnover_group=contracted_high_turnover_proxy | 172 | 1.1829 | 10.4881 | 10.0 |
| d1_big_up7 | volume_turnover_group=active_low_turnover_proxy | 116 | 0.7977 | 10.3058 | 9.9941 |
| d1_big_up7 | volume_turnover_group=unknown_turnover | 22 | 0.1513 | 12.4513 | 10.5738 |
| d1_big_up7 | volume_turnover_group=hot_low_turnover_proxy | 20 | 0.1375 | 9.3565 | 9.5168 |
| d1_big_up7 | volume_turnover_group=extreme_low_turnover_proxy | 7 | 0.0481 | 10.3193 | 10.0418 |
| d1_big_up7 | active_source_group=no_limit_source | 7980 | 54.8793 | 10.3329 | 9.9718 |
| d1_big_up7 | active_source_group=single_limit_source | 2670 | 18.3619 | 10.1113 | 9.9938 |
| d1_big_up7 | active_source_group=multi_limit_source | 1777 | 12.2206 | 9.8303 | 9.9982 |
| d1_big_up7 | active_source_group=touched_but_not_closed_limit | 1352 | 9.2978 | 10.2021 | 9.993 |
| d1_big_up7 | active_source_group=crowded_active_source | 762 | 5.2404 | 9.5497 | 9.9975 |
| d1_big_up7 | pre_volume_pattern=mixed_volume | 5282 | 36.3249 | 10.1892 | 9.9903 |
| d1_big_up7 | pre_volume_pattern=volume_contracting_three_day | 3029 | 20.8308 | 10.1193 | 9.991 |
| d1_big_up7 | pre_volume_pattern=volume_rising_three_day | 2369 | 16.2919 | 10.3352 | 9.994 |
| d1_big_up7 | pre_volume_pattern=multi_day_contraction | 2168 | 14.9096 | 10.0099 | 9.983 |
| d1_big_up7 | pre_volume_pattern=high_turnover_proxy_latest | 1385 | 9.5248 | 10.158 | 9.9944 |
| d1_big_up7 | pre_volume_pattern=sudden_volume_expansion | 280 | 1.9256 | 10.3808 | 10.0 |
| d1_big_up7 | pre_volume_pattern=volume_history_unknown | 28 | 0.1926 | 12.8585 | 11.0565 |
| d1_big_up7 | flag=active_source_compressed_high_close | 390 | 2.6821 | 10.0923 | 9.9988 |
| d1_big_up7 | flag=deep_low_close_rebound_absorption | 743 | 5.1097 | 9.9874 | 9.9744 |
| d1_big_up7 | flag=deep_low_first_sun_confirm | 174 | 1.1966 | 10.3469 | 9.9897 |
| d1_big_up7 | flag=extreme_volume_intraday_fade | 281 | 1.9325 | 10.3333 | 10.0 |
| d1_big_up7 | flag=active_source_breakdown | 588 | 4.0437 | 9.942 | 10.0 |
| d1_big_up7 | flag=hot_reacceleration_exhaustion | 126 | 0.8665 | 10.3727 | 10.0 |
| d1_big_up7 | flag=weak_repair_high_close_no_source | 381 | 2.6202 | 9.9926 | 9.9719 |
| d1_big_down7 | position_group=neutral | 2905 | 35.0084 | -8.8225 | -8.4281 |
| d1_big_down7 | position_group=high_momentum | 2573 | 31.0075 | -9.0747 | -8.7059 |
| d1_big_down7 | position_group=low_repair | 1826 | 22.0053 | -8.3698 | -7.9532 |
| d1_big_down7 | position_group=deep_oversold | 753 | 9.0745 | -8.6122 | -8.0494 |
| d1_big_down7 | position_group=extreme_hot | 241 | 2.9043 | -9.9198 | -9.8195 |
| d1_big_down7 | price_action_group=ordinary | 1788 | 21.5474 | -8.9144 | -8.4814 |
| d1_big_down7 | price_action_group=low_close | 1627 | 19.6071 | -8.4557 | -7.9609 |
| d1_big_down7 | price_action_group=first_sun_or_strong_close | 1627 | 19.6071 | -9.0758 | -8.7345 |
| d1_big_down7 | price_action_group=panic_low_close | 976 | 11.7619 | -8.8061 | -8.4873 |
| d1_big_down7 | price_action_group=balanced_mid_close | 732 | 8.8214 | -8.7438 | -8.2433 |
| d1_big_down7 | price_action_group=intraday_fade | 587 | 7.074 | -9.0718 | -8.7554 |
| d1_big_down7 | price_action_group=compressed_mid_close | 487 | 5.8689 | -8.5958 | -8.051 |
| d1_big_down7 | price_action_group=high_close | 474 | 5.7122 | -8.7933 | -8.3115 |
| d1_big_down7 | volume_turnover_group=normal | 2131 | 25.6809 | -8.6326 | -8.1156 |
| d1_big_down7 | volume_turnover_group=active | 1278 | 15.4013 | -8.8453 | -8.3669 |
| d1_big_down7 | volume_turnover_group=contracted | 1047 | 12.6175 | -8.4411 | -7.956 |
| d1_big_down7 | volume_turnover_group=active_high_turnover_proxy | 914 | 11.0147 | -9.0921 | -8.9159 |
| d1_big_down7 | volume_turnover_group=normal_high_turnover_proxy | 690 | 8.3153 | -8.908 | -8.6243 |
| d1_big_down7 | volume_turnover_group=hot_high_turnover_proxy | 630 | 7.5922 | -9.193 | -8.8982 |
| d1_big_down7 | volume_turnover_group=extreme_high_turnover_proxy | 525 | 6.3268 | -9.2543 | -9.0827 |
| d1_big_down7 | volume_turnover_group=hot | 411 | 4.953 | -8.8905 | -8.4324 |
| d1_big_down7 | volume_turnover_group=normal_low_turnover_proxy | 161 | 1.9402 | -8.4467 | -7.8942 |
| d1_big_down7 | volume_turnover_group=extreme | 148 | 1.7836 | -9.0036 | -8.6343 |
| d1_big_down7 | volume_turnover_group=contracted_high_turnover_proxy | 145 | 1.7474 | -8.5432 | -8.313 |
| d1_big_down7 | volume_turnover_group=contracted_low_turnover_proxy | 144 | 1.7354 | -8.5952 | -8.0279 |
| d1_big_down7 | volume_turnover_group=active_low_turnover_proxy | 38 | 0.4579 | -8.2453 | -7.8933 |
| d1_big_down7 | volume_turnover_group=unknown_turnover | 30 | 0.3615 | -10.0485 | -9.4491 |
| d1_big_down7 | volume_turnover_group=hot_low_turnover_proxy | 6 | 0.0723 | -9.1127 | -8.8648 |
| d1_big_down7 | active_source_group=no_limit_source | 4121 | 49.6626 | -8.7533 | -8.1301 |
| d1_big_down7 | active_source_group=single_limit_source | 1593 | 19.1974 | -8.8638 | -8.4886 |
| d1_big_down7 | active_source_group=multi_limit_source | 1206 | 14.5336 | -8.8715 | -8.7208 |
| d1_big_down7 | active_source_group=touched_but_not_closed_limit | 780 | 9.3999 | -8.8918 | -8.5371 |
| d1_big_down7 | active_source_group=crowded_active_source | 598 | 7.2066 | -8.8799 | -8.9941 |
| d1_big_down7 | pre_volume_pattern=mixed_volume | 2368 | 28.537 | -8.6955 | -8.197 |
| d1_big_down7 | pre_volume_pattern=volume_contracting_three_day | 1778 | 21.4268 | -8.8432 | -8.4176 |
| d1_big_down7 | pre_volume_pattern=volume_rising_three_day | 1453 | 17.5102 | -8.946 | -8.505 |
| d1_big_down7 | pre_volume_pattern=high_turnover_proxy_latest | 1414 | 17.0403 | -9.0359 | -8.8392 |
| d1_big_down7 | pre_volume_pattern=multi_day_contraction | 1109 | 13.3647 | -8.5247 | -8.0154 |
| d1_big_down7 | pre_volume_pattern=sudden_volume_expansion | 145 | 1.7474 | -8.8187 | -8.2778 |
| d1_big_down7 | pre_volume_pattern=volume_history_unknown | 31 | 0.3736 | -10.1675 | -9.5396 |
| d1_big_down7 | flag=active_source_compressed_high_close | 191 | 2.3018 | -9.0072 | -8.9024 |
| d1_big_down7 | flag=deep_low_close_rebound_absorption | 339 | 4.0853 | -8.4228 | -7.919 |
| d1_big_down7 | flag=deep_low_first_sun_confirm | 57 | 0.6869 | -9.0143 | -9.0588 |
| d1_big_down7 | flag=extreme_volume_intraday_fade | 254 | 3.061 | -8.9008 | -8.7219 |
| d1_big_down7 | flag=active_source_breakdown | 482 | 5.8086 | -8.8519 | -8.8008 |
| d1_big_down7 | flag=hot_reacceleration_exhaustion | 59 | 0.711 | -9.7618 | -9.5979 |
| d1_big_down7 | flag=weak_repair_high_close_no_source | 189 | 2.2777 | -8.6079 | -8.0154 |
| d1_limit_down | position_group=high_momentum | 601 | 38.7492 | -10.1141 | -9.9961 |
| d1_limit_down | position_group=neutral | 588 | 37.911 | -10.2107 | -9.9885 |
| d1_limit_down | position_group=low_repair | 191 | 12.3146 | -10.2673 | -9.9886 |
| d1_limit_down | position_group=deep_oversold | 108 | 6.9632 | -10.6007 | -9.9929 |
| d1_limit_down | position_group=extreme_hot | 63 | 4.0619 | -10.2526 | -9.9988 |
| d1_limit_down | price_action_group=first_sun_or_strong_close | 404 | 26.0477 | -10.0879 | -9.9917 |
| d1_limit_down | price_action_group=ordinary | 326 | 21.0187 | -10.3138 | -9.9964 |
| d1_limit_down | price_action_group=panic_low_close | 254 | 16.3765 | -10.135 | -9.9911 |
| d1_limit_down | price_action_group=low_close | 196 | 12.637 | -10.4672 | -9.9908 |
| d1_limit_down | price_action_group=balanced_mid_close | 121 | 7.8014 | -10.193 | -9.989 |
| d1_limit_down | price_action_group=intraday_fade | 109 | 7.0277 | -9.9744 | -9.9895 |
| d1_limit_down | price_action_group=high_close | 76 | 4.9001 | -10.2004 | -9.9963 |
| d1_limit_down | price_action_group=compressed_mid_close | 65 | 4.1908 | -10.3827 | -9.9927 |
| d1_limit_down | volume_turnover_group=normal | 273 | 17.6015 | -10.5656 | -9.9923 |
| d1_limit_down | volume_turnover_group=active_high_turnover_proxy | 242 | 15.6028 | -9.9824 | -9.9943 |
| d1_limit_down | volume_turnover_group=active | 185 | 11.9278 | -10.2728 | -9.9916 |
| d1_limit_down | volume_turnover_group=extreme_high_turnover_proxy | 173 | 11.1541 | -10.1145 | -9.9922 |
| d1_limit_down | volume_turnover_group=hot_high_turnover_proxy | 171 | 11.0251 | -10.0483 | -9.994 |
| d1_limit_down | volume_turnover_group=normal_high_turnover_proxy | 159 | 10.2515 | -9.9653 | -9.9896 |
| d1_limit_down | volume_turnover_group=contracted | 137 | 8.833 | -10.3699 | -9.9977 |
| d1_limit_down | volume_turnover_group=hot | 78 | 5.029 | -9.987 | -9.9841 |
| d1_limit_down | volume_turnover_group=extreme | 34 | 2.1921 | -10.1852 | -9.9975 |
| d1_limit_down | volume_turnover_group=contracted_low_turnover_proxy | 34 | 2.1921 | -10.2777 | -9.9905 |
| d1_limit_down | volume_turnover_group=contracted_high_turnover_proxy | 28 | 1.8053 | -9.8771 | -9.9861 |
| d1_limit_down | volume_turnover_group=normal_low_turnover_proxy | 24 | 1.5474 | -10.773 | -9.9586 |
| d1_limit_down | volume_turnover_group=unknown_turnover | 8 | 0.5158 | -12.4546 | -10.0023 |
| d1_limit_down | volume_turnover_group=active_low_turnover_proxy | 4 | 0.2579 | -10.4388 | -10.2692 |
| d1_limit_down | volume_turnover_group=hot_low_turnover_proxy | 1 | 0.0645 | -9.2644 | -9.2644 |
| d1_limit_down | active_source_group=multi_limit_source | 429 | 27.6596 | -9.9494 | -9.9932 |
| d1_limit_down | active_source_group=no_limit_source | 351 | 22.6306 | -10.9696 | -9.9909 |
| d1_limit_down | active_source_group=single_limit_source | 346 | 22.3082 | -10.017 | -9.9912 |
| d1_limit_down | active_source_group=crowded_active_source | 276 | 17.795 | -9.9117 | -9.9964 |
| d1_limit_down | active_source_group=touched_but_not_closed_limit | 149 | 9.6067 | -10.1627 | -9.9922 |
| d1_limit_down | pre_volume_pattern=high_turnover_proxy_latest | 374 | 24.1135 | -10.0633 | -9.9927 |
| d1_limit_down | pre_volume_pattern=volume_contracting_three_day | 357 | 23.0174 | -10.1639 | -9.9928 |
| d1_limit_down | pre_volume_pattern=mixed_volume | 337 | 21.7279 | -10.2096 | -9.9897 |
| d1_limit_down | pre_volume_pattern=volume_rising_three_day | 298 | 19.2134 | -10.2102 | -9.9932 |
| d1_limit_down | pre_volume_pattern=multi_day_contraction | 142 | 9.1554 | -10.648 | -9.994 |
| d1_limit_down | pre_volume_pattern=sudden_volume_expansion | 35 | 2.2566 | -9.9201 | -9.999 |
| d1_limit_down | pre_volume_pattern=volume_history_unknown | 8 | 0.5158 | -12.4546 | -10.0023 |
| d1_limit_down | flag=active_source_compressed_high_close | 67 | 4.3198 | -9.911 | -9.989 |
| d1_limit_down | flag=deep_low_close_rebound_absorption | 46 | 2.9658 | -10.8622 | -10.0 |
| d1_limit_down | flag=deep_low_first_sun_confirm | 10 | 0.6447 | -9.9217 | -9.9937 |
| d1_limit_down | flag=extreme_volume_intraday_fade | 78 | 5.029 | -9.8667 | -9.9738 |
| d1_limit_down | flag=active_source_breakdown | 176 | 11.3475 | -9.9016 | -9.9909 |
| d1_limit_down | flag=hot_reacceleration_exhaustion | 16 | 1.0316 | -9.9187 | -9.9959 |
| d1_limit_down | flag=weak_repair_high_close_no_source | 18 | 1.1605 | -10.6762 | -9.9979 |

## Samples


### d1_limit_up_examples

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-01 | 2026-06-02 | 300197.SZSE | 节能铁汉 | 20.2073 | 19.8758 | high_momentum | first_sun_or_strong_close | extreme | volume_rising_three_day | no_limit_source | 5.3691 | 1.2682 | 0.9793 | 2.8841 | 0.8116 | 0.6072 |
| 2026-04-23 | 2026-04-24 | 300422.SZSE | 博世科 | 20.0864 | 0.0 | neutral | balanced_mid_close | normal | mixed_volume | no_limit_source | 1.6347 | 1.0996 | 1.4014 | 0.9425 | 0.6081 | 0.7571 |
| 2026-06-30 | 2026-07-01 | 300175.SZSE | 朗源股份 | 20.0864 | 0.4338 | deep_oversold | ordinary | normal | mixed_volume | no_limit_source | 2.3636 | 1.8048 | 1.7978 | 1.085 | 0.8854 | 0.8879 |
| 2026-06-23 | 2026-06-24 | 300506.SZSE | 名家汇 | 20.0846 | -2.6749 | neutral | low_close | active_low_turnover_proxy | volume_contracting_three_day | single_limit_source | 0.965 | 1.1269 | None | 1.2616 | 1.5286 | 1.6818 |
| 2026-04-02 | 2026-04-03 | 300006.SZSE | 莱美药业 | 20.0737 | 5.2326 | neutral | ordinary | extreme_high_turnover_proxy | volume_rising_three_day | no_limit_source | 9.8993 | 3.2896 | 1.9424 | 3.6148 | 1.281 | 0.7346 |
| 2026-06-05 | 2026-06-08 | 300105.SZSE | 龙源技术 | 20.0669 | 0.6734 | low_repair | balanced_mid_close | normal | volume_rising_three_day | no_limit_source | 1.0321 | 1.0204 | 1.012 | 0.8512 | 0.8309 | 0.7906 |
| 2026-03-02 | 2026-03-03 | 300332.SZSE | 天壕能源 | 20.0663 | 5.9754 | neutral | first_sun_or_strong_close | extreme_high_turnover_proxy | volume_rising_three_day | no_limit_source | 15.0716 | 3.7635 | 2.2728 | 3.6689 | 0.9153 | 0.5264 |
| 2026-03-04 | 2026-03-05 | 688055.SSE | 龙腾光电 | 20.0565 | -2.7473 | low_repair | low_close | normal_low_turnover_proxy | mixed_volume | no_limit_source | 0.2132 | 0.2779 | 0.2709 | 1.088 | 1.3808 | 1.311 |
| 2026-06-09 | 2026-06-10 | 300264.SZSE | 佳创视讯 | 20.0514 | 6.7215 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 5.1708 | 4.0646 | 5.214 | 1.0162 | 0.7876 | 0.9678 |
| 2026-05-29 | 2026-06-01 | 300103.SZSE | 达刚控股 | 20.0501 | -3.9711 | low_repair | low_close | contracted | volume_contracting_three_day | no_limit_source | 2.8595 | 2.9749 | 3.4589 | 0.7208 | 0.7368 | 0.8501 |
| 2026-06-08 | 2026-06-09 | 300411.SZSE | 金盾股份 | 20.048 | -5.5556 | deep_oversold | ordinary | active | volume_contracting_three_day | no_limit_source | 4.3178 | 5.7273 | 8.4264 | 1.4684 | 1.9612 | 3.0646 |
| 2026-05-20 | 2026-05-21 | 688055.SSE | 龙腾光电 | 20.0445 | -3.2328 | neutral | low_close | contracted_low_turnover_proxy | multi_day_contraction | no_limit_source | 0.5139 | 0.5436 | 0.6236 | 0.6864 | 0.718 | 0.8173 |
| 2026-06-29 | 2026-06-30 | 300269.SZSE | 联建光电 | 20.0436 | -2.9598 | low_repair | ordinary | normal | mixed_volume | no_limit_source | 4.1541 | 5.1734 | 3.555 | 1.042 | 1.2586 | 0.8445 |
| 2026-03-13 | 2026-03-16 | 300209.SZSE | 行云科技 | 20.0431 | -0.8547 | high_momentum | low_close | normal | multi_day_contraction | no_limit_source | 1.5822 | 1.332 | 1.4522 | 0.7362 | 0.6173 | 0.685 |
| 2026-06-10 | 2026-06-11 | 300894.SZSE | 火星人 | 20.0422 | 2.9316 | neutral | ordinary | hot | volume_rising_three_day | no_limit_source | 2.24 | 1.8411 | 0.8047 | 2.2789 | 2.0284 | 0.9417 |
| 2026-03-04 | 2026-03-05 | 300708.SZSE | 聚灿光电 | 20.0384 | -1.4178 | neutral | balanced_mid_close | active | mixed_volume | no_limit_source | 7.7151 | 13.4067 | 6.9545 | 1.1565 | 2.0916 | 1.0901 |
| 2026-06-30 | 2026-07-01 | 688553.SSE | 汇宇制药 | 20.0376 | 0.1885 | deep_oversold | balanced_mid_close | normal | mixed_volume | no_limit_source | 1.5065 | 2.2558 | 1.8725 | 1.2246 | 2.0063 | 1.7899 |
| 2026-07-01 | 2026-07-02 | 300163.SZSE | 先锋新材 | 20.0371 | 0.9363 | deep_oversold | compressed_mid_close | contracted | multi_day_contraction | no_limit_source | 2.4217 | 2.5718 | 3.3285 | 0.5119 | 0.5325 | 0.6508 |
| 2026-05-26 | 2026-05-27 | 300291.SZSE | 百纳千成 | 20.0358 | -2.4433 | low_repair | ordinary | contracted | multi_day_contraction | no_limit_source | 2.2107 | 1.828 | 2.0728 | 0.64 | 0.5143 | 0.5791 |
| 2026-04-15 | 2026-04-16 | 300798.SZSE | 锦鸡股份 | 20.0358 | 11.5768 | high_momentum | first_sun_or_strong_close | hot_high_turnover_proxy | volume_rising_three_day | no_limit_source | 26.5131 | 11.4172 | 9.1911 | 2.074 | 0.9152 | 0.7429 |
| 2026-06-30 | 2026-07-01 | 300345.SZSE | 华民股份 | 20.0342 | -3.9474 | neutral | low_close | normal | mixed_volume | touched_but_not_closed_limit | 3.1667 | 4.1352 | 4.1485 | 0.983 | 1.2889 | 1.278 |
| 2026-04-22 | 2026-04-23 | 300590.SZSE | 移为通信 | 20.033 | 2.0185 | neutral | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 1.2397 | 0.6969 | 0.7039 | 1.5369 | 0.8263 | 0.8072 |
| 2026-06-24 | 2026-06-25 | 300650.SZSE | 太龙股份 | 20.0323 | -2.673 | low_repair | ordinary | normal | volume_contracting_three_day | no_limit_source | 3.0365 | 3.6008 | 4.5044 | 0.9552 | 1.0968 | 1.4341 |
| 2026-06-18 | 2026-06-22 | 300561.SZSE | 汇金科技 | 20.0314 | -3.997 | deep_oversold | low_close | normal | volume_contracting_three_day | no_limit_source | None | 3.765 | 4.519 | 0.7653 | 0.7719 | 0.9535 |

### d1_big_down_examples

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-12 | 2026-06-15 | 688662.SSE | 富信科技 | -22.5 | 17.8125 | high_momentum | first_sun_or_strong_close | extreme_high_turnover_proxy | volume_rising_three_day | single_limit_source | 20.2079 | 12.9476 | 8.5255 | 2.1947 | 1.7574 | 1.4347 |
| 2026-04-21 | 2026-04-22 | 688678.SSE | 福立旺 | -22.4918 | -2.6803 | high_momentum | ordinary | active | volume_contracting_three_day | no_limit_source | 7.6044 | 15.0466 | 13.4672 | 1.2787 | 2.6101 | 2.6535 |
| 2026-05-22 | 2026-05-25 | 688168.SSE | 安博通 | -22.3162 | 1.2113 | low_repair | high_close | normal | mixed_volume | no_limit_source | 1.9288 | 2.2234 | 1.5337 | 0.8713 | 0.957 | 0.6489 |
| 2026-05-21 | 2026-05-22 | 301266.SZSE | 宇邦新材 | -21.9357 | -6.7253 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | 4.9879 | 4.1447 | 4.0163 | 1.2461 | 1.0095 | 0.9768 |
| 2026-06-02 | 2026-06-03 | 688479.SSE | 友车科技 | -21.8788 | 1.3709 | neutral | compressed_mid_close | normal_low_turnover_proxy | volume_contracting_three_day | no_limit_source | 0.9071 | 1.1049 | 2.4092 | 0.7533 | 0.9163 | 1.918 |
| 2026-05-27 | 2026-05-28 | 301158.SZSE | 德石股份 | -21.8323 | -3.7719 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 3.3971 | 4.0486 | 4.9032 | 0.5951 | 0.6624 | 0.7659 |
| 2026-06-10 | 2026-06-11 | 301669.SZSE | 高特电子 | -21.1435 | -1.8129 | neutral | intraday_fade | unknown_turnover | volume_history_unknown | no_limit_source | 15.8003 | 21.452 | None | None | None | None |
| 2026-05-28 | 2026-05-29 | 301468.SZSE | 博盈特焊 | -20.9854 | 8.903 | neutral | first_sun_or_strong_close | normal | volume_rising_three_day | no_limit_source | 5.5115 | 4.7442 | 3.188 | 1.1086 | 0.9432 | 0.6068 |
| 2026-06-04 | 2026-06-05 | 300557.SZSE | 理工光科 | -20.8742 | -2.8064 | neutral | ordinary | active | mixed_volume | no_limit_source | 4.8988 | 7.672 | 1.7894 | 1.1628 | 1.9451 | 0.4958 |
| 2026-05-18 | 2026-05-19 | 300818.SZSE | 耐普矿机 | -20.8094 | -4.5271 | low_repair | low_close | active | mixed_volume | no_limit_source | 4.4315 | 4.7417 | 4.3927 | 1.3445 | 1.4579 | 1.4104 |
| 2026-05-29 | 2026-06-01 | 301035.SZSE | 润丰股份 | -20.8037 | -0.8772 | deep_oversold | balanced_mid_close | normal_low_turnover_proxy | volume_rising_three_day | no_limit_source | 0.5451 | 0.3805 | 0.3294 | 0.9546 | 0.6141 | 0.5247 |
| 2026-06-15 | 2026-06-16 | 301178.SZSE | 天亿马 | -20.7165 | 5.4771 | neutral | ordinary | active | mixed_volume | no_limit_source | 5.9179 | 2.916 | 3.4007 | 1.369 | 0.7009 | 0.8081 |
| 2026-05-25 | 2026-05-26 | 301061.SZSE | 匠心家居 | -20.6848 | -2.583 | deep_oversold | low_close | contracted_low_turnover_proxy | multi_day_contraction | no_limit_source | 0.5413 | 1.0012 | 0.7039 | 0.4239 | 0.7852 | 0.5291 |
| 2026-05-25 | 2026-05-26 | 301617.SZSE | 博苑新材 | -20.6517 | -2.0976 | neutral | ordinary | normal | mixed_volume | no_limit_source | 1.5371 | 1.5399 | 1.747 | 0.8015 | 0.7904 | 0.8922 |
| 2026-06-09 | 2026-06-10 | 300920.SZSE | 润阳科技 | -20.2571 | 1.7641 | neutral | high_close | active | mixed_volume | no_limit_source | 4.6817 | 5.3378 | 4.0852 | 1.5364 | 1.8145 | 1.499 |
| 2026-06-05 | 2026-06-08 | 300737.SZSE | 科顺股份 | -20.0225 | 4.7114 | high_momentum | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 12.947 | 15.7265 | 10.6523 | 2.4266 | 3.2683 | 2.6499 |
| 2026-05-18 | 2026-05-19 | 300658.SZSE | 延江股份 | -20.0213 | -1.0016 | deep_oversold | compressed_mid_close | contracted | multi_day_contraction | no_limit_source | 7.2698 | 9.7443 | 10.0921 | 0.6385 | 0.8146 | 0.7842 |
| 2026-05-13 | 2026-05-14 | 300363.SZSE | 博腾股份 | -20.0194 | -2.2328 | low_repair | ordinary | normal | volume_contracting_three_day | no_limit_source | 2.8636 | 3.1247 | 5.1011 | 0.9112 | 0.9678 | 1.6431 |
| 2026-04-08 | 2026-04-09 | 300561.SZSE | 汇金科技 | -20.0141 | 2.9112 | neutral | ordinary | normal | volume_rising_three_day | no_limit_source | 2.4837 | 2.2518 | 2.1726 | 0.8634 | 0.8208 | 0.8194 |
| 2026-05-11 | 2026-05-12 | 301310.SZSE | 鑫宏业 | -20.0063 | 0.3935 | high_momentum | compressed_mid_close | normal | multi_day_contraction | no_limit_source | 3.4236 | 3.153 | 3.0172 | 0.7926 | 0.7455 | 0.7277 |
| 2026-03-16 | 2026-03-17 | 688031.SSE | 星环科技 | -20.0 | 2.0408 | high_momentum | ordinary | normal_high_turnover_proxy | multi_day_contraction | single_limit_source | 12.0911 | 9.5729 | 11.907 | 0.798 | 0.6179 | 0.7311 |
| 2026-07-02 | 2026-07-03 | 688216.SSE | 气派科技 | -20.0 | 20.0 | high_momentum | first_sun_or_strong_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 23.7672 | 12.0085 | 11.27 | 2.6188 | 1.5635 | 1.6399 |
| 2026-07-03 | 2026-07-06 | 688669.SSE | 聚石化学 | -20.0 | 6.5729 | extreme_hot | ordinary | active | volume_contracting_three_day | single_limit_source | 7.0839 | 7.4768 | 8.1709 | 0.9746 | 1.0997 | 1.2079 |
| 2026-06-24 | 2026-06-25 | 688639.SSE | 华恒生物 | -20.0 | -1.9698 | low_repair | low_close | normal | mixed_volume | no_limit_source | 2.4525 | 4.4787 | 2.963 | 0.8781 | 1.6534 | 1.2014 |

### active_source_compressed_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-04-28 | 2026-04-29 | 300209.SZSE | 行云科技 | 20.0141 | 7.5 | high_momentum | first_sun_or_strong_close | active | volume_rising_three_day | single_limit_source | 6.3831 | 4.372 | 4.0992 | 1.0444 | 0.7394 | 0.7039 |
| 2026-06-02 | 2026-06-03 | 688655.SSE | 迅捷兴 | 20.0082 | 4.2662 | deep_oversold | first_sun_or_strong_close | contracted_high_turnover_proxy | multi_day_contraction | single_limit_source | 9.0224 | 6.4618 | 9.9303 | 0.6373 | 0.4352 | 0.6411 |
| 2026-06-17 | 2026-06-18 | 688485.SSE | 九州一轨 | 20.0071 | 8.5155 | neutral | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 5.4131 | 3.4582 | 3.5111 | 1.0482 | 0.7068 | 0.7221 |
| 2026-04-10 | 2026-04-13 | 301667.SZSE | 纳百川 | 20.0044 | 10.3882 | neutral | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 10.2116 | 4.2827 | 7.3517 | 0.9835 | 0.4434 | 0.7553 |
| 2026-03-24 | 2026-03-25 | 300658.SZSE | 延江股份 | 20.0 | 6.3879 | low_repair | first_sun_or_strong_close | contracted_high_turnover_proxy | multi_day_contraction | single_limit_source | 12.7653 | 13.6148 | 20.7731 | 0.5628 | 0.5917 | 0.8069 |
| 2026-04-30 | 2026-05-06 | 688813.SSE | 泰金新能 | 20.0 | 6.8579 | extreme_hot | first_sun_or_strong_close | active | volume_rising_three_day | multi_limit_source | 2.7953 | 2.519 | 2.5636 | 0.8978 | 0.8147 | 0.7996 |
| 2026-05-15 | 2026-05-18 | 301666.SZSE | 大普微 | 20.0 | 7.7655 | high_momentum | first_sun_or_strong_close | active | multi_day_contraction | multi_limit_source | 1.7334 | 2.0064 | 1.6007 | 0.6355 | 0.7215 | 0.6565 |
| 2026-06-15 | 2026-06-16 | 300964.SZSE | 本川智能 | 19.9958 | 7.9143 | neutral | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 5.5661 | 5.7727 | 5.4346 | 0.612 | 0.6371 | 0.5897 |
| 2026-06-15 | 2026-06-16 | 301176.SZSE | 逸豪新材 | 19.9941 | 20.0 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | multi_limit_source | 4.6944 | 8.8913 | 6.099 | 0.5572 | 1.3591 | 1.0688 |
| 2026-06-16 | 2026-06-17 | 300735.SZSE | 光弘科技 | 19.9903 | 4.4904 | low_repair | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 2.6843 | 1.9524 | 1.9527 | 0.9167 | 0.7016 | 0.7306 |
| 2026-03-06 | 2026-03-09 | 688158.SSE | 优刻得 | 19.9894 | 4.504 | neutral | first_sun_or_strong_close | contracted_high_turnover_proxy | multi_day_contraction | single_limit_source | 10.2654 | 9.271 | 7.1264 | 0.7343 | 0.6384 | 0.4741 |
| 2026-05-12 | 2026-05-13 | 301666.SZSE | 大普微 | 19.9643 | 4.9524 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 1.3088 | 1.9421 | 1.9099 | 0.5839 | 0.8255 | 0.896 |
| 2026-06-10 | 2026-06-11 | 688146.SSE | 中船特气 | 19.7945 | 16.4181 | extreme_hot | first_sun_or_strong_close | active | mixed_volume | multi_limit_source | 3.1989 | 2.8605 | 4.0152 | 0.8146 | 0.8029 | 1.1133 |
| 2026-06-12 | 2026-06-15 | 301377.SZSE | 鼎泰高科 | 17.4539 | 9.3783 | extreme_hot | first_sun_or_strong_close | active | mixed_volume | single_limit_source | 1.5229 | 0.942 | 1.0066 | 1.0182 | 0.6862 | 0.7337 |
| 2026-05-07 | 2026-05-08 | 301666.SZSE | 大普微 | 16.7785 | 14.058 | high_momentum | first_sun_or_strong_close | active | mixed_volume | single_limit_source | 1.6495 | 1.3585 | 1.1348 | 0.8944 | 0.7813 | 0.7898 |
| 2026-05-07 | 2026-05-08 | 300736.SZSE | 百邦科技 | 16.0139 | 3.1094 | high_momentum | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 7.6376 | 6.7533 | 5.8112 | 0.6559 | 0.5533 | 0.4619 |
| 2026-06-16 | 2026-06-17 | 300939.SZSE | 秋田微 | 15.9106 | 9.0267 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | volume_rising_three_day | single_limit_source | 9.345 | 4.9294 | 3.8762 | 1.0235 | 0.5694 | 0.4625 |
| 2026-06-15 | 2026-06-16 | 688143.SSE | 长盈通 | 15.222 | 5.6983 | high_momentum | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 7.3764 | 7.3186 | 8.344 | 0.688 | 0.591 | 0.636 |
| 2026-06-18 | 2026-06-22 | 688478.SSE | 晶升股份 | 15.2163 | 20.006 | high_momentum | first_sun_or_strong_close | contracted | mixed_volume | single_limit_source | None | 7.3509 | 6.9916 | 0.5907 | 1.1334 | 1.1024 |
| 2026-05-06 | 2026-05-07 | 301373.SZSE | 凌玮科技 | 14.8543 | 5.0612 | extreme_hot | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 5.5131 | 4.998 | 4.9675 | 0.7286 | 0.6542 | 0.6637 |
| 2026-06-08 | 2026-06-09 | 688323.SSE | 瑞华泰 | 14.0306 | 5.5537 | low_repair | first_sun_or_strong_close | normal | volume_rising_three_day | multi_limit_source | 7.0426 | 4.3784 | 4.3549 | 0.8971 | 0.557 | 0.5106 |
| 2026-06-24 | 2026-06-25 | 688545.SSE | 兴福电子 | 14.0136 | 5.2004 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 4.4871 | 4.2669 | 5.6691 | 0.8768 | 0.8477 | 1.0618 |
| 2026-05-22 | 2026-05-25 | 688820.SSE | 盛合晶微 | 13.8228 | 6.3066 | extreme_hot | first_sun_or_strong_close | normal | multi_day_contraction | multi_limit_source | 1.9779 | 2.3068 | 2.3965 | 0.6972 | 0.7828 | 0.7561 |
| 2026-05-08 | 2026-05-11 | 688820.SSE | 盛合晶微 | 13.7795 | 6.7227 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 1.6255 | 1.6595 | 1.9919 | 0.7111 | 0.7486 | 0.9363 |

### active_source_compressed_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-01 | 2026-07-02 | 688056.SSE | 莱伯泰科 | -16.1765 | 5.3447 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 7.6172 | 6.3161 | 8.476 | 0.8107 | 0.6956 | 0.9678 |
| 2026-06-22 | 2026-06-23 | 688056.SSE | 莱伯泰科 | -14.1278 | 10.56 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | volume_contracting_three_day | single_limit_source | 8.1624 | None | 8.7877 | 0.9758 | 1.0614 | 1.2842 |
| 2026-04-17 | 2026-04-20 | 688308.SSE | 欧科亿 | -13.9737 | 9.6154 | high_momentum | first_sun_or_strong_close | active | volume_rising_three_day | single_limit_source | 6.1926 | 5.216 | 4.8081 | 0.9295 | 0.8703 | 0.8384 |
| 2026-06-25 | 2026-06-26 | 301013.SZSE | 利和兴 | -13.9442 | 13.2889 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 31.5791 | 27.9079 | 30.0469 | 0.9704 | 0.8931 | 0.9951 |
| 2026-06-11 | 2026-06-12 | 688146.SSE | 中船特气 | -13.665 | 19.7945 | extreme_hot | first_sun_or_strong_close | hot | volume_rising_three_day | multi_limit_source | 4.306 | 3.1989 | 2.8605 | 0.9929 | 0.8146 | 0.8029 |
| 2026-05-20 | 2026-05-21 | 688661.SSE | 和林微纳 | -11.9479 | 4.8039 | high_momentum | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 3.7718 | 3.174 | 2.7954 | 0.7873 | 0.6969 | 0.6221 |
| 2026-06-11 | 2026-06-12 | 688610.SSE | 埃科光电 | -11.7269 | 12.6495 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 3.0683 | 2.7694 | 4.0494 | 0.7428 | 0.715 | 0.9826 |
| 2026-04-01 | 2026-04-02 | 688031.SSE | 星环科技 | -11.3898 | 5.2814 | deep_oversold | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 7.6758 | 6.364 | 6.1616 | 0.6904 | 0.5652 | 0.5412 |
| 2026-03-25 | 2026-03-26 | 300658.SZSE | 延江股份 | -11.2671 | 20.0 | high_momentum | first_sun_or_strong_close | contracted_high_turnover_proxy | multi_day_contraction | single_limit_source | 17.2703 | 12.7653 | 13.6148 | 0.6472 | 0.5628 | 0.5917 |
| 2026-07-01 | 2026-07-02 | 300319.SZSE | 麦捷科技 | -11.1635 | 7.3237 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 26.93 | 19.3891 | 25.2716 | 0.936 | 0.7057 | 0.9119 |
| 2026-05-11 | 2026-05-12 | 688268.SSE | 华特气体 | -10.8686 | 11.6702 | extreme_hot | first_sun_or_strong_close | active | mixed_volume | multi_limit_source | 7.8222 | 5.8457 | 9.1681 | 0.9166 | 0.7265 | 1.0817 |
| 2026-05-26 | 2026-05-27 | 301599.SZSE | 理奇智能 | -10.8546 | 4.2025 | neutral | first_sun_or_strong_close | contracted | multi_day_contraction | single_limit_source | 6.8267 | 8.0461 | 9.0748 | 0.6904 | 0.7973 | 0.8074 |
| 2026-05-28 | 2026-05-29 | 300263.SZSE | 隆华科技 | -10.5224 | 6.5183 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 6.7654 | 6.849 | 8.8052 | 0.9499 | 0.9932 | 1.2441 |
| 2026-05-28 | 2026-05-29 | 688419.SSE | 耐科装备 | -10.3989 | 4.75 | high_momentum | first_sun_or_strong_close | normal | volume_contracting_three_day | single_limit_source | 3.5214 | 4.3566 | 6.3739 | 0.9362 | 1.1965 | 1.7659 |
| 2026-05-20 | 2026-05-21 | 301511.SZSE | 德福科技 | -10.3558 | 9.1742 | extreme_hot | first_sun_or_strong_close | normal | multi_day_contraction | single_limit_source | 4.7704 | 3.9843 | 4.2308 | 0.7884 | 0.6933 | 0.7586 |
| 2026-06-30 | 2026-07-01 | 688662.SSE | 富信科技 | -10.3214 | 7.6923 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 13.1565 | 16.3017 | 11.8276 | 0.9859 | 1.2716 | 0.8024 |
| 2026-05-28 | 2026-05-29 | 688699.SSE | 明微电子 | -10.3133 | 6.7491 | high_momentum | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 6.2308 | 4.6821 | 4.7286 | 1.049 | 0.8264 | 0.8743 |
| 2026-05-14 | 2026-05-15 | 001267.SZSE | 汇绿生态 | -10.0745 | 9.9937 | high_momentum | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 12.717 | 8.1144 | 10.5127 | 0.9972 | 0.6549 | 0.8349 |
| 2026-03-03 | 2026-03-04 | 603616.SSE | 韩建河山 | -10.0367 | 9.9596 | high_momentum | first_sun_or_strong_close | contracted_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 8.5591 | 10.425 | 17.1211 | 0.4882 | 0.6344 | 1.0292 |
| 2026-05-28 | 2026-05-29 | 002918.SZSE | 蒙娜丽莎 | -10.0267 | 10.0 | high_momentum | first_sun_or_strong_close | contracted | volume_contracting_three_day | crowded_active_source | 5.3847 | 8.8751 | 12.8185 | 0.5322 | 0.9913 | 1.461 |
| 2026-05-25 | 2026-05-26 | 300042.SZSE | 朗科科技 | -10.0251 | 5.4086 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 19.1602 | 18.1327 | 23.4725 | 0.9047 | 0.8863 | 1.1208 |
| 2026-07-01 | 2026-07-02 | 605006.SSE | 山东玻纤 | -10.0183 | 3.651 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 13.4491 | 15.4181 | 3.3673 | 0.962 | 1.1091 | 0.2133 |
| 2026-05-19 | 2026-05-20 | 603178.SSE | 圣龙股份 | -10.0168 | 10.0 | high_momentum | first_sun_or_strong_close | normal_high_turnover_proxy | volume_contracting_three_day | crowded_active_source | 14.3023 | 13.7477 | 20.6532 | 0.8257 | 0.8929 | 1.3947 |
| 2026-05-28 | 2026-05-29 | 603067.SSE | 振华股份 | -10.0103 | 3.838 | neutral | first_sun_or_strong_close | normal | mixed_volume | multi_limit_source | 4.1284 | 6.2782 | 5.2638 | 0.959 | 1.5019 | 1.1681 |

### deep_low_close_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-18 | 2026-06-22 | 300561.SZSE | 汇金科技 | 20.0314 | -3.997 | deep_oversold | low_close | normal | volume_contracting_three_day | no_limit_source | None | 3.765 | 4.519 | 0.7653 | 0.7719 | 0.9535 |
| 2026-06-08 | 2026-06-09 | 688711.SSE | 宏微科技 | 20.0067 | -11.3033 | deep_oversold | panic_low_close | normal | volume_contracting_three_day | no_limit_source | 5.7851 | 6.1382 | 7.2972 | 0.7911 | 0.7964 | 0.9244 |
| 2026-05-29 | 2026-06-01 | 301236.SZSE | 软通动力 | 20.0061 | -6.3227 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 2.217 | 2.8335 | 2.184 | 1.1503 | 1.4068 | 0.9788 |
| 2026-06-08 | 2026-06-09 | 688596.SSE | 正帆科技 | 20.0053 | -7.2372 | deep_oversold | panic_low_close | contracted | mixed_volume | single_limit_source | 2.7406 | 4.5441 | 2.873 | 0.6692 | 1.0981 | 0.7303 |
| 2026-07-02 | 2026-07-03 | 300779.SZSE | 惠城环保 | 20.004 | -0.9625 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.3948 | 2.5664 | 1.9804 | 0.9169 | 1.0388 | 0.7941 |
| 2026-04-07 | 2026-04-08 | 300475.SZSE | 香农芯创 | 20.0032 | 1.2297 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 1.9364 | 1.8369 | 2.0148 | 0.6348 | 0.5687 | 0.5968 |
| 2026-06-01 | 2026-06-02 | 301419.SZSE | 阿莱德 | 20.0 | -2.4008 | deep_oversold | low_close | normal | volume_contracting_three_day | no_limit_source | 3.888 | 5.9026 | 6.7086 | 1.0482 | 1.6138 | 1.9649 |
| 2026-06-26 | 2026-06-29 | 300204.SZSE | 舒泰神 | 20.0 | -7.619 | deep_oversold | panic_low_close | normal | volume_contracting_three_day | touched_but_not_closed_limit | 4.5563 | 5.922 | 7.4727 | 0.9037 | 1.1637 | 1.482 |
| 2026-06-26 | 2026-06-29 | 301520.SZSE | 万邦医药 | 20.0 | -2.7663 | deep_oversold | low_close | normal_low_turnover_proxy | volume_contracting_three_day | no_limit_source | 0.4039 | 0.6724 | 0.6856 | 0.9597 | 1.6077 | 1.6097 |
| 2026-06-12 | 2026-06-15 | 688170.SSE | 德龙激光 | 20.0 | -3.8216 | deep_oversold | intraday_fade | contracted | multi_day_contraction | no_limit_source | 7.1703 | 6.1155 | 8.1468 | 0.666 | 0.5597 | 0.7011 |
| 2026-04-02 | 2026-04-03 | 300812.SZSE | 易天股份 | 20.0 | -0.4425 | deep_oversold | low_close | normal | multi_day_contraction | no_limit_source | 7.505 | 4.3674 | 4.9699 | 0.8416 | 0.4519 | 0.4943 |
| 2026-06-03 | 2026-06-04 | 300897.SZSE | 山科智能 | 20.0 | -3.866 | deep_oversold | intraday_fade | normal | volume_contracting_three_day | no_limit_source | 2.4752 | 4.3484 | 4.1049 | 1.3989 | 2.7325 | 2.8071 |
| 2026-06-26 | 2026-06-29 | 300436.SZSE | 广生堂 | 20.0 | -3.173 | deep_oversold | low_close | contracted | volume_contracting_three_day | no_limit_source | 3.0283 | 3.9045 | 4.403 | 0.7339 | 0.9635 | 1.0804 |
| 2026-07-02 | 2026-07-03 | 301379.SZSE | 天山电子 | 20.0 | -7.8721 | deep_oversold | panic_low_close | normal | mixed_volume | single_limit_source | 7.7866 | 13.7742 | 10.8552 | 1.0215 | 1.7998 | 1.5632 |
| 2026-03-03 | 2026-03-04 | 688525.SSE | 佰维存储 | 19.9986 | -8.6231 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | 2.3163 | 1.5405 | 1.4985 | 1.2098 | 0.7349 | 0.6788 |
| 2026-06-08 | 2026-06-09 | 688409.SSE | 富创精密 | 19.9985 | -5.6022 | deep_oversold | panic_low_close | normal | multi_day_contraction | touched_but_not_closed_limit | 1.3441 | 1.322 | 1.4499 | 0.7778 | 0.7272 | 0.8075 |
| 2026-07-03 | 2026-07-06 | 301191.SZSE | 菲菱科思 | 19.9982 | 0.5991 | deep_oversold | intraday_fade | active_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 8.0298 | 5.4705 | 9.5889 | 1.5373 | 1.0802 | 1.9405 |
| 2026-03-26 | 2026-03-27 | 688068.SSE | 热景生物 | 19.9982 | -3.9599 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 1.262 | 1.9177 | 1.6172 | 0.783 | 1.1901 | 1.0869 |
| 2026-06-08 | 2026-06-09 | 688500.SSE | 慧辰股份 | 19.9955 | -8.5892 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 5.5977 | 3.2812 | 4.9909 | 0.8959 | 0.4869 | 0.7185 |
| 2026-06-03 | 2026-06-04 | 301468.SZSE | 博盈特焊 | 19.9954 | -2.7397 | deep_oversold | low_close | active | volume_contracting_three_day | no_limit_source | 7.2311 | 8.7889 | 12.049 | 1.3997 | 1.7277 | 2.6366 |
| 2026-06-26 | 2026-06-29 | 688336.SSE | 三生国健 | 19.9952 | -6.8315 | deep_oversold | panic_low_close | active | volume_contracting_three_day | no_limit_source | 1.0946 | 1.365 | 1.7231 | 1.404 | 1.8657 | 2.5127 |
| 2026-06-08 | 2026-06-09 | 301222.SZSE | 浙江恒威 | 19.9934 | -10.5217 | deep_oversold | panic_low_close | normal | volume_contracting_three_day | touched_but_not_closed_limit | 3.898 | 4.7779 | 7.145 | 1.0435 | 1.2745 | 1.9424 |
| 2026-06-18 | 2026-06-22 | 300085.SZSE | 银之杰 | 19.9926 | -3.2999 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | None | 4.7377 | 5.3471 | 0.5568 | 0.6937 | 0.7917 |
| 2026-06-04 | 2026-06-05 | 301193.SZSE | 家联科技 | 19.9901 | -3.5322 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 2.9125 | 3.5061 | 3.4914 | 0.6335 | 0.6977 | 0.6484 |

### deep_low_close_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-21 | 2026-05-22 | 301266.SZSE | 宇邦新材 | -21.9357 | -6.7253 | deep_oversold | panic_low_close | normal | volume_rising_three_day | no_limit_source | 4.9879 | 4.1447 | 4.0163 | 1.2461 | 1.0095 | 0.9768 |
| 2026-05-27 | 2026-05-28 | 301158.SZSE | 德石股份 | -21.8323 | -3.7719 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 3.3971 | 4.0486 | 4.9032 | 0.5951 | 0.6624 | 0.7659 |
| 2026-05-29 | 2026-06-01 | 300427.SZSE | 红相股份 | -19.978 | -4.1053 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 5.4871 | 5.7296 | 4.9696 | 0.6784 | 0.6913 | 0.6 |
| 2026-05-21 | 2026-05-22 | 688543.SSE | 国科军工 | -18.1112 | -4.106 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 2.8415 | 3.4888 | 2.3098 | 0.8693 | 1.0621 | 0.6925 |
| 2026-03-31 | 2026-04-01 | 301302.SZSE | 华如科技 | -15.5513 | -3.8743 | deep_oversold | low_close | contracted | multi_day_contraction | single_limit_source | 6.6178 | 6.1947 | 5.9014 | 0.5019 | 0.4685 | 0.439 |
| 2026-04-02 | 2026-04-03 | 301137.SZSE | 哈焊华通 | -14.1086 | -3.7449 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 4.3682 | 6.3194 | 5.8102 | 0.5299 | 0.7687 | 0.6998 |
| 2026-07-01 | 2026-07-02 | 300394.SZSE | 天孚通信 | -12.0105 | -5.8412 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 6.1669 | 4.8478 | 5.9949 | 1.1508 | 0.8667 | 1.07 |
| 2026-05-29 | 2026-06-01 | 300965.SZSE | 恒宇信通 | -11.9799 | -4.9547 | deep_oversold | low_close | contracted | multi_day_contraction | multi_limit_source | 4.9325 | 4.2719 | 4.6867 | 0.6724 | 0.5715 | 0.6323 |
| 2026-04-29 | 2026-04-30 | 688280.SSE | 精进电动 | -11.8644 | -19.9612 | deep_oversold | panic_low_close | contracted | volume_contracting_three_day | no_limit_source | 4.5668 | 7.2423 | 9.6888 | 0.872 | 1.1086 | 1.5118 |
| 2026-05-12 | 2026-05-13 | 301310.SZSE | 鑫宏业 | -11.8581 | -20.0063 | deep_oversold | panic_low_close | active | volume_rising_three_day | no_limit_source | 4.6202 | 3.4236 | 3.153 | 1.1665 | 0.7926 | 0.7455 |
| 2026-03-20 | 2026-03-23 | 688282.SSE | 理工导航 | -11.5982 | -2.9718 | deep_oversold | low_close | normal | multi_day_contraction | no_limit_source | 1.2946 | 1.1568 | 1.4347 | 0.8096 | 0.7001 | 0.8418 |
| 2026-07-01 | 2026-07-02 | 300502.SZSE | 新易盛 | -11.5644 | -5.1796 | deep_oversold | panic_low_close | normal | mixed_volume | no_limit_source | 4.014 | 4.9047 | 4.0302 | 1.0167 | 1.2874 | 1.1652 |
| 2026-06-25 | 2026-06-26 | 300854.SZSE | 中兰环保 | -11.5436 | -5.5767 | deep_oversold | panic_low_close | contracted | volume_contracting_three_day | no_limit_source | 6.4862 | 7.2889 | 9.0123 | 0.6742 | 0.7383 | 0.9201 |
| 2026-06-25 | 2026-06-26 | 688635.SSE | 长进光子 | -11.0082 | -1.5854 | deep_oversold | low_close | contracted | multi_day_contraction | single_limit_source | 4.1925 | 3.8893 | 4.3283 | 0.5377 | 0.4967 | 0.5095 |
| 2026-06-26 | 2026-06-29 | 301486.SZSE | 致尚科技 | -10.4275 | -4.4769 | deep_oversold | intraday_fade | contracted | mixed_volume | touched_but_not_closed_limit | 5.7163 | 8.498 | 5.0343 | 0.7146 | 1.0351 | 0.5837 |
| 2026-06-01 | 2026-06-02 | 605056.SSE | 咸亨国际 | -10.4245 | -2.7077 | deep_oversold | low_close | contracted | multi_day_contraction | touched_but_not_closed_limit | 2.2418 | 2.5118 | 2.0557 | 0.6411 | 0.6959 | 0.5265 |
| 2026-06-24 | 2026-06-25 | 300652.SZSE | 雷迪克 | -10.3737 | -1.8718 | deep_oversold | low_close | contracted | mixed_volume | no_limit_source | 1.8825 | 3.1896 | 3.0421 | 0.6592 | 1.0083 | 0.9526 |
| 2026-03-20 | 2026-03-23 | 688685.SSE | 迈信林 | -10.3001 | -3.468 | deep_oversold | low_close | contracted | multi_day_contraction | no_limit_source | 1.1963 | 1.3111 | 1.2965 | 0.5348 | 0.5571 | 0.5326 |
| 2026-07-03 | 2026-07-06 | 688323.SSE | 瑞华泰 | -10.1978 | -6.7241 | deep_oversold | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 12.7586 | 12.0159 | 18.378 | 0.9642 | 0.8559 | 1.268 |
| 2026-06-26 | 2026-06-29 | 300328.SZSE | 宜安科技 | -10.1597 | -8.0494 | deep_oversold | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 10.4276 | 12.4801 | 7.789 | 0.9665 | 1.075 | 0.6581 |
| 2026-05-20 | 2026-05-21 | 600208.SSE | 衢州发展 | -10.1124 | -10.101 | deep_oversold | panic_low_close | normal | mixed_volume | crowded_active_source | 5.0919 | 0.191 | 0.2867 | 1.1302 | 0.0379 | 0.0509 |
| 2026-06-05 | 2026-06-08 | 001330.SZSE | 博纳影业 | -10.0386 | -5.3593 | deep_oversold | panic_low_close | normal_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 10.5549 | 9.3652 | 12.0683 | 0.9175 | 0.7401 | 0.9418 |
| 2026-03-20 | 2026-03-23 | 600331.SSE | 宏达股份 | -10.026 | -4.5963 | deep_oversold | low_close | normal | mixed_volume | no_limit_source | 4.027 | 4.9151 | 2.7479 | 0.926 | 1.121 | 0.5951 |
| 2026-06-26 | 2026-06-29 | 603201.SSE | 常润股份 | -10.0193 | -10.0 | deep_oversold | panic_low_close | active | volume_rising_three_day | single_limit_source | 4.8522 | 3.6394 | 2.682 | 1.4697 | 0.9958 | 0.6623 |

### deep_low_first_sun_winners

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-09 | 2026-06-10 | 300264.SZSE | 佳创视讯 | 20.0514 | 6.7215 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 5.1708 | 4.0646 | 5.214 | 1.0162 | 0.7876 | 0.9678 |
| 2026-06-29 | 2026-06-30 | 300270.SZSE | 中威电子 | 20.0185 | 4.8356 | low_repair | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 5.7753 | 5.0746 | 5.1593 | 1.764 | 1.565 | 1.5948 |
| 2026-06-15 | 2026-06-16 | 300780.SZSE | 德恩精工 | 20.0149 | 7.6769 | low_repair | first_sun_or_strong_close | normal | volume_rising_three_day | no_limit_source | 5.4833 | 4.6207 | 3.8374 | 1.0819 | 0.9083 | 0.7136 |
| 2026-06-22 | 2026-06-23 | 300085.SZSE | 银之杰 | 20.0 | 19.9926 | low_repair | first_sun_or_strong_close | active_high_turnover_proxy | sudden_volume_expansion | no_limit_source | 14.4863 | None | 4.7377 | 2.0061 | 0.5568 | 0.6937 |
| 2026-05-22 | 2026-05-25 | 300779.SZSE | 惠城环保 | 20.0 | 3.9177 | deep_oversold | ordinary | normal | volume_rising_three_day | no_limit_source | 2.794 | 2.1698 | 1.3659 | 1.0972 | 0.8623 | 0.5363 |
| 2026-06-22 | 2026-06-23 | 300961.SZSE | 深水海纳 | 19.982 | 2.5854 | low_repair | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.791 | 2.1754 | 3.0426 | 1.2073 | 0.9195 | 1.2553 |
| 2026-06-30 | 2026-07-01 | 300287.SZSE | 飞利信 | 19.9377 | 3.2154 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.3926 | 2.091 | 2.3204 | 1.2314 | 1.112 | 1.2038 |
| 2026-07-01 | 2026-07-02 | 300071.SZSE | 福石控股 | 19.891 | 4.8571 | low_repair | ordinary | active | volume_rising_three_day | no_limit_source | 5.4977 | 3.9769 | 2.5523 | 1.5926 | 1.1237 | 0.7337 |
| 2026-07-01 | 2026-07-02 | 300069.SZSE | 金利华电 | 18.021 | 4.7754 | deep_oversold | first_sun_or_strong_close | normal_high_turnover_proxy | high_turnover_proxy_latest | no_limit_source | 13.2436 | 5.0929 | 7.9838 | 1.151 | 0.4337 | 0.6658 |
| 2026-06-18 | 2026-06-22 | 301160.SZSE | 翔楼新材 | 17.5569 | 6.3122 | deep_oversold | first_sun_or_strong_close | hot | mixed_volume | no_limit_source | None | 2.7319 | 2.8695 | 2.0825 | 1.2772 | 1.3863 |
| 2026-06-15 | 2026-06-16 | 301312.SZSE | 智立方 | 17.0059 | 16.4818 | deep_oversold | first_sun_or_strong_close | normal | volume_rising_three_day | single_limit_source | 5.1071 | 2.3443 | 1.667 | 1.4429 | 0.7209 | 0.4848 |
| 2026-06-02 | 2026-06-03 | 688498.SSE | 源杰科技 | 16.413 | 12.4339 | deep_oversold | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 4.4124 | 2.944 | 2.9377 | 1.6837 | 1.2119 | 1.2006 |
| 2026-06-15 | 2026-06-16 | 300870.SZSE | 欧陆通 | 16.1198 | 17.2892 | deep_oversold | first_sun_or_strong_close | active | volume_rising_three_day | no_limit_source | 5.809 | 3.9633 | 2.1879 | 1.7368 | 1.3241 | 0.7603 |
| 2026-06-15 | 2026-06-16 | 300450.SZSE | 先导智能 | 15.9624 | 3.4232 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.9796 | 3.9579 | 2.5389 | 0.8311 | 1.1 | 0.7005 |
| 2026-06-23 | 2026-06-24 | 688685.SSE | 迈信林 | 15.4667 | 4.2149 | low_repair | ordinary | active | volume_rising_three_day | no_limit_source | 4.0777 | 3.8283 | None | 1.466 | 1.4579 | 1.4085 |
| 2026-06-12 | 2026-06-15 | 688332.SSE | 中科蓝讯 | 15.1874 | 4.1068 | deep_oversold | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 4.0421 | 3.6605 | 1.6891 | 1.6739 | 1.6744 | 0.7945 |
| 2026-06-15 | 2026-06-16 | 688343.SSE | 云天励飞 | 15.0415 | 4.4637 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.347 | 2.8517 | 2.2785 | 0.8584 | 1.0442 | 0.8116 |
| 2026-06-15 | 2026-06-16 | 301280.SZSE | 珠城科技 | 14.7805 | 2.4232 | low_repair | first_sun_or_strong_close | normal | multi_day_contraction | no_limit_source | 1.1133 | 1.127 | 0.9848 | 0.8333 | 0.8304 | 0.7459 |
| 2026-06-16 | 2026-06-17 | 688200.SSE | 华峰测控 | 14.7733 | 6.3725 | deep_oversold | ordinary | normal | volume_contracting_three_day | no_limit_source | 1.9497 | 2.3228 | 2.8053 | 1.3414 | 1.7717 | 2.2023 |
| 2026-06-12 | 2026-06-15 | 301259.SZSE | 艾布鲁 | 14.6643 | 3.8056 | deep_oversold | ordinary | normal | mixed_volume | no_limit_source | 1.9152 | 2.0034 | 1.218 | 1.1869 | 1.2946 | 0.7354 |
| 2026-06-12 | 2026-06-15 | 300902.SZSE | 国安达 | 14.3432 | 3.6831 | low_repair | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 2.1529 | 2.1755 | 1.577 | 0.8587 | 0.9057 | 0.6551 |
| 2026-06-16 | 2026-06-17 | 688720.SSE | 艾森股份 | 13.2075 | 2.4013 | deep_oversold | ordinary | normal | mixed_volume | no_limit_source | 5.9839 | 4.3495 | 6.7734 | 1.2286 | 0.9376 | 1.0299 |
| 2026-06-15 | 2026-06-16 | 301086.SZSE | 鸿富瀚 | 12.9372 | 7.5217 | deep_oversold | first_sun_or_strong_close | active | mixed_volume | no_limit_source | 3.633 | 3.2949 | 3.2515 | 1.822 | 1.7813 | 1.9577 |
| 2026-03-24 | 2026-03-25 | 301529.SZSE | 福赛科技 | 11.6071 | 2.4393 | deep_oversold | first_sun_or_strong_close | normal | mixed_volume | no_limit_source | 1.2436 | 1.5082 | 1.231 | 0.8871 | 1.0578 | 0.7818 |

### risk_flag_losers

| trade_date | next_trade_date | vt_symbol | name | d1_return | ret_d | position_group | price_action_group | volume_turnover_group | pre_volume_pattern | active_source_group | turnover_proxy | lag1_turnover_proxy | lag2_turnover_proxy | vol_vs_ma20 | lag1_vol_vs_ma20 | lag2_vol_vs_ma20 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-06-11 | 2026-06-12 | 688549.SSE | 中巨芯 | -17.3045 | 19.9601 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 10.4127 | 9.2868 | 8.275 | 1.5255 | 1.6442 | 1.8157 |
| 2026-04-24 | 2026-04-27 | 300766.SZSE | 每日互动 | -16.4439 | -3.7571 | neutral | intraday_fade | extreme_high_turnover_proxy | sudden_volume_expansion | no_limit_source | 41.8559 | 15.2041 | 18.0943 | 2.8175 | 1.0567 | 1.3118 |
| 2026-07-01 | 2026-07-02 | 688056.SSE | 莱伯泰科 | -16.1765 | 5.3447 | extreme_hot | first_sun_or_strong_close | normal | mixed_volume | single_limit_source | 7.6172 | 6.3161 | 8.476 | 0.8107 | 0.6956 | 0.9678 |
| 2026-07-01 | 2026-07-02 | 688409.SSE | 富创精密 | -16.0053 | -3.5624 | extreme_hot | intraday_fade | hot | mixed_volume | multi_limit_source | 5.1743 | 4.3073 | 5.2773 | 1.2342 | 1.0456 | 1.4204 |
| 2026-07-01 | 2026-07-02 | 688260.SSE | 昀冢科技 | -15.1568 | -9.2361 | high_momentum | intraday_fade | active_high_turnover_proxy | volume_rising_three_day | multi_limit_source | 9.8143 | 8.5734 | 6.1901 | 1.0881 | 0.8702 | 0.6944 |
| 2026-06-23 | 2026-06-24 | 688367.SSE | 工大高科 | -14.9392 | 6.861 | high_momentum | intraday_fade | extreme_high_turnover_proxy | volume_rising_three_day | single_limit_source | 23.0217 | 7.8487 | 2.8233 | 4.1931 | 1.6371 | 0.6803 |
| 2026-06-03 | 2026-06-04 | 300561.SZSE | 汇金科技 | -14.5596 | -12.3922 | neutral | panic_low_close | hot_high_turnover_proxy | volume_contracting_three_day | no_limit_source | 11.4424 | 11.7957 | 12.1601 | 2.5436 | 2.708 | 3.2086 |
| 2026-07-01 | 2026-07-02 | 688233.SSE | 神工股份 | -14.4995 | 11.2583 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | volume_contracting_three_day | single_limit_source | 13.5522 | 13.316 | 13.6503 | 1.3441 | 1.5866 | 1.8558 |
| 2026-06-22 | 2026-06-23 | 688056.SSE | 莱伯泰科 | -14.1278 | 10.56 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | volume_contracting_three_day | single_limit_source | 8.1624 | None | 8.7877 | 0.9758 | 1.0614 | 1.2842 |
| 2026-06-25 | 2026-06-26 | 301013.SZSE | 利和兴 | -13.9442 | 13.2889 | extreme_hot | first_sun_or_strong_close | active_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 31.5791 | 27.9079 | 30.0469 | 0.9704 | 0.8931 | 0.9951 |
| 2026-06-05 | 2026-06-08 | 300835.SZSE | 龙磁科技 | -13.9052 | 12.5393 | extreme_hot | first_sun_or_strong_close | hot_high_turnover_proxy | high_turnover_proxy_latest | single_limit_source | 10.2011 | 4.3542 | 6.2562 | 1.519 | 0.6993 | 1.0027 |
| 2026-06-11 | 2026-06-12 | 688146.SSE | 中船特气 | -13.665 | 19.7945 | extreme_hot | first_sun_or_strong_close | hot | volume_rising_three_day | multi_limit_source | 4.306 | 3.1989 | 2.8605 | 0.9929 | 0.8146 | 0.8029 |
| 2026-03-02 | 2026-03-03 | 300395.SZSE | 菲利华 | -13.1815 | -3.5884 | high_momentum | low_close | active_high_turnover_proxy | volume_contracting_three_day | single_limit_source | 10.3427 | 14.5507 | 14.9167 | 1.3348 | 2.0127 | 2.2349 |
| 2026-06-26 | 2026-06-29 | 301468.SZSE | 博盈特焊 | -12.8778 | -3.8806 | low_repair | intraday_fade | active_high_turnover_proxy | volume_rising_three_day | single_limit_source | 13.7872 | 10.6593 | 8.2393 | 1.3565 | 1.0928 | 0.8983 |
| 2026-06-05 | 2026-06-08 | 300069.SZSE | 金利华电 | -12.8612 | -7.8659 | extreme_hot | panic_low_close | active_high_turnover_proxy | high_turnover_proxy_latest | multi_limit_source | 29.4598 | 36.0185 | 31.604 | 1.405 | 1.6642 | 1.5619 |
| 2026-06-26 | 2026-06-29 | 300819.SZSE | 聚杰微纤 | -12.7707 | -3.4909 | high_momentum | intraday_fade | hot_high_turnover_proxy | volume_rising_three_day | single_limit_source | 11.0733 | 8.088 | 5.0446 | 2.0242 | 1.4777 | 1.0345 |
| 2026-05-20 | 2026-05-21 | 688409.SSE | 富创精密 | -12.7573 | 7.2041 | extreme_hot | first_sun_or_strong_close | hot | volume_contracting_three_day | touched_but_not_closed_limit | 2.3862 | 2.3071 | 2.6392 | 1.3712 | 1.3927 | 1.7037 |
| 2026-06-25 | 2026-06-26 | 688026.SSE | 洁特生物 | -12.7316 | -6.9522 | high_momentum | panic_low_close | hot | volume_contracting_three_day | touched_but_not_closed_limit | 7.3984 | 8.7929 | 9.3804 | 2.3416 | 2.9414 | 3.6824 |
| 2026-04-09 | 2026-04-10 | 301201.SZSE | 诚达药业 | -12.6226 | -15.5378 | high_momentum | panic_low_close | extreme_high_turnover_proxy | high_turnover_proxy_latest | touched_but_not_closed_limit | 23.4075 | 16.9504 | 18.5675 | 2.8729 | 2.0548 | 2.4726 |
| 2026-07-03 | 2026-07-06 | 300932.SZSE | 三友联众 | -12.6149 | 4.7244 | high_momentum | intraday_fade | extreme_high_turnover_proxy | volume_rising_three_day | touched_but_not_closed_limit | 15.8563 | 11.3499 | 8.9887 | 3.892 | 3.3858 | 3.1387 |
| 2026-04-03 | 2026-04-07 | 301008.SZSE | 宏昌科技 | -12.4852 | 2.8564 | high_momentum | intraday_fade | extreme_high_turnover_proxy | volume_contracting_three_day | multi_limit_source | 25.6325 | 25.0232 | 36.7838 | 4.2426 | 5.2217 | 10.4327 |
| 2026-03-02 | 2026-03-03 | 300277.SZSE | 汽轮科技 | -12.3179 | -4.3772 | high_momentum | low_close | active | volume_contracting_three_day | single_limit_source | 6.2512 | 7.8555 | 11.6629 | 1.0442 | 1.2806 | 2.2239 |
| 2026-05-28 | 2026-05-29 | 688055.SSE | 龙腾光电 | -12.1771 | -3.9007 | high_momentum | low_close | active | volume_contracting_three_day | single_limit_source | 2.0148 | 2.8108 | 4.1679 | 1.2732 | 1.779 | 2.8853 |
| 2026-05-29 | 2026-06-01 | 688172.SSE | 燕东微 | -11.886 | -7.5595 | extreme_hot | panic_low_close | hot | mixed_volume | single_limit_source | 2.3331 | 2.3731 | 1.7728 | 1.3051 | 1.3639 | 1.1508 |

## Notes

- stock_daily_bars 没有历史换手率字段；turnover_proxy 使用 D 日成交额 / 当前 market_cap 近似，只能作为成交活跃度代理，不是严格点位历史换手率。
- volume_ratio/amount_ratio 使用 D 日成交量或成交额相对前 20 日均值，前 20 日均值不包含 D 日。
- 所有正向/负向 flag 都只使用 D 日收盘前可见信息；D+1 只作为标签。
- 主样本剔除北交所、ST/退市、非连续 D+1、新股/除权或数据异常导致的超涨跌幅样本。
