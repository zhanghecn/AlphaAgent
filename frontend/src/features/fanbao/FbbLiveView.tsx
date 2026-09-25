import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, RefreshCw } from "lucide-react";

import {
  fetchFbbRules,
  type FbbLiveEntry,
  type FbbLivePayload,
} from "@/api/fanbao";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const SESSION_LABELS: Record<string, string> = {
  preopen: "盘前",
  auction: "竞价时段",
  first_window: "早盘",
  morning: "上午盘",
  lunch: "午间休市",
  afternoon: "下午盘",
  closed: "已收盘",
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  watching: { label: "待触发", className: "text-muted-foreground" },
  sealed_watch: { label: "T字观察", className: "text-amber-500" },
  entered: { label: "已买入", className: "text-rise font-semibold" },
  holding: { label: "持有中", className: "text-rise font-semibold" },
  pending_exit: { label: "待退出", className: "text-amber-600" },
  closed: { label: "已了结", className: "text-muted-foreground" },
  skipped_gap: { label: "一字·买不进", className: "text-muted-foreground line-through" },
  no_trigger: { label: "未触发", className: "text-muted-foreground/60" },
};

const EXIT_REASON_LABELS: Record<string, string> = {
  break_day_close: "炸板当日·收盘卖",
  next_close_fail: "次日未涨停·收盘卖",
  break_close: "断板日收盘卖",
  max_hold_close: "15日兜底·收盘卖",
};

/** 五方案点硬编码映射:S级金边出手、O级普通观察。 */
const POINT_BADGES: Record<string, { label: string; full: string; className: string }> = {
  S1: { label: "S1", full: "S1 低开急杀(2板·跌8~15%只洗一次,末日低开或平开)", className: "bg-rise/15 text-rise ring-1 ring-rise/40" },
  S2: { label: "S2", full: "S2 高开洗透(4板断1天·末日高开2%以上走低收阴)", className: "bg-amber-500/15 text-amber-500 ring-1 ring-amber-500/40" },
  S3: { label: "S3", full: "S3 高位扛住(5板以上断1天·昨天没跌=筹码锁死)", className: "bg-primary/15 text-primary ring-1 ring-primary/40" },
  O1: { label: "O1", full: "O1 高位阴断1(5板以上断1天但昨天跌了,观察级)", className: "bg-violet-500/15 text-violet-500" },
  O2: { label: "O2", full: "O2 四板阴断3(观察级)", className: "bg-orange-500/15 text-orange-500" },
};

const POINT_KEYS = ["S1", "S2", "S3", "O1", "O2"] as const;

const POINT_COUNT_TONE: Record<string, string> = {
  S1: "text-rise",
  S2: "text-amber-500",
  S3: "text-primary",
  O1: "text-violet-500",
  O2: "text-orange-500",
};

export function FbbLiveView({
  payload,
  availableDates,
  selectedDate,
  onDateChange,
}: {
  payload: FbbLivePayload;
  availableDates: string[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
}) {
  const rulesQuery = useQuery({
    queryKey: ["fbbRules"],
    queryFn: fetchFbbRules,
    staleTime: 300_000,
  });
  const [playbookOpen, setPlaybookOpen] = useState(false);
  const entries = payload.entries ?? [];
  const thsConditions = rulesQuery.data?.ths_pool_conditions;
  const playbook = rulesQuery.data?.intraday_playbook ?? [];
  const byPoint = payload.counts.by_point ?? {};
  const byStatus = payload.counts.by_status ?? {};
  const byGap = payload.counts.by_gap ?? {};

  return (
    <div className="space-y-4">
      <section aria-label="断板反包实时推荐" className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">断板反包 · 实时推荐</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">
              非当日(最新可用池)
            </span>
          ) : null}
          <span>池 {payload.counts.pool ?? 0}</span>
          <span>断1 {byGap["1"] ?? 0}</span>
          <span>断2 {byGap["2"] ?? 0}</span>
          <span>断3 {byGap["3"] ?? 0}</span>
          {POINT_KEYS.map((pk) => (
            <span key={pk} className={POINT_COUNT_TONE[pk]}>
              {pk} {byPoint[pk] ?? 0}
            </span>
          ))}
          <span className="font-semibold text-rise">出手 {payload.counts.actionable ?? 0}</span>
          <span className="text-rise">已买入 {byStatus.entered ?? 0}</span>
          <span className="text-rise">持有 {byStatus.holding ?? 0}</span>
          <span>已了结 {byStatus.closed ?? 0}</span>
          <span>昨日涨停 {payload.mkt_lim_tm1 ?? "--"} 家</span>
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
            盘中执行要点(触板即买·无首刻窗,只对✅出手/🔵观察的票触发)
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
            <table className="w-full min-w-[1420px] text-sm">
              <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">股票</th>
                  <th className="px-3 py-2 text-left font-medium">方案点</th>
                  <th className="px-3 py-2 text-left font-medium">级别</th>
                  <th className="px-3 py-2 text-left font-medium">组</th>
                  <th className="px-3 py-2 text-left font-medium">前波</th>
                  <th className="px-3 py-2 text-left font-medium">断板期</th>
                  <th className="px-3 py-2 text-right font-medium">累计%</th>
                  <th className="px-3 py-2 text-right font-medium">阴线数</th>
                  <th className="px-3 py-2 text-right font-medium">末开%</th>
                  <th className="px-3 py-2 text-right font-medium">坑深%</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">触发价</th>
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

function LiveRow({ entry }: { entry: FbbLiveEntry }) {
  const meta = STATUS_META[entry.status] ?? STATUS_META.watching;
  const badge = POINT_BADGES[entry.point] ?? null;
  // 雷达票(未命中方案点/死格)整体降透明度(只看不做)
  const dimmed = !entry.actionable;
  const dead = entry.avoid_static != null && entry.avoid_static !== "";
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
          entry.level === "S" ? (
            <span className="font-semibold text-rise" title="出手级">✅出手</span>
          ) : (
            <span className="font-semibold text-primary" title="观察级·默认只看不买">🔵观察</span>
          )
        ) : dead ? (
          <span className="text-amber-600" title={entry.avoid_static ?? undefined}>死格</span>
        ) : (
          <span className="text-muted-foreground/60">雷达</span>
        )}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">
        {entry.group6}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground" title={entry.chain ?? undefined}>
        {entry.n_board != null ? `${entry.n_board}板` : "--"}
        {entry.gap != null ? `·断${entry.gap}` : ""}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground" title={entry.break_days ?? undefined}>
        {entry.break_days ?? "--"}
      </td>
      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums", pctTone(entry.break_drop_pct))}>
        {fmtNum(entry.break_drop_pct)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">
        {entry.break_yin_count ?? "--"}
      </td>
      <td className={cn("px-3 py-2.5 text-right font-mono tabular-nums",
        entry.high_var ? "font-semibold text-amber-500" : "text-muted-foreground")}
          title={entry.high_var
            ? "⚠顶格开走低:胜率五五开,要买减半仓(不剔除,S2最大赢家日上集团就是顶格开)"
            : "末日开盘涨幅:S1 要低开或平开(直接砸);S2 要高开2%以上(借热度出货)"}>
        {entry.high_var ? "⚠" : ""}{fmtNum(entry.last_open_pct)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-muted-foreground">
        {fmtNum(entry.pit_depth_pct)}
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
        {formatPrice(entry.limit_price)}
        <span className="ml-1 text-[10px] text-muted-foreground">涨停价</span>
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
