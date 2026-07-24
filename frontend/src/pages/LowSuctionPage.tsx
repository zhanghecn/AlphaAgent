import { useQuery } from "@tanstack/react-query";

import {
  fetchLowSuctionCrossRegimeValidation,
  fetchLowSuctionHistoricalOverview,
  fetchLowSuctionStrategy,
} from "@/api/lowSuction";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { LowSuctionResearchWorkspace } from "@/features/lowSuction/LowSuctionResearchWorkspace";
import { liveRefetchIntervalMs } from "@/features/lowSuction/liveStatus";

export function LowSuctionPage() {
  const validation = useQuery({
    queryKey: ["lowSuctionCrossRegimeValidation"],
    queryFn: fetchLowSuctionCrossRegimeValidation,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const history = useQuery({
    queryKey: ["lowSuctionHistoryOverview"],
    queryFn: fetchLowSuctionHistoricalOverview,
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });
  const strategy = useQuery({
    queryKey: ["lowSuctionStrategy"],
    queryFn: fetchLowSuctionStrategy,
    refetchInterval: (query) =>
      query.state.data ? liveRefetchIntervalMs(query.state.data) : 60_000,
    refetchOnWindowFocus: true,
  });

  if (validation.isLoading || history.isLoading || strategy.isLoading) {
    return <div className="py-5"><LoadingState rows={8} /></div>;
  }
  if (validation.error || history.error || strategy.error || !validation.data || !history.data || !strategy.data) {
    const error = validation.error ?? history.error ?? strategy.error;
    return (
      <div className="py-5">
        <ErrorState
          message={error instanceof Error ? error.message : "反包回测暂时不可用"}
          onRetry={() => void Promise.all([validation.refetch(), history.refetch(), strategy.refetch()])}
        />
      </div>
    );
  }
  return <LowSuctionResearchWorkspace validation={validation.data} history={history.data} strategy={strategy.data} />;
}
