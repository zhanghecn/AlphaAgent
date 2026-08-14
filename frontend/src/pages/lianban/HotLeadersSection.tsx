import { Link } from "react-router-dom";

import type { LianbanReview } from "@/api/lianban";
import { cn, priceColorClass } from "@/lib/utils";
import { formatPctPoint } from "./ReviewStatsCards";

type HotLeaders = LianbanReview["hot_leaders"];
type HotItem = HotLeaders["items"][number];

/** 人气龙头榜只展示 Top10。 */
export const HOT_LEADERS_TOP_N = 10;

// ===== 派生纯函数 =====

/** 连板徽标：n>=2 →「N板」（红徽标）；n==1 →「首板」；0/null → null（不显示）。 */
export function hotStreakBadge(count: number | null): string | null {
  if (count == null || count <= 0) return null;
  return count >= 2 ? `${count}板` : "首板";
}

/** 关键词只取前 2 个（空串剔除）；null/undefined → []。 */
export function visibleKeywords(keywords: string[] | null | undefined): string[] {
  return (keywords ?? []).filter((keyword) => keyword?.trim()).slice(0, 2);
}

/** 榜次升序（null 最后）+ Top10 截断；防御性重排，不改原数组。 */
export function topHotItems(items: HotItem[]): HotItem[] {
  return [...items]
    .sort((a, b) => (a.rank ?? Number.MAX_SAFE_INTEGER) - (b.rank ?? Number.MAX_SAFE_INTEGER))
    .slice(0, HOT_LEADERS_TOP_N);
}

/** ISO 日期时间前缀（YYYY-MM-DDTHH:MM:SS，19 位），用于截断时区串的回退解析。 */
const ISO_PREFIX_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/;

/**
 * 解析人气榜快照时间：直解失败时回退「前 19 位 + Z」按 UTC 解析——
 * 后端 rank_time 真实形态可能是时区被截断的 30 字符串（如
 * "2026-08-13T06:30:17.195234+00:"），new Date() 直解为 Invalid Date。
 * 两条路径都失败 → null（调用方原样上屏）。
 */
function parseHotAsOf(asOf: string): Date | null {
  const direct = new Date(asOf);
  if (!Number.isNaN(direct.getTime())) return direct;
  const prefix = asOf.slice(0, 19);
  if (!ISO_PREFIX_PATTERN.test(prefix)) return null;
  const fallback = new Date(`${prefix}Z`);
  return Number.isNaN(fallback.getTime()) ? null : fallback;
}

/**
 * 人气榜快照时间 → "08-13 14:30"（Asia/Shanghai，对齐复盘页 formatClockTime 口径）。
 * null/空串 → null（头部省略小字）；完全非 ISO 串 → 原样返回。
 */
export function formatHotAsOf(asOf: string | null | undefined): string | null {
  if (!asOf) return null;
  const date = parseHotAsOf(asOf);
  if (!date) return asOf;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  return `${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
}

// ===== 组件 =====

interface HotLeadersSectionProps {
  hotLeaders: HotLeaders;
}

/**
 * 人气龙头榜：人气 × 连板 × 涨幅的 Top10 榜单。
 * items 为空降级为内联空态；as_of 为 null 时头部小字省略。
 */
export function HotLeadersSection({ hotLeaders }: HotLeadersSectionProps) {
  const items = topHotItems(hotLeaders.items);
  const asOf = formatHotAsOf(hotLeaders.as_of);

  return (
    <section aria-label="人气龙头榜" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">人气龙头榜</h2>
        <span className="text-[11px] text-muted-foreground">人气 · 连板 · 涨幅</span>
        {asOf && (
          <span className="text-[11px] tabular-nums text-muted-foreground">{asOf} 更新</span>
        )}
      </header>
      {items.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          人气榜数据暂缺
        </div>
      ) : (
        <div className="divide-y">
          {items.map((item, index) => (
            <HotLeaderRow key={item.vt_symbol} item={item} fallbackRank={index + 1} />
          ))}
        </div>
      )}
    </section>
  );
}

/** 榜单行：榜次（mono）+ 名称 + 关键词标签（前 2 个）+ 连板徽标 + 涨幅。 */
function HotLeaderRow({ item, fallbackRank }: { item: HotItem; fallbackRank: number }) {
  const keywords = visibleKeywords(item.keywords);
  const streak = hotStreakBadge(item.limit_up_count);
  return (
    <div className="flex min-w-0 items-center gap-2 px-3 py-1.5 sm:px-4">
      <span className="w-6 shrink-0 text-right font-mono text-xs tabular-nums text-muted-foreground">
        {item.rank ?? fallbackRank}
      </span>
      <Link
        to={`/stocks/${encodeURIComponent(item.vt_symbol)}`}
        title={`打开 ${item.name}`}
        className="min-w-0 truncate text-xs font-medium text-foreground hover:text-primary hover:underline"
      >
        {item.name}
      </Link>
      {keywords.map((keyword) => (
        <span
          key={keyword}
          className="shrink-0 rounded bg-muted px-1.5 py-px text-[10px] text-muted-foreground"
        >
          {keyword}
        </span>
      ))}
      {streak && (
        <span
          className={cn(
            "shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium",
            (item.limit_up_count ?? 0) >= 2
              ? "bg-rise/10 text-rise"
              : "bg-muted text-muted-foreground",
          )}
        >
          {streak}
        </span>
      )}
      <span
        className={cn(
          "ml-auto shrink-0 text-xs tabular-nums",
          item.change_pct == null ? "text-muted-foreground" : priceColorClass(item.change_pct),
        )}
      >
        {formatPctPoint(item.change_pct)}
      </span>
    </div>
  );
}
