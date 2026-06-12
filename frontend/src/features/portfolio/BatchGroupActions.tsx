import { CheckSquare, Plus, Square, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface BatchGroupActionsProps {
  selectedCount: number;
  totalCount: number;
  isSelecting: boolean;
  onToggleSelect: () => void;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onBatchAdd: () => void;
  onBatchRemove: () => void;
  isOperating: boolean;
}

export function BatchGroupActions({
  selectedCount,
  totalCount,
  isSelecting,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onBatchAdd,
  onBatchRemove,
  isOperating,
}: BatchGroupActionsProps) {
  if (!isSelecting) {
    return (
      <Button size="sm" variant="outline" onClick={onToggleSelect}>
        <CheckSquare size={14} />
        批量操作
      </Button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm text-muted-foreground">
        已选 {selectedCount}/{totalCount}
      </span>
      <Button size="sm" variant="outline" onClick={onSelectAll} disabled={selectedCount === totalCount}>
        <Square size={14} />
        全选
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={onBatchAdd}
        disabled={selectedCount === 0 || isOperating}
      >
        <Plus size={14} />
        批量加入
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={onBatchRemove}
        disabled={selectedCount === 0 || isOperating}
      >
        <Trash2 size={14} />
        批量移出
      </Button>
      <Button size="sm" variant="ghost" onClick={onClearSelection}>
        <X size={14} />
        取消
      </Button>
    </div>
  );
}
