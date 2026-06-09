import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { fetchSectorStocks, fetchSectorTrend, fetchSectors } from "@/api/sectors";
import type { SectorInfo, SectorTrend, StockQuote } from "@/api/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { formatAmount, formatMarketCap, formatPct, formatPrice, priceColorClass } from "@/lib/utils";

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
                  <th className="px-3 py-2 text-right">涨跌幅</th>
                  <th className="px-3 py-2 text-right">5日</th>
                  <th className="px-3 py-2 text-right">10日</th>
                  <th className="px-3 py-2 text-right">20日</th>
                  <th className="px-3 py-2 text-right">成交额</th>
                  <th className="px-3 py-2 text-right">换手率</th>
                  <th className="px-3 py-2 text-right">市值</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).map((stock: StockQuote) => (
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

function SectorTrendPanel({
  trend,
  isLoading,
  isError,
  onRetry,
}: {
  trend?: SectorTrend;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  if (isLoading) {
    return <LoadingState rows={2} />;
  }
  if (isError) {
    return <ErrorState message="板块趋势指标加载失败" onRetry={onRetry} />;
  }
  if (!trend) {
    return <div className="rounded-md border p-3 text-sm text-muted-foreground">暂无板块趋势指标</div>;
  }

  const primary = trend.turnover_weighted_change_pct ?? trend.avg_change_pct;
  return (
    <div className="rounded-md border">
      <div className="grid gap-0 sm:grid-cols-2 lg:grid-cols-4">
        <TrendMetric label="趋势" value={trendStateLabel(trend.trend_state)} valueClass={priceColorClass(primary)} />
        <TrendMetric label="成交额加权涨幅" value={formatPct(trend.turnover_weighted_change_pct)} valueClass={priceColorClass(trend.turnover_weighted_change_pct)} />
        <TrendMetric label="上涨家数" value={`${trend.rise_count}/${trend.sample_size}`} subValue={formatRatio(trend.rise_ratio)} valueClass={priceColorClass((trend.rise_ratio ?? 50) - 50)} />
        <TrendMetric label="板块成交额" value={formatAmount(trend.turnover)} />
      </div>
      <div className="grid gap-0 border-t sm:grid-cols-2 lg:grid-cols-4">
        <TrendMetric label="平均涨幅" value={formatPct(trend.avg_change_pct)} valueClass={priceColorClass(trend.avg_change_pct)} />
        <TrendMetric label="市值加权涨幅" value={formatPct(trend.market_cap_weighted_change_pct)} valueClass={priceColorClass(trend.market_cap_weighted_change_pct)} />
        <TrendMetric label="下跌家数" value={`${trend.fall_count}/${trend.sample_size}`} subValue={formatRatio(trend.fall_ratio)} valueClass={priceColorClass(50 - (trend.fall_ratio ?? 50))} />
        <TrendMetric label="涨跌停" value={`${trend.limit_up_count} / ${trend.limit_down_count}`} />
      </div>
      <div className="border-t px-3 py-2 text-xs text-muted-foreground">
        样本来自真实板块成分股行情，数据源: {trend.source ?? "--"}
      </div>
    </div>
  );
}

function TrendMetric({
  label,
  value,
  subValue,
  valueClass,
}: {
  label: string;
  value: string;
  subValue?: string;
  valueClass?: string;
}) {
  return (
    <div className="border-b px-3 py-2 last:border-b-0 sm:border-r lg:border-b-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={`text-sm font-semibold tabular-nums ${valueClass ?? ""}`}>{value}</span>
        {subValue && <span className="text-xs text-muted-foreground tabular-nums">{subValue}</span>}
      </div>
    </div>
  );
}

function ReturnCell({ value }: { value: number | null | undefined }) {
  return (
    <td className={`px-3 py-2 text-right tabular-nums ${priceColorClass(value)}`}>
      {formatPct(value)}
    </td>
  );
}

function trendStateLabel(state: SectorTrend["trend_state"]) {
  if (state === "STRONG_UP") return "强势上涨";
  if (state === "UP") return "上涨";
  if (state === "STRONG_DOWN") return "强势下跌";
  if (state === "DOWN") return "下跌";
  if (state === "RANGE") return "震荡";
  return "未知";
}

function formatRatio(value: number | null | undefined) {
  if (value == null) return "--";
  return `${value.toFixed(1)}%`;
}

function typeLabel(type: string) {
  if (type === "industry") return "行业";
  if (type === "region") return "地域";
  if (type === "theme") return "主题";
  return "概念";
}
