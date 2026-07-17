# Low-suction Free Forward Capture Evidence - 2026-07-16

## Conclusion

免费前向证据采集链路已经实现并部署到本地容器。`2026-07-16` 的 BaoStock 捕获形成
1 个完整证券状态 source-date scope、3,192 行；东方财富共享目录仍因
`BK1677/BK1678/BK1679` 失败，但 21:33 同日重试已按 exact-ID manifest 形成低吸专用
`concept_tradable=478/478` scope、67,403 行。因此成员和证券前向状态均为
`accumulating=1日`，低吸继续 `blocked_by_data_quality`，`formal_metrics=null`。双 scope
细节见 `low_suction_forward_tradable_scope_20260716.md`。

这不是回测结果，也不代表已经取得三年历史。系统只会从未来完整捕获的源交易日 S
开始，一对一映射到下一可靠交易日 D。

## Implemented Contract

- 东方财富共享成员：一个板块异常或空响应仍让整次同步失败。低吸专用可交易 scope
  仅允许 exact-ID 非交易类排除，并在独立事务中保存本次完整分页成员。
- BaoStock 证券状态：同一次登录读取证券主表和 `query_all_stock(S)`；只保留 S 日仍
  在市的沪深主板，同时保留 ST、退市整理和停牌记录。
- 有效日期：S 必须是可靠完整交易日，观察时间必须位于 S 日 15:00 之后且不晚于下一
  可靠交易日 D 的 09:25；不按自然日推算周末或节假日。
- 来源隔离：东方财富前向成员不与 Tushare DC 历史成员合并；BaoStock 前向状态不与
  `query_history_k_data_plus` 重建历史合并。
- 严格门禁：单一来源至少累计 720 个有效交易日和 1,095 个自然日后才可成为 strict
  coverage；此前状态为 `accumulating` 或不可用。

## Runtime Evidence

- API 容器重建后为 `healthy`；schema 和默认 registry 使用
  `ensure_sync_schema()` 完成协调。
- `eod_1900` 和 `eod_finalize_2130` 都按顺序包含
  `sync_sector_list -> sync_sector_members -> sync_stock_sector_memberships ->
  sync_low_suction_security_snapshot`。
- 当日股票日线有 5,531 个不同代码，满足 3,000 只可靠日门槛。
- BaoStock 首次 `query_all_stock(2026-07-16)` 空响应并失败；19:06 重试返回完整主板范围，
  原子写入 3,192 行和 1 个 complete scope，其中 ST/退市整理 151 行、停牌 1 行。
- 东方财富板块清单刷新 1,486 行。成员作业仍只在 `BK1677/BK1678/BK1679` 失败；
  共享目录没有冒充完整。低吸专用 scope 排除 20 个精确非交易类 ID 后覆盖 478/478
  个板块，未使用 2026-07-10 旧成员补洞。
- 19:00 是主采，21:30 是完整链路补偿重试；同日成功重试会原子替换，不会累加重复行。

## Coverage Audit

`low-suction-data-quality-v3` 在 `2026-07-16` 的真实库存：

| 数据 | 模式 | 交易日 | 范围 | 结论 |
| --- | --- | ---: | --- | --- |
| 股票日线 | strict | 800 | 2023-03-28..2026-07-16 | 已达历史门槛 |
| 概念指数 | strict | 800 | 2023-03-28..2026-07-16 | 已达历史门槛 |
| 概念成员 | current_proxy + forward accumulating | 3 + 1 source day | 2026-07-14..2026-07-16 | 前向未达三年门槛 |
| 证券状态 | accumulating | 1 | 2026-07-16 | 前向已启动，未达三年门槛 |

阻断项仍是：

- `historical_concept_membership`
- `historical_security_status`
- `candidate_minute_paths`

## Verification

```bash
uv run --group server pytest \
  tests/alphaagent/services/low_suction \
  tests/alphaagent/test_data_sync_schedule.py \
  tests/alphaagent/test_market_snapshot_repository.py -q
# 385 passed

uvx ruff check alphaagent/server/services/low_suction \
  alphaagent/server/services/market_snapshot_repository.py \
  tests/alphaagent/services/low_suction

uv run python -m compileall -q alphaagent
git diff --check
```

后续只观察完整 scope 的自然积累。不得把现有三天成员代理或 BaoStock 事后查询复制到
过去日期，也不得在 strict 历史未达标前计算胜率、复利或选择生产低吸规则。
