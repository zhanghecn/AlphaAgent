import { describe, expect, it } from "vitest";

import type { LowSuctionStrategyOverview } from "@/api/lowSuction";
import { buildLowSuctionPhases } from "./lowSuctionFlow";

function strategyAt(generatedAt: string, status = "awaiting_signal_window"): LowSuctionStrategyOverview {
  return {
    generated_at: generatedAt,
    session: { status },
  } as unknown as LowSuctionStrategyOverview;
}

describe("buildLowSuctionPhases", () => {
  it("renders the six daily nodes with scan schedule labels", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-22T10:35:00+08:00"));
    expect(phases.map((phase) => phase.label)).toEqual([
      "早盘预警",
      "上午跟踪",
      "午间休市",
      "下午跟踪",
      "尾盘确认",
      "纸面买入",
    ]);
    expect(phases.map((phase) => phase.timeLabel)).toEqual([
      "09:30",
      "10:30 · 11:30",
      "11:30-13:00",
      "13:30 · 14:30",
      "14:50",
      "14:55",
    ]);
  });

  it("marks the pre-market morning scan as next", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-22T09:15:00+08:00"));
    expect(phases.map((phase) => phase.state)).toEqual([
      "next",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("activates the morning tracking window after the first scan", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-22T10:35:00+08:00"));
    expect(phases.map((phase) => phase.state)).toEqual([
      "done",
      "active",
      "next",
      "pending",
      "pending",
      "pending",
    ]);
  });

  it("marks lunch break as the active amber node", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-22T12:05:00+08:00"));
    expect(phases.map((phase) => phase.state)).toEqual([
      "done",
      "done",
      "active",
      "next",
      "pending",
      "pending",
    ]);
    expect(phases[2].tone).toBe("lunch");
  });

  it("activates afternoon tracking until the final confirmation", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-22T13:56:00+08:00"));
    expect(phases.map((phase) => phase.state)).toEqual([
      "done",
      "done",
      "done",
      "active",
      "next",
      "pending",
    ]);
  });

  it("highlights the 14:50 confirmation as action time", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-22T14:52:00+08:00"));
    expect(phases.map((phase) => phase.state)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "active",
      "next",
    ]);
    expect(phases[4].tone).toBe("action");
    expect(phases[5].tone).toBe("action");
  });

  it("activates paper entry after 14:55 and finishes the day by 15:00", () => {
    const entry = buildLowSuctionPhases(strategyAt("2026-07-22T14:56:00+08:00", "paper_account_active"));
    expect(entry.map((phase) => phase.state)).toEqual([
      "done",
      "done",
      "done",
      "done",
      "done",
      "active",
    ]);
    const closed = buildLowSuctionPhases(strategyAt("2026-07-22T15:30:00+08:00", "paper_account_active"));
    expect(closed.every((phase) => phase.state === "done")).toBe(true);
  });

  it("resets to the morning scan on market-closed days", () => {
    const phases = buildLowSuctionPhases(strategyAt("2026-07-25T12:00:00+08:00", "market_closed"));
    expect(phases.map((phase) => phase.state)).toEqual([
      "next",
      "pending",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });
});
