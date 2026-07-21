import type { LimitUpLiveSignal, LimitUpSignalSnapshot } from "@/api/limitUp";

export type PresentationTone = "positive" | "warning" | "negative" | "neutral";

export interface StatusPresentation {
  label: string;
  tone: PresentationTone;
}

const ACTIVE_SESSION_STAGES = new Set([
  "auction_watch",
  "auction",
  "morning",
  "afternoon",
  "tail",
  "close_auction",
]);

// The background scanner persists at most one snapshot every five minutes.
// Polling the same large JSON payload every ten seconds only burns API/DB CPU.
export const ACTIVE_LIVE_POLL_INTERVAL_MS = 60_000;

export function shouldPollLiveTraces(
  snapshot: LimitUpSignalSnapshot | undefined,
): boolean {
  if (!snapshot) return true;
  return snapshot.mode === "live_snapshot"
    && ACTIVE_SESSION_STAGES.has(snapshot.session_stage ?? "");
}

export function liveSnapshotPollingInterval(
  snapshot: LimitUpSignalSnapshot | undefined,
): number {
  if (!snapshot || shouldPollLiveTraces(snapshot)) return ACTIVE_LIVE_POLL_INTERVAL_MS;
  if (snapshot.mode === "next_session_final") return 300_000;
  return 60_000;
}

export function isNextSessionPlan(snapshot: LimitUpSignalSnapshot): boolean {
  return snapshot.mode === "next_session_preliminary" || snapshot.mode === "next_session_final";
}

export function liveHeader(snapshot: LimitUpSignalSnapshot): { title: string; tone: PresentationTone } {
  if (snapshot.mode === "next_session_final") {
    return { title: "次交易时段正式观察", tone: "neutral" };
  }
  if (snapshot.mode === "next_session_preliminary") {
    return { title: "次交易时段初步观察", tone: "warning" };
  }
  return { title: "实时推荐", tone: "neutral" };
}

export function signalStatePresentation(
  signal: Pick<LimitUpLiveSignal, "signal_state" | "execution_permission" | "execution_state" | "action" | "concept_name">,
  stale = false,
): StatusPresentation {
  if (stale) return { label: "数据过期", tone: "negative" };
  if (signal.signal_state === "trigger_ready") {
    return {
      label: signal.execution_permission === "research_only" ? "买点触发（人工确认）" : "买点已触发",
      tone: "positive",
    };
  }
  if (signal.signal_state === "concept_warming") {
    return {
      label: signal.concept_name ? `${signal.concept_name}板块预热` : "板块预热",
      tone: "warning",
    };
  }
  if (signal.signal_state === "approaching_trigger") return { label: "接近买点", tone: "warning" };
  if (signal.signal_state === "pending_auction") return { label: "等待竞价确认", tone: "warning" };
  if (signal.signal_state === "missed") return { label: "已封板，错过不追", tone: "negative" };
  if (signal.signal_state === "rejected") return { label: "硬性排除", tone: "negative" };
  if (signal.signal_state === "invalidated") return { label: "条件失效", tone: "negative" };
  if (signal.signal_state === "observing" || signal.action === "observe") return { label: "观察中", tone: "warning" };
  if (signal.execution_state === "actionable") return { label: "条件满足，可买", tone: "positive" };
  if (signal.action === "pass") return { label: "条件失效，不买", tone: "negative" };
  return { label: "观察等待", tone: "neutral" };
}

export function liveSignalPresentation(
  signal: Pick<
    LimitUpLiveSignal,
    | "signal_state"
    | "execution_permission"
    | "execution_state"
    | "action"
    | "research_action"
    | "validation_passed"
    | "blocking_scope"
    | "pending_reasons"
    | "concept_name"
  >,
  stale = false,
  paused = false,
): StatusPresentation {
  if (paused) return { label: "午间休市，等待下午开盘", tone: "warning" };
  const state = signalStatePresentation(signal, stale);
  if (
    !stale
    && (signal.signal_state === "observing" || signal.signal_state === "approaching_trigger")
    && signal.blocking_scope === "market"
  ) {
    return { label: "等待市场修复", tone: "warning" };
  }
  if (!stale && signal.signal_state === "approaching_trigger") {
    const remaining = signal.pending_reasons?.length ?? 0;
    return {
      label: remaining > 0 ? `接近买点，还差 ${remaining} 项` : "接近买点",
      tone: "warning",
    };
  }
  if (
    stale
    || state.tone === "positive"
    || state.tone === "negative"
    || signal.signal_state === "concept_warming"
    || signal.signal_state === "pending_auction"
    || signal.signal_state === "missed"
    || signal.signal_state === "rejected"
    || signal.signal_state === "invalidated"
    || signal.validation_passed !== false
  ) {
    return state;
  }
  return { label: "观察，不执行", tone: "warning" };
}
