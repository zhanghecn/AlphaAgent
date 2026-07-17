import { FormEvent, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { ArrowRight, Database, GitBranch, Layers3, Radio, Search, TrendingUp } from "lucide-react";
import {
  fetchIndustryChainMap,
  fetchSectorRelationGraph,
  fetchSectorStocks,
  fetchSectorTrend,
  searchSectors,
} from "@/api/sectors";
import type {
  ChainStock,
  IndustryChainMap,
  IndustryChainSegment,
  SectorDiscoveryGroup,
  SectorInfo,
  SectorRelationGraph,
  SectorRelationGraphEdge,
  SectorRelationGraphNode,
  SectorSearchResult,
  SectorTrend,
  StockQuote,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import {
  cn,
  formatAmount,
  formatMarketCap,
  formatPct,
  formatPrice,
  priceColorClass,
} from "@/lib/utils";

type Selection =
  { kind: "sector"; id: string; name: string; sectorType: string };
type StockSortKey =
  | "symbol"
  | "name"
  | "last_price"
  | "change_pct"
  | "return_5d"
  | "return_10d"
  | "return_20d"
  | "turnover"
  | "turnover_rate"
  | "market_cap"
  | "related_sector_name";
type SortDirection = "asc" | "desc";
type StockSort = { key: StockSortKey; direction: SortDirection };

const DEFAULT_QUERY = "";
const DEFAULT_GRAPH_TITLE = "实时板块";

export function SectorsPage() {
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get("q") ?? DEFAULT_QUERY;
  const [query, setQuery] = useState(initialQuery);
  const [submittedQuery, setSubmittedQuery] = useState(initialQuery);
  const [selection, setSelection] = useState<Selection | null>(null);

  const searchQuery = useQuery({
    queryKey: ["sector-search", submittedQuery],
    queryFn: () => searchSectors(submittedQuery, 24),
  });

  const searchItems = searchQuery.data?.items ?? [];
  const sectorItems = useMemo(() => searchItems.filter((item) => item.kind === "sector"), [searchItems]);
  const hotQueries = searchQuery.data?.hot_queries ?? [];
  const discoveryGroups = searchQuery.data?.discovery_groups ?? [];

  useEffect(() => {
    if (selection || !submittedQuery.trim() || searchQuery.isLoading || sectorItems.length !== 1) {
      return;
    }
    const item = sectorItems[0];
    setSelection({ kind: "sector", id: item.id, name: item.name, sectorType: item.type });
  }, [searchQuery.isLoading, sectorItems, selection, submittedQuery]);

  function submitSearch(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    const nextQuery = query.trim() || DEFAULT_QUERY;
    setQuery(nextQuery);
    setSubmittedQuery(nextQuery);
    setSelection(null);
  }

  function chooseHotQuery(value: string) {
    setQuery(value);
    setSubmittedQuery(value);
    setSelection(null);
  }

  function chooseResult(item: SectorSearchResult) {
    setSelection({ kind: "sector", id: item.id, name: item.name, sectorType: item.type });
  }

  function chooseSector(sector: SectorInfo) {
    setSelection({ kind: "sector", id: sector.id, name: sector.name, sectorType: sector.type });
  }

  return (
    <div className="min-w-0 space-y-4">
      <section className="space-y-3 border-b pb-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">板块产业链</h1>
            <p className="mt-1 text-sm text-muted-foreground">用真实板块和成分股计算关系图谱，查看主线、扩散和个股样本。</p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Layers3 size={16} />
            <span>{sourceLabel(searchQuery.data?.data_origin, searchQuery.data?.source)}</span>
          </div>
        </div>

        <form onSubmit={submitSearch} className="flex min-w-0 flex-col gap-2 sm:flex-row">
          <div className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="pl-9"
              placeholder="输入板块、概念或行业关键词"
            />
          </div>
          <Button type="submit" className="gap-2">
            <Search size={16} />
            搜索
          </Button>
        </form>

        {!submittedQuery.trim() && (
          <DiscoveryQuickFilters
            discoveryGroups={discoveryGroups}
            hotQueries={hotQueries}
            onChoose={chooseHotQuery}
          />
        )}
      </section>

      <div className="grid min-w-0 gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <aside className="min-w-0 space-y-3">
          <SearchResultsPanel
            sectorItems={sectorItems}
            submittedQuery={submittedQuery}
            discoveryGroups={discoveryGroups}
            isLoading={searchQuery.isLoading}
            isError={searchQuery.isError}
            error={searchQuery.error}
            selected={selection}
            onRetry={() => searchQuery.refetch()}
            onSelect={chooseResult}
          />
        </aside>

        <main className="min-w-0">
          {selection?.kind === "sector" ? (
            <SectorWorkspace
              selection={selection}
              onChooseSector={chooseSector}
            />
          ) : (
            <SectorStartPanel
              submittedQuery={submittedQuery}
              hotQueries={hotQueries}
              discoveryGroups={discoveryGroups}
              onChooseHotQuery={chooseHotQuery}
            />
          )}
        </main>
      </div>
    </div>
  );
}

function DiscoveryQuickFilters({
  discoveryGroups,
  hotQueries,
  onChoose,
}: {
  discoveryGroups: SectorDiscoveryGroup[];
  hotQueries: string[];
  onChoose: (value: string) => void;
}) {
  const quickItems = uniqueStrings(
    discoveryGroups
      .filter((group) => group.id !== "style_status")
      .flatMap((group) => group.items.slice(0, 3).map((item) => item.name))
  ).slice(0, 10);
  const items = quickItems.length > 0 ? quickItems : hotQueries.slice(0, 10);
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {items.map((item) => (
        <button
          key={item}
          type="button"
          onClick={() => onChoose(item)}
          className="rounded-md border px-2.5 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted"
        >
          {item}
        </button>
      ))}
    </div>
  );
}

function uniqueStrings(values: string[]): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (!value || seen.has(value)) continue;
    seen.add(value);
    result.push(value);
  }
  return result;
}

function SectorStartPanel({
  submittedQuery,
  hotQueries,
  discoveryGroups,
  onChooseHotQuery,
}: {
  submittedQuery: string;
  hotQueries: string[];
  discoveryGroups: SectorDiscoveryGroup[];
  onChooseHotQuery: (value: string) => void;
}) {
  return (
    <section className="rounded-md border p-5">
      <h3 className="text-base font-semibold">先看懂板块，再选股票</h3>
      <p className="mt-2 text-sm text-muted-foreground">
        {submittedQuery.trim()
          ? "左侧是搜索结果，点击一个板块后查看趋势、强关联和成分股。"
          : "行业、题材、风格状态分开看。风格状态只能做过滤条件，不直接当产业主线。"}
      </p>
      {!submittedQuery.trim() && discoveryGroups.length > 0 ? (
        <div className="mt-4 space-y-4">
          {discoveryGroups.map((group) => (
            <DiscoveryGroupPanel key={`start-${group.id}`} group={group} onChoose={onChooseHotQuery} />
          ))}
        </div>
      ) : (
        !submittedQuery.trim() && hotQueries.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {hotQueries.slice(0, 8).map((item) => (
              <button
                key={`start-${item}`}
                type="button"
                onClick={() => onChooseHotQuery(item)}
                className="rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-muted"
              >
                {item}
              </button>
            ))}
          </div>
        )
      )}
    </section>
  );
}

function DiscoveryGroupPanel({
  group,
  onChoose,
}: {
  group: SectorDiscoveryGroup;
  onChoose: (value: string) => void;
}) {
  return (
    <div className="rounded-md border">
      <div className="border-b px-3 py-2.5">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold">{group.title}</h4>
          <span className="text-xs text-muted-foreground">{group.items.length} 项</span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">{group.description}</p>
      </div>
      <div className="divide-y">
        {group.items.slice(0, 8).map((item) => (
          <button
            key={`${group.id}-${item.id}`}
            type="button"
            onClick={() => onChoose(item.name)}
            className="flex w-full min-w-0 items-center justify-between gap-3 px-3 py-2 text-left hover:bg-muted"
          >
            <div className="min-w-0">
              <div className="flex min-w-0 items-center gap-2">
                <span className="truncate text-sm font-medium">{item.name}</span>
                <span className="shrink-0 text-[11px] text-muted-foreground">{resultTypeLabel(item)}</span>
              </div>
              <p className="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
                {item.decision_hint ?? item.user_explain ?? `${item.stock_count ?? "--"} 只成分股`}
              </p>
            </div>
            <span className={cn("shrink-0 text-xs font-medium tabular-nums", priceColorClass(item.change_pct))}>
              {formatPct(item.change_pct)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function SearchResultsPanel({
  sectorItems,
  submittedQuery,
  discoveryGroups,
  isLoading,
  isError,
  error,
  selected,
  onRetry,
  onSelect,
}: {
  sectorItems: SectorSearchResult[];
  submittedQuery: string;
  discoveryGroups: SectorDiscoveryGroup[];
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  selected: Selection | null;
  onRetry: () => void;
  onSelect: (item: SectorSearchResult) => void;
}) {
  if (isLoading) return <LoadingState rows={5} />;
  if (isError) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "板块搜索失败"}
        onRetry={onRetry}
      />
    );
  }

  return (
    <section className="min-w-0 rounded-md border">
      <PanelHeader
        icon={<Search size={16} />}
        title={submittedQuery.trim() ? "搜索结果" : "板块发现"}
        meta={submittedQuery.trim() ? `${sectorItems.length} 项` : `${discoveryGroups.length} 类`}
      />
      <div className="max-h-[560px] space-y-4 overflow-auto p-3">
        {submittedQuery.trim() ? (
          <ResultGroup
            title="真实板块"
            items={sectorItems}
            selected={selected}
            onSelect={onSelect}
          />
        ) : discoveryGroups.length > 0 ? (
          <div className="space-y-3">
            {discoveryGroups.map((group) => (
              <ResultDiscoveryGroup
                key={`result-${group.id}`}
                group={group}
                selected={selected}
                onSelect={onSelect}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-md border border-dashed px-3 py-5 text-sm text-muted-foreground">
            板块发现数据暂时不可用。可以直接搜索行业、概念或股票相关关键词。
          </div>
        )}
      </div>
    </section>
  );
}

function ResultDiscoveryGroup({
  group,
  selected,
  onSelect,
}: {
  group: SectorDiscoveryGroup;
  selected: Selection | null;
  onSelect: (item: SectorSearchResult) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{group.title}</p>
          <p className="mt-0.5 line-clamp-1 text-[11px] text-muted-foreground">{group.description}</p>
        </div>
        <span className="shrink-0 text-xs text-muted-foreground">{group.items.length}</span>
      </div>
      <div className="space-y-2">
        {group.items.slice(0, 8).map((item) => (
          <SectorResultButton
            key={`${group.id}-${item.id}`}
            item={item}
            selected={selected}
            onSelect={onSelect}
          />
        ))}
      </div>
    </div>
  );
}

function ResultGroup({
  title,
  items,
  selected,
  onSelect,
}: {
  title: string;
  items: SectorSearchResult[];
  selected: Selection | null;
  onSelect: (item: SectorSearchResult) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="font-medium text-muted-foreground">{title}</span>
        <span className="text-muted-foreground">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="rounded-md border border-dashed px-3 py-4 text-xs text-muted-foreground">暂无匹配</div>
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <SectorResultButton
              key={`${item.kind}-${item.id}`}
              item={item}
              selected={selected}
              onSelect={onSelect}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function SectorResultButton({
  item,
  selected,
  onSelect,
}: {
  item: SectorSearchResult;
  selected: Selection | null;
  onSelect: (item: SectorSearchResult) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect(item)}
      className={cn(
        "w-full rounded-md border px-3 py-2 text-left transition-colors hover:bg-muted",
        selected?.kind === item.kind && selected.id === item.id ? "border-primary bg-muted" : "bg-background"
      )}
    >
      <div className="flex min-w-0 items-center justify-between gap-2">
        <span className="truncate text-sm font-medium">{item.name}</span>
        <div className="flex shrink-0 items-center gap-1">
          {item.kind === "sector" && item.change_pct != null && (
            <span className={cn("text-xs font-medium tabular-nums", priceColorClass(item.change_pct))}>
              {formatPct(item.change_pct)}
            </span>
          )}
          <Badge variant="outline" className="rounded-md">{resultTypeLabel(item)}</Badge>
        </div>
      </div>
      <p className="mt-1.5 line-clamp-2 text-xs text-muted-foreground">
        {item.user_explain ?? `${item.stock_count ?? "--"} 只成分股`}
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {(item.matched ?? []).slice(0, 4).map((tag) => (
          <span key={tag} className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
            {tag}
          </span>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2 text-[11px] text-muted-foreground">
        <span className="truncate">{item.decision_hint ?? `${item.stock_count ?? "--"} 只成分股`}</span>
        <span className="shrink-0 truncate">{sectorSourceLabel(item.source)}</span>
      </div>
    </button>
  );
}

function GraphWorkspace({
  query,
  onChooseSector,
  compact = false,
}: {
  query: string;
  onChooseSector: (sector: SectorInfo) => void;
  compact?: boolean;
}) {
  const [selectedEdge, setSelectedEdge] = useState<SectorRelationGraphEdge | null>(null);
  const graphQuery = useQuery({
    queryKey: ["sector-relation-graph", query],
    queryFn: () => fetchSectorRelationGraph(query, 12, 50),
  });

  if (graphQuery.isLoading) return <LoadingState rows={8} />;
  if (graphQuery.isError) {
    return (
      <ErrorState
        message={graphQuery.error instanceof Error ? graphQuery.error.message : "板块关联图谱加载失败"}
        onRetry={() => graphQuery.refetch()}
      />
    );
  }

  const graph = graphQuery.data;
  if (!graph || graph.nodes.length === 0) {
    return (
      <div className="rounded-md border p-6 text-sm text-muted-foreground">
        {graph?.message ?? "暂无可计算的板块关联图谱"}
      </div>
    );
  }

  const viewGraph = compact ? compactGraphForQuery(graph, query) : graph;
  if (compact && viewGraph.nodes.length <= 1) {
    return (
      <section className="rounded-md border p-4 text-sm text-muted-foreground">
        暂未发现足够强的板块关联。当前只展示成分股和趋势数据。
      </section>
    );
  }

  const activeEdge = selectedEdge && graphHasEdge(viewGraph, selectedEdge) ? selectedEdge : viewGraph.edges[0] ?? null;
  const title = compact ? `${graph.query || DEFAULT_GRAPH_TITLE} 强关联图` : `${graph.query || DEFAULT_GRAPH_TITLE} 关联图谱`;

  return (
    <div className="min-w-0 space-y-4">
      <section className="rounded-md border">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold">{title}</h3>
              <Badge variant={graph.status === "ready" ? "secondary" : "outline"}>{graph.status}</Badge>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              {compact ? "只保留与当前板块直接相关、重叠度较高的关系。" : graph.algorithm.edge_basis}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">节点来源: {graph.algorithm.node_basis}</p>
          </div>
          <div className="grid grid-cols-4 gap-3 text-right text-xs">
            <div>
              <p className="text-muted-foreground">节点</p>
              <p className="mt-1 font-semibold tabular-nums">{viewGraph.nodes.length}</p>
            </div>
            <div>
              <p className="text-muted-foreground">关联边</p>
              <p className="mt-1 font-semibold tabular-nums">{viewGraph.edges.length}</p>
            </div>
            <div>
              <p className="text-muted-foreground">样本</p>
              <p className="mt-1 font-semibold tabular-nums">{graph.algorithm.sample_page_size}/板块</p>
            </div>
            <div>
              <p className="text-muted-foreground">种子</p>
              <p className="mt-1 font-semibold tabular-nums">{graph.algorithm.seed_count ?? graph.nodes.length}</p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_340px]">
          <SectorGraphCanvas
            graph={viewGraph}
            selectedEdge={activeEdge}
            onSelectEdge={setSelectedEdge}
            onChooseSector={(node) =>
              onChooseSector(sectorFromGraphNode(node))
            }
          />
          <GraphInspector
            graph={viewGraph}
            selectedEdge={activeEdge}
            onChooseSector={onChooseSector}
          />
        </div>
      </section>
    </div>
  );
}

function SectorGraphCanvas({
  graph,
  selectedEdge,
  onSelectEdge,
  onChooseSector,
}: {
  graph: SectorRelationGraph;
  selectedEdge: SectorRelationGraphEdge | null;
  onSelectEdge: (edge: SectorRelationGraphEdge) => void;
  onChooseSector: (node: SectorRelationGraphNode) => void;
}) {
  const layout = useMemo(() => graphLayout(graph), [graph]);
  const selectedKey = selectedEdge ? edgeKey(selectedEdge) : "";

  return (
    <div className="min-w-0 rounded-md bg-muted/30 p-3">
      <svg viewBox="0 0 980 560" role="img" aria-label={`${graph.query} 板块关联图谱`} className="h-[520px] w-full">
        <defs>
          <linearGradient id="edgeGradient" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity="0.35" />
            <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity="0.8" />
          </linearGradient>
        </defs>
        {graph.edges.map((edge) => {
          const source = layout.get(edge.source);
          const target = layout.get(edge.target);
          if (!source || !target) return null;
          const active = edgeKey(edge) === selectedKey;
          return (
            <g key={edgeKey(edge)} onClick={() => onSelectEdge(edge)} className="cursor-pointer">
              <line
                x1={source.x}
                y1={source.y}
                x2={target.x}
                y2={target.y}
                stroke={active ? "url(#edgeGradient)" : "hsl(var(--border))"}
                strokeWidth={Math.max(1.2, edge.score / 18)}
                strokeOpacity={active ? 0.95 : 0.58}
              />
              <line x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="transparent" strokeWidth={18} />
            </g>
          );
        })}
        {graph.nodes.map((node) => {
          const point = layout.get(node.id);
          if (!point) return null;
          const radius = nodeRadius(node);
          return (
            <g key={node.id} className="cursor-pointer" onClick={() => onChooseSector(node)}>
              <circle
                cx={point.x}
                cy={point.y}
                r={radius}
                fill="hsl(var(--background))"
                stroke={nodeStroke(node)}
                strokeWidth={2.2}
              />
              <circle
                cx={point.x}
                cy={point.y}
                r={Math.max(4, radius * 0.26)}
                fill={nodeFill(node)}
                opacity={0.9}
              />
              <text
                x={point.x}
                y={point.y + radius + 18}
                textAnchor="middle"
                className="fill-foreground text-[13px] font-medium"
              >
                {node.name}
              </text>
              <text
                x={point.x}
                y={point.y + radius + 34}
                textAnchor="middle"
                className="fill-muted-foreground text-[11px]"
              >
                {formatPct(node.change_pct ?? node.avg_change_pct)} · {node.stock_count ?? node.loaded_stock_count}股
              </text>
            </g>
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center gap-3 border-t pt-3 text-xs text-muted-foreground">
        <span>圆点越大表示板块成交活跃度越高</span>
        <span>红/绿表示板块当日涨跌</span>
        <span>连线越粗表示成分股重叠、名称相似和行情共振越强</span>
      </div>
    </div>
  );
}

function GraphInspector({
  graph,
  selectedEdge,
  onChooseSector,
}: {
  graph: SectorRelationGraph;
  selectedEdge: SectorRelationGraphEdge | null;
  onChooseSector: (sector: SectorInfo) => void;
}) {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  return (
    <aside className="min-w-0 space-y-3">
      <section className="rounded-md border bg-background">
        <PanelHeader icon={<GitBranch size={16} />} title="中心板块" meta={`${graph.central_nodes.length} 个`} />
        <div className="space-y-2 p-3">
          {graph.central_nodes.slice(0, 5).map((node) => (
            <button
              key={node.id}
              type="button"
              onClick={() => {
                const sourceNode = nodeById.get(node.id);
                if (sourceNode) {
                  onChooseSector(sectorFromGraphNode(sourceNode));
                }
              }}
              className="w-full rounded-md border px-3 py-2 text-left hover:bg-muted"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{node.name}</span>
                <span className="text-xs tabular-nums text-muted-foreground">{node.degree_score.toFixed(0)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between text-xs">
                <span className={priceColorClass(node.avg_change_pct)}>{formatPct(node.avg_change_pct)}</span>
                <span className="text-muted-foreground">{formatAmount(node.turnover)}</span>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-md border bg-background">
        <PanelHeader icon={<TrendingUp size={16} />} title="真实板块指标" meta={`${graph.nodes.length} 个`} />
        <div className="space-y-2 p-3">
          {graph.nodes.slice(0, 5).map((node) => (
            <button
              key={`metric-${node.id}`}
              type="button"
              onClick={() => onChooseSector(sectorFromGraphNode(node))}
              className="w-full rounded-md border px-3 py-2 text-left hover:bg-muted"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{node.name}</span>
                <span className={cn("text-xs tabular-nums", priceColorClass(node.change_pct ?? node.avg_change_pct))}>
                  {formatPct(node.change_pct ?? node.avg_change_pct)}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
                <span>{node.rise_count ?? "--"}涨 / {node.fall_count ?? "--"}跌</span>
                <span>{node.leader_stock ?? "无领涨股"}</span>
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-md border bg-background">
        <PanelHeader icon={<Layers3 size={16} />} title="关联详情" meta={selectedEdge ? `${selectedEdge.score.toFixed(0)} 分` : "无"} />
        {selectedEdge ? (
          <div className="space-y-3 p-3">
            <div>
              <p className="text-sm font-semibold">{selectedEdge.source_name} → {selectedEdge.target_name}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {selectedEdge.reasons.map((reason) => (
                  <Badge key={reason} variant="outline">{reason}</Badge>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <MetricMini label="共享股" value={`${selectedEdge.shared_stock_count}`} />
              <MetricMini label="重叠率" value={formatPct(selectedEdge.shared_stock_ratio)} />
              <MetricMini label="名称相似" value={formatPct(selectedEdge.name_similarity)} />
              <MetricMini label="行情共振" value={formatPct(selectedEdge.co_movement)} />
            </div>
            <div>
              <p className="mb-2 text-xs font-medium text-muted-foreground">共享代表股票</p>
              <div className="space-y-1.5">
                {selectedEdge.shared_stocks.slice(0, 6).map((stock) => (
                  <div key={stock.vt_symbol} className="flex items-center justify-between gap-2 text-xs">
                    <span className="truncate">{stock.name}</span>
                    <span className={priceColorClass(stock.change_pct)}>{formatPct(stock.change_pct)}</span>
                  </div>
                ))}
                {selectedEdge.shared_stocks.length === 0 && (
                  <div className="text-xs text-muted-foreground">当前关联主要来自名称相似或行情共振，暂无共享股票样本</div>
                )}
              </div>
            </div>
          </div>
        ) : (
          <div className="p-3 text-sm text-muted-foreground">暂无可解释关联边</div>
        )}
      </section>

      <section className="rounded-md border bg-background">
        <PanelHeader icon={<Layers3 size={16} />} title="算法分组" meta={`${graph.clusters.length} 组`} />
        <div className="space-y-2 p-3">
          {graph.clusters.slice(0, 6).map((cluster) => (
            <div key={cluster.name} className="rounded-md border px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-medium">{cluster.name}</span>
                <span className={cn("text-xs tabular-nums", priceColorClass(cluster.avg_change_pct))}>{formatPct(cluster.avg_change_pct)}</span>
              </div>
              <div className="mt-1 text-xs text-muted-foreground">
                {cluster.node_count} 节点 · {cluster.edge_count} 关联 · {formatAmount(cluster.turnover)}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-md border bg-background">
        <PanelHeader icon={<Layers3 size={16} />} title="算法说明" />
        <div className="space-y-2 p-3 text-xs text-muted-foreground">
          <p>{graph.algorithm.score_formula}</p>
          <div className="flex flex-wrap items-center gap-2">
            <OriginBadge dataOrigin={graph.data_origin} source={graph.source} />
            <span>节点 {graph.nodes.length} · 关联 {graph.edges.length}</span>
          </div>
        </div>
      </section>
    </aside>
  );
}

function MetricMini({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-muted/50 px-2.5 py-2">
      <p className="text-muted-foreground">{label}</p>
      <p className="mt-1 font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function OriginBadge({ dataOrigin, source }: { dataOrigin?: string; source?: string }) {
  const local = dataOrigin === "local_db" || source?.startsWith("postgresql");
  return (
    <Badge variant={local ? "secondary" : "outline"} className="rounded-md gap-1">
      {local ? <Database size={13} /> : <Radio size={13} />}
      {local ? "本地算法" : "实时计算"}
    </Badge>
  );
}

function sourceLabel(dataOrigin?: string, source?: string) {
  if (dataOrigin === "local_db" || source?.startsWith("postgresql")) return "本地库 + 动态算法";
  return "实时公开源 + 动态算法";
}

function sectorSourceLabel(source?: string) {
  if (!source) return "--";
  if (source.startsWith("postgresql")) return "本地板块库";
  if (source.includes("searchapi")) return "实时板块搜索";
  if (source.includes("eastmoney")) return "实时板块数据";
  return source;
}

function SectorWorkspace({
  selection,
  onChooseSector,
}: {
  selection: Extract<Selection, { kind: "sector" }>;
  onChooseSector: (sector: SectorInfo) => void;
}) {
  const navigate = useNavigate();
  const [stockFilter, setStockFilter] = useState("");
  const trendQuery = useQuery({
    queryKey: ["sector-trend", selection.id],
    queryFn: () => fetchSectorTrend(selection.id),
  });
  const stocksQuery = useQuery({
    queryKey: ["sector-stocks", selection.id, stockFilter],
    queryFn: () => fetchSectorStocks(selection.id, 1, 100, false, stockFilter),
  });
  const relationQuery = useQuery({
    queryKey: ["sector-relation-graph", selection.name],
    queryFn: () => fetchSectorRelationGraph(selection.name, 12, 50),
  });
  const chainQuery = useQuery({
    queryKey: ["industry-chain-map", selection.name],
    queryFn: () => fetchIndustryChainMap(selection.name, 30),
  });
  const stocks = stocksQuery.data?.items ?? [];
  const sampleSize = trendQuery.data?.sample_size;

  return (
    <div className="min-w-0 space-y-4">
      <section className="rounded-md border">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b p-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-lg font-semibold">{selection.name}</h3>
              <Badge variant="outline">{sectorTypeLabel(selection.sectorType)}</Badge>
            </div>
            <p className="mt-1 font-mono text-xs text-muted-foreground">{selection.id}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <OriginBadge
              dataOrigin={trendQuery.data?.data_origin ?? stocksQuery.data?.data_origin}
              source={trendQuery.data?.source ?? stocksQuery.data?.source}
            />
            {stocksQuery.data?.total != null && (
              <Badge variant="outline" className="rounded-md">
                {stocksQuery.data.total} 只成分股
              </Badge>
            )}
          </div>
        </div>

        {trendQuery.isLoading || stocksQuery.isLoading ? (
          <LoadingState rows={3} />
        ) : trendQuery.isError ? (
          <ErrorState
            message={trendQuery.error instanceof Error ? trendQuery.error.message : "板块趋势加载失败"}
            onRetry={() => trendQuery.refetch()}
          />
        ) : stocksQuery.isError ? (
          <ErrorState
            message={stocksQuery.error instanceof Error ? stocksQuery.error.message : "板块成分股加载失败"}
            onRetry={() => stocksQuery.refetch()}
          />
        ) : (
          <SectorOverview
            selection={selection}
            trend={trendQuery.data}
            stocks={stocks}
            graph={relationQuery.data}
            graphLoading={relationQuery.isLoading}
            onChooseSector={onChooseSector}
          />
        )}
      </section>

      <FocusStocksSection
        stocks={chainQuery.data?.focus_stocks ?? stocks}
        isLoading={chainQuery.isLoading && stocks.length === 0}
        onRowClick={(stock) => navigate(`/stocks/${stock.vt_symbol}`)}
      />

      <DynamicChainSection
        chain={chainQuery.data}
        isLoading={chainQuery.isLoading}
        isError={chainQuery.isError}
        error={chainQuery.error}
        onRetry={() => chainQuery.refetch()}
        onChooseSector={onChooseSector}
      />

      <section className="rounded-md border">
        <PanelHeader
          icon={<TrendingUp size={16} />}
          title="成分股"
          meta={
            stocksQuery.isLoading
              ? "加载中"
              : `${stocks.length}/${stocksQuery.data?.total ?? stocks.length} 只${sampleSize ? ` · 趋势样本 ${sampleSize}` : ""}`
          }
        />
        <div className="flex flex-col gap-2 border-b p-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative min-w-0 sm:w-80">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={stockFilter}
              onChange={(event) => setStockFilter(event.target.value)}
              className="h-9 pl-9"
              placeholder="在当前板块内搜索股票名称或代码"
            />
          </div>
          <p className="text-xs text-muted-foreground">
            当前显示前 100 条，可点击涨跌幅、5 日、10 日、20 日、成交额排序
          </p>
        </div>
        {stocksQuery.isLoading ? (
          <LoadingState rows={8} />
        ) : stocksQuery.isError ? (
          <ErrorState
            message={stocksQuery.error instanceof Error ? stocksQuery.error.message : "板块成分股加载失败"}
            onRetry={() => stocksQuery.refetch()}
          />
        ) : (
          <StockTable
            stocks={stocks}
            showReturns
            initialSort={{ key: "change_pct", direction: "desc" }}
            onRowClick={(stock) => navigate(`/stocks/${stock.vt_symbol}`)}
          />
        )}
      </section>

      <GraphWorkspace
        query={selection.name}
        onChooseSector={onChooseSector}
        compact
      />
    </div>
  );
}

function SectorOverview({
  selection,
  trend,
  stocks,
  graph,
  graphLoading,
  onChooseSector,
}: {
  selection: Extract<Selection, { kind: "sector" }>;
  trend?: SectorTrend;
  stocks: StockQuote[];
  graph?: SectorRelationGraph;
  graphLoading: boolean;
  onChooseSector: (sector: SectorInfo) => void;
}) {
  const sortedByTurnover = useMemo(() => sortStocks(stocks, { key: "turnover", direction: "desc" }).slice(0, 5), [stocks]);
  const sortedByChange = useMemo(() => sortStocks(stocks, { key: "change_pct", direction: "desc" }).slice(0, 5), [stocks]);
  const strongEdges = useMemo(() => strongestEdgesForQuery(graph, selection.name).slice(0, 5), [graph, selection.name]);
  const graphNodeById = useMemo(() => new Map((graph?.nodes ?? []).map((node) => [node.id, node])), [graph]);
  const primary = trend?.turnover_weighted_change_pct ?? trend?.avg_change_pct;

  return (
    <div className="grid min-w-0 gap-0 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="min-w-0">
        <div className="grid border-b sm:grid-cols-2 xl:grid-cols-4">
          <Metric label="趋势" value={trendStateLabel(trend?.trend_state ?? "UNKNOWN")} valueClass={priceColorClass(primary)} />
          <Metric label="成交额加权" value={formatPct(trend?.turnover_weighted_change_pct)} valueClass={priceColorClass(trend?.turnover_weighted_change_pct)} />
          <Metric label="上涨家数" value={trend ? `${trend.rise_count}/${trend.sample_size}` : "--"} subValue={formatRatio(trend?.rise_ratio)} />
          <Metric label="成交额" value={formatAmount(trend?.turnover)} />
        </div>
        <SectorBreadth trend={trend} />

        <div className="grid min-w-0 gap-0 lg:grid-cols-2">
          <StockMiniList title="成交额靠前" stocks={sortedByTurnover} />
          <StockMiniList title="涨幅靠前" stocks={sortedByChange} />
        </div>
      </div>

      <aside className="border-t p-4 xl:border-l xl:border-t-0">
        <div className="flex items-center justify-between gap-3">
          <h4 className="text-sm font-semibold">强关联证据</h4>
          <span className="text-xs text-muted-foreground">{graphLoading ? "计算中" : `${strongEdges.length} 个`}</span>
        </div>
        <div className="mt-3 space-y-2">
          {graphLoading ? (
            <LoadingState rows={3} />
          ) : strongEdges.length === 0 ? (
            <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">
              暂无强关联。先看成分股和趋势。
            </div>
          ) : (
            strongEdges.map((edge) => {
              const related = relatedSectorFromEdge(edge, selection.name, graphNodeById);
              return (
                <button
                  key={edgeKey(edge)}
                  type="button"
                  onClick={() => onChooseSector(related)}
                  className="w-full rounded-md border px-3 py-2 text-left hover:bg-muted"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{related.name}</span>
                    <span className="text-xs tabular-nums text-muted-foreground">{edge.score.toFixed(0)}分</span>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    共享 {edge.shared_stock_count} 股 · 重叠 {formatRatio(edge.shared_stock_ratio)}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {edge.shared_stocks.slice(0, 3).map((stock) => stock.name).join("、") || "按名称/行情相似关联"}
                  </div>
                </button>
              );
            })
          )}
        </div>
      </aside>
    </div>
  );
}

function SectorBreadth({ trend }: { trend?: SectorTrend }) {
  const rise = clampPercent(trend?.rise_ratio);
  const fall = clampPercent(trend?.fall_ratio);
  const flat = Math.max(0, 100 - rise - fall);
  return (
    <div className="border-b px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className="font-medium text-muted-foreground">涨跌分布</span>
        <span className="text-muted-foreground">
          {trend ? `${trend.rise_count} 涨 / ${trend.flat_count} 平 / ${trend.fall_count} 跌` : "--"}
        </span>
      </div>
      <div className="flex h-2 overflow-hidden rounded bg-muted">
        <div className="bg-rise" style={{ width: `${rise}%` }} />
        <div className="bg-muted-foreground/30" style={{ width: `${flat}%` }} />
        <div className="bg-fall" style={{ width: `${fall}%` }} />
      </div>
    </div>
  );
}

function FocusStocksSection({
  stocks,
  isLoading,
  onRowClick,
}: {
  stocks: (StockQuote | ChainStock)[];
  isLoading: boolean;
  onRowClick: (stock: StockQuote | ChainStock) => void;
}) {
  const focusStocks = useMemo(
    () => sortStocks(stocks, { key: "turnover", direction: "desc" }).slice(0, 12),
    [stocks]
  );
  return (
    <section className="rounded-md border">
      <PanelHeader icon={<TrendingUp size={16} />} title="当前可观察股票" meta={isLoading ? "计算中" : `${focusStocks.length} 只`} />
      {isLoading ? (
        <div className="p-4">
          <LoadingState rows={3} />
        </div>
      ) : focusStocks.length === 0 ? (
        <div className="p-4 text-sm text-muted-foreground">暂无可观察股票样本。</div>
      ) : (
        <div className="grid divide-y md:grid-cols-2 md:divide-x md:divide-y-0 xl:grid-cols-3">
          {focusStocks.slice(0, 6).map((stock) => (
            <div
              key={`focus-${stock.vt_symbol}`}
              onClick={() => onRowClick(stock)}
              className="min-w-0 cursor-pointer px-4 py-3 hover:bg-muted"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-muted-foreground">{stock.symbol}</span>
                    <span className="truncate text-sm font-semibold">{stock.name}</span>
                  </div>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {"related_sector_name" in stock && stock.related_sector_name ? stock.related_sector_name : stock.vt_symbol}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <p className={cn("text-sm font-semibold tabular-nums", priceColorClass(stock.change_pct))}>{formatPct(stock.change_pct)}</p>
                  <p className="text-xs tabular-nums text-muted-foreground">{formatAmount(stock.turnover)}</p>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function DynamicChainSection({
  chain,
  isLoading,
  isError,
  error,
  onRetry,
  onChooseSector,
}: {
  chain?: IndustryChainMap;
  isLoading: boolean;
  isError: boolean;
  error: unknown;
  onRetry: () => void;
  onChooseSector: (sector: SectorInfo) => void;
}) {
  if (isLoading) {
    return (
      <section className="rounded-md border">
        <PanelHeader icon={<Layers3 size={16} />} title="产业链推断" meta="计算中" />
        <div className="p-4">
          <LoadingState rows={4} />
        </div>
      </section>
    );
  }

  if (isError) {
    return (
      <section className="rounded-md border">
        <PanelHeader icon={<Layers3 size={16} />} title="产业链推断" meta="失败" />
        <ErrorState
          message={error instanceof Error ? error.message : "动态产业链加载失败"}
          onRetry={onRetry}
        />
      </section>
    );
  }

  const segments = orderedChainSegments(chain);
  const visibleSegments = segments.filter((segment) => (segment.nodes ?? []).length > 0);
  const hasNodes = visibleSegments.length > 0;
  if (!chain || !hasNodes) {
    return (
      <section className="rounded-md border">
        <PanelHeader icon={<Layers3 size={16} />} title="产业链推断" meta="暂无强证据" />
        <div className="p-4 text-sm text-muted-foreground">
          当前公开板块数据没有形成足够清晰的链路，只展示上方行情和下方成分股。
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-md border">
      <PanelHeader
        icon={<Layers3 size={16} />}
        title="产业链推断"
        meta={`${chain.related_sectors.length} 个相关板块`}
      />
      <div className={cn("grid gap-0", chainGridClass(visibleSegments.length))}>
        {visibleSegments.map((segment, index) => (
          <ChainStageColumn
            key={segment.stage}
            segment={segment}
            showConnector={index < visibleSegments.length - 1}
            onChooseSector={onChooseSector}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-center gap-2 border-t px-4 py-3 text-xs text-muted-foreground">
        <OriginBadge dataOrigin={chain.data_origin} source={chain.source} />
        <span>{chain.exposure_basis ?? "按真实板块成分股、成交额、市值和涨跌表现动态聚合。"}</span>
      </div>
    </section>
  );
}

function ChainStageColumn({
  segment,
  showConnector,
  onChooseSector,
}: {
  segment: IndustryChainSegment;
  showConnector: boolean;
  onChooseSector: (sector: SectorInfo) => void;
}) {
  const nodes = segment.nodes ?? [];
  const representativeStocks = (segment.representative_stocks ?? []).slice(0, 4);
  return (
    <div className="min-w-0 border-b p-4 lg:border-b-0 lg:border-r">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h4 className="truncate text-sm font-semibold">{stageTitle(segment)}</h4>
            {showConnector && <ArrowRight size={15} className="hidden text-muted-foreground lg:block" />}
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {segment.stock_count ?? 0} 股 · 成交额占比 {formatRatio(segment.turnover_ratio)}
          </p>
        </div>
        <span className={cn("shrink-0 text-xs tabular-nums", priceColorClass(segment.avg_change_pct))}>
          {formatPct(segment.avg_change_pct)}
        </span>
      </div>

      <div className="mt-3 space-y-2">
        {nodes.length > 0 ? (
          nodes.slice(0, 5).map((node) => {
            const sector = node.matched_sectors?.[0];
            return (
              <button
                key={node.id}
                type="button"
                disabled={!sector}
                onClick={() => sector && onChooseSector(sector)}
                className={cn(
                  "w-full rounded-md border px-3 py-2 text-left",
                  sector ? "hover:bg-muted" : "cursor-default"
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium">{node.name}</span>
                  <span className="text-xs tabular-nums text-muted-foreground">{formatRatio(node.weight)}</span>
                </div>
                {sector && (
                  <div className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span>{sector.stock_count ?? "--"} 只成分股</span>
                    <span className={priceColorClass(sector.change_pct)}>{formatPct(sector.change_pct)}</span>
                  </div>
                )}
              </button>
            );
          })
        ) : (
          <div className="rounded-md border border-dashed px-3 py-4 text-sm text-muted-foreground">暂无强证据节点</div>
        )}
      </div>

      {representativeStocks.length > 0 && (
        <div className="mt-4 border-t pt-3">
          <p className="mb-2 text-xs font-medium text-muted-foreground">代表股票</p>
          <div className="space-y-1.5">
            {representativeStocks.map((stock) => (
              <div key={`${segment.stage}-${stock.vt_symbol}`} className="grid grid-cols-[minmax(0,1fr)_64px_84px] gap-2 text-xs">
                <span className="truncate">{stock.name}</span>
                <span className={cn("text-right tabular-nums", priceColorClass(stock.change_pct))}>{formatPct(stock.change_pct)}</span>
                <span className="text-right tabular-nums text-muted-foreground">{formatAmount(stock.turnover)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StockMiniList({ title, stocks }: { title: string; stocks: StockQuote[] }) {
  return (
    <div className="min-w-0 border-b p-4 lg:border-r">
      <h4 className="mb-3 text-sm font-semibold">{title}</h4>
      <div className="space-y-2">
        {stocks.map((stock) => (
          <div key={`${title}-${stock.vt_symbol}`} className="grid grid-cols-[minmax(0,1fr)_64px_72px] items-center gap-2 text-sm">
            <div className="min-w-0">
              <div className="truncate font-medium">{stock.name}</div>
              <div className="mt-0.5 font-mono text-[11px] text-muted-foreground">{stock.symbol}</div>
            </div>
            <span className={cn("text-right text-xs tabular-nums", priceColorClass(stock.change_pct))}>{formatPct(stock.change_pct)}</span>
            <span className="text-right text-xs tabular-nums text-muted-foreground">{formatAmount(stock.turnover)}</span>
          </div>
        ))}
        {stocks.length === 0 && <div className="text-sm text-muted-foreground">暂无股票样本</div>}
      </div>
    </div>
  );
}

function orderedChainSegments(chain?: IndustryChainMap): IndustryChainSegment[] {
  const segments = chain?.segments ?? [];
  const order = ["source", "bridge", "sink"];
  return order
    .map((stage) => segments.find((segment) => segment.stage === stage))
    .filter((segment): segment is IndustryChainSegment => Boolean(segment));
}

function stageTitle(segment: IndustryChainSegment) {
  if (segment.stage === "source") return "上游线索";
  if (segment.stage === "bridge") return "当前核心";
  if (segment.stage === "sink") return "相关扩散";
  return segment.label;
}

function chainGridClass(count: number) {
  if (count <= 1) return "lg:grid-cols-1";
  if (count === 2) return "lg:grid-cols-2";
  return "lg:grid-cols-3";
}

function clampPercent(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function formatRatio(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value.toFixed(2)}%`;
}

function StockTable({
  stocks,
  showSector = false,
  showReturns = false,
  initialSort = { key: "turnover", direction: "desc" },
  onRowClick,
}: {
  stocks: (StockQuote | ChainStock)[];
  showSector?: boolean;
  showReturns?: boolean;
  initialSort?: StockSort;
  onRowClick: (stock: StockQuote | ChainStock) => void;
}) {
  const [sort, setSort] = useState<StockSort>(initialSort);
  const sortedStocks = useMemo(() => sortStocks(stocks, sort), [stocks, sort]);

  function toggleSort(key: StockSortKey) {
    setSort((current) => ({
      key,
      direction: current.key === key && current.direction === "desc" ? "asc" : "desc",
    }));
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[980px] text-sm">
        <thead className="bg-muted/60 text-muted-foreground">
          <tr>
            <SortableHeader label="代码" sortKey="symbol" sort={sort} onSort={toggleSort} />
            <SortableHeader label="名称" sortKey="name" sort={sort} onSort={toggleSort} />
            {showSector && <SortableHeader label="关联板块" sortKey="related_sector_name" sort={sort} onSort={toggleSort} />}
            <SortableHeader label="最新价" sortKey="last_price" sort={sort} onSort={toggleSort} align="right" />
            <SortableHeader label="涨跌幅" sortKey="change_pct" sort={sort} onSort={toggleSort} align="right" />
            {showReturns && <SortableHeader label="5日" sortKey="return_5d" sort={sort} onSort={toggleSort} align="right" />}
            {showReturns && <SortableHeader label="10日" sortKey="return_10d" sort={sort} onSort={toggleSort} align="right" />}
            {showReturns && <SortableHeader label="20日" sortKey="return_20d" sort={sort} onSort={toggleSort} align="right" />}
            <SortableHeader label="成交额" sortKey="turnover" sort={sort} onSort={toggleSort} align="right" />
            <SortableHeader label="换手率" sortKey="turnover_rate" sort={sort} onSort={toggleSort} align="right" />
            <SortableHeader label="市值" sortKey="market_cap" sort={sort} onSort={toggleSort} align="right" />
          </tr>
        </thead>
        <tbody>
          {sortedStocks.map((stock) => (
            <tr
              key={`${stock.vt_symbol}-${"related_sector_id" in stock ? stock.related_sector_id ?? "" : ""}`}
              className="cursor-pointer border-t hover:bg-muted/40"
              onClick={() => onRowClick(stock)}
            >
              <td className="px-3 py-2 font-mono text-xs">{stock.symbol}</td>
              <td className="px-3 py-2">
                <StockIdentityLink
                  name={stock.name}
                  vtSymbol={stock.vt_symbol}
                  board={stock.board}
                  boardLabel={stock.board_label}
                  link={false}
                />
              </td>
              {showSector && (
                <td className="px-3 py-2 text-muted-foreground">
                  {"related_sector_name" in stock ? stock.related_sector_name ?? "--" : "--"}
                </td>
              )}
              <td className="px-3 py-2 text-right tabular-nums">{formatPrice(stock.last_price)}</td>
              <td className={cn("px-3 py-2 text-right font-medium tabular-nums", priceColorClass(stock.change_pct))}>
                {formatPct(stock.change_pct)}
              </td>
              {showReturns && <ReturnCell value={stock.return_5d} />}
              {showReturns && <ReturnCell value={stock.return_10d} />}
              {showReturns && <ReturnCell value={stock.return_20d} />}
              <td className="px-3 py-2 text-right tabular-nums">{formatAmount(stock.turnover)}</td>
              <td className="px-3 py-2 text-right tabular-nums">
                {stock.turnover_rate != null ? `${stock.turnover_rate.toFixed(2)}%` : "--"}
              </td>
              <td className="px-3 py-2 text-right tabular-nums">{formatMarketCap(stock.market_cap)}</td>
            </tr>
          ))}
          {sortedStocks.length === 0 && (
            <tr>
              <td colSpan={showSector ? 11 : showReturns ? 10 : 7} className="px-3 py-8 text-center text-sm text-muted-foreground">
                当前条件下没有匹配股票
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SortableHeader({
  label,
  sortKey,
  sort,
  onSort,
  align = "left",
}: {
  label: string;
  sortKey: StockSortKey;
  sort: StockSort;
  onSort: (key: StockSortKey) => void;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  return (
    <th className={cn("px-3 py-2", align === "right" ? "text-right" : "text-left")}>
      <button
        type="button"
        onClick={() => onSort(sortKey)}
        className={cn(
          "inline-flex items-center gap-1 rounded px-1 py-0.5 text-xs font-medium hover:bg-background",
          align === "right" && "justify-end"
        )}
      >
        {label}
        <span className={cn("text-[10px]", active ? "text-foreground" : "text-muted-foreground/50")}>
          {active ? (sort.direction === "desc" ? "↓" : "↑") : "↕"}
        </span>
      </button>
    </th>
  );
}

function PanelHeader({ icon, title, meta }: { icon: React.ReactNode; title: string; meta?: string }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b px-3 py-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <span className="text-muted-foreground">{icon}</span>
        <h3 className="truncate text-sm font-semibold">{title}</h3>
      </div>
      {meta && <span className="shrink-0 text-xs text-muted-foreground">{meta}</span>}
    </div>
  );
}

function Metric({
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
    <div className="border-b px-4 py-3 sm:border-r xl:border-b-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className={cn("text-sm font-semibold tabular-nums", valueClass)}>{value}</span>
        {subValue && <span className="text-xs text-muted-foreground tabular-nums">{subValue}</span>}
      </div>
    </div>
  );
}

function ReturnCell({ value }: { value: number | null | undefined }) {
  return (
    <td className={cn("px-3 py-2 text-right tabular-nums", priceColorClass(value))}>
      {formatPct(value)}
    </td>
  );
}

function sortStocks<T extends StockQuote | ChainStock>(stocks: T[], sort: StockSort): T[] {
  return [...stocks].sort((left, right) => {
    const leftValue = stockSortValue(left, sort.key);
    const rightValue = stockSortValue(right, sort.key);
    const direction = sort.direction === "desc" ? -1 : 1;
    if (leftValue == null && rightValue == null) return 0;
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;
    if (typeof leftValue === "number" && typeof rightValue === "number") {
      return (leftValue - rightValue) * direction;
    }
    return String(leftValue).localeCompare(String(rightValue), "zh-Hans-CN") * direction;
  });
}

function stockSortValue(stock: StockQuote | ChainStock, key: StockSortKey): number | string | null | undefined {
  if (key === "related_sector_name") {
    return "related_sector_name" in stock ? stock.related_sector_name : "";
  }
  return stock[key];
}

function resultTypeLabel(item: SectorSearchResult) {
  return sectorTypeLabel(item.type);
}

function sectorTypeLabel(type: string) {
  if (type === "industry") return "行业";
  if (type === "region") return "地域";
  if (type === "theme") return "主题";
  return "概念";
}

function trendStateLabel(state: SectorTrend["trend_state"]) {
  if (state === "STRONG_UP") return "强势上涨";
  if (state === "UP") return "上涨";
  if (state === "STRONG_DOWN") return "强势下跌";
  if (state === "DOWN") return "下跌";
  if (state === "RANGE") return "震荡";
  return "未知";
}

function graphLayout(graph: SectorRelationGraph): Map<string, { x: number; y: number }> {
  const width = 980;
  const height = 560;
  const center = { x: width / 2, y: height / 2 };
  const degree = new Map<string, number>();
  graph.nodes.forEach((node) => degree.set(node.id, 0));
  graph.edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + edge.score);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + edge.score);
  });

  const sorted = [...graph.nodes].sort((left, right) => {
    const degreeDiff = (degree.get(right.id) ?? 0) - (degree.get(left.id) ?? 0);
    if (degreeDiff !== 0) return degreeDiff;
    return String(left.name).localeCompare(String(right.name), "zh-Hans-CN");
  });
  const positions = new Map<string, { x: number; y: number }>();
  if (!sorted.length) return positions;

  positions.set(sorted[0].id, center);
  const rings = sorted.slice(1);
  rings.forEach((node, index) => {
    const angle = (Math.PI * 2 * index) / Math.max(rings.length, 1) - Math.PI / 2;
    const strength = Math.min((degree.get(node.id) ?? 0) / 220, 1);
    const radius = 170 + (index % 2) * 72 - strength * 45;
    positions.set(node.id, {
      x: center.x + Math.cos(angle) * radius,
      y: center.y + Math.sin(angle) * radius,
    });
  });

  graph.edges.slice(0, 18).forEach((edge) => {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) return;
    const pull = Math.min(edge.score / 900, 0.08);
    const dx = target.x - source.x;
    const dy = target.y - source.y;
    positions.set(edge.source, { x: source.x + dx * pull, y: source.y + dy * pull });
    positions.set(edge.target, { x: target.x - dx * pull, y: target.y - dy * pull });
  });

  return positions;
}

function nodeRadius(node: SectorRelationGraphNode) {
  const turnover = node.turnover ?? 0;
  const scaledTurnover = Math.sqrt(Math.max(turnover, 0)) / 28000;
  const scaledCount = Math.min(node.loaded_stock_count / 5, 10);
  return Math.max(22, Math.min(46, 22 + scaledTurnover + scaledCount));
}

function nodeStroke(node: SectorRelationGraphNode) {
  const change = node.avg_change_pct ?? 0;
  if (change > 1) return "rgb(220 38 38)";
  if (change < -1) return "rgb(22 163 74)";
  return "hsl(var(--primary))";
}

function nodeFill(node: SectorRelationGraphNode) {
  const change = node.avg_change_pct ?? 0;
  if (change > 1) return "rgb(220 38 38)";
  if (change < -1) return "rgb(22 163 74)";
  return "hsl(var(--primary))";
}

function edgeKey(edge: SectorRelationGraphEdge) {
  return `${edge.source}->${edge.target}`;
}

function compactGraphForQuery(graph: SectorRelationGraph, query: string): SectorRelationGraph {
  const edges = strongestEdgesForQuery(graph, query);
  const ids = new Set<string>();
  edges.forEach((edge) => {
    ids.add(edge.source);
    ids.add(edge.target);
  });

  const focus = focusNodeForQuery(graph, query);
  if (focus) ids.add(focus.id);

  const nodes = graph.nodes.filter((node) => ids.has(node.id));
  const centralIds = new Set(nodes.map((node) => node.id));
  return {
    ...graph,
    nodes,
    edges,
    clusters: graph.clusters.filter((cluster) => cluster.node_ids.some((nodeId) => ids.has(String(nodeId)))),
    central_nodes: graph.central_nodes.filter((node) => centralIds.has(node.id)),
  };
}

function strongestEdgesForQuery(graph: SectorRelationGraph | undefined, query: string): SectorRelationGraphEdge[] {
  if (!graph) return [];
  const focus = focusNodeForQuery(graph, query);
  const directEdges = focus
    ? graph.edges.filter((edge) => edge.source === focus.id || edge.target === focus.id)
    : graph.edges;

  return directEdges
    .filter((edge) => edge.shared_stock_count >= 3 || edge.shared_stock_ratio >= 15 || edge.score >= 18)
    .sort((left, right) => {
      const sharedDiff = right.shared_stock_count - left.shared_stock_count;
      if (sharedDiff !== 0) return sharedDiff;
      return right.score - left.score;
    })
    .slice(0, 8);
}

function focusNodeForQuery(graph: SectorRelationGraph, query: string): SectorRelationGraphNode | null {
  const normalizedQuery = normalizeText(query);
  if (!normalizedQuery) return graph.nodes[0] ?? null;
  return (
    graph.nodes.find((node) => normalizeText(node.name) === normalizedQuery) ??
    graph.nodes.find((node) => normalizeText(node.name).includes(normalizedQuery) || normalizedQuery.includes(normalizeText(node.name))) ??
    graph.nodes[0] ??
    null
  );
}

function graphHasEdge(graph: SectorRelationGraph, edge: SectorRelationGraphEdge) {
  return graph.edges.some((item) => edgeKey(item) === edgeKey(edge));
}

function relatedSectorFromEdge(
  edge: SectorRelationGraphEdge,
  query: string,
  nodeById?: Map<string, SectorRelationGraphNode>,
): SectorInfo {
  const normalizedQuery = normalizeText(query);
  const sourceIsFocus = normalizeText(edge.source_name) === normalizedQuery || normalizeText(edge.source_name).includes(normalizedQuery);
  const targetIsFocus = normalizeText(edge.target_name) === normalizedQuery || normalizeText(edge.target_name).includes(normalizedQuery);
  if (sourceIsFocus && !targetIsFocus) {
    const node = nodeById?.get(edge.target);
    return node ? sectorFromGraphNode(node) : { id: edge.target, name: edge.target_name, type: "concept", path: [], source: "alphaagent_relation_algorithm" };
  }
  const node = nodeById?.get(edge.source);
  return node ? sectorFromGraphNode(node) : { id: edge.source, name: edge.source_name, type: "concept", path: [], source: "alphaagent_relation_algorithm" };
}

function normalizeText(value: string | null | undefined) {
  return String(value ?? "").toLowerCase().replace(/[\s\-_/\\|:：()（）.]+/g, "");
}

function sectorFromGraphNode(node: SectorRelationGraphNode): SectorInfo {
  return {
    id: node.id,
    name: node.name,
    type: node.type,
    path: node.path,
    source: node.source,
  };
}
