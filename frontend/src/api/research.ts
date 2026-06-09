/**
 * API client for research endpoints.
 *
 * Research endpoints return plain JSON (not the {success, data} wrapper),
 * so we use the shared `plainGet` helper.
 */

import { plainGet } from "./client";
import type {
  SectorRankingResponse,
  StockConceptCardsResponse,
} from "@/types/research";

// ── Sector Ranking ──

export interface SectorRankingParams {
  sector_type?: "concept" | "industry" | "all";
  sort_by?: "change_pct" | "fund_flow" | "stock_count";
  limit?: number;
}

export function fetchSectorRanking(params: SectorRankingParams = {}): Promise<SectorRankingResponse> {
  const qs = new URLSearchParams();
  if (params.sector_type) qs.set("sector_type", params.sector_type);
  if (params.sort_by) qs.set("sort_by", params.sort_by);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  return plainGet<SectorRankingResponse>(`/research/sectors/ranking?${qs.toString()}`);
}

// ── Stock Concept Cards ──

export function fetchConceptCards(vtSymbol: string): Promise<StockConceptCardsResponse> {
  return plainGet<StockConceptCardsResponse>(
    `/research/stocks/${encodeURIComponent(vtSymbol)}/concept-cards`
  );
}
