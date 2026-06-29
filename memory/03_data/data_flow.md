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

## AlphaAgent 板块日线同步路径

当前 AlphaAgent 自研服务的板块日线同步路径是：

1. `alphaagent.server.services.data_sync.run_job("sync_sector_daily_bars")`
2. `DataSyncRunner._run_sync_sector_daily_bars()`
3. `AkShareAdapter.sector_daily_bars(...)`
4. 写入 PostgreSQL `sector_daily_bars`

当前已验证事实：

- `AkShareAdapter.sector_daily_bars()` 优先使用东方财富 `push2his` 直连板块 K 线接口，`secid=90.BKxxxx`，源码 helper 为 `_eastmoney_board_kline()`。
- AkShare THS 板块指数函数仍作为兜底，但不再是首选路径。当前 Docker 镜像里的 `akracer 0.0.14` 缺 x86_64 `libmini_racer.glibc.so`，不能依赖 `py_mini_racer` 路径作为生产主路径。
- `sync_sector_daily_bars` 如果对所有板块读取 0 行，会抛 `DataSyncError` 并记录失败，而不是静默显示成功 0 行。
- `sync_sector_daily_bars` 和 `sync_sector_period_scores` 默认 `sector_limit=0`，即生产定时任务全量覆盖行业/概念板块；不能恢复成 300 的截断默认值，否则概念主线会只更新部分概念。
- `/mainline` 当前产品口径是“概念主线”，不是行业/板块混排。`/api/mainline-replay/timeline`、`snapshot`、`live` 和 `relation` 固定只读题材概念，拒绝外部 `sector_type` 参数，返回 payload 也不再暴露 `sector_type` 分类字段；指数篮子/风格/昨日涨停/近期新高等状态类伪概念会被过滤，行业如“元件、医药生物、化学制药”不进入概念主线。
- 概念主线依赖 `sector_period_scores`、`sector_fund_flows`、`sector_daily_bars`、`stock_daily_bars` 和 `quant_signal_runs`；生产 `sector_daily_bars` 为空会导致概念热度/主线数据与本地不一致。
- `sector_period_scores` 历史评分必须只读取 `as_of_date` 当天及以前的可回放数据。`sector_fund_flows` 来自东方财富实时/当日排行快照，不能稳定回放历史日期；因此只在最新完整交易日用于主线评分，历史回放日期资金流为中性 50 分，并在 evidence 中标记 `sector_fund_flows.latest_only`。
- `/api/mainline-replay/relation` 当前使用 `mainline_replay_relation_v2`：按目标概念最近 20 个评分日，从 `sector_period_scores.return_pct/fund_score` 按共同日期对齐计算行情/资金共振；候选池由“共享成分股概念 + 同窗口活跃评分概念”组成；成分重叠使用完整 `sector_memberships` Jaccard，不再用仅交集候选高估 overlap；返回 `evidence`（共同交易点、共享股票样例、Jaccard、价格/资金相关性）。非概念目标会返回 `unsupported_sector_type`。
- `sector_period_scores` 的宽度、龙头和涨停情绪也必须按 `as_of_date` 取数：宽度/龙头来自该日期的成分股 `stock_daily_bars`，不再读取 `sectors.rise_count/fall_count/leader_*` 当前快照；`stock_events.event_date` 同时兼容 `YYYY-MM-DD` 和 `YYYYMMDD`。
- `sync_sector_period_scores` 未显式传 `as_of_date` 时默认使用最新完整股票日线日期，不使用系统当天日期；周末/休市日不能生成新的主线评分日期。`/api/mainline-replay/timeline` 也只返回有完整股票日线覆盖的评分日期，避免脏的非交易日排到首位。
- 概念主线的成分股涨跌和从成分股点击进入的股票详情必须按所选回放日取 `stock_daily_bars`。缺少该日期日线时显示缺失/错误，不允许用上一交易日或实时公开源冒充历史行情。
- `/api/mainline-replay/live` 是收盘前/盘中概念主线入口：默认取概念 `sector_fund_flows` 的最新 `trade_date`，按即时主力净流入排序，并叠加最近完整交易日的概念 `sector_period_scores` 作为历史评分参考；它只读实时源表，不写 `sector_period_scores`。`/mainline` 前端默认优先显示该实时模式；历史回放仍只读完整日线日期的概念 `sector_period_scores`。
- `/mainline` 第一版“概念指数”不新增派生表：后端在 `live`/`snapshot` 排名项中补充最近 20 个 `sector_daily_bars` 指数点、同一 20 点窗口涨跌幅、`sector_period_scores` 连续热度天数、20 点活跃次数和状态。盘中实时会用今日 `sectors.change_pct` 在最后一个历史指数点后追加 `temporary=true` 的临时指数点；历史回放只读数据库缓存。实时概念榜排序不再按即时资金流截断，而是先拉足概念候选，再按最近 7 个交易日每日指数涨幅前 10 的滚动上榜次数、连续热度、20 点指数涨幅和资金流辅助排序，避免 `存储芯片` 这类连续强势但当天资金流出的概念从默认榜单消失。
- `/api/mainline-replay/sector-stocks` 在所选日期没有完整日线时，只允许对晚于最新完整日线且存在当日分钟线/资金流的盘中日期使用 `stocks` 快照价，并返回 `price_source=intraday_snapshot`；旧历史日期缺日线仍显示缺失，不能拿当前快照冒充历史价格。
- `/api/mainline-replay/sector-stocks` 默认按 `change_pct` 降序返回成分股，资金流只作为附加列。成分股来源是 `sector_memberships`，由 `sync_sector_members` 从板块成分股接口分页写入；2026-06-29 修复了外部源单页最多返回 100 条但 `total` 大于 100 时提前停止的问题，并把板块成员分页保护上限提高到 100 页，避免 `存储芯片`、`创新药`、`融资融券` 等成员被旧 100/2000 条上限截断。同步完成后需要跑 `sync_stock_sector_memberships` 重建反向索引。
- 同步写库语义不是“全量清库重建”：股票/板块日线、资金流、股票/板块清单大多按主键 upsert，只在本次成功拉到同一主键时覆盖；不会自动删除旧来源、已消失的成员关系、未重新拉取日期范围内的旧行，也不会自动重算已经生成的派生评分。
- 当前主线数据最需要显式清理的是 `sector_daily_bars` 的旧来源行：规范来源是 `eastmoney.board_kline`，历史 `akshare.stock_board_*_index_ths` 行如果未被同一 `(sector_id, trade_date)` 的新数据覆盖，会继续被 `sector_period_scores` 优先读取，导致同一算法在本地和生产使用不同输入。
- 成员关系表 `sector_memberships` / `shenwan_industry_members` 是快照关系，但当前同步只 upsert 本次返回成员；某个板块/行业成功同步后，应删除该板块/行业中本次源结果已不存在的旧成员。`stock_sector_memberships` 已通过 `DELETE FROM stock_sector_memberships` 后从 `sector_memberships` 重建，但它继承上游旧成员残留。
- `sector_period_scores` 是派生结果。上游 `sector_daily_bars`、`sector_memberships` 或 `stock_daily_bars` 口径改变后，必须按受影响 `as_of_date/period` 删除或覆盖重算；仅同步源表不会改变已经落库的历史评分。
- `sync_stock_daily_bars` 的增量同步默认带最近 5 天回刷窗口，避免外部行情源事后修正或旧 `change_pct` 残留导致本地/生产历史评分不一致；显式传 `refresh_days=0` 才恢复“最后日期+1”的纯增量。
- `sync_limit_up_pools` 写 `stock_events` 时按 `source + event_type + trade_date` 替换当天池数据，并兼容清理 `YYYYMMDD` / `YYYY-MM-DD` 两种历史日期格式；避免重复涨停事件或缺失当天涨停池影响情绪分。
- 事件/公告/龙虎榜/热度排行属于历史事件或时间序列，不适合简单全表清理；如需去重/刷新，应按 `source + event_type/rank_time/trade_date` 的业务范围清理，避免误删真实历史事件。

## AlphaAgent 分钟线同步路径

当前 `sync_stock_minute_bars` 是分钟线同步的主入口。分钟线不再是历史策略研究默认依赖，主要用于实时/盘中辅助、旧严格分钟报告复核和后续实盘确认：

1. `mode=recent`：保持原有最近分钟线同步，按 `stock_limit`、`limit`、`interval`、`start_date/end_date` 从 AkShare/公开行情适配器读取近端分钟线；这个入口属于通用分钟 K 线同步，不等于回测缺口已经覆盖。
2. `mode=backtest_gaps`：保留为旧严格分钟报告或未来盘中确认补执行日快照，可传 `backtest_id`、`gap_file_path` 或 `gap_csv_text`。默认窗口仍兼容 `tail_entry_start=14:30`、`tail_entry_end=14:30`。
3. 旧量化严格分钟缺口补数统一只支持 `1m` 快照，不再把 `5m/10m` 作为历史主流程周期；通用分钟 K 线导入仍可保留多周期供行情查看使用。
4. `provider=tdx`：使用 TDX 公开行情读取真实历史 `1m`；公开服务器可回溯范围有限，必须以缺口审计结果为准。
5. `provider=tushare`：使用 Tushare Pro `stk_mins`，需要 `TUSHARE_TOKEN` 和分钟数据权限；严格缺口 wrapper 只走 `1m`。
5. `dry_run=true` 默认只预检查/读取，不真实写入；关闭 dry-run 后才写 `stock_minute_bars`。
6. 数据管理页 `/data` 的“股票分钟 K 线”任务已提供参数面板，执行仍调用 `POST /api/data-sync/jobs/sync_stock_minute_bars/run`，不是手工脚本。

2026-06-14 复核 AkShare 分钟线能力：

- 运行中的 Docker API 容器内 AkShare 为 `1.18.64`，`/api/data-sources/akshare/smoke` 通过，A 股列表、日 K、板块、主营构成都可用。
- `AkShareAdapter.stock_bars(..., interval="1m", start_date="2026-06-12", end_date="2026-06-12")` 可通过项目自写 EastMoney 分钟 K 路径返回完整当日 240 根 1 分钟线；`002636.SZSE` 和 `600000.SSE` 均能查到 `2026-06-12 14:30` 分钟 bar。
- 同一路径请求 `002636.SZSE` 的 `2026-06-11`、`2026-01-07`、`2025-10-13` 返回空；请求 `600000.SSE` 的 `2026-01-07` 也返回空。当前不能把 AkShare/东方财富公共分钟线视为可覆盖 2025 至 2026-06-13 全区间严格回测缺口的数据源。
- 当前 `mode=backtest_gaps` 已接入 `akshare`、`tdx`、`tushare` 和 vn.py 本地库导入路径；AkShare 只适合作为近端分钟快照补充，历史缺口仍需要审计确认。

相关源码：

- `alphaagent/server/services/data_sync.py`
- `alphaagent/server/services/data_providers/tdx_minute_import.py`
- `alphaagent/server/services/data_providers/tushare_minute_import.py`
- `frontend/src/pages/DataManagementPage.tsx`

## AlphaAgent 统一批量定时同步

2026-06-18 起，数据同步从「24 个分散单任务 cron」改为「统一的批量增量定时档」：

- 新表 `sync_batch_schedules`（`schema.py`）：一条 = 一个 cron + 有序 `job_ids` + `concurrency` + `enabled`。
- 默认 seed 三档：`tail_preview_14h`（14:00 盘中预备）、`tail_quant_1430`（14:30 尾盘确认）和 `eod_18h`（18:00 盘后补完整日K + 板块 + 涨停池 + 龙虎榜 + 公告 + 财报；涨停池/龙虎榜排盘后慢链路，避免阻塞尾盘实时缓存）。
- `DEFAULT_JOBS` 的 24 个单任务 `schedule_cron` 已全部清空；调度器 `_run_scheduled_jobs` 改为遍历 `sync_batch_schedules`，cron 匹配则触发 `start_sync_batch(job_ids=..., concurrency=..., source="schedule")`。
- 批量执行 `_run_sync_batch`：任务按 `job_ids` 顺序串行（保证数据依赖），单任务失败不再中止整批（终态 `succeeded`/`partial`/`failed`）；基础任务（`sync_stock_list`/`sync_sector_list`）失败时用 `_depends_on` 跳过其下游。
- 日K/分钟K 任务内 `ThreadPoolExecutor(concurrency)` 并发拉全A；真增量：按每只股票最后 bar 日期 `start_date` 续传（`_last_bar_dates_daily`/`_last_bar_dates_minute`），修复旧 `only_missing`「整只跳过」导致老股不更新当日新 bar 的缺陷。
- API：`GET/POST/PATCH/DELETE /api/data-sync/schedules`、`POST /schedules/{id}/run`；前端 `/data` 同步管理 tab 新增「定时计划」区（启停/立即执行/新增自定义档）。
- 数据时效约束：14:00 档拿不到当日完整日K（AkShare 日线收盘后才更新）、龙虎榜（18:00 后）、财报（22:00 后）；这些只在 18:00 档跑。可自定义加更晚档。
- 并发度默认 8（AkShare 公开端限流克制值），每档可配。
- 尾盘预览的默认交易日必须来自晚于最新完整日线的真实 `stock_minute_bars.trade_date`。`stocks.updated_at` 只表示股票清单/快照同步时间，不能当作交易日；没有新分钟线时返回等待状态，不生成也不持久化假预览。

关键源码：

- `alphaagent/server/db/schema.py`（`sync_batch_schedules` 表）
- `alphaagent/server/services/data_sync.py`（`DEFAULT_BATCH_SCHEDULES`、`start_sync_batch`、`_run_sync_batch`、`_run_scheduled_jobs`、`_last_bar_dates_*`、schedule CRUD）
- `alphaagent/server/api/data_sync.py`（schedules 端点）
- `frontend/src/api/dataSync.ts`（`BatchSchedule` + schedule CRUD）、`frontend/src/pages/DataManagementPage.tsx`（`BatchSchedulesPanel`）
- 设计 `requirements/alphaagent_unified_incremental_schedule_plan.md`；执行计划 `requirements/alphaagent_unified_schedule_execution_plan.md`；测试 `tests/alphaagent/test_data_sync_schedule.py`（14 个）

验证：`uv run pytest tests/alphaagent/test_data_sync_schedule.py -v`（全绿）；回归 `uv run pytest tests/alphaagent/ --ignore=tests/alphaagent/test_playwright_research.py`（374 passed）。

2026-06-18 真实联调验证（Docker API 容器）：

- `GET /schedules` 返回两档（`eod_18h` 13任务 / `intraday_14h` 5任务），24 个单任务 cron 全部清空 ✓
- 触发 `intraday_14h`：5/5 `succeeded`（stock_list 4000只 → 分钟线 23520 → 资金流 → 热度 → 涨停池），任务按序、并发拉取、进度追踪 ✓
- 分钟K增量修复：`only_missing` 与 `incremental` 互斥（`only_missing = only_missing and not incremental`）。修复前 `only_missing=True` 会拉「下一批未同步的全量历史」而非当日增量；修复后 `incremental` 主导，对每只活跃股从最后 bar `start_date` 续传，已同步股增量跳过 → `read=0`（不重复拉历史）✓
- 日K增量：`incremental` 默认 True，按每只最后日K日期 `start_date` 续传（trade_date 是 date 类型，eod 档启用）。

2026-06-20 休市日复核（Docker API 容器）：

- 当前完整日线、分钟线和历史候选均停在 `2026-06-18`；`stocks.updated_at` 可能更新到休市日，但不再驱动尾盘预览交易日。
- `GET /api/quant/tail-preview?limit=5` 返回 `status=waiting_for_intraday_data`、`base_daily_date=2026-06-18`、`latest_intraday_date=null`，不会返回假的 `2026-06-19` 候选。
- `GET /api/data-sync/tail-workflow` 在 `/quant` 和 `/data` 可见同步口径：完整日线、分钟线、盘中快照、候选日期、尾盘预览状态，以及 14:00/14:30/18:00 定时任务最近状态。

已知优化点（非阻塞，后续可做）：

- 退市股（如 `001399`/`688797`）每次拉取报「股票数据不存在」被捕获跳过，浪费请求；可在 stocks 表标记退市、`_select_*` 过滤。
- `adapter.stock_bars` 的 `market_cache` 在同步场景理论上不需要（要最新数据），当前靠 `start_date` 区分 cache key 工作正常；如需可加 `use_cache=False` 透传。
- 前端「定时计划」区需 rebuild `alphaagent-web` 容器才能看到（`docker compose up -d --build alphaagent-web`）。
- AkShare 当日分钟线依赖数据源更新（交易时段 14:00 有当日，盘外无）。

## 数据健康仪表盘 + 推荐同步（基于数据更新节奏）

2026-06-21 起，`/data` 默认首页从「尾盘准备」改为「数据健康」仪表盘，解决三个痛点：发版后空库不知从何下手、财报更新不知要同步、定时都是死时间。

- 给 22 个同步任务打静态「更新节奏」标签（不入库、免迁移）：`intraday` 盘中实时 / `eod_daily` 盘后日K / `quarterly` 财报披露季(1/4/7/10月) / `lhb` 龙虎榜18:00后 / `irregular` 低频（板块清单/申万行业/供应链）。
- `data_health()` 合并 `coverage()` + `tail_workflow_status()` + 节奏 + 本地 `stock_daily_bars.MAX(trade_date)` 反推的最新交易日，对每个任务算 `is_stale/severity/reason`，再汇总整体健康度（green/yellow/red）+ 推荐同步清单（只含"现在跑有意义"的任务，按依赖优先级排序）。
- 判定要点：季报非披露季不进推荐（避免 6 月误报"财务落后"）；龙虎榜盘中（now<18）容忍本地停在上一交易日（跨周末最多 3 天），盘后才要求当日；eod_daily 对齐最新交易日，落后≥1 天算 stale。
- 空库（`stocks`/`stock_daily_bars` 两表 count=0）→ overall=red + 醒目空库引导卡 + 「一键核心初始化」(profile=core)。
- 前端 `/data` 默认 `health` tab；尾盘/状态/源 tab 保留不动。推荐同步和单任务同步都是手动触发，不自动跑。

API：

- `GET /api/data-sync/health` → `data_health()`。
- `POST /api/data-sync/batches/run-all` 新增透传 `job_ids`（推荐同步一键全部用；`start_sync_batch` 收到 job_ids 时 profile 自动变 `custom`，已有「上游失败跳下游」保护）。

关键源码：

- `alphaagent/server/services/data_sync.py`：`JOB_CADENCES`/`JobCadence`/`CATEGORY_*`（节奏元数据）、`data_health()`、`_resolve_latest_trade_date`、`_evaluate_job_staleness`、`_is_disclosure_season`、`_is_empty_database`、`_compute_recommended_jobs`。
- `alphaagent/server/api/data_sync.py`：`/health` 端点、`run_all` 透传 `job_ids`。
- `frontend/src/api/dataSync.ts`：`DataHealth`/`DataHealthCategory`/`DataHealthJob` 类型 + `fetchDataHealth()` + `runAllSyncJobs` 加 `job_ids`。
- `frontend/src/pages/DataManagementHealthTab.tsx`（新建）：健康仪表盘，复用 `DataManagementPage` 的 `BatchProgress`/`RunStatusBadge`/`SummaryCard`/`DataNotice`（已 export）。
- `frontend/src/pages/DataManagementPage.tsx`：tab 前置 `health` 默认。

验证：`uv run python -c "from alphaagent.server.services.data_sync import data_health; print(data_health()['overall'])"`（空库返回 health=red/bootstrap.needed=True）；`pnpm -C frontend exec tsc -b`（0 错误）；`pnpm -C frontend build`（通过）。后端改了需重启 API 服务前端 dev 热更新或 rebuild。

已知边界 / 后续可做：

- 最新交易日用本地 `stock_daily_bars.MAX(trade_date)` 反推（最可靠），未接 akshare 交易日历；空库时退化为按 staleness_days 兜底，不阻塞。
- 手动执行为主；「统一晚上自动跑推荐项」留作后续可选增强（19:00 action=recommended_sync 档）。
- 共表任务（financial_quarterly/indicators 都写 stock_financial_reports）首版共用 `MAX(updated_at)` 粗粒度判定。

## AlphaAgent 量化/回测核查路径

当前 `/quant` 候选和回测核查不走 vn.py Datafeed，而是使用 AlphaAgent PostgreSQL 业务表：

1. `GET /api/quant/trading-dates` 从 `stock_daily_bars` 聚合本地真实交易日，并返回 `earliest_trade_date` / `latest_trade_date`；前端候选日期和回测开始日期选择器使用它，只在有日线数据的交易日之间切换。
2. 前端“刷新候选并回测”调用 `POST /api/quant/research-runs` 启动进程内后台任务并轮询 `GET /api/quant/research-runs/latest`：后台自动补齐候选区间、生成统一买卖记录、运行组合回测。`POST /api/quant/screen-runs/range` 是该任务内部/兼容能力：从选中的起始交易日到本地最新交易日逐日生成候选并落库；已存在成功 run 的交易日会跳过，只补缺口，只有最后一个交易日同步到“量化候选”分组。`POST /api/quant/screen-runs` 保留为单日脚本/调试接口。
3. `quant_signal_runs` 记录每次筛选运行；`GET /api/quant/screen-runs` 给前端候选日期选择器叠加显示运行编号和候选数。
4. `quant_recommendations` 支持按 `trade_date` 查询；候选表会显示 `risk_score`、`liquidity_score` 和 `failed_rules`，用于核查当日推荐是否正确。
5. `GET /api/quant/symbols/{vt_symbol}/latest-state` 动态聚合最近全局量化过程，不新增派生表：优先以不早于最新候选日的 `strategy_replay_runs` 日期范围为准，读取同范围 `quant_stock_signals`、`quant_recommendations` 和该股 `strategy_replay_attempts`，返回评分/BUY 信号/候选/买卖记录/收益率的统一状态；如果最新买卖记录早于最新候选日或尚未生成买卖记录，则回退到最近 `quant_signal_runs` 的单日筛选状态，并返回 `latest_available_trade_date` / `is_stale`。
6. 组合回测列表支持 `GET /api/backtests?run_type=portfolio`，前端默认只看组合回测，避免股票详情页的单股回测混进量化页主列表；指定当前公开策略时，读取端按注册表当前策略版本过滤，旧版本回测不会挤掉当前注册版本。普通 `/quant` 和股票详情页会追加 `baseline_only=true`，只取结束到最新本地交易日且起点最早的产品基线组合回测，避免短区间实验或对照回测顶掉全历史基线。
6.1. `GET /api/backtests/{id}/report` 默认是轻量报告，只计算回测首屏需要的指标、最近成交、闭合交易、个股汇总、月度收益、权益尾部、执行质量和方法说明；不扫描全区间日线生成等权基准和稳健性分析。深度验证使用 `include_analysis=true`，用于基准对比、样本内外、市场环境、反过拟合、反未来函数审计和数据质量面板。
7. 新组合回测会写 `backtest_signal_events`，记录每只股票独立状态机下的理论 BUY/SELL 信号；旧回测没有这张流水，需要重跑组合回测。
8. `GET /api/backtests/{id}/equity` 返回该回测实际交易日，前端“信号计划”的开始/结束日期选择器使用它。
9. `GET /api/backtests/{id}/signal-events/amount-preview` 按 `总资金 / 最大持仓数` 做等权金额预览，买入按 100 股整数手，卖出沿用最近一次理论买入数量。
10. `GET /api/backtests/{id}/trades?limit=20&offset=0&order=desc` 分页返回真实组合成交，用于前端“组合最近成交”翻页查看全部。
11. `GET /api/backtests/{id}/drilldown-options` 返回回测钻取的完整日期和股票选项。日期来自 `backtest_daily_equity`，股票来自 `backtest_trades`、`backtest_orders`、`backtest_signal_events` 和 `backtest_daily_positions` 的合集，因此能查到“有理论信号/拒单但没有成交”的股票。
12. `GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=` 追踪某个交易日候选在组合回测中的链路：候选动作、理论信号计划、计划执行日、真实订单、成交、当天现金/持仓市值/总权益和没买原因。优先按 `backtest_signal_events` 关联理论计划；如果旧回测缺理论流水，则按真实订单/成交 `raw.signal_date` 兜底关联，避免真实买入被误报为“未入选/没有理论计划”。若候选存在但未进计划，会额外返回 `not_planned_context`，包含回测首个/最后信号日、股票池名次、候选排名、当天候选 BUY/WATCH 数、当天理论计划数和候选/计划前列。
13. 回测账本金额由 `alphaagent.server.services.backtest.ledger` 计算：买入滑点、卖出滑点、佣金、印花税、100 股整数手、现金不足降档和拒单都在这里；`engine.py` 只负责调用并写订单、成交、持仓和权益曲线。
14. 理论信号与真实订单关联由 `alphaagent.server.services.backtest.signal_plan` 计算：按 `vt_symbol + execute_date/trade_date + side` 匹配，输出 `linked_order_id`、`linked_order_status`、`linked_order_reason`、`plan_status` 和 `plan_status_label`，供信号流水和候选追踪复用。
15. 回测订单、信号和候选追踪 API 行会返回 `reason_label` / `linked_order_reason_label`，用于前端显示“入场条件未触发”“现金不足”等中文原因。
16. 组合回测加载日线时会从用户开始日前额外加载预热历史 K 线，避免 MA60、60 日回撤等指标在回测初期因样本不足而缺失；但权益、持仓和交易记录仍只从用户选择的开始日期开始。
17. 历史组合回测默认使用 `legacy_next_open`：D 日收盘信号，D+1 日线开盘买入/卖出，默认最大持仓 10、BUY 候选前 20 名、收益率和最大回撤为主要观察指标。
18. 普通量化产品路径只公开 `mainline_dragon_pullback`；`GET /api/quant/strategies` 返回单一公开策略，旧策略仅保留内部兼容和旧报告/对比接口。
19. 组合模拟只按候选排序、D+1 执行价、涨跌停、现金、组合上限和当前卖点生成真实成交流水；旧的“强信号挤出已有票”规则已删除，不再作为当前产品路径或候选质量解释。
20. 股票详情页 K 线标记优先来自产品基线组合回测：先取 `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true` 当前版本全历史基线，再用 `GET /api/backtests/{id}/symbols/{vt_symbol}` 加载真实组合订单/成交/收益标记，并用 `GET /api/backtests/{id}/signal-events?vt_symbol=` 叠加同一回测内的理论 BUY/SELL 信号计划；已关联真实成交的同日理论 BUY 会被前端抑制，避免同一信号重复显示。股票详情收益口径区分“闭合收益率”“当前浮盈率”和“盯市合计”，避免持有中盈利票被历史闭合亏损误读为整票亏损。`latest-state` 的全局买卖记录和 BUY 信号只作为没有组合执行记录时的兜底。

注意：`backtest_signal_events` 是理论信号计划，用于核查“历史上有没有买点/卖点”；真实组合资金曲线仍以 `backtest_trades`、`backtest_daily_equity` 和 `backtest_daily_positions` 为准。

当前量化状态：

- 本地日线交易日范围：`2025-03-26` 至 `2026-06-16`；`2026-06-16` 本地日线覆盖约 `1302` 只股票，低于正常全市场覆盖。
- 当前公开策略代码为 `mainline_dragon_pullback / 0.1.21`，低吸洗盘和经典龙回头是同一公开策略下的内部 setup；主要字段包括 `setup_type`、`entry_setup`、`low_suction_days`、`support_hold_days`、`ma_convergence_pct`、`low_suction_buildup_score`、`stealth_low_suction_score`、`low_suction_launch_confirmed`、`score_notes` 和 `score_breakdown`。
- 候选默认只展示前 `20` 个推荐；组合执行按默认最大持仓 `10`、BUY 候选前 `20` 做模拟买卖。候选、自动回测和成交追踪是内部链路，不再作为多个用户主操作拆开理解。
- 候选、股票详情、量化候选分组和组合执行 action 使用同一可执行入场口径：`entry_signal` 是原始诊断字段，只有 `executable_entry_signal=true` / `action=BUY` 才展示为 BUY、计入 BUY 次数并进入买入计划；硬信号低于 `min_entry_score` 或有失败规则时展示 `WATCH`。默认产品口径下，低吸蓄势未确认启动是质量/阶段标签，不是硬拒买；只有显式开启 `require_low_suction_launch_confirmation` 研究开关时才作为拒买规则。回测缓存和全局买卖记录也不再直接把原始 `entry_signal=true` 当作可买入。
- `/quant` 候选表直接显示“为什么这个分数”，并通过 `score_notes` / `score_breakdown` 解释总分来源、低吸蓄势加分和失败规则；候选行明确写出“总分按分项贡献相加后扣风险”，并优先露出“低吸蓄势”贡献，避免用户把连续低吸理解成额外策略或额外页面。
- `/quant` 普通视图只保留“候选/回测”两个入口；运行状态只显示覆盖区间、完成进度、最新候选数和自动回测编号，不展示“新生成/跳过/同步”等内部流水账。回测页首屏读取轻量报告并默认打开“交易归因”，用户打开“验证”子 tab 后才加载完整分析和数据质量审计，避免因为重分析耗时误判为“没数据”。
- `/quant` 回测页普通子入口只保留“验证 / 交易归因 / 收益分段”；全股票理论信号计划不再作为普通 tab 暴露。候选行的“回测成交”追踪和股票详情 K 线仍会使用同一底层信号/订单数据解释买入、拒单和卖出。
- `/stocks/:vtSymbol` 在“策略复盘”里固定显示“为什么这个分数”，即使该票在最新组合回测里已有实际成交，也能看到评分日、总分、状态、低吸蓄势天数、均线收敛、低吸蓄势分、评分构成，以及“低吸蓄势是同一回踩低吸策略里的连续加分”的解释。
- 东山精密 `002384.SZSE` 在 `0.1.21` 线索中修复了 `2026-03-27` 至 `2026-04-01` 低吸段：低吸天数从 `1/2/3/4` 累计，`2026-04-01` 为可执行 `stealth_low_suction` BUY，`low_suction_launch_confirmed=true`。2026-06-22 复核 `2026-06-12`：逐日评分为 `stealth_low_suction`，低吸蓄势 `4` 天，总分 `95.81`，`low_suction_launch_confirmed=false` 但默认产品口径仍为 `BUY / executable_entry_signal=true`；候选质量复核应按该信号 D+1 开盘独立入场并按当前卖点退出，不再用组合成交约束解释买点质量。
- 当前完整全历史组合回测为 `mainline_dragon_pullback / 0.1.21` 的 `backtests #175`：范围 `2025-03-26` 至 `2026-06-17`，收益约 `+81.36%`，最大回撤约 `-15.59%`，买入/卖出/持仓中 `224 / 214 / 10`。它较 `#172/#169` 改善收益和回撤，但仍需多年 walk-forward、参数敏感性和市场分层验证。
- 卖出侧失败边界：`0.1.19/#173` 买后早期连续破位止损收益约 `+54.40%`、最大回撤约 `-19.79%`；`0.1.20/#174` 买入当天硬破位次日撤退收益约 `+51.51%`、最大回撤约 `-19.00%`。二者已撤回，当前默认代码是 `0.1.21`。
- `/quant` 已切换为后台研究任务接口；任务状态是进程内内存状态，服务重启后 `GET /api/quant/research-runs/latest` 可能返回空，但已落库候选、买卖记录和回测仍按普通 API 可查。短区间任务如果日线不足，会显示具体失败原因，避免只看到“组合回测失败”。

2026-06-14 回测钻取复核：

- `#62` 的 `GET /api/backtests/62/drilldown-options` 返回 `date_count=85`、`symbol_count=61`，日期覆盖 `2026-02-02` 到 `2026-06-12`。
- `/quant -> 回测 -> 交易归因` 日期下拉和股票下拉已改用该接口；旧 `report.equity_tail/recent_trades` 推导只作为接口不可用时兜底。
- 浏览器验证可选中 `000338.SZSE` 这类“有拒单但无成交”的股票，并显示中文原因。

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
