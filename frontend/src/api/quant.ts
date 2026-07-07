import { apiClient, apiUrl } from "./client";

export type StockBoard = "main" | "chinext" | "star" | "bse" | "index" | "unknown" | string;

export interface StockIdentityFields {
  board?: StockBoard;
  board_label?: string | null;
}

export interface QuantStrategyExplainFactor {
  key: string;
  label: string;
  value?: string | number | null;
  tone?: "positive" | "risk" | "context" | string;
}

export interface QuantStrategyExplain {
  strategy_id: string;
  strategy_version?: string | null;
  strategy_name?: string | null;
  candidate_family?: string | null;
  candidate_family_label?: string | null;
  setup_labels?: string[];
  positive_factors?: QuantStrategyExplainFactor[];
  risk_factors?: QuantStrategyExplainFactor[];
  market_context?: QuantStrategyExplainFactor[];
  action?: string | null;
  research_only?: boolean;
  not_used_for_signal_score?: boolean;
}

export interface QuantRecommendation extends StockIdentityFields {
  id?: number;
  rank: number;
  trade_date: string;
  vt_symbol: string;
  name?: string | null;
  strategy_id: string;
  strategy_version: string;
  action: string;
  horizon: string;
  confidence?: number | null;
  total_score?: number | null;
  reason?: Record<string, unknown> | null;
  strategy_explain?: QuantStrategyExplain | null;
  risk_control?: Record<string, unknown> | null;
  signal_label?: string | null;
  signal_role?: string | null;
  key_entry_signal?: boolean | null;
  status?: string;
  expires_at?: string | null;
}

export interface QuantScreenRun {
  status: string;
  strategy_id: string;
  strategy_version: string;
  trade_date?: string;
  latest_complete_trade_date?: string | null;
  trade_date_daily_symbol_count?: number;
  min_complete_daily_symbol_count?: number;
  run_id?: number | null;
  preview_mode?: string | null;
  data_source?: string | null;
  temporary_bar?: boolean;
  base_daily_date?: string | null;
  latest_daily_date?: string | null;
  latest_intraday_date?: string | null;
  snapshot_updated_at?: string | null;
  snapshot_trade_time?: string | null;
  snapshot_price_count?: number;
  intraday_bar_count?: number;
  total?: number;
  recommendation_count?: number;
  included_boards?: string[];
  recommendations: QuantRecommendation[];
  message?: string | null;
  portfolio_sync?: {
    group_id: number;
    group_type: string;
    synced: number;
  } | null;
}

export interface QuantScreenRunRange extends QuantScreenRun {
  start_date?: string;
  end_date?: string;
  total_dates?: number;
  succeeded_count?: number;
  processed_count?: number;
  generated_count?: number;
  skipped_existing_count?: number;
  force_refreshed_count?: number;
  force_refresh?: boolean;
  persist_signal_details?: boolean;
  create_replay?: boolean;
  range_recommendation_count?: number;
  replay_run_id?: number | null;
  replay_run?: {
    status: string;
    replay_run_id?: number | null;
    strategy_id?: string;
    strategy_version?: string;
    start_date?: string;
    end_date?: string;
    metrics?: Record<string, unknown>;
    message?: string | null;
  } | null;
  runs?: Array<{
    trade_date: string;
    status: string;
    run_id?: number | null;
    candidate_count: number;
    recommendation_count: number;
    skipped_existing?: boolean;
    force_refreshed?: boolean;
  }>;
}

export interface QuantResearchRun {
  id: string;
  status: "running" | "succeeded" | "failed" | string;
  strategy_id: string;
  strategy_version?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string | null;
  stage?: "queued" | "screening" | "replay" | "candidate_quality" | string;
  message?: string | null;
  progress_current?: number;
  progress_total?: number;
  progress_pct?: number;
  params?: Record<string, unknown>;
  screen_run?: QuantScreenRunRange | null;
  replay_run?: QuantScreenRunRange["replay_run"] | null;
  replay_run_id?: number | null;
  backtest_id?: number | null;
  backtest?: {
    status?: string;
    backtest_id?: number | null;
    strategy?: string;
    strategy_version?: string;
    start?: string;
    end?: string;
    metrics?: BacktestMetrics;
    message?: string | null;
  } | null;
  candidate_trade_quality?: CandidateTradeQualityReport | null;
  error_type?: string | null;
  error_detail?: string | null;
}

export interface QuantStrategyOption {
  id: string;
  version: string;
  name: string;
  description: string;
  default_min_entry_score?: number;
  entry_action_label?: string;
  watch_action_label?: string;
  failed_rule_labels?: Record<string, string>;
  evidence_labels?: Record<string, string>;
  primary_metric_keys?: string[];
}

export interface SymbolSignalHistoryRow {
  trade_date: string;
  vt_symbol: string;
  total_score: number;
  relative_strength_score: number;
  washout_score: number;
  trend_quality_score: number;
  sector_mainline_score: number;
  financial_improvement_score: number;
  liquidity_score: number;
  risk_score: number;
  entry_signal: boolean;
  raw_entry_signal?: boolean;
  executable_entry_signal?: boolean;
  research_entry_signal?: boolean;
  action?: "BUY" | "WATCH" | string;
  ma5?: number | null;
  ma5_distance_pct?: number | null;
  turnover20?: number | null;
  turnover_estimated_from_volume?: boolean;
  failed_rules: string[];
  failed_rule_count: number;
  signal_label?: string | null;
  signal_role?: string | null;
  key_entry_signal?: boolean | null;
  evidence?: Record<string, unknown>;
}

export interface SymbolMarketLinePoint {
  trade_date: string;
  state: "bull" | "warming" | "range" | "bear" | "unknown" | string;
  phase?: string | null;
  label?: string | null;
  score?: number | null;
  level?: number | null;
  color_role?: string | null;
  notes?: string[];
  not_used_for_signal_score?: boolean;
}

export interface SymbolUnifiedMarker {
  kind: "buy" | "rejected_buy" | "sell" | string;
  label?: string | null;
  trade_date: string;
  price?: number | null;
  score?: number | null;
  return_pct?: number | null;
  max_drawdown_pct?: number | null;
  cluster_size?: number | null;
  cluster_start_date?: string | null;
  cluster_end_date?: string | null;
  failed_rules?: string[];
  raw?: Record<string, unknown>;
}

export interface SymbolUnifiedSegment {
  entry_date: string;
  exit_date: string;
  entry_price?: number | null;
  exit_price?: number | null;
  return_pct?: number | null;
  max_drawdown_pct?: number | null;
  win?: boolean;
}

export interface SymbolUnifiedReview {
  markers: SymbolUnifiedMarker[];
  segments: SymbolUnifiedSegment[];
  summary: {
    trade_count: number;
    win_count: number;
    win_rate_pct?: number | null;
    compound_return_pct?: number | null;
    average_return_pct?: number | null;
    max_drawdown_pct?: number | null;
  };
  method?: string | null;
  not_used_for_signal_score?: boolean;
}

export interface SymbolSignalHistory extends StockIdentityFields {
  status: string;
  vt_symbol: string;
  name?: string | null;
  strategy_id: string;
  strategy_version: string;
  start_date?: string | null;
  end_date?: string | null;
  scored_date_count?: number;
  entry_signal_count: number;
  watch_count?: number;
  entry_signals: SymbolSignalHistoryRow[];
  best_total_score?: SymbolSignalHistoryRow | null;
  best_entry_fit?: SymbolSignalHistoryRow | null;
  near_misses: SymbolSignalHistoryRow[];
  recent: SymbolSignalHistoryRow[];
  market_line?: SymbolMarketLinePoint[];
  unified_review?: SymbolUnifiedReview;
  financial_coverage?: {
    local_report_count: number;
    usable_report_count: number;
    missing_publish_date_count?: number;
    future_publish_date_count?: number;
    latest_publish_date?: string | null;
    latest_usable_publish_date?: string | null;
    latest_usable_report_date?: string | null;
    policy?: string;
  };
  rule?: Record<string, unknown>;
}

export interface SymbolMarketLineSummary extends StockIdentityFields {
  status: string;
  vt_symbol: string;
  name?: string | null;
  strategy_id: string;
  strategy_version: string;
  start_date?: string | null;
  end_date?: string | null;
  market_line: SymbolMarketLinePoint[];
  latest_market_line?: SymbolMarketLinePoint | null;
  market_line_count?: number;
  source?: string | null;
  not_used_for_signal_score?: boolean;
}

export interface SymbolStrategyComparisonItem {
  strategy: QuantStrategyOption;
  status: string;
  strategy_id: string;
  strategy_version?: string;
  scored_date_count: number;
  entry_signal_count: number;
  watch_count: number;
  best_total_score?: SymbolSignalHistoryRow | null;
  best_entry_fit?: SymbolSignalHistoryRow | null;
  entry_signals: SymbolSignalHistoryRow[];
  recent: SymbolSignalHistoryRow[];
  rule?: Record<string, unknown>;
  message?: string | null;
}

export interface SymbolStrategyComparison extends StockIdentityFields {
  status: string;
  vt_symbol: string;
  name?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  financial_coverage?: SymbolSignalHistory["financial_coverage"];
  items: SymbolStrategyComparisonItem[];
}

export interface SymbolDiagnosticsSummary {
  status: string;
  status_label?: string;
  has_entry_signal: boolean;
  entry_signal_count: number;
  strategy_signal_counts?: Array<{
    strategy_id: string;
    strategy_name?: string | null;
    entry_signal_count: number;
    watch_count: number;
    best_signal_date?: string | null;
    best_entry_score?: number | null;
  }>;
  strategies_with_entry_signal?: string[];
  best_signal_date?: string | null;
  selected_signal_date?: string | null;
  has_backtest: boolean;
  backtest_id?: number | null;
  has_trade: boolean;
  trade_count: number;
  buy_trade_count: number;
  sell_trade_count: number;
  has_order: boolean;
  order_count: number;
  rejected_order_count: number;
  has_position: boolean;
  position_day_count: number;
  main_reason?: string | null;
  main_reason_label?: string | null;
  main_reason_source?: string | null;
  main_reason_detail?: string | null;
  candidate_action?: string | null;
  candidate_rank?: number | null;
  candidate_score?: number | null;
  planned_execute_date?: string | null;
  signal_day_cash?: number | null;
  signal_day_market_value?: number | null;
  signal_day_total_equity?: number | null;
  signal_day_position_count?: number | null;
  not_traded_context?: {
    status?: string | null;
    reason?: string | null;
    needs_signal_date?: boolean;
    best_signal_date?: string | null;
    selected_signal_date?: string | null;
    candidate_action?: string | null;
    candidate_rank?: number | null;
    candidate_score?: number | null;
    plan_status?: string | null;
    planned_execute_date?: string | null;
    cash?: number | null;
    market_value?: number | null;
    total_equity?: number | null;
    position_count?: number | null;
  };
  diagnostic_checks?: Array<{
    label: string;
    status: "pass" | "warning" | "fail" | string;
  }>;
  next_action?: string | null;
}

export interface SymbolDiagnostics extends StockIdentityFields {
  status: string;
  vt_symbol: string;
  name?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  strategy_comparison: SymbolStrategyComparison;
  backtest?: {
    backtest_id?: number | null;
    signal_date?: string | null;
    symbol_detail?: BacktestSymbolDetail | null;
    candidate_trace?: BacktestCandidateTrace | null;
  } | null;
  summary: SymbolDiagnosticsSummary;
}

export interface BacktestRun {
  id: number;
  strategy_id: string;
  strategy_version: string;
  start_date: string;
  end_date: string;
  status: string;
  initial_cash: number;
  final_equity?: number | null;
  params?: Record<string, unknown>;
  metrics?: BacktestMetrics | null;
  finished_at?: string | null;
  run_type?: "portfolio" | "symbol" | string;
}

export interface BacktestMetrics {
  initial_cash?: number;
  final_equity?: number;
  total_return_pct?: number;
  annual_return_pct?: number;
  max_drawdown_pct?: number;
  total_trade_rows?: number;
  buy_count?: number;
  sell_count?: number;
  trade_count?: number;
  open_trade_count?: number;
  win_rate?: number;
  profit_factor?: number | null;
  average_win?: number;
  average_loss?: number;
  sharpe?: number | null;
  minute_1430_count?: number;
  daily_close_proxy_count?: number;
  minute_tail_entry_count?: number;
  daily_open_fallback_count?: number;
}

export interface BacktestMethod {
  id: string;
  name: string;
  signal_timing: string;
  execution_timing: string;
  candidate_policy: string;
  universe: string;
  symbols?: string[];
  included_boards?: string[];
  included_board_labels?: string[];
  entry_filter?: {
    min_entry_score?: number;
    strict_entry?: boolean;
    candidate_limit?: number;
  };
  execution?: {
    intraday_entry?: boolean;
    minute_entry_required?: boolean;
    minute_interval?: string;
    tail_entry_window?: string;
    tail_entry_ma5_tolerance_pct?: number;
    execution_model?: string;
  };
}

export interface BacktestTrade extends StockIdentityFields {
  id?: number;
  trade_date: string;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  price: number;
  volume: number;
  amount: number;
  fee: number;
  pnl?: number | null;
  reason?: string | null;
  reason_label?: string | null;
  raw?: Record<string, unknown>;
}

export interface BacktestEquityRow {
  backtest_id?: number;
  trade_date: string;
  cash: number;
  market_value: number;
  total_equity: number;
  drawdown_pct?: number | null;
  position_count: number;
}

export interface BacktestPositionSnapshot extends StockIdentityFields {
  backtest_id?: number;
  trade_date: string;
  vt_symbol: string;
  name?: string | null;
  volume: number;
  cost_price: number;
  close_price?: number | null;
  market_value: number;
  floating_pnl?: number | null;
  floating_pnl_pct?: number | null;
  weight_pct?: number | null;
  entry_date: string;
  holding_days: number;
  highest_price?: number | null;
  raw?: Record<string, unknown>;
}

export interface BacktestEquityResult {
  status: string;
  items: BacktestEquityRow[];
}

export interface BacktestOrderEvent extends StockIdentityFields {
  id?: number;
  backtest_id?: number;
  trade_date: string;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  price?: number | null;
  volume?: number | null;
  status: string;
  reason?: string | null;
  reason_label?: string | null;
  raw?: Record<string, unknown>;
}

export interface BacktestSignalEvent extends StockIdentityFields {
  id?: number;
  backtest_id?: number;
  trade_date: string;
  signal_date: string;
  execute_date: string;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  price?: number | null;
  score?: number | null;
  reason?: string | null;
  reason_label?: string | null;
  linked_order_id?: number | null;
  linked_order_status?: string | null;
  linked_order_reason?: string | null;
  linked_order_reason_label?: string | null;
  plan_status?: string | null;
  plan_status_label?: string | null;
  raw?: Record<string, unknown>;
}

export interface BacktestSignalAmountPreviewRow extends BacktestSignalEvent {
  preview_volume: number;
  preview_amount: number;
  preview_pnl?: number | null;
  preview_budget: number;
}

export interface BacktestSignalEventsResult {
  status: string;
  backtest_id: number;
  run_type?: string;
  items: BacktestSignalEvent[];
  returned_count?: number;
  note?: string | null;
}

export interface BacktestSignalAmountPreviewResult extends Omit<BacktestSignalEventsResult, "items"> {
  capital: number;
  max_positions: number;
  per_trade_budget: number;
  source_count?: number;
  items: BacktestSignalAmountPreviewRow[];
}

export interface BacktestTradesResult {
  status: string;
  backtest_id: number;
  items: BacktestTrade[];
  limit: number;
  offset: number;
  total: number;
  returned_count: number;
  has_more: boolean;
}

export interface BacktestDailyDecisionRow extends BacktestDailyDecisionSummary {
  trade_date: string;
  cash?: number | null;
  market_value?: number | null;
  total_equity?: number | null;
  drawdown_pct?: number | null;
  position_count: number;
  position_snapshot_count: number;
}

export interface BacktestDailyDecisionsResult {
  status: string;
  backtest_id: number;
  start_date?: string;
  end_date?: string;
  items: BacktestDailyDecisionRow[];
  limit: number;
  offset: number;
  total: number;
  returned_count: number;
  has_more: boolean;
  note?: string | null;
}

export interface BacktestDrilldownDateOption {
  trade_date: string;
  cash?: number | null;
  market_value?: number | null;
  total_equity?: number | null;
  drawdown_pct?: number | null;
  position_count: number;
  buy_trade_count: number;
  sell_trade_count: number;
  buy_candidate_count?: number;
  watch_candidate_count?: number;
  buy_signal_count?: number;
  sell_signal_count?: number;
  filled_order_count: number;
  rejected_order_count: number;
  signal_event_count: number;
  position_snapshot_count: number;
}

export interface BacktestDrilldownSymbolOption extends StockIdentityFields {
  vt_symbol: string;
  name?: string | null;
  trade_count: number;
  buy_trade_count: number;
  sell_trade_count: number;
  order_count: number;
  filled_order_count: number;
  rejected_order_count: number;
  signal_event_count: number;
  buy_signal_count: number;
  sell_signal_count: number;
  position_day_count: number;
  first_signal_date?: string | null;
  first_trade_date?: string | null;
  last_trade_date?: string | null;
  status: string;
  status_label: string;
  main_reason?: string | null;
  main_reason_label?: string | null;
}

export interface BacktestDrilldownOptions {
  status: string;
  backtest_id: number;
  run_type?: string;
  start_date?: string;
  end_date?: string;
  dates: BacktestDrilldownDateOption[];
  symbols: BacktestDrilldownSymbolOption[];
  date_count?: number;
  symbol_count?: number;
  note?: string | null;
}

export interface BacktestDayDetail {
  status: string;
  backtest_id: number;
  trade_date: string;
  equity?: BacktestEquityRow | null;
  positions: BacktestPositionSnapshot[];
  trades: BacktestTrade[];
  buy_trades: BacktestTrade[];
  sell_trades: BacktestTrade[];
  orders: BacktestOrderEvent[];
  signals?: BacktestSignalEvent[];
  recommendations?: QuantRecommendation[];
  decision_summary?: BacktestDailyDecisionSummary;
  snapshot_available: boolean;
  note?: string;
}

export interface BacktestDailyDecisionSummary {
  status: string;
  status_label: string;
  buy_candidate_count: number;
  watch_candidate_count: number;
  buy_signal_count: number;
  sell_signal_count: number;
  buy_order_count: number;
  sell_order_count: number;
  filled_order_count: number;
  rejected_order_count: number;
  buy_trade_count: number;
  sell_trade_count: number;
  buy_amount: number;
  sell_cash_in: number;
  realized_pnl: number;
  source_signal_dates?: string[];
  rejected_reasons: Array<{
    reason: string;
    reason_label?: string | null;
    count: number;
  }>;
}

export interface BacktestSymbolDetail extends StockIdentityFields {
  status: string;
  backtest_id: number;
  vt_symbol: string;
  name?: string | null;
  positions: BacktestPositionSnapshot[];
  trades: BacktestTrade[];
  orders: BacktestOrderEvent[];
  closed_trades: BacktestClosedTrade[];
  trade_attribution?: BacktestTradeAttribution[];
  snapshot_available: boolean;
  note?: string;
}

export interface BacktestTradeAttribution extends StockIdentityFields {
  vt_symbol: string;
  name?: string | null;
  status: "closed" | "open" | string;
  entry_date?: string | null;
  exit_date?: string | null;
  entry_price?: number | null;
  exit_price?: number | null;
  volume?: number | null;
  entry_amount?: number | null;
  exit_amount?: number | null;
  fee?: number | null;
  pnl?: number | null;
  return_pct?: number | null;
  holding_days?: number | null;
  exit_reason?: string | null;
  exit_reason_label?: string | null;
  max_floating_pnl?: number | null;
  min_floating_pnl?: number | null;
  max_floating_pnl_pct?: number | null;
  min_floating_pnl_pct?: number | null;
  entry_score?: number | null;
  entry_state?: string | null;
  entry_support_type?: string | null;
  low_suction_days?: number | null;
  low_suction_buildup_score?: number | null;
  low_suction_launch_quality_bucket?: string | null;
  low_suction_launch_quality_label?: string | null;
  low_suction_dragon_state?: string | null;
  low_suction_dragon_label?: string | null;
  low_suction_dragon_conflict?: boolean | null;
  low_suction_dragon_conflict_level?: string | null;
  low_suction_dragon_notes?: string[] | null;
  ma_convergence_pct?: number | null;
  entry_failed_rules?: string[];
  execution_mode?: string | null;
  price_source?: string | null;
  proxy_used?: boolean | null;
  bar_time?: string | null;
}

export interface BacktestTradeAttributionSummary {
  total_count: number;
  closed_count: number;
  open_count: number;
  realized_pnl: number;
  loss_pnl: number;
  win_pnl: number;
  win_rate: number;
  worst_trade_pnl?: number | null;
  best_trade_pnl?: number | null;
  largest_open_drawdown?: number | null;
  largest_open_profit?: number | null;
}

export interface BacktestTradeAttributionResult {
  status: string;
  backtest_id: number;
  start_date?: string;
  end_date?: string;
  items: BacktestTradeAttribution[];
  summary: BacktestTradeAttributionSummary;
  limit: number;
  offset: number;
  total: number;
  returned_count: number;
  has_more: boolean;
  sort: string;
  note?: string | null;
}

export interface BacktestPathDiagnosticRow extends StockIdentityFields {
  vt_symbol: string;
  name?: string | null;
  entry_date?: string | null;
  exit_date?: string | null;
  entry_setup?: string | null;
  entry_score?: number | null;
  return_pct?: number | null;
  mae_pct?: number | null;
  mfe_pct?: number | null;
  early_mae_pct?: number | null;
  early_mfe_pct?: number | null;
  early_return_pct?: number | null;
  early_follow_through_state?: string | null;
  early_follow_through_label?: string | null;
  entry_context_state?: string | null;
  entry_context_label?: string | null;
  entry_context_notes?: string[] | null;
  entry_launch_diagnostic_state?: string | null;
  entry_launch_diagnostic_label?: string | null;
  entry_launch_diagnostic_notes?: string[] | null;
  low_suction_launch_quality_bucket?: string | null;
  low_suction_launch_quality_label?: string | null;
  low_suction_dragon_state?: string | null;
  low_suction_dragon_label?: string | null;
  low_suction_dragon_conflict?: boolean | null;
  low_suction_dragon_conflict_level?: string | null;
  low_suction_dragon_notes?: string[] | null;
  market_mainline_trade_context?: string | null;
  market_mainline_trade_context_label?: string | null;
  market_mainline_trade_context_notes?: string[] | null;
  fund_flow_coverage_state?: string | null;
  fund_flow_coverage_label?: string | null;
  dynamic_market_label?: string | null;
  market_warning_label?: string | null;
  fund_flow_label?: string | null;
  recovery_label?: string | null;
  post_exit_max_return_pct?: number | null;
  sold_before_rebound?: boolean | null;
  exit_reason?: string | null;
}

export interface BacktestPathDiagnosticsResponse {
  status: string;
  backtest_id: number;
  start_date?: string;
  end_date?: string;
  lookahead_days: number;
  items: BacktestPathDiagnosticRow[];
  summary?: Record<string, unknown>;
  limit?: number;
  total?: number;
  returned_count?: number;
  has_more?: boolean;
  note?: string | null;
}

export interface BacktestAuditEvent extends StockIdentityFields {
  event_type: "order" | "trade" | string;
  trade_date: string;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  status?: string;
  reason?: string | null;
  reason_label?: string | null;
  price?: number | null;
  volume?: number | null;
  pnl?: number | null;
  execution_mode?: string | null;
  message?: string;
  raw?: Record<string, unknown>;
}

export interface BacktestAudit {
  status: string;
  backtest_id: number;
  vt_symbol?: string | null;
  strategy_id: string;
  strategy_version: string;
  start_date: string;
  end_date: string;
  method?: BacktestMethod;
  params?: Record<string, unknown>;
  orders: BacktestAuditEvent[];
  trades: BacktestTrade[];
  events: BacktestAuditEvent[];
  order_summary?: BacktestOrderStats;
  note?: string;
}

export interface BacktestCandidateTrace extends StockIdentityFields {
  status: string;
  summary: string;
  backtest_id: number;
  signal_date: string;
  planned_execute_date?: string | null;
  vt_symbol: string;
  name?: string | null;
  strategy_id?: string;
  strategy_version?: string;
  run_type?: string;
  action?: string | null;
  rank?: number | null;
  total_score?: number | null;
  recommendation?: QuantRecommendation | null;
  signals: BacktestSignalEvent[];
  orders: BacktestOrderEvent[];
  trades: BacktestTrade[];
  positions: BacktestPositionSnapshot[];
  equity?: BacktestEquityRow | null;
  linked_order_status?: string | null;
  linked_order_reason?: string | null;
  plan_status?: string | null;
  plan_status_label?: string | null;
  not_planned_context?: BacktestCandidateNotPlannedContext | null;
  diagnostics: Array<{
    id: string;
    status: string;
    message: string;
    failed_rules?: string[];
  }>;
}

export interface BacktestCandidateNotPlannedContext {
  likely_reason?: string | null;
  likely_reason_label?: string | null;
  backtest_start_date?: string | null;
  backtest_end_date?: string | null;
  first_signal_date?: string | null;
  last_signal_date?: string | null;
  signal_event_count?: number | null;
  signal_date_has_plan?: boolean | null;
  signal_date_plan_count?: number | null;
  signal_date_buy_plan_count?: number | null;
  signal_date_sell_plan_count?: number | null;
  candidate_limit?: number | null;
  max_positions?: number | null;
  max_symbols?: number | null;
  included_boards?: string[];
  target_in_universe?: boolean | null;
  target_universe_rank?: number | null;
  recommendation_run_id?: number | null;
  recommendation_rank?: number | null;
  recommendation_action?: string | null;
  recommendation_score?: number | null;
  target_signal_rank?: number | null;
  target_signal_score?: number | null;
  target_signal_setup?: string | null;
  target_exceeds_candidate_limit?: boolean | null;
  persisted_recommendation_count?: number | null;
  persisted_buy_candidate_count?: number | null;
  persisted_watch_candidate_count?: number | null;
  same_day_top_recommendations?: Array<{
    vt_symbol: string;
    name?: string | null;
    rank?: number | null;
    action?: string | null;
    total_score?: number | null;
  }>;
  planned_buy_symbols?: Array<{
    vt_symbol: string;
    name?: string | null;
    trade_date?: string | null;
    execute_date?: string | null;
    score?: number | null;
    reason?: string | null;
    rank?: number | null;
    setup_type?: string | null;
  }>;
  target_symbol?: string | null;
  target_theoretical_held_on_signal_date?: boolean | null;
  target_theoretical_entry_date?: string | null;
  target_real_held_on_signal_date?: boolean | null;
  target_real_entry_date?: string | null;
  signal_snapshot?: {
    source?: string | null;
    run_id?: number | null;
    trade_date?: string | null;
    vt_symbol?: string | null;
    total_score?: number | null;
    raw_entry_signal?: boolean | null;
    executable_entry_signal?: boolean | null;
    action?: string | null;
    failed_rules?: string[];
    signal_label?: string | null;
    signal_role?: string | null;
    entry_setup?: string | null;
    low_suction_days?: number | null;
    low_suction_launch_confirmed?: boolean | null;
    low_suction_launch_quality_bucket?: string | null;
    ma_convergence_pct?: number | null;
    latest_change_pct?: number | null;
    close_location_in_range?: number | null;
  } | null;
}

export interface BacktestClosedTrade extends StockIdentityFields {
  vt_symbol: string;
  name?: string | null;
  entry_date?: string | null;
  exit_date?: string | null;
  entry_price?: number | null;
  exit_price: number;
  volume: number;
  amount: number;
  fee: number;
  pnl: number;
  return_pct?: number | null;
  holding_days?: number | null;
  exit_reason?: string | null;
}

export interface BacktestMonthlyReturn {
  month: string;
  start_date?: string | null;
  end_date?: string | null;
  start_equity: number;
  end_equity: number;
  return_pct: number;
  max_drawdown_pct: number;
}

export interface BacktestSymbolPerformance extends StockIdentityFields {
  vt_symbol: string;
  name?: string | null;
  trade_count: number;
  win_count: number;
  loss_count: number;
  pnl: number;
  amount: number;
  best_trade?: number | null;
  worst_trade?: number | null;
  win_rate: number;
  return_pct?: number | null;
}

export interface BacktestExtendedMetrics {
  total_trade_rows: number;
  buy_count: number;
  sell_count: number;
  closed_trade_count: number;
  open_trade_count: number;
  average_holding_days: number;
  median_holding_days: number;
  turnover_pct?: number | null;
  traded_amount: number;
  average_exposure_pct: number;
  max_position_count: number;
  rejected_order_count: number;
  strict_tail_rejected_count?: number;
  strict_1430_rejected_count?: number;
  tail_entry_rejected_count?: number;
  tail_exit_rejected_count?: number;
  minute_gap_rejected_count?: number;
  limit_up_blocked_buy_count?: number;
  limit_down_blocked_sell_count?: number;
  filled_order_count: number;
  execution_modes?: Record<string, number>;
}

export interface BacktestExecutionQuality {
  status: "pass" | "warning" | string;
  buy_count: number;
  strict_tail_attempt_count?: number;
  strict_tail_rejected_count?: number;
  strict_tail_rejected_ratio?: number | null;
  strict_1430_attempt_count?: number;
  strict_1430_rejected_count?: number;
  strict_1430_rejected_ratio?: number | null;
  tail_entry_rejected_count?: number;
  tail_exit_rejected_count?: number;
  minute_gap_rejected_count?: number;
  minute_1430_count?: number;
  daily_close_proxy_count?: number;
  legacy_open_fallback_count?: number;
  limit_up_blocked_buy_count?: number;
  limit_down_blocked_sell_count?: number;
  minute_tail_entry_count?: number;
  daily_open_fallback_count?: number;
  minute_1430_ratio?: number | null;
  daily_close_proxy_ratio?: number | null;
  minute_tail_entry_ratio?: number | null;
  daily_open_fallback_ratio?: number | null;
  minute_bar_count: number;
  daily_bar_count: number;
  financial_report_count: number;
  diagnostics: BacktestRobustnessDiagnostic[];
}

export interface BacktestOrderStats {
  total: number;
  by_status: Record<string, number>;
  by_reason: Record<string, number>;
  rejected_examples: Array<StockIdentityFields & {
    trade_date: string;
    vt_symbol: string;
    name?: string | null;
    side: string;
    price?: number | null;
    volume?: number | null;
    status: string;
    reason?: string | null;
  }>;
}

export interface BacktestDataQuality {
  [tableName: string]: { count: number; [metric: string]: number | string | null | undefined } | string[] | undefined;
  limitations?: string[];
}

export interface BacktestBenchmarkItem {
  id: string;
  name: string;
  status: "ready" | "missing" | "empty" | string;
  start_date?: string;
  end_date?: string;
  days?: number;
  return_pct?: number | null;
  max_drawdown_pct?: number | null;
  strategy_return_pct?: number | null;
  excess_return_pct?: number | null;
  final_nav?: number | null;
  reason?: string;
  source?: string | null;
}

export interface BacktestPeriodRow {
  id: string;
  label: string;
  start_date: string;
  end_date: string;
  days: number;
  start_equity: number;
  end_equity: number;
  return_pct: number;
  max_drawdown_pct: number;
  trade_count: number;
  win_rate: number;
  pnl: number;
  benchmark_return_pct?: number | null;
  excess_return_pct?: number | null;
}

export interface BacktestPeriodAnalysis {
  status: string;
  method?: string;
  note?: string;
  periods: BacktestPeriodRow[];
}

export interface BacktestRegimeRow {
  regime: string;
  label: string;
  window_count: number;
  days: number;
  avg_strategy_return_pct: number;
  avg_benchmark_return_pct: number;
  max_drawdown_pct: number;
  trade_count: number;
  win_count: number;
  win_rate: number;
  pnl: number;
}

export interface BacktestRegimeAnalysis {
  status: string;
  benchmark_id?: string;
  method?: string;
  note?: string;
  periods: BacktestRegimeRow[];
}

export interface BacktestTopCandidateMetricSummary {
  candidate_count: number;
  evaluated_count: number;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  avg_benchmark_return_pct?: number | null;
  avg_excess_return_pct?: number | null;
}

export interface BacktestCandidateObservationMetricSummary {
  candidate_count: number;
  observed_count: number;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  avg_benchmark_return_pct?: number | null;
  avg_excess_return_pct?: number | null;
}

export interface BacktestCandidateObservationMarketBucket extends BacktestCandidateObservationMetricSummary {
  regime: string;
  label: string;
}

export interface BacktestDynamicMarketBucket {
  regime: string;
  label: string;
  candidate_count: number;
  evaluated_count: number;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  avg_excess_return_pct?: number | null;
  avg_market_score?: number | null;
  avg_breadth_score?: number | null;
  avg_risk_score?: number | null;
}

export interface BacktestThemeAlignmentBucket {
  alignment: string;
  label: string;
  candidate_count: number;
  evaluated_count: number;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  avg_excess_return_pct?: number | null;
  avg_market_score?: number | null;
  avg_theme_strength?: number | null;
}

export interface BacktestCandidateObservationSummary extends BacktestCandidateObservationMetricSummary {
  evaluable_count?: number;
  excluding_strong_summary?: BacktestCandidateObservationMetricSummary;
  market_buckets?: BacktestCandidateObservationMarketBucket[];
  dynamic_market_buckets?: BacktestDynamicMarketBucket[];
  theme_alignment_buckets?: BacktestThemeAlignmentBucket[];
  holding_days?: number;
  method?: string;
}

export interface BacktestTopCandidateMarketBucket extends BacktestTopCandidateMetricSummary {
  regime: string;
  label: string;
}

export interface BacktestTopCandidateSummary {
  top_n: number;
  total_count: number;
  evaluated_count: number;
  top_count: number;
  top_evaluated_count: number;
  top_win_rate?: number | null;
  top_avg_return_pct?: number | null;
  top_avg_benchmark_return_pct?: number | null;
  top_avg_excess_return_pct?: number | null;
  other_count: number;
  other_evaluated_count: number;
  other_win_rate?: number | null;
  other_avg_return_pct?: number | null;
  other_avg_benchmark_return_pct?: number | null;
  other_avg_excess_return_pct?: number | null;
  market_buckets: BacktestTopCandidateMarketBucket[];
  top_strong_summary?: BacktestTopCandidateMetricSummary;
  top_excluding_strong_summary?: BacktestTopCandidateMetricSummary;
  top_strong_candidate_share?: number | null;
  benchmark_sources?: Array<{ source: string; count: number }>;
  dynamic_market_sources?: Array<{ source: string; count: number }>;
  candidate_observation?: BacktestCandidateObservationSummary;
  dynamic_market_buckets?: BacktestDynamicMarketBucket[];
  theme_alignment_buckets?: BacktestThemeAlignmentBucket[];
}

export interface BacktestTopCandidateAuditItem extends StockIdentityFields {
  signal_date?: string | null;
  rank?: number | null;
  vt_symbol: string;
  name?: string | null;
  score?: number | null;
  entry_date?: string | null;
  exit_date?: string | null;
  return_pct?: number | null;
  benchmark_return_pct?: number | null;
  benchmark_source?: string | null;
  excess_return_pct?: number | null;
  market_regime?: string | null;
  evaluated?: boolean;
  dynamic_market_source?: string | null;
  observation_entry_date?: string | null;
  observation_exit_date?: string | null;
  observation_entry_price?: number | null;
  observation_exit_price?: number | null;
  observation_return_pct?: number | null;
  observation_excess_return_pct?: number | null;
  observation_status?: string | null;
  dynamic_market_regime?: string | null;
  dynamic_market_label?: string | null;
  dominant_theme?: string | null;
  dominant_theme_id?: string | null;
  theme_state?: string | null;
  market_score?: number | null;
  market_breadth_score?: number | null;
  market_risk_score?: number | null;
  theme_strength?: number | null;
  stock_theme_alignment?: string | null;
}

export interface BacktestTopCandidateAudit {
  status: string;
  backtest_id: number;
  top_n: number;
  summary: BacktestTopCandidateSummary;
  items?: BacktestTopCandidateAuditItem[];
  note?: string;
  message?: string;
}

export interface FactorAuditBucket {
  bucket: string;
  sample_count: number;
  win_rate?: number | null;
  average_return?: number | null;
  median_return?: number | null;
  profit_factor?: number | null;
  mfe_8_pct_hit_ratio?: number | null;
  mae_5_pct_loss_ratio?: number | null;
  failed_launch_ratio?: number | null;
  support_stop_like_ratio?: number | null;
}

export interface CandidateExecutionAttributionRow {
  signal_date?: string | null;
  execute_date?: string | null;
  vt_symbol?: string | null;
  name?: string | null;
  rank?: number | null;
  score?: number | null;
  entry_family?: string | null;
  entry_family_label?: string | null;
  planned?: boolean | null;
  ordered?: boolean | null;
  filled?: boolean | null;
  execution_status?: string | null;
  not_filled_reason?: string | null;
  not_filled_subreason?: string | null;
  not_filled_label?: string | null;
  order_status?: string | null;
  order_reason?: string | null;
  trade_price?: number | null;
  fixed_return_20d?: number | null;
  missed_return_20d?: number | null;
  missed_mfe_20d?: number | null;
  missed_mae_20d?: number | null;
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
}

export interface CandidateExecutionAttributionBucket {
  execution_status?: string | null;
  not_filled_reason?: string | null;
  not_filled_subreason?: string | null;
  sample_count?: number | null;
  filled_count?: number | null;
  missed_count?: number | null;
  positive_20d_count?: number | null;
  win_rate?: number | null;
  average_return_20d?: number | null;
}

export interface CandidateExecutionAttributionSummary {
  method?: string | null;
  max_execution_rank?: number | null;
  candidate_count?: number | null;
  filled_count?: number | null;
  missed_count?: number | null;
  top20_missed_quality?: {
    missed_count?: number | null;
    missed_positive_20d_count?: number | null;
    missed_avg_return_20d?: number | null;
    missed_avg_mfe_20d?: number | null;
    missed_avg_mae_20d?: number | null;
    by_reason?: CandidateExecutionAttributionBucket[];
  };
  by_status?: CandidateExecutionAttributionBucket[];
  by_not_filled_reason?: CandidateExecutionAttributionBucket[];
  by_not_filled_subreason?: CandidateExecutionAttributionBucket[];
  items?: CandidateExecutionAttributionRow[];
}

export interface FactorAuditResponse {
  status: string;
  backtest_id?: number;
  top_limit?: number;
  exclude_strong_market?: boolean;
  summary?: FactorAuditBucket;
  by_setup?: FactorAuditBucket[];
  by_entry_family_conflict?: FactorAuditBucket[];
  by_low_position_reclaim_type?: FactorAuditBucket[];
  by_rank_bucket?: FactorAuditBucket[];
  by_market_regime?: FactorAuditBucket[];
  by_market_warning_level?: FactorAuditBucket[];
  by_fund_flow_state?: FactorAuditBucket[];
  by_factor_bucket?: Record<string, FactorAuditBucket[]>;
  factor_interaction_opportunity_cost?: {
    method?: string | null;
    entry_family_rank?: BacktestPathMetricBucket[];
    entry_family_market?: BacktestPathMetricBucket[];
    launch_quality_market?: BacktestPathMetricBucket[];
    low_suction_days_first_lift?: BacktestPathMetricBucket[];
    reclaim_support_ma?: BacktestPathMetricBucket[];
    risk_market_warning?: BacktestPathMetricBucket[];
    opportunity_cost?: {
      removed_winner_count?: number | null;
      removed_winner_return_sum?: number | null;
      avoided_loser_count?: number | null;
      avoided_loser_return_sum?: number | null;
      added_loser_count?: number | null;
      added_loser_return_sum?: number | null;
      note?: string | null;
    };
    not_used_for_signal_score?: boolean | null;
  };
  candidate_execution_attribution?: CandidateExecutionAttributionSummary;
  success_paths?: unknown[];
  failure_paths?: unknown[];
  coverage?: Record<string, unknown>;
}

export interface CandidateTradeQualityMetricSummary {
  sample_count?: number | null;
  evaluated_count?: number | null;
  win_count?: number | null;
  win_rate?: number | null;
  quality_win_count?: number | null;
  quality_win_rate?: number | null;
  annual_return_pct?: number | null;
  annualized_return_method?: string | null;
  signal_day_compound_annual_return_pct?: number | null;
  average_return_pct?: number | null;
  median_return_pct?: number | null;
  average_max_drawdown_pct?: number | null;
  average_max_runup_pct?: number | null;
  average_holding_days?: number | null;
  d1_limit_up_count?: number | null;
  d1_limit_up_rate?: number | null;
  d1_near_limit_up_count?: number | null;
  d1_near_limit_up_rate?: number | null;
  d1_big_drop_count?: number | null;
  d1_big_drop_rate?: number | null;
  average_d2_close_return_pct?: number | null;
  average_d3_close_return_pct?: number | null;
  average_d2_d3_best_runup_pct?: number | null;
  hold_to_d3_worthwhile_count?: number | null;
  hold_to_d3_worthwhile_rate?: number | null;
  take_profit_next_day_count?: number | null;
  take_profit_next_day_rate?: number | null;
}

export interface CandidateTradeQualityYearlySummary extends CandidateTradeQualityMetricSummary {
  year?: string | null;
  label?: string | null;
}

export interface CandidateTradeQualityBucket extends CandidateTradeQualityMetricSummary {
  label?: string | null;
  rank_limit?: number | null;
  rank_bucket?: string | null;
  daily_rank_window?: string | null;
  score_bucket?: string | null;
  setup_family?: string | null;
  market_phase?: string | null;
  timing_window?: string | null;
  timing_phase?: string | null;
  setup_timing_bucket?: string | null;
  month?: string | null;
  month_timing_window?: string | null;
  month_timing_phase?: string | null;
  setup_month_timing_bucket?: string | null;
  setup_month_timing_phase_bucket?: string | null;
  evaluation_window?: string | null;
  d1_outcome?: string | null;
  exit_reason?: string | null;
  examples?: CandidateTradeQualitySample[];
}

export interface CandidateTradeQualityRankLimitMatrixRow {
  label?: string | null;
  setup_family?: string | null;
  market_phase?: string | null;
  timing_window?: string | null;
  timing_phase?: string | null;
  setup_timing_bucket?: string | null;
  month?: string | null;
  month_timing_window?: string | null;
  month_timing_phase?: string | null;
  setup_month_timing_bucket?: string | null;
  setup_month_timing_phase_bucket?: string | null;
  evaluation_window?: string | null;
  top5?: CandidateTradeQualityMetricSummary;
  top10?: CandidateTradeQualityMetricSummary;
  top20?: CandidateTradeQualityMetricSummary;
}

export interface CandidateTradeQualityDailyExtreme extends StockIdentityFields {
  vt_symbol?: string | null;
  name?: string | null;
  rank?: number | null;
  score?: number | null;
  return_pct?: number | null;
  d1_close_return_pct?: number | null;
  d1_quality_success?: boolean | null;
  d1_near_limit_up?: boolean | null;
  d1_limit_up?: boolean | null;
  d1_big_drop?: boolean | null;
  exit_reason?: string | null;
}

export interface CandidateTradeQualityDailySummary {
  entry_signal_date?: string | null;
  candidate_count?: number | null;
  evaluated_count?: number | null;
  missing_count?: number | null;
  top5?: CandidateTradeQualityMetricSummary;
  top10?: CandidateTradeQualityMetricSummary;
  top20?: CandidateTradeQualityMetricSummary;
  topn?: CandidateTradeQualityMetricSummary;
  best_candidate?: CandidateTradeQualityDailyExtreme | null;
  worst_candidate?: CandidateTradeQualityDailyExtreme | null;
}

export interface CandidateTradeQualityBucketAuditRow extends CandidateTradeQualityMetricSummary {
  bucket?: string | null;
  label?: string | null;
  path_bucket?: string | null;
  examples?: CandidateTradeQualitySample[];
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
}

export interface CandidateTradeQualityBucketAudit {
  status: string;
  method?: string | null;
  entry_selection?: string | null;
  rank_limit?: number | null;
  sample_limit?: number | null;
  summary?: CandidateTradeQualityMetricSummary;
  path_buckets?: CandidateTradeQualityBucketAuditRow[];
  loss_buckets?: CandidateTradeQualityBucketAuditRow[];
  winner_buckets?: CandidateTradeQualityBucketAuditRow[];
  coverage?: Record<string, unknown>;
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
}

export interface CandidateTradeQualityVolumeAuditRow extends CandidateTradeQualityMetricSummary {
  label?: string | null;
  volume_bucket?: string | null;
  active_volume_bucket?: string | null;
  preparation_bucket?: string | null;
  loss_path?: string | null;
  loss_path_label?: string | null;
  preparation_label?: string | null;
  loss_sample_count?: number | null;
  pure_loss_count?: number | null;
  deep_drawdown_loss_count?: number | null;
  mfe_giveback_count?: number | null;
  right_tail_count?: number | null;
  examples?: CandidateTradeQualityVolumeExample[];
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
}

export interface CandidateTradeQualityVolumeExample extends StockIdentityFields {
  vt_symbol?: string | null;
  name?: string | null;
  entry_signal_date?: string | null;
  rank?: number | null;
  score?: number | null;
  return_pct?: number | null;
  max_drawdown_pct?: number | null;
  max_runup_pct?: number | null;
  volume_ratio_5d_20d?: number | null;
  low_suction_days?: number | null;
  first_effective_lift?: boolean | null;
  recent_limit_up_20d?: boolean | null;
  large_bull_count_20d?: number | null;
  volume_stall_risk?: boolean | null;
}

export interface CandidateTradeQualityVolumeAudit {
  status: string;
  method?: string | null;
  entry_selection?: string | null;
  rank_limit?: number | null;
  sample_limit?: number | null;
  summary?: CandidateTradeQualityMetricSummary;
  by_volume_ratio?: CandidateTradeQualityVolumeAuditRow[];
  by_active_volume?: CandidateTradeQualityVolumeAuditRow[];
  by_preparation?: CandidateTradeQualityVolumeAuditRow[];
  loss_by_volume_ratio?: CandidateTradeQualityVolumeAuditRow[];
  loss_by_preparation?: CandidateTradeQualityVolumeAuditRow[];
  loss_path_by_preparation?: CandidateTradeQualityVolumeAuditRow[];
  coverage?: Record<string, unknown>;
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
}

export interface CandidateTradeQualitySample extends StockIdentityFields {
  status: string;
  vt_symbol: string;
  name?: string | null;
  rank?: number | null;
  score?: number | null;
  rank_bucket?: string | null;
  daily_rank_window?: string | null;
  score_bucket?: string | null;
  setup_family?: string | null;
  setup_family_label?: string | null;
  market_phase?: string | null;
  market_phase_label?: string | null;
  timing_window?: string | null;
  timing_window_label?: string | null;
  timing_phase?: string | null;
  timing_phase_label?: string | null;
  setup_timing_bucket?: string | null;
  setup_timing_label?: string | null;
  month_timing_window?: string | null;
  month_timing_window_label?: string | null;
  month_timing_phase?: string | null;
  month_timing_phase_label?: string | null;
  setup_month_timing_bucket?: string | null;
  setup_month_timing_label?: string | null;
  setup_month_timing_phase_bucket?: string | null;
  setup_month_timing_phase_label?: string | null;
  month?: string | null;
  label_model?: string | null;
  entry_model?: string | null;
  entry_signal_date?: string | null;
  entry_execute_date?: string | null;
  entry_price?: number | null;
  tail_entry_date?: string | null;
  tail_entry_price?: number | null;
  d1_trade_date?: string | null;
  d1_open_return_pct?: number | null;
  d1_high_runup_pct?: number | null;
  d1_low_drawdown_pct?: number | null;
  d1_close_return_pct?: number | null;
  d1_quality_success?: boolean | null;
  d1_near_limit_up?: boolean | null;
  d1_limit_up?: boolean | null;
  d1_big_drop?: boolean | null;
  d2_close_return_pct?: number | null;
  d3_close_return_pct?: number | null;
  d2_d3_best_runup_pct?: number | null;
  hold_to_d3_worthwhile?: boolean | null;
  take_profit_next_day?: boolean | null;
  exit_signal_date?: string | null;
  exit_execute_date?: string | null;
  exit_price?: number | null;
  return_pct?: number | null;
  max_drawdown_pct?: number | null;
  max_runup_pct?: number | null;
  holding_days?: number | null;
  exit_reason?: string | null;
  cluster_start_date?: string | null;
  cluster_end_date?: string | null;
  cluster_size?: number | null;
  entry_reason?: Record<string, unknown> | null;
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
}

export interface CandidateTradeQualityReport {
  status: string;
  backtest_id?: number;
  start_date?: string;
  end_date?: string;
  strategy_id?: string;
  strategy_version?: string;
  method?: string | null;
  rank_limit?: number;
  sample_limit?: number;
  summary?: CandidateTradeQualityMetricSummary;
  by_rank_bucket?: CandidateTradeQualityBucket[];
  by_rank_limit?: CandidateTradeQualityBucket[];
  by_daily_rank_window?: CandidateTradeQualityBucket[];
  by_score_bucket?: CandidateTradeQualityBucket[];
  by_setup_family?: CandidateTradeQualityBucket[];
  by_market_phase?: CandidateTradeQualityBucket[];
  by_timing_window?: CandidateTradeQualityBucket[];
  by_timing_phase?: CandidateTradeQualityBucket[];
  by_setup_x_timing?: CandidateTradeQualityBucket[];
  by_month?: CandidateTradeQualityBucket[];
  by_evaluation_window?: CandidateTradeQualityBucket[];
  by_setup_family_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_market_phase_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_timing_window_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_timing_phase_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_setup_x_timing_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_month_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_month_timing_window_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_month_timing_phase_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_setup_month_timing_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_setup_month_timing_phase_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_evaluation_window_rank_limit?: CandidateTradeQualityRankLimitMatrixRow[];
  by_d1_outcome?: CandidateTradeQualityBucket[];
  by_exit_reason?: CandidateTradeQualityBucket[];
  bucket_audit?: CandidateTradeQualityBucketAudit;
  volume_audit?: CandidateTradeQualityVolumeAudit;
  yearly?: CandidateTradeQualityYearlySummary[];
  daily_summaries?: CandidateTradeQualityDailySummary[];
  best_samples?: CandidateTradeQualitySample[];
  worst_samples?: CandidateTradeQualitySample[];
  items?: CandidateTradeQualitySample[];
  coverage?: Record<string, unknown>;
  cache?: Record<string, unknown>;
  uses_future_for_label_only?: boolean | null;
  not_used_for_signal_score?: boolean | null;
  note?: string | null;
  message?: string | null;
}

export interface BacktestPerformanceAttributionRunSummary {
  id: number;
  strategy_id?: string | null;
  strategy_version?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  initial_cash?: number | null;
  final_equity?: number | null;
  total_return_pct?: number | null;
  max_drawdown_pct?: number | null;
  win_rate?: number | null;
  profit_factor?: number | null;
  buy_count?: number | null;
  sell_count?: number | null;
  open_trade_count?: number | null;
  average_win?: number | null;
  average_loss?: number | null;
  trade_summary?: BacktestPerformanceTradeSummary;
  params?: Record<string, unknown>;
}

export interface BacktestPerformanceTradeSummary {
  trade_count?: number | null;
  win_count?: number | null;
  loss_count?: number | null;
  win_rate?: number | null;
  average_win?: number | null;
  average_loss?: number | null;
  gross_win?: number | null;
  gross_loss?: number | null;
  profit_factor?: number | null;
  net_pnl?: number | null;
}

export interface BacktestPerformanceExitReasonRow {
  exit_reason?: string | null;
  exit_reason_label?: string | null;
  current?: BacktestPerformanceTradeSummary;
  reference?: BacktestPerformanceTradeSummary;
  delta?: BacktestPerformanceTradeSummary;
}

export interface BacktestPerformanceTradeDelta {
  vt_symbol?: string | null;
  trade_date?: string | null;
  current_reason?: string | null;
  current_pnl?: number | null;
  reference_reason?: string | null;
  reference_pnl?: number | null;
  delta_pnl?: number | null;
}

export interface BacktestPerformanceAttributionReport {
  status: string;
  backtest_id?: number;
  reference_backtest_id?: number | null;
  current?: BacktestPerformanceAttributionRunSummary;
  reference?: BacktestPerformanceAttributionRunSummary;
  delta?: BacktestPerformanceTradeSummary & {
    total_return_pct?: number | null;
    max_drawdown_pct?: number | null;
    buy_count?: number | null;
    sell_count?: number | null;
  };
  constraint_comparison?: {
    same_max_positions?: boolean | null;
    same_candidate_limit?: boolean | null;
    same_position_sizing?: boolean | null;
    same_core_portfolio_params?: boolean | null;
    core_params?: Array<{ key: string; current?: unknown; reference?: unknown; same?: boolean | null }>;
  };
  signal_schema?: {
    current_required_version?: string | null;
    same_schema_lineage?: boolean | null;
    current?: Record<string, unknown>;
    reference?: Record<string, unknown>;
  };
  by_exit_reason?: BacktestPerformanceExitReasonRow[];
  monthly?: Array<{
    month: string;
    current_return_pct?: number | null;
    reference_return_pct?: number | null;
    delta_return_pct?: number | null;
  }>;
  trade_deltas?: {
    largest_negative?: BacktestPerformanceTradeDelta[];
    largest_positive?: BacktestPerformanceTradeDelta[];
    missing_reference_winners?: BacktestPerformanceTradeDelta[];
    added_current_losers?: BacktestPerformanceTradeDelta[];
  };
  interpretation?: {
    notes?: string[];
    next_tests?: string[];
  };
  note?: string | null;
  message?: string | null;
}

export interface BacktestPathMetricBucket {
  label?: string | null;
  trade_count?: number | null;
  evaluated_count?: number | null;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  median_return_pct?: number | null;
  total_return_pct?: number | null;
  avg_mfe_pct?: number | null;
  avg_mae_pct?: number | null;
  sold_before_rebound_count?: number | null;
  [key: string]: unknown;
}

export interface BuySellProblemMatrix {
  by_problem?: BacktestPathMetricBucket[];
  by_setup_problem?: BacktestPathMetricBucket[];
  by_market_problem?: BacktestPathMetricBucket[];
  focused_symbols?: BacktestPathDiagnosticRow[];
}

export interface MarketContextValidationSummary {
  method?: string | null;
  by_market_regime?: BacktestPathMetricBucket[];
  by_market_warning_level?: BacktestPathMetricBucket[];
  by_market_recovery_level?: BacktestPathMetricBucket[];
  by_fund_flow_state?: BacktestPathMetricBucket[];
  by_market_mainline_trade_context?: BacktestPathMetricBucket[];
  excluding_strong_market?: BacktestPathMetricBucket;
  fund_flow_coverage?: {
    by_coverage?: BacktestPathMetricBucket[];
    insufficient_data_count?: number | null;
  };
  not_used_for_signal_score?: boolean | null;
}

export interface BacktestSetupMarketExitAuditResponse {
  status: string;
  backtest_id?: number;
  start_date?: string;
  end_date?: string;
  lookahead_days?: number;
  summary?: {
    buy_sell_problem_matrix?: BuySellProblemMatrix;
    market_context_validation?: MarketContextValidationSummary;
    [key: string]: unknown;
  };
  items?: BacktestPathDiagnosticRow[];
  total?: number;
  returned_count?: number;
  has_more?: boolean;
  note?: string | null;
}

export interface PhaseStrategyFamilyMatrixRow {
  market_phase?: string | null;
  phase_label?: string | null;
  setup_family?: string | null;
  setup_label?: string | null;
  trade_count?: number | null;
  candidate_count?: number | null;
  evaluated_count?: number | null;
  win_count?: number | null;
  loss_count?: number | null;
  win_rate?: number | null;
  avg_return_pct?: number | null;
  median_return_pct?: number | null;
  total_return_pct?: number | null;
  total_pnl?: number | null;
  avg_pnl?: number | null;
  worst_return_pct?: number | null;
  best_return_pct?: number | null;
  support_stop_count?: number | null;
  mfe_8_pct_hit_ratio?: number | null;
  mae_5_pct_loss_ratio?: number | null;
}

export interface PhaseStrategyFamilyCandidateMatrix {
  rank_limit: number;
  candidate_count: number;
  by_phase?: PhaseStrategyFamilyMatrixRow[];
  by_phase_setup?: PhaseStrategyFamilyMatrixRow[];
  by_setup?: PhaseStrategyFamilyMatrixRow[];
}

export interface BacktestPhaseStrategyFamilyMatrix {
  status: string;
  backtest_id?: number;
  start_date?: string;
  end_date?: string;
  candidate_rank_limits?: number[];
  summary?: {
    method?: string | null;
    real_trade_matrix?: PhaseStrategyFamilyMatrixRow[];
    real_trade_by_phase?: PhaseStrategyFamilyMatrixRow[];
    real_trade_by_setup?: PhaseStrategyFamilyMatrixRow[];
    candidate_rank_limits?: number[];
    candidate_rank_matrices?: PhaseStrategyFamilyCandidateMatrix[];
    coverage?: {
      trade_count?: number | null;
      candidate_count?: number | null;
      candidate_max_rank_loaded?: number | null;
    };
    interpretation?: {
      low_suction_buildup_observation_only?: boolean | null;
      overlap_requires_conflict_resolution?: boolean | null;
      market_phase_not_raw_score_bonus?: boolean | null;
      notes?: string[];
    };
    audit_only?: boolean | null;
    not_used_for_signal_score?: boolean | null;
  };
  note?: string | null;
}

export interface FactorCandidateResponse {
  status: string;
  backtest_id?: number;
  items: Array<Record<string, unknown>>;
  coverage?: Record<string, unknown>;
}

export interface StrategyTimelineEvent {
  date: string;
  vt_symbol: string;
  candidate?: Record<string, unknown>;
  plan?: Record<string, unknown>;
  execution?: Record<string, unknown>;
  sell?: Record<string, unknown>;
  cluster?: Record<string, unknown>;
  markers?: string[];
  display_markers?: Array<"BUY_SIGNAL" | "BUY_REJECTED" | "BUY_FILLED" | "SELL_FILLED" | string>;
}

export interface StrategyLifecycleSegment {
  vt_symbol?: string | null;
  cluster_start_date?: string | null;
  cluster_end_date?: string | null;
  key_signal_date?: string | null;
  cluster_type?: string | null;
  buildup_days?: number | null;
  support_hold_days?: number | null;
  first_effective_lift?: boolean | null;
  launch_confirmed?: boolean | null;
  launch_quality_bucket?: string | null;
  key_signal_rank?: number | null;
  key_signal_score?: number | null;
  key_signal_action?: string | null;
}

export interface StrategyTimelineResponse {
  status: string;
  backtest_id: number;
  vt_symbol: string;
  items: StrategyTimelineEvent[];
  lifecycle_segments?: StrategyLifecycleSegment[];
  coverage?: Record<string, unknown>;
}

export interface BacktestCostStressRow {
  id: string;
  label: string;
  extra_bps: number;
  extra_stamp_tax_bps: number;
  extra_cost: number;
  final_equity: number;
  total_return_pct: number;
  return_delta_pct: number;
}

export interface BacktestRobustnessDiagnostic {
  id: string;
  label: string;
  status: "pass" | "fail" | "warning" | string;
  value?: number | null;
  value_type?: "pct" | "count" | string;
  message: string;
}

export interface BacktestRandomBaseline {
  status: string;
  method?: string;
  seed_base?: number;
  run_count?: number;
  sample_size?: number;
  return_avg_pct?: number | null;
  return_median_pct?: number | null;
  return_min_pct?: number | null;
  return_max_pct?: number | null;
  max_drawdown_avg_pct?: number | null;
}

export interface BacktestRobustnessChecks {
  status: string;
  yearly_periods: BacktestPeriodRow[];
  market_regime_periods?: BacktestRegimeRow[];
  market_regime_analysis?: BacktestRegimeAnalysis;
  cost_stress: BacktestCostStressRow[];
  random_baseline: BacktestRandomBaseline;
  diagnostics: BacktestRobustnessDiagnostic[];
  limitations: string[];
}

export interface BacktestDataAsOfAudit {
  status: string;
  policy?: string;
  diagnostics: BacktestRobustnessDiagnostic[];
}

export interface BacktestValidationGridRow {
  variant_id: number;
  is_base_params: boolean;
  min_entry_score: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  strict_entry: boolean;
  final_equity?: number | null;
  total_return_pct?: number | null;
  annual_return_pct?: number | null;
  max_drawdown_pct?: number | null;
  trade_count?: number | null;
  win_rate?: number | null;
  profit_factor?: number | null;
  sharpe?: number | null;
  in_sample_return_pct?: number | null;
  out_sample_return_pct?: number | null;
  out_sample_excess_pct?: number | null;
  sample_equal_weight_return_pct?: number | null;
  sample_equal_weight_excess_pct?: number | null;
  high_friction_return_pct?: number | null;
}

export interface BacktestValidationGridSummary {
  variant_count: number;
  positive_count: number;
  positive_ratio?: number | null;
  out_sample_positive_count: number;
  out_sample_positive_ratio?: number | null;
  sample_excess_positive_count: number;
  sample_excess_positive_ratio?: number | null;
  high_friction_positive_count: number;
  high_friction_positive_ratio?: number | null;
  return_avg_pct?: number | null;
  return_median_pct?: number | null;
  return_min_pct?: number | null;
  return_max_pct?: number | null;
  out_sample_return_median_pct?: number | null;
  base_variant_id?: number | null;
  base_total_return_pct?: number | null;
  base_out_sample_return_pct?: number | null;
  base_total_rank?: number | null;
  base_out_sample_rank?: number | null;
  best_total_variant_id?: number | null;
  best_out_sample_variant_id?: number | null;
}

export interface BacktestWalkForwardFold {
  id: string;
  train_start_date: string;
  train_end_date: string;
  test_start_date: string;
  test_end_date: string;
  train_days: number;
  test_days: number;
  selected_variant_id: number;
  min_entry_score: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  strict_entry: boolean;
  train_return_pct?: number | null;
  train_excess_return_pct?: number | null;
  train_max_drawdown_pct?: number | null;
  train_trade_count: number;
  test_return_pct?: number | null;
  test_benchmark_return_pct?: number | null;
  test_excess_return_pct?: number | null;
  test_max_drawdown_pct?: number | null;
  test_trade_count: number;
  test_win_rate: number;
  test_pnl: number;
}

export interface BacktestWalkForwardSummary {
  fold_count: number;
  positive_test_count: number;
  positive_test_ratio?: number | null;
  excess_positive_count: number;
  excess_positive_ratio?: number | null;
  test_return_avg_pct?: number | null;
  test_return_median_pct?: number | null;
  test_return_min_pct?: number | null;
  test_return_max_pct?: number | null;
  test_excess_avg_pct?: number | null;
  most_selected_variant_id?: number | null;
  selected_variant_counts: Record<string, number>;
}

export interface BacktestWalkForward {
  status: string;
  method?: string;
  train_days?: number;
  test_days?: number;
  step_days?: number;
  folds: BacktestWalkForwardFold[];
  summary?: BacktestWalkForwardSummary;
  diagnostics: BacktestRobustnessDiagnostic[];
  limitations?: string[];
}

export interface BacktestValidationGrid {
  status: string;
  backtest_id: number;
  strategy: string;
  strategy_version: string;
  start_date: string;
  end_date: string;
  method: string;
  variant_count: number;
  param_space: Record<string, unknown[]>;
  base_params: Record<string, unknown>;
  summary: BacktestValidationGridSummary;
  diagnostics: BacktestRobustnessDiagnostic[];
  walk_forward?: BacktestWalkForward;
  top_variants: BacktestValidationGridRow[];
  rows: BacktestValidationGridRow[];
  limitations: string[];
}

export interface BacktestExecutionModelComparisonRow {
  execution_model: "tail_close_hybrid" | "strict_1430" | string;
  label: string;
  status: string;
  message?: string | null;
  final_equity?: number | null;
  total_return_pct?: number | null;
  max_drawdown_pct?: number | null;
  trade_count?: number | null;
  total_trade_rows?: number | null;
  buy_count?: number | null;
  minute_1430_count?: number | null;
  daily_close_proxy_count?: number | null;
  minute_1430_ratio?: number | null;
  daily_close_proxy_ratio?: number | null;
  strict_1430_rejected_count?: number | null;
  tail_entry_rejected_count?: number | null;
  minute_gap_rejected_count?: number | null;
}

export interface BacktestExecutionModelComparison {
  status: string;
  backtest_id: number;
  base_execution_model?: string;
  start_date?: string | null;
  end_date?: string | null;
  strategy?: string;
  rows: BacktestExecutionModelComparisonRow[];
  summary?: {
    status: string;
    return_delta_pct?: number | null;
    message?: string;
  };
  note?: string;
}

export interface BacktestStrategyComparisonRow {
  strategy_id: string;
  strategy_version?: string | null;
  strategy_name?: string | null;
  status: string;
  message?: string | null;
  quality_status?: string | null;
  quality_label?: string | null;
  quality_warning?: string | null;
  final_equity?: number | null;
  total_return_pct?: number | null;
  max_drawdown_pct?: number | null;
  trade_count?: number | null;
  total_trade_rows?: number | null;
  buy_count?: number | null;
  sell_count?: number | null;
  buy_signal_count?: number | null;
  watch_count?: number | null;
  rejected_order_count?: number | null;
  strict_1430_rejected_count?: number | null;
  tail_entry_rejected_count?: number | null;
  minute_gap_rejected_count?: number | null;
  minute_1430_count?: number | null;
  daily_close_proxy_count?: number | null;
  minute_1430_ratio?: number | null;
  daily_close_proxy_ratio?: number | null;
  phase_summary?: BacktestStrategyPhaseSummary;
  phase_rank_hint?: {
    best_phase?: string | null;
    best_phase_label?: string | null;
    best_avg_return_pct?: number | null;
    weak_phase_count?: number | null;
    note?: string | null;
  } | null;
  candidate_phase_summary?: BacktestStrategyCandidatePhaseSummary;
}

export interface BacktestStrategyPhaseBucket {
  phase: string;
  label?: string | null;
  trade_count: number;
  evaluated_count?: number | null;
  win_count?: number | null;
  loss_count?: number | null;
  win_rate_pct?: number | null;
  avg_return_pct?: number | null;
  total_return_pct?: number | null;
  worst_return_pct?: number | null;
  best_return_pct?: number | null;
  support_stop_count?: number | null;
}

export interface BacktestStrategyPhaseSummary {
  status: string;
  trade_count: number;
  by_phase: BacktestStrategyPhaseBucket[];
  best_phase?: string | null;
  best_phase_label?: string | null;
  not_used_for_signal_score?: boolean;
  method?: string | null;
}

export interface BacktestStrategyCandidatePhaseBucket {
  phase: string;
  label?: string | null;
  signal_count: number;
  evaluated_count?: number | null;
  open_count?: number | null;
  not_triggered_count?: number | null;
  win_count?: number | null;
  loss_count?: number | null;
  win_rate_pct?: number | null;
  avg_return_pct?: number | null;
  total_return_pct?: number | null;
  worst_return_pct?: number | null;
  best_return_pct?: number | null;
  support_stop_count?: number | null;
}

export interface BacktestStrategyCandidatePhaseSummary {
  status: string;
  top_limit: number;
  signal_count: number;
  evaluated_count?: number | null;
  open_count?: number | null;
  not_triggered_count?: number | null;
  by_phase: BacktestStrategyCandidatePhaseBucket[];
  best_phase?: string | null;
  best_phase_label?: string | null;
  not_used_for_signal_score?: boolean;
  method?: string | null;
}

export interface BacktestStrategyComparison {
  status: string;
  params?: Record<string, unknown>;
  rows: BacktestStrategyComparisonRow[];
  summary?: {
    status: string;
    strategy_count?: number;
    ready_count?: number;
    best_strategy_id?: string | null;
    best_total_return_pct?: number | null;
    best_verifiable_strategy_id?: string | null;
    best_verifiable_total_return_pct?: number | null;
    complete_strict_count?: number;
    message?: string;
  };
  note?: string;
  message?: string;
}

export interface BacktestMinuteCoverage {
  status: "ready" | "mixed_proxy" | "missing_snapshots" | "strategy_not_triggered" | "empty" | "unavailable" | "not_found" | string;
  backtest_id?: number;
  execution_model?: string;
  buy_count?: number;
  minute_1430_count?: number;
  minute_1430_ratio?: number | null;
  daily_close_proxy_count?: number;
  daily_close_proxy_ratio?: number | null;
  strict_1430_rejected_count?: number;
  minute_gap_rejected_count?: number;
  tail_entry_rejected_count?: number;
  tail_exit_rejected_count?: number;
  next_action?: string;
  diagnostics?: BacktestRobustnessDiagnostic[];
  message?: string;
}

export interface BacktestDataQualityDashboard {
  status: "ready" | "warning" | "mixed_proxy" | "missing_snapshots" | "unavailable" | "not_found" | string;
  backtest_id: number;
  strategy_id?: string | null;
  strategy_version?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  execution_model?: string | null;
  minute_coverage?: BacktestMinuteCoverage;
  data_as_of_audit?: Record<string, unknown>;
  sample?: Record<string, unknown>;
  checks: Array<{
    id: string;
    label: string;
    status: "pass" | "warning" | "fail" | string;
    value?: number | string | null;
    message?: string | null;
  }>;
  next_action?: string | null;
  message?: string | null;
}

export interface BacktestReport {
  status: string;
  backtest_id: number;
  run_type?: "portfolio" | "symbol" | string;
  strategy_id: string;
  strategy_version: string;
  start_date: string;
  end_date: string;
  sample: {
    bar_count: number;
    symbol_count: number;
    data_start: string;
    data_end: string;
    equity_days: number;
    eligible_symbol_count?: number;
    universe_stock_count?: number;
    coverage_pct?: number | null;
  };
  metrics: BacktestMetrics;
  extended_metrics?: BacktestExtendedMetrics;
  summary_rows: Array<{ key: string; label: string; value: number | null }>;
  trades: BacktestTrade[];
  recent_trades?: BacktestTrade[];
  trade_count: number;
  returned_trade_count?: number;
  closed_trades?: BacktestClosedTrade[];
  closed_trade_count?: number;
  monthly_returns?: BacktestMonthlyReturn[];
  symbol_performance?: BacktestSymbolPerformance[];
  worst_trades?: BacktestClosedTrade[];
  order_stats?: BacktestOrderStats;
  equity_tail?: BacktestEquityRow[];
  data_quality?: BacktestDataQuality;
  benchmark?: {
    status: string;
    benchmarks: BacktestBenchmarkItem[];
  };
  period_analysis?: BacktestPeriodAnalysis;
  regime_analysis?: BacktestRegimeAnalysis;
  robustness_checks?: BacktestRobustnessChecks;
  execution_quality?: BacktestExecutionQuality;
  data_as_of_audit?: BacktestDataAsOfAudit;
  method?: BacktestMethod;
  assumptions: Record<string, string>;
  limitations: string[];
}

export interface PortfolioGroup {
  id: number;
  name: string;
  group_type: string;
  description?: string | null;
  auto_managed: boolean;
  risk_profile?: string;
}

export interface PortfolioItem extends StockIdentityFields {
  group_id: number;
  vt_symbol: string;
  name?: string | null;
  source: string;
  reason?: string | null;
  strategy_id?: string | null;
  strategy_version?: string | null;
  expires_at?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface SimulationAccount {
  id: number;
  name: string;
  status: string;
}

export interface SimulationPosition extends StockIdentityFields {
  account_id: number;
  account_name?: string;
  vt_symbol: string;
  name?: string | null;
  volume: number;
  available: number;
  cost_price: number;
  last_price?: number | null;
  floating_pnl_pct?: number | null;
  stop_loss_price?: number | null;
  take_profit_price?: number | null;
  trailing_stop_price?: number | null;
  /** Realtime exit advice: hold/stop_loss/take_profit/trailing_stop/time_stop. */
  advice?: string;
  source: string;
  reason?: string | null;
  last_buy_time?: string | null;
  last_buy_price?: number | null;
  last_buy_volume?: number | null;
  last_buy_reason?: string | null;
  last_sell_time?: string | null;
  last_sell_price?: number | null;
  last_sell_volume?: number | null;
  recommendation_id?: number | null;
  updated_at?: string;
}

export interface AutoBuyResult {
  status: string;
  account_id?: number;
  filled?: number;
  auto_position_sync?: {
    group_type: string;
    synced: number;
  };
  items?: Array<Record<string, unknown>>;
  message?: string;
}

/** A simulated order placement result (filled / skipped / rejected / invalid). */
export interface PlaceOrderResult {
  status: string;
  vt_symbol?: string;
  order_id?: number;
  side?: string;
  price?: number;
  volume?: number;
  reason?: string;
  message?: string;
}

/** A risk event row (order rejected, stop triggered, etc.). */
export interface RiskEvent {
  id: number;
  account_id?: number | null;
  vt_symbol?: string | null;
  event_type: string;
  severity: string;
  message: string;
  context?: Record<string, unknown> | null;
  created_at?: string;
}

export interface VnpyStatus {
  status: string;
  product: string;
  vnpy_package_name: string;
  launcher: {
    path: string;
    registered_gateways: string[];
    registered_apps: string[];
    a_share_gateway_registered: boolean;
  };
  plugins: Array<{
    module: string;
    name: string;
    category: string;
    purpose: string;
    installed: boolean;
    required_for_a_share: boolean;
  }>;
  capabilities: Record<string, boolean>;
  notes: string[];
}

export interface QuantScreenRunItem {
  id: number;
  strategy_id: string;
  strategy_version: string;
  trade_date: string;
  status: string;
  params?: Record<string, unknown>;
  candidate_count: number;
  signal_count: number;
  recommendation_count: number;
  buy_recommendation_count?: number;
  watch_recommendation_count?: number;
  message?: string | null;
  finished_at?: string | null;
}

export interface QuantTradingDateItem {
  trade_date: string;
  symbol_count: number;
  is_complete?: boolean;
  min_complete_daily_symbol_count?: number;
}

export function createScreenRun(payload: {
  trade_date?: string;
  strategy?: string;
  max_symbols?: number;
  recommendation_limit?: number;
  min_recommendation_score?: number;
  persist?: boolean;
  auto_portfolio?: boolean;
  included_boards?: string[];
} = {}) {
  return apiClient.post<QuantScreenRun>("/quant/screen-runs", payload);
}

export function createScreenRunRange(payload: {
  start?: string;
  end?: string;
  strategy?: string;
  max_symbols?: number;
  recommendation_limit?: number;
  min_recommendation_score?: number;
  persist?: boolean;
  auto_portfolio?: boolean;
  included_boards?: string[];
  force_refresh?: boolean;
  persist_signal_details?: boolean;
  create_replay?: boolean;
} = {}) {
  return apiClient.post<QuantScreenRunRange>("/quant/screen-runs/range", payload);
}

export function createQuantResearchRun(payload: {
  start?: string;
  end?: string;
  strategy?: string;
  max_symbols?: number;
  recommendation_limit?: number;
  min_recommendation_score?: number;
  min_entry_score?: number;
  persist?: boolean;
  auto_portfolio?: boolean;
  included_boards?: string[];
  candidate_limit?: number;
  strict_entry?: boolean;
  execution_model?: "legacy_next_open" | string;
  force_refresh?: boolean;
  persist_signal_details?: boolean;
  create_replay?: boolean;
} = {}) {
  return apiClient.post<QuantResearchRun>("/quant/research-runs", payload);
}

export function fetchLatestQuantResearchRun() {
  return apiClient.get<QuantResearchRun | null>("/quant/research-runs/latest");
}

export function fetchQuantResearchRun(runId: string) {
  return apiClient.get<QuantResearchRun>(`/quant/research-runs/${encodeURIComponent(runId)}`);
}

export interface StrategyReplayRun {
  id: number;
  strategy_id: string;
  strategy_version: string;
  start_date: string;
  end_date: string;
  status: string;
  params?: Record<string, unknown>;
  metrics?: {
    attempt_count?: number;
    buy_attempt_count?: number;
    sell_attempt_count?: number;
    filled_count?: number;
    rejected_count?: number;
    reject_reasons?: Array<{ reason: string; count: number }>;
  } | null;
  message?: string | null;
  finished_at?: string | null;
}

export function fetchReplayRuns(limit = 80, strategy?: string) {
  const search = new URLSearchParams({ limit: String(limit) });
  if (strategy) search.set("strategy", strategy);
  return apiClient.get<{ status: string; items: StrategyReplayRun[] }>(`/quant/replay-runs?${search.toString()}`);
}

export function createReplayRun(payload: {
  start: string;
  end: string;
  strategy?: string;
  max_symbols?: number;
  min_entry_score?: number;
  strict_entry?: boolean;
  execution_model?: string;
  minute_interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
  included_boards?: string[];
}) {
  return apiClient.post<{
    status: string;
    replay_run_id?: number;
    strategy_id?: string;
    strategy_version?: string;
    start_date?: string;
    end_date?: string;
    metrics?: StrategyReplayRun["metrics"];
    message?: string | null;
  }>("/quant/replay-runs", payload);
}

export function fetchScreenRuns(limit = 120, strategy?: string) {
  const search = new URLSearchParams({ limit: String(limit) });
  if (strategy) search.set("strategy", strategy);
  return apiClient.get<{ status: string; items: QuantScreenRunItem[] }>(`/quant/screen-runs?${search.toString()}`);
}

export function fetchTradingDates(params: { start?: string; end?: string; limit?: number } = {}) {
  const search = new URLSearchParams({ limit: String(params.limit ?? 600) });
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  return apiClient.get<{
    status: string;
    items: QuantTradingDateItem[];
    latest_trade_date?: string | null;
    latest_complete_trade_date?: string | null;
    min_complete_daily_symbol_count?: number;
    earliest_trade_date?: string | null;
    returned_count?: number;
  }>(`/quant/trading-dates?${search.toString()}`);
}

export function fetchRecommendations(limit = 20, tradeDate?: string, strategy?: string) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (tradeDate) params.set("trade_date", tradeDate);
  if (strategy) params.set("strategy", strategy);
  return apiClient.get<{
    status: string;
    trade_date?: string;
    run_id?: number | null;
    strategy_id?: string;
    strategy_version?: string;
    included_boards?: string[];
    items: QuantRecommendation[];
    message?: string;
  }>(`/quant/recommendations?${params.toString()}`);
}

export function fetchTailPreview(limit = 100, tradeDate?: string, strategy?: string, refresh = false) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (tradeDate) params.set("trade_date", tradeDate);
  if (strategy) params.set("strategy", strategy);
  if (refresh) params.set("refresh", "true");
  return apiClient.get<QuantScreenRun>(`/quant/tail-preview?${params.toString()}`);
}

export function fetchSymbolSignalHistory(vtSymbol: string, params: {
  strategy?: string;
  start?: string;
  end?: string;
  min_entry_score?: number;
  limit?: number;
} = {}) {
  const search = new URLSearchParams();
  if (params.strategy) search.set("strategy", params.strategy);
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.min_entry_score != null) search.set("min_entry_score", String(params.min_entry_score));
  if (params.limit != null) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiClient.get<SymbolSignalHistory>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/signal-history${suffix}`);
}

export function fetchSymbolMarketLine(vtSymbol: string, params: {
  strategy?: string;
  start?: string;
  end?: string;
  limit?: number;
} = {}) {
  const search = new URLSearchParams();
  if (params.strategy) search.set("strategy", params.strategy);
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.limit != null) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiClient.get<SymbolMarketLineSummary>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/market-line${suffix}`);
}

export function fetchSymbolStrategyComparison(vtSymbol: string, params: {
  start?: string;
  end?: string;
  limit?: number;
} = {}) {
  const search = new URLSearchParams();
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.limit != null) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiClient.get<SymbolStrategyComparison>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/strategy-comparison${suffix}`);
}

/** 某股最近一次候选的买卖计划（候选筛选时预算存储，单股详情直接读取，免重算）。 */
export interface SymbolTradePlan extends StockIdentityFields {
  status: string;
  message?: string;
  trade_date?: string;
  strategy_id?: string;
  rank?: number;
  action?: string;
  total_score?: number;
  trade_plan?: {
    entry_price: number;
    stop_loss_price: number;
    take_profit_price: number;
    entry_date?: string;
  } | null;
  risk_control?: Record<string, unknown>;
}

export function fetchSymbolTradePlan(vtSymbol: string, strategy?: string) {
  const suffix = strategy ? `?strategy=${encodeURIComponent(strategy)}` : "";
  return apiClient.get<SymbolTradePlan>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/trade-plan${suffix}`);
}

export interface SymbolQuantSignalRow extends StockIdentityFields {
  id?: number;
  run_id?: number | null;
  trade_date?: string;
  vt_symbol?: string;
  strategy_id?: string;
  strategy_version?: string;
  signal_type?: string;
  total_score?: number | null;
  relative_strength_score?: number | null;
  washout_score?: number | null;
  trend_quality_score?: number | null;
  sector_mainline_score?: number | null;
  financial_improvement_score?: number | null;
  liquidity_score?: number | null;
  risk_score?: number | null;
  entry_signal?: boolean;
  raw_entry_signal?: boolean;
  executable_entry_signal?: boolean;
  action?: "BUY" | "WATCH" | string;
  failed_rules?: string[];
  failed_rule_count?: number;
  signal_label?: string | null;
  signal_role?: string | null;
  key_entry_signal?: boolean | null;
  display_kind?: "buy" | "rejected_buy" | "trade" | string | null;
  cluster_size?: number | null;
  cluster_start_date?: string | null;
  cluster_end_date?: string | null;
  cluster_dates?: string[];
  risk_level?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface SymbolLatestQuantState extends StockIdentityFields {
  status: string;
  message?: string | null;
  vt_symbol: string;
  name?: string | null;
  strategy_id?: string;
  strategy_version?: string;
  process?: {
    source?: "replay" | "screen" | string;
    replay_run_id?: number | null;
    screen_run_id?: number | null;
    strategy_id?: string;
    strategy_version?: string;
    start_date?: string | null;
    end_date?: string | null;
    latest_available_trade_date?: string | null;
    is_stale?: boolean;
    status?: string | null;
    params?: Record<string, unknown>;
    metrics?: Record<string, unknown>;
    message?: string | null;
    included_boards?: string[];
  };
  state?: {
    code?: string;
    label?: string;
    severity?: "success" | "warning" | "neutral" | string;
    reason?: string | null;
  };
  signal?: {
    status?: string;
    scored_date_count?: number;
    entry_signal_count?: number;
    latest?: SymbolQuantSignalRow | null;
    latest_entry_signal?: SymbolQuantSignalRow | null;
    best_total_score?: SymbolQuantSignalRow | null;
    recent?: SymbolQuantSignalRow[];
    display_markers?: SymbolQuantSignalRow[];
  };
  candidate?: {
    status?: string;
    item?: SymbolTradePlan | null;
    trade_plan?: SymbolTradePlan["trade_plan"] | null;
  };
  replay?: {
    status?: string;
    replay_run_id?: number | null;
    vt_symbol?: string;
    name?: string | null;
    summary?: SymbolStrategyReplay["summary"] | null;
    attempts?: StrategyReplayAttempt[];
    events?: StrategyReplayEvent[];
    closed_trades?: StrategyReplayClosedTrade[];
  };
}

export function fetchLatestSymbolQuantState(vtSymbol: string, strategy?: string) {
  const suffix = strategy ? `?strategy=${encodeURIComponent(strategy)}` : "";
  return apiClient.get<SymbolLatestQuantState>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/latest-state${suffix}`);
}

/** 某股最近的单股回测（trades + metrics，免重算直接读存储）。 */
export interface SymbolLatestBacktest {
  status: string;
  message?: string;
  backtest_id?: number;
  strategy_id?: string;
  strategy_version?: string;
  start_date?: string;
  end_date?: string;
  metrics?: BacktestMetrics;
  trade_count?: number;
  trades?: BacktestTrade[];
  orders?: BacktestAuditEvent[];
  audit?: BacktestAudit;
}

export function fetchLatestSymbolBacktest(vtSymbol: string, strategy?: string) {
  const suffix = strategy ? `?strategy=${encodeURIComponent(strategy)}` : "";
  return apiClient.get<SymbolLatestBacktest>(`/backtests/symbols/${encodeURIComponent(vtSymbol)}/latest${suffix}`);
}

export interface StrategyReplayAttempt extends StockIdentityFields {
  id?: number;
  replay_run_id?: number;
  signal_run_id?: number | null;
  signal_date: string;
  execute_date: string;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  signal_type?: string | null;
  plan_status: string;
  execution_status: string;
  price?: number | null;
  price_source?: string | null;
  proxy_used?: boolean;
  reject_reason?: string | null;
  score?: number | null;
  raw?: Record<string, unknown>;
}

export interface StrategyReplayEvent extends StockIdentityFields {
  event_type: "signal" | "execution" | string;
  trade_date: string;
  signal_date?: string | null;
  execute_date?: string | null;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  status: string;
  price?: number | null;
  score?: number | null;
  reason?: string | null;
  price_source?: string | null;
  proxy_used?: boolean;
  raw?: Record<string, unknown>;
}

export interface StrategyReplayClosedTrade extends StockIdentityFields {
  vt_symbol: string;
  name?: string | null;
  entry_date?: string | null;
  exit_date?: string | null;
  entry_price?: number | null;
  exit_price?: number | null;
  return_pct?: number | null;
  holding_days?: number | null;
  exit_reason?: string | null;
}

export interface SymbolStrategyReplay extends StockIdentityFields {
  status: string;
  message?: string | null;
  replay_run_id?: number;
  vt_symbol: string;
  name?: string | null;
  strategy_id?: string;
  strategy_version?: string;
  start_date?: string | null;
  end_date?: string | null;
  params?: Record<string, unknown>;
  summary?: {
    signal_count?: number;
    buy_filled_count?: number;
    rejected_count?: number;
    closed_trade_count?: number;
    compound_return_pct?: number | null;
    average_return_pct?: number | null;
    win_rate_pct?: number | null;
    current_status?: string;
    reject_reasons?: Array<{ reason: string; count: number }>;
  };
  attempts?: StrategyReplayAttempt[];
  events?: StrategyReplayEvent[];
  closed_trades?: StrategyReplayClosedTrade[];
}

export function fetchLatestSymbolReplay(vtSymbol: string, strategy?: string) {
  const suffix = strategy ? `?strategy=${encodeURIComponent(strategy)}` : "";
  return apiClient.get<SymbolStrategyReplay>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/replay/latest${suffix}`);
}

export function fetchSymbolDiagnostics(vtSymbol: string, params: {
  start?: string;
  end?: string;
  backtest_id?: number | string;
  signal_date?: string;
  limit?: number;
} = {}) {
  const search = new URLSearchParams();
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.backtest_id != null && String(params.backtest_id).trim()) {
    search.set("backtest_id", String(params.backtest_id));
  }
  if (params.signal_date) search.set("signal_date", params.signal_date);
  if (params.limit != null) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiClient.get<SymbolDiagnostics>(`/quant/symbols/${encodeURIComponent(vtSymbol)}/diagnostics${suffix}`);
}

export function fetchQuantStrategies() {
  return apiClient.get<{ status: string; default_strategy_id: string; items: QuantStrategyOption[] }>("/quant/strategies");
}

export function fetchBacktests(
  limit = 10,
  runType: "portfolio" | "symbol" | "all" = "all",
  strategy?: string,
  options?: { baselineOnly?: boolean }
) {
  const search = new URLSearchParams({ limit: String(limit), run_type: runType });
  if (strategy) search.set("strategy", strategy);
  if (options?.baselineOnly) search.set("baseline_only", "true");
  return apiClient.get<{ status: string; items: BacktestRun[] }>(`/backtests?${search.toString()}`);
}

export function createBacktest(payload: {
  strategy?: string;
  start?: string;
  end?: string;
  initial_cash?: number;
  max_positions?: number;
  max_position_pct?: number;
  max_symbols?: number;
  candidate_limit?: number;
  persist?: boolean;
  min_entry_score?: number;
  strict_entry?: boolean;
  execution_model?: "tail_close_hybrid" | "strict_1430" | string;
  minute_interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
  require_low_suction_launch_confirmation?: boolean;
  exclude_repeated_dragon_pullback?: boolean;
  require_low_suction_launch_for_low_suction_context?: boolean;
  enable_entry_launch_quality_score?: boolean;
  enable_entry_launch_risk_penalty?: boolean;
  enable_low_suction_market_risk_penalty?: boolean;
  enable_market_adaptive_setup_weighting?: boolean;
  enable_low_suction_first_lift_bonus?: boolean;
  enable_low_suction_lifecycle_ranking?: boolean;
  enable_low_suction_buildup_quality_lane?: boolean;
  enable_candidate_tail_risk_penalty?: boolean;
  enable_mainline_momentum_lane?: boolean;
  enable_mainline_momentum_risk_control?: boolean;
  enable_mainline_momentum_hard_filter?: boolean;
  enable_surge_quality_lane?: boolean;
  enable_weekly_top_fractal_relief?: boolean;
  enable_pure_loss_weak_bucket_penalty?: boolean;
  enable_support_divergence_entry_lane?: boolean;
  enable_strong_trend_ma_pullback_entry_lane?: boolean;
  enable_high_risk_d2_follow_through_entry?: boolean;
  enable_dynamic_failed_launch_exit_stop?: boolean;
  enable_failed_launch_exit_stop?: boolean;
  enable_contextual_failed_launch_exit_stop?: boolean;
  enable_mid_profit_giveback_stop?: boolean;
  mid_profit_giveback_min_high_gain_pct?: number;
  mid_profit_giveback_max_current_gain_pct?: number;
  mid_profit_giveback_drawdown_pct?: number;
  reuse_signal_cache?: boolean;
  symbols?: string[];
  vt_symbol?: string;
  included_boards?: string[];
} = {}) {
  return apiClient.post<{
    status: string;
    backtest_id: number | null;
    metrics: BacktestMetrics;
    trades: BacktestTrade[];
    start: string;
    end: string;
  }>("/backtests", payload);
}

export function runBacktestStrategyComparison(payload: {
  strategies?: string[];
  start?: string;
  end?: string;
  initial_cash?: number;
  max_positions?: number;
  max_symbols?: number;
  candidate_limit?: number;
  persist?: boolean;
  min_entry_score?: number;
  strict_entry?: boolean;
  execution_model?: "tail_close_hybrid" | "strict_1430" | string;
  minute_interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
  require_low_suction_launch_confirmation?: boolean;
  exclude_repeated_dragon_pullback?: boolean;
  require_low_suction_launch_for_low_suction_context?: boolean;
  enable_entry_launch_quality_score?: boolean;
  enable_entry_launch_risk_penalty?: boolean;
  enable_low_suction_market_risk_penalty?: boolean;
  enable_market_adaptive_setup_weighting?: boolean;
  enable_low_suction_first_lift_bonus?: boolean;
  enable_low_suction_lifecycle_ranking?: boolean;
  enable_low_suction_buildup_quality_lane?: boolean;
  enable_candidate_tail_risk_penalty?: boolean;
  enable_mainline_momentum_lane?: boolean;
  enable_mainline_momentum_risk_control?: boolean;
  enable_mainline_momentum_hard_filter?: boolean;
  enable_surge_quality_lane?: boolean;
  enable_weekly_top_fractal_relief?: boolean;
  enable_pure_loss_weak_bucket_penalty?: boolean;
  enable_support_divergence_entry_lane?: boolean;
  enable_strong_trend_ma_pullback_entry_lane?: boolean;
  enable_high_risk_d2_follow_through_entry?: boolean;
  enable_dynamic_failed_launch_exit_stop?: boolean;
  enable_failed_launch_exit_stop?: boolean;
  enable_contextual_failed_launch_exit_stop?: boolean;
  enable_mid_profit_giveback_stop?: boolean;
  mid_profit_giveback_min_high_gain_pct?: number;
  mid_profit_giveback_max_current_gain_pct?: number;
  mid_profit_giveback_drawdown_pct?: number;
  included_boards?: string[];
} = {}) {
  return apiClient.post<BacktestStrategyComparison>("/backtests/strategy-comparison", payload);
}

export function createSymbolBacktest(payload: {
  vt_symbol: string;
  strategy?: string;
  start?: string;
  end?: string;
  initial_cash?: number;
  persist?: boolean;
  min_entry_score?: number;
  strict_entry?: boolean;
  execution_model?: "tail_close_hybrid" | "strict_1430" | string;
  minute_interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
  require_low_suction_launch_confirmation?: boolean;
  exclude_repeated_dragon_pullback?: boolean;
  require_low_suction_launch_for_low_suction_context?: boolean;
  enable_entry_launch_quality_score?: boolean;
  enable_entry_launch_risk_penalty?: boolean;
  enable_low_suction_market_risk_penalty?: boolean;
  enable_market_adaptive_setup_weighting?: boolean;
  enable_low_suction_first_lift_bonus?: boolean;
  enable_low_suction_lifecycle_ranking?: boolean;
  enable_low_suction_buildup_quality_lane?: boolean;
  enable_candidate_tail_risk_penalty?: boolean;
  enable_mainline_momentum_lane?: boolean;
  enable_mainline_momentum_risk_control?: boolean;
  enable_mainline_momentum_hard_filter?: boolean;
  enable_surge_quality_lane?: boolean;
  enable_weekly_top_fractal_relief?: boolean;
  enable_pure_loss_weak_bucket_penalty?: boolean;
  enable_support_divergence_entry_lane?: boolean;
  enable_strong_trend_ma_pullback_entry_lane?: boolean;
  enable_high_risk_d2_follow_through_entry?: boolean;
  enable_dynamic_failed_launch_exit_stop?: boolean;
  enable_failed_launch_exit_stop?: boolean;
  enable_contextual_failed_launch_exit_stop?: boolean;
  enable_mid_profit_giveback_stop?: boolean;
  mid_profit_giveback_min_high_gain_pct?: number;
  mid_profit_giveback_max_current_gain_pct?: number;
  mid_profit_giveback_drawdown_pct?: number;
  included_boards?: string[];
}) {
  return apiClient.post<{
    status: string;
    backtest_id: number | null;
    metrics: BacktestMetrics;
    trades: BacktestTrade[];
    orders?: BacktestAuditEvent[];
    start: string;
    end: string;
    audit?: BacktestAudit;
    assumptions?: Record<string, string>;
  }>("/backtests/symbol", payload);
}

export function runStrictMinuteBacktestPipeline(payload: {
  backtest_id?: number | string;
  start?: string;
  end?: string;
  initial_cash?: number;
  max_positions?: number;
  max_symbols?: number;
  candidate_limit?: number;
  min_entry_score?: number;
  execution_model?: "strict_1430" | string;
  minute_interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
  require_low_suction_launch_confirmation?: boolean;
  exclude_repeated_dragon_pullback?: boolean;
  require_low_suction_launch_for_low_suction_context?: boolean;
  enable_entry_launch_quality_score?: boolean;
  enable_entry_launch_risk_penalty?: boolean;
  enable_low_suction_market_risk_penalty?: boolean;
  enable_market_adaptive_setup_weighting?: boolean;
  enable_low_suction_first_lift_bonus?: boolean;
  enable_low_suction_lifecycle_ranking?: boolean;
  enable_low_suction_buildup_quality_lane?: boolean;
  enable_candidate_tail_risk_penalty?: boolean;
  enable_mainline_momentum_lane?: boolean;
  enable_mainline_momentum_risk_control?: boolean;
  enable_mainline_momentum_hard_filter?: boolean;
  enable_surge_quality_lane?: boolean;
  enable_weekly_top_fractal_relief?: boolean;
  enable_pure_loss_weak_bucket_penalty?: boolean;
  enable_support_divergence_entry_lane?: boolean;
  enable_strong_trend_ma_pullback_entry_lane?: boolean;
  enable_high_risk_d2_follow_through_entry?: boolean;
  enable_dynamic_failed_launch_exit_stop?: boolean;
  enable_failed_launch_exit_stop?: boolean;
  enable_contextual_failed_launch_exit_stop?: boolean;
  enable_mid_profit_giveback_stop?: boolean;
  mid_profit_giveback_min_high_gain_pct?: number;
  mid_profit_giveback_max_current_gain_pct?: number;
  mid_profit_giveback_drawdown_pct?: number;
  included_boards?: string[];
  gap_csv_text?: string;
  gap_file_path?: string;
  min_tail_bars?: number;
  trade_limit?: number;
} = {}) {
  return apiClient.post<{
    status: "ready" | "blocked_by_minute_gaps" | string;
    message?: string;
    audit?: {
      status: string;
      gap_count?: number;
      covered_count?: number;
      missing_count?: number;
      coverage_pct?: number;
      symbol_count?: number;
      date_count?: number;
      next_action?: string;
    };
    backtest?: {
      backtest_id?: number;
      metrics?: BacktestMetrics;
      start?: string;
      end?: string;
    };
    report?: BacktestReport;
    csv?: {
      status?: string;
      filename?: string;
    };
    params?: Record<string, unknown>;
    next_action?: string;
  }>("/backtests/strict-minute-pipeline", payload);
}

export function fetchBacktestReport(backtestId: number, tradeLimit = 50, options: { includeAnalysis?: boolean } = {}) {
  const search = new URLSearchParams({
    trade_limit: String(tradeLimit),
  });
  if (options.includeAnalysis) search.set("include_analysis", "true");
  return apiClient.get<BacktestReport>(`/backtests/${backtestId}/report?${search.toString()}`);
}

export function fetchBacktestEquity(backtestId: number) {
  return apiClient.get<BacktestEquityResult>(`/backtests/${backtestId}/equity`);
}

export function fetchBacktestDrilldownOptions(backtestId: number) {
  return apiClient.get<BacktestDrilldownOptions>(`/backtests/${backtestId}/drilldown-options`);
}

export function fetchBacktestTrades(backtestId: number, params: {
  limit?: number;
  offset?: number;
  order?: "asc" | "desc";
} = {}) {
  const search = new URLSearchParams({
    limit: String(params.limit ?? 50),
    offset: String(params.offset ?? 0),
    order: params.order ?? "desc",
  });
  return apiClient.get<BacktestTradesResult>(`/backtests/${backtestId}/trades?${search.toString()}`);
}

export function fetchBacktestDailyDecisions(backtestId: number, params: {
  limit?: number;
  offset?: number;
  order?: "asc" | "desc";
} = {}) {
  const search = new URLSearchParams({
    limit: String(params.limit ?? 100),
    offset: String(params.offset ?? 0),
    order: params.order ?? "desc",
  });
  return apiClient.get<BacktestDailyDecisionsResult>(`/backtests/${backtestId}/daily-decisions?${search.toString()}`);
}

export function fetchBacktestTradeAttribution(backtestId: number, params: {
  limit?: number;
  offset?: number;
  sort?: "pnl_asc" | "pnl_desc" | "entry_desc" | "entry_asc";
} = {}) {
  const search = new URLSearchParams({
    limit: String(params.limit ?? 100),
    offset: String(params.offset ?? 0),
    sort: params.sort ?? "pnl_asc",
  });
  return apiClient.get<BacktestTradeAttributionResult>(`/backtests/${backtestId}/trade-attribution?${search.toString()}`);
}

export function fetchBacktestPathDiagnostics(backtestId: number, vtSymbol?: string): Promise<BacktestPathDiagnosticsResponse> {
  const search = new URLSearchParams({ limit: "500", lookahead_days: "10" });
  if (vtSymbol) search.set("vt_symbol", vtSymbol);
  return apiClient.get<BacktestPathDiagnosticsResponse>(`/backtests/${backtestId}/path-diagnostics?${search.toString()}`);
}

export function fetchBacktestTopCandidateAudit(backtestId: number, topN = 10): Promise<BacktestTopCandidateAudit> {
  const search = new URLSearchParams({ top_n: String(topN) });
  return apiClient.get<BacktestTopCandidateAudit>(`/backtests/${backtestId}/top-candidate-audit?${search.toString()}`);
}

export function fetchBacktestFactorAudit(backtestId: number, topLimit = 100, options: { excludeStrongMarket?: boolean } = {}): Promise<FactorAuditResponse> {
  const search = new URLSearchParams({ top_limit: String(topLimit) });
  if (options.excludeStrongMarket) search.set("exclude_strong_market", "true");
  return apiClient.get<FactorAuditResponse>(`/backtests/${backtestId}/factor-audit?${search.toString()}`);
}

export function fetchBacktestCandidateTradeQualityReport(
  backtestId: number,
  params: {
    rankLimit?: number;
    sampleLimit?: number;
    startDate?: string;
    endDate?: string;
  } = {}
): Promise<CandidateTradeQualityReport> {
  const search = new URLSearchParams({
    rank_limit: String(params.rankLimit ?? 20),
    sample_limit: String(params.sampleLimit ?? 500),
  });
  if (params.startDate) search.set("start_date", params.startDate);
  if (params.endDate) search.set("end_date", params.endDate);
  return apiClient.get<CandidateTradeQualityReport>(`/backtests/${backtestId}/candidate-trade-quality-report?${search.toString()}`);
}

export function fetchBacktestPerformanceAttributionReport(
  backtestId: number,
  params: {
    referenceBacktestId?: number;
    sampleLimit?: number;
  } = {}
): Promise<BacktestPerformanceAttributionReport> {
  const search = new URLSearchParams({ sample_limit: String(params.sampleLimit ?? 20) });
  if (params.referenceBacktestId) search.set("reference_backtest_id", String(params.referenceBacktestId));
  return apiClient.get<BacktestPerformanceAttributionReport>(`/backtests/${backtestId}/performance-attribution?${search.toString()}`);
}

export function fetchBacktestSetupMarketExitAudit(backtestId: number, lookaheadDays = 10): Promise<BacktestSetupMarketExitAuditResponse> {
  const search = new URLSearchParams({ lookahead_days: String(lookaheadDays) });
  return apiClient.get<BacktestSetupMarketExitAuditResponse>(`/backtests/${backtestId}/setup-market-exit-audit?${search.toString()}`);
}

export function fetchBacktestPhaseStrategyFamilyMatrix(
  backtestId: number,
  candidateRankLimits: number[] = [10, 20, 100]
): Promise<BacktestPhaseStrategyFamilyMatrix> {
  const search = new URLSearchParams({ candidate_rank_limits: candidateRankLimits.join(",") });
  return apiClient.get<BacktestPhaseStrategyFamilyMatrix>(`/backtests/${backtestId}/phase-strategy-family-matrix?${search.toString()}`);
}

export function fetchBacktestFactorCandidates(backtestId: number, params: { vt_symbol?: string; limit?: number } = {}): Promise<FactorCandidateResponse> {
  const search = new URLSearchParams();
  if (params.vt_symbol) search.set("vt_symbol", params.vt_symbol);
  if (params.limit != null) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiClient.get<FactorCandidateResponse>(`/backtests/${backtestId}/factor-candidates${suffix}`);
}

export function fetchBacktestStrategyTimeline(backtestId: number, vtSymbol: string): Promise<StrategyTimelineResponse> {
  const search = new URLSearchParams({ vt_symbol: vtSymbol });
  return apiClient.get<StrategyTimelineResponse>(`/backtests/${backtestId}/strategy-timeline?${search.toString()}`);
}

export function fetchBacktestDayDetail(backtestId: number, tradeDate: string) {
  return apiClient.get<BacktestDayDetail>(`/backtests/${backtestId}/days/${tradeDate}`);
}

export function fetchBacktestSymbolDetail(backtestId: number, vtSymbol: string) {
  return apiClient.get<BacktestSymbolDetail>(`/backtests/${backtestId}/symbols/${vtSymbol}`);
}

export function fetchBacktestSignalEvents(backtestId: number, params: {
  start?: string;
  end?: string;
  vt_symbol?: string;
  side?: string;
  limit?: number;
} = {}) {
  const search = new URLSearchParams();
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.vt_symbol) search.set("vt_symbol", params.vt_symbol);
  if (params.side) search.set("side", params.side);
  if (params.limit != null) search.set("limit", String(params.limit));
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiClient.get<BacktestSignalEventsResult>(`/backtests/${backtestId}/signal-events${suffix}`);
}

export function fetchBacktestSignalAmountPreview(backtestId: number, params: {
  capital: number;
  max_positions: number;
  start?: string;
  end?: string;
  vt_symbol?: string;
  side?: string;
  limit?: number;
}) {
  const search = new URLSearchParams({
    capital: String(params.capital),
    max_positions: String(params.max_positions),
  });
  if (params.start) search.set("start", params.start);
  if (params.end) search.set("end", params.end);
  if (params.vt_symbol) search.set("vt_symbol", params.vt_symbol);
  if (params.side) search.set("side", params.side);
  if (params.limit != null) search.set("limit", String(params.limit));
  return apiClient.get<BacktestSignalAmountPreviewResult>(`/backtests/${backtestId}/signal-events/amount-preview?${search.toString()}`);
}

export function fetchBacktestAudit(backtestId: number, vtSymbol?: string, limit = 200) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (vtSymbol) params.set("vt_symbol", vtSymbol);
  return apiClient.get<BacktestAudit>(`/backtests/${backtestId}/audit?${params.toString()}`);
}

export function fetchBacktestCandidateTrace(backtestId: number, vtSymbol: string, signalDate: string) {
  const params = new URLSearchParams({ vt_symbol: vtSymbol, signal_date: signalDate });
  return apiClient.get<BacktestCandidateTrace>(`/backtests/${backtestId}/candidate-trace?${params.toString()}`);
}

export function backtestReportCsvUrl(backtestId: number, tradeLimit = 500) {
  return apiUrl(`/backtests/${backtestId}/report.csv?trade_limit=${tradeLimit}`);
}

export function fetchBacktestValidationGrid(backtestId: number, maxVariants = 54) {
  return apiClient.get<BacktestValidationGrid>(`/backtests/${backtestId}/validation-grid?max_variants=${maxVariants}`);
}

export function fetchBacktestExecutionModelComparison(backtestId: number) {
  return apiClient.get<BacktestExecutionModelComparison>(`/backtests/${backtestId}/execution-model-comparison`);
}

export function fetchBacktestMinuteCoverage(backtestId: number) {
  return apiClient.get<BacktestMinuteCoverage>(`/backtests/${backtestId}/minute-coverage`);
}

export function fetchBacktestDataQuality(backtestId: number) {
  return apiClient.get<BacktestDataQualityDashboard>(`/backtests/${backtestId}/data-quality`);
}

export function backtestValidationGridCsvUrl(backtestId: number, maxVariants = 54) {
  return apiUrl(`/backtests/${backtestId}/validation-grid.csv?max_variants=${maxVariants}`);
}

export function fetchPortfolioGroups() {
  return apiClient.get<{ status: string; items: PortfolioGroup[] }>("/portfolio/groups");
}

export function fetchPortfolioGroupItems(groupId: number) {
  return apiClient.get<{ status: string; items: PortfolioItem[] }>(`/portfolio/groups/${groupId}/items`);
}

export function createPortfolioGroup(payload: {
  name: string;
  group_type?: string;
  description?: string;
  risk_profile?: string;
}) {
  return apiClient.post<{ status: string; id?: number; message?: string }>("/portfolio/groups", payload);
}

export function addPortfolioGroupItem(groupId: number, payload: {
  vt_symbol: string;
  name?: string;
  source?: string;
  reason?: string;
  strategy_id?: string;
  strategy_version?: string;
}) {
  return apiClient.post<{ status: string; group_id: number; vt_symbol: string }>(`/portfolio/groups/${groupId}/items`, payload);
}

export function removePortfolioGroupItem(groupId: number, vtSymbol: string) {
  return apiClient.del<{ status: string; deleted: number }>(`/portfolio/groups/${groupId}/items/${encodeURIComponent(vtSymbol)}`);
}

export function reorderPortfolioGroups(groupIds: number[]) {
  return apiClient.post<{ status: string; reordered: number }>("/portfolio/groups/reorder", { group_ids: groupIds });
}

export function updatePortfolioGroup(groupId: number, payload: {
  name?: string;
  description?: string | null;
  risk_profile?: string;
  auto_managed?: boolean;
}) {
  return apiClient.patch<{ status: string; id: number; updated: number }>(`/portfolio/groups/${groupId}`, payload);
}

export function deletePortfolioGroup(groupId: number) {
  return apiClient.del<{ status: string; id: number; deleted: number }>(`/portfolio/groups/${groupId}`);
}

export function fetchHoldings() {
  return apiClient.get<{ status: string; items: SimulationPosition[] }>("/portfolio/holdings");
}

export function fetchSimulationAccounts() {
  return apiClient.get<{ status: string; items: SimulationAccount[] }>("/simulation/accounts");
}

export function autoBuyRecommendations(payload: {
  account_id?: number;
  limit?: number;
} = {}) {
  return apiClient.post<AutoBuyResult>("/simulation/auto-buy-recommendations", payload);
}

export function placeOrder(accountId: number, payload: {
  vt_symbol: string;
  side: "BUY" | "SELL";
  price?: number;
  volume?: number;
  reason?: string;
  recommendation_id?: number;
  strategy_id?: string;
}) {
  return apiClient.post<PlaceOrderResult>(`/simulation/accounts/${accountId}/orders`, payload);
}

export function updatePositionCost(accountId: number, vtSymbol: string, costPrice: number) {
  return apiClient.patch<{ status: string; position?: SimulationPosition }>(
    `/simulation/accounts/${accountId}/positions/${encodeURIComponent(vtSymbol)}`,
    { cost_price: costPrice },
  );
}

export function fetchRiskEvents(accountId: number, limit = 100) {
  return apiClient.get<{ status: string; items: RiskEvent[] }>(
    `/simulation/accounts/${accountId}/risk-events?limit=${limit}`,
  );
}

export function fetchVnpyStatus() {
  return apiClient.get<VnpyStatus>("/vnpy/status");
}

export function importVnpyMinuteBars(payload: {
  vt_symbol: string;
  start: string;
  end?: string;
  interval?: string;
  dry_run?: boolean;
}) {
  return apiClient.post<{
    status: string;
    vt_symbol?: string;
    interval?: string;
    dry_run?: boolean;
    rows_read?: number;
    rows_written?: number;
    source?: string;
    message?: string;
    note?: string;
  }>("/vnpy/import-minute-bars", payload);
}

export function importVnpyMinuteBarsForGaps(payload: {
  backtest_id?: number | string;
  gap_csv_text?: string;
  gap_file_path?: string;
  interval?: string;
  tail_entry_start?: string;
  tail_entry_end?: string;
  dry_run?: boolean;
  max_gaps?: number;
}) {
  return apiClient.post<{
    status: string;
    interval?: string;
    dry_run?: boolean;
    tail_entry_window?: string;
    gap_count?: number;
    processed_gap_count?: number;
    unprocessed_gap_count?: number;
    symbol_count?: number;
    date_count?: number;
    rows_read?: number;
    rows_written?: number;
    empty_request_count?: number;
    rows_skipped?: number;
    errors?: string[];
    audit_after?: {
      status: string;
      gap_count?: number;
      covered_count?: number;
      missing_count?: number;
      coverage_pct?: number;
    };
    source?: string;
    message?: string;
    note?: string;
  }>("/vnpy/import-minute-bars/gaps", payload);
}
