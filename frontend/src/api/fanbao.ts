import { apiClient } from "./client";

// ── 断板反包打板(2/4/5+板断板1~3天后再涨停)产品线 API 契约 ──
// 策略口径 = fbb-v2.0(量化因子研究/反包/反包规则.md 定稿)。
// 事件 = 前波恰好2/4/5+连板(5+无上限)→断板1~3天→今日盘中触涨停价打板;
// 池 = 断板中全量(雷达),五方案点 S1/S2/S3(出手级) O1/O2(观察级) 命中才出手,
// 死格命中也不买;无首刻窗(与高位接力最大差异:触板即买)。
// ⚠️ 双口径:yin_yang=跌幅口径(分组,昨收<前日收=阴);break_yin_count=实体口径(S1条件)。

export type FbbPoint = "S1" | "S2" | "S3" | "O1" | "O2" | "—";
export type FbbGroup6 =
  | "2板阴" | "2板阳" | "4板阴" | "4板阳" | "5+板阴" | "5+板阳";

export type FbbStatus =
  | "watching" | "sealed_watch" | "entered" | "holding" | "pending_exit"
  | "closed" | "skipped_gap" | "no_trigger";

export interface FbbLiveEntry {
  vt_symbol: string;
  name: string | null;
  group6: FbbGroup6;
  n_board: number | null;
  seg: string | null;
  gap: number | null;
  yin_yang: string | null;
  point: FbbPoint;
  level: "S" | "O" | "—";
  actionable: boolean;
  avoid_static: string | null;
  prev_close: number | null;
  limit_price: number | null;
  break_end: string | null;
  wave_start: string | null;
  /** 断板期逐日串(实体口径,如 "阴-3.2→阳+1.1") */
  break_days: string | null;
  /** 断板期实体阴线数(收盘<开盘;S1 条件口径) */
  break_yin_count: number | null;
  break_zha_days: number | null;
  /** 断板累计% = 昨收/末板收-1 */
  break_drop_pct: number | null;
  /** 坑深% = 断板期最低收盘/末板收-1 */
  pit_depth_pct: number | null;
  /** 末日实体阴/阳(收盘vs开盘;S2 条件口径) */
  last_entity: string | null;
  /** 末日开盘%(S1 要低开<=0 急杀;S2 要高开>2 洗透) */
  last_open_pct: number | null;
  /** S2 顶格开(>7%)高方差警示(减半仓,不剔除) */
  high_var: boolean | null;
  dist_ma5: number | null;
  dist_h60: number | null;
  ma_state: string | null;
  dist_ma10: number | null;
  chain: string | null;
  prev_wave60: number | null;
  prev_wave120: number | null;
  status: FbbStatus;
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
  /** 坏票=次日收盘<买价(仅统计标注) */
  bad_ticket: boolean | null;
}

export interface FbbLivePayload {
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
    by_gap: Record<string, number>;
    by_point: Record<string, number>;
    by_status: Record<string, number>;
  };
  /** 昨日主板非ST涨停家数(信息项) */
  mkt_lim_tm1: number | null;
  group6_labels: Record<FbbGroup6, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "S" | "O">;
  last_scan: { finished_at: string | null; status: string; message: string | null } | null;
  entries: FbbLiveEntry[];
}

export interface FbbStats {
  n: number;
  seal?: number;
  seal_fail?: number | null;
  avg_pct?: number | null;
  win?: number | null;
  bad?: number | null;
  bw_pct?: number | null;
  bw_median?: number | null;
  bw_win?: number | null;
  re_limit?: number | null;
}

export interface FbbAnchorStats {
  n: number;
  bw_pct: number;
  bw_win: number;
}

export interface FbbAnchorCheck {
  n_diff: number;
  bw_diff: number;
  win_diff: number;
  pass: boolean;
}

export interface FbbCaseGate {
  name: string;
  date: string;
  expect: string;
  actual_points: string[];
  pass: boolean;
  note: string;
}

export interface FbbYearlyTotal {
  year: string;
  n: number;
  avg_pct: number | null;
  sum_pct: number;
  compound_pct: number | null;
}

/** 18格矩阵行(六组×断1/2/3) */
export interface FbbMatrixCell extends FbbStats {
  group6: FbbGroup6;
  gap: number;
  follow0?: number | null;
  follow1?: number | null;
  follow2?: number | null;
  follow3plus?: number | null;
}

export interface FbbMatrixYearly {
  group6: FbbGroup6;
  gap: number;
  n: number;
  yearly: { year: string; bw_pct: number | null; n: number }[];
}

export interface FbbRefRow extends FbbStats {
  label: string;
}

export interface FbbSplitRow extends FbbStats {
  seg: string;
  yin?: string;
  pit?: string;
}

export interface FbbDeadStat extends FbbStats {
  group6: FbbGroup6;
  gap: number;
  reasons: string[];
}

export interface FbbBacktestReport {
  rules_version: string;
  generated_at: string;
  coverage: { from: string; to: string; months: number };
  caliber: string;
  group6_labels: Record<FbbGroup6, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "S" | "O">;
  /** key = 五点 + "S级" + "all" + "miss" */
  summary: Record<string, FbbStats>;
  group6_summary: Record<string, FbbStats>;
  matrix18: FbbMatrixCell[];
  matrix18_yearly: FbbMatrixYearly[];
  ref_rows: FbbRefRow[];
  yin_split: FbbSplitRow[];
  pit_split: FbbSplitRow[];
  yearly: Record<string, ({ year: string } & FbbStats)[]>;
  monthly: Record<string, ({ month: string } & FbbStats)[]>;
  curves: Record<string, { date: string; cum_pct: number }[]>;
  yearly_totals: FbbYearlyTotal[];
  anchors: Record<string, FbbAnchorStats>;
  anchor_tolerances: Record<string, number>;
  anchor_check: Record<string, FbbAnchorCheck | string>;
  matrix_anchors: Record<string, FbbAnchorStats>;
  matrix_anchor_check: Record<string, FbbAnchorCheck | string>;
  case_gates: FbbCaseGate[];
  dead_stats: FbbDeadStat[];
  radar: Record<string, { trigger_n: number; hit_n: number }>;
  built_at?: string | null;
}

export interface FbbRebuildStatus {
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

export interface FbbBacktestPayload {
  status: "ok" | "unavailable";
  message?: string;
  is_backtest?: boolean;
  report?: FbbBacktestReport;
  rebuild: FbbRebuildStatus;
}

export interface FbbLedgerTrade {
  vt_symbol: string;
  name: string;
  point: FbbPoint;
  level: "S" | "O" | "—";
  group6: FbbGroup6;
  gap: number;
  n_board: number;
  yin_yang: string;
  entry_price: number | null;
  sealed: boolean;
  /** 反包日起连板数 */
  streak_h: number;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason:
    | "break_day_close" | "next_close_fail" | "break_close" | "max_hold_close"
    | null;
  ret_pct: number | null;
  is_bad: boolean;
  /** 炸板 | 封次日负 | 封次日正 */
  result: string;
  break_drop_pct: number | null;
  break_yin_count: number;
  pit_depth_pct: number | null;
  last_entity: string | null;
  last_open_pct: number | null;
  /** S2 顶格开(>7%)高方差警示 */
  high_var: boolean | null;
  dist_ma5: number | null;
  /** 首触板15分钟K周期末刻; null=无分钟数据(2024-08前) */
  touch: string | null;
}

export interface FbbLedgerDay {
  trade_date: string;
  count: number;
  win: number;
  bad: number;
  avg_ret_pct: number | null;
  trades: FbbLedgerTrade[];
}

export interface FbbLedgerMonth {
  month: string;
  count: number;
  bad: number;
  win_rate: number | null;
  avg_ret_pct: number | null;
  total_ret_pct: number;
}

export interface FbbLedgerPayload {
  status: "ok" | "unavailable";
  is_backtest?: boolean;
  coverage?: FbbBacktestReport["coverage"];
  caliber?: string;
  month?: string | null;
  months?: FbbLedgerMonth[];
  ledger_days: FbbLedgerDay[];
}

export interface FbbRuleItem {
  no: number;
  rule: string;
  evidence: string;
}

export interface FbbRuleGroup {
  group: "pool" | FbbPoint | "dead" | "buy" | "sell";
  title: string;
  items: FbbRuleItem[];
}

export interface FbbRulesPayload {
  rules_version: string;
  group6_labels: Record<FbbGroup6, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "S" | "O">;
  point_desc: Record<string, string>;
  rules: FbbRuleGroup[];
  falsified_rules: string[];
  risk_notes: string[];
  ths_pool_conditions: Record<string, string>;
  ths_pool_note: string;
  intraday_playbook: string[];
  anchors: Record<string, FbbAnchorStats>;
  anchor_tolerances: Record<string, number>;
  matrix_anchors: Record<string, FbbAnchorStats>;
  case_gates: Omit<FbbCaseGate, "actual_points" | "pass">[];
}

export function fetchFbbLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<FbbLivePayload>(`/fanbao/live${query}`);
}

export function fetchFbbLiveDates() {
  return apiClient.get<{ dates: string[] }>("/fanbao/live/dates");
}

export function fetchFbbBacktest() {
  return apiClient.get<FbbBacktestPayload>("/fanbao/backtest");
}

export function rebuildFbbBacktest() {
  return apiClient.post<FbbRebuildStatus>("/fanbao/backtest/rebuild");
}

export function fetchFbbBacktestStatus() {
  return apiClient.get<FbbRebuildStatus>("/fanbao/backtest/status");
}

export function fetchFbbLedger(month?: string) {
  const query = month ? `?month=${encodeURIComponent(month)}` : "";
  return apiClient.get<FbbLedgerPayload>(`/fanbao/ledger${query}`);
}

export function fetchFbbRules() {
  return apiClient.get<FbbRulesPayload>("/fanbao/rules");
}
