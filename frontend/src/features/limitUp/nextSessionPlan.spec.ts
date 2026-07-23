import { describe, expect, it } from "vitest";

import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";
import {
  ACTIVE_LIVE_POLL_INTERVAL_MS,
  ACTIVE_LIVE_SNAPSHOT_POLL_INTERVAL_MS,
  liveHeader,
  liveSignalPresentation,
  liveSnapshotPollingInterval,
  shouldPollLiveTraces,
  signalStatePresentation,
} from "./nextSessionPlan";

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
  it("polls live snapshots at scanner speed and slows non-live requests", () => {
    const active = {
      ...snapshot("live_snapshot"),
      session_stage: "afternoon",
    };
    const lunch = {
      ...snapshot("stale_snapshot"),
      session_stage: "lunch",
    };
    const preliminary = snapshot("next_session_preliminary");
    const final = snapshot("next_session_final");

    expect(ACTIVE_LIVE_POLL_INTERVAL_MS).toBe(60_000);
    expect(ACTIVE_LIVE_SNAPSHOT_POLL_INTERVAL_MS).toBe(10_000);
    expect(liveSnapshotPollingInterval(undefined)).toBe(10_000);
    expect(liveSnapshotPollingInterval(active)).toBe(10_000);
    expect(liveSnapshotPollingInterval(lunch)).toBe(60_000);
    expect(liveSnapshotPollingInterval(preliminary)).toBe(60_000);
    expect(liveSnapshotPollingInterval(final)).toBe(300_000);
    expect(shouldPollLiveTraces(undefined)).toBe(true);
    expect(shouldPollLiveTraces(active)).toBe(true);
    expect(shouldPollLiveTraces(lunch)).toBe(false);
    expect(shouldPollLiveTraces(preliminary)).toBe(false);
    expect(shouldPollLiveTraces(final)).toBe(false);
  });

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
    ["approaching_trigger", "接近买点", "warning"],
    ["trigger_ready", "买点触发（人工确认）", "positive"],
    ["missed", "已封板，错过不追", "negative"],
    ["rejected", "硬性排除", "negative"],
    ["invalidated", "条件失效", "negative"],
  ])("maps %s to a user-facing state", (state, label, tone) => {
    expect(signalStatePresentation(signal(state))).toEqual({ label, tone });
  });

  it("shows concept warming as a pre-limit observation", () => {
    const warming = {
      ...signal("concept_warming"),
      concept_name: "PCB",
      action: "observe",
      validation_passed: false,
    } as LimitUpLiveSignal;

    expect(signalStatePresentation(warming)).toEqual({ label: "PCB板块预热", tone: "warning" });
    expect(liveSignalPresentation(warming)).toEqual({ label: "PCB板块预热", tone: "warning" });
  });

  it("shows a pending market repair instead of a permanent rejection", () => {
    const approaching = {
      ...signal("approaching_trigger"),
      blocking_scope: "market",
      pending_reasons: ["D-1退潮，盘中尚未确认修复"],
      validation_passed: false,
    } as LimitUpLiveSignal;

    expect(liveSignalPresentation(approaching)).toEqual({
      label: "等待市场修复",
      tone: "warning",
    });
  });

  it("counts the remaining dynamic checks on an approaching signal", () => {
    const approaching = {
      ...signal("approaching_trigger"),
      blocking_scope: "dynamic",
      pending_reasons: ["等待板块扩散", "等待个股资金转正"],
      validation_passed: false,
    } as LimitUpLiveSignal;

    expect(liveSignalPresentation(approaching)).toEqual({
      label: "接近买点，还差 2 项",
      tone: "warning",
    });
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

  it("labels the scheduled lunch pause without calling data expired", () => {
    expect(liveSignalPresentation(signal("approaching_trigger"), true, true)).toEqual({
      label: "午间休市，等待下午开盘",
      tone: "warning",
    });
  });
});
