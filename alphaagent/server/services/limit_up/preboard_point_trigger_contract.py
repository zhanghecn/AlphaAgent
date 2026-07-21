"""Frozen contract for the forward-only pre-board point trigger study."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time


CONTRACT_VERSION = "limit-up-preboard-point-trigger-v9"
ELIGIBLE_AFTER = date(2026, 7, 20)
FIT_DAY_COUNT = 40
CALIBRATION_DAY_COUNT = 15
VALIDATION_DAY_COUNT = 60
MODEL_FREEZE_DAY_COUNT = FIT_DAY_COUNT + CALIBRATION_DAY_COUNT
ENTRY_WINDOWS = (
    (time(10, 0), time(11, 30)),
    (time(13, 0), time(14, 30)),
)
SEQUENCE_HORIZONS_SECONDS = (20, 60, 180)
MINIMUM_GAIN_PCT = 3.0
MINIMUM_HISTORY_SAMPLE_COUNT = 5
MINIMUM_HISTORICAL_COMBINED_RATE = 30.0
MAXIMUM_QUOTE_AGE_SECONDS = 60.0
MAXIMUM_QUOTE_ENRICHMENT_AGE_SECONDS = 20.0
MAXIMUM_SEQUENCE_ANCHOR_LAG_SECONDS = 20.0
MAXIMUM_LABEL_GAP_SECONDS = 20.0
MINIMUM_LABEL_KNOWN_ELIGIBLE_HORIZON_RATIO = 0.98
MINIMUM_FORMAL_TWO_SLOT_EVIDENCE_RATIO = 1.0
MAXIMUM_CANDIDATE_AGE_SECONDS = 180.0
MAXIMUM_VISIBLE_FRAME_COUNT = 10
LIVE_CAUSAL_LOOKBACK_SECONDS = 220
TRANSIENT_LANE_BLOCKER_CODES = frozenset(
    {
        "first_touch_too_early",
        "industry_heat_unavailable",
        "intraday_support_unavailable",
        "intraday_support_breakdown",
        "first_board_local_setup_unconfirmed",
        "intraday_support_out_of_range",
        "auction_gap_out_of_range",
    }
)

FRAME_FEATURE_FIELDS = (
    "market_candidate_count_total",
    "market_candidate_count_3_5",
    "market_candidate_count_5_7",
    "market_candidate_count_7_9_5",
    "market_new_candidate_count_20s",
    "market_upward_candidate_ratio_20s",
    "market_gain_max_pct",
    "market_gain_p75_pct",
    "market_near_limit_candidate_count",
    "market_formal_event_count_20s",
    "market_formal_event_count_60s",
    "market_formal_event_count_180s",
    "market_concept_concentration_ratio",
    "market_positive_concept_acceleration_ratio",
    "market_same_day_positive_flow_ratio",
    "market_timing_gold_active",
    "market_timing_silver_active",
    "market_timing_fading",
    "market_timing_stale",
    "market_timing_none",
)

IDENTITY_FEATURE_FIELDS = (
    "candidate_gain_pct",
    "candidate_distance_to_limit_pct",
    "candidate_lane_rank_score",
    "candidate_support_score",
    "candidate_support_missing",
    "candidate_entry_quality_score",
    "candidate_entry_quality_missing",
    "candidate_market_blocked",
    "candidate_dynamic_blocked",
    "candidate_soft_structural_blocked",
    "candidate_transient_lane_blocker_count_log1p",
    "candidate_history_sample_count_log1p",
    "candidate_historical_combined_rate",
    "candidate_age_seconds_log1p",
    "candidate_visible_frame_count_log1p",
    "candidate_gain_slope_20s",
    "candidate_gain_slope_20s_missing",
    "candidate_gain_slope_60s",
    "candidate_gain_slope_60s_missing",
    "candidate_gain_slope_180s",
    "candidate_gain_slope_180s_missing",
    "candidate_gain_acceleration_20s",
    "candidate_gain_acceleration_20s_missing",
    "candidate_gain_acceleration_60s",
    "candidate_gain_acceleration_60s_missing",
    "candidate_gain_acceleration_180s",
    "candidate_gain_acceleration_180s_missing",
    "candidate_max_drawdown_20s",
    "candidate_max_drawdown_60s",
    "candidate_max_drawdown_180s",
    "candidate_recovery_20s",
    "candidate_recovery_60s",
    "candidate_recovery_180s",
    "candidate_volume_delta_rate_20s",
    "candidate_volume_delta_rate_20s_missing",
    "candidate_volume_delta_rate_60s",
    "candidate_volume_delta_rate_60s_missing",
    "candidate_turnover_delta_rate_20s",
    "candidate_turnover_delta_rate_20s_missing",
    "candidate_turnover_delta_rate_60s",
    "candidate_turnover_delta_rate_60s_missing",
    "candidate_rank_delta_20s",
    "candidate_rank_delta_20s_missing",
    "candidate_rank_delta_60s",
    "candidate_rank_delta_60s_missing",
    "candidate_quote_speed",
    "candidate_quote_speed_missing",
    "candidate_quote_amplitude_pct",
    "candidate_quote_amplitude_missing",
    "candidate_quote_main_net_inflow_ratio",
    "candidate_quote_main_net_inflow_missing",
    "candidate_quote_main_net_inflow_ratio_delta_20s",
    "candidate_quote_main_net_inflow_ratio_delta_20s_missing",
    "candidate_quote_main_net_inflow_ratio_delta_60s",
    "candidate_quote_main_net_inflow_ratio_delta_60s_missing",
    "candidate_concept_strength_score",
    "candidate_concept_leader_rank",
    "candidate_concept_strong_5_count_log1p",
    "candidate_concept_change_acceleration_1m",
    "candidate_concept_change_acceleration_3m",
    "candidate_concept_change_acceleration_5m",
    "candidate_concept_turnover_acceleration_1m",
    "candidate_concept_turnover_acceleration_3m",
    "candidate_concept_turnover_acceleration_5m",
    "candidate_concept_missing",
    "candidate_concept_acceleration_missing",
    "candidate_sector_main_net_inflow_ratio",
    "candidate_sector_flow_missing",
    "candidate_stock_main_net_inflow_ratio",
    "candidate_stock_flow_missing",
)


@dataclass(frozen=True)
class PointTriggerDayAudit:
    contract_version: str
    trade_date: date | None
    status: str
    is_complete: bool
    eligible_for_model: bool
    reason_codes: tuple[str, ...]
    frame_count: int
    observation_count: int
    metrics: dict[str, float | int | None]
    capture_runtime_fingerprint: str | None = None
    formal_baseline_order_projection_complete: bool = False
    formal_baseline_orders: tuple[dict[str, object], ...] = ()
