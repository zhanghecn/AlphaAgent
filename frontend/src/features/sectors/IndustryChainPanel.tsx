import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchIndustryChains, fetchIndustryChainStocks } from "@/api/sectors";
import type { IndustryChainInfo, StockQuote } from "@/api/types";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { formatAmount, formatMarketCap, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

export function IndustryChainPanel() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["industry-chains"],
    queryFn: fetchIndustryChains,
  });

  const chains = useMemo(() => data?.items ?? [], [data]);
  const selected = chains.find((chain) => chain.id === selectedId) ?? chains[0] ?? null;

  if (isLoading) return <LoadingState rows={3} />;
  if (isError)
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "产业链数据加载失败"}
        onRetry={() => refetch()}
      />
    );

  return (
    <div className="grid gap-4 xl:grid-cols-[440px_minmax(0,1fr)]">
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-sm font-medium">动态板块聚类</h3>
          <div className="flex flex-wrap gap-1.5">
            {data?.source && <Badge variant="outline">{data.source}</Badge>}
            {data?.sector_status && <Badge variant={data.sector_status === "ready" ? "secondary" : "outline"}>{data.sector_status}</Badge>}
          </div>
        </div>
        <div className="max-h-[760px] overflow-auto rounded-md border">
          <div className="space-y-3 p-3">
            {chains.map((chain) => (
              <ChainCard
                key={chain.id}
                chain={chain}
                active={selected?.id === chain.id}
                onSelect={() => setSelectedId(chain.id)}
              />
            ))}
          </div>
        </div>
      </section>

      <IndustryChainStocks chain={selected} />
    </div>
  );
}

function ChainCard({
  chain,
  active,
  onSelect,
}: {
  chain: IndustryChainInfo;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-md border p-3 text-left transition-colors hover:bg-muted ${
        active ? "border-primary bg-muted" : "bg-background"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-semibold">{chain.name}</h3>
        <span className="text-xs text-muted-foreground">{chain.id}</span>
      </div>
      {chain.keywords && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {chain.keywords.slice(0, 8).map((keyword) => (
            <Badge key={keyword} variant="secondary">
              {keyword}
            </Badge>
          ))}
        </div>
      )}
      {chain.segments && chain.segments.length > 0 && (
        <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
          {chain.segments.map((segment) => (
            <div key={segment.stage} className="space-y-1">
              <p className="text-muted-foreground">{segment.label}</p>
              <p className="line-clamp-3 leading-5 text-foreground">
                {(segment.items ?? []).slice(0, 4).join(" / ") || "--"}
              </p>
            </div>
          ))}
        </div>
      )}
      {chain.related_sectors && chain.related_sectors.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          <span className="text-xs text-muted-foreground">关联板块</span>
          {chain.related_sectors.slice(0, 6).map((sector) => (
            <Badge key={sector.id} variant="outline">
              {sector.name}
            </Badge>
          ))}
        </div>
      )}
    </button>
  );
}

function IndustryChainStocks({ chain }: { chain: IndustryChainInfo | null }) {
  const navigate = useNavigate();
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["industry-chain-stocks", chain?.id],
    queryFn: () => fetchIndustryChainStocks(chain!.id, 1, 40),
    enabled: !!chain,
  });

  if (!chain) {
    return <div className="rounded-md border p-4 text-sm text-muted-foreground">暂无产业链</div>;
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{chain.name}</h3>
          <p className="text-xs text-muted-foreground">按真实板块成分股聚合代表公司</p>
        </div>
        <Badge variant="secondary">{isLoading ? "加载中" : `${data?.total ?? 0} 只`}</Badge>
      </div>

      {data?.related_sectors && data.related_sectors.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.related_sectors.map((sector) => (
            <Badge key={sector.id} variant="outline">
              {sector.name}
            </Badge>
          ))}
        </div>
      )}

      {isLoading ? (
        <LoadingState rows={6} />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : "产业链成分股加载失败"}
          onRetry={() => refetch()}
        />
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="min-w-[920px] w-full text-sm">
            <thead className="bg-muted/60 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left">代码</th>
                <th className="px-3 py-2 text-left">名称</th>
                <th className="px-3 py-2 text-left">来源板块</th>
                <th className="px-3 py-2 text-right">最新价</th>
                <th className="px-3 py-2 text-right">涨跌幅</th>
                <th className="px-3 py-2 text-right">成交额</th>
                <th className="px-3 py-2 text-right">换手率</th>
                <th className="px-3 py-2 text-right">市值</th>
              </tr>
            </thead>
            <tbody>
              {(data?.items ?? []).map((stock) => (
                <ChainStockRow
                  key={`${stock.vt_symbol}-${stock.related_sector_id ?? ""}`}
                  stock={stock}
                  onClick={() => navigate(`/stocks/${stock.vt_symbol}`)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data?.source && <p className="text-xs text-muted-foreground">数据源: {data.source}</p>}
    </section>
  );
}

function ChainStockRow({
  stock,
  onClick,
}: {
  stock: StockQuote & { related_sector_name?: string };
  onClick: () => void;
}) {
  return (
    <tr className="cursor-pointer border-t hover:bg-muted/40" onClick={onClick}>
      <td className="px-3 py-2 font-mono text-xs">{stock.symbol}</td>
      <td className="px-3 py-2 font-medium">{stock.name}</td>
      <td className="px-3 py-2 text-muted-foreground">{stock.related_sector_name ?? "--"}</td>
      <td className="px-3 py-2 text-right tabular-nums">{formatPrice(stock.last_price)}</td>
      <td className={`px-3 py-2 text-right font-medium tabular-nums ${priceColorClass(stock.change_pct)}`}>
        {formatPct(stock.change_pct)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{formatAmount(stock.turnover)}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {stock.turnover_rate != null ? `${stock.turnover_rate.toFixed(2)}%` : "--"}
      </td>
      <td className="px-3 py-2 text-right tabular-nums">{formatMarketCap(stock.market_cap)}</td>
    </tr>
  );
}
