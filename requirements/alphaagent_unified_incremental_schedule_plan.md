# AlphaAgent 数据同步 — 统一增量定时调度设计

> 日期：2026-06-17
> 状态：设计已与用户确认，待实现
> 关联代码：`alphaagent/server/services/data_sync.py`、`alphaagent/server/api/data_sync.py`、
> `alphaagent/server/db/schema.py`、`frontend/src/pages/DataManagementPage.tsx`、`frontend/src/api/dataSync.ts`
> 与 `alphaagent_data_sync_management_plan.md` 的关系：那份是早期理想蓝图（Redis + 独立 worker +
> 多 provider），实际实现已简化为单进程 daemon 线程 + 单 AkShare 源。本文档是基于**现有简化实现**
> 的增量改造，不引入 Redis / 独立 worker，遵循 KISS。

## 1. 背景与目标

用户希望把数据管理从「24 个分散的单任务定时」改为「统一的批量增量定时同步」：

- **统一定时**：去掉 24 个零散的单任务 cron，用一个「批量定时」机制替代。
- **默认两档**：每天 `14:00`（盘中，服务尾盘选股）+ `18:00`（盘后，补完整数据）。
- **支持自定义定时**：前端可新增 / 编辑 / 删除 / 启停定时档。
- **真增量**：只拉新增的 bar，修复现有「整只股票跳过」的缺陷。
- **并发提速**：任务内（全 A 遍历类）并发拉取。
- **按优先级执行**：批量内任务按量化数据依赖排序，保证下游任务有上游数据。

## 2. 现状分析（带代码引用）

| 维度 | 现状 | 位置 |
|---|---|---|
| 调度器 | daemon 线程 + 60s 轮询 + 简易 cron 匹配，遍历 `sync_job_definitions` 逐个匹配 | `data_sync.py:2171` `_scheduler_loop` / `:2197` `_run_scheduled_jobs` / `:2234` `_cron_matches` |
| 单任务定时 | 24 个 `JobDefinition.schedule_cron` 分散在 8:30~23:00 | `data_sync.py:73-265` `DEFAULT_JOBS` |
| cron 覆盖 | `seed_default_registry` 每次启动用 `DEFAULT_JOBS.schedule_cron` **覆盖写回 DB** | `data_sync.py:1230` |
| 批量执行 | 已有 `start_sync_batch(profile)` → daemon 线程 → `_run_sync_batch` 串行 for 循环跑 job | `data_sync.py:1352` / `:1437` |
| 批量健壮性 | **一个 job 失败就整批 `return` 中止** | `data_sync.py:1493` |
| 任务内并发 | 日K / 分钟K 主循环**串行** `for stock_row`，一只一只拉 | `data_sync.py:469` / `:547` |
| 增量逻辑 | 日K `only_missing` = 「整只已同步 ≥80 根就跳过」→ **老股不再更新当日新 bar** | `data_sync.py:452-458` |
| 数据源能力 | `adapter.stock_bars` **已支持 `start_date/end_date`**，做真增量不难 | `akshare_adapter.py:461` |
| 前端定时 | **只读显示** `schedule_cron`，无配置 UI | `DataManagementPage.tsx:419` |
| 前端批量 | 「一键同步」`runAllSyncJobs({profile})` + `BatchProgress` 5s 轮询 | `dataSync.ts:35` / `DataManagementPage.tsx:299` |

数据时效硬约束（AkShare 公开源）：

- ✅ 14:00 盘中可取：实时行情快照、当日已走分钟线、资金流、热度、涨停池。
- ❌ 14:00 盘中不可取：当日完整日K（收盘后才更新）、龙虎榜（18:00 后）、财报（22:00 后）。

## 3. 需求决策（用户已确认）

1. **场景**：盘中尾盘选股 + 盘后研究，两者都要 → 两档定时。
2. **范围**：复用现有 core 批次思路，**全去掉** 24 个单任务 cron。
3. **默认档位**：`14:00` + `18:00`，支持自定义新增档。
4. **质量**：真增量 + 任务内并发 + 按优先级执行。

## 4. 架构设计：批量定时替换单任务定时

### 4.1 新增「批量定时」配置表 `sync_batch_schedules`

一条记录 = 一个定时档（一个 cron + 一组按优先级排序的任务）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | String(80) pk | 如 `intraday_14h` / `eod_18h` |
| `name` | String(120) | 如「盘中同步」「盘后同步」 |
| `cron` | String(80) | 如 `0 14 * * 1-5` |
| `job_ids` | JSONB | **有序**任务 id 列表，顺序即执行优先级 |
| `enabled` | Boolean | 启停 |
| `concurrency` | Integer | 任务内并发度，默认 8 |
| `last_status` / `last_started_at` / `last_finished_at` / `last_message` | — | 复用现有运行状态模式 |
| `created_at` / `updated_at` | — | 时间戳 |

默认 seed 两条（见 §5）。放在 `schema.py`，由 `ensure_sync_schema` 建表、`seed_default_registry` seed。

### 4.2 调度器改造

`_run_scheduled_jobs` 改为遍历 `sync_batch_schedules`（enabled 且有 cron），cron 匹配则触发批量，
**不再**遍历 `sync_job_definitions.schedule_cron`：

```text
for schedule in sync_batch_schedules(enabled, has cron):
    if _cron_matches(schedule.cron, now_china) and not _throttled(schedule):
        start_sync_batch(job_ids=schedule.job_ids, concurrency=schedule.concurrency,
                         source="schedule", schedule_id=schedule.id)
```

### 4.3 去掉单任务定时

`DEFAULT_JOBS` 里所有 `schedule_cron` 置 `None`（保留 job 定义本身，批量还要用）。
这样 `seed_default_registry` 不再写回单任务 cron，调度器也不再驱动单任务。
`update_job_schedule` API 保留（向前兼容，可做单任务手动定时），但默认不再使用。

### 4.4 `start_sync_batch` 扩展

现有签名 `start_sync_batch(profile="core")`。扩展为同时接受显式 `job_ids`：

```python
def start_sync_batch(profile="core", job_ids=None, params=None, concurrency=8,
                     source="manual", schedule_id=None): ...
```

- `job_ids` 非空时直接用它（来自 schedule），否则按 `profile` 取 `SYNC_BATCH_PROFILES`。
- `concurrency` 透传给 runner 的任务内并发。
- 复用现有 `_BATCH_LOCK`（防并发批量）、进度回调、`_SYNC_BATCHES` 内存状态、前端轮询。

## 5. 默认批量档位

任务优先级顺序遵循量化数据依赖（上游先跑）：

**🌅 `intraday_14h` — 14:00 盘中档**（cron `0 14 * * 1-5`，为尾盘选股服务，只跑 14:00 能拿到的）：

1. `sync_stock_list`（实时快照：最新价 / 涨跌幅 / 量比）
2. `sync_stock_minute_bars`（当日分钟K，截至 14:00）
3. `sync_stock_fund_flows`（个股资金流）
4. `sync_stock_hot_ranks`（个股热度）
5. `sync_limit_up_pools`（涨停池 / 跌停池）

**🌆 `eod_18h` — 18:00 盘后档**（cron `0 18 * * 1-5`，补完整数据）：

1. `sync_stock_list`（刷新收盘快照）
2. `sync_stock_daily_bars`（完整日K，真增量）
3. `sync_sector_list` → `sync_sector_members` → `sync_stock_sector_memberships`
4. `sync_sector_daily_bars` / `sync_sector_fund_flows` / `sync_sector_period_scores`
5. `sync_stock_lhb_records`（龙虎榜 18:00 后发布，**排靠后**给数据发布留时间）
6. `sync_stock_notices` / `sync_stock_financial_quarterly` / `sync_stock_financial_indicators` / `sync_stock_business_segments_history`（最晚，排末尾）

> 若财报 18:00 仍未发布，用户可**自定义加档**（如 22:00）只跑财报类 —— 这就是「支持自定义定时」的用途。

## 6. 执行模型：按优先级有序 + 任务内并发

两层提速，但保持简洁（KISS）：

- **任务间**：按 `job_ids` 顺序**串行**执行（保证数据依赖：先有股票清单才能拉 K 线）。
  - 不做「同阶段任务并发」——收益小且增加 DB 连接池 / 锁竞争复杂度（YAGNI，留作后续优化）。
- **任务内**：全 A 遍历类任务（日K / 分钟K / 资金流 / 热度）的 `for stock_row` 循环改为
  `ThreadPoolExecutor(concurrency)` 并发拉取。
  - 默认 `concurrency=8`（AkShare 公开源有限流，克制值，避免被封 IP），可配置。

提速预期：日K全A（~5000 只）从串行几十分钟 → 并发后接近 1/N 倍（受限于限流）。

## 7. 真增量策略（修复缺陷）

### 7.1 日K `_run_sync_stock_daily_bars`

- 现状：`only_missing` 跳过「已同步 ≥80 根」的整只股票 → 老股不更新当日新 bar。
- 改造：对每只需要同步的股票，查 `stock_daily_bars` 里该股票**最后一条 bar 的 trade_date**，
  带 `start_date = last_date + 1day` 调 `adapter.stock_bars(...)` 增量拉取（adapter 已支持）。
- 库里无记录的新股：拉默认 `limit`（如 250）历史。
- upsert 幂等，重复拉不脏数据。

### 7.2 分钟K `_run_sync_stock_minute_bars`

- 同理：查该股票该 interval 最后一条分钟 bar 的时间，之后增量。
- 保留现有 `mode=backtest_gap`（回测缺口补 14:30 尾盘快照）分支不动。

### 7.3 实现要点

- 新增查询 helper：`_last_bar_date(symbol, exchange, table, interval=None)`。
- 批量场景先一次性查出所有目标股票的 `last_bar_date`（一条 SQL `group by symbol having max(trade_date)`），
  避免逐只查询的开销。

## 8. 错误处理（修复「一败全停」）

### 8.1 失败隔离

- 现状：`_run_sync_batch` 一个 job 失败就 `_finish_batch(failed)` + `return`。
- 改造：单 job 失败**记录 failed、继续后续 job**，最后汇总 `succeeded/failed` 计数，
  批量终态用 `succeeded`（全成功）/ `partial`（有失败）/ `failed`（全失败）。
- 仅当「基础任务」（`sync_stock_list` / `sync_sector_list`）失败时，跳过依赖它的下游任务
  （标记 `skipped`，原因 `upstream_failed`）。简化判定：`sync_stock_list` 失败 → 跳过所有
  股票类下游（日K/分钟K/资金流/热度/龙虎榜/财报）；`sync_sector_list` 失败 → 跳过板块类下游
  （成分/反向索引/板块K线/资金流/评分）。用一个 `JOB_UPSTREAM` 映射（job_id → 依赖的基础任务）判定。

### 8.2 重试（可选，MVP 可先不做）

- 单 job 失败自动重试 N 次（默认 2），指数退避（30s / 2m）。
- 只重试可恢复错误（timeout / 502/503/504 / connection reset）；参数错误 / 解析失败不重试。

### 8.3 锁

- 复用现有 `_BATCH_LOCK`：批量运行中再触发（含调度触发）返回当前运行的 batch，不重复跑。

## 9. 前端 UI：自定义定时计划

`DataManagementPage.tsx`「同步管理」tab 新增**「定时计划」**区（在现有「一键同步」下方）：

- **列表**：每档显示 名称 / cron / 启停开关 / 任务数 / 上次状态 / 上次执行 / 下次触发。
- **新增 / 编辑**：表单输入 名称 + 时间 + 重复（周一~周五复选 → 自动生成 cron）+ 勾选任务（按档位预设，可自定义）+ 并发度；高级用户可手填 cron。
- **删除 / 启停**。
- 复用现有 `BatchProgress` 展示档触发的批量进度（5s 轮询）。
- 现有「一键同步」按钮保留（手动触发 core/all 批量），与定时计划并列。

## 10. API 契约（新增 / 修改）

```text
GET    /api/data-sync/schedules              列出批量定时
POST   /api/data-sync/schedules              新增
PATCH  /api/data-sync/schedules/{id}         编辑 / 启停
DELETE /api/data-sync/schedules/{id}         删除
POST   /api/data-sync/schedules/{id}/run     手动触发该档（调试用）
```

`POST /batches/run-all` 保留不变（手动 core/all）。

## 11. 数据库改动

- 新增表 `sync_batch_schedules`（§4.1），加进 `schema.py`，`ensure_sync_schema` 建表。
- `seed_default_registry`：seed 两条默认档；`DEFAULT_JOBS` 的 `schedule_cron` 全置 `None`。
- `sync_job_definitions` 表结构不变（`schedule_cron` 字段保留，默认空）。

## 12. 测试策略

- **调度器**：mock `datetime`，验证 cron 在 14:00 / 18:00 触发对应档、节流逻辑、enabled=false 不触发。
- **批量执行**：注入一个会失败的 fake runner，验证失败隔离（后续 job 继续）、`partial` 终态、上游失败跳过下游。
- **增量**：构造库里已有「最后 bar 日期」的股票，验证 `start_date` 续传；新股拉默认历史。
- **任务内并发**：mock adapter 计数并发调用数，验证受 `concurrency` 上限约束。
- **API**：schedules CRUD + run 端点。

## 13. 涉及文件清单

后端：

- `alphaagent/server/db/schema.py` — 新增 `sync_batch_schedules` 表。
- `alphaagent/server/services/data_sync.py` — `DEFAULT_JOBS` cron 清空；`start_sync_batch` 扩展 `job_ids/concurrency`；`_run_sync_batch` 失败隔离 + 优先级；`_run_scheduled_jobs` 改驱动批量；日K/分钟K 任务内并发 + 真增量；schedule CRUD helper；seed 默认两档。
- `alphaagent/server/api/data_sync.py` — 新增 schedules 端点。

前端：

- `frontend/src/api/dataSync.ts` — 新增 schedule CRUD 调用。
- `frontend/src/pages/DataManagementPage.tsx` — 新增「定时计划」区（列表 + 编辑表单）。
- 可能拆出 `frontend/src/components/ScheduleEditor.tsx`（若页面过长）。

## 14. 风险与默认决策

| 风险 / 决策 | 处理 |
|---|---|
| AkShare 公开源限流 / 封 IP | 任务内并发默认 **8**（克制），可配置；失败重试退避；记录 source 限速 |
| 龙虎榜 / 财报发布晚于档位 | 18:00 档把它们排在末尾；用户可自定义加更晚档 |
| 14:00 档拿不到当日日K | 日K只在 18:00 档跑；14:00 档用实时快照 + 当日分钟线服务尾盘选股 |
| 调度器单进程（无 Redis / worker） | 沿用现有 daemon 线程，KISS；API 进程重启时 `mark_interrupted_runs` 已处理中断态 |
| `seed_default_registry` 覆盖 | 把 `DEFAULT_JOBS.schedule_cron` 置空，从根上去掉单任务定时 |
| 并发写 DB 连接池 | 任务间串行，同一时刻只有一个 job 在写；任务内并发是 IO（等 AkShare），DB 写仍逐条 upsert |

## 15. 非目标（YAGNI）

- 不引入 Redis / Celery / 独立 worker 进程。
- 不做多数据源 fallback（保持单 AkShare 源；多源是早期蓝图的事）。
- 不做「同阶段任务并发」（任务间串行已够；任务内并发是主要提速点）。
- 不做 `data_freshness` SLA 表（现有 `last_*` 字段够用）。
- 不做 SSE 实时进度（保持 5s 轮询）。
