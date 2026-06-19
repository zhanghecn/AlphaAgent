# Low Position Reclaim Factor Audit

## Scope

This report validates the read-only factor audit pipeline added for the low-suction / dragon-pullback boundary plan.

API source:

- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5`
- `GET /api/backtests/213/factor-audit?top_limit=100`
- `GET /api/backtests/213/top-candidate-audit?top_n=10`
- `GET /api/backtests/213/top-candidate-audit?top_n=20`
- `GET /api/backtests/213/factor-candidates?vt_symbol=603439.SSE&limit=200`
- `GET /api/backtests/213/strategy-timeline?vt_symbol=...`

Important baseline note:

- After rebuilding the API container with the current workspace code, `baseline_only=true` returned `#213`, not the earlier `#203/#194`.
- `#213` covers `2024-05-28` to `2026-06-18`, while `#203/#194` covered `2025-03-26` to `2026-06-18`.
- This is a baseline selection drift, not proof that the strategy worsened. Future comparisons must either intentionally use the longer `#213` universe/range or restore the product baseline query to the intended `2025-03-26` start.

## Baseline Returned By Current API

| Run | Version | Range | Return | Max DD | Buy / Sell / Open | Win Rate | PF |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `#213` | `0.1.21` | `2024-05-28..2026-06-18` | `+45.17%` | `-23.83%` | `219 / 209 / 10` | `29.67%` | `1.2752` |

Execution remains the default historical model:

- `legacy_next_open`
- D-day close-visible signal
- D+1 daily open execution
- max positions `10`
- BUY candidate execution limit `20`
- no historical 14:30 dependency

## No-Future-Function Statement

The factor candidate rows use signal-day feature snapshots only:

- `as_of_date = trade_date`
- `feature_window_end = trade_date`
- `uses_future_for_label_only = false`
- `not_used_for_signal_score = true`

The outcome fields are explicitly label-only:

- D-day signal executes at next available trading day open.
- `return_*`, `MFE`, `MAE`, `failed_launch`, and `support_stop_like` are post-signal labels.
- `uses_future_for_label_only = true`
- `not_used_for_signal_score = true`

These rows are suitable for audit and factor selection, not for live score calculation.

## Factor Audit Summary

Top `100` factor-audit rows:

| Metric | Value |
| --- | ---: |
| Sample count | `100` |
| Fixed-horizon win rate | `66.00%` |
| Average observed return | `+36.12%` |
| Median observed return | `+3.81%` |
| Profit factor | `22.5353` |
| MFE >= 8% ratio | `55.00%` |
| MAE <= -5% ratio | `44.00%` |
| Failed-launch ratio | `32.00%` |
| Support-stop-like ratio | `44.00%` |

Interpretation:

- The top-100 audit is heavily affected by large trend winners. Average return is much higher than median return.
- Treat the result as a ranking/feature diagnostic, not as strategy PnL.

## Setup Family Buckets

| Setup | Samples | Win Rate | Avg Return | Median | Failed Launch | Support-Stop-Like |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `dragon_pullback` | `45` | `71.11%` | `+66.48%` | `+12.31%` | `13.33%` | `33.33%` |
| `low_position_reclaim` | `15` | `86.67%` | `+25.38%` | `+7.67%` | `20.00%` | `40.00%` |
| `unknown` | `40` | `52.50%` | `+5.99%` | `+0.33%` | `57.50%` | `57.50%` |

Interpretation:

- `low_position_reclaim` is promising in this top-100 fixed-horizon audit, with high win rate and strong median outcome.
- The sample size is only `15`, so this does not justify a default trading rule yet.
- The `unknown` bucket is materially weaker and should be inspected as a normalization/coverage target.

## Factor Buckets

### Low-Suction Days

| Days | Samples | Win Rate | Avg Return | Median | Failed Launch | Support-Stop-Like |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `0` | `26` | `88.46%` | `+110.97%` | `+83.51%` | `3.85%` | `19.23%` |
| `1-2` | `19` | `47.37%` | `+4.33%` | `-2.26%` | `57.89%` | `63.16%` |
| `3-5` | `43` | `60.47%` | `+13.34%` | `+1.53%` | `34.88%` | `58.14%` |
| `6-10` | `12` | `66.67%` | `+5.90%` | `+2.77%` | `41.67%` | `16.67%` |

Interpretation:

- More low-suction days are not monotonically better.
- `1-2` days are weak in this audit.
- `3-5` and `6-10` are usable as context but still show high failed-launch or support-stop-like risk.
- This supports the user's direction: low-suction buildup should accumulate context, but the buy marker should wait for a first effective lift/reclaim instead of treating every buildup day as a buy point.

### MA Convergence

| MA Convergence | Samples | Win Rate | Avg Return | Median | Failed Launch | Support-Stop-Like |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `<3%` | `30` | `76.67%` | `+10.55%` | `+2.61%` | `43.33%` | `36.67%` |
| `3-6%` | `29` | `51.72%` | `+17.79%` | `+0.17%` | `41.38%` | `62.07%` |
| `6-10%` | `19` | `42.11%` | `+3.89%` | `-1.84%` | `36.84%` | `68.42%` |
| `>10%` | `22` | `90.91%` | `+122.97%` | `+96.22%` | `0.00%` | `9.09%` |

Interpretation:

- The `>10%` bucket is unusually strong, but likely dominated by major trend winners and not necessarily a "low, tight MA convergence" pattern.
- This weakens a simple "MA distance must be small" rule. The feature needs setup-family context before it can be used.

### Volume

| Volume Bucket | Samples | Win Rate | Avg Return | Median | Failed Launch | Support-Stop-Like |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `shrinking` | `35` | `88.57%` | `+87.12%` | `+41.87%` | `11.43%` | `8.57%` |
| `normal` | `62` | `53.23%` | `+8.88%` | `+1.12%` | `43.55%` | `64.52%` |
| `moderate_expansion` | `3` | `66.67%` | `+4.09%` | `+10.15%` | `33.33%` | `33.33%` |

Interpretation:

- Shrinking-volume pullback remains a strong quality clue.
- Moderate expansion has too few samples in this top-100 audit.
- A future experiment should not blindly reward all volume expansion.

### Market Regime

| Regime | Samples | Win Rate | Avg Return | Median | Failed Launch | Support-Stop-Like |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `choppy_rotation` | `39` | `71.79%` | `+43.22%` | `+6.07%` | `15.38%` | `38.46%` |
| `false_bull` | `11` | `100.00%` | `+93.00%` | `+41.87%` | `27.27%` | `18.18%` |
| `strong_broad` | `50` | `54.00%` | `+18.07%` | `+2.24%` | `46.00%` | `54.00%` |

Interpretation:

- In this longer `#213` audit, strong broad market is not the best fixed-horizon bucket.
- This does not prove the strategy is bear-market safe, because the top-100 audit is candidate-level and the current historical fund-flow coverage is limited.

### Fund Flow

All `100` factor-audit rows are in `unknown` fund-flow state. This means the current long-range factor audit cannot yet validate fund-flow-driven trading rules.

## Top 10 / Top 20 Candidate Quality

Top-10 real closed portfolio candidates:

- Candidate count: `1832`
- Closed/evaluated: `26`
- Win rate: `46.15%`
- Average return: `+11.99%`
- Average excess return: `+12.49%`
- Strong-market share: `11.63%`
- Excluding strong-market: `25` evaluated, win rate `48.00%`, average return `+12.78%`, average excess `+13.64%`

Top-10 fixed 20-trading-day candidate observation:

- Observed count: `1632`
- Win rate: `47.24%`
- Average return: `+4.46%`
- Average excess return: `+3.32%`
- Excluding strong-market: `1419` observed, win rate `48.13%`, average return `+5.08%`, average excess `+4.70%`

Top-20 real closed portfolio candidates:

- Candidate count: `3600`
- Closed/evaluated: `35`
- Win rate: `37.14%`
- Average return: `+8.56%`
- Average excess return: `+8.61%`
- Strong-market share: `11.47%`
- Excluding strong-market: `34` evaluated, win rate `38.24%`, average return `+9.04%`, average excess `+9.34%`

Top-20 fixed 20-trading-day candidate observation:

- Observed count: `3200`
- Win rate: `45.59%`
- Average return: `+2.81%`
- Average excess return: `+1.72%`
- Excluding strong-market: `2787` observed, win rate `46.21%`, average return `+3.32%`, average excess `+3.00%`

Interpretation:

- Top-10 quality is materially better than top-20 quality in real closed trades.
- Fixed-horizon observation also degrades from top-10 to top-20.
- This supports keeping execution capacity at top `20`, but the ranking model still needs stronger discrimination inside the top `20`.

## Focus-Symbol Timeline Findings

### `603439.SSE` 三力制药

Coverage: `candidate_count=4`, `signal_count=13`, `order_count=0`, `trade_count=0`.

Findings:

- `2026-06-17`: candidate BUY rank `9`, score `92.58`, `low_position_reclaim`, `low_suction_days=3`, stage `低吸蓄势等待上拉`, launch quality `低吸蓄势未确认`, market `假强势`.
- `2026-06-18`: candidate BUY rank `2`, score `96.62`, `low_position_reclaim`, `low_suction_days=4`, stage `低吸启动偏晚`, launch quality `低吸启动回踩过久`; same row also has the planned BUY from `2026-06-17`.
- The unified timeline makes the conflict visible: 6/17 is still buildup context, while 6/18 is closer to the actual lift. It should not draw every buildup day as an independent buy point.

### `002384.SZSE` 东山精密

Coverage: `candidate_count=14`, `signal_count=21`, `order_count=3`, `trade_count=2`.

Findings:

- Recent high-score candidates are mostly classified as `dragon_pullback`, including `2026-04-29`, `2026-04-30`, `2026-05-26`, `2026-06-09`, and `2026-06-11`.
- `2026-06-03`: BUY rank `9`, score `95.69`, low-suction days `3`, stage `低吸蓄势等待上拉`, launch quality `低吸蓄势未确认`.
- `2026-06-09`: BUY rank `1`, score `99.53`, low-suction days `3`, stage `低吸上拉确认`, launch quality `低吸启动收盘偏高`.
- The timeline supports the product requirement: buildup should be evidence, while the first effective lift is the key marker. Current classification still tends to label Dongshan's June action as dragon-pullback even when low-suction context exists.

### `002443.SZSE` 金洲管道

Coverage: `candidate_count=9`, `signal_count=10`, `order_count=0`, `trade_count=0`.

Findings:

- `2026-05-13`: candidate BUY rank `5`, score `98.20`, classified as `dragon_pullback`.
- `2026-06-08`: planned SELL from `2026-06-05`, reason `support_stop`.
- This remains a sell-side/giveback sample, not a low-position-reclaim scoring sample.

### `002119.SZSE` 康强电子

Coverage: `candidate_count=9`, `signal_count=9`, `order_count=3`, `trade_count=2`.

Findings:

- `2026-02-05`: candidate BUY rank `1`, score `100.00`, dragon-pullback, no low-suction buildup.
- `2026-02-06`: real BUY filled around `24.80`.
- `2026-02-10`: support-stop SELL filled around `24.44`.
- The failure is a high-score dragon-pullback execution path, not a low-position-reclaim miss.

### `601179.SSE` 中国西电

Coverage: `candidate_count=10`, `signal_count=12`, `order_count=3`, `trade_count=2`.

Findings:

- `2026-02-03`: candidate/planned/filled BUY, score `99.34`, dragon-pullback, no low-suction buildup; exited by support stop on `2026-02-06`.
- `2026-02-25`: candidate BUY rank `48`, score `91.11`, low-suction days `3`, stage `低吸启动偏晚`, launch quality `低吸启动回踩过久`; plan BUY appears for `2026-02-26`.
- This confirms the user's concern: early 2/3 was not the durable low-suction point; 2/25 is the later low-suction context. They need separate scoring/labels.

### `600352.SSE` 浙江龙盛

Coverage: `candidate_count=10`, `signal_count=12`, `order_count=3`, `trade_count=2`.

Findings:

- `2026-03-10`: candidate BUY rank `49`, score `91.69`, low-suction days `5`, stage `低吸蓄势等待上拉`, launch quality `低吸蓄势未确认`.
- `2026-03-11`: candidate BUY rank `1`, score `98.18`, low-suction days `6`, stage `低吸上拉确认`, launch quality `低吸重复启动`.
- `2026-03-12`: real BUY filled around `16.26`.
- `2026-03-16`: support-stop SELL filled around `14.87`.
- This is a confirmed/repeated low-suction launch that failed after entry, so the fix is not "wait for any launch"; it needs launch-quality, market context, and sell/risk handling.

### `002240.SZSE` 盛新锂能

Coverage: `candidate_count=11`, `signal_count=18`, `order_count=6`, `trade_count=4`.

Findings:

- `2026-03-09`: candidate BUY rank `22`, score `90.72`, low-suction days `4`, stage `低吸上拉量能偏弱`, launch quality `低吸启动量能偏弱`, market `假强势`.
- `2026-03-11`: candidate BUY rank `2`, score `98.06`, low-suction days `6`, launch quality `低吸重复启动`.
- `2026-03-16`: real BUY filled around `40.01`.
- `2026-03-18`: support-stop SELL filled around `38.59`.
- The failure aligns with a weak-launch/false-bull context, but previous broad market-risk and launch-quality experiments already failed globally. Any experiment must be narrower than those failed switches.

## Does This Evidence Support A New Default-Off Experiment?

Not yet for a broad scoring change.

What the evidence supports now:

- Keep `dragon_pullback` and `low_position_reclaim` as separate internal setup families.
- Keep `low_position_reclaim` labels and factor buckets read-only on the first pass.
- Use the unified strategy timeline in stock detail so candidate BUY, planned BUY, real order/trade and sell markers are not shown as separate confusing workflows.
- Keep factor audit visible on the backtest review page.

Potential future default-off experiment, after more validation:

- A narrow `enable_contextual_reclaim_risk_penalty=false` experiment could target only rows with low-position context plus weak launch quality, weak/false-bull market context, and poor close/volume confirmation.
- It must explicitly avoid broad low-suction hard gates, because `#207` and `#208` already failed.
- It must compare against the correct baseline range. Current `#213` baseline selection drift must be resolved first.

Decision:

- Do not implement Task 8 trading-rule changes from this report alone.
- The plan should remain in read-only audit mode until the baseline query drift is clarified and the factor audit is rerun on the intended product baseline range.

## Verification

Commands run in this implementation pass:

```bash
pnpm --dir frontend run build
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k "entry_family or low_position_reclaim_context or keeps_dragon_family or high_level_sideways or factor_candidate or fixed_horizon_outcome or no_future or factor_audit or strategy_timeline" -q
uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
git diff --check
docker compose up -d --build alphaagent-api
```

Results:

- Focused pytest: `13 passed`.
- Full quant backtest pytest file: `346 passed`.
- Compileall: passed.
- Frontend build: passed, with existing large chunk warning.
- `git diff --check`: passed.
- API container rebuilt and new endpoints verified.
