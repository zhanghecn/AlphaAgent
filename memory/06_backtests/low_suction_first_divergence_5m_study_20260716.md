# AlphaAgent 首次日线分歧后 5m 低吸反证

协议：`low-suction-research-v2`\
协议哈希：`sha256:3c96f32f6693b657e230ac5f63dfc8d392098b6d64a8b86f549d7082c36d878c`\
证据：`event_recognition_first_divergence_5m_falsification`\
结论：`no_first_divergence_5m_edge`\
正式绩效：`null`；外层留出价格读取：`false`

## Conclusion

“认可龙头先完成首次日线分歧，再在下一交易日等待 5 分钟承接/收复”的独立假设没有
达到继续严格复测的资格。四条冻结规则最高胜率只有 `44.1718%`；只有开盘价收复和
前收收复的正常成本均值略高于零，但双倍成本分别变为 `-0.2786%/-0.1756%`，且都只
有 2/5 时间块为正。

本轮比“涨停认可后的次日”母样本改善了尾部和平均收益，却没有改善最关键的胜率与
跨时间稳定性。结果否定的是整个“日线首次分歧后，次日等收复并于 D+1 收盘退出”
研究路径，不能再通过改回撤阈值、VWAP 参数或金银手指小样本继续搜索。

下一研究必须回到 v2 中性状态面板：保留 leader spell 的全部可交易分钟状态，先观察
连续特征响应曲面，不再以首次分歧、首阴、修复或二波作为样本入口。

## Candidate Funnel

每个 `(sector_id, cycle_id, vt_symbol)` 只保留最早认可事件；在 S+1..S+5 内寻找首次
`close < previous_close`，分歧日仍须属于同一个 `breakout_trend cycle_id`。分歧后的
下一可靠交易日为观察日，再下一可靠交易日为计划退出日，二者都不能晚于
`2025-11-17`。

| Item | Count |
| --- | ---: |
| Recognition candidates | 505 |
| Earliest recognition spells | 369 |
| Rejected: no negative close in five sessions | 18 |
| Rejected: original cycle no longer active | 8 |
| Rejected: observation/exit crossed discovery | 9 |
| Pre-collision candidates | 334 |
| Cross-concept collisions removed | 1 |
| Final candidates | 333 |
| Symbols / divergence dates | 300 / 82 |
| Candidate date range | 2025-06-30..2025-11-13 |

首次分歧距离认可日的交易日偏移分布为：S+1 `132`、S+2 `108`、S+3 `64`、S+4
`22`、S+5 `7`。市场环境候选分布为 `GOLD/NORMAL 294`、`SILVER/NORMAL 37`、
`GOLD/DANGER 1`、`SILVER/DANGER 1`。

跨概念冲突按分歧日概念相对强度降序、原始认可日和概念 ID 升序去重。`source_date`
固定为分歧日，因此时间块和金银手指都使用分歧日收盘后已知状态，不回落到更早的认可日。

## Minute Coverage

首次 manifest 为 333/333 缺失。随后只按 manifest 股票日期从 TDX category 0 定向
回补，最终数据库复核如下：

| Item | Value |
| --- | ---: |
| Candidate pairs | 333 |
| Symbols / dates | 300 / 82 |
| Required bars per pair | 48 |
| Required window | 09:35..15:00 |
| Rows read / written | 15,984 / 15,984 |
| Complete pairs | 333 / 100.0000% |
| Missing / incomplete / duplicate | 0 / 0 / 0 |
| TDX remote rows scanned | 3,267,200 |
| Errors / reconnects | 0 / 0 |

分钟输入指纹：
`sha256:4044e507db107b06b6f27b78b1d91970a19fecce7e0d6383b71c071e1f6d7a6c`。

分钟指纹只包含精确 333 个候选观察日的 15,984 根 5m bar；数据库中其他打板或事件
研究分钟线没有混入。既有 1m 数据未改写。

## Frozen Execution

四条规则逐字复用上一轮：

1. `vwap_reclaim`。
2. `open_reclaim`。
3. `previous_close_reclaim`。
4. `two_higher_closes_after_open_break`。

信号在 5m 收盘确认，下一根 5m 开盘成交；每只候选每条规则只取第一次。退出为下一
可靠交易日首个可卖收盘，执行 10 万元、100 股整数手、佣金、最低佣金、过户费、
印花税、单边 10 bps 滑点和双倍成本。CLI 没有分歧窗口、规则、阈值、退出或日期参数。

## Overall Results

| Rule | Signals | Closed | Win | Mean | Median | PF | Tail 5% | Positive blocks | Double-cost mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `open_reclaim` | 170 | 169 | 42.0118% | +0.0282% | -0.7669% | 1.0121 | -7.8792% | 2/5 | -0.2786% |
| `previous_close_reclaim` | 163 | 163 | 44.1718% | +0.1323% | -0.8559% | 1.0585 | -8.5752% | 2/5 | -0.1756% |
| `two_higher_closes_after_open_break` | 298 | 297 | 38.7205% | -0.3938% | -1.2893% | 0.8227 | -7.3118% | 1/5 | -0.7022% |
| `vwap_reclaim` | 261 | 260 | 41.5385% | -0.1764% | -0.9386% | 0.9267 | -8.0454% | 3/5 | -0.4818% |

三条规则各有一笔在发现期内没有可卖退出，其余全部闭合。没有规则达到 60% 胜率、
双倍成本为正和 4/5 正向时间块的联合门槛。

## Time Blocks

| Rule | Block | Days | Closed | Win | Mean | PF | Positive |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `open_reclaim` | 1 | 12 | 34 | 55.8824% | +1.5096% | 1.8904 | yes |
| `open_reclaim` | 2 | 13 | 46 | 28.2609% | -1.2248% | 0.5867 | no |
| `open_reclaim` | 3 | 14 | 42 | 52.3810% | +0.3840% | 1.1813 | yes |
| `open_reclaim` | 4 | 12 | 24 | 33.3333% | -0.1452% | 0.9334 | no |
| `open_reclaim` | 5 | 14 | 23 | 39.1304% | -0.1245% | 0.9500 | no |
| `previous_close_reclaim` | 1 | 14 | 33 | 51.5152% | +1.8092% | 1.9326 | yes |
| `previous_close_reclaim` | 2 | 13 | 42 | 23.8095% | -2.0390% | 0.3941 | no |
| `previous_close_reclaim` | 3 | 14 | 49 | 59.1837% | +1.4241% | 1.9204 | yes |
| `previous_close_reclaim` | 4 | 13 | 21 | 33.3333% | -0.7680% | 0.5881 | no |
| `previous_close_reclaim` | 5 | 11 | 18 | 50.0000% | -0.3423% | 0.8717 | no |
| `two_higher_closes_after_open_break` | 1 | 16 | 64 | 46.8750% | +1.3351% | 1.8278 | yes |
| `two_higher_closes_after_open_break` | 2 | 17 | 78 | 26.9231% | -1.5892% | 0.4122 | no |
| `two_higher_closes_after_open_break` | 3 | 16 | 75 | 42.6667% | -0.4819% | 0.7864 | no |
| `two_higher_closes_after_open_break` | 4 | 16 | 41 | 36.5854% | -0.6095% | 0.7037 | no |
| `two_higher_closes_after_open_break` | 5 | 16 | 39 | 43.5897% | -0.4436% | 0.8117 | no |
| `vwap_reclaim` | 1 | 16 | 55 | 41.8182% | +0.4899% | 1.2078 | yes |
| `vwap_reclaim` | 2 | 13 | 68 | 30.8824% | -1.1283% | 0.6067 | no |
| `vwap_reclaim` | 3 | 15 | 68 | 52.9412% | +0.2932% | 1.1342 | yes |
| `vwap_reclaim` | 4 | 15 | 33 | 36.3636% | -0.5595% | 0.7292 | no |
| `vwap_reclaim` | 5 | 14 | 36 | 44.4444% | +0.0681% | 1.0292 | yes |

第二时间块四条规则全部显著为负；没有任何规则达到 4/5 正向，说明正均值并非可跨期
复现的规律。

## Market Context

| Rule | Context | Days | Closed | Win | Mean | PF | Double-cost mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| open reclaim | `GOLD/DANGER` | 1 | 1 | 100.0000% | +3.2329% | - | +2.9159% |
| open reclaim | `GOLD/NORMAL` | 52 | 148 | 41.8919% | -0.0122% | 0.9948 | -0.3189% |
| open reclaim | `SILVER/DANGER` | 1 | 1 | 0.0000% | -5.3406% | 0.0000 | -5.6411% |
| open reclaim | `SILVER/NORMAL` | 11 | 19 | 42.1053% | +0.4569% | 1.2041 | +0.1488% |
| previous-close reclaim | `GOLD/DANGER` | 1 | 1 | 100.0000% | +3.2329% | - | +2.9159% |
| previous-close reclaim | `GOLD/NORMAL` | 55 | 146 | 43.1507% | +0.1506% | 1.0674 | -0.1570% |
| previous-close reclaim | `SILVER/NORMAL` | 9 | 16 | 50.0000% | -0.2287% | 0.9135 | -0.5390% |
| two higher closes | `GOLD/DANGER` | 1 | 1 | 100.0000% | +0.7965% | - | +0.4892% |
| two higher closes | `GOLD/NORMAL` | 67 | 262 | 37.4046% | -0.4654% | 0.7933 | -0.7735% |
| two higher closes | `SILVER/DANGER` | 1 | 1 | 0.0000% | -4.3530% | 0.0000 | -4.6558% |
| two higher closes | `SILVER/NORMAL` | 12 | 33 | 48.4848% | +0.2587% | 1.1309 | -0.0528% |
| VWAP reclaim | `GOLD/NORMAL` | 60 | 226 | 40.7080% | -0.2835% | 0.8850 | -0.5891% |
| VWAP reclaim | `SILVER/DANGER` | 1 | 1 | 0.0000% | -4.3530% | 0.0000 | -4.6558% |
| VWAP reclaim | `SILVER/NORMAL` | 12 | 33 | 48.4848% | +0.6841% | 1.3540 | +0.3795% |

两个 100% 的 `GOLD/DANGER` 单元都只有 1 日 1 笔；最大的正向银手指单元也只有 33 笔、
12 日且胜率 48.48%。没有环境满足 20 日、30 笔、胜率大于 60% 的物质门，更不存在
两个合格环境。环境结果不转成交易/空仓表。

## Decision

1. 淘汰“首次日线分歧后下一日等 5m 收复、D+1 收盘退出”整个母假设。
2. 不再调整本轮四条规则、回撤深度、时间窗口、退出或金银手指条件。
3. 首次分歧标签只保留为失败归因，不进入下一轮候选生成。
4. 下一轮回到无预设分钟状态面板，以中性 leader spell 观察日研究连续响应曲面。
5. 事件关系仍不是完整历史成员 Top3；正式胜率、复利、回撤和留出继续为 `null/locked`。

## Reproduce

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-first-divergence-audit --format markdown

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-first-divergence-5m-manifest --format markdown

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-first-divergence-5m-study --format markdown
```
