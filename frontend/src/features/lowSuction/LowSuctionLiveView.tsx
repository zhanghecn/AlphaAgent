import { useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Clock3, TrendingUp, Waves } from "lucide-react";

import type {
  LowSuctionCandidate,
  LowSuctionLivePayload,
  LowSuctionLiveScanRun,
} from "@/api/lowSuction";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

/** 低吸实时推荐：上升趋势低吸 + 超跌反弹低吸两组，按综合分排序。 */
export function LowSuctionLiveView({
  payload,
  onTrendPageChange,
  onOversoldPageChange,
}: {
  payload: LowSuctionLivePayload;
  onTrendPageChange: (page: number) => void;
  onOversoldPageChange: (page: number) => void;
}) {
  const scanTrace = payload.scan_trace ?? [];
  if (payload.status !== "ok") {
    return (
      <section aria-label="低吸实时推荐">
        <LiveScanTrace runs={scanTrace} />
        <EmptyState message={payload.message ?? "低吸实时推荐暂时不可用"} />
      </section>
    );
  }
  const trend = payload.trend;
  const oversold = payload.oversold;
  return (
    <section aria-label="低吸实时推荐">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-3 py-2 text-xs text-muted-foreground sm:px-4">
        <span className="eyebrow">实时 LIVE</span>
        <span>
          信号日 <span className="font-medium text-foreground">{payload.trade_date}</span>
        </span>
        {payload.provisional ? (
          <span className="rounded-full bg-amber-500/15 px-1.5 py-px text-[10px] font-medium text-amber-600">
            盘中虚拟K线 · 未定型
          </span>
        ) : (
          <span className="rounded-full bg-emerald-500/15 px-1.5 py-px text-[10px] font-medium text-emerald-600">
            已收盘确认
          </span>
        )}
        {payload.merge_note && <span>{payload.merge_note}</span>}
        <span>当日已扫 {scanTrace.length} 次</span>
        <span className="ml-auto">
          缓存有效 {Math.round((payload.cache_ttl_seconds ?? 1800) / 60)} 分钟 · {payload.asof?.slice(11, 19)} 更新
        </span>
      </div>
      <LiveScanTrace runs={scanTrace} />
      <div className="grid gap-px bg-border xl:grid-cols-2">
        <FamilyColumn
          title="上升趋势低吸"
          en="TREND PULLBACK"
          icon={<TrendingUp size={14} className="text-primary" />}
          family={trend}
          onPageChange={onTrendPageChange}
        />
        <FamilyColumn
          title="超跌反弹低吸"
          en="OVERSOLD REBOUND"
          icon={<Waves size={14} className="text-primary" />}
          family={oversold}
          onPageChange={onOversoldPageChange}
        />
      </div>
      <div className="border-t px-3 py-2 text-[11px] text-muted-foreground sm:px-4">
        {payload.label_convention} · 分数为因子条件加权（详见规则说明）· 实时推荐不含 ST 股
      </div>
    </section>
  );
}

function LiveScanTrace({ runs }: { runs: LowSuctionLiveScanRun[] }) {
  const [expanded, setExpanded] = useState(false);
  const latest = runs[runs.length - 1];
  return (
    <div className="border-b bg-muted/10">
      <button
        type="button"
        className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-xs transition-colors hover:bg-muted/30 sm:px-4"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls="low-suction-scan-trace"
      >
        <span className="flex items-center gap-1.5 font-medium text-foreground">
          <Clock3 size={14} className="text-muted-foreground" />
          当日扫描轨道
        </span>
        <span className="tabular-nums text-muted-foreground">已执行 {runs.length} 次</span>
        {latest && (
          <span className="tabular-nums text-muted-foreground">
            最近 {scanTime(latest.started_at)}
          </span>
        )}
        <ChevronDown
          size={14}
          className={cn("ml-auto text-muted-foreground transition-transform", expanded && "rotate-180")}
        />
      </button>
      {expanded && (
        <ol id="low-suction-scan-trace" className="divide-y border-t">
          {runs.length === 0 ? (
            <li className="px-3 py-3 text-xs text-muted-foreground sm:px-4">暂无可读取的真实扫描记录</li>
          ) : (
            runs.map((run, index) => <ScanTraceRow key={run.id} run={run} index={index} />)
          )}
        </ol>
      )}
    </div>
  );
}

function ScanTraceRow({ run, index }: { run: LowSuctionLiveScanRun; index: number }) {
  const failed = run.status === "error";
  const unavailable = run.status === "unavailable";
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-xs tabular-nums sm:px-4">
      <span className="w-5 font-mono text-muted-foreground">{index + 1}</span>
      <time dateTime={run.started_at} className="font-mono text-foreground">
        {scanTime(run.started_at)}
      </time>
      <span className="text-muted-foreground">{scanInterval(run.interval_seconds)}</span>
      <span className="text-muted-foreground">耗时 {scanDuration(run.duration_ms)}</span>
      <span
        className={cn(
          failed ? "text-destructive" : unavailable ? "text-amber-600" : "text-emerald-600",
        )}
      >
        {failed ? "扫描失败" : unavailable ? "无可用数据" : run.provisional ? "盘中虚拟K线" : "确认日线"}
      </span>
      {failed ? (
        <span className="min-w-0 max-w-full basis-full truncate text-destructive/80" title={run.error ?? undefined}>
          {run.error ?? "未知错误"}
        </span>
      ) : (
        <>
          <span className="text-muted-foreground">趋势 {run.trend_count ?? "--"}</span>
          <span className="text-muted-foreground">超跌 {run.oversold_count ?? "--"}</span>
          {run.spot_active_symbols != null && (
            <span className="text-muted-foreground">现货 {run.spot_active_symbols.toLocaleString()} 只</span>
          )}
          {run.merge_note && (
            <span className="min-w-0 max-w-full basis-full truncate text-muted-foreground" title={run.merge_note}>
              {run.merge_note}
            </span>
          )}
        </>
      )}
    </li>
  );
}

function scanTime(value: string) {
  return value.slice(11, 19) || "--:--:--";
}

function scanInterval(seconds: number | null) {
  if (seconds == null) return "首次扫描";
  if (seconds < 60) return `距上次 ${seconds} 秒`;
  if (seconds < 3_600) return `距上次 ${Math.round(seconds / 60)} 分`;
  return `距上次 ${(seconds / 3_600).toFixed(1)} 小时`;
}

function scanDuration(milliseconds: number) {
  if (milliseconds < 1_000) return `${milliseconds} ms`;
  return `${(milliseconds / 1_000).toFixed(1)} 秒`;
}

function FamilyColumn({
  title,
  en,
  icon,
  family,
  onPageChange,
}: {
  title: string;
  en: string;
  icon: React.ReactNode;
  family: LowSuctionLivePayload["trend"];
  onPageChange: (page: number) => void;
}) {
  const total = family?.total ?? 0;
  const limit = family?.limit ?? 0;
  const items = family?.items ?? [];
  const page = family?.page ?? 1;
  const pageSize = family?.page_size ?? items.length;
  const pages = family?.pages ?? 1;
  const available = limit ? Math.min(total, limit) : total;
  return (
    <div className="min-w-0 bg-card">
      <div className="flex items-center gap-2 border-b px-3 py-2.5 sm:px-4">
        {icon}
        <span className="shrink-0 text-sm font-semibold">{title}</span>
        <span className="eyebrow hidden sm:inline">{en}</span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          命中 {total} 只 · 可查看前 {available}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="px-3 py-8 text-center text-xs text-muted-foreground">
          当日无命中候选（规则较严，空仓日是常态）
        </div>
      ) : (
        <div className="divide-y">
          {items.map((item) => (
            <CandidateCard key={`${item.setup_type}-${item.vt_symbol}`} item={item} />
          ))}
        </div>
      )}
      {items.length > 0 && (
        <FamilyPager
          page={page}
          pages={pages}
          pageSize={pageSize}
          available={available}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}

function CandidateCard({ item }: { item: LowSuctionCandidate }) {
  const [expanded, setExpanded] = useState(false);
  const earned = item.components.reduce((sum, c) => sum + c.points, 0);
  const total = item.components.reduce((sum, c) => sum + c.max_points, 0);
  return (
    <div className="px-3 py-2.5 sm:px-4">
      <div className="flex items-baseline gap-2">
        <span
          className={cn(
            "font-mono text-lg font-bold tabular-nums",
            item.score >= 80 ? "text-primary" : item.score >= 60 ? "text-foreground" : "text-muted-foreground",
          )}
        >
          {item.score.toFixed(0)}
        </span>
        {item.rank != null && <span className="font-mono text-[11px] text-muted-foreground">#{item.rank}</span>}
        <StockIdentityLink vtSymbol={item.vt_symbol} name={item.stock_name ?? item.symbol} />
        <span className="ml-auto text-xs text-muted-foreground">{item.rule_label}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs tabular-nums text-muted-foreground">
        <span>{item.streak.label}</span>
        <span>收盘 {item.close_price?.toFixed(2) ?? "--"}</span>
        <Pct label="当日" value={item.daily_return_pct} />
        <span>换手 {item.turnover_rate_pct?.toFixed(2) ?? "--"}%</span>
        <span>振幅 {item.candle_range_pct?.toFixed(2) ?? "--"}%</span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            "ml-auto flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] transition-colors",
            expanded ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground",
          )}
          aria-expanded={expanded}
        >
          因子详解 {earned.toFixed(0)}/{total.toFixed(0)}
          <ChevronDown size={12} className={cn("transition-transform", expanded && "rotate-180")} />
        </button>
      </div>
      {expanded && (
        <dl className="mt-2 grid gap-x-4 gap-y-1 rounded border bg-muted/20 p-2 text-xs sm:grid-cols-2">
          {item.components.map((c) => (
            <div key={c.key} className="flex items-baseline gap-1.5">
              <span
                className={cn(
                  "font-mono text-[10px] font-semibold",
                  c.passed ? "text-emerald-600" : "text-muted-foreground/60",
                )}
              >
                {c.passed ? "✓" : "×"}
              </span>
              <dt className="shrink-0 text-muted-foreground">{c.label}</dt>
              <dd className="min-w-0 flex-1 truncate text-foreground" title={c.detail}>
                {c.detail}
              </dd>
              <dd className="ml-auto shrink-0 font-mono text-[10px] tabular-nums text-muted-foreground">
                {c.points.toFixed(0)}/{c.max_points.toFixed(0)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function FamilyPager({
  page,
  pages,
  pageSize,
  available,
  onPageChange,
}: {
  page: number;
  pages: number;
  pageSize: number;
  available: number;
  onPageChange: (page: number) => void;
}) {
  if (pages <= 1) return null;
  const start = (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, available);
  return (
    <div className="flex items-center gap-2 border-t px-3 py-2 text-xs tabular-nums text-muted-foreground sm:px-4">
      <span>{start}-{end} / {available}</span>
      <div className="ml-auto flex items-center gap-1">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          className="grid h-7 w-7 place-items-center border text-foreground disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="上一页"
          title="上一页"
        >
          <ChevronLeft size={14} />
        </button>
        <span className="min-w-10 text-center">{page} / {pages}</span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={page >= pages}
          className="grid h-7 w-7 place-items-center border text-foreground disabled:cursor-not-allowed disabled:opacity-40"
          aria-label="下一页"
          title="下一页"
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

function Pct({ label, value }: { label: string; value: number | null }) {
  if (value == null) return <span>{label} --</span>;
  return (
    <span className={value > 0 ? "text-red-500" : value < 0 ? "text-emerald-600" : ""}>
      {label} {value >= 0 ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}
