# AlphaAgent Quant Cleanup Master Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 AlphaAgent 当前量化候选、组合回测、严格 14:30 执行、数据补数、个股诊断和策略验证整理成一个口径唯一、可核查、可继续重构的 A 股量化研究工作台。

**Architecture:** 不修改继承的 `vnpy/` 核心和官方 examples；业务代码只在 `alphaagent/`、`frontend/src/`、`tests/`、`docs/`、`memory/` 演进。普通新建组合回测固定走 `strict_1430 / 1m / 14:30 / strict_entry=true`：D 日收盘后只用 D 日及以前可见数据生成 D+1 买卖计划，D+1 只有在 14:30 的 1 分钟快照存在且满足执行条件时才成交。`tail_close_hybrid` 只保留为研究对比，`legacy_next_open` 只保留旧报告兼容。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、React、TanStack Query、TypeScript、pytest、Docker Compose、Playwright/Chromium 真实浏览器测试。

---

## 0. 当前源码事实

核查日期：2026-06-14。

### 0.1 当前主流程

候选生成：

```text
GET /api/quant/trading-dates
-> 从 stock_daily_bars 聚合本地真实交易日
-> 前端候选日期和回测开始日期只在本地有日线数据的交易日之间切换

POST /api/quant/screen-runs/range
-> 从用户选择的起始交易日到本地最新交易日逐日筛选
-> 每天只使用该日及以前可见数据
-> 写 quant_signal_runs / quant_stock_signals / quant_recommendations
-> 只把最后一个交易日同步到“量化候选”组合分组
```

组合回测：

```text
POST /api/backtests
-> BacktestParams 默认 strict_1430 / 1m / 14:30 / strict_entry=true
-> 读取股票池、预热日线、财报历史可见性、资金流/热度/板块上下文
-> 按历史交易日循环
-> 先执行上一交易日生成的卖出/买入计划
-> 再更新现金、持仓市值、总权益、逐股持仓快照
-> 用当天收盘后可见数据为下一交易日生成 BUY/SELL 理论计划
-> 写订单、成交、权益曲线、持仓快照、理论信号流水
```

执行规则：

```text
D 日生成信号
-> D+1 执行
-> strict_1430 必须命中 D+1 14:30 的 1m bar
-> 买入还要满足尾盘/MA5 触发条件
-> 涨停买不到、跌停卖不出、缺快照、尾盘未触发、仓位满、现金不足都会拒单或跳过
-> ledger.py 计算滑点、佣金、印花税、100 股整数手、现金和持仓变化
```

BUY/WATCH：

```text
BUY：entry_signal=true，普通组合回测会尝试买。
WATCH：观察候选，普通组合回测不买。
strict_entry=false：宽松研究模式，WATCH 可能参与，只能放在研究/参数验证入口。
```

### 0.2 当前策略

正式注册在 `alphaagent/server/services/quant/strategy_registry.py`：

| 策略 | 版本 | 作用 | 当前结论 |
| --- | --- | --- | --- |
| `mainline_leader_pullback` | `0.1.1` | 主线强势回踩 MA5 低吸 | 当前默认策略。`#62` 严格 14:30 为负收益，执行真实性较好但策略稳健性弱。 |
| `breakout_confirmation` | `0.1.0` | 平台放量突破确认 | 链路可用，但严格同口径经常 0 成交，不能把 0% 当有效收益。 |
| `limit_up_after_pullback` | `0.1.0` | 涨停后回踩确认 | 能捕捉金安国纪一类信号，但样本小且严格样本仍为负。 |
| `trend_acceleration` | `0.1.0` | 趋势形成后的温和加速 | 已接入链路，当前严格同口径 0 成交，只能继续验证。 |

策略原则：

- 不为金安国纪写股票特例。
- 不用硬改低吸阈值覆盖所有形态；不同买点应由不同策略解释。
- 调参前先做候选质量、交易归因、亏损归因、参数敏感性和 walk-forward。

### 0.3 5 分钟、10 分钟、多周期边界

严格回测和严格缺口补数只支持 `1m / 14:30`：

- `alphaagent/server/services/backtest/execution_models.py`：`SUPPORTED_BACKTEST_MINUTE_INTERVALS = {"1m"}`。
- `alphaagent/server/services/backtest/schemas.py`：`BacktestParams(minute_interval="5m")` 会拒绝。
- `alphaagent/server/services/minute_gaps.py`：严格缺口审计只接受 `1m`。
- `tests/alphaagent/test_quant_backtest_portfolio.py`：已有 `5m` 回测拒绝和 `10m` 导入拒绝测试。

可保留但必须隔离的多周期能力：

- 股票详情看盘：`frontend/src/features/stocks/StockKlineChart.tsx` 可保留 `5m/15m/30m/60m`。
- 通用最近分钟线同步：`sync_stock_minute_bars mode=recent` 可保留 `1m/5m/15m/30m/60m`。
- 通用分钟 CSV/文件导入：`alphaagent/server/services/minute_imports.py` 可保留 `1m/5m/15m/30m/60m`。

结论：

```text
严格回测执行快照：只支持 1m / 14:30。
行情查看/通用同步导入：可支持 5m/15m/30m/60m。
10m：不作为产品功能入口，只保留拒绝测试和历史说明。
```

### 0.4 当前已完成的收口

- 普通新建组合回测默认已收敛到 `strict_1430`。
- 前端普通回测参数里 `ExecutionModel` 已收窄为 `"strict_1430"`。
- `/quant -> 回测` 高级执行设置只展示“严格14:30 / 1分钟 / 14:30快照 / 只买 BUY”。
- 候选覆盖面板已分页显示所有交易日，不再只看最近 12 天。
- 回测钻取日期已经包含 BUY/WATCH 候选数、理论计划、真实交易和拒单概览。
- `#62` 是当前完整严格基线：21/21 买入使用真实 14:30，收盘代理 0，缺快照拒单 0，仍为负收益。
- `#70` 恢复早期理论信号，能解释金安国纪 2026-02-09 BUY，但有 400 个缺 14:30 快照拒单，不能替代 `#62` 作为完整严格基线。

### 0.5 当前仍然明显过大的文件

```text
alphaagent/server/services/backtest/engine.py              3075 行
alphaagent/server/services/data_sync.py                    4081 行
frontend/src/api/quant.ts                                  1807 行
frontend/src/pages/StockDetailPage.tsx                     1679 行
frontend/src/pages/DataManagementPage.tsx                  1129 行
tests/alphaagent/test_quant_backtest_portfolio.py          5895 行
alphaagent/server/services/quant/screening.py               801 行
frontend/src/features/quant/BacktestDrilldownPanel.tsx      571 行
frontend/src/features/quant/MinuteDataWizard.tsx            439 行
```

这些文件不是马上删，而是按模块边界等价拆分，先保行为，再优化。

---

## 1. 需要删除或下线

### D1. 普通产品入口删除 `10m`

删除范围：

- `/quant` 普通回测。
- `/quant -> 数据` 严格补数。
- `/data` 回测缺口补数。
- API/产品文案中把 `10m` 描述为严格回测周期的内容。
- 旧计划中“用 10m 替代 14:30”的执行描述。

保留范围：

- 拒绝测试。
- 历史说明中明确标注为过期尝试的内容。

验收：

```bash
rg -n "10m|10分钟" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx frontend/src/pages/DataManagementPage.tsx alphaagent/server/services/backtest docs/alphaagent -S --glob '!**/*.tsbuildinfo'
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "obsolete_10m or minute_interval" -q
```

### D2. 普通严格回测删除 `5m` 暗示

删除范围：

- “5m 可以降低数据量并替代严格 14:30”的文案。
- 严格回测普通表单中的周期选择。
- 严格缺口补数普通路径中的周期选择。

保留范围：

- 股票详情看盘 `5m/15m/30m/60m`。
- 通用最近分钟线同步。
- 通用分钟 CSV/文件导入。

验收：

```bash
rg -n "5m|5分钟" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx frontend/src/pages/DataManagementPage.tsx alphaagent/server/services/backtest docs/alphaagent -S --glob '!**/*.tsbuildinfo'
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_interval or strict_1430" -q
pnpm --dir frontend run build
```

### D3. 普通入口下线 `tail_close_hybrid`

原因：

- `tail_close_hybrid` 缺 14:30 快照时会使用执行日日线收盘价代理尾盘成交。
- 它适合研究对比，不应和默认严格回测并列出现在普通执行设置里。

保留：

- 执行模型对比面板。
- 策略/执行研究对比 API。
- 旧报告解释。

下线：

- 普通“运行组合回测”入口。
- 普通新建回测 UI 的执行模型下拉。
- 任何把尾盘混合称为“真实分钟回测”的文案。

验收：

```bash
rg -n "tail_close_hybrid|尾盘混合" frontend/src/features/quant/BacktestParamsForm.tsx frontend/src/pages/QuantTradingPage.tsx frontend/src/features/quant/constants.ts
pnpm --dir frontend run build
```

### D4. 普通入口下线 `legacy_next_open`

保留：

- 后端兼容旧报告。
- 报告里显示“旧报告兼容”。

下线：

- 新建回测 UI。
- 普通策略对比入口。
- 新文档中的推荐路径。

验收：

```bash
rg -n "legacy_next_open|daily_next_open_fallback|旧版次日开盘" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx docs/alphaagent -S
```

### D5. 普通补数下线 CSV-first

普通补数路径必须是：

```text
回测 ID
-> 审计 14:30 缺口
-> 选择 provider
-> dry-run 预检查
-> 写入
-> 复审覆盖
-> 运行 strict_1430
```

高级兜底才允许显示：

- 缺口 CSV。
- 供应商清单 CSV。
- 外部分钟线 CSV。
- 服务器文件路径。

验收：

```bash
pnpm --dir frontend run build
```

真实浏览器：

```text
/quant -> 数据
/data -> 股票分钟 K 线 -> 回测缺口
普通区只看到回测 ID/provider/固定 1m 14:30；CSV/file_path 只在高级区。
```

### D6. 删除旧绩效作为策略有效性的证据

处理规则：

- `strategy_version < 0.1.1` 的绩效只保留为历史排查。
- 卖出时序修复前的报告必须标为“旧口径，需重跑”。
- `memory/06_backtests/` 中旧报告不删除，但当前结论只引用修复后重跑结果。

### D7. 标记旧计划文件为过期

当前唯一执行主计划是本文件：

```text
docs/plans/2026-06-14-quant-cleanup-master-plan.md
```

旧计划保留历史背景，但不作为执行依据：

- `docs/plans/2026-06-14-quant-current-state-cleanup-roadmap.md`
- `docs/plans/2026-06-14-quant-refactor-and-feature-roadmap.md`
- `docs/plans/2026-06-14-quant-tail-close-hybrid-cleanup.md`

---

## 2. 需要重构

### R1. 继续瘦身 `backtest/engine.py`

已完成：

```text
execution_models.py  执行价、14:30、收盘代理、涨跌停、旧模型兼容
ledger.py            现金、费用、滑点、印花税、100 股整数手
schemas.py           BacktestParams、MinuteBar、Position、Trade、ScoreContext
reports.py           扩展指标、真实性检查、CSV 内容生成
persistence.py       backtest_* 表写入、字段过滤
scoring.py           BUY/WATCH 策略入口、候选过滤
validation.py        参数网格、walk-forward、稳健性辅助
queries.py           成交分页、权益、日期/股票详情、候选追踪、审计读侧
simulation.py        组合回测状态机第一版
```

下一步：

```text
backtest/engine.py
  只保留 run_backtest 编排入口、list/get wrapper 和兼容导出

backtest/data_loading.py
  股票池、日线预热、分钟线索引、财报/资金流/热度/板块上下文加载

backtest/benchmarking.py
  指数基准、样本等权、随机样本、市场状态分段

backtest/execution_comparison.py
  tail_close_hybrid 与 strict_1430 的同参数对比

backtest/minute_coverage.py
  minute-coverage、minute-gaps、数据质量中与订单相关的统计
```

规则：

- 每次只抽一个主题。
- 不改收益口径。
- 不改策略阈值。
- 保持 `run_backtest(params)` 返回契约不变。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py
```

### R2. 继续瘦身 `data_sync.py`

已完成：

```text
minute_gaps.py             严格 14:30 缺口解析、审计、模板、供应商清单
minute_imports.py          标准分钟 CSV/文件导入、路径安全、upsert
minute_provider_imports.py 回测 ID/gap_csv/file_path -> provider -> import result 编排
```

下一步目标结构：

```text
data_sync/jobs.py
  JobDefinition、DEFAULT_JOBS、SYNC_BATCH_PROFILES

data_sync/batches.py
  批次执行、进度、运行记录

data_sync/recent_minutes.py
  sync_stock_minute_bars mode=recent

data_sync/backtest_gap_minutes.py
  sync_stock_minute_bars mode=backtest_gaps provider 编排

data_sync/local_queries.py
  本地股票、日线、分钟、板块查询 helper

data_sync/progress.py
  同步批次进度、sample_items、当前任务状态格式化
```

边界：

- `mode=backtest_gaps` 固定 `1m / 14:30`。
- `mode=recent` 可以保留多周期，但 UI 必须标为行情同步，不是严格回测补数。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "data_sync or minute_bars or minute_gap or backtest_gaps or recent" -q
uv run python -m compileall alphaagent/server/services alphaagent/server/api/data_sync.py
```

### R3. 拆 `frontend/src/api/quant.ts`

目标：

```text
frontend/src/api/quant/index.ts
frontend/src/api/quant/types.ts
frontend/src/api/quant/strategies.ts
frontend/src/api/quant/screening.ts
frontend/src/api/quant/backtests.ts
frontend/src/api/quant/diagnostics.ts
frontend/src/api/quant/simulation.ts
```

要求：

- 保持 `@/api/quant` import 兼容。
- 先移动类型和函数，不改 URL。
- 不在同一步改 UI。

验收：

```bash
pnpm --dir frontend run build
```

### R4. 拆 `StockDetailPage.tsx`

目标：

```text
frontend/src/pages/StockDetailPage.tsx
  页面组合和数据入口

frontend/src/features/stocks/StockQuantAuditPanel.tsx
  量化信号复核、策略历史、指定组合回测原因

frontend/src/features/stocks/PortfolioBacktestSymbolPanel.tsx
  指定组合回测下的股票归因

frontend/src/features/stocks/PortfolioDiagnosticsSummary.tsx
  个股诊断摘要

frontend/src/features/stocks/SingleStockBacktestPanel.tsx
  单股严格回测和买卖点
```

验收样例：

```text
/stocks/002636.SZSE
选择 backtest_id=62 或 70
查看策略历史 BUY、指定组合没买原因、财报历史可见性
```

### R5. 拆 `DataManagementPage.tsx`

目标：

```text
frontend/src/features/data/StatusTab.tsx
frontend/src/features/data/SyncTab.tsx
frontend/src/features/data/SourcesTab.tsx
frontend/src/features/data/MinuteSyncParamsPanel.tsx
frontend/src/features/data/BatchProgress.tsx
```

约束：

- `backtest_gaps` 普通表单继续固定 `1m / 14:30`。
- 高级区才出现 CSV/file_path。
- `recent` 模式若显示多周期，必须明确是行情同步。

### R6. 拆 `QuantTradingPage.tsx` 状态

目标：

```text
frontend/src/pages/QuantTradingPage.tsx
  只保留页签和高层事件

frontend/src/features/quant/hooks/useQuantWorkspace.ts
  策略、交易日、候选、筛选、模拟账户、组合分组状态

frontend/src/features/quant/hooks/useBacktestSelection.ts
  回测列表、选中回测、报告、审计、覆盖、验证
```

约束：

- 新建组合回测继续强制传 `execution_model="strict_1430"`、`minute_interval="1m"`、`tail_entry_start/end="14:30"`。

### R7. 拆 `BacktestDrilldownPanel.tsx`

已完成第一步：

- `BacktestDecisionTimeline.tsx` 已拆出。

下一步：

```text
BacktestDailyDetailPanel.tsx
  日期钻取：现金、持仓市值、总权益、买入、卖出、拒单

BacktestSymbolDetailPanel.tsx
  股票钻取：理论 BUY、实际买入、持仓、卖出、拒单原因

BacktestRejectedReasonPanel.tsx
  当日/个股拒单原因分布
```

### R8. 拆 `screening.py` 中个股历史逻辑

目标：

```text
quant/symbol_history.py
  symbol_signal_history()
  symbol_strategy_comparison()

quant/symbol_diagnostics.py
  策略历史 + 指定回测归因 + 财报可见性

screening.py
  保留 wrapper 兼容旧调用
```

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "symbol_signal or symbol_strategy or diagnostics" -q
```

### R9. 拆测试文件

目标：

```text
tests/alphaagent/test_backtest_execution_models.py
tests/alphaagent/test_backtest_ledger.py
tests/alphaagent/test_backtest_queries.py
tests/alphaagent/test_backtest_reports.py
tests/alphaagent/test_backtest_strategy_comparison.py
tests/alphaagent/test_quant_strategies.py
tests/alphaagent/test_quant_symbol_diagnostics.py
tests/alphaagent/test_minute_gap_imports.py
tests/alphaagent/test_data_sync_minute_jobs.py
```

规则：

- 先移动测试，不改断言。
- 每次拆一个主题。
- 公共 helper 放测试 helper，避免复制。

---

## 3. 需要调整

### A1. 回测结果第一屏先显示真实性，再显示收益

第一屏必须先回答：

```text
执行模型是什么？
买入多少笔是真实 14:30？
有没有收盘代理？
有没有缺快照拒单？
有没有尾盘未触发拒单？
这份收益能不能当作真实分钟回测？
```

相关文件：

- `frontend/src/features/quant/BacktestSummary.tsx`
- `frontend/src/features/quant/BacktestAnalysis.tsx`
- `frontend/src/features/quant/MinuteCoveragePanel.tsx`
- `frontend/src/features/quant/BacktestDataQualityPanel.tsx`

### A2. 候选页强化“区间生成、逐日查看”

调整：

- 按钮文案统一为“生成区间候选”。
- 明确从“生成区间起点”到“最近本地交易日”逐日筛选。
- “查看交易日”只切换当天候选，不重新筛选。
- 显示已运行天数、未运行天数、最后同步到候选分组的日期。
- 支持点击日期查看当天 BUY/WATCH/失败规则。

相关文件：

- `frontend/src/features/quant/CandidateRunCoveragePanel.tsx`
- `frontend/src/features/quant/RecommendationsPanel.tsx`
- `alphaagent/server/api/quant.py`

### A3. 日期选择继续交易日化

所有日期选择都必须区分：

```text
生成区间起点
查看候选交易日
回测开始日期
信号计划开始/结束日期
回测内复核日期
```

自然日输入自动对齐最近本地交易日，并显示提示。

### A4. BUY/WATCH 文案统一

统一文案：

```text
BUY：默认组合回测会尝试买。
WATCH：默认组合回测不买。
宽松研究：显式开启后 WATCH 可能参与，只用于策略探索。
```

应用位置：

- 候选表。
- 信号计划。
- 候选追踪。
- 股票详情个股诊断。
- 回测报告。
- 策略对比。

### A5. 回测钻取继续增强

需要补强：

- 日期钻取顶部固定显示现金、持仓市值、总权益、当日买入、当日卖出、当日拒单。
- 股票钻取顶部固定显示是否曾 BUY、是否实际买入、没买原因、持仓期间、卖出原因。
- 理论信号金额预览和真实组合订单/成交必须视觉分开。
- “组合最近成交”默认分页，不只看最近若干条。
- 加入“当日拒单原因分布”。
- 股票钻取状态条固定区分“理论 BUY 但未计划 / 已计划但拒单 / 已成交 / 持仓中 / 已卖出”。

### A6. 金安国纪按标准流程处理

不写股票特例。标准诊断必须回答：

- 各策略有几次 BUY。
- 最佳 BUY 日期是什么。
- 指定组合回测 ID 下是否真实买入。
- 没买原因是未入选、WATCH、排名落后、仓位满、现金不足、涨停、跌停、尾盘未触发还是缺快照。
- 财报在该历史日期是否 `publish_date <= trade_date` 可见。

相关文件：

- `alphaagent/server/services/quant/symbol_diagnostics.py`
- `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- `frontend/src/pages/StockDetailPage.tsx`

### A7. 财报缺失提示改为“历史可见性”

所有提示区分：

```text
本地是否有财报
财报是否有 publish_date
publish_date 是否 <= trade_date
是否晚于回测日披露
```

相关文件：

- `alphaagent/server/services/quant/financials.py`
- `alphaagent/server/services/quant/symbol_diagnostics.py`
- `frontend/src/pages/StockDetailPage.tsx`

### A8. 策略对比结论继续保守

保持：

- `0.0` 收益作为有效数值。
- 无成交 `0%` 不表达成策略验证成功。
- `best_strategy_id` 和 `best_verifiable_strategy_id` 分开。

继续调整：

- 前端表格默认突出买入数、缺快照、收盘代理、质量状态。
- 策略对比结果可选落只读审计表，便于复盘，不污染正式回测列表。

### A9. 严格拒单原因标准化

统一原因：

```text
missing_1430_snapshot        缺执行日 14:30 快照
tail_entry_not_triggered     有快照，但尾盘/MA5 条件未触发
limit_up_tail_unfilled       涨停买不到
limit_down_tail_blocked      跌停卖不出
position_slot_unavailable    仓位满
insufficient_cash            现金不足
```

要求：

- 后端报告、候选追踪、个股诊断使用同一字典。
- 前端不直接展示英文 code。
- 缺数据和策略条件未触发必须分开显示。

### A10. `vn.py` 状态文案清晰化

把“部分就绪”改成可理解状态：

```text
vn.py core：可用
本地数据库桥：可用/空库
A 股 Gateway：未安装/未配置
Datafeed：未配置
严格分钟补数来源：按 AkShare/TDX/Tushare/vn.py 本地库逐项显示
```

相关文件：

- `alphaagent/server/services/vnpy_integration/status.py`
- `frontend/src/features/quant/VnpyStatusPanel.tsx`
- `frontend/src/features/quant/QuantWorkflowGuide.tsx`

### A11. 文档和 memory 同步当前真实状态

必须保持：

- `memory/02_source/core_entrypoints.md` 默认执行口径是 `strict_1430`。
- `memory/03_data/data_flow.md` 明确 `sync_stock_minute_bars mode=backtest_gaps` 是主补数入口。
- `memory/09_decisions/decisions.md` 把尾盘混合标注为历史/研究对比，不再是默认。
- `docs/alphaagent/quant_flow.md` 保持默认 `strict_1430`，并继续附中文注释式流程。

---

## 4. 需要新增

### N1. 逐日候选到成交复盘表

目标：

```text
每个交易日：
  BUY候选数 / WATCH候选数
  进入计划数
  实际下单数
  成交数
  拒单数及原因
  当日买入后现金、持仓市值、总权益
```

后端建议：

- 新增 `GET /api/backtests/{id}/daily-decision-summary`。
- 或扩展 `GET /api/backtests/{id}/days/{trade_date}`，并让它返回列表化的每日摘要。

前端建议：

- 放在 `BacktestDrilldownPanel` 日期区块。
- 后续拆为 `BacktestDailyDecisionSummary.tsx`。

### N2. 回测亏损归因面板

目标：

```text
每笔已完成交易：
  买入前候选分数和排名
  买入执行价和价格来源
  持仓内最大浮盈、最大浮亏
  卖出触发规则
  卖出是否失败
  对总收益的贡献
```

原因：

- 当前 `#62` 买入 21/21 都是真实 14:30，负收益不能继续只归因于缺分钟线。
- 需要拆出是选股问题、买点问题、卖点问题、止损止盈问题、仓位竞争问题还是市场环境问题。

### N3. 数据质量按 provider 的缺口建议

目标：

- 每个缺口按 AkShare/TDX/Tushare/vn.py 本地库给出下一步。
- 区分“数据源取不到”和“还没同步”。
- 显示 dry-run 预检查结果和导入后复审结果。
- 对 TDX 重复补前 N 个缺口的问题，支持“只补仍缺失项”的 payload 或后端自动过滤。

### N4. 反未来函数和反过拟合报告升级

新增检查：

- 财报必须 `publish_date <= trade_date`。
- 候选只用 `trade_date` 及以前数据。
- 买入/卖出只使用 `signal_date` 之后的执行日价格。
- 费用、滑点、印花税、100 股整数手进入账本。
- 多年全 A。
- walk-forward。
- 参数敏感性。
- 分市场状态。
- 基准超额。
- 随机样本对照。

### N5. 策略研究实验记录

新增只读研究记录，不污染正式回测列表：

```text
strategy_research_runs
strategy_research_variants
strategy_research_metrics
```

用途：

- 保存策略对比、参数网格、walk-forward 结果。
- 记录执行模型、数据质量、样本覆盖。
- 避免每次都靠内存或临时 CSV 回忆。

### N6. 远期新增 `intraday_1430_signal`

暂不做，直到历史 1m 覆盖足够。

目标模型：

```text
使用 T 日 14:30 及以前 1m 数据聚合出截至 14:30 的临时 OHLCV
-> 替代完整 T 日日线参与评分
-> T 日 14:30 生成信号
-> T 日 14:30 按同一快照成交
```

限制：

- 它是新信号/执行模型，不是当前日线回测开关。
- 禁止使用 T 日收盘价、T 日全日成交量、收盘后资金流等未来信息。

---

## 5. 推荐执行顺序

### Phase 0: 锁住主路径和清理误导残留

状态：基本完成，但需要持续回归。

1. 保持 `normalize_execution_model(None)` 默认 `strict_1430`。
2. 普通前端禁止暴露 `tail_close_hybrid` 和 `legacy_next_open`。
3. 普通新建组合回测只传 `strict_1430 / 1m / 14:30 / strict_entry=true`。
4. memory 和文档默认执行口径保持 `strict_1430`。
5. 真实浏览器确认 `/quant`、`/data`、`/stocks/002636.SZSE` 无 5m/10m 严格入口、无普通尾盘混合入口。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "execution_model or minute_interval or strict_1430" -q
pnpm --dir frontend run build
```

### Phase 1: 候选与日期核查

状态：第一版完成，继续增强。

1. 候选覆盖面板继续从交易日起点到本地最新交易日分页展示。
2. 支持点击某天查看当天候选。
3. 显示每个交易日 BUY/WATCH 数量和是否已运行。
4. 明确最后同步到“量化候选”分组的日期。
5. 补“查看交易日只切换，不重新筛选”的文案。

验收：

```bash
pnpm --dir frontend run build
```

真实浏览器：

```text
/quant -> 候选
  生成区间候选
  查看不同交易日
  BUY/WATCH 数量变化
```

### Phase 2: 回测逐日复盘和亏损归因

优先级：P1。

1. 新增逐日候选到成交复盘 API。
2. 前端日期钻取显示候选、计划、下单、成交、拒单、现金、持仓市值、总权益。
3. 新增交易亏损归因面板。
4. 用 `#62` 验证负收益来源，而不是继续只补分钟线。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "daily_decision or attribution or drilldown" -q
pnpm --dir frontend run build
```

### Phase 3: 个股诊断和金安国纪复核

优先级：P1。

1. 股票详情显示各策略 BUY/WATCH 次数和最佳 BUY 日期。
2. 指定组合回测 ID 后显示该股在组合里的真实买/没买原因。
3. 显示财报历史可见性。
4. 对金安国纪只走标准诊断，不写特例。
5. 对 `#70` 这类“理论信号恢复但缺分钟快照”的情况，用数据质量提示清楚解释，不能当完整严格基线。

验收：

```bash
curl -s "http://127.0.0.1:8000/api/quant/symbols/002636.SZSE/strategy-comparison?start=2025-10-14&end=2026-06-13"
curl -s "http://127.0.0.1:8000/api/quant/symbols/002636.SZSE/diagnostics?start=2026-02-02&end=2026-06-13&backtest_id=70&signal_date=2026-02-09&limit=5"
```

### Phase 4: 等价拆大文件

优先级：P1。

顺序：

1. `backtest/engine.py`
2. `data_sync.py`
3. `frontend/src/api/quant.ts`
4. `StockDetailPage.tsx`
5. `DataManagementPage.tsx`
6. `BacktestDrilldownPanel.tsx`
7. `tests/alphaagent/test_quant_backtest_portfolio.py`

每一步只做等价移动和导出兼容，不改行为。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services alphaagent/server/api
pnpm --dir frontend run build
```

### Phase 5: 策略稳健性验证

优先级：P2。

1. 多区间全 A 回测。
2. walk-forward。
3. 参数敏感性。
4. 样本等权和指数基准超额。
5. 随机样本对照。
6. 高摩擦成本压力测试。

完成前不宣称策略稳定盈利。

---

## 6. 验证矩阵

后端：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest alphaagent/server/services/data_providers alphaagent/server/api
```

前端：

```bash
pnpm --dir frontend run build
```

Docker/API：

```bash
docker compose up -d --build alphaagent-api alphaagent-web
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/quant/strategies
curl -s http://127.0.0.1:8000/api/backtests/62/minute-coverage
curl -s http://127.0.0.1:8000/api/backtests/62/data-quality
curl -s "http://127.0.0.1:8000/api/quant/symbols/002636.SZSE/diagnostics?start=2026-02-02&end=2026-06-13&backtest_id=70&signal_date=2026-02-09&limit=5"
```

真实浏览器：

```text
/quant
  候选页：交易日选择、策略选择、BUY/WATCH、候选追踪、候选覆盖。
  回测页：严格 14:30 默认、真实性结论、成交分页、日期/股票钻取、策略对比。
  数据页：回测 ID 审计、provider 预检查、严格流水线、高级 CSV 兜底。

/data
  sync_stock_minute_bars mode=backtest_gaps。
  普通入口固定 1m / 14:30。
  recent 模式明确为行情同步。

/stocks/002636.SZSE
  策略历史 BUY 次数。
  指定组合回测下的买/没买原因。
  财报历史可见性。
```

---

## 7. 当前最高优先级

1. `P1` 做逐日候选到成交复盘表，解决“点日期看当天买卖和资金”的核查问题。
2. `P1` 做亏损归因面板，解决 `#62` 数据真实但负收益时无法判断问题来源的问题。
3. `P1` 继续金安国纪标准诊断，把 `#62` 和 `#70` 的差异用数据质量解释清楚。
4. `P1` 等价拆大文件，先后端核心，再前端页面。
5. `P1` 保持普通入口清理：无 `5m/10m` 严格入口、无普通尾盘混合入口、CSV 只作高级兜底。
6. `P2` 多年全 A、walk-forward、参数敏感性、基准超额和随机样本对照。
