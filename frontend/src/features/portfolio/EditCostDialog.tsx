import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Modal, ModalHeader, ModalBody, ModalFooter } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { updatePositionCost } from "@/api/quant";

/**
 * 修改持仓成本价对话框。
 *
 * 用户手动校正建仓成本（如实际买入价与系统记录不符）。保存后刷新持仓收益率。
 */
export function EditCostDialog({
  open,
  onOpenChange,
  accountId,
  vtSymbol,
  defaultCost,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  accountId?: number;
  vtSymbol: string;
  defaultCost?: number;
}) {
  const queryClient = useQueryClient();
  const [costText, setCostText] = useState("");

  useEffect(() => {
    if (open) setCostText(defaultCost ? String(defaultCost) : "");
  }, [open, defaultCost]);

  const mutation = useMutation({
    mutationFn: () => updatePositionCost(accountId ?? 0, vtSymbol, Number(costText)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolioHoldings"] });
      queryClient.invalidateQueries({ queryKey: ["simulationAccounts"] });
      onOpenChange(false);
    },
  });

  const cost = Number(costText);
  const canSave = accountId != null && cost > 0;

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <ModalHeader title={`修改成本价 · ${vtSymbol}`} onClose={() => onOpenChange(false)} />
      <ModalBody>
        <div className="space-y-2 text-sm">
          <label className="text-muted-foreground">新成本价（按实际买入价校正，保存后刷新收益率）</label>
          <input
            type="number"
            step="0.01"
            min="0"
            className="h-9 w-full rounded-md border bg-background px-3"
            value={costText}
            onChange={(event) => setCostText(event.target.value)}
          />
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)}>取消</Button>
        <Button disabled={!canSave || mutation.isPending} onClick={() => mutation.mutate()}>
          {mutation.isPending ? "保存中..." : "保存"}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
