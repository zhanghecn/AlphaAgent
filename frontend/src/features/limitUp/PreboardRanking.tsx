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
  if (!candidates.length) return null;
  const researchOnly = candidates.every((row) => row.execution_mode === "research_only");
  return (
    <section className="border-b" aria-labelledby="preboard-ranking-title">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 bg-muted/20 px-3 py-2 sm:px-4">
        <h2 id="preboard-ranking-title" className="text-sm font-semibold">板前概率排序</h2>
        <span className="text-xs text-muted-foreground">
          {researchOnly ? "研究观察，不触发买入提醒" : "影子观察，不占用正式仓位"}
        </span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          {candidates.length} 只
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1180px] text-left text-xs">
          <thead className="border-y bg-muted/30 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">排序</th>
              <th className="px-3 py-2 font-medium">股票</th>
              <th className="px-3 py-2 font-medium">动态龙头</th>
              <th className="px-3 py-2 text-right font-medium">涨幅</th>
              <th className="px-3 py-2 text-right font-medium">距板</th>
              <th className="px-3 py-2 text-right font-medium">D+1预期</th>
              <th className="px-3 py-2 text-right font-medium">D+1胜率</th>
              <th className="px-3 py-2 text-right font-medium">3分钟触板</th>
              <th className="px-3 py-2 text-right font-medium">最终触板</th>
              <th className="px-3 py-2 text-right font-medium">触板后封板</th>
              <th className="px-3 py-2 font-medium">数据</th>
              <th className="px-3 py-2 text-right font-medium">更新</th>
            </tr>
          </thead>
          <tbody>
            {candidates.map((row, index) => (
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
                  amountTone(row.expected_d1_net_return_pct),
                )}>
                  {formatSignedPct(row.expected_d1_net_return_pct)}
                </td>
                <td className={cn(
                  "px-3 py-2 text-right tabular-nums",
                  probabilityTone(row.d1_win_probability),
                )}>
                  {formatProbability(row.d1_win_probability)}
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

function DynamicLeaderCell({ candidate }: { candidate: PreboardCandidate }) {
  const shadow = candidate.dynamic_leader_shadow;
  if (!shadow) return <span className="text-muted-foreground">--</span>;

  const leaderRank = shadow.concept_leader_rank == null
    ? "龙位待定"
    : `题材第${shadow.concept_leader_rank}`;
  const trackingRank = shadow.global_top5 && shadow.global_rank != null
    ? ` · 跟踪 Top ${shadow.global_rank}`
    : "";
  return (
    <div className="min-w-[150px] leading-5">
      <div
        className="truncate font-medium"
        title={shadow.concept_name ?? undefined}
      >
        {shadow.concept_name ?? "题材待识别"}
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
    waiting_theme: "等待题材启动",
    unavailable: "题材不可用",
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
