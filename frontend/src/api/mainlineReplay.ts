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
  mode: "single" | "delta";
  ranking: SectorRankItem[];
  index: IndexQuote[];
  status: string;
}

export interface RelationItem {
  sector_id: string;
  name?: string;
  relation_score: number;
  corr?: number | null;
  fund_corr?: number | null;
  overlap: number;
  overlap_count: number;
  reason: string;
}

export interface RelationData {
  target: string;
  target_date?: string;
  items: RelationItem[];
  status: string;
}

export function fetchReplayTimeline() {
  return apiClient.get<TimelineData>("/mainline-replay/timeline");
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
