import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Activity, BarChart3, BookOpenText, ClipboardList, ReceiptText } from "lucide-react";

import {
  fetchFirstBoardLeaderForwardLedger,
  fetchFirstBoardLeaderLive,
  fetchMinuteBacktest,
  fetchSweepBacktest,
  type LimitUpLaneBacktest,
  type LimitUpLiveSignal,
} from "@/api/limitUp";
import { LoadingState } from "@/components/LoadingState";
import { LedgerTimeline } from "@/features/limitUp/LedgerTimeline";
import { LiveSignalCard } from "@/features/limitUp/LiveSignalCard";
import { PremarketCandidatesPanel } from "@/features/limitUp/PremarketCandidatesPanel";
import { FusedScoreCandidatesPanel } from "@/features/limitUp/FusedScoreCandidatesPanel";
import { ACTIVE_LIVE_SNAPSHOT_POLL_INTERVAL_MS } from "@/features/limitUp/nextSessionPlan";
import { BacktestView } from "@/pages/LimitUpPage";
import { cn } from "@/lib/utils";

type LeaderView = "live" | "backtest" | "ledger" | "forward" | "guide";

const LEADER_VIEWS: { value: LeaderView; label: string; icon: typeof Activity }[] = [
  { value: "live", label: "实时推荐", icon: Activity },
  { value: "backtest", label: "回测", icon: BarChart3 },
  { value: "ledger", label: "历史交割单", icon: ReceiptText },
  { value: "forward", label: "前向台账", icon: ClipboardList },
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
        aria-label="潜龙首板视图"
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
      ) : view === "forward" ? (
        <ForwardLedgerView />
      ) : (
        <GuideView />
      )}
    </div>
  );
}

function useSweepBacktest() {
  return useQuery({
    queryKey: ["leaderSweepBacktest"],
    queryFn: fetchSweepBacktest,
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
      <section aria-label="潜龙首板实时推荐">
        <LoadingState rows={5} />
      </section>
    );
  }
  if (query.isError || !snapshot) {
    return <EmptyState text="无法加载潜龙首板强度榜" />;
  }
  const leaders = snapshot.leaders ?? [];
  const stale = Boolean(snapshot.data_quality?.is_stale);
  const paused = snapshot.session_stage === "lunch";
  const temperature = snapshot.market_temperature;
  return (
    <section aria-label="潜龙首板实时推荐">
      <div className="flex items-center justify-between gap-3 px-3 py-3 sm:px-4">
        <div className="min-w-0 text-sm">
          <span className="font-semibold text-foreground">潜龙首板强度榜</span>
          <span className="ml-2 text-muted-foreground">
            潜力分（白名单因子）优先 · 共 {leaders.length} 只
          </span>
          {temperature?.available && (
            <span
              className={cn(
                "ml-2 rounded-full px-1.5 py-px text-[10px] font-medium",
                temperature.level === "cold"
                  ? "bg-emerald-500/15 text-emerald-600"
                  : temperature.level === "hot"
                    ? "bg-red-500/15 text-red-600"
                    : "bg-muted text-muted-foreground",
              )}
              title="昨日全市场首板数（滞后温度，仅展示不做硬门）"
            >
              温度·{temperature.level === "cold" ? "冰点" : temperature.level === "hot" ? "高潮" : "中性"}{" "}
              {temperature.lag1_first_board_count}
            </span>
          )}
        </div>
        {stale && <span className="shrink-0 text-xs text-amber-500">数据过期</span>}
      </div>
      <PremarketCandidatesPanel />
      <FusedScoreCandidatesPanel />
      {leaders.length ? (
        <div className="grid gap-3 px-3 pb-4 sm:px-4 xl:grid-cols-2">
          {leaders.map((signal) => (
            <div key={signal.vt_symbol} className="min-w-0">
              <LeaderScoreStrip signal={signal} />
              <LiveSignalCard signal={signal} stale={stale} paused={paused} />
            </div>
          ))}
        </div>
      ) : (
        <EmptyState text="当前没有首板候选（盘前或全天无封板动作时为空）" />
      )}
    </section>
  );
}

/** 潜力分条：白名单因子分位加权 + 封板质量 + 尾盘/撤单预警（不动共享卡片）。 */
function LeaderScoreStrip({ signal }: { signal: LimitUpLiveSignal }) {
  const score = signal.potential_score;
  if (score == null) return null;
  const percent = Math.round(score * 100);
  const topFactors = Object.entries(signal.factor_percentiles ?? {})
    .filter(([key]) => key !== "seal_to_turnover_ratio")
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([key]) => FACTOR_LABELS[key] ?? key);
  return (
    <div className="mb-1 flex items-center gap-2 px-1 text-xs tabular-nums">
      <span
        className={cn(
          "font-mono text-base font-bold",
          percent >= 70 ? "text-primary" : percent >= 40 ? "text-foreground" : "text-muted-foreground",
        )}
      >
        {percent}
      </span>
      <span className="text-muted-foreground">潜力分</span>
      {topFactors.length > 0 && (
        <span className="truncate text-muted-foreground">· {topFactors.join(" / ")}</span>
      )}
      <span className="ml-auto flex shrink-0 gap-1">
        {signal.late_seal && (
          <span className="rounded-full bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-600">
            尾盘板
          </span>
        )}
        {signal.seal_weakening && (
          <span className="rounded-full bg-red-500/15 px-1.5 py-px text-[10px] font-medium text-red-600">
            撤单预警
          </span>
        )}
      </span>
    </div>
  );
}

const FACTOR_LABELS: Record<string, string> = {
  concept_max_return_20d: "板块动量",
  volume_ratio_5_60: "量能",
  drawdown_from_126d_high_pct: "半年位置",
  position_126d: "区间位置",
  prior_return_20d_pct: "20日动量",
  prior_return_5d_pct: "5日动量",
  seal_to_turnover_ratio: "封单比",
};

function BacktestLeaderView() {
  const sweepQuery = useSweepBacktest();
  const minuteQuery = useMinuteBacktest();
  const [detail, setDetail] = useState<"minute" | "sweep">("minute");
  if (sweepQuery.isLoading || minuteQuery.isLoading) return <LoadingState rows={4} />;
  const sweepReport = sweepQuery.data?.status === "ok" ? sweepQuery.data.report : undefined;
  const minuteReport = minuteQuery.data?.status === "ok" ? minuteQuery.data.report : undefined;
  if (!sweepReport && !minuteReport) {
    return <EmptyState text={minuteQuery.data?.message ?? sweepQuery.data?.message ?? "回测未运行"} />;
  }
  const active = detail === "minute" ? minuteReport : sweepReport;
  const start = (active?.coverage?.reliable_start as string | undefined) ?? "";
  const end = (active?.coverage?.reliable_end as string | undefined) ?? "";
  return (
    <section aria-label="潜龙首板回测">
      <CompareCard sweep={sweepReport} minute={minuteReport} />
      <div className="flex flex-wrap items-center justify-between gap-3 border-b px-3 py-2 sm:px-4">
        <div className="flex rounded-lg border p-0.5 text-xs">
          {(["minute", "sweep"] as const).map((key) => (
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
              {key === "minute" ? "分钟级（动量触发）" : "扫板（开板排板成交）"}
            </button>
          ))}
        </div>
        <span className="text-xs text-muted-foreground">
          {detail === "minute"
            ? "9:31-9:40 surge/累计触发 · 量能过滤 · 仅宽覆盖日 · 无未来函数"
            : "白名单因子共用 · 触板后开板按涨停价排板成交 · 全天未开板=买不到"}
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

/** 扫板（开板排板成交）vs 分钟级（动量触发）4 指标对照卡。 */
function CompareCard({
  sweep,
  minute,
}: {
  sweep?: LimitUpLaneBacktest;
  minute?: LimitUpLaneBacktest;
}) {
  return (
    <div className="grid grid-cols-2 gap-px border-b bg-border">
      <CompareColumn title="扫板" badge="开板排板成交" report={sweep} />
      <CompareColumn title="分钟级" badge="全市场·无未来函数" report={minute} highlight />
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
  const sweepQuery = useSweepBacktest();
  const minuteQuery = useMinuteBacktest();
  const [source, setSource] = useState<"minute" | "sweep">("minute");
  if (sweepQuery.isLoading || minuteQuery.isLoading) return <LoadingState rows={6} />;
  const current = source === "minute" ? minuteQuery.data : sweepQuery.data;
  const ledgerDays = current?.ledger_days ?? [];
  return (
    <section aria-label="潜龙首板历史交割单">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-amber-500/5 px-3 py-2 text-xs text-amber-600 sm:px-4">
        <span className="eyebrow">复盘 REVIEW</span>
        <span>⚠️ 回测模拟交割单，非实盘 · 最近 {ledgerDays.length} 个交易日 · 最新在左</span>
        <div className="ml-auto flex rounded-lg border p-0.5">
          {(["minute", "sweep"] as const).map((key) => (
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
              {key === "minute" ? "分钟级" : "扫板"}
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

/** 前向纸面台账（Phase 3 强制门）：周度胜率/封板率 vs 回测预期 + 最近信号。 */
function ForwardLedgerView() {
  const query = useQuery({
    queryKey: ["firstBoardLeaderForwardLedger"],
    queryFn: () => fetchFirstBoardLeaderForwardLedger(8),
    staleTime: 300_000,
  });
  const report = query.data;
  if (query.isLoading && !report) return <LoadingState rows={5} />;
  if (query.isError || !report) return <EmptyState text="无法加载前向台账" />;
  const reference = report.backtest_reference ?? {};
  return (
    <section aria-label="潜龙首板前向台账">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b bg-primary/5 px-3 py-2 text-xs text-muted-foreground sm:px-4">
        <span className="eyebrow">前向 FORWARD</span>
        <span>
          纸面跟踪非实盘 · 每日 10:05/15:05 捕获推荐榜 · T+1 开盘结算（口径 = D+1开盘/D收盘-1 未扣费）
        </span>
        <span className="ml-auto font-mono">
          回测预期：胜率 {fmtPct(reference.win_rate)} / 均笔 {fmtPct(reference.average_return_pct)}
        </span>
      </div>
      {report.weeks.length ? (
        <div className="overflow-x-auto px-3 py-3 sm:px-4">
          <table className="w-full min-w-[560px] text-sm tabular-nums">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-1.5 font-medium">周</th>
                <th className="font-medium">信号</th>
                <th className="font-medium">已结算</th>
                <th className="font-medium">胜率</th>
                <th className="font-medium">均D+1开盘</th>
                <th className="font-medium">封板率</th>
              </tr>
            </thead>
            <tbody>
              {report.weeks.map((week) => (
                <tr key={week.week} className="border-b last:border-0">
                  <td className="py-1.5 font-medium">{week.week}</td>
                  <td>{week.signals}</td>
                  <td>{week.settled}</td>
                  <td
                    className={cn(
                      "font-semibold",
                      (week.win_rate ?? 0) >= (reference.win_rate ?? 0)
                        ? "text-emerald-600"
                        : "text-amber-600",
                    )}
                  >
                    {fmtPct(week.win_rate)}
                  </td>
                  <td>{fmtPct(week.avg_d1_open_return_pct)}</td>
                  <td>{fmtPct(week.seal_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState text="前向台账暂无数据（每日 10:05/15:05 自动捕获盘中推荐）" />
      )}
      {report.recent.length > 0 && (
        <div className="px-3 pb-4 sm:px-4">
          <div className="mb-1.5 text-xs font-semibold text-muted-foreground">最近信号</div>
          <div className="grid gap-1.5">
            {report.recent.slice(0, 20).map((row) => (
              <div
                key={`${row.trade_date}-${row.vt_symbol}`}
                className="flex items-center gap-2 rounded border px-2.5 py-1.5 text-xs tabular-nums"
              >
                <span className="text-muted-foreground">{row.trade_date.slice(5)}</span>
                <span className="font-medium">{row.name ?? row.vt_symbol}</span>
                {row.potential_score != null && (
                  <span className="font-mono text-primary">{Math.round(row.potential_score * 100)}</span>
                )}
                {row.late_seal && (
                  <span className="rounded-full bg-amber-500/15 px-1.5 text-[10px] text-amber-600">尾盘</span>
                )}
                {row.seal_weakening && (
                  <span className="rounded-full bg-red-500/15 px-1.5 text-[10px] text-red-600">撤单</span>
                )}
                <span className="ml-auto font-mono">
                  {row.settled ? (
                    <span className={row.is_win ? "text-emerald-600" : "text-red-600"}>
                      {fmtPct(row.d1_open_return_pct)}
                    </span>
                  ) : (
                    <span className="text-muted-foreground">待结算</span>
                  )}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function GuideView() {
  return (
    <section aria-label="潜龙首板规则说明" className="px-3 py-4 text-sm sm:px-4">
      <div className="prose prose-sm max-w-none space-y-3">
        <h3 className="text-base font-semibold">潜龙首板</h3>
        <p className="text-muted-foreground">
          盘中实时跟踪 9:30-11:00 首板的<strong>强度</strong>——哪只涨得最猛、最接近封板、封单最实、概念龙排名最靠前，排前面。
          这是「跟踪强度」，不是「预测龙头」（首板当天分不出龙头）。
        </p>
        <div>
          <div className="mb-1 font-semibold">实时推荐排序（潜力分 v2）</div>
          <ul className="ml-4 list-disc text-muted-foreground">
            <li>潜力分 = Phase 0 稳定性门白名单因子的当日横截面分位加权：板块20日动量 0.30 / 量能 0.15 / 半年位置族合计 0.40（回撤+区间位置+20日/5日动量）</li>
            <li>封板质量 0.15：实时封单比分位（封板瞬间可观测，非未来函数）；封单保持率 &lt; 0.7 触发撤单预警并扣分</li>
            <li>尾盘降权：14:00 后封板标记「尾盘板」且潜力分减半（历史 D+1 溢价最差）</li>
            <li>市场温度徽章：昨日全市场首板数（≤32 冰点 / ≥69 高潮）——仅展示，未过稳定性门不做硬门</li>
          </ul>
        </div>
        <div>
          <div className="mb-1 font-semibold">回测策略（历史模拟）</div>
          <ul className="ml-4 list-disc text-muted-foreground">
            <li>扫板：与分钟级共用白名单因子与深跌排除，但不用分钟触发条件——盘中触板后若开板（炸板），按涨停价排板成交；全天未开板=买不到（真实打板机制）</li>
            <li>分钟级（无未来函数）：universe=当日有分钟数据的全市场主板非ST股，9:31-9:40 内 surge≥2% 或累计≥7% 按触发 bar close 买入</li>
            <li>封板/一字用价格可观测判断（触发时 bar close≥涨停价或开盘≥涨停价则跳过），不用事后涨停数据</li>
            <li>v4-B 配置：白名单 6 因子 + 深跌排除（20日跌≤-8.5% 或距半年高点≤-21% 排除，板块20日≥+16.5% 豁免）——A/B 两档口径唯一都赢 v3 的版本</li>
            <li>D+1 开盘高开就拿、低开/平盘就走、涨停减半留</li>
          </ul>
        </div>
        <div className="rounded border border-amber-500/40 bg-amber-500/5 p-3 text-xs text-amber-600">
          ⚠️ 分钟级回测只在「当日分钟数据覆盖≥600票」的宽覆盖日交易（稀疏日多为事件票回填、有覆盖偏差，
          整日跳过），样本窗口有限；宽覆盖日的未覆盖票（约 2/3）中的触发被漏掉，覆盖偏活跃股。
          打板回测假设涨停价全成交（上界）；样本有限，结果不可外推。
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
