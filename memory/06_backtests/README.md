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
- `/limit-up` 当前产品只执行一个综合首板连续盘中评估策略：10 万元、最多两仓各 50%，`10:00-11:30 / 13:00-14:30` 逐快照评估，D+1 `14:30` 卖出。完整候选代理为 188 个信号、114 笔闭合，`100,000 -> 223,543.33`，胜率 `61.40%`、复利 `+123.54%`、最大回撤 `-8.75%`、利润因子 `2.24`、平均资金利用率 `23.83%`；双倍成本后 `+95.88% / -9.82%`。84 个结果请求有精确 14:30 分钟价，104 个使用收盘代理；历史缺少逐帧市场/板块资金和 Tick/L2，页面固定标为候选代理，详见 `limit_up_scheduled_execution_feasibility.md`。
- 仓位冻结只使用 `2026-04-14` 前 119 个信号：单仓为 `+74.61% / -23.51%`，未过 `-10%` 回撤门；通过门槛的 2/3/4 仓为 `+65.85% / +42.89% / +31.46%`，因此仍选择两仓。后段只验证，两仓为 `+33.98% / -5.81%`；只有一只合格票时只买 50%，不补杂毛。
- 一进二已从实时执行、产品交割单和组合回测中剔除，只保留内部反例研究。两仓独立一进二为 167 笔、胜率 `39.52%`、复利 `-63.94%`、回撤 `-64.10%`；滚动样本外和锁定留出均为负。旧 4 仓动态多板位回测已降为历史研究，不再是 `/limit-up` 默认口径。
- 首次触板时间研究显示，09:25-09:30 的高封板率多数不可成交；以开板回封作为成交代理时，`09:30-10:00` 的 D+1 开盘扣费均值最好，`14:00-15:00` 最弱。
- 首板 D+1 盘中退出研究显示，固定 13:30 在 84 个分钟价锁定留出信号的 10 万元四仓账户中为 `+29.44% / 61.33% / -6.21%`，略高于同样本收盘退出的 `+26.88% / 64.38% / -4.57%`；但每天强制买一只尾盘首板的近期真实现金回放为 `-38.80% / 48.89% / -44.19%`，不能为交易频率放宽硬门。
- 首板资本感知换仓可行性验证显示：只在新买点需要资金且最弱 D+1 旧仓 `current_return + intraday_fade <= 0` 时提前卖出，剩余仓位 14:30 退出；84 个分钟配对信号的 10 万元四仓收益由固定收盘 `+26.88%` 提高到 `+38.50%`，后半段时间验证由 `+16.91%` 提高到 `+26.84%`，双倍成本后仍为 `+33.83%`。历史新买点仍是扫板代理，因此只允许进入冻结前向研究。
- 实时概念共振已完成工程落地：D 日严格读取 D-1 成员版本，全市场行情 30 秒刷新，所有主板非 ST 的 5% 雷达先评估概念再做 Top5/两仓排序。2026-07-14 的 739 帧回放只证明 PCB 分组和封板前可见性，不证明收益提升；真实 D+1 胜率、复利和回撤必须等待 20/60 个前向交易日，详见 `limit_up_realtime_concept_replay_20260714.md`。
- `ef099769` 已补齐实时概念质量门：来源交易日错误或全市场覆盖低于 90% 时不落库、不替换有效快照，全局质量失败也会阻断每只候选的新买点。复核后历史买点、胜率和复利没有变化；预热代理未同时改善锁定留出胜率与复利，继续不进入执行，详见 `limit_up_realtime_concept_backtest_20260715.md`。

## Read First

- `strategy_optimization_ledger.md`: 当前策略决策台账、0.1.66 全量指标和下一轮执行闭环。
- `limit_up_top5_mvp.md`: 主板龙 Top5、秒板不可成交、保守/乐观成交和 D+1 开盘/收盘代理回测基线。
- `limit_up_short_term_factor_research.md`: 公开游资方法到可验证因子的映射、当前分桶证据和样本外验收顺序。
- `limit_up_real_cash_backtest.md`: 10 万元共享现金账户、2/4/6/8 仓冻结选择、全历史板位对照和旧信号复利差异。
- `limit_up_time_bucket_research.md`: 主板首次触板时间分段的封板率、D+1 溢价、扣费收益和回封成交代理证据。
- `limit_up_first_board_1330_exit_research.md`: 当前首板 D+1 13:15-14:30 真实分钟退出敏感性，以及“13:30 卖后每天强制买尾盘首板”的负期望现金回放。
- `limit_up_scheduled_execution_feasibility.md`: 综合首板连续盘中评估、D+1 14:30 卖出、时间后验证、候选代理边界和成交逆向选择压力；当前冻结方向。
- `limit_up_capital_aware_rotation_feasibility.md`: 动态转弱换仓的替代研究证据；产品未采用。
- `limit_up_live_gate_replay_20260714.md`: 2026-07-14 的 320 帧市场门、扫描速度、逐股无买点原因和 10 点前触板后回封对照。
- `limit_up_realtime_concept_replay_20260714.md`: 2026-07-14 的 739 帧 PCB 分组、封板前可见性和无未来函数边界；不作为收益证据。
- `limit_up_realtime_concept_backtest_20260715.md`: 实时概念质量修复后的同口径回测、板块预热对照、压力测试和前向验收结论。
- `d1_event_feature_research_2025_01_01.md`: 从 `2025-01-01` 起的全市场 D+1 大涨/大跌前一日量价、成交额/换手代理和特征分组研究集合。
- `d1_event_feature_research_2026_03_01.md`: 从 `2026-03-01` 起的 D+1 涨停/大涨/大跌前一日量价、成交额/换手代理和叠加特征分组研究集合。
- `quant_overlay_d1_event_features_2025_08_06.md`: 0.1.63 合入超跌低位承接前的 overlay 证据，用于说明旧策略漏掉了 `deep_low_core_group`，不再作为当前基线。

## Verification

- 容器环境已验证 0.1.66 候选质量：`2025-01-01..2026-07-07`，source recommendations `4022`，D+1 evaluated `2885`。
- 已验证：`uv run pytest tests/alphaagent/test_candidate_lanes_silver_rotation_bonus.py tests/alphaagent/services/quant/test_d1_event_feature_research.py tests/alphaagent/test_tail_entry_next_day_label.py -q`，`64 passed`。
- 已验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "deep_low_absorption_reversal or bottom_reclaim or secondary_breakout or execution_pool or quant_strategy_registry_dispatches_default_strategy"`，`23 passed`。
- 已验证：`python -m py_compile alphaagent/server/services/quant/strategies/dragon_pullback.py alphaagent/server/services/quant/candidate_lanes.py alphaagent/server/services/quant/factors.py alphaagent/server/services/quant/d1_event_feature_research.py`。
- 已验证：`git diff --check`。
- 打板相关完整套件已验证：后端 `594 passed`，前端 `45 passed`，Python 编译、生产构建和 Docker 健康检查通过。

## Next Work

1. 继续按全历史所有交易日逐日评审，但每日只看 `Top5 / Top10 / Top20`。
2. 优先修复 6 月修复窗口 Top20 后排、低吸首启、重叠信号、`after_gold_late`、2026-05 月弱桶。
3. 对弱桶抽具体赢家/输家，尤其看 D+1 涨停或接近涨停、D+1 大跌样本，并按龙回头、低吸、超跌反弹内部 lane 总结 D 日可见共同特征。
4. 只把有样本证据的窄规则合入默认策略；不做 Top11-20 补位、Top10 保护这类绕开研究的兜底。
5. 实时概念共振累计满 20 个交易日先验收采集和召回，满 60 个交易日再决定是否允许影响冻结收益结论。
