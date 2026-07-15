import type {
  BoardLaneKey,
  LimitUpLiveSignal,
  LimitUpSignalSnapshot,
} from "@/api/limitUp";

export type LimitUpLiveScope = "portfolio" | BoardLaneKey;

const PORTFOLIO_LANES = new Set<BoardLaneKey>([
  "first_board",
  "two_to_three",
]);
const NON_ACTIONABLE_STATES = new Set(["rejected", "missed", "invalidated"]);

export function liveSignalsForScope(
  snapshot: LimitUpSignalSnapshot | undefined,
  scope: LimitUpLiveScope,
): LimitUpLiveSignal[] {
  if (!snapshot) return [];
  if (scope === "portfolio" && snapshot.recommendations.portfolio !== undefined) {
    const portfolio = new Map<string, LimitUpLiveSignal>();
    for (const signal of snapshot.recommendations.portfolio) {
      const lane = signal.board_lane ?? boardLaneForLevel(signal.board_level);
      if (!lane || !PORTFOLIO_LANES.has(lane) || !canTransitionToBuy(signal)) continue;
      if (!portfolio.has(signal.vt_symbol)) portfolio.set(signal.vt_symbol, signal);
    }
    const portfolioRows = [...portfolio.values()].slice(0, 2);
    const selectedSymbols = new Set(portfolioRows.map((signal) => signal.vt_symbol));
    const observations = new Map<string, LimitUpLiveSignal>();
    for (const signal of snapshot.recommendations.watchlist ?? []) {
      const lane = signal.board_lane ?? boardLaneForLevel(signal.board_level);
      if (
        !lane
        || !PORTFOLIO_LANES.has(lane)
        || !canTransitionToBuy(signal)
        || selectedSymbols.has(signal.vt_symbol)
        || observations.has(signal.vt_symbol)
      ) continue;
      observations.set(signal.vt_symbol, signal);
    }
    const observationRows = [...observations.values()]
      .sort(liveSignalSort)
      .slice(0, 6);
    return [...portfolioRows, ...observationRows].slice(0, 8);
  }

  const rows = Object.values(snapshot.recommendations.lanes).flat();
  const selected = new Map<string, LimitUpLiveSignal>();
  for (const signal of rows) {
    const lane = signal.board_lane ?? boardLaneForLevel(signal.board_level);
    if (
      !canTransitionToBuy(signal)
      || !lane
      || (scope === "portfolio" ? !PORTFOLIO_LANES.has(lane) : lane !== scope)
    ) continue;
    const current = selected.get(signal.vt_symbol);
    if (!current || actionPriority(signal.action) < actionPriority(current.action)) {
      selected.set(signal.vt_symbol, signal);
    }
  }
  return [...selected.values()]
    .sort(liveSignalSort)
    .slice(0, scope === "portfolio" ? 8 : 4);
}

function canTransitionToBuy(signal: LimitUpLiveSignal): boolean {
  return (
    !NON_ACTIONABLE_STATES.has(signal.signal_state ?? "")
    && signal.action !== "next_auction"
    && signal.blocking_scope !== "structural"
    && signal.missed_preseal_entry !== true
  );
}

function boardLaneForLevel(level: number): BoardLaneKey | null {
  if (level <= 1) return "first_board";
  if (level === 2) return null;
  if (level === 3) return "two_to_three";
  return "high_board";
}

function actionPriority(action: string): number {
  return ({ buy_now: 0, observe: 1, next_auction: 2, wait_tail: 3, pass: 4 } as Record<string, number>)[action] ?? 5;
}

function liveSignalSort(left: LimitUpLiveSignal, right: LimitUpLiveSignal): number {
  return (
    signalPriority(left) - signalPriority(right)
    || (left.concept_strength_rank ?? 9999) - (right.concept_strength_rank ?? 9999)
    || (left.concept_leader_rank ?? 9999) - (right.concept_leader_rank ?? 9999)
    || (left.distance_to_limit_pct ?? 99) - (right.distance_to_limit_pct ?? 99)
    || (left.market_dragon_rank ?? 9999) - (right.market_dragon_rank ?? 9999)
    || left.vt_symbol.localeCompare(right.vt_symbol)
  );
}

function signalPriority(signal: LimitUpLiveSignal): number {
  if (signal.signal_state === "trigger_ready" || signal.action === "buy_now") return 0;
  if (signal.portfolio_selected) return 1;
  if (signal.signal_state === "approaching_trigger") return 2;
  if (signal.signal_state === "concept_warming") return 3;
  if (signal.signal_state === "rejected") return 5;
  if (signal.signal_state === "missed" || signal.signal_state === "invalidated") return 6;
  return 4 + actionPriority(signal.action) / 10;
}
