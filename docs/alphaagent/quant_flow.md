# AlphaAgent 量化实现流程审查

本文按代码路径说明当前量化功能如何从上游数据进入本地库，如何生成候选，如何回测，如何处理尾盘分钟线缺口，以及如何写入模拟持仓。它描述的是当前实现，不是投资建议。

## 1. 总体链路

当前量化链路分成五段：

1. 数据同步：外部公开源、CSV、vn.py 数据库或 Tushare/TDX 补数进入 PostgreSQL。
2. 因子评分：用本地日线、板块、财务、资金流、热度、龙虎榜等表给股票打分。
3. 量化筛选：把分数高、靠近 5 日线、流动性和风险满足条件的股票写入推荐表。
4. 回测验证：按 D 日收盘信号、D+1 尾盘分钟或开盘回退成交模拟交易。
5. 模拟持仓：把推荐结果写入模拟账户和持仓分组，不连接券商实盘。

主页面入口：

- 前端页面：[frontend/src/pages/QuantTradingPage.tsx](/root/project/ai/vnpy/frontend/src/pages/QuantTradingPage.tsx)
- 数据管理页：[frontend/src/pages/DataManagementPage.tsx](/root/project/ai/vnpy/frontend/src/pages/DataManagementPage.tsx)
- API 路由聚合：[alphaagent/server/api/router.py](/root/project/ai/vnpy/alphaagent/server/api/router.py)

## 2. 数据入口

数据同步 API：

- [alphaagent/server/api/data_sync.py](/root/project/ai/vnpy/alphaagent/server/api/data_sync.py)
- [alphaagent/server/services/data_sync.py](/root/project/ai/vnpy/alphaagent/server/services/data_sync.py)

核心表定义：

- [alphaagent/server/db/schema.py](/root/project/ai/vnpy/alphaagent/server/db/schema.py)

主要数据表：

- `stocks`: 全 A 股票基础信息和最新快照。
- `stock_daily_bars`: 股票日线，用于主筛选和日线回测。
- `stock_minute_bars`: 1 分钟线，用于 D+1 尾盘接近 MA5 的真实成交验证。
- `stock_financial_reports`: 财报摘要，用于财务改善评分。
- `sector_period_scores`: 板块周期强弱，用于主线评分。
- `stock_fund_flows`, `stock_hot_ranks`, `stock_lhb_records`: 资金流、热度、龙虎榜代理指标。
- `quant_stock_signals`, `quant_recommendations`: 量化评分和推荐结果。
- `backtest_runs`, `backtest_trades`, `backtest_orders`, `backtest_daily_equity`: 回测结果。
- `simulation_accounts`, `simulation_positions`, `simulation_orders`, `simulation_trades`: 模拟账户。

数据来源：

- AkShare/东方财富/腾讯/新浪：通过 `DataSyncRunner` 同步股票、日线、板块、资金流等。
- 外部 CSV：`POST /api/data-sync/imports/minute-bars` 导入分钟线。
- vn.py 数据库：`POST /api/vnpy/import-minute-bars` 和 `/api/vnpy/import-minute-bars/gaps`。
- TDX 公开源：`POST /api/data-sync/imports/minute-bars/tdx-gaps`，适合近端分钟线补缺口。
- Tushare Pro：`POST /api/data-sync/imports/minute-bars/tushare-gaps`，需要 `TUSHARE_TOKEN` 和分钟数据权限。

注意：公开分钟源并不保证长历史可用。严格尾盘回测必须先审计分钟线覆盖率。

## 3. 因子评分

评分代码：

- [alphaagent/server/services/quant/factors.py](/root/project/ai/vnpy/alphaagent/server/services/quant/factors.py)

策略标识：

```python
STRATEGY_ID = "mainline_leader_pullback"
STRATEGY_VERSION = "0.1.0"
```

单股评分入口：

```python
score_stock(vt_symbol, bars, trade_date, index_return_20d, sector_score, financial_score, fund_flow_score, hot_rank_score, lhb_score)
```

当前总分权重：

- 相对大盘强弱 `relative_strength`: 25%
- 洗盘/回踩结构 `washout`: 20%
- 趋势质量 `trend_quality`: 15%
- 板块主线 `sector`: 12%
- 财务改善 `financial`: 10%
- 资金/热度/龙虎榜代理 `smart_money`: 8%
- 流动性 `liquidity`: 10%
- 风险分当前只用于入场过滤，不直接加权。

当前买点条件：

```python
entry_signal = total >= 68 and pullback_near_ma and risk >= 35 and liquidity >= 25
```

其中 `pullback_near_ma` 是最新收盘价距离 5 日均线约 `-1.5%` 到 `+2.0%`。

重要边界：

- “主力洗盘”“偷偷试探”当前是可观测代理指标，不是主力真实意图证明。
- 资金流、热度、龙虎榜只作为加分项，缺数据时默认中性 50 分。
- 财报只在有可用字段时加减分，缺数据不强制剔除。

## 4. 筛选和推荐

筛选服务：

- [alphaagent/server/services/quant/screening.py](/root/project/ai/vnpy/alphaagent/server/services/quant/screening.py)
- [alphaagent/server/api/quant.py](/root/project/ai/vnpy/alphaagent/server/api/quant.py)

前端调用：

- [frontend/src/api/quant.ts](/root/project/ai/vnpy/frontend/src/api/quant.ts)

API：

- `POST /api/quant/screen-runs`
- `GET /api/quant/recommendations`
- `GET /api/quant/signals`

筛选步骤：

1. 找最新交易日。
2. 从 `stocks` 里按成交额和市值取股票池。
3. 从 `stock_daily_bars` 取每只股票最近约 160 根日线。
4. 读取指数 20 日收益、板块分、财务分、资金流分、热度分、龙虎榜分。
5. 调用 `score_stock()`。
6. 只保留 `entry_signal=True` 或总分超过最小推荐分的股票。
7. 写入 `quant_stock_signals` 和 `quant_recommendations`。
8. 如果开启 `auto_portfolio`，同步到持仓分组“量化候选”。

数据库未配置时，服务返回：

```json
{"status": "unavailable", "message": "DATABASE_URL not configured"}
```

前端现在会展示原因，并引导去 `/data` 检查数据状态，而不是只报 503。

## 5. 回测

回测服务：

- [alphaagent/server/services/backtest/engine.py](/root/project/ai/vnpy/alphaagent/server/services/backtest/engine.py)
- [alphaagent/server/api/backtests.py](/root/project/ai/vnpy/alphaagent/server/api/backtests.py)

核心参数：

```python
BacktestParams(
    initial_cash=1_000_000,
    max_positions=8,
    max_position_pct=0.125,
    commission_rate=0.0003,
    stamp_tax_rate=0.0005,
    slippage_bps=10,
    stop_loss_pct=0.07,
    take_profit_pct=0.18,
    trailing_stop_pct=0.08,
    time_stop_days=15,
    min_entry_score=68,
    intraday_entry=True,
    minute_entry_required=False,
)
```

成交逻辑：

1. D 日用当日及之前可见日线评分。
2. D 日生成买入候选，实际成交放到 D+1。
3. 如果 `intraday_entry=True` 且有 D+1 尾盘窗口分钟线，尝试在 `14:30-14:57` 之间接近可见 MA5 成交。
4. 如果分钟线不足且 `minute_entry_required=False`，回退到 D+1 开盘价成交。
5. 如果分钟线不足且 `minute_entry_required=True`，该买单拒绝，原因记录为 `tail_entry_not_triggered`。
6. 卖出按止损、止盈、跟踪止损、时间止损执行。

费用假设：

- 买卖佣金。
- 卖出印花税。
- 滑点。
- 100 股取整。

反过拟合检查：

- 报告里包含样本内/样本外分段、市场环境分段、成本压力、随机样本基准、执行真实性检查。
- 参数网格通过 `GET /api/backtests/{id}/validation-grid` 重新跑多组参数，不默认自动触发，避免长任务误跑。

## 6. 严格尾盘分钟回测

严格流水线：

- [alphaagent/server/services/backtest/strict_pipeline.py](/root/project/ai/vnpy/alphaagent/server/services/backtest/strict_pipeline.py)

API：

- `POST /api/backtests/strict-minute-pipeline`
- `GET /api/backtests/{backtest_id}/minute-gaps.csv`
- `POST /api/data-sync/imports/minute-bars/audit-gaps`

严格流程：

1. 先运行 `minute_entry_required=true` 的回测，缺分钟线的订单会被拒绝。
2. 导出缺口 CSV：`/api/backtests/{id}/minute-gaps.csv`。
3. 用 `/api/data-sync/imports/minute-bars/audit-gaps` 审计缺口覆盖率。
4. 如果覆盖率不是 100%，流水线返回 `blocked_by_minute_gaps`，不运行严格回测。
5. 补齐分钟线后重新审计。
6. 审计 ready 后，`strict-minute-pipeline` 才会强制 `minute_entry_required=true` 运行并持久化回测。

这一步是为了避免伪真实回测：不能在没有分钟线的情况下声称尾盘低吸规则有效。

## 7. 模拟持仓

模拟账户服务：

- [alphaagent/server/services/simulation/account.py](/root/project/ai/vnpy/alphaagent/server/services/simulation/account.py)
- [alphaagent/server/api/simulation.py](/root/project/ai/vnpy/alphaagent/server/api/simulation.py)

API：

- `GET /api/simulation/accounts`
- `POST /api/simulation/accounts`
- `POST /api/simulation/auto-buy-recommendations`
- `GET /api/portfolios/holdings`

自动模拟建仓：

1. 读取最新 active 且 action 为 `BUY` 的 `quant_recommendations`。
2. 默认每只股票 10 万模拟买入。
3. 使用最新日线收盘或股票最新价作为成交价。
4. 已有持仓则跳过。
5. 写入模拟订单、成交、持仓。
6. 同步到“自动模拟持仓”分组。

当前限制：

- 不连接券商。
- 不自动卖出实盘。
- 价格来自本地数据，数据缺失会拒绝成交。

## 8. 前端操作路径

页面：

- `/data`: 数据状态、同步任务、数据源。
- `/quant`: 量化筛选、回测、分钟线补数、模拟持仓。

推荐操作顺序：

1. 到 `/data` 看 PostgreSQL、Redis、数据能力是否可用。
2. 同步股票清单和日线，财报/资金流/板块数据可逐步补。
3. 到 `/quant` 运行筛选。
4. 查看量化候选是否生成。
5. 先运行普通回测，看样本、交易、收益、回撤、执行真实性。
6. 如果要验证尾盘低吸，导出缺口 CSV，补分钟线，审计 ready 后运行严格流水线。
7. 只在筛选和回测都能解释时，使用自动模拟建仓。

## 9. 当前还缺什么

高优先级：

- 长区间 A 股 1 分钟历史数据源，需要 Tushare/RQData/XT/QMT/券商 CSV。
- A 股实盘 Gateway/Datafeed 还未安装配置，vn.py 当前不是 A 股实盘可交易状态。
- 财报字段覆盖率仍不高，现金流改善因子目前是优先级加分，不是硬过滤。
- `data_sync.py` 仍偏大，后续应拆成“同步任务”“分钟线导入”“缺口审计”“供应商清单”几个模块。

中优先级：

- 将参数网格和 walk-forward 结果做成更清晰的审查报告。
- 前端 `/quant` 继续拆组件，避免单文件过大。
- 指数基准应持久化到本地表，减少临时外部请求。

低优先级：

- 增加用户自定义策略模板。
- 增加持仓分组的批量操作。
- 增加更细的风险事件面板。
