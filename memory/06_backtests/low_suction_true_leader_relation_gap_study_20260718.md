# AlphaAgent 真龙头关系缺口审计

结论：`no_gap_promoted_to_credible_rank_failure`。升级为可信排序失败：`0`；正式模式：`null`。

本报告冻结上一轮 23 个来源已启动但关系未确认的漏抓，逐股检查 20 个交易日的
事件库存、涨停/炸板、原始原因、其他概念精确命中和后周期证据，不读取价格或低吸结果。

## Coverage

- 个股周期：`23`；股票：`22`。
- 完整 20 日库存窗口：`14`；部分窗口：`9`；库存日期缺口：`0`。
- 词面包含候选：`1`；命中其他精确概念：`9`；仅后周期命中目标：`3`。

## Classifications

| Dimension | Status | Cases |
| --- | --- | ---: |
| window | `full_inventory_window` | 14 |
| window | `partial_inventory_window` | 9 |
| stock evidence | `no_stock_limit_event` | 6 |
| stock evidence | `reason_target_unconfirmed` | 14 |
| stock evidence | `stock_limit_event_without_reason` | 3 |
| resolution | `unresolved_event_points_to_other_concepts` | 6 |
| resolution | `unresolved_no_stock_limit_event` | 3 |
| resolution | `unresolved_partial_inventory_window` | 9 |
| resolution | `unresolved_reason_missing` | 2 |
| resolution | `unresolved_unmapped_event_narrative` | 3 |

## Individual Cases

| Date | Concept | Truth leader | Window | Events/reasons | Other exact concepts | Lexical | Postcycle target | Resolution |
| --- | --- | --- | --- | ---: | --- | --- | --- | --- |
| `2025-06-27` | 英伟达概念 | 英维克 `002837.SZSE` | `partial_inventory_window` (1/20) | 0/0 | - | - | 2025-07-30、2025-07-31、2025-08-08、2025-08-18、2025-08-28、2025-11-13 | `unresolved_partial_inventory_window` |
| `2025-07-04` | 免疫治疗 | 中源协和 `600645.SSE` | `partial_inventory_window` (6/20) | 1/1 | 创新药 | 细胞免疫治疗 | - | `unresolved_partial_inventory_window` |
| `2025-07-07` | 职业教育 | 德生科技 `002908.SZSE` | `partial_inventory_window` (7/20) | 2/1 | - | - | - | `unresolved_partial_inventory_window` |
| `2025-07-08` | 体育产业 | 国恩股份 `002768.SZSE` | `partial_inventory_window` (8/20) | 0/0 | - | - | - | `unresolved_partial_inventory_window` |
| `2025-07-08` | 东数西算 | 东阳光 `600673.SSE` | `partial_inventory_window` (8/20) | 1/0 | - | - | - | `unresolved_partial_inventory_window` |
| `2025-07-10` | 单抗概念 | 海思科 `002653.SZSE` | `partial_inventory_window` (10/20) | 1/1 | - | - | - | `unresolved_partial_inventory_window` |
| `2025-07-10` | 流感 | 众生药业 `002317.SZSE` | `partial_inventory_window` (10/20) | 0/0 | - | - | 2025-11-12、2025-11-14 | `unresolved_partial_inventory_window` |
| `2025-07-14` | 中药概念 | 京新药业 `002020.SZSE` | `partial_inventory_window` (12/20) | 1/1 | 创新药、医疗器械概念 | - | - | `unresolved_partial_inventory_window` |
| `2025-07-16` | 机器人执行器 | 中大力德 `002896.SZSE` | `partial_inventory_window` (14/20) | 3/2 | 人形机器人 | - | - | `unresolved_partial_inventory_window` |
| `2025-08-15` | 券商概念 | 太平洋 `601099.SSE` | `full_inventory_window` (20/20) | 0/0 | - | - | - | `unresolved_no_stock_limit_event` |
| `2025-09-05` | 光伏概念 | 科士达 `002518.SZSE` | `full_inventory_window` (20/20) | 4/2 | AI应用、储能概念、数据中心 | - | - | `unresolved_event_points_to_other_concepts` |
| `2025-09-08` | 化工原料 | 多氟多 `002407.SZSE` | `full_inventory_window` (20/20) | 2/2 | 储能概念、固态电池 | - | - | `unresolved_event_points_to_other_concepts` |
| `2025-09-10` | 造纸印刷 | 松炀资源 `603863.SSE` | `full_inventory_window` (20/20) | 1/1 | - | - | - | `unresolved_unmapped_event_narrative` |
| `2025-09-10` | 包装材料 | 中锐股份 `002374.SZSE` | `full_inventory_window` (20/20) | 2/0 | - | - | - | `unresolved_reason_missing` |
| `2025-09-10` | 低价股 | 宝泰隆 `601011.SSE` | `full_inventory_window` (20/20) | 0/0 | - | - | - | `unresolved_no_stock_limit_event` |
| `2025-09-10` | 汽车一体化压铸 | 迪生力 `603335.SSE` | `full_inventory_window` (20/20) | 1/0 | - | - | - | `unresolved_reason_missing` |
| `2025-09-11` | 独角兽 | 多氟多 `002407.SZSE` | `full_inventory_window` (20/20) | 2/2 | 储能概念、固态电池 | - | - | `unresolved_event_points_to_other_concepts` |
| `2025-09-11` | 猪肉概念 | 金新农 `002548.SZSE` | `full_inventory_window` (20/20) | 1/1 | 股权激励 | - | - | `unresolved_event_points_to_other_concepts` |
| `2025-09-11` | 华为汽车 | 能科科技 `603859.SSE` | `full_inventory_window` (20/20) | 2/2 | AI智能体 | - | - | `unresolved_event_points_to_other_concepts` |
| `2025-09-11` | 储能概念 | 天山铝业 `002532.SZSE` | `full_inventory_window` (20/20) | 0/0 | - | - | - | `unresolved_no_stock_limit_event` |
| `2025-09-12` | 新能源 | 思源电气 `002028.SZSE` | `full_inventory_window` (20/20) | 1/1 | - | - | - | `unresolved_unmapped_event_narrative` |
| `2025-09-12` | 统一大市场 | 飞马国际 `002210.SZSE` | `full_inventory_window` (20/20) | 4/2 | - | - | 2025-09-16、2025-09-25 | `unresolved_unmapped_event_narrative` |
| `2025-09-12` | 光通信模块 | 合锻智能 `603011.SSE` | `full_inventory_window` (20/20) | 1/1 | 可控核聚变、算力概念 | - | - | `unresolved_event_points_to_other_concepts` |

## Raw Reason Evidence

| Date | Target concept | Stock | Observed reason events |
| --- | --- | --- | --- |
| `2025-07-04` | 免疫治疗 | 中源协和 `600645.SSE` | `2025-07-04` 创新药+细胞免疫治疗 |
| `2025-07-07` | 职业教育 | 德生科技 `002908.SZSE` | `2025-07-04` 数字人民币+AI民生+社保卡服务 |
| `2025-07-10` | 单抗概念 | 海思科 `002653.SZSE` | `2025-07-10` 创新药上市+股票发行受理+销售增长 |
| `2025-07-14` | 中药概念 | 京新药业 `002020.SZSE` | `2025-07-04` 创新药+商业化推进+医疗器械 |
| `2025-07-16` | 机器人执行器 | 中大力德 `002896.SZSE` | `2025-07-11` 人形机器人+泰国工厂+一季报增长；`2025-07-14` 人形机器人+泰国工厂+精密减速器 |
| `2025-09-05` | 光伏概念 | 科士达 `002518.SZSE` | `2025-08-15` AI应用+数据中心+储能+液冷技术；`2025-08-19` 数据中心电源+液冷技术+储能 |
| `2025-09-08` | 化工原料 | 多氟多 `002407.SZSE` | `2025-09-05` 固态电池+储能+六氟磷酸锂+回购；`2025-09-08` 固态电池+储能+六氟磷酸锂+回购 |
| `2025-09-10` | 造纸印刷 | 松炀资源 `603863.SSE` | `2025-09-04` 环保再生纸+彩票业务+控制权变更+亏损收窄 |
| `2025-09-11` | 独角兽 | 多氟多 `002407.SZSE` | `2025-09-05` 固态电池+储能+六氟磷酸锂+回购；`2025-09-08` 固态电池+储能+六氟磷酸锂+回购 |
| `2025-09-11` | 猪肉概念 | 金新农 `002548.SZSE` | `2025-09-11` 猪饲料+生猪养殖+降本增效+股权激励 |
| `2025-09-11` | 华为汽车 | 能科科技 `603859.SSE` | `2025-08-26` 中报增长+具身智能机器人+AI智能体；`2025-08-27` 中报增长+具身智能机器人+AI智能体 |
| `2025-09-12` | 新能源 | 思源电气 `002028.SZSE` | `2025-09-01` 中报增长+构网型储能+海外业务 |
| `2025-09-12` | 统一大市场 | 飞马国际 `002210.SZSE` | `2025-08-29` 供应链服务+固废处理+控制权变更；`2025-09-01` 供应链服务+固废处理+控制权变更 |
| `2025-09-12` | 光通信模块 | 合锻智能 `603011.SSE` | `2025-09-08` 可控核聚变+军工装备+算力 |

## Decision

可信关系排序失败仍为 `2`，审计后仍为 `2`。
这 23 个案例没有一个获得事前精确关系证据，因此不能用于增加排序权重或反推低吸收益。

## Boundary

- historical canonical event scopes were not persisted; inventory-date presence is a weaker coverage indicator
- no stock event or no reason remains unknown rather than a false concept membership
- event reasons describe the observed catalyst and do not define the complete historical member set
- lexical containment requires independent semantic verification and was not promoted
- postcycle exact relations cannot confirm an earlier cycle
- current concept membership remains a survivorship proxy

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-true-leader-relation-gap-study --format markdown
```
