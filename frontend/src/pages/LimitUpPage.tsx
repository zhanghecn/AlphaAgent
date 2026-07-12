import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  fetchLimitUpHistoryModelReport,
  fetchLimitUpLaneBacktest,
  fetchLimitUpLive,
  refreshLimitUpLive,
  type BoardLaneKey,
  type EntryMode,
  type ExitMode,
  type LimitUpBacktestScope,
  type LimitUpLaneBacktest,
  type LimitUpLaneLedger,
  type LimitUpLaneLedgerTrade,
  type LimitUpLiveSignal,
  type LimitUpSignalSnapshot,
  type LimitUpWalkForwardModelReport,
} from "@/api/limitUp";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
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

const BACKTEST_SCOPES: Array<{ value: LimitUpBacktestScope; label: string }> = [
  { value: "portfolio", label: "组合" },
  ...BOARD_LANES,
];

export function LimitUpPage() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<PrimaryView>("live");
  const [lane, setLane] = useState<BoardLaneKey>("first_board");
  const [backtestScope, setBacktestScope] = useState<LimitUpBacktestScope>("portfolio");
  const [selectedDate, setSelectedDate] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [exitMode, setExitMode] = useState<ExitMode>("next_open");
  const modelLane = backtestScope === "portfolio" ? null : backtestScope;

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
    queryKey: ["limitUpLaneLedger", selectedDate, lane, exitMode],
    queryFn: () => fetchLimitUpHistoryLedger({ date: selectedDate, lane, exitMode }),
    enabled: view === "ledger" && Boolean(selectedDate),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const backtestQuery = useQuery({
    queryKey: ["limitUpLaneBacktest", start, end, backtestScope, exitMode],
    queryFn: () => fetchLimitUpLaneBacktest({ start, end, lane: backtestScope, exitMode }),
    enabled: view === "backtest" && Boolean(start && end),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const modelQuery = useQuery({
    queryKey: ["limitUpLaneModel", start, end, modelLane, exitMode],
    queryFn: () => fetchLimitUpHistoryModelReport({
      start,
      end,
      lane: modelLane ?? "first_board",
      entryMode: modelEntryModeForLane(modelLane ?? "first_board"),
      exitMode,
    }),
    enabled: view === "backtest" && modelLane !== null && Boolean(start && end),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const refreshMutation = useMutation({
    mutationFn: refreshLimitUpLive,
    onSuccess: (snapshot) => {
      queryClient.setQueryData(["limitUpLive"], snapshot);
    },
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
              disabled={liveQuery.isFetching || refreshMutation.isPending}
              onClick={() => refreshMutation.mutate()}
            >
              <RefreshCw size={15} className={cn((liveQuery.isFetching || refreshMutation.isPending) && "animate-spin")} />
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
      ) : (
        <LaneTabs value={lane} onChange={setLane} />
      )}

      {activeError ? (
        <ErrorState message={activeError} onRetry={() => void refreshActive(view, liveQuery.refetch, ledgerQuery.refetch, backtestQuery.refetch)} />
      ) : view === "live" ? (
        <LiveView snapshot={liveQuery.data} lane={lane} loading={liveQuery.isLoading} />
      ) : view === "ledger" ? (
        <LedgerView ledger={ledgerQuery.data} loading={ledgerQuery.isLoading} />
      ) : (
        <BacktestView
          report={backtestQuery.data}
          modelReport={modelLane ? modelQuery.data : undefined}
          modelLoading={Boolean(modelLane) && (modelQuery.isLoading || modelQuery.isFetching)}
          modelError={modelLane ? modelQuery.error : null}
          loading={backtestQuery.isLoading}
          fetching={backtestQuery.isFetching || (Boolean(modelLane) && modelQuery.isFetching)}
          start={start}
          end={end}
          exitMode={exitMode}
          minimumDate={datesQuery.data?.start}
          maximumDate={datesQuery.data?.end}
          onStart={setStart}
          onEnd={setEnd}
          onExitMode={setExitMode}
          onRun={() => {
            void backtestQuery.refetch();
            if (modelLane) void modelQuery.refetch();
          }}
        />
      )}
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

function LiveView({ snapshot, lane, loading }: { snapshot?: LimitUpSignalSnapshot; lane: BoardLaneKey; loading: boolean }) {
  const signals = useMemo(() => liveSignalsForLane(snapshot, lane), [lane, snapshot]);
  if (loading) return <LoadingState rows={5} />;
  if (!snapshot) return <EmptyRow text="当前没有实时快照" />;
  const gate = snapshot.recommendations.market_gate;
  const laneValidation = snapshot.recommendations.board_lane_validations?.[lane];
  return (
    <section aria-label="实时推荐">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-muted/20 px-3 py-2 text-xs sm:px-4">
        <span className={gate.passed ? "text-rise" : "text-fall"}>
          {gate.passed ? "市场允许出手" : `市场门关闭${gate.reasons.length ? `：${gate.reasons.join("；")}` : ""}`}
        </span>
        {gate.repair_confirmed && <span className="text-rise">分歧修复已确认</span>}
        {laneValidation && (
          <span className={laneValidation.passed ? "text-rise" : "text-amber-700 dark:text-amber-300"}>
            {laneValidation.passed ? "战法验证通过" : `战法仅观察：${laneValidation.reason}`}
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
        <EmptyRow text="当前板位没有候选，保持空仓" />
      )}
    </section>
  );
}

function LiveSignalRow({ signal, stale }: { signal: LimitUpLiveSignal; stale: boolean }) {
  const actionable = !stale && ["buy_now", "next_auction"].includes(signal.action);
  const validationObservation = !stale && signal.validation_passed === false;
  const observation = signal.action === "wait_tail" || validationObservation;
  const factorSummary = liveFactorSummary(signal);
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
          <div className={cn("text-sm font-semibold", actionTone(signal.action, stale))}>{stale ? "数据过期" : validationObservation ? "观察，不执行" : actionLabel(signal.action)}</div>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {entryKindLabel(signal.entry_kind)} · {formatPrice(signal.trigger_price)}
            {signal.board_lane === "two_to_three" ? ` · ${twoToThreeQualityLabel(signal.lane_quality_tier, signal.lane_risk_count)}` : ""}
          </div>
        </div>
        <div className="min-w-0 text-xs leading-5">
          <div className="text-foreground">{signal.reason}</div>
          {signal.board_lane === "first_board" && (
            <div className="text-muted-foreground">
              封板门 {gateStateLabel(signal.seal_gate_passed)} · 溢价门 {gateStateLabel(signal.premium_gate_passed)}
            </div>
          )}
          {factorSummary && <div className="text-muted-foreground">{factorSummary}</div>}
          <div className="truncate text-muted-foreground" title={signal.cancel_condition}>取消：{signal.cancel_condition}</div>
        </div>
        <div className="grid grid-cols-2 gap-x-3 text-xs tabular-nums">
          <Metric label="板块热度" value={formatNumber(signal.sector_heat, 1)} />
          <Metric label="换手" value={formatPct(signal.turnover_rate)} />
          <Metric label="封单" value={formatAmount(signal.seal_amount)} />
          <Metric label="D+1样本" value={formatPct(signal.historical_evidence?.smoothed_win_rate)} tone={rateTone(signal.historical_evidence?.smoothed_win_rate)} />
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
            : `正式交割 ${ledger.selected_count} 只 · ${ledger.exit_mode === "next_open" ? "D+1 开盘卖出" : "D+1 收盘卖出"}`}
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
      <td className="px-3 py-3 text-xs tabular-nums"><div>{trade.sell_date ?? "待 D+1"} {trade.sell_time ?? ""}</div><div className="text-muted-foreground">{formatPrice(trade.sell_price)}</div></td>
      <td className={cn("px-3 py-3 text-xs font-medium", trade.d_board_status === "sealed" ? "text-rise" : "text-fall")}>{boardStatusLabel(trade.d_board_status)}</td>
      <td className="px-3 py-3 text-xs">{d1OutcomeLabel(trade.d1_outcome)}</td>
      <td className={cn("px-3 py-3 text-right font-semibold tabular-nums", amountTone(trade.return_pct))}>{formatPct(trade.return_pct)}</td>
      <td className="max-w-[360px] px-3 py-3 text-xs leading-5 text-muted-foreground">{trade.favorable_factors?.map(factorLabel).join("；") || "无可执行证据"}</td>
    </tr>
  );
}

interface BacktestViewProps {
  report?: LimitUpLaneBacktest;
  modelReport?: LimitUpWalkForwardModelReport;
  modelLoading: boolean;
  modelError: unknown;
  loading: boolean;
  fetching: boolean;
  start: string;
  end: string;
  exitMode: ExitMode;
  minimumDate?: string | null;
  maximumDate?: string | null;
  onStart: (value: string) => void;
  onEnd: (value: string) => void;
  onExitMode: (value: ExitMode) => void;
  onRun: () => void;
}

function BacktestView({ report, modelReport, modelLoading, modelError, loading, fetching, start, end, exitMode, minimumDate, maximumDate, onStart, onEnd, onExitMode, onRun }: BacktestViewProps) {
  if (loading && !report) return <LoadingState rows={7} />;
  const summary = report?.summary;
  return (
    <section aria-label="真实现金回测">
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-3 sm:px-4">
        <DateInput label="开始" value={start} min={minimumDate} max={maximumDate} onChange={onStart} />
        <DateInput label="结束" value={end} min={minimumDate} max={maximumDate} onChange={onEnd} />
        <label className="text-xs text-muted-foreground">
          卖出
          <select value={exitMode} onChange={(event) => onExitMode(event.target.value as ExitMode)} className="mt-1 block h-9 border bg-background px-2 text-sm text-foreground">
            <option value="next_open">D+1 开盘</option>
            <option value="next_close">D+1 收盘</option>
          </select>
        </label>
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
      {report?.lane === "portfolio" ? (
        <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">组合账户 · 共享现金 · 4 仓上限</div>
      ) : (
        <ModelEvidenceStrip
          ruleTradeCount={summary?.trade_count ?? 0}
          report={modelReport}
          loading={modelLoading}
          error={modelError}
        />
      )}
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

function ModelEvidenceStrip({ ruleTradeCount, report, loading, error }: {
  ruleTradeCount: number;
  report?: LimitUpWalkForwardModelReport;
  loading: boolean;
  error: unknown;
}) {
  if (loading && !report) {
    return <div className="border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">正在核验完整候选池</div>;
  }
  if (error || !report) {
    return <div className="border-b px-3 py-2 text-xs text-fall sm:px-4">完整候选池模型暂不可用，规则回测不受影响</div>;
  }
  const maximumTraining = Math.max(0, ...report.windows.map((window) => window.training_samples));
  const requiredTraining = report.model_contract.min_training_samples;
  const fittedWindows = report.coverage.fitted_windows ?? 0;
  const modelStatus = fittedWindows > 0
    ? `模型选择 ${report.selected_candidates.length} 笔`
    : "训练不足，模型空仓";
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b px-3 py-2 text-xs sm:px-4">
      <span className={fittedWindows > 0 ? "text-foreground" : "text-amber-700 dark:text-amber-300"}>{modelStatus}</span>
      <span className="text-muted-foreground">完整合格样本 {report.coverage.closed_candidate_count ?? 0}</span>
      <span className="text-muted-foreground">最大训练窗 {maximumTraining} / 最低 {requiredTraining}</span>
      <span className="text-muted-foreground">规则选择 {ruleTradeCount} 笔</span>
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

function SummaryCell({ label, value, tone, detail }: { label: string; value: string; tone?: string; detail?: string }) {
  return <div className="min-w-0 border-b border-r px-3 py-2.5 last:border-r-0 xl:border-b-0"><div className="text-[11px] text-muted-foreground">{label}</div><div className={cn("mt-0.5 truncate text-sm font-semibold tabular-nums", tone)}>{value}</div>{detail && <div className="mt-0.5 text-[10px] leading-4 text-muted-foreground">{detail}</div>}</div>;
}

function EmptyRow({ text }: { text: string }) {
  return <div className="px-4 py-16 text-center text-sm text-muted-foreground">{text}</div>;
}

function liveSignalsForLane(snapshot: LimitUpSignalSnapshot | undefined, lane: BoardLaneKey): LimitUpLiveSignal[] {
  if (!snapshot) return [];
  const lanes = snapshot.recommendations.lanes;
  const rows = [...(lanes.now ?? []), ...(lanes.tail ?? []), ...(lanes.next_auction ?? [])];
  const selected = new Map<string, LimitUpLiveSignal>();
  for (const signal of rows) {
    if ((signal.board_lane ?? boardLaneForLevel(signal.board_level)) !== lane) continue;
    const current = selected.get(signal.vt_symbol);
    if (!current || actionPriority(signal.action) < actionPriority(current.action)) selected.set(signal.vt_symbol, signal);
  }
  return [...selected.values()]
    .sort((left, right) => actionPriority(left.action) - actionPriority(right.action) || (left.market_dragon_rank ?? 99) - (right.market_dragon_rank ?? 99))
    .slice(0, 4);
}

function boardLaneForLevel(level: number): BoardLaneKey {
  if (level <= 1) return "first_board";
  if (level === 2) return "one_to_two";
  if (level === 3) return "two_to_three";
  return "high_board";
}

function boardLaneLabel(value: BoardLaneKey) { return ({ first_board: "首板", one_to_two: "一进二", two_to_three: "二进三", high_board: "高板" } as Record<BoardLaneKey, string>)[value]; }

function modelEntryModeForLane(lane: BoardLaneKey): EntryMode {
  return lane === "first_board" ? "sweep" : "next_auction";
}

function actionPriority(action: string) { return ({ buy_now: 0, next_auction: 1, wait_tail: 2, pass: 3 } as Record<string, number>)[action] ?? 4; }
function actionLabel(action: string) { return ({ buy_now: "现在打", next_auction: "明早竞价", wait_tail: "尾盘等确认", pass: "不打" } as Record<string, string>)[action] ?? action; }
function actionTone(action: string, stale: boolean) { if (stale || action === "pass") return "text-fall"; if (action === "buy_now" || action === "next_auction") return "text-rise"; return "text-amber-600 dark:text-amber-300"; }
function entryKindLabel(value: string) { return (({ none: "不执行", auction: "竞价", sweep: "扫板", reseal: "回封", tail_seal: "尾盘封板", next_auction: "竞价接力", first_touch: "首次触板", intraday: "盘中", wait: "等待确认" } as Record<string, string>)[value] ?? value) || "--"; }
function phaseLabel(value?: string) { return ({ warmup: "预热期", expanding_oos: "滚动样本外", locked_holdout: "锁定留出", post_freeze_forward: "冻结后前向" } as Record<string, string>)[value ?? ""] ?? value ?? "阶段未知"; }
function d1OutcomeLabel(value: string) { return ({ continuation_limit_up: "D+1 连板", next_limit_up_after_failed_board: "D+1 涨停", d1_premium: "D+1 有溢价", direct_breakdown: "D+1 直接砸", no_premium: "D+1 无溢价", awaiting_d1_bar: "待 D+1" } as Record<string, string>)[value] ?? value; }
function boardStatusLabel(value: string) { return ({ sealed: "封住", failed: "触板后炸板", no_limit: "未触板" } as Record<string, string>)[value] ?? value; }
function exitReasonLabel(value: string) { return ({ planned_open: "开盘退出", planned_close: "收盘退出", emergency_close: "开盘未成后收盘退出", retry_open: "延期至开盘退出", retry_close: "延期至收盘退出" } as Record<string, string>)[value] ?? value; }
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
function firstError(...values: unknown[]) { const error = values.find(Boolean); return error instanceof Error ? error.message : error ? "打板数据加载失败" : null; }
async function refreshActive(view: PrimaryView, live: () => Promise<unknown>, ledger: () => Promise<unknown>, backtest: () => Promise<unknown>) { if (view === "live") await live(); else if (view === "ledger") await ledger(); else await backtest(); }
