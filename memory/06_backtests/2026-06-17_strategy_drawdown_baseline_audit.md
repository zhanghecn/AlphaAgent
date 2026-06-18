# Strategy Drawdown Baseline Audit

## Baseline

- Strategy: `mainline_dragon_pullback / 0.1.21`.
- Backtest: `#177`, latest same-version full-range baseline returned by `baseline_only=true`. Existing reference `#175` has the same strategy, date range and nearly identical metrics.
- Range: `2025-03-26` to `2026-06-17`.
- Execution: `legacy_next_open`, BUY candidates top `20`, max positions `10`.
- Return: `+81.32%`.
- Max drawdown: `-15.59%`.
- Trades: buy/sell/open `224 / 214 / 10`, profit factor `1.6762`, win rate `32.24%`.

## Loss Attribution

| Bucket | Count | PnL / Return | Notes |
| --- | ---: | ---: | --- |
| `support_stop` | `125` | `-886,039.99`, avg return `-7.35%` | Main realized loss source: `120 / 125` are losers. This is the primary failure mode to diagnose before adding more buy rules. |
| `fragile_structure_stop` | `8` | `-47,011.67`, avg return `-6.10%` | Smaller but all losers; often overlaps with weak post-entry structure. |
| `trend_break` | `5` | `-17,050.99`, avg return `-3.55%` | Low count and not the main damage source. |
| `rotation_for_stronger_signal` | `11` | `-5,152.90`, avg return `-0.49%` | Rotation is not the main drawdown source, but should remain constrained by score gap and replacement quality. |
| `profit_protection_stop` | `26` | `+170,652.73`, avg return `+6.70%` | Mostly useful, but `11` cases still rebounded more than `8%` after exit; needs hold/profit review rather than broad removal. |
| `trend_trailing_stop` | `33` | `+1,442,342.35`, avg return `+44.54%` | Main profit source; future sell-side rules must not cut these winners too early. |

## Path Diagnostics

- Closed trade count: `214`.
- Loss count: `145`.
- Sold-before-rebound count: `80`, defined as max close return at least `+8%` within `10` natural days after sell.
- Average MAE: `-4.32%`.
- Average MFE: `+13.92%`.
- By exit reason:
  - `support_stop`: `125` trades, `47` sold-before-rebound, avg MAE `-6.96%`, avg MFE `+1.64%`.
  - `fragile_structure_stop`: `8` trades, `5` sold-before-rebound, avg MAE `-5.82%`, avg MFE `+1.74%`.
  - `trend_trailing_stop`: `33` trades, `16` sold-before-rebound, avg MAE `+0.99%`, avg MFE `+62.84%`.
  - `profit_protection_stop`: `26` trades, `11` sold-before-rebound, avg MAE `+0.68%`, avg MFE `+22.45%`.
- By setup:
  - `dragon_pullback`: `131` closed trades, `86` losses, `48` sold-before-rebound, avg return `+4.37%`, avg MAE `-4.36%`, avg MFE `+15.82%`.
  - `stealth_low_suction`: `83` closed trades, `59` losses, `32` sold-before-rebound, avg return `+1.20%`, avg MAE `-4.25%`, avg MFE `+10.93%`.

Main failure mode: not a pure entry-ranking issue. The largest realized loss bucket is `support_stop`, and many stopped trades later rebound. A sell-side/hold-side experiment should be prioritized, but it must preserve `trend_trailing_stop` winners because those are the main profit engine.

## Focused Symbols

| Symbol | Finding | Evidence | Next Action |
| --- | --- | --- | --- |
| `001258.SZSE` | No closed portfolio path in `#177`. | `path-diagnostics` returned `empty`. | Use candidate trace/signal history before treating it as a sell-path sample. |
| `002208.SZSE` | No closed portfolio path in `#177`. | `path-diagnostics` returned `empty`. | Use candidate trace/signal history; not enough portfolio evidence here. |
| `002384.SZSE` | Sell-side issue is visible. One late `2026-05-27` entry lost `-7.92%` but rebounded `+19.02%` after exit; earlier `2026-03-23` trade closed `+3.09%`. | `2026-05-27 -> 2026-06-02`, `support_stop`, MAE `-11.63%`, MFE `+2.94%`, sold-before-rebound `true`. | Review why earlier low-suction buildup around March/April was not the executed key point, and test hold/rebound-aware sell rules carefully. |
| `002119.SZSE` | Loss is small and not a sold-before-rebound case. Hard reject already failed globally in `0.1.22/#186`. | `2026-02-06 -> 2026-02-10`, return `-1.49%`, MAE `-2.88%`, MFE `-1.51%`, post-exit return `-5.30%`. | Keep as risk evidence, not as a default hard rejection. |
| `002443.SZSE` | User-reported buy date exists. It had MFE `+11.82%` but exited at `-4.86%`, so profit giveback before support stop is the key issue. | `2026-05-14 -> 2026-06-04`, `support_stop`, MAE `-5.27%`, MFE `+11.82%`, no post-exit rebound. | Prioritize dynamic highest-profit drawdown/profit-giveback sell experiment. |

## Decision

The next experiment should be sell-side / hold-side, not a direct entry-ranking change.

Reasoning:

1. Loss attribution is dominated by `support_stop` (`-886,039.99` realized PnL), with many sold-before-rebound cases.
2. `002443.SZSE` specifically shows high MFE before final loss, matching the requested “highest-profit drawdown” sell hypothesis.
3. Trend winners are the main profit source; broad early-stop rules already failed in `0.1.19/#173` and `0.1.20/#174`, so the next sell rule must be narrow, explainable, and gated by current buy/hold structure.
4. Entry/ranking work remains relevant for symbols with no portfolio path, but Task 2 evidence does not justify changing buy ranking before sell-side path control.

No strategy rule was changed in this task.

## Evidence Commands

```bash
curl -s 'http://localhost:8000/api/quant/strategies'
curl -s 'http://localhost:8000/api/backtests?limit=3&run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true'
curl -s 'http://localhost:8000/api/backtests/177/trade-attribution?sort=pnl_asc&limit=300'
curl -s 'http://localhost:8000/api/backtests/177/path-diagnostics?lookahead_days=10&limit=500'
curl -s 'http://localhost:8000/api/backtests/177/path-diagnostics?vt_symbol=001258.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/177/path-diagnostics?vt_symbol=002208.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/177/path-diagnostics?vt_symbol=002384.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/177/path-diagnostics?vt_symbol=002119.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/177/path-diagnostics?vt_symbol=002443.SZSE&lookahead_days=10&limit=50'
curl -s 'http://localhost:8000/api/backtests/177/report?trade_limit=20&include_analysis=true'
```
