# AlphaAgent 涨停龙头周期因子与正式推荐升级 Implementation Plan

> **Archived (2026-07-26):** 本计划已归档，不再是可执行的当前方案。Tasks 0-6 的有效
> 连板、市场情绪和覆盖审计仅作基础研究证据；正文中的 `v15/v9/v5`、回退开关、
> `limit-up-leader-cycle-v1` 目标和 Tasks 7 以后的步骤均为当时设想，不得按当前合同执行。
> 唯一正式合同已固定为 `limit-up-core-ab-v1`，无旧规则回退；当前方案、历史结果
> 和前向未通过状态见 `memory/06_backtests/limit_up_final_trading_scheme_20260726.md` 与
> `memory/06_backtests/limit_up_core_ab_formal_validation_20260726.md`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. This repository forbids commits unless the user explicitly requests one, so each task ends with a verification checkpoint instead of a commit step.

**Goal:** 构建并正式上线一套无未来函数、历史回放与实时推荐完全同源的龙头周期质量算法，在现有首板/二进三质量池内完成进一步过滤和排序，使全量推荐的 D+1 胜率、平均净收益、同窗复利、回撤和连亏恢复或超过旧高质量水平，并让用户在板前观察和触板扫板时优先看到真正的题材龙、容量核心和有效跟随者。

**Architecture:** 实施分为“全市场点时角色发现 -> 正式质量池消融与前向验证 -> 历史/实时同源正式晋级”三层。全市场层识别市场情绪、个股启动、题材传播和角色切换；交易层仍只处理现有首板/二进三正式质量池，保留 D+1 预期收益、胜率、触板率和封板率，不允许龙头因子绕过原质量门；晋级层冻结唯一的质量结论和排序函数，同时接入历史回放、板前概率列表、触板正式推荐及页面解释。历史先完成 2026 年 3-7 月日级周期账本，再只在点时成员、分钟行情和雷达覆盖完整的日期研究 1/3/5/10 分钟传播；覆盖不足时不能伪造盘中因果，也不能把计划标记为最终完成。

**Tech Stack:** Python 3.11、pandas、SQLAlchemy/PostgreSQL、scikit-learn、pytest、现有 AlphaAgent 打板回放与实时影子链。

---

## 为什么执行这个计划

### 问题不是“财报修好后策略自然变差”

本计划承接的是一次已经定位的数据偏差，不是从零发明一套龙头题材策略。旧打板账本曾经
显示很高的胜率和复利，但其中混合了两种不同口径和一个不可保留的数据 Bug：

| 历史口径 | 闭合交易 | 胜率 | 平均 D+1 净收益 | 复利 | 最大回撤 |
|---|---:|---:|---:|---:|---:|
| 原错误财报基线，全量独立槽位 | 194 | 61.86% | +1.33% | +425.74% | -13.77% |
| 旧 800 日同批全量推荐 | 164 | 62.1951% | - | - | - |
| 旧 800 日两仓成交子集 | 97 | 70.1031% | - | - | - |
| 当前正确财报，806 日全量推荐 | 239 | 54.8117% | +0.5687% | +101.5433% | -30.6303% |
| 当前正确财报，806 日两仓账户 | 127 | 58.2677% | +0.8045% | +54.7953% | -20.6187% |

前两组旧数字不是同一次回放：194 笔是旧错误财报仍生效时滚动重算到 2026-07-22 的
198 信号/194 闭合全量账本；164 笔和 97 笔是此前截止 2026-07-16 的冻结 800 日账本，
也是项目口头所称“约 70%”的来源。日期和信号数不同，所以它们只能说明旧状态，不能直接
互比复利。Task 10 必须在同一日期、同一候选版本和同一费用下重建旧错误/当前正确反事实，
再判断新因子是否真正恢复收益。

旧“约 70%”是两仓按到达顺序实际成交的 `68/97`，同批全部推荐只有
`102/164=62.1951%`。两仓因 T+1 占仓跳过了大量后排票，不能拿这个子集胜率代表实时
全量推荐质量。后续所有研究必须同时报告全量推荐和两仓账户，且以全量推荐作为质量主尺。

指标下降发生在修复以下三个财报数据问题之后：

1. 旧同步每天按**当前**成交额和市值倒序只取 100 只股票，绝大多数主板股票没有本地财报。
2. 股票已有 4 期报告后便停止更新，后续季度无法进入点时质量门。
3. 季度环比字段曾误当归母净利润同比，净利润口径也未严格使用归母口径。

其中真正造成大幅下降的不是“正确归母同比无效”，而是补齐全市场财报后，原来被
“本地无财报”偶然挡住的弱票进入了正式池。旧财报覆盖组实际偏向当前高成交额、大市值、
资金承载较强的股票，并带有用 2026 年当前快照回看历史的幸存者偏差。正确归母同比仍有
正边际：同比 `>=10%` 的 556 笔胜率 `50.90%`、均值 `+0.2576%`，同比不足的 675 笔
只有 `42.96% / -0.4821%`。因此不能恢复财报缺失 Bug，也不能删除正确财报门来追求旧曲线。

### 为什么不是加一个固定成交额门

已经用 D-1 可见成交额、20 日成交额中位数和横截面分位做过消融。开发段的高流动性门
可以碰到约 70%，但锁定留出立即回落到约 48%-50%；宽松的 D-1 成交额 `>=2 亿` 只把
当前全量胜率从 `54.8117%` 提高到 `55.4502%`，锁定留出基本不变。固定流动性只重建了
旧隐式筛选的一小部分，无法处理资金在题材、容量、连板高度和市场阶段之间的动态切换。

这也是研究转向龙头周期的原因：旧错误覆盖歪打正着捕获的是“资金承载 + 行业前排 +
财务质量 + 当期风格”的混合子集。现在需要用 D 日决策时已知的数据，把这些经济含义显式
拆成市场情绪、题材传播、个股角色、容量承载和切换风险，而不是继续依赖缺失值或一个固定
阈值。七月的恒尚节能、哈药股份和立新能源分别证明：空间高度、板块资金主线和题材扩散
会错位，单看最高板或板块净流入第一都不够。

### 当前正式回测到底按什么价格买

2026-07-25 已从源码、806 日 PostgreSQL 账本和页面实际调用链交叉核实：当前
`/short-term` 回测固定请求 `lane=portfolio`，使用
`limit-up-history-v15 / limit-up-scheduled-v9 / limit-up-cash-v5`，不是板前 3%-9% 回测。

- 806 日首板候选池有 572 个质量合格候选，572 个的 `entry_price` 全部等于涨停价。
- 其中 545 个落在正式 `10:00-11:30 / 13:00-14:30` 买入窗口，仍全部按涨停价入场；
  498 个在首次触板时触发，47 个因 10 点前已触板而在窗口内首次回封时触发。
- 当前正式盈利门过滤后有 243 个推荐、239 个闭合结果；两仓实际成交 127 笔，127 笔
  订单的原始入场价和现金账本成交价全部相同，均为涨停价。
- 因此当前正式回测**确实是首次触板或窗口内回封时，以涨停价作为排队成交代理**。
  它不是提前预测买入，也不是 3% 观察价成交。没有 Tick/L2 排队证据，所以仍必须标记
  `candidate_proxy_only / live_equivalent=false`，不能把推荐质量等同于真实成交率。

详细证据见
`memory/06_backtests/limit_up_formal_entry_price_audit_20260725.md`。如果后续代码出现
首板入场价不等于涨停价、首次触板/回封时间不等于买入时间，必须先停止收益研究并修复
口径，不能用新的龙头因子掩盖执行错误。

### 最终目标

本计划的最终交付不是研究报告、龙头名单或一个只展示不执行的影子分数，而是一个正式的
`limit-up-leader-cycle-v1` 质量策略版本。在不恢复数据 Bug、不使用未来数据、保持正式
触板价入场和 D+1 官方收盘退出的前提下，它必须用同一套点时特征、质量结论和排序函数
同时驱动历史回放与实时推荐：

1. 全市场层在每个决策时点识别市场情绪、题材主线、点火龙、空间龙、容量中军、龙二龙三、
   补涨和切换风险，但不能直接把全市场股票变成买点。
2. 交易层只在现有正式首板/二进三质量池内进一步判断“保留、降级观察或拒绝”，并输出
   唯一的 `leader_cycle_priority`。正式全量推荐质量按保留后的全部候选计算，不能只报
   Top2 或两仓成交子集。
3. 实时板前列表使用该优先级提前排列已经通过同源质量门且概率可用的候选；触板后的
   `actionable_recommendations` 使用同一优先级过滤和排序。`>=3%` 仍只是观察激活条件，
   龙头因子不能把普通涨幅股或板前观察直接升级为正式买点。
4. 历史回放在每个信号时点只读取当时可见数据，生成与实时逐字段一致的质量结论、优先级
   和理由；同一冻结输入在历史与实时两条路径上的保留状态和相对顺序必须一致。
5. 页面最终展示“当前题材阶段、个股角色、传播/切换概率、D+1 质量、正式优先级和保留/
   拒绝原因”，使用户知道为什么优先打某只，而不是只看到一个无法解释的总分。

最终业务结果是：用户面对同一时刻多只快速拉升股票时，先看到正式质量池中 D+1 预期更高、
龙头角色更可靠、板块传播更真实且切换风险更低的候选；股票触板后仍保留正式扫板入口。
本计划不承诺没有 L2 的排队成交率，也不把自动下单纳入交付范围。

### 量化完成门

以下五层必须全部通过，才能把本计划标记为完成并启用正式版本：

1. 先解释当前 `54.8117% / +0.5687% / +101.5433%` 与旧结果之间的逐因子差额，不能把
   未解释的下降笼统归因于“行情切换”。
2. 同日期、同费用、同触板价入场的全量推荐必须同时达到：胜率不低于旧全量
   `62.1951%`、平均 D+1 净收益不低于 `+1.30%`、最大回撤不差于 `-13.77%`，且同窗
   逐日等权复利不低于旧错误财报反事实。`70.1031%` 只作为两仓次级对照。
3. 新规则闭合样本不得少于当前正确基线的 80%，并同时降低当前最大连亏和硬亏率；不能靠
   大量删票、缩短回撤窗口或挑选已看日期制造恢复结果。
4. expanding walk-forward、锁定留出和按市场阶段分组均不得出现“总体提升但独立后段反向”；
   3-7 月只用于定义与对抗，不能承担最终晋级结论。
5. 至少 60 个完整新前向交易日、30 个闭合正式 Top5 候选通过同一冻结门；历史与实时同源
   测试、正式版本切换、页面展示和回滚开关全部完成。任一项未通过时只能保持影子，计划
   状态必须写成“尚未达到最终目标”，不能用“研究已完成”代替产品交付。

### 最终可见产物

- 一个冻结且可追溯的 `limit-up-leader-cycle-v1` 模型/规则指纹。
- 一个被历史回放和实时推荐共同调用的质量结论与排序模块，不维护两套权重。
- `/short-term` 中按正式优先级排列的板前候选和触板买点，以及可展开的中文排序理由。
- 一份同窗恢复记分卡和一份独立前向验收报告，均同时报告全量推荐与两仓账户。
- 一个可原子回退到当前 v15/v9 正式合同的开关；回退不删除实时扫板买点。

## 研究边界和成功标准

### 正式晋级前不变的合同

以下合同在 Task 10 晋级决定通过前保持不变；通过后只允许按 Task 11 原子升级版本和质量
排序，费用、入场、退出及候选母池边界仍不得改变。

- 正式版本继续是 `limit-up-history-v15`、`limit-up-live-v15`、
  `limit-up-scheduled-v9`、`limit-up-cash-v5`。
- 正式交易只包含现有首板和二进三质量池；本研究不得把全市场涨幅股直接变成推荐。
- 正式费用、D+1 官方收盘退出、首板扫板买点、二进三动作和两仓现金账户不变。
- 全市场行情可以用于判断谁带动板块；只有正式质量池候选可以进入收益评估和未来影子排序。
- 任何 D 日收盘后才知道的触板、封板、D+1 收益和最终龙头身份只能作为标签或结算，不能进入 D 日决策特征。

### 三个必须分开的周期时钟

1. `board_spell`：个股连续市场交易日的有效封板路径。股票停牌或缺少中间市场交易日时必须重置。
2. `leadership_tenure`：个股达到市场有效最高板或题材点时第一角色的任期；并列必须保留，不能事后只挑赢家。
3. `theme_propagation_cycle`：题材从点火、确认、扩散、加速、分歧、回流/反包到退潮的传播周期。它可以晚于个股首板，也可以在旧龙仍连板时提前切换。

### 角色标签

- `theme_ignition_leader`：最早产生点火事件，并在其后观察窗内带来排除自身后的题材增量扩散。
- `space_leader`：当日市场有效最高板之一。
- `independent_demon`：至少两日处于最高板组或有效连板达到五板，但题材传播增量不成立的空间龙；恒尚节能必须允许落入此类。
- `capacity_core`：题材内点时成交承载居前、与题材扩散同向但不一定占据最高板的容量股。
- `leader_2` / `leader_3`：在同一传播周期内，晚于点火龙响应、点时相对强度和成交承载依次居前的第二、第三核心。
- `replenishment`：题材确认后才首次启动、承担低位补涨而非原始点火的股票。
- `ordinary_follower`：只在龙头启动后跟随，且没有独立点火贡献、空间高度或容量承载的股票。

角色允许多标签。例如哈药股份可以同时是 `space_leader` 和
`theme_ignition_leader`；恒尚节能可以是 `space_leader + independent_demon`；容量中军可以不是连板最高股。

### 形态标签

- `first_board_ignition`：此前有效连板高度为 0，当日首次触板或封板。
- `continuous_two_to_three`：前两个相邻市场交易日都有效封板，当日为连续第三板。
- `short_cycle_reboard_three`：当日封板、前一市场交易日未封板，并且包含当日在内最近五个市场交易日恰有三次有效封板；不得与连续二进三混算。
- `higher_board_continuation`：当日前有效连板高度至少 3，继续封板。
- `failed_reboard`：满足短周期反包观察结构但当日只触板未封或未触板。

### 研究阶段成功标准

- 2026 年 3-7 月的每个市场交易日都有可复核的情绪、高度组、主要题材、角色和周期阶段账本。
- 恒尚节能停牌前后的涨停不会连成 8 板；2026-07-01..09 为有效 7 板。
- 七月报告至少复现：哈药股份先连板后医药扩散、立新能源的电力点火/资金脱钩/回流、恒尚节能的独立空间龙、7 月 7-9 日 TMT 无最高板统一龙头但有容量主线。
- 分钟传播只统计覆盖完整事件，并同时报告事件数、成员覆盖率、排除数和排除原因；缺失成员不能按“未跟风”计零。
- 每个模型特征都有 `known_at`、来源和可用范围；所有训练集、校准集和评估集按交易日分离。
- 因子加入/移除消融同时报告全量推荐质量和两仓到达顺序账户，不能用两仓子集胜率代替规则质量。
- 未达到至少 60 个完整点时交易日、30 个闭合传播正例和 30 个闭合正式候选时，结果固定为 `research_only/insufficient_point_in_time_coverage`。

本节只定义 Tasks 1-9 的研究质量，不能替代前述“量化完成门”。生成这些账本和报告不表示
正式推荐已经升级，也不表示整个计划完成。

## 当前数据快照（2026-07-25）

| 数据 | 3月 | 4月 | 5月 | 6月 | 7月 | 可做什么 |
|---|---:|---:|---:|---:|---:|---|
| 全市场日线交易日 | 22 | 21 | 18 | 21 | 18 | 完整日级周期与收益结算 |
| 1分钟股票数/股票日 | 465/2461 | 534/3099 | 632/3396 | 1537/7286 | 2333/7987 | 候选偏置的分钟个股路径，不是全市场连续快照 |
| 点时题材成员 | 0 | 0 | 0 | 0 | 7/13 后行业/主题，7/20 后概念 | 只能在覆盖日做严格题材传播 |
| 盘中板块资金 | 0 | 0 | 0 | 0 | 7/13..24 共 10 日 | 只能作七月后半段点时资金证据 |
| 概念分钟强度 | 0 | 0 | 0 | 0 | 7/15..24 共 8 日 | 可验证题材自身的分钟扩散 |
| 完整雷达帧 | 0 | 0 | 0 | 0 | 7/20..24 共 5 日 | 可连接个股启动与板块后续响应 |

因此 3-6 月先做完整日级轮换描述，不能声称已复原分钟级“谁带动谁”；七月前半段也只允许日级归因。严格分钟传播的首批开发样本限定为 7 月 20-24 日，7 月 15-17 日只有在成员、概念强度和个股分钟覆盖逐事件通过后才能加入。

## Git 接手边界

开始执行本计划时，前序工程改动已经审阅、验证并提交，不应重新实现或回退：

1. `c5f3f2c3`：财报按报告期覆盖全市场、公告日点时读取、正确归母同比、写入后缓存失效；
   同时补齐既有低吸收复分钟模块在统一数据同步器中的任务注册。
2. `62771b71`：板前观察只公开通过固定正式质量门且双触板概率真实有效的候选；UTC 分钟
   转为上海交易时间；动态题材龙头只作研究影子，不改变正式扫板、排序、两仓或退出。
3. 本计划及 `memory/06_backtests/` 下的财报、旧 70%、实时发布、动态龙头、七月周期和
   正式入场审计作为同一研究证据包提交。

新窗口先运行 `git status --short`。如果为空，直接从 Task 0 开始；如果出现新改动，按实际
来源审阅并保留，不得把它们误当成本计划遗留清理。已完成且由
`memory/06_backtests/limit_up_financial_point_in_time_fix_20260724.md` 取代的旧财报执行计划
不再保留。

## 文件边界

### 新建

- `alphaagent/server/services/limit_up/leader_cycle_contract.py`：纯函数形态、角色、周期状态和点时字段合同。
- `alphaagent/server/services/limit_up/leader_cycle_repository.py`：只读加载日线、事件、成员、资金、概念分钟、雷达和正式回放结果，并生成覆盖清单。
- `alphaagent/server/services/limit_up/leader_cycle_research.py`：构造日级账本、分钟传播事件、匹配对照、消融指标和 Markdown 报告。
- `alphaagent/server/services/limit_up/leader_cycle_model.py`：在覆盖门通过后拟合/校准角色、传播和切换概率；覆盖不足时返回明确状态，不产生概率。
- `alphaagent/server/services/limit_up/leader_cycle_policy.py`：加载唯一冻结策略，输出正式保留结论、中文理由和统一优先级；历史与实时共用。
- `tests/alphaagent/test_limit_up_sentiment.py`：有效连板与情绪权重回归。
- `tests/alphaagent/test_limit_up_leader_cycle_contract.py`：形态、角色、周期和无未来字段测试。
- `tests/alphaagent/test_limit_up_leader_cycle_research.py`：覆盖、传播、对照、正式候选连接和消融测试。
- `tests/alphaagent/test_limit_up_leader_cycle_model.py`：按日期切分、概率校准、样本门和标签翻转测试。
- `tests/alphaagent/test_limit_up_leader_cycle_policy.py`：冻结策略、历史/实时同源、排序稳定性和回退测试。
- `memory/06_backtests/limit_up_leader_cycle_2026_03_07.md`：五个月日级周期、逐月轮换、角色和持续时间总报告。
- `memory/06_backtests/limit_up_leader_propagation_intraday_202607.md`：七月严格分钟传播覆盖与案例报告。
- `memory/06_backtests/limit_up_leader_cycle_promotion.md`：同窗恢复记分卡、独立前向结果和正式晋级决定。

### 修改

- `alphaagent/server/services/limit_up/sentiment.py`：按全市场交易日连续性重算连板，并移除重复计算的高度权重。
- `alphaagent/server/services/limit_up/concept_resonance.py`：复用统一题材语义分类，继续保存原始分量，不直接改变正式动作。
- `alphaagent/server/services/limit_up/sector_warmup.py`：复用现有点时成员重叠分组，不另建第二套题材家族算法。
- `alphaagent/server/services/limit_up/dynamic_leader_shadow.py`：研究通过前只补充可审计的角色/传播分量；不改 `action`、正式排序或两仓。
- `alphaagent/server/services/limit_up/history_service.py`：晋级后在正式盈利门之后应用统一龙头质量结论和优先级。
- `alphaagent/server/services/limit_up/live_service.py`：晋级后对板前列表和触板正式推荐应用同一结论与排序。
- `alphaagent/server/services/limit_up/preboard_decision_service.py`：复用正式优先级，但不把板前观察直接变成买点。
- `alphaagent/server/services/limit_up/scheduled_execution.py`：同一捕获批次内按正式优先级决定两仓到达顺序，并保持真实先后约束。
- `alphaagent/server/services/limit_up/versions.py`：正式晋级时原子切换历史/实时策略版本；现金执行版本不变。
- `tests/alphaagent/test_limit_up_dynamic_leader_shadow.py`：固定影子只加字段、不改正式动作和顺序。
- `frontend/src/api/limitUp.ts`：公开角色、题材阶段、质量结论、正式优先级和理由字段。
- `frontend/src/features/limitUp/PreboardRanking.tsx`：按正式优先级展示板前候选和龙头解释。
- `frontend/src/features/limitUp/LiveSignalCard.tsx`：展示触板正式推荐的角色、优先级和保留理由。
- `frontend/src/pages/LimitUpPage.tsx`：保持板前观察与正式扫板分区，同时使用同一优先级语义。
- `memory/06_backtests/README.md`：只增加两份最终证据入口，不登记中间 JSON。
- `memory/09_decisions/decisions.md`：研究完成后只保存当前结论、验证方式、证据和未决风险。

## Task 0: 锁定正式入场与收益基线

龙头因子研究开始前先执行本任务。目的不是再次讨论板前概率，而是确保后续所有收益变化
只来自候选质量和排序，不能来自买入价、买入时点、页面接口或样本口径悄悄变化。

**Files:**

- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Modify: `tests/alphaagent/test_limit_up_cash_backtest.py`
- Verify: `frontend/src/pages/LimitUpPage.tsx`
- Update: `memory/06_backtests/limit_up_formal_entry_price_audit_20260725.md`

- [x] **Step 1: 核实当前持久账本和正式页面调用链**

已核实页面固定请求 `portfolio`；572/572 个质量合格首板候选入场价等于涨停价，正式窗口
内 545/545 个相等；498 个首次触板触发、47 个窗口内回封触发。正式 243 个推荐中
239 个闭合，两仓 127 笔成交的原始价和账面成交价也全部相等。完整结果已写入入场审计。

- [x] **Step 2: 增加首板触板价回归测试**

在 `test_limit_up_lanes.py` 直接构造一只前收盘 10 元、涨停价 11 元的首板：

```python
candidate = history_engine._board_lane_candidates_from_day(
    first_board_day,
    signal_date,
    event_evidence=event_index,
    financial_index=financial_index,
    total_cost_rate=history_engine.ROUND_TRIP_COST_RATE,
)[0]
assert candidate["signal_kind"] == "first_touch"
assert candidate["buy_time"] == candidate["event_evidence"]["first_limit_time"]
assert candidate["entry_price"] == candidate["limit_price"] == 11.0
```

再构造 10 点前首次触板、10 点后首次回封的路径，断言 `signal_kind == "reseal"`、买入时间
等于第一次可观察回封时间，入场价仍为 11 元，不能取回封前的分钟价。

- [x] **Step 3: 锁定正式订单提取和现金成交上限**

在 `test_limit_up_scheduled_execution.py` 断言正式订单只读取完整质量候选池、只接受双窗口，
且不读取板前观察表。在 `test_limit_up_cash_backtest.py` 保留并扩展涨停价上限断言：原始价
已经是涨停价时，滑点不能把成交价推到涨停价之上。

- [x] **Step 4: 增加页面 `portfolio` 合同测试**

为 `LimitUpPage` 查询增加最小测试，断言回测始终传 `lane: "portfolio"`，且质量卡读取
`recommendation_quality`、两仓卡读取 `summary`；禁止把板前研究结果接到正式复利卡。

- [x] **Step 5: 运行定向验证并冻结基线**

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_lanes.py \
  tests/alphaagent/test_limit_up_scheduled_execution.py \
  tests/alphaagent/test_limit_up_cash_backtest.py
npm --prefix frontend test -- --run
```

预期：测试全过；正式版本仍为 v15/v9/v5；当前基线仍明确分为全量
`239 / 54.8117% / +0.5687% / +101.5433%` 和两仓
`127 / 58.2677% / +54.7953%`。计数因新交易日自然增加时更新报告，但入场等式不得改变。

## 因子合同

每个决策时点只保存分量，不先拍脑袋相加成一个总分：

```text
E(t)     市场情绪：上涨宽度、涨跌停、炸板率、分层晋级率、有效最高板和高度变化
L(i,t)   个股冲击：板位形态、相对强度、价格/成交加速度、封板质量、承载和既有 D+1 基因
P(k,t|i) 龙头 i 启动后，排除 i 自身的题材 k 在 1/3/5/10 分钟和后续交易日的增量传播
R(i,t)   点时角色概率：点火龙、空间龙、独立妖股、容量中军、龙二龙三、补涨或普通跟风
H(t)     切换风险：旧龙断板、传播衰减、资金脱钩、新题材点火和回流/反包
```

分钟传播对每个指标 `m` 和观察窗 `h` 使用差分中的差分，而不是原始相关性：

```text
P_m(i,k,t,h) =
  [m(题材k排除股票i, t+h) - m(题材k排除股票i, t-1m)]
  - [m(同市场阶段匹配对照, t+h) - m(同市场阶段匹配对照, t-1m)]
```

指标至少包括上涨家数、涨幅 >=3%/5%/7% 家数、近板数、触板数、封板数、炸板数、中位涨幅、成交额加速度和点时主力净流入。60 秒内同题材出现多个点火事件时合并为 `co_ignition_cluster`，不得事后把全部传播归功于其中涨幅最高的一只。

## Task 1: 修正有效连板和情绪基础口径

**Files:**

- Modify: `alphaagent/server/services/limit_up/sentiment.py`
- Create: `tests/alphaagent/test_limit_up_sentiment.py`

- [x] **Step 1: 写失败测试锁定市场交易日连续性**

构造交易日 `06-15、06-16、07-01、07-02`，股票只在 `06-15、07-01、07-02` 封板。断言 7 月 1 日高度为 1、7 月 2 日高度为 2；停牌缺口不能接续。

- [x] **Step 2: 写失败测试锁定晋级分母**

断言 `previous_is_limit_up`、一进二、二进三和最高板都只读取上一全市场交易日；股票缺少上一交易日行情时不进入对应晋级分母。

- [x] **Step 3: 写失败测试锁定情绪权重**

断言 `_sentiment_score()` 的六个预注册权重为 `0.28/0.22/0.18/0.14/0.10/0.08`，总和为 1；当前重复的第二个 `0.18 * max_streak` 必须删除。

- [x] **Step 4: 修改 SQL 连板分组**

在 `load_sentiment_points()` 的 CTE 中为全市场交易日生成连续序号，并为每只股票读取上一行交易日序号。只有“当前封板、上一行也封板、两个交易日序号相邻”才延续 streak；否则新建 streak group。

- [x] **Step 5: 运行测试和七月实数断言**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_sentiment.py
docker compose exec -T alphaagent-api python -m pytest -q tests/alphaagent/test_limit_up_sentiment.py
```

预期：测试全过；真实 7 月账本中恒尚节能为有效 7 板，7 月 3 日、6 日、7 日保留并列高度组。

## Task 2: 建立形态、角色和周期纯函数合同

**Files:**

- Create: `alphaagent/server/services/limit_up/leader_cycle_contract.py`
- Create: `tests/alphaagent/test_limit_up_leader_cycle_contract.py`

- [x] **Step 1: 写形态分类失败测试**

覆盖 `first_board_ignition`、`continuous_two_to_three`、`short_cycle_reboard_three`、
`higher_board_continuation` 和 `failed_reboard`。短周期反包三板使用最近五个市场交易日，要求当前封板、上一日未封、窗口内含当前恰有三次封板。

- [x] **Step 2: 写多角色和并列失败测试**

断言一只股票可同时有多个角色；同日两只最高板必须都保留；空间龙题材传播弱时仍可标记 `independent_demon`，不能被普通跟风覆盖。

- [x] **Step 3: 写周期状态机失败测试**

固定合法转移：

```text
ignition -> confirmation -> diffusion -> acceleration
acceleration -> divergence -> reflux
divergence -> ebb
reflux -> diffusion | acceleration | divergence | ebb
```

禁止从 `ebb` 用未来信息改写过去状态；新点火必须生成新 `cycle_id`。

- [x] **Step 4: 实现不可变数据合同**

公共函数固定命名为 `classify_board_pattern`、`assign_ex_post_roles`、
`advance_cycle_state`、`point_in_time_role_features` 和
`reject_future_feature_names`，并使用以下枚举与未来字段守卫：

```python
from enum import StrEnum

class BoardPattern(StrEnum):
    FIRST_BOARD_IGNITION = "first_board_ignition"
    CONTINUOUS_TWO_TO_THREE = "continuous_two_to_three"
    SHORT_CYCLE_REBOARD_THREE = "short_cycle_reboard_three"
    HIGHER_BOARD_CONTINUATION = "higher_board_continuation"
    FAILED_REBOARD = "failed_reboard"

class LeaderRole(StrEnum):
    THEME_IGNITION_LEADER = "theme_ignition_leader"
    SPACE_LEADER = "space_leader"
    INDEPENDENT_DEMON = "independent_demon"
    CAPACITY_CORE = "capacity_core"
    LEADER_2 = "leader_2"
    LEADER_3 = "leader_3"
    REPLENISHMENT = "replenishment"
    ORDINARY_FOLLOWER = "ordinary_follower"

FUTURE_FEATURE_FIELDS = frozenset({
    "final_role",
    "final_sealed",
    "final_board_height",
    "cycle_end_date",
    "d1_return_pct",
    "d1_won",
})

def reject_future_feature_names(names: Sequence[str]) -> None:
    forbidden = sorted(set(names).intersection(FUTURE_FEATURE_FIELDS))
    if forbidden:
        raise ValueError(f"future leader-cycle features are forbidden: {forbidden}")
```

`assign_ex_post_roles` 明确只生成研究标签；`point_in_time_role_features` 禁止读取 `final_role`、当日最终封板、D+1 结果和周期结束日期。

- [x] **Step 5: 运行纯函数测试**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_cycle_contract.py
```

预期：所有形态互斥规则、角色多标签、合法状态转移和未来字段守卫通过。

## Task 3: 固化数据覆盖和只读仓库

**Files:**

- Create: `alphaagent/server/services/limit_up/leader_cycle_repository.py`
- Create: `tests/alphaagent/test_limit_up_leader_cycle_research.py`

- [x] **Step 1: 写覆盖失败测试**

测试覆盖对象分别报告日线、1分钟、5分钟、点时成员、板块资金、概念强度、雷达帧和正式回放的开始/结束日期、交易日、股票日和帧数。禁止用全表最早日期冒充指定区间完整度。

- [x] **Step 2: 实现区间加载接口**

实现 `load_leader_cycle_inputs(start, end)`、
`load_intraday_propagation_inputs(trade_dates)` 和
`evaluate_propagation_coverage(payload)`。覆盖结果使用以下固定合同：

```python
from dataclasses import dataclass
from datetime import date

@dataclass(frozen=True, slots=True)
class CoverageRow:
    dataset: str
    first_date: date | None
    last_date: date | None
    trade_day_count: int
    symbol_count: int
    symbol_day_count: int
    frame_count: int
    row_count: int
    evidence_level: str
```

`evidence_level` 只允许 `point_in_time_complete`、
`point_in_time_partial`、`daily_only` 或 `unavailable`；加载结果按
`daily_bars/minute_bars/events/memberships/fund_flows/concept_strength/radar/formal_replays/coverage`
返回，不能用一个无类型 `rows` 容器混装。

复用 `history_repository.py`、`concept_snapshot_repository.py` 和
`radar_observation_repository.py` 的既有查询边界；不得在新仓库复制正式质量门 SQL。

- [x] **Step 3: 固定严格分钟可用门**

单个事件只有同时满足以下条件才进入分钟传播：D-1 或更早的点时题材成员、基线和全部目标窗帧、题材成员行情覆盖率至少 90%、事件股票真实分钟路径、同市场阶段对照可用。失败事件保留排除原因，不填零。

- [x] **Step 4: 核对数据供应能力**

通过现有 `akshare_adapter.py` 和数据同步任务只读检查以下能力：历史点时题材成员、历史板块分钟资金、全市场分钟行情。每项输出 `available/backfillable/forward_only`；供应商只提供当前快照时固定为 `forward_only`，不写临时抓取脚本伪造历史。

- [x] **Step 5: 运行覆盖测试和真实区间探测**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_cycle_research.py -k coverage
docker compose exec -T alphaagent-api python -m alphaagent.server.services.limit_up.leader_cycle_research --coverage-only --start 2026-03-01 --end 2026-07-24
```

预期：日级覆盖为 100 个交易日；严格分钟报告只接受真实完整日期，不把 3-6 月标记为分钟可回放。

## Task 4: 生成 3-7 月日级龙头周期账本

**Files:**

- Create: `alphaagent/server/services/limit_up/leader_cycle_research.py`
- Modify: `tests/alphaagent/test_limit_up_leader_cycle_research.py`
- Create: `memory/06_backtests/limit_up_leader_cycle_2026_03_07.md`

- [x] **Step 1: 写日级账本失败测试**

每个交易日必须输出市场阶段、有效最高板组、首板/一进二/二进三/高板晋级、即时资金主攻、5 日余温、角色组和周期状态。并列龙头和无明确主线日必须原样保留。

- [x] **Step 2: 复用题材家族分组**

使用 `sector_warmup.group_concepts()` 对同一快照日高重叠题材分组；执行概念继续由
`concept_resonance.is_execution_concept()` 过滤。缺少历史点时成员的 3-6 月标记
`current_membership_descriptive_only`，不得伪装成点时成员。

- [x] **Step 3: 生成三种持续时间**

分别输出 `board_spell_days`、`leadership_tenure_days`、
`theme_propagation_days`，并记录点火、确认、峰值、首次分歧、回流和结束日期。覆盖完整且确认没有扩散时 `theme_propagation_days=0`；缺少点时成员或传播数据时必须为 `None` 并标记 `unavailable`，不能借空间龙任期填充。

- [x] **Step 4: 固定七月黄金案例**

真实报告必须满足：

- 恒尚节能：7 月 1-9 日有效 7 板，题材传播弱，保留空间妖股身份。
- 哈药股份：7 月 10 日启动，7 月 14 日进入最高板，7 月 15 日医药资金大扩散；记录“个股领先题材确认”。
- 立新能源：7 月 16 日启动，7 月 20 日为连续第三板；7 月 21-22 日资金与高度脱钩，
  7 月 23 日储能/电网回流，7 月 24 日触板未封。
- 7 月 7-9 日：TMT 资金连续攻击，但不存在连续占据市场最高板的同题材个股；容量主线和情绪高度线必须分开。

- [x] **Step 5: 按相同定义完成六月、五月、四月、三月**

报告顺序固定为 7 月校验定义、6 月、5 月、4 月、3 月；每月给出周期总表、逐日切换、角色持续时间、主线与高度脱钩案例和数据限制，不为每月新增独立报告文件。

- [x] **Step 6: 运行报告并核对总数**

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.limit_up.leader_cycle_research --mode daily --start 2026-03-01 --end 2026-07-24 --output memory/06_backtests/limit_up_leader_cycle_2026_03_07.md
```

预期：报告覆盖 100 个交易日；每月交易日分别为 22、21、18、21、18，且没有无法解释的跨停牌连板。

## Task 5: 验证“股票先动，板块后扩散”的分钟传播

**Files:**

- Modify: `alphaagent/server/services/limit_up/leader_cycle_research.py`
- Modify: `tests/alphaagent/test_limit_up_leader_cycle_research.py`
- Create: `memory/06_backtests/limit_up_leader_propagation_intraday_202607.md`

- [x] **Step 1: 写排除龙头自身的失败测试**

构造只有龙头上涨、其他成员不动的题材。断言原始题材均值会上升，但排除龙头后的传播为 0，不能判定龙头带动板块。

- [x] **Step 2: 写事件先后和共点火失败测试**

断言题材成员在 `t0` 前已经上涨的不算龙头传播；同题材 60 秒内两只股票同时点火时合并为一个共点火簇，不强行确定唯一因果龙。

- [x] **Step 3: 写市场对照失败测试**

构造全市场同时普涨而题材没有超额扩散的样本。断言差分中的差分传播为 0；不能把大盘普涨误判为个股带动。

- [x] **Step 4: 实现传播面板**

实现 `build_ignition_events(payload)`、`build_propagation_panel(events, payload)`、
`match_market_controls(event, payload)` 和 `summarize_propagation(panel)`，并冻结：

```python
PROPAGATION_HORIZONS_MINUTES = (1, 3, 5, 10)
PROPAGATION_METRICS = (
    "rise_count",
    "strong_3_count",
    "strong_5_count",
    "strong_7_count",
    "near_limit_count",
    "touched_count",
    "sealed_count",
    "failed_count",
    "median_change_pct",
    "turnover",
    "main_net_inflow",
)
CO_IGNITION_WINDOW_SECONDS = 60
MINIMUM_MEMBER_COVERAGE_RATIO = 0.90
```

传播行主键固定为
`(trade_date, ignition_cluster_id, concept_group_id, horizon_minutes, metric)`，
并保存 `raw_theme_delta_ex_leader`、`matched_market_delta`、
`incremental_propagation`、`member_coverage_ratio` 和 `known_at`。

每个 horizon 保存原始题材变化、排除龙头后的变化、匹配市场变化和最终增量，不只保存总分。

- [x] **Step 5: 运行七月严格分钟报告**

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.limit_up.leader_cycle_research --mode intraday --start 2026-07-15 --end 2026-07-24 --output memory/06_backtests/limit_up_leader_propagation_intraday_202607.md
```

预期：报告首先列覆盖与排除表；7 月 20-24 日逐事件可复核，7 月 15-17 日只有通过严格覆盖的事件才进入结果，7 月 1-14 日不输出分钟因果结论。

实际结果：过滤事后/风格题材并排除全部点火股票后，严格门接受 `0` 个事件、排除
`4,184` 个事件、传播面板 `0` 行，状态固定为
`research_only/insufficient_point_in_time_coverage`。Task 5 的工程与排除审计已完成，
但现有数据不足以可靠验证“股票先动、板块后扩散”。

## Task 6: 生成点时角色和切换风险特征

**Files:**

- Modify: `alphaagent/server/services/limit_up/leader_cycle_contract.py`
- Modify: `alphaagent/server/services/limit_up/leader_cycle_research.py`
- Modify: `tests/alphaagent/test_limit_up_leader_cycle_contract.py`

- [x] **Step 1: 为五组因子写字段白名单测试**

固定 `E/L/P/R/H` 的字段名、来源、`known_at` 和缺失语义。缺失值保留缺失指示，不用 0 代表未知。

- [x] **Step 2: 实现点时角色特征**

个股特征包含有效板位、相对题材强度、距板、1/3/5 分钟价格与成交加速度、题材内触板顺序、开板/回封、D-1 成交额分位、同股 D+1 基因和财务承载质量。最终板数、周期峰值和 D+1 结果不得进入。

- [x] **Step 3: 实现切换风险特征**

切换风险必须分别记录旧龙断板/炸板、旧题材传播衰减、即时资金与高度脱钩、新题材共点火、容量中军迁移和回流恢复。不得把它们先压成一个布尔市场门。

- [x] **Step 4: 用七月路径验证状态序列**

哈药股份路径应产生“点火 -> 确认 -> 扩散 -> 分歧”；立新能源应包含“点火 -> 扩散 -> 分歧/脱钩 -> 回流 -> 退潮”；恒尚节能应显示空间高度持续而题材传播缺失。

- [x] **Step 5: 运行合同测试**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_cycle_contract.py
```

**Task 0-6 执行状态（2026-07-25）：** 上述工程、测试和真实数据报告均已完成。日级账本
覆盖 100 个交易日；正式版本、候选池、费用、触板价入场、D+1 退出和排序均未改变。
Task 5 因严格点时覆盖不足只形成排除审计，不形成机制成功结论；这不阻止 Task 0-6
按既定范围完成，但阻止后续模型或正式策略据此晋级。

## Task 7: 与正式首板、二进三和 D+1 结果连接

**Files:**

- Modify: `alphaagent/server/services/limit_up/leader_cycle_research.py`
- Modify: `tests/alphaagent/test_limit_up_leader_cycle_research.py`

- [ ] **Step 1: 写候选边界失败测试**

全市场角色表可以包含所有合格主板股，但收益表只能接入现有正式首板和二进三质量池。一个题材杂毛即使跟随涨停，只要不在正式质量池，就不得进入策略收益分母。

- [ ] **Step 2: 写三种形态独立统计测试**

首板、连续二进三、短周期反包三板分别报告候选数、触板率、封板率、D+1 胜率、平均净收益、利润因子、硬亏率和连亏分布；禁止把反包板混入连续二进三抬高晋级率。

- [ ] **Step 3: 连接现有 prior-only 基因**

复用现有 `expected_d1_net_return_pct`、`d1_win_probability`、
`seal_probability_given_touch`、同股样本数和联合率。所有历史基因必须满足
`result_date < signal_date`。

- [ ] **Step 4: 同时报全量质量和两仓账户**

每个因子版本先统计全量推荐独立槽位，再用现有现金回测按到达顺序统计两仓。报告必须同时展示两者，且说明两仓变化来自排序、占仓还是规则质量。

- [ ] **Step 5: 对连续亏损做角色归因**

将每段连亏分类为市场退潮、旧龙与资金脱钩、误报占仓、角色排序错误、题材扩散失败或个股 D+1 基因失效；同段未入选盈利候选必须并列报告，避免把排序错误笼统写成市场风格切换。

- [ ] **Step 6: 运行正式基线不变测试**

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_history.py \
  tests/alphaagent/test_limit_up_lanes.py \
  tests/alphaagent/test_limit_up_first_board_quality.py \
  tests/alphaagent/test_limit_up_leader_cycle_research.py
```

预期：加入研究连接前后的正式候选、动作、费用和订单逐笔一致。

## Task 8: 拟合角色、传播和切换概率并做消融

**Files:**

- Create: `alphaagent/server/services/limit_up/leader_cycle_model.py`
- Create: `tests/alphaagent/test_limit_up_leader_cycle_model.py`
- Modify: `alphaagent/server/services/limit_up/leader_cycle_research.py`

- [ ] **Step 1: 写样本门失败测试**

少于 60 个完整点时交易日、30 个传播正例或 30 个闭合正式候选时，模型返回
`insufficient_point_in_time_coverage`，所有概率为 `None`，不得回退为经验分数。

- [ ] **Step 2: 写日期隔离和标签翻转测试**

训练、校准和评估日期必须完全不重叠；翻转评估段最终触板、封板、D+1 或最终角色标签不能改变训练矩阵和模型指纹。

- [ ] **Step 3: 复用现有概率模型模式**

使用 `HistGradientBoostingClassifier` 加独立校准，分别输出：

```text
P(theme_diffusion | point-in-time state)
P(role = ignition/space/capacity/follower | point-in-time state)
P(old_leader_to_new_theme_switch | point-in-time state)
```

不覆盖现有三分钟触板、最终触板、触板后封板和 D+1 概率；所有概率分头保存并校准。

- [ ] **Step 4: 预注册加入/移除消融**

固定比较：正式基因基线、`+E`、`+E+L`、`+E+L+P`、`+E+L+P+R`、
`+E+L+P+R+H`，以及分别移除 `P/R/H`。每组同时报告 Brier、PR-AUC、Top1/Top2 命中、提前时间、触板/封板、D+1 质量、复利、回撤和连亏。

- [ ] **Step 5: 固定验证身份**

3-7 月已经被查看，只能作为 `development/adversarial_reuse`。日级模型需要更早历史做 expanding walk-forward；分钟模型需要 7 月之后至少 60 个完整交易日前向样本。不得把 3-7 月最优权重标记为生产结果。

- [ ] **Step 6: 运行模型测试**

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_leader_cycle_model.py
```

## Task 9: 只在通过门槛后接入动态龙头影子

**Files:**

- Modify: `alphaagent/server/services/limit_up/dynamic_leader_shadow.py`
- Modify: `tests/alphaagent/test_limit_up_dynamic_leader_shadow.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_service.py`

- [ ] **Step 1: 写正式不变失败测试**

无论角色概率是否存在，`action`、`formal_action`、正式候选顺序、扫板列表和两仓选择都必须逐字段不变；影子只能新增研究字段。

- [ ] **Step 2: 替换“单纯题材 Top5”语义**

保留当前题材锁定与原始分量，新增点时角色概率、传播概率、切换风险和证据新鲜度。当前
`global_top5` 继续只是 D+1 顺序内的跟踪标记，直到新排序完成独立前向验收。

- [ ] **Step 3: 增加角色感知影子排序**

只有 Task 8 样本门和历史门通过后，才生成独立 `leader_cycle_shadow_rank`。排序依次保留
D+1 预期收益、D+1 胜率，再比较触板、封板、传播、角色和切换风险；不增加新的正式硬门。

- [ ] **Step 4: 冻结前向验收**

至少 60 个完整交易日、30 个闭合 Top5 正式候选，并按市场阶段、首板、连续二进三和反包三板分别报告。Top5 必须在同日非 Top5 对照上同时改善 D+1 胜率、平均净收益和硬亏率，且不能依赖单一交易日。

- [ ] **Step 5: 运行影子与实时回归**

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_dynamic_leader_shadow.py \
  tests/alphaagent/test_limit_up_preboard_decision_service.py \
  tests/alphaagent/test_limit_up_live.py
```

## Task 10: 研究证据和正式晋级判定

**Files:**

- Modify: `alphaagent/server/services/limit_up/leader_cycle_model.py`
- Modify: `tests/alphaagent/test_limit_up_leader_cycle_model.py`
- Create: `memory/06_backtests/limit_up_leader_cycle_promotion.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_limit_up_leader_cycle_factor_research_plan.md`

- [ ] **Step 1: 只登记最终证据**

在索引中链接两份最终 Markdown；中间 DataFrame、JSON、截图和模型临时文件不进入
`memory/`，需要时从数据库和冻结命令重建。

- [ ] **Step 2: 更新当前决策，不追加聊天流水**

决策总览只保留当前正式基线、龙头研究状态、运行/验证命令、证据链接和仍未解决的数据风险。完成的过程说明由最终报告承载。

- [ ] **Step 3: 执行完整回归**

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

- [ ] **Step 4: 核对最终结论措辞**

最终报告必须分别回答：实际龙头是谁、持续多久、是否带动板块、是点火龙/空间妖股/容量中军还是跟风、因子是否改善正式质量池、改善来自全量质量还是两仓排序。覆盖不足时明确回答“尚未可靠”，不得用七月个案替代通用算法结论。

- [ ] **Step 5: 输出旧高收益恢复记分卡**

用完全相同的日期、费用、触板价入场和 D+1 收盘退出，逐列对比：当前正确基线、旧错误
财报反事实、每个单因子消融、最终组合因子。至少列出全量样本数、胜率、平均净收益、
逐日等权复利、最大回撤、硬亏率和最长连亏；明确标记是否超过当前基线、是否恢复旧全量
`62.1951%`，以及未恢复部分由哪个样本组贡献。不得只给一个最终总分。

- [ ] **Step 6: 冻结唯一晋级决定**

在 `leader_cycle_model.py` 生成可机读决定，测试必须锁定所有门同时通过才允许正式晋级：

```python
decision = build_leader_cycle_promotion_decision(scorecard)
assert decision == {
    "status": "forward_pass_for_formal",
    "policy_version": "limit-up-leader-cycle-v1",
    "model_fingerprint": frozen_fingerprint,
    "historical_gate_passed": True,
    "walk_forward_gate_passed": True,
    "forward_gate_passed": True,
    "parity_gate_passed": True,
    "product_gate_passed": True,
}
```

任一量化完成门失败时，状态固定为 `historical_rejected` 或
`insufficient_point_in_time_coverage`，不得写正式开关。此时可以完成研究报告，但 Task 11、
Task 12 和本计划总状态必须保持未完成。

## Task 11: 将通过验收的策略接入正式历史与实时后端

本任务才是从“研究有结论”进入“产品策略已改变”的边界。只有 Task 10 输出
`forward_pass_for_formal` 才能执行；否则不得为了完成计划手工打开。

**Files:**

- Create: `alphaagent/server/services/limit_up/leader_cycle_policy.py`
- Create: `tests/alphaagent/test_limit_up_leader_cycle_policy.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/preboard_decision_service.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`

- [ ] **Step 1: 写统一策略合同失败测试**

用同一候选和同一冻结模型分别模拟历史、板前和触板输入，断言质量结论与优先级一致：

```python
historical = evaluate_leader_cycle_candidate(history_candidate, policy)
preboard = evaluate_leader_cycle_candidate(preboard_candidate, policy)
live = evaluate_leader_cycle_candidate(live_candidate, policy)

assert historical.eligible == preboard.eligible == live.eligible
assert historical.priority == preboard.priority == live.priority
assert historical.reason_codes == preboard.reason_codes == live.reason_codes
```

再翻转 D 日最终封板、D+1 收益和盘后最终龙头标签，断言三者不变，证明正式策略没有读取
结算标签。

- [ ] **Step 2: 实现唯一正式策略模块**

`leader_cycle_policy.py` 只暴露以下稳定接口，其他服务不得自行复制权重或阈值：

```python
@dataclass(frozen=True)
class LeaderCycleDecision:
    eligible: bool
    priority: float
    role: str
    theme_stage: str
    reason_codes: tuple[str, ...]
    reason_text: str
    policy_version: str
    model_fingerprint: str


def evaluate_leader_cycle_candidate(
    candidate: Mapping[str, object],
    policy: FrozenLeaderCyclePolicy,
) -> LeaderCycleDecision:
    decision = policy.evaluate(candidate)
    if decision.policy_version != policy.version:
        raise ValueError("leader-cycle policy version mismatch")
    if decision.model_fingerprint != policy.model_fingerprint:
        raise ValueError("leader-cycle model fingerprint mismatch")
    return decision


def rank_leader_cycle_candidates(
    candidates: Sequence[Mapping[str, object]],
    policy: FrozenLeaderCyclePolicy,
) -> list[dict[str, object]]:
    evaluated = [
        {**dict(candidate), **asdict(evaluate_leader_cycle_candidate(candidate, policy))}
        for candidate in candidates
    ]
    return sorted(
        evaluated,
        key=lambda item: (
            item["eligible"] is not True,
            -float(item["priority"]),
            str(item.get("vt_symbol") or ""),
        ),
    )
```

模块只能加载 Task 10 通过的指纹；指纹缺失、模型不匹配或点时输入不完整时返回
`policy_unavailable`，并回退到当前 v15/v9 正式结果，不能清空买点，也不能临时使用影子权重。

- [ ] **Step 3: 接入历史全量推荐质量链**

在 `history_service._build_scheduled_history_backtest()` 中，现有静态质量门和同股 D+1 盈利门
通过后调用统一策略。全量推荐只保留 `eligible=True`，并保存 `leader_cycle_priority`、角色、
题材阶段、理由、版本和指纹。收益仍使用原触板/回封时间、涨停价和 D+1 官方收盘，不允许
因新策略改变入场或退出价格。

- [ ] **Step 4: 接入实时板前与正式扫板链**

在 `preboard_decision_service.py` 中只重排已有 `preboard_candidates`；它们仍是板前观察，
不写正式动作。在 `live_service.py` 中，于现有正式质量门和盈利门之后、构造
`actionable_recommendations` 之前应用同一 `eligible` 和 `priority`。已封板/回封且合格的
正式扫板买点必须继续显示，不能再次出现“板前候选退出导致扫板买点消失”。

- [ ] **Step 5: 保持真实到达先后并统一同批排序**

`scheduled_execution._scheduled_order_sort_key()` 先按交易日和可观察到达批次排序，仅在同一
批次内使用 `leader_cycle_priority` 决定优先级。禁止后来出现的高分票事后挤掉用户已执行的
早先买点；全量质量统计不受两仓限制，两仓账户单独记录优先级带来的占仓变化。

- [ ] **Step 6: 原子升级版本并保留回滚**

只有上述测试和 Task 10 晋级决定同时通过，才将唯一正式版本升级为
`limit-up-history-v16 / limit-up-live-v16 / limit-up-scheduled-v10`；现金执行继续
`limit-up-cash-v5`。正式开关必须同时校验策略状态和模型指纹；关闭开关后完整回退当前
v15/v9 候选、排序和买点，不删除历史账本。

- [ ] **Step 7: 运行后端正式同源回归**

```bash
uv run --group server pytest -q \
  tests/alphaagent/test_limit_up_leader_cycle_policy.py \
  tests/alphaagent/test_limit_up_history.py \
  tests/alphaagent/test_limit_up_live.py \
  tests/alphaagent/test_limit_up_scheduled_execution.py \
  tests/alphaagent/test_limit_up_preboard_decision_service.py
```

预期：历史/实时同源断言通过；晋级开关关闭时逐笔等于 v15/v9，开启时只改变候选质量结论
和同批顺序，不改变触板价、D+1 退出、费用和二进三形态定义。

## Task 12: 交付用户可用的正式排序并完成发布验收

**Files:**

- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/PreboardRanking.tsx`
- Modify: `frontend/src/features/limitUp/preboardRanking.spec.tsx`
- Modify: `frontend/src/features/limitUp/LiveSignalCard.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `frontend/src/features/limitUp/GuideView.tsx`
- Modify: `frontend/src/features/limitUp/GuideView.spec.tsx`
- Modify: `memory/06_backtests/limit_up_leader_cycle_promotion.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_limit_up_leader_cycle_factor_research_plan.md`

- [ ] **Step 1: 锁定前端正式字段合同**

扩展 `PreboardCandidate` 和正式 `LimitUpLiveSignal`：

```typescript
leader_cycle_policy_version: string | null;
leader_cycle_priority: number | null;
leader_cycle_role: string | null;
leader_cycle_theme_stage: string | null;
leader_cycle_reason: string | null;
leader_cycle_formal: boolean;
```

测试断言板前行和触板卡使用相同字段语义；`leader_cycle_formal=false` 时必须明确显示“研究
排序”，不能伪装成正式优先级。

- [ ] **Step 2: 让用户看到排序结果和原因**

板前表按正式优先级展示候选，同时保留 D+1 预期、D+1 胜率、三分钟/最终触板概率和封板率；
正式买点卡显示题材阶段、个股角色、优先级及一句中文理由。板前观察与正式买点继续分区，
不得把“高优先级”写成“保证涨停”或“保证 D+1 盈利”。

- [ ] **Step 3: 增加桌面与移动端渲染测试**

```bash
npm --prefix frontend test -- --run \
  src/features/limitUp/preboardRanking.spec.tsx \
  src/features/limitUp/GuideView.spec.tsx
```

预期：长股票名、长题材名和中文理由不覆盖其他列；390px 下可横向访问概率和优先级；正式
扫板卡不会因板前列表存在而隐藏。

- [ ] **Step 4: 重建正式账本并核对页面指标**

以 v16/v10 重建相同截止日账本，页面必须同时展示全量推荐和两仓账户。API、报告和页面的
样本数、胜率、平均收益、复利和回撤逐项相等；买入价审计仍为首板
`entry_price == limit_price`。

- [ ] **Step 5: 执行完整回归和浏览器验收**

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

再用 Playwright 检查 `/short-term` 的 1280px 和 390px：板前优先级、正式扫板、中文原因、
回测全量指标和两仓指标均可见，页面无重叠、无横向页面溢出、控制台无错误。

- [ ] **Step 6: 写最终状态并关闭计划**

只有量化完成门、正式后端、页面和回滚全部通过，才能勾选本步骤并在决策记忆中写
“`limit-up-leader-cycle-v1` 已正式启用”。若未达到旧全量恢复目标，报告必须写清差额和
失败样本组，本计划保持未完成；不能以“龙头周期研究报告已生成”关闭任务。

## 执行顺序和停止条件

1. Task 0 先锁定触板/回封涨停价入场、页面 `portfolio` 和当前双口径指标。
2. Task 1-4 可以立即完成，得到 3-7 月真实日级周期。
3. Task 5 在现有七月后半段数据上立即完成严格小样本机制验证。
4. Task 6-7 可以立即完成因子面板和正式回测连接，但结果仍是已查看历史研究。
5. Task 8 若点时样本门不足，必须以明确状态结束，不继续调阈值。
6. Task 9 只有 Task 8 通过后才生成独立影子排序；当前正式买点仍不改变。
7. Task 10 必须给出可机读晋级决定；研究报告本身不能触发正式版本。
8. Task 11 仅在五层量化完成门全部通过后执行，并把同一策略接入历史与实时后端。
9. Task 12 完成页面、账本、回滚和端到端验收后，整个计划才允许标记完成。
10. 任何阶段发现正式首板、二进三、扫板动作或 D+1 结算被非预期改变，立即停止并先修复回归。
