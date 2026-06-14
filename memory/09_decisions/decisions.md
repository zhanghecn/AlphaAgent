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
- 旧版回测曾采用 D 日收盘信号、D+1 可执行成交；该口径现在只作为历史兼容记录。2026-06-11 曾把默认回测模型调整为尾盘混合：上一交易日可见候选在执行日 14:30 真实快照成交，缺分钟线时使用执行日收盘价代理尾盘；该默认值已在后续 2026-06-14 收敛为普通新建回测默认 `strict_1430 / 1m / 14:30`，尾盘混合只保留为研究对比。
- 财报评分只使用 `publish_date <= trade_date` 的数据；缺披露日财报不进入真实回测评分。已支持从现金流量表补经营现金流和现金流质量，但全量稳定同步仍需优化。
- 历史记录：回测 9 曾作为 `0.1.0` 宽松回测样本保存，文件为 `memory/06_backtests/2026-06-11_backtest_9_report.md` 和 `memory/06_backtests/alphaagent_backtest_9_2025-10-14_2026-06-11.csv`；2026-06-12 发现 `0.1.0` 卖出撮合存在时间顺序错误，收益、胜率、回撤和参数验证结论均需用 `0.1.1` 重跑后再引用。
- 回测 10 为严格尾盘分钟验证：`minute_entry_required=true`，不允许 D+1 开盘回退；同区间同 1500 标的下 0 笔买入成交，收益 0%，证明当前分钟线覆盖不足以验证尾盘低吸真实表现。
- 回测报告/API/CSV 和 `/quant` 前端增加“成交真实性检查”，当前主指标区分 `minute_1430` 真实快照成交、`daily_close_proxy` 收盘代理成交、严格 14:30 拒单、涨跌停阻断；旧 D+1 开盘回退只作为旧报告兼容风险显示。
- 对严格尾盘回测 10 生成分钟缺口清单 `memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv`，包含 794 条待补分钟线订单、101 个交易日、194 只股票；公共 EastMoney 1 分钟接口请求历史日期仍返回最近日期，已增加日期过滤避免误写错期数据。
- 为补严格尾盘分钟回测缺口，新增历史分钟 CSV 导入和审计入口：`GET /api/data-sync/imports/minute-bars/template.csv`、`POST /api/data-sync/imports/minute-bars`、`POST /api/data-sync/imports/minute-bars/audit-gaps`、`POST /api/data-sync/imports/minute-bars/gap-template.csv`。当前只是导入/校验通道完成，尚未导入覆盖回测区间的真实历史分钟数据。
- 分钟 CSV 导入/缺口审计支持 `file_path`，但只允许读取 `data/imports/` 和 `memory/06_backtests/` 下的 `.csv`，用于大型外部分钟线文件，同时避免任意服务器路径读取风险；分钟线文件导入已改为流式分批写入，降低大文件内存占用。
- 对回测 10 缺口做审计：794 个缺口中当前只覆盖 2 个，缺 792 个，覆盖率 0.2519%；严格尾盘胜率和收益仍不能真实计算。
- 新增 `/api/vnpy/local-bars` 和 `alphaagent.server.services.vnpy_integration.local_data`，可把 AlphaAgent 本地日线表转换为 vn.py `HistoryRequest`/`BarData` 语义；这是本地对象适配桥，不等同于官方 vn.py Datafeed 或 A 股实盘 Gateway。
- 新增 `/api/vnpy/import-minute-bars` 和 `alphaagent.server.services.vnpy_integration.database_import`，可在 vn.py 数据库已有 A 股 1 分钟 BarData 时导入到 AlphaAgent `stock_minute_bars`；它不负责下载数据，也不等同于 A 股实盘 Gateway。
- 新增 `/api/vnpy/import-minute-bars/gaps`，可按严格尾盘缺口 CSV 批量从 vn.py 数据库导入执行日 14:30 快照分钟线并返回覆盖审计；当前 `/root/.vntrader/database.db` 四张 vn.py 数据表均为 0 行，dry-run 读取 0 行，因此严格尾盘真实回测仍必须先补真实历史分钟数据。
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
- 回测撮合版本 `0.1.1` 修复卖出时间顺序：当时的默认模型为 D 日收盘确认退出信号、D+1 开盘撮合；所有 `strategy_version < 0.1.1` 的回测、参数网格和 walk-forward 绩效结果都标为需重跑。证据见 `memory/06_backtests/2026-06-12_backtest_engine_audit.md`。
- 新版宽松组合回测 `#8`（2025-10-14 至 2026-06-11，主板 120 只，`0.1.1`）结果为总收益 -5.73%、最大回撤 -15.47%、胜率 32.18%；买入 93 笔全部为 D+1 开盘回退，仍不能宣称验证了“尾盘到 5 日线低吸”。
- `/quant` 回测页新增第一屏“回测结论/可信度”提示：旧版本显示“需重跑”，新版但全部开盘回退显示“宽松模拟”，避免用户从一堆指标里猜这份结果是否可信。
- 量化问题审计已归档到 `memory/06_backtests/2026-06-12_quant_issue_audit.md`：当前优先修复顺序为“最近买卖点”排序、vn.py 状态文案、财报落库/覆盖说明、日线成交额落库或单位修正、每日逐股持仓快照和日期/股票钻取。
- 日线成交额同步链路已修复：股票日线优先使用腾讯 `newfqkline`，成交额按“万元 -> 元”入库；旧数据缺 `turnover` 时流动性估算按 A 股成交量单位“手”使用 `close * volume * 100`。金安国纪定向回填后当前低吸策略历史买点从 0 次变为 26 次，但 `2026-06-12` 这种强势加速仍应由独立突破/加速策略处理，不通过硬改低吸策略门槛解决。

## 2026-06-13

- 量化页候选核查改为“起始交易日 -> 最新交易日”的区间候选：前端通过 `/api/quant/trading-dates` 选择本地真实交易日，调用 `POST /api/quant/screen-runs/range` 逐日生成候选并落库；`GET /api/quant/screen-runs` 继续叠加显示已运行筛选的编号和候选数。页面只保留一个“生成区间候选”入口，避免两个筛选按钮误导用户。
- 组合回测和股票详情页单股回测在列表层区分 `run_type`；量化页默认只展示组合回测，单股回测继续用于股票详情买卖点可视化，不挤占量化页主回测结果。
- “所有股票先回测一遍”采用信号计划优先：新组合回测额外写 `backtest_signal_events`，对每只股票独立维护理论持仓状态，记录历史 BUY/SELL 信号；不为每只股票单独生成资金曲线。
- 理论信号金额换算采用总资金等权预览：`每笔预算 = 总资金 / 最大持仓数`，买入按 A 股 100 股整数手换算，卖出沿用最近一次理论买入数量。该预览用于核查候选和买卖点金额，不替代真实组合资金曲线；价格来源必须复用当前回测执行模型，不能再默认用执行日开盘价。
- 金额、现金、持仓市值、总权益等真实组合结果仍以 `backtest_trades`、`backtest_daily_equity`、`backtest_daily_positions` 和日期/股票钻取接口为准；`backtest_signal_events` 不受组合现金和仓位竞争约束。

## 2026-06-14

- 严格尾盘买入对照回测 `#42` 已完成：同 `#41` 参数但 `minute_entry_required=true`，只成交 2 笔尾盘买入、拒绝 783 笔买入，收益 -0.25%；`#41` 收益 56.57% 但 152/153 笔买入来自 D+1 开盘回退。当前不能用现有分钟线覆盖判断严格尾盘策略收益是否更高，必须先补齐历史分钟线。证据见 `memory/06_backtests/2026-06-14_backtest_42_strict_tail_comparison.md`。
- 回测执行参数 `minute_interval` 当前量化主流程只支持 `1m`，严格 14:30 缺口补数也只走 `1m` 快照；历史 `5m/10m` 尝试保留为过期排查记录，不再作为新建回测或严格缺口补数的产品功能。
- 用当前 1m 数据派生 5m/10m 后运行严格回测 `#43/#44`，收益仍约 -0.25%、仅 2 笔买入、约 780 个尾盘缺口拒单；结论是周期切换没有解决收益问题，根因仍是长区间历史分钟线覆盖不足。
- 执行质量报告新增严格尾盘拒单诊断：有 `tail_entry_not_triggered` 拒单时显示 warning 和 `strict_tail_rejected_count`，避免“已成交买入 100% 来自分钟尾盘”掩盖大量未成交缺口。
- 分钟缺口补数回到数据同步主入口：`sync_stock_minute_bars` 新增 `mode=backtest_gaps`，支持按 `backtest_id/gap_file_path/gap_csv_text` 调 AkShare/TDX/Tushare 补执行日 14:30 快照；`/data` 页面“股票分钟 K 线”任务提供参数面板。不要再把这类工作默认处理成外部手工补数据脚本。
- 严格尾盘买入当前默认是执行日 `14:30-14:30` 快照，只要求那一刻的 1 分钟 K 线；早期 `14:30-14:57` 窗口只作为过期历史记录保留。回测、严格流水线、AkShare/TDX/Tushare/vn.py 缺口导入、缺口审计、供应商清单和 `/data` 面板默认值已统一。
- 默认 `1m` 最符合“14:30 那一刻”的语义；`5m/10m` 在量化主流程中已移除，通用分钟 K 线导入/查看的多周期能力另行处理。
- 量化清理/重构完整计划已按当前源码状态重写到 `docs/plans/2026-06-14-quant-current-state-cleanup-roadmap.md`，并在 `#62` 真实复核后更新。当前结论是严格量化主流程只保留 `1m/14:30`；股票详情看盘和通用分钟导入可保留 `5m/15m/30m/60m`，但必须和严格 14:30 执行快照分开；`10m` 只保留拒绝测试和历史说明。后续优先级是清理旧入口和误导文案，拆 `engine.py` 报告/持久化，拆分钟缺口服务和前端补数向导，再把股票详情策略对比与指定组合回测 ID 的买/没买原因合并。
- 策略失败规则阈值和展示口径已修正：`_recommendation_to_db()` 按策略默认硬门槛生成失败规则，突破策略不再被 68 分低吸阈值影响；`/api/quant/strategies` 返回策略动作标签、证据字段标签和主指标字段。候选页和股票详情按策略显示主指标，低吸为 `MA5距离`，突破为 `距60日高点 / 量能比`。真实浏览器复核金安国纪页面和突破候选空状态通过，截图为 `/tmp/alphaagent-stock-002636-strategy-metrics.png`、`/tmp/alphaagent-quant-breakout-metrics.png`。
- 策略选择已产品化到候选页、组合回测页、股票详情单股回测和量化信号复核面板，当前注册策略为 `mainline_leader_pullback / 0.1.1` 和 `breakout_confirmation / 0.1.0`；普通入口不再硬编码“低吸”作为唯一策略。
- 严格 14:30 补数主流程改为回测 ID 优先：`audit-gaps`、供应商清单、AkShare/TDX/Tushare/vn.py 缺口导入、严格流水线和前端补数向导都可从 `backtest_id` 生成缺口需求；CSV 仍保留为供应商文件/高级兜底。
- `#52` 低吸组合回测（2026-02-02 至 2026-06-13，主板，`tail_close_hybrid`）确认负收益：期末权益 865,299.76，总收益 -13.47%，最大回撤 -14.09%，平仓交易 19，成交明细 40 条；其中买入/成交质量仍以混合尾盘口径为准，`minute_1430_count=2`、`daily_close_proxy_count=19`，不能称为纯分钟真实回测。
- `#53` 突破策略组合回测已验证策略参数贯通：同区间期末权益 1,023,351.11，总收益 +2.34%，最大回撤 -0.21%，平仓交易 2；但全部成交来自 `daily_close_proxy`，样本太小，只能说明策略链路可运行，不能说明策略稳健。
- 金安国纪 `002636.SZSE` 已复核：2025-10-14 至 2026-06-13 区间内低吸策略 `entry_signal_count=23`，突破策略 `entry_signal_count=18`；本地财报 20 条、可用 20 条，最新可用披露日 2026-04-29。之前“历史总会有一次”的问题当前结论是确实存在历史买点，若组合没买需要继续按具体回测 ID 查资金、排名、持仓上限和执行日成交约束。
- 回测卖出时序已修正：日线卖出信号按 D 日收盘生成，D+1 再按 14:30 或收盘代理执行，避免用执行日完整日线 `close/high` 后又在同日 14:30 卖出的未来函数风险。旧 `#58` 等报告不能再作为当前绩效结论。
- `/api/backtests/{id}/minute-coverage` 和 `/quant` 的“14:30覆盖”面板已加入，用于一眼区分 `ready / mixed_proxy / missing_snapshots / strategy_not_triggered / empty`，并展示买入数、真实 14:30 占比、收盘代理、严格拒单和下一步。
- 当前严格 14:30 重跑结果以 `#59` 为准：2026-02-02 至 2026-06-13，主板 80 只，`strict_1430`，期末权益 990,530.15，总收益 -0.9470%，最大回撤 -5.3325%，平仓交易 16；买入 20/20 都是 14:30 真实快照，无收盘代理，但仍有 12 个缺 14:30 快照的严格拒单。证据见 `memory/06_backtests/2026-06-14_backtest_59_strict_1430_recheck.md`。
- 回测真实性当前结论：候选/回测使用交易日及以前日线，财报按 `publish_date <= trade_date` 过滤，卖出时序已改为信号后下一交易日执行；`#59` 已成交买入为真实 14:30 快照，但路径仍有 12 个缺快照拒单，必须补齐后再重跑判断完整严格收益。过拟合尚未证明解决，`#59` 跑赢本地样本等权 0.3192%，但未跑赢随机样本均值，仍需多年全 A、walk-forward、参数敏感性和基准超额检验。
- 执行模型对比已产品化到 `/api/backtests/{id}/execution-model-comparison` 和 `/quant` 回测页“回测真实性结论”。`#52` 真实复核显示：尾盘混合 -13.47%，严格 14:30 -0.33%，但严格模式只有 3 笔买入且 193 个严格拒单、188 个缺 14:30 快照，因此不能把严格收益当成完整策略收益；下一步应先按严格缺口补齐分钟快照再重跑。
- 真实浏览器复核已用 headless Chromium 通过：`/quant` 候选、回测、数据页，`/data` 回测缺口同步页，`/stocks/002636.SZSE` 金安国纪复核页，以及 `http://127.0.0.1:5173/quant` 均可访问；截图为 `/tmp/alphaagent-quant-candidates-verified.png`、`/tmp/alphaagent-quant-backtest-verified.png`、`/tmp/alphaagent-quant-data-verified.png`、`/tmp/alphaagent-data-page-verified.png`、`/tmp/alphaagent-stock-002636-verified.png`。
- 量化清理继续按小步重构推进：严格量化主流程只保留 `1m / 14:30`，普通 UI 不暴露 `5m/10m` 严格周期、不暴露旧 `legacy_next_open` 入口、不让用户编辑尾盘窗口；`5m/15m/30m/60m` 仅保留在通用分钟线同步/股票详情看盘能力里，`10m` 只保留拒绝测试和历史记录。
- 回测账本计算从 `engine.py` 抽到 `alphaagent/server/services/backtest/ledger.py`：买入/卖出金额、滑点、佣金、印花税、100 股整数手、现金不足重算都由纯函数负责；当前目标是等价重构，不改变策略阈值和收益口径。
- 信号计划关联逻辑从 `engine.py` 抽到 `alphaagent/server/services/backtest/signal_plan.py`：理论信号与真实订单的匹配、`plan_status`、中文状态标签和候选追踪诊断由独立纯函数负责；当前仍保持 API 返回契约不变。下一步才考虑把 `planned_execute_date / actual_trade_date / execution_model / price_source / proxy_used / cash_after / total_equity` 等字段进一步落成结构化列或统一 DTO。
- 财报可见性统一由 `alphaagent/server/services/quant/financials.py` 管理：股票详情“财报口径”和回测评分都使用 `publish_date <= trade_date`，并显式返回缺披露日数量和晚于回测日披露数量。该改动只统一口径和解释，不改变财报数据本身，也不改变策略阈值。
- 当前严格 14:30 结果更新为 `#62`：2026-02-02 至 2026-06-13，主板 80 只，`strict_1430`，期末权益 `949,180.14`，总收益 `-5.0820%`，最大回撤 `-9.5778%`；买入 21/21 使用真实 14:30 快照，收盘代理 0，缺 14:30 快照拒单 0。`#60` 的 5 个缺口已通过 TDX 写入 5 行补齐后重跑，证据见 `memory/06_backtests/2026-06-14_backtest_62_strict_1430_recheck.md`。
- 回测真实性结论更新：`#62` 是当前同口径 `max_symbols=80` 的完整严格 14:30 回测，已成交买入可按真实 14:30 解读，剩余 83 个严格拒单属于尾盘条件未触发，不是缺数据。负收益未解决，过拟合也未证明解决；策略未跑赢样本等权、主要指数、随机样本均值和高摩擦压力测试，后续需多年全 A walk-forward、参数敏感性和基准超额检验。
- 股票详情策略对比已收敛为统一接口：`GET /api/quant/symbols/{vt_symbol}/strategy-comparison` 返回各策略的评分日、BUY 次数、WATCH 天数、最佳匹配日、失败规则和财报口径；`/stocks/002636.SZSE` 默认区间对齐 `2025-10-14` 后显示低吸 BUY 23 次、突破 BUY 18 次。真实浏览器复核 `127.0.0.1` 和 `localhost` 均无 console error / failed requests。
- 回测钻取 P0 已完成第一版：`GET /api/backtests/{id}/drilldown-options` 给 `/quant -> 回测 -> 交易归因` 提供完整日期和股票选项，日期来自权益曲线，股票覆盖成交、订单、理论信号和持仓快照。`#62` 真实返回 85 个日期、61 只相关股票，可核查有拒单但无成交的股票；订单/信号/候选追踪统一增加中文原因字段。下一步不先加策略，继续按计划拆 `backtest/engine.py` 查询/报告职责和分钟缺口服务。
- 量化清理计划已收敛为 `docs/plans/2026-06-14-quant-cleanup-master-plan.md`；此前两份 `2026-06-14-quant-current-state-cleanup-roadmap.md` 和 `2026-06-14-quant-refactor-and-feature-roadmap.md` 已标记为被取代。后续执行以 master plan 为准：先完成读侧迁移和普通入口清理，再拆 `backtest/engine.py`、分钟缺口服务、前端补数向导、策略实现，最后做组合级策略对比和新策略。
- 已按 master plan 推进第一轮结构清理：`backtest_candidate_trace()` 和 `backtest_audit()` 的数据库读取迁到 `alphaagent/server/services/backtest/queries.py`；`BacktestParams/MinuteBar/Position/Trade/ScoreContext` 迁到 `alphaagent/server/services/backtest/schemas.py` 并保持 `engine` 兼容导出；扩展指标、成交真实性检查和 CSV 内容生成迁到 `alphaagent/server/services/backtest/reports.py` 并保持 `engine` wrapper。`/data` 的 `sync_stock_minute_bars mode=backtest_gaps` 普通表单不再允许编辑尾盘开始/结束，固定传 `14:30-14:30`。验证：读侧定向测试 12 passed，参数/账本/信号测试 21 passed，报告/CSV/真实性测试 26 passed，`compileall` 通过，`pnpm --dir frontend run build` 通过。
- 量化 master plan 已按当前源码状态刷新：Phase 0/Phase 1 和 `schemas.py`、`reports.py` 基础拆分标为已完成；下一步优先拆 `backtest/persistence.py`、`backtest/scoring.py`、`backtest/validation.py`，再拆分钟缺口服务和 `MinuteDataWizard.tsx`。`/data` 普通回测缺口路径继续固定 `1m / 14:30`，但缺口 CSV/file_path 仍需收进高级兜底区。
- `alphaagent/server/services/backtest/persistence.py` 和 `alphaagent/server/services/backtest/scoring.py` 已从 `engine.py` 拆出并保持 `engine` 私有 wrapper 兼容；持久化写表、表字段过滤、评分候选、BUY/WATCH 策略入口均已转发到新模块。验证：`pytest -k "persist or table_values"` 3 passed，`pytest -k "strict_entry or watch or scoring or signal_events or candidate_trace"` 11 passed，读侧/账本/报告相关三组定向测试分别 12/14/17 passed，`compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py` 通过。
- `alphaagent/server/services/backtest/validation.py` 已从 `engine.py` 拆出并保持 wrapper 兼容；参数网格、摘要诊断、walk-forward、排名和数值提取逻辑迁入新模块。验证：`pytest -k "validation_grid or walk_forward or robustness"` 6 passed；综合 `candidate_trace/audit/drilldown/persist/strict_entry/signal_events/validation_grid/walk_forward/report/execution_quality` 36 passed；`engine.py` 当前约 3374 行。
- `alphaagent/server/services/minute_gaps.py` 已从 `data_sync.py` 拆出第一批纯函数：严格 1m 校验、缺口 CSV 解析、导入模板、供应商清单 CSV/JSON、Tushare 代码转换和行 API 转换；`data_sync.py` 保留 wrapper 兼容。验证：`pytest -k "minute_gap or minute_bars or vendor_manifest or backtest_gaps or tdx or tushare or akshare or obsolete_10m"` 27 passed，相关 `compileall` 通过。
- `alphaagent/server/services/minute_gaps.py` 继续承接严格 14:30 缺口覆盖审计：`audit_minute_gap_requirements()` 和 `minute_gap_coverage_counts()` 已迁入新模块；`data_sync.py` 保留 `_audit_minute_gap_requirements()` 和 `_minute_gap_coverage_counts()` wrapper，避免破坏 provider/vn.py 导入模块和旧测试的 monkeypatch 入口。验证：`pytest -k "audit_minute_gap or minute_gap_audit or minute_gap_vendor or minute_bars or tdx_gap or tushare or akshare or vnpy_gap_import or strict_minute_pipeline"` 为 31 passed；相关 `compileall` 通过；`/api/backtests/62/minute-coverage` 仍返回买入 21/21 真实 14:30、收盘代理 0、缺快照拒单 0。
- `/data` 的 `sync_stock_minute_bars` 回测缺口表单已收敛为普通路径优先：主表单只显示回测 ID、数据源、固定 `1分钟 / 14:30快照`、最大缺口和预检查；服务器缺口文件路径移入“高级兜底”。验证：`pnpm --dir frontend run build` 通过，仅 Vite chunk size 警告。
- `frontend/src/features/quant/MinuteDataWizard.tsx` 已完成第一阶段拆分：状态、mutation 和请求编排留在主文件，严格补数普通区、高级缺口来源、provider 导入、外部 CSV 兜底、缺口示例和消息展示迁入 `MinuteDataWizardPanels.tsx`。普通区继续只显示回测 ID、provider 和固定 `1分钟 / 14:30快照`；服务器缺口文件路径、缺口 CSV 和外部分钟线 CSV 只在高级展开区显示。严格流水线有源回测 ID 时前端不再传 `max_symbols=1500`，由后端复用源回测参数；无回测 ID 的高级 CSV/file_path 来源必须勾选确认后才允许按默认股票池参数运行。验证：`pnpm --dir frontend run build` 通过；`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 139 passed；`pytest -k "strict_minute_pipeline"` 为 5 passed；真实浏览器复核 `/quant -> 数据` 展开前后和高级来源确认通过，截图 `/tmp/alphaagent-real-browser/quant_data_tab_refactor.png`、`/tmp/alphaagent-real-browser/quant_data_tab_expanded_precise_refactor.png`、`/tmp/alphaagent-real-browser/quant_strict_pipeline_confirmation.png`。后续仍需继续拆 `MinuteDataWizardPanels.tsx`。
- 量化清理 master plan 已按当前源码重新收敛：严格主流程只保留 `1m / 14:30 / strict_1430`；`5m/15m/30m/60m` 仅保留在股票详情看盘和通用分钟导入；`10m` 只保留拒绝测试和历史说明。当前执行顺序固定为：先收口 `MinuteDataWizardPanels.tsx` 半拆状态，再拆 `backtest/engine.py` 模拟主循环，再拆 `data_sync.py` 标准分钟导入/provider 编排，再清理 `/data` 严格缺口表单，之后才拆策略实现、做组合级策略对比和新增策略。旧计划文件已标记为被 `docs/plans/2026-06-14-quant-cleanup-master-plan.md` 取代。
- 前端补数向导半拆状态已收口：新增 `frontend/src/features/quant/MinuteCsvFallbackPanel.tsx`，`MinuteDataWizardPanels.tsx` 只保留共享类型、`MinuteStep` 和 re-export，来源/provider/CSV 兜底分文件维护。验证：`pnpm --dir frontend run build` 通过；真实浏览器 `/quant -> 数据` 普通区和高级区均渲染成功，无 console error / failed request，截图 `/tmp/alphaagent-real-browser/quant_data_after_panel_split.png`、`/tmp/alphaagent-real-browser/quant_data_expanded_after_panel_split_scoped.png`。
- 后端组合回测模拟主循环已迁到 `alphaagent/server/services/backtest/simulation.py`；`engine._simulate()`、`_signal_events_for_day()`、`_sell_reason()` 等保留兼容 wrapper，测试和旧 monkeypatch 入口不变。验证：`uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/api/backtests.py` 通过；定向 `pytest -k "signal_events or strict_entry or watch or sell or cash or commission or stamp or slippage or lot or validation_grid"` 为 22 passed；完整 `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 139 passed。
- 标准分钟导入和严格 14:30 provider 编排已从 `data_sync.py` 拆出：`alphaagent/server/services/minute_imports.py` 负责标准分钟 CSV/文件导入、路径安全校验和 upsert；`alphaagent/server/services/minute_provider_imports.py` 负责 `backtest_id/gap_csv/file_path -> provider -> import result` 编排。`data_sync.py` 保留兼容 wrapper 和 job runner。验证：分钟/provider 定向测试 28 passed，完整 `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 139 passed，相关 `compileall` 通过。
- 新建组合回测默认执行模型已改为 `strict_1430`：`BacktestParams`、`POST /api/backtests` 缺省值和 `/quant -> 回测` 前端默认值一致；`tail_close_hybrid` 保留为高级研究对比模型。真实浏览器确认 `/quant -> 回测` 默认下拉值为“严格14:30”，无 `5m/10m` 严格入口，无 console error / failed request，截图 `/tmp/alphaagent-real-browser/quant_backtest_strict_default_precise.png`。
- `/data` 与金安国纪详情页真实浏览器复核通过：`/data` 显示回测缺口、最近分钟线、AkShare/TDX provider、固定 14:30 快照和高级 CSV 兜底，无 `10m`；`/stocks/002636.SZSE` 显示量化信号复核和单股回测，运行单股回测后能显示买卖点相关内容。截图 `/tmp/alphaagent-real-browser/data_strict_gap_provider_real.png`、`/tmp/alphaagent-real-browser/stock_002636_single_backtest_real.png`。
- `#62` API 复核补充：`/api/backtests/62/drilldown-options` 返回 85 个日期、61 只相关股票；`/api/backtests/62/trades?limit=5` 返回总成交 39 条；`/api/backtests/62/days/2026-06-12` 返回现金 `613,146.14`、持仓市值 `336,034.00`、总权益 `949,180.14`、买入 2、卖出 2、持仓快照 3。当前回测结果可以按日期/股票核查资金、订单、成交和持仓路径。
- 策略实现已从 `alphaagent/server/services/quant/factors.py` 拆到 `alphaagent/server/services/quant/strategies/pullback.py` 和 `alphaagent/server/services/quant/strategies/breakout.py`；`factors.py` 保留公共指标和兼容 wrapper。`strategy_registry.py` 直接注册策略模块。验证：策略相关定向测试通过，完整 `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 139 passed。
- 量化筛选服务已继续拆分：`screening_loaders.py` 承接数据加载，`screening_payloads.py` 承接 API/DB payload、失败规则和默认风控，`screening_persistence.py` 承接筛选运行写库、推荐写库和“量化候选”分组同步；`screening.py` 降到 776 行并保留私有 wrapper 兼容测试。验证：`compileall` 通过，完整量化测试 139 passed。
- 最新真实浏览器复核已用 headless Chrome 访问 `/quant`、`/quant -> 回测`、`/quant -> 数据`、`/data`、`/stocks/002636.SZSE`：严格 `1分钟 / 14:30快照` 文案、回测成交分页、回测 ID/provider 补数路径、高级 CSV 兜底和金安国纪量化信号复核均可见；无 console error / failed request，普通量化路径无 `10m/10分钟` 文案。
- 金安国纪当前按正确接口复核：`GET /api/quant/symbols/002636.SZSE/signal-history?start=2026-02-02&end=2026-06-13&strategy=mainline_leader_pullback` 返回 `scored_date_count=85`、`entry_signal_count=16`、`watch_count=69`，最佳 BUY 日为 2026-02-09；`#62` 指定股票钻取没有成交，说明问题不是“完全筛不出”，而是组合排序、资金/仓位和严格 14:30 执行约束下未实际买入。
- 量化清理 master plan 已按当前源码重新收敛为 `docs/plans/2026-06-14-quant-cleanup-master-plan.md`：严格回测只保留 `1m / 14:30 / strict_1430`，`tail_close_hybrid` 仅作研究对比；`5m/15m/30m/60m` 只保留在股票详情看盘和通用分钟同步/导入，`10m` 只保留拒绝测试和历史说明。后续最高优先级是锁住严格主路径、补强策略对比解释、补强个股诊断、做数据质量仪表板，再做后端/前端大文件等价拆分。
- 策略同口径对比 P0 已修复：`strategy_comparison._summary()` 现在显式把 `0.0` 当作有效收益值，`0%` 会优于负收益；但无成交的 `0%` 不能被表达为策略验证成功，下一步需要在策略对比 UI/API 中增加“完整严格/缺快照/无成交/收盘代理”等可解释状态。真实 API 复核同区间 `mainline_leader_pullback=-5.081985865099958%`、`breakout_confirmation=0.0%` 时，`best_strategy_id=breakout_confirmation`。
- `limit_up_after_pullback / 0.1.0` 已作为正式策略注册并完成严格样本回测 `#66`：2026-02-02 至 2026-06-13，主板 `max_symbols=80`，`strict_1430 / 1m / 14:30`，总收益 `-1.0622%`，买入 2，卖出 0，持仓中 2，缺 14:30 快照拒单 11。该策略能捕获金安国纪等强势涨停后回踩信号，但当前样本仍负收益且分钟覆盖不完整，不能宣称有效。证据见 `memory/06_backtests/2026-06-14_backtest_66_limit_up_pullback_strict_1430.md`。
- 个股诊断摘要已补充候选动作、排名、分数、计划执行日和信号日现金/持仓市值/总权益；金安国纪 `002636.SZSE` + `#62` + `2026-02-09` 显示 BUY、排名 2、分数 84.4645、现金/总权益 100 万，主原因仍是 `candidate_not_planned`。严格 `14:30` 拒单原因已拆分：缺目标分钟快照使用 `missing_1430_snapshot`，有快照但 MA5/尾盘条件不满足使用 `tail_entry_not_triggered`；报告、策略对比、缺口 CSV、中文原因和股票详情同步识别。
- 量化验证面板继续补强：`POST /api/backtests/strategy-comparison` 的每个策略行新增 `quality_status/quality_label/quality_warning`，无成交 `0%` 会标为“未成交/缺14:30快照，不能验证收益”；summary 同时区分“收益排序最优”和“数据可验证最优”，真实 API 复核同口径三策略时收益排序最优为未成交的 `breakout_confirmation=0%`，数据可验证最优为 `mainline_leader_pullback=-5.081985865099958%`。`GET /api/backtests/{id}/data-quality` 新增回测数据质量仪表板，聚合 14:30 覆盖、收盘代理、缺快照拒单、财报历史可见性和样本覆盖；`#62` 数据质量为 warning：买入 21/21 真实 14:30、收盘代理 0、缺快照 0，但 83 笔严格拒单来自尾盘条件未触发。验证：`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 155 passed；`pnpm --dir frontend run build` 通过；真实浏览器 `/quant -> 回测`、点击“运行对比”和 `/stocks/002636.SZSE` 无 console error / failed request，截图 `/tmp/alphaagent-real-browser/quant_backtest_strategy_compare_clicked.png`、`/tmp/alphaagent-real-browser/stock_002636_diagnostics_with_backtest_62.png`。
- 量化 master plan 已按当前真实状态再次刷新到 `docs/plans/2026-06-14-quant-cleanup-master-plan.md`：普通组合回测入口固定 `strict_1430 / 1m / 14:30 / strict_entry=true`，`tail_close_hybrid` 只作研究对比，`legacy_next_open` 只作旧报告兼容；`5m/15m/30m/60m` 只保留在股票详情看盘和通用分钟同步/导入，`10m` 只保留拒绝测试和历史说明。当前最高优先级是逐日候选到成交复盘、回测亏损归因、金安国纪标准诊断解释、继续等价拆大文件；在多年全 A、walk-forward、参数敏感性和基准超额验证前不宣称策略稳定盈利。
- P0/P1 继续完成：`QuantWorkflowGuide` 不再提示“没有分钟线只能做宽松回测”，改为严格 14:30 缺快照会拒单并引导补缺口或研究对比；股票详情单股回测默认改为 `strict_1430 / 1m / 14:30`；`/quant -> 候选` 新增候选运行覆盖面板，可核查起点至本地交易日的已运行/未运行、最新同步日和近期 BUY/候选数量；`/quant -> 回测 -> 交易归因` 新增股票决策时间线，串联理论信号、真实订单、成交和持仓路径。验证：`pnpm --dir frontend run build` 通过；`uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q` 为 156 passed；`compileall` 通过；Docker 重建后真实浏览器确认候选覆盖、严格默认、决策时间线和金安国纪单股严格文案可见，且无 console error / failed request。
- 前端继续小步拆分：回测决策时间线已从 `BacktestDrilldownPanel.tsx` 抽到 `frontend/src/features/quant/BacktestDecisionTimeline.tsx`，保持 UI 行为不变；抽取后 `pnpm --dir frontend run build` 通过，Docker 重建后真实浏览器仍能看到候选运行覆盖、严格默认和决策时间线。
- 回测真实性复核仍以 `#62` 为当前严格基线：`GET /api/backtests/62/data-quality` 和 `/minute-coverage` 返回买入 21/21 使用真实 14:30 快照，收盘代理 0，缺快照拒单 0，83 笔严格拒单来自 `tail_entry_not_triggered`。这说明当前负收益不是因为缺 14:30 数据导致，主要需要复核策略阈值、候选质量和稳健性；金安国纪 `002636.SZSE` 在 `#62` 里存在理论 BUY 信号但未成交，API 显示多次 `tail_entry_not_triggered`。
- 候选运行覆盖面板的 BUY/WATCH 计数已改为后端按 `quant_recommendations.action` 聚合，而不是误用评分池 `signal_count`。`GET /api/quant/screen-runs` 新增 `buy_recommendation_count` 和 `watch_recommendation_count`；最新低吸运行 `#177` 返回候选 20、BUY 13、WATCH 7。验证：完整量化测试 156 passed，前端 build 通过，真实浏览器确认 `/quant -> 候选` 显示 BUY候选/WATCH候选且无 console error / failed request。
- `#62` 已完成 54 组参数网格和 walk-forward 真实性复核归档到 `memory/06_backtests/2026-06-14_backtest_62_validation_grid_recheck.md`：54/54 参数组合中正收益 0、样本外正收益 0、跑赢样本等权 0、高摩擦正收益 0；默认参数排名 44/54；walk-forward 只有 1 个折叠且测试收益 -4.74%、平均超额 -22.08%。结论是 `#62` 成交执行真实性较强，但策略稳健性很弱，不能宣称已经抗过拟合或稳定盈利。
- 回测日线加载已修复预热窗口：组合回测现在会向开始日前额外加载 160 个自然日 * 2 的历史 K 线用于 MA60、60 日回撤等指标，但权益曲线和交易日仍只从用户选择的开始日期记录。该修复解决了旧回测从 `start` 当天才加载 K 线导致早期信号计划缺失的问题。
- 候选追踪新增 `not_planned_context`：当候选存在但未进入组合理论计划时，会返回回测起止、首个/最后信号日、股票池名次、候选排名、候选 BUY/WATCH 数、当天理论计划数、当天候选前列和计划买入列表。股票详情和候选追踪面板会显示“未进计划核查”，避免只给“候选未进入组合计划”的泛化结论。
- 金安国纪 `002636.SZSE` 复核更新：旧 `#62` + `2026-02-09` 仍显示候选 BUY 排名 2、分数 84.4645，但属于旧回测信号明细空窗，首个可复盘信号日为 `2026-05-08`；用修复后的同参数严格回测 `#70` 重跑后，`2026-02-09` 已进入理论买入计划并在 `2026-02-10` 尝试执行，但真实组合订单被拒绝，原因是 `missing_1430_snapshot`（缺执行日 14:30 的 1m 快照）。
- 组合回测核查入口更新：`/quant -> 回测 -> 交易归因` 现在优先看组合级“每日候选到成交复盘”和“组合亏损归因”，再下钻到单日/单股。每日复盘由 `/api/backtests/{id}/daily-decisions` 提供，不再只靠日期下拉；组合亏损由 `/api/backtests/{id}/trade-attribution` 提供，不再需要逐个股票点开才能找最差交易。`#62` 当前返回 85 个执行日、21 笔归因记录，最差三笔为华天科技、豫能控股、长飞光纤，均是 `minute_1430` 真实 14:30 成交。该功能只增强读侧核查，不改变回测撮合逻辑。
- `#70` 说明预热修复能恢复早期理论信号计划，但也暴露早期分钟缺口：`GET /api/backtests/70/minute-coverage` 返回买入成交 21/21 使用真实 14:30、收盘代理 0，同时严格拒单 483，其中缺 14:30 快照 400、尾盘入场未触发 83。`#70` 绩效与 `#62` 一样为总收益 -5.081985865099958%，但数据质量状态为 `missing_snapshots`，不能替代 `#62` 作为完整严格基线。
