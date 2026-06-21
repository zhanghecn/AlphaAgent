# Strategy Optimization Ledger

这个台账只保留当前仍有决策价值的策略结论。过程报告、截图、raw JSON、CSV 和长日志不作为长期记忆保留；需要复核时从持久化回测编号、API 和测试入口重新查。

## Current Product Baseline

- Public strategy: `mainline_dragon_pullback / 0.1.21`.
- Range: `2025-03-26..2026-06-18`.
- Execution model: `legacy_next_open`, signal visible at D close, fill at D+1 daily open.
- Candidate observation: top `100`, paged `20`.
- Portfolio execution: BUY candidates top `20`, max positions `10`.
- Product default follows the historical high-return runs `#203/#194`: return about `+82.99%`, max drawdown about `-15.59%`, closed win rate `32.24%`, PF `1.6762`, buy/sell/open `224 / 214 / 10`.
- Portfolio backtests recompute candidates by default; persisted `quant_signal_runs` cache is only allowed when `reuse_signal_cache=true` is explicitly set for diagnostics/speed, and such runs are excluded from product baselines.
- Clean no-cache analysis run `#275` is explicitly `reuse_signal_cache=false`, return about `+48.80%`, max drawdown about `-23.83%`, closed win rate `29.76%`, PF `1.2420`, buy/sell/open `215 / 205 / 10`.
- `#275` does not improve both return and win rate versus `#203/#194`, so it must not replace the product default.
- Read-only attribution `GET /api/backtests/{id}/performance-attribution` now explains why a current run differs from a historical high-return comparable run. For `#275` the clean no-cache result is still far below historical `#203/#194`, but the comparison must be treated as lineage analysis, not a same-input parameter win/loss.
- `baseline_only=true` must return product-default, non-experiment runs protected by return and win-rate gates. A new clean/no-cache run may replace `#203/#194` only if it improves both return and win rate. Diagnostic run `#204`, all research-switch runs, and `reuse_signal_cache=true` runs are excluded from product baseline views.

## Product Decisions

- Keep one public strategy: `mainline_dragon_pullback`.
- Do not expose low-suction and dragon-pullback as ordinary user strategy switches.
- Market phase `主升 / 震荡 / 退潮 / 回暖` is audit/risk context only for now. It does not directly change score, rank, buy, sell, or position size.
- `低吸蓄势` is an observation cluster, not daily BUY. Only the first effective lift or later visible confirmation may become an executable buy candidate.
- `低吸首启` and `龙回头` are separate internal setup families. They share support/MA/volume/close-location features, but overlap does not auto-stack score.
- Stock detail markers are independent single-stock strategy replay markers: `买入 / 拒买 / 卖出`. They do not depend on portfolio capacity.
- Candidate independent trade quality report is read-only: it merges repeated BUY candidates into symbol clusters, simulates one theoretical D+1-open trade per cluster with current sell logic, and does not enter default signal score, buy/sell rules, portfolio sizing, or replacement decisions.
- Candidate independent trade quality uses a no-future entry rule: the trade entry is the first visible BUY in the cluster, not a later higher-score/confirmed signal. As of 2026-06-21, full rank20 candidate clusters (`#203/#275` source candidates) show about `2330` clusters, `2316` evaluated trades, `38.73%` win rate, `+1.81%` average return, `-5.86%` median return, `-7.92%` average max drawdown, and `+16.60%` average max runup.
- Candidate TopN quality must be read as candidate-pool quality, not a portfolio equity curve: Top10 means every historical signal day's ranks `1..10` are each simulated independently; Top20 means ranks `1..20` cumulatively. The separate rank-window table (`1-10 / 11-20 / 21-50 / 51-100`) shows marginal quality by daily rank band, and the signal-day table shows one trading day's Top10/Top20 outcomes.
- Portfolio backtest remains the real execution truth: BUY signal still must pass D+1 open, cash, max-position, limit-up/limit-down, rank, and replacement constraints.
- Portfolio backtest reproducibility rule: default runs must not read historical candidate caches. Cache reuse is an explicit diagnostic mode only and is marked by `assumptions.signal_cache_reuse`.
- Product promotion rule: do not select a new strategy/run as default unless both return and win rate improve over the current product default.

## Current Diagnosis

- Candidate quality has measurable positive edge after removing position constraints: full rank20 independent candidate trades average about `+1.81%` with `38.73%` win rate, but the median trade remains negative. The larger loss source is still the execution chain: full positions, replacement quality, sell timing, and protection of existing trend winners.
- Max positions `10` is not the main bottleneck. The post-fix 2026-06-21 sensitivity grid found:
  - Capital-neutral sizing: `5 x 20%` `+59.09%` / DD `-26.00%`; `10 x 10%` `+45.17%` / DD `-23.83%`; `15 x 6.67%` `+45.67%` / DD `-21.92%`; `20 x 5%` `+29.47%` / DD `-18.62%`.
  - Slot-only with fixed `10%`: `5` slots `+29.22%`; `10` slots `+45.17%`; `15` slots `+65.93%` with `89` insufficient-cash rejects; `20` slots `+45.17%` with `488` insufficient-cash rejects.
- Interpretation: wider portfolios dilute the candidate edge; more concentrated portfolios can lift return but increase drawdown. Fixed `10%` with more than `10` slots is a cash-constraint experiment, not a clean capacity improvement.
- Baseline reproducibility was tightened before further parameter grids. Default portfolio backtests no longer read persisted score caches; explicit score-cache reuse now requires the current `signal_evidence_schema_version`; old `#203/#194` and current-schema results should not be mixed in comparisons.
- The apparent return/win-rate drop from `#203/#194` to `#275` is mainly a baseline lineage problem, not a max-position effect: old high-return runs used older candidate-cache semantics, while `#275` recomputes candidates from current code and data. Silent cache reuse was unsafe because it let a current backtest consume historical candidate inputs whose generation code and evidence semantics were different. Product default still follows `#203/#194` until a new run beats both return and win rate.
- The measured drop is mostly reduced winner contribution: `#274` gross wins are about `37.76` 万 lower while gross losses are only about `1.03` 万 worse. Trend trailing winners dropped from `33` to `24` closed trades and contributed about `34.98` 万 less. This points to winner admission/protection and replacement path quality, not just raw win-rate chasing.
- Phase reports no longer treat current-schema signal events as all unknown: nested `raw.evidence` is expanded and missing rows get visible market context annotation. For `#274`, real trades group roughly as `震荡 106 / 退潮 86 / 主升 17`; `#275` should be the next phase-distribution reference after runtime report refresh.
- `support_stop` is not one sell bug. It mixes failed launch, sold-before-rebound, float-profit giveback, and bad replacement after a sell.
- Broad fixes have repeatedly failed: direct low-suction score boosts, hard low-suction gates, simple market weighting, failed-launch early exits, high-score rotation, weak-holding rotation, and protected weak-holding rotation all stayed below the baseline.
- The next useful work should be narrow and default-off: execution consistency, trend-winner protection, replacement quality, and no-future single-stock marker correctness.

## Major Experiments

| Run | Tested | Result | Decision |
| --- | --- | --- | --- |
| `#203/#194` | Historical high-return default strategy lineage. | `+82.99%`, max DD `-15.59%`, `224 / 214 / 10`. | Current product default while analysis continues. |
| `#275` | Clean no-cache product parameters. | `+48.80%`, max DD `-23.83%`, `215 / 205 / 10`. | Analysis baseline only; not promoted because return and win rate are lower. |
| `#274` | Current-schema cached reference before the cache boundary was tightened. | `+45.17%`, max DD `-23.83%`, `219 / 209 / 10`. | Historical/diagnostic only; not current baseline. |
| `#255..#258` | Low-suction-only, dragon-only, phase-aware selector, phase selector plus replacement quality. | Returns `+15.87% / +38.56% / +45.52% / +39.19%`; all below baseline. | Rejected. Splitting strategy families or adding phase selector did not improve the portfolio path. |
| `#259/#260` | Low-suction MA10 pullback entry with and without slot reservation. | `+43.63%` and `+23.09%`; both worse drawdown than baseline. | Rejected. Pullback wait semantics need narrower confirmation and better execution handling. |
| `#261` | Low-suction trigger-day confirmation, buy next open. | `+46.81%`, max DD `-24.47%`. | Rejected. Candidate-level confirmation has value, but current sell/replacement path loses too much. |
| `#262/#263/#264` | Low-suction branch exits, replacement quality gate, strict replacement setup gate. | Best variant `#264` about `+55.25%`, still far below baseline. | Rejected. The direction reduces some weak replacements but misses trend payoff. |
| `#265/#267` | Dynamic failed-launch exit and replacement-quality gate. | `+32.56%` and `+34.76%`, both worse DD than baseline. | Rejected. Early exits release slots into worse replacements and miss winners. |
| `#268` | High-quality trend candidate rotation when full. | `+42.40%`, max DD `-21.97%`. | Rejected. Broad high-score rotation disrupts trend winners. |
| `#270/#271` | Weak-holding quality rotation and protected weak-holding rotation. | `+39.63%` and `+42.28%`, max DD `-22.55%`. | Rejected. D+1 weak holdings often repair by open; tradable replacement set is too small and weak. |
| `#214..#217` | Support-stop delay, peak giveback, low-suction false-launch watch, missed-candidate quality rotation. | All materially below baseline. | Rejected as default rules. |
| `#195..#201/#207/#208/#211` | Mid-profit giveback, low-suction launch gates, repeated dragon, launch quality/risk score, failed-launch exit variants. | Some reduce local loss buckets, none improve full portfolio return over baseline. | Keep as audit context only. |
| `#175/#177/#190/#194` | Low-suction/dragon boundary and current `0.1.21` refresh lineage. | Current lineage fixed several single-stock interpretation issues and reached the current baseline. | Useful code evidence, but not proof of stable alpha across regimes. |

## Read-Only Matrices Kept In Product UI

- Candidate independent trade quality report: judges candidate quality apart from cash, max positions, full portfolio, existing holdings, and replacement. Use it to separate “candidate is good/bad” from “portfolio execution path is good/bad”; read both cumulative daily TopN and individual signal-day Top10/Top20 tables.
- Performance attribution report: compares a current run with a historical comparable run and shows parameter equality, candidate schema lineage, exit-reason contribution, missing old winners, and newly added losers. Use it first when asking why收益/胜率 changed.
- Market phase audit: use it to compare `主升 / 震荡 / 退潮 / 回暖`, not to directly weight trades.
- Phase × setup-family matrix: explains low-suction first lift, dragon pullback, buildup, and overlap buckets.
- Replacement-quality matrix: explains whether freed slots buy weak follow-up candidates.
- Rotation opportunity and trend-winner protection matrices: explain why naive rotation harms existing winners.
- Stock detail market line and unified markers: visual audit layer only; the bull/bear line does not change strategy rules.

## Verification Entrypoints

- Main backend test file: `uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q`.
- Compile check: `uv run python -m compileall alphaagent/server/api alphaagent/server/services`.
- Frontend build: `pnpm --dir frontend run build`.
- Useful APIs:
  - `GET /api/backtests?run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true&limit=5`
  - `GET /api/backtests/{id}/performance-attribution`
  - `GET /api/backtests/{id}/phase-strategy-family-matrix`
  - `GET /api/backtests/{id}/candidate-trade-quality-report`
  - `GET /api/backtests/{id}/replacement-quality-matrix`
  - `GET /api/backtests/{id}/support-stop-matrix`
  - `GET /api/backtests/{id}/rotation-opportunity-cost-matrix`
  - `GET /api/backtests/{id}/trend-winner-protection-matrix`
  - `GET /api/quant/symbols/{vt_symbol}/signal-history`
  - `GET /api/quant/symbols/{vt_symbol}/market-line`

## Open Risks

- Current baseline still overlaps a strong 2025-2026 technology/speculation window; it is not enough to claim stable alpha.
- Long historical sector/fund-flow coverage remains insufficient for robust mainline rotation.
- Weak/bear-market and non-technology regime validation still requires broader walk-forward and parameter-sensitivity checks.
- `#275` is the fresh no-cache analysis reference for future `max_positions` / `candidate_limit` sensitivity grids.
- Any future default rule must beat current product default `#203/#194` on both return and win rate, then explain whether it recovers the historical winner contribution without relying on stale candidate inputs.
