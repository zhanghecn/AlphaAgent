# Short-term Trade Context Audit

## Current State

- Baseline: `mainline_dragon_pullback / 0.1.21`, portfolio backtest `#203/#194`.
- Range: `2025-03-26` to `2026-06-18`.
- Execution model: `legacy_next_open`, signal visible after daily close and executed at next trading day's open.
- This audit adds read-only short-term trade context labels to path diagnostics and setup/market/exit audit. It does not change candidate scoring, buy/sell rules, ranking, position count or product baseline.

The purpose is to translate public short-term/youzi concepts into measurable path buckets:

- `退潮防守`: market or fund-flow context is defensive.
- `假启动止损`: support stop after failed or absent early follow-through.
- `趋势浮盈回吐`: meaningful MFE existed but a large portion was given back.
- `卖早且替换差`: sold before rebound and the freed slot led to a bad replacement.
- `分歧低吸观察`: low-suction setup in weak breadth or not-yet-warmed context.
- `回暖后资金跟随`, `买后承接`, `主线活跃`, `震荡轮动`: positive or neutral explanatory buckets.

## Verification

API checks:

- `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5`
  - Returns `#203/#194`, not research experiments.
- `GET /api/backtests/203/setup-market-exit-audit?lookahead_days=10`
  - Summary includes `by_short_term_trade_context`.
- `GET /api/backtests/203/path-diagnostics?lookahead_days=10&limit=2000`
  - All `214` closed paths carry the same context labels.
- `GET /api/backtests/203/candidate-trace?vt_symbol=002240.SZSE&signal_date=2026-03-13`
  - Now returns `watch_not_bought`: the old persisted recommendation action was `BUY`, but read-side evidence resolution derives current action as `WATCH` with `low_suction_launch_unconfirmed`.

Code-level behavior:

- `alphaagent/server/services/backtest/queries.py` derives labels in `_short_term_trade_context_marker`.
- Labels are attached through `_with_path_issue`, so both `path-diagnostics` and `setup-market-exit-audit` share one read-only classification.
- The classification only reads persisted trades, visible path metrics, market context labels, replacement attribution and sell-after rebound audit fields.
- `quant_recommendations.action` can be stale for old persisted rows. Read-side APIs now resolve the current action from normalized reason/evidence and expose `persisted_action` plus `action_mismatch_resolved` when a legacy `BUY` is currently a `WATCH`. This does not rewrite history and does not change persisted backtest trades.

## Baseline Context Buckets

`#203` path diagnostics, `214` closed trades:

| Context | Label | Trades | Win Rate | Avg Return | Notes |
| --- | --- | ---: | ---: | ---: | --- |
| `trend_profit_giveback` | 趋势浮盈回吐 | `53` | `67.92%` | `+19.46%` | A profitable bucket overall, but it contains the user's clean giveback samples where sell timing can still improve. |
| `failed_launch_cut` | 假启动止损 | `49` | `0.00%` | `-8.60%` | The most direct failed-entry bucket. Prior broad early-exit experiment `#201` still failed, so this is not enough for a default stop rule. |
| `defensive_tide` | 退潮防守 | `39` | `41.03%` | `+3.00%` | Mixed results. Defensive market context cannot be used as a hard sell or hard reject by itself. |
| `failed_slot_replacement` | 卖早且替换差 | `32` | `28.12%` | `+3.18%` | Shows why sell experiments must audit freed-slot replacement quality, not just original-trade exit timing. |
| `neutral_rotation` | 震荡轮动 | `27` | `11.11%` | `-4.54%` | Weak bucket and useful for review, but still requires setup-level and replacement-quality protection before trading changes. |
| `warming_follow_through` | 回暖后资金跟随 | `6` | `33.33%` | `-2.26%` | Small sample. Do not overfit. |
| `follow_through` | 买后承接 | `4` | `0.00%` | `-5.37%` | Small sample. Early follow-through alone is not sufficient. |
| `divergence_low_suction` | 分歧低吸观察 | `4` | `75.00%` | `+0.29%` | Tiny sample. This supports keeping divergence low-suction as a watch label, not a forced slot. |

## Focus Samples

Use `path-diagnostics` for single-stock closed paths. `setup-market-exit-audit` returns worst examples and should not be read as per-symbol detail.

| Symbol | Entry | Exit | Setup | Return | Context | Read |
| --- | --- | --- | --- | ---: | --- | --- |
| `600352.SSE` | `2026-03-12` | `2026-03-16` | `stealth_low_suction` | `-8.56%` | 假启动止损 | Low-suction confirmation existed, but entry context was `震荡但未回暖` and buy-after-entry follow-through failed. |
| `002240.SZSE` | `2026-03-12` | `2026-03-19` | `stealth_low_suction` | `-9.69%` | 假启动止损 | Same weak-launch pattern; later rebound existed, so sell-side and replacement quality both matter. |
| `002443.SZSE` | `2026-05-14` | `2026-06-04` | `dragon_pullback` | `-4.86%` | 趋势浮盈回吐 | MFE was about `+11.82%`, then gave back about `16.69` points before support stop. Broad giveback stop `#195` failed, so any next rule must be narrower. |
| `601179.SSE` | `2026-02-03` | `2026-02-06` | `dragon_pullback` | `-9.60%` | 假启动止损 | The early 2/3 entry is a classic dragon-pullback false start; the user's 2/24-2/25 low-suction idea is a different later setup. |
| `002119.SZSE` | `2026-02-06` | `2026-02-10` | `dragon_pullback` | `-1.49%` | 震荡轮动 | The repeated/high-level dragon risk is real, but hard-reject experiments `#186/#198` failed globally. |
| `002384.SZSE` | `2026-05-27` | `2026-06-02` | `dragon_pullback` | `-7.92%` | 震荡轮动 | Sold before rebound and replacement was strong; this is not a simple "do not sell" case. |
| `002384.SZSE` | `2026-03-23` | `2026-03-25` | `dragon_pullback` | `+3.09%` | 退潮防守 | Defensive market label can still have profitable trades, so it cannot be a blanket reject. |

## Conclusion

The new context layer is useful for explaining user-named failures, but it should stay read-only for now.

The best next default-off experiment is not another broad low-suction gate. It should target a narrower state transition:

1. `假启动止损`: only when early follow-through fails, market/sector context is not supportive, and no reclaim appears.
2. `趋势浮盈回吐`: only when a trade has real MFE, loses key support or volume/price structure turns distribution-like, and the current day has no fresh buy/hold protection.
3. `卖早且替换差`: use replacement-quality audit as a guardrail before any earlier sell or delayed sell is promoted.

Required validation for any trading experiment remains unchanged:

- Compare against `#203/#194` on total return, max drawdown, PF, Sharpe, trade count and open positions.
- Check yearly split, dynamic market buckets, top-10 candidate audit and excluding-strong-market audit.
- Recheck the focused samples above plus `002384.SZSE`, `600352.SSE`, `002240.SZSE`, `002443.SZSE`, `601179.SSE`, and `002119.SZSE`.
- Confirm no future function: labels used for trading must be computable on signal day or sell-signal day, not from post-exit lookahead.
