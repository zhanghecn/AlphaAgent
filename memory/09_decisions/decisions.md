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

- 唯一正式版本为 `limit-up-history-v15`、`limit-up-live-v15`、
  `limit-up-scheduled-v9` 和 `limit-up-cash-v5`。
- 正式策略保留首板、二进三、两仓现金账户、正式费用和 D+1 官方日线收盘退出。
  竞价止盈、盘中最优退出和结果后选择卖点不属于正式合同。
- `actionable_recommendations` 是不受两仓容量限制的正式触发列表；`portfolio` 才对应
  两仓现金账户。全量规则质量和两仓到达顺序结果必须分别报告。
- 合格的 `near_limit/sealed/resealed` 可以形成正式涨停价排队买点；封板/回封不保证
  成交。板前研究触板后退出自己的观察表，不能清除正式扫板买点。

### Current historical baseline

- 财报点时修复后的 806 日账本有 243 个全量信号、239 笔闭合，胜率 `54.8117%`、
  平均净收益 `+0.5687%`、复利 `+101.5433%`、最大回撤 `-30.6303%`。
- 同期两仓账户有 127 笔闭合，胜率 `58.2677%`、复利 `+54.7953%`、最大回撤
  `-20.6187%`。
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

- `dynamic-concept-leader-shadow-v1` 只在正式质量链候选上保存题材、题材内龙位、市场
  转化、资金承载和概率分量；执行效果固定为 `none_research_only`。
- 当前题材 Top5 只是采集/展示层，不是通用龙头算法。七月已经确认情绪高度、资金主线和
  板块传播会错位：恒尚节能是独立空间龙，哈药股份的医药扩散晚于个股启动，立新能源
  经历电力点火、资金脱钩和回流。
- 下一研究必须分别计算个股连板路径、市场龙头任期和题材传播周期，并覆盖首板点火、连续
  二进三、短周期反包三板、空间妖股、容量中军、龙二龙三、补涨和普通跟风。
- 执行计划：`requirements/alphaagent_limit_up_leader_cycle_factor_research_plan.md`。

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

- 板前合同：`requirements/alphaagent_limit_up_preboard_decision.md`。
- 板前冻结：`memory/06_backtests/limit_up_preboard_decision_validation_20260723.md`。
- 最近实时时序：`memory/06_backtests/limit_up_live_vs_backtest_entry_audit_20260723.md`。
- 实时发布修复：`memory/06_backtests/limit_up_preboard_live_publication_fix_20260724.md`。
- 财报修复：`memory/06_backtests/limit_up_financial_point_in_time_fix_20260724.md`。
- 旧 70% 审计：`memory/06_backtests/limit_up_legacy_70pct_liquidity_audit_20260724.md`。
- 动态龙头因子：`memory/06_backtests/limit_up_dynamic_leader_style_factor_20260724.md`。
- 七月周期：`memory/06_backtests/limit_up_emotion_leader_cycle_july_20260725.md`。
- 正式入场价格：`memory/06_backtests/limit_up_formal_entry_price_audit_20260725.md`。

### Open risks and next work

- 当前情绪 SQL 未检查股票行之间是否隔着市场交易日，且情绪分重复计算了一次最高板权重；
  龙头周期计划的 Task 1 必须先修正。
- 2026 年 3-6 月有完整日线但没有历史点时题材成员和盘中板块资金，只能做日级轮换；
  严格分钟传播当前主要覆盖 7 月 20-24 日。
- 3-7 月已经被查看，只能作为发现/对抗复用样本。生产晋级仍需更早 walk-forward 和至少
  60 个完整新前向交易日、30 个闭合 Top5 信号。
- 龙头因子只能提高正式质量池内的用户优先级，未通过消融和前向门前不得绕过正式质量门。

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
