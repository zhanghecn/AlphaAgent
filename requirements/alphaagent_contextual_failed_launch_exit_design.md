# Contextual Failed Launch Exit Design

## Goal

Add a default-off research experiment for `mainline_dragon_pullback` that tests
whether confirmed failed launches can be exited earlier when, and only when, the
portfolio can rotate into a stronger visible candidate. The final report must
answer whether the experiment improves total return and reduces realized losses
versus the current product baseline `#203/#194`.

## Baseline Facts

- Current product baseline: `mainline_dragon_pullback / 0.1.21`, backtests
  `#203/#194`, range `2025-03-26..2026-06-18`.
- Baseline return: about `+82.99%`; max drawdown: about `-15.59%`.
- Largest realized loss source: `support_stop`, `125` exits, about `-886,040`
  realized PnL.
- `support_stop` is mixed:
  - `true_failed_launch_stop`: `49` trades, average about `-7.84%`, PnL about
    `-373k`.
  - `stopped_then_rebounded`: `41` trades, average about `-6.94%`, PnL about
    `-279k`.
  - `clean_float_profit_giveback`: `13` trades, average about `-8.87%`, PnL
    about `-111k`.
- Prior broad failed-launch exit `#201` failed globally: it did not reduce
  `support_stop` loss and missed/displaced trend winners.

## Trading Hypothesis

The useful short-term trading translation is not "sell faster whenever the
position is weak." It is:

1. If a trade was bought for a near-term launch but fails to launch after several
   visible daily bars, the opportunity cost rises.
2. Selling is only useful when the released slot can buy a stronger visible
   candidate; otherwise it may simply replace one weak trade with another.
3. Holding protection must remain for bottom accumulation, normal moving-average
   support pullback, price-volume synchronized pullback, or a current same-stock
   buy/hold signal.

This maps public short-term/youzi language into measurable proxies: market phase,
mainline strength, launch follow-through, support reclaim, panic/rebound context,
and replacement quality. It does not hard-code any trader identity or quote.

## Experiment Switch

Add `enable_contextual_failed_launch_exit_stop: bool = False`.

When `False`, current product behavior and `baseline_only=true` must be unchanged.
When `True`, the strategy may emit sell reason
`contextual_failed_launch_exit_stop` before the existing `support_stop`.

## Trigger Conditions

Use only data visible on the sell signal day. The sell still executes at the next
trading day's open under `legacy_next_open`.

Required conditions:

- Strategy is `mainline_dragon_pullback`.
- Entry setup is `dragon_pullback` or `stealth_low_suction`.
- `visible_holding_bars >= 3`.
- `high_gain < 0.025`.
- Current gain `<= -0.025`.
- Close failed to reclaim either:
  - entry support: `close < support_price * 0.99`, or
  - MA support: `close < min(entry_ma10, entry_ma20) * 0.995`.
- No hold protection:
  - not bottom long-base accumulation;
  - not moving-average support pullback with synchronized price/volume;
  - no current same-stock buy signal.
- Replacement quality guard passes.

## Replacement Quality Guard

The guard is evaluated from the same day's scored candidate list, before
scheduling next-day orders.

Pass if at least one BUY candidate that is not already held or pending:

- is inside the top `candidate_limit` execution pool;
- has `total_score >= rotation_min_score`;
- has a score at least `rotation_min_score_gap` higher than the held position's
  entry score if that entry score is available;
- is not blocked by failed rules under current scoring.

If no such replacement exists, the position is not sold by this experiment. It
may still be sold later by existing default rules.

## Reporting Requirements

Every persisted experiment run must have a final report in `memory/06_backtests/`
that includes:

- Backtest id, params, range, strategy version, and execution model.
- Total return, max drawdown, buy/sell/open counts, win rate, profit factor, and
  Sharpe versus `#203/#194`.
- `support_stop` count and loss before/after.
- `contextual_failed_launch_exit_stop` count, average return, and realized PnL.
- Trend-winner protection check: `trend_trailing_stop` count and PnL before/after.
- Replacement-quality check: bad/strong replacement counts and average
  replacement return.
- Year split and market-regime split.
- Top-10 candidate audit including excluding-strong-market summary.
- Focus-symbol review for `600352.SSE`, `002240.SZSE`, `601179.SSE`,
  `002443.SZSE`, and `002384.SZSE`.
- Anti-future-function statement: entry and sell decisions use only signal-day
  or earlier data; post-exit rebound and realized replacement return are report
  diagnostics only.

## Decision Rule

Do not promote the experiment unless it proves, globally, that losses are reduced
without damaging return quality:

- Total return should improve or not materially weaken versus `+82.99%`.
- Max drawdown should improve or not materially worsen versus `-15.59%`.
- Realized loss from `support_stop` plus
  `contextual_failed_launch_exit_stop` should be lower than baseline
  `support_stop` loss.
- `trend_trailing_stop` PnL must not collapse.
- Replacement quality must not be worse than baseline.
- Year and market-regime splits must not show that the experiment only works in
  one narrow bull-market segment.
