import { StatCard } from "@/components/dashboard/StatCard";
import { priceColorClass } from "@/lib/utils";
import { CountUp, KpiNumber, StaggerList, StaggerItem } from "@/components/motion";

export interface QuantKpi {
  candidateCount: number;
  holdingsCount: number;
  averageReturnPct: number | null;
}

/**
 * 量化页 KPI bar — 只展示候选数、持仓数和收益率，不展示账户金额。
 * 计数走 CountUp 滚动，收益率走 KpiNumber（滚动 + 涨跌脉冲）。
 */
export function QuantKpiBar({ kpi }: { kpi: QuantKpi }) {
  const { candidateCount, holdingsCount, averageReturnPct } = kpi;
  return (
    <StaggerList className="grid gap-3 sm:grid-cols-3" staggerDelay={0.08}>
      <StaggerItem>
        <StatCard
          label="量化候选"
          value={
            <>
              <CountUp value={candidateCount} format="raw" decimals={0} /> 只
            </>
          }
        />
      </StaggerItem>
      <StaggerItem>
        <StatCard
          label="持仓"
          value={
            <>
              <CountUp value={holdingsCount} format="raw" decimals={0} /> 只
            </>
          }
        />
      </StaggerItem>
      <StaggerItem>
        <StatCard
          label="持仓收益率"
          value={
            <KpiNumber
              value={averageReturnPct}
              format="pct"
              pulse
              className={priceColorClass(averageReturnPct)}
            />
          }
          deltaLabel="平均收益率"
        />
      </StaggerItem>
    </StaggerList>
  );
}
