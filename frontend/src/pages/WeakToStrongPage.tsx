import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ReceiptText } from "lucide-react";

import {
  fetchW2sBacktest,
  fetchW2sBacktestStatus,
  fetchW2sLedger,
  fetchW2sLive,
  fetchW2sLiveDates,
  rebuildW2sBacktest,
  type W2sRebuildStatus,
} from "@/api/weakToStrong";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { W2sBacktestView } from "@/features/weakToStrong/W2sBacktestView";
import { W2sGuideView } from "@/features/weakToStrong/W2sGuideView";
import { W2sLedgerView } from "@/features/weakToStrong/W2sLedgerView";
import { W2sLiveView } from "@/features/weakToStrong/W2sLiveView";
import { cn } from "@/lib/utils";

type W2sView = "live" | "backtest" | "ledger" | "guide";

export const W2S_LIVE_REFRESH_INTERVAL_MS = 30 * 1000;

const W2S_VIEWS: { value: W2sView; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "guide", label: "规则说明", icon: BookOpenText },
];

function isBuilding(status: W2sRebuildStatus | undefined) {
  return status?.status === "queued" || status?.status === "running";
}

export function WeakToStrongPage() {
  const [view, setView] = useState<W2sView>("live");
  return (
    <div className="min-w-0">
      <nav
        className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b"
        role="tablist"
        aria-label="U型补涨打板视图"
      >
        {W2S_VIEWS.map((item) => {
          const Icon = item.icon;
          const active = view === item.value;
          return (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setView(item.value)}
              className={cn(
                "flex h-11 shrink-0 items-center gap-2 border-b-2 text-sm transition-colors",
                active
                  ? "border-primary font-semibold text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              <Icon size={15} />
              {item.label}
            </button>
          );
        })}
      </nav>
      {view === "live" ? (
        <LiveTab />
      ) : view === "backtest" ? (
        <BacktestTab />
      ) : view === "ledger" ? (
        <LedgerTab />
      ) : (
        <W2sGuideView />
      )}
    </div>
  );
}

function LiveTab() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const datesQuery = useQuery({
    queryKey: ["w2sLiveDates"],
    queryFn: fetchW2sLiveDates,
    staleTime: W2S_LIVE_REFRESH_INTERVAL_MS,
    refetchInterval: W2S_LIVE_REFRESH_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
  const query = useQuery({
    queryKey: ["w2sLive", selectedDate],
    queryFn: () => fetchW2sLive(selectedDate ?? undefined),
    refetchInterval: selectedDate === null ? W2S_LIVE_REFRESH_INTERVAL_MS : false,
    refetchOnWindowFocus: selectedDate === null,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="U型补涨打板实时推荐暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <W2sLiveView
      payload={query.data}
      availableDates={datesQuery.data?.dates ?? []}
      selectedDate={selectedDate}
      onDateChange={setSelectedDate}
    />
  );
}

function BacktestTab() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["w2sBacktest"],
    queryFn: fetchW2sBacktest,
    staleTime: 300_000,
  });
  const rebuild = useMutation({ mutationFn: rebuildW2sBacktest });
  const statusQuery = useQuery({
    queryKey: ["w2sBacktestStatus"],
    queryFn: fetchW2sBacktestStatus,
    refetchInterval: (q) => (isBuilding(q.state.data) ? 8_000 : false),
    refetchOnWindowFocus: true,
  });
  const status: W2sRebuildStatus =
    statusQuery.data ?? query.data?.rebuild ?? { status: "idle" };
  const building = isBuilding(status) || rebuild.isPending;
  const previousStatus = useRef(status.status);

  useEffect(() => {
    const was = previousStatus.current;
    const now = status.status;
    if ((was === "queued" || was === "running") && (now === "done" || now === "failed")) {
      qc.invalidateQueries({ queryKey: ["w2sBacktest"] });
      qc.invalidateQueries({ queryKey: ["w2sLedger"] });
    }
    previousStatus.current = now;
  }, [qc, status.status]);

  const trigger = () => {
    rebuild.mutate(undefined, {
      onSuccess: () => void statusQuery.refetch(),
      onError: () => void statusQuery.refetch(),
    });
  };

  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="U型补涨打板回测报告暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <W2sBacktestView
      report={query.data.report}
      rebuild={status}
      building={building}
      canRebuild={!building}
      onRebuild={trigger}
      rebuildError={
        rebuild.isError ? (rebuild.error as Error).message : status.error ?? null
      }
    />
  );
}

function LedgerTab() {
  const qc = useQueryClient();
  const [month, setMonth] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["w2sLedger", month],
    queryFn: () => fetchW2sLedger(month ?? undefined),
    staleTime: 300_000,
  });
  const statusQuery = useQuery({
    queryKey: ["w2sBacktestStatus"],
    queryFn: fetchW2sBacktestStatus,
    refetchInterval: (q) => (isBuilding(q.state.data) ? 8_000 : false),
    refetchOnWindowFocus: true,
  });
  const statusValue = statusQuery.data?.status;
  const previousStatus = useRef(statusValue);
  useEffect(() => {
    if (
      (previousStatus.current === "queued" || previousStatus.current === "running")
      && (statusValue === "done" || statusValue === "failed")
    ) {
      qc.invalidateQueries({ queryKey: ["w2sLedger"] });
      qc.invalidateQueries({ queryKey: ["w2sBacktest"] });
    }
    previousStatus.current = statusValue;
  }, [qc, statusValue]);
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="U型补涨打板历史交割单暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <W2sLedgerView
      ledgerDays={query.data.ledger_days}
      months={query.data.months ?? []}
      month={query.data.month ?? null}
      onMonthChange={setMonth}
      caliber={query.data.caliber}
    />
  );
}
