import { apiClient, apiUrl } from "./client";

export type StockBoard = "main" | "chinext" | "star" | "bse" | "index" | "unknown" | string;

export interface StockIdentityFields {
  board?: StockBoard;
  board_label?: string | null;
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
  risk_control?: Record<string, unknown> | null;
  status?: string;
  expires_at?: string | null;
}

export interface QuantScreenRun {
  status: string;
  strategy_id: string;
  strategy_version: string;
  trade_date?: string;
  run_id?: number | null;
  total?: number;
  recommendation_count?: number;
  included_boards?: string[];
  recommendations: QuantRecommendation[];
  portfolio_sync?: {
    group_id: number;
    group_type: string;
    synced: number;
  } | null;
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
}

export interface BacktestMetrics {
  initial_cash?: number;
  final_equity?: number;
  total_return_pct?: number;
  annual_return_pct?: number;
  max_drawdown_pct?: number;
  trade_count?: number;
  win_rate?: number;
  profit_factor?: number | null;
  average_win?: number;
  average_loss?: number;
  sharpe?: number | null;
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
    tail_entry_window?: string;
    tail_entry_ma5_tolerance_pct?: number;
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
  raw?: Record<string, unknown>;
}

export interface BacktestAuditEvent extends StockIdentityFields {
  event_type: "order" | "trade" | string;
  trade_date: string;
  vt_symbol: string;
  name?: string | null;
  side: "BUY" | "SELL" | string;
  status?: string;
  reason?: string | null;
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
  filled_order_count: number;
  execution_modes?: Record<string, number>;
}

export interface BacktestExecutionQuality {
  status: "pass" | "warning" | string;
  buy_count: number;
  minute_tail_entry_count: number;
  daily_open_fallback_count: number;
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
  [tableName: string]: { count: number } | string[] | undefined;
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
  cost_stress: BacktestCostStressRow[];
  random_baseline: BacktestRandomBaseline;
  diagnostics: BacktestRobustnessDiagnostic[];
  limitations: string[];
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

export interface BacktestReport {
  status: string;
  backtest_id: number;
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
  trade_count: number;
  returned_trade_count?: number;
  closed_trades?: BacktestClosedTrade[];
  closed_trade_count?: number;
  monthly_returns?: BacktestMonthlyReturn[];
  symbol_performance?: BacktestSymbolPerformance[];
  worst_trades?: BacktestClosedTrade[];
  order_stats?: BacktestOrderStats;
  data_quality?: BacktestDataQuality;
  benchmark?: {
    status: string;
    benchmarks: BacktestBenchmarkItem[];
  };
  period_analysis?: BacktestPeriodAnalysis;
  regime_analysis?: BacktestRegimeAnalysis;
  robustness_checks?: BacktestRobustnessChecks;
  execution_quality?: BacktestExecutionQuality;
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
  initial_cash: number;
  cash: number;
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
  market_value?: number | null;
  floating_pnl?: number | null;
  floating_pnl_pct?: number | null;
  stop_loss_price?: number | null;
  take_profit_price?: number | null;
  trailing_stop_price?: number | null;
  source: string;
  reason?: string | null;
  last_buy_time?: string | null;
  last_buy_price?: number | null;
  last_buy_volume?: number | null;
  last_buy_amount?: number | null;
  last_buy_reason?: string | null;
  last_sell_time?: string | null;
  last_sell_price?: number | null;
  last_sell_volume?: number | null;
  last_sell_amount?: number | null;
  last_sell_pnl?: number | null;
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

export function createScreenRun(payload: {
  trade_date?: string;
  max_symbols?: number;
  recommendation_limit?: number;
  min_recommendation_score?: number;
  persist?: boolean;
  auto_portfolio?: boolean;
  included_boards?: string[];
} = {}) {
  return apiClient.post<QuantScreenRun>("/quant/screen-runs", payload);
}

export function fetchRecommendations(limit = 20) {
  return apiClient.get<{
    status: string;
    trade_date?: string;
    run_id?: number | null;
    strategy_version?: string;
    included_boards?: string[];
    items: QuantRecommendation[];
    message?: string;
  }>(
    `/quant/recommendations?limit=${limit}`
  );
}

export function fetchBacktests(limit = 10) {
  return apiClient.get<{ status: string; items: BacktestRun[] }>(`/backtests?limit=${limit}`);
}

export function createBacktest(payload: {
  start?: string;
  end?: string;
  initial_cash?: number;
  max_positions?: number;
  max_symbols?: number;
  candidate_limit?: number;
  persist?: boolean;
  min_entry_score?: number;
  strict_entry?: boolean;
  intraday_entry?: boolean;
  minute_entry_required?: boolean;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
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

export function createSymbolBacktest(payload: {
  vt_symbol: string;
  start?: string;
  end?: string;
  initial_cash?: number;
  persist?: boolean;
  min_entry_score?: number;
  strict_entry?: boolean;
  intraday_entry?: boolean;
  minute_entry_required?: boolean;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
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
  start?: string;
  end?: string;
  initial_cash?: number;
  max_positions?: number;
  max_symbols?: number;
  candidate_limit?: number;
  min_entry_score?: number;
  tail_entry_start?: string;
  tail_entry_end?: string;
  tail_entry_ma5_tolerance_pct?: number;
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

export function fetchBacktestReport(backtestId: number, tradeLimit = 50) {
  return apiClient.get<BacktestReport>(`/backtests/${backtestId}/report?trade_limit=${tradeLimit}`);
}

export function fetchBacktestAudit(backtestId: number, vtSymbol?: string, limit = 200) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (vtSymbol) params.set("vt_symbol", vtSymbol);
  return apiClient.get<BacktestAudit>(`/backtests/${backtestId}/audit?${params.toString()}`);
}

export function backtestReportCsvUrl(backtestId: number, tradeLimit = 500) {
  return apiUrl(`/backtests/${backtestId}/report.csv?trade_limit=${tradeLimit}`);
}

export function fetchBacktestValidationGrid(backtestId: number, maxVariants = 54) {
  return apiClient.get<BacktestValidationGrid>(`/backtests/${backtestId}/validation-grid?max_variants=${maxVariants}`);
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

export function fetchHoldings() {
  return apiClient.get<{ status: string; items: SimulationPosition[] }>("/portfolio/holdings");
}

export function fetchSimulationAccounts() {
  return apiClient.get<{ status: string; items: SimulationAccount[] }>("/simulation/accounts");
}

export function autoBuyRecommendations(payload: {
  account_id?: number;
  limit?: number;
  amount_per_order?: number;
  initial_cash?: number;
} = {}) {
  return apiClient.post<AutoBuyResult>("/simulation/auto-buy-recommendations", payload);
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
