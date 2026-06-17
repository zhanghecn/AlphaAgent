import { Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import type { PortfolioItem } from "@/api/quant";

/**
 * PortfolioList — stocks of the currently selected group.
 *
 * A group is just a classification container; every stock renders the SAME way
 * regardless of which group it's in (no special holding-only advice/P&L).
 * One row = stock identity + join reason + 删掉 (remove from this group).
 */
export function PortfolioList({
  items,
  onRemove,
  onViewDetail,
  removingSymbol,
}: {
  items: PortfolioItem[];
  onRemove: (groupId: number, vtSymbol: string) => void;
  onViewDetail?: (vtSymbol: string) => void;
  removingSymbol?: string | null;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        message="该分组暂无股票"
        description="在股票列表点「加入」把股票加到这里，或切到其他分组查看。"
      />
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => {
        const removing = removingSymbol === item.vt_symbol;
        return (
          <Card key={`${item.group_id}-${item.vt_symbol}`} className="flex items-center gap-3 p-3">
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={onViewDetail ? () => onViewDetail(item.vt_symbol) : undefined}
            >
              <StockIdentityLink
                name={item.name}
                vtSymbol={item.vt_symbol}
                board={item.board}
                boardLabel={item.board_label}
              />
              {item.reason && <div className="mt-0.5 truncate text-xs text-muted-foreground">{item.reason}</div>}
            </button>
            <Button
              size="sm"
              variant="ghost"
              className="text-muted-foreground hover:text-destructive"
              disabled={removing}
              onClick={() => onRemove(item.group_id, item.vt_symbol)}
            >
              <Trash2 size={13} className="mr-1" /> {removing ? "…" : "删掉"}
            </Button>
          </Card>
        );
      })}
    </div>
  );
}
