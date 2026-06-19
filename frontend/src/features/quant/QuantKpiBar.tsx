import { StatCard } from "@/components/dashboard/StatCard";
import { formatPct, priceColorClass } from "@/lib/utils";

export interface QuantKpi {
  candidateCount: number;
  holdingsCount: number;
  averageReturnPct: number | null;
}

/**
 * 量化页 KPI bar — 只展示候选数、持仓数和收益率，不展示账户金额。
 */
export function QuantKpiBar({ kpi }: { kpi: QuantKpi }) {
  const { candidateCount, holdingsCount, averageReturnPct } = kpi;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard label="量化候选" value={`${candidateCount} 只`} />
      <StatCard label="持仓" value={`${holdingsCount} 只`} />
      <StatCard
        label="持仓收益率"
        value={<span className={priceColorClass(averageReturnPct)}>{formatPct(averageReturnPct)}</span>}
        deltaLabel="平均收益率"
      />
    </div>
  );
}
