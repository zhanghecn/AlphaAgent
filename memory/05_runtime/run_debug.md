# Run and Debug

这个文件只记录当前有效的运行、调试和验证入口。历史回测过程、长命令输出和截图清单放在 `memory/06_backtests/` 或具体计划文档中。

## Current State

- 项目外显名称是 AlphaAgent，Python 发行包名和源码包目录仍保留 `vnpy`，用于兼容 vn.py 插件。
- 官方桌面 GUI 入口仍是 `examples/veighna_trader/run.py`，当前只注册 `CtpGateway`、`CtaStrategyApp`、`CtaBacktesterApp`、`DataManagerApp`，不能视为 A 股实盘或全市场实时行情已接入。
- AlphaAgent Web/API 是当前主要研发入口，包含 A 股数据同步、量化候选、组合回测、股票详情、持仓和数据管理。
- 普通组合回测默认执行模型是 `strict_1430 / 1m / 14:30 / strict_entry=true`。组合严格 14:30 仍以真实分钟快照为主；单股历史信号复盘允许历史缺分钟线时使用执行日日线收盘价代理尾盘价格，并明确标记 `daily_close_proxy` / `tail_entry_not_triggered`。
- `tail_close_hybrid` 只用于研究对比，`legacy_next_open` 只用于旧报告兼容。严格主流程不再暴露 `5m/10m`。

## Local Run

桌面 vn.py GUI：

```bash
uv run python examples/veighna_trader/run.py
```

API：

```bash
uv run uvicorn alphaagent.server.main:app --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm run dev -- --host 0.0.0.0 --port 5173
```

常用页面：

- `/quant`: 候选、组合回测、审计/归因、严格 14:30 补数入口。
- `/data`: 数据同步、回测缺口补 14:30 快照、通用分钟线同步。
- `/portfolio`: 自选分组、量化候选分组、模拟持仓。
- `/stocks/:vtSymbol`: 股票详情、财报口径、量化信号复核、单股信号复盘。K 线会显示 BUY 信号、买入拒绝、买入成交和卖出成交；点击 K 线或指标柱可查看较前一日涨跌、跳空、振幅、均线距离和量比。

## Docker

本地开发默认入口：

```bash
docker compose up --build
```

当前 Compose 服务：

- `postgres`: AlphaAgent 业务数据。
- `redis`: 缓存和任务辅助。
- `alphaagent-api`: FastAPI 服务，容器内连接 Compose PostgreSQL。
- `alphaagent-web`: Vite dev server，默认端口 `5173`。

部署入口：

```bash
cd deploy
./docker-deploy.sh
docker compose -f docker-compose.local.yml up -d
```

约束：

- 不要把根目录 `.env` 改回 `host.docker.internal`，容器应使用 Compose 内部数据库。
- 日常不要使用 `docker compose build --no-cache`，除非正在排查基础镜像或依赖缓存。
- 前端使用 pnpm，`frontend/package.json` 固定 `pnpm@11.6.0`。

## Quant Debug

核心接口：

- `GET /api/quant/trading-dates`: 从本地日线表聚合真实交易日。
- `POST /api/quant/screen-runs/range`: 从起始交易日到本地最新交易日逐日生成候选。
- `GET /api/quant/screen-runs`: 查看候选运行覆盖、BUY/WATCH 数。
- `POST /api/backtests`: 新建组合回测，默认严格 14:30。
- `GET /api/backtests?run_type=portfolio`: 量化页组合回测列表。
- `GET /api/backtests/{id}/minute-coverage`: 判断真实 14:30、收盘代理、缺快照和入场未触发。
- `GET /api/backtests/{id}/daily-decisions`: 每日候选到成交复盘。
- `GET /api/backtests/{id}/trade-attribution`: 组合亏损/贡献归因。
- `GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=`: 单股单日候选、计划、订单、成交和没买原因。
- `GET /api/backtests/{id}/drilldown-options`: 日期和股票下钻选项。
- `GET /api/backtests/{id}/audit?vt_symbol=&limit=`: 单股详情页读取最新回测审计事件，用于展示信号日标记、执行日拒绝原因和成交标记。

当前基线和证据索引见 `memory/06_backtests/README.md`。

## Data Debug

核心接口：

- `POST /api/data-sync/batches/run-all`: 一键同步批次。
- `GET /api/data-sync/batches/latest`: 查看最新批次进度。
- `POST /api/data-sync/jobs/sync_stock_daily_bars/run`: 同步日线，可用 `symbols` 定向回填。
- `POST /api/data-sync/jobs/sync_stock_minute_bars/run`: 分钟线同步主入口。
- `POST /api/data-sync/imports/minute-bars/audit-gaps`: 审计严格 14:30 缺口覆盖。
- `POST /api/data-sync/imports/minute-bars/tdx-gaps`: 用 TDX 按缺口补历史 1m 快照。
- `POST /api/data-sync/imports/minute-bars/tushare-gaps`: 用 Tushare Pro 按缺口补 1m 快照，需要 `TUSHARE_TOKEN` 和权限。
- `POST /api/vnpy/import-minute-bars/gaps`: 从本机 vn.py 数据库按缺口导入 1m 快照。

当前数据事实：

- AkShare/东方财富公共分钟线可用于近端日期，但不能可靠覆盖 2025 至 2026-06 的历史分钟缺口。
- 严格 14:30 主流程只要求执行日 `14:30` 单点 `1m` 快照。
- CSV/file_path 仍保留为外部供应商数据回填和高级兜底，不是首选同步路径。

## Verification

常用后端验证：

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

常用前端验证：

```bash
pnpm --dir frontend run build
```

最近一次源码验证结论：

- Python compileall 通过。
- `tests/alphaagent/test_quant_backtest_portfolio.py`: `166 passed, 1 warning`。
- `pnpm --dir frontend run build` 通过，仅 Vite chunk size 警告。
- API 容器已用 `docker compose up -d --build alphaagent-api` 重建并健康。
- `002536.SZSE` 最新单股回测 `#84` 审计验证：`2025-12-30` 是 BUY 信号日，`2025-12-31` 买入拒绝，`reason=tail_entry_not_triggered`，`reason_label=尾盘入场未触发`，消息包含执行价 `29.7`、信号日 MA5 `31.744`、距 MA5 `-6.44%`。

## Known Caveats

- vn.py A 股实盘 Gateway 和官方 A 股 Datafeed 插件仍未安装配置。
- 严格 14:30 回测可以真实模拟已覆盖的执行快照，但当前策略收益仍为负，不能宣称稳定盈利。
- 多年全 A、walk-forward、参数敏感性、市场环境分层、基准超额和高摩擦压力测试仍是策略可信度的必要验证。
- 旧 `strategy_version < 0.1.1` 的回测存在卖出撮合时序问题，只能作为历史排查材料。
