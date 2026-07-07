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
- 提供日线组合回测和 `/api/backtests/{id}/report` 回测表接口；组合执行诊断仍可用 `legacy_next_open / strict_entry=true` 表示 D 日收盘可见候选生成 D+1 计划、D+1 按日线开盘价执行。`/quant` 候选质量主口径已经独立为 D 日收盘价买入、D+1 收盘验证；`strict_1430` 和 `tail_close_hybrid` 保留为实时/分钟数据层和旧报告兼容能力。
- 股票详情页 `/stocks/:vtSymbol` 的单股信号复盘会把 BUY 信号、买入拒绝和买卖成交分开显示在 K 线上；最新单股回测会额外读取 `/api/backtests/{id}/audit`，因此即使 BUY 信号未成交也能看到信号日标记和执行日拒绝原因。
- 单股信号复盘不再展示模拟账户金额、现金、权益、成交金额、数量、费用或盈亏金额；收益统计改为按成交价格直接计算闭合交易收益率：`sell_price / buy_price - 1`，汇总使用单笔收益率连乘。
- `/api/backtests/{id}/minute-coverage` 返回 14:30 覆盖摘要，状态包括 `ready`、`mixed_proxy`、`missing_snapshots`、`strategy_not_triggered` 和 `empty`；前端 `/quant` 的“14:30覆盖”面板使用它快速判断某次回测是否可按真实 14:30 成交解读。
- `alphaagent/server/services/backtest/queries.py` 负责回测读侧 helper，包括成交分页、权益曲线、日期/股票详情、候选追踪、审计事件数据读取、交易归因日期/股票选项聚合和拒单/信号原因中文标签；`engine.py` 仍保留兼容 wrapper 给现有 API 和测试使用。
- `alphaagent/server/services/backtest/schemas.py` 负责回测参数和账本数据结构，包括 `BacktestParams`、`MinuteBar`、`Position`、`Trade` 和 `ScoreContext`；`engine.BacktestParams` 保持兼容导出。
- `alphaagent/server/services/backtest/reports.py` 负责回测报告纯函数，包括扩展交易指标、成交真实性检查、报告 CSV、参数网格 CSV 和严格 14:30 缺口 CSV 内容生成；`engine.py` 保留同名 wrapper。
- `/api/backtests/{id}/report` 当前返回扩展回测表：样本覆盖率、扩展交易指标、样本等权和指数基准对比、样本内/样本外分段、年度分段、市场环境分段、成本压力测试、随机样本基准、反过拟合诊断、月度收益、个股贡献、最差交易、订单未成交原因、权益尾部和数据质量快照。
- `/api/backtests/{id}/report.csv` 返回可下载 CSV 回测表，包含摘要、核心指标、样本覆盖、扩展交易指标、基准对比、分段、反过拟合检查、月度、个股、最差交易、交易明细、订单统计和数据质量。
- 量化、回测、持仓、模拟服务会在直接调用时创建 AlphaAgent 业务表，不依赖 API lifespan 单一路径。
- 提供持仓分组、自选观察、量化候选、模拟持仓和黑名单基础能力。
- 提供本地模拟账户、模拟订单、模拟成交、模拟持仓和风险事件查询。
- 前端 `/quant` 页面展示量化候选、回测表和模拟持仓；用户主操作是“刷新候选并回测”，后台内部从起始交易日到本地最新交易日逐日落库候选、生成买卖记录并运行组合回测。回测页只用于查看报告、导出 CSV 和审计/钻取能力。
- `stock_minute_bars` 和 `sync_stock_minute_bars` 已加入，用于执行日 14:30 快照的分钟级入场验证；普通量化入口和 `/data` 回测缺口补数表单只展示 14:30 单点快照。当前单股历史复盘口径下，历史日期缺 14:30 分钟线可用执行日日线收盘价代理尾盘价格，今日缺快照才等待数据补齐/拒绝；若代理价距离信号日 MA5 超过容忍度，会标记 `tail_entry_not_triggered` 而不是误写成缺分钟。`tail_close_hybrid` 研究对比模型缺分钟线时也会标记 `daily_close_proxy`；旧 14:30-14:57 窗口仅保留后端兼容/历史排查。
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

验证入口：

- 后端编译：`uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`
- 量化测试：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`
- 前端构建：`pnpm --dir frontend run build`
- 当前回测证据索引：`memory/06_backtests/README.md`
