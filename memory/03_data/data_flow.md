# Data Flow

这个文件只记录当前有效的数据路径和数据口径。旧同步事故、单次生产验证和历史回测状态不要放这里；需要复核旧过程时看对应报告或 git 历史。

## vn.py Data Paths

vn.py 核心把数据分成四类：

- 合约/证券基础信息。
- 实时 Tick 行情。
- 历史 K 线/Tick。
- 财务、基本面、指数成分等研究数据。

实时行情路径：

1. 安装并注册 Gateway 插件。
2. `MainEngine.connect()` 连接。
3. Gateway 查询/推送合约信息，产生 `ContractData`。
4. `MainEngine.subscribe()` 订阅标的行情。
5. Gateway 推送 `TickData`。
6. `OmsEngine` 缓存最新 tick，可通过 `get_tick()` 或 `get_all_ticks()` 查询。

历史数据路径：

1. 安装 Datafeed 插件，例如 `vnpy_rqdata`、`vnpy_xt`、`vnpy_tushare`。
2. 配置 `SETTINGS["datafeed.name"]` 及账号/token。
3. 使用 `get_datafeed()` 获取数据服务实例。
4. 构造 `HistoryRequest`。
5. 调用 `query_bar_history()` 或 `query_tick_history()`。
6. 保存到数据库或 AlphaLab。

相关源码和文档：

- `vnpy/trader/engine.py`
- `vnpy/trader/gateway.py`
- `vnpy/trader/datafeed.py`
- `vnpy/trader/object.py`
- `docs/community/info/datafeed.md`
- `examples/download_bars/download_bars.ipynb`
- `examples/alpha_research/download_data_rq.ipynb`
- `examples/alpha_research/download_data_xt.ipynb`

## AlphaAgent Stock Data

AlphaAgent 自研服务的股票日线同步不走 vn.py Datafeed，路径是：

1. `alphaagent.server.services.data_sync.run_job("sync_stock_daily_bars")`
2. `DataSyncRunner._run_sync_stock_daily_bars()`
3. `AkShareAdapter.stock_bars(..., interval="1d")`
4. 写入 PostgreSQL `stock_daily_bars`

当前有效事实：

- 股票日线优先使用腾讯 `newfqkline` 接口，helper 为 `_tencent_stock_kline_full()`。
- 腾讯成交额字段单位为“万元”，入库前换算为“元”。
- `stock_daily_bars.volume` 常见单位为“手”；旧数据缺 `turnover` 时，量化流动性兜底按 `close * volume * 100` 估算成交额。
- `sync_stock_daily_bars` 支持 `symbols` 定向重跑，也支持增量同步和最近交易日回刷。

## AlphaAgent Sector And Mainline Data

板块日线同步路径：

1. `run_job("sync_sector_daily_bars")`
2. `DataSyncRunner._run_sync_sector_daily_bars()`
3. `AkShareAdapter.sector_daily_bars(...)`
4. 写入 PostgreSQL `sector_daily_bars`

当前有效事实：

- `AkShareAdapter.sector_daily_bars()` 优先使用东方财富 `push2his` 板块 K 线接口，`secid=90.BKxxxx`，helper 为 `_eastmoney_board_kline()`。
- AkShare THS 板块指数函数只作为兜底；Docker x86_64 环境不能依赖 `py_mini_racer` 路径作为生产主路径。
- `sync_sector_daily_bars` 如果对所有板块读取 0 行，会抛 `DataSyncError` 并记录失败，不静默成功。
- `sync_sector_daily_bars` 和 `sync_sector_period_scores` 默认 `sector_limit=0`。当前默认 18:00 定时保留 `sync_sector_period_scores`，`sync_sector_daily_bars` 因公共板块 K 线源覆盖不稳定，不放入默认定时链路，避免每天把批次标成失败；需要时可手动跑。
- `/mainline` 产品口径是“概念主线”，不是行业/板块混排。主线 API 固定只读题材概念，过滤指数篮子、风格、昨日涨停、近期新高等状态类伪概念。
- `sector_period_scores` 历史评分必须只读取 `as_of_date` 当天及以前可回放数据；实时/当日资金流不能稳定回放历史日期。
- `/api/mainline-replay/live` 是盘中概念主线入口，只读实时源表，不写 `sector_period_scores`。
- `/api/mainline-replay/snapshot` 和 `timeline` 只读完整日线日期的概念 `sector_period_scores`。
- `/api/mainline-replay/relation` 使用共同日期价格/资金相关性和完整 `sector_memberships` Jaccard 计算关联概念。
- `/api/mainline-replay/sector-stocks` 在旧历史日期缺日线时不能用当前快照冒充历史价格；只有晚于最新完整日线且存在当日分钟线/资金流的盘中日期可返回 `price_source=intraday_snapshot`。
- `/api/mainline-replay/sentiment-cycle` 是 `/mainline` 情绪周期图数据源：历史点从完整 `stock_daily_bars` 计算涨跌家数、涨跌停、炸板代理、连板高度和晋级率；盘中点仅在可用时用 `stocks` 快照和 `stock_minute_bars` 高点作临时投影，不写回 `sector_period_scores`。

数据维护风险：

- 同步写库通常是 upsert，不是全量清库重建；旧来源行、旧成员关系和已生成派生评分不会自动消失。
- 规范板块日线来源是 `eastmoney.board_kline`。历史旧来源行如果未被同一主键覆盖，可能继续影响 `sector_period_scores`。
- `sector_memberships` / `shenwan_industry_members` 是快照关系；同步成功后应清理本次源结果已不存在的旧成员，并重建反向索引 `stock_sector_memberships`。
- `sector_period_scores` 是派生结果；上游日线、成员或个股日线口径改变后，必须按受影响日期/period 删除或覆盖重算。

## Minute Data

`sync_stock_minute_bars` 是分钟线同步主入口。分钟线不再是历史策略研究默认依赖，主要用于实时/盘中辅助、旧严格分钟报告复核和未来实盘确认。

模式：

- `mode=recent`: 同步近端分钟 K 线。
- `mode=backtest_gaps`: 兼容旧严格分钟报告或未来盘中确认，可按回测缺口补执行日快照。
- `provider=tdx`: 使用 TDX 公开行情读取真实历史 `1m`，回溯范围有限。
- `provider=tushare`: 使用 Tushare Pro `stk_mins`，需要 `TUSHARE_TOKEN` 和分钟数据权限。
- `dry_run=true` 默认只预检查/读取，不真实写入。

约束：

- 普通历史主流程不再依赖 14:30/分钟线。
- 旧严格分钟缺口补数统一只支持 `1m` 快照；通用分钟 K 线导入可保留多周期供行情查看。
- AkShare/东方财富公共分钟线可用于近端日期，但不能视为覆盖长历史严格回测缺口的数据源。

## Batch Sync And Health

统一批量定时同步使用 `sync_batch_schedules`，默认由
`alphaagent/server/services/data_sync.py` 的 `DEFAULT_BATCH_SCHEDULES`
写入/更新数据库：

- `tail_quant_1430`: 14:30 实时尾盘量化结果；只跑分钟线、个股/板块资金流和热度等快任务，然后生成缓存，不跑慢的全 A `sync_stock_list`。
- `eod_18h`: 18:00 盘后完整日 K、板块、涨停池、龙虎榜、公告、财报等。

11:30、14:00、15:00 旧盘中缓存档已停用；启动种子逻辑会把
`intraday_noon_1130`、`tail_preview_14h`、`intraday_close_1500`
以及更早的 `intraday_14h`、`tail_prepare_14h` 标记为禁用，避免页面读取到
14:00 这类与 14:30 实时尾盘量化不一致的半成品。

批量执行按 `job_ids` 顺序串行，单任务失败不再中止整批；基础任务失败时下游会跳过。日 K/分钟 K 内部按股票并发增量续传。

数据健康入口：

- `GET /api/data-sync/health`: 数据健康和推荐同步。
- `POST /api/data-sync/batches/run-all`: 批量同步，可传 `job_ids`。
- `/data` 默认应优先展示数据健康/同步状态，而不是要求用户理解底层 job。

## Quant Data Path

`/quant` 候选和回测核查使用 AlphaAgent PostgreSQL 业务表，不走 vn.py Datafeed。

核心表/接口路径：

- `stock_daily_bars`: 本地真实交易日和日线。
- `quant_signal_runs`: 每次筛选运行。
- `quant_recommendations`: 候选 TopN。
- `backtest_signal_events`: 理论 BUY/SELL 信号计划。
- `backtest_orders` / `backtest_trades` / `backtest_daily_equity` / `backtest_daily_positions`: 真实组合执行账本。
- `GET /api/quant/trading-dates`: 本地真实交易日范围。
- `POST /api/quant/research-runs`: 刷新候选并研究。
- `POST /api/quant/screen-runs/range`: 补齐区间候选。
- `GET /api/backtests?run_type=portfolio`: 组合回测列表。
- `GET /api/backtests/{id}/candidate-trace`: 单股单日候选、计划、订单和成交链路。
- `GET /api/backtests/{id}/candidate-trade-quality-report`: 候选独立买卖质量报告。

当前产品口径：

- 普通量化产品路径只公开 `mainline_dragon_pullback`。
- 候选质量主口径是全历史交易日每日 Top5/Top10/Top20，D 日 BUY 候选按 D 日收盘价买入，D+1 收盘收益作为主胜率和主收益；D+2/D+3 是否值得格局只作为辅助标签。
- `GET /api/backtests/{id}/candidate-trade-quality-report` 会按买点区域、金/银手指窗口、行情阶段、月份、重点区间和 D+1 涨跌形态分桶；`alphaagent/server/services/backtest/tail_entry_next_day_label.py` 负责生成只读标签。
- 组合模拟只按候选排序、D+1 执行价、涨跌停、现金、组合上限和当前卖点生成真实成交流水；组合层不能反向解释候选质量。
- 股票详情页 K 线标记优先来自当前公开策略对该股的独立复盘；组合真实成交只作执行层复核。

## Financial Visibility

股票详情页和回测评分共用 `alphaagent.server.services.quant.financials` 的历史可见性口径：

- `financial_coverage_summary(session, vt_symbol, trade_date)` 返回本地财报数、回测可用数、缺披露日数、晚于回测日披露数、最新披露日和最近可用报告日。
- `financial_scores_from_rows_by_symbol(rows_by_symbol, trade_date)` 只使用 `publish_date <= trade_date` 的第一条本地财报打分。
- 股票详情页看到“现在可查”的财报，不代表历史回测当天可用；页面必须显示财报口径说明。

## DataManager

vn.py DataManager 仍是官方历史数据 GUI 能力，依赖已配置 Datafeed 或能提供历史数据的 Gateway。

相关文件：

- `docs/community/app/data_manager.md`
- 插件：`vnpy_datamanager`
