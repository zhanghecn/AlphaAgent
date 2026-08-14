import { useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

import type { LadderStock, LadderTier, LianbanReview } from "@/api/lianban";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";
import { formatRatioPct, formatShortDate } from "./ReviewStatsCards";

type Ladder = LianbanReview["ladder"];
type Promotion = LianbanReview["promotion"];
type LadderSource = NonNullable<Ladder>["source"];
type RelayDay = NonNullable<Promotion>["relay_5d"][number];

/** 家数最多的档（通常 1 板档）默认折叠，只显示前 20 只。 */
export const COLLAPSED_STOCK_COUNT = 20;

/** 早盘强势封板界线：10:00:00（含）前首封的时间标红（对齐 lianban 图例暖色口径）。 */
export const EARLY_SEAL_CUTOFF = "10:00:00";

/** by_streak 合并档：streak>=8 合并为 "8+"（与后端 B2 口径一致）。 */
const TOP_STREAK_KEY = "8+";
const TOP_STREAK_MIN = 8;

/** 五日接力矩阵展示行（高板在上；键与后端 tiers 一致，streak>=6 合并 "6+"）。 */
export const RELAY_TIER_KEYS = ["6+", "5", "4", "3", "2", "1"] as const;

// ===== 派生纯函数 =====

/**
 * 「明日晋级率≈」查表：streak 1-7 按数值键匹配（容忍后端序列化成字符串），
 * streak>=8 查合并档 "8+"；档位缺失或 rate 为 null → null。
 */
export function promotionRateFor(promotion: Promotion, streak: number): number | null {
  if (!promotion) return null;
  const key = streak >= TOP_STREAK_MIN ? TOP_STREAK_KEY : String(streak);
  const entry = promotion.by_streak.find((item) => String(item.streak) === key);
  return entry?.rate ?? null;
}

/** 「明日晋级率 ≈45.1%」（近一年历史频率，一位小数）；rate 缺失 → "明日晋级率 --"。 */
export function tomorrowPromotionText(promotion: Promotion, streak: number): string {
  const rate = promotionRateFor(promotion, streak);
  return rate == null ? "明日晋级率 --" : `明日晋级率 ≈${formatRatioPct(rate)}`;
}

/** 反包徽标文案：is_reverse 且统计完整 → "反·13天9板"；否则 null。 */
export function reverseBadgeText(
  stock: Pick<LadderStock, "is_reverse" | "limit_stat_days" | "limit_stat_boards">,
): string | null {
  if (!stock.is_reverse) return null;
  if (stock.limit_stat_days == null || stock.limit_stat_boards == null) return null;
  return `反·${stock.limit_stat_days}天${stock.limit_stat_boards}板`;
}

/** 早盘强势封板：10:00:00（含）前 → true；null → false。非定长输入先补零。 */
export function isEarlySeal(time: string | null | undefined): boolean {
  return time != null && time.padStart(8, "0") <= EARLY_SEAL_CUTOFF;
}

/** 今日实际晋级率（0-1 比率 → 整数百分，对齐 lianban「85%」口径）；null → "--"。 */
export function formatTodayRate(rate: number | null | undefined): string {
  if (rate == null || !Number.isFinite(rate)) return "--";
  return `${Math.round(rate * 100)}%`;
}

/**
 * 「今日 X 进 Y」档头文案：streak>=2 → "今日{streak-1}进{streak} {rate}"；
 * 1 板档不显示（对齐 lianban：1 板档只有明日晋级率）；rate 缺失 → "--"。
 */
export function todayPromotionText(
  tier: Pick<LadderTier, "streak" | "today_promotion">,
): string | null {
  if (tier.streak < 2) return null;
  return `今日${tier.streak - 1}进${tier.streak} ${formatTodayRate(tier.today_promotion?.rate)}`;
}

/** 折叠显隐：未展开时截断到前 COLLAPSED_STOCK_COUNT 只。 */
export function visibleStocks(tier: Pick<LadderTier, "stocks">, expanded: boolean): LadderStock[] {
  return expanded ? tier.stocks : tier.stocks.slice(0, COLLAPSED_STOCK_COUNT);
}

/** 是否出现「展开全部 N 家」按钮：家数超过折叠阈值才需要。 */
export function isTierCollapsible(stockCount: number): boolean {
  return stockCount > COLLAPSED_STOCK_COUNT;
}

/** 档位按 streak 降序（防御性重排，不改原数组；后端 B1 已按此输出）。 */
export function sortTiersDesc(tiers: LadderTier[]): LadderTier[] {
  return [...tiers].sort((a, b) => b.streak - a.streak);
}

interface SourceBadge {
  label: string;
  className: string;
  title?: string;
}

/** 天梯数据源徽标：东财盘口(归档) / 实时盘口(盘中) / 日线口径(历史重建)。 */
export function ladderSourceBadge(source: LadderSource): SourceBadge {
  if (source === "live_pool") {
    return {
      label: "实时盘口",
      className: "bg-amber-500/15 text-amber-600",
      title: "盘中实时涨停池，封板口径随行情滚动，以收盘归档为准",
    };
  }
  if (source === "daily_rebuild") {
    return {
      label: "日线口径",
      className: "bg-primary/10 text-primary",
      title: "历史归档按日线口径重建，首封时间等盘口字段缺失",
    };
  }
  return { label: "东财盘口", className: "bg-emerald-500/15 text-emerald-600" };
}

/** 五日接力矩阵行标签："6+" → "6+板"。 */
export function relayTierLabel(key: string): string {
  return `${key}板`;
}

/** 首封时间 "09:25:03" → "09:25"（档内只展示到分）；null 原样。 */
export function shortSealTime(time: string | null): string | null {
  return time == null ? null : time.slice(0, 5);
}

// ===== 组件 =====

interface LadderSectionProps {
  ladder: Ladder;
  promotion: Promotion;
}

/**
 * 连板天梯：档区头（标题 + 数据源徽标 + 五日接力小表）+ 各板位档（streak 降序）。
 * ladder=null 时降级为 EmptyState 块；rebuild 口径下首封时间等盘口字段为空自动省略。
 */
export function LadderSection({ ladder, promotion }: LadderSectionProps) {
  if (!ladder) {
    return (
      <section aria-label="连板天梯" className="rounded-lg border">
        <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
          <h2 className="text-sm font-semibold text-foreground">连板天梯</h2>
        </header>
        <div className="p-3 sm:p-4">
          <EmptyState
            message="天梯数据暂缺"
            description="当日涨停池归档与日线重建均不可用，请检查数据同步"
          />
        </div>
      </section>
    );
  }

  const badge = ladderSourceBadge(ladder.source);
  const tiers = sortTiersDesc(ladder.tiers);
  const relay = promotion?.relay_5d ?? [];

  return (
    <section aria-label="连板天梯" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">连板天梯</h2>
        <span
          className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", badge.className)}
          title={badge.title}
        >
          {badge.label}
        </span>
        <span className="text-[11px] text-muted-foreground">
          梯队完整度 · 超短核心指标看五日接力
        </span>
      </header>
      {relay.length > 0 && <RelayMatrix relay={relay} currentDate={ladder.trade_date} />}
      {tiers.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          当日无连板梯队
        </div>
      ) : (
        tiers.map((tier) => <TierRow key={tier.streak} tier={tier} promotion={promotion} />)
      )}
    </section>
  );
}

/** 五日接力矩阵：近 5 个交易日 × 各板位家数（高板在上）。
 *  加粗列按 currentDate 精确匹配（live 模式 relay 锚定 rebuild 日，无匹配则不加粗）。 */
function RelayMatrix({ relay, currentDate }: { relay: RelayDay[]; currentDate?: string }) {
  const lastIndex = relay.length - 1;
  const currentIndex = relay.findIndex((day) => day.trade_date === currentDate);
  const boldIndex = currentIndex >= 0 ? currentIndex : lastIndex;
  return (
    <div className="overflow-x-auto border-b px-3 py-2 sm:px-4">
      <table className="w-full min-w-[420px] border-collapse text-[11px]">
        <thead>
          <tr className="text-muted-foreground">
            <th className="py-0.5 pr-2 text-left font-medium">五日接力</th>
            {relay.map((day, index) => (
              <th
                key={day.trade_date}
                className={cn(
                  "px-2 py-0.5 text-right font-medium tabular-nums",
                  index === boldIndex && "text-foreground",
                )}
              >
                {formatShortDate(day.trade_date)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {RELAY_TIER_KEYS.map((key) => (
            <tr key={key}>
              <td className="py-0.5 pr-2 text-left text-muted-foreground">
                {relayTierLabel(key)}
              </td>
              {relay.map((day, index) => {
                const value = day.tiers[key] ?? 0;
                return (
                  <td
                    key={day.trade_date}
                    className={cn(
                      "px-2 py-0.5 text-right tabular-nums",
                      value > 0 ? "text-foreground" : "text-muted-foreground/40",
                      index === boldIndex && value > 0 && "font-medium",
                    )}
                  >
                    {value}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 单个板位档：档头（N板/家数/今日晋级/明日晋级率）+ 个股网格 + 折叠按钮。 */
function TierRow({ tier, promotion }: { tier: LadderTier; promotion: Promotion }) {
  const [expanded, setExpanded] = useState(false);
  const stocks = visibleStocks(tier, expanded);
  const collapsible = isTierCollapsible(tier.stocks.length);
  const todayText = todayPromotionText(tier);

  return (
    <div className="border-b last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 pt-2 sm:px-4">
        <span className="text-sm font-semibold tabular-nums text-foreground">
          {tier.streak}板
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">{tier.count}家</span>
        {todayText && (
          <span
            className="text-xs tabular-nums text-muted-foreground"
            title={`昨日${tier.streak - 1}板个股今日晋级${tier.streak}板的实际比例`}
          >
            {todayText}
          </span>
        )}
        <span
          className="text-xs tabular-nums text-muted-foreground"
          title="近一年同板位个股次日继续涨停的历史频率"
        >
          {tomorrowPromotionText(promotion, tier.streak)}
        </span>
      </div>
      <div className="grid grid-cols-1 gap-x-3 px-2 py-1 sm:grid-cols-2 sm:px-3 lg:grid-cols-3 xl:grid-cols-4">
        {stocks.map((stock) => (
          <StockChip key={stock.vt_symbol} stock={stock} />
        ))}
      </div>
      {collapsible && (
        <div className="px-3 pb-2 sm:px-4">
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:text-foreground"
          >
            {expanded ? "收起" : `展开全部 ${tier.stocks.length} 家`}
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * 个股 chip：首封时间（mono，早盘红）+ 名称（StockIdentityLink，industry 放 meta 副行）
 * + 反包/一字徽标。rebuild 口径首封时间为 null → 时间不显示。
 */
function StockChip({ stock }: { stock: LadderStock }) {
  const time = shortSealTime(stock.first_limit_time);
  const reverse = reverseBadgeText(stock);
  return (
    <div className="flex min-w-0 items-center gap-1.5 rounded px-1 py-0.5">
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
      <StockIdentityLink
        name={stock.name}
        vtSymbol={stock.vt_symbol}
        meta={stock.industry}
        className="min-w-0 flex-1"
      />
      {reverse && (
        <span className="shrink-0 rounded-full bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-600">
          {reverse}
        </span>
      )}
      {stock.is_one_word && (
        <span className="shrink-0 rounded-full bg-muted px-1.5 py-px text-[10px] font-medium text-muted-foreground">
          一字
        </span>
      )}
    </div>
  );
}
