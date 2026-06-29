# Mainline Relation Drilldown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/mainline` sector relations more explainable and clickable, so related sectors can be inspected through funds, constituents, and stock detail.

**Architecture:** Keep the feature inside the existing mainline replay flow. The backend relation endpoint will broaden candidates, compute complete-membership overlap, classify relation groups, and return evidence. The frontend will reuse the current selected-sector panel instead of adding a new page.

**Tech Stack:** FastAPI, SQLAlchemy Core, pytest, React, TanStack Query, Vite.

---

### Task 1: Relation Algorithm Evidence

**Files:**
- Modify: `alphaagent/server/services/mainline_replay.py`
- Modify: `tests/alphaagent/test_mainline_replay_algo.py`

- [ ] Add tests for complete Jaccard overlap and zero-overlap co-movement candidates.
- [ ] Update `compute_relations_aligned` to accept complete candidate membership sets and return `relation_group`, `evidence`, and `common_points`.
- [ ] Run `uv run pytest tests/alphaagent/test_mainline_replay_algo.py -q`.

### Task 2: Relation API Candidate Loading

**Files:**
- Modify: `alphaagent/server/api/mainline_replay.py`
- Modify: `tests/alphaagent/test_mainline_replay_api.py`

- [ ] Broaden relation candidates from overlap-only to recent scored sectors plus overlap candidates.
- [ ] Load complete membership sets for target and candidates.
- [ ] Add sector category classification for industry/theme/status grouping.
- [ ] Run `uv run pytest tests/alphaagent/test_mainline_replay_api.py -q`.

### Task 3: Frontend Drilldown

**Files:**
- Modify: `frontend/src/api/mainlineReplay.ts`
- Modify: `frontend/src/features/replay/RelationPanel.tsx`
- Modify: `frontend/src/pages/MainlineReplayPage.tsx`

- [ ] Add relation item fields to TypeScript types.
- [ ] Make related sectors clickable and call back into the page to select that sector.
- [ ] Keep the selected related sector visible even when it is not in the top ranking list.
- [ ] Run `cd frontend && npm run build`.

### Task 4: Accuracy Smoke Test

**Files:**
- Modify: `memory/03_data/data_flow.md` if durable algorithm facts changed.

- [ ] Query local `/api/mainline-replay/relation` samples for `BK1431`, `BK1050`, and `BK1051`.
- [ ] Confirm industry/theme results are ranked separately from status/style results.
- [ ] Run combined backend tests used by mainline replay.
