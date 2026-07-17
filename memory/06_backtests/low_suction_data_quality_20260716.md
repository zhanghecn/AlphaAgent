# AlphaAgent 低吸研究数据质量审计

数据截止日：2026-07-15\
研究版本：`low-suction-data-quality-v2`\
结论：`blocked_by_data_quality`\
证据层级：`membership_proxy`

正式胜率、复利、利润因子和回撤：`null`。当前输入未通过严格历史研究门禁，
任何代理样本只能用于发现假设，不能用于选择生产规则或承诺未来收益。

## Blocking Gaps

- `historical_concept_membership`：历史概念成员
- `historical_security_status`：历史证券状态
- `candidate_minute_paths`：候选分钟路径

## Core Coverage

| Input | Mode | Rows | Entities | Trade days | Range | Coverage |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 股票日线 | `strict` | 4,288,952 | 5,675 | 799 | 2023-03-28..2026-07-15 | 92.2090% |
| 概念指数 | `strict` | 333,871 | 498 | 799 | 2023-03-28..2026-07-15 | 99.7567% |
| 概念成员 | `current_proxy` | 211,782 | 5,610 | 2 | 2026-07-14..2026-07-15 | 100.0000% |
| 证券状态 | `unavailable` | 0 | 0 | 0 | - | 0.0000% |
| 金银手指 | `point_in_time_derived` | 518 | 5 | 518 | 2024-05-28..2026-07-15 | 100.0000% |

股票日线可靠窗口为 `799` 个交易日、`1,205` 个自然日，已经通过 720 个交易日和
1,095 个自然日门槛。可靠日横截面为 5,101..5,532 只股票；只有满足每日至少
`3,000` 只股票、且不晚于已收盘截止日的日期计入可靠窗口。2026-07-16 午间已写入
5,531 只股票的盘中日 K，但研究覆盖仍截止 2026-07-15。股票回补和时点保护证据见
`low_suction_stock_history_backfill_20260716.md`。

## Concept Evidence

- 当前题材概念：`498` 个。
- 官方概念指数：`eastmoney.board_kline`；已建指数 `498` 个。
- 截止日内原始概念指数日期：`859` 天，范围 `2022-12-26..2026-07-15`。
- 动态有效概念分母为 `371..495`；每日至少 300 个且覆盖不低于 90%。
- 达到动态横截面门槛：`799` 天，范围 `2023-03-28..2026-07-15`，
  最低覆盖 `99.7567%`。
- `concept_index_history` 已解除；回补和动态主升证据见
  `low_suction_concept_index_backfill_20260716.md`。
- 原始成员快照：`3` 天。
- 按盘后快照只能次日使用后：`2` 天。
- 当前成员不能回填历史；盘后 D 日快照不能解释 D 日盘中。

## Supporting Coverage

| Input | Rows | Entities | Trade days | Range | Research use |
| --- | ---: | ---: | ---: | --- | --- |
| 1 分钟线 | 1,045,389 | 1,709 | 105 | 2026-01-20..2026-07-15 | 候选定向覆盖，非全市场连续 |
| 龙虎榜 | 1,096 | 348 | 45 | 2026-05-13..2026-07-15 | 近端分层，不证明自然人身份 |
| 竞价 | 9,121 | 3,041 | 3 | 2026-07-13..2026-07-15 | 仅前向近端 |
| 个股资金流 | 7,095 | 3,326 | 25 | 2026-06-12..2026-07-15 | 仅近端特征 |
| 板块资金流 | 56,487 | 994 | 19 | 2026-06-18..2026-07-15 | 仅近端特征 |
| 盘中概念强度 | 75,748 | 426 | 1 | 2026-07-15..2026-07-15 | 仅前向点时证据 |

## Market-Timing Labels

- `GOLD/DANGER`：4 天
- `GOLD/NORMAL`：395 天
- `NEUTRAL/NORMAL`：23 天
- `SILVER/DANGER`：30 天
- `SILVER/NORMAL`：66 天

金银手指覆盖可用于代理样本分层，但不能弥补概念成员、历史证券状态和
候选分钟路径缺口，也不能预设它必然提高低吸收益。

## Source Findings

- `current_eastmoney_members`：`membership_proxy`；当前成员关系不能回填到历史交易日
- `tushare_dc_member`：`candidate_historical_membership_unconfigured`；官方 `dc_member`
  支持按 `BKxxxx.DC` 和交易日查询历史成分，但本地没有 token，三年起点、完整性和
  D-1 滞后尚未实测（https://tushare.pro/document/2?doc_id=363）
- `tushare_ths_member`：`not_strict_historical_membership`；官方明确不能查询历史成分，
  且 in_date/out_date 标记为“暂无”（https://tushare.pro/document/2?doc_id=261）
- `baostock_security_history`：`reconstructed_only`；可重建证券主表和逐日
  `tradestatus/isST`，但没有已核验的历史发布时间承诺，不能计入严格证券状态覆盖。

`dc_member` 的来源对照、精确 BK 映射和三天成员动态检验见
`low_suction_historical_membership_source_research_20260716.md`。它是下一步探测对象，
不是已经解除的门禁。

BaoStock 主表与本地数据的专项比对见
`low_suction_security_master_audit_20260716.md`。三年窗内退市的 94 只主板股全部有本地
日线，当前没有发现这一维度的价格样本幸存者偏差；但本地上市/退市日期仍为 0，逐日
ST/停牌有效期也仍为 0，所以 `historical_security_status` 不变。

## Current Decision

当前不能计算或发布正式低吸胜率与复利。股票和概念指数的三年日线门槛都已通过，
但 `membership_proxy` 日线探索仍只用于缩小待验证的事件家族。最终规则必须取得
点时概念成员、历史 ST/退市/上市状态，并在重建候选后补齐分钟路径再重新验证。

## Reproduce

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format json
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format markdown
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli security-master-audit --format json
```
