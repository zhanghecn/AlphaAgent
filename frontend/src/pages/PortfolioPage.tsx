import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { PortfolioKpiBar } from "@/features/portfolio/PortfolioKpiBar";
import { PortfolioTabs } from "@/features/portfolio/PortfolioTabs";
import { PortfolioList } from "@/features/portfolio/PortfolioList";
import { GroupManageDialog } from "@/features/portfolio/GroupManageDialog";
import { usePortfolioGroups } from "@/features/portfolio/hooks/usePortfolioGroups";
import { useHoldings } from "@/features/portfolio/hooks/useHoldings";
import { usePortfolioState } from "@/features/portfolio/hooks/usePortfolioState";
import { removePortfolioGroupItem } from "@/api/quant";

/**
 * PortfolioPage — holdings center.
 *
 * Tabs are the actual backend groups (one tab per non-empty group, named by
 * the group's own name) — not a fixed set of lifecycle buckets. Selecting a
 * tab shows that group's stocks. Each row has only 加入 / 删掉. The
 * 「分组管理」button opens a modal to create / edit / delete groups.
 */
export function PortfolioPage() {
  const queryClient = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const groups = usePortfolioGroups();
  const portfolioState = usePortfolioState(groups.groups);
  const holdings = useHoldings();

  const [activeGroupId, setActiveGroupId] = useState<number | null>(null);
  const [manageOpen, setManageOpen] = useState(false);

  const removeMutation = useMutation({
    mutationFn: ({ groupId, symbol }: { groupId: number; symbol: string }) =>
      removePortfolioGroupItem(groupId, symbol),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      toast({ title: "已删除", variant: "success" });
    },
    onError: (error) => toast({ title: "删除失败", description: error.message, variant: "error" }),
  });

  // Per-group item count (for the manage dialog: all groups, including empty).
  const itemCounts = useMemo(() => {
    const c: Record<number, number> = {};
    portfolioState.itemsByGroupId.forEach((list, gid) => {
      c[gid] = list.length;
    });
    return c;
  }, [portfolioState.itemsByGroupId]);

  // Tabs = user-managed groups only. System-generated groups (量化候选 from
  // screening, 自动模拟持仓 from backtest) are excluded — their data lives on
  // the quant/backtest pages. The holdings center stays a generic, user-managed
  // stock collection. Sorted so groups with stocks come first.
  const SYSTEM_GROUP_TYPES = new Set(["quant_candidate", "simulation_auto"]);
  const tabGroups = useMemo(
    () =>
      groups.groups
        .filter((g) => !SYSTEM_GROUP_TYPES.has(g.group_type))
        .map((g) => ({ id: g.id, name: g.name, count: itemCounts[g.id] ?? 0 }))
        .sort((a, b) => b.count - a.count),
    [groups.groups, itemCounts],
  );

  const effectiveGroupId = activeGroupId ?? tabGroups[0]?.id ?? null;
  const items = effectiveGroupId ? portfolioState.itemsOf(effectiveGroupId) : [];
  const removingSymbol = removeMutation.isPending ? removeMutation.variables?.symbol ?? null : null;

  const refresh = () => {
    groups.refetch();
    holdings.refetch();
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">持仓中心</h1>
          <p className="text-xs text-muted-foreground">每个 tab 是一个分组 · 加入 / 删除股票 · 持仓实时评估</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setManageOpen(true)}>
            <Settings2 size={14} className="mr-1" /> 分组管理
          </Button>
          <Button variant="outline" size="sm" onClick={refresh}>
            <RefreshCw size={14} className="mr-1" /> 刷新
          </Button>
        </div>
      </div>

      <PortfolioKpiBar kpi={holdings.kpi} />

      <PortfolioTabs groups={tabGroups} activeGroupId={effectiveGroupId} onChange={setActiveGroupId} />

      {effectiveGroupId ? (
        <PortfolioList
          items={items}
          positionsBySymbol={holdings.positionsBySymbol}
          onRemove={(groupId, vt) => removeMutation.mutate({ groupId, symbol: vt })}
          onViewDetail={(vt) => navigate(`/stocks/${vt}`)}
          removingSymbol={removingSymbol}
        />
      ) : (
        <p className="py-10 text-center text-sm text-muted-foreground">
          暂无分组有股票。点「分组管理」新建分组，或在股票列表点「加入」。
        </p>
      )}

      <GroupManageDialog
        open={manageOpen}
        onOpenChange={setManageOpen}
        groups={groups.groups}
        itemCounts={itemCounts}
        onCreate={groups.createGroup}
        onUpdate={(groupId, payload) => groups.updateGroup({ groupId, payload })}
        onDelete={groups.deleteGroup}
        isCreating={groups.isCreating}
        isUpdating={groups.isUpdating}
        isDeleting={groups.isDeleting}
      />
    </div>
  );
}
