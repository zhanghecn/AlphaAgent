import type { LimitUpLiveSignal, LimitUpTriggerCheck } from "@/api/limitUp";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";
import { liveSignalPresentation } from "./nextSessionPlan";
import { firstBoardCompositeReasons } from "./limitUpPresentation";
import { signalAnchorId } from "./BuyAlertBanner";
import {
  amountTone,
  entryKindLabel,
  factorLabel,
  formatAmount,
  formatNumber,
  formatPct,
  formatPrice,
  formatSignedPct,
  formatTime,
  gateStateLabel,
  liveFactorSummary,
  rateTone,
  sectorRouteLabel,
  setupTagLabel,
  tboxTone,
  twoToThreeQualityLabel,
} from "./liveFormat";

interface LiveSignalCardProps {
  signal: LimitUpLiveSignal;
  stale: boolean;
  paused: boolean;
  preboard?: boolean;
}

export function LiveSignalCard({ signal, stale, paused, preboard = false }: LiveSignalCardProps) {
  const state = liveSignalPresentation(signal, stale, paused);
  const actionable = state.tone === "positive";
  const observation = state.tone === "warning";
  const manualResearchTrigger = (
    !stale
    && !paused
    && signal.signal_state === "trigger_ready"
    && signal.execution_permission === "research_only"
  );
  const factorSummary = liveFactorSummary(signal);
  const setupSummary = (signal.setup_tags ?? []).map(setupTagLabel).join(" · ");
  const strategyName = signal.strategy_name ?? setupSummary;
  const primaryPendingReason = signal.pending_reasons?.[0];
  const additionalPendingCount = Math.max((signal.pending_reasons?.length ?? 0) - 1, 0);
  const conclusion = primaryPendingReason ?? signal.reason;
  const selectionReasons = [
    ...(signal.selection_reasons?.slice(0, 4).map(factorLabel) ?? []),
    ...firstBoardCompositeReasons(signal),
  ].slice(0, 5).join(" · ") || factorSummary;
  const stockEvidence = signal.historical_evidence;
  const conceptEvidence = signal.concept_name
    ? `${signal.concept_name} · 强度${formatNumber(signal.concept_strength_score, 1)} · 排名${signal.concept_strength_rank ?? "-"} · 概念龙${signal.concept_leader_rank ?? "-"}`
    : "概念共振待确认";
  const stateLabel = preboard ? "板前买点" : state.label;
  const conceptDegraded = (
    (signal.concept_snapshot_age_seconds ?? 0) > 45
    || (signal.concept_coverage_ratio ?? 1) < 0.9
  );

  return (
    <article
      id={signalAnchorId(signal.vt_symbol)}
      className={cn(
        "scroll-mt-24 rounded-lg border bg-card transition-shadow",
        actionable
          ? "border-rise/60 shadow-md shadow-rise/10"
          : observation
            ? "border-amber-500/50"
            : "border-border",
      )}
    >
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3">
        <span
          className={cn(
            "inline-flex shrink-0 items-center rounded-full border px-2.5 py-1 text-xs font-semibold",
            actionable
              ? "border-rise/50 bg-rise/10 text-rise"
              : observation
                ? "border-amber-500/50 bg-amber-500/10 text-amber-700 dark:text-amber-300"
                : "border-border bg-muted/40 text-muted-foreground",
          )}
        >
          {stateLabel}
        </span>
        <div className="min-w-0">
          <StockIdentityLink
            name={signal.name}
            vtSymbol={signal.vt_symbol}
            meta={`${signal.concept_name ?? signal.sector_name ?? "板块待确认"} · 概念龙${signal.concept_leader_rank ?? "-"} · 市场${signal.market_dragon_rank ?? "-"}`}
          />
        </div>
        <div className="ml-auto flex items-baseline gap-4 tabular-nums">
          <span className={cn("text-2xl font-bold leading-none", amountTone(signal.change_pct))}>
            {formatSignedPct(signal.change_pct)}
          </span>
          <span className="text-sm font-medium text-foreground">现价 {formatPrice(signal.last_price)}</span>
          <span className="text-sm text-muted-foreground">距板 {formatPct(signal.distance_to_limit_pct)}</span>
        </div>
      </header>

      <div className="grid gap-x-6 gap-y-3 px-4 py-3 text-xs leading-5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div className="min-w-0 space-y-1">
          <div className="font-medium text-foreground">{conceptEvidence}</div>
          {conceptDegraded && (
            <div className="text-fall">
              概念快照 {formatNumber(signal.concept_snapshot_age_seconds, 0)} 秒 · 覆盖 {formatPct((signal.concept_coverage_ratio ?? 0) * 100)}
            </div>
          )}
          {strategyName && <div className="font-medium text-foreground">战法：{strategyName}</div>}
          {selectionReasons && <div className="text-foreground">入选：{selectionReasons}</div>}
          {manualResearchTrigger && (
            <div className="font-medium text-rise">
              {signal.state === "sealed" || signal.state === "resealed"
                ? "动能买点已到；可尝试涨停价排队，成交以委托回报为准"
                : "动能买点已到；自动下单仍未开放"}
            </div>
          )}
          {conclusion && (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1 text-amber-700 dark:text-amber-300">
              结论：{conclusion}{additionalPendingCount > 0 ? `（另有 ${additionalPendingCount} 项）` : ""}
            </div>
          )}
          <TriggerChecks checks={signal.trigger_checks} />
          {signal.board_lane === "first_board" && (
            <div className="text-muted-foreground">
              动能门 {gateStateLabel(signal.momentum_gate_passed)} · 溢价门 {gateStateLabel(signal.premium_gate_passed)}
              {signal.sector_route ? ` · 实时路径 ${sectorRouteLabel(signal.sector_route)}` : ""}
              {signal.concept_launch_confirmed ? " · 全面启动确认" : ""}
            </div>
          )}
        </div>

        <div className="min-w-0 space-y-1 lg:border-l lg:pl-6">
          <InstructionRow label="买入" value={signal.buy_instruction ?? signal.buy_condition ?? "条件待确认"} />
          <InstructionRow label="卖出" value={signal.sell_instruction ?? signal.sell_condition ?? "D+1尾盘按官方收盘价统一卖出"} />
          <InstructionRow label="取消" value={signal.cancel_checks?.join("；") ?? signal.cancel_condition} />
          <div className="pt-1 text-muted-foreground">
            {entryKindLabel(signal.entry_kind)} · 触发价 {formatPrice(signal.trigger_price)}
            {signal.board_lane === "first_board" && signal.lane_support_score != null
              ? ` · 动能 ${formatNumber(signal.lane_support_score, 1)}`
              : ""}
            {signal.board_lane === "two_to_three" ? ` · ${twoToThreeQualityLabel(signal.lane_quality_tier, signal.lane_risk_count)}` : ""}
            {signal.state_updated_at ? ` · ${formatTime(signal.state_updated_at)}` : ""}
          </div>
          <div className="text-muted-foreground">
            盘口：换手 {formatPct(signal.turnover_rate)} · 封单 {formatAmount(signal.seal_amount)}
          </div>
        </div>
      </div>

      <footer className="grid grid-cols-2 gap-px overflow-hidden rounded-b-lg border-t bg-border sm:grid-cols-4">
        {preboard ? (
          <>
            <MetricCell label="板后质量胜率" value={formatPct(signal.quality_win_probability == null ? null : signal.quality_win_probability * 100)} tone={rateTone(signal.quality_win_probability == null ? null : signal.quality_win_probability * 100)} />
            <MetricCell label="预计 D+1" value={formatPct(signal.quality_expected_d1_net_return_pct)} tone={amountTone(signal.quality_expected_d1_net_return_pct)} />
            <MetricCell label="若触板质量" value="通过" tone="text-rise" />
            <MetricCell label="实时动能" value={formatNumber(signal.lane_support_score, 1)} />
          </>
        ) : signal.board_lane === "first_board" ? (
          <>
            <MetricCell label="个股联合率" value={formatPct(stockEvidence?.historical_win_rate)} tone={rateTone(stockEvidence?.historical_win_rate)} />
            <MetricCell label={`同股D+1 (${stockEvidence?.d1_money_effect_sample_count ?? 0})`} value={formatPct(stockEvidence?.d1_money_effect_win_rate)} tone={rateTone(stockEvidence?.d1_money_effect_win_rate)} />
            <MetricCell label={`126日封停 (${stockEvidence?.seal_sample_count ?? 0})`} value={formatPct(stockEvidence?.seal_success_rate)} tone={rateTone(stockEvidence?.seal_success_rate)} />
            <MetricCell label="同股D+1平均" value={formatPct(stockEvidence?.d1_money_effect_average_return_pct)} tone={amountTone(stockEvidence?.d1_money_effect_average_return_pct)} />
          </>
        ) : (
          <>
            <MetricCell label="TBOX" value={formatNumber(signal.historical_evidence?.tbox_score, 1)} tone={tboxTone(signal.historical_evidence?.tbox_score)} />
            <MetricCell label="历史胜率" value={formatPct(signal.historical_evidence?.smoothed_win_rate)} tone={rateTone(signal.historical_evidence?.smoothed_win_rate)} />
            <MetricCell label="平均 D+1" value={formatPct(signal.historical_evidence?.average_return_pct)} tone={amountTone(signal.historical_evidence?.average_return_pct)} />
            <MetricCell label="战法复利" value={formatPct(signal.strategy_evidence?.total_return_pct)} tone={amountTone(signal.strategy_evidence?.total_return_pct)} />
          </>
        )}
      </footer>
    </article>
  );
}

function InstructionRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex gap-2">
      <span className="w-8 shrink-0 font-mono text-[10px] font-semibold leading-5 tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="min-w-0 text-muted-foreground">{value || "条件待确认"}</span>
    </div>
  );
}

function MetricCell({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return (
    <div className="bg-card px-3 py-2">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 text-sm font-semibold tabular-nums", tone)}>{value}</div>
    </div>
  );
}

function TriggerChecks({ checks = [] }: { checks?: LimitUpTriggerCheck[] }) {
  if (!checks.length) return null;
  const unresolved = checks.filter((check) => check.status === "pending" || check.status === "failed");
  if (!unresolved.length) return <div className="text-rise">触发检查：全部通过</div>;
  const [primary] = unresolved;
  return (
    <div className="text-muted-foreground">
      {primary.status === "failed" ? "未通过" : "待确认"}：{primary.label}
      {primary.observed ? ` ${primary.observed}` : ""}
      {primary.required ? `（要求 ${primary.required}）` : ""}
      {unresolved.length > 1 ? ` · 另有 ${unresolved.length - 1} 项` : ""}
    </div>
  );
}
