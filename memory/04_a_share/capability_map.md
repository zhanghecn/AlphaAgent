# A-share Capability Map

## 当前结论

当前仓库和环境不能开箱即用地查看全部 A 股实时数据。

原因：

- vn.py core 不内置 A 股全市场数据源。
- 当前未安装 A 股数据/交易插件。
- 当前 GUI 启动脚本只注册了 `CtpGateway`，面向期货/期权，不是 A 股。

## A 股相关能力由什么承接

### 交易 Gateway

官方 README 中列出的 A 股交易接口：

- `vnpy_xtp`: 中泰 XTP，A 股、两融、ETF 期权。
- `vnpy_tora`: 华鑫奇点，A 股、ETF 期权。
- `vnpy_ost`: 东证 OST，A 股。
- `vnpy_emt`: 东方财富 EMT，A 股。

这些用于：

- 连接券商/柜台。
- 查询合约、账号、持仓、委托、成交。
- 订阅实时行情。
- 实盘下单/撤单。

### 数据服务 Datafeed

官方文档/README 中与 A 股历史数据相关：

- `vnpy_xt`: 迅投研，股票、期货、期权、基金、债券、合约信息、财务信息。
- `vnpy_rqdata`: 米筐 RQData，股票、期货、期权、基金、债券。
- `vnpy_tushare`: TuShare，股票、期货、期权、基金。

这些用于：

- 历史 K 线。
- 部分 Tick。
- 指数成分/合约/财务信息，取决于插件能力和账号权限。

## “看到所有 A 股”需要拆成几个目标

- 看到 A 股证券列表：需要数据源或 Gateway 的合约/证券基础信息。
- 看到实时行情：需要实时行情 Gateway 或支持实时的 Datafeed/Gateway。
- 看到历史 K 线：需要 Datafeed，并写入数据库或 AlphaLab。
- 看到财务/基本面：需要支持财务数据的数据源，例如 XT 或其他外部源。
- 能交易：需要券商 A 股 Gateway 和真实账户/仿真环境。

## 后续实现路线

不改 vn.py core 的前提下：

1. 选择数据源插件。
2. 安装插件。
3. 配置 `datafeed.name` 或注册 Gateway。
4. 用 DataManager/ScriptTrader/MainEngine 验证数据是否进入系统。
5. 再写选股、策略、回测、交易执行。

待用户确认的数据源偏好：

- 尽可能免费。
- 实时性强。
- 能覆盖全 A。

需要进一步验证各插件当前可用性、费用、权限和 Python 3.13 兼容性。
