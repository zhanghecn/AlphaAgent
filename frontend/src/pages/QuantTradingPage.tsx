import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart3, Play, RefreshCw, WalletCards } from "lucide-react";
import {
  addPortfolioGroupItem,
  autoBuyRecommendations,
  createBacktest,
  createScreenRun,
  fetchBacktestAudit,
  fetchBacktestReport,
  fetchBacktestValidationGrid,
  fetchBacktests,
  fetchHoldings,
  fetchPortfolioGroupItems,
  fetchPortfolioGroups,
  fetchRecommendations,
  fetchSimulationAccounts,
  fetchVnpyStatus,
} from "@/api/quant";
import type { MinuteGapAuditResult } from "@/api/dataSync";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { DEFAULT_BACKTEST_PARAMS, type BacktestParams } from "@/features/quant/constants";
import { ActionStatus } from "@/features/quant/ActionStatus";
import { QuantWorkflowGuide } from "@/features/quant/QuantWorkflowGuide";
import { QuantGroupPreview } from "@/features/quant/QuantGroupPreview";
import { VnpyStatusPanel } from "@/features/quant/VnpyStatusPanel";
import { RecommendationsPanel } from "@/features/quant/RecommendationsPanel";
import { BacktestPanel } from "@/features/quant/BacktestPanel";
import { BacktestLogWorkspace } from "@/features/quant/BacktestLogWorkspace";
import { BacktestDataQuality } from "@/features/quant/BacktestAnalysis";
import { MinuteDataWizard } from "@/features/quant/MinuteDataWizard";
import { AddToGroupDialog } from "@/features/portfolio/AddToGroupDialog";

export function QuantTradingPage() {
  const queryClient = useQueryClient();
  const [selectedBacktestId, setSelectedBacktestId] = useState<number | null>(null);
  const [backtestParams, setBacktestParams] = useState(DEFAULT_BACKTEST_PARAMS);
  const [minuteAudit, setMinuteAudit] = useState<MinuteGapAuditResult | undefined>(undefined);
  const [addToGroupOpen, setAddToGroupOpen] = useState(false);
  const [addToGroupSymbol, setAddToGroupSymbol] = useState<string | null>(null);

  const applyStrictMinutePreset = () => {
    setBacktestParams((current) => ({
      ...current,
      max_symbols: Math.max(current.max_symbols, 1500),
      intraday_entry: true,
      minute_entry_required: true,
      tail_entry_start: current.tail_entry_start || "14:30",
      tail_entry_end: current.tail_entry_end || "14:57",
      tail_entry_ma5_tolerance_pct: current.tail_entry_ma5_tolerance_pct || 1.5,
    }));
  };

  const recommendationsQuery = useQuery({
    queryKey: ["quantRecommendations"],
    queryFn: () => fetchRecommendations(20),
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
    queryKey: ["backtests"],
    queryFn: () => fetchBacktests(10),
    staleTime: 20_000,
  });

  const activeBacktestId = selectedBacktestId ?? backtestsQuery.data?.items[0]?.id ?? null;
  const reportQuery = useQuery({
    queryKey: ["backtestReport", activeBacktestId],
    queryFn: () => fetchBacktestReport(activeBacktestId!, 80),
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
    mutationFn: () =>
      createScreenRun({
        max_symbols: 500,
        recommendation_limit: 20,
        min_recommendation_score: 60,
        persist: true,
        auto_portfolio: true,
        included_boards: backtestParams.included_boards,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["quantRecommendations"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
    },
  });

  const backtestMutation = useMutation({
    mutationFn: (override?: Partial<BacktestParams> & { persist?: boolean }) =>
      createBacktest({
        ...backtestParams,
        ...override,
        persist: override?.persist ?? true,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      if (result.backtest_id) {
        setSelectedBacktestId(result.backtest_id);
        queryClient.invalidateQueries({ queryKey: ["backtestReport", result.backtest_id] });
      }
    },
  });

  const autoBuyMutation = useMutation({
    mutationFn: () =>
      autoBuyRecommendations({
        account_id: accountsQuery.data?.items[0]?.id,
        limit: 5,
        amount_per_order: 100_000,
        initial_cash: 1_000_000,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
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

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">量化交易</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            按"数据准备、筛选候选、回测验证、模拟持仓"执行。当前不会连接券商实盘。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" onClick={() => screenMutation.mutate()} disabled={screenMutation.isPending}>
            {screenMutation.isPending ? <RefreshCw size={16} className="animate-spin" /> : <Play size={16} />}
            运行筛选
          </Button>
          <Button variant="outline" onClick={() => backtestMutation.mutate(undefined)} disabled={backtestMutation.isPending}>
            {backtestMutation.isPending ? <RefreshCw size={16} className="animate-spin" /> : <BarChart3 size={16} />}
            运行回测
          </Button>
          <Button onClick={() => autoBuyMutation.mutate()} disabled={autoBuyMutation.isPending}>
            {autoBuyMutation.isPending ? <RefreshCw size={16} className="animate-spin" /> : <WalletCards size={16} />}
            自动模拟建仓
          </Button>
        </div>
      </div>

      {(screenMutation.data || backtestMutation.data || autoBuyMutation.data) && (
        <ActionStatus
          screen={screenMutation.data}
          backtestId={backtestMutation.data?.backtest_id}
          autoBuy={autoBuyMutation.data}
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
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <RecommendationsPanel
              isLoading={recommendationsQuery.isLoading}
              isError={recommendationsQuery.isError}
              error={recommendationsQuery.error}
              items={recommendationsQuery.data?.items ?? []}
              tradeDate={recommendationsQuery.data?.trade_date}
              runId={recommendationsQuery.data?.run_id}
              strategyVersion={recommendationsQuery.data?.strategy_version}
              includedBoards={recommendationsQuery.data?.included_boards}
              selectedBoards={backtestParams.included_boards}
              onSelectedBoardsChange={(included_boards) => setBacktestParams({ ...backtestParams, included_boards })}
              status={recommendationsQuery.data?.status}
              message={recommendationsQuery.data?.message}
              syncedCount={quantGroupItemsQuery.data?.items.length ?? 0}
              onRetry={() => recommendationsQuery.refetch()}
              onRunScreen={() => screenMutation.mutate()}
              isRunningScreen={screenMutation.isPending}
            />
            <section className="space-y-4">
              <QuantGroupPreview
                candidateCount={quantGroupItemsQuery.data?.items.length ?? 0}
                holdingsCount={holdingsQuery.data?.items.length ?? 0}
                cash={accountsQuery.data?.items[0]?.cash}
                initialCash={accountsQuery.data?.items[0]?.initial_cash}
                positions={holdingsQuery.data?.items ?? []}
                onAutoBuy={() => autoBuyMutation.mutate()}
                isAutoBuying={autoBuyMutation.isPending}
              />
            </section>
          </div>
        </TabsContent>

        <TabsContent value="backtest" className="mt-0">
          <BacktestPanel
            runs={backtestsQuery.data?.items ?? []}
            selectedId={activeBacktestId}
            onSelect={setSelectedBacktestId}
            params={backtestParams}
            onParamsChange={setBacktestParams}
            isRunning={backtestMutation.isPending}
            onRun={() => backtestMutation.mutate(undefined)}
            onStrictMinutePreset={applyStrictMinutePreset}
            report={reportQuery.data}
            audit={auditQuery.data}
            isLoading={backtestsQuery.isLoading || reportQuery.isLoading}
            isError={backtestsQuery.isError || reportQuery.isError}
            onRetry={() => {
              backtestsQuery.refetch();
              reportQuery.refetch();
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
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <MinuteDataWizard
              tailEntryStart={backtestParams.tail_entry_start}
              tailEntryEnd={backtestParams.tail_entry_end}
              isRunningBacktest={backtestMutation.isPending}
              onStrictPipelineComplete={(backtestId) => {
                setSelectedBacktestId(backtestId);
                queryClient.invalidateQueries({ queryKey: ["backtestReport", backtestId] });
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
    </div>
  );
}
