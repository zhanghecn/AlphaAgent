# Low-suction Context Launch Gate Experiment

Date: 2026-06-19

## Hypothesis

User hypothesis: low-suction buildup should not mark every buildup day as a buy point. The key buy should be the first visible lift after the buildup; pure buildup without launch should stay as observation.

This experiment tests only that narrow idea:

- Research switch: `require_low_suction_launch_for_low_suction_context=true`.
- Scope: any entry candidate with `low_suction_days >= 3`.
- Rule: require `low_suction_launch_confirmed=true`; otherwise do not enter the portfolio execution pool.
- This is narrower than `require_balanced_low_suction_launch_quality`: it does not reject late, thin-volume, repeated, or high-close confirmed launches.
- Default remains `false`.

No future data is used. The filter uses signal-day evidence already stored in candidate raw/evidence. Post-entry fields such as follow-through are used only for diagnosis.

## Baseline

Current product baseline remains `mainline_dragon_pullback / 0.1.21 / #203/#194`.

- Range: `2025-03-26..2026-06-18`.
- Execution: `legacy_next_open`, daily close-visible signal, next-day open execution.
- Candidate execution: top `20`, max positions `10`, main board.
- Return: `+82.9854%`.
- Max drawdown: `-15.5904%`.
- Buy / sell / open: `224 / 214 / 10`.
- Win rate / PF / Sharpe: `32.24% / 1.6762 / 2.3831`.

## Result

Experiment run: `#208`.

- Return: `+55.1181%`.
- Max drawdown: `-16.1611%`.
- Buy / sell / open: `209 / 199 / 10`.
- Win rate / PF / Sharpe: `30.65% / 1.4475 / 1.7749`.
- Decision: rejected as default.
- Persistence: run `#208` is marked `exclude_from_product_baseline=true`.

The experiment did remove the weak pure-buildup bucket, but portfolio-level return and drawdown both worsened.

## Diagnostics

Read-only path split on `#203` supported the local intuition:

- `unconfirmed_buildup`: `33` trades, win `9.09%`, avg return `-3.89%`.
- `balanced_first_lift`: `6` trades, win `66.67%`, avg return `+13.00%`.
- `low_suction_waiting_launch`: `24` trades, win `12.50%`, avg return `-3.14%`.
- `dragon_overlap_waiting_low_suction`: `9` trades, win `0%`, avg return `-5.91%`.

But the hard gate changed the portfolio path badly:

- Removed baseline-only closed trades: `74`, total PnL about `+181,779`.
- Added experiment-only closed trades: `59`, total PnL about `-54,247`.
- Removed winners included `603115.SSE`, `000510.SZSE`, `600362.SSE`, `603618.SSE`, `603826.SSE`, `000630.SZSE`, `000833.SZSE`, `002379.SZSE`, `601126.SSE`, and `003031.SZSE`.
- Added losers included `000753.SZSE`, `603920.SSE`, `002596.SZSE`, `000908.SZSE`, `002560.SZSE`, `002126.SZSE`, `002246.SZSE`, and `600884.SSE`.

Focused symbols:

- `600352.SSE` still bought `2026-03-12` and lost `-8.5575%`.
- `002240.SZSE` still bought `2026-03-12` and lost `-9.6942%`.
- `601179.SSE` still bought `2026-02-03` and lost `-9.6040%`.
- `002443.SZSE` still bought `2026-05-14` and lost `-4.8649%`.
- `002384.SZSE` still had mixed late/dragon entries: `2026-05-27` lost `-7.9249%`, `2026-06-10` gained `+1.6018%`.

The gate did not solve the user's named failure samples because several are confirmed repeated/late launches or classic dragon-pullback problems, not pure unconfirmed buildup.

Top-10 audit weakened:

- Baseline `#203` real closed top-10 win rate: `44.83%`; excluding strong windows: `46.43%`.
- Experiment `#208` real closed top-10 win rate: `32.26%`; excluding strong windows: `35.71%`.
- Fixed 20-trading-day candidate observation stayed unchanged, which confirms this experiment changed execution/replacement path rather than the candidate observation universe.

Year/regime splits:

- Baseline closed PnL by entry year: 2025 about `+546,513`, 2026 about `+112,343`.
- Experiment closed PnL by entry year: 2025 about `+475,937`, 2026 about `-66,392`.
- Baseline regime PnL: strong about `+77,489`, weak about `-20,303`, choppy about `+509,346`.
- Experiment regime PnL: strong about `+75,637`, weak about `-23,677`, choppy about `+385,841`.

## Conclusion

The user's semantic point is correct for display and diagnosis: low-suction buildup should not be explained as the key buy point; the first effective lift is the important event.

However, a hard portfolio gate is not supported. It removes some weak entries but also changes ranking, rotation, and replacement path in a way that misses large trend winners and buys weaker replacements. The next low-suction work should not be another hard filter. It should focus on:

- keeping pure buildup as read-only cluster evidence in UI;
- making the executable marker the first launch row;
- improving replacement quality checks before any sell/entry gate;
- testing narrower sell-side handling for confirmed-failed launches and float-profit giveback, with protection for trend winners.

Verification:

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`: `331 passed, 1 warning` on the final pre-commit recheck.
- `uv run python -m compileall alphaagent/server/services/backtest alphaagent/server/services/quant alphaagent/server/api`: passed.
- API container rebuilt and `#208` persisted.
