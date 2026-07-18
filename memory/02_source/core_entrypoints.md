# Core Source Entrypoints

## vn.py Core

- `vnpy/trader/engine.py`: `MainEngine`，管理 Gateway、App、订阅、委托和查询。
- `vnpy/trader/gateway.py`: 交易接口基类。
- `vnpy/trader/datafeed.py`: `get_datafeed()` 和历史数据服务动态加载。
- `vnpy/trader/object.py`: Tick、Bar、Contract、HistoryRequest、OrderRequest 等对象。
- `vnpy/alpha/lab.py`: AlphaLab 本地因子/模型研究工作流。

不要为 AlphaAgent 业务修改 `vnpy/`。A 股实时和交易能力仍由实际安装配置的插件提供。

## AlphaAgent Service

- `alphaagent/server/main.py`: FastAPI 应用、生命周期、数据同步与保留产品预热。
- `alphaagent/server/api/router.py`: 当前路由注册。
- `alphaagent/server/db/schema.py`: 保留业务表 metadata。
- `alphaagent/server/db/legacy_product_cleanup.py`: 固定 23 张旧产品表的一次性删除清单。
- `alphaagent/server/services/data_sync.py`: 数据健康、任务、批次和 schedule。
- `alphaagent/server/services/mainline_replay.py`: 概念主线计算。
- `alphaagent/server/services/market_context.py`: 点时大盘上下文。
- `alphaagent/server/services/market_timing/`: 金/银手指和大盘择时。
- `alphaagent/server/services/limit_up/`: 打板研究、历史账本、实时扫描和前向证据。
- `alphaagent/server/services/low_suction/`: 独立低吸历史研究；包含数据门禁、主升
  Top3、事件/分钟执行、严格历史输入、BaoStock 重建审计、Tushare DC 历史成员探测
  和题材资格研究，不导入打板策略规则。
- `alphaagent/server/services/execution/cash_ledger.py`: 中立的现金成交数学，仅由保留产品显式使用。

旧 `services/quant`、`services/backtest`、`services/portfolio` 和
`services/simulation` 已删除。

## Frontend

- `frontend/src/App.tsx`: 页面路由。
- `frontend/src/components/AppShell.tsx`: 当前产品导航。
- `frontend/src/pages/ShortTermResearchPage.tsx`: `/short-term` 入口。
- `frontend/src/pages/LimitUpPage.tsx`: 当前短线研究内容。作战指挥台布局：OpsFlowRail 作战步进器（`frontend/src/features/limitUp/OpsFlowRail.tsx` + `opsFlow.ts`）+ 门禁指挥条 + 折叠轨迹面板；回测视图 PanelHead 编号章节 01-06。
- `frontend/src/pages/MainlineReplayPage.tsx`: 概念主线。
- `frontend/src/pages/MarketTimingPage.tsx`: 大盘择时。
- `frontend/src/pages/DataManagementPage.tsx`: 健康、同步、打板证据和显式分钟缺口。
