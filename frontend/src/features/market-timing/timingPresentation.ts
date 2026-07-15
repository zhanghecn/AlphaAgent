import type {
  TimingDailyState,
  TimingSetupType,
  TimingSignal,
} from "@/api/marketTiming";

const TIMING_SETUP_LABELS: Record<TimingSetupType, string> = {
  TREND_GOLD: "趋势转强金手指",
  REVERSAL_GOLD: "弱势衰竭反转金手指",
  TOP_SILVER: "顶部风险银手指",
  BREAKDOWN_SILVER: "趋势破位银手指",
  STRUCTURAL_BREAKDOWN_SILVER: "结构性破位银手指",
  GOLD_FAILURE_SILVER: "金手指失效银手指",
};

export interface TimingEventSummary {
  confirmed: {
    gold: number;
    silver: number;
  };
  invalidated: number;
  pending: number;
}

export function summarizeTimingEvents(signals: TimingSignal[]): TimingEventSummary {
  const summary: TimingEventSummary = {
    confirmed: { gold: 0, silver: 0 },
    invalidated: 0,
    pending: 0,
  };

  for (const signal of signals) {
    if (signal.status === "CONFIRMED") {
      if (signal.direction === "GOLD") summary.confirmed.gold += 1;
      if (signal.direction === "SILVER") summary.confirmed.silver += 1;
    } else if (signal.status === "INVALIDATED") {
      summary.invalidated += 1;
    } else {
      summary.pending += 1;
    }
  }

  return summary;
}

export function recentTimingRows(
  series: TimingDailyState[],
  limit = 20,
): TimingDailyState[] {
  return series.slice(-Math.max(0, limit));
}

export function visibleChartSignals(signals: TimingSignal[]): TimingSignal[] {
  return signals.filter((signal) => signal.status !== "INVALIDATED");
}

export function timingSetupLabel(setupType: TimingSetupType): string {
  return TIMING_SETUP_LABELS[setupType];
}
