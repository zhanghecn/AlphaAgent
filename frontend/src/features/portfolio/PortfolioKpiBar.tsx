import { StatCard } from "@/components/dashboard/StatCard";
import { formatAmount, formatPct, priceColorClass } from "@/lib/utils";

export interface PortfolioKpi {
  weightedReturnPct: number | null;
  floatingPnl: number;
  returnPct: number | null;
  positionCount: number;
}

/**
 * Portfolio KPI bar — 三张 StatCard：持仓收益率(加权%) / 持仓盈亏 / 持仓数。
 * 不显示总资产/可用现金金额，聚焦持仓盈亏质量（用户看收益率而非金额）。
 * 持仓收益率 = 各股浮动收益率按市值加权，反映"选的股"整体表现。
 */
export function PortfolioKpiBar({ kpi }: { kpi: PortfolioKpi }) {
  const { weightedReturnPct, floatingPnl, returnPct, positionCount } = kpi;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <StatCard
        label="持仓收益率"
        value={<span className={priceColorClass(weightedReturnPct)}>{formatPct(weightedReturnPct)}</span>}
        deltaLabel="市值加权"
      />
      <StatCard
        label="持仓盈亏"
        value={<span className={priceColorClass(floatingPnl)}>{formatAmount(floatingPnl)}</span>}
        delta={returnPct ?? undefined}
        deltaLabel="总收益率"
      />
      <StatCard label="持仓数" value={`${positionCount} 只`} />
    </div>
  );
}
