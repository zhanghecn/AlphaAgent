import { useMemo, useState } from "react";
import type { LowSuctionLedgerDay, LowSuctionLedgerLeg } from "@/api/lowSuction";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

const SETUP_BADGES: Record<string, { label: string; className: string }> = {
  trend_pullback: { label: "趋势", className: "bg-primary/15 text-primary" },
  oversold_rebound: { label: "超跌", className: "bg-cyan-500/15 text-cyan-600" },
};

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** 低吸历史交割单：两族各前五逐日逐票（回测模拟，非实盘），支持按日期与票筛选。 */
export function LowSuctionLedgerView({
  ledgerDays,
  labelConvention,
}: {
  ledgerDays: LowSuctionLedgerDay[];
  labelConvention?: string;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [keyword, setKeyword] = useState("");
  const [view, setView] = useState<"table" | "timeline">("table");

  if (!ledgerDays.length) {
    return <EmptyState message="无交割记录" description="由 CLI low-suction-daily-backtest 物化后展示" />;
  }

  // 最新在左：min 取末尾、max 取首位
  const minDate = ledgerDays[ledgerDays.length - 1]?.trade_date ?? "";
  const maxDate = ledgerDays[0]?.trade_date ?? "";

  const filteredDays = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return ledgerDays
      .filter((d) => (!start || d.trade_date >= start) && (!end || d.trade_date <= end))
      .map((d) =>
        kw
          ? {
              ...d,
              legs: d.legs.filter(
                (leg) =>
                  leg.vt_symbol.toLowerCase().includes(kw) ||
                  leg.symbol.toLowerCase().includes(kw) ||
                  (leg.stock_name ?? "").toLowerCase().includes(kw),
              ),
            }
          : d,
      )
      .filter((d) => d.legs.length > 0);
  }, [ledgerDays, start, end, keyword]);

  const rows = useMemo(
    () => filteredDays.flatMap((day) => day.legs.map((leg) => ({ day, leg }))),
    [filteredDays],
  );

  return (
    <section aria-label="低吸历史交割单">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b bg-amber-500/5 px-3 py-2 text-xs text-amber-600 sm:px-4">
        <span className="eyebrow">复盘 REVIEW</span>
        <span>⚠️ 回测模拟交割单，非实盘 · 每族前 5、每票 10% · 最近 {ledgerDays.length} 个交易日 · 最新在左</span>
        <span className="ml-auto">{labelConvention}</span>
      </div>
      <div className="flex flex-wrap items-end gap-2 border-b px-3 py-2 sm:px-4">
        <DateInput label="开始" value={start} min={minDate} max={maxDate} onChange={setStart} />
        <DateInput label="结束" value={end} min={minDate} max={maxDate} onChange={setEnd} />
        <SearchInput value={keyword} onChange={setKeyword} />
        <span className="text-xs text-muted-foreground">{rows.length} 条记录</span>
        <div className="ml-auto inline-flex shrink-0 border">
          <button
            type="button"
            onClick={() => setView("table")}
            className={cn("px-3 py-1 text-xs", view === "table" ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground")}
          >
            表格
          </button>
          <button
            type="button"
            onClick={() => setView("timeline")}
            className={cn("px-3 py-1 text-xs", view === "timeline" ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground")}
          >
            时间轴
          </button>
        </div>
      </div>
      {view === "table" ? (
        rows.length ? (
          <LedgerTable rows={rows} />
        ) : (
          <EmptyState message="无匹配记录" description="调整日期范围或搜索关键字" />
        )
      ) : filteredDays.length ? (
        <div className="overflow-x-auto" aria-label="交割单时间轴">
          <div className="flex min-w-max items-stretch divide-x">
            {filteredDays.map((day) => (
              <LedgerDayColumn key={day.trade_date} day={day} />
            ))}
          </div>
        </div>
      ) : (
        <EmptyState message="无匹配记录" description="调整日期范围或搜索关键字" />
      )}
    </section>
  );
}

function LedgerTable({ rows }: { rows: { day: LowSuctionLedgerDay; leg: LowSuctionLedgerLeg }[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">日期</th>
            <th className="px-3 py-2 text-left">股票</th>
            <th className="px-3 py-2 text-left">族 / 排名</th>
            <th className="px-3 py-2 text-right">分数</th>
            <th className="px-3 py-2 text-right">买价 / 连小K</th>
            <th className="px-3 py-2 text-right">D+1 收益</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map(({ day, leg }) => (
            <LedgerRow key={`${day.trade_date}-${leg.setup_type}-${leg.rank}`} day={day} leg={leg} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LedgerRow({ day, leg }: { day: LowSuctionLedgerDay; leg: LowSuctionLedgerLeg }) {
  const badge = SETUP_BADGES[leg.setup_type] ?? SETUP_BADGES.trend_pullback;
  const weekday = WEEKDAYS[new Date(`${day.trade_date}T00:00:00`).getDay()];
  const ret = leg.d1_close_return_pct;
  return (
    <tr>
      <td className="whitespace-nowrap px-3 py-2.5 text-xs tabular-nums">
        <div>{day.trade_date.slice(5)}</div>
        <div className="text-muted-foreground">{weekday}</div>
      </td>
      <td className="px-3 py-2.5">
        <StockIdentityLink vtSymbol={leg.vt_symbol} name={leg.stock_name ?? leg.symbol} />
      </td>
      <td className="px-3 py-2.5">
        <span className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", badge.className)}>{badge.label}</span>
        <span className="ml-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">#{leg.rank}</span>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right">
        <span className="font-mono text-xs font-bold tabular-nums text-primary">{leg.score.toFixed(0)}</span>
        <span className="ml-1 text-[10px] text-muted-foreground">{leg.band}</span>
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right text-xs tabular-nums text-muted-foreground">
        {leg.close_price?.toFixed(2) ?? "--"}
        {leg.streak_total >= 2 && <span className="ml-1.5 text-foreground">连{leg.streak_total}</span>}
      </td>
      <td
        className={cn(
          "whitespace-nowrap px-3 py-2.5 text-right text-sm font-semibold tabular-nums",
          ret == null ? "text-muted-foreground" : ret >= 0 ? "text-red-500" : "text-emerald-600",
        )}
      >
        {ret == null ? "待结算" : `${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`}
      </td>
    </tr>
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
          D+1 结算日 {day.d1_trade_date?.slice(5) ?? "--"} · 每票 10%，不足 10 票留现金
        </div>
      </header>
      <div className="flex flex-1 flex-col gap-2 px-3 py-2.5">
        {day.legs.map((leg) => (
          <LegCard key={`${day.trade_date}-${leg.setup_type}-${leg.rank}`} leg={leg} />
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
        <span className="font-mono text-[11px] tabular-nums text-muted-foreground">#{leg.rank}</span>
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

function DateInput({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: string;
  min?: string | null;
  max?: string | null;
  onChange: (value: string) => void;
}) {
  return (
    <label className="text-xs text-muted-foreground">
      {label}
      <input
        type="date"
        value={value}
        min={min ?? undefined}
        max={max ?? undefined}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 block h-9 border bg-background px-2 text-sm text-foreground"
      />
    </label>
  );
}

function SearchInput({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <label className="text-xs text-muted-foreground">
      搜票
      <input
        type="text"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="代码 / 名称"
        className="mt-1 block h-9 w-40 border bg-background px-2 text-sm text-foreground"
      />
    </label>
  );
}
