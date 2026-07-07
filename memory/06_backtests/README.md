# Backtest Evidence Index

这个目录只保留当前可行动入口。过程报告、raw JSON、截图和失败流水不作为长期证据入口。

## Current State

- 当前默认策略：`mainline_dragon_pullback / 0.1.63`。
- 用户侧只保留一个策略；龙回头、低吸、超跌反弹、金/银手指、退潮/回暖都只是内部 lane、候选源、上下文或加分因子。
- `/quant` 候选质量主口径：全历史所有交易日逐日生成候选，但只评审每日 `Top5 / Top10 / Top20`。
- 主收益算法：D 日信号出现，按 D 日收盘价理论买入；D+1 收盘涨跌作为主胜率和主收益。
- D+2/D+3 只作为是否值得格局的辅助标签，不再混入主胜率收益。
- `/quant` 候选质量面板已展示买点区域、金/银手指窗口、行情阶段、月份、重点区间的 `Top5/10/20` 矩阵。
- 旧组合持有期/卖点收益只做执行层诊断，不再作为候选排序主目标。

## Read First

- `strategy_optimization_ledger.md`: 当前策略决策台账和下一轮执行闭环。

## Verification

- 已验证：`uv run pytest tests/alphaagent/test_candidate_lanes_silver_rotation_bonus.py tests/alphaagent/test_tail_entry_next_day_label.py -q`
- 已验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "candidate_trade_quality_scope_uses_execution_selected_inside_candidate_limit or execution_pool_drops_stale_active_weak_decay_pullback_without_refill or execution_pool_promotes_bottom_reclaim"`
- 已验证：`python -m py_compile alphaagent/server/services/backtest/tail_entry_next_day_label.py alphaagent/server/services/backtest/factor_audit.py alphaagent/server/services/backtest/engine.py alphaagent/server/services/quant/candidate_lanes.py`
- 已验证：`git diff --check`
- `0.1.63` 已在服务环境刷新轻量全历史候选：`2025-06-03..2026-07-06`，source recommendations `4002`；实际 D+1 可评价 BUY 样本从 `2025-08-06` 开始。
- `/api/quant/research-runs/latest` 已返回 `/quant` 可直接展示的候选质量完整矩阵：`by_rank_limit`、买点区域、金/银窗口、月份、重点区间、年度、每日汇总、Top 成功/失败样本。

## Next Work

1. 继续按全历史所有交易日逐日评审，但每日只看 `Top5 / Top10 / Top20`。
2. 按全样本、月份、金/银手指窗口、行情阶段、重点区间评审候选胜率、平均收益、接近涨停率、大跌率。
3. 优先研究 `金手指后0-5日`、`银手指后20日+`、`dragon_pullback::after_gold_0_5`、`low_suction_first_lift::after_silver_late`、`dragon_low_suction_overlap::after_silver_6_20`。
4. 对弱桶抽具体赢家/输家，尤其看 D+1 涨停或接近涨停、D+1 大跌样本，并按龙回头、低吸、超跌反弹内部 lane 总结 D 日可见共同特征。
5. 只把有样本证据的窄规则合入默认策略；不做 Top11-20 补位、Top10 保护这类绕开研究的兜底。
