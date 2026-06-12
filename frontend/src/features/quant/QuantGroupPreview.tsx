import { useMemo } from "react";
import { Link } from "react-router-dom";
import { Briefcase, RefreshCw, WalletCards } from "lucide-react";
import { cn, formatAmount, formatPct, priceColorClass } from "@/lib/utils";
import { InfoCell } from "@/components/InfoCell";
import { Button } from "@/components/ui/button";

export function QuantGroupPreview({
  candidateCount,
  holdingsCount,
  cash,
  initialCash,
  positions,
  onAutoBuy,
  isAutoBuying,
}: {
  candidateCount: number;
  holdingsCount: number;
  cash?: number;
  initialCash?: number;
  positions: Array<{ market_value?: number | null }>;
  onAutoBuy: () => void;
  isAutoBuying: boolean;
}) {
  const marketValue = useMemo(() => positions.reduce((sum, p) => sum + (p.market_value ?? 0), 0), [positions]);
  const equity = (cash ?? 0) + marketValue;
  const returnPct = initialCash ? (equity / initialCash - 1) * 100 : null;

  return (
    <section className="rounded-lg border">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <Briefcase size={16} />
          <h2 className="text-sm font-semibold">模拟持仓</h2>
        </div>
        <Button asChild size="sm" variant="outline">
          <Link to="/portfolio">打开持仓中心</Link>
        </Button>
      </div>
      <div className="space-y-3 p-4">
        <div className="grid grid-cols-2 gap-2 text-sm">
          <InfoCell label="量化候选" value={`${candidateCount} 只`} />
          <InfoCell label="模拟持仓" value={`${holdingsCount} 只`} />
          <InfoCell label="权益" value={formatAmount(equity)} />
          <div className="text-xs text-muted-foreground">收益</div>
          <div className={cn("mt-0.5 font-medium tabular-nums", priceColorClass(returnPct))}>{formatPct(returnPct)}</div>
        </div>
        <Button size="sm" className="w-full" onClick={onAutoBuy} disabled={isAutoBuying}>
          {isAutoBuying ? <RefreshCw size={15} className="animate-spin" /> : <WalletCards size={15} />}
          自动模拟建仓
        </Button>
      </div>
    </section>
  );
}
