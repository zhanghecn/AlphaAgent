// ── API Response Wrapper ──

export interface ApiError {
  code: string;
  message: string;
  detail: Record<string, unknown>;
}

export interface ApiResponse<T> {
  success: boolean;
  data: T | null;
  error: ApiError | null;
  request_id: string;
}

// ── Market / Index ──

export interface IndexQuote {
  symbol: string;
  exchange: string;
  vt_symbol: string;
  name: string;
  last_price: number | null;
  change: number | null;
  change_pct: number | null;
  turnover: number | null;
  source: string;
}

export interface MarketOverview {
  trade_date: string;
  indices: IndexQuote[];
  active_stocks: StockQuote[];
  market_state: "RISK_ON" | "RISK_OFF" | "RANGE" | "UNKNOWN";
  source: string;
  updated_at: string;
}

// ── Stock ──

export interface StockQuote {
  symbol: string;
  exchange: string;
  vt_symbol: string;
  board?: string | null;
  board_label?: string | null;
  name: string;
  last_price: number | null;
  change: number | null;
  change_pct: number | null;
  open_price: number | null;
  high_price: number | null;
  low_price: number | null;
  previous_close: number | null;
  volume: number | null;
  turnover: number | null;
  market_cap: number | null;
  pe: number | null;
  pb: number | null;
  turnover_rate: number | null;
  volume_ratio: number | null;
  return_5d?: number | null;
  return_10d?: number | null;
  return_20d?: number | null;
  industry: string | null;
  area: string | null;
  trade_time: string | null;
  source: string;
  price_source?: "daily_bar" | "intraday_snapshot" | string | null;
}

export interface StockListData {
  items: StockQuote[];
  page: number;
  page_size: number;
  total: number | null;
  source: string;
  data_origin?: "local_db" | "live_api" | string;
  storage_table?: string | null;
  fallback_used?: boolean;
  coverage?: Record<string, unknown>;
  updated_at?: string;
}

export interface Bar {
  trade_date: string;
  open: number;
  close: number;
  high: number;
  low: number;
  volume: number;
  turnover: number | null;
  change_pct: number | null;
}

export interface BarSeriesData {
  symbol?: string;
  exchange?: string;
  vt_symbol?: string;
  interval?: string;
  items: Bar[];
  source?: string;
  data_origin?: "local_db" | "live_api" | string;
  storage_table?: string | null;
  fallback_used?: boolean;
  coverage?: Record<string, unknown>;
  updated_at?: string;
}

export interface TechnicalIndicators {
  vt_symbol: string;
  status: "ready" | "insufficient_data" | "pending";
  source?: string | null;
  sample_size?: number;
  latest_close?: number | null;
  latest_change_pct?: number | null;
  temporary_bar?: boolean;
  temporary_bar_date?: string | null;
  moving_average?: {
    ma5?: number | null;
    ma10?: number | null;
    ma20?: number | null;
    ma60?: number | null;
  };
  volume_average?: {
    volume_ma5?: number | null;
    volume_ma10?: number | null;
    volume_ma20?: number | null;
  };
  period_return?: {
    return_20d?: number | null;
    return_60d?: number | null;
  };
  volatility?: {
    volatility_20d?: number | null;
    volatility_60d?: number | null;
  };
  drawdown?: {
    max_drawdown_60d?: number | null;
  };
  bollinger?: {
    mid?: number | null;
    upper?: number | null;
    lower?: number | null;
    width?: number | null;
  };
  macd?: {
    dif?: number | null;
    dea?: number | null;
    macd?: number | null;
  };
  kdj?: {
    k?: number | null;
    d?: number | null;
    j?: number | null;
  };
  rsi?: {
    rsi6?: number | null;
    rsi12?: number | null;
    rsi24?: number | null;
  };
  price_position?: {
    above_ma20?: boolean | null;
    above_ma60?: boolean | null;
    boll_percent_b?: number | null;
  };
  message?: string;
}

export interface BusinessSegment {
  name: string | null;
  revenue: number | null;
  revenue_ratio: number | null;
  gross_profit: number | null;
  gross_profit_ratio: number | null;
  profit_ratio: number | null;
  rank: number | null;
  report_date: string | null;
}

export interface StockBusiness {
  vt_symbol: string;
  summary: string | null;
  business_scope?: string | null;
  main_products: string[];
  segments?: BusinessSegment[];
  report_date?: string | null;
  source: string;
  message?: string;
  company?: {
    full_name?: string | null;
    industry?: string | null;
    market?: string | null;
    website?: string | null;
    address?: string | null;
    employees?: number | null;
  };
}

export interface StockSnapshot {
  quote: StockQuote;
  bars?: Bar[];
  technical_indicators?: TechnicalIndicators;
  business?: StockBusiness;
  sectors?: SectorInfo[];
  data_quality: {
    missing: string[];
  };
}

// ── Sectors / Industry Chains ──

export interface SectorInfo {
  id: string;
  name: string;
  type: string;
  path?: string[];
  source?: string;
  confirmed?: boolean;
  confirmation?: string;
  is_precise?: boolean | null;
  rank?: number | null;
  matched_keywords?: string[];
  count?: number | null;
  stock_count?: number | null;
  change_pct?: number | null;
  market_cap?: number | null;
  rise_count?: number | null;
  fall_count?: number | null;
  leader_stock?: string | null;
}

export interface SectorTrend {
  sector_id: string;
  trend_state: "STRONG_UP" | "UP" | "RANGE" | "DOWN" | "STRONG_DOWN" | "UNKNOWN";
  sample_size: number;
  rise_count: number;
  flat_count: number;
  fall_count: number;
  rise_ratio: number | null;
  fall_ratio: number | null;
  avg_change_pct: number | null;
  turnover_weighted_change_pct: number | null;
  market_cap_weighted_change_pct: number | null;
  turnover: number | null;
  limit_up_count: number;
  limit_down_count: number;
  top_gainers: StockQuote[];
  top_losers: StockQuote[];
  source?: string;
  data_origin?: "local_db" | "live_api" | string;
  storage_table?: string | null;
  fallback_used?: boolean;
  coverage?: Record<string, unknown>;
  updated_at?: string;
}

export interface IndustryChainInfo {
  id: string;
  name: string;
  keywords?: string[];
  upstream: string[];
  midstream: string[];
  downstream: string[];
  segments?: IndustryChainSegment[];
  related_sectors?: SectorInfo[];
  stocks?: string[];
}

export interface IndustryChainSegment {
  stage: "source" | "bridge" | "sink";
  label: string;
  items?: string[];
  nodes?: IndustryChainNode[];
  related_sectors?: SectorInfo[];
  stock_count?: number;
  turnover?: number | null;
  turnover_ratio?: number | null;
  market_cap?: number | null;
  avg_change_pct?: number | null;
  representative_stocks?: ChainStock[];
}

export interface IndustryChainNode {
  id: string;
  name: string;
  stage: "source" | "bridge" | "sink";
  stage_label?: string;
  matched_sectors?: SectorInfo[];
  sector_count?: number;
  weight?: number | null;
}

export interface IndustryChainEdge {
  source: string;
  target: string;
}

export interface ChainStock extends StockQuote {
  related_sector_id?: string;
  related_sector_name?: string;
}

export interface IndustryChainMap {
  chain_id: string;
  name: string | null;
  keywords?: string[];
  related_sectors: SectorInfo[];
  focus_stocks?: ChainStock[];
  segments: IndustryChainSegment[];
  nodes: IndustryChainNode[];
  edges: IndustryChainEdge[];
  stage_exposure: {
    stage: "source" | "bridge" | "sink";
    label: string;
    stock_count: number;
    sector_count: number;
    turnover: number | null;
    market_cap: number | null;
    avg_change_pct: number | null;
    turnover_ratio: number | null;
  }[];
  exposure_basis?: string;
  status?: string;
  source?: string;
  data_origin?: "local_db" | "live_api" | string;
  storage_table?: string | null;
  fallback_used?: boolean;
  coverage?: Record<string, unknown>;
  updated_at?: string;
}

export interface SectorRelationGraphNode {
  id: string;
  name: string;
  type: string;
  path?: string[];
  matched_keywords?: string[];
  stock_count?: number | null;
  loaded_stock_count: number;
  change_pct?: number | null;
  avg_change_pct: number | null;
  rise_ratio: number | null;
  turnover: number | null;
  market_cap: number | null;
  rise_count?: number | null;
  fall_count?: number | null;
  leader_stock?: string | null;
  leader_change_pct?: number | null;
  representative_stocks?: ChainStock[];
  source?: string;
}

export interface SectorRelationGraphEdge {
  source: string;
  target: string;
  source_name: string;
  target_name: string;
  score: number;
  shared_stock_count: number;
  shared_stock_ratio: number;
  jaccard: number;
  name_similarity: number;
  co_movement: number;
  reasons: string[];
  shared_stocks: ChainStock[];
  evidence_level?: "strong" | "weak";
}

export interface SectorRelationGraphCluster {
  name: string;
  node_ids: string[];
  node_count: number;
  edge_count: number;
  avg_change_pct: number | null;
  turnover: number | null;
}

export interface SectorRelationGraph {
  query: string;
  nodes: SectorRelationGraphNode[];
  edges: SectorRelationGraphEdge[];
  clusters: SectorRelationGraphCluster[];
  central_nodes: {
    id: string;
    name: string;
    type: string;
    degree_score: number;
    avg_change_pct: number | null;
    turnover: number | null;
  }[];
  algorithm: {
    name: string;
    node_basis: string;
    edge_basis: string;
    score_formula: string;
    sample_page_size: number;
    seed_count?: number;
  };
  status: string;
  message?: string;
  error?: {
    type?: string;
  };
  source: string;
  data_origin?: "local_db" | "live_api" | string;
  storage_table?: string | null;
  fallback_used?: boolean;
  coverage?: Record<string, unknown>;
  updated_at: string;
}

export interface SectorSearchResult {
  kind: "sector";
  id: string;
  name: string;
  type: string;
  path?: string[];
  matched?: string[];
  change_pct?: number | null;
  stock_count?: number | null;
  source?: string;
  user_category?: "mainline_watch" | "industry" | "theme" | "style_status" | "region" | string;
  user_category_label?: string;
  user_explain?: string;
  decision_hint?: string;
}

export interface SectorDiscoveryGroup {
  id: "mainline_watch" | "industry" | "theme" | "style_status" | "region" | string;
  title: string;
  description: string;
  items: SectorSearchResult[];
}

export interface SectorSearchData {
  query: string;
  items: SectorSearchResult[];
  total: number;
  sector_status?: string;
  hot_queries?: string[];
  discovery_groups?: SectorDiscoveryGroup[];
  source?: string;
  data_origin?: "local_db" | "live_api" | string;
  storage_table?: string | null;
  fallback_used?: boolean;
  coverage?: Record<string, unknown>;
  updated_at?: string;
}

export interface IndustryChainStocksData {
  chain_id: string;
  name?: string;
  items: ChainStock[];
  related_sectors: SectorInfo[];
  page: number;
  page_size: number;
  total: number | null;
  status?: string;
  source?: string;
}

// ── Data Status ──

export interface DataSourceStatus {
  name: string;
  ok: boolean;
  message: string;
  checked_at?: string;
}

export interface ReadyStatus {
  status: string;
  persistence?: string;
  cache?: string;
  postgres?: string;
  redis?: string;
  storage?: DataSourceStatus[];
  coverage?: SyncCoverage | Record<string, unknown>;
  market_data: DataSourceStatus[];
}

export interface DataStatus {
  ready: ReadyStatus;
  [key: string]: unknown;
}

// ── Data Sync ──

export interface SyncSource {
  id: string;
  name: string;
  kind: string;
  base_url?: string | null;
  enabled: boolean;
  priority: number;
  status: string;
  message?: string | null;
  checked_at?: string | null;
  updated_at?: string | null;
}

export interface SyncJob {
  id: string;
  name: string;
  description: string;
  source_id: string;
  target_table: string;
  enabled: boolean;
  default_params: Record<string, unknown>;
  schedule_cron?: string | null;
  last_status?: string | null;
  last_run_id?: number | null;
  last_started_at?: string | null;
  last_finished_at?: string | null;
  last_message?: string | null;
}

export interface SyncRun {
  id: number;
  job_id: string;
  status: "running" | "succeeded" | "failed" | string;
  params: Record<string, unknown>;
  rows_read: number;
  rows_written: number;
  message?: string | null;
  error_type?: string | null;
  error_detail?: string | null;
  started_at: string;
  finished_at?: string | null;
}

export interface SyncCoverageTable {
  rows: number;
  stocks?: number;
  updated_at?: string | null;
  latest_trade_date?: string | null;
}

export interface SyncCoverage {
  tables: Record<string, SyncCoverageTable>;
  source: string;
  updated_at: string;
}

export interface DataUsageCapability {
  id: string;
  name: string;
  user_value: string;
  used_by: string[];
  local_tables: string[];
  coverage: Record<string, SyncCoverageTable | Record<string, unknown>>;
  status: "ready" | "partial" | "degraded" | string;
  data_origin: "local_db" | "live_api" | string;
  fallback_used: boolean;
  reliability: string;
  live_fallback: string;
}

export interface DataUsage {
  status: "ready" | "partial" | "degraded" | string;
  summary?: {
    ready: number;
    partial: number;
    degraded: number;
    capability_count: number;
  };
  capabilities: DataUsageCapability[];
  coverage?: SyncCoverage | Record<string, unknown>;
  source: string;
  updated_at: string;
  message?: string;
}

export interface ListResult<T> {
  items: T[];
  total: number;
}
