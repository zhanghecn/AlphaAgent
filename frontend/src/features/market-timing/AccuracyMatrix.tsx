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
  // 按 direction 两行
  const gold = aggregateByDirection(
    accuracy.buckets.filter((b) => b.direction === "GOLD"),
  );
  const silver = aggregateByDirection(
    accuracy.buckets.filter((b) => b.direction === "SILVER"),
  );
  const baseline = accuracy.random_baseline;
  const inval = accuracy.invalidated_summary ?? {};

  const renderRow = (label: string, isGold: boolean, cells: AccuracyBucket[]) => {
    const byHorizon = new Map(cells.map((c) => [c.horizon, c]));
    return (
      <tr className="border-b border-border/40 last:border-0">
        <td className="px-2 py-1.5">
          <span
            className={cn(
              "inline-block w-2.5 h-2.5 rounded-full mr-1.5 align-middle",
              isGold ? "bg-amber-400" : "bg-slate-500",
            )}
          />
          <span className="font-medium">{label}</span>
        </td>
        {HORIZONS.map((h) => (
          <Cell key={h} bucket={byHorizon.get(h)} />
        ))}
      </tr>
    );
  };

  return (
    <Card className="p-5">
      <div className="mb-3 flex items-baseline justify-between">
        <h3 className="font-display text-base font-semibold">历史准确率</h3>
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
            {renderRow("金手指（看多）", true, gold)}
            {renderRow("银手指（看空）", false, silver)}
          </tbody>
        </table>
      </div>

      {/* 假突破候选对比(回应"次日确认是否真有预测力") */}
      {Object.keys(inval).length > 0 && (
        <div className="mt-3 rounded-md border border-border/60 bg-muted/30 px-3 py-2">
          <div className="mb-1 text-xs font-medium text-muted-foreground">
            假突破候选（被否决，对比验证过滤价值）
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
            {HORIZONS.map((h) => {
              const row = inval[h];
              if (!row) return null;
              return (
                <span key={h}>
                  {h}日: 命中 {(row.win_rate * 100).toFixed(0)}% · 均
                  {row.avg_return >= 0 ? "+" : ""}
                  {row.avg_return.toFixed(1)}% · n={row.count}
                </span>
              );
            })}
          </div>
        </div>
      )}

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
        ⚠️ {accuracy.silver_caveat}
      </div>
    </Card>
  );
}
