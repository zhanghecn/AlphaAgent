# Run And Debug

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

- 正式入口：`http://agu.yantiandao.com`；数据管理页为 `/data`，短线研究页为
  `/short-term`，旧 `/limit-up` 会跳转到 `/short-term`。
- 远端正式环境当前仍是历史 v6 验收 API：`v2.5.20-exit1430.20260716`；Web、Gateway 仍为
  `v2.5.19-autosync.20260716`。正式根目录 `/opt/1panel/project/AlphaAgent` 的
  `docker-compose.ghcr.yml` 已固定本地镜像并设置 `pull_policy: never`，避免 GHCR
  `latest` 回退；本地 v9 尚未发布到该远端环境。
- 当前版本不是 GHCR 发布物。下一次正式发版必须先替换固定镜像标签和 pull policy；
  在此之前不要把页面“一键更新”当成可升级到新版本的路径。
- 正式 PostgreSQL 发布前备份：
  `backups/pre-autosync-20260716T0945Z.dump`；Compose 发布前配置备份：
  `backups/docker-compose.ghcr.pre-exit1430-20260716T142521.yml`，SHA-256 为
  `73d7dd98c15b626d1bfd25a08d56b35b01189a3f4cff8b65ed61af5ac7ce8886`。
- v6 增量复验批次：`fb361830c02f4eb384e8467c5788d30e`，由正式页面提前触发，
  9/9 成功、读取/写入均为 73,301 行。事件分钟覆盖 200/200、写入 48,000 根；
  候选 D+1 14:30 在批次内覆盖 12/12，重建后新发现的 4 个可重试缺口又由页面单任务
  `run_id=560` 覆盖 4/4。最终 122/213 个候选有精确 14:30，剩余 91 个全部冷却、
  当前可重试 0；历史账本再次刷新到 800 日。详细覆盖、质量门禁和未解除限制见
  `memory/06_backtests/limit_up_production_local_parity_20260715.md`。

正式机检查：

```bash
cd /opt/1panel/project/AlphaAgent
docker compose -f docker-compose.ghcr.yml ps
docker compose -f docker-compose.ghcr.yml config --images
```

## Local V9/V15 Acceptance

2026-07-17 本地 Compose 已重建并验收：

- API 镜像 `sha256:3ad1bf58c388def6292e3a790dab9658c6652995db2f3f256d1bfcba6702dc6b`，
  Web 镜像 `sha256:3014eff8aef1167a87f411ddc3381ce145ec121f7877bd574c5ed65c9d235c0c`；
  API 为 `healthy`、重启 0、`OOMKilled=false`。
- 盘后恢复批次 `2657ae6773d94f67b4515126720d4ac0` 已完成，季度财务从原先无超时卡在
  `91/100` 修复为单股最多等待 60 秒；21:30 补偿批次
  `d9a9b6cbead141f69f14a499f7f0198d` 为 15 成功、2 失败、1 跳过。两项失败分别是
  东方财富正式板块日线空响应和 TDX 事件分钟冷却；3% 雷达分钟无到期缺口，历史账本
  重建为 801 日，证券状态快照为 3191/3191。
- 当前本地正式合同为 `limit-up-scheduled-v9 / limit-up-live-v15`：执行首板和二进三，
  买入窗口 `10:00-11:30`、`13:00-14:30`，D+1 `15:00` 按官方日线收盘价卖出。
- 3% 提前雷达已部署为内部点时采集，正式阈值仍为 5%；只读验证为
  `collecting / 0 of 60`，`production_contract` 和 `selected_contract` 均为
  `formal_5pct`。盘中页面只保留一套正式推荐，20/60 日验收未完成前不得发布 v16。
- 已验收的冻结参考覆盖 800 日、168 个有效收盘价信号；两仓 97 笔、胜率 70.1031%、平均净
  收益 +2.1953%、复利 +167.9810%、最大回撤 -8.3083%、利润因子 2.8721。二进三
  15 笔、胜率 73.3333%、平均净收益 +3.2790%；全推荐独立口径 164 笔、胜率
  62.1951%、平均净收益 +1.3011%，回撤为 -13.7650%。当前动态账本已增量到 801 日、
  截止 `2026-07-17`；规则说明仍单独展示上述截止 `2026-07-16` 的冻结参考指纹。
- 冻结后前向仍为 0 笔，状态是 `research_only`；以上只是历史候选代理，不是远端已发布
  状态或实盘收益保证。正式前向已升级为 `limit-up-forward-validation-v2`，唯一读取
  保存帧的 `actionable_recommendations`，并固定 `sweep + next_close`；竞价买入或 D+1
  开盘退出参数返回 422，`research_action` 不再产生订单。完整对照见
  `memory/06_backtests/limit_up_wide_window_next_close_two_to_three_20260717.md`。
- v14 历史版本把首板实时买点从 5% 雷达按动能分至少 55 触发，不再等待距板 1%；
  封板票满足全部条件时仍可提示尝试排队。板块门使用盘中行业或概念核心双路径，D-1 热度只诊断和
  排序，当时 `launch` 只加分。首板研究层也禁止把 D-1 热度/龙位回退成实时概念字段；
  二进三不变。
- 2026-07-15..17 的 643 个保存快照反事实形成 15/20/10 个结构买点，正式风险门后为
  0。7 月 15 日 15 个闭合结构样本胜率 `46.6667%`、平均净收益 `+1.0715%`；同股门
  通过的 4 个平均 `-0.7525%`。v9 历史收益不属于 v14，详见
  `memory/06_backtests/limit_up_dynamic_sector_entry_v14_20260717.md`。
- 同快照旧板块门消融在三天分别形成 10/5/0 个信号，全部包含在 v14 内；唯一闭合日
  旧门为 `60%/+2.8066%`，v14 新增组为 `20%/-2.3985%`。运行时继续保留正式历史
  风险否决，不把扩大覆盖解释为收益提升。
- v15 最终规则保留盘中行业路径，概念单路必须 `launch`；首板历史胜率和联合率只排序，
  不再否决正式列表。643 帧重放的闭合日从 v14 `15笔/46.6667%/+1.0774%` 改善到
  v15 `11笔/63.6364%/+2.9050%`；两仓 2 笔全胜，账户收益 `+5.7892%`。
- 13:47 数据库验收有 48 个 v14 保存帧，其中 47 个是 13:00:53..13:46:32 的合格
  `live_snapshot`，1 个非实时帧被来源审计排除。正式列表累计 0 条，独立抽取的首次
  正式信号集合与前向接口订单集合均为空且精确相等；正式胜率、收益和回撤保持 `null`。
- v2 重建后容器 `healthy`、重启 0、`OOMKilled=false`，API 日志无错误；当前本地 API
  镜像只在本地环境运行，尚未发布到远端正式环境。
- 14:19:23 首个 v15 实盘帧正式推荐华银电力、深南电A、赣能股份，14:24:45 新增
  宁波能源；截至 14:26 的 4 个 v2 前向订单股票和首次时间逐项一致，等待 D+1 收盘。
- 正式回放缓存预热后 API 容器内存约 3.7 GiB；内部连续 20 次健康请求全部成功，
  最慢 27.2 ms。盘中实时扫描会短暂显示 schedule 为 `running`，未发现超时僵尸任务。

## Focused Verification

```bash
uv run python -m compileall alphaagent/server alphaagent/market alphaagent/data_sources
uv run --group server pytest tests/alphaagent/test_legacy_product_removal.py -q
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
uv run --group server pytest tests/alphaagent/services/market_timing -q
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
git diff --check
```

低吸成员与题材门禁：

```bash
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli membership-source-status
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli audit --format json
docker compose exec -T alphaagent-api python -m alphaagent.server.services.low_suction.cli theme-eligibility-research --start 2023-03-28 --end 2026-07-15 --format json
```

## Runtime Checks

```bash
curl -fsS http://localhost:8080/api/health
curl -fsS http://localhost:8080/api/limit-up/history/status
curl -fsS http://localhost:8080/api/market-timing/panel
curl -fsS http://localhost:8080/api/mainline-replay/timeline
```

旧 `/api/quant`、`/api/backtests`、`/api/portfolios` 和
`/api/simulation` 应返回 404。

网关对外 `/api/health` 可能要求登录；容器自身健康检查使用 API 容器内的同一路径，
以 `docker compose ps` 的 `healthy` 为本地无凭据检查结果。

## Free Forward Evidence

重建 API 后，应用启动流程会先建表、协调默认调度，再启动调度器：

```bash
docker compose up -d --build alphaagent-api
docker compose ps alphaagent-api
```

不要在健康 API 旁边另起进程调用 `ensure_sync_schema()`；该入口包含旧进程中断恢复，
会把当前 API 正在执行的同步任务误判为上一个进程残留。只需依赖
`alphaagent/server/main.py` 的启动调用，随后从数据库核对 schedule 的 `job_ids`。

默认 `eod_1900` 在 19:00 主采板块/个股资金、日线、成员、涨停池和盘后证据；
`eod_finalize_2130` 在 21:30 重试资金、完整成员链路、
`sync_low_suction_security_snapshot`、涨停池和事件分钟，再重建打板账本。旧
`sync_limit_up_exit_minutes` 仍可手动用于 14:30 研究，但已从推荐任务和 21:30 正式链路
移除；v9 正式退出直接使用日线同步得到的 D+1 官方收盘价。不要用旧的
`ensure_sync_registry()` 名称，也不要在供应商空响应时手工插入 scope。Tick/L2 和真实
成交不属于夜间可回填数据。

2026-07-16 v6 历史运行验收：

- API 镜像 `sha256:ffe2ce75e200b0ac18bc8ae3678d4ec415e8d5db31f415dd57c4aada3c182c72`
  为 `healthy`；数据库中的 19:00/21:30 `job_ids` 与当时默认顺序一致。
- 19:00 恢复批次在占用时，21:30 补偿没有丢失，而是在 21:46 自动接续；21:30 批次
  首轮仍被东方财富部分板块成员响应阻断；无兜底合同上线后，`run_id=1125` 写入
  85,675 条并剔除 `BK1677/BK1678/BK1679/BK0738/BK1200`，`run_id=1131` 随后成功
  生成 85,675 条反向索引和逐日快照。概念 `495/498`、行业 `494/496` scope 均完整且
  记录精确排除 ID；五个板块在当日冻结快照均为 0 行。
- 超时晚写竞态修复部署后，正式成员任务 `run_id=1132` 写入 86,111 条，只剔除
  `BK1677/BK1678/BK1679`；两个行业接口已恢复，三个失败概念当前成员仍为 0 行。
  `run_id=1133` 因已过午夜而按可靠日期合同跳过，没有覆盖 7 月 16 日冻结快照。
- `run_id=1101` 首轮处理 200 个 D+1 14:30 缺口，真实覆盖 98、空响应 102、错误 0；
  `run_id=1102` 处理单批上限外的剩余 21 个，覆盖 0、空响应 21、错误 0。总精确覆盖
  从 98/319 提升为 196/319，剩余 123 个全部进入退避，当前可重试为 0。
- 第二轮缺口日期为 2025-06-30 至 2025-08-11；TDX 扫描 470,640 根远端分钟记录仍无
  目标行，证明公开源回溯边界不能靠重复夜间任务消除。当时 `limit-up-live-v10` 成熟
  正式推荐请求为 0；下一交易日闭合后才会自动加入。
- 正式 `limit-up-scheduled-v6` 回放只认精确 D+1 14:30：151 个请求中 124 个精确、
  27 个剔除、收盘代理 0。两仓 58 笔、胜率 63.7931%、复利 +66.9032%、回撤
  -5.7239%；全推荐独立统计 121 笔、胜率 57.8512%。冻结后前向 0 笔，状态仍为
  `research_only`。详见
  `memory/06_backtests/limit_up_no_fallback_impact_20260716.md`。

## Data Notes

- `ensure_schema_once()` 在 API 进程内只执行一次。
- `create_schema()` 先执行固定旧表清理，再创建保留 metadata。
- schedule registry 会删除旧 `tail_quant_1430`、`quant_research` 和
  `tail_preview` 行。
- 不在通过静态、后端、前端和打板指纹门禁前重建 API 容器。
