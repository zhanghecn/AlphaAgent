# 综合首板连续盘中执行实施计划

> **For agentic workers:** 本计划在当前会话内逐项执行；仓库规则禁止未经用户明确要求提交，因此所有提交步骤省略。

**Goal:** 将 `/limit-up` 从两个窄买入窗口升级为无未来数据的连续盘中评估，并让用户直接看见零买点漏斗与阻断原因。

**Architecture:** 保留 `scheduled_execution.py` 作为唯一时钟和历史信号时间合同；实时策略继续产生研究动作，组合层只负责时钟、陈旧度和最多两仓，绝不把观察动作提升为买点。两日追加轨迹负责按股票去重生成日内漏斗；历史账户明确标记为候选代理，并返回实时执行门覆盖缺口。

**Tech Stack:** Python 3.11、FastAPI 服务层、PostgreSQL JSONB 轨迹、pytest、React/TypeScript、Vitest。

---

### Task 1: 冻结 v2 时钟

**Files:**
- Modify: `tests/alphaagent/test_limit_up_scheduled_execution.py`
- Modify: `alphaagent/server/services/limit_up/scheduled_execution.py`

- [x] 写失败测试，断言 `[10:00,11:30)`、`[13:00,14:30)` 可评估，午休和 14:30 后不可评估，14:25 同时给卖出提醒但仍允许评估。
- [x] 运行 `uv run --group server pytest tests/alphaagent/test_limit_up_scheduled_execution.py -q`，确认旧窄窗口实现失败。
- [x] 将版本改为 `limit-up-scheduled-v2`，更新 `ENTRY_WINDOWS`、`execution_clock()` 和 `next_session_execution_clock()`。
- [x] 重跑定向测试，期望全部通过。

### Task 2: 保留观察候选且禁止错误提升

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`

- [x] 写失败测试：结构合格、`portfolio_selected=true`、研究动作仍为 `observe` 的首板必须进入两只综合列表，但保持 `observe/approaching_trigger`；只有 `research_action=buy_now` 且时钟和新鲜度通过才成为 `trigger_ready`。
- [x] 运行 `uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k 'portfolio and scheduled'`，确认旧过滤逻辑失败。
- [x] 修改 `_build_live_portfolio()` 接收结构合格观察项；修改 `_scheduled_live_signal()` 按原始研究动作、时钟和陈旧度三层处理。
- [x] 重跑定向测试，期望全部通过。

### Task 3: 生成按股票去重的零买点漏斗

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live_trace.py`
- Modify: `alphaagent/server/services/limit_up/live_trace_service.py`

- [x] 写失败测试，构造市场阻断、动态阻断、触发、未触发封板和结构排除事件，断言 `lane_funnels.first_board` 的各级数量及 `primary_blockers`。
- [x] 运行 `uv run --group server pytest tests/alphaagent/test_limit_up_live_trace.py -q`，确认尚无漏斗字段。
- [x] 从每只股票事件中选择最接近触发的一帧，按股票去重统计 `radar/recommended/approaching/triggered/sealed_without_trigger/structural_rejected` 和未通过检查代码。
- [x] 重跑定向测试，期望全部通过。

### Task 4: 标记历史候选代理并更新产品界面

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`

- [x] 写失败测试，断言历史报告返回 `execution_comparability.status=candidate_proxy_only`、缺失实时资金/Tick/L2 字段，且执行窗口为两个连续交易时段。
- [x] 更新 API 类型与实时页：顶部改为“连续盘中评估”，轨迹顶部用一行显示首板漏斗和前三个阻断项；回测紧邻收益显示“候选代理，非实盘等价”。
- [x] 运行 `pnpm --dir frontend test -- --run` 与 `pnpm --dir frontend run build`，期望通过。

### Task 5: 全历史和运行态验收

**Files:**
- Modify: `memory/06_backtests/limit_up_scheduled_execution_feasibility.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] 运行完整综合首板回测，记录信号、闭合、买入日、期末权益、复利、胜率、回撤、资金利用率、双倍成本和只成交炸板压力。
- [x] 分别核对设计段、后段时间验证和冻结后前向；若候选代理回撤差于 -10% 或双倍成本非正，恢复 v1 产品时钟但保留漏斗。
- [x] 运行 `uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py -q`、前端测试和构建。
- [x] 执行 `docker compose up -d --build alphaagent-api alphaagent-web`，用浏览器验证 `http://localhost:8080/limit-up` 的桌面和 390px 视口、控制台和网络错误。
- [x] 将最终事实写回现有 memory 文件，不新增根目录脚本，不提交 Git。
