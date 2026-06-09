import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { fetchStockSectors } from "@/api/stocks";
import type { SectorInfo } from "@/api/types";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { dataSourceLabel } from "@/lib/utils";

interface StockSectorPanelProps {
  vtSymbol: string;
}

export function StockSectorPanel({ vtSymbol }: StockSectorPanelProps) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["stock-sectors", vtSymbol],
    queryFn: () => fetchStockSectors(vtSymbol),
  });

  if (isLoading) return <CardSkeleton />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "板块数据加载失败"}
        onRetry={() => refetch()}
      />
    );

  const items = data?.items as SectorInfo[] | undefined;
  const message = data?.message;

  if (!items || items.length === 0) {
    return (
      <EmptyState
        message="暂无板块数据"
        description={message ?? "AkShare 暂未返回可匹配的行业、概念、主题或地域板块"}
      />
    );
  }

  const confirmedItems = items.filter((item) => item.confirmed !== false);
  const candidateItems = items.filter((item) => item.confirmed === false);

  const grouped = confirmedItems.reduce<Record<string, SectorInfo[]>>((acc, item) => {
    const key = item.type || "concept";
    acc[key] = acc[key] ?? [];
    acc[key].push(item);
    return acc;
  }, {});

  return (
    <div className="space-y-4">
      {sectorTypeOrder(Object.keys(grouped)).map((type) => (
        <div key={type}>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground">
            {typeLabel(type)}
          </h4>
          <div className="flex flex-wrap gap-2">
            {grouped[type].map((item) => (
              <Link key={`${item.id}-${item.name}`} to={`/explore?sector=${encodeURIComponent(item.id)}`}>
                <Badge
                  variant={type === "industry" ? "default" : "secondary"}
                  title={item.confirmation ?? item.source}
                  className="cursor-pointer hover:opacity-80 transition-opacity"
                >
                  {item.name}
                  {item.change_pct != null && (
                    <span className={item.change_pct >= 0 ? "ml-1 text-red-400" : "ml-1 text-green-400"}>
                      {item.change_pct >= 0 ? "+" : ""}{item.change_pct.toFixed(1)}%
                    </span>
                  )}
                  {item.rank ? <span className="ml-1 opacity-70">#{item.rank}</span> : null}
                  {item.is_precise ? <span className="ml-1 opacity-70">精准</span> : null}
                </Badge>
              </Link>
            ))}
          </div>
        </div>
      ))}
      {candidateItems.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground">候选线索</h4>
          <div className="flex flex-wrap gap-2">
            {candidateItems.map((item) => (
              <Badge
                key={`${item.id}-${item.name}`}
                variant="outline"
                title={item.confirmation ?? item.source}
                className="text-muted-foreground"
              >
                {item.name}
              </Badge>
            ))}
          </div>
        </div>
      )}
      {data?.source && (
        <p className="text-xs text-muted-foreground" title={data.source}>
          数据: {dataSourceLabel(data.source)}
        </p>
      )}
    </div>
  );
}

function typeLabel(type: string) {
  if (type === "industry") return "行业";
  if (type === "region") return "地域";
  if (type === "theme") return "主题";
  return "概念";
}

function sectorTypeOrder(types: string[]) {
  const order: Record<string, number> = { industry: 0, concept: 1, region: 2, theme: 3 };
  return [...types].sort((a, b) => (order[a] ?? 9) - (order[b] ?? 9));
}
