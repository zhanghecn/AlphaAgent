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
  14:30 实时尾盘量化和 18:00 盘后补全；旧 11:30、14:00、15:00
  盘中缓存档会被启动种子逻辑禁用。
- `GET /api/quant/tail-preview?limit=50`: 今日实时尾盘量化结果，只读，不写历史候选。
- `POST /api/data-sync/tail-workflow/run-tail-quant`: 手动执行 14:30 实时尾盘量化批次。
- `POST /api/data-sync/batches/run-all`: 一键同步批次。
- `GET /api/data-sync/batches/latest`: 最新批次进度。
- `POST /api/data-sync/jobs/sync_stock_daily_bars/run`: 同步日线，可用 `symbols` 定向回填。
- `POST /api/data-sync/jobs/sync_stock_minute_bars/run`: 分钟线同步。
- `POST /api/data-sync/imports/minute-bars/audit-gaps`: 审计严格 14:30 缺口覆盖。

当前数据口径和维护风险见 `memory/03_data/data_flow.md`。

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
