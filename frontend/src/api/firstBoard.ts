import { apiClient } from "./client";

export interface FirstBoardLeader {
  rank: number;
  vt_symbol: string;
  name: string;
  last_price: number | null;
  limit_price: number | null;
  change_pct: number | null;
  seal_amount: number | null;
  turnover_rate: number | null;
  volume_ratio: number | null;
  first_limit_time: string | null;
  last_limit_time: string | null;
  open_times: number | null;
  seal_to_turnover_ratio: number | null;
}

export interface FirstBoardLivePayload {
  status: "ok" | "unavailable";
  trade_date: string;
  captured_at: string;
  session_stage: "preopen" | "morning" | "lunch" | "afternoon" | "closed";
  source: string;
  data_quality: {
    status: "ready" | "unavailable";
    is_stale: boolean;
    pool_total: number;
    first_board_total: number;
    message?: string;
  };
  leaders: FirstBoardLeader[];
}

export function fetchFirstBoardLive() {
  return apiClient.get<FirstBoardLivePayload>("/first-board/live");
}
