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

- 唯一当前执行合同为 `limit-up-core-abc-v2`；历史正式过滤、实时触板、板前概率准备、
  雷达持久化和现金账本使用同一公共质量合同。`limit-up-core-abc-v1` 只标识冻结历史候选
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
  胜率目标仍是 `>=60%`。未真实触板为 `qualified_waiting_trigger`；真实触板/回封后不依赖
  概率模型，重新通过完整公共质量门才形成当前正式扫板买点。板前模型当前只作研究排序，
  不生成正式买点；未来若独立晋级也必须单独记账，两类成绩不得混报。
- 正式策略保留首板、二进三、正式费用和 D+1 官方日线收盘退出。一仓/两仓现金账户是
  独立的回测容量模拟，不能截断正式推荐或充当全量质量分母。
  竞价止盈、盘中最优退出和结果后选择卖点不属于正式合同。
- `actionable_recommendations` 是不受两仓容量限制的正式触发列表；`portfolio` 才对应
  两仓现金账户。全量规则质量和两仓到达顺序结果必须分别报告。
- 合格的 `near_limit/sealed/resealed` 可以形成正式涨停价排队买点；封板/回封不保证
  成交。板前研究触板后退出自己的观察表，不能清除正式扫板买点。

### Formal historical and forward status

- 806 个交易日是行情背景；真实事件覆盖 `2025-06-27..2026-07-24`，正式闭合
  推荐覆盖 `2025-07-10..2026-07-23`，不是因为日线只有这一年。
- v2 全历史按因果顺序重放：140 笔闭合独立交割，`97/140=69.2857%`，平均净收益
  `+2.1478%`，独立信号复利 `+742.9976%`，最大回撤 `-21.0357%`，硬亏
  `10/140=7.1429%`。A 为 `35/41=85.3659%`，C 为 `44/69=63.7681%`，B 为
  `18/30=60%`；另有 1 条 7 月 24 日信号尚无 D+1 收盘。
- 单仓实际成交 79 笔、胜率 69.6203%、复利 `+376.6561%`、回撤 `-19.2649%`，没有
  达到单仓 `+400%`；两仓成交 95 笔、胜率 73.6842%、复利 `+201.9840%`、回撤
  `-8.6709%`，达到两仓目标。两仓跳过 45 条，其中 33 条因给后续 A 保留仓位。
- 最近闭合窗口 `2026-07-14..23` 全量只有 `6/13=46.1538%`，两仓 `2/4=50%`、
  复利 `-1.0721%`；冻结后历史代理两仓只有 3 笔且复利 `-2.2819%`。当前不能以全历史
  达标替代近期退化事实。
- 当前状态固定为 `historical_proxy_pass_forward_unconfirmed`；历史 69.2857% 不是实盘
  胜率承诺。自然前向从 v2 服务重建后的下一有效交易日起累计；7 月 21-24 日旧 v15 帧和
  7 月 27 日周一交易日的旧 A+B/A+B+C 帧都不是新代码自然生成，不进入前向分母。
- 核心门前 560 笔闭合事件有 179 个候选日，A+B 只保留 78 笔/50 日；排除组
  `235/482=48.7552%`、复利 `-32.0997%`，因此不能整体撤门。129 个无 A+B 买点日的
  全天空仓条件带有未来信息，只用于逆向特征发现。改成触板时可知的“此前尚无 A+B”，
  并交叉 D-1 行业量能、个股回撤和触板前动态概念梯队后，形成当前 C。原逆向研究的
  `46/71=64.7887%` 是晋级前定义；接入正式时间门和同秒因果顺序后，冻结闭合结果为
  `46/72=63.8889%`；加入 v2 公共估计门后 C 实际闭合为 `44/69=63.7681%`。历史概念
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

### Pre-board contract

- 当前合同为 `limit-up-preboard-decision-v2`。集合顺序为
  `raw_capture_pool -> model_training_pool / quality_pool -> action_pool -> filled_pool`。
  捕获门通过但公共质量失败的股票只可教模型识别触板形态；只有公共质量准备通过且涨幅
  达到 3% 的股票才能评分和展示，普通全市场 3% 股票不是买点。
- 同源质量门在板前只读取同帧已物化的 A/B 或 C 质量准备结论；正式触板时钟尚未发生不构成
  板前拒绝。触板后的正式扫板仍必须通过完整 `core_quality_gate_passed` 和 10:00/10:30
  入场时钟，两条链路不能共用一个含未来触板事件的布尔门。
- prior-only 的 D+1 预期收益、D+1 胜率、触板后封板率和封板后 D+1 质量继续负责交易
  质量；动态模型只补充三分钟触板概率和当日最终触板概率。
- v2 使用 144 个声明特征，加入 D-1 市场阶段、炸板率、最高板、首板数、1进2/2进3、
  行业量能/热度/封板、个股辨识度，以及同一时点同行业 3%/5%/7%/9% 扩散和梯队排名。
  validation 的最终触板 PR-AUC 为 `0.3777`、Top20% lift 为 `3.0769`，但 calibration
  没有至少 10 笔且胜率 `>=60%`、平均 D+1 为正的板前买入规则，状态继续为
  `research_only / not_eligible`。
- 实时只公开双概率真实有效的板前候选；输入不合格或模型不可用只保留内部审计。当前
  v2 模型仍是 `research_only`，所以它不会写正式动作。以后只有
  全量推荐胜率 `>=60%`、平均 D+1 为正且账户验证可接受的模型才能进入正式路径。
- 正式触板链的隔离已锁定：概率不可用但真实触板且公共质量通过必须进入正式买点；概率
  99% 但公共质量失败必须拒绝。当前重跑仍为 141 条正式信号、两仓 95 笔，胜率
  73.6842%、复利 `+201.9840%`。
- 板前 v2 校准概率上限为 `79.2453%`，不存在 `>80%` 样本。接近上限的 validation
  仅 2 笔且触板率、D+1 胜率均为 50%；最近旧帧当前代码重放的最高最终触板概率也只有
  76.6584%。在 calibration 未达到至少 10 笔、胜率 60% 和平均 D+1 为正前，不生成
  板前正式买点，也不通过重新缩放制造 80% 概率。
- 当日轨迹只读取当前 `limit-up-core-abc-v2` 帧；只有 `action=buy_now` 且公共状态为
  `actionable` 才计为“买点曾触发”。
  `research_action=buy_now` 但正式 `action=pass` 的信号只计为质量拒绝，旧合同帧仅保留数据库审计。
- 当前 D+1 优先和纯触板概率排序在已查看 validation 上结果相同；主要瓶颈是早期误报
  占仓和行动门，不是简单交换两个排序键。

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
- 正式交易固定为 A+B+C v2：`97/140=69.2857%`。C 只能覆盖核心门的三个明确排除原因，
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
- v2 公共质量计算、阈值敏感性、最近窗口和实时帧审计：
  `memory/06_backtests/limit_up_unified_public_quality_20260727.md`。

### Open risks and next work

- 2026 年 3-6 月有完整日线但没有历史点时题材成员和盘中板块资金，只能做日级轮换；
  7 月 15-24 日也没有事件同时满足成员、分钟路径和匹配市场对照门。
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
