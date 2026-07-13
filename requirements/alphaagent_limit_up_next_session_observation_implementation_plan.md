# AlphaAgent 打板次交易时段观察实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `/limit-up` 在收盘后持续展示下一交易时段观察计划，并在 09:15 后按竞价数据更新为接近触发、研究买点触发或失效。

**Architecture:** 复用追加式 `limit_up_signal_snapshots` 保存初步/正式计划，不新增表。独立计划服务把现有实时候选转换为下一交易时段观察；实时扫描显式合并计划股票的定向行情；前端继续使用单列表，只扩展状态和结构化解释。

**Tech Stack:** Python 3.13、FastAPI、SQLAlchemy/PostgreSQL、现有 AkShareAdapter、pytest、React 18、TypeScript、TanStack Query、Vitest、Playwright。

---

### Task 1: 盘后计划服务和读侧优先级

**Files:**
- Create: `alphaagent/server/services/limit_up/next_session_plan.py`
- Modify: `alphaagent/server/services/limit_up/live_repository.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Test: `tests/alphaagent/test_limit_up_next_session_plan.py`

- [ ] **Step 1: 写失败测试**

覆盖三个行为：正式计划优先于初步计划；周五计划在周末保持可读；计划候选统一为观察状态且包含源交易日和下一交易时段标识。

```python
def test_final_plan_is_preferred_without_expiring_on_weekend(monkeypatch):
    monkeypatch.setattr(plan_service, "load_latest_next_session_plan", lambda: FINAL_PLAN)
    result = live_service.get_latest_live_snapshot(
        datetime(2026, 7, 11, 20, 0, tzinfo=SHANGHAI)
    )
    assert result["mode"] == "next_session_final"
    assert result["source_trade_date"] == "2026-07-10"
    assert result["target_session"] == "next_trading_session"
    assert result["data_quality"]["is_stale"] is False
```

- [ ] **Step 2: 确认测试先失败**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_next_session_plan.py -q`

Expected: FAIL，因为计划服务和计划读侧尚不存在。

- [ ] **Step 3: 实现最小计划服务**

`next_session_plan.py` 只暴露以下接口：

```python
PLAN_MODES = ("next_session_preliminary", "next_session_final")

def refresh_next_session_plan(
    phase: Literal["preliminary", "final"],
    *,
    source_trade_date: date | None = None,
    captured_at: datetime | None = None,
    adapter: AkShareAdapter | None = None,
) -> dict[str, object]:
    local_at = _local_datetime(captured_at or datetime.now(SHANGHAI))
    source_date = source_trade_date or load_latest_daily_trade_date(local_at.date())
    if source_date is None:
        return {"status": "empty", "reason": "daily_history_unavailable"}
    pools = (adapter or AkShareAdapter()).limit_up_pools(source_date.strftime("%Y%m%d"))
    snapshot = build_next_session_plan_snapshot(pools, source_date, local_at, phase)
    return save_snapshot(snapshot)

def get_latest_next_session_plan() -> dict[str, object] | None:
    return load_latest_next_session_plan(strategy_version=LIVE_STRATEGY_VERSION)

def start_next_session_plan_warmup() -> dict[str, object]:
    if _warmup_running():
        return {"status": "running", "already_running": True}
    _start_warmup_thread()
    return {"status": "started"}
```

实现约束：

- 来源日期取最新完整日线日，不猜下一自然日。
- 使用源日期最终涨停池和现有 `build_live_snapshot`/候选规则生成计划。
- 只把原 `next_auction` 研究动作转成 `action=observe`、`signal_state=observing`。
- 保存 `source_trade_date`、`target_session=next_trading_session`、`plan_phase` 和 `execution_permission=research_only`。
- `preliminary` 与 `final` 追加保存；读侧按 `final > preliminary`、再按采集时间选择。

- [ ] **Step 4: 让非交易时段 GET 返回计划**

`get_latest_live_snapshot()` 在没有当前交易日实时快照时优先返回最新计划；计划不走旧的非交易时段 stale 降级。没有计划时才返回现有 empty/stale 结果。GET 不调用适配器、不写库。

- [ ] **Step 5: 运行定向测试**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_next_session_plan.py tests/alphaagent/test_limit_up_live.py -q`

Expected: PASS。

### Task 2: 竞价观察到研究买点触发

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/next_session_plan.py`
- Test: `tests/alphaagent/test_limit_up_live.py`
- Test: `tests/alphaagent/test_limit_up_next_session_plan.py`

- [ ] **Step 1: 写 09:15 状态机失败测试**

```python
def test_auction_watch_never_becomes_actionable_before_0920():
    result = build_live_recommendations(
        [_candidate(previous_limit_up=True, auction_gap_pct=3.0)],
        _market(),
        datetime(2026, 7, 13, 9, 18, tzinfo=SHANGHAI),
    )
    signal = result["lanes"]["now"][0]
    assert signal["action"] == "observe"
    assert signal["signal_state"] == "approaching_trigger"
    assert signal["execution_permission"] == "research_only"
```

再覆盖 09:20 后全部硬门通过变为 `trigger_ready`，数据过期/竞价范围失败变为 `pending_auction` 或 `invalidated`。

- [ ] **Step 2: 确认测试先失败**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_live.py -q -k "auction_watch or trigger_ready"`

Expected: FAIL，因为 `auction_watch` 和结构化状态尚不存在。

- [ ] **Step 3: 扩展最小状态机**

```python
def session_stage(captured_at: datetime) -> str:
    local = _local_datetime(captured_at)
    if local.weekday() >= 5:
        return "closed"
    minute = local.hour * 60 + local.minute
    if minute < 9 * 60 + 15:
        return "preopen"
    if minute < 9 * 60 + 20:
        return "auction_watch"
    if minute < 9 * 60 + 30:
        return "auction"
    if minute <= 11 * 60 + 30:
        return "morning"
    if minute < 13 * 60:
        return "lunch"
    if minute < 14 * 60 + 30:
        return "afternoon"
    if minute <= 14 * 60 + 57:
        return "tail"
    if minute < 15 * 60:
        return "close_auction"
    return "closed"
```

- `ACTIVE_SESSION_STAGES` 增加 `auction_watch`。
- `auction_watch` 只能输出 `observe`，不能输出 `buy_now`。
- `auction` 只有硬门、数据日期和新鲜度全部通过时输出 `signal_state=trigger_ready`。
- `action` 仍只决定研究动作；`execution_permission` 第一版固定为 `research_only`。

- [ ] **Step 4: 定向获取计划股票行情**

`_fetch_live_payloads()` 增加 `planned_symbols` 参数，最多五只，通过现有 `AkShareAdapter.get_quotes()` 定向获取，并用 `Quote.to_api()` 合并进涨幅榜结果。定向失败只追加 `source_errors`，计划股票保留为 `pending`，不能默认为通过。

- [ ] **Step 5: 增加结构化解释**

每条信号统一补充：

```python
{
    "strategy_name": "二进三·弱转强突破",
    "selection_reasons": ["板块核心", "前板换手回封"],
    "trigger_checks": [
        {"code": "auction_gap", "label": "竞价强度", "status": "passed", "observed": "3.00%", "required": "1%-7%"},
    ],
    "buy_instruction": "09:20-09:24硬门保持通过时按竞价计划执行",
    "sell_instruction": "D+1动态评估竞价兑现，否则15:00退出",
    "cancel_checks": ["竞价低于1%或高于7%", "跌出动态Top5", "市场门关闭"],
}
```

解释从现有候选字段和规则生成，不复制一套新的交易判断。

- [ ] **Step 6: 运行状态机测试**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_next_session_plan.py -q`

Expected: PASS。

### Task 3: 15:05、19:00、21:30 调度与启动补偿

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
- Modify: `alphaagent/server/main.py`
- Test: `tests/alphaagent/test_data_sync_schedule.py`

- [ ] **Step 1: 写调度失败测试**

```python
def test_next_session_plan_has_preliminary_and_final_schedule_paths():
    preliminary = next(row for row in svc.DEFAULT_BATCH_SCHEDULES if row["id"] == "limit_up_plan_1505")
    eod = next(row for row in svc.DEFAULT_BATCH_SCHEDULES if row["id"] == "eod_1900")
    finalize = next(row for row in svc.DEFAULT_BATCH_SCHEDULES if row["id"] == "eod_finalize_2130")
    assert preliminary["cron"] == "5 15 * * 1-5"
    assert "limit_up_next_session_plan_final" in eod["job_ids"]
    assert "limit_up_next_session_plan_final" in finalize["job_ids"]
```

另断言实时扫描窗口从 09:15 开始、09:14 不运行。

- [ ] **Step 2: 确认测试先失败**

Run: `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q -k "next_session_plan or live_scan_window"`

Expected: FAIL。

- [ ] **Step 3: 实现调度和内部任务**

- 新增 `limit_up_plan_1505`，调用 `refresh_next_session_plan("preliminary")`。
- 在 19:00 和 21:30 job 尾部加入 `limit_up_next_session_plan_final`；内部任务调用 `refresh_next_session_plan("final")`。
- `_limit_up_live_scan_window_open()` 起点改为 09:15。
- API lifespan 调用 `start_next_session_plan_warmup()`；函数只在最新完整交易日缺计划时启动单飞后台线程。

- [ ] **Step 4: 运行调度测试**

Run: `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q`

Expected: PASS。

### Task 4: 单列表展示计划、状态和规则

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `frontend/src/features/limitUp/nextSessionPlan.spec.ts`
- Create: `frontend/src/features/limitUp/nextSessionPlan.ts`

- [ ] **Step 1: 写前端纯逻辑失败测试**

```typescript
it("labels final next-session plans without calling them a closed market", () => {
  expect(liveHeader(FINAL_PLAN)).toEqual({
    title: "次交易时段正式观察",
    tone: "neutral",
  });
});
```

再覆盖 `preliminary`、`approaching_trigger`、`trigger_ready + research_only` 和 `invalidated`。

- [ ] **Step 2: 确认测试先失败**

Run: `pnpm --dir frontend test -- --run`

Expected: FAIL，因为辅助函数尚不存在。

- [ ] **Step 3: 扩展 API 类型和最小展示 helper**

为 snapshot 增加 `mode/source_trade_date/target_session/plan_phase`；为 signal 增加 `signal_state/execution_permission/strategy_name/selection_reasons/trigger_checks/buy_instruction/sell_instruction/cancel_checks`。

`nextSessionPlan.ts` 只负责状态到中文标签和颜色语义的纯映射，不重新判断交易条件。

- [ ] **Step 4: 修改现有单列表**

- 计划模式顶部显示“初步观察”或“正式观察”，不显示“市场门关闭”。
- 股票行按顺序显示当前状态、战法、最多四条入选原因、未通过/待确认检查、买入、卖出和取消规则。
- `trigger_ready + research_only` 固定显示“买点已触发（研究）”。
- 保留现有四板位切换和桌面/移动端换行，不增加新卡片或设置项。

- [ ] **Step 5: 运行前端测试和构建**

Run: `pnpm --dir frontend test -- --run`

Expected: PASS。

Run: `pnpm --dir frontend run build`

Expected: PASS，只有既有 chunk-size warning 可以保留。

### Task 5: 回归、部署、浏览器验收和提交

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: 完整定向回归**

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_*.py -q`

Expected: PASS。

Run: `uv run --group server pytest tests/alphaagent/test_data_sync_schedule.py -q`

Expected: PASS。

Run: `pnpm --dir frontend test -- --run && pnpm --dir frontend run build`

Expected: PASS。

- [ ] **Step 2: 重建并验证真实计划**

Run: `docker compose up -d --build alphaagent-api alphaagent-web`

验证最新完整交易日能补建 `next_session_final`，`GET /api/limit-up/live` 命中缓存且不产生额外快照；确认页面打开速度和容器健康。

- [ ] **Step 3: Playwright 验收**

在 `1440x1000` 和 `390x844` 检查：正式观察标题、四板位、每股原因、触发检查、买卖/取消规则、无整页横向溢出、console 0 error/0 warning。

- [ ] **Step 4: 维护项目记忆**

只改写现有 Limit-up 段落，记录当前计划时序、运行接口、验证结果和 `research_only` 限制；不追加聊天式流水记录。

- [ ] **Step 5: 定向提交**

逐文件/逐 hunk 暂存本任务，确认 `git diff --cached --check` 和暂存 diff 不含主线、量化或 D2 研究后提交：

```bash
git commit -m "feat(limit-up): add next-session observation flow"
```

不推送，其他工作区改动保持原样。
