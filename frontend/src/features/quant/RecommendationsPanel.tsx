import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { AlertTriangle, Database, Play, RefreshCw, Search, ShieldCheck } from "lucide-react";
import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { formatNumber, numberValue } from "@/lib/backtest-utils";
import { QUANT_BOARD_OPTIONS, boardLabels, type QuantBoard } from "@/features/quant/constants";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TradingDateSelector } from "@/features/quant/TradingDateSelector";
import { fetchBacktestCandidateTrace, type BacktestCandidateNotPlannedContext, type BacktestCandidateTrace, type QuantRecommendation, type QuantScreenRunItem, type QuantStrategyOption } from "@/api/quant";

export function RecommendationsPanel({
  isLoading,
  isError,
  error,
  items,
  tradeDate,
  runId,
  strategyVersion,
  includedBoards,
  screenRuns,
  tradingDates,
  screenStartDate,
  onScreenStartDateChange,
  selectedTradeDate,
  onSelectedTradeDateChange,
  strategies,
  selectedStrategy,
  onStrategyChange,
  selectedBoards,
  onSelectedBoardsChange,
  activeBacktestId,
  status,
  message,
  syncedCount,
  onRetry,
  onRunScreen,
  isRunningScreen,
}: {
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  items: QuantRecommendation[];
  tradeDate?: string;
  runId?: number | null;
  strategyVersion?: string;
  includedBoards?: string[];
  screenRuns: QuantScreenRunItem[];
  tradingDates: string[];
  screenStartDate: string;
  onScreenStartDateChange: (tradeDate: string) => void;
  selectedTradeDate: string;
  onSelectedTradeDateChange: (tradeDate: string) => void;
  strategies: QuantStrategyOption[];
  selectedStrategy: string;
  onStrategyChange: (strategy: string) => void;
  selectedBoards: string[];
  onSelectedBoardsChange: (boards: string[]) => void;
  activeBacktestId?: number | null;
  status?: string;
  message?: string;
  syncedCount: number;
  onRetry: () => void;
  onRunScreen: () => void;
  isRunningScreen: boolean;
}) {
  const [actionFilter, setActionFilter] = useState<"all" | "BUY" | "WATCH">("all");
  const [failedRuleFilter, setFailedRuleFilter] = useState("all");
  const [traceTarget, setTraceTarget] = useState<{ vtSymbol: string; tradeDate: string } | null>(null);
  const activeBoards = includedBoards?.length ? includedBoards : selectedBoards;
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
  const availableDates = Array.from(
    new Set([...tradingDates, ...screenRuns.map((run) => run.trade_date), selectedTradeDate, screenStartDate].filter(Boolean))
  );
  const stats = useMemo(() => candidateStats(items), [items]);
  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (actionFilter !== "all" && item.action !== actionFilter) return false;
      if (failedRuleFilter !== "all" && !failedRules(item).includes(failedRuleFilter)) return false;
      return true;
    });
  }, [actionFilter, failedRuleFilter, items]);
  const runDates = new Set(screenRuns.filter((run) => run.status === "succeeded").map((run) => run.trade_date));
  const runDateCount = availableDates.filter((date) => runDates.has(date)).length;
  const missingRunCount = Math.max(availableDates.length - runDateCount, 0);
  const traceQuery = useQuery({
    queryKey: ["backtestCandidateTrace", activeBacktestId, traceTarget?.vtSymbol, traceTarget?.tradeDate],
    queryFn: () => fetchBacktestCandidateTrace(activeBacktestId!, traceTarget!.vtSymbol, traceTarget!.tradeDate),
    enabled: Boolean(activeBacktestId && traceTarget),
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
            {tradeDate ?? "--"} · {runId ? `运行 #${runId}` : "未运行"} · {strategyVersion ?? "--"} · 分组同步 {syncedCount} 只
          </div>
        </div>
        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_260px]">
          <TradingDateSelector
            label="生成区间起点"
            value={screenStartDate}
            dates={availableDates}
            onChange={onScreenStartDateChange}
            getOptionLabel={(date) => {
              const run = latestRunByDate.get(date);
              return run ? `${date} · #${run.id} · 候选 ${run.recommendation_count}` : `${date} · 未运行`;
            }}
            className="items-start gap-1"
            selectClassName="mt-1 w-full min-w-0"
          />
          <TradingDateSelector
            label="查看交易日"
            value={selectedTradeDate}
            dates={availableDates}
            onChange={onSelectedTradeDateChange}
            getOptionLabel={(date) => {
              const run = latestRunByDate.get(date);
              return run ? `${date} · #${run.id} · 候选 ${run.recommendation_count}` : `${date} · 未运行`;
            }}
            className="items-start gap-1"
            selectClassName="mt-1 w-full min-w-0"
          />
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">策略</span>
            <select
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              value={selectedStrategy}
              onChange={(event) => onStrategyChange(event.target.value)}
            >
              {strategies.length === 0 ? (
                <option value={selectedStrategy}>主线强势回踩低吸</option>
              ) : (
                strategies.map((strategy) => (
                  <option key={strategy.id} value={strategy.id}>
                    {strategy.name}
                  </option>
                ))
              )}
            </select>
          </label>
        </div>
        <QuantBoardSelector
          selectedBoards={selectedBoards}
          activeBoards={activeBoards}
          onChange={onSelectedBoardsChange}
          onRun={onRunScreen}
          isRunning={isRunningScreen}
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
              <span>已运行 {runDateCount} 日</span>
              <span>未运行 {missingRunCount} 日</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="h-8 rounded-md border bg-background px-2 text-sm"
                value={actionFilter}
                onChange={(event) => setActionFilter(event.target.value as "all" | "BUY" | "WATCH")}
              >
                <option value="all">全部动作</option>
                <option value="BUY">仅买入</option>
                <option value="WATCH">仅观察</option>
              </select>
              <select
                className="h-8 rounded-md border bg-background px-2 text-sm"
                value={failedRuleFilter}
                onChange={(event) => setFailedRuleFilter(event.target.value)}
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
                <TableHead>核查</TableHead>
                <TableHead className="w-24">回测追踪</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredItems.map((item) => {
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
                        {item.action === "BUY" ? "买入" : "观察"}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatNumber(item.total_score, 2)}
                    </TableCell>
                    {metricColumns.map((metric) => {
                      const value = numberValue(reason[metric.key]);
                      return (
                        <TableCell key={metric.key} className={cn("text-right tabular-nums", metric.className(value))}>
                          {metric.format(value)}
                        </TableCell>
                      );
                    })}
                    <TableCell className="text-right text-xs text-muted-foreground">
                      {formatNumber(riskScore, 1)} / {formatNumber(liquidityScore, 1)}
                    </TableCell>
                    <TableCell className="max-w-60 text-xs text-muted-foreground">
                      {itemFailedRules.length ? itemFailedRules.map((rule) => failedRuleLabel(rule, failedRuleLabels)).join(", ") : `止损 ${formatPct(numberValue(risk.stop_loss_pct) ? -numberValue(risk.stop_loss_pct)! * 100 : null)}`}
                    </TableCell>
                    <TableCell>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setTraceTarget({ vtSymbol: item.vt_symbol, tradeDate: item.trade_date })}
                        disabled={!activeBacktestId}
                      >
                        <Search size={14} />
                        追踪
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {filteredItems.length === 0 && <div className="border-t p-3 text-sm text-muted-foreground">当前过滤条件下没有候选。</div>}
          {traceTarget && (
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
        <div className="rounded-md border p-3 text-sm text-muted-foreground">先运行或选择一个组合回测，再追踪候选是否真实下单。</div>
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
          <div className="grid gap-3 md:grid-cols-4">
            <TraceCell label="现金" value={formatAmount(trace.equity?.cash)} framed />
            <TraceCell label="持仓市值" value={formatAmount(trace.equity?.market_value)} framed />
            <TraceCell label="总权益" value={formatAmount(trace.equity?.total_equity)} framed />
            <TraceCell label="持仓数" value={trace.equity?.position_count ?? "--"} framed />
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
            left: row.name ?? row.vt_symbol,
            right: `${row.execute_date ?? "--"} · ${formatNumber(row.score, 1)}`,
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
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">没有真实组合订单或成交。</div>;
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
            <TableHead className="text-right">金额</TableHead>
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
              <TableCell className="text-right tabular-nums">--</TableCell>
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
              <TableCell className="text-right tabular-nums">{formatAmount(row.amount)}</TableCell>
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

function traceStatusLabel(status: string): string {
  if (status === "filled") return "已成交";
  if (status === "rejected") return "已拒单";
  if (status === "watch_not_bought") return "观察未买";
  if (status === "candidate_not_planned") return "候选未进计划";
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
  if (rule === "risk_score") return "风险不足";
  if (rule === "liquidity_score") return "流动性不足";
  return rule;
}

function recommendationMetricColumns(strategy?: QuantStrategyOption) {
  const keys = strategy?.primary_metric_keys?.length ? strategy.primary_metric_keys : ["ma5_distance_pct"];
  return keys.slice(0, 2).map((key) => ({
    key,
    label: strategy?.evidence_labels?.[key] ?? metricLabel(key),
    format: metricFormatter(key),
    className: metricColorClass(key),
  }));
}

function metricLabel(key: string): string {
  const labels: Record<string, string> = {
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
  if (key.includes("ratio")) return formatRatio;
  if (key.includes("days") || key.includes("count")) return formatIntegerMetric;
  return formatPct;
}

function metricColorClass(key: string) {
  if (key.includes("ratio")) return ratioColorClass;
  if (key.includes("days") || key.includes("count")) return () => undefined;
  return priceColorClass;
}

function formatIntegerMetric(value?: number | null): string {
  return value == null ? "--" : value.toFixed(0);
}

function formatRatio(value?: number | null): string {
  return value == null ? "--" : `${value.toFixed(2)}x`;
}

function ratioColorClass(value?: number | null): string | undefined {
  return value == null ? undefined : value >= 1 ? "text-rise" : "text-fall";
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
          当前结果: {boardLabels(activeBoards)}
        </span>
        {onRun && (
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            生成区间候选
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
              {message || "选择起始交易日后生成区间候选。系统会按真实交易日逐日打分并落库。"}
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
