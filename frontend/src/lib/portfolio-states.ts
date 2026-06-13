/**
 * Portfolio workflow state mapping.
 *
 * Maps the backend group_type values to workflow lanes
 * (watch / candidate / holding / review) plus a blacklist sidebar, so the
 * portfolio page can render stocks by investment lifecycle stage instead of
 * a flat, semantically-flat group list.
 */

/** The five workflow states a portfolio group can belong to. */
export type PortfolioState = "watch" | "candidate" | "holding" | "review" | "blacklist";

/**
 * group_type -> state mapping. Unknown group_type falls back to "watch".
 *
 * Note: "manual" is the backend create_group fallback (services/portfolio/
 * groups.py defaults group_type to "manual"), so it MUST map to watch too —
 * otherwise user-created groups become unclassified.
 */
export const GROUP_TYPE_STATE_MAP: Record<string, PortfolioState> = {
  manual: "watch",
  manual_watch: "watch",
  pullback_entry: "watch",
  trend_follow: "watch",
  quality_long: "watch",
  quant_candidate: "candidate",
  simulation_auto: "holding",
  sold_review: "review",
  blacklist: "blacklist",
};

/** Metadata for a workflow lane. */
export interface PortfolioStateMeta {
  key: PortfolioState;
  label: string;
  description: string;
  order: number;
}

/** The four main lanes in display order (blacklist is rendered separately). */
export const PORTFOLIO_STATES: PortfolioStateMeta[] = [
  { key: "watch", label: "观察池", description: "手动跟踪、等待入场的股票", order: 0 },
  { key: "candidate", label: "候选池", description: "量化策略每日筛选产出", order: 1 },
  { key: "holding", label: "持仓仓", description: "已建仓的模拟持仓，实时监控盈亏", order: 2 },
  { key: "review", label: "复盘池", description: "已卖出股票的复盘归档", order: 3 },
];

const STATE_META_RECORD: Record<PortfolioState, PortfolioStateMeta> = {
  watch: PORTFOLIO_STATES[0],
  candidate: PORTFOLIO_STATES[1],
  holding: PORTFOLIO_STATES[2],
  review: PORTFOLIO_STATES[3],
  blacklist: { key: "blacklist", label: "黑名单", description: "风控禁止的股票", order: 99 },
};

/** Resolve the workflow state for a group_type. Unknown -> watch. */
export function groupTypeToState(groupType: string): PortfolioState {
  return GROUP_TYPE_STATE_MAP[groupType] ?? "watch";
}

/** Whether a group_type is not in the known mapping (needs an "未分类" hint). */
export function isUnclassifiedGroup(groupType: string): boolean {
  return !(groupType in GROUP_TYPE_STATE_MAP);
}

/** Metadata (label/description) for a state. */
export function getStateMeta(state: PortfolioState): PortfolioStateMeta {
  return STATE_META_RECORD[state];
}

/** Minimal shape needed to classify a group by workflow state. */
export interface PortfolioGroupLike {
  id: number;
  name: string;
  group_type: string;
  auto_managed?: boolean;
  description?: string | null;
}

/** Partition groups into the five workflow states. */
export function groupByState<T extends PortfolioGroupLike>(
  groups: T[],
): Record<PortfolioState, T[]> {
  const result: Record<PortfolioState, T[]> = {
    watch: [],
    candidate: [],
    holding: [],
    review: [],
    blacklist: [],
  };
  for (const group of groups) {
    result[groupTypeToState(group.group_type)].push(group);
  }
  return result;
}
