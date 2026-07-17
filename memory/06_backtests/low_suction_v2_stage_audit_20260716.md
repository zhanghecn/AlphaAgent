# AlphaAgent 低吸 V2 阶段审计

协议：`low-suction-research-v2`\
协议哈希：`sha256:3c96f32f6693b657e230ac5f63dfc8d392098b6d64a8b86f549d7082c36d878c`\
结论：`blocked_by_data_quality`\
正式绩效：`null`

## Qualification Targets

- 锁定留出闭合交易：至少 300 笔。
- 费用后交易胜率：严格大于 `60%`。
- 10 万元现金账户复利：严格大于 `60%`。
- 最大回撤：不差于 `-10%`。
- 利润因子：大于 1；双倍成本复利仍为正。
- 物质环境：样本覆盖至少 20 日；至少两个环境真实交易。
- 每个交易环境：至少 30 笔、胜率严格大于 `60%`、复利为正、回撤不差于 `-10%`。
- 其他环境可冻结为 `cash`，但必须零成交、零收益、零回撤，不能伪报胜率。

环境适配只允许“同一冻结入场规则 + 一张交易/空仓策略表”，不为 GOLD、SILVER 分别
训练不同买点条件。

## Current Stages

| Stage | Status | Evidence |
| --- | --- | --- |
| Concept cycle | `completed` | 800 日，冻结 `breakout_trend`，未读留出价格 |
| Top3 identity | `blocked` | 三种非加权算法已实现；历史 strict 成员/证券均 0 日；成员和证券前向各 accumulating 1 日 |
| Minute state | `blocked` | 冻结候选对 0，覆盖 0 |
| Validation | `blocked` | frozen pipeline `null`，留出访问次数 0 |

当前成员只有 3 个 `current_proxy` 日期，不能进入 Top3 选择。当前市场环境库存为：
`GOLD/NORMAL=395`、`SILVER/NORMAL=67`、`SILVER/DANGER=30`、
`NEUTRAL/NORMAL=23`、`GOLD/DANGER=4`。

免费前向库存单独计数：共享成员快照仍只是 current proxy；低吸专用成员已有
`2026-07-16` 一个完整 `concept_tradable` scope、67,403 行，BaoStock 证券状态同日有
一个完整 source-date scope、3,192 行。前向日不能回填过去，累计到 720 个有效交易日
和 1,095 个自然日前仍不等于三年 strict 历史。

## Reproduce

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-audit --format json
```
