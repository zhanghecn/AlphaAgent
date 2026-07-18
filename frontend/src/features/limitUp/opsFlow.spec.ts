import { describe, expect, it } from "vitest";

import type { LimitUpSignalSnapshot } from "@/api/limitUp";
import { buildOpsPhases } from "./opsFlow";

function snapshot(overrides: Partial<LimitUpSignalSnapshot> = {}): LimitUpSignalSnapshot {
  return {
    trade_date: "2026-07-18",
    captured_at: "2026-07-18T10:05:00+08:00",
    source: "test",
    mode: "live_snapshot",
    session_stage: "morning",
    market_context: {},
    recommendations: {
      market_gate: { passed: true, reasons: [] },
      lanes: { now: [], tail: [], next_auction: [] },
      execution_schedule: {
        entry_windows: ["09:35-10:30", "13:05-14:45"],
        exit_time: "15:00",
      },
    },
    data_quality: { status: "ready", is_stale: false },
    ...overrides,
  } as LimitUpSignalSnapshot;
}

describe("ops flow phases", () => {
  it("marks the morning window active during morning session", () => {
    const phases = buildOpsPhases(snapshot());
    expect(phases.map((phase) => phase.state)).toEqual([
      "done",
      "active",
      "next",
      "pending",
      "pending",
    ]);
  });

  it("uses the real execution windows as time labels", () => {
    const phases = buildOpsPhases(snapshot());
    expect(phases.map((phase) => phase.timeLabel)).toEqual([
      "09:15-09:30",
      "09:35-10:30",
      "11:30-13:00",
      "13:05-14:45",
      "D+1 15:00",
    ]);
  });

  it("falls back to official session times without a schedule", () => {
    const base = snapshot();
    const phases = buildOpsPhases({
      ...base,
      recommendations: { ...base.recommendations, execution_schedule: undefined },
    });
    expect(phases[1].timeLabel).toBe("09:30-11:30");
    expect(phases[3].timeLabel).toBe("13:00-15:00");
  });

  it("treats lunch break as its own active phase", () => {
    const phases = buildOpsPhases(snapshot({ session_stage: "lunch" }));
    expect(phases[2].state).toBe("active");
    expect(phases[3].state).toBe("next");
  });

  it("maps tail and close auction into the afternoon window", () => {
    for (const stage of ["afternoon", "tail", "close_auction"]) {
      const phases = buildOpsPhases(snapshot({ session_stage: stage }));
      expect(phases[3].state).toBe("active");
    }
  });

  it("points to the D+1 exit after close", () => {
    const phases = buildOpsPhases(snapshot({ session_stage: "closed" }));
    expect(phases.map((phase) => phase.state)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "next",
    ]);
  });

  it("starts from preopen for a next-session plan", () => {
    const phases = buildOpsPhases(
      snapshot({ mode: "next_session_final", session_stage: "closed" }),
    );
    expect(phases[0].state).toBe("active");
    expect(phases[1].state).toBe("next");
  });

  it("flags both entry windows as action phases", () => {
    const phases = buildOpsPhases(snapshot());
    expect(phases.map((phase) => phase.entryWindow)).toEqual([
      false,
      true,
      false,
      true,
      false,
    ]);
  });
});
