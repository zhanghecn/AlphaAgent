# Low-suction Free Source And Report-board Research - 2026-07-16

## Conclusion

本轮没有找到一个无需账号权限、可立即提供三年东方财富 `BKxxxx` 点时成员和开盘前
证券状态的免费来源。正式结论仍是 `blocked_by_data_quality`，`formal_metrics=null`。

但得到两个可执行研究结论：

1. `BK1677/BK1678/BK1679` 是已经由精确 ID manifest 标记的 `report_event`，不是
   低吸产品要交易的叙事题材。它们不应永久阻塞“可交易题材”前向 scope，但必须通过
   版本化排除清单和独立目录 scope 明示，不能按名称临时删除。
2. Tushare 普通 token 值得先做低成本证券状态探测：`namechange` 有
   `start_date/end_date/ann_date`，`suspend_d` 有逐日停复牌；这可能解决 ST 和停牌，
   但不解决需要 6,000 积分的 DC 历史概念成员。

状态更新：本报告提出的 catalog/tradable 双 scope 已在同日完成实现和真实捕获；当前
结果见 `low_suction_forward_tradable_scope_20260716.md`。本报告的免费历史来源结论仍然
有效，但“尚未修改 scope”的过程状态已被后续证据取代。

## Search Method

- MiniMax `mmx search` 因本机没有凭据返回认证错误 3，未使用搜索摘要形成结论。
- 随后只核验数据商官方文档、仓库内 vendored AkShare 源码、官方 vn.py/XT notebook、
  已安装 BaoStock 客户端源码和东方财富真实接口响应。

## Free Historical Source Matrix

| Source | Historical membership/status | Taxonomy | Cost/access | Decision |
| --- | --- | --- | --- | --- |
| Eastmoney push2 / AkShare `stock_board_concept_cons_em` | 只有当前成员；函数没有日期参数 | 同一 `BKxxxx` | 公开 | 只能前向采集或代理 |
| Eastmoney concept K-line | 有历史指数 K 线，没有历史成员 | 同一 `BKxxxx` | 公开 | 继续作为严格概念指数，不证明 Top3 成员 |
| Tushare `dc_member` | 官方支持按交易日查询历史成分 | `BKxxxx.DC` 可精确去后缀 | 6,000 积分 | 当前唯一同体系三年候选，非免费开箱即用 |
| Tushare `ths_member` | 官方明确不能查询历史成分 | `885xxx.TI` | token | 拒绝 |
| JQData concept members | 可传日期 | 聚宽 `GN...` | 账号/额度 | 删除/改名目录与 BK 无精确历史映射，不能混用 |
| XT/QMT `stocklistchange` | 官方示例支持下载历史成分并按日期查询 | QMT `BKZS`/指数体系 | 券商 QMT 环境；本机未安装 | 可另建数据体系，不能直接拼接现有 BK 指数 |
| BaoStock `query_all_stock(day)` | 可事后查询每日代码、名称、交易状态 | 证券，不含概念 | 免费 | 历史只作 reconstructed；实际当日捕获可前向 strict |
| Tushare `namechange` + `suspend_d` | 历史名称区间、公告日、逐日停复牌 | 证券 | 文档未列 6,000 分门槛，需普通 token 实测 | 免费/低积分证券状态候选 |
| Tushare `stock_st` | 从 2016 年按交易日返回 ST 列表，09:20 更新 | 证券 | 3,000 积分 | 可验证但不是零门槛 |
| Tushare `stock_basic` / `bak_basic` | 上退市日期 / 每日股票历史列表 | 证券 | 2,000 / 5,000 积分 | BaoStock 可覆盖主表；不作为首选付费项 |

官方文档：

- DC 历史成员：https://tushare.pro/document/2?doc_id=363
- THS 当前成员：https://tushare.pro/document/2?doc_id=261
- 股票曾用名：https://tushare.pro/document/2?doc_id=100
- 每日停复牌：https://tushare.pro/document/2?doc_id=214
- 历史 ST 列表：https://tushare.pro/document/2?doc_id=397
- 股票基础信息：https://tushare.pro/document/2?doc_id=25
- 股票历史列表：https://tushare.pro/document/2?doc_id=262

## Three Failed Report Boards

东方财富板块清单在 2026-07-16 仍返回：

| ID | Name | Manifest class | Member endpoint |
| --- | --- | --- | --- |
| `BK1677` | 2025年报预增 | `report_event` | `rc=102` |
| `BK1678` | 2025年报预减 | `report_event` | `rc=102` |
| `BK1679` | 2025年报扭亏 | `report_event` | `rc=102` |

东方财富公开数据中心 `RPT_PUBLIC_OP_NEWPREDICT` 可按 `REPORT_DATE=2025-12-31`
读取公告记录。使用以下事前可解释规则：

```text
IS_LATEST = T
PREDICT_FINANCE_CODE = 004  # 归属于上市公司股东的净利润
PREDICT_TYPE = 预增 / 预减 / 扭亏
SECURITY_TYPE = A股
```

与 2026-07-10 已实际捕获的成员对照：

| ID | Rebuilt A shares | Old captured | Intersection | Missing | Extra | Jaccard |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `BK1677` | 624 | 626 | 624 | 2 | 0 | 0.996805 |
| `BK1678` | 371 | 372 | 371 | 1 | 0 | 0.997312 |
| `BK1679` | 367 | 365 | 365 | 0 | 2 | 0.994550 |

未经 A 股过滤的差异主要是 B 股；`BK1679` 的 2 个 A 股额外项是已经退市的风险股票。
该规则足以证明这三个 ID 是机械财报筛选，而不是叙事题材，但尚不足以把数据中心结果
冒充 push2 的精确同源成员。

## Recommended Scope Design

下一版设计应分离两个 scope：

1. `catalog_scope`：记录完整官方目录、抓取失败 ID、manifest class 和原始来源；允许明确
   标记 provider-unavailable，但不能称为完整成员历史。
2. `tradable_theme_scope`：只对版本化 manifest 明确允许或尚待研究的可交易题材要求成员
   完整。精确标记为 `mechanical_event/style_universe/report_event/ambiguous` 的板块不进入
   Top3 分母，但保留为反证对照。

在改代码前必须新增以下保护测试：

- 排除只按 exact ID + manifest version，不按名称模糊判断。
- 被排除 ID、类别、理由和原目录数量写入 scope raw。
- 未分类 ID 仍然进入待捕获分母，不能因为抓取失败自动变成 excluded。
- narrative theme 抓取失败仍让当天 strict snapshot 失败。
- 目录 scope 与可交易 scope 不得合并成一个“100% 完整率”。

## Method Research Status

本轮来源研究没有改变低吸方法结论：

- 只做主升继续保留；非主升 Top3 的 3/5 日代理均值为负。
- Top3 是用户定义的研究宇宙，不是已证明的超额因子；Rank 4-10 部分结果不弱。
- 后续 V2 已取消所有预设低吸家族；本报告的来源结论不再携带任何买点优先级。
- `second_wave_pullback` 只保留为连续特征候选。
- GOLD/SILVER/DANGER 继续做分层；代理样本不能直接升级为硬门。
- 没有可信一手资料或严格本地数据支持以某位游资姓名命名“必胜低吸法”。

在点时成员、证券状态和候选分钟路径全部严格前，不重新跑 800 日当前成员回填，也不
输出胜率、复利最高方案。

## Next Research Gate

1. 观察 19:00/21:30 是否恢复三个 report board 和 BaoStock 当日发布。
2. 先用普通免费 Tushare token 对 `namechange/suspend_d` 做只读、零写入探测；无权限则
   保留 BaoStock reconstructed，不降低门禁。
3. catalog/tradable 双 scope 已实现；继续前向累计，并保持共享完整目录失败语义。
4. 历史成员仍优先探测 `dc_member`；没有 6,000 积分或 XT/RQData 等账号时，接受免费
   前向积累无法立即产生三年正式回测这一事实。
