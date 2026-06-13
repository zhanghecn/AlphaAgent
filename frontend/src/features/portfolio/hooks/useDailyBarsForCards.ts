/**
 * Batched daily bars hook (N+1 fix).
 *
 * Replaces the per-card fetchStockBars query: all visible symbols are queried
 * in one useQueries call, and React Query de-dupes by the shared
 * ["stockDailyBarsForCard", symbol] key, so the same stock in multiple lanes
 * fires only one request. The "刷新行情" button still works because the key
 * prefix is unchanged.
 */
import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { fetchStockBars } from "@/api/stocks";
import type { DailyBar } from "@/features/portfolio/HoldingCard";

export function useDailyBarsForCards(symbols: string[]) {
  const uniqueSymbols = useMemo(
    () => Array.from(new Set(symbols.filter(Boolean))),
    [symbols],
  );

  const queries = useQueries({
    queries: uniqueSymbols.map((symbol) => ({
      queryKey: ["stockDailyBarsForCard", symbol],
      queryFn: () => fetchStockBars(symbol, "1d", 30),
      staleTime: 60_000,
      select: (data: { items?: Array<{ trade_date: string; open: number; high: number; low: number; close: number }> }): DailyBar[] =>
        (data.items ?? []).map((bar) => ({
          time: bar.trade_date,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        })),
    })),
  });

  const barsBySymbol = useMemo(() => {
    const map = new Map<string, DailyBar[]>();
    uniqueSymbols.forEach((symbol, index) => {
      map.set(symbol, queries[index].data ?? []);
    });
    return map;
  }, [uniqueSymbols, queries]);

  return barsBySymbol;
}
