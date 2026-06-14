# AlphaAgent Quant Refactor And Feature Roadmap Implementation Plan

> Superseded: 本计划已被 `docs/plans/2026-06-14-quant-cleanup-master-plan.md` 取代。后续执行以 master plan 为准，本文件仅保留历史上下文。

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把当前量化候选、策略、组合回测、14:30 分钟补数、个股诊断和回测报告整理成口径一致、可核查、可继续扩展策略的研究工作台。

**Architecture:** 不修改继承的 `vnpy/` 核心；量化业务继续集中在 `alphaagent/`、`frontend/src/`、`tests/`、`docs/`、`memory/`。严格真实性主流程固定为“D 日收盘可见信号 -> D+1 14:30 执行”，量化执行只使用 `1m / 14:30` 快照；股票详情看盘和通用分钟 K 线导入可以保留多周期，但必须和严格回测执行口径隔离。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、React、TanStack Query、TypeScript、pytest、Playwright、Docker Compose。

---

## 0. 当前源码事实

### 0.1 量化执行周期

当前严格量化主流程已经收敛到 `1m / 14:30`：

- `alphaagent/server/services/backtest/execution_models.py`
  - `SUPPORTED_BACKTEST_MINUTE_INTERVALS = {"1m"}`。
  - `SUPPORTED_EXECUTION_MODELS = {"tail_close_hybrid", "strict_1430", "legacy_next_open"}`。
- `alphaagent/server/services/backtest/engine.py`
  - `BacktestParams.minute_interval = "1m"`。
  - `BacktestParams.tail_entry_start = "14:30"`。
  - `BacktestParams.tail_entry_end = "14:30"`。
  - `BacktestParams(execution_model="strict_1430")` 会强制 `minute_entry_required=True`。
- `frontend/src/features/quant/constants.ts`
  - `MinuteInterval = "1m"`。
  - 普通回测参数默认 `minute_interval="1m"`、`tail_entry_start="14:30"`、`tail_entry_end="14:30"`。
- `frontend/src/features/quant/BacktestParamsForm.tsx`
  - 普通 UI 只显示“1分钟 / 14:30快照”，不再提供 5m/10m 选择。
- `tests/alphaagent/test_quant_backtest_portfolio.py`
  - 已有测试拒绝 `BacktestParams(minute_interval="5m")`。
  - 已有测试拒绝通用分钟导入的 `10m`。

当前仍保留的多周期能力不是严格回测入口：

- `frontend/src/features/stocks/StockKlineChart.tsx`
  - 股票详情看盘周期仍有 `5m/15m/30m/60m/1d/1w/1mo`。
- `alphaagent/data_sources/akshare_adapter.py`
  - 行情查询支持 `1m/5m/15m/30m/60m`。
- `alphaagent/server/services/data_sync.py`
  - 标准分钟线 CSV/文件导入支持 `1m/5m/15m/30m/60m`。
  - `sync_stock_minute_bars mode=backtest_gaps` 会固定使用 `1m`。
- `frontend/src/pages/DataManagementPage.tsx`
  - 当前数据同步页面实际也只展示 `1分钟`，并没有把 `5m/15m/30m/60m` 暴露为通用同步选项。

结论：

- `10m` 应删除为功能入口，只保留拒绝测试和历史说明。
- `5m/15m/30m/60m` 可以保留为股票详情看盘/外部数据导入能力，但不要进入严格 14:30 回测主流程。
- 数据管理页是否重新开放 `5m/15m/30m/60m` 需要单独作为“通用看盘数据同步”设计，不应混在严格补数任务里。

### 0.2 当前量化策略

已注册策略在 `alphaagent/server/services/quant/strategy_registry.py`：

```text
mainline_leader_pullback / 0.1.1
主线强势回踩低吸
硬买入：total_score >= 68，MA5 距离 [-1.5%, 2.0%]，risk_score >= 35，liquidity_score >= 25

breakout_confirmation / 0.1.0
平台放量突破确认
硬买入：total_score >= 70，距 60 日高点 >= -1.0%，量能比 >= 1.10，trend_quality >= 60，risk_score >= 35，liquidity_score >= 25
```

当前策略实现仍在 `alphaagent/server/services/quant/factors.py`：

- `score_stock()`：低吸策略。
- `score_breakout_confirmation()`：突破策略。
- 同文件还包含公共指标函数、`Bar`、`SignalScore`。

BUY/WATCH 规则：

- `screening._recommendation_to_db()` 中 `entry_signal=True` 才写为 `BUY`，否则为 `WATCH`。
- `engine._is_buy_candidate()` 默认 `strict_entry=True`，只买 `entry_signal=True` 的 BUY。
- `strict_entry=False` 会允许分数达标但没有硬买点的 WATCH 进入研究回测，只能作为高级宽松研究模式。

### 0.3 当前组合回测流程

当前组合回测不是用“今天候选”套历史，而是逐日动态重算：

```text
每个交易日 D 收盘后，只使用 D 日及以前可见数据评分
-> 生成 D+1 的买入/卖出计划
-> D+1 按执行模型撮合
-> 更新现金、持仓、市值、总权益
-> 写入订单、成交、权益曲线、逐股持仓快照、理论信号计划
```

执行模型：

```text
tail_close_hybrid
  有 D+1 14:30 的 1m 快照：用 minute_1430 成交。
  缺 D+1 14:30 快照：用 D+1 日线 close 代理尾盘成交，并标记 daily_close_proxy。

strict_1430
  只允许 D+1 14:30 的 1m 快照成交。
  缺快照、涨停买不到、跌停卖不出、尾盘条件未触发时拒单。

legacy_next_open
  旧报告兼容模型；普通 UI 不暴露。
```

当前金额账本已抽到 `alphaagent/server/services/backtest/ledger.py`：

- 买入滑点。
- 卖出滑点。
- 佣金。
- 印花税。
- 100 股整数手。
- 现金不足时降档。

当前理论信号和真实订单关联已抽到 `alphaagent/server/services/backtest/signal_plan.py`：

- `link_signal_events_to_orders()`。
- `plan_status`。
- 中文状态标签。
- 候选追踪诊断。

### 0.4 当前页面可核查能力

已有基础能力：

- `/quant` 候选页：
  - 可选择策略。
  - 可按交易日查看候选。
  - 可生成从起始交易日到最新交易日的区间候选。
- `/quant` 回测页：
  - 可运行组合回测。
  - 可看真实性结论。
  - 可看 14:30 覆盖。
  - 可分页看全部成交。
  - 可看日期/股票钻取。
  - 可看全股票理论信号计划和金额预览。
- `/quant` 数据页：
  - 可按回测 ID 审计 14:30 缺口。
  - 可选 AkShare/TDX/Tushare/vn.py 补缺口。
  - CSV 入口已放在高级区域。
- `/stocks/:vtSymbol`：
  - 股票详情看盘可用多周期。
  - 量化信号复核可对比低吸/突破。
  - 可输入组合回测 ID 和信号日追踪为什么买/没买。

仍存在的核查缺口：

- `BacktestDrilldownPanel` 的日期选项主要来自 `equity_tail` 和近期成交，不是完整回测日期。
- `BacktestDrilldownPanel` 的股票选项主要来自近期成交和个股贡献，不适合核查“曾经有信号但没买”的股票。
- 拒单原因在部分表格里仍显示英文 raw reason。
- `backtest_signal_events` 仍有一些重要字段放在 `raw` 中，查询和展示依赖推断。
- `engine.py`、`data_sync.py`、`MinuteDataWizard.tsx` 文件过大，继续改功能会增加误伤概率。

## 1. 需要删除

### D1. 删除所有普通入口中的 10m

状态：代码层基本完成，继续保持。

删除/禁止：

- `/quant` 严格回测周期选项中的 `10m`。
- `/data` 严格缺口补数周期选项中的 `10m`。
- 后端严格回测参数中的 `10m`。
- 文档中把 `10m` 描述为可替代 14:30 快照的文字。

保留：

- `tests/alphaagent/test_quant_backtest_portfolio.py::test_import_stock_minute_bars_rejects_obsolete_10m_interval`。
- 历史报告或 memory 中对旧探索结果的说明。

验收：

```bash
rg -n "10m|10分钟" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx frontend/src/pages/DataManagementPage.tsx alphaagent/server/services/backtest alphaagent/server/api/backtests.py docs/alphaagent -S --glob '!**/*.tsbuildinfo'
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "10m or minute_interval" -q
```

预期：

- 只允许命中拒绝测试、历史说明和非产品入口兼容代码。

### D2. 删除普通量化入口中的 5m 严格回测暗示

状态：普通 UI 已完成，继续防回归。

删除/禁止：

- `/quant` 普通回测表单中的 `5m`。
- 严格补数向导中“5m 可减少数据量并替代 14:30”的暗示。
- `BacktestParams` 接受 `5m`。

保留：

- 股票详情看盘 `5m`。
- `AkShareAdapter.stock_bars(..., interval="5m")` 作为行情查看。
- 标准分钟线 CSV/文件导入的 `5m`，前提是只作为通用分钟 K 线导入，不参与严格回测。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_backtest_params_rejects_non_1m_minute_interval -q
pnpm --dir frontend run build
```

### D3. 删除普通路径的 CSV-first 补数体验

状态：页面已把 CSV 放入高级区域，但后端 API 仍需保留。

删除/隐藏：

- 用户第一屏先上传缺口 CSV 的操作方式。
- 把供应商 CSV 清单当成推荐主流程的文案。

保留：

- `/api/data-sync/imports/minute-bars` 标准 CSV 导入。
- `/api/data-sync/imports/minute-bars/vendor-manifest(.csv)` 供应商清单。
- `memory/06_backtests/` 里的历史证据 CSV。

普通补数路径固定为：

```text
回测 ID
-> 审计 14:30 缺口
-> 选择 provider
-> 预检查
-> 写入
-> 复审覆盖
-> 运行 strict_1430
```

### D4. 删除旧绩效结论引用

不删除旧报告文件，但删除“旧口径绩效可证明策略有效”的表达。

处理规则：

- `strategy_version < 0.1.1` 绩效只作为历史排查材料。
- 卖出时序修复前的报告只标“需重跑”。
- 当前低吸严格结论以 `#62` 为准。
- `tail_close_hybrid` 中若有大量 `daily_close_proxy`，不能称为真实 14:30 回测。

### D5. 删除普通 UI 对 `partial` 的直译

状态：量化页 vn.py 文案已修过；数据管理页仍有通用 `partial -> 能力受限` 映射，可以保留。

删除/禁止：

- 直接显示“部分就绪”。

保留：

- API 内部 `status="partial"`。
- 页面中文翻译为可行动状态：
  - 本地研究可用。
  - A 股 Datafeed 待配置。
  - A 股 Gateway 待配置。
  - vn.py 本地库是否有分钟数据。

## 2. 需要重构

### R1. 拆 `alphaagent/server/services/backtest/engine.py`

当前约 4259 行，仍混有：

- `run_backtest()` 主循环。
- 报告构建。
- CSV 导出。
- 读取回测详情。
- 日期/股票钻取。
- 理论信号查询。
- 持久化写表。
- 旧模型兼容。

已经拆出的模块：

- `execution_models.py`
- `ledger.py`
- `signal_plan.py`

下一步拆分顺序：

1. `reports.py`
   - 移动执行质量统计。
   - 移动真实性结论。
   - 移动反未来函数审计。
   - 移动 CSV 报告构建。
   - 保留 `engine.py` 兼容 wrapper，避免测试和 API 大面积改动。
2. `queries.py` 或 `persistence.py`
   - 移动 `backtest_report()` 的数据库读取部分。
   - 移动 `backtest_trades()`、`backtest_equity()`。
   - 移动 `backtest_day_detail()`、`backtest_symbol_detail()`。
   - 移动 `backtest_candidate_trace()` 查询部分。
3. `storage.py`
   - 移动 `_persist_run()`。
   - 移动 `backtest_runs/backtest_orders/backtest_trades/backtest_daily_equity/backtest_daily_positions/backtest_signal_events` 写表。
4. `simulation.py`
   - 移动主循环和状态机。
   - `engine.py` 最终只保留 `BacktestParams`、`run_backtest()` 编排和兼容导出。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "report or execution_quality or csv or minute_coverage" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

### R2. 结构化 `backtest_signal_events`

当前 `backtest_signal_events` 已解决“全股票理论信号计划”，但仍有不少信息放在 `raw`。

需要结构化字段：

```text
signal_date
planned_execute_date
actual_trade_date
planned_action
plan_status
linked_order_id
linked_order_status
linked_order_reason
execution_model
execution_mode
price_source
proxy_used
cash_after
position_market_value
total_equity
raw
```

收益：

- 候选追踪不用再靠 raw 推断。
- 股票详情能直接回答“有买点为什么没买”。
- 后续组合级策略对比能直接统计真实成交、拒单、代理成交。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "signal_events or candidate_trace or amount_preview" -q
```

### R3. 拆 `alphaagent/server/services/data_sync.py`

当前约 4521 行，职责过多：

- 同步任务 registry。
- 批次运行。
- 本地行情 fallback。
- 日线同步。
- 分钟线 recent 同步。
- 严格缺口解析。
- 严格缺口审计。
- CSV 导入。
- provider 缺口导入。
- 供应商清单。

目标拆分：

```text
alphaagent/server/services/data_sync.py
  只保留 JobDefinition、runner registry、批次编排。

alphaagent/server/services/minute_gaps.py
  backtest_id -> gap requirements。
  CSV/file -> gap requirements。
  覆盖审计。
  供应商清单。

alphaagent/server/services/minute_imports.py
  标准分钟线 CSV/文件导入。
  文件路径白名单。
  streaming import。
  upsert minute bars。

alphaagent/server/services/minute_provider_imports.py
  AkShare/TDX/Tushare/vn.py provider 统一包装。
  dry-run 和正式写入后的复审。
```

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_gap or minute_bars or akshare or tdx or tushare or vnpy" -q
uv run python -m compileall alphaagent/server/services alphaagent/server/api/data_sync.py
```

### R4. 拆 `frontend/src/features/quant/MinuteDataWizard.tsx`

当前约 804 行，状态和 UI 过密。

目标拆分：

```text
MinuteDataWizard.tsx
  只保留状态组合和主流程布局。

MinuteGapSourceForm.tsx
  回测 ID / 高级缺口 CSV / 文件路径。

MinuteProviderImportPanel.tsx
  AkShare/TDX/Tushare/vn.py provider 预检查和导入。

MinuteCsvFallbackPanel.tsx
  外部分钟线 CSV 高级兜底。

VnpyMinuteImportPanel.tsx
  vn.py 本地库单标的和按缺口导入。

StrictBacktestRunner.tsx
  审计通过后运行 strict_1430。
```

验收：

```bash
pnpm --dir frontend run build
```

真实浏览器：

```text
/quant -> 数据页
  第一屏仍是回测 ID、数据源、审计、预检查、补齐、严格回测。
  CSV 只在高级区域。
```

### R5. 拆 `alphaagent/server/services/quant/factors.py`

当前 `factors.py` 既包含策略又包含公共指标。

目标：

```text
alphaagent/server/services/quant/factors.py
  Bar、SignalScore、公共指标函数。

alphaagent/server/services/quant/strategies/pullback.py
  mainline_leader_pullback。

alphaagent/server/services/quant/strategies/breakout.py
  breakout_confirmation。

alphaagent/server/services/quant/strategy_registry.py
  策略注册、元数据、dispatch。
```

原则：

- 先等价移动，不改阈值。
- 新策略前必须完成这步，否则策略逻辑会继续堆在一个文件里。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy or breakout or pullback or failed_rules" -q
```

### R6. 拆测试文件

当前 `tests/alphaagent/test_quant_backtest_portfolio.py` 约 4775 行，已经成为集成测试合集。

建议拆分：

```text
tests/alphaagent/backtest/test_execution_models.py
tests/alphaagent/backtest/test_ledger.py
tests/alphaagent/backtest/test_reports.py
tests/alphaagent/backtest/test_signal_plan.py
tests/alphaagent/backtest/test_backtest_queries.py
tests/alphaagent/data_sync/test_minute_gaps.py
tests/alphaagent/quant/test_strategy_registry.py
```

执行方式：

- 先搬测试，不改断言。
- 每搬一个文件就跑对应 `pytest`。
- 最后保留原文件中的跨模块集成用例。

## 3. 需要调整

### A1. 回测日期/股票钻取改为全量可选

当前问题：

- 日期选择只从 `equity_tail` 和近期成交推导。
- 股票选择只从近期成交和个股贡献推导。
- 无法方便核查“某天没成交但有拒单/持仓变化”。

调整：

- `BacktestDrilldownPanel` 日期选项改用 `/api/backtests/{id}/equity` 的全部日期。
- 股票选项新增后端接口或复用信号事件，覆盖：
  - 有真实成交的股票。
  - 有订单/拒单的股票。
  - 有理论信号但没下单的股票。
  - 有持仓快照的股票。
- 日期钻取顶部增加：
  - 当日买入数。
  - 当日卖出数。
  - 当日拒单数。
  - 当日理论信号数。
- 股票钻取顶部增加：
  - 是否曾 BUY。
  - 是否实际买入。
  - 首次买入日。
  - 最终卖出日。
  - 没买主因。

验收：

```bash
pnpm --dir frontend run build
```

真实浏览器：

```text
/quant -> 回测 -> 交易归因
  日期下拉可覆盖整个回测区间。
  股票下拉可查有理论信号但没成交的股票。
```

### A2. 拒单原因全部中文化

当前部分表格仍显示 raw reason，例如：

- `tail_entry_not_triggered`
- `tail_exit_not_triggered`
- `limit_up_tail_unfilled`
- `limit_down_tail_blocked`
- `insufficient_cash`

调整：

- 后端提供 `reason_label`。
- 前端 `backtest-utils.ts` 兜底翻译。
- 订单表、信号计划、候选追踪、股票详情统一使用中文。

### A3. 研究回测和严格真实性回测视觉上分开

当前普通按钮默认跑 `tail_close_hybrid`，这个可以保留为快速研究，但要持续强调：

- `tail_close_hybrid` 可能包含 `daily_close_proxy`。
- `strict_1430` 才是当前严格真实性口径。
- 混合回测收益不能直接当成真实 14:30 收益。

调整：

- 回测列表 option 显示执行模型、策略和 14:30 覆盖状态。
- 回测结果第一屏固定展示：
  - 执行模型。
  - 买入数。
  - 真实 14:30 买入数。
  - 收盘代理数。
  - 缺快照拒单数。
  - 尾盘条件未触发拒单数。
- 严格回测按钮放在数据补齐闭环后，不和普通研究回测混在同一个按钮语义里。

### A4. BUY/WATCH 解释统一

规则固定：

```text
BUY：默认组合回测会尝试买。
WATCH：默认组合回测不买。
宽松研究：用户显式开启 strict_entry=false 后，分数达标 WATCH 才可能参与回测。
```

调整范围：

- 候选表。
- 回测参数高级区。
- 信号计划。
- 候选追踪。
- 股票详情量化复核。
- 文档 `docs/alphaagent/quant_flow.md`。

### A5. 金安国纪复核做成标准个股诊断

不要给 `002636.SZSE` 写特殊策略。

标准个股诊断要支持任意股票：

- 多策略 BUY/WATCH 历史摘要。
- 最接近买点日期。
- 失败规则。
- 财报可见性。
- 指定回测 ID 下：
  - 是否入选候选。
  - 是否只是 WATCH。
  - 是否进入理论计划。
  - 计划执行日。
  - 是否下真实订单。
  - 是否成交。
  - 没买/拒单原因。
  - 执行日现金、持仓市值、总权益。
  - 后续持仓路径。

### A6. 数据管理页区分严格补数和通用分钟同步

当前数据管理页 `sync_stock_minute_bars` 只露出 `1m`。

调整：

- 严格缺口模式：
  - 固定 `1m / 14:30`。
  - 不允许 5m/15m/30m/60m。
- 最近分钟线模式：
  - 可以继续只保留 `1m`，保持简单。
  - 如果要恢复 `5m/15m/30m/60m`，必须标为“看盘数据同步”，不能进入严格回测补数。

建议当前先不恢复多周期同步选项，避免用户再次把它理解为量化执行周期。

## 4. 需要新增

### N1. 组合级策略对比

当前已有个股级：

- `GET /api/quant/symbols/{vt_symbol}/strategy-comparison`

需要新增组合级：

```text
POST /api/backtests/strategy-comparison
```

输入：

```json
{
  "strategies": ["mainline_leader_pullback", "breakout_confirmation"],
  "start": "2025-10-14",
  "end": "2026-06-13",
  "execution_model": "strict_1430",
  "max_symbols": 80,
  "included_boards": ["main"]
}
```

输出：

- 策略。
- BUY 次数。
- WATCH 次数。
- 理论买入数。
- 真实成交数。
- 拒单数。
- 收益。
- 最大回撤。
- 14:30 真实占比。
- 收盘代理占比。
- 基准超额。
- 随机样本对比。

用途：

- 判断低吸、突破、新增策略谁更值得继续研究。
- 避免只看单只股票或单次回测做结论。

### N2. 策略：涨停后回踩

建议 ID：

```text
limit_up_after_pullback
```

目标：

- 覆盖涨停后回踩确认的买点。
- 不硬改低吸策略。

第一版日线条件：

- 过去 20 个交易日内有涨停或接近涨停。
- 涨停后没有跌破关键均线。
- 回踩 MA5/MA10 或缩量整理。
- 板块强度不弱。
- 当天不是一字涨停不可买。
- 过滤连续过热、流动性不足、风险分过低。

验收：

- 有独立 `failed_rule_labels`。
- 有独立 `primary_metric_keys`。
- 能在金安国纪等股票详情中展示 BUY/WATCH。
- 必须用 `strict_1430` 重跑，不能只看日线代理结果。

### N3. 策略：强势加速

建议 ID：

```text
trend_acceleration
```

目标：

- 覆盖突破后继续加速的趋势段。
- 与 `breakout_confirmation` 区分，不做阈值略变的重复策略。

第一版日线条件：

- 20/60 日强度显著。
- 站上 MA5/MA10/MA20。
- 放量但不过度爆量。
- 回撤控制可接受。
- 涨停不可买和高开追涨风险单独标注。

风险：

- 追高策略天然回撤可能更大。
- 必须做高摩擦、涨跌停阻断、随机样本和 walk-forward。

### N4. 盘中 14:30 信号模型

建议 ID：

```text
intraday_1430_signal
```

暂缓，不进入当前第一阶段。

目标模型：

```text
用 T 日 14:30 及以前 1m 数据聚合临时 OHLCV
-> 只用 14:30 前可见数据评分
-> T 日 14:30 生成信号
-> T 日 14:30 成交
```

要求：

- 不能用 T 日完整日线 close/high/volume。
- 不能用收盘后资金流、热榜、财报更新。
- 需要完整历史 1m 数据。
- 必须独立报告，不能混进 D close -> D+1 14:30。

### N5. 策略验证报告升级

新增固定检查：

- 数据可见日期审计。
- 财报 `publish_date <= trade_date`。
- D 日信号和 D+1 执行时序。
- 14:30 快照覆盖。
- 涨跌停无法成交。
- 费用、滑点、印花税、100 股整数手。
- 样本等权。
- 指数基准。
- 随机样本。
- 参数敏感性。
- walk-forward。
- 分市场环境。
- 高摩擦压力测试。

## 5. 推荐执行顺序

### Task 1: 锁定边界测试

**Files:**

- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 确认严格回测只接受 `1m`。
2. 确认 `10m` 被拒绝。
3. 确认默认 `strict_entry=True` 不买 WATCH。
4. 确认 `strict_entry=False` 是显式宽松研究。
5. 确认卖出仍是 D 日信号、D+1 执行。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_interval or 10m or watch or strict_entry or sell" -q
```

### Task 2: 修正回测钻取选择范围

**Files:**

- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `alphaagent/server/api/backtests.py`
- Modify: `frontend/src/features/quant/BacktestDrilldownPanel.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 后端新增或扩展回测可选日期/股票摘要接口。
2. 日期来源改为全量 equity 日期。
3. 股票来源覆盖成交、订单、信号、持仓。
4. 前端下拉改用完整选项。
5. 顶部增加买入/卖出/拒单/理论信号统计。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "day_detail or symbol_detail or trades or signal_events" -q
pnpm --dir frontend run build
```

### Task 3: 拆 `backtest/reports.py`

**Files:**

- Create: `alphaagent/server/services/backtest/reports.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 移动 `_execution_quality_report()`。
2. 移动 `_data_as_of_audit()`。
3. 移动 `_report_csv_content()`。
4. 移动报告相关指标函数。
5. 保留 `engine.py` 兼容导入。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "report or csv or execution_quality or data_as_of or minute_coverage" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

### Task 4: 拆分钟缺口服务

**Files:**

- Create: `alphaagent/server/services/minute_gaps.py`
- Create: `alphaagent/server/services/minute_imports.py`
- Create: `alphaagent/server/services/minute_provider_imports.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/api/data_sync.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 移动缺口 requirement 解析。
2. 移动 backtest_id -> gap requirements。
3. 移动覆盖审计。
4. 移动供应商清单。
5. 移动标准分钟线导入。
6. provider 统一返回结构。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_gap or minute_bars or akshare or tdx or tushare or vnpy" -q
```

### Task 5: 拆 `MinuteDataWizard`

**Files:**

- Create: `frontend/src/features/quant/MinuteGapSourceForm.tsx`
- Create: `frontend/src/features/quant/MinuteProviderImportPanel.tsx`
- Create: `frontend/src/features/quant/MinuteCsvFallbackPanel.tsx`
- Create: `frontend/src/features/quant/VnpyMinuteImportPanel.tsx`
- Create: `frontend/src/features/quant/StrictBacktestRunner.tsx`
- Modify: `frontend/src/features/quant/MinuteDataWizard.tsx`

**Steps:**

1. 抽回测 ID 和高级缺口来源。
2. 抽 provider 操作和结果卡片。
3. 抽 CSV 高级兜底。
4. 抽 vn.py 本地库导入。
5. 抽严格流水线运行。

**Run:**

```bash
pnpm --dir frontend run build
```

### Task 6: 拆策略文件

**Files:**

- Create: `alphaagent/server/services/quant/strategies/__init__.py`
- Create: `alphaagent/server/services/quant/strategies/pullback.py`
- Create: `alphaagent/server/services/quant/strategies/breakout.py`
- Modify: `alphaagent/server/services/quant/factors.py`
- Modify: `alphaagent/server/services/quant/strategy_registry.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 移动低吸策略，不改阈值。
2. 移动突破策略，不改阈值。
3. `factors.py` 只留公共指标。
4. registry 改为从策略模块导入。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy or breakout or pullback or failed_rules" -q
```

### Task 7: 个股诊断增强

**Files:**

- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 股票详情默认加载最新组合回测 ID。
2. 信号表的“追踪”展示更完整持仓路径。
3. 没买原因中文化并分类。
4. 金安国纪只作为验收样本，不写特殊规则。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "candidate_trace or symbol_signal or strategy_comparison" -q
pnpm --dir frontend run build
```

### Task 8: 组合级策略对比

**Files:**

- Modify: `alphaagent/server/api/backtests.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/quant/BacktestAnalysis.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 新增 `POST /api/backtests/strategy-comparison`。
2. 同一参数分别跑多个策略的非持久化对比。
3. 汇总收益、回撤、成交、拒单、14:30 覆盖、基准。
4. 前端展示策略对比表。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_comparison or execution_model_comparison" -q
pnpm --dir frontend run build
```

### Task 9: 新策略前基线复核

**Files:**

- Modify: `memory/06_backtests/`
- Modify: `memory/09_decisions/decisions.md`

**Steps:**

1. 用当前代码重跑低吸 `strict_1430`。
2. 用当前代码重跑突破 `strict_1430`。
3. 记录收益、回撤、成交、拒单、14:30 覆盖、基准和随机样本。
4. 若缺口未覆盖，不判断策略优劣。

### Task 10: 新增策略

**Files:**

- Create: `alphaagent/server/services/quant/strategies/limit_up_pullback.py`
- Create: `alphaagent/server/services/quant/strategies/trend_acceleration.py`
- Modify: `alphaagent/server/services/quant/strategy_registry.py`
- Modify: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Order:**

1. 先做 `limit_up_after_pullback`。
2. 严格 14:30 回测和个股对比。
3. 再做 `trend_acceleration`。
4. 每个策略都必须有独立失败规则、关键指标、BUY/WATCH 文案和真实性报告。

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

Docker：

```bash
docker compose up -d --build alphaagent-api alphaagent-web
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/api/quant/strategies
```

真实浏览器：

```text
/quant
  候选：策略选择、交易日候选、BUY/WATCH、候选追踪。
  回测：参数、真实性结论、14:30 覆盖、成交分页、日期/股票钻取、信号计划。
  数据：回测 ID 审计、provider 预检查、补齐、严格流水线。

/stocks/002636.SZSE
  低吸/突破历史 BUY。
  指定组合回测 ID 下的买/没买原因。
  财报口径。

/data
  sync_stock_minute_bars mode=backtest_gaps。
```

## 7. 当前优先级

第一优先级：

1. 回测钻取全量日期/股票，解决“想核查某天/某股但下拉不到”的问题。
2. 拆 `engine.py` 报告和查询，降低继续修金额、真实性和诊断的风险。
3. 拆分钟缺口服务和 `MinuteDataWizard`，保持回测 ID 优先，CSV 只做高级兜底。

第二优先级：

1. 拆策略文件。
2. 组合级策略对比。
3. 个股诊断增强。

暂缓：

1. 新增策略。
2. 盘中 14:30 信号模型。
3. 多年全 A walk-forward 大验证。

原因：

- 当前严格 14:30 链路已经能跑，但收益仍负。
- 现在最需要先把“怎么买、为什么没买、当天金额和持仓如何变化、数据缺在哪里”做成稳定可核查链路。
- 链路稳定后再加策略，才不会继续把策略问题、数据问题和页面解释问题混在一起。

## 8. 本次源码复核结论

本次只按当前产品代码复核，不把历史计划文档里的旧探索文字算作当前残留：

- `10m` 当前没有产品入口，只剩拒绝测试。它应继续作为“过期周期会被拒绝”的边界测试保留，不再删除更多代码。
- `5m/15m/30m/60m` 当前只在股票详情 K 线、AkShare 行情适配和通用分钟线导入能力里出现；普通组合回测、严格回测和严格缺口补数入口没有暴露这些周期。
- 严格量化主流程已经固定为 `1m / 14:30 / strict_1430`；默认研究回测仍可用 `tail_close_hybrid`，但必须持续标明它可能使用收盘代理。
- 当前策略只有两个正式注册策略：`mainline_leader_pullback` 和 `breakout_confirmation`。金安国纪能出现历史买点，但不能为单只股票写特殊规则。
- 当前最影响用户核查的是回测钻取：日期和股票下拉仍偏向报告尾部、近期成交和个股贡献，不能覆盖所有权益日期、理论信号、拒单和持仓快照。
- 当前最大维护风险是文件过大：`backtest/engine.py` 约 4259 行，`data_sync.py` 约 4521 行，`MinuteDataWizard.tsx` 约 804 行，测试文件约 4775 行。后续继续加策略或加数据源前必须拆分。

## 9. 最终执行路线

### P0: 先清理误导入口和核查缺口

状态：已完成第一版。

目标：先让用户能看懂当前量化到底怎么筛、怎么买、为什么没买。

删除：

- 删除普通 UI 和文档里任何“`5m/10m` 可替代严格 14:30 回测”的暗示。
- 删除普通入口对 `legacy_next_open` 的选择，不删除旧报告兼容代码。
- 删除或隐藏 CSV-first 补数路径；CSV 只保留在高级兜底和供应商文件导入。

调整：

- 回测钻取日期改成全量 `backtest_daily_equity` 日期。
- 回测钻取股票改成成交、订单、理论信号、持仓快照的合集。
- 订单、信号、候选追踪中的 raw reason 增加中文 `reason_label`。
- 交易日选择只用本地交易日，候选页继续保留“生成区间起点”和“查看交易日”两个不同语义的日期。

新增：

- `/api/backtests/{id}/drilldown-options`，返回全量日期摘要和股票摘要。
- 钻取页顶部统计：当日买入、卖出、拒单、理论信号、现金、持仓市值、总权益。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "day_detail or symbol_detail or trades or signal_events or reason" -q
pnpm --dir frontend run build
```

真实浏览器验收：

- `/quant -> 回测 -> 交易归因` 日期覆盖完整回测区间。
- 股票下拉能查到有理论信号但没成交的股票。
- 点击日期能看到当天买入、卖出、拒单、持仓和权益金额。

完成记录：

- 新增 `GET /api/backtests/{id}/drilldown-options`，日期来自 `backtest_daily_equity`，股票来自成交、订单、理论信号和持仓快照合集。
- `#62` 真实接口返回 `date_count=85`、`symbol_count=61`，日期覆盖 `2026-02-02` 到 `2026-06-12`。
- `BacktestDrilldownPanel` 已改用全量选项，旧报告推导只作为兜底。
- 订单、信号和候选追踪 API 行已增加 `reason_label` / `linked_order_reason_label`；页面显示“尾盘入场未触发”等中文原因。
- 真实浏览器验证 `/quant -> 回测 -> 交易归因` 无 failed requests；日期下拉 85 项，股票下拉 61 项；可选中 `000338.SZSE` 这类未成交但有拒单的股票并看到中文原因。
- 截图：`/tmp/alphaagent-quant-drilldown-options.png`、`/tmp/alphaagent-quant-drilldown-rejected-symbol.png`。

验证：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "day_detail or symbol_detail or trades or signal_events or candidate_trace or drilldown or reason_label" -q
# 13 passed, 125 deselected, 1 warning

pnpm --dir frontend run build
# 通过，仅 Vite chunk 体积警告

docker compose up -d --build alphaagent-api
curl http://127.0.0.1:8000/api/backtests/62/drilldown-options
# ready, date_count=85, symbol_count=61
```

### P1: 拆后端回测核心

状态：已完成第一小步。

目标：降低继续修金额、真实性、策略对比和个股诊断时的误伤概率。

重构：

- `backtest/reports.py`：执行质量、真实性结论、反未来函数审计、CSV 报告。
- `backtest/queries.py`：报告读取、成交分页、权益曲线、日期钻取、股票钻取、候选追踪查询。
- `backtest/storage.py`：`backtest_*` 表写入和 DTO 映射。
- `backtest/simulation.py`：主循环和状态机。

暂不改：

- 策略阈值。
- 手续费、滑点、印花税。
- `run_backtest(params)` 返回契约。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py
```

进度记录：

- 已新增 `alphaagent/server/services/backtest/queries.py`，承接回测钻取日期/股票聚合和原因中文翻译。
- `engine.py` 保留 `_backtest_drilldown_date_options()`、`_backtest_drilldown_symbol_options()`、`backtest_reason_label()` 兼容 wrapper，API 和前端契约不变。
- `backtest_trades()`、`backtest_equity()`、`backtest_day_detail()`、`backtest_symbol_detail()` 的数据库查询已迁到 `queries.py`，`engine.py` 继续保留同名 wrapper。
- 真实接口 `GET /api/backtests/62/drilldown-options` 仍返回 `date_count=85`、`symbol_count=61`。
- 浏览器回归 `/quant -> 回测 -> 交易归因` 可继续选中 `000338.SZSE` 并显示“有拒单 / 尾盘入场未触发”。
- 截图：`/tmp/alphaagent-quant-drilldown-after-queries.png`、`/tmp/alphaagent-quant-drilldown-after-read-query-move.png`。

验证：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "drilldown_options or reason_label or day_detail or symbol_detail or signal_events or candidate_trace" -q
# 10 passed, 128 deselected, 1 warning

uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "trades_api or day_detail or symbol_detail or backtest_equity or signal_events or drilldown_options or candidate_trace" -q
# 11 passed, 127 deselected, 1 warning

uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py
# 通过

pnpm --dir frontend run build
# 通过，仅 Vite chunk 体积警告
```

下一步：

- 继续迁移 `backtest_report()` 的数据库读取部分、`backtest_audit()`、`backtest_candidate_trace()` 和 CSV 构建相关读侧逻辑。

### P2: 拆分钟缺口和补数流程

目标：把“严格缺口补数”和“通用分钟线同步/看盘”彻底分开。

重构：

- `minute_gaps.py`：回测 ID、CSV、文件路径到缺口需求；覆盖审计；供应商清单。
- `minute_imports.py`：标准分钟线 CSV/文件导入。
- `minute_provider_imports.py`：AkShare/TDX/Tushare/vn.py provider 统一包装。
- `MinuteDataWizard.tsx` 拆成来源表单、provider 面板、CSV 高级兜底、vn.py 导入、严格流水线运行。

保留：

- 严格缺口补数只用 `1m / 14:30`。
- 股票详情和通用导入可以保留 `5m/15m/30m/60m`，但必须标为看盘/通用数据，不参与严格回测执行。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_gap or minute_bars or akshare or tdx or tushare or vnpy" -q
pnpm --dir frontend run build
```

### P3: 拆策略层，再新增策略

目标：先把低吸和突破从公共指标文件拆出来，再加新策略，避免继续堆阈值。

重构：

- `quant/factors.py` 只保留 `Bar`、`SignalScore` 和公共指标函数。
- `quant/strategies/pullback.py` 放 `mainline_leader_pullback`。
- `quant/strategies/breakout.py` 放 `breakout_confirmation`。
- `strategy_registry.py` 只负责元数据和 dispatch。

新增策略顺序：

1. `limit_up_after_pullback`：涨停后回踩。
2. `trend_acceleration`：强势趋势加速。
3. `intraday_1430_signal` 暂缓，等历史分钟数据完整后再做。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy or breakout or pullback or failed_rules" -q
```

### P4: 组合级策略对比和真实性报告升级

目标：不再靠单只股票或单次回测判断策略好坏。

新增：

- `POST /api/backtests/strategy-comparison`。
- 策略对比表：收益、最大回撤、BUY 数、WATCH 数、真实成交、拒单、14:30 覆盖、代理成交、基准超额、随机样本。
- 固定真实性检查：数据可见日期、财报披露日、D/D+1 时序、涨跌停、费用、100 股整数手、参数敏感性、walk-forward、高摩擦。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy_comparison or validation_grid or walk_forward" -q
pnpm --dir frontend run build
```

### P5: 个股诊断标准化

目标：金安国纪只是验收样本，能力要适用于任意股票。

调整/新增：

- 股票详情展示多策略 BUY/WATCH 历史摘要。
- 展示最接近买点日期、失败规则、财报可见性。
- 指定组合回测 ID 后，展示是否入选候选、是否 WATCH、是否进入理论计划、是否下单、是否成交、没买原因、执行日现金/持仓/总权益和后续持仓路径。

验收样本：

- `/stocks/002636.SZSE` 能看到低吸和突破历史买点。
- 若某个组合回测没有买入，页面能解释是 WATCH、排名/仓位竞争、现金不足、涨跌停、尾盘条件未触发，还是缺数据。

## 10. 不做或暂缓

- 不把 `5m/10m` 重新作为严格量化周期。
- 不为了金安国纪写单票特判。
- 不在数据不完整时宣称策略盈利或稳健。
- 不把 `tail_close_hybrid` 的结果当成纯真实 14:30 回测。
- 不在 `engine.py` 和 `data_sync.py` 继续堆大功能；新增功能前先拆职责。
