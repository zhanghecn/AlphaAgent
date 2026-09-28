import { apiClient } from "./client";

// ── 高位接力打板(二接三/三接四)产品线 API 契约 ──
// 策略口径 = hpr-v4.4 打板口诀卡七条(量化因子研究/高位接力/打板口诀卡.md,2026-09-28合体定稿)。
// 买点 = 昨日恰好2/3连板,链区间(前几板开盘%+换手窗)命中且今天开盘在口诀窗内,
// 触涨停价即打(低吸类低开直接买);开盘≥9.5%顶格不命中(正常开盘口径)。
// 池 = 昨日2/3连板全量(雷达),七条 A1/A2(二接三阳) B1/B2弱开系/B4(二接三阴)
// E1四板便捷(三接四不分阴阳,含一字系3~5档)/E2四板捡漏(低吸+温开两分支)。

export type HprPoint =
  | "A1" | "A2" | "B1" | "B2" | "B4"
  | "E1" | "E2" | "—";   // v4.4 七条:B3/E3 退休(并入弱开系/四板捡漏)
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
  group: "pool" | "A" | "B" | "E" | HprPoint | "avoid" | "time" | "buy" | "sell";
  title: string;
  items: HprRuleItem[];
}

export interface HprRulesPayload {
  rules_version: string;
  group4_labels: Record<HprGroup4, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "A" | "B">;
  point_desc: Record<string, string>;
  point_names: Record<string, string>;   // A1→双平贴零(纯口诀名,规则页卡片标题用)
  point_psycho: Record<string, string>;  // A1→主力心理解读(规则页口诀卡用)
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

// ── 答题训练题库(hpr-quiz):回测事件逐题物化,按月下发,前端本地判分 ──
// 题库随回测重建整表刷新,版本串 hpr-v4.0·qN 进 localStorage key(版本变→旧进度作废)。
// 事件范围含顶格票(今开≥9.5,月内置后,练「顶格不打」);收益=E3卖出纪律口径;K线未复权。

export interface HprQuizBar {
  d: string;  // YYYY-MM-DD
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface HprQuizMonthSummary {
  month: string;
  total: number;
  buy_count: number;     // 命中口诀(该买)题数
  reject_count: number;  // 未命中(该拒)题数
}

export interface HprQuizOverviewPayload {
  status: "ok" | "unavailable";
  rules_version?: string;
  total?: number;
  years?: { year: string; months: HprQuizMonthSummary[] }[];
}

export interface HprQuizDisplay {
  board_label: string;          // 打3板/打4板
  b1_open: number | null;       // 一板开盘%
  b2_open: number | null;       // 二板开盘%
  b3_open: number | null;       // 三板开盘%(三接四)
  b2_turn: number | null;       // 二板换手率
  b3_turn: number | null;       // 三板换手率(三接四)
  pre20_pct: number | null;     // 首板前20日涨幅(半山腰判定)
  auction_pct: number;          // 今开%(决策日竞价)
  prev_close: number;
  limit_price: number | null;   // 涨停价(打板买入价)
  decision_open: number;        // 决策日开盘价(今开十字bar用)
  day_high_pct: number;         // 决策日盘中最高涨幅%(第二决策信息:冲到9%快触板才决定打不打)
  chain: string | null;         // 板型链 实体→一字
}

export interface HprQuizAnswer {
  point: HprPoint;              // —=不该买
  should_buy: boolean;
  ret_pct: number | null;       // E3收益%(判分用)
  buy_price: number | null;
  sealed: boolean;
  hold_days: number | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
}

export interface HprQuizExplainHit {
  kind: "hit";
  scheme_no: string;
  scheme_name: string;          // B1 强转弱
  scheme_desc: string;          // 口诀原文
  psycho: string;               // 主力心理
  today_window: [number, number] | null;
  matched_line: string;         // 本票数据对照行
  case_note: string | null;     // 典型样例(19个具名案例之一时)
  half_mountain: boolean;       // 阳组半山腰注记
}

export interface HprQuizExplainMiss {
  kind: "miss";
  trap_kind?: "yin_yang" | "near" | "toxic" | "plain";  // 陷阱类型(q10起,综合挑战卷抽题用)
  reasons: string[];            // 为什么不该买(1~3条)
}

export interface HprQuizQuestion {
  seq: number;                  // 月内题号(匿名题干用)
  vt_symbol: string;
  name: string;
  decision_date: string;
  n_board: number;
  group4: HprGroup4;
  display: HprQuizDisplay;
  bars_before: HprQuizBar[];    // 截断K线(末根=末板收盘)
  bars_after: HprQuizBar[];     // 揭示K线(首根=决策日全天)
  answer: HprQuizAnswer;
  explain: HprQuizExplainHit | HprQuizExplainMiss;
}

export interface HprQuizQuestionsPayload {
  status: "ok" | "unavailable";
  month?: string;
  rules_version?: string;
  count?: number;
  questions?: HprQuizQuestion[];
}

export function fetchHprQuizOverview() {
  return apiClient.get<HprQuizOverviewPayload>("/high-relay/quiz/overview");
}

export function fetchHprQuizQuestions(month: string) {
  return apiClient.get<HprQuizQuestionsPayload>(
    `/high-relay/quiz/questions?month=${encodeURIComponent(month)}`,
  );
}

// 综合挑战卷(主人定 2026-09-28):七条口诀每条随机2道好票+21道陷阱差票
// (阴阳反串/形态接近/毒段三等分,差:好=1:1~3:1),每次调用重抽、全卷乱序;
// 结构与月题一致(month 缺省),进度与月题共享(同一题 key)。
export function fetchHprQuizMixed() {
  return apiClient.get<HprQuizQuestionsPayload>("/high-relay/quiz/mixed");
}
