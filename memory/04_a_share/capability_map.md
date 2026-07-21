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

当前官方 4.4.0 README 没有列出中信建投证券专用 Gateway。普通中信建投客户端账号
不能直接用于上述其他券商/柜台插件。

这些用于：

- 连接券商/柜台。
- 查询合约、账号、持仓、委托、成交。
- 订阅实时行情。
- 实盘下单/撤单。

### 当前交易接口适配结论

- `vnpy_tora` 当前版本为 `2026.5.14`，官方包声明支持 Windows/Linux 和
  Python 3.10-3.13；近期更新包含 Linux 安装修复，技术上最匹配 AlphaAgent
  当前 Linux/Python 3.13 服务端环境。
- `vnpy_xtp` 当前版本为 `2.2.32.2.3`，同样声明支持 Windows/Linux 和
  Python 3.10-3.13，但底层 XTP API 与插件更新节奏相对较旧。
- PyPI 对两者的 Python 3.13 均直接提供 Windows wheel；Linux 发布形态为源码包，
  接入前仍需在目标 Docker 基础镜像中验证编译、柜台动态库和网络连通。
- 对个人用户，技术排序不能代替券商准入。TORA/XTP 的生产账号、行情、交易、IP/MAC
  或终端认证权限必须由对应券商明确开通；未取得书面确认前不能视为可用。
- 如果券商只向个人开放 miniQMT/xtquant，可采用独立 Windows 执行器或自定义 Gateway，
  但 `vnpy_xt` 是行情/Datafeed 插件，不是 QMT 交易接口。
- 社区项目 `ruyisee/vnpy_qmt` 可以把 miniQMT 包装成 Gateway，但不是 vn.py 官方插件；
  当前版本 `0.3.3`、最后代码更新为 2024-03，只声明到 Python 3.10，并且仍要求本机启动
  miniQMT。它与 AlphaAgent 的 vn.py 4.4/Python 3.13 兼容性和订单状态恢复尚未验证，
  不能作为生产默认方案。

### 策略与服务接口

- AlphaAgent 当前已运行独立的 `low-suction-swing-paper-v1` 前向纸面策略和
  `/api/low-suction/strategy` 只读视图；它只生成纸面持仓/交割单，明确不调用
  `MainEngine.send_order`，也不代表当前环境已具备 A 股券商交易接口。
- `/api/low-suction/swing-research` 已提供独立研究证据视图，其中突破前主升子合同从
  SHA256 固定报告解析 446 个概念、4,745 个匹配对的 D-10 候选和弱证据。该视图只在
  低吸“研究证据”Tab 加载，明确不改变纸面策略候选、推荐、持仓或成交。
- `MainEngine` 提供统一的连接、订阅、下单、撤单，以及账户、持仓、委托、成交查询；
  对已有独立选股和风控业务的 AlphaAgent，这是最小的执行接入层。
- `ScriptTrader` 适合多股票扫描和同步脚本，但没有回测，不宜单独承担服务端订单账本。
- `PortfolioStrategy` 适合多股票目标仓位和组合调仓，可进行回测和实盘交易。
- `AlgoTrading` 提供 TWAP、Sniper、Iceberg、BestLimit 等委托执行算法。
- `RiskManager` 提供单笔数量、活动委托、重复委托、全天委托/撤单等事前限制。
- `RpcService` 用于可信内网的分布式交易路由；`WebTrader` 在其上提供 REST/WebSocket。
  互联网入口和持有券商凭据的交易进程应隔离部署。

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

仍需向目标券商逐项确认个人准入、资产门槛、费用、实盘/仿真权限、行情等级和服务器/IP
限制；任何接口都不能仅凭安装 Python 包直接交易。
