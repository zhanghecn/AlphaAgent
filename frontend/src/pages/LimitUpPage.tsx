import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  RefreshCw,
  ReceiptText,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  fetchLimitUpHistoryDates,
  fetchLimitUpHistoryLedger,
  fetchLimitUpLaneBacktest,
  fetchLimitUpLive,
  fetchLimitUpSectorWarmupResearch,
  type BoardLaneKey,
  type LimitUpBacktestScope,
  type LimitUpLaneBacktest,
  type LimitUpLaneLedger,
  type LimitUpLaneLedgerTrade,
  type LimitUpLiveSignal,
  type LimitUpSignalSnapshot,
  type LimitUpSectorWarmupReport,
  type LimitUpTriggerCheck,
} from "@/api/limitUp";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import {
  isNextSessionPlan,
  liveHeader,
  liveSignalPresentation,
  type PresentationTone,
} from "@/features/limitUp/nextSessionPlan";
import {
  liveSignalsForScope,
  type LimitUpLiveScope,
} from "@/features/limitUp/livePortfolio";
import { SectorWarmupResearchPanel } from "@/features/limitUp/SectorWarmupResearchPanel";
import { useChartColors } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";

type PrimaryView = "live" | "ledger" | "backtest";

const PRIMARY_VIEWS: Array<{ value: PrimaryView; label: string; icon: typeof Activity }> = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "backtest", label: "回测", icon: BarChart3 },
];

const BOARD_LANES: Array<{ value: BoardLaneKey; label: string }> = [
  { value: "first_board", label: "首板" },
  { value: "one_to_two", label: "一进二" },
  { value: "two_to_three", label: "二进三" },
  { value: "high_board", label: "高板" },
];

const LIVE_SCOPES: Array<{ value: LimitUpLiveScope; label: string }> = [
  { value: "portfolio", label: "组合" },
  ...BOARD_LANES,
];

const BACKTEST_SCOPES: Array<{ value: LimitUpBacktestScope; label: string }> = [
  { value: "portfolio", label: "组合" },
  ...BOARD_LANES,
];

export function LimitUpPage() {
  const [view, setView] = useState<PrimaryView>("live");
  const [liveScope, setLiveScope] = useState<LimitUpLiveScope>("portfolio");
  const [lane, setLane] = useState<BoardLaneKey>("first_board");
  const [backtestScope, setBacktestScope] = useState<LimitUpBacktestScope>("portfolio");
  const [selectedDate, setSelectedDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const datesQuery = useQuery({
    queryKey: ["limitUpHistoryDates"],
    queryFn: fetchLimitUpHistoryDates,
    staleTime: 60_000,
  });
  const liveQuery = useQuery({
    queryKey: ["limitUpLive"],
    queryFn: fetchLimitUpLive,
    enabled: view === "live",
    staleTime: 8_000,
    refetchInterval: view === "live" ? 10_000 : false,
    refetchOnWindowFocus: true,
  });
  const ledgerQuery = useQuery({
    queryKey: ["limitUpLaneLedger", selectedDate, lane],
    queryFn: () => fetchLimitUpHistoryLedger({ date: selectedDate, lane }),
    enabled: view === "ledger" && Boolean(selectedDate),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const backtestQuery = useQuery({
    queryKey: ["limitUpLaneBacktest", start, end, backtestScope],
    queryFn: () => fetchLimitUpLaneBacktest({
      start: start === datesQuery.data?.start ? undefined : start,
      end: end === datesQuery.data?.end ? undefined : end,
      lane: backtestScope,
    }),
    enabled: view === "backtest" && Boolean(start && end),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const warmupResearchQuery = useQuery({
    queryKey: ["limitUpSectorWarmupResearch", start, end],
    queryFn: () => fetchLimitUpSectorWarmupResearch({
      start: start === datesQuery.data?.start ? undefined : start,
      end: end === datesQuery.data?.end ? undefined : end,
    }),
    enabled: view === "backtest" && backtestScope === "first_board" && Boolean(start && end),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const portfolioBacktestQuery = useQuery({
    queryKey: ["limitUpLaneBacktest", start, end, "portfolio"],
    queryFn: () => fetchLimitUpLaneBacktest({
      start: start === datesQuery.data?.start ? undefined : start,
      end: end === datesQuery.data?.end ? undefined : end,
      lane: "portfolio",
    }),
    enabled: view === "live" && Boolean(start && end),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    const latest = datesQuery.data?.latest;
    if (!selectedDate && latest) setSelectedDate(latest);
    if (!end && latest) setEnd(latest);
    if (!start && datesQuery.data?.start) setStart(datesQuery.data.start);
  }, [datesQuery.data?.latest, datesQuery.data?.start, end, selectedDate, start]);

  const dates = datesQuery.data?.dates ?? [];
  const dateIndex = dates.indexOf(selectedDate);
  const previousDate = dateIndex > 0 ? dates[dateIndex - 1] : null;
  const nextDate = dateIndex >= 0 && dateIndex < dates.length - 1 ? dates[dateIndex + 1] : null;
  const activeError = firstError(
    datesQuery.error,
    view === "live" ? liveQuery.error : null,
    view === "ledger" ? ledgerQuery.error : null,
    view === "backtest" ? backtestQuery.error : null,
  );

  return (
    <div className="min-w-0">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-lg font-semibold">打板</h1>
          {view === "live" && <Freshness snapshot={liveQuery.data} />}
        </div>
        <div className="flex items-center gap-2">
          {view === "ledger" && (
            <DateNavigator
              dates={dates}
              value={selectedDate}
              previous={previousDate}
              next={nextDate}
              onChange={setSelectedDate}
            />
          )}
          {view === "live" && (
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-9 w-9"
              title="刷新实时推荐"
              disabled={liveQuery.isFetching}
              onClick={() => void liveQuery.refetch()}
            >
              <RefreshCw size={15} className={cn(liveQuery.isFetching && "animate-spin")} />
            </Button>
          )}
        </div>
      </header>

      <nav className="flex h-12 items-end gap-6 border-b" aria-label="打板主视图">
        {PRIMARY_VIEWS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.value}
              type="button"
              className={cn(
                "flex h-12 items-center gap-2 border-b-2 px-0 text-sm transition-colors",
                view === item.value
                  ? "border-foreground font-semibold text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
              onClick={() => setView(item.value)}
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>

      {view === "backtest" ? (
        <BacktestScopeTabs value={backtestScope} onChange={setBacktestScope} />
      ) : view === "live" ? (
        <LiveScopeTabs value={liveScope} onChange={setLiveScope} />
      ) : (
        <LaneTabs value={lane} onChange={setLane} />
      )}

      {activeError ? (
        <ErrorState message={activeError} onRetry={() => void refreshActive(view, liveQuery.refetch, ledgerQuery.refetch, backtestQuery.refetch)} />
      ) : view === "live" ? (
        <LiveView
          snapshot={liveQuery.data}
          scope={liveScope}
          portfolioReport={portfolioBacktestQuery.data}
          loading={liveQuery.isLoading}
        />
      ) : view === "ledger" ? (
        <LedgerView ledger={ledgerQuery.data} loading={ledgerQuery.isLoading} />
      ) : (
        <BacktestView
          report={backtestQuery.data}
          warmupReport={backtestScope === "first_board" ? warmupResearchQuery.data : undefined}
          warmupLoading={backtestScope === "first_board" && warmupResearchQuery.isLoading}
          warmupError={backtestScope === "first_board" ? firstError(warmupResearchQuery.error) : null}
          loading={backtestQuery.isLoading}
          fetching={backtestQuery.isFetching}
          start={start}
          end={end}
          minimumDate={datesQuery.data?.start}
          maximumDate={datesQuery.data?.end}
          onStart={setStart}
          onEnd={setEnd}
          onRun={() => {
            void backtestQuery.refetch();
            if (backtestScope === "first_board") void warmupResearchQuery.refetch();
          }}
        />
      )}
    </div>
  );
}

function LiveScopeTabs({ value, onChange }: { value: LimitUpLiveScope; onChange: (scope: LimitUpLiveScope) => void }) {
  return (
    <div className="grid h-11 grid-cols-5 border-b" role="tablist" aria-label="实时组合与板位">
      {LIVE_SCOPES.map((scope) => (
        <button
          key={scope.value}
          type="button"
          role="tab"
          aria-selected={value === scope.value}
          className={cn(
            "border-r px-1 text-sm last:border-r-0 sm:px-2",
            value === scope.value
              ? "bg-foreground font-semibold text-background"
              : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
          onClick={() => onChange(scope.value)}
        >
          {scope.label}
        </button>
      ))}
    </div>
  );
}

function LaneTabs({ value, onChange }: { value: BoardLaneKey; onChange: (lane: BoardLaneKey) => void }) {
  return (
    <div className="grid h-11 grid-cols-4 border-b" role="tablist" aria-label="板位战法">
      {BOARD_LANES.map((lane) => (
        <button
          key={lane.value}
          type="button"
          role="tab"
          aria-selected={value === lane.value}
          className={cn(
            "border-r px-2 text-sm last:border-r-0",
            value === lane.value
              ? "bg-foreground font-semibold text-background"
              : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
          onClick={() => onChange(lane.value)}
        >
          {lane.label}
        </button>
      ))}
    </div>
  );
}

function BacktestScopeTabs({ value, onChange }: { value: LimitUpBacktestScope; onChange: (scope: LimitUpBacktestScope) => void }) {
  return (
    <div className="grid h-11 grid-cols-5 border-b" role="tablist" aria-label="回测范围">
      {BACKTEST_SCOPES.map((scope) => (
        <button
          key={scope.value}
          type="button"
          role="tab"
          aria-selected={value === scope.value}
          className={cn(
            "border-r px-1 text-sm last:border-r-0 sm:px-2",
            value === scope.value
              ? "bg-foreground font-semibold text-background"
              : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
          )}
          onClick={() => onChange(scope.value)}
        >
          {scope.label}
        </button>
      ))}
    </div>
  );
}

function Freshness({ snapshot }: { snapshot?: LimitUpSignalSnapshot }) {
  if (!snapshot) return <span className="text-xs text-muted-foreground">读取中</span>;
  const quality = snapshot.data_quality;
  const age = quality.snapshot_age_seconds;
  const limited = quality.rate_limit_status === "limited";
  const degraded = quality.is_stale || quality.status !== "ready" || Boolean(quality.source_errors?.length);
  return (
    <div className={cn("flex min-w-0 items-center gap-2 text-xs", degraded ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground")}>
      {degraded ? <CircleAlert size={14} /> : <Clock3 size={14} />}
      <span className="truncate">
        {snapshot.trade_date} · {snapshot.captured_at ? formatTime(snapshot.captured_at) : "无快照"}
        {age != null ? ` · 延迟 ${formatAge(age)}` : ""}
        {limited ? " · 已触发限流" : quality.source_errors?.length ? " · 数据源降级" : ""}
      </span>
    </div>
  );
}

function LiveView({ snapshot, scope, portfolioReport, loading }: { snapshot?: LimitUpSignalSnapshot; scope: LimitUpLiveScope; portfolioReport?: LimitUpLaneBacktest; loading: boolean }) {
  const signals = useMemo(() => liveSignalsForScope(snapshot, scope), [scope, snapshot]);
  if (loading) return <LoadingState rows={5} />;
  if (!snapshot) return <EmptyRow text="当前没有实时快照" />;
  const gate = snapshot.recommendations.market_gate;
  const laneValidation = scope === "portfolio"
    ? undefined
    : snapshot.recommendations.board_lane_validations?.[scope];
  const planMode = isNextSessionPlan(snapshot);
  const header = liveHeader(snapshot);
  const plan = snapshot.recommendations.plan ?? snapshot.data_quality.plan;
  const strictPortfolioCount = snapshot.recommendations.portfolio?.length ?? signals.length;
  const watchlistCount = snapshot.recommendations.watchlist?.length ?? 0;
  return (
    <section aria-label="实时推荐">
      <LivePortfolioBacktestStrip report={portfolioReport} />
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span className={planMode ? presentationToneClass(header.tone) : gate.passed ? "text-rise" : "text-fall"}>
          {planMode
            ? header.title
            : gate.passed
              ? "市场允许出手"
              : `市场门关闭${gate.reasons.length ? `：${gate.reasons.join("；")}` : ""}`}
        </span>
        {planMode && (
          <span className="text-muted-foreground">
            来源 {snapshot.source_trade_date ?? plan?.source_trade_date ?? snapshot.trade_date}
          </span>
        )}
        {!planMode && gate.repair_confirmed && <span className="text-rise">分歧修复已确认</span>}
        {laneValidation && (
          <span className={laneValidation.passed ? "text-rise" : "text-amber-700 dark:text-amber-300"}>
            {laneValidation.passed ? "战法验证通过" : `战法仅观察：${laneValidation.reason}`}
          </span>
        )}
        {scope === "portfolio" && (
          <span className="text-muted-foreground">
            {planMode ? "提前观察" : "可买组合"} {strictPortfolioCount} / 4
            {!planMode && strictPortfolioCount === 0 && watchlistCount > 0 ? ` · 雷达候选 ${watchlistCount}` : ""}
          </span>
        )}
        <span className="ml-auto text-muted-foreground">
          封板 {snapshot.market_context.sealed_count ?? 0} · 炸板 {snapshot.market_context.failed_count ?? 0} · {snapshot.source}
        </span>
      </div>
      {signals.length ? (
        <div className="divide-y">
          {signals.map((signal) => <LiveSignalRow key={signal.vt_symbol} signal={signal} stale={snapshot.data_quality.is_stale} />)}
        </div>
      ) : (
        <EmptyRow text={
          scope === "portfolio"
            ? "当前没有通过组合硬门的候选，保持空仓"
            : planMode
              ? "当前板位没有入选次交易时段的观察候选"
              : "当前板位没有候选，保持空仓"
        } />
      )}
    </section>
  );
}

function LivePortfolioBacktestStrip({ report }: { report?: LimitUpLaneBacktest }) {
  const summary = report?.summary;
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-x-5 gap-y-1 border-b px-3 py-2 text-xs tabular-nums sm:px-4">
      <span className="font-medium text-foreground">10 万元组合验证</span>
      {summary ? (
        <>
          <span>期末 {formatCurrency(summary.final_equity)}</span>
          <span className={amountTone(summary.total_return_pct)}>复利 {formatPct(summary.total_return_pct)}</span>
          <span className={rateTone(summary.win_rate)}>胜率 {formatPct(summary.win_rate)}</span>
          <span className="text-fall">回撤 {formatPct(summary.max_drawdown_pct)}</span>
          <span className="text-muted-foreground">{summary.trade_count} 笔</span>
        </>
      ) : (
        <span className="text-muted-foreground">历史组合缓存读取中</span>
      )}
    </div>
  );
}

function LiveSignalRow({ signal, stale }: { signal: LimitUpLiveSignal; stale: boolean }) {
  const state = liveSignalPresentation(signal, stale);
  const actionable = state.tone === "positive";
  const observation = state.tone === "warning";
  const manualResearchTrigger = (
    !stale
    && signal.signal_state === "trigger_ready"
    && signal.execution_permission === "research_only"
  );
  const factorSummary = liveFactorSummary(signal);
  const setupSummary = (signal.setup_tags ?? []).map(setupTagLabel).join(" · ");
  const strategyName = signal.strategy_name ?? setupSummary;
  const selectionReasons = signal.selection_reasons?.slice(0, 4).map(factorLabel).join(" · ") ?? factorSummary;
  return (
    <article className={cn("border-l-2 px-3 py-3 sm:px-4", actionable ? "border-l-rise" : observation ? "border-l-amber-500" : "border-l-border")}>
      <div className="grid gap-3 lg:grid-cols-[minmax(180px,1.1fr)_minmax(160px,0.8fr)_minmax(300px,1.8fr)_minmax(150px,0.8fr)] lg:items-center">
        <div className="min-w-0">
          <StockIdentityLink
            name={signal.name}
            vtSymbol={signal.vt_symbol}
            meta={`${signal.sector_name ?? "板块待确认"} · 龙${signal.market_dragon_rank ?? "-"}`}
          />
        </div>
        <div>
          <div className={cn("text-sm font-semibold", presentationToneClass(state.tone))}>{state.label}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {entryKindLabel(signal.entry_kind)} · {formatPrice(signal.trigger_price)}
            {signal.distance_to_limit_pct != null ? ` · 距板 ${formatPct(signal.distance_to_limit_pct)}` : ""}
            {signal.board_lane === "two_to_three" ? ` · ${twoToThreeQualityLabel(signal.lane_quality_tier, signal.lane_risk_count)}` : ""}
            {signal.state_updated_at ? ` · ${formatTime(signal.state_updated_at)}` : ""}
          </div>
        </div>
        <div className="min-w-0 text-xs leading-5">
          {strategyName && <div className="font-medium text-foreground">战法：{strategyName}</div>}
          {selectionReasons && <div className="text-foreground">入选：{selectionReasons}</div>}
          {manualResearchTrigger && (
            <div className="font-medium text-rise">人工买点已到；自动下单仍未开放</div>
          )}
          {signal.reason && <div className="text-amber-700 dark:text-amber-300">结论：{signal.reason}</div>}
          <TriggerChecks checks={signal.trigger_checks} />
          {signal.board_lane === "first_board" && (
            <div className="text-muted-foreground">
              封板门 {gateStateLabel(signal.seal_gate_passed)} · 溢价门 {gateStateLabel(signal.premium_gate_passed)}
            </div>
          )}
          {signal.board_lane === "first_board" && signal.warmup_group && (
            <div className="text-muted-foreground">
              板块预热研究：{signal.warmup_group_name ?? signal.sector_name ?? "概念待确认"} · {warmupStateLabel(signal.warmup_state)} {formatNumber(signal.warmup_score, 0)}
              {signal.warmup_leader_rank ? ` · 动态龙${signal.warmup_leader_rank}` : ""} · 仅影子观察
            </div>
          )}
          <div className="text-muted-foreground">买入：{signal.buy_instruction ?? signal.buy_condition ?? "条件待确认"}</div>
          <div className="text-muted-foreground">卖出：{signal.sell_instruction ?? signal.sell_condition ?? "D+1动态判断"}</div>
          <div className="text-muted-foreground">取消：{signal.cancel_checks?.join("；") ?? signal.cancel_condition}</div>
          <div className="text-muted-foreground">
            盘口：板块热度 {formatNumber(signal.sector_heat, 1)} · 换手 {formatPct(signal.turnover_rate)} · 封单 {formatAmount(signal.seal_amount)}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-x-3 text-xs tabular-nums">
          <Metric label="TBOX" value={formatNumber(signal.historical_evidence?.tbox_score, 1)} tone={tboxTone(signal.historical_evidence?.tbox_score)} />
          <Metric label="历史胜率" value={formatPct(signal.historical_evidence?.smoothed_win_rate)} tone={rateTone(signal.historical_evidence?.smoothed_win_rate)} />
          <Metric label="平均 D+1" value={formatPct(signal.historical_evidence?.average_return_pct)} tone={amountTone(signal.historical_evidence?.average_return_pct)} />
          <Metric label="战法复利" value={formatPct(signal.strategy_evidence?.total_return_pct)} tone={amountTone(signal.strategy_evidence?.total_return_pct)} />
        </div>
      </div>
    </article>
  );
}

function LedgerView({ ledger, loading }: { ledger?: LimitUpLaneLedger; loading: boolean }) {
  if (loading) return <LoadingState rows={5} />;
  if (!ledger) return <EmptyRow text="选择交易日查看交割单" />;
  const observations = ledger.observations ?? [];
  const displayRows = ledger.trades.length ? ledger.trades : observations;
  const observationOnly = ledger.trades.length === 0 && observations.length > 0;
  return (
    <section aria-label="历史交割单">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span>{ledger.trade_date} · {phaseLabel(ledger.validation_phase)}</span>
        <span className={observationOnly ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"}>
          {observationOnly
            ? `研究观察 ${observations.length} 只，不计入正式交割${ledger.validation?.reason ? `：${ledger.validation.reason}` : ""}`
            : `正式交割 ${ledger.selected_count} 只 · 系统动态退出`}
        </span>
      </div>
      {displayRows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[960px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">股票</th>
                <th className="px-3 py-2 text-left">D 买入</th>
                <th className="px-3 py-2 text-left">D+1 卖出</th>
                <th className="px-3 py-2 text-left">板上结果</th>
                <th className="px-3 py-2 text-left">D+1 结果</th>
                <th className="px-3 py-2 text-right">净收益</th>
                <th className="px-3 py-2 text-left">买入依据</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {displayRows.map((trade) => <LedgerTradeRow key={`${trade.buy_date}:${trade.vt_symbol}`} trade={trade} />)}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyRow text="当天没有通过硬门的候选，系统空仓" />
      )}
    </section>
  );
}

function LedgerTradeRow({ trade }: { trade: LimitUpLaneLedgerTrade }) {
  const setups = (trade.setup_tags ?? []).map(setupTagLabel).join(" · ");
  return (
    <tr>
      <td className="px-3 py-3"><StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} meta={trade.industry_name ?? "行业待确认"} /></td>
      <td className="px-3 py-3 text-xs tabular-nums">
        <div>{trade.buy_date} {trade.buy_time}</div>
        <div className="text-muted-foreground">{formatPrice(trade.buy_price)} · {entryKindLabel(trade.signal_kind ?? "")}</div>
        {trade.lane === "two_to_three" && (
          <div className="text-muted-foreground" title={twoToThreeRiskTitle(trade.two_to_three_risk_flags)}>
            {twoToThreeQualityLabel(trade.two_to_three_quality_tier, trade.two_to_three_risk_count)}
          </div>
        )}
      </td>
      <td className="px-3 py-3 text-xs tabular-nums"><div>{trade.sell_date ?? "待 D+1"} {trade.sell_time ?? ""}</div><div className="text-muted-foreground">{formatPrice(trade.sell_price)} · {dynamicExitLabel(trade.dynamic_exit?.mode)}</div>{trade.dynamic_exit?.reason && <div className="mt-1 max-w-64 text-muted-foreground">{trade.dynamic_exit.reason}</div>}</td>
      <td className={cn("px-3 py-3 text-xs font-medium", trade.d_board_status === "sealed" ? "text-rise" : "text-fall")}>{boardStatusLabel(trade.d_board_status)}</td>
      <td className="px-3 py-3 text-xs">{d1OutcomeLabel(trade.d1_outcome)}</td>
      <td className={cn("px-3 py-3 text-right font-semibold tabular-nums", amountTone(trade.return_pct))}>{formatPct(trade.return_pct)}</td>
      <td className="max-w-[360px] px-3 py-3 text-xs leading-5 text-muted-foreground">{setups && <div className="text-foreground">{setups}</div>}{trade.favorable_factors?.map(factorLabel).join("；") || "无可执行证据"}</td>
    </tr>
  );
}

interface BacktestViewProps {
  report?: LimitUpLaneBacktest;
  warmupReport?: LimitUpSectorWarmupReport;
  warmupLoading: boolean;
  warmupError: string | null;
  loading: boolean;
  fetching: boolean;
  start: string;
  end: string;
  minimumDate?: string | null;
  maximumDate?: string | null;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
  onRun: () => void;
}

function BacktestView({ report, warmupReport, warmupLoading, warmupError, loading, fetching, start, end, minimumDate, maximumDate, onStart, onEnd, onRun }: BacktestViewProps) {
  if (loading && !report) return <LoadingState rows={7} />;
  const summary = report?.summary;
  return (
    <section aria-label="真实现金回测">
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-3 sm:px-4">
        <DateInput label="开始" value={start} min={minimumDate} max={maximumDate} onChange={onStart} />
        <DateInput label="结束" value={end} min={minimumDate} max={maximumDate} onChange={onEnd} />
        <div className="h-9 border bg-muted/20 px-3 text-xs leading-9 text-muted-foreground">系统动态退出</div>
        <Button type="button" size="icon" variant="outline" className="h-9 w-9" title="运行回测" disabled={fetching} onClick={onRun}>
          <RefreshCw size={15} className={cn(fetching && "animate-spin")} />
        </Button>
        <div className="ml-auto pb-1 text-xs tabular-nums text-muted-foreground">
          10 万元 · 最多 4 仓 · 100 股整数手 · 含费用滑点
        </div>
      </div>

      <div className="grid grid-cols-2 border-b sm:grid-cols-3 xl:grid-cols-6">
        <SummaryCell label="期末权益" value={formatCurrency(summary?.final_equity)} detail={`初始 ${formatCurrency(summary?.initial_cash)}`} />
        <SummaryCell label="实盘复利" value={formatPct(summary?.total_return_pct)} tone={amountTone(summary?.total_return_pct)} detail={`费用 ${formatCurrency(summary?.total_fees)}`} />
        <SummaryCell label="成交胜率" value={formatPct(summary?.win_rate)} tone={rateTone(summary?.win_rate)} detail={`闭合 ${summary?.trade_count ?? 0} · 未平 ${summary?.open_position_count ?? 0}`} />
        <SummaryCell label="最大回撤" value={formatPct(summary?.max_drawdown_pct)} tone="text-fall" />
        <SummaryCell label="平均仓位" value={formatPct(summary?.average_utilization_pct)} detail={`峰值 ${formatPct(summary?.peak_utilization_pct)}`} />
        <SummaryCell label="跳过信号" value={String(summary?.skipped_count ?? 0)} detail={`实际买入 ${summary?.buy_count ?? 0}`} />
      </div>

      {report && <SignalSummaryStrip report={report} />}
      <SectorWarmupResearchPanel report={warmupReport} loading={warmupLoading} error={warmupError} />
      {report && (
        <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">
          动态退出 · 竞价 {report.exit_summary.auction_exit_count} 笔 · 尾盘 {report.exit_summary.tail_exit_count} 笔
        </div>
      )}
      {report?.lane === "portfolio" ? (
        <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">执行首板 / 二进三 / 高板 · 一进二仅研究 · 共享现金 / 4 仓</div>
      ) : null}
      {report && <ValidationStrip report={report} />}
      {report?.daily_results.length ? <EquityChart report={report} /> : <EmptyRow text="当前范围没有账户权益记录" />}
      {report && <BacktestTrades report={report} />}
      {report && <SkippedOrders report={report} />}
    </section>
  );
}

function SignalSummaryStrip({ report }: { report: LimitUpLaneBacktest }) {
  const summary = report.signal_summary;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
      <span className="font-medium text-foreground">信号研究</span>
      <span className="text-muted-foreground">成熟 {summary.trade_count} / {summary.signal_count}</span>
      <span className="text-muted-foreground">胜率 {formatPct(summary.win_rate)}</span>
      <span className="text-muted-foreground">平均 D+1 {formatPct(summary.average_return_pct)}</span>
      <span className="text-muted-foreground">信号日等权上界 {formatPct(summary.total_return_pct)}</span>
    </div>
  );
}

function ValidationStrip({ report }: { report: LimitUpLaneBacktest }) {
  return (
    <div className="grid border-b lg:grid-cols-[180px_repeat(3,minmax(0,1fr))]">
      <div className="border-b px-3 py-3 lg:border-b-0 lg:border-r sm:px-4">
        <div className={cn("text-sm font-semibold", report.validation.passed ? "text-rise" : "text-fall")}>{report.validation.passed ? "验证通过" : "研究中，不可自动执行"}</div>
        <div className="mt-1 text-xs text-muted-foreground">分时路径 {report.coverage.intraday_path_trade_days ?? 0} 日</div>
      </div>
      {report.validation.checks.map((check) => (
        <div key={check.phase} className="border-b px-3 py-3 last:border-b-0 lg:border-b-0 lg:border-r lg:last:border-r-0 sm:px-4">
          <div className="flex items-center justify-between text-xs"><span className="font-semibold">{phaseLabel(check.phase)}</span><span className={check.passed ? "text-rise" : "text-fall"}>{check.passed ? "通过" : "未通过"}</span></div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs tabular-nums text-muted-foreground">
            <span>{check.trade_count} 笔</span><span>胜率 {formatPct(check.win_rate)}</span><span>复利 {formatPct(check.total_return_pct)}</span><span>回撤 {formatPct(check.max_drawdown_pct)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function EquityChart({ report }: { report: LimitUpLaneBacktest }) {
  const colors = useChartColors();
  return (
    <div className="h-56 border-b px-1 py-3 sm:px-3">
      <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 320, height: 200 }}>
        <LineChart data={report.daily_results} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={colors.grid} strokeDasharray="3 3" />
          <XAxis dataKey="result_date" minTickGap={36} tick={{ fill: colors.text, fontSize: 11 }} axisLine={{ stroke: colors.axis }} tickLine={false} />
          <YAxis tickFormatter={(value) => `${value}%`} tick={{ fill: colors.text, fontSize: 11 }} axisLine={{ stroke: colors.axis }} tickLine={false} width={48} />
          <Tooltip contentStyle={{ background: colors.tooltipBg, borderColor: colors.tooltipBorder, color: colors.tooltipText, borderRadius: 6, fontSize: 12 }} />
          <Line type="monotone" dataKey="total_return_pct" name="累计收益" stroke={colors.brand} strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="drawdown_pct" name="回撤" stroke={colors.fall} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function BacktestTrades({ report }: { report: LimitUpLaneBacktest }) {
  const trades = [...report.trades].reverse().slice(0, 100);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground"><tr><th className="px-3 py-2 text-left">买入 / 卖出</th><th className="px-3 py-2 text-left">股票</th><th className="px-3 py-2 text-left">数量 / 价格</th><th className="px-3 py-2 text-left">D 日 / D+1</th><th className="px-3 py-2 text-right">费用</th><th className="px-3 py-2 text-right">净盈亏</th><th className="px-3 py-2 text-right">收益</th></tr></thead>
        <tbody className="divide-y">
          {trades.map((trade) => (
            <tr key={`${trade.buy_date}:${trade.vt_symbol}:${trade.sell_date}`}>
              <td className="px-3 py-3 text-xs tabular-nums"><div>{trade.buy_date} {trade.buy_time}</div><div className="text-muted-foreground">{trade.sell_date} {trade.sell_time} · {exitReasonLabel(trade.exit_reason)}</div></td>
              <td className="px-3 py-3"><StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} meta={trade.industry_name ?? "行业待确认"} /></td>
              <td className="px-3 py-3 text-xs tabular-nums"><div>{trade.volume} 股 · {formatPrice(trade.buy_price)}</div><div className="text-muted-foreground">卖出 {formatPrice(trade.sell_price)}</div></td>
              <td className="px-3 py-3 text-xs"><div className={trade.d_board_status === "sealed" ? "text-rise" : "text-fall"}>{boardStatusLabel(trade.d_board_status)}</div><div className="text-muted-foreground">{d1OutcomeLabel(trade.d1_outcome)}</div></td>
              <td className="px-3 py-3 text-right text-xs tabular-nums">{formatCurrency(trade.total_fee)}</td>
              <td className={cn("px-3 py-3 text-right text-xs font-medium tabular-nums", amountTone(trade.net_pnl))}>{formatCurrency(trade.net_pnl)}</td>
              <td className={cn("px-3 py-3 text-right font-semibold tabular-nums", amountTone(trade.return_pct))}>{formatPct(trade.return_pct)}</td>
            </tr>
          ))}
          {!trades.length && <tr><td colSpan={7} className="px-3 py-10 text-center text-muted-foreground">没有闭合交易</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function SkippedOrders({ report }: { report: LimitUpLaneBacktest }) {
  const rows = [...report.skipped_orders].reverse().slice(0, 100);
  if (!rows.length) return null;
  return (
    <div className="overflow-x-auto border-t">
      <table className="w-full min-w-[720px] text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground"><tr><th className="px-3 py-2 text-left">未成交</th><th className="px-3 py-2 text-left">股票</th><th className="px-3 py-2 text-left">板位</th><th className="px-3 py-2 text-left">原因</th><th className="px-3 py-2 text-right">当时现金</th></tr></thead>
        <tbody className="divide-y">
          {rows.map((order) => (
            <tr key={order.order_id}>
              <td className="px-3 py-3 text-xs tabular-nums">{order.trade_date} {order.trade_time}</td>
              <td className="px-3 py-3"><StockIdentityLink name={order.name} vtSymbol={order.vt_symbol} /></td>
              <td className="px-3 py-3 text-xs">{boardLaneLabel(order.lane)}</td>
              <td className="px-3 py-3 text-xs text-fall">{skipReasonLabel(order.reason)}</td>
              <td className="px-3 py-3 text-right text-xs tabular-nums">{formatCurrency(order.cash_after)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DateNavigator({ dates, value, previous, next, onChange }: { dates: string[]; value: string; previous: string | null; next: string | null; onChange: (value: string) => void }) {
  return (
    <div className="flex h-9 items-center border">
      <Button type="button" variant="ghost" size="icon" className="h-8 w-8" disabled={!previous} title="前一交易日" onClick={() => previous && onChange(previous)}><ChevronLeft size={15} /></Button>
      <select aria-label="历史交易日" value={value} onChange={(event) => onChange(event.target.value)} className="h-8 min-w-[130px] border-x bg-background px-2 text-sm tabular-nums outline-none">
        {dates.map((date) => <option key={date} value={date}>{date}</option>)}
      </select>
      <Button type="button" variant="ghost" size="icon" className="h-8 w-8" disabled={!next} title="后一交易日" onClick={() => next && onChange(next)}><ChevronRight size={15} /></Button>
    </div>
  );
}

function DateInput({ label, value, min, max, onChange }: { label: string; value: string; min?: string | null; max?: string | null; onChange: (value: string) => void }) {
  return <label className="text-xs text-muted-foreground">{label}<input type="date" value={value} min={min ?? undefined} max={max ?? undefined} onChange={(event) => onChange(event.target.value)} className="mt-1 block h-9 border bg-background px-2 text-sm text-foreground" /></label>;
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div><div className="text-[11px] text-muted-foreground">{label}</div><div className={cn("mt-0.5 font-medium", tone)}>{value}</div></div>;
}

function TriggerChecks({ checks = [] }: { checks?: LimitUpTriggerCheck[] }) {
  if (!checks.length) return null;
  const unresolved = checks.filter((check) => check.status !== "passed");
  if (!unresolved.length) return <div className="text-rise">触发检查：全部通过</div>;
  return (
    <div className="text-muted-foreground">
      {unresolved.map((check) => (
        <div key={check.code}>
          {check.status === "failed" ? "未通过" : "待确认"}：{check.label}
          {check.observed ? ` ${check.observed}` : ""}
          {check.required ? `（要求 ${check.required}）` : ""}
        </div>
      ))}
    </div>
  );
}

function SummaryCell({ label, value, tone, detail }: { label: string; value: string; tone?: string; detail?: string }) {
  return <div className="min-w-0 border-b border-r px-3 py-2.5 last:border-r-0 xl:border-b-0"><div className="text-[11px] text-muted-foreground">{label}</div><div className={cn("mt-0.5 truncate text-sm font-semibold tabular-nums", tone)}>{value}</div>{detail && <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{detail}</div>}</div>;
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-4 py-16 text-center text-sm text-muted-foreground">{text}</div>;
}

function boardLaneLabel(value: BoardLaneKey) { return ({ first_board: "首板", one_to_two: "一进二", two_to_three: "二进三", high_board: "高板" } as Record<BoardLaneKey, string>)[value]; }

function presentationToneClass(tone: PresentationTone) { return ({ positive: "text-rise", warning: "text-amber-700 dark:text-amber-300", negative: "text-fall", neutral: "text-foreground" } as Record<PresentationTone, string>)[tone]; }
function entryKindLabel(value: string) { return (({ none: "不执行", auction: "竞价", sweep: "扫板", reseal: "回封", tail_seal: "尾盘封板", next_auction: "竞价接力", first_touch: "首次触板", intraday: "盘中", wait: "等待确认" } as Record<string, string>)[value] ?? value) || "--"; }
function phaseLabel(value?: string) { return ({ warmup: "预热期", expanding_oos: "滚动样本外", locked_holdout: "锁定留出", post_freeze_forward: "冻结后前向" } as Record<string, string>)[value ?? ""] ?? value ?? "阶段未知"; }
function d1OutcomeLabel(value: string) { return ({ continuation_limit_up: "D+1 连板", next_limit_up_after_failed_board: "D+1 涨停", d1_premium: "D+1 有溢价", direct_breakdown: "D+1 直接砸", no_premium: "D+1 无溢价", awaiting_d1_bar: "待 D+1" } as Record<string, string>)[value] ?? value; }
function boardStatusLabel(value: string) { return ({ sealed: "封住", failed: "触板后炸板", no_limit: "未触板" } as Record<string, string>)[value] ?? value; }
function exitReasonLabel(value: string) { return ({ dynamic_auction_exit: "动态竞价兑现", dynamic_tail_exit: "动态尾盘退出", planned_open: "开盘退出", planned_close: "收盘退出", emergency_close: "开盘未成后收盘退出", retry_open: "延期至开盘退出", retry_close: "延期至收盘退出" } as Record<string, string>)[value] ?? value; }
function dynamicExitLabel(value?: string) { return ({ auction_exit: "竞价兑现", tail_exit: "尾盘退出" } as Record<string, string>)[value ?? ""] ?? "动态判断"; }
function setupTagLabel(value: string) { return ({ sandwich_board: "夹板", return_board: "回马板", weak_to_strong_breakout: "弱转强突破", dragon_first_negative_relay: "龙首阴接力", dragon_weak_to_strong: "龙头弱转强", anti_nuclear_board: "反核板" } as Record<string, string>)[value] ?? value; }
function warmupStateLabel(value?: string) { return ({ cold: "冷却", observe: "观察", warming: "升温", launch: "启动", crowded: "拥挤", ebb: "退潮", unavailable: "数据不足" } as Record<string, string>)[value ?? ""] ?? value ?? "数据不足"; }
function skipReasonLabel(value: string) { return ({ position_limit: "持仓已满", insufficient_cash: "现金不足", below_one_lot: "目标仓位不足一手", duplicate_position: "已有同股持仓", invalid_entry_price: "买入价无效" } as Record<string, string>)[value] ?? value; }
function twoToThreeQualityLabel(tier?: "A" | "B" | null, riskCount?: number | null) { const quality = tier ?? "B"; const risks = riskCount ?? 0; return `${quality}级${risks > 0 ? ` · 风险${risks}` : ""}`; }
function twoToThreeRiskTitle(flags?: string[]) { return (flags ?? []).map((flag) => ({ auction_gap_outside_core: "竞价不在2%-5%核心区", prior_turnover_outside_core: "前板换手不在10%-20%核心区", prior_amount_ratio_outside_core: "前板量能比不在1.2-2", financial_snapshot_missing: "财报快照缺失", prior_low_below_zero: "前板最低价翻绿或缺失", prior_market_failed_rate_high: "前日炸板率偏高或缺失" } as Record<string, string>)[flag] ?? flag).join("；"); }
function factorLabel(value: string) {
  return ({
    half_year_limit_up_gene: "半年有涨停",
    half_year_strong_touch_gene: "半年触板至少6次",
    low_position_or_cooled_pullback: "低位/充分回调",
    post_ten_first_touch: "10点后首次触板",
    intraday_support_confirmed: "盘中承接通过",
    first_board_seal_gate_confirmed: "封板门通过",
    point_in_time_profit_growth: "已披露净利同比至少10%",
    prior_divergence_repair_setup: "前日分歧修复",
    auction_strength_balanced: "竞价强度适中",
    prior_board_changed_hands_and_resealed: "前板换手回封",
    prior_board_full_turnover_reseal: "前板充分换手回封",
    prior_amount_ratio_balanced: "前板温和放量",
    financial_snapshot_available: "财报证据完整",
    prior_low_held_positive: "前板最低未翻绿",
    prior_market_failed_rate_controlled: "前日炸板率受控",
    prior_market_two_to_three_active: "二进三晋级率活跃",
    third_board_weak_to_strong: "三板弱转强",
    prior_divergence_next_auction_strength: "前日分歧次日转强",
    high_board_weak_to_strong: "高板弱转强",
    sector_core: "板块核心",
  } as Record<string, string>)[value] ?? value;
}
function liveFactorSummary(signal: LimitUpLiveSignal) {
  const factors = signal.lane_favorable_factors ?? [];
  const priority = signal.board_lane === "first_board"
    ? [
      "half_year_strong_touch_gene",
      "point_in_time_profit_growth",
      "prior_divergence_repair_setup",
      "intraday_support_confirmed",
    ]
    : factors.slice(0, 4);
  const visible = priority.filter((factor) => factors.includes(factor));
  return visible.map(factorLabel).join(" · ");
}
function gateStateLabel(value?: boolean | null) { return value === true ? "通过" : value === false ? "未通过" : "待数据"; }
function formatPct(value?: number | null) { return value == null || !Number.isFinite(value) ? "--" : `${value.toFixed(2)}%`; }
function formatNumber(value?: number | null, digits = 2) { return value == null || !Number.isFinite(value) ? "--" : value.toFixed(digits); }
function formatPrice(value?: number | null) { return value == null || !Number.isFinite(value) ? "--" : `¥${value.toFixed(2)}`; }
function formatCurrency(value?: number | null) { if (value == null || !Number.isFinite(value)) return "--"; const sign = value < 0 ? "-" : ""; return `${sign}¥${Math.abs(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function formatAmount(value?: number | null) { if (value == null || !Number.isFinite(value)) return "--"; const absolute = Math.abs(value); if (absolute >= 1e8) return `${(value / 1e8).toFixed(2)}亿`; if (absolute >= 1e4) return `${(value / 1e4).toFixed(0)}万`; return value.toFixed(0); }
function formatTime(value: string) { try { return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value)); } catch { return value.slice(11, 19); } }
function formatAge(seconds: number) { return seconds < 60 ? `${seconds}秒` : `${Math.floor(seconds / 60)}分${seconds % 60}秒`; }
function amountTone(value?: number | null) { return value == null || !Number.isFinite(value) ? "text-muted-foreground" : value >= 0 ? "text-rise" : "text-fall"; }
function rateTone(value?: number | null) { return value == null ? "text-muted-foreground" : value >= 50 ? "text-rise" : "text-fall"; }
function tboxTone(value?: number | null) { return value == null ? "text-muted-foreground" : value >= 60 ? "text-rise" : value >= 40 ? "text-amber-700 dark:text-amber-300" : "text-fall"; }
function firstError(...values: unknown[]) { const error = values.find(Boolean); return error instanceof Error ? error.message : error ? "打板数据加载失败" : null; }
async function refreshActive(view: PrimaryView, live: () => Promise<unknown>, ledger: () => Promise<unknown>, backtest: () => Promise<unknown>) { if (view === "live") await live(); else if (view === "ledger") await ledger(); else await backtest(); }
