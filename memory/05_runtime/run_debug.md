# Run And Debug

## API 性能基线（2026-07-20 优化后）

- 数据健康三接口曾 10s 级（4.5M 行全表 distinct 聚合），已根治：PK 等价 `count(*)`
  改写 + `ix_stock_daily_bars_date_symbol` 等 4 个索引 + `coverage()/data_health()`
  60s 进程内缓存（端点支持 `?force=1` 强刷）+ pg_class 行数估算 + source_status
  探测并行（TTL 300s）。稳态全部 <10ms，冷重算 <1s。
- 排障先查缓存是否生效，再 `EXPLAIN` 看是否走 `ix_stock_daily_bars_date_symbol`
  index-only scan。注意 `create_all` 不会给已存在的表补建索引，新索引必须加进
  `schema.py::_apply_compatible_schema_patches`。
- 遗留：`/api/mainline-replay/sentiment-cycle` 冷 ~3.2s（75 天窗口函数 CTE），
  根治需物化日指标表；300s 响应缓存兜底。

## Local Development

首选入口：

```bash
docker compose up --build
```

Web：`http://localhost:8080`。API 由网关代理到 `/api/*`。

只启动业务服务：

```bash
docker compose up -d --build alphaagent-api alphaagent-web
docker compose ps
```

vn.py 官方桌面入口仍是：

```bash
uv run python examples/veighna_trader/run.py
```

当前 launcher 只有 CTP，不代表已具备 A 股实盘 Gateway。

## Production

- 服务器本地目录部署使用 `deploy/docker-compose.local.yml`；GHCR 发布由 `v*`
  标签工作流生成 API/Web 镜像。
- 远端当前镜像和运行状态必须在目标主机现场核验；不再保留过期镜像哈希、批次 ID
  或旧策略版本作为当前事实。

```bash
cd /opt/1panel/project/AlphaAgent
docker compose -f docker-compose.ghcr.yml ps
docker compose -f docker-compose.ghcr.yml config --images
```

## Local Limit-up Acceptance

### Current state

- 本地唯一正式质量合同为 `limit-up-core-abc-v2`；历史、实时触板、调度和现金账本同源。
  正式推荐输出全量合格信号；一仓/两仓只用于回测账户容量、费用和复利模拟。
- 本地运行数据已自然推进到 `2026-07-24` 的 806 个可靠交易日。
- A+B+C v2 当前闭合 140 笔，`97/140=69.2857%`、平均 `+2.1478%`、独立信号复利
  `+742.9976%`、最大回撤 `-21.0357%`。A 为 `35/41=85.3659%`，C 为
  `44/69=63.7681%`，B 为 `18/30=60%`。严格单仓成交 79 笔、复利 `+376.6561%`；
  两仓成交 95 笔、复利 `+201.9840%`。自然前向从新 v2 有效交易日起算，状态是
  `historical_proxy_pass_forward_unconfirmed`，不是实盘胜率承诺。
- C 每日最多一笔，且只允许在当天此前尚无 A/B 时进入；同秒按 A/C/B，跨时点按真实
  到达顺序。历史概念成员主要是幸存者代理，不能把 `46/72` 当作自然前向成绩。
- 板前概率、提前推荐、独立观察池、模型评分和冻结结算链已经移除。真实触板或回封后才
  执行 `limit-up-core-abc-v2`；完整质量门通过时 `near_limit/sealed/resealed` 可形成
  `buy_now`，`failed` 炸板继续拦截。
- `>=3%` 雷达只保存原始行情、概念、资金和历史点时字段，不评分、不生成推荐、不进入页面
  买点，也不进入正式胜率、收益或账户统计。
- 后端打板快扫为 10 秒、概念刷新约 30 秒、交易窗口调度心跳 2 秒；
  `/short-term` 活动时段实时快照为 10 秒，两日轨迹为 60 秒。
- 两日轨迹默认只查询 `LIVE_STRATEGY_VERSION`，且只有正式 `action=buy_now` 才形成
  `trigger_ready` 事件；旧合同和被质量门取消的研究动作不进入当前“买点曾触发”统计。
- 公共 `/api/limit-up/radar-validation` 和对应旧服务已经删除；它们不是当前模型、动作
  来源或产品合同。

### Ownership and safety

- 调度所有权在独立 `alphaagent-data-sync-worker`；API 不启动第二套调度器。
- 市场、行业/概念、个股资金和历史点时快照保留为原始研究证据，不得用日终值补造盘中
  正式质量条件。
- 正式推荐只读取 `limit-up-core-abc-v2`。旧 A+B、v15/v9/v5 和未获准的研究观察不得
  作为兼容回退或写入当前 `actionable_recommendations`。

## Focused Verification

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py
uv run --group server pytest -q tests/alphaagent/test_data_sync_schedule.py
uv run python -m compileall -q alphaagent/server/services/limit_up
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
```

2026-07-28 删除提前推荐子系统后验收：打板后端 `780 passed`、同步调度 `160 passed`，
前端 `142 passed`；compileall、生产构建和 `git diff --check` 均通过。Compose 默认只运行
API 与统一 data-sync worker；`alphaagent-research` 仅在 `research` profile 中按需启动。

## Heavy Research Jobs

全历史研究必须使用独立的 `alphaagent-research` Compose 服务。该服务默认限制为
1 个 CPU，可用 `ALPHAAGENT_RESEARCH_CPUS` 调整；数值库单线程、单数据库连接，
并通过 `PGOPTIONS` 关闭 PostgreSQL 查询
并行；不得改用常驻 `alphaagent-api` 执行重放。

低吸成员与题材门禁：

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli membership-source-status
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format json
docker compose run --rm --no-deps -v "$PWD:/workspace" -w /workspace alphaagent-research python -m alphaagent.server.services.low_suction.cli theme-eligibility-research --start 2023-03-28 --end 2026-07-15 --format json
```

## Runtime Checks

```bash
curl -fsS http://localhost:8080/api/health
curl -fsS http://localhost:8080/api/limit-up/history/status
curl -fsS http://localhost:8080/api/limit-up/live
curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:8080/api/limit-up/radar-validation
docker compose ps
docker compose logs --tail=100 \
  alphaagent-api alphaagent-data-sync-worker
```

验收时必须看到：

- API、Web、PostgreSQL、Redis 和 data-sync worker 正常运行，无循环 import 或缺失模块；
  Compose 中不存在独立提前推荐轮询服务。
- 正式历史、实时、调度和现金账本统一声明 `limit-up-core-abc-v2`，不存在其他合同入口。
- 根 Compose 本地开发默认启用 `ALPHAAGENT_STARTUP_BACKTEST_WARMUP=true`。首次全量回测
  尚未进入进程缓存时，`/short-term` 必须显示“A+B+C 回测载入中”并自动刷新，
  不得显示空白内容区。
- 已删除的 `/api/limit-up/radar-validation` 返回 404。
- 活动交易时段实时快照轮询为 10 秒，轨迹为 60 秒；正式列表只有真实触板或回封后通过
  A/B/C 质量门的买点。
- 旧 `/api/quant`、`/api/backtests`、`/api/portfolios` 和
  `/api/simulation` 返回 404。

网关对外 `/api/health` 可能要求登录；无凭据时以容器自身健康检查和
`docker compose ps` 为准。

## Scheduler Notes

- API 启动流程负责建表和调度注册；不要在健康 API 旁另起进程调用
  `ensure_sync_schema()`，否则会误判正在执行的任务为旧进程残留。
- `eod_1900` 负责主盘后采集，`eod_finalize_2130` 负责重试、打板历史重建和唯一
  板前冻结/结算。中断任务保留失败证据，由下一个合法时点补偿。
- `sync_limit_up_exit_minutes` 只保留为手动 14:30 研究；正式 `limit-up-core-abc-v2` 退出继续读取 D+1
  官方日线收盘。Tick/L2 和真实排队成交不能由夜间任务补造。

## Data Notes

- `ensure_schema_once()` 在 API 进程内只执行一次。
- `create_schema()` 先执行固定旧表清理，再创建保留 metadata。
- schedule registry 会删除旧 `tail_quant_1430`、`quant_research` 和
  `tail_preview` 行。
- 不在通过静态、后端、前端和打板指纹门禁前重建 API 容器。
