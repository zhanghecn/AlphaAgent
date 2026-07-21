# Data Flow

## Current State

AlphaAgent 的自研 A 股数据主要由 `data_sync.py` 通过 AkShare、东方财富、
腾讯、TDX 和可选 Tushare 适配器写入 PostgreSQL；这条路径独立于 vn.py
Datafeed。vn.py Datafeed/Gateway 仍可作为后续正式数据和交易插件入口。

## Daily Bars

`sync_stock_daily_bars` 的路径：

1. 读取全市场股票清单或显式 symbols。
2. 普通增量刷新默认请求 250 根；仅全市场、非定向、增量运行在可靠历史不足 750 日时
   自动请求 800 根自举。
3. 优先通过腾讯复权 K 线获取股票日线。
4. upsert 到 `stock_daily_bars`。
5. 15:05 前的当天盘中日 K 保留但不计入研究；收盘后仍低于上一完整日 95% 或
   3000 只的局部发布日会被丢弃并等待重试。

可靠完整日必须满足至少 3000 个不同股票。共享库截止 `2026-07-20` 有 802 个可靠日，
范围 `2023-03-28..2026-07-20`；当前 `limit-up-history-v15` 账本已增量到 802 日。
规则说明中的 800 日长期指标仍是截止 `2026-07-16` 的冻结参考报告，不能与动态账本
混算。策略规则和阈值仍保持冻结，不因共享历史加深而自动重调。

## Concepts And Mainline

- 概念/行业清单写入 `sectors`，成员写入 `sector_memberships` 和反向索引。
  `sync_sector_members` 落实既有 7 天 cadence：只向东方财富请求没有成员或已过期的板块，
  新鲜板块从本地表复用并继续生成当日因果成员快照；人工传 `refresh_days=0` 才强制全刷。
  同一工作线程复用 HTTPS Session，成员按 500 行 PostgreSQL upsert，不再逐成员查询再写入。
  2026-07-20 真实库为 994 个板块，其中 991 个直接复用，只有 3 个长期无成员的报告板块
  仍进入失败重试，远程请求范围比原全量路径缩小 99.7%。
- 日线、资金和点时资金快照分别写入 `sector_daily_bars`、
  `sector_fund_flows`、`sector_fund_flow_snapshots`。
- `sync_sector_daily_bars` 手动/历史自举默认请求 800 根、最多 1,000 根；每个板块一次
  bulk upsert，正式板块日线只接受东方财富 `90.BKxxxx` 官方指数，数据库规范标签为
  `eastmoney.board_kline`。历史 K 线主机全部失败或返回 HTTP 200 空 `klines` 时，只允许
  用同一板块的东方财富收盘快照恢复一个已完成交易日；raw 明确保存
  `source_detail=eastmoney.board_quote_daily`、源时间和前收。盘中未完成、代码错配、
  OHLC 不一致或非官方来源全部拒绝。19:00/21:30 已获得历史后只为 concept/theme 请求
  最近 30 个时段，不每日重建 800 日历史。
- 低吸、打板和主线共享原始 `sector_daily_bars`，但策略候选、规则和绩效不共享。
- 低吸按每个板块首末官方指数动态计算 D 日有效概念分母；至少 300 个有效概念且
  横截面覆盖不低于 90% 才是完整日。截止 `2026-07-20` 已有 802 个完整日，范围
  `2023-03-28..2026-07-20`；完整日最低动态横截面覆盖为 `99.7567%`。
- `2026-07-18` 的修复前正式任务 `run_id=1235` 曾得到
  `0 行/0 请求失败/498 空响应/0 写入`。根因是历史 K 线 CDN 拒绝连接后，旧适配器把
  `push2delay` 的 HTTP 200 空数组当成成功。修复后正式任务 `run_id=1237` 读取并写入
  495 条 7 月 17 日官方收盘快照；其余 3 个是 7 月 18 日新出现、没有 7 月 17 日行情的
  年报事件板块。已用原先唯一成功的 `BK0949` 逐字段证明备用快照与历史 K 线的
  开高低收、成交量、成交额和涨跌幅完全一致；没有使用成分股聚合或同花顺替代指数。
- `/api/mainline-replay/*` 固定以题材概念为产品口径。
- 历史快照只读取查询日及以前可见数据；盘中投影不能覆盖历史结果。
- 点时成员快照用于避免用今天的成分解释过去。
- 官方概念指数只能计算板块主升，不能证明 D 日成员；低吸正式 Top3 仍要求开盘前
  点时成员。东方财富同一 `concept` 类型还混有“昨日连板”等事件风格板块，产品层
  需要独立题材资格规则。

## Minute Data

`sync_stock_minute_bars` 的产品入口只接受 `mode=recent`，由系统数据源同步近端分钟 K 线。
涨停事件的历史分钟缺口由数据库覆盖审计自动生成结构化股票/日期要求，再交给
TDX、Tushare 或 AkShare provider；不接受 CSV、服务器文件路径、缺口清单文件或
`backtest_id`。公共近端源不能冒充长历史覆盖；供应商不可用或返回不完整时保留缺口，
质量门禁继续关闭。涨停事件分钟补数使用独立退避账本和主板合格股票池。

打板分钟同步保留四个数据库派生任务；事件路径和 3% 雷达前向验证属于自动链路：

- `sync_low_suction_forward_ma5_minutes` 只读取严格前向 MA5 账本中
  `signal_eligible=true` 的股票/信号日，跨身份模式按股票/日去重，通过免费 TDX 补
  `09:35..15:00` 的 48 根 5m 路径。它不扫描全市场、不读取 Tushare token、不生成
  推荐或订单；当前真实账本 0 个信号，dry-run 正确返回 0 对/0 写入。
- `sync_limit_up_event_minutes` 按涨停事件的信号日补 `09:15..15:00` 完整路径。
- `sync_limit_up_radar_minutes` 只读取新鲜、同源日有效的 3% 雷达帧，同股同日去重后
  补 `09:15..15:00` 的 240 根 1m 路径。239 根仍是缺口；作用域固定为
  `tdx_radar_3pct`，不插值、不切换替代供应商。19:00 和 21:30 各限 300 对。
- `sync_limit_up_preboard_hazard_minutes` 是数据管理中的手动有界研究任务，不加入
  19:00/21:30 默认链路。它只补同股前序 D+1 样本至少 5、联合率至少 30% 的静态
  `>=3%` 母池，并在写入后按 240 个官方分钟槽位复核。2026-07-19 六批共写入
  2,686,800 根真实 TDX 1m，最终覆盖 `12,187/12,187`；无缺失、部分或非法股票日。
  TDX 分钟线不是 Tick/L2，不能提供排队、撤单或秒级成交。
- `sync_limit_up_preboard_transaction_features` 只对冻结的共用首板母池抓取 TDX 历史逐笔，
  按完整分钟聚合 9 个资金流特征并以输入 SHA256 不可变保存；当前 89 日范围
  `962/962` 股票日 `flow_ready`，22,821 个共用前缀中 22,804 个可评分、17 个显式
  `causal_no_action`、数据缺失 0。TDX `get_transaction_data()` 当日接口已实测可用，但
  当前 live 推荐未接入；返回时间只有分钟级，且没有委托、撤单、排队和 L2。
- `sync_limit_up_exit_minutes` 是手动研究任务，合并两类旧 14:30 请求：
  `limit-up-history-v15` 持久化候选池通过
  `scheduled_execution.extract_scheduled_orders()` 派生的研究通道 D+1，以及
  `limit-up-live-v15` 真实保存的全部 `actionable_recommendations`。实时推荐只有在本地
  日线已经出现下一交易日后才生成退出请求，不猜测周末或节假日。
- 合并请求先排除已有精确 14:30 行，再从 TDX 请求 `14:30..14:30`；同股同日多个快照
  自动去重，正式推荐不受两仓 `portfolio` 限制。
- 三者共享进程锁但重试作用域分开：事件路径为 `tdx`，3% 雷达为
  `tdx_radar_3pct`，候选卖出价为 `tdx_exit_1430`。下载返回行不等于覆盖；雷达必须
  二次核验 240 根，候选卖出价必须二次查到精确 14:30 行才记为 covered。
- `limit-up-scheduled-v9` 正式账户不读取上述 14:30 研究价。它执行首板和二进三，
  直接读取 D+1 官方日线 `close_price`，缺少或非正数时剔除；当前正式回放覆盖
  `168/168`，不使用其他价格替代。

## Scheduling

允许的 action：`sync`、`limit_up_live_scan`、
`limit_up_concept_scan`、`low_suction_swing`。默认保留：

- 09:26 竞价快照。
- 09:31 独立执行低吸前一交易日已触发持仓的纸面开盘退出；遇跌停开盘延期，不创建
  券商委托。
- 盘中资金/热度同步。
- 15 秒打板扫描和 30 秒概念共振。
- 14:50 独立冻结低吸 D-1 `cycle_relative_strength` Top3 的点时主升/MA5 信号，
  14:55 独立完成纸面买入。两者不进入共享同步批次锁、没有错过时点后的 catch-up。
- 15:05 次交易时段初步观察。
- 19:00 盘后统一更新，包含板块和个股资金、日线、成员、涨停池、3% 雷达分钟路径及
  盘后证据。
- 19:00 按完整股票日线、概念指数、成员、反向快照、免费证券状态、前向 Top3、
  前向 MA5 影子和 MA5 精确信号日 5m 的顺序采集低吸证据；Top3 任一同源日 scope
  不完整即关闭，MA5 影子仍保存 blocked scope 并继续推进已有非终态结果。股票日线
  后运行 `sync_low_suction_swing_settlement`，只按最新达到 3,000 只覆盖的可靠日期更新
  持仓标记和结构退出触发。
- 21:30 重试日线、板块/个股资金、完整成员链路、免费证券状态、涨停池、同花顺证据、
  事件分钟、3% 雷达分钟和打板历史；随后运行
  `sync_limit_up_preboard_point_trigger`，只冻结已保存的 15 秒点时因果行、结算研究动作，
  不修改正式推荐。该任务只在 21:30，且排在 `limit_up_history_rebuild` 之后。
  `sync_limit_up_exit_minutes` 已从推荐任务和默认 21:30 链路移除，仅能按需手动运行旧
  14:30 研究。
- 点触发日冻结对当前日期增加 15:00 收盘门：盘中手动运行 21:30 计划不能把尚未完成的
  当前日写成不可变 incomplete scope；更早尚未冻结的雷达日仍按最早日期恢复。
- API 在 21:00 后重启时，不再从头恢复已中断的 19:00 主批次；它保持 interrupted 失败
  证据并由 21:30 完整补偿链接管。21:30 自身若中断，仍按原规则恢复。

调度器自动执行这些计划；数据管理页“同步任务”可用“立即执行”手动触发同一条
服务端计划，API 为 `POST /api/data-sync/schedules/{schedule_id}/run`。手动触发不改变
数据来源，也不开放本地文件导入。

个股季度财务同步使用独立的 180 秒单股预算，外层最多同时处理 3 只股票；每只股票的
利润表、资产负债表和现金流通过同一个 AkShare/东方财富适配器并发读取。利润表是必要
输入，另外两表失败时只缺少对应富化字段，不生成替代值。超时股票继续禁止迟到写入。

`stock_financial_sync_attempts` 按股票保存季度财报同步的成功、空响应、失败和超时；后三类冷却
一天，自动任务优先从未尝试股票开始，再按最久未尝试顺序轮转，避免固定成交额前 100
只长期占住队列。显式 `symbols` 定向任务保持人工排障优先级，不受自动冷却排序影响。
本实现没有引入代理池。生产出口只读实测同一股票三表并发为 47.58 秒、返回
`20/8/8` 期；数据同步和打板相关回归共 219 项通过。`v2.5.24`（`f8a19554`）已部署，
生产正式任务入口定向同步 `600664.SSE` 用时 45.65 秒，读取/写入 20/20 期、超时 0，
尝试账本状态为 `succeeded` 且没有冷却。19:00 和 21:30 计划均启用；季度财报按设计只在
19:00 主批次轮转，21:30 不重复运行该任务。

旧尾盘量化和盘后量化 schedule 会在 registry 对账时删除。

## Limit-up Evidence

- 原始涨停/炸板事件、历史逐日账本、实时轨迹、概念强度、竞价和分钟路径分表保存。
- 同花顺公开源最多补近 252 个交易日，不能代表 Tick/L2 或完整竞价。
- Tick/L2、排队位置和真实委托成交不能在晚上重建；夜间任务只补公开源能够核验的
  日线、资金、事件和分钟价格。
- 历史代理、点时数据和前向 live 快照必须在报告中分开。
- 3% 雷达只在内部点时账本保存反事实动作；公开 `live` 接口继续只返回 5% v15 正式
  推荐。验证按同股同日第一次通过、20..60 秒延迟保存报价和 D+1 官方收盘结算，页面
  只在现有规则说明的数据集页展示覆盖，不增加第二个推荐面板。
- 腾讯全市场快照原生提供涨速、振幅和主力净流入/流入/流出。适配器将其规范为
  `quote_speed`、`quote_amplitude_pct`、`quote_main_*`，并按同帧写入
  `limit_up_radar_observations`；这些列不属于静态 `stocks`。2026-07-20 收盘后只读实测
  5,528 只股票的涨速、振幅和三项主力金额均非空，主力净流入率为 5,524/5,528；主板
  `>=3%` 的 370 只六项全部非空。旧雷达行不回填，首个交易时段连续覆盖从下一完整日
  验证；该源仍是聚合快照，不是逐笔成交、委托队列或 L2。
- 点触发 v9 的候选级序列变化量使用“有限数值 + 缺失标记”合同：首次进入 `>=3%` 后
  尚无 20/60 秒锚点，或腾讯点时主力流缺失时，变化量写 `0` 且对应 missing flag 写 `1`；
  不允许以缺少历史锚点或资金值为理由删掉候选。数据集构造和冻结仓储都会拒绝 `None`、
  `NaN` 或无穷模型字段。2026-07-20 只读重建的 4,956 行身份池已全部通过模型向量检查，
  但该日质量门失败且固定排除，不写入前向账本。
- 一分钟 Hazard 的实时等价输入使用通用
  `sync_stock_minute_bars(symbols, interval=1m, limit=240)` 按候选补当日前缀，盘后由
  `sync_limit_up_radar_minutes` 固化实际观察股票日；雷达帧保存 support、Rank、累计
  量额、概念 1/3/5 分钟加速度和资金字段。通用
  `features.market_snapshot_for_trade()` 以 D-1 已确认金/银手指生成
  `GOLD_ACTIVE/SILVER_ACTIVE/FADING/STALE/NONE`；雷达帧现将该状态保存为
  `market_timing_state`，不另造一套时机 API。历史核心模型不回填概念、资金或金银手指
  历史，动态字段只按冻结核心分数做前向分层。
- v3 前向评分只读取非陈旧、`source_trade_date` 同日、报价年龄不超过 60 秒且一分钟路径
  已完成到当前帧分钟的观察；同股同分钟只保留最早帧，再重算同分钟横截面并执行连续
  两分钟、每日最多两只。5 分钟分数只生成 `research_prepare`，3 分钟联合分数过冻结
  阈值只生成 `research_action`；两者均 `none_research_only`，不会进入正式推荐或两仓。
  2026-07-20 03:43 部署后表结构和 API 健康已验证；开盘前雷达仍为 0 帧，状态保持
  `collecting_forward_overlay`，不得补造过去点时帧。
- v6 纯三分钟触板模型已在同一 962 个股票日上历史拒绝：校准段满足至少 10 个选择的
  最佳触板精度仅 `46.1538%`，未达到 70% 硬门，因此没有 v6 实时准备/动作字段，也不
  消费当日逐笔 API。未来身份 oracle 的 `16/21` 只登记理论可达上界，不进入验收。
- 打板的现金成交使用 `services/execution/cash_ledger.py`，不依赖通用回测表。
- v15 首板实时板块门只读取当前快照：盘中行业触板扩散加当日行业资金，或新鲜完整的
  概念帧达到 `launch`、至少 2 只涨超 5% 且个股为概念 Top3。D-1 行业热度、同股
  联合率和成熟路径风险仍随候选保存，但首板只用于诊断和排序；两仓组合仍可使用联合率
  选择。首板研究适配禁止把 D-1 热度/龙位回退成盘中概念字段，二进三保持原合同。
- `limit_up_concept_strength_snapshots` 在 2026-07-15/16/17 分别保存 251/252/135 个
  真实分钟帧；只有这些已保存点时帧可反事实验证动态概念门。800 日历史账本没有全市场
  概念分钟帧、信号时点行业触板数和当日行业资金，不能用日终或 D-1 数据补造 v15。

## Low-suction Historical Inputs

- `services/low_suction/historical_inputs.py` 分开校验概念成员和证券状态；成员响应必须
  带日期/概念完整性清单，证券使用显式日期/股票作用域。
- Tushare `dc_index/dc_member` 客户端、D-1 规范化和自适应探测/回补已实现：
  `BKxxxx.DC` 只能精确映射到本地 `BKxxxx`，研究日 D 只消费前一已完成交易日的成员。
  本地没有 token，当前 probe 为 `unconfigured`，未写入或解除门禁；旧 `ths_member`
  明确不能查询历史。
- `low_suction_concept_membership_history` 保存压缩成员有效期，
  `low_suction_concept_membership_scopes` 保存每个日期/概念的完整性分母；两表按 provider
  原子替换，不覆盖 `stock_sector_membership_snapshots` 当前代理。当前两表均为 0 行。
- 题材资格使用严格成员的 20 日动态、精确 ID manifest 和 60/20/20 时间拆分；不使用
  策略收益选择分类阈值。当前 498 个活跃概念只有 30 个种子分类，命令返回
  `blocked_by_historical_membership`，不会生成正式 Top3。
- `low_suction_security_history` 保存上市、退市、ST、停牌有效期，
  `low_suction_security_history_scopes` 保存已验证覆盖分母；两表在一个事务中替换，
  且不外键依赖当前 `stocks`，可以保留历史退市证券。
- `stock_sector_membership_snapshot_scopes` 保存每日 concept/industry 完整性；一个板块
  异常或空响应时删除该板块旧成员，剩余成功板块形成 `strict_exclusions` scope，并在
  `raw` 保存目录分母和精确排除 ID；全部板块失败仍关闭快照。打板盘中概念只读取
  `stock_daily_bars` 确定的严格 D-1 完整 scope，不能回退到 D-2。
  `low_suction_security_snapshots` 和对应 scope 保存 BaoStock 当日盘后实际观察。
  `low_suction_forward_leader_rank_snapshots` 和对应 scope 保存三套无收益 Top3 排名、
  主升周期、特征截止、排除理由和输入指纹。源日 S 先冻结为
  `target_session=next_trading_session`；只有本地出现下一完整交易日后才补
  `target_trade_date`，不按自然日猜测周末/节假日。
- `low_suction_forward_ma5_candidates/scopes/outcomes` 与 Top3 表隔离：候选特征和范围
  首次完整指纹后不可改，blocked 可在上游恢复后晋升；结果只允许从 waiting/open
  推进到终态，终态不可改。合同只做连续严格 Top3 spell 的第 3 浪首次 MA5 止跌，
  D+1 官方开盘成交；资金流与金银状态保存实际 known_at，但只作诊断。
- BaoStock 0.9.3 的历史查询只作为 `reconstructed`；当日完整
  `query_all_stock(S)` 可从未来开始积累 strict forward 证据，两者不合并。只读复现命令为：

```bash
docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli security-master-audit --format json

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli membership-source-status

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli theme-eligibility-research \
  --start 2023-03-28 --end 2026-07-16 --format json

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-historical-phase-low-suction-study --format markdown

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli v2-forward-top3-report \
  --format markdown

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-forward-ma5-shadow-run --as-of-date 2026-07-17

docker compose exec -T alphaagent-api \
  python -m alphaagent.server.services.low_suction.cli \
  v2-forward-ma5-shadow-report --format markdown
```

- `2026-07-16` 晚间重试已得到 `concept_tradable=478/478`、67,403 条成员和 3,192 条
  BaoStock 主板证券状态。首个严格前向身份源日冻结 36 个主升概念、3,474 条三模式
  排名和 314 个 Top3，现已绑定目标日 `2026-07-17`。7 月 17 日自身的严格成员
  68,956 行、证券状态 3,191 只和修复后的 495 个官方概念指数已冻结第二个身份源日：
  3,471 行排名、307 行 Top3，等待下一完整交易日绑定。MA5 影子当前为 178 个候选、
  0 个触发，`selected_mode=null`。证据见
  `memory/06_backtests/low_suction_forward_top3_ledger_20260717.md` 和
  `memory/06_backtests/low_suction_forward_ma5_shadow_20260718.md`。
- 即时历史阶段研究只读复用 800 日股票/概念日线、历史事件 Rank1-3 代理和完整候选
  5 分钟线，不读取或改写前向 Top3 账本。1,283 笔首次触价交易与 4,587 个承接触发的
  结果见 `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.md`。

## Low-suction Forward Paper Strategy

- `low-suction-swing-paper-v1` 是独立的前向纸面执行合同：D-1 主升概念
  `cycle_relative_strength` Top3、沪深主板、两个更高高点后的首次 MA5 止跌、至少 5%
  回调和前一冲击段至少一个 `>=9.5%` 强势日；D 14:50 冻结临时日线/概念主升，14:55
  纸面买入，最多四仓且同概念一仓。
- 前高突破或连续两日收盘低于 MA20 只冻结结构退出，下一股票交易日 09:31 用开盘报价
  纸面卖出。系统固定 `execution_mode=paper`、`broker_orders_enabled=false`，没有券商
  下单端点。
- 运行、候选、持仓和交割单分别写入 `low_suction_strategy_runs`、
  `low_suction_strategy_signals`、`low_suction_paper_positions`、
  `low_suction_paper_trades`；不读写打板推荐、持仓、交割单或绩效表。
- `GET /api/low-suction/strategy` 只读返回今日信号、持仓、交割单和由上述纸面现金流/持仓
  标记计算的前向绩效。`GET /api/low-suction/swing-research` 单独返回 23 笔已查看历史描述，
  并从带 SHA256 的突破前报告动态生成 `main_rise_evidence`：D-10 四项候选、三项弱证据
  和龙头扩散区间。该子合同固定 `research_only_no_signal_filter`，只供“研究证据”Tab
  诊断，不进入今日候选、推荐、持仓、交割单或信号指纹。
- API 镜像显式复制 MA5 波段报告和突破前主升报告；缺少任一带哈希 JSON 时研究端点失败
  关闭，不以数据库或未校验文件替代。
- 2026-07-19 为周日，真实 PostgreSQL 四张表均为 0 行；接口返回 `market_closed`、
  0 候选、0 持仓、0 交割，前向胜率/利润因子为 `null`，没有制造当日信号。

## Verification

```bash
uv run --group server pytest tests/alphaagent/test_data_health.py tests/alphaagent/test_data_sync_schedule.py -q
uv run --group server pytest tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_live.py -q
uv run pytest tests/alphaagent/services/low_suction/test_swing_strategy.py \
  tests/alphaagent/services/low_suction/test_swing_strategy_repository.py \
  tests/alphaagent/services/low_suction/test_swing_strategy_service.py \
  tests/alphaagent/test_low_suction_api.py -q
```

详细删除前覆盖基线：
`memory/06_backtests/legacy_quant_removal_baseline_20260716.md`。

当前宽窗口、D+1 官方收盘正式回放：
`memory/06_backtests/limit_up_wide_window_next_close_two_to_three_20260717.md`。

历史 v8 窄窗口对照：
`memory/06_backtests/limit_up_two_window_next_close_two_to_three_20260717.md`。

历史打板成员、D-1 和精确 14:30 无兜底影响：
`memory/06_backtests/limit_up_no_fallback_impact_20260716.md`。
