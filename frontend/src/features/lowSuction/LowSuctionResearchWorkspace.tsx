import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Activity, BarChart3, BookOpenText, Info } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type {
  LowSuctionCrossRegimeValidation,
  LowSuctionHistoricalOverview,
  LowSuctionStrategyOverview,
  LowSuctionStrategySignal,
} from "@/api/lowSuction";
import { FlowRail } from "@/components/FlowRail";
import { PanelHead } from "@/components/PanelHead";
import { cn } from "@/lib/utils";
import { Definition, Metric, dateText, formatNumber, formatPct, formatRate, formatTime, phaseLabel, rateTone } from "./format";
import { buildLowSuctionPhases } from "./lowSuctionFlow";
import { deriveLiveStatus, type LiveStatus, type LiveTone } from "./liveStatus";
import { LowSuctionHistoryLedger } from "./LowSuctionHistoryLedger";
import { LowSuctionRuleEvidenceModal, type LowSuctionRuleEvidence } from "./LowSuctionRuleEvidenceModal";
import { LowSuctionRulesView } from "./LowSuctionRulesView";

type View = "live" | "backtest" | "rules";

const VIEWS: Array<{ value: View; label: string; icon: LucideIcon }> = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测分析", icon: BarChart3 },
  { value: "rules", label: "规则说明", icon: BookOpenText },
];

export function LowSuctionResearchWorkspace({
  validation,
  history,
  strategy,
}: {
  validation: LowSuctionCrossRegimeValidation;
  history: LowSuctionHistoricalOverview;
  strategy: LowSuctionStrategyOverview;
}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const viewParam = searchParams.get("view");
  const view: View = viewParam === "backtest" || viewParam === "rules" ? viewParam : "live";
  const setView = (next: View) => {
    const params = new URLSearchParams(searchParams);
    if (next === "live") params.delete("view");
    else params.set("view", next);
    setSearchParams(params, { replace: true });
  };
  return (
    <div className="min-w-0">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="font-display text-lg font-semibold">反包研究</h1>
          <span className="text-xs text-muted-foreground">主升龙头 · 反包确认</span>
        </div>
        <div className="text-xs text-muted-foreground">
          主板 · 动态 Top3 · 第一次 MA5 / 后续 MA10
        </div>
      </header>

      <nav className="flex h-11 items-end gap-6 overflow-x-auto border-b" role="tablist" aria-label="反包研究视图">
        {VIEWS.map((item) => {
          const Icon = item.icon;
          const active = view === item.value;
          return (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={active}
              className={cn(
                "flex h-11 shrink-0 items-center gap-2 border-b-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                active ? "border-primary font-semibold text-foreground" : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setView(item.value)}
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>

      <section role="tabpanel" className="min-w-0">
        {view === "live" && <LiveView strategy={strategy} />}
        {view === "backtest" && <BacktestView validation={validation} history={history} />}
        {view === "rules" && <LowSuctionRulesView validation={validation} />}
      </section>
    </div>
  );
}

export function BacktestView({
  validation,
  history,
}: {
  validation: LowSuctionCrossRegimeValidation;
  history: LowSuctionHistoricalOverview;
}) {
  const candidate = validation.three_phase_candidate;
  const run = history.latest_run;
  const quality = run?.metrics.all_trade_quality;
  const account = run?.metrics.two_slot_compound_backtest;
  const skipped = account ? Math.max(account.signals - account.accepted_entries, 0) : 0;
  const phaseRows = [
    ...candidate.development_market_phases.map((row) => ({ ...row, split: "开发段" })),
    ...candidate.validation_market_phases.map((row) => ({ ...row, split: "验证段" })),
  ];
  return (
    <div className="min-w-0">
      <PanelHead
        no="01"
        zh="参数与口径"
        en="SETUP"
        note={candidate.policy_version}
        aside={run ? `${run.trade_count} 笔 · ${dateText(run.built_at)} 重算` : "回测账本未生成"}
      />
      <div className="border-b px-3 py-2 text-[11px] text-muted-foreground sm:px-4">
        当前成分历史代理 · 信号日收盘近涨停成交不保证（D+1 开盘压力口径收益大幅下降）· 仅作探索，不计入正式资格门
      </div>

      <div className="grid border-b lg:grid-cols-2">
        <section aria-label="两仓复利回测">
          <PanelHead no="02" zh="两仓真实账户" en="ACCOUNT" note="受两仓上限、同概念和持仓冲突约束" accent />
          <dl className="grid grid-cols-2 border-l sm:grid-cols-3">
            <Metric label="闭合成交" value={account ? `${account.closed_trades} 笔` : "--"} />
            <Metric label="成交胜率" value={formatRate(account?.cash_win_rate_pct)} tone={rateTone((account?.cash_win_rate_pct ?? 0) - 50)} />
            <Metric label="账户复利" value={formatPct(account?.compound_return_pct)} tone={rateTone(account?.compound_return_pct ?? 0)} />
            <Metric label="最大回撤" value={formatPct(account?.maximum_drawdown_pct)} tone="text-fall" />
            <Metric label="全部信号" value={account ? `${account.signals} 笔` : "--"} />
            <Metric label="仓位跳过" value={account ? `${skipped} 笔` : "--"} />
          </dl>
        </section>
        <section aria-label="全部交易质量">
          <PanelHead no="03" zh="全部推荐质量" en="QUALITY" note="每笔规则信号独立统计，不受两仓已满影响" />
          <dl className="grid grid-cols-2 border-l sm:grid-cols-3">
            <Metric label="全部交易" value={`${quality?.trades ?? run?.trade_count ?? candidate.full_history.closed_trades} 笔`} />
            <Metric label="规则胜率" value={formatRate(quality?.positive_rate_pct ?? candidate.full_history.win_rate_pct)} tone={rateTone((quality?.positive_rate_pct ?? candidate.full_history.win_rate_pct ?? 0) - 50)} />
            <Metric label="单笔均值" value={formatPct(quality?.mean_net_return_pct ?? candidate.full_history.mean_net_return_pct)} tone={rateTone(quality?.mean_net_return_pct ?? candidate.full_history.mean_net_return_pct ?? 0)} />
            <Metric label="利润因子" value={formatNumber(quality?.profit_factor ?? candidate.full_history.profit_factor)} />
            <Metric label="评价口径" value="独立逐笔" />
            <Metric label="仓位影响" value="不剔除" />
          </dl>
        </section>
      </div>

      <section className="border-b py-5" aria-labelledby="phase-result-title">
        <PanelHead no="04" zh="分行情结果" en="REGIME" aside="开发段与验证段分别统计" />
        <div className="overflow-x-auto border-t">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">区间</th>
                <th className="px-3 py-2 font-medium">行情</th>
                <th className="px-3 py-2 text-right font-medium">交易</th>
                <th className="px-3 py-2 text-right font-medium">胜率</th>
                <th className="px-3 py-2 text-right font-medium">95% 下界</th>
                <th className="px-3 py-2 text-right font-medium">单笔均值</th>
              </tr>
            </thead>
            <tbody>
              {phaseRows.map((row) => (
                <tr key={`${row.split}-${row.id}`} className="border-b last:border-b-0">
                  <td className="px-3 py-2.5">{row.split}</td>
                  <td className="px-3 py-2.5">{phaseLabel(row.id)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{row.closed_trades}</td>
                  <td className={cn("px-3 py-2.5 text-right tabular-nums", rateTone((row.win_rate_pct ?? 0) - 50))}>{formatRate(row.win_rate_pct)}</td>
                  <td className={cn("px-3 py-2.5 text-right tabular-nums", rateTone(row.wilson_95_lower_pct - 60))}>{formatRate(row.wilson_95_lower_pct)}</td>
                  <td className={cn("px-3 py-2.5 text-right tabular-nums", rateTone(row.mean_net_return_pct ?? 0))}>{formatPct(row.mean_net_return_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="py-5" aria-labelledby="robustness-title">
        <PanelHead no="05" zh="稳健性检查" en="ROBUSTNESS" />
        <dl className="grid border-t text-sm md:grid-cols-2">
          <Definition label="全历史 95% 胜率下界" value={formatRate(candidate.robustness.full_history.wilson_95_lower_pct)} />
          <Definition label="删除单一概念后的最低胜率" value={formatRate(candidate.robustness.full_history.leave_one_campaign_out_min_win_rate_pct)} />
          <Definition label="开发 / 验证下界" value={`${formatRate(candidate.robustness.development.all.wilson_95_lower_pct)} / ${formatRate(candidate.robustness.validation.all.wilson_95_lower_pct)}`} />
          <Definition label="五个时间块" value={`${candidate.robustness.time_block_summary.point_win_rate_above_60_blocks}/5 胜率超过 60% · ${candidate.robustness.time_block_summary.positive_mean_return_blocks}/5 均值为正`} />
        </dl>
      </section>

      <section className="border-t" aria-labelledby="history-ledger-title">
        <div className="pt-5">
          <PanelHead no="06" zh="逐笔交割" en="TRADES" note="每一笔信号的买入价、D+1 表现、持有周期和退出收益" />
        </div>
        <LowSuctionHistoryLedger />
      </section>
    </div>
  );
}

const STATUS_TONE_CLASS: Record<LiveTone, string> = {
  go: "bg-rise gate-breathe",
  wait: "bg-amber-500",
  stop: "bg-fall",
  info: "bg-primary",
  muted: "bg-muted-foreground/40",
};

function StatusLamp({ status }: { status: LiveStatus }) {
  return (
    <span className="flex items-center gap-2">
      <span className={cn("h-2.5 w-2.5 rounded-full", STATUS_TONE_CLASS[status.tone])} aria-hidden />
      <span className="text-sm font-semibold">{status.label}</span>
    </span>
  );
}

function qualificationLabel(status?: "collecting_forward_evidence" | "not_qualified" | "qualified") {
  return status === "qualified" ? "已达标" : status === "not_qualified" ? "未达标" : "前向收集中";
}

function LiveView({ strategy }: { strategy: LowSuctionStrategyOverview }) {
  const [selectedEvidence, setSelectedEvidence] = useState<LowSuctionRuleEvidence | null>(null);
  const cachedRecommendations = strategy.cached_recommendations ?? [];
  const effectiveRecommendations = strategy.recommendations.length > 0 ? strategy.recommendations : cachedRecommendations;
  const signals = effectiveRecommendations.length > 0 ? effectiveRecommendations : strategy.today_candidates;
  const isRecommendation = effectiveRecommendations.length > 0;
  const usingCache = strategy.recommendations.length === 0 && cachedRecommendations.length > 0;
  const blocked = strategy.session.status === "blocked";
  const hasRun = strategy.session.status !== "not_run";
  const finalConfirmed = strategy.session.alert_stage === "final_confirmation";
  const liveStatus = deriveLiveStatus(strategy);
  const forward = strategy.forward_performance;
  const qualification = forward?.qualification;
  const d2Shadow = strategy.d2_fast_limit_shadow;
  return (
    <div className="min-w-0">
      <FlowRail
        label="作战流程 OPS FLOW"
        phases={buildLowSuctionPhases(strategy)}
        nextAt={strategy.session.next_scan_at ? formatTime(strategy.session.next_scan_at) : undefined}
      />

      <div className="border-b px-3 py-3 sm:px-4">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <StatusLamp status={liveStatus} />
          {liveStatus.detail && <span className="text-xs font-medium text-fall">{liveStatus.detail}</span>}
          <span className="ml-auto text-xs text-muted-foreground">
            候选 <span className="font-semibold tabular-nums text-foreground">{strategy.today_candidates.length}</span> 只
          </span>
          <span className="text-xs text-muted-foreground">
            推荐 <span className="font-semibold tabular-nums text-foreground">{effectiveRecommendations.length}</span> 只
          </span>
          <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
            {strategy.session.last_scan_at ? `跟踪于 ${formatTime(strategy.session.last_scan_at)}` : `更新于 ${formatTime(strategy.generated_at)}`}
            {strategy.session.next_scan_at ? ` · 下次跟踪 ${formatTime(strategy.session.next_scan_at)}` : ""}
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
          <span>
            前向账本 {forward ? `${forward.closed_trades}/${qualification?.thresholds.closed_trades ?? 300} 笔` : "--"} · {qualificationLabel(qualification?.status)}
          </span>
          <span>执行方式 研究推荐，不自动下单</span>
          <span>
            D+2 快速涨停影子 已结算 {d2Shadow?.settled ?? 0}/{d2Shadow?.target_samples ?? 20} 笔
            {(d2Shadow?.settled ?? 0) > 0 && d2Shadow ? ` · 改善 ${d2Shadow.improved} 笔 · 平均增量 ${formatPct(d2Shadow.mean_return_delta_pct_points)}` : ""}
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-b py-4">
        <div>
          <h2 className="text-sm font-semibold">{strategy.session.trade_date} {finalConfirmed ? "尾盘确认" : "盘中预警"}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {blocked
              ? "信号计算受阻，今日推荐可能不完整，请先修复数据管道"
              : isRecommendation
                ? `${effectiveRecommendations.length} 只满足买入条件${usingCache ? ` · 缓存自 ${strategy.recommendation_cache?.source_trade_date ?? signals[0]?.signal_trade_date}` : ""}`
                : hasRun
                  ? "当前没有满足全部买入条件的股票"
                  : "等待首次盘中跟踪"}
          </p>
        </div>
      </div>

      {signals.length === 0 ? (
        <div className="border-b py-12 text-center">
          <div className="text-sm font-medium">
            {blocked ? "信号计算受阻" : hasRun ? "今日暂无买入推荐" : "盘中预警尚未计算"}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">
            {blocked
              ? "阻塞原因已显示在上方指挥条，修复后将在下个扫描窗口自动重试"
              : hasRun
                ? "没有股票同时通过主升、动态 Top3、回踩和转强条件"
                : "等待当日数据更新与反包筛选任务执行"}
          </div>
        </div>
      ) : (
        <div className="overflow-x-auto border-b">
          <table className="w-full min-w-[940px] text-left text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">股票</th>
                <th className="px-3 py-2 font-medium">概念</th>
                <th className="px-3 py-2 text-right font-medium">龙头 / 波段</th>
                <th className="px-3 py-2 font-medium">回踩支撑</th>
                <th className="px-3 py-2 text-right font-medium">参考收盘</th>
                <th className="px-3 py-2 font-medium">结论</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((signal) => <LiveSignalRow key={signal.signal_id} signal={signal} recommended={isRecommendation} onExplain={setSelectedEvidence} />)}
            </tbody>
          </table>
        </div>
      )}

      <p className="py-3 text-xs leading-5 text-muted-foreground">
        交易日 09:30、10:30、11:30、13:30、14:30 跟踪盘面并提前预警；14:50 尾盘最终确认。盘中预警不占仓，只有尾盘确认才进入 14:55 纸面买入与后续验证账本。
      </p>
      <LowSuctionRuleEvidenceModal open={Boolean(selectedEvidence)} onOpenChange={(open) => { if (!open) setSelectedEvidence(null); }} evidence={selectedEvidence} />
    </div>
  );
}

function LiveSignalRow({ signal, recommended, onExplain }: { signal: LowSuctionStrategySignal; recommended: boolean; onExplain: (evidence: LowSuctionRuleEvidence) => void }) {
  return (
    <tr className="border-b last:border-b-0">
      <td className="px-3 py-2.5"><div className="flex items-center gap-1"><span className="font-medium">{signal.stock_name}</span><button type="button" className="p-1 text-muted-foreground hover:text-foreground" title="查看买入规则" aria-label={`查看${signal.stock_name}买入规则`} onClick={() => onExplain(liveEvidence(signal))}><Info size={14} /></button></div><div className="font-mono text-xs text-muted-foreground">{signal.vt_symbol}{signal.cached ? ` · 缓存 ${signal.signal_trade_date}` : ""}</div></td>
      <td className="px-3 py-2.5">{signal.sector_name}</td>
      <td className="px-3 py-2.5 text-right tabular-nums">龙{signal.rank} / 第{signal.current_wave_number}波</td>
      <td className="px-3 py-2.5"><div>{signal.support_line ?? "--"} {signal.support_price?.toFixed(2) ?? "--"}</div><div className="text-xs text-muted-foreground">前高 {signal.reference_peak_price.toFixed(2)}</div></td>
      <td className="px-3 py-2.5 text-right tabular-nums">{signal.provisional_close.toFixed(2)}</td>
      <td className="px-3 py-2.5"><div className={recommended ? "font-semibold text-rise" : "font-medium"}>{recommended ? "推荐买入" : signal.signal_eligible ? "等待组合确认" : "暂不买入"}</div><div className="max-w-72 text-xs text-muted-foreground">{signal.decision_reason}</div></td>
    </tr>
  );
}

function liveEvidence(signal: LowSuctionStrategySignal): LowSuctionRuleEvidence {
  return {
    stockName: signal.stock_name,
    vtSymbol: signal.vt_symbol,
    conceptName: signal.sector_name,
    rank: signal.rank,
    waveNumber: signal.current_wave_number,
    supportLine: signal.support_line,
    supportPrice: signal.support_price,
    signalDate: signal.signal_trade_date,
    entryPrice: signal.provisional_close,
    signalEligible: signal.signal_eligible,
    decisionReason: signal.decision_reason,
  };
}
