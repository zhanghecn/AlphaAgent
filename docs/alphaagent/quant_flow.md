# AlphaAgent 量化实现流程审查

本文说明 AlphaAgent 当前量化功能的真实实现：数据如何进入本地库，如何生成候选，如何执行回测，哪些结果可信，哪些地方还不能支撑结论。

本文描述的是当前工程状态，不是投资建议。

## 0. 当前结论

截至 2026-06-12，本地 Docker 环境中：

- 当前量化策略版本：`mainline_leader_pullback / 0.1.1`。
- 最新组合回测样本：回测 `#29`，区间 `2025-10-14` 至 `2026-06-12`，总收益约 `-9.00%`，最大回撤约 `-16.21%`。
- `#29` 的交易记录实际到 `2026-06-12`；“最近买卖点”排序已修复，报告接口现在按最近成交返回。
- `stock_daily_bars` 有约 97.97 万行，覆盖 `2025-03-26` 至 `2026-06-12`，约 4001 个标的。
- `stock_minute_bars` 只有约 2.35 万行，覆盖 `2026-06-11` 至 `2026-06-12` 的 98 个标的，不能支撑长区间严格尾盘回测。
- `stock_financial_reports` 当前为 0 行，所以筛选/回测里的财务改善分会降级为中性；股票详情页能看到财报，是因为详情接口实时回退到 AkShare，并没有把这些财报持久化进回测库。
- `stock_daily_bars.turnover` 同步链路已修复：股票日线优先使用腾讯 `newfqkline` 带成交额接口，成交额从“万元”换算为“元”后落库。
- 历史全表仍需重跑 `sync_stock_daily_bars` 才能补齐旧数据；金安国纪 `002636.SZSE` 已定向回填 250 根日线，`turnover` 覆盖约 99.6%。

## 1. 代码入口

后端：

- 筛选 API：[alphaagent/server/api/quant.py](/root/project/ai/vnpy/alphaagent/server/api/quant.py)
- 回测 API：[alphaagent/server/api/backtests.py](/root/project/ai/vnpy/alphaagent/server/api/backtests.py)
- 筛选服务：[alphaagent/server/services/quant/screening.py](/root/project/ai/vnpy/alphaagent/server/services/quant/screening.py)
- 因子评分：[alphaagent/server/services/quant/factors.py](/root/project/ai/vnpy/alphaagent/server/services/quant/factors.py)
- 回测引擎：[alphaagent/server/services/backtest/engine.py](/root/project/ai/vnpy/alphaagent/server/services/backtest/engine.py)
- 数据同步：[alphaagent/server/services/data_sync.py](/root/project/ai/vnpy/alphaagent/server/services/data_sync.py)
- 表结构：[alphaagent/server/db/schema.py](/root/project/ai/vnpy/alphaagent/server/db/schema.py)

前端：

- 量化页面：[frontend/src/pages/QuantTradingPage.tsx](/root/project/ai/vnpy/frontend/src/pages/QuantTradingPage.tsx)
- 回测面板：[frontend/src/features/quant/BacktestPanel.tsx](/root/project/ai/vnpy/frontend/src/features/quant/BacktestPanel.tsx)
- 回测表格：[frontend/src/features/quant/BacktestTables.tsx](/root/project/ai/vnpy/frontend/src/features/quant/BacktestTables.tsx)
- vn.py 状态：[frontend/src/features/quant/VnpyStatusPanel.tsx](/root/project/ai/vnpy/frontend/src/features/quant/VnpyStatusPanel.tsx)
- 流程状态条：[frontend/src/features/quant/QuantWorkflowGuide.tsx](/root/project/ai/vnpy/frontend/src/features/quant/QuantWorkflowGuide.tsx)

## 2. 数据层

核心表：

- `stocks`: 股票基础信息、最新价、市值、成交额等。
- `stock_daily_bars`: 日线，是筛选和普通回测的主数据。
- `stock_minute_bars`: 1 分钟线，只用于验证 D+1 尾盘接近 MA5 的入场。
- `stock_financial_reports`: 财报摘要，用于财务改善评分。
- `sector_period_scores`: 板块强度。
- `stock_fund_flows`: 个股资金流。
- `stock_hot_ranks`: 热度。
- `stock_lhb_records`: 龙虎榜。
- `quant_signal_runs`: 每次筛选运行。
- `quant_stock_signals`: 单股评分明细。
- `quant_recommendations`: 推荐列表。
- `backtest_runs`: 回测主记录。
- `backtest_signal_events`: 组合回测附带生成的全股票理论买卖点流水，用于核查每只股票历史何时触发买入/卖出。
- `backtest_orders`: 回测订单，包括 pending、filled、rejected。
- `backtest_trades`: 回测成交。
- `backtest_daily_equity`: 每日总现金、持仓市值、总权益、持仓数量。
- `backtest_metrics`: 指标键值。

`backtest_daily_positions` 已新增。新回测会记录每日每只股票的持仓数量、成本、市值、浮盈和仓位占比；旧回测没有这张快照，只能展示总权益和成交流水。

`backtest_signal_events` 只在组合回测生成，单股回测不写这张表。它是不受组合资金、最大持仓槽位和现金占用约束的理论信号流水，目的是回答“这只股票历史上有没有触发过当前策略买点/卖点”。真实组合盈亏仍以 `backtest_orders`、`backtest_trades`、`backtest_daily_equity` 和 `backtest_daily_positions` 为准。

## 3. 筛选流程

策略常量：

```python
STRATEGY_ID = "mainline_leader_pullback"
STRATEGY_VERSION = "0.1.1"
```

筛选入口：

```python
screen_stocks(
    trade_date=None,                 # 不传则使用 stock_daily_bars 最新交易日
    max_symbols=500,                 # 从股票池中取前 N 只
    recommendation_limit=20,         # 最多返回推荐数量
    min_recommendation_score=60.0,   # 推荐展示分数线，不等于买点硬门槛
    persist=False,                   # 是否写入 quant_* 表
    included_boards=("main",),       # 默认只跑主板
)
```

注释式流程：

```python
# 1. 确认数据库可用，并创建量化相关表
_ensure_quant_schema()

# 2. 找筛选日期；页面不指定时使用日线表里的最新交易日
as_of = trade_date or latest_trade_date()

# 3. 生成股票池
#    默认 included_boards=["main"]，即只筛主板；
#    科创板、创业板、北交所必须在页面显式勾选。
stock_rows = load_stock_universe(max_symbols, included_boards)

# 4. 拉取每只股票最近约 160 根日线
bars_by_symbol = load_bars(symbols, as_of, lookback_days=160)

# 5. 拉取辅助因子
index_return_20d = load_index_return_20d(as_of)
sector_scores = load_sector_scores(symbols, as_of)
financial_scores = load_financial_scores(symbols, as_of)
fund_flow_scores = load_fund_flow_scores(symbols, as_of)
hot_rank_scores = load_hot_rank_scores(symbols, as_of)
lhb_scores = load_lhb_scores(symbols, as_of)

# 6. 对每只股票打分
score = score_stock(
    vt_symbol,
    bars,
    as_of,
    index_return_20d=index_return_20d,
    sector_score=sector_scores.get(vt_symbol),
    financial_score=financial_scores.get(vt_symbol),
    fund_flow_score=fund_flow_scores.get(vt_symbol),
    hot_rank_score=hot_rank_scores.get(vt_symbol),
    lhb_score=lhb_scores.get(vt_symbol),
)

# 7. 只保留 evidence.status == "ready" 的股票
#    日线不足 60 根的股票不会进入有效评分。

# 8. 按总分降序排序，生成推荐
#    推荐条件是 entry_signal=True 或 total_score >= min_recommendation_score。

# 9. persist=True 时，写入 quant_signal_runs、quant_stock_signals、quant_recommendations
#    auto_portfolio=True 时，同步到“量化候选”持仓分组。
```

候选核查接口：

- `GET /api/quant/trading-dates?limit=600`：从本地 `stock_daily_bars` 聚合真实交易日，前端候选和回测开始日期选择器使用它，避免选到周末或无日线数据日期。
- `GET /api/quant/screen-runs?limit=120`：列出已持久化的筛选运行，前端候选日期选择器会叠加显示运行编号和候选数；未运行的交易日可先选中再点“运行筛选”生成当天候选。
- `GET /api/quant/recommendations?trade_date=YYYY-MM-DD&limit=200`：按指定日期返回当日推荐；如果这天没有持久化运行，会回退到当日日线对应的推荐记录。
- 候选表的 `reason` 已包含 `risk_score`、`liquidity_score` 和 `failed_rules`，用于核查为什么某只股票只是观察或未通过买点门槛。

## 4. 因子评分

单股评分入口：

```python
score_stock(vt_symbol, bars, trade_date, ...)
```

总分权重：

- 相对强弱 `relative_strength_score`: 25%
- 洗盘/回踩结构 `washout_score`: 20%
- 趋势质量 `trend_quality_score`: 15%
- 板块主线 `sector_mainline_score`: 12%
- 财务改善 `financial_improvement_score`: 10%
- 资金/热度/龙虎榜代理 `smart_money`: 8%
- 流动性 `liquidity_score`: 10%
- 风险分 `risk_score`: 当前不直接加权，只作为入场过滤。

买点条件：

```python
pullback_near_ma = -1.5 <= ma5_distance_pct <= 2.0

entry_signal = (
    total >= 68
    and pullback_near_ma
    and risk >= 35
    and liquidity >= 25
)
```

中文注释：

```python
# total >= 68：
#   综合分达到策略门槛。

# pullback_near_ma：
#   最新收盘价必须贴近 5 日均线。
#   这是“尾盘 5 日线附近低吸”的日线预筛。

# risk >= 35：
#   近期回撤和单日跌幅不能过高。

# liquidity >= 25：
#   20 日平均成交额要达到基本流动性要求。
#   优先使用 stock_daily_bars.turnover（元）。
#   如果旧数据缺失 turnover，则按 A 股日线常见单位“手”估算：
#   close_price * volume * 100。
```

重要边界：

- 系统不会证明“主力真实洗盘”，只把价格、成交量、资金流、热度、龙虎榜转为代理信号。
- 财报缺失不会剔除股票，财务分默认中性 50。
- 当前财报表为空，所以财务改善在筛选/回测中实际没有加分。

## 5. 回测流程

回测入口：

```python
run_backtest(BacktestParams(...))
```

关键参数：

```python
BacktestParams(
    start=date(2020, 1, 1),
    end=None,                         # 不传则使用本地日线最新交易日
    initial_cash=1_000_000,
    max_positions=8,
    max_position_pct=0.125,           # 单只股票最多使用初始资金 12.5%
    commission_rate=0.0003,
    stamp_tax_rate=0.0005,
    slippage_bps=10,
    stop_loss_pct=0.07,
    take_profit_pct=0.18,
    trailing_stop_pct=0.08,
    time_stop_days=15,
    candidate_limit=20,
    max_symbols=500,
    min_entry_score=68.0,
    strict_entry=True,
    intraday_entry=True,
    minute_entry_required=False,
    tail_entry_start="14:30",
    tail_entry_end="14:57",
    tail_entry_ma5_tolerance_pct=1.5,
)
```

注释式主循环：

```python
for current_day in trading_days:
    # 1. 先处理今天该执行的卖出单
    #    卖出信号是在前一交易日收盘后确认，
    #    今天开盘价加滑点成交。
    execute_pending_sells(current_day)

    # 2. 再处理今天该执行的买入单
    #    买入信号是在前一交易日收盘后生成，
    #    今天尝试尾盘分钟成交；缺分钟时可回退开盘。
    execute_pending_buys(current_day)

    # 3. 对当前持仓检查卖出条件
    #    止损、止盈、跟踪止损、时间止损都在收盘后确认，
    #    实际成交排到下一交易日开盘。
    for position in positions:
        sell_reason = check_exit_signal(position, current_day)
        if sell_reason:
            create_pending_sell(next_trading_day)

    # 4. 如果还有仓位空位，按当日收盘数据重新打分
    #    注意：这是历史逐日动态候选，不是把今天候选套到过去。
    candidates = score_day(current_day)
    create_pending_buy_orders(candidates, next_trading_day)

    # 5. 记录每日总权益和每日逐股票持仓快照
    #    backtest_daily_equity 记录现金、持仓总市值、总权益、持仓数量；
    #    backtest_daily_positions 记录每只持仓的成本、市值、浮盈和仓位占比。
    record_daily_equity(current_day)
    record_daily_positions(current_day)

    # 6. 组合回测额外生成全股票理论信号流水
    #    这条流水对每只股票独立维护“理论是否持仓”状态：
    #    没有理论持仓时，满足入场规则就记 BUY；
    #    已有理论持仓时，不再重复记 BUY；
    #    满足止损、止盈、跟踪止损或时间止损时，下一交易日有日线开盘价才记 SELL。
    #    它用于核查候选和买卖点，不用于替代真实组合资金曲线。
    record_signal_events(current_day)
```

买入撮合：

```python
if intraday_entry:
    # 使用信号日可见的 5 日均线，避免未来函数
    ma5 = ma5_for_signal_day(signal_date)

    # 在 D+1 的 14:30-14:57 分钟线里找接近 MA5 的价格
    trigger = find_tail_minute_bar(current_day, ma5)

    if trigger:
        # 真实分钟尾盘成交
        fill_price = trigger.close_price
        mode = "minute_tail_ma5"
    elif minute_entry_required:
        # 严格模式：没有触发就拒绝，不允许伪成交
        reject_order("tail_entry_not_triggered")
    else:
        # 宽松模式：缺分钟或没触发时，回退到 D+1 开盘
        fill_price = daily_open_price
        mode = "daily_next_open_fallback"
else:
    # 不启用分钟入场时，直接 D+1 开盘模拟
    fill_price = daily_open_price
    mode = "daily_next_open"
```

卖出撮合：

```python
# 当前可信版本 0.1.1：
# D 日收盘后确认退出信号，D+1 开盘成交。

if close <= cost_price * (1 - stop_loss_pct):
    reason = "stop_loss"
elif close >= cost_price * (1 + take_profit_pct):
    reason = "take_profit"
elif close <= highest_price * (1 - trailing_stop_pct):
    reason = "trailing_stop"
elif holding_calendar_days >= time_stop_days * 2:
    reason = "time_stop"
```

费用和成交约束：

- 买入佣金：`amount * commission_rate`
- 卖出佣金和印花税：`amount * (commission_rate + stamp_tax_rate)`
- 滑点：买入加滑点，卖出减滑点。
- A 股按 100 股取整。
- 涨停开盘不买，跌停开盘不卖。
- 仓位满时拒绝新买入。

## 6. 回测现在能回答什么

当前能回答：

- 回测区间、样本股票数、交易日数。
- 总收益、年化收益、最大回撤、胜率、盈亏比、Sharpe。
- 每笔成交：日期、股票、方向、价格、数量、成交金额、费用、卖出盈亏、原因。
- 每日总权益：现金、持仓总市值、总权益、持仓数量、回撤。
- 成交真实性：尾盘分钟成交数量、开盘回退数量、缺分钟比例。
- 订单约束：pending、filled、rejected 以及原因。

新回测还能回答：

- 点击某个交易日，列出当天每只持仓的市值、成本、浮盈、仓位占比。
- 点击某个股票，展示完整持仓周期的每日持仓金额变化。
- 在组合回测页直接按日期钻取“当天买了什么、卖了什么、剩余现金、持仓市值、总权益”。
- 在组合回测页“信号流水”中，按日期、股票、方向查看全股票理论买卖点。
- 输入总资金和最大持仓数后，按 `每笔预算 = 总资金 / 最大持仓数` 预览理论买卖点金额；买入按 100 股整数手换算，卖出沿用最近一次理论买入数量。
- “组合最近成交”支持分页查看全部真实组合成交，不再只截取前 12 条。

相关接口：

- `GET /api/backtests?run_type=portfolio|symbol|all`：按组合/单股回测过滤列表；量化页默认只展示组合回测，避免单股回测把组合回测挤掉。
- `GET /api/backtests/{id}/trades?limit=20&offset=0&order=desc`：分页查看真实组合成交。
- `GET /api/backtests/{id}/days/{date}`：按日期钻取现金、持仓市值、总权益、当日买卖、逐股持仓。
- `GET /api/backtests/{id}/symbols/{vt_symbol}`：按股票钻取买卖记录和每日持仓轨迹。
- `GET /api/backtests/{id}/equity`：返回该回测实际覆盖的每日权益日期，前端“信号流水”的开始/结束日期选择器使用它，只在回测交易日之间切换。
- `GET /api/backtests/{id}/signal-events`：查询组合回测生成的全股票理论信号流水，支持 `start`、`end`、`vt_symbol`、`side`、`limit`。
- `GET /api/backtests/{id}/signal-events/amount-preview`：按总资金和最大持仓数预览理论成交数量、金额和配对卖出盈亏。

边界：

- 新增快照只对修复后运行的新回测完整可用。
- 旧回测没有 `backtest_daily_positions` 历史快照，需要重跑才能看到逐股每日持仓。
- 旧回测没有 `backtest_signal_events`，需要重跑组合回测后才能看到全股票理论信号流水。
- 金额预览不是一条真实组合资金曲线，不考虑同一天多信号之间的现金争用，也不替代真实组合回测结果。
- 组合回测不是“拿今天候选回放历史”。它从 `start_date` 到 `end_date` 逐个交易日重新评分，只用当日及以前数据生成当日候选；买入占用现金和持仓槽位，卖出成交后释放现金和仓位，后续交易日会继续使用剩余现金和空出来的仓位。

## 7. 严格尾盘分钟回测

严格模式参数：

```python
minute_entry_required=True
intraday_entry=True
tail_entry_start="14:30"
tail_entry_end="14:57"
```

严格流程：

```python
# 1. 先审计缺口 CSV 是否已经有分钟线覆盖
audit = audit_minute_gaps(gap_csv)

# 2. 缺口未覆盖时，不运行严格回测
if audit.status != "ready":
    return "blocked_by_minute_gaps"

# 3. 缺口覆盖后，强制 minute_entry_required=True 运行回测
result = run_backtest(params)

# 4. 报告里必须显示所有买入是否来自 minute_tail_ma5
```

当前状态：

- 长区间严格尾盘回测仍不充分，因为分钟线只覆盖近端少量股票。
- 最新组合回测 `#29` 买入 94 笔，其中 1 笔是 `minute_tail_ma5`，93 笔是 `daily_next_open_fallback`。
- 因此 `#29` 可以用于检查日线策略和撮合顺序，但不能证明“尾盘 5 日线附近低吸”已经有效。

## 8. 金安国纪复核

金安国纪 `002636.SZSE` 当前：

- 在 `stocks` 表中存在。
- 是主板，默认股票池不会排除它。
- 在当前股票池排序中很靠前。
- 日线覆盖 `2025-06-03` 至 `2026-06-12`。
- 已定向回填最近 250 根日线成交额，最近日线示例：`2026-06-12 turnover=7,580,017,900` 元。

修复前没有入选的直接原因：

- `2026-06-12` 总分约 `68.31`，但 `entry_signal=False`。
- 收盘价距离 MA5 约 `+16.29%`，不满足 `-1.5%` 到 `+2.0%` 的“靠近 5 日线低吸”条件。
- 流动性分只有 `15`，低于入场过滤的 `25`；这和日线 `turnover` 缺失、用 `close * volume` 估算成交额有关。
- 财务改善分为中性 `50`，因为本地 `stock_financial_reports` 没有数据。

修复后历史诊断：

- `GET /api/quant/symbols/002636.SZSE/signal-history?limit=12` 对应服务层结果显示 `entry_signal_count=26`。
- 早期触发日期包括 `2025-08-29`、`2025-09-01`、`2025-09-16`、`2025-10-30`、`2025-11-11`、`2025-11-13`、`2025-12-17`。
- 这证明用户判断“历史上总会有一次”是对的；此前漏掉关键原因是日线成交额缺失导致流动性评分失真。

仍需注意：

- `2026-06-12` 这一天仍不是当前低吸策略买点，因为价格离 MA5 太远，属于强势加速/突破，不是“5 日线附近低吸”。
- 如果要抓这类位置，需要新增“突破/强势加速/涨停接力/回踩确认”等非低吸策略，不能只用当前低吸策略解释。

## 9. vn.py 状态

`/api/vnpy/status` 返回 `partial` 时，前端现在显示“本地回测可用 / A股插件待接入”。

真实含义：

- AlphaAgent 本地 PostgreSQL 日线回测可用。
- AlphaAgent 本地分钟线表有少量数据，可做部分分钟验证。
- 但 Docker API 镜像里没有安装官方 A 股 Datafeed/Gateway 插件。
- 当前 vn.py GUI 只登记 CTP Gateway，不是 A 股实盘连接状态。

需要避免的误解：

- “本地回测可用”不等于 A 股实盘就绪。
- “A股插件待接入”表示 vn.py 官方 A 股数据源/Gateway 还没有安装配置完成。
- 它只说明 AlphaAgent 自研本地数据和部分回测能力可用。

## 10. 正确的量化回测应该包含什么

正确的 A 股组合回测至少应包含：

1. 历史逐日动态股票池：每个交易日只使用当日及以前的数据重新选股。
2. 无未来函数：财报必须用披露日，不能用报告期末日期提前生效。
3. 可执行撮合：D 日收盘信号，D+1 或真实分钟窗口成交；不能当天收盘发现信号又当天低价成交。
4. 成本模型：佣金、印花税、滑点、整数手、涨跌停、停牌、仓位上限。
5. 交易流水：每笔订单、成交、拒绝原因都能追溯。
6. 持仓流水：每天现金、每只持仓市值、浮盈、总权益、仓位占比。
7. 个股归因：每只股票什么时候买、为什么买、什么时候卖、为什么卖、贡献多少盈亏。
8. 日期归因：点击某天能看到当天买入、卖出、持仓、现金、总资产变化。
9. 数据质量：日线覆盖、分钟线覆盖、财报覆盖、资金流/热度/龙虎榜覆盖。
10. 稳健性检查：样本内外、不同市场环境、成本压力、参数敏感性、随机基准。

当前 AlphaAgent 已补齐第 6-8 的基础能力：新回测会写每日逐股持仓，前端提供日期/股票钻取；组合回测还会生成全股票理论信号流水和等权金额预览，便于核查“历史上有没有买点”。严格尾盘分钟数据、财报落库和策略族扩展仍需继续完善。

## 11. 下一步建议

优先修复：

1. 全量重跑 `sync_stock_daily_bars`，补齐旧 `stock_daily_bars.turnover`，不要只依赖金安国纪单股回填。
2. 同步并落库财报：至少让 `sync_stock_financial_quarterly` 跑通一批高流动性股票，并在回测报告里显示财报覆盖率。
3. 重跑代表性组合回测，让 `backtest_daily_positions` 覆盖完整区间。
4. 为金安国纪这类强势行情新增独立策略：突破、加速、涨停接力、回踩确认，和当前低吸策略分开评估。
5. 长区间严格尾盘回测需要补齐历史 1 分钟数据后再判断胜率和收益。

再做增强：

- 给单股详情页增加“为什么没有入选”解释，展示总分、MA5 距离、流动性、风险、财务分和未通过的门槛。
- 把“低吸策略”和“突破策略”分开建模，避免用一个策略解释所有买点。
- 长区间严格尾盘回测需要补齐历史 1 分钟数据后再判断胜率和收益。
