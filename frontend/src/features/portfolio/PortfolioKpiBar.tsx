import { StatCard } from "@/components/dashboard/StatCard";
import { formatPct, priceColorClass } from "@/lib/utils";

export interface PortfolioKpi {
  averageReturnPct: number | null;
  positionCount: number;
}

/**
 * Portfolio KPI bar — no account amount display, only position return quality.
 */
export function PortfolioKpiBar({ kpi }: { kpi: PortfolioKpi }) {
  const { averageReturnPct, positionCount } = kpi;
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <StatCard
        label="持仓收益率"
        value={<span className={priceColorClass(averageReturnPct)}>{formatPct(averageReturnPct)}</span>}
        deltaLabel="算术平均"
      />
      <StatCard label="持仓数" value={`${positionCount} 只`} />
    </div>
  );
}
