# Decisions

这个文件记录仍然有效的长期决策。按日期产生的验证过程、接口输出和截图不放在这里；需要证据时链接到 `memory/06_backtests/`、`docs/plans/` 或具体源码。

## Project Boundary

- 项目外显名称是 AlphaAgent，目标是基于 vn.py 做服务端化 A 股量化研究、智能选股、策略回测、模拟持仓和后续交易工作流。
- 保留 Python 包名和源码目录 `vnpy`，不重命名为 AlphaAgent，避免破坏 vn.py 插件依赖和已有导入。
- 不修改继承的 `vnpy/` 核心包和官方 examples，除非用户明确要求或项目兼容性必须修改。
- AlphaAgent 自研业务层放在 `alphaagent/`、`frontend/`、`docs/`、`requirements/` 和 `memory/`。
- 需求分析和产品设计放在 `requirements/`，长期项目事实放在 `memory/`。

## Collaboration And Git

- 不主动 `git commit` 或 `git push`。只有用户明确要求“提交”或“push”时才执行。
- 工作区可能包含用户或前序模型改动，不能随意 revert、reset 或 checkout。
- 提交前优先做可验证的小步整理：编译、定向测试、前端 build、`git diff --check`。
- `memory/` 是项目地图，不是日记。新增事实时优先改写现有 overview，长报告放到 typed artifact。

## A-share Capability

- 当前 vn.py GUI 只注册 CTP，不能声称已经接入 A 股实盘或全 A 实时行情。
- A 股实盘交易应通过官方或兼容 Gateway，例如 XTP、TORA、OST、EMT。
- 历史数据应优先通过可验证的数据源或插件，例如 XT、RQData、Tushare、券商/QMT/TDX/vn.py 本地库。
- 免费公共分钟源只能作为近端补充，不能直接当作长区间严格回测依据。

## Quant Product Shape

- `/quant` 是量化研究工作台，主路径为一键策略研究、候选查看、组合回测、交易归因、数据质量和日志复核。
- `/portfolio` 是独立持仓模块，负责自选分组、量化候选分组、模拟持仓、成本价、买卖依据。
- 股票详情页 `/stocks/:vtSymbol` 承接单股回测、K 线买卖点、财报口径和组合回测复核。
- 量化页默认只展示组合回测；股票详情页生成的单股回测不混入量化页主列表。
- 股票展示尽量使用“名称 + vt_symbol + 板块标签”，并复用可点击的股票身份组件。
- 用户界面和 API message 不暴露 `replay` 这类内部工程词；统一称为“买卖记录”或“买卖执行记录”。接口路径、字段名和表名可先保持 `replay` 以避免兼容性迁移。

## Candidate And Strategy Rules

- 组合回测必须使用历史逐日动态候选：每个信号日只使用当日及以前可见数据生成候选，再在下一交易日执行。
- 前端只暴露“运行策略研究”主操作：页面调用 `POST /api/quant/research-runs` 创建后台研究任务并轮询状态；任务内部从用户选定交易日跑到本地最新交易日，自动补候选、生成买卖记录并运行组合回测。
- 候选区间生成是内部主量化过程；`persist=true` 时会跳过已存在成功交易日，只补缺失日期，并基于已落库 `quant_stock_signals` 生成统一 `strategy_replay_runs` / `strategy_replay_attempts`，不再让股票详情默认单独重算一套单股缓存。
- 量化页候选 tab 展示候选和最新买卖记录状态，不再要求用户单独理解或手动触发“生成区间候选/生成执行复盘”。
- 量化页候选默认日期优先选择当前公开策略最新已生成候选日；如果最新交易日尚未运行，不应默认展示空候选误导用户。工作流卡片必须同时显示本地日线最新交易日和候选最新日期，明确暴露候选滞后。
- 量化页候选 KPI 使用当前选中交易日实际推荐数；分组同步数只作为同步状态，不作为“候选数量”主指标。
- 量化页组合回测列表按当前公开策略和当前注册版本过滤；旧策略或旧版本回测不能挤掉当前策略回测。
- 普通用户入口只公开 `mainline_dragon_pullback` 一个策略；策略仍通过注册表管理，避免在 API/UI 里硬编码散落。
- 旧 `mainline_leader_pullback`、`breakout_confirmation`、`limit_up_after_pullback`、`trend_acceleration` 只保留为内部兼容和旧报告/对比工具能力，不再出现在普通策略列表和主流程下拉中。
- `WATCH` 只表示观察，不应作为自动组合买入信号；买入计划只应来自 `action=BUY` 并通过组合约束的候选。

## Backtest Execution

- 普通新建组合回测默认执行模型是 `legacy_next_open / strict_entry=true`：D 日收盘产生信号，D+1 按日线开盘价执行买入和卖出。
- 历史主流程不再依赖 `14:30` 分钟线。14:30/分钟快照只保留为未来实时数据、盘中确认、分钟数据同步和旧报告兼容能力。
- BUY 信号不等于实际购买。BUY 信号表示 T 日收盘后策略生成买入计划；实际购买必须经过 T+1 执行价、涨停/跌停、现金和仓位等约束。
- 执行拒绝原因必须精确区分：`limit_up_open_blocked` 是开盘涨停买不到，`limit_down_open_blocked` 是开盘跌停卖不出，`no_execute_bar` 是缺执行日 K 线，不能再合并成“涨停或缺数据”。
- `tail_close_hybrid` 和 `strict_1430` 保留为研究对比/旧报告兼容模型，不能当作当前历史主流程。
- `strategy_version < 0.1.1` 只作为旧报告兼容，旧绩效不作为当前策略结论。

## Single-stock Review

- 股票详情页默认优先读取最新组合回测的该股详情，把真实组合订单、成交和闭合收益标到 K 线；再读取 `/api/quant/symbols/{vt_symbol}/latest-state` 的最近全局量化过程状态补充评分、BUY 信号、候选计划、买卖记录和拒绝原因。个股页不暴露日期选择和手动单股回测入口，避免用户看到与全局量化过程不一致的第二套口径。
- 股票详情页不能用早于最新候选日期的旧买卖记录覆盖新候选状态；如果最新 `strategy_replay_runs.end_date` 早于最新 `quant_signal_runs.trade_date`，详情页状态应回退到最新候选筛选，并标记过程滞后，直到新的全局买卖记录生成。
- 股票详情页固定使用公开策略 `mainline_dragon_pullback`，先读取最新组合回测下该股的真实执行标记；若组合回测里没有该股执行记录，再使用最近全局买卖记录/信号；仍没有执行标记时才后台准备同策略单股买卖点缓存。不要恢复“运行手动研究回测”按钮或多策略下拉。
- 股票详情页如果最新组合回测已经有该股订单/成交，则 K 线展示同一组合回测口径的实际订单/成交标记，并叠加同一回测的理论信号计划；不再叠加独立全局买卖记录的 `already_holding` 信号噪音。全局买卖记录只作为无组合执行记录时的兜底。
- 持仓中心的持仓卡读取 `/api/quant/symbols/{vt_symbol}/replay/latest` 派生策略建议，显示“策略持有 / 策略已卖出 / 卖出待确认 / 买入未成交 / 无买卖记录”等状态；后续如持仓数量变大再加批量买卖记录 API。
- 持仓中心不再把模拟账户金额作为用户主功能暴露；批量建仓、手动加入和加仓按股数/最小整手操作，KPI 和卡片以收益率、价格、股数和策略建议为主，持仓收益率按持仓股票收益率做算术平均，不再用市值金额加权展示。
- 股票详情页单股复盘不展示模拟账户金额，不以 `initial_cash/final_equity/cash/equity/amount/fee/pnl amount/volume` 解释单股收益。
- 单股收益率按闭合成交价格直接计算：单笔收益率为 `sell_price / buy_price - 1`，累计收益率为各闭合单笔收益率连乘。
- K 线图必须同时显示 BUY 信号、买入拒绝、买入成交和卖出成交；即使本轮买卖记录没有 execution attempt，只要 `quant_stock_signals` 存在 BUY 信号也要显示信号标记。点击 K 线或指标柱显示当日涨跌、跳空、振幅、均线距离、量比和相关信号/执行标记。

## Data Rules

- 回测评分只使用 `publish_date <= trade_date` 的财报，股票详情看到的当前财报不等于历史回测当天可用。
- 股票日线成交额入库单位必须统一为元；旧数据缺成交额时可用 `close * volume * 100` 估算流动性。
- 分钟数据补数属于实时/分钟数据层，不是历史策略研究主流程；如需旧严格分钟报告或未来盘中确认，应优先走同步/导入服务：`sync_stock_minute_bars mode=backtest_gaps`、TDX、Tushare、vn.py 本地库或供应商数据。
- CSV/file_path 是外部供应商回填和高级兜底，不是首选日常补数方式。
- API 必须区分日线开盘执行、实时分钟执行、收盘代理、缺快照、入场未触发和涨跌停/现金/仓位拒单。

## Current Strategy Evidence

- `requirements/alphaagent_pullback_low_suction_strategy_research.md` 已形成当前回踩低吸优化研究结论：不要继续微调单日 MA5 触发器，应新增 `mainline_dragon_pullback_v1` 状态机研究策略，并先并行验证再决定是否设为唯一默认。
- `mainline_dragon_pullback / 0.1.1` 已成为普通历史研究唯一公开策略；旧 `mainline_leader_pullback / 0.1.1` 和 `mainline_dragon_pullback / 0.1.0` 保留为内部备份/历史对照。当前全历史刷新见 `memory/06_backtests/2026-06-16_dragon_pullback_v0_1_1_refresh.md` 和 `memory/06_backtests/README.md`：组合回测 `#120` 覆盖 `2025-03-26` 至 `2026-06-16`，收益约 `+44.45%`，最大回撤约 `-29.61%`，不能直接宣称策略稳定盈利。
- 当前默认历史研究基线已切换为日线 D+1 开盘模型和 `mainline_dragon_pullback`。`GET /api/quant/strategies` 只返回该公开策略。旧严格 14:30 回测 `#62` 保留为分钟模型历史证据，不再作为产品默认操作口径。
- `#62` 的参数网格和 walk-forward 复核显示稳健性很弱，不能宣称抗过拟合或稳定盈利。
- `#70` 修复了回测开始日前预热 K 线不足导致的早期信号计划缺失，能解释金安国纪 `2026-02-09` 进入理论买入计划但因缺 `2026-02-10 14:30` 快照被拒单；它不是完整严格基线。
- `#66` 验证了 `limit_up_after_pullback` 策略链路和金安国纪强势回踩信号，但样本仍负收益且分钟覆盖不完整。
- 当前正确结论是：系统已能复盘候选、计划、订单、成交和持仓路径，但策略本身尚未证明盈利。

## Superseded Records

- `0.1.0` 回测、参数网格和 walk-forward 受卖出撮合时序错误影响，只保留为历史排查材料。
- 旧 `14:30-14:57` 尾盘窗口、`5m/10m` 严格回测尝试和宽松 D+1 开盘结果不再作为当前产品默认。
- `strict_1430 / 1m / 14:30` 曾作为阶段性严格验证主流程；2026-06-16 起被日线 D+1 历史研究主流程取代，14:30 转为实时/分钟数据层能力。
- 早期把分钟缺口当成手工 CSV 补数的表述已被同步任务入口替代；CSV 仍是高级导入格式，不是主流程。
