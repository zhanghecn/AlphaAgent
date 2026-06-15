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

- `/quant` 是量化研究工作台，主路径为候选、组合回测、交易归因、数据质量和严格 14:30 补数。
- `/portfolio` 是独立持仓模块，负责自选分组、量化候选分组、模拟持仓、成本价、买卖依据。
- 股票详情页 `/stocks/:vtSymbol` 承接单股回测、K 线买卖点、财报口径和组合回测复核。
- 量化页默认只展示组合回测；股票详情页生成的单股回测不混入量化页主列表。
- 股票展示尽量使用“名称 + vt_symbol + 板块标签”，并复用可点击的股票身份组件。

## Candidate And Strategy Rules

- 组合回测必须使用历史逐日动态候选：每个信号日只使用当日及以前可见数据生成候选，再在下一交易日执行。
- 候选区间生成通过 `POST /api/quant/screen-runs/range`，从用户选定交易日跑到本地最新交易日。
- 候选区间生成是主量化过程；`persist=true` 时会基于已落库 `quant_stock_signals` 生成统一 `strategy_replay_runs` / `strategy_replay_attempts`，不再让股票详情默认单独重算一套单股缓存。
- 量化页候选 tab 展示最新全局 replay 的区间、执行尝试、成交、拒绝和拒绝原因，并提供“补齐 replay”按钮用于基于已有候选补建执行复盘。
- 策略必须通过注册表暴露，不再把“低吸”硬编码成唯一策略。
- 当前注册策略包括 `mainline_leader_pullback`、`breakout_confirmation`、`limit_up_after_pullback` 等；策略有效性必须分别验证。
- `WATCH` 只表示观察，不应作为自动组合买入信号；买入计划只应来自 `action=BUY` 并通过组合约束的候选。

## Backtest Execution

- 普通新建组合回测默认执行模型是 `strict_1430 / 1m / 14:30 / strict_entry=true`。
- 严格 14:30 使用 D 日收盘后可见数据生成计划，D+1 在 `14:30` 的真实 1 分钟快照满足条件时成交。
- BUY 信号不等于实际购买。BUY 信号表示 T 日收盘后策略生成买入计划；实际购买必须经过 T+1 执行价、涨停/跌停、MA5 容忍度、现金和仓位等约束。
- 单股历史信号复盘以历史日线收盘价作为缺分钟线时的尾盘代理价格；如果代理执行价距离信号日 MA5 超过容忍度，标记 `tail_entry_not_triggered` 并显示执行价、信号日 MA5 和距离。今日缺 14:30 快照才标记等待/缺快照。
- 执行拒绝原因必须精确区分：`limit_up_open_blocked` 是开盘涨停买不到，`limit_up_tail_unfilled` 是尾盘涨停买不到，`no_execute_bar` 是缺执行日 K 线，`tail_entry_not_triggered` 是尾盘入场条件未触发，不能再合并成“涨停或缺数据”。
- `tail_close_hybrid` 保留为研究对比模型，缺分钟线时可标记 `daily_close_proxy`，不能当作严格真实成交。
- `legacy_next_open` 和 `strategy_version < 0.1.1` 只作为旧报告兼容，旧绩效不作为当前策略结论。
- 严格主流程只保留 `1m / 14:30`；`5m/15m/30m/60m` 只属于通用分钟线同步/行情查看，`10m` 只保留拒绝测试和历史说明。

## Single-stock Review

- 股票详情页默认读取 `/api/quant/symbols/{vt_symbol}/replay/latest` 的全局 replay 结果；旧 `/api/backtests/symbol` 只保留为手动研究工具，不再自动触发或作为主口径。
- 持仓中心的持仓卡读取 `/api/quant/symbols/{vt_symbol}/replay/latest` 派生策略建议，显示“策略持有 / 策略已卖出 / 卖出待确认 / 买入未成交 / 无 replay”等状态；后续如持仓数量变大再加批量 replay API。
- 持仓中心不再把模拟账户金额作为用户主功能暴露；批量建仓、手动加入和加仓按股数/最小整手操作，KPI 和卡片以收益率、价格、股数和策略建议为主。
- 股票详情页单股复盘不展示模拟账户金额，不以 `initial_cash/final_equity/cash/equity/amount/fee/pnl amount/volume` 解释单股收益。
- 单股收益率按闭合成交价格直接计算：单笔收益率为 `sell_price / buy_price - 1`，累计收益率为各闭合单笔收益率连乘。
- K 线图必须同时显示 BUY 信号、买入拒绝、买入成交和卖出成交；点击 K 线或指标柱显示当日涨跌、跳空、振幅、均线距离、量比和相关信号/执行标记。

## Data Rules

- 回测评分只使用 `publish_date <= trade_date` 的财报，股票详情看到的当前财报不等于历史回测当天可用。
- 股票日线成交额入库单位必须统一为元；旧数据缺成交额时可用 `close * volume * 100` 估算流动性。
- 严格 14:30 缺口补数应优先走同步/导入服务：`sync_stock_minute_bars mode=backtest_gaps`、TDX、Tushare、vn.py 本地库或供应商数据。
- CSV/file_path 是外部供应商回填和高级兜底，不是首选日常补数方式。
- API 必须区分真实 14:30、收盘代理、缺快照、尾盘未触发和涨跌停/现金/仓位拒单。

## Current Strategy Evidence

- 当前最重要的严格基线是回测 `#62`：`mainline_leader_pullback / 0.1.1`、`2026-02-02` 至 `2026-06-13`、主板 `max_symbols=80`、严格 14:30。成交买入 21/21 使用真实 14:30 快照，收盘代理 0，缺快照拒单 0，但总收益约 `-5.08%`。
- `#62` 的参数网格和 walk-forward 复核显示稳健性很弱，不能宣称抗过拟合或稳定盈利。
- `#70` 修复了回测开始日前预热 K 线不足导致的早期信号计划缺失，能解释金安国纪 `2026-02-09` 进入理论买入计划但因缺 `2026-02-10 14:30` 快照被拒单；它不是完整严格基线。
- `#66` 验证了 `limit_up_after_pullback` 策略链路和金安国纪强势回踩信号，但样本仍负收益且分钟覆盖不完整。
- 当前正确结论是：系统已能复盘候选、计划、订单、成交和持仓路径，但策略本身尚未证明盈利。

## Superseded Records

- `0.1.0` 回测、参数网格和 walk-forward 受卖出撮合时序错误影响，只保留为历史排查材料。
- 旧 `14:30-14:57` 尾盘窗口、`5m/10m` 严格回测尝试和宽松 D+1 开盘结果不再作为当前产品默认。
- 早期把分钟缺口当成手工 CSV 补数的表述已被同步任务入口替代；CSV 仍是高级导入格式，不是主流程。
