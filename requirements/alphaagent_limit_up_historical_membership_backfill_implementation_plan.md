# Limit-up Historical Membership Backfill Implementation Plan

> **For agentic workers:** Use `executing-plans` inline. Steps use checkbox (`- [ ]`) syntax for tracking. Do not commit unless the user explicitly requests it.

**Goal:** Rebuild auditable daily Shenwan level-2 memberships and make limit-up history consume them point in time.

**Architecture:** A dedicated import service fetches membership intervals from the configured provider, expands them only across reliable local trade dates, audits daily main-board coverage, and atomically replaces the industry scope. Data-quality SQL validates actual daily coverage; history repository merges snapshots by date before current-membership fallback. User CSV/template/file paths are intentionally absent.

**Tech Stack:** Python 3.13, requests, SQLAlchemy/PostgreSQL, pandas, FastAPI, React 19, TanStack Query, pytest, Vitest, Playwright.

---

### Task 1: Pure interval contract

**Files:**
- Create: `alphaagent/server/services/limit_up/historical_membership_import.py`
- Create: `tests/alphaagent/test_limit_up_membership_import.py`

- [ ] Normalize Tushare interval rows, main-board filter and L2 fields.
- [ ] Expand `in_date <= D < out_date`, resolve overlaps by latest `in_date`, and report conflicts.
- [ ] Audit each date against expected local daily symbols with a 90% minimum.

### Task 2: Scoped persistence and provider import

**Files:**
- Modify: `alphaagent/server/services/market_snapshot_repository.py`
- Modify: `alphaagent/server/services/limit_up/historical_membership_import.py`
- Test: `tests/alphaagent/test_limit_up_membership_import.py`

- [ ] Add industry-scoped atomic replacement that preserves concept rows.
- [ ] Query `index_classify(L1, SW2021)` then `index_member_all` per L1 code.
- [ ] Add bounded reliable-date selection, token guard, dry-run and per-date summaries.

### Task 3: Strict data quality and point-in-time history

**Files:**
- Modify: `alphaagent/server/services/limit_up/data_quality_repository.py`
- Modify: `alphaagent/server/services/limit_up/history_repository.py`
- Test: `tests/alphaagent/test_limit_up_data_quality.py`
- Test: `tests/alphaagent/test_limit_up_history.py`

- [ ] Count only dates where industry snapshot symbols cover at least 90% of that day's eligible daily-bar symbols.
- [ ] Report raw snapshot, industry, concept and qualifying trade days separately.
- [ ] Merge daily primary industry snapshots into the historical frame before current-membership fallback.
- [ ] Prove later membership changes cannot alter earlier dates.

### Task 4: API and product controls

**Files:**
- Modify: `alphaagent/server/api/data_sync.py`
- Modify: `frontend/src/api/dataSync.ts`
- Create: `frontend/src/features/limitUp/HistoricalMembershipBackfillPanel.tsx`
- Create: `frontend/src/features/limitUp/HistoricalMembershipBackfillPanel.spec.tsx`
- Modify: `frontend/src/features/limitUp/LimitUpEvidenceBackfillPanel.tsx`

- [ ] Add status and bounded Tushare endpoints; keep old template/CSV routes at `404`.
- [ ] Add typed client contracts and an un-nested industry-membership section in the existing tab.
- [ ] Render token state, daily coverage, date audit and write confirmation on desktop/mobile.

### Task 5: Verification and durable evidence

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] Run focused/full backend and frontend tests, compile, build and `git diff --check`.
- [ ] Rebuild API/Web and verify authenticated status, token-unavailable and removed-route `404` paths.
- [ ] Verify `/data` and `/limit-up` desktop/mobile, console, network and no whole-page overflow.
- [ ] Record actual coverage only; with no token/data imported, keep historical membership at zero and simulation blocked.
