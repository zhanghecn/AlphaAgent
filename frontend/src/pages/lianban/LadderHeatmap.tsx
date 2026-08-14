import type { LadderHistoryDay } from "@/api/lianban";
import { cn } from "@/lib/utils";
import { formatShortDate } from "./ReviewStatsCards";

/** 热力矩阵行键：6+板在上，1板在下（与一期五日接力矩阵同档序）。 */
export const HEAT_TIER_KEYS = ["6+", "5", "4", "3", "2", "1"] as const;

/** 热力色阶档：0=空 / 1=浅 / 2=中 / 3=深。 */
export type HeatLevel = 0 | 1 | 2 | 3;

/**
 * 家数 → 色阶档：0 家 → 空（降噪，不渲染底色与数字）；1-2 家 → 浅；
 * 3-5 家 → 中；>=6 家 → 深。非法输入（null/NaN/负数）按 0 家处理。
 */
export function heatLevel(count: number | null | undefined): HeatLevel {
  if (count == null || !Number.isFinite(count) || count <= 0) return 0;
  if (count <= 2) return 1;
  if (count <= 5) return 2;
  return 3;
}

const HEAT_LEVEL_CLASSES: Record<HeatLevel, string> = {
  0: "",
  1: "bg-rise/10",
  2: "bg-rise/25",
  3: "bg-rise/45 font-medium",
};

/** 色阶档 → 单元格底色 class（rise 红系透明度阶梯：连板家数越多情绪越热）。 */
export function heatCellClass(level: HeatLevel): string {
  return HEAT_LEVEL_CLASSES[level] ?? "";
}

/** 单元格文案：0 家显示空（降噪），正数显示家数。 */
export function heatCellText(count: number | null | undefined): string {
  return heatLevel(count) === 0 ? "" : String(count);
}

/** 行标签："6+" → "6+板"。 */
export function heatTierLabel(key: string): string {
  return `${key}板`;
}

/** 单元格悬浮提示："2026-08-13 3板 2家"（0 家也保留提示，便于确认当日空缺）。 */
export function heatCellTitle(date: string, tierKey: string, count: number): string {
  return `${date} ${heatTierLabel(tierKey)} ${count}家`;
}

interface LadderHeatmapProps {
  /** 窗口内每日梯队快照（升序，左旧右新渲染） */
  days: LadderHistoryDay[];
  /** 窗口最新交易日（as_of）：该列加粗边框高亮；null 或无匹配则不高亮 */
  asOf: string | null;
}

/**
 * 连板天梯热力矩阵：行=板位（6+板在上），列=交易日，单元格=当日该板位家数。
 * 颜色深度∝家数；0 家留空；当日列加粗边框。横向可滚动，板位列冻结在左。
 * 所有单元格统一 border-x-2（默认透明），as_of 列仅换成主题色，避免高亮列宽度跳变。
 */
export function LadderHeatmap({ days, asOf }: LadderHeatmapProps) {
  return (
    <section aria-label="天梯热力图" className="rounded-lg border">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-2.5 sm:px-4">
        <h2 className="text-sm font-semibold text-foreground">天梯热力图</h2>
        <span className="text-[11px] text-muted-foreground">
          行=板位 · 列=交易日 · 颜色越深家数越多
        </span>
        <span className="ml-auto flex items-center gap-1.5 text-[10px] text-muted-foreground">
          <span className="tabular-nums">0</span>
          <i aria-hidden className="h-2.5 w-2.5 rounded-sm bg-rise/10" />
          <span className="tabular-nums">1-2</span>
          <i aria-hidden className="h-2.5 w-2.5 rounded-sm bg-rise/25" />
          <span className="tabular-nums">3-5</span>
          <i aria-hidden className="h-2.5 w-2.5 rounded-sm bg-rise/45" />
          <span className="tabular-nums">≥6家</span>
        </span>
      </header>
      {days.length === 0 ? (
        <div className="px-3 py-6 text-center text-xs text-muted-foreground sm:px-4">
          窗口内无涨停交易日
        </div>
      ) : (
        // 横向滚动容器不带内边距（sticky 板位列才能贴边盖住滚过内容）；
        // 左侧间距由板位列 pl 承担，右侧由末尾占位列承担。
        <div className="overflow-x-auto py-2">
          <table className="w-full min-w-[640px] border-collapse text-[11px]">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-background py-1 pl-3 pr-2 text-left font-medium text-muted-foreground sm:pl-4">
                  板位
                </th>
                {days.map((day) => (
                  <th
                    key={day.trade_date}
                    className={cn(
                      "min-w-7 border-x-2 px-1 py-1 text-center font-medium tabular-nums",
                      day.trade_date === asOf
                        ? "border-primary/60 text-foreground"
                        : "border-transparent text-muted-foreground",
                    )}
                  >
                    {formatShortDate(day.trade_date)}
                  </th>
                ))}
                <th aria-hidden className="w-3 sm:w-4" />
              </tr>
            </thead>
            <tbody>
              {HEAT_TIER_KEYS.map((key) => (
                <tr key={key}>
                  <td className="sticky left-0 z-10 bg-background py-0.5 pl-3 pr-2 text-left text-muted-foreground sm:pl-4">
                    {heatTierLabel(key)}
                  </td>
                  {days.map((day) => {
                    const count = day.tiers[key] ?? 0;
                    const level = heatLevel(count);
                    const isAsOf = day.trade_date === asOf;
                    return (
                      <td
                        key={day.trade_date}
                        title={heatCellTitle(day.trade_date, key, count)}
                        className={cn(
                          "h-7 border-x-2 text-center tabular-nums",
                          isAsOf ? "border-primary/60" : "border-transparent",
                          heatCellClass(level),
                          level > 0 && "text-foreground",
                          isAsOf && level > 0 && "font-semibold",
                        )}
                      >
                        {heatCellText(count)}
                      </td>
                    );
                  })}
                  <td aria-hidden />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
