# Entry Launch Risk Penalty Experiment

Date: 2026-06-19

## Scope

- Baseline: `#194`, strategy `mainline_dragon_pullback / 0.1.21`
- Experiment: `#200`, same range and product parameters, with
  `enable_entry_launch_risk_penalty=true`
- Range: `2025-03-26` to `2026-06-18`
- Execution: `legacy_next_open`, main board, `candidate_limit=20`,
  `max_positions=10`, `max_symbols=5000`, `min_entry_score=76`

The experiment is a research-only ranking penalty. It only subtracts score for
the worst visible launch-risk buckets:

- `pullback_days >= 12`
- `volume_ratio_5d_20d < 0.7`
- `stealth_low_suction` with `low_suction_days >= 5` and
  `close_location_in_range < 0.58`

The switch defaults to `false`, and `baseline_only=true` excludes runs with the
switch enabled.

## Result

| Run | Return | Max DD | Win Rate | PF | Sharpe | Buy / Sell / Open |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `#194` baseline | `+82.99%` | `-15.59%` | `32.24%` | `1.6762` | `2.3831` | `224 / 214 / 10` |
| `#200` risk penalty | `+38.14%` | `-19.31%` | `27.10%` | `1.2008` | `1.1801` | `224 / 214 / 10` |

## Path Audit

The penalty did not reduce the failed-launch rate. It changed which trades were
selected while leaving the headline early-follow-through mix unchanged.

| Run | Closed Trades | Failed Launch | Confirmed Follow-Through | Support Stop PnL | Trend-Trailing PnL |
| --- | ---: | ---: | ---: | ---: | ---: |
| `#194` | `214` | `87` / `40.65%` | `77` / `35.98%` | about `-886,040` | about `+1,442,342` |
| `#200` | `214` | `87` / `40.65%` | `77` / `35.98%` | about `-980,521` | about `+1,079,976` |

Setup split in `#200`:

- `dragon_pullback`: `146` trades, win rate `24.66%`, avg return `+0.68%`,
  PnL about `+88,460`, failed launch `58`, confirmed follow-through `60`.
- `stealth_low_suction`: `68` trades, win rate `32.35%`, avg return `+1.77%`,
  PnL about `+121,938`, failed launch `29`, confirmed follow-through `17`.

## Trade Replacement

Compared with `#194`, the experiment removed `60` closed trades and added `60`
closed trades.

Removed `#194` trades had about `+315,218` total PnL and `+5.36%` average
return. The largest missed winners were:

- `603115.SSE` 海星股份: `2026-04-16 -> 2026-05-27`, `+128.73%`,
  about `+127,226` PnL.
- `000510.SZSE` 新金路: `+61.22%`, about `+60,723` PnL.
- `002796.SZSE` 世嘉科技: `+54.30%`, about `+53,923` PnL.
- `600362.SSE` 江西铜业: `+44.42%`, about `+42,983` PnL.
- `603618.SSE` 杭电股份: `+41.69%`, about `+41,248` PnL.

Added `#200` trades had about `-102,804` total PnL and `-1.79%` average return.
The worst added losers were:

- `001896.SZSE` 豫能控股: `-13.67%`, support stop.
- `002866.SZSE` 传艺科技: `-13.81%`, support stop.
- `603920.SSE` XD世运电: `-13.45%`, support stop.
- `000908.SZSE` 景峰医药: `-12.28%`, support stop.
- `603396.SSE` 金辰股份: `-11.88%`, support stop.

## Conclusion

Reject as default. The narrow penalty is better structured than broad launch
quality scoring because it does not reward pretty launch shapes, but the global
portfolio result is still poor. It failed the most important test: failed-launch
share did not fall, support-stop loss increased, and trend-trailing profit fell
sharply.

The entry launch risk fields should remain explanation/audit context for now.
Do not promote `enable_entry_launch_risk_penalty` to the public default strategy.
Future work should avoid isolated entry-score penalties unless they also prove
that trend-winner opportunity cost is preserved.

## Verification

- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_quant_backtest_portfolio.py -q`: `323 passed`.
- `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`: passed.
- `pnpm --dir frontend build`: passed with the existing large chunk warning.
- `git diff --check`: passed.
- API run `#200`: persisted and audited after rebuilding `alphaagent-api`.
