# AlphaAgent Decisions

## Current Product

- 产品名使用 AlphaAgent；Python 包名 `vnpy` 暂不改名，保持插件兼容。
- 不修改 `vnpy/` 或官方 examples，除非用户明确要求。
- 本地开发使用 `docker compose up --build`；部署和发布复杂度留在 Docker/Compose/CI。
- A 股实时行情和实盘交易能力必须以真实安装配置的 Gateway/Datafeed 为准，不能用核心框架能力代替插件事实。

## Research Surfaces

- 当前导航保留今日市场、大盘择时、概念主线、短线研究、全 A 股票和数据管理。
- `/short-term` 是短线研究入口；当前内容是独立打板研究。
- 打板与未来低吸使用 Tab 区分，但候选、策略版本、成交账本和绩效必须完全隔离。
- 旧 `/quant`、通用回测、`/portfolio`、模拟账户和 23 张派生表全部删除。
- 原始行情、概念、金银手指、大盘择时、主线和打板证据保留。

## Low-suction Current Boundary

- 低吸与打板继续使用独立候选、版本、账本和绩效；低吸不得继承打板规则或历史结果。
- 当前低吸仅有前向纸面研究，不连接券商自动下单。历史代理、自然前向与真实可成交
  证据必须分开。
- 严格历史概念成员覆盖仍不足；旧历史研究已被反复查看，不能再称未读留出或用于继续
  调参。
- 当前产品、账户和页面决定保留在本文后部；详细研究数字由 `memory/06_backtests/`
  独立证据文件承载，不在决策总览重复。
- 研究边界以 `requirements/alphaagent_low_suction_research_reset_design.md` 为准。

## Preserved Limit-up Baseline

### Current state

- 唯一正式版本为 `limit-up-history-v15`、`limit-up-live-v15`、
  `limit-up-scheduled-v9`、`limit-up-cash-v5`。它们属于历史、实时、调度和现金账户
  四个不同合同层，不合并成一个版本号。
- 正式策略继续执行首板和二进三，每日最多两个仓位，使用正式费用，D+1 只按官方日线
  收盘价退出。竞价止盈、盘中最优退出和结果后选卖点均不属于正式合同。
- 802 日正式组合基线为 170 个信号、99 笔两仓成交，胜率 `69.6970%`、复利
  `+171.7614%`、最大回撤 `-8.3083%`、利润因子 `2.8454`。该账户是触板执行基线，
  不能直接解释为板前可成交胜率。
- 历史首板使用当天真实触板事件形成候选，只保留为 A 基线和标签来源。唯一板前 C
  回放必须在每个 `decision_at` 使用当时可见行情重新运行正式同源质量门，不能先知道
  当天后来触板的股票身份。
- 页面只提供一套当前策略，不提供旧研究版本选择。正式前向账本只读取保存帧中的
  `actionable_recommendations`；板前研究观察和诊断消融均不
  产生正式订单。

### Live invariants

- 正式 v15 首板链继续允许合格的 `near_limit/sealed/resealed` 形成
  `buy_now`；`sealed/resealed` 只表示可尝试涨停价排队，不保证成交。
- 新板前 `preboard_candidates` 才必须严格低于涨停价；触板后只从板前
  观察列表退出，不得改写或过滤正式 `actionable_recommendations/portfolio`。
- 交易时段后台快扫和 `/short-term` 实时快照均为 10 秒；较大的两日轨迹保持 60 秒。
  页面轮询只影响可见性，不改变后端采集、候选或账户。
- 正式 v15 自己的市场、板块和执行门保持不变。对新板前 C 而言，历史无法按
  `known_at <= decision_at` 还原的行业/概念、个股资金、当前换手、市场和新鲜度字段只能
  是 `diagnostic/non-blocking`，不能填零、使用日终值或成为实时独有硬门；共享风险、
  窗口、完整分钟和严格板前价格继续 fail closed。
- 二进三规则、订单、费用和正式历史账户不得因板前研究发生变化。

### Evidence

- 当前板前合同：`requirements/alphaagent_limit_up_preboard_decision.md`。
- 最新冻结报告：
  `memory/06_backtests/limit_up_preboard_decision_validation_20260723.md`。原始 JSON 按需重建，
  不作为仓库证据保留。
- 最近交易日根因：
  `memory/06_backtests/limit_up_live_vs_backtest_entry_audit_20260723.md`。

## Autonomous Data Bootstrap

- 新部署和空库必须通过系统配置的数据供应商、覆盖审计和调度任务自主同步；禁止把
  复制现有数据库作为初始化流程。
- 不向普通用户提供 CSV、服务器文件路径、缺口清单或模板导入入口。供应商不可用、
  数据为空或覆盖不足时必须明确失败、保留原数据并保持质量门禁关闭。
- 自动计划和数据管理页“立即执行”调用同一服务端调度链路；手动触发只改变执行时机，
  不改变数据来源或完整度规则。
- 2026-07-16 正式环境已用同一 `eod_finalize_2130` 链路完成 8/8 任务、700 日可靠账本
  和 253 日涨停事件覆盖；全过程未复制数据库或使用 CSV。验证证据见
  `memory/06_backtests/limit_up_production_local_parity_20260715.md`。

## Pre-board decision contract and frozen outcome (2026-07-23)

### Frozen requirement

- 股票必须先进入正式回测/实时同源的
  `eligible_first_board_pool`：主板交易资格、非 ST/退市、新股/风险、正式 lane 质量门、
  prior-only D+1 盈利门和既有历史基因均使用当时已知数据。
- 只有该高质量母池中 `change_pct >= 3` 且严格未触板的股票进入
  `quality_pool`。因此 `>=3%` 只启动观察，不是全市场母池、训练负样本、固定买点或
  3%/5%/8%/9% 分档买入规则。
- 已有 `average_return_pct`、`smoothed_win_rate`、`seal_success_rate` 和
  `d1_money_effect_win_rate` 继续分别提供 D+1 预期净收益、D+1 胜率、触板后封板率和
  封板后 D+1 盈利率。动态层只补充未来三分钟正式触板概率和当日最终正式触板概率。
- 排序优先级固定为 D+1 预期净收益、D+1 胜率、三分钟触板概率、最终触板概率、触板后
  封板率、lane 支撑分、时间和代码。误报真实占仓，后来强票不得事后替换。
- `observe` 和 `prepare` 不占仓；只有严格板前、全部环境门通过且抢到两个首板仓位的
  `actionable` 才能成为候选动作。没有 L2 时不声称涨停排队一定成交。

### Frozen evidence and decision

- 89 日数据按 44 fit、15 calibration、30 validation 冻结；候选索引分层为
  `16,132 -> 15,970 -> 1,500 -> 1,044`，最终冻结路径包含 135 个后来触板和 909 个
  未触板股票日。1,044 个冻结成员全部可重建；当前静态门重算为 1,042 个，2 个漂移
  股票日只作审计，逐时点质量门仍重新执行。翻转触板、封板、D+1 和正式入选标签不改变
  membership。
- 数据指纹为
  `sha256:b61228ea9da6ee82bf18ccfa9568fa715663f0375b34fb08bf35a354c6b2fc24`，
  候选索引指纹为
  `sha256:73bce5b983cb694c56786a7f138aa758bde27a61967b64aa0e8012975cd5863e`，
  本轮未发布研究模型指纹为
  `sha256:5246336ab1ae7455cd97c26c88382c24dc2e3ca155c51ba96ce3ef7d18a2ae11`；运行库活动
  模型仍是
  `sha256:b1d4ca83ca4dad25e1e74cda21c5b01c4f40d6e62ed9da62582d6eb8c651b71a`。
- 双概率资格已经通过。三分钟/最终触板头在 validation 的 Brier skill 为
  `+0.1360/+0.2253`，PR-AUC 为 `0.3451/0.4265`，机会 Top20% lift 为
  `4.48/3.30`；模型能在触板前产生有信息量的概率排序。
- 最终状态仍为 `historical_rejected`，因为严格 C 首板 27 笔只有 `51.85%` 胜率、
  `+6.10%` 复利、`-14.58%` 回撤，低于 A 首板的 22 笔、`63.64%`、`+23.38%`、
  `-4.66%`。41 个 C 动作最终触板率 `48.78%`，误报率 `51.22%`；概率排序有效不等于
  D+1 账户可继承 A 的约 70% 胜率。
- 预注册三排序比较没有找到改进：当前 D+1 优先与纯触板概率的 Top1/Top2、提前时间、
  动作、触板/误报、D+1 账户和误报占仓错过数全部相同；综合机会价值因 fit 触板未封
  只有 4 笔，低于预注册最少 5 笔，固定为 `insufficient_fit_scenarios`。validation 已被
  查看，全部结果只能是 `adversarial_reuse/research_only`，不得发布或晋级。
- 当前实时板前链加载该唯一模型并只公开一个 `preboard_candidates`，状态为
  `ready / historical_rejected / research_only / not_eligible`。它展示概率和 D+1 排序，
  但 `action_saved=0`、不占两仓、不替换正式首板。
- 保留 v15 既有产品语义：`actionable_recommendations` 是不受两仓容量约束的旧触发列表，
  `portfolio` 才对应两仓现金回测。板前模型未晋级时不得借“同源”名义收紧、替换或混写
  这两个正式列表；新的高质量 `quality_pool` 当前只形成研究概率观察。
- 正式开关具有双重条件：数据库模型状态必须为 `forward_pass_for_formal`，并且
  `ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT` 必须精确匹配该模型指纹。晋级只原子
  替换首板动作和两仓，二进三原样保留。

### Recent live root cause

- 最近三日先按回测触板正标签反查板前全过程：14 只正式正标签全部存在板前帧，13 只通过
  当前静态质量门并可评分；5 只进入 D+1 优先的产品 Top2，11 只进入纯触板概率 Top2。
  唯一静态淘汰为 `605111.SSE 新洁能`，原因 `same_stock_joint_rate_below_30`。
- 全部保存帧漏斗为
  `2442 曾>=3% -> 911 prior-only 盈利基因 -> 537 静态质量上界 -> 488 有帧 -> 350 可评分`。
  因此不是全市场 3% 股票直接算买点，主要损失依次来自历史基因/质量、分钟可评分性和
  D+1 优先的两仓产品排序。
- 旧正式两仓 13 个股票日有 9 个首次入选时已经触板；旧 `buy_now` 仅 3 只在板前出现。
  这证明旧“只有封板才显示”主要是触发和组合选择时钟，不是所有 8%-9% 股票都没有板前
  动能。后台和页面轮询差异会进一步吞掉很短的可见窗口。
- 连亏不是单一“市场切风格”假设即可解释：A 最大 3 连亏的三笔都归为 `ranking_error`，
  同段有 29 只未入选正收益候选；C 的五段 2 连亏主要是 `false_positive_occupancy`，也有
  一段 `ranking_error`。现有证据先指向两仓排序与误报占仓，市场/金银/板块只能作为待验证
  归因，不能用日终行情事后解释。
- 2026-07-23 回归曾把“触板后退出板前候选”误接到正式 `_now_signal()`、
  `_build_live_buy_list()` 和前端 `livePortfolio.ts`，导致合格的 `sealed/resealed` 扫板
  买点先被后端清除、恢复后又被页面隐藏；同时内部 `HistoricalPrior` 对象泄漏到 JSONB
  快照，使刷新回退 09:17 旧数据。三处均已修复。
- 修复后正式封板/回封 `buy_now` 继续显示；新板前概率表也已在桌面和移动端验证渲染。
  两者互不覆盖，板前当前仍是 `research_only`，没有借 UI 修复升级成正式策略。
- 2026-07-24 源码收口验收为打板后端 `808 passed`、data-sync `155 passed`、前端
  `140 passed`；compileall、前端生产构建、开发/部署 Compose 配置和差异检查均通过。
  独立板前 worker 已从代码、Compose 和运行容器删除；数据库只保留当前
  `active / ready / historical_rejected` 模型。镜像与页面运行态留待下次重建部署复验。

### Future research boundary

- 当前代码、历史回放、最近交易日逐票解释和实时观察面已经完成，不以“等待交易日”为
  工程收口理由。旧板前链和版本选择已删除，不再创建或恢复兼容分支。
- 三排序比较已经完成；仅替换当前 D+1/触板排序键没有改善。下一项有价值的研究转为行动门
  和误报占仓机制，必须使用新的独立时间段预注册验证；不得继续在同一 validation 调阈值、
  等待时长或失败分支样本门槛。
- 板块起身、龙头连板、同板块首板扩散、个股/行业资金、金银手指和新鲜度必须先积累
  `known_at` 同源覆盖，再逐因子做加入/移除消融。没有同源历史前只显示诊断，禁止用收盘
  板块热度解释或筛选盘中买点。
- 只有新的预注册历史/独立前向账户通过同一门，才允许将首板触发和两仓排序作为一个整体
  替换；已有正式扫板买点不因板前研究失效。
- 正式首板、二进三、两仓、费用和 D+1 官方收盘退出在此之前保持不变。

## Low-suction Current Decisions

- 历史回放与自然前向资格严格分开，禁止互相回填；历史代理不得解锁纸面或正式资格。
- 低吸页面、候选、持仓、交割单和绩效与打板隔离；当前只作纸面研究，不自动下单。
- 信号日收盘确认与同收盘成交不是已证明的可执行价格，账户结论必须单列成交假设和容量。
- 当前具体产品决定以 `requirements/alphaagent_low_suction_research_reset_design.md` 为准；
  详细证据留在 `memory/06_backtests/`，不在本总览累计实验流水。
