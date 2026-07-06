# Strategy Optimization Ledger

这个文件只记录当前还会影响后续行动的策略结论。实验过程、长表、raw JSON、截图和失败流水不放这里；旧过程报告已从工作区移除。

## Current Baseline

- 默认策略：`mainline_dragon_pullback / 0.1.52`。
- 用户侧仍只有一个策略。
- 内部 lane/候选源：龙回头、低吸、超跌反弹、退潮高低切。
- 内部择时因子：金手指、银手指、退潮、回暖，只做正向机会分或候选源门控，不作为用户开关。
- 默认卖点：过滤后的 `dynamic_failed_launch_exit_stop` 已合入。

## Metric Decision

旧主口径 `candidate_trade_quality` 是 D 日 Top20、D+1 开盘买、按当前卖点退出。这个口径会把选股质量和持仓/卖点混在一起，导致每次优化都卡在胜率、平均收益、右尾和左尾取舍。

新的主口径：

- D 日信号出现，按尾盘价买入。
- D+1 必须上涨，作为选股层主目标。
- D+2/D+3 是否继续拿，作为持仓层二级标签。
- 旧多日卖点收益只做辅助诊断，不再作为 Top20 排序主目标。

交接文件：`2026-07-06_tail_buy_next_day_rewrite_handoff.md`。

## Production Changes Kept

- `0.1.52`: 金后期回暖低吸爬升窄因子。
- `0.1.51`: 银后 6-20 日轮动漏选右尾因子。
- 退潮板生存/高低切隐藏候选源。
- 深跌二次确认前排空位补位，用于 `603260.SSE` 型样本。

这些结论只保留在本台账中，不再保留每个窄因子的单独过程报告。

## Current Stock-Level Facts

- `002407.SZSE` 属于标准 `bottom_reclaim`：底部向上、均线修复、银后 6-20 日退潮修复窗口已能抓到。
- `603260.SSE` 不是首次收复型，而是低位修复失败后的二次确认：`secondary_breakout_confirm + deep_cycle_secondary_breakout_reversal`。
- 3 月 `2026-03-13..2026-03-24` 是银手指后压力窗口，不是普通震荡；上涨股主要是相对强势、低位补涨、高低切、首板/二板和特殊主线。
- `after_silver_6_20 / warming` 是假回暖弱桶，继续用日线低吸/超跌阈值加分会伤右尾。

## Rejected Conclusions

- 不再扩大普通 `bottom_reclaim` 加分。最新临时 `after_silver_6_20 / retreat + bottom_reclaim + rank21-60` 提高胜率但降低平均收益，并误伤 `600206.SSE`、`000672.SZSE`、`603002.SSE`、`600999.SSE`、`603260.SSE` 等右尾。
- 不做 `Top10 保护 / Top11-20 替换` 作为方案；它只能作为防误伤右尾的验收约束。
- 不继续调 `after_silver_6_20 / warming` 的低吸、超跌、深跌修复阈值。
- 不把 `secondary_breakout_confirm` 做宽泛加分；只能保留识别字段和严格前排空位补位。
- 不靠旧多日收益继续 overfit 统一 Top20。

## Next Work

1. 实现 `tail_entry_next_day_label` 只读研究器。
2. 给全量候选生成：
   - D 日尾盘买入价。
   - D+1 开高低收收益。
   - `d1_success` 和 `d1_quality_success`。
   - D+2/D+3 是否值得格局拿。
3. 用新标签重算：
   - 龙回头区域。
   - 低吸区域。
   - 超跌反弹区域。
   - 金手指/银手指不同区间。
   - 3 月压力窗口和 6 月修复窗口。
4. 只在新口径通过后，再进入生产因子修改。

## Maintenance Rules

- 每轮只新增一个交接/结论文档；不要再为每个试验写一份长报告。
- 失败方案写进本台账的 rejected 段即可，详细 raw 输出只在必要时留 `cache/`。
- 顶层只保留当前入口和收益口径交接；过程性报告不再长期保留在工作区。
