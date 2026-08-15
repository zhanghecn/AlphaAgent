import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ReceiptText } from "lucide-react";

import {
  fetchLowSuctionBacktest,
  fetchLowSuctionBacktestStatus,
  fetchLowSuctionLedger,
  fetchLowSuctionLive,
  fetchLowSuctionLiveDates,
  rebuildLowSuctionBacktest,
  type LowSuctionRebuildStatus,
} from "@/api/lowSuction";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { LowSuctionBacktestView } from "@/features/lowSuction/LowSuctionBacktestView";
import { LowSuctionGuideView } from "@/features/lowSuction/LowSuctionGuideView";
import { LowSuctionLedgerView } from "@/features/lowSuction/LowSuctionLedgerView";
import { LowSuctionLiveView } from "@/features/lowSuction/LowSuctionLiveView";
import { cn } from "@/lib/utils";

type LowSuctionView = "live" | "backtest" | "ledger" | "guide";

export const LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS = 60 * 1000;

const LOW_SUCTION_VIEWS: { value: LowSuctionView; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "guide", label: "规则说明", icon: BookOpenText },
];

export function LowSuctionPage() {
  const [view, setView] = useState<LowSuctionView>("live");
  return (
    <div className="min-w-0">
      <nav
        className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b"
        role="tablist"
        aria-label="低吸视图"
      >
        {LOW_SUCTION_VIEWS.map((item) => {
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
        <LowSuctionGuideView />
      )}
    </div>
  );
}

function LiveTab() {
  const [trendPage, setTrendPage] = useState(1);
  const [oversoldPage, setOversoldPage] = useState(1);
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const datesQuery = useQuery({
    queryKey: ["lowSuctionLiveDates"],
    queryFn: fetchLowSuctionLiveDates,
    staleTime: LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS,
    refetchInterval: LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
  const query = useQuery({
    queryKey: ["lowSuctionLive", selectedDate, trendPage, oversoldPage],
    queryFn: () => fetchLowSuctionLive({ trendPage, oversoldPage, date: selectedDate ?? undefined }),
    // 后端只读持久化快照；分钟级读取可及时显示下一轮后台扫描结果。
    refetchInterval: selectedDate === null ? LOW_SUCTION_LIVE_REFRESH_INTERVAL_MS : false,
    refetchOnWindowFocus: selectedDate === null,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="低吸实时推荐暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <LowSuctionLiveView
      payload={query.data}
      availableDates={datesQuery.data?.dates ?? []}
      selectedDate={selectedDate}
      onDateChange={(date) => {
        setSelectedDate(date);
        setTrendPage(1);
        setOversoldPage(1);
      }}
      onTrendPageChange={setTrendPage}
      onOversoldPageChange={setOversoldPage}
    />
  );
}

function BacktestTab() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["lowSuctionBacktest"],
    queryFn: fetchLowSuctionBacktest,
    staleTime: 300_000,
  });
  const rebuild = useMutation({ mutationFn: rebuildLowSuctionBacktest });
  const statusQuery = useQuery({
    queryKey: ["lowSuctionBacktestStatus"],
    queryFn: fetchLowSuctionBacktestStatus,
    // 即使当前没有物化报告，也先读取状态，避免刷新页面后丢失运行中的回测。
    enabled: true,
    refetchInterval: (q) =>
      q.state.data?.status === "building" ? 8_000 : false,
    refetchOnWindowFocus: true,
  });
  const status: LowSuctionRebuildStatus = statusQuery.data ?? query.data?.rebuild ?? { status: "idle" };
  const building = status.status === "building";
  const previousStatus = useRef(status.status);

  useEffect(() => {
    if (
      previousStatus.current === "building"
      && (status.status === "ready" || status.status === "failed")
    ) {
      qc.invalidateQueries({ queryKey: ["lowSuctionBacktest"] });
      qc.invalidateQueries({ queryKey: ["lowSuctionLedger"] });
    }
    previousStatus.current = status.status;
  }, [qc, status.status]);

  const trigger = () => {
    rebuild.mutate(undefined, {
      onSuccess: (result) => {
        qc.setQueryData(["lowSuctionBacktestStatus"], result);
        void statusQuery.refetch();
      },
      // 409 表示已有任务；立即读取状态和运行记录，不把它伪装成一次新任务。
      onError: () => void statusQuery.refetch(),
    });
  };

  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="低吸回测报告暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <LowSuctionBacktestView
      report={query.data.report}
      rebuild={status}
      building={building || rebuild.isPending}
      canRebuild={!building && !rebuild.isPending}
      onRebuild={trigger}
      rebuildError={
        rebuild.isError ? (rebuild.error as Error).message : status.error?.message ?? null
      }
    />
  );
}

function LedgerTab() {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["lowSuctionLedger"],
    queryFn: fetchLowSuctionLedger,
    staleTime: 300_000,
  });
  // 与回测页共享状态缓存；本页签挂载期间若正在重算，也保持 8s 轮询，
  // 让「无记录」页能实时展示重建进度并在完成后自动出记录。
  const statusQuery = useQuery({
    queryKey: ["lowSuctionBacktestStatus"],
    queryFn: fetchLowSuctionBacktestStatus,
    refetchInterval: (q) =>
      q.state.data?.status === "building" ? 8_000 : false,
    refetchOnWindowFocus: true,
  });
  const statusValue = statusQuery.data?.status;
  const previousStatus = useRef(statusValue);
  useEffect(() => {
    if (
      previousStatus.current === "building"
      && (statusValue === "ready" || statusValue === "failed")
    ) {
      qc.invalidateQueries({ queryKey: ["lowSuctionLedger"] });
      qc.invalidateQueries({ queryKey: ["lowSuctionBacktest"] });
    }
    previousStatus.current = statusValue;
  }, [qc, statusValue]);
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="低吸历史交割单暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return (
    <LowSuctionLedgerView
      ledgerDays={query.data.ledger_days}
      labelConvention={query.data.label_convention}
      rebuild={statusQuery.data}
    />
  );
}
