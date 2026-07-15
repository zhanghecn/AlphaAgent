import { apiClient } from "./client";

/** 金手指=金行情 / 银手指=银行情，直到相反已确认手指反转 */
export type TimingDirection = "GOLD" | "SILVER" | "NEUTRAL";
export type TimingGrade = "STRONG" | "MEDIUM" | "WEAK" | "";
export type TimingDangerState = "NORMAL" | "DANGER";
export type TimingSetupType =
  | "TREND_GOLD"
  | "REVERSAL_GOLD"
  | "TOP_SILVER"
  | "BREAKDOWN_SILVER"
  | "STRUCTURAL_BREAKDOWN_SILVER";
/** 候选确认状态: CONFIRMED 已确认 / INVALIDATED 假突破否决 / PENDING 待确认 */
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
  factor_date: string;
  quote_date: string;
  current_direction: TimingDirection;
  danger_state: TimingDangerState;
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
    setup_type: TimingSetupType;
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
  setup_type: TimingSetupType;
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

export interface TimingDailyEvent {
  direction: TimingDirection;
  status: TimingStatus;
  grade: TimingGrade;
  setup_type: TimingSetupType;
  confirm_date: string | null;
}

export interface TimingDailyState {
  date: string;
  bull_force: number;
  bear_force: number;
  active_direction: TimingDirection;
  zone_direction: TimingDirection;
  danger_state: TimingDangerState;
  phase: string;
  event: TimingDailyEvent | null;
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

export interface AccuracyRow {
  date: string;
  candidate_date: string;
  confirm_date: string | null;
  start_date: string;
  direction: TimingDirection;
  status: TimingStatus;
  grade: TimingGrade;
  setup_type: TimingSetupType;
  horizon: number;
  return: number;
  correct: boolean;
}

export interface AccuracyEvaluationBasis {
  confirmed_start: "confirm_date_close";
  candidate_start: "candidate_date_close";
  executable: false;
}

export interface TimingAccuracy {
  buckets: AccuracyBucket[];
  rows?: AccuracyRow[];
  candidate_buckets?: AccuracyBucket[];
  candidate_rows?: AccuracyRow[];
  evaluation_basis?: AccuracyEvaluationBasis;
  random_baseline: Record<string, number>;
  buy_hold_return_pct: number | null;
  n_events: number;
  n_confirmed?: number;
  n_invalidated?: number;
  n_pending?: number;
  /** 兼容旧接口的否决候选摘要；起点与确认后表现不同，不应直接横向比较。 */
  invalidated_summary?: Record<
    number,
    { count: number; avg_return: number; win_rate: number }
  >;
  silver_caveat: string;
}

export interface MarketTimingPanel {
  overview: TimingOverview;
  chart: TimingChart;
  timing_series?: TimingDailyState[];
  accuracy: TimingAccuracy;
  generated_at: number;
  sample_range: [string, string];
}

/** 全套面板数据(概览+K线+信号+准确率)。首次约 1 分钟, 之后命中缓存秒回。 */
export function fetchMarketTimingPanel(force = false): Promise<MarketTimingPanel> {
  return apiClient.get<MarketTimingPanel>(`/market-timing/panel${force ? "?force=true" : ""}`);
}
