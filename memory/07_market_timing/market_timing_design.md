# Market Timing Design

这个文件记录大盘择时模块的当前设计和已验证限制。具体实验过程不要继续追加到这里；新实验应写到 `memory/06_backtests/` 或独立研究报告。

## Current Semantics

- 金手指：大盘结构进入看多区域的方向事件，不代表加仓、重仓或实际仓位。
- 银手指：大盘结构进入看空区域的方向事件，不代表减仓、空仓或实际仓位。
- 对外方向固定为 `GOLD / SILVER / NEUTRAL`；`setup_type` 只解释事件来源：
  `TREND_GOLD / REVERSAL_GOLD / TOP_SILVER / STRUCTURAL_BREAKDOWN_SILVER`
  和 `GOLD_FAILURE_SILVER`。
  `BREAKDOWN_SILVER` 常量仅为历史载荷和前端类型兼容保留，v8 不再生成新事件。
- v9（2026-07-15 起）增加金手指失效银：只在新的趋势金候选被次日宽基急跌
  明确否决、多头退出金区且空头反超时，于失败日确认银手指。该保护不恢复普通
  破位银，也不修改反转金、顶部银或结构银。
- v8（2026-07-15 起）采用精度优先银手指：普通趋势破位银在完整广度样本和
  长历史宽基代理中均未通过验证，因此删除普通破位银，只保留顶部银和结构银
  作为基础银通道。
- v7（2026-07-14 起）增加结构性破位银和独立 `danger_state=NORMAL/DANGER`。
  危险状态表达市场风险是否修复，不代表仓位，也不直接决定当日金银方向。
- 结构性破位银要求空头绝对强度、多空差值、趋势破位、MA20、MACD 顶部结构和
  宽基参与度同时转弱；只在 `NORMAL -> DANGER` 时发一次事件。同一危险阶段内
  不重复统计普通银事件，但完整强破位条件消失后仍允许反转金等相反方向事件。
- 每日先判断候选区；连续停留同一区域不重复，离开后重新进入可以再次发同方向事件。
  反转金另有 10 个交易日同类冷却；当日完整结构性破位优先于反转金。
- 候选事件标在【候选日 i】。普通金银和反转金由次日方向/参与度确认；结构性
  破位银由次日是否完成风险修复确认。所有否决候选继续保留，序列末端为 `PENDING`。
  正式金银次数只统计 `CONFIRMED`，候选总数不冒充正式次数。
- `active_direction` 保存最近一次已确认金银事件的因果方向：从 `confirm_date`
  起持续沿用，直到相反方向事件确认；`PENDING/INVALIDATED` 不切换。界面固定称为
  “手指状态”，显示“金手指延续 / 银手指延续”，不再把当日中性候选区作为
  用户结果。`zone_direction` 和否决候选保留在 API 中供内部审计，不在用户主结果
  中展示。行情和因子日期拆成 `quote_date` 与 `factor_date`。
- 产品用法：金/银手指不作为用户手动策略开关；市场择时面板同时输出
  `danger_state`，没有把它直接接入量化候选、涨停策略、仓位或下单。
- 当前与 Top20 研究的关系：金/银手指单独不够精准，必须结合 setup、均线位置、量能、收盘位置、主线、右尾保护和失败风险。
- 表现评估分成两个时间口径：`buckets/rows` 只含已确认事件，从 `confirm_date` 收盘起算；`candidate_buckets/candidate_rows` 包含全部候选，不按次日状态筛选，从候选日收盘起算。API 用 `evaluation_basis` 声明两套起点和 `executable=false`；二者都是观察性表现，不是含下一可成交价、滑点和费用的策略收益。

## Algorithm Shape

大盘基准：

- 用 `market_context.INDEX_WEIGHTS` 对 7 大指数日收益率加权，再 cumprod 成综合序列。
- 图表可以展示上证指数，但信号基于综合序列。

主要因子族：

- trend：趋势。
- momentum：动量，包含 MACD/RSI/ROC 等技术代理。
- breadth：市场广度。
- structure：波动结构、风险分、连阳/收敛。
- volume：量能和量价同向。
- top-divergence：MACD 顶背离、广度顶背离等顶部风险。

反转金固定规则：

- 候选日同时满足 `RSI(2)<=20`、10 日收益 `<=-2%`、相对近 20 日最高收盘回撤
  `<=-3%`、当日收益位于 `[-1.0%, +0.5%]`。
- 次日综合指数上涨且至少一半有效宽基指数上涨才确认。
- `CompositeBar.up_ratio` 保存当日有效宽基上涨比例；候选计算只读取截止当日的收盘前缀。

结构性破位银固定规则：

- 候选日同时满足 `bear_force>=65`、`bear_force-bull_force>=15`、
  `trend_breakdown>=80`、综合指数低于 MA20、`macd_top>=70`、
  `up_ratio<=0.5`；参与度缺失时严格不触发。
- 危险状态在综合指数收复 MA5、`up_ratio>=0.5` 且 `bear_force<65` 时于当日
  收盘后解除，不使用未来反弹回填上一日的结束边界。
- 当日完整强破位优先输出银；残余危险状态本身不压制新的反转金，因此风险
  状态和方向事件可以并存。
- 普通银区若只有 `trend_breakdown>=60` 而未满足完整结构破位，不生成银事件；
  顶部空头合力且 `trend_breakdown<60` 时仍可生成 `TOP_SILVER`。

金手指失效银固定规则：

- 前一交易日必须已经产生 `TREND_GOLD` 候选；`REVERSAL_GOLD` 失败不触发。
- 失败日综合指数跌幅 `<=-2%`、有效宽基上涨比例 `<=0.25`、
  `bull_force<60` 且 `bear_force>=bull_force`。
- 失败银事件记在失败日并在正式日线完成后同日确认；若
  `confirmed_through` 尚未覆盖失败日，只输出 `PENDING`，不提前切换方向。
- 日跌阈值 `-1.5%..-3.5%`、多头上限 `55..65`、参与度上限 `0..0.43`
  的邻域检查均只命中同一个真实样本，但样本数仍只有 1。

硬约束：

- 所有特征严格只用 `<=t` 数据。
- 未来收益只用于 backtest/eval 标签，不进入信号生成。
- 信号生成和回测评估物理隔离。
- 无未来函数测试必须覆盖“篡改 t 之后数据，t 及以前因子/信号不变”。

## Implementation Entrypoints

模块：

```text
alphaagent/server/services/quant/market_timing/
  series.py
  factors.py
  signal.py
  backtest.py
```

脚本和测试：

```bash
uv run python scripts/market_timing_eval.py
uv run --group server pytest tests/alphaagent/services/quant/test_market_timing_backtest.py tests/alphaagent/services/quant/test_market_timing_no_lookahead.py tests/alphaagent/services/quant/test_market_timing_intraday.py -q
pnpm --dir frontend test
pnpm --dir frontend run build
```

面板服务：

- `market_timing_panel`: 单行 JSONB 预计算表。
- `POST /api/market-timing/refresh`: 强制刷新。
- `GET /api/market-timing/panel`: 面板读取，优先内存缓存，再库缓存，再现算。
- 盘中/盘后同步前实时：`panel.start_intraday_refresher()` daemon thread（`main.py` lifespan 启动）盘中每 5min force_refresh；`_compute_panel` 只有在七大指数实时 composite 和上证主图实时 K 线都可用时，才追加今天到基础 panel。今天 ctx 数值沿用昨天近似，但用 `dataclasses.replace` 把 `trade_date` 复制为今天，避免候选错记到昨天。`GET /panel` 的 transient overlay 覆盖交易时段和 15:00-19:30 的盘后日线同步窗口，只更新 `quote_date`、主图和点位，不覆盖 `factor_date`。限制仍是广度滞后一天、PENDING 非确认、5min 间隔。
- 面板输出完整 `timing_series`（日期、多空合力、`active_direction`、
  `zone_direction`、`danger_state` 和候选/确认信息）；overview 同步输出最新危险
  状态。盘中追加 bar 通过 `confirmed_through` 截止正式确认，次日盘中涨跌不能
  提前改变最近确认方向。主 K 线只画已确认和待确认事件，否决候选保留在计数、
  日期表和准确率对照中。
- 主摘要读取 `overview.current_direction`，展示为“手指状态”，并用
  `overview.latest_signal.confirm_date` 解释延续起点。最近交易日表只向用户展示
  `active_direction` 和有效手指事件。K 线悬停按日期展示 `YYYY-MM-DD`、OHLC、
  涨跌幅、持续手指状态和当日有效新手指；`zone_direction=NEUTRAL` 与
  `INVALIDATED` 候选不会覆盖用户看到的金银结果。

## Current Evidence Summary

- v9 研究快照区间为 `2024-05-28..2026-07-15`：65 个候选，金 55、银 10；
  42 个确认、23 个否决、0 个待确认。相对 v8 只增加 1 个
  `GOLD_FAILURE_SILVER`，普通 `BREAKDOWN_SILVER` 仍为 0。
- 持续状态验证显示，v9 金状态未来 5 日命中率/均收益/`3%` 不利为
  `58.9%/+0.80%/13.3%`，银状态为 `51.6%/-0.21%/20.9%`。银状态未来
  10/20 日命中率仅 `41.9%/34.9%`，不能解释为整个延续区间必然下跌。
- 研究用波动迟滞版本已拒绝：银状态 EARLY/LATE 未来 5 日均收益仍为
  `+0.44%/+0.13%`，转换从 v9 的 9 次膨胀到 35 次，最坏反弹为 `+34.45%`。
  生产 v9 未修改，最新仍为银手指。完整证据见
  `memory/06_backtests/market_timing_state_validation_2026_07_15.md`。
- 三个银转金恢复版本也已拒绝。R1/R2/R3 都只改变
  `2025-10-20..2025-12-22` 一个银区间；银 10 日命中降到 `31.1%..31.8%`，
  银 5 日 `3%` 不利升到 `30.0%..30.6%`，五个逐银区间留一均只有 1 折不劣于
  v9。当前 `2026-07-02` 开放银区间没有确认恢复金，生产 v9 和最新银状态未修改。
  详细证据见 `memory/06_backtests/market_timing_recovery_gold_validation_2026_07_15.md`。
- 金候选未来 5 日上涨率为 `63.6%`、平均收益 `+1.82%`；34 个确认金从确认日
  收盘起算的 5 日上涨率为 `79.4%`、平均收益 `+2.07%`。确认后口径经过次日
  状态筛选，不能替代全部候选口径。
- 关闭前普通破位银未来 5 日下跌率为 `41.2%`、平均收益 `+1.07%`；2025、
  2026 年下跌率均只有 `22.2%`。保留的顶部银和结构银合计 9 个，未来 5 日
  下跌率 `66.7%`、平均收益 `-1.2763%`，但 Wilson 95% 区间仍为
  `35.4%..87.9%`，不能宣称统计显著。
- 55 个金事件的日期、setup、状态和确认日继续与 v7 逐项一致，事件签名 SHA-256 为
  `b30746cbe057084f798153d8ec1c5fc1a71acd573425d3182a35eecb0c90018e`；
  v8 的 9 个保留银事件也未改变，v9 在其上增加 1 个失败银。
- 关键日期：`2026-03-13` 保持 `STRUCTURAL_BREAKDOWN_SILVER / CONFIRMED /
  2026-03-16`；`2026-06-11` 保持 `REVERSAL_GOLD / CONFIRMED / 2026-06-12`；
  `2026-06-26` 与 `2026-07-07` 均不再生成事件。
- v7 危险状态证据仍独立有效：5 个结构性危险阶段未来 5 日平均 `-2.08%`，
  危险状态日未来 5 日最大回撤 `<=-3%` 的比例高于正常状态；危险状态不等于
  v8 银事件数量，也不用于恢复普通破位银。
- 六宽基 `2015-2026` 价格代理显示结构破位在 `2015-2019` 较有效，但在
  `2020-2023` 只有约 `30.8%` 的未来 5 日下跌率、平均收益约 `+2.03%`。
  均线、动量、波动、长期趋势、滚动状态和浅层模型没有形成跨时期稳定过滤。
- 当前回归验证：市场择时后端测试 `74 passed`，前端测试 `67 passed`，生产构建
  通过；重建 API/Web 后强制刷新返回 200。真实面板行情、因子和基础样本均截至
  `2026-07-15`，`overview.current_direction=timing_series[-1].active_direction=SILVER`。
- 关键日期链保持因果：`2026-06-11 REVERSAL_GOLD / CONFIRMED / 2026-06-12`；
  `2026-07-01 TREND_GOLD / INVALIDATED / 2026-07-02`；`2026-07-02
  GOLD_FAILURE_SILVER / CONFIRMED / 2026-07-02`。失败银当日依据为综合指数
  `-3.7%`、`up_ratio=0`、`bull=53.6`、`bear=55.4`，不读取 7 月 3 日数据。
- v9 银候选未来 5 日下跌率为 `60.0%`、平均收益约 `-1.12%`；确认银 5 日
  样本为 8 个，下跌率 `62.5%`、平均收益约 `-1.77%`。7 月 2 日失败银本身
  未来 5 日收益约 `+0.29%`，因此该规则是金状态失效保护，不能宣传为稳定的
  5 日下跌预测。
- 2026-07-02 页面验证：真实 K 线十字线显示“银手指延续 / 当日新手指
  银手指确认”，并在 7 月 2 日画银箭头；移出图表后恢复最新行情
  `2026-07-15 / 银手指延续`。`1440x1000` 与 `390x844` 横向溢出均为 0，
  控制台 0 错误/0 警告。实现提交为 `fc837bd5`。
- 设计和实施证据：`requirements/alphaagent_market_timing_v8_precision_silver_design.md`、
  `requirements/alphaagent_market_timing_v8_precision_silver_implementation_plan.md`、
  `requirements/alphaagent_market_timing_persistent_regime_design.md`、
  `requirements/alphaagent_market_timing_persistent_regime_implementation_plan.md`、
  `requirements/alphaagent_market_timing_hover_semantics_design.md`、
  `requirements/alphaagent_market_timing_hover_semantics_implementation_plan.md`、
  `requirements/alphaagent_market_timing_v9_gold_failure_silver_design.md`、
  `requirements/alphaagent_market_timing_v9_gold_failure_silver_implementation_plan.md`、
  `requirements/alphaagent_market_timing_state_validation_design.md`、
  `requirements/alphaagent_market_timing_state_validation_implementation_plan.md`、
  `requirements/alphaagent_market_timing_recovery_gold_research_design.md`、
  `requirements/alphaagent_market_timing_recovery_gold_research_implementation_plan.md`。

## How To Use In Quant Research

- 在 Top20 研究中，金/银手指应作为 D 日可见特征进入 meta-feature table。
- 不要只比较“金手指 vs 银手指”；要分 setup 和位置，例如 `bottom_reclaim + after_silver + retreat`、`dragon_pullback + after_gold_6_20 + warming`。
- 银手指后退潮修复对 `bottom_reclaim/bottom_ma_repair` 更有价值；弱金或假回暖可能对应低吸首启失败风险。
- 行情标签若与个股结构冲突，优先看具体结构：均线修复阶段、MA20/MA60 距离、量能可控、收盘位置、主线扩散和 D+1 跟随。

## Open Risks

- 反转金已覆盖 2015、2018、2021 等压力期，但只有 33 个可评估样本且 bootstrap
  平均收益下沿仅略高于零；它是补充事件，不是保证上涨或重仓依据。
- v9 银只有 10 个完整广度样本，其中失败银只有 1 个；结构性危险区只有 5 个独立阶段；
  `2026-03-13` 已参与需求定义，不是未触碰样本外。参数必须冻结并做前向观察，
  不能继续围绕该日期调参。
- 持续状态日不是独立样本。v9 的 5 个银区间在 10/20 日方向上没有稳定看空优势；
  在取得更长同口径广度历史或新的冻结前向样本前，不能把当前银状态宣传为
  持续下跌预测，也不能据此直接控制仓位。
- MA5 危险修复、广度多头反超和 MA20 确认三类恢复金都未形成跨银区间改善；
  不再组合这三类条件或围绕 `2025-10` 调阈值。恢复时点问题继续保持未解决，
  只能等待新独立区间或无幸存者偏差的更长广度数据。
- `2026-07-02` 参与了失败银需求定义，且该事件未来 5 日最终收益为正；它不是
  未触碰样本外证据。若前向样本频繁在快速反弹前触发，应整体删除失败银 setup，
  不能继续增加日期例外或叠加过滤条件。
- 六宽基价格代理在 `2020-2023` 无法稳定区分破位延续和破位反弹；2024 年前
  缺少可靠个股广度，不能把当前短样本结果冒充 2015 年以来验证。
- 危险区因无未来函数会比肉眼事后区间更晚解除：3 月真实状态到 `03-26`，而非
  读取 `03-24` 以后反弹后回填结束到 `03-23`。
- 候选生成只使用 `<=t` 数据；`CONFIRMED/INVALIDATED` 仍合法地读取 `t+1` 收盘，因此在确认日收盘前不能知道正式状态。此前“用确认日涨跌筛样本、又从候选日收盘起算”的选择偏差已修复，但 `confirm_date_close` 仍不是可成交价；若要宣称策略收益，必须改用下一可成交价并计入滑点、费用、停牌和涨跌停约束。
- 市场择时更适合作为候选 ranker 的上下文因子，不适合作为硬开关；硬开关容易漏掉个股右尾。
- 运维：`market_timing_panel` 库缓存 TTL=24h + 进程内 30min，**算法变更不会自动失效**。改 signal/factors 算法后必须两步：① `docker compose up --build -d alphaagent-api`（+ `alphaagent-web` 若改前端）重建镜像让容器代码跟上源码（2026-07-04 即发现本地容器停在 v2.4.1，而源码已更新）；② `POST /api/market-timing/refresh` 强制重算落库。否则线上/本地/源码三方展示不同版本事件，极易被误判为未来函数。
- 线上 `agu.yantiandao.com` 是否已升级到 v5 尚未验证；本地变更需要后续 tag/发布流程对齐线上。
- no-lookahead 守护测试覆盖候选存在性、次日确认、否决候选保留、连续区域去重、
  结构危险状态、参与度缺失、冲突优先级和未来污染。见
  `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`。
- `/market` 日期一致性守护覆盖盘后行情 overlay、当天 K 线替换、盘中 context 日期复制、当前方向和逐日序列。见 `tests/alphaagent/services/quant/test_market_timing_intraday.py`。
