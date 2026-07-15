import { describe, expect, it } from "vitest";

import type { TimingDailyState, TimingSignal } from "@/api/marketTiming";
import {
  recentTimingRows,
  summarizeTimingEvents,
  timingSetupLabel,
  visibleChartSignals,
} from "./timingPresentation";

function signal(
  direction: TimingSignal["direction"],
  status: TimingSignal["status"],
): TimingSignal {
  return {
    date: "2026-07-07",
    direction,
    status,
    grade: "WEAK",
    setup_type: direction === "GOLD" ? "TREND_GOLD" : "TOP_SILVER",
    confirm_date: status === "PENDING" ? null : "2026-07-08",
    bull_force: direction === "GOLD" ? 70 : 40,
    bear_force: direction === "SILVER" ? 70 : 40,
    phase: "retreat",
    reasons: [],
  };
}

describe("market timing presentation", () => {
  it("separates formal gold and silver events from candidates", () => {
    const summary = summarizeTimingEvents([
      signal("GOLD", "CONFIRMED"),
      signal("SILVER", "CONFIRMED"),
      signal("SILVER", "CONFIRMED"),
      signal("GOLD", "INVALIDATED"),
      signal("SILVER", "PENDING"),
    ]);

    expect(summary).toEqual({
      confirmed: { gold: 1, silver: 2 },
      invalidated: 1,
      pending: 1,
    });
  });

  it("keeps the latest dates and confirmation details in chronological order", () => {
    const rows = Array.from({ length: 24 }, (_, index) => ({
      date: `2026-07-${String(index + 1).padStart(2, "0")}`,
      bull_force: 50 + index,
      bear_force: 50 - index,
      active_direction: index < 12 ? "GOLD" : "SILVER",
      zone_direction: "NEUTRAL",
      danger_state: index === 23 ? "DANGER" : "NORMAL",
      phase: "rotation",
      event:
        index === 23
          ? {
              direction: "SILVER",
              status: "CONFIRMED",
              grade: "WEAK",
              setup_type: "TOP_SILVER",
              confirm_date: "2026-07-25",
            }
          : null,
    })) as TimingDailyState[];

    const recent = recentTimingRows(rows, 20);

    expect(recent[0].date).toBe("2026-07-05");
    expect(recent[recent.length - 1]?.date).toBe("2026-07-24");
    expect(recent[recent.length - 1]?.event?.confirm_date).toBe("2026-07-25");
    expect(recent[recent.length - 1]?.danger_state).toBe("DANGER");
  });

  it("keeps rejected candidates out of the primary chart", () => {
    const confirmed = signal("GOLD", "CONFIRMED");
    const invalidated = signal("SILVER", "INVALIDATED");
    const pending = signal("SILVER", "PENDING");

    expect(visibleChartSignals([confirmed, invalidated, pending])).toEqual([
      confirmed,
      pending,
    ]);
  });

  it("names the internal setup without changing the public direction", () => {
    expect(timingSetupLabel("REVERSAL_GOLD")).toBe("弱势衰竭反转金手指");
    expect(timingSetupLabel("BREAKDOWN_SILVER")).toBe("趋势破位银手指");
    expect(timingSetupLabel("STRUCTURAL_BREAKDOWN_SILVER")).toBe("结构性破位银手指");
  });
});
