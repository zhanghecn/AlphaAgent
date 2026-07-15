# Current Market-Timing Signal Presentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent a stale historical gold or silver event from appearing as the current `/market` signal.

**Architecture:** Keep the market-timing API and algorithms unchanged. Make `TimingHero` render only `overview.current_direction`; history remains owned by the chart and date table, while a neutral latest day gets an explicit no-signal status.

**Tech Stack:** React 18, TypeScript, Vitest with server-side rendering, Vite, Docker Compose.

---

### Task 1: Add current-versus-history presentation tests

**Files:**
- Create: `frontend/src/features/market-timing/TimingHero.spec.tsx`
- Test: `frontend/src/features/market-timing/TimingHero.tsx`

- [x] **Step 1: Create a complete overview fixture**

```tsx
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { TimingDirection, TimingOverview } from "@/api/marketTiming";
import { TimingHero } from "./TimingHero";

function overview(currentDirection: TimingDirection): TimingOverview {
  return {
    latest_date: "2026-07-15",
    factor_date: "2026-07-15",
    quote_date: "2026-07-15",
    current_direction: currentDirection,
    danger_state: "NORMAL",
    phase: "retreat",
    phase_label: "退潮",
    bull_force: 46.2,
    bear_force: 53.9,
    factors: {
      trend: 54.8,
      momentum: 33.6,
      breadth: 50,
      structure: 43.9,
      volume: 50,
    },
    top_factors: {},
    index_close: 3958.21,
    index_change_pct: -0.22,
    latest_signal: {
      direction: "GOLD",
      status: "CONFIRMED",
      grade: "WEAK",
      setup_type: "REVERSAL_GOLD",
      date: "2026-06-11",
      confirm_date: "2026-06-12",
      bull_force: 39.5,
      bear_force: 61.7,
    },
  };
}
```

- [x] **Step 2: Assert that neutral does not render the stale gold event**

```tsx
it("shows no current signal instead of a stale historical gold event", () => {
  const html = renderToStaticMarkup(
    <TimingHero overview={overview("NEUTRAL")} loading={false} />,
  );

  expect(html).toContain("无信号");
  expect(html).toContain("当前无金银信号");
  expect(html).not.toContain("最近信号");
  expect(html).not.toContain("2026-06-11");
  expect(html).not.toContain("金手指");
  expect(html).not.toContain("银手指区");
});
```

- [x] **Step 3: Assert that genuine current gold and silver still render**

```tsx
it("keeps genuine current gold and silver directions", () => {
  const gold = renderToStaticMarkup(
    <TimingHero overview={overview("GOLD")} loading={false} />,
  );
  const silver = renderToStaticMarkup(
    <TimingHero overview={overview("SILVER")} loading={false} />,
  );

  expect(gold).toContain("金手指");
  expect(silver).toContain("银手指");
  expect(gold).not.toContain("当前无金银信号");
  expect(silver).not.toContain("当前无金银信号");
});
```

- [x] **Step 4: Run the focused test and verify the neutral case fails**

Run:

```bash
pnpm --dir frontend exec vitest run src/features/market-timing/TimingHero.spec.tsx
```

Expected: the neutral case fails because the current component renders “观望”, the historical `2026-06-11` gold event, and “金手指区”.

### Task 2: Make the hero current-state only

**Files:**
- Modify: `frontend/src/features/market-timing/TimingHero.tsx`
- Test: `frontend/src/features/market-timing/TimingHero.spec.tsx`

- [x] **Step 1: Remove historical-event-only helpers and labels**

```tsx
const DIRECTION_LABEL: Record<TimingDirection, string> = {
  GOLD: "金手指",
  SILVER: "银手指",
  NEUTRAL: "无信号",
};
```

Delete `GOLD_DEEP`, `daysAgo`, and `latestSignalDirection`; they become unused when the historical row is removed.

- [x] **Step 2: Make force labels direction-neutral and render the neutral status**

```tsx
<ForceBar label="多头合力 bull" value={overview.bull_force} color={GOLD} />
<ForceBar label="空头合力 bear" value={overview.bear_force} color={SILVER_DEEP} />
{direction === "NEUTRAL" && (
  <p className="text-sm text-muted-foreground">
    当前无金银信号 · 因子截至 {factorDate}
  </p>
)}
```

Delete the complete `overview.latest_signal` rendering block. Do not change the API type or backend payload.

- [x] **Step 3: Run the focused test**

Run:

```bash
pnpm --dir frontend exec vitest run src/features/market-timing/TimingHero.spec.tsx
```

Expected: both tests pass.

### Task 3: Verify, deploy, and record the result

**Files:**
- Modify: `memory/07_market_timing/market_timing_design.md`
- Modify: `requirements/alphaagent_market_timing_current_signal_presentation_implementation_plan.md`

- [x] **Step 1: Run all frontend tests and the production build**

```bash
pnpm --dir frontend test
pnpm --dir frontend run build
```

Expected: all Vitest tests pass and TypeScript/Vite production build succeeds.

- [x] **Step 2: Rebuild the Web service**

```bash
docker compose up -d --build alphaagent-web
docker compose ps alphaagent-web alphaagent-gateway alphaagent-api
```

Expected: all three services are running and the API/gateway health checks pass.

- [x] **Step 3: Verify the real page at desktop and mobile widths**

Open `http://localhost:8080/market` at `1440x1000` and `390x844`. Assert the current hero contains “无信号” and “当前无金银信号”, does not contain `2026-06-11` or a current “金手指” label, has no horizontal overflow, and produces no browser console errors.

- [x] **Step 4: Update durable memory**

Record that the current hero consumes only `current_direction`; `latest_signal` remains API-compatible historical data and is no longer rendered in the current summary. Add the frontend test/build and browser verification entrypoints.

- [x] **Step 5: Commit only current-signal presentation files**

```bash
git add frontend/src/features/market-timing/TimingHero.tsx \
  frontend/src/features/market-timing/TimingHero.spec.tsx \
  memory/07_market_timing/market_timing_design.md \
  requirements/alphaagent_market_timing_current_signal_presentation_implementation_plan.md
git commit -m "fix(market-timing): stop presenting stale signals as current"
```

Expected: unrelated limit-up changes remain unstaged.
