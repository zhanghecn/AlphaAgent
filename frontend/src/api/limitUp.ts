import { apiClient } from "./client";

export type ExitMode = "dynamic" | "next_open" | "next_close";
export type EntryMode = "auction" | "sweep" | "tail" | "next_auction";
export type BoardLaneKey = "first_board" | "one_to_two" | "two_to_three" | "high_board";
export type LimitUpBacktestScope = "portfolio" | BoardLaneKey;
export type HistoryValidationPhase = "warmup" | "expanding_oos" | "locked_holdout";
export type LimitUpLiveAction = "buy_now" | "observe" | "wait_tail" | "next_auction" | "pass";
export type LimitUpLane = "now" | "tail" | "next_auction";

export interface LimitUpTriggerCheck {
  code: string;
  label: string;
  status: "passed" | "pending" | "failed" | string;
  observed?: string | null;
  required?: string | null;
  evidence_time?: string | null;
}

export interface LimitUpPlanMetadata {
  source_trade_date?: string | null;
  target_session?: string | null;
  plan_phase?: "preliminary" | "final" | string;
}

export interface LimitUpLiveSignal {
  vt_symbol: string;
  name: string;
  sector_name?: string | null;
  market_dragon_rank?: number | null;
  board_level: number;
  board_lane?: BoardLaneKey;
  lane_favorable_factors?: string[];
  lane_blocker_reasons?: string[];
  lane_quality_tier?: "A" | "B" | null;
  lane_risk_count?: number;
  lane_risk_flags?: string[];
  lane_rank_score?: number | null;
  portfolio_selected?: boolean;
  seal_gate_passed?: boolean | null;
  premium_gate_passed?: boolean | null;
  validation_passed?: boolean;
  research_action?: LimitUpLiveAction;
  action: LimitUpLiveAction;
  entry_kind: string;
  trigger_price?: number | null;
  reason: string;
  cancel_condition: string;
  execution_state?: "watch" | "waiting" | "actionable" | "cancelled" | string;
  signal_state?: "observing" | "approaching_trigger" | "pending_auction" | "trigger_ready" | "missed" | "rejected" | "invalidated" | string;
  execution_permission?: "research_only" | string;
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
  historical_evidence?: {
    status?: string;
    smoothed_win_rate: number | null;
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
  source: string;
  market_context: {
    sealed_count?: number;
    failed_count?: number;
  };
  recommendations: {
    market_gate: {
      passed: boolean;
      repair_confirmed?: boolean;
      reasons: string[];
    };
    lanes: Record<LimitUpLane, LimitUpLiveSignal[]>;
    portfolio?: LimitUpLiveSignal[];
    watchlist?: LimitUpLiveSignal[];
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
    plan?: LimitUpPlanMetadata;
  };
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

export interface LimitUpLaneLedgerTrade {
  lane: BoardLaneKey;
  vt_symbol: string;
  name: string;
  industry_name?: string | null;
  signal_kind?: string | null;
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

export interface LimitUpLaneBacktest {
  status: string;
  mode: string;
  strategy_version: string;
  lane: LimitUpBacktestScope;
  exit_mode: ExitMode;
  summary: LimitUpEntrySummary;
  execution_summary: LimitUpEntrySummary;
  signal_summary: LimitUpEntrySummary;
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
  };
  exit_summary: {
    mode: ExitMode;
    policy_version?: string;
    auction_exit_count: number;
    tail_exit_count: number;
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
  };
}

export interface LimitUpSectorWarmupComparison {
  variant: string;
  label: string;
  formal: boolean;
  trade_count: number;
  trade_day_count: number;
  win_rate: number | null;
  average_net_return_pct: number | null;
  total_return_pct: number;
  max_drawdown_pct: number;
  hard_loss_rate: number | null;
  seal_rate: number | null;
  initial_cash: number;
  final_equity: number;
  start: string | null;
  end: string | null;
  delta: null | {
    trade_count: number;
    win_rate: number | null;
    average_net_return_pct: number | null;
    total_return_pct: number | null;
    max_drawdown_pct: number | null;
  };
}

export interface LimitUpSectorWarmupReport {
  status: string;
  research_version: string;
  research_status: "formal" | "proxy_only" | string;
  simulation_eligible: boolean;
  scope: "first_board";
  primary_exit: "next_open";
  initial_cash: number;
  round_trip_cost_pct: number;
  forward_start_date: string;
  event_start: string | null;
  event_end: string | null;
  candidate_funnel: {
    raw_first_board: number;
    eligible: number;
    closed: number;
    warmup_confirmed: number;
  };
  comparisons: LimitUpSectorWarmupComparison[];
  phase_summaries: Record<string, LimitUpSectorWarmupComparison[]>;
  acceptance: {
    passed: boolean;
    evaluated_variant: string;
    checks: Array<{ code: string; passed: boolean; label: string }>;
  };
  data_coverage: {
    concept_daily_bar_days?: number;
    membership_snapshot_days?: number;
    intraday_fund_snapshot_days?: number;
    signal_time_feature_linkage_ready?: boolean;
    [key: string]: string | number | boolean | null | undefined;
  };
  formal_concept_backtest_ready: boolean;
  lane_isolation: {
    passed: boolean;
    affected_lanes: BoardLaneKey[];
    unchanged_lanes: BoardLaneKey[];
  };
  limitations: string[];
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

export function refreshLimitUpLive(): Promise<LimitUpSignalSnapshot> {
  return apiClient.post<LimitUpSignalSnapshot>("/limit-up/live/refresh");
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

export function fetchLimitUpSectorWarmupResearch(params: {
  start?: string;
  end?: string;
}): Promise<LimitUpSectorWarmupReport> {
  const query = new URLSearchParams();
  if (params.start) query.set("start", params.start);
  if (params.end) query.set("end", params.end);
  const suffix = query.size ? `?${query.toString()}` : "";
  return apiClient.get<LimitUpSectorWarmupReport>(`/limit-up/history/sector-warmup${suffix}`);
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
