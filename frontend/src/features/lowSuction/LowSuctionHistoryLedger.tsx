import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Info } from "lucide-react";

import {
  fetchLowSuctionHistoricalOverview,
  fetchLowSuctionHistoricalTrade,
  fetchLowSuctionHistoricalTrades,
} from "@/api/lowSuction";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";
import { formatPct, phaseLabel, rateTone } from "./format";
import { LowSuctionRuleEvidenceModal } from "./LowSuctionRuleEvidenceModal";

const PAGE_SIZE = 20;

export function LowSuctionHistoryLedger() {
  const [page, setPage] = useState(1);
  const [marketPhase, setMarketPhase] = useState("");
  const [outcome, setOutcome] = useState("");
  const [selectedSignal, setSelectedSignal] = useState<string | null>(null);
  const overview = useQuery({
    queryKey: ["lowSuctionHistoryOverview"],
    queryFn: fetchLowSuctionHistoricalOverview,
    staleTime: Infinity,
  });
  const run = overview.data?.latest_run;
  const trades = useQuery({
    queryKey: ["lowSuctionHistoryTrades", run?.run_id, page, marketPhase, outcome],
    queryFn: () => fetchLowSuctionHistoricalTrades({
      runId: run!.run_id,
      page,
      pageSize: PAGE_SIZE,
      marketPhase: marketPhase || undefined,
      outcome: outcome || undefined,
    }),
    enabled: Boolean(run),
    staleTime: Infinity,
  });
  const detail = useQuery({
    queryKey: ["lowSuctionHistoryTrade", run?.run_id, selectedSignal],
    queryFn: () => fetchLowSuctionHistoricalTrade(run!.run_id, selectedSignal!),
    enabled: Boolean(run && selectedSignal),
    staleTime: Infinity,
  });

  if (overview.isLoading) return <div className="py-5"><LoadingState rows={6} /></div>;
  if (overview.error) {
    return <div className="py-5"><ErrorState message="反包历史逐笔账本暂时不可用" onRetry={() => void overview.refetch()} /></div>;
  }
  if (!run) {
    return (
      <div className="border-t py-12 text-center text-sm text-muted-foreground">
        历史数据库回放尚未完成物化
      </div>
    );
  }

  const totalPages = Math.max(1, Math.ceil((trades.data?.total ?? 0) / PAGE_SIZE));
  return (
    <div className="min-w-0">
      <div className="border-b py-4 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-medium">数据库历史回放 · {run.trade_count} 笔</div>
            <div className="mt-1 text-xs text-muted-foreground">
              当前成分向后回放，仅作探索；不计入正式资格门
            </div>
          </div>
          <div className="text-right text-xs text-muted-foreground">
            <div>输入 {run.input_fingerprint.slice(0, 12)}</div>
            <div>交易 {run.trade_fingerprint.slice(0, 12)}</div>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 border-b py-3">
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          行情
          <select
            className="h-8 border bg-background px-2 text-sm text-foreground"
            value={marketPhase}
            onChange={(event) => { setMarketPhase(event.target.value); setPage(1); }}
          >
            <option value="">全部</option>
            <option value="uptrend">主升</option>
            <option value="rotation">轮动</option>
            <option value="warming">升温</option>
          </select>
        </label>
        <label className="flex items-center gap-2 text-xs text-muted-foreground">
          结果
          <select
            className="h-8 border bg-background px-2 text-sm text-foreground"
            value={outcome}
            onChange={(event) => { setOutcome(event.target.value); setPage(1); }}
          >
            <option value="">全部</option>
            <option value="winner">盈利</option>
            <option value="loser">亏损</option>
          </select>
        </label>
      </div>

      {trades.isLoading ? <LoadingState rows={8} /> : trades.error ? (
        <ErrorState message="历史交易读取失败" onRetry={() => void trades.refetch()} />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1160px] text-left text-sm">
            <thead className="bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">信号日</th>
                <th className="px-3 py-2 font-medium">龙头</th>
                <th className="px-3 py-2 font-medium">概念 / 行情</th>
                <th className="px-3 py-2 text-right font-medium">排名 / 波段</th>
                <th className="px-3 py-2 font-medium">支撑</th>
                <th className="px-3 py-2 text-right font-medium">买入</th>
                <th className="px-3 py-2 text-right font-medium">D+1</th>
                <th className="px-3 py-2 font-medium">持有 / 退出</th>
                <th className="px-3 py-2 text-right font-medium">净收益</th>
              </tr>
            </thead>
            <tbody>
              {(trades.data?.items ?? []).map((trade) => (
                <tr
                  key={trade.signal_id}
                  className="border-b hover:bg-muted/20"
                >
                  <td className="px-3 py-2.5 font-mono text-xs">{trade.signal_date}</td>
                  <td className="min-w-40 px-3 py-2.5"><div className="flex items-center gap-1"><StockIdentityLink name={trade.stock_name} vtSymbol={trade.vt_symbol} /><button type="button" className="p-1 text-muted-foreground hover:text-foreground" title="查看买入规则" aria-label={`查看${trade.stock_name}买入规则`} onClick={() => setSelectedSignal(trade.signal_id)}><Info size={14} /></button></div></td>
                  <td className="px-3 py-2.5"><div>{trade.concept_name}</div><div className="text-xs text-muted-foreground">{phaseLabel(trade.market_phase)}</div></td>
                  <td className="px-3 py-2.5 text-right tabular-nums">龙{trade.dynamic_rank} / 第{trade.wave_number}波</td>
                  <td className="px-3 py-2.5"><div>{trade.support_line} · {trade.support_price.toFixed(2)}</div><div className="font-mono text-xs text-muted-foreground">{trade.support_test_date}</div></td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{trade.entry_price.toFixed(2)}</td>
                  <td className={cn("px-3 py-2.5 text-right tabular-nums", rateTone(trade.d1_net_return_pct))}>{formatPct(trade.d1_net_return_pct)}</td>
                  <td className="px-3 py-2.5"><div>{trade.holding_sessions} 日 · <span className="font-mono text-xs">{trade.exit_date}</span></div><div className="text-xs text-muted-foreground">{exitReasonLabel(trade.exit_reason)}</div></td>
                  <td className={cn("px-3 py-2.5 text-right font-semibold tabular-nums", rateTone(trade.net_return_pct))}>{formatPct(trade.net_return_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex min-h-12 items-center justify-between border-b text-xs text-muted-foreground">
        <span>共 {trades.data?.total ?? 0} 笔</span>
        <div className="flex items-center gap-2">
          <button className="p-2 disabled:opacity-30" title="上一页" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}><ChevronLeft size={16} /></button>
          <span>{page} / {totalPages}</span>
          <button className="p-2 disabled:opacity-30" title="下一页" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}><ChevronRight size={16} /></button>
        </div>
      </div>

      <LowSuctionRuleEvidenceModal
        open={Boolean(selectedSignal && detail.data)}
        onOpenChange={(open) => { if (!open) setSelectedSignal(null); }}
        evidence={detail.data ? {
          stockName: detail.data.stock_name,
          vtSymbol: detail.data.vt_symbol,
          conceptName: detail.data.concept_name,
          marketPhase: phaseLabel(detail.data.market_phase),
          rank: detail.data.dynamic_rank,
          waveNumber: detail.data.wave_number,
          supportLine: detail.data.support_line,
          supportPrice: detail.data.support_price,
          signalDate: detail.data.signal_date,
          entryPrice: detail.data.entry_price,
          signalEligible: true,
          decisionReason: `动态龙${detail.data.dynamic_rank}，第${detail.data.wave_number}波回踩${detail.data.support_line.toUpperCase()}后转强`,
          exitText: `${detail.data.exit_date} ${exitReasonLabel(detail.data.exit_reason)}，净收益 ${formatPct(detail.data.net_return_pct)}`,
        } : null}
      />
    </div>
  );
}

function exitReasonLabel(reason: string) {
  const labels: Record<string, string> = {
    higher_high_confirmed: "创新高确认退出",
    d1_loss_stop: "D+1 亏损止损",
    structure_broken: "个股结构破坏退出",
    campaign_ended: "概念行情结束退出",
  };
  return labels[reason] ?? reason;
}
