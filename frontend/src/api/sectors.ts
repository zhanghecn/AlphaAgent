import { apiClient } from "./client";
import type {
  SectorInfo,
  IndustryChainInfo,
  IndustryChainMap,
  StockListData,
  IndustryChainStocksData,
  SectorSearchData,
  SectorTrend,
  SectorRelationGraph,
} from "./types";

export function fetchSectors(type?: string) {
  const qs = type ? `?type=${type}` : "";
  return apiClient.get<{ items: SectorInfo[]; source?: string; type?: string; updated_at?: string }>(`/sectors${qs}`);
}

export function fetchSectorStocks(
  sectorId: string,
  page = 1,
  pageSize = 30,
  withReturns = false,
  q = "",
) {
  const qs = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
    with_returns: String(withReturns),
  });
  if (q.trim()) qs.set("q", q.trim());
  return apiClient.get<StockListData>(
    `/sectors/${encodeURIComponent(sectorId)}/stocks?${qs.toString()}`
  );
}

export function fetchSectorTrend(sectorId: string, pageSize = 100, pages = 3) {
  return apiClient.get<SectorTrend>(
    `/sectors/${encodeURIComponent(sectorId)}/trend?page_size=${pageSize}&pages=${pages}`
  );
}

export function searchSectors(query: string, limit = 20) {
  const qs = new URLSearchParams({ q: query, limit: String(limit) });
  return apiClient.get<SectorSearchData>(`/sectors/search?${qs.toString()}`);
}

export function fetchIndustryChains() {
  return apiClient.get<{ items: IndustryChainInfo[]; source?: string; sector_status?: string }>("/industry-chains");
}

export function fetchSectorRelationGraph(query: string, limit = 12, pageSize = 50) {
  const qs = new URLSearchParams({
    q: query,
    limit: String(limit),
    page_size: String(pageSize),
  });
  return apiClient.get<SectorRelationGraph>(`/industry-chains/graph?${qs.toString()}`);
}

export function fetchIndustryChainMap(chainId: string, pageSize = 20) {
  return apiClient.get<IndustryChainMap>(
    `/industry-chains/${encodeURIComponent(chainId)}/map?page_size=${pageSize}`
  );
}

export function fetchIndustryChainStocks(chainId: string, page = 1, pageSize = 30) {
  return apiClient.get<IndustryChainStocksData>(
    `/industry-chains/${encodeURIComponent(chainId)}/stocks?page=${page}&page_size=${pageSize}`
  );
}
