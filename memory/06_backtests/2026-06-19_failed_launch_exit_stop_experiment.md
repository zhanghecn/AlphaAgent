# Failed Launch Exit Stop Experiment

Date: 2026-06-19

## Scope

- Baseline: `#194`, `mainline_dragon_pullback / 0.1.21`
- Experiment: `#201`
- Range: `2025-03-26` to `2026-06-18`
- Universe: main board only, `max_symbols=5000`
- Execution: `legacy_next_open`, `min_entry_score=76`, BUY execution candidate top `20`, max positions `10`
- Switch: `enable_failed_launch_exit_stop=true`

The switch is default-off. It was added only as a research experiment and does
not change the product baseline returned by `baseline_only=true`.

## Rule Tested

The rule tries to exit early when a position fails to launch:

- at least `3` visible holding daily bars after entry;
- no current-day buy/hold protection signal;
- highest price since entry has not reached `+2.5%`;
- current close is at least `-2.5%` below cost;
- close fails to reclaim entry support or MA10/MA20.

The implementation only uses state accumulated as bars arrive. It does not use
post-trade path diagnostics or future prices.

## Global Result

| Run | Return | Max Drawdown | Win Rate | PF | Sharpe | Buy / Sell / Open |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `#194` baseline | `+82.99%` | `-15.59%` | `32.24%` | `1.6762` | `2.3831` | `224 / 214 / 10` |
| `#201` experiment | `+60.67%` | `-15.75%` | `27.85%` | `1.4162` | `1.8342` | `229 / 219 / 10` |

Decision: reject as default. The rule lowers return materially and does not
improve drawdown.

## Exit Attribution

| Exit Reason | `#194` Count / PnL | `#201` Count / PnL | Interpretation |
| --- | ---: | ---: | --- |
| `support_stop` | `125 / -886,040` | `131 / -922,779` | Loss got worse, not better. |
| `failed_launch_exit_stop` | `0 / 0` | `6 / -24,998` | The new rule fired rarely and was not enough to solve support-stop loss. |
| `trend_trailing_stop` | `33 / +1,442,342` | `32 / +1,316,059` | Trend-winner profit fell by about `126,000`. |
| `profit_protection_stop` | `26 / +170,653` | `22 / +153,324` | Fewer profitable protection exits. |

Support-stop context also worsened in important buckets:

- `support_stop` count rose from `125` to `131`.
- `stopped_then_rebounded` rose from `41` to `43`.
- `had_follow_through_but_lost_support` rose from `14` to `19`.
- `clean_float_profit_giveback` fell from `13` to `11`, but the improvement was
  too small to offset missed trend winners and weaker replacements.

## Replacement Trade Audit

Matched by `(vt_symbol, entry_date)`:

- Common trades: `183`
- Removed baseline trades: `41`, total PnL about `+266,883`
- Added experiment trades: `46`, total PnL about `+46,342`
- Changed common trades net: about `-2,511`

The largest removed baseline winners include:

- `603115.SSE` 海星股份, `2026-04-16 -> 2026-05-27`, `trend_trailing_stop`, about `+127,226`
- `000510.SZSE` 新金路, `2025-12-26 -> 2026-01-29`, `trend_trailing_stop`, about `+60,723`
- `600362.SSE` 江西铜业, `2025-12-22 -> 2026-01-26`, `trend_trailing_stop`, about `+42,983`
- `603618.SSE` 杭电股份, `2026-03-23 -> 2026-04-08`, `trend_trailing_stop`, about `+41,248`
- `603826.SSE` 坤彩科技, `2026-03-25 -> 2026-05-07`, `trend_trailing_stop`, about `+35,103`

The biggest common-trade regression was `002290.SZSE` 禾盛新材:

- Baseline: `2026-02-02 -> 2026-03-05`, `time_efficiency_stop`, about `+5,127`
- Experiment: `2026-02-02 -> 2026-02-05`, `failed_launch_exit_stop`, about `-6,516`

## Interpretation

The user hypothesis that "买入后破位连续下跌导致亏损" is directionally real,
but this specific daily three-bar early-exit rule is still too broad. It
changes the portfolio path and replacement set more than it fixes failed
launches.

This experiment confirms the same lesson as `#173/#174`: broad early-breakdown
or failed-launch daily exits can reduce a few visible bad paths, but the freed
slots and earlier exits miss high-payoff trend winners. The next sell-side work
should focus on narrower context models, especially:

- rebound-prone support-stop / reclaim protection;
- market or sector context around weak support-stop buckets;
- replacement-quality guard before any early exit can free a slot.

## Verification

- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_quant_backtest_portfolio.py -q`: `327 passed, 1 warning`
- `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`: passed
- `pnpm --dir frontend build`: passed, with the existing large chunk warning
- `git diff --check`: passed
- `docker compose up -d --build alphaagent-api`: API rebuilt and healthy
- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5`: still returns `#194`
