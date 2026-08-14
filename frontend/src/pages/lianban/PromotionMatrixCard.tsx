import type { LadderPromotionRow } from "@/api/lianban";
import { cn } from "@/lib/utils";
import { formatGroupedInt, formatRatioPct } from "./ReviewStatsCards";

/**
 * 档位标签：数字档（含字符串数字）→ "N进N+1"（当日 N 板次日晋级 N+1 板）；
 * 合并档 "8+" 不进位，原样显示；无法解析的输入原样返回。
 */
export function promotionRowLabel(streak: number | string): string {
  if (typeof streak === "string" && streak.endsWith("+")) return streak;
  const numeric = Number(streak);
  if (!Number.isFinite(numeric)) return String(streak);
  return `${numeric}进${numeric + 1}`;
}

/** 晋级率文案：0 样本或 rate 缺失/非法 → "--"；否则一位小数百分（与一期天梯档头口径一致）。 */
export function promotionRateText(rate: number | null | undefined, samples: number): string {
  if (samples <= 0) return "--";
  return formatRatioPct(rate);
}

/** 横条宽度百分（0-100，封顶）；rate 缺失/非法/负值 → 0（不渲染横条）。 */
export function promotionBarPercent(rate: number | null | undefined): number {
  if (rate == null || !Number.isFinite(rate) || rate <= 0) return 0;
  return Math.min(100, rate * 100);
}

/** 排序键：数字档按数值；"8+" 合并档折算 8.5 垫底；无法解析的排最后。 */
function promotionSortKey(streak: number | string): number {
  if (typeof streak === "string" && streak.endsWith("+")) {
    const numeric = Number(streak.slice(0, -1));
    return Number.isFinite(numeric) ? numeric + 0.5 : Number.MAX_SAFE_INTEGER;
  }
  const numeric = Number(streak);
  return Number.isFinite(numeric) ? numeric : Number.MAX_SAFE_INTEGER;
}

/** 档位排序：1进2 在上，8+ 合并档垫底（防御性重排，不改原数组；后端已按此输出）。 */
export function sortPromotionRows(rows: LadderPromotionRow[]): LadderPromotionRow[] {
  return [...rows].sort((a, b) => promotionSortKey(a.streak) - promotionSortKey(b.streak));
}

interface PromotionMatrixCardProps {
  rows: LadderPromotionRow[];
  /** 窗口天数，仅用于标题 */
  days: number;
}

/**
 * 窗口晋级率矩阵：近 N 日「当日 N 板 → 次日 N+1 板」的历史频率
 * （与一期天梯档头的近一年版同口径，这里是短窗研究版）。
 * 晋级率列为横条 + 数字；样本为 0 或 rate 缺失时显示 "--"。
 */
export function PromotionMatrixCard({ rows, days }: PromotionMatrixCardProps) {
  const sorted = sortPromotionRows(rows);
  return (
    <section aria-label="窗口晋级率" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">近{days}日晋级率</h2>
        <span className="text-[11px] text-muted-foreground">
          当日 N 板 → 窗口内次日 N+1 板的历史频率
        </span>
      </header>
      {sorted.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          窗口内无晋级样本
        </div>
      ) : (
        <div className="overflow-x-auto px-3 py-2 sm:px-4">
          <table className="w-full min-w-[420px] border-collapse text-xs">
            <thead>
              <tr className="text-muted-foreground">
                <th className="py-1 pr-2 text-left font-medium">档位</th>
                <th className="px-2 py-1 text-right font-medium">样本数</th>
                <th className="px-2 py-1 text-right font-medium">晋级数</th>
                <th className="w-2/5 py-1 pl-2 text-left font-medium">晋级率</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => {
                const barPercent = promotionBarPercent(row.rate);
                return (
                  <tr key={String(row.streak)} className="border-t border-border/50 first:border-t-0">
                    <td className="py-1.5 pr-2 font-medium tabular-nums text-foreground">
                      {promotionRowLabel(row.streak)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {formatGroupedInt(row.samples)}
                    </td>
                    <td className="px-2 py-1.5 text-right tabular-nums text-muted-foreground">
                      {formatGroupedInt(row.promoted)}
                    </td>
                    <td className="py-1.5 pl-2">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 min-w-16 flex-1 rounded-full bg-muted">
                          <div
                            className="h-full rounded-full bg-rise/70"
                            style={{ width: `${barPercent}%` }}
                          />
                        </div>
                        <span
                          className={cn(
                            "w-12 shrink-0 text-right tabular-nums",
                            row.rate == null ? "text-muted-foreground" : "text-foreground",
                          )}
                        >
                          {promotionRateText(row.rate, row.samples)}
                        </span>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
