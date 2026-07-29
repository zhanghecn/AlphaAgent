# AlphaAgent Decisions

## Current State

- 产品名为 AlphaAgent；内部 Python 包继续使用 `vnpy`，保持官方插件兼容。
- 不修改 `vnpy/` 或官方 examples，除非用户明确要求。
- 本地开发统一使用 `docker compose up --build`；服务器部署和镜像发布由 `deploy/`、
  Dockerfile、Compose 和 CI 承担。
- 产品保留今日市场、大盘择时、概念主线、短线研究、全 A 股票和数据管理；
  `/short-term` 承载彼此隔离的打板与低吸研究。
- 自动同步、历史回放和实时推荐都从配置的数据源与 PostgreSQL 自主构建，不以复制现有
  数据库或人工 CSV 作为部署流程。

## Limit-up Current State

### Formal contract

- 唯一当前执行合同为 `limit-up-core-abc-v2`；历史正式过滤、实时真实触板、调度和现金
  账本使用同一公共质量合同。`limit-up-core-abc-v1` 只标识冻结历史候选
  数据集和 A/B/C 估计先验；数据库旧帧保留审计，但不会重标版本或进入 v2 前向成绩。
- A/B 基座在原正确财报、结构、lane、盘中支撑和同股盈利门通过后，要求
  `2 <= prior_limit_count_126 <= 6`。D-1 行业成交额相对前 5 日均值 `>=1.0` 为 A，
  其余为 B。C 只覆盖同股样本不足、联合率低或半年涨停超过 6 次，并交叉 D-1 资金/
  回撤或触板前概念已有 2-4 只封板且最高至少二板；概念名称不写死。
- 同一时点优先级为 `A > C > B`，跨时点严格按信号实际到达顺序。A/C 首板和二进三
  10:00 后行动；B 首板 10:30 后首次触板或回封才行动。C 每日最多一笔，且此前不能
  已观察到 A/B；两仓尚无 A 时最多持有一个 B/C，为稍后 A 保留一仓。
- 公共胜率和 D+1 预期以 A/C/B 冻结层级先验与决策时点前同股闭合样本按 10 笔强度
  收缩。逐票要求质量胜率 `>=50%` 且 D+1 预期为正；50% 是候选入围线，整体策略闭合
  胜率目标仍是 `>=60%`。只有真实触板或回封并重新通过完整公共质量门，才形成当前正式
  扫板买点。
- 已反事实测试用“包含炸板的全触板 D+1 胜率为主、历史封板率为独立底线”替换联合率。
  九组 `封板率40/50/60% x D+1胜率50/55/60%` 均未同时改善数量、复利和回撤；最宽
  方案新增34笔平均收益为 `-0.29%`，所以正式联合率门保持不变，全触板字段仅作诊断。
- 正式策略保留首板、二进三、正式费用和 D+1 官方日线收盘退出。一仓/两仓现金账户是
  独立的回测容量模拟，不能截断正式推荐或充当全量质量分母。
  竞价止盈、盘中最优退出和结果后选择卖点不属于正式合同。
- `actionable_recommendations` 是不受两仓容量限制的正式触发列表；`portfolio` 才对应
  两仓现金账户。全量规则质量和两仓到达顺序结果必须分别报告。
- 合格的 `near_limit/sealed/resealed` 可以形成正式涨停价排队买点；封板/回封不保证成交。

### Formal historical and forward status

- 808 个交易日是行情背景；真实事件覆盖已推进到 `2026-07-28`，正式闭合
  推荐覆盖 `2025-07-10..2026-07-23`，不是因为日线只有这一年。
- v2 全历史按因果顺序重放：140 笔闭合独立交割，`96/140=68.5714%`，平均净收益
  `+2.0988%`，独立信号复利 `+687.9533%`，最大回撤 `-21.0357%`，硬亏
  `10/140=7.1429%`。A/C/B 历史分层继续作为公共质量收缩先验，不再与当前聚合结果
  拼接成同一份成绩。
- 两仓成交 94 笔、`69/94=73.4043%`，平均净收益 `+2.4371%`、复利
  `+195.3585%`、回撤 `-8.8761%`。两仓跳过 46 条，其中 34 条因给后续 A 保留仓位。
- 单仓成交 78 笔、`54/78=69.2308%`、复利 `+350.8300%`、回撤 `-19.2428%`，
  未达到单仓 `+400%` 目标。
- 最近闭合窗口 `2026-07-14..23` 全量只有 `6/13=46.1538%`，两仓 `2/4=50%`、
  复利 `-1.0721%`；冻结后历史代理两仓只有 3 笔且复利 `-2.2819%`。当前不能以全历史
  达标替代近期退化事实。
- 当前状态固定为 `historical_proxy_pass_forward_unconfirmed`；历史 68.5714% 不是实盘
  胜率承诺。自然前向从 v2 服务重建后的下一有效交易日起累计；7 月 21-24 日旧 v15 帧和
  7 月 27 日周一交易日的旧 A+B/A+B+C 帧都不是新代码自然生成，不进入前向分母。
- 核心门前 560 笔闭合事件有 179 个候选日，A+B 只保留 78 笔/50 日；排除组
  `235/482=48.7552%`、复利 `-32.0997%`，因此不能整体撤门。129 个无 A+B 买点日的
  全天空仓条件带有未来信息，只用于逆向特征发现。改成触板时可知的“此前尚无 A+B”，
  并交叉 D-1 行业量能、个股回撤和触板前动态概念梯队后，形成当前 C。原逆向研究的
  `46/71=64.7887%` 是晋级前定义；接入正式时间门和同秒因果顺序后，冻结闭合结果为
  `46/72=63.8889%`；加入 v2 公共估计门后 C 实际闭合为 `43/69=62.3188%`。历史概念
  成员代理仍要求从下一有效 v2 交易日起自然前向确认。
- 财报点时修复后的前一正式基线是 243 个全量信号、239 笔闭合，胜率
  `54.8117%`、平均净收益 `+0.5687%`。它现在只用于解释 A+B 的增量，不再是当前合同。
- 前一财报修复基线的首板回测已核实为触板价口径：572 个质量合格候选全部按涨停价记账；正式双窗口
  内 545 个中 498 个首次触板触发、47 个窗口内回封触发。最终两仓 127 笔成交的原始价
  与账面成交价也全部等于涨停价。该结论只证明候选代理口径，不证明 Tick/L2 排队可成交。
- 旧 800 日约 70% 是 `68/97` 的两仓成交子集；同批全量推荐只有 `102/164=62.1951%`。
  它还受旧财报覆盖偏差影响，不能作为当前实时推荐质量承诺。
- 旧覆盖捕获的是资金承载、行业前排和财务质量的混合偏差，不是“有财报”本身。
  `行业 Top5 + D-1 成交额前30%` 在已查看历史为 24 笔、70.83%，但 2026-Q3 只有
  3 笔、33.33%，只能作为动态风格假设。

### Financial point-in-time rules

- 季度财报按报告期覆盖全市场，不再每天轮转 100 只，也不因已有 4 期停止更新。
- 回测和实时都只读取 `announcement_date <= signal_date` 的最新报告；归母净利润同比使用
  正确同比字段，写入后同步失效财报与实时缓存。
- 本地财报缺失是数据覆盖错误，不是上市公司未披露，也不能作为恢复旧高胜率的隐式筛选。

### Removed early-entry experiment

- 未校准的板前概率、训练/评分模型和兼容回退合同保持移除。独立板前榜按单一正式合同设计：
  只展示“若此刻真实触板就会成为正式买点”的股票，不混入正式买点。`2026-07-20..29`
  历史帧中板前时间为空被解析为 `00:00`，巨人网络因此只在 10:53 触板后出现。该缺口已
  修复：未触板 `near_limit` 信号使用当前快照作为临时预审时点，不写入真实买入/触板时间；
  触板后仍重新运行相同 A/B/C 门。本地回放已验证，下一交易日以新保存帧确认页面展示；详见
  `memory/06_backtests/limit_up_preboard_actual_frame_audit_20260729.md`。
- 3% 只是雷达发现下限。公开板前候选必须同时满足 A/B/C 触板就绪、lane 验证通过、无其他
  阻断和快照新鲜；任何一项不满足都不公开。
- 当日轨迹只读取当前 `limit-up-core-abc-v2` 帧；只有 `action=buy_now` 且公共状态为
  `actionable` 才计为“买点曾触发”。
- 新的只读研究把目标固定为“后续真实触板且最终形成正式 `buy_now`”。最佳
  `质量+动能+逐笔资金` 在冻结 validation 的 PR-AUC 为 `0.4467`，但 80% 档真实联合
  精确率和 D+1 胜率都只有 `47.54%`，因此结论为 `REJECT/INSUFFICIENT`。该研究没有
  产品导入、数据库写入、API、任务或页面入口。
- 按当前 v2 正式账本重标后，`质量+动能+逐笔资金` 的 `>90%` 档为 16 只、真实触板
  7 只、正式买点 4 只；100% 档也只有 3/9 触板。触板非正式的 3 只都被当前质量门明确
  拒绝，完整正式门通过后漏单为 0；但板前同股联合率与正式门不一致，旧概率不得恢复。

### Dynamic leader research

- 3-7 月研究已经归档。固定从 `memory/06_backtests/README.md` 恢复结论，不再从聊天记录
  或旧候选 JSON 恢复状态。
- 100 个交易日共切出 22 个市场周期和 1,668 个动态概念周期；个股连板、市场空间龙、
  概念资金龙和波段趋势/容量龙使用不同点时时钟，不设半导体、医药、电力等静态白名单。
- 龙头映射包含 449 个确认事件和 986 条唯一龙二龙三边。映射后 1 日上涨率为
  `52.8147%`，非分歧 `55.0318%`、分歧 `43.7500%`；龙头/龙二龙三身份单独不是稳定
  `>=60%` 硬门，分歧只保留为风险解释。
- 静态概念成交额前 20% 的独立历史为 `16/29=55.1724%`，状态固定为
  `historical_proxy_rejected`。动态低位跟随和早期扩散交叉样本小且没有新的独立历史，
  只保留研究证据，不绕过 A/B/C 的冻结交叉准入、排序或下单链。
- 新的资金与概念扩散补位影子不再使用 `warming -> launch` 或固定龙二/龙三。它在候选
  触板时要求当天此前尚无 A/B，并按全部严格 D-1 概念成员动态选择细分概念；有效梯队为
  已有 2-4 只先行封板且最高至少 2 板，再与市场阶段、个股回撤或 D-1 行业成交额扩张
  交叉。每天只取第一笔补位，后续容量留给可能出现的 A。该规则已成为正式 C，但历史
  证据仍标记为代理；从 `2026-07-27` 起自然前向收集，不回放此前合同雷达帧作为前向成绩。
- 可重启动态波段已经识别金安国纪、亨通光电、东山精密、德明利和深科技的趋势/容量
  领导力；多概念重复归属和 3-6 月成员幸存者偏差仍未解决，月度占席榜不能作为唯一
  情绪龙结论。
- 财报旧高胜率来自按当前成交额/市值优先同步形成的资金关注粘性白名单，不是错误财务
  字段本身。正确同比仍有正边际，不恢复“本地财报缺失即拒绝”。
- 正式交易固定为 A+B+C v2：`96/140=68.5714%`。C 只能覆盖核心门的三个明确排除原因，
  并必须通过冻结交叉条件和每天第一笔容量约束；不能把“有龙头”或“属于热门概念”
  直接当作放行理由。
- 历史退出固定为涨停价入场、D+1 官方收盘和正式费用。自然前向状态仍为
  `historical_pass_forward_not_passed`，现有历史不能再次承担晋级验证。

### How to verify

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py
uv run --group server pytest -q \
  tests/alphaagent/test_akshare_adapter.py \
  tests/alphaagent/test_data_sync_parallel.py \
  tests/alphaagent/test_data_sync_schedule.py
uv run python -m compileall -q alphaagent/server/services/limit_up
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
```

### Evidence

- 正式入场价格：`memory/06_backtests/limit_up_formal_entry_price_audit_20260725.md`。
- 3-7 月日级龙头周期：`memory/06_backtests/limit_up_leader_cycle_2026_03_07.md`。
- 七月严格分钟传播：`memory/06_backtests/limit_up_leader_propagation_intraday_202607.md`。
- 日级资金主线周期：`memory/06_backtests/limit_up_capital_mainline_cycle_2026_03_07.md`。
- 日级资金消融：`memory/06_backtests/limit_up_capital_mainline_fund_ablation.md`。
- 正式候选反事实：`memory/06_backtests/limit_up_capital_mainline_candidate_counterfactual.md`。
- 龙头映射与因子发现：
  `memory/06_backtests/limit_up_leader_follower_factor_formal_discovery_2026_03_07.md`。
- 龙头映射冻结因子历史验证：
  `memory/06_backtests/limit_up_leader_follower_factor_806d_validation.md`。
- 可重启动态波段龙头与正式候选交叉：
  `memory/06_backtests/limit_up_dynamic_wave_leader_discovery_2026_03_07.md`。
- 财报覆盖质量重建、风险指标和 41 笔逐票账本：
  `memory/06_backtests/limit_up_quality_reconstruction_20260726.md`。
- A+B 正式方案：`memory/06_backtests/limit_up_final_trading_scheme_20260726.md`。
- A+B 重建、交割和近期快照复核：
  `memory/06_backtests/limit_up_core_ab_formal_validation_20260726.md`。
- 空仓日逆向特征、因果修正与严格复利：
  `memory/06_backtests/limit_up_no_trade_day_reverse_factor_20260727.md`。
- A+B+C 正式因果回放：
  `memory/06_backtests/limit_up_abc_formal_replay_20260727.md`。
- 板前联合概率最终拒绝结论：
  `memory/06_backtests/limit_up_formal_touch_readiness_20260728.md`。
- 全触板 D+1 盈利门反事实：
  `memory/06_backtests/limit_up_all_touch_d1_gate_20260729.md`。

### Open risks and next work

- 2026 年 3-6 月有完整日线但没有历史点时题材成员和盘中板块资金，只能做日级轮换。
  数据库当前有 10 个严格概念快照日，但冻结切分仍是 fit/calibration/validation
  `0/0/2` 日；唯一自然 v2 雷达日是 7 月 28 日，尚无足够闭合标签。
- 3-7 月已经被查看，只能作为龙头映射因子发现/反例样本，不能承担最终晋级结论。
- `limit-up-core-abc-v2` 的自然前向账本必须从新合同实际保存快照起算；最近
  合同之前的保存帧不是自然前向样本。累计至少 60 个新交易日、30 笔闭合全量买点和
  两个情绪阶段后，再按胜率 `>=60%`、均值为正、回撤和硬亏判定。
- C 单独要求至少 15 笔、至少新增 10 个交易日，新增与合并胜率均
  `>=60%`，且合并复利提高、最大回撤不恶化。历史 3-7 月新增组仅 55%，必须重点检查
  自然前向是否恢复。证据见
  `memory/06_backtests/limit_up_concept_diffusion_shadow_20260726.md`。

## Low-suction Current State

### Current contract

- 低吸与打板使用独立候选、版本、账本和绩效；低吸只做前向纸面研究，不连接券商自动
  下单，也不继承打板规则或历史结果。
- 页面固定为 `实时推荐 / 回测分析 / 规则说明`。实时采用盘中预警和 14:50 最终确认两阶段；
  只有最终确认可以进入 14:55 纸面买入。
- 组合为两个等额仓位、同一概念最多一仓。全部推荐质量和两仓现金账户分别展示。
- 严格历史概念成员仍不足；89 笔历史结果标记为
  `exploratory_survivorship_proxy`，不能解锁正式收益声明。
- 收盘确认与同收盘成交不可保证。D+1 开盘压力测试将胜率从 76.40% 降到 53.93%、
  单笔均值从 +3.08% 降到 +0.51%，说明旧 +230% 复利只是研究代理上界。
- D+2 快速涨停延长持有只作小样本前向影子；回踩日直接入场和弱转强前置预判两条变体
  已否决，不再继续调参。

### Evidence and verification

- 研究边界：`requirements/alphaagent_low_suction_research_reset_design.md`。
- 产品设计：`requirements/alphaagent_low_suction_ops_console_redesign.md`。
- 详细证据：`memory/06_backtests/README.md` 下的 `low_suction_*.md`。

```bash
uv run --group server pytest -q tests/alphaagent/services/low_suction
npm --prefix frontend test -- --run
npm --prefix frontend run build
```

### Open risks and next work

- 历史成员和证券状态不完整，历史代理不能替代自然前向。
- 在前向 300 笔纸面账本达标前，不提高交易频率、不放宽入场阈值；扩容顺序固定为前向
  达标、同信号增加仓位、最后扩股票池。

## Shared Data Decisions

- `stock_daily_bars` 当前是不复权口径；涉及跨除权价格比较必须显式处理，不能默认前复权。
- 日终数据可用于 D+1 状态、标签和归因，不能回填盘中买点。
- 点时数据统一要求 `known_at <= decision_at`；覆盖不足时失败关闭或标记诊断，不填零、
  不使用当前成员关系冒充历史成员。
- 原始大 JSON、缓存和截图不作为长期记忆。可复现结论保留 Markdown，运行时固定读取且带
  SHA 的小型冻结 JSON 可以保留；其他中间结果按需从数据库重建。
