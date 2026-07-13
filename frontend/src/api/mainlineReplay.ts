import { apiClient } from "./client";

export interface TimelineData {
  dates: string[];
  status: "ready" | "empty" | "unavailable";
  message?: string;
}

export interface SectorRankItem {
  sector_id: string;
  name?: string;
  heat_score?: number | null;
  fund_score?: number | null;
  momentum_score?: number | null;
  trend_state?: string | null;
  rank_return?: number | null;
  return_pct?: number | null;
  confidence?: number | null;
  data_mode?: "live" | "history" | string;
  main_net_inflow?: number | null;
  main_net_inflow_ratio?: number | null;
  historical_return_pct?: number | null;
  stock_count?: number | null;
  leader_stock?: string | null;
  leader_change_pct?: number | null;
  score_date?: string | null;
  flow_updated_at?: string | null;
  index_points?: ConceptIndexPoint[];
  index_change_pct?: number | null;
  continuation_status?: "maintained" | "new" | "broken" | "watch" | "hot" | "cold" | string;
  continuation_days?: number;
  activity_days_20?: number;
  activity_ratio_20?: number | null;
  previous_hot?: boolean;
  rolling_board_count?: number;
  rolling_board_dates?: string[];
  rolling_board_avg_change_pct?: number | null;
  // delta 模式额外字段
  fund_strength?: number | null;
  volume_ratio?: number | null;
  delta_heat?: number | null;
  delta_fund?: number | null;
  accumulated_main_inflow?: number | null;
  fund_inflow_available?: boolean;
  trend_transition?: string | null;
}

export interface ConceptIndexPoint {
  date: string;
  close: number | null;
  change_pct?: number | null;
  turnover?: number | null;
  temporary?: boolean;
}

export interface IndexQuote {
  vt_symbol: string;
  name: string;
  close: number | null;
  change_pct: number | null;
  turnover: number | null;
}

export interface FlowTopItem extends Partial<Omit<SectorRankItem, "sector_id" | "name">> {
  sector_id: string;
  name: string;
  net_inflow: number;
}
export interface FlowTop {
  inflows: FlowTopItem[];
  outflows: FlowTopItem[];
  period?: string;
  actual_days?: number | null;
}
export interface SnapshotData {
  mode: "single" | "delta" | "live";
  trade_date?: string;
  base_daily_date?: string | null;
  ranking: SectorRankItem[];
  flow_top?: FlowTop | null;
  index: IndexQuote[];
  status: string;
  source?: string;
  data_state?: "realtime" | "realtime_delayed" | "history_fallback" | string;
  temporary_bar?: boolean;
  latest_minute_time?: string | null;
  realtime_updated_at?: string | null;
  snapshot_updated_at?: string | null;
  snapshot_trade_time?: string | null;
  message?: string;
}

export type SentimentPhase = "ice" | "repair" | "divergence" | "climax" | "ebb" | string;

export interface SentimentCyclePoint {
  date: string;
  score: number;
  score_change?: number | null;
  phase: SentimentPhase;
  phase_label: string;
  total_stocks: number;
  rise_count: number;
  fall_count: number;
  flat_count: number;
  up_ratio?: number | null;
  down_ratio?: number | null;
  limit_up_count: number;
  limit_down_count: number;
  limit_up_rate?: number | null;
  limit_down_rate?: number | null;
  failed_limit_up_count: number;
  failed_limit_up_rate?: number | null;
  max_limit_up_streak: number;
  previous_limit_up_count: number;
  promoted_limit_up_count: number;
  promotion_rate?: number | null;
  temporary?: boolean;
}

export interface SentimentCycleRange {
  label: string;
  days: number;
  start_date: string;
  end_date: string;
  min_score: number;
  max_score: number;
  avg_score: number;
  score_change?: number | null;
  dominant_phase: SentimentPhase;
  dominant_phase_label: string;
}

export interface SentimentCycleData {
  status: "ready" | "empty" | "unavailable" | string;
  mode: "live" | "history" | string;
  trade_date?: string | null;
  base_daily_date?: string | null;
  points: SentimentCyclePoint[];
  ranges: SentimentCycleRange[];
  current?: SentimentCyclePoint | null;
  source?: string;
  temporary_bar?: boolean;
  latest_minute_time?: string | null;
  snapshot_updated_at?: string | null;
  snapshot_trade_time?: string | null;
  limitations?: string[];
  message?: string;
}

export interface RelationItem {
  sector_id: string;
  name?: string;
  relation_score: number;
  corr?: number | null;
  fund_corr?: number | null;
  overlap: number;
  overlap_count: number;
  common_points?: number;
  relation_group?: "industry" | "theme" | "region" | "style_status" | string;
  evidence?: {
    common_points?: number;
    shared_stock_count?: number;
    shared_symbols?: string[];
    jaccard?: number | null;
    price_correlation?: number | null;
    fund_correlation?: number | null;
  };
  reason: string;
}

export interface RelationData {
  target: string;
  target_date?: string;
  items: RelationItem[];
  status: string;
  algorithm?: {
    name?: string;
    window_days?: number;
    basis?: string;
    candidate_basis?: string;
  };
}

export function fetchReplayTimeline() {
  return apiClient.get<TimelineData>("/mainline-replay/timeline");
}

export function fetchLiveMainline(params: { trade_date?: string; flow_period?: string } = {}) {
  const qs = new URLSearchParams();
  if (params.trade_date) qs.set("trade_date", params.trade_date);
  if (params.flow_period) qs.set("flow_period", params.flow_period);
  const query = qs.toString();
  return apiClient.get<SnapshotData>(`/mainline-replay/live${query ? `?${query}` : ""}`);
}

export function fetchReplaySnapshot(params: {
  date?: string;
  t1?: string;
  t2?: string;
  flow_period?: string;
}) {
  const qs = new URLSearchParams();
  if (params.date) qs.set("date", params.date);
  if (params.t1) qs.set("t1", params.t1);
  if (params.t2) qs.set("t2", params.t2);
  if (params.flow_period) qs.set("flow_period", params.flow_period);
  return apiClient.get<SnapshotData>(`/mainline-replay/snapshot?${qs.toString()}`);
}

export function fetchSentimentCycle(params: {
  date?: string;
  lookback?: number;
  include_live?: boolean;
} = {}) {
  const qs = new URLSearchParams();
  if (params.date) qs.set("date", params.date);
  if (params.lookback) qs.set("lookback", String(params.lookback));
  if (params.include_live != null) qs.set("include_live", String(params.include_live));
  const query = qs.toString();
  return apiClient.get<SentimentCycleData>(`/mainline-replay/sentiment-cycle${query ? `?${query}` : ""}`);
}

export interface ConceptSearchData {
  items: FlowTopItem[];
  q: string;
  total: number;
  status: string;
}

export function fetchConceptSearch(params: { q: string; trade_date: string; period?: string }) {
  const qs = new URLSearchParams({ q: params.q, trade_date: params.trade_date });
  if (params.period) qs.set("period", params.period);
  return apiClient.get<ConceptSearchData>(`/mainline-replay/concept-search?${qs.toString()}`);
}

export function fetchReplayRelation(sectorId: string, date: string) {
  return apiClient.get<RelationData>(
    `/mainline-replay/relation?sector_id=${encodeURIComponent(sectorId)}&date=${date}`,
  );
}

export interface SectorStockItem {
  vt_symbol: string;
  name: string;
  close: number | null;
  change_pct: number | null;
  return_5d: number | null;
  limit_up_count_5d: number;
  price_date?: string | null;
  price_source?: "daily_bar" | "intraday_snapshot" | string | null;
  trade_time?: string | null;
  main_net_inflow: number | null;
  main_net_inflow_ratio: number | null;
  fund_inflow_available: boolean;
}

export interface SectorStocksData {
  sector_id: string;
  date: string;
  items: SectorStockItem[];
  total: number;
  fund_flow_available: number;
  filtered_out?: number;
  price_source?: "daily_bar" | "intraday_snapshot" | string | null;
  status: string;
}

export function fetchSectorStocks(
  sectorId: string,
  date: string,
  sortBy: "net_inflow" | "change_pct" | "name" = "change_pct",
  industryFilter: boolean = true,
) {
  return apiClient.get<SectorStocksData>(
    `/mainline-replay/sector-stocks?sector_id=${encodeURIComponent(sectorId)}&date=${date}&sort_by=${sortBy}&industry_filter=${industryFilter}`,
  );
}
