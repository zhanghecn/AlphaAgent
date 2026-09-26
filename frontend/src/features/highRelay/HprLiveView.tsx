import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, RefreshCw } from "lucide-react";

import {
  fetchHprRules,
  type HprLiveEntry,
  type HprLivePayload,
} from "@/api/highRelay";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const SESSION_LABELS: Record<string, string> = {
  preopen: "盘前",
  auction: "竞价时段",
  first_window: "早盘(09:30~09:45)",
  morning: "上午盘",
  lunch: "午间休市",
  afternoon: "下午盘",
  closed: "已收盘",
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  watching: { label: "待触发", className: "text-muted-foreground" },
  entered: { label: "已买入", className: "text-rise font-semibold" },
  holding: { label: "持有中", className: "text-rise font-semibold" },
  pending_exit: { label: "待退出", className: "text-amber-600" },
  closed: { label: "已了结", className: "text-muted-foreground" },
  skipped_auction: { label: "竞价回避", className: "text-muted-foreground line-through" },
  skipped_gap: { label: "顶格·买不进", className: "text-muted-foreground line-through" },
  no_trigger: { label: "未触发", className: "text-muted-foreground/60" },
};

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板当日·收盘卖",
  next_close_fail: "次日未涨停·收盘卖",
  break_close: "断板日收盘卖",
  max_hold_close: "15日兜底·收盘卖",
};

/** 链式十方案硬编码映射(A=二接三阳 B=二接三阴 C=三接四阳 D=三接四阴)。 */
const POINT_BADGES: Record<string, { label: string; full: string; className: string }> = {
  A1: { label: "A1", full: "A1 双低贴零(二接三阳)", className: "bg-rise/15 text-rise ring-1 ring-rise/40" },
  A2: { label: "A2", full: "A2 平启贴零(二接三阳)", className: "bg-emerald-500/15 text-emerald-500" },
  A3: { label: "A3", full: "A3 一字急锁缓启(二接三阳)", className: "bg-teal-500/15 text-teal-500" },
  B1: { label: "B1", full: "B1 强强活跃温开(二接三阴)", className: "bg-amber-500/15 text-amber-500 ring-1 ring-amber-500/40" },
  B2: { label: "B2", full: "B2 低洗走强(二接三阴)", className: "bg-yellow-500/15 text-yellow-500" },
  C1: { label: "C1", full: "C1 放量高板低吸(三接四阳)", className: "bg-primary/15 text-primary" },
  C2: { label: "C2", full: "C2 双一字确认(三接四阳)", className: "bg-sky-500/15 text-sky-500" },
  D1: { label: "D1", full: "D1 低板转强(三接四阴)", className: "bg-orange-500/15 text-orange-500" },
  D2: { label: "D2", full: "D2 低洗平推(三接四阴)", className: "bg-violet-500/15 text-violet-500" },
  D3: { label: "D3", full: "D3 贴零温开(三接四阴)", className: "bg-fuchsia-500/15 text-fuchsia-500" },
};

const POINT_KEYS = ["A1", "A2", "A3", "B1", "B2", "C1", "C2", "D1", "D2", "D3"] as const;

const POINT_COUNT_TONE: Record<string, string> = {
  A1: "text-rise",
  A2: "text-emerald-500",
  A3: "text-teal-500",
  B1: "text-amber-500",
  B2: "text-yellow-500",
  C1: "text-primary",
  C2: "text-sky-500",
  D1: "text-orange-500",
  D2: "text-violet-500",
  D3: "text-fuchsia-500",
};

export function HprLiveView({
  payload,
  availableDates,
  selectedDate,
  onDateChange,
}: {
  payload: HprLivePayload;
  availableDates: string[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
}) {
  const rulesQuery = useQuery({
    queryKey: ["hprRules"],
    queryFn: fetchHprRules,
    staleTime: 300_000,
  });
  const [playbookOpen, setPlaybookOpen] = useState(false);
  const entries = payload.entries ?? [];
  const thsConditions = rulesQuery.data?.ths_pool_conditions;
  const playbook = rulesQuery.data?.intraday_playbook ?? [];
  const byPoint = payload.counts.by_point ?? {};
  const byStatus = payload.counts.by_status ?? {};

  return (
    <div className="space-y-4">
      <section aria-label="高位接力实时推荐" className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">高位接力 · 实时推荐</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">
              非当日(最新可用池)
            </span>
          ) : null}
          <span>池 {payload.counts.pool ?? 0}</span>
          {POINT_KEYS.map((pk) => (
            <span key={pk} className={POINT_COUNT_TONE[pk]}>
              {pk} {byPoint[pk] ?? 0}
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
              ? POINT_KEYS.map((pk) => (
                  <CopyThsConditionsButton
                    key={pk}
                    conditions={thsConditions[pk]}
                    label={`复制${pk}条件`}
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
            盘中执行要点(竞价定型对照「今天开」档,命中方案触板即打)
          </button>
          {playbookOpen ? (
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-xs text-muted-foreground">
              {playbook.map((line) => <li key={line}>{line}</li>)}
            </ol>
          ) : null}
        </div>

        {entries.length === 0 ? (
          <div className="p-4">
            <EmptyState message="今日池为空——盘后统一更新链会自动计算次日池" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1380px] text-sm">
              <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">股票</th>
                  <th className="px-3 py-2 text-left font-medium">方案点</th>
                  <th className="px-3 py-2 text-left font-medium">级别</th>
                  <th className="px-3 py-2 text-left font-medium">打板</th>
                  <th className="px-3 py-2 text-left font-medium">地基</th>
                  <th className="px-3 py-2 text-left font-medium">板型链</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">触发价</th>
                  <th className="px-3 py-2 text-right font-medium">竞价</th>
                  <th className="px-3 py-2 text-right font-medium">现价</th>
                  <th className="px-3 py-2 text-right font-medium">涨幅</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                  <th className="px-3 py-2 text-right font-medium">首触</th>
                  <th className="px-3 py-2 text-right font-medium">买入价</th>
                  <th className="px-3 py-2 text-right font-medium">退出</th>
                  <th className="px-3 py-2 text-right font-medium">收益</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <LiveRow key={entry.vt_symbol} entry={entry} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function LiveRow({ entry }: { entry: HprLiveEntry }) {
  const meta = STATUS_META[entry.status] ?? STATUS_META.watching;
  const badge = POINT_BADGES[entry.point] ?? null;
  // 雷达票(未命中方案点/静态回避)整体降透明度(只看不做)
  const dimmed = !entry.actionable;
  const auctionBlocked =
    entry.status === "skipped_auction" ||
    (entry.avoid_static != null && entry.avoid_static !== "");
  return (
    <tr className={cn("border-b last:border-b-0 hover:bg-muted/30", dimmed && "opacity-50")}>
      <td className="px-3 py-2.5">
        <StockIdentityLink name={entry.name ?? entry.vt_symbol} vtSymbol={entry.vt_symbol} />
      </td>
      <td className="px-3 py-2.5">
        {badge ? (
          <span
            className={cn("rounded px-1.5 py-0.5 text-[10px] font-medium", badge.className)}
            title={badge.full}
          >
            {badge.label}
          </span>
        ) : (
          <span className="text-muted-foreground/60">—</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs">
        {entry.actionable ? (
          entry.level === "A" ? (
            <span className="font-semibold text-rise" title="链式方案命中">✅出手</span>
          ) : (
            <span className="font-semibold text-primary" title="候选(今天开窗待盘中确认)">🔵候选</span>
          )
        ) : entry.avoid_static ? (
          <span className="text-amber-600" title={entry.avoid_static}>回避</span>
        ) : (
          <span className="text-muted-foreground/60">雷达</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">
        {entry.n_board != null ? `打${entry.n_board + 1}板` : "--"}
      </td>
      <td className="px-3 py-2.5 text-xs" title={`均线 ${entry.ma_state || "--"} · 换手梯度 ${fmtNum(entry.turn_grad)}`}>
        {entry.foundation_yang == null ? "--" : entry.foundation_yang ? "阳" : "阴"}
        {entry.dist_h60 != null ? ` 新高${entry.dist_h60.toFixed(0)}%` : ""}
        {entry.prior_height != null ? ` 前${entry.prior_height}板` : ""}
      </td>
      <td className={cn("px-3 py-2.5 text-xs", auctionBlocked && entry.avoid_static ? "text-amber-600" : "text-muted-foreground")}>
        {entry.chain ?? "--"}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
        {formatPrice(entry.limit_price)}
        <span className="ml-1 text-[10px] text-muted-foreground">封板价</span>
      </td>
      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums",
        entry.status === "skipped_auction" ? "text-amber-600" : pctTone(entry.auction_pct))}>
        {entry.auction_pct == null ? "--" : formatPct(entry.auction_pct)}
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
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">
        {formatTimeHM(entry.touched_at)}
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

function fmtNum(value: number | null | undefined) {
  return value == null ? "--" : value.toFixed(1);
}

function formatTimeHM(value: string | null) {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "--";
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(d);
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
