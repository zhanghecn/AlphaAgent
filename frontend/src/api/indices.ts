import { apiClient } from "./client";
import type { IndexQuote, BarSeriesData, TechnicalIndicators } from "./types";

export function fetchIndices() {
  return apiClient.get<{ items: IndexQuote[] }>("/indices");
}

export function fetchIndexDetail(key: string) {
  return apiClient.get<IndexQuote>(`/indices/${encodeURIComponent(key)}`);
}

export function fetchIndexBars(key: string, interval = "1d", limit = 120) {
  return apiClient.get<BarSeriesData>(`/indices/${encodeURIComponent(key)}/bars?interval=${interval}&limit=${limit}`);
}

export function fetchIndexIndicators(key: string, interval = "1d", limit = 120) {
  return apiClient.get<TechnicalIndicators>(
    `/indices/${encodeURIComponent(key)}/indicators?interval=${interval}&limit=${limit}`
  );
}
