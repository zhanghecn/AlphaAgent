# Market Mainline Trade Context Audit

## Current State

- Baseline: `mainline_dragon_pullback / 0.1.21`, portfolio backtest `#203/#194`.
- Range: `2025-03-26` to `2026-06-18`.
- Execution model: `legacy_next_open`.
- This change adds read-only `market_mainline_trade_context` labels to path diagnostics and setup/market/exit audit. It does not change default scoring, BUY/WATCH, sell rules, ranking, max positions, or product baseline.

The new context maps public short-term/youzi ideas into measurable market buckets:

- `退潮/弱市防守`: weak market, high market-warning level, or continuous/panic fund outflow.
- `主线分歧回踩`: narrow-theme bull or active-pullback theme, with candidate aligned to the dominant theme.
- `窄牛主线活跃`: active narrow-theme market, but candidate alignment is not proven.
- `震荡轮动主线候选`: choppy rotation with theme-aligned candidate.
- `震荡低吸观察`: choppy/false-bull market with stealth low-suction setup.
- `弱市独立强票`: weak/isolated candidate not aligned to a proven theme.
- `买后承接验证`: post-entry follow-through bucket, audit-only.
- `主线未知/普通轮动`: theme alignment is missing or not enough.

## External Method Mapping

Public youzi/short-term references mostly repeat a few engineering-relevant ideas:

- market emotion and cycle matter;
- mainline direction matters more than isolated K-line shape;
- divergence/pullback can be bought only when strength has not died;
- recession/退潮 periods need defense;
- trend winners must not be cut only because of a generic rule.

These ideas are not trading rules by themselves. AlphaAgent maps them into observable fields: dynamic market regime, fund-flow pressure, dominant theme, stock-theme alignment, low-suction/dragon setup, early follow-through, replacement quality and support-stop behavior.

## Verification

Commands:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q -k "market_mainline_context or low_suction_dragon or path_diagnostics or market_context_summary"
uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant
pnpm -C frontend build
git diff --check
docker compose up -d --build alphaagent-api
```

Results:

- Targeted tests: `12 passed, 317 deselected, 1 warning`.
- `compileall`: passed.
- Frontend build: passed, with the existing chunk-size warning.
- `git diff --check`: passed.
- API container rebuilt.

API sample:

- `GET /api/backtests/203/setup-market-exit-audit?lookahead_days=10`
  - returns `summary.by_market_mainline_trade_context`.
- `GET /api/backtests/203/path-diagnostics?lookahead_days=10&limit=5`
  - rows include `market_mainline_trade_context_label`.

## #203 Buckets

`#203` setup/market/exit audit, `214` closed trades:

| Context | Label | Trades | Win Rate | Avg Return |
| --- | --- | ---: | ---: | ---: |
| `unknown_mainline` | 主线未知/普通轮动 | `75` | `22.67%` | `+1.46%` |
| `rotation_low_suction_watch` | 震荡低吸观察 | `62` | `33.87%` | `+2.63%` |
| `risk_off` | 退潮/弱市防守 | `39` | `41.03%` | `+3.00%` |
| `market_follow_through` | 买后承接验证 | `38` | `39.47%` | `+7.45%` |

Focused worst-path sample from path diagnostics:

- `605117.SSE` 2026-04-24: `震荡低吸观察` + `假启动止损` + `低吸确认后无承接`, return about `-19.86%`.
- `600226.SSE` 2026-02-02: `震荡低吸观察` + `假启动止损` + `低吸确认后无承接`, return about `-15.86%`.
- `000973.SZSE` 2025-12-02: `主线未知/普通轮动` + `假启动止损` + `标准龙回头`, return about `-15.17%`.

## Conclusion

The new context helps answer the user's market-regime questions, but it is still an audit layer.

Important limitation: `主线分歧回踩` did not appear as a large #203 bucket because historical sector/theme alignment is still sparse. This confirms the existing product decision: do not claim AlphaAgent has fully quantified "科技主线回踩" or "new non-tech mainline rotation" until historical sector scoring and memberships are more complete.

Next default-off experiments should use this context as a guardrail, not as a hard rule:

- failed-launch exits should focus on `震荡低吸观察` or `主线未知/普通轮动` plus no reclaim and weak replacement-quality checks;
- profit-giveback exits should protect trend winners in `主线分歧回踩` or `窄牛主线活跃` once that bucket has enough data;
- risk-off should remain a warning unless a full global backtest proves dynamic threshold or position control improves return and drawdown.
