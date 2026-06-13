import { StatCard } from "@/components/dashboard/StatCard";
import { formatAmount, priceColorClass } from "@/lib/utils";

export interface PortfolioKpi {
  cash: number;
  equity: number;
  returnPct: number | null;
  floatingPnl: number;
}

/**
 * Portfolio KPI bar — three focused StatCards: total assets (with return
 * badge), floating P&L, and available cash. Trimmed from five cards to cut
 * visual noise so the workflow lanes stay the focus.
 */
export function PortfolioKpiBar({ kpi }: { kpi: PortfolioKpi }) {
  const { cash, equity, returnPct, floatingPnl } = kpi;

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard
        label="总资产"
        value={formatAmount(equity)}
        delta={returnPct ?? undefined}
        deltaLabel="累计收益率"
      />
      <StatCard
        label="持仓盈亏"
        value={<span className={priceColorClass(floatingPnl)}>{formatAmount(floatingPnl)}</span>}
        delta={returnPct ?? undefined}
        deltaLabel="收益率"
      />
      <StatCard label="可用现金" value={formatAmount(cash)} />
    </div>
  );
}
