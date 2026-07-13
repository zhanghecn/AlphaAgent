# Low First-Board Sector Warmup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. This repository forbids commits unless the user explicitly requests one, so verification checkpoints replace commit steps.

**Goal:** Add a research-only sector warmup layer for low first boards, expose an auditable historical proxy comparison and live shadow labels, and prove whether it improves the existing backtest without changing relay-board decisions.

**Architecture:** Keep warmup calculations in a pure limit-up domain module. Build the historical comparison from the persisted `limit-up-history-v11` candidate pool, expose it through a cached service/API endpoint, and render it only in the first-board backtest. Live scans attach shadow-only concept-group observations and dynamic group-leader ranks; `action`, lane blockers, and portfolio selection remain unchanged.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy/PostgreSQL, pytest, React 18, TypeScript, TanStack Query, Vitest, Docker Compose.

---

### Task 1: Pure Warmup Domain Rules

**Files:**
- Create: `alphaagent/server/services/limit_up/sector_warmup.py`
- Create: `tests/alphaagent/test_limit_up_sector_warmup.py`

- [ ] **Step 1: Write failing grouping and state tests**

Cover deterministic overlap grouping, style-sector exclusion, single counting of members, stable group IDs, proxy confirmation, live state classification, and lane isolation. Fixtures must prove that only `first_board` receives shadow fields.

- [ ] **Step 2: Run the focused test and confirm failure**

Run:

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_sector_warmup.py -q
```

Expected: import failure for `sector_warmup`.

- [ ] **Step 3: Implement pure functions**

Implement these public functions and immutable constants:

```python
def group_concepts(memberships: Sequence[Mapping[str, object]]) -> list[dict[str, object]]: ...
def historical_warmup_proxy(candidate: Mapping[str, object]) -> dict[str, object]: ...
def live_warmup_observation(contexts: Sequence[Mapping[str, object]]) -> dict[str, object]: ...
def attach_dynamic_group_leader_ranks(candidates: Sequence[Mapping[str, object]]) -> list[dict[str, object]]: ...
```

Grouping uses concept/theme memberships, at least five shared stocks, Jaccard at least 0.35, and smaller-set coverage at least 0.70. Live state is always marked `research_only`; missing evidence returns `unavailable` rather than guessing.

- [ ] **Step 4: Run the focused test**

Expected: all domain tests pass.

### Task 2: Historical Proxy Research Report

**Files:**
- Create: `alphaagent/server/services/limit_up/sector_warmup_research.py`
- Modify: `tests/alphaagent/test_limit_up_sector_warmup.py`

- [ ] **Step 1: Add failing report tests**

Use synthetic daily candidate pools to verify four variants:

```text
baseline
warmup_rank
warmup_gate
warmup_leader_proxy
```

The report must use eligible first-board candidates only, D+1 open return minus 0.31% cost, one candidate per trading day, 100,000 initial cash, calendar-day compounding, drawdown, phase summaries, coverage, and explicit non-formal status for the leader proxy.

- [ ] **Step 2: Implement report construction**

Implement:

```python
def build_sector_warmup_research_report(
    rows: Sequence[Mapping[str, object]],
    *,
    start: date | None = None,
    end: date | None = None,
    data_coverage: Mapping[str, object] | None = None,
) -> dict[str, object]: ...
```

Return comparison rows, phase rows, selected trade details, acceptance checks, lane-isolation evidence, limitations, and `simulation_eligible=False` while point-in-time concept coverage is incomplete.

- [ ] **Step 3: Run focused tests**

Expected: deterministic metrics and no mutation of input replay rows.

### Task 3: Repository, Cache, and API

**Files:**
- Modify: `alphaagent/server/services/limit_up/history_service.py`
- Modify: `alphaagent/server/api/limit_up.py`
- Modify: `tests/alphaagent/test_limit_up_history.py`

- [ ] **Step 1: Add failing service/API tests**

Test date validation, cached report loading, data coverage fields, and the route:

```http
GET /api/limit-up/history/sector-warmup?start=YYYY-MM-DD&end=YYYY-MM-DD
```

- [ ] **Step 2: Add service wrapper and coverage query**

The wrapper loads full replay payloads, calls the pure report builder, and reports counts/date ranges for concept bars, period scores, fund flows, fund-flow snapshots, membership snapshots, and relation edges. Cache by strategy version and date range.

- [ ] **Step 3: Add API endpoint**

Use the existing `ok`/`fail` envelope and the same invalid-range/database-unavailable behavior as other history endpoints.

- [ ] **Step 4: Run API and history tests**

Expected: endpoint contract passes without changing existing backtest responses.

### Task 4: Live Shadow Observation

**Files:**
- Modify: `alphaagent/server/services/limit_up/live_repository.py`
- Modify: `alphaagent/server/services/limit_up/live_service.py`
- Modify: `alphaagent/server/services/limit_up/live_policy.py`
- Modify: `tests/alphaagent/test_limit_up_live.py`
- Modify: `tests/alphaagent/test_limit_up_lanes.py`

- [ ] **Step 1: Add failing shadow-only tests**

Verify that first-board candidates receive `warmup_group`, `warmup_state`, `warmup_score`, `warmup_confidence`, and `warmup_leader_rank`; relay lanes retain byte-for-byte equivalent decisions and ranks; stale or partial data never upgrades an action.

- [ ] **Step 2: Preserve all candidate concept contexts**

Extend `load_live_context()` to retain usable concept/theme memberships and their latest heat/flow evidence while preserving the existing best-membership fields for compatibility.

- [ ] **Step 3: Attach live research observations**

After candidate enrichment, call the pure warmup functions and assign dynamic leader ranks within each warmup group. Do not add warmup values to `_leadership_score`, lane rank, market gate, or portfolio selection.

- [ ] **Step 4: Serialize shadow fields**

Expose the fields from `_signal()` only for `board_lane == "first_board"`; set `warmup_execution_effect="none_research_only"`.

- [ ] **Step 5: Run live/lane regression tests**

Expected: existing recommendations are unchanged apart from additive first-board evidence fields.

### Task 5: First-Board Backtest UI

**Files:**
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Create: `frontend/src/features/limitUp/SectorWarmupResearchPanel.tsx`
- Create: `frontend/src/features/limitUp/SectorWarmupResearchPanel.spec.tsx`

- [ ] **Step 1: Add API types and query function**

Define typed comparison/coverage/check objects and:

```typescript
fetchLimitUpSectorWarmupResearch({ start, end })
```

- [ ] **Step 2: Add failing panel tests**

Verify compact rendering of baseline versus three warmup variants, 10 万期末资金, win rate, mean return, compounding, drawdown, trade count, data warning, and research-only status.

- [ ] **Step 3: Implement the compact panel**

Use one unframed comparison band with a responsive table. Avoid nested cards, settings, and strategy switches. Highlight deltas but never label the result as validated when acceptance checks fail.

- [ ] **Step 4: Integrate only into first-board backtest**

Fetch the report only when the backtest view and `first_board` scope are active. Place it above the existing validation/equity sections. Other scopes make no request and show no warmup controls.

- [ ] **Step 5: Show live shadow tag**

For first-board rows only, render a compact line such as `板块预热研究：升温 68 · 动态龙1`; state clearly that it does not change the buy action.

- [ ] **Step 6: Run frontend tests and build**

```bash
pnpm --dir frontend test -- --run
pnpm --dir frontend run build
```

Expected: tests and TypeScript build pass.

### Task 6: Real Historical Backtest and Evidence

**Files:**
- Create: `memory/06_backtests/limit_up_sector_warmup_first_board.md`
- Modify: `memory/06_backtests/README.md`
- Modify: `memory/09_decisions/decisions.md`

- [ ] **Step 1: Run the report against the current PostgreSQL ledger**

Use the new service with all 600 replay dates and record the actual eligible event range, trade counts, phase results, acceptance checks, and 100,000-equity outcomes.

- [ ] **Step 2: Validate relay-board isolation**

Run existing lane backtests before and after the change and compare one-to-two, two-to-three, and high-board summaries. Differences are a release blocker.

- [ ] **Step 3: Record durable evidence**

Keep detailed tables in the dedicated backtest artifact. Update overview memory only with the current conclusion, verification command, evidence link, and unresolved point-in-time coverage gap.

### Task 7: Full Verification and Product Check

**Files:**
- No additional source files expected.

- [ ] **Step 1: Run focused backend tests**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_sector_warmup.py tests/alphaagent/test_limit_up_history.py tests/alphaagent/test_limit_up_live.py tests/alphaagent/test_limit_up_lanes.py -q
```

- [ ] **Step 2: Run the complete limit-up suite**

```bash
uv run --group server pytest tests/alphaagent/test_limit_up_*.py -q
```

- [ ] **Step 3: Rebuild API and web containers**

```bash
docker compose up -d --build alphaagent-api alphaagent-web
```

- [ ] **Step 4: Verify APIs and browser**

Check `/limit-up` on desktop and mobile, confirm the first-board research comparison is visible, live rows remain compact, no text overlaps, console has no errors, and non-first-board tabs contain no warmup promotion.

- [ ] **Step 5: Inspect final diff and status**

Run `git diff --check`, list only task-owned files, and leave all unrelated dirty worktree changes intact. Do not commit without an explicit user request.

### Task 8: Post-Holdout Warmup Quality Gate

**Files:**
- Modify: `alphaagent/server/services/limit_up/sector_warmup.py`
- Modify: `alphaagent/server/services/limit_up/sector_warmup_research.py`
- Modify: `tests/alphaagent/test_limit_up_sector_warmup.py`
- Modify: `frontend/src/api/limitUp.ts`
- Modify: `frontend/src/features/limitUp/SectorWarmupResearchPanel.tsx`
- Modify: `frontend/src/features/limitUp/SectorWarmupResearchPanel.spec.tsx`
- Modify: `memory/06_backtests/limit_up_sector_warmup_first_board.md`
- Modify: `memory/06_backtests/README.md`

- [x] **Step 1: Add failing pure-rule and report tests**

Prove that `warmup_quality_gate` requires confirmed warmup, a score below 70 and
`prior_industry_sealed_count > 0`; missing fields and each failed rule must return a
stable rejection code. Prove that the variant is distinct, research-only and cannot
make `simulation_eligible` true from old holdout results.

- [x] **Step 2: Add failing loss and missed-winner diagnostic tests**

Build a locked-holdout fixture containing a failed-board loss, a crowded loss, a
profitable baseline skipped by the original gate and a non-profitable skip. Assert
that only the intended trades appear and all explanations use signal-time fields.

- [x] **Step 3: Implement the frozen quality gate and report contract**

Add the fifth comparison variant, phase summaries, selected trades, a separate
`quality_gate_validation` object and bounded diagnostic lists. Keep the existing
acceptance target as `warmup_gate`; quality rejection leaves that date empty instead
of backfilling a lower-ranked candidate. Never read outcome fields when selecting or
explaining a gate decision.

- [x] **Step 4: Render the hypothesis and individual diagnostics**

Extend the typed API contract and show the quality-gate row, its post-holdout warning,
forward sample count, original-gate losses and top missed winners in the existing
unframed panel. Do not add controls or alter live recommendations.

- [x] **Step 5: Recompute evidence and run regression checks**

Run the focused backend and frontend tests, all limit-up tests, frontend build and
`git diff --check`. Recompute the PostgreSQL report and record full/OOS/holdout/forward
metrics without relabeling the old holdout as new validation.
