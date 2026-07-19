import { useTheme } from "@/theme/useTheme";

/**
 * 统一图表配色来源。
 *
 * 设计原则：
 * - A 股涨跌色（红涨绿绿跌）在任何模式下都保持不变，神圣保留。
 * - 品牌/网格/轴线/文字/tooltip 配色按深浅模式区分，保证深色模式可读。
 * - 三套图表库（echarts / lightweight-charts / recharts）共享同一色板。
 */

/** A 股涨跌色（神圣保留） */
export const RISE_COLOR = "#ef4444"; // 红 = 涨
export const FALL_COLOR = "#22c55e"; // 绿 = 跌

/** 品牌主色：香槟金（金手指语言） */
export const BRAND_COLOR = "#d9a84e"; // brand-500

export interface ChartPalette {
  mode: "light" | "dark";
  brand: string;
  rise: string;
  fall: string;
  /** 网格线 */
  grid: string;
  /** 坐标轴文字 */
  text: string;
  /** 坐标轴线 / 边框 */
  axis: string;
  /** tooltip 背景 */
  tooltipBg: string;
  /** tooltip 边框 */
  tooltipBorder: string;
  /** tooltip 文字 */
  tooltipText: string;
  /** 多线指标调色板（MA / MACD / KDJ / RSI 等固定区分色） */
  linePalette: string[];
}

const LIGHT: ChartPalette = {
  mode: "light",
  brand: "#c08a33", // brand-600，浅底下加深保证金色可读
  rise: RISE_COLOR,
  fall: FALL_COLOR,
  grid: "#f1f5f9",
  text: "#64748b",
  axis: "#e2e8f0",
  tooltipBg: "rgba(255,255,255,0.96)",
  tooltipBorder: "#e5e7eb",
  tooltipText: "#374151",
  linePalette: ["#c08a33", "#8b5cf6", "#2563eb", "#475569"],
};

const DARK: ChartPalette = {
  mode: "dark",
  brand: "#e2bc61", // brand-400，深底下稍亮
  rise: RISE_COLOR,
  fall: FALL_COLOR,
  grid: "#1a2233", // 墨蓝网格，比旧 slate 更贴深墨底
  text: "#94a3b8", // slate-400
  axis: "#2a3448",
  tooltipBg: "rgba(13,17,24,0.96)",
  tooltipBorder: "#2a3448",
  tooltipText: "#e2e8f0",
  linePalette: ["#e2bc61", "#a78bfa", "#60a5fa", "#94a3b8"],
};

/** hook：返回当前深浅模式下的图表配色。必须在组件内调用。 */
export function useChartColors(): ChartPalette {
  const { theme } = useTheme();
  return theme === "dark" ? DARK : LIGHT;
}

/** 非 hook 场景：按指定模式取配色（用于无法用 hook 的工具函数）。 */
export function chartColors(mode: "light" | "dark" = "light"): ChartPalette {
  return mode === "dark" ? DARK : LIGHT;
}
