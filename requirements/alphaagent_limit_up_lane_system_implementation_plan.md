# AlphaAgent 分战法打板系统实施计划

> 状态：已获用户批准，直接实施。仓库规则禁止自动提交，本计划不包含 `git commit`。

## 目标

把现有统一 Top5 打分改为四条独立战法：`首板`、`一进二`、`二进三`、`高板`。每条战法使用自己的买前因子、硬门槛、排名和样本外统计；每日组合最多四只，允许空仓。页面只保留实时推荐、历史交割单、回测三个主视图。

## 真实性边界

- 股票池固定为沪深主板非 ST 10cm，排除创业板、科创板、北交所、退市和特殊状态股票。
- 买前因子只能读取信号时点已经可见的数据。最终是否封板、最终开板次数、最终封单额和 D+1 行情只能进入结果归因。
- 同花顺 80 点分时路径按交易时段三分钟网格解释；路径特征只读取信号时间以前的前缀。
- 分时路径覆盖和日线代理覆盖必须分别报告。缺少 Tick/L2 时不声称排队成交。
- 财务报告只读取 `publish_date <= signal_date` 的最新一期。
- 训练、滚动样本外、锁定留出三段按时间切分，锁定留出结果不反向修改规则。

## 文件边界

- 新建 `alphaagent/server/services/limit_up/lane_features.py`：纯函数，负责涨停基因、位置、回调、板位结构、分时前缀和财务风险。
- 新建 `alphaagent/server/services/limit_up/lane_repository.py`：读取并合并历史涨停事件、分时路径和点时财务数据。
- 新建 `alphaagent/server/services/limit_up/lane_research.py`：四条 lane 的硬门、独立排序、每日 0-4 只组合和 D+1 交割单。
- 修改 `history_engine.py`：在日线特征帧中增加无未来函数的涨停基因与位置字段，并把事件证据交给分战法引擎。
- 修改 `history_repository.py`：加载富事件证据和点时财务报告，随历史账本一起记录覆盖率。
- 修改 `history_service.py`：提供按 lane 的逐日交割单和分层回测汇总。
- 修改 `api/limit_up.py`：增加 `/history/ledger` 与 lane 参数，保留旧接口兼容。
- 新建/修改 `tests/alphaagent/test_limit_up_lanes.py`、现有打板测试：覆盖未来函数、四战法路由、每日上限、空仓和 D+1 日期。
- 修改 `frontend/src/api/limitUp.ts`：增加 lane、交割单和分层回测类型与请求函数。
- 重写 `frontend/src/pages/LimitUpPage.tsx`，新建聚焦组件：只组织三个主视图，不再把研究面板全部纵向堆叠。
- 更新 `memory/06_backtests/limit_up_short_term_factor_research.md` 和 `memory/09_decisions/decisions.md`：只记录实际跑出的结论、覆盖和未解决风险。

## 任务 1：冻结特征契约

- [ ] 为半年涨停次数、半年触板封住率、距上次涨停交易日、上次涨停后回调、120 日位置、近 5 日涨停次数写失败测试。
- [ ] 为 80 点路径时间映射、信号前缀、首次触板、首次真实回封和前缀回封次数写失败测试。
- [ ] 为 `publish_date` 截止和财务风险分级写失败测试。
- [ ] 实现最小纯函数并通过定向测试。

验收命令：

```bash
uv run pytest tests/alphaagent/test_limit_up_lanes.py -q
```

## 任务 2：四条独立战法

- [ ] `首板`：要求半年内有涨停基因；低位或前次涨停后充分回调；默认首次触板不早于 10:00；严重财务风险禁入。
- [ ] `一进二`：读取昨日首板的首次/最后封板、开板回封、换手、量能、行业前排和今日竞价强度。
- [ ] `二进三`：连续二板和近 5 日两次涨停结构都可进入；分歧弱转强与强一致分开标记；中位淘汰和严重财务风险禁入。
- [ ] `高板`：只保留市场/板块核心，默认需要更强的数据完整度；无盘口证据时只观察。
- [ ] 每条 lane 使用自己的硬门、排序键和原因，不再共享一个统一总分阈值。
- [ ] 组合分配最多四只，每条 lane 默认最多一只；同一板块最多两只；退潮和数据过期可返回零只。

## 任务 3：逐日交割单与回测

- [ ] 历史构建时合并富事件证据和点时财务数据。
- [ ] 对盘中首板按信号时间顺序生成候选，避免收盘后从全天触板股反选。
- [ ] 对竞价接力在 09:25 横截面内比较一进二、二进三和高板候选。
- [ ] 每笔记录 D 日买入日期/时间/价格、lane、动作、D+1 卖出日期/时间/价格、净收益和结果类型。
- [ ] 回测分别输出严格分时段和日线代理段、训练/滚动样本外/锁定留出、lane 分层、年度分层、胜率、均值、复利、回撤、利润因子和硬亏损率。
- [ ] 当缺少 D+1 行情或不能证明成交时保留未结算/未成交状态，不静默删除。

API：

```text
GET /api/limit-up/history/ledger?date=YYYY-MM-DD&lane=first_board
GET /api/limit-up/history/backtest?start=...&end=...&lane=first_board&exit_mode=next_open
```

## 任务 4：精简产品界面

- [ ] 顶部只保留交易日、数据更新时间、延迟、数据源/降级状态和刷新。
- [ ] 一级页签固定为 `实时推荐 / 历史交割单 / 回测`。
- [ ] 实时推荐和交割单内固定四个 lane 切换：`首板 / 一进二 / 二进三 / 高板`。
- [ ] 推荐行只显示股票、买点、信号时间、板块/龙位、关键通过因子、取消条件和 D+1 历史证据。
- [ ] 交割单按日期显示买入和 D+1 卖出，不再把研究审计、补数和模型面板全部放在主路径。
- [ ] 回测只显示关键指标、三段验证、净值/回撤和逐笔交易；详细研究信息按需展开。
- [ ] 桌面和手机都不出现文字溢出、重叠和嵌套卡片。

## 任务 5：验证门

- [ ] 后端所有打板测试通过。
- [ ] 前端组件测试和生产构建通过。
- [ ] 重建历史账本并记录实际耗时、覆盖和限流/降级状态。
- [ ] 用浏览器验证最新日期、历史日期、四条 lane、交割单和回测切换。
- [ ] 只有训练、滚动样本外、锁定留出三段都达到正收益、胜率不低于 50%、回撤和硬亏损率受控，才允许显示“通过验证”；否则明确显示研究中，绝不承诺稳定复利。

验证命令：

```bash
uv run pytest tests/alphaagent/test_limit_up_mvp.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_lanes.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
docker compose up -d --build alphaagent-api alphaagent-web
```
