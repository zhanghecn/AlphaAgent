import { BarChart3, Download, RefreshCw } from "lucide-react";
import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";
import { formatNumber, formatRobustnessValue, robustnessStatus } from "@/lib/backtest-utils";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  backtestValidationGridCsvUrl,
  fetchBacktestCandidateTradeQualityReport,
  fetchBacktestExecutionModelComparison,
  fetchBacktestFactorAudit,
  fetchBacktestPerformanceAttributionReport,
  type PhaseStrategyFamilyMatrixRow,
  fetchBacktestPhaseStrategyFamilyMatrix,
  fetchBacktestReplacementQualityMatrix,
  fetchBacktestReport,
  fetchBacktestRotationOpportunityCostMatrix,
  fetchBacktestTrendWinnerProtectionMatrix,
  type RotationOpportunityBucketRow,
  type TrendWinnerProtectionBucketRow,
  fetchBacktestSetupMarketExitAudit,
  fetchBacktestTopCandidateAudit,
  fetchBacktestValidationGrid,
  type CandidateTradeQualityBucket,
  type CandidateTradeQualityDailySummary,
  type CandidateTradeQualitySample,
  type BacktestPerformanceExitReasonRow,
  type BacktestPerformanceTradeDelta,
} from "@/api/quant";
import { BacktestRegimeTable, BacktestYearlyTable } from "./BacktestTables";

export function BacktestRealityVerdictPanel({
  report,
  comparison,
  isComparisonLoading,
  onRunComparison,
}: {
  report: Awaited<ReturnType<typeof fetchBacktestReport>>;
  comparison?: Awaited<ReturnType<typeof fetchBacktestExecutionModelComparison>>;
  isComparisonLoading: boolean;
  onRunComparison: () => void;
}) {
  const quality = report.execution_quality;
  const verdict = realityVerdict(report);
  const strictRow = comparison?.rows.find((row) => row.execution_model === "strict_1430");
  const hybridRow = comparison?.rows.find((row) => row.execution_model === "tail_close_hybrid");

  return (
    <div className="rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">回测真实性结论</div>
        <span className={cn("rounded-md border px-2 py-1 text-xs", verdict.className)}>{verdict.label}</span>
      </div>
      <div className="space-y-3 p-3">
        <div className="grid gap-3 text-sm md:grid-cols-4">
          <InfoCell label="执行模型" value={executionModelLabel(report.method?.execution?.execution_model)} />
          <InfoCell label="14:30真实占比" value={formatPct(quality?.minute_1430_ratio ?? quality?.minute_tail_entry_ratio)} />
          <InfoCell label="收盘代理占比" value={formatPct(quality?.daily_close_proxy_ratio)} />
          <InfoCell label="严格拒单" value={`${quality?.strict_1430_rejected_count ?? quality?.strict_tail_rejected_count ?? 0}笔`} />
        </div>
        <div className="grid gap-2 text-sm lg:grid-cols-2">
          <VerdictLine label="成交口径" text={verdict.executionText} />
          <VerdictLine label="反未来函数" text={verdict.asOfText} />
          <VerdictLine label="数值可信度" text={verdict.numericText} />
          <VerdictLine label="过拟合" text={verdict.overfitText} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-sm">
          <div className="text-muted-foreground">
            {comparison?.summary?.message ??
              "执行模型对比会用同一参数重跑尾盘混合和严格14:30，判断收益是否依赖收盘代理。"}
          </div>
          <Button variant="outline" size="sm" onClick={onRunComparison} disabled={isComparisonLoading}>
            {isComparisonLoading ? <RefreshCw size={15} className="animate-spin" /> : <BarChart3 size={15} />}
            执行模型对比
          </Button>
        </div>
        {comparison?.status === "ready" && (
          <div className="grid gap-2 text-sm md:grid-cols-3">
            <InfoCell label="混合收益" value={formatPct(hybridRow?.total_return_pct)} />
            <InfoCell label="严格收益" value={formatPct(strictRow?.total_return_pct)} />
            <InfoCell label="严格-混合" value={formatPct(comparison.summary?.return_delta_pct)} />
          </div>
        )}
      </div>
    </div>
  );
}

export function BacktestExecutionModelComparisonPanel({
  comparison,
  isLoading,
  onRun,
}: {
  comparison?: Awaited<ReturnType<typeof fetchBacktestExecutionModelComparison>>;
  isLoading: boolean;
  onRun: () => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">执行模型对比</div>
          <div className="text-xs text-muted-foreground">同一回测参数下，对比尾盘混合和严格14:30。</div>
        </div>
        <Button variant="outline" size="sm" onClick={onRun} disabled={isLoading}>
          {isLoading ? <RefreshCw size={15} className="animate-spin" /> : <BarChart3 size={15} />}
          运行对比
        </Button>
      </div>
      {!comparison ? (
        <div className="p-3 text-sm text-muted-foreground">点击运行后，会非持久化重跑两个执行模型，不新增回测记录。</div>
      ) : comparison.status !== "ready" ? (
        <div className="p-3 text-sm text-muted-foreground">执行模型对比状态：{comparison.status}</div>
      ) : (
        <div className="space-y-3 p-3">
          {comparison.summary?.message && <div className="text-sm text-muted-foreground">{comparison.summary.message}</div>}
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>模型</TableHead>
                <TableHead className="text-right">收益</TableHead>
                <TableHead className="text-right">回撤</TableHead>
                <TableHead className="text-right">买入</TableHead>
                <TableHead className="text-right">14:30占比</TableHead>
                <TableHead className="text-right">收盘代理</TableHead>
                <TableHead className="text-right">严格拒单</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {comparison.rows.map((row) => (
                <TableRow key={row.execution_model}>
                  <TableCell className="font-medium">{row.label}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(row.total_return_pct))}>
                    {formatPct(row.total_return_pct)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums text-fall">{formatPct(row.max_drawdown_pct)}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.buy_count ?? "--"}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPct(row.minute_1430_ratio)}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatPct(row.daily_close_proxy_ratio)}</TableCell>
                  <TableCell className="text-right tabular-nums">{row.strict_1430_rejected_count ?? 0}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {comparison.note && <div className="border-t pt-2 text-xs text-muted-foreground">{comparison.note}</div>}
        </div>
      )}
    </div>
  );
}

export function BacktestRobustnessPanel({
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

export function BacktestMarketAuditPanel({
  report,
  topCandidateAudit,
  isTopCandidateAuditLoading,
  factorAudit,
  isFactorAuditLoading,
  setupMarketExitAudit,
  isSetupMarketExitAuditLoading,
  phaseStrategyFamilyMatrix,
  isPhaseStrategyFamilyMatrixLoading,
  replacementQualityMatrix,
  isReplacementQualityMatrixLoading,
  rotationOpportunityCostMatrix,
  isRotationOpportunityCostMatrixLoading,
  trendWinnerProtectionMatrix,
  isTrendWinnerProtectionMatrixLoading,
}: {
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  topCandidateAudit?: Awaited<ReturnType<typeof fetchBacktestTopCandidateAudit>>;
  isTopCandidateAuditLoading?: boolean;
  factorAudit?: Awaited<ReturnType<typeof fetchBacktestFactorAudit>>;
  isFactorAuditLoading?: boolean;
  setupMarketExitAudit?: Awaited<ReturnType<typeof fetchBacktestSetupMarketExitAudit>>;
  isSetupMarketExitAuditLoading?: boolean;
  phaseStrategyFamilyMatrix?: Awaited<ReturnType<typeof fetchBacktestPhaseStrategyFamilyMatrix>>;
  isPhaseStrategyFamilyMatrixLoading?: boolean;
  replacementQualityMatrix?: Awaited<ReturnType<typeof fetchBacktestReplacementQualityMatrix>>;
  isReplacementQualityMatrixLoading?: boolean;
  rotationOpportunityCostMatrix?: Awaited<ReturnType<typeof fetchBacktestRotationOpportunityCostMatrix>>;
  isRotationOpportunityCostMatrixLoading?: boolean;
  trendWinnerProtectionMatrix?: Awaited<ReturnType<typeof fetchBacktestTrendWinnerProtectionMatrix>>;
  isTrendWinnerProtectionMatrixLoading?: boolean;
}) {
  const yearlyRows = report?.robustness_checks?.yearly_periods ?? [];
  const regimeAnalysis = report?.regime_analysis ?? report?.robustness_checks?.market_regime_analysis;
  const summary = topCandidateAudit?.summary;
  const excludingStrong = summary?.top_excluding_strong_summary;
  const strong = summary?.top_strong_summary;
  const observation = summary?.candidate_observation;
  const observationExcludingStrong = observation?.excluding_strong_summary;
  const sourceText = formatBenchmarkSources(summary?.benchmark_sources);
  const dynamicSourceText = formatDynamicMarketSources(summary?.dynamic_market_sources);
  const hasFactorAudit = factorAudit?.status === "ready" && Boolean(factorAudit.summary?.sample_count);
  const hasProblemMatrix = Boolean(setupMarketExitAudit?.summary?.buy_sell_problem_matrix?.by_problem?.length);
  const hasPhaseStrategyMatrix = Boolean(phaseStrategyFamilyMatrix?.summary?.real_trade_matrix?.length);
  const hasReplacementQualityMatrix = Boolean(replacementQualityMatrix?.summary?.filled_by_setup_family?.length);
  const hasRotationOpportunityMatrix = Boolean(rotationOpportunityCostMatrix?.summary?.overall?.candidate_count);
  const hasTrendWinnerProtectionMatrix = Boolean(trendWinnerProtectionMatrix?.summary?.overall?.candidate_count);
  const hasAnalysis =
    yearlyRows.length > 0 ||
    Boolean(regimeAnalysis?.periods?.length) ||
    Boolean(summary) ||
    Boolean(report?.data_quality) ||
    hasFactorAudit ||
    hasProblemMatrix ||
    hasPhaseStrategyMatrix ||
    hasReplacementQualityMatrix ||
    hasRotationOpportunityMatrix ||
    hasTrendWinnerProtectionMatrix;

  if (
    !hasAnalysis &&
    !isTopCandidateAuditLoading &&
    !isFactorAuditLoading &&
    !isSetupMarketExitAuditLoading &&
    !isPhaseStrategyFamilyMatrixLoading &&
    !isReplacementQualityMatrixLoading &&
    !isRotationOpportunityCostMatrixLoading &&
    !isTrendWinnerProtectionMatrixLoading
  ) return null;

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">年度 / 大盘 / 前10候选审计</div>
          <div className="mt-1 text-xs text-muted-foreground">
            用同一回测结果检查收益是否集中在强势行情；候选胜率只统计真实成交并闭仓的前10候选。
          </div>
        </div>
        {summary && (
          <span className="rounded-md border px-2 py-1 text-xs text-muted-foreground">
            前{summary.top_n}候选：{summary.top_evaluated_count}/{summary.top_count} 已闭仓
          </span>
        )}
      </div>

      {summary && (
        <div className="grid gap-3 text-sm md:grid-cols-4">
          <InfoCell label={`前${summary.top_n}胜率`} value={formatRate(summary.top_win_rate)} />
          <InfoCell label={`前${summary.top_n}平均收益`} value={formatPct(summary.top_avg_return_pct)} />
          <InfoCell label={`前${summary.top_n}平均超额`} value={formatPct(summary.top_avg_excess_return_pct)} />
          <InfoCell label="强势候选占比" value={formatRate(summary.top_strong_candidate_share)} />
          <InfoCell label="排除强势胜率" value={formatRate(excludingStrong?.win_rate)} />
          <InfoCell label="排除强势平均收益" value={formatPct(excludingStrong?.avg_return_pct)} />
          <InfoCell label="排除强势平均超额" value={formatPct(excludingStrong?.avg_excess_return_pct)} />
          <InfoCell label="强势行情胜率" value={formatRate(strong?.win_rate)} />
          <InfoCell label="候选观察胜率" value={formatRate(observation?.win_rate)} />
          <InfoCell label="观察排除强势胜率" value={formatRate(observationExcludingStrong?.win_rate)} />
          <InfoCell label="观察排除强势收益" value={formatPct(observationExcludingStrong?.avg_return_pct)} />
          <InfoCell label="观察排除强势超额" value={formatPct(observationExcludingStrong?.avg_excess_return_pct)} />
        </div>
      )}

      <PhaseStrategyFamilyMatrixPanel matrix={phaseStrategyFamilyMatrix} isLoading={isPhaseStrategyFamilyMatrixLoading} />
      <ReplacementQualityMatrixPanel matrix={replacementQualityMatrix} isLoading={isReplacementQualityMatrixLoading} />
      <RotationOpportunityCostMatrixPanel matrix={rotationOpportunityCostMatrix} isLoading={isRotationOpportunityCostMatrixLoading} />
      <TrendWinnerProtectionMatrixPanel matrix={trendWinnerProtectionMatrix} isLoading={isTrendWinnerProtectionMatrixLoading} />
      <FactorAuditSummaryPanel audit={factorAudit} isLoading={isFactorAuditLoading} />
      <BuySellProblemMatrixPanel audit={setupMarketExitAudit} isLoading={isSetupMarketExitAuditLoading} />

      {report?.data_quality || summary ? (
        <MarketDataCoveragePanel data={report?.data_quality} dynamicSourceText={dynamicSourceText} />
      ) : null}

      {summary?.dynamic_market_buckets?.length ? (
        <DynamicMarketBucketTable title="前10候选按动态市场画像" rows={summary.dynamic_market_buckets} />
      ) : null}
      {summary?.theme_alignment_buckets?.length ? (
        <ThemeAlignmentBucketTable title="前10候选按主线对齐" rows={summary.theme_alignment_buckets} />
      ) : null}
      {observation?.dynamic_market_buckets?.length ? (
        <DynamicMarketBucketTable title="固定持有观察按动态市场画像" rows={observation.dynamic_market_buckets} />
      ) : null}
      {observation?.theme_alignment_buckets?.length ? (
        <ThemeAlignmentBucketTable title="固定持有观察按主线对齐" rows={observation.theme_alignment_buckets} />
      ) : null}
      {summary?.market_buckets?.length ? <TopCandidateMarketBucketTable rows={summary.market_buckets} /> : null}
      {observation?.market_buckets?.length ? <CandidateObservationMarketBucketTable rows={observation.market_buckets} /> : null}
      {yearlyRows.length > 0 && <BacktestYearlyTable rows={yearlyRows} />}
      {regimeAnalysis?.periods?.length ? <BacktestRegimeTable analysis={regimeAnalysis} /> : null}

      <div className="text-xs text-muted-foreground">
        {isTopCandidateAuditLoading
          ? "正在加载前10候选审计。"
          : `${topCandidateAudit?.note ?? "候选审计未加载。"} ${observation?.method ?? ""}`}
        {sourceText ? ` 大盘基准来源：${sourceText}。` : ""}
        {dynamicSourceText ? ` 动态画像来源：${dynamicSourceText}。` : ""}
      </div>
    </div>
  );
}

export function CandidateTradeQualityPanel({
  report,
  isLoading,
}: {
  report?: Awaited<ReturnType<typeof fetchBacktestCandidateTradeQualityReport>>;
  isLoading?: boolean;
}) {
  if (!report && !isLoading) return null;
  if (!report) {
    return <div className="rounded-lg border p-3 text-sm text-muted-foreground">正在加载候选独立买卖质量。</div>;
  }
  if (report.status !== "ready" && report.status !== "empty") {
    return <div className="rounded-lg border p-3 text-sm text-muted-foreground">候选独立买卖质量状态：{report.status}</div>;
  }

  const summary = report.summary;
  const coverage = report.coverage ?? {};
  const hasBuckets = Boolean(
    report.by_rank_limit?.length ||
    report.by_daily_rank_window?.length ||
    report.by_rank_bucket?.length ||
    report.by_score_bucket?.length ||
    report.by_setup_family?.length ||
    report.by_market_phase?.length ||
    report.by_exit_reason?.length
  );
  const hasSamples = Boolean(report.worst_samples?.length || report.best_samples?.length);

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">候选独立买卖质量</div>
          <div className="mt-1 text-xs text-muted-foreground">
            每个信号日的候选按排名独立测算，D+1 开盘买入、当前卖点卖出；不看现金、仓位、满仓、已有持仓或换仓。这里不是组合收益。
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          Top{report.rank_limit ?? 100} / 样本上限 {report.sample_limit ?? 500}
        </div>
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-4 xl:grid-cols-8">
        <InfoCell label="候选簇" value={formatNumber(numberValue(coverage.cluster_count) ?? summary?.sample_count, 0)} />
        <InfoCell label="纳入排名" value={formatNumber(numberValue(coverage.rank_limited_cluster_count) ?? summary?.sample_count, 0)} />
        <InfoCell label="可评价" value={formatNumber(summary?.evaluated_count, 0)} />
        <InfoCell label="胜率" value={formatRatioPct(summary?.win_rate)} />
        <InfoCell label="平均收益" value={formatPct(summary?.average_return_pct)} />
        <InfoCell label="中位收益" value={formatPct(summary?.median_return_pct)} />
        <InfoCell label="平均最大回撤" value={formatPct(summary?.average_max_drawdown_pct)} />
        <InfoCell label="平均持有" value={formatHoldingDays(summary?.average_holding_days)} />
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-4">
        <InfoCell label="缺失执行" value={formatNumber(numberValue(coverage.missing_count), 0)} />
        <InfoCell label="无D+1日线" value={formatNumber(numberValue(coverage.no_execute_bar_count), 0)} />
        <InfoCell label="涨停开盘阻塞" value={formatNumber(numberValue(coverage.limit_up_open_blocked_count), 0)} />
        <InfoCell label="来源候选" value={formatNumber(numberValue(coverage.source_candidate_count), 0)} />
      </div>

      {report.status === "empty" && !summary?.sample_count ? (
        <div className="rounded-md border p-3 text-sm text-muted-foreground">
          {report.message ?? "当前回测区间暂无可评价的 BUY 候选簇。"}
        </div>
      ) : null}

      {hasBuckets ? (
        <div className="grid gap-3 lg:grid-cols-2">
          <CandidateTradeQualityBucketTable title="每日累计TopN" rows={report.by_rank_limit} bucketKey="rank_limit" />
          <CandidateTradeQualityBucketTable title="每日排名段" rows={report.by_daily_rank_window ?? report.by_rank_bucket} bucketKey={report.by_daily_rank_window?.length ? "daily_rank_window" : "rank_bucket"} />
          <CandidateTradeQualityBucketTable title="按分数段" rows={report.by_score_bucket} bucketKey="score_bucket" />
          <CandidateTradeQualityBucketTable title="按 setup" rows={report.by_setup_family} bucketKey="setup_family" />
          <CandidateTradeQualityBucketTable title="按行情阶段" rows={report.by_market_phase} bucketKey="market_phase" />
        </div>
      ) : null}

      <CandidateTradeQualityDailyTable rows={(report.daily_summaries ?? []).slice(0, 12)} topN={report.rank_limit ?? 100} />

      <CandidateTradeQualityBucketTable title="按卖出原因" rows={report.by_exit_reason} bucketKey="exit_reason" />

      {hasSamples ? (
        <div className="grid gap-3 xl:grid-cols-2">
          <CandidateTradeQualitySampleTable title="Top失败样本" rows={(report.worst_samples ?? []).slice(0, 8)} />
          <CandidateTradeQualitySampleTable title="Top成功样本" rows={(report.best_samples ?? []).slice(0, 8)} />
        </div>
      ) : null}

      <div className="text-xs text-muted-foreground">
        {report.note ?? "后验收益、MFE/MAE 只作为报告标签，不进入信号评分；候选质量和真实组合收益需要分开判断。"}
      </div>
    </div>
  );
}

export function BacktestPerformanceAttributionPanel({
  report,
  isLoading,
}: {
  report?: Awaited<ReturnType<typeof fetchBacktestPerformanceAttributionReport>>;
  isLoading?: boolean;
}) {
  if (!report && !isLoading) return null;
  if (!report) {
    return <div className="rounded-lg border p-3 text-sm text-muted-foreground">正在加载收益差异归因。</div>;
  }
  if (report.status !== "ready") {
    return <div className="rounded-lg border p-3 text-sm text-muted-foreground">收益差异归因状态：{report.status}</div>;
  }

  const current = report.current;
  const reference = report.reference;
  const delta = report.delta;
  const schema = report.signal_schema;
  const constraints = report.constraint_comparison;
  const exitRows = report.by_exit_reason ?? [];
  const missingWinners = report.trade_deltas?.missing_reference_winners ?? [];
  const addedLosers = report.trade_deltas?.added_current_losers ?? [];

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">收益/胜率差异归因</div>
          <div className="mt-1 text-xs text-muted-foreground">
            当前回测对比同策略同区间的历史高收益参照，解释收益和胜率为什么下降；这是只读诊断，不改变交易规则。
          </div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <div>当前 #{report.backtest_id ?? current?.id ?? "--"}</div>
          <div>参照 #{report.reference_backtest_id ?? reference?.id ?? "--"}</div>
        </div>
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-4 xl:grid-cols-8">
        <InfoCell label="当前收益" value={formatPct(current?.total_return_pct)} />
        <InfoCell label="参照收益" value={formatPct(reference?.total_return_pct)} />
        <InfoCell label="收益差" value={formatSignedPct(delta?.total_return_pct)} />
        <InfoCell label="胜率差" value={formatSignedPct(ratioToPctDelta(delta?.win_rate))} />
        <InfoCell label="PF差" value={formatSignedNumber(delta?.profit_factor, 3)} />
        <InfoCell label="平均盈利差" value={formatSignedAmount(delta?.average_win)} />
        <InfoCell label="毛盈利差" value={formatSignedAmount(delta?.gross_win)} />
        <InfoCell label="毛亏损差" value={formatSignedAmount(delta?.gross_loss)} />
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-4">
        <InfoCell label="持仓上限相同" value={constraints?.same_max_positions ? "是" : "否"} />
        <InfoCell label="候选排名相同" value={constraints?.same_candidate_limit ? "是" : "否"} />
        <InfoCell label="单票仓位相同" value={constraints?.same_position_sizing ? "是" : "否"} />
        <InfoCell label="候选schema同源" value={schema?.same_schema_lineage ? "是" : "否"} />
      </div>

      {report.interpretation?.notes?.length ? (
        <div className="rounded-md border p-3 text-sm leading-6 text-muted-foreground">
          {report.interpretation.notes.map((item) => (
            <div key={item}>{item}</div>
          ))}
        </div>
      ) : null}

      <div className="grid gap-3 xl:grid-cols-2">
        <PerformanceExitReasonTable rows={exitRows.slice(0, 8)} />
        <div className="space-y-3">
          <PerformanceTradeDeltaTable title="旧高收益有、当前缺失的赢家" rows={missingWinners.slice(0, 8)} mode="missingWinner" />
          <PerformanceTradeDeltaTable title="当前新增的亏损样本" rows={addedLosers.slice(0, 8)} mode="addedLoser" />
        </div>
      </div>

      {report.interpretation?.next_tests?.length ? (
        <div className="border-t pt-3 text-sm">
          <div className="mb-2 font-medium">下一步测评重点</div>
          <div className="space-y-1 text-muted-foreground">
            {report.interpretation.next_tests.map((item) => (
              <div key={item}>{item}</div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function PerformanceExitReasonTable({ rows }: { rows: BacktestPerformanceExitReasonRow[] }) {
  if (!rows.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-sm font-medium">按卖出原因看差异</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>卖出</TableHead>
            <TableHead className="text-right">当前/参照</TableHead>
            <TableHead className="text-right">胜率差</TableHead>
            <TableHead className="text-right">贡献差</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={String(row.exit_reason ?? row.exit_reason_label ?? "unknown")}>
              <TableCell className="font-medium">{row.exit_reason_label ?? candidateQualityExitReasonLabel(row.exit_reason)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatNumber(row.current?.trade_count, 0)} / {formatNumber(row.reference?.trade_count, 0)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(ratioToPctDelta(row.delta?.win_rate)))}>
                {formatSignedPct(ratioToPctDelta(row.delta?.win_rate))}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.delta?.net_pnl))}>
                {formatSignedAmount(row.delta?.net_pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function PerformanceTradeDeltaTable({
  title,
  rows,
  mode,
}: {
  title: string;
  rows: BacktestPerformanceTradeDelta[];
  mode: "missingWinner" | "addedLoser";
}) {
  if (!rows.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>股票</TableHead>
            <TableHead>日期</TableHead>
            <TableHead>原因</TableHead>
            <TableHead className="text-right">差异</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${title}-${row.vt_symbol ?? "symbol"}-${row.trade_date ?? "date"}-${index}`}>
              <TableCell className="font-medium">{row.vt_symbol ?? "--"}</TableCell>
              <TableCell className="whitespace-nowrap">{row.trade_date ?? "--"}</TableCell>
              <TableCell>{mode === "missingWinner" ? candidateQualityExitReasonLabel(row.reference_reason) : candidateQualityExitReasonLabel(row.current_reason)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.delta_pnl))}>
                {formatSignedAmount(row.delta_pnl)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CandidateTradeQualityBucketTable({
  title,
  rows,
  bucketKey,
}: {
  title: string;
  rows?: CandidateTradeQualityBucket[];
  bucketKey: keyof CandidateTradeQualityBucket;
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分桶</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">均值</TableHead>
            <TableHead className="text-right">中位数</TableHead>
            <TableHead className="text-right">回撤</TableHead>
            <TableHead className="text-right">持有</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${title}-${candidateQualityBucketKey(row, bucketKey)}-${index}`}>
              <TableCell className="font-medium">{candidateQualityBucketLabel(row, bucketKey)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.sample_count, 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.average_return_pct))}>
                {formatPct(row.average_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.median_return_pct))}>
                {formatPct(row.median_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.average_max_drawdown_pct))}>
                {formatPct(row.average_max_drawdown_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatHoldingDays(row.average_holding_days)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CandidateTradeQualityDailyTable({
  rows,
  topN,
}: {
  rows: CandidateTradeQualityDailySummary[];
  topN: number;
}) {
  if (!rows.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-sm font-medium">按信号日看候选池</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>信号日</TableHead>
            <TableHead className="text-right">候选/可评</TableHead>
            <TableHead className="text-right">Top10</TableHead>
            <TableHead className="text-right">Top20</TableHead>
            <TableHead className="text-right">Top{topN}</TableHead>
            <TableHead>最好候选</TableHead>
            <TableHead>最差候选</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={String(row.entry_signal_date ?? "")}>
              <TableCell className="whitespace-nowrap font-medium">{row.entry_signal_date ?? "--"}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatNumber(row.candidate_count, 0)} / {formatNumber(row.evaluated_count, 0)}
              </TableCell>
              <CandidateTradeQualityDailyMetricCell summary={row.top10} />
              <CandidateTradeQualityDailyMetricCell summary={row.top20} />
              <CandidateTradeQualityDailyMetricCell summary={row.topn} />
              <CandidateTradeQualityExtremeCell row={row.best_candidate} />
              <CandidateTradeQualityExtremeCell row={row.worst_candidate} />
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CandidateTradeQualityDailyMetricCell({ summary }: { summary?: CandidateTradeQualityDailySummary["top10"] }) {
  return (
    <TableCell className="text-right tabular-nums">
      <div>{formatRatioPct(summary?.win_rate)}</div>
      <div className={cn("text-xs", priceColorClass(summary?.average_return_pct))}>
        {formatPct(summary?.average_return_pct)}
      </div>
    </TableCell>
  );
}

function CandidateTradeQualityExtremeCell({ row }: { row?: CandidateTradeQualityDailySummary["best_candidate"] }) {
  if (!row) return <TableCell className="text-muted-foreground">--</TableCell>;
  return (
    <TableCell>
      <div className="whitespace-nowrap">
        {row.name || row.vt_symbol || "--"}
        {row.rank != null ? ` #${row.rank}` : ""}
      </div>
      <div className={cn("text-xs tabular-nums", priceColorClass(row.return_pct))}>
        {formatPct(row.return_pct)} · {candidateQualityExitReasonLabel(row.exit_reason)}
      </div>
    </TableCell>
  );
}

function CandidateTradeQualitySampleTable({
  title,
  rows,
}: {
  title: string;
  rows: CandidateTradeQualitySample[];
}) {
  if (!rows.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>信号</TableHead>
            <TableHead>候选</TableHead>
            <TableHead>簇</TableHead>
            <TableHead>执行</TableHead>
            <TableHead className="text-right">收益</TableHead>
            <TableHead className="text-right">回撤/MFE</TableHead>
            <TableHead>卖出</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${title}-${row.entry_signal_date ?? "date"}-${row.vt_symbol}-${index}`}>
              <TableCell className="whitespace-nowrap">{row.entry_signal_date ?? "--"}</TableCell>
              <TableCell>
                <StockIdentityLink
                  name={row.name}
                  vtSymbol={row.vt_symbol}
                  board={row.board}
                  boardLabel={row.board_label}
                  meta={candidateQualitySampleMeta(row)}
                />
              </TableCell>
              <TableCell>
                <div className="whitespace-nowrap">{candidateQualityClusterText(row)}</div>
                <div className="text-xs text-muted-foreground">{row.setup_family_label ?? setupFamilyLabel(row.setup_family)}</div>
              </TableCell>
              <TableCell>
                <div className="whitespace-nowrap">{row.entry_execute_date ?? "--"} 买</div>
                <div className="whitespace-nowrap text-xs text-muted-foreground">{row.exit_execute_date ?? "未卖出"} 卖</div>
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.return_pct))}>
                {formatPct(row.return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                <div className={priceColorClass(row.max_drawdown_pct)}>{formatPct(row.max_drawdown_pct)}</div>
                <div className={cn("text-xs", priceColorClass(row.max_runup_pct))}>{formatPct(row.max_runup_pct)}</div>
              </TableCell>
              <TableCell>
                <div>{candidateQualityExitReasonLabel(row.exit_reason)}</div>
                <div className="text-xs text-muted-foreground">{row.market_phase_label ?? phaseLabel(row.market_phase)}</div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function BuySellProblemMatrixPanel({
  audit,
  isLoading,
}: {
  audit?: Awaited<ReturnType<typeof fetchBacktestSetupMarketExitAudit>>;
  isLoading?: boolean;
}) {
  const rows = audit?.summary?.buy_sell_problem_matrix?.by_problem ?? [];
  const exitQuality = audit?.summary?.exit_path_replacement_quality;
  const replacementSummary = exitQuality?.replacement_quality_summary;
  const marketValidation = audit?.summary?.market_context_validation;
  if (!rows.length) {
    if (!isLoading) return null;
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">正在加载买卖问题归因。</div>;
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">买卖问题归因</div>
          <div className="mt-1 text-xs text-muted-foreground">
            用真实闭仓路径、卖后反弹和替换交易质量判断问题来源；仅用于审计，不改变买卖规则。
          </div>
        </div>
        <span className="text-xs text-muted-foreground">样本 {formatNumber(sumMetric(rows, "trade_count"), 0)}</span>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>问题</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">均值</TableHead>
            <TableHead className="text-right">卖早</TableHead>
            <TableHead className="text-right">坏替换</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 8).map((row) => (
            <TableRow key={String(row.trade_problem_type ?? row.label ?? "unknown")}>
              <TableCell className="font-medium">{String(row.label ?? problemLabel(row.trade_problem_type))}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(numberValue(row.trade_count), 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(numberValue(row.avg_return_pct)))}>
                {formatPct(numberValue(row.avg_return_pct))}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.sold_before_rebound_count, 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(numberValue(row.bad_replacement_count), 0)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {replacementSummary ? (
        <div className="border-t p-3">
          <div className="mb-2 text-xs font-medium text-muted-foreground">卖点释放仓位后的替换质量</div>
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
            <InfoCell label="替换交易" value={formatNumber(replacementSummary.replacement_trade_count, 0)} />
            <InfoCell label="坏替换" value={formatNumber(replacementSummary.bad_replacement_count, 0)} />
            <InfoCell label="强替换" value={formatNumber(replacementSummary.strong_replacement_count, 0)} />
            <InfoCell label="替换均值" value={formatPct(replacementSummary.avg_replacement_return_pct)} />
            <InfoCell label="质量差" value={formatPct(replacementSummary.avg_replacement_return_delta_pct)} />
          </div>
          {exitQuality?.by_support_stop_context?.length ? (
            <CompactPathBucketTable
              title="支撑止损上下文"
              rows={exitQuality.by_support_stop_context.slice(0, 5)}
              bucketKey="support_stop_context"
            />
          ) : null}
        </div>
      ) : null}
      {marketValidation ? (
        <div className="border-t p-3">
          <div className="mb-2 text-xs font-medium text-muted-foreground">市场环境验证</div>
          <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
            <InfoCell label="排除强势样本" value={formatNumber(marketValidation.excluding_strong_market?.trade_count, 0)} />
            <InfoCell label="排除强势胜率" value={formatRatioPct(marketValidation.excluding_strong_market?.win_rate)} />
            <InfoCell label="排除强势均值" value={formatPct(marketValidation.excluding_strong_market?.avg_return_pct)} />
            <InfoCell label="资金不足样本" value={formatNumber(marketValidation.fund_flow_coverage?.insufficient_data_count, 0)} />
          </div>
          {marketValidation.by_market_regime?.length ? (
            <CompactPathBucketTable
              title="按动态市场画像"
              rows={marketValidation.by_market_regime.slice(0, 5)}
              bucketKey="dynamic_market_regime"
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PhaseStrategyFamilyMatrixPanel({
  matrix,
  isLoading,
}: {
  matrix?: Awaited<ReturnType<typeof fetchBacktestPhaseStrategyFamilyMatrix>>;
  isLoading?: boolean;
}) {
  const summary = matrix?.summary;
  const realRows = summary?.real_trade_matrix ?? [];
  const top20 = (summary?.candidate_rank_matrices ?? []).find((item) => item.rank_limit === 20)
    ?? summary?.candidate_rank_matrices?.[0];
  const candidateRows = top20?.by_phase_setup ?? [];
  if (!realRows.length && !candidateRows.length) {
    if (!isLoading) return null;
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">正在加载行情与策略族矩阵。</div>;
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">行情与策略族矩阵</div>
          <div className="mt-1 text-xs text-muted-foreground">
            行情只做环境和审计，不直接加到个股分数；低吸蓄势只做观察簇。
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          成交 {formatNumber(summary?.coverage?.trade_count, 0)} / 候选 {formatNumber(summary?.coverage?.candidate_count, 0)}
        </div>
      </div>

      <PhaseStrategyFamilyTable title="真实成交" rows={realRows} mode="trade" />
      {candidateRows.length ? (
        <PhaseStrategyFamilyTable title={`候选 Top${top20?.rank_limit ?? "--"}`} rows={candidateRows} mode="candidate" />
      ) : null}

      {summary?.interpretation?.notes?.length ? (
        <div className="border-t px-3 py-2 text-xs leading-6 text-muted-foreground">
          {summary.interpretation.notes.join(" ")}
        </div>
      ) : null}
    </div>
  );
}

function PhaseStrategyFamilyTable({
  title,
  rows,
  mode,
}: {
  title: string;
  rows: PhaseStrategyFamilyMatrixRow[];
  mode: "trade" | "candidate";
}) {
  if (!rows.length) return null;
  return (
    <div className="border-t first:border-t-0">
      <div className="px-3 py-2 text-xs font-medium text-muted-foreground">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>行情</TableHead>
            <TableHead>策略族</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">均值</TableHead>
            <TableHead className="text-right">中位数</TableHead>
            <TableHead className="text-right">{mode === "trade" ? "止损" : "MFE>=8%"}</TableHead>
            <TableHead className="text-right">{mode === "trade" ? "收益合计" : "MAE<=-5%"}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.slice(0, 16).map((row, index) => (
            <TableRow key={`${title}-${row.market_phase ?? "phase"}-${row.setup_family ?? "setup"}-${index}`}>
              <TableCell className="font-medium">{row.phase_label ?? phaseLabel(row.market_phase)}</TableCell>
              <TableCell>{row.setup_label ?? setupFamilyLabel(row.setup_family)}</TableCell>
              <TableCell className="text-right tabular-nums">
                {formatNumber(mode === "trade" ? row.trade_count : row.candidate_count, 0)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_return_pct))}>
                {formatPct(row.avg_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.median_return_pct))}>
                {formatPct(row.median_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {mode === "trade" ? formatNumber(row.support_stop_count, 0) : formatRatioPct(row.mfe_8_pct_hit_ratio)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", mode === "trade" ? priceColorClass(row.total_return_pct) : undefined)}>
                {mode === "trade" ? formatPct(row.total_return_pct) : formatRatioPct(row.mae_5_pct_loss_ratio)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ReplacementQualityMatrixPanel({
  matrix,
  isLoading,
}: {
  matrix?: Awaited<ReturnType<typeof fetchBacktestReplacementQualityMatrix>>;
  isLoading?: boolean;
}) {
  const summary = matrix?.summary;
  const setupRows = summary?.filled_by_setup_family ?? [];
  const rejectReasons = summary?.rejected_reason_counts ?? [];
  const bucketRows = summary?.filled_by_low_suction_bucket ?? [];
  if (!setupRows.length && !rejectReasons.length) {
    if (!isLoading) return null;
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">正在加载替换质量矩阵。</div>;
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">卖后替换质量矩阵</div>
          <div className="mt-1 text-xs text-muted-foreground">
            复查卖出释放仓位后买入了什么，以及闸门拒掉了什么；只读审计，不改变买卖规则。
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 text-right text-xs">
          <InfoCell label="闭合成交" value={formatNumber(matrix?.total?.filled_trade_count, 0)} />
          <InfoCell label="闸门拒买" value={formatNumber(matrix?.total?.gate_reject_count, 0)} />
        </div>
      </div>

      <div className="grid gap-3 p-3 text-sm md:grid-cols-4">
        <InfoCell label="成交均值" value={formatPct(summary?.filled_overall?.avg_return_pct)} />
        <InfoCell label="成交胜率" value={formatRatioPct(summary?.filled_overall?.win_rate)} />
        <InfoCell label="拒买均分" value={formatNumber(summary?.rejected_overall?.avg_entry_score, 2)} />
        <InfoCell label="高风险拒买" value={formatNumber(summary?.rejected_overall?.high_warning_count, 0)} />
      </div>

      <PhaseStrategyFamilyTable title="真实成交按策略族" rows={setupRows} mode="trade" />
      {bucketRows.length ? <PhaseStrategyFamilyTable title="真实成交按低吸桶" rows={bucketRows.slice(0, 8)} mode="trade" /> : null}
      {rejectReasons.length ? <ReplacementRejectReasonTable rows={rejectReasons.slice(0, 8)} /> : null}

      {summary?.interpretation?.notes?.length ? (
        <div className="border-t px-3 py-2 text-xs leading-6 text-muted-foreground">
          {summary.interpretation.notes.join(" ")}
        </div>
      ) : null}
    </div>
  );
}

function ReplacementRejectReasonTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestReplacementQualityMatrix>>["summary"]>["rejected_reason_counts"];
}) {
  if (!rows?.length) return null;
  return (
    <div className="border-t">
      <div className="px-3 py-2 text-xs font-medium text-muted-foreground">闸门拒买原因</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>原因</TableHead>
            <TableHead className="text-right">次数</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.reason}>
              <TableCell className="font-medium">{row.label ?? rejectReasonLabel(row.reason)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.count, 0)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function RotationOpportunityCostMatrixPanel({
  matrix,
  isLoading,
}: {
  matrix?: Awaited<ReturnType<typeof fetchBacktestRotationOpportunityCostMatrix>>;
  isLoading?: boolean;
}) {
  const summary = matrix?.summary;
  const overall = summary?.overall;
  const phaseRows = summary?.by_phase ?? [];
  const setupRows = summary?.by_setup_family ?? [];
  const bucketRows = summary?.by_opportunity_bucket ?? [];
  const proxyTables = [
    { title: "按候选排名", rows: summary?.by_candidate_rank ?? [], labelKey: "candidateRank" as const },
    { title: "按低吸天数", rows: summary?.by_low_suction_days ?? [], labelKey: "lowSuctionDays" as const },
    { title: "按启动质量", rows: summary?.by_launch_quality ?? [], labelKey: "launchQuality" as const },
    { title: "按均线收敛", rows: summary?.by_ma_convergence ?? [], labelKey: "maConvergence" as const },
    { title: "按弱持仓状态", rows: summary?.by_replaced_current_return ?? [], labelKey: "replacedReturn" as const },
    { title: "按执行开盘状态", rows: summary?.by_replaced_execute_open_return ?? [], labelKey: "replacedExecuteOpenReturn" as const },
    { title: "按持仓天数", rows: summary?.by_replaced_holding_days ?? [], labelKey: "replacedHoldingDays" as const },
  ].filter((table) => table.rows.length);
  const sampleRows = matrix?.items ?? [];
  if (!overall?.candidate_count && !phaseRows.length && !sampleRows.length) {
    if (!isLoading) return null;
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">正在加载满仓换仓机会矩阵。</div>;
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">满仓换仓机会矩阵</div>
          <div className="mt-1 text-xs text-muted-foreground">
            满仓错过的前列买入候选，对比同日最弱持仓真实退出收益；只读审计，不改变策略。
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          Top{matrix?.candidate_rank_limit ?? 20} / {matrix?.holding_days ?? 20}日观察
        </div>
      </div>

      <div className="grid gap-3 p-3 text-sm md:grid-cols-6">
        <InfoCell label="满仓候选" value={formatNumber(overall?.candidate_count, 0)} />
        <InfoCell label="可评价" value={formatNumber(overall?.evaluated_count, 0)} />
        <InfoCell label="正机会率" value={formatRatioPct(overall?.positive_rate)} />
        <InfoCell label="强正机会" value={formatRatioPct(overall?.strong_positive_rate)} />
        <InfoCell label="有害率" value={formatRatioPct(overall?.harmful_rate)} />
        <InfoCell label="开盘仍弱" value={formatRatioPct(overall?.execute_open_weak_rate)} />
        <InfoCell label="开盘已盈利" value={formatRatioPct(overall?.execute_open_profitable_rate)} />
        <div>
          <div className="text-xs text-muted-foreground">平均差值</div>
          <div className={cn("mt-0.5 font-medium tabular-nums", priceColorClass(overall?.avg_opportunity_delta_pct))}>
            {formatPct(overall?.avg_opportunity_delta_pct)}
          </div>
        </div>
      </div>

      {summary?.interpretation?.message ? (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground">{summary.interpretation.message}</div>
      ) : null}

      <div className="grid gap-3 border-t p-3 lg:grid-cols-2">
        {phaseRows.length ? <RotationOpportunityBucketTable title="按行情" rows={phaseRows.slice(0, 6)} labelKey="phase" /> : null}
        {setupRows.length ? <RotationOpportunityBucketTable title="按策略族" rows={setupRows.slice(0, 6)} labelKey="setup" /> : null}
      </div>
      {proxyTables.length ? (
        <div className="grid gap-3 border-t p-3 lg:grid-cols-2">
          {proxyTables.slice(0, 6).map((table) => (
            <RotationOpportunityBucketTable
              key={table.title}
              title={table.title}
              rows={table.rows.slice(0, 5)}
              labelKey={table.labelKey}
            />
          ))}
        </div>
      ) : null}
      {bucketRows.length ? <RotationOpportunityBucketTable title="按机会差值" rows={bucketRows.slice(0, 6)} labelKey="bucket" /> : null}
      {sampleRows.length ? <RotationOpportunitySampleTable rows={sampleRows.slice(0, 8)} /> : null}

      {matrix?.note ? <div className="border-t px-3 py-2 text-xs text-muted-foreground">{matrix.note}</div> : null}
    </div>
  );
}

function RotationOpportunityBucketTable({
  title,
  rows,
  labelKey,
}: {
  title: string;
  rows: NonNullable<NonNullable<Awaited<ReturnType<typeof fetchBacktestRotationOpportunityCostMatrix>>["summary"]>["by_phase"]>;
  labelKey:
    | "phase"
    | "setup"
    | "bucket"
    | "candidateRank"
    | "lowSuctionDays"
    | "launchQuality"
    | "maConvergence"
    | "replacedReturn"
    | "replacedExecuteOpenReturn"
    | "replacedHoldingDays";
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分桶</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">正机会</TableHead>
            <TableHead className="text-right">候选均值</TableHead>
            <TableHead className="text-right">替换均值</TableHead>
            <TableHead className="text-right">开盘仍弱</TableHead>
            <TableHead className="text-right">差值</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${title}-${rotationOpportunityRowKey(row, labelKey)}-${index}`}>
              <TableCell className="font-medium">{rotationOpportunityRowLabel(row, labelKey)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.evaluated_count ?? row.candidate_count, 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.positive_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_candidate_return_pct))}>
                {formatPct(row.avg_candidate_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_replaced_real_return_pct))}>
                {formatPct(row.avg_replaced_real_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.execute_open_weak_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_opportunity_delta_pct))}>
                {formatPct(row.avg_opportunity_delta_pct)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function RotationOpportunitySampleTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestRotationOpportunityCostMatrix>>["items"]>;
}) {
  if (!rows?.length) return null;
  return (
    <div className="border-t">
      <div className="px-3 py-2 text-xs font-medium text-muted-foreground">机会差值样本</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>日期</TableHead>
            <TableHead>候选</TableHead>
            <TableHead>行情</TableHead>
            <TableHead>策略族</TableHead>
            <TableHead>被替换</TableHead>
            <TableHead className="text-right">候选</TableHead>
            <TableHead className="text-right">快照</TableHead>
            <TableHead className="text-right">开盘</TableHead>
            <TableHead className="text-right">退出</TableHead>
            <TableHead className="text-right">差值</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.signal_date ?? "date"}-${row.vt_symbol ?? "symbol"}-${index}`}>
              <TableCell className="whitespace-nowrap">{row.signal_date ?? "--"}</TableCell>
              <TableCell>
                <StockIdentityLink
                  name={row.name}
                  vtSymbol={row.vt_symbol}
                  board={row.board}
                  boardLabel={row.board_label}
                  meta={row.rank ? `#${row.rank}` : undefined}
                />
              </TableCell>
              <TableCell>{row.market_phase_label ?? phaseLabel(row.market_phase)}</TableCell>
              <TableCell>{setupFamilyLabel(row.setup_family ?? row.entry_family)}</TableCell>
              <TableCell>
                <StockIdentityLink name={row.replaced_name} vtSymbol={row.replaced_symbol} meta={row.replaced_exit_reason ?? undefined} />
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.candidate_return_pct))}>
                {formatPct(row.candidate_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.replaced_snapshot_return_pct ?? row.replaced_current_return_pct))}>
                {formatPct(row.replaced_snapshot_return_pct ?? row.replaced_current_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.replaced_execute_open_return_pct))}>
                {formatPct(row.replaced_execute_open_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.replaced_real_return_pct))}>
                {formatPct(row.replaced_real_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.opportunity_delta_pct))}>
                {formatPct(row.opportunity_delta_pct)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function TrendWinnerProtectionMatrixPanel({
  matrix,
  isLoading,
}: {
  matrix?: Awaited<ReturnType<typeof fetchBacktestTrendWinnerProtectionMatrix>>;
  isLoading?: boolean;
}) {
  const summary = matrix?.summary;
  const overall = summary?.overall;
  const protectionRows = summary?.by_protection_bucket ?? [];
  const openRows = summary?.by_execute_open_return ?? [];
  const phaseRows = summary?.by_phase ?? [];
  const sampleRows = matrix?.items ?? [];
  if (!overall?.candidate_count && !protectionRows.length && !sampleRows.length) {
    if (!isLoading) return null;
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">正在加载趋势赢家保护矩阵。</div>;
  }

  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">趋势赢家保护矩阵</div>
          <div className="mt-1 text-xs text-muted-foreground">
            复用满仓换仓样本，识别 D+1 开盘已盈利或已修复的持仓；只读审计，不改变策略。
          </div>
        </div>
        <div className="text-xs text-muted-foreground">
          Top{matrix?.candidate_rank_limit ?? 20} / {matrix?.holding_days ?? 20}日观察
        </div>
      </div>

      <div className="grid gap-3 p-3 text-sm md:grid-cols-6">
        <InfoCell label="样本" value={formatNumber(overall?.candidate_count, 0)} />
        <InfoCell label="应保护" value={formatRatioPct(overall?.protected_rate)} />
        <InfoCell label="可替换审计" value={formatRatioPct(overall?.replaceable_rate)} />
        <InfoCell label="替换有害" value={formatRatioPct(overall?.harmful_replacement_rate)} />
        <div>
          <div className="text-xs text-muted-foreground">开盘收益</div>
          <div className={cn("mt-0.5 font-medium tabular-nums", priceColorClass(overall?.avg_held_execute_open_return_pct))}>
            {formatPct(overall?.avg_held_execute_open_return_pct)}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted-foreground">真实退出</div>
          <div className={cn("mt-0.5 font-medium tabular-nums", priceColorClass(overall?.avg_held_real_return_pct))}>
            {formatPct(overall?.avg_held_real_return_pct)}
          </div>
        </div>
      </div>

      {summary?.interpretation?.message ? (
        <div className="border-t px-3 py-2 text-xs text-muted-foreground">{summary.interpretation.message}</div>
      ) : null}

      <div className="grid gap-3 border-t p-3 lg:grid-cols-3">
        {protectionRows.length ? <TrendWinnerProtectionBucketTable title="按保护状态" rows={protectionRows} labelKey="bucket" /> : null}
        {openRows.length ? <TrendWinnerProtectionBucketTable title="按执行开盘" rows={openRows} labelKey="openReturn" /> : null}
        {phaseRows.length ? <TrendWinnerProtectionBucketTable title="按行情" rows={phaseRows} labelKey="phase" /> : null}
      </div>
      {sampleRows.length ? <TrendWinnerProtectionSampleTable rows={sampleRows.slice(0, 8)} /> : null}
      {matrix?.note ? <div className="border-t px-3 py-2 text-xs text-muted-foreground">{matrix.note}</div> : null}
    </div>
  );
}

function TrendWinnerProtectionBucketTable({
  title,
  rows,
  labelKey,
}: {
  title: string;
  rows: TrendWinnerProtectionBucketRow[];
  labelKey: "bucket" | "openReturn" | "phase";
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分桶</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">保护</TableHead>
            <TableHead className="text-right">可替换</TableHead>
            <TableHead className="text-right">有害</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${title}-${trendWinnerRowLabel(row, labelKey)}-${index}`}>
              <TableCell className="font-medium">{trendWinnerRowLabel(row, labelKey)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.candidate_count, 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.protected_rate)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.replaceable_rate)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.harmful_replacement_rate)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function TrendWinnerProtectionSampleTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestTrendWinnerProtectionMatrix>>["items"]>;
}) {
  if (!rows?.length) return null;
  return (
    <div className="border-t">
      <div className="px-3 py-2 text-xs font-medium text-muted-foreground">保护样本</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>执行日</TableHead>
            <TableHead>持仓</TableHead>
            <TableHead>候选</TableHead>
            <TableHead>状态</TableHead>
            <TableHead className="text-right">挡住</TableHead>
            <TableHead className="text-right">开盘</TableHead>
            <TableHead className="text-right">真实退出</TableHead>
            <TableHead className="text-right">机会差</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${row.execute_date ?? "date"}-${row.held_symbol ?? "held"}-${index}`}>
              <TableCell className="whitespace-nowrap">{row.execute_date ?? "--"}</TableCell>
              <TableCell>
                <StockIdentityLink name={row.held_name} vtSymbol={row.held_symbol} meta={row.held_exit_reason ?? undefined} />
              </TableCell>
              <TableCell>
                <StockIdentityLink
                  name={row.candidate_name}
                  vtSymbol={row.candidate_symbol}
                  meta={row.candidate_rank ? `#${row.candidate_rank}` : undefined}
                />
              </TableCell>
              <TableCell>
                <div className="font-medium">{row.protection_label ?? trendWinnerProtectionLabel(row.protection_bucket)}</div>
                <div className="text-xs text-muted-foreground">{row.reason ?? row.market_phase_label ?? phaseLabel(row.market_phase)}</div>
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.blocked_candidate_count, 0)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.held_execute_open_return_pct))}>
                {formatPct(row.held_execute_open_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.held_real_return_pct))}>
                {formatPct(row.held_real_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.best_opportunity_delta_pct ?? row.opportunity_delta_pct))}>
                {formatPct(row.best_opportunity_delta_pct ?? row.opportunity_delta_pct)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function phaseLabel(value?: string | null) {
  const labels: Record<string, string> = {
    uptrend: "主升",
    rotation: "震荡",
    retreat: "退潮",
    warming: "回暖",
    unknown: "未知",
  };
  return labels[String(value || "unknown")] ?? String(value || "未知");
}

function setupFamilyLabel(value?: string | null) {
  const labels: Record<string, string> = {
    dragon_pullback: "龙回头",
    low_suction_first_lift: "低吸首启",
    low_suction_buildup: "低吸蓄势",
    dragon_low_suction_overlap: "龙回头+低吸",
    unknown: "未归类",
  };
  return labels[String(value || "unknown")] ?? String(value || "未归类");
}

function trendWinnerRowLabel(row: TrendWinnerProtectionBucketRow, labelKey: "bucket" | "openReturn" | "phase") {
  if (labelKey === "bucket") return row.label ?? trendWinnerProtectionLabel(row.protection_bucket);
  if (labelKey === "openReturn") return row.label ?? String(row.held_execute_open_return_bucket ?? "执行开盘未知");
  return row.label ?? phaseLabel(row.market_phase);
}

function trendWinnerProtectionLabel(value?: string | null) {
  const labels: Record<string, string> = {
    protect_trend_winner: "保护趋势赢家",
    protect_uptrend_repair: "主升修复保护",
    protect_open_profit: "开盘盈利保护",
    replaceable_weak_holding: "可研究弱持仓替换",
    needs_manual_review: "需要人工复核",
    unknown: "状态未知",
  };
  return labels[String(value || "unknown")] ?? String(value || "状态未知");
}

function rejectReasonLabel(value?: string | null) {
  const labels: Record<string, string> = {
    score_below_gate: "分数低于接力闸门",
    market_warning_too_high: "市场风险等级过高",
    has_failed_or_risk_flags: "候选带失败/风险标记",
    low_suction_overlap_unconfirmed: "低吸/龙回头重叠未确认",
    weak_low_suction_launch_bucket: "低吸启动桶偏弱",
    low_suction_ma_convergence_too_wide: "低吸均线收敛过宽",
    dragon_ma_convergence_too_wide: "龙回头均线收敛过宽",
    dragon_not_fresh_tail_buy: "龙回头不是新鲜回踩",
    unsupported_setup: "不支持的接力形态",
  };
  return labels[String(value || "")] ?? String(value || "未知拒买原因");
}

function rotationOpportunityRowKey(
  row: RotationOpportunityBucketRow,
  labelKey:
    | "phase"
    | "setup"
    | "bucket"
    | "candidateRank"
    | "lowSuctionDays"
    | "launchQuality"
    | "maConvergence"
    | "replacedReturn"
    | "replacedExecuteOpenReturn"
    | "replacedHoldingDays"
) {
  if (labelKey === "phase") return String(row.market_phase ?? row.label ?? "unknown");
  if (labelKey === "setup") return String(row.setup_family ?? row.label ?? "unknown");
  if (labelKey === "candidateRank") return String(row.candidate_rank_bucket ?? row.label ?? "unknown");
  if (labelKey === "lowSuctionDays") return String(row.low_suction_days_bucket ?? row.label ?? "unknown");
  if (labelKey === "launchQuality") return String(row.low_suction_launch_quality_bucket ?? row.label ?? "unknown");
  if (labelKey === "maConvergence") return String(row.ma_convergence_bucket ?? row.label ?? "unknown");
  if (labelKey === "replacedReturn") return String(row.replaced_current_return_bucket ?? row.label ?? "unknown");
  if (labelKey === "replacedExecuteOpenReturn") return String(row.replaced_execute_open_return_bucket ?? row.label ?? "unknown");
  if (labelKey === "replacedHoldingDays") return String(row.replaced_holding_days_bucket ?? row.label ?? "unknown");
  return String(row.opportunity_bucket ?? row.label ?? "unknown");
}

function rotationOpportunityRowLabel(
  row: RotationOpportunityBucketRow,
  labelKey:
    | "phase"
    | "setup"
    | "bucket"
    | "candidateRank"
    | "lowSuctionDays"
    | "launchQuality"
    | "maConvergence"
    | "replacedReturn"
    | "replacedExecuteOpenReturn"
    | "replacedHoldingDays"
) {
  if (typeof row.label === "string" && row.label.trim()) return row.label;
  if (labelKey === "phase") return String(row.market_phase_label ?? phaseLabel(String(row.market_phase ?? "")));
  if (labelKey === "setup") return String(row.setup_family_label ?? setupFamilyLabel(String(row.setup_family ?? "")));
  if (labelKey === "candidateRank") return String(row.candidate_rank_bucket ?? "排名未知");
  if (labelKey === "lowSuctionDays") return String(row.low_suction_days_bucket ?? "低吸天数未知");
  if (labelKey === "launchQuality") return String(row.low_suction_launch_quality_bucket ?? "启动质量未知");
  if (labelKey === "maConvergence") return String(row.ma_convergence_bucket ?? "均线收敛未知");
  if (labelKey === "replacedReturn") return String(row.replaced_current_return_bucket ?? "持仓浮盈未知");
  if (labelKey === "replacedExecuteOpenReturn") return String(row.replaced_execute_open_return_bucket ?? "执行开盘未知");
  if (labelKey === "replacedHoldingDays") return String(row.replaced_holding_days_bucket ?? "持仓天数未知");
  return String(row.opportunity_bucket ?? "未归类");
}

function CompactPathBucketTable({
  title,
  rows,
  bucketKey,
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  bucketKey: string;
}) {
  return (
    <div className="mt-3 overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-xs font-medium text-muted-foreground">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分桶</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">均值</TableHead>
            <TableHead className="text-right">坏替换</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow key={`${bucketKey}-${String(row[bucketKey] ?? row.label ?? index)}`}>
              <TableCell className="font-medium">{String(row.label ?? row[bucketKey] ?? "未归类")}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(numberValue(row.trade_count), 0)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(numberValue(row.win_rate))}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(numberValue(row.avg_return_pct)))}>
                {formatPct(numberValue(row.avg_return_pct))}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(numberValue(row.bad_replacement_count), 0)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function FactorAuditSummaryPanel({
  audit,
  isLoading,
}: {
  audit?: Awaited<ReturnType<typeof fetchBacktestFactorAudit>>;
  isLoading?: boolean;
}) {
  if (!audit && !isLoading) return null;
  if (audit && audit.status !== "ready") {
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">因子分桶审计状态：{audit.status}</div>;
  }

  const setupRows = topFactorRows(audit?.by_setup, 6);
  const rankRows = topFactorRows(audit?.by_rank_bucket, 4);
  const marketRows = topFactorRows(audit?.by_market_regime, 6);
  const warningRows = topFactorRows(audit?.by_market_warning_level, 4);
  const fundFlowRows = topFactorRows(audit?.by_fund_flow_state, 4);
  const reclaimRows = topFactorRows(audit?.by_low_position_reclaim_type, 5);
  const convergenceRows = topFactorRows(audit?.by_factor_bucket?.ma_convergence, 5);
  const lowSuctionRows = topFactorRows(audit?.by_factor_bucket?.low_suction_days, 5);
  const launchRows = topFactorRows(audit?.by_factor_bucket?.launch_quality, 5);
  const volumeRows = topFactorRows(audit?.by_factor_bucket?.volume, 5);
  const closeRows = topFactorRows(audit?.by_factor_bucket?.close_location, 5);
  const interaction = audit?.factor_interaction_opportunity_cost;
  const interactionRows = topPathRows(interaction?.entry_family_market, 5);
  const hasRows =
    setupRows.length ||
    rankRows.length ||
    marketRows.length ||
    warningRows.length ||
    fundFlowRows.length ||
    reclaimRows.length ||
    convergenceRows.length ||
    lowSuctionRows.length ||
    launchRows.length ||
    volumeRows.length ||
    closeRows.length ||
    interactionRows.length;

  if (!hasRows) {
    return (
      <div className="rounded-md border p-3 text-sm text-muted-foreground">
        {isLoading ? "正在加载因子分桶审计。" : "暂无因子分桶审计样本。"}
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">低吸 / 龙回头因子分桶</div>
          <div className="mt-1 text-xs text-muted-foreground">
            按信号日可见特征分桶，再用固定持有后验做审计；这些后验结果不参与买入评分。
          </div>
        </div>
        <div className="text-xs text-muted-foreground">样本 {factorSampleCount(audit)}</div>
      </div>

      <div className="grid gap-3 text-sm md:grid-cols-4">
        <InfoCell label="总体胜率" value={formatRatioPct(audit?.summary?.win_rate)} />
        <InfoCell label="平均观察收益" value={formatPct(audit?.summary?.average_return)} />
        <InfoCell label="失败启动占比" value={formatRatioPct(audit?.summary?.failed_launch_ratio)} />
        <InfoCell label="类止损占比" value={formatRatioPct(audit?.summary?.support_stop_like_ratio)} />
      </div>

      {setupRows.length ? <FactorBucketTable title="按入场类型" rows={setupRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "setup")} /> : null}
      {reclaimRows.length ? <FactorBucketTable title="按低位承接类型" rows={reclaimRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "reclaim")} /> : null}
      {rankRows.length ? <FactorBucketTable title="按候选排名" rows={rankRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "rank")} /> : null}
      {marketRows.length ? <FactorBucketTable title="按市场环境" rows={marketRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "market")} /> : null}
      <div className="grid gap-3 lg:grid-cols-2">
        {warningRows.length ? <FactorBucketTable title="按风险等级" rows={warningRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "warning")} compact /> : null}
        {fundFlowRows.length ? <FactorBucketTable title="按资金流" rows={fundFlowRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "fund")} compact /> : null}
        {convergenceRows.length ? <FactorBucketTable title="按均线收敛" rows={convergenceRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "ma")} compact /> : null}
        {lowSuctionRows.length ? <FactorBucketTable title="按低吸蓄势天数" rows={lowSuctionRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "days")} compact /> : null}
        {launchRows.length ? <FactorBucketTable title="按启动质量" rows={launchRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "launch")} compact /> : null}
        {volumeRows.length ? <FactorBucketTable title="按量能" rows={volumeRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "volume")} compact /> : null}
        {closeRows.length ? <FactorBucketTable title="按收盘位置" rows={closeRows} labelFormatter={(bucket) => factorBucketLabel(bucket, "close")} compact /> : null}
      </div>

      {interactionRows.length ? (
        <div className="overflow-hidden rounded-md border">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
            <div>
              <div className="text-sm font-medium">因子交互审计</div>
              <div className="mt-1 text-xs text-muted-foreground">按入场类型和市场环境交叉分桶；后验结果只用于审计。</div>
            </div>
            <div className="text-xs text-muted-foreground">
              赢家 {formatNumber(interaction?.opportunity_cost?.removed_winner_count, 0)} / 亏损 {formatNumber(interaction?.opportunity_cost?.avoided_loser_count, 0)}
            </div>
          </div>
          <CompactPathBucketTable title="入场类型 x 市场环境" rows={interactionRows} bucketKey="factor_value" />
        </div>
      ) : null}

      <CandidateExecutionAttributionPanel attribution={audit?.candidate_execution_attribution} />

      <div className="text-xs text-muted-foreground">
        审计口径：候选特征只取信号日之前可见数据；固定持有收益、MFE/MAE、失败启动只作为后验标签，不写入策略评分。
      </div>
    </div>
  );
}

function CandidateExecutionAttributionPanel({
  attribution,
}: {
  attribution?: Awaited<ReturnType<typeof fetchBacktestFactorAudit>>["candidate_execution_attribution"];
}) {
  if (!attribution?.candidate_count) return null;
  const missed = attribution.top20_missed_quality;
  const portfolioSummary = attribution.portfolio_opportunity_summary;
  const reasonRows = attribution.by_not_filled_reason ?? missed?.by_reason ?? [];
  const subreasonRows = attribution.by_not_filled_subreason ?? [];
  const opportunityRows = attribution.missed_candidate_opportunity_cost ?? [];
  const fullPortfolioMissed = portfolioSummary?.full_portfolio_missed;
  const opportunityTypeRows = portfolioSummary?.by_opportunity_type ?? [];
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b px-3 py-2">
        <div>
          <div className="text-sm font-medium">候选执行归因</div>
          <div className="mt-1 text-xs text-muted-foreground">
            前{attribution.max_execution_rank ?? 20}名候选与真实组合成交对应；错过收益是后验审计，不参与排名。
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3 text-right text-xs">
          <InfoCell label="候选" value={formatNumber(attribution.candidate_count, 0)} />
          <InfoCell label="成交" value={formatNumber(attribution.filled_count, 0)} />
          <InfoCell label="错过" value={formatNumber(attribution.missed_count, 0)} />
        </div>
      </div>
      <div className="grid gap-3 p-3 text-sm md:grid-cols-4">
        <InfoCell label="错过后验胜数" value={formatNumber(missed?.missed_positive_20d_count, 0)} />
        <InfoCell label="错过平均收益" value={formatPct(missed?.missed_avg_return_20d)} />
        <InfoCell label="错过平均MFE" value={formatPct(missed?.missed_avg_mfe_20d)} />
        <InfoCell label="错过平均MAE" value={formatPct(missed?.missed_avg_mae_20d)} />
      </div>
      {portfolioSummary ? (
        <div className="border-t px-3 py-2">
          <div className="mb-2 text-xs font-medium text-muted-foreground">满仓机会审计</div>
          <div className="grid gap-2 md:grid-cols-4">
            <InfoCell label="满仓错过新标的" value={formatNumber(fullPortfolioMissed?.sample_count, 0)} />
            <InfoCell label="后验胜率" value={formatRatioPct(fullPortfolioMissed?.win_rate)} />
            <InfoCell label="后验均值" value={formatPct(fullPortfolioMissed?.average_return_20d)} />
            <InfoCell label="相对最弱持仓" value={formatPct(fullPortfolioMissed?.average_delta_vs_weakest_held)} />
          </div>
          {opportunityTypeRows.length ? (
            <div className="mt-2 grid gap-2 md:grid-cols-3">
              {opportunityTypeRows.slice(0, 3).map((row, index) => (
                <div key={`${row.opportunity_type ?? "type"}-${index}`} className="rounded-md border bg-muted/20 p-2">
                  <div className="text-xs font-medium">{opportunityTypeLabel(row.opportunity_type)}</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    样本 {formatNumber(row.sample_count, 0)}，均值 {formatPct(row.average_return_20d)}
                  </div>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      {reasonRows.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>未成交原因</TableHead>
              <TableHead className="text-right">样本</TableHead>
              <TableHead className="text-right">错过</TableHead>
              <TableHead className="text-right">后验胜率</TableHead>
              <TableHead className="text-right">后验均值</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reasonRows.slice(0, 6).map((row, index) => (
              <TableRow key={`${row.not_filled_reason ?? "none"}-${index}`}>
                <TableCell className="font-medium">{notFilledReasonLabel(row.not_filled_reason)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.sample_count, 0)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatNumber(row.missed_count, 0)}</TableCell>
                <TableCell className="text-right tabular-nums">{formatRatioPct(row.win_rate)}</TableCell>
                <TableCell className={cn("text-right tabular-nums", priceColorClass(numberValue(row.average_return_20d)))}>
                  {formatPct(numberValue(row.average_return_20d))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
      {subreasonRows.length ? (
        <div className="border-t px-3 py-2">
          <div className="mb-2 text-xs font-medium text-muted-foreground">候选未进计划子原因</div>
          <div className="grid gap-2 md:grid-cols-3">
            {subreasonRows.slice(0, 6).map((row, index) => (
              <div key={`${row.not_filled_subreason ?? "none"}-${index}`} className="rounded-md border bg-muted/20 p-2">
                <div className="text-xs font-medium">{notFilledSubreasonLabel(row.not_filled_subreason)}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  样本 {formatNumber(row.sample_count, 0)}，后验均值 {formatPct(numberValue(row.average_return_20d))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      {opportunityRows.length ? (
        <div className="border-t">
          <div className="px-3 py-2 text-xs font-medium text-muted-foreground">错过候选机会成本</div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>错过候选</TableHead>
                <TableHead>对比持仓</TableHead>
                <TableHead className="text-right">分差</TableHead>
                <TableHead className="text-right">候选20日</TableHead>
                <TableHead className="text-right">持仓浮盈</TableHead>
                <TableHead className="text-right">质量差</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {opportunityRows.slice(0, 6).map((row, index) => (
                <TableRow key={`${row.signal_date ?? "date"}-${row.missed_symbol ?? "miss"}-${row.held_symbol ?? "held"}-${index}`}>
                  <TableCell className="whitespace-nowrap">{row.signal_date ?? "--"}</TableCell>
                  <TableCell className="font-medium">
                    {row.missed_symbol ?? "--"}
                    {row.missed_rank ? <span className="ml-1 text-xs text-muted-foreground">#{row.missed_rank}</span> : null}
                  </TableCell>
                  <TableCell>{row.held_symbol ?? "--"}</TableCell>
                  <TableCell className="text-right tabular-nums">{formatNumber(row.rotation_score_gap, 2)}</TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(numberValue(row.missed_return_20d)))}>
                    {formatPct(numberValue(row.missed_return_20d))}
                  </TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(numberValue(row.held_unrealized_return_pct)))}>
                    {formatPct(numberValue(row.held_unrealized_return_pct))}
                  </TableCell>
                  <TableCell className={cn("text-right tabular-nums", priceColorClass(numberValue(row.replacement_quality_delta)))}>
                    {formatPct(numberValue(row.replacement_quality_delta))}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : null}
    </div>
  );
}

function FactorBucketTable({
  title,
  rows,
  labelFormatter,
  compact = false,
}: {
  title: string;
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestFactorAudit>>["by_setup"]>;
  labelFormatter: (bucket: string) => string;
  compact?: boolean;
}) {
  return (
    <div className="overflow-hidden rounded-md border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>分桶</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">均值</TableHead>
            {!compact && <TableHead className="text-right">中位数</TableHead>}
            <TableHead className="text-right">PF</TableHead>
            {!compact && <TableHead className="text-right">失败启动</TableHead>}
            {!compact && <TableHead className="text-right">类止损</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${title}-${row.bucket}`}>
              <TableCell className="font-medium">{labelFormatter(row.bucket)}</TableCell>
              <TableCell className="text-right tabular-nums">{row.sample_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRatioPct(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.average_return))}>
                {formatPct(row.average_return)}
              </TableCell>
              {!compact && (
                <TableCell className={cn("text-right tabular-nums", priceColorClass(row.median_return))}>
                  {formatPct(row.median_return)}
                </TableCell>
              )}
              <TableCell className="text-right tabular-nums">{formatNumber(row.profit_factor, 2)}</TableCell>
              {!compact && <TableCell className="text-right tabular-nums">{formatRatioPct(row.failed_launch_ratio)}</TableCell>}
              {!compact && <TableCell className="text-right tabular-nums">{formatRatioPct(row.support_stop_like_ratio)}</TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function MarketDataCoveragePanel({
  data,
  dynamicSourceText,
}: {
  data?: Awaited<ReturnType<typeof fetchBacktestReport>>["data_quality"];
  dynamicSourceText: string;
}) {
  const dailyBars = qualityItem(data, "stock_daily_bars");
  const sectorFlows = qualityItem(data, "sector_fund_flows");
  const stockFlows = qualityItem(data, "stock_fund_flows");
  const sectorScores = qualityItem(data, "sector_period_scores");
  const fundFlowStatus = marketFundFlowCoverageStatus(sectorFlows, stockFlows);
  return (
    <div className="rounded-md border bg-muted/20 p-3 text-sm">
      <div className="font-medium">行情数据覆盖</div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <InfoCell label="动态画像来源" value={dynamicSourceText || "--"} />
        <InfoCell label="指数/日线覆盖" value={qualityRangeText(dailyBars)} />
        <InfoCell label="板块资金流" value={qualityRangeText(sectorFlows)} />
        <InfoCell label="个股资金流" value={qualityRangeText(stockFlows)} />
        <InfoCell label="板块评分" value={qualityRangeText(sectorScores)} />
        <InfoCell label="资金流可信度" value={fundFlowStatus.label} />
      </div>
      <div className="mt-3 text-xs leading-6 text-muted-foreground">
        {fundFlowStatus.note}
      </div>
    </div>
  );
}

export function BacktestDataAsOfAuditPanel({
  audit,
}: {
  audit: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["data_as_of_audit"]>;
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2">
        <div className="text-sm font-medium">反未来函数审计</div>
        <span
          className={cn(
            "rounded-md border px-2 py-1 text-xs",
            audit.status === "pass" ? "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10" : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
          )}
        >
          {audit.status === "pass" ? "通过" : "需复核"}
        </span>
      </div>
      <div className="space-y-3 p-3">
        {audit.policy && <div className="text-xs text-muted-foreground">{audit.policy}</div>}
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
            {audit.diagnostics.map((row) => (
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

export function BacktestValidationGridPanel({
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
        <div className="p-3 text-sm text-muted-foreground">点击运行后，会用同一股票池和交易区间重跑不同入场分、止损、止盈、硬入场/宽松研究组合。</div>
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

export function BacktestWalkForwardPanel({
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

export function BacktestRealityStats({
  metrics,
}: {
  metrics: NonNullable<Awaited<ReturnType<typeof fetchBacktestReport>>["extended_metrics"]>;
}) {
  return (
    <div className="grid gap-2 border-t pt-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <InfoCell label="平均持仓" value={`${formatNumber(metrics.average_holding_days, 1)}天`} />
      <InfoCell label="持仓中位数" value={`${formatNumber(metrics.median_holding_days, 1)}天`} />
      <InfoCell label="换手估算" value={formatPct(metrics.turnover_pct)} />
      <InfoCell label="平均仓位" value={formatPct(metrics.average_exposure_pct)} />
      <InfoCell label="最大持仓数" value={`${metrics.max_position_count}只`} />
      <InfoCell label="买入/卖出/持仓中" value={`${metrics.buy_count} / ${metrics.sell_count} / ${metrics.open_trade_count}笔`} />
      <InfoCell label="成交订单" value={`${metrics.filled_order_count}笔`} />
      <InfoCell label="未成交订单" value={`${metrics.rejected_order_count}笔`} />
      <InfoCell label="涨停未买" value={`${metrics.limit_up_blocked_buy_count ?? 0}笔`} />
      <InfoCell label="跌停未卖" value={`${metrics.limit_down_blocked_sell_count ?? 0}笔`} />
    </div>
  );
}

export function BacktestExecutionQualityPanel({
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
            quality.status === "pass" ? "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10" : "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300"
          )}
        >
          {quality.status === "pass" ? "通过" : "有缺口"}
        </span>
      </div>
      <div className="space-y-3 p-3">
        <div className="grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-6">
          <InfoCell label="买入笔数" value={`${quality.buy_count}笔`} />
          <InfoCell label="14:30真实成交" value={`${quality.minute_1430_count ?? quality.minute_tail_entry_count ?? 0}笔`} />
          <InfoCell label="收盘代理成交" value={`${quality.daily_close_proxy_count ?? 0}笔`} />
          <InfoCell label="入场未触发" value={`${quality.tail_entry_rejected_count ?? 0}笔`} />
          <InfoCell label="缺14:30快照" value={`${quality.minute_gap_rejected_count ?? 0}笔`} />
          <InfoCell label="14:30真实占比" value={formatPct(quality.minute_1430_ratio ?? quality.minute_tail_entry_ratio)} />
          <InfoCell label="收盘代理占比" value={formatPct(quality.daily_close_proxy_ratio)} />
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

export function BacktestOrderStatsPanel({
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

export function BacktestDataQuality({
  data,
  limitations,
}: {
  data?: Awaited<ReturnType<typeof fetchBacktestReport>>["data_quality"];
  limitations: string[];
}) {
  const tableNames = [
    "stocks",
    "stock_daily_bars",
    "stock_financial_reports",
    "sector_period_scores",
    "sector_fund_flows",
    "stock_fund_flows",
    "stock_hot_ranks",
    "stock_lhb_records",
  ];
  const dailyBars = data?.stock_daily_bars;
  const financialReports = data?.stock_financial_reports;
  const turnoverCoverage = !Array.isArray(dailyBars) ? numberValue(dailyBars?.turnover_coverage_pct) : undefined;
  return (
    <div className="rounded-lg border p-3 text-sm">
      <div className="font-medium">数据质量和限制</div>
      {data && (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {tableNames.map((name) => {
              const item = data[name];
              const count = item && !Array.isArray(item) ? item.count : undefined;
              return <InfoCell key={name} label={name} value={count?.toLocaleString()} />;
            })}
          </div>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            <InfoCell label="日线成交额覆盖" value={formatPct(turnoverCoverage)} />
            <InfoCell label="可用于回测财报" value={(!Array.isArray(financialReports) ? financialReports?.count : 0)?.toLocaleString()} />
          </div>
        </>
      )}
      <ul className="mt-3 space-y-1 text-xs text-muted-foreground">
        {[...(data?.limitations ?? []), ...limitations].map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function sumMetric(rows: Array<Record<string, unknown>>, key: string) {
  return rows.reduce((total, row) => total + (numberValue(row[key]) ?? 0), 0);
}

function problemLabel(value: unknown) {
  const labels: Record<string, string> = {
    buy_point_bad: "买点问题",
    sell_giveback: "卖点回撤问题",
    sold_too_early: "卖早反弹",
    portfolio_capacity_miss: "满仓错过",
    replacement_bad: "替换交易变差",
    healthy_trend_winner: "趋势赢家",
    unknown: "未归类",
  };
  return labels[String(value ?? "unknown")] ?? String(value ?? "未归类");
}

function qualityItem(
  data: Awaited<ReturnType<typeof fetchBacktestReport>>["data_quality"] | undefined,
  key: string
): { count?: number; min_date?: string | null; max_date?: string | null } | undefined {
  const item = data?.[key];
  if (!item || Array.isArray(item)) return undefined;
  return {
    count: numberValue(item.count),
    min_date: typeof item.min_date === "string" ? item.min_date : null,
    max_date: typeof item.max_date === "string" ? item.max_date : null,
  };
}

function qualityRangeText(item?: { count?: number; min_date?: string | null; max_date?: string | null }) {
  const count = item?.count ?? 0;
  if (!count) return "无数据";
  const range = item?.min_date && item?.max_date ? `${item.min_date} 至 ${item.max_date}` : "日期未知";
  return `${count.toLocaleString()} / ${range}`;
}

function marketFundFlowCoverageStatus(
  sectorFlows?: { count?: number; min_date?: string | null; max_date?: string | null },
  stockFlows?: { count?: number; min_date?: string | null; max_date?: string | null }
) {
  if ((sectorFlows?.count ?? 0) > 0) {
    return {
      label: "可用",
      note: "板块资金流可用于市场资金状态和风险等级；资金回流/连续流出标签可以作为行情审计依据。",
    };
  }
  if ((stockFlows?.count ?? 0) > 0) {
    return {
      label: "局部参考",
      note: "当前没有板块资金流，只有个股资金流局部榜单。系统会标记为局部资金流，不能把它当成全市场资金流或行业主线资金。",
    };
  }
  return {
    label: "资金未知",
    note: "当前缺少可用资金流数据，市场状态主要来自指数、宽度和板块热度；不要把资金未知解释为资金正常。",
  };
}

function VerdictLine({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-md border bg-muted/20 p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 leading-6">{text}</div>
    </div>
  );
}

function TopCandidateMarketBucketTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestTopCandidateAudit>>["summary"]>["market_buckets"];
}) {
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">前10候选按大盘环境</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>环境</TableHead>
            <TableHead className="text-right">候选</TableHead>
            <TableHead className="text-right">已闭仓</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">平均收益</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">平均超额</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.regime}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.candidate_count}</TableCell>
              <TableCell className="text-right tabular-nums">{row.evaluated_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRate(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_return_pct))}>
                {formatPct(row.avg_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_benchmark_return_pct))}>
                {formatPct(row.avg_benchmark_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_excess_return_pct))}>
                {formatPct(row.avg_excess_return_pct)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function DynamicMarketBucketTable({
  title,
  rows,
}: {
  title: string;
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestTopCandidateAudit>>["summary"]>["dynamic_market_buckets"];
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>市场</TableHead>
            <TableHead className="text-right">候选</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">收益</TableHead>
            <TableHead className="text-right">超额</TableHead>
            <TableHead className="text-right">市场分</TableHead>
            <TableHead className="text-right">广度</TableHead>
            <TableHead className="text-right">风险</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${title}-${row.regime}`}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.candidate_count}</TableCell>
              <TableCell className="text-right tabular-nums">{row.evaluated_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRate(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_return_pct))}>
                {formatPct(row.avg_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_excess_return_pct))}>
                {formatPct(row.avg_excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.avg_market_score)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.avg_breadth_score)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.avg_risk_score)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function ThemeAlignmentBucketTable({
  title,
  rows,
}: {
  title: string;
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestTopCandidateAudit>>["summary"]>["theme_alignment_buckets"];
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">{title}</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>对齐</TableHead>
            <TableHead className="text-right">候选</TableHead>
            <TableHead className="text-right">样本</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">收益</TableHead>
            <TableHead className="text-right">超额</TableHead>
            <TableHead className="text-right">市场分</TableHead>
            <TableHead className="text-right">主线强度</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={`${title}-${row.alignment}`}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.candidate_count}</TableCell>
              <TableCell className="text-right tabular-nums">{row.evaluated_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRate(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_return_pct))}>
                {formatPct(row.avg_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_excess_return_pct))}>
                {formatPct(row.avg_excess_return_pct)}
              </TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.avg_market_score)}</TableCell>
              <TableCell className="text-right tabular-nums">{formatNumber(row.avg_theme_strength)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function CandidateObservationMarketBucketTable({
  rows,
}: {
  rows: NonNullable<Awaited<ReturnType<typeof fetchBacktestTopCandidateAudit>>["summary"]["candidate_observation"]>["market_buckets"];
}) {
  if (!rows?.length) return null;
  return (
    <div className="overflow-hidden rounded-lg border">
      <div className="border-b px-3 py-2 text-sm font-medium">前10候选固定持有观察</div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>环境</TableHead>
            <TableHead className="text-right">候选</TableHead>
            <TableHead className="text-right">可观察</TableHead>
            <TableHead className="text-right">胜率</TableHead>
            <TableHead className="text-right">观察收益</TableHead>
            <TableHead className="text-right">基准收益</TableHead>
            <TableHead className="text-right">观察超额</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.regime}>
              <TableCell className="font-medium">{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.candidate_count}</TableCell>
              <TableCell className="text-right tabular-nums">{row.observed_count}</TableCell>
              <TableCell className="text-right tabular-nums">{formatRate(row.win_rate)}</TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_return_pct))}>
                {formatPct(row.avg_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_benchmark_return_pct))}>
                {formatPct(row.avg_benchmark_return_pct)}
              </TableCell>
              <TableCell className={cn("text-right tabular-nums", priceColorClass(row.avg_excess_return_pct))}>
                {formatPct(row.avg_excess_return_pct)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function formatBenchmarkSources(sources?: Array<{ source: string; count: number }>) {
  if (!sources?.length) return "";
  return sources.map((item) => `${benchmarkSourceLabel(item.source)} ${item.count}`).join("、");
}

function formatDynamicMarketSources(sources?: Array<{ source: string; count: number }>) {
  if (!sources?.length) return "";
  return sources.map((item) => `${formatDynamicMarketSource(item.source)} ${item.count}`).join("、");
}

function benchmarkSourceLabel(source: string) {
  if (source === "index_daily_bars") return "指数日线";
  if (source === "equal_weight_stock_proxy") return "股票等权代理";
  if (source === "akshare_index_spot") return "AkShare指数";
  if (source === "unknown") return "未知";
  return source;
}

function formatDynamicMarketSource(source?: string | null) {
  if (!source) return "";
  if (source === "benchmark_return_20d_proxy") return "20日市场收益代理";
  if (source === "stock_daily_bars") return "指数/日线市场画像";
  if (source === "fallback") return "数据不足降级";
  return source;
}

function formatRate(value?: number | null) {
  return value == null ? "--" : formatPct(value * 100);
}

function formatRatioPct(value?: number | null) {
  return value == null ? "--" : formatPct(value);
}

function formatHoldingDays(value?: number | null) {
  return value == null ? "--" : `${formatNumber(value, 1)}天`;
}

function ratioToPctDelta(value?: number | null) {
  return value == null ? null : value * 100;
}

function formatSignedPct(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatPct(value)}`;
}

function formatSignedNumber(value?: number | null, digits = 2) {
  if (value == null || !Number.isFinite(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value, digits)}`;
}

function formatSignedAmount(value?: number | null) {
  if (value == null || !Number.isFinite(value)) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatAmount(value)}`;
}

function candidateQualityBucketKey(row: CandidateTradeQualityBucket, bucketKey: keyof CandidateTradeQualityBucket) {
  return String(row[bucketKey] ?? row.label ?? "unknown");
}

function candidateQualityBucketLabel(row: CandidateTradeQualityBucket, bucketKey: keyof CandidateTradeQualityBucket) {
  if (typeof row.label === "string" && row.label.trim()) return row.label;
  const value = String(row[bucketKey] ?? "unknown");
  if (bucketKey === "setup_family") return setupFamilyLabel(value);
  if (bucketKey === "market_phase") return phaseLabel(value);
  if (bucketKey === "exit_reason") return candidateQualityExitReasonLabel(value);
  return value;
}

function candidateQualitySampleMeta(row: CandidateTradeQualitySample) {
  const parts = [];
  if (row.rank != null) parts.push(`#${row.rank}`);
  if (row.score != null) parts.push(formatNumber(row.score, 1));
  return parts.length ? parts.join(" / ") : undefined;
}

function candidateQualityClusterText(row: CandidateTradeQualitySample) {
  const size = row.cluster_size == null ? "" : ` / ${row.cluster_size}天`;
  if (row.cluster_start_date && row.cluster_end_date && row.cluster_start_date !== row.cluster_end_date) {
    return `${row.cluster_start_date} - ${row.cluster_end_date}${size}`;
  }
  return `${row.cluster_start_date ?? row.entry_signal_date ?? "--"}${size}`;
}

function candidateQualityExitReasonLabel(value?: string | null) {
  const labels: Record<string, string> = {
    open: "仍持有",
    no_execute_bar: "无执行日线",
    limit_up_open_blocked: "涨停开盘阻塞",
    support_break: "跌破支撑",
    time_stop: "时间止损",
    take_profit: "止盈",
    trailing_stop: "回撤止盈",
    stop_loss: "止损",
  };
  return labels[String(value || "")] ?? String(value || "未归类");
}

function topFactorRows(
  rows?: Awaited<ReturnType<typeof fetchBacktestFactorAudit>>["by_setup"],
  limit = 6
) {
  return [...(rows ?? [])]
    .filter((row) => row.sample_count > 0)
    .sort((left, right) => right.sample_count - left.sample_count)
    .slice(0, limit);
}

function topPathRows(rows?: Array<Record<string, unknown>>, limit = 6) {
  return [...(rows ?? [])]
    .filter((row) => (numberValue(row.trade_count) ?? numberValue(row.sample_count) ?? 0) > 0)
    .sort((left, right) => (numberValue(right.trade_count) ?? numberValue(right.sample_count) ?? 0) - (numberValue(left.trade_count) ?? numberValue(left.sample_count) ?? 0))
    .slice(0, limit);
}

function factorSampleCount(audit?: Awaited<ReturnType<typeof fetchBacktestFactorAudit>>) {
  const value = audit?.summary?.sample_count ?? numberValue(audit?.coverage?.candidate_count);
  return value == null ? "--" : value.toLocaleString();
}

function factorBucketLabel(
  bucket: string,
  kind:
    | "setup"
    | "rank"
    | "market"
    | "ma"
    | "days"
    | "reclaim"
    | "warning"
    | "fund"
    | "launch"
    | "volume"
    | "close"
    | "generic" = "generic"
) {
  if (kind === "ma") {
    const labels: Record<string, string> = {
      "<3": "小于3%",
      "3-6": "3%至6%",
      "6-10": "6%至10%",
      ">10": "大于10%",
    };
    return labels[bucket] ?? bucket;
  }
  if (kind === "days") {
    const labels: Record<string, string> = {
      "0": "0天",
      "1-2": "1至2天",
      "3-5": "3至5天",
      "6-10": "6至10天",
      "10+": "10天以上",
    };
    return labels[bucket] ?? bucket;
  }
  const labels: Record<string, string> = {
    all: "全部",
    dragon_pullback: "龙回头回踩",
    low_position_reclaim: "低位承接转强",
    unknown: "未归类",
    top_10: "前10",
    top_20: "前20",
    top_100: "前100",
    outside_top_100: "100名外",
    false_bull: "假强势",
    choppy_rotation: "震荡轮动",
    strong_broad: "普涨强势",
    weak_risk_off: "弱势防守",
    narrow_theme: "窄牛主线",
    shrinking: "缩量",
    normal: "常量",
    moderate_expansion: "温和放量",
    double_volume: "倍量",
    explosive: "爆量",
    low: "低位收盘",
    middle: "中位收盘",
    high: "高位收盘",
    inflow: "资金流入",
    recovery: "资金回暖",
    outflow: "资金流出",
    panic_outflow: "恐慌流出",
    insufficient_data: "资金不足",
    clean: "无冲突",
    conflict: "低吸/龙回头重叠",
    none: "非低位承接",
    platform_accumulation_launch: "平台低吸首启",
    ma_support_reclaim: "均线承接上攻",
    deep_reclaim: "深回踩修复",
    warning: "风险提示",
    risk_off: "风险向下",
    strong: "强势",
    hot: "过热",
    overheated: "过热",
    unconfirmed_buildup: "低吸蓄势未确认",
    balanced_first_lift: "低吸首个均衡上拉",
    thin_volume_launch: "低吸启动量能偏弱",
    high_close_launch: "低吸启动收盘偏高",
    late_pullback_launch: "低吸启动回踩过久",
    repeated_launch: "低吸重复启动",
    other_confirmed_launch: "其他低吸确认",
    not_low_suction: "非低吸买点",
  };
  return labels[bucket] ?? bucket;
}

function notFilledReasonLabel(value?: string | null) {
  const labels: Record<string, string> = {
    none: "已成交",
    candidate_not_planned: "候选未进计划",
    planned_not_ordered: "计划未下单",
    ordered_not_filled: "下单未成交",
    outside_execution_top20: "不在执行前20",
    portfolio_full_no_rotation: "满仓未换仓",
    full_position_no_rotation: "满仓未换仓",
    limit_up_open_blocked: "开盘涨停买不到",
    no_execute_bar: "缺执行K线",
  };
  const key = String(value || "none");
  return labels[key] ?? key;
}

function notFilledSubreasonLabel(value?: string | null) {
  const labels: Record<string, string> = {
    none: "无",
    already_theoretical_holding: "理论层已持有",
    signal_event_missing: "信号计划缺失",
    candidate_cache_sparse_or_missing: "候选缓存稀疏",
    action_mismatch_resolved_to_watch: "旧BUY已修正为观察",
    execution_pool_filtered: "执行池过滤",
    date_outside_replay_window: "日期不在复盘范围",
    planned_not_ordered: "计划未下单",
    ordered_not_filled: "下单未成交",
    unknown_plan_gap: "未知计划差异",
  };
  const key = String(value || "none");
  return labels[key] ?? key;
}

function opportunityTypeLabel(value?: string | null) {
  const labels: Record<string, string> = {
    filled: "已成交",
    repeat_same_symbol_holding: "同股已持有",
    new_symbol_missed_full_portfolio: "满仓错过新标的",
    new_symbol_missed_with_open_slots: "有持仓但未买",
    new_symbol_missed_without_position_snapshot: "缺持仓快照",
  };
  const key = String(value || "unknown");
  return labels[key] ?? key;
}

function executionModelLabel(model?: string | null): string {
  if (model === "tail_close_hybrid") return "尾盘混合";
  if (model === "strict_1430") return "严格14:30";
  if (model === "legacy_next_open") return "旧版次日开盘";
  return model || "--";
}

function realityVerdict(report: Awaited<ReturnType<typeof fetchBacktestReport>>) {
  const quality = report.execution_quality;
  const dataAsOf = report.data_as_of_audit;
  const minuteRatio = numberValue(quality?.minute_1430_ratio ?? quality?.minute_tail_entry_ratio) ?? 0;
  const proxyRatio = numberValue(quality?.daily_close_proxy_ratio) ?? 0;
  const strictRejected = Number(quality?.strict_1430_rejected_count ?? quality?.strict_tail_rejected_count ?? 0);
  const gapRejected = Number(quality?.minute_gap_rejected_count ?? 0);
  const hasFutureWarning = dataAsOf?.status && dataAsOf.status !== "pass";
  const hasOverfitWarning = report.robustness_checks?.status && report.robustness_checks.status !== "pass";

  let label = "需复核";
  let className = "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";
  if (minuteRatio >= 80 && proxyRatio <= 20 && strictRejected === 0 && !hasFutureWarning) {
    label = "接近真实14:30";
    className = "border-green-200 bg-green-50 text-rise dark:border-green-500/30 dark:bg-green-500/10";
  } else if (proxyRatio >= 50 || gapRejected > 0 || strictRejected > 0) {
    label = "不能当纯真实";
  }

  const executionText =
    proxyRatio >= 50
      ? "收益主要按尾盘混合口径解读，当前大量买入使用执行日收盘价代理尾盘。"
      : minuteRatio >= 80
        ? "大多数买入使用 14:30 分钟快照，执行口径相对接近真实尾盘。"
        : "14:30 覆盖不足，必须结合收盘代理占比和严格拒单看结果。";
  const asOfText = hasFutureWarning
    ? "反未来函数审计存在警告，需要逐项检查数据可见时间。"
    : "当前审计显示日线和财报按交易日可见口径使用，未直接发现未来函数证据。";
  const numericText =
    strictRejected > 0 || gapRejected > 0
      ? "严格14:30存在拒单或缺快照，数值不能直接代表完整可执行策略。"
      : "费用、滑点、100股整数手和持仓资金已进入模拟，但仍需用严格模式对比收益。";
  const overfitText = hasOverfitWarning
    ? "反过拟合检查存在警告，不能用单次回测收益证明策略有效。"
    : "已有基础稳健性检查；仍需要多年全A、walk-forward 和基准超额验证。";

  return { label, className, executionText, asOfText, numericText, overfitText };
}
