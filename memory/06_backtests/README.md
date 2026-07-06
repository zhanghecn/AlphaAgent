# Backtest Evidence Index

这个目录只保留当前可行动入口。旧实验过程报告已从工作区移除，不再把日志当成策略证据入口。

## Current State

- 当前默认策略：`mainline_dragon_pullback / 0.1.52`。
- 用户侧只保留一个策略；龙回头、低吸、超跌反弹、金/银手指、退潮/回暖都只是内部 lane、候选源或正向因子。
- 旧收益口径 `candidate_trade_quality` 会把选股和持仓天数混在一起。后续主目标改为：D 日信号出现后尾盘买入，D+1 必须上涨；D+2/D+3 是否格局拿作为持仓层二级标签。
- 旧持有期/卖点收益后续只做辅助诊断，不再作为 Top20 排序主目标。

## Read First

- `strategy_optimization_ledger.md`: 当前策略决策台账，只放仍有决策价值的结论。
- `2026-07-06_tail_buy_next_day_rewrite_handoff.md`: 收益算法重写交接，下一步从这里开工。

## Current Production Notes

- 生产因子结论已压缩到 `strategy_optimization_ledger.md`，不再为每个窄因子保留单独长报告。
- 详细过程报告、旧 Top20 实验脚本引用和大块 raw 输出不再作为长期证据入口。

## Removed Logs

- 旧实验过程报告已从工作区移除，不再保留 100+ 份流水式 markdown。
- `archive_index.md`: 记录清理规则和旧报告范围，不代表当前默认策略。
- `cache/`: JSON/PKL 研究缓存，不作为长期阅读入口。需要清磁盘时，优先清理可再生成的 `*_rows_*.pkl`。

## Next Work

1. 新增只读 `tail_entry_next_day_label` 研究器。
2. 全量生成 D 日尾盘买入后的 D+1/D+2/D+3 标签。
3. 重新统计龙回头、低吸、超跌反弹在金/银手指不同区间的 D+1 胜率和 D+2/D+3 格局率。
4. 只有新口径通过后，才改生产因子。
