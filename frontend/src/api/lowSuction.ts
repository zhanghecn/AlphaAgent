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
}

export interface LowSuctionLiveFamily {
  total: number;
  items: LowSuctionCandidate[];
}

export interface LowSuctionLivePayload {
  status: "ok" | "unavailable";
  message?: string;
  asof?: string;
  trade_date?: string;
  provisional?: boolean;
  merge_note?: string | null;
  cache_ttl_seconds?: number;
  score_version?: string;
  label_convention?: string;
  trend?: LowSuctionLiveFamily;
  oversold?: LowSuctionLiveFamily;
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
  compound_pct: number;
  max_drawdown_pct?: number;
}

export interface LowSuctionEquityPoint {
  date: string;
  equity: number;
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
  families: {
    trend_pullback: LowSuctionFamilyReport;
    oversold_rebound: LowSuctionFamilyReport;
  };
  position_sim: {
    trend_pullback: LowSuctionSimSummary;
    oversold_rebound: LowSuctionSimSummary;
    combined: LowSuctionSimSummary;
    equity_curve: LowSuctionEquityPoint[];
  };
}

export interface LowSuctionBacktestPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  report?: LowSuctionBacktestReport | null;
  rebuild?: LowSuctionRebuildStatus;
}

export interface LowSuctionRebuildStatus {
  status: "idle" | "building" | "ready" | "failed";
  started_at?: string | null;
  finished_at?: string | null;
  error?: { type: string; message: string } | null;
  already_running?: boolean;
  trade_days?: number;
  labeled?: number;
}

export interface LowSuctionLedgerLeg {
  trade_date: string;
  d1_trade_date: string | null;
  vt_symbol: string;
  symbol: string;
  stock_name?: string | null;
  setup_type: "trend_pullback" | "oversold_rebound";
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
  day_return_pct: number;
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

export function fetchLowSuctionLive() {
  return apiClient.get<LowSuctionLivePayload>("/low-suction/live");
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
