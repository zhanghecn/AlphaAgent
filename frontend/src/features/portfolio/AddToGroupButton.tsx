import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { AddToGroupDialog } from "./AddToGroupDialog";
import { usePortfolioGroups } from "./hooks/usePortfolioGroups";
import { addPortfolioGroupItem } from "@/api/quant";

/**
 * AddToGroupButton — self-contained "加入持仓" entry for any stock list.
 *
 * One button → opens AddToGroupDialog (pick a group, optional note) →
 * addPortfolioGroupItem. The caller only passes vtSymbol/name; account,
 * groups list, mutation and cache invalidation are all handled here. This is
 * the single "加入" action the user asked for (no 建仓/加仓/卖出).
 */
export function AddToGroupButton({
  vtSymbol,
  compact = false,
}: {
  vtSymbol: string;
  name?: string | null;
  /** Compact label (加入持仓 -> 加入) for dense table rows. */
  compact?: boolean;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const groups = usePortfolioGroups();
  const [open, setOpen] = useState(false);

  const addMutation = useMutation({
    mutationFn: ({ groupId, symbol, reason }: { groupId: number; symbol: string; reason: string }) =>
      addPortfolioGroupItem(groupId, { vt_symbol: symbol, source: "manual", reason }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioGroupItems"] });
      setOpen(false);
      toast({ title: "已加入分组", variant: "success" });
    },
    onError: (error) => toast({ title: "加入失败", description: error.message, variant: "error" }),
  });

  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setOpen(true)}>
        <Plus size={13} className="mr-1" /> {compact ? "加入" : "加入持仓"}
      </Button>
      <AddToGroupDialog
        open={open}
        onOpenChange={setOpen}
        defaultSymbol={vtSymbol}
        groups={groups.groups}
        onAdd={(groupId, symbol, reason) => addMutation.mutate({ groupId, symbol, reason })}
        isAdding={addMutation.isPending}
      />
    </>
  );
}
