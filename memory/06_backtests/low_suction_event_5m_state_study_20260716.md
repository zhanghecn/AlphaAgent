# AlphaAgent 事件认可 5m 承接/收复研究

协议：`low-suction-research-v2`\
证据：`event_recognition_5m_falsification`\
结论：`no_event_5m_recovery_edge`\
正式绩效：`null`；外层留出价格读取：`false`

## Conclusion

完整 5 分钟路径没有挽救“主升概念当日涨停认可前三，下一交易日低吸”这个母样本。
预注册的 VWAP 收复、开盘价收复、前收收复和跌破开盘后连续两根收高，费用后胜率只有
`36.1963%..42.7027%`；四条规则平均收益、利润因子和双倍成本平均收益全部为负，最多
只有 1/5 时间块为正。

因此，下一步不应继续调整 VWAP、跌幅、时间或持有期。被否定的是“涨停认可日后的
下一交易日”这一母样本，而不仅是盲挂单或某个触发阈值。更符合游资低吸经济含义的下一
独立假设应是：认可龙头在主升周期内先完成首次日线分歧，再研究随后交易日的盘中承接；
该假设必须另行预注册，不能与本报告结果混算。

## Data Result

TDX 公共节点的 1 分钟实际库存只扫描到约 23,040 根，最早候选 `2025-06-30` 返回 0；
同一股票的 5 分钟 category 0 返回完整 48 根 `09:35..15:00`，因此采用候选定向 5m：

| Item | Value |
| --- | ---: |
| Candidate pairs | 505 |
| Symbols / dates | 322 / 76 |
| Required rows per pair | 48 |
| Complete pairs | 505 / 100.0000% |
| Missing / incomplete / duplicate | 0 / 0 / 0 |
| Candidate 5m rows | 24,240 |
| TDX rows scanned in 500-pair batch | 3,460,000 |
| Existing 1m rows before/after | 1,063,327 / 1,063,327 |

小批 5 对先写入 240 根并通过完整性验收，随后 500 对写入 24,000 根；两批均无错误、
无重连、每对精确 48 根。全库 5m 最终为 33,844 根，其中 24,240 根属于本研究候选。

分钟输入指纹：
`sha256:923138e516d296422aefa1ac430133db29d7b27a9bc6d9abaa6f8a08fddb5c00`。

## Frozen Transitions

所有状态只使用当前 5m 收盘时已知数据，信号后下一根 5m 开盘成交：

1. `vwap_reclaim`：前一收盘低于前一累计 VWAP，当前收盘达到当前累计 VWAP。
2. `open_reclaim`：前一收盘低于当日开盘，当前收盘收复开盘。
3. `previous_close_reclaim`：前一收盘低于来源日收盘，当前收盘收复前收。
4. `two_higher_closes_after_open_break`：当日已经跌破开盘，随后出现连续两根收高。

每只股票每条规则只取第一次；无下一根 5m 不成交。统一 D+1 首个可卖收盘退出，使用
10 万元单笔数学、双边滑点、最低佣金、过户费、印花税和双倍成本复算。

## Overall Results

| Rule | Signals | Closed | Win | Mean | Median | PF | Tail 5% | Positive blocks | Double-cost mean |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `open_reclaim` | 200 | 185 | 42.7027% | -1.1979% | -1.6630% | 0.6217 | -10.6938% | 1/5 | -1.5055% |
| `previous_close_reclaim` | 166 | 163 | 36.1963% | -2.1071% | -2.0990% | 0.3889 | -11.4982% | 0/5 | -2.4097% |
| `two_higher_closes_after_open_break` | 414 | 395 | 37.2152% | -1.0723% | -1.4805% | 0.6264 | -10.0193% | 1/5 | -1.3779% |
| `vwap_reclaim` | 366 | 334 | 39.8204% | -0.9137% | -1.4378% | 0.6811 | -10.0382% | 1/5 | -1.2182% |

前四个时间块没有任何规则形成稳定正收益；`previous_close_reclaim` 5/5 全负。其余三条
只在最后一个时间块转正，重复了日线盲挂研究的时间集中问题。

## Market Context

| Rule | Context | Days | Closed | Win | Mean | PF | Double-cost mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| open reclaim | `GOLD/DANGER` | 1 | 1 | 0.0000% | -7.1968% | 0.0000 | -7.4935% |
| open reclaim | `GOLD/NORMAL` | 55 | 165 | 40.0000% | -1.5715% | 0.5363 | -1.8772% |
| open reclaim | `SILVER/NORMAL` | 10 | 19 | 68.4211% | +2.3620% | 3.3054 | +2.0381% |
| previous-close reclaim | `GOLD/DANGER` | 1 | 1 | 0.0000% | -7.1968% | 0.0000 | -7.4935% |
| previous-close reclaim | `GOLD/NORMAL` | 52 | 145 | 35.1724% | -2.1559% | 0.3812 | -2.4582% |
| previous-close reclaim | `SILVER/NORMAL` | 10 | 17 | 47.0588% | -1.3908% | 0.5243 | -1.6969% |
| two higher closes | `GOLD/DANGER` | 1 | 2 | 50.0000% | +2.6135% | 2.3430 | +2.2976% |
| two higher closes | `GOLD/NORMAL` | 62 | 348 | 35.3448% | -1.3281% | 0.5624 | -1.6330% |
| two higher closes | `SILVER/NORMAL` | 13 | 45 | 51.1111% | +0.7422% | 1.4545 | +0.4320% |
| VWAP reclaim | `GOLD/DANGER` | 1 | 2 | 50.0000% | +3.3225% | 2.7073 | +2.9694% |
| VWAP reclaim | `GOLD/NORMAL` | 62 | 293 | 37.5427% | -1.2006% | 0.5990 | -1.5042% |
| VWAP reclaim | `SILVER/NORMAL` | 13 | 39 | 56.4103% | +1.0238% | 1.5272 | +0.7153% |

`SILVER/NORMAL + open_reclaim` 再次出现超过 60% 的表面胜率，但只有 19 笔、10 日，
仍集中于数据末端；它同时不满足 30 笔、20 日、跨时间块和两个环境门槛。完整环境表
保留，不能据此事后生成 `SILVER=trade`。

## Decision

1. 淘汰“当日涨停被市场认可后，下一交易日做低吸”整个母样本，不再调触发或退出。
2. 5m TDX 定向数据能力保留；它已证明可以免费覆盖 2025 年候选，而 1m 不行。
3. 下一独立研究对象改为“主升期认可龙头先完成首次分歧，再观察后续盘中承接”，不得
   把本报告最后时间块或 SILVER 小样本用作验证集。
4. 事件关系仍不是完整成员 Top3；任何后续正向代理结论都必须等待 strict Top3 复测。
5. 正式胜率、10 万元复利、最大回撤、外层留出和生产规则继续为 `null/locked`。

## Reproduce

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-event-5m-manifest --format markdown

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-event-5m-study --format markdown
```
