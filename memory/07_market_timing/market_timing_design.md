# Market Timing Design

这个文件记录大盘择时模块的当前设计和已验证限制。具体实验过程不要继续追加到这里；新实验应写到 `memory/06_backtests/` 或独立研究报告。

## Current Semantics

- 金手指：大盘结构进入看多区域的方向事件，不代表加仓、重仓或实际仓位。
- 银手指：大盘结构进入看空区域的方向事件，不代表减仓、空仓或实际仓位。
- 对外方向固定为 `GOLD / SILVER / NEUTRAL`；`setup_type` 只解释事件来源：
  `TREND_GOLD / REVERSAL_GOLD / TOP_SILVER / BREAKDOWN_SILVER`。
- v6（2026-07-13 起）在 v5 区域进入事件上增加 `REVERSAL_GOLD` 弱势衰竭反转金。
  趋势金和现有银手指继续使用原区域逻辑；镜像反转银跨时期失效，未上线。
- 每日先判断候选区；连续停留同一区域不重复，离开后重新进入可以再次发同方向事件。
  反转金另有 10 个交易日同类冷却，并优先于同日弱势银区。
- 候选事件标在【候选日 i】，`status` 记次日确认结果：`CONFIRMED`（次日同向）、
  `INVALIDATED`（次日反向或反转金参与度不足，事件保留）、`PENDING`（序列末端待确认）。
  正式金银次数只统计 `CONFIRMED`，候选总数不冒充正式次数。
- “当前状态”直接使用最新交易日候选区；最新日没有合格区域就是 `NEUTRAL`，不沿用
  最近已确认事件模拟持仓。行情和因子日期拆成 `quote_date` 与 `factor_date`。
- 产品用法：金/银手指不作为用户手动策略开关；在量化候选中作为内部市场环境因子、风险解释和排序上下文。
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
- 面板输出完整 `timing_series`（日期、多空合力、当日区域和候选/确认信息）；前端最近 20 个交易日表使用该序列。主 K 线只画已确认和待确认事件，否决候选保留在计数、日期表和准确率对照中。

## Current Evidence Summary

- v3/v4 仓位状态机曾减少金/银交替，但会吞掉新的同向区域；v5 改成区域重入事件，
  v6 再把当前方向与历史事件彻底解耦。旧版本的事件数和胜率不能作为当前结论。
- v6 自主实验否决了四通道加权、布尔共振、扩展确认、因果摆动、滚动逻辑回归和
  镜像反转银；只保留在六/七指数、冻结分段和相邻参数中方向一致的反转金。
- 六指数 `2015-01-05..2026-07-10` 固定规则共有 33 个可评估确认样本：确认后 5 日
  平均 `+1.06%`、方向命中 `72.7%`；固定种子 bootstrap 95% 区间分别为
  `+0.04%..+2.09%` 和 `57.6%..87.9%`。区间下沿仅略高于零，不能据此承诺上涨。
- 2026-07-13 强制刷新后的真实面板样本为 `2024-05-28..2026-07-13`，共 99 个候选：
  56 个已确认（正式金 34、正式银 22）和 43 个否决，待确认 0；全部事件和表现行
  均有合法 `setup_type`，确认后与候选表现起点错位数均为 0。
- 关键日期回归：`2026-06-11 GOLD / REVERSAL_GOLD / CONFIRMED / 2026-06-12`；
  `2026-06-26` 为 `NEUTRAL` 且无事件；`2026-07-07 SILVER / BREAKDOWN_SILVER /
  CONFIRMED / 2026-07-08`。最新 `factor_date=quote_date=2026-07-13`，当天仍在银区。
- 当前真实面板确认后 5/10/20 日方向胜率：金 `79%/71%/74%`（各 `n=34`），银
  `38%/43%/43%`（各 `n=21`）；全部候选金 `62%/65%/69%`（`n=56/55/55`），
  银 `43%/55%/43%`（各 `n=42`）。这是偏牛短样本的观察性表现，不是成交收益。
- Playwright 验证 `1920x1080` 与 `390x844` 均无全页横向溢出、控制台 0 错误/
  0 警告、面板接口 200；移动端最近日期表和两张表现表在各自容器内横向滚动。
- v6 信号实现改为按候选日索引读取固定窗口，不再逐日复制完整历史前缀；2,800 日
  微基准中事件检测约 `14.2ms -> 9.7ms`，日期序列构建约 `16.1ms -> 9.0ms`。
  34 项后端守护和真实 API `99/56/43/0` 事件计数保持不变。
- 设计和实施证据：`requirements/alphaagent_market_timing_v6_general_signal_design.md`、
  `requirements/alphaagent_market_timing_v6_general_signal_implementation_plan.md`。

## How To Use In Quant Research

- 在 Top20 研究中，金/银手指应作为 D 日可见特征进入 meta-feature table。
- 不要只比较“金手指 vs 银手指”；要分 setup 和位置，例如 `bottom_reclaim + after_silver + retreat`、`dragon_pullback + after_gold_6_20 + warming`。
- 银手指后退潮修复对 `bottom_reclaim/bottom_ma_repair` 更有价值；弱金或假回暖可能对应低吸首启失败风险。
- 行情标签若与个股结构冲突，优先看具体结构：均线修复阶段、MA20/MA60 距离、量能可控、收盘位置、主线扩散和 D+1 跟随。

## Open Risks

- 反转金已覆盖 2015、2018、2021 等压力期，但只有 33 个可评估样本且 bootstrap
  平均收益下沿仅略高于零；它是补充事件，不是保证上涨或重仓依据。
- 银手指没有因为反转金上线而获得额外证据；真实面板仍从 2024-05 开始且整体偏牛，
  银侧阈值和镜像反转银仍需独立长历史研究，不能为了次数或对称性上线。
- 候选生成只使用 `<=t` 数据；`CONFIRMED/INVALIDATED` 仍合法地读取 `t+1` 收盘，因此在确认日收盘前不能知道正式状态。此前“用确认日涨跌筛样本、又从候选日收盘起算”的选择偏差已修复，但 `confirm_date_close` 仍不是可成交价；若要宣称策略收益，必须改用下一可成交价并计入滑点、费用、停牌和涨跌停约束。
- 市场择时更适合作为候选 ranker 的上下文因子，不适合作为硬开关；硬开关容易漏掉个股右尾。
- 运维：`market_timing_panel` 库缓存 TTL=24h + 进程内 30min，**算法变更不会自动失效**。改 signal/factors 算法后必须两步：① `docker compose up --build -d alphaagent-api`（+ `alphaagent-web` 若改前端）重建镜像让容器代码跟上源码（2026-07-04 即发现本地容器停在 v2.4.1，而源码已更新）；② `POST /api/market-timing/refresh` 强制重算落库。否则线上/本地/源码三方展示不同版本事件，极易被误判为未来函数。
- 线上 `agu.yantiandao.com` 是否已升级到 v5 尚未验证；本地变更需要后续 tag/发布流程对齐线上。
- no-lookahead 守护测试覆盖候选存在性、次日确认、否决候选保留、连续区域去重和离开后同方向重发。见 `tests/alphaagent/services/quant/test_market_timing_no_lookahead.py`。
- `/market` 日期一致性守护覆盖盘后行情 overlay、当天 K 线替换、盘中 context 日期复制、当前方向和逐日序列。见 `tests/alphaagent/services/quant/test_market_timing_intraday.py`。
