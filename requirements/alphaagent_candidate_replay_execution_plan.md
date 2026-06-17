# AlphaAgent Candidate Observation And Trade Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` or equivalent task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate "candidate observation" from "strategy trade replay" so users can inspect the top 100 scored candidates without forced low-suction slots, and inspect one stock's paired buy/sell strategy replay without confusing every low-suction day as a buy point.

**Architecture:** Keep one public strategy, one candidate pool, and one single-stock detail page. Back end continues to rank candidates by score and portfolio execution still uses the configured candidate limit; front end adds candidate pagination and a stock-detail mode switch between candidate signals and trade replay. Strategy payloads mark low-suction buildup as observation until a key launch confirmation. A separate hard-reject experiment for structurally stretched non-low-suction dragon-pullback entries was tested and rejected globally, so it is kept only as risk evidence.

**Tech Stack:** FastAPI, SQLAlchemy, PostgreSQL, React, TanStack Query, TypeScript, pytest, Vite.

---

## Scope

This plan implements four concrete changes:

1. Candidate observation shows up to top 100 ranked candidates with pagination. It does not reserve slots for low-suction or any setup; rows are ranked only by score/order saved by the screen run.
2. Candidate wording distinguishes `WATCH / 蓄势观察` from `BUY / 关键买点`.
3. Stock detail gets a simple toggle: `交易复盘` and `候选信号`; `交易复盘` shows paired strategy buy/sell points, while `候选信号` shows theoretical candidate/signal points. A score such as `75+` can be inspected as a strategy signal threshold without implying that the portfolio bought it.
4. The `002119.SZSE` repeated stretched dragon-pullback issue is documented as a risk pattern, but not implemented as a default hard rejection because global backtest `0.1.22/#186` was worse than `0.1.21/#175`.

Out of scope:

- No new public strategy.
- No forced low-suction quota.
- No new page-level workflow.
- No 14:30 historical execution logic.

## Files

- Modify `alphaagent/server/services/quant/screening_payloads.py`
  - Ensure candidate payload exposes setup/action wording needed by UI.
- Modify `alphaagent/server/services/quant/screening.py`
  - Keep ranking score-based, raise default recommendation limit to 100 for observation, and preserve execution candidate limit separately.
- Modify `alphaagent/server/api/quant.py`
  - Keep `limit` bounded, allow front end to request 100.
- Modify `frontend/src/features/quant/constants.ts`
  - Add `DEFAULT_CANDIDATE_OBSERVATION_LIMIT = 100`.
  - Keep `DEFAULT_EXECUTION_CANDIDATE_LIMIT = 20`.
- Modify `frontend/src/pages/QuantTradingPage.tsx`
  - Fetch top 100 recommendations for observation only.
  - Pass observation limit and paging state to recommendations panel.
- Modify `frontend/src/features/quant/RecommendationsPanel.tsx`
  - Add pagination for top 100.
  - Update text from "前 20" to "观察前 100 / 执行前 20".
  - Keep sort by stored rank.
- Modify `frontend/src/pages/StockDetailPage.tsx`
  - Add toggle state: `candidate_signals` and `trade_replay`.
  - Feed chart markers and summary panels from selected mode, instead of merging portfolio trades, global replay, single-stock replay, and candidate signals into one ambiguous marker list.
- Modify `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
  - Present signal table as candidate signal review, not paired trade replay.
  - Show low-suction buildup rows as observation unless launch confirmation makes them key buy.
- Modify `tests/alphaagent/test_quant_backtest_portfolio.py`
  - Add focused tests for 002119-like stretched dragon-pullback rejection.
  - Add tests for low-suction launch as a key signal.
  - Add API behavior tests for recommendation limit 100 if not already covered.

## Tasks

### Task 1: Lock Candidate Observation Limit

**Files:**
- Modify: `frontend/src/features/quant/constants.ts`
- Modify: `frontend/src/pages/QuantTradingPage.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Reuse the existing recommendation API limit path and let the front end request 100 ranked rows for observation.

- [x] Step 2: Add a separate observation constant of `100`; do not reuse it for portfolio/backtest execution. Keep execution `candidate_limit` at `20`.

- [x] Step 3: In the front end, use `DEFAULT_CANDIDATE_OBSERVATION_LIMIT = 100` for recommendation fetches and display.

- [x] Step 4: Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
pnpm --dir frontend run build
```

Expected: tests pass; Vite may keep the existing chunk-size warning.

### Task 2: Add Candidate Pagination

**Files:**
- Modify: `frontend/src/features/quant/RecommendationsPanel.tsx`

- [x] Step 1: Add local page state with page size 20.

- [x] Step 2: Apply filters before pagination and slice rows for the current page.

- [x] Step 3: Add previous/next buttons and display `第 X-Y / N 个候选`.

- [x] Step 4: Keep the table sorted by stored API order; do not add setup-specific sorting, low-suction reservation, or forced setup quotas.

- [x] Step 5: Run:

```bash
pnpm --dir frontend run build
```

Expected: build passes.

### Task 3: Clarify Signal Semantics

**Files:**
- Modify: `alphaagent/server/services/quant/screening_payloads.py`
- Modify: `alphaagent/server/services/quant/strategies/dragon_pullback.py`
- Modify: `frontend/src/features/quant/RecommendationsPanel.tsx`
- Modify: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add payload fields or stable evidence notes:
  - `entry_setup`
  - `low_suction_launch_confirmed`
  - `fresh_tail_buy`
  - `tail_buy_repeat_days`
  - `key_entry_signal` or equivalent boolean for the launch/first actionable signal.

- [x] Step 2: Update UI labels:
  - `stealth_low_suction` with launch confirmation: `低吸启动买点`
  - `stealth_low_suction` without launch confirmation: `低吸蓄势观察`
  - repeated dragon signal: `重复信号观察` unless it is selected by actual trade replay.

- [x] Step 3: Add tests proving low-suction buildup days can score but are not all described as key buy points.

- [x] Step 4: Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
pnpm --dir frontend run build
```

Expected: tests and build pass.

### Task 4: Audit Stretched Dragon Pullback Hard-Reject Experiment

**Files:**
- Test: `tests/alphaagent/test_quant_backtest_portfolio.py`

- [x] Step 1: Add a risk-evidence test for a 002119-like setup:
  - `setup_type = dragon_pullback`
  - `low_suction_days = 0`
  - `ma_convergence_pct >= 18`
  - `return_20d >= 40`
  - `near_limit_up_count_20d >= 3`
  - repeated tail buy
  Expected evidence: the risky structure is exposed, but the default strategy does not force a hard reject.

- [x] Step 2: Run global experiment `0.1.22/#186` with a minimal hard-reject rule and compare against `0.1.21/#175`.

- [x] Step 3: Reject and remove the rule from default metadata because `#186` reduced return and worsened drawdown.

- [x] Step 4: Run:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
```

Expected: all tests pass; the risk-evidence test must not require a default hard reject.

### Task 5: Stock Detail Mode Switch

**Files:**
- Modify: `frontend/src/pages/StockDetailPage.tsx`
- Modify: `frontend/src/features/stocks/StockQuantAuditPanel.tsx`

- [x] Step 1: Add state:

```ts
const [quantViewMode, setQuantViewMode] = useState<"candidate_signals" | "trade_replay">("trade_replay");
```

- [x] Step 2: Add a compact segmented control near the strategy panel:
  - `交易复盘`
  - `候选信号`

- [x] Step 3: In `交易复盘`, show paired portfolio/single-stock buy-sell markers and closed-trade stats.

- [x] Step 4: In `候选信号`, show theoretical signal markers and signal tables. Make text explicit that candidate signals do not guarantee a portfolio order.

- [x] Step 5: Ensure chart markers follow the selected mode instead of merging all modes into one ambiguous marker set.

- [x] Step 6: In candidate mode, use signal/action semantics:
  - `BUY` only when the signal is executable by strategy rules.
  - `WATCH`/observation when the score is high but launch/risk/execution conditions are missing.
  - A high score threshold such as `75+` is a signal-review lens, not automatic evidence of a portfolio buy.

- [x] Step 7: Run:

```bash
pnpm --dir frontend run build
```

Expected: build passes.

### Task 6: End-To-End Verification With 002119

**Files:**
- No planned source edits unless verification exposes a defect.

- [x] Step 1: Rebuild/restart API and front end if needed.

- [x] Step 2: Check current strategy version and latest baseline:

```bash
curl -s 'http://localhost:8000/api/quant/strategies'
curl -s 'http://localhost:8000/api/backtests?limit=3&run_type=portfolio&strategy=mainline_dragon_pullback&baseline_only=true'
```

- [x] Step 3: Re-run candidate/signal checks for `002119.SZSE`:

```bash
curl -s 'http://localhost:8000/api/quant/symbols/002119.SZSE/signal-history?strategy=mainline_dragon_pullback&start=2026-01-15&end=2026-06-17'
curl -s 'http://localhost:8000/api/backtests/<id>/symbols/002119.SZSE'
curl -s 'http://localhost:8000/api/backtests/<id>/candidate-trace?vt_symbol=002119.SZSE&signal_date=2026-04-30'
```

- [x] Step 4: Verify expected behavior:
  - `2026-02-05` stretched non-low-suction dragon entry is visible as a risk pattern; the broad hard-reject experiment was not kept because global results worsened.
  - `2026-04-30` remains visible as low-suction launch candidate, but only buys if rank/execution rules select it.
  - Candidate page can inspect ranks 1-100 through pagination.
  - Stock detail can switch between candidate signals and paired trade replay.

- [ ] Step 5: Run final checks:

```bash
uv run pytest tests/alphaagent/test_quant_backtest_portfolio.py -q
uv run python -m compileall alphaagent/server/api alphaagent/server/services alphaagent/market alphaagent/data_sources alphaagent/server/db
pnpm --dir frontend run build
git diff --check
```

Expected: all checks pass, except Vite may emit the existing chunk-size warning.

## Completion Criteria

- Candidate observation shows top 100 with pagination and keeps score ranking.
- Execution candidate limit remains 20 and max positions remains 10.
- Low-suction buildup days are not all presented as buy points.
- Low-suction launch confirmation is presented as the key signal.
- Stock detail can switch between theoretical candidate signals and paired trade replay.
- 002119-style stretched dragon pullback without low-suction buildup is documented as a risk pattern, but not kept as a default hard reject after global validation failed.
- Tests/build/checks pass.
