/**
 * ThemeExplorerPage — 主线探索 (核心创新页面)
 *
 * Left panel: Concept/industry ranking list with tabs and search
 * Right panel: Detail view — trend stats, stock analytics, constituent stocks
 *
 * Data sources:
 *   - Sector ranking (from research API)
 *   - Sector constituent stocks (from sectors API, with period returns)
 *   - Sector trend stats (from sectors API)
 */
import React, { useState, useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchSectorRanking } from "@/api/research";
import { fetchSectorStocks, fetchSectorTrend, searchSectors } from "@/api/sectors";
import { SectorRankCard } from "@/components/SectorRankCard";
import { SectorTrendPanel } from "@/components/SectorTrendPanel";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { formatPct, formatAmount, formatPrice, formatMarketCap, cn, priceColorClass } from "@/lib/utils";
import type { SectorRankingItem } from "@/types/research";
import type { StockQuote } from "@/api/types";
import {
  Search,
  Users,
  Activity,
  ArrowUp,
  ArrowDown,
  ArrowUpDown,
} from "lucide-react";

// ── Sort options ──
type SortBy = "change_pct" | "fund_flow" | "stock_count";
const SORT_OPTIONS: { value: SortBy; label: string }[] = [
  { value: "change_pct", label: "按涨幅" },
  { value: "fund_flow", label: "按资金" },
  { value: "stock_count", label: "按规模" },
];

type SectorType = "concept" | "industry" | "all";
const SECTOR_TABS: { value: SectorType; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "concept", label: "概念" },
  { value: "industry", label: "行业" },
];

export default function ThemeExplorerPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  // State from URL + local
  const sectorType = (searchParams.get("type") as SectorType) || "all";
  const preselectedId = searchParams.get("sector");
  const sortBy = (searchParams.get("sort") as SortBy) || "change_pct";
  const searchQuery = searchParams.get("q") || "";
  const [selectedId, setSelectedId] = useState<string | null>(preselectedId);
  const [inputValue, setInputValue] = useState(searchQuery);

  // Update URL params helper
  const updateParams = useCallback(
    (updates: Record<string, string | null>) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, val] of Object.entries(updates)) {
          if (val === null) next.delete(key);
          else next.set(key, val);
        }
        return next;
      });
    },
    [setSearchParams]
  );

  // ── Queries ──

  // Sector ranking (normal browse mode)
  const rankingQuery = useQuery({
    queryKey: ["sectorRanking", sectorType, sortBy],
    queryFn: () =>
      fetchSectorRanking({
        sector_type: sectorType,
        sort_by: sortBy,
        limit: 50,
      }),
    staleTime: 30_000,
  });

  // Sector search (activated when user types in search box)
  const searchQueryResult = useQuery({
    queryKey: ["sectorSearch", searchQuery, sectorType],
    queryFn: () => searchSectors(searchQuery, 30),
    staleTime: 30_000,
    enabled: !!searchQuery.trim(),
  });

  // Merge into a single item list for the left panel
  const filteredItems = useMemo(() => {
    if (!searchQuery.trim()) {
      return rankingQuery.data?.items ?? [];
    }
    // When searching, use searchSectors results mapped to SectorRankingItem shape
    const results = searchQueryResult.data?.items ?? [];
    const filtered = sectorType === "all"
      ? results
      : results.filter((r) => r.type === sectorType);
    return filtered.map((r) => ({
      sector_id: r.id,
      name: r.name,
      type: (r.type as "concept" | "industry") ?? "concept",
      change_pct: r.change_pct ?? null,
      stock_count: r.stock_count ?? null,
      rise_count: null,
      fall_count: null,
      leader_stock: null,
      leader_change_pct: null,
      market_cap: null,
      turnover_rate: null,
      main_net_inflow: null,
    }));
  }, [rankingQuery.data?.items, searchQueryResult.data?.items, searchQuery, sectorType]);

  // Resolve selected item — fall back to URL placeholder if not in ranking
  const selectedItem = useMemo(() => {
    if (!selectedId) return null;
    const found = rankingQuery.data?.items?.find((i) => i.sector_id === selectedId);
    if (found) return found;
    // Placeholder so the detail panel still renders for URL-selected sectors
    return {
      sector_id: selectedId,
      name: selectedId,
      type: "concept" as const,
      change_pct: null,
      stock_count: null,
      rise_count: null,
      fall_count: null,
      leader_stock: null,
      leader_change_pct: null,
      market_cap: null,
      turnover_rate: null,
      main_net_inflow: null,
    };
  }, [rankingQuery.data?.items, selectedId]);

  // Auto-select first item when data loads (if none selected)
  React.useEffect(() => {
    if (!selectedId && filteredItems.length > 0) {
      setSelectedId(filteredItems[0].sector_id);
    }
  }, [selectedId, filteredItems]);

  // Handle search
  const handleSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      updateParams({ q: inputValue || null });
    },
    [inputValue, updateParams]
  );

  // Handle sector type tab
  const handleTabChange = useCallback(
    (type: SectorType) => {
      updateParams({ type: type === "all" ? null : type });
    },
    [updateParams]
  );

  // Handle sort change
  const handleSortChange = useCallback(
    (sort: SortBy) => {
      updateParams({ sort: sort === "change_pct" ? null : sort });
    },
    [updateParams]
  );

  // Handle select
  const handleSelect = useCallback(
    (item: SectorRankingItem) => {
      setSelectedId(item.sector_id);
      updateParams({ sector: item.sector_id });
    },
    [updateParams]
  );

  return (
    <div className="space-y-4">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold">主线探索</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          探索市场最强概念与行业主线，发现资金聚集方向
        </p>
      </div>

      {/* Main layout: left list + right detail */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[320px_minmax(0,1fr)]">
        {/* Left: Ranking list */}
        <div className="space-y-3">
          {/* Search */}
          <form onSubmit={handleSearch} className="relative">
            <Search
              size={16}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              type="text"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="搜索概念/行业..."
              className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-primary/20"
            />
          </form>

          {/* Tabs */}
          <div className="flex gap-1 rounded-lg border p-1">
            {SECTOR_TABS.map((tab) => (
              <button
                key={tab.value}
                className={cn(
                  "flex-1 rounded-md px-2 py-1.5 text-xs font-medium transition-colors",
                  sectorType === tab.value
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted"
                )}
                onClick={() => handleTabChange(tab.value)}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Sort options */}
          <div className="flex gap-1">
            {SORT_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={cn(
                  "rounded-md px-2 py-1 text-xs transition-colors",
                  sortBy === opt.value
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
                onClick={() => handleSortChange(opt.value)}
              >
                {opt.label}
              </button>
            ))}
          </div>

          {/* List */}
          {rankingQuery.isLoading && <LoadingState rows={8} />}
          {rankingQuery.isError && (
            <ErrorState
              message="加载排行失败"
              onRetry={() => rankingQuery.refetch()}
            />
          )}
          {rankingQuery.data && (
            <div className="space-y-1">
              <div className="text-xs text-muted-foreground">
                {filteredItems.length} / {rankingQuery.data.total} 个板块
              </div>
              <div className="max-h-[calc(100vh-320px)] space-y-1 overflow-y-auto pr-1">
                {filteredItems.map((item, idx) => (
                  <SectorRankCard
                    key={item.sector_id}
                    item={item}
                    rank={idx + 1}
                    selected={selectedId === item.sector_id}
                    onClick={() => handleSelect(item)}
                  />
                ))}
                {filteredItems.length === 0 && (
                  <div className="py-8 text-center text-sm text-muted-foreground">
                    无匹配结果
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Right: Detail panel */}
        <div className="min-w-0">
          {selectedItem ? (
            <SectorDetailPanel item={selectedItem} />
          ) : (
            <div className="flex h-64 items-center justify-center rounded-lg border border-dashed text-muted-foreground">
              ← 选择左侧板块查看详情
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Sector Detail Panel ──

function SectorDetailPanel({ item }: { item: SectorRankingItem }) {
  // Sort state for constituent stocks table
  const [stockSort, setStockSort] = useState<{ key: string; direction: "asc" | "desc" }>({
    key: "change_pct",
    direction: "desc",
  });
  const [stockPage, setStockPage] = useState(1);
  const [stockSearch, setStockSearch] = useState("");
  const [appliedStockSearch, setAppliedStockSearch] = useState("");
  const STOCK_PAGE_SIZE = 50;

  // Reset page & search when sector changes
  React.useEffect(() => {
    setStockPage(1);
    setStockSearch("");
    setAppliedStockSearch("");
  }, [item.sector_id]);

  function toggleStockSort(key: string) {
    setStockSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "desc" ? "asc" : "desc" }
        : { key, direction: "desc" },
    );
  }

  // Constituent stocks (server-side paginated + searchable, with period returns)
  const stocksQuery = useQuery({
    queryKey: ["sectorStocks", item.sector_id, stockPage, STOCK_PAGE_SIZE, appliedStockSearch],
    queryFn: () =>
      fetchSectorStocks(item.sector_id, stockPage, STOCK_PAGE_SIZE, true, appliedStockSearch),
    staleTime: 30_000,
    enabled: !!item.sector_id,
  });

  // Sector trend stats
  const trendQuery = useQuery({
    queryKey: ["sectorTrend", item.sector_id],
    queryFn: () => fetchSectorTrend(item.sector_id),
    staleTime: 30_000,
    enabled: !!item.sector_id,
  });

  const stocks = stocksQuery.data?.items ?? [];
  const totalStocks = stocksQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalStocks / STOCK_PAGE_SIZE));

  // Client-side sorted stocks
  const sortedStocks = useMemo(() => {
    const { key, direction } = stockSort;
    return [...stocks].sort((a: StockQuote, b: StockQuote) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const av = Number((a as any)[key] ?? 0) || 0;
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const bv = Number((b as any)[key] ?? 0) || 0;
      return direction === "desc" ? bv - av : av - bv;
    });
  }, [stocks, stockSort]);

  // Client-side analytics from constituent stocks data
  const stockAnalytics = useMemo(() => {
    if (stocks.length === 0) return null;
    const validReturns5d = stocks.map((s) => s.return_5d).filter((v): v is number => v != null);
    const validReturns10d = stocks.map((s) => s.return_10d).filter((v): v is number => v != null);
    const avg = (arr: number[]) =>
      arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;
    const positiveRatio5d =
      validReturns5d.length > 0
        ? (validReturns5d.filter((v) => v > 0).length / validReturns5d.length) * 100
        : null;
    const totalTurnover = stocks.reduce((sum, s) => sum + (s.turnover ?? 0), 0);
    const sorted = [...stocks].sort(
      (a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0)
    );
    return {
      avgReturn5d: avg(validReturns5d),
      avgReturn10d: avg(validReturns10d),
      positiveRatio5d,
      totalTurnover,
      topGainers: sorted.slice(0, 3),
      topLosers: sorted.slice(-3).reverse(),
    };
  }, [stocks]);

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="sector-detail-panel">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold">{item.name}</h2>
              {item.type === "industry" && (
                <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">
                  行业
                </span>
              )}
              {item.type === "concept" && (
                <span className="rounded bg-purple-100 px-1.5 py-0.5 text-xs text-purple-600 dark:bg-purple-500/15 dark:text-purple-300">
                  概念
                </span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div
              className={cn(
                "font-display text-2xl font-bold tabular-nums",
                item.change_pct != null && item.change_pct > 0 ? "text-rise" : "text-fall"
              )}
            >
              {formatPct(item.change_pct)}
            </div>
          </div>
        </div>

        {/* Metrics grid */}
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          <MetricBox label="成分股" value={item.stock_count != null ? `${item.stock_count} 只` : "--"} />
          <MetricBox
            label="涨/跌"
            value={
              item.rise_count != null && item.fall_count != null ? (
                <>
                  <span className="text-rise">{item.rise_count}</span>
                  <span> / </span>
                  <span className="text-fall">{item.fall_count}</span>
                </>
              ) : (
                "--"
              )
            }
          />
          <MetricBox
            label="主力净流入"
            value={
              item.main_net_inflow != null ? (
                <span className={item.main_net_inflow >= 0 ? "fund-inflow" : "fund-outflow"}>
                  {(item.main_net_inflow >= 0 ? "+" : "") +
                    formatAmount(item.main_net_inflow)}
                </span>
              ) : (
                "--"
              )
            }
          />
          <MetricBox
            label="龙头股"
            value={item.leader_stock ?? "--"}
          />
        </div>
      </div>

      {/* Sector trend stats (full-width) */}
      <SectorTrendPanel
        trend={trendQuery.data}
        isLoading={trendQuery.isLoading}
        isError={trendQuery.isError}
        onRetry={() => trendQuery.refetch()}
      />

      {/* Stock analytics summary (client-side computed) */}
      {stockAnalytics && (
        <StockAnalyticsSummary analytics={stockAnalytics} />
      )}

      {/* Constituent stocks table (full-width, paginated, searchable) */}
      <section className="sector-detail-panel">
        <div className="flex items-center justify-between mb-3">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Users size={14} />
            成分股
          </h3>
          <div className="flex items-center gap-2">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                setAppliedStockSearch(stockSearch.trim());
                setStockPage(1);
              }}
              className="relative"
            >
              <Search
                size={14}
                className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
              <input
                type="text"
                value={stockSearch}
                onChange={(e) => setStockSearch(e.target.value)}
                placeholder="搜索成分股..."
                className="h-8 w-40 rounded-md border bg-background py-1 pl-8 pr-2 text-xs outline-none focus:ring-2 focus:ring-primary/20"
              />
            </form>
            <span className="text-xs text-muted-foreground">
              {totalStocks > 0 ? `共 ${totalStocks} 只` : ""}
              {appliedStockSearch && (
                <button
                  type="button"
                  className="ml-1.5 text-primary hover:underline"
                  onClick={() => {
                    setStockSearch("");
                    setAppliedStockSearch("");
                    setStockPage(1);
                  }}
                >
                  × 清除搜索
                </button>
              )}
            </span>
          </div>
        </div>
        {stocksQuery.isLoading ? (
          <LoadingState rows={5} />
        ) : stocks.length === 0 ? (
          <div className="py-4 text-center text-sm text-muted-foreground">
            暂无成分股数据
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="pb-2 text-left font-medium">名称</th>
                  <th className="pb-2 text-right font-medium">最新价</th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="涨跌幅" sortKey="change_pct" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="5日" sortKey="return_5d" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="10日" sortKey="return_10d" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="20日" sortKey="return_20d" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="成交额" sortKey="turnover" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="换手率" sortKey="turnover_rate" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                  <th className="pb-2 text-right font-medium">
                    <SortHeader label="市值" sortKey="market_cap" sort={stockSort} onSort={toggleStockSort} />
                  </th>
                </tr>
              </thead>
              <tbody>
                {sortedStocks.map((stock) => (
                  <tr key={stock.vt_symbol} className="border-t hover:bg-muted/30">
                    <td className="py-1.5">
                      <StockIdentityLink
                        name={stock.name}
                        vtSymbol={stock.vt_symbol}
                        board={stock.board}
                        boardLabel={stock.board_label}
                      />
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {formatPrice(stock.last_price)}
                    </td>
                    <td
                      className={cn(
                        "py-1.5 text-right font-medium tabular-nums",
                        priceColorClass(stock.change_pct)
                      )}
                    >
                      {formatPct(stock.change_pct)}
                    </td>
                    <td className={cn("py-1.5 text-right tabular-nums", priceColorClass(stock.return_5d))}>
                      {formatPct(stock.return_5d)}
                    </td>
                    <td className={cn("py-1.5 text-right tabular-nums", priceColorClass(stock.return_10d))}>
                      {formatPct(stock.return_10d)}
                    </td>
                    <td className={cn("py-1.5 text-right tabular-nums", priceColorClass(stock.return_20d))}>
                      {formatPct(stock.return_20d)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                      {formatAmount(stock.turnover)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {stock.turnover_rate != null
                        ? `${stock.turnover_rate.toFixed(2)}%`
                        : "--"}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">
                      {formatMarketCap(stock.market_cap)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {totalPages > 1 && (
              <div className="mt-3 flex items-center justify-between border-t pt-3">
                <span className="text-xs text-muted-foreground">
                  第 {stockPage} / {totalPages} 页
                </span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    disabled={stockPage <= 1}
                    className="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-40 disabled:pointer-events-none"
                    onClick={() => setStockPage((p) => Math.max(1, p - 1))}
                  >
                    上一页
                  </button>
                  <button
                    type="button"
                    disabled={stockPage >= totalPages}
                    className="rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:bg-muted disabled:opacity-40 disabled:pointer-events-none"
                    onClick={() => setStockPage((p) => Math.min(totalPages, p + 1))}
                  >
                    下一页
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}

// ── Stock Analytics Summary ──

interface StockAnalytics {
  avgReturn5d: number | null;
  avgReturn10d: number | null;
  positiveRatio5d: number | null;
  totalTurnover: number;
  topGainers: StockQuote[];
  topLosers: StockQuote[];
}

function StockAnalyticsSummary({ analytics }: { analytics: StockAnalytics }) {
  return (
    <section className="sector-detail-panel">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Activity size={14} />
        成分股分析
      </h3>
      <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MetricBox
          label="平均5日涨幅"
          value={
            <span className={cn("tabular-nums", priceColorClass(analytics.avgReturn5d))}>
              {formatPct(analytics.avgReturn5d)}
            </span>
          }
        />
        <MetricBox
          label="5日正收益比"
          value={analytics.positiveRatio5d != null ? `${analytics.positiveRatio5d.toFixed(0)}%` : "--"}
        />
        <MetricBox
          label="平均10日涨幅"
          value={
            <span className={cn("tabular-nums", priceColorClass(analytics.avgReturn10d))}>
              {formatPct(analytics.avgReturn10d)}
            </span>
          }
        />
        <MetricBox
          label="板块总成交"
          value={formatAmount(analytics.totalTurnover)}
        />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-4 border-t pt-3">
        <MiniStockList title="涨幅前三" stocks={analytics.topGainers} />
        <MiniStockList title="跌幅前三" stocks={analytics.topLosers} />
      </div>
    </section>
  );
}

function MiniStockList({ title, stocks }: { title: string; stocks: StockQuote[] }) {
  return (
    <div>
      <h4 className="text-xs font-medium text-muted-foreground">{title}</h4>
      <div className="mt-1.5 space-y-1">
        {stocks.map((stock) => (
          <div key={stock.vt_symbol} className="flex items-center justify-between text-sm">
            <StockIdentityLink
              name={stock.name}
              vtSymbol={stock.vt_symbol}
              board={stock.board}
              boardLabel={stock.board_label}
              className="min-w-0"
            />
            <span className={cn("tabular-nums text-xs ml-2", priceColorClass(stock.change_pct))}>
              {formatPct(stock.change_pct)}
            </span>
          </div>
        ))}
        {stocks.length === 0 && (
          <div className="text-xs text-muted-foreground">暂无数据</div>
        )}
      </div>
    </div>
  );
}

// ── Helper components ──

function MetricBox({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border p-2.5">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
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
  );
}
