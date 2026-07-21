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
- `>=3%` 提前雷达只作为内部观察分母，不是买点；点触发 v9 只保存研究数据，正式
  `limit-up-live-v15 / limit-up-scheduled-v9` 未改变。盘中页面仍只保留一套正式推荐，
  点触发未通过完整 `40 fit + 15 calibration + 60 validation` 前不得升级生产规则。
- 正式历史默认入口现固定为 `portfolio / next_close`。当前可靠窗口为
  `2023-03-28..2026-07-20` 共 802 日、170 个信号；两仓 99 笔、胜率
  `69.6970%`、平均净收益 `+2.1796%`、复利 `+171.7614%`、最大回撤
  `-8.3083%`、利润因子 `2.8454`。这是触板后正式组合基线，不能直接解释为提前点触发
  的胜率。
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
- 旧启动流程会无条件预热全历史打板回放和次日计划，实测 API 持续占用
  `79%-96% CPU`、内存升到约 `3.7 GiB`；这不是常驻接口的必要成本。默认启动现已关闭
  两项预热，只有明确设置 `ALPHAAGENT_STARTUP_BACKTEST_WARMUP=true` 或
  `ALPHAAGENT_STARTUP_NEXT_SESSION_PLAN_WARMUP=true` 才恢复。正式 15:05/19:00/21:30
  计划任务不受影响。
- API 和研究容器的 OpenBLAS/OMP/MKL/NumExpr 均固定为单线程；根开发 Compose、
  local-directory 服务器部署和 GHCR 部署的 API/PostgreSQL 默认上限均为 `0.25/0.25`
  核，本地独立研究容器上限为 `0.10` 核。API 连接也关闭 PostgreSQL 并行 worker，避免
  在 0.25 核数据库配额内启动多个争抢进程。数据同步批次的 `concurrency` 会显式传入
  每个 `DataSyncRunner`；盘中小时任务默认为 2，19:00/21:30 全量增量任务默认为 1。
  点触发研究的后端内部采集为打板快扫 10 秒、概念刷新约 30 秒、交易窗口 scheduler
  tick 2 秒；`/short-term` 浏览器轮询独立保持 60 秒，不能把前端读取节奏写回后端采集。
  行情缓存仅在交易时段且 TTL 到期后刷新；大盘基础择时最多 30 分钟重算，读取时仍覆盖
  实时指数。
- 点触发采集开盘前必须从运行中的 data-sync worker 验证
  `LIVE_SCAN_INTERVAL_SECONDS=10`、`SCHEDULER_TICK_SECONDS=2` 和非空
  `capture_runtime_fingerprint`。2026-07-21 `10:42` 的错误镜像曾把前两项改成
  `60/15`，运行库随即出现 P50 `70.613s` 的固定扫描节拍；`11:33` 恢复 `10/2` 后下午
  P50/P90 回到 `10.799/14.102s`。交易窗口内不得部署采集实现，盘中实现或指纹变化会让
  整日只能冻结为 `incomplete`，不能事后补洞。
- 宿主 `pytest` 现在也由 `tests/conftest.py` 在测试模块导入前固定 OpenBLAS/OMP/MKL/
  NumExpr 为单线程，避免本地定向测试绕过 Compose 限额。低吸 warming 定向测试实测
  `11 passed`、CPU 约 `103%`（含 `uv` 启动开销），OpenBLAS 运行时线程数为 1。本机
  Vitest 也关闭测试文件并行。本机 VS Code 配置把 Vitest 监听从全仓库 `**/*` 收缩到
  `frontend/src/**/*.{spec,test}.{ts,tsx}`，关闭 Python 保存时自动重发现测试，并排除
  `.venv`、`node_modules`、缓存、数据目录和大型回测 JSON；稳定窗口中 Vitest worker
  为 `0%`。该编辑器配置位于被忽略的 `.vscode/settings.json`，只属于当前工作区环境。
  项目不使用 Bun，工作区也关闭 Bun 测试发现、诊断 socket、lockfile 预览和调试终端。
  本机 Codex 配置已将无效的 `model_reasoning_effort="max"` 修正为客户端支持的
  `"xhigh"`，`codex doctor` 确认整份配置成功加载，因此 `tui.animations=false` 才真实
  生效；修复前已启动的会话仍需正常退出后重开，不能通过终止进程冒充应用 CPU 优化。
- 实时打板历史验证改为绑定历史账本更新时间的 6 小时精简缓存；历史类比和同股票
  D+1 证据只投影所需 JSON，一次查询共同生成。当日情绪、交易日历和概念分组只加载
  一次。概念聚合在 5,000 股票/446 概念固定基准从 `0.364654s` 降到 `0.151567s`
  （约 `2.4x`），输出指纹不变。严格 D-1 成员缓存和只读行情帧复用上线后，盘中完整
  概念扫描由原记录的 `11.3-13.4s` 降到最近 `3.3-3.5s`；改造前 15 秒打板扫描最近为
  `3.4-5.3s`。当前快速页并发读取 page 1..4、每页 100 只，并按最早来源时间合并；盘后
  宿主/部署镜像实测均为 `400/400` 唯一代码、100% 页覆盖、零错误，耗时约
  `0.80s/1.57-2.65s`。交易时段真实 10 秒缺口仍待下一完整日审计，正式交易规则未改变。
- 实时轨迹写入不再回传整行大 JSON，并把同股三通道信号压成最高优先级一条。2026-07-20
  盘中实测每帧从约 231 条降到 88 条，轨迹持久化从 `189-291ms` 降到 `67-102ms`。
  后续又确认 `radar_candidates` 与 `ranked_candidates` 在保留的 1,514 帧中 100% 相同；
  新写入不再保存后一份副本，读侧也不再选择该列，并按 32 帧流式解析 JSON。旧 API
  冷读当日 694 帧后匿名内存约 `3.2 GiB`；部署镜像从约 `172 MiB` 增至 `471 MiB`，
  冷读高水位下降约 85%，受限数据库上的首次读取为 `49.948s`，缓存命中为 `0.130s`。
  旧两交易日大帧按原保留策略自然
  淘汰，不清表。前端仅在真实交易时段每 60 秒刷新实时快照和轨迹；午休/盘后停止轨迹
  轮询，实时快照在初步计划阶段为 60 秒、正式计划阶段降为 300 秒。
- 实时概念扫描现在按严格 D-1 交易日缓存不可变成员索引，同一交易日不再每 30 秒重读、
  重建约 8 万条成员关系；运行时快照只复制会更新的顶层质量字段，10 秒快速增量扫描不再
  深拷贝整份成员图；增量行情进一步只重算其股票所属概念和相关成员，不再复制约 5,000
  只股票后全概念重算。三个无实际消费者的股票榜单后台预热也已移除，页面仍使用本地库和
  自身按需缓存。成员查询/建索引路径已从栈采样消失，行情预热线程实际工作时间从约
  `3.82s` 降到 `0.42s`。
- 低吸波段页不再在整个工作日固定每 30 秒读取纸面账户。服务端现在返回距离下一个刷新
  窗口的秒数：`09:25-09:40`、`14:45-15:05` 为 30 秒，`18:55-22:30` 晚间结算为
  300 秒，其余时间只设置一个直达下一窗口的长定时器，并跳过周末；5 秒只读缓存合并
  多标签页的重复数据库/Pandas 汇总。真实库在 `0.10` 核研究容器的首次/缓存读取为
  `1.802120s/0.000023s`；部署后 HTTP 冷读/命中为 `0.724326s/0.094106s`，负载消退后
  API/worker/PostgreSQL CPU 为 `0.14%/0.00%/0.00%`。
- 2026-07-21 点触发冷启动、Wilson 最终验收门、研究行情隔离、盘中冻结保护、active
  model 记录完整性、官方 D+1 独立重算、冻结结算证据和动作阶段完整性门修复后的
  当前 API、data-sync worker 和 point-trigger worker 统一镜像为
  `sha256:53ee907c237a1d51e140ef39ea11b74810e66f8e5f1f7d1ee1d7484f3f11929b`；API 和
  data-sync worker 均为
  `healthy`，三者重启 0、`OOMKilled=false`，独立 worker 为 `0.10 CPU`、pool `1/0`，
  状态 `not_ready_model_scope`。运行报告为 `collecting_fit`，进度
  `0/40 + 0/15 + 0/60`，`model_fingerprint=null`、`performance_visible=false`、
  `formal_strategy_changed=false`；四张前向账本为 `1/0/0/0`。首次事件标签定向测试为
  `40 passed`，点触发与雷达仓储为 `184 passed`，打板与数据同步组合为 `1207 passed`
  （1 条既有 Starlette 弃用警告）。下一交易日固定采集运行指纹为
  `sha256:4ccbb7635e49ab257da20f991733848a47186ace91e7822be14b6edea5357462`；7 月 21 日最后
  已保存帧仍属于盘中旧镜像指纹，不能回填或改写。
- 2026-07-21 在真实 15:00 后冻结为 `incomplete`：正式窗口 `719` 帧、`225,918` 条观察、
  6 个冻结正式订单，feature/model/action 均为 0。原因码同时包含 ready、扫描 P90、最大
  缺口、概念加速度覆盖、运行指纹缺失和运行指纹切换。日级较差值为 ready `95%`、扫描
  P90/max `69.9095/98.4517s`、概念覆盖 `68.3489%`、运行指纹覆盖 `6.3978%`；下午自身
  `459` 帧、ready `98.6928%`、扫描 P50/P90/max `11.0012/14.6813/57.8240s`，不得冲淡
  上午故障。最终报告绩效、账户、可靠门均为 `null`，归档文件不存在。
- 对该排除日的 970 帧、277,886 条观察做只读标签重放时，发现 7,026 条持续
  `buy_now` 实际只对应 42 个首次首板股票日。旧标签把重复状态当成 65 个可达事件；按
  股票日只认第一次正式事件后，601 个已知候选帧中有 53 个正例帧、严格可达 13/40 个
  买入窗口内首次事件，领先 P50/P90 为 `31.5565/52.0809s`。该结果只证明采集可产生真实
  提前标签，不是模型精度或收益；详见
  `memory/06_backtests/limit_up_preboard_point_trigger_v9_first_event_label_audit_20260721.md`。
- 2026-07-22 为周三且不在 2026 公共假期集合中，当前按下一预期交易日准备。使用运行库
  状态模拟该日 09:00 的 worker 健康检查为 `healthy`：当前日允许尚无帧，固定常量仍为
  `10s/2s/30s`，实时和概念扫描 schedule 均启用。09:15 后必须由真实 schedule 心跳和
  当日首批帧的唯一指纹重新证明健康；只有收盘后的上午/下午完整性审计才能决定该日是否
  成为首个 fit 日，日历预期或盘前模拟本身均不能计数。
- 调度所有权已从 API lifespan 拆到独立 `alphaagent-data-sync-worker`；API 固定
  `ALPHAAGENT_STARTUP_DATA_SYNC_SCHEDULER=false`，只建表且不恢复/启动调度。普通 API/Web
  重建不再清空 scheduler 进程内概念历史；只有显式重建 data-sync worker 或整套 Compose
  才会中断采集，仍按完整日质量门排除当天缺口。
- data-sync worker 已增加 Compose 原生只读健康检查。它不调用约 7 秒的完整源码/依赖
  指纹计算，而是用 AST 直接核对镜像中的 `10s/2s/30s` 固定节拍，再用轻量 psycopg 查询
  两个扫描 schedule 的盘中心跳和数据库已保存的指纹。周末不要求盘中心跳；工作日休市
  仍只要求 scheduler 活着，不因缺少当日行情帧误报；当日指纹缺失/切换只在扫描窗口内
  报错，盘后已冻结的坏日不会触发无效重启循环。Docker 使用 worker 暖进程内仅监听
  `127.0.0.1:8010` 的只读 `/healthz`，避免每 30 秒冷启动 Python 与扫描争抢 0.25 CPU；
  真实容器单次检查为 `21.5ms`，状态 `healthy`、失败计数 0。验证命令：
  `docker compose exec -T alphaagent-data-sync-worker curl --fail --silent http://127.0.0.1:8010/healthz`。
- 点触发仓储现在拒绝 `trade_date <= 2026-07-20`，冻结模型必须恰好包含按日期唯一有序的
  `40 fit + 15 calibration` 且 calibration 晚于 fit、validation 日期为空；实时评分再次
  校验同一 cohort，非法模型失败关闭。`reliability-v8` 还要求 validation scope 晚于模型
  和自身收盘，重算模型/动作/完整日标签指纹、每日两仓选择约束、官方 D+1 结果和动作
  四阶段完整性，并从冻结结算证据独立重放延迟成交、正式身份和物理触板。运行库已存在
  `settlement_evidence JSONB` 和 `settlement_evidence_fingerprint VARCHAR` 两列；四个新增
  硬门为 `settlement_evidence_integrity`、`delayed_fill_integrity`、
  `formal_identity_integrity` 和 `physical_touch_integrity`。最终归档器只接受满 60
  个 validation 日、展示绩效、状态为 `forward_reliable_candidate_for_live_review` 且
  指标重算后的完整可靠门全部通过的正确合同报告；
  `forward_rejected` 不能生成最终 JSON/Markdown。
  v8 在首个合法 scope 前另冻结同期正式账户不劣门：联合产品正常/双倍成本胜率和复利差
  均不得为负，最大回撤差不得低于 `-1pct`，PF 保留率不得低于 `0.95`。
- 每个新冻结日的 `audit_metrics` 还会不可变保存正式首板事件经过“原始 3%、帧质量、
  新鲜报价、成熟历史、lane 合同存在、静态门”的 60 秒可达漏斗，以及已知/缺口/跨时段
  标签覆盖。它们只用于定位采集、母池和过滤损失，不进入模型向量或改变可靠门。
- `eod_finalize_2130` 已启用，点触发任务位于 21 个任务中的序号 19；最近批次
  `2026-07-20 21:45:21..22:49:38` 为 `succeeded`，未完成 job 为 0。15:05 公开
  `limit-up-live-v15` 为 `next_session_preliminary`，85 个候选、组合为空；候选、市场上下文
  和推荐的当次规范指纹为
  `7f4e06c02177bf3effc4f56bd40e7ae7f5fba99b22ea8c662b093c7da704d7e4`，递归投影没有
  点触发概率、身份分、研究行情增强值或运行指纹。次交易日 final plan 为 2 个二进三观察项；
  所需 2026-07-20 D-1 概念
  成员 scope 完整，为 `70,116` 行、495 个概念、5,609 只股票，行业 scope 也完整，为
  `16,830` 行、496 个行业、5,610 只股票。正式新浪和研究东方财富盘后各返回
  `4 x 100` 行、400 个唯一代码，交集 399；研究涨速、振幅、主力净流入、净流入率和独立
  来源时间均为 `400/400`。7 月 20 日旧观察对应列保持 0 覆盖，禁止回填。
  合同修复前最近一次盘后无研究任务的干净 20 秒 cgroup 累计计量为 API `0.402%`、
  PostgreSQL `0.345%`，瞬时值约 `0.15%/0.00%`，API 未加载轨迹缓存时约 `182 MiB`；
  该性能数值不重新归因给新镜像。上一镜像交易时段两次 45 秒计量为
  API `9.31%` 和 `8.90%`，相对更旧镜像的 `11.51%` 降低约 `19%-23%`。以后优先使用
  `cpu.stat usage_usec` 固定时间差，不用少量瞬时点估算平均值。
- 19:00 盘后批次曾因调度并发只记录在批次元数据、未传给任务执行器而实际回退到 8 个
  逐股解析线程，API 持续触及 `0.50` 核旧上限。修复传递后，在同一运行中并发 2 的
  30 秒平均为 `23.278%`，并发 1 为 `20.108%`；再将 API 硬上限降至 `0.25` 核后，
  不同活跃阶段的 20 秒平均为 `8.030%-23.681%`，峰值受限于单核 `25%`，即当前
  6 核主机总容量约 `4.17%`。期间健康请求通常 `1.2-1.8ms`，最慢采样 `58.6ms`，
  容器重启计数为 0。该数值是活跃同步负载，不与盘后空闲基线混用。
- 板块资金流持久化不再为每条记录分别查询并更新 `sectors/sector_fund_flows`；现在先按
  主键去重，再用两条固定 `ON CONFLICT` 语句批量执行。最终镜像实际盘后任务写入
  `2,973/2,973` 行并在 `24.968s` 内成功完成，覆盖该任务主体的 20 秒 cgroup 平均为
  `8.030%`，随后批次正常进入单并发股票日线同步。
- 板块成员同步不再在 19:00/21:30 每次抓取全部板块：执行层按 `updated_at` 落实 7 天
  新鲜度，线程内复用东方财富 HTTPS Session，并以 500 行 `ON CONFLICT` 批量写入。
  2026-07-20 真实库验收为 `994 total / 991 reused / 3 requested / 0 refreshed`，完整调用
  `23.997s`，其中三项请求均是长期无成员报告板块失败；原来的 991 个有效板块没有外网
  请求或成员 upsert。21:00 后中断的 19:00 主批次不再从头恢复，交由 21:30 补偿；最终
  该次成员优化验收镜像为 `sha256:e749c7a05bc7b810791c18899cf86940c9f5706a151ab32cb54a10f4658cde5c`，
  API 健康且无批次工作线程。空闲 20 秒 `cpu.stat usage_usec` 差分为 API
  `0.0061` 核、PostgreSQL `0.0068` 核、点触发 worker `0.0010` 核；分别是单核的
  `0.610%/0.681%/0.100%`，仅占各自 `0.25/0.25/0.10` 核硬上限约
  `2.44%/2.72%/1.00%`。数据库同时无活动业务 SQL，瞬时 `docker stats` 不再作为
  稳态结论。
- 全市场行情热路径只转换实时策略需要的轻量字段，不再保存每股 `raw` 或重复规范化；
  专用短 TTL 缓存只复制列表和行容器。历史类比与同股 D+1 证据共用一次精简查询和一个
  6 小时缓存，命中时只复制顶层索引容器。雷达观测改为固定 upsert 加 `executemany`
  参数批量写入，不再为每帧生成数百值的 SQL。最近完整调度中概念扫描 `2.334821s`、
  实时打板 `3.050970s`，均为 `succeeded`；实测最近每帧 `229-252` 个候选，
  `capture_count` 与实际观测行数始终一致，未以丢数据换取性能。
- 全历史回测报告仍按需构建，但 `_BACKTEST_REPORT_CACHE` 只复制顶层报告壳；通用
  `TTLCache` 默认深拷贝合同不变。API 重启后的首个 portfolio 回测实测 `49.318s`、响应
  `435,611` 字节、API 观测峰值约 `1.704 GiB`；同一报告缓存命中为 `0.075s`，没有再次
  递归复制，构建后的容器高水位约 `1.56 GiB`。首次构建仍是一次性重 CPU/内存负载，
  不能算作常驻基线；启动时全历史预热继续默认关闭。
- 802 日 `limit_up_history_rebuild` 已完成独立真实验收。最终镜像为
  `sha256:fdc2822f39f739417d1c5cf7eb70cd3eb03d70747689295b07308562bafd8a1a`，
  API 为 `healthy`、重启 0、`OOMKilled=false`，仍受 `0.25 CPU` 硬上限约束。无额外
  校验干扰的总耗时由约 `10m49s` 降到 `8m32s`；最终带并发全账本哈希的验收为
  `8m45s`。特征阶段约从 `2m09s` 降到 `1m00s`，逐日回放约从 `5m45s` 降到
  `4m04s`；任务执行期间会触及 0.25 核限额，结束后 API 空闲 CPU 回到约
  `0.14%-0.16%`。
- 重建热路径现在向量化滚动特征、市场映射和聚合，逐日仅物化竞价候选及事件股，并复用
  同日类比桶、首板三入口状态、固定日内网格和日期索引。峰值内存由最初约 `6 GiB` 降到
  `3.98 GiB`；任务结束后通过 GC 和 glibc `malloc_trim` 归还空闲堆，常驻内存由旧版约
  `2.84 GiB` 降到 `0.69 GiB`。历史账本按 20 日小批序列化，数据库只持久化一份
  `board_lanes/board_candidate_pool`，读取时恢复原 API 字段；有效 JSON 由约 `114 MB`
  降到 `60 MB`，写库网络量约从 `340 MB` 降到 `194 MB`。重建前后 802 日账本指纹均为
  `ba84653d68c46603eaeb1f0cc9c27208`，范围保持 `2023-03-28..2026-07-20`。
- 历史刷新完成或账本已经最新时，不再隐式启动全历史回测预热；显式
  `ALPHAAGENT_STARTUP_BACKTEST_WARMUP=true` 开关仍保留。重建完成后没有
  `limit-up-backtest-warmup` 线程。`VACUUM (FULL, ANALYZE) limit_up_history_replays`
  已把总表由 `1.84 GiB` 收缩到 `1.538 GiB`；剩余主体是仍被研究文档引用的
  `limit-up-history-v2..v14` 共约 7,809 行，不得作为本次性能清理的一部分直接删除。

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

2026-07-20 CPU 热路径验收：后端两组分别 `224 passed`、`150 passed`；研究清单硬门
下沉后定向回归 `15 passed`；前端 `117 passed`，生产构建、定向 Ruff、compileall 和
`git diff --check` 均通过。Wilson 门和盘中冻结保护加入后的完整
点触发六文件定向回归为 `122 passed`，`tests/alphaagent/test_limit_up*.py` 回归为
`963 passed`，1 条既有 Starlette 弃用警告；
compileall、Ruff、空白及开发/部署
Compose 展开均通过。7 月 20 日全日只读重放在专用
`0.10 CPU` 容器中完成：静态质量身份池 `4,956/4,956` 行均可形成有限模型向量，
加载/构造/标签/总耗时 `71.30/55.00/8.40/153.30s`，四账本前后均为 0。

2026-07-21 点触发完整性审计已改为按股票日一次分组、零完整行复制，并在完整性门通过前
只读取 20 个必要观察字段。对同一 `2026-07-20` 的 677 帧、204,425 条观察，在同一
`0.10 CPU` 研究容器中，全字段路径为 `81.800s / 1,301,612 KiB`，窄列路径为
`27.099s / 435,644 KiB`，总耗时下降 `66.9%`、峰值 RSS 下降 `66.5%`；状态、原因码和
全部正式漏斗指标逐项相同。冻结 artifact 同源与模型记录完整性门补齐后，定向模型/服务/
仓储回归 `55 passed`，当时 API/worker 镜像为
`sha256:55e56cfc304d709ec191ed4f9f243bc454e3186ab240ad63ad1ca5e1d409319b`。
两次部署后干净约 20 秒 `cpu.stat` 差分折算到 6 核整机为 API
`0.0368%-0.0566%`、worker `0.0136%-0.0145%`、PostgreSQL
`0.0507%-0.0544%`，三者合计约 `0.10%-0.13%`；无
`alphaagent-api-run-*` 临时容器，三项服务均未重启或 OOM。

802 日历史重建优化后的完整打板与调度回归为 `1084 passed`；定向 Ruff、compileall、
`git diff --check` 均通过。唯一警告是既有 Starlette `httpx` 弃用警告。

## Heavy Research Jobs

全历史研究使用独立的 `alphaagent-research` Compose 服务，不再临时复用未限额的
`alphaagent-api` 服务。研究容器硬限制为 `0.10` CPU，不能再由调用方环境变量提高；
数值库线程固定为 1，数据库池固定为单连接，并通过 `PGOPTIONS` 将新研究连接标记为
`alphaagent-research`、关闭 PostgreSQL 查询并行 worker。这里必须同时约束 Python 和
数据库端：仅限制研究容器无法阻止 SQL 把计算转移给 PostgreSQL 多核执行。常驻 API
不受该限额影响。

运行时验证：`docker inspect <research-container>` 的 `NanoCpus` 应为 `100000000`；
研究连接执行 `show max_parallel_workers_per_gather` 应返回 `0`。修正前一次显式 1 核的
逐笔研究任务曾把 PostgreSQL 拉到约 `303% CPU`。2026-07-20 又观察到误用
`docker compose exec/run alphaagent-api` 的 Hazard 覆盖和补数任务，两次都让 PostgreSQL
持续触及 `0.25` 核上限；任务已自然结束且未被中断。后续研究必须从
`alphaagent-research` 服务启动，才会同时得到 `0.10` 核、`1/0` 连接池和非并行数据库
会话；常驻 CPU 排障时也必须先排除 `alphaagent-api-run-*` 临时容器。

`preboard_radar_sequence_study` 入口和共用 `load_preboard_manifest` 清单加载层都会校验
容器内 `PGOPTIONS`；不是 `application_name=alphaagent-research` 或没有关闭 PostgreSQL
查询并行时，会在读取数据库前直接失败并提示正确 Compose 服务。实测直接通过
`alphaagent-api` 调用底层 `load_static_hazard_manifest` 也已被拒绝，数据库活动查询数保持
为 0。排障期间旧 v8 对照曾留下 `scope-retry` 和 `rerun1-stable` 临时容器：前者自然
结束，后者虽只有约 `0.04%` 容器 CPU，却把 SQL 计算转移到 PostgreSQL 并持续触及
`0.25` 核上限。两者现均已删除，没有半成品报告或研究数据库会话，正式 v8 历史报告
未被覆盖。清理后四次瞬时采样中 API 通常为 `0.14%-0.30%`（一次计划任务脉冲
`2.61%`），PostgreSQL 为 `0.02%-0.18%`。

低吸研究已采用收盘价代理，`sync_low_suction_forward_ma5_minutes` 因此保留为手动诊断
任务，但不再加入 19:00 和 21:30 默认批次；打板研究需要的事件/雷达分钟补数不受影响。

API 启动时四类昂贵后台工作现均默认关闭：历史回测预热、次日计划预热、市场缓存并发
预热和盘中择时 refresher。对应环境变量分别为
`ALPHAAGENT_STARTUP_BACKTEST_WARMUP`、
`ALPHAAGENT_STARTUP_NEXT_SESSION_PLAN_WARMUP`、
`ALPHAAGENT_STARTUP_MARKET_CACHE_WARMUP` 和
`ALPHAAGENT_STARTUP_INTRADAY_REFRESHER`；只有明确需要主动刷新时才设为 `true`。
页面请求仍可惰性加载，正常计划任务不受影响。2026-07-21 部署镜像
`sha256:35c9fe0e6e0608840ae68ccc2aee0c87a53507976d17c8eba7be58609a84706f`
后，四项均为 false；常规概念扫描约 3.6 秒完成，随后 API/worker/PostgreSQL 瞬时 CPU
为 `0.16%/0.00%/0.06%`，API/worker 均无重启或 OOM。

首板一分钟前缀回放已取消每个决策点重复排序和重扫开盘以来全部记录。同一组 240 根
分钟线在优化前后输出指纹完全一致；本地单股单日基准中，完整策略前缀由约 `39.55ms`
先降到 `22.34ms`，再通过复用股票日静态盈利门、候选字段、支撑分和入场质量降到
`17.34ms`（相对原始约 `2.28x`）；基础特征由 `12.27ms` 降到 `8.45ms`
（约 `1.45x`）。相关 lane、策略前缀和 hazard 回归共 `91 passed`。

首板 3% 清单查询不再先对 454 万条全历史日线执行多层窗口再按日期过滤；目标交易日和
主板范围先收窄，再通过 `(vt_symbol, trade_date)` 主键读取前两根、126+1 根基因上下文
和 D+1。原始一分钟加载也改为每批最多 128 个精确股票-日期对，避免近千个复合条件让
PostgreSQL 放弃索引改走 670 万行顺序扫描。规则字段、D+1 合同和 126 日统计口径不变。

通用研究数据指纹保持原 SHA-256 内容不变，但改为有序输入零整表复制、每 25,000 行
分块增量哈希。40 万行同构日线基准的峰值 RSS 从约 `614 MiB` 降到 `208 MiB`，耗时
从 `3.87s` 降到 `3.54s`；这主要消除大表 JSON 导致的内存和换页压力。CPU 峰值由
Compose 的 `0.10` 核硬限额控制。

低吸动态龙头回放现将路径规范化、信号和日状态账本集中到
`prepare_stock_campaigns()` 一次完成。完整 V4 四变体复用同一份已准备路径，不再为
每个变体复制、排序整张 leader path；V5 支撑日研究只调用
`prepare_dynamic_leader_paths()`，在规则未入围前不执行旧 V4 的任何交易退出变体。
V5 的双成本敏感性改为对同一 D+1 成交账本向量化重定价；无规则入围时，完整股票
收盘日历从两次扫描降为一次。针对性状态/交易回归 `48 passed`，并有测试锁定“准备
阶段零交易执行”“准备/完整回放账本相同”和“重定价不改变成交身份/日期”。
V2 因果前向捕获在逐候选定位前一次性排序龙头路径和股票特征多级索引，消除了 Pandas
非词典序索引慢路径；对应捕获回归 `4 passed` 且不再产生 `PerformanceWarning`。

```bash
docker compose run --rm --no-deps \
  -v "$PWD:/workspace" -w /workspace \
  alphaagent-research python -m \
  alphaagent.server.services.limit_up.preboard_competing_risk_study \
  evaluate --format markdown
```

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
curl -fsS http://localhost:8080/api/market-timing/panel
curl -fsS http://localhost:8080/api/mainline-replay/timeline
```

后端内部点触发采集固定为打板快扫 10 秒、概念刷新约 30 秒、交易窗口调度心跳 2 秒；
前端实时快照、轨迹日期、当日轨迹和展开后的单股轨迹统一每 60 秒检查一次。不要把页面
轮询恢复为 10 秒：`/api/limit-up/live` 当前响应约 1 MB，浏览器无需追随内部采集频率。
2026-07-21 部署 Web 镜像
`sha256:845c801a806e4944f57532fa2ad2f7f8571680726eaecf06d2158f3437daab47`
后，盘中抽样 API CPU 从约 23% 降到 2.63%，PostgreSQL 从约 11.5% 降到 0.21%。
浏览器中已打开的旧页面需要刷新一次才能加载新轮询合同。

同日进一步修正后，API 镜像为
`sha256:27164ad6ebf071a9cbd37fde167f53c0381e29b1c55b92f2b863a6398589a534`。
稳定期抽样中 API/PostgreSQL 空闲 CPU 约 `0.13%-0.25%`，快照执行时 API 可短时触及
`24.6%` 的 0.25 核硬上限；这是分钟任务的瞬时峰值，不再是 2 秒空轮询造成的持续占用。

2026-07-21 跨行情低吸证据页面部署版本：API
`sha256:bfae0436ad79e8bb4dbeb51633a119c92de22986d2ffb9b7828356d05961a8d7`，
Web `sha256:d99243381d5cfd7127f9a04c87a4d5192899ea318fea2e451daf3117219226b4`。
API 镜像必须同时包含 V3 summary 与 V5 rotation-timeliness JSON；缺少前者会使
`/api/low-suction/swing-research` 返回 503。桌面与 390px 移动端浏览器验收通过，
控制台零错误，页面无全局横向溢出。

旧 `/api/quant`、`/api/backtests`、`/api/portfolios` 和
`/api/simulation` 应返回 404。

网关对外 `/api/health` 可能要求登录；容器自身健康检查使用 API 容器内的同一路径，
以 `docker compose ps` 的 `healthy` 为本地无凭据检查结果。

## Free Forward Evidence

The frozen cross-regime candidate now accumulates through
`causal-leader-pullback-cross-regime-forward-v2` only. A 2026-07-21 09:xx
readiness run returned `strict_source_pair_unavailable`, wrote no capture,
recommendation, or order, and left formal metrics null. This is the expected
pre-close state: the 2026-07-20 strict source scopes may only bind to the next
observed session after the 2026-07-21 daily close exists.

```bash
docker compose exec -T alphaagent-api python -m \
  alphaagent.server.services.low_suction.cli \
  v4-cross-regime-forward-run --as-of-date 2026-07-21
docker compose exec -T alphaagent-api python -m \
  alphaagent.server.services.low_suction.cli \
  v4-cross-regime-forward-report --as-of-date 2026-07-21 --format json
```

Do not supply a fabricated post-close timestamp and do not backfill a missed
natural date. The normal 19:00/21:30 EOD chain owns the first complete capture.

重建 API 后，应用启动流程会先建表、协调默认调度，再启动调度器：

```bash
docker compose up -d --build alphaagent-api
docker compose ps alphaagent-api
```

不要在健康 API 旁边另起进程调用 `ensure_sync_schema()`；该入口包含旧进程中断恢复，
会把当前 API 正在执行的同步任务误判为上一个进程残留。只需依赖
`alphaagent/server/main.py` 的启动调用，随后从数据库核对 schedule 的 `job_ids`。
中断恢复对 `eod_1900/eod_finalize_2130` 另有时间门禁：当天未到各自 cron 时刻不会在
盘中重跑整套 EOD；状态先收口为 `failed/interrupted`，到 19:00/21:30 再由正常调度
执行。实时扫描和其他轻量任务的恢复行为不变。

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
