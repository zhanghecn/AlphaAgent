# AlphaAgent 行情计算真龙头研究

结论：`stable_relative_improvement_but_identity_accuracy_insufficient`。正式 Top3：`false`；低吸绩效：`null`。

龙头候选和 Top3 全部由沪深主板股票、概念指数和市场基准的日线计算；概念成员、涨停原因、分钟线、金银环境和交易结果读取数均为 0。

## Coverage

- 发现段：`2023-03-28..2025-11-17`；真值截止：`2026-01-14`。
- 主板股票：`3294` 只 / `2172576` 根日线。
- 预筛概念周期：`1854`；因果关系周期：`1825`；完整真值周期：`1854`。
- 因果关系行：`54711`；已实现关系行：`55449`。

## Frozen Calculation

- 关系：过去 `40` 个交易日，至少 `30` 个配对观测；股票和概念都先减去沪深300/中证500/中证1000等权日收益。
- 关系共识：同期残差相关、股票领先概念一日相关、残差同向率三项在同周期内的百分位等权平均；没有搜索其他权重或窗口。
- 个股资格：收盘不低于 MA5，且 MA5 > MA10 > MA20，MA5/MA10均较三日前上升，近十日至少一次涨幅不低于 5%。
- 未来真值：D+1..D+40 独立重算关系，再按多波次数、最大概念超额、20 日收盘超额排序；不回流因果排名。

## Identity Validation

| Segment | Mode | Cycles | Relation pool captures truth Top1 | Top1 exact | Top3 captures truth Top1 | Top3 overlap |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `all` | `calculated_leadership` | 1825 | 26.3014% | 0.8219% | 2.9589% | 2.4840% |
| `all` | `ten_day_excess_baseline` | 1825 | 26.3014% | 0.7671% | 2.5205% | 2.3014% |
| `block_1` | `calculated_leadership` | 333 | 24.3243% | 1.8018% | 3.6036% | 4.0040% |
| `block_1` | `ten_day_excess_baseline` | 333 | 24.3243% | 1.8018% | 3.6036% | 4.4044% |
| `block_2` | `calculated_leadership` | 371 | 32.8841% | 0.5391% | 1.3477% | 1.7969% |
| `block_2` | `ten_day_excess_baseline` | 371 | 32.8841% | 0.2695% | 1.0782% | 1.0782% |
| `block_3` | `calculated_leadership` | 386 | 26.1658% | 0.2591% | 3.3679% | 1.9862% |
| `block_3` | `ten_day_excess_baseline` | 386 | 26.1658% | 0.5181% | 4.1451% | 2.7634% |
| `block_4` | `calculated_leadership` | 381 | 20.7349% | 0.0000% | 1.8373% | 1.3998% |
| `block_4` | `ten_day_excess_baseline` | 381 | 20.7349% | 0.2625% | 1.3123% | 1.0499% |
| `block_5` | `calculated_leadership` | 354 | 27.4011% | 1.6949% | 4.8023% | 3.4840% |
| `block_5` | `ten_day_excess_baseline` | 354 | 27.4011% | 1.1299% | 2.5424% | 2.4482% |

## Decision

- 五块胜数：`3/5`；相对稳定门：`true`。
- 绝对身份门：`false`；要求 Top1 精确率 30%、Top3 捕获 60%、Top3 重合 50%。
- 归因：关系池漏抓 `1345`，池内排序漏抓 `426`，Top3 捕获 `54`。

## Representative Misses

| Date | Concept | Realized Top1 | Calculated Top3 | Attribution |
| --- | --- | --- | --- | --- |
| `2024-05-16` | 工程建设 | 世联行 `002285.SZSE` | *ST京化 `600889.SSE`, 金科股份 `000656.SZSE`, 万里股份 `600847.SSE` | `relationship_pool_miss` |
| `2024-09-26` | 工程建设 | *ST东易 `002713.SZSE` | 中哲精化 `000953.SZSE`, 建设机械 `600984.SSE`, 首钢股份 `000959.SZSE` | `relationship_pool_miss` |
| `2025-09-16` | 工程建设 | 宝泰隆 `601011.SSE` | ST百利 `603959.SSE`, 美邦服饰 `002269.SZSE`, 上海建工 `600170.SSE` | `relationship_pool_miss` |
| `2025-10-21` | 工程建设 | 冠城新材 `600067.SSE` | 合肥城建 `002208.SZSE`, 宝泰隆 `601011.SSE`, 海鸥住工 `002084.SZSE` | `relationship_pool_miss` |
| `2024-03-08` | 交运设备 | 万安科技 `002590.SZSE` | 川润股份 `002272.SZSE`, 文投控股 `600715.SSE`, 艾艾精工 `603580.SSE` | `relationship_pool_miss` |
| `2024-07-26` | 交运设备 | 瀛通通讯 `002861.SZSE` | 大众交通 `600611.SSE`, 金龙汽车 `600686.SSE`, 腾达科技 `001379.SZSE` | `leader_rank_miss` |
| `2025-05-08` | 交运设备 | 今创集团 `603680.SSE` | 龙溪股份 `600592.SSE`, 襄阳轴承 `000678.SZSE`, 大业股份 `603278.SSE` | `leader_rank_miss` |
| `2023-06-01` | 互联网服务 | 华工科技 `000988.SZSE` | ST智知 `603869.SSE`, 南方传媒 `601900.SSE`, 姚记科技 `002605.SZSE` | `relationship_pool_miss` |
| `2024-08-01` | 互联网服务 | 美利云 `000815.SZSE` | 四创电子 `600990.SSE`, 春光科技 `603657.SSE`, 爱仕达 `002403.SZSE` | `relationship_pool_miss` |
| `2024-09-20` | 互联网服务 | 梦网科技 `002123.SZSE` | 银宝山新 `002786.SZSE`, 国华退 `000004.SZSE`, *ST网达 `603189.SSE` | `relationship_pool_miss` |
| `2024-12-02` | 互联网服务 | 三维通信 `002115.SZSE` | XD华胜天 `600410.SSE`, 生 意 宝 `002095.SZSE`, 跨境通 `002640.SZSE` | `leader_rank_miss` |
| `2025-02-06` | 互联网服务 | 云鼎科技 `000409.SZSE` | 新炬网络 `605398.SSE`, 浙江东方 `600120.SSE`, 三六零 `601360.SSE` | `leader_rank_miss` |
| `2025-03-06` | 互联网服务 | 福达股份 `603166.SSE` | 贝瑞基因 `000710.SZSE`, 云鼎科技 `000409.SZSE`, 浙江黎明 `603048.SSE` | `relationship_pool_miss` |
| `2025-06-09` | 互联网服务 | 奥康国际 `603001.SSE` | 中电鑫龙 `002298.SZSE`, 顺钠股份 `000533.SZSE`, 华脉科技 `603042.SSE` | `relationship_pool_miss` |
| `2025-11-03` | 互联网服务 | 榕基软件 `002474.SZSE` | 神州信息 `000555.SZSE`, 欢瑞世纪 `000892.SZSE`, 联环药业 `600513.SSE` | `relationship_pool_miss` |
| `2023-07-26` | 造纸印刷 | *ST泛海 `000046.SZSE` | 东方新能 `002310.SZSE`, ST迪马 `600565.SSE`, 美邦服饰 `002269.SZSE` | `relationship_pool_miss` |
| `2024-05-17` | 造纸印刷 | 凯撒文化 `002425.SZSE` | *ST京化 `600889.SSE`, 金科股份 `000656.SZSE`, 万里股份 `600847.SSE` | `leader_rank_miss` |
| `2024-11-27` | 造纸印刷 | 省广集团 `002400.SZSE` | 实丰文化 `002862.SZSE`, 广博股份 `002103.SZSE`, 二六三 `002467.SZSE` | `relationship_pool_miss` |
| `2025-09-10` | 造纸印刷 | 大连圣亚 `600593.SSE` | *ST春兴 `002547.SZSE`, 卧龙新能 `600173.SSE`, 美邦服饰 `002269.SZSE` | `relationship_pool_miss` |
| `2023-06-15` | 酿酒概念 | ST中南 `000961.SZSE` | 威龙股份 `603779.SSE`, 联明股份 `603006.SSE`, 兴民智通 `002355.SZSE` | `relationship_pool_miss` |

## Boundary

- The former outer holdout has already been inspected and is not reusable as untouched evidence.
- Historical point-in-time ST and suspension status is incomplete; eligibility uses main-board symbols and observed bars only.
- Realized leader truth is a price-calculated proxy, not an exchange-published semantic concept membership label.
- No low-suction entry, exit, win rate, return, compounding or drawdown is read until identity gates pass in a newly locked validation set.

## Reproduce

```bash
docker compose run --rm --no-deps -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api python -m alphaagent.server.services.low_suction.cli v2-calculated-true-leader-study --format markdown
```
