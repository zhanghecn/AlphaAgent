# Data Flow

vn.py 中数据需要分清四类：

- 合约列表/证券基础信息。
- 实时 Tick 行情。
- 历史 K 线/Tick。
- 财务/基本面/指数成分等研究数据。

## 实时行情路径

1. 安装并注册 Gateway 插件。
2. 通过 `MainEngine.connect()` 连接。
3. Gateway 查询/推送合约信息，产生 `ContractData` 事件。
4. 通过 `MainEngine.subscribe()` 订阅标的行情。
5. Gateway 推送 `TickData`。
6. `OmsEngine` 缓存最新 Tick，可通过 `get_tick()` 或 `get_all_ticks()` 查询。

相关源码：

- `vnpy/trader/engine.py`
- `vnpy/trader/gateway.py`
- `vnpy/trader/object.py`
- `vnpy/trader/event.py`

## 历史数据路径

1. 安装 Datafeed 插件，例如 `vnpy_rqdata`、`vnpy_xt`、`vnpy_tushare`。
2. 配置全局 `SETTINGS["datafeed.name"]`、用户名、密码/token。
3. 使用 `get_datafeed()` 获取数据服务实例。
4. 构造 `HistoryRequest`。
5. 调用 `query_bar_history()` 或 `query_tick_history()`。
6. 保存到数据库或 AlphaLab。

相关文件：

- `vnpy/trader/datafeed.py`
- `docs/community/info/datafeed.md`
- `examples/download_bars/download_bars.ipynb`
- `examples/alpha_research/download_data_rq.ipynb`
- `examples/alpha_research/download_data_xt.ipynb`

## 本地数据库路径

当前安装了 `vnpy_sqlite`，适合入门阶段保存历史数据。

常见入口：

- DataManager GUI。
- `vnpy.trader.database.get_database()`。
- 官方 `examples/download_bars/download_bars.ipynb`。

## AlphaAgent 日线同步路径

当前 AlphaAgent 自研服务的股票日线同步不走 vn.py Datafeed，而是：

1. `alphaagent.server.services.data_sync.run_job("sync_stock_daily_bars")`
2. `DataSyncRunner._run_sync_stock_daily_bars()`
3. `AkShareAdapter.stock_bars(..., interval="1d")`
4. 写入 PostgreSQL `stock_daily_bars`

当前已验证事实：

- 股票日线优先使用腾讯 `newfqkline` 接口，源码 helper 为 `_tencent_stock_kline_full()`。
- 腾讯 `newfqkline` 的成交额字段单位为“万元”，入库前换算为“元”。
- `stock_daily_bars.volume` 来自 A 股行情源，常见单位为“手”；旧数据缺 `turnover` 时，量化流动性兜底按 `close * volume * 100` 估算成交额。
- `sync_stock_daily_bars` 支持 `symbols` 参数，可定向重跑单只股票，例如 `{"symbols":["002636.SZSE"],"limit":250}`。
- 2026-06-12 已定向回填金安国纪 `002636.SZSE` 250 根日线，`turnover` 覆盖约 99.6%；全表历史旧数据仍需重跑补齐。

## AlphaAgent 分钟线同步路径

当前 `sync_stock_minute_bars` 是分钟线同步的主入口，不能再把严格回测缺口补数只当作旁路导入工具：

1. `mode=recent`：保持原有最近分钟线同步，按 `stock_limit`、`limit`、`interval`、`start_date/end_date` 从 AkShare/公开行情适配器读取近端分钟线；这个入口属于通用分钟 K 线同步，不等于回测缺口已经覆盖。
2. `mode=backtest_gaps`：按严格尾盘回测缺口补执行日 14:30 快照分钟线，可传 `backtest_id`、`gap_file_path` 或 `gap_csv_text`。默认窗口为 `tail_entry_start=14:30`、`tail_entry_end=14:30`。
3. 量化严格 14:30 缺口补数统一只支持 `1m` 快照，不再把 `5m/10m` 作为量化主流程周期；通用分钟 K 线导入仍可保留多周期供行情查看使用。
4. `provider=tdx`：使用 TDX 公开行情读取真实历史 `1m`；公开服务器可回溯范围有限，必须以缺口审计结果为准。
5. `provider=tushare`：使用 Tushare Pro `stk_mins`，需要 `TUSHARE_TOKEN` 和分钟数据权限；严格缺口 wrapper 只走 `1m`。
5. `dry_run=true` 默认只预检查/读取，不真实写入；关闭 dry-run 后才写 `stock_minute_bars`。
6. 数据管理页 `/data` 的“股票分钟 K 线”任务已提供参数面板，执行仍调用 `POST /api/data-sync/jobs/sync_stock_minute_bars/run`，不是手工脚本。

2026-06-14 复核 AkShare 分钟线能力：

- 运行中的 Docker API 容器内 AkShare 为 `1.18.64`，`/api/data-sources/akshare/smoke` 通过，A 股列表、日 K、板块、主营构成都可用。
- `AkShareAdapter.stock_bars(..., interval="1m", start_date="2026-06-12", end_date="2026-06-12")` 可通过项目自写 EastMoney 分钟 K 路径返回完整当日 240 根 1 分钟线；`002636.SZSE` 和 `600000.SSE` 均能查到 `2026-06-12 14:30` 分钟 bar。
- 同一路径请求 `002636.SZSE` 的 `2026-06-11`、`2026-01-07`、`2025-10-13` 返回空；请求 `600000.SSE` 的 `2026-01-07` 也返回空。当前不能把 AkShare/东方财富公共分钟线视为可覆盖 2025 至 2026-06-13 全区间严格回测缺口的数据源。
- 当前 `mode=backtest_gaps` 已接入 `akshare`、`tdx`、`tushare` 和 vn.py 本地库导入路径；AkShare 只适合作为近端 14:30 快照补充，历史缺口仍需要审计确认。

相关源码：

- `alphaagent/server/services/data_sync.py`
- `alphaagent/server/services/data_providers/tdx_minute_import.py`
- `alphaagent/server/services/data_providers/tushare_minute_import.py`
- `frontend/src/pages/DataManagementPage.tsx`

## AlphaAgent 量化/回测核查路径

当前 `/quant` 候选和回测核查不走 vn.py Datafeed，而是使用 AlphaAgent PostgreSQL 业务表：

1. `GET /api/quant/trading-dates` 从 `stock_daily_bars` 聚合本地真实交易日；前端候选日期和回测开始日期选择器使用它，只在有日线数据的交易日之间切换。
2. `POST /api/quant/screen-runs/range` 从选中的起始交易日到本地最新交易日逐日生成候选并落库；只有最后一个交易日同步到“量化候选”分组。`POST /api/quant/screen-runs` 保留为单日脚本/调试接口。
3. `quant_signal_runs` 记录每次筛选运行；`GET /api/quant/screen-runs` 给前端候选日期选择器叠加显示运行编号和候选数。
4. `quant_recommendations` 支持按 `trade_date` 查询；候选表会显示 `risk_score`、`liquidity_score` 和 `failed_rules`，用于核查当日推荐是否正确。
5. 组合回测列表支持 `GET /api/backtests?run_type=portfolio`，前端默认只看组合回测，避免股票详情页的单股回测混进量化页主列表。
6. 新组合回测会写 `backtest_signal_events`，记录每只股票独立状态机下的理论 BUY/SELL 信号；旧回测没有这张流水，需要重跑组合回测。
7. `GET /api/backtests/{id}/equity` 返回该回测实际交易日，前端“信号计划”的开始/结束日期选择器使用它。
8. `GET /api/backtests/{id}/signal-events/amount-preview` 按 `总资金 / 最大持仓数` 做等权金额预览，买入按 100 股整数手，卖出沿用最近一次理论买入数量。
9. `GET /api/backtests/{id}/trades?limit=20&offset=0&order=desc` 分页返回真实组合成交，用于前端“组合最近成交”翻页查看全部。
10. `GET /api/backtests/{id}/drilldown-options` 返回回测钻取的完整日期和股票选项。日期来自 `backtest_daily_equity`，股票来自 `backtest_trades`、`backtest_orders`、`backtest_signal_events` 和 `backtest_daily_positions` 的合集，因此能查到“有理论信号/拒单但没有成交”的股票。
11. `GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=` 追踪某个交易日候选在组合回测中的链路：候选动作、理论信号计划、计划执行日、真实订单、成交、当天现金/持仓市值/总权益和没买原因。没有理论信号计划时不会把同日订单误关联为候选成交；若候选存在但未进计划，会额外返回 `not_planned_context`，包含回测首个/最后信号日、股票池名次、候选排名、当天候选 BUY/WATCH 数、当天理论计划数和候选/计划前列。
12. 回测账本金额由 `alphaagent.server.services.backtest.ledger` 计算：买入滑点、卖出滑点、佣金、印花税、100 股整数手、现金不足降档和拒单都在这里；`engine.py` 只负责调用并写订单、成交、持仓和权益曲线。
13. 理论信号与真实订单关联由 `alphaagent.server.services.backtest.signal_plan` 计算：按 `vt_symbol + execute_date/trade_date + side` 匹配，输出 `linked_order_id`、`linked_order_status`、`linked_order_reason`、`plan_status` 和 `plan_status_label`，供信号流水和候选追踪复用。
14. 回测订单、信号和候选追踪 API 行会返回 `reason_label` / `linked_order_reason_label`，用于前端显示“尾盘入场未触发”“现金不足”等中文原因。
15. 组合回测加载日线时会从用户开始日前额外加载预热历史 K 线，避免 MA60、60 日回撤等指标在回测初期因样本不足而缺失；但权益、持仓和交易记录仍只从用户选择的开始日期开始。
16. 股票详情页单股复盘会在读取最新单股回测后再调用 `/api/backtests/{id}/audit?vt_symbol=`，用审计事件生成 K 线标记：T 日 BUY 信号、T+1 执行拒绝、实际买入成交和实际卖出成交。只有 `backtest_trades` 不足以解释“有信号但未买入”的情况。

注意：`backtest_signal_events` 是理论信号计划，用于核查“历史上有没有买点/卖点”；真实组合资金曲线仍以 `backtest_trades`、`backtest_daily_equity` 和 `backtest_daily_positions` 为准。

2026-06-14 回测钻取复核：

- `#62` 的 `GET /api/backtests/62/drilldown-options` 返回 `date_count=85`、`symbol_count=61`，日期覆盖 `2026-02-02` 到 `2026-06-12`。
- `/quant -> 回测 -> 交易归因` 日期下拉和股票下拉已改用该接口；旧 `report.equity_tail/recent_trades` 推导只作为接口不可用时兜底。
- 浏览器验证可选中 `000338.SZSE` 这类“有拒单但无成交”的股票，并显示中文原因“尾盘入场未触发”。

## AlphaAgent 财报可见性口径

股票详情页和回测评分现在共用 `alphaagent.server.services.quant.financials` 的可见性口径：

1. `financial_coverage_summary(session, vt_symbol, trade_date)` 返回本地财报数、回测可用数、缺披露日数、晚于回测日披露数、最新披露日和最近可用报告日。
2. `financial_scores_from_rows_by_symbol(rows_by_symbol, trade_date)` 只使用 `publish_date <= trade_date` 的第一条本地财报打分。
3. 股票详情页看到“现在可查”的财报，不代表历史回测当天可用；页面会显示“财报口径”说明和不可用统计，避免误解为数据丢失。

2026-06-14 金安国纪 `002636.SZSE` 复核：

- 本地财报 `20` 条。
- 回测可用 `20` 条。
- 缺披露日 `0` 条。
- 披露日晚于区间 `0` 条。
- 最新披露日 `2026-04-29`。
- 最近可用报告 `2026-03-31 00:00:00`。
- 策略对比入口：`GET /api/quant/symbols/002636.SZSE/strategy-comparison?start=2025-10-14&end=2026-06-13` 返回低吸 BUY `23` 次、突破 BUY `18` 次，两个策略各有 `162` 个评分日。

## DataManager

文件/文档：

- `docs/community/app/data_manager.md`
- 插件：`vnpy_datamanager`

作用：

- 下载历史数据。
- 导入 CSV。
- 查看数据库已有数据。
- 导出 CSV。
- 删除/更新数据。

前提：

- 已配置 Datafeed，或者已连接能提供历史数据的 Gateway。
