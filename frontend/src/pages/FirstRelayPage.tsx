import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { Activity, BarChart3, BookOpenText } from "lucide-react";

import {
  fetchFirstRelayBacktest,
  fetchFirstRelayLive,
  fetchFirstRelayLiveDates,
} from "@/api/firstRelay";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { J12BacktestView } from "@/features/firstRelay/J12BacktestView";
import { J12GuideView } from "@/features/firstRelay/J12GuideView";
import { J12LiveView } from "@/features/firstRelay/J12LiveView";
import { cn } from "@/lib/utils";

type J12View = "live" | "backtest" | "guide";

const J12_VIEWS: { value: J12View; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "guide", label: "口诀卡", icon: BookOpenText },
];

const REFRESH_MS = 30 * 1000;

function parseView(raw: string | null): J12View {
  return J12_VIEWS.some((v) => v.value === raw) ? (raw as J12View) : "live";
}

export function FirstRelayPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const view = parseView(searchParams.get("view"));
  const selectView = (v: J12View) => {
    if (v === view) return;
    const next = new URLSearchParams(searchParams);
    if (v === "live") next.delete("view");
    else next.set("view", v);
    setSearchParams(next, { replace: true });
  };
  return (
    <div className="min-w-0">
      <nav
        className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b"
        role="tablist"
        aria-label="一接二视图"
      >
        {J12_VIEWS.map((item) => {
          const Icon = item.icon;
          const active = view === item.value;
          return (
            <button
              key={item.value}
              id={`j12-view-${item.value}`}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => selectView(item.value)}
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
      {view === "live" ? <LiveTab /> : view === "backtest" ? <BacktestTab /> : <J12GuideView />}
    </div>
  );
}

function LiveTab() {
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const datesQuery = useQuery({
    queryKey: ["j12LiveDates"],
    queryFn: fetchFirstRelayLiveDates,
    staleTime: REFRESH_MS,
    refetchInterval: REFRESH_MS,
  });
  const query = useQuery({
    queryKey: ["j12Live", selectedDate],
    queryFn: () => fetchFirstRelayLive(selectedDate ?? undefined),
    refetchInterval: selectedDate === null ? REFRESH_MS : false,
    refetchOnWindowFocus: selectedDate === null,
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data)
    return <ErrorState message="一接二实时推荐暂时不可用" />;
  return (
    <J12LiveView
      payload={query.data}
      availableDates={datesQuery.data?.dates ?? []}
      selectedDate={selectedDate}
      onDateChange={setSelectedDate}
    />
  );
}

function BacktestTab() {
  const qc = useQueryClient();
  const query = useQuery({ queryKey: ["j12Backtest"], queryFn: fetchFirstRelayBacktest });
  const rebuild = useMutation({
    mutationFn: async () => {
      const r = await import("@/api/firstRelay").then((m) => m.rebuildFirstRelayBacktest());
      return r;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["j12Backtest"] }),
  });
  if (query.isLoading && !query.data) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (query.isError || !query.data)
    return <ErrorState message="一接二回测报告暂时不可用" />;
  const payload = query.data;
  if (payload.status !== "ok" || !payload.report) {
    return (
      <J12BacktestView
        report={undefined}
        building={rebuild.isPending}
        onRebuild={() => rebuild.mutate()}
      />
    );
  }
  return (
    <J12BacktestView
      report={payload.report}
      building={rebuild.isPending}
      onRebuild={() => rebuild.mutate()}
    />
  );
}
