import { apiClient, plainGet } from "./client";
import type { MarketOverview } from "./types";
import type { FundFlowResponse, HotRanksResponse, LimitPoolsData } from "@/types/research";

// ── Market Overview (wrapped response) ──

export function fetchMarketOverview() {
  return apiClient.get<MarketOverview>("/market/overview");
}

// ── Sector Fund Flow Ranking (plain JSON) ──

export function fetchFundFlow(
  sectorType: "concept" | "industry" = "concept",
  topN: number = 20,
): Promise<FundFlowResponse> {
  const qs = new URLSearchParams({
    sector_type: sectorType,
    top_n: String(topN),
  });
  return plainGet<FundFlowResponse>(`/market/fund-flow?${qs.toString()}`);
}

// ── Stock Hot Ranks (plain JSON) ──

export function fetchHotRanks(limit: number = 20): Promise<HotRanksResponse> {
  const qs = new URLSearchParams({ limit: String(limit) });
  return plainGet<HotRanksResponse>(`/market/hot-ranks?${qs.toString()}`);
}

// ── Limit Pools (plain JSON) ──

export function fetchLimitPools(tradeDate?: string): Promise<LimitPoolsData> {
  const qs = new URLSearchParams();
  if (tradeDate) qs.set("trade_date", tradeDate);
  const query = qs.toString();
  return plainGet<LimitPoolsData>(`/market/limit-pools${query ? `?${query}` : ""}`);
}
