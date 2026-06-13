/**
 * Portfolio workflow state hook.
 *
 * Takes the flat group list, fetches every group's items in one batched
 * useQueries call, and partitions both groups and their items into the five
 * workflow states (watch / candidate / holding / review / blacklist) so the
 * page can render by lifecycle lane.
 */
import { useMemo } from "react";
import { useQueries } from "@tanstack/react-query";
import { fetchPortfolioGroupItems } from "@/api/quant";
import type { PortfolioGroup, PortfolioItem } from "@/api/quant";
import { groupByState, type PortfolioState } from "@/lib/portfolio-states";

const EMPTY_STATE_ITEMS: Record<PortfolioState, PortfolioItem[]> = {
  watch: [],
  candidate: [],
  holding: [],
  review: [],
  blacklist: [],
};

export function usePortfolioState(groups: PortfolioGroup[]) {
  const itemsQueries = useQueries({
    queries: groups.map((group) => ({
      queryKey: ["portfolioGroupItems", group.id],
      queryFn: () => fetchPortfolioGroupItems(group.id),
      staleTime: 20_000,
    })),
  });

  const itemsByGroupId = useMemo(() => {
    const map = new Map<number, PortfolioItem[]>();
    groups.forEach((group, index) => {
      map.set(group.id, itemsQueries[index].data?.items ?? []);
    });
    return map;
  }, [groups, itemsQueries]);

  const groupsByState = useMemo(() => groupByState(groups), [groups]);

  const itemsByState = useMemo(() => {
    const result: Record<PortfolioState, PortfolioItem[]> = {
      watch: [],
      candidate: [],
      holding: [],
      review: [],
      blacklist: [],
    };
    (Object.keys(groupsByState) as PortfolioState[]).forEach((state) => {
      result[state] = groupsByState[state].flatMap((group) => itemsByGroupId.get(group.id) ?? []);
    });
    return result;
  }, [groupsByState, itemsByGroupId]);

  const isLoading = itemsQueries.some((query) => query.isLoading);
  const isError = itemsQueries.some((query) => query.isError);

  return {
    groupsByState,
    itemsByState,
    itemsByGroupId,
    isLoading,
    isError,
    // Helper for components that still need a single group's items.
    itemsOf: (groupId: number) => itemsByGroupId.get(groupId) ?? [],
    emptyStateItems: EMPTY_STATE_ITEMS,
  };
}
