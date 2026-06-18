# Tail Sync And Quant Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or equivalent task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the data page expose one simple tail-session preparation workflow while the backend schedules fast 14:00 key-data sync and 14:30 quant research.

**Architecture:** Keep historical backtests on complete `stock_daily_bars`. Add a separate tail workflow layer that prepares intraday data and triggers quant research without exposing job-level configuration to ordinary users. The first implementation keeps today's live-candidate scoring as a documented next step; it wires the automated sync/research flow and simplifies UI around the existing data sources.

**Tech Stack:** FastAPI service layer, PostgreSQL-backed sync schedules, React/Vite/TanStack Query frontend, pytest.

---

## File Structure

- Modify `alphaagent/server/services/data_sync.py`
  - Rename/default the 14:00 batch to tail preparation.
  - Add a 14:30 quant research schedule concept and scheduler support for non-sync actions.
  - Keep 18:00 full EOD data completion.
- Modify `alphaagent/server/api/data_sync.py`
  - Expose a simple tail-workflow status endpoint and a "run tail preparation now" endpoint if needed.
- Modify `frontend/src/api/dataSync.ts`
  - Add types and client methods for tail workflow status/actions.
- Modify `frontend/src/pages/DataManagementPage.tsx`
  - Default to a compact "尾盘准备" view.
  - Move job list, schedule CRUD, and minute-gap settings behind an advanced disclosure.
- Modify `tests/alphaagent/test_data_sync.py` or add focused tests if existing file is absent.
  - Verify default schedule seeding, tail workflow status shape, and scheduler action dispatch.
- Modify `memory/09_decisions/decisions.md`
  - Record product rule: ordinary data UI shows tail workflow, advanced config is hidden by default.

## Tasks

### Task 1: Backend Tail Schedule Semantics

- [x] Add/adjust default schedules:
  - `tail_prepare_14h`: 14:00 fast key-data sync.
  - `tail_quant_1430`: 14:30 quant research trigger.
  - `eod_18h`: 18:00 complete data sync.
- [x] Scheduler should dispatch sync schedules through `start_sync_batch`.
- [x] Scheduler should dispatch quant schedules through `research_jobs.start_research_run`.
- [x] Do not write intraday data into `stock_daily_bars`.

### Task 2: Tail Workflow API

- [x] Add a status response that reports:
  - latest complete daily bar date.
  - latest stock snapshot update.
  - latest minute update.
  - latest candidate date.
  - latest research run state.
  - whether the system is ready for tail candidate generation.
- [x] Add a single manual action endpoint for "run tail preparation now" that starts the tail sync batch.

### Task 3: Frontend Simplification

- [x] Make `数据管理` default to tail preparation.
- [x] Show only:
  - tail sync status.
  - daily bar latest date.
  - intraday snapshot latest time.
  - candidate latest date.
  - automatic schedule state.
  - buttons: `立即尾盘准备`, `刷新状态`.
- [x] Move existing schedules, jobs, minute settings, and run history into `高级同步`.

### Task 4: Verification

- [x] Run backend tests for data sync and quant backtest modules.
- [x] Run frontend build.
- [ ] Rebuild API container.
- [ ] Browser-check `/data` or `/data-management` page for the simplified tail workflow.
- [ ] Confirm `/quant` still shows existing candidate/backtest data.

## Scope Guard

This plan does not complete the separate "history + current price live candidate" scoring engine. It prepares the product workflow and schedule shape needed for it, while preserving the current truthful behavior that ordinary historical quant research uses complete daily bars only.
