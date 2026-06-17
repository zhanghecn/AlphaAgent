# 统一增量定时同步 — 实现执行计划

> **For Claude:** 按任务顺序实现，每个任务先写测试再实现再验证。设计依据见
> `requirements/alphaagent_unified_incremental_schedule_plan.md`。
> 项目约束：**未经主人明确同意，不要 `git commit` / `git push`**。每个任务以「验证通过」为完成标志，不内置 commit 步骤。

**Goal:** 把数据同步从「24 个分散单任务 cron」改为「批量定时（默认 14:00 + 18:00 两档，可自定义）+ 真增量 + 任务内并发 + 失败隔离」。

**Architecture:** 新增 `sync_batch_schedules` 表存「定时档」；调度器从驱动单任务改为驱动批量档；`start_sync_batch` 扩展接受 `job_ids/concurrency`；批量内任务按优先级串行、单任务失败不中止整批；日K/分钟K 改真增量（按最后 bar 日期续传）+ 任务内 ThreadPool 并发。沿用现有 daemon 线程，不引入 Redis/worker（KISS）。

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / PostgreSQL / pytest（后端）；React 18 + TypeScript + TanStack Query + Tailwind（前端）。

**关键代码位置：**
- 后端服务：`alphaagent/server/services/data_sync.py`
- 后端 API：`alphaagent/server/api/data_sync.py`
- DB schema：`alphaagent/server/db/schema.py`
- 前端页面：`frontend/src/pages/DataManagementPage.tsx`
- 前端 API：`frontend/src/api/dataSync.ts`

---

## Phase 1：数据层

### Task 1：新增 `sync_batch_schedules` 表

**Files:**
- Modify: `alphaagent/server/db/schema.py`（在 `sync_job_runs` 表定义后，`stocks` 表之前插入）
- Test: `tests/alphaagent/test_data_sync_schedule.py`（新建）

**Step 1：写测试（表存在性）**

```python
# tests/alphaagent/test_data_sync_schedule.py
from alphaagent.server.db import schema


def test_sync_batch_schedules_table_defined():
    table = schema.sync_batch_schedules
    assert table.name == "sync_batch_schedules"
    cols = {c.name for c in table.columns}
    assert {"id", "name", "cron", "job_ids", "enabled", "concurrency"}.issubset(cols)
    assert {"last_status", "last_started_at", "last_finished_at"}.issubset(cols)
```

**Step 2：跑测试确认失败**

Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py::test_sync_batch_schedules_table_defined -v`
Expected: FAIL（`sync_batch_schedules` 不存在）

**Step 3：在 `schema.py` 加表定义**

```python
sync_batch_schedules = Table(
    "sync_batch_schedules",
    metadata,
    Column("id", String(80), primary_key=True),
    Column("name", String(120), nullable=False),
    Column("cron", String(80), nullable=False),
    Column("job_ids", JSONB, nullable=False, server_default="[]"),
    Column("enabled", Boolean, nullable=False, server_default="true"),
    Column("concurrency", Integer, nullable=False, server_default="8"),
    Column("last_status", String(40), nullable=True),
    Column("last_started_at", DateTime(timezone=True), nullable=True),
    Column("last_finished_at", DateTime(timezone=True), nullable=True),
    Column("last_message", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()),
)
```

> `ensure_schema_once(engine)` 会自动建 `metadata` 里所有表，无需额外注册。

**Step 4：跑测试确认通过**

Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py::test_sync_batch_schedules_table_defined -v`
Expected: PASS

---

### Task 2：默认档 seed + `DEFAULT_JOBS` cron 清空

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
  - `DEFAULT_JOBS`（`:73-265`）：所有 `schedule_cron=...` 改为不传（默认 `None`）
  - 新增 `DEFAULT_BATCH_SCHEDULES` 常量
  - `seed_default_registry`（`:1230`）：增加 seed 默认档逻辑

**Step 1：写测试（seed 默认档）**

```python
# 追加到 tests/alphaagent/test_data_sync_schedule.py
from alphaagent.server.services import data_sync as svc


def test_default_batch_schedules_defined():
    ids = {s["id"] for s in svc.DEFAULT_BATCH_SCHEDULES}
    assert {"intraday_14h", "eod_18h"}.issubset(ids)


def test_default_jobs_have_no_cron():
    # 去掉单任务定时后，DEFAULT_JOBS 的 schedule_cron 应全部为 None
    for job in svc.DEFAULT_JOBS:
        assert job.schedule_cron is None, f"{job.id} 仍有 schedule_cron"


def test_intraday_schedule_contains_intraday_jobs():
    intraday = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "intraday_14h")
    assert "sync_stock_minute_bars" in intraday["job_ids"]
    # 14:00 拿不到当日日K，日K 不应在盘中档
    assert "sync_stock_daily_bars" not in intraday["job_ids"]


def test_eod_schedule_has_daily_bars_and_lhb_last():
    eod = next(s for s in svc.DEFAULT_BATCH_SCHEDULES if s["id"] == "eod_18h")
    assert "sync_stock_daily_bars" in eod["job_ids"]
    # 龙虎榜发布晚，应排在靠后位置
    assert eod["job_ids"].index("sync_stock_lhb_records") > eod["job_ids"].index("sync_stock_daily_bars")
```

**Step 2：跑测试确认失败**

Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py -v -k "default"`
Expected: FAIL（`DEFAULT_BATCH_SCHEDULES` 不存在 / `DEFAULT_JOBS` 仍有 cron）

**Step 3：实现**

a) `DEFAULT_JOBS`：把 24 处 `schedule_cron="..."` 全部删掉（保留 job 定义）。

b) 在 `DEFAULT_JOBS` 之后、`SYNC_BATCH_PROFILES` 之前新增：

```python
# 执行优先级 = 列表顺序（上游先跑，保证数据依赖）
DEFAULT_BATCH_SCHEDULES: list[dict[str, Any]] = [
    {
        "id": "intraday_14h",
        "name": "盘中同步（14:00，服务尾盘选股）",
        "cron": "0 14 * * 1-5",
        "enabled": True,
        "concurrency": 8,
        "job_ids": [
            "sync_stock_list",          # 实时快照（最新价/涨跌幅/量比）
            "sync_stock_minute_bars",   # 当日分钟K（截至14:00）
            "sync_stock_fund_flows",    # 个股资金流
            "sync_stock_hot_ranks",     # 个股热度
            "sync_limit_up_pools",      # 涨停池/跌停池
        ],
    },
    {
        "id": "eod_18h",
        "name": "盘后同步（18:00，补完整数据）",
        "cron": "0 18 * * 1-5",
        "enabled": True,
        "concurrency": 8,
        "job_ids": [
            "sync_stock_list",
            "sync_stock_daily_bars",     # 完整日K（真增量）
            "sync_sector_list",
            "sync_sector_members",
            "sync_stock_sector_memberships",
            "sync_sector_daily_bars",
            "sync_sector_fund_flows",
            "sync_sector_period_scores",
            "sync_stock_lhb_records",    # 龙虎榜（18:00后发布，排靠后）
            "sync_stock_notices",
            "sync_stock_financial_quarterly",
            "sync_stock_financial_indicators",
            "sync_stock_business_segments_history",
        ],
    },
]

# 基础任务 → 其失败时应跳过的下游（用于失败隔离）
JOB_UPSTREAM: dict[str, str] = {}
# 在 seed 时根据 job_ids 前缀填充（见 Task 4 用到），这里先建占位：
# sync_stock_list 失败 → 跳过所有股票类下游；sync_sector_list 失败 → 跳过板块类下游
```

c) `seed_default_registry` 末尾追加 seed 批量档（模式同 job seed）：

```python
for sched in DEFAULT_BATCH_SCHEDULES:
    existing = session.execute(
        select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.id == sched["id"])
    ).first()
    values = {
        "id": sched["id"],
        "name": sched["name"],
        "cron": sched["cron"],
        "job_ids": sched["job_ids"],
        "enabled": sched["enabled"],
        "concurrency": sched["concurrency"],
    }
    if existing is None:
        session.execute(schema.sync_batch_schedules.insert().values(**values))
    else:
        session.execute(
            schema.sync_batch_schedules.update()
            .where(schema.sync_batch_schedules.c.id == sched["id"])
            .values(**values)
        )
```

**Step 4：跑测试确认通过**

Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py -v -k "default"`
Expected: PASS

---

## Phase 2：批量执行增强

### Task 3：`start_sync_batch` 支持 `job_ids / concurrency / source / schedule_id`

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:1352`（`start_sync_batch`）+ `:1437`（`_run_sync_batch`）

**Step 1：写测试**

```python
# 追加到 test 文件
def test_start_sync_batch_accepts_custom_job_ids(monkeypatch):
    captured = {}
    def fake_run_batch(batch_id, params, concurrency=8, source="manual", schedule_id=None):
        captured["concurrency"] = concurrency
        captured["source"] = source
        captured["schedule_id"] = schedule_id
        # 模拟填充 batch 的 job_ids
        from alphaagent.server.services.data_sync import _SYNC_BATCHES, _LATEST_BATCH_ID
        _SYNC_BATCHES[batch_id]["jobs"] = [{"job_id": j, "status": "pending"} for j in params.get("_job_ids", [])]
        captured["job_ids"] = [j["job_id"] for j in _SYNC_BATCHES[batch_id]["jobs"]]
    monkeypatch.setattr(svc, "_run_sync_batch", fake_run_batch)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    result = svc.start_sync_batch(job_ids=["sync_stock_list", "sync_stock_daily_bars"], concurrency=12, source="schedule", schedule_id="eod_18h")
    assert captured["concurrency"] == 12
    assert captured["source"] == "schedule"
    assert captured["schedule_id"] == "eod_18h"
    assert captured["job_ids"] == ["sync_stock_list", "sync_stock_daily_bars"]
```

**Step 2：跑测试确认失败** → Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py::test_start_sync_batch_accepts_custom_job_ids -v` → Expected FAIL

**Step 3：实现**

a) 改 `start_sync_batch` 签名与 job_ids 解析：

```python
def start_sync_batch(
    profile: str = "core",
    job_ids: list[str] | None = None,
    params: dict[str, Any] | None = None,
    concurrency: int = 8,
    source: str = "manual",
    schedule_id: str | None = None,
) -> dict[str, Any]:
    """Start a background batch that runs sync jobs in priority order."""
    global _LATEST_BATCH_ID
    if not is_database_configured():
        raise DataSyncError("DATABASE_URL is not configured")
    # 显式 job_ids 优先（来自 schedule），否则按 profile 取
    resolved = list(job_ids) if job_ids else list(SYNC_BATCH_PROFILES.get(profile, SYNC_BATCH_PROFILES["core"]))
    with _BATCH_LOCK:
        if _LATEST_BATCH_ID:
            latest = _SYNC_BATCHES.get(_LATEST_BATCH_ID)
            if latest and latest.get("status") == "running":
                return _copy_batch(latest)
    batch_id = uuid4().hex
    created_at = _utc_now_iso()
    batch = {
        "id": batch_id, "profile": profile if job_ids is None else "custom",
        "source": source, "schedule_id": schedule_id, "concurrency": concurrency,
        "status": "running", "created_at": created_at, "started_at": created_at,
        "finished_at": None, "current_job_id": resolved[0] if resolved else None,
        "total_jobs": len(resolved), "completed_jobs": 0, "succeeded_jobs": 0,
        "failed_jobs": 0, "skipped_jobs": 0, "rows_read": 0, "rows_written": 0,
        "message": "", "jobs": [_new_batch_job_item(j) for j in resolved],
    }
    with _BATCH_LOCK:
        _SYNC_BATCHES[batch_id] = batch
        _LATEST_BATCH_ID = batch_id
        _trim_batches_locked()
    thread = threading.Thread(
        target=_run_sync_batch,
        args=(batch_id, {**(params or {}), "_job_ids": resolved}),
        kwargs={"concurrency": concurrency, "source": source, "schedule_id": schedule_id},
        name=f"data-sync-batch-{batch_id[:8]}", daemon=True,
    )
    thread.start()
    return get_sync_batch(batch_id)
```

b) `_run_sync_batch` 签名加 `concurrency/source/schedule_id`（内部暂存到 batch dict 供子任务用）。

> `_new_batch_job_item` = 现有 jobs 列表里那段 dict 抽成函数（DRY）。

**Step 4：跑测试确认通过** → PASS

---

### Task 4：失败隔离（partial 状态 + 上游失败跳过下游）

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:1437`（`_run_sync_batch` 的 `for` 循环 + `:1493` 的 `return`）

**Step 1：写测试**

```python
def test_batch_continues_after_job_failure(monkeypatch):
    calls = []
    def fake_run_job(job_id, params=None, progress=None):
        calls.append(job_id)
        if job_id == "bad":
            raise RuntimeError("boom")
        return {"rows_read": 1, "rows_written": 1}
    monkeypatch.setattr(svc, "run_job", fake_run_job)
    monkeypatch.setattr(svc, "is_database_configured", lambda: True)
    result = svc.start_sync_batch(job_ids=["good_a", "bad", "good_b"])
    # 等线程跑完
    import time; time.sleep(0.2)
    batch = svc.get_sync_batch(result["id"])
    assert batch["status"] == "partial"          # 有失败但不全失败
    assert batch["failed_jobs"] == 1
    assert batch["succeeded_jobs"] == 2
    assert "good_b" in calls                     # 失败后继续跑后续
```

**Step 2：跑确认失败** → FAIL（现状一个失败就 return，good_b 不会跑）

**Step 3：实现**

把 `_run_sync_batch` 循环里 `except` 分支的 `_finish_batch(... "failed" ...); return` 改为：

```python
except Exception as exc:
    _update_batch_job(batch_id, job_id, {"status": "failed", "finished_at": _utc_now_iso(),
        "message": str(exc), "error_type": exc.__class__.__name__, "stage": "失败"})
    _increment_batch(batch_id, completed=1, failed=1)
    failed_upstream = job_id if job_id in {"sync_stock_list", "sync_sector_list"} else None
    if failed_upstream:
        # 跳过依赖该基础任务的下游
        for later in job_ids[index+1:]:
            if _depends_on(later, failed_upstream):
                _update_batch_job(batch_id, later, {"status": "skipped", "finished_at": _utc_now_iso(),
                    "message": f"上游 {failed_upstream} 失败，跳过", "stage": "跳过"})
                _increment_batch(batch_id, completed=1, skipped=1)
        # 继续跑剩余非依赖任务（不 return）
    continue
```

循环结束后按 `failed_jobs / succeeded_jobs` 决定终态：

```python
with _BATCH_LOCK:
    b = _SYNC_BATCHES.get(batch_id)
    failed = b["failed_jobs"]; succeeded = b["succeeded_jobs"]
if failed and succeeded == 0:
    _finish_batch(batch_id, "failed", "全部失败")
elif failed:
    _finish_batch(batch_id, "partial", f"{succeeded} 成功 / {failed} 失败")
else:
    _finish_batch(batch_id, "succeeded", "同步完成")
```

`_depends_on(job_id, upstream)`：用一个简单映射判定（`sync_stock_list` → 所有 `sync_stock_*`；`sync_sector_list` → 所有 `sync_sector_*` / `sync_stock_sector_memberships`）。

**Step 4：跑测试确认通过** → PASS

---

### Task 5：任务内并发（日K / 分钟K 用 ThreadPoolExecutor）

**Files:**
- Modify: `alphaagent/server/services/data_sync.py`
  - `_run_sync_stock_daily_bars`（`:443`，for 循环 `:469`）
  - `_run_sync_stock_minute_bars`（`:501`，for 循环 `:547`）
  - `DataSyncRunner.__init__` 接受 `concurrency`

**Step 1：写测试（并发受上限约束）**

```python
import threading
def test_daily_bars_respects_concurrency_limit(monkeypatch):
    seen = []
    lock = threading.Lock()
    active = {"n": 0, "peak": 0}
    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            with lock:
                active["n"] += 1
                active["peak"] = max(active["peak"], active["n"])
            import time; time.sleep(0.01)
            with lock:
                active["n"] -= 1
                seen.append(symbol)
            return {"items": []}
    runner = svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=3)
    # 注入 10 只假股票
    monkeypatch.setattr(svc, "_select_stock_rows", lambda **k: [{"symbol": f"{i:06d}", "exchange": "SSE", "name": "X"} for i in range(10)])
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda s, e, items: 0)
    runner._run_sync_stock_daily_bars({"limit": 5})
    assert active["peak"] <= 3, f"并发超限: peak={active['peak']}"
    assert len(seen) == 10
```

**Step 2：跑确认失败** → FAIL（现状串行，peak=1，但需要先把 for 改成可注入的 `_select_stock_rows` + 并发）

**Step 3：实现**

a) `DataSyncRunner.__init__` 加 `concurrency: int = 8`，存 `self.concurrency`。

b) 把日K的「查股票 + 循环」拆成：`_select_stock_rows(...)` 取列表（便于测试 mock），然后：

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

lock = threading.Lock()
def _do_one(stock_row):
    symbol = str(stock_row["symbol"]); exchange = str(stock_row["exchange"])
    # ... 现有单只逻辑（含异常捕获，返回 rows_read/written 或失败标记）...
    return {"symbol": symbol, "read": n_read, "written": n_written}

total_read = total_written = 0
with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
    futures = {pool.submit(_do_one, row): row for row in stock_rows}
    for fut in as_completed(futures):
        res = fut.result()
        with lock:
            total_read += res["read"]; total_written += res["written"]
        self._report_progress("写入股票日 K 线", ...)  # 用计数器推进
```

c) 分钟K 同样改造。

> 注意：`market_cache.get_or_set` 与 `_upsert_daily_bars`（各自 `session_scope`）在并发下需线程安全——`session_scope` 每次新建 session，互不影响；进度计数器加 `lock`。

**Step 4：跑测试确认通过** → PASS

---

## Phase 3：真增量

### Task 6：日K 真增量（按最后 bar 日期续传）

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:443`（`_run_sync_stock_daily_bars` 的 `only_missing` 段 `:452-458`）

**Step 1：写测试**

```python
def test_daily_increment_uses_start_date_from_last_bar(monkeypatch):
    requested = {}
    class FakeAdapter:
        def stock_bars(self, symbol, exchange=None, limit=90, interval="1d", start_date=None, end_date=None):
            requested[symbol] = start_date
            return {"items": []}
    # 假设 000001 最后日K 是 2026-06-10，000002 无记录
    monkeypatch.setattr(svc, "_last_bar_dates_daily", lambda symbols: {"000001.SSE": "2026-06-10"})
    monkeypatch.setattr(svc, "_select_stock_rows", lambda **k: [{"symbol": s.split(".")[0], "exchange": "SSE", "name": "X"} for s in ["000001.SSE", "000002.SSE"]])
    monkeypatch.setattr(svc, "_upsert_daily_bars", lambda *a, **k: 0)
    svc.DataSyncRunner(adapter=FakeAdapter(), concurrency=2)._run_sync_stock_daily_bars({"limit": 250, "incremental": True})
    assert requested["000001"].startswith("2026-06-11")   # 最后bar次日
    assert requested["000002"] is None or requested["000002"] == ""  # 新股拉默认历史
```

**Step 2：跑确认失败** → FAIL

**Step 3：实现**

a) 新增批量查询最后 bar 日期的 helper：

```python
def _last_bar_dates_daily(vt_symbols: list[str]) -> dict[str, str]:
    """返回 {vt_symbol: 最后一条日K的 trade_date(ISO)}，无记录的不含 key。"""
    if not vt_symbols:
        return {}
    with session_scope() as session:
        rows = session.execute(
            select(
                schema.stock_daily_bars.c.vt_symbol,
                func.max(schema.stock_daily_bars.c.trade_date),
            ).where(schema.stock_daily_bars.c.vt_symbol.in_(vt_symbols))
            .group_by(schema.stock_daily_bars.c.vt_symbol)
        ).all()
    return {str(r[0]): str(r[1]) for r in rows if r[1] is not None}
```

b) `_run_sync_stock_daily_bars`：先取股票列表 → `_last_bar_dates_daily(vt_symbols)` → 每只带 `start_date = last + 1day`（无 last 则不传，拉默认 `limit`）。废弃旧的 `only_missing`「整只跳过」逻辑（保留参数兼容但默认走真增量）。

**Step 4：跑测试确认通过** → PASS

---

### Task 7：分钟K 真增量

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:501`（分钟K `only_missing` 段）

**Step 1-4：** 同 Task 6 模式，新增 `_last_bar_dates_minute(vt_symbols, interval)`（查 `stock_minute_bars` 带 `interval` 过滤 + `MAX(trade_date)`，分钟表若用 datetime 则取 `MAX(trade_date)`），分钟K 带 `start_date` 续传。测试同构。保留 `mode=backtest_gap` 分支不动。

Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py -v` → 全部 PASS

---

## Phase 4：调度器

### Task 8：`_run_scheduled_jobs` 改驱动批量档

**Files:**
- Modify: `alphaagent/server/services/data_sync.py:2197`（`_run_scheduled_jobs`）

**Step 1：写测试**

```python
import datetime
def test_scheduler_triggers_matching_batch_schedule(monkeypatch):
    triggered = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw) or {"id": "x"})
    # 构造一个内存档：cron "0 14 * * 1-5"，当前时间 14:00 周三
    monkeypatch.setattr(svc, "_load_batch_schedules", lambda: [{"id": "eod_18h", "cron": "0 18 * * 1-5", "enabled": True, "job_ids": ["sync_stock_list"], "concurrency": 8}])
    # now_china = 18:00 周三
    monkeypatch.setattr(svc, "_now_china", lambda: datetime.datetime(2026, 6, 17, 18, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))))
    svc._run_scheduled_jobs()
    assert triggered and triggered[0]["job_ids"] == ["sync_stock_list"]
    assert triggered[0]["source"] == "schedule"
    assert triggered[0]["schedule_id"] == "eod_18h"


def test_scheduler_skips_disabled(monkeypatch):
    triggered = []
    monkeypatch.setattr(svc, "start_sync_batch", lambda **kw: triggered.append(kw))
    monkeypatch.setattr(svc, "_load_batch_schedules", lambda: [{"id": "x", "cron": "0 14 * * 1-5", "enabled": False, "job_ids": [], "concurrency": 8}])
    monkeypatch.setattr(svc, "_now_china", lambda: datetime.datetime(2026, 6, 17, 14, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))))
    svc._run_scheduled_jobs()
    assert not triggered
```

**Step 2：跑确认失败** → FAIL

**Step 3：实现**

```python
def _now_china() -> datetime:
    return datetime.now(timezone(timedelta(hours=8)))

def _load_batch_schedules() -> list[dict[str, Any]]:
    if not is_database_configured():
        return []
    with session_scope() as session:
        rows = session.execute(
            select(schema.sync_batch_schedules).where(schema.sync_batch_schedules.c.enabled == True)  # noqa: E712
        ).mappings().all()
    return [dict(r) for r in rows]

def _run_scheduled_jobs() -> None:
    now_china = _now_china()
    for row in _load_batch_schedules():
        cron = row.get("cron")
        if not cron:
            continue
        if _recently_started(row, within_seconds=1800):
            continue
        try:
            if _cron_matches(cron, now_china):
                try:
                    start_sync_batch(
                        job_ids=list(row.get("job_ids") or []),
                        concurrency=int(row.get("concurrency") or 8),
                        source="schedule",
                        schedule_id=str(row["id"]),
                    )
                except Exception as exc:
                    logger.warning("Scheduled batch %s failed: %s", row["id"], exc)
        except Exception:
            pass
```

`_recently_started(row, within_seconds)`：用 `row["last_started_at"]` 判断（同现有节流逻辑）。

**Step 4：跑测试确认通过** → PASS

---

## Phase 5：API

### Task 9：schedules CRUD 端点

**Files:**
- Modify: `alphaagent/server/api/data_sync.py`（新增端点）
- Modify: `alphaagent/server/services/data_sync.py`（新增 `list_schedules / create_schedule / update_schedule / delete_schedule`）

**Step 1：写测试（用 FastAPI TestClient，参考现有 `test_api.py` 模式）**

```python
from fastapi import FastAPI
from alphaagent.server.api.data_sync import router
# 测试 list / create / update / delete 四个端点返回结构正确（mock service 层）
```

**Step 2：跑确认失败** → FAIL

**Step 3：实现**

a) service 层 4 个函数（CRUD `sync_batch_schedules`，`create/update` 校验 cron 5 段、job_ids 在 `JOB_RUNNERS` 内）。

b) API 端点：

```python
@router.get("/schedules")
def list_schedules():
    try: return ok(service.list_schedules())
    except Exception as exc: return _sync_error(exc)

@router.post("/schedules")
def create_schedule(payload: dict[str, Any] = Body(default_factory=dict)):
    try: return ok(service.create_schedule(payload))
    except Exception as exc: return _sync_error(exc)

@router.patch("/schedules/{schedule_id}")
def update_schedule(schedule_id: str, payload: dict[str, Any] = Body(default_factory=dict)):
    try: return ok(service.update_schedule(schedule_id, payload))
    except Exception as exc: return _sync_error(exc)

@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: str):
    try: return ok(service.delete_schedule(schedule_id))
    except Exception as exc: return _sync_error(exc)

@router.post("/schedules/{schedule_id}/run")
def run_schedule(schedule_id: str):
    try: return ok(service.run_schedule_now(schedule_id))
    except Exception as exc: return _sync_error(exc)
```

**Step 4：跑测试 + 手测**

Run: `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_api.py -v` → PASS
手测：`curl -s http://localhost:8000/api/data-sync/schedules | jq` 看到两条默认档。

---

## Phase 6：前端

### Task 10：前端 API 封装

**Files:**
- Modify: `frontend/src/api/dataSync.ts`

**Step 1：实现 + 类型检查**

```typescript
export interface BatchSchedule {
  id: string;
  name: string;
  cron: string;
  job_ids: string[];
  enabled: boolean;
  concurrency: number;
  last_status?: string | null;
  last_started_at?: string | null;
  last_finished_at?: string | null;
}

export function fetchSyncSchedules() {
  return apiClient.get<BatchSchedule[]>("/data-sync/schedules");
}
export function createSyncSchedule(payload: Partial<BatchSchedule>) {
  return apiClient.post<BatchSchedule>("/data-sync/schedules", payload);
}
export function updateSyncSchedule(id: string, payload: Partial<BatchSchedule>) {
  return apiClient.patch<BatchSchedule>(`/data-sync/schedules/${id}`, payload);
}
export function deleteSyncSchedule(id: string) {
  return apiClient.delete<{ id: string }>(`/data-sync/schedules/${id}`);
}
export function runSyncSchedule(id: string) {
  return apiClient.post<{ id: string }>(`/data-sync/schedules/${id}/run`);
}
```

Run: `cd frontend && npx tsc --noEmit` → 无类型错误。

---

### Task 11：定时计划 UI

**Files:**
- Modify: `frontend/src/pages/DataManagementPage.tsx`（在「数据初始化」section `:334` 之后、「同步任务」section `:398` 之前，插入「定时计划」section）

**Step 1：实现**

新增一个 `<BatchSchedulesPanel />` 区块（可内联或拆 `frontend/src/components/BatchSchedulesPanel.tsx`）：
- `useQuery(["syncSchedules"], fetchSyncSchedules)` 列表
- 每行：名称 / cron / 启停 Switch / 任务数 / 上次状态徽标 / 「立即执行」/ 「编辑」/ 「删除」
- 「新增定时」按钮 → 表单：名称 + 时间(time) + 重复(周一~周五复选) + 勾选任务 + 并发度 → 生成 cron 提交
- 复用 `BatchProgress` 展示触发后的进度（轮询 `syncBatchLatest`）
- `useMutation` 调 create/update/delete/run，成功后 `invalidateQueries(["syncSchedules"])`

**Step 2：验证**

Run: `cd frontend && npm run build` → 构建成功
手测：访问 `/data`，看到「定时计划」区，显示 14:00 / 18:00 两条默认档，能启停、立即执行、新增自定义档。

---

## Phase 7：集成验证

### Task 12：端到端 + memory 更新

**Steps:**

1. 启动后端，确认日志 `Data sync scheduler started`，库里 `sync_batch_schedules` 有两条默认档，`sync_job_definitions` 的 `schedule_cron` 全空。
2. `POST /api/data-sync/schedules/intraday_14h/run` 手动触发 14:00 档，前端观察进度条按 job 顺序推进、单任务失败时后续继续、最终 `partial/succeeded`。
3. 验证增量：对一只已有日K的股票再跑 `eod_18h`，确认只拉 `start_date` 之后的新 bar（看日志 / `rows_read`）。
4. 验证并发：日K档触发时，观察日志并发拉取数 ≤ concurrency。
5. 全量回归：`uv run pytest tests/alphaagent/ -v` 全绿；`cd frontend && npm run build` 成功。

**Memory 更新**（任务完成后）：
- 更新 `memory/03_data/data_flow.md` 或新建 `memory/03_data/sync_schedule.md`：记录「批量定时（14:00/18:00）+ 真增量 + 任务内并发」的当前状态、验证命令、关键文件。
- 更新 `memory/09_decisions/decisions.md`：记录「废弃 24 个单任务 cron，改批量定时档」的决策。

---

## 风险与回退

- **AkShare 限流**：若并发触发封 IP，把 `DEFAULT_BATCH_SCHEDULES[*].concurrency` 调小（如 4），或给单源加 sleep。前端并发度可配。
- **cron 覆盖**：`seed_default_registry` 已改为 seed 批量档 + job cron 全空；若需保留某个单任务定时，可在 `DEFAULT_JOBS` 单独恢复（但默认不恢复）。
- **回退**：若新调度有问题，`DEFAULT_JOBS` 恢复 cron + 禁用 `sync_batch_schedules`（`enabled=false`）即可回到旧行为。
