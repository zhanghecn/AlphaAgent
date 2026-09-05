import { useMemo, useState } from "react";

import type { W2sGroupKey, W2sLedgerDay, W2sLedgerMonth, W2sLedgerTrade } from "@/api/weakToStrong";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const EXIT_REASON_LABELS: Record<string, string> = {
  next_close_fail: "次日未涨停·收盘卖",
  break_close: "断板日收盘卖",
  max_hold_close: "20日兜底·收盘卖",
  open_end: "持有中",
};

const GROUP_KEYS = ["yin2", "yang2a", "yang2b", "yin4", "yang4"] as const;

const GROUP_BADGES: Record<W2sGroupKey, { label: string; className: string }> = {
  yin2: { label: "2板阴", className: "bg-primary/15 text-primary" },
  yang2a: { label: "首阳", className: "bg-rise/15 text-rise" },
  yang2b: { label: "纠缠", className: "bg-orange-500/15 text-orange-500" },
  yin4: { label: "4+阴", className: "bg-violet-500/15 text-violet-500" },
  yang4: { label: "4+阳", className: "bg-amber-500/15 text-amber-500" },
};

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** N型补涨打板历史交割单:横向平铺列表(全部出手信号逐笔,不限仓位),支持月份/组/搜票筛选。 */
export function W2sLedgerView({
  ledgerDays,
  months,
  month,
  onMonthChange,
}: {
  ledgerDays: W2sLedgerDay[];
  months: W2sLedgerMonth[];
  month: string | null;
  onMonthChange: (month: string) => void;
  caliber?: string;
}) {
  const [groupFilter, setGroupFilter] = useState<W2sGroupKey | "all">("all");
  const [keyword, setKeyword] = useState("");

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return ledgerDays.flatMap((day) =>
      day.trades
        .filter((t) => (groupFilter === "all" || t.group === groupFilter))
        .filter((t) =>
          !kw
          || t.vt_symbol.toLowerCase().includes(kw)
          || (t.name ?? "").toLowerCase().includes(kw),
        )
        .map((t) => ({ day, trade: t })),
    );
  }, [ledgerDays, groupFilter, keyword]);

  const groupSummaries = useMemo(
    () => summarizeByGroup(ledgerDays),
    [ledgerDays],
  );

  if (!ledgerDays.length) {
    return <EmptyState message="该月暂无交割记录——先在回测页运行一次「重新计算」,或切换其他月份" />;
  }

  return (
    <section aria-label="N型补涨打板历史交割单" className="rounded-lg border">
      <div className="border-b px-4 py-2 text-xs text-muted-foreground">
        回测模拟口径(非实盘):板上买(触板买涨停价,一字排除),板留断走
        ;全部出手信号逐笔,不限仓位。实时前推成交随产品上线逐日沉淀。
      </div>

      <GroupSummaryBar summaries={groupSummaries} />

      <div className="flex flex-wrap items-end gap-2 border-b px-4 py-2">
        <label className="text-xs text-muted-foreground">
          月份
          <select
            className="mt-1 block h-9 rounded-md border bg-background px-2 text-sm"
            value={month ?? ""}
            onChange={(e) => onMonthChange(e.target.value)}
            aria-label="选择月份"
          >
            {months.map((m) => (
              <option key={m.month} value={m.month}>
                {m.month} · {m.count}笔 · 均{m.avg_ret_pct == null ? "--" : formatPct(m.avg_ret_pct)}
              </option>
            ))}
          </select>
        </label>
        <span className="inline-flex border">
          {(["all", ...GROUP_KEYS] as const).map((gk) => (
            <button
              key={gk}
              type="button"
              onClick={() => setGroupFilter(gk)}
              className={cn(
                "px-3 py-1 text-xs",
                groupFilter === gk ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground",
              )}
            >
              {gk === "all" ? "全部" : GROUP_BADGES[gk].label}
            </button>
          ))}
        </span>
        <label className="text-xs text-muted-foreground">
          搜票
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="代码 / 名称"
            className="mt-1 block h-9 w-36 border bg-background px-2 text-sm text-foreground"
          />
        </label>
        <span className="text-xs text-muted-foreground">{rows.length} 条记录</span>
      </div>

      {rows.length === 0 ? (
        <EmptyState message="无匹配记录" description="调整组筛选或搜索关键字" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1020px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">日期</th>
                <th className="px-3 py-2 text-left font-medium">股票</th>
                <th className="px-3 py-2 text-left font-medium">组</th>
                <th className="px-3 py-2 text-right font-medium">竞价/高开</th>
                <th className="px-3 py-2 text-right font-medium">买入价</th>
                <th className="px-3 py-2 text-right font-medium">首触</th>
                <th className="px-3 py-2 text-right font-medium">卖出价</th>
                <th className="px-3 py-2 text-right font-medium">卖出日</th>
                <th className="px-3 py-2 text-left font-medium">卖出原因</th>
                <th className="px-3 py-2 text-right font-medium">连板高度</th>
                <th className="px-3 py-2 text-right font-medium">收益</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map(({ day, trade }) => (
                <LedgerRow key={`${day.trade_date}-${trade.vt_symbol}-${trade.group}`}
                  day={day.trade_date} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** 15mK周期末刻 → 区间起点(09:45→09:30, 13:15→13:00, 其他→前15分钟). */
function touchStart(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  const mins = h * 60 + m - 15;
  return `${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
}

function LedgerRow({ day, trade }: { day: string; trade: W2sLedgerTrade }) {
  const badge = GROUP_BADGES[trade.group] ?? GROUP_BADGES.yin2;
  const weekday = WEEKDAYS[new Date(`${day}T00:00:00`).getDay()];
  return (
    <tr>
      <td className="whitespace-nowrap px-3 py-2.5 text-xs tabular-nums">
        <div>{day.slice(5)}</div>
        <div className="text-muted-foreground">{weekday}</div>
      </td>
      <td className="px-3 py-2.5">
        <StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} />
      </td>
      <td className="px-3 py-2.5">
        <span className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", badge.className)}
          title={trade.group_label}>
          {badge.label}
        </span>
      </td>
      <td className={cn("whitespace-nowrap px-3 py-2.5 text-right text-xs tabular-nums", tone(trade.gap_open_pct))}>
        {trade.gap_open_pct == null ? "--" : formatPct(trade.gap_open_pct)}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono text-xs tabular-nums">
        {formatPrice(trade.entry_price)}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono text-xs tabular-nums"
        title={trade.touch ? `${touchStart(trade.touch)}~${trade.touch} 首次触板` : "无分钟数据(2024-08前)"}>
        {trade.touch ?? <span className="text-muted-foreground/60">--</span>}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono text-xs tabular-nums">
        {formatPrice(trade.exit_price)}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right text-xs tabular-nums text-muted-foreground">
        {trade.exit_date.slice(5)}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">
        {EXIT_REASON_LABELS[trade.exit_reason] ?? trade.exit_reason}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono text-xs tabular-nums">
        {trade.streak_h >= 2 ? <span className="text-rise">{trade.streak_h} 板</span> : "--"}
      </td>
      <td className={cn(
        "whitespace-nowrap px-3 py-2.5 text-right text-sm font-semibold tabular-nums",
        trade.ret_pct == null ? "text-muted-foreground" : tone(trade.ret_pct),
      )}>
        {trade.ret_pct == null ? "--" : formatPct(trade.ret_pct)}
      </td>
    </tr>
  );
}

interface GroupSummary {
  count: number;
  wins: number;
  avgPct: number | null;
  totalPct: number | null;
}

function summarizeByGroup(days: W2sLedgerDay[]): Record<W2sGroupKey, GroupSummary> {
  const result = Object.fromEntries(
    GROUP_KEYS.map((k) => [k, { count: 0, wins: 0, avgPct: null, totalPct: null }]),
  ) as Record<W2sGroupKey, GroupSummary>;
  for (const key of GROUP_KEYS) {
    let sum = 0;
    for (const day of days) {
      for (const t of day.trades) {
        if (t.group !== key || t.ret_pct == null) continue;
        result[key].count += 1;
        sum += t.ret_pct;
        if (t.ret_pct > 0) result[key].wins += 1;
      }
    }
    if (result[key].count > 0) {
      result[key].avgPct = sum / result[key].count;
      result[key].totalPct = sum;
    }
  }
  return result;
}

function GroupSummaryBar({ summaries }: { summaries: Record<W2sGroupKey, GroupSummary> }) {
  return (
    <div className="grid grid-cols-2 gap-px border-b bg-border md:grid-cols-5">
      {GROUP_KEYS.map((key) => {
        const badge = GROUP_BADGES[key];
        const s = summaries[key];
        const winRate = s.count > 0 ? (s.wins / s.count) * 100 : null;
        return (
          <div key={key}
            className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 bg-card px-3 py-2 text-xs tabular-nums sm:px-4">
            <span className={cn("rounded-full px-1.5 py-px text-[10px] font-medium", badge.className)}>
              {badge.label}
            </span>
            <span className="text-muted-foreground">{s.count} 笔</span>
            <span>
              <span className="text-muted-foreground">胜率 </span>
              <span className="font-medium">{winRate == null ? "--" : `${winRate.toFixed(1)}%`}</span>
            </span>
            <span>
              <span className="text-muted-foreground">均笔 </span>
              <span className={cn("font-medium", tone(s.avgPct))}>{fmtSigned(s.avgPct)}</span>
            </span>
            <span>
              <span className="text-muted-foreground">累计 </span>
              <span className={cn("font-semibold", tone(s.totalPct))}>{fmtSigned(s.totalPct)}</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function fmtSigned(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number | null | undefined) {
  if (value == null) return "";
  return value >= 0 ? "text-rise" : "text-fall";
}
