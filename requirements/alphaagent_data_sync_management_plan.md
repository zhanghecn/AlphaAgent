# AlphaAgent 数据同步管理模块执行计划

状态：可执行方案，待用户审查后进入实现。  
目标：把 A 股动态数据同步做成可视化、可配置、可追踪、可恢复的系统模块，而不是依赖人工命令或临时脚本。  
边界：本计划只覆盖数据源同步管理、任务调度、稳定性和接口/页面契约；不做选股、交易和推荐。

## 1. 用户目标

用户希望：

- 数据不要长期写死，板块、概念、成分股、新闻、公告、财报、主营构成都应尽量动态获取。
- 同步过程要有管理页面：
  - 能看到每个数据来源。
  - 能开启/关闭同步。
  - 能设置定时。
  - 能立即执行。
  - 能看到进度、成功/失败、最后更新时间。
- 系统要稳定：
  - 外部源失败不能拖垮 API。
  - 失败要能重试。
  - 数据要有来源、时间和质量状态。
  - 页面不能因为同步中断就变成假数据或空白。

## 2. 模块定位

新增一级模块：`数据同步管理`。

后端建议目录：

```text
alphaagent/
  server/api/data_sync.py
  services/data_sync/
    scheduler.py
    runner.py
    registry.py
    locks.py
    retry.py
    health.py
  data_sources/
    akshare_provider.py
    tushare_provider.py
    public_market.py
    eastmoney_provider.py
    cninfo_provider.py
  db/repositories/
    sync_jobs.py
    sync_sources.py
```

前端建议目录：

```text
frontend/src/pages/DataSyncPage.tsx
frontend/src/features/data-sync/
  SourceList.tsx
  SourceDetail.tsx
  ScheduleEditor.tsx
  JobRunTable.tsx
  JobLogPanel.tsx
```

导航新增：`数据同步`。

## 3. 同步对象

第一批同步对象按重要性分级。

### 3.1 P0 必须做

- 全 A 股票基础信息。
- 指数基础信息和行情。
- 全 A 最新行情快照。
- 股票日 K。
- 新浪/东方财富/同花顺板块和概念列表。
- 板块/概念成分股。
- 个股所属板块反向索引。

### 3.2 P1 其次做

- 个股新闻。
- 个股公告。
- 财报披露日历。
- 利润表、资产负债表、现金流量表。
- 财务指标。
- 主营业务构成和收入占比。

### 3.3 P2 后续增强

- 研报。
- 龙虎榜。
- 资金流。
- 股东户数。
- 机构持仓。
- 产业链自动发现和证据图谱。

## 4. 数据源管理

每个数据源定义为可管理对象。

字段：

- `source_id`：如 `sina_market_center`、`eastmoney_hsf10`、`akshare_em`、`tushare_pro`、`cninfo`。
- `name`：用户可读名称。
- `provider`：实现类。
- `data_domains`：支持的数据范围，如行情、板块、新闻、财报。
- `auth_type`：none/token/cookie。
- `enabled`：是否启用。
- `priority`：同类数据源优先级。
- `rate_limit_per_minute`：限速。
- `timeout_seconds`：超时。
- `retry_policy`：重试策略。
- `last_success_at`。
- `last_failure_at`。
- `last_error`。
- `health_status`：ready/degraded/down/disabled。

原则：

- 免费公开源默认启用，但必须有超时和限速。
- Tushare 等 Token 源可以配置但默认 disabled，直到用户提供 Token。
- 同类数据支持 fallback，例如个股详情先东财，失败走腾讯行情兜底。
- 任何数据必须记录 `source` 和 `updated_at`。

## 5. 同步任务模型

同步任务分两层：

- `sync_job_definition`：任务定义。
- `sync_job_run`：每次运行记录。

### 5.1 任务定义字段

- `job_id`
- `name`
- `data_domain`
- `source_id`
- `enabled`
- `schedule_type`：manual/interval/cron/market_calendar
- `cron_expr`
- `interval_seconds`
- `market_session_only`
- `depends_on`
- `timeout_seconds`
- `max_retries`
- `retry_backoff_seconds`
- `concurrency_key`
- `params`

### 5.2 运行记录字段

- `run_id`
- `job_id`
- `trigger_type`：manual/schedule/dependency/retry
- `status`：queued/running/succeeded/failed/cancelled/partial
- `started_at`
- `finished_at`
- `duration_ms`
- `progress_current`
- `progress_total`
- `inserted_count`
- `updated_count`
- `skipped_count`
- `failed_count`
- `error_code`
- `error_message`
- `log_excerpt`

### 5.3 任务日志

保留结构化日志：

- `run_id`
- `level`
- `message`
- `context`
- `created_at`

前端只显示最近 N 条，完整日志可后续下载。

## 6. 调度与执行

建议使用 Redis + PostgreSQL 实现轻量任务队列，MVP 不引入复杂分布式系统。

Compose 新增：

```text
alphaagent-worker     执行同步任务
alphaagent-scheduler  负责定时入队
```

如果先简化，也可以一个 `alphaagent-worker` 同时做 scheduler 和 runner，但 API 进程不能负责长任务。

执行原则：

- API 只创建任务、查询状态，不直接执行长任务。
- Worker 执行任务并写 PostgreSQL。
- Redis 保存队列、锁和短期任务状态。
- PostgreSQL 保存任务定义、运行历史和最终数据。

## 7. 稳定性设计

### 7.1 超时

所有外部请求必须设置 timeout。

默认：

- 行情/板块：8-15 秒。
- 财报/公告：20-30 秒。
- 批量同步单任务：按任务粒度设置总 timeout。

### 7.2 限速

每个 source 单独限速，避免被封。

示例：

- 新浪行情：并发低、分页拉取。
- 东方财富 HSF10：低并发，个股级请求必须排队。
- AKShare：视底层接口设置保守限速。
- Tushare：按积分和频率限制执行。

### 7.3 重试

只重试可恢复错误：

- timeout
- 502/503/504
- connection reset

不重试：

- 参数错误
- Token 无效
- 权限不足
- 数据结构解析失败但已确认接口变更

重试策略：

- 指数退避：30s、2m、10m。
- 最多 3 次。
- 失败后标记 source/job degraded。

### 7.4 幂等

所有同步任务必须幂等。

规则：

- 使用唯一键 upsert。
- 同一天同一股票同一数据源重复同步不会生成重复数据。
- 每次运行记录可重复，但业务数据不能重复。

### 7.5 锁

相同任务不允许并发跑。

锁 key：

```text
sync:{job_id}:{date_or_scope}
```

锁存在时：

- 手动触发返回已有 run_id。
- 或提示“已有任务运行中”。

### 7.6 部分成功

大批量同步不能因为一只股票失败而整体失败。

状态：

- 全部成功：succeeded。
- 有失败但有数据更新：partial。
- 全部失败：failed。

前端要能看到失败列表。

### 7.7 数据新鲜度

每类数据定义 freshness SLA：

- 最新行情：交易时间内 1-5 分钟。
- 板块成分：每日。
- 新闻：10-30 分钟。
- 公告：30-60 分钟。
- 财报：每日或财报季更频繁。
- 主营构成：财报发布后更新。

API 返回数据时应附带：

- `source`
- `updated_at`
- `freshness_status`：fresh/stale/missing

## 8. 管理页面设计

页面：`/data-sync`

### 8.1 总览

显示：

- 数据源健康状态。
- 今日任务成功/失败/运行中数量。
- 最近失败任务。
- 数据新鲜度红黄绿状态。

### 8.2 数据源列表

列：

- 来源名称。
- 支持数据。
- 状态。
- 是否启用。
- 优先级。
- 最后成功。
- 最后失败。
- 操作：测试连接、启用/停用、编辑配置。

### 8.3 同步任务列表

列：

- 任务名。
- 数据范围。
- 来源。
- 定时策略。
- 启用状态。
- 最近运行状态。
- 最近耗时。
- 最近更新数量。
- 操作：立即执行、暂停、编辑定时、查看日志。

### 8.4 任务详情

显示：

- 最近运行历史。
- 进度。
- 失败样本。
- 日志。
- 参数。
- 数据写入统计。

### 8.5 立即执行

点击立即执行时：

- 弹出确认。
- 可选择范围：
  - 全量。
  - 增量。
  - 指定股票。
  - 指定板块。
  - 指定日期范围。
- 创建 `sync_job_run`。
- 返回 run_id。
- 页面轮询进度，后续可改 SSE。

### 8.6 定时设置

支持：

- 每隔 N 分钟。
- 每日某时。
- 交易日收盘后。
- 财报季每日。
- 自定义 cron。

初期不需要做复杂 cron 编辑器，可以用表单生成 cron。

## 9. 后端 API 契约

新增：

```text
GET  /api/data-sync/sources
GET  /api/data-sync/sources/{source_id}
POST /api/data-sync/sources/{source_id}/test
PATCH /api/data-sync/sources/{source_id}

GET  /api/data-sync/jobs
GET  /api/data-sync/jobs/{job_id}
PATCH /api/data-sync/jobs/{job_id}
POST /api/data-sync/jobs/{job_id}/run

GET  /api/data-sync/runs
GET  /api/data-sync/runs/{run_id}
POST /api/data-sync/runs/{run_id}/cancel
GET  /api/data-sync/runs/{run_id}/logs

GET  /api/data-sync/freshness
```

### 9.1 立即执行响应

```json
{
  "run_id": "run_20260607_001",
  "job_id": "sync_sector_members",
  "status": "queued"
}
```

### 9.2 运行状态响应

```json
{
  "run_id": "run_20260607_001",
  "job_id": "sync_sector_members",
  "status": "running",
  "progress_current": 42,
  "progress_total": 100,
  "inserted_count": 120,
  "updated_count": 380,
  "failed_count": 2,
  "started_at": "2026-06-07T15:00:00+08:00",
  "source": "sina_market_center"
}
```

## 10. 数据库表

新增系统表：

```text
sync_sources
sync_job_definitions
sync_job_runs
sync_job_logs
data_freshness
```

后续业务数据表：

```text
stocks
stock_quotes
stock_bars
sectors
sector_members
stock_sector_memberships
stock_news
stock_announcements
financial_statements
financial_indicators
business_segments
industry_chain_nodes
industry_chain_edges
chain_evidence
```

## 11. 首批默认任务

MVP 默认内置这些任务定义：

| job_id | 名称 | 来源 | 定时 |
|---|---|---|---|
| sync_a_share_stocks | 全 A 股票基础信息 | sina/akshare | 每日 08:30 |
| sync_market_quotes | 全 A 最新行情 | sina/tencent | 交易时间每 1-5 分钟 |
| sync_daily_bars | 日 K 增量 | sina/eastmoney | 每日 17:30 |
| sync_sector_nodes | 板块/概念列表 | sina/akshare | 每日 08:45 |
| sync_sector_members | 板块/概念成分股 | sina/akshare | 每日 09:00、15:30 |
| sync_stock_news | 个股新闻 | eastmoney/akshare | 每 30 分钟 |
| sync_announcements | 公告 | cninfo/akshare | 每 60 分钟 |
| sync_financials | 财报和财务指标 | tushare/akshare | 每日 19:00 |
| rebuild_stock_sector_index | 股票-板块反向索引 | local_db | 板块同步后 |
| rebuild_industry_chain_graph | 产业链证据图谱 | local_db | 每日 20:30 |

## 12. 实施顺序

### 阶段 A：同步管理骨架

- 建表：sources/jobs/runs/logs/freshness。
- 实现 job registry。
- 实现手动 run。
- 实现 worker。
- 实现任务状态查询。
- 前端做 `/data-sync` 总览、任务列表、立即执行。

验收：

- 能从页面点击执行 `sync_sector_nodes`。
- 能看到 queued/running/succeeded。
- 能看到 inserted/updated 数量。

### 阶段 B：动态板块和成分股落库

- 同步板块/概念列表。
- 同步板块成分股。
- 建股票-板块反向索引。
- 板块页优先读本地库。
- 外部源只作为同步任务使用，不再由页面实时打外部接口。

验收：

- 能查询“亨通光电属于哪些板块”。
- 能看到光纤光缆全量成分股和最后同步时间。

### 阶段 C：新闻、公告、财报

- 同步个股新闻。
- 同步公告。
- 同步财报和财务指标。
- 个股详情页增加新闻、公告、财报模块。

验收：

- 进入个股详情能看到最近新闻、公告、财务指标。
- 每条数据有 source 和 updated_at。

### 阶段 D：动态产业链

- 用板块共现、主营构成、新闻公告关键词生成产业链证据。
- 产业链规则降级为 seed/兜底。
- 页面显示 evidence 和 confidence。

验收：

- 搜 CPO/PCB/光纤无需手工补规则。
- 每个产业链节点能展开证据来源。

## 13. 风险

- 免费公开源接口不稳定，必须有缓存、落库、重试和降级。
- Tushare 需要 Token 和积分，不能默认假设可用。
- 新闻/公告/财报数据量大，需要分批同步和限速。
- 产业链自动生成存在误判，需要 evidence 和 confidence，不能只给结论。
- 行情实时性依赖公开源，不等同于交易级实时行情。

## 14. 当前结论

同步管理模块必须做，而且应该早做。  
下一步建议先实现阶段 A 和 B：让板块/概念/成分股从“实时外部拉取”变成“可管理同步 + 本地库优先读取”，这样页面稳定性会明显提升，也能解决“是不是全量、最后什么时候更新、失败了为什么”的问题。
