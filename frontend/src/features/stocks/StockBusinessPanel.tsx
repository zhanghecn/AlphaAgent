import { useQuery } from "@tanstack/react-query";
import { fetchStockBusiness } from "@/api/stocks";
import type { StockBusiness } from "@/api/types";
import { CardSkeleton } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { dataSourceLabel, formatAmount } from "@/lib/utils";

interface StockBusinessPanelProps {
  vtSymbol: string;
}

export function StockBusinessPanel({ vtSymbol }: StockBusinessPanelProps) {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["stock-business", vtSymbol],
    queryFn: () => fetchStockBusiness(vtSymbol),
  });

  if (isLoading) return <CardSkeleton />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "主营业务加载失败"}
        onRetry={() => refetch()}
      />
    );

  const business = data as StockBusiness | null;
  const status = business?.source;
  const message = business?.message;

  if (status === "pending" || !business || (!business.summary && !business.business_scope)) {
    return (
      <EmptyState
        message="暂无主营业务数据"
        description={message ?? "AkShare 暂未返回该股票的主营业务或经营范围"}
      />
    );
  }

  return (
    <div className="space-y-4">
      {business.company && (
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <Info label="公司全称" value={business.company.full_name} />
          <Info label="行业" value={business.company.industry} />
          <Info label="市场" value={business.company.market} />
          <Info label="员工数" value={business.company.employees != null ? `${business.company.employees}` : null} />
        </div>
      )}
      {business.summary && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">概述</h4>
          <p className="text-sm leading-6">{business.summary}</p>
        </div>
      )}
      {business.business_scope && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">经营范围</h4>
          <p className="line-clamp-5 text-sm leading-6">{business.business_scope}</p>
        </div>
      )}
      {Array.isArray(business.main_products) && business.main_products.length > 0 && (
        <div>
          <h4 className="text-sm font-medium text-muted-foreground mb-1">主要产品</h4>
          <div className="flex flex-wrap gap-2">
            {(business.main_products as string[]).map((p, i) => (
              <span key={i} className="text-xs bg-muted px-2 py-1 rounded">{p}</span>
            ))}
          </div>
        </div>
      )}
      {business.segments && business.segments.length > 0 && (
        <div>
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h4 className="text-sm font-medium text-muted-foreground">主营构成</h4>
            {business.report_date && (
              <span className="text-xs text-muted-foreground">报告期 {business.report_date.slice(0, 10)}</span>
            )}
          </div>
          <div className="space-y-2">
            {business.segments.slice(0, 8).map((segment, index) => (
              <div key={`${segment.name}-${segment.rank}-${segment.report_date}-${index}`} className="rounded-md border p-3">
                <div className="flex items-center justify-between gap-3 text-sm">
                  <span className="font-medium">{segment.name ?? "--"}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {segment.revenue_ratio != null ? `${segment.revenue_ratio.toFixed(2)}%` : "--"}
                  </span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded bg-muted">
                  <div
                    className="h-full rounded bg-primary"
                    style={{ width: `${Math.max(0, Math.min(100, segment.revenue_ratio ?? 0))}%` }}
                  />
                </div>
                <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                  <span>收入 {formatAmount(segment.revenue)}</span>
                  <span>毛利率 {segment.gross_profit_ratio != null ? `${segment.gross_profit_ratio.toFixed(2)}%` : "--"}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {business.source && (
        <p className="text-xs text-muted-foreground" title={business.source}>
          数据: {dataSourceLabel(business.source)}
        </p>
      )}
    </div>
  );
}

function Info({ label, value }: { label: string; value: string | number | null | undefined }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 break-words text-sm font-medium">{value ?? "--"}</p>
    </div>
  );
}
