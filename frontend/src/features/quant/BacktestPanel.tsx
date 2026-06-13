import { BarChart3, Download, ShieldCheck } from "lucide-react";
import type { BacktestRun } from "@/api/quant";
import { backtestReportCsvUrl, fetchBacktestAudit, fetchBacktestReport, fetchBacktestValidationGrid } from "@/api/quant";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { BacktestParams } from "@/features/quant/constants";
import { BacktestParamsForm } from "@/features/quant/BacktestParamsForm";
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
import { BacktestSignalEventsPanel } from "@/features/quant/BacktestSignalEventsPanel";
import {
  BacktestExecutionQualityPanel,
  BacktestRealityStats,
  BacktestRobustnessPanel,
  BacktestValidationGridPanel,
} from "@/features/quant/BacktestAnalysis";
import { SignalCardList } from "@/features/quant/SignalCardList";

export function BacktestPanel({
  runs,
  selectedId,
  onSelect,
  params,
  onParamsChange,
  tradingDates,
  isRunning,
  onRun,
  onStrictMinutePreset,
  report,
  audit,
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
  onParamsChange: (params: BacktestParams) => void;
  tradingDates: string[];
  isRunning: boolean;
  onRun: () => void;
  onStrictMinutePreset: () => void;
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  audit?: Awaited<ReturnType<typeof fetchBacktestAudit>>;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  validationGrid?: Awaited<ReturnType<typeof fetchBacktestValidationGrid>>;
  isValidationGridLoading: boolean;
  onRunValidationGrid: () => void;
  onAddToPortfolio?: (vtSymbol: string) => void;
}) {
  if (isLoading) return <LoadingState rows={5} />;
  if (isError) return <ErrorState message="加载回测报告失败" onRetry={onRetry} />;

  return (
    <section className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <BarChart3 size={16} />
          <h2 className="text-sm font-semibold">回测结果</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={onStrictMinutePreset}>
            <ShieldCheck size={15} />
            严格分钟预设
          </Button>
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
                #{run.id} {run.start_date} - {run.end_date}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="space-y-4 p-4">
        <BacktestParamsForm
          params={params}
          onChange={onParamsChange}
          tradingDates={tradingDates}
          isRunning={isRunning}
          onRun={onRun}
        />
        {!report ? (
          <EmptyState message="暂无回测报告" description="运行回测后会生成可复查的交易表和指标。" />
        ) : (
          <>
            <BacktestSummary report={report} audit={audit} />

            <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
              <section className="space-y-4">
                {report.execution_quality && <BacktestExecutionQualityPanel quality={report.execution_quality} />}
                <BacktestTradeTable backtestId={selectedId} trades={report.recent_trades ?? report.trades} total={report.trade_count} />
                <SignalCardList trades={report.recent_trades ?? report.trades} />
              </section>
              <section className="space-y-4">
                {report.extended_metrics && <BacktestRealityStats metrics={report.extended_metrics} />}
                <BacktestSymbolTable rows={report.symbol_performance ?? []} compact onAddToPortfolio={onAddToPortfolio} />
              </section>
            </div>

            <Tabs defaultValue="validation" className="space-y-3">
              <TabsList className="h-auto rounded-none bg-transparent p-0">
                <TabsTrigger value="validation" className="rounded-none px-3 py-2 shadow-none">验证</TabsTrigger>
                <TabsTrigger value="trades" className="rounded-none px-3 py-2 shadow-none">交易归因</TabsTrigger>
                <TabsTrigger value="signals" className="rounded-none px-3 py-2 shadow-none">信号流水</TabsTrigger>
                <TabsTrigger value="months" className="rounded-none px-3 py-2 shadow-none">收益分段</TabsTrigger>
              </TabsList>
              <TabsContent value="validation" className="space-y-4">
                {report.benchmark && <BacktestBenchmarkTable benchmarks={report.benchmark.benchmarks} />}
                {report.period_analysis && <BacktestPeriodTable analysis={report.period_analysis} />}
                {report.regime_analysis && <BacktestRegimeTable analysis={report.regime_analysis} />}
                {report.robustness_checks && <BacktestRobustnessPanel checks={report.robustness_checks} />}
                {selectedId && (
                  <BacktestValidationGridPanel
                    backtestId={selectedId}
                    grid={validationGrid}
                    isLoading={isValidationGridLoading}
                    onRun={onRunValidationGrid}
                  />
                )}
              </TabsContent>
              <TabsContent value="trades" className="space-y-4">
                {selectedId && <BacktestDrilldownPanel backtestId={selectedId} report={report} />}
                <BacktestSymbolTable rows={report.symbol_performance ?? []} onAddToPortfolio={onAddToPortfolio} />
                <BacktestWorstTrades rows={report.worst_trades ?? []} />
              </TabsContent>
              <TabsContent value="signals" className="space-y-4">
                {selectedId && (
                  <BacktestSignalEventsPanel
                    backtestId={selectedId}
                    defaultCapital={params.initial_cash}
                    defaultMaxPositions={params.max_positions}
                    defaultStart={report.start_date}
                    defaultEnd={report.end_date}
                  />
                )}
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
