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
        {report.summary_rows
          .filter((row) => !["initial_cash", "final_equity", "average_win", "average_loss"].includes(row.key))
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
        <InfoCell label="买入/卖出/持仓中" value={tradePathLabel(report)} />
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
        <InfoCell label="买入/卖出/持仓中" value={tradePathLabel(report)} />
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
        <InfoCell label="执行时点" value={method?.execution_timing ?? report.assumptions.execution} />
        <InfoCell label="股票池" value={method?.universe ?? `${report.sample.symbol_count} 只样本`} />
        <InfoCell label="候选口径" value={method?.candidate_policy ?? "历史逐日动态候选"} />
      </div>
      {audit?.note && <div className="mt-3 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">{audit.note}</div>}
    </div>
  );
}
