/** RelationPanel — 从行情反推的关联概念（侧滑面板，列表模式）。 */
import { useQuery } from "@tanstack/react-query";

import { LoadingState } from "@/components/LoadingState";
import { fetchReplayRelation, type RelationItem } from "@/api/mainlineReplay";
import { cn } from "@/lib/utils";

export function RelationPanel({
  sectorId,
  date,
  onSelectSector,
}: {
  sectorId: string;
  date: string;
  onSelectSector?: (sector: RelationItem) => void;
}) {
  const q = useQuery({
    queryKey: ["replayRelation", sectorId, date],
    queryFn: () => fetchReplayRelation(sectorId, date),
    enabled: !!sectorId && !!date,
    staleTime: 60_000,
  });

  return (
    <div>
      <div className="mb-1 text-xs text-muted-foreground">关联概念（行情反推 · {date}）</div>
      {q.isLoading ? (
        <LoadingState rows={4} />
      ) : (q.data?.items ?? []).length === 0 ? (
        <div className="text-xs text-muted-foreground">
          {q.data?.status === "unsupported_sector_type"
            ? "该标的不是概念，已从概念主线排除。"
            : q.data?.status === "insufficient_data"
              ? "历史评分点不足，无法计算关联。"
              : "暂无关联数据。"}
        </div>
      ) : (
        <div className="space-y-1">
          {(q.data?.items ?? []).map((it) => (
            <button
              key={it.sector_id}
              onClick={() => onSelectSector?.(it)}
              className="w-full rounded-md border p-1.5 text-left transition-colors hover:bg-muted/60 focus:outline-none focus-visible:ring-1 focus-visible:ring-indigo-400"
              title={`点击查看 ${it.name ?? it.sector_id} 的资金流向和成分股`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-xs font-medium">{it.name ?? it.sector_id}</span>
                <span className="shrink-0 text-xs tabular-nums text-primary">
                  {Math.round(it.relation_score * 100)}%
                </span>
              </div>
              <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                <span className="truncate">{it.reason}</span>
                <span className="shrink-0">题材</span>
              </div>
              <div className="mt-0.5 truncate text-[10px] text-muted-foreground/80">
                {evidenceText(it)}
              </div>
              <div className="mt-1 h-1 overflow-hidden rounded bg-muted">
                <div className={cn("h-full bg-primary")} style={{ width: `${it.relation_score * 100}%` }} />
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function evidenceText(item: RelationItem): string {
  const shared = item.evidence?.shared_symbols ?? [];
  const commonPoints = item.common_points ?? item.evidence?.common_points;
  const parts = [
    commonPoints ? `${commonPoints} 个共同交易点` : "",
    shared.length ? `共享 ${shared.slice(0, 3).join("、")}` : "无共享成分",
  ].filter(Boolean);
  return parts.join(" · ");
}
