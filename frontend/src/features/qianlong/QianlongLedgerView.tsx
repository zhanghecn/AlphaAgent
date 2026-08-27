import { useMemo, useState } from "react";

import type { QianlongLedgerDay, QianlongLedgerMonth, QianlongLedgerTrade } from "@/api/qianlong";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const EXIT_REASON_LABELS: Record<string, string> = {
  next_open_fail: "未封板·次日开盘卖",
  next_open_nostreak: "未连板·次日开盘卖",
  break_open: "断板日卖",
};

const WEEKDAYS = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];

/** 潜龙首板历史交割单:横向平铺列表(全部触发信号逐笔,不限仓位),支持月份/搜票筛选。 */
export function QianlongLedgerView({
  ledgerDays,
  months,
  month,
  onMonthChange,
  caliber,
}: {
  ledgerDays: QianlongLedgerDay[];
  months: QianlongLedgerMonth[];
  month: string | null;
  onMonthChange: (month: string) => void;
  caliber?: string;
}) {
  const [keyword, setKeyword] = useState("");

  const rows = useMemo(() => {
    const kw = keyword.trim().toLowerCase();
    const merged: { day: QianlongLedgerDay; trade: QianlongLedgerTrade | null }[] = [];
    for (const day of ledgerDays) {
      const matches = day.trades.filter((t) =>
        !kw
        || t.vt_symbol.toLowerCase().includes(kw)
        || (t.name ?? "").toLowerCase().includes(kw),
      );
      // 零开张日(建池但无信号触及)渲染为占位行,证明当日已覆盖
      if (!matches.length && !kw) merged.push({ day, trade: null });
      else for (const t of matches) merged.push({ day, trade: t });
    }
    return merged;
  }, [ledgerDays, keyword]);

  const summary = useMemo(() => {
    let count = 0;
    let wins = 0;
    let sum = 0;
    let monthRet = 0;
    for (const day of ledgerDays) {
      if (day.avg_ret_pct != null) monthRet += day.avg_ret_pct;
      for (const t of day.trades) {
        if (t.ret_pct == null) continue;
        count += 1;
        sum += t.ret_pct;
        if (t.ret_pct > 0) wins += 1;
      }
    }
    return {
      count,
      winRate: count > 0 ? (wins / count) * 100 : null,
      avgPct: count > 0 ? sum / count : null,
      monthRet,
    };
  }, [ledgerDays]);

  if (!ledgerDays.length) {
    return <EmptyState message="该月暂无交割记录——先在回测页运行一次「重新计算」,或切换其他月份" />;
  }

  return (
    <section aria-label="潜龙首板历史交割单" className="rounded-lg border">
      <div className="border-b px-4 py-2 text-xs text-muted-foreground">
        回测模拟口径(非实盘):{caliber ?? "日线保守下限,含 0.5% 滑点"}
        ;全部触发信号逐笔展示,不限仓位(仓位约束只影响回测页的模拟仓净值曲线)。实时前推成交随产品上线逐日沉淀。
      </div>

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 border-b px-4 py-2 text-xs tabular-nums">
        <span className="text-muted-foreground">当月合计</span>
        <span className="text-muted-foreground">{summary.count} 笔</span>
        <span>
          <span className="text-muted-foreground">胜率 </span>
          <span className="font-medium">
            {summary.winRate == null ? "--" : `${summary.winRate.toFixed(1)}%`}
          </span>
        </span>
        <span>
          <span className="text-muted-foreground">均笔 </span>
          <span className={cn("font-medium", tone(summary.avgPct))}>{fmtSigned(summary.avgPct)}</span>
        </span>
        <span>
          <span className="text-muted-foreground">月收益 </span>
          <span className={cn("font-semibold", tone(summary.monthRet))}>{fmtSigned(summary.monthRet)}</span>
        </span>
        <span className="text-muted-foreground">(月收益=每个信号日满仓当日全部信号赚一次当日均值,非复利)</span>
      </div>

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
                {m.month} · {m.count}笔 · 月收益{m.month_ret_pct == null ? "--" : formatPct(m.month_ret_pct)}
              </option>
            ))}
          </select>
        </label>
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
        <EmptyState message="无匹配记录" description="调整搜索关键字" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] text-sm">
            <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">日期</th>
                <th className="px-3 py-2 text-left font-medium">股票</th>
                <th className="px-3 py-2 text-right font-medium">高开</th>
                <th className="px-3 py-2 text-right font-medium">买入价</th>
                <th className="px-3 py-2 text-right font-medium">卖出价</th>
                <th className="px-3 py-2 text-right font-medium">卖出日</th>
                <th className="px-3 py-2 text-left font-medium">卖出原因</th>
                <th className="px-3 py-2 text-right font-medium">连板高度</th>
                <th className="px-3 py-2 text-right font-medium">收益</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {rows.map(({ day, trade }) =>
                trade === null ? (
                  <tr key={`zero-${day.trade_date}`}>
                    <td className="whitespace-nowrap px-3 py-2.5 text-xs tabular-nums">
                      <div>{day.trade_date.slice(5)}</div>
                      <div className="text-muted-foreground">{WEEKDAYS[new Date(`${day.trade_date}T00:00:00`).getDay()]}</div>
                    </td>
                    <td className="px-3 py-2.5 text-xs text-muted-foreground" colSpan={8}>
                      建池但当日无信号触及 +8%（未开张）
                    </td>
                  </tr>
                ) : (
                  <LedgerRow key={`${day.trade_date}-${trade.vt_symbol}`}
                    day={day.trade_date} trade={trade} />
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function LedgerRow({ day, trade }: { day: string; trade: QianlongLedgerTrade }) {
  const weekday = WEEKDAYS[new Date(`${day}T00:00:00`).getDay()];
  return (
    <tr>
      <td className="whitespace-nowrap px-3 py-2.5 text-xs tabular-nums">
        <div>{day.slice(5)}</div>
        <div className="text-muted-foreground">{weekday}</div>
      </td>
      <td className="px-3 py-2.5">
        <span className="inline-flex items-center gap-1.5">
          <StockIdentityLink name={trade.name} vtSymbol={trade.vt_symbol} />
          {trade.chassis_tag ? (
            <span
              className={trade.chassis_tag.includes("B")
                ? "rounded bg-primary/15 px-1 py-0.5 text-[10px] text-primary"
                : "rounded bg-muted/60 px-1 py-0.5 text-[10px] text-muted-foreground"}
            >
              {trade.chassis_tag}
            </span>
          ) : null}
        </span>
      </td>
      <td className={cn("whitespace-nowrap px-3 py-2.5 text-right text-xs tabular-nums", tone(trade.gap_open_pct))}>
        {trade.gap_open_pct == null ? "--" : formatPct(trade.gap_open_pct)}
      </td>
      <td className="whitespace-nowrap px-3 py-2.5 text-right font-mono text-xs tabular-nums">
        {formatPrice(trade.entry_price)}
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

function fmtSigned(value: number | null): string {
  if (value == null || Number.isNaN(value)) return "--";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function tone(value: number | null | undefined) {
  if (value == null) return "";
  return value >= 0 ? "text-rise" : "text-fall";
}
