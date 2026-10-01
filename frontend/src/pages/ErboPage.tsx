import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText } from "lucide-react";

import {
  fetchErboBacktest,
  fetchErboBacktestStatus,
  fetchErboLive,
  fetchErboLiveDates,
  rebuildErboBacktest,
  type ErboRebuildStatus,
} from "@/api/erbo";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { ErboBacktestView } from "@/features/erbo/ErboBacktestView";
import { ErboGuideView } from "@/features/erbo/ErboGuideView";
import { ErboLiveView } from "@/features/erbo/ErboLiveView";
import { cn } from "@/lib/utils";

type ErboView = "live" | "backtest" | "guide";

export const ERBO_LIVE_REFRESH_INTERVAL_MS = 30 * 1000;

const ERBO_VIEWS: { value: ErboView; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "guide", label: "规则说明", icon: BookOpenText },
];

function isBuilding(status: ErboRebuildStatus | undefined) {
  return status?.status === "queued" || status?.status === "running";
}

export function ErboPage() {
  const [view, setView] = useState<ErboView>("live");
  return (
    <div className="min-w-0">
      <nav
        className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b"
        role="tablist"
        aria-label="二波反包视图"
      >
        {ERBO_VIEWS.map((item) => {
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
      ) : (
        <ErboGuideView />
      )}
    </div>
  );
}

function LiveTab() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const datesQuery = useQuery({
    queryKey: ["erboLiveDates"],
    queryFn: fetchErboLiveDates,
    staleTime: ERBO_LIVE_REFRESH_INTERVAL_MS,
    refetchInterval: ERBO_LIVE_REFRESH_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
  const query = useQuery({
    queryKey: ["erboLive", selectedDate],
    queryFn: () => fetchErboLive(selectedDate ?? undefined),
    refetchInterval: selectedDate === null ? ERBO_LIVE_REFRESH_INTERVAL_MS : false,
    refetchOnWindowFocus: selectedDate === null,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="二波反包实时推荐暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <ErboLiveView
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
    queryKey: ["erboBacktest"],
    queryFn: fetchErboBacktest,
    staleTime: 300_000,
  });
  const rebuild = useMutation({ mutationFn: rebuildErboBacktest });
  const statusQuery = useQuery({
    queryKey: ["erboBacktestStatus"],
    queryFn: fetchErboBacktestStatus,
    refetchInterval: (q) => (isBuilding(q.state.data) ? 8_000 : false),
    refetchOnWindowFocus: true,
  });
  const status: ErboRebuildStatus =
    statusQuery.data ?? (query.data?.rebuild as ErboRebuildStatus | undefined) ?? { status: "idle" };
  const building = isBuilding(status) || rebuild.isPending;
  const previousStatus = useRef(status.status);

  useEffect(() => {
    const was = previousStatus.current;
    const now = status.status;
    if ((was === "queued" || was === "running") && (now === "done" || now === "failed")) {
      qc.invalidateQueries({ queryKey: ["erboBacktest"] });
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
        <ErrorState message="二波反包回测报告暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  if (!query.data.report) {
    return (
      <div className="py-5 text-sm text-muted-foreground">
        {query.data.message ?? "回测报告尚未生成——点击「全量重算」生成。"}
        <button
          type="button"
          className="ml-3 h-8 rounded-md border px-3 text-xs font-semibold hover:bg-muted/40 disabled:opacity-50"
          disabled={building}
          onClick={trigger}
        >
          {building ? "重算中…" : "全量重算"}
        </button>
      </div>
    );
  }
  return (
    <ErboBacktestView
      report={query.data.report}
      rebuild={status}
      building={building}
      canRebuild={!building}
      onRebuild={trigger}
      rebuildError={rebuild.isError ? (rebuild.error as Error).message : status.error ?? null}
    />
  );
}
