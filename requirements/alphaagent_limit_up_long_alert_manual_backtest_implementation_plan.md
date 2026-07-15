# Long Buy Alert And Manual Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the short buy alert with a non-overlapping four-second ringtone and let users rebuild the current limit-up history/backtest from the production page.

**Architecture:** Move Web Audio scheduling into a focused module with a pure, testable tone pattern. Reuse the existing asynchronous history rebuild/status endpoints from a React Query mutation and poll, then invalidate every limit-up report query after completion.

**Tech Stack:** React 18, TypeScript, TanStack Query, Web Audio API, Vitest, FastAPI, Docker Compose.

---

### Task 1: Test And Build The Long Ringtone

**Files:**
- Create: `frontend/src/features/limitUp/buyAlertSound.ts`
- Create: `frontend/src/features/limitUp/buyAlertSound.spec.ts`

- [x] **Step 1: Write the failing ringtone pattern test**

Define assertions that the declared duration is at least four seconds, at least five double-tone rounds exist, every tone ends inside the duration, and offsets are ordered.

```ts
expect(BUY_ALERT_RINGTONE_DURATION_SECONDS).toBeGreaterThanOrEqual(4);
expect(BUY_ALERT_RINGTONE_PATTERN).toHaveLength(12);
expect(BUY_ALERT_RINGTONE_PATTERN.every(
  (tone) => tone.offset + tone.duration <= BUY_ALERT_RINGTONE_DURATION_SECONDS,
)).toBe(true);
```

- [x] **Step 2: Run the test and verify it fails**

Run: `pnpm --dir frontend test -- buyAlertSound.spec.ts`

Expected: FAIL because `buyAlertSound.ts` does not exist.

- [x] **Step 3: Implement the ringtone module**

Export a four-second schedule, `unlockBuyAlertAudio()`, and `playBuyAlertSound()`. Use six repeated 880/1175 Hz double tones with exponential decay. Keep one module-level `AudioContext` and one `playingUntil` guard so repeated clicks and simultaneous signals cannot overlap.

```ts
export const BUY_ALERT_RINGTONE_DURATION_SECONDS = 4.05;
export const BUY_ALERT_RINGTONE_PATTERN = Array.from({ length: 6 }, (_, round) => [
  { frequency: 880, offset: round * 0.68, duration: 0.18 },
  { frequency: 1_175, offset: round * 0.68 + 0.2, duration: 0.28 },
]).flat();
```

When `context.currentTime < playingUntil`, return without scheduling another ringtone. Each tone ramps from `0.0001` to a restrained peak and back to `0.0001`.

- [x] **Step 4: Run the ringtone test**

Run: `pnpm --dir frontend test -- buyAlertSound.spec.ts`

Expected: PASS.

### Task 2: Route Real And Test Alerts Through The Ringtone

**Files:**
- Modify: `frontend/src/features/limitUp/useBuyAlerts.ts`
- Test: `frontend/src/features/limitUp/buyAlert.spec.ts`

- [x] **Step 1: Replace local audio helpers with the shared module**

Import `playBuyAlertSound` and `unlockBuyAlertAudio` from `buyAlertSound.ts`. Keep real alerts and the manual speaker test calling the same `playBuyAlertSound()` function, and delete the old 0.3-second oscillator implementation from the Hook.

- [x] **Step 2: Run alert tests and TypeScript build**

Run: `pnpm --dir frontend test -- buyAlert.spec.ts buyAlertSound.spec.ts`

Expected: PASS.

Run: `pnpm --dir frontend run build`

Expected: PASS with no TypeScript errors.

### Task 3: Add Typed History Rebuild API Calls

**Files:**
- Modify: `frontend/src/api/limitUp.ts`

- [x] **Step 1: Add the rebuild status contract**

Define `LimitUpHistoryRebuildStatus` with `status`, `strategy_version`, optional timestamps, optional structured error, optional `already_running`, and optional coverage.

- [x] **Step 2: Add status and start functions**

```ts
export function fetchLimitUpHistoryStatus(): Promise<LimitUpHistoryRebuildStatus> {
  return apiClient.get<LimitUpHistoryRebuildStatus>("/limit-up/history/status");
}

export async function startLimitUpHistoryRebuild(): Promise<LimitUpHistoryRebuildStatus> {
  try {
    return await apiClient.post<LimitUpHistoryRebuildStatus>("/limit-up/history/rebuild");
  } catch (error) {
    if (error instanceof ApiClientError && error.code === "HISTORY_REBUILD_RUNNING") {
      return fetchLimitUpHistoryStatus();
    }
    throw error;
  }
}
```

This converts the existing 409 into an attach-to-running-task result by re-reading authoritative status while preserving all other errors.

- [x] **Step 3: Run the frontend build**

Run: `pnpm --dir frontend run build`

Expected: PASS.

### Task 4: Add The Production Rebuild Control

**Files:**
- Create: `frontend/src/features/limitUp/BacktestRebuildControl.tsx`
- Create: `frontend/src/features/limitUp/BacktestRebuildControl.spec.tsx`
- Modify: `frontend/src/pages/LimitUpPage.tsx`

- [x] **Step 1: Write the control rendering test**

Use `renderToStaticMarkup` to verify idle state displays “重新计算”, building state displays “计算中” and disables the button, and building state explains that the old result remains visible during calculation.

- [x] **Step 2: Run the control test and verify it fails**

Run: `pnpm --dir frontend test -- BacktestRebuildControl.spec.tsx`

Expected: FAIL because the component does not exist.

- [x] **Step 3: Implement the compact control**

Render an icon-and-text button using `RefreshCw`. Do not add a new card or parameter panel. During rebuild, animate the icon and show one inline status sentence.

- [x] **Step 4: Wire mutation, polling, and cache invalidation**

In `LimitUpPage`, query history status while the backtest view is open and poll every two seconds only while `status === "building"`. Start the mutation from the control. On a `building -> ready` transition, invalidate these prefixes:

```ts
["limitUpHistoryDates"]
["limitUpScheduledLedger"]
["limitUpLaneBacktest"]
```

Show a success toast after invalidation. On `failed`, keep the prior report and show the structured server error. Opening the page while a rebuild is already running must immediately restore the running UI.

- [x] **Step 5: Run focused tests and the production build**

Run: `pnpm --dir frontend test -- BacktestRebuildControl.spec.tsx buyAlertSound.spec.ts buyAlert.spec.ts`

Expected: PASS.

Run: `pnpm --dir frontend run build`

Expected: PASS.

### Task 5: Verify, Deploy, Remember, And Release

**Files:**
- Modify: `memory/09_decisions/decisions.md`
- Modify: `requirements/alphaagent_limit_up_buy_alert_design.md`
- Create: `requirements/alphaagent_limit_up_manual_backtest_refresh_design.md`

- [x] **Step 1: Run the full regression suite required by the change**

Run: `pnpm --dir frontend test`

Expected: all frontend tests pass.

Run: `uv run --group server pytest tests/alphaagent/test_limit_up_lanes.py -q`

Expected: all targeted backend tests pass.

Run: `git diff --check`

Expected: no whitespace errors.

- [x] **Step 2: Rebuild the local web service**

Run: `docker compose up -d --build alphaagent-web`

Expected: web container starts successfully and `http://localhost:8080/limit-up` returns 200 through the gateway.

- [x] **Step 3: Verify in a browser**

Use Playwright at desktop and mobile widths. Enable alerts and click the speaker control, verify the four-second sound scheduling causes no console error, then open 回测 and click “重新计算”. Verify it becomes “计算中”, a second click is impossible, the page remains readable, and status polling is visible in network traffic.

- [x] **Step 4: Update durable memory**

Record that “继续” means complete the confirmed scope through implementation, tests, deployment/release, and verification without repeated approval gates, except for irreversible actions or missing authority. Record the long ringtone and manual full-history rebuild behavior in the current `/limit-up` product state.

- [x] **Step 5: Commit and publish the next patch release**

Stage only the related files, commit with `feat(limit-up): add durable alerts and manual backtest rebuild`, tag the next patch version, push the commit and tag, and verify all Docker Release jobs complete successfully.
