export function ActionStatus({
  screen,
  backtestId,
  autoBuy,
}: {
  screen?: {
    status: string;
    start_date?: string;
    end_date?: string;
    total_dates?: number;
    succeeded_count?: number;
    recommendation_count?: number;
    range_recommendation_count?: number;
    portfolio_sync?: { synced: number } | null;
  };
  backtestId?: number | null;
  autoBuy?: { status: string; filled?: number; auto_position_sync?: { synced: number } };
}) {
  const screenText = screen?.total_dates
    ? `候选: ${screen.status}，${screen.start_date ?? "--"} 至 ${screen.end_date ?? "--"}，交易日 ${screen.succeeded_count ?? screen.total_dates}/${screen.total_dates}，最新日推荐 ${screen.recommendation_count ?? 0}，累计推荐 ${screen.range_recommendation_count ?? 0}，同步 ${screen.portfolio_sync?.synced ?? 0}`
    : `候选: ${screen?.status}，推荐 ${screen?.recommendation_count ?? 0}，同步 ${screen?.portfolio_sync?.synced ?? 0}`;
  return (
    <div className="rounded-lg border bg-muted/30 px-4 py-3 text-sm">
      {screen && (
        <span className="mr-4">{screenText}</span>
      )}
      {backtestId && <span className="mr-4">回测: #{backtestId}</span>}
      {autoBuy && <span>模拟建仓: {autoBuy.status}，成交 {autoBuy.filled ?? 0}，持仓分组同步 {autoBuy.auto_position_sync?.synced ?? 0}</span>}
    </div>
  );
}
