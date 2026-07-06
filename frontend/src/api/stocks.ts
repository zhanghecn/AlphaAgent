import { apiClient } from "./client";
import type {
  StockListData,
  StockQuote,
  BarSeriesData,
  StockSnapshot,
  TechnicalIndicators,
  StockBusiness,
  SectorInfo,
} from "./types";

export interface StockListParams {
  q?: string;
  page?: number;
  page_size?: number;
  sort?: string;
  order?: "asc" | "desc";
}

export function fetchStocks(params: StockListParams = {}) {
  const qs = new URLSearchParams();
  if (params.q) qs.set("q", params.q);
  if (params.page) qs.set("page", String(params.page));
  if (params.page_size) qs.set("page_size", String(params.page_size));
  if (params.sort) qs.set("sort", params.sort);
  if (params.order) qs.set("order", params.order);
  const search = qs.toString();
  return apiClient.get<StockListData>(`/stocks${search ? `?${search}` : ""}`);
}

export function fetchStockDetail(vtSymbol: string, date?: string | null) {
  const qs = new URLSearchParams();
  if (date) qs.set("date", date);
  const search = qs.toString();
  return apiClient.get<StockQuote>(
    `/stocks/${encodeURIComponent(vtSymbol)}${search ? `?${search}` : ""}`,
  );
}

export function fetchStockBars(vtSymbol: string, interval = "1d", limit = 120) {
  return apiClient.get<BarSeriesData>(`/stocks/${encodeURIComponent(vtSymbol)}/bars?interval=${interval}&limit=${limit}`);
}

export function fetchStockIndicators(vtSymbol: string, interval = "1d", limit = 120) {
  return apiClient.get<TechnicalIndicators>(
    `/stocks/${encodeURIComponent(vtSymbol)}/indicators?interval=${interval}&limit=${limit}`
  );
}

export function fetchStockBusiness(vtSymbol: string) {
  return apiClient.get<StockBusiness | null>(`/stocks/${encodeURIComponent(vtSymbol)}/business`);
}

export function fetchStockSectors(vtSymbol: string) {
  return apiClient.get<{ items: SectorInfo[]; message?: string; source?: string }>(`/stocks/${encodeURIComponent(vtSymbol)}/sectors`);
}

export function fetchStockIndustryChain(vtSymbol: string) {
  return apiClient.get<Record<string, unknown> | null>(`/stocks/${encodeURIComponent(vtSymbol)}/industry-chain`);
}

export function fetchStockSnapshot(vtSymbol: string, date?: string | null) {
  const qs = new URLSearchParams();
  if (date) qs.set("date", date);
  const search = qs.toString();
  return apiClient.get<StockSnapshot>(
    `/stocks/${encodeURIComponent(vtSymbol)}/snapshot${search ? `?${search}` : ""}`,
  );
}

// ── 龙头身份 (leader-identity) ────────────────────────────────────────
// 该股在所属「行业」概念里的综合分排名（市值+成交额+20日涨幅加权）。
// is_leader=true 表示龙一/龙二/龙三，前端用奖牌标识；false 用灰色展示「在大行业排第几」。

export interface LeaderConcept {
  sector_id: string;
  concept: string;
  concept_type: string;
  rank: number;
  total: number;
  score: number;
  is_leader: boolean;
  stock_change_pct: number | null;
}

export interface LeaderIdentity {
  vt_symbol: string;
  has_leader_identity: boolean;
  leader_concepts: LeaderConcept[];
  main_products?: string[];
  business_summary?: string | null;
  data_quality: {
    scanned_concepts?: number;
    skipped_small?: number;
    reason?: string;
  };
}

export function fetchStockLeaderIdentity(vtSymbol: string) {
  return apiClient.get<LeaderIdentity>(
    `/stocks/${encodeURIComponent(vtSymbol)}/leader-identity`,
  );
}
