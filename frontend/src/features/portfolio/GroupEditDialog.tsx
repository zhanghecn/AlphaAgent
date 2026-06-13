import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { Modal, ModalBody, ModalFooter, ModalHeader } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import type { PortfolioGroup } from "@/api/quant";

interface GroupEditDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  group: PortfolioGroup | null;
  onUpdate: (groupId: number, payload: {
    name?: string;
    description?: string | null;
    risk_profile?: string;
  }) => void;
  onDelete: (groupId: number) => void;
  isUpdating: boolean;
  isDeleting: boolean;
}

/**
 * GroupEditDialog — edit a group's name / description / risk profile, or
 * delete it. Wired to the already-existing PATCH/DELETE /portfolio/groups
 * endpoints that the old UI never surfaced.
 */
export function GroupEditDialog({
  open,
  onOpenChange,
  group,
  onUpdate,
  onDelete,
  isUpdating,
  isDeleting,
}: GroupEditDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [riskProfile, setRiskProfile] = useState("balanced");
  const [confirmDelete, setConfirmDelete] = useState(false);

  useEffect(() => {
    if (open && group) {
      setName(group.name);
      setDescription(group.description ?? "");
      setRiskProfile(group.risk_profile ?? "balanced");
      setConfirmDelete(false);
    }
  }, [open, group]);

  if (!group) return null;

  const handleSave = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    onUpdate(group.id, { name: trimmed, description: description.trim() || null, risk_profile: riskProfile });
  };

  return (
    <Modal open={open} onOpenChange={onOpenChange} className="max-w-md">
      <ModalHeader title="编辑分组" onClose={() => onOpenChange(false)} />
      <ModalBody className="space-y-4">
        <div className="space-y-1">
          <label className="block text-sm font-medium">分组名称</label>
          <input
            type="text"
            className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </div>
        <div className="space-y-1">
          <label className="block text-sm font-medium">描述</label>
          <input
            type="text"
            className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="可选"
          />
        </div>
        <div className="space-y-1">
          <label className="block text-sm font-medium">风险偏好</label>
          <select
            className="w-full rounded-md border bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50"
            value={riskProfile}
            onChange={(event) => setRiskProfile(event.target.value)}
          >
            <option value="conservative">保守</option>
            <option value="balanced">均衡</option>
            <option value="aggressive">激进</option>
          </select>
        </div>

        {group.auto_managed && (
          <p className="text-xs text-muted-foreground">
            此分组由策略自动维护，编辑名称/描述不影响自动同步行为。
          </p>
        )}

        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2">
          {!confirmDelete ? (
            <button
              type="button"
              className="flex items-center gap-1 text-xs text-destructive hover:underline"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 size={12} />
              删除此分组
            </button>
          ) : (
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-destructive">确认删除？该分组下的股票关联会被移除。</span>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(false)} disabled={isDeleting}>
                  取消
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => onDelete(group.id)}
                  disabled={isDeleting}
                >
                  删除
                </Button>
              </div>
            </div>
          )}
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isUpdating}>
          关闭
        </Button>
        <Button variant="brand" onClick={handleSave} disabled={isUpdating || !name.trim()}>
          {isUpdating ? "保存中…" : "保存"}
        </Button>
      </ModalFooter>
    </Modal>
  );
}
