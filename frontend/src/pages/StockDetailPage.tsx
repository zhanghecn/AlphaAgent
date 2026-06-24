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
import { useQuery } from "@tanstack/react-query";
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
  fetchBacktestCandidateTrace,
  fetchBacktestSymbolDetail,
  fetchBacktests,
  fetchLatestSymbolBacktest,
  fetchQuantStrategies,
  fetchLatestSymbolQuantState,
  fetchSymbolMarketLine,
  type BacktestRun,
  type BacktestAudit,
  type BacktestAuditEvent,
  type BacktestCandidateTrace,
  type BacktestSymbolDetail,
  type BacktestTrade,
  type BacktestTradeAttribution,
  type QuantStrategyOption,
  type SymbolQuantSignalRow,
  type SymbolLatestQuantState,
  type SymbolMarketLinePoint,
  type SymbolLatestBacktest,
  type SymbolUnifiedMarker,
  type SymbolUnifiedReview,
  type SymbolUnifiedSegment,
} from "@/api/quant";
import { StockQuoteHeader } from "@/features/stocks/StockQuoteHeader";
import { StockKlineChart, type KlineMarker } from "@/features/stocks/StockKlineChart";
import { StockIndicatorPanel } from "@/features/stocks/StockIndicatorPanel";
import { StockFinanceChart } from "@/features/stocks/StockFinanceChart";
import { DEFAULT_BACKTEST_PARAMS } from "@/features/quant/constants";
import { ConceptTag } from "@/components/ConceptTag";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { AddToGroupButton } from "@/features/portfolio/AddToGroupButton";
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
} from "lucide-react";

const STOCK_DETAIL_REVIEW_START = "2025-03-26";

export function StockDetailPage() {
  const { vtSymbol } = useParams<{ vtSymbol: string }>();
  const singleBacktestStrategy = DEFAULT_BACKTEST_PARAMS.strategy;
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

  const latestQuantStateQuery = useQuery({
    queryKey: ["symbolLatestQuantState", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchLatestSymbolQuantState(vtSymbol!, singleBacktestStrategy),
    enabled: !!vtSymbol,
    staleTime: 30_000,
  });
  const marketLineQuery = useQuery({
    queryKey: ["symbolMarketLine", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchSymbolMarketLine(vtSymbol!, {
      strategy: singleBacktestStrategy,
      start: STOCK_DETAIL_REVIEW_START,
      limit: 1000,
    }),
    enabled: !!vtSymbol,
    staleTime: 60_000,
  });
  const quantProcessRangeKey = processDateRangeKey(latestQuantStateQuery.data);
  const latestPortfolioBacktestQuery = useQuery({
    queryKey: ["backtests", "portfolio", singleBacktestStrategy, "baseline"],
    queryFn: () => fetchBacktests(1, "portfolio", singleBacktestStrategy, { baselineOnly: true }),
    enabled: !!vtSymbol,
    staleTime: 60_000,
  });
  const latestPortfolioBacktest = latestPortfolioBacktestQuery.data?.items[0] ?? undefined;
  const latestPortfolioBacktestId = latestPortfolioBacktest?.id ?? undefined;
  const portfolioSymbolDetailQuery = useQuery({
    queryKey: ["portfolioBacktestSymbolDetail", latestPortfolioBacktestId, vtSymbol],
    queryFn: () => fetchBacktestSymbolDetail(Number(latestPortfolioBacktestId), vtSymbol!),
    enabled: Boolean(vtSymbol && latestPortfolioBacktestId),
    staleTime: 60_000,
  });
  const latestSymbolBacktestQuery = useQuery({
    queryKey: ["symbolLatestBacktest", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchLatestSymbolBacktest(vtSymbol!, singleBacktestStrategy),
    enabled: Boolean(vtSymbol),
    staleTime: 5 * 60_000,
  });
  const latestSymbolBacktest = latestSymbolBacktestQuery.data;
  const reviewEndDate =
    latestQuantStateQuery.data?.process?.latest_available_trade_date
    ?? latestQuantStateQuery.data?.process?.end_date
    ?? undefined;
  const needsFullRangeSymbolBacktest =
    latestSymbolBacktest?.status === "ready"
    && (
      (latestSymbolBacktest.start_date ?? "") > STOCK_DETAIL_REVIEW_START
      || Boolean(reviewEndDate && (latestSymbolBacktest.end_date ?? "") < reviewEndDate)
    );
  const latestSymbolBacktestUsable =
    latestSymbolBacktest?.status === "ready" && !needsFullRangeSymbolBacktest;
  const latestSymbolBacktestId = latestSymbolBacktestUsable ? latestSymbolBacktest.backtest_id : undefined;
  const latestSymbolAuditQuery = useQuery({
    queryKey: ["symbolLatestBacktestAudit", latestSymbolBacktestId, vtSymbol],
    queryFn: () => fetchBacktestAudit(Number(latestSymbolBacktestId), vtSymbol!, 500),
    enabled: Boolean(vtSymbol && latestSymbolBacktestId),
    staleTime: 5 * 60_000,
  });
  const autoCreateReviewQuery = useQuery({
    queryKey: ["symbolAutoCreateReview", vtSymbol, singleBacktestStrategy, STOCK_DETAIL_REVIEW_START, quantProcessRangeKey],
    queryFn: () =>
      createSymbolBacktest({
        vt_symbol: vtSymbol!,
        strategy: singleBacktestStrategy,
        start: STOCK_DETAIL_REVIEW_START,
        end: reviewEndDate,
        persist: true,
        min_entry_score: strategyMinEntryScore(strategiesQuery.data?.items ?? [], singleBacktestStrategy),
        strict_entry: true,
        execution_model: "legacy_next_open",
        included_boards: latestQuantStateQuery.data?.process?.included_boards?.length
          ? latestQuantStateQuery.data.process.included_boards
          : ["main"],
      }),
    enabled: Boolean(
      vtSymbol
      && !latestQuantStateQuery.isLoading
      && !latestQuantStateQuery.isFetching
      && !latestSymbolBacktestQuery.isLoading
      && !latestSymbolBacktestQuery.isFetching
      && (latestSymbolBacktestQuery.data?.status === "empty" || needsFullRangeSymbolBacktest)
    ),
    staleTime: 5 * 60_000,
    retry: 1,
  });
  const autoCreatedSymbolBacktestReady = autoCreateReviewQuery.data?.status === "ready";
  const autoReviewAudit = autoCreatedSymbolBacktestReady
    ? autoCreateReviewQuery.data?.audit ?? latestSymbolAuditQuery.data
    : latestSymbolBacktestUsable ? latestSymbolAuditQuery.data : undefined;
  const autoReviewTrades =
    autoCreatedSymbolBacktestReady
      ? autoReviewAudit?.trades
        ?? autoCreateReviewQuery.data?.trades
        ?? (latestSymbolBacktestUsable ? latestSymbolBacktest?.trades : undefined)
        ?? []
      : autoReviewAudit?.trades
    ?? (latestSymbolBacktestUsable ? latestSymbolBacktest?.trades : undefined)
    ?? [];
  const symbolStrategyBacktest = autoCreatedSymbolBacktestReady
    ? autoCreateReviewQuery.data
    : latestSymbolBacktestUsable ? latestSymbolBacktest : latestSymbolBacktest?.status === "empty" ? latestSymbolBacktest : undefined;
  const autoReviewMarkers = useMemo(
    () => backtestAuditToMarkers(autoReviewTrades, autoReviewAudit),
    [autoReviewAudit, autoReviewTrades]
  );
  const isAutoReviewLoading =
    latestSymbolBacktestQuery.isLoading
    || latestSymbolBacktestQuery.isFetching
    || latestSymbolAuditQuery.isLoading
    || latestSymbolAuditQuery.isFetching
    || autoCreateReviewQuery.isLoading
    || autoCreateReviewQuery.isFetching;
  const isMarketLineLoading = (marketLineQuery.isLoading || marketLineQuery.isFetching) && !marketLineQuery.data?.market_line?.length;
  const strategyPathMarkers = useMemo(
    () => sortMarkers(autoReviewMarkers.length ? autoReviewMarkers : []),
    [autoReviewMarkers]
  );
  const backtestMarkers = useMemo(
    () => strategyPathDisplayMarkers(strategyPathMarkers),
    [strategyPathMarkers]
  );
  const displayReview = useMemo(
    () => buildDisplayReview(backtestMarkers),
    [backtestMarkers]
  );
  const selectedBacktestMarker = useMemo(
    () => backtestMarkers.find((marker) => marker.id === selectedBacktestMarkerId) ?? defaultSelectedMarker(backtestMarkers),
    [backtestMarkers, selectedBacktestMarkerId]
  );
  const selectedSignalDate = selectedBacktestMarker?.signalDate ?? null;
  const selectedSymbolBacktestId =
    autoCreatedSymbolBacktestReady
      ? autoCreateReviewQuery.data?.backtest_id
      : latestSymbolBacktestUsable ? latestSymbolBacktestId : undefined;
  const selectedCandidateTraceQuery = useQuery({
    queryKey: ["symbolSelectedCandidateTrace", selectedSymbolBacktestId, vtSymbol, selectedSignalDate],
    queryFn: () => fetchBacktestCandidateTrace(Number(selectedSymbolBacktestId), vtSymbol!, selectedSignalDate!),
    enabled: Boolean(vtSymbol && selectedSymbolBacktestId && selectedSignalDate),
    staleTime: 60_000,
  });
  useEffect(() => {
    setSelectedBacktestMarkerId((current) => {
      if (current && backtestMarkers.some((marker) => marker.id === current)) return current;
      return defaultSelectedMarker(backtestMarkers)?.id ?? null;
    });
  }, [backtestMarkers]);

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

      {/* 加入持仓 entry (self-contained: pick a group to add this stock to) */}
      <div className="flex items-center gap-2">
        <AddToGroupButton vtSymbol={vtSymbol!} name={quote?.name} />
      </div>

      {/* Data evidence bar */}
      <StockDataEvidence sources={sources} missing={missing} />

      {/* ⭐ Identity Card — Core Innovation */}
      <IdentityCard
        conceptData={concepts}
        isLoading={conceptQuery.isLoading}
      />

      <SingleStockBacktestPanel
        strategy={singleBacktestStrategy}
        strategies={strategyOptions}
        quantState={latestQuantStateQuery.data}
        portfolioBacktest={latestPortfolioBacktest}
        portfolioDetail={portfolioSymbolDetailQuery.data}
        markerCount={backtestMarkers.length}
        isQuantStateLoading={latestQuantStateQuery.isLoading || latestQuantStateQuery.isFetching}
        quantStateError={latestQuantStateQuery.error}
        isPortfolioDetailLoading={portfolioSymbolDetailQuery.isLoading || portfolioSymbolDetailQuery.isFetching}
        portfolioDetailError={portfolioSymbolDetailQuery.error}
        isAutoReviewLoading={isAutoReviewLoading}
        autoReviewError={latestSymbolBacktestQuery.error ?? latestSymbolAuditQuery.error ?? autoCreateReviewQuery.error}
        autoReviewAudit={autoReviewAudit}
        symbolStrategyBacktest={symbolStrategyBacktest}
        marketLine={marketLineQuery.data?.market_line}
        displayReview={displayReview}
        displayMarkers={backtestMarkers}
      />

      {/* K-line chart */}
      <div className="rounded-lg border p-3 sm:p-4">
        <StockKlineChart
          vtSymbol={vtSymbol}
          markers={backtestMarkers}
          marketLine={marketLineQuery.data?.market_line}
          markersLoading={isAutoReviewLoading && backtestMarkers.length === 0}
          marketLineLoading={isMarketLineLoading}
          selectedMarkerId={selectedBacktestMarker?.id ?? null}
          onMarkerClick={handleBacktestMarkerClick}
        />
        <BacktestMarkerInsight
          marker={selectedBacktestMarker}
          loading={isAutoReviewLoading && backtestMarkers.length === 0}
          candidateTrace={selectedCandidateTraceQuery.data}
          candidateTraceLoading={selectedCandidateTraceQuery.isLoading || selectedCandidateTraceQuery.isFetching}
        />
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
  strategy,
  strategies,
  quantState,
  portfolioBacktest,
  portfolioDetail,
  markerCount,
  isQuantStateLoading,
  quantStateError,
  isPortfolioDetailLoading,
  portfolioDetailError,
  isAutoReviewLoading,
  autoReviewError,
  autoReviewAudit,
  symbolStrategyBacktest,
  marketLine,
  displayReview,
  displayMarkers,
}: {
  strategy: string;
  strategies: QuantStrategyOption[];
  quantState?: SymbolLatestQuantState;
  portfolioBacktest?: BacktestRun | null;
  portfolioDetail?: BacktestSymbolDetail | null;
  markerCount: number;
  isQuantStateLoading: boolean;
  quantStateError: unknown;
  isPortfolioDetailLoading: boolean;
  portfolioDetailError: unknown;
  isAutoReviewLoading: boolean;
  autoReviewError: unknown;
  autoReviewAudit?: BacktestAudit;
  symbolStrategyBacktest?: SymbolLatestBacktest | Awaited<ReturnType<typeof createSymbolBacktest>>;
  marketLine?: SymbolMarketLinePoint[] | null;
  displayReview?: SymbolUnifiedReview | null;
  displayMarkers: KlineMarker[];
}) {
  const candidate = quantState?.candidate?.item;
  const latestSignal = quantState?.signal?.latest_entry_signal ?? quantState?.signal?.latest;
  const hasPortfolioExecutions = (portfolioDetail?.trades?.length ?? 0) > 0
    || (portfolioDetail?.orders?.length ?? 0) > 0
    || (portfolioDetail?.trade_attribution?.length ?? 0) > 0;
  const latestMarketLine = marketLine?.[marketLine.length - 1];

  return (
    <section className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <BarChart3 size={15} />
            单股策略评估
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            按当前量化策略独立复盘这只股票的完整走势，主图只显示该策略得到的买入、拒买和卖出点。
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="text-sm">
            <div className="text-xs text-muted-foreground">评估策略</div>
            <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2">
              {strategies.find((item) => item.id === strategy)?.name ?? "主线龙回头回踩低吸"}
            </div>
          </div>
        </div>
      </div>
      <div className="mt-3 rounded-md border bg-muted/20 p-3 text-sm text-muted-foreground">
        股票详情不按候选排名、组合满仓或真实组合持仓决定买卖点；组合回测只作为辅助参考。牛熊线用于核对行情状态，不参与信号分。
      </div>
      <UnifiedReviewSummary review={displayReview} latestMarketLine={latestMarketLine} />
      <StrategyTimelinePanel
        displayMarkers={displayMarkers}
        isLoading={isAutoReviewLoading}
        error={autoReviewError}
      />

      <SymbolStrategyBacktestSummary
        result={symbolStrategyBacktest}
        audit={autoReviewAudit}
        isLoading={isAutoReviewLoading}
        error={autoReviewError}
        markerCount={markerCount}
      />

      {isQuantStateLoading ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          正在读取最近量化过程...
        </div>
      ) : quantStateError ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {quantStateError instanceof Error ? quantStateError.message : "读取最近量化过程失败"}
        </div>
      ) : quantState?.status === "ready" ? (
        <div className="mt-4 space-y-4">
          <LatestSignalScoreSummary signal={latestSignal} candidate={candidate} />
          {hasPortfolioExecutions ? (
            <PortfolioBacktestSymbolSummary
              backtest={portfolioBacktest}
              detail={portfolioDetail}
              markerCount={markerCount}
              isLoading={isPortfolioDetailLoading}
              error={portfolioDetailError}
              strategyName={strategies.find((item) => item.id === strategy)?.name ?? "主线龙回头回踩低吸"}
              compact
            />
          ) : null}
        </div>
      ) : (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          {quantState?.message ?? "暂无全局量化过程。请先在量化页刷新候选并回测。"}
        </div>
      )}
    </section>
  );
}


function PortfolioBacktestSymbolSummary({
  backtest,
  detail,
  markerCount,
  isLoading,
  error,
  strategyName,
  compact = false,
}: {
  backtest?: BacktestRun | null;
  detail?: BacktestSymbolDetail | null;
  markerCount: number;
  isLoading: boolean;
  error: unknown;
  strategyName: string;
  compact?: boolean;
}) {
  if (isLoading && !detail) {
    return (
      <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
        正在读取最新组合回测逐股明细...
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
        {error instanceof Error ? error.message : "读取组合回测逐股明细失败"}
      </div>
    );
  }

  const trades = detail?.trades ?? [];
  const orders = detail?.orders ?? [];
  const attributionRows = detail?.trade_attribution ?? [];
  const closedRows = attributionRows.filter((row) => row.status === "closed");
  const buyTrades = trades.filter((trade) => trade.side === "BUY");
  const sellTrades = trades.filter((trade) => trade.side === "SELL");
  const rejectedOrders = orders.filter((order) => order.status === "rejected");
  const openRows = attributionRows.filter((row) => row.status === "open");
  const realizedReturnPct = sumNumbers(closedRows.map((row) => row.return_pct));
  const openReturnPct = sumNumbers(openRows.map((row) => latestOpenReturnPct(row, detail?.positions ?? [])));
  const markedReturnPct = sumNumbers([realizedReturnPct, openReturnPct]);
  const averageReturnPct = closedRows.length && realizedReturnPct != null ? realizedReturnPct / closedRows.length : null;
  const winRatePct = closedRows.length
    ? closedRows.filter((row) => (row.return_pct ?? 0) > 0).length / closedRows.length * 100
    : null;
  const maxFloatingPct = maxMaybe(attributionRows.map((row) => row.max_floating_pnl_pct));
  const minFloatingPct = minMaybe(attributionRows.map((row) => row.min_floating_pnl_pct));
  const statusLabel = openRows.length ? "持有中" : closedRows.length ? "已闭合" : trades.length ? "已成交" : "无成交";
  const dateRange = backtest?.start_date && backtest?.end_date
    ? `${backtest.start_date} 至 ${backtest.end_date}`
    : "--";

  return (
    <div className="mt-4 space-y-4">
      <div className="rounded-md border bg-muted/20 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-medium">
            <ShieldCheck size={14} />
            组合回测参考
          </div>
          <Badge variant={closedRows.length || openRows.length ? "secondary" : "outline"} className="rounded-md">
            {statusLabel}
          </Badge>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <InfoCell label="日期范围" value={dateRange} />
          <InfoCell label="过程来源" value="组合回测" />
          <InfoCell label="回测ID" value={backtest?.id ? `#${backtest.id}` : "--"} />
          <InfoCell label="策略" value={strategyName} />
          <InfoCell label="K线标记" value={`${markerCount} 个`} />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          这里只解释组合真实买卖，不决定股票详情主图买卖点；主图按该股票独立策略复盘展示。
        </p>
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-6">
        <InfoCell label="买入成交" value={`${buyTrades.length} 次`} valueClass={buyTrades.length ? "text-rise" : undefined} />
        <InfoCell label="卖出成交" value={`${sellTrades.length} 次`} />
        <InfoCell label="买/卖拒绝" value={`${rejectedOrders.length} 次`} valueClass={rejectedOrders.length ? "text-fall" : undefined} />
        <InfoCell label="闭合交易" value={`${closedRows.length} 笔`} />
        <InfoCell label="持仓状态" value={statusLabel} />
        <InfoCell label="执行方式" value={portfolioExecutionModeLabel(attributionRows)} />
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-5">
        <InfoCell label="闭合收益率" value={formatPct(realizedReturnPct)} valueClass={priceColorClass(realizedReturnPct)} />
        <InfoCell label="当前浮盈率" value={formatPct(openReturnPct)} valueClass={priceColorClass(openReturnPct)} />
        <InfoCell label="盯市合计" value={formatPct(markedReturnPct)} valueClass={priceColorClass(markedReturnPct)} />
        <InfoCell label="平均单笔" value={formatPct(averageReturnPct)} valueClass={priceColorClass(averageReturnPct)} />
        <InfoCell label="胜率" value={formatPct(winRatePct)} />
      </div>
      <div className="text-sm">
        <InfoCell label="最大浮盈/浮亏" value={`${formatPct(maxFloatingPct)} / ${formatPct(minFloatingPct)}`} valueClass={priceColorClass(maxFloatingPct)} />
      </div>
      {!compact && (closedRows.length || openRows.length ? (
        <PortfolioClosedTradeTable rows={attributionRows} positions={detail?.positions ?? []} />
      ) : (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">
          最新组合回测中该股票没有形成实际买卖。若 K 线只有信号或拒绝标记，可点击标记查看原因。
        </div>
      ))}
    </div>
  );
}

function SymbolStrategyBacktestSummary({
  result,
  audit,
  isLoading,
  error,
  markerCount,
}: {
  result?: SymbolLatestBacktest | Awaited<ReturnType<typeof createSymbolBacktest>>;
  audit?: BacktestAudit;
  isLoading: boolean;
  error: unknown;
  markerCount: number;
}) {
  if (isLoading && !result && !audit) {
    return <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">正在生成该股票的策略买卖点...</div>;
  }
  if (error && !result && !audit) {
    return (
      <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
        {error instanceof Error ? error.message : "生成单股策略评估失败"}
      </div>
    );
  }
  const metrics = result?.metrics;
  const trades = audit?.trades ?? result?.trades ?? [];
  const orders = audit?.orders ?? result?.orders ?? [];
  const buyCount = metrics?.buy_count ?? trades.filter((trade) => trade.side === "BUY").length;
  const sellCount = metrics?.sell_count ?? trades.filter((trade) => trade.side === "SELL").length;
  const rejectedCount = orders.filter((order) => order.status === "rejected").length;
  const tradeCount = metrics?.trade_count ?? Math.min(buyCount, sellCount);
  const resultStart = symbolBacktestStartDate(result);
  const resultEnd = symbolBacktestEndDate(result);
  const range = (audit?.start_date || resultStart) && (audit?.end_date || resultEnd)
    ? `${audit?.start_date ?? resultStart} 至 ${audit?.end_date ?? resultEnd}`
    : "--";
  return (
    <div className="mt-4 space-y-3">
      <div className="rounded-md border bg-muted/20 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2 font-medium">
            <ShieldCheck size={14} />
            单股策略买卖点
          </div>
          <Badge variant={tradeCount ? "secondary" : "outline"} className="rounded-md">
            {result?.status === "empty" ? "待生成" : tradeCount ? "已生成" : "无闭合交易"}
          </Badge>
        </div>
        <div className="mt-3 grid gap-3 md:grid-cols-5">
          <InfoCell label="日期范围" value={range} />
          <InfoCell label="回测ID" value={result?.backtest_id ? `#${result.backtest_id}` : audit?.backtest_id ? `#${audit.backtest_id}` : "--"} />
          <InfoCell label="K线标记" value={`${markerCount} 个`} />
          <InfoCell label="买入/卖出" value={`${buyCount} / ${sellCount}`} />
          <InfoCell label="拒绝" value={`${rejectedCount} 次`} valueClass={rejectedCount ? "text-fall" : undefined} />
        </div>
      </div>
      <div className="grid gap-3 text-sm md:grid-cols-5">
        <InfoCell label="预期收益率" value={formatPct(metrics?.total_return_pct)} valueClass={priceColorClass(metrics?.total_return_pct)} />
        <InfoCell label="最大回撤" value={formatPct(metrics?.max_drawdown_pct)} valueClass={priceColorClass(metrics?.max_drawdown_pct)} />
        <InfoCell label="胜率" value={metrics?.win_rate == null ? "--" : formatPct(metrics.win_rate * 100)} />
        <InfoCell label="交易笔数" value={`${tradeCount ?? 0} 笔`} />
        <InfoCell label="盈亏比" value={formatMaybeNumber(metrics?.profit_factor, 2)} />
      </div>
    </div>
  );
}

function UnifiedReviewSummary({
  review,
  latestMarketLine,
}: {
  review?: SymbolUnifiedReview | null;
  latestMarketLine?: SymbolMarketLinePoint | null;
}) {
  if (!review) {
    return (
      <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
        正在等待统一买卖统计。该统计按日期顺序聚合买入簇，不使用未来收益挑买点。
      </div>
    );
  }
  const summary = review.summary;
  const markerCounts = review.markers.reduce<Record<string, number>>((acc, marker) => {
    acc[marker.kind] = (acc[marker.kind] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <div className="mt-4 space-y-3">
      <div className="grid gap-3 text-sm md:grid-cols-6">
        <InfoCell label="买入" value={`${markerCounts.buy ?? 0} 次`} valueClass={(markerCounts.buy ?? 0) > 0 ? "text-rise" : undefined} />
        <InfoCell label="拒买" value={`${markerCounts.rejected_buy ?? 0} 次`} valueClass={(markerCounts.rejected_buy ?? 0) > 0 ? "text-fall" : undefined} />
        <InfoCell label="卖出" value={`${markerCounts.sell ?? 0} 次`} />
        <InfoCell label="闭合交易" value={`${summary.trade_count ?? 0} 笔`} />
        <InfoCell label="胜率" value={formatPct(summary.win_rate_pct)} />
        <InfoCell label="牛熊线" value={latestMarketLine?.label ?? "--"} valueClass={marketLineTextClass(latestMarketLine?.state)} />
      </div>
      <div className="grid gap-3 text-sm md:grid-cols-4">
        <InfoCell label="累计收益" value={formatPct(summary.compound_return_pct)} valueClass={priceColorClass(summary.compound_return_pct)} />
        <InfoCell label="平均单笔" value={formatPct(summary.average_return_pct)} valueClass={priceColorClass(summary.average_return_pct)} />
        <InfoCell label="最大回撤" value={formatPct(summary.max_drawdown_pct)} valueClass={priceColorClass(summary.max_drawdown_pct)} />
        <InfoCell label="行情分" value={formatMaybeNumber(latestMarketLine?.score, 1)} />
      </div>
    </div>
  );
}

function PortfolioClosedTradeTable({
  rows,
  positions,
}: {
  rows: NonNullable<BacktestSymbolDetail["trade_attribution"]>;
  positions: BacktestSymbolDetail["positions"];
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">组合回测交易收益率</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>买入日期</TableHead>
            <TableHead>卖出日期</TableHead>
            <TableHead className="text-right">买入价</TableHead>
            <TableHead className="text-right">卖出价</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead className="text-right">最大浮盈</TableHead>
            <TableHead className="text-right">最大浮亏</TableHead>
            <TableHead className="text-right">持有天数</TableHead>
            <TableHead>退出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => {
            const displayReturnPct = row.status === "open" ? latestOpenReturnPct(row, positions) : row.return_pct;
            return (
              <TableRow key={`${row.vt_symbol}-${row.entry_date}-${row.exit_date ?? "open"}-${index}`}>
                <TableCell className="tabular-nums">{row.entry_date ?? "--"}</TableCell>
                <TableCell className="tabular-nums">{row.exit_date ?? (row.status === "open" ? "持有中" : "--")}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(row.entry_price)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(row.exit_price)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(displayReturnPct))}>
                  {formatPct(displayReturnPct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.max_floating_pnl_pct))}>
                  {formatPct(row.max_floating_pnl_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.min_floating_pnl_pct))}>
                  {formatPct(row.min_floating_pnl_pct)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{row.holding_days ?? "--"}</TableCell>
                <TableCell className="text-muted-foreground">{row.status === "open" ? "持有中" : exitReasonLabel(row.exit_reason)}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}

function LatestSignalScoreSummary({
  signal,
  candidate,
  compact = false,
}: {
  signal?: SymbolQuantSignalRow | null;
  candidate?: { trade_date?: string | null; action?: string | null; rank?: number | null } | null;
  compact?: boolean;
}) {
  if (!signal) {
    return (
      <div className={cn("rounded-md border p-3 text-sm text-muted-foreground", compact ? "" : "mt-4")}>
        暂无最近评分记录。请先在量化页刷新候选并回测。
      </div>
    );
  }

  const evidence = safeRaw(signal.evidence);
  const failedRules = quantSignalFailedRules(signal, evidence);
  const notes = evidenceStringArray(evidence.score_notes).map(readableStrategyScoreNote);
  const breakdown = scoreBreakdownRows(evidence.score_breakdown);
  const lowSuctionDays = getRawNumber(evidence, "low_suction_days");
  const lowSuctionScore = getRawNumber(evidence, "low_suction_buildup_score");
  const lowSuctionStage = getRawText(evidence, "low_suction_stage_label");
  const lowSuctionQuality = getRawText(evidence, "low_suction_launch_quality_label");
  const lowSuctionDragon = getRawText(evidence, "low_suction_dragon_label");
  const convergence = getRawNumber(evidence, "ma_convergence_pct");
  const state = getRawText(evidence, "dragon_state");
  const support = getRawText(evidence, "support_type");
  const action = quantSignalAction(signal);
  const isBuy = action === "BUY";
  const signalLabel = signal.signal_label || action;

  return (
    <div className={cn("rounded-md border p-3 text-sm", compact ? "" : "mt-4")}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-medium">为什么这个分数</div>
        <Badge variant={isBuy ? "secondary" : "outline"} className="rounded-md">
          {signalLabel}
        </Badge>
      </div>
      <div className="mt-2 text-xs text-muted-foreground">
        总分 = 分项贡献相加后扣风险；低吸蓄势是同一回踩低吸策略里的连续加分，不是额外策略。
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-6">
        <InfoCell label="评分日" value={signal.trade_date ?? "--"} />
        <InfoCell label="总分" value={formatMaybeNumber(signal.total_score, 1)} valueClass={isBuy ? "text-rise" : undefined} />
        <InfoCell label="信号" value={signalLabel} valueClass={isBuy ? "text-rise" : undefined} />
        <InfoCell label="状态" value={strategyDragonStateLabel(state)} />
        <InfoCell label="低吸蓄势" value={lowSuctionDays == null ? "--" : `${lowSuctionDays.toFixed(0)} 天`} />
        <InfoCell label="低吸阶段" value={lowSuctionStage && lowSuctionStage !== "非低吸蓄势" ? lowSuctionStage : "--"} />
        <InfoCell label="低吸质量" value={lowSuctionQuality && lowSuctionQuality !== "非低吸买点" ? lowSuctionQuality : "--"} />
        <InfoCell label="启动诊断" value={lowSuctionDragon && lowSuctionDragon !== "非低吸龙回头" ? lowSuctionDragon : "--"} />
        <InfoCell label="均线收敛" value={convergence == null ? "--" : formatPct(convergence)} />
        <InfoCell label="候选" value={candidateLabelForSignal(signal, candidate)} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <InfoCell label="承接" value={strategySupportTypeLabel(support)} />
        <InfoCell label="低吸蓄势分" value={lowSuctionScore == null ? "--" : formatNumber(lowSuctionScore, 1)} />
        <InfoCell label="流动性" value={formatMaybeNumber(signal.liquidity_score, 1)} />
        <InfoCell label="风险分" value={formatMaybeNumber(signal.risk_score, 1)} />
      </div>
      {notes.length ? (
        <div className="mt-3 text-xs leading-6 text-muted-foreground">
          {notes.join("；")}
        </div>
      ) : null}
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
        {breakdown.map((row) => (
          <div key={row.name} className="rounded-md border bg-muted/20 px-2 py-1.5">
            <div className="text-xs text-muted-foreground">{row.name}</div>
            <div className="mt-0.5 text-sm font-medium tabular-nums">
              {row.score} * {row.weight} = {row.contribution}
            </div>
          </div>
        ))}
      </div>
      <div className="mt-3 text-xs text-muted-foreground">
        失败规则：{failedRules.length ? failedRules.map(strategyFailedRuleLabel).join("、") : "通过"}
      </div>
    </div>
  );
}

function BacktestMarkerInsight({
  marker,
  loading,
  candidateTrace,
  candidateTraceLoading = false,
}: {
  marker: KlineMarker | null;
  loading: boolean;
  candidateTrace?: BacktestCandidateTrace;
  candidateTraceLoading?: boolean;
}) {
  if (!marker) {
    return (
      <div className="mt-4 border-t pt-3 text-sm text-muted-foreground">
        {loading ? "正在生成单股策略买卖点，K 线可先查看。" : "当前没有可显示的单股策略买卖点。"}
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
        <InfoCell label="对应候选" value={candidateTraceLabel(candidateTrace, candidateTraceLoading)} />
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

function StrategyTimelinePanel({
  displayMarkers,
  isLoading,
  error,
}: {
  displayMarkers: KlineMarker[];
  isLoading: boolean;
  error: unknown;
}) {
  const rows = displayMarkers.slice(-10).reverse();
  if (isLoading && !rows.length) {
    return <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">正在读取单股策略买卖点...</div>;
  }
  if (error && !rows.length) {
    return (
      <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200">
        单股策略买卖点暂不可用，请稍后重新打开页面。
      </div>
    );
  }
  if (!rows.length) return null;
  return (
    <div className="mt-3 overflow-hidden rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-28">日期</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">价格</TableHead>
            <TableHead className="text-right">量化分数</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead>原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((marker) => {
            const score = timelineMarkerScore(marker);
            return (
              <TableRow key={marker.id ?? `${marker.time}-${marker.side}-${marker.price ?? ""}`}>
                <TableCell className="font-mono text-xs">{marker.time}</TableCell>
                <TableCell>{markerBadgeLabel(marker)}</TableCell>
                <TableCell className="text-right tabular-nums">{marker.price == null ? "--" : formatPrice(marker.price)}</TableCell>
                <TableCell className="text-right tabular-nums">{score == null ? "--" : formatNumber(score, 1)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(marker.returnPct))}>
                  {marker.returnPct == null ? "--" : formatPct(marker.returnPct)}
                </TableCell>
                <TableCell className="text-muted-foreground">{marker.reasonLabel ?? marker.reasonText ?? marker.reason ?? "--"}</TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
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
  if (marker.markerKind === "signal" || marker.status === "signal") return "买入";
  if (marker.markerKind === "rejected" || marker.status === "rejected") return "拒买";
  if (marker.side === "BUY") return "买入";
  if (marker.side === "SELL") return "卖出";
  return marker.side || "--";
}

function strategyMinEntryScore(strategies: QuantStrategyOption[], strategyId: string) {
  return strategies.find((item) => item.id === strategyId)?.default_min_entry_score ?? DEFAULT_BACKTEST_PARAMS.min_entry_score;
}

function processDateRangeKey(state?: SymbolLatestQuantState) {
  const start = state?.process?.start_date ?? STOCK_DETAIL_REVIEW_START;
  const end = state?.process?.end_date ?? "latest";
  return `${start}:${end}`;
}

function formatMaybeNumber(value?: number | null, digits = 2) {
  return value == null ? "--" : formatNumber(value, digits);
}

type SymbolBacktestResult = SymbolLatestBacktest | Awaited<ReturnType<typeof createSymbolBacktest>>;

function symbolBacktestStartDate(result?: SymbolBacktestResult) {
  if (!result) return null;
  const raw = result as Record<string, unknown>;
  return typeof raw.start_date === "string" ? raw.start_date : typeof raw.start === "string" ? raw.start : null;
}

function symbolBacktestEndDate(result?: SymbolBacktestResult) {
  if (!result) return null;
  const raw = result as Record<string, unknown>;
  return typeof raw.end_date === "string" ? raw.end_date : typeof raw.end === "string" ? raw.end : null;
}

function candidateLabelForSignal(signal?: SymbolQuantSignalRow | null, candidate?: { trade_date?: string | null; action?: string | null; rank?: number | null } | null) {
  if (!signal?.trade_date) return "--";
  if (!candidate) return "未找到同日候选";
  if (candidate.trade_date !== signal.trade_date) return `最新候选 ${candidate.trade_date ?? "--"} ${candidate.action ?? "--"} #${candidate.rank ?? "--"}`;
  return `${candidate.action ?? "--"} #${candidate.rank ?? "--"}`;
}

function candidateTraceLabel(trace?: BacktestCandidateTrace, loading = false) {
  if (loading) return "查询中";
  if (!trace) return "--";
  const action = trace.action ?? trace.recommendation?.action ?? "--";
  const rank = trace.rank ?? trace.recommendation?.rank;
  const score = trace.total_score ?? trace.recommendation?.total_score;
  const scoreText = score == null ? "" : ` ${formatNumber(score, 1)}分`;
  const rankText = rank == null ? "未进候选" : `#${rank}`;
  return `${trace.signal_date} ${action} ${rankText}${scoreText}`;
}

function quantSignalAction(signal?: SymbolQuantSignalRow | null) {
  if (!signal) return "WATCH";
  if (signal.action) return signal.action.toUpperCase();
  if (signal.executable_entry_signal != null) return signal.executable_entry_signal ? "BUY" : "WATCH";
  const evidence = safeRaw(signal.evidence);
  return signal.entry_signal && !quantSignalFailedRules(signal, evidence).length ? "BUY" : "WATCH";
}

function quantSignalFailedRules(signal: SymbolQuantSignalRow, evidence: Record<string, unknown>) {
  if (Array.isArray(signal.failed_rules)) return signal.failed_rules.map((item) => String(item)).filter(Boolean);
  return evidenceStringArray(evidence.failed_rules);
}

function strategyPathDisplayMarkers(strategyPath: KlineMarker[]): KlineMarker[] {
  const pathMarkers = strategyPath.filter((marker) => {
    if (marker.markerKind === "trade") return true;
    return marker.markerKind === "rejected" && String(marker.side).toUpperCase() === "BUY";
  });
  return cleanDisplayMarkers(positionPathMarkers(pathMarkers));
}

function positionPathMarkers(markers: KlineMarker[]): KlineMarker[] {
  const selected: KlineMarker[] = [];
  let holding = false;
  for (const marker of sortMarkers(markers)) {
    const side = String(marker.side).toUpperCase();
    const rejected = marker.markerKind === "rejected" || marker.status === "rejected";
    const buy = side === "BUY" && !rejected;
    const sell = side === "SELL" && !rejected;
    if (holding && (buy || rejected)) continue;
    selected.push(marker);
    if (buy) holding = true;
    if (sell) holding = false;
  }
  return sortMarkers(selected);
}

function cleanDisplayMarkers(markers: KlineMarker[]): KlineMarker[] {
  return collapsePendingSellMarkers(normalizeDisplayReturnPct(markers));
}

function normalizeDisplayReturnPct(markers: KlineMarker[]): KlineMarker[] {
  return markers.map((marker) => {
    if (String(marker.side).toUpperCase() !== "SELL" || marker.returnPct == null) return marker;
    const raw = safeRaw(marker.raw);
    if (raw.return_pct != null || raw.returnPct != null) return marker;
    if (raw.pnl != null) return { ...marker, returnPct: null };
    return marker;
  });
}

function collapsePendingSellMarkers(markers: KlineMarker[]): KlineMarker[] {
  const sorted = sortMarkers(markers);
  const selected: KlineMarker[] = [];
  let lastSellIndex = -1;
  for (const marker of sorted) {
    if (String(marker.side).toUpperCase() === "BUY" && marker.markerKind !== "rejected" && marker.status !== "rejected") {
      lastSellIndex = -1;
      selected.push(marker);
      continue;
    }
    if (String(marker.side).toUpperCase() === "SELL") {
      if (lastSellIndex >= 0) {
        selected[lastSellIndex] = marker;
      } else {
        selected.push(marker);
        lastSellIndex = selected.length - 1;
      }
      continue;
    }
    selected.push(marker);
  }
  return sortMarkers(selected);
}

function buildDisplayReview(markers: KlineMarker[]): SymbolUnifiedReview {
  const segments = displaySegments(markers);
  return {
    markers: markers.map(displayMarkerToUnifiedMarker),
    segments,
    summary: displaySegmentSummary(segments),
    method: "页面显示口径：股票详情主图按当前策略对该股票独立复盘得到买入、拒买、卖出；组合回测只作辅助解释。",
    not_used_for_signal_score: true,
  };
}

function displayMarkerToUnifiedMarker(marker: KlineMarker): SymbolUnifiedMarker {
  return {
    kind: marker.markerKind === "rejected" || marker.status === "rejected" ? "rejected_buy" : String(marker.side).toUpperCase() === "SELL" ? "sell" : "buy",
    label: markerBadgeLabel(marker),
    trade_date: marker.time,
    price: marker.price ?? null,
    score: markerScore(marker) || null,
    return_pct: marker.returnPct ?? null,
    max_drawdown_pct: null,
    raw: marker.raw,
  };
}

function displaySegments(markers: KlineMarker[]): SymbolUnifiedSegment[] {
  const segments: SymbolUnifiedSegment[] = [];
  let openBuy: KlineMarker | null = null;
  for (const marker of sortMarkers(markers)) {
    if (marker.markerKind === "rejected" || marker.status === "rejected") continue;
    if (String(marker.side).toUpperCase() === "BUY") {
      openBuy = marker;
      continue;
    }
    if (String(marker.side).toUpperCase() !== "SELL" || !openBuy) continue;
    const returnPct = marker.returnPct ?? percentReturn(openBuy.price, marker.price);
    segments.push({
      entry_date: openBuy.time,
      exit_date: marker.time,
      entry_price: openBuy.price ?? null,
      exit_price: marker.price ?? null,
      return_pct: returnPct,
      max_drawdown_pct: null,
      win: returnPct != null ? returnPct > 0 : undefined,
    });
    openBuy = null;
  }
  return segments;
}

function displaySegmentSummary(segments: SymbolUnifiedSegment[]): SymbolUnifiedReview["summary"] {
  const returns = segments.map((segment) => segment.return_pct).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (!returns.length) {
    return {
      trade_count: segments.length,
      win_count: 0,
      win_rate_pct: null,
      compound_return_pct: null,
      average_return_pct: null,
      max_drawdown_pct: null,
    };
  }
  const compound = returns.reduce((value, item) => value * (1 + item / 100), 1);
  const drawdowns = segments.map((segment) => segment.max_drawdown_pct).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const wins = returns.filter((value) => value > 0);
  return {
    trade_count: returns.length,
    win_count: wins.length,
    win_rate_pct: wins.length / returns.length * 100,
    compound_return_pct: (compound - 1) * 100,
    average_return_pct: returns.reduce((sum, value) => sum + value, 0) / returns.length,
    max_drawdown_pct: drawdowns.length ? Math.min(...drawdowns) : null,
  };
}

function percentReturn(entry?: number | null, exit?: number | null) {
  if (!entry || !exit) return null;
  return (exit / entry - 1) * 100;
}

function backtestAuditToMarkers(trades: BacktestTrade[], audit?: BacktestAudit): KlineMarker[] {
  const returnQueues = closedReturnQueues(trades);
  const markers = audit?.events?.length
    ? audit.events.flatMap((event, index) => auditEventToMarkers(event, index, returnQueues))
    : trades.map((trade, index) => tradeToExecutionMarker(trade, index, nextReturnForSell(returnQueues, trade)));
  return dedupeMarkers(suppressResolvedSignals(markers)).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function auditEventToMarkers(
  event: BacktestAuditEvent,
  index: number,
  returnQueues: Map<string, number[]>
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
    id: `single-review-signal-${event.vt_symbol}-${signalDate}-${index}`,
    time: signalDate,
    side: "BUY",
    markerKind: "signal",
    status: "signal",
    price: null,
    text: "信号",
    title: "BUY 信号",
    strategy: auditSignalText(event),
    signalText: auditSignalText(event),
    executionText: `计划在 ${executeDate} 按执行规则撮合；只有执行规则通过才会成为实际买入。`,
    reasonText: "BUY 信号代表信号日收盘后策略认为可买，不代表下一交易日一定成交。",
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
  returnQueues: Map<string, number[]>
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
    id: `single-review-rejected-${event.vt_symbol}-${executeDate}-${event.side}-${event.reason ?? "unknown"}-${index}`,
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
    signalText: auditSignalText(event),
    executionText: event.message ?? `${sideLabel}未成交：${reasonLabel}`,
    reasonText: markerReasonTextFromReason(event.reason),
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
    id: `single-review-trade-${event.vt_symbol}-${event.trade_date}-${event.side}-${index}`,
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
    signalText: isBuy ? auditSignalText(event) : `${signalDate ?? "信号日"} 收盘后触发 ${event.reason_label ?? exitReasonLabel(event.reason)}。`,
    executionText: event.message,
    reasonText: event.reason_label ?? markerReasonTextFromReason(event.reason),
    evidence: auditMarkerEvidence(event),
    raw: event.raw,
    text: isBuy ? "买" : "卖",
  };
}

function tradeToExecutionMarker(trade: BacktestTrade, index: number, returnPct: number | null = null): KlineMarker {
  const execution = markerExecutionRaw(trade);
  const isBuy = trade.side === "BUY";
  const signalDate = isBuy ? getRawText(execution, "reference_date") : getRawText(execution, "signal_date");
  const executeDate = getRawText(execution, "execute_date") ?? trade.trade_date;
  return {
    id: `single-review-trade-${trade.vt_symbol}-${trade.trade_date}-${trade.side}-${index}`,
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
    executionMode: getRawText(execution, "mode"),
    title: isBuy ? "买入成交" : `卖出成交：${exitReasonLabel(trade.reason)}`,
    strategy: isBuy ? "单股复盘中买入成交。" : "单股复盘中卖出成交。",
    signalText: isBuy ? auditSignalTextFromRaw(trade.raw) : `${signalDate ?? "信号日"} 收盘后触发 ${exitReasonLabel(trade.reason)}。`,
    executionText: auditExecutionText(trade.side, execution, trade.price),
    reasonText: isBuy ? markerReasonTextFromReason(trade.reason) : exitReasonLabel(trade.reason),
    evidence: tradeMarkerEvidence(trade, execution),
    raw: trade.raw,
    text: isBuy ? "买" : "卖",
  };
}

function auditSignalText(event: BacktestAuditEvent): string {
  return auditSignalTextFromRaw(event.raw);
}

function auditSignalTextFromRaw(rawValue: unknown): string {
  const raw = safeRaw(rawValue);
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

function auditExecutionText(side: string, execution: Record<string, unknown>, price?: number | null) {
  const mode = getRawText(execution, "mode");
  if (side === "BUY" && mode === "daily_next_open") return `信号次一交易日按日线开盘价买入，价格 ${formatPrice(price)}。`;
  if (side === "BUY" && mode === "minute_1430") return `执行日实时分钟快照成交，价格 ${formatPrice(price)}。`;
  if (side === "BUY" && mode === "daily_close_proxy") return `使用执行日收盘价代理成交，价格 ${formatPrice(price)}。`;
  if (side === "SELL" && (mode === "daily_next_open" || mode === "daily_next_open_sell")) {
    return `信号次一交易日按日线开盘价卖出，价格 ${formatPrice(price)}。`;
  }
  if (side === "SELL" && mode === "minute_1430_sell") return `执行日实时分钟快照卖出，价格 ${formatPrice(price)}。`;
  if (side === "SELL" && mode === "daily_close_proxy_sell") return `使用执行日收盘价代理卖出，价格 ${formatPrice(price)}。`;
  return `按 ${executionModeLabel(mode)} 执行，价格 ${formatPrice(price)}。`;
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
  const priceSource = getRawText(execution, "price_source");
  if (priceSource) rows.push({ label: "价格来源", value: priceSource });
  return rows;
}

function tradeMarkerEvidence(trade: BacktestTrade, execution: Record<string, unknown>): KlineMarker["evidence"] {
  const rows = auditMarkerEvidence({
    event_type: "trade",
    trade_date: trade.trade_date,
    vt_symbol: trade.vt_symbol,
    side: trade.side,
    status: "filled",
    reason: trade.reason,
    reason_label: trade.reason_label,
    price: trade.price,
    raw: trade.raw,
  });
  const entryDate = getRawText(execution, "entry_date");
  if (entryDate) rows?.unshift({ label: "买入日期", value: entryDate });
  return rows;
}

function markerExecutionRaw(trade: BacktestTrade) {
  const raw = safeRaw(trade.raw);
  return raw.execution && typeof raw.execution === "object" && !Array.isArray(raw.execution)
    ? raw.execution as Record<string, unknown>
    : raw;
}

function closedReturnQueues(trades: BacktestTrade[]): Map<string, number[]> {
  const openBuys: BacktestTrade[] = [];
  const queues = new Map<string, number[]>();
  const sorted = [...trades].sort((left, right) => {
    const dateCompare = String(left.trade_date).localeCompare(String(right.trade_date));
    if (dateCompare !== 0) return dateCompare;
    return (left.id ?? 0) - (right.id ?? 0);
  });
  for (const trade of sorted) {
    if (trade.side === "BUY") {
      openBuys.push(trade);
      continue;
    }
    if (trade.side !== "SELL") continue;
    const entry = openBuys.shift();
    if (!entry?.price || !trade.price) continue;
    const items = queues.get(trade.trade_date) ?? [];
    items.push((trade.price / entry.price - 1) * 100);
    queues.set(trade.trade_date, items);
  }
  return queues;
}

function nextReturnForSell(
  queues: Map<string, number[]>,
  trade: Pick<BacktestTrade, "side" | "trade_date"> | Pick<BacktestAuditEvent, "side" | "trade_date">
): number | null {
  if (trade.side !== "SELL") return null;
  return queues.get(trade.trade_date)?.shift() ?? null;
}

function sortMarkers(markers: KlineMarker[]): KlineMarker[] {
  return dedupeMarkers(markers).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function suppressResolvedSignals(markers: KlineMarker[]): KlineMarker[] {
  const resolvedSignalDates = new Set<string>();
  for (const marker of markers) {
    if (marker.markerKind !== "trade" && marker.markerKind !== "rejected") continue;
    if (String(marker.side).toUpperCase() !== "BUY") continue;
    const signalDate = marker.signalDate ?? getRawText(safeRaw(marker.raw), "signal_date") ?? getRawText(safeRaw(marker.raw), "reference_date");
    if (signalDate) resolvedSignalDates.add(signalDate);
  }
  return markers.filter((marker) => {
    if (marker.markerKind !== "signal") return true;
    const signalDate = marker.signalDate ?? marker.time;
    return !resolvedSignalDates.has(signalDate);
  });
}

function defaultSelectedMarker(markers: KlineMarker[]): KlineMarker | null {
  return markers.length ? markers[markers.length - 1] : null;
}

function markerScore(marker: KlineMarker) {
  return getRawNumber(safeRaw(marker.raw), "total_score") ?? getRawNumber(safeRaw(marker.raw), "score") ?? 0;
}

// 买入点时间线表格专用：卖出/平仓行不计入（其 raw 仅记录入场分数），其余行回放当时总分；取不到则返回 null 由表格显示 --。
function timelineMarkerScore(marker: KlineMarker): number | null {
  if (String(marker.side).toUpperCase() === "SELL") return null;
  const raw = safeRaw(marker.raw);
  return getRawNumber(raw, "total_score") ?? getRawNumber(raw, "score");
}

function markerReasonTextFromReason(reason?: string | null): string {
  if (reason === "tail_entry_not_triggered") return "执行价没有落在策略要求的 MA5 容忍范围内，因此 BUY 信号没有转成实际买入。";
  if (reason === "limit_up_open_blocked") return "执行日开盘涨停或接近涨停，保守判定买不到。";
  if (reason === "limit_up_tail_unfilled") return "执行日涨停或接近涨停，保守判定买不到。";
  if (reason === "limit_down_open_blocked") return "执行日开盘跌停或接近跌停，保守判定卖不出。";
  if (reason === "no_execute_bar") return "缺少执行日 K 线，无法判断可执行价格。";
  if (reason === "missing_1430_snapshot") return "实时分钟快照缺失，需等待数据补齐。历史日线研究不依赖该数据。";
  if (reason === "position_slot_unavailable") return "组合持仓名额已满，信号未转成实际买入。";
  if (reason === "insufficient_cash") return "组合可用资金不足，信号未转成实际买入。";
  return reason ? portfolioReasonLabel(reason) : "--";
}

function sumNumbers(values: Array<number | null | undefined>): number | null {
  const valid = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (!valid.length) return null;
  return valid.reduce((sum, value) => sum + value, 0);
}

function latestOpenReturnPct(
  row: BacktestTradeAttribution,
  positions: BacktestSymbolDetail["positions"]
): number | null {
  if (row.status !== "open" || !row.entry_date) return row.return_pct ?? null;
  const path = positions
    .filter((position) => position.vt_symbol === row.vt_symbol && position.entry_date === row.entry_date)
    .sort((a, b) => a.trade_date.localeCompare(b.trade_date));
  return path.length ? path[path.length - 1]?.floating_pnl_pct ?? null : row.max_floating_pnl_pct ?? null;
}

function maxMaybe(values: Array<number | null | undefined>): number | null {
  const valid = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  return valid.length ? Math.max(...valid) : null;
}

function minMaybe(values: Array<number | null | undefined>): number | null {
  const valid = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  return valid.length ? Math.min(...valid) : null;
}

function portfolioExecutionModeLabel(rows: NonNullable<BacktestSymbolDetail["trade_attribution"]>): string {
  const modes = Array.from(new Set(rows.map((row) => row.execution_mode).filter(Boolean)));
  if (!modes.length) return "--";
  return modes.map((mode) => executionModeLabel(mode)).join(" / ");
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

function marketLineTextClass(state?: string | null) {
  if (state === "bull") return "text-rise";
  if (state === "bear") return "text-fall";
  if (state === "warming") return "text-amber-700 dark:text-amber-300";
  return undefined;
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

function evidenceStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function scoreBreakdownRows(value: unknown): Array<{ name: string; score: string; weight: string; contribution: string }> {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const raw = item as Record<string, unknown>;
    const name = String(raw.name ?? "");
    if (!name) return [];
    const score = numericValue(raw.score);
    const weight = numericValue(raw.weight);
    const contribution = numericValue(raw.contribution);
    return [{
      name,
      score: score == null ? "--" : formatNumber(score, 1),
      weight: weight == null ? "--" : `${formatNumber(weight * 100, 0)}%`,
      contribution: contribution == null ? "--" : formatNumber(contribution, 2),
    }];
  });
}

function numericValue(value: unknown): number | null {
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
  if (reason === "support_stop") return "支撑止损";
  if (reason === "trend_break") return "趋势破位";
  if (reason === "trend_trailing_stop") return "趋势回撤";
  if (reason === "profit_protection_stop") return "浮盈保护";
  if (reason === "dynamic_failed_launch_exit_stop") return "动态失败启动撤退";
  if (reason === "dynamic_failed_launch_replacement_quality_gate") return "动态失败启动后替换闸门";
  if (reason === "low_suction_failed_follow_branch_stop") return "低吸没拉起撤";
  if (reason === "low_suction_opened_space_giveback_stop") return "低吸回撤卖";
  if (reason === "low_suction_branch_replacement_quality_gate") return "低吸替换质量闸门";
  if (reason === "rotation_for_stronger_signal") return "轮动换强";
  if (reason === "time_efficiency_stop") return "时间效率";
  if (reason === "mid_profit_giveback_stop") return "中段浮盈回撤";
  return reason || "--";
}

function strategyFailedRuleLabel(rule?: string | null) {
  const labels: Record<string, string> = {
    total_score: "分数不足",
    strong_leg: "第一波强度不足",
    pullback_structure: "回踩结构不足",
    pullback_too_short: "回踩时间不足",
    pullback_too_late: "回踩时间过长",
    support_acceptance: "均线承接不足",
    reclaim_confirmation: "弱转强确认不足",
    low_suction_buildup: "低吸蓄势不足",
    ma_convergence_too_wide_without_low_suction: "均线发散且缺少低吸蓄势",
    weak_rebound_ma5_below_ma10: "MA5下穿MA10弱反抽",
    distribution_risk: "高位派发风险",
    weekly_top_fractal_risk: "周线顶分型风险",
    spiky_churn_risk: "毛刺剧烈震荡风险",
    volume_stall_risk: "高位放量滞涨",
    key_support_break_risk: "关键支撑破位",
    illiquid_forgotten_risk: "成交极度萎靡",
    high_position_volume_stall_risk: "高位量能滞涨",
    high_level_sideways_distribution_risk: "高位久横派发风险",
    pullback_too_deep: "回撤过深",
    ma20_broken: "跌破MA20支撑",
    overheat: "短期过热",
    risk_score: "风险分不足",
    liquidity_score: "流动性不足",
  };
  return rule ? labels[rule] ?? portfolioReasonLabel(rule) : "--";
}

function strategyDragonStateLabel(state?: string | null) {
  const labels: Record<string, string> = {
    TAIL_BUY_READY: "龙回头买点",
    LOW_SUCTION_BUILDUP: "低吸蓄势",
    SUPPORT_ACCEPTED: "均线承接",
    PULLBACK_OBSERVE: "回踩观察",
    STRONG_LEG_CONFIRMED: "强势确认",
    DISTRIBUTION_RISK: "派发风险",
    INVALIDATED: "破位失效",
  };
  return state ? labels[state] ?? state : "--";
}

function strategySupportTypeLabel(support?: string | null) {
  const labels: Record<string, string> = {
    ma5_reclaim: "MA5承接",
    ma10_support: "MA10承接",
    ma20_support: "MA20承接",
    none: "未承接",
  };
  return support ? labels[support] ?? support : "--";
}

function readableStrategyScoreNote(note: string) {
  if (note.startsWith("状态 ")) return `状态 ${strategyDragonStateLabel(note.slice(3))}`;
  if (note.startsWith("承接 ")) return `承接 ${strategySupportTypeLabel(note.slice(3))}`;
  return note;
}

function InfoCell({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 font-medium tabular-nums", valueClass)}>{value ?? "--"}</div>
    </div>
  );
}

function portfolioReasonLabel(reason?: string | null) {
  const labels: Record<string, string> = {
    entry_signal: "入场信号",
    missing_1430_snapshot: "缺分钟快照",
    tail_entry_not_triggered: "入场条件未触发",
    limit_up_open_blocked: "开盘涨停买不到",
    limit_up_tail_unfilled: "涨停买不到",
    limit_down_open_blocked: "开盘跌停卖不出",
    limit_down_tail_blocked: "跌停卖不出",
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
  if (mode === "minute_1430") return "实时分钟";
  if (mode === "daily_close_proxy") return "收盘代理";
  if (mode === "minute_1430_sell") return "实时分钟卖出";
  if (mode === "daily_close_proxy_sell") return "收盘代理卖出";
  if (mode === "strict_1430_required") return "严格分钟";
  if (mode === "strict_1430_required_sell") return "严格分钟卖出";
  if (mode === "limit_up_tail_unfilled") return "涨停未买";
  if (mode === "limit_down_tail_blocked") return "跌停未卖";
  if (mode === "limit_down_open_blocked") return "开盘跌停未卖";
  if (mode === "minute_tail_ma5") return "实时分钟";
  if (mode === "daily_next_open_fallback") return "开盘回退";
  if (mode === "minute_tail_ma5_required") return "严格分钟";
  if (mode === "daily_next_open") return "次日开盘";
  if (mode === "daily_next_open_sell") return "次日开盘卖出";
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
