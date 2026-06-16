# Dragon Pullback Signal Dedupe Execution Plan

## Goal

Reduce noisy repeated BUY signals for `mainline_dragon_pullback` while keeping the valid Dragon Pullback buy point visible in stock detail and portfolio backtests.

## Current Evidence

- `/stocks/603629.SSE` now shows portfolio backtest `#118` as the primary execution source:
  - BUY signal: `2026-03-09`
  - BUY fill: `2026-03-10` at `58.86`
  - SELL fill: `2026-06-02` at `194.80`
  - closed return: `+230.69%`
- `603629.SSE` signal history from `2026-01-01` to `2026-02-10` still has multiple daily BUY signals, but `candidate-trace` for `2026-01-16` in portfolio backtest `#118` returns `not_selected`.
- Root cause: `score_dragon_pullback` is a stateless daily scorer. Once a structure is `TAIL_BUY_READY`, it can emit BUY on several nearby days. Portfolio execution avoids duplicate holdings, but candidate history and single-stock signal history remain noisy.

## Execution Steps

1. Add strategy-level freshness evidence:
   - Detect whether the current `TAIL_BUY_READY` state is the first fresh reclaim after a non-ready day or a materially new pivot.
   - Persist evidence fields such as `fresh_tail_buy`, `tail_buy_repeat_days`, and `last_tail_buy_ready_date`.
   - Add failed rule `repeat_tail_buy_setup` when the setup is a repeated ready state.

2. Keep valid March 603629 buy point:
   - The March setup must remain BUY because it is a different pullback leg from the January setup.
   - The repeated January days should be reduced to one or a smaller number of BUY signals.

3. Filter replay display noise:
   - Continue using portfolio detail as the primary stock-detail execution source.
   - In global replay, keep `already_holding` as an auditable attempt but hide it from primary K-line execution markers when a portfolio detail exists.

4. Verification gates:
   - Unit tests for fresh vs repeated dragon pullback setup.
   - Existing portfolio tests still pass.
   - API smoke for `603629.SSE` and latest portfolio backtest.
   - Browser smoke for `/quant` and `/stocks/603629.SSE`.

