import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import { liveHeader, liveSignalPresentation, signalStatePresentation } from "./nextSessionPlan";

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
    ["trigger_ready", "买点触发（人工确认）", "positive"],
    ["missed", "已封板，错过不追", "negative"],
    ["rejected", "硬门未过，今日不买", "negative"],
    ["invalidated", "条件失效", "negative"],
  ])("maps %s to a user-facing state", (state, label, tone) => {
    expect(signalStatePresentation(signal(state))).toEqual({ label, tone });
  });

  it("keeps a research buy trigger visible when automatic validation is locked", () => {
    const triggered = {
      ...signal("trigger_ready"),
      action: "pass",
      research_action: "buy_now",
      validation_passed: false,
    } as LimitUpLiveSignal;

    expect(liveSignalPresentation(triggered)).toEqual({
      label: "买点触发（人工确认）",
      tone: "positive",
    });
  });

  it("keeps a non-triggered validation failure as observation only", () => {
    const observing = {
      ...signal("observing"),
      action: "pass",
      research_action: "pass",
      validation_passed: false,
    } as LimitUpLiveSignal;

    expect(liveSignalPresentation(observing)).toEqual({
      label: "观察，不执行",
      tone: "warning",
    });
  });
});
