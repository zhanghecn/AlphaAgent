# Core Source Entrypoints

## MainEngine

文件：`vnpy/trader/engine.py`

作用：

- 平台主引擎。
- 管理 Gateway、App、功能引擎。
- 暴露连接、订阅、下单、撤单、查历史数据等统一接口。

关键方法：

- `add_gateway(gateway_class, gateway_name="")`
- `add_app(app_class)`
- `connect(setting, gateway_name)`
- `subscribe(req, gateway_name)`
- `send_order(req, gateway_name)`
- `cancel_order(req, gateway_name)`
- `query_history(req, gateway_name)`
- `get_all_contracts()`
- `get_all_ticks()`

## Gateway

文件：`vnpy/trader/gateway.py`

作用：

- 定义交易接口基类。
- 具体 Gateway 插件负责实现连接、订阅、下单、撤单、查询等。
- Gateway 通过事件把 Tick、Contract、Account、Position、Order、Trade 推给主引擎。

## Datafeed

文件：`vnpy/trader/datafeed.py`

作用：

- 定义历史数据服务接口。
- `get_datafeed()` 读取 `SETTINGS["datafeed.name"]`。
- 如果配置了 `datafeed.name = "rqdata"`，会尝试导入 `vnpy_rqdata`。
- 如果没有配置或模块不存在，会返回 `BaseDatafeed`，查询结果为空并打印错误。

## Object Models

文件：`vnpy/trader/object.py`

关键对象：

- `TickData`: Tick 行情。
- `BarData`: K 线。
- `ContractData`: 合约信息。
- `HistoryRequest`: 历史数据请求。
- `SubscribeRequest`: 行情订阅请求。
- `OrderRequest`: 委托请求。

## AlphaLab

文件：`vnpy/alpha/lab.py`

作用：

- Alpha 投研数据管理。
- 保存/加载日线、分钟线、指数成分、数据集、模型、信号。
- 使用 parquet 和 shelve 管理本地研究数据。

## AlphaAgent Quant MVP

文件：

- `alphaagent/server/api/quant.py`
- `alphaagent/server/api/backtests.py`
- `alphaagent/server/api/portfolios.py`
- `alphaagent/server/api/simulation.py`
- `alphaagent/server/services/quant/`
- `alphaagent/server/services/backtest/`
- `alphaagent/server/services/portfolio/`
- `alphaagent/server/services/simulation/`
- `frontend/src/api/quant.ts`
- `frontend/src/pages/QuantTradingPage.tsx`

作用：

- 提供主线龙头分歧低吸的日线量化信号。
- 持久化筛选会把高分候选同步到“量化候选”分组；只有 `action=BUY` 的推荐会被自动模拟建仓。
- 提供日线组合回测和 `/api/backtests/{id}/report` 回测表接口，规则为 D 日收盘生成信号、D+1 开盘模拟成交。
- `/api/backtests/{id}/report` 当前返回扩展回测表：样本覆盖率、扩展交易指标、样本等权和指数基准对比、样本内/样本外分段、年度分段、市场环境分段、成本压力测试、随机样本基准、反过拟合诊断、月度收益、个股贡献、最差交易、订单未成交原因、权益尾部和数据质量快照。
- `/api/backtests/{id}/report.csv` 返回可下载 CSV 回测表，包含摘要、核心指标、样本覆盖、扩展交易指标、基准对比、分段、反过拟合检查、月度、个股、最差交易、交易明细、订单统计和数据质量。
- 量化、回测、持仓、模拟服务会在直接调用时创建 AlphaAgent 业务表，不依赖 API lifespan 单一路径。
- 提供持仓分组、自选观察、量化候选、模拟持仓和黑名单基础能力。
- 提供本地模拟账户、模拟订单、模拟成交、模拟持仓和风险事件查询。
- 前端 `/quant` 页面展示量化候选、回测表和模拟持仓，并提供运行筛选、参数化运行回测、导出 CSV、自动模拟建仓按钮。
- `stock_minute_bars` 和 `sync_stock_minute_bars` 已加入，用于尾盘 14:30-14:57 接近 MA5 的分钟级入场验证；分钟线缺失时回测会把买入标记为 `daily_next_open_fallback`，强制分钟模式可拒绝缺分钟数据的订单。
- `sync_stock_minute_bars` 支持 `symbols`、`start_date`、`end_date` 参数；当前公共 EastMoney 分钟源不能可靠回填指定历史日，AkShare adapter 会过滤区间外分钟线，避免把最近分钟数据误写进历史回测窗口。
- `/api/data-sync/imports/minute-bars/template.csv` 和 `/api/data-sync/imports/minute-bars` 已加入，可用外部 CSV 补 `stock_minute_bars` 历史分钟线，支持 `dry_run` 预检查。
- `/api/data-sync/imports/minute-bars/audit-gaps` 和 `/api/data-sync/imports/minute-bars/gap-template.csv` 已加入，用于检查严格尾盘缺口覆盖并生成按缺口待填的分钟线模板。
- 分钟线导入和缺口审计同时支持 `csv_text` 与 `file_path`；`file_path` 仅允许 `data/imports/` 和 `memory/06_backtests/` 下的 `.csv` 文件，避免任意服务器文件读取；分钟线文件导入按批流式写入，适配大型历史 1 分钟 CSV。
- 财报同步可从利润表映射 `publish_date`、扣非净利润，并从现金流量表合并 `operating_cash_flow`、`cash_flow_quality`；回测只使用 `publish_date <= trade_date` 的财报数据，避免未来函数。
- `alphaagent/server/services/vnpy_integration/local_data.py` 和 `/api/vnpy/local-bars` 可把本地 `stock_daily_bars` 查询转换为 vn.py `HistoryRequest`/`BarData` 语义；gateway_name 为 `ALPHAAGENT_LOCAL`。
- `alphaagent/server/services/vnpy_integration/database_import.py` 和 `/api/vnpy/import-minute-bars` 可从当前 vn.py 数据库读取 `Interval.MINUTE` BarData 并导入 AlphaAgent `stock_minute_bars`，用于补严格尾盘回测所需历史分钟线。
- `/api/vnpy/import-minute-bars/gaps` 可按严格尾盘缺口 CSV 批量从当前 vn.py 数据库读取 D+1 尾盘窗口分钟线，写入 AlphaAgent 后返回缺口覆盖审计；当前本机 vn.py SQLite 为空时该接口会返回 `empty`，不会把缺数据误判为完成。
- `alphaagent/server/services/data_providers/tushare_minute_import.py` 和 `/api/data-sync/imports/minute-bars/tushare-gaps` 可按严格尾盘缺口 CSV 调用 Tushare Pro `stk_mins` 历史分钟接口；需要 `TUSHARE_TOKEN` 和分钟数据权限，且会按目标交易日过滤返回行，避免错期数据写入。
- `alphaagent/server/services/backtest/strict_pipeline.py` 和 `/api/backtests/strict-minute-pipeline` 可先审计严格尾盘缺口，审计 `ready` 后才强制运行 `minute_entry_required=true` 的严格回测并返回报告/CSV 信息；缺口未覆盖时返回 `blocked_by_minute_gaps`。
- `/api/data-sync/imports/minute-bars/vendor-manifest` 和 `/api/data-sync/imports/minute-bars/vendor-manifest.csv` 可把严格尾盘缺口 CSV 转成供应商补数清单；字段包括 `vt_symbol`、Tushare `ts_code`、交易日、尾盘窗口、AlphaAgent 导入列说明。

验证：

- 2026-06-11 运行 `uv run pytest tests/alphaagent -q`，结果 150 passed, 1 skipped, 1 warning。
- 2026-06-11 运行 `npm run build`，前端构建通过，仅有 Vite chunk 体积提示。
- 2026-06-11 运行 `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`，编译通过。
- 2026-06-11 服务烟测通过：筛选 `screen ready`，推荐 `recommendations ready`，持仓 `holdings ready 4`，回测报告 `backtest_report ready`，vn.py 状态 `partial` 且未声称 A 股 Gateway 就绪。
- 2026-06-11 使用 Playwright headless 验证 `/quant` 可加载参数表单、导出 CSV、扩展回测表、指数/样本基准对比、样本内/样本外、年度分段、市场环境分段、反过拟合检查、月度收益、个股贡献、最差交易、成交约束、数据质量、模拟持仓和 vn.py 集成状态。
