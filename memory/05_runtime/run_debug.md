# Run and Debug

这个文件只记录当前有效的运行、调试和验证入口。历史回测过程、长命令输出和截图清单放在 `memory/06_backtests/` 或具体计划文档中。

## Current State

- 项目外显名称是 AlphaAgent，Python 发行包名和源码包目录仍保留 `vnpy`，用于兼容 vn.py 插件。
- 官方桌面 GUI 入口仍是 `examples/veighna_trader/run.py`，当前只注册 `CtpGateway`、`CtaStrategyApp`、`CtaBacktesterApp`、`DataManagerApp`，不能视为 A 股实盘或全市场实时行情已接入。
- AlphaAgent Web/API 是当前主要研发入口，包含 A 股数据同步、量化候选、组合回测、股票详情、持仓和数据管理。
- 普通组合回测默认执行模型是 `legacy_next_open / strict_entry=true`：D 日收盘产生信号，D+1 按日线开盘价执行买入/卖出。14:30/分钟线只保留为实时、盘中确认、分钟数据同步和旧报告兼容能力，不再是历史主流程默认依赖。
- `tail_close_hybrid` 只用于研究对比，`strict_1430` 只用于旧报告兼容、分钟数据复核或未来盘中确认。普通历史主流程不再暴露 `5m/10m`。

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

- `/quant`: 单一主操作“刷新候选并回测”；普通视图只保留“候选/回测”两个入口。候选默认观察评分前 100 并分页，每页 20；组合执行 BUY 前 20，最大持仓 10，页面直接展示“为什么这个分数”和回测归因；回测页不再把“信号计划”作为普通 tab 暴露。
- `/data`: 数据同步、回测缺口补 14:30 快照、通用分钟线同步。
- `/portfolio`: 自选分组、量化候选分组、模拟持仓。
- `/stocks/:vtSymbol`: 股票详情、财报口径、策略复盘和“为什么这个分数”。股票详情支持 `交易复盘 / 候选信号` 切换：交易复盘只显示实际买入、卖出和拒绝执行，候选信号只显示理论候选/信号。点击 K 线或指标柱可查看较前一日涨跌、跳空、振幅、均线距离和量比。

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
- `POST /api/backtests`: 新建组合回测，普通历史主流程默认日线 D+1 开盘。
- `GET /api/backtests?run_type=portfolio`: 组合回测列表；普通 `/quant` 和股票详情页使用 `baseline_only=true`，只取当前公开策略版本里结束到最新本地交易日、起点最早的产品基线回测，避免短区间实验顶掉当前全历史基线。
- `GET /api/backtests/{id}/minute-coverage`: 旧严格分钟报告/高级复核接口，普通历史主流程不依赖它。
- `GET /api/backtests/{id}/report`: 默认返回轻量回测报告，供 `/quant` 回测首屏快速显示收益、最近成交和基础方法；需要基准、样本内外、市场分层、反过拟合和反未来函数深度分析时，传 `include_analysis=true`。
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

- API 容器健康，`GET /api/quant/strategies` 返回当前公开策略 `mainline_dragon_pullback / 0.1.21`。
- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true` 当前返回 `#190 / 0.1.21`：覆盖 `2025-03-26` 至 `2026-06-17`，收益约 `+81.32%`，最大回撤约 `-15.59%`，买入/卖出/持仓中 `224 / 214 / 10`。
- 当前代码证据是组合回测 `#190 / 0.1.21`：低吸蓄势可在 MA5/MA10/MA20 承接、缩量、MA 收敛改善且 MA20 未破时累计；至少 3 天吸筹后的首个温和拉升可确认 `stealth_low_suction`，执行候选前 `20`，最大持仓 `10`。
- 买入当天硬破位次日撤退实验 `#174 / 0.1.20` 已验证失败并从默认代码撤回：同区间收益约 `+51.51%`、最大回撤约 `-19.00%`，收益/PF/Sharpe 弱于 `#169`。不要把 `entry_day_breakdown_stop` 当作当前基线。
- 卖出侧早期破位实验 `#173 / 0.1.19` 已验证失败并从默认代码撤回：同区间收益约 `+54.40%`、最大回撤约 `-19.79%`，弱于 `#169`。不要把 `early_breakdown_stop` 当作当前基线。
- `#190` 不给低吸固定保留名额；低吸仍在同一候选池竞争。买入 setup 仍是 `dragon_pullback` 与 `stealth_low_suction` 两个内部 setup，不作为两个公开策略。
- `#186 / 0.1.22` 高位重复龙回头硬拒实验已验证失败并从默认代码撤回：同区间收益约 `+59.39%`、最大回撤约 `-18.13%`，弱于 `#190 / 0.1.21`。`002119.SZSE` 类重复高位龙回头风险只作为诊断证据，不作为默认硬拒买规则。
- `stealth_low_suction` 已作为独立 setup 与 `dragon_pullback` 并列计算并进入内部 lane；红星发展 `2026-02-11/02-12`、合肥城建 `2026-04-28/04-29/04-30`、埃斯顿 `2026-04-14` 起的多日低吸蓄势可由单股逐日评分识别。
- 东山精密 `002384.SZSE` 的 `2026-03-27` 至 `2026-04-01` 低吸段已修复：单股逐日评分显示低吸天数从 `1/2/3/4` 累计，`2026-04-01` 为可执行 `stealth_low_suction` BUY，`low_suction_launch_confirmed=true`。此前 `#175` candidate trace 显示该信号进入执行池第 `7` 名，但执行日满仓 `10/10` 且未触发换仓，所以有理论计划但没有真实订单。
- `#165` candidate-trace 关键结论：红星发展 `2026-02-11` 全部 BUY 原始排名 `238`，但进入低吸洗盘通道执行池第 `15` 名，执行日满仓 `10/10` 且未触发换仓；合肥城建 `2026-04-28` 原始排名 `293`，进入低吸洗盘通道执行池第 `8` 名，执行日满仓 `10/10` 且未触发换仓；埃斯顿 `2026-04-14` 原始排名 `250`，仍未进入执行前 `20`。
- 低吸执行/换仓边界：`#162 / 0.1.12` 收益约 `+30.19%`、最大回撤约 `-23.37%`，拒绝；`#163 / 0.1.13` 收益约 `+46.88%`、最大回撤约 `-16.71%`，回撤改善但收益牺牲过大，拒绝作为基线；`#165 / 0.1.15` 收益约 `+55.41%`、最大回撤约 `-21.17%`，是中间方向；`#167 / 0.1.16` 收益约 `+28.80%`，过度保守；`#168 / 0.1.17` 收益约 `+39.16%`、最大回撤约 `-27.63%`，低吸机会加分过宽，拒绝。
- 单股逐日评分接口 `GET /api/quant/symbols/{vt_symbol}/signal-history` 会重新按历史可见日线逐日计算，适合查连续低吸状态；`GET /api/backtests/{id}/candidate-trace` 查组合计划/订单/成交链路，适合解释为什么有信号但没买。两者不能混读。
- 当前数据库没有目标历史日期同版本 `quant_recommendations` 落库候选记录，历史候选页和组合回测信号计划仍存在数据源差异；后续应统一候选落库与回测理论计划的数据源。
- 最新源码验证：低吸涨停启动四因子定向测试 `3 passed, 1 warning`；此前完整套件为 `267 passed, 1 warning`，`compileall` 通过，`pnpm --dir frontend run build` 通过且只有既有 chunk-size warning，`git diff --check` 通过。API 容器健康，`/api/quant/strategies` 返回 `mainline_dragon_pullback / 0.1.21`。
- `GET /api/backtests/190/low-suction-start-factor-audit` 复核：`stealth_low_suction` 闭合交易 `83` 笔，胜率约 `28.92%`，弱/震荡市场代理胜率约 `24.24%`；`3-4` 因子桶胜率约 `28.57%`，低于 `0-1` 因子桶约 `30.77%`。连续上涨标签上 `3-4` 因子桶 MFE>=8% 约 `42.86%`，但弱/震荡市场里胜率仅约 `13.33%`，因此四因子继续作为诊断字段，不直接进入默认买入加分。

## Known Caveats

- vn.py A 股实盘 Gateway 和官方 A 股 Datafeed 插件仍未安装配置。
- 多年全 A、walk-forward、参数敏感性、市场环境分层、基准超额和高摩擦压力测试仍是策略可信度的必要验证。
- 旧 `strategy_version < 0.1.1` 的回测存在卖出撮合时序问题，只能作为历史排查材料。
- 当前公开策略代码为 `mainline_dragon_pullback / 0.1.21`，最新 `#190` 在当前本地样本中优于 `#172/#169/#137` 的收益和最大回撤；仍不能宣称稳定盈利或最终优化成功，参数敏感性和多年 walk-forward 尚未完成。
- 旧严格 14:30 报告只作为分钟模型历史材料；当前历史主流程是日线 D+1 开盘执行。
- 候选页落库推荐、单股逐日评分和组合回测理论计划仍需进一步统一展示口径。
- 不要默认使用 `0.1.22/#186` 那类“高位重复龙回头且缺少低吸蓄势”硬拒买规则；已验证全局收益/回撤弱于当前基线。
