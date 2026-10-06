import { apiClient } from "./client";

// ── 高位接力打板(二接三/三接四)产品线 API 契约 ──
// 策略口径 = hpr-v4.4 打板口诀卡七条(量化因子研究/高位接力/打板口诀卡.md,2026-09-28合体定稿)。
// 买点 = 昨日恰好2/3连板,链区间(前几板开盘%+换手窗)命中且今天开盘在口诀窗内,
// 触涨停价即打(低吸类低开直接买);开盘≥9.5%顶格不命中(正常开盘口径)。
// 池 = 昨日2/3连板全量(雷达),七条 v6.0(A=阳B=阴C=中性,字母语义跨板位统一):
// A1双平贴零/A2一字转强/A3高开低吸(三接四阳) B1强开系/B2捡尸/B3贴零温开(三接四阴)
// C1冒泡转弱(二接三,阴阳都打)/C2四板换手+C3一字换手(三接四不分阴阳,v6.11拆分)。

export type HprPoint =
  | "A1" | "A2" | "B1" | "B2" | "C1"
  | "A3" | "B3" | "C2" | "C3" | "—";   // v6.0:A=阳/B=阴/C=中性(字母跨板位统一,E退休);v6.11:C3一字换手拆自C2
export type HprWeakPoint = "K2" | "K4" | "K5" | "K9" | "K3";   // 弱市组(v7.0;v7.7 K7退役)
export type HprAnyPoint = HprPoint | HprWeakPoint;   // 动态口诀组:点位可能是两组任一编号
export type HprGroup4 = "二接三阴" | "二接三阳" | "三接四阴" | "三接四阳";
export type HprDynGroup = "weak" | "strong" | "both";

export type HprStatus =
  | "watching" | "sealed_watch" | "entered" | "holding" | "pending_exit" | "closed"
  | "skipped_auction" | "skipped_gap" | "late_touch" | "no_trigger";

export interface HprLiveEntry {
  vt_symbol: string;
  name: string | null;
  group4: HprGroup4;
  n_board: number | null;
  point: HprAnyPoint;
  level: "A" | "B" | "—";
  actionable: boolean;
  avoid_static: string | null;
  auction_gate: "a2_0_9.5" | "b2_4_7" | null;
  /** 出手条件人话(今天开多少+怎么买;多分支链重叠票为条件表;point="—"为 null) */
  action_hint: string | null;
  /** 出手今开窗列表(全部候选分支窗;无窗为空数组) */
  today_window: [number, number][];
  /** 弱市组候选(v7.1 动态口诀组):K系链级命中,当前组=weak/both 才出手 */
  weak_point: HprWeakPoint | "—";
  weak_label: string | null;
  weak_hint: string | null;
  weak_windows: [number, number][];
  b3_turn: number | null;
  /** 动态组标注(v7.1,后端 get_live 下发):strong/weak_active=该组当前启用且命中;
   *  active=出手资格(启用组任一命中);paused_label=命中但所属组未启用(灰显) */
  strong_active?: boolean;
  weak_active?: boolean;
  active?: boolean;
  paused_label?: string | null;
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
  /** 当前启用口诀组(v7.1:出手资格按组过滤;asof=数据截止月) */
  dyn_group: { group: HprDynGroup; asof: string | null; label: string } | null;
  counts: {
    pool: number;
    actionable: number;
    /** 当前组出手数(启用组命中;未启用组命中只展示) */
    active?: number;
    signals: number;
    by_group: Record<string, number>;
    by_point: Record<string, number>;
    by_weak_point?: Record<string, number>;
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
  /** v7.2 弱市时代段(2020-22)K系分条成绩,含 all 合计——回测卡主数字 */
  weak_era_by_point?: Record<string, HprStats>;
  /** v7.2 弱市时代段(2020-22)分年成绩 */
  weak_era_yearly?: ({ year: string } & HprStats)[];
  /** v7.3 动态组实盘口径(按月自动切换启用组)分年成绩 */
  dyn_sim_yearly?: ({ year: string } & HprStats)[];
  /** v7.4 动态组实盘口径的一年的成绩(2020起七年,含复利/相加列) */
  dyn_sim_totals?: HprYearlyTotal[];
  /** v7.3 两组全开对照(14条都打,全时段)分年成绩 */
  dyn_open_yearly?: ({ year: string } & HprStats)[];
  /** v7.5 动态组实盘口径分条分年(key=出手编号;月度另含 all=全部出手) */
  dyn_point_yearly?: Record<string, ({ year: string } & HprStats)[]>;
  dyn_point_monthly?: Record<string, ({ month: string } & HprStats)[]>;
  dyn_point_totals?: Record<string, HprStats>;
  /** v7.5 未启用时代参考层(全量命中)——实盘无成交的格子灰字显示 */
  ref_point_yearly?: Record<string, ({ year: string } & HprStats)[]>;
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
  /** v7.3 动态组交割单含 K 系出手点(当月弱市组启用的成交笔) */
  point: HprPoint | HprWeakPoint;
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
  /** 同票持仓重叠(v6.1):前笔 E3 未退真实买不进,行保留展示但不进收益汇总 */
  overlap?: boolean;
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
  no: number | string;   // 机制组=数字序号;口诀卡组=方案点编号(A1/C2…)
  rule: string;
  evidence: string;
}

export interface HprRuleGroup {
  group: "pool" | "A" | "B" | "C" | "E" | HprPoint | "avoid" | "time" | "buy" | "sell";
  title: string;
  items: HprRuleItem[];
}

// 速查表行(后端 contracts.CHEAT_ROWS/WEAK_CHEAT_ROWS 单一事实源;多分支口诀拆子项一行支)
export interface HprCheatRow {
  no: HprAnyPoint;
  sub?: string;      // 子项名(A1 低开等强开/B1 转温/C2 二板一字…;单分支口诀无)
  name: string;      // 行名=子项全名(A1 双平贴零·低开等强开)
  yang: string;      // 组=阴阳+板位(阳·打3板)
  b1: string;
  b2: string;
  b3: string;
  today: string;
  ground?: string;   // 地基腿条件(姿态/前10日/锚点/先手小阳;主人2026-10-05定名ground)
  stat: string;      // 成绩(E3口径)
}

export interface HprRulesPayload {
  rules_version: string;
  group4_labels: Record<HprGroup4, string>;
  point_labels: Record<string, string>;
  point_levels: Record<string, "A" | "B">;
  point_desc: Record<string, string>;
  point_names: Record<string, string>;   // A1→双平贴零(纯口诀名,规则页卡片标题用)
  point_psycho: Record<string, string>;  // A1→主力心理解读(规则页口诀卡用)
  point_stats: Record<string, string>;   // A1→"16笔·胜69%·均+12.0"成绩速览(E3口径)
  point_boards: Record<string, string>;  // A1→"打3板"板位归属
  rules: HprRuleGroup[];
  cheat_rows: HprCheatRow[];             // 速查表(规则页主表;答题讲解卡取命中行)
  weak_cheat_rows: HprCheatRow[];        // 弱市组K系速查表(v7.2 起规则页并列渲染)
  weak_point_boards: Record<string, string>;  // K2→打4板(K系板位归属)
  falsified_rules: string[];
  risk_notes: string[];
  ths_pool_conditions: Record<string, string>;
  ths_pool_note: string;
  intraday_playbook: string[];
  anchors: Record<string, HprAnchorStats>;
  anchor_tolerances: Record<string, number>;
  case_gates: Omit<HprCaseGate, "actual_points" | "pass">[];
  pose_cases?: import("@/features/highRelay/PoseCaseChart").HprPoseCase[]; // 地基姿态案例K线窗(v6.10,随物化出)
}

export function fetchHprLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<HprLivePayload>(`/high-relay/live${query}`);
}

// ── 动态口诀组(v7.0:「近一年哪组口诀赚得多就用哪组」,规则页「获取最新口诀」) ──
export interface HprKoujueGroupStats {
  n: number;
  avg: number | null;
  win: number | null;
  label: string;                     // 弱市组/强市组
  rows: (HprCheatRow & { dyn_stat: string })[];   // 速查表行+近12月动态成绩(多分支仅首行)
}

export interface HprKoujueCurrent {
  status: "ok" | "unavailable";
  rules_version: string;
  window_months: number;
  asof: string;                      // 数据截止月(YYYY-MM)
  current_group: "weak" | "strong" | "both";
  groups: { weak: HprKoujueGroupStats; strong: HprKoujueGroupStats };
  current_rows: (HprCheatRow & { dyn_stat: string })[];
  switch_history: { month: string; from: string; to: string }[];
  caliber: string;
  reason?: string;
}

export function fetchHprKoujueCurrent() {
  return apiClient.get<HprKoujueCurrent>("/high-relay/koujue/current");
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
  years?: { year: string; months: HprQuizMonthSummary[]; dyn_states?: string[] }[];
}

export interface HprQuizDisplay {
  board_label: string;          // 打3板/打4板
  b1_open: number | null;       // 一板开盘%
  b2_open: number | null;       // 二板开盘%
  b3_open: number | null;       // 三板开盘%(三接四)
  b2_turn: number | null;       // 二板换手率
  b3_turn: number | null;       // 三板换手率(三接四)
  pre20_pct: number | null;     // 首板前20日涨幅(半山腰判定)
  pre10_pct: number | null;     // 首板前10日涨幅(A2近端透支判定)
  foundation_chg: number | null; // 地基日涨幅%(判定同源单源下发,q32;C2「涨1~3%×三板<7」腿)
  foundation_pose: string | null; // 地基K线姿态(v6.10弱票腿B2/B3判定:站线上/骑线/贴线/掉线下)
  foundation_ma20: number | null; // 地基日收盘距20日线%(v6.10起仅参考)
  anchor_pos: number | null;      // 地基日收盘距前期涨停高点%(v6.8 C2锚点腿:贴着-2~0/超5%不碰)
  auction_pct: number;          // 今开%(决策日竞价)
  prev_close: number;
  limit_price: number | null;   // 涨停价(打板买入价)
  decision_open: number;        // 决策日开盘价(今开十字bar用)
  day_high_pct: number;         // 决策日盘中最高涨幅%(第二决策信息:冲到9%快触板才决定打不打)
  chain: string | null;         // 板型链 实体→一字
  // 弱市组题判定格(v7.1,仅2020-22题下发;题面可判原则):K4一板换手腿/
  // K5前波命根/K3距新高贴顶腿
  b1_turn?: number | null;
  prev_wave60?: number | null;
  dist_h60?: number | null;
}

export interface HprQuizAnswer {
  point: HprAnyPoint;           // —=不该买;2020-22题=K系编号(弱市组),2023+题=强市组编号
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
  scheme_name: string;          // 子项全名(A1 双平贴零·低开等强开;q31与规则页速查表统一)
  scheme_row: HprCheatRow | null; // 速查表命中行(表格化讲解;地基/一板/二板/三板/今天开/地基日/成绩)
  matched_line: string;         // 本票数据对照行
  fail_fields?: string[];       // 命中=空数组(红格仅 miss 题用)
  row_fails?: string[];         // 速查表红列键(q34;hit 恒空)
}

export interface HprQuizExplainMiss {
  kind: "miss";
  trap_kind?: "yin_yang" | "near" | "toxic" | "plain";  // 陷阱类型(q10起,综合挑战卷抽题用)
  reasons: string[];            // 为什么不该买(1~3条)
  fail_fields?: string[];       // 不符合的腿对应的题面格子标签(q32:前端判分后红格标出)
  scheme_row?: HprCheatRow | null; // 最接近口诀的速查表行(q34「错误的口诀也给出表格」;链形不沾边=null)
  row_fails?: string[];         // 速查表红列键(yang/b1/b2/b3/today/ground;q34;反串题只标组列)
}

export interface HprQuizQuestion {
  seq: number;                  // 月内题号(匿名题干用)
  vt_symbol: string;
  name: string;
  decision_date: string;
  /** v7.3 该题所属月的动态组状态(weak/strong/both):判组按月滚动无未来函数;
   *  旧物化缺省时前端按日期兜底切分 */
  dyn_state?: "weak" | "strong" | "both";
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

// 综合挑战卷(主人定 2026-09-28):六条口诀每条随机2道好票+21道陷阱差票
// (阴阳反串/形态接近/毒段三等分,差:好=1:1~3:1),每次调用重抽、全卷乱序;
// year 指定=只在该年抽(按年份练市场环境,单年池不足的口诀有多少抽多少);
// 结构与月题一致(month 缺省),进度与月题共享(同一题 key)。
export function fetchHprQuizMixed(scope?: { year?: string; years?: string[]; era?: "weak" | "strong" }) {
  const params = new URLSearchParams();
  const yearParam = scope?.years?.length ? scope.years.join(",") : scope?.year;
  if (yearParam) params.set("year", yearParam);
  if (scope?.era) params.set("era", scope.era);
  const query = params.size > 0 ? `?${params.toString()}` : "";
  return apiClient.get<HprQuizQuestionsPayload>(`/high-relay/quiz/mixed${query}`);
}
