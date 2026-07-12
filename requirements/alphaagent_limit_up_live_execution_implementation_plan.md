# AlphaAgent 实时打板操作台实施计划

> **执行方式：** 当前会话使用 `executing-plans` 逐项实现。按仓库约束不执行 `git commit`。

**目标：** 在现有 `/limit-up` 页面实现可持久化的实时三通道推荐、历史时点复现和按买点回测。

**架构：** `stock_events` 保留日终事实；新增追加式信号快照表。纯函数策略引擎将实时候选转换为动态 Top5 和三个操作通道；实时服务负责采集、补充数据库上下文并持久化；旧日期由日终事件生成明确标记的代理视图。

**技术栈：** FastAPI、SQLAlchemy/PostgreSQL JSONB、React/TypeScript、TanStack Query、Vitest、pytest、Playwright。

**状态：** 2026-07-11 已实现并完成测试、构建、容器和真实接口验证；交易时段外或行情日期过期的扫描只读且不落库。

---

### 任务 1：信号领域模型与纯函数策略

**文件：**

- 新建：`alphaagent/server/services/limit_up/live_policy.py`
- 测试：`tests/alphaagent/test_limit_up_live.py`

- [x] 先写失败测试，覆盖交易阶段、动态 Top5 替换、主板过滤、三个通道、过期金银手指不计分。
- [x] 运行 `uv run pytest tests/alphaagent/test_limit_up_live.py -q`，确认因模块缺失而失败。
- [x] 实现 `session_stage()`、`rank_live_candidates()`、`build_live_recommendations()`。
- [x] 使用固定动作 `buy_now/wait_tail/next_auction/pass` 和固定通道 `now/tail/next_auction`。
- [x] 再次运行测试，确认纯函数测试通过。

核心接口：

```python
def build_live_recommendations(
    candidates: list[dict[str, object]],
    market_context: Mapping[str, object],
    captured_at: datetime,
    previous_snapshot: Mapping[str, object] | None = None,
) -> dict[str, object]: ...
```

### 任务 2：追加式快照表和仓储

**文件：**

- 修改：`alphaagent/server/db/schema.py`
- 新建：`alphaagent/server/services/limit_up/live_repository.py`
- 测试：`tests/alphaagent/test_limit_up_live.py`

- [x] 增加 `limit_up_signal_snapshots` 表和日期/时间索引。
- [x] 写仓储测试，验证同一分钟和策略版本幂等更新、不同时点追加、`as_of` 查询不读取未来快照。
- [x] 实现 `save_snapshot()`、`load_latest_snapshot()`、`load_snapshot_as_of()`、`list_snapshot_dates()`。
- [x] 调用现有 `ensure_schema()` 创建表，不引入独立迁移框架。

表的唯一键：

```text
(trade_date, captured_minute, strategy_version)
```

### 任务 3：实时采集和候选构建

**文件：**

- 新建：`alphaagent/server/services/limit_up/live_service.py`
- 修改：`alphaagent/data_sources/akshare_adapter.py`
- 测试：`tests/alphaagent/test_limit_up_live.py`

- [x] 测试实时涨幅榜、涨停池、炸板池合并后保留主板非 ST，且字段带来源时间。
- [x] 将当日涨停池缓存缩短到 20 秒，历史日期仍使用 600 秒。
- [x] 从涨幅榜发现 `near_limit`，从涨停/炸板池构建 `first_touch/resealed_n/failed`。
- [x] 查询候选当前板块成员关系、D-1 板块评分/资金和个股资金，生成板块龙位。
- [x] 计算实时封板数、炸板数、炸板率和相对上一快照的变化。
- [x] 调用领域策略，保存完整候选和推荐快照。
- [x] 数据源失败时返回最近成功快照并标记 `stale`，不能返回空白伪实时结果。

### 任务 4：实时和历史信号 API

**文件：**

- 修改：`alphaagent/server/api/limit_up.py`
- 修改：`alphaagent/server/services/limit_up/service.py`
- 修改：`alphaagent/server/services/limit_up/repository.py`
- 测试：`tests/alphaagent/test_limit_up_live.py`

- [x] 添加 `GET /limit-up/live`、`POST /limit-up/live/refresh`、`GET /limit-up/signals`。
- [x] `signals` 优先读取严格快照；旧日期使用现有 dashboard 生成 `historical_proxy` 三通道。
- [x] `dates` 合并快照日期和事件日期。
- [x] 修复历史动态 Top5：每个时点都返回当时最新 Top5，不再在最早五只后停止。
- [x] API 测试覆盖日期、`as_of`、严格/代理模式和错误响应。

### 任务 5：盘中定时快照

**文件：**

- 修改：`alphaagent/server/services/data_sync.py`
- 测试：`tests/alphaagent/test_data_sync_schedule.py`

- [x] 增加 `limit_up_live_scan` 计划，交易日 09:20-11:30、13:00-14:57 每分钟触发轻量快照动作。
- [x] 定时动作复用实时刷新服务，不把快照写回覆盖式 `stock_events`。
- [x] 保留 19:00 `sync_limit_up_pools` 作为日终事实同步。
- [x] 测试默认计划、交易时段守卫和异常恢复。

### 任务 6：按买点回测

**文件：**

- 新建：`alphaagent/server/services/limit_up/entry_backtest.py`
- 修改：`alphaagent/server/api/limit_up.py`
- 修改：`alphaagent/server/services/limit_up/service.py`
- 测试：`tests/alphaagent/test_limit_up_live.py`

- [x] 增加 `entry_mode=auction/sweep/tail/next_auction`。
- [x] 严格快照日期只回测当时保存的 `buy_now/next_auction` 信号。
- [x] 旧日期分别实现日终代理，并在结果标记 `historical_proxy`。
- [x] 正确对齐四种入场和 D、D+1、D+2 退出日期。
- [x] 返回胜率、平均收益、复利、最大回撤、硬亏损率、封板率、成交可信度和逐笔交易。
- [x] 保持旧 `exit_mode=next_open/next_close` 兼容。

### 任务 7：前端 API 和操作台

**文件：**

- 修改：`frontend/src/api/limitUp.ts`
- 新建：`frontend/src/features/limitUp/LiveActionDesk.tsx`
- 新建：`frontend/src/features/limitUp/LiveActionDesk.spec.tsx`
- 修改：`frontend/src/pages/LimitUpPage.tsx`

- [x] 定义实时快照、推荐、通道和买点回测类型。
- [x] 接入 `live/signals/refresh`，最新日期 15 秒轮询，历史日期按所选日期读取信号。
- [x] 第一屏实现“现在打 / 尾盘打 / 明早竞价”三列操作表，显示动作、触发价、龙位、板位、回封路径、预期结果和取消条件。
- [x] 顶部显示交易阶段、严格/代理状态、数据时间和刷新按钮。
- [x] 回测区增加买点分段控件并展示对应摘要与逐笔记录。
- [x] 复用现有股票链接、颜色、按钮和表格，不创建营销式卡片或嵌套卡片。

### 任务 8：完整验证和运行

**文件：**

- 更新：`memory/03_data/data_flow.md`
- 更新：`memory/05_runtime/run_debug.md`
- 更新：`memory/06_backtests/limit_up_short_term_factor_research.md`

- [x] 运行 `uv run pytest tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_mvp.py tests/alphaagent/test_data_sync_schedule.py -q`。
- [x] 运行 `pnpm --dir frontend test -- --run frontend/src/features/limitUp/LiveActionDesk.spec.tsx`。
- [x] 运行 `pnpm --dir frontend run build`。
- [x] 重建 `alphaagent-api` 和 `alphaagent-web`，确认网关健康。
- [x] 在桌面和 390x844 手机视口检查 `/limit-up`，确认无重叠、无空白、控制台无错误。
- [x] 调用实时和历史 API，核对数据时间、三个通道、日期复现及四种回测日期对齐。
