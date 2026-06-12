import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";

export interface PortfolioSummaryProps {
  cash?: number;
  initialCash?: number;
  positions: Array<{ market_value?: number | null }>;
  accountCount: number;
  groupCount: number;
}

export function PortfolioSummary({
  cash,
  initialCash,
  positions,
  accountCount: _accountCount,
  groupCount: _groupCount,
}: PortfolioSummaryProps) {
  void _accountCount;
  void _groupCount;
  const marketValue = positions.reduce((sum, p) => sum + (p.market_value ?? 0), 0);
  const equity = (cash ?? 0) + marketValue;
  const returnPct = initialCash ? (equity / initialCash - 1) * 100 : null;

  return (
    <section className="grid gap-3 rounded-lg border p-4 text-sm md:grid-cols-5">
      <div>
        <div className="text-xs text-muted-foreground">总权益</div>
        <div className="mt-0.5 font-medium tabular-nums">{formatAmount(equity)}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">现金</div>
        <div className="mt-0.5 font-medium tabular-nums">{formatAmount(cash)}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">持仓市值</div>
        <div className="mt-0.5 font-medium tabular-nums">{formatAmount(marketValue)}</div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">总收益率</div>
        <div className={cn("mt-0.5 font-medium tabular-nums", priceColorClass(returnPct))}>
          {formatPct(returnPct)}
        </div>
      </div>
      <div>
        <div className="text-xs text-muted-foreground">持仓数</div>
        <div className="mt-0.5 font-medium tabular-nums">{positions.length}</div>
      </div>
    </section>
  );
}
