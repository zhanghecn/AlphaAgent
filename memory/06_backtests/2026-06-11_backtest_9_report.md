# AlphaAgent 回测报告 9

- 生成时间：2026-06-11T16:42:39
- 回测区间：2025-10-14 至 2026-06-11
- 策略：mainline_leader_pullback / 0.1.0
- 样本：股票库 4535，区间有日线 1582，满足 >=80 根日线 1551，覆盖率 34.88423373759647%
- 初始资金：1000000.00，期末权益：1446418.16
- 总收益率：44.64%，年化：78.19%，最大回撤：-6.87%
- 平仓交易：177，胜率：53.67%，盈亏比：1.87，Sharpe：3.04
- 平均盈利：9621.89，平均亏损：-5957.63
- 分钟尾盘成交：0，日线开盘回退成交：181

## 参数网格与反过拟合

- 参数组合：54
- 正收益组合占比：100.00%
- 样本外正收益组合占比：100.00%
- 跑赢样本等权占比：92.59%
- 高摩擦正收益占比：100.00%
- 当前参数总收益排名：39 / 54
- 当前参数样本外排名：46 / 54
- Walk-forward 折数：5
- Walk-forward 测试正收益占比：100.00%
- Walk-forward 测试超额为正占比：60.00%

## 执行规则

- D close signal; D+1 tail-window minute fill when stock_minute_bars is available, otherwise D+1 open fallback unless minute_entry_required=true
- uses prior visible daily MA5 and the configured intraday window; no same-day close look-ahead
- 成本：commission, stamp tax on sells, and slippage are included
- 仓位：equal cash budget per position, 100-share lot rounded

## 数据质量

- 日线：{'count': 275997}
- 分钟线：{'count': 22080}
- 财报：{'count': 2906}
- 资金流：{'count': 471}

## 统计

- 订单统计：{'total': 361, 'by_status': {'filled': 358, 'rejected': 3}, 'by_reason': {'entry_signal': 181, 'insufficient_cash': 3, 'stop_loss': 49, 'take_profit': 34, 'time_stop': 1, 'trailing_stop': 93}, 'rejected_examples': [{'id': 2124, 'backtest_id': 9, 'trade_date': '2026-04-27', 'vt_symbol': '688498.SSE', 'side': 'BUY', 'price': 1400.58919, 'volume': 0, 'status': 'rejected', 'reason': 'insufficient_cash', 'raw': {'ma5': 1408.1200000000001, 'mode': 'daily_next_open_fallback', 'price': 1399.19, 'status': 'filled', 'window': '14:30-14:57', 'reference_date': '2026-04-24', 'fallback_reason': 'minute_tail_entry_unavailable_or_not_triggered', 'minute_bar_count': 0}, 'created_at': '2026-06-11T08:16:40.386436+00:00'}, {'id': 2128, 'backtest_id': 9, 'trade_date': '2026-04-28', 'vt_symbol': '688498.SSE', 'side': 'BUY', 'price': 1468.5470799999998, 'volume': 0, 'status': 'rejected', 'reason': 'insufficient_cash', 'raw': {'ma5': 1414.188, 'mode': 'daily_next_open_fallback', 'price': 1467.08, 'status': 'filled', 'window': '14:30-14:57', 'reference_date': '2026-04-27', 'fallback_reason': 'minute_tail_entry_unavailable_or_not_triggered', 'minute_bar_count': 0}, 'created_at': '2026-06-11T08:16:40.386436+00:00'}, {'id': 2165, 'backtest_id': 9, 'trade_date': '2026-05-15', 'vt_symbol': '688498.SSE', 'side': 'BUY', 'price': 1584.6330499999997, 'volume': 0, 'status': 'rejected', 'reason': 'insufficient_cash', 'raw': {'ma5': 1654.6, 'mode': 'daily_next_open_fallback', 'price': 1583.05, 'status': 'filled', 'window': '14:30-14:57', 'reference_date': '2026-05-14', 'fallback_reason': 'minute_tail_entry_unavailable_or_not_triggered', 'minute_bar_count': 0}, 'created_at': '2026-06-11T08:16:40.386436+00:00'}]}
- 交易成本压力：[{'id': 'base', 'label': '原始成本', 'extra_bps': 0, 'extra_stamp_tax_bps': 0, 'extra_cost': 0.0, 'final_equity': 1446418.158672803, 'total_return_pct': 44.64181586728031, 'return_delta_pct': 0.0}, {'id': 'slippage_plus_10bps', 'label': '滑点再加10bp', 'extra_bps': 10, 'extra_stamp_tax_bps': 0, 'extra_cost': 42337.262559, 'final_equity': 1404080.8961138031, 'total_return_pct': 40.40808961138032, 'return_delta_pct': -4.233726255899988}, {'id': 'slippage_plus_30bps', 'label': '滑点再加30bp', 'extra_bps': 30, 'extra_stamp_tax_bps': 0, 'extra_cost': 127011.787677, 'final_equity': 1319406.370995803, 'total_return_pct': 31.940637099580304, 'return_delta_pct': -12.701178767700004}, {'id': 'stamp_tax_plus_5bps', 'label': '卖出税费再加5bp', 'extra_bps': 0, 'extra_stamp_tax_bps': 5, 'extra_cost': 10588.3415595, 'final_equity': 1435829.817113303, 'total_return_pct': 43.582981711330305, 'return_delta_pct': -1.0588341559500023}, {'id': 'high_friction', 'label': '高摩擦：滑点30bp+卖出5bp', 'extra_bps': 30, 'extra_stamp_tax_bps': 5, 'extra_cost': 137600.1292365, 'final_equity': 1308818.029436303, 'total_return_pct': 30.881802943630298, 'return_delta_pct': -13.76001292365001}]
- 样本内/样本外：{'status': 'ready', 'method': 'time_split_60_40', 'note': '按权益交易日时间切分的初步样本外检查，不是参数训练后的 walk-forward。', 'periods': [{'id': 'in_sample', 'label': '样本内 60%', 'start_date': '2025-10-14', 'end_date': '2026-03-06', 'days': 96, 'start_equity': 1000000.0, 'end_equity': 1103735.1783756008, 'return_pct': 10.373517837560087, 'max_drawdown_pct': -6.868521527487115, 'trade_count': 57, 'win_rate': 0.40350877192982454, 'pnl': 81892.78551280078, 'benchmark_return_pct': 25.895195154752493, 'excess_return_pct': -15.521677317192406}, {'id': 'out_of_sample', 'label': '样本外 40%', 'start_date': '2026-03-06', 'end_date': '2026-06-11', 'days': 66, 'start_equity': 1103735.1783756008, 'end_equity': 1446418.158672803, 'return_pct': 31.047572552823645, 'max_drawdown_pct': -6.593889284393539, 'trade_count': 120, 'win_rate': 0.6, 'pnl': 343661.51299200143, 'benchmark_return_pct': 10.579184262350694, 'excess_return_pct': 20.46838829047295}]}
- 市场环境分段：{'status': 'ready', 'benchmark_id': 'sample_equal_weight', 'method': '20 trading-day windows classified by sample equal-weight return', 'note': '指数日线缺失时使用样本等权基准划分强弱环境；这不是正式沪深指数市场分段。', 'periods': [{'regime': 'strong', 'window_count': 4, 'days': 80, 'max_drawdown_pct': -6.554053037366736, 'trade_count': 98, 'win_count': 50, 'pnl': 302218.8205824013, 'windows': [{'regime': 'strong', 'start_date': '2025-12-09', 'end_date': '2026-01-07', 'days': 20, 'strategy_return_pct': 0.0, 'benchmark_return_pct': 9.960133385312652, 'max_drawdown_pct': 0.0, 'trade_count': 0, 'win_count': 0, 'pnl': 0}, {'regime': 'strong', 'start_date': '2026-01-08', 'end_date': '2026-02-04', 'days': 20, 'strategy_return_pct': 2.1334689694689324, 'benchmark_return_pct': 5.725167061999992, 'max_drawdown_pct': -6.554053037366736, 'trade_count': 31, 'win_count': 13, 'pnl': 34911.4075080004}, {'regime': 'strong', 'start_date': '2026-02-05', 'end_date': '2026-03-12', 'days': 20, 'strategy_return_pct': 7.790788837485718, 'benchmark_return_pct': 6.18967740182077, 'max_drawdown_pct': -1.9952356523351256, 'trade_count': 35, 'win_count': 14, 'pnl': 46123.686878400484}, {'regime': 'strong', 'start_date': '2026-04-13', 'end_date': '2026-05-13', 'days': 20, 'strategy_return_pct': 19.168205534662096, 'benchmark_return_pct': 16.72973866729277, 'max_drawdown_pct': -0.887948752062373, 'trade_count': 32, 'win_count': 23, 'pnl': 221183.7261960004}], 'avg_strategy_return_pct': 7.2731158354041865, 'avg_benchmark_return_pct': 9.651179129106547, 'win_rate': 0.5102040816326531, 'label': '样本强势'}, {'regime': 'choppy', 'window_count': 4, 'days': 80, 'max_drawdown_pct': -6.411320414982602, 'trade_count': 75, 'win_count': 44, 'pnl': 154858.7806176009, 'windows': [{'regime': 'choppy', 'start_date': '2025-10-14', 'end_date': '2025-11-10', 'days': 20, 'strategy_return_pct': 0.0, 'benchmark_return_pct': 4.373265717560781, 'max_drawdown_pct': 0.0, 'trade_count': 0, 'win_count': 0, 'pnl': 0}, {'regime': 'choppy', 'start_date': '2025-11-11', 'end_date': '2025-12-08', 'days': 20, 'strategy_return_pct': 0.0, 'benchmark_return_pct': 0.13906048128684567, 'max_drawdown_pct': 0.0, 'trade_count': 0, 'win_count': 0, 'pnl': 0}, {'regime': 'choppy', 'start_date': '2026-03-13', 'end_date': '2026-04-10', 'days': 20, 'strategy_return_pct': -0.2590313755418516, 'benchmark_return_pct': -0.676415932831842, 'max_drawdown_pct': -6.411320414982602, 'trade_count': 29, 'win_count': 11, 'pnl': -33184.0289799997}, {'regime': 'choppy', 'start_date': '2026-05-14', 'end_date': '2026-06-10', 'days': 20, 'strategy_return_pct': 12.993460203216522, 'benchmark_return_pct': -2.6898921406544596, 'max_drawdown_pct': -3.296249414007524, 'trade_count': 46, 'win_count': 33, 'pnl': 188042.80959760057}], 'avg_strategy_return_pct': 3.1836072069186674, 'avg_benchmark_return_pct': 0.2865045313403314, 'win_rate': 0.5866666666666667, 'label': '样本震荡'}]}
- 基准：{'status': 'ready', 'benchmarks': [{'id': 'sample_equal_weight', 'name': '样本等权基准', 'status': 'ready', 'start_date': '2025-10-14', 'end_date': '2026-06-11', 'days': 161, 'return_pct': 39.21387982761977, 'max_drawdown_pct': -11.72547446101575, 'strategy_return_pct': 44.64181586728031, 'excess_return_pct': 5.427936039660537, 'final_nav': 1.3921387982761977, 'curve_tail': [{'trade_date': '2026-05-15', 'nav': 1.4280428963003309, 'daily_return': -0.005716789647821865, 'member_count': 1561}, {'trade_date': '2026-05-18', 'nav': 1.4380151295915937, 'daily_return': 0.006983146876818742, 'member_count': 1562}, {'trade_date': '2026-05-19', 'nav': 1.454537907821535, 'daily_return': 0.011489989145409073, 'member_count': 1558}, {'trade_date': '2026-05-20', 'nav': 1.4594362777873484, 'daily_return': 0.003367646824103481, 'member_count': 1560}, {'trade_date': '2026-05-21', 'nav': 1.4134875649447118, 'daily_return': -0.03148387739977211, 'member_count': 1561}, {'trade_date': '2026-05-22', 'nav': 1.4520380212864552, 'daily_return': 0.02727329005066353, 'member_count': 1562}, {'trade_date': '2026-05-25', 'nav': 1.4710959239992911, 'daily_return': 0.013124933668025798, 'member_count': 1563}, {'trade_date': '2026-05-26', 'nav': 1.4578266055298008, 'daily_return': -0.009020022592011904, 'member_count': 1563}, {'trade_date': '2026-05-27', 'nav': 1.4348341521730106, 'daily_return': -0.015771733942552338, 'member_count': 1563}, {'trade_date': '2026-05-28', 'nav': 1.4534754299833947, 'daily_return': 0.012991939021072724, 'member_count': 1563}, {'trade_date': '2026-05-29', 'nav': 1.407790115379028, 'daily_return': -0.03143177632172884, 'member_count': 1563}, {'trade_date': '2026-06-01', 'nav': 1.398179372912099, 'daily_return': -0.006826829057782859, 'member_count': 1562}, {'trade_date': '2026-06-02', 'nav': 1.4075021680190647, 'daily_return': 0.00666781050241671, 'member_count': 1562}, {'trade_date': '2026-06-03', 'nav': 1.4193735749306586, 'daily_return': 0.008434379130159429, 'member_count': 1562}, {'trade_date': '2026-06-04', 'nav': 1.4230310113965239, 'daily_return': 0.0025767962222657246, 'member_count': 1562}, {'trade_date': '2026-06-05', 'nav': 1.414601324158331, 'daily_return': -0.005923755118955618, 'member_count': 1563}, {'trade_date': '2026-06-08', 'nav': 1.3725105271588078, 'daily_return': -0.029754529619549594, 'member_count': 1561}, {'trade_date': '2026-06-09', 'nav': 1.4150540303315733, 'daily_return': 0.030996850174135664, 'member_count': 1541}, {'trade_date': '2026-06-10', 'nav': 1.397619982112906, 'daily_return': -0.012320411690981357, 'member_count': 1541}, {'trade_date': '2026-06-11', 'nav': 1.3921387982761977, 'daily_return': -0.003921798419354335, 'member_count': 1539}]}, {'id': 'index_000001_sse', 'name': '上证指数', 'status': 'ready', 'start_date': '2025-10-14', 'end_date': '2026-06-11', 'days': 161, 'return_pct': 3.1506533893196575, 'max_drawdown_pct': -8.829696432115009, 'strategy_return_pct': 44.64181586728031, 'excess_return_pct': 41.49116247796065, 'final_nav': 1.0315065338931966, 'source': 'tencent.stock_kline'}, {'id': 'index_000300_sse', 'name': '沪深300', 'status': 'ready', 'start_date': '2025-10-14', 'end_date': '2026-06-11', 'days': 161, 'return_pct': 4.039382603446495, 'max_drawdown_pct': -7.779463918558715, 'strategy_return_pct': 44.64181586728031, 'excess_return_pct': 40.60243326383381, 'final_nav': 1.040393826034465, 'source': 'tencent.stock_kline'}, {'id': 'index_000905_sse', 'name': '中证500', 'status': 'ready', 'start_date': '2025-10-14', 'end_date': '2026-06-11', 'days': 161, 'return_pct': 11.687943459557903, 'max_drawdown_pct': -14.063718101969712, 'strategy_return_pct': 44.64181586728031, 'excess_return_pct': 32.9538724077224, 'final_nav': 1.116879434595579, 'source': 'tencent.stock_kline'}, {'id': 'index_000852_sse', 'name': '中证1000', 'status': 'ready', 'start_date': '2025-10-14', 'end_date': '2026-06-11', 'days': 161, 'return_pct': 10.664370045367333, 'max_drawdown_pct': -13.453469519346239, 'strategy_return_pct': 44.64181586728031, 'excess_return_pct': 33.97744582191297, 'final_nav': 1.1066437004536733, 'source': 'tencent.stock_kline'}]}

## 文件

- 原始交易明细和参数网格 CSV 已从长期记忆移除；关键指标、订单统计和验证结论保留在本报告。

## 限制
- 当前本地样本不是全 A，只能作为小样本真实日线模拟。
- 分钟线只覆盖已同步股票和日期；未覆盖订单会在 raw.execution.mode 中标记为 daily_next_open_fallback，除非 minute_entry_required=true。
- 板块周期评分、资金流、热度、龙虎榜数据不完整时会降低主线/游资信号可信度。
- 财报仅在 publish_date 不晚于交易日时参与评分，缺披露日的数据不会用于真实回测。
- 上证指数、沪深300、中证500、中证1000基准会临时从外部行情获取，尚未持久化为本地可审计指数表。
- 样本内/样本外分段为时间切分的初步检查，不等同于完整 walk-forward 验证。
- 市场环境分段当前按样本等权基准粗分，尚未使用正式指数/行业 regime 模型。
- 参数网格验证通过 /api/backtests/{id}/validation-grid 单独重跑，报告页默认不自动嵌入以避免误触发长任务。
- 本次财报扩展同步补入了部分 publish_date/经营现金流字段，但外部 AkShare 财报接口在小批量验证中耗时过长，未完成稳定全量扩展同步。
- 本次 0 笔分钟尾盘真实成交，说明当前分钟线覆盖不足；尾盘低吸规则已实现，但还需要补齐历史分钟线后才能大量验证。
- 54 组合参数网格已完成，但本地历史只有约数月；仍需 3-5 年跨周期数据做更强 walk-forward 验证。

## 月度收益

- {'month': '2025-10', 'start_date': '2025-10-14', 'end_date': '2025-10-31', 'start_equity': 1000000.0, 'end_equity': 1000000.0, 'return_pct': 0.0, 'max_drawdown_pct': 0.0}
- {'month': '2025-11', 'start_date': '2025-11-03', 'end_date': '2025-11-28', 'start_equity': 1000000.0, 'end_equity': 1000000.0, 'return_pct': 0.0, 'max_drawdown_pct': 0.0}
- {'month': '2025-12', 'start_date': '2025-12-01', 'end_date': '2025-12-31', 'start_equity': 1000000.0, 'end_equity': 1000000.0, 'return_pct': 0.0, 'max_drawdown_pct': 0.0}
- {'month': '2026-01', 'start_date': '2026-01-05', 'end_date': '2026-01-30', 'start_equity': 1000000.0, 'end_equity': 1039269.4274002002, 'return_pct': 3.926942740020012, 'max_drawdown_pct': -6.211445487952183}
- {'month': '2026-02', 'start_date': '2026-02-02', 'end_date': '2026-02-27', 'start_equity': 1039269.4274002002, 'end_equity': 1053410.3189533006, 'return_pct': 1.3606569365246068, 'max_drawdown_pct': -2.4387255396910668}
- {'month': '2026-03', 'start_date': '2026-03-02', 'end_date': '2026-03-31', 'start_equity': 1053410.3189533006, 'end_equity': 1047409.0641420011, 'return_pct': -0.5696977429708983, 'max_drawdown_pct': -6.053809386960307}
- {'month': '2026-04', 'start_date': '2026-04-01', 'end_date': '2026-04-30', 'start_equity': 1047409.0641420011, 'end_equity': 1225555.2940822018, 'return_pct': 17.008276521468858, 'max_drawdown_pct': -0.887948752062373}
- {'month': '2026-05', 'start_date': '2026-05-06', 'end_date': '2026-05-29', 'start_equity': 1225555.2940822018, 'end_equity': 1439918.5285394026, 'return_pct': 17.49111080440755, 'max_drawdown_pct': -1.9054773045619533}
- {'month': '2026-06', 'start_date': '2026-06-01', 'end_date': '2026-06-11', 'start_equity': 1439918.5285394026, 'end_equity': 1446418.158672803, 'return_pct': 0.45138874211121394, 'max_drawdown_pct': -3.3795994747431557}
