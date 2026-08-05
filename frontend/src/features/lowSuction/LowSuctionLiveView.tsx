import { useState } from "react";
import { ChevronDown, TrendingUp, Waves } from "lucide-react";

import type { LowSuctionCandidate, LowSuctionLivePayload } from "@/api/lowSuction";
import { EmptyState } from "@/components/EmptyState";
import { StockIdentityLink } from "@/components/StockIdentityLink";
import { cn } from "@/lib/utils";

/** 低吸实时推荐：上升趋势低吸 + 超跌反弹低吸两组，按综合分排序。 */
export function LowSuctionLiveView({ payload }: { payload: LowSuctionLivePayload }) {
  if (payload.status !== "ok") {
    return <EmptyState message={payload.message ?? "低吸实时推荐暂时不可用"} />;
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
        <span className="ml-auto">
          每 {Math.round((payload.cache_ttl_seconds ?? 1800) / 60)} 分钟重算 · {payload.asof?.slice(11, 19)} 更新
        </span>
      </div>
      <div className="grid gap-px bg-border xl:grid-cols-2">
        <FamilyColumn
          title="上升趋势低吸"
          en="TREND PULLBACK"
          icon={<TrendingUp size={14} className="text-primary" />}
          total={trend?.total ?? 0}
          items={trend?.items ?? []}
        />
        <FamilyColumn
          title="超跌反弹低吸"
          en="OVERSOLD REBOUND"
          icon={<Waves size={14} className="text-primary" />}
          total={oversold?.total ?? 0}
          items={oversold?.items ?? []}
        />
      </div>
      <div className="border-t px-3 py-2 text-[11px] text-muted-foreground sm:px-4">
        {payload.label_convention} · 分数为因子条件加权（详见规则说明）· 实时推荐不含 ST 股
      </div>
    </section>
  );
}

function FamilyColumn({
  title,
  en,
  icon,
  total,
  items,
}: {
  title: string;
  en: string;
  icon: React.ReactNode;
  total: number;
  items: LowSuctionCandidate[];
}) {
  return (
    <div className="min-w-0 bg-card">
      <div className="flex items-center gap-2 border-b px-3 py-2.5 sm:px-4">
        {icon}
        <span className="text-sm font-semibold">{title}</span>
        <span className="eyebrow">{en}</span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground">
          命中 {total} 只 · 展示前 {items.length}
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

function Pct({ label, value }: { label: string; value: number | null }) {
  if (value == null) return <span>{label} --</span>;
  return (
    <span className={value > 0 ? "text-red-500" : value < 0 ? "text-emerald-600" : ""}>
      {label} {value >= 0 ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}
