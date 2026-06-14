import { StatCard } from "@/components/dashboard/StatCard";
import { formatPct, priceColorClass } from "@/lib/utils";

export interface QuantKpi {
  candidateCount: number;
  holdingsCount: number;
  weightedReturnPct: number | null;
}

/**
 * 量化页 KPI bar — 三张 StatCard：候选数 / 持仓数 / 持仓收益率(加权%)。
 * 与 PortfolioKpiBar 同构，去金额显示（用户看收益率而非总权益）。
 */
export function QuantKpiBar({ kpi }: { kpi: QuantKpi }) {
  const { candidateCount, holdingsCount, weightedReturnPct } = kpi;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard label="量化候选" value={`${candidateCount} 只`} />
      <StatCard label="持仓" value={`${holdingsCount} 只`} />
      <StatCard
        label="持仓收益率"
        value={<span className={priceColorClass(weightedReturnPct)}>{formatPct(weightedReturnPct)}</span>}
        deltaLabel="市值加权"
      />
    </div>
  );
}
