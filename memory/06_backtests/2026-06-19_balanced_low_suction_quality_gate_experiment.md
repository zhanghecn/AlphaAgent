# Balanced Low-suction Launch Quality Gate Experiment

Date: 2026-06-19

## Current State

This is a default-off research experiment. It does not change the current product baseline.

The tested switch is `require_balanced_low_suction_launch_quality=true`. The corrected experiment applies the gate to any entry with low-suction context, not only to `entry_setup=stealth_low_suction`:

- `entry_setup=stealth_low_suction`, or
- `low_suction_days >= 3`, including dragon-pullback rows that overlap with low-suction buildup.

Allowed low-suction launch-quality buckets in the experiment:

- `balanced_first_lift`
- `high_close_launch`
- `other_confirmed_launch`

Blocked buckets include unconfirmed buildup, late pullback launch, thin-volume launch, and repeated launch.

## Runs

Main comparison range and params:

- Strategy: `mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Universe: main board, `max_symbols=5000`
- Execution: `legacy_next_open`, strict entry, `candidate_limit=20`, max positions `10`, `min_entry_score=76`
- Rotation: enabled, min score `98`, score gap `8`, max holding return `3%`, min holding days `3`

| Run | Switch | Return | Max Drawdown | Buy / Sell / Open | Win Rate | PF | Sharpe |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| `#203/#194` | baseline | `+82.99%` | `-15.59%` | `224 / 214 / 10` | `32.24%` | `1.6762` | `2.3831` |
| `#207` | corrected low-suction launch-quality gate | `+74.52%` | `-15.32%` | `216 / 206 / 10` | `32.52%` | `1.6199` | `2.1762` |
| `#206` | stale/narrow gate, only `stealth_low_suction` | `+58.36%` | `-21.57%` | `227 / 217 / 10` | `29.03%` | `1.3993` | `1.7601` |

`#206` is kept only as a diagnostic for the earlier experiment-scope bug. It should not be used as the strategy conclusion because it did not gate low-suction-context dragon-pullback rows.

## What Improved

`#207` confirms the user's suspicion that some low-suction/dragon-overlap rows were too early:

- `600352.SSE` `2026-03-12` was removed from the closed trade path. In baseline `#203`, it was `stealth_low_suction`, entry score `95.0141`, low-suction days `6`, entry context `震荡但未回暖`, launch diagnostic `启动后立即失败`, and exited by `support_stop` at `-8.5575%`.
- Low-suction setup quality improved: `stealth_low_suction` average return rose from `+1.20%` across `83` trades in `#203` to `+3.65%` across `39` trades in `#207`.
- `support_stop` count fell slightly from `125` to `123`, and sold-before-rebound support stops fell from `48` to `35`.
- Max drawdown improved slightly from `-15.59%` to `-15.32%`.

## What Got Worse

The global portfolio still got weaker:

- Total return fell from `+82.99%` to `+74.52%`.
- Profit factor fell from `1.6762` to `1.6199`.
- Sharpe fell from `2.3831` to `2.1762`.
- Top-10 real-closed candidate win rate fell from `43.18%` to `32.56%`.
- Excluding strong-market windows, top-10 win rate fell from `45.24%` to `35.90%`.
- Dynamic market buckets worsened, especially `choppy_rotation`: baseline top-10 closed win rate `44.83%`, average return `+2.03%`; experiment `30.43%`, average return `-1.30%`.

Trade replacement explains the return loss:

- Trades present in baseline but absent in `#207`: `119` closed trades, total PnL about `+74,869`, average return about `+0.55%`.
- Trades added by `#207` but absent in baseline: `111` closed trades, total PnL about `+7,263`, average return about `+0.02%`.
- Matched trades also lost about `-6,725` PnL versus baseline.
- Removed winners included `603115.SSE` 海星股份, `000510.SZSE` 新金路, `600362.SSE` 江西铜业, `603618.SSE` 杭电股份, `605255.SSE` 天普股份, and other trend winners.

This means the gate removes real weak entries, but the freed capacity is not reliably redeployed into better opportunities.

## Focused Symbols

- `600352.SSE`: improved by the gate because the failed low-suction launch was removed.
- `002240.SZSE`: the March failed low-suction trade was removed, but `#207` still had an earlier `2026-01-13` low-suction trade that lost `-8.2358%`; the issue is not solved by launch-quality gate alone.
- `002384.SZSE`: unchanged for the main losing `2026-05-27` dragon-pullback trade because it has no low-suction context (`low_suction_days=0`). This remains a sell/weak-follow-through problem, not this low-suction gate.
- `002443.SZSE`: unchanged; still a clean MFE giveback sample (`2026-05-14`, MFE about `+11.82%`, final `-4.86%`). This is a dynamic sell problem.
- `601179.SSE`: unchanged; `2026-02-03` is classic dragon-pullback with no low-suction context, so the low-suction gate correctly does not touch it.
- `002119.SZSE`: unchanged; repeated classic dragon-pullback risk remains diagnostic only.
- `603005.SSE`: latest candidate still appears as `dragon_pullback` with low-suction context and label `低吸蓄势未确认`; under `#207`-style research gate it would be demoted, but the default product still shows it as BUY because the gate remains off.

## Anti-future-function And Overfit Notes

- The experiment uses only signal-day evidence fields already available in candidate `raw.evidence`; execution remains `D` close-visible signal and `D+1` open.
- `low_suction_launch_quality_bucket` uses entry evidence fields such as `low_suction_days`, `low_suction_launch_confirmed`, close location, volume ratio, repeat days, and pullback days. It does not inspect post-entry return.
- The conclusion is based on the full main-board sample range, not only the named stocks. The named stocks are used for focused sanity checks.
- The sample still overlaps a strong technology/speculation market. The top-10 audit worsened after excluding strong-market windows, so the gate is not a robust anti-overfit improvement.

## Verification

Commands:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
pnpm --dir frontend run build
git diff --check
docker compose up -d --build alphaagent-api alphaagent-web
```

Results:

- Quant/backtest tests: `324 passed, 1 warning`.
- `compileall`: passed.
- Frontend build: passed, with the existing chunk-size warning.
- `git diff --check`: passed.
- Docker API/Web rebuilt; API health returned `ok`.

## Conclusion

Do not enable `require_balanced_low_suction_launch_quality` by default.

The corrected gate is directionally useful as an explanation and risk marker: low-suction buildup without the first effective lift, late pullback launch, thin-volume launch, and repeated low-suction launch are visibly weaker than balanced first lift. But turning that into a hard portfolio gate lowers total return and worsens top-10 candidate quality, mainly through opportunity cost and weaker replacement trades.

Next research should keep the low-suction launch-quality bucket as a visible marker and use it in narrower, context-aware experiments only. A better next direction is not a hard gate; it should combine launch quality with market/mainline context and replacement-quality checks, or use it to explain why a candidate is observation-only in a future non-default candidate mode.
