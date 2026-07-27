import type { PreboardCandidate } from "@/api/limitUp";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

import {
  amountTone,
  formatPct,
  formatSignedPct,
  formatTime,
} from "./liveFormat";

export function PreboardRanking({ candidates }: { candidates: PreboardCandidate[] }) {
  const preboardCandidates = candidates.filter((row) => row.strictly_preboard === true);
  if (!preboardCandidates.length) return null;
  const executionLabel = preboardExecutionLabel(preboardCandidates);
  return (
    <section className="border-b" aria-labelledby="preboard-ranking-title">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 bg-muted/20 px-3 py-2 sm:px-4">
        <h2 id="preboard-ranking-title" className="text-sm font-semibold">板前概率排序</h2>
        <span className="text-xs text-muted-foreground">
          {executionLabel}
        </span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {preboardCandidates.length} 只
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1240px] text-left text-xs">
          <thead className="border-y bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">排序</th>
              <th className="px-3 py-2 font-medium">股票</th>
              <th className="px-3 py-2 font-medium">动态龙头</th>
              <th className="px-3 py-2 font-medium">质量层</th>
              <th className="px-3 py-2 text-right font-medium">涨幅</th>
              <th className="px-3 py-2 text-right font-medium">距板</th>
              <th className="px-3 py-2 text-right font-medium">D+1预期</th>
              <th className="px-3 py-2 text-right font-medium">质量胜率</th>
              <th className="px-3 py-2 text-right font-medium">3分钟触板</th>
              <th className="px-3 py-2 text-right font-medium">最终触板</th>
              <th className="px-3 py-2 text-right font-medium">触板后封板</th>
              <th className="px-3 py-2 font-medium">数据</th>
              <th className="px-3 py-2 text-right font-medium">更新</th>
            </tr>
          </thead>
          <tbody>
            {preboardCandidates.map((row, index) => (
              <tr
                key={row.vt_symbol}
                className={cn(
                  "border-b last:border-b-0",
                  row.dynamic_leader_shadow?.global_top5 && "bg-primary/[0.035]",
                )}
              >
                <td className="px-3 py-2 font-mono tabular-nums text-muted-foreground">
                  {index + 1}
                </td>
                <td className="px-3 py-2">
                  <StockIdentityLink
                    name={row.name}
                    vtSymbol={row.vt_symbol}
                    meta={preboardStateLabel(row.decision_state)}
                  />
                </td>
                <td className="px-3 py-2">
                  <DynamicLeaderCell candidate={row} />
                </td>
                <td className="px-3 py-2 font-medium">
                  {qualityTierLabel(row.quality_priority_tier)}
                </td>
                <td className={cn(
                  "px-3 py-2 text-right font-medium tabular-nums",
                  amountTone(row.change_pct),
                )}>
                  {formatSignedPct(row.change_pct)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatPct(row.distance_to_limit_pct)}
                </td>
                <td className={cn(
                  "px-3 py-2 text-right tabular-nums",
                  amountTone(row.quality_expected_d1_net_return_pct),
                )}>
                  {formatSignedPct(row.quality_expected_d1_net_return_pct)}
                </td>
                <td className={cn(
                  "px-3 py-2 text-right tabular-nums",
                  probabilityTone(row.quality_win_probability),
                )}>
                  {formatProbability(row.quality_win_probability)}
                </td>
                <td className="px-3 py-2 text-right font-medium tabular-nums">
                  {formatProbability(row.touch_probability_3m)}
                </td>
                <td className="px-3 py-2 text-right font-medium tabular-nums">
                  {formatProbability(row.eventual_touch_probability)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatProbability(row.seal_probability_given_touch)}
                </td>
                <td className="px-3 py-2 text-muted-foreground">
                  {sourceQualityLabel(row.source_quality)}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                  {row.updated_at ? formatTime(row.updated_at) : "--"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function preboardExecutionLabel(candidates: PreboardCandidate[]) {
  if (candidates.some((row) => row.execution_mode === "formal")) {
    return "正式模型运行中，达标买点进入全量推荐";
  }
  if (candidates.some((row) => row.execution_mode === "shadow")) {
    return "影子观察，不触发买入提醒";
  }
  return "研究观察，不触发买入提醒";
}

function DynamicLeaderCell({ candidate }: { candidate: PreboardCandidate }) {
  const shadow = candidate.dynamic_leader_shadow;
  if (!shadow) return <span className="text-muted-foreground">--</span>;

  const hasDynamicLeader = shadow.status === "locked" || shadow.status === "cooling";
  const leaderRank = hasDynamicLeader && shadow.concept_leader_rank != null
    ? `题材第${shadow.concept_leader_rank}`
    : "尚未形成龙位";
  const trackingRank = shadow.global_top5 && shadow.global_rank != null
    ? ` · 跟踪 Top ${shadow.global_rank}`
    : "";
  return (
    <div className="min-w-[150px] leading-5">
      <div
        className="truncate font-medium"
        title={shadow.concept_name ?? undefined}
      >
        {shadow.concept_name ?? "概念数据缺失"}
      </div>
      <div className="tabular-nums text-muted-foreground">
        {leaderRank}{trackingRank}
      </div>
      <div className={cn(
        "text-[11px]",
        shadow.market_gate_passed === false ? "text-fall" : "text-muted-foreground",
      )}>
        {dynamicLeaderStatus(shadow)}
      </div>
    </div>
  );
}

function dynamicLeaderStatus(
  shadow: NonNullable<PreboardCandidate["dynamic_leader_shadow"]>,
) {
  if (shadow.market_gate_passed === false) return "市场暂停";
  return ({
    locked: "龙位锁定",
    cooling: "题材冷却",
    waiting_theme: "题材未启动",
    unavailable: "概念数据缺失",
  } as Record<string, string>)[shadow.status] ?? "研究跟踪";
}

function formatProbability(value?: number | null) {
  return value == null || !Number.isFinite(value) ? "--" : `${(value * 100).toFixed(2)}%`;
}

function probabilityTone(value?: number | null) {
  return value == null || !Number.isFinite(value)
    ? "text-muted-foreground"
    : value >= 0.5
      ? "text-rise"
      : "text-fall";
}

function qualityTierLabel(value: string) {
  return ({
    A_industry_expanding: "A · 板块扩张",
    C_capital_diffusion_rescue: "C · 资金扩散",
    B_recognition_only: "B · 历史辨识",
  } as Record<string, string>)[value] ?? "--";
}

function preboardStateLabel(value: PreboardCandidate["decision_state"]) {
  return ({
    observe: "观察",
    prepare: "准备",
    actionable: "行动",
    missed: "已错过",
    rejected: "已淘汰",
  } as const)[value];
}

function sourceQualityLabel(value: string) {
  return ({
    official_historical_minute: "官方分钟",
    live_quote_buffer: "实时采样",
    sampled_quote_proxy: "快照代理",
    insufficient_live_prefix: "分钟不足",
  } as Record<string, string>)[value] ?? value;
}
