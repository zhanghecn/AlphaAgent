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

可靠完整日必须满足至少 3000 个不同股票。共享库截止 `2026-07-17` 有 801 个可靠日，
范围 `2023-03-28..2026-07-17`；当前 `limit-up-history-v15` 账本已增量到 801 日。
规则说明中的 800 日长期指标仍是截止 `2026-07-16` 的冻结参考报告，不能与动态账本
混算。策略规则和阈值仍保持冻结，不因共享历史加深而自动重调。

## Concepts And Mainline

- 概念/行业清单写入 `sectors`，成员写入 `sector_memberships` 和反向索引。
- 日线、资金和点时资金快照分别写入 `sector_daily_bars`、
  `sector_fund_flows`、`sector_fund_flow_snapshots`。
- `sync_sector_daily_bars` 手动/历史自举默认请求 800 根、最多 1,000 根；每个板块一次
  bulk upsert，正式板块日线只接受 `eastmoney.board_kline`。19:00/21:30 已获得历史后
  只为 concept/theme 请求最近 30 个时段，动态补新日线而不每日重建 800 日历史。
- 低吸、打板和主线共享原始 `sector_daily_bars`，但策略候选、规则和绩效不共享。
- 低吸按每个板块首末官方 K 线动态计算 D 日有效概念分母；至少 300 个有效概念且
  横截面覆盖不低于 90% 才是完整日。截止 `2026-07-16` 已有 800 个完整日，范围
  `2023-03-28..2026-07-16`，最低覆盖 `99.7567%`。
- `2026-07-17` 东方财富板块日线正式源返回空数据，`sector_daily_bars` 因而仍截止
  `2026-07-16`；同步任务保持失败并等待源恢复，没有把成分股聚合或同花顺数据冒充
  `eastmoney.board_kline`。
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

打板分钟同步保留三个数据库派生任务；事件路径和 3% 雷达前向验证属于自动链路：

- `sync_limit_up_event_minutes` 按涨停事件的信号日补 `09:15..15:00` 完整路径。
- `sync_limit_up_radar_minutes` 只读取新鲜、同源日有效的 3% 雷达帧，同股同日去重后
  补 `09:15..15:00` 的 240 根 1m 路径。239 根仍是缺口；作用域固定为
  `tdx_radar_3pct`，不插值、不切换替代供应商。19:00 和 21:30 各限 300 对。
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
`limit_up_concept_scan`。默认保留：

- 09:26 竞价快照。
- 盘中资金/热度同步。
- 15 秒打板扫描和 30 秒概念共振。
- 15:05 次交易时段初步观察。
- 19:00 盘后统一更新，包含板块和个股资金、日线、成员、涨停池、3% 雷达分钟路径及
  盘后证据。
- 19:00 按完整股票日线、概念指数、成员、反向快照、免费证券状态、前向 Top3 的顺序
  采集低吸证据；Top3 任一同源日 scope 不完整即关闭。
- 21:30 重试日线、板块/个股资金、完整成员链路、免费证券状态、涨停池、同花顺证据、
  事件分钟、3% 雷达分钟和打板历史。`sync_limit_up_exit_minutes` 已从推荐任务和默认
  21:30 链路移除，仅能按需手动运行旧 14:30 研究。

调度器自动执行这些计划；数据管理页“同步任务”可用“立即执行”手动触发同一条
服务端计划，API 为 `POST /api/data-sync/schedules/{schedule_id}/run`。手动触发不改变
数据来源，也不开放本地文件导入。

个股季度财务同步按股票有 60 秒上限；单只 AkShare 请求超时后明确跳过并继续整批，
迟到响应不再写入。该保护只改变卡死行为，不替换财务数据源或伪造成功记录。

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
```

- `2026-07-16` 晚间重试已得到 `concept_tradable=478/478`、67,403 条成员和 3,192 条
  BaoStock 主板证券状态。首个严格前向身份源日随后冻结 36 个主升概念、3,474 条三模式
  排名和 314 个 Top3；目标日仍未绑定，`selected_mode=null`。证据见
  `memory/06_backtests/low_suction_forward_top3_ledger_20260717.md`。
- 即时历史阶段研究只读复用 800 日股票/概念日线、历史事件 Rank1-3 代理和完整候选
  5 分钟线，不读取或改写前向 Top3 账本。1,283 笔首次触价交易与 4,587 个承接触发的
  结果见 `memory/06_backtests/low_suction_historical_phase_entry_study_20260717.md`。

## Verification

```bash
uv run --group server pytest tests/alphaagent/test_data_health.py tests/alphaagent/test_data_sync_schedule.py -q
uv run --group server pytest tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_live.py -q
```

详细删除前覆盖基线：
`memory/06_backtests/legacy_quant_removal_baseline_20260716.md`。

当前宽窗口、D+1 官方收盘正式回放：
`memory/06_backtests/limit_up_wide_window_next_close_two_to_three_20260717.md`。

历史 v8 窄窗口对照：
`memory/06_backtests/limit_up_two_window_next_close_two_to_three_20260717.md`。

历史打板成员、D-1 和精确 14:30 无兜底影响：
`memory/06_backtests/limit_up_no_fallback_impact_20260716.md`。
