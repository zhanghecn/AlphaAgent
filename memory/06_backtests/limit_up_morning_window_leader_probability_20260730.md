# Morning-Window (09:30-11:00) Leader-Probability Scoring

## Boundary

- 状态：`ok`；研究版本 `morning-window-leader-probability-v1`。
- 本报告只读 `stock_events`/`stock_daily_bars`，不修改 `limit-up-core-abc-v2`、C、实时推荐或账户。
- 龙头概率 = 入选 A 因子五分位正样本率的 effect 加权平均；透明可解释，非黑盒模型。
- `eventual_peak` 仅作 label；评分只用 D-1 收盘可观测因子，无未来函数。
- 窗口 `09:30:00`~`11:00:00`；连板阈值 `>= 3`；train 前 `10` 个月。

## Coverage

- 结算范围：`2025-06-27` 至 `2026-07-30`。
- 全部首板：11134；9:30-11:00 窗口：6628；train：3860；test：2768。
- 输入指纹：`c11ef9a49f11c3e4`。

## Sample Balance

- 正样本（连板 >= 阈值）：352；负样本：6276；正样本率：5.31%。

## Train Selected Factors (A 组，封板前可观测)

| 因子 | AUC | 效应强度 | 方向 | 权重 |
|---|---:|---:|---|---:|
| prior_return_5d_pct | 0.5515 | 5.1500 | higher | 21.90% |
| prior_turnover_ratio_5d | 0.5539 | 5.3900 | higher | 22.92% |
| prior_3d_up_days | 0.5550 | 5.5000 | higher | 23.38% |
| float_market_cap | 0.4252 | 7.4800 | lower | 31.80% |

## Holdout Validation

- test 样本：2768；正样本：93。
- 评分 AUC：`0.5692`；基线正样本率：`3.36%`。
- top20% 正样本率：`5.23%`；bottom20%：`2.53%`；lift：`1.5566`。
- **锁定状态**：`NOT_LOCKED`。
- **locked 因子**（train 入选 + test 锁定 + 月度稳定）：（无）。

## Monthly Stability

| 因子 | 方向集合 | 是否翻转(unstable) |
|---|---|---|
| prior_return_5d_pct | higher,lower | 是 |
| prior_turnover_ratio_5d | higher,lower | 是 |
| prior_change_pct | higher,lower | 是 |
| prior_3d_cum_return_pct | higher,lower | 是 |
| prior_3d_max_change_pct | higher,lower | 是 |
| prior_3d_up_days | higher,lower | 是 |
| prior_day_change_pct | higher,lower | 是 |
| prior_day_body_pct | higher,lower | 是 |
| prior_day_range_pct | higher,lower | 是 |
| prior_day_close_position | higher,lower | 是 |
| prior_limit_count_126 | higher,lower | 是 |
| prior_limit_count_20 | higher,lower | 是 |
| days_since_prior_limit | higher,lower | 是 |
| float_market_cap | higher,lower | 是 |
| turnover_rate | higher,lower | 是 |

## Probability Score Formula

- 对新首板样本：查每个 locked A 因子所在五分位的正样本率，按 train effect 权重加权平均 = 龙头概率。
- 排序：按龙头概率降序即每日推荐顺序。
- 注意：评分为「封板首板中成龙头的概率」；实盘还需前置「会不会封板」的候选筛选。

## Group-B Quality Factors (封板时刻质量，仅诊断)

- `first_limit_hour`: AUC `0.4764`，效应 `2.3600`，方向 lower
- `is_early_seal`: AUC `0.5234`，效应 `2.3400`，方向 higher
- `open_times`: AUC `0.4770`，效应 `2.3000`，方向 lower
- `seal_to_turnover_ratio`: AUC `0.5862`，效应 `8.6200`，方向 higher
- `is_one_word_board`: AUC `0.5038`，效应 `0.3800`，方向 higher
- `is_clean_seal`: AUC `0.5223`，效应 `2.2300`，方向 higher
- `first_limit_time_bucket`（分类）：
  - morning_0930_1000: 样本 4110，正样本率 5.69%
  - morning_1000_1100: 样本 2517，正样本率 4.69%
  - morning_1100_1130: 样本 1，正样本率 0.00%

## Decision

- 本报告为只读概率评分证据，``execution_valid`` 恒为 False，不产出可执行信号，不改变正式门或实时推荐。
- locked 因子仅作研究线索；任何上线须经独立自然前向验证与用户审批。

## Evidence Boundary

- JSON 含校准表、holdout 明细与月度明细；Markdown 只显示汇总，避免事后最高被误读为可交易规则。
- 样本仅 13 个月、holdout 约 4 个月，统计功效有限；结论不可外推为全周期普适规律。
