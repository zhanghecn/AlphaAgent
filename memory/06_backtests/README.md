# Backtest Evidence Index

这个目录只保留当前可行动入口。过程报告、raw JSON、截图和失败流水不作为长期证据入口。

## Current State

- 当前默认策略：`mainline_dragon_pullback / 0.1.66`。
- 用户侧只保留一个策略；龙回头、低吸、超跌反弹、金/银手指、退潮/回暖都只是内部 lane、候选源、上下文或加分因子。
- `/quant` 候选质量主口径：全历史所有交易日逐日生成候选，但只评审每日 `Top5 / Top10 / Top20`。
- 主收益算法：D 日信号出现，按 D 日收盘价理论买入；D+1 收盘涨跌作为主胜率和主收益。
- D+2/D+3 只作为是否值得格局的辅助标签，不混入主胜率收益。
- 0.1.66 已把“深度超跌 + 恐慌低收 + 无涨停源 + 温和/缩量承接”的超跌反弹形态合入默认策略内部 `oversold_rebound_start` lane，子型为 `deep_low_absorption_reversal`。
- 旧组合持有期/卖点收益只做执行层诊断，不再作为候选排序主目标。
- `/limit-up` 默认回测是 10 万元、4 仓共享现金账户，只执行首板、二进三和高板，一进二保留为独立负样本研究。`2024-01-15..2026-07-10` 共 600 日的 D+1 收盘账户为 `100,000 -> 303,796.95`，243 笔闭合交易，胜率 `61.73%`、真实复利 `+203.80%`、最大回撤 `-10.36%`；旧二进三 `+499.18%` 和组合 `+1680.91%` 仅是信号日等权上界。冻结后前向仍为 0，状态保持 `research_only / simulation_eligible=false`，详见 `limit_up_real_cash_backtest.md`。
- 首次触板时间研究显示，09:25-09:30 的高封板率多数不可成交；以开板回封作为成交代理时，`09:30-10:00` 的 D+1 开盘扣费均值最好，`14:00-15:00` 最弱。

## Read First

- `strategy_optimization_ledger.md`: 当前策略决策台账、0.1.66 全量指标和下一轮执行闭环。
- `limit_up_top5_mvp.md`: 主板龙 Top5、秒板不可成交、保守/乐观成交和 D+1 开盘/收盘代理回测基线。
- `limit_up_short_term_factor_research.md`: 公开游资方法到可验证因子的映射、当前分桶证据和样本外验收顺序。
- `limit_up_real_cash_backtest.md`: 10 万元共享现金账户、2/4/6/8 仓冻结选择、全历史板位对照和旧信号复利差异。
- `limit_up_time_bucket_research.md`: 主板首次触板时间分段的封板率、D+1 溢价、扣费收益和回封成交代理证据。
- `d1_event_feature_research_2025_01_01.md`: 从 `2025-01-01` 起的全市场 D+1 大涨/大跌前一日量价、成交额/换手代理和特征分组研究集合。
- `d1_event_feature_research_2026_03_01.md`: 从 `2026-03-01` 起的 D+1 涨停/大涨/大跌前一日量价、成交额/换手代理和叠加特征分组研究集合。
- `quant_overlay_d1_event_features_2025_08_06.md`: 0.1.63 合入超跌低位承接前的 overlay 证据，用于说明旧策略漏掉了 `deep_low_core_group`，不再作为当前基线。

## Verification

- 容器环境已验证 0.1.66 候选质量：`2025-01-01..2026-07-07`，source recommendations `4022`，D+1 evaluated `2885`。
- 已验证：`uv run pytest tests/alphaagent/test_candidate_lanes_silver_rotation_bonus.py tests/alphaagent/services/quant/test_d1_event_feature_research.py tests/alphaagent/test_tail_entry_next_day_label.py -q`，`64 passed`。
- 已验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "deep_low_absorption_reversal or bottom_reclaim or secondary_breakout or execution_pool or quant_strategy_registry_dispatches_default_strategy"`，`23 passed`。
- 已验证：`python -m py_compile alphaagent/server/services/quant/strategies/dragon_pullback.py alphaagent/server/services/quant/candidate_lanes.py alphaagent/server/services/quant/factors.py alphaagent/server/services/quant/d1_event_feature_research.py`。
- 已验证：`git diff --check`。

## Next Work

1. 继续按全历史所有交易日逐日评审，但每日只看 `Top5 / Top10 / Top20`。
2. 优先修复 6 月修复窗口 Top20 后排、低吸首启、重叠信号、`after_gold_late`、2026-05 月弱桶。
3. 对弱桶抽具体赢家/输家，尤其看 D+1 涨停或接近涨停、D+1 大跌样本，并按龙回头、低吸、超跌反弹内部 lane 总结 D 日可见共同特征。
4. 只把有样本证据的窄规则合入默认策略；不做 Top11-20 补位、Top10 保护这类绕开研究的兜底。
