import { ChevronLeft, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";

import type { LianbanReview } from "@/api/lianban";
import { cn, formatPct, priceColorClass } from "@/lib/utils";

type ReviewMode = LianbanReview["mode"];

interface ReviewHeaderProps {
  review: LianbanReview;
  /** 可复盘交易日（降序，来自 /lianban/dates） */
  dates: string[];
  /** 当前 ?date= 参数；undefined 表示最新复盘 */
  selectedDate: string | undefined;
  onDateChange: (date: string | undefined) => void;
  /** live 模式下最近一次成功拉取时间（query.dataUpdatedAt），仅用于展示刷新时刻 */
  liveFetchedAt?: number;
}

interface ModeBadge {
  label: string;
  className: string;
  title?: string;
}

/** 复盘模式徽标：live 盘中滚动 / final 收盘定版 / rebuild 历史归档。 */
export function reviewModeBadge(mode: ReviewMode): ModeBadge {
  if (mode === "live") {
    return {
      label: "盘中滚动 · 未定版",
      className: "bg-amber-500/15 text-amber-600",
      title: "盘中数据随行情滚动更新，封板/炸板等口径以收盘定版为准",
    };
  }
  if (mode === "rebuild") {
    return {
      label: "历史归档(日线口径)",
      className: "bg-primary/10 text-primary",
      title: "历史归档按日线口径重建，盘口字段（首次封板时间、封单额、开板次数等）缺失",
    };
  }
  return { label: "已收盘定版", className: "bg-emerald-500/15 text-emerald-600" };
}

/** "2026-08-13" → "2026年8月13日"；非 ISO 格式原样返回。 */
export function formatCnDate(tradeDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(tradeDate);
  if (!match) return tradeDate;
  return `${Number(match[1])}年${Number(match[2])}月${Number(match[3])}日`;
}

/**
 * 前一/后一交易日导航。dates 为可复盘交易日（任意顺序，内部自行排序），
 * current 为当前展示的 trade_date（可以不在 dates 内，如 live 当日尚未归档）。
 * prev = 最近的更旧交易日；next = 最近的更新交易日（current 已最新时为 null）。
 */
export function adjacentDates(
  dates: string[],
  current: string,
): { prev: string | null; next: string | null } {
  const sortedDesc = [...new Set(dates)].sort((a, b) => (a < b ? 1 : -1));
  const older = sortedDesc.filter((d) => d < current);
  const newer = sortedDesc.filter((d) => d > current);
  return { prev: older[0] ?? null, next: newer[newer.length - 1] ?? null };
}

/** live 拉取时刻 → "15:05:09"（Asia/Shanghai，对齐首板页口径）。 */
export function formatClockTime(ms: number): string {
  const date = new Date(ms);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(date);
}

/** 复盘页页头：日期标题 + 模式徽标 + 六指数条 + 日期导航。 */
export function ReviewHeader({
  review,
  dates,
  selectedDate,
  onDateChange,
  liveFetchedAt,
}: ReviewHeaderProps) {
  const badge = reviewModeBadge(review.mode);
  const { prev, next } = adjacentDates(dates, review.trade_date);
  const showLiveClock = review.mode === "live" && liveFetchedAt != null && liveFetchedAt > 0;

  return (
    <header className="rounded-lg border">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h1 className="text-sm font-semibold text-foreground">
          {formatCnDate(review.trade_date)} A股复盘
        </h1>
        <span className="text-xs text-muted-foreground">{review.weekday}</span>
        <span
          className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", badge.className)}
          title={badge.title}
        >
          {badge.label}
        </span>
        {review.data_quality.fallback_from && (
          <span className="text-[11px] text-amber-600">
            今日暂无数据，已展示最近交易日 {review.data_quality.fallback_from}
          </span>
        )}
        {showLiveClock && (
          <span className="tabular-nums text-[11px] text-muted-foreground">
            {formatClockTime(liveFetchedAt)} 更新 · 30s 轮询
          </span>
        )}
        <Link
          to="/lianban/ladder"
          className="flex h-7 items-center gap-0.5 rounded border px-2 text-xs text-muted-foreground hover:text-foreground"
        >
          天梯历史
          <ChevronRight size={13} />
        </Link>
        <nav className="ml-auto flex items-center gap-1.5 text-xs" aria-label="复盘日期导航">
          <button
            type="button"
            disabled={!prev}
            onClick={() => prev && onDateChange(prev)}
            className="flex h-7 items-center gap-0.5 rounded border px-2 tabular-nums text-muted-foreground enabled:hover:text-foreground disabled:opacity-40"
          >
            <ChevronLeft size={13} />
            {prev ?? "无更早"}
          </button>
          <select
            aria-label="选择复盘交易日"
            value={selectedDate ?? ""}
            onChange={(event) => onDateChange(event.target.value || undefined)}
            className="h-7 max-w-40 border bg-background px-2 text-xs text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">最新复盘</option>
            {/* 手动 ?date= 填了未归档的合法日期：动态补 option，避免下拉框显空 */}
            {selectedDate && !dates.includes(selectedDate) && (
              <option value={selectedDate}>{selectedDate}</option>
            )}
            {dates.map((date) => (
              <option key={date} value={date}>{date}</option>
            ))}
          </select>
          <button
            type="button"
            disabled={!next}
            onClick={() => next && onDateChange(next)}
            title={next ? undefined : "已是最新"}
            className="flex h-7 items-center gap-0.5 rounded border px-2 tabular-nums text-muted-foreground enabled:hover:text-foreground disabled:opacity-40"
          >
            {next ?? "已是最新"}
            <ChevronRight size={13} />
          </button>
        </nav>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-xs sm:px-4">
        {review.indices.length === 0 ? (
          <span className="text-muted-foreground">指数行情暂无数据</span>
        ) : (
          review.indices.map((index) => (
            <span key={index.key} className="flex items-center gap-1">
              <span className="text-muted-foreground">{index.name}</span>
              <span
                className={cn(
                  "tabular-nums font-medium",
                  index.change_pct == null ? "text-muted-foreground" : priceColorClass(index.change_pct),
                )}
              >
                {formatPct(index.change_pct)}
              </span>
            </span>
          ))
        )}
      </div>
    </header>
  );
}
