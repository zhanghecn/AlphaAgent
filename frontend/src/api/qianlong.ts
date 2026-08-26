import { apiClient } from "./client";

// ── 潜龙首板(首板打板)产品线 API 契约 ──
// 策略口径 = qianlong v4(量化因子研究/潜龙首板/潜龙首板条件定稿.md)。

export interface QianlongLiveEntry {
  vt_symbol: string;
  name: string | null;
  prev_close: number | null;
  trigger_price: number | null;
  limit_price: number | null;
  chg_tm1: number | null;
  turnover_rate_tm1: number | null;
  market_cap_yi: number | null;
  dist_ma20: number | null;
  status:
    | "watching" | "touched" | "holding" | "pending_exit" | "closed"
    | "unconfirmed" | "skipped_gap" | "no_trigger";
  priority: boolean;
  chassis_tag: string | null;
  trend_days: number | null;
  lu_cnt20: number | null;
  lu_cnt60: number | null;
  gap_open_pct: number | null;
  touched_at: string | null;
  entry_price: number | null;
  entry_time: string | null;
  last_price: number | null;
  change_pct: number | null;
  sealed: boolean | null;
  streak_h: number | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: "next_open_fail" | "next_open_nostreak" | "break_open" | null;
  ret_pct: number | null;
}

export interface QianlongCircuitBreaker {
  month: string;
  realized_pct: number;
  threshold_pct: number;
  halted: boolean;
  closed_trades: number;
  note: string;
}

export interface QianlongLivePayload {
  status: "ok";
  trade_date: string;
  stale: boolean;
  session_stage: "preopen" | "morning" | "lunch" | "afternoon_closed_for_entry" | "closed";
  rules_version: string;
  counts: Record<string, number>;
  circuit_breaker: QianlongCircuitBreaker;
  time_window?: QianlongTimeWindow | null;
  last_scan: { finished_at: string | null; status: string; message: string | null } | null;
  entries: QianlongLiveEntry[];
}

export interface QianlongWindowStats {
  n: number;
  seal: number;   // 触板率%
  streak: number; // 连板率%
  d1: number;     // D+1 均价%
  ret: number;    // 均笔收益%
}

export interface QianlongTimeWindow {
  level: "prep" | "gold" | "fading" | "weak" | "lunch" | "none" | "closed";
  label: string;
  start: string;
  end: string;
  advice: string;
  stats?: { a?: QianlongWindowStats; b?: QianlongWindowStats };
}

export interface QianlongStats {
  n: number;
  avg_pct?: number;
  median_pct?: number;
  win?: number;
  seal?: number;
  streak2?: number;
}

export interface QianlongSimSummary {
  trades: number;
  final_equity: number;
  total_return_pct: number;
  win_rate_pct: number | null;
  max_drawdown_pct: number;
  curve: { date: string; equity: number }[];
}

export interface QianlongBacktestReport {
  rules_version: string;
  generated_at: string;
  coverage: { from: string; to: string; months: number };
  caliber: string;
  summary: QianlongStats;
  chassis_a_subset: QianlongStats;
  chassis_b_subset: QianlongStats;
  chassis_ab_subset: QianlongStats;
  segments: Record<string, QianlongStats>;
  monthly: ({ month: string; ret_pct?: number; signal_days?: number } & QianlongStats)[];
  anchors: Record<string, number>;
  anchor_check: Record<string, number | string>;
  simulation: {
    note: string;
    plain: QianlongSimSummary;
    with_circuit_breaker: QianlongSimSummary;
  };
  built_at?: string | null;
}

export interface QianlongRebuildStatus {
  status: "idle" | "queued" | "running" | "done" | "failed";
  stage?: string;
  source?: string;
  rules_version?: string;
  requested_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  message?: string | null;
  error?: string | null;
  metrics?: Record<string, unknown>;
  already_running?: boolean;
  run_id?: number;
}

export interface QianlongBacktestPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  report?: QianlongBacktestReport;
  rebuild: QianlongRebuildStatus;
}

export interface QianlongLedgerTrade {
  vt_symbol: string;
  name: string;
  chassis_tag: string | null;
  entry_date: string;
  entry_price: number | null;
  gap_open_pct: number | null;
  priority: boolean;
  sealed: boolean;
  streak_h: number;
  exit_price: number | null;
  exit_date: string;
  exit_reason: "next_open_fail" | "next_open_nostreak" | "break_open";
  ret_pct: number | null;
}

export interface QianlongLedgerDay {
  trade_date: string;
  count: number;
  win: number;
  avg_ret_pct: number | null;
  trades: QianlongLedgerTrade[];
}

export interface QianlongLedgerMonth {
  month: string;
  count: number;
  win_rate: number | null;
  avg_ret_pct: number | null;
  /** 月收益(精确式):Σ当日全部信号等权均值,每天满仓当日全部信号、非复利 */
  month_ret_pct: number;
  signal_days: number;
}

export interface QianlongLedgerPayload {
  status: "ok" | "unavailable";
  is_backtest?: boolean;
  coverage?: QianlongBacktestReport["coverage"];
  caliber?: string;
  month?: string | null;
  months?: QianlongLedgerMonth[];
  ledger_days: QianlongLedgerDay[];
}

export interface QianlongRuleItem {
  no: number;
  rule: string;
  evidence: string;
}

export interface QianlongRuleGroup {
  group: "pool" | "buy" | "sell" | "risk";
  title: string;
  items: QianlongRuleItem[];
}

export interface QianlongGapGroupStats {
  n: number;
  seal: number;
  d1_win: number;
  ret: number;
}

export interface QianlongAuctionGapRow {
  label: string;
  n: number;
  seal: number;
  d1_win: number;
  ret: number;
  verdict: "best" | "good" | "neutral" | "caution" | "avoid";
  advice: string;
  a?: QianlongGapGroupStats;
  b?: QianlongGapGroupStats;
  cells?: ({ seal: number; n: number } | null)[];
  cells_a?: ({ seal: number; n: number; ret: number } | null)[];
  cells_b?: ({ seal: number; n: number; ret: number } | null)[];
}

export interface QianlongGroupRangeItem {
  gap: string;
  tone: "good" | "gold_only" | "caution" | "avoid";
  action: string;
}

export interface QianlongGroupRanges {
  group: string;
  label: string;
  ranges: QianlongGroupRangeItem[];
}

export interface QianlongAuctionMatrix {
  caliber: string;
  group_ranges?: QianlongGroupRanges[];
  matrix_buckets: string[];
  gap_rows: QianlongAuctionGapRow[];
  note: string;
}

export interface QianlongRulesPayload {
  rules_version: string;
  rules: QianlongRuleGroup[];
  falsified_rules: string[];
  risk_notes: string[];
  ths_pool_conditions: string;
  ths_pool_conditions_b: string;
  ths_pool_note: string;
  intraday_playbook: string[];
  intraday_windows?: QianlongTimeWindow[];
  intraday_windows_note?: string;
  auction_matrix?: QianlongAuctionMatrix;
  anchors: Record<string, number>;
}

export function fetchQianlongLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<QianlongLivePayload>(`/qianlong/live${query}`);
}

export function fetchQianlongLiveDates() {
  return apiClient.get<{ dates: string[] }>("/qianlong/live/dates");
}

export function fetchQianlongBacktest() {
  return apiClient.get<QianlongBacktestPayload>("/qianlong/backtest");
}

export function rebuildQianlongBacktest() {
  return apiClient.post<QianlongRebuildStatus>("/qianlong/backtest/rebuild");
}

export function fetchQianlongBacktestStatus() {
  return apiClient.get<QianlongRebuildStatus>("/qianlong/backtest/status");
}

export function fetchQianlongLedger(month?: string) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return apiClient.get<QianlongLedgerPayload>(`/qianlong/ledger${query}`);
}

export function fetchQianlongRules() {
  return apiClient.get<QianlongRulesPayload>("/qianlong/rules");
}
