import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, ChevronDown, Clock, RefreshCw } from "lucide-react";

import {
  fetchW2sRules,
  type W2sGroupKey,
  type W2sLiveEntry,
  type W2sLivePayload,
} from "@/api/weakToStrong";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const SESSION_LABELS: Record<string, string> = {
  preopen: "盘前",
  auction: "竞价时段",
  morning: "上午盘",
  lunch: "午间休市",
  afternoon: "下午盘",
  closed: "已收盘",
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  watching: { label: "待触发", className: "text-muted-foreground" },
  touched: { label: "已触及", className: "text-amber-500" },
  entered: { label: "已买入", className: "text-rise font-semibold" },
  holding: { label: "持有中", className: "text-rise font-semibold" },
  pending_exit: { label: "待次日卖", className: "text-amber-600" },
  closed: { label: "已了结", className: "text-muted-foreground" },
  skipped_gap: { label: "竞价外·放弃", className: "text-muted-foreground line-through" },
  halted: { label: "停手日·不做", className: "text-muted-foreground line-through" },
  no_trigger: { label: "未触发", className: "text-muted-foreground/60" },
};

const EXIT_REASON_LABELS: Record<string, string> = {
  next_close_fail: "次日未涨停·收盘卖",
  break_close: "断板日收盘卖",
  max_hold_close: "15日兜底·收盘卖",
  same_day_fail: "当日未封·尾盘卖",
  open_end: "持有中",
};

const GROUP_BADGES: Record<W2sGroupKey, { label: string; className: string }> = {
  a1: { label: "A1 恐慌出清", className: "bg-primary/15 text-primary" },
  a2: { label: "A2 强势整理", className: "bg-rise/15 text-rise" },
  b: { label: "B 高位弱转强", className: "bg-amber-500/15 text-amber-500" },
};

export function W2sLiveView({
  payload,
  availableDates,
  selectedDate,
  onDateChange,
}: {
  payload: W2sLivePayload;
  availableDates: string[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
}) {
  const rulesQuery = useQuery({
    queryKey: ["w2sRules"],
    queryFn: fetchW2sRules,
    staleTime: 300_000,
  });
  const [playbookOpen, setPlaybookOpen] = useState(false);
  const [windowOpen, setWindowOpen] = useState(false);
  const halt = payload.market_halt;
  const entries = payload.entries ?? [];
  const thsConditions = rulesQuery.data?.ths_pool_conditions;
  const playbook = rulesQuery.data?.intraday_playbook ?? [];
  const sessionWindow = rulesQuery.data?.session_window;
  const byGroup = payload.counts.by_group ?? {};
  const byStatus = payload.counts.by_status ?? {};

  return (
    <div className="space-y-4">
      <section aria-label="趋势弱转强实时推荐" className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">趋势弱转强 · 实时推荐</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">
              非当日(最新可用池)
            </span>
          ) : null}
          <span>池 {payload.counts.pool ?? 0}</span>
          <span className="text-primary">A1 {byGroup.a1 ?? 0}</span>
          <span className="text-rise">A2 {byGroup.a2 ?? 0}</span>
          <span className="text-amber-500">B {byGroup.b ?? 0}</span>
          <span className="text-rise">已买入 {byStatus.entered ?? 0}</span>
          <span className="text-rise">持有 {byStatus.holding ?? 0}</span>
          <span>已了结 {byStatus.closed ?? 0}</span>
          {payload.last_scan ? (
            <span className="flex items-center gap-1 tabular-nums">
              <RefreshCw size={12} />
              {formatScanTime(payload.last_scan.finished_at)}
            </span>
          ) : (
            <span>等待盘中扫描(09:30 起每分钟)</span>
          )}
          <span className="ml-auto flex items-center gap-2">
            <select
              className="h-8 rounded-md border bg-background px-2 text-xs"
              value={selectedDate ?? ""}
              onChange={(e) => onDateChange(e.target.value || null)}
              aria-label="选择回看交易日"
            >
              <option value="">实时</option>
              {availableDates.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
            {thsConditions
              ? (Object.keys(GROUP_BADGES) as W2sGroupKey[]).map((gk) => (
                  <CopyThsConditionsButton
                    key={gk}
                    conditions={thsConditions[gk]}
                    label={`复制${GROUP_BADGES[gk].label.split(" ")[0]}条件`}
                  />
                ))
              : null}
          </span>
        </div>

        {halt.halted ? (
          <div className="flex items-center gap-2 border-b border-fall/30 bg-fall/10 px-4 py-2 text-xs text-fall">
            <AlertOctagon size={14} />
            大盘停手日:昨日主板非ST涨停 {halt.mkt_lim_tm1 ?? "--"} 家(阈值 {halt.threshold}),
            今日整池停手——情绪高潮日池内 -2.12%/35%,不做。
          </div>
        ) : null}

        {sessionWindow ? (
          <div className="border-b border-amber-500/30 bg-amber-500/5 px-4 py-2 text-xs">
            <button
              type="button"
              className="flex w-full items-start gap-2 text-left"
              onClick={() => setWindowOpen((v) => !v)}
              aria-expanded={windowOpen}
            >
              <Clock size={14} className="mt-0.5 shrink-0 text-amber-500" />
              <span className="min-w-0 flex-1">
                <span className="font-medium text-amber-600">{sessionWindow.headline}</span>
                <span className="ml-2 text-muted-foreground">{sessionWindow.warning}</span>
              </span>
              <ChevronDown
                size={13}
                className={cn("mt-0.5 shrink-0 text-muted-foreground", windowOpen && "rotate-180")}
              />
            </button>
            {windowOpen ? (
              <div className="mt-2 space-y-1.5 pl-6">
                {sessionWindow.rows.map((row) => (
                  <div key={row.group} className="flex gap-2">
                    <span
                      className={cn(
                        "shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium",
                        GROUP_BADGES[row.group].className,
                      )}
                    >
                      {GROUP_BADGES[row.group].label}
                    </span>
                    <span className="shrink-0 rounded bg-rise/15 px-1.5 py-0.5 text-[10px] font-medium text-rise">
                      出手期 {row.window}
                    </span>
                    <span className="text-muted-foreground">
                      首触占比 {row.share} · {row.note}
                    </span>
                  </div>
                ))}
                <p className="text-[11px] text-muted-foreground/80">{sessionWindow.research_note}</p>
              </div>
            ) : null}
          </div>
        ) : null}

        <div className="border-b px-4 py-2">
          <button
            type="button"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setPlaybookOpen((v) => !v)}
            aria-expanded={playbookOpen}
          >
            <ChevronDown size={13} className={cn(playbookOpen && "rotate-180")} />
            盘中执行要点(同花顺池建好后对照此执行)
          </button>
          {playbookOpen ? (
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
              {playbook.map((line) => <li key={line}>{line}</li>)}
            </ol>
          ) : null}
        </div>

        {entries.length === 0 ? (
          <div className="p-4">
            <EmptyState message="今日池为空——盘后 19:00 统一更新链会自动计算次日池" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] text-sm">
              <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">股票</th>
                  <th className="px-3 py-2 text-left font-medium">组</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">触发价</th>
                  <th className="px-3 py-2 text-right font-medium">竞价/高开</th>
                  <th className="px-3 py-2 text-right font-medium">现价</th>
                  <th className="px-3 py-2 text-right font-medium">涨幅</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                  <th className="px-3 py-2 text-right font-medium">买入价</th>
                  <th className="px-3 py-2 text-right font-medium">退出</th>
                  <th className="px-3 py-2 text-right font-medium">收益</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <LiveRow key={`${entry.vt_symbol}-${entry.group_key}`} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function LiveRow({ entry }: { entry: W2sLiveEntry }) {
  const meta = STATUS_META[entry.status] ?? STATUS_META.watching;
  const badge = GROUP_BADGES[entry.group_key] ?? GROUP_BADGES.a1;
  const dimmed = ["skipped_gap", "no_trigger", "halted"].includes(entry.status);
  return (
    <tr className={cn("border-b last:border-b-0 hover:bg-muted/30", dimmed && "opacity-50")}>
      <td className="px-3 py-2.5">
        <StockIdentityLink name={entry.name ?? entry.vt_symbol} vtSymbol={entry.vt_symbol} />
      </td>
      <td className="px-3 py-2.5">
        <span className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)}>
          {badge.label}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
        {formatPrice(entry.trigger_price)}
        <span className="ml-1 text-[10px] text-muted-foreground">
          {entry.group_key === "a2" ? "封板价" : "+7%"}
        </span>
      </td>
      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums", pctTone(entry.gap_open_pct))}>
        {entry.gap_open_pct == null ? "--" : formatPct(entry.gap_open_pct)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.last_price)}</td>
      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums", pctTone(entry.change_pct))}>
        {entry.change_pct == null ? "--" : formatPct(entry.change_pct)}
      </td>
      <td className={cn("px-3 py-2.5 text-xs", meta.className)}>
        {meta.label}
        {entry.status === "holding" && entry.streak_h ? `${entry.streak_h}板` : ""}
        {entry.status === "closed" && entry.exit_reason
          ? ` · ${EXIT_REASON_LABELS[entry.exit_reason] ?? entry.exit_reason}`
          : ""}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.entry_price)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">
        {entry.exit_price == null ? "--" : `${formatPrice(entry.exit_price)} / ${entry.exit_date ?? ""}`}
      </td>
      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums", pctTone(entry.ret_pct))}>
        {entry.ret_pct == null ? "--" : formatPct(entry.ret_pct)}
      </td>
    </tr>
  );
}

function pctTone(value: number | null | undefined) {
  if (value == null) return "";
  return value >= 0 ? "text-rise" : "text-fall";
}

function formatScanTime(value: string | null) {
  if (!value) return "未扫描";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "未扫描";
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(d);
  return `${time} 扫描`;
}
