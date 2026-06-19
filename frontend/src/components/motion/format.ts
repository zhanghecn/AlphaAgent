import { formatPct, formatAmount, formatMarketCap } from "@/lib/utils";

/** 动效组件支持的数字格式。复用 lib/utils 的单参 formatter，不引第二套格式化路径。 */
export type AnimFormat = "raw" | "price" | "pct" | "amount" | "marketcap";

// pct/amount/marketcap 走 lib/utils 既有单参 formatter（内部固定 toFixed(2)）。
const FIXED: Record<Exclude<AnimFormat, "raw" | "price">, (v: number) => string> = {
  pct: formatPct,
  amount: formatAmount,
  marketcap: formatMarketCap,
};

/**
 * 动画过程中的数字格式化：
 * - raw / price：尊重 decimals（自行 toFixed，因 formatPrice 内部固定 toFixed(2) 无法透传）
 * - pct / amount / marketcap：直接调用单参 formatter（保留 亿/万、正负号等业务格式）
 * - NaN / 非有限值：返回 "--"（与 lib/utils 的 null 语义一致）
 */
export function formatAnimatedValue(
  value: number,
  format: AnimFormat,
  decimals = 2,
): string {
  if (!Number.isFinite(value)) return "--";
  if (format === "raw" || format === "price") return value.toFixed(decimals);
  return FIXED[format](value);
}
