/**
 * StockResearchPage — 个股投研 (重写 StockDetailPage)
 *
 * Core innovation: "Identity Card" showing all concepts a stock belongs to,
 * each with today's change_pct — so users see which "mainline" is driving it.
 *
 * Layout: Quote header → Identity card (concept tag cloud) → K-line →
 *         Business + Financials → Fund flow + Events
 */
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchStockDetail,
  fetchStockSnapshot,
  fetchStockBusiness,
} from "@/api/stocks";
import { fetchConceptCards } from "@/api/research";
import { fetchLimitPools } from "@/api/market";
import {
  createSymbolBacktest,
  fetchBacktestAudit,
  fetchQuantStrategies,
  fetchLatestSymbolReplay,
  fetchSymbolTradePlan,
  fetchLatestSymbolBacktest,
  type BacktestAudit,
  type BacktestAuditEvent,
  type BacktestTrade,
  type QuantStrategyOption,
  type SymbolTradePlan,
  type SymbolLatestBacktest,
  type SymbolStrategyReplay,
  type StrategyReplayEvent,
} from "@/api/quant";
import { StockQuoteHeader } from "@/features/stocks/StockQuoteHeader";
import { StockKlineChart, type KlineMarker } from "@/features/stocks/StockKlineChart";
import { StockIndicatorPanel } from "@/features/stocks/StockIndicatorPanel";
import { StockFinanceChart } from "@/features/stocks/StockFinanceChart";
import { deriveStockReturnSummary, type ClosedReturnTrade } from "@/features/stocks/stockReturnMetrics";
import { DEFAULT_BACKTEST_START } from "@/features/quant/constants";
import { ConceptTag } from "@/components/ConceptTag";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatPct, formatPrice, priceColorClass, cn } from "@/lib/utils";
import type { ConceptCard, ShenwanClassification, StockConceptCardsResponse, ConceptHint } from "@/types/research";
import type { StockSnapshot, StockBusiness as StockBusinessType } from "@/api/types";
import {
  Fingerprint,
  ShieldCheck,
  Database,
  Radio,
  Building2,
  Flame,
  ArrowRight,
  TrendingUp,
  BarChart3,
  RefreshCw,
  FileText,
} from "lucide-react";

export function StockDetailPage() {
  const { vtSymbol } = useParams<{ vtSymbol: string }>();
  const queryClient = useQueryClient();
  const [backtestStart, setBacktestStart] = useState(DEFAULT_BACKTEST_START);
  const [singleBacktestStrategy, setSingleBacktestStrategy] = useState("mainline_leader_pullback");
  const [selectedBacktestMarkerId, setSelectedBacktestMarkerId] = useState<string | null>(null);

  const quoteQuery = useQuery({
    queryKey: ["stock-detail", vtSymbol],
    queryFn: () => fetchStockDetail(vtSymbol!),
    enabled: !!vtSymbol,
  });

  const snapshotQuery = useQuery({
    queryKey: ["stock-snapshot", vtSymbol],
    queryFn: () => fetchStockSnapshot(vtSymbol!),
    enabled: !!vtSymbol,
  });

  // Concept cards — the core innovation
  const conceptQuery = useQuery({
    queryKey: ["conceptCards", vtSymbol],
    queryFn: () => fetchConceptCards(vtSymbol!),
    staleTime: 30_000,
    enabled: !!vtSymbol,
  });

  // Business data
  const businessQuery = useQuery({
    queryKey: ["stock-business", vtSymbol],
    queryFn: () => fetchStockBusiness(vtSymbol!),
    enabled: !!vtSymbol,
  });

  // Limit pool data — for seal order (封单) display
  const limitPoolQuery = useQuery({
    queryKey: ["limit-pools-seal", vtSymbol],
    queryFn: () => fetchLimitPools(),
    staleTime: 60_000,
    enabled: !!vtSymbol,
  });

  const strategiesQuery = useQuery({
    queryKey: ["quantStrategies"],
    queryFn: fetchQuantStrategies,
    staleTime: 60_000,
  });

  const sealInfo = useMemo(() => {
    const pools = limitPoolQuery.data?.pools ?? {};
    const stockCode = vtSymbol!.split(".")[0];
    // Backend pool keys: zt, zt_previous, strong, zbgc, dtgc
    for (const poolKey of ["zt", "strong", "zbgc", "dtgc"] as const) {
      const group = pools[poolKey];
      const items = group?.items ?? [];
      const match = items.find((item) => item.symbol === stockCode);
      if (match) {
        return {
          limit_amount: match.limit_amount ?? null,
          limit_pool_type: poolKey,
          continuous_limit_up_count: match.limit_up_count ?? null,
        };
      }
    }
    return null;
  }, [limitPoolQuery.data, vtSymbol]);

  // 候选筛选时已预算并存储的买卖计划，单股详情直接读取，避免重跑回测
  const tradePlanQuery = useQuery({
    queryKey: ["symbolTradePlan", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchSymbolTradePlan(vtSymbol!, singleBacktestStrategy),
    enabled: !!vtSymbol,
    staleTime: 30_000,
  });

  const latestReplayQuery = useQuery({
    queryKey: ["symbolLatestReplay", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchLatestSymbolReplay(vtSymbol!, singleBacktestStrategy),
    enabled: !!vtSymbol,
    staleTime: 30_000,
  });
  const latestReplay = latestReplayQuery.data?.status === "ready" ? latestReplayQuery.data : null;

  // 单股回测结果缓存：读最近 symbol 回测，免重算；无缓存时自动创建一次
  const latestBacktestQuery = useQuery({
    queryKey: ["symbolLatestBacktest", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchLatestSymbolBacktest(vtSymbol!, singleBacktestStrategy),
    enabled: false,
    staleTime: 30_000,
  });
  const latestBacktest = latestBacktestQuery.data?.status === "ready" ? latestBacktestQuery.data : null;

  const latestAuditQuery = useQuery({
    queryKey: ["symbolLatestBacktestAudit", latestBacktest?.backtest_id, vtSymbol],
    queryFn: () => fetchBacktestAudit(Number(latestBacktest!.backtest_id), vtSymbol!, 500),
    enabled: Boolean(vtSymbol && latestBacktest?.backtest_id),
    staleTime: 30_000,
  });

  const singleBacktestMutation = useMutation({
    mutationFn: () =>
      createSymbolBacktest({
        vt_symbol: vtSymbol!,
        strategy: singleBacktestStrategy,
        start: backtestStart,
        persist: true,
        min_entry_score: 68,
        strict_entry: true,
        execution_model: "strict_1430",
        minute_interval: "1m",
        tail_entry_start: "14:30",
        tail_entry_end: "14:30",
        tail_entry_ma5_tolerance_pct: 1.5,
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["symbolLatestBacktest"] });
      queryClient.invalidateQueries({ queryKey: ["symbolLatestBacktestAudit"] });
    },
  });
  const backtestAudit = singleBacktestMutation.data?.audit ?? latestAuditQuery.data;
  // 买卖点优先取刚跑的回测，否则读最近缓存，免重算
  const effectiveTrades = backtestAudit?.trades ?? singleBacktestMutation.data?.trades ?? latestBacktest?.trades ?? [];
  const backtestMarkers = useMemo(
    () => latestReplay ? replayEventsToMarkers(latestReplay) : backtestAuditToMarkers(effectiveTrades, backtestAudit),
    [latestReplay, effectiveTrades, backtestAudit]
  );
  const selectedBacktestMarker = useMemo(
    () => backtestMarkers.find((marker) => marker.id === selectedBacktestMarkerId) ?? backtestMarkers[0] ?? null,
    [backtestMarkers, selectedBacktestMarkerId]
  );

  useEffect(() => {
    setSelectedBacktestMarkerId((current) => {
      if (current && backtestMarkers.some((marker) => marker.id === current)) return current;
      return backtestMarkers[0]?.id ?? null;
    });
  }, [backtestMarkers]);

  // 切换策略时清旧回测结果，避免显示上一策略的买卖点
  const handleSingleStrategyChange = (strategy: string) => {
    setSingleBacktestStrategy(strategy);
    singleBacktestMutation.reset();
  };

  const handleBacktestMarkerClick = useCallback((marker: KlineMarker) => {
    setSelectedBacktestMarkerId(marker.id ?? null);
  }, []);

  if (!vtSymbol) return <ErrorState message="无效的股票代码" />;

  if (quoteQuery.isLoading) return <LoadingState rows={6} />;
  if (quoteQuery.isError)
    return (
      <ErrorState
        message={
          quoteQuery.error instanceof Error
            ? quoteQuery.error.message
            : "加载股票详情失败"
        }
        onRetry={() => quoteQuery.refetch()}
      />
    );

  const quote = quoteQuery.data!;
  const snapshot = snapshotQuery.data as StockSnapshot | undefined;
  const missing = snapshot?.data_quality?.missing ?? [];
  const sources: string[] = [];

  const concepts = conceptQuery.data;
  const business = businessQuery.data as StockBusinessType | null | undefined;
  const strategyOptions = strategiesQuery.data?.items ?? [];

  return (
    <div className="space-y-5">
      {/* Quote header (reused) */}
      <StockQuoteHeader quote={quote} sealInfo={sealInfo} />

      {/* Data evidence bar */}
      <StockDataEvidence sources={sources} missing={missing} />

      {/* ⭐ Identity Card — Core Innovation */}
      <IdentityCard
        conceptData={concepts}
        isLoading={conceptQuery.isLoading}
      />

      <SingleStockBacktestPanel
        start={backtestStart}
        onStartChange={setBacktestStart}
        strategy={singleBacktestStrategy}
        strategies={strategyOptions}
        onStrategyChange={handleSingleStrategyChange}
        replay={latestReplayQuery.data}
        isReplayLoading={latestReplayQuery.isLoading || latestReplayQuery.isFetching}
        result={singleBacktestMutation.data}
        audit={backtestAudit}
        tradePlan={tradePlanQuery.data}
        latest={latestBacktest}
        isRunning={singleBacktestMutation.isPending}
        error={singleBacktestMutation.error}
        onRun={() => singleBacktestMutation.mutate()}
      />

      {/* K-line chart */}
      <div className="rounded-lg border p-3 sm:p-4">
        <StockKlineChart
          vtSymbol={vtSymbol}
          markers={backtestMarkers}
          selectedMarkerId={selectedBacktestMarker?.id ?? null}
          onMarkerClick={handleBacktestMarkerClick}
        />
        <BacktestMarkerInsight marker={selectedBacktestMarker} />
      </div>

      {/* Technical indicators */}
      <section className="rounded-lg border p-3 sm:p-4">
        <h3 className="mb-3 text-sm font-medium">技术指标</h3>
        <StockIndicatorPanel vtSymbol={vtSymbol} />
      </section>

      {/* Two-column: Business + Financial summary */}
      <div className="grid gap-5 lg:grid-cols-2">
        {/* Business composition */}
        <section className="rounded-lg border p-3 sm:p-4">
          <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
            <Building2 size={14} />
            主营业务
          </h3>
          {business ? (
            <BusinessComposition business={business} />
          ) : (
            <div className="py-4 text-sm text-muted-foreground">
              {businessQuery.isLoading ? "加载中..." : "暂无业务数据"}
            </div>
          )}
        </section>

        {/* Shenwan hierarchy + sector memberships */}
        <section className="rounded-lg border p-3 sm:p-4">
          <h3 className="mb-3 text-sm font-medium">行业归属</h3>
          <ShenwanHierarchy shenwan={concepts?.shenwan} />
        </section>
      </div>

      {/* Historical Financial Reports */}
      <section className="rounded-lg border p-3 sm:p-4">
        <h3 className="mb-3 flex items-center gap-2 text-sm font-medium">
          <TrendingUp size={14} />
          历史财报
        </h3>
        <StockFinanceChart vtSymbol={vtSymbol} />
      </section>
    </div>
  );
}

function SingleStockBacktestPanel({
  start,
  onStartChange,
  strategy,
  strategies,
  onStrategyChange,
  replay,
  isReplayLoading,
  result,
  audit,
  tradePlan,
  latest,
  isRunning,
  error,
  onRun,
}: {
  start: string;
  onStartChange: (value: string) => void;
  strategy: string;
  strategies: QuantStrategyOption[];
  onStrategyChange: (value: string) => void;
  replay?: SymbolStrategyReplay;
  isReplayLoading: boolean;
  result: Awaited<ReturnType<typeof createSymbolBacktest>> | undefined;
  audit?: BacktestAudit;
  tradePlan?: SymbolTradePlan;
  latest?: SymbolLatestBacktest | null;
  isRunning: boolean;
  error: unknown;
  onRun: () => void;
}) {
  const trades = audit?.trades ?? result?.trades ?? latest?.trades ?? [];
  const events = audit?.events ?? [];
  const returnSummary = useMemo(() => deriveStockReturnSummary(trades), [trades]);
  const replayClosedTrades = replay?.closed_trades ?? [];
  const replaySummary = replay?.summary;
  const hasReplay = replay?.status === "ready";

  return (
    <section className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <BarChart3 size={15} />
            策略复盘
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            读取区间候选生成后的全局 replay。BUY 信号不等于实际购买，执行日还要通过涨跌停、尾盘价格和卖出规则。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            className="h-9 rounded-md border bg-background px-2 text-sm"
            value={strategy}
            onChange={(event) => onStrategyChange(event.target.value)}
          >
            {strategies.length === 0 ? (
              <option value={strategy}>主线强势回踩低吸</option>
            ) : (
              strategies.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))
            )}
          </select>
          <input
            className="h-9 rounded-md border bg-background px-2 text-sm"
            type="date"
            value={start}
            onChange={(event) => onStartChange(event.target.value)}
          />
          <Button size="sm" variant="outline" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <RefreshCw size={15} />}
            手动研究回测
          </Button>
        </div>
      </div>

      {tradePlan?.status === "ready" && tradePlan.trade_plan && (
        <div className="mt-3 rounded-md border bg-muted/30 p-3 text-sm">
          <div className="flex items-center gap-2 font-medium">
            <ShieldCheck size={14} />
            候选买卖计划（{tradePlan.trade_date} 候选第 {tradePlan.rank} 名 · 评分 {tradePlan.total_score?.toFixed(1)}）
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-4">
            <InfoCell label="买入价" value={formatPrice(tradePlan.trade_plan.entry_price)} />
            <InfoCell label="止损价" value={formatPrice(tradePlan.trade_plan.stop_loss_price)} valueClass="text-fall" />
            <InfoCell label="止盈价" value={formatPrice(tradePlan.trade_plan.take_profit_price)} valueClass="text-rise" />
            <InfoCell label="信号日" value={tradePlan.trade_plan.entry_date ?? tradePlan.trade_date ?? "--"} />
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            候选筛选时已生成信号计划，无需重新运行即可查看；下方可手动运行完整单股复盘查看执行结果。
          </p>
        </div>
      )}
      {tradePlan?.status === "empty" && (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          该股未在候选列表中。可手动运行下方单股回测。
        </div>
      )}

      {Boolean(error) && (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {error instanceof Error ? error.message : "单股回测失败"}
        </div>
      )}

      {isReplayLoading ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          正在读取最新全局策略复盘...
        </div>
      ) : !hasReplay ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          {replay?.message ?? "该股暂无全局策略复盘结果。请先在量化页生成区间候选，或用补齐 replay 接口基于已有候选生成统一复盘。"}
        </div>
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid gap-3 text-sm md:grid-cols-6">
            <InfoCell label="Replay ID" value={replay.replay_run_id ?? "--"} />
            <InfoCell label="BUY信号" value={`${replaySummary?.signal_count ?? 0} 次`} />
            <InfoCell label="买入成交" value={`${replaySummary?.buy_filled_count ?? 0} 次`} valueClass={(replaySummary?.buy_filled_count ?? 0) > 0 ? "text-rise" : undefined} />
            <InfoCell label="拒绝" value={`${replaySummary?.rejected_count ?? 0} 次`} valueClass={(replaySummary?.rejected_count ?? 0) > 0 ? "text-fall" : undefined} />
            <InfoCell label="闭合交易" value={`${replaySummary?.closed_trade_count ?? 0} 笔`} />
            <InfoCell label="状态" value={strategyStatusLabel(replaySummary?.current_status)} />
          </div>
          <div className="grid gap-3 text-sm md:grid-cols-3">
            <InfoCell label="累计收益率" value={formatPct(replaySummary?.compound_return_pct)} valueClass={priceColorClass(replaySummary?.compound_return_pct)} />
            <InfoCell label="平均单笔" value={formatPct(replaySummary?.average_return_pct)} valueClass={priceColorClass(replaySummary?.average_return_pct)} />
            <InfoCell label="胜率" value={formatPct(replaySummary?.win_rate_pct)} />
          </div>
          {replaySummary?.reject_reasons?.length ? <ReplayRejectReasonList rows={replaySummary.reject_reasons} /> : null}
          {replayClosedTrades.length ? (
            <ReplayClosedTradeTable trades={replayClosedTrades} />
          ) : (
            <div className="rounded-md border p-3 text-sm text-muted-foreground">
              当前全局 replay 尚未形成闭合交易。若图上有 BUY 信号或拒绝标记，请点击 K 线查看执行原因。
            </div>
          )}
        </div>
      )}

      {(result || latest) && (
        <div className="mt-4 space-y-4">
          <div className="border-t pt-4 text-sm font-medium">手动研究回测结果</div>
          <div className="grid gap-3 text-sm md:grid-cols-6">
            <InfoCell label="状态" value={(result ?? latest)?.status ?? "--"} />
            <InfoCell label="回测ID" value={(result ?? latest)?.backtest_id ?? "--"} />
            <InfoCell label="累计收益率" value={formatPct(returnSummary.compoundReturnPct)} valueClass={priceColorClass(returnSummary.compoundReturnPct)} />
            <InfoCell label="平均单笔" value={formatPct(returnSummary.averageReturnPct)} valueClass={priceColorClass(returnSummary.averageReturnPct)} />
            <InfoCell label="胜率" value={formatPct(returnSummary.winRatePct)} />
            <InfoCell label="闭合交易" value={`${returnSummary.closedCount} 笔`} />
          </div>
          <div className="grid gap-3 text-sm md:grid-cols-3">
            <InfoCell label="最好单笔" value={formatPct(returnSummary.bestReturnPct)} valueClass={priceColorClass(returnSummary.bestReturnPct)} />
            <InfoCell label="最差单笔" value={formatPct(returnSummary.worstReturnPct)} valueClass={priceColorClass(returnSummary.worstReturnPct)} />
            <InfoCell label="成交记录" value={`${trades.length} 条`} />
          </div>

          {audit?.method && (
            <div className="rounded-md border bg-muted/30 p-3 text-sm">
              <div className="flex items-center gap-2 font-medium">
                <FileText size={14} />
                策略口径
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                <InfoCell label="候选生成" value={audit.method.signal_timing} />
                <InfoCell label="执行时点" value={audit.method.execution_timing} />
                <InfoCell label="入场过滤" value={`最低分 ${audit.method.entry_filter?.min_entry_score ?? "--"} / 严格 ${audit.method.entry_filter?.strict_entry ? "是" : "否"}`} />
                <InfoCell label="执行模式" value={stockExecutionMethodLabel(audit.method.execution)} />
              </div>
            </div>
          )}

          {trades.length === 0 ? (
            <div className="rounded-md border p-3 text-sm text-muted-foreground">
              当前区间没有实际成交。若图上有 BUY 信号或买入拒绝，请查看对应执行日的拒绝原因和策略日志。
            </div>
          ) : returnSummary.trades.length === 0 ? (
            <div className="rounded-md border p-3 text-sm text-muted-foreground">
              当前区间有成交记录，但还没有形成“买入成交到卖出成交”的闭合交易，暂不计算单笔收益率。
            </div>
          ) : (
            <ClosedReturnTradeTable trades={returnSummary.trades} />
          )}

          <BacktestEventLog events={events} />
        </div>
      )}
    </section>
  );
}

function ClosedReturnTradeTable({ trades }: { trades: ClosedReturnTrade[] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">闭合交易收益率</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>买入日期</TableHead>
            <TableHead>卖出日期</TableHead>
            <TableHead className="text-right">买入价</TableHead>
            <TableHead className="text-right">卖出价</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead className="text-right">持有天数</TableHead>
            <TableHead>退出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade, index) => (
            <TableRow key={`${trade.entryDate}-${trade.exitDate}-${index}`}>
              <TableCell className="tabular-nums">{trade.entryDate}</TableCell>
              <TableCell className="tabular-nums">{trade.exitDate}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(trade.entryPrice)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(trade.exitPrice)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(trade.returnPct))}>
                {formatPct(trade.returnPct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{trade.holdingDays ?? "--"}</TableCell>
              <TableCell className="text-muted-foreground">{trade.exitReasonLabel ?? exitReasonLabel(trade.exitReason)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ReplayClosedTradeTable({ trades }: { trades: NonNullable<SymbolStrategyReplay["closed_trades"]> }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">闭合交易收益率</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>买入日期</TableHead>
            <TableHead>卖出日期</TableHead>
            <TableHead className="text-right">买入价</TableHead>
            <TableHead className="text-right">卖出价</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead className="text-right">持有天数</TableHead>
            <TableHead>退出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade, index) => (
            <TableRow key={`${trade.vt_symbol}-${trade.entry_date}-${trade.exit_date}-${index}`}>
              <TableCell className="tabular-nums">{trade.entry_date ?? "--"}</TableCell>
              <TableCell className="tabular-nums">{trade.exit_date ?? "--"}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(trade.entry_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(trade.exit_price)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(trade.return_pct))}>
                {formatPct(trade.return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{trade.holding_days ?? "--"}</TableCell>
              <TableCell className="text-muted-foreground">{exitReasonLabel(trade.exit_reason)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ReplayRejectReasonList({ rows }: { rows: Array<{ reason: string; count: number }> }) {
  return (
    <div className="rounded-md border p-3 text-sm">
      <div className="font-medium">拒绝原因</div>
      <div className="mt-2 flex flex-wrap gap-2">
        {rows.map((row) => (
          <Badge key={row.reason} variant="outline" className="rounded-md">
            {portfolioReasonLabel(row.reason)}：{row.count}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function BacktestEventLog({ events }: { events: BacktestAudit["events"] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">策略日志</div>
      {events.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">暂无订单日志。</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>日期</TableHead>
              <TableHead>股票</TableHead>
              <TableHead>事件</TableHead>
              <TableHead>执行</TableHead>
              <TableHead className="text-right">价格</TableHead>
              <TableHead>说明</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.slice(0, 20).map((event, index) => (
              <TableRow key={`${event.trade_date}-${event.event_type}-${index}`}>
                <TableCell className="tabular-nums">{event.trade_date}</TableCell>
                <TableCell>
                  <StockIdentityLink name={event.name} vtSymbol={event.vt_symbol} board={event.board} boardLabel={event.board_label} />
                </TableCell>
                <TableCell>{stockEventLabel(event.event_type, event.side, event.status)}</TableCell>
                <TableCell className="text-muted-foreground">{executionModeLabel(event.execution_mode)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(event.price)}</TableCell>
                <TableCell className="text-muted-foreground">{event.message ?? event.reason ?? "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function BacktestMarkerInsight({ marker }: { marker: KlineMarker | null }) {
  if (!marker) {
    return (
      <div className="mt-4 border-t pt-3 text-sm text-muted-foreground">
        单股复盘的 BUY 信号、买入拒绝和成交会标在 K 线上；点击标记可查看对应策略口径。
      </div>
    );
  }

  return (
    <section className="mt-4 border-t pt-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">{marker.title ?? markerBadgeLabel(marker)}</h3>
          <p className="mt-1 max-w-4xl text-sm text-muted-foreground">{marker.strategy}</p>
        </div>
        <Badge variant={marker.markerKind === "trade" ? "secondary" : "outline"} className="rounded-md">
          {markerBadgeLabel(marker)}
        </Badge>
      </div>

      <div className="mt-3 grid gap-3 text-sm md:grid-cols-6">
        <InfoCell label="标记日期" value={marker.time} />
        <InfoCell label="信号日期" value={marker.signalDate ?? "--"} />
        <InfoCell label="执行日期" value={marker.executeDate ?? marker.tradeDate ?? "--"} />
        <InfoCell label="执行方式" value={executionModeLabel(marker.executionMode)} />
        <InfoCell label="价格" value={formatPrice(marker.price)} />
        <InfoCell label="收益率" value={formatPct(marker.returnPct)} valueClass={priceColorClass(marker.returnPct)} />
      </div>

      <div className="mt-3 grid gap-3 text-sm lg:grid-cols-3">
        <InsightBlock title="信号" text={marker.signalText} />
        <InsightBlock title="执行" text={marker.executionText} />
        <InsightBlock title="原因" text={marker.reasonText} />
      </div>

      {marker.evidence && marker.evidence.length > 0 && (
        <div className="mt-3">
          <div className="mb-2 text-xs text-muted-foreground">回测证据</div>
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            {marker.evidence.map((item) => (
              <InfoCell key={item.label} label={item.label} value={item.value} valueClass={item.valueClass} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function InsightBlock({ title, text }: { title: string; text?: string }) {
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="text-xs text-muted-foreground">{title}</div>
      <div className="mt-1 leading-6">{text || "--"}</div>
    </div>
  );
}

function markerBadgeLabel(marker: KlineMarker) {
  if (marker.markerKind === "signal" || marker.status === "signal") return "BUY 信号";
  if (marker.markerKind === "rejected" || marker.status === "rejected") {
    return marker.side === "SELL" ? "卖出拒绝" : "买入拒绝";
  }
  if (marker.side === "BUY") return "买入成交";
  if (marker.side === "SELL") return "卖出成交";
  return marker.side || "--";
}

function replayEventsToMarkers(replay: SymbolStrategyReplay): KlineMarker[] {
  const events = replay.events ?? [];
  return dedupeMarkers(events.map((event, index) => replayEventToMarker(event, index))).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function replayEventToMarker(event: StrategyReplayEvent, index: number): KlineMarker {
  const raw = safeRaw(event.raw);
  const evidence = raw.evidence && typeof raw.evidence === "object" && !Array.isArray(raw.evidence)
    ? raw.evidence as Record<string, unknown>
    : {};
  const isSignal = event.event_type === "signal" || event.status === "signal";
  const isRejected = event.status === "rejected";
  const markerKind = isSignal ? "signal" : isRejected ? "rejected" : "trade";
  const reasonLabel = portfolioReasonLabel(event.reason);
  return {
    id: `replay-${event.event_type}-${event.vt_symbol}-${event.trade_date}-${event.side}-${index}`,
    time: event.trade_date,
    tradeDate: event.trade_date,
    signalDate: event.signal_date ?? getRawText(raw, "signal_date"),
    executeDate: event.execute_date ?? getRawText(raw, "execute_date"),
    side: event.side,
    markerKind,
    status: event.status,
    reason: event.reason,
    reasonLabel,
    price: event.price ?? null,
    executionMode: getRawText(raw, "mode") ?? getRawText(raw, "execution_model"),
    title: replayMarkerTitle(event, reasonLabel),
    strategy: replayMarkerStrategyText(event, evidence, reasonLabel),
    signalText: replaySignalText(event, evidence),
    executionText: replayExecutionText(event, reasonLabel),
    reasonText: markerReasonTextFromReason(event.reason),
    evidence: replayMarkerEvidence(event, raw, evidence),
    raw: event.raw,
    text: replayMarkerText(event),
  };
}

function replayMarkerTitle(event: StrategyReplayEvent, reasonLabel: string) {
  if (event.status === "signal") return "BUY 信号";
  if (event.status === "rejected") return `${event.side === "SELL" ? "卖出" : "买入"}拒绝：${reasonLabel}`;
  if (event.side === "BUY") return "买入成交";
  if (event.side === "SELL") return `卖出成交：${reasonLabel}`;
  return event.status;
}

function replayMarkerText(event: StrategyReplayEvent) {
  if (event.status === "signal") return "信号";
  if (event.status === "rejected") return event.side === "SELL" ? "卖拒" : "买拒";
  return event.side === "SELL" ? "卖" : "买";
}

function replayMarkerStrategyText(event: StrategyReplayEvent, evidence: Record<string, unknown>, reasonLabel: string) {
  if (event.status === "signal") return replaySignalText(event, evidence);
  if (event.status === "rejected") return `${event.execute_date ?? event.trade_date} 执行未成交：${reasonLabel}。`;
  return `${event.execute_date ?? event.trade_date} 按统一策略 replay 成交，价格来源 ${event.price_source ?? "--"}。`;
}

function replaySignalText(event: StrategyReplayEvent, evidence: Record<string, unknown>) {
  const score = event.score ?? getRawNumber(evidence, "total_score");
  const ma5Distance = getRawNumber(evidence, "ma5_distance_pct");
  const parts = [
    `${event.signal_date ?? event.trade_date} 收盘后生成 BUY 信号`,
    score == null ? "" : `总分 ${formatNumber(score, 1)}`,
    ma5Distance == null ? "" : `距MA5 ${formatPct(ma5Distance)}`,
  ].filter(Boolean);
  return parts.join("；");
}

function replayExecutionText(event: StrategyReplayEvent, reasonLabel: string) {
  if (event.status === "signal") return `计划执行日 ${event.execute_date ?? "--"}，实际是否成交以执行规则为准。`;
  if (event.status === "rejected") return `执行状态：拒绝，原因 ${reasonLabel}。`;
  return `执行状态：成交，价格 ${formatPrice(event.price)}。`;
}

function replayMarkerEvidence(
  event: StrategyReplayEvent,
  raw: Record<string, unknown>,
  evidence: Record<string, unknown>
): KlineMarker["evidence"] {
  const rows: Array<{ label: string; value: string; valueClass?: string }> = [];
  if (event.signal_date) rows.push({ label: "信号日", value: event.signal_date });
  if (event.execute_date) rows.push({ label: "执行日", value: event.execute_date });
  if (event.reason) rows.push({ label: "原因", value: portfolioReasonLabel(event.reason) });
  pushPriceEvidence(rows, "执行价", event.price);
  pushPriceEvidence(rows, "MA5", getRawNumber(raw, "ma5") ?? getRawNumber(evidence, "ma5"));
  pushPctEvidence(rows, "距MA5", getRawNumber(raw, "ma5_distance_pct") ?? getRawNumber(evidence, "ma5_distance_pct"));
  pushNumberEvidence(rows, "分钟线数量", getRawNumber(raw, "minute_bar_count"), 0);
  if (event.price_source) rows.push({ label: "价格来源", value: event.price_source });
  rows.push({ label: "代理价格", value: event.proxy_used ? "是" : "否" });
  return rows;
}

function backtestAuditToMarkers(trades: BacktestTrade[], audit?: BacktestAudit): KlineMarker[] {
  const returnQueues = closedReturnQueues(trades);
  const markers = audit?.events?.length
    ? audit.events.flatMap((event, index) => auditEventToMarkers(event, index, returnQueues))
    : trades.map((trade, index) => tradeToExecutionMarker(trade, index, audit, nextReturnForSell(returnQueues, trade)));
  return dedupeMarkers(markers).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function auditEventToMarkers(
  event: BacktestAuditEvent,
  index: number,
  returnQueues: Map<string, ClosedReturnTrade[]>
): KlineMarker[] {
  const markers: KlineMarker[] = [];
  const signalMarker = auditEventToSignalMarker(event, index);
  if (signalMarker) markers.push(signalMarker);
  const executionMarker = auditEventToExecutionMarker(event, index, returnQueues);
  if (executionMarker) markers.push(executionMarker);
  return markers;
}

function auditEventToSignalMarker(event: BacktestAuditEvent, index: number): KlineMarker | null {
  if (event.event_type !== "order" || event.side !== "BUY") return null;
  const raw = safeRaw(event.raw);
  const signalDate = getRawText(raw, "signal_date") ?? getRawText(raw, "reference_date");
  if (!signalDate) return null;
  const executeDate = getRawText(raw, "execute_date") ?? event.trade_date;
  return {
    id: `signal-${event.vt_symbol}-${signalDate}-${index}`,
    time: signalDate,
    side: "BUY",
    markerKind: "signal",
    status: "signal",
    price: null,
    text: "信号",
    title: "BUY 信号",
    strategy: markerSignalTextFromAuditEvent(event),
    signalText: markerSignalTextFromAuditEvent(event),
    executionText: `计划在 ${executeDate} 按执行模型撮合；只有执行规则通过才会成为实际买入。`,
    reasonText: "BUY 信号代表 T 日收盘后策略认为可买，不代表 T+1 一定成交。",
    signalDate,
    executeDate,
    tradeDate: signalDate,
    evidence: auditMarkerEvidence(event),
    raw: event.raw,
  };
}

function auditEventToExecutionMarker(
  event: BacktestAuditEvent,
  index: number,
  returnQueues: Map<string, ClosedReturnTrade[]>
): KlineMarker | null {
  if (event.event_type === "trade") {
    return auditTradeEventToMarker(event, index, nextReturnForSell(returnQueues, event));
  }
  if (event.event_type !== "order" || event.status !== "rejected") return null;
  const raw = safeRaw(event.raw);
  const signalDate = getRawText(raw, "signal_date") ?? getRawText(raw, "reference_date");
  const executeDate = getRawText(raw, "execute_date") ?? event.trade_date;
  const sideLabel = event.side === "SELL" ? "卖出" : "买入";
  const reasonLabel = event.reason_label ?? portfolioReasonLabel(event.reason);
  return {
    id: `rejected-${event.vt_symbol}-${executeDate}-${event.side}-${event.reason ?? "unknown"}-${index}`,
    time: executeDate,
    side: event.side,
    markerKind: "rejected",
    status: "rejected",
    reason: event.reason,
    reasonLabel,
    price: event.price ?? getRawNumber(raw, "price"),
    text: event.side === "SELL" ? "卖拒" : "买拒",
    title: `${sideLabel}拒绝：${reasonLabel}`,
    strategy: event.message ?? `${sideLabel}未成交：${reasonLabel}`,
    signalText: markerSignalTextFromAuditEvent(event),
    executionText: event.message ?? `${sideLabel}未成交：${reasonLabel}`,
    reasonText: reasonLabel,
    executionMode: event.execution_mode ?? getRawText(raw, "mode"),
    signalDate,
    executeDate,
    tradeDate: event.trade_date,
    evidence: auditMarkerEvidence(event),
    raw: event.raw,
  };
}

function auditTradeEventToMarker(event: BacktestAuditEvent, index: number, returnPct: number | null): KlineMarker {
  const raw = safeRaw(event.raw);
  const execution = raw.execution && typeof raw.execution === "object" && !Array.isArray(raw.execution)
    ? raw.execution as Record<string, unknown>
    : raw;
  const signalDate = getRawText(execution, "signal_date") ?? getRawText(execution, "reference_date");
  const executeDate = getRawText(execution, "execute_date") ?? event.trade_date;
  const isBuy = event.side === "BUY";
  return {
    id: `trade-${event.vt_symbol}-${event.trade_date}-${event.side}-${index}`,
    time: event.trade_date,
    tradeDate: event.trade_date,
    signalDate,
    executeDate,
    side: event.side,
    markerKind: "trade",
    status: "filled",
    reason: event.reason,
    reasonLabel: event.reason_label ?? portfolioReasonLabel(event.reason),
    price: event.price,
    returnPct,
    executionMode: event.execution_mode ?? getRawText(execution, "mode"),
    title: isBuy ? "买入成交" : `卖出成交：${event.reason_label ?? exitReasonLabel(event.reason)}`,
    strategy: event.message ?? (isBuy ? "买入执行已成交。" : "卖出执行已成交。"),
    signalText: isBuy ? markerSignalTextFromAuditEvent(event) : `${signalDate ?? "信号日"} 收盘后触发 ${event.reason_label ?? exitReasonLabel(event.reason)}。`,
    executionText: event.message,
    reasonText: event.reason_label ?? markerReasonTextFromReason(event.reason),
    evidence: auditMarkerEvidence(event),
    raw: event.raw,
    text: isBuy ? "买" : "卖",
  };
}

function markerSignalTextFromAuditEvent(event: BacktestAuditEvent): string {
  const raw = safeRaw(event.raw);
  const evidence = raw.execution && typeof raw.execution === "object" && !Array.isArray(raw.execution)
    ? raw
    : raw;
  const score = getRawNumber(evidence, "total_score");
  const return20 = getRawNumber(evidence, "return_20d");
  const indexReturn20 = getRawNumber(evidence, "index_return_20d");
  const ma5Distance = getRawNumber(evidence, "ma5_distance_pct");
  const signalDate = getRawText(raw, "signal_date") ?? getRawText(raw, "reference_date");
  const parts = [
    signalDate ? `${signalDate} 收盘后生成 BUY 信号` : "收盘后生成 BUY 信号",
    score == null ? "" : `总分 ${formatNumber(score, 1)}`,
    return20 == null ? "" : `20日收益 ${formatPct(return20)}`,
    indexReturn20 == null ? "" : `同期指数 ${formatPct(indexReturn20)}`,
    ma5Distance == null ? "" : `距MA5 ${formatPct(ma5Distance)}`,
  ].filter(Boolean);
  return parts.length ? parts.join("；") : "策略在信号日收盘后生成计划，执行日再按撮合规则判断是否成交。";
}

function markerReasonTextFromReason(reason?: string | null): string {
  if (reason === "tail_entry_not_triggered") return "执行价没有落在尾盘 MA5 容忍范围内，因此 BUY 信号没有转成实际买入。";
  if (reason === "limit_up_open_blocked") return "执行日开盘涨停或接近涨停，保守判定买不到。";
  if (reason === "limit_up_tail_unfilled") return "执行日尾盘涨停或接近涨停，保守判定买不到。";
  if (reason === "no_execute_bar") return "缺少执行日 K 线，无法判断可执行价格。";
  if (reason === "missing_1430_snapshot") return "今日严格 14:30 模式缺少可用分钟快照，需等待分钟数据补齐。";
  if (reason === "position_slot_unavailable") return "组合持仓名额已满，信号未转成实际买入。";
  if (reason === "insufficient_cash") return "组合可用资金不足，信号未转成实际买入。";
  return reason ? portfolioReasonLabel(reason) : "--";
}

function auditMarkerEvidence(event: BacktestAuditEvent): KlineMarker["evidence"] {
  const raw = safeRaw(event.raw);
  const execution = raw.execution && typeof raw.execution === "object" && !Array.isArray(raw.execution)
    ? raw.execution as Record<string, unknown>
    : raw;
  const rows: Array<{ label: string; value: string; valueClass?: string }> = [];
  const signalDate = getRawText(execution, "signal_date") ?? getRawText(execution, "reference_date");
  const executeDate = getRawText(execution, "execute_date") ?? event.trade_date;
  if (signalDate) rows.push({ label: "信号日", value: signalDate });
  if (executeDate) rows.push({ label: "执行日", value: executeDate });
  if (event.reason_label || event.reason) rows.push({ label: "原因", value: event.reason_label ?? portfolioReasonLabel(event.reason) });
  pushPriceEvidence(rows, "执行价", event.price ?? getRawNumber(execution, "price"));
  pushPriceEvidence(rows, "MA5", getRawNumber(execution, "ma5") ?? getRawNumber(raw, "ma5"));
  pushPctEvidence(rows, "距MA5", getRawNumber(execution, "ma5_distance_pct") ?? getRawNumber(raw, "ma5_distance_pct"));
  pushNumberEvidence(rows, "分钟线数量", getRawNumber(execution, "minute_bar_count"), 0);
  const window = getRawText(execution, "window");
  if (window) rows.push({ label: "尾盘窗口", value: window });
  const priceSource = getRawText(execution, "price_source");
  if (priceSource) rows.push({ label: "价格来源", value: priceSource });
  return rows;
}

function tradeToExecutionMarker(
  trade: BacktestTrade,
  index: number,
  audit?: BacktestAudit,
  returnPct: number | null = null
): KlineMarker {
    const execution = markerExecutionRaw(trade);
    const executionMode = getRawText(execution, "mode");
    const isBuy = trade.side === "BUY";
    const signalDate = isBuy ? getRawText(execution, "reference_date") : getRawText(execution, "signal_date");
    const executeDate = getRawText(execution, "execute_date") ?? trade.trade_date;
    return {
      id: `${trade.trade_date}-${trade.side}-${trade.vt_symbol}-${index}`,
      time: trade.trade_date,
      tradeDate: trade.trade_date,
      signalDate,
      executeDate,
      side: trade.side,
      markerKind: "trade",
      status: "filled",
      reason: trade.reason,
      reasonLabel: trade.reason_label,
      price: trade.price,
      returnPct,
      executionMode,
      title: markerTitle(trade),
      strategy: markerStrategyText(trade, audit),
      signalText: markerSignalText(trade, audit),
      executionText: markerExecutionText(trade, execution),
      reasonText: markerReasonText(trade),
      evidence: markerEvidence(trade, execution),
      raw: trade.raw,
      text: isBuy ? `买 ${formatPrice(trade.price)}` : `卖 ${formatPrice(trade.price)}`,
    };
}

function closedReturnQueues(trades: BacktestTrade[]): Map<string, ClosedReturnTrade[]> {
  const summary = deriveStockReturnSummary(trades);
  const queues = new Map<string, ClosedReturnTrade[]>();
  for (const trade of summary.trades) {
    const items = queues.get(trade.exitDate) ?? [];
    items.push(trade);
    queues.set(trade.exitDate, items);
  }
  return queues;
}

function nextReturnForSell(
  queues: Map<string, ClosedReturnTrade[]>,
  trade: Pick<BacktestTrade, "side" | "trade_date"> | Pick<BacktestAuditEvent, "side" | "trade_date">
): number | null {
  if (trade.side !== "SELL") return null;
  const queue = queues.get(trade.trade_date);
  return queue?.shift()?.returnPct ?? null;
}

function dedupeMarkers(markers: KlineMarker[]): KlineMarker[] {
  const result = new Map<string, KlineMarker>();
  for (const marker of markers) {
    const key = [
      marker.markerKind ?? "trade",
      marker.status ?? "",
      marker.time,
      marker.side,
      marker.reason ?? "",
      marker.price ?? "",
    ].join("|");
    if (!result.has(key)) result.set(key, marker);
  }
  return [...result.values()];
}

function markerSortRank(marker: KlineMarker) {
  if (marker.markerKind === "signal") return 0;
  if (marker.markerKind === "rejected") return 1;
  if (marker.side === "BUY") return 2;
  return 3;
}

function markerTitle(trade: BacktestTrade) {
  if (trade.side === "BUY") return "买入信号";
  return `卖出信号：${exitReasonLabel(trade.reason)}`;
}

function markerStrategyText(trade: BacktestTrade, audit?: BacktestAudit) {
  if (trade.side === "BUY") {
    const minScore = audit?.method?.entry_filter?.min_entry_score;
    const strict = audit?.method?.entry_filter?.strict_entry;
    const window = audit?.method?.execution?.tail_entry_window;
    return [
      "历史逐日动态候选回测：只使用信号日及以前可见数据打分。",
      `入场要求${minScore == null ? "" : `总分不低于 ${minScore}`}${strict ? "，并满足严格入场条件" : ""}。`,
      window ? `执行日按 ${window} 尾盘规则复核；历史缺分钟线时用收盘价代理，今日缺快照才等待数据补齐。` : "",
    ].filter(Boolean).join(" ");
  }
  return "退出规则在持仓后的每个交易日收盘后检查止损、止盈、移动止损和时间止损；当前模型只生成下一交易日卖出计划，再按 14:30 快照执行，缺快照或未触发则拒单。";
}

function markerSignalText(trade: BacktestTrade, audit?: BacktestAudit) {
  if (trade.side === "BUY") {
    const raw = safeRaw(trade.raw);
    const return20 = getRawNumber(raw, "return_20d");
    const indexReturn20 = getRawNumber(raw, "index_return_20d");
    const ma5Distance = getRawNumber(raw, "ma5_distance_pct");
    const scoreText = audit?.method?.entry_filter?.min_entry_score == null
      ? "达到入场过滤条件"
      : `达到最低入场分 ${audit.method.entry_filter.min_entry_score}`;
    return [
      `信号日收盘后重新打分，${scoreText}。`,
      return20 == null ? "" : `近 20 日收益 ${formatPct(return20)}`,
      indexReturn20 == null ? "" : `同期指数 ${formatPct(indexReturn20)}`,
      ma5Distance == null ? "" : `收盘距 MA5 ${formatPct(ma5Distance)}`,
    ].filter(Boolean).join("；");
  }

  const execution = markerExecutionRaw(trade);
  const signalDate = getRawText(execution, "signal_date");
  return `${signalDate ?? "信号日"} 收盘后触发 ${exitReasonLabel(trade.reason)}，当天只记录卖出计划，不使用未发生的次日开盘价。`;
}

function markerExecutionText(trade: BacktestTrade, execution: Record<string, unknown>) {
  const mode = getRawText(execution, "mode");
  const modeLabel = executionModeLabel(mode);
  if (trade.side === "BUY") {
    if (mode === "minute_1430") {
      const barTime = getRawText(execution, "bar_time");
      const distance = getRawNumber(execution, "ma5_distance_pct");
      return `执行日 14:30 真实分钟快照成交，${barTime ? `成交分钟 ${barTime}，` : ""}成交方式 ${modeLabel}${distance == null ? "" : `，距 MA5 ${formatPct(distance)}`}。`;
    }
    if (mode === "daily_close_proxy") {
      const distance = getRawNumber(execution, "ma5_distance_pct");
      return `缺少执行日 14:30 分钟线，使用执行日收盘价代理尾盘成交${distance == null ? "" : `，距 MA5 ${formatPct(distance)}`}。`;
    }
    if (mode === "minute_tail_ma5") {
      const barTime = getRawText(execution, "bar_time");
      const distance = getRawNumber(execution, "ma5_distance_pct");
      return `旧版尾盘分钟线触发，${barTime ? `成交分钟 ${barTime}，` : ""}成交方式 ${modeLabel}${distance == null ? "" : `，距 MA5 ${formatPct(distance)}`}。`;
    }
    if (mode === "daily_next_open_fallback") {
      const count = getRawNumber(execution, "minute_bar_count");
      return `旧版模型尾盘分钟线缺失或未触发，回退为次日开盘成交${count == null ? "" : `；当日分钟线 ${count} 根`}。`;
    }
    return `按 ${modeLabel} 执行成交。`;
  }

  const signalDate = getRawText(execution, "signal_date");
  const executeDate = getRawText(execution, "execute_date") ?? trade.trade_date;
  if (mode === "minute_1430_sell") {
    return `${signalDate ?? "D 日"} 出现退出信号，${executeDate} 使用 14:30 真实分钟快照卖出；成交价已计入滑点、佣金和卖出印花税。`;
  }
  if (mode === "daily_close_proxy_sell") {
    return `${signalDate ?? "D 日"} 出现退出信号，${executeDate} 使用收盘价代理尾盘卖出；成交价已计入滑点、佣金和卖出印花税。`;
  }
  return `${signalDate ?? "信号日"} 出现退出信号，${executeDate} 按当前执行模型撮合；成交价已计入滑点、佣金和卖出印花税。`;
}

function markerReasonText(trade: BacktestTrade) {
  if (trade.side === "BUY") {
    const raw = safeRaw(trade.raw);
    const washout = safeRaw(raw.washout);
    const drawdown = getRawNumber(washout, "drawdown_from_20d_high");
    const volumeRatio = getRawNumber(washout, "volume_ratio_5d_20d");
    const parts = [
      "策略寻找相对强势、趋势未破坏、回踩接近 MA5 的候选。",
      drawdown == null ? "" : `较 20 日高点回撤 ${formatPct(drawdown)}`,
      volumeRatio == null ? "" : `5/20 日量比 ${formatNumber(volumeRatio, 2)}`,
    ].filter(Boolean);
    return parts.join("；");
  }
  return exitReasonDescription(trade.reason);
}

function markerEvidence(trade: BacktestTrade, execution: Record<string, unknown>): KlineMarker["evidence"] {
  const raw = safeRaw(trade.raw);
  const rows: Array<{ label: string; value: string; valueClass?: string }> = [];
  if (trade.side === "BUY") {
    pushPctEvidence(rows, "20日收益", getRawNumber(raw, "return_20d"));
    pushPctEvidence(rows, "60日收益", getRawNumber(raw, "return_60d"));
    pushPctEvidence(rows, "60日回撤", getRawNumber(raw, "max_drawdown_60d"));
    pushPriceEvidence(rows, "MA5", getRawNumber(raw, "ma5"));
    pushPctEvidence(rows, "距MA5", getRawNumber(raw, "ma5_distance_pct"));
    pushNumberEvidence(rows, "资金热度代理", getRawNumber(raw, "smart_money_proxy_score"));
    pushNumberEvidence(rows, "资金流分", getRawNumber(raw, "fund_flow_score"));
    pushNumberEvidence(rows, "热度排名分", getRawNumber(raw, "hot_rank_score"));
    pushNumberEvidence(rows, "龙虎榜分", getRawNumber(raw, "lhb_score"));
    pushNumberEvidence(rows, "分钟线数量", getRawNumber(execution, "minute_bar_count"), 0);
    const window = getRawText(execution, "window");
    if (window) rows.push({ label: "尾盘窗口", value: window });
    return rows;
  }
  const entryDate = getRawText(execution, "entry_date");
  const signalDate = getRawText(execution, "signal_date");
  const executeDate = getRawText(execution, "execute_date");
  if (entryDate) rows.push({ label: "买入日期", value: entryDate });
  if (signalDate) rows.push({ label: "信号日期", value: signalDate });
  if (executeDate) rows.push({ label: "成交日期", value: executeDate });
  rows.push({ label: "退出原因", value: exitReasonLabel(trade.reason) });
  return rows;
}

function markerExecutionRaw(trade: BacktestTrade) {
  const raw = safeRaw(trade.raw);
  return raw.execution && typeof raw.execution === "object" && !Array.isArray(raw.execution)
    ? raw.execution as Record<string, unknown>
    : raw;
}

function safeRaw(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function getRawText(raw: Record<string, unknown>, key: string) {
  const value = raw[key];
  return typeof value === "string" && value.length > 0 ? value : null;
}

function getRawNumber(raw: Record<string, unknown>, key: string) {
  const value = raw[key];
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function pushPctEvidence(
  rows: Array<{ label: string; value: string; valueClass?: string }>,
  label: string,
  value: number | null
) {
  if (value == null) return;
  rows.push({ label, value: formatPct(value), valueClass: priceColorClass(value) });
}

function pushPriceEvidence(rows: Array<{ label: string; value: string; valueClass?: string }>, label: string, value: number | null | undefined) {
  if (value == null) return;
  rows.push({ label, value: formatPrice(value) });
}

function pushNumberEvidence(
  rows: Array<{ label: string; value: string; valueClass?: string }>,
  label: string,
  value: number | null | undefined,
  digits = 1
) {
  if (value == null) return;
  rows.push({ label, value: formatNumber(value, digits) });
}

function formatNumber(value: number, digits = 2) {
  return value.toFixed(digits);
}

function exitReasonLabel(reason?: string | null) {
  if (reason === "stop_loss") return "止损";
  if (reason === "take_profit") return "止盈";
  if (reason === "trailing_stop") return "移动止损";
  if (reason === "time_stop") return "时间止损";
  if (reason === "entry_signal") return "入场信号";
  return reason || "--";
}

function strategyStatusLabel(status?: string | null) {
  if (status === "holding") return "持有中";
  if (status === "closed") return "已闭合";
  if (status === "no_position") return "无持仓";
  return status || "--";
}

function exitReasonDescription(reason?: string | null) {
  if (reason === "stop_loss") return "价格跌破成本价下方的止损阈值，按当前执行模型卖出。";
  if (reason === "take_profit") return "价格达到设定止盈阈值，按当前执行模型卖出。";
  if (reason === "trailing_stop") return "持仓后曾创新高，但价格从持仓高点回撤超过移动止损阈值，按当前执行模型卖出。";
  if (reason === "time_stop") return "持仓时间超过策略设定的时间上限，按当前执行模型卖出。";
  return reason || "--";
}

function stockExecutionMethodLabel(execution?: Record<string, unknown>) {
  const model = execution?.execution_model;
  const window = execution?.tail_entry_window;
  if (model === "strict_1430") return `严格14:30 ${typeof window === "string" ? window : "14:30-14:30"}`;
  if (model === "tail_close_hybrid" || !model) return `尾盘混合 ${typeof window === "string" ? window : "14:30-14:30"}`;
  if (model === "legacy_next_open") return "旧报告兼容";
  return String(model);
}

function InfoCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function stockEventLabel(eventType: string, side?: string, status?: string) {
  const sideLabel = side === "BUY" ? "买入" : side === "SELL" ? "卖出" : side ?? "--";
  if (eventType === "trade") return `${sideLabel}成交`;
  if (status === "rejected") return `${sideLabel}拒绝`;
  if (status === "filled") return `${sideLabel}订单成交`;
  return `${sideLabel}订单`;
}

function portfolioReasonLabel(reason?: string | null) {
  const labels: Record<string, string> = {
    entry_signal: "入场信号",
    missing_1430_snapshot: "缺14:30快照",
    tail_entry_not_triggered: "尾盘入场未触发",
    limit_up_open_blocked: "开盘涨停买不到",
    limit_up_tail_unfilled: "尾盘涨停买不到",
    limit_down_tail_blocked: "尾盘跌停卖不出",
    no_execute_bar: "缺少执行日K线",
    limit_up_or_no_bar: "涨停或缺少执行日K线",
    no_bar: "无日线",
    position_slot_unavailable: "仓位已满",
    insufficient_cash: "现金不足",
    stop_loss: "止损",
    take_profit: "止盈",
    trailing_stop: "移动止损",
    time_stop: "时间止损",
  };
  return reason ? labels[reason] ?? reason : "--";
}

function executionModeLabel(mode?: string | null) {
  if (mode === "minute_1430") return "14:30真实";
  if (mode === "daily_close_proxy") return "收盘代理";
  if (mode === "minute_1430_sell") return "14:30卖出";
  if (mode === "daily_close_proxy_sell") return "收盘代理卖出";
  if (mode === "strict_1430_required") return "严格14:30";
  if (mode === "strict_1430_required_sell") return "严格14:30卖出";
  if (mode === "limit_up_tail_unfilled") return "涨停未买";
  if (mode === "limit_down_tail_blocked") return "跌停未卖";
  if (mode === "minute_tail_ma5") return "尾盘分钟";
  if (mode === "daily_next_open_fallback") return "开盘回退";
  if (mode === "minute_tail_ma5_required") return "严格分钟";
  if (mode === "daily_next_open") return "旧报告兼容";
  return mode || "--";
}

// ── Identity Card (core innovation) ──

function IdentityCard({
  conceptData,
  isLoading,
}: {
  conceptData: StockConceptCardsResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={3} />;

  const cards = conceptData?.cards ?? [];
  const shenwan = conceptData?.shenwan;
  const hint = conceptData?.concept_hint;

  // Find the "hottest" concept (highest |change_pct|)
  const hottest: ConceptCard | null = cards.reduce<ConceptCard | null>(
    (prev: ConceptCard | null, curr: ConceptCard) => {
      const prevAbs = Math.abs(prev?.change_pct ?? 0);
      const currAbs = Math.abs(curr.change_pct ?? 0);
      return currAbs > prevAbs ? curr : prev;
    },
    null
  );

  return (
    <section className="rounded-lg border bg-gradient-to-r from-card to-muted/30 p-4 sm:p-5">
      <div className="flex items-center gap-2 mb-3">
        <Fingerprint size={16} className="text-primary" />
        <h3 className="text-sm font-semibold">身份卡片</h3>
        {conceptData && (
          <span className="text-xs text-muted-foreground">
            {conceptData.total_cards} 个概念/行业
          </span>
        )}
      </div>

      {/* ── 概念解读面板 ── */}
      {hint && hint.main_identity && <ConceptHintPanel hint={hint} />}

      {/* Shenwan industry path */}
      {shenwan && (shenwan.level1 || shenwan.level2 || shenwan.level3) && (
        <div className="mb-3 flex flex-wrap items-center gap-1 text-sm">
          <span className="text-muted-foreground">申万行业:</span>
          {[shenwan.level1, shenwan.level2, shenwan.level3]
            .filter(Boolean)
            .map((level, idx, arr) => (
              <span key={idx} className="flex items-center gap-1">
                <span className="font-medium">
                  {(level as { name?: string })?.name}
                </span>
                {idx < arr.length - 1 && (
                  <span className="text-muted-foreground">→</span>
                )}
              </span>
            ))}
        </div>
      )}

      {/* Concept tag cloud */}
      {cards.length > 0 ? (
        <div className="flex flex-wrap gap-1.5">
          {cards.map((card) => {
            const isHot = hottest?.sector_id === card.sector_id && card.change_pct != null && Math.abs(card.change_pct) > 1;
            return (
              <Link
                key={card.sector_id}
                to={`/explore?sector=${encodeURIComponent(card.sector_id)}`}
              >
                <ConceptTag
                  name={card.name}
                  changePct={card.change_pct}
                  type={card.type}
                  hot={isHot}
                />
              </Link>
            );
          })}
        </div>
      ) : (
        <div className="text-sm text-muted-foreground">暂无概念归属数据</div>
      )}

      {/* Hot mainline hint */}
      {hottest && hottest.change_pct != null && Math.abs(hottest.change_pct) > 1 && (
        <div className="mt-3 flex items-center gap-2 rounded-md bg-muted/60 px-3 py-2 text-sm">
          <Flame size={14} className="text-orange-500" />
          <span>
            今日最强主线:
            <Link
              to={`/explore?sector=${encodeURIComponent(hottest.sector_id)}`}
              className="ml-1 font-medium text-primary hover:underline"
            >
              {hottest.name} ({formatPct(hottest.change_pct)})
            </Link>
          </span>
          <ArrowRight size={14} className="text-muted-foreground" />
        </div>
      )}
    </section>
  );
}

// ── Concept Hint Panel (概念解读) ──

function ConceptHintPanel({ hint }: { hint: ConceptHint }) {
  const res = hint.resonance;
  const resonanceColor = res?.level_color === "rise"
    ? "text-rise"
    : res?.level_color === "fall"
      ? "text-fall"
      : "text-muted-foreground";

  return (
    <div className="mb-4 rounded-lg border bg-card/80 px-4 py-3 space-y-2">
      {/* 一句话定位 */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-muted-foreground">核心定位</span>
        <span className="text-sm font-semibold text-primary">
          {hint.main_identity}
        </span>
      </div>

      {/* 主题聚类标签 */}
      {hint.themes.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">主线</span>
          {hint.themes.slice(0, 4).map((t) => (
            <Badge
              key={t.name}
              variant="outline"
              className="text-xs gap-1 px-2 py-0"
            >
              {t.name}
              <span className="text-muted-foreground">×{t.strength}</span>
            </Badge>
          ))}
          {hint.themes.length > 4 && (
            <span className="text-xs text-muted-foreground">
              +{hint.themes.length - 4}
            </span>
          )}
        </div>
      )}

      {/* 共振指示器 */}
      {res && res.total > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-muted-foreground">概念共振</span>
          {/* Mini bar */}
          <div className="flex h-3 w-24 overflow-hidden rounded-sm bg-muted">
            <div
              className="bg-rise/70"
              style={{ width: `${(res.rising / res.total) * 100}%` }}
            />
            <div
              className="bg-muted-foreground/30"
              style={{ width: `${(res.flat / res.total) * 100}%` }}
            />
            <div
              className="bg-fall/70"
              style={{ width: `${(res.falling / res.total) * 100}%` }}
            />
          </div>
          <span className={resonanceColor}>{res.level}</span>
          <span className="text-muted-foreground">
            {res.rising}/{res.total}上涨
          </span>
        </div>
      )}
    </div>
  );
}

// ── Shenwan Hierarchy display ──

function ShenwanHierarchy({
  shenwan,
}: {
  shenwan: ShenwanClassification | undefined;
}) {
  if (!shenwan || (!shenwan.level1 && !shenwan.level2 && !shenwan.level3)) {
    return (
      <div className="text-sm text-muted-foreground">暂无申万行业分类数据</div>
    );
  }

  const levels = [
    { label: "一级行业", data: shenwan.level1 },
    { label: "二级行业", data: shenwan.level2 },
    { label: "三级行业", data: shenwan.level3 },
  ].filter((l) => l.data);

  return (
    <div className="space-y-2">
      {levels.map(({ label, data }) => (
        <div key={label} className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-xs text-muted-foreground">
            {label}
          </span>
          <span className="rounded-md bg-muted px-2 py-1 text-sm font-medium">
            {data?.name ?? "--"}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Business composition display ──

function BusinessComposition({
  business,
}: {
  business: StockBusinessType;
}) {
  const segments = business.segments ?? [];
  const summary = business.summary;

  if (segments.length === 0 && !summary) {
    return <div className="text-sm text-muted-foreground">暂无业务数据</div>;
  }

  return (
    <div className="space-y-3">
      {summary && (
        <p className="text-sm text-muted-foreground line-clamp-3">{summary}</p>
      )}
      {segments.length > 0 && (
        <div className="space-y-2">
          {segments.slice(0, 6).map((seg, idx) => {
            const name = seg.name ?? `业务${idx + 1}`;
            const ratio = seg.revenue_ratio;
            return (
              <div key={idx} className="flex items-center gap-2 text-sm">
                <span className="min-w-[80px] truncate">{name}</span>
                <div className="flex-1">
                  <div className="h-2 rounded-full bg-muted">
                    <div
                      className="h-2 rounded-full bg-primary/70 transition-all"
                      style={{
                        width: `${Math.min((ratio ?? 0) * 100, 100)}%`,
                      }}
                    />
                  </div>
                </div>
                <span className="w-12 text-right text-xs tabular-nums text-muted-foreground">
                  {ratio != null ? `${(ratio * 100).toFixed(1)}%` : "--"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Data Evidence bar ──

function StockDataEvidence({
  sources,
  missing,
}: {
  sources: string[];
  missing: string[];
}) {
  const hasLocal = sources.some((source) => source.startsWith("postgresql"));
  return (
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-3 py-2">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <ShieldCheck size={15} />
        <span>当前个股数据</span>
        <Badge
          variant={hasLocal ? "secondary" : "outline"}
          className="rounded-md gap-1"
        >
          {hasLocal ? <Database size={13} /> : <Radio size={13} />}
          {hasLocal ? "本地库参与" : "实时源为主"}
        </Badge>
        <span
          className={cn(
            missing.length ? "text-muted-foreground" : "text-green-600"
          )}
        >
          {missing.length
            ? `${missing.length} 个模块待补齐`
            : "主要模块已返回"}
        </span>
      </div>
      {sources.length > 0 && (
        <div
          className="max-w-full truncate text-xs text-muted-foreground"
          title={sources.join(", ")}
        >
          证据: {sources.slice(0, 3).join(" / ")}
        </div>
      )}
    </section>
  );
}
