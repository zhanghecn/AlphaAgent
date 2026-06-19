# Dynamic Market Context Audit

## Scope

- Strategy/run: `mainline_dragon_pullback / 0.1.21`, backtest `#190`.
- Range: `2025-03-26` to `2026-06-17`.
- Execution model: `legacy_next_open`, BUY top `20`, max positions `10`.
- New code: dynamic market-context audit only; no buy/sell behavior changed.

## Data Coverage

Current local database check:

| Dataset | Coverage |
| --- | --- |
| `stock_daily_bars` | `2025-03-26` to `2026-06-17`, about `1,019,820` rows |
| index bars for `000001.SSE`, `000300.SSE`, `000905.SSE`, `000852.SSE`, `399001.SZSE`, `399006.SZSE`, `000688.SSE` | `0` rows |
| `sector_period_scores` | `900` rows, only `2026-06-12`, `2026-06-13`, `2026-06-17` |
| `stock_sector_memberships` | `54,698` rows |

Because index bars and historical sector scores are incomplete, the current dynamic market-context audit uses `benchmark_return_20d_proxy`: a 20-trading-day market return proxy. It can audit strong/weak/choppy/crash-like windows, but it cannot yet prove precise sector mainline pullback behavior.

## Current Result On `#190`

Real closed portfolio top-10 candidate audit:

| Metric | Value |
| --- | ---: |
| Top-10 candidate rows | `1,868` |
| Closed/evaluated trades | `44` |
| Win rate | `43.18%` |
| Average return | `+8.34%` |
| Average excess return | `+7.23%` |
| Excluding strong-market candidate rows | `1,408` |
| Excluding strong-market evaluated trades | `38` |
| Excluding strong-market win rate | `44.74%` |
| Excluding strong-market average return | `+3.72%` |
| Excluding strong-market average excess | `+3.70%` |

Fixed 20-trading-day top-10 candidate observation:

| Metric | Value |
| --- | ---: |
| Candidate rows | `1,868` |
| Observable rows | `1,668` |
| Win rate | `46.94%` |
| Average return | `+4.26%` |
| Average excess return | `+1.72%` |
| Excluding strong-market observable rows | `1,208` |
| Excluding strong-market win rate | `48.92%` |
| Excluding strong-market average return | `+4.10%` |
| Excluding strong-market average excess | `+3.94%` |

Dynamic market proxy buckets, real closed top-10 candidates:

| Regime | Candidates | Evaluated | Win Rate | Avg Return | Avg Excess |
| --- | ---: | ---: | ---: | ---: | ---: |
| 普涨强势 | `460` | `6` | `33.33%` | `+37.66%` | `+29.59%` |
| 震荡轮动 | `1,098` | `29` | `37.93%` | `+3.37%` | `+1.63%` |
| 弱势防守 | `220` | `7` | `71.43%` | `+3.07%` | `+7.79%` |
| 快速杀跌 | `90` | `2` | `50.00%` | `+11.02%` | `+19.49%` |

Dynamic market proxy buckets, fixed 20-trading-day observation:

| Regime | Candidates | Observable | Win Rate | Avg Return | Avg Excess |
| --- | ---: | ---: | ---: | ---: | ---: |
| 普涨强势 | `460` | `460` | `41.74%` | `+4.67%` | `-4.09%` |
| 震荡轮动 | `1,098` | `1,008` | `48.12%` | `+3.43%` | `+2.15%` |
| 弱势防守 | `220` | `160` | `55.00%` | `+8.37%` | `+13.11%` |
| 快速杀跌 | `90` | `40` | `45.00%` | `+3.95%` | `+12.38%` |

Theme alignment is still limited by missing historical sector scores:

| Alignment | Candidates | Evaluated | Current Meaning |
| --- | ---: | ---: | --- |
| 主线内 | `2` | `0` | Too little evidence; not usable yet |
| 主线相关 | `6` | `0` | Too little evidence; not usable yet |
| 独立强票 | `302` | `9` | Weak/crash proxy windows with surviving candidates |
| 未知 | `1,558` | `35` | Most historical rows lack usable theme state |

## Interpretation

This audit supports adding market-context visibility to the UI, but it does not prove a new trading edge yet.

Useful evidence:

- Top-10 candidates still have positive average returns after excluding strong-market windows.
- Fixed 20-day observation also stays positive after excluding strong-market windows.
- Weak/crash proxy buckets are not automatically bad in this sample; a small set of candidates produced positive excess returns, which matches the user's hypothesis that bear/weak markets may still have a few low-suction setups preparing to launch.

Limitations:

- Closed-trade sample sizes inside weak/crash buckets are small.
- The current proxy cannot identify "technology mainline pullback" versus "non-technology emerging rotation".
- Theme alignment is mostly unknown until historical sector scores are backfilled.
- No buy/sell rule changed, so this is not a return improvement claim.

## Decision

Keep dynamic market context as a first-screen audit and explanation layer. Do not use it yet as a hard buy threshold, sell rule, or position-size rule.

Next work should backfill index bars and historical sector scores, then re-run this audit. Only after that should market context become a dynamic threshold or warehouse-control algorithm.

## 2026-06-19 Read-side Integration

`GET /api/backtests/{id}/path-diagnostics` now annotates each closed trade path
with the same read-only market context at `entry_date`. This gives stock detail
and path review the same fields already used by setup/market/exit audit:

- `dynamic_market_regime` / `dynamic_market_label`
- `dynamic_market_source`
- `market_warning_label`
- `fund_flow_label`
- `recovery_label`
- `stock_theme_alignment`

Runtime check on `#194` after rebuilding the API container:

| Field | Value |
| --- | ---: |
| Closed paths returned | `214` |
| Dynamic market source | `stock_daily_bars` for all `214` rows |
| Market regimes present | `choppy_rotation`, `false_bull`, `strong_broad` |
| `rebound_prone_support_stop_review` rows | `60` |

This is not a trading result and does not alter buy/sell behavior. It only makes
path diagnostics explain whether a trade was opened in a choppy, false-bull, or
strong-broad market bucket, plus the visible risk/recovery labels.
