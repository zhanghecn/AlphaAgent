import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchIndexDetail, fetchIndexIndicators } from "@/api/indices";
import { StockKlineChart } from "@/features/stocks/StockKlineChart";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { formatPrice, formatPct, formatAmount, priceColorClass } from "@/lib/utils";
import { TechnicalIndicatorView } from "@/features/stocks/StockIndicatorPanel";
import type { IndexQuote } from "@/api/types";

export function IndexDetailPage() {
  const { key } = useParams<{ key: string }>();

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["index-detail", key],
    queryFn: () => fetchIndexDetail(key!),
    enabled: !!key,
  });

  const indicatorQuery = useQuery({
    queryKey: ["index-indicators", key],
    queryFn: () => fetchIndexIndicators(key!),
    enabled: !!key,
  });

  if (!key) return <ErrorState message="无效的指数代码" />;
  if (isLoading) return <LoadingState rows={6} />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载指数详情失败"}
        onRetry={() => refetch()}
      />
    );

  const index = data as IndexQuote;
  const name = index.name ?? key;
  const lastPrice = index.last_price;
  const changePct = index.change_pct;
  const turnover = index.turnover;
  const source = index.source;
  const colorClass = priceColorClass(changePct);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-display break-words text-2xl font-bold">{name}</h2>
          <Badge variant="outline">{key}</Badge>
        </div>
        <div className="flex flex-wrap items-baseline gap-4">
          <span className={`font-display text-4xl font-bold tabular-nums ${colorClass}`}>
            {formatPrice(lastPrice)}
          </span>
          <span className={`text-lg tabular-nums ${colorClass}`}>
            {formatPct(changePct)}
          </span>
          <span className="text-sm text-muted-foreground">
            成交额 {formatAmount(turnover)}
          </span>
        </div>
        {source && (
          <p className="text-xs text-muted-foreground">数据源: {source}</p>
        )}
      </div>

      {/* K-Line Chart */}
      <div className="rounded-lg border p-3 sm:p-4">
        <StockKlineChart vtSymbol={key} isIndex />
      </div>

      <div className="rounded-lg border p-3 sm:p-4">
        <h3 className="font-display mb-3 text-sm font-medium">指数指标</h3>
        {indicatorQuery.isLoading ? (
          <LoadingState rows={2} />
        ) : indicatorQuery.isError ? (
          <ErrorState
            message={
              indicatorQuery.error instanceof Error
                ? indicatorQuery.error.message
                : "加载指数指标失败"
            }
            onRetry={() => indicatorQuery.refetch()}
          />
        ) : (
          <TechnicalIndicatorView indicators={indicatorQuery.data} />
        )}
      </div>
    </div>
  );
}
