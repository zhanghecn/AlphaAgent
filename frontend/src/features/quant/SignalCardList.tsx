import { useState } from "react";
import type { BacktestTrade } from "@/api/quant";
import { SignalCard } from "./SignalCard";
import { StaggerList, StaggerItem } from "@/components/motion";

interface SignalCardListProps {
  trades: BacktestTrade[];
  onTradeClick?: (trade: BacktestTrade) => void;
  highlightedId?: number | null;
}

type FilterMode = "all" | "buy" | "sell";

export function SignalCardList({ trades, onTradeClick, highlightedId }: SignalCardListProps) {
  const [filter, setFilter] = useState<FilterMode>("all");

  if (trades.length === 0) return null;

  const filtered = filter === "all"
    ? trades
    : trades.filter((t) => filter === "buy" ? t.side === "BUY" : t.side === "SELL");

  const buyCount = trades.filter((t) => t.side === "BUY").length;
  const sellCount = trades.filter((t) => t.side === "SELL").length;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-sm font-medium">信号卡片</div>
        <div className="flex rounded-md border text-xs">
          <FilterBtn active={filter === "all"} onClick={() => setFilter("all")}>
            全部 {trades.length}
          </FilterBtn>
          <FilterBtn active={filter === "buy"} onClick={() => setFilter("buy")}>
            买入 {buyCount}
          </FilterBtn>
          <FilterBtn active={filter === "sell"} onClick={() => setFilter("sell")}>
            卖出 {sellCount}
          </FilterBtn>
        </div>
      </div>
      {/* 信号卡片：错峰进入 + 每张 mount 时扫光一次（新信号仪式感） */}
      <StaggerList className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" staggerDelay={0.04}>
        {filtered.map((trade, idx) => (
          <StaggerItem key={`${trade.trade_date}-${trade.vt_symbol}-${trade.side}-${idx}`}>
            <SignalCard
              trade={trade}
              isHighlighted={highlightedId != null && trade.id === highlightedId}
              isNew
              onClick={onTradeClick}
            />
          </StaggerItem>
        ))}
      </StaggerList>
      {filtered.length === 0 && (
        <div className="py-4 text-center text-sm text-muted-foreground">
          没有匹配的信号
        </div>
      )}
    </div>
  );
}

function FilterBtn({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={
        active
          ? "bg-primary px-2.5 py-1 text-primary-foreground"
          : "px-2.5 py-1 text-muted-foreground hover:bg-muted"
      }
      onClick={onClick}
    >
      {children}
    </button>
  );
}
