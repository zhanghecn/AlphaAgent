# Market Timing Design

这个文件记录大盘择时模块的当前设计和已验证限制。具体实验过程不要继续追加到这里；新实验应写到 `memory/06_backtests/` 或独立研究报告。

## Current Semantics

- 金手指：大盘结构进入看多区域的方向事件，不代表加仓、重仓或实际仓位。
- 银手指：大盘结构进入看空区域的方向事件，不代表减仓、空仓或实际仓位。
- 对外方向固定为 `GOLD / SILVER / NEUTRAL`；`setup_type` 只解释事件来源：
  `TREND_GOLD / REVERSAL_GOLD / TOP_SILVER / BREAKDOWN_SILVER /
  STRUCTURAL_BREAKDOWN_SILVER`。
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
- “当前状态”直接使用最新交易日候选区；最新日没有合格区域就是 `NEUTRAL`，不沿用
  最近已确认事件模拟持仓。行情和因子日期拆成 `quote_date` 与 `factor_date`。
- 产品用法：金/银手指不作为用户手动策略开关；v7 只在市场择时面板输出
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
uv run pytest tests/alphaagent/services/quant/test_market_timing_backtest.py tests/alphaagent/services/quant/test_market_timing_no_lookahead.py tests/alphaagent/services/quant/test_market_timing_intraday.py -q
pnpm --dir frontend test -- timingPresentation.spec.ts
pnpm --dir frontend run build
```

面板服务：

- `market_timing_panel`: 单行 JSONB 预计算表。
- `POST /api/market-timing/refresh`: 强制刷新。
- `GET /api/market-timing/panel`: 面板读取，优先内存缓存，再库缓存，再现算。
- 盘中/盘后同步前实时：`panel.start_intraday_refresher()` daemon thread（`main.py` lifespan 启动）盘中每 5min force_refresh；`_compute_panel` 只有在七大指数实时 composite 和上证主图实时 K 线都可用时，才追加今天到基础 panel。今天 ctx 数值沿用昨天近似，但用 `dataclasses.replace` 把 `trade_date` 复制为今天，避免候选错记到昨天。`GET /panel` 的 transient overlay 覆盖交易时段和 15:00-19:30 的盘后日线同步窗口，只更新 `quote_date`、主图和点位，不覆盖 `factor_date`。限制仍是广度滞后一天、PENDING 非确认、5min 间隔。
- 面板输出完整 `timing_series`（日期、多空合力、当日区域、`danger_state` 和
  候选/确认信息）；overview 同步输出最新危险状态。前端最近 20 个交易日表
  显示结构风险行，顶部仅在危险时显示状态标签。主 K 线只画已确认和待确认事件，
  否决候选保留在计数、日期表和准确率对照中。

## Current Evidence Summary

- v3/v4 仓位状态机会吞掉同向区域；v5 改为区域重入，v6 增加反转金，v7 再把
  连续风险状态与方向事件分开。旧版本事件数和胜率不能与 v7 混用。
- v6 反转金的六指数长历史证据保持不变：`2015-01-05..2026-07-10` 共 33 个
  可评估确认样本，确认后 5 日平均 `+1.06%`、方向命中 `72.7%`；它仍只是
  补充事件，不是上涨保证。
- v7 源码直连数据库回放区间为 `2024-05-28..2026-07-13`、516 日：共 98 个
  候选，金 55、银 43；60 个确认（正式金 34、正式银 26）、38 个否决、待确认 0。
  危险阶段内的普通银事件已去重，不把同一段风险的再次恶化重复计次。
- 固定结构条件有 10 次原始重入；迟滞合并后为 5 个可评估独立危险阶段，未来
  5 日平均 `-2.08%`、下跌率 `60.0%`、最大回撤 `<=-3%` 比例 `60.0%`。
  独立样本太少，bootstrap 均值区间跨零，不能宣称稳定预测下跌。
- 危险状态内 34 个可评估交易日的未来 5 日最大回撤 `<=-3%` 比例为 `41.2%`，
  正常状态 477 日为 `13.6%`；次日平均收益分别为 `-0.175% / +0.126%`。
  日级样本存在序列相关，只能说明风险富集。
- 相邻参数复核覆盖进入 `bear/gap/trend_breakdown/macd/up_ratio` 和退出
  `bear/up_ratio/MA(4..6)`；原始重入、独立阶段、3 月覆盖和风险富集方向稳定。
- 关键日期源码回放：`2026-03-13 SILVER / STRUCTURAL_BREAKDOWN_SILVER /
  CONFIRMED / 2026-03-16`；危险状态覆盖 `03-13..03-26`，`03-20` 不再产生
  反转金，`03-27` 因真实修复回到正常。`2026-06-11` 保持
  `REVERSAL_GOLD / CONFIRMED / 2026-06-12`，允许与残余危险状态并存；
  `2026-06-26` 中性，`2026-07-07` 保持破位银。
- 后端市场择时目标测试 `41 passed`，其中 no-lookahead 23 项覆盖结构候选存在性、
  参与度缺失、危险迟滞、次日确认、冲突优先级、事件去重和未来污染；前端相关
  Vitest `42 passed`，生产构建通过。
- 设计和实施证据：`requirements/alphaagent_market_timing_v7_structural_risk_design.md`、
  `requirements/alphaagent_market_timing_v7_structural_risk_implementation_plan.md`。

## How To Use In Quant Research

- 在 Top20 研究中，金/银手指应作为 D 日可见特征进入 meta-feature table。
- 不要只比较“金手指 vs 银手指”；要分 setup 和位置，例如 `bottom_reclaim + after_silver + retreat`、`dragon_pullback + after_gold_6_20 + warming`。
- 银手指后退潮修复对 `bottom_reclaim/bottom_ma_repair` 更有价值；弱金或假回暖可能对应低吸首启失败风险。
- 行情标签若与个股结构冲突，优先看具体结构：均线修复阶段、MA20/MA60 距离、量能可控、收盘位置、主线扩散和 D+1 跟随。

## Open Risks

- 反转金已覆盖 2015、2018、2021 等压力期，但只有 33 个可评估样本且 bootstrap
  平均收益下沿仅略高于零；它是补充事件，不是保证上涨或重仓依据。
- 结构性危险区完整广度只有 516 日、5 个独立阶段；`2026-03-13` 已参与需求
  定义，不是未触碰样本外。参数必须冻结并做前向观察，不能继续围绕该日期调参。
- 六宽基价格代理在 `2020-2023` 无法稳定区分破位延续和破位反弹；2024 年前
  缺少可靠个股广度，不能把短样本 v7 结果冒充 2015 年以来验证。
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
