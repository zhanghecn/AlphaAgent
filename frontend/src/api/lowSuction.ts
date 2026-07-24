import { apiClient } from "./client";

interface CrossRegimeReturnMetrics {
  closed_trades: number;
  win_rate_pct: number | null;
  mean_net_return_pct: number | null;
  profit_factor: number | null;
}

interface CrossRegimePhaseMetrics extends CrossRegimeReturnMetrics {
  id: string;
}

interface ThreePhaseMetrics extends CrossRegimePhaseMetrics {
  wilson_95_lower_pct: number;
}

interface CrossRegimeCashMetrics {
  closed_trades: number;
  cash_win_rate_pct: number | null;
  compound_return_pct: number;
  maximum_drawdown_pct: number;
}

interface CrossRegimeCandidate {
  policy_version: string;
  formal_strategy: false;
  full_history: CrossRegimeReturnMetrics;
  development: CrossRegimeReturnMetrics;
  validation: CrossRegimeReturnMetrics;
  cash: CrossRegimeCashMetrics;
  qualification: {
    historical_numeric_gates_passed: boolean;
    status: string;
    failed_gates: string[];
  };
  formal_blockers: string[];
}

export interface LowSuctionCrossRegimeValidation {
  report_version: "cross-regime-validation-product-v1";
  formal_strategy: false;
  current_candidate: CrossRegimeCandidate;
  adaptive_candidate: CrossRegimeCandidate & {
    selection_origin: string;
    development_market_phases: CrossRegimePhaseMetrics[];
    validation_market_phases: CrossRegimePhaseMetrics[];
  };
  three_phase_candidate: CrossRegimeCandidate & {
    selection_origin: string;
    execution_contract: {
      universe: string;
      data_frequency: string;
      concept_campaign: string;
      leader_identity: string;
      main_rise_structure: string;
      wave_support: string;
      common_reclaim: string;
      uptrend_entry: string;
      warming_entry: string;
      rotation_entry: string;
      retreat_entry: string;
      entry_execution: string;
      d1_exit: string;
      winner_exit: string;
      portfolio: string;
    };
    development_market_phases: ThreePhaseMetrics[];
    validation_market_phases: ThreePhaseMetrics[];
    robustness: {
      full_history: {
        wilson_95_lower_pct: number;
        without_largest_winner_mean_pct: number;
        leave_one_campaign_out_min_win_rate_pct: number;
      };
      development: { all: { wilson_95_lower_pct: number } };
      validation: { all: { wilson_95_lower_pct: number } };
      time_block_summary: {
        blocks: number;
        point_win_rate_above_60_blocks: number;
        positive_mean_return_blocks: number;
        wilson_95_lower_above_60_blocks: number;
      };
      conclusion: string;
    };
  };
  natural_forward: {
    research_status: string;
    coverage: {
      candidate_rows: number;
      closed_outcomes: number;
      candidate_market_phases: Record<string, number>;
      closed_market_phases: Record<string, number>;
    };
    qualification: {
      sample_gates_passed: boolean;
      performance_gates_passed: boolean;
      confidence_gates_passed: boolean;
      all_gates_passed: boolean;
      failed_gates: string[];
    };
    four_slot_cash: CrossRegimeCashMetrics;
    verified_forward_metrics: Record<string, unknown> | null;
  };
  boundaries: string[];
  artifact: {
    path: string;
    sha256: string;
  };
  three_phase_artifact: {
    path: string;
    sha256: string;
  };
}

export interface LowSuctionStrategyPhase {
  status: string;
  complete: boolean;
  attempted_at: string | null;
  candidate_count: number;
  recommendation_count: number;
  positions_opened: number;
  positions_closed: number;
  blocking_reasons: string[];
}

export interface LowSuctionStrategySignal {
  signal_id: string;
  signal_trade_date: string;
  captured_at: string;
  feature_cutoff_at: string;
  vt_symbol: string;
  stock_name: string;
  sector_id: string;
  sector_name: string;
  rank: number;
  current_wave_number: number;
  confirmed_higher_highs: number;
  reference_peak_price: number;
  support_line: string | null;
  support_price: number | null;
  provisional_close: number;
  provisional_ma5: number | null;
  signal_eligible: boolean;
  decision_reason: string;
  recommendation_state: string;
  portfolio_reason: string | null;
  quote_trade_time: string;
  evidence_level: string;
  recommendation_source?: "previous_close_cache";
  cached?: boolean;
}

export interface LowSuctionPaperPosition {
  signal_id: string;
  vt_symbol: string;
  stock_name: string;
  sector_id: string;
  sector_name: string;
  status: "open" | "exit_pending";
  entry_trade_date: string;
  entry_at: string;
  entry_price: number;
  volume: number;
  reference_peak_price: number;
  exit_trigger_date: string | null;
  exit_trigger_reason: string | null;
  exit_due_after: string | null;
  exit_deferred_sessions: number;
  last_mark_date: string | null;
  last_mark_price: number | null;
  market_value: number;
  unrealized_pnl: number;
  unrealized_return_pct: number | null;
}

export interface LowSuctionPaperTrade {
  signal_id: string;
  vt_symbol: string;
  stock_name: string;
  sector_id: string;
  sector_name: string;
  entry_trade_date: string;
  entry_at: string;
  entry_price: number;
  volume: number;
  exit_trigger_date: string;
  exit_trigger_reason: string;
  exit_trade_date: string;
  exit_at: string;
  exit_price: number;
  total_fees: number;
  net_pnl: number;
  net_return_pct: number;
  exit_deferred_sessions: number;
  evidence_level: string;
}

export interface LowSuctionForwardQualification {
  status: "collecting_forward_evidence" | "not_qualified" | "qualified";
  qualified: boolean;
  checks: Record<string, boolean>;
  thresholds: {
    closed_trades: number;
    win_rate_pct_strictly_above: number;
    compound_return_pct_strictly_above: number;
    maximum_drawdown_pct_not_below: number;
    profit_factor_strictly_above: number;
  };
}

export interface LowSuctionStrategyOverview {
  strategy_version: "low-suction-swing-paper-v1";
  strategy_status: "forward_paper_collecting";
  execution_mode: "paper";
  broker_orders_enabled: false;
  contract: {
    universe: string;
    main_rise: string;
    identity: string;
    signal: string;
    entry: string;
    holding_style: "multi_session_structural";
    exit: {
      take_profit: "reference_peak_rebreak";
      defensive: "two_closes_below_ma20";
      execution: "next_session_open";
    };
    portfolio: {
      initial_cash: number;
      capacity: number;
      position_target: string;
      concept_limit: number;
      lot_size: number;
      leverage: false;
    };
  };
  session: {
    trade_date: string;
    status: string;
    market_closed: boolean;
    auto_refresh_seconds: number | null;
    phases: Record<string, LowSuctionStrategyPhase>;
    alert_stage?: "intraday_preview" | "final_confirmation";
    last_scan_at?: string | null;
    next_scan_at?: string | null;
  };
  today_candidates: LowSuctionStrategySignal[];
  recommendations: LowSuctionStrategySignal[];
  cached_recommendations: LowSuctionStrategySignal[];
  recommendation_cache: {
    active: boolean;
    source_trade_date: string | null;
    valid_until: string | null;
    policy: string;
  };
  d2_fast_limit_shadow: {
    version: string;
    trigger_rule: string;
    target_samples: number;
    triggered: number;
    settled: number;
    improved: number;
    mean_return_delta_pct_points: number | null;
    eligible_for_review: boolean;
  };
  positions: LowSuctionPaperPosition[];
  trades: LowSuctionPaperTrade[];
  forward_performance: {
    initial_cash: number;
    cash: number;
    market_value: number;
    equity: number;
    realized_pnl: number;
    unrealized_pnl: number;
    closed_trades: number;
    winning_trades: number;
    win_rate_pct: number | null;
    mean_net_return_pct: number | null;
    profit_factor: number | null;
    compound_return_pct: number;
    maximum_drawdown_pct: number;
    total_fees: number;
    qualification: LowSuctionForwardQualification;
  };
  evidence_boundary: {
    historical_metrics_in_forward: false;
    historical_evidence_is_descriptive: true;
    historical_evidence_endpoint: string;
    forward_metrics_source: string;
    broker_fill_claimed: false;
  };
  generated_at: string;
}

export interface LowSuctionHistoricalRun {
  run_id: string;
  policy_version: string;
  qualification_contract_version: string;
  evidence_level: "exploratory_survivorship_proxy" | "strict_point_in_time";
  membership_mode: "current_membership_replayed_backward" | "point_in_time_snapshot";
  input_fingerprint: string;
  trade_fingerprint: string;
  trade_count: number;
  metrics: {
    trades: number;
    positive_rate_pct: number;
    mean_net_return_pct: number;
    profit_factor?: number | null;
    all_trade_quality: {
      trades: number;
      positive_rate_pct: number | null;
      mean_net_return_pct: number | null;
      profit_factor: number | null;
    };
    two_slot_compound_backtest: {
      signals: number;
      accepted_entries: number;
      closed_trades: number;
      winning_trades: number;
      cash_win_rate_pct: number | null;
      compound_return_pct: number;
      maximum_drawdown_pct: number;
      skip_reasons: Record<string, number>;
    };
    two_slot_cash: Record<string, number | Record<string, number>>;
  };
  built_at: string;
  raw: {
    formal_strategy: false;
    formal_blockers: string[];
    regression_artifact_is_input: false;
  };
}

export interface LowSuctionHistoricalOverview {
  latest_run: LowSuctionHistoricalRun | null;
  latest_strict_run: LowSuctionHistoricalRun | null;
  formal_strategy: false;
  exploratory_counts_toward_qualification: false;
  strict_history_available: boolean;
}

export interface LowSuctionHistoricalTrade {
  run_id: string;
  signal_id: string;
  campaign_id: string;
  sector_id: string;
  concept_name: string;
  vt_symbol: string;
  stock_name: string;
  market_phase: "uptrend" | "rotation" | "warming";
  time_block: string;
  dynamic_rank: number;
  wave_number: number;
  support_line: string;
  support_price: number;
  support_test_date: string;
  signal_date: string;
  entry_price: number;
  d1_date: string;
  d1_close: number;
  d1_net_return_pct: number;
  exit_date: string;
  exit_price: number;
  exit_reason: string;
  holding_sessions: number;
  net_return_pct: number;
  raw: Record<string, unknown>;
}

export interface LowSuctionHistoricalTradePage {
  items: LowSuctionHistoricalTrade[];
  total: number;
  page: number;
  page_size: number;
}

export function fetchLowSuctionCrossRegimeValidation() {
  return apiClient.get<LowSuctionCrossRegimeValidation>(
    "/reverse-wrap/cross-regime-validation",
  );
}

export function fetchLowSuctionStrategy() {
  return apiClient.get<LowSuctionStrategyOverview>("/reverse-wrap/strategy");
}

export function fetchLowSuctionHistoricalOverview() {
  return apiClient.get<LowSuctionHistoricalOverview>("/reverse-wrap/history");
}

export function fetchLowSuctionHistoricalTrades(filters: {
  runId: string;
  page: number;
  pageSize: number;
  marketPhase?: string;
  outcome?: string;
}) {
  const query = new URLSearchParams({
    run_id: filters.runId,
    page: String(filters.page),
    page_size: String(filters.pageSize),
  });
  if (filters.marketPhase) query.set("market_phase", filters.marketPhase);
  if (filters.outcome) query.set("outcome", filters.outcome);
  return apiClient.get<LowSuctionHistoricalTradePage>(
    `/reverse-wrap/history/trades?${query.toString()}`,
  );
}

export function fetchLowSuctionHistoricalTrade(runId: string, signalId: string) {
  const query = new URLSearchParams({ run_id: runId });
  return apiClient.get<LowSuctionHistoricalTrade>(
    `/reverse-wrap/history/trades/${encodeURIComponent(signalId)}?${query.toString()}`,
  );
}
