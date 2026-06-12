import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Briefcase, RefreshCw } from "lucide-react";
import {
  addPortfolioGroupItem,
  autoBuyRecommendations,
  createPortfolioGroup,
  fetchHoldings,
  fetchPortfolioGroupItems,
  fetchPortfolioGroups,
  fetchSimulationAccounts,
  removePortfolioGroupItem,
  reorderPortfolioGroups,
} from "@/api/quant";
import { fetchStockBars } from "@/api/stocks";
import type { SimulationPosition, PortfolioGroup, PortfolioItem } from "@/api/quant";
import type { DailyBar } from "@/features/portfolio/HoldingCard";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { Button } from "@/components/ui/button";
import { PortfolioSummary } from "@/features/portfolio/PortfolioSummary";
import { GroupNav } from "@/features/portfolio/GroupNav";
import { HoldingCard } from "@/features/portfolio/HoldingCard";
import { SimulationSummary } from "@/features/portfolio/SimulationSummary";
import { AddToGroupDialog } from "@/features/portfolio/AddToGroupDialog";
import { BatchGroupActions } from "@/features/portfolio/BatchGroupActions";

export function PortfolioPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [addToGroupDialogOpen, setAddToGroupDialogOpen] = useState(false);
  const [addToGroupSymbol, setAddToGroupSymbol] = useState("");
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set());
  const [batchMode, setBatchMode] = useState<"add" | "remove">("add");

  const groupsQuery = useQuery({
    queryKey: ["portfolioGroups"],
    queryFn: fetchPortfolioGroups,
    staleTime: 30_000,
  });

  const groups = groupsQuery.data?.items ?? [];
  const activeGroup = useMemo(() => {
    if (selectedGroupId) return groups.find((g) => g.id === selectedGroupId) ?? null;
    return groups[0] ?? null;
  }, [groups, selectedGroupId]);

  const groupItemsQuery = useQuery({
    queryKey: ["portfolioGroupItems", activeGroup?.id],
    queryFn: () => fetchPortfolioGroupItems(activeGroup!.id),
    enabled: Boolean(activeGroup?.id),
    staleTime: 20_000,
  });

  const accountsQuery = useQuery({
    queryKey: ["simulationAccounts"],
    queryFn: fetchSimulationAccounts,
    staleTime: 20_000,
  });

  const holdingsQuery = useQuery({
    queryKey: ["portfolioHoldings"],
    queryFn: fetchHoldings,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const items = groupItemsQuery.data?.items ?? [];
  const positions = holdingsQuery.data?.items ?? [];

  const positionsBySymbol = useMemo(() => {
    const map = new Map<string, SimulationPosition>();
    for (const pos of positions) {
      map.set(pos.vt_symbol, pos);
    }
    return map;
  }, [positions]);

  const groupItemCounts = useMemo(() => {
    const counts: Record<number, number> = {};
    if (activeGroup?.id != null && groupItemsQuery.data?.items) {
      counts[activeGroup.id] = groupItemsQuery.data.items.length;
    }
    return counts;
  }, [activeGroup?.id, groupItemsQuery.data?.items]);

  const createGroupMutation = useMutation({
    mutationFn: (name: string) =>
      createPortfolioGroup({
        name,
        group_type: "manual",
        description: "用户手动维护的持仓分组",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
    },
  });

  const addItemMutation = useMutation({
    mutationFn: ({ groupId, symbol, reason }: { groupId: number; symbol: string; reason: string }) =>
      addPortfolioGroupItem(groupId, {
        vt_symbol: symbol,
        source: "manual",
        reason: reason || "用户手动加入",
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems", activeGroup?.id] });
    },
  });

  const autoBuyMutation = useMutation({
    mutationFn: () =>
      autoBuyRecommendations({
        account_id: accountsQuery.data?.items[0]?.id,
        limit: 5,
        amount_per_order: 100_000,
        initial_cash: 1_000_000,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
    },
  });

  const reorderMutation = useMutation({
    mutationFn: (groupIds: number[]) => reorderPortfolioGroups(groupIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroups"] });
    },
  });

  const batchRemoveMutation = useMutation({
    mutationFn: async ({ groupId, symbols }: { groupId: number; symbols: string[] }) => {
      const results = await Promise.all(
        symbols.map((s) => removePortfolioGroupItem(groupId, s)),
      );
      return results;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems", activeGroup?.id] });
      setSelectedSymbols(new Set());
      setIsSelecting(false);
    },
  });

  const batchAddMutation = useMutation({
    mutationFn: async ({ groupId, symbols, reason }: { groupId: number; symbols: string[]; reason: string }) => {
      const results = await Promise.all(
        symbols.map((s) =>
          addPortfolioGroupItem(groupId, { vt_symbol: s, source: "batch", reason }),
        ),
      );
      return results;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      setAddToGroupDialogOpen(false);
      setSelectedSymbols(new Set());
      setIsSelecting(false);
    },
  });

  const toggleSymbol = (vtSymbol: string) => {
    setSelectedSymbols((prev) => {
      const next = new Set(prev);
      if (next.has(vtSymbol)) next.delete(vtSymbol);
      else next.add(vtSymbol);
      return next;
    });
  };

  const selectAll = () => {
    setSelectedSymbols(new Set(items.map((i) => i.vt_symbol)));
  };

  const clearSelection = () => {
    setSelectedSymbols(new Set());
    setIsSelecting(false);
  };

  const handleBatchAdd = () => {
    setBatchMode("add");
    setAddToGroupDialogOpen(true);
  };

  const handleBatchRemove = () => {
    if (!activeGroup) return;
    batchRemoveMutation.mutate({ groupId: activeGroup.id, symbols: [...selectedSymbols] });
  };

  const handleAddToGroup = (vtSymbol: string) => {
    setAddToGroupSymbol(vtSymbol);
    setBatchMode("add");
    setAddToGroupDialogOpen(true);
  };

  const handleViewDetail = (vtSymbol: string) => {
    navigate(`/stocks/${encodeURIComponent(vtSymbol)}`);
  };

  if (groupsQuery.isLoading) return <LoadingState rows={6} />;
  if (groupsQuery.isError) {
    return (
      <ErrorState
        message={groupsQuery.error instanceof Error ? groupsQuery.error.message : "加载持仓分组失败"}
        onRetry={() => groupsQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">持仓中心</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            分组管理自选、量化候选和模拟持仓。量化筛选的结果会自动同步到对应分组。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link to="/quant">回到量化</Link>
          </Button>
          <Button onClick={() => autoBuyMutation.mutate()} disabled={autoBuyMutation.isPending}>
            {autoBuyMutation.isPending ? <RefreshCw size={16} className="animate-spin" /> : <Briefcase size={16} />}
            量化候选模拟建仓
          </Button>
        </div>
      </div>

      <PortfolioSummary
        cash={accountsQuery.data?.items[0]?.cash}
        initialCash={accountsQuery.data?.items[0]?.initial_cash}
        positions={positions}
        accountCount={accountsQuery.data?.items.length ?? 0}
        groupCount={groups.length}
      />

      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <GroupNav
          groups={groups}
          activeId={activeGroup?.id ?? null}
          onSelect={setSelectedGroupId}
          itemCounts={groupItemCounts}
          onCreateGroup={(name) => createGroupMutation.mutate(name)}
          isCreating={createGroupMutation.isPending}
          onReorder={(groupIds) => reorderMutation.mutate(groupIds)}
        />

        <GroupContentPanel
          group={activeGroup}
          items={items}
          positionsBySymbol={positionsBySymbol}
          isLoading={groupItemsQuery.isLoading}
          isError={groupItemsQuery.isError}
          onRetry={() => groupItemsQuery.refetch()}
          onAddToGroup={handleAddToGroup}
          onViewDetail={handleViewDetail}
          onRefreshBars={() => {
            queryClient.invalidateQueries({ queryKey: ["stockDailyBarsForCard"] });
          }}
          isSelecting={isSelecting}
          selectedSymbols={selectedSymbols}
          onToggleSelect={toggleSymbol}
          onSelectAll={selectAll}
          onClearSelection={clearSelection}
          onToggleSelecting={() => setIsSelecting((v) => !v)}
          onBatchAdd={handleBatchAdd}
          onBatchRemove={handleBatchRemove}
          isBatchOperating={batchRemoveMutation.isPending || batchAddMutation.isPending}
        />
      </div>

      <SimulationSummary
        items={positions}
        isLoading={holdingsQuery.isLoading || accountsQuery.isLoading}
        isError={holdingsQuery.isError || accountsQuery.isError}
        onRetry={() => {
          holdingsQuery.refetch();
          accountsQuery.refetch();
        }}
      />

      <AddToGroupDialog
        open={addToGroupDialogOpen}
        onOpenChange={setAddToGroupDialogOpen}
        defaultSymbol={batchMode === "add" && selectedSymbols.size === 1 ? [...selectedSymbols][0] : addToGroupSymbol}
        groups={groups}
        onAdd={(groupId, symbol, reason) => {
          if (batchMode === "add" && selectedSymbols.size > 0) {
            batchAddMutation.mutate({ groupId, symbols: [...selectedSymbols], reason });
          } else {
            addItemMutation.mutate({ groupId, symbol, reason });
          }
          setAddToGroupDialogOpen(false);
        }}
        isAdding={addItemMutation.isPending || batchAddMutation.isPending}
      />
    </div>
  );
}

function GroupContentPanel({
  group,
  items,
  positionsBySymbol,
  isLoading,
  isError,
  onRetry,
  onAddToGroup,
  onViewDetail,
  onRefreshBars,
  isSelecting,
  selectedSymbols,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onToggleSelecting,
  onBatchAdd,
  onBatchRemove,
  isBatchOperating,
}: {
  group: PortfolioGroup | null;
  items: PortfolioItem[];
  positionsBySymbol: Map<string, SimulationPosition>;
  isLoading: boolean;
  isError: boolean;
  onRetry: () => void;
  onAddToGroup: (vtSymbol: string) => void;
  onViewDetail: (vtSymbol: string) => void;
  onRefreshBars: () => void;
  isSelecting: boolean;
  selectedSymbols: Set<string>;
  onToggleSelect: (vtSymbol: string) => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onToggleSelecting: () => void;
  onBatchAdd: () => void;
  onBatchRemove: () => void;
  isBatchOperating: boolean;
}) {
  if (!group) return <EmptyState message="暂无持仓分组" description="先在左侧创建一个分组。" />;
  if (isLoading) return <LoadingState rows={4} />;
  if (isError) return <ErrorState message="加载分组股票失败" onRetry={onRetry} />;

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold">{group.name}</h2>
          <div className="mt-0.5 text-xs text-muted-foreground">
            {items.length} 只 · {group.auto_managed ? "策略自动维护，可手动补充" : "用户手动维护"}
            {group.description && ` · ${group.description}`}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <BatchGroupActions
            selectedCount={selectedSymbols.size}
            totalCount={items.length}
            isSelecting={isSelecting}
            onToggleSelect={onToggleSelecting}
            onSelectAll={onSelectAll}
            onClearSelection={onClearSelection}
            onBatchAdd={onBatchAdd}
            onBatchRemove={onBatchRemove}
            isOperating={isBatchOperating}
          />
          <Button size="sm" variant="outline" onClick={onRefreshBars}>
            <RefreshCw size={14} />
            刷新行情
          </Button>
        </div>
      </div>

      {items.length === 0 ? (
        <EmptyState
          message="分组为空"
          description="可以手动加入股票，也可以由量化筛选自动同步候选。"
        />
      ) : (
        <div className="grid gap-3 lg:grid-cols-2">
          {items.map((item) => (
            <HoldingCardWithBars
              key={`${item.group_id}-${item.vt_symbol}`}
              item={item}
              position={positionsBySymbol.get(item.vt_symbol)}
              onAddToGroup={onAddToGroup}
              onViewDetail={onViewDetail}
              isSelecting={isSelecting}
              isSelected={selectedSymbols.has(item.vt_symbol)}
              onToggleSelect={onToggleSelect}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function HoldingCardWithBars({
  item,
  position,
  onAddToGroup,
  onViewDetail,
  isSelecting,
  isSelected,
  onToggleSelect,
}: {
  item: PortfolioItem;
  position?: SimulationPosition;
  onAddToGroup: (vtSymbol: string) => void;
  onViewDetail: (vtSymbol: string) => void;
  isSelecting?: boolean;
  isSelected?: boolean;
  onToggleSelect?: (vtSymbol: string) => void;
}) {
  const barsQuery = useQuery({
    queryKey: ["stockDailyBarsForCard", item.vt_symbol],
    queryFn: () => fetchStockBars(item.vt_symbol, "1d", 30),
    staleTime: 60_000,
    select: (data): DailyBar[] =>
      (data.items ?? []).map((bar) => ({
        time: bar.trade_date,
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
  });

  return (
    <HoldingCard
      item={item}
      position={position}
      dailyBars={barsQuery.data}
      onAddToGroup={onAddToGroup}
      onViewDetail={onViewDetail}
      isSelecting={isSelecting}
      isSelected={isSelected}
      onToggleSelect={onToggleSelect}
    />
  );
}
