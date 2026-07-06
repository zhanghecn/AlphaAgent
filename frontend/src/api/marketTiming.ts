import { apiClient } from "./client";

/** 金手指=看多 / 银手指=看空 / 中性观望 */
export type TimingDirection = "GOLD" | "SILVER" | "NEUTRAL";
export type TimingGrade = "STRONG" | "MEDIUM" | "WEAK" | "";
/** v4 候选确认状态: CONFIRMED 已确认 / INVALIDATED 假突破否决 / PENDING 待确认 */
export type TimingStatus = "CONFIRMED" | "INVALIDATED" | "PENDING";

export interface TimingFactors {
  trend: number;
  momentum: number;
  breadth: number;
  structure: number;
  volume: number;
}

export interface TimingOverview {
  latest_date: string;
  phase: string;
  phase_label: string;
  bull_force: number;
  bear_force: number;
  factors: TimingFactors;
  top_factors: Record<string, number | string | null>;
  index_close: number | null;
  index_change_pct: number | null;
  is_intraday?: boolean;
  latest_signal: {
    direction: TimingDirection;
    status: TimingStatus;
    grade: TimingGrade;
    date: string;
    confirm_date: string | null;
    bull_force: number;
    bear_force: number;
  } | null;
}

export interface TimingSignal {
  date: string;
  direction: TimingDirection;
  status: TimingStatus;
  grade: TimingGrade;
  confirm_date: string | null;
  bull_force: number;
  bear_force: number;
  phase: string;
  reasons: string[];
}

export interface TimingBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  turnover: number;
}

export interface TimingChart {
  index_symbol: string;
  bars: TimingBar[];
  composite: { date: string; close: number }[];
  signals: TimingSignal[];
}

export interface AccuracyBucket {
  direction: TimingDirection;
  grade: TimingGrade;
  horizon: number;
  count: number;
  win_rate: number;
  avg_return: number;
  worst_return: number;
  ci_low: number;
  ci_high: number;
}

export interface TimingAccuracy {
  buckets: AccuracyBucket[];
  random_baseline: Record<string, number>;
  buy_hold_return_pct: number | null;
  n_events: number;
  n_confirmed?: number;
  n_invalidated?: number;
  n_pending?: number;
  /** 假突破候选的后续收益(按 horizon), 揭示次日确认是真预测力还是数据窥视 */
  invalidated_summary?: Record<
    number,
    { count: number; avg_return: number; win_rate: number }
  >;
  silver_caveat: string;
}

export interface MarketTimingPanel {
  overview: TimingOverview;
  chart: TimingChart;
  accuracy: TimingAccuracy;
  generated_at: number;
  sample_range: [string, string];
}

/** 全套面板数据(概览+K线+信号+准确率)。首次约 1 分钟, 之后命中缓存秒回。 */
export function fetchMarketTimingPanel(force = false): Promise<MarketTimingPanel> {
  return apiClient.get<MarketTimingPanel>(`/market-timing/panel${force ? "?force=true" : ""}`);
}
