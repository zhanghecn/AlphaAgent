import { useEffect, useState } from "react";
import { Plus, X, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface AddToGroupDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  defaultSymbol?: string;
  groups: Array<{
    id: number;
    name: string;
    group_type: string;
    auto_managed: boolean;
    description?: string | null;
  }>;
  onAdd: (groupId: number, symbol: string, reason: string) => void;
  isAdding: boolean;
}

export function AddToGroupDialog({
  open,
  onOpenChange,
  defaultSymbol,
  groups,
  onAdd,
  isAdding,
}: AddToGroupDialogProps) {
  const [symbol, setSymbol] = useState(defaultSymbol ?? "");
  const [reason, setReason] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);

  useEffect(() => {
    if (open) {
      setSymbol(defaultSymbol ?? "");
      setReason("");
      setSelectedGroupId(null);
    }
  }, [open, defaultSymbol]);

  const handleClose = () => {
    onOpenChange(false);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      handleClose();
    }
  };

  const normalizedSymbol = symbol.trim().toUpperCase();
  const canConfirm = normalizedSymbol.length > 0 && selectedGroupId !== null;

  const handleConfirm = () => {
    if (!canConfirm) return;
    onAdd(selectedGroupId, normalizedSymbol, reason.trim());
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={handleClose}
      onKeyDown={handleKeyDown}
    >
      <div
        className="w-full max-w-md rounded-lg border bg-background shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-lg font-semibold">加入分组</h2>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-4 px-4 py-4">
          <div>
            <label className="mb-1 block text-sm font-medium">股票代码</label>
            <input
              type="text"
              className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
              placeholder="例如 600519"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            />
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium">备注原因</label>
            <input
              type="text"
              className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
              placeholder="选入理由（可选）"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>

          <div>
            <label className="mb-2 block text-sm font-medium">选择分组</label>
            {groups.length === 0 ? (
              <p className="text-sm text-muted-foreground">暂无可用分组</p>
            ) : (
              <div className="max-h-52 space-y-2 overflow-y-auto">
                {groups.map((group) => (
                  <button
                    key={group.id}
                    className={cn(
                      "w-full rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted/50",
                      selectedGroupId === group.id &&
                        "border-primary bg-primary/5",
                    )}
                    onClick={() => setSelectedGroupId(group.id)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{group.name}</span>
                      {group.auto_managed && (
                        <span className="rounded bg-primary/10 px-1.5 py-0.5 text-xs text-primary">
                          自动
                        </span>
                      )}
                    </div>
                    {group.description && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        {group.description}
                      </p>
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t px-4 py-3">
          <Button variant="outline" onClick={handleClose}>
            取消
          </Button>
          <Button disabled={!canConfirm || isAdding} onClick={handleConfirm}>
            {isAdding ? (
              <>
                <RefreshCw className="mr-1 h-4 w-4 animate-spin" />
                添加中
              </>
            ) : (
              <>
                <Plus className="mr-1 h-4 w-4" />
                确认加入
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
