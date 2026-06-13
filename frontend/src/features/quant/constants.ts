/** Constants and types shared across quant feature components. */

export const DEFAULT_BACKTEST_START = "2025-10-14";

export const QUANT_BOARD_OPTIONS = [
  { value: "main", label: "主板" },
  { value: "chinext", label: "创业板" },
  { value: "star", label: "科创板" },
  { value: "bse", label: "北交所" },
] as const;

export type QuantBoard = (typeof QUANT_BOARD_OPTIONS)[number]["value"];
export type MinuteInterval = "1m" | "5m" | "10m";

export const MINUTE_INTERVAL_OPTIONS = [
  { value: "1m", label: "1分钟" },
  { value: "5m", label: "5分钟" },
  { value: "10m", label: "10分钟" },
] as const;

export const DEFAULT_BACKTEST_PARAMS = {
  start: DEFAULT_BACKTEST_START,
  initial_cash: 1_000_000,
  max_symbols: 120,
  max_positions: 8,
  min_entry_score: 68,
  strict_entry: true,
  intraday_entry: true,
  minute_entry_required: false,
  minute_interval: "1m" as MinuteInterval,
  tail_entry_start: "14:30",
  tail_entry_end: "14:57",
  tail_entry_ma5_tolerance_pct: 1.5,
  included_boards: ["main"] as string[],
};

export type BacktestParams = typeof DEFAULT_BACKTEST_PARAMS;

/** Map board values to display labels. */
export function boardLabels(boards: string[]): string {
  const labels = QUANT_BOARD_OPTIONS
    .filter((option) => boards.includes(option.value))
    .map((option) => option.label);
  return labels.length ? labels.join("、") : "主板";
}
