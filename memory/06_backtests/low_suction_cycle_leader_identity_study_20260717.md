# AlphaAgent D-1 周期龙头身份比较

结论：`no_stable_proxy_identity`\
候选池：`event_candidate_pool_proxy`，不是历史完整概念成员\
代理选择：`null`\
正式选择：`null`\
周期/动态候选行/身份账本行：`53/3781/11343`\
是否读取低吸收益：`false`

## 身份指标

| Mode | Segment | Sessions | Top3 | Ret N | Retention | Strong N | Lead | Hit <=5 | Capacity | Market Top1 | Return Top1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cycle_relative_strength` | `all` | 463 | 1389 | 1200 | 87.9167% | 1323 | 6.0000 | 49.1308% | 85.6012% | 72.3542% | 66.5227% |
| `cycle_relative_strength` | `block_1` | 119 | 357 | 321 | 88.7850% | 357 | 6.0000 | 46.7787% | 68.9076% | 65.5462% | 45.3782% |
| `cycle_relative_strength` | `block_2` | 145 | 435 | 381 | 90.2887% | 435 | 6.0000 | 45.0575% | 90.3448% | 73.7931% | 64.8276% |
| `cycle_relative_strength` | `block_3` | 98 | 294 | 249 | 83.9357% | 294 | 5.0000 | 53.4014% | 96.9388% | 70.4082% | 94.8980% |
| `cycle_relative_strength` | `block_4` | 48 | 144 | 123 | 83.7398% | 144 | 4.0000 | 59.0278% | 93.7500% | 75.0000% | 75.0000% |
| `cycle_relative_strength` | `block_5` | 53 | 159 | 126 | 90.4762% | 93 | 6.0000 | 48.3871% | 81.7610% | 84.9057% | 58.4906% |
| `cycle_relative_strength` | `development` | 362 | 1086 | 951 | 88.1178% | 1086 | 6.0000 | 47.8821% | 85.0829% | 70.1657% | 66.5746% |
| `cycle_relative_strength` | `validation` | 101 | 303 | 249 | 87.1486% | 237 | 4.0000 | 54.8523% | 87.4587% | 80.1980% | 66.3366% |
| `market_recognition_lexicographic` | `all` | 463 | 1389 | 1200 | 90.4167% | 1323 | 6.0000 | 49.3575% | 85.5292% | 71.9222% | 57.8834% |
| `market_recognition_lexicographic` | `block_1` | 119 | 357 | 321 | 91.9003% | 357 | 6.0000 | 48.1793% | 68.6275% | 67.2269% | 45.3782% |
| `market_recognition_lexicographic` | `block_2` | 145 | 435 | 381 | 90.2887% | 435 | 6.0000 | 45.7471% | 89.8851% | 71.0345% | 57.2414% |
| `market_recognition_lexicographic` | `block_3` | 98 | 294 | 249 | 90.7631% | 294 | 5.0000 | 53.7415% | 97.2789% | 62.2449% | 69.3878% |
| `market_recognition_lexicographic` | `block_4` | 48 | 144 | 123 | 88.6179% | 144 | 4.5000 | 54.8611% | 93.7500% | 89.5833% | 70.8333% |
| `market_recognition_lexicographic` | `block_5` | 53 | 159 | 126 | 88.0952% | 93 | 6.0000 | 48.3871% | 82.3899% | 86.7925% | 54.7170% |
| `market_recognition_lexicographic` | `development` | 362 | 1086 | 951 | 90.9569% | 1086 | 6.0000 | 48.7109% | 84.8987% | 67.4033% | 56.6298% |
| `market_recognition_lexicographic` | `validation` | 101 | 303 | 249 | 88.3534% | 237 | 5.0000 | 52.3207% | 87.7888% | 88.1188% | 62.3762% |
| `recognition_consensus` | `all` | 446 | 1338 | 1134 | 90.2116% | 1272 | 5.0000 | 50.7862% | 85.2765% | 71.3004% | 61.4350% |
| `recognition_consensus` | `block_1` | 117 | 351 | 312 | 91.9872% | 351 | 6.0000 | 49.0028% | 68.6610% | 66.6667% | 44.4444% |
| `recognition_consensus` | `block_2` | 139 | 417 | 360 | 90.0000% | 417 | 6.0000 | 47.4820% | 89.6882% | 72.6619% | 58.2734% |
| `recognition_consensus` | `block_3` | 90 | 270 | 219 | 90.8676% | 270 | 4.0000 | 56.2963% | 97.4074% | 63.3333% | 85.5556% |
| `recognition_consensus` | `block_4` | 47 | 141 | 117 | 86.3248% | 141 | 4.0000 | 56.0284% | 93.6170% | 76.5957% | 74.4681% |
| `recognition_consensus` | `block_5` | 53 | 159 | 126 | 88.8889% | 93 | 6.0000 | 48.3871% | 82.3899% | 86.7925% | 54.7170% |
| `recognition_consensus` | `development` | 346 | 1038 | 891 | 90.9091% | 1038 | 5.0000 | 50.2890% | 84.5857% | 68.2081% | 60.6936% |
| `recognition_consensus` | `validation` | 100 | 300 | 243 | 87.6543% | 234 | 5.0000 | 52.9915% | 87.6667% | 82.0000% | 64.0000% |

## 五块身份赢家

| Block | Winner | Status |
| ---: | --- | --- |
| 1 | `recognition_consensus` | `winner_selected` |
| 2 | `cycle_relative_strength` | `winner_selected` |
| 3 | `recognition_consensus` | `winner_selected` |
| 4 | `market_recognition_lexicographic` | `winner_selected` |
| 5 | `cycle_relative_strength` | `winner_selected` |

## 模式重合

| Left | Right | Shared sessions | Mean Jaccard |
| --- | --- | ---: | ---: |
| `cycle_relative_strength` | `market_recognition_lexicographic` | 463 | 79.0065% |
| `cycle_relative_strength` | `recognition_consensus` | 446 | 84.3498% |
| `market_recognition_lexicographic` | `recognition_consensus` | 446 | 92.6682% |

## 回调复验门

状态：`not_run_identity_gate_failed`\
身份：`null`\
读取低吸收益：`false`

## 边界

本报告只比较事件候选池内的 D-1 身份，不是严格全成员 Top3。事后阶段龙头只用于覆盖诊断；代理模式不能成为正式策略身份。
