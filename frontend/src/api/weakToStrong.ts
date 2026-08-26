import { apiClient } from "./client";

// ── 趋势弱转强(二板弱转强打板)产品线 API 契约 ──
// 策略口径 = w2s-v2(量化因子研究/低吸研究/趋势低吸研究-弱转强v2.md 定稿)。

export type W2sGroupKey = "a1" | "a2" | "b";

export interface W2sLiveEntry {
  vt_symbol: string;
  name: string | null;
  group_key: W2sGroupKey;
  prev_close: number | null;
  trigger_price: number | null;
  limit_price: number | null;
  chg_tm1: number | null;
  lshadow_tm1: number | null;
  ushadow_tm1: number | null;
  yang_tm1: boolean | null;
  vol_rel5_tm1: number | null;
  amp_tm1: number | null;
  turnover_tm1: number | null;
  base20_tm1: number | null;
  last_streak: number | null;
  gap_days: number | null;
  halted: boolean;
  status:
    | "watching" | "touched" | "entered" | "holding" | "pending_exit" | "closed"
    | "skipped_gap" | "halted" | "no_trigger";
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
  exit_reason:
    | "next_close_fail" | "break_close" | "max_hold_close" | "open_end"
    | "same_day_fail" | null;
  ret_pct: number | null;
}

export interface W2sMarketHalt {
  halted: boolean;
  mkt_lim_tm1: number | null;
  threshold: number;
  note: string;
}

export interface W2sLivePayload {
  status: "ok";
  trade_date: string;
  stale: boolean;
  session_stage: "preopen" | "auction" | "morning" | "lunch" | "afternoon" | "closed";
  rules_version: string;
  counts: {
    pool: number;
    signals: number;
    by_group: Record<string, number>;
    by_status: Record<string, number>;
  };
  market_halt: W2sMarketHalt;
  group_labels: Record<W2sGroupKey, string>;
  last_scan: { finished_at: string | null; status: string; message: string | null } | null;
  entries: W2sLiveEntry[];
}

export interface W2sStats {
  n: number;
  seal?: number;
  avg_pct?: number;
  win?: number;
  streak2?: number;
  bw_pct?: number | null;
  bw_win?: number | null;
}

export interface W2sAnchorStats {
  n: number;
  seal: number;
  avg_pct: number;
  win: number;
  streak2: number;
  bw_pct: number;
}

export interface W2sAnchorCheck {
  n_diff: number;
  avg_diff: number;
  win_diff: number;
  pass: boolean;
}

export interface W2sCaseGate {
  name: string;
  date: string;
  expect: string;
  actual_groups: string[];
  pass: boolean;
  note: string;
}

export interface W2sBacktestReport {
  rules_version: string;
  generated_at: string;
  coverage: { from: string; to: string; months: number };
  caliber: string;
  group_labels: Record<W2sGroupKey, string>;
  summary: Record<string, W2sStats>;
  yearly: Record<W2sGroupKey, ({ year: string } & W2sStats)[]>;
  monthly: Record<W2sGroupKey, ({ month: string } & W2sStats)[]>;
  curves: Record<W2sGroupKey, { date: string; cum_pct: number }[]>;
  anchors: Record<string, W2sAnchorStats>;
  anchor_tolerances: Record<string, number>;
  anchor_check: Record<string, W2sAnchorCheck | string>;
  case_gates: W2sCaseGate[];
  built_at?: string | null;
}

export interface W2sRebuildStatus {
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

export interface W2sBacktestPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  report?: W2sBacktestReport;
  rebuild: W2sRebuildStatus;
}

export interface W2sLedgerTrade {
  vt_symbol: string;
  name: string;
  group: W2sGroupKey;
  group_label: string;
  entry_price: number | null;
  gap_open_pct: number | null;
  sealed: boolean;
  streak_h: number;
  exit_date: string;
  exit_price: number | null;
  exit_reason: "next_close_fail" | "break_close" | "max_hold_close" | "open_end";
  ret_pct: number | null;
}

export interface W2sLedgerDay {
  trade_date: string;
  count: number;
  win: number;
  avg_ret_pct: number | null;
  trades: W2sLedgerTrade[];
}

export interface W2sLedgerMonth {
  month: string;
  count: number;
  win_rate: number | null;
  avg_ret_pct: number | null;
  total_ret_pct: number;
}

export interface W2sLedgerPayload {
  status: "ok" | "unavailable";
  is_backtest?: boolean;
  coverage?: W2sBacktestReport["coverage"];
  caliber?: string;
  month?: string | null;
  months?: W2sLedgerMonth[];
  ledger_days: W2sLedgerDay[];
}

export interface W2sRuleItem {
  no: number;
  rule: string;
  evidence: string;
}

export interface W2sRuleGroup {
  group: "pool" | "a1" | "a2" | "b" | "buy" | "sell";
  title: string;
  items: W2sRuleItem[];
}

export interface W2sSessionWindowRow {
  group: W2sGroupKey;
  window: string;
  share: string;
  note: string;
}

export interface W2sSessionTableRow {
  group: W2sGroupKey;
  bucket: string;
  n: number;
  seal: number;
  d1: number;
  d1_win: number;
  n2_lim: number;
  ret: number;
  ret_win: number;
}

export interface W2sSessionWindow {
  headline: string;
  rows: W2sSessionWindowRow[];
  table_columns?: string[];
  table_rows?: W2sSessionTableRow[];
  warning: string;
  research_note: string;
}

export interface W2sRulesPayload {
  rules_version: string;
  group_labels: Record<W2sGroupKey, string>;
  rules: W2sRuleGroup[];
  falsified_rules: string[];
  risk_notes: string[];
  ths_pool_conditions: Record<W2sGroupKey, string>;
  ths_pool_note: string;
  intraday_playbook: string[];
  session_window: W2sSessionWindow;
  anchors: Record<string, W2sAnchorStats>;
  anchor_tolerances: Record<string, number>;
  case_gates: Omit<W2sCaseGate, "actual_groups" | "pass">[];
}

export function fetchW2sLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<W2sLivePayload>(`/weak-to-strong/live${query}`);
}

export function fetchW2sLiveDates() {
  return apiClient.get<{ dates: string[] }>("/weak-to-strong/live/dates");
}

export function fetchW2sBacktest() {
  return apiClient.get<W2sBacktestPayload>("/weak-to-strong/backtest");
}

export function rebuildW2sBacktest() {
  return apiClient.post<W2sRebuildStatus>("/weak-to-strong/backtest/rebuild");
}

export function fetchW2sBacktestStatus() {
  return apiClient.get<W2sRebuildStatus>("/weak-to-strong/backtest/status");
}

export function fetchW2sLedger(month?: string) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return apiClient.get<W2sLedgerPayload>(`/weak-to-strong/ledger${query}`);
}

export function fetchW2sRules() {
  return apiClient.get<W2sRulesPayload>("/weak-to-strong/rules");
}
