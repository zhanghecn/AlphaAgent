"""Shared data structures for AlphaAgent backtests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from alphaagent.market.boards import DEFAULT_QUANT_INCLUDED_BOARDS, normalize_included_boards
from alphaagent.server.services.backtest import execution_models
from alphaagent.server.services.quant.factors import STRATEGY_ID


@dataclass
class BacktestParams:
    strategy: str = STRATEGY_ID
    start: date = date(2020, 1, 1)
    end: date | None = None
    initial_cash: float = 1_000_000
    max_positions: int = 10
    max_position_pct: float = 0.125
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    slippage_bps: float = 10
    stop_loss_pct: float = 0.08  # 0.07->0.08 (2026-06-24): CPCV 验证 PBO=0.33 稳健，0.07 在波动市误杀 55%（止损后5日回升），0.08 扛过回升
    take_profit_pct: float = 0.18
    trailing_stop_pct: float = 0.08
    time_stop_days: int = 15
    candidate_limit: int = 20
    max_symbols: int = 5000
    min_entry_score: float = 68.0
    strict_entry: bool = True
    execution_model: str = "legacy_next_open"
    intraday_entry: bool = False
    minute_entry_required: bool = False
    minute_interval: str = "1m"
    tail_entry_start: str = "14:30"
    tail_entry_end: str = "14:30"
    tail_entry_ma5_tolerance_pct: float = 1.5
    enable_signal_rotation: bool = True
    rotation_min_score: float = 98.0
    rotation_min_score_gap: float = 8.0
    rotation_max_holding_return_pct: float = 3.0
    rotation_min_holding_days: int = 3
    require_low_suction_launch_confirmation: bool = False
    exclude_repeated_dragon_pullback: bool = False
    require_low_suction_launch_for_low_suction_context: bool = False
    require_balanced_low_suction_launch_quality: bool = False
    enable_entry_launch_quality_score: bool = False
    enable_entry_launch_risk_penalty: bool = False
    enable_low_suction_market_risk_penalty: bool = False
    enable_market_adaptive_setup_weighting: bool = False
    enable_low_suction_first_lift_bonus: bool = False
    enable_low_suction_lifecycle_ranking: bool = False
    enable_low_suction_buildup_quality_lane: bool = False
    enable_candidate_tail_risk_penalty: bool = False
    enable_mainline_momentum_lane: bool = False
    enable_mainline_momentum_risk_control: bool = False
    enable_mainline_momentum_hard_filter: bool = False
    enable_surge_quality_lane: bool = False
    enable_top20_day_quality_gate: bool = False
    enable_weekly_top_fractal_relief: bool = False
    enable_pure_loss_weak_bucket_penalty: bool = False
    enable_selective_setup_quality_lane: bool = False
    enable_high_risk_d2_follow_through_entry: bool = False
    enable_dynamic_failed_launch_exit_stop: bool = False
    enable_dynamic_failed_launch_replacement_quality_gate: bool = False
    enable_failed_launch_exit_stop: bool = False
    enable_contextual_failed_launch_exit_stop: bool = False
    enable_mid_profit_giveback_stop: bool = False
    mid_profit_giveback_min_high_gain_pct: float = 0.10
    mid_profit_giveback_max_current_gain_pct: float = 0.04
    mid_profit_giveback_drawdown_pct: float = 0.07
    enable_contextual_support_reclaim_delay: bool = False
    support_reclaim_delay_max_warning_level: int = 2
    support_reclaim_delay_max_replacement_score_gap: float = 6.0
    support_reclaim_delay_min_sell_day_range_pct: float = 5.0
    enable_contextual_peak_giveback_stop: bool = False
    peak_giveback_min_high_gain_pct: float = 0.12
    peak_giveback_max_current_gain_pct: float = 0.03
    peak_giveback_drawdown_pct: float = 0.07
    peak_giveback_min_holding_days: int = 5
    enable_low_suction_false_launch_watch_gate: bool = False
    low_suction_false_launch_min_days: int = 3
    low_suction_false_launch_min_warning_level: int = 2
    low_suction_false_launch_max_recovery_level: int = 1
    enable_missed_candidate_quality_rotation: bool = False
    missed_rotation_min_score: float = 98.0
    missed_rotation_min_score_gap: float = 10.0
    missed_rotation_max_held_return_pct: float = 1.0
    missed_rotation_min_held_days: int = 4
    enable_high_quality_trend_rotation: bool = False
    high_quality_rotation_min_score: float = 96.0
    high_quality_rotation_max_rank: int = 10
    high_quality_rotation_min_score_gap: float = 8.0
    high_quality_rotation_max_held_return_pct: float = 0.0
    high_quality_rotation_min_held_days: int = 4
    enable_weak_holding_quality_rotation: bool = False
    weak_holding_rotation_min_score: float = 96.0
    weak_holding_rotation_max_rank: int = 20
    weak_holding_rotation_min_score_gap: float = 6.0
    weak_holding_rotation_max_held_return_pct: float = -5.0
    weak_holding_rotation_min_held_days: int = 3
    weak_holding_rotation_max_ma_convergence_pct: float = 5.0
    weak_holding_rotation_min_low_suction_days: int = 3
    enable_protected_weak_holding_rotation: bool = False
    enable_low_suction_pullback_entry: bool = False
    low_suction_pullback_entry_max_wait_days: int = 3
    low_suction_pullback_entry_buffer_pct: float = 0.01
    low_suction_pullback_entry_reserve_slot: bool = True
    enable_low_suction_trigger_day_confirmation: bool = False
    enable_low_suction_confirmed_branch_exit: bool = False
    low_suction_failed_follow_d3_low_pct: float = -8.0
    low_suction_failed_follow_d3_high_pct: float = 2.0
    low_suction_failed_follow_d3_close_pct: float = -3.0
    low_suction_opened_space_d5_high_pct: float = 6.0
    low_suction_opened_space_d5_low_pct: float = -5.0
    enable_low_suction_branch_replacement_quality_gate: bool = False
    low_suction_branch_replacement_gate_wait_days: int = 3
    low_suction_branch_replacement_min_score: float = 98.0
    low_suction_branch_replacement_max_market_warning_level: int = 1
    low_suction_branch_replacement_max_low_suction_ma_convergence_pct: float = 7.0
    low_suction_branch_replacement_max_dragon_ma_convergence_pct: float = 12.0
    enable_low_suction_branch_replacement_strict_setup_gate: bool = False
    setup_family_filter: str = ""
    enable_phase_aware_setup_selector: bool = False
    enable_phase_replacement_quality: bool = False
    exclude_from_product_baseline: bool = False
    persist: bool = False
    symbols: list[str] | None = None
    included_boards: tuple[str, ...] = DEFAULT_QUANT_INCLUDED_BOARDS
    reuse_signal_cache: bool = False

    def __post_init__(self) -> None:
        self.included_boards = normalize_included_boards(self.included_boards)
        self.execution_model = execution_models.normalize_execution_model(self.execution_model)
        self.minute_interval = execution_models.normalize_backtest_minute_interval(self.minute_interval)
        if self.execution_model == "strict_1430":
            self.intraday_entry = True
            self.minute_entry_required = True


@dataclass(frozen=True)
class MinuteBar:
    bar_time: datetime
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None = None
    turnover: float | None = None


@dataclass
class Position:
    vt_symbol: str
    name: str | None
    volume: int
    cost_price: float
    entry_date: date
    highest_price: float
    reason: dict[str, Any]
    last_price: float | None = None
    visible_holding_bars: int = 0
    lowest_price: float | None = None
    low_suction_confirmed_branch: str | None = None
    low_suction_confirmed_branch_raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trade:
    trade_date: date
    vt_symbol: str
    side: str
    price: float
    volume: int
    amount: float
    fee: float
    pnl: float | None = None
    reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoreContext:
    financial_rows_by_symbol: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
