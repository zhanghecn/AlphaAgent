import { useState } from "react";
import { Activity, ArrowRight, BarChart3, BookOpenText, Info } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type {
  LowSuctionCrossRegimeValidation,
  LowSuctionHistoricalOverview,
  LowSuctionStrategyOverview,
  LowSuctionStrategySignal,
} from "@/api/lowSuction";
import { cn } from "@/lib/utils";
import { LowSuctionHistoryLedger } from "./LowSuctionHistoryLedger";
import { LowSuctionRuleEvidenceModal, type LowSuctionRuleEvidence } from "./LowSuctionRuleEvidenceModal";

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
  const [view, setView] = useState<View>("live");
  return (
    <div className="min-w-0">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="font-display text-lg font-semibold">低吸研究</h1>
          <span className="text-xs text-muted-foreground">主升龙头 · 日线收盘回测</span>
        </div>
        <div className="text-xs text-muted-foreground">
          主板 · 动态 Top3 · 第一次 MA5 / 后续 MA10
        </div>
      </header>

      <nav className="flex h-11 items-end gap-6 overflow-x-auto border-b" role="tablist" aria-label="低吸研究视图">
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
        {view === "rules" && <RulesView validation={validation} />}
      </section>
    </div>
  );
}

function BacktestView({
  validation,
  history,
}: {
  validation: LowSuctionCrossRegimeValidation;
  history: LowSuctionHistoricalOverview;
}) {
  const candidate = validation.three_phase_candidate;
  const run = history.latest_run;
  const phaseRows = [
    ...candidate.development_market_phases.map((row) => ({ ...row, split: "开发段" })),
    ...candidate.validation_market_phases.map((row) => ({ ...row, split: "验证段" })),
  ];
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b py-4">
        <div>
          <div className="text-sm font-semibold">三行情自适应回测</div>
          <div className="mt-1 text-xs text-muted-foreground">{candidate.policy_version}</div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div>{run ? `${run.trade_count} 笔 · ${dateText(run.built_at)} 重算` : "回测账本未生成"}</div>
          <div>当前成分历史代理，不计入正式资格</div>
        </div>
      </div>

      <dl className="grid grid-cols-2 border-b border-l sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="交易" value={`${candidate.full_history.closed_trades} 笔`} />
        <Metric label="胜率" value={formatRate(candidate.full_history.win_rate_pct)} tone={rateTone((candidate.full_history.win_rate_pct ?? 0) - 50)} />
        <Metric label="单笔均值" value={formatPct(candidate.full_history.mean_net_return_pct)} tone={rateTone(candidate.full_history.mean_net_return_pct ?? 0)} />
        <Metric label="利润因子" value={formatNumber(candidate.full_history.profit_factor)} />
        <Metric label="两仓复利" value={formatPct(candidate.cash.compound_return_pct)} tone={rateTone(candidate.cash.compound_return_pct)} />
        <Metric label="最大回撤" value={formatPct(candidate.cash.maximum_drawdown_pct)} tone="text-fall" />
      </dl>

      <section className="border-b py-5" aria-labelledby="phase-result-title">
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 id="phase-result-title" className="text-sm font-semibold">分行情结果</h2>
          <span className="text-xs text-muted-foreground">开发段与验证段分别统计</span>
        </div>
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
        <h2 id="robustness-title" className="mb-3 text-sm font-semibold">稳健性检查</h2>
        <dl className="grid border-t text-sm md:grid-cols-2">
          <Definition label="全历史 95% 胜率下界" value={formatRate(candidate.robustness.full_history.wilson_95_lower_pct)} />
          <Definition label="删除单一概念后的最低胜率" value={formatRate(candidate.robustness.full_history.leave_one_campaign_out_min_win_rate_pct)} />
          <Definition label="开发 / 验证下界" value={`${formatRate(candidate.robustness.development.all.wilson_95_lower_pct)} / ${formatRate(candidate.robustness.validation.all.wilson_95_lower_pct)}`} />
          <Definition label="五个时间块" value={`${candidate.robustness.time_block_summary.point_win_rate_above_60_blocks}/5 胜率超过 60% · ${candidate.robustness.time_block_summary.positive_mean_return_blocks}/5 均值为正`} />
        </dl>
      </section>

      <section className="border-t" aria-labelledby="history-ledger-title">
        <div className="pt-5">
          <h2 id="history-ledger-title" className="text-sm font-semibold">回测买卖记录</h2>
          <p className="mt-1 text-xs text-muted-foreground">每一笔信号的买入价、D+1 表现、持有周期和退出收益</p>
        </div>
        <LowSuctionHistoryLedger />
      </section>
    </div>
  );
}

function LiveView({ strategy }: { strategy: LowSuctionStrategyOverview }) {
  const [selectedEvidence, setSelectedEvidence] = useState<LowSuctionRuleEvidence | null>(null);
  const cachedRecommendations = strategy.cached_recommendations ?? [];
  const effectiveRecommendations = strategy.recommendations.length > 0 ? strategy.recommendations : cachedRecommendations;
  const signals = effectiveRecommendations.length > 0 ? effectiveRecommendations : strategy.today_candidates;
  const isRecommendation = effectiveRecommendations.length > 0;
  const usingCache = strategy.recommendations.length === 0 && cachedRecommendations.length > 0;
  const hasRun = strategy.session.status !== "not_run";
  const finalConfirmed = strategy.session.alert_stage === "final_confirmation";
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b py-4">
        <div>
          <h2 className="text-sm font-semibold">{strategy.session.trade_date} {finalConfirmed ? "尾盘确认" : "盘中预警"}</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            {isRecommendation ? `${effectiveRecommendations.length} 只满足买入条件${usingCache ? ` · 缓存自 ${strategy.recommendation_cache?.source_trade_date ?? signals[0]?.signal_trade_date}` : ""}` : hasRun ? "当前没有满足全部买入条件的股票" : "等待首次盘中跟踪"}
          </p>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div>{sessionStatusLabel(strategy.session.status)}</div>
          <div>{strategy.session.last_scan_at ? `跟踪于 ${formatTime(strategy.session.last_scan_at)}` : `更新于 ${formatTime(strategy.generated_at)}`}</div>
          {strategy.session.next_scan_at && <div>下次跟踪 {formatTime(strategy.session.next_scan_at)}</div>}
        </div>
      </div>

      {signals.length === 0 ? (
        <div className="border-b py-12 text-center">
          <div className="text-sm font-medium">{hasRun ? "今日暂无买入推荐" : "盘中预警尚未计算"}</div>
          <div className="mt-1 text-xs text-muted-foreground">{hasRun ? "没有股票同时通过主升、动态 Top3、回踩和转强条件" : "等待当日数据更新与低吸筛选任务执行"}</div>
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

      <div className="grid border-b text-sm sm:grid-cols-3">
        <Definition label="候选" value={`${strategy.today_candidates.length} 只`} />
        <Definition label="推荐买入" value={`${effectiveRecommendations.length} 只${usingCache ? "（早盘缓存）" : ""}`} />
        <Definition label="执行方式" value="研究推荐，不自动下单" />
      </div>
      <p className="py-3 text-xs leading-5 text-muted-foreground">
        交易日 09:30、10:30、11:30、13:30、14:30 跟踪盘面并提前预警；14:50 尾盘最终确认。盘中预警不占仓，只有尾盘确认才进入 14:55 纸面买入与后续验证账本。
      </p>
      <div className="border-t py-3 text-xs text-muted-foreground">
        D+2 快速涨停影子：已结算 {strategy.d2_fast_limit_shadow?.settled ?? 0} / 20 笔
        {(strategy.d2_fast_limit_shadow?.settled ?? 0) > 0 && ` · 改善 ${strategy.d2_fast_limit_shadow.improved} 笔 · 平均增量 ${formatPct(strategy.d2_fast_limit_shadow.mean_return_delta_pct_points)}`}
      </div>
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

type RuleNode = {
  id: string;
  title: string;
  summary: string;
  algorithm: string;
  data: string;
  reject: string;
};

function RulesView({ validation }: { validation: LowSuctionCrossRegimeValidation }) {
  const contract = validation.three_phase_candidate.execution_contract;
  const nodes: RuleNode[] = [
    { id: "universe", title: "股票池", summary: "只保留可交易主板", algorithm: contract.universe, data: "证券基础信息、上市状态、ST 标记、交易板块", reject: "排除，不进入当日候选。" },
    { id: "campaign", title: "概念主升", summary: "确认资金推动的概念行情", algorithm: contract.concept_campaign, data: "概念成分日线、概念涨幅、换手与回撤序列", reject: "概念未启动或已经退潮，整组股票不参与。" },
    { id: "leader", title: "动态龙头", summary: "计算概念内 Top3", algorithm: contract.leader_identity, data: "截至当日的波段涨幅、强势日、概念超额、换手扩张", reject: "排名在 Top3 之外，不做低吸。" },
    { id: "structure", title: "个股主升", summary: "确认仍有创新高能力", algorithm: contract.main_rise_structure, data: "个股日线、可见前高、波段结构与均线", reject: "结构破坏或无法形成更高点，停止跟踪。" },
    { id: "support", title: "回踩支撑", summary: "第一次看 MA5，后续看 MA10", algorithm: contract.wave_support, data: "信号日前完整日线、MA5、MA10、波段次数", reject: "未触及目标支撑或有效跌破支撑，不买。" },
    { id: "reclaim", title: "分歧转强", summary: "支撑测试后重新走强", algorithm: contract.common_reclaim, data: "支撑测试后 1-2 日的收盘、涨幅、最低价和参考前高", reject: "只有回踩、没有转强确认，继续等待。" },
    { id: "entry", title: "收盘买入", summary: "信号日按收盘价成交", algorithm: `${contract.uptrend_entry}；${contract.warming_entry}；${contract.rotation_entry}。${contract.entry_execution}`, data: "行情阶段、信号日完整收盘价、组合可用仓位", reject: `退潮时${contract.retreat_entry}；仓位或概念限制不通过也不买。` },
    { id: "exit", title: "退出结算", summary: "D+1 止损，盈利单跟随结构", algorithm: `${contract.d1_exit}；${contract.winner_exit}`, data: "D+1 及后续完整日线、前高、个股结构、概念行情状态", reject: "成本后 D+1 不盈利直接退出；盈利单在创新高确认或结构结束时退出。" },
  ];
  const [selectedId, setSelectedId] = useState(nodes[0].id);
  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0];
  return (
    <div className="min-w-0 py-5">
      <div className="overflow-x-auto pb-3">
        <ol className="flex min-w-[980px] items-stretch" aria-label="低吸规则流程图">
          {nodes.map((node, index) => (
            <li key={node.id} className="flex min-w-0 flex-1 items-center">
              <button type="button" aria-current={selected.id === node.id ? "step" : undefined} onClick={() => setSelectedId(node.id)} className={cn("h-full w-full border px-3 py-3 text-left transition-colors", selected.id === node.id ? "border-foreground bg-muted/40" : "border-border hover:bg-muted/20")}>
                <span className="block font-mono text-xs text-muted-foreground">{String(index + 1).padStart(2, "0")}</span>
                <span className="mt-1 block text-sm font-semibold">{node.title}</span>
                <span className="mt-1 block text-xs leading-4 text-muted-foreground">{node.summary}</span>
              </button>
              {index < nodes.length - 1 && <ArrowRight size={16} className="mx-1 shrink-0 text-muted-foreground" aria-hidden />}
            </li>
          ))}
        </ol>
      </div>

      <section className="mt-3 border-t" aria-live="polite">
        <div className="grid text-sm lg:grid-cols-[180px_minmax(0,1fr)]">
          <div className="border-b px-3 py-3 font-medium lg:border-r">算法条件</div>
          <div className="border-b px-3 py-3 leading-6">{selected.algorithm}</div>
          <div className="border-b px-3 py-3 font-medium lg:border-r">使用数据</div>
          <div className="border-b px-3 py-3 leading-6 text-muted-foreground">{selected.data}</div>
          <div className="border-b px-3 py-3 font-medium lg:border-r">不通过</div>
          <div className="border-b px-3 py-3 leading-6 text-muted-foreground">{selected.reject}</div>
        </div>
      </section>

      <div className="mt-5 border-t py-3 text-xs text-muted-foreground">
        成交口径：{contract.portfolio}；{contract.data_frequency}
      </div>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div className="border-b border-r px-3 py-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className={cn("mt-1 font-semibold tabular-nums", tone)}>{value}</dd></div>;
}

function Definition({ label, value }: { label: string; value: string }) {
  return <div className="grid grid-cols-[minmax(140px,0.8fr)_minmax(0,1.2fr)] gap-4 border-b px-3 py-2.5 md:odd:border-r"><dt className="text-muted-foreground">{label}</dt><dd className="text-right">{value}</dd></div>;
}

function formatRate(value: number | null) {
  return value == null ? "--" : `${value.toFixed(2)}%`;
}

function formatPct(value: number | null) {
  return value == null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function formatNumber(value: number | null) {
  return value == null ? "--" : value.toFixed(2);
}

function rateTone(value: number) {
  return value > 0 ? "text-rise" : value < 0 ? "text-fall" : "text-muted-foreground";
}

function phaseLabel(value: string) {
  return value === "uptrend" ? "主升" : value === "rotation" ? "轮动" : "升温";
}

function dateText(value: string) {
  return value.slice(0, 10);
}

function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

function sessionStatusLabel(value: string) {
  const labels: Record<string, string> = {
    pre_market: "盘前等待",
    trading: "盘中计算中",
    market_closed: "今日已收盘",
    closed: "今日已收盘",
    not_run: "今日尚未计算",
    preview_ready: "盘中预警已更新",
    signal_frozen: "尾盘信号已确认",
    paper_account_active: "尾盘买入已记录",
  };
  return labels[value] ?? value;
}
