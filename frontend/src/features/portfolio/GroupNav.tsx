import { useState } from "react";
import { FolderPlus, GripVertical } from "lucide-react";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";

interface GroupNavProps {
  groups: Array<{
    id: number;
    name: string;
    group_type: string;
    description?: string | null;
    auto_managed: boolean;
    risk_profile?: string;
  }>;
  activeId: number | null;
  onSelect: (id: number) => void;
  itemCounts: Record<number, number>;
  onCreateGroup: (name: string) => void;
  isCreating: boolean;
  onReorder?: (groupIds: number[]) => void;
}

export function GroupNav({
  groups,
  activeId,
  onSelect,
  itemCounts,
  onCreateGroup,
  isCreating,
  onReorder,
}: GroupNavProps) {
  const [newGroupName, setNewGroupName] = useState("");

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const handleCreate = () => {
    const trimmed = newGroupName.trim();
    if (!trimmed) return;
    onCreateGroup(trimmed);
    setNewGroupName("");
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (!over || active.id === over.id || !onReorder) return;

    const oldIndex = groups.findIndex((g) => g.id === active.id);
    const newIndex = groups.findIndex((g) => g.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = [...groups];
    const [moved] = reordered.splice(oldIndex, 1);
    reordered.splice(newIndex, 0, moved);
    onReorder(reordered.map((g) => g.id));
  };

  return (
    <section className="space-y-4">
      {/* Group list with drag-and-drop */}
      <section className="rounded-lg border">
        <div className="border-b px-4 py-3 text-sm font-semibold">
          持仓分组
        </div>
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
        >
          <SortableContext
            items={groups.map((g) => g.id)}
            strategy={verticalListSortingStrategy}
          >
            <div className="divide-y">
              {groups.map((group) => (
                <SortableGroupItem
                  key={group.id}
                  group={group}
                  isActive={activeId === group.id}
                  itemCount={itemCounts[group.id] ?? 0}
                  onSelect={onSelect}
                  isDraggable={Boolean(onReorder)}
                />
              ))}
            </div>
          </SortableContext>
        </DndContext>
      </section>

      {/* Create form */}
      <section className="rounded-lg border p-4 text-sm">
        <div className="font-medium">新建分组</div>
        <div className="mt-3 flex gap-2">
          <input
            className="flex-1 rounded-md border bg-transparent px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring"
            placeholder="分组名称"
            value={newGroupName}
            onChange={(e) => setNewGroupName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleCreate();
            }}
            disabled={isCreating}
          />
          <Button
            size="sm"
            onClick={handleCreate}
            disabled={isCreating || !newGroupName.trim()}
          >
            <FolderPlus className="mr-1 h-4 w-4" />
            新建
          </Button>
        </div>
      </section>
    </section>
  );
}

// ── Sortable group item ────────────────────────────────────────────────────

function SortableGroupItem({
  group,
  isActive,
  itemCount,
  onSelect,
  isDraggable,
}: {
  group: {
    id: number;
    name: string;
    group_type: string;
  };
  isActive: boolean;
  itemCount: number;
  onSelect: (id: number) => void;
  isDraggable: boolean;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: group.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "flex items-center gap-1 px-4 py-3 text-sm hover:bg-muted/50",
        isActive && "bg-muted",
      )}
    >
      {isDraggable && (
        <button
          type="button"
          className="cursor-grab text-muted-foreground hover:text-foreground active:cursor-grabbing"
          {...attributes}
          {...listeners}
        >
          <GripVertical size={14} />
        </button>
      )}
      <button
        type="button"
        className="flex-1 text-left"
        onClick={() => onSelect(group.id)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-medium">{group.name}</span>
            {group.group_type === "quant_candidate" && (
              <span className="rounded-md border px-1.5 py-0.5 text-xs text-muted-foreground">
                自动
              </span>
            )}
            {group.group_type !== "quant_candidate" &&
              group.group_type !== "manual" && (
                <span className="text-xs text-muted-foreground">
                  {group.group_type}
                </span>
              )}
          </div>
          <span className="text-muted-foreground">
            {itemCount}
          </span>
        </div>
      </button>
    </div>
  );
}
