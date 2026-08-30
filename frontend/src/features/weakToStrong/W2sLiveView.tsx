import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, RefreshCw } from "lucide-react";

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
  skipped_gap: { label: "一字·买不进", className: "text-muted-foreground line-through" },
  no_trigger: { label: "未触发", className: "text-muted-foreground/60" },
};

const EXIT_REASON_LABELS: Record<string, string> = {
  next_close_fail: "次日未涨停·收盘卖",
  break_close: "断板日收盘卖",
  max_hold_close: "20日兜底·收盘卖",
  open_end: "持有中",
};

/** 五组硬编码映射:label=短标签(徽标/计数条用),full=全标签(悬浮提示用)。 */
const GROUP_BADGES: Record<W2sGroupKey, { label: string; full: string; className: string }> = {
  yin2: { label: "2板阴", full: "2板阴·U坑", className: "bg-primary/15 text-primary" },
  yang2a: { label: "首阳", full: "2板阳·首阳", className: "bg-rise/15 text-rise" },
  yang2b: { label: "纠缠", full: "2板阳·纠缠", className: "bg-orange-500/15 text-orange-500" },
  yin4: { label: "4+阴", full: "4+阴·孤板", className: "bg-violet-500/15 text-violet-500" },
  yang4: { label: "4+阳", full: "4+阳·穿插", className: "bg-amber-500/15 text-amber-500" },
};

const GROUP_KEYS = Object.keys(GROUP_BADGES) as W2sGroupKey[];

const GROUP_COUNT_TONE: Record<W2sGroupKey, string> = {
  yin2: "text-primary",
  yang2a: "text-rise",
  yang2b: "text-orange-500",
  yin4: "text-violet-500",
  yang4: "text-amber-500",
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
  const entries = payload.entries ?? [];
  const thsConditions = rulesQuery.data?.ths_pool_conditions;
  const playbook = rulesQuery.data?.intraday_playbook ?? [];
  const byGroup = payload.counts.by_group ?? {};
  const byStatus = payload.counts.by_status ?? {};

  return (
    <div className="space-y-4">
      <section aria-label="U型补涨打板实时推荐" className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">U型补涨打板 · 实时推荐</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">
              非当日(最新可用池)
            </span>
          ) : null}
          <span>池 {payload.counts.pool ?? 0}</span>
          {GROUP_KEYS.map((gk) => (
            <span key={gk} className={GROUP_COUNT_TONE[gk]}>
              {GROUP_BADGES[gk].label} {byGroup[gk] ?? 0}
            </span>
          ))}
          <span className="font-semibold text-rise">出手 {payload.counts.actionable ?? 0}</span>
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
              ? GROUP_KEYS.map((gk) => (
                  <CopyThsConditionsButton
                    key={gk}
                    conditions={thsConditions[gk]}
                    label={`复制${GROUP_BADGES[gk].label}条件`}
                  />
                ))
              : null}
          </span>
        </div>

        <div className="border-b px-4 py-2">
          <button
            type="button"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => setPlaybookOpen((v) => !v)}
            aria-expanded={playbookOpen}
          >
            <ChevronDown size={13} className={cn(playbookOpen && "rotate-180")} />
            盘中执行要点(板上买,只对✅出手的票触发)
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
                  <th className="px-3 py-2 text-left font-medium">U状态</th>
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
  const badge = GROUP_BADGES[entry.group_key] ?? GROUP_BADGES.yin2;
  // 触发池全量是雷达:非出手标记的行整体降透明度(只看不做)
  const dimmed = !entry.actionable;
  return (
    <tr className={cn("border-b last:border-b-0 hover:bg-muted/30", dimmed && "opacity-50")}>
      <td className="px-3 py-2.5">
        <StockIdentityLink name={entry.name ?? entry.vt_symbol} vtSymbol={entry.vt_symbol} />
      </td>
      <td className="px-3 py-2.5">
        <span
          className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)}
          title={badge.full}
        >
          {badge.label}
        </span>
      </td>
      <td className="px-3 py-2.5 text-xs">
        {entry.actionable ? (
          <span className="font-semibold text-rise" title="白名单出手">✅出手</span>
        ) : entry.pos3 ? (
          <span className="text-muted-foreground">
            {entry.pos3}
            {entry.low_dd != null ? ` ${entry.low_dd.toFixed(0)}%` : ""}
          </span>
        ) : (
          <span className="text-muted-foreground/60">--</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
        {formatPrice(entry.trigger_price)}
        <span className="ml-1 text-[10px] text-muted-foreground">封板价</span>
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
