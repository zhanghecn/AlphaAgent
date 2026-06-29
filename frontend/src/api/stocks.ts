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
