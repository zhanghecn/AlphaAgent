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
npm run dev -- --host 0.0.0.0 --port 5173
```

2026-06-11 验证过的备用端口：

- API: `http://localhost:8001`
- Frontend: `http://localhost:5175`
- 扩展回测表联调使用过 API `http://localhost:8002` 和 Frontend `http://localhost:5176`
- 指数基准、CSV 导出和参数化回测页面联调使用过 API `http://localhost:8003` 和 Frontend `http://localhost:5177`

本地 CORS 允许 `5173/5174/5175/5176/5177` 和 `8000/8001/8002/8003`，用于 Vite 自动换端口后的页面联调。

量化工作台：

- URL: `/quant`
- 页面能力：量化候选、参数化回测表、CSV 导出、反过拟合检查、模拟持仓。
- 2026-06-11 使用 Chrome headless 验证页面可加载真实推荐、扩展回测报告、指数基准、市场环境分段、反过拟合检查、模拟持仓和 vn.py 状态。
- 扩展回测页面截图：`/tmp/alphaagent-quant-expanded-report.png`。
- CSV 导出和市场环境分段页面截图：`/tmp/alphaagent-quant-report4-export.png`。
- 反过拟合检查页面截图：`/tmp/alphaagent-quant-robustness-report4.png`。

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
- 服务烟测：筛选、推荐、持仓、回测报告、vn.py 状态均返回；当前 vn.py 状态为 `partial`，A 股 Gateway 未就绪。
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
- 供应商补数清单：`POST /api/data-sync/imports/minute-bars/vendor-manifest` 和 `.csv` 可把严格缺口转成外部数据供应商请求清单；当前回测 10 缺口生成 794 条 symbol-date 请求、194 只股票、101 个交易日、区间 2026-01-08 至 2026-06-11、窗口 14:30-14:57。

回测 9：

- 报告：`memory/06_backtests/2026-06-11_backtest_9_report.md`
- 交易明细：`memory/06_backtests/alphaagent_backtest_9_2025-10-14_2026-06-11.csv`
- 区间：2025-10-14 至 2026-06-11。
- 样本：股票库 4535；区间有日线 1582；满足 >=80 根日线 1551。
- 指标：总收益 44.64%，最大回撤 -6.87%，胜率 53.67%，盈亏比 1.87，Sharpe 3.04。
- 参数网格：54 组合完整重跑完成，文件 `memory/06_backtests/alphaagent_validation_grid_9_2025-10-14_2026-06-11.csv`；正收益组合占比 100%，样本外正收益组合占比 100%，跑赢样本等权占比 92.59%，Walk-forward 测试正收益占比 100%，测试超额为正占比 60%。
- 执行：分钟尾盘成交 0，日线开盘回退成交 181；这说明尾盘规则已接入但分钟历史覆盖不足，不能声称已完成大量分钟级尾盘验证。

严格尾盘回测 10：

- CSV：`memory/06_backtests/alphaagent_backtest_10_2025-10-14_2026-06-11.csv`
- 参数：1500 标的，`minute_entry_required=true`，只承认 D+1 14:30-14:57 接近可见 MA5 的分钟成交，不允许日线开盘回退。
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
- 回测 API 和 `/quant` 前端已暴露 `intraday_entry`、`minute_entry_required`、`tail_entry_start`、`tail_entry_end`、`tail_entry_ma5_tolerance_pct`，可直接运行宽松回退或严格分钟尾盘两种模式；报告和 CSV 会输出“成交真实性检查”。
- `/api/vnpy/local-bars` 已把 AlphaAgent 本地 `stock_daily_bars` 转换为 vn.py `HistoryRequest`/`BarData` 语义，作为本地研究和后续策略适配桥；它不是官方 vn.py Datafeed，也不提供实时行情或实盘交易。
- `/api/vnpy/import-minute-bars` 是从 vn.py 数据库向 AlphaAgent 补 `stock_minute_bars` 的导入桥；前提是 vn.py 数据库里已经有对应 A 股 1 分钟历史数据。
- `/api/vnpy/import-minute-bars/gaps` 是按严格尾盘缺口批量从 vn.py 数据库补数的导入桥；当前本机 vn.py 数据库为空，不能直接生成严格真实回测。
- `/api/data-sync/imports/minute-bars/tushare-gaps` 是按严格尾盘缺口从 Tushare Pro `stk_mins` 补数的导入桥；需要 `.env` 配置 `TUSHARE_TOKEN` 且账号开通分钟数据权限，当前未配置。
- `/api/data-sync/imports/minute-bars/tdx-gaps` 是按严格尾盘缺口从 TDX 公开行情服务器补数的导入桥；已实测可补 2026-05 至 2026-06 的 1 分钟尾盘窗口，但公开源回溯范围有限，长区间仍需 Tushare/RQData/XT/QMT/券商 CSV。
- `/api/backtests/strict-minute-pipeline` 是最终严格回测入口；补齐分钟线后优先调用它生成真实严格回测表。
- `/api/backtests/{backtest_id}/minute-gaps.csv` 可从严格回测被拒买入订单导出分钟缺口 CSV，用于后续补数和严格流水线。
- `/api/data-sync/imports/minute-bars/vendor-manifest.csv` 可作为给 Tushare/RQData/XT/QMT/券商导出工具的数据需求清单；回填数据仍必须按 `vt_symbol,bar_time,open,high,low,close,volume,turnover` 导入。
- `sync_stock_minute_bars` 已支持 `symbols`、`start_date`、`end_date` 参数，用于未来接入支持历史分钟回填的数据源后按缺口清单补数据；当前公共源对历史 1 分钟回填不可用。
- 外部历史分钟线补数入口已接入：`GET /api/data-sync/imports/minute-bars/template.csv` 下载模板，`POST /api/data-sync/imports/minute-bars` 传 `csv_text`、`interval`、`source`、`dry_run` 导入到 `stock_minute_bars`；`POST /api/data-sync/imports/minute-bars/audit-gaps` 审计缺口覆盖。这只是补数和校验通道，不代表当前已经有足够历史分钟数据完成严格尾盘回测。
- 大文件建议路径：把外部导出的 1 分钟 K 线 CSV 放到 `data/imports/`，然后用 `file_path="data/imports/文件名.csv"` 预检查、导入、再审计缺口覆盖。

严格分钟真实模拟回测 12：

- 缺口来源：先运行严格回测 11（2026-02-02 至 2026-06-11，`minute_entry_required=true`）生成 192 个 `tail_entry_not_triggered` 缺口，再通过 `/api/backtests/11/minute-gaps.csv` 导出为 `memory/06_backtests/alphaagent_minute_gap_backtest_11_2026-02-02_2026-06-11.csv`。
- TDX dry-run：`POST /api/data-sync/imports/minute-bars/tdx-gaps` 对 192 个缺口读取 5376 行、预覆盖 192 个缺口。
- TDX 正式导入：写入 5376 行 `tdx_public_hq` 1 分钟线；导入后审计 `ready`，192/192 覆盖，覆盖率 100%。
- 严格流水线：`POST /api/backtests/strict-minute-pipeline` 用回测 11 缺口文件返回 `ready`，生成回测 ID 12。
- 回测 12 指标：区间 2026-02-02 至 2026-06-11，期末权益 1,065,953.89，总收益 6.60%，最大回撤 -2.22%，胜率 62.96%，盈亏比 2.77，Sharpe 2.42。
- 成交真实性：买入 30 笔，分钟尾盘成交 30 笔，日线开盘回退 0 笔。
- 参数网格：54 组合重跑完成，文件 `memory/06_backtests/alphaagent_validation_grid_12_2026-02-02_2026-06-11.csv`；54/54 正收益，样本外 54/54 正收益，高摩擦 54/54 正收益，收益区间 6.08% 至 10.86%，默认参数收益排名 41/54；Walk-forward 只有 1 个折叠，不能当作跨周期稳健证明。
- 文件：`memory/06_backtests/2026-06-11_backtest_12_strict_tdx_minute_report.md` 和 `memory/06_backtests/alphaagent_backtest_12_2026-02-02_2026-06-11.csv`。
- 复核命令：`uv run pytest tests/alphaagent -q` 164 passed, 1 skipped, 1 warning；`uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db` 通过；`cd frontend && npm run build` 通过，仅 Vite chunk 体积警告。

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
