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
- `/limit-up` 当前只提供一个综合推荐：首板与二进三共用两仓现金账户、`10:00-11:30 / 13:00-14:30` 触发窗口和 D+1 `14:30` 退出；竞价只观察，同刻二进三优先，异时先到先买，不预留仓位。`limit-up-history-v15` 覆盖 603 日，正式组合为 307 个信号、149 笔闭合交易，`100,000 -> 366,449.06`，胜率 `63.0872%`、复利 `+266.4491%`、最大回撤 `-8.0275%`、利润因子 `2.4961`；时间验证段 `+72.2507% / -5.6825%`，双倍成本 `+215.1593% / -8.6789%`。高板组合未通过回撤门，只保留独立研究；完整证据见 `limit_up_unified_intraday_relay_backtest_20260715.md`。
- 2026-07-15 正式环境一致性审计确认：正式 `v2.5.18` 只有 18 个涨停事件交易日，回测为 13 个信号、2 笔交易和 `-0.6152%`；同一正式镜像在本地完整事件证据和相同 268 日选择区间下仍为 290 个信号、139 笔交易和 `+224.0076%`。主因是正式环境未执行同花顺 252 日事件回补，不是服务器性能或日期选择；详见 `limit_up_production_local_parity_20260715.md`。
- v14 弱市题材进攻只软化“半年触板不足 6 次、本地财报未覆盖、缺分歧修复”三个阻断，并继续要求半年至少 1 次涨停/3 次触板、低位或回调、10 点后、承接至少 55、板块热度至少 60 和龙一/龙二。它新增 14 个候选，双仓账户实际成交 9 笔（6 胜 3 负、均值 `+2.3768%`），5 笔因仓位占满跳过，并替换 3 笔原路径成交；账户复利相对 v13 净增 `34.2891` 个百分点。新增成交仅 1 笔有精确 14:30 价，8 笔为收盘代理；财报覆盖仅 `1,524/3,481`，历史点时行业成员覆盖约 `0.3355%`，不能把这组小样本称为实盘收益证明。
- 统一组合仓位冻结只使用 `2026-04-14` 前 145 个信号：单仓虽为 `+177.57%`，但 `-22.95%` 回撤未过 `-10%` 门；通过门槛的 2/3/4 仓为 `+112.82% / +70.40% / +55.82%`，因此仍选择两仓。只有一只合格票时只买 50%，不预留、不换仓。
- 一进二已从活跃板位、候选池、实时推荐、回测/API、缓存预热和前端合同中完全移除，不再保留当前内部研究入口。603 日候选池的一进二、入选和 `target_board=2` 均为 0，公开 API 返回 422；旧负收益数字只存在于历史报告。
- 首次触板时间研究显示，09:25-09:30 的高封板率多数不可成交；以开板回封作为成交代理时，`09:30-10:00` 的 D+1 开盘扣费均值最好，`14:00-15:00` 最弱。
- 首板 D+1 盘中退出研究显示，固定 13:30 在 84 个分钟价锁定留出信号的 10 万元四仓账户中为 `+29.44% / 61.33% / -6.21%`，略高于同样本收盘退出的 `+26.88% / 64.38% / -4.57%`；但每天强制买一只尾盘首板的近期真实现金回放为 `-38.80% / 48.89% / -44.19%`，不能为交易频率放宽硬门。
- v13 两仓早盘轮动验证显示：D+1 09:30 卖、10:00 后买可把闭合交易/买入日从 `131/94` 提高到 `173/112`，但复利从 `+170.57%` 降到 `+65.30%`，最大回撤扩大到 `-16.20%`，设计段为 `-5.85%`；10:15/10:30 后再买也未修复。94 个近期共同分钟样本中 09:45 为 `+120.99% / -9.22%`，但设计段低于 14:30，暂只作前向影子，不修改产品卖点。详见 `limit_up_first_board_1330_exit_research.md`。
- “D+1 14:30 仍涨停则持有到 D+2”同样未通过：19 个候选触发、账户实际续持 9 笔，主账户变为 `+123.80% / 60.47% / -13.56%`，低于固定 D+1 14:30 的 `+170.57% / 61.07% / -9.04%`。9 笔虽全部盈利，但平均从 D+1 可锁定的 `+9.7841%` 回落到 D+2 的 `+8.8292%`，并挤占后续仓位；不进入产品。
- 首板资本感知换仓可行性验证显示：只在新买点需要资金且最弱 D+1 旧仓 `current_return + intraday_fade <= 0` 时提前卖出，剩余仓位 14:30 退出；84 个分钟配对信号的 10 万元四仓收益由固定收盘 `+26.88%` 提高到 `+38.50%`，后半段时间验证由 `+16.91%` 提高到 `+26.84%`，双倍成本后仍为 `+33.83%`。历史新买点仍是扫板代理，因此只允许进入冻结前向研究。
- 实时概念共振已完成工程落地：D 日严格读取 D-1 成员版本，全市场行情 30 秒刷新，所有主板非 ST 的 5% 雷达先评估概念再做 Top5/两仓排序。2026-07-14 的 739 帧回放只证明 PCB 分组和封板前可见性，不证明收益提升；真实 D+1 胜率、复利和回撤必须等待 20/60 个前向交易日，详见 `limit_up_realtime_concept_replay_20260714.md`。
- `limit-up-live-v5` 已把概念启动改为内部绝对共振，全市场强度百分位只排序，不再决定 `launch/warming`。2026-07-15 的 75,748 条概念记录重放为每分钟平均 14.30 个启动、P90 28、最大 38，启动进入/退出由旧公式 716/704 降至 327/309；金种子酒临板概念提前至 10:11:19，巨人网络提前至 13:01:08，但个股硬门仍独立生效。该日是设计样本，不是收益验证，详见 `limit_up_absolute_concept_launch_verification.md`。
- `ef099769` 已补齐实时概念质量门：来源交易日错误或全市场覆盖低于 90% 时不落库、不替换有效快照，全局质量失败也会阻断每只候选的新买点。复核后历史买点、胜率和复利没有变化；预热代理未同时改善锁定留出胜率与复利，继续不进入执行，详见 `limit_up_realtime_concept_backtest_20260715.md`。

## Read First

- `strategy_optimization_ledger.md`: 当前策略决策台账、0.1.66 全量指标和下一轮执行闭环。
- `limit_up_top5_mvp.md`: 主板龙 Top5、秒板不可成交、保守/乐观成交和 D+1 开盘/收盘代理回测基线。
- `limit_up_short_term_factor_research.md`: 公开游资方法到可验证因子的映射、当前分桶证据和样本外验收顺序。
- `limit_up_real_cash_backtest.md`: 10 万元共享现金账户、2/4/6/8 仓冻结选择、全历史板位对照和旧信号复利差异。
- `limit_up_time_bucket_research.md`: 主板首次触板时间分段的封板率、D+1 溢价、扣费收益和回封成交代理证据。
- `limit_up_first_board_1330_exit_research.md`: 当前首板 D+1 13:15-14:30 真实分钟退出敏感性，以及“13:30 卖后每天强制买尾盘首板”的负期望现金回放。
- `limit_up_scheduled_execution_feasibility.md`: 首板连续盘中评估、D+1 14:30 卖出和候选代理边界的旧冻结基线；当前组合结论以统一接力报告为准。
- `limit_up_capital_aware_rotation_feasibility.md`: 动态转弱换仓的替代研究证据；产品未采用。
- `limit_up_live_gate_replay_20260714.md`: 2026-07-14 的 320 帧市场门、扫描速度、逐股无买点原因和 10 点前触板后回封对照。
- `limit_up_realtime_concept_replay_20260714.md`: 2026-07-14 的 739 帧 PCB 分组、封板前可见性和无未来函数边界；不作为收益证据。
- `limit_up_realtime_concept_backtest_20260715.md`: 实时概念质量修复后的同口径回测、板块预热对照、压力测试和前向验收结论。
- `limit_up_absolute_concept_launch_verification.md`: v5 内部绝对共振公式、2026-07-15 点时重放、全回测结果和历史数据边界。
- `limit_up_unified_intraday_relay_backtest_20260715.md`: 一进二移除、二进三统一盘中触发、四组冻结组合、独立板位、覆盖审计和正式运行验收。
- `limit_up_production_local_parity_20260715.md`: 正式与本地的镜像、数据覆盖、同区间回测矩阵和根因审计。
- `limit_up_additive_concept_entry_backtest_20260715.md`: 非连续涨停板位修复、短周期回马板新增候选、v11/v12 双仓成交替换和实时概念 OR 路径边界。
- `d1_event_feature_research_2025_01_01.md`: 从 `2025-01-01` 起的全市场 D+1 大涨/大跌前一日量价、成交额/换手代理和特征分组研究集合。
- `d1_event_feature_research_2026_03_01.md`: 从 `2026-03-01` 起的 D+1 涨停/大涨/大跌前一日量价、成交额/换手代理和叠加特征分组研究集合。
- `quant_overlay_d1_event_features_2025_08_06.md`: 0.1.63 合入超跌低位承接前的 overlay 证据，用于说明旧策略漏掉了 `deep_low_core_group`，不再作为当前基线。

## Verification

- 容器环境已验证 0.1.66 候选质量：`2025-01-01..2026-07-07`，source recommendations `4022`，D+1 evaluated `2885`。
- 已验证：`uv run pytest tests/alphaagent/test_candidate_lanes_silver_rotation_bonus.py tests/alphaagent/services/quant/test_d1_event_feature_research.py tests/alphaagent/test_tail_entry_next_day_label.py -q`，`64 passed`。
- 已验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "deep_low_absorption_reversal or bottom_reclaim or secondary_breakout or execution_pool or quant_strategy_registry_dispatches_default_strategy"`，`23 passed`。
- 已验证：`python -m py_compile alphaagent/server/services/quant/strategies/dragon_pullback.py alphaagent/server/services/quant/candidate_lanes.py alphaagent/server/services/quant/factors.py alphaagent/server/services/quant/d1_event_feature_research.py`。
- 已验证：`git diff --check`。
- v15 已在真实 PostgreSQL 重建 `2024-01-15..2026-07-15` 共 603 个交易日。全部打板后端 `489 passed`，完整非 Playwright 后端 `1490 passed, 8 skipped`，前端 `68 passed`；Python 编译、TypeScript/生产构建和 `git diff --check` 通过。容器版本为 `history-v15 / live-v6 / scheduled-v4 / cash-v4 / walk-forward-v6`，运行验收见 `limit_up_unified_intraday_relay_backtest_20260715.md`。

## Next Work

1. 继续按全历史所有交易日逐日评审，但每日只看 `Top5 / Top10 / Top20`。
2. 优先修复 6 月修复窗口 Top20 后排、低吸首启、重叠信号、`after_gold_late`、2026-05 月弱桶。
3. 对弱桶抽具体赢家/输家，尤其看 D+1 涨停或接近涨停、D+1 大跌样本，并按龙回头、低吸、超跌反弹内部 lane 总结 D 日可见共同特征。
4. 只把有样本证据的窄规则合入默认策略；不做 Top11-20 补位、Top10 保护这类绕开研究的兜底。
5. `limit-up-live-v6` 从统一盘中接力和绝对概念共振上线后独立累计点时证据；满 20 个交易日先验收采集和召回，满 60 个交易日再决定是否允许影响冻结收益结论。
