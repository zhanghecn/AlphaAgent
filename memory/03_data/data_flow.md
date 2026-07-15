# Data Flow

这个文件只记录当前有效的数据路径和数据口径。旧同步事故、单次生产验证和历史回测状态不要放这里；需要复核旧过程时看对应报告或 git 历史。

## vn.py Data Paths

vn.py 核心把数据分成四类：

- 合约/证券基础信息。
- 实时 Tick 行情。
- 历史 K 线/Tick。
- 财务、基本面、指数成分等研究数据。

实时行情路径：

1. 安装并注册 Gateway 插件。
2. `MainEngine.connect()` 连接。
3. Gateway 查询/推送合约信息，产生 `ContractData`。
4. `MainEngine.subscribe()` 订阅标的行情。
5. Gateway 推送 `TickData`。
6. `OmsEngine` 缓存最新 tick，可通过 `get_tick()` 或 `get_all_ticks()` 查询。

历史数据路径：

1. 安装 Datafeed 插件，例如 `vnpy_rqdata`、`vnpy_xt`、`vnpy_tushare`。
2. 配置 `SETTINGS["datafeed.name"]` 及账号/token。
3. 使用 `get_datafeed()` 获取数据服务实例。
4. 构造 `HistoryRequest`。
5. 调用 `query_bar_history()` 或 `query_tick_history()`。
6. 保存到数据库或 AlphaLab。

相关源码和文档：

- `vnpy/trader/engine.py`
- `vnpy/trader/gateway.py`
- `vnpy/trader/datafeed.py`
- `vnpy/trader/object.py`
- `docs/community/info/datafeed.md`
- `examples/download_bars/download_bars.ipynb`
- `examples/alpha_research/download_data_rq.ipynb`
- `examples/alpha_research/download_data_xt.ipynb`

## AlphaAgent Stock Data

AlphaAgent 自研服务的股票日线同步不走 vn.py Datafeed，路径是：

1. `alphaagent.server.services.data_sync.run_job("sync_stock_daily_bars")`
2. `DataSyncRunner._run_sync_stock_daily_bars()`
3. `AkShareAdapter.stock_bars(..., interval="1d")`
4. 写入 PostgreSQL `stock_daily_bars`

当前有效事实：

- 股票日线优先使用腾讯 `newfqkline` 接口，helper 为 `_tencent_stock_kline_full()`。
- 腾讯成交额字段单位为“万元”，入库前换算为“元”。
- `stock_daily_bars.volume` 常见单位为“手”；旧数据缺 `turnover` 时，量化流动性兜底按 `close * volume * 100` 估算成交额。
- `sync_stock_daily_bars` 支持 `symbols` 定向重跑，也支持增量同步和最近交易日回刷。
- 全市场 `sync_stock_daily_bars` 完成后会检查最新日期横截面覆盖；低于 `max(3000, 上一完整交易日覆盖数*95%)` 的最新日期会从 `stock_daily_bars` 丢弃，等待晚间重试补齐，避免公共源半发布的当日日线污染历史量化。没有上一完整日时才回退到股票清单总数。

## AlphaAgent Sector And Mainline Data

板块日线同步路径：

1. `run_job("sync_sector_daily_bars")`
2. `DataSyncRunner._run_sync_sector_daily_bars()`
3. `AkShareAdapter.sector_daily_bars(...)`
4. 写入 PostgreSQL `sector_daily_bars`

当前有效事实：

- `AkShareAdapter.sector_daily_bars()` 优先使用东方财富 `push2his` 板块 K 线接口，`secid=90.BKxxxx`，helper 为 `_eastmoney_board_kline()`。
- AkShare THS 板块指数函数只作为兜底；Docker x86_64 环境不能依赖 `py_mini_racer` 路径作为生产主路径。
- `sync_sector_daily_bars` 如果对所有板块读取 0 行，会抛 `DataSyncError` 并记录失败，不静默成功。
- `sync_sector_daily_bars` 和 `sync_sector_period_scores` 默认 `sector_limit=0`。当前默认 18:00 定时保留 `sync_sector_period_scores`，`sync_sector_daily_bars` 因公共板块 K 线源覆盖不稳定，不放入默认定时链路，避免每天把批次标成失败；需要时可手动跑。
- `/mainline` 产品口径是“概念主线”，不是行业/板块混排。主线 API 固定只读题材概念，过滤指数篮子、风格、昨日涨停、近期新高等状态类伪概念。
- `sector_period_scores` 历史评分必须只读取 `as_of_date` 当天及以前可回放数据；实时/当日资金流不能稳定回放历史日期。
- `/api/mainline-replay/live` 是盘中概念主线入口，只读实时源表，不写 `sector_period_scores`。
- `/api/mainline-replay/snapshot` 和 `timeline` 只读完整日线日期的概念 `sector_period_scores`。
- `/api/mainline-replay/relation` 使用共同日期价格/资金相关性和完整 `sector_memberships` Jaccard 计算关联概念。
- `/api/mainline-replay/sector-stocks` 在旧历史日期缺日线时不能用当前快照冒充历史价格；只有晚于最新完整日线且存在当日分钟线/资金流的盘中日期可返回 `price_source=intraday_snapshot`。
- `/api/mainline-replay/sentiment-cycle` 是 `/mainline` 情绪周期图数据源：历史点从完整 `stock_daily_bars` 计算涨跌家数、涨跌停、炸板代理、连板高度和晋级率；盘中点仅在可用时用 `stocks` 快照和 `stock_minute_bars` 高点作临时投影，不写回 `sector_period_scores`。

数据维护风险：

- 同步写库通常是 upsert，不是全量清库重建；旧来源行、旧成员关系和已生成派生评分不会自动消失。
- 规范板块日线来源是 `eastmoney.board_kline`。历史旧来源行如果未被同一主键覆盖，可能继续影响 `sector_period_scores`。
- `sector_memberships` / `shenwan_industry_members` 是快照关系；同步成功后应清理本次源结果已不存在的旧成员，并重建反向索引 `stock_sector_memberships`。
- `sector_period_scores` 是派生结果；上游日线、成员或个股日线口径改变后，必须按受影响日期/period 删除或覆盖重算。

## Minute Data

`sync_stock_minute_bars` 是分钟线同步主入口。普通量化历史主流程不依赖分钟线；`/limit-up` 的首板点时账本在事件原始分时路径缺失时，会把已落库 1 分钟线作为盘中承接回退证据。

模式：

- `mode=recent`: 同步近端分钟 K 线。
- `mode=backtest_gaps`: 兼容旧严格分钟报告或未来盘中确认，可按回测缺口补执行日快照。
- `provider=tdx`: 使用 TDX 公开行情读取真实历史 `1m`，回溯范围有限。
- `provider=tushare`: 使用 Tushare Pro `stk_mins`，需要 `TUSHARE_TOKEN` 和分钟数据权限。
- `dry_run=true` 默认只预检查/读取，不真实写入。

约束：

- 普通量化历史主流程不依赖 14:30/分钟线；`/limit-up` 回退只为缺少原始分时路径的事件批量取数，原始路径不得被替换。
- `/limit-up` 的 09:30/13:00 网格点使用 09:31/13:01 首根 bar 开盘价，其余网格点使用对应分钟收盘价，再以 D-1 收盘转换涨跌幅；信号特征只读取信号时点及以前，至少 6 个有效点，否则继续拒绝。
- 旧严格分钟缺口补数统一只支持 `1m` 快照；通用分钟 K 线导入可保留多周期供行情查看。
- AkShare/东方财富公共分钟线可用于近端日期，但不能视为覆盖长历史严格回测缺口的数据源。
- 当日分钟线增量如果本地已有当天部分 bar，不推进到下一交易日；仍刷新实时分钟窗口并用 upsert 去重，避免 14:30 后无法补齐 15:00 前后数据。

## Batch Sync And Health

统一批量定时同步使用 `sync_batch_schedules`，默认由
`alphaagent/server/services/data_sync.py` 的 `DEFAULT_BATCH_SCHEDULES`
写入/更新数据库：

- `tail_quant_1430`: 14:30 实时尾盘量化结果；只跑分钟线、个股/板块资金流和热度等快任务，然后生成缓存，不跑慢的全 A `sync_stock_list`。
- `eod_18h`: 18:00 盘后慢数据维护，只跑股票/板块清单、资金流、涨停池、龙虎榜、公告和财务等增强数据；不跑股票日线、指数日线、板块周期评分或真实盘后量化，避免 18:00 公共行情源半发布时重复抓取和污染候选。
- `eod_finalize_2130`: 21:30 晚间日线补全，只跑股票日线、指数日线、板块周期评分和真实盘后量化；用于处理公共行情源盘后稍晚才全量发布当日日线的情况。
- 自动盘后真实量化默认只生成最新完整交易日的候选，不能无参补全全历史；历史候选补齐必须显式传 `start`，避免定时任务为了当天结果跑 200+ 历史交易日并超时。

启动种子逻辑只保留当前默认三档定时；已废弃且禁用的旧盘中缓存 schedule 会被删除，避免页面或接口继续露出与 14:30 实时尾盘量化不一致的半成品配置。若旧批次的 `partial` 汇总数量和当前 `job_ids` 数量不一致，启动时会清空该过期状态，避免配置变更后继续显示旧失败。

批量执行按 `job_ids` 顺序串行，单任务失败不再中止整批；基础任务失败时下游会跳过。日 K/分钟 K 内部按股票并发增量续传；当日分钟线增量不向 AkShare 传当天 `start_date`，改用实时分钟窗口后由本地 upsert 去重，避免 14:30 走历史分钟接口返回空结果。日 K/分钟 K 的单股超时只允许跳过读取，超时线程晚返回后不能继续写库，避免旧同步线程挤占连接池或污染后续量化。`tail_quant_1430` 会把最新成功量化信号池注入给 `sync_stock_minute_bars`，定向同步候选股分钟线，而不是默认按成交额前 100 只随机覆盖。14:30 档默认并发降到 6，API 数据库连接池默认提高到 `20 + 20` overflow、60 秒等待，降低同步/策略研究并发时的 QueuePool 超时风险。

数据健康入口：

- `GET /api/data-sync/health`: 数据健康和推荐同步。
- `POST /api/data-sync/batches/run-all`: 批量同步，可传 `job_ids`。
- `/data` 默认应优先展示数据健康/同步状态，而不是要求用户理解底层 job。

## Limit-up Research Data Path

`/limit-up` 是独立的实时打板决策和历史研究路径，当前不接券商自动执行：

1. `stock_events` 读取 `limit_pool_zt / limit_pool_zbgc`，同股同日只保留最后采集状态；每条事件必须与同股同日的 `stock_daily_bars` 最终价格和涨跌幅一致，否则剔除，避免错期快照污染研究。
2. 只保留沪深主板非 ST 的 10cm 股票，排除创业板、科创板、北交所、新股/特殊股和退市整理。
3. `stock_sector_memberships` 只取 `theme / industry`，并过滤指数、风格、财务状态和昨日表现等伪题材。
4. `sector_fund_flows` 提供热门板块资金，`stock_fund_flows` 提供个股资金，日终封单/换手用于盘后证据展示。
5. 实时概念横截面固定读取最近一个 `snapshot_date < D` 的题材成员版本；股票可以同时属于多个有效概念。所有沪深主板非 ST 的 5% 雷达股票先附加实时概念强度、扩散、加速度和概念龙排名，再按情绪、涨停基因、位置、资金、量能、换手、距板和封板质量评估；Top5 与两仓只在评估完成后排序，不再作为信号计算前置门槛。历史缺少点时概念快照时继续明确使用代理，不用日终结果补算当时概念强度。
6. `stock_daily_bars` 提供涨停价代理和 D+1 开盘/收盘退出价。
7. `limit_up_signal_snapshots` 按分钟保存实时审计，同一分钟内 15 秒扫描更新最新 `captured_at`；独立的 `limit_up_live_trace_snapshots` 从主板涨幅 5% 开始追加概念预热、接近、触发、错过、封板、炸板和硬门证据。`limit_up_concept_scan` 每 30 秒并发获取完整 A 股行情并与 15 秒强势股/涨停池增量合并，所有主板非 ST 的 5% 雷达先完成概念和战法评估，再取动态 Top5、两仓和最多 6 条观察。09:15-09:59 及竞价阶段只允许观察；10:00 后首板按既有触板规则，二进三按新鲜首次触板/可观察回封规则转为 `trigger_ready`，执行许可仍固定为 `research_only`。第一次采到时已经封死且此前无封板前帧的股票标记为错过，不事后补买点。行情日期错误、概念覆盖低于 90%、完整概念帧超过 45 秒或快照过期时禁止新买点。候选保存封板资金和相邻快照变化；连续快照间隔超过 2 分钟不累计稳定时间，封单缩水超过 30% 关闭动作。缺 Tick/L2 时执行可信度固定为 `proxy_without_l2`。
   D-1 弱势只决定日内市场门从 `pending_repair` 开始；一次完整修复证据把它推进为 `repair_confirmed`，健康的零增量快照不会关门，封板少于 5 只、炸板率高于 35%、快照过期或日期错误才进入 `repair_revoked`。结构硬伤输出 `rejected`，市场/热度/扩散/资金/换手等可变化缺口输出 `observing / approaching_trigger`，未触发便封板输出 `missed`。
   同表仍复用 `next_session_preliminary / next_session_final` 保存盘后观察；首板不再生成一进二计划，二板结构可形成目标三板观察，高板只保留研究。竞价阶段不买，下一交易日 10:00 后只有首次触板或可观察回封才能进入综合候选。盘后、周末和盘前 `GET /live` 会附加 09:55 提醒、两段连续评估和 D+1 14:30 退出日程。
8. 严格时点证据分别写入 `stock_sector_membership_snapshots`、`limit_up_concept_strength_snapshots`、`sector_fund_flow_snapshots` 和 `stock_auction_snapshots`。19:00 成员反向索引重建成功后才冻结当日完整版本，空来源不会再先清空上一版；D 日概念扫描只读取更早版本。概念强度表按分钟保存 Top30、包含 5% 雷达或进入预热/启动/退潮状态的概念，并保留 120 个交易日。每次“即时”板块资金同步都按分钟追加主力净流入、超大/大/中/小单、来源时间和涨跌家数，资金加速度可由相邻快照计算，扩散宽度直接使用当时上涨/下跌/平盘家数。09:26 竞价表保存开盘价、撮合量额、未匹配量和字段完整度；公共源没有未匹配量时只算部分证据，不能开放模拟。
9. `limit_up_history_replays` 以 `(trade_date, strategy_version)` 保存逐日点时账本；当前 `limit-up-history-v15` 覆盖 `2024-01-15..2026-07-15` 共 603 个可靠交易日。活跃候选池只包含首板、二进三和高板，一进二及 `target_board=2` 不再生成。接力的 D-1 观察资格与 D 日触发分开保存：窗口内首次触板可直接触发，10 点前触板必须有窗口内回封路径；缺事件、无回封或窗口外触板都进入覆盖审计而不成交。产品回测加载完整 `candidate_pool.first_board/two_to_three`，按 `buy_time` 和同刻接力优先级推进，禁止用日终 `selected` 反选。D+1 14:30 价格批量读取 `stock_minute_bars`，缺失时标为 `daily_close_proxy`；跌停锁死按账户规则延后。`eod_finalize_2130` 只在最新完整日线日推进后串行全量重建。
10. `limit-up-walk-forward-v6` 只为首板、二进三和高板保留活跃模型合同；传 `lane` 时消费对应 `board_candidate_pool`。窗口按完整交易日历推进，首板特征包含信号前 15/30 分钟承接、回撤和攻击速度；触板事件池不强拟合一类全真的成交标签，`fill_probability` 留空并由 Tick/L2 门禁独立控制。每条战法每日最多 1 只，单窗训练样本低于 300 时返回 `insufficient_training` 并空仓。
11. `forward_validation.py` 只消费交易时段真实保存、`live_snapshot`、非 stale、采集日与交易日一致的快照；历史代理、周末和无效时段只进入排除统计。实时链路先做历史负期望否决，再把门禁前研究动作保存为 `research_action`，最后将未验证战法的用户动作 `action` 降为 `pass`。前向账本只读 `research_action` 并标记 `saved_research_action_not_executed`；普通严格动作回测仍只读 `action`，不能把研究观察冒充执行。老快照没有 `research_action` 时兼容回退到原 `action`。第一笔盘中动作不可被后续快照改写，明早竞价只取当日最后有效计划，D+1 使用明确交易日历闭合。
12. `live_evidence.py` 为实时推荐和无严格快照的历史代理附加同路径成熟样本，只允许 `result_date < signal_date` 的闭合结果进入统计。样本不少于 60 笔且平均净收益非正、收缩胜率低于 40% 或硬亏损率不低于 20% 时，只否决 `buy_now / next_auction`，不以正样本直接证明可交易。证据同时生成透明的 `TBOX 0..100`：历史平滑胜率 35 分、平均 D+1 25 分、硬亏控制 20 分、触板封住率 10 分、样本可信度 10 分；缺失项不得分。证据查询失败时，历史代理保留原信号并写入 `data_quality`；实时快照必须 fail-closed，把 `buy_now / next_auction` 降为 `pass` 并显示“证据不可用，已禁止执行”。已经保存的严格历史快照仍原样返回，不能事后回填证据或改写动作。
13. 产品实时组合和历史账户共用 `limit-up-scheduled-v4`：首板和二进三共用最多两只、每只目标 50% 的连续盘中队列，D+1 14:30 退出；同刻接力优先，异时先到先买，不预留仓位。实时证据版本为 `limit-up-live-v6`。概念绝对共振、首板行业 OR 概念门和弱市题材进攻规则保持不变；二进三必须同时有 D-1 资格、窗口内新鲜触板/回封和实时动态门，竞价不得产生买点。高板只在独立研究数据中保留，不占产品仓位。历史账户明确是缺少逐帧资金门的 `candidate_proxy_only`。

实时/事件接口为 `GET /api/limit-up/dates`、`GET /api/limit-up/dashboard?date=`、`GET /api/limit-up/live`、`POST /api/limit-up/live/refresh` 和 `GET /api/limit-up/signals?date=&as_of=`。两日逐次诊断读取使用 `GET /api/limit-up/live-traces/dates`、`GET /api/limit-up/live-traces/day?date=` 和 `GET /api/limit-up/live-traces/symbol?date=&vt_symbol=`；读侧按新增行增量聚合，股票跌出 Top5 后仍保留 `concept_warming / dropped_from_top5 / rejected / missed / sealed / failed / invalidated` 等变化。自动调度和数据管理页的手动“立即执行”复用 `limit_up_live_scan`；完整概念刷新由 `limit_up_concept_scan` 独立调度，手动接口分别为 `POST /api/data-sync/schedules/limit_up_live_scan/run` 和 `POST /api/data-sync/schedules/limit_up_concept_scan/run`。只有 live、非 stale 的有效结果返回 `succeeded`，其他结果返回 `skipped`，盘后不会伪造概念强度行。严格前向接口为 `GET /api/limit-up/forward-validation?start=&end=&entry_mode=&exit_mode=`；数据门禁接口为 `GET /api/limit-up/data-quality`。兼容同步补数接口为 `POST /api/limit-up/data-quality/minute-backfill`；产品入口使用 `POST /minute-backfill/start` 立即返回 `202` 和批次 ID，再每 2 秒读取 `GET /minute-backfill/batches/{batch_id}`，终态后刷新门禁。全历史接口为 `GET /api/limit-up/history/status`、`POST /api/limit-up/history/rebuild`、`GET /api/limit-up/history/dates`、`GET /api/limit-up/history/day?date=`、`GET /api/limit-up/history/backtest?entry_mode=auction|sweep|tail|next_auction`、`GET /api/limit-up/history/factors?entry_mode=&exit_mode=&start=&end=` 和 `GET /api/limit-up/history/model-report?entry_mode=&exit_mode=&start=&end=`。

历史事件/竞价证据可在 `/data` 的“打板证据”页通过 Tushare 或完整 CSV 回补。接口为 `GET /api/data-sync/imports/limit-up-evidence/status`、`GET /template.csv?dataset=events|auction`、`POST /tushare` 和 `POST /csv`。事件导入把 `limit_list_d` 的首封、末封、开板次数、封单额和连板数规范到现有 `stock_events`；竞价导入把 `stk_auction` 的价格、成交量额、昨收、换手和量比写入 `stock_auction_snapshots`。导入先用本地日线构造当日预期触板/交易股票集合，事件覆盖至少 90%、竞价至少 95% 才允许逐日原子替换；空响应、跨日期、非主板/ST、字段错误和覆盖不足都只进入审计结果。`captured_at` 是真实导入时间，`source_updated_at/source_quote_time` 才是行情时点，不得把盘后历史导入冒充当时实时采集。Tushare 竞价没有未匹配量，导入后也只能算部分证据。

同页的“同花顺近252日”只回补涨停/炸板事件：`POST /api/data-sync/imports/limit-up-evidence/ths/start` 立即返回后台批次，页面每 2 秒读取 `GET /ths/batches/{batch_id}`，刷新后也能恢复最近批次。供应商行来自 `ths.limit_up_pool/open_limit_pool`，规范化首封/末封时间、连板数、开板次数、封单额和盘中路径，并复用同一个 90% 逐日原子替换门槛。当前真实覆盖 `2025-06-27..2026-07-10` 共 252 个事件日、19,978 条事件；该公开接口上限是近 252 个交易日，不得称为 500 日全历史。

逐日申万二级行业成员也在同一页面回补，接口为 `GET /api/data-sync/imports/limit-up-memberships/status`、`GET /template.csv`、`POST /tushare` 和 `POST /csv`。Tushare 路径先取 `index_classify(SW2021, L1)`，再按一级行业完整读取 `index_member_all`；CSV 使用相同区间字段。有效期固定为 `in_date <= trade_date < out_date`，重叠区间选择最新 `in_date` 并记录冲突。每个可靠交易日必须覆盖至少 90% 的当日沪深主板非 ST 日线股票才只替换该日 `sector_type=industry`，同日概念快照不会被删除；空响应、供应商错误和覆盖不足不写库。历史账本优先按 `snapshot_date + vt_symbol` 读取行业，缺失行才回退当前成员并标记 `current_proxy`。

前端实时视图每 10 秒读取 `/live`，任何 GET 都不直接访问外部行情源或写快照。页面只保留实时推荐、历史交割单和回测三个主入口，不显示板位执行切换；首板和二进三仍呈现为一个综合推荐。实时操作列表只展示仍可转买状态，`rejected / missed / invalidated` 只留轨迹；前端还会过滤旧缓存中的一进二。候选掉出 Top5 后仍保存触发、封板、炸板和失效历史。盘后显示下一交易日 09:55/10:00 日程；全页快照超过 90 秒 fail-closed，买点快照超过 20 秒先单独失效。实时 signal 原样透传点时价格，禁止用后续或最终封板结果回填。

买点声音和桌面通知是浏览器本地辅助功能，不改变 signal、快照、交割单或回测。用户必须通过铃铛按钮主动启用，`trigger_ready/actionable` 首次进入时提醒，同一股票离开后超过 60 秒重新触发才可再次提醒；stale、历史代理和盘后计划不提醒。扬声器按钮复用真实提醒链路作手动测试，但不写后端数据。页面完全关闭后当前版本不具备 Service Worker/服务端推送；通知权限被拒绝时仅保留声音和页面 Toast。

`data_quality.py` 把研究账本和执行证据拆成 8 个独立门禁：点时历史账本、涨停事件路径、逐日行业成员、个股分钟路径、集合竞价、板块分钟资金、Tick/L2 队列和 60 日真实前向观察。门禁只读取真实落库计数；逐日行业先要求本地全市场日线至少 3000 只来确认日期可靠，再要求行业快照覆盖该日实际沪深主板非 ST 股票的 90%，并分开展示原始、行业、概念和合格快照日。板块分钟资金只统计交易时段、来源日期等于采集日且主力净流入非空的快照，竞价同时展示采集日和字段完整日。当前成员快照、覆盖不足的行业日、日终板块资金、公开源缺未匹配量的竞价或日线开盘代理都不能冒充严格证据。只有全部门禁达标时 `simulation_eligible` 才能为 `true`。

分钟补数只查询沪深主板非 ST/退市/特殊状态且尚无任何本地 1 分钟数据的涨停事件股票-日期对，按最近交易日优先；创业板、科创板和北交所不进入事件总量、板块扩散、覆盖率或补数队列。事件门禁按 `vt_symbol + trade_date` 选择最后一次盘中状态，并要求同股同日存在日线；重复盘中快照和休市日原始记录保留审计，但不重复计数。产品后台入口和 `sync_limit_up_event_minutes` 夜间任务默认 200 个；夜间任务排在 21:30 盘后量化之后。全局已有无关同步批次时产品接口返回 `409`，同一目标批次则复用，不能因 HTTP 超时重复启动。TDX 固定读取 `09:15-15:00` 整日 `1m` 路径；单股瞬时错误会断开并重连重试一次，全批最多重连 3 次；写入后重新查询本地分钟表作为覆盖判据。`limit_up_minute_backfill_attempts` 按股票、日期和 provider 保存 `covered / empty / error`、尝试次数和下一重试时间；第 1/2/3 次及以后失败分别冷却 1/3/14 天。2026-07-12 同花顺事件导入后，有效事件路径为 252 日、19,978 个股票-日期对，本地分钟覆盖 `2,215/19,978 = 11.0872%`；尝试账本为 `1,928 covered / 0 empty / 0 error`，其余事件对尚未进入补数尝试。个股分钟日期仍只有 `2026-02-03..2026-07-10` 共 55 日；11.0872% 只是事件对路径覆盖，不是成交成功率，也不能解除 500 日模拟门禁。

AkShare/东方财富 `stock_zt_pool_em + stock_zt_pool_zbgc_em` 只适合近期缺口恢复。2026-07-12 实测服务端仅 `2026-06-22..2026-07-10` 返回数据，更早交易日返回空池；近期逐日与本地日线触板集合的主板覆盖为 `94.8454%..98.6111%`。它不能承担 500 日历史回补，也不能用空表证明当日没有事件；同步空响应现在保留旧事件，不再先删库。全历史严格入口仍是 Tushare `limit_list_d` 或覆盖完整的 CSV。

顶部事件日期列表的历史部分使用 `stock_daily_bars` 交易日历过滤周末、非交易日和异常快照；日线尚未收盘落库时，只允许“今天采集、`live_snapshot`、非 stale”的已验证当日快照临时进入。非交易时段会保留当日供复核但把动作降为 `pass`；旧快照日期无效时会校正到最近已验证交易日并标记 stale。600 日账本逐日只使用信号时点可见字段，历史相似样本只有在 `result_date < signal_date` 后才成熟；最终封板和 D+1 只进入结果栏。无严格快照的历史代理会展示该日当时可用的成熟样本胜率、平均净收益、硬亏率和样本数，但仍标记为未证明成交。`history/factors` 只审计每日 Top5 候选的 D/D+1 结果，不把候选冒充成交；因子按滚动样本外排序，锁定留出只验证方向，不能回灌排序或阈值。秒板封死不能视为成交，尾盘日线只能给出“假设可成交”的观察值且不计入主收益；逐日行业读取已支持点时快照，但当前尚未导入任何合格历史日期，现有账本仍会标记当前成员回退和幸存者风险。详细基线见 `memory/06_backtests/limit_up_top5_mvp.md` 和 `memory/06_backtests/limit_up_short_term_factor_research.md`。

`history/model-report` 即使选择了较晚开始日，也会从账本起点保留前置训练上下文，只在展示和绩效层裁剪日期。每个窗口分别返回 63 日拟合校准诊断和未参与拟合的测试预测校准；顶层 `calibration` 固定读取锁定留出测试预测，留出标签不参与训练、校准器或门槛。报告缓存 1 小时，历史账本重建后清空。缺 Tick/L2 和逐日行业成员时 `simulation_eligible` 固定为 `false`。

严格前向观察以 20 个有效交易日做流程检查、60 个有效交易日做策略复核；未闭合时胜率、平均收益、复利和回撤必须为 `null`。Tick/L2 队列证据补齐前，即使有闭合价格结果，`simulation_eligible` 仍固定为 `false`。

后端 `live_policy.py` 仍生成多通道内部研究动作和结构化触发检查，夹板、回马板、弱转强突破、龙首阴接力、龙头弱转强、反核板只解释形态。产品层在研究评估之后应用 `scheduled_execution.py`：只取首板 `research_action=buy_now`，最多两只，在窗口内输出 `trigger_ready / research_only`，窗口外改为观察，D+1 卖出纪律固定为 14:30。旧分板位验证门不再把已经满足产品时钟的人工研究买点隐藏为普通观察；自动执行资格仍由 Tick/L2 和冻结后前向门禁控制。

产品组合不使用逐笔动态退出。`lane=portfolio` 固定返回首板+二进三两仓、D+1 14:30 的 `scheduled_unified_intraday_cash_replay`，并附四个冻结组合的同口径门结果；用户选择日期只裁剪范围，不重新选择仓位或时间。一进二接口返回 422；高板和旧动态退出只保留独立研究。

## Quant Data Path

`/quant` 候选和回测核查使用 AlphaAgent PostgreSQL 业务表，不走 vn.py Datafeed。

核心表/接口路径：

- `stock_daily_bars`: 本地真实交易日和日线。
- `quant_signal_runs`: 每次筛选运行。
- `quant_recommendations`: 候选 TopN。
- `backtest_signal_events`: 理论 BUY/SELL 信号计划。
- `backtest_orders` / `backtest_trades` / `backtest_daily_equity` / `backtest_daily_positions`: 真实组合执行账本。
- `GET /api/quant/trading-dates`: 本地真实交易日范围。
- `POST /api/quant/research-runs`: 刷新候选并研究。
- `POST /api/quant/screen-runs/range`: 补齐区间候选。
- `GET /api/backtests?run_type=portfolio`: 组合回测列表。
- `GET /api/backtests/{id}/candidate-trace`: 单股单日候选、计划、订单和成交链路。
- `GET /api/backtests/{id}/candidate-trade-quality-report`: 候选独立买卖质量报告。

当前产品口径：

- 普通量化产品路径只公开 `mainline_dragon_pullback`。
- 日线筛选、组合回测、查询复核和策略回放构造 `Bar` 时都保留 `stock_daily_bars.turnover_rate`；`Bar` 继续保持原有 `change_pct` 位置参数顺序，避免旧调用静默错位。
- 历史量化、历史候选缓存、默认 `/quant` 候选展示和自动买入只使用完整日线交易日；`stock_daily_bars` 当日只有部分股票覆盖时不能作为收盘历史结果，也不能复用已落库的半截日线 run。
- 最新完整交易日的 `quant_signal_runs.params.daily_symbol_count` 必须与当前日线覆盖数一致；缺失该字段或覆盖数不一致的最新日旧 run 不能复用，日线补全后要重新生成候选。
- `GET /api/quant/trading-dates` 同时返回本地最新有记录日期和 `latest_complete_trade_date`。前端历史候选和策略研究截止日期必须优先使用 `latest_complete_trade_date`。
- 当日 14:30 结果走 `GET /api/quant/tail-preview`，用最新完整日线作为基准、叠加当日分钟线/快照临时 K 线，只读缓存，不写入 `quant_signal_runs` 或历史候选。
- 候选质量主口径是全历史交易日每日 Top5/Top10/Top20，D 日 BUY 候选按 D 日收盘价买入，D+1 收盘收益作为主胜率和主收益；D+2/D+3 是否值得格局只作为辅助标签。
- `GET /api/backtests/{id}/candidate-trade-quality-report` 会按买点区域、金/银手指窗口、行情阶段、月份、重点区间和 D+1 涨跌形态分桶；`alphaagent/server/services/backtest/tail_entry_next_day_label.py` 负责生成只读标签。
- 组合模拟只按候选排序、D+1 执行价、涨跌停、现金、组合上限和当前卖点生成真实成交流水；组合层不能反向解释候选质量。
- 股票详情页 K 线标记优先来自当前公开策略对该股的独立复盘；组合真实成交只作执行层复核。

## Financial Visibility

股票详情页和回测评分共用 `alphaagent.server.services.quant.financials` 的历史可见性口径：

- `financial_coverage_summary(session, vt_symbol, trade_date)` 返回本地财报数、回测可用数、缺披露日数、晚于回测日披露数、最新披露日和最近可用报告日。
- `financial_scores_from_rows_by_symbol(rows_by_symbol, trade_date)` 只使用 `publish_date <= trade_date` 的第一条本地财报打分。
- 股票详情页看到“现在可查”的财报，不代表历史回测当天可用；页面必须显示财报口径说明。

## DataManager

vn.py DataManager 仍是官方历史数据 GUI 能力，依赖已配置 Datafeed 或能提供历史数据的 Gateway。

相关文件：

- `docs/community/app/data_manager.md`
- 插件：`vnpy_datamanager`
