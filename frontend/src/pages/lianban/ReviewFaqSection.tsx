import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import type { LianbanReview, LianbanStats } from "@/api/lianban";
import { cn } from "@/lib/utils";
import { formatTodayRate } from "./LadderSection";
import { formatCnDate } from "./ReviewHeader";
import {
  formatGroupedInt,
  formatPctPoint,
  formatRatioPct,
  formatTemperature,
} from "./ReviewStatsCards";
import { sortThemes } from "./ThemeGroupsSection";

type Themes = LianbanReview["themes"];
type Relay = LianbanReview["relay"];
type Ladder = LianbanReview["ladder"];

/** FAQ 答案降级文案：主字段为 null 时整题降级，不炸页面。 */
export const FAQ_NO_DATA = "暂无数据";

/** 题材直答只取前 3 组（对齐 lianban 主线题材 Top3 口径）。 */
export const FAQ_THEME_TOP_N = 3;

/** 最高板点名最多列 5 只，超出以「等 N 只」收尾。 */
export const FAQ_TOP_STOCK_NAMES = 5;

export interface FaqItem {
  key: string;
  question: string;
  answer: string;
}

// ===== 派生纯函数（每题一个 builder，返回 null → 降级「暂无数据」）=====

/**
 * 「涨停多少家」：涨停为主口径（缺失 → null 整题降级），
 * 连板/最高板/跌停/炸板/封板率逐个子句缺失即跳过。
 */
export function faqLimitUpAnswer(stats: LianbanStats): string | null {
  if (stats.limit_up == null) return null;
  const parts = [`涨停 ${formatGroupedInt(stats.limit_up)} 家`];
  if (stats.lianban != null) parts.push(`连板 ${formatGroupedInt(stats.lianban)} 家`);
  if (stats.max_streak != null) parts.push(`最高 ${stats.max_streak} 板`);
  if (stats.limit_down != null) parts.push(`跌停 ${formatGroupedInt(stats.limit_down)} 家`);
  if (stats.broken != null) parts.push(`炸板 ${formatGroupedInt(stats.broken)} 家`);
  if (stats.seal_rate != null) parts.push(`封板率 ${formatRatioPct(stats.seal_rate)}`);
  return `${parts.join("，")}。`;
}

/** 「市场情绪阶段」：阶段缺失 → null；温度缺失时只答阶段。 */
export function faqSentimentAnswer(stats: LianbanStats): string | null {
  if (stats.sentiment_phase == null) return null;
  const temperature =
    stats.sentiment_score == null ? null : `温度 ${formatTemperature(stats.sentiment_score)}`;
  return temperature
    ? `市场情绪处于「${stats.sentiment_phase}」阶段（${temperature}）。`
    : `市场情绪处于「${stats.sentiment_phase}」阶段。`;
}

/** 「昨日涨停今日表现」：平均涨幅缺失 → null；中位/翻红率可选追加。 */
export function faqPrevLimitUpAnswer(stats: LianbanStats): string | null {
  if (stats.prev_lu_avg_change == null) return null;
  const parts = [`昨日涨停个股今日平均涨幅 ${formatPctPoint(stats.prev_lu_avg_change)}`];
  if (stats.prev_lu_median_change != null) {
    parts.push(`中位 ${formatPctPoint(stats.prev_lu_median_change)}`);
  }
  if (stats.prev_lu_rise_ratio != null) {
    parts.push(`翻红占比 ${formatRatioPct(stats.prev_lu_rise_ratio)}`);
  }
  return `${parts.join("，")}；逐只晋级/断板见上方「连板梯队接力」。`;
}

/**
 * 「首板晋级率(1进2)」：base/promoted 缺失（relay.first_board 恒在，防御）→ null；
 * base=0 → 昨日无首板样本；rate 缺失降级「--」，mean 缺失省略均值子句。
 */
export function faqFirstBoardAnswer(relay: Relay): string | null {
  const firstBoard = relay.first_board;
  if (firstBoard == null) return null;
  const { base, promoted, rate, mean } = firstBoard;
  if (base === 0) return "昨日无首板个股，今日无 1 进 2 晋级样本。";
  const parts = [`昨日首板 ${formatGroupedInt(base)} 只`, `今日晋级 ${formatGroupedInt(promoted)} 只`];
  parts.push(`晋级率 ${formatTodayRate(rate)}`);
  if (mean != null) parts.push(`近一年历史均值 ${formatRatioPct(mean)}`);
  return `${parts.join("，")}。`;
}

/**
 * 「最高连板股」：最高板缺失 → null；天梯在时点名最高板个股
 * （最多 FAQ_TOP_STOCK_NAMES 只），天梯缺失时只答板数。
 */
export function faqTopStreakAnswer(stats: LianbanStats, ladder: Ladder): string | null {
  if (stats.max_streak == null) return null;
  const topTier = ladder?.tiers.find((tier) => tier.streak === stats.max_streak);
  if (!topTier || topTier.stocks.length === 0) {
    return `最高 ${stats.max_streak} 板。`;
  }
  const names = topTier.stocks.slice(0, FAQ_TOP_STOCK_NAMES).map((stock) => stock.name);
  const suffix =
    topTier.stocks.length > FAQ_TOP_STOCK_NAMES ? ` 等 ${topTier.stocks.length} 只` : "";
  return `最高 ${stats.max_streak} 板：${names.join("、")}${suffix}；梯队详情见上方「连板天梯」。`;
}

/** 「主线题材」：按涨停家数降序取前 3 组；无题材分组 → null。 */
export function faqThemesAnswer(themes: Themes): string | null {
  const top = sortThemes(themes).slice(0, FAQ_THEME_TOP_N);
  if (top.length === 0) return null;
  const list = top.map((theme) => `${theme.name} ${theme.count} 家`).join("、");
  return `涨停家数前三的题材：${list}；完整分组见上方「热点题材」。`;
}

/** 「数据从哪来」：静态文案（口径说明 + 免责声明），不依赖当日数据。 */
export function faqDataSourceAnswer(): string {
  return "涨停/连板数据来自东方财富涨停池盘后归档与全市场日线重建双口径，盘后 19:00 统一同步定版；盘中为实时滚动口径（页头标「盘中滚动 · 未定版」），封板/炸板等数据以收盘定版为准。仅供研究，不构成投资建议。";
}

/**
 * 组装 7 条 FAQ（对齐 lianban「常见问题 · 当日数据直答」格式）：
 * 6 条当日数据题（值为 null 降级「暂无数据」）+ 1 条口径/免责静态题。
 */
export function buildFaqItems(review: LianbanReview): FaqItem[] {
  const date = formatCnDate(review.trade_date);
  const stats = review.stats;
  const candidates: [string, string, string | null][] = [
    ["limit_up", `${date} A股涨停多少家？`, faqLimitUpAnswer(stats)],
    ["sentiment", `${date} 市场情绪处于什么阶段？`, faqSentimentAnswer(stats)],
    ["prev_limit_up", `${date} 昨日涨停今日表现如何？`, faqPrevLimitUpAnswer(stats)],
    ["first_board", `${date} 首板晋级率（1进2）是多少？`, faqFirstBoardAnswer(review.relay)],
    ["top_streak", `${date} 最高连板股是哪几只？`, faqTopStreakAnswer(stats, review.ladder)],
    ["themes", `${date} 主线题材是什么？`, faqThemesAnswer(review.themes)],
    ["data_source", "复盘数据从哪来、什么时候定版？", faqDataSourceAnswer()],
  ];
  return candidates.map(([key, question, answer]) => ({
    key,
    question,
    answer: answer ?? FAQ_NO_DATA,
  }));
}

// ===== 组件 =====

interface ReviewFaqSectionProps {
  review: LianbanReview;
}

/**
 * 常见问题：当日数据直答的折叠列表（对齐天梯折叠的 ChevronDown/Up 惯例，零动画）。
 * 默认展开第一条；各题独立开合；null 字段已降级为「暂无数据」。
 */
export function ReviewFaqSection({ review }: ReviewFaqSectionProps) {
  const items = buildFaqItems(review);
  const [openKeys, setOpenKeys] = useState<ReadonlySet<string>>(
    () => new Set(items.length > 0 ? [items[0].key] : []),
  );

  const toggle = (key: string) => {
    setOpenKeys((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <section aria-label="常见问题" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">常见问题</h2>
        <span className="text-[11px] text-muted-foreground">当日数据直答 · 仅供研究</span>
      </header>
      <ul className="divide-y">
        {items.map((item) => {
          const open = openKeys.has(item.key);
          return (
            <li key={item.key}>
              <button
                type="button"
                aria-expanded={open}
                onClick={() => toggle(item.key)}
                className={cn(
                  "flex w-full items-center gap-2 px-3 py-2 text-left text-xs sm:px-4",
                  open ? "text-foreground" : "text-muted-foreground hover:text-foreground",
                )}
              >
                <span className="min-w-0 flex-1 font-medium">{item.question}</span>
                {open ? (
                  <ChevronUp size={13} className="shrink-0 text-muted-foreground" />
                ) : (
                  <ChevronDown size={13} className="shrink-0 text-muted-foreground" />
                )}
              </button>
              {open && (
                <p className="px-3 pb-2.5 text-xs leading-5 text-muted-foreground tabular-nums sm:px-4">
                  {item.answer}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
