import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertOctagon, ChevronDown, RefreshCw } from "lucide-react";

import {
  fetchQianlongRules,
  type QianlongLiveEntry,
  type QianlongLivePayload,
} from "@/api/qianlong";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { CopyThsConditionsButton } from "@/features/qianlong/CopyThsConditionsButton";
import { FirstBoardLeaderPage } from "@/pages/FirstBoardLeaderPage";
import { cn, formatPct, formatPrice } from "@/lib/utils";

const SESSION_LABELS: Record<string, string> = {
  preopen: "盘前",
  morning: "上午盘(可交易时段)",
  lunch: "午间休市",
  afternoon_closed_for_entry: "午后(本策略不做)",
  closed: "已收盘",
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  watching: { label: "待触发", className: "text-muted-foreground" },
  touched: { label: "已触及+8%", className: "text-amber-500" },
  holding: { label: "持有中", className: "text-rise font-semibold" },
  pending_exit: { label: "待次日卖", className: "text-amber-600" },
  closed: { label: "已了结", className: "text-muted-foreground" },
  unconfirmed: { label: "未收住·放弃", className: "text-muted-foreground" },
  skipped_gap: { label: "禁做·高开≥8%", className: "text-muted-foreground line-through" },
  no_trigger: { label: "未触发", className: "text-muted-foreground/60" },
};

const EXIT_REASON_LABELS: Record<string, string> = {
  next_open_fail: "未封板·次日开盘卖",
  next_open_nostreak: "未连板·次日开盘卖",
  break_open: "断板日卖",
};

// v6 池 = A板块 ∪ B板块(买卖规则对两组完全相同,标签只决定同日抢槽优先级与分组统计)
type GroupKey = "auto" | "A" | "B" | "AB" | "all";
const GROUP_OPTIONS: { key: GroupKey; label: string }[] = [
  { key: "auto", label: "可操作" },
  { key: "A", label: "A板块" },
  { key: "B", label: "B板块" },
  { key: "AB", label: "AB双满足" },
  { key: "all", label: "全池" },
];
const GROUP_DESC: Record<GroupKey, string> = {
  auto: "默认:B 类优先 + 活跃信号",
  A: "A板块 = 全新急建仓(含 AB)",
  B: "B板块 = 小阳建仓(含 AB)",
  AB: "AB = 两类同时满足,历史最优子集",
  all: "全池(A∪B 并集)",
};

export function QianlongLiveView({
  payload,
  availableDates,
  selectedDate,
  onDateChange,
}: {
  payload: QianlongLivePayload;
  availableDates: string[];
  selectedDate: string | null;
  onDateChange: (date: string | null) => void;
}) {
  const rulesQuery = useQuery({
    queryKey: ["qianlongRules"],
    queryFn: fetchQianlongRules,
    staleTime: 300_000,
  });
  const [playbookOpen, setPlaybookOpen] = useState(false);
  const [group, setGroup] = useState<GroupKey>("auto");
  const [query, setQuery] = useState("");
  const circuit = payload.circuit_breaker;
  const entries = payload.entries ?? [];
  const thsConditionsA = rulesQuery.data?.ths_pool_conditions;
  const thsConditionsB = rulesQuery.data?.ths_pool_conditions_b;
  const playbook = rulesQuery.data?.intraday_playbook ?? [];
  const q = query.trim().toLowerCase();
  const groupCounts = useMemo(() => {
    let a = 0, b = 0, ab = 0;
    for (const e of entries) {
      const tag = e.chassis_tag ?? "";
      if (tag.includes("A")) a += 1;
      if (tag.includes("B")) b += 1;
      if (tag === "AB") ab += 1;
    }
    return { a, b, ab };
  }, [entries]);
  const groupCount = (key: GroupKey) =>
    key === "A" ? groupCounts.a : key === "B" ? groupCounts.b : key === "AB" ? groupCounts.ab : null;
  const visibleEntries = entries.filter((entry) => {
    if (q) {
      return (
        entry.vt_symbol.toLowerCase().includes(q) ||
        (entry.name ?? "").toLowerCase().includes(q)
      );
    }
    const tag = entry.chassis_tag ?? "";
    if (group === "all") return true;
    if (group === "A") return tag.includes("A");
    if (group === "B") return tag.includes("B");
    if (group === "AB") return tag === "AB";
    // auto:宽观察池默认只显示可操作行(活跃状态 + B类优先)
    return entry.priority || (entry.status !== "watching" && entry.status !== "no_trigger");
  });

  return (
    <div className="space-y-4">
      <section aria-label="潜龙首板实时推荐" className="rounded-lg border">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-3 text-xs text-muted-foreground">
          <span className="text-sm font-semibold text-foreground">潜龙首板 · 实时推荐</span>
          <span className="font-mono tabular-nums">{payload.trade_date}</span>
          <span>{SESSION_LABELS[payload.session_stage] ?? payload.session_stage}</span>
          {payload.stale ? (
            <span className="rounded border border-amber-500/40 px-1.5 py-0.5 text-amber-500">
              非当日(最新可用池)
            </span>
          ) : null}
          <span>池 {payload.counts.pool ?? 0}</span>
          <span className="text-amber-500">触及 {payload.counts.touched ?? 0}</span>
          <span className="text-rise">持有 {payload.counts.holding ?? 0}</span>
          <span>已了结 {payload.counts.closed ?? 0}</span>
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
            {thsConditionsA ? (
              <CopyThsConditionsButton conditions={thsConditionsA} label="复制A板块条件" />
            ) : null}
            {thsConditionsB ? (
              <CopyThsConditionsButton conditions={thsConditionsB} label="复制B板块条件" />
            ) : null}
          </span>
        </div>

        {circuit.halted ? (
          <div className="flex items-center gap-2 border-b border-fall/30 bg-fall/10 px-4 py-2 text-xs text-fall">
            <AlertOctagon size={14} />
            风控熔断:{circuit.month} 已实现 {circuit.realized_pct}%(阈值 {circuit.threshold_pct}%),
            当月停止交易——本月新信号不再给买入徽章。
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
            <div className="flex flex-wrap items-center gap-3 border-b px-4 py-2 text-xs text-muted-foreground">
              <span className="flex items-center gap-1" aria-label="按底盘分组查看">
                {GROUP_OPTIONS.map((opt) => (
                  <button
                    key={opt.key}
                    type="button"
                    className={cn(
                      "h-7 rounded-md border px-2",
                      group === opt.key && "border-primary text-primary",
                    )}
                    onClick={() => setGroup(opt.key)}
                  >
                    {opt.label}
                    {groupCount(opt.key) != null ? ` ${groupCount(opt.key)}` : ""}
                  </button>
                ))}
              </span>
              <span>
                显示 {visibleEntries.length} / 全池 {entries.length}({GROUP_DESC[group]})
              </span>
              <input
                className="h-7 w-44 rounded-md border bg-background px-2 text-xs"
                placeholder="搜代码/名称…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="搜索池内股票"
              />
            </div>
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="border-b bg-muted/30 text-xs text-muted-foreground">
                <tr>
                  <th className="px-3 py-2 text-left font-medium">股票</th>
                  <th className="px-3 py-2 text-right font-medium">昨收</th>
                  <th className="px-3 py-2 text-right font-medium">触发价(+8%)</th>
                  <th className="px-3 py-2 text-right font-medium">高开</th>
                  <th className="px-3 py-2 text-right font-medium">现价</th>
                  <th className="px-3 py-2 text-right font-medium">涨幅</th>
                  <th className="px-3 py-2 text-left font-medium">状态</th>
                  <th className="px-3 py-2 text-right font-medium">买入价</th>
                  <th className="px-3 py-2 text-right font-medium">退出</th>
                  <th className="px-3 py-2 text-right font-medium">收益</th>
                </tr>
              </thead>
              <tbody>
                {visibleEntries.map((entry) => (
                  <LiveRow key={entry.vt_symbol} entry={entry} halted={circuit.halted} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section aria-label="已封板首板复盘对照">
        <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">已封板首板(复盘对照)</span>
          <span>东财涨停池口径 · 用于对照池外封板与池内漏网</span>
        </div>
        <FirstBoardLeaderPage />
      </section>
    </div>
  );
}

function LiveRow({ entry, halted }: { entry: QianlongLiveEntry; halted: boolean }) {
  const meta = STATUS_META[entry.status] ?? STATUS_META.watching;
  const dimmed = entry.status === "skipped_gap" || entry.status === "no_trigger";
  return (
    <tr className={cn("border-b last:border-b-0 hover:bg-muted/30", dimmed && "opacity-50")}>
      <td className="px-3 py-2.5">
        <span className="inline-flex items-center gap-1.5">
          <StockIdentityLink name={entry.name ?? entry.vt_symbol} vtSymbol={entry.vt_symbol} />
          <ChassisBadge tag={entry.chassis_tag} priority={entry.priority && !halted} />
        </span>
      </td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums">{formatPrice(entry.prev_close)}</td>
      <td className="px-3 py-2.5 text-right font-mono tabular-nums text-primary">
        {formatPrice(entry.trigger_price)}
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

function ChassisBadge({ tag, priority }: { tag: string | null | undefined; priority: boolean }) {
  if (!tag) return null;
  const isB = tag.includes("B");
  return (
    <span
      className={cn(
        "rounded px-1 py-0.5 text-[10px] font-medium",
        isB ? "bg-primary/15 text-primary" : "bg-muted/60 text-muted-foreground",
      )}
      title={isB ? "B类 · 小阳建仓(优先)" : "A类 · 全新急建仓"}
    >
      {tag}{isB && priority ? "·优先" : ""}
    </span>
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
