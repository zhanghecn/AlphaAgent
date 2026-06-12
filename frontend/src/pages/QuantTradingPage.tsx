import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, BarChart3, Briefcase, ClipboardCheck, Database, Download, FileText, FileUp, Play, RefreshCw, ShieldCheck, Upload, WalletCards } from "lucide-react";
import {
  autoBuyRecommendations,
  backtestReportCsvUrl,
  backtestValidationGridCsvUrl,
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
  importVnpyMinuteBars,
  importVnpyMinuteBarsForGaps,
  runStrictMinuteBacktestPipeline,
  type BacktestClosedTrade,
  type BacktestRun,
  type QuantRecommendation,
  type VnpyStatus,
} from "@/api/quant";
import {
  auditMinuteGapCsv,
  fetchMinuteGapImportTemplate,
  fetchMinuteGapVendorManifest,
  fetchMinuteGapVendorManifestCsv,
  importMinuteBarsCsv,
  importMinuteGapsFromTdx,
  importMinuteGapsFromTushare,
  type MinuteBarsImportResult,
  type MinuteGapAuditResult,
  type MinuteGapProviderImportResult,
  type MinuteGapVendorManifest,
} from "@/api/dataSync";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn, formatAmount, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

const DEFAULT_BACKTEST_START = "2025-10-14";
const MIN_TRUSTED_BACKTEST_VERSION = "0.1.1";
const QUANT_BOARD_OPTIONS = [
  { value: "main", label: "主板" },
  { value: "chinext", label: "创业板" },
  { value: "star", label: "科创板" },
  { value: "bse", label: "北交所" },
] as const;

const DEFAULT_BACKTEST_PARAMS = {
  start: DEFAULT_BACKTEST_START,
  initial_cash: 1_000_000,
  max_symbols: 120,
  max_positions: 8,
  min_entry_score: 68,
  strict_entry: true,
  intraday_entry: true,
  minute_entry_required: false,
  tail_entry_start: "14:30",
  tail_entry_end: "14:57",
  tail_entry_ma5_tolerance_pct: 1.5,
  included_boards: ["main"],
};

type QuantBoard = (typeof QUANT_BOARD_OPTIONS)[number]["value"];

export function QuantTradingPage() {
  const queryClient = useQueryClient();
  const [selectedBacktestId, setSelectedBacktestId] = useState<number | null>(null);
  const [backtestParams, setBacktestParams] = useState(DEFAULT_BACKTEST_PARAMS);
  const [minuteGapCsv, setMinuteGapCsv] = useState("");
  const [minuteImportCsv, setMinuteImportCsv] = useState("");
  const [minuteGapFilePath, setMinuteGapFilePath] = useState("");
  const [minuteImportFilePath, setMinuteImportFilePath] = useState("");
  const [minuteGapTemplate, setMinuteGapTemplate] = useState("");
  const [minuteVendorManifestCsv, setMinuteVendorManifestCsv] = useState("");
  const [vnpyImportParams, setVnpyImportParams] = useState({
    vt_symbol: "600000.SSE",
    start: DEFAULT_BACKTEST_START,
    end: "",
    dry_run: true,
  });

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
    mutationFn: (override?: Partial<typeof DEFAULT_BACKTEST_PARAMS> & { persist?: boolean }) =>
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

  const minuteGapAuditMutation = useMutation({
    mutationFn: () =>
      auditMinuteGapCsv({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: backtestParams.tail_entry_start,
        tail_entry_end: backtestParams.tail_entry_end,
      }),
  });

  const minuteGapTemplateMutation = useMutation({
    mutationFn: () => fetchMinuteGapImportTemplate({ gap_csv_text: minuteGapCsv, sample_limit: 200 }),
    onSuccess: (content) => setMinuteGapTemplate(content),
  });

  const minuteVendorManifestMutation = useMutation({
    mutationFn: () =>
      fetchMinuteGapVendorManifest({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        tail_entry_start: backtestParams.tail_entry_start,
        tail_entry_end: backtestParams.tail_entry_end,
        sample_limit: 20,
      }),
  });

  const minuteVendorManifestCsvMutation = useMutation({
    mutationFn: () =>
      fetchMinuteGapVendorManifestCsv({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        tail_entry_start: backtestParams.tail_entry_start,
        tail_entry_end: backtestParams.tail_entry_end,
      }),
    onSuccess: (content) => setMinuteVendorManifestCsv(content),
  });

  const minuteImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteBarsCsv({
        csv_text: minuteImportFilePath.trim() ? undefined : minuteImportCsv,
        file_path: minuteImportFilePath.trim() || undefined,
        interval: "1m",
        source: minuteImportFilePath.trim() ? "manual_csv_file" : "manual_csv",
        dry_run: dryRun,
      }),
    onSuccess: (_result, dryRun) => {
      if (!dryRun) {
        minuteGapAuditMutation.reset();
      }
    },
  });

  const vnpyMinuteImportMutation = useMutation({
    mutationFn: () =>
      importVnpyMinuteBars({
        vt_symbol: vnpyImportParams.vt_symbol,
        start: vnpyImportParams.start,
        end: vnpyImportParams.end || undefined,
        interval: "1m",
        dry_run: vnpyImportParams.dry_run,
      }),
    onSuccess: (result) => {
      if (result.rows_written) {
        minuteGapAuditMutation.reset();
      }
    },
  });

  const vnpyGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importVnpyMinuteBarsForGaps({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: backtestParams.tail_entry_start,
        tail_entry_end: backtestParams.tail_entry_end,
        dry_run: dryRun,
        max_gaps: 2000,
      }),
    onSuccess: (result, dryRun) => {
      if (!dryRun && result.rows_written) {
        minuteGapAuditMutation.reset();
      }
    },
  });

  const tushareGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteGapsFromTushare({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: backtestParams.tail_entry_start,
        tail_entry_end: backtestParams.tail_entry_end,
        dry_run: dryRun,
        max_gaps: 200,
      }),
    onSuccess: (result, dryRun) => {
      if (!dryRun && result.rows_written) {
        minuteGapAuditMutation.reset();
      }
    },
  });

  const tdxGapImportMutation = useMutation({
    mutationFn: (dryRun: boolean) =>
      importMinuteGapsFromTdx({
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        interval: "1m",
        tail_entry_start: backtestParams.tail_entry_start,
        tail_entry_end: backtestParams.tail_entry_end,
        dry_run: dryRun,
        max_gaps: 2000,
        max_pages_per_symbol: 32,
        timeout_seconds: 2,
      }),
    onSuccess: (result, dryRun) => {
      if (!dryRun && result.rows_written) {
        minuteGapAuditMutation.reset();
      }
    },
  });

  const strictPipelineMutation = useMutation({
    mutationFn: () =>
      runStrictMinuteBacktestPipeline({
        ...backtestParams,
        max_symbols: Math.max(backtestParams.max_symbols, 1500),
        gap_csv_text: minuteGapFilePath.trim() ? undefined : minuteGapCsv,
        gap_file_path: minuteGapFilePath.trim() || undefined,
        min_tail_bars: 1,
        trade_limit: 80,
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["backtests"] });
      const backtestId = result.backtest?.backtest_id;
      if (backtestId) {
        setSelectedBacktestId(backtestId);
        queryClient.invalidateQueries({ queryKey: ["backtestReport", backtestId] });
      }
    },
  });

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">量化交易</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            按“数据准备、筛选候选、回测验证、模拟持仓”执行。当前不会连接券商实盘。
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
        minuteAudit={minuteGapAuditMutation.data}
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
              <HoldingsPanel
                accountCount={accountsQuery.data?.items.length ?? 0}
                cash={accountsQuery.data?.items[0]?.cash}
                initialCash={accountsQuery.data?.items[0]?.initial_cash}
                items={holdingsQuery.data?.items ?? []}
                isLoading={accountsQuery.isLoading || holdingsQuery.isLoading}
                isError={accountsQuery.isError || holdingsQuery.isError}
                onRetry={() => {
                  accountsQuery.refetch();
                  holdingsQuery.refetch();
                }}
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
          />
        </TabsContent>

        <TabsContent value="logs" className="mt-0">
          <BacktestLogWorkspace report={reportQuery.data} audit={auditQuery.data} isLoading={auditQuery.isLoading} />
        </TabsContent>

        <TabsContent value="data" className="mt-0">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <MinuteDataPanel
              gapCsv={minuteGapCsv}
              importCsv={minuteImportCsv}
              gapFilePath={minuteGapFilePath}
              importFilePath={minuteImportFilePath}
              template={minuteGapTemplate}
              vendorManifest={minuteVendorManifestMutation.data}
              vendorManifestCsv={minuteVendorManifestCsv}
              onGapCsvChange={setMinuteGapCsv}
              onImportCsvChange={setMinuteImportCsv}
              onGapFilePathChange={setMinuteGapFilePath}
              onImportFilePathChange={setMinuteImportFilePath}
              onGapFileLoad={setMinuteGapCsv}
              onImportFileLoad={setMinuteImportCsv}
              onAudit={() => minuteGapAuditMutation.mutate()}
              onTemplate={() => minuteGapTemplateMutation.mutate()}
              onVendorManifest={() => minuteVendorManifestMutation.mutate()}
              onVendorManifestCsv={() => minuteVendorManifestCsvMutation.mutate()}
              onDryRun={() => minuteImportMutation.mutate(true)}
              onImport={() => minuteImportMutation.mutate(false)}
              vnpyParams={vnpyImportParams}
              onVnpyParamsChange={setVnpyImportParams}
              onImportFromVnpy={() => vnpyMinuteImportMutation.mutate()}
              onImportGapsFromVnpy={(dryRun) => vnpyGapImportMutation.mutate(dryRun)}
              onImportGapsFromTushare={(dryRun) => tushareGapImportMutation.mutate(dryRun)}
              onImportGapsFromTdx={(dryRun) => tdxGapImportMutation.mutate(dryRun)}
              onRunStrictPipeline={() => strictPipelineMutation.mutate()}
              audit={minuteGapAuditMutation.data}
              importResult={minuteImportMutation.data}
              vnpyImportResult={vnpyMinuteImportMutation.data}
              vnpyGapImportResult={vnpyGapImportMutation.data}
              tushareGapImportResult={tushareGapImportMutation.data}
              tdxGapImportResult={tdxGapImportMutation.data}
              strictPipelineResult={strictPipelineMutation.data}
              isAuditing={minuteGapAuditMutation.isPending}
              isGeneratingTemplate={minuteGapTemplateMutation.isPending}
              isGeneratingVendorManifest={minuteVendorManifestMutation.isPending || minuteVendorManifestCsvMutation.isPending}
              isImporting={minuteImportMutation.isPending}
              isImportingFromVnpy={vnpyMinuteImportMutation.isPending}
              isImportingGapsFromVnpy={vnpyGapImportMutation.isPending}
              isImportingGapsFromTushare={tushareGapImportMutation.isPending}
              isImportingGapsFromTdx={tdxGapImportMutation.isPending}
              isRunningStrictPipeline={strictPipelineMutation.isPending}
              isRunningBacktest={backtestMutation.isPending}
              error={
                minuteGapAuditMutation.error ??
                minuteGapTemplateMutation.error ??
                minuteVendorManifestMutation.error ??
                minuteVendorManifestCsvMutation.error ??
                minuteImportMutation.error ??
                vnpyMinuteImportMutation.error ??
                vnpyGapImportMutation.error ??
                tushareGapImportMutation.error ??
                tdxGapImportMutation.error ??
                strictPipelineMutation.error
              }
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
    </div>
  );
}

function RecommendationsPanel({
  isLoading,
  isError,
  error,
  items,
  tradeDate,
  runId,
  strategyVersion,
  includedBoards,
  selectedBoards,
  onSelectedBoardsChange,
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
  selectedBoards: string[];
  onSelectedBoardsChange: (boards: string[]) => void;
  status?: string;
  message?: string;
  syncedCount: number;
  onRetry: () => void;
  onRunScreen: () => void;
  isRunningScreen: boolean;
}) {
  if (isLoading) return <LoadingState rows={6} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载量化推荐失败"}
        onRetry={onRetry}
      />
    );
  }

  const activeBoards = includedBoards?.length ? includedBoards : selectedBoards;

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
          onRunScreen={onRunScreen}
          isRunningScreen={isRunningScreen}
        />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">排名</TableHead>
              <TableHead>股票</TableHead>
              <TableHead>动作</TableHead>
              <TableHead className="text-right">总分</TableHead>
              <TableHead className="text-right">MA5距离</TableHead>
              <TableHead className="text-right">20日收益</TableHead>
              <TableHead className="text-right">风控</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => {
              const reason = item.reason ?? {};
              const ma5Distance = numberValue(reason.ma5_distance_pct);
              const return20 = numberValue(reason.return_20d);
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
                        item.action === "BUY" ? "border-red-200 bg-red-50 text-rise" : "text-muted-foreground"
                      )}
                    >
                      {item.action === "BUY" ? "买入" : "观察"}
                    </span>
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">
                    {formatNumber(item.total_score, 2)}
                  </TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(ma5Distance))}>
                    {formatPct(ma5Distance)}
                  </TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(return20))}>
                    {formatPct(return20)}
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">
                    止损 {formatPct(numberValue(risk.stop_loss_pct) ? -numberValue(risk.stop_loss_pct)! * 100 : null)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function QuantBoardSelector({
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
            按当前股票池筛选
          </Button>
        )}
      </div>
    </div>
  );
}

function boardLabels(boards: string[]) {
  const labels = QUANT_BOARD_OPTIONS
    .filter((option) => boards.includes(option.value))
    .map((option) => option.label);
  return labels.length ? labels.join("、") : "主板";
}

function QuantWorkflowGuide({
  recommendationLoading,
  recommendationError,
  recommendationStatus,
  recommendationMessage,
  recommendationCount,
  backtestCount,
  holdingsCount,
  minuteAudit,
  vnpyStatus,
}: {
  recommendationLoading: boolean;
  recommendationError: boolean;
  recommendationStatus?: string;
  recommendationMessage?: string;
  recommendationCount: number;
  backtestCount: number;
  holdingsCount: number;
  minuteAudit?: MinuteGapAuditResult;
  vnpyStatus?: VnpyStatus;
}) {
  const dataState: "ready" | "warning" | "pending" =
    recommendationLoading
      ? "pending"
      : recommendationError || recommendationStatus === "unavailable"
        ? "warning"
        : "ready";
  const auditReady = minuteAudit?.status === "ready";
  const steps: Array<{
    label: string;
    status: "ready" | "warning" | "pending";
    value: string;
    note: string;
  }> = [
    {
      label: "数据",
      status: dataState,
      value: dataState === "ready" ? "可筛选" : dataState === "pending" ? "检查中" : "待配置",
      note: recommendationMessage || "需要本地股票、日线和可选财报/资金流数据。",
    },
    {
      label: "筛选",
      status: recommendationCount > 0 ? "ready" : "pending",
      value: recommendationCount > 0 ? `${recommendationCount}只` : "未生成",
      note: "运行筛选会写入量化推荐表和量化候选持仓分组。",
    },
    {
      label: "回测",
      status: backtestCount > 0 ? "ready" : "pending",
      value: backtestCount > 0 ? `${backtestCount}份` : "未运行",
      note: auditReady ? "分钟缺口已覆盖，可运行严格尾盘回测。" : "没有分钟线时只能做宽松回测或生成缺口清单。",
    },
    {
      label: "模拟",
      status: holdingsCount > 0 ? "ready" : "pending",
      value: holdingsCount > 0 ? `${holdingsCount}只` : "空仓",
      note: "自动建仓只写模拟账户，不会下实盘委托。",
    },
    {
      label: "vn.py",
      status: vnpyStatus?.status === "ready" ? "ready" : "warning",
      value: vnpyStatus?.status === "ready" ? "A股就绪" : "部分就绪",
      note: "A股实盘和实时全市场仍需要安装并配置对应 Gateway/Datafeed。",
    },
  ];

  return (
    <section className="rounded-lg border">
      <div className="grid divide-y md:grid-cols-5 md:divide-x md:divide-y-0">
        {steps.map((step) => (
          <div key={step.label} className="p-2.5" title={step.note}>
            <div className="flex items-center justify-between gap-2">
              <div className="text-sm font-medium">{step.label}</div>
              <WorkflowStatus status={step.status} />
            </div>
            <div className="mt-1 text-sm tabular-nums text-muted-foreground">{step.value}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function WorkflowStatus({ status }: { status: "ready" | "warning" | "pending" }) {
  const cls =
    status === "ready"
      ? "border-green-200 bg-green-50 text-green-700"
      : status === "warning"
        ? "border-amber-200 bg-amber-50 text-amber-700"
        : "border-gray-200 bg-gray-50 text-gray-600";
  const text = status === "ready" ? "就绪" : status === "warning" ? "需处理" : "待执行";
  return <span className={cn("rounded-md border px-2 py-0.5 text-xs", cls)}>{text}</span>;
}

function QuantEmptyState({
  status,
  message,
  onRunScreen,
  isRunningScreen,
}: {
  status?: string;
  message?: string;
  onRunScreen: () => void;
  isRunningScreen: boolean;
}) {
  const unavailable = status === "unavailable";
  return (
    <div className="p-4">
      <div className={cn("rounded-lg border p-4", unavailable ? "border-amber-200 bg-amber-50" : "bg-muted/20")}>
        <div className="flex items-start gap-3">
          {unavailable ? <AlertTriangle size={18} className="mt-0.5 text-amber-700" /> : <Database size={18} className="mt-0.5 text-muted-foreground" />}
          <div className="min-w-0 flex-1">
            <div className="font-medium">{unavailable ? "量化数据还不能读取" : "还没有量化候选"}</div>
            <div className="mt-1 text-sm text-muted-foreground">
              {message || "先运行筛选。系统会基于本地日线、相对大盘强弱、资金/财务辅助因子生成候选。"}
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button size="sm" onClick={onRunScreen} disabled={isRunningScreen || unavailable}>
                {isRunningScreen ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
                运行筛选
              </Button>
              <Button asChild size="sm" variant="outline">
                <Link to="/data">
                  <Database size={15} />
                  查看数据状态
                </Link>
              </Button>
            </div>
            {unavailable && (
              <div className="mt-3 text-xs text-amber-700">
                先配置 PostgreSQL 的 DATABASE_URL，并同步股票清单、日线和可选财报/资金流数据。
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function BacktestPanel({
  runs,
  selectedId,
  onSelect,
  params,
  onParamsChange,
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
}: {
  runs: BacktestRun[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  params: typeof DEFAULT_BACKTEST_PARAMS;
  onParamsChange: (params: typeof DEFAULT_BACKTEST_PARAMS) => void;
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
                <BacktestTradeTable trades={report.trades} />
              </section>
              <section className="space-y-4">
                {report.extended_metrics && <BacktestRealityStats metrics={report.extended_metrics} />}
                <BacktestSymbolTable rows={report.symbol_performance ?? []} compact />
              </section>
            </div>

            <Tabs defaultValue="validation" className="space-y-3">
              <TabsList className="h-auto rounded-none bg-transparent p-0">
                <TabsTrigger value="validation" className="rounded-none px-3 py-2 shadow-none">验证</TabsTrigger>
                <TabsTrigger value="trades" className="rounded-none px-3 py-2 shadow-none">交易归因</TabsTrigger>
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
                <BacktestSymbolTable rows={report.symbol_performance ?? []} />
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

function BacktestParamsForm({
  params,
  onChange,
  isRunning,
  onRun,
}: {
  params: typeof DEFAULT_BACKTEST_PARAMS;
  onChange: (params: typeof DEFAULT_BACKTEST_PARAMS) => void;
  isRunning: boolean;
  onRun: () => void;
}) {
  const setNumber = (key: keyof typeof DEFAULT_BACKTEST_PARAMS, value: string) => {
    onChange({ ...params, [key]: Number(value) });
  };

  return (
    <div className="rounded-lg border p-3">
      <div className="mb-3 border-b pb-3">
        <QuantBoardSelector
          selectedBoards={params.included_boards}
          activeBoards={params.included_boards}
          onChange={(included_boards) => onChange({ ...params, included_boards })}
          isRunning={isRunning}
        />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">开始日期</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="date"
            value={params.start}
            onChange={(event) => onChange({ ...params, start: event.target.value })}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">初始资金</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={100000}
            step={100000}
            value={params.initial_cash}
            onChange={(event) => setNumber("initial_cash", event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">样本股票</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={20}
            max={5000}
            value={params.max_symbols}
            onChange={(event) => setNumber("max_symbols", event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">最大持仓</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={1}
            max={30}
            value={params.max_positions}
            onChange={(event) => setNumber("max_positions", event.target.value)}
          />
        </label>
        <label className="text-sm">
          <span className="text-xs text-muted-foreground">最低分</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
            type="number"
            min={0}
            max={100}
            step={1}
            value={params.min_entry_score}
            onChange={(event) => setNumber("min_entry_score", event.target.value)}
          />
        </label>
        <div className="flex items-end gap-2">
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={params.strict_entry}
              onChange={(event) => onChange({ ...params, strict_entry: event.target.checked })}
            />
            严格入场
          </label>
          <Button size="sm" onClick={onRun} disabled={isRunning}>
            {isRunning ? <RefreshCw size={15} className="animate-spin" /> : <Play size={15} />}
            运行
          </Button>
        </div>
      </div>
      <details className="mt-3 border-t pt-3 text-sm">
        <summary className="cursor-pointer text-muted-foreground">高级执行设置：尾盘分钟线、强制分钟成交、MA5 偏离</summary>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={params.intraday_entry}
              onChange={(event) => onChange({ ...params, intraday_entry: event.target.checked })}
            />
            尝试尾盘分钟入场
          </label>
          <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-sm">
            <input
              type="checkbox"
              checked={params.minute_entry_required}
              onChange={(event) => onChange({ ...params, minute_entry_required: event.target.checked })}
            />
            强制分钟成交
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">尾盘开始</span>
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="time"
              value={params.tail_entry_start}
              onChange={(event) => onChange({ ...params, tail_entry_start: event.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">尾盘结束</span>
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="time"
              value={params.tail_entry_end}
              onChange={(event) => onChange({ ...params, tail_entry_end: event.target.value })}
            />
          </label>
          <label className="text-sm">
            <span className="text-xs text-muted-foreground">MA5允许偏离%</span>
            <input
              className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-sm"
              type="number"
              min={0.1}
              max={5}
              step={0.1}
              value={params.tail_entry_ma5_tolerance_pct}
              onChange={(event) => setNumber("tail_entry_ma5_tolerance_pct", event.target.value)}
            />
          </label>
        </div>
      </details>
    </div>
  );
}

function BacktestSummary({
  report,
  audit,
}: {
  report: Awaited<ReturnType<typeof fetchBacktestReport>>;
  audit?: Awaited<ReturnType<typeof fetchBacktestAudit>>;
}) {
  return (
    <div className="space-y-4">
      <BacktestTrustPanel report={report} />
      <BacktestMethodPanel report={report} audit={audit} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {report.summary_rows.slice(1, 9).map((row) => (
          <div key={row.key} className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{row.label}</div>
            <div className={cn("mt-1 text-lg font-semibold tabular-nums", metricColor(row.key, row.value))}>
              {formatMetric(row.key, row.value)}
            </div>
          </div>
        ))}
      </div>
      <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
        <InfoCell label="样本股票" value={`${report.sample.symbol_count}只`} />
        <InfoCell label="有效样本" value={`${report.sample.eligible_symbol_count ?? report.sample.symbol_count}只`} />
        <InfoCell label="交易日" value={`${report.sample.equity_days}天`} />
        <InfoCell label="区间" value={`${report.start_date} 至 ${report.end_date}`} />
        <InfoCell label="闭仓笔数" value={`${report.closed_trade_count ?? report.metrics.trade_count ?? 0}笔`} />
      </div>
    </div>
  );
}

function BacktestTrustPanel({
  report,
}: {
  report: Awaited<ReturnType<typeof fetchBacktestReport>>;
}) {
  const verdict = backtestTrustVerdict(report);
  return (
    <div
      className={cn(
        "rounded-lg border p-3 text-sm",
        verdict.status === "invalid" && "border-red-200 bg-red-50",
        verdict.status === "warning" && "border-amber-200 bg-amber-50",
        verdict.status === "pass" && "border-green-200 bg-green-50"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 font-medium">
            {verdict.status === "pass" ? <ShieldCheck size={15} /> : <AlertTriangle size={15} />}
            {verdict.title}
          </div>
          <div className="mt-1 text-xs text-muted-foreground">{verdict.description}</div>
        </div>
        <span className={cn("rounded-md border bg-background px-2 py-1 text-xs", verdict.status === "invalid" ? "text-fall" : verdict.status === "pass" ? "text-rise" : "text-amber-700")}>
          {verdict.label}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <InfoCell label="撮合版本" value={report.strategy_version} />
        <InfoCell label="买入方式" value={verdict.entryMode} />
        <InfoCell label="尾盘成交占比" value={formatPct(report.execution_quality?.minute_tail_entry_ratio)} />
        <InfoCell label="开盘回退占比" value={formatPct(report.execution_quality?.daily_open_fallback_ratio)} />
        <InfoCell label="闭仓笔数" value={`${report.closed_trade_count ?? report.metrics.trade_count ?? 0}笔`} />
      </div>

      {verdict.items.length > 0 && (
        <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
          {verdict.items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function BacktestMethodPanel({
  report,
  audit,
}: {
  report: Awaited<ReturnType<typeof fetchBacktestReport>>;
  audit?: Awaited<ReturnType<typeof fetchBacktestAudit>>;
}) {
  const method = report.method ?? audit?.method;
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 font-medium">
          <FileText size={15} />
          回测方法
        </div>
        <span className="text-xs text-muted-foreground">
          {report.strategy_id} / {report.strategy_version}
        </span>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        <InfoCell label="候选生成" value={method?.signal_timing ?? report.assumptions.candidate_generation} />
        <InfoCell label="执行时点" value={method?.execution_timing ?? report.assumptions.execution} />
        <InfoCell label="股票池" value={method?.universe ?? `${report.sample.symbol_count} 只样本`} />
        <InfoCell label="候选口径" value={method?.candidate_policy ?? "历史逐日动态候选"} />
      </div>
      {audit?.note && <div className="mt-3 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">{audit.note}</div>}
    </div>
  );
}

function BacktestTradeTable({ trades }: { trades: Awaited<ReturnType<typeof fetchBacktestReport>>["trades"] }) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">最近买卖点</div>
      </div>
      {trades.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">当前回测没有成交记录。</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>日期</TableHead>
              <TableHead>股票</TableHead>
              <TableHead>方向</TableHead>
              <TableHead className="text-right">价格</TableHead>
              <TableHead className="text-right">数量</TableHead>
              <TableHead className="text-right">盈亏</TableHead>
              <TableHead>原因</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.slice(0, 12).map((trade, index) => (
              <TableRow key={`${trade.trade_date}-${trade.vt_symbol}-${index}`}>
                <TableCell className="tabular-nums">{trade.trade_date}</TableCell>
                <TableCell>
                  <StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} board={trade.board} boardLabel={trade.board_label} />
                </TableCell>
                <TableCell>{trade.side === "BUY" ? "买入" : "卖出"}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(trade.price)}</TableCell>
                <TableCell className="text-right tabular-nums">{trade.volume.toLocaleString()}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(trade.pnl))}>
                  {trade.pnl == null ? "--" : formatAmount(trade.pnl)}
                </TableCell>
                <TableCell className="text-muted-foreground">{trade.reason ?? "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function BacktestLogWorkspace({
  report,
  audit,
  isLoading,
}: {
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  audit?: Awaited<ReturnType<typeof fetchBacktestAudit>>;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={5} />;
  if (!report && !audit) {
    return <EmptyState message="暂无策略日志" description="先运行或选择一份回测，再检查每天的订单、成交和拒绝原因。" />;
  }

  return (
    <section className="space-y-4">
      <div className="rounded-lg border p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="text-sm font-semibold">策略日志</h2>
          {report && (
            <div className="grid grid-cols-3 gap-4 text-sm">
              <InfoCell label="交易行数" value={`${report.trade_count.toLocaleString()}行`} />
              <InfoCell label="返回明细" value={`${report.returned_trade_count ?? report.trades.length}行`} />
              <InfoCell label="闭仓笔数" value={`${report.closed_trade_count ?? report.metrics.trade_count ?? 0}笔`} />
            </div>
          )}
        </div>
      </div>
      {audit?.order_summary && <BacktestOrderStatsPanel stats={audit.order_summary} />}
      {audit && <BacktestAuditPanel audit={audit} />}
    </section>
  );
}

function BacktestAuditPanel({
  audit,
}: {
  audit: Awaited<ReturnType<typeof fetchBacktestAudit>>;
}) {
  const events = audit.events ?? [];
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">订单审计</div>
        <span className="text-xs text-muted-foreground">
          订单 {audit.orders.length} · 成交 {audit.trades.length}
        </span>
      </div>
      {events.length === 0 ? (
        <div className="p-3 text-sm text-muted-foreground">
          当前报告没有订单事件。若是单股回测，通常表示该股在区间内没有满足入场分或严格入场条件。
        </div>
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
            {events.slice(0, 16).map((event, index) => (
              <TableRow key={`${event.trade_date}-${event.vt_symbol}-${event.event_type}-${index}`}>
                <TableCell className="tabular-nums">{event.trade_date}</TableCell>
                <TableCell>
                  <StockIdentityLink name={event.name} vtSymbol={event.vt_symbol} board={event.board} boardLabel={event.board_label} />
                </TableCell>
                <TableCell>{eventLabel(event)}</TableCell>
                <TableCell className="text-muted-foreground">{executionModeLabel(event.execution_mode)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatPrice(event.price)}</TableCell>
                <TableCell className="max-w-[520px] text-muted-foreground">{event.message ?? event.reason ?? "--"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}

function BacktestBenchmarkTable({
  benchmarks,
}: {
  benchmarks: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["benchmark"]>["benchmarks"];
}) {
  if (benchmarks.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">基准对比</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>基准</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">策略收益</TableHead>
            <TableHead className="text-right">超额收益</TableHead>
            <TableHead className="text-right">基准回撤</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {benchmarks.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <div className="font-medium">{row.name}</div>
                {row.reason && <div className="text-xs text-muted-foreground">{row.reason}</div>}
              </TableCell>
              <TableCell>{row.status === "ready" ? "可用" : "缺失"}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.strategy_return_pct))}>
                {formatPct(row.strategy_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.excess_return_pct))}>
                {formatPct(row.excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BacktestPeriodTable({
  analysis,
}: {
  analysis: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["period_analysis"]>;
}) {
  if (analysis.periods.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">样本内 / 样本外</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分段</TableHead>
            <TableHead>区间</TableHead>
            <TableHead className="text-right">策略收益</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">超额收益</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">胜率</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.periods.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-muted-foreground">
                {row.start_date} 至 {row.end_date}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.benchmark_return_pct))}>
                {formatPct(row.benchmark_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.excess_return_pct))}>
                {formatPct(row.excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {analysis.note && <div className="border-t px-3 py-2 text-xs text-muted-foreground">{analysis.note}</div>}
    </div>
  );
}

function BacktestRegimeTable({
  analysis,
}: {
  analysis: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["regime_analysis"]>;
}) {
  if (analysis.periods.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">市场环境分段</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>环境</TableHead>
            <TableHead className="text-right">窗口</TableHead>
            <TableHead className="text-right">策略均值</TableHead>
            <TableHead className="text-right">基准均值</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.periods.map((row) => (
            <TableRow key={row.regime}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.window_count}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_strategy_return_pct))}>
                {formatPct(row.avg_strategy_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_benchmark_return_pct))}>
                {formatPct(row.avg_benchmark_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {analysis.note && <div className="border-t px-3 py-2 text-xs text-muted-foreground">{analysis.note}</div>}
    </div>
  );
}

function BacktestRobustnessPanel({
  checks,
}: {
  checks: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["robustness_checks"]>;
}) {
  return (
    <div className="space-y-3">
      <div className="overflow-hidden rounded-lg border">
        <div className="border-b px-3 py-2 text-sm font-medium">反过拟合检查</div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>检查项</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">数值</TableHead>
              <TableHead>结论</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.diagnostics.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell>{robustnessStatus(row.status)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                  {formatRobustnessValue(row.value, row.value_type)}
                </TableCell>
                <TableCell className="text-muted-foreground">{row.message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {checks.yearly_periods.length > 0 && <BacktestYearlyTable rows={checks.yearly_periods} />}

      <div className="overflow-hidden rounded-lg border">
        <div className="border-b px-3 py-2 text-sm font-medium">成本压力测试</div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>情景</TableHead>
              <TableHead className="text-right">额外成本</TableHead>
              <TableHead className="text-right">收益率</TableHead>
              <TableHead className="text-right">收益变化</TableHead>
              <TableHead className="text-right">期末权益</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {checks.cost_stress.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(row.extra_cost)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                  {formatPct(row.total_return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_delta_pct))}>
                  {formatPct(row.return_delta_pct)}
                </TableCell>
                <TableCell className="text-right tabular-nums">{formatAmount(row.final_equity)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {checks.random_baseline.status === "ready" && (
        <div className="rounded-lg border p-3 text-sm">
          <div className="font-medium">随机样本基准</div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            <InfoCell label="随机次数" value={checks.random_baseline.run_count} />
            <InfoCell label="每组股票" value={checks.random_baseline.sample_size} />
            <InfoCell label="平均收益" value={formatPct(checks.random_baseline.return_avg_pct)} />
            <InfoCell label="中位收益" value={formatPct(checks.random_baseline.return_median_pct)} />
            <InfoCell label="平均回撤" value={formatPct(checks.random_baseline.max_drawdown_avg_pct)} />
          </div>
        </div>
      )}
    </div>
  );
}

function BacktestYearlyTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["robustness_checks"]>["yearly_periods"];
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">年度分段</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>年份</TableHead>
            <TableHead className="text-right">策略收益</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">超额收益</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">胜率</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.benchmark_return_pct))}>
                {formatPct(row.benchmark_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.excess_return_pct))}>
                {formatPct(row.excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BacktestValidationGridPanel({
  backtestId,
  grid,
  isLoading,
  onRun,
}: {
  backtestId: number;
  grid?: Awaited<ReturnType<typeof fetchBacktestValidationGrid>>;
  isLoading: boolean;
  onRun: () => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">参数网格验证</div>
          <div className="text-xs text-muted-foreground">重新撮合 54 组关键参数，检查默认参数是否过拟合。</div>
        </div>
        <div className="flex gap-2">
          {grid?.status === "ready" && (
            <Button asChild variant="outline" size="sm">
              <a href={backtestValidationGridCsvUrl(backtestId, 54)} download>
                <Download size={15} />
                导出网格
              </a>
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onRun} disabled={isLoading}>
            {isLoading ? <RefreshCw size={15} className="animate-spin" /> : <BarChart3 size={15} />}
            运行网格
          </Button>
        </div>
      </div>

      {!grid ? (
        <div className="p-3 text-sm text-muted-foreground">点击运行后，会用同一股票池和交易区间重跑不同入场分、止损、止盈、严格入场组合。</div>
      ) : grid.status !== "ready" ? (
        <div className="p-3 text-sm text-muted-foreground">网格验证状态：{grid.status}</div>
      ) : (
        <div className="space-y-3 p-3">
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
            <InfoCell label="组合数量" value={`${grid.summary.variant_count}组`} />
            <InfoCell label="盈利占比" value={formatPct(grid.summary.positive_ratio)} />
            <InfoCell label="样本外盈利" value={formatPct(grid.summary.out_sample_positive_ratio)} />
            <InfoCell label="跑赢等权" value={formatPct(grid.summary.sample_excess_positive_ratio)} />
            <InfoCell label="当前样本外排名" value={grid.summary.base_out_sample_rank ? `${grid.summary.base_out_sample_rank}/${grid.summary.variant_count}` : "--"} />
          </div>

          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>检查项</TableHead>
                <TableHead>状态</TableHead>
                <TableHead className="text-right">数值</TableHead>
                <TableHead>结论</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {grid.diagnostics.map((row) => (
                <TableRow key={row.id}>
                  <TableCell className="font-medium">{row.label}</TableCell>
                  <TableCell>{robustnessStatus(row.status)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                    {formatRobustnessValue(row.value, row.value_type)}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{row.message}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {grid.walk_forward && <BacktestWalkForwardPanel analysis={grid.walk_forward} />}

          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>组合</TableHead>
                  <TableHead className="text-right">入场分</TableHead>
                  <TableHead className="text-right">止损</TableHead>
                  <TableHead className="text-right">止盈</TableHead>
                  <TableHead>严格</TableHead>
                  <TableHead className="text-right">总收益</TableHead>
                  <TableHead className="text-right">样本外</TableHead>
                  <TableHead className="text-right">等权超额</TableHead>
                  <TableHead className="text-right">回撤</TableHead>
                  <TableHead className="text-right">交易</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {grid.top_variants.slice(0, 10).map((row) => (
                  <TableRow key={row.variant_id}>
                    <TableCell className="font-medium">
                      #{row.variant_id}{row.is_base_params ? " 当前" : ""}
                    </TableCell>
                    <TableCell className="text-right tabular-nums">{formatNumber(row.min_entry_score, 0)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPct(row.stop_loss_pct * 100)}</TableCell>
                    <TableCell className="text-right tabular-nums">{formatPct(row.take_profit_pct * 100)}</TableCell>
                    <TableCell>{row.strict_entry ? "是" : "否"}</TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                      {formatPct(row.total_return_pct)}
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.out_sample_return_pct))}>
                      {formatPct(row.out_sample_return_pct)}
                    </TableCell>
                    <TableCell className={cn("text-right tabular-nums", priceColorClass(row.sample_equal_weight_excess_pct))}>
                      {formatPct(row.sample_equal_weight_excess_pct)}
                    </TableCell>
                    <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
                    <TableCell className="text-right tabular-nums">{row.trade_count ?? "--"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {grid.limitations.length > 0 && (
            <div className="border-t pt-2 text-xs text-muted-foreground">{grid.limitations[0]}</div>
          )}
        </div>
      )}
    </div>
  );
}

function BacktestWalkForwardPanel({
  analysis,
}: {
  analysis: NonNullable<Awaited<ReturnType<typeof fetchBacktestValidationGrid>>["walk_forward"]>;
}) {
  if (analysis.status !== "ready" || !analysis.summary) {
    return (
      <div className="rounded-lg border p-3 text-sm text-muted-foreground">
        Walk-forward 状态：{analysis.status}
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div>
        <div className="text-sm font-medium">Walk-forward 验证</div>
        <div className="text-xs text-muted-foreground">
          训练 {analysis.train_days} 日选参数，随后 {analysis.test_days} 日只验证未来窗口。
        </div>
      </div>

      <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
        <InfoCell label="折叠数量" value={`${analysis.summary.fold_count}个`} />
        <InfoCell label="测试盈利占比" value={formatPct(analysis.summary.positive_test_ratio)} />
        <InfoCell label="测试超额占比" value={formatPct(analysis.summary.excess_positive_ratio)} />
        <InfoCell label="测试平均收益" value={formatPct(analysis.summary.test_return_avg_pct)} />
        <InfoCell label="测试平均超额" value={formatPct(analysis.summary.test_excess_avg_pct)} />
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>检查项</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">数值</TableHead>
            <TableHead>结论</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {analysis.diagnostics.map((row) => (
            <TableRow key={row.id}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell>{robustnessStatus(row.status)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                {formatRobustnessValue(row.value, row.value_type)}
              </TableCell>
              <TableCell className="text-muted-foreground">{row.message}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>折叠</TableHead>
              <TableHead>训练区间</TableHead>
              <TableHead>测试区间</TableHead>
              <TableHead className="text-right">参数</TableHead>
              <TableHead className="text-right">训练收益</TableHead>
              <TableHead className="text-right">测试收益</TableHead>
              <TableHead className="text-right">测试超额</TableHead>
              <TableHead className="text-right">测试回撤</TableHead>
              <TableHead className="text-right">测试交易</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {analysis.folds.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">#{row.selected_variant_id}</TableCell>
                <TableCell className="text-muted-foreground">
                  {row.train_start_date} 至 {row.train_end_date}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {row.test_start_date} 至 {row.test_end_date}
                </TableCell>
                <TableCell className="text-right text-xs tabular-nums">
                  {formatNumber(row.min_entry_score, 0)} / {formatPct(row.stop_loss_pct * 100)} / {formatPct(row.take_profit_pct * 100)} / {row.strict_entry ? "严" : "宽"}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.train_return_pct))}>
                  {formatPct(row.train_return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.test_return_pct))}>
                  {formatPct(row.test_return_pct)}
                </TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.test_excess_return_pct))}>
                  {formatPct(row.test_excess_return_pct)}
                </TableCell>
                <TableCell className="text-right tabular-nums text-fall">{formatPct(row.test_max_drawdown_pct)}</TableCell>
                <TableCell className="text-right tabular-nums">{row.test_trade_count}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function BacktestRealityStats({
  metrics,
}: {
  metrics: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["extended_metrics"]>;
}) {
  const executionModes = metrics.execution_modes ?? {};
  return (
    <div className="grid gap-2 border-t pt-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <InfoCell label="平均持仓" value={`${formatNumber(metrics.average_holding_days, 1)}天`} />
      <InfoCell label="持仓中位数" value={`${formatNumber(metrics.median_holding_days, 1)}天`} />
      <InfoCell label="成交额" value={formatAmount(metrics.traded_amount)} />
      <InfoCell label="换手估算" value={formatPct(metrics.turnover_pct)} />
      <InfoCell label="平均仓位" value={formatPct(metrics.average_exposure_pct)} />
      <InfoCell label="最大持仓数" value={`${metrics.max_position_count}只`} />
      <InfoCell label="成交订单" value={`${metrics.filled_order_count}笔`} />
      <InfoCell label="未成交订单" value={`${metrics.rejected_order_count}笔`} />
      <InfoCell label="分钟尾盘买入" value={`${executionModes.minute_tail_ma5 ?? 0}笔`} />
      <InfoCell label="开盘回退买入" value={`${executionModes.daily_next_open_fallback ?? 0}笔`} />
    </div>
  );
}

function BacktestExecutionQualityPanel({
  quality,
}: {
  quality: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["execution_quality"]>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">成交真实性检查</div>
        <span
          className={cn(
            "rounded-md border px-2 py-1 text-xs",
            quality.status === "pass" ? "border-green-200 bg-green-50 text-rise" : "border-amber-200 bg-amber-50 text-amber-700"
          )}
        >
          {quality.status === "pass" ? "通过" : "有缺口"}
        </span>
      </div>
      <div className="space-y-3 p-3">
        <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
          <InfoCell label="买入笔数" value={`${quality.buy_count}笔`} />
          <InfoCell label="尾盘分钟成交" value={`${quality.minute_tail_entry_count}笔`} />
          <InfoCell label="尾盘成交占比" value={formatPct(quality.minute_tail_entry_ratio)} />
          <InfoCell label="开盘回退占比" value={formatPct(quality.daily_open_fallback_ratio)} />
          <InfoCell label="分钟线条数" value={quality.minute_bar_count.toLocaleString()} />
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>检查项</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="text-right">数值</TableHead>
              <TableHead>结论</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {quality.diagnostics.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell>{robustnessStatus(row.status)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.value))}>
                  {formatRobustnessValue(row.value, row.value_type)}
                </TableCell>
                <TableCell className="text-muted-foreground">{row.message}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function BacktestMonthlyTable({ rows }: { rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["monthly_returns"]> }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">月度收益</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>月份</TableHead>
            <TableHead>区间</TableHead>
            <TableHead className="text-right">月收益</TableHead>
            <TableHead className="text-right">月内回撤</TableHead>
            <TableHead className="text-right">期末权益</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.month}>
              <TableCell className="font-medium tabular-nums">{row.month}</TableCell>
              <TableCell className="text-muted-foreground">
                {row.start_date ?? "--"} 至 {row.end_date ?? "--"}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatAmount(row.end_equity)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BacktestSymbolTable({
  rows,
  compact = false,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["symbol_performance"]>;
  compact?: boolean;
}) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">个股贡献</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票</TableHead>
            <TableHead className="text-right">闭仓</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">收益</TableHead>
            <TableHead className="text-right">投入回报</TableHead>
            <TableHead className="text-right">最差单笔</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, compact ? 6 : 12).map((row) => (
            <TableRow key={row.vt_symbol}>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.trade_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatPct(row.win_rate * 100)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.worst_trade))}>
                {formatAmount(row.worst_trade)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {compact && rows.length > 6 && (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground">更多个股贡献在“交易归因”页签查看。</div>
      )}
    </div>
  );
}

function BacktestWorstTrades({ rows }: { rows: BacktestClosedTrade[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">最差交易</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票</TableHead>
            <TableHead>买入/卖出</TableHead>
            <TableHead className="text-right">持仓</TableHead>
            <TableHead className="text-right">收益率</TableHead>
            <TableHead className="text-right">盈亏</TableHead>
            <TableHead>退出原因</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 10).map((row, index) => (
            <TableRow key={`${row.vt_symbol}-${row.exit_date}-${index}`}>
              <TableCell>
                <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
              </TableCell>
              <TableCell className="text-muted-foreground">
                {row.entry_date ?? "--"} / {row.exit_date ?? "--"}
              </TableCell>
              <TableCell className="text-right tabular-nums">{row.holding_days ?? "--"}天</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.pnl))}>
                {formatAmount(row.pnl)}
              </TableCell>
              <TableCell className="text-muted-foreground">{row.exit_reason ?? "--"}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BacktestOrderStatsPanel({
  stats,
}: {
  stats: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["order_stats"]>;
}) {
  const reasonRows = Object.entries(stats.by_reason).sort((a, b) => b[1] - a[1]);
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="font-medium">成交约束</div>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        <InfoCell label="订单总数" value={`${stats.total}笔`} />
        <InfoCell label="已成交" value={`${stats.by_status.filled ?? 0}笔`} />
        <InfoCell label="未成交" value={`${stats.by_status.rejected ?? 0}笔`} />
      </div>
      {reasonRows.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {reasonRows.map(([reason, count]) => (
            <span key={reason} className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
              {reason}: {count}
            </span>
          ))}
        </div>
      )}
      {stats.rejected_examples.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>股票</TableHead>
                <TableHead>方向</TableHead>
                <TableHead>原因</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {stats.rejected_examples.slice(0, 5).map((row, index) => (
                <TableRow key={`${row.trade_date}-${row.vt_symbol}-${index}`}>
                  <TableCell className="tabular-nums">{row.trade_date}</TableCell>
                  <TableCell>
                    <StockIdentityLink name={row.name} vtSymbol={row.vt_symbol} board={row.board} boardLabel={row.board_label} />
                  </TableCell>
                  <TableCell>{row.side === "BUY" ? "买入" : "卖出"}</TableCell>
                  <TableCell className="text-muted-foreground">{row.reason ?? "--"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}

function BacktestDataQuality({
  data,
  limitations,
}: {
  data?: Awaited<ReturnType<typeof fetchBacktestReport>>["data_quality"];
  limitations: string[];
}) {
  const tableNames = ["stocks", "stock_daily_bars", "stock_financial_reports", "sector_period_scores", "stock_fund_flows", "stock_hot_ranks", "stock_lhb_records"];
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="font-medium">数据质量和限制</div>
      {data && (
        <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {tableNames.map((name) => {
            const item = data[name];
            const count = item && !Array.isArray(item) ? item.count : undefined;
            return <InfoCell key={name} label={name} value={count?.toLocaleString()} />;
          })}
        </div>
      )}
      <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
        {[...(data?.limitations ?? []), ...limitations].map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function HoldingsPanel({
  accountCount,
  cash,
  initialCash,
  items,
  isLoading,
  isError,
  onRetry,
}: {
  accountCount: number;
  cash?: number;
  initialCash?: number;
  items: Array<{
    vt_symbol: string;
    name?: string | null;
    board?: string | null;
    board_label?: string | null;
    volume: number;
    cost_price: number;
    last_price?: number | null;
    market_value?: number | null;
    floating_pnl?: number | null;
    floating_pnl_pct?: number | null;
    source: string;
    reason?: string | null;
    stop_loss_price?: number | null;
    take_profit_price?: number | null;
    trailing_stop_price?: number | null;
    last_buy_time?: string | null;
    last_buy_price?: number | null;
    last_buy_volume?: number | null;
    last_buy_reason?: string | null;
    last_sell_time?: string | null;
    last_sell_price?: number | null;
    last_sell_pnl?: number | null;
    recommendation_id?: number | null;
  }>;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const equity = useMemo(() => (cash ?? 0) + items.reduce((sum, item) => sum + (item.market_value ?? 0), 0), [cash, items]);

  if (isLoading) return <LoadingState rows={4} />;
  if (isError) return <ErrorState message="加载模拟持仓失败" onRetry={onRetry} />;

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Briefcase size={16} />
          <h2 className="text-sm font-semibold">模拟持仓</h2>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground">{accountCount} 个账户</span>
          <Button asChild size="sm" variant="outline">
            <Link to="/portfolio">打开持仓</Link>
          </Button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 border-b p-4 text-sm">
        <InfoCell label="现金" value={formatAmount(cash)} />
        <InfoCell label="权益" value={formatAmount(equity)} />
        <InfoCell label="收益" value={formatPct(initialCash ? (equity / initialCash - 1) * 100 : null)} />
      </div>
      {items.length === 0 ? (
        <div className="p-4">
          <EmptyState message="暂无模拟持仓" description="可从量化推荐自动生成模拟买入。" />
        </div>
      ) : (
        <div className="divide-y">
          {items.map((item) => (
            <div key={item.vt_symbol} className="px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <StockIdentityLink name={item.name} vtSymbol={item.vt_symbol} board={item.board} boardLabel={item.board_label} />
                  <div className="text-xs text-muted-foreground">{item.source}</div>
                </div>
                <div className={cn("text-right text-sm font-medium tabular-nums", priceColorClass(item.floating_pnl_pct))}>
                  {formatPct(item.floating_pnl_pct)}
                </div>
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                <span>成本 {formatPrice(item.cost_price)}</span>
                <span>现价 {formatPrice(item.last_price)}</span>
                <span>数量 {item.volume.toLocaleString()}</span>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                <span>买入 {formatTime(item.last_buy_time)} · {formatPrice(item.last_buy_price)}</span>
                <span>止损/止盈 {formatPrice(item.stop_loss_price)} / {formatPrice(item.take_profit_price)}</span>
                <span>跟踪止损 {formatPrice(item.trailing_stop_price)}</span>
                <span>推荐 #{item.recommendation_id ?? "--"}</span>
              </div>
              {(item.last_buy_reason || item.reason || item.last_sell_time) && (
                <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                  {(item.last_buy_reason || item.reason) && (
                    <div className="line-clamp-2">买入依据: {item.last_buy_reason || item.reason}</div>
                  )}
                  {item.last_sell_time && (
                    <div>
                      最近卖出: {formatTime(item.last_sell_time)} · {formatPrice(item.last_sell_price)} · 盈亏{" "}
                      <span className={priceColorClass(item.last_sell_pnl)}>{formatAmount(item.last_sell_pnl)}</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function MinuteDataPanel({
  gapCsv,
  importCsv,
  gapFilePath,
  importFilePath,
  template,
  vendorManifest,
  vendorManifestCsv,
  audit,
  importResult,
  vnpyImportResult,
  vnpyGapImportResult,
  tushareGapImportResult,
  tdxGapImportResult,
  strictPipelineResult,
  vnpyParams,
  isAuditing,
  isGeneratingTemplate,
  isGeneratingVendorManifest,
  isImporting,
  isImportingFromVnpy,
  isImportingGapsFromVnpy,
  isImportingGapsFromTushare,
  isImportingGapsFromTdx,
  isRunningStrictPipeline,
  isRunningBacktest,
  error,
  onGapCsvChange,
  onImportCsvChange,
  onGapFilePathChange,
  onImportFilePathChange,
  onGapFileLoad,
  onImportFileLoad,
  onAudit,
  onTemplate,
  onVendorManifest,
  onVendorManifestCsv,
  onDryRun,
  onImport,
  onVnpyParamsChange,
  onImportFromVnpy,
  onImportGapsFromVnpy,
  onImportGapsFromTushare,
  onImportGapsFromTdx,
  onRunStrictPipeline,
}: {
  gapCsv: string;
  importCsv: string;
  gapFilePath: string;
  importFilePath: string;
  template: string;
  vendorManifest?: MinuteGapVendorManifest;
  vendorManifestCsv: string;
  audit?: MinuteGapAuditResult;
  importResult?: MinuteBarsImportResult;
  vnpyImportResult?: Awaited<ReturnType<typeof importVnpyMinuteBars>>;
  vnpyGapImportResult?: Awaited<ReturnType<typeof importVnpyMinuteBarsForGaps>>;
  tushareGapImportResult?: MinuteGapProviderImportResult;
  tdxGapImportResult?: MinuteGapProviderImportResult;
  strictPipelineResult?: Awaited<ReturnType<typeof runStrictMinuteBacktestPipeline>>;
  vnpyParams: {
    vt_symbol: string;
    start: string;
    end: string;
    dry_run: boolean;
  };
  isAuditing: boolean;
  isGeneratingTemplate: boolean;
  isGeneratingVendorManifest: boolean;
  isImporting: boolean;
  isImportingFromVnpy: boolean;
  isImportingGapsFromVnpy: boolean;
  isImportingGapsFromTushare: boolean;
  isImportingGapsFromTdx: boolean;
  isRunningStrictPipeline: boolean;
  isRunningBacktest: boolean;
  error: unknown;
  onGapCsvChange: (value: string) => void;
  onImportCsvChange: (value: string) => void;
  onGapFilePathChange: (value: string) => void;
  onImportFilePathChange: (value: string) => void;
  onGapFileLoad: (value: string) => void;
  onImportFileLoad: (value: string) => void;
  onAudit: () => void;
  onTemplate: () => void;
  onVendorManifest: () => void;
  onVendorManifestCsv: () => void;
  onDryRun: () => void;
  onImport: () => void;
  onVnpyParamsChange: (value: { vt_symbol: string; start: string; end: string; dry_run: boolean }) => void;
  onImportFromVnpy: () => void;
  onImportGapsFromVnpy: (dryRun: boolean) => void;
  onImportGapsFromTushare: (dryRun: boolean) => void;
  onImportGapsFromTdx: (dryRun: boolean) => void;
  onRunStrictPipeline: () => void;
}) {
  const [fileError, setFileError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const canAudit = Boolean(gapCsv.trim() || gapFilePath.trim());
  const canImport = Boolean(importCsv.trim() || importFilePath.trim());
  const loadCsvFile = (file: File | undefined, onLoad: (value: string) => void) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setFileError(null);
      onLoad(String(reader.result ?? ""));
    };
    reader.onerror = () => setFileError("读取 CSV 文件失败");
    reader.readAsText(file, "utf-8");
  };

  return (
    <section className="rounded-lg border p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ClipboardCheck size={16} />
          <h2 className="text-sm font-semibold">严格分钟补数</h2>
        </div>
        <div className="flex items-center gap-2">
        {audit && (
          <span
            className={cn(
              "rounded-md border px-2 py-1 text-xs",
              audit.status === "ready" ? "border-green-200 bg-green-50 text-rise" : "border-amber-200 bg-amber-50 text-amber-700"
            )}
          >
            {audit.status === "ready" ? "覆盖完成" : "仍有缺口"}
          </span>
        )}
          <Button size="sm" variant="outline" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "收起" : "展开"}
          </Button>
        </div>
      </div>
      {!expanded && (
        <div className="mt-3 grid grid-cols-2 gap-2 border-t pt-3">
          <InfoCell label="缺口状态" value={audit?.status ?? "未审计"} />
          <InfoCell label="覆盖率" value={formatPct(audit?.coverage_pct)} />
          <InfoCell label="缺口" value={audit?.gap_count == null ? "--" : `${audit.gap_count}个`} />
          <InfoCell label="缺失" value={audit?.missing_count == null ? "--" : `${audit.missing_count}个`} />
        </div>
      )}

      {expanded && (

      <div className="mt-3 space-y-3">
        <MinuteStep
          number="1"
          title="先拿到缺口清单"
          description="严格尾盘回测会记录哪些股票在 D+1 尾盘缺少 1 分钟线。这里先导入或填写这份缺口 CSV。"
        />
        <label className="block">
          <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            严格尾盘缺口 CSV
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-foreground">
              <FileUp size={13} />
              读文件
              <input
                className="hidden"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => loadCsvFile(event.target.files?.[0], onGapFileLoad)}
              />
            </span>
          </span>
          <textarea
            className="mt-1 min-h-24 w-full resize-y rounded-md border bg-background p-2 font-mono text-xs"
            value={gapCsv}
            onChange={(event) => onGapCsvChange(event.target.value)}
            placeholder="trade_date,vt_symbol,reference_date,window,ma5..."
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">服务器缺口文件路径</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-xs"
            value={gapFilePath}
            onChange={(event) => onGapFilePathChange(event.target.value)}
            placeholder="memory/06_backtests/alphaagent_minute_gap_backtest_10_2025-10-14_2026-06-11.csv"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={onAudit} disabled={!canAudit || isAuditing}>
            {isAuditing ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
            审计缺口
          </Button>
          <Button size="sm" variant="outline" onClick={onTemplate} disabled={!gapCsv.trim() || isGeneratingTemplate}>
            {isGeneratingTemplate ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
            生成模板
          </Button>
          <Button size="sm" variant="outline" onClick={onVendorManifest} disabled={!canAudit || isGeneratingVendorManifest}>
            {isGeneratingVendorManifest ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
            预览补数清单
          </Button>
          <Button size="sm" variant="outline" onClick={onVendorManifestCsv} disabled={!canAudit || isGeneratingVendorManifest}>
            {isGeneratingVendorManifest ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
            导出补数清单
          </Button>
        </div>

        {vendorManifest && (
          <div className="grid grid-cols-2 gap-2 rounded-md border p-3 text-xs">
            <InfoCell label="补数请求" value={`${vendorManifest.request_count ?? 0}行`} />
            <InfoCell label="股票" value={`${vendorManifest.symbol_count ?? 0}只`} />
            <InfoCell label="交易日" value={`${vendorManifest.date_count ?? 0}天`} />
            <InfoCell label="窗口" value={vendorManifest.tail_entry_window ?? "--"} />
            <InfoCell label="开始" value={vendorManifest.start_date ?? "--"} />
            <InfoCell label="结束" value={vendorManifest.end_date ?? "--"} />
          </div>
        )}

        {vendorManifestCsv && (
          <label className="block">
            <span className="text-xs text-muted-foreground">供应商补数清单 CSV</span>
            <textarea className="mt-1 min-h-20 w-full resize-y rounded-md border bg-muted/30 p-2 font-mono text-xs" readOnly value={vendorManifestCsv} />
          </label>
        )}

        {audit && (
          <div className="grid grid-cols-2 gap-2 border-t pt-3">
            <InfoCell label="缺口" value={`${audit.gap_count ?? 0}个`} />
            <InfoCell label="已覆盖" value={`${audit.covered_count ?? 0}个`} />
            <InfoCell label="缺失" value={`${audit.missing_count ?? 0}个`} />
            <InfoCell label="覆盖率" value={formatPct(audit.coverage_pct)} />
            <InfoCell label="股票数" value={`${audit.symbol_count ?? 0}只`} />
            <InfoCell label="交易日" value={`${audit.date_count ?? 0}天`} />
          </div>
        )}
        {audit && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={onRunStrictPipeline} disabled={!canAudit || isRunningStrictPipeline || isRunningBacktest}>
              {isRunningStrictPipeline ? <RefreshCw size={15} className="animate-spin" /> : <ShieldCheck size={15} />}
              审计并运行严格回测
            </Button>
          </div>
        )}
        {strictPipelineResult && (
          <div
            className={cn(
              "rounded-md border p-3 text-xs",
              strictPipelineResult.status === "ready" ? "border-green-200 bg-green-50 text-rise" : "border-amber-200 bg-amber-50 text-amber-700"
            )}
          >
            <div className="font-medium">{strictPipelineResult.message ?? strictPipelineResult.status}</div>
            <div className="mt-2 grid grid-cols-2 gap-2 text-foreground">
              <InfoCell label="状态" value={strictPipelineResult.status} />
              <InfoCell label="缺口覆盖" value={formatPct(strictPipelineResult.audit?.coverage_pct)} />
              <InfoCell label="缺口" value={`${strictPipelineResult.audit?.gap_count ?? 0}个`} />
              <InfoCell label="缺失" value={`${strictPipelineResult.audit?.missing_count ?? 0}个`} />
              <InfoCell label="回测ID" value={strictPipelineResult.backtest?.backtest_id ?? "--"} />
              <InfoCell label="CSV" value={strictPipelineResult.csv?.filename ?? "--"} />
            </div>
            {strictPipelineResult.next_action && <div className="mt-2">{strictPipelineResult.next_action}</div>}
          </div>
        )}

        {template && (
          <label className="block border-t pt-3">
            <span className="text-xs text-muted-foreground">待填分钟线模板</span>
            <textarea className="mt-1 min-h-20 w-full resize-y rounded-md border bg-muted/30 p-2 font-mono text-xs" readOnly value={template} />
          </label>
        )}

        <MinuteStep
          number="2"
          title="补齐分钟线"
          description="可从外部 CSV、vn.py 数据库、TDX 公开源或 Tushare Pro 回填。建议先预检查，再正式导入。"
        />
        <label className="block border-t pt-3">
          <span className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            外部分钟线 CSV
            <span className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-foreground">
              <FileUp size={13} />
              读文件
              <input
                className="hidden"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => loadCsvFile(event.target.files?.[0], onImportFileLoad)}
              />
            </span>
          </span>
          <textarea
            className="mt-1 min-h-24 w-full resize-y rounded-md border bg-background p-2 font-mono text-xs"
            value={importCsv}
            onChange={(event) => onImportCsvChange(event.target.value)}
            placeholder="vt_symbol,bar_time,open,high,low,close,volume,turnover..."
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">服务器分钟线文件路径</span>
          <input
            className="mt-1 h-9 w-full rounded-md border bg-background px-2 text-xs"
            value={importFilePath}
            onChange={(event) => onImportFilePathChange(event.target.value)}
            placeholder="data/imports/xt_1m_bars.csv"
          />
        </label>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={onDryRun} disabled={!canImport || isImporting}>
            {isImporting ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
            预检查
          </Button>
          <Button size="sm" onClick={onImport} disabled={!canImport || isImporting}>
            {isImporting ? <RefreshCw size={15} className="animate-spin" /> : <Upload size={15} />}
            导入
          </Button>
        </div>

        {importResult && (
          <div className="grid grid-cols-2 gap-2 border-t pt-3">
            <InfoCell label="状态" value={importResult.status} />
            <InfoCell label="预检查" value={importResult.dry_run ? "是" : "否"} />
            <InfoCell label="读取" value={`${importResult.rows_read ?? 0}行`} />
            <InfoCell label="写入" value={`${importResult.rows_written ?? 0}行`} />
            <InfoCell label="跳过" value={`${importResult.rows_skipped ?? 0}行`} />
            <InfoCell label="股票" value={`${importResult.symbol_count ?? 0}只`} />
          </div>
        )}

        <div className="border-t pt-3">
          <div className="text-xs text-muted-foreground">vn.py 数据库分钟线</div>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            <input
              className="h-9 rounded-md border bg-background px-2 text-xs"
              value={vnpyParams.vt_symbol}
              onChange={(event) => onVnpyParamsChange({ ...vnpyParams, vt_symbol: event.target.value })}
              placeholder="600000.SSE"
            />
            <input
              className="h-9 rounded-md border bg-background px-2 text-xs"
              type="date"
              value={vnpyParams.start}
              onChange={(event) => onVnpyParamsChange({ ...vnpyParams, start: event.target.value })}
            />
            <input
              className="h-9 rounded-md border bg-background px-2 text-xs"
              type="date"
              value={vnpyParams.end}
              onChange={(event) => onVnpyParamsChange({ ...vnpyParams, end: event.target.value })}
            />
            <label className="flex h-9 items-center gap-2 rounded-md border px-2 text-xs">
              <input
                type="checkbox"
                checked={vnpyParams.dry_run}
                onChange={(event) => onVnpyParamsChange({ ...vnpyParams, dry_run: event.target.checked })}
              />
              预检查
            </label>
          </div>
          <Button
            className="mt-2"
            size="sm"
            variant="outline"
            onClick={onImportFromVnpy}
            disabled={!vnpyParams.vt_symbol.trim() || !vnpyParams.start || isImportingFromVnpy}
          >
            {isImportingFromVnpy ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
            单标的导入
          </Button>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onImportGapsFromVnpy(true)}
              disabled={!canAudit || isImportingGapsFromVnpy}
            >
              {isImportingGapsFromVnpy ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
              按缺口预检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onImportGapsFromVnpy(false)}
              disabled={!canAudit || isImportingGapsFromVnpy}
            >
              {isImportingGapsFromVnpy ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
              按缺口导入
            </Button>
          </div>
          {vnpyImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="状态" value={vnpyImportResult.status} />
              <InfoCell label="预检查" value={vnpyImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="读取" value={`${vnpyImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${vnpyImportResult.rows_written ?? 0}行`} />
            </div>
          )}
          {vnpyGapImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="批量状态" value={vnpyGapImportResult.status} />
              <InfoCell label="预检查" value={vnpyGapImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="处理缺口" value={`${vnpyGapImportResult.processed_gap_count ?? 0}个`} />
              <InfoCell label="读取" value={`${vnpyGapImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${vnpyGapImportResult.rows_written ?? 0}行`} />
              <InfoCell label="空请求" value={`${vnpyGapImportResult.empty_request_count ?? 0}个`} />
              <InfoCell label="导入后覆盖" value={formatPct(vnpyGapImportResult.audit_after?.coverage_pct)} />
              <InfoCell label="导入后缺失" value={`${vnpyGapImportResult.audit_after?.missing_count ?? 0}个`} />
            </div>
          )}
        </div>

        <div className="border-t pt-3">
          <div className="text-xs text-muted-foreground">通达信公开行情历史分钟线</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onImportGapsFromTdx(true)}
              disabled={!canAudit || isImportingGapsFromTdx}
            >
              {isImportingGapsFromTdx ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
              TDX预检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onImportGapsFromTdx(false)}
              disabled={!canAudit || isImportingGapsFromTdx}
            >
              {isImportingGapsFromTdx ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
              TDX导入
            </Button>
          </div>
          {tdxGapImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="状态" value={tdxGapImportResult.status} />
              <InfoCell label="预检查" value={tdxGapImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="处理缺口" value={`${tdxGapImportResult.processed_gap_count ?? 0}个`} />
              <InfoCell label="读取" value={`${tdxGapImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${tdxGapImportResult.rows_written ?? 0}行`} />
              <InfoCell label="扫描" value={`${tdxGapImportResult.remote_rows_scanned ?? 0}行`} />
              <InfoCell label="预覆盖" value={`${tdxGapImportResult.preview_covered_gap_count ?? 0}个`} />
              <InfoCell label="导入后覆盖" value={formatPct(tdxGapImportResult.audit_after?.coverage_pct)} />
            </div>
          )}
          {tdxGapImportResult?.message && (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
              {tdxGapImportResult.message}
            </div>
          )}
        </div>

        <div className="border-t pt-3">
          <div className="text-xs text-muted-foreground">Tushare Pro 历史分钟线</div>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onImportGapsFromTushare(true)}
              disabled={!canAudit || isImportingGapsFromTushare}
            >
              {isImportingGapsFromTushare ? <RefreshCw size={15} className="animate-spin" /> : <ClipboardCheck size={15} />}
              Tushare预检查
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => onImportGapsFromTushare(false)}
              disabled={!canAudit || isImportingGapsFromTushare}
            >
              {isImportingGapsFromTushare ? <RefreshCw size={15} className="animate-spin" /> : <Download size={15} />}
              Tushare导入
            </Button>
          </div>
          {tushareGapImportResult && (
            <div className="mt-3 grid grid-cols-2 gap-2">
              <InfoCell label="状态" value={tushareGapImportResult.status} />
              <InfoCell label="预检查" value={tushareGapImportResult.dry_run ? "是" : "否"} />
              <InfoCell label="处理缺口" value={`${tushareGapImportResult.processed_gap_count ?? 0}个`} />
              <InfoCell label="读取" value={`${tushareGapImportResult.rows_read ?? 0}行`} />
              <InfoCell label="写入" value={`${tushareGapImportResult.rows_written ?? 0}行`} />
              <InfoCell label="空请求" value={`${tushareGapImportResult.empty_request_count ?? 0}个`} />
              <InfoCell label="错期过滤" value={`${tushareGapImportResult.wrong_date_row_count ?? 0}行`} />
              <InfoCell label="导入后覆盖" value={formatPct(tushareGapImportResult.audit_after?.coverage_pct)} />
            </div>
          )}
          {tushareGapImportResult?.message && (
            <div className="mt-2 rounded-md border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
              {tushareGapImportResult.message}
            </div>
          )}
        </div>

        {audit?.missing_examples && audit.missing_examples.length > 0 && (
          <div className="border-t pt-3">
            <div className="text-xs text-muted-foreground">缺口示例</div>
            <div className="mt-2 max-h-28 overflow-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>股票</TableHead>
                    <TableHead>日期</TableHead>
                    <TableHead className="text-right">分钟线</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {audit.missing_examples.slice(0, 8).map((row) => (
                    <TableRow key={`${row.vt_symbol}-${row.trade_date}`}>
                      <TableCell>
                        <StockIdentityLink vtSymbol={row.vt_symbol} />
                      </TableCell>
                      <TableCell>{row.trade_date}</TableCell>
                      <TableCell className="text-right tabular-nums">{row.minute_bar_count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        <MinuteStep
          number="3"
          title="复审后再跑严格回测"
          description="导入后重新审计缺口。只有覆盖率为 100% 时，严格流水线才会生成真实尾盘分钟成交回测。"
        />
        {fileError ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-fall">{fileError}</div> : null}
        {error ? <div className="rounded-md border border-red-200 bg-red-50 p-2 text-xs text-fall">{String(error)}</div> : null}
      </div>
      )}
    </section>
  );
}

function VnpyStatusPanel({ data, isLoading }: { data?: VnpyStatus; isLoading: boolean }) {
  if (isLoading) return <LoadingState rows={3} />;
  if (!data) return null;
  const missing = data.plugins.filter((item) => item.required_for_a_share && !item.installed);
  const installed = data.plugins.filter((item) => item.installed);

  return (
    <section className="rounded-lg border p-4 text-sm">
      <h2 className="text-sm font-semibold">vn.py 集成</h2>
      <div className="mt-3 grid grid-cols-2 gap-2">
        <InfoCell label="状态" value={data.status === "ready" ? "A股就绪" : "部分就绪"} />
        <InfoCell label="已安装插件" value={`${installed.length} 个`} />
        <InfoCell label="GUI Gateway" value={data.launcher.registered_gateways.join(", ")} />
        <InfoCell label="A股缺口" value={`${missing.length} 项`} />
      </div>
      {missing.length > 0 && (
        <div className="mt-3 border-t pt-3">
          <div className="text-xs text-muted-foreground">待安装/配置</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {missing.slice(0, 8).map((item) => (
              <span key={item.module} className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
                {item.module}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function MinuteStep({ number, title, description }: { number: string; title: string; description: string }) {
  return (
    <div className="flex gap-3 rounded-lg border bg-muted/20 p-3">
      <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border bg-background text-xs font-medium">
        {number}
      </div>
      <div className="min-w-0">
        <div className="font-medium">{title}</div>
        <div className="mt-1 text-xs leading-5 text-muted-foreground">{description}</div>
      </div>
    </div>
  );
}

function ActionStatus({
  screen,
  backtestId,
  autoBuy,
}: {
  screen?: { status: string; recommendation_count?: number; portfolio_sync?: { synced: number } | null };
  backtestId?: number | null;
  autoBuy?: { status: string; filled?: number; auto_position_sync?: { synced: number } };
}) {
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
      {screen && (
        <span className="mr-4">筛选: {screen.status}，推荐 {screen.recommendation_count ?? 0}，同步 {screen.portfolio_sync?.synced ?? 0}</span>
      )}
      {backtestId && <span className="mr-4">回测: #{backtestId}</span>}
      {autoBuy && <span>模拟建仓: {autoBuy.status}，成交 {autoBuy.filled ?? 0}，持仓分组同步 {autoBuy.auto_position_sync?.synced ?? 0}</span>}
    </div>
  );
}

function InfoCell({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div>
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 font-medium tabular-nums">{value ?? "--"}</div>
    </div>
  );
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatNumber(value: number | null | undefined, digits = 2) {
  if (value == null) return "--";
  return value.toFixed(digits);
}

function formatTime(value: string | null | undefined) {
  if (!value) return "--";
  const normalized = value.replace("T", " ");
  return normalized.length > 16 ? normalized.slice(0, 16) : normalized;
}

function formatMetric(key: string, value: number | null) {
  if (value == null) return "--";
  if (key.endsWith("_pct") || key === "win_rate") {
    const pct = key === "win_rate" ? value * 100 : value;
    return formatPct(pct);
  }
  if (key.includes("cash") || key.includes("equity") || key.includes("win") || key.includes("loss")) {
    return formatAmount(value);
  }
  return value.toFixed(2);
}

function backtestTrustVerdict(report: Awaited<ReturnType<typeof fetchBacktestReport>>) {
  const legacy = compareVersions(report.strategy_version, MIN_TRUSTED_BACKTEST_VERSION) < 0;
  const quality = report.execution_quality;
  const buyCount = quality?.buy_count ?? 0;
  const minuteRatio = quality?.minute_tail_entry_ratio ?? 0;
  const fallbackRatio = quality?.daily_open_fallback_ratio ?? 0;
  const items: string[] = [];

  if (legacy) {
    items.push("旧版本卖出撮合存在时间顺序风险：收盘触发条件可能按当天开盘成交，历史结果不要用于判断策略有效性。");
  }
  if (buyCount === 0) {
    items.push("这份报告没有买入成交，只能检查数据和筛选流程，不能统计策略胜率。");
  }
  if (buyCount > 0 && fallbackRatio >= 80) {
    items.push("多数买入是 D+1 开盘回退，不是你想要的尾盘接近 5 日线真实分钟成交。");
  }
  if (buyCount > 0 && minuteRatio < 80) {
    items.push("严格验证尾盘低吸前，需要补齐分钟线并使用“严格分钟预设”。");
  }

  if (legacy) {
    return {
      status: "invalid" as const,
      label: "需重跑",
      title: "这份旧回测不能信",
      description: "当前结果来自旧撮合版本，先重新运行回测再看收益、胜率和个股归因。",
      entryMode: "旧版撮合",
      items,
    };
  }
  if (buyCount > 0 && fallbackRatio >= 80) {
    return {
      status: "warning" as const,
      label: "宽松模拟",
      title: "结果只能当日线近似",
      description: "卖出撮合已按下一交易日开盘处理，但买入大多没有分钟线成交证据。",
      entryMode: "D+1 开盘回退",
      items,
    };
  }
  if (quality?.status === "pass") {
    return {
      status: "pass" as const,
      label: "可复核",
      title: "撮合顺序和分钟覆盖通过",
      description: "买卖时点没有同日未来函数，买入主要由尾盘分钟规则成交。",
      entryMode: "尾盘分钟成交",
      items,
    };
  }
  return {
    status: "warning" as const,
    label: "需复核",
    title: "结果需要结合日志复核",
    description: "撮合版本已更新，但样本、分钟线或财报覆盖仍可能影响结论。",
    entryMode: buyCount > 0 ? "混合成交" : "无成交",
    items,
  };
}

function compareVersions(left: string, right: string) {
  const leftParts = left.split(".").map((item) => Number(item) || 0);
  const rightParts = right.split(".").map((item) => Number(item) || 0);
  const length = Math.max(leftParts.length, rightParts.length);
  for (let index = 0; index < length; index += 1) {
    const diff = (leftParts[index] ?? 0) - (rightParts[index] ?? 0);
    if (diff !== 0) return diff;
  }
  return 0;
}

function metricColor(key: string, value: number | null) {
  if (value == null) return "";
  if (key === "max_drawdown_pct") return "text-fall";
  if (key === "average_loss") return "text-fall";
  if (key.includes("return") || key === "average_win") return priceColorClass(value);
  return "";
}

function robustnessStatus(status: string) {
  if (status === "pass") return "通过";
  if (status === "fail") return "未通过";
  return "需复核";
}

function formatRobustnessValue(value: number | null | undefined, valueType?: string) {
  if (valueType === "count") return value == null ? "--" : value.toLocaleString();
  return formatPct(value);
}

function eventLabel(event: { event_type: string; side?: string; status?: string }) {
  const side = event.side === "BUY" ? "买入" : event.side === "SELL" ? "卖出" : event.side ?? "--";
  if (event.event_type === "trade") return `${side}成交`;
  if (event.status === "filled") return `${side}订单成交`;
  if (event.status === "rejected") return `${side}订单拒绝`;
  return `${side}订单`;
}

function executionModeLabel(mode?: string | null) {
  if (mode === "minute_tail_ma5") return "尾盘分钟";
  if (mode === "daily_next_open") return "次日开盘";
  if (mode === "daily_next_open_fallback") return "开盘回退";
  if (mode === "minute_tail_ma5_required") return "严格分钟";
  return mode || "--";
}
