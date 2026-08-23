import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ReceiptText } from "lucide-react";

import {
  fetchQianlongBacktest,
  fetchQianlongBacktestStatus,
  fetchQianlongLedger,
  fetchQianlongLive,
  fetchQianlongLiveDates,
  rebuildQianlongBacktest,
  type QianlongRebuildStatus,
} from "@/api/qianlong";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { QianlongBacktestView } from "@/features/qianlong/QianlongBacktestView";
import { QianlongGuideView } from "@/features/qianlong/QianlongGuideView";
import { QianlongLedgerView } from "@/features/qianlong/QianlongLedgerView";
import { QianlongLiveView } from "@/features/qianlong/QianlongLiveView";
import { cn } from "@/lib/utils";

type QianlongView = "live" | "backtest" | "ledger" | "guide";

export const QIANLONG_LIVE_REFRESH_INTERVAL_MS = 30 * 1000;

const QIANLONG_VIEWS: { value: QianlongView; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "guide", label: "规则说明", icon: BookOpenText },
];

function isBuilding(status: QianlongRebuildStatus | undefined) {
  return status?.status === "queued" || status?.status === "running";
}

export function QianlongPage() {
  const [view, setView] = useState<QianlongView>("live");
  return (
    <div className="min-w-0">
      <nav
        className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b"
        role="tablist"
        aria-label="潜龙首板视图"
      >
        {QIANLONG_VIEWS.map((item) => {
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
        <QianlongGuideView />
      )}
    </div>
  );
}

function LiveTab() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const datesQuery = useQuery({
    queryKey: ["qianlongLiveDates"],
    queryFn: fetchQianlongLiveDates,
    staleTime: QIANLONG_LIVE_REFRESH_INTERVAL_MS,
    refetchInterval: QIANLONG_LIVE_REFRESH_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
  const query = useQuery({
    queryKey: ["qianlongLive", selectedDate],
    queryFn: () => fetchQianlongLive(selectedDate ?? undefined),
    refetchInterval: selectedDate === null ? QIANLONG_LIVE_REFRESH_INTERVAL_MS : false,
    refetchOnWindowFocus: selectedDate === null,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="潜龙首板实时推荐暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <QianlongLiveView
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
    queryKey: ["qianlongBacktest"],
    queryFn: fetchQianlongBacktest,
    staleTime: 300_000,
  });
  const rebuild = useMutation({ mutationFn: rebuildQianlongBacktest });
  const statusQuery = useQuery({
    queryKey: ["qianlongBacktestStatus"],
    queryFn: fetchQianlongBacktestStatus,
    refetchInterval: (q) => (isBuilding(q.state.data) ? 8_000 : false),
    refetchOnWindowFocus: true,
  });
  const status: QianlongRebuildStatus =
    statusQuery.data ?? query.data?.rebuild ?? { status: "idle" };
  const building = isBuilding(status) || rebuild.isPending;
  const previousStatus = useRef(status.status);

  useEffect(() => {
    const was = previousStatus.current;
    const now = status.status;
    if ((was === "queued" || was === "running") && (now === "done" || now === "failed")) {
      qc.invalidateQueries({ queryKey: ["qianlongBacktest"] });
      qc.invalidateQueries({ queryKey: ["qianlongLedger"] });
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
        <ErrorState message="潜龙首板回测报告暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <QianlongBacktestView
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
    queryKey: ["qianlongLedger", month],
    queryFn: () => fetchQianlongLedger(month ?? undefined),
    staleTime: 300_000,
  });
  const statusQuery = useQuery({
    queryKey: ["qianlongBacktestStatus"],
    queryFn: fetchQianlongBacktestStatus,
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
      qc.invalidateQueries({ queryKey: ["qianlongLedger"] });
      qc.invalidateQueries({ queryKey: ["qianlongBacktest"] });
    }
    previousStatus.current = statusValue;
  }, [qc, statusValue]);
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="潜龙首板历史交割单暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <QianlongLedgerView
      ledgerDays={query.data.ledger_days}
      months={query.data.months ?? []}
      month={query.data.month ?? null}
      onMonthChange={setMonth}
      caliber={query.data.caliber}
    />
  );
}
