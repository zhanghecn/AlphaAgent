import { type AccuracyBucket, type TimingDirection, type TimingAccuracy } from "@/api/marketTiming";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const HORIZONS = [5, 10, 20] as const;

/** 胜率染色: ≥60% 好, 40-60% 中性, <40% 差 */
function winRateClass(rate: number): string {
  if (rate >= 0.6) return "text-rise";
  if (rate < 0.4) return "text-fall";
  return "text-muted-foreground";
}

/** 按 (direction, horizon) 聚合所有 grade, 简化到金/银两行。
 *  win_rate/avg_return 按 count 加权; worst 取最差; ci 取保守并集区间。 */
function aggregateByDirection(buckets: AccuracyBucket[]): AccuracyBucket[] {
  const map = new Map<string, AccuracyBucket[]>();
  for (const b of buckets) {
    const key = `${b.direction}|${b.horizon}`;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(b);
  }
  const out: AccuracyBucket[] = [];
  for (const [key, cells] of map) {
    const [direction, horizonStr] = key.split("|");
    const horizon = Number(horizonStr);
    const count = cells.reduce((s, c) => s + c.count, 0);
    if (count === 0) continue;
    const win_rate = cells.reduce((s, c) => s + c.win_rate * c.count, 0) / count;
    const avg_return = cells.reduce((s, c) => s + c.avg_return * c.count, 0) / count;
    const worst_return =
      direction === "GOLD"
        ? Math.min(...cells.map((c) => c.worst_return))
        : Math.max(...cells.map((c) => c.worst_return));
    const ci_low = Math.min(...cells.map((c) => c.ci_low));
    const ci_high = Math.max(...cells.map((c) => c.ci_high));
    out.push({ direction: direction as TimingDirection, grade: "", horizon, count, win_rate, avg_return, worst_return, ci_low, ci_high });
  }
  // 金在前, 银在后
  return out.sort((a, b) => Number(a.direction === "GOLD") * -1 || a.horizon - b.horizon);
}

function Cell({ bucket }: { bucket: AccuracyBucket | undefined }) {
  if (!bucket) return <td className="px-2 py-1.5 text-center text-muted-foreground/40">—</td>;
  return (
    <td className="px-2 py-1.5 text-center">
      <div className={cn("text-sm font-semibold tabular-nums", winRateClass(bucket.win_rate))}>
        {(bucket.win_rate * 100).toFixed(0)}%
      </div>
      <div className="text-[10px] tabular-nums text-muted-foreground">
        n={bucket.count} · [{(bucket.ci_low * 100).toFixed(0)},{(bucket.ci_high * 100).toFixed(0)}]
      </div>
      <div
        className={cn(
          "text-[10px] tabular-nums",
          bucket.avg_return >= 0 ? "text-rise/80" : "text-fall/80",
        )}
      >
        均{bucket.avg_return >= 0 ? "+" : ""}
        {bucket.avg_return.toFixed(1)}%
      </div>
    </td>
  );
}

function DirectionRow({
  label,
  direction,
  buckets,
}: {
  label: string;
  direction: "GOLD" | "SILVER";
  buckets: AccuracyBucket[];
}) {
  const byHorizon = new Map(
    aggregateByDirection(buckets.filter((bucket) => bucket.direction === direction)).map(
      (bucket) => [bucket.horizon, bucket],
    ),
  );

  return (
    <tr className="border-b border-border/40 last:border-0">
      <td className="px-2 py-1.5">
        <span
          className={cn(
            "mr-1.5 inline-block h-2.5 w-2.5 rounded-full align-middle",
            direction === "GOLD" ? "bg-amber-400" : "bg-slate-500",
          )}
        />
        <span className="font-medium">{label}</span>
      </td>
      {HORIZONS.map((horizon) => (
        <Cell key={horizon} bucket={byHorizon.get(horizon)} />
      ))}
    </tr>
  );
}

function PerformanceTable({
  buckets,
  label,
}: {
  buckets: AccuracyBucket[];
  label: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] text-sm" aria-label={label}>
        <thead>
          <tr className="border-b text-xs text-muted-foreground">
            <th className="px-2 py-1.5 text-left font-medium">信号</th>
            {HORIZONS.map((horizon) => (
              <th key={horizon} className="px-2 py-1.5 text-center font-medium">
                {horizon} 日胜率
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <DirectionRow label="金手指（看多）" direction="GOLD" buckets={buckets} />
          <DirectionRow label="银手指（看空）" direction="SILVER" buckets={buckets} />
        </tbody>
      </table>
    </div>
  );
}

export function AccuracyMatrix({
  accuracy,
  loading,
  sampleRange,
}: {
  accuracy: TimingAccuracy | null;
  loading: boolean;
  sampleRange?: [string, string];
}) {
  if (loading || !accuracy) {
    return (
      <Card className="flex h-56 items-center justify-center text-sm text-muted-foreground">
        加载准确率矩阵…
      </Card>
    );
  }
  const baseline = accuracy.random_baseline;
  const candidateBuckets = accuracy.candidate_buckets ?? [];

  return (
    <Card className="min-w-0 p-5">
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-baseline sm:justify-between">
        <div>
          <h3 className="font-display text-base font-semibold">确认后表现</h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            从确认日收盘开始观察，非成交收益
          </p>
        </div>
        <span className="text-xs text-muted-foreground">
          样本 {sampleRange?.[0] ?? ""} ~ {sampleRange?.[1] ?? ""}
        </span>
      </div>
      <PerformanceTable buckets={accuracy.buckets} label="确认后表现" />

      <div className="mb-2 mt-4 border-t border-border/60 pt-3">
        <h4 className="text-sm font-semibold">全部候选表现（不经过次日筛选）</h4>
        <p className="mt-0.5 text-xs text-muted-foreground">从候选日收盘开始观察</p>
      </div>
      <PerformanceTable buckets={candidateBuckets} label="全部候选表现" />

      <div className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
        <div>
          随机基准：{" "}
          {HORIZONS.map((h) => `${h}d=${((baseline[String(h)] ?? 0) * 100).toFixed(0)}%`).join(" · ")}
        </div>
        {accuracy.buy_hold_return_pct != null && (
          <div>
            全仓持有：
            <span className="text-rise font-medium">
              {(accuracy.buy_hold_return_pct >= 0 ? "+" : "") + accuracy.buy_hold_return_pct.toFixed(1)}%
            </span>
          </div>
        )}
        <div>
          事件 已确认 {accuracy.n_confirmed ?? 0} · 否决 {accuracy.n_invalidated ?? 0}
        </div>
      </div>

      <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/90">
        样本限制：{accuracy.silver_caveat}
      </div>
    </Card>
  );
}
