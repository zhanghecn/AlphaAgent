/**
 * Type definitions for the Research API (sector ranking, concept cards, etc.)
 *
 * Research endpoints return plain JSON (not the {success, data} wrapper),
 * so these types describe the raw response shapes.
 */

// ── Sector Ranking ──

export interface SectorRankingItem {
  sector_id: string;
  name: string;
  type: "concept" | "industry";
  change_pct: number | null;
  stock_count: number | null;
  rise_count: number | null;
  fall_count: number | null;
  leader_stock: string | null;
  leader_change_pct: number | null;
  market_cap: number | null;
  turnover_rate: number | null;
  main_net_inflow: number | null;
}

export interface SectorRankingResponse {
  items: SectorRankingItem[];
  total: number;
  sort_by: string;
  status: "ready" | "unavailable";
  message?: string;
  updated_at: string;
}

// ── Concept Cards (per-stock) ──

export interface ConceptCard {
  sector_id: string;
  name: string;
  type: "concept" | "industry";
  change_pct: number | null;
  stock_count: number | null;
  rise_count: number | null;
  fall_count: number | null;
  leader_stock: string | null;
  turnover_rate: number | null;
  confirmed: boolean;
}

export interface ShenwanClassification {
  level1?: { name?: string; code?: string };
  level2?: { name?: string; code?: string };
  level3?: { name?: string; code?: string };
}

export interface StockConceptCardsResponse {
  vt_symbol: string;
  name: string;
  cards: ConceptCard[];
  shenwan: ShenwanClassification;
  total_cards: number;
  status: "ready" | "empty";
  updated_at: string;
}

// ── Market Fund Flow ──

export interface FundFlowItem {
  code: string;
  name: string;
  change_pct: number | null;
  main_net_inflow: number | null;
  main_net_inflow_ratio: number | null;
  super_large_net_inflow: number | null;
  large_net_inflow: number | null;
  medium_net_inflow: number | null;
  small_net_inflow: number | null;
}

export interface FundFlowResponse {
  items: FundFlowItem[];
  total: number;
  sector_type: string;
  status: "ready" | "unavailable";
  message?: string;
  updated_at: string;
}

// ── Hot Ranks ──

export interface HotRankItem {
  stock_code: string;
  stock_name: string;
  rank: number;
  popularity?: number;
  change_pct?: number | null;
  latest_price?: number | null;
  [key: string]: unknown;
}

export interface HotRanksResponse {
  items: HotRankItem[];
  total: number;
  status: "ready" | "unavailable";
  message?: string;
  updated_at: string;
}

// ── Limit Pools ──

export interface LimitPoolStock {
  code: string;
  name: string;
  change_pct: number | null;
  latest_price: number | null;
  turnover_rate?: number | null;
  turnover?: number | null;
  limit_amount?: number | null;
  continuous_limit_up_count?: number | null;
  [key: string]: unknown;
}

export interface LimitPoolsData {
  trade_date: string;
  pools: {
    limit_up?: LimitPoolStock[];
    limit_down?: LimitPoolStock[];
    strong?: LimitPoolStock[];
  };
  status: "ready" | "unavailable";
  message?: string;
  updated_at: string;
}
