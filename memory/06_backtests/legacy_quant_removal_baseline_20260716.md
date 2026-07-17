# Legacy Quant Removal Baseline

日期：2026-07-16\
用途：旧量化、通用回测、持仓和模拟账户物理删除前后的保护基线。

## Protected Working-Tree Changes

开始清理前工作区已有 9 个修改文件和 1 个未跟踪计划文件，共
`534 insertions / 30 deletions`。这些改动属于既有“自主数据自举与打板 v15”工作，
清理任务必须保留：

- `alphaagent/server/services/data_sync.py`
- `alphaagent/server/services/limit_up/history_repository.py`
- `alphaagent/server/services/limit_up/history_service.py`
- `tests/alphaagent/test_data_health.py`
- `tests/alphaagent/test_data_sync_schedule.py`
- `tests/alphaagent/test_limit_up_history.py`
- `memory/03_data/data_flow.md`
- `memory/05_runtime/run_debug.md`
- `memory/06_backtests/limit_up_production_local_parity_20260715.md`
- `docs/superpowers/plans/2026-07-15-autonomous-data-bootstrap.md`

清理实现需要删除旧量化调度，但不能删除其中的 600 日全市场日线自举、同花顺
252 日证据补缺、历史输入变更检测或强制重建能力。

## Preserved Product Fingerprint

- History strategy version: `limit-up-history-v15`
- Product strategy version: `limit-up-scheduled-v4`
- Execution version: `limit-up-cash-v4`
- Reliable range: `2024-01-15..2026-07-15`，603 个交易日
- Signal count: `307`
- Closed trades: `149`
- Winning trades: `94`
- Win rate: `63.0872%`
- Average trade return: `+1.8562%`
- Profit factor: `2.4961`
- Compounded return: `+266.4491%`
- Maximum drawdown: `-8.0275%`
- Final equity: `366,449.0557`
- Total fees: `15,583.2553`
- Exact 14:30 exits: `98/307`
- Daily-close proxies: `209/307`

验证命令：

```bash
uv run --group server pytest \
  tests/alphaagent/test_limit_up_cash_backtest.py \
  tests/alphaagent/test_limit_up_history.py -q
```

结果：`44 passed`。

## Legacy Table Counts

以下数据已由用户明确批准物理删除：

| Table | Rows |
| --- | ---: |
| `backtest_daily_equity` | 113,116 |
| `backtest_daily_positions` | 277,793 |
| `backtest_factor_outcomes` | 464,824 |
| `backtest_factor_snapshots` | 600,248 |
| `backtest_metrics` | 8,102 |
| `backtest_orders` | 105,776 |
| `backtest_runs` | 491 |
| `backtest_signal_events` | 3,177,991 |
| `backtest_trades` | 66,071 |
| `portfolio_group_items` | 42 |
| `portfolio_groups` | 11 |
| `quant_recommendations` | 389,372 |
| `quant_signal_runs` | 24,857 |
| `quant_stock_signals` | 19,191,156 |
| `quant_strategy_templates` | 0 |
| `quant_tail_preview_cache` | 21 |
| `risk_events` | 11 |
| `simulation_accounts` | 1 |
| `simulation_orders` | 33 |
| `simulation_positions` | 10 |
| `simulation_trades` | 22 |
| `strategy_replay_attempts` | 5,411,230 |
| `strategy_replay_runs` | 206 |

## Preserved Table Coverage

| Table | Rows | Minimum date | Maximum date |
| --- | ---: | --- | --- |
| `limit_up_concept_strength_snapshots` | 75,748 | 2026-07-15 | 2026-07-15 |
| `limit_up_history_replays` | 8,412 | 2024-01-15 | 2026-07-15 |
| `limit_up_live_trace_snapshots` | 1,599 | 2026-07-14 | 2026-07-15 |
| `limit_up_minute_backfill_attempts` | 2,828 | 2026-06-09 | 2026-07-15 |
| `limit_up_signal_snapshots` | 682 | 2026-07-10 | 2026-07-15 |
| `market_timing_panel` | 1 | - | - |
| `sector_daily_bars` | 237,457 | 2025-06-16 | 2026-07-06 |
| `sector_fund_flow_snapshots` | 20,233 | 2026-07-13 | 2026-07-15 |
| `sector_fund_flows` | 56,487 | 2026-06-18 | 2026-07-15 |
| `sectors` | 994 | - | - |
| `stock_auction_snapshots` | 9,121 | 2026-07-13 | 2026-07-15 |
| `stock_daily_bars` | 3,457,789 | 1994-09-20 | 2026-07-15 |
| `stock_fund_flows` | 7,095 | 2026-06-12 | 2026-07-15 |
| `stock_minute_bars` | 1,059,893 | 2026-01-20 | 2026-07-15 |
| `stock_sector_membership_snapshots` | 262,272 | 2026-07-13 | 2026-07-15 |
| `stock_sector_memberships` | 87,466 | - | - |
| `stocks` | 5,878 | - | - |

## Post-Migration Evidence

完成日期：2026-07-16。

### Physical Deletion And Preserved Data

- 固定清理清单中的旧派生表：`23` 张。
- 清理后仍存在的旧派生表：`0/23`。
- 逐表复核的保留业务表：`17` 张。
- 保留表行数回退：`0/17`；行数及日期范围与本报告删表前基线完全一致。
- 已清除旧调度：`tail_quant_1430`、`quant_research`、`tail_preview`。
- 600 日全市场日线自举、同花顺 252 日补缺、打板数据同步和市场择时调度均保留。

物理删除由 `alphaagent/server/db/legacy_product_cleanup.py` 的固定清单驱动，
API 启动期间通过 `create_schema()` 执行；没有使用表名前缀通配删除。

### HTTP Boundary

使用管理员鉴权后的实际容器服务验证：

| Request | Status |
| --- | ---: |
| `GET /api/limit-up/history/status` | `200` |
| `GET /api/market-timing/panel` | `200` |
| `GET /api/mainline-replay/timeline` | `200` |
| `GET /api/quant/strategies` | `404` |
| `GET /api/backtests` | `404` |
| `GET /api/portfolios/groups` | `404` |
| `GET /api/simulation/account` | `404` |

### Browser Acceptance

`http://localhost:8080/short-term` 已使用真实登录和真实 API 数据完成 Playwright 验收：

| Viewport | Rendered evidence | Document width | Console |
| --- | --- | --- | --- |
| `1440x900` | 打板账户终值、复利、胜率、回撤及当日轨迹均已渲染 | `scrollWidth=1440`, `clientWidth=1440` | 0 errors, 0 warnings |
| `390x844` | 移动导航、打板指标和轨迹表均已渲染 | `scrollWidth=390`, `clientWidth=390` | 0 errors, 0 warnings |

移动端宽表只在局部 `overflow-x:auto` 容器内滚动，不产生全页横向溢出。

- [桌面截图](legacy_quant_removal_short_term_desktop_1440x900.png)
- [移动端截图](legacy_quant_removal_short_term_mobile_390x844.png)

### Final Limit-Up Fingerprint

删除后复核值与删除前完全一致：

- History strategy version: `limit-up-history-v15`
- Product strategy version: `limit-up-scheduled-v4`
- Execution version: `limit-up-cash-v4`
- Signal count: `307`
- Closed trades: `149`
- Winning trades: `94`
- Win rate: `63.0872%`
- Profit factor: `2.4961`
- Compounded return: `+266.4491%`
- Maximum drawdown: `-8.0275%`
- Final equity: `366,449.0557`

### Verification Gates

最终验证结果：

- 完整剩余后端测试：`833 passed`。
- 删除边界测试：`7 passed`。
- 打板保护测试：`44 passed`。
- 市场择时测试：`74 passed`。
- 前端测试：`69 passed`。
- Python compileall、TypeScript 检查、Vite 生产构建和 `git diff --check` 均通过。
