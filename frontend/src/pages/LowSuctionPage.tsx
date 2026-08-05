import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ReceiptText } from "lucide-react";

import {
  fetchLowSuctionBacktest,
  fetchLowSuctionLedger,
  fetchLowSuctionLive,
} from "@/api/lowSuction";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { LowSuctionBacktestView } from "@/features/lowSuction/LowSuctionBacktestView";
import { LowSuctionGuideView } from "@/features/lowSuction/LowSuctionGuideView";
import { LowSuctionLedgerView } from "@/features/lowSuction/LowSuctionLedgerView";
import { LowSuctionLiveView } from "@/features/lowSuction/LowSuctionLiveView";
import { cn } from "@/lib/utils";

type LowSuctionView = "live" | "backtest" | "ledger" | "guide";

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
  const query = useQuery({
    queryKey: ["lowSuctionLive"],
    queryFn: fetchLowSuctionLive,
    // 与后端 30 分钟缓存同频：盘中轮询命中缓存即可
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="低吸实时推荐暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return <LowSuctionLiveView payload={query.data} />;
}

function BacktestTab() {
  const query = useQuery({
    queryKey: ["lowSuctionBacktest"],
    queryFn: fetchLowSuctionBacktest,
    staleTime: 300_000,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data) {
    return (
      <div className="py-5">
        <ErrorState message="低吸回测报告暂时不可用" onRetry={() => void query.refetch()} />
      </div>
    );
  }
  return <LowSuctionBacktestView report={query.data.report} />;
}

function LedgerTab() {
  const query = useQuery({
    queryKey: ["lowSuctionLedger"],
    queryFn: fetchLowSuctionLedger,
    staleTime: 300_000,
  });
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
    />
  );
}
