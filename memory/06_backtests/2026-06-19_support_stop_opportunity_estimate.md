# Support Stop Opportunity Estimate

Date: 2026-06-19

## Scope

- Baseline: `#194`, `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Source: `GET /api/backtests/194/path-diagnostics?lookahead_days=10&limit=2000`
- Purpose: estimate which `support_stop` context is worth turning into a
  default-off experiment.

This is not a backtest and does not prove a rule works. It is a read-only
opportunity estimate from already persisted trade paths.

## Method

The estimate uses the `support_stop_context_audit` buckets:

- `true_failed_launch_stop`
- `stopped_then_rebounded`
- `had_follow_through_but_lost_support`
- `clean_float_profit_giveback`
- `high_mfe_then_rebound_after_stop`
- `other_support_stop`

Three simple upper-bound proxies were checked:

- Early failed-launch cap: for `true_failed_launch_stop`, cap loss at about
  `-4%`.
- Rebound hold/reclaim proxy: for rebound buckets, add only the first `6%` of
  the 10-day post-exit rebound.
- Giveback guard proxy: for `clean_float_profit_giveback`, preserve about `35%`
  of MFE.

These proxies are intentionally conservative but still optimistic because they
ignore replacement trades, execution gaps and false positives.

## Result

| Context | Count | Actual Return Points | Proxy Best Points | Proxy Improvement | Actual PnL |
| --- | ---: | ---: | ---: | ---: | ---: |
| `stopped_then_rebounded` | `41` | `-284.69` | `-38.69` | `+246.00` | `-278,751` |
| `true_failed_launch_stop` | `49` | `-383.99` | `-181.58` | `+202.41` | `-373,057` |
| `clean_float_profit_giveback` | `13` | `-115.32` | `+51.90` | `+167.22` | `-110,817` |
| `high_mfe_then_rebound_after_stop` | `7` | `-44.10` | `-2.10` | `+42.00` | `-43,241` |
| `had_follow_through_but_lost_support` | `14` | `-75.06` | `-75.06` | `0.00` | `-74,408` |
| `other_support_stop` | `1` | `-5.78` | `-5.78` | `0.00` | `-5,766` |

## Focus Samples

Large rebound-after-stop samples:

- `600487.SSE` 亨通光电: `2026-05-25 -> 2026-05-27`, return `-6.29%`,
  MFE `+0.32%`, post-exit rebound `+42.73%`, early state `failed_launch`.
- `603778.SSE` 国晟科技: return `-10.82%`, MFE `+7.82%`, rebound `+38.31%`,
  early state `confirmed_follow_through`.
- `600021.SSE` 上海电力: return `-7.38%`, MFE `-2.18%`, rebound `+35.40%`,
  early state `failed_launch`.
- `605111.SSE` 新洁能: return `-11.15%`, MFE `+0.42%`, rebound `+31.66%`,
  early state `failed_launch`.
- `002636.SZSE` 金安国纪: return `-9.06%`, MFE `-1.88%`, rebound `+27.67%`,
  early state `failed_launch`.

Clean float-profit giveback is smaller than expected:

- Only `13` support-stop trades are clean high-MFE giveback without later
  rebound.
- This explains why the prior broad `enable_mid_profit_giveback_stop` experiment
  helped focused examples such as `002443.SZSE`, but lowered full-portfolio
  return.

## Interpretation

The next rule experiment should not be a generic support-stop replacement.
The highest opportunity contexts are:

1. `stopped_then_rebounded`: likely needs a rebound-prone stop-out / reclaim
   protection model, not an earlier exit.
2. `true_failed_launch_stop`: likely needs an early failed-launch recognition
   model, but prior broad early-breakdown exits failed. Any new rule must be
   narrower and must not free slots into weak replacements.
3. `clean_float_profit_giveback`: real but only `13` trades, so it should be a
   narrowly gated sell experiment, not a primary global fix.

`had_follow_through_but_lost_support` currently has no obvious read-side proxy
improvement. It may need market/sector context rather than a price-only sell
rule.

## Next Experiment Boundary

Do not implement a default-on rule. If implementing, use a default-off research
switch and compare against `#194`.

Candidate experiments:

- `enable_failed_launch_exit_review`: only for early failed launch, after a
  first-three-day no-follow-through condition, and with a replacement-quality
  guard. This should first be a candidate/exit review marker unless the full
  backtest proves return and drawdown improve.
- `enable_rebound_prone_stop_hold_review`: mark stop-outs likely to rebound
  after capitulation, but do not blindly hold all stops. It needs a reclaim or
  market-context condition.
- `enable_contextual_profit_giveback_stop`: only for confirmed-follow-through
  trades with high MFE and no rebound-prone marker.

Validation gates:

- Total return and max drawdown must both beat or at least not materially weaken
  `#194`.
- Trend-trailing PnL must not collapse.
- Replacement trades must be audited; avoiding a loss is not enough if freed
  slots buy weaker names.
- Year/market-regime split and excluding-strong-market top candidate audit must
  remain acceptable.
