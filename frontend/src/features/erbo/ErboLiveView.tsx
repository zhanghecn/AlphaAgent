import type { ErboLiveEntry, ErboLivePayload } from "@/api/erbo";
import { cn, formatPrice } from "@/lib/utils";

/** 档位徽章(A 金边出手 / B 高方差出手 / 死格灰) */
const POINT_BADGES: Record<string, { label: string; full: string; className: string }> = {
  A: { label: "A", full: "A档 平开企稳(末日开-2~+2%,洗完了)", className: "bg-primary/15 text-primary ring-1 ring-primary/40" },
  B: { label: "B", full: "B档 深低开杀透(末日开≤-4%,恐慌盘出清)", className: "bg-rise/15 text-rise ring-1 ring-rise/40" },
};

const STATUS_LABELS: Record<string, string> = {
  watching: "监控中", sealed_watch: "T字观察", entered: "已入场",
  holding: "在持", closed: "已了结", no_trigger: "未触发", skipped_gap: "一字未开",
};

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板次日·收盘卖",
  next_close_fail: "次日断板卖",
  break_close: "断板日卖",
  max_hold_close: "15日兜底卖",
};

export function ErboLiveView({
  payload,
  availableDates,
  selectedDate,
  onDateChange,
}: {
  payload: ErboLivePayload;
  availableDates: string[];
  selectedDate: string | null;
  onDateChange: (d: string | null) => void;
}) {
  const entries = payload.entries ?? [];
  const actionable = entries.filter((e) => e.actionable);
  const radar = entries.filter((e) => !e.actionable);
  return (
    <div className="space-y-4">
      <section className="rounded-lg border px-4 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">
            二波反包 · {payload.trade_date}
          </span>
          <span>规则 {payload.rules_version}</span>
          <span>
            池 {payload.counts.pool} · 出手 {payload.counts.actionable}（
            {Object.entries(payload.counts.by_point).map(([k, v]) => `${k}档${v}`).join(" · ") || "无"}）
          </span>
          {payload.stale ? <span className="text-amber-600">（非今日池,回看）</span> : null}
          {payload.last_scan ? (
            <span className="ml-auto">
              扫描 {payload.last_scan.status} · {payload.last_scan.finished_at?.slice(11, 19) ?? "--"}
            </span>
          ) : null}
        </div>
        {availableDates.length > 0 ? (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <span className="text-[11px]">回看</span>
            <button
              type="button"
              className={cn(
                "rounded border px-2 py-0.5 text-[11px]",
                selectedDate == null ? "border-primary bg-primary/10 font-semibold text-primary" : "hover:bg-muted/40",
              )}
              onClick={() => onDateChange(null)}
            >
              最新
            </button>
            {availableDates.slice(0, 12).map((d) => (
              <button
                key={d}
                type="button"
                className={cn(
                  "rounded border px-2 py-0.5 text-[11px] tabular-nums",
                  selectedDate === d ? "border-primary bg-primary/10 font-semibold text-primary" : "hover:bg-muted/40",
                )}
                onClick={() => onDateChange(d)}
              >
                {d.slice(5)}
              </button>
            ))}
          </div>
        ) : null}
      </section>

      <section className="rounded-lg border">
        <div className="border-b px-4 py-2 text-xs text-muted-foreground">
          出手名单（✅ 触板即买,按涨停价;⚠情绪冰点=昨日全市场涨停&lt;40家减半仓）
        </div>
        <EntryTable entries={actionable} emptyText="今日无出手票(妖股二波结构空窗)" highlight />
      </section>

      <section className="rounded-lg border">
        <div className="border-b px-4 py-2 text-xs text-muted-foreground">
          雷达（结构满足但死格/未打档——只看不做）
        </div>
        <EntryTable entries={radar} emptyText="无雷达票" />
      </section>

      <p className="text-[11px] leading-5 text-muted-foreground">
        二波反包=妖股波段(30日+50~80%)深洗后(-8~-15%,不破MA20)再触板。昨天必须收阴;
        末日开盘 A 平开(-2~+2)/B 深低开(≤-4)才出手,浅低开(-4~-2)和高开(&gt;+2)是死格。
        买入当天炸板→第二天收盘卖(T+1);封住→断板日收盘卖,最多15天。
        鱼尾二波赚的是一两天延续,不是大肉——见好就收。
      </p>
    </div>
  );
}

function EntryTable({
  entries,
  emptyText,
  highlight,
}: {
  entries: ErboLiveEntry[];
  emptyText: string;
  highlight?: boolean;
}) {
  if (entries.length === 0) {
    return <div className="px-4 py-6 text-center text-xs text-muted-foreground">{emptyText}</div>;
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1080px] text-sm">
        <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left font-medium">股票</th>
            <th className="px-3 py-2 text-left font-medium">档</th>
            <th className="px-3 py-2 text-right font-medium">断</th>
            <th className="px-3 py-2 text-right font-medium">波段%</th>
            <th className="px-3 py-2 text-right font-medium">洗%</th>
            <th className="px-3 py-2 text-right font-medium">MA20距</th>
            <th className="px-3 py-2 text-right font-medium">涨停数</th>
            <th className="px-3 py-2 text-right font-medium">末开%</th>
            <th className="px-3 py-2 text-right font-medium">涨停价</th>
            <th className="px-3 py-2 text-left font-medium">状态</th>
            <th className="px-3 py-2 text-right font-medium">现价/涨幅</th>
            <th className="px-3 py-2 text-left font-medium">结果</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {entries.map((e) => {
            const badge = POINT_BADGES[e.point];
            return (
              <tr key={e.vt_symbol} className={cn(highlight && e.point !== "—" && "bg-primary/[0.03]")}>
                <td className="px-3 py-2">
                  <a
                    className="group block min-w-0 rounded-sm"
                    title={`打开 ${e.name ?? e.vt_symbol}`}
                    href={`/stocks/${e.vt_symbol}`}
                  >
                    <div className="truncate font-medium text-primary group-hover:underline">
                      {e.name ?? e.vt_symbol}
                    </div>
                    <div className="truncate text-xs text-muted-foreground">{e.vt_symbol}</div>
                  </a>
                </td>
                <td className="px-3 py-2">
                  {badge ? (
                    <span title={badge.full} className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)}>
                      {badge.label}
                      {e.cold_market ? " ⚠冰点" : ""}
                    </span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground" title={e.avoid_static ?? undefined}>
                      死格
                    </span>
                  )}
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs text-muted-foreground">{e.gap}天</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmt(e.gain30_pct)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs text-fall">{fmt(e.dd_pct)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmt(e.ma20gap_pct)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs text-muted-foreground">{e.lim30 ?? "--"}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{fmt(e.last_open_pct)}</td>
                <td className="px-3 py-2 text-right font-mono text-xs">{e.limit_price != null ? formatPrice(e.limit_price) : "--"}</td>
                <td className="px-3 py-2 text-xs">
                  {STATUS_LABELS[e.status] ?? e.status}
                  {e.touched_at ? (
                    <span className="ml-1 text-[10px] text-muted-foreground">{e.touched_at.slice(11, 16)}</span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right font-mono text-xs tabular-nums">
                  {e.last_price != null ? formatPrice(e.last_price) : "--"}
                  {e.change_pct != null ? (
                    <span className={cn("ml-1", e.change_pct >= 0 ? "text-rise" : "text-fall")}>
                      {e.change_pct >= 0 ? "+" : ""}{e.change_pct.toFixed(1)}%
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-xs">
                  {e.status === "closed" ? (
                    <span className={cn("font-mono", (e.ret_pct ?? 0) >= 0 ? "text-rise" : "text-fall")}>
                      {e.ret_pct != null ? `${e.ret_pct >= 0 ? "+" : ""}${e.ret_pct.toFixed(1)}%` : "--"}
                      <span className="ml-1 text-[10px] text-muted-foreground">
                        {EXIT_REASON_LABELS[e.exit_reason ?? ""] ?? ""}
                      </span>
                    </span>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function fmt(v: number | null | undefined): string {
  if (v == null) return "--";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}`;
}
