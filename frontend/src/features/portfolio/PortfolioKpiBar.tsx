import { StatCard } from "@/components/dashboard/StatCard";
import { formatPct, priceColorClass } from "@/lib/utils";

export interface PortfolioKpi {
  weightedReturnPct: number | null;
  averageReturnPct: number | null;
  positionCount: number;
}

/**
 * Portfolio KPI bar — no account amount display, only position return quality.
 */
export function PortfolioKpiBar({ kpi }: { kpi: PortfolioKpi }) {
  const { weightedReturnPct, averageReturnPct, positionCount } = kpi;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard
        label="持仓收益率"
        value={<span className={priceColorClass(weightedReturnPct)}>{formatPct(weightedReturnPct)}</span>}
        deltaLabel="市值加权"
      />
      <StatCard
        label="平均收益率"
        value={<span className={priceColorClass(averageReturnPct)}>{formatPct(averageReturnPct)}</span>}
        deltaLabel="算术平均"
      />
      <StatCard label="持仓数" value={`${positionCount} 只`} />
    </div>
  );
}
