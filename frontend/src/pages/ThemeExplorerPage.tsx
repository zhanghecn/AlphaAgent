/**
 * ThemeExplorerPage — 主线探索 (核心创新页面)
 *
 * Left panel: Concept/industry ranking list with tabs and search
 * Right panel: Detail view — constituent stocks, related concepts, fund flow
 *
 * Data sources:
 *   - Sector ranking (from research API)
 *   - Sector constituent stocks (from sectors API)
 *   - Sector relation graph (from sectors API)
 *   - Fund flow (from market API)
 */
import React, { useState, useCallback, useMemo } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchSectorRanking } from "@/api/research";
import { fetchSectorStocks, fetchSectorRelationGraph } from "@/api/sectors";
import { fetchFundFlow } from "@/api/market";
import { SectorRankCard } from "@/components/SectorRankCard";
import { ConceptTag } from "@/components/ConceptTag";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { formatPct, formatAmount, cn, priceColorClass } from "@/lib/utils";
import type { SectorRankingItem } from "@/types/research";
import {
  Search,
  TrendingUp,
  Users,
  Layers,
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

  // Sector ranking (main list)
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

  // Client-side search filtering
  const filteredItems = useMemo(() => {
    const items = rankingQuery.data?.items ?? [];
    if (!searchQuery.trim()) return items;
    const q = searchQuery.trim().toLowerCase();
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.leader_stock?.toLowerCase().includes(q)
    );
  }, [rankingQuery.data?.items, searchQuery]);

  // Resolve selected item
  const selectedItem = useMemo(() => {
    if (!selectedId) return null;
    return (
      rankingQuery.data?.items?.find((i) => i.sector_id === selectedId) ?? null
    );
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
  // Constituent stocks
  const stocksQuery = useQuery({
    queryKey: ["sectorStocks", item.sector_id],
    queryFn: () =>
      fetchSectorStocks(item.sector_id, 1, 30, true),
    staleTime: 30_000,
    enabled: !!item.sector_id,
  });

  // Related concepts (relation graph)
  const relationQuery = useQuery({
    queryKey: ["sectorRelation", item.name],
    queryFn: () => fetchSectorRelationGraph(item.name, 8, 30),
    staleTime: 60_000,
    enabled: !!item.name,
  });

  // Fund flow for this sector
  const fundQuery = useQuery({
    queryKey: ["sectorFundFlow", item.type],
    queryFn: () => fetchFundFlow(item.type === "industry" ? "industry" : "concept", 20),
    staleTime: 30_000,
  });

  // Find this sector's fund flow
  const sectorFund = useMemo(() => {
    const items = fundQuery.data?.items ?? [];
    return items.find(
      (f) => f.name === item.name || f.code === item.sector_id
    );
  }, [fundQuery.data, item.name, item.sector_id]);

  // Related concepts from graph
  const relatedConcepts = useMemo(() => {
    const graph = relationQuery.data;
    if (!graph) return [];
    // Find edges connected to our sector
    const edges = graph.edges.filter(
      (e) => e.source === item.name || e.target === item.name
    );
    const related: { name: string; sharedStockCount: number; score: number }[] = [];
    for (const edge of edges) {
      const otherName = edge.source === item.name ? edge.target_name : edge.source_name;
      if (otherName && otherName !== item.name) {
        related.push({
          name: otherName,
          sharedStockCount: edge.shared_stock_count ?? 0,
          score: edge.score ?? 0,
        });
      }
    }
    return related.sort((a, b) => b.score - a.score).slice(0, 8);
  }, [relationQuery.data, item.name]);

  const stocks = stocksQuery.data?.items ?? [];

  return (
    <div className="space-y-4">
      {/* Header card */}
      <div className="sector-detail-panel">
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold">{item.name}</h2>
              {item.type === "industry" && (
                <span className="rounded bg-blue-100 px-1.5 py-0.5 text-xs text-blue-600">
                  行业
                </span>
              )}
              {item.type === "concept" && (
                <span className="rounded bg-purple-100 px-1.5 py-0.5 text-xs text-purple-600">
                  概念
                </span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div
              className={cn(
                "text-2xl font-bold tabular-nums",
                item.change_pct != null && item.change_pct > 0
                  ? "text-rise"
                  : "text-fall"
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

      {/* Two-column detail */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        {/* Constituent stocks */}
        <section className="sector-detail-panel">
          <div className="flex items-center justify-between mb-3">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Users size={14} />
              成分股
            </h3>
            <span className="text-xs text-muted-foreground">
              {stocks.length} 只
            </span>
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
                    <th className="pb-2 text-right font-medium">涨跌幅</th>
                    <th className="pb-2 text-right font-medium">换手率</th>
                    <th className="pb-2 text-right font-medium">成交额</th>
                  </tr>
                </thead>
                <tbody>
                  {stocks.slice(0, 15).map((stock) => (
                    <tr key={stock.vt_symbol} className="border-t hover:bg-muted/30">
                      <td className="py-1.5">
                        <Link
                          to={`/stocks/${stock.vt_symbol}`}
                          className="font-medium hover:underline"
                        >
                          {stock.name}
                        </Link>
                        <div className="text-[10px] text-muted-foreground">
                          {stock.symbol}
                        </div>
                      </td>
                      <td
                        className={cn(
                          "py-1.5 text-right font-medium tabular-nums",
                          priceColorClass(stock.change_pct)
                        )}
                      >
                        {formatPct(stock.change_pct)}
                      </td>
                      <td className="py-1.5 text-right tabular-nums">
                        {stock.turnover_rate != null
                          ? `${stock.turnover_rate.toFixed(2)}%`
                          : "--"}
                      </td>
                      <td className="py-1.5 text-right tabular-nums text-muted-foreground">
                        {formatAmount(stock.turnover)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {stocks.length > 15 && (
                <div className="mt-2 text-center text-xs text-muted-foreground">
                  显示前 15 只，共 {stocks.length} 只
                </div>
              )}
            </div>
          )}
        </section>

        {/* Related concepts + fund flow */}
        <div className="space-y-4">
          {/* Related concepts */}
          <section className="sector-detail-panel">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <Layers size={14} />
              关联概念
            </h3>
            {relatedConcepts.length > 0 ? (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {relatedConcepts.map((rc) => (
                  <ConceptTag
                    key={rc.name}
                    name={rc.name}
                    type="concept"
                    onClick={() => {
                      /* Could navigate to this concept */
                    }}
                  />
                ))}
              </div>
            ) : (
              <div className="mt-3 text-sm text-muted-foreground">
                暂无关联概念数据
              </div>
            )}
            {/* Shared stock details */}
            {relatedConcepts.length > 0 && (
              <div className="mt-3 space-y-1">
                {relatedConcepts.slice(0, 5).map((rc) => (
                  <div
                    key={rc.name}
                    className="flex items-center justify-between text-xs"
                  >
                    <span>{rc.name}</span>
                    <span className="text-muted-foreground">
                      共享 {rc.sharedStockCount} 只
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Sector fund flow detail */}
          <section className="sector-detail-panel">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <TrendingUp size={14} />
              资金流向
            </h3>
            {sectorFund ? (
              <div className="mt-3 space-y-2">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div>
                    <div className="text-xs text-muted-foreground">主力净流入</div>
                    <div
                      className={cn(
                        "font-medium tabular-nums",
                        sectorFund.main_net_inflow != null &&
                          sectorFund.main_net_inflow >= 0
                          ? "fund-inflow"
                          : "fund-outflow"
                      )}
                    >
                      {sectorFund.main_net_inflow != null
                        ? formatAmount(sectorFund.main_net_inflow)
                        : "--"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">净占比</div>
                    <div className="font-medium tabular-nums">
                      {sectorFund.main_net_inflow_ratio != null
                        ? `${sectorFund.main_net_inflow_ratio.toFixed(2)}%`
                        : "--"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">超大单</div>
                    <div className="tabular-nums text-sm">
                      {sectorFund.super_large_net_inflow != null
                        ? formatAmount(sectorFund.super_large_net_inflow)
                        : "--"}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground">散户</div>
                    <div className="tabular-nums text-sm">
                      {sectorFund.small_net_inflow != null
                        ? formatAmount(sectorFund.small_net_inflow)
                        : "--"}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-2 text-sm text-muted-foreground">
                暂无资金流向数据
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

// ── Helper: metric display box ──

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
