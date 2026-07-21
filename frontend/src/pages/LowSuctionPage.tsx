import { useQuery } from "@tanstack/react-query";

import {
  fetchLowSuctionHistoricalOverview,
  fetchLowSuctionStrategy,
  fetchLowSuctionSwingResearch,
} from "@/api/lowSuction";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { LowSuctionResearchWorkspace } from "@/features/lowSuction/LowSuctionResearchWorkspace";

export function LowSuctionPage() {
  const research = useQuery({
    queryKey: ["lowSuctionSwingResearch"],
    queryFn: fetchLowSuctionSwingResearch,
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
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });

  if (research.isLoading || history.isLoading || strategy.isLoading) {
    return <div className="py-5"><LoadingState rows={8} /></div>;
  }
  const validation = research.data?.cross_regime_validation;
  if (research.error || history.error || strategy.error || !validation || !history.data || !strategy.data) {
    const error = research.error ?? history.error ?? strategy.error;
    return (
      <div className="py-5">
        <ErrorState
          message={error instanceof Error ? error.message : "低吸回测暂时不可用"}
          onRetry={() => void Promise.all([research.refetch(), history.refetch(), strategy.refetch()])}
        />
      </div>
    );
  }
  return <LowSuctionResearchWorkspace validation={validation} history={history.data} strategy={strategy.data} />;
}
