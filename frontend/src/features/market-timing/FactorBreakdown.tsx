import { type TimingFactors, type TimingOverview } from "@/api/marketTiming";
import { Card } from "@/components/ui/card";
import { GOLD, SILVER_DEEP } from "./TimingHero";

const BULL_FACTORS: { key: keyof TimingFactors; label: string }[] = [
  { key: "trend", label: "趋势" },
  { key: "momentum", label: "动量" },
  { key: "breadth", label: "市场广度" },
  { key: "structure", label: "波动结构" },
  { key: "volume", label: "量能" },
];

const TOP_FACTORS: { key: string; label: string }[] = [
  { key: "breadth_top", label: "广度顶背离" },
  { key: "macd_top", label: "MACD 顶背离" },
  { key: "vol_price_div", label: "放量滞涨" },
  { key: "trend_breakdown", label: "趋势破位" },
];

function toNum(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v))) return Number(v);
  return null;
}

function Bar({ label, value, color }: { label: string; value: number | null; color: string }) {
  const v = value ?? 0;
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium tabular-nums">{value == null ? "--" : value.toFixed(0)}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.max(0, Math.min(100, v))}%`, background: color, transition: "width .5s ease" }}
        />
      </div>
    </div>
  );
}

export function FactorBreakdown({
  overview,
  loading,
}: {
  overview: TimingOverview | null;
  loading: boolean;
}) {
  if (loading || !overview) {
    return (
      <Card className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        加载因子明细…
      </Card>
    );
  }
  const top = overview.top_factors ?? {};
  return (
    <Card className="p-5">
      <h3 className="mb-1 font-display text-base font-semibold">当前因子明细</h3>
      <p className="mb-3 text-xs text-muted-foreground">{overview.latest_date} · 阶段 {overview.phase_label}</p>

      <div className="mb-1 text-xs font-medium text-amber-300/90">多头合力分族（利多）</div>
      <div className="mb-4 space-y-2.5">
        {BULL_FACTORS.map((f) => (
          <Bar key={f.key} label={f.label} value={overview.factors[f.key]} color={GOLD} />
        ))}
      </div>

      <div className="mb-1 text-xs font-medium text-slate-300/90">顶部空头因子（警示见顶）</div>
      <div className="space-y-2.5">
        {TOP_FACTORS.map((f) => (
          <Bar key={f.key} label={f.label} value={toNum(top[f.key])} color={SILVER_DEEP} />
        ))}
      </div>
    </Card>
  );
}
