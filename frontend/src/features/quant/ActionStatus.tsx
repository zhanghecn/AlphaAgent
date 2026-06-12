export function ActionStatus({
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
