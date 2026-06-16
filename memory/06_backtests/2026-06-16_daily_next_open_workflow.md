# Daily Next Open Workflow

日期：2026-06-16

## Current State

- 历史策略研究默认口径改为 `legacy_next_open`：D 日收盘产生信号，D+1 日线开盘买入/卖出。
- 前端主操作改为“运行策略研究”：内部自动逐日生成候选，再自动跑组合回测。
- 默认策略为 `mainline_dragon_pullback`，默认最大持仓 10，只取候选评分前 10。
- 普通策略列表只公开 `mainline_dragon_pullback`；旧策略保留为内部兼容，不再作为用户日常选择项。
- 历史主流程不再要求 14:30 分钟线；14:30/分钟快照保留为实时/分钟数据层和旧报告兼容能力。
- `/quant` 页面默认读取当前公开策略最新已生成候选日，不再先跳到“最新交易日但未运行”的空结果。
- `/api/backtests` 支持 `strategy` 过滤；量化页回测列表只展示当前公开策略的组合回测，避免旧策略记录挤掉当前策略结果。

## Changed Areas

- 后端默认：
  - `BacktestParams.execution_model = legacy_next_open`
  - `/api/backtests` 默认 `max_positions=10`、`candidate_limit=10`、`max_symbols=5000`
  - `screen_stocks_range(..., persist=True)` 自动生成同区间买卖记录，执行模型为日线 D+1
  - `strategy_replay` 在 `legacy_next_open` 下关闭 `intraday_entry`，买入和卖出都走日线开盘
- 前端默认：
  - `/quant` 一键运行策略研究，不再暴露 14:30 参数和分钟补数入口
  - `/quant` 和股票详情页不再暴露多策略选择；策略显示固定为“主线龙回头回踩低吸”
  - `/stocks/:vtSymbol` 自动单股复盘改为 `legacy_next_open`
  - 用户可见文案统一为“买卖记录”，不再要求理解 `replay`

## Verification

已通过：

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
# 178 passed, 1 warning

uv run pytest tests/alphaagent/test_factors.py -q
# 8 passed

uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api/backtests.py alphaagent/server/api/quant.py
# passed

pnpm --dir frontend build
# passed; existing large chunk warning remains for StockDetailPage

git diff --check
# passed
```

Docker/API smoke：

```text
GET /api/quant/strategies
default_strategy_id = mainline_dragon_pullback
items = [mainline_dragon_pullback]
mainline_dragon_pullback.default_min_entry_score = 76

POST /api/backtests
payload: start=2026-02-02, end=2026-06-12, persist=false, max_symbols=20, candidate_limit=10, max_positions=10
status = ready
strategy = mainline_dragon_pullback / 0.1.0
execution_model = legacy_next_open
execution = 历史日线模型：D 日收盘信号，D+1 开盘执行买入/卖出。
first_trade_mode = daily_next_open
trades = 96
buy trades = 52
```

页面级验证：

```text
http://localhost:5173/quant
候选 tab：5 秒内显示 10 行候选；默认日期 2026-03-30，运行 #1685，KPI 为“量化候选 10 只”。
回测 tab：显示 #112 2025-10-14 - 2026-02-04，收益约 +11.62%，买入/卖出/持仓中为 99 / 89 / 10 笔。

截图：
memory/06_backtests/quant_page_smoke_after_empty_fix.png
memory/06_backtests/quant_page_backtest_tab_after_empty_fix.png
```

## Notes

- 旧 `strict_1430`、`tail_close_hybrid`、分钟缺口审计和同步接口暂不删除，避免破坏历史报告、数据管理和未来实时确认能力。
- 新策略收益仍需按日线 D+1 新主流程重新做多年全 A、walk-forward、参数敏感性和高摩擦验证。
