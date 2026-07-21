# 首板提前点触发 v9 前向协议（2026-07-20）

## Current state

- 合同为 `limit-up-preboard-point-trigger-v9`，最终验收门版本为
  `limit-up-preboard-point-trigger-reliability-v8`。
- 当前状态为 `collecting_fit`，真实进度为
  `0/40 fit + 0/15 calibration + 0/60 validation`；模型指纹、研究动作和绩效均不存在。
- 所有动作固定为 `actionable=false / none_research_only`。正式
  `limit-up-live-v15 / limit-up-scheduled-v9` 未修改。
- 2026-07-20 是永久排除的 shakedown 日，只用于验证采集和标签链路，不进入任何阶段。
- 2026-07-21 已在 `15:03` 冻结为唯一 `incomplete` scope：正式窗口 `719` 帧、
  `225,918` 条观察、6 个冻结正式订单，feature/model/action 均为 0。上午扫描和概念质量、
  全日运行指纹缺失及盘中实现切换分别失败，不能进入 fit，也禁止事后补洞。

## Frozen causal contract

`>=3%` 是观察分母而不是买点，不设 9.5% 上限。每个保存时刻只允许使用 `<=t` 的
亚分钟雷达帧；快速行情固定为每 10 秒并发读取涨幅榜前四页（每页 100 只），约 30 秒
全市场概念行情补充其余股票。候选必须是尚未触板的沪深主板首板，并复用正式首板已经
确定的静态 lane 质量、至少 5 个成熟同股 D+1 样本和至少 30% 联合率门。触板基因、财报和分歧修复等
静态 blocker 继续硬排除；support、entry quality、正式市场门和 7 个动态 lane blocker
只作为预测特征，不能要求预测前已经通过。

上午 `10:00..11:30` 和下午 `13:00..14:30` 必须各自通过帧 ready/stale、新鲜报价、
扫描 P90/max gap、报价覆盖、市场状态和概念加速度门；日级审计取两个窗口的较差值，
不能让稳定窗口稀释故障窗口。每个原始 frame 同时冻结基于运行源码和依赖版本的
`capture_runtime_fingerprint`；完整日必须 100% 非空、格式合法且全日唯一，该值还写入
不可变 day scope 和 cohort 指纹。同名策略盘中换实现、缺指纹或非法指纹都只能冻结为
`incomplete`。

模型分为市场事件、同刻身份排序和动作概率三层。标签是动作后完整 60 秒候选 cohort 中
最早出现的正式首板身份；不得只检查模型已经选择的股票。未来触板、D+1、日终资金、
后来概念和股票/概念身份字符串不得进入模型向量。缺少 20/60 秒锚点或点时资金时使用
`0 + missing flag`，不能静默删除刚进入 3% 的候选。

成交代理只检查动作后 20..60 秒内第一条新鲜报价：第一条报价低于涨停价才算成交；
第一条已经涨停或没有报价均记为 `queue_unknown_without_l2`，从可靠账户中拒绝。午休或
收盘前不足完整 60 秒时不生成研究动作。

D+1 结算先用全市场至少 3,000 只日线的可靠交易日历绑定动作后的精确下一市场交易日，
再只接受该股票在该日期的官方收盘 bar。精确 D+1 缺 bar 时动作保持未闭合并使行情完整
门失败；即使 D+2 已有 bar 也禁止顺延替代。最终报告只认外部传入的可靠市场日历和原始
官方日线，按正式费用函数独立重算 gross、普通成本和双倍成本收益，再逐项核对动作账本的
D+1 日期、收盘价和三项收益；账本字段不能直接成为绩效真值。

每个动作在结算前冻结动作后报价、同日正式事件和物理触板观察的原始证据及 SHA-256
指纹。最终报告必须从该证据独立重放延迟成交和物理触板，从冻结 feature label 重放正式
身份，并用 D 日官方最高价/收盘价复核触板与最终封板；修改成交价、收益、正式身份或
物理触板状态均不能靠同步修改账本字段绕过可靠门。同日证据只有 15:00 后才允许冻结。

动作时同帧 `portfolio/portfolio_selected` 最多两只只证明正式输入完整；已观察到的空名单
是完整空输入，组合字段缺失则不生成动作。它不能判断提前动作是否命中原账户，因为尚未
触板的提前候选在同帧本来就不会是正式 `buy_now`。每个完整日改为冻结随后真实到达的
首板和二进三 `buy_now` 正式订单、到达顺序、涨停价和来源帧，并把订单指纹写入日级
cohort。正式账户与提前账户都从空仓开始，按同一两仓现金规则独立重放；原账户身份只认
正式账户实际成交的首板股票日。最终运行不得回读后来变化的历史推荐重建这些订单。

每个模型日固定 `daily_slot=1/2`，模型+日期+槽位和模型+日期+股票均唯一。校准、实时
选择和最终动作集重放共用同一真实到达排序：同股日一次、同帧一个、每日最多两个；任一
缺失、额外或乱序动作均使可靠门失败。

## Frozen stages and acceptance

首批 40 个完整日只拟合，随后 15 日只校准一次阈值，再后的首批 60 个完整日只验证。
模型只能在第 15 个 calibration 日收盘后冻结；validation scope 必须晚于模型冻结且晚于
自身收盘，重复日期、模型前 scope 和第 61 日均不能改变冻结 cohort。
校准没有至少 20 个股票日且正式身份点估计精度至少 70% 时，模型永久拒绝；不得读取
validation 结果重选阈值。

验证未满 60 个完整日不展示绩效。满 60 日后仍同时要求：

- 60 个 validation scope 的完整标签 cohort、日级正式订单投影及指纹、唯一模型记录、
  全部动作决策指纹和完整动作集重放必须逐项一致；
- 每个动作的延迟成交、正式身份、物理触板和 D+1 阶段均已闭合，且官方 D+1 独立重算
  与动作账本逐项一致；
- 每个动作的冻结结算证据及指纹完整，`settlement_evidence_integrity`、
  `delayed_fill_integrity`、`formal_identity_integrity` 和 `physical_touch_integrity`
  四个独立重放门全部通过；
- 至少 60 个官方重算闭合动作、40 个动作日，所有标签以及两套账户 D/D+1 官方行情完整；
- 正式身份精度和原两仓身份精度点估计均至少 70%，且双侧 95% Wilson 下界均至少 70%；
- 可达召回点估计及其 95% Wilson 下界均至少 30%；
- D+1 胜率点估计及其 95% Wilson 下界均至少 60%，平均净收益至少 1%；
- 两仓 PF 至少 1.5、双倍成本 PF 至少 1.2、两套复利均为正、最大回撤不差于 -15%；
- 同一 validation 日期和冻结正式订单重放的联合产品账户，在正常和双倍成本下，胜率与
  复利都不得低于正式账户；最大回撤相对正式账户最多劣化 1 个百分点，PF 至少保留正式
  账户的 95%。正式账户、提前账户和联合账户必须使用相同初始现金、费用、两仓约束和
  D+1 日历，任一同期正式指标缺失即失败；
- 五个连续 12 日块至少四块盈利，单日正利润贡献不超过 15%。

Wilson 门防止最小样本刚好达到点估计就被宣称可靠：`42/60=70%` 的 95% 下界只有
`57.4913%`，`36/60=60%` 的下界只有 `47.3661%`。全部通过也只能生成
`forward_reliable_candidate_for_live_review`，不能自动改正式推荐。归档器必须从指标重算
完整的 `reliability-v8` 门集合；删门、伪造门、重复 validation 日期或任一指纹漂移均拒绝。

`reliability-v8` 在首个合法 scope 产生前由 v7 提升，只增加同期正式账户不劣门，没有
读取前向收益、调整模型或筛选日期，因此不会把 validation 反馈引入合同。

## Shakedown evidence

2026-07-20 共保存 677 帧、204,425 条观察；正式窗口为 522 帧、165,064 条观察，扫描
缺口 P50/P90/max 为 `18.1853/27.7388/105.8185s`。只读重建后的身份母池为
4,956 行/519 帧/29 只，模型向量有限值覆盖 `4956/4956`，概念加速度覆盖
`85.0686%`。20 个首次正式首板事件在前 60 秒的 `>=3%` 观察、成熟历史门和静态 lane
门下依次可达 `8/4/3` 个；严格连续阳性仅华电辽能 7 帧。这些数字只能暴露可达性风险，
不能训练模型或估计胜率。

新日级诊断固定保存正式事件经过“原始 3%、帧质量、新鲜报价、成熟历史、lane 合同存在、
静态门”的 60 秒漏斗和标签覆盖，但不进入模型或可靠门。用原生旧行回放 7 月 20 日得到
`20/8/8/8/4/0/0`；上面的静态 `3` 来自混合 blocker 重建，而原始行没有
`lane_blocker_codes`，两种证据不得混用。

## Post-shakedown capture repair

- 7 月 20 日概念加速度断续缺失的主因已由 Docker daemon 日志直接定位：概念历史全量
  重置点与人工停止并替换 API 容器的时间逐项对齐（10:03、10:20、13:29、13:52、
  14:22、14:30），且同期内核日志没有 OOM 记录。概念加速度只保留进程内最近 16 帧，
  每次重启后必须重新积累约 5 分钟历史；因此该联调日的 85.0686% 覆盖不能代表稳定运行
  能力，也不能归因于市场风格。旧版同步概念调用同时拉长部分雷达间隔，是次要叠加因素。
- 快速涨幅榜固定并发读取 page 1..4、每页 100 只，按页序和 `vt_symbol` 去重。空页、
  非法来源时间或请求异常均记录独立 page source error；四页和涨停池同时不可用时失败
  关闭。合并 payload 的 `updated_at` 取成功页中最早时间，不能用最后完成页冒充整批
  新鲜度。
- 每只股票保留自身 quote known-at：快速页使用所属页时间，全市场补充票使用概念快照
  时间，涨停池独有票使用池时间；观察投影优先行级时间。正常实时帧在行情、上下文等输入
  加载完成后才生成评价时间，避免网络响应发生在帧时间之后。
- 完整日质量改为上午、下午分别计算并取较差窗口，避免午后恢复后的密集帧把上午持续
  慢扫描或字段缺失稀释掉；frame/day scope 新增采集运行实现指纹，指纹失败只关闭研究日，
  不传播到正式实时快照。
- 调度固定为 `LIVE_SCAN_INTERVAL_SECONDS=10`、`SCHEDULER_TICK_SECONDS=2`；页缓存仍为
  10 秒，实际下一次 start-to-start 超过 TTL 后才会取得新页。
- 正式涨幅榜继续读取新浪四页，价格、排序、正式候选和推荐均不使用研究增强。独立东方
  财富四页只向内部 `trace_capture_candidates` 补充涨速、振幅、主力净流入及比例，并保存
  独立 `quote_flow_observed_at`；超过 20 秒、未来时间或无时间戳时模型只读取缺失值。
- 最终统一镜像盘后烟测中，正式新浪和研究东方财富均为 `4 x 100=400` 条、各 400 个唯一
  代码，两源交集 399 只；研究涨速、振幅、主力净流入、净流入率和来源时间均为
  `400/400`。2026-07-20 的 204,425 条旧观察在新增研究时间列上仍全部为空，禁止回填。
  这些结果只证明接口和隔离链路，不计入 fit 日；下一完整交易日仍必须通过原 P90/max
  gap、报价、概念和完整 cohort 硬门。

## How to verify

```bash
uv run --group server pytest tests/alphaagent/test_limit_up*.py -q
uvx ruff check alphaagent/server/services/limit_up/preboard_point_trigger_service.py tests/alphaagent/test_limit_up_preboard_point_trigger_service.py
uv run python -m compileall -q alphaagent/server alphaagent/market alphaagent/data_sources
docker compose config --quiet
```

当前实现入口：

- `alphaagent/server/services/limit_up/preboard_point_trigger_contract.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_dataset.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_model.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_repository.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_settlement.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_service.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_study.py`
- `alphaagent/server/services/limit_up/preboard_point_trigger_worker.py`

冻结 artifact 的实时重建已用多帧、多候选和反转输入顺序逐项核对事件概率、身份分、
Top1/margin/候选数、动作概率和三层模型指纹；实时评分还会在读取 active model 后重算
覆盖完整 artifact 的 `record_fingerprint`，任何漂移均在动作前失败关闭。当前首次事件
标签定向测试为 `40 passed`，点触发与雷达仓储定向回归为 `184 passed`；加入
data-sync worker 后的打板与数据同步组合为 `1207 passed`，另有 1 条既有 Starlette
弃用警告；
Ruff、compileall、`git diff --check` 和
root/deploy 两套 Compose 配置检查均通过。API、data-sync worker 和 point-trigger worker 统一运行
镜像为
`sha256:53ee907c237a1d51e140ef39ea11b74810e66f8e5f1f7d1ee1d7484f3f11929b`，三者重启 0、
OOM false；当前采集运行指纹为
`sha256:4ccbb7635e49ab257da20f991733848a47186ace91e7822be14b6edea5357462`，point-trigger
worker 限制 `0.10 CPU` 且状态为 `not_ready_model_scope`。盘后
公开 `limit-up-live-v15` 递归审计不存在点触发概率、身份分、研究行情增强值或运行指纹；
正式历史无参数入口固定为 `portfolio / next_close`，802 日两仓仍为
`99笔/69.6970%/+171.7614%/-8.3083%/PF 2.8454`。21:30 补偿批次已完整成功、
unfinished job 为 0，四张点触发账本现为 `1/0/0/0`。当前日只有 15:00 后才允许冻结，
盘中手动运行不会把未完成日期永久写成 incomplete scope。严格 D+1 的 D2 禁代和精确
D1 正常闭合均有服务级回归覆盖；报告级反例还锁定收益篡改、错误 D1 日期和未闭合物理
触板阶段均必须拒绝可靠状态。运行库已存在 `capture_runtime_fingerprint`、
`settlement_evidence` 和 `settlement_evidence_fingerprint` 所需列；正式决策投影不读取
研究增强字段。

对 2026-07-21 排除日的 970 帧、277,886 条观察做同源只读重放后，首次事件标签修复前后
分别为 `602` 个已知帧/`170` 个正例帧/`65` 个伪重复事件和 `601` 个已知帧/`53` 个
正例帧/`13/40` 个严格可达首次事件。修复后领先时间 P50/P90 为
`31.5565/52.0809s`。正式 `buy_now` 的持续状态现在按股票日只认第一次事件；同帧不同
股票仍各计一次。该排除日不进入模型，完整证据见
`limit_up_preboard_point_trigger_v9_first_event_label_audit_20260721.md`。

2026-07-21 的不可变 scope 原因码为 `ready_frame_ratio_below_98pct`、
`scan_interval_p90_above_20s`、`entry_window_max_gap_above_60s`、
`concept_acceleration_coverage_below_95pct`、`capture_runtime_fingerprint_missing` 和
`capture_runtime_fingerprint_changed`。日级较差值为 ready `95%`、扫描 P90/max
`69.9095/98.4517s`、概念加速度覆盖 `68.3489%`、运行指纹覆盖 `6.3978%`；上午/下午
帧数为 `260/459`，下午自身 ready `98.6928%`、扫描 P50/P90/max
`11.0012/14.6813/57.8240s`，不能稀释上午故障。正式首板事件漏斗为
`40/23/20/20/16/16/14`（事件/原始 3%/新鲜报价/质量/成熟历史/lane 合同/静态门），只作
采集归因，不进入模型。当前报告仍为 `collecting_fit`、`performance_visible=false`，
绩效、账户和可靠门均为 `null`，最终归档文件不存在。

上午持续慢节拍的根因已由运行库和保留 Docker 镜像交叉闭合。`10:42` 构建的镜像
`sha256:27164ad6...` 实际固定为 `LIVE_SCAN_INTERVAL_SECONDS=60`、
`SCHEDULER_TICK_SECONDS=15`；`10:43..11:30` 共 40 帧的 start-to-start P50/P90 为
`70.613/75.488s`，而单次扫描 P90 仅 `6.624s`，因此约 70 秒缺口来自错误节流，不是
扫描计算、数据库或市场风格。`11:33` 后镜像恢复为 `10s/2s`；`13:01..14:17` 共 411 帧
的间隔 P50/P90 为 `10.799/14.102s`，单次扫描 P90 为 `6.066s`。当前统一运行镜像继续
固定 `10s/2s`，调度测试直接断言这两个值并验证概念刷新不会阻塞实时扫描。该修复不能
追溯挽救已经冻结的 7 月 21 日，只能从下一交易日重新取得首个合法 fit 日。

data-sync worker 的 Compose 健康门已在盘后真实运行：开盘前始终从镜像源码核对
`LIVE_SCAN_INTERVAL_SECONDS=10`、`SCHEDULER_TICK_SECONDS=2` 和
`CONCEPT_REFRESH_SECONDS=30`；盘中再要求实时/概念 schedule 分别在 `60/120s` 内启动，
并检查当日已有雷达帧的指纹非空、格式合法且唯一。worker 暖进程内的本地 `/healthz`
只读取数据库中的现成指纹，不调用完整运行指纹计算；周末跳过心跳，法定休市日不要求
凭空出现当日行情帧，盘后也不因已经冻结的坏日循环报错。Docker 只执行 curl，不再每次
冷启动 Python；真实单次耗时为 `21.5ms`，当前 health 为 `healthy`。

下午概念加速度按合同候选分母重算为 `28,384/31,139=91.1526%`，仍不能单独成为完整
窗口；分段归因显示 13:00 首 10 分钟因进程历史冷启动只有 `36.4510%`，13:10..14:09
连续六个 10 分钟段均为 `100%`，14:18 和 14:27 两次实现切换后对应两段又降到
`94.4994%/94.7194%`。因此稳定进程下字段链路已有超过 95% 的盘中证据，但下一完整日
仍必须以整段窗口实测通过，不能用稳定分段替代日级门。

训练容量已在与 worker 相同的 `0.10 CPU` 限额下做无落库规模基准：40 个合成日期、
20,000 帧、200,000 个候选行的构造、最终事件模型、最终身份排序、四段走步 OOF 和动作
模型总耗时 `442.497s`，分段为 `34.598/34.604/47.397/315.500/10.398s`；三层均为
`ready`。这证明第 55 个完整日盘后的冻结训练可在次日开盘前完成，当前无需改变模型、
阶段或 CPU 隔离。真实 2026-07-20 排除日的只读加载与特征构造耗时分别为
`66.299/46.900s`；其原生行缺少后来新增的 `lane_blocker_codes`，因此训练行严格为 0，
继续按合同失败关闭，不能用重建字段回填。

模型冻结后的实时评分也已按同步热路径做容量上界：在 `0.10 CPU` 下读取真实
2026-07-20 14:00 点的 220 秒因果窗口及既有正式事件证据，共 348 帧、5,416 条观察，
加载/特征构造为 `2.798/0.403s`；冻结 artifact 的记录校验、两个 LightGBM 文本模型重建
和 10 选 1 推理运行 20 次，耗时 P50/P90/max 为 `0.0505/0.0961/0.0994s`。旧采集日自身
扫描耗时 P90 为 `5.5972s`，即使按更低 CPU 上界叠加评分和 2 秒 scheduler tick，仍低于
20 秒完整日门。当前保留同帧保存后同步评分，避免异步队列把动作绑定到错误帧；真实
validation 日仍继续以保存帧间隔而非该基准作为最终质量证据。

排除日和阶段边界由合同单一定义并在仓储、报告、实时评分三层重复校验：任何
`trade_date <= 2026-07-20` 的 scope 写入都被拒绝；冻结模型必须恰好包含日期唯一有序的
40 个 fit 日和其后的 15 个 calibration 日，validation 日期必须为空。最终归档还必须同时
满足 60 个 validation 日、`performance_visible=true`、正确合同/门版本、
`none_research_only`、正式策略未改变、状态为
`forward_reliable_candidate_for_live_review` 且所有可靠门通过；`forward_rejected` 不能归档。

## Open risks and next work

- 2026-07-22 是下一预期交易日；09:00 预检已确认 worker 固定常量为 `10s/2s/30s`、
  两个扫描 schedule 启用且健康。09:15 后仍必须用真实心跳、当日唯一运行指纹和行情帧
  重新证明，盘前模拟不计入 scope。
- 下一完整交易日先审计扫描 P90、报价/概念覆盖、完整候选 cohort 和首个 60 秒标签；
  质量门未过的日期只能排除，不能补洞或回填。
- 下一完整交易日盘中不得为研究开发重启 API；若因真实故障发生重启，仍由既定概念覆盖、
  扫描 gap 和标签完整门决定是否排除，不对当日历史做进程内状态回填。
- 开盘前必须从运行中的 data-sync worker 核对 `LIVE_SCAN_INTERVAL_SECONDS=10`、
  `SCHEDULER_TICK_SECONDS=2` 和非空运行指纹；交易窗口内禁止部署改变采集实现的镜像。
- 当前未解的是三项真实效果：动态市场特征能否识别未来 20..60 秒触板时钟；同刻排序
  能否选中后来正式账户实际成交的首板股票；提前占用两仓后的 D+1 胜率、复利和回撤能否
  通过可靠门。旧分钟/逐笔证据已经否定当时的模型，但不能代替新 10 秒特征的未读前向验证。
- 聚合亚分钟报价不是逐笔委托或 L2，快速封板的排队成交仍只能保守记为未知。
- 未达到 40/15/60 和全部最终门前，不创建
  `limit_up_preboard_point_trigger_v9_forward.{json,md}`，也不使用“可靠”表述。
