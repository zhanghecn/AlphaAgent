import { ApiClientError, apiClient } from "./client";

export type ExitMode = "dynamic" | "next_open" | "next_close" | "next_1430";
export type EntryMode = "auction" | "sweep" | "tail" | "next_auction";
export type BoardLaneKey = "first_board" | "two_to_three" | "high_board";
export type LimitUpBacktestScope = "portfolio" | BoardLaneKey;
export type HistoryValidationPhase = "warmup" | "expanding_oos" | "locked_holdout";
export type LimitUpLiveAction = "buy_now" | "observe" | "wait_tail" | "next_auction" | "pass";
export type LimitUpLane = "now" | "tail" | "next_auction";
export type LimitUpBlockingScope = "none" | "market" | "dynamic" | "structural";
export type LimitUpMarketRepairState = "not_required" | "pending_repair" | "repair_confirmed" | "repair_revoked";

export interface LimitUpStrategyGuide {
  guide_version: string;
  strategy: {
    live_version: string;
    history_version: string;
    history_dataset_version: string;
    selection_no_lookahead: boolean;
    selection_contract: string;
    entry_windows: string[];
    entry_mode: string;
    exit_mode: string;
    max_positions: number;
    live_actionable_limit: number | null;
  };
  core_quality: {
    contract_version: string;
    prior_limit_window_days: number;
    minimum_prior_limit_count: number;
    maximum_prior_limit_count: number;
    a_tier_industry_turnover_ratio_5d: number;
    b_tier_is_actionable: boolean;
    b_first_board_minimum_time: string;
    c_tier_is_actionable: boolean;
    c_daily_limit: number;
    c_evidence_status: string;
    priority_rule: string;
    minimum_quality_win_probability: number;
    minimum_quality_expected_d1_net_return_pct: number;
    quality_estimate_prior_strength: number;
    quality_states: string[];
    frozen_evidence: {
      status: string;
      evidence_role: string;
      source_contract: string;
      live_equivalent: boolean;
      date_start: string;
      date_end: string;
      closed_count: number;
      win_count: number;
      win_rate_pct: number;
      average_net_return_pct: number;
      max_drawdown_pct: number;
      hard_loss_rate_pct: number;
      a_tier: {
        closed_count: number;
        win_count: number;
        win_rate_pct: number;
      };
      c_tier: {
        closed_count: number;
        win_count: number;
        win_rate_pct: number;
      };
      b_tier: {
        closed_count: number;
        win_count: number;
        win_rate_pct: number;
      };
      single_position: LimitUpGuideAccountEvidence;
      two_positions: LimitUpGuideAccountEvidence;
    };
    forward_status: {
      start_date: string;
      closed_count: number;
      win_count: number;
      win_rate_pct: number | null;
      minimum_closed_count: number;
      minimum_trade_days: number;
      status: string;
    };
  };
  verdict: {
    title: string;
    detail: string;
    execution_boundary: string;
  };
  selection_steps: Array<{
    order: number;
    title: string;
    rule: string;
    timing: string;
  }>;
  ranking: {
    first_board_primary: string;
    first_board_secondary: string;
    historical_win_rate_formula: string;
    history_cutoff: string;
    ranking_only: boolean;
    portfolio_gate: string;
  };
  field_groups: Array<{
    key: "intraday" | "prior" | "outcome" | string;
    label: string;
    selection_allowed: boolean;
    fields: string[];
  }>;
}
export type LimitUpLiveTraceState =
  | "radar_entered"
  | "concept_warming"
  | "recommended"
  | "approaching_trigger"
  | "trigger_ready"
  | "dropped_from_top5"
  | "source_missing"
  | "missed"
  | "sealed"
  | "resealed"
  | "failed"
  | "rejected"
  | "invalidated";

export interface LimitUpTriggerCheck {
  code: string;
  label: string;
  status: "passed" | "pending" | "failed" | "informational" | string;
  observed?: string | null;
  required?: string | null;
  evidence_time?: string | null;
}

export interface LimitUpPlanMetadata {
  source_trade_date?: string | null;
  target_session?: string | null;
  plan_phase?: "preliminary" | "final" | string;
}

export interface LimitUpExecutionSchedule {
  strategy_version: string;
  state: string;
  message: string;
  entry_allowed: boolean;
  target_at?: string | null;
  entry_windows: string[];
  exit_time: string;
  max_positions: number;
  target_position_pct: number;
  max_snapshot_age_seconds: number;
}

export interface LimitUpCoreQualityFilterMetadata {
  contract_version: string;
  first_board_minimum_d1_samples: number;
  first_board_minimum_combined_rate: number;
  minimum_prior_limit_count_126: number;
  maximum_prior_limit_count_126: number;
  a_tier_industry_turnover_ratio_5d: number;
  b_tier_is_actionable: boolean;
  b_first_board_minimum_time: string;
  c_tier_is_actionable: boolean;
  c_daily_limit: number;
  c_evidence_status: string;
  priority_rule: string;
}

interface LimitUpGuideAccountEvidence {
  closed_count: number;
  win_count: number;
  win_rate_pct: number;
  total_return_pct: number;
  max_drawdown_pct: number;
}

export interface LimitUpLiveSignal {
  vt_symbol: string;
  name: string;
  sector_name?: string | null;
  concept_id?: string | null;
  concept_name?: string | null;
  concept_state?: "unavailable" | "observe" | "warming" | "launch" | "ebb" | string;
  concept_launch_confirmed?: boolean;
  concept_strength_score?: number | null;
  concept_strength_rank?: number | null;
  concept_strength_percentile?: number | null;
  concept_leader_rank?: number | null;
  concept_coverage_ratio?: number | null;
  concept_strong_5_count?: number | null;
  concept_near_limit_count?: number | null;
  concept_sealed_count?: number | null;
  concept_failed_count?: number | null;
  concept_change_acceleration_3m?: number | null;
  concept_turnover_acceleration_3m?: number | null;
  concept_snapshot_age_seconds?: number | null;
  market_dragon_rank?: number | null;
  board_level: number;
  board_lane?: BoardLaneKey;
  first_board_route?: "divergence_repair" | "weak_market_theme_attack" | string | null;
  lane_favorable_factors?: string[];
  lane_blocker_reasons?: string[];
  lane_quality_tier?: "A" | "B" | null;
  lane_risk_count?: number;
  lane_risk_flags?: string[];
  lane_rank_score?: number | null;
  lane_support_score?: number | null;
  lane_entry_quality_score?: number | null;
  sector_route?: "realtime_industry" | "realtime_concept_launch" | string | null;
  portfolio_selected?: boolean;
  public_quality_status?: "rejected" | "actionable" | string;
  quality_priority_tier?: string | null;
  quality_win_probability?: number | null;
  quality_expected_d1_net_return_pct?: number | null;
  seal_gate_passed?: boolean | null;
  momentum_gate_passed?: boolean | null;
  premium_gate_passed?: boolean | null;
  validation_passed?: boolean;
  research_action?: LimitUpLiveAction;
  action: LimitUpLiveAction;
  entry_kind: string;
  trigger_price?: number | null;
  last_price?: number | null;
  limit_price?: number | null;
  change_pct?: number | null;
  reason: string;
  cancel_condition: string;
  execution_state?: "watch" | "waiting" | "actionable" | "cancelled" | string;
  signal_state?: "observing" | "concept_warming" | "approaching_trigger" | "pending_auction" | "trigger_ready" | "missed" | "rejected" | "invalidated" | string;
  blocking_scope?: LimitUpBlockingScope | string;
  pending_reasons?: string[];
  execution_permission?: "research_only" | string;
  scheduled_execution_version?: string;
  profitability_gate_version?: string;
  profitability_gate_applies?: boolean;
  profitability_gate_passed?: boolean;
  profitability_gate_reason?: string;
  profitability_gate_minimum_d1_samples?: number;
  profitability_gate_minimum_combined_rate?: number;
  profitability_gate_sample_count?: number | null;
  profitability_gate_combined_rate?: number | null;
  quality_gate_passed?: boolean;
  preparation_environment_passed?: boolean;
  execution_environment_passed?: boolean;
  failed_environment_checks?: string[];
  target_position_pct?: number;
  state?: "near_limit" | "sealed" | "resealed" | "failed" | string;
  distance_to_limit_pct?: number | null;
  seen_before_seal?: boolean;
  missed_preseal_entry?: boolean;
  strategy_name?: string;
  selection_reasons?: string[];
  trigger_checks?: LimitUpTriggerCheck[];
  buy_condition?: string;
  sell_condition?: string;
  buy_instruction?: string;
  sell_instruction?: string;
  cancel_checks?: string[];
  state_updated_at?: string;
  setup_tags?: string[];
  setup_confidence?: string | null;
  execution_confidence: string;
  sector_heat?: number | null;
  turnover_rate?: number | null;
  seal_amount?: number | null;
  warmup_group?: string | null;
  warmup_group_name?: string | null;
  warmup_state?: "cold" | "observe" | "warming" | "launch" | "crowded" | "ebb" | string;
  warmup_score?: number | null;
  warmup_confidence?: string | null;
  warmup_leader_rank?: number | null;
  warmup_main_net_inflow?: number | null;
  warmup_main_net_inflow_ratio?: number | null;
  warmup_execution_effect?: "none_research_only" | string;
  rotation_shadow_state?: "unavailable" | "rejected" | "watch" | "trigger" | "missed" | string;
  historical_evidence?: {
    status?: string;
    smoothed_win_rate: number | null;
    historical_win_rate?: number | null;
    historical_win_rate_method?: "seal_success_x_d1_close_net_profit" | string;
    d1_money_effect_win_rate?: number | null;
    d1_money_effect_average_return_pct?: number | null;
    d1_money_effect_sample_count?: number;
    seal_success_rate?: number | null;
    seal_sample_count?: number;
    stock_gene_status?: "ready" | "limited" | "insufficient" | string;
    stock_gene_history_window_days?: number;
    stock_gene_minimum_d1_samples?: number;
    stock_gene_sample_qualified?: boolean;
    stock_gene_touch_count?: number;
    stock_gene_seal_count?: number;
    stock_d1_win_count?: number;
    d1_exit_proxy?: "next_close" | string;
    average_return_pct?: number | null;
    hard_loss_rate?: number | null;
    seal_after_touch_rate?: number | null;
    effective_sample_count?: number;
    confidence?: string;
    tbox_score?: number;
  } | null;
  strategy_evidence?: {
    win_rate?: number | null;
    total_return_pct?: number | null;
    max_drawdown_pct?: number | null;
    trade_count?: number;
  };
}

export interface LimitUpSignalSnapshot {
  mode?: "live_snapshot" | "next_session_preliminary" | "next_session_final" | string;
  trade_date: string;
  source_trade_date?: string | null;
  target_session?: string | null;
  plan_phase?: "preliminary" | "final" | string;
  captured_at: string | null;
  session_stage?: string;
  source: string;
  market_context: {
    sealed_count?: number;
    failed_count?: number;
  };
  recommendations: {
    market_gate: {
      passed: boolean;
      repair_confirmed?: boolean;
      repair_state?: LimitUpMarketRepairState | string;
      repair_confirmed_at?: string | null;
      repair_evidence_at?: string | null;
      repair_revoked_reason?: string | null;
      reasons: string[];
    };
    lanes: Record<LimitUpLane, LimitUpLiveSignal[]>;
    actionable_recommendations?: LimitUpLiveSignal[];
    portfolio?: LimitUpLiveSignal[];
    watchlist?: LimitUpLiveSignal[];
    execution_schedule?: LimitUpExecutionSchedule;
    core_quality_filter?: LimitUpCoreQualityFilterMetadata;
    plan?: LimitUpPlanMetadata;
    board_lane_validations?: Partial<Record<BoardLaneKey, {
      passed: boolean;
      reason: string;
    }>>;
  };
  data_quality: {
    status: string;
    is_stale: boolean;
    snapshot_age_seconds?: number | null;
    rate_limit_status?: "normal" | "limited" | "degraded" | "unknown" | string;
    source_errors?: string[];
    concept_status?: string;
    concept_snapshot_age_seconds?: number | null;
    concept_quote_coverage_ratio?: number | null;
    concept_trigger_allowed?: boolean;
    concept_membership_snapshot_date?: string | null;
    plan?: LimitUpPlanMetadata;
  };
}

export interface LimitUpLiveTraceDates {
  status: "ready" | "empty" | string;
  dates: string[];
  latest: string | null;
}

export interface LimitUpLiveTraceItem {
  vt_symbol: string;
  name: string;
  board_lane: BoardLaneKey | null;
  board_level: number | null;
  first_seen_at: string;
  last_seen_at: string;
  highest_state: LimitUpLiveTraceState;
  final_state: LimitUpLiveTraceState;
  ever_recommended: boolean;
  ever_triggered: boolean;
  triggered_at: string | null;
  last_price: number | null;
  change_pct: number | null;
  distance_to_limit_pct: number | null;
  concept_name?: string | null;
  concept_state?: string | null;
  concept_strength_rank?: number | null;
  concept_leader_rank?: number | null;
  reason: string;
  event_count: number;
}

export interface LimitUpLiveTraceDay {
  status: "ready" | "not_found" | string;
  trade_date: string;
  snapshot_count?: number;
  scan_error_count?: number;
  lane_funnels?: Partial<Record<BoardLaneKey, LimitUpLiveTraceFunnel>>;
  items: LimitUpLiveTraceItem[];
}

export interface LimitUpLiveTraceFunnel {
  radar_count: number;
  warming_count: number;
  recommended_count: number;
  approaching_count: number;
  triggered_count: number;
  sealed_without_trigger_count: number;
  structural_rejected_count: number;
  market_blocked_count: number;
  dynamic_blocked_count: number;
  primary_blockers: Array<{
    code: string;
    label: string;
    count: number;
  }>;
}

export interface LimitUpLiveTraceEvent {
  event: LimitUpLiveTraceState;
  captured_at: string;
  triggered_at: string | null;
  vt_symbol: string | null;
  name: string | null;
  board_lane: BoardLaneKey | null;
  board_level: number | null;
  state: "near_limit" | "sealed" | "resealed" | "failed" | string | null;
  signal_state: string | null;
  action: LimitUpLiveAction | null;
  research_action: LimitUpLiveAction | null;
  last_price: number | null;
  change_pct: number | null;
  distance_to_limit_pct: number | null;
  concept_id?: string | null;
  concept_name?: string | null;
  concept_state?: string | null;
  concept_strength_score?: number | null;
  concept_strength_rank?: number | null;
  concept_strength_percentile?: number | null;
  concept_leader_rank?: number | null;
  concept_coverage_ratio?: number | null;
  concept_strong_5_count?: number | null;
  concept_near_limit_count?: number | null;
  concept_sealed_count?: number | null;
  concept_failed_count?: number | null;
  concept_change_acceleration_3m?: number | null;
  concept_turnover_acceleration_3m?: number | null;
  concept_snapshot_age_seconds?: number | null;
  sector_heat: number | null;
  sector_touch_count: number | null;
  sector_main_net_inflow: number | null;
  stock_main_net_inflow: number | null;
  turnover_rate: number | null;
  seal_amount: number | null;
  seal_amount_retention_ratio: number | null;
  seal_amount_change_pct: number | null;
  portfolio_selected: boolean;
  in_top5: boolean;
  market_gate_passed: boolean;
  market_gate_reasons: string[];
  market_repair_state: LimitUpMarketRepairState | string | null;
  market_repair_confirmed_at: string | null;
  blocking_scope: LimitUpBlockingScope | string | null;
  pending_reasons: string[];
  trigger_checks: LimitUpTriggerCheck[];
  blockers: string[];
  reason: string;
  data_quality_status: string | null;
}

export interface LimitUpLiveTraceSymbol {
  status: "ready" | "not_found" | string;
  trade_date: string;
  vt_symbol: string;
  events: LimitUpLiveTraceEvent[];
}

export interface LimitUpHistoryCoverage {
  reliable_start?: string | null;
  reliable_end?: string | null;
  reliable_trade_days?: number;
  persisted_start?: string | null;
  persisted_end?: string | null;
  persisted_days?: number;
  selected_start?: string | null;
  selected_end?: string | null;
  selected_trade_days?: number;
}

export interface LimitUpHistoryDates {
  status: string;
  strategy_version: string;
  dates: string[];
  start: string | null;
  end: string | null;
  latest: string | null;
  count: number;
  coverage: LimitUpHistoryCoverage;
}

export interface LimitUpHistoryRebuildStatus {
  status: "idle" | "building" | "ready" | "failed" | string;
  strategy_version: string;
  already_running?: boolean;
  started_at?: string | null;
  finished_at?: string | null;
  persisted_days?: number;
  start?: string | null;
  end?: string | null;
  coverage?: LimitUpHistoryCoverage;
  error?: {
    type?: string;
    message?: string;
  } | null;
}

export interface LimitUpEntrySummary {
  initial_cash?: number;
  final_equity?: number;
  signal_count: number;
  filled_count: number;
  fill_rate: number | null;
  trade_count: number;
  trade_day_count: number;
  average_trades_per_day: number;
  max_trades_per_day: number;
  max_industry_concentration_pct: number | null;
  win_count: number;
  win_rate: number | null;
  average_return_pct: number | null;
  median_return_pct: number | null;
  total_return_pct: number;
  max_drawdown_pct: number;
  hard_loss_count: number;
  hard_loss_rate: number | null;
  seal_rate: number | null;
  profit_factor?: number | null;
  buy_count?: number;
  open_position_count?: number;
  skipped_count?: number;
  skipped_reasons?: Record<string, number>;
  total_fees?: number;
  average_utilization_pct?: number;
  peak_utilization_pct?: number;
}

export interface LimitUpRecommendationQuality {
  mode: "independent_standard_slot_daily_equal_weight" | string;
  position_constraints_applied: false;
  standard_slot_cash: number;
  costs_included: boolean;
  daily_aggregation: "mean_net_return_by_exit_date" | string;
  summary: LimitUpEntrySummary;
  daily_results: LimitUpRecommendationDailyResult[];
  trades: LimitUpLaneLedgerTrade[];
  skipped_reasons: Record<string, number>;
}

export interface LimitUpRecommendationDailyResult {
  result_date: string;
  trade_count: number;
  daily_return_pct: number;
  equity: number;
  total_return_pct: number;
  drawdown_pct: number;
}

export interface LimitUpBacktestCoreQualityFilter extends LimitUpCoreQualityFilterMetadata {
  audit: {
    input_count: number;
    selected_count: number;
    excluded_count: number;
    reason_counts: Record<string, number>;
    tier_counts: Record<string, number>;
  };
  selected_summary: LimitUpEntrySummary;
  unfiltered_summary: LimitUpEntrySummary;
  selected_recommendation_quality: LimitUpRecommendationQuality;
  unfiltered_recommendation_quality: LimitUpRecommendationQuality;
  selected_phase_summaries: Record<string, LimitUpEntrySummary>;
  unfiltered_phase_summaries: Record<string, LimitUpEntrySummary>;
  selected_double_cost: LimitUpEntrySummary;
  unfiltered_double_cost: LimitUpEntrySummary;
  delta: {
    trade_count: number;
    win_rate_pct_points: number;
    total_return_pct_points: number;
    recommendation_win_rate_pct_points: number;
    recommendation_average_return_pct_points: number;
    recommendation_total_return_pct_points: number;
  };
}

export interface LimitUpLaneLedgerTrade {
  lane: BoardLaneKey;
  vt_symbol: string;
  name: string;
  industry_name?: string | null;
  signal_kind?: string | null;
  prior_limit_count_126?: number | null;
  prior_industry_turnover_ratio_5d?: number | null;
  quality_priority_tier?: "A_industry_expanding" | "C_capital_diffusion_rescue" | "B_recognition_only" | string | null;
  public_quality_contract_version?: string | null;
  public_quality_status?: "rejected" | "actionable" | string | null;
  public_quality_gate_passed?: boolean | null;
  public_quality_actionable?: boolean | null;
  public_quality_reason?: string | null;
  quality_tier_prior_win_probability?: number | null;
  quality_tier_prior_expected_d1_net_return_pct?: number | null;
  quality_tier_prior_sample_count?: number | null;
  quality_estimate_prior_strength?: number | null;
  quality_estimate_stock_sample_count?: number | null;
  quality_win_probability?: number | null;
  quality_expected_d1_net_return_pct?: number | null;
  stock_d1_sample_count?: number | null;
  stock_d1_win_rate?: number | null;
  stock_d1_average_return_pct?: number | null;
  profitability_gate_passed?: boolean | null;
  profitability_gate_reason?: string | null;
  recognition_gate_passed?: boolean | null;
  recognition_gate_reason?: string | null;
  core_quality_gate_passed?: boolean | null;
  core_quality_gate_reason?: string | null;
  buy_date: string;
  buy_time: string;
  buy_price: number | null;
  sell_date: string | null;
  sell_time: string | null;
  sell_price: number | null;
  return_pct: number | null;
  d1_outcome: string;
  d_board_status: "sealed" | "failed" | "no_limit";
  execution_confidence: string;
  two_to_three_quality_tier?: "A" | "B" | null;
  two_to_three_risk_count?: number | null;
  two_to_three_risk_flags?: string[];
  favorable_factors?: string[];
  setup_tags?: string[];
  setup_confidence?: string | null;
  dynamic_exit?: {
    mode?: "auction_exit" | "tail_exit" | string;
    reason?: string;
    policy_version?: string;
  };
  exit_price_source?: "minute_1430" | "daily_close_proxy" | string;
  exit_price_proxy?: boolean;
}

export interface LimitUpLaneValidation {
  passed: boolean;
  status: "validated" | "research_only" | string;
  checks: Array<{
    phase: HistoryValidationPhase | string;
    passed: boolean;
    trade_count: number;
    win_rate: number | null;
    total_return_pct: number | null;
    max_drawdown_pct: number | null;
  }>;
  reason?: string;
}

export interface LimitUpLaneLedger {
  status: string;
  trade_date: string;
  validation_phase?: HistoryValidationPhase | string;
  lane: BoardLaneKey | null;
  exit_mode: ExitMode;
  selected_count: number;
  trades: LimitUpLaneLedgerTrade[];
  observations?: LimitUpLaneLedgerTrade[];
  validation?: LimitUpLaneValidation | null;
}

export interface LimitUpDailyResult {
  result_date: string;
  trade_count: number;
  cash: number;
  market_value: number;
  total_equity: number;
  position_count: number;
  utilization_pct: number;
  daily_return_pct: number;
  equity: number;
  total_return_pct: number;
  drawdown_pct: number;
}

export interface LimitUpDrawdownReturnMetrics {
  count: number;
  win_count: number;
  win_rate: number | null;
  average_return_pct: number | null;
}

export interface LimitUpDrawdownTrade {
  vt_symbol: string;
  name: string;
  lane: BoardLaneKey;
  entry_date?: string | null;
  buy_date?: string | null;
  exit_date?: string | null;
  sell_date?: string | null;
  return_pct: number;
  net_pnl?: number | null;
  d_board_status?: "sealed" | "failed" | "no_limit" | string | null;
}

export interface LimitUpDrawdownDiagnostics {
  diagnostics_version: string;
  status: "ready" | "insufficient_data" | string;
  scope_explanation: string;
  longest_losing_streak: {
    count: number;
    start_date: string | null;
    end_date: string | null;
    first_entry_date: string | null;
    compound_return_pct: number;
    trades: LimitUpDrawdownTrade[];
  };
  maximum_drawdown_episode: {
    peak_date: string | null;
    trough_date: string | null;
    recovery_date: string | null;
    drawdown_pct: number;
    duration_trade_days: number;
    recovery_trade_days: number | null;
    principal_losses: LimitUpDrawdownTrade[];
  };
  execution_filter: {
    all: LimitUpDrawdownCohort;
    time_validation: LimitUpDrawdownCohort & {
      start: string;
      end: string;
    };
    latest_entry_month: LimitUpDrawdownCohort & {
      month: string | null;
    };
  };
  board_outcome_attribution: {
    actionability: "outcome_only_not_entry_filter" | string;
    note: string;
    groups: Array<LimitUpDrawdownReturnMetrics & {
      status: "sealed" | "failed" | "no_limit" | "unknown" | string;
      hard_loss_count: number;
    }>;
    hard_loss_count: number;
    hard_loss_failed_count: number;
    hard_loss_failed_share_pct: number | null;
  };
  recommendation_regime: {
    design_sample: LimitUpDrawdownReturnMetrics;
    time_validation: LimitUpDrawdownReturnMetrics;
    win_rate_delta_pct_points: number | null;
    average_return_delta_pct_points: number | null;
  };
  stock_gene_calibration: {
    field: string;
    selection_action: "do_not_add_static_threshold" | string;
    design_sample: LimitUpCalibrationBucket[];
    time_validation: LimitUpCalibrationBucket[];
    validation_monotonic: boolean | null;
  };
  causes: Array<{
    code: string;
    finding: string;
    implication: string;
  }>;
  exit_research: {
    research_version: string;
    status: "blocked_by_execution_price_coverage" | string;
    formal_strategy_changed: boolean;
    formal_policy: {
      policy_version: string;
      mode: string;
      decision_time: string;
      execution_time: string;
    };
    withdrawn_policy: {
      policy_version: string;
      status: "invalidated_same_price_decision_fill_lookahead" | string;
      invalidated_on: string;
      published_metrics_withdrawn: boolean;
      published_metrics: null;
      reason_codes: Array<{
        code: string;
        detail: string;
      }>;
    };
    d0_open_benchmark: {
      policy_version: string;
      status: "rejected_below_frozen_baseline" | string;
      rule: string;
      decision_time: string;
      price_source: string;
      baseline_summary: LimitUpEntrySummary;
      summary: LimitUpEntrySummary;
      return_delta_pct_points: number | null;
      win_rate_delta_pct_points: number | null;
    };
    precommitted_limit_research: {
      policy_version: string;
      status: "blocked_by_auction_fill_evidence" | string;
      rule: string;
      decision_time: string;
      selected_threshold_pct: null;
      coverage: {
        required_pair_count: number;
        snapshot_covered_pair_count: number;
        strict_complete_pair_count: number;
        unmatched_volume_pair_count: number;
        strict_coverage_pct: number;
        minimum_strict_coverage_pct: number;
        coverage_passed: boolean;
      };
      account_performance: null;
      account_performance_reason: string;
    };
    post_auction_research: {
      policy_version: string;
      status: "blocked_by_execution_price_coverage" | string;
      signal_time: string;
      execution_time: string;
      execution_price_proxy: string;
      metric_scope: "covered_baseline_trades_signal_diagnostic" | string;
      selected_threshold_pct: null;
      coverage: {
        required_pair_count: number;
        covered_pair_count: number;
        missing_pair_count: number;
        coverage_pct: number;
        minimum_coverage_pct: number;
        coverage_passed: boolean;
      };
      baseline_covered_sample: LimitUpDrawdownReturnMetrics;
      all_post_auction_exit_sample: LimitUpDrawdownReturnMetrics;
      threshold_rows: Array<{
        threshold_pct: number;
        trigger_count: number;
        sample_count: number;
        win_rate: number | null;
        average_return_pct: number | null;
        average_return_delta_vs_close_pct_points: number | null;
      }>;
      account_performance: null;
      account_performance_reason: string;
    };
  };
}

interface LimitUpDrawdownCohort {
  executed: LimitUpDrawdownReturnMetrics;
  skipped: LimitUpDrawdownReturnMetrics;
}

interface LimitUpCalibrationBucket {
  bucket: string;
  count: number;
  win_rate: number | null;
  average_return_pct: number | null;
}

export interface LimitUpLaneBacktest {
  status: string;
  mode: string;
  strategy_version: string;
  history_strategy_version?: string;
  lane: LimitUpBacktestScope;
  exit_mode: ExitMode;
  summary: LimitUpEntrySummary;
  execution_summary: LimitUpEntrySummary;
  signal_summary: LimitUpEntrySummary;
  recommendation_quality?: LimitUpRecommendationQuality;
  account_config: {
    initial_cash: number;
    max_positions: number;
    commission_rate: number;
    minimum_commission: number;
    stamp_tax_rate: number;
    transfer_fee_rate: number;
    slippage_bps: number;
    lot_size: number;
  };
  portfolio_policy: {
    included_lanes: BoardLaneKey[];
    excluded_lanes: BoardLaneKey[];
    selection_basis: string;
    candidate_source?: string;
    configured_lanes?: BoardLaneKey[];
    configuration_matches_gate?: boolean;
  };
  core_quality_filter?: LimitUpBacktestCoreQualityFilter;
  execution_schedule?: {
    entry_windows: string[];
    exit_time: string;
    exit_rule: string;
    target_position_pct: number;
    max_snapshot_age_seconds: number;
  };
  execution_comparability?: {
    status: "candidate_proxy_only" | "live_equivalent" | string;
    live_equivalent: boolean;
    candidate_proxy_signal_count: number;
    missing_evidence: string[];
    reason: string;
  };
  exit_summary: {
    mode: ExitMode;
    policy_version?: string;
    auction_exit_count?: number;
    tail_exit_count?: number;
    close_exit_count?: number;
    minute_1430_count?: number;
    daily_close_proxy_count?: number;
  };
  stress_tests?: {
    double_cost: LimitUpEntrySummary;
  };
  drawdown_diagnostics?: LimitUpDrawdownDiagnostics;
  position_sizing_audit?: {
    selected_max_positions: number;
    selected_by_development: number;
    selection_matches_frozen_policy: boolean;
    selection_rule: string;
    selection_cutoff_exclusive: string;
    drawdown_floor_pct: number;
    target_position_pct: number;
    development_sample: {
      signal_count: number;
      signal_day_count: number;
      start: string | null;
      end: string | null;
    };
    validation_sample: {
      signal_count: number;
      signal_day_count: number;
      start: string | null;
      end: string | null;
    };
    development_variants: Record<string, LimitUpEntrySummary>;
    validation_variants: Record<string, LimitUpEntrySummary>;
    variants: Record<string, LimitUpEntrySummary>;
  };
  relay_comparison?: {
    selected_variant: string;
    configured_variant?: string | null;
    gate_selected_variant?: string | null;
    configuration_matches_gate: boolean;
    variants: Record<string, {
      lanes: BoardLaneKey[];
      passed: boolean;
      gate_checks: Record<string, boolean>;
      summary: LimitUpEntrySummary;
      phase_summaries: Record<string, LimitUpEntrySummary>;
      double_cost: LimitUpEntrySummary;
    }>;
    trigger_coverage: {
      by_lane: Partial<Record<BoardLaneKey, Record<string, number>>>;
      total: Record<string, number>;
    };
  };
  daily_results: LimitUpDailyResult[];
  trades: Array<LimitUpLaneLedgerTrade & {
    signal_date: string;
    entry_date: string;
    exit_date: string;
    entry_price: number;
    exit_price: number;
    volume: number;
    buy_amount: number;
    buy_fee: number;
    sell_amount: number;
    sell_fee: number;
    total_fee: number;
    net_pnl: number;
    exit_reason: string;
  }>;
  skipped_orders: Array<{
    order_id: string;
    vt_symbol: string;
    name: string;
    lane: BoardLaneKey;
    trade_date: string;
    trade_time: string;
    reason: string;
    cash_after: number;
    buy_price?: number | null;
    result_date?: string | null;
    d1_close_price?: number | null;
    d1_return_pct?: number | null;
    d_board_status?: "sealed" | "failed" | "no_limit" | null;
    is_win?: boolean | null;
  }>;
  open_positions: Array<{
    vt_symbol: string;
    name: string;
    lane: BoardLaneKey;
    buy_date: string;
    buy_price: number;
    volume: number;
    last_close: number;
    market_value: number;
    unrealized_pnl: number;
  }>;
  validation: LimitUpLaneValidation;
  simulation_eligible: boolean;
  coverage: LimitUpHistoryCoverage & {
    intraday_path_trade_days?: number;
    exit_price_request_count?: number;
    daily_close_count?: number;
    daily_close_missing_count?: number;
    minute_1430_count?: number;
    daily_close_proxy_count?: number;
    exit_price_missing_count?: number;
  };
}

export interface LimitUpWalkForwardModelReport {
  status: string;
  model_version: string;
  history_strategy_version: string;
  entry_mode: EntryMode;
  board_lane?: BoardLaneKey | null;
  exit_mode: ExitMode;
  model_contract: {
    min_training_samples: number;
  };
  coverage: LimitUpHistoryCoverage & {
    closed_candidate_count?: number;
    fitted_windows?: number;
  };
  windows: Array<{
    training_samples: number;
  }>;
  selected_candidates: Array<Record<string, unknown>>;
}

export function fetchLimitUpLive(): Promise<LimitUpSignalSnapshot> {
  return apiClient.get<LimitUpSignalSnapshot>("/limit-up/live");
}

export function fetchLimitUpStrategyGuide(): Promise<LimitUpStrategyGuide> {
  return apiClient.get<LimitUpStrategyGuide>("/limit-up/strategy-guide");
}

export function fetchLimitUpLiveTraceDates(): Promise<LimitUpLiveTraceDates> {
  return apiClient.get<LimitUpLiveTraceDates>("/limit-up/live-traces/dates");
}

export function fetchLimitUpLiveTraceDay(tradeDate: string): Promise<LimitUpLiveTraceDay> {
  const query = new URLSearchParams({ date: tradeDate });
  return apiClient.get<LimitUpLiveTraceDay>(`/limit-up/live-traces/day?${query.toString()}`);
}

export function fetchLimitUpLiveTraceSymbol(params: {
  date: string;
  vtSymbol: string;
}): Promise<LimitUpLiveTraceSymbol> {
  const query = new URLSearchParams({
    date: params.date,
    vt_symbol: params.vtSymbol,
  });
  return apiClient.get<LimitUpLiveTraceSymbol>(`/limit-up/live-traces/symbol?${query.toString()}`);
}

export function refreshLimitUpLive(): Promise<LimitUpSignalSnapshot> {
  return apiClient.post<LimitUpSignalSnapshot>("/limit-up/live/refresh");
}

export function fetchLimitUpHistoryStatus(): Promise<LimitUpHistoryRebuildStatus> {
  return apiClient.get<LimitUpHistoryRebuildStatus>("/limit-up/history/status");
}

export async function startLimitUpHistoryRebuild(): Promise<LimitUpHistoryRebuildStatus> {
  try {
    return await apiClient.post<LimitUpHistoryRebuildStatus>("/limit-up/history/rebuild");
  } catch (error) {
    if (error instanceof ApiClientError && error.code === "HISTORY_REBUILD_RUNNING") {
      const status = await fetchLimitUpHistoryStatus();
      return { ...status, already_running: true };
    }
    throw error;
  }
}

export function fetchLimitUpHistoryDates(): Promise<LimitUpHistoryDates> {
  return apiClient.get<LimitUpHistoryDates>("/limit-up/history/dates");
}

export function fetchLimitUpHistoryLedger(params: {
  date: string;
  lane?: BoardLaneKey;
}): Promise<LimitUpLaneLedger> {
  const query = new URLSearchParams({ date: params.date });
  if (params.lane) query.set("lane", params.lane);
  return apiClient.get<LimitUpLaneLedger>(`/limit-up/history/ledger?${query.toString()}`);
}

export function fetchLimitUpLaneBacktest(params: {
  start?: string;
  end?: string;
  lane: LimitUpBacktestScope;
}): Promise<LimitUpLaneBacktest> {
  const query = new URLSearchParams({ lane: params.lane });
  if (params.start) query.set("start", params.start);
  if (params.end) query.set("end", params.end);
  return apiClient.get<LimitUpLaneBacktest>(`/limit-up/history/backtest?${query.toString()}`);
}

export function fetchLimitUpHistoryModelReport(params: {
  start?: string;
  end?: string;
  entryMode: EntryMode;
  exitMode: ExitMode;
  lane?: BoardLaneKey;
}): Promise<LimitUpWalkForwardModelReport> {
  const query = new URLSearchParams({
    entry_mode: params.entryMode,
    exit_mode: params.exitMode,
  });
  if (params.start) query.set("start", params.start);
  if (params.end) query.set("end", params.end);
  if (params.lane) query.set("lane", params.lane);
  return apiClient.get<LimitUpWalkForwardModelReport>(`/limit-up/history/model-report?${query.toString()}`);
}
