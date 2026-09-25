import { useMemo, useState } from "react";

import type { FbbGroup6, FbbLedgerDay, FbbLedgerMonth, FbbLedgerTrade, FbbPoint } from "@/api/fanbao";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板当日·收盘卖",
  next_close_fail: "次日未涨停·收盘卖",
  break_close: "断板日收盘卖",
  max_hold_close: "15日兜底·收盘卖",
};

const POINT_KEYS = ["S1", "S2", "S3", "O1", "O2"] as const;
const GROUP6_KEYS: FbbGroup6[] = ["2板阴", "2板阳", "4板阴", "4板阳", "5+板阴", "5+板阳"];

const POINT_BADGES: Record<string, { label: string; className: string }> = {
  S1: { label: "S1", className: "bg-rise/15 text-rise" },
  S2: { label: "S2", className: "bg-amber-500/15 text-amber-500" },
  S3: { label: "S3", className: "bg-primary/15 text-primary" },
  O1: { label: "O1", className: "bg-violet-500/15 text-violet-500" },
  O2: { label: "O2", className: "bg-orange-500/15 text-orange-500" },
};

/** 断板反包历史交割单:好票/坏票两分组平铺(=好差票验证月度文件的产品化等价)。 */
export function FbbLedgerView({
  ledgerDays,
  months,
  month,
  onMonthChange,
}: {
  ledgerDays: FbbLedgerDay[];
  months: FbbLedgerMonth[];
  month: string | null;
  onMonthChange: (month: string) => void;
  caliber?: string;
}) {
  const [pointFilter, setPointFilter] = useState<FbbPoint | "all">("all");
  const [groupFilter, setGroupFilter] = useState<FbbGroup6 | "all">("all");
  const [keyword, setKeyword] = useState("");

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    return ledgerDays.flatMap((day) =>
      day.trades
        .filter((t) => (pointFilter === "all" || t.point === pointFilter))
        .filter((t) => (groupFilter === "all" || t.group6 === groupFilter))
        .filter((t) =>
          !kw
          || t.vt_symbol.toLowerCase().includes(kw)
          || (t.name ?? "").toLowerCase().includes(kw),
        )
        .map((t) => ({ day, trade: t })),
    );
  }, [ledgerDays, pointFilter, groupFilter, keyword]);

  const pointSummaries = useMemo(
    () => summarizeByPoint(ledgerDays),
    [ledgerDays],
  );
  const badRows = rows.filter((r) => r.trade.is_bad);
  const goodRows = rows.filter((r) => !r.trade.is_bad);

  if (!ledgerDays.length) {
    return <EmptyState message="该月暂无交割记录——先在回测页运行一次「重新计算」,或切换其他月份" />;
  }

  return (
    <section aria-label="断板反包历史交割单" className="space-y-4">
      <div className="rounded-lg border">
        <div className="border-b px-4 py-2 text-xs text-muted-foreground">
          回测模拟口径(非实盘):触板买涨停价(一字排除,T字可买),反包日炸板当日收盘走/封住→断板收盘卖(15日兜底)
          ;坏票=次日收盘低于买价(炸板但第二天涨回来的算好票);全部方案点命中信号逐笔,不限仓位。实时前推成交随产品上线逐日沉淀。
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
                  {m.month} · {m.count}笔 · 坏{m.bad} · 均{m.avg_ret_pct == null ? "--" : formatPct(m.avg_ret_pct)}
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
                {pk === "all" ? "全部点" : pk}
              </button>
            ))}
          </span>
          <span className="inline-flex border">
            {(["all", ...GROUP6_KEYS] as const).map((gk) => (
              <button
                key={gk}
                type="button"
                onClick={() => setGroupFilter(gk)}
                className={cn(
                  "px-3 py-1 text-xs",
                  groupFilter === gk ? "bg-primary/15 font-medium text-primary" : "text-muted-foreground",
                )}
              >
                {gk === "all" ? "全部组" : gk}
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
          <span className="text-xs text-muted-foreground">
            {rows.length} 条 · 坏票 {badRows.length} · 好票 {goodRows.length}
          </span>
        </div>
      </div>

      <TradeBlock
        title={`坏票 — ${badRows.length} 笔`}
        tone="text-fall"
        description="次日收盘低于买价(含炸板票与封住但次日走弱的票)"
        rows={badRows}
        showStreak={false}
      />
      <TradeBlock
        title={`好票 — ${goodRows.length} 笔`}
        tone="text-rise"
        description="次日收盘不低于买价(炸板但第二天涨回来的也算好票)"
        rows={goodRows}
        showStreak
      />
    </section>
  );
}

function TradeBlock({
  title,
  tone,
  description,
  rows,
  showStreak,
}: {
  title: string;
  tone: string;
  description: string;
  rows: { day: FbbLedgerDay; trade: FbbLedgerTrade }[];
  showStreak: boolean;
}) {
  return (
    <section aria-label={title} className="rounded-lg border">
      <div className={cn("border-b px-4 py-2", tone)}>
        <span className="text-sm font-semibold">{title}</span>
        <span className="ml-3 text-xs text-muted-foreground">{description}</span>
      </div>
      {rows.length === 0 ? (
        <EmptyState message="无记录" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1180px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">日期</th>
                <th className="px-3 py-2 text-left font-medium">股票</th>
                <th className="px-3 py-2 text-left font-medium">点</th>
                <th className="px-3 py-2 text-left font-medium">组</th>
                <th className="px-3 py-2 text-right font-medium">断</th>
                <th className="px-3 py-2 text-right font-medium">累计%</th>
                <th className="px-3 py-2 text-right font-medium">阴线数</th>
                <th className="px-3 py-2 text-right font-medium">末开%</th>
                <th className="px-3 py-2 text-right font-medium">坑深%</th>
                <th className="px-3 py-2 text-right font-medium">买入价</th>
                <th className="px-3 py-2 text-left font-medium">结果</th>
                {showStreak ? <th className="px-3 py-2 text-right font-medium">持有板数</th> : null}
                <th className="px-3 py-2 text-left font-medium">卖出原因</th>
                <th className="px-3 py-2 text-right font-medium">卖出日</th>
                <th className="px-3 py-2 text-right font-medium">收益</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map(({ day, trade }) => (
                <LedgerRow
                  key={`${day.trade_date}-${trade.vt_symbol}`}
                  day={day.trade_date}
                  trade={trade}
                  showStreak={showStreak}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LedgerRow({ day, trade, showStreak }: { day: string; trade: FbbLedgerTrade; showStreak: boolean }) {
  const badge = POINT_BADGES[trade.point] ?? null;
  return (
    <tr>
      <td className="px-3 py-2 font-mono tabular-nums text-xs text-muted-foreground">{day}</td>
      <td className="px-3 py-2">
        <StockIdentityLink name={trade.name ?? trade.vt_symbol} vtSymbol={trade.vt_symbol} />
      </td>
      <td className="px-3 py-2">
        {badge ? (
          <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)}>
            {badge.label}
            {trade.level === "S" ? "·出" : "·观"}
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs text-muted-foreground">
        {trade.group6}({trade.n_board}板)
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-xs text-muted-foreground">
        断{trade.gap}
      </td>
      <td className={cn("px-3 py-2 text-right font-mono tabular-nums text-xs", tone(trade.break_drop_pct))}>
        {trade.break_drop_pct == null ? "--" : trade.break_drop_pct.toFixed(1)}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-xs text-muted-foreground">
        {trade.break_yin_count}
      </td>
      <td className={cn("px-3 py-2 text-right font-mono tabular-nums text-xs",
        trade.high_var ? "font-semibold text-amber-500" : "text-muted-foreground")}
          title={trade.high_var ? "⚠顶格开走低:胜率五五开,轻仓" : undefined}>
        {trade.high_var ? "⚠" : ""}{trade.last_open_pct == null ? "--" : trade.last_open_pct.toFixed(1)}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-xs text-muted-foreground">
        {trade.pit_depth_pct == null ? "--" : trade.pit_depth_pct.toFixed(1)}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">{formatPrice(trade.entry_price)}</td>
      <td className="px-3 py-2 text-xs">
        <span className={cn(trade.result === "炸板" || trade.result === "封次日负" ? "text-fall" : "text-rise")}>
          {trade.result}
        </span>
      </td>
      {showStreak ? (
        <td className="px-3 py-2 text-right font-mono tabular-nums text-xs text-muted-foreground">
          {trade.sealed ? `${trade.streak_h}板` : "炸板"}
        </td>
      ) : null}
      <td className="px-3 py-2 text-xs text-muted-foreground">
        {trade.exit_reason ? EXIT_REASON_LABELS[trade.exit_reason] ?? trade.exit_reason : "--"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-xs text-muted-foreground">
        {trade.exit_date ?? "--"}
      </td>
      <td className={cn("px-3 py-2 text-right font-mono tabular-nums font-medium", tone(trade.ret_pct))}>
        {trade.ret_pct == null ? "--" : formatPct(trade.ret_pct)}
      </td>
    </tr>
  );
}

function PointSummaryBar({
  summaries,
}: {
  summaries: { point: string; count: number; win_rate: number | null; avg_ret_pct: number | null; bad: number }[];
}) {
  if (!summaries.length) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 border-b px-4 py-2 text-xs text-muted-foreground">
      {summaries.map((s) => (
        <span key={s.point}>
          <span className="font-medium text-foreground">{s.point}</span> {s.count}笔 · 胜
          {s.win_rate == null ? "--" : `${s.win_rate.toFixed(0)}%`} · 均
          {s.avg_ret_pct == null ? "--" : formatPct(s.avg_ret_pct)} · 坏{s.bad}
        </span>
      ))}
    </div>
  );
}

function summarizeByPoint(days: FbbLedgerDay[]) {
  const acc = new Map<string, { count: number; win: number; bad: number; sum: number }>();
  for (const day of days) {
    for (const t of day.trades) {
      if (t.ret_pct == null) continue;
      const key = t.point || "—";
      const v = acc.get(key) ?? { count: 0, win: 0, bad: 0, sum: 0 };
      v.count += 1;
      v.sum += t.ret_pct;
      if (t.ret_pct > 0) v.win += 1;
      if (t.is_bad) v.bad += 1;
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
      bad: v.bad,
    }));
}

function tone(value: number | null | undefined) {
  if (value == null) return "";
  return value >= 0 ? "text-rise" : "text-fall";
}
