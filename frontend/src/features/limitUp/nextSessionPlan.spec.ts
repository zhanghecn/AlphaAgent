import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import { liveHeader, signalStatePresentation } from "./nextSessionPlan";

function snapshot(mode: string): LimitUpSignalSnapshot {
  return { mode } as LimitUpSignalSnapshot;
}

function signal(
  signalState: string,
  executionPermission = "research_only",
): LimitUpLiveSignal {
  return {
    signal_state: signalState,
    execution_permission: executionPermission,
  } as LimitUpLiveSignal;
}

describe("next-session plan presentation", () => {
  it("labels final next-session plans without calling them a closed market", () => {
    expect(liveHeader(snapshot("next_session_final"))).toEqual({
      title: "次交易时段正式观察",
      tone: "neutral",
    });
  });

  it("labels preliminary next-session plans", () => {
    expect(liveHeader(snapshot("next_session_preliminary"))).toEqual({
      title: "次交易时段初步观察",
      tone: "warning",
    });
  });

  it.each([
    ["approaching_trigger", "接近触发", "warning"],
    ["trigger_ready", "买点已触发（研究）", "positive"],
    ["invalidated", "条件失效", "negative"],
  ])("maps %s to a user-facing state", (state, label, tone) => {
    expect(signalStatePresentation(signal(state))).toEqual({ label, tone });
  });
});
