import type { LowSuctionLedgerDay, LowSuctionLedgerLeg } from "@/api/lowSuction";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

const SETUP_BADGES: Record<string, { label: string; className: string }> = {
  trend_pullback: { label: "趋势", className: "bg-primary/15 text-primary" },
  oversold_rebound: { label: "超跌", className: "bg-cyan-500/15 text-cyan-600" },
};

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** 低吸历史交割单：两仓模拟逐日逐票（回测模拟，非实盘），最新在左。 */
export function LowSuctionLedgerView({
  ledgerDays,
  labelConvention,
}: {
  ledgerDays: LowSuctionLedgerDay[];
  labelConvention?: string;
}) {
  if (!ledgerDays.length) {
    return <EmptyState message="无交割记录" description="由 CLI low-suction-daily-backtest 物化后展示" />;
  }
  return (
    <section aria-label="低吸历史交割单">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-amber-500/5 px-3 py-2 text-xs text-amber-600 sm:px-4">
        <span className="eyebrow">复盘 REVIEW</span>
        <span>⚠️ 回测模拟交割单，非实盘 · 最近 {ledgerDays.length} 个交易日 · 最新在左</span>
        <span className="ml-auto">{labelConvention}</span>
      </div>
      <div className="overflow-x-auto" aria-label="交割单时间轴">
        <div className="flex min-w-max items-stretch divide-x">
          {ledgerDays.map((day) => (
            <LedgerDayColumn key={day.trade_date} day={day} />
          ))}
        </div>
      </div>
    </section>
  );
}

function LedgerDayColumn({ day }: { day: LowSuctionLedgerDay }) {
  const weekday = WEEKDAYS[new Date(`${day.trade_date}T00:00:00`).getDay()];
  return (
    <section className="flex w-64 shrink-0 flex-col" aria-label={`${day.trade_date} 交割单`}>
      <header className="border-b bg-muted/20 px-3 py-2.5">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold tabular-nums">{day.trade_date.slice(5)}</span>
          <span className="text-xs text-muted-foreground">{weekday}</span>
          <span className={cn("ml-auto text-sm font-bold tabular-nums", day.day_return_pct >= 0 ? "text-red-500" : "text-emerald-600")}>
            {day.day_return_pct >= 0 ? "+" : ""}
            {day.day_return_pct.toFixed(2)}%
          </span>
        </div>
        <div className="mt-0.5 text-[10px] text-muted-foreground">
          D+1 结算日 {day.d1_trade_date?.slice(5) ?? "--"} · 两仓各半
        </div>
      </header>
      <div className="flex flex-1 flex-col gap-2 px-3 py-2.5">
        {day.legs.map((leg) => (
          <LegCard key={`${day.trade_date}-${leg.setup_type}`} leg={leg} />
        ))}
      </div>
    </section>
  );
}

function LegCard({ leg }: { leg: LowSuctionLedgerLeg }) {
  const badge = SETUP_BADGES[leg.setup_type] ?? SETUP_BADGES.trend_pullback;
  const ret = leg.d1_close_return_pct;
  return (
    <div className="rounded-md border px-2.5 py-2">
      <div className="flex items-center gap-1.5">
        <span className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", badge.className)}>
          {badge.label}
        </span>
        <span className="font-mono text-xs font-bold tabular-nums text-primary">{leg.score.toFixed(0)}</span>
        <span className="ml-auto text-[10px] text-muted-foreground">{leg.band}</span>
      </div>
      <div className="mt-1">
        <StockIdentityLink vtSymbol={leg.vt_symbol} name={leg.stock_name ?? leg.symbol} />
      </div>
      <div className="mt-1 flex items-baseline justify-between text-xs tabular-nums">
        <span className="text-muted-foreground">
          买 {leg.close_price?.toFixed(2) ?? "--"}
          {leg.streak_total >= 2 && <span className="ml-1.5">连小K {leg.streak_total}</span>}
        </span>
        <span className={cn("font-semibold", ret == null ? "" : ret >= 0 ? "text-red-500" : "text-emerald-600")}>
          {ret == null ? "待结算" : `${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`}
        </span>
      </div>
    </div>
  );
}
