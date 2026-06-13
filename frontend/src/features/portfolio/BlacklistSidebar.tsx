import { useState } from "react";
import { Ban, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { SectionCard } from "@/components/dashboard/SectionCard";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import type { PortfolioItem } from "@/api/quant";

interface BlacklistSidebarProps {
  items: PortfolioItem[];
  onViewDetail?: (vtSymbol: string) => void;
}

/**
 * Blacklist sidebar — collapsed by default since it's risk-control, not part
 * of the main workflow. Click the header to expand the list.
 */
export function BlacklistSidebar({ items, onViewDetail }: BlacklistSidebarProps) {
  const [open, setOpen] = useState(false);

  return (
    <SectionCard
      title={
        <button
          type="button"
          className="flex items-center gap-2"
          onClick={() => setOpen((value) => !value)}
        >
          <Ban size={16} />
          黑名单
          <span className="rounded-full bg-muted px-1.5 py-0 text-xs tabular-nums text-muted-foreground">
            {items.length}
          </span>
          <ChevronDown
            size={14}
            className={cn("text-muted-foreground transition-transform", open && "rotate-180")}
          />
        </button>
      }
      bodyClassName={open ? "p-2" : "p-0"}
    >
      {open &&
        (items.length === 0 ? (
          <EmptyState message="黑名单为空" />
        ) : (
          <ul className="space-y-0.5">
            {items.map((item) => (
              <li key={`${item.group_id}-${item.vt_symbol}`}>
                <button
                  type="button"
                  className="w-full rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted/60"
                  onClick={() => onViewDetail?.(item.vt_symbol)}
                >
                  <StockIdentityLink
                    name={item.name}
                    vtSymbol={item.vt_symbol}
                    board={item.board}
                    boardLabel={item.board_label}
                  />
                </button>
              </li>
            ))}
          </ul>
        ))}
    </SectionCard>
  );
}
