# Run And Debug

## API 性能基线（2026-07-20 优化后）

- 数据健康三接口曾 10s 级（4.5M 行全表 distinct 聚合），已根治：PK 等价 `count(*)`
  改写 + `ix_stock_daily_bars_date_symbol` 等 4 个索引 + `coverage()/data_health()`
  60s 进程内缓存（端点支持 `?force=1` 强刷）+ pg_class 行数估算 + source_status
  探测并行（TTL 300s）。稳态全部 <10ms，冷重算 <1s。
- 排障先查缓存是否生效，再 `EXPLAIN` 看是否走 `ix_stock_daily_bars_date_symbol`
  index-only scan。注意 `create_all` 不会给已存在的表补建索引，新索引必须加进
  `schema.py::_apply_compatible_schema_patches`。
- `/api/mainline-replay/sentiment-cycle` 不再在页面请求中扫描全市场日线。
  `sync_mainline_sentiment_history` 在股票/指数日线完成后预计算 250 个交易日曲线和盘中
  投影所需状态，持久化到 `mainline_sentiment_history`；接口只读取并切片，首个无缓存请求
  返回 `building`，前端每 3 秒重试。稳态实测历史/盘中读取约 `0.1-0.2s`。
- 盘中分钟线最高价和最新分钟时间必须由同一条“交易日 + 1m”聚合查询取得。不要重新加入
  单独的 `MAX(bar_time)`：当当天尚无分钟线时，它会沿时间索引跨日期倒扫数百万行。

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
- 已验证的性能风险：正式组合的 `/api/limit-up/history/backtest?lane=portfolio`
  与默认历史交割单都会进入 `get_scheduled_history_backtest()`。进程内报告缓存冷启动时，
  它会读取完整历史并补齐 C 质量证据；`history/status=ready` 只说明持久化历史账本可读，
  不代表该报告缓存已经就绪。若 API、PostgreSQL 或 worker 仍使用 Compose 的 `0.25`
  CPU 默认值，完整计算会超过网关 60 秒上限，网关返回 502，页面会在查询重试期间持续显示
  “A+B+C 回测载入中”。
- 正式组合报告的冷缓存处理已在本地代码实现、待版本化发版：
  `/api/limit-up/history/backtest?lane=portfolio` 和默认
  `/api/limit-up/history/ledger` 先返回 `202 {status: building}`，由 API 后台单飞构建报告；
  缓存就绪后返回原有 `200` 结构。前端仅在“回测”或“历史交割单”视图请求正式报告，
  每 3 秒轮询构建状态，并在报告就绪前不发出每日交割单并发请求。显式分赛道研究与内部
  同步 API 保持原有行为。
- 生产发布验收：正式 `.env` 设为 `ALPHAAGENT_ENV=production`，并根据已核验的 8 核
  主机设置 `ALPHAAGENT_API_CPUS=2`、`ALPHAAGENT_POSTGRES_CPUS=2`、
  `ALPHAAGENT_SCHEDULER_CPUS=0.5`。不要把提高网关超时作为替代方案；在非交易时段
  用版本化镜像重建服务后，应验证冷缓存立即 `202`、缓存就绪后 `200`，以及实时扫描
  心跳正常。

```bash
cd /opt/1panel/project/AlphaAgent
docker compose -f docker-compose.ghcr.yml ps
docker compose -f docker-compose.ghcr.yml config --images
```

## Local Limit-up Acceptance

### Current state

- 本地唯一正式质量合同为 `limit-up-core-abc-v2`；历史、实时触板、调度和现金账本同源。
  正式推荐输出全量合格信号；一仓/两仓只用于回测账户容量、费用和复利模拟。
- 行情日线已完整覆盖 `2023-03-28..2026-07-31` 的 811 个可靠交易日，最新截面
  `5522/5522`；正式历史账本仍重建到 `2026-07-30`，需再次显式重建才会纳入 7 月 31 日。
  盘中雷达帧不能替代日线账本。
- A+B+C v2 当前闭合 141 笔，`96/141=68.0851%`、平均 `+2.0608%`、独立信号复利
  `+662.3119%`、最大回撤 `-21.0357%`。两仓成交 95 笔、`69/95=72.6316%`、
  平均 `+2.3772%`、复利 `+189.2273%`、回撤 `-8.8668%`。自然前向从新 v2
  有效交易日起算，状态是
  `historical_proxy_pass_forward_unconfirmed`，不是实盘胜率承诺。
- C 每日最多一笔，且只允许在当天此前尚无 A/B 时进入；同秒按 A/C/B，跨时点按真实
  到达顺序。历史概念成员主要是幸存者代理，不能把 `46/72` 当作自然前向成绩。
- 未校准的数值触板概率、产品模型评分和冻结结算链保持移除。独立板前榜只展示
  `limit-up-core-abc-v2` 已触板就绪、lane 验证通过、无其他阻断且快照不超过 20 秒的股票；
  唯一允许缺少的正式条件是真实触板。板前榜不进入正式胜率、收益或账户统计。
- `>=3%` 只是雷达原始发现下限，不直接形成候选或买点。真实触板或回封后重新执行同一
  公共质量门，只有 `public_quality_actionable=true` 才升级正式 `buy_now`，炸板继续拦截。
- 实时炸板率和 D-1 弱势修复状态继续采集、展示并参与诊断/排序，但不再作为全市场
  一票否决；历史正式回测本来不读取这两道实时硬门。主板封板不足 5 只以及全部个股
  结构、动能、资金、财务、半年基因、A/B/C 质量和验证门仍保留。
- `2026-07-31` 保存帧反事实复核中，解除上述额外市场否决后有 4 只在触板前同时通过
  实时动能和公共质量：视觉中国 `10:59:27/9.319%`、日盈电子
  `11:10:27/9.994%`、腾龙股份 `11:20:34/8.782%`、锡业股份
  `14:28:16/8.678%`。前两只随后触板，后两只最高仅 `9.368%/9.504%`；板前榜是
  条件概率提示，不等于必然触板，也不进入正式触板回测成绩。
- 后端打板快扫为 10 秒、概念刷新约 30 秒、交易窗口调度心跳 2 秒；
  `/short-term` 活动时段实时快照为 10 秒，两日轨迹为 60 秒。
- 两日轨迹默认只查询 `LIVE_STRATEGY_VERSION`，且只有正式 `action=buy_now` 才形成
  `trigger_ready` 事件；旧合同和被质量门取消的研究动作不进入当前“买点曾触发”统计。
- 公共 `/api/limit-up/radar-validation` 和对应旧服务已经删除；它们不是当前模型、动作
  来源或产品合同。

### Ownership and safety

- 调度所有权在独立 `alphaagent-data-sync-worker`；API 不启动第二套调度器。
- 已知监控缺口（2026-07-30）：盘中 worker 重启或运行版本切换会让当天
  `limit_up_radar_frames` 出现多个采集运行指纹，`/healthz` 随即返回 503
  `current_day_radar_fingerprint_changed`，即使快扫心跳、新鲜度和快照写入都正常。
  排障时先核对 `limit_up_live_scan` 心跳与最新雷达帧；该告警目前不能单独判定数据阻塞。
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

2026-07-31 删除两道额外实时市场否决并完成代码收敛后，限涨停后端 `861 passed`、
同步调度 `167 passed`、前端 `142 passed`；编译、生产构建和 `git diff --check` 均通过。
Compose 默认只运行 API 与统一 data-sync worker；
`alphaagent-research` 仅在 `research` profile 中按需启动。

## Heavy Research Jobs

全历史研究必须使用独立的 `alphaagent-research` Compose 服务。该服务默认限制为
1 个 CPU，可用 `ALPHAAGENT_RESEARCH_CPUS` 调整；数值库单线程、单数据库连接，
并通过 `PGOPTIONS` 关闭 PostgreSQL 查询
并行；不得改用常驻 `alphaagent-api` 执行重放。

低吸成员与题材门禁：

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli membership-source-status
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format json
docker compose --profile research run --rm --no-deps -v "$PWD:/workspace" -w /workspace alphaagent-research python -m alphaagent.server.services.low_suction.cli theme-eligibility-research --start 2023-03-28 --end 2026-07-15 --format json
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
  A/B/C 质量门的买点。板前列表只允许“除真实触板外全部正式条件已齐”的新鲜候选。
- 旧 `/api/quant`、`/api/backtests`、`/api/portfolios` 和
  `/api/simulation` 返回 404。

网关对外 `/api/health` 可能要求登录；无凭据时以容器自身健康检查和
`docker compose ps` 为准。

## Scheduler Notes

- API 启动流程负责建表和调度注册；不要在健康 API 旁另起进程调用
  `ensure_sync_schema()`，否则会误判正在执行的任务为旧进程残留。
- `eod_1900` 负责主盘后采集，`eod_finalize_2130` 负责重试和打板历史重建，不包含
  板前冻结/结算。中断任务保留失败证据，由下一个合法时点补偿。
- `sync_limit_up_exit_minutes` 只保留为手动 14:30 研究；正式 `limit-up-core-abc-v2` 退出继续读取 D+1
  官方日线收盘。Tick/L2 和真实排队成交不能由夜间任务补造。

## Data Notes

- `ensure_schema_once()` 在 API 进程内只执行一次。
- `create_schema()` 先执行固定旧表清理，再创建保留 metadata。
- schedule registry 会删除旧 `tail_quant_1430`、`quant_research` 和
  `tail_preview` 行。
- 不在通过静态、后端、前端和打板指纹门禁前重建 API 容器。
