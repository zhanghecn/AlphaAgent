# Decisions

## 2026-06-07

- 保留 `AGENTS.md` 作为 Codex/后续协作入口。
- 用户要求后续不要主动提交或推送；只有用户明确说“提交”或“push”时才执行 git commit/push。
- 删除之前生成的本地 A 股教程 md、临时 py、临时 CSV 数据，因为它们没有充分基于项目结构和源码梳理。
- 新建 `memory/` 作为长期上下文地图，按类型维护项目事实。
- 需求分析文档单独放在 `requirements/`，不混在 `memory/` 中。
- 新增 `requirements/alphaagent_functional_design.md` 作为功能模块与执行流程设计文档。
- 新增 `requirements/alphaagent_service_frontend_execution_plan.md` 作为 vn.py 服务化、前后端分工、API 草案和 MVP 执行计划。
- 项目外显名称改为 `AlphaAgent`，目标是基于 vn.py 做服务端化 A 股自动量化、Agent 智能选股和交易系统。
- 不重命名 `vnpy/` Python 包目录，也不修改 Python 发行包名 `vnpy`，避免破坏 vn.py 插件依赖和已有导入路径。
- 后续重写文档时，必须同时覆盖：
  - 项目整体结构。
  - 源码入口。
  - 数据接入链路。
  - A 股相关插件和能力边界。
  - 如何调试看数据。
  - 如何从选股/策略/回测/实盘逐步搭建系统。

## 2026-06-11

- 量化选股、组合回测、持仓分组、模拟账户和 `/quant` 工作台已作为 AlphaAgent 自研业务层实现；未修改 `vnpy/` 核心包。
- “主力洗盘/试探/游资”统一作为价格、成交量、资金流、热度、龙虎榜等可观测代理信号处理，不作为真实主力意图断言。
- 回测采用 D 日收盘信号、D+1 可执行成交；分钟线存在时尝试 14:30-14:57 接近可见 MA5 成交，否则标记为次日开盘回退。当前分钟线覆盖不足，不能宣称已完成真实尾盘大量验证。
- 财报评分只使用 `publish_date <= trade_date` 的数据；缺披露日财报不进入真实回测评分。已支持从现金流量表补经营现金流和现金流质量，但全量稳定同步仍需优化。
- 回测 9 为当前最新真实模拟表：2025-10-14 至 2026-06-11，初始资金 100 万，期末权益 144.64 万，总收益 44.64%，最大回撤 -6.87%，胜率 53.67%，盈亏比 1.87，Sharpe 3.04。
- 回测 9 文件：`memory/06_backtests/2026-06-11_backtest_9_report.md` 和 `memory/06_backtests/alphaagent_backtest_9_2025-10-14_2026-06-11.csv`。
- 回测 10 为严格尾盘分钟验证：`minute_entry_required=true`，不允许 D+1 开盘回退；同区间同 1500 标的下 0 笔买入成交，收益 0%，证明当前分钟线覆盖不足以验证尾盘低吸真实表现。
- 回测报告/API/CSV 和 `/quant` 前端增加“成交真实性检查”，将分钟尾盘成交数、日线开盘回退数、尾盘成交占比、开盘回退占比作为显式诊断。
- 对严格尾盘回测 10 生成分钟缺口清单 `memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv`，包含 794 条待补分钟线订单、101 个交易日、194 只股票；公共 EastMoney 1 分钟接口请求历史日期仍返回最近日期，已增加日期过滤避免误写错期数据。
- 为补严格尾盘分钟回测缺口，新增历史分钟 CSV 导入和审计入口：`GET /api/data-sync/imports/minute-bars/template.csv`、`POST /api/data-sync/imports/minute-bars`、`POST /api/data-sync/imports/minute-bars/audit-gaps`、`POST /api/data-sync/imports/minute-bars/gap-template.csv`。当前只是导入/校验通道完成，尚未导入覆盖回测区间的真实历史分钟数据。
- 分钟 CSV 导入/缺口审计支持 `file_path`，但只允许读取 `data/imports/` 和 `memory/06_backtests/` 下的 `.csv`，用于大型外部分钟线文件，同时避免任意服务器路径读取风险；分钟线文件导入已改为流式分批写入，降低大文件内存占用。
- 对回测 10 缺口做审计：794 个缺口中当前只覆盖 2 个，缺 792 个，覆盖率 0.2519%；严格尾盘胜率和收益仍不能真实计算。
- 新增 `/api/vnpy/local-bars` 和 `alphaagent.server.services.vnpy_integration.local_data`，可把 AlphaAgent 本地日线表转换为 vn.py `HistoryRequest`/`BarData` 语义；这是本地对象适配桥，不等同于官方 vn.py Datafeed 或 A 股实盘 Gateway。
- 新增 `/api/vnpy/import-minute-bars` 和 `alphaagent.server.services.vnpy_integration.database_import`，可在 vn.py 数据库已有 A 股 1 分钟 BarData 时导入到 AlphaAgent `stock_minute_bars`；它不负责下载数据，也不等同于 A 股实盘 Gateway。
- 新增 `/api/vnpy/import-minute-bars/gaps`，可按严格尾盘缺口 CSV 批量从 vn.py 数据库导入 D+1 尾盘窗口分钟线并返回覆盖审计；当前 `/root/.vntrader/database.db` 四张 vn.py 数据表均为 0 行，dry-run 读取 0 行，因此严格尾盘真实回测仍必须先补真实历史分钟数据。
- 新增 `/api/data-sync/imports/minute-bars/tushare-gaps`，作为正规历史分钟数据补数通道；使用 Tushare Pro `stk_mins`，只从环境变量 `TUSHARE_TOKEN` 读取 token，并按目标交易日过滤返回行。当前没有配置 token/分钟权限，所以仍不能完成严格尾盘真实回测。
- 公共 EastMoney/Sina 分钟 K 和 Sina 历史逐笔已复核，不能可靠补 2026-01 至 2026-06 历史 1 分钟缺口；后续不要把这些公共源作为严格分钟回测依据。
- 新增 `/api/backtests/strict-minute-pipeline` 作为严格尾盘最终入口：先审计缺口，缺口未 ready 时返回 `blocked_by_minute_gaps`，不运行回测；ready 后才运行并持久化严格分钟回测。长区间回测 10 缺口覆盖率仍为 0.2519%，但较近区间已经通过 TDX 补数完成严格分钟真实模拟回测 12。
- 新增 `/api/backtests/{backtest_id}/minute-gaps.csv`，可从严格回测中被 `tail_entry_not_triggered` 拒绝的买入订单导出标准缺口 CSV，作为 TDX/Tushare/vn.py/外部 CSV 补数输入。
- 新增 `/api/data-sync/imports/minute-bars/tdx-gaps`，可从通达信公开行情服务器按缺口批量读取历史 1 分钟 K 线。实测回测 11 缺口 192 个 symbol-date 全部可取，导入 5376 行后审计覆盖 100%；公开源回溯范围有限，2026-01 的长区间缺口仍需正规数据源补齐。
- 严格分钟真实模拟回测 12 已完成：区间 2026-02-02 至 2026-06-11，回测表 `memory/06_backtests/alphaagent_backtest_12_2026-02-02_2026-06-11.csv`，报告 `memory/06_backtests/2026-06-11_backtest_12_strict_tdx_minute_report.md`；总收益 6.60%，最大回撤 -2.22%，胜率 62.96%，盈亏比 2.77，Sharpe 2.42，买入 30 笔全部为真实分钟尾盘成交，日线开盘回退 0 笔。
- 按 `karpathy-guidelines` 做第一次小范围精简：只合并重复缺口 CSV 加载逻辑为 `load_minute_gap_requirements()`，并删除一个只转发的私有包装函数；不扩大到回测撮合或页面结构重构。后续继续优化时仍以小步、可验证、不改变行为为原则。
- 新增供应商补数清单接口 `/api/data-sync/imports/minute-bars/vendor-manifest(.csv)`；当前严格缺口可导出 794 条 symbol-date 请求清单，交给 Tushare/RQData/XT/QMT/券商导出后，再按 AlphaAgent 标准分钟 CSV 导入。
- 1500 标的大样本 54 组合参数网格已完成并导出到 `memory/06_backtests/alphaagent_validation_grid_9_2025-10-14_2026-06-11.csv`；54 组均为正收益，92.59% 跑赢样本等权，高摩擦组 100% 正收益，walk-forward 测试正收益 100%、超额正收益 60%。当前参数不是网格最优（总收益排名 39/54，样本外排名 46/54），不能把单次回测收益当作稳健收益承诺。
- vn.py A 股实盘/官方 A 股数据插件仍未安装配置；当前是 AlphaAgent 本地数据、业务回测、模拟持仓闭环，不是券商实盘接入完成。
