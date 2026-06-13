import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Briefcase, RefreshCw } from "lucide-react";
import {
  addPortfolioGroupItem,
  removePortfolioGroupItem,
} from "@/api/quant";
import type { PortfolioGroup } from "@/api/quant";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { Button } from "@/components/ui/button";
import { PortfolioKpiBar } from "@/features/portfolio/PortfolioKpiBar";
import { GroupNav } from "@/features/portfolio/GroupNav";
import { WorkflowLanes } from "@/features/portfolio/WorkflowLanes";
import { BlacklistSidebar } from "@/features/portfolio/BlacklistSidebar";
import { AddToGroupDialog } from "@/features/portfolio/AddToGroupDialog";
import { BatchGroupActions } from "@/features/portfolio/BatchGroupActions";
import { TradeDialog, type TradeOrderPayload } from "@/features/portfolio/TradeDialog";
import { BuildPreviewDialog } from "@/features/portfolio/BuildPreviewDialog";
import { GroupEditDialog } from "@/features/portfolio/GroupEditDialog";
import { useDailyBarsForCards } from "@/features/portfolio/hooks/useDailyBarsForCards";
import { useToast } from "@/components/ui/toast";
import {
  useBatchSelection,
  useHoldings,
  usePortfolioGroups,
  usePortfolioState,
  useTradeActions,
} from "@/features/portfolio/hooks";

interface TradeDialogState {
  open: boolean;
  mode: "sell" | "add";
  symbol: string;
}

/**
 * Portfolio center — workflow-lane layout with actionable holdings.
 *
 * Four lifecycle lanes (watch / candidate / holding / review) + blacklist
 * sidebar, driven by extracted hooks. Holding cards support manual
 * sell / add-position (via placeOrder), the build button opens a configurable
 * preview with result feedback, and group editing/deleting is wired to the
 * already-existing PATCH/DELETE endpoints.
 */
export function PortfolioPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();

  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [addToGroupOpen, setAddToGroupOpen] = useState(false);
  const [addToGroupSymbol, setAddToGroupSymbol] = useState("");
  const [tradeDialog, setTradeDialog] = useState<TradeDialogState>({
    open: false,
    mode: "sell",
    symbol: "",
  });
  const [buildOpen, setBuildOpen] = useState(false);
  const [editGroup, setEditGroup] = useState<PortfolioGroup | null>(null);

  const groups = usePortfolioGroups();
  const holdings = useHoldings();
  const portfolioState = usePortfolioState(groups.groups);
  const selection = useBatchSelection();
  const trade = useTradeActions(holdings.accountId);

  // Items that participate in batch group operations (non-holding lanes).
  const batchableItems = useMemo(
    () => [
      ...portfolioState.itemsByState.watch,
      ...portfolioState.itemsByState.candidate,
      ...portfolioState.itemsByState.review,
    ],
    [portfolioState.itemsByState],
  );

  // All symbols needing daily bars (lane items + real positions).
  const allSymbols = useMemo(() => {
    const symbols = new Set<string>();
    batchableItems.forEach((item) => symbols.add(item.vt_symbol));
    holdings.positions.forEach((position) => symbols.add(position.vt_symbol));
    return Array.from(symbols);
  }, [batchableItems, holdings.positions]);

  const barsBySymbol = useDailyBarsForCards(allSymbols);

  const itemCounts = useMemo(() => {
    const counts: Record<number, number> = {};
    for (const [groupId, items] of portfolioState.itemsByGroupId) {
      counts[groupId] = items.length;
    }
    return counts;
  }, [portfolioState.itemsByGroupId]);

  // Batch add selected symbols to a target group.
  const batchAddMutation = useMutation({
    mutationFn: async ({
      groupId,
      symbols,
      reason,
    }: {
      groupId: number;
      symbols: string[];
      reason: string;
    }) => {
      return Promise.allSettled(
        symbols.map((symbol) =>
          addPortfolioGroupItem(groupId, { vt_symbol: symbol, source: "batch", reason }),
        ),
      );
    },
    onSuccess: (results) => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      selection.clear();
      const fulfilled = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.length - fulfilled;
      toast({
        title: fulfilled > 0 ? `已加入 ${fulfilled} 只` : "加入分组失败",
        description: failed > 0 ? `${failed} 只未成功` : undefined,
        variant: fulfilled > 0 ? "success" : "error",
      });
    },
  });

  // Batch remove selected symbols from every group they belong to.
  const batchRemoveMutation = useMutation({
    mutationFn: async (symbols: string[]) => {
      const removals: Promise<unknown>[] = [];
      for (const symbol of symbols) {
        for (const [groupId, items] of portfolioState.itemsByGroupId) {
          if (items.some((item) => item.vt_symbol === symbol)) {
            removals.push(removePortfolioGroupItem(groupId, symbol));
          }
        }
      }
      return Promise.allSettled(removals);
    },
    onSuccess: (results) => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      selection.clear();
      const fulfilled = results.filter((r) => r.status === "fulfilled").length;
      const failed = results.length - fulfilled;
      toast({
        title: fulfilled > 0 ? `已移出 ${fulfilled} 只` : "移出失败",
        description: failed > 0 ? `${failed} 只未成功` : undefined,
        variant: fulfilled > 0 ? "success" : "error",
      });
    },
  });

  if (groups.isLoading) return <LoadingState rows={6} />;
  if (groups.isError) {
    return <ErrorState message="加载持仓分组失败" onRetry={() => groups.refetch()} />;
  }

  const handleAddToGroup = (vtSymbol: string) => {
    setAddToGroupSymbol(vtSymbol);
    setAddToGroupOpen(true);
  };

  const handleViewDetail = (vtSymbol: string) => {
    navigate(`/stocks/${encodeURIComponent(vtSymbol)}`);
  };

  const refreshBars = () => {
    queryClient.invalidateQueries({ queryKey: ["stockDailyBarsForCard"] });
  };

  const openSell = (vtSymbol: string) => {
    trade.resetPlaceOrder();
    setTradeDialog({ open: true, mode: "sell", symbol: vtSymbol });
  };

  const openAddPosition = (vtSymbol: string) => {
    trade.resetPlaceOrder();
    setTradeDialog({ open: true, mode: "add", symbol: vtSymbol });
  };

  const handleTradeConfirm = async (payload: TradeOrderPayload) => {
    try {
      await trade.placeOrderAsync(payload);
      setTradeDialog((prev) => ({ ...prev, open: false }));
      trade.resetPlaceOrder();
    } catch {
      // Failure keeps the dialog open; error shows via placeOrderError and
      // the backend also writes a risk_event visible in RiskEventsPanel.
    }
  };

  const openBuild = () => {
    trade.resetAutoBuy();
    setBuildOpen(true);
  };

  // Build a single candidate into a position (default 100k per order).
  const handleSingleBuild = (vtSymbol: string) => {
    trade.placeOrder({ vt_symbol: vtSymbol, side: "BUY", amount: 100_000 });
  };

  const tradePosition = tradeDialog.open
    ? holdings.positionsBySymbol.get(tradeDialog.symbol) ?? null
    : null;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">持仓中心</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            按投资生命周期管理观察、候选、持仓与复盘。量化筛选结果自动同步到候选池。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link to="/quant">回到量化</Link>
          </Button>
        </div>
      </div>

      {/* KPI bar */}
      <PortfolioKpiBar kpi={holdings.kpi} />

      {/* Main: group sidebar + workflow lanes */}
      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <GroupNav
            groups={groups.groups}
            activeId={selectedGroupId ?? groups.groups[0]?.id ?? null}
            onSelect={setSelectedGroupId}
            itemCounts={itemCounts}
            onCreateGroup={groups.createGroup}
            isCreating={groups.isCreating}
            onReorder={groups.reorderGroups}
            onEdit={setEditGroup}
          />
          <BlacklistSidebar
            items={portfolioState.itemsByState.blacklist}
            onViewDetail={handleViewDetail}
          />
        </aside>

        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <BatchGroupActions
              selectedCount={selection.selectedCount}
              totalCount={batchableItems.length}
              isSelecting={selection.isSelecting}
              onToggleSelect={selection.toggleSelecting}
              onSelectAll={() => selection.selectAll(batchableItems.map((item) => item.vt_symbol))}
              onClearSelection={selection.clear}
              onBatchAdd={() => setAddToGroupOpen(true)}
              onBatchRemove={() =>
                batchRemoveMutation.mutate(Array.from(selection.selectedSymbols))
              }
              isOperating={batchAddMutation.isPending || batchRemoveMutation.isPending}
            />
            <Button size="sm" variant="outline" onClick={refreshBars}>
              <RefreshCw size={14} />
              刷新行情
            </Button>
          </div>

          <WorkflowLanes
            itemsByState={portfolioState.itemsByState}
            groupsByState={portfolioState.groupsByState}
            positions={holdings.positions}
            positionsBySymbol={holdings.positionsBySymbol}
            barsBySymbol={barsBySymbol}
            riskBadgesBySymbol={holdings.riskBadgesBySymbol}
            onAddToGroup={handleAddToGroup}
            onViewDetail={handleViewDetail}
            onSell={openSell}
            onAddPosition={openAddPosition}
            onBuild={handleSingleBuild}
            laneAction={(state) =>
              state === "candidate" ? (
                <Button size="sm" variant="outline" onClick={openBuild}>
                  <Briefcase size={14} />
                  批量建仓
                </Button>
              ) : null
            }
            isSelecting={selection.isSelecting}
            selectedSymbols={selection.selectedSymbols}
            onToggleSelect={selection.toggle}
          />
        </div>
      </div>

      {/* Add-to-group dialog (also used for batch add) */}
      <AddToGroupDialog
        open={addToGroupOpen}
        onOpenChange={setAddToGroupOpen}
        defaultSymbol={
          selection.selectedCount === 1
            ? Array.from(selection.selectedSymbols)[0]
            : addToGroupSymbol
        }
        groups={groups.groups}
        onAdd={(groupId, symbol, reason) => {
          const symbols =
            selection.selectedCount > 0 ? Array.from(selection.selectedSymbols) : [symbol];
          batchAddMutation.mutate({ groupId, symbols, reason });
          setAddToGroupOpen(false);
        }}
        isAdding={batchAddMutation.isPending}
      />

      {/* Sell / add-position dialog */}
      <TradeDialog
        open={tradeDialog.open}
        onOpenChange={(open) => setTradeDialog((prev) => ({ ...prev, open }))}
        mode={tradeDialog.mode}
        position={tradePosition}
        onConfirm={handleTradeConfirm}
        isPlacing={trade.isPlacing}
        error={trade.placeOrderError instanceof Error ? trade.placeOrderError : null}
      />

      {/* Build preview + result feedback */}
      <BuildPreviewDialog
        open={buildOpen}
        onOpenChange={(open) => {
          setBuildOpen(open);
          if (!open) trade.resetAutoBuy();
        }}
        onBuild={(params) =>
          trade.autoBuy({
            limit: params.limit,
            amount_per_order: params.amount_per_order,
            initial_cash: params.initial_cash,
          })
        }
        isBuilding={trade.isAutoBuying}
        result={trade.autoBuyResult}
        error={trade.autoBuyError instanceof Error ? trade.autoBuyError : null}
      />

      {/* Group edit / delete */}
      <GroupEditDialog
        open={editGroup !== null}
        onOpenChange={(open) => {
          if (!open) setEditGroup(null);
        }}
        group={editGroup}
        onUpdate={(groupId, payload) => groups.updateGroup({ groupId, payload })}
        onDelete={(groupId) => {
          groups.deleteGroup(groupId);
          setEditGroup(null);
        }}
        isUpdating={groups.isUpdating}
        isDeleting={groups.isDeleting}
      />
    </div>
  );
}
