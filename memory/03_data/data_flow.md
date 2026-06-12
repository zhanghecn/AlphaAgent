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
