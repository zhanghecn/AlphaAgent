import { describe, expect, it } from "vitest";

import type { LimitUpLiveTraceItem, LimitUpLiveTraceState } from "@/api/limitUp";
import { liveTraceFunnelSummary, liveTraceStatusLabel, sortLiveTraceItems } from "./liveTrace";


function trace(
  vtSymbol: string,
  highestState: LimitUpLiveTraceState,
  everTriggered: boolean,
): LimitUpLiveTraceItem {
  return {
    vt_symbol: vtSymbol,
    name: vtSymbol,
    board_lane: "first_board",
    board_level: 1,
    first_seen_at: "2026-07-14T10:05:00+08:00",
    last_seen_at: "2026-07-14T10:06:00+08:00",
    highest_state: highestState,
    final_state: highestState,
    ever_recommended: true,
    ever_triggered: everTriggered,
    triggered_at: everTriggered ? "2026-07-14T10:05:30+08:00" : null,
    last_price: 10.8,
    change_pct: 8,
    distance_to_limit_pct: 2,
    reason: "test",
    event_count: 2,
  };
}


describe("limit-up live trace presentation", () => {
  it("sorts actionable and historically triggered rows before terminal rows", () => {
    const radarOnly = trace("600001.SSE", "radar_entered", false);
    radarOnly.ever_recommended = false;
    expect(sortLiveTraceItems([
      radarOnly,
      trace("600002.SSE", "approaching_trigger", false),
      trace("600003.SSE", "invalidated", true),
      trace("600004.SSE", "dropped_from_top5", false),
    ]).map((row) => row.vt_symbol)).toEqual([
      "600002.SSE",
      "600003.SSE",
      "600004.SSE",
      "600001.SSE",
    ]);
  });

  it("uses explicit trading-state labels", () => {
    expect(liveTraceStatusLabel("missed")).toBe("已封板，错过不追");
    expect(liveTraceStatusLabel("rejected")).toBe("硬性排除");
    expect(liveTraceStatusLabel("dropped_from_top5")).toBe("已跌出当前 Top5");
    expect(liveTraceStatusLabel("trigger_ready")).toBe("买点曾触发");
    expect(liveTraceStatusLabel("concept_warming")).toBe("板块预热");
  });

  it("summarizes the zero-buy funnel and its primary blockers", () => {
    expect(liveTraceFunnelSummary({
      radar_count: 146,
      warming_count: 18,
      recommended_count: 54,
      approaching_count: 6,
      triggered_count: 0,
      sealed_without_trigger_count: 3,
      structural_rejected_count: 40,
      market_blocked_count: 8,
      dynamic_blocked_count: 6,
      primary_blockers: [
        { code: "sector_heat", label: "板块热度", count: 6 },
        { code: "sector_expansion", label: "板块扩散", count: 5 },
      ],
    })).toEqual({
      stages: ["雷达 146", "预热 18", "Top5 54", "接近 6", "买点 0", "错过 3"],
      blockers: "主要卡点：板块热度 6 · 板块扩散 5",
    });
  });
});
