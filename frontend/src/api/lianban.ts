import { apiClient } from "./client";

// ===== 连板复盘 API（后端 /api/lianban/*，B4 契约）=====
// apiClient.get 自动解包 {success, data}，以下类型均为 data 本体。

// 统计卡
export interface LianbanStats {
  limit_up: number | null;
  limit_up_prev: number | null;
  lianban: number | null;
  lianban_prev: number | null;
  max_streak: number | null;
  max_streak_prev: number | null;
  limit_down: number | null;
  limit_down_prev: number | null;
  seal_rate: number | null;
  seal_rate_prev: number | null;
  broken: number | null;
  broken_prev: number | null;
  prev_lu_avg_change: number | null;
  prev_lu_median_change: number | null;
  prev_lu_rise_ratio: number | null;
  sentiment_phase: string | null;
  sentiment_score: number | null;
  rise_count: number | null;
  fall_count: number | null;
  new_high_63: number | null;
  new_low_63: number | null;
  total_amount: number | null;
  margin_balance: number | null;
  margin_change: number | null;
  margin_date: string | null;
}

// 天梯个股
export interface LadderStock {
  vt_symbol: string;
  name: string;
  limit_up_count: number | null;
  first_limit_time: string | null;
  last_limit_time: string | null;
  limit_amount: number | null;
  break_count: number | null;
  limit_stat_days: number | null;
  limit_stat_boards: number | null;
  is_reverse: boolean | null;
  industry: string | null;
  concepts: string[];
  close_price: number | null;
  change_pct: number | null;
  is_one_word: boolean | null;
  is_st: boolean | null;
  board: string | null;
}

// 天梯档位（按连板数分组）
export interface LadderTier {
  streak: number;
  count: number;
  today_promotion: { base: number; promoted: number; rate: number | null } | null;
  stocks: LadderStock[];
}

export interface LianbanReview {
  trade_date: string;
  mode: "live" | "final" | "rebuild";
  weekday: string;
  indices: { key: string; name: string; vt_symbol: string; change_pct: number | null }[];
  stats: LianbanStats;
  sentiment: Record<string, unknown> | null;
  ladder: {
    trade_date: string;
    source: "pool_archive" | "daily_rebuild" | "live_pool";
    tiers: LadderTier[];
  } | null;
  promotion: {
    trade_date: string;
    lookback_days: number;
    sample_start: string;
    sample_end: string;
    by_streak: { streak: number | string; samples: number; promoted: number; rate: number | null }[];
    first_board_today: { base: number; promoted: number; rate: number | null };
    first_board_mean: number | null;
    relay_5d: { trade_date: string; tiers: Record<string, number> }[];
  } | null;
  relay: {
    tiers: {
      prev_streak: number;
      stocks: {
        vt_symbol: string;
        name: string;
        today_change_pct: number | null;
        status: "promoted" | "broken" | "open";
        today_streak: number | null;
      }[];
    }[];
    first_board: { base: number; promoted: number; rate: number | null; mean: number | null };
  };
  broken_list: {
    vt_symbol: string;
    name: string;
    first_limit_time: string | null;
    break_count: number | null;
    industry: string | null;
  }[];
  themes: {
    name: string;
    count: number;
    leader: { vt_symbol: string; name: string; limit_up_count: number | null } | null;
    stocks: {
      vt_symbol: string;
      name: string;
      limit_up_count: number | null;
      first_limit_time: string | null;
      is_reverse: boolean | null;
    }[];
  }[];
  theme_strength: { name: string; change_pct: number | null }[];
  hot_leaders: {
    as_of: string | null;
    items: {
      rank: number | null;
      vt_symbol: string;
      name: string;
      hot_score: number | null;
      limit_up_count: number | null;
      change_pct: number | null;
      keywords: string[];
    }[];
  };
  data_quality: {
    pool_archived: boolean;
    rebuild_date: string | null;
    missing: string[];
    live?: boolean;
    fallback_from?: string;
  };
}

export interface LianbanDates {
  dates: string[];
  latest: string | null;
}

export function fetchLianbanReview(date?: string) {
  return apiClient.get<LianbanReview>(`/lianban/review${date ? `?date=${date}` : ""}`);
}

export function fetchLianbanDates() {
  return apiClient.get<LianbanDates>("/lianban/dates");
}
