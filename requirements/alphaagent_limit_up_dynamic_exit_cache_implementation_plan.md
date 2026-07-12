# AlphaAgent 打板动态退出与实时缓存实施计划

> 本计划按 TDD 执行，使用当前工作区直接实现；只定向暂存本任务文件。

**目标：** 完成系统动态退出、六类战法标签、实时操作说明和回测缓存的第一版产品。

**架构：** 新增独立动态退出策略模块，为历史候选附加逐笔决策；现金模拟器消费逐笔退出方式。历史服务缓存紧凑输入和最终报告，实时策略输出统一状态及操作规则，React 页面只展示系统决策。

**技术栈：** Python 3.13、FastAPI、PostgreSQL、现有 `TTLCache`、pytest、React 18、TypeScript、TanStack Query、Vitest、Playwright。

---

### 任务 1：动态退出策略

**文件：**

- 新建 `alphaagent/server/services/limit_up/dynamic_exit.py`
- 新建 `tests/alphaagent/test_limit_up_dynamic_exit.py`

- [x] 测试成熟样本必须满足 `result_date < decision_date`，同日收盘结果不能进入训练。
- [x] 测试 expanding OOS 逐日滚动，locked holdout 使用开发期冻结策略。
- [x] 测试样本不足时默认尾盘退出，高板强竞价仅在开发样本同时改善胜率和复利时竞价退出。
- [x] 实现 `attach_dynamic_exit_decisions(signals)`，返回 `exit_mode/reason/training_cutoff/sample_count/confidence`。

### 任务 2：真实现金逐笔退出

**文件：**

- 修改 `alphaagent/server/services/limit_up/cash_backtest.py`
- 修改 `tests/alphaagent/test_limit_up_cash_backtest.py`

- [x] 测试 `dynamic` 模式下同一天可同时存在竞价退出和尾盘退出。
- [x] 测试竞价卖出现金可供其后的盘中买入，尾盘退出资金不可提前复用。
- [x] 测试动态退出遇到跌停时进入顺延重试。
- [x] 给持仓保存逐笔计划退出方式，并在开盘、收盘处理器分别执行。

### 任务 3：历史服务与缓存

**文件：**

- 修改 `alphaagent/server/services/limit_up/history_service.py`
- 修改 `alphaagent/server/api/limit_up.py`
- 修改 `tests/alphaagent/test_limit_up_history.py`

- [x] 测试 ledger/backtest 默认 `dynamic`，旧模式仍兼容。
- [x] 测试动态交割单显示实际卖点和退出原因。
- [x] 增加版本化回测报告 TTL 缓存和单飞加载，历史重建时清空。
- [x] 精简正式响应中的重复嵌套信号，保留页面需要的交割信息。

### 任务 4：六类战法标签

**文件：**

- 修改 `alphaagent/server/services/limit_up/lane_features.py`
- 修改 `alphaagent/server/services/limit_up/lane_research.py`
- 修改 `alphaagent/server/services/limit_up/history_engine.py`
- 修改 `alphaagent/server/services/limit_up/live_service.py`
- 新建 `tests/alphaagent/test_limit_up_setup_tags.py`

- [x] 为六种形态分别添加正例、边界和无未来数据测试。
- [x] 在历史候选和实时候选统一输出 `setup_tags/setup_confidence`。
- [x] 保证 `anti_nuclear_board` 只产生研究标签，不绕过现有市场门和验证门。

### 任务 5：实时操作状态

**文件：**

- 修改 `alphaagent/server/services/limit_up/live_policy.py`
- 修改 `tests/alphaagent/test_limit_up_live.py`

- [x] 测试实时信号包含 `execution_state/buy_condition/sell_condition/cancel_condition/state_updated_at`。
- [x] 测试等待信号满足条件后切换为 actionable，失效后切换 cancelled/pass。
- [x] 保持数据 stale 或验证未通过时 fail closed。

### 任务 6：精简产品界面

**文件：**

- 修改 `frontend/src/api/limitUp.ts`
- 修改 `frontend/src/pages/LimitUpPage.tsx`

- [x] 删除 `exitMode` 状态、下拉框和查询键。
- [x] 实时行展示状态、标签、买入条件、卖出条件、取消条件和更新时间。
- [x] 交割单展示动态退出方式与战法标签。
- [x] 回测摘要展示竞价退出/尾盘退出数量，不增加新卡片层级。

### 任务 7：验证、部署和证据

**文件：**

- 更新 `memory/03_data/data_flow.md`
- 更新 `memory/05_runtime/run_debug.md`
- 更新 `memory/06_backtests/limit_up_real_cash_backtest.md`
- 更新 `memory/09_decisions/decisions.md`

- [x] 运行打板定向 pytest、API 测试和前端构建。
- [x] 重建 API/Web 容器，测量动态回测冷/热请求耗时。
- [x] 运行 10 万元全历史、expanding OOS、locked holdout，并与两个固定基准并列记录。
- [x] 用 Playwright 登录 `/limit-up`，验证日期切换、实时说明、动态交割单和回测页面。
- [x] 定向暂存并提交本任务文件，不包含工作区其他改动。
