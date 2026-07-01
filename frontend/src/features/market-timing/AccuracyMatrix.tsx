import { type AccuracyBucket, type TimingAccuracy } from "@/api/marketTiming";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const HORIZONS = [5, 10, 20] as const;

/** 胜率染色: ≥60% 金/绿(好), 40-60% 中性, <40% 红(差) */
function winRateClass(rate: number): string {
  if (rate >= 0.6) return "text-rise";
  if (rate < 0.4) return "text-fall";
  return "text-muted-foreground";
}

function gradeLabel(grade: string): string {
  return { STRONG: "强", MEDIUM: "中", WEAK: "弱" }[grade] ?? "—";
}

/** 把 buckets 按 (direction, grade) 分组, 每个 cell 是某个 horizon 的统计 */
function groupBuckets(buckets: AccuracyBucket[]) {
  const map = new Map<string, AccuracyBucket[]>();
  for (const b of buckets) {
    const key = `${b.direction}|${b.grade}`;
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(b);
  }
  // 排序: 金手指在前, 档位 强>中>弱
  const order = { GOLD: 0, SILVER: 1 } as const;
  const gOrder = { STRONG: 0, MEDIUM: 1, WEAK: 2 } as const;
  return [...map.entries()].sort((a, b) => {
    const [da, ga] = a[0].split("|");
    const [db, gb] = b[0].split("|");
    if (da !== db) return order[da as keyof typeof order] - order[db as keyof typeof order];
    return gOrder[ga as keyof typeof gOrder] - gOrder[gb as keyof typeof gOrder];
  });
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
  const rows = groupBuckets(accuracy.buckets);
  const baseline = accuracy.random_baseline;

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-display text-base font-semibold">历史准确率矩阵</h3>
        <span className="text-xs text-muted-foreground">
          样本 {sampleRange?.[0] ?? ""} ~ {sampleRange?.[1] ?? ""}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-xs text-muted-foreground">
              <th className="px-2 py-1.5 text-left font-medium">信号</th>
              {HORIZONS.map((h) => (
                <th key={h} className="px-2 py-1.5 text-center font-medium">
                  {h} 日胜率
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(([key, cells]) => {
              const [dir, grade] = key.split("|");
              const byHorizon = new Map(cells.map((c) => [c.horizon, c]));
              const isGold = dir === "GOLD";
              return (
                <tr key={key} className="border-b border-border/40 last:border-0">
                  <td className="px-2 py-1.5">
                    <span
                      className={cn(
                        "inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle",
                        isGold ? "bg-amber-400" : "bg-slate-300",
                      )}
                    />
                    <span className="font-medium">{isGold ? "金手指" : "银手指"}</span>
                    <span className="ml-1 text-xs text-muted-foreground">{gradeLabel(grade)}</span>
                  </td>
                  {HORIZONS.map((h) => (
                    <Cell key={h} bucket={byHorizon.get(h)} />
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="mt-4 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
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
        <div>事件总数 {accuracy.n_events}</div>
      </div>

      <div className="mt-3 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200/90">
        ⚠️ {accuracy.silver_caveat}
      </div>
    </Card>
  );
}
