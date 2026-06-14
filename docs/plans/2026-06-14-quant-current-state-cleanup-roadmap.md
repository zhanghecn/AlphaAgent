# AlphaAgent Quant Current State Cleanup Implementation Plan

> Superseded: 本计划已被 `docs/plans/2026-06-14-quant-cleanup-master-plan.md` 取代。后续执行以 master plan 为准，本文件仅保留历史上下文。

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 AlphaAgent 当前量化候选、策略、组合回测、14:30 分钟补数、金安国纪复核和 vn.py 状态整理成口径一致、少误导、可审计、可真实浏览器验证的 A 股量化研究工作台。

**Architecture:** 不修改继承的 `vnpy/` 核心；量化业务只在 `alphaagent/`、`frontend/src/`、`tests/`、`docs/`、`memory/` 演进。严格量化主流程固定为“D 日收盘可见信号 -> D+1 执行”，执行价格只允许 `1m / 14:30` 快照或明确标记的收盘代理；股票详情看盘和通用分钟线同步可以保留多周期，但不能混入严格回测口径。

**Tech Stack:** FastAPI、SQLAlchemy、PostgreSQL、React、TanStack Query、TypeScript、pytest、Playwright、Docker Compose。

---

## 0. 当前源码状态

### 0.1 5 分钟 / 10 分钟残留边界

源码核查结论：

- 严格组合回测已经只支持 `1m`：
  - `frontend/src/features/quant/constants.ts` 中 `MinuteInterval = "1m"`。
  - `alphaagent/server/services/backtest/execution_models.py` 中 `SUPPORTED_BACKTEST_MINUTE_INTERVALS = {"1m"}`。
  - `alphaagent/server/services/data_sync.py` 中严格缺口审计会通过 `_strict_gap_interval()` 收敛到 `1m`。
- `10m` 当前不应作为任何产品入口；只允许保留在拒绝测试、旧报告说明和历史排查记录中。
- `5m/15m/30m/60m` 仍是通用分钟线能力，不应一刀切删除：
  - 股票详情 K 线看盘。
  - `sync_stock_minute_bars mode=recent` 最近分钟线同步。
  - 标准分钟线 CSV/文件导入。
- 产品边界必须写死：

```text
严格回测执行快照：只支持 1m / 14:30。
行情查看/通用同步导入：可支持 5m/15m/30m/60m。
10m：不作为功能入口，只保留拒绝测试和历史说明。
```

### 0.2 当前量化策略

已注册策略：

```text
mainline_leader_pullback / 0.1.1
主线强势回踩低吸。
硬买点：总分 >= 68，MA5 距离 [-1.5%, 2.0%]，风险分 >= 35，流动性 >= 25。

breakout_confirmation / 0.1.0
平台放量突破确认。
硬买点：总分 >= 70，距 60 日高点 >= -1.0%，量能比 >= 1.10，趋势质量 >= 60，风险分 >= 35，流动性 >= 25。
```

BUY/WATCH 规则：

- `BUY` 来自 `entry_signal=True`，默认组合回测才允许买。
- `WATCH` 是观察候选，默认组合回测不买。
- `strict_entry=false` 会允许分数达标但没有硬买点的 WATCH 参与回测；只能作为高级研究模式，不能作为默认真实口径。

### 0.3 当前组合回测流程

组合回测不是用“今天候选”套历史，而是逐日动态重算：

```text
D 日收盘后，只用 D 日及以前可见数据评分
-> 生成 D+1 买入/卖出计划
-> D+1 按执行模型撮合
-> 更新现金、持仓、市值、总权益
-> 下一交易日重复
```

当前执行模型：

```text
tail_close_hybrid
  有 D+1 14:30 的 1m 快照：用快照 close 成交。
  缺 D+1 14:30 快照：用 D+1 日线 close 代理尾盘成交，并在报告里标记 daily_close_proxy。

strict_1430
  只允许 D+1 14:30 的 1m 快照成交。
  缺快照、涨停买不到、跌停卖不出、尾盘条件未触发时拒单。

legacy_next_open
  旧报告兼容模型；普通 UI 不应暴露。
```

### 0.4 已完成的基础拆分

这些不要重复做，只需要继续补齐结构化和测试：

- `alphaagent/server/services/backtest/execution_models.py`
  - 已抽出执行模型、14:30 快照、收盘代理、涨跌停阻断和旧模型兼容。
- `alphaagent/server/services/backtest/ledger.py`
  - 已抽出买入/卖出滑点、佣金、印花税、100 股整数手、现金不足降档。
- `alphaagent/server/services/backtest/signal_plan.py`
  - 已抽出理论信号和真实订单关联、`plan_status`、中文状态标签、候选追踪诊断。
- `alphaagent/server/services/quant/financials.py`
  - 已统一财报可见性：股票详情和回测评分都按 `publish_date <= trade_date` 解释。
- 前端已把普通严格回测周期锁成 `1分钟 / 14:30快照`，vn.py 状态也不再直接显示“部分就绪”。

### 0.5 当前仍然明显过大的文件

这些是后续重构主目标：

```text
alphaagent/server/services/backtest/engine.py      约 4251 行
alphaagent/server/services/data_sync.py            约 4521 行
frontend/src/features/quant/MinuteDataWizard.tsx   约 804 行
frontend/src/pages/QuantTradingPage.tsx            约 402 行
```

### 0.6 当前真实性结论

当前严格结果以 `#62` 为准：

```text
策略：mainline_leader_pullback / 0.1.1
区间：2026-02-02 至 2026-06-13
执行：strict_1430 / 1m / 14:30
股票池：主板 max_symbols=80
期末权益：949,180.14
总收益：-5.0820%
最大回撤：-9.5778%
平仓交易：18
买入：21/21 都使用真实 14:30 快照
收盘代理：0
缺 14:30 快照拒单：0
剩余严格拒单：83，均为尾盘条件未触发
```

结论：

- 已成交买入可按真实 14:30 快照解读。
- `#60` 的 5 个缺快照已通过 TDX 写入 5 行补齐，并按同口径重跑得到 `#62`。
- `#62` 是当前同口径 `max_symbols=80` 的完整严格 14:30 回测；剩余 83 个拒单是策略尾盘条件未触发，不是缺数据。
- 收益仍为负；过拟合没有被证明解决，且未跑赢样本等权、主要指数、随机样本均值和高摩擦压力测试。
- 证据见 `memory/06_backtests/2026-06-14_backtest_62_strict_1430_recheck.md`。

## 1. 需要删除

### D1. 删除普通产品入口里的 5m/10m 严格回测暗示

状态：基础验收已完成。普通量化入口没有 `5m/10m` 严格回测入口；股票详情看盘仍保留 `5m/15m`，属于行情查看能力。

删除范围：

- `/quant` 普通回测表单中任何可选 `5m/10m` 的入口。
- 严格补数向导中任何“5m/10m 可以替代 14:30 快照”的文案。
- 文档中把 `5m/10m` 作为严格量化主流程选项的描述。

保留范围：

- `data_sync.py` 通用分钟线同步和导入的 `5m/15m/30m/60m`。
- 股票详情看盘用多周期分钟线。
- `10m` 拒绝测试。

验收：

```bash
rg -n "10m|10分钟" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx alphaagent/server/services/backtest alphaagent/server/api/backtests.py -S --glob '!**/*.tsbuildinfo'
rg -n "5m|5分钟" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx alphaagent/server/services/backtest alphaagent/server/api/backtests.py -S --glob '!**/*.tsbuildinfo'
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_interval or obsolete_10m or strict_minute" -q
```

### D2. 删除普通 UI 中旧执行模型入口

状态：基础验收已完成。普通量化入口只展示 `tail_close_hybrid` 和 `strict_1430`；`legacy_next_open` 仅保留为旧报告兼容说明。

删除或隐藏：

- `legacy_next_open` 选择入口。
- `intraday_entry`、`minute_entry_required`、`daily_next_open_fallback` 作为普通用户参数或默认解释。
- “今天候选回测全部历史”的任何暗示。

保留：

- 后端对旧报告和历史脚本的兼容解析。
- 报告中对旧模型的“旧口径，需重跑/仅供排查”标记。

验收：

```bash
rg -n "legacy_next_open|intraday_entry|minute_entry_required|daily_next_open_fallback" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx docs/alphaagent -S
pnpm --dir frontend run build
```

### D3. 删除普通路径的 CSV-first 补数体验

不是删除 CSV 能力，而是把 CSV 放到高级兜底。

普通补数路径必须是：

```text
回测 ID
-> 审计 14:30 缺口
-> 选择数据源 AkShare/TDX/Tushare/vn.py
-> 预检查
-> 导入
-> 覆盖审计
-> 重跑 strict_1430
```

高级兜底才显示：

- 缺口 CSV。
- 供应商清单 CSV。
- 外部分钟线 CSV。
- 服务器文件路径。

### D4. 删除旧绩效作为策略有效性的证据

处理规则：

- `strategy_version < 0.1.1` 的绩效只保留为历史排查。
- 卖出时序修复前的报告必须标为“旧口径，需重跑”。
- `memory/06_backtests/` 中旧报告不删除，但当前结论只引用修复后重跑结果。

### D5. 删除 stale 文案和重复字段

状态：基础验收已完成。vn.py 状态不再展示“部分就绪”，而是显示本地研究和 A 股 Datafeed/Gateway 的可行动状态。

清理范围：

- `_backtest_assumptions()` 中重复或过期 key。
- 报告和前端里把“D+1 开盘回退”描述成默认路径的文字。
- 前端对 `partial` 的直接展示；用户只应看到可行动状态：
  - 本地研究可用。
  - A 股 Datafeed 待配置。
  - A 股 Gateway 待配置。
  - vn.py 本地库分钟线是否有数据。

## 2. 需要重构

### R1. 继续拆 `backtest/engine.py`

已完成：

```text
execution_models.py  执行价、14:30、收盘代理、涨跌停、旧模型兼容。
ledger.py            现金、费用、滑点、印花税、100 股整数手。
signal_plan.py       理论信号、订单关联、候选追踪诊断。
```

下一步拆分：

```text
reports.py           指标、真实性结论、反未来函数、反过拟合、CSV 导出。
persistence.py       backtest_* 表写入、读取、详情查询。
simulation.py        _simulate 主循环和逐日状态机。
schemas.py           BacktestParams、Position、Trade、MinuteBar、ScoreContext 等数据结构。
engine.py            只保留 run_backtest 编排入口和少量兼容 wrapper。
```

执行原则：

- 每次只抽一个模块。
- `run_backtest(params)` 返回契约不变。
- 先补测试，再移动代码。
- 不顺手改策略阈值。

必测：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "cash or commission or stamp or slippage or lot" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "signal_events or candidate_trace or day_detail or symbol_detail" -q
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "execution_quality or minute_coverage or report or audit" -q
```

### R2. 信号计划继续结构化，减少依赖 raw 推断

当前已有：

- `backtest_signal_events`
- `/api/backtests/{id}/candidate-trace`
- `/api/backtests/{id}/days/{trade_date}`
- `/api/backtests/{id}/symbols/{vt_symbol}`
- `/api/backtests/{id}/trades?limit&offset&order`

下一步目标字段：

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
price_source
proxy_used
cash_after
position_market_value
total_equity
raw
```

验收：

- 点击某交易日能看到当天买入、卖出、拒单、现金、持仓市值、总权益。
- 点击某只股票能看到持仓路径、买入、卖出、拒单和没买原因。
- 候选追踪不再靠同日模糊关联。

### R3. 拆 `data_sync.py` 的分钟缺口和分钟导入

当前 `data_sync.py` 同时负责同步任务、缺口解析、CSV 导入、provider 导入、供应商清单等。

目标拆分：

```text
minute_gaps.py       backtest_id -> gap requirements、缺口解析、覆盖审计、供应商清单。
minute_imports.py    标准分钟 CSV/文件导入、通用 upsert、文件路径安全校验。
minute_provider.py   provider 返回结构、错误分类、导入后审计包装。
data_sync.py         同步任务 registry 和编排。
providers/*          AkShare/TDX/Tushare/vn.py provider adapter。
```

统一 provider 返回结构：

```text
status
provider
dry_run
interval
processed_gap_count
rows_read
rows_written
empty_request_count
wrong_date_row_count
missing_reason_counts
audit_after
next_action
```

缺口原因必须区分：

- 本地已有覆盖。
- 数据源拿不到。
- 非交易日。
- 无 14:30。
- 接口权限不足。
- 网络失败。
- 策略尾盘未触发，不是缺数据。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_gap or minute_bars or tdx or tushare or akshare or vnpy" -q
uv run python -m compileall alphaagent/server/services/data_sync.py alphaagent/server/services/data_providers alphaagent/server/api/data_sync.py
```

### R4. 拆 `MinuteDataWizard.tsx`

当前 `MinuteDataWizard.tsx` 约 804 行，状态、审计、provider、CSV、vn.py、严格流水线全部混在一个组件。

目标拆分：

```text
MinuteCoveragePanel.tsx       已存在；只展示覆盖状态和下一步。
MinuteGapSourceForm.tsx       回测 ID / 高级 CSV 来源。
MinuteProviderImportPanel.tsx provider 预检查/导入。
MinuteCsvFallbackPanel.tsx    CSV 兜底。
VnpyMinuteImportPanel.tsx     vn.py 本地库单标的/缺口导入。
StrictBacktestRunner.tsx      审计 ready 后运行 strict_1430。
MinuteDataWizard.tsx          只保留状态组合和数据流。
```

验收：

- `/quant` 数据页第一屏只看到回测 ID、覆盖状态、数据源、预检查、补齐、严格回测。
- CSV 只在高级区域。
- `/data` 仍能运行 `sync_stock_minute_bars mode=backtest_gaps`。
- 前端构建通过：

```bash
pnpm --dir frontend run build
```

### R5. 策略实现从 `factors.py` 继续拆

当前 `factors.py` 同时放了低吸、突破、公共指标函数。新增策略前先拆清楚，否则会继续变大。

目标：

```text
alphaagent/server/services/quant/factors.py
  只保留 Bar、SignalScore、公共指标函数。

alphaagent/server/services/quant/strategies/pullback.py
  mainline_leader_pullback。

alphaagent/server/services/quant/strategies/breakout.py
  breakout_confirmation。

alphaagent/server/services/quant/strategy_registry.py
  只做注册、元数据、dispatch。
```

原则：

- 先等价移动，不调阈值。
- 每个策略必须暴露：
  - `default_min_entry_score`
  - `failed_rule_labels`
  - `evidence_labels`
  - `primary_metric_keys`
  - `score()`

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy or breakout or pullback or failed_rules" -q
```

## 3. 需要调整

### A1. 回测入口分清“研究回测”和“严格真实性”

当前普通按钮默认跑 `tail_close_hybrid`，这可以保留为快速研究，但必须明确：

- `tail_close_hybrid` 是研究回测，可能包含 `daily_close_proxy`。
- `strict_1430` 是真实性回测，缺 14:30 快照就拒单。
- UI 上不要把混合回测的收益当成真实收益。

调整：

- 回测列表和报告选择器显示：
  - 策略。
  - 执行模型。
  - 14:30 真实买入数。
  - 收盘代理数。
  - 严格拒单数。
  - 覆盖状态。
- 普通运行结果第一屏固定展示“可信度/真实性结论”。
- 严格回测入口优先走回测 ID 补缺口，不再让用户先想 CSV。

### A2. BUY/WATCH 文案统一

规则：

```text
BUY：默认组合回测尝试买。
WATCH：默认组合回测不买。
宽松研究：显式开启后才允许 WATCH/分数达标股参与回测。
```

调整：

- 候选表、信号计划、候选追踪、回测报告统一中文解释。
- 报告显示 `strict_entry=true/false`，解释 WATCH 是否参与。
- “宽松研究买入”保留在高级区，并加风险提示。

验收：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "watch or strict_entry or candidate_trace" -q
pnpm --dir frontend run build
```

### A3. 日期选择全部交易日化

已有基础：

- `/api/quant/trading-dates`
- `/api/backtests/{id}/equity`
- `TradingDateSelector`

继续调整：

- 候选日期只来自本地交易日。
- 回测内日期只来自该回测权益曲线日期。
- 自然日输入自动对齐最近本地交易日，并显示提示。
- 明确区分：
  - 生成区间起点。
  - 查看候选交易日。
  - 回测开始日期。
  - 信号计划开始/结束日期。
  - 回测内复核日期。

### A4. 回测结果可读性继续增强

已具备：

- 组合最近成交分页查看全部。
- 日期钻取。
- 股票钻取。
- 14:30 覆盖面板。

继续调整：

- 拒单原因全部中文化。
- 理论金额预览和真实组合订单/成交视觉上分开。
- 日期钻取顶部固定显示：
  - 现金。
  - 持仓市值。
  - 总权益。
  - 当日买入。
  - 当日卖出。
  - 当日拒单。
- 股票钻取顶部固定显示：
  - 是否曾入选 BUY。
  - 是否实际买入。
  - 没买原因。
  - 持仓期间。
  - 卖出原因。

### A5. 金安国纪复核变成标准个股诊断

不要给 `002636.SZSE` 写特殊规则。

股票详情应支持：

- 默认加载最新组合回测 ID，并允许手动选择回测 ID。
- 展示低吸、突破策略历史 BUY 次数、最佳匹配日、失败规则。
- 展示指定组合回测下：
  - 候选动作。
  - 理论信号计划。
  - 真实订单。
  - 成交。
  - 持仓路径。
  - 没买原因。
- 没买原因定位到：
  - 未入选。
  - 只是 WATCH。
  - 排名落后。
  - 仓位满。
  - 现金不足。
  - 涨停买不到。
  - 跌停卖不出。
  - 尾盘未触发。
  - 缺 14:30。

### A6. 每次回测后固定真实性审计

每份回测报告必须能快速回答：

```text
1. 是否使用未来数据？
2. 买入/卖出信号日和执行日分别是哪天？
3. 买入价格来自 14:30、收盘代理还是旧开盘模型？
4. 费用、滑点、印花税、100 股整数手是否进入账本？
5. 现金、持仓市值、总权益是否可追踪？
6. 与基准、随机样本、walk-forward 的对比是否足够？
```

## 4. 需要新增

### N1. 策略对比面板

当前已完成第一步：

- `GET /api/quant/symbols/{vt_symbol}/strategy-comparison` 返回同一股票、同一区间的多策略摘要。
- 股票详情现有 `StockQuantAuditPanel` 已改为使用该统一接口，展示评分日、BUY 次数、WATCH 天数、最佳匹配日、失败规则和财报口径。
- 金安国纪默认区间已对齐 `DEFAULT_BACKTEST_START=2025-10-14`，页面显示低吸 BUY 23 次、突破 BUY 18 次。

仍未完成：

- `POST /api/backtests/strategy-comparison` 组合级策略对比。
- 指定组合回测 ID 下的基础买/没买原因已接入股票详情；后续还可把多策略摘要、组合级收益和候选排名变化合并成更完整的策略对比报告。

功能：

- 同一区间对比多个策略。
- 输出：
  - BUY 次数。
  - WATCH 次数。
  - 真实成交数。
  - 拒单数。
  - 收益。
  - 回撤。
  - 14:30 真实占比。
  - 收盘代理占比。
- 股票详情可对金安国纪同时展示低吸、突破、后续新策略。

后端建议：

```text
GET /api/quant/symbols/{vt_symbol}/strategy-comparison
POST /api/backtests/strategy-comparison
```

### N2. 新策略：涨停后回踩

建议 ID：

```text
limit_up_after_pullback
```

目标：

- 覆盖强势股涨停后回踩确认买点。
- 加入涨停不可买、换手过热、板块强度衰减、次日冲高回落约束。
- 不硬改低吸策略。

第一版只用日线可见数据，不引入盘中分钟信号。

### N3. 新策略：强势加速

建议 ID：

```text
trend_acceleration
```

目标：

- 覆盖金安国纪这类不适合低吸解释的突破/加速段。
- 必须单独做追高风险、涨跌停无法成交、回撤、止损验证。
- 和 `breakout_confirmation` 做对比，不要重复造一个阈值略不同的突破策略。

### N4. 新执行模型：盘中 14:30 信号

建议 ID：

```text
intraday_1430_signal
```

目标：

```text
使用 T 日 14:30 及以前 1m 数据聚合出截至 14:30 的临时 OHLCV
-> 替代完整 T 日日线参与评分
-> T 日 14:30 生成信号
-> T 日 14:30 按同一快照成交
```

限制：

- 不是当前日线回测的参数开关。
- 禁止使用 T 日收盘价、T 日全日成交量、收盘后资金流等未来信息。
- 单独报告，不和 `D close -> D+1 14:30` 混在一起。
- 需要足够完整的历史 1m 数据；当前不要先做。

### N5. 反未来函数和反过拟合报告升级

新增检查：

- 每类数据可见日期约束。
- 财报必须 `publish_date <= trade_date`。
- 候选只用 `trade_date` 及以前日线。
- 买入/卖出只使用 `signal_date` 之后的执行日价格。
- 多年全 A。
- walk-forward。
- 参数敏感性。
- 分市场状态。
- 基准超额。
- 随机样本对照。

## 5. 推荐执行顺序

### Task 1: 锁定当前边界测试

**Files:**

- Modify: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 补测试：严格回测只接受 `1m`。
2. 补测试：`10m` 继续被拒绝。
3. 补测试：默认 `strict_entry=true` 不买 WATCH。
4. 补测试：`strict_entry=false` 只作为显式宽松研究模式。
5. 补测试：卖出必须 D 日信号、D+1 执行。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_interval or watch or strict_entry or sell" -q
```

### Task 2: 清理旧入口和误导文案

**Files:**

- Modify: `frontend/src/features/quant/BacktestParamsForm.tsx`
- Modify: `frontend/src/features/quant/constants.ts`
- Modify: `frontend/src/features/quant/QuantWorkflowGuide.tsx`
- Modify: `frontend/src/features/quant/VnpyStatusPanel.tsx`
- Modify: `frontend/src/features/quant/BacktestSummary.tsx`
- Modify: `frontend/src/lib/backtest-utils.ts`
- Modify: `docs/alphaagent/quant_flow.md`

**Steps:**

1. 普通回测入口只展示起始交易日、资金、样本股票、最大持仓、最低分、运行按钮。
2. 高级区保留策略、执行模型、宽松研究；尾盘时间固定 `14:30`，不可编辑。
3. 清理旧 `legacy_next_open`、开盘回退默认描述。
4. vn.py 状态拆成可行动检查项。

**Run:**

```bash
rg -n "legacy_next_open|10m|10分钟|部分就绪" frontend/src/features/quant frontend/src/pages/QuantTradingPage.tsx docs/alphaagent -S --glob '!**/*.tsbuildinfo'
pnpm --dir frontend run build
```

### Task 3: 补齐 `#60` 严格缺口闭环（已完成）

**Files:**

- Modify only if needed: `alphaagent/server/services/data_sync.py`
- Modify only if needed: `alphaagent/server/services/data_providers/tdx_minute_import.py`
- Modify only if needed: `alphaagent/server/services/data_providers/tushare_minute_import.py`
- Evidence: `memory/06_backtests/`

**Steps:**

1. 已用 `backtest_id=60` 审计出 5 个 14:30 缺口。
2. 已用 TDX dry-run 覆盖 5/5；AkShare 历史日期无数据，Tushare 当前未配置 token，vn.py 本地库路径当前不可用。
3. 已正式写入 5 行 TDX `1m / 14:30` 快照。
4. 已按来源参数重跑 `strict_1430`，生成 `#62`。
5. 已更新真实性报告和 memory。

**Run:**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
curl -s http://127.0.0.1:8000/api/backtests/62/minute-coverage
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_gap or strict_pipeline" -q
```

### Task 4: 拆 `backtest/reports.py`

**Files:**

- Create: `alphaagent/server/services/backtest/reports.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 移动执行质量统计。
2. 移动真实性结论。
3. 移动报告导出/CSV 构建。
4. 保持 API 返回不变。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "report or execution_quality or minute_coverage or csv" -q
```

### Task 5: 拆 `backtest/persistence.py`

**Files:**

- Create: `alphaagent/server/services/backtest/persistence.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 移动 `_persist_run()` 和 backtest 表写入。
2. 移动回测读取详情。
3. 移动日期/股票钻取查询。
4. 保持 API 契约不变。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "persist or day_detail or symbol_detail or trades" -q
```

### Task 6: 拆分钟缺口服务

**Files:**

- Create: `alphaagent/server/services/minute_gaps.py`
- Create: `alphaagent/server/services/minute_imports.py`
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/api/data_sync.py`
- Modify: `alphaagent/server/services/data_providers/akshare_minute_import.py`
- Modify: `alphaagent/server/services/data_providers/tdx_minute_import.py`
- Modify: `alphaagent/server/services/data_providers/tushare_minute_import.py`
- Modify: `alphaagent/server/services/vnpy_integration/database_import.py`

**Steps:**

1. 移动缺口解析和审计函数。
2. 移动标准分钟线导入函数。
3. API 路径不变。
4. 统一 provider 返回结构。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "minute_gap or minute_bars or tdx or tushare or akshare or vnpy" -q
```

### Task 7: 拆前端分钟补数向导

**Files:**

- Create: `frontend/src/features/quant/MinuteGapSourceForm.tsx`
- Create: `frontend/src/features/quant/MinuteProviderImportPanel.tsx`
- Create: `frontend/src/features/quant/MinuteCsvFallbackPanel.tsx`
- Create: `frontend/src/features/quant/VnpyMinuteImportPanel.tsx`
- Create: `frontend/src/features/quant/StrictBacktestRunner.tsx`
- Modify: `frontend/src/features/quant/MinuteDataWizard.tsx`
- Modify: `frontend/src/pages/DataManagementPage.tsx`

**Steps:**

1. 抽回测 ID 缺口来源表单。
2. 抽 provider 预检查/导入按钮。
3. 抽 CSV 高级兜底。
4. 抽 vn.py 本地库导入。
5. 抽严格回测运行按钮。

**Run:**

```bash
pnpm --dir frontend run build
```

### Task 8: 策略对比和金安国纪诊断（部分完成）

**Files:**

- Modify: `alphaagent/server/api/quant.py`
- Modify: `alphaagent/server/services/quant/screening.py`
- Modify: `alphaagent/server/services/backtest/engine.py`
- Modify: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Steps:**

1. 已完成：同一股票、同一区间返回所有策略历史 BUY/WATCH 摘要。
2. 已完成：股票详情展示每套策略的评分日、BUY 次数、WATCH 天数、最佳匹配日和失败规则。
3. 已完成：金安国纪页面默认完整区间显示低吸 BUY 23 次、突破 BUY 18 次。
4. 已完成基础版：指定组合回测 ID 和信号日后，股票详情显示为什么没买、是否下单/成交，以及执行日现金、持仓市值和总权益。
5. 未完成增强版：组合级多策略对比和收益/回撤统一报告。

**Run:**

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "strategy or symbol_signal or candidate_trace" -q
pnpm --dir frontend run build
```

### Task 9: 新策略前固定验证基线

**Files:**

- Modify: `memory/06_backtests/`
- Modify: `memory/09_decisions/decisions.md`

**Steps:**

1. 用当前修复后代码重跑低吸 `strict_1430`。
2. 用当前修复后代码重跑突破 `strict_1430`。
3. 记录 14:30 覆盖、剩余缺口、收益、回撤、基准、随机样本。
4. 缺口未补齐时不判断策略优劣。

### Task 10: 新增策略

**Files:**

- Modify: `alphaagent/server/services/quant/factors.py`
- Modify: `alphaagent/server/services/quant/strategy_registry.py`
- Add after R5 if split first: `alphaagent/server/services/quant/strategies/limit_up_pullback.py`
- Add after R5 if split first: `alphaagent/server/services/quant/strategies/trend_acceleration.py`
- Modify: `frontend/src/features/quant/RecommendationsPanel.tsx`
- Modify: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

**Order:**

1. 先新增 `limit_up_after_pullback`。
2. 重跑策略对比。
3. 再新增 `trend_acceleration`。
4. 每个新策略都必须有独立失败规则、关键指标、BUY/WATCH 文案和回测真实性报告。

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
  候选页：交易日选择、策略选择、BUY/WATCH、候选追踪。
  回测页：回测参数、真实性结论、14:30 覆盖、成交分页、日期/股票钻取。
  数据页：回测 ID 审计、provider 预检查、严格流水线。

/stocks/002636.SZSE
  低吸/突破历史 BUY 次数。
  组合回测买卖点和没买原因。
  财报覆盖说明。

/data
  sync_stock_minute_bars mode=backtest_gaps。
```

## 7. 当前优先级判断

优先做：

1. 拆 `engine.py` 的报告/持久化部分，降低后续金额和真实性排查成本。
2. 拆 `data_sync.py` 和 `MinuteDataWizard.tsx`，让补数路径保持回测 ID 优先，CSV 只作为高级兜底。
3. 把股票详情的策略对比摘要与指定组合回测 ID 的买/没买原因继续合并成更完整的标准个股诊断。
4. 做组合级多策略对比和参数敏感性验证。
5. 在上述口径稳定后再设计涨停后回踩、强势加速等新策略。

暂缓做：

- 新增策略。
- `intraday_1430_signal`。
- 多年全 A walk-forward 大验证。

原因：当前基础链路还有可读性和结构问题。先把“当前策略到底怎么选、怎么成交、为什么没买、数据缺在哪里”变成稳定可核查，再扩展策略。
