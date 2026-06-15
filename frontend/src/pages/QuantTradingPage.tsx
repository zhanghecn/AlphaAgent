import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addPortfolioGroupItem,
  createBacktest,
  createReplayRun,
  createScreenRunRange,
  fetchBacktestAudit,
  fetchBacktestDataQuality,
  fetchBacktestExecutionModelComparison,
  fetchBacktestMinuteCoverage,
  fetchBacktestReport,
  fetchBacktestValidationGrid,
  fetchBacktests,
  fetchHoldings,
  fetchPortfolioGroupItems,
  fetchPortfolioGroups,
  fetchQuantStrategies,
  fetchRecommendations,
  fetchReplayRuns,
  fetchScreenRuns,
  fetchSimulationAccounts,
  fetchTradingDates,
  fetchVnpyStatus,
  placeOrder,
  type QuantRecommendation,
  type StrategyReplayRun,
} from "@/api/quant";
import type { MinuteGapAuditResult } from "@/api/dataSync";
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
import { MinuteDataWizard } from "@/features/quant/MinuteDataWizard";
import { AddToGroupDialog } from "@/features/portfolio/AddToGroupDialog";
import { ManualBuyDialog } from "@/features/quant/ManualBuyDialog";
import { Button } from "@/components/ui/button";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";

export function QuantTradingPage() {
  const queryClient = useQueryClient();
  const [selectedBacktestId, setSelectedBacktestId] = useState<number | null>(null);
  const [backtestParams, setBacktestParams] = useState(DEFAULT_BACKTEST_PARAMS);
  const [minuteAudit, setMinuteAudit] = useState<MinuteGapAuditResult | undefined>(undefined);
  const [addToGroupOpen, setAddToGroupOpen] = useState(false);
  const [addToGroupSymbol, setAddToGroupSymbol] = useState<string | null>(null);
  const [selectedRecommendationDate, setSelectedRecommendationDate] = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState(DEFAULT_BACKTEST_PARAMS.strategy);
  const [isScreenRunning, setIsScreenRunning] = useState(false);
  const [strategyRunIndex, setStrategyRunIndex] = useState(0);

  const updateBacktestParams = (next: BacktestParams) => {
    setBacktestParams(next);
    setMinuteAudit(undefined);
  };

  const strategiesQuery = useQuery({
    queryKey: ["quantStrategies"],
    queryFn: fetchQuantStrategies,
    staleTime: 60_000,
  });

  const screenRunsQuery = useQuery({
    queryKey: ["quantScreenRuns", selectedStrategy],
    queryFn: () => fetchScreenRuns(500, selectedStrategy),
    staleTime: 30_000,
    // 批量生成时每 2s 轮询已 persist 的 run 数，驱动实时进度条
    refetchInterval: () => (isScreenRunning ? 2000 : false),
  });

  const tradingDatesQuery = useQuery({
    queryKey: ["quantTradingDates"],
    queryFn: () => fetchTradingDates({ limit: 800 }),
    staleTime: 60_000,
  });

  const activeRecommendationDate =
    selectedRecommendationDate ||
    tradingDatesQuery.data?.latest_trade_date ||
    screenRunsQuery.data?.items[0]?.trade_date ||
    backtestParams.start ||
    "";

  const recommendationsQuery = useQuery({
    queryKey: ["quantRecommendations", activeRecommendationDate, selectedStrategy],
    queryFn: () => fetchRecommendations(200, activeRecommendationDate || undefined, selectedStrategy),
    staleTime: 20_000,
  });

  const replayRunsQuery = useQuery({
    queryKey: ["quantReplayRuns", selectedStrategy],
    queryFn: () => fetchReplayRuns(80, selectedStrategy),
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
    queryKey: ["backtests", "portfolio"],
    queryFn: () => fetchBacktests(20, "portfolio"),
    staleTime: 20_000,
  });

  const activeBacktestId = selectedBacktestId ?? backtestsQuery.data?.items[0]?.id ?? null;
  const reportQuery = useQuery({
    queryKey: ["backtestReport", activeBacktestId],
    queryFn: () => fetchBacktestReport(activeBacktestId!, 80),
    enabled: Boolean(activeBacktestId),
    staleTime: 20_000,
  });

  const minuteCoverageQuery = useQuery({
    queryKey: ["backtestMinuteCoverage", activeBacktestId],
    queryFn: () => fetchBacktestMinuteCoverage(activeBacktestId!),
    enabled: Boolean(activeBacktestId),
    staleTime: 20_000,
  });

  const dataQualityQuery = useQuery({
    queryKey: ["backtestDataQuality", activeBacktestId],
    queryFn: () => fetchBacktestDataQuality(activeBacktestId!),
    enabled: Boolean(activeBacktestId),
    staleTime: 20_000,
  });

  const auditQuery = useQuery({
    queryKey: ["backtestAudit", activeBacktestId],
    queryFn: () => fetchBacktestAudit(activeBacktestId!, undefined, 120),
    enabled: Boolean(activeBacktestId),
    staleTime: 20_000,
  });

  const validationGridQuery = useQuery({
    queryKey: ["backtestValidationGrid", activeBacktestId],
    queryFn: () => fetchBacktestValidationGrid(activeBacktestId!, 54),
    enabled: false,
    staleTime: 60_000,
  });

  const executionComparisonQuery = useQuery({
    queryKey: ["backtestExecutionModelComparison", activeBacktestId],
    queryFn: () => fetchBacktestExecutionModelComparison(activeBacktestId!),
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

  const screenMutation = useMutation({
    mutationFn: async () => {
      // 全局每策略预算：批量跑所有策略 × 所有交易日，各自存储买卖计划
      const strategyIds = (strategiesQuery.data?.items ?? []).map((item) => item.id);
      const targets = strategyIds.length > 0 ? strategyIds : [selectedStrategy];
      let lastResult: Awaited<ReturnType<typeof createScreenRunRange>> | undefined;
      for (let index = 0; index < targets.length; index += 1) {
        setStrategyRunIndex(index);
        lastResult = await createScreenRunRange({
          strategy: targets[index],
          max_symbols: 500,
          recommendation_limit: 20,
          min_recommendation_score: 60,
          persist: true,
          auto_portfolio: true,
          included_boards: backtestParams.included_boards,
        });
      }
      return lastResult;
    },
    onMutate: () => {
      setStrategyRunIndex(0);
      setIsScreenRunning(true);
    },
    onSuccess: () => {
      setIsScreenRunning(false);
      queryClient.invalidateQueries({ queryKey: ["quantScreenRuns"] });
      queryClient.invalidateQueries({ queryKey: ["quantTradingDates"] });
      queryClient.invalidateQueries({ queryKey: ["quantRecommendations"] });
      queryClient.invalidateQueries({ queryKey: ["quantReplayRuns"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
    },
    onError: () => setIsScreenRunning(false),
  });

  const replayMutation = useMutation({
    mutationFn: () =>
      createReplayRun({
        start: backtestParams.start,
        end: tradingDatesQuery.data?.latest_trade_date ?? backtestParams.start,
        strategy: selectedStrategy,
        max_symbols: 500,
        min_entry_score: 68,
        strict_entry: true,
        execution_model: "strict_1430",
        minute_interval: "1m",
        tail_entry_start: "14:30",
        tail_entry_end: "14:30",
        tail_entry_ma5_tolerance_pct: 1.5,
        included_boards: backtestParams.included_boards,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quantReplayRuns"] });
      queryClient.invalidateQueries({ queryKey: ["symbolLatestReplay"] });
    },
  });

  const backtestMutation = useMutation({
    mutationFn: (override?: Partial<BacktestParams> & { persist?: boolean }) =>
      createBacktest({
        ...backtestParams,
        strategy: selectedStrategy,
        ...override,
        strict_entry: true,
        execution_model: "strict_1430",
        minute_interval: "1m",
        tail_entry_start: "14:30",
        tail_entry_end: "14:30",
        persist: override?.persist ?? true,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      if (result.backtest_id) {
        setSelectedBacktestId(result.backtest_id);
        queryClient.invalidateQueries({ queryKey: ["backtestReport", result.backtest_id] });
        queryClient.invalidateQueries({ queryKey: ["backtestMinuteCoverage", result.backtest_id] });
      }
    },
  });

  const [buyTarget, setBuyTarget] = useState<QuantRecommendation | null>(null);
  const placeOrderMutation = useMutation({
    mutationFn: ({ price, volume }: { price: number; volume: number }) =>
      placeOrder(accountsQuery.data?.items[0]?.id ?? 0, {
        vt_symbol: buyTarget!.vt_symbol,
        side: "BUY",
        price,
        volume,
        reason: `手动加入持仓（候选#${buyTarget!.rank}，${buyTarget!.trade_date}）`,
        recommendation_id: buyTarget!.id,
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

  const handleStrategyChange = (strategy: string) => {
    setSelectedStrategy(strategy);
    updateBacktestParams({ ...backtestParams, strategy });
    setSelectedRecommendationDate("");
  };

  const quantHoldings = holdingsQuery.data?.items ?? [];
  const quantAverageReturnPct = quantHoldings.length > 0
    ? quantHoldings.reduce((sum, p) => sum + (p.floating_pnl_pct ?? 0), 0) / quantHoldings.length
    : null;
  const quantKpi: QuantKpi = {
    candidateCount: quantGroupItemsQuery.data?.items.length ?? 0,
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

      {isScreenRunning && (
        <ScreenProgress
          completed={screenRunsQuery.data?.items.length ?? 0}
          total={tradingDatesQuery.data?.items.length ?? 0}
          strategyName={strategiesQuery.data?.items[strategyRunIndex]?.name}
          strategyIndex={strategyRunIndex}
          strategyTotal={strategiesQuery.data?.items.length ?? 1}
        />
      )}

      {(screenMutation.data || backtestMutation.data) && (
        <ActionStatus
          screen={screenMutation.data}
          backtestId={backtestMutation.data?.backtest_id}
        />
      )}

      <QuantWorkflowGuide
        recommendationLoading={recommendationsQuery.isLoading}
        recommendationError={recommendationsQuery.isError}
        recommendationStatus={recommendationsQuery.data?.status}
        recommendationMessage={recommendationsQuery.data?.message}
        recommendationCount={recommendationsQuery.data?.items.length ?? 0}
        backtestCount={backtestsQuery.data?.items.length ?? 0}
        holdingsCount={holdingsQuery.data?.items.length ?? 0}
        minuteAudit={minuteAudit}
        vnpyStatus={vnpyStatusQuery.data}
      />

      <Tabs defaultValue="candidates" className="space-y-4">
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
            <ReplayRunPanel
              latest={replayRunsQuery.data?.items[0]}
              isLoading={replayRunsQuery.isLoading || replayRunsQuery.isFetching}
              isCreating={replayMutation.isPending}
              error={replayMutation.error}
              onCreate={() => replayMutation.mutate()}
            />
            <RecommendationsPanel
              isLoading={recommendationsQuery.isLoading}
              isError={recommendationsQuery.isError}
              error={recommendationsQuery.error}
              items={recommendationsQuery.data?.items ?? []}
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
              onStrategyChange={handleStrategyChange}
              selectedBoards={backtestParams.included_boards}
              onSelectedBoardsChange={(included_boards) => updateBacktestParams({ ...backtestParams, included_boards })}
              activeBacktestId={activeBacktestId}
              status={recommendationsQuery.data?.status}
              message={recommendationsQuery.data?.message}
              syncedCount={quantGroupItemsQuery.data?.items.length ?? 0}
              onRetry={() => recommendationsQuery.refetch()}
              onRunScreen={() => screenMutation.mutate()}
              isRunningScreen={isScreenRunning}
              onAddToHolding={(item) => setBuyTarget(item)}
            />
          </div>
        </TabsContent>

        <TabsContent value="backtest" className="mt-0">
          <BacktestPanel
            runs={backtestsQuery.data?.items ?? []}
            selectedId={activeBacktestId}
            onSelect={setSelectedBacktestId}
            params={backtestParams}
            onParamsChange={updateBacktestParams}
            strategies={strategiesQuery.data?.items ?? []}
            selectedStrategy={selectedStrategy}
            onStrategyChange={handleStrategyChange}
            tradingDates={tradingDatesQuery.data?.items.map((item) => item.trade_date) ?? []}
            isRunning={backtestMutation.isPending}
            onRun={() => backtestMutation.mutate(undefined)}
            report={reportQuery.data}
            minuteCoverage={minuteCoverageQuery.data}
            isMinuteCoverageLoading={minuteCoverageQuery.isLoading}
            dataQuality={dataQualityQuery.data}
            isDataQualityLoading={dataQualityQuery.isLoading}
            audit={auditQuery.data}
            isLoading={backtestsQuery.isLoading || reportQuery.isLoading}
            isError={backtestsQuery.isError || reportQuery.isError}
            onRetry={() => {
              backtestsQuery.refetch();
              reportQuery.refetch();
              minuteCoverageQuery.refetch();
              dataQualityQuery.refetch();
              auditQuery.refetch();
            }}
            validationGrid={validationGridQuery.data}
            isValidationGridLoading={validationGridQuery.isFetching}
            onRunValidationGrid={() => validationGridQuery.refetch()}
            executionComparison={executionComparisonQuery.data}
            isExecutionComparisonLoading={executionComparisonQuery.isFetching}
            onRunExecutionComparison={() => executionComparisonQuery.refetch()}
            onAddToPortfolio={handleAddToPortfolio}
          />
        </TabsContent>

        <TabsContent value="logs" className="mt-0">
          <BacktestLogWorkspace report={reportQuery.data} audit={auditQuery.data} isLoading={auditQuery.isLoading} />
        </TabsContent>

        <TabsContent value="data" className="mt-0">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <MinuteDataWizard
              tailEntryStart={backtestParams.tail_entry_start}
              tailEntryEnd={backtestParams.tail_entry_end}
              minuteInterval={backtestParams.minute_interval}
              backtestId={activeBacktestId}
              isRunningBacktest={backtestMutation.isPending}
              onStrictPipelineComplete={(backtestId) => {
                setSelectedBacktestId(backtestId);
                queryClient.invalidateQueries({ queryKey: ["backtestReport", backtestId] });
                queryClient.invalidateQueries({ queryKey: ["backtestMinuteCoverage", backtestId] });
                queryClient.invalidateQueries({ queryKey: ["backtestDataQuality", backtestId] });
              }}
              onAuditChange={setMinuteAudit}
            />
            <section className="space-y-4">
              <VnpyStatusPanel data={vnpyStatusQuery.data} isLoading={vnpyStatusQuery.isLoading} />
              {reportQuery.data && (
                <BacktestDataQuality data={reportQuery.data.data_quality} limitations={reportQuery.data.limitations} />
              )}
            </section>
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
        onConfirm={(price, volume) => placeOrderMutation.mutate({ price, volume })}
        isPending={placeOrderMutation.isPending}
      />
    </div>
  );
}

function ReplayRunPanel({
  latest,
  isLoading,
  isCreating,
  error,
  onCreate,
}: {
  latest?: StrategyReplayRun;
  isLoading: boolean;
  isCreating: boolean;
  error: unknown;
  onCreate: () => void;
}) {
  const metrics = latest?.metrics ?? {};
  const rejectReasons = metrics.reject_reasons ?? [];
  return (
    <section className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Replay 执行</h2>
          <div className="mt-1 text-sm text-muted-foreground">
            基于已落库候选生成信号到执行的统一复盘，股票详情和持仓建议读取这里。
          </div>
        </div>
        <Button size="sm" variant="outline" onClick={onCreate} disabled={isCreating}>
          {isCreating ? <RefreshCw size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          补齐 replay
        </Button>
      </div>
      {isLoading ? (
        <div className="mt-3 text-sm text-muted-foreground">正在读取 replay...</div>
      ) : latest ? (
        <div className="mt-3 grid gap-3 text-sm md:grid-cols-6">
          <ReplayMetric label="Replay ID" value={`#${latest.id}`} />
          <ReplayMetric label="区间" value={`${latest.start_date} ~ ${latest.end_date}`} />
          <ReplayMetric label="执行尝试" value={metrics.attempt_count ?? 0} />
          <ReplayMetric label="成交" value={metrics.filled_count ?? 0} valueClass="text-rise" />
          <ReplayMetric label="拒绝" value={metrics.rejected_count ?? 0} valueClass={(metrics.rejected_count ?? 0) > 0 ? "text-fall" : undefined} />
          <ReplayMetric label="状态" value={latest.status} />
        </div>
      ) : (
        <div className="mt-3 rounded-md border p-3 text-sm text-muted-foreground">
          暂无 replay。生成区间候选会自动创建，也可以基于已有候选手动补齐。
        </div>
      )}
      {rejectReasons.length ? (
        <div className="mt-3 flex flex-wrap gap-2 border-t pt-3 text-xs">
          {rejectReasons.slice(0, 6).map((row) => (
            <span key={row.reason} className="rounded-md border px-2 py-1 text-muted-foreground">
              {replayReasonLabel(row.reason)}：{row.count}
            </span>
          ))}
        </div>
      ) : null}
      {error ? (
        <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-2 text-sm text-fall dark:border-red-500/30 dark:bg-red-500/10">
          {error instanceof Error ? error.message : "补齐 replay 失败"}
        </div>
      ) : null}
    </section>
  );
}

function ReplayMetric({ label, value, valueClass }: { label: string; value?: string | number | null; valueClass?: string }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={`mt-0.5 font-medium tabular-nums ${valueClass ?? ""}`}>{value ?? "--"}</div>
    </div>
  );
}

function replayReasonLabel(reason?: string | null) {
  const labels: Record<string, string> = {
    limit_up_open_blocked: "开盘涨停买不到",
    limit_up_tail_unfilled: "尾盘涨停买不到",
    no_execute_bar: "缺执行日K线",
    tail_entry_not_triggered: "尾盘入场未触发",
    today_pending_1430_snapshot: "等待今日14:30",
    already_holding: "已持有",
    no_next_trade_date: "无下一交易日",
  };
  return labels[reason ?? ""] ?? reason ?? "--";
}
