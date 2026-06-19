import { cn, formatAmount, formatPrice, priceColorClass } from "@/lib/utils";
import type { BacktestTrade } from "@/api/quant";

export interface SignalCardProps {
  trade: BacktestTrade;
  isHighlighted?: boolean;
  /** 新信号：mount 时触发一次扫光高亮（CSS animation 默认只跑一次） */
  isNew?: boolean;
  onClick?: (trade: BacktestTrade) => void;
}

/**
 * A single buy/sell signal card with A-share color convention:
 * - Buy: red left border (红涨)
 * - Sell: green left border (绿跌)
 */
export function SignalCard({ trade, isHighlighted, isNew, onClick }: SignalCardProps) {
  const isBuy = trade.side === "BUY";

  return (
    <button
      type="button"
      className={cn(
        "relative w-full overflow-hidden rounded-lg border border-l-4 p-3 text-left text-sm transition-shadow hover:shadow-md",
        isBuy ? "border-l-red-500" : "border-l-green-500",
        isHighlighted && "ring-2 ring-primary",
      )}
      onClick={onClick ? () => onClick(trade) : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={cn("rounded-md px-1.5 py-0.5 text-xs font-medium", isBuy ? "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300" : "bg-green-50 text-green-700 dark:bg-green-500/15 dark:text-green-300")}>
          {isBuy ? "买入" : "卖出"}
        </span>
        <span className="text-xs text-muted-foreground">{trade.trade_date}</span>
      </div>
      <div className="mt-1.5 font-medium">{trade.name || trade.vt_symbol}</div>
      <div className="mt-1 text-xs text-muted-foreground">{trade.vt_symbol}</div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="tabular-nums">{formatPrice(trade.price)}</span>
        <span className="tabular-nums text-muted-foreground">{trade.volume}股</span>
        {trade.pnl != null && (
          <span className={cn("tabular-nums font-medium", priceColorClass(trade.pnl))}>
            {formatAmount(trade.pnl)}
          </span>
        )}
      </div>
      {trade.reason && (
        <div className="mt-1.5 truncate text-xs text-muted-foreground">{trade.reason}</div>
      )}
      {/* 新信号扫光：半透明白光自左向右掠过一次，pointer-events-none 不挡点击 */}
      {isNew && (
        <span className="pointer-events-none absolute inset-0 animate-sweep-shine bg-gradient-sweep" />
      )}
    </button>
  );
}
