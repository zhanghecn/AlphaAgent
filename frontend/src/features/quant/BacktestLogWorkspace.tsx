import { fetchBacktestAudit, fetchBacktestReport } from "@/api/quant";
import { InfoCell } from "@/components/InfoCell";
import { LoadingState } from "@/components/LoadingState";
import { BacktestOrderStatsPanel } from "./BacktestAnalysis";

export function BacktestLogWorkspace({
  report,
  audit,
  isLoading,
}: {
  report?: Awaited<ReturnType<typeof fetchBacktestReport>>;
  audit?: Awaited<ReturnType<typeof fetchBacktestAudit>>;
  isLoading: boolean;
}) {
  if (isLoading) return <LoadingState rows={4} />;

  if (!report && !audit) {
    return (
      <div className="rounded-lg border p-6 text-center text-sm text-muted-foreground">
        暂无日志数据。选择或运行回测后可查看审计日志。
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {audit && <BacktestAuditPanel audit={audit} />}
      {report?.order_stats && <BacktestOrderStatsPanel stats={report.order_stats} />}
    </div>
  );
}

export function BacktestAuditPanel({
  audit,
}: {
  audit: NonNullable<Awaited<ReturnType<typeof fetchBacktestAudit>>>;
}) {
  return (
    <div className="rounded-lg border p-4 text-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="font-medium">回测审计日志</div>
        <span className="text-xs text-muted-foreground">
          #{audit.backtest_id} {audit.strategy_id} / {audit.strategy_version}
        </span>
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <InfoCell label="区间" value={`${audit.start_date} 至 ${audit.end_date}`} />
        <InfoCell label="订单事件" value={`${audit.orders.length}条`} />
        <InfoCell label="成交记录" value={`${audit.trades.length}条`} />
        <InfoCell label="其他事件" value={`${audit.events.length}条`} />
      </div>

      {audit.note && (
        <div className="mt-3 rounded-md border bg-muted/30 p-2 text-xs text-muted-foreground">
          {audit.note}
        </div>
      )}

      {audit.order_summary && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <InfoCell label="订单总数" value={`${audit.order_summary.total}笔`} />
          <InfoCell label="已成交" value={`${audit.order_summary.by_status.filled ?? 0}笔`} />
          <InfoCell label="未成交" value={`${audit.order_summary.by_status.rejected ?? 0}笔`} />
        </div>
      )}
    </div>
  );
}
