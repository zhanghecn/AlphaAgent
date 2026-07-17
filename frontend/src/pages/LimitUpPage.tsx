import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bell,
  BellRing,
  BookOpenText,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleAlert,
  Clock3,
  RefreshCw,
  ReceiptText,
  Volume2,
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
  fetchLimitUpHistoryStatus,
  fetchLimitUpLaneBacktest,
  fetchLimitUpLive,
  fetchLimitUpLiveTraceDates,
  fetchLimitUpLiveTraceDay,
  fetchLimitUpLiveTraceSymbol,
  fetchLimitUpStrategyGuide,
  startLimitUpHistoryRebuild,
  type LimitUpHistoryRebuildStatus,
  type LimitUpLaneBacktest,
  type LimitUpLaneLedger,
  type LimitUpLaneLedgerTrade,
  type LimitUpLiveSignal,
  type LimitUpLiveTraceDay,
  type LimitUpLiveTraceEvent,
  type LimitUpLiveTraceItem,
  type LimitUpLiveTraceState,
  type LimitUpSignalSnapshot,
  type LimitUpTriggerCheck,
} from "@/api/limitUp";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { BacktestRebuildControl } from "@/features/limitUp/BacktestRebuildControl";
import { StrategyGuideDialog } from "@/features/limitUp/StrategyGuideDialog";
import {
  isNextSessionPlan,
  liveHeader,
  liveSignalPresentation,
  type PresentationTone,
} from "@/features/limitUp/nextSessionPlan";
import {
  liveSignalsForScope,
} from "@/features/limitUp/livePortfolio";
import {
  firstBoardCompositeReasons,
  limitUpLaneLabel,
} from "@/features/limitUp/limitUpPresentation";
import {
  liveTraceFunnelSummary,
  liveTraceStatusLabel,
  sortLiveTraceItems,
} from "@/features/limitUp/liveTrace";
import {
  useBuyAlerts,
  type BuyAlertPermission,
} from "@/features/limitUp/useBuyAlerts";
import { useChartColors } from "@/lib/chart-theme";
import { cn } from "@/lib/utils";

type PrimaryView = "live" | "ledger" | "backtest";

const PRIMARY_VIEWS: Array<{ value: PrimaryView; label: string; icon: typeof Activity }> = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "backtest", label: "回测", icon: BarChart3 },
];

export function LimitUpPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const rebuildObservedStatus = useRef<string | null>(null);
  const [view, setView] = useState<PrimaryView>("live");
  const [selectedDate, setSelectedDate] = useState("");
  const [selectedTraceDate, setSelectedTraceDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rebuildError, setRebuildError] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);

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
  const strategyGuideQuery = useQuery({
    queryKey: ["limitUpStrategyGuide"],
    queryFn: fetchLimitUpStrategyGuide,
    enabled: guideOpen,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const traceDatesQuery = useQuery({
    queryKey: ["limitUpLiveTraceDates"],
    queryFn: fetchLimitUpLiveTraceDates,
    enabled: view === "live",
    staleTime: 8_000,
    refetchInterval: view === "live" ? 10_000 : false,
    refetchOnWindowFocus: true,
  });
  const traceDayQuery = useQuery({
    queryKey: ["limitUpLiveTraceDay", selectedTraceDate],
    queryFn: () => fetchLimitUpLiveTraceDay(selectedTraceDate),
    enabled: view === "live" && Boolean(selectedTraceDate),
    staleTime: selectedTraceDate === traceDatesQuery.data?.latest ? 8_000 : Infinity,
    refetchInterval: view === "live" && selectedTraceDate === traceDatesQuery.data?.latest ? 10_000 : false,
    refetchOnWindowFocus: selectedTraceDate === traceDatesQuery.data?.latest,
  });
  const ledgerQuery = useQuery({
    queryKey: ["limitUpScheduledLedger", selectedDate],
    queryFn: () => fetchLimitUpHistoryLedger({ date: selectedDate }),
    enabled: view === "ledger" && Boolean(selectedDate),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const backtestQuery = useQuery({
    queryKey: ["limitUpLaneBacktest", start, end, "portfolio"],
    queryFn: () => fetchLimitUpLaneBacktest({
      start: start === datesQuery.data?.start ? undefined : start,
      end: end === datesQuery.data?.end ? undefined : end,
      lane: "portfolio",
    }),
    enabled: view === "backtest" && Boolean(start && end),
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
  const historyStatusQuery = useQuery({
    queryKey: ["limitUpHistoryStatus"],
    queryFn: fetchLimitUpHistoryStatus,
    enabled: view === "backtest",
    staleTime: 0,
    refetchInterval: (query) => query.state.data?.status === "building" ? 2_000 : false,
    refetchOnWindowFocus: true,
  });
  const historyRebuildMutation = useMutation({
    mutationFn: startLimitUpHistoryRebuild,
    onMutate: () => {
      rebuildObservedStatus.current = "building";
      setRebuildError(null);
    },
    onSuccess: (status) => {
      queryClient.setQueryData<LimitUpHistoryRebuildStatus>(["limitUpHistoryStatus"], status);
      toast({
        title: status.already_running ? "已接入正在进行的重算" : "回测重算已开始",
        description: "后台完成后会自动刷新历史交割单和回测结果",
      });
    },
    onError: (error) => {
      rebuildObservedStatus.current = "failed";
      const message = error instanceof Error ? error.message : "无法启动历史回测重算";
      setRebuildError(message);
      toast({ title: "回测重算启动失败", description: message, variant: "error" });
    },
  });
  const buyAlerts = useBuyAlerts(liveQuery.data);
  useEffect(() => {
    const latest = datesQuery.data?.latest;
    if (!selectedDate && latest) setSelectedDate(latest);
    if (!end && latest) setEnd(latest);
    if (!start && datesQuery.data?.start) setStart(datesQuery.data.start);
  }, [datesQuery.data?.latest, datesQuery.data?.start, end, selectedDate, start]);
  useEffect(() => {
    const traceDates = traceDatesQuery.data?.dates ?? [];
    if (traceDates.length && (!selectedTraceDate || !traceDates.includes(selectedTraceDate))) {
      setSelectedTraceDate(traceDatesQuery.data?.latest ?? traceDates[0]);
    }
  }, [selectedTraceDate, traceDatesQuery.data?.dates, traceDatesQuery.data?.latest]);
  useEffect(() => {
    const status = historyStatusQuery.data?.status;
    if (!status) return;
    const previous = rebuildObservedStatus.current;
    rebuildObservedStatus.current = status;
    if (previous !== "building") return;

    if (status === "ready") {
      setRebuildError(null);
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["limitUpHistoryDates"] }),
        queryClient.invalidateQueries({ queryKey: ["limitUpScheduledLedger"] }),
        queryClient.invalidateQueries({ queryKey: ["limitUpLaneBacktest"] }),
      ]).then(() => {
        toast({
          title: "回测重算完成",
          description: "当前日期、历史交割单和回测结果已刷新",
          variant: "success",
        });
      }).catch(() => {
        const message = "历史账本已更新，但页面刷新失败，请重新打开回测页";
        setRebuildError(message);
        toast({ title: "回测结果刷新失败", description: message, variant: "error" });
      });
      return;
    }

    if (status === "failed") {
      const message = historyStatusQuery.data?.error?.message || "后台重建历史账本失败";
      setRebuildError(message);
      toast({ title: "回测重算失败", description: message, variant: "error" });
    }
  }, [historyStatusQuery.data?.error?.message, historyStatusQuery.data?.status, queryClient, toast]);

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
  const toggleBuyAlerts = async () => {
    const enabling = !buyAlerts.enabled;
    const permission = await buyAlerts.toggle();
    toast({
      title: enabling ? "买点提醒已开启" : "买点提醒已关闭",
      description: enabling
        ? buyAlertPermissionDescription(permission)
        : "不会再播放声音或发送桌面通知",
      variant: enabling ? "success" : "default",
    });
  };
  const testBuyAlerts = async () => {
    const permission = await buyAlerts.test();
    toast({
      title: "测试提醒已触发",
      description: buyAlertPermissionDescription(permission),
      variant: "success",
    });
  };

  return (
    <div className="min-w-0">
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="text-lg font-semibold">打板</h1>
          {view === "live" && <Freshness snapshot={liveQuery.data} />}
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="h-9 gap-2"
            onClick={() => setGuideOpen(true)}
          >
            <BookOpenText size={15} />
            规则说明
          </Button>
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
            <>
              <Button
                type="button"
                size="icon"
                variant="outline"
                className={cn("h-9 w-9", buyAlerts.enabled && "border-rise/50 text-rise")}
                title={buyAlerts.enabled
                  ? `关闭买点提醒 · ${buyAlertPermissionDescription(buyAlerts.permission)}`
                  : "开启买点声音和桌面通知"}
                aria-label={buyAlerts.enabled ? "关闭买点提醒" : "开启买点提醒"}
                aria-pressed={buyAlerts.enabled}
                onClick={() => void toggleBuyAlerts()}
              >
                {buyAlerts.enabled ? <BellRing size={15} /> : <Bell size={15} />}
              </Button>
              {buyAlerts.enabled && (
                <Button
                  type="button"
                  size="icon"
                  variant="outline"
                  className="h-9 w-9"
                  title="测试买点声音和桌面通知"
                  aria-label="测试买点提醒"
                  onClick={() => void testBuyAlerts()}
                >
                  <Volume2 size={15} />
                </Button>
              )}
            </>
          )}
          {view === "live" && (
            <Button
              type="button"
              size="icon"
              variant="outline"
              className="h-9 w-9"
              title="刷新实时推荐"
              disabled={liveQuery.isFetching || traceDatesQuery.isFetching || traceDayQuery.isFetching}
              onClick={() => void Promise.all([
                liveQuery.refetch(),
                traceDatesQuery.refetch(),
                ...(selectedTraceDate ? [traceDayQuery.refetch()] : []),
              ])}
            >
              <RefreshCw
                size={15}
                className={cn(
                  (liveQuery.isFetching || traceDatesQuery.isFetching || traceDayQuery.isFetching) && "animate-spin",
                )}
              />
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

      {activeError ? (
        <ErrorState message={activeError} onRetry={() => void refreshActive(view, liveQuery.refetch, ledgerQuery.refetch, backtestQuery.refetch)} />
      ) : view === "live" ? (
        <LiveView
          snapshot={liveQuery.data}
          portfolioReport={portfolioBacktestQuery.data}
          loading={liveQuery.isLoading}
          traceDates={traceDatesQuery.data?.dates ?? []}
          selectedTraceDate={selectedTraceDate}
          traceDay={traceDayQuery.data}
          traceLoading={traceDatesQuery.isLoading || traceDayQuery.isLoading}
          traceError={firstError(traceDatesQuery.error, traceDayQuery.error)}
          onTraceDateChange={setSelectedTraceDate}
          onTraceRetry={() => void Promise.all([
            traceDatesQuery.refetch(),
            ...(selectedTraceDate ? [traceDayQuery.refetch()] : []),
          ])}
        />
      ) : view === "ledger" ? (
        <LedgerView ledger={ledgerQuery.data} loading={ledgerQuery.isLoading} />
      ) : (
        <BacktestView
          report={backtestQuery.data}
          loading={backtestQuery.isLoading}
          start={start}
          end={end}
          minimumDate={datesQuery.data?.start}
          maximumDate={datesQuery.data?.end}
          onStart={setStart}
          onEnd={setEnd}
          rebuildRunning={historyRebuildMutation.isPending || historyStatusQuery.data?.status === "building"}
          rebuildError={rebuildError ?? firstError(historyStatusQuery.error)}
          onRebuild={() => historyRebuildMutation.mutate()}
        />
      )}
      <StrategyGuideDialog
        open={guideOpen}
        onOpenChange={setGuideOpen}
        guide={strategyGuideQuery.data}
        loading={strategyGuideQuery.isLoading}
        error={firstError(strategyGuideQuery.error)}
        onRetry={() => void strategyGuideQuery.refetch()}
      />
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

interface LiveViewProps {
  snapshot?: LimitUpSignalSnapshot;
  portfolioReport?: LimitUpLaneBacktest;
  loading: boolean;
  traceDates: string[];
  selectedTraceDate: string;
  traceDay?: LimitUpLiveTraceDay;
  traceLoading: boolean;
  traceError: string | null;
  onTraceDateChange: (value: string) => void;
  onTraceRetry: () => void;
}

function LiveView({
  snapshot,
  portfolioReport,
  loading,
  traceDates,
  selectedTraceDate,
  traceDay,
  traceLoading,
  traceError,
  onTraceDateChange,
  onTraceRetry,
}: LiveViewProps) {
  const signals = useMemo(() => liveSignalsForScope(snapshot, "portfolio"), [snapshot]);
  const tracePanel = (
    <LiveTracePanel
      dates={traceDates}
      selectedDate={selectedTraceDate}
      day={traceDay}
      loading={traceLoading}
      error={traceError}
      onDateChange={onTraceDateChange}
      onRetry={onTraceRetry}
    />
  );
  if (loading && !snapshot) {
    return <section aria-label="实时推荐"><LoadingState rows={5} />{tracePanel}</section>;
  }
  if (!snapshot) {
    return <section aria-label="实时推荐"><EmptyRow text="当前没有实时快照" />{tracePanel}</section>;
  }
  const gate = snapshot.recommendations.market_gate;
  const planMode = isNextSessionPlan(snapshot);
  const header = liveHeader(snapshot);
  const plan = snapshot.recommendations.plan ?? snapshot.data_quality.plan;
  const buySignalCount = signals.length;
  const lunchPaused = snapshot.session_stage === "lunch";
  const waitingForRepair = gate.repair_state === "pending_repair";
  const repairRevoked = gate.repair_state === "repair_revoked";
  const schedule = snapshot.recommendations.execution_schedule;
  const afternoonEntryStart = schedule?.entry_windows[1]?.split("-")[0];
  const lunchMessage = afternoonEntryStart
    ? `午间休市：展示上午最后快照，${afternoonEntryStart}后恢复买入评估`
    : "午间休市：展示上午最后快照，等待下午恢复买入评估";
  return (
    <section aria-label="实时推荐">
      <LivePortfolioBacktestStrip report={portfolioReport} />
      {schedule && (
        <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b px-3 py-2 text-xs sm:px-4">
          <span className={schedule.entry_allowed ? "font-semibold text-rise" : "font-medium text-foreground"}>{schedule.message}</span>
          <span className="text-muted-foreground">推荐不限数量 · 两仓账户按排序执行 · D+1尾盘按官方收盘价卖出</span>
          {schedule.target_at && <span className="ml-auto text-muted-foreground">下一节点 {formatTime(schedule.target_at)}</span>}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span className={cn(
          planMode
            ? presentationToneClass(header.tone)
            : lunchPaused
              ? "text-amber-700 dark:text-amber-300"
              : gate.passed
                ? "text-rise"
                : waitingForRepair
                  ? "text-amber-700 dark:text-amber-300"
                  : "text-fall",
        )}>
          {planMode
            ? header.title
            : lunchPaused
              ? lunchMessage
              : gate.passed
                ? "市场允许出手"
                : waitingForRepair
                  ? `市场等待盘中修复${gate.reasons.length ? `：${gate.reasons.join("；")}` : ""}`
                  : repairRevoked
                    ? `市场修复已撤销${gate.repair_revoked_reason ? `：${gate.repair_revoked_reason}` : ""}`
                    : `市场门关闭${gate.reasons.length ? `：${gate.reasons.join("；")}` : ""}`}
        </span>
        {planMode && (
          <span className="text-muted-foreground">
            来源 {snapshot.source_trade_date ?? plan?.source_trade_date ?? snapshot.trade_date}
          </span>
        )}
        {!planMode && gate.repair_confirmed && (
          <span className="text-rise">
            分歧修复已确认{gate.repair_confirmed_at ? ` · ${formatTime(gate.repair_confirmed_at)}` : ""}
          </span>
        )}
        <span className="text-muted-foreground">
          {planMode ? `提前观察 ${signals.length}` : `正式买点 ${buySignalCount}`}
        </span>
        <span className="ml-auto text-muted-foreground">
          封板 {snapshot.market_context.sealed_count ?? 0} · 炸板 {snapshot.market_context.failed_count ?? 0} · {snapshot.source}
        </span>
      </div>
      {signals.length ? (
        <div className="divide-y">
          {signals.map((signal) => (
            <LiveSignalRow
              key={signal.vt_symbol}
              signal={signal}
              stale={snapshot.data_quality.is_stale}
              paused={lunchPaused}
            />
          ))}
        </div>
      ) : (
        <EmptyRow text={
          planMode
            ? "当前没有入选次交易时段的综合推荐观察候选"
            : "当前没有通过正式门禁的买点，保持现金"
        } />
      )}
      {tracePanel}
    </section>
  );
}

function LivePortfolioBacktestStrip({ report }: { report?: LimitUpLaneBacktest }) {
  const cashSummary = report?.summary;
  const qualitySummary = report?.recommendation_quality?.summary ?? report?.signal_summary;
  const proxyOnly = report?.execution_comparability?.live_equivalent === false;
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-x-5 gap-y-1 border-b px-3 py-2 text-xs tabular-nums sm:px-4">
      <span className="font-medium text-foreground">全量推荐质量</span>
      {cashSummary && qualitySummary ? (
        <>
          <span className="text-muted-foreground">独立闭合 {qualitySummary.trade_count} / {qualitySummary.signal_count}</span>
          <span className={rateTone(qualitySummary.win_rate)}>胜率 {formatPct(qualitySummary.win_rate)}</span>
          <span className={amountTone(qualitySummary.average_return_pct)}>平均 D+1 {formatPct(qualitySummary.average_return_pct)}</span>
          <span className={amountTone(qualitySummary.total_return_pct)}>逐日等权复利 {formatPct(qualitySummary.total_return_pct)}</span>
          <span className={amountTone(cashSummary.total_return_pct)}>两仓复利 {formatPct(cashSummary.total_return_pct)}</span>
          <span className="text-fall">两仓回撤 {formatPct(cashSummary.max_drawdown_pct)}</span>
          {proxyOnly && (
            <span className="text-amber-700 dark:text-amber-300" title={report?.execution_comparability?.reason}>
              候选代理 · 非实盘等价
            </span>
          )}
        </>
      ) : (
        <span className="text-muted-foreground">历史组合缓存读取中</span>
      )}
    </div>
  );
}

function LiveSignalRow({ signal, stale, paused }: { signal: LimitUpLiveSignal; stale: boolean; paused: boolean }) {
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
    ? `${signal.concept_name} · 强度${signal.concept_strength_rank ?? "-"} · ${signal.concept_strong_5_count ?? 0}只涨超5% · 概念龙${signal.concept_leader_rank ?? "-"}`
    : "概念共振待确认";
  const conceptDegraded = (
    (signal.concept_snapshot_age_seconds ?? 0) > 45
    || (signal.concept_coverage_ratio ?? 1) < 0.9
  );
  return (
    <article className={cn("border-l-2 px-3 py-3 sm:px-4", actionable ? "border-l-rise" : observation ? "border-l-amber-500" : "border-l-border")}>
      <div className="grid gap-3 lg:grid-cols-[minmax(180px,1.1fr)_minmax(160px,0.8fr)_minmax(300px,1.8fr)_minmax(150px,0.8fr)] lg:items-center">
        <div className="min-w-0">
          <StockIdentityLink
            name={signal.name}
            vtSymbol={signal.vt_symbol}
            meta={`${signal.concept_name ?? signal.sector_name ?? "板块待确认"} · 概念龙${signal.concept_leader_rank ?? "-"} · 市场${signal.market_dragon_rank ?? "-"}`}
          />
        </div>
        <div>
          <div className={cn("text-sm font-semibold", presentationToneClass(state.tone))}>{state.label}</div>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-xs tabular-nums">
            <span className={cn("font-semibold", amountTone(signal.change_pct))}>
              现涨 {formatSignedPct(signal.change_pct)}
            </span>
            <span className="text-foreground">现价 {formatPrice(signal.last_price)}</span>
            <span className="text-muted-foreground">距板 {formatPct(signal.distance_to_limit_pct)}</span>
          </div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {entryKindLabel(signal.entry_kind)} · 触发价 {formatPrice(signal.trigger_price)}
            {signal.board_lane === "first_board" && signal.lane_support_score != null
              ? ` · 动能 ${formatNumber(signal.lane_support_score, 1)}`
              : ""}
            {signal.board_lane === "two_to_three" ? ` · ${twoToThreeQualityLabel(signal.lane_quality_tier, signal.lane_risk_count)}` : ""}
            {signal.state_updated_at ? ` · ${formatTime(signal.state_updated_at)}` : ""}
          </div>
        </div>
        <div className="min-w-0 text-xs leading-5">
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
            <div className="text-amber-700 dark:text-amber-300">
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
          <div className="text-muted-foreground">买入：{signal.buy_instruction ?? signal.buy_condition ?? "条件待确认"}</div>
          <div className="text-muted-foreground">卖出：{signal.sell_instruction ?? signal.sell_condition ?? "D+1尾盘按官方收盘价统一卖出"}</div>
          <div className="text-muted-foreground">取消：{signal.cancel_checks?.join("；") ?? signal.cancel_condition}</div>
          <div className="text-muted-foreground">盘口：换手 {formatPct(signal.turnover_rate)} · 封单 {formatAmount(signal.seal_amount)}</div>
        </div>
        <div className="grid grid-cols-2 gap-x-3 text-xs tabular-nums">
          {signal.board_lane === "first_board" ? (
            <>
              <Metric label="个股联合率" value={formatPct(stockEvidence?.historical_win_rate)} tone={rateTone(stockEvidence?.historical_win_rate)} />
              <Metric label={`同股D+1 (${stockEvidence?.d1_money_effect_sample_count ?? 0})`} value={formatPct(stockEvidence?.d1_money_effect_win_rate)} tone={rateTone(stockEvidence?.d1_money_effect_win_rate)} />
              <Metric label={`126日封停 (${stockEvidence?.seal_sample_count ?? 0})`} value={formatPct(stockEvidence?.seal_success_rate)} tone={rateTone(stockEvidence?.seal_success_rate)} />
              <Metric label="同股D+1平均" value={formatPct(stockEvidence?.d1_money_effect_average_return_pct)} tone={amountTone(stockEvidence?.d1_money_effect_average_return_pct)} />
            </>
          ) : (
            <>
              <Metric label="TBOX" value={formatNumber(signal.historical_evidence?.tbox_score, 1)} tone={tboxTone(signal.historical_evidence?.tbox_score)} />
              <Metric label="历史胜率" value={formatPct(signal.historical_evidence?.smoothed_win_rate)} tone={rateTone(signal.historical_evidence?.smoothed_win_rate)} />
              <Metric label="平均 D+1" value={formatPct(signal.historical_evidence?.average_return_pct)} tone={amountTone(signal.historical_evidence?.average_return_pct)} />
              <Metric label="战法复利" value={formatPct(signal.strategy_evidence?.total_return_pct)} tone={amountTone(signal.strategy_evidence?.total_return_pct)} />
            </>
          )}
        </div>
      </div>
    </article>
  );
}

interface LiveTracePanelProps {
  dates: string[];
  selectedDate: string;
  day?: LimitUpLiveTraceDay;
  loading: boolean;
  error: string | null;
  onDateChange: (value: string) => void;
  onRetry: () => void;
}

function LiveTracePanel({
  dates,
  selectedDate,
  day,
  loading,
  error,
  onDateChange,
  onRetry,
}: LiveTracePanelProps) {
  const items = useMemo(() => {
    const scoped = (day?.items ?? []).filter(
      (item) => item.board_lane === "first_board" || item.board_lane === "two_to_three",
    );
    return sortLiveTraceItems(scoped);
  }, [day?.items]);
  const funnel = day?.lane_funnels?.first_board;
  const funnelSummary = funnel ? liveTraceFunnelSummary(funnel) : null;

  return (
    <section className="border-t-4 border-double" aria-label="最近两交易日推荐轨迹">
      <div className="flex flex-wrap items-center gap-3 border-b px-3 py-2 sm:px-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">当日轨迹</h2>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {day
              ? `${items.length} 只 · ${day.snapshot_count ?? 0} 次扫描${day.scan_error_count ? ` · ${day.scan_error_count} 次异常` : ""}`
              : "保留推荐消失、买点触发、封板和炸板过程"}
          </p>
        </div>
        <div className="ml-auto flex w-full min-w-0 border sm:w-auto" role="tablist" aria-label="轨迹交易日">
          {dates.slice(0, 2).map((tradeDate, index) => (
            <button
              key={tradeDate}
              type="button"
              role="tab"
              aria-selected={tradeDate === selectedDate}
              className={cn(
                "min-h-9 min-w-0 flex-1 border-r px-3 text-xs last:border-r-0 sm:min-w-[124px] sm:flex-none",
                tradeDate === selectedDate
                  ? "bg-foreground font-semibold text-background"
                  : "bg-background text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
              onClick={() => onDateChange(tradeDate)}
            >
              <span>{index === 0 ? latestTraceDateLabel(tradeDate) : "上一交易日"}</span>
              <span className="ml-1 tabular-nums opacity-75">{formatShortDate(tradeDate)}</span>
            </button>
          ))}
        </div>
      </div>

      {funnelSummary && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
          <span className="font-medium text-foreground">首板漏斗</span>
          {funnelSummary.stages.map((stage, index) => (
            <span
              key={stage}
              className={index === 3 && funnel?.triggered_count === 0 ? "font-medium text-fall" : "text-muted-foreground"}
            >
              {stage}
            </span>
          ))}
          <span className="sm:ml-auto text-amber-700 dark:text-amber-300">{funnelSummary.blockers}</span>
        </div>
      )}

      {error ? (
        <div className="flex min-h-16 items-center gap-3 border-b px-3 py-3 text-xs text-fall sm:px-4">
          <CircleAlert size={15} className="shrink-0" />
          <span className="min-w-0 flex-1 break-words">轨迹缓存读取失败：{error}</span>
          <Button type="button" size="icon" variant="outline" className="h-8 w-8 shrink-0" title="重试轨迹查询" onClick={onRetry}>
            <RefreshCw size={14} />
          </Button>
        </div>
      ) : loading && !day ? (
        <LoadingState rows={3} />
      ) : dates.length === 0 ? (
        <EmptyRow text="最近两个交易日尚无诊断扫描" />
      ) : items.length === 0 ? (
        <EmptyRow text={`${selectedDate || "所选交易日"} 当前板位没有进入 5% 预热雷达的股票`} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1040px] table-fixed text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="w-10 px-2 py-2" aria-label="展开轨迹" />
                <th className="w-44 px-2 py-2 text-left">股票</th>
                <th className="w-20 px-2 py-2 text-left">板位</th>
                <th className="w-24 px-2 py-2 text-left">首次发现</th>
                <th className="w-40 px-2 py-2 text-left">最高状态</th>
                <th className="w-40 px-2 py-2 text-left">最终状态</th>
                <th className="w-28 px-2 py-2 text-right">最后盘口</th>
                <th className="px-2 py-2 text-left">最后说明</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {items.map((item) => (
                <LiveTraceRow
                  key={`${selectedDate}:${item.vt_symbol}`}
                  tradeDate={selectedDate}
                  item={item}
                  latest={selectedDate === dates[0]}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LiveTraceRow({
  tradeDate,
  item,
  latest,
}: {
  tradeDate: string;
  item: LimitUpLiveTraceItem;
  latest: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const eventsQuery = useQuery({
    queryKey: ["limitUpLiveTraceSymbol", tradeDate, item.vt_symbol],
    queryFn: () => fetchLimitUpLiveTraceSymbol({ date: tradeDate, vtSymbol: item.vt_symbol }),
    enabled: expanded,
    staleTime: latest ? 8_000 : Infinity,
    refetchInterval: expanded && latest ? 10_000 : false,
    refetchOnWindowFocus: expanded && latest,
  });

  return (
    <>
      <tr className={cn(item.final_state === "trigger_ready" && "bg-rise/5")}>
        <td className="px-2 py-2 align-middle">
          <button
            type="button"
            className="flex h-7 w-7 items-center justify-center text-muted-foreground hover:bg-muted hover:text-foreground"
            title={expanded ? "收起逐次轨迹" : "展开逐次轨迹"}
            aria-label={expanded ? `收起 ${item.name} 逐次轨迹` : `展开 ${item.name} 逐次轨迹`}
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </button>
        </td>
        <td className="px-2 py-2">
          <StockIdentityLink
            name={item.name || item.vt_symbol}
            vtSymbol={item.vt_symbol}
            meta={`${item.event_count} 次变化 · 最后 ${formatTime(item.last_seen_at)}`}
          />
        </td>
        <td className="px-2 py-2 text-xs">{item.board_lane ? limitUpLaneLabel(item.board_lane) : `第${item.board_level ?? "-"}板`}</td>
        <td className="px-2 py-2 text-xs tabular-nums">
          <div>{formatTime(item.first_seen_at)}</div>
          <div className="text-muted-foreground">首次进入雷达</div>
        </td>
        <td className={cn("px-2 py-2 text-xs font-medium", liveTraceTone(item.highest_state))}>
          <div>{liveTraceStatusLabel(item.highest_state)}</div>
          {item.triggered_at && <div className="mt-0.5 font-normal tabular-nums text-muted-foreground">触发 {formatTime(item.triggered_at)}</div>}
        </td>
        <td className={cn("px-2 py-2 text-xs font-medium", liveTraceTone(item.final_state))}>
          {liveTraceStatusLabel(item.final_state)}
        </td>
        <td className="px-2 py-2 text-right text-xs tabular-nums">
          <div>{formatPrice(item.last_price)}</div>
          <div className={amountTone(item.change_pct)}>{formatPct(item.change_pct)}</div>
        </td>
        <td className="px-2 py-2 text-xs leading-5 text-muted-foreground">
          <span className="line-clamp-2" title={item.reason}>{item.reason || "等待下一次状态变化"}</span>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} className="border-t bg-muted/10 p-0">
            <LiveTraceEvents
              events={eventsQuery.data?.events}
              loading={eventsQuery.isLoading}
              error={firstError(eventsQuery.error)}
              onRetry={() => void eventsQuery.refetch()}
            />
          </td>
        </tr>
      )}
    </>
  );
}

function LiveTraceEvents({
  events,
  loading,
  error,
  onRetry,
}: {
  events?: LimitUpLiveTraceEvent[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  if (loading && !events) return <LoadingState rows={2} />;
  if (error) {
    return (
      <div className="flex min-h-12 items-center gap-3 px-12 py-2 text-xs text-fall">
        <span className="flex-1">逐次轨迹读取失败：{error}</span>
        <Button type="button" size="icon" variant="outline" className="h-7 w-7" title="重试逐次轨迹" onClick={onRetry}>
          <RefreshCw size={13} />
        </Button>
      </div>
    );
  }
  if (!events?.length) return <div className="px-12 py-3 text-xs text-muted-foreground">没有可展示的状态变化</div>;

  return (
    <ol className="divide-y px-10">
      {events.map((event, index) => {
        const evidence = traceEventEvidence(event);
        return (
          <li
            key={`${event.captured_at}:${event.event}:${index}`}
            className="grid grid-cols-[80px_150px_110px_minmax(0,1fr)] gap-3 px-2 py-2 text-xs leading-5"
          >
            <time className="tabular-nums text-muted-foreground">{formatTime(event.captured_at)}</time>
            <span className={cn("font-medium", liveTraceTone(event.event))}>{liveTraceStatusLabel(event.event)}</span>
            <span className="text-right tabular-nums">
              {formatPrice(event.last_price)}
              {event.change_pct != null ? ` · ${formatPct(event.change_pct)}` : ""}
            </span>
            <span className="min-w-0 text-muted-foreground">
              <span className="text-foreground">{event.reason || "状态发生变化"}</span>
              {evidence ? ` · ${evidence}` : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function traceEventEvidence(event: LimitUpLiveTraceEvent): string {
  const evidence = [
    ...event.pending_reasons,
    ...event.blockers.map(blockerLabel),
    ...(event.market_gate_passed ? [] : event.market_gate_reasons),
    ...event.trigger_checks
      .filter((check) => check.status === "pending" || check.status === "failed")
      .map((check) => `${check.label}${check.observed ? ` ${check.observed}` : ""}${check.required ? `（要求 ${check.required}）` : ""}`),
  ].filter((value) => value && !event.reason.includes(value));
  if (event.market_repair_state === "pending_repair") {
    evidence.push("市场修复待确认");
  } else if (event.market_repair_state === "repair_confirmed") {
    evidence.push(`市场修复已确认${event.market_repair_confirmed_at ? ` ${formatTime(event.market_repair_confirmed_at)}` : ""}`);
  } else if (event.market_repair_state === "repair_revoked") {
    evidence.push("市场修复已撤销");
  }
  if (event.concept_name) {
    evidence.push(
      `${event.concept_name} 强度${event.concept_strength_rank ?? "-"} · ${event.concept_strong_5_count ?? 0}只涨超5% · 概念龙${event.concept_leader_rank ?? "-"}`,
    );
  }
  if (event.sector_heat != null) evidence.push(`D-1行业热度 ${formatNumber(event.sector_heat, 1)}`);
  if (event.sector_touch_count != null) evidence.push(`板块触板 ${event.sector_touch_count}只`);
  if (event.sector_main_net_inflow != null) evidence.push(`板块资金 ${formatAmount(event.sector_main_net_inflow)}`);
  if (event.stock_main_net_inflow != null) evidence.push(`个股资金 ${formatAmount(event.stock_main_net_inflow)}`);
  if (event.turnover_rate != null) evidence.push(`换手 ${formatPct(event.turnover_rate)}`);
  if (event.seal_amount != null) evidence.push(`封单 ${formatAmount(event.seal_amount)}`);
  if (event.seal_amount_retention_ratio != null) {
    evidence.push(`封单保留 ${formatPct(event.seal_amount_retention_ratio * 100)}`);
  }
  if (event.seal_amount_change_pct != null) evidence.push(`封单变化 ${formatPct(event.seal_amount_change_pct)}`);
  if (event.data_quality_status && event.data_quality_status !== "ready") {
    evidence.push(`数据状态 ${event.data_quality_status}`);
  }
  return [...new Set(evidence)].join("；");
}

function blockerLabel(value: string): string {
  return ({
    high_board_prior_divergence_missing: "高板缺少前日分歧回封",
    high_board_not_sector_core: "高板不是板块龙一",
    high_board_requires_l2: "高板盘中接力缺少 L2 队列证据",
    limit_up_gene_missing: "半年内缺少涨停基因",
    first_board_touch_gene_weak: "半年触板不足 6 次",
    financial_report_unavailable: "本地财报数据未覆盖",
    first_board_profit_growth_weak: "点时净利润同比低于 10%",
    first_board_repair_setup_missing: "D-1 分歧修复条件未成立",
    low_position_missing: "不属于低位或充分回调后的首次涨停",
    first_touch_too_early: "10 点前仅观察，等待 10 点后确认",
    industry_heat_unavailable: "缺少实时板块热度",
    intraday_support_unavailable: "缺少信号时点盘中承接路径",
    intraday_support_breakdown: "临近触板路径失速或回落",
    first_board_local_setup_unconfirmed: "触板前承接结构未确认",
    first_board_quality_below_threshold: "首板综合质量分不足",
    intraday_support_out_of_range: "盘中承接区间未通过",
    auction_gap_out_of_range: "竞价强度不在战法区间",
    third_board_setup_unconfirmed: "三板分歧转强结构未确认",
    two_to_three_risk_stack: "二进三可见风险达到 4 项",
    fundamental_risk: "已披露基本面风险未通过",
    lane_features_unavailable: "战法前置证据未就绪",
    prior_board_evidence_missing: "缺少前一板盘口证据",
    prior_board_path_incomplete: "前一板首封、开板或回封证据不完整",
    industry_leader_rank_unverified: "行业龙位未确认",
    stock_not_industry_top2: "不属于行业龙一或龙二",
  } as Record<string, string>)[value] ?? value;
}

function liveTraceTone(state: LimitUpLiveTraceState): string {
  if (state === "trigger_ready") return "text-rise";
  if (state === "concept_warming" || state === "approaching_trigger" || state === "missed" || state === "sealed" || state === "resealed") {
    return "text-amber-700 dark:text-amber-300";
  }
  if (state === "failed" || state === "rejected" || state === "invalidated") return "text-fall";
  return "text-muted-foreground";
}

function latestTraceDateLabel(tradeDate: string): string {
  return tradeDate === shanghaiDate(new Date()) ? "今天" : "最近交易日";
}

function shanghaiDate(value: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(value);
}

function formatShortDate(value: string): string {
  return value.length >= 10 ? value.slice(5) : value;
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
            : `连续评估交割 ${ledger.selected_count} 只 · D+1尾盘按官方收盘价卖出`}
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
      <td className="px-3 py-3 text-xs tabular-nums"><div>{trade.sell_date ?? "待 D+1"} {trade.sell_time ?? ""}</div><div className="text-muted-foreground">{formatPrice(trade.sell_price)} · 官方收盘价</div></td>
      <td className={cn("px-3 py-3 text-xs font-medium", trade.d_board_status === "sealed" ? "text-rise" : "text-fall")}>{boardStatusLabel(trade.d_board_status)}</td>
      <td className="px-3 py-3 text-xs">{d1OutcomeLabel(trade.d1_outcome)}</td>
      <td className={cn("px-3 py-3 text-right font-semibold tabular-nums", amountTone(trade.return_pct))}>{formatPct(trade.return_pct)}</td>
      <td className="max-w-[360px] px-3 py-3 text-xs leading-5 text-muted-foreground">{setups && <div className="text-foreground">{setups}</div>}{trade.favorable_factors?.map(factorLabel).join("；") || "无可执行证据"}</td>
    </tr>
  );
}

interface BacktestViewProps {
  report?: LimitUpLaneBacktest;
  loading: boolean;
  start: string;
  end: string;
  minimumDate?: string | null;
  maximumDate?: string | null;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
  rebuildRunning: boolean;
  rebuildError: string | null;
  onRebuild: () => void;
}

function BacktestView({
  report,
  loading,
  start,
  end,
  minimumDate,
  maximumDate,
  onStart,
  onEnd,
  rebuildRunning,
  rebuildError,
  onRebuild,
}: BacktestViewProps) {
  if (loading && !report) return <LoadingState rows={7} />;
  const summary = report?.summary;
  return (
    <section aria-label="真实现金回测">
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-3 sm:px-4">
        <DateInput label="开始" value={start} min={minimumDate} max={maximumDate} onChange={onStart} />
        <DateInput label="结束" value={end} min={minimumDate} max={maximumDate} onChange={onEnd} />
        <div className="h-9 border bg-muted/20 px-3 text-xs leading-9 text-muted-foreground">双窗口买入 / D+1收盘</div>
        <BacktestRebuildControl running={rebuildRunning} error={rebuildError} onRebuild={onRebuild} />
        <div className="ml-auto pb-1 text-xs tabular-nums text-muted-foreground">
          10 万元 · 两仓各 50% · 100 股整数手 · 含费用滑点
        </div>
      </div>

      <div className="grid grid-cols-2 border-b sm:grid-cols-3 xl:grid-cols-6">
        <SummaryCell label="期末权益" value={formatCurrency(summary?.final_equity)} detail={`初始 ${formatCurrency(summary?.initial_cash)}`} />
        <SummaryCell label="账户复利" value={formatPct(summary?.total_return_pct)} tone={amountTone(summary?.total_return_pct)} detail={`费用 ${formatCurrency(summary?.total_fees)}`} />
        <SummaryCell label="成交胜率" value={formatPct(summary?.win_rate)} tone={rateTone(summary?.win_rate)} detail={`闭合 ${summary?.trade_count ?? 0} · 未平 ${summary?.open_position_count ?? 0}`} />
        <SummaryCell label="最大回撤" value={formatPct(summary?.max_drawdown_pct)} tone="text-fall" />
        <SummaryCell label="平均仓位" value={formatPct(summary?.average_utilization_pct)} detail={`峰值 ${formatPct(summary?.peak_utilization_pct)}`} />
        <SummaryCell label="跳过信号" value={String(summary?.skipped_count ?? 0)} detail={`实际买入 ${summary?.buy_count ?? 0}`} />
      </div>

      {report && <SignalSummaryStrip report={report} />}
      {report && (
        <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">
          买入 {report.execution_schedule?.entry_windows.join(" / ") ?? "连续盘中"} · D+1 {report.execution_schedule?.exit_time ?? "15:00"} 收盘卖出 ·
          官方收盘价 {report.coverage.daily_close_count ?? 0} · 缺失剔除 {report.coverage.daily_close_missing_count ?? 0}
          {report.execution_comparability?.live_equivalent === false && (
            <span className="ml-3 text-amber-700 dark:text-amber-300" title={report.execution_comparability.reason}>
              候选代理，盘中资金门未历史重放
            </span>
          )}
        </div>
      )}
      {report?.lane === "portfolio" ? (
        <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">首板 + 二进三 · 按到达时间成交 · 两仓各 50% · 不预留仓位</div>
      ) : null}
      {report && <RobustnessStrip report={report} />}
      {report && <ValidationStrip report={report} />}
      {report?.daily_results.length ? <EquityChart report={report} /> : <EmptyRow text="当前范围没有账户权益记录" />}
      {report && <BacktestTrades report={report} />}
      {report && <SkippedOrders report={report} />}
    </section>
  );
}

function RobustnessStrip({ report }: { report: LimitUpLaneBacktest }) {
  const doubleCost = report.stress_tests?.double_cost;
  const sizing = report.position_sizing_audit;
  if (!doubleCost && !sizing) return null;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
      <span className="font-medium text-foreground">压力测试</span>
      {doubleCost && <span className={amountTone(doubleCost.total_return_pct)}>双倍成本 {formatPct(doubleCost.total_return_pct)}</span>}
      {sizing && (
        <span className="text-muted-foreground">
          开发期选择 {sizing.selected_max_positions} 仓 · 单仓回撤 {formatPct(sizing.development_variants["1"]?.max_drawdown_pct)} · 后段只验证
        </span>
      )}
    </div>
  );
}

function SignalSummaryStrip({ report }: { report: LimitUpLaneBacktest }) {
  const quality = report.recommendation_quality;
  const summary = quality?.summary ?? report.signal_summary;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
      <span className="font-medium text-foreground">全量推荐质量</span>
      <span className="text-muted-foreground">独立闭合 {summary.trade_count} / {summary.signal_count}</span>
      <span className="text-muted-foreground">胜率 {formatPct(summary.win_rate)}</span>
      <span className="text-muted-foreground">平均 D+1 净收益 {formatPct(summary.average_return_pct)}</span>
      <span className="text-muted-foreground">逐日等权复利 {formatPct(summary.total_return_pct)}</span>
      {quality && (
        <span className="text-muted-foreground">标准槽位 {formatCurrency(quality.standard_slot_cash)} · 不受共享仓位限制</span>
      )}
    </div>
  );
}

function ValidationStrip({ report }: { report: LimitUpLaneBacktest }) {
  return (
    <div className="grid border-b lg:grid-cols-[180px_repeat(3,minmax(0,1fr))]">
      <div className="border-b px-3 py-3 lg:border-b-0 lg:border-r sm:px-4">
        <div className={cn("text-sm font-semibold", report.validation.passed ? "text-rise" : "text-fall")}>{report.validation.passed ? "验证通过" : "研究账户，人工确认"}</div>
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
              <td className="px-3 py-3 text-xs tabular-nums"><div>{trade.buy_date} {trade.buy_time}</div><div className="text-muted-foreground">{trade.sell_date} {trade.sell_time} · {exitReasonLabel(trade.exit_reason)}{trade.exit_price_proxy ? " · 收盘代理" : ""}</div></td>
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
              <td className="px-3 py-3 text-xs">{limitUpLaneLabel(order.lane)}</td>
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

function SummaryCell({ label, value, tone, detail }: { label: string; value: string; tone?: string; detail?: string }) {
  return <div className="min-w-0 border-b border-r px-3 py-2.5 last:border-r-0 xl:border-b-0"><div className="text-[11px] text-muted-foreground">{label}</div><div className={cn("mt-0.5 truncate text-sm font-semibold tabular-nums", tone)}>{value}</div>{detail && <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{detail}</div>}</div>;
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-4 py-16 text-center text-sm text-muted-foreground">{text}</div>;
}

function presentationToneClass(tone: PresentationTone) { return ({ positive: "text-rise", warning: "text-amber-700 dark:text-amber-300", negative: "text-fall", neutral: "text-foreground" } as Record<PresentationTone, string>)[tone]; }
function entryKindLabel(value: string) { return (({ none: "不执行", auction: "竞价", momentum: "动能", sweep: "扫板", reseal: "回封", tail_seal: "尾盘封板", next_auction: "竞价接力", first_touch: "首次触板", intraday: "盘中", wait: "等待确认" } as Record<string, string>)[value] ?? value) || "--"; }
function sectorRouteLabel(value: string) { return ({ realtime_industry: "盘中行业", realtime_concept_launch: "概念启动" } as Record<string, string>)[value] ?? value; }
function phaseLabel(value?: string) { return ({ warmup: "预热期", earlier_history: "更早历史稳健性", design_sample: "前段设计样本", time_validation: "后段时间验证", expanding_oos: "滚动样本外", locked_holdout: "锁定留出", post_freeze_forward: "冻结后前向" } as Record<string, string>)[value ?? ""] ?? value ?? "阶段未知"; }
function d1OutcomeLabel(value: string) { return ({ continuation_limit_up: "D+1 连板", next_limit_up_after_failed_board: "D+1 涨停", d1_premium: "D+1 有溢价", direct_breakdown: "D+1 直接砸", no_premium: "D+1 无溢价", awaiting_d1_bar: "待 D+1" } as Record<string, string>)[value] ?? value; }
function boardStatusLabel(value: string) { return ({ sealed: "封住", failed: "触板后炸板", no_limit: "未触板" } as Record<string, string>)[value] ?? value; }
function exitReasonLabel(value: string) { return ({ dynamic_auction_exit: "动态竞价兑现", dynamic_tail_exit: "动态尾盘退出", planned_open: "开盘退出", planned_close: "收盘退出", planned_1430: "14:30退出", emergency_close: "开盘未成后收盘退出", retry_open: "延期至开盘退出", retry_close: "延期至收盘退出" } as Record<string, string>)[value] ?? value; }
function setupTagLabel(value: string) { return ({ weak_market_theme_attack: "弱市题材进攻", sandwich_board: "夹板", return_board: "回马板", weak_to_strong_breakout: "弱转强突破", dragon_first_negative_relay: "龙首阴接力", dragon_weak_to_strong: "龙头弱转强", anti_nuclear_board: "反核板" } as Record<string, string>)[value] ?? value; }
function skipReasonLabel(value: string) { return ({ position_limit: "持仓已满", insufficient_cash: "现金不足", below_one_lot: "目标仓位不足一手", duplicate_position: "已有同股持仓", invalid_entry_price: "买入价无效" } as Record<string, string>)[value] ?? value; }
function twoToThreeQualityLabel(tier?: "A" | "B" | null, riskCount?: number | null) { const quality = tier ?? "B"; const risks = riskCount ?? 0; return `${quality}级${risks > 0 ? ` · 风险${risks}` : ""}`; }
function twoToThreeRiskTitle(flags?: string[]) { return (flags ?? []).map((flag) => ({ auction_gap_outside_core: "竞价不在2%-5%核心区", prior_turnover_outside_core: "前板换手不在10%-20%核心区", prior_amount_ratio_outside_core: "前板量能比不在1.2-2", financial_snapshot_missing: "财报快照缺失", prior_low_below_zero: "前板最低价翻绿或缺失", prior_market_failed_rate_high: "前日炸板率偏高或缺失" } as Record<string, string>)[flag] ?? flag).join("；"); }
function factorLabel(value: string) {
  return ({
    weak_market_theme_attack_setup: "强题材龙一/龙二承接",
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
      "weak_market_theme_attack_setup",
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
function formatSignedPct(value?: number | null) { return value == null || !Number.isFinite(value) ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`; }
function formatNumber(value?: number | null, digits = 2) { return value == null || !Number.isFinite(value) ? "--" : value.toFixed(digits); }
function formatPrice(value?: number | null) { return value == null || !Number.isFinite(value) ? "--" : `¥${value.toFixed(2)}`; }
function formatCurrency(value?: number | null) { if (value == null || !Number.isFinite(value)) return "--"; const sign = value < 0 ? "-" : ""; return `${sign}¥${Math.abs(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
function formatAmount(value?: number | null) { if (value == null || !Number.isFinite(value)) return "--"; const absolute = Math.abs(value); if (absolute >= 1e8) return `${(value / 1e8).toFixed(2)}亿`; if (absolute >= 1e4) return `${(value / 1e4).toFixed(0)}万`; return value.toFixed(0); }
function formatTime(value: string) { try { return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Shanghai", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(value)); } catch { return value.slice(11, 19); } }
function formatAge(seconds: number) { return seconds < 60 ? `${seconds}秒` : `${Math.floor(seconds / 60)}分${seconds % 60}秒`; }
function amountTone(value?: number | null) { return value == null || !Number.isFinite(value) ? "text-muted-foreground" : value >= 0 ? "text-rise" : "text-fall"; }
function buyAlertPermissionDescription(permission: BuyAlertPermission) { return ({ granted: "声音和桌面通知均已启用", denied: "声音已启用；浏览器已拒绝桌面通知", default: "声音已启用；桌面通知尚未授权", unsupported: "声音已启用；当前浏览器不支持桌面通知" } as Record<BuyAlertPermission, string>)[permission]; }
function rateTone(value?: number | null) { return value == null ? "text-muted-foreground" : value >= 50 ? "text-rise" : "text-fall"; }
function tboxTone(value?: number | null) { return value == null ? "text-muted-foreground" : value >= 60 ? "text-rise" : value >= 40 ? "text-amber-700 dark:text-amber-300" : "text-fall"; }
function firstError(...values: unknown[]) { const error = values.find(Boolean); return error instanceof Error ? error.message : error ? "打板数据加载失败" : null; }
async function refreshActive(view: PrimaryView, live: () => Promise<unknown>, ledger: () => Promise<unknown>, backtest: () => Promise<unknown>) { if (view === "live") await live(); else if (view === "ledger") await ledger(); else await backtest(); }
