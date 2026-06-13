/**
 * Holdings + KPI hook.
 *
 * Fetches simulation accounts and positions, derives KPI totals (equity,
 * market value, return %) and pre-computes risk badges per position, so the
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
  const floatingPnl = positions.reduce((sum, position) => sum + (position.floating_pnl ?? 0), 0);
  const cash = account?.cash ?? 0;
  const equity = cash + marketValue;
  const initialCash = account?.initial_cash ?? 0;
  const returnPct = initialCash ? (equity / initialCash - 1) * 100 : null;

  return {
    account,
    accountId: account?.id,
    positions,
    positionsBySymbol,
    riskBadgesBySymbol,
    kpi: {
      cash,
      marketValue,
      equity,
      initialCash,
      returnPct,
      floatingPnl,
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
