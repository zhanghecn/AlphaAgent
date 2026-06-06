# Project Structure

## 项目定位

本仓库是 AlphaAgent，一个基于 VeighNa/vn.py 4.4.0 二次开发的 A 股量化交易与 Agent 投研系统。

核心事实：

- 项目外显名称/仓库名是 AlphaAgent。
- 底层 `vnpy/` Python 包名和 Python 发行包名保留，以兼容 vn.py 插件和既有导入路径。
- vn.py core 提供交易系统框架、事件引擎、对象模型、Gateway/Datafeed/Database 抽象。
- 具体交易接口、数据服务、策略应用大量通过独立插件包接入。
- 当前仓库源码本身不内置 A 股全市场免费实时数据。
- 长期方向是服务端化的 A 股量化平台，支持自动量化、智能选股、策略回测、实盘交易和 Agent 辅助决策。

## 关键目录

- `vnpy/`: 核心 Python 包。
- `vnpy/trader/`: 交易核心，包括主引擎、Gateway、Datafeed、Database、对象模型、UI。
- `vnpy/event/`: 事件引擎。
- `vnpy/alpha/`: Alpha 多因子/机器学习投研模块。
- `vnpy/chart/`: K 线图表组件。
- `vnpy/rpc/`: RPC 通讯组件。
- `docs/`: 官方文档源码。
- `examples/`: 官方示例。
- `tests/`: 测试。
- `memory/`: 本地长期上下文地图。

## 官方文档入口

- `README.md`: 项目总览、模块列表、Gateway/App/Datafeed 清单。
- `docs/community/info/introduction.md`: 项目介绍。
- `docs/community/info/gateway.md`: 交易接口加载、连接、合约查询。
- `docs/community/info/datafeed.md`: 数据服务配置和历史数据查询。
- `docs/community/info/database.md`: 数据库配置。
- `docs/community/info/alpha.md`: Alpha 模块和表达式安全说明。
- `docs/community/app/data_manager.md`: 历史数据管理 GUI。
- `docs/community/app/script_trader.md`: 脚本策略交易。
- `docs/community/app/data_recorder.md`: 实时行情录制。
- `docs/community/app/portfolio_strategy.md`: 组合策略。

## 官方示例入口

- `examples/veighna_trader/run.py`: 当前 GUI 启动脚本。
- `examples/download_bars/download_bars.ipynb`: Datafeed 下载历史 K 线并保存到数据库。
- `examples/alpha_research/download_data_rq.ipynb`: RQData 下载 A 股指数成分和历史行情。
- `examples/alpha_research/download_data_xt.ipynb`: XT 下载 A 股指数成分和历史行情。
- `examples/alpha_research/research_workflow_*.ipynb`: Alpha 投研工作流。
