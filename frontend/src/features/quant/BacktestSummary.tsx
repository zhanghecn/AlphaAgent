import { AlertTriangle, FileText, ShieldCheck } from "lucide-react";
import { cn, formatPct } from "@/lib/utils";
import { backtestTrustVerdict, formatMetric, metricColor } from "@/lib/backtest-utils";
import { InfoCell } from "@/components/InfoCell";
import { fetchBacktestAudit, fetchBacktestReport } from "@/api/quant";

export function BacktestSummary({
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
        <InfoCell label="执行时点" value={method?.execution_timing ?? report.assumptions.execution} />
        <InfoCell label="股票池" value={method?.universe ?? `${report.sample.symbol_count} 只样本`} />
        <InfoCell label="候选口径" value={method?.candidate_policy ?? "历史逐日动态候选"} />
      </div>
      {audit?.note && <div className="mt-3 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">{audit.note}</div>}
    </div>
  );
}
