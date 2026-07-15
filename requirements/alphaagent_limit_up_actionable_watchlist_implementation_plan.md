# AlphaAgent 可转买观察列表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Do not use subagents or create commits for this repository task.

**Goal:** 让 `/limit-up` 实时操作列表只展示仍可能转成买点的候选，把永久拒绝、错过和失效股票留在当日轨迹。

**Architecture:** 后端在生成 `watchlist` 时执行状态白名单，避免无效候选进入 API 操作集合；前端使用相同契约做防御过滤，兼容旧缓存响应。轨迹数据流保持不变，因此被过滤股票仍可复盘。

**Tech Stack:** Python 3.13、FastAPI 服务层、pytest、React、TypeScript、Vitest、Playwright。

---

### Task 1: 锁定后端可转买 watchlist

**Files:**
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`

- [ ] **Step 1: 把旧拒绝项测试改成状态分层测试**

构造结构阻断、动态等待、概念预热、已错过四只首板，断言 watchlist 只保留动态等待和概念预热：

```python
assert [row["vt_symbol"] for row in watchlist] == [
    "600002.SSE",
    "600003.SSE",
]
assert {row["signal_state"] for row in watchlist} == {
    "approaching_trigger",
    "concept_warming",
}
assert all("今日拒买" not in str(row.get("reason") or "") for row in watchlist)
```

- [ ] **Step 2: 运行定向测试并确认旧实现失败**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k live_watchlist
```

Expected: FAIL，旧实现仍返回结构阻断股票。

- [ ] **Step 3: 实现后端状态白名单**

在 `_build_live_watchlist()` 中，在生成观察行之前跳过：

```python
signal_state = str(signal.get("signal_state") or "observing")
permanent_state = signal_state in {"rejected", "missed", "invalidated"}
structural_blocked = str(signal.get("blocking_scope") or "") == "structural"
if permanent_state or structural_blocked:
    continue
```

不能按 `lane_decision=blocked` 直接过滤；该粗粒度字段也包含可修复动态 blocker。
剩余候选只生成 `concept_warming / approaching_trigger / observing`，删除“今日拒买”和
“板位硬门未通过，今日不买”的 watchlist 分支。

- [ ] **Step 4: 运行后端 watchlist 测试**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "live_watchlist or structurally_selected_observation"
```

Expected: PASS。

### Task 2: 前端防御旧缓存并修正数量语义

**Files:**
- Modify: `frontend/src/features/limitUp/livePortfolio.spec.ts`
- Modify: `frontend/src/features/limitUp/livePortfolio.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [ ] **Step 1: 写前端失败测试**

在 watchlist 中加入 `rejected`、`missed`、`invalidated`、`blocking_scope=structural` 和
`approaching_trigger`，断言只返回最后一项；旧 lanes 回退响应也不得显示永久状态。

- [ ] **Step 2: 运行前端定向测试并确认失败**

Run:

```bash
pnpm --dir frontend test -- --run src/features/limitUp/livePortfolio.spec.ts
```

Expected: FAIL，旧实现仍把永久状态拼入列表。

- [ ] **Step 3: 实现前端防御过滤**

在 `livePortfolio.ts` 增加小函数：

```typescript
const NON_ACTIONABLE_STATES = new Set(["rejected", "missed", "invalidated"]);

function canTransitionToBuy(signal: LimitUpLiveSignal): boolean {
  return (
    !NON_ACTIONABLE_STATES.has(signal.signal_state ?? "")
    && signal.blocking_scope !== "structural"
    && signal.missed_preseal_entry !== true
  );
}
```

后端 portfolio、watchlist 和旧 lanes 回退三条读取路径都调用该函数。

- [ ] **Step 4: 修正实时页数量和空状态**

`LimitUpPage.tsx` 使用过滤后的 `signals` 计算组合数和观察数；文案改为：

```text
可买组合 N / 2 · 可转买观察 M
暂无可转买观察，保持现金；全部雷达结果见当日轨迹
```

- [ ] **Step 5: 运行前端测试**

Run:

```bash
pnpm --dir frontend test -- --run
```

Expected: 通过全部前端测试。

### Task 3: 回归、部署与页面验收

**Files:**
- Modify only files required by failing tests
- Update: `memory/03_data/data_flow.md`
- Update: `memory/05_runtime/run_debug.md`
- Update: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 运行后端相关完整套件**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_akshare_adapter.py tests/alphaagent/test_api.py -q
```

- [ ] **Step 2: 运行构建和静态检查**

```bash
pnpm --dir frontend run build
python -m compileall -q alphaagent/server/services/limit_up tests/alphaagent
git diff --check
```

- [ ] **Step 3: 重建产品服务**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps
```

Expected: API、Gateway、PostgreSQL、Redis healthy，Web 运行。

- [ ] **Step 4: 浏览器验证**

打开 `http://localhost:8080/limit-up`，验证：

- 实时操作列表没有“硬性排除 / 今日拒买”。
- 若有可转买候选，只显示预热、接近、市场等待或买点触发。
- 被排除股票仍能在当日轨迹看到。
- 桌面和 `390x844` 无横向溢出，console 0 error / 0 warning。

- [ ] **Step 5: 更新当前事实**

只在现有 memory 文件内更新实时列表与轨迹分工，不改变 v12 回测数字；最终不执行
`git commit` 或 `git push`。
