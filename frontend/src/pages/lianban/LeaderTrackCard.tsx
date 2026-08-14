import type { LadderLeaderDay } from "@/api/lianban";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { formatShortDate } from "./ReviewStatsCards";

/** 连续在位区间：同一只龙头（vt_symbol）连续多日为最高板时合并成一行。 */
export interface LeaderRun {
  vtSymbol: string;
  name: string;
  startDate: string;
  endDate: string;
  startStreak: number;
  endStreak: number;
  days: number;
  /** 区间内任一日为一字板即标记 */
  isOneWord: boolean;
}

/**
 * 每日最高板龙头合并为「连续在位」区间：先按日期升序，相邻同一只（vt_symbol）
 * 合并为一行（板数取首末，如 百花医药 08-11~08-12 6→7板），换龙头即断开；
 * 输出按区间末日降序（最新在上）。不改原数组。
 */
export function mergeLeaderRuns(leaders: LadderLeaderDay[]): LeaderRun[] {
  const ascending = [...leaders].sort((a, b) =>
    a.trade_date < b.trade_date ? -1 : a.trade_date > b.trade_date ? 1 : 0,
  );
  const runs: LeaderRun[] = [];
  for (const leader of ascending) {
    const last = runs[runs.length - 1];
    if (last && last.vtSymbol === leader.vt_symbol) {
      last.endDate = leader.trade_date;
      last.endStreak = leader.streak;
      last.days += 1;
      last.isOneWord = last.isOneWord || Boolean(leader.is_one_word);
      if (leader.name) last.name = leader.name;
    } else {
      runs.push({
        vtSymbol: leader.vt_symbol,
        name: leader.name,
        startDate: leader.trade_date,
        endDate: leader.trade_date,
        startStreak: leader.streak,
        endStreak: leader.streak,
        days: 1,
        isOneWord: Boolean(leader.is_one_word),
      });
    }
  }
  return runs.sort((a, b) => (a.endDate < b.endDate ? 1 : a.endDate > b.endDate ? -1 : 0));
}

/** 区间日期标签：单日 "08-13"；多日 "08-11~08-12"。 */
export function leaderRunDateLabel(run: LeaderRun): string {
  if (run.startDate === run.endDate) return formatShortDate(run.endDate);
  return `${formatShortDate(run.startDate)}~${formatShortDate(run.endDate)}`;
}

/** 板数标签：单日/板数不变 "5板"；区间推进 "6→7板"。 */
export function leaderRunStreakLabel(run: LeaderRun): string {
  if (run.startStreak === run.endStreak) return `${run.endStreak}板`;
  return `${run.startStreak}→${run.endStreak}板`;
}

interface LeaderTrackCardProps {
  leaders: LadderLeaderDay[];
}

/**
 * 最高板追踪：近 N 日每日龙头（日期/区间 + 名称链接 + 板数徽标 + 一字标记），
 * 按日期降序；连续同一只合并为区间行，减少重复行。
 */
export function LeaderTrackCard({ leaders }: LeaderTrackCardProps) {
  const runs = mergeLeaderRuns(leaders);
  return (
    <section aria-label="最高板追踪" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">最高板追踪</h2>
        <span className="text-[11px] text-muted-foreground">
          每日最高板龙头 · 连续在位合并显示
        </span>
      </header>
      {runs.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          窗口内无最高板记录
        </div>
      ) : (
        <div className="divide-y divide-border/50 px-1 py-1 sm:px-2">
          {runs.map((run) => (
            <div
              key={`${run.vtSymbol}-${run.startDate}`}
              className="flex min-w-0 items-center gap-2 px-2 py-1.5 sm:px-3"
            >
              <span className="w-24 shrink-0 text-xs tabular-nums text-muted-foreground">
                {leaderRunDateLabel(run)}
              </span>
              <StockIdentityLink
                name={run.name}
                vtSymbol={run.vtSymbol}
                className="min-w-0 flex-1"
              />
              {run.days > 1 && (
                <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground">
                  {run.days}天
                </span>
              )}
              <span className="shrink-0 rounded-full bg-rise/10 px-1.5 py-px text-[10px] font-medium tabular-nums text-rise">
                {leaderRunStreakLabel(run)}
              </span>
              {run.isOneWord && (
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-px text-[10px] font-medium text-muted-foreground">
                  一字
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
