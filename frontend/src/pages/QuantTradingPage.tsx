import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addPortfolioGroupItem,
  createQuantResearchRun,
  fetchBacktestAudit,
  fetchBacktestDataQuality,
  fetchBacktestReport,
  fetchBacktestValidationGrid,
  fetchBacktests,
  fetchHoldings,
  fetchLatestQuantResearchRun,
  fetchPortfolioGroupItems,
  fetchPortfolioGroups,
  fetchQuantStrategies,
  fetchRecommendations,
  fetchScreenRuns,
  fetchSimulationAccounts,
  fetchTradingDates,
  fetchVnpyStatus,
  placeOrder,
  type QuantRecommendation,
  type QuantResearchRun,
} from "@/api/quant";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DEFAULT_BACKTEST_PARAMS, type BacktestParams } from "@/features/quant/constants";
import { ActionStatus } from "@/features/quant/ActionStatus";
import { ScreenProgress } from "@/features/quant/ScreenProgress";
import { QuantWorkflowGuide } from "@/features/quant/QuantWorkflowGuide";
import { QuantKpiBar, type QuantKpi } from "@/features/quant/QuantKpiBar";
import { VnpyStatusPanel } from "@/features/quant/VnpyStatusPanel";
import { RecommendationsPanel } from "@/features/quant/RecommendationsPanel";
import { BacktestPanel } from "@/features/quant/BacktestPanel";
import { BacktestLogWorkspace } from "@/features/quant/BacktestLogWorkspace";
import { BacktestDataQuality } from "@/features/quant/BacktestAnalysis";
import { AddToGroupDialog } from "@/features/portfolio/AddToGroupDialog";
import { ManualBuyDialog } from "@/features/quant/ManualBuyDialog";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";

export function QuantTradingPage() {
  const queryClient = useQueryClient();
  const [selectedBacktestId, setSelectedBacktestId] = useState<number | null>(null);
  const [backtestParams, setBacktestParams] = useState(DEFAULT_BACKTEST_PARAMS);
  const [addToGroupOpen, setAddToGroupOpen] = useState(false);
  const [addToGroupSymbol, setAddToGroupSymbol] = useState<string | null>(null);
  const [selectedRecommendationDate, setSelectedRecommendationDate] = useState("");
  const [handledResearchJobId, setHandledResearchJobId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("candidates");

  const updateBacktestParams = (next: BacktestParams) => setBacktestParams(next);
  const selectedStrategy = backtestParams.strategy;

  const strategiesQuery = useQuery({
    queryKey: ["quantStrategies"],
    queryFn: fetchQuantStrategies,
    staleTime: 60_000,
  });

  const latestResearchRunQuery = useQuery({
    queryKey: ["quantResearchRunLatest"],
    queryFn: fetchLatestQuantResearchRun,
    refetchInterval: (query) => (query.state.data?.status === "running" ? 2000 : false),
    staleTime: 1000,
  });
  const latestResearchRun = latestResearchRunQuery.data;
  const latestResearchRunning = researchIsRunning(latestResearchRun);

  const screenRunsQuery = useQuery({
    queryKey: ["quantScreenRuns", selectedStrategy],
    queryFn: () => fetchScreenRuns(160, selectedStrategy),
    staleTime: 30_000,
    // 批量生成时每 2s 轮询已 persist 的 run 数，驱动实时进度条
    refetchInterval: () => (latestResearchRunning ? 2000 : false),
  });

  const tradingDatesQuery = useQuery({
    queryKey: ["quantTradingDates"],
    queryFn: () => fetchTradingDates({ limit: 360 }),
    staleTime: 60_000,
  });

  const activeRecommendationDate =
    selectedRecommendationDate ||
    screenRunsQuery.data?.items[0]?.trade_date ||
    (!screenRunsQuery.isLoading ? tradingDatesQuery.data?.latest_trade_date : "") ||
    "";
  const latestScreenDate = screenRunsQuery.data?.items[0]?.trade_date ?? null;
  const latestTradeDate = tradingDatesQuery.data?.latest_trade_date ?? null;
  const earliestTradeDate = tradingDatesQuery.data?.earliest_trade_date ?? null;

  useEffect(() => {
    if (!earliestTradeDate) return;
    setBacktestParams((current) =>
      current.start === DEFAULT_BACKTEST_PARAMS.start
        ? { ...current, start: earliestTradeDate }
        : current
    );
  }, [earliestTradeDate]);

  const recommendationsQuery = useQuery({
    queryKey: ["quantRecommendations", activeRecommendationDate, selectedStrategy],
    queryFn: () => fetchRecommendations(200, activeRecommendationDate || undefined, selectedStrategy),
    enabled: Boolean(activeRecommendationDate),
    staleTime: 20_000,
  });

  const groupsQuery = useQuery({
    queryKey: ["portfolioGroups"],
    queryFn: fetchPortfolioGroups,
    staleTime: 60_000,
  });

  const quantGroupId = groupsQuery.data?.items.find((item) => item.group_type === "quant_candidate")?.id;
  const quantGroupItemsQuery = useQuery({
    queryKey: ["portfolioGroupItems", quantGroupId],
    queryFn: () => fetchPortfolioGroupItems(quantGroupId!),
    enabled: Boolean(quantGroupId),
    staleTime: 20_000,
  });

  const backtestsQuery = useQuery({
    queryKey: ["backtests", "portfolio", selectedStrategy],
    queryFn: () => fetchBacktests(50, "portfolio", selectedStrategy),
    staleTime: 20_000,
  });

  const backtestRuns = (backtestsQuery.data?.items ?? []).filter((run) => run.strategy_id === selectedStrategy);
  const selectedBacktest =
    selectedBacktestId == null ? null : backtestRuns.find((run) => run.id === selectedBacktestId) ?? null;
  const activeBacktestId = selectedBacktest?.id ?? backtestRuns[0]?.id ?? null;
  const shouldLoadBacktestReport = activeTab === "backtest" || activeTab === "data";
  const shouldLoadBacktestDataQuality = activeTab === "backtest";
  const shouldLoadBacktestAudit = activeTab === "backtest" || activeTab === "logs";
  const reportQuery = useQuery({
    queryKey: ["backtestReport", activeBacktestId],
    queryFn: () => fetchBacktestReport(activeBacktestId!, 80),
    enabled: Boolean(activeBacktestId && shouldLoadBacktestReport),
    staleTime: 20_000,
  });

  const dataQualityQuery = useQuery({
    queryKey: ["backtestDataQuality", activeBacktestId],
    queryFn: () => fetchBacktestDataQuality(activeBacktestId!),
    enabled: Boolean(activeBacktestId && shouldLoadBacktestDataQuality),
    staleTime: 20_000,
  });

  const auditQuery = useQuery({
    queryKey: ["backtestAudit", activeBacktestId],
    queryFn: () => fetchBacktestAudit(activeBacktestId!, undefined, 120),
    enabled: Boolean(activeBacktestId && shouldLoadBacktestAudit),
    staleTime: 20_000,
  });

  const validationGridQuery = useQuery({
    queryKey: ["backtestValidationGrid", activeBacktestId],
    queryFn: () => fetchBacktestValidationGrid(activeBacktestId!, 54),
    enabled: false,
    staleTime: 60_000,
  });

  const accountsQuery = useQuery({
    queryKey: ["simulationAccounts"],
    queryFn: fetchSimulationAccounts,
    staleTime: 20_000,
  });

  const holdingsQuery = useQuery({
    queryKey: ["portfolioHoldings"],
    queryFn: fetchHoldings,
    staleTime: 20_000,
  });

  const vnpyStatusQuery = useQuery({
    queryKey: ["vnpyStatus"],
    queryFn: fetchVnpyStatus,
    staleTime: 60_000,
  });

  const researchMutation = useMutation({
    mutationFn: () => {
      const minEntryScore = strategyMinEntryScore(strategiesQuery.data?.items ?? [], selectedStrategy, backtestParams.min_entry_score);
      return createQuantResearchRun({
        start: backtestParams.start || earliestTradeDate || undefined,
        end: tradingDatesQuery.data?.latest_trade_date ?? undefined,
        strategy: selectedStrategy,
        max_symbols: backtestParams.max_symbols,
        recommendation_limit: backtestParams.candidate_limit,
        min_recommendation_score: 60,
        min_entry_score: minEntryScore,
        persist: true,
        auto_portfolio: true,
        included_boards: backtestParams.included_boards,
        initial_cash: backtestParams.initial_cash,
        max_positions: 10,
        candidate_limit: 10,
        max_position_pct: 0.1,
        strict_entry: true,
        execution_model: "legacy_next_open",
        force_refresh: true,
      });
    },
    onSuccess: (result) => {
      queryClient.setQueryData(["quantResearchRunLatest"], result);
      queryClient.invalidateQueries({ queryKey: ["quantResearchRunLatest"] });
    },
  });
  const isResearchRunning = researchMutation.isPending || latestResearchRunning;

  useEffect(() => {
    if (!latestResearchRun || latestResearchRun.status === "running" || latestResearchRun.id === handledResearchJobId) {
      return;
    }
    setHandledResearchJobId(latestResearchRun.id);
    if (latestResearchRun.status !== "succeeded") {
      return;
    }

    if (latestResearchRun.backtest_id) {
      setSelectedBacktestId(latestResearchRun.backtest_id);
    }
    const recommendationDate = latestSucceededResearchDate(latestResearchRun);
    if (recommendationDate) {
      setSelectedRecommendationDate(recommendationDate);
    }
    queryClient.invalidateQueries({ queryKey: ["quantScreenRuns"] });
    queryClient.invalidateQueries({ queryKey: ["quantTradingDates"] });
    queryClient.invalidateQueries({ queryKey: ["quantRecommendations"] });
    queryClient.invalidateQueries({ queryKey: ["quantReplayRuns"] });
    queryClient.invalidateQueries({ queryKey: ["symbolLatestQuantState"] });
    queryClient.invalidateQueries({ queryKey: ["symbolLatestBacktest"] });
    queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
    queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
    queryClient.invalidateQueries({ queryKey: ["backtests"] });
    if (latestResearchRun.backtest_id) {
      queryClient.invalidateQueries({ queryKey: ["backtestReport", latestResearchRun.backtest_id] });
      queryClient.invalidateQueries({ queryKey: ["backtestAudit", latestResearchRun.backtest_id] });
      queryClient.invalidateQueries({ queryKey: ["backtestDataQuality", latestResearchRun.backtest_id] });
    }
  }, [handledResearchJobId, latestResearchRun, queryClient]);

  const [buyTarget, setBuyTarget] = useState<QuantRecommendation | null>(null);
  const placeOrderMutation = useMutation({
    mutationFn: ({ price, volume, strategyId }: { price: number; volume: number; strategyId: string }) =>
      placeOrder(accountsQuery.data?.items[0]?.id ?? 0, {
        vt_symbol: buyTarget!.vt_symbol,
        side: "BUY",
        price,
        volume,
        reason: `手动加入持仓（候选#${buyTarget!.rank}，${buyTarget!.trade_date}）`,
        recommendation_id: buyTarget!.id,
        strategy_id: strategyId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      setBuyTarget(null);
    },
  });

  const addItemMutation = useMutation({
    mutationFn: ({ groupId, symbol, reason }: { groupId: number; symbol: string; reason: string }) =>
      addPortfolioGroupItem(groupId, { vt_symbol: symbol, source: "backtest", reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      setAddToGroupOpen(false);
      setAddToGroupSymbol(null);
    },
  });

  const handleAddToPortfolio = (vtSymbol: string) => {
    setAddToGroupSymbol(vtSymbol);
    setAddToGroupOpen(true);
  };

  const quantHoldings = holdingsQuery.data?.items ?? [];
  const recommendationItems = recommendationsQuery.data?.items ?? [];
  const quantAverageReturnPct = quantHoldings.length > 0
    ? quantHoldings.reduce((sum, p) => sum + (p.floating_pnl_pct ?? 0), 0) / quantHoldings.length
    : null;
  const quantKpi: QuantKpi = {
    candidateCount: recommendationItems.length,
    holdingsCount: quantHoldings.length,
    averageReturnPct: quantAverageReturnPct,
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">量化交易</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            候选按交易日核查，回测按历史逐日动态候选执行。当前不会连接券商实盘。
          </p>
        </div>
        <Button asChild size="sm" variant="outline">
          <Link to="/portfolio">打开持仓中心</Link>
        </Button>
      </div>

      {isResearchRunning && (
        <ScreenProgress
          completed={latestResearchRun?.progress_current ?? 0}
          total={latestResearchRun?.progress_total ?? 0}
          pct={latestResearchRun?.progress_pct}
          stage={latestResearchRun?.stage}
          message={latestResearchRun?.message}
          strategyName={strategiesQuery.data?.items.find((item) => item.id === selectedStrategy)?.name}
        />
      )}

      {latestResearchRun && latestResearchRun.status !== "running" && (
        <ActionStatus
          screen={latestResearchRun.screen_run ?? undefined}
          backtestId={latestResearchRun.backtest_id}
          status={latestResearchRun.status}
          message={latestResearchRun.message}
        />
      )}

      <QuantWorkflowGuide
        recommendationLoading={recommendationsQuery.isLoading}
        recommendationError={recommendationsQuery.isError}
        recommendationStatus={recommendationsQuery.data?.status}
        recommendationMessage={recommendationsQuery.data?.message}
        recommendationCount={recommendationsQuery.data?.items.length ?? 0}
        backtestCount={backtestRuns.length}
        holdingsCount={holdingsQuery.data?.items.length ?? 0}
        vnpyStatus={vnpyStatusQuery.data}
        latestTradeDate={latestTradeDate}
        latestScreenDate={latestScreenDate}
      />

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b">
          <TabsList className="h-auto rounded-none bg-transparent p-0">
            <TabsTrigger value="candidates" className="rounded-none px-3 py-2 shadow-none">候选</TabsTrigger>
            <TabsTrigger value="backtest" className="rounded-none px-3 py-2 shadow-none">回测</TabsTrigger>
            <TabsTrigger value="logs" className="rounded-none px-3 py-2 shadow-none">日志</TabsTrigger>
            <TabsTrigger value="data" className="rounded-none px-3 py-2 shadow-none">数据</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="candidates" className="mt-0">
          <div className="space-y-4">
            <QuantKpiBar kpi={quantKpi} />
            <RecommendationsPanel
              isLoading={recommendationsQuery.isLoading}
              isError={recommendationsQuery.isError}
              error={recommendationsQuery.error}
              items={recommendationItems}
              tradeDate={recommendationsQuery.data?.trade_date}
              runId={recommendationsQuery.data?.run_id}
              strategyVersion={recommendationsQuery.data?.strategy_version}
              includedBoards={recommendationsQuery.data?.included_boards}
              screenRuns={screenRunsQuery.data?.items ?? []}
              tradingDates={tradingDatesQuery.data?.items.map((item) => item.trade_date) ?? []}
              selectedTradeDate={activeRecommendationDate}
              onSelectedTradeDateChange={setSelectedRecommendationDate}
              strategies={strategiesQuery.data?.items ?? []}
              selectedStrategy={selectedStrategy}
              selectedBoards={backtestParams.included_boards}
              onSelectedBoardsChange={(included_boards) => updateBacktestParams({ ...backtestParams, included_boards })}
              activeBacktestId={activeBacktestId}
              status={recommendationsQuery.data?.status}
              message={recommendationsQuery.data?.message}
              syncedCount={quantGroupItemsQuery.data?.items.length ?? 0}
              onRetry={() => recommendationsQuery.refetch()}
              onRunScreen={() => researchMutation.mutate()}
              isRunningScreen={isResearchRunning}
              onAddToHolding={(item) => setBuyTarget(item)}
            />
          </div>
        </TabsContent>

        <TabsContent value="backtest" className="mt-0">
          <BacktestPanel
            runs={backtestRuns}
            selectedId={activeBacktestId}
            onSelect={setSelectedBacktestId}
            params={backtestParams}
            onParamsChange={updateBacktestParams}
            strategies={strategiesQuery.data?.items ?? []}
            selectedStrategy={selectedStrategy}
            tradingDates={tradingDatesQuery.data?.items.map((item) => item.trade_date) ?? []}
            isRunning={isResearchRunning}
            report={reportQuery.data}
            dataQuality={dataQualityQuery.data}
            isDataQualityLoading={dataQualityQuery.isLoading}
            audit={auditQuery.data}
            isLoading={backtestsQuery.isLoading || reportQuery.isLoading}
            isError={backtestsQuery.isError || reportQuery.isError}
            onRetry={() => {
              backtestsQuery.refetch();
              reportQuery.refetch();
              dataQualityQuery.refetch();
              auditQuery.refetch();
            }}
            validationGrid={validationGridQuery.data}
            isValidationGridLoading={validationGridQuery.isFetching}
            onRunValidationGrid={() => validationGridQuery.refetch()}
            onAddToPortfolio={handleAddToPortfolio}
          />
        </TabsContent>

        <TabsContent value="logs" className="mt-0">
          <BacktestLogWorkspace report={reportQuery.data} audit={auditQuery.data} isLoading={auditQuery.isLoading} />
        </TabsContent>

        <TabsContent value="data" className="mt-0">
          <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
            <VnpyStatusPanel data={vnpyStatusQuery.data} isLoading={vnpyStatusQuery.isLoading} />
            {reportQuery.data && (
              <BacktestDataQuality data={reportQuery.data.data_quality} limitations={reportQuery.data.limitations} />
            )}
          </div>
        </TabsContent>
      </Tabs>

      <AddToGroupDialog
        open={addToGroupOpen}
        onOpenChange={setAddToGroupOpen}
        defaultSymbol={addToGroupSymbol ?? undefined}
        groups={groupsQuery.data?.items ?? []}
        onAdd={(groupId, symbol, reason) => addItemMutation.mutate({ groupId, symbol, reason })}
        isAdding={addItemMutation.isPending}
      />

      <ManualBuyDialog
        open={Boolean(buyTarget)}
        onOpenChange={(open) => !open && setBuyTarget(null)}
        vtSymbol={buyTarget?.vt_symbol ?? ""}
        name={buyTarget?.name}
        defaultPrice={(buyTarget?.risk_control as { trade_plan?: { entry_price?: number } } | null | undefined)?.trade_plan?.entry_price}
        onConfirm={(price, volume, strategyId) => placeOrderMutation.mutate({ price, volume, strategyId })}
        isPending={placeOrderMutation.isPending}
      />
    </div>
  );
}

function strategyMinEntryScore(
  strategies: Array<{ id: string; default_min_entry_score?: number | null }>,
  strategyId: string,
  fallback: number
): number {
  return strategies.find((strategy) => strategy.id === strategyId)?.default_min_entry_score ?? fallback;
}

function researchIsRunning(run?: QuantResearchRun | null): boolean {
  return run?.status === "running";
}

function latestSucceededResearchDate(run: QuantResearchRun): string {
  const screen = run.screen_run;
  const latestRun = [...(screen?.runs ?? [])]
    .filter((run) => ["ready", "succeeded"].includes(run.status) && run.trade_date)
    .sort((left, right) => right.trade_date.localeCompare(left.trade_date))[0];
  return latestRun?.trade_date ?? screen?.end_date ?? screen?.trade_date ?? "";
}
