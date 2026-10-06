import { useMemo, useState } from "react";

import type { HprLedgerDay, HprLedgerMonth, HprLedgerTrade } from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板次日卖",
  next_close_fail: "次日未涨停卖",
  break_close: "断板日卖",
  max_hold_close: "15日兜底卖",
};

// v7.3 交割单切动态组口径:含 K 系出手点(当月弱市组启用的成交笔,紫色系)
const POINT_KEYS = ["A1", "A2", "A3", "B1", "B2", "B3", "C1", "C2", "C3", "K2", "K4", "K5", "K7", "K9", "K3"] as const;

const POINT_BADGES: Record<string, { label: string; className: string }> = {
  A1: { label: "A1", className: "bg-rise/15 text-rise" },
  A2: { label: "A2", className: "bg-teal-500/15 text-teal-500" },
  B1: { label: "B1", className: "bg-amber-500/15 text-amber-500" },
  B2: { label: "B2", className: "bg-yellow-500/15 text-yellow-500" },
  C1: { label: "C1", className: "bg-emerald-500/15 text-emerald-500" },
  A3: { label: "A3", className: "bg-rose-500/15 text-rose-500" },
  B3: { label: "B3", className: "bg-orange-500/15 text-orange-500" },
  C2: { label: "C2", className: "bg-primary/15 text-primary" },
  C3: { label: "C3", className: "bg-primary/15 text-primary" },
  K2: { label: "K2", className: "bg-violet-500/15 text-violet-500" },
  K4: { label: "K4", className: "bg-violet-500/15 text-violet-500" },
  K5: { label: "K5", className: "bg-violet-500/15 text-violet-500" },
  K7: { label: "K7", className: "bg-violet-500/15 text-violet-500" },
  K9: { label: "K9", className: "bg-violet-500/15 text-violet-500" },
  K3: { label: "K3", className: "bg-violet-500/15 text-violet-500" },
};

/** 高位接力历史交割单:横向平铺列表(全部命中信号逐笔,不限仓位),支持月份/点/搜票筛选。 */
export function HprLedgerView({
  ledgerDays,
  months,
  month,
  onMonthChange,
}: {
  ledgerDays: HprLedgerDay[];
  months: HprLedgerMonth[];
  month: string | null;
  onMonthChange: (month: string) => void;
  caliber?: string;
}) {
  const [pointFilter, setPointFilter] = useState<string>("all");
  const [keyword, setKeyword] = useState("");

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return ledgerDays.flatMap((day) =>
      day.trades
        .filter((t) => (pointFilter === "all" || t.point === pointFilter))
        .filter((t) =>
          !kw
          || t.vt_symbol.toLowerCase().includes(kw)
          || (t.name ?? "").toLowerCase().includes(kw),
        )
        .map((t) => ({ day, trade: t })),
    );
  }, [ledgerDays, pointFilter, keyword]);

  const pointSummaries = useMemo(
    () => summarizeByPoint(ledgerDays),
    [ledgerDays],
  );

  if (!ledgerDays.length) {
    return <EmptyState message="该月暂无交割记录——先在回测页运行一次「重新计算」,或切换其他月份" />;
  }

  return (
    <section aria-label="高位接力历史交割单" className="rounded-lg border">
      <div className="border-b px-4 py-2 text-xs text-muted-foreground">
        回测模拟口径(非实盘):<span className="text-foreground">动态口诀组纪律——每月自动切换启用组(近一年哪组赚得多用哪组),当月未启用组的命中不成交</span>(2020 上半年双开期两组都出手/2020-07~2023-06 弱市组 K 系/2023-08 起强市组八条)
        ;成交笔触板买涨停价,炸板次日走(T+1)/封住→断板日卖(15日兜底,E3口径);收益列=E3,对照列E0=持有到断板;不限仓位。同票持仓未退时的新信号标「持仓中」——真实买不进(T+1+一票一份),显示但不进收益汇总。实时前推成交随产品上线逐日沉淀。
      </div>

      <PointSummaryBar summaries={pointSummaries} />

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
          {(["all", ...POINT_KEYS] as const).map((pk) => (
            <button
              key={pk}
              type="button"
              onClick={() => setPointFilter(pk)}
              className={cn(
                "px-3 py-1 text-xs",
                pointFilter === pk ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground",
              )}
            >
              {pk === "all" ? "全部" : pk}
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
        <EmptyState message="无匹配记录" description="调整方案点筛选或搜索关键字" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1080px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">日期</th>
                <th className="px-3 py-2 text-left font-medium">股票</th>
                <th className="px-3 py-2 text-left font-medium">点</th>
                <th className="px-3 py-2 text-left font-medium">组</th>
                <th className="px-3 py-2 text-right font-medium">竞价</th>
                <th className="px-3 py-2 text-right font-medium">买入价</th>
                <th className="px-3 py-2 text-right font-medium">首触</th>
                <th className="px-3 py-2 text-right font-medium">卖出价</th>
                <th className="px-3 py-2 text-right font-medium">卖出日</th>
                <th className="px-3 py-2 text-left font-medium">卖出原因</th>
                <th className="px-3 py-2 text-right font-medium">持有板数</th>
                <th className="px-3 py-2 text-right font-medium">收益E3</th>
                <th className="px-3 py-2 text-right font-medium">对照E0</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map(({ day, trade }) => (
                <LedgerRow key={`${day.trade_date}-${trade.vt_symbol}`} day={day.trade_date} trade={trade} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LedgerRow({ day, trade }: { day: string; trade: HprLedgerTrade }) {
  const badge = POINT_BADGES[trade.point] ?? null;
  return (
    <tr className={trade.overlap ? "opacity-50" : undefined}>
      <td className="px-3 py-2 font-mono tabular-nums text-xs text-muted-foreground">{day}</td>
      <td className="px-3 py-2">
        <StockIdentityLink name={trade.name ?? trade.vt_symbol} vtSymbol={trade.vt_symbol} />
      </td>
      <td className="px-3 py-2">
        {badge ? (
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)}>
            {badge.label}
            {trade.level === "A" ? "·出" : "·轻"}
          </span>
        ) : null}
        {trade.overlap ? (
          <span className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px] text-muted-foreground" title="前一笔尚未退出(T+1+一票一份),真实买不进">
            持仓中
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">{trade.group4}</td>
      <td className={cn("px-3 py-2 text-right font-mono tabular-nums", tone(trade.auction_pct))}>
        {trade.auction_pct == null ? "--" : formatPct(trade.auction_pct)}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">{formatPrice(trade.entry_price)}</td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
        {trade.touch ?? "--"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">{formatPrice(trade.exit_price)}</td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
        {trade.exit_date ?? "--"}
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">
        {trade.exit_reason ? EXIT_REASON_LABELS[trade.exit_reason] ?? trade.exit_reason : "--"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-muted-foreground">
        {trade.sealed ? `${trade.streak_h}板` : "炸板"}
      </td>
      <td className={cn("px-3 py-2 text-right font-mono tabular-nums font-medium", tone(trade.ret_pct))}>
        {trade.ret_pct == null ? "--" : formatPct(trade.ret_pct)}
      </td>
      <td className={cn("px-3 py-2 text-right font-mono tabular-nums text-muted-foreground", tone(trade.ret_e0))}>
        {trade.ret_e0 == null ? "--" : formatPct(trade.ret_e0)}
      </td>
    </tr>
  );
}

function PointSummaryBar({
  summaries,
}: {
  summaries: { point: string; count: number; win_rate: number | null; avg_ret_pct: number | null }[];
}) {
  if (!summaries.length) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 border-b px-4 py-2 text-xs text-muted-foreground">
      {summaries.map((s) => (
        <span key={s.point}>
          <span className="font-medium text-foreground">{s.point}</span> {s.count}笔 · 胜
          {s.win_rate == null ? "--" : `${s.win_rate.toFixed(0)}%`} · 均
          {s.avg_ret_pct == null ? "--" : formatPct(s.avg_ret_pct)}
        </span>
      ))}
    </div>
  );
}

function summarizeByPoint(days: HprLedgerDay[]) {
  const acc = new Map<string, { count: number; win: number; sum: number }>();
  for (const day of days) {
    for (const t of day.trades) {
      if (t.ret_pct == null) continue;
      if (t.overlap) continue; // 同票持仓中未成交,不进收益汇总
      const key = t.point || "—";
      const v = acc.get(key) ?? { count: 0, win: 0, sum: 0 };
      v.count += 1;
      v.sum += t.ret_pct;
      if (t.ret_pct > 0) v.win += 1;
      acc.set(key, v);
    }
  }
  return [...acc.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([point, v]) => ({
      point,
      count: v.count,
      win_rate: v.count ? (v.win / v.count) * 100 : null,
      avg_ret_pct: v.count ? v.sum / v.count : null,
    }));
}

function tone(value: number | null | undefined) {
  if (value == null) return "";
  return value >= 0 ? "text-rise" : "text-fall";
}
