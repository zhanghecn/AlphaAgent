# AlphaAgent 量化实现流程审查

本文说明 AlphaAgent 当前量化功能的真实实现：数据如何进入本地库，如何生成候选，如何执行回测，哪些结果可信，哪些地方仍不能支撑结论。

本文描述工程实现和验证口径，不构成投资建议。

## 0. 当前结论

当前默认组合回测不是“拿今天候选名单回测全部历史”，而是历史逐日动态重算：

```text
D 日收盘可见数据 -> 生成下一交易日买入/卖出计划 -> 下一交易日尾盘执行
```

默认执行模型是 `strict_1430`：

- `strict_1430`：必须有执行日 `14:30` 的 `1m` 分钟快照，否则拒单。
- `tail_close_hybrid`：研究对比模型；有 `14:30` 快照时使用真实分钟价，缺快照时使用执行日日线收盘价作为 `daily_close_proxy` 尾盘代理。
- `legacy_next_open`：只作为旧报告兼容，不是当前默认研究口径，也不作为普通用户新的验证目标。

当前已注册策略是：

```python
STRATEGY_ID = "mainline_leader_pullback"
STRATEGY_VERSION = "0.1.1"
BREAKOUT_STRATEGY_ID = "breakout_confirmation"
BREAKOUT_STRATEGY_VERSION = "0.1.0"
LIMIT_UP_PULLBACK_STRATEGY_ID = "limit_up_after_pullback"
LIMIT_UP_PULLBACK_STRATEGY_VERSION = "0.1.0"
TREND_ACCELERATION_STRATEGY_ID = "trend_acceleration"
TREND_ACCELERATION_STRATEGY_VERSION = "0.1.0"
```

低吸策略是“主线强势股回踩 MA5 低吸”，突破策略是“平台放量突破确认”，涨停后回踩策略是“近 20 日有涨停、回踩 MA5/MA20 未破坏的强势股确认”，趋势加速策略是“趋势已形成且温和加速、但尚未明显过热的强势股确认”。不同买点必须由独立策略解释，不能靠硬改低吸策略门槛覆盖所有形态。

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
- 候选面板：[frontend/src/features/quant/RecommendationsPanel.tsx](/root/project/ai/vnpy/frontend/src/features/quant/RecommendationsPanel.tsx)
- 回测参数：[frontend/src/features/quant/BacktestParamsForm.tsx](/root/project/ai/vnpy/frontend/src/features/quant/BacktestParamsForm.tsx)
- 回测结果：[frontend/src/features/quant/BacktestPanel.tsx](/root/project/ai/vnpy/frontend/src/features/quant/BacktestPanel.tsx)
- 日期/股票账本：[frontend/src/features/quant/BacktestDrilldownPanel.tsx](/root/project/ai/vnpy/frontend/src/features/quant/BacktestDrilldownPanel.tsx)
- 数据补齐：[frontend/src/features/quant/MinuteDataWizard.tsx](/root/project/ai/vnpy/frontend/src/features/quant/MinuteDataWizard.tsx)

## 2. 数据层

核心表：

- `stocks`：股票基础信息、最新价、市值、成交额等。
- `stock_daily_bars`：日线，是筛选、持仓估值和尾盘混合代理的主数据。
- `stock_minute_bars`：分钟线。量化严格回测主流程只使用 `1m / 14:30` 快照。
- `stock_financial_reports`：财报摘要，只有 `publish_date <= trade_date` 时才可参与回测评分。
- `sector_period_scores`：板块强度。
- `stock_fund_flows`：个股资金流。
- `stock_hot_ranks`：热度。
- `stock_lhb_records`：龙虎榜。
- `quant_signal_runs`：每次筛选运行。
- `quant_stock_signals`：单股评分明细。
- `quant_recommendations`：推荐列表，区分 `BUY` 和 `WATCH`。
- `backtest_runs`：回测主记录。
- `backtest_orders`：回测订单，包括 `pending`、`filled`、`rejected`。
- `backtest_trades`：真实组合成交。
- `backtest_daily_equity`：每日现金、持仓市值、总权益、持仓数量。
- `backtest_daily_positions`：每日逐股持仓快照。
- `backtest_signal_events`：组合回测附带生成的全股票理论信号计划。

`backtest_signal_events` 不受组合现金、最大持仓槽位和仓位竞争约束，目的是回答“这只股票历史上有没有触发当前策略信号”。真实组合盈亏必须以 `backtest_orders`、`backtest_trades`、`backtest_daily_equity` 和 `backtest_daily_positions` 为准。

## 3. 选股评分流程

筛选入口：

```python
screen_stocks(
    trade_date=None,                 # 不传则使用 stock_daily_bars 最新交易日
    max_symbols=500,                 # 从股票池中取前 N 只
    recommendation_limit=20,         # 最多返回推荐数量
    min_recommendation_score=60.0,   # 推荐展示线，不等于买点硬门槛
    persist=False,                   # 是否写入 quant_* 表
    included_boards=("main",),       # 默认只跑主板
)
```

注释式流程：

```python
# 1. 确认数据库可用，并创建量化相关表。
_ensure_quant_schema()

# 2. 找筛选日期；页面不指定时使用日线表里的最新交易日。
as_of = trade_date or latest_trade_date()

# 3. 生成股票池。
#    默认 included_boards=["main"]，即只筛主板。
#    创业板、科创板、北交所必须在页面显式勾选。
stock_rows = load_stock_universe(max_symbols, included_boards)

# 4. 拉取每只股票截至 as_of 的最近约 160 根日线。
#    注意：不会读取 as_of 之后的数据。
bars_by_symbol = load_bars(symbols, as_of, lookback_days=160)

# 5. 拉取辅助因子。
#    财报必须使用 publish_date <= as_of 的记录。
index_return_20d = load_index_return_20d(as_of)
sector_scores = load_sector_scores(symbols, as_of)
financial_scores = load_financial_scores(symbols, as_of)
fund_flow_scores = load_fund_flow_scores(symbols, as_of)
hot_rank_scores = load_hot_rank_scores(symbols, as_of)
lhb_scores = load_lhb_scores(symbols, as_of)

# 6. 对每只股票打分。
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

# 7. 只保留 evidence.status == "ready" 的股票。
#    日线不足 60 根的股票不会进入有效评分。

# 8. 生成推荐：
#    - entry_signal=True：动作是 BUY。
#    - 分数达到展示线但 entry_signal=False：动作是 WATCH。
#    WATCH 只是观察，默认组合回测不会买。

# 9. persist=True 时写入 quant_signal_runs、quant_stock_signals、quant_recommendations。
#    auto_portfolio=True 时，仅把最后一个交易日同步到“量化候选”分组。
```

当前买点条件：

```python
# 当前策略只做 MA5 附近低吸。
pullback_near_ma = -1.5 <= ma5_distance_pct <= 2.0

entry_signal = (
    total_score >= 68
    and pullback_near_ma
    and risk_score >= 35
    and liquidity_score >= 25
)
```

评分权重：

- 相对强弱：25%
- 洗盘/回踩结构：20%
- 趋势质量：15%
- 板块主线：12%
- 财务改善：10%
- 资金/热度/龙虎榜代理：8%
- 流动性：10%

## 4. 区间候选流程

区间入口：

```python
screen_stocks_range(
    start=date(2025, 10, 14),
    end=None,                        # 不传则使用本地最新交易日
    persist=True,
    auto_portfolio=True,
)
```

注释式流程：

```python
# 1. 从 stock_daily_bars 聚合 start/end 之间真实存在的交易日。
trade_dates = trading_dates_between(start, end)

# 2. 按交易日升序逐日调用同一套 screen_stocks。
for trade_date in trade_dates:
    screen_stocks(
        trade_date,
        persist=True,
        auto_portfolio=False,
    )

# 3. 只有最后一个交易日同步到“量化候选”持仓分组。
#    历史日期用于核查，不代表当前分组持仓。
screen_stocks(
    trade_dates[-1],
    persist=True,
    auto_portfolio=True,
)
```

前端候选页已经拆成两个日期：

- `生成区间起点`：从该交易日到最新交易日逐日生成候选。
- `查看交易日`：查看某一天候选，可核查 BUY/WATCH 和失败规则。

## 5. 组合回测流程

回测入口：

```python
run_backtest(
    BacktestParams(
        start=date(2025, 10, 14),
        end=None,
        initial_cash=1_000_000,
        max_positions=8,
        max_position_pct=0.125,
        min_entry_score=68,
        strict_entry=True,
        execution_model="strict_1430",
        minute_interval="1m",
        tail_entry_start="14:30",
        tail_entry_end="14:30",
        tail_entry_ma5_tolerance_pct=1.5,
    )
)
```

主循环：

```python
for current_day in trading_days:
    # 1. 执行此前收盘后生成、今天要卖出的 pending 卖单。
    #    tail_close_hybrid：
    #      - 有 current_day 14:30 的 1m bar：minute_1430_sell。
    #      - 没有 current_day 14:30 的 1m bar：daily_close_proxy_sell。
    #    strict_1430：
    #      - 缺 14:30 bar：拒单并继续持仓。
    #    legacy_next_open：
    #      - 旧报告兼容路径，普通入口不使用。
    execute_pending_sells(current_day)

    # 2. 执行昨天收盘后生成、今天尾盘要买的 pending 买单。
    #    tail_close_hybrid 研究对比：
    #      - 有 current_day 14:30 的 1m bar：minute_1430。
    #      - 没有 current_day 14:30 的 1m bar：daily_close_proxy。
    #    strict_1430：
    #      - 没有 14:30 bar 或价格偏离 MA5：拒单。
    execute_pending_buys(current_day)

    # 3. 用当前日收盘可见数据对当前持仓检查退出信号。
    #    这里只生成下一交易日 pending_sells，不能用当前日收盘信号在当前日 14:30 卖出。
    plan_exits_for_next_trading_day(current_day)

    # 4. 用当前日收盘可见数据重新选股。
    #    这些候选不会在当前日买入，而是生成下一交易日的 pending_buys。
    candidates = score_day(current_day)
    pending_buys.extend(plan_for_next_trading_day(candidates))

    # 5. 记录每日组合资金和逐股持仓快照。
    record_daily_equity(current_day)
    record_daily_positions(current_day)

    # 6. 记录全股票理论信号计划。
    #    这只用于核查历史信号，不替代真实组合资金曲线。
    record_signal_events(current_day)
```

买入撮合：

```python
if execution_model == "tail_close_hybrid":
    # 优先使用执行日 14:30 真实分钟快照。
    if has_1430_minute_bar:
        fill_price = minute_1430.close
        mode = "minute_1430"
    else:
        # 历史没有分钟线时，用执行日收盘价代理尾盘成交。
        fill_price = daily_bar.close
        mode = "daily_close_proxy"

elif execution_model == "strict_1430":
    # 严格模式不允许代理价格。
    if has_1430_minute_bar:
        fill_price = minute_1430.close
        mode = "minute_1430"
    else:
        reject("tail_entry_not_triggered")

elif execution_model == "legacy_next_open":
    # 仅用于旧报告兼容。
    fill_price = next_day_open_or_legacy_tail_fill
```

卖出撮合：

```python
if close <= cost_price * (1 - stop_loss_pct):
    reason = "stop_loss"
elif close >= cost_price * (1 + take_profit_pct):
    reason = "take_profit"
elif close <= highest_price * (1 - trailing_stop_pct):
    reason = "trailing_stop"
elif holding_days >= time_stop_days * 2:
    reason = "time_stop"

# 以上退出信号在 D 日收盘后生成，只能在下一交易日执行。
if execution_model == "tail_close_hybrid":
    sell_next_trade_day_at_1430_or_daily_close_proxy()
elif execution_model == "strict_1430":
    sell_next_trade_day_at_1430_or_reject_and_keep_position()
elif execution_model == "legacy_next_open":
    sell_next_open()
```

费用和成交约束：

- 买入佣金：`amount * commission_rate`
- 卖出佣金和印花税：`amount * (commission_rate + stamp_tax_rate)`
- 滑点：买入加滑点，卖出减滑点。
- A 股按 100 股取整。
- 涨停或接近涨停保守判定买不到。
- 跌停或接近跌停保守判定卖不出。
- 仓位满、现金不足会拒单。

## 6. 结果如何核查

真实组合结果看：

- `backtest_orders`：订单、拒单、原因、执行来源。
- `backtest_trades`：成交、费用、盈亏。
- `backtest_daily_equity`：每日现金、持仓市值、总权益、回撤。
- `backtest_daily_positions`：每日逐股持仓金额、成本、浮盈、仓位占比。

信号核查看：

- `backtest_signal_events`：全股票理论信号计划。
- `GET /api/backtests/{id}/signal-events/amount-preview`：按输入资金做等权金额预览。

注意：

- 金额预览不是组合资金曲线，不考虑同一天多个信号之间的现金争用。
- 单股回测可以看这只股票的买卖点，但组合盈亏仍以组合回测为准。
- 旧回测没有逐股持仓快照或信号计划时，需要重跑新回测。

前端已经支持：

- 回测结果中分页查看全部成交。
- 点击日期看当天现金、持仓市值、总权益、订单、买入、卖出、持仓。
- 点击股票看该股订单、成交、闭仓、持仓路径。

## 7. 分钟数据和严格 14:30

量化主流程只认：

```text
1m / 14:30 快照
```

不要把 `5m/10m` 当作严格 14:30 的替代。通用股票 K 线查看可以保留 5m/15m/30m/60m，但那是行情查看能力，不是严格回测主流程。

分钟补数主入口：

```text
sync_stock_minute_bars
```

模式：

- `mode=recent`：同步近端分钟线，适合收盘后补最近交易日。
- `mode=backtest_gaps`：按回测缺口补执行日 `14:30` 快照。

数据源判断：

- AkShare/东方财富公共分钟线适合近端交易日，不保证覆盖 2025 到当前全区间。
- TDX/Tushare/vn.py 本地库可以作为补数来源，但必须用缺口审计确认覆盖。
- CSV 只作为供应商或本地文件兜底，不是推荐主流程。

严格回测只有在缺口覆盖后才有解释价值：

```python
audit = audit_1430_gaps(backtest_id)

if audit.coverage_pct < 100:
    return "blocked_by_minute_gaps"

run_backtest(execution_model="strict_1430")
```

## 8. 金安国纪复核口径

金安国纪 `002636.SZSE`：

- 是主板，默认量化股票池不会因板块排除它。
- 当前低吸策略历史上可以出现买点。
- 但如果某天价格远离 MA5、属于突破/强势加速，当前低吸策略不应该买。

正确复核方式：

1. 查该股信号历史：哪天 `entry_signal=True`，哪天只是 `WATCH`。
2. 查组合回测订单：是否下单、是否成交、是否拒单。
3. 查拒单原因：仓位满、现金不足、涨停、尾盘未触发、缺 14:30 快照。
4. 判断买点类型：低吸、突破、涨停后确认、趋势加速。

后续应继续按独立策略复核低吸、突破、涨停后回踩和趋势加速，不要把所有买点塞进 `mainline_leader_pullback`。

## 9. 财报缺失口径

必须区分：

```text
股票详情页财报：现在能通过外部源查到。
回测可用财报：本地已落库，并且 publish_date <= trade_date。
```

如果详情页有财报，但量化提示缺失，通常原因是：

- 财报没有落库到 `stock_financial_reports`。
- 财报没有 `publish_date`。
- `publish_date` 晚于当时的 `trade_date`，不能用于防未来函数的回测评分。

后续页面应显示本地财报记录数、最近可用 `publish_date` 和是否参与当前交易日评分。

## 10. 正确量化回测的最低要求

1. 历史逐日动态股票池。
2. 只使用当日及以前可见数据。
3. 财报用披露日，不用报告期末日期提前生效。
4. 明确执行模型：真实 14:30、收盘代理、严格拒单或旧版开盘兼容。
5. 计入佣金、印花税、滑点、整数手。
6. 处理涨停买不到、跌停卖不出、停牌/缺 K 线。
7. 记录订单、成交、拒单原因。
8. 记录每日现金、持仓市值、总权益、逐股持仓。
9. 支持日期归因和个股归因。
10. 报告执行真实性：14:30 真实占比、收盘代理占比、拒单数。
11. 做样本外、walk-forward、参数敏感性和成本压力测试。

当前 AlphaAgent 已具备 1-10 的基础能力，11 仍需要继续增强。

## 11. 当前可信边界

可以相信：

- 候选不是每天同一批，而是逐交易日动态评分。
- 默认回测只买 `BUY`，不买 `WATCH`。
- 资金会随卖出释放后继续用于后续买入。
- 订单、成交、现金、持仓市值、总权益可追溯。
- 财报评分遵守 `publish_date <= trade_date` 的防未来函数边界。

不能过度相信：

- `tail_close_hybrid` 如果多数成交是 `daily_close_proxy`，不能宣称纯分钟真实回测。
- `strict_1430` 如果买入很少，可能是分钟覆盖不足，不代表策略一定无效。
- 单一低吸策略不能解释全部强势股票买点。
- 本地样本不是全 A 全历史覆盖时，收益不能外推。

## 12. 下一步

优先级：

1. 保持普通回测默认严格 14:30，尾盘混合只作为高级研究对比。
2. 继续完善信号计划和订单链接，避免误读为真实成交。
3. 执行模型对比只保留 `tail_close_hybrid` 和 `strict_1430` 的当前口径；`legacy_next_open` 只用于识别旧报告。
4. 继续完善金安国纪专项审计面板，把组合回测 ID 下的买/没买原因和多策略表现合并成完整诊断。
5. 按同一严格 14:30 口径继续验证低吸、突破、涨停后回踩和趋势加速策略。
6. 同步并落库财报，展示回测可用财报覆盖率。
7. 构造小样本确定性测试，逐笔校验现金、持仓和总权益。
