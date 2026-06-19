# Low-Suction Launch And Mid-Profit Giveback Experiments

Date: 2026-06-19

## Scope

- Baseline: `#194`
- Strategy: `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Universe: main board, `max_symbols=5000`
- Portfolio: max positions `10`, BUY execution pool top `20`
- Execution model: `legacy_next_open`
- Purpose: test whether the next fix should be a low-suction launch-confirmation hard gate or a dragon-pullback mid-profit giveback stop.

The experiment runs were persisted to reuse stored candidate signals. `baseline_only=true` was updated and verified so these research runs do not replace the product baseline in `/quant` or stock details.

## Runs

| Run | Research Switch | Return | Max DD | Win Rate | Profit Factor | Sharpe | Buy / Sell / Open | Decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `#194` | Baseline, both switches off | `+82.99%` | `-15.59%` | `32.24%` | `1.6762` | `2.3831` | `224 / 214 / 10` | Keep |
| `#195` | `enable_mid_profit_giveback_stop=true` | `+56.10%` | `-13.42%` | `31.80%` | `1.3957` | `1.7370` | `227 / 217 / 10` | Reject as default |
| `#196` | `require_low_suction_launch_confirmation=true` | `+65.69%` | `-17.95%` | `29.13%` | `1.4891` | `1.8972` | `216 / 206 / 10` | Reject as default |
| `#197` | Both switches true | `+74.44%` | `-13.78%` | `33.64%` | `1.6298` | `2.2382` | `227 / 217 / 10` | Reject as default |

## Exit Attribution

| Run | `support_stop` PnL | `trend_trailing_stop` PnL | New Stop PnL | Main Observation |
| --- | ---: | ---: | ---: | --- |
| `#194` | `-886,039.99` from `125` sells | `+1,442,342.35` from `33` sells | n/a | Baseline has large support-stop loss but also large trend winners. |
| `#195` | `-772,413.14` from `105` sells | `+1,125,863.05` from `25` sells | `mid_profit_giveback_stop`: `-28,912.90` from `25` sells | The rule trims some support-stop losses, but cuts trend winners and replacement path hurts total return. |
| `#196` | `-943,805.05` from `130` sells | `+1,341,378.73` from `29` sells | n/a | Low-suction hard gate lowers trade count but worsens support-stop loss and win rate. |
| `#197` | `-726,026.38` from `105` sells | `+1,231,771.60` from `28` sells | `mid_profit_giveback_stop`: `-27,652.71` from `29` sells | Drawdown improves versus baseline, but total return remains below baseline. |

## Low-Suction Findings

Baseline `#194` closed `83` `stealth_low_suction` trades:

| Bucket | Trades | Win Rate | Avg Return | Median Return | PnL |
| --- | ---: | ---: | ---: | ---: | ---: |
| Launch confirmed false | `24` | `12.50%` | `-3.14%` | `-5.10%` | `-76,081.58` |
| Launch confirmed true | `59` | `35.59%` | `+2.97%` | `-2.75%` | `+173,613.58` |

This supports using launch confirmation as a quality signal, but not as a hard portfolio gate:

- Hard gating removed `51` baseline closed trades and added `43` replacement trades.
- Removed baseline trades had total PnL about `+195,951.74`.
- Added replacement trades had total PnL about `+61,844.01`.
- The removed baseline set included `17` dragon-pullback trades with about `+280,900.61` PnL, including large trend winners such as `603115.SSE`, `002796.SZSE`, `603618.SSE`, and `603826.SSE`.
- The removed `stealth_low_suction` trades were weak as a group, about `-84,948.87`, but the hard gate also displaced high-payoff dragon-pullback opportunities.

Conclusion: launch confirmation should remain a scoring/ranking and explanation factor. Do not require every low-suction candidate to be launch-confirmed before it can compete, because the portfolio-level replacement path matters.

## Mid-Profit Giveback Findings

The lightweight closed-trade replay suggested a potential benefit on `#194`: `21` dragon-pullback weak-path trades could have moved from about `-80.84%` actual sum return to about `+4.39%` at the signal-day close. The full portfolio experiment contradicted direct promotion:

- In `#195`, `25` `mid_profit_giveback_stop` sells improved some same-key baseline trades by about `+96,131.73` PnL where they matched.
- But global return still fell from `+82.99%` to `+56.10%`.
- The main damage is opportunity cost: trend-trailing winners fell from `33` sells / about `+1,442,342` to `25` sells / about `+1,125,863`.
- This confirms that a local "save this trade" sell rule can hurt the complete portfolio by cutting winners and changing later replacements.

Conclusion: the current `mid_profit_giveback_stop` threshold is too broad for default use. If revisited, it must be narrower, probably requiring a failed reclaim / weak market / no theme strength confirmation, not just a high-to-current drawdown.

## Focus Samples

- `002443.SZSE`: baseline bought `2026-05-14`, sold `2026-06-04` by `support_stop` for about `-4,918`; `#195/#197` sold `2026-05-25` by `mid_profit_giveback_stop` for about `+5,356`. This sample still supports a narrower path-aware sell idea, but not the broad current threshold.
- `002384.SZSE`: `2026-04-01` was already a candidate BUY at rank `7`, setup `stealth_low_suction`, launch confirmed true. It did not become a real order in baseline because the portfolio was full and only bought a higher-priority candidate after sells. `2026-06-09` was rank `1`; `#194` still did not buy because no effective slot was released, while `#197` did buy after experiment-driven exits freed a slot.
- `002119.SZSE`: baseline bought on `2026-02-06` from the `2026-02-05` dragon-pullback signal and stopped out on `2026-02-10`. The later `2026-06-17` signal appears in experiments because different exits freed capacity; it is not proof that the baseline missed the newest candidate.
- `601179.SSE`: all runs kept the `2026-02-03` entry and stopped out on `2026-02-06`; it remains a buy-quality / early failure sample, not a mid-profit giveback sample.
- `600352.SSE` and `002240.SZSE`: both had launch-confirmed low-suction entries around `2026-03-12` and both failed quickly. Launch confirmation alone does not filter weak-market failed starts.
- `603629.SSE`: `#196/#197` bought `2026-04-08` and captured a large trend winner, but `#194` had a different earlier/later path. This shows portfolio path dependence: filtering or selling one trade can unlock or block unrelated big winners.

## Product Baseline Guard

`GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true` was verified after persisting the experiments. It returns only `#194`, not `#195/#196/#197`.

The guard excludes portfolio runs that have:

- `require_low_suction_launch_confirmation=true`
- `enable_mid_profit_giveback_stop=true`
- non-default `mid_profit_giveback_*` parameters

## Conclusion

Do not promote either research switch to the default strategy.

The next useful direction is narrower:

- Keep low-suction launch confirmation as a positive ranking/explanation factor, not a hard gate.
- Separate "低吸蓄势状态" from "低吸启动买点": the UI can show continuous buildup as observation, while the executable marker should emphasize the best launch day or the highest-score day in a short cluster.
- Revisit sell-side control only with an added context filter: failed reclaim, market risk, theme/sector weakening, or no active buy/hold evidence. The current high-to-current drawdown threshold is too blunt.
- Continue to use full persisted portfolio experiments before accepting any local single-stock improvement.

## Verification

- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_quant_backtest_portfolio.py -q`: `315 passed, 1 warning` before the final baseline-guard test extension.
- `docker compose up -d --build alphaagent-api`: rebuilt API before persisted experiments.
- Full persisted experiments: `#195`, `#196`, `#197`.
- `GET /api/backtests?...baseline_only=true` returns `#194` after experiments.
