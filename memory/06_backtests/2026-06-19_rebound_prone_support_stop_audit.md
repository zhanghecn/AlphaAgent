# Rebound-prone Support Stop Audit

Date: 2026-06-19

## Scope

- Baseline: `#194`, `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Source:
  - `GET /api/backtests/194/path-diagnostics?lookahead_days=10&limit=2000`
  - local `stock_daily_bars` inside the API container for sell-signal-day K-line features
- Purpose: decide whether `support_stop` followed by a rebound can be recognized
  from visible information, before adding a hold/reclaim trading rule.

This is a read-only audit. It does not change scoring, buying, selling, ranking,
or UI defaults.

## Baseline Fact

`#194` has `125` `support_stop` exits:

- `48` were followed by at least `+8%` max close rebound inside the next
  `10` trading days.
- `77` were not followed by that rebound.

The prior opportunity estimate showed this bucket has large theoretical upside,
but that estimate used future information and cannot become a trading rule by
itself.

## Entry-path Difference

Compared with non-rebound support stops, the rebound group had slightly stronger
pre-stop path quality:

| Field | Rebound Avg / Median | No-rebound Avg / Median | Difference |
| --- | ---: | ---: | ---: |
| `mfe_pct` | `+2.49 / +1.14` | `+1.12 / -1.02` | `+1.37` avg |
| `early_mfe_pct` | `+2.15 / +1.14` | `+0.30 / -1.18` | `+1.85` avg |
| `return_pct` | `-6.85 / -7.35` | `-7.53 / -7.39` | `+0.69` avg |

Interpretation: rebound-prone stops are less often complete zero-follow-through
failures. They often had some early or intratrade strength before breaking
support.

## Sell-signal-day Difference

Using the daily bar on the sell signal day (`D` close, `D+1` open execution),
the rebound group looked more like panic/wide-range selling:

| Field | Rebound Avg / Median | No-rebound Avg / Median | Difference |
| --- | ---: | ---: | ---: |
| `signal_intraday_range_pct` | `8.05 / 8.12` | `6.26 / 5.45` | `+1.79` avg |
| `signal_body_pct` | `-4.03 / -3.99` | `-3.13 / -2.94` | `-0.90` avg |
| `signal_upper_shadow_pct` | `1.97 / 1.22` | `1.17 / 0.76` | `+0.80` avg |
| `signal_close_location` | `0.21 / 0.16` | `0.29 / 0.20` | `-0.08` avg |
| `signal_volume_vs_5d` | `0.89 / 0.83` | `0.81 / 0.78` | `+0.08` avg |

Interpretation: rebound-prone support stops are not obvious bullish reversal
bars. They more often close weak inside a wide-range selloff. This makes a
simple "wait because it will rebound" rule risky: it would require tolerating
ugly closes, which is exactly where true breakdowns also appear.

## Simple Visible Classifiers

Several simple rules were checked using only path-to-date and sell-signal-day
daily bar data:

| Rule | Count | Rebound / False | Precision | Recall |
| --- | ---: | ---: | ---: | ---: |
| `MFE 0..3%` and sell-signal range `>=5%` | `15` | `10 / 5` | `66.7%` | `20.8%` |
| confirmed early follow-through and sell-signal range `>=5%` | `28` | `18 / 10` | `64.3%` | `37.5%` |
| early MFE `>=0` and sell-signal range `>=5%` | `46` | `29 / 17` | `63.0%` | `60.4%` |
| sell-signal range `>=5%` and lower shadow `>=1%` | `40` | `18 / 22` | `45.0%` | `37.5%` |
| panic range `>=5%` and close location `>=0.35` | `21` | `8 / 13` | `38.1%` | `16.7%` |

The best simple rule still creates many false positives. The broader rule with
useful recall (`early MFE >=0` plus wide selloff) is only about `63%` precise,
meaning it would hold many real breakdowns. That is not strong enough to become
a default sell rule.

## Implemented Read Marker

`GET /api/backtests/{id}/path-diagnostics` now includes a read-only
`rebound_prone_support_stop_review` marker for `support_stop` exits. It uses
only visible path information up to the sell execution date:

- early/path MFE;
- early follow-through state;
- the sell signal daily bar before the next-open execution.

It does not use `post_exit_max_return_pct` or `sold_before_rebound` to decide
the marker, and it does not change buying, selling, ranking, or portfolio
execution.

Runtime check on `#194` after rebuilding the API container:

| Item | Count |
| --- | ---: |
| Closed trades returned | `214` |
| `support_stop` exits | `125` |
| rows with sell-signal K-line context | `214` |
| `rebound_prone_support_stop_review=true` | `60` |
| review=true and sold-before-rebound=true | `32` |
| review=true and sold-before-rebound=false | `28` |
| review=false and sold-before-rebound=true | `16` |
| review=false and sold-before-rebound=false | `49` |

The marker catches many later rebound cases, but the false-positive count is
still too high for a trading rule. Its correct use is path review and future
experiment targeting.

## Replacement-quality Attribution

`path-diagnostics` also now includes a read-only replacement-quality attribution
for each closed trade. It pairs each sell with the next real BUY in chronological
backtest trade order, then reports that replacement trade's final closed return
when available:

- `replacement_vt_symbol`
- `replacement_entry_date`
- `replacement_entry_setup`
- `replacement_return_pct`
- `replacement_return_delta_pct`
- `replacement_outcome`

This is not a trading signal. It is a portfolio path audit that answers whether
selling freed a slot for a better trade or a worse trade.

Runtime check on `#194`:

| Replacement outcome | Count | Avg original return | Avg replacement return | Avg delta |
| --- | ---: | ---: | ---: | ---: |
| bad replacement | `98` | `+3.73%` | `-8.86%` | `-12.58` |
| strong replacement | `42` | `+2.14%` | `+31.82%` | `+29.68` |
| weak replacement | `38` | `-3.18%` | `-2.69%` | `+0.49` |
| profitable replacement | `26` | `+12.58%` | `+3.31%` | `-9.27` |
| open replacement | `10` | `+1.13%` | n/a | n/a |

Overall, `#194` replacement trades averaged `+2.22%`, about `1.03` percentage
points below the original closed trade return. Among `support_stop` rows marked
`rebound_prone_support_stop_review=true`, `30` led to bad replacements and only
`9` led to strong replacements. This reinforces the key constraint for future
sell experiments: do not optimize exits without checking what the freed slot
actually buys.

## Conclusion

Do not implement a direct default rule such as "support stop that might rebound
should not sell." The current evidence is only enough for a read-only marker:

- `rebound_prone_support_stop_review`
- likely inputs: prior MFE/early MFE, confirmed/weak follow-through, sell-signal
  wide-range panic bar, and market/sector context.

If this becomes a default-off experiment later, it must include:

1. a replacement-quality guard, because `#201` proved freeing or delaying slots
   changes portfolio path materially;
2. a market/sector context check, because wide weak closes are otherwise hard to
   distinguish from true breakdowns;
3. a reclaim condition after the stop day, not a blind hold-through-stop rule.

The next practical step is a read-side marker or audit bucket, not a trading
rule.
