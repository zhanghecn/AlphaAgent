import { apiClient } from "./client";

// ── 高位接力打板(二接三/三接四)产品线 API 契约 ──
// 策略口径 = hpr-v2.0 连板链组合方案(量化因子研究/高位接力/汇总/连板链组合总结.md,2026-09-25定稿)。
// 买点 = 昨日恰好2/3连板,链条件(前几板开盘档)命中且今天开盘在方案窗内(6~9.5为主),
// 触涨停价即打(无时间窗);开盘≥9.5%顶格不命中(正常开盘口径)。
// 池 = 昨日2/3连板全量(雷达),七方案 A1/A2(二接三阳) B1(二接三阴) C1/C2(三接四阳) D1/D2(三接四阴)。

export type HprPoint = "A1" | "A2" | "B1" | "C1" | "C2" | "D1" | "D2" | "—";
export type HprGroup4 = "二接三阴" | "二接三阳" | "三接四阴" | "三接四阳";

export type HprStatus =
  | "watching" | "sealed_watch" | "entered" | "holding" | "pending_exit" | "closed"
  | "skipped_auction" | "skipped_gap" | "late_touch" | "no_trigger";

export interface HprLiveEntry {
  vt_symbol: string;
  name: string | null;
  group4: HprGroup4;
  n_board: number | null;
  point: HprPoint;
  level: "A" | "B" | "—";
  actionable: boolean;
  avoid_static: string | null;
  auction_gate: "a2_0_9.5" | "b2_4_7" | null;
  prev_close: number | null;
  limit_price: number | null;
  foundation_yang: boolean | null;
  foundation_chg: number | null;
  dist_h60: number | null;
  ma_state: string | null;
  dist_ma10: number | null;
  prior_height: number | null;
  prev_wave60: number | null;
  prev_wave120: number | null;
  chain: string | null;
  b1_open: number | null;
  b2_open: number | null;
  b1_turn: number | null;
  b2_turn: number | null;
  turn_grad: number | null;
  status: HprStatus;
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
  exit_reason:
    | "break_day_close" | "next_close_fail" | "break_close" | "max_hold_close"
    | null;
  ret_pct: number | null;
}

export interface HprLivePayload {
  status: "ok";
  trade_date: string;
  stale: boolean;
  session_stage:
    | "preopen" | "auction" | "first_window" | "morning" | "lunch" | "afternoon" | "closed";
  rules_version: string;
  counts: {
    pool: number;
    actionable: number;
    signals: number;
    by_group: Record<string, number>;
    by_point: Record<string, number>;
    by_status: Record<string, number>;
  };
  /** 昨日主板非ST涨停家数(信息项) */
  mkt_lim_tm1: number | null;
  group4_labels: Record<HprGroup4, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "A" | "B">;
  last_scan: { finished_at: string | null; status: string; message: string | null } | null;
  entries: HprLiveEntry[];
}

export interface HprStats {
  n: number;
  seal?: number;
  avg_pct?: number | null;
  win?: number | null;
  bw_pct?: number | null;
  bw_median?: number | null;
  bw_win?: number | null;
  e3_pct?: number | null;
  e3_win?: number | null;
}

export interface HprAnchorStats {
  n: number;
  bw_pct: number;
  bw_win: number;
}

export interface HprAnchorCheck {
  n_diff: number;
  bw_diff: number;
  win_diff: number;
  pass: boolean;
}

export interface HprCaseGate {
  name: string;
  date: string;
  expect: string;
  actual_points: string[];
  pass: boolean;
  note: string;
}

export interface HprYearlyTotal {
  year: string;
  n: number;
  avg_pct: number | null;
  sum_pct: number;
  compound_pct: number | null;
}

export interface HprExecSubset {
  name: string;
  n: number;
  e0_win: number | null;
  e0_pct: number | null;
  e3_pct: number | null;
  e3_win: number | null;
  e3_worst: number | null;
  yearly: { year: string; n: number; e3_pct: number }[];
}

export interface HprBacktestReport {
  rules_version: string;
  generated_at: string;
  coverage: { from: string; to: string; months: number };
  caliber: string;
  group4_labels: Record<HprGroup4, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "A" | "B">;
  /** key = 五点 + "A级" + "all" + "miss" */
  summary: Record<string, HprStats>;
  yearly: Record<string, ({ year: string } & HprStats)[]>;
  monthly: Record<string, ({ month: string } & HprStats)[]>;
  curves: Record<string, { date: string; cum_pct: number }[]>;
  yearly_totals: HprYearlyTotal[];
  execution: { caliber: string; subsets: HprExecSubset[] };
  anchors: Record<string, HprAnchorStats>;
  anchor_tolerances: Record<string, number>;
  anchor_check: Record<string, HprAnchorCheck | string>;
  case_gates: HprCaseGate[];
  avoid_stats: Record<string, { hit_n: number; avoid_n: number }>;
  radar: Record<string, { trigger_n: number; hit_n: number }>;
  built_at?: string | null;
}

export interface HprRebuildStatus {
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

export interface HprBacktestPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  report?: HprBacktestReport;
  rebuild: HprRebuildStatus;
}

export interface HprLedgerTrade {
  vt_symbol: string;
  name: string;
  point: HprPoint;
  level: "A" | "B" | "—";
  group4: HprGroup4;
  entry_price: number | null;
  auction_pct: number | null;
  sealed: boolean;
  streak_h: number;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason:
    | "break_day_close" | "next_close_fail" | "break_close" | "max_hold_close"
    | null;
  /** E3 收益(产品卖出纪律) */
  ret_pct: number | null;
  /** E0 收益(研究持有到断板口径,对照) */
  ret_e0: number | null;
  /** 首触板15分钟K周期末刻(如"09:45"=首刻段); null=无分钟数据(2024-08前) */
  touch: string | null;
}

export interface HprLedgerDay {
  trade_date: string;
  count: number;
  win: number;
  avg_ret_pct: number | null;
  trades: HprLedgerTrade[];
}

export interface HprLedgerMonth {
  month: string;
  count: number;
  win_rate: number | null;
  avg_ret_pct: number | null;
  total_ret_pct: number;
}

export interface HprLedgerPayload {
  status: "ok" | "unavailable";
  is_backtest?: boolean;
  coverage?: HprBacktestReport["coverage"];
  caliber?: string;
  month?: string | null;
  months?: HprLedgerMonth[];
  ledger_days: HprLedgerDay[];
}

export interface HprRuleItem {
  no: number;
  rule: string;
  evidence: string;
}

export interface HprRuleGroup {
  group: "pool" | HprPoint | "avoid" | "time" | "buy" | "sell";
  title: string;
  items: HprRuleItem[];
}

export interface HprRulesPayload {
  rules_version: string;
  group4_labels: Record<HprGroup4, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "A" | "B">;
  point_desc: Record<string, string>;
  rules: HprRuleGroup[];
  falsified_rules: string[];
  risk_notes: string[];
  ths_pool_conditions: Record<string, string>;
  ths_pool_note: string;
  intraday_playbook: string[];
  anchors: Record<string, HprAnchorStats>;
  anchor_tolerances: Record<string, number>;
  case_gates: Omit<HprCaseGate, "actual_points" | "pass">[];
}

export function fetchHprLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<HprLivePayload>(`/high-relay/live${query}`);
}

export function fetchHprLiveDates() {
  return apiClient.get<{ dates: string[] }>("/high-relay/live/dates");
}

export function fetchHprBacktest() {
  return apiClient.get<HprBacktestPayload>("/high-relay/backtest");
}

export function rebuildHprBacktest() {
  return apiClient.post<HprRebuildStatus>("/high-relay/backtest/rebuild");
}

export function fetchHprBacktestStatus() {
  return apiClient.get<HprRebuildStatus>("/high-relay/backtest/status");
}

export function fetchHprLedger(month?: string) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return apiClient.get<HprLedgerPayload>(`/high-relay/ledger${query}`);
}

export function fetchHprRules() {
  return apiClient.get<HprRulesPayload>("/high-relay/rules");
}
