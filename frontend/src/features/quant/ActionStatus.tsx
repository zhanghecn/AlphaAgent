export function ActionStatus({
  screen,
  backtestId,
  status,
  message,
}: {
  screen?: {
    status: string;
    start_date?: string;
    end_date?: string;
    total_dates?: number;
    succeeded_count?: number;
    processed_count?: number;
    generated_count?: number;
    skipped_existing_count?: number;
    force_refreshed_count?: number;
    force_refresh?: boolean;
    recommendation_count?: number;
    range_recommendation_count?: number;
    portfolio_sync?: { synced: number } | null;
  };
  backtestId?: number | null;
  status?: string;
  message?: string | null;
}) {
  const screenText = screen && screen.total_dates
    ? `覆盖 ${screen.start_date ?? "--"} 至 ${screen.end_date ?? "--"}，已完成 ${screen.processed_count ?? screen.total_dates}/${screen.total_dates} 个交易日，最新候选 ${screen.recommendation_count ?? 0} 只`
    : `最新候选 ${screen?.recommendation_count ?? 0} 只`;
  const statusText = status === "succeeded" ? "策略研究完成" : status === "failed" ? "策略研究失败" : status ? `策略研究: ${status}` : "";
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
      {statusText && <span className="mr-4 font-medium">{statusText}</span>}
      {screen && (
        <span className="mr-4">{screenText}</span>
      )}
      {backtestId && <span className="mr-4">自动回测 #{backtestId}</span>}
      {message && <span className={status === "failed" ? "text-destructive" : "text-muted-foreground"}>{message}</span>}
    </div>
  );
}
