/**
 * ChainGraphPage — 产业链图谱
 *
 * Search-driven: user types a keyword, we call the relation-graph API
 * to get an interactive @xyflow/react visualization.
 *
 * Also supports pre-defined chains from /industry-chains list (when available).
 */
import { useState, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeTypes,
  Position,
  MarkerType,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { fetchIndustryChains, fetchSectorRelationGraph } from "@/api/sectors";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { ConceptTag } from "@/components/ConceptTag";
import { cn, formatPct } from "@/lib/utils";
import { motion } from "framer-motion";
import { KpiNumber } from "@/components/motion";
import type { SectorRelationGraph } from "@/api/types";
import {
  Network,
  Search,
  Maximize2,
} from "lucide-react";

// ── Popular search suggestions ──
const SUGGESTIONS = [
  "半导体", "AI", "新能源车", "光伏", "机器人",
  "锂电池", "消费电子", "军工", "医药", "白酒",
];

// ── Custom node component ──

function ChainNode({ data }: { data: { label: string; changePct?: number | null; stockCount?: number | null } }) {
  const changePct = data.changePct;
  const isFall = changePct != null && changePct < 0;

  return (
    <motion.div
      initial={{ scale: 0.8, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className={cn(
        "rounded-lg border-2 border-gray-300 bg-white px-3 py-2 shadow-sm min-w-[100px] text-center dark:border-gray-600 dark:bg-gray-800"
      )}
    >
      <div className="text-xs font-bold">{data.label}</div>
      {data.stockCount != null && (
        <div className="text-[10px] text-muted-foreground">{data.stockCount}只</div>
      )}
      {changePct != null && (
        <KpiNumber
          value={changePct}
          format="pct"
          pulse
          className={cn(
            "block text-xs font-semibold",
            changePct > 0 ? "text-rise" : isFall ? "text-fall" : "text-gray-500 dark:text-gray-400"
          )}
        />
      )}
    </motion.div>
  );
}

const nodeTypes: NodeTypes = {
  chainNode: ChainNode,
};

// ── Convert relation graph to React Flow nodes/edges ──

function graphToFlowElements(graph: SectorRelationGraph) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  // Layout: group by clusters if available, otherwise arrange in force-like layout
  const clusterMap: Record<string, number> = {};
  let clusterIdx = 0;
  for (const c of graph.clusters ?? []) {
    for (const nid of c.node_ids ?? []) {
      if (!(nid in clusterMap)) {
        clusterMap[nid] = clusterIdx;
      }
    }
    clusterIdx++;
  }

  // Assign unclustered nodes to their own column
  for (const n of graph.nodes) {
    if (!(n.id in clusterMap)) {
      clusterMap[n.id] = clusterIdx;
      clusterIdx++;
    }
  }

  // Simple grid layout by cluster
  const columnCounts: Record<number, number> = {};
  for (const n of graph.nodes) {
    const col = clusterMap[n.id] ?? 0;
    const row = columnCounts[col] ?? 0;
    columnCounts[col] = row + 1;
    nodes.push({
      id: n.id,
      type: "chainNode",
      position: { x: col * 350, y: row * 120 },
      data: {
        label: n.name,
        changePct: n.change_pct ?? n.avg_change_pct,
        stockCount: n.stock_count,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    });
  }

  // Center each column vertically
  for (const col of Object.keys(columnCounts)) {
    const count = columnCounts[Number(col)];
    const nodesInCol = nodes.filter(
      (_, i) => clusterMap[graph.nodes[i]?.id] === Number(col)
    );
    const offset = -((count - 1) * 60);
    nodesInCol.forEach((node, i) => {
      node.position.y = offset + i * 120;
    });
  }

  // Edges
  for (const e of graph.edges ?? []) {
    edges.push({
      id: `${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      animated: true,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 },
      style: {
        stroke: e.evidence_level === "strong" ? "#3b82f6" : "#94a3b8",
        strokeWidth: Math.max(1, Math.min(3, (e.score ?? 1) / 30)),
      },
    });
  }

  return { nodes, edges };
}

// ── Main Page ──

export default function ChainGraphPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");

  // Pre-defined chains (may be empty)
  const chainsQuery = useQuery({
    queryKey: ["industryChains"],
    queryFn: () => fetchIndustryChains(),
    staleTime: 60_000,
  });

  // Relation graph for active search
  const graphQuery = useQuery({
    queryKey: ["chainGraph", activeQuery],
    queryFn: () => fetchSectorRelationGraph(activeQuery),
    enabled: !!activeQuery,
    staleTime: 60_000,
  });

  const chains = useMemo(() => {
    const data = chainsQuery.data as { items: { id: string; name: string; keywords?: string[] }[] } | undefined | null;
    const items = data?.items ?? [];
    if (!searchQuery.trim() || activeQuery) return items;
    const q = searchQuery.trim().toLowerCase();
    return items.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.keywords?.some((kw) => kw.toLowerCase().includes(q))
    );
  }, [chainsQuery.data, searchQuery, activeQuery]);

  // Flow elements for searched graph
  const flowElements = useMemo(() => {
    const graph = graphQuery.data as SectorRelationGraph | undefined | null;
    if (!graph || graph.nodes.length === 0) return null;
    return graphToFlowElements(graph);
  }, [graphQuery.data]);

  const handleSearch = useCallback(() => {
    const q = searchQuery.trim();
    if (q) setActiveQuery(q);
  }, [searchQuery]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Enter") handleSearch();
  }, [handleSearch]);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="font-display text-xl font-bold">产业链图谱</h1>
      </div>

      {/* Search bar */}
      <div className="flex gap-2">
        <div className="relative flex-1 max-w-md">
          <Search
            size={16}
            className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="搜索行业/概念，如：半导体、AI、新能源车..."
            className="w-full rounded-lg border bg-background py-2 pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-primary/20"
          />
        </div>
        <button
          onClick={handleSearch}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
        >
          搜索
        </button>
      </div>

      {/* Active search graph view */}
      {activeQuery && (
        <ChainGraphView
          query={activeQuery}
          flowElements={flowElements}
          graphData={graphQuery.data as SectorRelationGraph | undefined}
          isLoading={graphQuery.isLoading}
          error={graphQuery.error}
          onBack={() => { setActiveQuery(""); setSearchQuery(""); }}
        />
      )}

      {/* Default view: suggestions + pre-defined chains */}
      {!activeQuery && (
        <>
          {/* Search suggestions */}
          <div className="flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => { setSearchQuery(s); setActiveQuery(s); }}
                className="rounded-full border px-3 py-1 text-sm transition-colors hover:bg-muted hover:border-primary"
              >
                {s}
              </button>
            ))}
          </div>

          {/* Pre-defined chain cards */}
          {chainsQuery.isLoading && <LoadingState rows={4} />}
          {chainsQuery.isError && (
            <ErrorState
              message="加载产业链失败"
              onRetry={() => chainsQuery.refetch()}
            />
          )}

          {chains.length > 0 && (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {chains.map((chain) => (
                <button
                  key={chain.id}
                  className="sector-detail-panel text-left transition-colors hover:border-primary"
                  onClick={() => { setSearchQuery(chain.name); setActiveQuery(chain.name); }}
                >
                  <div className="flex items-center justify-between">
                    <div className="font-medium">{chain.name}</div>
                    <Maximize2 size={14} className="text-muted-foreground" />
                  </div>
                  {chain.keywords && chain.keywords.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {chain.keywords.slice(0, 5).map((kw) => (
                        <ConceptTag key={kw} name={kw} type="concept" />
                      ))}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}

          {!chainsQuery.isLoading && !chainsQuery.isError && chains.length === 0 && (
            <div className="rounded-lg border border-dashed p-8 text-center">
              <Network size={32} className="mx-auto mb-3 text-muted-foreground" />
              <div className="text-muted-foreground">
                输入关键词搜索产业链，例如 "半导体"、"AI"、"新能源车"
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Graph View Component ──

function ChainGraphView({
  query,
  flowElements,
  graphData,
  isLoading,
  error,
  onBack,
}: {
  query: string;
  flowElements: { nodes: Node[]; edges: Edge[] } | null;
  graphData: SectorRelationGraph | undefined;
  isLoading: boolean;
  error: Error | null;
  onBack: () => void;
}) {
  if (isLoading) return <LoadingState rows={6} />;
  if (error) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "加载图谱失败"}
        onRetry={() => {}}
      />
    );
  }

  if (!flowElements || flowElements.nodes.length === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <Network size={32} className="mx-auto mb-3 text-muted-foreground" />
        <div className="text-muted-foreground">
          未找到与 "{query}" 相关的产业链关系
        </div>
        <button
          onClick={onBack}
          className="mt-3 text-sm text-primary hover:underline"
        >
          返回搜索
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Graph info bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border p-3">
        <Network size={16} className="text-primary" />
        <span className="font-medium">"{query}" 产业链关系</span>
        <div className="flex gap-4 text-sm text-muted-foreground">
          <span>{(graphData?.nodes ?? []).length} 个板块</span>
          <span>{(graphData?.edges ?? []).length} 条关系</span>
        </div>
        {/* Clusters */}
        {(graphData?.clusters ?? []).length > 0 && (
          <div className="flex gap-2">
            {graphData!.clusters.map((c) => (
              <span
                key={c.name}
                className="rounded-md bg-muted px-2 py-0.5 text-xs"
              >
                {c.name}
              </span>
            ))}
          </div>
        )}
        <button
          onClick={onBack}
          className="ml-auto text-sm text-primary hover:underline"
        >
          ← 新搜索
        </button>
      </div>

      {/* React Flow canvas */}
      <div className="h-[500px] rounded-lg border bg-muted/20">
        <ReactFlow
          nodes={flowElements.nodes}
          edges={flowElements.edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.3 }}
          minZoom={0.3}
          maxZoom={2}
          attributionPosition="bottom-left"
        >
          <Background gap={20} size={1} />
          <Controls showInteractive={false} />
          <MiniMap
            nodeStrokeWidth={2}
            pannable
            zoomable
          />
        </ReactFlow>
      </div>

      {/* Node list table */}
      {(graphData?.nodes ?? []).length > 0 && (
        <section className="rounded-lg border">
          <div className="border-b px-4 py-3">
            <h3 className="text-sm font-semibold">关联板块</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground bg-muted/50">
                <tr>
                  <th className="px-4 py-2 text-left">名称</th>
                  <th className="px-4 py-2 text-right">涨跌幅</th>
                  <th className="px-4 py-2 text-right">成分股</th>
                  <th className="px-4 py-2 text-right">龙头</th>
                </tr>
              </thead>
              <tbody>
                {graphData!.nodes.map((n) => (
                  <tr key={n.id} className="border-t hover:bg-muted/30">
                    <td className="px-4 py-2 font-medium">{n.name}</td>
                    <td className={cn(
                      "px-4 py-2 text-right tabular-nums",
                      (n.change_pct ?? 0) > 0 ? "text-rise" : (n.change_pct ?? 0) < 0 ? "text-fall" : ""
                    )}>
                      {n.change_pct != null ? formatPct(n.change_pct) : "--"}
                    </td>
                    <td className="px-4 py-2 text-right tabular-nums text-muted-foreground">
                      {n.stock_count ?? n.loaded_stock_count ?? "--"}
                    </td>
                    <td className="px-4 py-2 text-right text-muted-foreground">
                      {n.leader_stock ?? "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
