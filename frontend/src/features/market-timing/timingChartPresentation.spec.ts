import { describe, expect, it } from "vitest";
import type { TimingBar, TimingDailyState } from "@/api/marketTiming";
import {
  buildTimingHoverSummaries,
  formatTimingAxisTick,
  formatTimingCrosshairDate,
  timingActiveLabel,
  timingConfirmationLabels,
  timingZoneLabel,
} from "./timingChartPresentation";

const bars: TimingBar[] = [
  { date: "2026-06-30", open: 100, high: 102, low: 99, close: 100, volume: 1, turnover: 1 },
  { date: "2026-07-01", open: 100, high: 104, low: 99, close: 102, volume: 1, turnover: 1 },
  { date: "2026-07-02", open: 102, high: 103, low: 98, close: 99, volume: 1, turnover: 1 },
  { date: "2026-07-03", open: 99, high: 101, low: 98, close: 100, volume: 1, turnover: 1 },
];

const series: TimingDailyState[] = [
  {
    date: "2026-07-01",
    bull_force: 67.0164,
    bear_force: 43.9,
    active_direction: "GOLD",
    zone_direction: "GOLD",
    danger_state: "NORMAL",
    phase: "retreat",
    event: {
      direction: "GOLD",
      status: "INVALIDATED",
      grade: "MEDIUM",
      setup_type: "TREND_GOLD",
      confirm_date: "2026-07-02",
    },
  },
  {
    date: "2026-07-02",
    bull_force: 53.6375,
    bear_force: 55.4,
    active_direction: "GOLD",
    zone_direction: "NEUTRAL",
    danger_state: "NORMAL",
    phase: "retreat",
    event: null,
  },
];

describe("market timing chart presentation", () => {
  it("keeps July 2 neutral while exposing the rejected July 1 gold candidate", () => {
    const summary = buildTimingHoverSummaries(bars, series).get("2026-07-02");

    expect(summary?.date).toBe("2026-07-02");
    expect(summary?.changePct).toBeCloseTo(-2.9412, 4);
    expect(timingZoneLabel(summary?.state ?? null)).toBe("中性");
    expect(timingActiveLabel(summary?.state ?? null)).toBe("金未反转");
    expect(timingConfirmationLabels(summary?.confirmations ?? [])).toEqual([
      "7月1日金候选已否决",
    ]);
  });

  it("does not carry stale factors onto a newer quote bar", () => {
    const summary = buildTimingHoverSummaries(bars, series).get("2026-07-03");

    expect(summary?.state).toBeNull();
    expect(timingZoneLabel(summary?.state ?? null)).toBe("因子未就绪");
    expect(timingActiveLabel(summary?.state ?? null)).toBe("因子未就绪");
  });

  it("formats crosshair and axis dates without English month names", () => {
    expect(formatTimingCrosshairDate("2026-07-02")).toBe("2026-07-02");
    expect(formatTimingCrosshairDate({ year: 2026, month: 7, day: 2 })).toBe("2026-07-02");
    expect(formatTimingAxisTick("2026-07-02")).toBe("07-02");
  });
});
