import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  Bell,
  BellRing,
  BookOpenText,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  Clock3,
  RefreshCw,
  ReceiptText,
  Volume2,
} from "lucide-react";
import {
  CartesianGrid,
  Legend,
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
  fetchLimitUpRadarValidation,
  fetchLimitUpStrategyGuide,
  startLimitUpHistoryRebuild,
  type LimitUpHistoryRebuildStatus,
  type LimitUpLaneBacktest,
  type LimitUpLiveTraceDay,
  type LimitUpLiveTraceEvent,
  type LimitUpLiveTraceItem,
  type LimitUpLiveTraceState,
  type LimitUpSignalSnapshot,
} from "@/api/limitUp";
import { fetchIndexBars } from "@/api/indices";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { BacktestRebuildControl } from "@/features/limitUp/BacktestRebuildControl";
import { BacktestDrawdownPanel } from "@/features/limitUp/BacktestDrawdownPanel";
import { BuyAlertBanner, alertBannerLocate } from "@/features/limitUp/BuyAlertBanner";
import { GuideView } from "@/features/limitUp/GuideView";
import { LedgerTimeline } from "@/features/limitUp/LedgerTimeline";
import { LiveSignalCard } from "@/features/limitUp/LiveSignalCard";
import { OpsFlowRail } from "@/features/limitUp/OpsFlowRail";
import { buildBacktestChartPoints } from "@/features/limitUp/backtestChart";
import {
  amountTone,
  boardStatusLabel,
  d1OutcomeLabel,
  exitReasonLabel,
  formatAge,
  formatAmount,
  formatCurrency,
  formatNumber,
  formatPct,
  formatPrice,
  formatTime,
  phaseLabel,
  rateTone,
  skipReasonLabel,
} from "@/features/limitUp/liveFormat";
import {
  isNextSessionPlan,
  liveHeader,
} from "@/features/limitUp/nextSessionPlan";
import {
  liveSignalsForScope,
} from "@/features/limitUp/livePortfolio";
import {
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

type PrimaryView = "live" | "ledger" | "backtest" | "guide";

const PRIMARY_VIEWS: Array<{ value: PrimaryView; label: string; icon: typeof Activity }> = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "guide", label: "规则说明", icon: BookOpenText },
];

const LEDGER_TIMELINE_PAGE = 10;
const SHANGHAI_INDEX_SYMBOL = "000001.SSE";

export function LimitUpPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const rebuildObservedStatus = useRef<string | null>(null);
  const [view, setView] = useState<PrimaryView>("live");
  const [timelineCount, setTimelineCount] = useState(LEDGER_TIMELINE_PAGE);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rebuildError, setRebuildError] = useState<string | null>(null);

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
    enabled: view === "guide",
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const radarValidationQuery = useQuery({
    queryKey: ["limitUpRadarValidation"],
    queryFn: fetchLimitUpRadarValidation,
    enabled: view === "guide",
    staleTime: 60_000,
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
  const [selectedTraceDate, setSelectedTraceDate] = useState("");
  const traceDayQuery = useQuery({
    queryKey: ["limitUpLiveTraceDay", selectedTraceDate],
    queryFn: () => fetchLimitUpLiveTraceDay(selectedTraceDate),
    enabled: view === "live" && Boolean(selectedTraceDate),
    staleTime: selectedTraceDate === traceDatesQuery.data?.latest ? 8_000 : Infinity,
    refetchInterval: view === "live" && selectedTraceDate === traceDatesQuery.data?.latest ? 10_000 : false,
    refetchOnWindowFocus: selectedTraceDate === traceDatesQuery.data?.latest,
  });
  const dates = datesQuery.data?.dates ?? [];
  const timelineDates = useMemo(
    () => dates.slice(-timelineCount).reverse(),
    [dates, timelineCount],
  );
  const ledgerTimelineQueries = useQueries({
    queries: timelineDates.map((date) => ({
      queryKey: ["limitUpScheduledLedger", date],
      queryFn: () => fetchLimitUpHistoryLedger({ date }),
      enabled: view === "ledger",
      staleTime: Infinity,
      refetchOnWindowFocus: false,
    })),
  });
  const backtestQuery = useQuery({
    queryKey: ["limitUpLaneBacktest", start, end, "portfolio"],
    queryFn: () => fetchLimitUpLaneBacktest({
      start: start === datesQuery.data?.start ? undefined : start,
      end: end === datesQuery.data?.end ? undefined : end,
      lane: "portfolio",
    }),
    enabled: (view === "backtest" || view === "live") && Boolean(start && end),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const indexBarsQuery = useQuery({
    queryKey: ["indexBars", SHANGHAI_INDEX_SYMBOL],
    queryFn: () => fetchIndexBars(SHANGHAI_INDEX_SYMBOL, "1d", 3_000),
    enabled: view === "backtest",
    staleTime: 300_000,
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
    if (!end && latest) setEnd(latest);
    if (!start && datesQuery.data?.start) setStart(datesQuery.data.start);
  }, [datesQuery.data?.latest, datesQuery.data?.start, end, start]);
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

  const activeError = firstError(
    datesQuery.error,
    view === "live" ? liveQuery.error : null,
    view === "backtest" ? backtestQuery.error : null,
    view === "guide" ? strategyGuideQuery.error : null,
  );

  return (
    <div className="min-w-0">
      <BuyAlertBanner
        items={buyAlerts.banner}
        onDismiss={buyAlerts.dismissBanner}
        onLocate={alertBannerLocate}
      />
      <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b pb-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="font-display text-lg font-semibold tracking-tight">打板</h1>
          <span className="eyebrow hidden sm:inline">LIMIT-UP OPS</span>
        </div>
        <div className="flex items-center gap-2">
          {view === "live" && (
            <BuyAlertControls alerts={buyAlerts} />
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

      <nav className="flex h-12 items-end gap-6 overflow-x-auto border-b" aria-label="打板主视图">
        {PRIMARY_VIEWS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.value}
              type="button"
              className={cn(
                "flex h-12 shrink-0 items-center gap-2 border-b-2 text-sm transition-colors",
                view === item.value
                  ? "border-primary font-semibold text-foreground"
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
        <ErrorState message={activeError} onRetry={() => void refreshActive(view, liveQuery.refetch, backtestQuery.refetch, strategyGuideQuery.refetch)} />
      ) : view === "live" ? (
        <LiveView
          snapshot={liveQuery.data}
          portfolioReport={backtestQuery.data}
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
          onOpenBacktest={() => setView("backtest")}
        />
      ) : view === "ledger" ? (
        <section aria-label="历史交割单">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs text-muted-foreground sm:px-4">
            <span className="eyebrow">复盘 REVIEW</span>
            <span>最近 {timelineDates.length} 个交易日 · 最新在左</span>
            <span>连续评估交割 · D+1尾盘按官方收盘价卖出</span>
            {timelineCount < dates.length && (
              <button
                type="button"
                className="ml-auto font-medium text-foreground underline-offset-2 hover:underline"
                onClick={() => setTimelineCount((count) => count + LEDGER_TIMELINE_PAGE)}
              >
                加载更早 {Math.min(LEDGER_TIMELINE_PAGE, dates.length - timelineCount)} 天
              </button>
            )}
          </div>
          <LedgerTimeline
            days={timelineDates.map((date, index) => ({
              date,
              ledger: ledgerTimelineQueries[index]?.data,
              loading: Boolean(ledgerTimelineQueries[index]?.isLoading),
            }))}
          />
        </section>
      ) : view === "backtest" ? (
        <BacktestView
          report={backtestQuery.data}
          indexBars={indexBarsQuery.data?.items ?? []}
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
      ) : (
        <GuideView
          guide={strategyGuideQuery.data}
          radarValidation={radarValidationQuery.data}
          radarValidationLoading={radarValidationQuery.isLoading}
          radarValidationError={firstError(radarValidationQuery.error)}
          loading={strategyGuideQuery.isLoading}
          error={firstError(strategyGuideQuery.error)}
          onRetry={() => void strategyGuideQuery.refetch()}
        />
      )}
    </div>
  );
}

function BuyAlertControls({ alerts }: { alerts: ReturnType<typeof useBuyAlerts> }) {
  const toast = useToast();
  const [panelOpen, setPanelOpen] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!panelOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!panelRef.current?.contains(event.target as Node)) setPanelOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [panelOpen]);

  const toggleBuyAlerts = async () => {
    const enabling = !alerts.enabled;
    const permission = await alerts.toggle();
    toast({
      title: enabling ? "买点提醒已开启" : "买点提醒已关闭",
      description: enabling
        ? buyAlertPermissionDescription(permission)
        : "不会再播放声音、语音播报或发送桌面通知",
      variant: enabling ? "success" : "default",
    });
  };
  const testBuyAlerts = async () => {
    const permission = await alerts.test();
    toast({
      title: "测试提醒已触发",
      description: buyAlertPermissionDescription(permission),
      variant: "success",
    });
  };

  return (
    <div className="relative" ref={panelRef}>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          size="icon"
          variant="outline"
          className={cn("h-9 w-9", alerts.enabled && "border-rise/50 text-rise")}
          title={alerts.enabled
            ? `关闭买点提醒 · ${buyAlertPermissionDescription(alerts.permission)}`
            : "开启买点声音、语音播报和桌面通知"}
          aria-label={alerts.enabled ? "关闭买点提醒" : "开启买点提醒"}
          aria-pressed={alerts.enabled}
          onClick={() => void toggleBuyAlerts()}
        >
          {alerts.enabled ? <BellRing size={15} /> : <Bell size={15} />}
        </Button>
        {alerts.enabled && (
          <Button
            type="button"
            size="icon"
            variant="outline"
            className="h-9 w-9"
            title="语音播报设置"
            aria-label="语音播报设置"
            aria-expanded={panelOpen}
            onClick={() => setPanelOpen((open) => !open)}
          >
            <Volume2 size={15} />
          </Button>
        )}
      </div>
      {alerts.enabled && panelOpen && (
        <div className="absolute right-0 top-11 z-40 w-64 rounded-lg border bg-card p-3 shadow-lg">
          <div className="text-xs font-semibold">语音播报</div>
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            新买点触发时朗读股票名、涨幅和距板，并发送桌面通知。
          </p>
          <label className="mt-3 block text-[11px] text-muted-foreground">
            语速
            <input
              type="range"
              min={0.6}
              max={1.6}
              step={0.2}
              value={alerts.speechRate}
              onChange={(event) => alerts.setSpeechRate(Number(event.target.value))}
              className="mt-1 w-full accent-rise"
              aria-label="语音播报语速"
            />
          </label>
          <div className="mt-1 flex items-center justify-between text-[11px] tabular-nums text-muted-foreground">
            <span>慢</span>
            <span>{alerts.speechRate.toFixed(1)}x</span>
            <span>快</span>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-3 w-full"
            onClick={() => void testBuyAlerts()}
          >
            测试声音和语音
          </Button>
          <div className="mt-2 text-[11px] text-muted-foreground">
            {buyAlertPermissionDescription(alerts.permission)}
            {!alerts.speechAvailable && " · 当前浏览器不支持语音合成"}
          </div>
        </div>
      )}
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
  onOpenBacktest: () => void;
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
  onOpenBacktest,
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
  const planMode = isNextSessionPlan(snapshot);
  return (
    <section aria-label="实时推荐">
      <OpsFlowRail snapshot={snapshot} />
      <LiveCommandBar
        snapshot={snapshot}
        signalCount={signals.length}
        report={portfolioReport}
        onOpenBacktest={onOpenBacktest}
      />
      {signals.length ? (
        <div className="grid gap-3 px-3 py-3 sm:px-4 xl:grid-cols-2">
          {signals.map((signal) => (
            <LiveSignalCard
              key={signal.vt_symbol}
              signal={signal}
              stale={snapshot.data_quality.is_stale}
              paused={snapshot.session_stage === "lunch"}
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

/** 门禁状态：指挥条的核心答案——现在能不能出手 */
type GateTone = "go" | "wait" | "stop" | "plan";

function gateStatus(snapshot: LimitUpSignalSnapshot): { tone: GateTone; label: string; detail?: string } {
  const gate = snapshot.recommendations.market_gate;
  if (isNextSessionPlan(snapshot)) {
    const header = liveHeader(snapshot);
    const plan = snapshot.recommendations.plan ?? snapshot.data_quality.plan;
    return {
      tone: "plan",
      label: header.title,
      detail: `来源 ${snapshot.source_trade_date ?? plan?.source_trade_date ?? snapshot.trade_date}`,
    };
  }
  if (snapshot.session_stage === "lunch") {
    const schedule = snapshot.recommendations.execution_schedule;
    const afternoonEntryStart = schedule?.entry_windows[1]?.split("-")[0];
    return {
      tone: "wait",
      label: "午间休市",
      detail: afternoonEntryStart
        ? `展示上午最后快照 · ${afternoonEntryStart} 后恢复买入评估`
        : "展示上午最后快照",
    };
  }
  if (gate.passed) return { tone: "go", label: "允许出手" };
  if (gate.repair_state === "pending_repair") {
    return { tone: "wait", label: "等待盘中修复", detail: gate.reasons.join("；") || undefined };
  }
  if (gate.repair_state === "repair_revoked") {
    return { tone: "stop", label: "修复已撤销", detail: gate.repair_revoked_reason || undefined };
  }
  return { tone: "stop", label: "市场门关闭", detail: gate.reasons.join("；") || undefined };
}

const GATE_TONE_CLASS: Record<GateTone, { dot: string; text: string }> = {
  go: { dot: "bg-rise gate-breathe", text: "text-rise" },
  wait: { dot: "bg-amber-500 gate-breathe", text: "text-amber-700 dark:text-amber-300" },
  stop: { dot: "bg-fall", text: "text-fall" },
  plan: { dot: "bg-primary gate-breathe", text: "text-foreground" },
};

function GateLamp({ snapshot }: { snapshot: LimitUpSignalSnapshot }) {
  const status = gateStatus(snapshot);
  const tone = GATE_TONE_CLASS[status.tone];
  return (
    <div className="flex min-w-0 items-center gap-2">
      <span className={cn("h-2.5 w-2.5 shrink-0 rounded-full", tone.dot)} aria-hidden />
      <span className={cn("shrink-0 text-sm font-semibold", tone.text)}>{status.label}</span>
      {status.detail && (
        <span className="truncate text-xs text-muted-foreground" title={status.detail}>
          {status.detail}
        </span>
      )}
    </div>
  );
}

/**
 * 指挥条：把原来的「门禁条 + 时刻表条 + 质量条 + 新鲜度」四层合并成
 * 一个状态区——第一行回答“现在能不能买、有几个买点、市场什么温度”，
 * 第二行是安静的近期质量标尺。
 */
function LiveCommandBar({
  snapshot,
  signalCount,
  report,
  onOpenBacktest,
}: {
  snapshot: LimitUpSignalSnapshot;
  signalCount: number;
  report?: LimitUpLaneBacktest;
  onOpenBacktest: () => void;
}) {
  const gate = snapshot.recommendations.market_gate;
  const planMode = isNextSessionPlan(snapshot);
  return (
    <div className="border-b" aria-label="指挥条">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 px-3 py-2.5 sm:px-4">
        <GateLamp snapshot={snapshot} />
        {!planMode && gate.repair_confirmed && (
          <span className="text-xs text-rise">
            分歧修复已确认{gate.repair_confirmed_at ? ` · ${formatTime(gate.repair_confirmed_at)}` : ""}
          </span>
        )}
        <span className="flex items-baseline gap-1.5 text-xs text-muted-foreground">
          {planMode ? "提前观察" : "正式买点"}
          <span className="font-display text-lg font-bold leading-none tabular-nums text-foreground">
            {signalCount}
          </span>
        </span>
        <span className="text-xs text-muted-foreground">
          封板 {snapshot.market_context.sealed_count ?? 0} · 炸板 {snapshot.market_context.failed_count ?? 0} · {snapshot.source}
        </span>
        <div className="ml-auto">
          <Freshness snapshot={snapshot} />
        </div>
      </div>
      <QualityRow report={report} onOpenBacktest={onOpenBacktest} />
    </div>
  );
}

function QualityRow({
  report,
  onOpenBacktest,
}: {
  report?: LimitUpLaneBacktest;
  onOpenBacktest: () => void;
}) {
  const cashSummary = report?.summary;
  const qualitySummary = report?.recommendation_quality?.summary ?? report?.signal_summary;
  const proxyOnly = report?.execution_comparability?.live_equivalent === false;
  return (
    <div className="flex min-h-9 flex-wrap items-center gap-x-4 gap-y-1 border-t bg-muted/20 px-3 py-1.5 text-[11px] tabular-nums sm:px-4">
      <span className="eyebrow">近期质量</span>
      {cashSummary && qualitySummary ? (
        <>
          <span className="text-muted-foreground">样本 {qualitySummary.trade_count}/{qualitySummary.signal_count}</span>
          <span className={rateTone(qualitySummary.win_rate)}>胜率 {formatPct(qualitySummary.win_rate)}</span>
          <span className={amountTone(qualitySummary.average_return_pct)}>平均 D+1 {formatPct(qualitySummary.average_return_pct)}</span>
          <span className={amountTone(cashSummary.total_return_pct)}>两仓复利 {formatPct(cashSummary.total_return_pct)}</span>
          <span className="text-fall">回撤 {formatPct(cashSummary.max_drawdown_pct)}</span>
          {proxyOnly && (
            <span className="text-amber-700 dark:text-amber-300" title={report?.execution_comparability?.reason}>
              候选代理 · 非实盘等价
            </span>
          )}
          <button
            type="button"
            className="ml-auto text-muted-foreground underline-offset-2 transition-colors hover:text-foreground hover:underline"
            onClick={onOpenBacktest}
          >
            回测详情 →
          </button>
        </>
      ) : (
        <span className="text-muted-foreground">历史组合缓存读取中</span>
      )}
    </div>
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

/**
 * 当日轨迹：默认折叠为一行摘要（只数 / 扫描次数 / 首板漏斗），
 * 展开后才进入逐股轨迹表，避免诊断信息抢占盘中注意力。
 */
function LiveTracePanel({
  dates,
  selectedDate,
  day,
  loading,
  error,
  onDateChange,
  onRetry,
}: LiveTracePanelProps) {
  const [open, setOpen] = useState(false);
  const items = useMemo(() => {
    const scoped = (day?.items ?? []).filter(
      (item) => item.board_lane === "first_board" || item.board_lane === "two_to_three",
    );
    return sortLiveTraceItems(scoped);
  }, [day?.items]);
  const funnel = day?.lane_funnels?.first_board;
  const funnelSummary = funnel ? liveTraceFunnelSummary(funnel) : null;

  return (
    <section className="border-t" aria-label="最近两交易日推荐轨迹">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 sm:px-4">
        <button
          type="button"
          className="flex min-w-0 items-center gap-2 text-left"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          <span className="text-muted-foreground">
            {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </span>
          <span className="text-sm font-semibold">当日轨迹</span>
          <span className="eyebrow hidden sm:inline">TRACE</span>
          <span className="text-xs text-muted-foreground">
            {day
              ? `${items.length} 只 · ${day.snapshot_count ?? 0} 次扫描`
              : "保留推荐消失、买点触发、封板和炸板过程"}
          </span>
          {day?.scan_error_count ? (
            <span className="text-xs text-fall">{day.scan_error_count} 次异常</span>
          ) : null}
        </button>
        {!open && funnelSummary && (
          <span
            className="hidden min-w-0 flex-1 truncate font-mono text-[10px] tabular-nums text-muted-foreground lg:inline"
            title={funnelSummary.stages.join(" → ")}
          >
            {funnelSummary.stages.join(" → ")}
          </span>
        )}
        {open && (
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
        )}
      </div>

      {open && funnelSummary && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t bg-muted/20 px-3 py-2 text-xs sm:px-4">
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

      {open && (
        error ? (
          <div className="flex min-h-16 items-center gap-3 border-t px-3 py-3 text-xs text-fall sm:px-4">
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
          <div className="overflow-x-auto border-t">
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
        )
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

interface BacktestViewProps {
  report?: LimitUpLaneBacktest;
  indexBars: import("@/api/types").Bar[];
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
  indexBars,
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
  const qualitySummary = report?.recommendation_quality?.summary ?? report?.signal_summary;
  const skippedReasons = report?.recommendation_quality?.skipped_reasons ?? {};
  const skippedTotal = Object.values(skippedReasons).reduce((sum, count) => sum + count, 0);
  return (
    <section aria-label="真实现金回测">
      <PanelHead
        no="01"
        zh="参数与口径"
        en="SETUP"
        aside="10 万元 · 两仓各 50% · 100 股整数手 · 含费用滑点"
      />
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-3 sm:px-4">
        <DateInput label="开始" value={start} min={minimumDate} max={maximumDate} onChange={onStart} />
        <DateInput label="结束" value={end} min={minimumDate} max={maximumDate} onChange={onEnd} />
        <div className="h-9 border bg-muted/20 px-3 text-xs leading-9 text-muted-foreground">双窗口买入 / D+1收盘</div>
        <BacktestRebuildControl running={rebuildRunning} error={rebuildError} onRebuild={onRebuild} />
      </div>

      {report && (
        <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">
          买入 {report.execution_schedule?.entry_windows.join(" / ") ?? "连续盘中"} · D+1 {report.execution_schedule?.exit_time ?? "15:00"} 收盘卖出 ·
          官方收盘价 {report.coverage.daily_close_count ?? 0} · 缺失剔除 {report.coverage.daily_close_missing_count ?? 0}
          {report.lane === "portfolio" ? " · 首板 + 二进三 · 按到达时间成交 · 不预留仓位" : ""}
          {report.execution_comparability?.live_equivalent === false && (
            <span className="ml-3 text-amber-700 dark:text-amber-300" title={report.execution_comparability.reason}>
              候选代理，盘中资金门未历史重放
            </span>
          )}
        </div>
      )}

      <div className="grid border-b lg:grid-cols-2">
        <section className="border-b lg:border-b-0 lg:border-r" aria-label="两仓真实账户">
          <PanelHead no="02" zh="两仓真实账户" en="ACCOUNT" note="受持仓上限约束的实际可执行结果" accent />
          <div className="grid grid-cols-2 sm:grid-cols-3">
            <SummaryCell label="期末权益" value={formatCurrency(summary?.final_equity)} detail={`初始 ${formatCurrency(summary?.initial_cash)}`} />
            <SummaryCell label="账户复利" value={formatPct(summary?.total_return_pct)} tone={amountTone(summary?.total_return_pct)} detail={`费用 ${formatCurrency(summary?.total_fees)}`} />
            <SummaryCell label="成交胜率" value={formatPct(summary?.win_rate)} tone={rateTone(summary?.win_rate)} detail={`闭合 ${summary?.trade_count ?? 0} · 未平 ${summary?.open_position_count ?? 0}`} />
            <SummaryCell label="最大回撤" value={formatPct(summary?.max_drawdown_pct)} tone="text-fall" />
            <SummaryCell label="平均仓位" value={formatPct(summary?.average_utilization_pct)} detail={`峰值 ${formatPct(summary?.peak_utilization_pct)}`} />
            <SummaryCell label="跳过信号" value={String(summary?.skipped_count ?? 0)} detail={`实际买入 ${summary?.buy_count ?? 0}`} />
          </div>
        </section>

        <section aria-label="全量推荐质量">
          <PanelHead no="03" zh="推荐质量标尺" en="QUALITY" note="每只推荐独立标准槽位 · 不受持仓已满影响" />
          <div className="grid grid-cols-2 sm:grid-cols-3">
            <SummaryCell label="独立闭合" value={`${qualitySummary?.trade_count ?? 0} / ${qualitySummary?.signal_count ?? 0}`} detail="闭合 / 全部推荐" />
            <SummaryCell label="推荐胜率" value={formatPct(qualitySummary?.win_rate)} tone={rateTone(qualitySummary?.win_rate)} />
            <SummaryCell label="平均 D+1 净收益" value={formatPct(qualitySummary?.average_return_pct)} tone={amountTone(qualitySummary?.average_return_pct)} />
            <SummaryCell label="逐日等权复利" value={formatPct(qualitySummary?.total_return_pct)} tone={amountTone(qualitySummary?.total_return_pct)} detail="推荐质量标尺" />
            <SummaryCell
              label="标准槽位"
              value={formatCurrency(report?.recommendation_quality?.standard_slot_cash)}
              detail="每只推荐独立记账"
            />
            <SummaryCell
              label="跳过原因"
              value={skippedTotal ? String(skippedTotal) : "0"}
              detail={skippedTotal ? Object.entries(skippedReasons).map(([reason, count]) => `${skipReasonLabel(reason)} ${count}`).join(" · ") : "无跳过"}
            />
          </div>
        </section>
      </div>

      {report && (
        <>
          <PanelHead no="04" zh="稳健性验证" en="ROBUSTNESS" />
          <ValidationStrip report={report} />
          <RobustnessStrip report={report} />
        </>
      )}
      {report?.daily_results.length ? (
        <>
          <PanelHead no="05" zh="权益曲线" en="EQUITY" />
          <EquityChart report={report} indexBars={indexBars} />
        </>
      ) : (
        <EmptyRow text="当前范围没有账户权益记录" />
      )}
      {report?.drawdown_diagnostics && (
        <BacktestDrawdownPanel diagnostics={report.drawdown_diagnostics} />
      )}
      {report && (
        <>
          <PanelHead no="06" zh="逐笔交割" en="TRADES" note="最新在前 · 最多 100 笔" />
          <BacktestTrades report={report} />
        </>
      )}
      {report && <SkippedOrders report={report} />}
    </section>
  );
}

/** 章节头：mono 编号 + 中文标题 + 英文代号，把长回测页变成有顺序的报告 */
function PanelHead({
  no,
  zh,
  en,
  note,
  aside,
  accent = false,
}: {
  no: string;
  zh: string;
  en: string;
  note?: string;
  aside?: string;
  accent?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-baseline gap-x-2 gap-y-0.5 border-b px-3 py-2 sm:px-4",
        accent ? "bg-primary/[0.05]" : "bg-muted/20",
      )}
    >
      <span className="font-mono text-[10px] font-semibold tracking-[0.15em] text-primary">{no}</span>
      <h2 className="text-sm font-semibold">{zh}</h2>
      <span className="eyebrow">{en}</span>
      {note && <span className="text-[11px] text-muted-foreground">{note}</span>}
      {aside && <span className="ml-auto text-xs tabular-nums text-muted-foreground">{aside}</span>}
    </div>
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

function EquityChart({ report, indexBars }: { report: LimitUpLaneBacktest; indexBars: import("@/api/types").Bar[] }) {
  const colors = useChartColors();
  const points = useMemo(() => buildBacktestChartPoints(report, indexBars), [report, indexBars]);
  const hasRecommendation = points.some((point) => point.recommendation_return_pct != null);
  const hasIndex = points.some((point) => point.index_return_pct != null);
  const indexReturn = hasIndex ? points[points.length - 1].index_return_pct : null;
  return (
    <div className="border-b px-1 py-3 sm:px-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 pb-2 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">收益对比（双轴）</span>
        <span>左轴：策略收益与回撤 · 右轴：上证指数累计收益</span>
        {hasIndex && indexReturn != null && (
          <span className={cn("font-medium tabular-nums", amountTone(indexReturn))}>
            同期上证 {indexReturn > 0 ? "+" : ""}{indexReturn.toFixed(2)}%
          </span>
        )}
        {!hasIndex && <span className="text-amber-700 dark:text-amber-300">指数行情暂未覆盖该区间</span>}
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%" minWidth={0} minHeight={0} initialDimension={{ width: 320, height: 240 }}>
          <LineChart data={points} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke={colors.grid} strokeDasharray="3 3" />
            <XAxis dataKey="result_date" minTickGap={36} tick={{ fill: colors.text, fontSize: 11 }} axisLine={{ stroke: colors.axis }} tickLine={false} />
            <YAxis yAxisId="strategy" tickFormatter={(value) => `${value}%`} tick={{ fill: colors.text, fontSize: 11 }} axisLine={{ stroke: colors.axis }} tickLine={false} width={48} />
            {hasIndex && (
              <YAxis yAxisId="index" orientation="right" tickFormatter={(value) => `${value}%`} tick={{ fill: colors.linePalette[3], fontSize: 11 }} axisLine={{ stroke: colors.linePalette[3] }} tickLine={false} width={44} />
            )}
            <Tooltip contentStyle={{ background: colors.tooltipBg, borderColor: colors.tooltipBorder, color: colors.tooltipText, borderRadius: 6, fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line yAxisId="strategy" type="monotone" dataKey="account_return_pct" name="两仓账户" stroke={colors.brand} strokeWidth={2.5} dot={false} connectNulls />
            {hasRecommendation && (
              <Line yAxisId="strategy" type="monotone" dataKey="recommendation_return_pct" name="全量推荐(等权)" stroke={colors.linePalette[0]} strokeWidth={2} dot={false} connectNulls />
            )}
            {hasIndex && (
              <Line yAxisId="index" type="monotone" dataKey="index_return_pct" name="上证指数(右轴)" stroke={colors.linePalette[3]} strokeWidth={1.8} strokeDasharray="5 3" dot={false} connectNulls />
            )}
            <Line yAxisId="strategy" type="monotone" dataKey="account_drawdown_pct" name="账户回撤" stroke={colors.fall} strokeWidth={1.5} dot={false} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
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
  const withReturn = rows.filter((order) => order.d1_return_pct != null);
  const wins = withReturn.filter((order) => (order.d1_return_pct ?? 0) > 0).length;
  const avgReturn = withReturn.length
    ? withReturn.reduce((sum, order) => sum + (order.d1_return_pct ?? 0), 0) / withReturn.length
    : null;
  return (
    <div className="overflow-x-auto border-t">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span className="font-medium text-foreground">未成交推荐的反事实收益</span>
        <span className="text-muted-foreground">
          因持仓已满或现金不足没买成 · 但仍计入上方「全量推荐质量」
        </span>
        {withReturn.length > 0 && (
          <span className="ml-auto flex items-center gap-x-5 gap-y-1 tabular-nums">
            <span className="text-muted-foreground">如果都买入</span>
            <span className={rateTone(wins / withReturn.length * 100)}>胜率 {formatPct(wins / withReturn.length * 100)}（{wins}/{withReturn.length}）</span>
            <span className={amountTone(avgReturn)}>平均 D+1 {formatPct(avgReturn)}</span>
          </span>
        )}
      </div>
      <table className="w-full min-w-[920px] text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground"><tr><th className="px-3 py-2 text-left">未成交时间</th><th className="px-3 py-2 text-left">股票</th><th className="px-3 py-2 text-left">板位</th><th className="px-3 py-2 text-left">原因</th><th className="px-3 py-2 text-left">板上结果</th><th className="px-3 py-2 text-right">买/卖价</th><th className="px-3 py-2 text-right">如果买入 D+1</th><th className="px-3 py-2 text-right">当时现金</th></tr></thead>
        <tbody className="divide-y">
          {rows.map((order) => {
            const hasReturn = order.d1_return_pct != null;
            return (
              <tr key={order.order_id}>
                <td className="px-3 py-3 text-xs tabular-nums"><div>{order.trade_date} {order.trade_time}</div>{order.result_date && <div className="text-muted-foreground">D+1 {order.result_date}</div>}</td>
                <td className="px-3 py-3"><StockIdentityLink name={order.name} vtSymbol={order.vt_symbol} /></td>
                <td className="px-3 py-3 text-xs">{limitUpLaneLabel(order.lane)}</td>
                <td className="px-3 py-3 text-xs text-fall">{skipReasonLabel(order.reason)}</td>
                <td className={cn("px-3 py-3 text-xs font-medium", order.d_board_status === "sealed" ? "text-rise" : order.d_board_status ? "text-fall" : "text-muted-foreground")}>{order.d_board_status ? boardStatusLabel(order.d_board_status) : "--"}</td>
                <td className="whitespace-nowrap px-3 py-3 text-right text-xs tabular-nums"><div>{formatPrice(order.buy_price)}</div><div className="text-muted-foreground">{formatPrice(order.d1_close_price)}</div></td>
                <td className={cn("px-3 py-3 text-right text-sm font-semibold tabular-nums", hasReturn ? amountTone(order.d1_return_pct) : "text-muted-foreground")}>{hasReturn ? formatPct(order.d1_return_pct) : "待 D+1"}</td>
                <td className="px-3 py-3 text-right text-xs tabular-nums">{formatCurrency(order.cash_after)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function DateInput({ label, value, min, max, onChange }: { label: string; value: string; min?: string | null; max?: string | null; onChange: (value: string) => void }) {
  return <label className="text-xs text-muted-foreground">{label}<input type="date" value={value} min={min ?? undefined} max={max ?? undefined} onChange={(event) => onChange(event.target.value)} className="mt-1 block h-9 border bg-background px-2 text-sm text-foreground" /></label>;
}

function SummaryCell({ label, value, tone, detail }: { label: string; value: string; tone?: string; detail?: string }) {
  return <div className="min-w-0 border-b border-r px-3 py-2.5 last:border-r-0 sm:border-b-0 xl:border-b-0"><div className="text-[11px] text-muted-foreground">{label}</div><div className={cn("mt-0.5 truncate text-sm font-semibold tabular-nums", tone)}>{value}</div>{detail && <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{detail}</div>}</div>;
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-4 py-16 text-center text-sm text-muted-foreground">{text}</div>;
}

function buyAlertPermissionDescription(permission: BuyAlertPermission) {
  return ({
    granted: "声音和桌面通知均已启用",
    denied: "声音已启用；浏览器已拒绝桌面通知",
    default: "声音已启用；桌面通知尚未授权",
    unsupported: "声音已启用；当前浏览器不支持桌面通知",
  } as Record<BuyAlertPermission, string>)[permission];
}

function firstError(...values: unknown[]) {
  const error = values.find(Boolean);
  return error instanceof Error ? error.message : error ? "打板数据加载失败" : null;
}

async function refreshActive(view: PrimaryView, live: () => Promise<unknown>, backtest: () => Promise<unknown>, guide: () => Promise<unknown>) {
  if (view === "live") await live();
  else if (view === "guide") await guide();
  else await backtest();
}
