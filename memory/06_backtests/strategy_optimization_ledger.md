# Strategy Optimization Ledger

这个台账只保留当前仍有决策价值的策略结论。过程报告、截图、raw JSON、CSV 和长日志不作为长期记忆保留；需要复核时从持久化回测编号、API 和测试入口重新查。

## Current Product Baseline

- Public strategy: `mainline_dragon_pullback / 0.1.21`.
- Product baseline backtests: `#203/#194`.
- Range: `2025-03-26..2026-06-18`.
- Execution model: `legacy_next_open`, signal visible at D close, fill at D+1 daily open.
- Candidate observation: top `100`, paged `20`.
- Portfolio execution: BUY candidates top `20`, max positions `10`.
- Baseline result: return about `+82.99%`, max drawdown about `-15.59%`, closed win rate `32.24%`, PF `1.6762`, buy/sell/open `224 / 214 / 10`.
- `baseline_only=true` must return only product-default, non-experiment runs. Diagnostic run `#204`, longer-range run `#213`, and all research-switch runs are excluded from the product baseline.

## Product Decisions

- Keep one public strategy: `mainline_dragon_pullback`.
- Do not expose low-suction and dragon-pullback as ordinary user strategy switches.
- Market phase `主升 / 震荡 / 退潮 / 回暖` is audit/risk context only for now. It does not directly change score, rank, buy, sell, or position size.
- `低吸蓄势` is an observation cluster, not daily BUY. Only the first effective lift or later visible confirmation may become an executable buy candidate.
- `低吸首启` and `龙回头` are separate internal setup families. They share support/MA/volume/close-location features, but overlap does not auto-stack score.
- Stock detail markers are independent single-stock strategy replay markers: `买入 / 拒买 / 卖出`. They do not depend on portfolio capacity.
- Portfolio backtest remains the real execution truth: BUY signal still must pass D+1 open, cash, max-position, limit-up/limit-down, rank, and replacement constraints.

## Current Diagnosis

- Candidate quality is not the only problem. The larger loss source is the execution chain: full positions, replacement quality, sell timing, and protection of existing trend winners.
- `support_stop` is not one sell bug. It mixes failed launch, sold-before-rebound, float-profit giveback, and bad replacement after a sell.
- Broad fixes have repeatedly failed: direct low-suction score boosts, hard low-suction gates, simple market weighting, failed-launch early exits, high-score rotation, weak-holding rotation, and protected weak-holding rotation all stayed below the baseline.
- The next useful work should be narrow and default-off: execution consistency, trend-winner protection, replacement quality, and no-future single-stock marker correctness.

## Major Experiments

| Run | Tested | Result | Decision |
| --- | --- | --- | --- |
| `#203/#194` | Product baseline, default public strategy. | `+82.99%`, max DD `-15.59%`, `224 / 214 / 10`. | Current baseline. |
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
  - `GET /api/backtests/{id}/phase-strategy-family-matrix`
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
- Any future default rule must beat `#203/#194` on return, drawdown, replacement quality, and trend-winner preservation without future functions.
