import { apiClient } from "./client";

export interface LowSuctionScoreComponent {
  key: string;
  label: string;
  passed: boolean;
  points: number;
  max_points: number;
  detail: string;
}

export interface LowSuctionStreak {
  total: number;
  yin: number;
  yang: number;
  label: string;
}

export interface LowSuctionCandidate {
  vt_symbol: string;
  symbol: string;
  stock_name?: string | null;
  trade_date: string;
  setup_type: "trend_pullback" | "oversold_rebound";
  setup_label: string;
  rule_key: string;
  rule_label: string;
  matched_rule_keys: string[];
  score: number;
  band: string;
  streak: LowSuctionStreak;
  components: LowSuctionScoreComponent[];
  close_price: number | null;
  daily_return_pct: number | null;
  turnover_rate_pct: number | null;
  candle_range_pct: number | null;
  rank?: number;
}

export interface LowSuctionLiveFamily {
  total: number;
  limit?: number;
  page?: number;
  page_size?: number;
  pages?: number;
  items: LowSuctionCandidate[];
}

export interface LowSuctionLiveScanRun {
  id: number;
  trade_date: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
  status: "ok" | "unavailable" | "error";
  provisional: boolean | null;
  spot_active_symbols: number | null;
  trend_count: number | null;
  oversold_count: number | null;
  score_version: string;
  merge_note: string | null;
  error: string | null;
  interval_seconds: number | null;
}

export type LowSuctionSnapshotPhase = "intraday" | "tail_final" | "confirmed";

export interface LowSuctionLivePayload {
  status: "ok" | "unavailable";
  message?: string;
  asof?: string;
  trade_date?: string;
  snapshot_phase?: LowSuctionSnapshotPhase;
  provisional?: boolean;
  merge_note?: string | null;
  refresh_interval_seconds?: number;
  score_version?: string;
  label_convention?: string;
  trend?: LowSuctionLiveFamily;
  oversold?: LowSuctionLiveFamily;
  scan_trace?: LowSuctionLiveScanRun[];
}

export interface LowSuctionSegmentStats {
  n: number;
  win_rate_pct: number | null;
  mean_pct: number | null;
  median_pct?: number | null;
}

export interface LowSuctionBandStats extends LowSuctionSegmentStats {
  compound_pct: number;
  active_days: number;
  recommended: boolean;
  segments: Record<string, LowSuctionSegmentStats>;
}

export interface LowSuctionFamilyReport {
  total: LowSuctionSegmentStats;
  bands: Record<string, LowSuctionBandStats>;
}

export interface LowSuctionSimSummary extends LowSuctionSegmentStats {
  trades?: number;
  days?: number;
  positions?: number;
  active_days?: number;
  average_positions_per_day?: number;
  average_deployed_pct?: number;
  daily_mean_pct?: number | null;
  compound_pct: number;
  max_drawdown_pct?: number | null;
}

export interface LowSuctionEquityPoint {
  date: string;
  equity: number;
}

/** 单族仓位模拟汇总：统计、权益曲线与样本外/市况复核全部按族分开。 */
export interface LowSuctionFamilySim extends LowSuctionSimSummary {
  equity_curve: LowSuctionEquityPoint[];
  time_segments: Record<string, LowSuctionSimSummary>;
  market_regimes: Record<string, LowSuctionSimSummary>;
}

export interface LowSuctionBacktestReport {
  version: string;
  label_convention: string;
  coverage: {
    calendar_start: string | null;
    calendar_end: string | null;
    trade_days: number;
    candidates: number;
    labeled: number;
  };
  time_split: Record<string, { start: string | null; end: string | null; days: number }>;
  selection: {
    picks_per_family: number;
    max_positions: number;
    allocation_per_pick_pct: number;
    unfilled_slots_are_cash: boolean;
  };
  market_regime: {
    index_vt_symbol: string;
    definition: string;
    labels: Record<string, string>;
  };
  families: {
    trend_pullback: LowSuctionFamilyReport;
    oversold_rebound: LowSuctionFamilyReport;
  };
  position_sim: {
    trend_pullback: LowSuctionFamilySim;
    oversold_rebound: LowSuctionFamilySim;
  };
}

export interface LowSuctionBacktestPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  report?: LowSuctionBacktestReport | null;
  rebuild?: LowSuctionRebuildStatus;
}

export interface LowSuctionRebuildRun {
  id: number;
  source: string;
  status: "running" | "ready" | "failed" | "already_running" | "interrupted";
  stage: string;
  strategy_version: string;
  score_version: string;
  requested_at: string;
  started_at: string | null;
  stage_started_at: string | null;
  finished_at: string | null;
  message: string | null;
  error: string | null;
  metrics: Record<string, number>;
}

export interface LowSuctionRebuildStatus {
  status: "idle" | "building" | "ready" | "failed";
  run_id?: number | null;
  source?: string | null;
  stage?: string | null;
  stage_started_at?: string | null;
  message?: string | null;
  metrics?: Record<string, number>;
  started_at?: string | null;
  finished_at?: string | null;
  error?: { type: string; message: string } | null;
  already_running?: boolean;
  trade_days?: number;
  labeled?: number;
  recent_runs?: LowSuctionRebuildRun[];
}

export interface LowSuctionLedgerLeg {
  trade_date: string;
  d1_trade_date: string | null;
  vt_symbol: string;
  symbol: string;
  stock_name?: string | null;
  setup_type: "trend_pullback" | "oversold_rebound";
  rank: number;
  allocation_pct: number;
  rule_key: string;
  score: number;
  band: string;
  close_price: number | null;
  d1_close_return_pct: number | null;
  streak_total: number;
}

export interface LowSuctionLedgerDay {
  trade_date: string;
  d1_trade_date: string | null;
  day_return_pct: number | null;
  legs: LowSuctionLedgerLeg[];
}

export interface LowSuctionLedgerPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  ledger_days: LowSuctionLedgerDay[];
  coverage?: LowSuctionBacktestReport["coverage"];
  label_convention?: string;
}

export function fetchLowSuctionLive({
  trendPage = 1,
  oversoldPage = 1,
  date,
}: {
  trendPage?: number;
  oversoldPage?: number;
  date?: string;
} = {}) {
  const query = new URLSearchParams({
    trend_page: String(trendPage),
    oversold_page: String(oversoldPage),
  });
  if (date) query.set("date", date);
  return apiClient.get<LowSuctionLivePayload>(
    `/low-suction/live?${query.toString()}`,
  );
}

export function fetchLowSuctionLiveDates() {
  return apiClient.get<{ dates: string[] }>("/low-suction/live/dates");
}

export function fetchLowSuctionBacktest() {
  return apiClient.get<LowSuctionBacktestPayload>("/low-suction/backtest");
}

export function rebuildLowSuctionBacktest() {
  return apiClient.post<LowSuctionRebuildStatus>("/low-suction/backtest/rebuild");
}

export function fetchLowSuctionBacktestStatus() {
  return apiClient.get<LowSuctionRebuildStatus>("/low-suction/backtest/status");
}

export function fetchLowSuctionLedger() {
  return apiClient.get<LowSuctionLedgerPayload>("/low-suction/ledger");
}

/** 说明书案例：单案的 D+N 收盘收益（后端现算，session-indexed）。 */
export interface GuideCaseReturns {
  d1_close_return_pct: number | null;
  d3_close_return_pct: number | null;
  d5_close_return_pct: number | null;
  /** available / missing_exit_session / raw_price_limit_outlier / signal_date_not_found / bars_unavailable */
  status: string;
}

/** 说明书案例：策展经典案例（真实历史股票 + 信号日 + 底盘叙事起点）。 */
export interface GuideCaseItem {
  case_id: string;
  name: string;
  vt_symbol: string;
  signal_date: string;
  setup_type: "trend_pullback" | "oversold_rebound";
  narrative_start_date: string | null;
  expected_launch_date: string | null;
  source_anchor: string;
  /** complete / research_pending */
  narrative_status: string;
  returns: GuideCaseReturns;
}

export interface GuideCasesRule {
  rule_key: string;
  description: string;
  tier: "product" | "research";
  product_tier: "P1.5" | "P1" | null;
  cases: GuideCaseItem[];
}

export interface GuideCasesFamily {
  key: "trend_pullback" | "oversold_rebound";
  label: string;
  rules: GuideCasesRule[];
}

export interface GuideCasesPayload {
  status: "ok" | "partial";
  score_version: string;
  families: GuideCasesFamily[];
  /** 无 rule_key 的待验证锚点案例（research_pending）。 */
  orphan_cases: GuideCaseItem[];
}

export function fetchLowSuctionGuideCases() {
  return apiClient.get<GuideCasesPayload>("/low-suction/guide/cases");
}
