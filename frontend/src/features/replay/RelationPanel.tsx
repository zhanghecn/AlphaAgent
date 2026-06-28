/** RelationPanel — 从行情反推的关联板块（侧滑面板，列表模式）。 */
import { useQuery } from "@tanstack/react-query";

import { LoadingState } from "@/components/LoadingState";
import { fetchReplayRelation } from "@/api/mainlineReplay";
import { cn } from "@/lib/utils";

export function RelationPanel({ sectorId, date }: { sectorId: string; date: string }) {
  const q = useQuery({
    queryKey: ["replayRelation", sectorId, date],
    queryFn: () => fetchReplayRelation(sectorId, date),
    enabled: !!sectorId && !!date,
    staleTime: 60_000,
  });

  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">🔗 关联板块（行情反推）</div>
      {q.isLoading ? (
        <LoadingState rows={4} />
      ) : (q.data?.items ?? []).length === 0 ? (
        <div className="text-xs text-muted-foreground">
          {q.data?.status === "insufficient_data" ? "历史评分点不足，无法计算关联。" : "暂无关联数据。"}
        </div>
      ) : (
        <div className="space-y-1">
          {(q.data?.items ?? []).map((it) => (
            <div key={it.sector_id} className="rounded-md border p-1.5">
              <div className="flex items-center justify-between">
                <span className="truncate text-xs font-medium">{it.name ?? it.sector_id}</span>
                <span className="ml-2 shrink-0 text-xs tabular-nums text-primary">
                  {Math.round(it.relation_score * 100)}%
                </span>
              </div>
              <div className="text-[10px] text-muted-foreground">{it.reason}</div>
              <div className="mt-1 h-1 overflow-hidden rounded bg-muted">
                <div className={cn("h-full bg-primary")} style={{ width: `${it.relation_score * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
