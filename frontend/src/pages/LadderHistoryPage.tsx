import { useQuery } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchLadderHistory } from "@/api/lianban";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { cn } from "@/lib/utils";
import { LadderHeatmap } from "@/pages/lianban/LadderHeatmap";
import { LeaderTrackCard } from "@/pages/lianban/LeaderTrackCard";
import { PromotionMatrixCard } from "@/pages/lianban/PromotionMatrixCard";
import { formatCnDate } from "@/pages/lianban/ReviewHeader";

/** 可选历史窗口天数（后端合法区间 [5,250]，这里只放出常用档）。 */
export const LADDER_DAY_OPTIONS = [30, 60, 120, 250] as const;

/** 默认窗口：60 日（无 ?days= 参数时的回落值）。 */
export const DEFAULT_LADDER_DAYS = 60;

/**
 * 解析 ?days= 参数：只接受 LADDER_DAY_OPTIONS 内的值；乱填/非数字 → 默认 60 日，
 * 避免把垃圾参数直接打到 API（FastAPI 越界会 422 触发整页错误）。
 */
export function parseDaysParam(raw: string | null): number {
  if (!raw) return DEFAULT_LADDER_DAYS;
  const days = Number(raw);
  return (LADDER_DAY_OPTIONS as readonly number[]).includes(days) ? days : DEFAULT_LADDER_DAYS;
}

/**
 * 连板天梯历史页（复盘页姊妹页，研究视角）：页头（天数切换 + 回链）
 * + 天梯热力矩阵（日期×板位）+ 窗口晋级率 + 最高板追踪。
 * 窗口状态走 ?days=（对齐复盘页 ?date= 惯例）；切天数用 placeholderData
 * 保留旧内容避免整页闪烁；queryKey 含 days，不同窗口独立缓存。
 */
export function LadderHistoryPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const days = parseDaysParam(searchParams.get("days"));

  const historyQuery = useQuery({
    queryKey: ["lianbanLadderHistory", days],
    queryFn: () => fetchLadderHistory(days),
    placeholderData: (previous) => previous,
  });
  const payload = historyQuery.data;

  const handleDaysChange = (nextDays: number) => {
    const next = new URLSearchParams(searchParams);
    if (nextDays === DEFAULT_LADDER_DAYS) next.delete("days");
    else next.set("days", String(nextDays));
    setSearchParams(next, { replace: true });
  };

  if (historyQuery.isLoading && !payload) return <LoadingState rows={6} />;
  if (!payload) {
    const detail =
      historyQuery.error instanceof Error ? historyQuery.error.message : null;
    return (
      <ErrorState
        message={detail ?? "天梯历史数据暂时不可用"}
        onRetry={() => void historyQuery.refetch()}
      />
    );
  }

  return (
    <div className="min-w-0 space-y-3">
      <header className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 px-3 py-2.5 sm:px-4">
          <h1 className="text-sm font-semibold text-foreground">连板天梯历史</h1>
          {payload.as_of && (
            <span className="text-xs tabular-nums text-muted-foreground">
              截至 {formatCnDate(payload.as_of)}
            </span>
          )}
          <span className="text-[11px] text-muted-foreground">
            近 {payload.days} 个涨停交易日 · 日线口径
          </span>
          <nav className="ml-auto flex items-center gap-1.5 text-xs" aria-label="历史窗口天数">
            {LADDER_DAY_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                aria-pressed={option === days}
                onClick={() => handleDaysChange(option)}
                className={cn(
                  "h-7 rounded border px-2 tabular-nums",
                  option === days
                    ? "border-primary bg-primary/10 font-medium text-primary"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {option}日
              </button>
            ))}
            <Link
              to="/lianban"
              className="flex h-7 items-center gap-0.5 rounded border px-2 text-muted-foreground hover:text-foreground"
            >
              <ChevronLeft size={13} />
              每日复盘
            </Link>
          </nav>
        </div>
      </header>
      {payload.dates.length === 0 ? (
        <EmptyState
          message="天梯历史暂缺"
          description="窗口内无涨停交易日，请检查日线重建同步"
        />
      ) : (
        <>
          <LadderHeatmap days={payload.matrix} asOf={payload.as_of} />
          <PromotionMatrixCard rows={payload.promotion_matrix} days={payload.days} />
          <LeaderTrackCard leaders={payload.leaders} />
        </>
      )}
    </div>
  );
}
