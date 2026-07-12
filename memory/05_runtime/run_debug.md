# Run and Debug

这个文件只记录当前有效的运行、调试和验证入口。历史回测结论看 `memory/06_backtests/`；生产事故复盘、长命令输出、截图清单、原始 JSON、CSV 和日志不作为长期记忆保留。

## Current State

- 项目外显名称是 AlphaAgent，Python 发行包名和源码包目录仍保留 `vnpy`，用于兼容 vn.py 插件。
- 官方桌面 GUI 入口仍是 `examples/veighna_trader/run.py`，但当前不能视为 A 股实盘或全市场实时行情已接入。
- AlphaAgent Web/API 是当前主要研发入口，包含 A 股数据同步、量化候选、组合回测、股票详情、持仓和数据管理。
- 普通历史主流程是日线 D+1：D 日收盘产生候选，D+1 按日线开盘价执行买入/卖出。14:30/分钟线只保留为实时、盘中确认、分钟数据同步和旧报告兼容能力。
- 当前策略状态和实验结论以 `memory/06_backtests/README.md` 和 `memory/06_backtests/strategy_optimization_ledger.md` 为准。

## Local Run

桌面 vn.py GUI：

```bash
uv run python examples/veighna_trader/run.py
```

API：

```bash
uv run uvicorn alphaagent.server.main:app --host 0.0.0.0 --port 8000
```

前端/全栈本地默认走 Docker Compose，入口 `http://localhost:8080`，不再把 Vite `5173` 直连作为默认验证环境。

```bash
docker compose up --build
```

常用页面：

- `/quant`: 刷新候选并研究；展示候选 Top20 独立买卖质量、候选解释和回测归因。
- `/data`: 数据健康、同步状态、批量同步、定时计划、分钟线/日线同步。
- `/portfolio`: 自选分组、量化候选分组、模拟持仓。
- `/stocks/:vtSymbol`: 股票详情、财报口径、策略复盘和买卖点。
- `/mainline`: 概念主线、实时/历史回放、概念指数和成分股。

## Docker

AlphaAgent 容器化由三个自研镜像 + postgres/redis 组成，统一入口是 Go 网关：

- `alphaagent-gateway`: 唯一对外端口，处理管理员登录、JWT 和反向代理。
- `alphaagent-api`: FastAPI，仅内部 `expose 8000`。
- `alphaagent-web`: Vite build + nginx，仅内部 `expose 80`。
- `postgres` / `redis`: 业务数据和缓存。

本地全栈：

```bash
docker compose up --build
# 打开 http://localhost:8080，用 ADMIN_USERNAME/ADMIN_PASSWORD 登录
```

日常改前端代码后只 rebuild web：

```bash
docker compose up -d --build alphaagent-web
```

部署：

```bash
cd deploy
./docker-deploy.sh
docker compose -f docker-compose.local.yml up -d
```

发版：推 `v*` tag，CI 构建并发布 `alphaagent-api/web/gateway` 到 GHCR。

约束：

- 不要恢复 api/web 对外 `ports:` 映射，必须经网关登录访问。
- 不要把根目录 `.env` 改回 `host.docker.internal`；容器应使用 Compose 内部数据库。
- 日常不要使用 `docker compose build --no-cache`，除非排查基础镜像或依赖缓存。
- `JWT_SECRET` 必须 ≥32 字节，否则网关启动 fail-fast。

## Quant Debug

统一策略测试通道：

```bash
uv run pytest tests/alphaagent/test_quant_strategy_acceptance.py -q
```

说明：

- 当前 shell 没有 `DATABASE_URL` 时会跳过。
- 快速通道验证当前公开策略链路、no-cache 假设和基础指标。
- 完整慢测需显式设置 `ALPHAAGENT_RUN_FULL_STRATEGY_ACCEPTANCE=1`。
- 测试通道固定 `reuse_signal_cache=false`、`persist=false`、`exclude_from_product_baseline=true`，不会写入真实产品基线。

常用接口：

- `GET /api/quant/trading-dates`
- `POST /api/quant/research-runs`
- `POST /api/quant/screen-runs/range`
- `GET /api/quant/screen-runs`
- `POST /api/backtests`
- `GET /api/backtests?run_type=portfolio`
- `GET /api/backtests/{id}/report`
- `GET /api/backtests/{id}/candidate-trade-quality-report`
- `GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=`
- `GET /api/backtests/{id}/setup-market-exit-audit`
- `GET /api/backtests/{id}/path-diagnostics`

当前基线和证据索引见 `memory/06_backtests/README.md`。

## Data Debug

常用接口：

- `GET /api/data-sync/health`: 数据健康和推荐同步。
- `GET /api/data-sync/tail-workflow`: 实时尾盘量化状态。默认只展示
  14:30 实时尾盘量化、18:00 盘后同步和 21:30 晚间日线补全；旧
  11:30、14:00、15:00 盘中缓存档会被启动种子逻辑禁用。
- `GET /api/quant/tail-preview?limit=50`: 今日实时尾盘量化结果，只读，不写历史候选。
- `POST /api/data-sync/tail-workflow/run-tail-quant`: 手动执行 14:30 实时尾盘量化批次。
- `POST /api/data-sync/batches/run-all`: 一键同步批次。
- `GET /api/data-sync/batches/latest`: 最新批次进度。
- `POST /api/data-sync/jobs/sync_stock_daily_bars/run`: 同步日线，可用 `symbols` 定向回填。
- `POST /api/data-sync/jobs/sync_stock_minute_bars/run`: 分钟线同步。
- `POST /api/data-sync/imports/minute-bars/audit-gaps`: 审计严格 14:30 缺口覆盖。

当前数据口径和维护风险见 `memory/03_data/data_flow.md`。

验证重点：

- 生产和本地 `/quant` 不一致时，先查 `GET /api/quant/trading-dates` 的 `latest_complete_trade_date` 和最新日期 `symbol_count`，历史候选默认只应读完整日线日期。
- 18:00 公共源可能只发布部分当日日线；全市场日线同步会丢弃低于完整阈值的最新日期，21:30 再自动补全重试。
- `QueuePool limit ... timed out` 优先检查是否有超时同步线程晚返回继续写库、生产连接池配置是否低于 `20 + 20` overflow，以及是否同时运行同步批次和策略研究。

## Mainline Debug

常用接口：

- `GET /api/mainline-replay/live?limit=80`: 今日实时概念主线。
- `GET /api/mainline-replay/snapshot?date=YYYY-MM-DD&limit=80`: 历史概念主线。
- `GET /api/mainline-replay/sentiment-cycle?date=YYYY-MM-DD&lookback=60`: 短线情绪周期图，返回情绪分、阶段、涨跌家数、涨跌停、炸板代理、连板高度、晋级率和区间摘要。
- `GET /api/mainline-replay/timeline`: 可回放日期。
- `GET /api/mainline-replay/relation?sector_id=&date=`: 关联概念。
- `GET /api/mainline-replay/sector-stocks?sector_id=&date=&limit=`: 概念成分股。

验证重点：

- 生产和本地主线不一致时，优先查 PostgreSQL 数据覆盖和派生评分，不先怀疑前端资源。
- 历史回放必须按 `as_of_date` 截断；盘中实时只能使用实时源表和最近完整日线参考。
- 概念主线只展示题材概念，过滤行业、指数篮子和状态类伪概念。
- 情绪周期历史点只读完整 `stock_daily_bars`；盘中点只作 `stocks` 快照和 `stock_minute_bars` 高点投影，不写入历史评分。
- `/mainline-replay/timeline`、`live` 和 `sentiment-cycle` 有进程内短 TTL 缓存：timeline/历史情绪约 5 分钟，live/盘中情绪约 30 秒。冷请求仍会扫库，命中后用于页面刷新和切回加速。
- 前端情绪周期曲线是交互图：鼠标移动显示交易日和关键值，点击锁定交易日明细；锁定后才请求 20/60/120 日版本热度，避免首屏额外加载。

## Limit-up Debug

常用接口：

- `GET /api/limit-up/live`: 只读每分钟后台保存的最新实时信号，不访问外部行情；交易时段超过 90 秒未更新会 fail-closed。`POST /api/limit-up/live/refresh` 仅供调度/显式采集使用。
- `GET /api/limit-up/signals?date=YYYY-MM-DD&as_of=`: 历史快照或历史代理；无严格快照的代理会附加只使用该日前已闭合结果的历史胜率、平均净收益、硬亏率和样本数。
- `GET /api/limit-up/history/status` / `POST /api/limit-up/history/rebuild`: 全历史账本状态和后台重建。
- `GET /api/limit-up/history/dates` / `GET /api/limit-up/history/day?date=`: 600 日日期与逐日四路径验证。
- `GET /api/limit-up/history/backtest?lane=portfolio|first_board|one_to_two|two_to_three|high_board&start=&end=&exit_mode=`: 10 万元真实现金回测；默认 `dynamic`，兼容 `next_open / next_close` 基准。页面完整范围不传日期，直接命中后台预热缓存。
- `GET /api/limit-up/history/factors?start=&end=&entry_mode=&exit_mode=`: 每日 Top5 候选的成功板/直接砸盘分型、买前因子样本外差异和锁定留出方向验证；结果口径不是成交。
- `GET /api/limit-up/history/model-report?start=&end=&entry_mode=&exit_mode=&lane=`: 不传 `lane` 时兼容旧买点 Top5；传首板/一进二/二进三/高板时读取完整板位候选池，按完整交易日历运行 252/63/63 Walk-forward，每日最多 1 只，训练不足 300 条时明确空仓。
- `GET /api/limit-up/forward-validation?start=&end=&entry_mode=&exit_mode=`: 只读真实保存快照的严格前向观察账本，支持四种买点和 D+1 开/收盘。
- `GET /api/limit-up/data-quality`: 研究账本、事件路径、历史成员、竞价、分钟、Tick/L2 和前向观察的真实覆盖门禁。
- `POST /api/limit-up/data-quality/minute-backfill`: 兼容的同步补数接口，默认 20 个、最大 200 个；长批次不要从产品调用。
- `POST /api/limit-up/data-quality/minute-backfill/start` / `GET /batches/{batch_id}`: 产品后台补数入口，默认 200 个并立即返回 `202`；前端每 2 秒轮询，终态自动刷新门禁。全局无关同步批次运行时返回 `409`。
- `sync_limit_up_event_minutes`: 夜间自动补主板非 ST 涨停事件分钟路径，默认 200 个；位于 `eod_finalize_2130` 的 `eod_quant_research` 之后，失败按 1/3/14 天持久化退避。
- `limit_up_history_rebuild`: `eod_finalize_2130` 最后一个内部任务；仅当最新完整日线日晚于 v11 账本末日时重建，无新交易日返回 `skipped`。重建完成会清空并重新预热动态回测/战法验证缓存。
- `auction_0926` / `sync_stock_auction_snapshots`: 交易日 09:26 保存主板非 ST 集合竞价公开字段；行情日期不等于当天、源时间不在 09:25-09:29、分页不足或去重后缺股都会整批失败且不写快照。
- `GET /api/data-sync/imports/limit-up-evidence/status`: 历史事件/竞价供应商配置和真实覆盖；不返回 token。
- `GET /api/data-sync/imports/limit-up-evidence/template.csv?dataset=events|auction`: 完整 CSV 模板。
- `POST /api/data-sync/imports/limit-up-evidence/tushare` / `csv`: 限量 Tushare 或完整 CSV 预检查/写入。事件/竞价覆盖不足分别按 90%/95% 拒绝，失败日期不覆盖旧数据。
- `POST /api/data-sync/imports/limit-up-evidence/ths/start` / `GET /ths/batches/{batch_id}`: 同花顺近 252 个交易日涨停/炸板证据后台批次；立即返回 `202`，前端每 2 秒轮询并可在刷新后恢复最近批次。
- `sync_limit_up_ths_evidence`: 上述批次的内部任务；使用 `ths.limit_up_pool/open_limit_pool`，逐日覆盖不足 90%、空响应或供应商错误时保留旧数据。
- `GET /api/data-sync/imports/limit-up-memberships/status` / `template.csv`: 逐日申万二级行业成员配置、四种覆盖口径和区间 CSV 模板。
- `POST /api/data-sync/imports/limit-up-memberships/tushare` / `csv`: 按日期范围和批次数预检查/写入行业成员；每日覆盖不足 90% 不写，同日概念成员保持不变。
- `POST /api/data-sync/schedules/limit_up_live_scan/run`: 手动执行与自动盘中计划相同的实时扫描；有效快照返回 `succeeded`，非交易时段或过期行情返回 `skipped / 未保存`。

当前事件工作台有 252 个有效历史日期，范围为 `2025-06-27..2026-07-10`；顶部 `/dates` 的历史部分必须和日线交易日历相交，不能出现周末快照。交易日上午日线尚未落库时，今天只有在快照确实今天采集、mode 为 live 且非 stale 时才可临时进入；午间和收盘后动作会自动降为 `pass`。`limit-up-history-v11` 点时账本覆盖 `2024-01-15..2026-07-10` 共 600 日，并保存完整候选池、最终选择、六类形态标签和逐笔退出决定。页面可按首板、一进二、二进三和高板切换，逐日查看 D 日买入、D+1 实际卖点、动态退出原因和净收益；冻结后前向为 0，仍保持研究状态。

2026-07-12 同花顺事件导入后，事件门禁为 252 日、19,978 条（涨停 14,455，炸板 5,523）；已有分钟路径 `2,215/19,978 = 11.0872%`，分钟交易日门禁仍为 `55/500` 日。TDX 尝试账本为 `1,928 covered / 0 empty / 0 error`，这不代表其余 17,763 个事件对已尝试或无需补数。桌面 `1440x1000` 与手机 `390x844` 浏览器验证无整页横向溢出，按钮启动、批次查询和终态门禁刷新分别返回 `202/200/200`，console 为 0 error / 0 warning。

前向表当前有 1 个周末快照，被 `non_trading_day` 排除；合格快照和有效前向交易日均为 0，状态为 `collecting`，胜率、收益和回撤均为空。新快照会同时保存历史风险门后的 `research_action` 和用户可执行 `action`；未验证战法仍显示 `pass`，但严格前向观察可据研究动作闭合 D+1，普通动作回测不会读取它。非交易时段刷新不请求外部行情、不写快照；交易时段内行情日期仍是上一交易日也不写。周末真实调用手动计划返回 `skipped / rows_written=0 / 未保存`，调用前后快照表都为 1 行。`/dates` 使用已验证事件日期轻查询；同一日期的 dashboard/signals 通过进程内单飞缓存共享一次单日计算。真实冷测 `/dates` 约 0.6 秒，同日 dashboard/signals 并发冷测约 7.7 秒，缓存后的 signals 约 30 毫秒。

当前日期页面查询 `/live`，历史日期才查询 `/signals`。交易时段行情采集只由 `limit_up_live_scan` 每分钟后台执行；页面 10 秒轮询只读已保存快照，不触发行情源或新增审计行。同日快照年龄超过 90 秒时动作自动降为 stale/pass。调试实时性时要同时检查页面延迟、`limit_up_live_scan` 状态、network 路径和快照表行数。

2026-07-12 真实 `/data-quality` 结果：点时历史账本 `600/500` 日达标；主板非 ST 涨停事件路径 `252/500` 日、19,978 条；事件分钟路径 `2,215/19,978 = 11.0872%`，分钟交易日为 `55/500`；逐日板块成员、竞价、板块分钟资金和 Tick/L2 均为 0，合格前向观察日为 0。末封时间和封单额覆盖只在最终封板事件内计算，当前均为 100%，炸板行不再把覆盖率推到 100% 以上。当前 8 个门禁仍仅 1 个达标、2 个补数中、5 个缺失，`research_ledger_ready=true`、`simulation_eligible=false`。当前成员表虽有 5,611 只股票、86,701 条关系，仍只能按 `current_snapshot` 计 0 个逐日历史覆盖日。原始周末/休市事件和盘中重复快照继续保留审计，但必须有同股同日日线且只取最后状态才进入门禁。

三张时点表和 `auction_0926` 已在真实 PostgreSQL 注册。当前日期为周末，系统没有伪造交易日行；首批有效成员、板块资金和竞价证据从下个交易日自动累积。公开竞价源仍缺未匹配量，所以竞价严格日保持 0，模拟资格继续关闭。

`/data` 已增加“打板证据”页。当前真实状态为 Tushare 未配置、同花顺近 252 日已覆盖、竞价 0 日；状态、模板、Tushare 无令牌和 CSV 预检查接口均返回 200。同花顺后台批次补齐原缺失的 `233/233` 日，写入 17,833 条，供应商错误和覆盖不足日均为 0；最终覆盖 `2025-06-27..2026-07-10` 共 252 日、19,978 条。按钮使用后台批次和 2 秒轮询，刷新页面后可恢复最近批次；全部已覆盖时明确显示无缺失日期。该公开源只覆盖近 252 个交易日，不能当作 500 日全历史；空响应也不会删除已有可靠事件。桌面和 `390x844` 页面无整页横向溢出，逐日审计宽表局部滚动，console 0 error/0 warning。

同页“逐日行业成员”已上线。2026-07-11 真实状态为 Tushare 未配置，原始/行业/概念/90% 合格历史日均为 0，当前成员仍为 5611 只、86701 行且不计入历史门禁。2026-07-10 单行区间 CSV 预检查以 3035 只有效主板日线股票为参照，只覆盖 1 只（`0.0329%`），结果 `rejected / rows_written=0`；错误的深市代码+沪市交易所组合已从资格分母排除。桌面和 `390x844` 下操作区无整页横向溢出，console 0 error/0 warning，状态、模板、Tushare 无令牌和 CSV 拒绝路径均返回 200。

验证入口：

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py -q
uv run --group server pytest tests/alphaagent/test_market_snapshot_repository.py tests/alphaagent/services/quant/test_market_timing_intraday.py -q
uv run --group server pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "registry_dispatches_default_strategy"
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
docker compose up -d --build alphaagent-api alphaagent-web
```

API runtime 需要 `libgomp1` 才能导入 LightGBM；该包在 `Dockerfile.alphaagent-api` 独立缓存层安装，并先删除只用于安装 Docker CLI 的 apt source，避免源码重建受 Docker 官方源波动阻塞。

浏览器检查 `http://localhost:8080/limit-up`，桌面和 `390x844` 都要验证四板位、历史日期交割单、动态卖点/原因、回测区间、局部表格滚动、console 和 network。v11 验证为打板后端 301 项、调度 87 项、前端 14 项和生产构建通过；桌面/手机无整页横向溢出，console 0 error/0 warning。部署后完整组合回测约 196ms、已预热交割单约 66ms、实时快照读取约 16ms。账本仍为 600 日，四板位均为 `research_only`，冻结后有效前向交易为 0，`simulation_eligible=false`；主结果见 `memory/06_backtests/limit_up_real_cash_backtest.md`。

## Verification

常用后端验证：

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run pytest tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_data_sync_schedule.py -q
```

常用前端验证：

```bash
pnpm --dir frontend run build
```

按变更范围补充更窄测试：

- 量化策略：`tests/alphaagent/test_quant_strategy_acceptance.py` 和对应 research script tests。
- 主线：`tests/alphaagent/test_mainline_replay_api.py`、`tests/alphaagent/test_mainline_replay_algo.py`。
- 同步调度：`tests/alphaagent/test_data_sync_schedule.py`。
- 网关：`cd gateway && go test ./...`。

## Known Caveats

- vn.py A 股实盘 Gateway 和官方 A 股 Datafeed 插件仍未安装配置。
- 多年全 A、walk-forward、参数敏感性、市场环境分层、基准超额和高摩擦压力测试仍是策略可信度的必要验证。
- 旧严格 14:30 报告只作为分钟模型历史材料；当前 `/quant` 候选质量主流程是 D 日收盘买入、D+1 收盘验证，组合执行诊断仍可显示 D+1 执行约束。
- 候选页落库推荐、单股逐日评分和组合回测理论计划仍需继续保持口径一致。
