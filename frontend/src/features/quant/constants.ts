/** Constants and types shared across quant feature components. */

export const DEFAULT_BACKTEST_START = "2025-10-14";

export const QUANT_BOARD_OPTIONS = [
  { value: "main", label: "主板" },
  { value: "chinext", label: "创业板" },
  { value: "star", label: "科创板" },
  { value: "bse", label: "北交所" },
] as const;

export type QuantBoard = (typeof QUANT_BOARD_OPTIONS)[number]["value"];
export type ExecutionModel = "legacy_next_open";

export const DEFAULT_BACKTEST_PARAMS = {
  strategy: "mainline_dragon_pullback",
  start: DEFAULT_BACKTEST_START,
  initial_cash: 1_000_000,
  max_symbols: 5000,
  max_positions: 10,
  candidate_limit: 10,
  min_entry_score: 76,
  strict_entry: true,
  execution_model: "legacy_next_open" as ExecutionModel,
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
