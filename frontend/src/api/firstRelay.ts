import { apiClient } from "./client";

// 一接二 j12-v2.0 综合最终版：F1~F10 任一命中，同票同日去重。
// 入场为开盘非涨停且日线严格突破 +9%；退出为失败板次日尾盘或断板尾盘。

export type J12RulePoint =
  | "F1" | "F2" | "F3" | "F4" | "F5"
  | "F6" | "F7" | "F8" | "F9" | "F10";
export type J12Point = J12RulePoint | "—";
export type J12Level = "A" | "—";

export interface J12LiveEntry {
  vt_symbol: string;
  name: string | null;
  point: J12Point;
  level: J12Level;
  actionable: boolean;
  avoid_static: string | null;
  auction_gate: string | null;
  action_hint: string | null;
  rule_ids: string | null;
  bonus: string | null;
  prev_close: number | null;
  limit_price: number | null;
  trigger_price: number | null;
  foundation_yang: boolean | null;
  foundation_chg: number | null;
  dist_ma20: number | null;
  dist_h60: number | null;
  pre10_pct: number | null;
  b1_type: string | null;
  b1_open: number | null;
  b1_turn: number | null;
  chassis: string | null;
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
    [key: string]: number;
  };
  koujue: string;
  mechanism: string;
  entries: J12LiveEntry[];
}

export interface J12YearAgg {
  n: number;
  e3: number;
  win?: number;
  med?: number;
  sum_pct?: number;
  trim3?: number | null;
}

export interface J12Agg {
  n: number;
  win?: number | null;
  e3?: number | null;
  med?: number | null;
  worst?: number | null;
  seal?: number | null;
  trim3?: number | null;
  allpos?: boolean;
  by_year?: Record<string, J12YearAgg>;
}

export interface J12TailGroup {
  n: number;
  share: number;
  win: number | null;
  e3: number | null;
}

export interface J12BacktestReport {
  window: { start: string; main_start: string };
  total: J12Agg;
  main: J12Agg;
  oos: J12Agg;
  by_point: Record<"main" | "oos" | "all", Record<J12RulePoint, J12Agg>>;
  miss_control: J12Agg;
  poison: { n: number; e3: number | null };
  supply: { months: number; per_month: number };
  yearly_totals: {
    year: string;
    n: number;
    avg_pct: number;
    win: number;
    med: number;
    trim3: number | null;
    compound_pct: number;
    sum_pct: number;
  }[];
  info_layer: Record<string, { n: number; win: number; e3: number }>;
  tail_structure: Record<"all" | "main" | "oos", Record<"未封" | "次日断" | "连板尾", J12TailGroup>>;
  best: { date: string; name: string; point: string; open: number; e3: number }[];
  worst: { date: string; name: string; point: string; open: number; e3: number }[];
  rules_version: string;
}

export interface J12RulesPayload {
  rules_version: string;
  points: Record<J12RulePoint, {
    name: string;
    level: string;
    actionable: boolean;
    desc: string;
    gate: [number, number] | null;
    hint: string;
  }>;
  cheat_rows: { 口诀: string; 条件: string; 级别: string; 六年: string }[];
  rules_text: {
    koujue: string;
    entry: string;
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
