import type {
  LimitUpLiveTraceFunnel,
  LimitUpLiveTraceItem,
  LimitUpLiveTraceState,
} from "@/api/limitUp";

const STATUS_LABELS: Record<LimitUpLiveTraceState, string> = {
  radar_entered: "进入 5% 预热",
  concept_warming: "板块预热",
  recommended: "曾进入当前 Top5",
  approaching_trigger: "接近买点",
  trigger_ready: "买点曾触发",
  dropped_from_top5: "已跌出当前 Top5",
  source_missing: "行情源已缺失",
  missed: "已封板，错过不追",
  sealed: "已封板",
  resealed: "已回封",
  failed: "已炸板",
  rejected: "硬性排除",
  invalidated: "条件已失效",
};

const CURRENT_STATE_PRIORITY: Record<LimitUpLiveTraceState, number> = {
  trigger_ready: 0,
  approaching_trigger: 1,
  concept_warming: 2,
  recommended: 3,
  radar_entered: 4,
  dropped_from_top5: 5,
  source_missing: 6,
  missed: 7,
  sealed: 8,
  resealed: 8,
  failed: 9,
  rejected: 10,
  invalidated: 11,
};

export function liveTraceStatusLabel(state: LimitUpLiveTraceState): string {
  return STATUS_LABELS[state] ?? state;
}

export function sortLiveTraceItems(items: LimitUpLiveTraceItem[]): LimitUpLiveTraceItem[] {
  return [...items].sort((left, right) => {
    const priorityDifference = tracePriority(left) - tracePriority(right);
    if (priorityDifference !== 0) return priorityDifference;
    const timeDifference = right.last_seen_at.localeCompare(left.last_seen_at);
    if (timeDifference !== 0) return timeDifference;
    return left.vt_symbol.localeCompare(right.vt_symbol);
  });
}

export function liveTraceFunnelSummary(funnel: LimitUpLiveTraceFunnel): {
  stages: string[];
  blockers: string;
} {
  const stages = [
    `雷达 ${funnel.radar_count}`,
    `预热 ${funnel.warming_count ?? 0}`,
    `Top5 ${funnel.recommended_count}`,
    `接近 ${funnel.approaching_count}`,
    `买点 ${funnel.triggered_count}`,
    `错过 ${funnel.sealed_without_trigger_count}`,
  ];
  const blockerText = funnel.primary_blockers
    .slice(0, 3)
    .map((item) => `${item.label} ${item.count}`)
    .join(" · ");
  return {
    stages,
    blockers: blockerText ? `主要卡点：${blockerText}` : "主要卡点：无",
  };
}

function tracePriority(item: LimitUpLiveTraceItem): number {
  if (item.final_state === "trigger_ready") return 0;
  if (item.final_state === "approaching_trigger") return 1;
  if (item.final_state === "recommended") return 2;
  if (item.ever_triggered) return 3;
  if (item.ever_recommended) return 4;
  return 5 + CURRENT_STATE_PRIORITY[item.final_state];
}
