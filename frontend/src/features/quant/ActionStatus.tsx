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
  const refreshedCount = screen?.force_refreshed_count ?? 0;
  const newlyGeneratedCount = Math.max((screen?.generated_count ?? 0) - refreshedCount, 0);
  const refreshText = screen?.force_refresh
    ? `重算 ${refreshedCount} 日，新生成 ${newlyGeneratedCount} 日`
    : `新生成 ${screen?.generated_count ?? 0} 日，跳过 ${screen?.skipped_existing_count ?? 0} 日`;
  const screenText = screen && screen.total_dates
    ? `候选: ${screen.status}，${screen.start_date ?? "--"} 至 ${screen.end_date ?? "--"}，已处理 ${screen.processed_count ?? screen.total_dates}/${screen.total_dates}，${refreshText}，有候选 ${screen.succeeded_count ?? 0} 日，最新日推荐 ${screen.recommendation_count ?? 0}，累计推荐 ${screen.range_recommendation_count ?? 0}，同步 ${screen.portfolio_sync?.synced ?? 0}`
    : `候选: ${screen?.status}，推荐 ${screen?.recommendation_count ?? 0}，同步 ${screen?.portfolio_sync?.synced ?? 0}`;
  const statusText = status === "succeeded" ? "策略研究完成" : status === "failed" ? "策略研究失败" : status ? `策略研究: ${status}` : "";
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
      {statusText && <span className="mr-4 font-medium">{statusText}</span>}
      {screen && (
        <span className="mr-4">{screenText}</span>
      )}
      {backtestId && <span className="mr-4">回测: #{backtestId}</span>}
      {message && <span className={status === "failed" ? "text-destructive" : "text-muted-foreground"}>{message}</span>}
    </div>
  );
}
