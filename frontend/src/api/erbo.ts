import { apiClient } from "./client";

// ── 二波反包打板(erbo)产品线 API 契约 ──
// 口径 = erbo-v1.0(妖股波段二波反包研究定稿 2026-10-01)。
// 事件 = 30日波段50~80%×深洗8~15%×MA20上方5%×30日涨停≥2×昨阴×断板3~7天
// → 今日盘中触涨停价按涨停价买;出手档=末日开盘 A平开-2~2/B深低开≤-4;
// 死格(末开-4~-2浅低开/末开>+2高开)只留雷达;卖出=T+1(同断板反包)。

export type ErboPoint = "A" | "B" | "—";

export type ErboStatus =
  | "watching" | "sealed_watch" | "entered" | "holding" | "pending_exit"
  | "closed" | "skipped_gap" | "no_trigger";

export interface ErboLiveEntry {
  vt_symbol: string;
  name: string | null;
  gap: number | null;
  gain30_pct: number | null;
  dd_pct: number | null;
  ma20gap_pct: number | null;
  lim30: number | null;
  yin_yang: string | null;
  last_open_pct: number | null;
  point: ErboPoint;
  level: string;
  actionable: boolean;
  avoid_static: string | null;
  cold_market: boolean | null;
  prev_close: number | null;
  limit_price: number | null;
  status: ErboStatus;
  auction_pct: number | null;
  opened: boolean | null;
  touched_at: string | null;
  entry_price: number | null;
  entry_time: string | null;
  last_price: number | null;
  change_pct: number | null;
  sealed: boolean | null;
  streak_h: number | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  ret_pct: number | null;
  bad_ticket: boolean | null;
}

export interface ErboLivePayload {
  status: "ok";
  trade_date: string;
  stale: boolean;
  session_stage: string;
  rules_version: string;
  counts: {
    pool: number;
    actionable: number;
    signals: number;
    by_point: Record<string, number>;
    by_status: Record<string, number>;
  };
  point_labels: Record<string, string>;
  point_levels: Record<string, string>;
  last_scan: { finished_at: string | null; status: string | null; message: string | null } | null;
  entries: ErboLiveEntry[];
}

export interface ErboStats {
  n: number;
  seal?: number;
  seal_fail?: number | null;
  avg_pct?: number | null;
  win?: number | null;
  bw_pct?: number | null;
  bw_median?: number | null;
  bw_win?: number | null;
}

export interface ErboBacktestReport {
  rules_version: string;
  generated_at: string;
  coverage: { from: string | null; to: string | null; months: number };
  caliber: string;
  point_labels: Record<string, string>;
  point_levels: Record<string, string>;
  summary: Record<string, ErboStats>;
  dead_summary: ErboStats;
  yearly: Record<string, ({ year: string } & ErboStats)[]>;
  monthly: Record<string, { month: string; n: number; bw_pct: number }[]>;
  ledger_days: ErboLedgerDay[];
  anchors: Record<string, { n: number; bw_pct: number; bw_win: number | null }>;
  anchor_tolerances: Record<string, number>;
  anchor_check: Record<string, { n_diff: number; bw_diff: number; pass: boolean } | string>;
  case_gates: { name: string; date: string; expect: string; actual: unknown; pass: boolean; note: string }[];
  built_at?: string | null;
}

export interface ErboLedgerTrade {
  vt_symbol: string;
  name: string;
  point: ErboPoint;
  level: string;
  gap: number;
  gain30_pct: number;
  dd_pct: number;
  ma20gap_pct: number;
  lim30: number | null;
  last_open_pct: number | null;
  entry_price: number | null;
  sealed: boolean;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  ret_pct: number | null;
  is_bad: boolean;
}

export interface ErboLedgerDay {
  trade_date: string;
  count: number;
  win: number;
  bad: number;
  avg_ret_pct: number | null;
  trades: ErboLedgerTrade[];
}

export interface ErboLedgerPayload {
  status: "ok" | "unavailable";
  coverage?: { from: string | null; to: string | null; months: number };
  caliber?: string;
  month?: string | null;
  months?: { month: string; count: number; win_rate: number | null; avg_ret_pct: number | null; total_ret_pct: number }[];
  ledger_days?: ErboLedgerDay[];
}

export interface ErboRebuildStatus {
  status: string;
  stage?: string;
  source?: string;
  rules_version?: string;
  finished_at?: string | null;
  message?: string | null;
  error?: string | null;
  metrics?: Record<string, unknown>;
}

export interface ErboRulesPayload {
  rules_version: string;
  point_labels: Record<string, string>;
  point_levels: Record<string, string>;
  point_desc: Record<string, string>;
  rules: { group: string; title: string; items: { no: number; rule: string; evidence: string }[] }[];
  falsified_rules: string[];
  risk_notes: string[];
  intraday_playbook: string[];
}

export function fetchErboLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<ErboLivePayload>(`/erbo/live${query}`);
}

export function fetchErboLiveDates() {
  return apiClient.get<{ dates: string[] }>("/erbo/live/dates");
}

export function fetchErboBacktest() {
  return apiClient.get<{
    status: string;
    report?: ErboBacktestReport;
    rebuild?: ErboRebuildStatus;
    message?: string;
  }>("/erbo/backtest");
}

export function rebuildErboBacktest() {
  return apiClient.post<unknown>("/erbo/backtest/rebuild");
}

export function fetchErboBacktestStatus() {
  return apiClient.get<ErboRebuildStatus>("/erbo/backtest/status");
}

export function fetchErboLedger(month?: string) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return apiClient.get<ErboLedgerPayload>(`/erbo/ledger${query}`);
}

export function fetchErboRules() {
  return apiClient.get<ErboRulesPayload>("/erbo/rules");
}
