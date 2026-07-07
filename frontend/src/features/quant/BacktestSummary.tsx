import { AlertTriangle, FileText, ShieldCheck } from "lucide-react";
import { cn, formatPct } from "@/lib/utils";
import { backtestTrustVerdict, formatMetric, metricColor } from "@/lib/backtest-utils";
import { InfoCell } from "@/components/InfoCell";
import { fetchBacktestAudit, fetchBacktestCandidateTradeQualityReport, fetchBacktestReport } from "@/api/quant";

export function BacktestSummary({
  report,
  audit,
  candidateQuality,
  candidateQualityLoading = false,
}: {
  report: Awaited<ReturnType<typeof fetchBacktestReport>>;
  audit?: Awaited<ReturnType<typeof fetchBacktestAudit>>;
  candidateQuality?: Awaited<ReturnType<typeof fetchBacktestCandidateTradeQualityReport>>;
  candidateQualityLoading?: boolean;
}) {
  const candidateSummary = candidateQuality?.summary;
  const candidatePending = candidateQualityLoading && !candidateQuality;
  return (
    <div className="space-y-4">
      <BacktestTrustPanel report={report} />
      <BacktestMethodPanel report={report} audit={audit} />
      <div className="rounded-lg border p-3">
        <div className="text-sm font-medium">候选 Top20 D+1 验证</div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <MetricTile label="D+1胜率" value={formatCandidateRate(candidateSummary?.win_rate, candidatePending)} />
          <MetricTile label="D+1质量胜率" value={formatCandidateRate(candidateSummary?.quality_win_rate, candidatePending)} />
          <MetricTile label="年度胜率" value={formatYearlyWinRate(candidateQuality, candidatePending)} />
          <MetricTile label="D+1平均收益" value={formatCandidatePct(candidateSummary?.average_return_pct, candidatePending)} tone={candidateSummary?.average_return_pct} />
          <MetricTile label="D+1接近涨停" value={formatCandidateRate(candidateSummary?.d1_near_limit_up_rate, candidatePending)} />
          <MetricTile label="可评价候选" value={formatCount(candidateSummary?.evaluated_count, candidatePending)} />
        </div>
      </div>
      <div className="rounded-lg border p-3">
        <div className="text-sm font-medium">组合诊断指标</div>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricTile label="组合总收益" value={formatPct(report.metrics.total_return_pct)} tone={report.metrics.total_return_pct} />
          <MetricTile label="组合年化收益" value={formatPct(report.metrics.annual_return_pct)} tone={report.metrics.annual_return_pct} />
          <MetricTile label="组合胜率" value={formatMetric("win_rate", report.metrics.win_rate ?? null)} />
          <MetricTile label="最大回撤" value={formatPct(report.metrics.max_drawdown_pct)} tone={report.metrics.max_drawdown_pct} />
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {report.summary_rows
          .filter((row) => !["initial_cash", "final_equity", "average_win", "average_loss", "total_return_pct", "annual_return_pct", "max_drawdown_pct", "win_rate"].includes(row.key))
          .slice(0, 8)
          .map((row) => (
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
        <InfoCell label="组合买入/卖出/持仓中" value={tradePathLabel(report)} />
      </div>
    </div>
  );
}

function MetricTile({ label, value, tone }: { label: string; value: string; tone?: number | null }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-1 text-lg font-semibold tabular-nums", tone == null ? "" : tone > 0 ? "text-rise" : tone < 0 ? "text-fall" : "")}>
        {value}
      </div>
    </div>
  );
}

function formatCandidatePct(value?: number | null, pending = false) {
  if (pending && value == null) return "计算中...";
  return formatPct(value);
}

function formatCandidateRate(value?: number | null, pending = false) {
  if (pending && value == null) return "计算中...";
  if (value == null) return "--";
  return `${value.toFixed(2)}%`;
}

function formatCount(value?: number | null, pending = false) {
  if (pending && value == null) return "计算中...";
  if (value == null) return "--";
  return value.toLocaleString();
}

function formatYearlyWinRate(report?: Awaited<ReturnType<typeof fetchBacktestCandidateTradeQualityReport>>, pending = false) {
  const yearly = report?.yearly ?? [];
  const valid = yearly.filter((row) => row.win_rate != null);
  if (pending && !valid.length) return "计算中...";
  if (!valid.length) return "--";
  const positiveYears = valid.filter((row) => (row.win_rate ?? 0) >= 50).length;
  const avg = valid.reduce((sum, row) => sum + Number(row.win_rate ?? 0), 0) / valid.length;
  return `${avg.toFixed(2)}% / ${positiveYears}/${valid.length}年`;
}

export function BacktestTrustPanel({
  report,
}: {
  report: Awaited<ReturnType<typeof fetchBacktestReport>>;
}) {
  const verdict = backtestTrustVerdict(report);
  return (
    <div
      className={cn(
        "rounded-lg border p-3 text-sm",
        verdict.status === "invalid" && "border-red-200 bg-red-50 dark:border-red-500/30 dark:bg-red-500/10",
        verdict.status === "warning" && "border-amber-200 bg-amber-50 dark:border-amber-500/30 dark:bg-amber-500/10",
        verdict.status === "pass" && "border-green-200 bg-green-50 dark:border-green-500/30 dark:bg-green-500/10"
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
        <span className={cn("rounded-md border bg-background px-2 py-1 text-xs", verdict.status === "invalid" ? "text-fall" : verdict.status === "pass" ? "text-rise" : "text-amber-700 dark:text-amber-300")}>
          {verdict.label}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-6">
        <InfoCell label="撮合版本" value={report.strategy_version} />
        <InfoCell label="买入方式" value={verdict.entryMode} />
        <InfoCell label="执行模型" value={executionModelLabel(report.method?.execution?.execution_model)} />
        <InfoCell label="开盘执行占比" value={formatPct(report.execution_quality?.daily_open_fallback_ratio)} />
        <InfoCell label="收盘执行占比" value={formatPct(report.execution_quality?.daily_close_proxy_ratio)} />
        <InfoCell label="组合买入/卖出/持仓中" value={tradePathLabel(report)} />
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

function executionModelLabel(model?: string | null): string {
  if (model === "legacy_next_open") return "日线D+1开盘";
  if (model === "tail_close_hybrid") return "日线收盘代理";
  if (model === "strict_1430") return "实时分钟";
  return model || "--";
}

function tradePathLabel(report: Awaited<ReturnType<typeof fetchBacktestReport>>) {
  const metrics = report.metrics ?? {};
  const extended = report.extended_metrics;
  const buyCount = extended?.buy_count ?? metrics.buy_count ?? 0;
  const sellCount = extended?.sell_count ?? metrics.sell_count ?? report.closed_trade_count ?? metrics.trade_count ?? 0;
  const openCount = extended?.open_trade_count ?? metrics.open_trade_count ?? Math.max(buyCount - sellCount, 0);
  return `${buyCount} / ${sellCount} / ${openCount} 笔`;
}

export function BacktestMethodPanel({
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
        <InfoCell label="组合执行时点" value={method?.execution_timing ?? report.assumptions.execution} />
        <InfoCell label="股票池" value={method?.universe ?? `${report.sample.symbol_count} 只样本`} />
        <InfoCell label="候选口径" value={method?.candidate_policy ?? "历史逐日动态候选"} />
      </div>
      {audit?.note && <div className="mt-3 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">{audit.note}</div>}
    </div>
  );
}
