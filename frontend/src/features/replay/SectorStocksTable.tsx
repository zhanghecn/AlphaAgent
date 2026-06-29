/** SectorStocksTable — 板块成分股 + 当日涨跌 + 个股资金流向。点击个股跳详情页。*/
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { LoadingState } from "@/components/LoadingState";
import { fetchSectorStocks } from "@/api/mainlineReplay";
import { cn, formatAmount } from "@/lib/utils";

type SortBy = "net_inflow" | "change_pct" | "name";

export function SectorStocksTable({ sectorId, date }: { sectorId: string; date: string }) {
  const navigate = useNavigate();
  const [sortBy, setSortBy] = useState<SortBy>("net_inflow");
  const q = useQuery({
    queryKey: ["replaySectorStocks", sectorId, date, sortBy],
    queryFn: () => fetchSectorStocks(sectorId, date, sortBy),
    enabled: !!sectorId && !!date,
    staleTime: 60_000,
  });

  return (
    <div>
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">📊 成分股资金流向</span>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortBy)}
          className="rounded border bg-background px-1.5 py-0.5 text-[11px]"
        >
          <option value="net_inflow">按主力净流入</option>
          <option value="change_pct">按当日涨跌</option>
          <option value="name">按名称</option>
        </select>
      </div>
      {q.isLoading ? (
        <LoadingState rows={5} />
      ) : (q.data?.items ?? []).length === 0 ? (
        <div className="py-3 text-center text-xs text-muted-foreground">无成分股数据</div>
      ) : (
        <div className="max-h-72 space-y-px overflow-y-auto">
          <div className="flex items-center justify-between px-2 py-1 text-[10px] uppercase tracking-wide text-muted-foreground">
            <span>个股（点击看详情）</span>
            <span className="flex gap-3">
              <span className="w-12 text-right">涨跌</span>
              <span className="w-16 text-right">主力净流入</span>
            </span>
          </div>
          {(q.data?.items ?? []).map((it) => {
            const net = it.main_net_inflow;
            const inflowPositive = (net ?? 0) >= 0;
            return (
              <button
                key={it.vt_symbol}
                onClick={() => navigate(`/stocks/${it.vt_symbol}?date=${date}`)}
                title={`${it.vt_symbol}${it.main_net_inflow_ratio != null ? ` · 净流入占比 ${it.main_net_inflow_ratio.toFixed(2)}%` : ""} · 点击查看 ${date} 个股详情`}
                className="group flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-indigo-500/10 focus:outline-none focus-visible:ring-1 focus-visible:ring-indigo-400"
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate font-medium">{it.name}</span>
                  <span className="shrink-0 text-[10px] text-muted-foreground/60 group-hover:text-indigo-300/70">{it.vt_symbol.split(".")[0]}</span>
                </span>
                <span className="ml-2 flex shrink-0 items-center gap-3 tabular-nums">
                  <span className={cn("w-12 text-right", (it.change_pct ?? 0) >= 0 ? "text-rise" : "text-fall")}>
                    {it.change_pct == null ? "--" : `${it.change_pct > 0 ? "+" : ""}${it.change_pct.toFixed(2)}%`}
                  </span>
                  <span className="flex w-16 items-center justify-end gap-1">
                    {it.fund_inflow_available && (
                      <span className={cn("h-3 w-0.5 rounded-full", inflowPositive ? "bg-rise/70" : "bg-fall/70")} />
                    )}
                    <span className={cn(inflowPositive ? "text-rise" : "text-fall")}>
                      {it.fund_inflow_available ? formatAmount(net) : "--"}
                    </span>
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
      {q.data && (
        <div className="mt-1.5 text-[10px] text-muted-foreground">
          共 {q.data.total} 只 · {q.data.fund_flow_available} 只有资金流 · 价格源 {priceSourceLabel(q.data.price_source)}
        </div>
      )}
    </div>
  );
}

function priceSourceLabel(source: string | null | undefined): string {
  if (source === "daily_bar") return "日线";
  if (source === "intraday_snapshot") return "盘中快照";
  return "--";
}
