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
- 历史记录：回测 9 曾作为 `0.1.0` 宽松回测样本保存，文件为 `memory/06_backtests/2026-06-11_backtest_9_report.md` 和 `memory/06_backtests/alphaagent_backtest_9_2025-10-14_2026-06-11.csv`；2026-06-12 发现 `0.1.0` 卖出撮合存在时间顺序错误，收益、胜率、回撤和参数验证结论均需用 `0.1.1` 重跑后再引用。
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
- 历史记录：严格分钟回测 12 买入 30 笔全部来自真实分钟尾盘成交、日线开盘回退 0 笔，可作为补数覆盖记录参考；但该报告运行在 `0.1.0` 卖出撮合上，收益 6.60%、最大回撤 -2.22%、胜率 62.96% 等绩效指标必须用 `0.1.1` 重跑后再引用。
- 按 `karpathy-guidelines` 做第一次小范围精简：只合并重复缺口 CSV 加载逻辑为 `load_minute_gap_requirements()`，并删除一个只转发的私有包装函数；不扩大到回测撮合或页面结构重构。后续继续优化时仍以小步、可验证、不改变行为为原则。
- 新增供应商补数清单接口 `/api/data-sync/imports/minute-bars/vendor-manifest(.csv)`；当前严格缺口可导出 794 条 symbol-date 请求清单，交给 Tushare/RQData/XT/QMT/券商导出后，再按 AlphaAgent 标准分钟 CSV 导入。
- `0.1.0` 生成的参数网格和 walk-forward 结果同样受卖出撮合时间错误影响，不能作为稳健性结论；保留 CSV 仅作历史排查材料。
- vn.py A 股实盘/官方 A 股数据插件仍未安装配置；当前是 AlphaAgent 本地数据、业务回测、模拟持仓闭环，不是券商实盘接入完成。

## 2026-06-12

- `/quant` 的产品边界调整为量化研究工作台：负责筛选候选、组合回测、回测方法说明、反过拟合检查和订单/成交审计，不再把持仓当作量化页内部功能。
- `/quant` 按任务页签组织为“候选 / 回测 / 日志 / 数据”，避免把候选、参数、回测、日志、补数工具全部纵向堆叠。默认页只让用户先看候选和持仓摘要。
- 量化候选、回测报告、审计日志、单股回测和模拟持仓中凡是展示股票，都必须尽量显示股票名称并附 vt_symbol；只有数据导入缺口 CSV 这类文件键场景可以只显示代码。
- 持仓作为独立模块 `/portfolio` 维护：分组、自选加入、量化候选同步、自动模拟持仓、成本价、买卖时间和买卖依据都在持仓页查看。
- 全量组合回测必须明确显示“历史逐日动态候选”：每个历史交易日只用当日及以前数据重新生成候选，下一交易日执行；不能让用户误解为“今天候选回测全部历史”。
- 单股回测放在股票详情页触发，后端走 `POST /api/backtests/symbol`，前端在 K 线图显示真实成交买卖点；如果没有交易，应显示没有满足入场信号，而不是为了可视化强造买卖点。
- 日志先采用结构化审计 API：`GET /api/backtests/{backtest_id}/audit` 返回策略版本、参数、方法、订单、成交和事件说明；暂不引入独立日志系统或 WebSocket。
- 分钟线补数是严格尾盘回测的高级数据准备流程，默认不应占据 `/quant` 主流程；同步和补数的长期入口优先归到 `/data`。
- 前端展示股票身份时优先复用 `StockIdentityLink`，默认“名称 + vt_symbol”整块可点击进入股票详情；不要在量化、持仓、日志页面重复手写不可点击的股票文本。
- 量化页维护原则：主路径只保留状态、决策表和明确操作；方法说明、审计、补数、参数验证要分区或折叠，避免把解释文案和工具控件继续堆成长页面。
- 板块过滤规则：所有股票展示页面仍显示全量股票；默认排除科创板、北交所、创业板只发生在量化筛选/组合回测生成股票池时，默认仅主板，且必须可配置包含主板、创业板、科创板、北交所。
- 股票身份规则扩展为“名称 + vt_symbol + 板块标签”；创业板、科创板、北交所、主板标签应尽量出现在所有股票展示位置。缺后端字段时，前端可按 vt_symbol 兜底推导。
- 回测撮合版本 `0.1.1` 修复卖出时间顺序：D 日收盘确认退出信号，只能 D+1 开盘撮合；所有 `strategy_version < 0.1.1` 的回测、参数网格和 walk-forward 绩效结果都标为需重跑。证据见 `memory/06_backtests/2026-06-12_backtest_engine_audit.md`。
- 新版宽松组合回测 `#8`（2025-10-14 至 2026-06-11，主板 120 只，`0.1.1`）结果为总收益 -5.73%、最大回撤 -15.47%、胜率 32.18%；买入 93 笔全部为 D+1 开盘回退，仍不能宣称验证了“尾盘到 5 日线低吸”。
- `/quant` 回测页新增第一屏“回测结论/可信度”提示：旧版本显示“需重跑”，新版但全部开盘回退显示“宽松模拟”，避免用户从一堆指标里猜这份结果是否可信。
- 量化问题审计已归档到 `memory/06_backtests/2026-06-12_quant_issue_audit.md`：当前优先修复顺序为“最近买卖点”排序、vn.py 状态文案、财报落库/覆盖说明、日线成交额落库或单位修正、每日逐股持仓快照和日期/股票钻取。
- 日线成交额同步链路已修复：股票日线优先使用腾讯 `newfqkline`，成交额按“万元 -> 元”入库；旧数据缺 `turnover` 时流动性估算按 A 股成交量单位“手”使用 `close * volume * 100`。金安国纪定向回填后当前低吸策略历史买点从 0 次变为 26 次，但 `2026-06-12` 这种强势加速仍应由独立突破/加速策略处理，不通过硬改低吸策略门槛解决。
