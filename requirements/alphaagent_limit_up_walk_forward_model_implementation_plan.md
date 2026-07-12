# AlphaAgent 打板 Walk-forward 净期望模型实施计划

> **For agentic workers:** Execute this plan inline with test-first checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit unless the user explicitly requests it.

**Goal:** 在现有 600 日逐日 Top5 账本上实现严格时序隔离的成交、封板、盈利和净收益模型，每日最多输出 0-2 只研究计划，并以锁定留出、成本压力、校准和回撤门槛决定是否允许升级。

**Architecture:** 新模型只消费持久化 `limit_up_history_replays`，不改变 `limit-up-history-v3` 候选账本。每个滚动测试窗使用前 252 个交易日，末 63 日只做校准，随后预测 63 日；最后 120 日使用留出开始前冻结的同一个模型。API 返回模型、窗口、计划、压力和验收报告，前端与既有日期/买点/退出口径联动，但不向普通用户暴露参数开关。

**Tech Stack:** Python 3.13、LightGBM、scikit-learn、pandas、FastAPI、React、TypeScript、TanStack Query、Vitest。

---

### Task 1: Runtime dependencies and fixed model contract

**Files:**
- Modify: `pyproject.toml`
- Modify: `Dockerfile.alphaagent-api`
- Create: `alphaagent/server/services/limit_up/walk_forward_model.py`
- Test: `tests/alphaagent/test_limit_up_walk_forward_model.py`

- [x] Add `scikit-learn>=1.6.1` and `lightgbm>=4.6.0` to the server dependency group without installing the full `alpha` extra.
- [x] Define immutable constants for `252` training days, `63` calibration days, `63` test days, `120` locked holdout days, `2` daily plans and model version `limit-up-walk-forward-v1`.
- [x] Define the numeric feature list exclusively from `known_at_signal`, plus target board and prior streak. Do not include final seal, same-day close, D+1 fields, candidate action or holdout statistics.
- [x] Add a test that mutates outcome fields and proves `feature_vector(candidate)` is unchanged.

### Task 2: Point-in-time sample and window builder

**Files:**
- Modify: `alphaagent/server/services/limit_up/walk_forward_model.py`
- Test: `tests/alphaagent/test_limit_up_walk_forward_model.py`

- [x] Flatten persisted Top5 candidates into dated samples with `signal_date`, `result_date`, features, fill proxy, final seal, profit and selected D+1 net return.
- [x] Treat auction and next-auction open entries as daily-open fill proxies; sweep fill is only a touch proxy; tail fill is unavailable and must never become executable.
- [x] Build expanding test windows up to the locked holdout boundary and one frozen holdout window. Assert every training/calibration sample has `result_date < test_start`.
- [x] Add a mutation test proving changed holdout outcomes cannot alter training dates, model inputs, thresholds or expanding-OOS predictions.

### Task 3: Calibrated LightGBM model bundle

**Files:**
- Modify: `alphaagent/server/services/limit_up/walk_forward_model.py`
- Test: `tests/alphaagent/test_limit_up_walk_forward_model.py`

- [x] Train fixed low-complexity LightGBM classifiers for fill where observable, final seal and positive return, plus a regressor for net return.
- [x] Fit probability calibration only on the chronological 63-day calibration slice; report raw and calibrated Brier scores.
- [x] Build deterministic calibration score buckets and bootstrap their mean net return to produce an 80% lower confidence bound without reading test or holdout labels.
- [x] Return `insufficient_training` instead of fitting when dates, classes or closed returns are inadequate.

### Task 4: Daily 0-2 plans and acceptance report

**Files:**
- Modify: `alphaagent/server/services/limit_up/walk_forward_model.py`
- Test: `tests/alphaagent/test_limit_up_walk_forward_model.py`

- [x] Score every test candidate with fill, seal and profit probability, expected return, lower confidence bound and model EV.
- [x] Mark a candidate `model_eligible` only when calibrated probabilities, positive EV and the training-only confidence lower bound pass fixed gates; sort by EV and retain at most two per day.
- [x] Keep `simulation_eligible=false` whenever execution evidence is daily proxy, L2 is absent or historical industry membership is not point-in-time.
- [x] Summarize expanding OOS and holdout trades with count, win rate, mean, compounded return, maximum drawdown, profit factor, hard-loss rate, positive-quarter ratio and concentration.
- [x] Add doubled-cost stress and an acceptance checklist matching `alphaagent_limit_up_compounding_system_design.md`; `upgrade_status` is `eligible` only when every gate passes.

### Task 5: Service and API

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/api/limit_up.py`
- Test: `tests/alphaagent/test_limit_up_walk_forward_model.py`

- [x] Add a cached `get_history_model_report(start, end, entry_mode, exit_mode)` service over persisted history rows.
- [x] Add `GET /api/limit-up/history/model-report` with the same date, entry and exit validation as the existing history reports.
- [x] Include explicit `candidate_scope`, `execution_scope`, feature/model versions, window boundaries, limitations and rejection reasons.
- [x] Test parameter forwarding, invalid ranges and structured service failures.

### Task 6: Product interface

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Create: `frontend/src/features/limitUp/WalkForwardModelPanel.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Test: `frontend/src/features/limitUp/WalkForwardModelPanel.spec.tsx`

- [x] Add typed model report contracts and a fetcher keyed by the shared start, end, entry mode and exit mode.
- [x] Show current research/upgrade status, model plan versus Top5 baseline, expanding OOS versus locked holdout, calibration, doubled-cost stress and every acceptance gate.
- [x] Show each 63-day test window and representative selected/rejected candidates; never label proxy plans as fills or live orders.
- [x] Keep tables in local horizontal scrollers and preserve the existing dense workbench layout on desktop and `390x844` mobile.

### Task 7: Real-data validation and durable evidence

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/06_backtests/limit_up_short_term_factor_research.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] Run the report on all four entry modes and both D+1 exits against the persisted 600-day ledger.
- [x] Record actual expanding-OOS, holdout, stress, calibration and acceptance results without tuning from holdout.
- [x] Run focused and full limit-up/data-sync tests, frontend tests, production build and `git diff --check`.
- [x] Rebuild API/Web images and verify health plus `/limit-up` on desktop and `390x844` using Playwright.
- [x] Keep the strategy in research state if any mandatory gate fails; do not claim stable compounding.
