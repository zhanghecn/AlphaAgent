import { type TimingOverview, type TimingDirection } from "@/api/marketTiming";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** 金手指/银手指信号专色(页面独有, 不复用涨跌色) */
export const GOLD = "#fbbf24"; // amber-400
export const GOLD_DEEP = "#f59e0b";
export const SILVER = "#cbd5e1"; // slate-300
export const SILVER_DEEP = "#94a3b8";

const DIRECTION_LABEL: Record<TimingDirection, string> = {
  GOLD: "金手指",
  SILVER: "银手指",
  NEUTRAL: "观望",
};

function daysAgo(dateStr: string): string {
  const d = new Date(dateStr);
  const diff = Math.round((Date.now() - d.getTime()) / 86400000);
  if (Number.isNaN(diff)) return "";
  if (diff <= 0) return "今天";
  return `${diff} 天前`;
}

/**
 * 金/银指环 —— 页面 signature。
 * 外环金色弧长 = bull_force(多头合力), 内环银色弧长 = bear_force(顶部空头合力)。
 * 当前信号方向用对应金属色发光, 中心大字标方向。
 */
function SignalRing({
  bull,
  bear,
  direction,
}: {
  bull: number;
  bear: number;
  direction: TimingDirection;
}) {
  const size = 168;
  const stroke = 13;
  const rOuter = (size - stroke) / 2;
  const rInner = rOuter - stroke - 4;
  const cOuter = 2 * Math.PI * rOuter;
  const cInner = 2 * Math.PI * rInner;
  const bullLen = (Math.max(0, Math.min(100, bull)) / 100) * cOuter;
  const bearLen = (Math.max(0, Math.min(100, bear)) / 100) * cInner;
  const glow =
    direction === "GOLD"
      ? `drop-shadow(0 0 10px ${GOLD}aa)`
      : direction === "SILVER"
        ? `drop-shadow(0 0 10px ${SILVER}aa)`
        : "none";
  const centerColor = direction === "GOLD" ? GOLD : direction === "SILVER" ? SILVER : "currentColor";

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* 外环底 + bull 金色进度 */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={rOuter}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          className="text-muted/15"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={rOuter}
          fill="none"
          stroke={GOLD}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${bullLen} ${cOuter - bullLen}`}
          style={{ filter: direction === "GOLD" ? glow : "none", transition: "stroke-dasharray .6s ease" }}
        />
        {/* 内环底 + bear 银色进度 */}
        <circle
          cx={size / 2}
          cy={size / 2}
          r={rInner}
          fill="none"
          stroke="currentColor"
          strokeWidth={stroke}
          className="text-muted/15"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={rInner}
          fill="none"
          stroke={SILVER}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${bearLen} ${cInner - bearLen}`}
          style={{ filter: direction === "SILVER" ? glow : "none", transition: "stroke-dasharray .6s ease" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[10px] uppercase tracking-widest text-muted-foreground">当前信号</span>
        <span
          className="font-display text-2xl font-bold leading-tight"
          style={{ color: centerColor, textShadow: direction === "NEUTRAL" ? "none" : `0 0 12px ${centerColor}66` }}
        >
          {DIRECTION_LABEL[direction]}
        </span>
      </div>
    </div>
  );
}

function ForceBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{value.toFixed(1)}</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(0, Math.min(100, value))}%`, background: color, transition: "width .5s ease" }}
        />
      </div>
    </div>
  );
}

export function TimingHero({ overview, loading }: { overview: TimingOverview | null; loading: boolean }) {
  if (loading || !overview) {
    return (
      <Card className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        正在计算大盘因子(首次约 1 分钟, 含全市场广度)…
      </Card>
    );
  }
  const direction = overview.latest_signal?.direction ?? "NEUTRAL";
  const indexUp = (overview.index_change_pct ?? 0) >= 0;
  return (
    <Card className="p-5">
      <div className="flex flex-col gap-6 md:flex-row md:items-center">
        <SignalRing bull={overview.bull_force} bear={overview.bear_force} direction={direction} />
        <div className="flex-1 space-y-4">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <div>
              <span className="font-display text-3xl font-bold tabular-nums">
                {overview.index_close?.toFixed(2) ?? "--"}
              </span>
              <span
                className={cn("ml-2 text-sm font-medium tabular-nums", indexUp ? "text-rise" : "text-fall")}
              >
                {indexUp ? "+" : ""}
                {overview.index_change_pct?.toFixed(2)}%
              </span>
            </div>
            <span className="text-xs text-muted-foreground">上证指数 · {overview.latest_date}</span>
            <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium">
              阶段：{overview.phase_label}
            </span>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ForceBar label="多头合力 bull（金手指区）" value={overview.bull_force} color={GOLD} />
            <ForceBar label="顶部合力 bear（银手指区）" value={overview.bear_force} color={SILVER_DEEP} />
          </div>
          {overview.latest_signal && (
            <div className="flex items-center gap-2 text-sm">
              <span className="text-muted-foreground">最近信号</span>
              <span
                className="rounded-md px-2 py-0.5 text-xs font-semibold"
                style={{
                  background: `${direction === "GOLD" ? GOLD : SILVER}22`,
                  color: direction === "GOLD" ? GOLD_DEEP : SILVER_DEEP,
                }}
              >
                {DIRECTION_LABEL[direction]} · {overview.latest_signal.grade || "—"}
              </span>
              <span className="text-muted-foreground">
                {overview.latest_signal.date}（{daysAgo(overview.latest_signal.date)}）
              </span>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
