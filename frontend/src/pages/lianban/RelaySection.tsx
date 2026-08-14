import type { LianbanReview } from "@/api/lianban";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, priceColorClass } from "@/lib/utils";
import { formatTodayRate } from "./LadderSection";
import { formatPctPoint, formatRatioPct } from "./ReviewStatsCards";

type Relay = LianbanReview["relay"];
type RelayTier = Relay["tiers"][number];
type RelayStock = RelayTier["stocks"][number];
type FirstBoard = Relay["first_board"];

// ===== 派生纯函数 =====

/**
 * 头部「晋级 x/y」：只统计连板档（prev_streak>=2，对齐 lianban「连板股今日表现」口径）。
 * prev_streak=1 档（昨日首板）由 first_board 块的「首板晋级(1进2)」单独表达，不重复计入。
 */
export function relaySummary(relay: Relay): { promoted: number; total: number } {
  let promoted = 0;
  let total = 0;
  for (const tier of relay.tiers) {
    if (tier.prev_streak < 2) continue;
    for (const stock of tier.stocks) {
      total += 1;
      if (stock.status === "promoted") promoted += 1;
    }
  }
  return { promoted, total };
}

/** 展示的连板档：prev_streak>=2 且降序（防御性重排，不改原数组）。 */
export function relayLianbanTiers(relay: Relay): RelayTier[] {
  return relay.tiers
    .filter((tier) => tier.prev_streak >= 2)
    .sort((a, b) => b.prev_streak - a.prev_streak);
}

/**
 * 「首板晋级(1进2) 16%(12/75,历史均值 16.3%)」：rate 整数百分、mean 一位小数；
 * rate/mean 为 null 分别降级为 "--"/省略均值子句；空形（全零全 null）→ null。
 */
export function firstBoardText(firstBoard: FirstBoard | null | undefined): string | null {
  if (!firstBoard) return null;
  const { base, promoted, rate, mean } = firstBoard;
  if (!base && !promoted && rate == null && mean == null) return null;
  const head = `首板晋级(1进2) ${formatTodayRate(rate)}(${promoted}/${base}`;
  return mean == null ? `${head})` : `${head},历史均值 ${formatRatioPct(mean)})`;
}

/** 状态徽标：promoted → 晋N板（暖/强势，today_streak 缺失降级「晋级」）；broken → 炸板（冷/走弱）；open → null（行内只显示涨幅）。 */
export function relayStatusBadge(stock: RelayStock): { label: string; className: string } | null {
  if (stock.status === "promoted") {
    return {
      label: stock.today_streak != null ? `晋${stock.today_streak}板` : "晋级",
      className: "bg-rise/10 text-rise",
    };
  }
  if (stock.status === "broken") {
    return { label: "炸板", className: "bg-fall/10 text-fall" };
  }
  return null;
}

// ===== 组件 =====

interface RelaySectionProps {
  relay: Relay;
}

/**
 * 连板梯队接力：昨日各连板档个股今日表现（晋级/炸板/红盘）。
 * relay payload 不含昨日日期（后端未导出 prev_daily），副标用「昨日」文案，不硬造日期。
 * 空档降级为内联空态，不拖垮整页。
 */
export function RelaySection({ relay }: RelaySectionProps) {
  const tiers = relayLianbanTiers(relay);
  const { promoted, total } = relaySummary(relay);
  const firstBoard = firstBoardText(relay.first_board);

  return (
    <section aria-label="连板梯队接力" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">连板梯队接力</h2>
        <span className="text-[11px] tabular-nums text-muted-foreground">
          昨日连板股今日表现 · 晋级 {promoted}/{total}
        </span>
        {firstBoard && (
          <span className="text-[11px] tabular-nums text-muted-foreground">{firstBoard}</span>
        )}
      </header>
      {tiers.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          昨日无连板股接力样本
        </div>
      ) : (
        tiers.map((tier) => <RelayTierRow key={tier.prev_streak} tier={tier} />)
      )}
    </section>
  );
}

/** 单个昨日板位档：档头（昨N板/家数）+ 个股网格。 */
function RelayTierRow({ tier }: { tier: RelayTier }) {
  return (
    <div className="border-b last:border-b-0">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 pt-2 sm:px-4">
        <span className="text-sm font-semibold tabular-nums text-foreground">
          昨{tier.prev_streak}板
        </span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {tier.stocks.length}家
        </span>
      </div>
      <div className="grid grid-cols-1 gap-x-3 px-2 py-1 sm:grid-cols-2 sm:px-3 lg:grid-cols-3 xl:grid-cols-4">
        {tier.stocks.map((stock) => (
          <RelayStockChip key={stock.vt_symbol} stock={stock} />
        ))}
      </div>
    </div>
  );
}

/** 接力个股 chip：名称 + 状态徽标（晋N板/炸板）或涨幅（红涨绿跌，null → "--"）。 */
function RelayStockChip({ stock }: { stock: RelayStock }) {
  const badge = relayStatusBadge(stock);
  return (
    <div className="flex min-w-0 items-center gap-1.5 rounded px-1 py-0.5">
      <StockIdentityLink
        name={stock.name}
        vtSymbol={stock.vt_symbol}
        className="min-w-0 flex-1"
      />
      {badge ? (
        <span
          className={cn(
            "shrink-0 rounded-full px-1.5 py-px text-[10px] font-medium",
            badge.className,
          )}
        >
          {badge.label}
        </span>
      ) : (
        <span
          className={cn(
            "shrink-0 text-xs tabular-nums",
            stock.today_change_pct == null
              ? "text-muted-foreground"
              : priceColorClass(stock.today_change_pct),
          )}
        >
          {formatPctPoint(stock.today_change_pct)}
        </span>
      )}
    </div>
  );
}
