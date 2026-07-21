# AlphaAgent 第一浪概念内动态排名轨迹研究

研究状态：`no_stable_rank_trajectory_feature`；验证边界：`reused_history_not_validation`。
正式低吸胜率、收益、复利：`null`。以下只描述已查看历史中的身份轨迹。

## Coverage

- 已决第二浪标签：`1183`；轨迹面板 `1183`，完整特征 `1183`。
- 轨迹剔除：`0`；每日龙头行 `13196`，成员日行 `679375`。
- 候选特征：`0`；只能进入新的前向块。

## 新信息覆盖

| 数据 | 日期数 | 范围 | 标签重合日 | 是否读取 |
| --- | ---: | --- | ---: | --- |
| 个股资金流 | 27 | 2026-06-12..2026-07-17 | 0 | `False` |
| 板块资金流 | 21 | 2026-06-18..2026-07-17 | 0 | `False` |
| 成员快照 | 5 | 2026-07-13..2026-07-17 | 0 | `False` |
| 板块资金快照 | 5 | 2026-07-13..2026-07-17 | 0 | `False` |

这些数据与 2023-2025 决策日重合为 0，因此没有硬拼到历史特征。

## 单特征轨迹

方向只由 block 1-3 决定；所有时间块都已被历史研究查看过。

| 特征 | 方向 | 开发 AUC | B1 | B2 | B3 | B4 | B5 | 稳定块 | 状态 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `leader_decision_turnover_strength_pct` | `lower` | 0.5454 | 0.4875 | 0.5585 | 0.5779 | 0.5137 | 0.5903 | 3 | `exploratory_not_selected` |
| `leader_decision_strength_pct` | `lower` | 0.5409 | 0.5302 | 0.5252 | 0.5675 | 0.4676 | 0.5219 | 1 | `exploratory_not_selected` |
| `leader_strength_std_pct` | `lower` | 0.5376 | 0.5307 | 0.5307 | 0.5350 | 0.4823 | 0.4338 | 0 | `exploratory_not_selected` |
| `leader_trough_to_decision_strength_change_pct_points` | `lower` | 0.5326 | 0.5086 | 0.5129 | 0.5544 | 0.4473 | 0.4255 | 1 | `exploratory_not_selected` |
| `leader_peak_to_decision_strength_change_pct_points` | `lower` | 0.5318 | 0.5080 | 0.5223 | 0.5702 | 0.4399 | 0.4751 | 1 | `exploratory_not_selected` |
| `leader_path_median_turnover_strength_pct` | `lower` | 0.5290 | 0.4806 | 0.5769 | 0.5184 | 0.4662 | 0.5799 | 2 | `exploratory_not_selected` |
| `positive_breadth_trough_to_decision_change_pct_points` | `lower` | 0.5230 | 0.4848 | 0.5243 | 0.5561 | 0.5393 | 0.4822 | 1 | `exploratory_not_selected` |
| `top3_concentration_trough_to_decision_change_pct_points` | `higher` | 0.5214 | 0.4461 | 0.5419 | 0.5650 | 0.5102 | 0.4776 | 1 | `exploratory_not_selected` |
| `leader_decision_gap_to_top3_mean_pct` | `higher` | 0.5186 | 0.5260 | 0.5219 | 0.4895 | 0.4917 | 0.4505 | 0 | `exploratory_not_selected` |
| `leader_path_top1_share_pct` | `lower` | 0.5183 | 0.4973 | 0.5246 | 0.5375 | 0.5357 | 0.4934 | 0 | `exploratory_not_selected` |
| `leader_recovery_top3_share_pct` | `higher` | 0.5163 | 0.5113 | 0.5177 | 0.4989 | 0.4768 | 0.4726 | 0 | `exploratory_not_selected` |
| `leader_decision_gap_to_best_other_pct` | `higher` | 0.5162 | 0.5302 | 0.5175 | 0.4814 | 0.4893 | 0.4403 | 0 | `exploratory_not_selected` |
| `leader_top3_streak_to_decision_sessions` | `higher` | 0.5160 | 0.5134 | 0.5200 | 0.4970 | 0.4847 | 0.4818 | 0 | `exploratory_not_selected` |
| `strong_breadth_trough_to_decision_change_pct_points` | `lower` | 0.5154 | 0.5708 | 0.5698 | 0.4282 | 0.5892 | 0.4400 | 3 | `exploratory_not_selected` |
| `leader_worst_strength_pct` | `higher` | 0.5145 | 0.5146 | 0.5123 | 0.5072 | 0.5168 | 0.4606 | 0 | `exploratory_not_selected` |
| `leader_path_top3_share_pct` | `higher` | 0.5116 | 0.5238 | 0.5121 | 0.4860 | 0.4623 | 0.4946 | 0 | `exploratory_not_selected` |
| `leader_trough_strength_pct` | `lower` | 0.5020 | 0.5234 | 0.5019 | 0.4950 | 0.5130 | 0.5527 | 1 | `exploratory_not_selected` |
| `leader_peak_strength_pct` | `higher` | 0.5007 | 0.4952 | 0.5016 | 0.5186 | 0.4650 | 0.4471 | 0 | `exploratory_not_selected` |

## 冻结轨迹分类

| Scope | 轨迹 | 样本 | 续浪 | 续浪比例 |
| --- | --- | ---: | ---: | ---: |
| `pooled` | `lost_leadership` | 909 | 516 | 56.7657% |
| `pooled` | `mixed_trajectory` | 194 | 114 | 58.7629% |
| `pooled` | `persistent_leader` | 80 | 44 | 55.0000% |
| `block_1` | `lost_leadership` | 175 | 85 | 48.5714% |
| `block_1` | `mixed_trajectory` | 19 | 9 | 47.3684% |
| `block_1` | `persistent_leader` | 9 | 6 | 66.6667% |
| `block_2` | `lost_leadership` | 184 | 104 | 56.5217% |
| `block_2` | `mixed_trajectory` | 46 | 29 | 63.0435% |
| `block_2` | `persistent_leader` | 17 | 10 | 58.8235% |
| `block_3` | `lost_leadership` | 165 | 95 | 57.5758% |
| `block_3` | `mixed_trajectory` | 47 | 26 | 55.3191% |
| `block_3` | `persistent_leader` | 17 | 9 | 52.9412% |
| `block_4` | `lost_leadership` | 230 | 128 | 55.6522% |
| `block_4` | `mixed_trajectory` | 39 | 22 | 56.4103% |
| `block_4` | `persistent_leader` | 22 | 11 | 50.0000% |
| `block_5` | `lost_leadership` | 155 | 104 | 67.0968% |
| `block_5` | `mixed_trajectory` | 43 | 28 | 65.1163% |
| `block_5` | `persistent_leader` | 15 | 8 | 53.3333% |

## 个股轨迹例子

| 类型 | 股票 | 概念 | 决策日 | 全程 Top3 | 恢复 Top3 | 决策强度 | 连续 Top3 | 领先第二名 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 持续/续浪 | 杭州解百 `600814.SSE` | 退税商店 | 2023-05-25 | 85.7143% | 100.0000% | 90.9091% | 7.0000 | -0.6950% |
| 持续/续浪 | 亿道信息 `001314.SZSE` | 混合现实 | 2023-12-26 | 100.0000% | 100.0000% | 93.7500% | 4.0000 | -7.1984% |
| 持续/续浪 | 海德股份 `000567.SZSE` | 钒电池 | 2024-10-15 | 100.0000% | 100.0000% | 100.0000% | 9.0000 | 13.0569% |
| 持续/续浪 | 润达医疗 `603108.SSE` | SPD概念 | 2025-02-14 | 100.0000% | 100.0000% | 100.0000% | 4.0000 | 5.4425% |
| 持续/续浪 | 富临运业 `002357.SZSE` | 北斗导航 | 2025-07-09 | 88.8889% | 100.0000% | 97.2222% | 7.0000 | -1.9982% |
| 持续/终止 | 力鼎光电 `605118.SSE` | 安防概念 | 2023-06-06 | 80.0000% | 100.0000% | 100.0000% | 4.0000 | 17.1483% |
| 持续/终止 | 乐通股份 `002319.SZSE` | HJT电池 | 2024-03-19 | 100.0000% | 100.0000% | 100.0000% | 7.0000 | 2.6692% |
| 持续/终止 | 贝因美 `002570.SZSE` | 乳业 | 2024-10-23 | 92.8571% | 100.0000% | 100.0000% | 9.0000 | 20.5108% |
| 持续/终止 | 润建股份 `002929.SZSE` | 多模态AI | 2025-02-19 | 88.8889% | 100.0000% | 100.0000% | 8.0000 | 44.9762% |
| 持续/终止 | 兴业股份 `603928.SSE` | 光刻机(胶) | 2025-07-01 | 100.0000% | 100.0000% | 100.0000% | 5.0000 | 3.4037% |
| 丢失地位 | 中国电影 `600977.SSE` | 中字头 | 2023-05-09 | 0.0000% | 0.0000% | 87.5000% | 0.0000 | -11.6549% |
| 丢失地位 | 宏英智能 `001266.SZSE` | 新型工业化 | 2023-11-27 | 0.0000% | 0.0000% | 85.7143% | 0.0000 | -51.4970% |
| 丢失地位 | 华映科技 `000536.SZSE` | 柔性屏(折叠屏) | 2024-09-10 | 0.0000% | 0.0000% | 82.1429% | 0.0000 | -97.4359% |
| 丢失地位 | XD华胜天 `600410.SSE` | 新型工业化 | 2025-02-07 | 0.0000% | 0.0000% | 36.3636% | 0.0000 | -12.7480% |
| 丢失地位 | 南山控股 `002314.SZSE` | 统一大市场 | 2025-11-03 | 0.0000% | 0.0000% | 30.3030% | 0.0000 | -30.3959% |

## 边界

- all five historical blocks were already viewed in the prior identity study
- current concept memberships create survivorship bias
- local fund flow and membership snapshots overlap zero label dates
- free EastMoney historical fund-flow probes expose recent data only and were not imported
- trajectory continuation share is not low-suction trade win rate
- no wave-2 path, minute bar, timing regime or trade return is a predictor

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-multi-wave-rank-trajectory-study --format markdown
```
