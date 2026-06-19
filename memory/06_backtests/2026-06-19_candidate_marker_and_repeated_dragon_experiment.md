# Candidate Marker And Repeated Dragon Experiment

Date: 2026-06-19

## Scope

- Product baseline: `#194 / mainline_dragon_pullback / 0.1.21`
- Range: `2025-03-26` to `2026-06-18`
- Universe: main board, `max_symbols=5000`
- Portfolio: max positions `10`, BUY execution pool top `20`
- Execution model: `legacy_next_open`

This note covers two related findings:

1. Stock-detail candidate markers should show the low-suction buildup as context and only mark the launch/key buy point.
2. A broad "exclude repeated dragon-pullback" hard gate is not suitable as the default strategy, even though it explains the `002119.SZSE` loss sample.

## Candidate Marker Display

The stock-detail candidate signal view is now a read-side display transformation, not a strategy change.

- Dense daily candidate rows are grouped into a visible candidate cluster.
- Unconfirmed low-suction buildup rows can be included as cluster evidence.
- The K-line marker is drawn only for the executable/key buy row in the cluster.
- Pure low-suction buildup without a later launch/key buy row is not drawn as a BUY marker.
- Buy rejections remain visible as rejected-buy markers.
- Frontend stock detail now prefers backend `signal.display_markers`; it no longer mixes those already-aggregated markers with raw portfolio theoretical signals when display markers exist.

Focused verification:

| Symbol | Result |
| --- | --- |
| `002384.SZSE` | `2026-04-01` is the displayed low-suction launch marker; its cluster now covers `2026-03-31` to `2026-04-07`. `2026-04-08` is not marked as low-suction because it was already far above MA5/MA10 and failed overheat/pullback timing checks. |
| `002384.SZSE` | `2026-06-09` remains the displayed low-suction launch marker; its cluster covers `2026-06-09` to `2026-06-12`. |
| `002119.SZSE` | Candidate markers compress repeated candidate days into broader clusters, e.g. `2025-12-24` cluster covers `2025-12-15` to `2025-12-29`, and `2026-05-07` covers `2026-04-30` to `2026-05-14`. |

This fixes the user-facing confusion where low-suction state looked like many separate BUY points. It does not change ranking, buying, selling or backtest performance.

## Candidate Trace State Split

Follow-up API verification on `#194` showed a second user-facing confusion:
`quant_recommendations`, theoretical signal markers, and real portfolio trades
can disagree because they answer different questions.

Focused Dongshan Precision checks:

| Date | Result |
| --- | --- |
| `2026-04-01` | Candidate trace reports a `BUY` candidate ranked `7`; the theoretical low-suction signal entered the execution pool but the real portfolio was full `10/10`, so no order was sent. The target was not yet theoretically held on the signal date. |
| `2026-06-09` | Candidate trace reports a `BUY` candidate ranked `1`; no new theoretical BUY event was written because the theoretical marker ledger had already bought Dongshan on `2026-06-04`, while the real portfolio did not hold it. This must be displayed as "候选 BUY 存在但真实组合未买", not as missing factor recognition. |
| `2026-06-12` | Candidate trace reports a `BUY` candidate ranked `3` and the real portfolio bought on `2026-06-15`. |

Implementation note: `candidate-trace` now exposes read-only context fields
`target_theoretical_held_on_signal_date`, `target_theoretical_entry_date`,
`target_real_held_on_signal_date`, and `target_real_entry_date` for
`candidate_not_planned` cases. The theoretical-held check uses the event
execute/trade date, not the signal date, so a D signal that only executes on
D+1 is not incorrectly treated as already held on D.

This still does not change portfolio execution. It only makes the diagnostic
reason precise enough for the stock detail page to show candidate BUY markers
separately from real portfolio buy/sell markers.

Frontend follow-up: stock detail now reads the selected marker date through
`candidate-trace` and shows a compact state split: candidate BUY, theoretical
signal marker state, and real portfolio execution state. The default selected
K-line marker is the latest marker, so `/stocks/002384.SZSE` candidate-signal
view opens on the `2026-06-09` BUY cluster instead of an old historical marker.

## `002119.SZSE` Diagnosis

Baseline `#194`:

- `2026-02-04`: theoretical dragon-pullback BUY existed, but candidate trace says the execution day was full position `10/10`, so no real order was sent.
- `2026-02-05`: repeated dragon-pullback BUY scored `99.03`; the portfolio bought on `2026-02-06`.
- `2026-02-10`: sold by `support_stop`.
- Closed return: about `-1.57%`.

Conclusion: this sample is not a missing-signal problem. It is a repeated/late dragon-pullback quality issue plus support-stop exit. The loss is small, but it is a useful risk pattern.

## Experiment `#198`

Research switch:

- `exclude_repeated_dragon_pullback=true`
- Default is `false`.
- Rule: when setup is `dragon_pullback`, block entries where `fresh_tail_buy=false` or `tail_buy_repeat_days > 0`.

| Run | Return | Max DD | Win Rate | Profit Factor | Sharpe | Buy / Sell / Open | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `#194` baseline | `+82.99%` | `-15.59%` | `32.24%` | `1.6762` | `2.3831` | `224 / 214 / 10` | Keep |
| `#198` exclude repeated dragon | `+33.90%` | `-20.14%` | `28.00%` | `1.1788` | `1.1583` | `235 / 225 / 10` | Reject as default |

Focused sample effect:

- `#198` avoided the `002119.SZSE` `2026-02-05 -> 2026-02-10` losing trade.
- But it later opened `002119.SZSE` on `2026-06-18` and had an open gain of about `+5.59%`.
- The global result is much worse than baseline, so this is not a valid broad filter.

## Decision

Keep `exclude_repeated_dragon_pullback` as a research switch only. Do not turn it on by default.

The correct use is diagnostic/ranking context:

- Repeated dragon-pullback can be risky in some names like `002119.SZSE`.
- A broad hard reject removes too many profitable trend opportunities and changes replacement trades badly.
- Future work should use a narrower context model, such as repeated dragon only under weak market, high extension, failed theme strength, or poor post-entry structure.

## Verification

- `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -k 'low_suction_launch_confirmation or exclude_repeated_dragon_pullback or candidate_signal_display or symbol_signal_payload_counts_only_executable_buy' -q`: `8 passed`.
- `uv run pytest tests/alphaagent/test_data_sync_schedule.py tests/alphaagent/test_quant_backtest_portfolio.py -q`: `335 passed` after adding the candidate-trace state split and full-portfolio replacement attribution tests.
- `uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db`: passed.
- `git diff --check`: passed.
- `pnpm --dir frontend build`: passed after frontend candidate-marker and state-split changes.
- `GET /api/backtests?limit=5&run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true`: still returns `#194`, not `#198`.
- API spot checks after rebuilding `alphaagent-api`:
  - `/api/backtests/194/candidate-trace?vt_symbol=002384.SZSE&signal_date=2026-06-09` returns `candidate_not_planned` with summary saying the theoretical marker ledger was already holding from `2026-06-04`, but the real portfolio was not holding.
  - `/api/backtests/194/path-diagnostics?vt_symbol=002384.SZSE` pairs the `2026-06-02` Dongshan sell with the next portfolio BUY, `600667.SSE` 太极实业, confirming single-symbol filtering no longer limits replacement attribution to the same stock.
- Browser spot check with Playwright `chromium --no-sandbox` on `http://localhost:5173/stocks/002384.SZSE`: candidate-signal view shows `2026-06-09`, `候选 BUY = BUY #1`, `理论信号 = 已持仓 2026-06-04`, `真实成交 = 未进入真实买入`, matching the candidate-trace API.
