import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { fetchLianbanDates, fetchLianbanProjection, fetchLianbanReview } from "@/api/lianban";
import type { LianbanReview } from "@/api/lianban";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { BrokenBoardsSection } from "@/pages/lianban/BrokenBoardsSection";
import { HotLeadersSection } from "@/pages/lianban/HotLeadersSection";
import { LadderSection } from "@/pages/lianban/LadderSection";
import { ProjectionCard } from "@/pages/lianban/ProjectionCard";
import { RelaySection } from "@/pages/lianban/RelaySection";
import { ReviewFaqSection } from "@/pages/lianban/ReviewFaqSection";
import { adjacentDates, ReviewHeader } from "@/pages/lianban/ReviewHeader";
import { ReviewStatsCards } from "@/pages/lianban/ReviewStatsCards";
import { ThemeGroupsSection } from "@/pages/lianban/ThemeGroupsSection";

/** live 模式（盘中滚动）轮询间隔，对齐首板页 30s 节奏；final/rebuild 不轮询。 */
export const LIANBAN_LIVE_REFETCH_INTERVAL_MS = 30_000;

/** ?date= 参数合法形状：YYYY-MM-DD（月 01-12、日 01-31；2 月 30 日等交由 API 报错兜底）。 */
const DATE_PARAM_PATTERN = /^\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])$/;

/**
 * 解析 ?date= 参数：合法 ISO 形状原样透传；乱填/非日期 → undefined（回落最新复盘），
 * 避免把垃圾参数直接打到 API 触发整页错误。
 */
export function parseDateParam(raw: string | null): string | undefined {
  if (!raw) return undefined;
  return DATE_PARAM_PATTERN.test(raw) ? raw : undefined;
}

/** 轮询条件：仅 live（盘中滚动）模式 30s 轮询；收盘定版/历史归档/无数据不刷新。 */
export function reviewRefetchInterval(data: LianbanReview | undefined): number | false {
  return data?.mode === "live" ? LIANBAN_LIVE_REFETCH_INTERVAL_MS : false;
}

interface ArchiveNavProps {
  /** 可复盘交易日（任意顺序，adjacentDates 内部自行排序） */
  dates: string[];
  /** 当前展示的 trade_date（可以不在 dates 内，如 live 当日尚未归档） */
  currentDate: string;
  onDateChange: (date: string | undefined) => void;
}

/**
 * 底部归档导航：「← {prev_date} 复盘」/「{next_date} 复盘 →」，与 ReviewHeader
 * 的翻页共用 adjacentDates 口径；无更早/已是最新时降级为不可点文案。
 */
export function ArchiveNav({ dates, currentDate, onDateChange }: ArchiveNavProps) {
  const { prev, next } = adjacentDates(dates, currentDate);
  return (
    <nav
      aria-label="复盘归档导航"
      className="flex items-center justify-between gap-2 rounded-lg border px-3 py-2.5 text-xs sm:px-4"
    >
      {prev ? (
        <button
          type="button"
          onClick={() => onDateChange(prev)}
          className="flex items-center gap-0.5 tabular-nums text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft size={13} />
          {prev} 复盘
        </button>
      ) : (
        <span className="tabular-nums text-muted-foreground/50">无更早复盘</span>
      )}
      {next ? (
        <button
          type="button"
          onClick={() => onDateChange(next)}
          className="flex items-center gap-0.5 tabular-nums text-muted-foreground hover:text-foreground"
        >
          {next} 复盘
          <ChevronRight size={13} />
        </button>
      ) : (
        <span className="tabular-nums text-muted-foreground/50">已是最新</span>
      )}
    </nav>
  );
}

/**
 * 连板复盘页：页头（指数条 + 日期导航）+ 统计卡 + 连板天梯
 * + 梯队接力 + 炸板列表 + 热点题材 + 人气龙头榜 + FAQ + 归档导航。
 * 日期状态走 ?date=（对齐 ShortTermResearchPage 的 tab 参数惯例），无参数 = 最新复盘。
 * 切日期用 placeholderData 保留旧页内容避免整页闪烁；轮询失败保留旧数据 + 顶部小字提示。
 */
export function LianbanReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const dateParam = parseDateParam(searchParams.get("date"));

  const datesQuery = useQuery({
    queryKey: ["lianbanDates"],
    queryFn: fetchLianbanDates,
    staleTime: 300_000,
  });
  const reviewQuery = useQuery({
    queryKey: ["lianbanReview", dateParam],
    queryFn: () => fetchLianbanReview(dateParam),
    refetchInterval: (query) => reviewRefetchInterval(query.state.data),
    // 切日期/轮询期间保留上一份数据，避免整页 Loading 闪烁（react-query v5 口径）。
    placeholderData: (previous) => previous,
  });
  const payload = reviewQuery.data;

  // 明日推演（同景统计）：跟随复盘页 ?date=；后端 60s 缓存，60s staleTime 对齐。
  // 辅助卡，加载/失败都不阻塞主内容（placeholderData 保旧值防闪烁）。
  const projectionQuery = useQuery({
    queryKey: ["lianbanProjection", dateParam],
    queryFn: () => fetchLianbanProjection(dateParam),
    staleTime: 60_000,
    placeholderData: (previous) => previous,
  });

  const handleDateChange = (date: string | undefined) => {
    const next = new URLSearchParams(searchParams);
    if (date) next.set("date", date);
    else next.delete("date");
    setSearchParams(next, { replace: true });
  };

  if (reviewQuery.isLoading && !payload) return <LoadingState rows={6} />;
  // 有旧数据时即使最近一次刷新失败也保持显示（顶部小字提示）；无数据才整页错误。
  if (!payload) {
    // 优先透传后端错误文案（如「复盘数据不存在: 2026-08-09(无涨停池归档且无日线重建)」）。
    const detail =
      reviewQuery.error instanceof Error ? reviewQuery.error.message : null;
    return (
      <ErrorState
        message={detail ?? "连板复盘数据暂时不可用"}
        onRetry={() => void reviewQuery.refetch()}
      />
    );
  }

  return (
    <div className="min-w-0 space-y-3">
      {reviewQuery.isError && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-1.5 text-[11px] text-amber-600 sm:px-4">
          最新一次刷新失败，当前展示最近一次成功数据
          <button
            type="button"
            onClick={() => void reviewQuery.refetch()}
            className="ml-1 underline hover:text-amber-700"
          >
            重试
          </button>
        </p>
      )}
      <ReviewHeader
        review={payload}
        dates={datesQuery.data?.dates ?? []}
        selectedDate={dateParam}
        onDateChange={handleDateChange}
        liveFetchedAt={reviewQuery.dataUpdatedAt}
      />
      <ReviewStatsCards stats={payload.stats} />
      {projectionQuery.data && (
        <ProjectionCard projection={projectionQuery.data} reviewDate={payload.trade_date} />
      )}
      <LadderSection ladder={payload.ladder} promotion={payload.promotion} />
      <RelaySection relay={payload.relay} />
      <BrokenBoardsSection items={payload.broken_list} />
      <ThemeGroupsSection themes={payload.themes} />
      <HotLeadersSection hotLeaders={payload.hot_leaders} />
      <ReviewFaqSection review={payload} />
      <ArchiveNav
        dates={datesQuery.data?.dates ?? []}
        currentDate={payload.trade_date}
        onDateChange={handleDateChange}
      />
    </div>
  );
}
