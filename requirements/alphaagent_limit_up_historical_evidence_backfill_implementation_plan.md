# Limit-up Historical Evidence Backfill Implementation Plan

> **For agentic workers:** Use `executing-plans` inline. Steps use checkbox (`- [ ]`) syntax for tracking. Repository rules prohibit commits unless the user explicitly requests one.

**Goal:** Add an auditable Tushare/CSV product workflow that backfills historical main-board limit-event paths and opening-auction evidence without weakening strict execution gates.

**Architecture:** A focused provider service normalizes both inputs into existing evidence tables and performs per-date validation before atomic replacement. FastAPI exposes status, template, provider and CSV operations; a dedicated data-management panel drives the workflow and refreshes the limit-up data-quality view.

**Tech Stack:** Python 3.13, requests, SQLAlchemy/PostgreSQL, FastAPI, React 19, TypeScript, TanStack Query, pytest, Vitest, Playwright.

---

### Task 1: Freeze normalization and safety contracts

**Files:**
- Create: `alphaagent/server/services/limit_up/historical_evidence_import.py`
- Create: `tests/alphaagent/test_limit_up_evidence_import.py`

- [x] Test Tushare event and auction rows normalize to AlphaAgent symbols and Chinese raw keys.
- [x] Test exclusion of ST, delisted, GEM, STAR and BSE rows.
- [x] Test duplicate symbols, malformed dates, missing required fields and cross-date rows are rejected or counted explicitly.
- [x] Implement pure normalizers and date-level audit results.

### Task 2: Add atomic persistence and provider queries

**Files:**
- Modify: `alphaagent/server/services/limit_up/historical_evidence_import.py`
- Test: `tests/alphaagent/test_limit_up_evidence_import.py`

- [x] Test that empty/error/coverage-incomplete inputs preserve existing rows.
- [x] Test idempotent replacement of one event date and one auction date.
- [x] Implement Tushare REST queries for `limit_list_d` and `stk_auction` with token/config validation and structured provider errors.
- [x] Implement bounded missing-date selection, dry-run and per-date result summaries.

### Task 3: Add CSV templates and imports

**Files:**
- Modify: `alphaagent/server/services/limit_up/historical_evidence_import.py`
- Test: `tests/alphaagent/test_limit_up_evidence_import.py`

- [x] Define exact event and auction CSV headers and downloadable examples.
- [x] Parse UTF-8/UTF-8-BOM CSV, group by date and apply the same normalizers and atomic writers as Tushare.
- [x] Return parsed, accepted, written, skipped and incomplete counts plus bounded row errors.

### Task 4: Add REST contracts

**Files:**
- Modify: `alphaagent/server/api/data_sync.py`
- Test: `tests/alphaagent/test_limit_up_evidence_import.py`

- [x] Add `GET /api/data-sync/imports/limit-up-evidence/status`.
- [x] Add `GET /api/data-sync/imports/limit-up-evidence/template.csv?dataset=events|auction`.
- [x] Add `POST /api/data-sync/imports/limit-up-evidence/tushare` and `/csv` with validated bounded inputs.
- [x] Test success, unavailable token, invalid dataset/range and structured failures.

### Task 5: Add the product interface

**Files:**
- Modify: `frontend/src/api/dataSync.ts`
- Create: `frontend/src/features/limitUp/LimitUpEvidenceBackfillPanel.tsx`
- Create: `frontend/src/features/limitUp/LimitUpEvidenceBackfillPanel.spec.tsx`
- Modify: `frontend/src/pages/DataManagementPage.tsx`

- [x] Add typed status/import contracts and fetchers.
- [x] Add a “打板证据” data-management tab with dataset, date range, max dates and dry-run controls.
- [x] Add local CSV selection, template download, explicit write confirmation and result/audit rendering.
- [x] Keep the layout dense, use local table scrolling and verify `390x844` without page overflow.

### Task 6: Verify and record durable facts

**Files:**
- Modify: `memory/03_data/data_flow.md`
- Modify: `memory/05_runtime/run_debug.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] Run focused and full limit-up/data-sync backend tests.
- [x] Run frontend tests, production build, Python compile and `git diff --check`.
- [x] Rebuild API/Web, call authenticated real endpoints, and verify token-unavailable plus CSV-dry-run states.
- [x] Verify `/data` and `/limit-up` on desktop/mobile with zero console/network errors.
- [x] Record that Tushare is optional and currently unconfigured; never claim imported data or relaxed gates without real rows.
