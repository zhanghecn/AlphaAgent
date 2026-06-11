import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format a number as A-share price with 2 decimals */
export function formatPrice(value: number | null | undefined): string {
  if (value == null) return "--";
  return value.toFixed(2);
}

/** Format percentage with sign, A-share style */
export function formatPct(value: number | null | undefined): string {
  if (value == null) return "--";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

/** Format large numbers (e.g. turnover) in 亿/万 (supports negative values) */
export function formatAmount(value: number | null | undefined): string {
  if (value == null) return "--";
  const abs = Math.abs(value);
  if (abs >= 1e8) return `${(value / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(value / 1e4).toFixed(2)}万`;
  return value.toFixed(2);
}

/** Format market cap in 亿 */
export function formatMarketCap(value: number | null | undefined): string {
  if (value == null) return "--";
  return `${(value / 1e8).toFixed(2)}亿`;
}

/** CSS class for rise/fall coloring */
export function priceColorClass(value: number | null | undefined): string {
  if (value == null) return "";
  if (value > 0) return "text-rise";
  if (value < 0) return "text-fall";
  return "";
}

export function dataSourceLabel(source?: string | null, dataOrigin?: string | null): string {
  const value = source ?? "";
  if (dataOrigin === "local_db" || value.startsWith("postgresql")) return "本地库";
  if (value.includes("stock_zygc") || value.includes("stock_zyjs")) return "公开财报/主营数据";
  if (value.includes("eastmoney") || value.includes("tencent") || value.includes("sina") || value.includes("akshare")) {
    return "实时公开源";
  }
  if (!value) return "--";
  return value;
}
