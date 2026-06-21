# Decisions

这个文件只记录仍然有效的长期决策。回测过程、接口输出、截图和单次实验结果不放这里；量化实验证据统一看 `memory/06_backtests/README.md` 和 `memory/06_backtests/strategy_optimization_ledger.md`。

## Project Boundary

- 项目外显名称是 AlphaAgent，目标是在 vn.py 基础上建设 A 股量化研究、智能选股、组合回测、模拟持仓和后续交易工作流。
- 保留 Python 包名和源码目录 `vnpy`，避免破坏 vn.py 插件依赖和已有导入。
- 不修改继承的 `vnpy/` 核心包和官方 examples，除非用户明确要求或兼容性必须修改。
- AlphaAgent 自研业务层放在 `alphaagent/`、`frontend/`、`docs/`、`requirements/` 和 `memory/`。
- 需求分析和产品设计放在 `requirements/`；长期项目事实放在 `memory/`。

## Collaboration And Git

- 不主动 `git commit` 或 `git push`；只有用户明确要求提交或推送时才执行。
- 工作区可能包含用户或前序改动，不能随意 revert、reset 或 checkout。
- 提交前优先做可验证的小步整理：定向测试、编译、前端 build、`git diff --check`。
- `memory/` 是项目地图，不是日记。新增事实时优先改写 overview，长报告放到 typed artifact。

## A-share Capability

- 当前 vn.py GUI 只注册 CTP，不能声称已经接入 A 股实盘或全 A 实时行情。
- A 股实盘交易应通过官方或兼容 Gateway，例如 XTP、TORA、OST、EMT。
- 历史数据应优先通过可验证数据源或插件，例如 XT、RQData、Tushare、券商/QMT/TDX/vn.py 本地库。
- 免费公共分钟源只能作为近端补充，不能直接当作长区间严格回测依据。

## Gateway And Deployment

- 部署统一入口是 Go 网关 `alphaagent-gateway`，对外唯一端口；`alphaagent-api` 和 `alphaagent-web` 只暴露内部端口，避免绕过登录直连。
- 管理员登录使用环境变量 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD`；首次部署占位值时由部署脚本随机生成。
- 登录态用 JWT HS256，前端存 `localStorage` key `alphaagent_token`；当前接受 localStorage 的 XSS 风险，不使用 cookie/CSRF 方案。
- 网关 `GET /api/auth/me` 未登录时返回 `{authenticated:false}`；其余 `/api/*` 失败返回 401，前端全局拦截后清 token 并跳转登录。
- 发版走 `.github/workflows/docker-release.yml`，推 `v*` tag 发布 `alphaagent-api/web/gateway` 镜像到 GHCR。
- 本地开发和生产结构保持一致：网关入口、runtime web、compose 管理。旧 5173 dev server 和 api/web 直连模式不作为默认口径。
- HTTPS 后续由网关前置 Caddy 处理，不在 Go 网关里做 TLS 终止。

## Quant Product Shape

- `/quant` 是量化研究工作台，普通用户只需要候选和组合回测两条主路径。
- `/portfolio` 是独立持仓模块，负责自选分组、量化候选分组、模拟持仓、成本价和买卖依据。
- `/stocks/:vtSymbol` 是股票详情页，承接单股复盘、K 线买卖点、财报口径和组合回测复核。
- 量化页默认只展示组合回测；股票详情页生成的单股回测不混入量化页主列表。
- 用户界面和 API message 不暴露 `replay` 这类内部词；统一称为“买卖记录”或“买卖执行记录”。内部接口路径/表名可暂时保留兼容。
- 股票展示尽量使用“名称 + vt_symbol + 板块标签”，并复用可点击的股票身份组件。

## Candidate And Strategy Rules

- 普通用户入口只公开 `mainline_dragon_pullback` 一个策略；旧策略只保留为内部兼容和旧报告对比。
- 候选生成和组合回测必须按历史逐日推进：D 日只使用当日及以前可见数据生成候选，D+1 执行。
- 历史主流程不再依赖 `14:30` 分钟线。14:30/分钟快照只保留为未来实时数据、盘中确认、分钟同步和旧报告兼容能力。
- 前端主操作应是“刷新候选并回测”：内部自动补候选、生成买卖记录并运行组合回测，不要求用户理解“生成区间候选/生成执行复盘”。
- 候选观察默认评分前 `100`、分页 `20`；组合执行默认 BUY 前 `20`、最大持仓 `10`。观察前 `100` 方便审查排序，不等于扩大真实执行池。
- 不强行给低吸保留名额；候选按统一评分排序。
- `WATCH` 只表示观察，不进入自动组合买入。真实买入计划只来自 `action=BUY` 并通过组合约束的候选。
- `entry_signal` 是原始诊断字段；只有 `executable_entry_signal=true` / `action=BUY` 才显示为可买入、计入 BUY 次数并进入买入计划。
- 旧 `quant_recommendations.action` 不能单独作为当前 BUY/WATCH 依据。读侧必须从规范化后的 `reason/evidence` 派生当前 action；旧落库 action 不一致时标记 `action_mismatch_resolved=true`。
- 候选评分必须可解释：候选行或股票复核中应能看到状态、低吸蓄势天数、均线收敛、启动质量、失败规则和评分拆解。
- 用户可见候选读取必须匹配当前 `signal_evidence_schema_version`；旧 schema 不应静默回退展示旧解释字段。
- 量化页候选日期默认选择当前公开策略最新已生成候选日；如果本地日线最新交易日尚未生成候选，页面必须暴露候选滞后。

## Market And Setup Model

- 行情阶段 `主升 / 震荡 / 退潮 / 回暖` 当前只作为审计、风险上下文和用户解释，不直接进入默认评分、排序、买卖、卖点或仓位。
- 行情和策略族当前作为审计/风险上下文，具体实验结论见 `memory/06_backtests/strategy_optimization_ledger.md`。
- 低吸首启和龙回头是两套内部 setup；支撑、均线承接、量能、收盘位置、风险形态是共用因子，但不能粗暴叠分。
- `低吸蓄势` 不是每天买入；只有蓄势后的首个有效上拉或后续确认，才可能进入可执行买点讨论。
- `龙回头 + 低吸` 重叠不自动叠分；重叠冲突先作为解释和审计。
- 公开游资/短线方法只能转成可验证代理，例如主线、情绪周期、分歧、承接、再转强、替换质量；不能量化为席位身份硬规则。
- 在历史板块/资金流覆盖不足前，不能宣称已经稳定量化科技主线或新主线轮动。

## Backtest And Baseline

- 当前产品基线看 `memory/06_backtests/README.md` 和 `memory/06_backtests/strategy_optimization_ledger.md`。
- `baseline_only=true` 只返回产品默认基线：当前公开策略、默认研究参数、最新本地交易日结束、且未标记 `exclude_from_product_baseline`。
- 局部候选刷新、短区间诊断、研究开关回测必须显式排除产品基线，不能顶掉 `/quant` 和股票详情默认基线。
- BUY 信号不等于实际购买。BUY 代表 D 日收盘后生成计划；实际成交还要经过 D+1 执行价、涨停/跌停、现金和仓位等约束。
- 执行拒绝原因必须精确区分，例如 `limit_up_open_blocked`、`limit_down_open_blocked`、`no_execute_bar`，不能合并成含糊原因。
- `tail_close_hybrid`、`strict_1430`、`strategy_version < 0.1.1` 只作为旧报告兼容或研究对比，不作为当前产品默认。
- 每次策略优化必须维护 `memory/06_backtests/strategy_optimization_ledger.md`，记录版本、规则变化、回测编号、区间、收益、回撤、交易数、是否保留、未来函数/过拟合风险和证据文件。

## Current Strategy Lessons

- 多轮默认关闭实验证明：不能把零散因子直接塞进默认策略。
- 低吸生命周期加分、低吸启动硬门槛、市场风险简单降权、失败启动早退、高分满仓换仓、弱持仓换仓、保护版弱持仓换仓都不能晋升默认。具体证据见 `memory/06_backtests/strategy_optimization_ledger.md`。
- 当前收益损耗更多来自真实组合执行、满仓、替换质量、卖点和趋势赢家路径保护，而不是候选池完全无效。
- `support_stop` 不能当作单一卖点错误；它包含买后失败、卖后反弹、浮盈回吐和卖后替换差等不同桶。
- 信号只负责买点/拒买证据；卖点应按真实持仓、入场成本/支撑、最高浮盈回撤、当前支撑结构和当前日信号动态计算，且必须无未来函数。
- 组合轮动必须有分差约束；默认换仓分差仍保持保守，不扩大宽泛换仓。
- 后续优化优先做执行一致性和趋势赢家路径保护：让候选前列赢家进入真实组合，同时不破坏已有趋势持仓。

## Single-stock Review

- 股票详情页主图口径是“当前公开策略对该股票独立全历史复盘”，不看组合最大持仓、不看组合是否真实持有。
- 股票详情固定使用 `mainline_dragon_pullback`，读取单股复盘结果；缓存缺失或落后时可后台创建同策略单股复盘缓存。
- 股票详情主 K 线只显示 `买入 / 拒买 / 卖出`：买入和卖出来自单股复盘成交路径，拒买只展示买入拒绝。
- 牛熊线是只读多指数潮汐层，映射到个股价格坐标展示 `线上/线下`、距离、方向和简短动作提示；它不自动改买点、卖点或仓位。
- 完整 `signal-history` 只用于逐日评分审计、分数解释和诊断场景，不决定主图买卖点。

## Superseded Records

- 旧 `14:30-14:57` 尾盘窗口、`5m/10m` 严格回测和宽松 D+1 结果不作为当前产品默认。
- `strict_1430 / 1m / 14:30` 曾是阶段性严格验证主流程；现在是实时/分钟数据层能力。
- 早期把分钟缺口当成手工 CSV 补数的表述已被同步任务入口替代；CSV 仍是高级导入格式，不是主流程。
