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
3. 优先通过腾讯 K 线获取股票日线。
4. upsert 到 `stock_daily_bars`。
5. 15:05 前的当天盘中日 K 保留但不计入研究；收盘后仍低于上一完整日 95% 或
   3000 只的局部发布日会被丢弃并等待重试。

复权口径（2026-07-22 实证修正，旧记录“腾讯复权 K 线”有误）：三条抓取链
（腾讯 `newfqkline` 空 fq 参数读 `day` 键、东财 `fqt=0`、akshare `adjust=""`）
**统一为不复权**；实证为主板个股出现 -21%~-37% 单日“跌幅”（±10% 涨跌停下不可能），
即除权缺口。影响：MA/前高/收益率等策略特征在除息日附近失真（2-7 月分红季覆盖回测
窗口），低吸/打板的均线支撑与参考前高口径需在后续算法项目引入前复权序列
（全量重刷或按 Top3 候选按需取 qfq 序列），分钟线同为不复权。

可靠完整日必须满足至少 3000 个不同股票。共享库截止 `2026-07-24` 有 806 个可靠日，
范围 `2023-03-28..2026-07-24`；这是行情背景，不是正式推荐覆盖。当前
`limit-up-core-ab-v1` 的真实事件从 `2025-06-27` 开始，闭合推荐覆盖
`2025-07-10..2026-07-23`。
板前最终冻结报告仍固定使用 802 日输入，不随运行库增长重选模型或阈值；规则说明的历史
参考已明确标注为截至 `2026-07-24` 的 806 日候选代理。滚动绩效以回测接口为准，冻结
板前模型、规则说明证据快照和当前回测指标不能混算。

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
  历史持久化候选池通过
  `scheduled_execution.extract_scheduled_orders()` 派生的研究通道 D+1，以及
  实时保存的全部 `actionable_recommendations`。实时推荐只有在本地
  日线已经出现下一交易日后才生成退出请求，不猜测周末或节假日。
- 合并请求先排除已有精确 14:30 行，再从 TDX 请求 `14:30..14:30`；同股同日多个快照
  自动去重，正式推荐不受两仓 `portfolio` 限制。
- 三者共享进程锁但重试作用域分开：事件路径为 `tdx`，3% 雷达为
  `tdx_radar_3pct`，候选卖出价为 `tdx_exit_1430`。下载返回行不等于覆盖；雷达必须
  二次核验 240 根，候选卖出价必须二次查到精确 14:30 行才记为 covered。
- `limit-up-core-ab-v1` 正式账户不读取上述 14:30 研究价。它执行首板和二进三，
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
  `sync_limit_up_preboard_decision`，调用唯一
  `preboard_decision_service.freeze_and_settle()`，冻结板前决策证据并结算已有
  shadow/formal 动作；当前 `research_only` 不写动作、不修改正式推荐。任务只在 21:30，
  且排在 `limit_up_history_rebuild` 之后；没有独立轮询进程。
  `sync_limit_up_exit_minutes` 已从推荐任务和默认 21:30 链路移除，仅能按需手动运行旧
  14:30 研究。
- 板前决策日冻结对当前日期保留 15:00 收盘门：盘中手动运行 21:30 计划不能把尚未完成的
  当前日写成不可变 incomplete scope；更早尚未冻结的雷达日仍按最早日期恢复。
- API 在 21:00 后重启时，不再从头恢复已中断的 19:00 主批次；它保持 interrupted 失败
  证据并由 21:30 完整补偿链接管。21:30 自身若中断，仍按原规则恢复。

调度器自动执行这些计划；数据管理页“同步任务”可用“立即执行”手动触发同一条
服务端计划，API 为 `POST /api/data-sync/schedules/{schedule_id}/run`。手动触发不改变
数据来源，也不开放本地文件导入。

季度财务任务按报告期批量读取东方财富 `RPT_LICO_FN_CPD`，不再每天逐股轮转 100 只或
并发请求三张报表。首次自举最近 16 个季度，之后跳过已完整报告期并每日刷新最新已结束
季度；显式 `report_dates/symbols` 仅用于定向核验。批量源的 `SJLTZ` 是归母净利润同比，
`SJLHZ` 是季度环比，禁止再把 `*_QOQ` 写成同比。每股经营现金流除以每股收益得到与归母
净利润一致的现金流质量；扣非归母净利润只在原始字段存在时写入，资产负债率因该批量源
没有总资产/总负债而保持缺失，不用 0 或旧季度伪造。

回测和实时共用 `stock_financial_reports`，交易日 D 只读取 D 日之前已公告的最新报告；公告
源没有盘中时间，因此公告当日不用于盘中决策。财报写入或旧同比失效后会清空同进程实时
质量缓存，避免 15:05 初步计划的“财报缺失”延续到 19:00 最终计划。当前表共 90,930 条、
覆盖 5,531 只股票；批量源 82,266 条，其中现金流质量 81,065 条、扣非利润 26,757 条，
重复股票季度为 0。当前根因和回测影响见
`memory/06_backtests/limit_up_financial_coverage_reverse_reasoning_20260726.md`。季度财报只在 19:00
主批次运行，21:30 不重复请求；21:30 的历史重建吸收已落库结果。

旧尾盘量化和盘后量化 schedule 会在 registry 对账时删除。

## Limit-up Evidence

- 原始涨停/炸板事件、历史逐日账本、实时轨迹、概念强度、竞价和分钟路径分表保存。
- 截至 2026-07-24，2026 年 3-7 月全市场日线分别覆盖 22/21/18/21/18 个交易日；1 分钟
  行情虽覆盖这些交易日，但每月只有 465/534/632/1537/2333 只股票，属于候选回填而非
  全市场连续快照。点时行业/主题成员从 7 月 13 日开始、概念成员从 7 月 20 日开始，
  盘中板块资金从 7 月 13 日开始，概念分钟强度从 7 月 15 日开始，完整雷达主要覆盖
  7 月 20-24 日。因此 3-6 月只能做日级龙头轮换，严格“个股先动、板块后扩散”分钟研究
  必须逐事件通过成员和行情覆盖门。
- 同花顺公开源最多补近 252 个交易日，不能代表 Tick/L2 或完整竞价。
- Tick/L2、排队位置和真实委托成交不能在晚上重建；夜间任务只补公开源能够核验的
  日线、资金、事件和分钟价格。
- 历史代理、点时数据和前向 live 快照必须在报告中分开。
- 唯一活动板前合同为 `limit-up-preboard-decision-v1`。底层可以读取全市场行情构造分钟
  和横截面诊断，但个股必须先通过正式同源首板质量门，再由 `change_pct >= 3` 激活观察；
  普通 3% 股票、质量失败股票和已触板股票不得进入个股模型或当前板前列表。
- 历史和实时分别规范化保存分钟/逐笔/横截面输入，再调用同一特征、双概率模型、状态机和
  排序函数。10 秒报价只形成采样分钟代理；当前未完成分钟、午休伪分钟、未来触板/封板和
  D+1 结果均不得进入点时特征。
- 实时 `/api/limit-up/live` 现在只增加一个顶层 `preboard_candidates`：显示高质量股票的
  D+1 预期收益/胜率、三分钟/最终触板概率、触板后封板率、涨幅、距板、数据质量和时间。
  当前执行模式是 `research_only`，所以不写 action、不占两仓、不进入正式买入提醒。
- 严格板前 C 只认行动后的第一条新报价且必须低于涨停价；一分钟历史代理使用下一分钟
  open，等于涨停价或缺少报价都算未成交。正式 v15 触板基线仍使用信号后 20--60 秒保存
  报价代理，涨停价买点只表示可尝试排队。两种成交口径必须分开说明，不能互相替代。
- 腾讯全市场快照原生提供涨速、振幅和主力净流入/流入/流出。适配器将其规范为
  `quote_speed`、`quote_amplitude_pct`、`quote_main_*`，并按同帧写入
  `limit_up_radar_observations`；这些列不属于静态 `stocks`。2026-07-20 收盘后只读实测
  5,528 只股票的涨速、振幅和三项主力金额均非空，主力净流入率为 5,524/5,528；主板
  `>=3%` 的 370 只六项全部非空。旧雷达行不回填，首个交易时段连续覆盖从下一完整日
  验证；该源仍是聚合快照，不是逐笔成交、委托队列或 L2。
- 当前模型使用 52 个声明特征，其中 fit 实际使用 38 个、删除 14 个常量/不可用列。任何
  非有限模型值都会关闭该点评分；缺失资金或短期锚点以显式 missing 特征表达，不能静默
  把候选删掉或用未来值回填。
- 金/银手指沿用 `features.market_snapshot_for_trade()` 的 D-1 已确认状态。概念强度、行业
  资金、个股资金、当前换手、报价/快照新鲜度和市场门在冻结历史中没有充分点时同源覆盖，
  当前统一标记 `parity_status=diagnostic`、`blocking=false`；只有共享风险、正式窗口、
  完整分钟和严格板前价格可以阻断。诊断字段待独立预注册覆盖后再研究，不能成为实时独有
  硬门，也不能用收盘数据回填。
- 最新冻结模型的概率排序通过：三分钟/最终触板 Brier skill 为 `+0.1360/+0.2253`，
  PR-AUC 为 `0.3451/0.4265`，机会 Top20% lift 为 `4.48/3.30`。但严格板前 C 首板账户
  只有 27 笔、51.85% 胜率、`+6.10%` 复利、`-14.58%` 回撤，低于 A 触板基线，状态为
  `historical_rejected`；模型指纹为
  `sha256:b1d4ca83ca4dad25e1e74cda21c5b01c4f40d6e62ed9da62582d6eb8c651b71a`。
- 正式切换有双重保护：模型记录必须是 `forward_pass_for_formal`，环境变量
  `ALPHAAGENT_PREBOARD_FORMAL_MODEL_FINGERPRINT` 还必须精确匹配同一模型指纹。晋级时
  只原子替换首板动作和两仓，二进三原样保留。
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
  0 个触发，`selected_mode=null`。旧逐日账本已随历史研究清理；数据库前向表是当前事实源。
- 即时历史阶段研究只读复用 800 日股票/概念日线、历史事件 Rank1-3 代理和完整候选
  5 分钟线，不读取或改写前向 Top3 账本。旧研究报告已归档在删除前 Git 历史，不再作为
  当前入口。

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

当前打板合同、历史结果和研究证据统一从
`memory/06_backtests/README.md` 进入。被提交 `f99d4afc` 删除的旧窗口、v8 和 14:30
报告只在 Git 历史中保留，不再作为当前链接。
