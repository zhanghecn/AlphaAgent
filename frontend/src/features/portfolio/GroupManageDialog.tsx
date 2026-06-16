import { useState } from "react";
import { Plus, Pencil, Settings2 } from "lucide-react";
import { Modal, ModalBody, ModalFooter, ModalHeader } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { GroupEditDialog } from "./GroupEditDialog";
import { groupTypeToState, getStateMeta } from "@/lib/portfolio-states";
import type { PortfolioGroup } from "@/api/quant";

interface GroupManageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: PortfolioGroup[];
  itemCounts: Record<number, number>;
  onCreate: (name: string) => void;
  onUpdate: (groupId: number, payload: {
    name?: string;
    description?: string | null;
    risk_profile?: string;
  }) => void;
  onDelete: (groupId: number) => void;
  isCreating: boolean;
  isUpdating: boolean;
  isDeleting: boolean;
}

/**
 * GroupManageDialog — the single place to manage backend groups.
 *
 * Lists every group (proving they are live backend data, not hardcoded), with
 * the lifecycle tab each belongs to and its stock count. New group via the
 * bottom input; edit/rename/delete via GroupEditDialog. This restores the
 * create/edit/delete capability that was lost when the old left sidebar was
 * removed — but as a focused modal instead of a always-on sidebar.
 */
export function GroupManageDialog({
  open,
  onOpenChange,
  groups,
  itemCounts,
  onCreate,
  onUpdate,
  onDelete,
  isCreating,
  isUpdating,
  isDeleting,
}: GroupManageDialogProps) {
  const [newName, setNewName] = useState("");
  const [editing, setEditing] = useState<PortfolioGroup | null>(null);

  const handleCreate = () => {
    const trimmed = newName.trim();
    if (!trimmed) return;
    onCreate(trimmed);
    setNewName("");
  };

  return (
    <>
      <Modal open={open && editing === null} onOpenChange={onOpenChange} className="max-w-lg">
        <ModalHeader
          title={
            <span className="flex items-center gap-2">
              <Settings2 size={16} /> 分组管理
            </span>
          }
          onClose={() => onOpenChange(false)}
        />
        <ModalBody className="space-y-3">
          <p className="text-xs text-muted-foreground">
            共 {groups.length} 个分组（后台数据）。每个分组按类型归到顶部某个 tab。
          </p>
          <div className="max-h-96 space-y-1 overflow-y-auto">
            {groups.map((group) => {
              const state = groupTypeToState(group.group_type);
              const meta = getStateMeta(state);
              const count = itemCounts[group.id] ?? 0;
              return (
                <div
                  key={group.id}
                  className="flex items-center gap-2 rounded-md border p-2 text-sm"
                >
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{group.name}</span>
                      {group.auto_managed && (
                        <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
                          自动
                        </Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground">
                      <span className="rounded bg-muted px-1 py-0.5">{meta.label}</span>
                      <span className="ml-2 tabular-nums">{count} 只</span>
                      {group.group_type !== meta.key && (
                        <span className="ml-2">· {group.group_type}</span>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="shrink-0 rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-primary"
                    title="编辑 / 删除"
                    onClick={() => setEditing(group)}
                  >
                    <Pencil size={14} />
                  </button>
                </div>
              );
            })}
            {groups.length === 0 && (
              <p className="py-6 text-center text-sm text-muted-foreground">暂无分组</p>
            )}
          </div>

          <div className="flex gap-2 border-t pt-3">
            <input
              type="text"
              className="flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm outline-none focus:ring-2 focus:ring-primary/50"
              placeholder="新分组名称"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") handleCreate();
              }}
              disabled={isCreating}
            />
            <Button size="sm" onClick={handleCreate} disabled={!newName.trim() || isCreating}>
              <Plus size={14} className="mr-1" /> 新建
            </Button>
          </div>
        </ModalBody>
        <ModalFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </ModalFooter>
      </Modal>

      <GroupEditDialog
        open={editing !== null}
        onOpenChange={(next) => !next && setEditing(null)}
        group={editing}
        onUpdate={onUpdate}
        onDelete={onDelete}
        isUpdating={isUpdating}
        isDeleting={isDeleting}
      />
    </>
  );
}
