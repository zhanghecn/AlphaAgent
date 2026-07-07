import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, ChevronLeft, ChevronRight, Database, Play, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { cn, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { formatNumber, numberValue } from "@/lib/backtest-utils";
import { DEFAULT_CANDIDATE_OBSERVATION_LIMIT, DEFAULT_EXECUTION_CANDIDATE_LIMIT, QUANT_BOARD_OPTIONS, boardLabels, type QuantBoard } from "@/features/quant/constants";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import { fetchBacktestCandidateTrace, type BacktestCandidateNotPlannedContext, type BacktestCandidateTrace, type QuantRecommendation, type QuantScreenRun, type QuantScreenRunItem, type QuantStrategyExplain, type QuantStrategyExplainFactor, type QuantStrategyOption } from "@/api/quant";
import type { TailWorkflowStatus } from "@/api/dataSync";

export function RecommendationsPanel({
  isLoading,
  isError,
  error,
  items,
  tradeDate,
  runId,
  strategyVersion,
  includedBoards,
  viewMode,
  onViewModeChange,
  previewMeta,
  screenRuns,
  tradingDates,
  selectedTradeDate,
  onSelectedTradeDateChange,
  strategies,
  selectedStrategy,
  selectedBoards,
  onSelectedBoardsChange,
  activeBacktestId,
  status,
  message,
  tailWorkflowStatus,
  tailWorkflowLoading,
  tailWorkflowError,
  onRetry,
  onRunScreen,
  isRunningScreen,
  onAddToHolding,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  items: QuantRecommendation[];
  tradeDate?: string;
  runId?: number | null;
  strategyVersion?: string;
  includedBoards?: string[];
  viewMode: "history" | "tail_preview";
  onViewModeChange: (mode: "history" | "tail_preview") => void;
  previewMeta?: QuantScreenRun;
  screenRuns: QuantScreenRunItem[];
  tradingDates: string[];
  selectedTradeDate: string;
  onSelectedTradeDateChange: (tradeDate: string) => void;
  strategies: QuantStrategyOption[];
  selectedStrategy: string;
  selectedBoards: string[];
  onSelectedBoardsChange: (boards: string[]) => void;
  activeBacktestId?: number | null;
  status?: string;
  message?: string;
  tailWorkflowStatus?: TailWorkflowStatus;
  tailWorkflowLoading?: boolean;
  tailWorkflowError?: unknown;
  onRetry: () => void;
  onRunScreen: () => void;
  isRunningScreen: boolean;
  onAddToHolding?: (item: QuantRecommendation) => void;
}) {
  const [actionFilter, setActionFilter] = useState<"all" | "BUY" | "WATCH">("all");
  const [failedRuleFilter, setFailedRuleFilter] = useState("all");
  const [traceTarget, setTraceTarget] = useState<{ vtSymbol: string; tradeDate: string } | null>(null);
  const [page, setPage] = useState(1);
  const activeBoards = includedBoards?.length ? includedBoards : selectedBoards;
  const isTailPreview = viewMode === "tail_preview";
  const selectedStrategyMeta = strategies.find((strategy) => strategy.id === selectedStrategy);
  const failedRuleLabels = selectedStrategyMeta?.failed_rule_labels ?? {};
  const metricColumns = recommendationMetricColumns(selectedStrategyMeta);
  const latestRunByDate = new Map<string, QuantScreenRunItem>();
  for (const run of screenRuns) {
    const current = latestRunByDate.get(run.trade_date);
    if (!current || run.id > current.id) {
      latestRunByDate.set(run.trade_date, run);
    }
  }
  const succeededRunDates = screenRuns.filter((run) => run.status === "succeeded").map((run) => run.trade_date);
  const fallbackDates = succeededRunDates.length ? [] : tradingDates.slice(0, 60);
  const availableDates = Array.from(new Set([...succeededRunDates, ...fallbackDates, selectedTradeDate].filter(Boolean)));
  const stats = useMemo(() => candidateStats(items), [items]);
  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (actionFilter !== "all" && item.action !== actionFilter) return false;
      if (failedRuleFilter !== "all" && !failedRules(item).includes(failedRuleFilter)) return false;
      return true;
    });
  }, [actionFilter, failedRuleFilter, items]);
  const pageSize = 20;
  const pageCount = Math.max(Math.ceil(filteredItems.length / pageSize), 1);
  const currentPage = Math.min(page, pageCount);
  const pageStartIndex = (currentPage - 1) * pageSize;
  const pagedItems = filteredItems.slice(pageStartIndex, pageStartIndex + pageSize);
  const pageStart = filteredItems.length ? pageStartIndex + 1 : 0;
  const pageEnd = Math.min(pageStartIndex + pageSize, filteredItems.length);
  const runDates = new Set(succeededRunDates);
  const runDateCount = availableDates.filter((date) => runDates.has(date)).length;
  const missingRunCount = Math.max(availableDates.length - runDateCount, 0);
  const traceQuery = useQuery({
    queryKey: ["backtestCandidateTrace", activeBacktestId, traceTarget?.vtSymbol, traceTarget?.tradeDate],
    queryFn: () => fetchBacktestCandidateTrace(activeBacktestId!, traceTarget!.vtSymbol, traceTarget!.tradeDate),
    enabled: Boolean(activeBacktestId && traceTarget && !isTailPreview),
    staleTime: 20_000,
  });

  if (isLoading) return <LoadingState rows={6} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载量化推荐失败"}
        onRetry={onRetry}
      />
    );
  }

  return (
    <section className="rounded-lg border">
      <div className="space-y-3 border-b px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <ShieldCheck size={16} />
            <h2 className="text-sm font-semibold">量化候选</h2>
          </div>
          <div className="text-xs text-muted-foreground">
            {tradeDate ?? "--"} · 观察前 {DEFAULT_CANDIDATE_OBSERVATION_LIMIT} · {isTailPreview ? "实时尾盘量化" : `执行前 ${DEFAULT_EXECUTION_CANDIDATE_LIMIT}`} · {runId ? `运行 #${runId}` : isTailPreview ? "未落库" : "未运行"} · {strategyVersion ?? "--"}
          </div>
        </div>
        <div className="flex w-fit rounded-md border bg-muted/30 p-1">
          <button
            className={cn("rounded px-3 py-1.5 text-sm", !isTailPreview ? "bg-background shadow-sm" : "text-muted-foreground")}
            onClick={() => onViewModeChange("history")}
          >
            历史候选
          </button>
          <button
            className={cn("rounded px-3 py-1.5 text-sm", isTailPreview ? "bg-background shadow-sm" : "text-muted-foreground")}
            onClick={() => onViewModeChange("tail_preview")}
          >
            实时尾盘量化
          </button>
        </div>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_260px]">
          {isTailPreview ? (
            <TailPreviewSummary meta={previewMeta} />
          ) : (
            <TradingDateSelector
              label="查看交易日"
              value={selectedTradeDate}
              dates={availableDates}
              onChange={onSelectedTradeDateChange}
              getOptionLabel={(date) => {
                const run = latestRunByDate.get(date);
                return run ? `${date} · #${run.id} · 候选 ${run.recommendation_count}` : `${date} · 未运行`;
              }}
              className="gap-1"
              selectClassName="w-full min-w-0"
            />
          )}
          <div className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">策略</span>
            <div className="flex h-8 items-center rounded-md border bg-muted/30 px-2 text-sm">
              {selectedStrategyMeta?.name ?? "主线龙回头回踩低吸"}
            </div>
          </div>
        </div>
        <QuantBoardSelector
          selectedBoards={selectedBoards}
          activeBoards={activeBoards}
          onChange={onSelectedBoardsChange}
          onRun={onRunScreen}
          isRunning={isRunningScreen}
        />
        <TailWorkflowSyncStrip
          workflow={tailWorkflowStatus}
          isLoading={Boolean(tailWorkflowLoading)}
          error={tailWorkflowError}
        />
      </div>
      {items.length === 0 ? (
        <QuantEmptyState
          status={status}
          message={message}
          strategy={selectedStrategyMeta}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2">
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span>BUY {stats.buyCount}</span>
              <span>WATCH {stats.watchCount}</span>
              <span>按评分排名观察前 {DEFAULT_CANDIDATE_OBSERVATION_LIMIT}，不强行保留低吸名额</span>
              {isTailPreview ? (
                <span>盘中临时K线只用于 14:30 决策参考，不参与回测</span>
              ) : (
                <>
                  <span>回测只执行 BUY 前 {DEFAULT_EXECUTION_CANDIDATE_LIMIT}</span>
                  <span>已运行 {runDateCount} 日</span>
                  <span>未运行 {missingRunCount} 日</span>
                </>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="h-8 rounded-md border bg-background px-2 text-sm"
                value={actionFilter}
                onChange={(event) => {
                  setActionFilter(event.target.value as "all" | "BUY" | "WATCH");
                  setPage(1);
                }}
              >
                <option value="all">全部动作</option>
                <option value="BUY">仅买入</option>
                <option value="WATCH">仅观察</option>
              </select>
              <select
                className="h-8 rounded-md border bg-background px-2 text-sm"
                value={failedRuleFilter}
                onChange={(event) => {
                  setFailedRuleFilter(event.target.value);
                  setPage(1);
                }}
              >
                <option value="all">全部规则</option>
                {stats.failedRules.map((rule) => (
                  <option key={rule} value={rule}>{failedRuleLabel(rule, failedRuleLabels)}</option>
                ))}
              </select>
            </div>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-14">排名</TableHead>
                <TableHead>股票</TableHead>
                <TableHead>动作</TableHead>
                <TableHead className="text-right">总分</TableHead>
                {metricColumns.map((metric) => (
                  <TableHead key={metric.key} className="text-right">{metric.label}</TableHead>
                ))}
                <TableHead className="text-right">风险/流动性</TableHead>
                <TableHead>为什么这个分数</TableHead>
                <TableHead className="w-24">回测成交</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pagedItems.map((item) => {
                const reason = item.reason ?? {};
                const riskScore = numberValue(reason.risk_score);
                const liquidityScore = numberValue(reason.liquidity_score);
                const itemFailedRules = failedRules(item);
                const risk = item.risk_control ?? {};
                return (
                  <TableRow key={`${item.trade_date}-${item.vt_symbol}`}>
                    <TableCell className="font-medium tabular-nums">{item.rank}</TableCell>
                    <TableCell>
                      <StockIdentityLink name={item.name} vtSymbol={item.vt_symbol} board={item.board} boardLabel={item.board_label} />
                    </TableCell>
                    <TableCell>
                      <span
                        className={cn(
                          "rounded-md border px-2 py-1 text-xs",
                          item.action === "BUY" ? "border-red-200 bg-red-50 text-rise dark:border-red-500/30 dark:bg-red-500/10" : "text-muted-foreground"
                        )}
                      >
                        {candidateActionLabel(item)}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatNumber(item.total_score, 2)}
                    </TableCell>
                    {metricColumns.map((metric) => {
                      const value = metricValue(reason, metric.key);
                      return (
                        <TableCell key={metric.key} className={cn("text-right tabular-nums", metric.className(value))}>
                          {metric.format(value)}
                        </TableCell>
                      );
                    })}
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {formatNumber(riskScore, 1)} / {formatNumber(liquidityScore, 1)}
                    </TableCell>
                    <TableCell
                      className="min-w-72 max-w-96 text-xs"
                      title={candidateScoreTooltip(reason, itemFailedRules, failedRuleLabels, risk)}
                    >
                      <CandidateScoreExplanation
                        reason={reason}
                        explain={item.strategy_explain}
                        rules={itemFailedRules}
                        labels={failedRuleLabels}
                        risk={risk}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => setTraceTarget({ vtSymbol: item.vt_symbol, tradeDate: item.trade_date })}
                          disabled={!activeBacktestId || isTailPreview}
                          title={
                            isTailPreview
                              ? "实时尾盘量化未落库，暂无历史回测成交链路"
                              : activeBacktestId
                                ? "查看该候选在选中回测里的成交/拒单情况"
                                : "先在「回测」tab选中一个回测，才能追踪候选的成交情况"
                          }
                        >
                          <Search size={14} />
                          回测成交
                        </Button>
                        {onAddToHolding && (
                          <Button size="sm" onClick={() => onAddToHolding(item)}>
                            加入持仓
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {filteredItems.length === 0 && <div className="border-t p-3 text-sm text-muted-foreground">当前过滤条件下没有候选。</div>}
          {filteredItems.length > pageSize && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t px-4 py-3 text-sm">
              <div className="text-muted-foreground">
                第 {pageStart}-{pageEnd} / {filteredItems.length} 个候选
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPage((value) => Math.max(value - 1, 1))}
                  disabled={currentPage <= 1}
                >
                  <ChevronLeft size={14} />
                  上一页
                </Button>
                <span className="text-xs text-muted-foreground">
                  {currentPage} / {pageCount}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPage((value) => Math.min(value + 1, pageCount))}
                  disabled={currentPage >= pageCount}
                >
                  下一页
                  <ChevronRight size={14} />
                </Button>
              </div>
            </div>
          )}
          {traceTarget && !isTailPreview && (
            <CandidateTracePanel
              backtestId={activeBacktestId}
              target={traceTarget}
              trace={traceQuery.data}
              isLoading={traceQuery.isFetching}
              error={traceQuery.error}
            />
          )}
        </>
      )}
    </section>
  );
}

function TailPreviewSummary({ meta }: { meta?: QuantScreenRun }) {
  return (
    <div className="rounded-md border bg-muted/20 p-3 text-sm">
      <div className="font-medium">实时尾盘量化</div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>量化日 {meta?.trade_date ?? "--"}</span>
        <span>基础日线 {meta?.base_daily_date ?? "--"}</span>
        <span>最新分钟线 {meta?.latest_intraday_date ?? "--"}</span>
        <span>快照 {compactDateTime(meta?.snapshot_updated_at) || "--"}</span>
        <span>分钟K {meta?.intraday_bar_count ?? 0} 只</span>
        <span>快照价 {meta?.snapshot_price_count ?? 0} 只</span>
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        使用盘中临时K线，只用于 14:30 决策参考，不写入历史候选和收益统计。
      </div>
    </div>
  );
}

function TailWorkflowSyncStrip({
  workflow,
  isLoading,
  error,
}: {
  workflow?: TailWorkflowStatus;
  isLoading: boolean;
  error?: unknown;
}) {
  if (isLoading && !workflow) {
    return (
      <div className="rounded-md border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        正在读取同步状态...
      </div>
    );
  }

  if (error && !workflow) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
        同步状态读取失败: {(error as Error).message ?? "请稍后刷新"}
      </div>
    );
  }

  if (!workflow) return null;

  const preview = workflow.tail_preview;
  const previewStatus = preview?.status ?? "unknown";
  const stateItems = [
    { label: "完整日线", value: workflow.daily_bar_latest_complete_date ?? workflow.daily_bar_latest_date, detail: compactDateTime(workflow.daily_bar_updated_at) },
    { label: "分钟线", value: workflow.minute_latest_date, detail: compactDateTime(workflow.minute_latest_time) },
    { label: "盘中快照", value: compactDateTime(workflow.intraday_snapshot_updated_at), detail: workflow.intraday_snapshot_trade_time },
    { label: "量化候选", value: workflow.candidate_latest_date, detail: compactDateTime(workflow.candidate_updated_at) },
    {
      label: "尾盘量化",
      value: preview?.trade_date ?? preview?.cached_trade_date ?? statusLabel(previewStatus),
      detail: preview?.message ?? (preview?.cached_recommendation_count != null ? `已生成 ${preview.cached_recommendation_count} 个推荐` : null),
    },
  ];

  const schedules = [
    { label: "14:30", schedule: workflow.tail_quant_schedule },
    { label: "18:00", schedule: workflow.eod_schedule },
  ];

  return (
    <div className="rounded-md border bg-muted/20 px-3 py-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="font-medium">同步状态</span>
          <CompactStatusPill status={previewStatus} />
          {workflow.status === "unavailable" ? <CompactStatusPill status="unavailable" /> : null}
        </div>
        <Button asChild size="sm" variant="outline" className="h-7 px-2 text-xs">
          <Link to="/data">数据同步</Link>
        </Button>
      </div>

      <div className="mt-2 grid gap-2 md:grid-cols-5">
        {stateItems.map((item) => (
          <div key={item.label} className="min-w-0">
            <div className="text-xs text-muted-foreground">{item.label}</div>
            <div className="mt-0.5 truncate text-sm font-medium tabular-nums">{item.value || "--"}</div>
            {item.detail ? <div className="mt-0.5 truncate text-xs text-muted-foreground">{item.detail}</div> : null}
          </div>
        ))}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 border-t pt-2 text-xs text-muted-foreground">
        {schedules.map((item) => (
          <span key={item.label}>
            {item.label} {statusLabel(item.schedule?.last_status)} {compactDateTime(item.schedule?.last_finished_at ?? item.schedule?.last_started_at) || "--"}
            {item.schedule?.last_message ? ` · ${item.schedule.last_message}` : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

function CandidateTracePanel({
  backtestId,
  target,
  trace,
  isLoading,
  error,
}: {
  backtestId?: number | null;
  target: { vtSymbol: string; tradeDate: string };
  trace?: BacktestCandidateTrace;
  isLoading: boolean;
  error: unknown;
}) {
  return (
    <div className="border-t p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-sm font-medium">候选到订单追踪</div>
          <div className="mt-1 text-xs text-muted-foreground">
            回测 #{backtestId ?? "--"} · {target.tradeDate} · {target.vtSymbol}
          </div>
        </div>
        {trace && <span className="rounded-md border px-2 py-1 text-xs">{traceStatusLabel(trace.status)}</span>}
      </div>
      {!backtestId ? (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">先运行或选择一个回测诊断，再查看候选进入组合执行链路的情况。</div>
      ) : isLoading ? (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">正在查询候选到订单链路...</div>
      ) : error ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">查询失败，请稍后重试。</div>
      ) : !trace ? (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">暂无追踪结果。</div>
      ) : (
        <div className="space-y-3">
          <div className="rounded-md border bg-muted/20 p-3 text-sm">
            <div className="font-medium">{trace.summary}</div>
            <div className="mt-2 grid gap-3 md:grid-cols-6">
              <TraceCell label="候选动作" value={trace.action === "BUY" ? "买入" : trace.action === "WATCH" ? "观察" : trace.action ?? "--"} />
              <TraceCell label="排名" value={trace.rank ?? "--"} />
              <TraceCell label="总分" value={formatNumber(trace.total_score, 1)} />
              <TraceCell label="计划执行日" value={trace.planned_execute_date ?? "--"} />
              <TraceCell label="订单状态" value={traceOrderStatus(trace.linked_order_status)} />
              <TraceCell label="订单原因" value={trace.linked_order_reason ?? "--"} />
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <TraceCell label="持仓数" value={trace.equity?.position_count ?? "--"} framed />
            <TraceCell label="拒单数" value={trace.orders.filter((row) => row.status === "rejected").length} framed />
          </div>
          <div className="grid gap-2 md:grid-cols-2">
            {trace.diagnostics.map((item) => (
              <div key={item.id} className="rounded-md border p-2 text-xs">
                <div className="font-medium">{diagnosticStatusLabel(item.status)}</div>
                <div className="mt-1 text-muted-foreground">{item.message}</div>
              </div>
            ))}
          </div>
          <NotPlannedContextPanel context={trace.not_planned_context} />
          <TraceOrderRows trace={trace} />
        </div>
      )}
    </div>
  );
}

function NotPlannedContextPanel({ context }: { context?: BacktestCandidateNotPlannedContext | null }) {
  if (!context) return null;
  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="font-medium">未进计划核查</div>
      <div className="mt-2 grid gap-3 md:grid-cols-6">
        <TraceCell label="具体原因" value={context.likely_reason_label ?? context.likely_reason ?? "--"} />
        <TraceCell label="理论买入排名" value={context.target_signal_rank == null ? "--" : `${context.target_signal_rank}`} />
        <TraceCell label="理论分数" value={formatNumber(context.target_signal_score, 1)} />
        <TraceCell label="理论形态" value={setupLabel(context.target_signal_setup)} />
        <TraceCell label="执行上限" value={`前 ${context.candidate_limit ?? "--"}`} />
        <TraceCell label="超出上限" value={context.target_exceeds_candidate_limit == null ? "--" : context.target_exceeds_candidate_limit ? "是" : "否"} />
        <TraceCell label="回测区间" value={`${context.backtest_start_date ?? "--"} ~ ${context.backtest_end_date ?? "--"}`} />
        <TraceCell label="首个信号日" value={context.first_signal_date ?? "--"} />
        <TraceCell label="当天计划数" value={context.signal_date_plan_count ?? 0} />
        <TraceCell label="候选BUY数" value={context.persisted_buy_candidate_count ?? 0} />
        <TraceCell label="股票池名次" value={context.target_universe_rank == null ? "--" : `${context.target_universe_rank}/${context.max_symbols ?? "--"}`} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <TraceMiniList
          title="当天候选前列"
          rows={(context.same_day_top_recommendations ?? []).slice(0, 5).map((row) => ({
            key: `${row.rank}-${row.vt_symbol}`,
            left: `${row.rank ?? "--"}. ${row.name ?? row.vt_symbol}`,
            right: `${row.action ?? "--"} · ${formatNumber(row.total_score, 1)}`,
          }))}
          empty="该日没有落库候选。"
        />
        <TraceMiniList
          title="当天计划买入"
          rows={(context.planned_buy_symbols ?? []).slice(0, 5).map((row) => ({
            key: `${row.execute_date}-${row.vt_symbol}`,
            left: `${row.rank ?? "--"}. ${row.name ?? row.vt_symbol}`,
            right: `${setupLabel(row.setup_type)} · ${formatNumber(row.score, 1)}`,
          }))}
          empty="该日没有理论买入计划。"
        />
      </div>
    </div>
  );
}

function TraceMiniList({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: Array<{ key: string; left: string; right: string }>;
  empty: string;
}) {
  return (
    <div className="rounded-md border p-2 text-xs">
      <div className="font-medium">{title}</div>
      {rows.length === 0 ? (
        <div className="mt-2 text-muted-foreground">{empty}</div>
      ) : (
        <div className="mt-2 space-y-1">
          {rows.map((row) => (
            <div key={row.key} className="flex items-center justify-between gap-2">
              <span className="truncate">{row.left}</span>
              <span className="shrink-0 tabular-nums text-muted-foreground">{row.right}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function TraceOrderRows({ trace }: { trace: BacktestCandidateTrace }) {
  if (trace.orders.length === 0 && trace.trades.length === 0) {
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">没有组合订单或成交。</div>;
  }
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>类型</TableHead>
            <TableHead>方向</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">数量</TableHead>
            <TableHead>原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trace.orders.map((row) => (
            <TableRow key={`order-${row.id ?? `${row.trade_date}-${row.side}`}`}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell>订单</TableCell>
              <TableCell>{sideLabel(row.side)}</TableCell>
              <TableCell>{traceOrderStatus(row.status)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.price)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume == null ? "--" : row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-muted-foreground">{row.reason ?? "--"}</TableCell>
            </TableRow>
          ))}
          {trace.trades.map((row) => (
            <TableRow key={`trade-${row.id ?? `${row.trade_date}-${row.side}`}`}>
              <TableCell className="tabular-nums">{row.trade_date}</TableCell>
              <TableCell>成交</TableCell>
              <TableCell>{sideLabel(row.side)}</TableCell>
              <TableCell>已成交</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.price)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.volume.toLocaleString()}</TableCell>
              <TableCell className="text-muted-foreground">{row.reason ?? "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function TraceCell({ label, value, framed }: { label: string; value?: string | number | null; framed?: boolean }) {
  return (
    <div className={framed ? "rounded-md border p-2" : undefined}>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-medium tabular-nums">{value ?? "--"}</div>
    </div>
  );
}

function failedRules(item: QuantRecommendation): string[] {
  const raw = item.reason?.failed_rules;
  return Array.isArray(raw) ? raw.map((rule) => String(rule)).filter(Boolean) : [];
}

function candidateActionLabel(item: QuantRecommendation): string {
  if (typeof item.signal_label === "string" && item.signal_label) return item.signal_label;
  return item.action === "BUY" ? "买入" : "观察";
}

function CandidateScoreExplanation({
  reason,
  explain,
  rules,
  labels,
  risk,
}: {
  reason: Record<string, unknown>;
  explain?: QuantStrategyExplain | null;
  rules: string[];
  labels: Record<string, string>;
  risk: Record<string, unknown>;
}) {
  const facts = candidateScoreFacts(reason);
  const market = candidateMarketFacts(reason);
  const contributions = topScoreContributions(reason.score_breakdown, 4);
  const rejected = rules.map((rule) => failedRuleLabel(rule, labels));
  const fallback = candidateScoreReason(reason, rules, labels, risk);
  return (
    <div className="space-y-1 leading-5">
      {explain && <StrategyFactorExplanation explain={explain} />}
      {facts.length > 0 ? (
        <div className="text-foreground">{facts.join(" · ")}</div>
      ) : (
          <div className="text-muted-foreground">{fallback}</div>
      )}
      {market && (
        <div className="text-muted-foreground">{market}</div>
      )}
      {contributions.length > 0 && (
        <div className="text-muted-foreground">分项贡献: {contributions.join(" / ")}</div>
      )}
      <div className="text-muted-foreground">
        总分按分项贡献相加后扣风险；低吸蓄势是同一策略内的连续加分。
      </div>
      {rejected.length > 0 && (
        <div className="text-fall">观察原因: {rejected.join(" / ")}</div>
      )}
    </div>
  );
}

function StrategyFactorExplanation({ explain }: { explain: QuantStrategyExplain }) {
  const setupLabels = (explain.setup_labels ?? []).filter(Boolean).slice(0, 4);
  const factors = (explain.positive_factors ?? []).filter(Boolean).slice(0, 5);
  const market = (explain.market_context ?? []).filter(Boolean).slice(0, 3);
  const flags = [
    explain.research_only ? "研究观察" : null,
    explain.not_used_for_signal_score ? "未入默认评分" : null,
  ].filter((label): label is string => Boolean(label));

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1">
        <span className="font-medium text-foreground">{explain.candidate_family_label ?? explain.strategy_name ?? "策略因子"}</span>
        {setupLabels.map((label) => (
          <span key={label} className="rounded-md border px-1.5 py-0.5 text-muted-foreground">
            {label}
          </span>
        ))}
        {flags.map((label) => (
          <span key={label} className="rounded-md border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
            {label}
          </span>
        ))}
      </div>
      {factors.length > 0 && (
        <div className="text-foreground">因子: {factors.map(factorText).join(" · ")}</div>
      )}
      {market.length > 0 && (
        <div className="text-muted-foreground">环境: {market.map(factorText).join(" · ")}</div>
      )}
      {(explain.risk_factors ?? []).length > 0 && (
        <div className="text-fall">风险: {(explain.risk_factors ?? []).slice(0, 3).map(factorText).join(" / ")}</div>
      )}
    </div>
  );
}

function factorText(factor: QuantStrategyExplainFactor): string {
  const value = factor.value == null || factor.value === "" ? "" : `${factor.value}`;
  return value ? `${factor.label}${value}` : factor.label;
}

function candidateScoreFacts(reason: Record<string, unknown>): string[] {
  const lowSuctionDays = numberValue(reason.low_suction_days);
  const convergence = numberValue(reason.ma_convergence_pct);
  const lowSuctionScore = numberValue(reason.low_suction_buildup_score);
  const supportHoldDays = numberValue(reason.support_hold_days);
  const lowSuctionStage = typeof reason.low_suction_stage_label === "string" ? reason.low_suction_stage_label : null;
  const lowSuctionQuality = typeof reason.low_suction_launch_quality_label === "string" ? reason.low_suction_launch_quality_label : null;
  const lowSuctionDragon = typeof reason.low_suction_dragon_label === "string" ? reason.low_suction_dragon_label : null;
  const supportType = typeof reason.support_type === "string" ? reason.support_type : null;
  const state = typeof reason.dragon_state === "string" ? reason.dragon_state : null;
  const parts: string[] = [];
  if (state) parts.push(dragonStateLabel(state));
  if (supportType) parts.push(supportTypeLabel(supportType));
  if (lowSuctionStage && lowSuctionStage !== "非低吸蓄势") parts.push(lowSuctionStage);
  if (lowSuctionQuality && lowSuctionQuality !== "非低吸买点") parts.push(lowSuctionQuality);
  if (lowSuctionDragon && lowSuctionDragon !== "非低吸龙回头" && lowSuctionDragon !== "标准龙回头") parts.push(lowSuctionDragon);
  if (lowSuctionDays != null) parts.push(`低吸${lowSuctionDays.toFixed(0)}天`);
  if (supportHoldDays != null) parts.push(`支撑${supportHoldDays.toFixed(0)}天`);
  if (convergence != null) parts.push(`均线收敛${formatPct(convergence)}`);
  if (lowSuctionScore != null) parts.push(`低吸分${formatNumber(lowSuctionScore, 1)}`);
  return parts;
}

function candidateMarketFacts(reason: Record<string, unknown>): string {
  const summary = reason.market_context_summary;
  if (summary && typeof summary === "object") {
    const row = summary as Record<string, unknown>;
    const label = typeof row.label === "string" ? row.label : null;
    const notes = Array.isArray(row.notes) ? row.notes.map((item) => String(item)).filter(Boolean).slice(0, 3) : [];
    const parts = [label, ...notes].filter(Boolean);
    if (parts.length) return `大盘: ${parts.join(" / ")}`;
  }
  const regime = typeof reason.dynamic_market_label === "string" ? reason.dynamic_market_label : null;
  const warning = typeof reason.market_warning_label === "string" ? reason.market_warning_label : null;
  const fund = typeof reason.fund_flow_label === "string" ? reason.fund_flow_label : null;
  const recovery = typeof reason.recovery_label === "string" ? reason.recovery_label : null;
  const parts = [regime, warning, fund, recovery].filter(Boolean);
  return parts.length ? `大盘: ${parts.join(" / ")}` : "";
}

function candidateScoreReason(
  reason: Record<string, unknown>,
  rules: string[],
  labels: Record<string, string>,
  risk: Record<string, unknown>
): string {
  const notes = Array.isArray(reason.score_notes)
    ? reason.score_notes.map((item) => String(item)).filter(Boolean)
    : [];
  const contributions = topScoreContributions(reason.score_breakdown, 3);
  const lowSuctionDays = numberValue(reason.low_suction_days);
  const convergence = numberValue(reason.ma_convergence_pct);
  const lowSuctionScore = numberValue(reason.low_suction_buildup_score);
  const parts: string[] = [];
  const state = typeof reason.dragon_state === "string" ? reason.dragon_state : null;
  if (state) parts.push(`状态${dragonStateLabel(state)}`);
  if (lowSuctionDays != null) parts.push(`低吸${lowSuctionDays.toFixed(0)}天`);
  if (convergence != null) parts.push(`均线收敛${formatPct(convergence)}`);
  if (lowSuctionScore != null) parts.push(`蓄势分${formatNumber(lowSuctionScore, 1)}`);
  if (parts.length && contributions.length) return `${parts.join("，")}；来源 ${contributions.join("、")}`;
  if (parts.length) return parts.join("，");
  if (contributions.length) return `主要来源 ${contributions.join("、")}`;
  if (notes.length) return notes.slice(0, 3).join("；");
  if (rules.length) return rules.map((rule) => failedRuleLabel(rule, labels)).join(", ");
  return `止损 ${formatPct(numberValue(risk.stop_loss_pct) ? -numberValue(risk.stop_loss_pct)! * 100 : null)}`;
}

function candidateScoreTooltip(
  reason: Record<string, unknown>,
  rules: string[],
  labels: Record<string, string>,
  risk: Record<string, unknown>
): string {
  const notes = Array.isArray(reason.score_notes)
    ? reason.score_notes.map((item) => readableScoreNote(String(item))).filter(Boolean)
    : [];
  const breakdown = Array.isArray(reason.score_breakdown)
    ? reason.score_breakdown
        .map((item) => {
          if (!item || typeof item !== "object") return "";
          const row = item as Record<string, unknown>;
          const name = String(row.name ?? "");
          const score = numberValue(row.score);
          const weight = numberValue(row.weight);
          const contribution = numberValue(row.contribution);
          if (!name) return "";
          const scoreText = score == null ? "--" : formatNumber(score, 1);
          const weightText = weight == null ? "--" : `${formatNumber(weight * 100, 0)}%`;
          const contributionText = contribution == null ? "--" : formatNumber(contribution, 2);
          return `${name}: ${scoreText} * ${weightText} = ${contributionText}`;
        })
        .filter(Boolean)
    : [];
  const fallback = candidateScoreReason(reason, rules, labels, risk);
  return [...notes, ...breakdown].join("\n") || fallback;
}

function traceStatusLabel(status: string): string {
  if (status === "filled") return "已成交";
  if (status === "rejected") return "已拒单";
  if (status === "watch_not_bought") return "观察未买";
  if (status === "candidate_not_planned") return "候选未进计划";
  if (status === "signal_snapshot_not_persisted") return "信号未进计划";
  if (status === "planned_not_ordered") return "计划未下单";
  if (status === "not_selected") return "未入选";
  return status || "--";
}

function traceOrderStatus(status?: string | null): string {
  if (status === "filled") return "成交";
  if (status === "rejected") return "拒单";
  if (status === "pending") return "待执行";
  if (status === "not_ordered") return "未下单";
  return status || "--";
}

function setupLabel(value?: string | null): string {
  if (value === "stealth_low_suction") return "低吸洗盘";
  if (value === "dragon_pullback") return "龙回头";
  return value || "--";
}

function diagnosticStatusLabel(status: string): string {
  if (status === "pass") return "通过";
  if (status === "warning") return "需核查";
  if (status === "missing") return "缺失";
  if (status === "info") return "信息";
  return status || "--";
}

function sideLabel(side: string): string {
  if (side === "BUY") return "买入";
  if (side === "SELL") return "卖出";
  return side || "--";
}

function failedRuleLabel(rule: string, labels: Record<string, string> = {}): string {
  if (labels[rule]) return labels[rule];
  if (rule === "total_score") return "总分不足";
  if (rule === "ma5_distance") return "MA5距离";
  if (rule === "breakout_distance") return "突破距离";
  if (rule === "volume_confirmation") return "量能确认";
  if (rule === "trend_quality") return "趋势质量";
  if (rule === "limit_up_presence") return "近20日无涨停";
  if (rule === "limit_up_recency") return "涨停后时间";
  if (rule === "pullback_position") return "回踩位置";
  if (rule === "ma20_support") return "MA20支撑";
  if (rule === "ma_convergence_too_wide_without_low_suction") return "均线发散且缺少低吸蓄势";
  if (rule === "risk_score") return "风险不足";
  if (rule === "liquidity_score") return "流动性不足";
  return rule;
}

function recommendationMetricColumns(strategy?: QuantStrategyOption) {
  const keys = strategy?.primary_metric_keys?.length ? strategy.primary_metric_keys : ["ma5_distance_pct"];
  return keys.slice(0, 3).map((key) => ({
    key,
    label: strategy?.evidence_labels?.[key] ?? metricLabel(key),
    format: metricFormatter(key),
    className: metricColorClass(key),
  }));
}

function metricValue(reason: Record<string, unknown>, key: string): string | number | null {
  const raw = reason[key];
  if (typeof raw === "string" && raw) return raw;
  if (typeof raw === "number" && Number.isFinite(raw)) return raw;
  return null;
}

function metricLabel(key: string): string {
  const labels: Record<string, string> = {
    dragon_state: "龙回头状态",
    support_type: "承接类型",
    low_suction_days: "低吸天数",
    support_hold_days: "支撑天数",
    ma_convergence_pct: "均线收敛",
    low_suction_buildup_score: "蓄势分",
    ma5_distance_pct: "MA5距离",
    ma20_distance_pct: "MA20距离",
    close_to_prior_high_pct: "距60日高点",
    volume_ratio_5d_20d: "量能比",
    days_since_limit_up: "距涨停天数",
    limit_up_count_20d: "20日涨停数",
  };
  return labels[key] ?? key;
}

function metricFormatter(key: string) {
  if (key === "dragon_state") return dragonStateLabel;
  if (key === "support_type") return supportTypeLabel;
  if (key.endsWith("_score")) return formatScoreMetric;
  if (key.includes("ratio")) return formatRatio;
  if (key.includes("days") || key.includes("count")) return formatIntegerMetric;
  return formatPercentMetric;
}

function metricColorClass(key: string) {
  if (key === "dragon_state") return dragonStateClass;
  if (key === "support_type") return () => undefined;
  if (key.endsWith("_score")) return scoreColorClass;
  if (key.includes("ratio")) return ratioColorClass;
  if (key.includes("days") || key.includes("count")) return () => undefined;
  return percentColorClass;
}

function formatPercentMetric(value?: string | number | null): string {
  return formatPct(metricNumber(value));
}

function percentColorClass(value?: string | number | null): string | undefined {
  return priceColorClass(metricNumber(value));
}

function formatIntegerMetric(value?: string | number | null): string {
  const number = metricNumber(value);
  return number == null ? "--" : number.toFixed(0);
}

function formatRatio(value?: string | number | null): string {
  const number = metricNumber(value);
  return number == null ? "--" : `${number.toFixed(2)}x`;
}

function formatScoreMetric(value?: string | number | null): string {
  const number = metricNumber(value);
  return number == null ? "--" : number.toFixed(1);
}

function metricNumber(value?: string | number | null): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function dragonStateLabel(value?: string | number | null): string {
  const state = String(value ?? "");
  const labels: Record<string, string> = {
    TAIL_BUY_READY: "龙回头买点",
    LOW_SUCTION_BUILDUP: "低吸蓄势",
    SUPPORT_ACCEPTED: "均线承接",
    PULLBACK_OBSERVE: "回踩观察",
    STRONG_LEG_CONFIRMED: "强势确认",
    DISTRIBUTION_RISK: "派发风险",
    INVALIDATED: "破位失效",
  };
  return (labels[state] ?? state) || "--";
}

function readableScoreNote(note: string): string {
  if (note.startsWith("状态 ")) return `状态 ${dragonStateLabel(note.slice(3))}`;
  if (note.startsWith("承接 ")) return `承接 ${supportTypeLabel(note.slice(3))}`;
  return note;
}

function supportTypeLabel(value?: string | number | null): string {
  const support = String(value ?? "");
  const labels: Record<string, string> = {
    ma5_reclaim: "MA5承接",
    ma10_support: "MA10承接",
    ma20_support: "MA20承接",
    none: "未承接",
  };
  return (labels[support] ?? support) || "--";
}

function dragonStateClass(value?: string | number | null): string | undefined {
  const state = String(value ?? "");
  if (state === "TAIL_BUY_READY" || state === "LOW_SUCTION_BUILDUP") return "text-rise";
  if (state === "DISTRIBUTION_RISK" || state === "INVALIDATED") return "text-fall";
  return undefined;
}

function scoreColorClass(value?: string | number | null): string | undefined {
  const number = metricNumber(value);
  if (number == null) return undefined;
  return number >= 85 ? "text-rise" : number < 60 ? "text-fall" : undefined;
}

function topScoreContributions(value: unknown, limit: number): string[] {
  if (!Array.isArray(value)) return [];
  const ranked = value
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const row = item as Record<string, unknown>;
      const name = String(row.name ?? "");
      const contribution = metricNumber(row.contribution as string | number | null);
      if (!name || contribution == null || contribution <= 0) return null;
      return { name, contribution };
    })
    .filter((item): item is { name: string; contribution: number } => Boolean(item))
    .sort((left, right) => right.contribution - left.contribution);
  const selected = ranked.slice(0, limit);
  const lowSuction = ranked.find((item) => item.name === "低吸蓄势");
  if (lowSuction && limit > 0 && !selected.some((item) => item.name === lowSuction.name)) {
    if (selected.length >= limit) {
      selected[selected.length - 1] = lowSuction;
    } else {
      selected.push(lowSuction);
    }
  }
  return selected.map((item) => `${item.name}+${item.contribution.toFixed(2)}`);
}

function ratioColorClass(value?: string | number | null): string | undefined {
  const number = metricNumber(value);
  return number == null ? undefined : number >= 1 ? "text-rise" : "text-fall";
}

function candidateStats(items: QuantRecommendation[]) {
  const failedRuleSet = new Set<string>();
  let buyCount = 0;
  let watchCount = 0;
  for (const item of items) {
    if (item.action === "BUY") {
      buyCount += 1;
    } else {
      watchCount += 1;
    }
    for (const rule of failedRules(item)) {
      failedRuleSet.add(rule);
    }
  }
  return {
    buyCount,
    watchCount,
    failedRules: [...failedRuleSet].sort(),
  };
}

function compactDateTime(value?: string | null): string {
  if (!value) return "";
  return value.replace("T", " ").slice(0, 16);
}

function statusLabel(status?: string | null): string {
  if (!status) return "--";
  const labels: Record<string, string> = {
    ready: "可用",
    waiting: "等待",
    waiting_for_intraday_data: "等待分钟线",
    unavailable: "不可用",
    succeeded: "成功",
    failed: "失败",
    running: "运行中",
    pending: "等待",
    unknown: "未知",
  };
  return labels[status] ?? status;
}

function CompactStatusPill({ status }: { status?: string | null }) {
  const className =
    status === "ready" || status === "succeeded"
      ? "border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300"
      : status === "waiting" || status === "waiting_for_intraday_data" || status === "pending"
        ? "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
        : status === "failed" || status === "unavailable"
          ? "border-red-200 bg-red-50 text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300"
          : "border-border bg-background text-muted-foreground";

  return (
    <span className={cn("rounded-md border px-1.5 py-0.5 text-xs", className)}>
      {statusLabel(status)}
    </span>
  );
}

export function QuantBoardSelector({
  selectedBoards,
  activeBoards,
  onChange,
  onRun,
  isRunning,
}: {
  selectedBoards: string[];
  activeBoards: string[];
  onChange: (boards: string[]) => void;
  onRun?: () => void;
  isRunning: boolean;
}) {
  const toggleBoard = (board: QuantBoard, checked: boolean) => {
    const current = new Set(selectedBoards);
    if (checked) {
      current.add(board);
    } else {
      current.delete(board);
    }
    const next = QUANT_BOARD_OPTIONS
      .map((item) => item.value)
      .filter((item) => current.has(item));
    onChange(next.length ? next : ["main"]);
  };

  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">股票池</span>
        {QUANT_BOARD_OPTIONS.map((option) => (
          <label key={option.value} className="flex h-8 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={selectedBoards.includes(option.value)}
              onChange={(event) => toggleBoard(option.value, event.target.checked)}
            />
            {option.label}
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">
          当前结果: {boardLabels(activeBoards)} · 观察前 {DEFAULT_CANDIDATE_OBSERVATION_LIMIT} · 执行前 {DEFAULT_EXECUTION_CANDIDATE_LIMIT}
        </span>
        {onRun && (
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            刷新候选并回测
          </Button>
        )}
      </div>
    </div>
  );
}

function QuantEmptyState({
  status,
  message,
  strategy,
}: {
  status?: string;
  message?: string;
  strategy?: QuantStrategyOption;
}) {
  const unavailable = status === "unavailable";
  const metrics = recommendationMetricColumns(strategy);
  return (
    <div className="p-4">
      <div className={cn("rounded-lg border p-4", unavailable ? "border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10" : "bg-muted/20")}>
        <div className="flex items-start gap-3">
          {unavailable ? <AlertTriangle size={18} className="mt-0.5 text-amber-700 dark:text-amber-400" /> : <Database size={18} className="mt-0.5 text-muted-foreground" />}
          <div className="min-w-0 flex-1">
            <div className="font-medium">{unavailable ? "量化数据还不能读取" : "还没有量化候选"}</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {message || "选择起始交易日后刷新候选并回测。系统会按真实交易日逐日打分、生成候选并自动回测。"}
            </div>
            {strategy && (
              <div className="mt-2 text-xs text-muted-foreground">
                当前策略: {strategy.name} · 关键指标 {metrics.map((metric) => metric.label).join(" / ")}
              </div>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              <Button asChild size="sm" variant="outline">
                <Link to="/data">
                  <Database size={15} />
                  查看数据状态
                </Link>
              </Button>
            </div>
            {unavailable && (
              <div className="mt-3 text-xs text-amber-700 dark:text-amber-400">
                先配置 PostgreSQL 的 DATABASE_URL，并同步股票清单、日线和可选财报/资金流数据。
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
