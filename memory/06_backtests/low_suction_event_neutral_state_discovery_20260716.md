# AlphaAgent 事件认可 leader spell 中性 5m 状态发现

协议：`low-suction-research-v2`\
协议哈希：`sha256:3c96f32f6693b657e230ac5f63dfc8d392098b6d64a8b86f549d7082c36d878c`\
证据：`event_recognition_neutral_state_falsification`\
结论：`no_event_neutral_state_edge`\
正式绩效：`null`；外层留出价格读取：`false`

完整机器报告：
`low_suction_event_neutral_state_discovery_20260716.json`\
报告 SHA256：
`d20d6dd4301c19a5bf107c00ea6e43d03c4c7a9ff91c14368b08974ec65ab7cd`

## Conclusion

从旧形态方向重置到 outcome-neutral 状态面板后，仍未发现可进入严格 Top3 复测的低吸
规律。1,722 个中性观察日、75,768 条可执行 5m 状态按时间分为五块；前三块只拟合
分位和一个深度 2 浅树，后两块不参与阈值选择。

浅树的 4 个叶子全部在开发门被拒绝：两个叶子是明确负期望；另外两个表面胜率为
`64.2857%/100.0000%`，但条件要求价格相对前收上涨超过 `9.9866%`，分别只有 28/4
笔闭合，且大部分信号因下一 5m 开盘处于涨停被拒单。这不是低吸，而是模型在有限样本
中找到的接近涨停状态；独立块仅 62/18，也没有达到 100 块门槛。

验证段 100 个响应格中，78 个达到至少 30 个独立块。最高胜率格只有 `45.7944%` 且
均值 `-0.6167%`；最高均值格只有 `+0.1166%`、胜率 `42.5121%`，双倍成本均值转为
`-0.1898%`。没有任何胜率大于 60%、正常和双倍成本同时正向的验证格。

因此研究顺序在入场阶段停止：不能继续比较 D+1 10:00/14:30、D+3/D+5 退出、仓位、
金银环境开关或现金复利。继续添加规则会违反“没有方案通过就停止”的冻结协议。

## Neutral Candidate Funnel

每个 `(sector_id, cycle_id, vt_symbol)` 只保留最早认可事件。S+1..S+5 的观察日不读取
当天个股涨跌、K 线、最终低点或概念收盘；仅要求 D-1 仍属于同一个
`breakout_trend cycle_id`。所有均线、前高和金银状态也冻结在 D-1。

| Item | Count |
| --- | ---: |
| Recognition candidates | 505 |
| Earliest leader spells | 369 |
| Potential S+1..S+5 days | 1,845 |
| Rejected: D-1 no longer in exact cycle | 48 |
| Rejected: observation/exit crossed discovery | 67 |
| Pre-collision candidates | 1,730 |
| Cross-concept collisions removed | 8 |
| Final neutral candidate days | 1,722 |
| Symbols / dates / concept cycles | 318 / 94 / 51 |
| Date range | 2025-06-30..2025-11-14 |

偏移分布为 S+1 `361`、S+2 `354`、S+3 `347`、S+4 `334`、S+5 `326`。市场环境
为 `GOLD/NORMAL 1,508`、`SILVER/NORMAL 205`、`GOLD/DANGER 6`、
`SILVER/DANGER 3`。同日概念收盘、个股结果和当前成员读取均为 0。

候选指纹：
`sha256:04bcb710a69d40850a52790b1cb498d4e8698ee1715bd3d8753c880c2334ac7f`。

## Minute And State Coverage

初始 manifest 已有 766/1,722 对完整，来自前两轮真实 5m 数据。其余 956 对定向回补
45,888 根，TDX category 0 无错误、无重连；最终 1,722/1,722 全部为 48 根，缺失、
部分和重复均为 0。

| Item | Value |
| --- | ---: |
| Candidate 5m rows | 82,656 |
| Complete candidate days | 1,722 / 100.0000% |
| Existing complete / newly filled | 766 / 956 |
| New rows read / written | 45,888 / 45,888 |
| Existing 1m rows before / after | 1,063,567 / 1,063,567 |
| Initial three-bar history exclusions | 5,166 |
| No-next-bar 15:00 exclusions | 1,722 |
| Executable point-in-time states | 75,768 |

分钟指纹：
`sha256:fdf74bdd706ac5af3aef4c5a258b8413fe7647bd193bac81c138a9e7909a5012`。\
状态指纹：
`sha256:4501b6069a90aea430119325eb911895f86ef6d6cd02ea36d057e83de3bdda59`。

每个完整日固定保留 44 条状态。每个 `(trade_date, cycle_id)` 块的样本权重总和为 1，
分钟行数不会被当成独立样本数。

## Frozen Features And Split

状态只包含以下连续、点时字段：

- 当日高点回撤，距前收、开盘、点时 VWAP、D-1 前高、D-1 MA5/MA10 的距离。
- 1/3 bar 收益，当前量相对前三根已结束 bar 均量。
- 开盘后交易分钟数、D-1 概念相对百分位、spell 的 S+1..S+5 偏移。

候选日按日期等分：block 1/2/3/4/5 分别为 `454/485/356/222/205` 个。block 1-3
只用于训练，block 4-5 只用于验证。训练期 20/40/60/80 分位边界完整保存在机器报告，
验证极端值不能修改边界。

四张预注册曲面固定为：

1. 当日高点回撤 × D-1 概念相对强度。
2. 距点时 VWAP × 前三 bar 量比。
3. 开盘后时间 × 距前收。
4. 3 bar 收益 × 当日高点回撤。

## Frozen Execution Labels

每条状态在当前 5m 收盘确认，下一根 5m 开盘按 10 万元、100 股整数手、佣金、最低
佣金、过户费和单边 10 bps 滑点执行；仅标注 D+1 首个可卖收盘及双倍成本。

正常和双倍成本均有 71,631 条闭合标签；4,137 条因下一根开盘达到涨停而拒单，没有
其他拒单原因。正常/双倍成本 outcome 指纹分别为：

- `sha256:1dc8f55b15e4044b85a34775b58fcf1489ad3cfee52fc85c68f4ab1748536b39`
- `sha256:6aad8d41d8459deacf067e07582221c92d222720ab3c15cef240ed7c50f83a1a`

## Development Tree Ledger

浅树合同固定为 `max_depth=2`、`min_samples_leaf=100`、`random_state=0`，目标只使用
正常成本 D+1 净对数收益，权重为独立块反频率。所有叶子都保留：

| Leaf | Conditions | Blocks | Signals / closed | Win | Mean | PF | Double mean | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2 | 距前收 <= 9.9866%，距 MA5 <= 21.9366% | 87 | 99 / 99 | 42.4242% | -1.4514% | 0.6137 | -1.7526% | reject: 样本不足且负期望 |
| 3 | 距前收 <= 9.9866%，距 MA5 > 21.9366% | 64 | 71 / 71 | 42.2535% | -2.3807% | 0.4859 | -2.6811% | reject: 样本不足且负期望 |
| 5 | 距前收 > 9.9866%，距 MA5 <= 25.3293% | 62 | 72 / 28 | 64.2857% | +1.0630% | 1.4868 | +0.7451% | reject: 少于 100 独立块 |
| 6 | 距前收 > 9.9866%，距 MA5 > 25.3293% | 18 | 18 / 4 | 100.0000% | +4.0661% | - | +3.7177% | reject: 少于 100 独立块 |

叶 5/6 都位于 10cm 涨停附近，不属于可执行低吸。树深度 2、叶子 4、开发接受候选 0，
因此后两块没有规则可验证，`candidate_rules=[]`、`qualifying_rules=[]`。

## Validation Surfaces

开发和验证各生成 100 个完整响应格。验证中 78 格达到至少 30 个独立块：

| Diagnostic | Surface/cell | Episodes / blocks | Win | Mean | PF | Double mean |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Highest validation win | 时间 q40-q60 × 距前收 q40-q60 | 107 / 67 | 45.7944% | -0.6167% | 0.6954 | -0.9255% |
| Highest validation mean | 距 VWAP q40-q60 × 量比 q40-q60 | 207 / 97 | 42.5121% | +0.1166% | 1.0627 | -0.1898% |

验证格中满足胜率大于 60%、正常均值为正、双倍成本均值为正的数量为 0。全部 200 格
及其原始状态数、episode、独立块、胜率、均值、中位数、PF 和 5% 尾部均保存在 JSON。

## Decision

1. 淘汰事件认可代理上的 S+1..S+5 两条件中性 5m 状态发现方向。
2. 不从 28/4 笔接近涨停的小叶提炼规则，也不把它们改名为低吸。
3. 因开发接受候选为 0，不研究退出、仓位、环境开关、复利或外层留出。
4. 目前没有高胜率高收益低吸规律；结论必须是 `no_qualified_strategy`，不能制造答案。
5. 下一步不是增加第三个条件，而是等待严格历史成员和证券状态后，按正式 Top3 身份
   重建同一无预设状态研究；免费前向证据继续积累。

## Reproduce

```bash
docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-event-neutral-audit --format markdown

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-event-neutral-5m-manifest --format markdown

docker compose run --rm --no-deps \
  -v /root/project/ai/vnpy:/workspace -w /workspace alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-event-neutral-state-study --format markdown
```
