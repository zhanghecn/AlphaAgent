import { type TimingOverview, type TimingDirection } from "@/api/marketTiming";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** 金手指/银手指信号专色: 暖金 vs 冷银, 明度+色相双重对立, 深浅模式都清晰。
 *  避开 A 股涨红(#ef4444)/跌绿(#22c55e)。金亮暖、银深冷, 一眼可辨。 */
export const GOLD = "#fbbf24"; // amber-400 亮暖金
export const SILVER = "#64748b"; // slate-500 深冷银(浅底深灰清晰, 深底中灰可见)
export const SILVER_DEEP = "#475569"; // slate-600

const DIRECTION_LABEL: Record<TimingDirection, string> = {
  GOLD: "金手指",
  SILVER: "银手指",
  NEUTRAL: "无信号",
};

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
        <span className="text-[10px] text-muted-foreground">最近确认</span>
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
  const direction = overview.current_direction;
  const activeSignal = overview.latest_signal?.direction === direction
    ? overview.latest_signal
    : null;
  const reversalLabel = direction === "GOLD" ? "银手指" : "金手指";
  const quoteDate = overview.quote_date;
  const factorDate = overview.factor_date;
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
            <span className="text-xs text-muted-foreground">上证指数 · 行情 {quoteDate}</span>
            {overview.is_intraday && (
              <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-300">
                盘中实时
              </span>
            )}
            <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium">
              阶段：{overview.phase_label}
            </span>
            {overview.danger_state === "DANGER" && (
              <span className="rounded-md bg-destructive/10 px-2 py-0.5 text-xs font-medium text-destructive">
                结构风险：危险
              </span>
            )}
            {factorDate !== quoteDate && (
              <span className="text-xs text-muted-foreground">因子截至 {factorDate}</span>
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <ForceBar label="多头合力 bull" value={overview.bull_force} color={GOLD} />
            <ForceBar label="空头合力 bear" value={overview.bear_force} color={SILVER_DEEP} />
          </div>
          {direction === "NEUTRAL" && (
            <p className="text-sm text-muted-foreground">
              尚无已确认金银手指 · 因子截至 {factorDate}
            </p>
          )}
          {direction !== "NEUTRAL" && activeSignal && (
            <p className="flex flex-wrap gap-x-1 text-sm text-muted-foreground">
              <span>最近确认{DIRECTION_LABEL[direction]}</span>
              <span>· {activeSignal.confirm_date ?? activeSignal.date} 确认</span>
              <span>· 尚无{reversalLabel}反转</span>
            </p>
          )}
        </div>
      </div>
    </Card>
  );
}
