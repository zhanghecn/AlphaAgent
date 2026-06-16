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
  fetchBacktestSignalEvents,
  fetchBacktestSymbolDetail,
  fetchBacktests,
  fetchLatestSymbolBacktest,
  fetchQuantStrategies,
  fetchLatestSymbolQuantState,
  type BacktestSignalEvent,
  type BacktestRun,
  type BacktestAudit,
  type BacktestAuditEvent,
  type BacktestOrderEvent,
  type BacktestSymbolDetail,
  type BacktestTrade,
  type QuantStrategyOption,
  type SymbolLatestQuantState,
  type SymbolStrategyReplay,
  type StrategyReplayEvent,
} from "@/api/quant";
import { StockQuoteHeader } from "@/features/stocks/StockQuoteHeader";
import { StockKlineChart, type KlineMarker } from "@/features/stocks/StockKlineChart";
import { StockIndicatorPanel } from "@/features/stocks/StockIndicatorPanel";
import { StockFinanceChart } from "@/features/stocks/StockFinanceChart";
import { DEFAULT_BACKTEST_PARAMS, DEFAULT_BACKTEST_START } from "@/features/quant/constants";
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
  const latestReplay = latestQuantStateToReplay(latestQuantStateQuery.data);
  const quantProcessRangeKey = processDateRangeKey(latestQuantStateQuery.data);
  const hasGlobalExecutionMarkers = latestQuantStateQuery.data?.status === "ready"
    ? quantStateToMarkers(latestQuantStateQuery.data).some((marker) => marker.markerKind === "trade" || marker.markerKind === "rejected")
    : false;
  const latestPortfolioBacktestQuery = useQuery({
    queryKey: ["backtests", "portfolio", singleBacktestStrategy],
    queryFn: () => fetchBacktests(1, "portfolio", singleBacktestStrategy),
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
  const portfolioSignalEventsQuery = useQuery({
    queryKey: ["portfolioBacktestSignalEvents", latestPortfolioBacktestId, vtSymbol],
    queryFn: () => fetchBacktestSignalEvents(Number(latestPortfolioBacktestId), { vt_symbol: vtSymbol!, limit: 2000 }),
    enabled: Boolean(vtSymbol && latestPortfolioBacktestId),
    staleTime: 60_000,
  });
  const hasPortfolioSymbolExecutions = (portfolioSymbolDetailQuery.data?.trades?.length ?? 0) > 0
    || (portfolioSymbolDetailQuery.data?.orders?.length ?? 0) > 0;
  const latestSymbolBacktestQuery = useQuery({
    queryKey: ["symbolLatestBacktest", vtSymbol, singleBacktestStrategy],
    queryFn: () => fetchLatestSymbolBacktest(vtSymbol!, singleBacktestStrategy),
    enabled: Boolean(vtSymbol && !hasPortfolioSymbolExecutions && !hasGlobalExecutionMarkers),
    staleTime: 5 * 60_000,
  });
  const latestSymbolBacktestId =
    latestSymbolBacktestQuery.data?.status === "ready" ? latestSymbolBacktestQuery.data.backtest_id : undefined;
  const latestSymbolAuditQuery = useQuery({
    queryKey: ["symbolLatestBacktestAudit", latestSymbolBacktestId, vtSymbol],
    queryFn: () => fetchBacktestAudit(Number(latestSymbolBacktestId), vtSymbol!, 500),
    enabled: Boolean(vtSymbol && latestSymbolBacktestId && !hasPortfolioSymbolExecutions && !hasGlobalExecutionMarkers),
    staleTime: 5 * 60_000,
  });
  const autoCreateReviewQuery = useQuery({
    queryKey: ["symbolAutoCreateReview", vtSymbol, singleBacktestStrategy, quantProcessRangeKey],
    queryFn: () =>
      createSymbolBacktest({
        vt_symbol: vtSymbol!,
        strategy: singleBacktestStrategy,
        start: DEFAULT_BACKTEST_START,
        end: latestQuantStateQuery.data?.process?.latest_available_trade_date ?? latestQuantStateQuery.data?.process?.end_date ?? undefined,
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
      && !portfolioSymbolDetailQuery.isLoading
      && !portfolioSymbolDetailQuery.isFetching
      && !latestSymbolBacktestQuery.isLoading
      && !latestSymbolBacktestQuery.isFetching
      && !hasPortfolioSymbolExecutions
      && !hasGlobalExecutionMarkers
      && latestSymbolBacktestQuery.data?.status === "empty"
    ),
    staleTime: 5 * 60_000,
    retry: 1,
  });
  const autoReviewAudit = latestSymbolAuditQuery.data ?? autoCreateReviewQuery.data?.audit;
  const autoReviewTrades =
    autoReviewAudit?.trades
    ?? latestSymbolBacktestQuery.data?.trades
    ?? autoCreateReviewQuery.data?.trades
    ?? [];
  const portfolioDetailMarkers = useMemo(
    () => backtestSymbolDetailToMarkers(portfolioSymbolDetailQuery.data),
    [portfolioSymbolDetailQuery.data]
  );
  const portfolioSignalMarkers = useMemo(
    () => backtestSignalEventsToMarkers(portfolioSignalEventsQuery.data?.items ?? []),
    [portfolioSignalEventsQuery.data]
  );

  const backtestMarkers = useMemo(
    () => {
      if (portfolioDetailMarkers.some((marker) => marker.markerKind === "trade" || marker.markerKind === "rejected")) {
        return mergeMarkerSets(portfolioDetailMarkers, portfolioSignalMarkers);
      }
      const quantMarkers = latestQuantStateQuery.data?.status === "ready"
        ? quantStateToMarkers(latestQuantStateQuery.data)
        : latestReplay
          ? replayEventsToMarkers(latestReplay)
          : [];
      const autoReviewMarkers = backtestAuditToMarkers(autoReviewTrades, autoReviewAudit);
      return mergeMarkerSets(mergeMarkerSets(portfolioDetailMarkers, portfolioSignalMarkers), mergeMarkerSets(prioritizeExecutionMarkers(quantMarkers), autoReviewMarkers));
    },
    [autoReviewAudit, autoReviewTrades, latestQuantStateQuery.data, latestReplay, portfolioDetailMarkers, portfolioSignalMarkers]
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
        isAutoReviewLoading={
          latestSymbolBacktestQuery.isLoading
          || latestSymbolBacktestQuery.isFetching
          || latestSymbolAuditQuery.isLoading
          || latestSymbolAuditQuery.isFetching
          || autoCreateReviewQuery.isLoading
          || autoCreateReviewQuery.isFetching
        }
        autoReviewError={latestSymbolBacktestQuery.error ?? latestSymbolAuditQuery.error ?? autoCreateReviewQuery.error}
        autoReviewAudit={autoReviewAudit}
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
}) {
  const replay = latestQuantStateToReplay(quantState);
  const replayClosedTrades = replay?.closed_trades ?? [];
  const replaySummary = replay?.summary;
  const tradePlan = quantState?.candidate?.trade_plan;
  const candidate = quantState?.candidate?.item;
  const latestSignal = quantState?.signal?.latest_entry_signal ?? quantState?.signal?.latest;
  const hasPortfolioExecutions = (portfolioDetail?.trades?.length ?? 0) > 0
    || (portfolioDetail?.orders?.length ?? 0) > 0
    || (portfolioDetail?.trade_attribution?.length ?? 0) > 0;
  const sourceMode: "portfolio" | "global" = hasPortfolioExecutions ? "portfolio" : "global";

  return (
    <section className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <BarChart3 size={15} />
            策略复盘
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            优先读取最新组合回测的实际买卖；若组合没有该票成交，再退回全局信号记录。BUY 信号不等于实际购买。
          </p>
        </div>
        <div className="text-sm">
          <div className="text-xs text-muted-foreground">策略</div>
          <div className="mt-1 flex h-9 items-center rounded-md border bg-muted/30 px-2">
            {strategies.find((item) => item.id === strategy)?.name ?? "主线龙回头回踩低吸"}
          </div>
        </div>
      </div>

      {isQuantStateLoading ? (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          正在读取最近量化过程...
        </div>
      ) : quantStateError ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {quantStateError instanceof Error ? quantStateError.message : "读取最近量化过程失败"}
        </div>
      ) : sourceMode === "portfolio" ? (
        <PortfolioBacktestSymbolSummary
          backtest={portfolioBacktest}
          detail={portfolioDetail}
          markerCount={markerCount}
          isLoading={isPortfolioDetailLoading}
          error={portfolioDetailError}
          strategyName={strategies.find((item) => item.id === strategy)?.name ?? "主线龙回头回踩低吸"}
        />
      ) : quantState?.status === "ready" ? (
        <div className="mt-4 space-y-4">
          <div className="rounded-md border bg-muted/20 p-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck size={14} />
                最近量化过程
              </div>
              <Badge variant={stateBadgeVariant(quantState.state?.severity)} className="rounded-md">
                {quantState.state?.label ?? "--"}
              </Badge>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-5">
              <InfoCell label="日期范围" value={processDateRange(quantState)} />
              <InfoCell label="过程来源" value={quantProcessSourceLabel(quantState.process?.source)} />
              <InfoCell label="过程ID" value={quantState.process?.replay_run_id ?? quantState.process?.screen_run_id ?? "--"} />
              <InfoCell label="评分日期" value={`${quantState.signal?.scored_date_count ?? 0} 天`} />
              <InfoCell label="BUY信号" value={`${quantState.signal?.entry_signal_count ?? 0} 次`} valueClass={(quantState.signal?.entry_signal_count ?? 0) > 0 ? "text-rise" : undefined} />
            </div>
            <p className="mt-3 text-xs text-muted-foreground">{quantState.message}</p>
            {isAutoReviewLoading ? (
              <p className="mt-2 text-xs text-muted-foreground">正在自动准备该策略的历史买卖点...</p>
            ) : autoReviewAudit ? (
              <p className="mt-2 text-xs text-muted-foreground">
                K 线已补充该策略单股复盘买卖点：{autoReviewAudit.start_date} 至 {autoReviewAudit.end_date}。
              </p>
            ) : autoReviewError ? (
              <p className="mt-2 text-xs text-fall">
                自动准备买卖点失败：{autoReviewError instanceof Error ? autoReviewError.message : "请稍后刷新重试"}。
              </p>
            ) : null}
          </div>

          <div className="grid gap-3 text-sm md:grid-cols-4">
            <InfoCell label="最近信号日" value={latestSignal?.trade_date ?? "--"} />
            <InfoCell label="信号类型" value={latestSignal?.entry_signal ? "BUY" : latestSignal ? "WATCH/评分" : "--"} valueClass={latestSignal?.entry_signal ? "text-rise" : undefined} />
            <InfoCell label="评分" value={formatMaybeNumber(latestSignal?.total_score, 1)} />
            <InfoCell label="候选" value={candidate ? `${candidate.action ?? "--"} #${candidate.rank ?? "--"}` : "未进入候选"} />
          </div>

          {tradePlan && (
            <div className="rounded-md border p-3 text-sm">
              <div className="flex items-center gap-2 font-medium">
                <ShieldCheck size={14} />
                候选买卖计划
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-4">
                <InfoCell label="买入价" value={formatPrice(tradePlan.entry_price)} />
                <InfoCell label="止损价" value={formatPrice(tradePlan.stop_loss_price)} valueClass="text-fall" />
                <InfoCell label="止盈价" value={formatPrice(tradePlan.take_profit_price)} valueClass="text-rise" />
                <InfoCell label="信号日" value={tradePlan.entry_date ?? candidate?.trade_date ?? "--"} />
              </div>
            </div>
          )}

          {replay ? (
            <div className="space-y-4">
              <div className="grid gap-3 text-sm md:grid-cols-6">
                <InfoCell label="买卖记录ID" value={replay.replay_run_id ?? "--"} />
                <InfoCell label="执行状态" value={replayStatusLabel(quantState.replay?.status)} />
                <InfoCell label="买入成交" value={`${replaySummary?.buy_filled_count ?? 0} 次`} valueClass={(replaySummary?.buy_filled_count ?? 0) > 0 ? "text-rise" : undefined} />
                <InfoCell label="拒绝" value={`${replaySummary?.rejected_count ?? 0} 次`} valueClass={(replaySummary?.rejected_count ?? 0) > 0 ? "text-fall" : undefined} />
                <InfoCell label="闭合交易" value={`${replaySummary?.closed_trade_count ?? 0} 笔`} />
                <InfoCell label="持仓状态" value={strategyStatusLabel(replaySummary?.current_status)} />
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
                  本轮未形成闭合交易。若状态显示有 BUY 信号或买入拒绝，可点击 K 线标记查看当天信号和执行原因。
                </div>
              )}
            </div>
          ) : (
            <div className="rounded-md border p-3 text-sm text-muted-foreground">
              当前已有筛选评分，但尚未生成统一买卖记录。请在量化页运行策略研究，系统会自动生成全局候选和组合回测，避免单股临时回测和全局口径不一致。
            </div>
          )}
        </div>
      ) : (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          {quantState?.message ?? "暂无全局量化过程。请先在量化页运行策略研究。"}
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
}: {
  backtest?: BacktestRun | null;
  detail?: BacktestSymbolDetail | null;
  markerCount: number;
  isLoading: boolean;
  error: unknown;
  strategyName: string;
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
  const totalReturnPct = sumNumbers(closedRows.map((row) => row.return_pct));
  const averageReturnPct = closedRows.length && totalReturnPct != null ? totalReturnPct / closedRows.length : null;
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
            最新组合回测
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
          本页收益、闭合交易和 K 线买卖标记均来自同一个组合回测口径，已过滤全局 replay 中重复的持仓期 BUY 信号。
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

      <div className="grid gap-3 text-sm md:grid-cols-4">
        <InfoCell label="累计收益率" value={formatPct(totalReturnPct)} valueClass={priceColorClass(totalReturnPct)} />
        <InfoCell label="平均单笔" value={formatPct(averageReturnPct)} valueClass={priceColorClass(averageReturnPct)} />
        <InfoCell label="胜率" value={formatPct(winRatePct)} />
        <InfoCell label="最大浮盈/浮亏" value={`${formatPct(maxFloatingPct)} / ${formatPct(minFloatingPct)}`} valueClass={priceColorClass(maxFloatingPct)} />
      </div>

      {closedRows.length || openRows.length ? (
        <PortfolioClosedTradeTable rows={attributionRows} />
      ) : (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">
          最新组合回测中该股票没有形成实际买卖。若 K 线只有信号或拒绝标记，可点击标记查看原因。
        </div>
      )}
    </div>
  );
}

function PortfolioClosedTradeTable({ rows }: { rows: NonNullable<BacktestSymbolDetail["trade_attribution"]> }) {
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
          {rows.map((row, index) => (
            <TableRow key={`${row.vt_symbol}-${row.entry_date}-${row.exit_date ?? "open"}-${index}`}>
              <TableCell className="tabular-nums">{row.entry_date ?? "--"}</TableCell>
              <TableCell className="tabular-nums">{row.exit_date ?? (row.status === "open" ? "持有中" : "--")}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.entry_price)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPrice(row.exit_price)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.max_floating_pnl_pct))}>
                {formatPct(row.max_floating_pnl_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.min_floating_pnl_pct))}>
                {formatPct(row.min_floating_pnl_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.holding_days ?? "--"}</TableCell>
              <TableCell className="text-muted-foreground">{exitReasonLabel(row.exit_reason)}</TableCell>
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

type LatestQuantSignalRow = NonNullable<NonNullable<SymbolLatestQuantState["signal"]>["latest_entry_signal"]>;

function strategyMinEntryScore(strategies: QuantStrategyOption[], strategyId: string) {
  return strategies.find((item) => item.id === strategyId)?.default_min_entry_score ?? DEFAULT_BACKTEST_PARAMS.min_entry_score;
}

function processDateRangeKey(state?: SymbolLatestQuantState) {
  const start = state?.process?.start_date ?? DEFAULT_BACKTEST_START;
  const end = state?.process?.end_date ?? "latest";
  return `${start}:${end}`;
}

function processDateRange(state: SymbolLatestQuantState) {
  const start = state.process?.start_date;
  const end = state.process?.end_date;
  if (start && end && start !== end) return `${start} 至 ${end}`;
  return start ?? end ?? "--";
}

function quantProcessSourceLabel(source?: string) {
  if (source === "replay") return "全局买卖记录";
  if (source === "screen") return "候选筛选";
  return source || "--";
}

function replayStatusLabel(status?: string) {
  if (status === "ready") return "有执行记录";
  if (status === "no_attempts") return "无执行尝试";
  if (status === "not_generated") return "未生成买卖记录";
  return status || "--";
}

function stateBadgeVariant(severity?: string): "default" | "secondary" | "destructive" | "outline" | "brand" {
  if (severity === "success") return "secondary";
  if (severity === "warning") return "outline";
  return "outline";
}

function formatMaybeNumber(value?: number | null, digits = 2) {
  return value == null ? "--" : formatNumber(value, digits);
}

function latestQuantStateToReplay(state?: SymbolLatestQuantState): SymbolStrategyReplay | null {
  if (state?.status !== "ready" || !state.replay || state.replay.status === "not_generated") return null;
  return {
    status: state.replay.status === "ready" ? "ready" : "empty",
    message: state.message ?? null,
    replay_run_id: state.replay.replay_run_id ?? undefined,
    vt_symbol: state.vt_symbol,
    name: state.name,
    strategy_id: state.strategy_id,
    strategy_version: state.strategy_version,
    start_date: state.process?.start_date ?? null,
    end_date: state.process?.end_date ?? null,
    params: state.process?.params ?? {},
    summary: state.replay.summary ?? undefined,
    attempts: state.replay.attempts ?? [],
    events: state.replay.events ?? [],
    closed_trades: state.replay.closed_trades ?? [],
  };
}

function quantStateToMarkers(state: SymbolLatestQuantState): KlineMarker[] {
  const replay = latestQuantStateToReplay(state);
  const markers = replay ? replayEventsToMarkers(replay) : [];
  const signal = state.signal?.latest_entry_signal;
  const hasExecutionMarker = markers.some((marker) => marker.markerKind === "trade" || marker.markerKind === "rejected");
  if (!hasExecutionMarker && signal?.trade_date && !markers.some((marker) => marker.markerKind === "signal" && marker.signalDate === signal.trade_date)) {
    markers.push(quantSignalToMarker(signal, markers.length));
  }
  return dedupeMarkers(markers).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function quantSignalToMarker(signal: LatestQuantSignalRow, index: number): KlineMarker {
  const evidence = safeRaw(signal.evidence);
  const signalDate = signal.trade_date ?? "";
  return {
    id: `quant-signal-${signal.vt_symbol ?? ""}-${signalDate}-${index}`,
    time: signalDate,
    tradeDate: signalDate,
    signalDate,
    side: "BUY",
    markerKind: "signal",
    status: "signal",
    price: null,
    title: "BUY 信号",
    strategy: quantSignalText(signal, evidence),
    signalText: quantSignalText(signal, evidence),
    executionText: "本轮最新量化过程记录了 BUY 信号；是否实际购买以候选和买卖记录为准。",
    reasonText: "BUY 信号是收盘后策略判断，不等于实际成交。",
    evidence: quantSignalEvidence(signal, evidence),
    raw: evidence,
    text: "信号",
  };
}

function quantSignalText(signal: LatestQuantSignalRow, evidence: Record<string, unknown>) {
  const score = signal.total_score ?? getRawNumber(evidence, "total_score");
  const ma5Distance = getRawNumber(evidence, "ma5_distance_pct");
  const closePrice = getRawNumber(evidence, "close_price");
  const parts = [
    `${signal.trade_date ?? "信号日"} 收盘后生成 BUY 信号`,
    score == null ? "" : `总分 ${formatNumber(score, 1)}`,
    closePrice == null ? "" : `收盘价 ${formatPrice(closePrice)}`,
    ma5Distance == null ? "" : `距MA5 ${formatPct(ma5Distance)}`,
  ].filter(Boolean);
  return parts.join("；");
}

function quantSignalEvidence(
  signal: LatestQuantSignalRow,
  evidence: Record<string, unknown>
): KlineMarker["evidence"] {
  const rows: Array<{ label: string; value: string; valueClass?: string }> = [];
  if (signal.trade_date) rows.push({ label: "信号日", value: signal.trade_date });
  pushNumberEvidence(rows, "评分", signal.total_score, 1);
  pushNumberEvidence(rows, "流动性", signal.liquidity_score, 1);
  pushNumberEvidence(rows, "风险分", signal.risk_score, 1);
  pushPriceEvidence(rows, "收盘价", getRawNumber(evidence, "close_price"));
  pushPriceEvidence(rows, "MA5", getRawNumber(evidence, "ma5"));
  pushPctEvidence(rows, "距MA5", getRawNumber(evidence, "ma5_distance_pct"));
  return rows;
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
  const isSignal = event.event_type === "signal" || event.status === "signal" || event.status === "signal_only";
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
  if (event.status === "signal" || event.status === "signal_only") return "BUY 信号";
  if (event.status === "rejected") return `${event.side === "SELL" ? "卖出" : "买入"}拒绝：${reasonLabel}`;
  if (event.side === "BUY") return "买入成交";
  if (event.side === "SELL") return `卖出成交：${reasonLabel}`;
  return event.status;
}

function replayMarkerText(event: StrategyReplayEvent) {
  if (event.status === "signal" || event.status === "signal_only") return "信号";
  if (event.status === "rejected") return event.side === "SELL" ? "卖拒" : "买拒";
  return event.side === "SELL" ? "卖" : "买";
}

function replayMarkerStrategyText(event: StrategyReplayEvent, evidence: Record<string, unknown>, reasonLabel: string) {
  if (event.status === "signal" || event.status === "signal_only") return replaySignalText(event, evidence);
  if (event.status === "rejected") return `${event.execute_date ?? event.trade_date} 执行未成交：${reasonLabel}。`;
  return `${event.execute_date ?? event.trade_date} 按统一买卖记录成交，价格来源 ${event.price_source ?? "--"}。`;
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
  if (event.status === "signal" || event.status === "signal_only") return `计划执行日 ${event.execute_date ?? "--"}；${event.reason === "already_holding" ? "当时已持仓，不重复买入。" : "实际是否成交以执行规则为准。"}`;
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
    : trades.map((trade, index) => tradeToExecutionMarker(trade, index, nextReturnForSell(returnQueues, trade)));
  return dedupeMarkers(markers).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function backtestSymbolDetailToMarkers(detail?: BacktestSymbolDetail | null): KlineMarker[] {
  const trades = detail?.trades ?? [];
  const orders = detail?.orders ?? [];
  if (!trades.length && !orders.length) return [];
  const returnQueues = closedReturnQueues(trades);
  const events: BacktestAuditEvent[] = [
    ...orders.map(orderToAuditEvent),
    ...trades.map((trade) => ({ ...trade, event_type: "trade", status: "filled" })),
  ].sort((left, right) => {
    const dateCompare = String(left.trade_date).localeCompare(String(right.trade_date));
    if (dateCompare !== 0) return dateCompare;
    return auditEventSortRank(left) - auditEventSortRank(right);
  });
  const markers = events.flatMap((event, index) => auditEventToMarkers(event, index, returnQueues));
  return dedupeMarkers(markers).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function backtestSignalEventsToMarkers(events: BacktestSignalEvent[]): KlineMarker[] {
  return dedupeMarkers(
    events
      .filter((event) => event.side === "BUY" || event.side === "SELL")
      .map((event, index) => backtestSignalEventToMarker(event, index))
  ).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function backtestSignalEventToMarker(event: BacktestSignalEvent, index: number): KlineMarker {
  const raw = safeRaw(event.raw);
  const evidence = raw.evidence && typeof raw.evidence === "object" && !Array.isArray(raw.evidence)
    ? raw.evidence as Record<string, unknown>
    : raw;
  const isBuy = event.side === "BUY";
  const status = event.linked_order_status === "filled" ? "filled" : event.plan_status ?? "planned";
  return {
    id: `portfolio-signal-${event.backtest_id ?? ""}-${event.vt_symbol}-${event.signal_date}-${event.side}-${index}`,
    time: event.signal_date ?? event.trade_date,
    tradeDate: event.trade_date,
    signalDate: event.signal_date,
    executeDate: event.execute_date,
    side: event.side,
    markerKind: "signal",
    status: "signal",
    reason: event.reason,
    reasonLabel: event.reason_label ?? portfolioReasonLabel(event.reason),
    price: null,
    executionMode: getRawText(raw, "mode") ?? getRawText(raw, "execution_model"),
    title: isBuy ? "BUY 信号" : `SELL 信号：${event.reason_label ?? portfolioReasonLabel(event.reason)}`,
    strategy: isBuy ? portfolioSignalText(event, evidence) : `${event.signal_date} 收盘后触发 ${event.reason_label ?? portfolioReasonLabel(event.reason)}。`,
    signalText: isBuy ? portfolioSignalText(event, evidence) : `${event.signal_date} 收盘后触发 ${event.reason_label ?? portfolioReasonLabel(event.reason)}。`,
    executionText: portfolioSignalExecutionText(event, status),
    reasonText: isBuy
      ? "同一组合回测里的理论 BUY 计划；是否实际买入还取决于排名、持仓、资金和执行规则。"
      : markerReasonTextFromReason(event.reason),
    evidence: portfolioSignalEvidence(event, evidence),
    raw: event.raw,
    text: isBuy ? "信号" : "卖信",
  };
}

function portfolioSignalText(event: BacktestSignalEvent, evidence: Record<string, unknown>) {
  const score = event.score ?? getRawNumber(evidence, "total_score");
  const ma5Distance = getRawNumber(evidence, "ma5_distance_pct");
  const closePrice = getRawNumber(evidence, "close_price");
  const parts = [
    `${event.signal_date} 收盘后生成 BUY 信号`,
    score == null ? "" : `总分 ${formatNumber(score, 1)}`,
    closePrice == null ? "" : `收盘价 ${formatPrice(closePrice)}`,
    ma5Distance == null ? "" : `距MA5 ${formatPct(ma5Distance)}`,
  ].filter(Boolean);
  return parts.join("；");
}

function portfolioSignalExecutionText(event: BacktestSignalEvent, status: string) {
  if (event.linked_order_status) {
    return `执行日 ${event.execute_date}，关联订单状态 ${event.linked_order_status}。`;
  }
  if (status === "planned") {
    return `理论计划执行日 ${event.execute_date}；组合未必实际成交，请以买入成交/买拒标记为准。`;
  }
  return `${event.plan_status_label ?? status}，执行日 ${event.execute_date}。`;
}

function portfolioSignalEvidence(event: BacktestSignalEvent, evidence: Record<string, unknown>): KlineMarker["evidence"] {
  const rows: Array<{ label: string; value: string; valueClass?: string }> = [];
  rows.push({ label: "信号日", value: event.signal_date });
  rows.push({ label: "执行日", value: event.execute_date });
  if (event.reason_label || event.reason) rows.push({ label: "原因", value: event.reason_label ?? portfolioReasonLabel(event.reason) });
  if (event.plan_status_label || event.plan_status) rows.push({ label: "计划状态", value: event.plan_status_label ?? event.plan_status ?? "--" });
  pushNumberEvidence(rows, "评分", event.score, 1);
  pushPriceEvidence(rows, "理论价", event.price);
  pushPriceEvidence(rows, "MA5", getRawNumber(evidence, "ma5"));
  pushPctEvidence(rows, "距MA5", getRawNumber(evidence, "ma5_distance_pct"));
  if (event.linked_order_status) rows.push({ label: "订单状态", value: event.linked_order_status });
  if (event.linked_order_reason_label || event.linked_order_reason) rows.push({ label: "订单原因", value: event.linked_order_reason_label ?? portfolioReasonLabel(event.linked_order_reason) });
  return rows;
}

function orderToAuditEvent(order: BacktestOrderEvent): BacktestAuditEvent {
  return {
    ...order,
    event_type: "order",
    message: undefined,
    execution_mode: undefined,
  };
}

function auditEventSortRank(event: BacktestAuditEvent) {
  if (event.event_type === "order" && event.status === "rejected") return 1;
  if (event.event_type === "trade" && event.side === "BUY") return 2;
  if (event.event_type === "trade" && event.side === "SELL") return 3;
  return 4;
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

function mergeMarkerSets(primary: KlineMarker[], fallback: KlineMarker[]): KlineMarker[] {
  const primaryHasExecutions = primary.some((marker) => marker.markerKind === "trade" || marker.markerKind === "rejected");
  const fallbackHasExecutions = fallback.some((marker) => marker.markerKind === "trade" || marker.markerKind === "rejected");
  const merged = fallbackHasExecutions && !primaryHasExecutions ? [...fallback, ...primary] : [...primary, ...fallback];
  return dedupeMarkers(merged).sort((left, right) => {
    const dateCompare = left.time.localeCompare(right.time);
    if (dateCompare !== 0) return dateCompare;
    return markerSortRank(left) - markerSortRank(right);
  });
}

function prioritizeExecutionMarkers(markers: KlineMarker[]): KlineMarker[] {
  const hasExecutionMarker = markers.some((marker) => marker.markerKind === "trade" || marker.markerKind === "rejected");
  if (!hasExecutionMarker) return markers.slice(-6);
  return markers.filter((marker) => marker.markerKind !== "signal");
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
