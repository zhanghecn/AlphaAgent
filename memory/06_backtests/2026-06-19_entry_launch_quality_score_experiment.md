# Entry Launch Quality Score Experiment

Date: 2026-06-19

## Scope

- Baseline: `#194`, strategy `mainline_dragon_pullback / 0.1.21`
- Experiment: `#199`, same range and product parameters, with
  `enable_entry_launch_quality_score=true`
- Range: `2025-03-26` to `2026-06-18`
- Execution: `legacy_next_open`, main board, `candidate_limit=20`,
  `max_positions=10`, `max_symbols=5000`

The experiment is a research-only ranking adjustment. It does not change the
default public strategy because the switch defaults to `false` and
`baseline_only=true` excludes runs with the switch enabled.

## Result

| Run | Return | Max DD | Win Rate | PF | Sharpe | Buy / Sell / Open |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `#194` baseline | `+82.99%` | `-15.59%` | `32.24%` | `1.6762` | `2.3831` | `224 / 214 / 10` |
| `#199` launch-quality score | `+28.70%` | `-20.34%` | `31.60%` | `1.1086` | `0.9705` | `241 / 231 / 10` |

## Path Audit

The experiment moved the early-follow-through ratios in the intended direction,
but portfolio return collapsed.

| Run | Closed Trades | Failed Launch | Confirmed Follow-Through | Avg Closed Return |
| --- | ---: | ---: | ---: | ---: |
| `#194` | `214` | `87` / `40.65%` | `77` / `35.98%` | `+3.14%` |
| `#199` | `231` | `83` / `35.93%` | `95` / `41.13%` | `+0.57%` |

Setup split in `#199`:

- `dragon_pullback`: `151` trades, avg return `+0.17%`, failed launch `38.41%`,
  confirmed follow-through `45.70%`.
- `stealth_low_suction`: `80` trades, avg return `+1.33%`, failed launch
  `31.25%`, confirmed follow-through `32.50%`.

## Difference Samples

The score adjustment displaced high-payoff baseline winners:

- `603115.SSE` 海星股份: baseline `2026-04-16 -> 2026-05-27`,
  `+128.91%`, about `+127,226` PnL.
- `000510.SZSE` 新金路: `+61.35%`, about `+60,723` PnL.
- `002796.SZSE` 世嘉科技: `+54.42%`, about `+53,923` PnL.
- `600362.SSE` 江西铜业: `+44.54%`, about `+42,983` PnL.

It also added large losers that looked good by the launch-quality proxy:

- `002208.SZSE` 合肥城建: adjustment `+3.8`, return `-20.89%`.
- `600208.SSE` 衢州发展: adjustment `+5.0`, return `-18.38%`.
- `600756.SSE` 浪潮软件: adjustment `+3.6`, return `-15.02%`.
- `603667.SSE` 五洲新春: adjustment `+5.0`, return `-12.75%`.

## Conclusion

Reject as default. The launch-quality proxy is useful as a diagnostic because it
reduces the failed-launch share and increases confirmed-follow-through share,
but it is not a reliable portfolio-ranking rule. It over-rewards "pretty"
short-term launch shapes and misses high-payoff trend continuation trades.

Next direction:

- Keep `enable_entry_launch_quality_score` default `false`.
- Use entry launch quality as explanation/audit context, not as direct score
  addition.
- If revisiting, make it a narrow penalty for only the worst buckets
  (`pullback_days >= 12`, dead volume, weak close), not a broad positive bonus.
- Any future variant must compare not just failed-launch share, but also missed
  trend-winner opportunity cost.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py::test_backtest_experiment_entry_launch_quality_adjusts_candidate_ranking tests/alphaagent/test_quant_backtest_portfolio.py::test_backtest_list_baseline_only_hides_short_range_experiments tests/alphaagent/test_quant_backtest_portfolio.py::test_entry_launch_quality_audit_groups_visible_entry_factors -q`: passed.
- `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`: passed.
- API run `#199`: persisted and audited.
