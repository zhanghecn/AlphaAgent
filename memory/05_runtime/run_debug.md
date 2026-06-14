# Run and Debug

## 当前 GUI 启动入口

```bash
uv run python examples/veighna_trader/run.py
```

当前注册内容：

- Gateway: `CtpGateway`
- Apps: `CtaStrategyApp`, `CtaBacktesterApp`, `DataManagerApp`

源码位置：

- `examples/veighna_trader/run.py`

## 依赖状态

`pyproject.toml` 当前设置：

```toml
name = "vnpy"
requires-python = ">=3.11"
```

仓库/产品名是 AlphaAgent，但源码包目录和 Python 发行包名仍然是 `vnpy`，这是为了保持 vn.py 插件兼容性。

原因：

- `uv sync` 解析 `dev` 依赖时，`scipy-stubs>=1.16.3.0` 需要 Python >= 3.11。
- 原项目 `requires-python = ">=3.10"` 会让解析器认为需要支持 Python 3.10，从而产生冲突。

## 调试看数据的优先路径

优先从 vn.py 官方机制调试：

1. `examples/veighna_trader/run.py` 看注册了哪些 Gateway/App。
2. `MainEngine.get_all_gateway_names()` 看运行时有哪些接口。
3. 连接 Gateway 后，用 `get_all_contracts()` 看合约是否进入系统。
4. 订阅行情后，用 `get_tick(vt_symbol)` 或 `get_all_ticks()` 看 Tick 是否进入系统。
5. 配置 Datafeed 后，用 `get_datafeed().query_bar_history()` 看历史数据是否可取。
6. 用 DataManager 看数据库中是否有历史数据。

不优先写临时免费数据脚本，除非用户明确要求做外部数据源适配。

## AlphaAgent Web/API 调试

默认 API：

```bash
uv run uvicorn alphaagent.server.main:app --host 0.0.0.0 --port 8000
```

默认前端：

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm run dev -- --host 0.0.0.0 --port 5173
```

2026-06-11 验证过的备用端口：

- API: `http://localhost:8001`
- Frontend: `http://localhost:5175`
- 扩展回测表联调使用过 API `http://localhost:8002` 和 Frontend `http://localhost:5176`
- 指数基准、CSV 导出和参数化回测页面联调使用过 API `http://localhost:8003` 和 Frontend `http://localhost:5177`

本地 CORS 允许 `5173/5174/5175/5176/5177` 和 `8000/8001/8002/8003`，用于 Vite 自动换端口后的页面联调。

## Docker 构建策略

本地开发默认只用 Compose：

```bash
docker compose up --build
```

参考 `~/project/ai/sub2api` 的维护方式：复杂性留在 Dockerfile/Compose/deploy/CI，用户不需要记额外构建命令。`Dockerfile.alphaagent-api` 使用依赖层和运行层；API 运行依赖统一维护在 `pyproject.toml` 的 `[dependency-groups].server`，Docker 通过 `pip install --group pyproject.toml:server` 安装，不再维护 `alphaagent/server/requirements.txt`。Python 3.13 使用 `TA-Lib>=0.6.8` 的 manylinux wheel，并设置 `PIP_ONLY_BINARY=TA-Lib,numpy`，避免 pip 在镜像构建时退回源码编译。`.dockerignore` 已排除 `frontend/node_modules`、`frontend/dist`、构建缓存、部署数据目录和回测大 CSV，减少 Docker build context。

开发 Compose 当前包含四个服务：

- `postgres`: PostgreSQL 16，数据卷 `vnpy_alphaagent_postgres_data`。
- `redis`: Redis 8，数据卷 `vnpy_alphaagent_redis_data`。
- `alphaagent-api`: 通过 Compose 显式运行 `python -m uvicorn alphaagent.server.main:app --host 0.0.0.0 --port 8000`，避免旧镜像 CMD 影响启动。
- `alphaagent-web`: Vite dev server，端口 `5173`。

AlphaAgent 研究数据、同步任务、量化推荐、回测、持仓和模拟账户使用 Compose 内部 PostgreSQL；vn.py 运行目录挂载到 `vnpy_alphaagent_vntrader`，用于 `vt_setting.json`、vn.py SQLite `database.db` 和日志等本地文件。不要把根目录 `.env` 再改回 `host.docker.internal`，否则容器会绕过 Compose 内部数据库。

日常不要使用 `docker compose build --no-cache`，除非正在排查基础镜像或依赖缓存问题。

前端开发镜像 `frontend/Dockerfile` 使用 pnpm：

- `frontend/package.json` 通过 `packageManager` 固定 `pnpm@11.6.0`，前端 lockfile 为 `frontend/pnpm-lock.yaml`；不要再维护 `frontend/package-lock.json`。
- `frontend/pnpm-workspace.yaml` 记录 `allowBuilds.esbuild=true`，用于 pnpm 11 在 Docker/CI 中无交互批准 esbuild 的必要 postinstall。
- Docker 通过 corepack 激活 pnpm，`pnpm install --frozen-lockfile --store-dir=/pnpm/store --prefer-offline` 使用 `--mount=type=cache,id=alphaagent-web-pnpm-store,target=/pnpm/store` 保留 pnpm store。
- 本地 `docker-compose.yml` 给 `alphaagent-web` 构建传入 `PNPM_REGISTRY`，默认 `https://registry.npmmirror.com`；如需官方源，可在 `.env` 设置 `PNPM_REGISTRY=https://registry.npmjs.org/`。
- 2026-06-13 验证：`cd frontend && pnpm install --frozen-lockfile` 约 0.9 秒，`pnpm run build` 通过；`docker compose build alphaagent-web` 在 pnpm store 已有部分缓存时安装依赖约 6.9 秒，重复构建约 0.4 秒；`docker build -f frontend/Dockerfile --build-arg PNPM_REGISTRY=https://registry.npmmirror.com -t alphaagent-web-runtime-test frontend` 通过。若 Docker 中未显式 `pnpm config set registry`，会退回 `registry.npmjs.org` 并可能因 `echarts` 等包下载超时。
- 2026-06-12 曾用 npm BuildKit cache 把 `npm ci` 从约 7 分钟降到约 9 秒；2026-06-13 按用户偏好迁移到 pnpm，后续以 pnpm 构建结果为准。

部署目录参考 `~/project/ai/sub2api/deploy`：

- `deploy/docker-compose.local.yml`: 本地目录持久化，适合服务器迁移。
- `deploy/.env.example`: 部署环境变量模板。
- `deploy/docker-deploy.sh`: 生成 `.env` 和数据目录。
- `deploy/README.md`: 部署入口说明。

服务器部署入口：

```bash
cd deploy
./docker-deploy.sh
docker compose -f docker-compose.local.yml up -d
```

发版入口：

- `.github/workflows/docker-release.yml` 在 `v*` tag 或手动触发时发布镜像。
- 默认镜像：
  - `ghcr.io/zhanghecn/alphaagent-api`
  - `ghcr.io/zhanghecn/alphaagent-web`
- 前端生产镜像使用 Nginx 静态服务，容器启动时从 `VITE_API_BASE_URL` 写入 `/config.js`，服务器换 API 地址不需要重建前端镜像。
- `deploy/docker-deploy.sh` 会把模板里的 `POSTGRES_PASSWORD=change-me` 替换成随机密钥。

量化工作台：

- URL: `/quant`
- 当前布局：顶层任务页签为“候选 / 回测 / 日志 / 数据”。默认先看候选和模拟持仓摘要；回测、策略日志、分钟线补数不再挤在同一个长页面里。
- 股票显示规则：全 A 列表、市场活跃股、板块/主题股票表、股票详情、候选、回测交易、个股贡献、最差交易、订单审计、模拟持仓、持仓分组和单股回测日志都显示股票身份，尽量包含“股票名称 + vt_symbol + 板块标签”。默认复用 `frontend/src/components/StockIdentityLink.tsx` 跳转到 `/stocks/:vtSymbol`；AkShare 列表/详情/板块成分、推荐、回测报告/审计、持仓接口会补 `board` 和 `board_label`，缺后端字段时前端按 `vt_symbol` 兜底推导。
- 量化股票池：`POST /api/quant/screen-runs`、`POST /api/backtests` 和 `POST /api/backtests/strict-minute-pipeline` 支持 `included_boards`。默认 `["main"]`，即量化筛选/组合回测默认仅跑主板；前端 `/quant` 的“候选”页表头直接显示“主板 / 科创板 / 北交所 / 创业板”复选项，可显式加入其他板块。普通股票列表、详情、持仓和显式单股回测不按该默认规则过滤，仍显示所有股票。候选/信号接口默认按最新筛选运行 `run_id` 返回结果，不再把同一交易日旧版本或旧板块配置的候选混在一起；持久化新筛选结果前仍会清理同交易日同策略版本旧候选。
- 组合回测现在在报告和审计中明确展示：每个历史交易日收盘后重新生成当日候选，下一交易日执行；不是用今天候选名单回测全部历史。
- 回测撮合当前可信版本为 `0.1.1`：买入仍为 D 日收盘信号、D+1 执行；卖出已修正为 D 日收盘确认退出信号、D+1 开盘撮合。所有 `strategy_version < 0.1.1` 的绩效结果需要重跑。审计记录见 `memory/06_backtests/2026-06-12_backtest_engine_audit.md`。
- 回测页默认只显示核心参数、回测结论、回测方法、核心指标、成交真实性和最近买卖点；验证、交易归因、收益分段放在回测页内部页签；尾盘分钟线参数默认折叠在“高级执行设置”。旧版本报告会提示“需重跑”，新版但买入全部开盘回退会提示“宽松模拟”。
- 日志页专门展示结构化审计：`GET /api/backtests/{backtest_id}/audit?vt_symbol=&limit=` 返回策略版本、参数、方法、订单、成交和事件说明。
- 数据页承接严格分钟补数和 vn.py/TDX/Tushare/CSV 导入。普通筛选/组合回测不要求先补分钟线；补数和同步主流程长期优先放到 `/data`。
- 单股回测接口：`POST /api/backtests/symbol`，参数含 `vt_symbol`，内部用 `symbols=[vt_symbol]`、默认 `max_positions=1`、`candidate_limit=1`，返回持久化回测和审计；如果区间内无交易，应显示为“没有有效入场信号”，不强造买卖点。
- 股票详情页 `/stocks/:vtSymbol` 已接入“单股回测”：成交记录会作为 K 线买/卖 marker 展示，点击图表买卖点或下方买/卖标签可查看中文策略说明、信号日期、执行方式、成交价格、盈亏和回测证据；同时展示带股票名称的策略日志。
- 独立持仓模块：`/portfolio`，支持分组列表、新建分组、手动加入股票、量化候选/自动模拟持仓分组查看、模拟持仓明细、成本价、买入/卖出时间和买卖依据。
- 持仓相关接口：`GET/POST /api/portfolio/groups`、`GET/POST /api/portfolio/groups/{group_id}/items`、`GET /api/portfolio/holdings`。模拟建仓仍走 `/api/simulation/auto-buy-recommendations`，只写模拟账户，不下实盘单。
- 2026-06-12 使用 Playwright 验证 `/quant` 候选、回测、日志页签均可点击股票进入详情页：候选 `华虹宏力 688347.SSE -> /stocks/688347.SSE`，回测/日志 `绿的谐波 688017.SSE -> /stocks/688017.SSE`；页面截图 `/tmp/alphaagent-quant-cleanup-candidates.png`、`/tmp/alphaagent-quant-cleanup-backtest.png`、`/tmp/alphaagent-quant-cleanup-logs.png`。
- 旧截图：`/tmp/alphaagent-quant-expanded-report.png`、`/tmp/alphaagent-quant-report4-export.png`、`/tmp/alphaagent-quant-robustness-report4.png`。

## 2026-06-11 量化验证记录

命令：

```bash
uv run pytest tests/alphaagent -q
npm run build
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
```

结果：

- 后端测试：164 passed, 1 skipped, 1 warning。
- 前端构建：通过，仅 Vite chunk 体积警告。
- Python compileall：通过。
- 依赖导入：`vnpy`、`vnpy_ctp`、`vnpy_ctastrategy`、`vnpy_ctabacktester`、`vnpy_datamanager`、`vnpy_sqlite`、`bs4`、`lxml` 均 ok。
- 服务烟测：筛选、推荐、持仓、回测报告、vn.py 状态均返回；后端 vn.py readiness 可返回 `partial`，前端应翻译为“本地回测可用，A 股 Datafeed/Gateway 待接入”，不直接展示“部分就绪”。
- vn.py 本地数据适配烟测：`/api/vnpy/local-bars?vt_symbol=600000.SSE&start=2026-01-01&end=2026-06-11&limit=3` 返回 `ready`、3 条日线、interval `d`、gateway_name `ALPHAAGENT_LOCAL`。
- 历史分钟 CSV 导入烟测：`/api/data-sync/imports/minute-bars/template.csv` 返回模板；`POST /api/data-sync/imports/minute-bars` 在 `dry_run=true` 下返回 `ready`、`rows_read=1`、`rows_written=0`、`symbol_count=1`。
- 严格尾盘缺口审计：`POST /api/data-sync/imports/minute-bars/audit-gaps` 支持检查缺口 CSV 覆盖；`POST /api/data-sync/imports/minute-bars/gap-template.csv` 可生成待填分钟线模板。
- 服务器路径导入/审计：`POST /api/data-sync/imports/minute-bars` 和 `/audit-gaps` 支持 `file_path`，仅允许 `data/imports/` 与 `memory/06_backtests/` 下的 `.csv`，用于大型分钟线文件；真实审计 `memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv` 返回 `incomplete`、794 缺口、2 覆盖、792 缺失、覆盖率 0.2519%。
- 大文件分钟线导入走流式分批写入，默认约 2000 行 flush 一批，避免把外部 1 分钟历史 CSV 全量读入内存后再落库。
- 页面烟测：临时启动 API `http://localhost:8004` 和前端 `http://localhost:5178`，用 Playwright 打开 `/quant`，确认“分钟线补数”面板渲染、缺口 CSV 可审计并显示覆盖率/缺口示例；截图 `/tmp/alphaagent-quant-minute-data.png`。
- 页面补数流程烟测：`/quant` 的“严格分钟预设”可将样本数切到 1500 并启用 `minute_entry_required`；缺口 CSV 和外部分钟线 CSV 可通过文件选择读入文本框，随后可触发缺口审计；截图 `/tmp/alphaagent-quant-minute-file-flow.png`。
- 页面路径模式烟测：`/quant` 可填写服务器缺口文件路径和服务器分钟线文件路径；用 `memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv` 审计后显示仍有缺口，且“运行严格分钟回测”按钮保持禁用，避免未补齐分钟线时误跑严格回测；截图 `/tmp/alphaagent-quant-minute-path-flow.png`。
- vn.py 数据库分钟线导入：`POST /api/vnpy/import-minute-bars` 可按 `vt_symbol/start/end/interval/dry_run` 从当前 vn.py database 配置读取 1 分钟 BarData 并导入 `stock_minute_bars`；`/quant` 页面已展示“vn.py 数据库分钟线”导入区。页面烟测确认按钮可见，截图 `/tmp/alphaagent-quant-vnpy-minute-import.png`。
- vn.py 缺口批量导入：`POST /api/vnpy/import-minute-bars/gaps` 可按严格尾盘缺口 CSV 批量读取当前 vn.py database 的 D+1 尾盘窗口 1 分钟 BarData 并返回导入后覆盖审计；`/quant` 页面新增“按缺口预检查/按缺口导入”按钮。
- 当前本机 vn.py SQLite 审计：`/root/.vntrader/database.db` 存在，但 `dbbardata`、`dbbaroverview`、`dbtickdata`、`dbtickoverview` 均为 0 行；用缺口文件 dry-run 批量导入前 10 个缺口返回 `status=empty`、`rows_read=0`、`rows_written=0`、`empty_request_count=10`，导入后审计仍为 `incomplete`、覆盖 2、缺失 792、覆盖率 0.2519%。
- Tushare Pro 缺口导入：`POST /api/data-sync/imports/minute-bars/tushare-gaps` 可按严格尾盘缺口 CSV 调用 `stk_mins` 补历史分钟线；当前环境未配置 `TUSHARE_TOKEN`，dry-run 返回 `status=unavailable`、`message=TUSHARE_TOKEN not configured`。
- 严格分钟流水线：`POST /api/backtests/strict-minute-pipeline` 会先审计缺口覆盖，只有审计 ready 才运行 `minute_entry_required=true` 的严格回测；当前用回测 10 缺口文件实测返回 `blocked_by_minute_gaps`、`gap_count=794`、`covered_count=2`、`missing_count=792`、覆盖率 0.2519%，不会误跑伪严格回测。

2026-06-11 复核：

- 重新运行 `uv run pytest tests/alphaagent -q`：161 passed, 1 skipped, 1 warning。
- 重新运行 `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`：通过。
- 重新运行 `cd frontend && npm run build`：通过，仅 Vite chunk 体积警告。
- 用 `TestClient` 调用 `/api/backtests/strict-minute-pipeline` 并传入 `memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv`：返回 `blocked_by_minute_gaps`，审计为 `incomplete`，`gap_count=794`、`covered_count=2`、`missing_count=792`、覆盖率 0.2519%，且没有生成新的严格回测对象。
- 供应商补数清单：`POST /api/data-sync/imports/minute-bars/vendor-manifest` 和 `.csv` 可把严格缺口转成外部数据供应商请求清单；历史回测 10 缺口曾按 14:30-14:57 窗口生成 794 条 symbol-date 请求、194 只股票、101 个交易日。当前新默认已收敛为 D+1 14:30 快照，显式传旧窗口时才按 14:30-14:57 审计。

2026-06-12 量化/持仓可用性复核：

- `uv run pytest tests/alphaagent -q`：170 passed, 1 skipped, 1 warning。
- `uv run python -m compileall alphaagent/market/boards.py alphaagent/data_sources/akshare_adapter.py alphaagent/server/services/quant/screening.py alphaagent/server/services/backtest/engine.py alphaagent/server/api/quant.py alphaagent/server/api/backtests.py`：通过。
- `cd frontend && npm run build`：通过，仅 Vite chunk 体积警告。
- 用户反馈的 5 个量化问题已完成排查，审计报告见 `memory/06_backtests/2026-06-12_quant_issue_audit.md`；当前确认存在“最近买卖点”排序文案/展示错误、vn.py 状态文案不清、财报详情与回测数据链路不一致、日线成交额缺失影响流动性评分、缺每日逐股持仓快照等问题。
- 2026-06-12 晚间修复复核：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 通过（79 passed）；`uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/server/db` 通过；`cd frontend && npm run build` 通过，仅 Vite chunk 体积警告。API 已重建并重启，`/api/backtests/29/report?trade_limit=8` 返回最近交易日期 `2026-06-12/2026-06-11`；新回测 `#30` 写入 3 条 `backtest_daily_positions`，日期/股票钻取接口可返回逐股持仓。
- 金安国纪历史信号复核：`/api/quant/symbols/002636.SZSE/signal-history?limit=10` 返回 `entry_signal_count=0`，但 `2026-02-09` 等多天只因 `liquidity_score=15` 未触发；这和 `stock_daily_bars.turnover` 覆盖为 0 直接相关。
- 2026-06-12 日线成交额修复后复核：`AkShareAdapter.stock_bars("002636","SZSE",limit=1,interval="1d")` 返回 `source=tencent.stock_kline_full`、`turnover=7580017900.0`；定向运行 `sync_stock_daily_bars` 参数 `{"symbols":["002636.SZSE"],"limit":250}` 写入 250 行；正式 API `/api/quant/symbols/002636.SZSE/signal-history?limit=5` 返回 `entry_signal_count=26`，最近 `2026-06-12` 未入场原因只剩 `ma5_distance`。
- 2026-06-12 成交额修复验证：`uv run pytest tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_quant_backtest_portfolio.py -q` 通过（111 passed, 1 warning）；`uv run python -m compileall alphaagent/data_sources/akshare_adapter.py alphaagent/server/services/data_sync.py alphaagent/server/services/quant/factors.py alphaagent/server/api alphaagent/server/services alphaagent/server/db` 通过；`cd frontend && npm run build` 通过，仅 Vite chunk 体积警告。API 已 `docker compose up -d --build alphaagent-api` 重建并健康。
- `docker compose up -d --build alphaagent-api alphaagent-web` 使用依赖缓存重建业务层；`/api/backtests/1/audit?limit=3` 返回 `daily_dynamic_candidate_backtest` 方法说明和订单审计；`/portfolio`、`/quant`、`/stocks/600000.SSE` 浏览器 smoke 均通过。
- 页面截图：`/tmp/alphaagent--quant-final.png`、`/tmp/alphaagent--portfolio-final.png`、`/tmp/alphaagent--stocks-600000.SSE-final.png`。
- 追加 UI 复核：`/api/quant/recommendations?limit=3` 返回 `name`（如华虹宏力、联瑞新材、芯碁微装）；`/api/backtests/2/report?trade_limit=3` 和 `/api/backtests/2/audit?limit=3` 返回 `name`（如绿的谐波、紫金矿业、拓荆科技）；Playwright smoke 确认 `/quant` 候选、回测、日志页签均显示名称且“高级执行设置”默认折叠。
- 单股回测图表复核：Playwright 打开 `/stocks/600118.SSE`，运行单股回测后生成 2 个买卖点，页面显示“回测买卖点已标注在图表上”，买入说明包含“历史逐日动态候选回测”和“信号日收盘后重新打分”，切换卖出点后显示退出规则说明；控制台错误数为 0。
- 板块过滤/展示复核：`alphaagent/market/boards.py` 统一识别主板、创业板、科创板、北交所；测试覆盖默认量化股票池排除创业板/科创板/北交所、勾选后可包含其他板块、显式单股回测不受默认过滤影响。候选/信号读取只认当前策略版本的最新成功筛选运行，按 `run_id` 取数，避免同交易日旧版本或旧股票池结果混入。2026-06-12 复核 `/api/quant/recommendations?limit=50` 返回 `strategy_version=0.1.1`、`included_boards=["main"]`，样本全为主板；`/api/quant/signals?limit=50` 也全为主板；Playwright 复核 `/quant` 候选页有四个板块选项，表格 20 行中科创板行数为 0。

过期宽松回测 9（`0.1.0`，仅作历史排查材料）：

- 报告：`memory/06_backtests/2026-06-11_backtest_9_report.md`
- 交易明细：`memory/06_backtests/alphaagent_backtest_9_2025-10-14_2026-06-11.csv`
- 区间：2025-10-14 至 2026-06-11。
- 样本：股票库 4535；区间有日线 1582；满足 >=80 根日线 1551。
- 原指标：总收益 44.64%，最大回撤 -6.87%，胜率 53.67%，盈亏比 1.87，Sharpe 3.04。
- 2026-06-12 发现 `0.1.0` 卖出撮合存在时间顺序错误，以上绩效指标、参数网格和 walk-forward 结论均不能作为策略有效性依据。
- 参数网格：54 组合文件 `memory/06_backtests/alphaagent_validation_grid_9_2025-10-14_2026-06-11.csv` 保留为历史文件；因同属 `0.1.0`，不再引用其正收益/超额结论。
- 执行：分钟尾盘成交 0，日线开盘回退成交 181；这说明尾盘规则已接入但分钟历史覆盖不足，不能声称已完成大量分钟级尾盘验证。

严格尾盘回测 10：

- CSV：`memory/06_backtests/alphaagent_backtest_10_2025-10-14_2026-06-11.csv`
- 参数：1500 标的，`minute_entry_required=true`，当时只承认 D+1 14:30-14:57 接近可见 MA5 的分钟成交，不允许日线开盘回退；新默认严格尾盘已改为 D+1 14:30 单点快照。
- 结果：期末权益 100 万，总收益 0%，平仓交易 0，分钟尾盘成交 0。
- 结论：当前本地 1 分钟线只有 22080 条，无法支撑“尾盘到 5 日线附近低吸”的严格历史回测；必须补齐历史分钟线后才能验证该入场规则的真实胜率和收益。
- 分钟缺口清单：`memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv`，794 条缺口订单，覆盖 101 个交易日、194 只股票。
- 2026-06-11 缺口审计结果：794 个缺口中当前只覆盖 2 个，缺 792 个，覆盖率 0.2519%；缺口仍覆盖 101 个交易日、194 只股票。
- 公共分钟源探测：对 `688387.SSE`、`688568.SSE` 请求 2026-01-08 的 EastMoney 1 分钟 K 线时，源接口实际返回最近 2026-06-11 数据；已在 AkShare adapter 中增加日期过滤，避免把区间外分钟线误写成历史回测数据。
- 2026-06-11 复核公共分钟源：EastMoney 分钟 K 对 2026-01-08 缺口样本仍返回 2026-06-11；Sina 分钟 K 返回 2026-06-10/11 近端数据；Sina 历史逐笔 JSON 对 2026-01-08 返回 0 条、对 2026-06-11 当日样本才有逐笔数据。不能把这些公共源用于补 2026-01 至 2026-06 严格历史分钟缺口。

数据快照：

- `stocks`: 4535
- `stock_daily_bars`: 275997
- `stock_minute_bars`: 22080
- `stock_financial_reports`: 2906
- 其中有 `publish_date` 的财报约 348 行，有 `operating_cash_flow` 的财报约 145 行。

注意：

- 小批量财报现金流扩展同步会触发 AkShare 内部多次请求，验证时出现耗时过长，已中止长跑任务并把运行记录标记失败；已提交代码支持字段映射和落库，但全量稳定同步还需后续优化批处理/超时/数据源。
- 1500 标的大样本 54 组合参数网格已通过财务评分缓存优化完成；仍需更长历史周期检验默认参数是否跨牛熊稳健。
- 回测 API 和 `/quant` 前端已暴露 `intraday_entry`、`minute_entry_required`、`tail_entry_start`、`tail_entry_end`、`tail_entry_ma5_tolerance_pct`，可直接运行宽松回退或严格分钟尾盘两种模式；默认尾盘窗口为 14:30-14:30，报告和 CSV 会输出“成交真实性检查”。
- `/api/vnpy/local-bars` 已把 AlphaAgent 本地 `stock_daily_bars` 转换为 vn.py `HistoryRequest`/`BarData` 语义，作为本地研究和后续策略适配桥；它不是官方 vn.py Datafeed，也不提供实时行情或实盘交易。
- `/api/vnpy/import-minute-bars` 是从 vn.py 数据库向 AlphaAgent 补 `stock_minute_bars` 的导入桥；前提是 vn.py 数据库里已经有对应 A 股 1 分钟历史数据。
- `/api/vnpy/import-minute-bars/gaps` 是按严格尾盘缺口批量从 vn.py 数据库补数的导入桥；当前本机 vn.py 数据库为空，不能直接生成严格真实回测。
- `/api/data-sync/imports/minute-bars/tushare-gaps` 是按严格尾盘缺口从 Tushare Pro `stk_mins` 补数的导入桥；需要 `.env` 配置 `TUSHARE_TOKEN` 且账号开通分钟数据权限，当前未配置。
- `/api/data-sync/imports/minute-bars/tdx-gaps` 是按严格尾盘缺口从 TDX 公开行情服务器补数的导入桥；已实测可补 2026-05 至 2026-06 的 1 分钟尾盘窗口，但公开源回溯范围有限，长区间仍需 Tushare/RQData/XT/QMT/券商 CSV。
- `/api/backtests/strict-minute-pipeline` 是最终严格回测入口；补齐分钟线后优先调用它生成真实严格回测表。
- `/api/backtests/{backtest_id}/minute-gaps.csv` 可从严格回测被拒买入订单导出分钟缺口 CSV，用于后续补数和严格流水线。
- `/api/data-sync/imports/minute-bars/vendor-manifest.csv` 可作为给 Tushare/RQData/XT/QMT/券商导出工具的数据需求清单；回填数据仍必须按 `vt_symbol,bar_time,open,high,low,close,volume,turnover` 导入。
- `sync_stock_minute_bars` 现在同时支持 `mode=recent` 和 `mode=backtest_gaps`：最近同步仍按 `symbols/start_date/end_date` 拉公开近端分钟线；回测缺口同步可传 `backtest_id`、`gap_file_path` 或 `gap_csv_text`，并通过 AkShare/TDX/Tushare/vn.py 补 D+1 14:30 的 `1m` 快照。严格缺口主流程只支持 `1m / 14:30`；`5m/15m/30m/60m` 只属于通用分钟线同步/看盘能力，`10m` 只保留拒绝测试和历史记录。
- 外部历史分钟线补数入口已接入：`GET /api/data-sync/imports/minute-bars/template.csv` 下载模板，`POST /api/data-sync/imports/minute-bars` 传 `csv_text`、`interval`、`source`、`dry_run` 导入到 `stock_minute_bars`；`POST /api/data-sync/imports/minute-bars/audit-gaps` 审计缺口覆盖。这只是补数和校验通道，不代表当前已经有足够历史分钟数据完成严格尾盘回测。
- 大文件建议路径：把外部导出的 1 分钟 K 线 CSV 放到 `data/imports/`，然后用 `file_path="data/imports/文件名.csv"` 预检查、导入、再审计缺口覆盖。

数据管理台：

- URL: `/data`
- 入口：默认进入“同步管理”，第一屏提供“一键同步”。
- 后端批次接口：
  - `POST /api/data-sync/batches/run-all`
  - `GET /api/data-sync/batches/latest`
  - `GET /api/data-sync/batches/{batch_id}`
- 批次进度存 API 进程内存；每个子任务仍写入 PostgreSQL `sync_job_runs`。API 重启后会把遗留 `running` 任务标记为 `failed / Interrupted`，避免页面永远卡住；内存批次快照本身不会跨 API 重启保留。
- 批次任务现在有内部进度字段：`progress_current`、`progress_total`、`progress_pct`、`stage`、`current_label`、`sample_items`。页面会显示每个任务自己的进度条、当前页/股票/板块、读写行数和最近 1-3 条压缩样本，避免长任务看起来卡死。
- 已接入内部进度的同步任务包括：股票清单、板块清单、板块成分股、股票日 K、股票分钟 K、个股资金流、个股热度、季度财报、财务指标、主营构成历史和个股公告。其他任务仍可用同一个 `DataSyncRunner(progress=...)` 机制继续扩展。
- `core` 批次当前按依赖顺序跑 5 个初始化任务：`sync_stock_list`、`sync_sector_list`、`sync_stock_daily_bars`、`sync_stock_fund_flows`、`sync_stock_hot_ranks`。`all` 批次跑 `DEFAULT_JOBS` 全量任务，包含财报、公告、龙虎榜、行业链等，耗时更长。
- “股票分钟 K 线”单任务在页面内提供参数面板：可选“回测缺口 / 最近分钟线”、数据源、周期、回测 ID、缺口文件、尾盘时间、dry-run 和最大缺口数；默认尾盘时间为 14:30-14:30，执行按钮仍调用 `POST /api/data-sync/jobs/sync_stock_minute_bars/run`。
- 同步任务 registry 启动时会同步 `DEFAULT_JOBS` 的名称、描述、默认参数到 `sync_job_definitions`，避免代码更新后数据库继续显示旧任务说明。
- 2026-06-12 容器烟测：`/data` 返回 200；核心批次完成过一次，写入约 `stocks=4000`、`sectors=1484`、`stock_daily_bars=975733`、`stock_fund_flows=175`、`stock_hot_ranks=97`。小参数批次验证过内部进度和样本字段，例如股票清单显示页码和最近股票样本，日线显示当前股票和最近 K 线样本。
- 页面烟测：`cd frontend && npm run build` 通过；浏览器打开 `http://localhost:5173/data` 可见“数据管理 / 同步管理 / 数据初始化 / 一键同步 / 同步任务 / 最近执行记录”，截图 `/tmp/alphaagent-data-sync-progress.png`。
- 2026-06-14 页面烟测：浏览器打开 `http://localhost:5173/data`，填写 `backtest_id=42`、`max_gaps=1` 并执行“股票分钟 K 线”任务，返回 `mode=backtest_gaps`、`provider=tdx`、`gap_source=backtest_id=42`，无 failed requests 和 console errors；截图 `/tmp/alphaagent-data-sync-minute-gap.png`。
- 验证命令：`uv run pytest tests/alphaagent -q` 为 164 passed, 1 skipped, 1 warning；`uv run python -m compileall alphaagent/server/services/data_sync.py alphaagent/server/services/vnpy_integration/local_data.py` 通过。
- 相关修复：`/api/vnpy/local-bars` 会先校验 `vt_symbol` 再判断数据库配置，非法值如 `BAD` 返回 400 `INVALID_VT_SYMBOL`，不会被数据库未配置状态吞掉。

2026-06-14 量化清理/策略选择/回测 ID 补数复核：

- 后端量化测试：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`，结果 `109 passed, 1 warning`。
- Python 编译：`uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/data_sources alphaagent/server/db`，通过。
- 前端构建：`pnpm --dir frontend run build`，通过，仅 Vite chunk 体积警告。
- Docker：`docker compose up -d --build alphaagent-api alphaagent-web` 后 API healthy，web started。
- 地址复核：`curl -I http://127.0.0.1:5173/quant` 和 `curl -I http://localhost:5173/quant` 均返回 200；`/api/health` 返回 `status=ok`。前端默认 API 地址仍是 `http://localhost:8000/api`，用 `127.0.0.1:5173` 打开页面时接口仍请求 `localhost:8000`。
- Playwright CLI 在 root 环境因 Chromium sandbox 失败，改用本地 Playwright `chromium.launch({ args: ["--no-sandbox"] })` 做真实浏览器复核。
- 浏览器复核通过：`/quant` 候选页显示策略选择和“生成区间候选”，无 5m/10m 严格回测入口；回测页显示“运行组合回测”和“信号计划”；量化数据页显示严格14:30补数、回测ID和高级兜底；`/data` 的股票分钟 K 线任务默认回测缺口、回测 ID、`1分钟 / 14:30快照`；`/stocks/002636.SZSE` 显示两个量化策略。
- 截图证据：`/tmp/alphaagent-quant-candidates.png`、`/tmp/alphaagent-quant-backtest.png`、`/tmp/alphaagent-quant-data.png`、`/tmp/alphaagent-data-sync.png`、`/tmp/alphaagent-stock-002636.png`。
- 真实 API 复核：`/api/quant/strategies` 返回 `mainline_leader_pullback / 0.1.1` 和 `breakout_confirmation / 0.1.0`；`/api/quant/trading-dates?limit=5` 最新本地交易日为 `2026-06-12`，用户选择到 `2026-06-13` 会按交易日对齐到最近有数据的交易日。
- 回测 ID 补数复核：`POST /api/data-sync/imports/minute-bars/audit-gaps {"backtest_id":52,...}` 返回 `ready`、`gap_count=0`；这是因为 `#52` 是 `tail_close_hybrid`，缺分钟线主要走收盘代理，不生成严格拒单缺口。
- 策略贯通复核：`POST /api/backtests` 使用 `strategy=breakout_confirmation`、`start=2026-02-02`、`end=2026-06-13`、`persist=true` 生成组合回测 `#53`，返回总收益 +2.3351%、最大回撤 -0.2141%、平仓交易 2、`daily_close_proxy_count=2`。
- 低吸当前组合回测 `#52` 报告：总收益 -13.4700%、最大回撤 -14.0935%、平仓交易 19、`minute_1430_count=2`、`daily_close_proxy_count=19`，数据质量快照为 `stock_daily_bars=990640`、成交额覆盖率 99.61%、`stock_minute_bars=61544`、`stock_financial_reports=3851`。
- 执行模型对比新增并复核：`GET /api/backtests/{id}/execution-model-comparison` 会用同一回测参数非持久化重跑 `tail_close_hybrid` 和 `strict_1430`。真实 API 验证 `#52`：尾盘混合总收益 -13.4700%、买入 21 笔、`minute_1430_ratio=9.52%`、`daily_close_proxy_ratio=90.48%`；严格 14:30 总收益 -0.3322%、买入 3 笔、`strict_1430_rejected_count=193`、`minute_gap_rejected_count=188`。结论是严格结果也不能代表完整策略收益，必须先补齐 14:30 快照缺口。
- 金安国纪复核：`/api/quant/symbols/002636.SZSE/signal-history?start=2025-10-14&end=2026-06-13` 低吸 `entry_signal_count=23`；同接口带 `strategy=breakout_confirmation` 返回突破 `entry_signal_count=18`；财报覆盖为本地 20 条、可用 20 条、最新披露日 2026-04-29。
- 2026-06-14 候选到订单追踪新增并复核：`GET /api/backtests/{id}/candidate-trace?vt_symbol=&signal_date=` 可解释某日候选是否进入理论信号计划、是否下真实组合订单、是否成交、当天现金/持仓市值/总权益和没买原因。真实 API 验证：`#52 + 603986.SSE + 2026-06-11` 返回 `filled`，计划执行日 `2026-06-12`，订单/成交为 `minute_1430`；`#52 + 603986.SSE + 2026-06-12` 返回 `candidate_not_planned`，不会把尾日候选错误关联到同日成交；`#52 + 002636.SZSE + 2026-06-12` 返回 `not_selected`，显示金安国纪在该回测该日未入选。浏览器复核 `/quant` 点击“追踪”可见“候选到订单追踪 / 订单状态 / 现金 / 持仓市值 / 总权益”，截图 `/tmp/alphaagent-quant-candidate-trace.png`；`/stocks/002636.SZSE` 回归截图 `/tmp/alphaagent-stock-002636-trace-regression.png`。
- 2026-06-14 真实性结论 UI 复核：`/quant` 回测页新增“回测真实性结论”和“执行模型对比”。真实浏览器点击“执行模型对比”后展示尾盘混合/严格14:30表格、严格拒单警告和收盘代理占比；无 failed requests，仅 React Router v7 future warning。截图 `/tmp/alphaagent-quant-reality-verdict-before.png`、`/tmp/alphaagent-quant-execution-comparison.png`。验证命令：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 119 passed, 1 warning；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告。
- 2026-06-14 策略元数据/金安国纪复核修正：`/api/quant/strategies` 现在返回 `entry_action_label`、`watch_action_label`、`evidence_labels`、`primary_metric_keys`，候选页和股票详情按策略显示关键指标；低吸显示 `MA5距离`，突破显示 `距60日高点 / 量能比`。`_recommendation_to_db()` 不再把失败规则阈值硬编码为 68，突破策略按 70 分硬门槛生成失败规则。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 121 passed, 1 warning；`pnpm --dir frontend run build` 通过；`uv run python -m compileall alphaagent/server/services/quant alphaagent/server/api/quant.py` 通过；`docker compose up -d --build alphaagent-api alphaagent-web` 后 `/api/health` 正常；真实浏览器验证 `/stocks/002636.SZSE` 同时显示低吸和突破策略指标，`/quant` 选择突破策略后空状态也显示 `距60日高点 / 量能比`，无 failed requests 和 console errors。截图：`/tmp/alphaagent-stock-002636-strategy-metrics.png`、`/tmp/alphaagent-quant-breakout-metrics.png`。
- 2026-06-14 卖出时序修复后重跑：`#59` 使用当前代码重跑 `mainline_leader_pullback / strict_1430 / 1m / 14:30`，区间 `2026-02-02` 至 `2026-06-13`，总收益 -0.9470%、最大回撤 -5.3325%、买入 20/20 为真实 14:30 快照、收盘代理 0、缺 14:30 快照拒单 12。`#58` 属旧卖出时序口径，不再作为当前绩效结论。证据见 `memory/06_backtests/2026-06-14_backtest_59_strict_1430_recheck.md`。
- 2026-06-14 14:30 覆盖面板复核：新增 `GET /api/backtests/{id}/minute-coverage` 和 `/quant` 回测页“14:30覆盖”；真实浏览器确认默认显示 `#59`、缺快照状态、收益 -0.95%，`127.0.0.1:5173/quant` 与 `localhost:5173/quant` 均正常，无 failed requests 和 console errors。截图 `/tmp/alphaagent-quant-minute-coverage-59.png`、`/tmp/alphaagent-stock-002636-current.png`。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 126 passed, 1 warning；`pnpm --dir frontend run build` 通过；`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api` 通过；`docker compose up -d --build alphaagent-api alphaagent-web` 通过。
- 2026-06-14 量化清理第一批复核：`BacktestParamsForm` 普通高级区固定展示 `1分钟 / 14:30快照` 和 `14:30 单点`，不再提供 `尾盘开始`、`尾盘结束`、`MA5允许偏离` 输入；`vn.py` 状态不再向用户展示“部分就绪”，而是显示 A 股接入待配置。回测金额账本已抽到 `alphaagent/server/services/backtest/ledger.py`，保持滑点、佣金、印花税、100 股整数手和现金不足重算口径不变。
- 2026-06-14 验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 132 passed, 1 warning；`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/vnpy_integration alphaagent/server/api` 通过；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告；`docker compose up -d --build alphaagent-api alphaagent-web` 后 API healthy。`curl -I http://127.0.0.1:5173/` 和 `curl -I http://localhost:5173/` 均返回 200。
- 2026-06-14 真实浏览器复核：`/quant` 候选页显示从 `2025-06-13` 到 `2026-06-12` 的交易日候选核查；回测页显示 14:30 覆盖，展开高级执行设置可见固定 `1分钟 / 14:30快照`；数据页显示分钟/14:30 工具；`/stocks/002636.SZSE` 正常加载金安国纪量化上下文。无 failed requests 和 console errors。截图：`/tmp/alphaagent-quant-candidates-real.png`、`/tmp/alphaagent-quant-backtest-real.png`、`/tmp/alphaagent-quant-backtest-advanced-real.png`、`/tmp/alphaagent-quant-data-real.png`、`/tmp/alphaagent-stock-002636-real.png`。
- 2026-06-14 当前严格结果更新为 `#62`：`mainline_leader_pullback / strict_1430 / 1m / 14:30`，区间 `2026-02-02` 至 `2026-06-13`，主板 `max_symbols=80`，期末权益 `949,180.1413490004`，总收益 `-5.0820%`，最大回撤 `-9.5778%`，平仓交易 18；买入 21/21 为真实 14:30 快照，收盘代理 0，缺 14:30 快照拒单 0。`#60` 的 5 个缺口已通过 TDX 写入 5 行补齐，`#62` 剩余 83 个严格拒单均为尾盘条件未触发，不是缺分钟数据。证据见 `memory/06_backtests/2026-06-14_backtest_62_strict_1430_recheck.md`。
- 2026-06-14 信号计划重构复核：`_link_signal_events_to_orders`、计划状态标签和候选追踪诊断已抽到 `alphaagent/server/services/backtest/signal_plan.py`，`engine.py` 保留兼容包装。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "signal_plan or signal_events or candidate_trace" -q` 为 9 passed；全量 `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 133 passed；`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api` 通过；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告。
- 2026-06-14 信号计划真实浏览器复核：`docker compose up -d --build alphaagent-api alphaagent-web` 后 API healthy；`/quant` 点击“追踪”可见“候选到订单追踪”、订单状态、现金/总权益；回测页“信号计划”页签可加载理论/订单/金额信息；无 failed requests 和 console errors。截图：`/tmp/alphaagent-quant-signal-plan-trace-real.png`、`/tmp/alphaagent-quant-signal-plan-tab-real.png`。
- 2026-06-14 财报口径服务化复核：`financial_coverage_summary` 和历史可见财报评分已抽到 `alphaagent/server/services/quant/financials.py`，筛选/股票详情和回测评分共用同一 `publish_date <= trade_date` 口径。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "financial_coverage or financial_scores_from_context" -q` 为 2 passed；全量回测测试仍为 133 passed；`uv run python -m compileall alphaagent/server/services/quant alphaagent/server/services/backtest alphaagent/server/api` 通过；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告。
- 2026-06-14 金安国纪财报口径浏览器复核：`/stocks/002636.SZSE` 显示“财报口径 / 本地财报 / 回测可用 / 披露日晚于区间 / 缺披露日”，无 failed requests 和 console errors。API 返回本地财报 20、回测可用 20、缺披露日 0、未来披露 0、最新披露日 2026-04-29。截图：`/tmp/alphaagent-stock-002636-financial-coverage-real.png`。
- 2026-06-14 股票详情策略对比统一接口复核：新增 `GET /api/quant/symbols/{vt_symbol}/strategy-comparison`，`/stocks/002636.SZSE` 改为单次请求展示多策略评分日、BUY、WATCH、最佳匹配和财报口径；默认起点对齐 `2025-10-14`。API 返回金安国纪低吸 BUY 23、突破 BUY 18、两个策略各 162 个评分日。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 136 passed；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告；`docker compose up -d --build alphaagent-api alphaagent-web` 后真实浏览器验证 `127.0.0.1` 和 `localhost` 均可访问，无 failed requests 和 console errors。截图：`/tmp/alphaagent-stock-002636-strategy-comparison-fixed.png`、`/tmp/alphaagent-quant-after-strategy-comparison-fixed.png`、`/tmp/alphaagent-quant-localhost-after-strategy-comparison-fixed.png`。
- 2026-06-14 股票详情组合回测买/没买诊断复核：`/stocks/002636.SZSE` 的历史 BUY 行新增“追踪”，组合回测复核面板可输入回测 ID 和信号日，调用 `/api/backtests/{id}/candidate-trace` 展示候选动作、计划执行日、订单状态、现金、持仓市值、总权益和诊断信息。真实浏览器验证 `#62 + 002636.SZSE + 2026-06-03` 显示“理论买入信号存在，但执行日 14:30 价格没有满足尾盘入场条件，因此没有下真实组合订单”，现金 `36.12万`、持仓市值 `60.81万`、总权益 `96.93万`；无 failed requests 和 console errors。截图：`/tmp/alphaagent-stock-002636-candidate-trace-20260603.png`。
- 2026-06-14 普通入口旧口径清理复核：扫描 `frontend/src/features/quant`、`QuantTradingPage`、`DataManagementPage`、`StockDetailPage`、`frontend/src/features/stocks` 和 `docs/alphaagent/quant_flow.md`，普通量化入口没有 `5m/10m` 严格回测、`部分就绪` 或旧版次日开盘入口；剩余命中仅为股票看盘 5m/15m、多周期历史说明或旧报告兼容说明。文档已把 `legacy_next_open` 降级为旧报告兼容，不再作为当前验证目标。验证：`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告；`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 136 passed；真实浏览器复核 `/quant`、`localhost:5173/quant` 和 `/stocks/002636.SZSE` 无 failed requests 和 console errors。截图：`/tmp/alphaagent-quant-cleanup-regression.png`、`/tmp/alphaagent-stock-002636-cleanup-trace-regression.png`。
- 2026-06-14 回测钻取全量核查复核：新增 `GET /api/backtests/{id}/drilldown-options`，`#62` 返回 `date_count=85`、`symbol_count=61`；`/quant -> 回测 -> 交易归因` 日期下拉 85 项、股票下拉 61 项。真实浏览器可选中 `000338.SZSE` 这类有拒单但无成交的股票，显示“有拒单”和中文原因“尾盘入场未触发”；无 failed requests，只有 React Router v7 future warning。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "day_detail or symbol_detail or trades or signal_events or candidate_trace or drilldown or reason_label" -q` 为 13 passed；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告；`docker compose up -d --build alphaagent-api` 后 `/api/health` 正常。截图：`/tmp/alphaagent-quant-drilldown-options.png`、`/tmp/alphaagent-quant-drilldown-rejected-symbol.png`。
- 2026-06-14 回测读侧重构第一步：新增 `alphaagent/server/services/backtest/queries.py`，把交易归因日期/股票选项聚合和原因中文标签从 `engine.py` 抽出；`engine.py` 保留兼容 wrapper。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "drilldown_options or reason_label or day_detail or symbol_detail or signal_events or candidate_trace" -q` 为 10 passed；`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py` 通过；`pnpm --dir frontend run build` 通过，仅 Vite chunk 体积警告；`docker compose up -d --build alphaagent-api` 后 `/api/backtests/62/drilldown-options` 仍返回 85 个日期、61 只股票，浏览器回归无 failed requests 和 console errors。截图：`/tmp/alphaagent-quant-drilldown-after-queries.png`。
- 2026-06-14 回测读侧重构继续：`backtest_trades()`、`backtest_equity()`、`backtest_day_detail()`、`backtest_symbol_detail()` 的数据库查询迁到 `queries.py`，`engine.py` 保留同名 wrapper。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "trades_api or day_detail or symbol_detail or backtest_equity or signal_events or drilldown_options or candidate_trace" -q` 为 11 passed；`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py` 通过；`pnpm --dir frontend run build` 通过；`docker compose up -d --build alphaagent-api` 后真实 API `/trades`、`/equity`、`/days/2026-06-12`、`/symbols/000338.SZSE`、`/drilldown-options` 均返回 ready，浏览器回归交易归因无 failed requests 和 console errors。截图：`/tmp/alphaagent-quant-drilldown-after-read-query-move.png`。
- 2026-06-14 回测组合级复盘补强：新增 `GET /api/backtests/{id}/daily-decisions` 和 `GET /api/backtests/{id}/trade-attribution`。前者按执行日分页展示候选、理论计划、订单、成交、拒单、买入占用、卖出回款、实现盈亏和总权益；候选按 `signal_date` 映射到执行日。后者按全组合成交和每日持仓快照做亏损归因，默认按 `pnl_asc` 看最差交易，并返回闭仓/未平仓、胜率、已实现盈亏、亏损合计和最大单笔亏损。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 162 passed；`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py` 通过；`pnpm --dir frontend run build` 通过；`docker compose up -d --build alphaagent-api alphaagent-web` 后真实浏览器 `/quant -> 回测 -> 交易归因` 显示“每日候选到成交复盘”和“组合亏损归因”，`#62` 每日复盘为 85 天、归因为 21 笔，无 failed requests 和 console errors。截图：`/tmp/alphaagent-real-browser/quant-daily-attribution.png`、`/tmp/alphaagent-real-browser/quant-daily-attribution-interactions.png`、`/tmp/alphaagent-real-browser/quant-daily-pagination-panel.png`。

严格分钟真实模拟回测 12：

- 缺口来源：先运行严格回测 11（2026-02-02 至 2026-06-11，`minute_entry_required=true`）生成 192 个 `tail_entry_not_triggered` 缺口，再通过 `/api/backtests/11/minute-gaps.csv` 导出为 `memory/06_backtests/alphaagent_minute_gap_backtest_11_2026-02-02_2026-06-11.csv`。
- TDX dry-run：`POST /api/data-sync/imports/minute-bars/tdx-gaps` 对 192 个缺口读取 5376 行、预覆盖 192 个缺口。
- TDX 正式导入：写入 5376 行 `tdx_public_hq` 1 分钟线；导入后审计 `ready`，192/192 覆盖，覆盖率 100%。
- 严格流水线：旧 `0.1.0` 引擎曾用回测 11 缺口文件生成回测 ID 12；该报告现在仅保留为补数覆盖记录，绩效需要用 `0.1.1` 重跑。
- 旧回测 12 原指标：区间 2026-02-02 至 2026-06-11，期末权益 1,065,953.89，总收益 6.60%，最大回撤 -2.22%，胜率 62.96%，盈亏比 2.77，Sharpe 2.42。因 `0.1.0` 卖出撮合缺陷，这些绩效指标不能继续引用。
- 成交真实性：买入 30 笔，分钟尾盘成交 30 笔，日线开盘回退 0 笔。
- 参数网格：文件 `memory/06_backtests/alphaagent_validation_grid_12_2026-02-02_2026-06-11.csv` 保留为历史文件；因同属 `0.1.0`，不再引用其收益排名或正收益结论。
- 文件：`memory/06_backtests/2026-06-11_backtest_12_strict_tdx_minute_report.md` 和 `memory/06_backtests/alphaagent_backtest_12_2026-02-02_2026-06-11.csv`。
- 复核命令：`uv run pytest tests/alphaagent -q` 164 passed, 1 skipped, 1 warning；`uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db` 通过；`cd frontend && npm run build` 通过，仅 Vite chunk 体积警告。

新版回测撮合复核（2026-06-12）：

- `0.1.1` 修复卖出撮合：D 日收盘确认退出信号，D+1 开盘成交。
- 新宽松回测 `#8`：2025-10-14 至 2026-06-11，主板 120 只，期末权益 942,738.58，总收益 -5.73%，最大回撤 -15.47%，胜率 32.18%，买入 93 笔全部为 D+1 开盘回退。
- 结论：`#8` 可用于验证新版撮合和页面审计，但仍不是严格尾盘低吸验证；长短区间严格分钟回测需要用 `0.1.1` 重跑。
- 验证：`uv run pytest tests/alphaagent -q` 为 174 passed, 1 skipped, 1 warning；`cd frontend && npm run build` 通过；`docker compose up -d --build alphaagent-api alphaagent-web` 后 `/api/health` 正常；浏览器 smoke 确认 `/quant` 回测页显示 `0.1.1`、`#8`、宽松模拟结论和 100% 开盘回退。
- 提交前复核：`uv run pytest tests/alphaagent -q` 为 175 passed, 1 skipped, 1 warning；`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 79 passed, 1 warning；`cd frontend && npm run build` 通过，仅 Vite chunk 体积警告。

## 2026-06-11 精简和提交准备

- 按 `karpathy-guidelines` 做小范围精简：把 TDX、Tushare、vn.py 三个缺口导入桥重复的缺口 CSV 加载逻辑收敛为 `alphaagent.server.services.data_sync.load_minute_gap_requirements()`。
- 继续做低风险精简：`minute_gap_vendor_manifest*` 直接调用 `load_minute_gap_requirements()`，删除只转发的私有包装函数；提交前统一清理暂存文本文件 CRLF/行尾空白。
- 没有重构回测撮合、评分或前端页面结构，避免在真实回测刚跑通后扩大风险面。
- 验证：
  - `uv run pytest tests/alphaagent -q`：164 passed, 1 skipped, 1 warning。
  - `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`：通过。
  - `cd frontend && npm run build`：通过，仅 Vite chunk 体积警告。
- 下次优化优先级：
  1. 不改行为地拆小 `alphaagent/server/services/data_sync.py`，优先按“分钟线导入/缺口审计/供应商清单”和“同步任务”分模块。
  2. 给 `/quant` 页面拆组件，优先拆 `MinuteDataPanel`，保持现有 API 和交互不变。
  3. 给回测报告 CSV 里的 dict 字段做更稳定的 JSON 序列化，减少后续分析解析成本。
  4. 长区间严格回测仍需补 2026-01 至 2026-05 更早分钟线，优先 Tushare/RQData/XT/QMT/券商 CSV。
