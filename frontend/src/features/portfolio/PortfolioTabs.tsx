import { cn } from "@/lib/utils";

/**
 * PortfolioTabs — one tab per actual backend group (dynamic), not a fixed
 * set of lifecycle buckets.
 *
 * The user's mental model is "my groups" (自选观察 / 量化候选 / 手动持仓 …),
 * each group a stock collection they manage. So tabs ARE the groups — as many
 * tabs as there are non-empty groups, named by the group's own name. Empty
 * groups stay hidden here (visible in the GroupManage dialog) to avoid clutter.
 */
export function PortfolioTabs({
  groups,
  activeGroupId,
  onChange,
}: {
  groups: Array<{ id: number; name: string; count: number }>;
  activeGroupId: number | null;
  onChange: (id: number) => void;
}) {
  if (groups.length === 0) return null;
  return (
    <div className="flex items-center gap-1 overflow-x-auto border-b">
      {groups.map((group) => {
        const active = activeGroupId === group.id;
        return (
          <button
            key={group.id}
            type="button"
            className={cn(
              "relative shrink-0 px-4 py-2.5 text-sm font-medium transition-colors",
              active ? "text-primary" : "text-muted-foreground hover:text-foreground",
            )}
            onClick={() => onChange(group.id)}
          >
            <span>{group.name}</span>
            <span
              className={cn(
                "ml-1.5 rounded px-1.5 py-0.5 text-xs tabular-nums",
                active ? "bg-primary/10 text-primary" : "bg-muted text-muted-foreground",
              )}
            >
              {group.count}
            </span>
            {active && (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary" />
            )}
          </button>
        );
      })}
    </div>
  );
}
