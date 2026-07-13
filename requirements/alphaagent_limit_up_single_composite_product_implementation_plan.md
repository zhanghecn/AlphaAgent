# Single Composite First-board Product Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/limit-up` expose one user-facing “综合首板” strategy while retaining warmup and rotation research only in the backend.

**Architecture:** Remove the independent warmup research query and panel from the page. Keep the existing `first_board` lane, cash backtest, ranking and actions as the only product result; merge any positive sector research evidence into the existing selection-reason sentence without adding another strategy or status row.

**Tech Stack:** React 18, TypeScript, TanStack Query, Vitest, FastAPI research endpoint retained unchanged.

---

### Task 1: Lock the simplified rendering contract

**Files:**
- Create: `frontend/src/features/limitUp/limitUpPresentation.spec.ts`
- Create: `frontend/src/features/limitUp/limitUpPresentation.ts`

- [x] **Step 1: Add failing presentation tests**

Add tests asserting that `first_board` is labeled `综合首板`, positive warmup/rotation evidence is returned as one concise reason list, and unavailable/rejected shadow evidence is omitted.

```ts
expect(limitUpLaneLabel("first_board")).toBe("综合首板");
expect(firstBoardCompositeReasons({
  board_lane: "first_board",
  warmup_group_name: "创新药",
  warmup_state: "warming",
  warmup_leader_rank: 1,
  rotation_shadow_state: "trigger",
} as LimitUpLiveSignal)).toEqual(["创新药资金预热", "板块扩散龙头确认"]);
expect(firstBoardCompositeReasons({
  board_lane: "first_board",
  rotation_shadow_state: "unavailable",
} as LimitUpLiveSignal)).toEqual([]);
```

- [x] **Step 2: Run the focused test**

Run: `pnpm -C frontend test -- limitUpPresentation.spec.ts`

Expected: FAIL because the composite helpers do not yet exist.

- [x] **Step 3: Implement pure presentation helpers**

Export `limitUpLaneLabel()` and `firstBoardCompositeReasons()` from `limitUpPresentation.ts`. The latter returns at most two internal sector evidence phrases and never changes `action`.

```ts
export function limitUpLaneLabel(lane: BoardLaneKey) {
  return lane === "first_board" ? "综合首板" : RELAY_LABELS[lane];
}

export function firstBoardCompositeReasons(signal: LimitUpLiveSignal) {
  if (signal.board_lane !== "first_board") return [];
  const reasons: string[] = [];
  if (signal.warmup_group_name && ["warming", "launch"].includes(signal.warmup_state ?? "")) {
    reasons.push(`${signal.warmup_group_name}资金预热`);
  }
  if (signal.rotation_shadow_state === "trigger") reasons.push("板块扩散龙头确认");
  return reasons.slice(0, 2);
}
```

- [x] **Step 4: Re-run the focused test**

Run: `pnpm -C frontend test -- limitUpPresentation.spec.ts`

Expected: PASS.

### Task 2: Remove the multi-strategy research surface

**Files:**
- Modify: `frontend/src/pages/LimitUpPage.tsx`
- Delete: `frontend/src/features/limitUp/SectorWarmupResearchPanel.tsx`
- Delete: `frontend/src/features/limitUp/SectorWarmupResearchPanel.spec.tsx`

- [x] **Step 1: Remove the warmup query and panel**

Delete `fetchLimitUpSectorWarmupResearch`, `SectorWarmupResearchPanel`, query state, props and rendering from `LimitUpPage.tsx`. Do not change the backend endpoint or research service.

The page must retain only:

```tsx
<BacktestView
  report={backtestQuery.data}
  loading={backtestQuery.isLoading}
  fetching={backtestQuery.isFetching}
  start={start}
  end={end}
  minimumDate={datesQuery.data?.start}
  maximumDate={datesQuery.data?.end}
  onStart={setStart}
  onEnd={setEnd}
  onRun={() => void backtestQuery.refetch()}
/>
```

- [x] **Step 2: Present only the composite strategy**

Use `综合首板` for first-board tabs and labels. Keep the existing official `LimitUpLaneBacktest` summary, chart and trades as the sole backtest result.

- [x] **Step 3: Merge live evidence into one sentence**

Append `firstBoardCompositeReasons(signal)` to the existing `入选` text and remove the separate “板块预热研究” and “轮动影子” blocks.

```ts
const selectionReasons = [
  ...(signal.selection_reasons?.slice(0, 4).map(factorLabel) ?? []),
  ...firstBoardCompositeReasons(signal),
].slice(0, 5).join(" · ") || factorSummary;
```

- [x] **Step 4: Use one empty-state sentence**

For the first-board scope, render `综合首板暂无买点，保持空仓` when no candidates or trades exist.

```tsx
<EmptyRow text={scope === "first_board" ? "综合首板暂无买点，保持空仓" : defaultText} />
```

### Task 3: Verify behavior and deploy

**Files:**
- Modify: `memory/06_backtests/limit_up_sector_warmup_first_board.md`
- Modify: `memory/09_decisions/decisions.md`

- [x] **Step 1: Run frontend tests and build**

Run: `pnpm -C frontend test`

Expected: all frontend tests pass.

Run: `pnpm -C frontend build`

Expected: TypeScript and Vite production build pass.

- [x] **Step 2: Run backend regression relevant to retained research**

Run: `uv run pytest -q tests/alphaagent/test_limit_up_first_board_dual_lane.py tests/alphaagent/test_limit_up_sector_warmup.py`

Expected: all tests pass, proving hidden research data is still produced.

- [x] **Step 3: Update durable project memory**

Record that warmup/rotation comparisons remain backend-only and the product exposes one composite first-board strategy.

- [x] **Step 4: Build and deploy the web service**

Run: `docker compose up -d --build alphaagent-web`

Expected: API and gateway healthy, web running, `http://localhost:8080/limit-up` returns HTTP 200.

- [x] **Step 5: Browser verification**

At desktop and 390px mobile widths, verify that “回测 -> 综合首板” shows one cash result, realtime rows contain at most one combined reason line, the removed research labels do not appear, and there is no page-level overflow or console error.

No Git commit is included because repository instructions require explicit user authorization.
