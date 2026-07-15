# AlphaAgent 弱市题材进攻首板 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` inline. This repository task must not dispatch subagents. Steps use checkbox syntax for tracking.

**Goal:** 在现有综合首板中增加经过冻结验证的弱市题材进攻路径，同时保持原分歧修复路径、基本面风险门和产品单一入口不变。

**Architecture:** `lane_research.py` 先执行现有首板规则，只在剩余 lane blockers 完全属于三个冻结软阻断时评估进攻路径。历史使用 D-1 市场和行业代理，实时由 `live_service.py` 既有映射提供当时概念强度、概念龙位和情绪；两端共用同一个纯规则函数。

**Tech Stack:** Python 3.13、FastAPI 服务层、pandas 历史回放、PostgreSQL、pytest、React/Vitest、Docker Compose。

---

### Task 1: 冻结首板双路径规则

**Files:**
- Modify: `tests/alphaagent/test_limit_up_lanes.py`
- Modify: `tests/alphaagent/test_limit_up_setup_tags.py`
- Modify: `alphaagent/server/services/limit_up/lane_research.py`

- [x] **Step 1: 写失败测试**

新增 `_weak_market_attack_candidate()` 夹具，覆盖：退潮/混合、触板 3 次、承接 55、热度
60、龙二且 lane blockers 只可能是触板弱、财报缺失、修复缺失时返回：

```python
assert result["decision"] == "eligible"
assert result["first_board_route"] == "weak_market_theme_attack"
assert "weak_market_theme_attack" in result["setup_tags"]
assert "weak_market_theme_attack_setup" in result["favorable_factors"]
```

分别把触板改为 2、承接改为 54.99、热度改为 59.99、龙位改为 3、阶段改为
`broad_rise/repair`、财报改为已披露利润 9.99%、加入低位失败或基本面风险，断言对应
硬门仍存在。翻转 `outcome.sealed/next_close_return_pct` 后决策和路由必须完全相同。

- [x] **Step 2: 验证旧实现失败**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_setup_tags.py -q -k "weak_market_theme_attack"
```

Expected: FAIL，旧实现没有进攻路由，三个软阻断仍否决。

- [x] **Step 3: 实现纯规则**

固定以下常量：

```python
FIRST_BOARD_ATTACK_MIN_TOUCH_COUNT = 3
FIRST_BOARD_ATTACK_MIN_SUPPORT_SCORE = 55.0
FIRST_BOARD_ATTACK_MIN_HEAT_SCORE = 60.0
FIRST_BOARD_ATTACK_MAX_LEADER_RANK = 2
FIRST_BOARD_ATTACK_PHASES = frozenset({"retreat", "mixed", "ice", "ebb", "divergence"})
FIRST_BOARD_ATTACK_SOFT_BLOCKERS = frozenset({
    "first_board_touch_gene_weak",
    "financial_report_unavailable",
    "first_board_repair_setup_missing",
})
```

让 `_first_board_rules()` 返回 `(blockers, favorable, route)`。原规则无阻断时 route 为
`divergence_repair`；只有 blockers 非空且完全属于软阻断集合、五个阈值全部满足时才清空
blockers，route 为 `weak_market_theme_attack`。`premium_gate_passed` 接受任一路径，
`detect_setup_tags()` 根据 route 增加 `weak_market_theme_attack`，不得读取 `outcome`。

- [x] **Step 4: 运行规则回归**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py tests/alphaagent/test_limit_up_setup_tags.py -q
```

Expected: PASS，现有分歧修复、回马板和接力夹具不变。

### Task 2: 实时推荐和页面解释

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: 写实时失败测试**

用 `divergence` 情绪、10:12、触板 3 次、承接 55、有效 `launch` 概念、概念强度 60、
概念龙二和缺财报夹具调用 `_attach_lane_decisions()`，断言 lane eligible、route/tag 保留；
进入距板 1% 且共享执行检查通过时，`build_live_recommendations()` 返回 `buy_now`。把
`financial_risk.blocked` 改为真时必须返回 `pass`。

- [x] **Step 2: 更新最小说明层**

在 `_SETUP_LABELS`、`_FACTOR_LABELS` 和前端 `setupTagLabel/factorLabel` 增加：

```text
weak_market_theme_attack -> 弱市题材进攻
weak_market_theme_attack_setup -> 强题材龙一/龙二承接
```

`_sweep_entry_reason()` 检测进攻标签时说明“弱市题材进攻，概念龙一/龙二且承接通过”；
`financial_report_unavailable` 的后端和前端文案统一改为“本地财报数据未覆盖”。不增加
策略开关、卡片或新接口。

- [x] **Step 3: 运行实时和前端验证**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "weak_market_theme_attack or live_first_board"
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
```

Expected: PASS。

### Task 3: 升级 v14 并执行冻结账户验收

**Files:**
- Modify: `tests/alphaagent/test_limit_up_history.py`
- Modify: `alphaagent/server/services/limit_up/versions.py`

- [x] **Step 1: 升级版本测试和常量**

把版本断言和 `HISTORY_STRATEGY_VERSION` 从 `limit-up-history-v13` 升为
`limit-up-history-v14`，把实时证据版本升级为 `limit-up-live-v4`，避免旧规则快照污染
新路径前向账本；连续账户版本保持不变。

- [x] **Step 2: 构建并重建 602 日账本**

```bash
docker compose up -d --build alphaagent-api
docker compose exec -T alphaagent-api python -c 'from alphaagent.server.services.limit_up.history_service import rebuild_history_sync; print(rebuild_history_sync())'
docker compose restart alphaagent-api
```

Expected: `status=ready`，覆盖 `2024-01-15..2026-07-14` 或更晚的最新完整交易日。

- [x] **Step 3: 冻结验收**

调用 `get_scheduled_history_backtest(None, None, trade_limit=None)`。只有信号不少于 290、
闭合交易不少于 137、胜率不低于 61%、复利高于 `+170.5731%`、最大回撤不差于
`-10%`、时间验证段复利高于 `+55.9578%`、双倍成本复利高于 `+138.1645%` 时保留
执行资格。逐笔核对新增、替换、跳过订单以及 14:30 精确/收盘代理来源；失败时把进攻
路径降为观察，不继续调阈值。

正式 PostgreSQL 重建覆盖 `2024-01-15..2026-07-14` 共 602 日。冻结账户得到 290 个
信号、139 笔买入、137 笔闭合和 2 笔待 D+1，胜率 `62.0438%`、复利
`+204.8622%`、最大回撤 `-7.9408%`、利润因子 `2.4185`；时间验证段
`+61.4413%`，双倍成本 `+162.0535% / -8.6864%`，全部通过预设门槛。新路径新增
14 个候选，其中 9 笔成交、5 笔因双仓占满跳过；成交为 6 胜 3 负，1 笔使用精确
14:30 价、8 笔使用收盘代理。未在查看结果后调整阈值。

### Task 4: 完整验证和记忆卫生

**Files:**
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`
- Modify: `memory/06_backtests/limit_up_first_board_1330_exit_research.md`

- [x] **Step 1: 更新当前事实**

把 v14 的账户结果、财报覆盖 1,524/3,481、历史点时成员覆盖风险、新增样本和退出价格
代理写入现有 overview/研究报告；不新增 raw JSON、诊断脚本或根目录文件。

- [x] **Step 2: 完整回归**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_api.py -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
docker compose ps
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8080/limit-up
```

Expected: 测试、编译、构建和 diff 检查通过；API/Gateway/PostgreSQL/Redis healthy，页面
返回 200。本任务不自动提交 Git。

实际结果：后端 `613 passed`、前端 `48 passed`；Python 编译、TypeScript/生产构建和
`git diff --check` 通过。Web 镜像已重建，API/Gateway/PostgreSQL/Redis healthy，
`http://localhost:8080/limit-up` 返回 200；容器内版本为
`limit-up-history-v14 / limit-up-live-v4`，账本为 602 日。
