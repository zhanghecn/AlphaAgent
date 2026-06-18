import { BarChart3, Download, RefreshCw } from "lucide-react";
import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";
import { formatNumber, formatRobustnessValue, robustnessStatus } from "@/lib/backtest-utils";
import { InfoCell } from "@/components/InfoCell";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  backtestValidationGridCsvUrl,
  fetchBacktestExecutionModelComparison,
  fetchBacktestReport,
  fetchBacktestTopCandidateAudit,
  fetchBacktestValidationGrid,
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
}: {
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  topCandidateAudit?: Awaited<ReturnType<typeof fetchBacktestTopCandidateAudit>>;
  isTopCandidateAuditLoading?: boolean;
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
  const hasAnalysis = yearlyRows.length > 0 || Boolean(regimeAnalysis?.periods?.length) || Boolean(summary);

  if (!hasAnalysis && !isTopCandidateAuditLoading) return null;

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
  const tableNames = ["stocks", "stock_daily_bars", "stock_financial_reports", "sector_period_scores", "stock_fund_flows", "stock_hot_ranks", "stock_lhb_records"];
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
