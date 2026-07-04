# Decisions

这个文件只记录仍然有效的长期决策。量化实验结果、回测编号、接口输出和单次验证记录统一放在 `memory/06_backtests/` 或对应 typed memory 文件里。

## Project Boundary

- 项目外显名称是 AlphaAgent，目标是在 vn.py 基础上建设 A 股量化研究、智能选股、组合回测、模拟持仓和后续交易工作流。
- 保留 Python 包名和源码目录 `vnpy`，避免破坏 vn.py 插件依赖和已有导入。
- 不修改继承的 `vnpy/` 核心包和官方 examples，除非用户明确要求或兼容性必须修改。
- AlphaAgent 自研业务层放在 `alphaagent/`、`frontend/`、`gateway/`、`deploy/`、`requirements/` 和 `memory/`。
- 需求分析和产品设计放在 `requirements/`；长期项目事实和决策放在 `memory/`。

## Collaboration And Git

- 不主动 `git commit` 或 `git push`；只有用户明确要求提交或推送时才执行。
- 工作区可能包含用户或前序改动，不能随意 revert、reset 或 checkout。
- 提交前优先做可验证的小步整理：定向测试、编译、前端 build（`pnpm -C frontend build` / `pnpm -C frontend test`）、`git diff --check`。前端单测用 vitest（配置在 `frontend/vitest.config.ts`），纯逻辑抽到 `src/features/**/*.ts` 配 `*.spec.ts`，UI 组件靠 tsc + vite build + 浏览器实测。
- `memory/` 是项目地图，不是日记。新增事实时优先改写 overview，长报告放到 typed artifact。

## A-share Capability

- 当前 vn.py GUI 不能被描述为已经接入 A 股实盘或全 A 实时行情；A 股能力主要来自 AlphaAgent 自研业务层和后续官方/兼容插件接入。
- A 股实盘交易应通过官方或兼容 Gateway，例如 XTP、TORA、OST、EMT。
- 历史数据应优先通过可验证数据源或插件，例如 XT、RQData、Tushare、券商/QMT/TDX/vn.py 本地库；免费公共分钟源只能作近端补充，不能直接当作长区间严格回测依据。

## Deployment

- 部署统一入口是 Go 网关 `alphaagent-gateway`，对外唯一端口；`alphaagent-api` 和 `alphaagent-web` 只暴露内部端口，避免绕过登录直连。
- 管理员登录使用环境变量 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`；登录态用 JWT HS256，前端存 `localStorage` key `alphaagent_token`。
- 发版走 `.github/workflows/docker-release.yml`，推 `v*` tag 发布 `alphaagent-api/web/gateway` 镜像到 GHCR。
- 本地开发和生产结构保持一致：网关入口、runtime web、compose 管理。旧 5173 dev server 和 api/web 直连模式不作为默认口径。

## Quant Product Shape

- `/quant` 是量化研究工作台，普通用户主路径是候选 Top20 独立买卖质量。组合回测/组合诊断只能作为执行层诊断，不能替代 `/quant` 主结果。
- `/portfolio` 是独立持仓模块，负责自选分组、量化候选分组、模拟持仓、成本价和买卖依据。
- `/stocks/:vtSymbol` 是股票详情页，承接单股复盘、K 线买卖点、财报口径和组合回测复核。
- `/mainline` 是概念指数页（板块排名 + 成分股），统一时间轴：合并 live 最新资金流日 + history 评分日，默认选中最新；选中 == liveDate 走实时数据（盘中刷新），其余走历史 snapshot，不再分"今日实时 / 历史回放"两个 tab。顶部"概念资金流"条带读 live/snapshot 的 `flow_top` 字段（后端 `_compute_flow_top` 从**全部概念**按主力净流入算 top10 流入/流出，独立于 `_sort_live_concept_ranking` 截断——避免 broken 概念如 CPO/光通信被 _sort 后 limit 截断挤出），双列紧凑展示，每行可点击 → 选中该概念并滚动到三栏看成分股（复用 SectorStocksTable），不归主题——游资看的是具体概念（半导体/AI/白酒/猪肉）而非抽象主题。条带顶部支持周期切换（今日/3日/5日/10日/20日；3日/20日=SUM(即时) 最近N交易日，`actual_days` 反映数据保留约11天）+ 搜索框（`/concept-search` 按 name 模糊搜全部概念，定位 CPO/PCB 等不在 top10 的概念）。即时资金流（sector_fund_flows）只保留约 11 天，更早历史日资金流字段为空属正常（数据保留策略，非 bug）。盘中同步档：11:30 / 14:00 / 14:30 / 15:00 / 18:00（`data_sync.py` DEFAULT_BATCH_SCHEDULES，9:30-11:30 之间显示前一交易日数据）。成分股按核心行业过滤：`/sector-stocks?industry_filter=true` 取概念成分股与申万行业重叠 top2 的交集，过滤东财概念宽泛杂股（半导体概念去掉家电/教育/机械设备股，保留真半导体）；`_STYLE_STATUS_KEYWORDS` 过滤指数篮子/风格标签（HS300_/专精特新/创业板综/标准普尔 等）让真题材进 top10。
- 用户界面和 API message 不暴露 `replay` 这类内部词；统一称为“买卖记录”或“买卖执行记录”。内部接口路径/表名可暂时保留兼容。
- 股票展示尽量使用“名称 + vt_symbol + 板块标签”，并复用可点击的股票身份组件。

## Strategy Rules

- 普通用户入口只公开 `mainline_dragon_pullback` 一个策略；旧策略只保留为内部兼容和旧报告对比。
- 策略优化不能设计成需要用户手动选择的开关。研究参数、实验开关只允许作为研发验证和回测隔离工具；产品落地必须表现为一个确定的默认策略版本，达标后合入默认，不达标就不进入默认。
- 候选生成和组合回测必须按历史逐日推进：D 日只使用当日及以前可见数据生成候选，D+1 执行。
- `/quant` 当前产品质量主口径是 `candidate_trade_quality`：D 日每日候选 Top20，D+1 开盘逐只独立买入，按当前卖点卖出，统计候选本身收益、胜率和回撤。
- 候选观察默认评分前 `100`、分页 `20`；候选质量默认评估每日 Top20。观察前 `100` 方便审查排序，不等于扩大真实执行池。
- 不强行给低吸、龙回头或超跌反弹保留名额；候选按统一评分/内部 ranker 排序。
- `WATCH` 只表示观察，不进入自动组合买入。真实买入计划只来自 `action=BUY` 并通过组合约束的候选。
- `entry_signal` 是原始诊断字段；只有 `executable_entry_signal=true` / `action=BUY` 才显示为可买入、计入 BUY 次数并进入买入计划。
- 研究买点只用于解释和复盘：`research_entry_signal=true`、`signal_role=research_buy` 或 evidence 中 `*_entry_observation_only=true` 的点必须显示为观察/研究标记，不得生成真实交易段，不得进入组合执行池，不得计入正式 BUY 收益胜率。
- 用户可见候选读取必须匹配当前 `signal_evidence_schema_version`；旧 schema 不应静默回退展示旧解释字段。
- 同一交易日可能存在多次 `quant_signal_runs` 全量同步。所有候选 TopN、收益胜率和页面对比必须固定 run_id，或按“每个交易日最新成功 run_id”去重。

## Market And Setup Model

- 行情阶段 `主升 / 震荡 / 退潮 / 回暖`、金手指和银手指当前作为内部因子、风险上下文和用户解释，不直接作为用户策略开关。
- 低吸首启、龙回头、超跌反弹是内部 setup/候选源；支撑、均线承接、量能、收盘位置、风险形态是共用因子，但不能粗暴叠分。
- `bottom_reclaim/bottom_ma_repair` 是底部修复加分项和 reserve，不是独立 BUY，也不是简单过滤器。
- 公开游资/短线方法只能转成可验证代理，例如主线、情绪周期、分歧、承接、再转强、买点质量和卖点质量；不能量化为席位身份硬规则。
- 在历史板块/资金流覆盖不足前，不能宣称已经稳定量化科技主线或新主线轮动。
- `/mainline` 概念页 `continuation_status` 的"维持"必须是量价齐升：价格涨且主力非明确净流出。价格涨但主力净流出（顶部派发，如芯片半导体 +2.7% / -358 亿）必须判 `BROKEN`，不能 `MAINTAINED` 霸占榜首掩盖撤退；资金流缺失(None) 不等同流出，不降级。live 与历史回放（snapshot）均走派发：`_ranking_for_date` 已 LEFT JOIN `sector_fund_flows` 补 `main_net_inflow` + `data_mode="history"`，`_enrich_concept_index_context` 对有 `data_mode` 的 item（live/history）都走量价判定，只有 delta/无 data_mode 才回退 hot/cold。回归测试：`test_continuation_status_marks_top_distribution_as_broken`、`test_enrich_marks_history_distribution_as_broken`。

## Backtest And Baseline

- 当前产品基线和策略实验结论以 `memory/06_backtests/README.md` 和 `memory/06_backtests/strategy_optimization_ledger.md` 为准。
- `baseline_only=true` 只返回持久化组合回测基线；它不代表候选质量主口径。独立组合回测若用于执行诊断，必须与候选质量基线分开解读。
- BUY 信号不等于实际成交。BUY 代表 D 日收盘后生成候选/计划；真实组合成交另行经过 D+1 执行价、涨跌停、现金和组合上限等约束。
- 策略优化结论必须区分候选层和组合层：候选层按每日候选独立买卖验收，组合层必须另跑真实组合回测。
- 信号只负责买点/拒买证据；卖点应按真实持仓、入场成本/支撑、最高浮盈回撤、当前支撑结构和当前日信号动态计算，且必须无未来函数。
- 后续优化优先做候选自身买点质量、统一 Top20 排序质量、卖点质量和趋势赢家路径保护；真实组合执行只作为独立成交层复核，不回灌为候选质量解释。

## Single-stock Review

- 股票详情页主图口径是“当前公开策略对该股票独立全历史复盘”，不看组合最大持仓、不看组合是否真实持有。
- 股票详情固定使用 `mainline_dragon_pullback`，读取单股复盘结果；缓存缺失或落后时可后台创建同策略单股复盘缓存。
- 股票详情主 K 线只显示 `买入 / 拒买 / 卖出`：买入和卖出来自单股复盘成交路径，拒买只展示买入拒绝。
- 牛熊线是只读多指数潮汐层，映射到个股价格坐标展示 `线上/线下`、距离、方向和简短动作提示；它不自动改买点、卖点或资金权重。
- 完整 `signal-history` 只用于逐日评分审计、分数解释和诊断场景，不决定主图买卖点。

## Superseded Records

- 旧 `14:30-14:57` 尾盘窗口、`5m/10m` 严格回测、宽松 D+1 早期结果和旧 `strategy_version < 0.1.1` 只作为历史排查材料。
- 旧低吸、龙回头、止损、组合重排实验的具体编号和收益不放本决策文件；需要复核时看 `memory/06_backtests/archive_index.md` 和具体报告。
