# Low-Suction Limit-Up-Start Factor Audit

## Baseline

- Strategy/run: `mainline_dragon_pullback / 0.1.21`, backtests `#190` and `#175`.
- Range: `2025-03-26` to `2026-06-17`.
- Execution model: `legacy_next_open`, BUY top `20`, max positions `10`.
- Purpose: test whether successful `stealth_low_suction` entries are better identified by four launch-strength signals:
  - recent limit-up or near-limit-up within `20` trading days;
  - `4`/`5` consecutive bullish closes;
  - upward gap in the rising leg;
  - persistent volume expansion, not a single volume spike.

## Method

- Added `GET /api/backtests/{id}/path-diagnostics` for trade MAE/MFE and post-exit rebound review.
- Added `GET /api/backtests/{id}/low-suction-start-factor-audit` for low-suction factor buckets.
- The audit recalculates factor evidence from daily bars visible at each buy entry date when old trades do not contain the new fields.
- The local database does not contain index daily bars such as `000001.SSE`; weak/sideways market buckets therefore use an equal-weight stock return proxy and mark `market_return_20d_source=equal_weight_stock_proxy`.

## Result On `#190`

`#190` is the latest same-version product baseline and has the same closed-trade path as `#175/#177/#189` for this audit. The low-suction factor result is unchanged versus the earlier `#175` report.

| Metric | Value |
| --- | ---: |
| Closed low-suction trades | `83` |
| Winners / losers | `24 / 59` |
| Win rate | `28.92%` |
| Average return | `+1.20%` |
| Weak/sideways proxy trades | `33` |
| Weak/sideways proxy win rate | `24.24%` |
| Winner factor average | `1.92` |
| Loser factor average | `2.02` |

Factor-count buckets:

| Factor Count | Trades | Win Rate | Average Return | Weak/Sideways Count |
| --- | ---: | ---: | ---: | ---: |
| `0-1` | `26` | `30.77%` | `+3.18%` | `11` |
| `2` | `29` | `27.59%` | `-0.18%` | `7` |
| `3-4` | `28` | `28.57%` | `+0.79%` | `15` |

## Continuation Test

The user hypothesis was also tested against "successful low-suction then continued rise", using each trade's maximum floating return (`mfe_pct`) after entry as the outcome label. The four launch-strength fields still use only data visible at the entry date; `mfe_pct` is only the research label.

| Group | Trades | MFE >= 8% | MFE >= 12% | Avg MFE | Avg Return | Avg Factor Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All closed low-suction | `83` | `36.14%` | `27.71%` | `+10.93%` | `+1.20%` | `1.99` |
| MFE >= 8% winners | `30` | `100.00%` | `76.67%` | `+30.61%` | `+14.28%` | `2.10` |
| MFE >= 12% winners | `23` | `100.00%` | `100.00%` | `+36.90%` | `+19.62%` | `2.09` |

Factor-count buckets by continuation:

| Factor Count | Trades | MFE >= 8% | MFE >= 12% | Avg MFE | Avg Return |
| --- | ---: | ---: | ---: | ---: | ---: |
| `0-1` | `26` | `30.77%` | `23.08%` | `+11.55%` | `+3.18%` |
| `2` | `29` | `34.48%` | `27.59%` | `+8.34%` | `-0.18%` |
| `3-4` | `28` | `42.86%` | `32.14%` | `+13.02%` | `+0.79%` |

Weak/sideways market proxy bucket:

| Factor Count | Trades | Trade Win Rate | MFE >= 8% | MFE >= 12% | Avg MFE | Avg Return |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| All weak/sideways | `33` | `24.24%` | `30.30%` | `21.21%` | `+7.50%` | `-1.67%` |
| `0-1` | `11` | `45.45%` | `36.36%` | `27.27%` | `+9.12%` | `+2.06%` |
| `2` | `7` | `14.29%` | `28.57%` | `14.29%` | `+4.99%` | `-2.83%` |
| `3-4` | `15` | `13.33%` | `26.67%` | `20.00%` | `+7.48%` | `-3.86%` |

Conclusion: the four-signal count has a weak positive relation to later floating profit in the full sample (`3-4` factors gives `42.86%` MFE>=8% versus `30.77%` for `0-1`), but it fails in the weak/sideways-market proxy sample. Therefore it is not safe as a direct weak-market buy bonus. It is more suitable as an explanatory field or as a secondary tie-break only after other conditions pass: mature low-suction buildup, first lift/launch confirmation, clean support, and sell-side drawdown control.

Winner hit rates:

- Recent limit-up: `41.67%`.
- Consecutive bullish closes >= 4: `12.50%`.
- Upward gap: `66.67%`.
- Persistent volume expansion: `70.83%`.

## Decision

Do not add a ranking or buy-score bonus for `limit_up_start_factor_count >= 3` yet.

Reason: in the current `#190/#175` low-suction closed-trade sample, the `3-4` factor bucket does not improve final trade win rate over the `0-1` bucket, and losers have a slightly higher average factor count than winners. The four fields are useful as diagnostics and user-facing explanation, and they have weak relation to later maximum floating profit in the full sample. They do not improve weak/sideways-market low-suction selection, which was the key acceptance gate.

## Verification

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
git diff --check
docker compose run --rm -v "$PWD/alphaagent:/app/alphaagent:ro" alphaagent-api python - <<'PY'
from alphaagent.server.services.backtest.engine import backtest_low_suction_start_factor_audit
import json
result = backtest_low_suction_start_factor_audit(190)
print(json.dumps({"status": result.get("status"), "summary": result.get("summary")}, ensure_ascii=False, default=str, indent=2))
PY
```

Verification status:

- `267 passed`, one existing `StarletteDeprecationWarning`.
- `compileall` passed.
- `pnpm --dir frontend run build` passed, with the existing chunk-size warning.
- `git diff --check` passed.
