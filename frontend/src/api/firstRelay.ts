import { apiClient } from "./client";

// ── 低位一接二(首板次日打二板)产品线 API 契约 ──
// 策略口径 = j12-v1.1 竞价确认两分支(量化因子研究/一接二/打板口诀卡-一接二.md)。
// 池 = 昨日恰好1板(孤立首板)全量(雷达);二板开盘即一字的票不进池。
// G1【阴坑满开】出手 = 阴线地基 × 今开7.5~9.5;S1【阳坑半开】观察 = 阳线地基
// × 前10日跌超3% × 今开7.5~8.5;命中也不买 = 贴顶(地基距60高0~10%)力竭。
// 卖出全套沿用 hpr v6.7(炸板当日走/断板日收盘卖/D+2深开竞价卖/一字死封顺延)。

export type J12Point = "G1" | "S1" | "—";
export type J12Level = "A" | "B" | "—";

export interface J12LiveEntry {
  vt_symbol: string;
  name: string | null;
  point: J12Point;
  level: J12Level;
  actionable: boolean;
  avoid_static: string | null;
  auction_gate: string | null;   // "7.5_9.5"/"7.5_8.5"
  action_hint: string | null;
  bonus: string | null;          // 信息层加分: 锁板/深坑/大阴洗透/骑线轻仓
  prev_close: number | null;
  limit_price: number | null;
  foundation_yang: boolean | null;
  foundation_chg: number | null;
  dist_ma20: number | null;
  dist_h60: number | null;
  pre10_pct: number | null;
  b1_type: string | null;
  b1_open: number | null;
  b1_turn: number | null;
  chassis: string | null;        // 纯底盘/孤立板/前波连板
  mkt_lim_tm1: number | null;
  sig_status?: string;
  sig_auction_pct?: number;
  sig_entry_price?: number;
  sig_ret_pct?: number;
}

export interface J12LivePayload {
  status: string;
  trade_date: string;
  stale: boolean;
  session_stage: string;
  rules_version: string;
  counts: {
    pool: number;
    actionable: number;
    signals: number;
    act_G1: number;
    act_S1: number;
  };
  koujue: string;
  mechanism: string;
  entries: J12LiveEntry[];
}

export interface J12Agg {
  n: number;
  win?: number;
  e3?: number;
  med?: number;
  worst?: number;
  seal?: number;
  allpos?: boolean;
  by_year?: Record<string, { n: number; e3: number; win?: number; med?: number; sum_pct?: number }>;
}

export interface J12BacktestReport {
  window: { start: string; main_start: string };
  total: J12Agg;
  main: J12Agg;
  oos: J12Agg;
  by_point: Record<"main" | "oos" | "all", Record<"G1" | "S1", J12Agg>>;
  miss_control: J12Agg;
  poison: { n: number; e3: number | null };
  supply: { months: number; per_month: number };
  yearly_totals: { year: string; n: number; avg_pct: number; win: number; med: number; compound_pct: number; sum_pct: number }[];
  info_layer: Record<string, { n: number; win: number; e3: number }>;
  best: { date: string; name: string; point: string; open: number; e3: number }[];
  worst: { date: string; name: string; point: string; open: number; e3: number }[];
  rules_version: string;
}

export interface J12RulesPayload {
  rules_version: string;
  points: Record<string, { name: string; level: string; desc: string; gate: [number, number]; hint: string }>;
  cheat_rows: { 口诀: string; 条件: string; 级别: string; 六年: string; 月均: string }[];
  rules_text: {
    koujue: string;
    mechanism: string;
    sell: string;
    position: string;
    avoid: string[];
    honest: string;
  };
  main_window: { start: string; note: string };
}

export function fetchFirstRelayLive(date?: string) {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  return apiClient.get<J12LivePayload>(`/first-relay/live${query}`);
}

export function fetchFirstRelayLiveDates() {
  return apiClient.get<{ dates: string[] }>("/first-relay/live/dates");
}

export function fetchFirstRelayBacktest() {
  return apiClient.get<{
    status: string;
    is_backtest?: boolean;
    report?: J12BacktestReport;
    message?: string;
    rebuild?: { running: boolean; latest?: { status?: string; finished_at?: string } | null };
  }>("/first-relay/backtest");
}

export function rebuildFirstRelayBacktest() {
  return apiClient.post<{ status: string; trades: number }>("/first-relay/backtest/rebuild");
}

export function fetchFirstRelayRules() {
  return apiClient.get<J12RulesPayload>("/first-relay/rules");
}
