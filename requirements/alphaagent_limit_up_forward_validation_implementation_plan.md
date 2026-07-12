# AlphaAgent 打板严格前向验证实施计划

> **For agentic workers:** Execute this plan inline with test-first checkpoints. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit unless the user explicitly requests it.

**Goal:** 只用系统在交易时段真实保存的非过期盘中信号建立前向观察账本，并在下一交易日行情到齐后闭合结果，让用户按日期、四种买点和 D+1 开盘/收盘口径核验真实推荐质量。

**Architecture:** 新建独立 `forward_validation.py`，先对 `limit_up_signal_snapshots` 做来源、时点、交易日和交易阶段审计，再复用 `build_limit_up_entry_backtest(..., historical_proxy_candidates=[])` 解析计划与 D+1 结果。历史代理、stale 和非交易日快照只进入排除统计；无合格快照或无闭合交易时收益字段保持空值，不能显示成 0% 策略。前端新增一个与现有日期区间、买点和退出口径联动的只读面板。

**Tech Stack:** Python 3.13、SQLAlchemy、FastAPI、React 18、TypeScript、TanStack Query、Vitest、Playwright。

---

### Task 1: Freeze the forward-validation contract

**Files:**
- Create: `tests/alphaagent/test_limit_up_forward_validation.py`
- Create: `alphaagent/server/services/limit_up/forward_validation.py`

- [x] Write failing tests proving that only `mode=live_snapshot`, `data_quality.is_stale=false`, matching capture/trade dates, a verified trading day and an active A-share session are eligible.
- [x] Assert that weekend, stale, historical proxy, mismatched timestamp and invalid-session snapshots each produce a structured exclusion reason and never enter plans or returns.
- [x] Define immutable contract values `limit-up-forward-validation-v1`, `research_plan_forward_observation`, 20-day process check, 60-day strategy review and `simulation_eligible=false`.

### Task 2: Preserve the action that was actually available

**Files:**
- Modify: `alphaagent/server/services/limit_up/entry_backtest.py`
- Test: `tests/alphaagent/test_limit_up_forward_validation.py`

- [x] Add a regression test where a later snapshot changes an intraday signal and prove the first saved `buy_now` action and trigger price remain unchanged.
- [x] Add a regression test where the morning and tail `next_auction` plans differ and prove only the final valid snapshot for that trade date is used; withdrawn earlier symbols must not survive as a union.
- [x] Add an optional `trade_calendar` dataset field so D/D+1 offsets follow the market calendar rather than one stock's bar availability.
- [x] Fix fixed-exit semantics so both `next_open` and `next_close` always resolve to the first trading day after the actual entry date.

### Task 3: Build the strict forward ledger

**Files:**
- Modify: `alphaagent/server/services/limit_up/forward_validation.py`
- Test: `tests/alphaagent/test_limit_up_forward_validation.py`

- [x] Implement `build_forward_validation_report(dataset, snapshots, trade_calendar, entry_mode, exit_mode, current_date)` as a deterministic function.
- [x] Call `build_limit_up_entry_backtest` with only eligible snapshots and an explicit empty `historical_proxy_candidates` list.
- [x] Return raw/eligible/excluded snapshot counts, exclusion buckets, observed dates, 20/60-day progress, plan/closed/pending/rejected counts, recent orders, closed trades and D+1 results.
- [x] Derive entry-day final seal from the completed daily bar for reporting only; never feed it back into signal selection or fill decisions.
- [x] When no eligible snapshot exists return `status=collecting`; when no trade is closed, win rate, average return, compounded return and drawdown are `null`, not `0`.

### Task 4: Add the database-backed service and API

**Files:**
- Modify: `alphaagent/server/services/limit_up/forward_validation.py`
- Modify: `alphaagent/server/api/limit_up.py`
- Test: `tests/alphaagent/test_limit_up_forward_validation.py`

- [x] Implement `get_forward_validation(start, end, entry_mode, exit_mode)` using the saved live strategy version, the local stock trading calendar and only the symbols present in eligible snapshots.
- [x] Load enough D-1/D/D+1 bars to resolve auction gaps, entry-day seal and the next-trading-day exit while preserving pending results when bars are not yet available.
- [x] Add `GET /api/limit-up/forward-validation?start=&end=&entry_mode=&exit_mode=` with the same literal and date-range validation used by existing history endpoints.
- [x] Test parameter forwarding, invalid ranges, database-unavailable responses and structured service errors.

### Task 5: Add the product panel

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Create: `frontend/src/features/limitUp/ForwardValidationPanel.tsx`
- Create: `frontend/src/features/limitUp/ForwardValidationPanel.spec.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] Add typed forward report, progress, coverage, observation-day and order contracts plus `fetchLimitUpForwardValidation`.
- [x] Query by the shared start/end, four-entry-mode and D+1 exit state; refresh the query after a live scan and during the current trading date.
- [x] Render a dense 20/60-day validation ruler, eligible/excluded snapshot counts, plan/closed/pending counts, nullable performance metrics and recent saved plans.
- [x] Render the `collecting` state without a fake 0% return, and label every result as forward research observation rather than fill, simulation or live order.
- [x] Keep the page un-nested, tables locally scrollable and content usable at desktop and `390x844`.

### Task 6: Verify the entire product path

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] Run the focused new backend tests, then all `test_limit_up_*.py` and data-sync tests.
- [x] Run all frontend tests, TypeScript/Vite production build and `git diff --check`.
- [x] Rebuild API/Web containers, verify health and call the new endpoint against the real database.
- [x] Validate `/limit-up` with Playwright on desktop and `390x844`: date range, four buy points, both D+1 exits, collecting state, local table scrolling, console and completed network requests.
- [x] Update durable memory with the exact eligible forward-day count and current limitation; do not describe proxy results as stable compounding.
