import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, formatPrice, priceColorClass } from "@/lib/utils";
import type { PortfolioItem, SimulationPosition } from "@/api/quant";

/** Inline advice labels/colors so this list stays self-contained. */
const ADVICE_LABEL: Record<string, string> = {
  hold: "建议持有",
  stop_loss: "触发止损",
  trailing_stop: "跟踪止损",
  take_profit: "触发止盈",
  time_stop: "持仓超时",
};

function adviceClass(advice?: string): string {
  if (advice === "stop_loss" || advice === "trailing_stop")
    return "border-red-200 bg-red-50 text-fall dark:border-red-500/30 dark:bg-red-500/10";
  if (advice === "take_profit")
    return "border-green-200 bg-green-50 text-green-700 dark:border-green-500/30 dark:bg-green-500/10 dark:text-green-300";
  if (advice === "time_stop")
    return "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300";
  return "border-border bg-muted/40 text-muted-foreground";
}

/**
 * PortfolioList — the stocks of the currently selected group.
 *
 * One row per group-item (a stock in this group). Each row has exactly two
 * actions: 加入 (add to a group) and 删掉 (remove from this group). Held rows
 * also surface the realtime advice + P&L. No 建仓/加仓/卖出 simulation verbs.
 */
export function PortfolioList({
  items,
  positionsBySymbol,
  onAddToGroup,
  onRemove,
  onViewDetail,
  removingSymbol,
}: {
  items: PortfolioItem[];
  positionsBySymbol: Map<string, SimulationPosition>;
  onAddToGroup: (vtSymbol: string, name?: string | null) => void;
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
        const position = positionsBySymbol.get(item.vt_symbol);
        const removing = removingSymbol === item.vt_symbol;
        return (
          <Card key={`${item.group_id}-${item.vt_symbol}`} className="flex items-center gap-3 p-3">
            <button
              type="button"
              className="min-w-0 flex-1 text-left"
              onClick={onViewDetail ? () => onViewDetail(item.vt_symbol) : undefined}
            >
              <div className="flex flex-wrap items-center gap-2">
                <StockIdentityLink
                  name={item.name}
                  vtSymbol={item.vt_symbol}
                  board={item.board}
                  boardLabel={item.board_label}
                />
                {position?.advice && (
                  <Badge variant="outline" className={cn("px-2 py-0.5 text-xs", adviceClass(position.advice))}>
                    {ADVICE_LABEL[position.advice] ?? position.advice}
                  </Badge>
                )}
              </div>
              {position ? (
                <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                  <span>
                    现价 <span className="text-foreground tabular-nums">{formatPrice(position.last_price)}</span>
                  </span>
                  <span>
                    成本 <span className="text-foreground tabular-nums">{formatPrice(position.cost_price)}</span>
                  </span>
                  <span className={priceColorClass(position.floating_pnl_pct ?? undefined)}>
                    {formatPct(position.floating_pnl_pct)} · {position.volume.toLocaleString()} 股
                  </span>
                </div>
              ) : (
                item.reason && <div className="mt-0.5 truncate text-xs text-muted-foreground">{item.reason}</div>
              )}
            </button>

            <Button size="sm" variant="outline" onClick={() => onAddToGroup(item.vt_symbol, item.name)}>
              <Plus size={13} className="mr-1" /> 加入
            </Button>
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
