import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { Link } from "react-router-dom";

import type { LianbanReview } from "@/api/lianban";
import { cn } from "@/lib/utils";
import { isEarlySeal, shortSealTime } from "./LadderSection";

type Theme = LianbanReview["themes"][number];
type ThemeStock = Theme["stocks"][number];

/** 题材分组默认只显示前 8 组，其余折叠。 */
export const THEME_COLLAPSE_COUNT = 8;

// ===== 派生纯函数 =====

/** 题材按涨停家数降序（同数按名称码点序，对齐后端 (-count, name)）；防御性重排，不改原数组。 */
export function sortThemes(themes: Theme[]): Theme[] {
  return [...themes].sort((a, b) => {
    if (b.count !== a.count) return b.count - a.count;
    if (a.name === b.name) return 0;
    return a.name < b.name ? -1 : 1;
  });
}

/** 折叠显隐：未展开时截断到前 THEME_COLLAPSE_COUNT 组（入参应已排序）。 */
export function visibleThemes(themes: Theme[], expanded: boolean): Theme[] {
  return expanded ? themes : themes.slice(0, THEME_COLLAPSE_COUNT);
}

/** 是否需要「展开剩余 k 个题材」按钮。 */
export function isThemeCollapsible(themeCount: number): boolean {
  return themeCount > THEME_COLLAPSE_COUNT;
}

/** 组内个股按首封时间升序（null 最后；后端已排，前端防御重排，不改原数组）。 */
export function sortThemeStocks(stocks: ThemeStock[]): ThemeStock[] {
  return [...stocks].sort((a, b) => {
    if (a.first_limit_time == null && b.first_limit_time == null) return 0;
    if (a.first_limit_time == null) return 1;
    if (b.first_limit_time == null) return -1;
    if (a.first_limit_time === b.first_limit_time) return 0;
    return a.first_limit_time < b.first_limit_time ? -1 : 1;
  });
}

/** 连板文案：n>1 →「N连板」；n==1 →「首板」；0/null → null（不显示）。 */
export function themeStreakText(count: number | null): string | null {
  if (count == null || count <= 0) return null;
  return count > 1 ? `${count}连板` : "首板";
}

/** 题材龙头 ★ 判定：按 leader.vt_symbol 匹配；leader 为 null → false。 */
export function isThemeLeader(theme: Theme, stock: ThemeStock): boolean {
  return theme.leader != null && theme.leader.vt_symbol === stock.vt_symbol;
}

// ===== 组件 =====

interface ThemeGroupsSectionProps {
  themes: Theme[];
}

/**
 * 热点题材：涨停股按行业分组（东财行业粒度，粗粒度对齐是后端话题）。
 * 组卡编号按 count 降序；组内按首封时间升序，早盘封板时间标红（复用天梯 isEarlySeal 口径）。
 * rebuild 模式下行业可能整体缺失为单一「其他」组，正常渲染即可。
 */
export function ThemeGroupsSection({ themes }: ThemeGroupsSectionProps) {
  const [expanded, setExpanded] = useState(false);
  const sorted = sortThemes(themes);
  const visible = visibleThemes(sorted, expanded);
  const collapsible = isThemeCollapsible(sorted.length);

  return (
    <section aria-label="热点题材" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">热点题材</h2>
        <span className="text-[11px] text-muted-foreground">全部涨停个股 · 按首封时间</span>
      </header>
      {sorted.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          今日无题材分组
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-2 p-3 sm:grid-cols-2 sm:p-4 xl:grid-cols-3">
            {visible.map((theme, index) => (
              <ThemeCard key={theme.name} theme={theme} index={index} />
            ))}
          </div>
          {collapsible && (
            <div className="border-t px-3 py-2 sm:px-4">
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground"
              >
                {expanded ? "收起" : `展开剩余 ${sorted.length - THEME_COLLAPSE_COUNT} 个题材`}
                {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

/** 单个题材组卡：编号 + 名称 + 家数；个股按首封时间列，★ 标记题材龙头。 */
function ThemeCard({ theme, index }: { theme: Theme; index: number }) {
  const stocks = sortThemeStocks(theme.stocks);
  return (
    <div className="min-w-0 rounded-md border px-2.5 py-2">
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground/60">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className="truncate text-xs font-semibold text-foreground">{theme.name}</span>
        <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
          {theme.count}家涨停
        </span>
      </div>
      {stocks.length > 0 && (
        <ul className="mt-1.5 space-y-0.5">
          {stocks.map((stock) => (
            <ThemeStockRow key={stock.vt_symbol} theme={theme} stock={stock} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** 题材个股行：首封时间（mono，早盘红）+ ★龙头 + 名称 + N连板/反包徽标。 */
function ThemeStockRow({ theme, stock }: { theme: Theme; stock: ThemeStock }) {
  const time = shortSealTime(stock.first_limit_time);
  const streak = themeStreakText(stock.limit_up_count);
  const leader = isThemeLeader(theme, stock);
  return (
    <li className="flex min-w-0 items-center gap-1.5 text-xs">
      {time && (
        <span
          className={cn(
            "shrink-0 font-mono text-[11px] tabular-nums",
            isEarlySeal(stock.first_limit_time)
              ? "font-medium text-rise"
              : "text-muted-foreground",
          )}
        >
          {time}
        </span>
      )}
      {leader && (
        <span className="shrink-0 text-amber-500" title="题材龙头">
          ★
        </span>
      )}
      <Link
        to={`/stocks/${encodeURIComponent(stock.vt_symbol)}`}
        title={`打开 ${stock.name}`}
        className={cn(
          "min-w-0 truncate font-medium text-foreground hover:text-primary hover:underline",
        )}
      >
        {stock.name}
      </Link>
      {streak && (
        <span className="shrink-0 rounded-full bg-rise/10 px-1.5 py-px text-[10px] font-medium text-rise">
          {streak}
        </span>
      )}
      {stock.is_reverse && (
        <span className="shrink-0 rounded-full bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-600">
          反
        </span>
      )}
    </li>
  );
}
