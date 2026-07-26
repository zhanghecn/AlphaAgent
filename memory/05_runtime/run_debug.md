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

- 本地唯一正式合同为 `limit-up-core-ab-v1`；历史、实时、调度和现金账本同源且无旧规则
  回退。首板、二进三、两仓、正式费用和 D+1 官方收盘退出保持不变。
- 本地运行数据已自然推进到 `2026-07-24` 的 806 个可靠交易日；板前模型最终报告继续
  固定使用 802 日输入，不因新增交易日重选模型或阈值。
- A+B 当前历史闭合 78 笔，胜率 `56/78=71.7949%`、平均 `+2.2512%`、最大回撤
  `-14.5416%`；A 为 `35/41=85.3659%`，B 为 `21/37=56.7568%`。最近 24 笔旧快照
  反事实只有 50%，所以状态是 `historical_pass_forward_not_passed`，不是实盘胜率承诺。
- 唯一板前合同为 `limit-up-preboard-decision-v1`。概率资格为 `ready`，历史晋级为
  `historical_rejected`，执行模式为 `research_only`，正式激活为 `not_eligible`；模型指纹
  为 `sha256:b1d4ca83ca4dad25e1e74cda21c5b01c4f40d6e62ed9da62582d6eb8c651b71a`。
- 双概率排序有效，但严格 C 首板账户只有 27 笔、51.85% 胜率、`+6.10%` 复利和
  `-14.58%` 回撤，未通过相对 A 基线的冻结账户门。当前 D+1 优先与纯触板概率排序的
  validation 结果完全相同；综合机会价值因 fit 触板未封仅 4 笔而不可评估。实时只展示
  `preboard_candidates` 概率观察，不写 action、不占两仓、不改正式买点。
- `>=3%` 只对已通过正式同源高质量门的首板启动观察，不是全市场母池、训练分母或
  买点。普通 3% 股票不得进入模型、页面推荐或两仓。
- 新板前 `preboard_candidates` 必须严格低于涨停价；已触板或
  `sealed/resealed/failed` 后退出板前观察。正式 A+B 扫板链是独立口径：质量和执行门
  通过时，`near_limit/sealed/resealed` 仍可为 `buy_now`，页面必须显示涨停价排队买点；
  `failed` 炸板继续拦截。
- 后端打板快扫为 10 秒、概念刷新约 30 秒、交易窗口调度心跳 2 秒；
  `/short-term` 活动时段实时快照为 10 秒，两日轨迹为 60 秒。
- 公共 `/api/limit-up/radar-validation` 和对应旧服务已经删除；它们不是当前模型、动作
  来源或产品合同。

### Ownership and safety

- 调度所有权在独立 `alphaagent-data-sync-worker`；API 不启动第二套调度器。
- 板前日级冻结和结算由 21:30 的 `sync_limit_up_preboard_decision` 唯一负责；不保留
  第二个板前轮询容器。`research_only` 动作数必须为 0。
- 市场、行业/概念、个股资金、当前换手、报价和快照新鲜度无法按
  `known_at <= decision_at` 重建时统一保留为 `diagnostic/non-blocking`，不得用日终值补造
  或作为实时独有硬门。共享风险、窗口、完整分钟和严格板前价格继续 fail closed。
- 正式推荐只读取 `limit-up-core-ab-v1`。研究观察不得写入正式
  `actionable_recommendations`，也不得作为 C 级扩容或旧规则回退。
- 正式切换必须同时满足数据库 `forward_pass_for_formal` 和环境变量
  `ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT` 精确匹配；切换只原子替换首板动作和
  两仓，二进三不变。

## Focused Verification

```bash
uv run --group server pytest -q tests/alphaagent/test_limit_up_*.py
uv run --group server pytest -q tests/alphaagent/test_data_sync_schedule.py
uv run python -m compileall -q alphaagent/server/services/limit_up
npm --prefix frontend test -- --run
npm --prefix frontend run build
git diff --check
```

2026-07-26 当前源码验收：打板后端 `924 passed`，前端 `144 passed`；compileall、前端
生产构建、`docker compose config --quiet` 和 `git diff --check` 均通过。Compose 只保留
API 与统一 data-sync worker，旧独立板前 worker 已删除；数据库只有 1 个当前
`active / ready / historical_rejected` 板前模型。`/short-term` 回测显示 A+B 全量
`78/78`、胜率 `71.79%`、平均 `2.25%`；冷缓存期间显示明确载入状态，不再出现空白区。

## Heavy Research Jobs

全历史研究必须使用独立的 `alphaagent-research` Compose 服务。该服务固定为
`0.10 CPU`、数值库单线程、单数据库连接，并通过 `PGOPTIONS` 关闭 PostgreSQL 查询
并行；不得改用常驻 `alphaagent-api` 执行重放。

唯一板前冻结回放命令：

```bash
docker compose --profile research run --rm -T --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  -e PYTHONPATH=/workspace:/app/third_party/akshare \
  alphaagent-research python -m \
  alphaagent.server.services.limit_up.preboard_decision_replay \
  --sessions 89 \
  --end-date 2026-07-20 \
  --json-output /tmp/limit_up_preboard_decision_validation_20260723.json \
  --markdown-output memory/06_backtests/limit_up_preboard_decision_validation_20260723.md
```

完成后必须核对数据/候选索引/模型指纹、44/15/30 日期切分和唯一终止状态；
当前概率资格为 `ready`、最终状态为 `historical_rejected`，所以必须运行并核对严格 A/C
账户，但执行模式只能是 `research_only`。任何指纹变化先定位，不得静默覆盖报告或在
validation 上重新调参。当前完整回放耗时 `2259.389s`、峰值 RSS `6925.750 MiB`；固定
内存中止门已删除，只保留实际峰值审计。

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

- API、Web、PostgreSQL、Redis 和 data-sync worker 正常运行，无循环 import、旧模型加载
  或缺失模型回退；Compose 中不存在独立板前轮询服务。
- 正式历史、实时、调度和现金账本统一声明 `limit-up-core-ab-v1`，无旧版本回退；
  板前状态为
  `ready / historical_rejected / research_only / not_eligible`。
- 根 Compose 本地开发默认启用 `ALPHAAGENT_STARTUP_BACKTEST_WARMUP=true`。首次全量回测
  尚未进入进程缓存时，`/short-term` 必须显示“A+B 回测载入中”并自动刷新，
  不得显示空白内容区。
- research/shadow/formal 动作均为 0，`formal_strategy_changed=false`。
- 已删除的 `/api/limit-up/radar-validation` 返回 404。
- 已触板首板不出现在板前当前买点；活动交易时段实时快照轮询为 10 秒，轨迹为 60 秒。
- 旧 `/api/quant`、`/api/backtests`、`/api/portfolios` 和
  `/api/simulation` 返回 404。

网关对外 `/api/health` 可能要求登录；无凭据时以容器自身健康检查和
`docker compose ps` 为准。

## Scheduler Notes

- API 启动流程负责建表和调度注册；不要在健康 API 旁另起进程调用
  `ensure_sync_schema()`，否则会误判正在执行的任务为旧进程残留。
- `eod_1900` 负责主盘后采集，`eod_finalize_2130` 负责重试、打板历史重建和唯一
  板前冻结/结算。中断任务保留失败证据，由下一个合法时点补偿。
- `sync_limit_up_exit_minutes` 只保留为手动 14:30 研究；正式 `limit-up-core-ab-v1` 退出继续读取 D+1
  官方日线收盘。Tick/L2 和真实排队成交不能由夜间任务补造。

## Data Notes

- `ensure_schema_once()` 在 API 进程内只执行一次。
- `create_schema()` 先执行固定旧表清理，再创建保留 metadata。
- schedule registry 会删除旧 `tail_quant_1430`、`quant_research` 和
  `tail_preview` 行。
- 不在通过静态、后端、前端和打板指纹门禁前重建 API 容器。
