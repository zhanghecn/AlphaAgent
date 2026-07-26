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

- 唯一正式合同为 `limit-up-core-ab-v1`；历史、实时、调度和现金账本使用
  同一公开版本。旧 `v15/v9/v5` 只作历史研究与审计证据，不参与当前准入、排序或回退。
- 正式全量规则是 A+B：原正确财报、结构、lane、盘中支撑和同股盈利门通过后，
  统一要求 `2 <= prior_limit_count_126 <= 6`。D-1 行业成交额相对前 5 日均值
  `>=1.0` 为 A，其余为 B；A 优先，B 仍可交易。C 级不存在于正式合同。
- 正式策略保留首板、二进三、两仓现金账户、正式费用和 D+1 官方日线收盘退出。
  竞价止盈、盘中最优退出和结果后选择卖点不属于正式合同。
- `actionable_recommendations` 是不受两仓容量限制的正式触发列表；`portfolio` 才对应
  两仓现金账户。全量规则质量和两仓到达顺序结果必须分别报告。
- 合格的 `near_limit/sealed/resealed` 可以形成正式涨停价排队买点；封板/回封不保证
  成交。板前研究触板后退出自己的观察表，不能清除正式扫板买点。

### Formal historical and forward status

- 806 个交易日是行情背景；真实事件覆盖 `2025-06-27..2026-07-24`，正式闭合
  推荐覆盖 `2025-07-10..2026-07-23`，不是因为日线只有这一年。
- A+B 已按新合同重建：78 笔全量独立闭合交割，`56/78=71.7949%`，平均
  净收益 `+2.2512%`，最大回撤 `-14.5416%`，硬亏 `7/78=8.9744%`。A 为
  `35/41=85.3659%`，B 为 `21/37=56.7568%`；全量口径必须报 A+B，不能只报 A。
- 78 笔分布在 50 个交易日，日均 1.56 笔、单日最多 5 笔；“笔”是一只股票的
  一次独立买卖，同日可以有多笔，不是每日限一笔。
- 最近旧保存快照的 A+B 反事实只有 `12/24=50%`、平均 `-0.2351%`，未达到
  60% 门。当前状态固定为 `historical_pass_forward_not_passed`；历史 71.7949%
  不是实盘胜率承诺，也不允许回退到旧财报覆盖逻辑。
- 财报点时修复后的前一正式基线是 243 个全量信号、239 笔闭合，胜率
  `54.8117%`、平均净收益 `+0.5687%`。它现在只用于解释 A+B 的增量，不再是当前合同。
- 正式首板回测已核实为触板价口径：572 个质量合格候选全部按涨停价记账；正式双窗口
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

- 集合顺序为 `raw_capture_pool -> eligible_first_board_pool -> quality_pool -> action_pool -> filled_pool`。
  股票先通过正式同源首板质量门，涨幅达到 3% 后才启动板前跟踪；普通全市场 3% 股票
  不进入模型、页面推荐或收益回测。
- prior-only 的 D+1 预期收益、D+1 胜率、触板后封板率和封板后 D+1 质量继续负责交易
  质量；动态模型只补充三分钟触板概率和当日最终触板概率。
- 当前模型为 `ready / historical_rejected / research_only / not_eligible`。validation 中
  正式触板首板为 22 笔、63.64% 胜率、`+23.38%` 复利；严格板前为 27 笔、51.85%、
  `+6.10%`，41 个动作最终触板率只有 48.78%。概率有排序信息，但尚未达到正式替换门。
- 实时只公开双概率真实有效的板前候选；输入不合格或模型不可用只保留内部审计，不伪装
  成页面观察。板前研究不写正式动作、不占两仓、不替换二进三。
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
  只保留研究证据，不修改 A+B 准入、排序或下单链。
- 可重启动态波段已经识别金安国纪、亨通光电、东山精密、德明利和深科技的趋势/容量
  领导力；多概念重复归属和 3-6 月成员幸存者偏差仍未解决，月度占席榜不能作为唯一
  情绪龙结论。
- 财报旧高胜率来自按当前成交额/市值优先同步形成的资金关注粘性白名单，不是错误财务
  字段本身。正确同比仍有正边际，不恢复“本地财报缺失即拒绝”。
- 最终只保留 A+B：`56/78=71.7949%`。A+B+C 新增 C 级只有
  `24/43=55.8140%` 且 2025 分段低于 60%，已否决；动态概念因素不能绕过核心质量门。
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

### Open risks and next work

- 2026 年 3-6 月有完整日线但没有历史点时题材成员和盘中板块资金，只能做日级轮换；
  7 月 15-24 日也没有事件同时满足成员、分钟路径和匹配市场对照门。
- 3-7 月已经被查看，只能作为龙头映射因子发现/反例样本，不能承担最终晋级结论。
- `limit-up-core-ab-v1` 的自然前向账本必须从新合同实际保存快照起算；最近
  24 笔旧快照反事实只是风险证据，不是自然前向样本。累计至少 60 个新交易日、
  30 笔闭合全量买点和两个情绪阶段后，再按胜率 `>=60%`、均值为正、回撤和硬亏判定。

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
