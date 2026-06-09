import { useQuery } from "@tanstack/react-query";
import { fetchStockIndustryChain } from "@/api/stocks";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Badge } from "@/components/ui/badge";
import { formatAmount } from "@/lib/utils";

interface StockIndustryChainPanelProps {
  vtSymbol: string;
}

interface ChainEvidence {
  keyword?: string;
  category?: string;
  content?: string;
  source?: string;
}

interface ChainExposure {
  name?: string | null;
  revenue?: number | null;
  revenue_ratio?: number | null;
  gross_profit_ratio?: number | null;
}

interface ChainSector {
  id?: string;
  name?: string;
  type?: string;
  rank?: number;
  source?: string;
}

interface StockChain {
  chain_name?: string | null;
  position?: string | null;
  upstream?: string[];
  midstream?: string[];
  downstream?: string[];
  exposure?: ChainExposure[];
  sectors?: ChainSector[];
  evidence?: ChainEvidence[];
  matched_by?: string[];
  status?: string;
  source?: string;
  message?: string;
}

export function StockIndustryChainPanel({ vtSymbol }: StockIndustryChainPanelProps) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["stock-industry-chain", vtSymbol],
    queryFn: () => fetchStockIndustryChain(vtSymbol),
  });

  if (isLoading) return <CardSkeleton />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "产业链数据加载失败"}
        onRetry={() => refetch()}
      />
    );

  const chain = data as StockChain | null;
  const midstream = chain?.midstream ?? [];
  const hasData = Boolean(chain?.chain_name || midstream.length || chain?.sectors?.length || chain?.exposure?.length);

  if (!chain || !hasData) {
    return (
      <EmptyState
        message="暂无业务板块线索"
        description={chain?.message ?? "AkShare 暂未返回足够的主营、板块或概念线索"}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h4 className="text-base font-semibold">{chain.chain_name ?? "业务板块线索"}</h4>
          {chain.position && <p className="text-xs text-muted-foreground">识别位置: {chain.position}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          {chain.status && <Badge variant={chain.status === "matched" ? "default" : "secondary"}>{chain.status}</Badge>}
          {chain.source && <Badge variant="outline">{chain.source}</Badge>}
        </div>
      </div>

      {chain.matched_by && chain.matched_by.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-xs text-muted-foreground">匹配词</span>
          {chain.matched_by.map((keyword) => (
            <Badge key={keyword} variant="secondary">
              {keyword}
            </Badge>
          ))}
        </div>
      )}

      {midstream.length > 0 && <ChainSegment title="公司业务线索" items={midstream} highlight />}

      {chain.sectors && chain.sectors.length > 0 && (
        <div>
          <h5 className="mb-2 text-sm font-medium">所属板块</h5>
          <div className="flex flex-wrap gap-2">
            {chain.sectors.slice(0, 16).map((sector) => (
              <Badge
                key={`${sector.id ?? sector.name}-${sector.type ?? ""}`}
                variant={sector.type === "industry" ? "default" : "secondary"}
              >
                {sector.name ?? sector.id}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {chain.exposure && chain.exposure.length > 0 && (
        <div>
          <h5 className="mb-2 text-sm font-medium">业务占比</h5>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {chain.exposure.slice(0, 9).map((item, index) => (
              <div key={`${item.name ?? "exposure"}-${index}`} className="rounded-md border p-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">{item.name ?? "--"}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {item.revenue_ratio != null ? `${item.revenue_ratio.toFixed(2)}%` : "--"}
                  </span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full rounded bg-primary"
                    style={{ width: `${Math.max(0, Math.min(100, item.revenue_ratio ?? 0))}%` }}
                  />
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  收入 {formatAmount(item.revenue)}
                  {item.gross_profit_ratio != null ? ` / 毛利率 ${item.gross_profit_ratio.toFixed(2)}%` : ""}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {chain.evidence && chain.evidence.length > 0 && (
        <div>
          <h5 className="mb-2 text-sm font-medium">识别证据</h5>
          <div className="space-y-2">
            {chain.evidence.map((item, index) => (
              <details key={`${item.keyword}-${index}`} className="rounded-md border p-3">
                <summary className="cursor-pointer text-sm font-medium">
                  {item.keyword ?? "线索"} {item.category ? <span className="text-muted-foreground">/ {item.category}</span> : null}
                </summary>
                {item.content && <p className="mt-2 text-sm leading-6 text-muted-foreground">{item.content}</p>}
              </details>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ChainSegment({ title, items, highlight = false }: { title: string; items: string[]; highlight?: boolean }) {
  return (
    <div className={`rounded-md border p-3 ${highlight ? "bg-muted/50" : ""}`}>
      <h5 className="mb-2 text-xs font-medium text-muted-foreground">{title}</h5>
      {items.length === 0 ? (
        <p className="text-xs text-muted-foreground/70">暂无结构化数据</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map((item) => (
            <span key={item} className="rounded bg-background px-2 py-1 text-xs">
              {item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
