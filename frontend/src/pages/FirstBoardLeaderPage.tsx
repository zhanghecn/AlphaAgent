import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ReceiptText } from "lucide-react";

import { fetchFirstBoardLeaderBacktest, fetchFirstBoardLeaderLive } from "@/api/limitUp";
import { LoadingState } from "@/components/LoadingState";
import { LedgerTimeline } from "@/features/limitUp/LedgerTimeline";
import { LiveSignalCard } from "@/features/limitUp/LiveSignalCard";
import { ACTIVE_LIVE_SNAPSHOT_POLL_INTERVAL_MS } from "@/features/limitUp/nextSessionPlan";
import { BacktestView } from "@/pages/LimitUpPage";
import { cn } from "@/lib/utils";

type LeaderView = "live" | "backtest" | "ledger" | "guide";

const LEADER_VIEWS: { value: LeaderView; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "guide", label: "规则说明", icon: BookOpenText },
];

const IDLE_POLL_INTERVAL_MS = 120_000;

export function FirstBoardLeaderPage() {
  const [view, setView] = useState<LeaderView>("live");
  return (
    <div className="min-w-0">
      <nav
        className="mb-3 flex h-11 items-end gap-6 overflow-x-auto border-b"
        role="tablist"
        aria-label="首板龙头视图"
      >
        {LEADER_VIEWS.map((item) => {
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
        <LiveLeaderView />
      ) : view === "backtest" ? (
        <BacktestLeaderView />
      ) : view === "ledger" ? (
        <LedgerLeaderView />
      ) : (
        <GuideView />
      )}
    </div>
  );
}

function useLeaderBacktest() {
  return useQuery({
    queryKey: ["firstBoardLeaderBacktest"],
    queryFn: fetchFirstBoardLeaderBacktest,
    staleTime: 300_000,
  });
}

function LiveLeaderView() {
  const query = useQuery({
    queryKey: ["firstBoardLeaderLive"],
    queryFn: fetchFirstBoardLeaderLive,
    staleTime: 8_000,
    refetchInterval: (q) =>
      q.state.data?.mode === "live_snapshot"
        ? ACTIVE_LIVE_SNAPSHOT_POLL_INTERVAL_MS
        : IDLE_POLL_INTERVAL_MS,
    refetchOnWindowFocus: true,
  });
  const snapshot = query.data;
  if (query.isLoading && !snapshot) {
    return (
      <section aria-label="首板龙头实时推荐">
        <LoadingState rows={5} />
      </section>
    );
  }
  if (query.isError || !snapshot) {
    return <EmptyState text="无法加载首板龙头强度榜" />;
  }
  const leaders = snapshot.leaders ?? [];
  const stale = Boolean(snapshot.data_quality?.is_stale);
  const paused = snapshot.session_stage === "lunch";
  return (
    <section aria-label="首板龙头实时推荐">
      <div className="flex items-center justify-between gap-3 px-3 py-3 sm:px-4">
        <div className="min-w-0 text-sm">
          <span className="font-semibold text-foreground">首板龙头强度榜</span>
          <span className="ml-2 text-muted-foreground">
            按涨幅 · 距板 · 封单 · 概念龙实时排序 · 共 {leaders.length} 只
          </span>
        </div>
        {stale && <span className="shrink-0 text-xs text-amber-500">数据过期</span>}
      </div>
      {leaders.length ? (
        <div className="grid gap-3 px-3 pb-4 sm:px-4 xl:grid-cols-2">
          {leaders.map((signal) => (
            <LiveSignalCard key={signal.vt_symbol} signal={signal} stale={stale} paused={paused} />
          ))}
        </div>
      ) : (
        <EmptyState text="当前没有首板候选（盘前或全天无封板动作时为空）" />
      )}
    </section>
  );
}

function BacktestLeaderView() {
  const query = useLeaderBacktest();
  if (query.isLoading) return <LoadingState rows={4} />;
  const data = query.data;
  if (!data || data.status !== "ok" || !data.report) {
    return <EmptyState text={data?.message ?? "回测未运行"} />;
  }
  const report = data.report;
  const start = (report.coverage?.reliable_start as string | undefined) ?? "";
  const end = (report.coverage?.reliable_end as string | undefined) ?? "";
  return (
    <section aria-label="首板龙头回测">
      <div className="border-b bg-amber-500/5 px-3 py-2 text-xs text-amber-600 sm:px-4">
        ⚠️ 回测模拟（假设涨停价全成交），非实盘；实际会因买不到而打折
      </div>
      <BacktestView
        report={report}
        indexBars={[]}
        loading={false}
        start={start}
        end={end}
        onStart={() => undefined}
        onEnd={() => undefined}
        rebuildRunning={false}
        rebuildError={null}
        onRebuild={() => undefined}
      />
    </section>
  );
}

function LedgerLeaderView() {
  const query = useLeaderBacktest();
  if (query.isLoading) return <LoadingState rows={6} />;
  const data = query.data;
  const ledgerDays = data?.ledger_days ?? [];
  if (!ledgerDays.length) {
    return <EmptyState text={data?.message ?? "无交割记录"} />;
  }
  return (
    <section aria-label="首板龙头历史交割单">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-amber-500/5 px-3 py-2 text-xs text-amber-600 sm:px-4">
        <span className="eyebrow">复盘 REVIEW</span>
        <span>⚠️ 回测模拟交割单，非实盘 · 最近 {ledgerDays.length} 个交易日 · 最新在左</span>
      </div>
      <LedgerTimeline
        days={[...ledgerDays].reverse().map((ledger) => ({
          date: ledger.trade_date,
          ledger,
          loading: false,
        }))}
      />
    </section>
  );
}

function GuideView() {
  return (
    <section aria-label="首板龙头规则说明" className="px-3 py-4 text-sm sm:px-4">
      <div className="prose prose-sm max-w-none space-y-3">
        <h3 className="text-base font-semibold">首板龙头</h3>
        <p className="text-muted-foreground">
          盘中实时跟踪 9:30-11:00 首板的<strong>强度</strong>——哪只涨得最猛、最接近封板、封单最实、概念龙排名最靠前，排前面。
          这是「跟踪强度」，不是「预测龙头」（首板当天分不出龙头）。
        </p>
        <div>
          <div className="mb-1 font-semibold">实时推荐排序</div>
          <ul className="ml-4 list-disc text-muted-foreground">
            <li>涨幅（change_pct）高 → 涨得猛</li>
            <li>距涨停（distance_to_limit_pct）低 → 快封板</li>
            <li>概念龙排名（concept_leader_rank）靠前 → 板块龙头</li>
            <li>封单（seal_amount）大 → 封得实</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">回测策略（历史模拟）</div>
          <ul className="ml-4 list-disc text-muted-foreground">
            <li>每天用 3 个 D-1 因子和触板时流通市值打分选 TOP3 首板，涨停价打板买入</li>
            <li>D+1 开盘高开就拿、低开/平盘就走</li>
            <li>拿着当天涨停则减半留、不涨停收盘走</li>
            <li>4 因子：触板时流通市值、前5日涨幅、前3天上涨天数、前5日量比</li>
          </ul>
        </div>
        <div className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600">
          ⚠️ 回测假设涨停价全成交（实盘封单厚时买不到，收益会打折）；
          每日 TOP3 是完整晨盘候选的研究排序，并非实时到达顺序；D+1 用开盘价代理竞价
          （非真实集合竞价）；样本仅约 13 个月，结果不可外推。
        </div>
      </div>
    </section>
  );
}

function EmptyState({ text }: { text: string }) {
  return (
    <div className="px-3 py-10 text-center text-sm text-muted-foreground sm:px-4">{text}</div>
  );
}
