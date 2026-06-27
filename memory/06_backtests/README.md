# Backtest Evidence Index

这个目录保存 AlphaAgent 量化策略的回测报告、审计矩阵和可复现验证入口。判断当前策略状态时，先读本文件，再读 `strategy_optimization_ledger.md`，最后按需打开具体证据报告。截图、原始 JSON、CSV 和长日志不作为长期记忆保留。

## Current State

- 当前公开策略：`mainline_dragon_pullback / 0.1.21`。
- 基线区间：`2025-03-26` 至 `2026-06-18`。
- 执行模型：`legacy_next_open`，即 D 日收盘可见信号，D+1 日线开盘执行。
- 候选展示：评分前 `100`，分页 `20`。
- 组合执行事实：真实组合 BUY 候选前 `20`，最大持仓 `10`；但当前统一 acceptance 主口径不再用组合仓位结果做验收。
- 产品默认先沿用历史高收益组合回测 `#203/#194`：收益约 `+82.99%`，最大回撤约 `-15.59%`，胜率 `32.24%`，PF `1.6762`，买/卖/持仓 `224 / 214 / 10`。
- 组合回测默认不复用 `quant_signal_runs` 候选缓存；每次按当前代码重新生成候选。只有显式传入 `reuse_signal_cache=true` 的诊断/加速回测才允许读缓存，且这类回测不能作为产品基线。
- 干净 no-cache 分析样本：组合回测 `#275`，明确 `reuse_signal_cache=false`，收益约 `+48.80%`，最大回撤约 `-23.83%`，胜率 `29.76%`，PF `1.2420`，买/卖/持仓 `215 / 205 / 10`。
- `#275` 收益和胜率都没有超过 `#203/#194`，因此不能替代产品默认；它用于分析旧高收益为什么难以复现。
- 2026-06-21 旧组合口径全市场检测未通过：命令 `ALPHAAGENT_RUN_FULL_STRATEGY_ACCEPTANCE=1 ALPHAAGENT_REQUIRE_STRATEGY_PROMOTION=1 uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_full_acceptance_against_best_product_baseline -q` 跑完 `23:08` 后失败。该结果说明 no-cache 组合样本 `#275` 收益 `+48.80%`、胜率 `29.76%`、最大回撤 `-23.83%` 弱于产品基线 `#203`，但它已不再是当前统一候选质量 acceptance 的主验收口径。
- 历史 Top10 候选日 cohort 参考：共同候选日 `196` 个，当前/基线评估候选 `1857 / 1822`；当前平均收益 `+2.35%` vs 基线 `+2.52%`，胜率 `33.12%` vs `33.32%`，平均最大回撤 `-7.31%` vs `-7.09%`，收益回撤比 `0.321` vs `0.356`。该口径已升级为 Top20 主验收。
- 2026-06-22 统一完整 acceptance 已改为无仓位 Top20 候选质量：每个共同候选日分别取当前策略和产品基线 Top20，每只票独立 D+1 开盘买入，按当前卖点退出；不看现金、最大持仓、满仓、已有持仓或换仓。真实组合满仓/让位只作为诊断，不进入候选质量主验收。
- 2026-06-22 全市场无仓位 Top20 完整基准检测已跑完，耗时 `11:04`：共同候选日 `196`，当前/基线候选数 `3820 / 3600`；当前平均收益 `+1.86%` vs 基线 `+1.58%`，胜率 `32.81%` vs `32.43%`，但平均最大回撤 `-7.09%` vs `-6.91%`、最差回撤 `-34.13%` vs `-33.92%`。结论：本次没有改策略，只是验证新测试口径；现有策略 Top20 候选收益和胜率略胜，但回撤质量略弱。
- 2026-06-22 股票级失败审计见 `2026-06-22_strategy_failure_stock_and_market_audit.md`：历史 Top10 cohort 显示当前候选层略弱于基线但差距不大；真实组合层看得到多数基线大赢家，但同一信号日满仓且未触发让位。下一步应先继续做无仓位 Top20 因子钻取，再把真实组合让位、风险环境低吸启动门槛作为独立诊断实验。
- 2026-06-22 候选亏损和漏选赢家审计见 `2026-06-22_candidate_loss_missed_winner_audit.md`：Top20 独立候选 `2330` 簇、评估 `2316` 笔，平均收益 `+1.8149%`，中位数 `-5.8553%`，胜率 `38.73%`；亏损尾部集中在 `dragon_pullback + high_close_launch`、`choppy_rotation + unconfirmed/thin/high-close launch`、高收盘且 MA 发散的龙回头。可交易 20 日大赢家扫描显示大量机会不属于当前低吸/龙回头候选体系，少量已在候选但评分偏低，提示应做默认关闭的主线动量/情绪 lane，而不是扩大现有低吸买入频率。
- 2026-06-22 固定持有路径审计见 `2026-06-22_top20_fixed_holding_path_audit.md`：落库 `0.1.21` Top20 候选 `3600` 条、可评价 `3580` 条，D+1 开盘买后当天收盘胜率 `48.72%`、买后第二个交易日收盘胜率 `48.52%`；持有到 20 日平均收益 `+3.1133%`，但中位数仍为 `-1.3572%`，平均 MAE 扩到 `-10.3857%`。结论：Top20 候选是右尾收益驱动，普通候选短期胜率和持有体验都不足；下一步应先做弱桶降权/延迟确认的默认关闭实验，而不是扩大买入频率。
- 2026-06-22 当前代码 Top20 因子路径报告见 `2026-06-22_candidate_factor_path_report.md`：最近窗口 `2026-02-24..2026-06-22`、`max_symbols=500`、剔除疑似未复权断层后 Top20 独立路径 `1535` 条，平均收益 `-1.0516%`、中位数 `-4.4808%`、胜率 `25.99%`、平均最大回撤 `-6.9417%`，但 `34.92%` 能打出 `>=8%` MFE。结论：当前收益低不是完全没 alpha，而是普通候选纯亏太多、右尾票回撤/回吐大；下一步应默认关闭测试“支撑抬升型低吸/活跃中低位承接加分”与“滞涨低吸/高位拥挤/远离 MA5 降权”的组合。
- 2026-06-22 当前代码 Top20 启动路径报告见 `2026-06-22_candidate_launch_path_report.md`：同窗口、同 Top20 独立路径剔除疑似价格断层后，`34.20%` 候选能先触发 `+5%` 再跌破 `-3%`，`23.26%` 能先触发 `+8%`，但 `60.85%` 先跌破 `-3%`、`47.04%` 先跌破 `-5%`。弱桶集中在 MA5 超距、极窄均线无激活、高位拥挤启动、确认但无活跃资金、false_bull/warning 且无低位支撑、6-10 天低吸但无 fresh lift。结论：收益低的主因是太多候选先破位而不是先启动；`突破 5 日线` 只是症状，较好的启动更像低/中低位承接、贴近 MA5/MA10、MA5 上拐和活跃资金共同出现。
- 2026-06-22 V3/V4/V5/V6/V7 支撑抬升与启动质量后处理已在测试通道验证但未通过晋升，详见 `2026-06-22_candidate_launch_quality_postprocess_report.md` 和 `2026-06-22_postprocess_stock_audit_report.md`：同窗口 `max_symbols=500` 下，V5 cap8 clean `+0.1852% / 33.05% / DD -6.9380%`，V6 cap8 clean `+0.3846% / 32.97% / DD -6.9534%`、候选数 `746`，V7 cap8 clean `+0.1843% / 32.97% / DD -6.9339%`、候选数 `845`；均未优于 `v2_cap8` clean `+0.3884% / 33.33% / DD -6.9106%`、候选数 `845`。结论：低位/MA5 上拐和高位强右尾例外都有解释价值，但当前规则要么保留弱 warning 陷阱，要么压缩覆盖或引入普通替换票，不更新真实策略。
- 2026-06-25 V8 严格坏桶后处理已加入统一测试通道但未晋升真实策略：最近窗口 `2026-02-26..2026-06-24`、`max_symbols=500`、Top80 后处理 `v8_v2_strict_bad_bucket_cap8 + mfe8_keep6_giveback5` 为 `+0.3638% / 33.16% / DD -6.9513% / worst -32.8267%`、候选 `752`，优于同轮 default `-1.2723% / 27.67% / DD -6.9355% / worst -34.1282%` 和 V2 cap8 `-0.1627% / 32.07% / DD -7.1418% / worst -32.8267%`。V8 主要剔除 `other_confirmed_launch`、`repeated_launch`、`warning_far 高位弱启动`、`false_bull/w3 无支撑`、`6-10 天低吸但无干净抬升` 等先跌桶；但个股审计仍误伤右尾高位赢家，如 `000811.SZSE` 冰轮环境 `2026-04-16`、`000691.SZSE` 亚太实业 `2026-05-28/2026-06-09`、`000967.SZSE` 盈峰环境 `2026-03-24`。结论：V8 是当前更好的测试通道候选质量方向，但还需要右尾例外和 full acceptance 复核，不能更新真实策略。
- 2026-06-25 最新收益低归因已补进 `strategy_optimization_ledger.md`：当前 Top20 不是没有上拉，`1554` 笔默认候选平均 MFE `+9.8865%`、`34.17%` 能 surge；真正拖累是 `down5_before_up8` 占 `730/1554`、胜率仅 `4.11%`、平均 `-5.8907%`，以及 `39.45%` 纯亏和 `13.32%` 高 MFE 回吐。好买点不是简单突破 MA5，而是低/中低位或受控中位收盘、贴近 MA5/MA10、近期涨停/大阳活跃、fresh lift 或可交易 MA 结构共同出现。坏桶集中在 `other_confirmed mid/high no strong`、`unconfirmed extreme high`、`repeated high without right-tail`、MA5 超 `6%`、`tight quiet + warning>=3`、false-bull 高 warning 无支撑、`6-10` 天低吸但无 clean lift。
- 2026-06-25 东山精密 `002384.SZSE` 2026-06-12 复核：快速 `max_symbols=500` 候选快照未覆盖该股票，不能用缺席判断策略漏选；全市场 `screen_stocks(...max_symbols=5000, persist=false)` 重算确认其为 BUY rank `10`、score `91.81`。它是 4 天低吸蓄势、低位收盘 `0.2773`、MA5/MA10/MA20 附近、active strength `4`、近 20 日有涨停/大阳痕迹，D+1 `2026-06-15` 开盘买入后到本地最新 `2026-06-24` 为 `+15.5796%`，MFE `+24.7809%`，MAE `-3.1825%`。这类应作为“受控低吸蓄势 + 活跃资金 + fresh lift”保护样本，而不是因为未确认启动或周线标记一刀切扣分。
- 2026-06-22 东山精密 `002384.SZSE` 2026-06-12 回归排查：当前动态单股和全市场重算都仍是低吸蓄势 BUY，全市场 `screen_stocks(..., persist=false)` 主板重算约为 rank `10`、score `91.81`；旧版本落库曾在 `0.1.7/0.1.10` rank `1`、`0.1.22` rank `2`、`0.1.23` rank `3`。排名下降主因是 2026-06-17 引入 `candidate_lanes.py` 后，执行池按 `total_score + stealth_low_suction_opportunity_bonus` 排序，6 天且启动确认的低吸候选会拿到最高约 `+6` 机会分，而东山精密 4 天、未确认启动只约 `+1`。另有落库不一致：`0.1.21` run `#5772` 信号表中东山精密是 BUY，但推荐表未包含；用同一信号表按当前代码重选会到 rank `8`。这类历史推荐表不能直接当作当前策略是否漏选的证据，需要重算或做信号/推荐一致性检查。
- 2026-06-22 京东方A `000725.SZSE` 2026-06-16 买入点排查：单股回测审计显示该笔成交的 `signal_date=2026-06-15`、`execute_date=2026-06-16`。历史落库里旧版本 `0.1.8/0.1.10/0.1.18` 为 rank `7`、`0.1.22/0.1.23` 为 rank `8/9`、`0.1.21` run `#5771` 为 rank `16`。进一步复核发现 `weekly_top_fractal_risk` 的旧周K聚合按加载窗口起点每 5 根日K切组，不是自然周，因此同一信号日会随回测 lookback 起点改变而误标记。已改为 ISO 自然周聚合后，2026-06-15 的京东方A稳定为无 `weekly_top_fractal_risk`、score `95.1727`、全市场重算 rank 约 `13`。股票详情页已补充选中 K 线标记时的“对应信号日候选”展示，避免把执行日 6/16 误读成候选日 6/15 缺失。
- 2026-06-22 `weekly_top_fractal_risk` 只读审计见 `2026-06-22_weekly_top_fractal_risk_audit.md`：该标记不应直接视为坏候选。落库 `0.1.21` Top20 中，标记候选 `154` 笔胜率 `36.36%`、平均收益 `+1.5916%`，略好于未标记候选 `32.25% / +1.5755%`；但从 Top100 反事实加回 `+2/+4` 分重新选 Top20，收益和胜率提升的同时平均回撤从 `-6.9079%` 扩到约 `-7.07%`。本轮保留自然周修复；默认关闭的 `enable_weekly_top_fractal_relief` quick 矩阵未带来额外 Top20 改善，暂不晋升。
- 2026-06-22 已按候选亏损/漏选赢家方向做默认关闭实验：`enable_candidate_tail_risk_penalty`、`enable_mainline_momentum_lane`、`enable_mainline_momentum_risk_control`、`enable_mainline_momentum_hard_filter`。它们已接入回测参数、API 参数解析、run 序列化/回放、baseline 排除和统一测试通道，但默认策略不启用。
- 2026-06-22 已新增默认关闭实验 `enable_low_suction_buildup_quality_lane`：低吸蓄势质量独立加分，启动确认只作为额外加分；周线顶分型减免只对干净低吸蓄势小幅生效。该开关已接入回测参数、API 参数解析、run 序列化/回放、baseline 排除和统一测试通道。`002384.SZSE` 在 `2026-06-12` 全市场主板重算从默认 rank `6`、score `91.81` 变为开关开启后 rank `5`、score `93.78`，但最近 20 个交易日全市场 Top20 矩阵显示胜率和平均收益未提升，因此不能晋升默认策略。
- 2026-06-22 已新增默认关闭实验 `enable_surge_quality_lane`：尝试用信号日可见的活跃资金、收盘位置、均线宽度、启动质量和低吸蓄势状态区分猛拉候选与弱启动候选。它已接入回测参数、API 参数解析、run 序列化/回放、baseline 排除、前端 payload 类型和统一测试通道，但矩阵未通过：quick `max_symbols=120` 与扩展 `500` 都降低平均收益、胜率并扩大平均回撤。该开关只能保留为审计实验，不能晋升默认策略。
- 2026-06-22 扩展 quick 矩阵 `max_symbols=500` 发现，收窄后的 `enable_mainline_momentum_lane` 是更有潜力的收益来源：无仓位 Top20 平均收益/胜率从 default `-1.4597% / 24.79%` 改善到 `-0.4000% / 28.74%`，但平均回撤/最差回撤从 `-7.0668% / -34.1282%` 恶化到 `-8.1055% / -35.3124%`。补充的 `tail_plus_momentum_risk_control` 把收益/胜率进一步改善到 `-0.2998% / 29.06%`，但平均和最差回撤仍弱于默认；`tail_plus_momentum_hard_filter` 把最差回撤恢复到默认 `-34.1282%`，但收益/胜率和平均回撤仍未达晋升标准。结论：主线动量能找回部分大赢家，但当前风险控制/硬过滤仍不足，不能直接推广。
- 2026-06-22 当前卖点口径持有路径拆解：default Top20 最终平均收益 `-1.4597%`，但平均 MFE `+9.9975%`；`13.68%` 候选曾有 `>=8%` 浮盈后仍非正收益，`39.11%` 候选最大浮盈不到 `3%` 且最终亏损。momentum_only 放大赢家但也放大回撤：赢家平均 `+16.32%`，MFE>=8 后回吐为亏的比例 `17.51%`，纯亏损比例 `31.92%`。收益低不是单一买点问题，还包括同日候选池风险和卖点/利润保护不足。
- 2026-06-22 候选因子猛拉/下跌归因见 `2026-06-22_candidate_factor_surge_decline_analysis.md`，原始 JSON 见同名 `.json`：`#275` Top20 共 `3751` 条 ready 样本，10 日平均收益 `+2.30%` 但中位数 `-0.46%`，`59.26%` 先触发亏损。猛拉主要来自 recent limit-up / 大阳线活跃、宽 MA 趋势结构、`0.35-0.58` 下中位收盘等组合；下跌集中在 `high_close_launch`、弱量/重复/过晚启动、`low_suction_days 6-10` 未激活、unknown family 和同日 Top20 集体恶化。结论：当前评分把强趋势右尾和高位失败启动混在一起，下一版应做默认关闭的窄版 surge-quality lane 加 weak-launch/high-close/stale-low-suction 降权，而不是扩大买入频率。
- 2026-06-22 严格 Top20 补充复核直接查 `#275` 因子快照和 outcome，过滤为 `rank 1..20 / BUY / executable / ready`：`3580` 条平均 10D `+1.98%`、中位数 `-0.60%`、胜率 `47.54%`；按同股连续候选只取首个后仍为平均 `+1.66%`、中位数 `-0.73%`、胜率 `47.16%`。可见好桶是“活跃资金 + 低/下中位收盘 + MA 3..18 + 贴近 MA5”，坏桶是“高位弱启动”“6-10 天低吸但无活跃资金”“极窄均线但无激活”。同日 Top20 构成比单个行情标签更重要：`false_bull/w3` 既可能是 2026-06-03 这种强主线日，也可能在高位弱启动拥挤时转弱；下一版只能做默认关闭的日级候选池质量 gate，不能粗暴过滤 `false_bull`。
- 2026-06-22 quick 候选质量矩阵有两组口径。早期 `max_symbols=120` 只用于烟测；`max_symbols=500` 是当前主要反馈口径。修复测试通道行情上下文补齐后，最新窗口 `2026-02-24..2026-06-22` 显示：default 约 `-1.37% / 24.76% / DD -7.08% / worst -34.13%`；`momentum_only` 约 `-0.30% / 29.01% / DD -8.10% / worst -35.31%`；`tail_plus_momentum_risk_control` 约 `-0.18% / 29.26% / DD -7.85% / worst -35.31%`；`momentum_risk_control_pure_loss_plus_mfe8_giveback` 约 `-0.04% / 29.52% / DD -7.77% / worst -35.31%`。收窄后的 `tail_momentum_hard_pure_loss_plus_mfe8_giveback` 可把 worst DD 拉回 `-34.13%`，但平均回撤仍约 `-7.45%`，弱于 default。结论：主线动量和利润保护能明显改善收益/胜率，但回撤 gate 仍未通过，全部保持默认关闭，不更新真实策略。
- 2026-06-22 已新增并验证默认关闭实验 `enable_top20_day_quality_gate`：用同一候选日预排序 Top20 的结构区分“活跃中低位承接日”和“高位弱启动拥挤日”，再重排当天候选。它已接入回测参数、API 参数解析、run 序列化/回放、baseline 排除和统一测试通道，但 quick `max_symbols=500` 失败：default `-1.3199% / 25.63% / DD -7.1669%`，day gate `-1.4288% / 25.56% / DD -7.2347%`。挤入/挤出归因显示它移除的 67 票平均 `-0.3361%`，新增的 67 票平均 `-2.8664%`，并错杀部分右尾赢家。结论：日级候选池结构有解释价值，但整日重排太粗，不能晋升。
- 2026-06-22 统一测试通道修复了一个基础一致性问题：`enable_candidate_tail_risk_penalty`、`enable_mainline_momentum_lane`、`enable_surge_quality_lane`、`enable_low_suction_buildup_quality_lane`、`enable_pure_loss_weak_bucket_penalty` 等实验读取 `dynamic_market_regime / market_warning_level`，因此在评分缓存命中时也必须补齐信号日行情上下文。已补单测覆盖，避免矩阵在 `unknown/w0` 下误评行情相关因子。
- 2026-06-22 新增/复核的默认关闭实验结论：`enable_pure_loss_weak_bucket_penalty` 单独失败，最新 quick 约 `-1.50% / 24.56% / DD -7.20%`；`mid_profit_giveback_only` 和 `exit_dynamic_failed_plus_mid_profit` 小幅改善 default，分别约 `-1.21% / 26.25% / DD -6.93%`、`-1.17% / 25.99% / DD -6.86%`；`high_risk_d2_follow_through` 继续失败，约 `-1.72% / 23.92% / DD -7.55%`。结论：广泛 D+2 延迟确认和简单弱桶排序惩罚不是主方向，利润保护有效但幅度不足。
- 2026-06-22 固定 10 日路径补充分析显示，猛拉不是简单突破 5 日线：`active>=3 + close<0.35 + MA 3-6` 的 10 日平均收益 `+10.86%`、胜率 `50.00%`，而 `thin_volume_launch + high close`、`other_confirmed_launch + mid-high close`、`repeated_launch + high close` 和 unconfirmed 高位/中高位收盘明显拖累。部分 active 宽 MA 样本 MFE 很高但最终收益差，说明后续必须把“信号日弱桶降权”和“卖点/利润保护”分开测。
- 2026-06-22 最近窗口 no-position Top20 复核确认：当前收益低的核心不是没有上拉，而是候选池右尾和亏损/回吐混在一起。`2026-02-24..2026-06-22`、`max_symbols=500` 下，default 平均最终收益 `-1.3148%`、胜率 `25.69%`、平均 DD `-7.1613%`，但平均 MFE 仍有 `+10.0565%`；`momentum_risk_control + pure_loss + mfe8_giveback` 把收益/胜率推到 `-0.0279% / 29.89%`，但平均/最差 DD 恶化为 `-7.8347% / -35.3124%`。同日回填重排的窄组合反事实最好仅到约 `+0.0781% / 30.08% / DD -7.6687%`，仍未通过回撤 gate。结论：继续默认关闭研究，不更新真实策略。
- 2026-06-22 follow-up：`mfe8_keep4_giveback6` 利润保护改善但未晋升。单独开启从 default `-1.3148% / 25.69% / DD -7.1613%` 改到 `-1.1368% / 27.55% / DD -6.9664%`；与 momentum/pure-loss 组合可到 `+0.0371% / 30.71%`，但平均/最差 DD 恶化为 `-7.8020% / -35.3124%`。同轮固定持有检查显示 D+1/D+2/D+5/D+10 close 胜率约 `49.26% / 46.06% / 42.32% / 38.72%`，说明不能简单长拿，必须分开处理纯亏路径和高 MFE 回吐路径。
- 2026-06-25 Top80 后处理测试入口：`ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT=1 uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_quality_postprocess_report -q -s`。它不改变真实策略，只从每天当前 Top80 池做信号日可见因子重排/坏日压缩，再独立模拟 Top20/Top10/Top5。报告现在同时输出 V2/V3/V4/V5/V6/V7/V8、`data_quality` 和 `overall_without_price_discontinuity`。当前测试通道最好的是 `v8_v2_strict_bad_bucket_cap8 + mfe8_keep6_giveback5`，但因覆盖压缩且仍误伤右尾高位赢家，只能作为下一轮研究候选，不能晋升真实策略。
- 2026-06-22 测试通道新增本地 Top80 候选快照缓存：`_current_code_top_candidate_rows_with_context()` 会把同一窗口/股票池/top_n/策略 schema 的候选和 bars 缓存在 `memory/06_backtests/cache/`，命中时打印 `[candidate_snapshot_cache] hit`；可用 `ALPHAAGENT_DISABLE_CANDIDATE_SNAPSHOT_CACHE=1` 关闭。该目录已加入 `.gitignore`，不进入长期 memory。验证：`max_symbols=120` postprocess 从 miss `40.72s` 到 hit `1.11s`，`max_symbols=500` 从 miss `3:08` 到 hit `3.42s`，default/V2/V6/V7 clean 指标完全一致。
- 2026-06-22 `/quant` 回测页已改成候选质量主视图：进入回测页后先显示“候选 Top20 质量”和“候选独立买卖质量”，包含候选年化参考、候选胜率、年度胜率、平均收益、平均回撤和可评价候选；组合收益、成交、持仓和交易表只作为“组合诊断”展示。
- 2026-06-22 候选年化主展示口径已修正：旧信号日复利口径把完整持有期收益按信号日逐日复利，`#203` 会得到 `+21547.29%`，现已降级为调试字段 `signal_day_compound_annual_return_pct`；主展示 `annual_return_pct` 改为平均单笔收益按平均持有天数折算，`#203` 约为 `+41.45%`。
- 2026-06-22 `GET /api/backtests/{id}/candidate-trade-quality-report` 已增加进程内短缓存，同一 `backtest_id/rank_limit/sample_limit/date range` 10 分钟内复用结果；`#203` 首次约 `7.5s`，缓存命中约 `0.05s`。接口返回 `quality_cache=miss/hit` 用于排查。
- 已新增只读收益/胜率归因入口：`GET /api/backtests/{id}/performance-attribution`，前端回测详情页的 `交易归因` 页签显示“收益/胜率差异归因”。`#275` 可对比历史高收益参照 `#203`，但只能作为候选生成链路差异分析，不能当成同输入参数对比。
- 公开策略仍只保留一个：`mainline_dragon_pullback`。低吸首启、龙回头、重叠冲突、行情阶段都是内部解释/审计维度，不拆成普通用户要手动切换的多策略。

## Current Conclusions

- 行情阶段 `主升 / 震荡 / 退潮 / 回暖` 当前只做审计、风险上下文和用户解释，不直接进入默认评分、排序、买卖或仓位。
- `低吸蓄势` 不是每天买入；默认产品口径允许高分、无硬风险的低吸蓄势进入 BUY，`low_suction_launch_confirmed=false` 只作为质量/阶段标签。只有显式开启 `require_low_suction_launch_confirmation` 研究开关时，未确认启动才会被硬降为 WATCH。
- 股票详情主图应显示独立单股策略路径的 `买入 / 拒买 / 卖出`，不看组合是否满仓；组合回测用于评估真实仓位路径。
- 候选独立买卖质量报告是新的只读候选质量入口：它不看资金、最大持仓、组合满仓、已有持仓或换仓，每个候选簇只模拟一笔理论交易，并明确不进入信号评分或默认买卖规则。
- 2026-06-21 修正候选独立买卖质量口径：同股连续 BUY 簇只用首个可见 BUY 作为入场信号，D+1 开盘买入，随后逐日按当前策略卖点卖出；簇内后续更高分/启动确认只作为审计字段，不用于交易。全量 rank20 候选簇约 `2330` 个，评估 `2316` 个，胜率 `38.73%`，平均收益 `+1.81%`，中位数 `-5.86%`，平均最大回撤 `-7.92%`，平均最大冲高 `+16.60%`。
- 候选独立买卖报告现在同时展示两层概念：整体 TopN 是“全历史每个信号日排名前 N 的独立候选交易汇总”；细化表按信号日展示当天 Top10、Top20 和当前 TopN 候选后续胜率/收益。排名段 `1-10 / 11-20 / 21-50 / 51-100` 不等同于累计 TopN。
- 候选池整体不差，收益损耗更多发生在真实组合执行、满仓、替换质量、卖点和趋势赢家路径保护。
- `#274` 的归因曾显示，相比旧高收益 `#203`，下降主因是赢家贡献减少：毛盈利少约 `37.76` 万，毛亏损只多约 `1.03` 万；`trend_trailing_stop` 趋势赢家从 `33` 笔降到 `24` 笔，贡献减少约 `34.98` 万。旧高收益不是靠更高持仓上限得到，二者核心仓位参数同为 `max_positions=10`、`candidate_limit=20`、单票 `10%`。
- 2026-06-21 修复后持仓敏感性复核显示，单纯把最大持仓从 `10` 放到 `20` 不是提升方向：资金中性 `20 x 5%` 收益降至 `+29.47%`；固定单票 `10%` 的 `20` 槽位收益约 `+45.17%` 且出现 `488` 次现金不足。`5 x 20%` 收益约 `+59.09%` 但回撤扩大到 `-26.00%`，说明更集中可能更赚钱但风险更高。
- 已修复一个基础实验风险：组合回测默认不再静默复用 `quant_signal_runs` 候选缓存；如果显式打开 `reuse_signal_cache=true`，仍必须匹配当前 `signal_evidence_schema_version`，且该回测会被排除出产品基线。新策略只有在收益率和胜率都超过历史高收益默认时才能晋升产品默认。
- 已修复行情矩阵“行情未知”误显示：回测信号事件的候选证据保存在 `raw.evidence`，行情/策略族矩阵现在会展开该字段并按缺失行补算可见行情上下文。`#274` 已验证能归到震荡、退潮、主升，`#275` 后续报告应以同一逻辑刷新。
- 弱持仓换仓、高分换仓、低吸硬门槛、低吸生命周期加分、失败启动早退等多轮默认关闭实验均未超过产品基线，不能晋升默认。
- 每次策略优化必须更新 `strategy_optimization_ledger.md`，不能只留下零散报告。

## Key Evidence

### Current Entrypoints

- `strategy_optimization_ledger.md`: 统一策略优化台账，记录当前基线、主要实验结果、是否晋升和复核入口。
- `tests/alphaagent/test_quant_strategy_acceptance.py`: 统一策略测试通道。快速通道默认用本地最新数据窗口和小股票池重算当前策略 Top20 候选，并验证独立候选路径可评估；矩阵报告通道需显式设置 `ALPHAAGENT_RUN_STRATEGY_MATRIX_REPORT=1`，会输出 default、low-suction-buildup、tail-only、momentum-only、momentum-risk-control、momentum-hard-filter、surge-quality、Top20 day-quality、tail+surge、tail+momentum、tail+momentum-risk-control、tail+momentum-hard-filter、profit-protection 和组合变体的同口径候选质量对比；Top80 后处理通道需显式设置 `ALPHAAGENT_RUN_STRATEGY_POSTPROCESS_REPORT=1`，会输出当前 Top80 的 post-score 重排、弱日压缩、V2/V3/V4/V5/V6/V7/V8、价格断层审计和剔除疑似断层后的指标，并默认复用本地 candidate snapshot cache；完整通道需显式设置 `ALPHAAGENT_RUN_FULL_STRATEGY_ACCEPTANCE=1`，用本地完整数据日期对齐当前策略和产品基线的同候选日 Top20。主口径是无仓位候选质量：D+1 开盘独立入场，按当前策略卖点逐日退出，整体比较平均收益、胜率、平均/最差回撤；日胜负只作辅助，不看组合现金、最大持仓、满仓、已有持仓或换仓。所有测试通道参数强制 `reuse_signal_cache=false`、`persist=false`、`exclude_from_product_baseline=true`。
- `tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_factor_path_report`: 显式因子路径解释通道，需设置 `ALPHAAGENT_RUN_CANDIDATE_FACTOR_PATH_REPORT=1`；建议同时设置 `ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500`。它解释当前 Top20 候选为什么猛拉、纯亏、下跌或回吐 MFE，只读，不改变评分、买卖或仓位。
- `tests/alphaagent/test_quant_strategy_acceptance.py::test_current_strategy_candidate_launch_path_report`: 显式启动路径解释通道，需设置 `ALPHAAGENT_RUN_CANDIDATE_LAUNCH_PATH_REPORT=1`；建议同时设置 `ALPHAAGENT_QUICK_ACCEPTANCE_MAX_SYMBOLS=500`。它把当前 Top20 拆成先 `+5/+8` 与先 `-3/-5` 路径，并按信号日可见因子解释什么时候会猛拉、什么时候买后先跌；只读，不改变评分、买卖或仓位。
- `GET /api/backtests/{id}/performance-attribution`: 解释当前回测为什么弱于历史高收益参照；默认选择同策略、同版本、同区间、同核心仓位参数里的历史最高收益 run 作参照。
- `GET /api/backtests/{id}/candidate-trade-quality-report`: 判断候选本身质量的首选入口；前端回测主视图直接显示“候选 Top20 质量”和“候选独立买卖质量”，包含整体 TopN、年度胜率、每日排名段和信号日细化。候选报告只读，不改变策略、评分、买卖或仓位。
- `2026-06-22_candidate_loss_missed_winner_audit.md`: Top20 候选亏损桶、MFE 回吐样本、全市场可交易大赢家漏选/低分样本，以及炒股养家心法到 AlphaAgent 可测假设的映射。
- `2026-06-22_candidate_factor_surge_decline_analysis.md`: `#275` Top20 因子归因，回答候选什么时候猛拉、什么时候买后下跌，以及为什么当前总分还不够区分强趋势右尾和失败启动风险。
- `2026-06-22_candidate_factor_path_report.md`: 当前代码最近窗口 Top20 因子路径归因，剔除疑似价格断层后解释当前质量下降来自纯亏过多和右尾 MFE 回吐，而不是完全没有上拉机会。
- `2026-06-22_candidate_launch_path_report.md`: 当前代码最近窗口 Top20 启动路径归因，直接解释候选买后是先上拉还是先下跌，以及 MA5/低吸蓄势/活跃资金/行情 warning 的组合影响。
- `2026-06-22_candidate_launch_quality_postprocess_report.md`: V4/V5 启动质量后处理复盘，说明为什么低位 MA5 上拐保护方向有效但仍未超过 V2 cap8，不能晋升真实策略。
- `2026-06-22_postprocess_stock_audit_report.md`: V2/V5/V6/V7 后处理的个股级移除/新增审计，包含拉动位置、MA/资金代理、压力位、行情 warning 和入场后路径；说明 broad score relief 无法修复 V2 误伤，下一步应先做 Top80 快照缓存和更精准的个股特征例外。
- `2026-06-22_top20_fixed_holding_path_audit.md`: Top20 候选从 D+1 开盘买入后的固定持有路径，用来解释“第二天胜率低、长拿体验差”的结构性原因；只读，不进入评分或买卖。
- `memory/09_decisions/decisions.md`: 当前产品和策略长期决策。
- 旧日期报告只作为历史排查材料；不要把日期报告当成当前状态入口。

### What The Ledger Covers

- 产品基线 `#203/#194`，以及 `#275` 为什么只能作为 no-cache 分析样本。
- 行情阶段、策略族、低吸/龙回头边界。
- 低吸 MA10 回踩、低吸触发日确认、低吸分支卖点和替换质量。
- `support_stop` 拆分、失败启动控制、浮盈回吐。
- 满仓机会、换仓、D+1 执行可行性和趋势赢家保护。
- 股票详情牛熊线和统一 `买入 / 拒买 / 卖出` 标记。

## Superseded Or Historical Evidence

- `2026-06-11_*` 和 `2026-06-14_*`: 旧严格尾盘/分钟模型和早期参数网格，保留为历史排查材料，不作为当前产品默认。
- `#62` 严格 14:30 回测：历史证据，不再是当前默认流程。
- `#275`: 当前干净 no-cache 分析样本，默认重算候选，明确 `reuse_signal_cache=false`；因收益和胜率都低于 `#203/#194`，不作为产品默认。
- `#274`: 缓存边界修复前的当前 schema 参照样本；不再作为当前产品基线。
- `#203/#194`: 当前产品默认沿用的历史高收益结果；后续要分析其候选链路，但不能用收益/胜率更低的新回测替代。
- `#204`: 混入局部候选刷新，已排除产品基线。
- `#213`: 当前 schema 候选缓存下的审计样本，接近修复后可复现基线。
- `#269`: 缺少 D+1 执行日弱持仓复核的无效中间样本。

## Open Risks

- 当前基线仍不能证明熊市、震荡市和非科技主线下稳定有效。
- 历史资金流和主线板块覆盖不足，不能宣称已经稳定量化科技主线或新主线轮动。
- 当前最重要的问题不是再加宽泛因子，而是执行一致性：候选前列赢家如何进入真实组合，同时不破坏已有趋势赢家。
- 最新本地行情上下文截至 `2026-06-18` 为 `假强势`：指数 5 日/20 日收益为正，但广度弱、资金恐慌流出、风险等级 `4`。真实交易前必须先更新本地日线和板块资金；在该上下文下不应扩大未确认低吸买入频率。
- 回测实验基线已收紧：默认组合回测不复用候选缓存；显式缓存回测必须绑定当前 `signal_evidence_schema_version` 且不能进入产品基线。后续参数敏感性结论应同时对照产品默认 `#203/#194` 和 no-cache 分析样本 `#275`。
- 策略更新流程已新增 acceptance 测试通道，但全市场完整通道仍是慢测；日常快速通道只能证明链路和小样本没有明显崩坏，不能作为策略变更证据。当前完整候选质量 gate 要求 Top20 平均收益、胜率、平均回撤和最差回撤均不弱于产品基线。
- 当前 `stock_daily_bars` 来自 AkShare 未复权日线，`raw={}` 且大量行 `change_pct=None`，除权/送转附近会出现约 `-20%~-30%` 的价格断层。测试通道已能审计疑似断层，但真实回测/数据同步仍未改成统一前复权或带复权因子；任何策略晋升前必须先解决或显式审计这一数据质量问题。
- 2026-06-25 矩阵报告已共享同一批日线和原始评分缓存，并修复实验 variant 复用缓存时缺少市场上下文的问题。Top80 后处理和个股审计已有本地候选快照缓存，`max_symbols=500` 命中后可在数秒内复用候选；快照写入已改为进程唯一临时文件，避免两个报告并行写同一缓存时竞争。矩阵报告和全市场 `5000` 只仍未完整快照化。全市场 `5000` 只曾在 `2:18` 后手动中断，瓶颈是 `dragon_pullback` 特征逐日逐票重算和市场上下文补算。后续如要做 full matrix，应扩展同版本候选快照、分段进度输出或复用评分快照。
- `support_stop`、低吸确认后无承接、浮盈回吐和卖后替换质量仍需要更窄、默认关闭、可解释且无未来函数的实验。

## Maintenance Rule

- 新策略实验优先同步 `strategy_optimization_ledger.md`；只有需要长期复核的大型实验才写独立 Markdown 报告。
- 本文件只保留当前结论和证据入口，不追加大段流水、接口响应或表格。
- 原始 JSON、截图、CSV 和长日志不放入长期记忆；必要数据应汇总进 Markdown 报告，并保留可复现的接口、测试或命令入口。
