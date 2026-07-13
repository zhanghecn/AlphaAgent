import type {
  BoardLaneKey,
  LimitUpLiveSignal,
  LimitUpSignalSnapshot,
} from "@/api/limitUp";

export type LimitUpLiveScope = "portfolio" | BoardLaneKey;

const PORTFOLIO_LANES = new Set<BoardLaneKey>([
  "first_board",
  "two_to_three",
  "high_board",
]);

export function liveSignalsForScope(
  snapshot: LimitUpSignalSnapshot | undefined,
  scope: LimitUpLiveScope,
): LimitUpLiveSignal[] {
  if (!snapshot) return [];
  if (scope === "portfolio" && snapshot.recommendations.portfolio !== undefined) {
    const selected = new Map<string, LimitUpLiveSignal>();
    for (const signal of [
      ...snapshot.recommendations.portfolio,
      ...(snapshot.recommendations.watchlist ?? []),
    ]) {
      if (!selected.has(signal.vt_symbol)) selected.set(signal.vt_symbol, signal);
    }
    return [...selected.values()].slice(0, 4);
  }

  const rows = Object.values(snapshot.recommendations.lanes).flat();
  const selected = new Map<string, LimitUpLiveSignal>();
  for (const signal of rows) {
    const lane = signal.board_lane ?? boardLaneForLevel(signal.board_level);
    if (scope === "portfolio" ? !PORTFOLIO_LANES.has(lane) : lane !== scope) continue;
    const current = selected.get(signal.vt_symbol);
    if (!current || actionPriority(signal.action) < actionPriority(current.action)) {
      selected.set(signal.vt_symbol, signal);
    }
  }
  return [...selected.values()]
    .sort((left, right) => (
      actionPriority(left.action) - actionPriority(right.action)
      || (left.market_dragon_rank ?? 99) - (right.market_dragon_rank ?? 99)
      || left.vt_symbol.localeCompare(right.vt_symbol)
    ))
    .slice(0, 4);
}

function boardLaneForLevel(level: number): BoardLaneKey {
  if (level <= 1) return "first_board";
  if (level === 2) return "one_to_two";
  if (level === 3) return "two_to_three";
  return "high_board";
}

function actionPriority(action: string): number {
  return ({ buy_now: 0, observe: 1, next_auction: 2, wait_tail: 3, pass: 4 } as Record<string, number>)[action] ?? 5;
}
