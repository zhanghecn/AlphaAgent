import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3, Download } from "lucide-react";
import type { BacktestRun, QuantStrategyOption } from "@/api/quant";
import {
  backtestReportCsvUrl,
  fetchBacktestAudit,
  fetchBacktestDataQuality,
  fetchBacktestFactorAudit,
  fetchBacktestPhaseStrategyFamilyMatrix,
  fetchBacktestReplacementQualityMatrix,
  fetchBacktestReport,
  fetchBacktestRotationOpportunityCostMatrix,
  fetchBacktestSetupMarketExitAudit,
  fetchBacktestTopCandidateAudit,
  fetchBacktestTrendWinnerProtectionMatrix,
  fetchBacktestValidationGrid,
  runBacktestStrategyComparison,
} from "@/api/quant";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { BacktestParams } from "@/features/quant/constants";
import { BacktestSummary } from "@/features/quant/BacktestSummary";
import {
  BacktestTradeTable,
  BacktestBenchmarkTable,
  BacktestPeriodTable,
  BacktestRegimeTable,
  BacktestMonthlyTable,
  BacktestSymbolTable,
  BacktestWorstTrades,
} from "@/features/quant/BacktestTables";
import { BacktestDrilldownPanel } from "@/features/quant/BacktestDrilldownPanel";
import { BacktestDataQualityPanel } from "@/features/quant/BacktestDataQualityPanel";
import {
  BacktestDataAsOfAuditPanel,
  BacktestMarketAuditPanel,
  BacktestRealityStats,
  BacktestRobustnessPanel,
  BacktestValidationGridPanel,
} from "@/features/quant/BacktestAnalysis";
import { SignalCardList } from "@/features/quant/SignalCardList";
import { BacktestStrategyComparisonPanel } from "@/features/quant/BacktestStrategyComparisonPanel";

export function BacktestPanel({
  runs,
  selectedId,
  onSelect,
  params,
  strategies,
  selectedStrategy,
  report,
  isLoading,
  isError,
  onRetry,
  validationGrid,
  isValidationGridLoading,
  onRunValidationGrid,
  onAddToPortfolio,
}: {
  runs: BacktestRun[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  params: BacktestParams;
  strategies: QuantStrategyOption[];
  selectedStrategy: string;
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  validationGrid?: Awaited<ReturnType<typeof fetchBacktestValidationGrid>>;
  isValidationGridLoading: boolean;
  onRunValidationGrid: () => void;
  onAddToPortfolio?: (vtSymbol: string) => void;
}) {
  const selectedRun = runs.find((item) => item.id === selectedId) ?? runs[0] ?? null;
  const [activeDetailTab, setActiveDetailTab] = useState("trades");
  const shouldLoadValidation = Boolean(selectedId && activeDetailTab === "validation");
  const marketAuditReportQuery = useQuery({
    queryKey: ["backtestReport", selectedId, "market-audit"],
    queryFn: () => fetchBacktestReport(selectedId!, 80, { includeAnalysis: true }),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const marketAuditReport = marketAuditReportQuery.data ?? report;
  const topCandidateAuditQuery = useQuery({
    queryKey: ["backtestTopCandidateAudit", selectedId, 10],
    queryFn: () => fetchBacktestTopCandidateAudit(selectedId!, 10),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const factorAuditQuery = useQuery({
    queryKey: ["backtestFactorAudit", selectedId, 100],
    queryFn: () => fetchBacktestFactorAudit(selectedId!, 100),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const setupMarketExitAuditQuery = useQuery({
    queryKey: ["backtestSetupMarketExitAudit", selectedId, 10],
    queryFn: () => fetchBacktestSetupMarketExitAudit(selectedId!, 10),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const phaseStrategyFamilyMatrixQuery = useQuery({
    queryKey: ["backtestPhaseStrategyFamilyMatrix", selectedId, "10,20,100"],
    queryFn: () => fetchBacktestPhaseStrategyFamilyMatrix(selectedId!, [10, 20, 100]),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const replacementQualityMatrixQuery = useQuery({
    queryKey: ["backtestReplacementQualityMatrix", selectedId, 80],
    queryFn: () => fetchBacktestReplacementQualityMatrix(selectedId!, 80),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const rotationOpportunityCostMatrixQuery = useQuery({
    queryKey: ["backtestRotationOpportunityCostMatrix", selectedId, 20, 80, 20],
    queryFn: () => fetchBacktestRotationOpportunityCostMatrix(selectedId!, 20, 80, 20),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const trendWinnerProtectionMatrixQuery = useQuery({
    queryKey: ["backtestTrendWinnerProtectionMatrix", selectedId, 20, 80, 20],
    queryFn: () => fetchBacktestTrendWinnerProtectionMatrix(selectedId!, 20, 80, 20),
    enabled: Boolean(selectedId),
    staleTime: 60_000,
  });
  const validationReport = marketAuditReport;
  const strategyComparisonQuery = useQuery({
    queryKey: ["backtestStrategyComparison", params],
    queryFn: () =>
      runBacktestStrategyComparison({
        ...params,
        persist: false,
        strategies: strategies.map((strategy) => strategy.id),
      }),
    enabled: false,
    staleTime: 60_000,
  });
  const dataQualityQuery = useQuery({
    queryKey: ["backtestDataQuality", selectedId],
    queryFn: () => fetchBacktestDataQuality(selectedId!),
    enabled: shouldLoadValidation,
    staleTime: 60_000,
  });
  const auditQuery = useQuery({
    queryKey: ["backtestAudit", selectedId],
    queryFn: () => fetchBacktestAudit(selectedId!, undefined, 120),
    enabled: shouldLoadValidation,
    staleTime: 60_000,
  });
  const validationAnalysisLoading =
    activeDetailTab === "validation" && marketAuditReportQuery.isFetching && !marketAuditReportQuery.data;
  if (isLoading && !selectedRun) return <LoadingState rows={5} />;
  if (isError) return <ErrorState message="加载回测报告失败" onRetry={onRetry} />;

  return (
    <section className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} />
          <h2 className="text-sm font-semibold">回测结果</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {selectedId && (
            <Button asChild variant="outline" size="sm">
              <a href={backtestReportCsvUrl(selectedId, 500)} download>
                <Download size={15} />
                导出CSV
              </a>
            </Button>
          )}
          <select
            className="h-8 rounded-md border bg-background px-2 text-sm"
            value={selectedId ?? ""}
            onChange={(event) => onSelect(Number(event.target.value))}
          >
            {runs.map((run) => (
              <option key={run.id} value={run.id}>
                #{run.id} {run.start_date} - {run.end_date} / {run.strategy_version}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-4 p-4">
        <BacktestReadonlyMethod
          run={selectedRun}
          report={report}
          params={params}
          strategyName={strategies.find((strategy) => strategy.id === selectedStrategy)?.name ?? "主线龙回头回踩低吸"}
        />
        {!report ? (
          isLoading ? (
            <div className="rounded-lg border p-4">
              <div className="mb-3 text-sm font-medium">正在加载回测报告</div>
              <LoadingState rows={4} />
            </div>
          ) : (
            <EmptyState message="暂无回测报告" description="请先在候选页刷新候选并回测，系统会自动生成组合回测。" />
          )
        ) : (
          <>
            <BacktestSummary report={report} audit={auditQuery.data} />
            <BacktestMarketAuditPanel
              report={marketAuditReport}
              topCandidateAudit={topCandidateAuditQuery.data}
              isTopCandidateAuditLoading={topCandidateAuditQuery.isFetching}
              factorAudit={factorAuditQuery.data}
              isFactorAuditLoading={factorAuditQuery.isFetching}
              setupMarketExitAudit={setupMarketExitAuditQuery.data}
              isSetupMarketExitAuditLoading={setupMarketExitAuditQuery.isFetching}
              phaseStrategyFamilyMatrix={phaseStrategyFamilyMatrixQuery.data}
              isPhaseStrategyFamilyMatrixLoading={phaseStrategyFamilyMatrixQuery.isFetching}
              replacementQualityMatrix={replacementQualityMatrixQuery.data}
              isReplacementQualityMatrixLoading={replacementQualityMatrixQuery.isFetching}
              rotationOpportunityCostMatrix={rotationOpportunityCostMatrixQuery.data}
              isRotationOpportunityCostMatrixLoading={rotationOpportunityCostMatrixQuery.isFetching}
              trendWinnerProtectionMatrix={trendWinnerProtectionMatrixQuery.data}
              isTrendWinnerProtectionMatrixLoading={trendWinnerProtectionMatrixQuery.isFetching}
            />
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <section className="space-y-4">
                <BacktestTradeTable backtestId={selectedId} trades={report.recent_trades ?? report.trades} total={report.trade_count} />
                <SignalCardList trades={report.recent_trades ?? report.trades} />
              </section>
              <section className="space-y-4">
                {report.extended_metrics && <BacktestRealityStats metrics={report.extended_metrics} />}
                <BacktestSymbolTable rows={report.symbol_performance ?? []} compact onAddToPortfolio={onAddToPortfolio} />
              </section>
            </div>

            <Tabs value={activeDetailTab} onValueChange={setActiveDetailTab} className="space-y-3">
              <TabsList className="h-auto rounded-none bg-transparent p-0">
                <TabsTrigger value="validation" className="rounded-none px-3 py-2 shadow-none">验证</TabsTrigger>
                <TabsTrigger value="trades" className="rounded-none px-3 py-2 shadow-none">交易归因</TabsTrigger>
                <TabsTrigger value="months" className="rounded-none px-3 py-2 shadow-none">收益分段</TabsTrigger>
              </TabsList>
              <TabsContent value="validation" className="space-y-4">
                <BacktestDataQualityPanel quality={dataQualityQuery.data} isLoading={dataQualityQuery.isLoading} />
                {validationAnalysisLoading && (
                  <div className="rounded-lg border p-3 text-sm text-muted-foreground">
                    正在加载深度验证数据，回测收益和交易归因已可先查看。
                  </div>
                )}
                {validationReport?.data_as_of_audit && <BacktestDataAsOfAuditPanel audit={validationReport.data_as_of_audit} />}
                {validationReport?.benchmark && <BacktestBenchmarkTable benchmarks={validationReport.benchmark.benchmarks} />}
                {validationReport?.period_analysis && <BacktestPeriodTable analysis={validationReport.period_analysis} />}
                {validationReport?.regime_analysis && <BacktestRegimeTable analysis={validationReport.regime_analysis} />}
                {validationReport?.robustness_checks && <BacktestRobustnessPanel checks={validationReport.robustness_checks} />}
                {selectedId && (
                  <BacktestValidationGridPanel
                    backtestId={selectedId}
                    grid={validationGrid}
                    isLoading={isValidationGridLoading}
                    onRun={onRunValidationGrid}
                  />
                )}
                <BacktestStrategyComparisonPanel
                  comparison={strategyComparisonQuery.data}
                  isLoading={strategyComparisonQuery.isFetching}
                  error={strategyComparisonQuery.error}
                  onRun={() => strategyComparisonQuery.refetch()}
                />
              </TabsContent>
              <TabsContent value="trades" className="space-y-4">
                {selectedId && <BacktestDrilldownPanel backtestId={selectedId} report={report} />}
                <BacktestSymbolTable rows={report.symbol_performance ?? []} onAddToPortfolio={onAddToPortfolio} />
                <BacktestWorstTrades rows={report.worst_trades ?? []} />
              </TabsContent>
              <TabsContent value="months">
                <BacktestMonthlyTable rows={report.monthly_returns ?? []} />
              </TabsContent>
            </Tabs>
          </>
        )}
      </div>
    </section>
  );
}

function BacktestReadonlyMethod({
  run,
  report,
  params,
  strategyName,
}: {
  run: BacktestRun | null;
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  params: BacktestParams;
  strategyName: string;
}) {
  const rawParams = run?.params ?? {};
  const maxPositions = numberOrDefault(rawParams.max_positions, params.max_positions);
  const candidateLimit = numberOrDefault(report?.method?.entry_filter?.candidate_limit ?? rawParams.candidate_limit, params.candidate_limit);
  const maxSymbols = numberOrDefault(rawParams.max_symbols, params.max_symbols);
  const boardValues = report?.method?.included_board_labels?.length
    ? report.method.included_board_labels
    : Array.isArray(rawParams.included_boards)
      ? rawParams.included_boards
      : [];
  const boards = boardValues.length
    ? boardValues.join("、")
    : "主板";
  const executionModel = String(rawParams.execution_model ?? report?.method?.execution?.execution_model ?? params.execution_model);

  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-3">
        <div>
          <div className="font-medium">当前回测口径</div>
          <div className="mt-1 text-xs text-muted-foreground">
            回测由候选页一键研究自动生成；这里仅查看结果和归因。
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          {run ? `#${run.id}` : "--"}
        </div>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-6">
        <ReadonlyCell label="策略" value={strategyName} />
        <ReadonlyCell label="区间" value={report ? `${report.start_date} 至 ${report.end_date}` : run ? `${run.start_date} 至 ${run.end_date}` : "--"} />
        <ReadonlyCell label="股票池" value={`${boards} / ${maxSymbols}只`} />
        <ReadonlyCell label="买入规则" value={`前${candidateLimit}名`} />
        <ReadonlyCell label="最大持仓" value={`${maxPositions}只`} />
        <ReadonlyCell label="执行" value={executionModel === "legacy_next_open" ? "D+1开盘" : executionModel} />
      </div>
    </div>
  );
}

function ReadonlyCell({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 min-h-5 font-medium">{value ?? "--"}</div>
    </div>
  );
}

function numberOrDefault(value: unknown, fallback: number) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}
