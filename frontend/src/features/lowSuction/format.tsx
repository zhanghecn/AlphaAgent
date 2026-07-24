import { cn } from "@/lib/utils";

/** 反包研究共用的格式化与小部件，workspace 与历史账本统一从这里取 */

export function Metric({ label, value, tone }: { label: string; value: string; tone?: string }) {
  return <div className="border-b border-r px-3 py-3"><dt className="text-xs text-muted-foreground">{label}</dt><dd className={cn("mt-1 font-semibold tabular-nums", tone)}>{value}</dd></div>;
}

export function Definition({ label, value }: { label: string; value: string }) {
  return <div className="grid grid-cols-[minmax(140px,0.8fr)_minmax(0,1.2fr)] gap-4 border-b px-3 py-2.5 md:odd:border-r"><dt className="text-muted-foreground">{label}</dt><dd className="text-right">{value}</dd></div>;
}

export function formatRate(value: number | null | undefined) {
  return value == null ? "--" : `${value.toFixed(2)}%`;
}

export function formatPct(value: number | null | undefined) {
  return value == null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function formatNumber(value: number | null | undefined) {
  return value == null ? "--" : value.toFixed(2);
}

export function rateTone(value: number) {
  return value > 0 ? "text-rise" : value < 0 ? "text-fall" : "text-muted-foreground";
}

export function phaseLabel(value: string) {
  return value === "uptrend" ? "主升" : value === "rotation" ? "轮动" : "升温";
}

export function dateText(value: string) {
  return value.slice(0, 10);
}

export function formatTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}
