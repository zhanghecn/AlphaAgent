import { apiClient } from "./client";

// ── N型补涨打板(V3 三组体系升级 V4)产品线 API 契约 ──
// 策略口径 = w2s-v4.0(量化因子研究/低吸研究/N型补涨打板.md 定稿)。
// 买点 = 断板后再启动首个涨停板板上买(触板买涨停价,一字排除);
// 池 = 触发池全量(雷达),白名单出手标记 actionable。

export type W2sGroupKey = "yin2" | "yang2a" | "yang2b" | "yin4" | "yang4";

export interface W2sLiveEntry {
  vt_symbol: string;
  name: string | null;
  group_key: W2sGroupKey;
  actionable: boolean;
  prev_close: number | null;
  trigger_price: number | null;
  limit_price: number | null;
  chg_tm1: number | null;
  ushadow_tm1: number | null;
  yang_tm1: boolean | null;
  base: string | null;
  base_label: string | null;
  pos3: "无坑" | "坑内" | "已回顶" | null;
  /** 坑深%(断板期最低收盘距上波顶,负值) */
  low_dd: number | null;
  /** 距顶%(信号日收盘距上波顶,负值) */
  pull: number | null;
  /** 弹回%(信号日收盘距坑底弹回幅度) */
  reb: number | null;
  ma_st: string | null;
  n_lim_mid: number | null;
  topped: boolean | null;
  d23ok: boolean | null;
  seg_h: number | null;
  gap_days: number | null;
  status:
    | "watching" | "touched" | "entered" | "holding" | "pending_exit" | "closed"
    | "skipped_gap" | "no_trigger";
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
    | null;
  ret_pct: number | null;
}

export interface W2sLivePayload {
  status: "ok";
  trade_date: string;
  stale: boolean;
  session_stage: "preopen" | "auction" | "morning" | "lunch" | "afternoon" | "closed";
  rules_version: string;
  counts: {
    pool: number;
    actionable: number;
    signals: number;
    by_group: Record<string, number>;
    by_status: Record<string, number>;
  };
  /** 昨日主板非ST涨停家数(信息项,V4 无大盘停手) */
  mkt_lim_tm1: number | null;
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
  bw_pct: number;
  bw_win: number;
}

export interface W2sAnchorCheck {
  n_diff: number;
  bw_diff: number;
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
  /** 单一口径(板上买·板留断走):key = 五组 + "all" */
  summary: Record<string, W2sStats>;
  yearly: Record<string, ({ year: string } & W2sStats)[]>;
  monthly: Record<string, ({ month: string } & W2sStats)[]>;
  curves: Record<string, { date: string; cum_pct: number }[]>;
  anchors: Record<string, W2sAnchorStats>;
  anchor_tolerances: Record<string, number>;
  anchor_check: Record<string, W2sAnchorCheck | string>;
  case_gates: W2sCaseGate[];
  /** 触发池(雷达)全量 vs 白名单出手笔数:key = 五组 + "all" */
  radar: Record<string, { trigger_n: number; actionable_n: number }>;
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
  group: "pool" | W2sGroupKey | "buy" | "sell";
  title: string;
  items: W2sRuleItem[];
}

export interface W2sTouchWindow {
  group: "yin2" | "yang2" | "yin4" | "yang4";
  label: string;
  window: string;
  n: number;
  ret: number;
  win: number;
  note: string;
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
  anchors: Record<string, W2sAnchorStats>;
  anchor_tolerances: Record<string, number>;
  case_gates: Omit<W2sCaseGate, "actual_groups" | "pass">[];
  touch_time_windows: { meta: string; groups: W2sTouchWindow[] };
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
