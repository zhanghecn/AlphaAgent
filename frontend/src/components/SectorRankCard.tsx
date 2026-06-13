/**
 * SectorRankCard — 板块排名卡片
 *
 * Renders a single ranking row for a concept/industry sector.
 * Shows: rank number, name, change_pct, fund flow, stock count, leader.
 */
import { cn, formatPct, formatAmount } from "@/lib/utils";
import type { SectorRankingItem } from "@/types/research";

export interface SectorRankCardProps {
  item: SectorRankingItem;
  rank: number;
  selected?: boolean;
  compact?: boolean;
  onClick?: () => void;
}

function RankBadge({ rank }: { rank: number }) {
  const cls =
    rank === 1 ? "rank-badge rank-badge-top1" :
    rank === 2 ? "rank-badge rank-badge-top2" :
    rank === 3 ? "rank-badge rank-badge-top3" :
    "rank-badge rank-badge-default";

  return <span className={cls}>{rank}</span>;
}

export function SectorRankCard({
  item,
  rank,
  selected = false,
  compact = false,
  onClick,
}: SectorRankCardProps) {
  const changePct = item.change_pct;
  const isRise = changePct != null && changePct > 0;

  return (
    <button
      type="button"
      className={cn(
        "w-full rounded-lg border p-3 text-left transition-colors",
        selected
          ? "border-primary bg-primary/5"
          : "border-border hover:bg-muted/50",
        compact && "p-2"
      )}
      onClick={onClick}
    >
      {/* Main row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <RankBadge rank={rank} />
          <span className={cn("font-medium truncate text-sm")}>
            {item.name}
          </span>
          {item.type === "industry" && (
            <span className="rounded bg-blue-100 px-1 py-0.5 text-[10px] text-blue-600 dark:bg-blue-500/15 dark:text-blue-300">行业</span>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {/* Change percent */}
          <span
            className={cn(
              "font-semibold tabular-nums",
              compact ? "text-xs" : "text-sm",
              isRise ? "text-rise" : changePct != null ? "text-fall" : "text-muted-foreground"
            )}
          >
            {formatPct(changePct)}
          </span>
        </div>
      </div>

      {/* Secondary info row (hidden in compact mode) */}
      {!compact && (
        <div className="mt-1.5 flex items-center gap-3 text-xs text-muted-foreground">
          {item.stock_count != null && (
            <span>{item.stock_count}只</span>
          )}
          {item.rise_count != null && item.fall_count != null && (
            <span>
              <span className="text-rise">{item.rise_count}</span>
              <span>/</span>
              <span className="text-fall">{item.fall_count}</span>
            </span>
          )}
          {item.main_net_inflow != null && (
            <span className={item.main_net_inflow >= 0 ? "fund-inflow" : "fund-outflow"}>
              {(item.main_net_inflow >= 0 ? "+" : "") + formatAmount(item.main_net_inflow)}
            </span>
          )}
          {item.leader_stock && (
            <span className="truncate">龙头: {item.leader_stock}</span>
          )}
        </div>
      )}
    </button>
  );
}
