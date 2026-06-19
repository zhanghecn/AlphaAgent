# Quant Feature Table Execution Progress - 2026-06-19

## Current State

本文件记录 `requirements/alphaagent_quant_feature_table_execution_plan.md` 的本轮执行进展，不是默认策略晋升报告。

当前产品基线仍是：

- Strategy: `mainline_dragon_pullback / 0.1.21`
- Product baseline: `#203/#194`
- Range: `2025-03-26..2026-06-18`
- Execution: `legacy_next_open`
- Return: about `+82.99%`
- Max drawdown: about `-15.59%`
- Buy / sell / open: about `224 / 214 / 10`

## Completed In This Slice

- `missed_candidate_opportunity_cost` now excludes same-symbol comparisons. If a missed candidate is already held as the same `vt_symbol`, it is no longer counted as a rotation opportunity.
- `setup-market-exit-audit.summary` now exposes `exit_path_replacement_quality`:
  - `by_trade_problem_type`
  - `by_exit_reason`
  - `by_support_stop_context`
  - `replacement_quality_summary`
  - `not_used_for_signal_score=true`
- `setup-market-exit-audit.summary` now exposes `market_context_validation`:
  - `by_market_regime`
  - `by_market_warning_level`
  - `by_market_recovery_level`
  - `by_fund_flow_state`
  - `by_market_mainline_trade_context`
  - `excluding_strong_market`
  - `fund_flow_coverage`
  - `not_used_for_signal_score=true`
- Fund-flow coverage now treats blank, `unknown`, and `insufficient_data` as `资金流数据不足`.
- `factor-audit` now exposes `factor_interaction_opportunity_cost`:
  - `entry_family_rank`
  - `entry_family_market`
  - `launch_quality_market`
  - `low_suction_days_first_lift`
  - `reclaim_support_ma`
  - `risk_market_warning`
  - `opportunity_cost`
- `/quant`回测分析区 now shows the new audit nodes inside the existing analysis panel:
  - sell/replacement quality summary
  - support-stop context table
  - market context validation summary
  - dynamic market bucket table
  - factor interaction audit
- Task 9 focus-symbol attribution is now expanded in `memory/06_backtests/2026-06-19_quant_focus_symbol_validation.md`:
  - separates full-position misses, ranking misses, theoretical-holding display gaps, signal-definition gaps, false launches, high-MFE giveback, and replacement-quality issues
  - covers the focus symbols named by the user, including 云南锗业、江海股份、剑桥科技、合肥城建、金安国纪、亨通光电、红星发展、埃斯顿、立新能源
- Task 10/11 are closed by promotion-gate decision:
  - no new default-off experiment is launched in this slice
  - no empty experiment table is used as fake evidence
  - the next experiment must first have targeted tests, then one isolated global run and grouped report

No default buy/sell rule changed.

## Validation

Passed:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "candidate_execution_attribution or missed_opportunity_cost or candidate_not_planned or setup_market_exit_audit_summary or buy_sell_problem_matrix or support_stop_context_audit" -q
```

Result: `8 passed, 362 deselected`.

Passed:

```bash
pnpm --dir frontend run build
```

Result: TypeScript and Vite build passed. Vite still reports the existing large chunk warning for `StockDetailPage`, which is not introduced by this change.

Passed:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

Result: `370 passed`.

Latest rerun after factor-interaction additions:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

Result: `371 passed`.

Passed:

```bash
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
git diff --check
docker compose up -d --build alphaagent-api
```

Result: compileall and diff check passed; API container rebuilt.

API smoke after rebuild:

```text
GET /api/health -> ok
GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5 -> ids [203, 194]
GET /api/backtests/203/factor-audit?top_limit=100 -> candidate_count 22, opportunity_rows 44, same_symbol_rows 0
GET /api/backtests/203/setup-market-exit-audit?lookahead_days=10 -> overall 214, exit_path_replacement_quality present, market_context_validation present
GET /api/backtests/203/strategy-timeline?vt_symbol=002384.SZSE -> items 36, lifecycle_segments 14
```

Latest API smoke also verified `factor_interaction_opportunity_cost` is present in `factor-audit`.

Feature-table report:

- `memory/06_backtests/2026-06-19_quant_feature_table_validation_report.md`
- Report conclusion: do not promote any default rule from this slice. The report added visibility and fixed attribution, but does not prove a default trading-rule improvement.

## Open Work

- This plan slice is complete as an audit/validation slice.
- No default-off experiment from this plan has been launched or promoted because the feature-table and focus-symbol reports did not satisfy the promotion gate.
- Next executable work is a new default-off experiment only after selecting one narrow bucket and adding targeted tests first.
