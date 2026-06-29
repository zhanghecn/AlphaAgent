import { apiClient } from "./client";

export interface TimelineData {
  dates: string[];
  status: "ready" | "empty" | "unavailable";
  message?: string;
}

export interface SectorRankItem {
  sector_id: string;
  name?: string;
  sector_type?: string;
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
  // delta 模式额外字段
  fund_strength?: number | null;
  volume_ratio?: number | null;
  delta_heat?: number | null;
  delta_fund?: number | null;
  accumulated_main_inflow?: number | null;
  fund_inflow_available?: boolean;
  trend_transition?: string | null;
}

export interface IndexQuote {
  vt_symbol: string;
  name: string;
  close: number | null;
  change_pct: number | null;
  turnover: number | null;
}

export interface SnapshotData {
  mode: "single" | "delta" | "live";
  trade_date?: string;
  base_daily_date?: string | null;
  ranking: SectorRankItem[];
  index: IndexQuote[];
  status: string;
  source?: string;
  temporary_bar?: boolean;
  latest_minute_time?: string | null;
  snapshot_updated_at?: string | null;
  snapshot_trade_time?: string | null;
  message?: string;
}

export interface RelationItem {
  sector_id: string;
  name?: string;
  sector_type?: string;
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

export function fetchLiveMainline(params: { trade_date?: string; sector_type?: string } = {}) {
  const qs = new URLSearchParams();
  if (params.trade_date) qs.set("trade_date", params.trade_date);
  if (params.sector_type) qs.set("sector_type", params.sector_type);
  return apiClient.get<SnapshotData>(`/mainline-replay/live?${qs.toString()}`);
}

export function fetchReplaySnapshot(params: {
  date?: string;
  t1?: string;
  t2?: string;
  sector_type?: string;
}) {
  const qs = new URLSearchParams();
  if (params.date) qs.set("date", params.date);
  if (params.t1) qs.set("t1", params.t1);
  if (params.t2) qs.set("t2", params.t2);
  if (params.sector_type) qs.set("sector_type", params.sector_type);
  return apiClient.get<SnapshotData>(`/mainline-replay/snapshot?${qs.toString()}`);
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
  price_source?: "daily_bar" | "intraday_snapshot" | string | null;
  status: string;
}

export function fetchSectorStocks(
  sectorId: string,
  date: string,
  sortBy: "net_inflow" | "change_pct" | "name" = "net_inflow",
) {
  return apiClient.get<SectorStocksData>(
    `/mainline-replay/sector-stocks?sector_id=${encodeURIComponent(sectorId)}&date=${date}&sort_by=${sortBy}`,
  );
}
