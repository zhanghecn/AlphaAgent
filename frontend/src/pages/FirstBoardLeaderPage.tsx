import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ReceiptText } from "lucide-react";

import {
  fetchFirstBoardLeaderBacktest,
  fetchFirstBoardLeaderLive,
  fetchMinuteBacktest,
  type LimitUpLaneBacktest,
} from "@/api/limitUp";
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

function useMinuteBacktest() {
  return useQuery({
    queryKey: ["leaderMinuteBacktest"],
    queryFn: fetchMinuteBacktest,
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
  const leaderQuery = useLeaderBacktest();
  const minuteQuery = useMinuteBacktest();
  const [detail, setDetail] = useState<"minute" | "leader">("minute");
  if (leaderQuery.isLoading || minuteQuery.isLoading) return <LoadingState rows={4} />;
  const leaderReport = leaderQuery.data?.status === "ok" ? leaderQuery.data.report : undefined;
  const minuteReport = minuteQuery.data?.status === "ok" ? minuteQuery.data.report : undefined;
  if (!leaderReport && !minuteReport) {
    return <EmptyState text={minuteQuery.data?.message ?? leaderQuery.data?.message ?? "回测未运行"} />;
  }
  const active = detail === "minute" ? minuteReport : leaderReport;
  const start = (active?.coverage?.reliable_start as string | undefined) ?? "";
  const end = (active?.coverage?.reliable_end as string | undefined) ?? "";
  return (
    <section aria-label="首板龙头回测">
      <CompareCard leader={leaderReport} minute={minuteReport} />
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-3 py-2 sm:px-4">
        <div className="flex rounded-lg border p-0.5 text-xs">
          {(["minute", "leader"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setDetail(key)}
              className={cn(
                "rounded-md px-3 py-1 font-medium transition-colors",
                detail === key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {key === "minute" ? "分钟级（真实可执行）" : "涨停价打板（上界）"}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">
          {detail === "minute"
            ? "开盘 10 分钟窗口 surge/累计涨幅触发 bar close 买入"
            : "假设涨停价全成交，实盘封单厚会打折"}
        </span>
      </div>
      {active ? (
        <BacktestView
          report={active}
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
      ) : (
        <EmptyState text={detail === "minute" ? "分钟级回测未运行" : "打板回测未运行"} />
      )}
    </section>
  );
}

/** 打板（乐观上界）vs 分钟级（真实可执行）4 指标对照卡。 */
function CompareCard({
  leader,
  minute,
}: {
  leader?: LimitUpLaneBacktest;
  minute?: LimitUpLaneBacktest;
}) {
  return (
    <div className="grid grid-cols-2 gap-px border-b bg-border">
      <CompareColumn title="涨停价打板" badge="乐观上界" report={leader} />
      <CompareColumn title="分钟级" badge="真实可执行" report={minute} highlight />
    </div>
  );
}

function CompareColumn({
  title,
  badge,
  report,
  highlight,
}: {
  title: string;
  badge: string;
  report?: LimitUpLaneBacktest;
  highlight?: boolean;
}) {
  const s = report?.summary;
  return (
    <div className={cn("bg-card px-3 py-3 sm:px-4", highlight && "bg-primary/5")}>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-sm font-semibold text-foreground">{title}</span>
        <span
          className={cn(
            "rounded-full px-1.5 py-px text-[10px] font-medium",
            highlight ? "bg-primary/15 text-primary" : "bg-amber-500/15 text-amber-600",
          )}
        >
          {badge}
        </span>
      </div>
      {s ? (
        <div className="grid grid-cols-2 gap-x-3 gap-y-1.5 tabular-nums">
          <CompareMetric label="复利" value={fmtPct(s.total_return_pct)} />
          <CompareMetric label="胜率" value={fmtPct(s.win_rate)} />
          <CompareMetric label="最大回撤" value={fmtPct(s.max_drawdown_pct)} />
          <CompareMetric label="笔数" value={`${s.trade_count ?? 0}`} />
        </div>
      ) : (
        <div className="text-xs text-muted-foreground">回测未运行</div>
      )}
    </div>
  );
}

function CompareMetric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className="text-sm font-semibold text-foreground">{value}</div>
    </div>
  );
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return "--";
  return `${v.toFixed(1)}%`;
}

function LedgerLeaderView() {
  const leaderQuery = useLeaderBacktest();
  const minuteQuery = useMinuteBacktest();
  const [source, setSource] = useState<"minute" | "leader">("minute");
  if (leaderQuery.isLoading || minuteQuery.isLoading) return <LoadingState rows={6} />;
  const current = source === "minute" ? minuteQuery.data : leaderQuery.data;
  const ledgerDays = current?.ledger_days ?? [];
  return (
    <section aria-label="首板龙头历史交割单">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-amber-500/5 px-3 py-2 text-xs text-amber-600 sm:px-4">
        <span className="eyebrow">复盘 REVIEW</span>
        <span>⚠️ 回测模拟交割单，非实盘 · 最近 {ledgerDays.length} 个交易日 · 最新在左</span>
        <div className="ml-auto flex rounded-lg border p-0.5">
          {(["minute", "leader"] as const).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setSource(key)}
              className={cn(
                "rounded-md px-2.5 py-0.5 font-medium transition-colors",
                source === key
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {key === "minute" ? "分钟级" : "打板"}
            </button>
          ))}
        </div>
      </div>
      {ledgerDays.length ? (
        <LedgerTimeline
          days={[...ledgerDays].reverse().map((ledger) => ({
            date: ledger.trade_date,
            ledger,
            loading: false,
          }))}
        />
      ) : (
        <EmptyState text={current?.message ?? "无交割记录"} />
      )}
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
