import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchSectorStocks, fetchSectorTrend, fetchSectors } from "@/api/sectors";
import type { SectorInfo, StockQuote } from "@/api/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { SectorTrendPanel } from "@/components/SectorTrendPanel";
import { formatAmount, formatMarketCap, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import { ArrowUp, ArrowDown, ArrowUpDown } from "lucide-react";

const SECTOR_TYPES = [
  { value: "industry", label: "行业" },
  { value: "concept", label: "概念" },
];

export function SectorList() {
  const [activeType, setActiveType] = useState("industry");
  const [selected, setSelected] = useState<SectorInfo | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sectors", activeType],
    queryFn: () => fetchSectors(activeType),
  });

  const items = useMemo(() => data?.items ?? [], [data]);
  const selectedSector = selected && selected.type === activeType ? selected : items[0] ?? null;

  return (
    <div className="space-y-4">
      <Tabs
        value={activeType}
        onValueChange={(value) => {
          setActiveType(value);
          setSelected(null);
        }}
      >
        <TabsList className="flex flex-wrap">
          {SECTOR_TYPES.map((t) => (
            <TabsTrigger key={t.value} value={t.value}>
              {t.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {SECTOR_TYPES.map((t) => (
          <TabsContent key={t.value} value={t.value}>
            {isLoading ? (
              <LoadingState rows={5} />
            ) : isError ? (
              <ErrorState
                message={error instanceof Error ? error.message : "板块数据加载失败"}
                onRetry={() => refetch()}
              />
            ) : (
              <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(280px,360px)_minmax(0,1fr)]">
                <SectorGrid
                  items={items}
                  selectedId={selectedSector?.id}
                  source={data?.source}
                  onSelect={setSelected}
                />
                <SectorMembers sector={selectedSector} />
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>
    </div>
  );
}

function SectorGrid({
  items,
  selectedId,
  source,
  onSelect,
}: {
  items: SectorInfo[];
  selectedId?: string;
  source?: string;
  onSelect: (sector: SectorInfo) => void;
}) {
  return (
    <section className="min-w-0 space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-medium">板块列表</h3>
        <span className="text-xs text-muted-foreground">{items.length} 个</span>
      </div>
      <div className="max-h-[620px] overflow-auto rounded-md border">
        <div className="grid grid-cols-2 gap-2 p-2 sm:grid-cols-3 xl:grid-cols-2">
          {items.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onSelect(item)}
              className={`rounded-md border p-3 text-left transition-colors hover:bg-muted ${
                selectedId === item.id ? "border-primary bg-muted" : "bg-background"
              }`}
            >
              <p className="truncate text-sm font-medium">{item.name}</p>
              <p className="mt-1 truncate text-xs text-muted-foreground">{item.id}</p>
            </button>
          ))}
        </div>
      </div>
      {source && <p className="text-xs text-muted-foreground">数据源: {source}</p>}
    </section>
  );
}

function SectorMembers({ sector }: { sector: SectorInfo | null }) {
  const navigate = useNavigate();
  const [sort, setSort] = useState<{ key: string; direction: "asc" | "desc" }>({ key: "change_pct", direction: "desc" });
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["sector-stocks", sector?.id],
    queryFn: () => fetchSectorStocks(sector!.id, 1, 30, true),
    enabled: !!sector,
  });
  const trendQuery = useQuery({
    queryKey: ["sector-trend", sector?.id],
    queryFn: () => fetchSectorTrend(sector!.id),
    enabled: !!sector,
  });

  // Client-side sorting (small dataset ~30 rows)
  const sortedItems = useMemo(() => {
    const items = data?.items ?? [];
    if (!sort) return items;
    const { key, direction } = sort;
    return [...items].sort((a: StockQuote, b: StockQuote) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const av = Number((a as any)[key] ?? 0) || 0;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const bv = Number((b as any)[key] ?? 0) || 0;
      return direction === "desc" ? bv - av : av - bv;
    });
  }, [data?.items, sort]);

  function toggleSort(key: string) {
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "desc" ? "asc" : "desc" }
        : { key, direction: "desc" },
    );
  }

  if (!sector) {
    return <div className="rounded-md border p-4 text-sm text-muted-foreground">请选择板块</div>;
  }

  return (
    <section className="min-w-0 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold">{sector.name}</h3>
          <p className="text-xs text-muted-foreground">{sector.id}</p>
        </div>
        <Badge variant="secondary">{typeLabel(sector.type)}</Badge>
      </div>

      {isLoading ? (
        <LoadingState rows={6} />
      ) : isError ? (
        <ErrorState
          message={error instanceof Error ? error.message : "板块成分股加载失败"}
          onRetry={() => refetch()}
        />
      ) : (
        <div className="space-y-3">
          <SectorTrendPanel
            trend={trendQuery.data}
            isLoading={trendQuery.isLoading}
            isError={trendQuery.isError}
            onRetry={() => trendQuery.refetch()}
          />
          <div className="overflow-x-auto rounded-md border">
            <table className="min-w-[1120px] w-full text-sm">
              <thead className="bg-muted/60 text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left">代码</th>
                  <th className="px-3 py-2 text-left">名称</th>
                  <th className="px-3 py-2 text-right">最新价</th>
                  <SortHeader label="涨跌幅" sortKey="change_pct" sort={sort} onSort={toggleSort} />
                  <SortHeader label="5日" sortKey="return_5d" sort={sort} onSort={toggleSort} />
                  <SortHeader label="10日" sortKey="return_10d" sort={sort} onSort={toggleSort} />
                  <SortHeader label="20日" sortKey="return_20d" sort={sort} onSort={toggleSort} />
                  <SortHeader label="成交额" sortKey="turnover" sort={sort} onSort={toggleSort} />
                  <SortHeader label="换手率" sortKey="turnover_rate" sort={sort} onSort={toggleSort} />
                  <SortHeader label="市值" sortKey="market_cap" sort={sort} onSort={toggleSort} />
                </tr>
              </thead>
              <tbody>
                {sortedItems.map((stock: StockQuote) => (
                  <tr
                    key={stock.vt_symbol}
                    className="cursor-pointer border-t hover:bg-muted/40"
                    onClick={() => navigate(`/stocks/${stock.vt_symbol}`)}
                  >
                    <td className="px-3 py-2 font-mono text-xs">{stock.symbol}</td>
                    <td className="px-3 py-2 font-medium">{stock.name}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatPrice(stock.last_price)}</td>
                    <td className={`px-3 py-2 text-right font-medium tabular-nums ${priceColorClass(stock.change_pct)}`}>
                      {formatPct(stock.change_pct)}
                    </td>
                    <ReturnCell value={stock.return_5d} />
                    <ReturnCell value={stock.return_10d} />
                    <ReturnCell value={stock.return_20d} />
                    <td className="px-3 py-2 text-right tabular-nums">{formatAmount(stock.turnover)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {stock.turnover_rate != null ? `${stock.turnover_rate.toFixed(2)}%` : "--"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatMarketCap(stock.market_cap)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {data?.source && <p className="text-xs text-muted-foreground">成分股数据源: {data.source}</p>}
    </section>
  );
}

function SortHeader({ label, sortKey, sort, onSort }: {
  label: string;
  sortKey: string;
  sort: { key: string; direction: "asc" | "desc" };
  onSort: (key: string) => void;
}) {
  const isActive = sort.key === sortKey;
  return (
    <th className="px-3 py-2 text-right">
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-foreground transition-colors"
        onClick={() => onSort(sortKey)}
      >
        {label}
        {isActive ? (
          sort.direction === "desc" ? <ArrowDown size={12} /> : <ArrowUp size={12} />
        ) : (
          <ArrowUpDown size={12} className="opacity-40" />
        )}
      </button>
    </th>
  );
}

function ReturnCell({ value }: { value: number | null | undefined }) {
  return (
    <td className={`px-3 py-2 text-right tabular-nums ${priceColorClass(value)}`}>
      {formatPct(value)}
    </td>
  );
}

function typeLabel(type: string) {
  if (type === "industry") return "行业";
  if (type === "region") return "地域";
  if (type === "theme") return "主题";
  return "概念";
}
