/**
 * Holdings + KPI hook.
 *
 * Fetches simulation accounts and positions, derives return-rate KPIs and
 * pre-computes risk badges per position, so the
 * holding lane and KPI bar can read everything from one source.
 */
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHoldings, fetchSimulationAccounts } from "@/api/quant";
import type { SimulationPosition } from "@/api/quant";
import { computeRiskBadges, type RiskBadge } from "@/lib/portfolio-risk";

export function useHoldings() {
  const accountsQuery = useQuery({
    queryKey: ["simulationAccounts"],
    queryFn: fetchSimulationAccounts,
    staleTime: 20_000,
  });

  const holdingsQuery = useQuery({
    queryKey: ["portfolioHoldings"],
    queryFn: fetchHoldings,
    staleTime: 15_000,
    refetchInterval: 30_000,
  });

  const positions = holdingsQuery.data?.items ?? [];
  const account = accountsQuery.data?.items[0];

  const positionsBySymbol = useMemo(() => {
    const map = new Map<string, SimulationPosition>();
    for (const position of positions) map.set(position.vt_symbol, position);
    return map;
  }, [positions]);

  const riskBadgesBySymbol = useMemo(() => {
    const map = new Map<string, RiskBadge[]>();
    for (const position of positions) {
      map.set(position.vt_symbol, computeRiskBadges(position));
    }
    return map;
  }, [positions]);

  const marketValue = positions.reduce((sum, position) => sum + (position.market_value ?? 0), 0);
  // 持仓加权收益率：按市值加权的各股浮动收益率，反映持仓整体盈亏质量（而非总资产收益率）
  const weightedReturnPct = marketValue > 0
    ? positions.reduce((sum, position) => sum + (position.market_value ?? 0) * (position.floating_pnl_pct ?? 0), 0) / marketValue
    : null;
  const averageReturnPct = positions.length
    ? positions.reduce((sum, position) => sum + (position.floating_pnl_pct ?? 0), 0) / positions.length
    : null;

  return {
    account,
    accountId: account?.id,
    positions,
    positionsBySymbol,
    riskBadgesBySymbol,
    kpi: {
      weightedReturnPct,
      averageReturnPct,
      positionCount: positions.length,
    },
    isLoading: holdingsQuery.isLoading || accountsQuery.isLoading,
    isError: holdingsQuery.isError || accountsQuery.isError,
    refetch: () => {
      holdingsQuery.refetch();
      accountsQuery.refetch();
    },
  };
}
