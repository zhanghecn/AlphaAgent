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
