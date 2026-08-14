"""Read-only discovery for the daily low-suction research case archive.

Only named rules derived from the user's documented research cases participate
in the active manifest. The module remains causal, read-only, and does not
fetch data or write strategy/product records.
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import fmean, median
from typing import Any

from .daily_factor_comprehensive_study import (
    EXIT_PROBES,
    MAX_EXIT_HOLDING_SESSIONS,
    PERSONAL_CASES,
    evaluate_close_exit_probe,
)
from .daily_factor_research import (
    DailyFactorInputError,
    build_daily_features,
    d1_close_label_status,
    is_main_board_close_within_price_limit,
    is_main_board_limit_up_touched,
    split_market_calendar,
)


SETUP_TYPES = ("oversold_rebound", "trend_pullback")
SEGMENTS = ("development", "validation", "holdout")
RECENT_CROSS_LOOKBACK = 5
PROCESS_CROSS_LOOKBACK = 15
TRANSITION_CROSS_LOOKBACK = 7
NEAR_MA_DISTANCE_PCT = 0.5
RECENT_CROSS_MAX_ABOVE_PCT = 1.5
OVERSOLD_PROCESS_DAILY_RETURN_MIN_PCT = -10.0
OVERSOLD_PROCESS_PULLBACK_LOOKBACK = 6
OVERSOLD_PROCESS_PULLBACK_MIN_PCT = -3.0
LONG_BEAR_ALIGNMENT_MIN_SESSIONS = 10
MA_CONTACT_DISTANCE_PCT = 0.5
TRANSITION_MA20_MA30_CONTACT_PCT = 0.25
SUPPORT_BROAD_LOW_MIN_PCT = -5.0
SUPPORT_BROAD_CLOSE_MIN_PCT = -2.0
SUPPORT_CLOSE_REACTION_MIN_PCT = 0.3
TURNOVER_RATE_LOW_MAX_PCT = 3.0
CAPITULATION_TURNOVER_MAX_PCT = 5.0
TREND_GENTLE_SLOPE_MAX_PCT = 2.0
EARLY_TREND_ALIGNMENT_MIN_SESSIONS = 3
EARLY_TREND_ALIGNMENT_MAX_SESSIONS = 20
MA10_MA30_CONVERGENCE_LOOKBACK = 5
MA10_MA30_CONVERGENCE_MIN_PCT = 0.5
MA10_MA30_FAST_CONVERGENCE_MIN_PCT = 5.0
PROCESS_VOLUME_CHANGE_PCT = 10.0
MA5_EXTENSION_MIN_PCT = 1.5
TREND_CANDLE_QUIET_RANGE_MAX_PCT = 5.0
TREND_DIST_EXCESS_MAX_PCT = 2.0
TREND_REBUILD_PRIOR_LOOKBACK = 10
TREND_REBUILD_MIN_DISORDERED_SESSIONS = 3
YANG_WRAP_STABLE_BASE_LOW_MA_MAX_PCT = 1.5
YANG_WRAP_STABLE_BASE_VOLUME_END_TO_PEAK_MAX = 0.55
POST_WRAP_UPPER_BAND_DISTANCE_MAX_PCT = 1.5
POST_WRAP_CONFIRMATION_TURNOVER_MIN_PCT = 1.5
POST_WRAP_CONFIRMATION_TURNOVER_MAX_PCT = 8.0
VOLUME_MONOTONE_6D_MIN_RATIO = 0.8
MIN_SELECTION_SAMPLES = 30
MIN_SELECTION_CANDIDATE_DAYS = 10
MIN_QUALIFICATION_SAMPLES = 30
MIN_QUALIFICATION_CANDIDATE_DAYS = 10
MAX_WORST_OBSERVATIONS = 50
MAX_MARKDOWN_WORST_ROWS = 30
POST_LIMIT_UP_HOLDING_SESSIONS = (1, 2, 3)
DEVELOPMENT_SELECTION_MODE = "development_window"
FROZEN_SELECTION_MODE = "frozen_recent_half_year"
OVERSOLD_TO_TREND_RULE_KEY = (
    "oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30"
)
RESEARCH_THREE_MA_WRAP_RULE_KEY = "research_oversold_three_ma_wrap_stable_base"
POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY = (
    "post_wrap_upper_band_reclaim_confirmation"
)
MA10_MA20_PRE_CROSS_RULE_KEY = (
    "ma10_ma20_contact_pre_cross_positive_volume_expand"
)
FIRST_LEG_TWO_MA_WRAP_RULE_KEY = "first_leg_two_ma_body_wrap_before_ma30"
STAGED_MA10_SUPPORT_RULE_KEY = (
    "staged_ma10_support_before_ma30_convergence_shrink"
)
ATTACK_BODY_HOLD_RULE_KEY = (
    "attack_body_hold_after_ma10_ma20_cross_before_ma30"
)
STAGED_MA30_CONVERGENCE_RULE_KEYS = frozenset(
    {STAGED_MA10_SUPPORT_RULE_KEY}
)
ATTACK_BODY_MIN_PCT = 3.0
ATTACK_BODY_HOLD_DAILY_RETURN_MIN_PCT = -3.0
ATTACK_BODY_HOLD_DAILY_RETURN_MAX_PCT = 0.5
ATTACK_BODY_HOLD_VOLUME_MAX_RATIO = 0.8
FIRST_LEG_TWO_MA_WRAP_EFFICIENCY_5D_MIN = 0.156084
FIRST_LEG_TWO_MA_WRAP_GAP_NARROWING_3D_MIN_PCT = 1.32474
FIRST_LEG_TWO_MA_WRAP_SETTLED_BASE_PHASES = frozenset(
    {"gradual_support_ladder", "release_retest_base"}
)
FIRST_LEG_TWO_MA_WRAP_CLOSE_TO_MA10_MAX_PCT = 3.0
FIRST_LEG_TWO_MA_WRAP_DAILY_RETURN_MAX_PCT = 5.0
FIRST_LEG_TWO_MA_WRAP_GAP_NARROWING_3D_MAX_PCT = 4.0
FIRST_LEG_TWO_MA_WRAP_PIVOT_AGE_MIN_SESSIONS = 9
FIRST_LEG_TWO_MA_WRAP_CLOSE_OFF_LOW_MIN_PCT = 3.216433
OVERSOLD_ATTACK_STAGE_PRE_CROSS_PRESSURE = "pre_cross_pressure"
OVERSOLD_ATTACK_STAGE_FIRST_LEG_TWO_MA_WRAP = "first_leg_two_ma_wrap"
OVERSOLD_ATTACK_STAGE_THREE_MA_WRAP = "three_ma_wrap"
OVERSOLD_ATTACK_STAGE_BRIDGE_CROSS = "bridge_cross_before_ma30"
OVERSOLD_ATTACK_STAGE_SECOND_LEG_SUPPORT = "second_leg_support_before_ma30"
OVERSOLD_ATTACK_STAGE_ATTACK_BODY_HOLD = "attack_body_hold"
OVERSOLD_ATTACK_STAGE_POST_WRAP_CONFIRMATION = "post_wrap_confirmation"
OVERSOLD_ATTACK_STAGE_COMPLETED_PATH_RETEST = "completed_path_retest"
OVERSOLD_ATTACK_STAGE_PRICE_FIRST_OBSERVATION = "price_first_observation"
PRE_ATTACK_BASE_WINDOW_SESSIONS = 15
PRE_ATTACK_BASE_EXCLUDED_RECENT_SESSIONS = 2
PRE_ATTACK_BASE_TAIL_SESSIONS = 3
PRE_ATTACK_BASE_MIN_SETTLEMENT_SESSIONS = 3
PRE_ATTACK_BASE_MATERIAL_MOVE_RANGE_MULTIPLE = 1.0
PRE_ATTACK_BASE_COMPACT_TAIL_RANGE_MULTIPLE = 1.0
# These source geometries remain auditable, but their broad samples do not
# enter the daily list without a narrower production qualification gate.
RESEARCH_PENDING_DAILY_RULE_KEYS = frozenset(
    {
        ATTACK_BODY_HOLD_RULE_KEY,
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        MA10_MA20_PRE_CROSS_RULE_KEY,
    }
)
TRANSITION_RULE_KEYS = frozenset({OVERSOLD_TO_TREND_RULE_KEY})
SCORE_VARIANTS_BY_SETUP: dict[str, tuple[str, ...]] = {
    "oversold_rebound": ("base", "with_volume"),
    "trend_pullback": ("base", "with_transition_bonus"),
}
SCORE_BANDS = (
    (0.0, 39.999, "0-39"),
    (40.0, 59.999, "40-59"),
    (60.0, 79.999, "60-79"),
    (80.0, 89.999, "80-89"),
    (90.0, 100.0, "90-100"),
)


@dataclass(frozen=True)
class DiscoveryRule:
    """One source-derived rule frozen before the full-window run."""

    key: str
    setup_type: str
    description: str


EXPLICIT_CASE_OVERSOLD_RULES = (
    DiscoveryRule(
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY,
        "oversold_rebound",
        "首段两线实体包裹：跨 MA10/20、未越 MA30；实时仅放行成熟底盘、非追高且有承接子型",
    ),
    DiscoveryRule(
        RESEARCH_THREE_MA_WRAP_RULE_KEY,
        "oversold_rebound",
        "三线收敛阳线包裹（贴线、缩量）",
    ),
    DiscoveryRule(
        POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY,
        "oversold_rebound",
        "稳定三线包裹后的次日上沿回踩站稳",
    ),
    DiscoveryRule(
        STAGED_MA10_SUPPORT_RULE_KEY,
        "oversold_rebound",
        "分段支撑：MA10 回踩后向 MA30 收敛",
    ),
    DiscoveryRule(
        ATTACK_BODY_HOLD_RULE_KEY,
        "oversold_rebound",
        "攻击实体缩量守住（研究待验证）",
    ),
    DiscoveryRule(
        MA10_MA20_PRE_CROSS_RULE_KEY,
        "oversold_rebound",
        "MA10/MA20 预上穿放量（研究待验证）",
    ),
    DiscoveryRule(
        "ma10_ma30_retest_after_actual_cross_two_leg_volume",
        "oversold_rebound",
        "MA30 回踩后的缩量转放量修复",
    ),
)


EXPLICIT_CASE_TREND_RULES = (
    DiscoveryRule(
        OVERSOLD_TO_TREND_RULE_KEY,
        "trend_pullback",
        "长期空头后 MA10 在 7 日内依次上穿 MA20、MA30，回撤后 MA20/30 紧贴且 MA10/20 向上；不要求 MA5 或 MA60",
    ),
    DiscoveryRule(
        "ma10_low_touch_after_ma5_extension",
        "trend_pullback",
        "稳定多头中前一日收盘偏离 MA5，随后 D 日低点回踩 MA10",
    ),
    DiscoveryRule(
        "ma5_low_touch_stable_trend",
        "trend_pullback",
        "稳定多头中 D 日低点回踩 MA5",
    ),
    DiscoveryRule(
        "ma5_low_touch_stable_trend_volume_shrink",
        "trend_pullback",
        "稳定多头中 D 日低点回踩 MA5，D 日成交量缩量",
    ),
    DiscoveryRule(
        "ma5_low_touch_after_disordered_trend_rebuild",
        "trend_pullback",
        "均线混乱后新恢复多头排列，D 日低点宽回踩 MA5",
    ),
    DiscoveryRule(
        "ma5_low_touch_early_trend",
        "trend_pullback",
        "多头排列形成早期的 MA5 低点回踩",
    ),
    DiscoveryRule(
        "ma5_low_touch_early_trend_prior_touch",
        "trend_pullback",
        "多头排列形成早期且前一日已触及 MA5 的连续回踩",
    ),
)

EXPLICIT_CASE_PROCESS_RULE_KEYS = frozenset(
    rule.key for rule in (*EXPLICIT_CASE_OVERSOLD_RULES, *EXPLICIT_CASE_TREND_RULES)
)


DISCOVERY_RULES: dict[str, tuple[DiscoveryRule, ...]] = {
    "oversold_rebound": EXPLICIT_CASE_OVERSOLD_RULES,
    "trend_pullback": EXPLICIT_CASE_TREND_RULES,
}


@dataclass(frozen=True)
class _CandidateSnapshot:
    symbol: str
    trade_date: date
    position: int
    history: Sequence[Mapping[str, object]]
    dates: tuple[date, ...]
    features: Mapping[str, object]
    prior_features: Mapping[str, object] | None
    d1_close_return_pct: float | None
    d1_label_status: str
    d1_initial_short_trend_formed: bool | None


@dataclass
class _ReturnAccumulator:
    candidate_count: int = 0
    label_unavailable_count: int = 0
    dates: set[date] = field(default_factory=set)
    values: list[float] = field(default_factory=list)
    d1_initial_short_trend_outcomes: list[bool] = field(default_factory=list)

    def add(
        self,
        trade_date: date,
        value: float | None,
        *,
        d1_initial_short_trend_formed: bool | None = None,
    ) -> None:
        self.candidate_count += 1
        self.dates.add(trade_date)
        if value is None:
            self.label_unavailable_count += 1
            return
        self.values.append(value)
        if isinstance(d1_initial_short_trend_formed, bool):
            self.d1_initial_short_trend_outcomes.append(
                d1_initial_short_trend_formed
            )

    def summary(self) -> dict[str, object]:
        negative = [value for value in self.values if value < 0]
        return {
            "candidate_count": self.candidate_count,
            "candidate_days": len(self.dates),
            "sample_count": len(self.values),
            "label_unavailable_count": self.label_unavailable_count,
            "win_rate_pct": _rate_pct(
                sum(value > 0 for value in self.values),
                len(self.values),
            ),
            "negative_count": len(negative),
            "negative_rate_pct": _rate_pct(len(negative), len(self.values)),
            "d1_mean_return_pct": _round_pct(fmean(self.values)) if self.values else None,
            "d1_median_return_pct": _round_pct(median(self.values)) if self.values else None,
            "negative_mean_return_pct": _round_pct(fmean(negative)) if negative else None,
            "d1_initial_short_trend_formed_available_count": len(
                self.d1_initial_short_trend_outcomes
            ),
            "d1_initial_short_trend_formed_count": sum(
                self.d1_initial_short_trend_outcomes
            ),
            "d1_initial_short_trend_formed_rate_pct": _rate_pct(
                sum(self.d1_initial_short_trend_outcomes),
                len(self.d1_initial_short_trend_outcomes),
            ),
            "daily_candidate_average": _round_pct(
                self.candidate_count / len(self.dates)
            )
            if self.dates
            else 0.0,
        }


@dataclass
class _RuleAccumulator:
    overall: _ReturnAccumulator = field(default_factory=_ReturnAccumulator)
    daily: dict[date, _ReturnAccumulator] = field(
        default_factory=lambda: defaultdict(_ReturnAccumulator)
    )
    stocks: dict[str, _ReturnAccumulator] = field(
        default_factory=lambda: defaultdict(_ReturnAccumulator)
    )
    worst_heap: list[tuple[float, int, dict[str, object]]] = field(default_factory=list)
    label_excluded_main_board_price_limit_count: int = 0
    observation_index: int = 0
    transition_volume_expand_then_shrink: _ReturnAccumulator = field(
        default_factory=_ReturnAccumulator
    )
    transition_volume_other_pattern: _ReturnAccumulator = field(
        default_factory=_ReturnAccumulator
    )
    d1_initial_short_trend_formed_group: _ReturnAccumulator = field(
        default_factory=_ReturnAccumulator
    )
    d1_initial_short_trend_not_formed_group: _ReturnAccumulator = field(
        default_factory=_ReturnAccumulator
    )

    def add(self, observation: Mapping[str, object]) -> None:
        label_status = str(observation.get("d1_label_status") or "available")
        if label_status == "label_excluded_main_board_price_limit":
            self.label_excluded_main_board_price_limit_count += 1
            return

        trade_date = _required_date(observation.get("trade_date"))
        value = _number_or_none(observation.get("d1_close_return_pct"))
        d1_initial_short_trend_outcome = observation.get(
            "d1_initial_short_trend_formed"
        )
        if not isinstance(d1_initial_short_trend_outcome, bool):
            d1_initial_short_trend_outcome = None
        symbol = str(observation.get("vt_symbol") or "").strip().upper()
        self.overall.add(
            trade_date,
            value,
            d1_initial_short_trend_formed=d1_initial_short_trend_outcome,
        )
        self.daily[trade_date].add(
            trade_date,
            value,
            d1_initial_short_trend_formed=d1_initial_short_trend_outcome,
        )
        if symbol:
            self.stocks[symbol].add(
                trade_date,
                value,
                d1_initial_short_trend_formed=d1_initial_short_trend_outcome,
            )
        transition_volume_confirmation = observation.get(
            "transition_volume_expand_then_shrink"
        )
        if isinstance(transition_volume_confirmation, bool):
            volume_accumulator = (
                self.transition_volume_expand_then_shrink
                if transition_volume_confirmation
                else self.transition_volume_other_pattern
            )
            volume_accumulator.add(
                trade_date,
                value,
                d1_initial_short_trend_formed=d1_initial_short_trend_outcome,
            )
        if d1_initial_short_trend_outcome is not None:
            trend_outcome_accumulator = (
                self.d1_initial_short_trend_formed_group
                if d1_initial_short_trend_outcome
                else self.d1_initial_short_trend_not_formed_group
            )
            trend_outcome_accumulator.add(
                trade_date,
                value,
                d1_initial_short_trend_formed=d1_initial_short_trend_outcome,
            )
        if value is not None:
            self._record_worst(observation, value)

    def _record_worst(self, observation: Mapping[str, object], value: float) -> None:
        self.observation_index += 1
        row = {
            "vt_symbol": str(observation.get("vt_symbol") or ""),
            "trade_date": _required_date(observation.get("trade_date")).isoformat(),
            "d1_close_return_pct": value,
            "d1_initial_short_trend_formed": observation.get(
                "d1_initial_short_trend_formed"
            ),
            "feature_snapshot": dict(observation.get("feature_snapshot") or {}),
        }
        item = (-value, self.observation_index, row)
        if len(self.worst_heap) < MAX_WORST_OBSERVATIONS:
            heapq.heappush(self.worst_heap, item)
        elif item[0] > self.worst_heap[0][0]:
            heapq.heapreplace(self.worst_heap, item)

    def render(self) -> dict[str, object]:
        daily = [
            {"trade_date": trade_date.isoformat(), **accumulator.summary()}
            for trade_date, accumulator in sorted(self.daily.items())
        ]
        stocks = [
            {"vt_symbol": symbol, **accumulator.summary()}
            for symbol, accumulator in self.stocks.items()
            if accumulator.values
        ]
        worst_stocks = sorted(
            (
                row
                for row in stocks
                if _number_or_none(row.get("d1_mean_return_pct")) is not None
                and float(row["d1_mean_return_pct"]) < 0
            ),
            key=lambda row: (
                float(row["d1_mean_return_pct"]),
                str(row["vt_symbol"]),
            ),
        )
        overall = {
            **self.overall.summary(),
            "label_excluded_main_board_price_limit_count": self.label_excluded_main_board_price_limit_count,
        }
        result = {
            "overall": overall,
            "daily_outcomes": daily,
            "worst_days": sorted(
                (
                    row
                    for row in daily
                    if _number_or_none(row.get("d1_mean_return_pct")) is not None
                    and float(row["d1_mean_return_pct"]) < 0
                ),
                key=lambda row: (
                    float(row["d1_mean_return_pct"]),
                    str(row["trade_date"]),
                ),
            ),
            "worst_stocks": worst_stocks,
            "negative_observations": [
                item[2]
                for item in sorted(
                    self.worst_heap,
                    key=lambda item: float(item[2]["d1_close_return_pct"]),
                )
            ],
        }
        if (
            self.transition_volume_expand_then_shrink.candidate_count
            or self.transition_volume_other_pattern.candidate_count
        ):
            result["transition_volume_comparison"] = {
                "expand_then_shrink": self.transition_volume_expand_then_shrink.summary(),
                "other_volume_pattern": self.transition_volume_other_pattern.summary(),
            }
        if (
            self.d1_initial_short_trend_formed_group.candidate_count
            or self.d1_initial_short_trend_not_formed_group.candidate_count
        ):
            result["d1_initial_short_trend_comparison"] = {
                "formed": self.d1_initial_short_trend_formed_group.summary(),
                "not_formed": self.d1_initial_short_trend_not_formed_group.summary(),
            }
        return result


def _render_rule_aggregate(accumulator: _RuleAccumulator) -> dict[str, object]:
    """Render only the aggregate needed to rank a rule or score band."""

    result = {
        **accumulator.overall.summary(),
        "label_excluded_main_board_price_limit_count": (
            accumulator.label_excluded_main_board_price_limit_count
        ),
    }
    if (
        accumulator.transition_volume_expand_then_shrink.candidate_count
        or accumulator.transition_volume_other_pattern.candidate_count
    ):
        result["transition_volume_comparison"] = {
            "expand_then_shrink": (
                accumulator.transition_volume_expand_then_shrink.summary()
            ),
            "other_volume_pattern": (
                accumulator.transition_volume_other_pattern.summary()
            ),
        }
    if (
        accumulator.d1_initial_short_trend_formed_group.candidate_count
        or accumulator.d1_initial_short_trend_not_formed_group.candidate_count
    ):
        result["d1_initial_short_trend_comparison"] = {
            "formed": accumulator.d1_initial_short_trend_formed_group.summary(),
            "not_formed": accumulator.d1_initial_short_trend_not_formed_group.summary(),
        }
    return result


@dataclass
class _ExitAccumulator:
    candidate_count: int = 0
    closed_count: int = 0
    unavailable_count: int = 0
    not_triggered_count: int = 0
    dates: set[date] = field(default_factory=set)
    triggered_dates: set[date] = field(default_factory=set)
    values: list[float] = field(default_factory=list)
    holding_sessions: list[int] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, row: Mapping[str, object]) -> None:
        self.candidate_count += 1
        self.dates.add(_required_date(row.get("trade_date")))
        status = str(row.get("status") or "unavailable")
        if status == "not_triggered":
            self.not_triggered_count += 1
            self.reasons[str(row.get("exit_reason") or status)] += 1
            return
        self.triggered_dates.add(_required_date(row.get("trade_date")))
        if status != "closed":
            self.unavailable_count += 1
            self.reasons[str(row.get("exit_reason") or status)] += 1
            return
        self.closed_count += 1
        value = _number_or_none(row.get("return_pct"))
        holding = _integer_or_none(row.get("holding_sessions"))
        if value is not None:
            self.values.append(value)
        if holding is not None:
            self.holding_sessions.append(holding)
        self.reasons[str(row.get("exit_reason") or "fixed_horizon")] += 1

    def summary(self) -> dict[str, object]:
        return {
            "candidate_count": self.candidate_count,
            "candidate_days": len(self.dates),
            "triggered_candidate_count": self.closed_count + self.unavailable_count,
            "triggered_candidate_days": len(self.triggered_dates),
            "closed_count": self.closed_count,
            "unavailable_count": self.unavailable_count,
            "not_triggered_count": self.not_triggered_count,
            "sample_count": len(self.values),
            "win_rate_pct": _rate_pct(
                sum(value > 0 for value in self.values),
                len(self.values),
            ),
            "mean_return_pct": _round_pct(fmean(self.values)) if self.values else None,
            "median_return_pct": _round_pct(median(self.values)) if self.values else None,
            "mean_holding_sessions": _round_pct(fmean(self.holding_sessions))
            if self.holding_sessions
            else None,
            "exit_reasons": dict(sorted(self.reasons.items())),
        }


def build_pre_attack_base_process_features(
    history: Sequence[Mapping[str, object]],
    *,
    as_of_date: date | None = None,
    include_d_minus_one: bool = False,
) -> dict[str, object]:
    """Describe the base before a D-day attack observation.

    By default the final two visible sessions are excluded for the
    ``ATTACK_BODY_HOLD_RULE_KEY`` sequence, where D-1 is the attack body and
    D is the hold signal.  Direct D-day attacks can set ``include_d_minus_one``
    so their final base session remains visible.  This is a causal descriptor;
    callers may use it in a frozen qualification gate, but it never scores a
    candidate by itself.
    """

    visible = _visible_history(history, as_of_date=as_of_date)
    closes = [
        _required_positive_number(row.get("close_price"), "close_price")
        for row in visible
    ]
    ma_series = {
        window: _moving_average_series(closes, window)
        for window in (10, 20)
    }
    return _pre_attack_base_process_features(
        visible,
        closes,
        ma_series,
        excluded_recent_sessions=(1 if include_d_minus_one else 2),
    )


def is_first_leg_two_ma_wrap_base_qualified(
    features: Mapping[str, object],
) -> bool:
    """Check the base and MA10/20 convergence required before D-day attack."""

    efficiency = _number_or_none(
        features.get("ma10_ma20_convergence_efficiency_5d")
    )
    gap_narrowing = _number_or_none(
        features.get("ma10_ma20_gap_narrowing_3d_pct")
    )
    return bool(
        features.get("pre_attack_base_phase")
        in FIRST_LEG_TWO_MA_WRAP_SETTLED_BASE_PHASES
        and efficiency is not None
        and efficiency >= FIRST_LEG_TWO_MA_WRAP_EFFICIENCY_5D_MIN
        and gap_narrowing is not None
        and gap_narrowing >= FIRST_LEG_TWO_MA_WRAP_GAP_NARROWING_3D_MIN_PCT
    )


def is_mature_first_leg_two_ma_wrap_qualified(
    features: Mapping[str, object],
) -> bool:
    """Qualify a non-chasing, mature first-leg MA10/20 wrap for the daily list."""

    close_to_ma10 = _number_or_none(features.get("close_to_ma10_pct"))
    daily_return = _number_or_none(features.get("daily_return_pct"))
    gap_narrowing = _number_or_none(
        features.get("ma10_ma20_gap_narrowing_3d_pct")
    )
    pivot_age = _number_or_none(
        features.get("pre_attack_base_pivot_age_sessions")
    )
    close_off_low = _number_or_none(features.get("close_off_low_pct"))
    return bool(
        is_first_leg_two_ma_wrap_base_qualified(features)
        and close_to_ma10 is not None
        and close_to_ma10 <= FIRST_LEG_TWO_MA_WRAP_CLOSE_TO_MA10_MAX_PCT
        and daily_return is not None
        and daily_return <= FIRST_LEG_TWO_MA_WRAP_DAILY_RETURN_MAX_PCT
        and gap_narrowing is not None
        and gap_narrowing <= FIRST_LEG_TWO_MA_WRAP_GAP_NARROWING_3D_MAX_PCT
        and pivot_age is not None
        and pivot_age >= FIRST_LEG_TWO_MA_WRAP_PIVOT_AGE_MIN_SESSIONS
        and close_off_low is not None
        and close_off_low >= FIRST_LEG_TWO_MA_WRAP_CLOSE_OFF_LOW_MIN_PCT
    )


def classify_oversold_attack_stages(
    features: Mapping[str, object],
    *,
    prior_features: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Describe where a causal oversold D-day sits in an attack sequence.

    A research low-suction point is an attack anchor even when its candle is a
    small support candle rather than a large positive body.  This classifier
    keeps those stages explicit for case coverage and later stage-local
    ranking research.  It is deliberately not a candidate rule or score.
    """

    stages: list[str] = []
    long_bear = bool(features.get("long_bear_alignment"))
    full_bear = bool(features.get("current_full_bear_alignment"))
    positive_candle = bool(features.get("positive_candle"))
    pre_cross_pressure = bool(
        long_bear
        and full_bear
        and bool(features.get("ma10_below_ma20"))
        and positive_candle
        and bool(features.get("ma10_ma20_gap_narrowing"))
    )
    first_leg_wrap = bool(
        long_bear
        and full_bear
        and bool(features.get("yang_wrap_two_ma"))
        and bool(features.get("close_below_ma30"))
        and bool(features.get("signal_day_not_limit_up_closed"))
    )
    bridge_cross = bool(
        long_bear
        and bool(features.get("ma10_above_ma20"))
        and bool(features.get("ma10_below_ma30"))
        and bool(features.get("ma10_crossed_ma20_after_long_bear_within_15d"))
        and _number_or_none(
            features.get("ma10_crossed_ma20_after_long_bear_age_sessions_15d")
        )
        == 0
    )
    second_leg_support = bool(
        long_bear
        and bool(features.get("ma10_above_ma20"))
        and bool(features.get("ma10_below_ma30"))
        and bool(features.get("ma10_crossed_ma20_after_long_bear_within_15d"))
        and bool(features.get("ma10_low_touch"))
    )
    attack_body_hold = bool(
        long_bear
        and bool(features.get("ma10_above_ma20"))
        and bool(features.get("ma10_below_ma30"))
        and bool(features.get("ma10_crossed_ma20_after_long_bear_within_15d"))
        and bool(features.get("controlled_attack_body_retest_candle"))
        and bool(features.get("attack_body_low_held"))
        and bool(features.get("attack_body_close_held"))
    )
    post_wrap_confirmation = bool(
        _prior_stable_three_ma_wrap(prior_features)
        and _post_wrap_upper_band_touched(features, prior_features)
        and _close_above_current_three_ma(features)
        and bool(features.get("small_positive_candle"))
        and _post_wrap_turnover_controlled(features)
    )
    completed_path_retest = bool(
        long_bear
        and bool(features.get("ma10_was_above_ma30_within_15d"))
        and bool(features.get("ma10_ma30_contact"))
        and bool(features.get("post_cross_pullback"))
    )
    close_to_ma10 = _number_or_none(features.get("close_to_ma10_pct"))
    price_first_observation = bool(
        long_bear
        and full_bear
        and positive_candle
        and bool(features.get("ma10_below_ma30"))
        and bool(features.get("ma10_ma30_fast_convergence"))
        and close_to_ma10 is not None
        and 4.0 <= close_to_ma10 <= 10.0
    )

    if pre_cross_pressure:
        stages.append(OVERSOLD_ATTACK_STAGE_PRE_CROSS_PRESSURE)
    if first_leg_wrap:
        stages.append(OVERSOLD_ATTACK_STAGE_FIRST_LEG_TWO_MA_WRAP)
    if bool(features.get("yang_wrap_three_ma")):
        stages.append(OVERSOLD_ATTACK_STAGE_THREE_MA_WRAP)
    if bridge_cross:
        stages.append(OVERSOLD_ATTACK_STAGE_BRIDGE_CROSS)
    if second_leg_support:
        stages.append(OVERSOLD_ATTACK_STAGE_SECOND_LEG_SUPPORT)
    if attack_body_hold:
        stages.append(OVERSOLD_ATTACK_STAGE_ATTACK_BODY_HOLD)
    if post_wrap_confirmation:
        stages.append(OVERSOLD_ATTACK_STAGE_POST_WRAP_CONFIRMATION)
    if completed_path_retest:
        stages.append(OVERSOLD_ATTACK_STAGE_COMPLETED_PATH_RETEST)
    if price_first_observation:
        stages.append(OVERSOLD_ATTACK_STAGE_PRICE_FIRST_OBSERVATION)
    return tuple(stages)


def _pre_attack_base_process_features(
    visible: Sequence[Mapping[str, object]],
    closes: Sequence[float],
    ma_series: Mapping[int, Sequence[float | None]],
    *,
    excluded_recent_sessions: int = PRE_ATTACK_BASE_EXCLUDED_RECENT_SESSIONS,
) -> dict[str, object]:
    """Classify the preceding 15-session base at a declared causal cutoff."""

    if excluded_recent_sessions not in (1, 2):
        raise DailyFactorInputError(
            "pre-attack base cutoff must exclude either D or D-1 and D"
        )
    base_end = len(visible) - excluded_recent_sessions
    base_start = base_end - PRE_ATTACK_BASE_WINDOW_SESSIONS
    if base_start < 0:
        return _empty_pre_attack_base_process_features(len(visible))

    base = visible[base_start:base_end]
    base_closes = closes[base_start:base_end]
    base_lows = [
        _required_positive_number(row.get("low_price"), "low_price")
        for row in base
    ]
    ranges = [
        _pct_change(
            _required_positive_number(row.get("high_price"), "high_price"),
            low_price,
        )
        for row, low_price in zip(base, base_lows)
    ]
    median_range_pct = median(ranges) if ranges else None
    if median_range_pct is None or median_range_pct <= 0:
        return _empty_pre_attack_base_process_features(len(base))

    pivot_low = min(base_lows)
    pivot_index = max(
        index for index, low_price in enumerate(base_lows) if low_price == pivot_low
    )
    daily_returns = _pre_attack_base_daily_returns(
        closes,
        base_start=base_start,
        base_end=base_end,
    )
    material_indices = [
        index
        for index, daily_return in enumerate(daily_returns)
        if daily_return is not None
        and daily_return
        >= PRE_ATTACK_BASE_MATERIAL_MOVE_RANGE_MULTIPLE * median_range_pct
    ]
    release_index = material_indices[-1] if material_indices else None
    release_after_final_pivot = bool(
        release_index is not None and release_index > pivot_index
    )
    settlement_sessions = (
        len(base) - 1 - release_index
        if release_index is not None
        else len(base)
    )
    tail_lows = base_lows[-PRE_ATTACK_BASE_TAIL_SESSIONS:]
    tail_floor = min(tail_lows)
    tail_span_pct = _pct_change(max(tail_lows), tail_floor)
    tail_span_to_median_range = tail_span_pct / median_range_pct
    tail_floor_vs_pivot_pct = _pct_change(tail_floor, pivot_low)
    release_origin_close = (
        _pre_attack_release_origin_close(closes, base_start, release_index)
        if release_index is not None
        else None
    )
    tail_floor_vs_release_origin_pct = (
        _pct_change(tail_floor, release_origin_close)
        if release_origin_close is not None
        else None
    )
    tail_retested_release = bool(
        tail_floor_vs_release_origin_pct is not None
        and tail_floor_vs_release_origin_pct < 0
    )
    phase = _pre_attack_base_phase(
        has_release=release_index is not None,
        release_after_final_pivot=release_after_final_pivot,
        settlement_sessions=settlement_sessions,
        tail_span_to_median_range=tail_span_to_median_range,
        tail_floor_vs_pivot_pct=tail_floor_vs_pivot_pct,
        tail_retested_release=tail_retested_release,
    )
    return {
        "pre_attack_base_phase": phase,
        "pre_attack_base_window_sessions": len(base),
        "pre_attack_base_pivot_age_sessions": len(base) - 1 - pivot_index,
        "pre_attack_base_release_after_final_pivot": release_after_final_pivot,
        "pre_attack_base_settlement_sessions": settlement_sessions,
        "pre_attack_base_tail_span_to_median_range": _round_pct(
            tail_span_to_median_range
        ),
        "pre_attack_base_tail_floor_vs_pivot_pct": _round_pct(
            tail_floor_vs_pivot_pct
        ),
        "pre_attack_base_tail_retested_release": tail_retested_release,
        "pre_attack_base_ma10_ma20_progress_per_churn": (
            _pre_attack_ma10_ma20_progress_per_churn(
                base_closes,
                ma10_series=ma_series[10][base_start:base_end],
                ma20_series=ma_series[20][base_start:base_end],
            )
        ),
        "pre_attack_base_tail_floor_vs_release_origin_pct": (
            _round_pct(tail_floor_vs_release_origin_pct)
            if tail_floor_vs_release_origin_pct is not None
            else None
        ),
    }


def _empty_pre_attack_base_process_features(
    window_sessions: int,
) -> dict[str, object]:
    return {
        "pre_attack_base_phase": "insufficient_history",
        "pre_attack_base_window_sessions": window_sessions,
        "pre_attack_base_pivot_age_sessions": None,
        "pre_attack_base_release_after_final_pivot": False,
        "pre_attack_base_settlement_sessions": None,
        "pre_attack_base_tail_span_to_median_range": None,
        "pre_attack_base_tail_floor_vs_pivot_pct": None,
        "pre_attack_base_tail_retested_release": False,
        "pre_attack_base_ma10_ma20_progress_per_churn": None,
        "pre_attack_base_tail_floor_vs_release_origin_pct": None,
    }


def _pre_attack_base_daily_returns(
    closes: Sequence[float],
    *,
    base_start: int,
    base_end: int,
) -> list[float | None]:
    """Return base-session close changes using only D-2-and-earlier anchors."""

    result: list[float | None] = []
    for index in range(base_start, base_end):
        result.append(_pct_change(closes[index], closes[index - 1]) if index else None)
    return result


def _pre_attack_release_origin_close(
    closes: Sequence[float],
    base_start: int,
    release_index: int,
) -> float | None:
    release_position = base_start + release_index
    return closes[release_position - 1] if release_position else None


def _pre_attack_base_phase(
    *,
    has_release: bool,
    release_after_final_pivot: bool,
    settlement_sessions: int,
    tail_span_to_median_range: float,
    tail_floor_vs_pivot_pct: float,
    tail_retested_release: bool,
) -> str:
    """Name the observable base path; the labels are not trading decisions."""

    if not has_release:
        return (
            "gradual_support_ladder"
            if tail_floor_vs_pivot_pct > 0
            else "unrepaired_base"
        )
    if not release_after_final_pivot:
        return "post_release_washout"
    if tail_floor_vs_pivot_pct <= 0:
        return "unrepaired_base"
    if settlement_sessions < PRE_ATTACK_BASE_MIN_SETTLEMENT_SESSIONS:
        return "fresh_expansion"
    if (
        tail_span_to_median_range
        > PRE_ATTACK_BASE_COMPACT_TAIL_RANGE_MULTIPLE
    ):
        return "expanded_but_unsettled"
    if tail_retested_release:
        return "release_retest_base"
    return "new_price_shelf"


def _pre_attack_ma10_ma20_progress_per_churn(
    closes: Sequence[float],
    *,
    ma10_series: Sequence[float | None],
    ma20_series: Sequence[float | None],
) -> float | None:
    if len(closes) < 6 or len(ma10_series) < 6 or len(ma20_series) < 6:
        return None
    ma10_tail = ma10_series[-6:]
    ma20_tail = ma20_series[-6:]
    if any(value is None for value in (*ma10_tail, *ma20_tail)):
        return None
    gap_start = _pct_change(float(ma10_tail[0]), float(ma20_tail[0]))
    gap_end = _pct_change(float(ma10_tail[-1]), float(ma20_tail[-1]))
    close_tail = closes[-6:]
    churn = sum(
        abs(_pct_change(close_tail[index], close_tail[index - 1]))
        for index in range(1, len(close_tail))
    )
    return _round_pct((gap_end - gap_start) / churn) if churn else None


def build_extended_daily_features(
    history: Sequence[Mapping[str, object]],
    *,
    as_of_date: date | None = None,
    include_pre_attack_base_features: bool = False,
) -> dict[str, object]:
    """Return finite D-and-earlier extensions to the frozen daily feature set.

    ``include_pre_attack_base_features`` is reserved for offline research
    reports.  The live scanner keeps its established feature workload and does
    not receive these descriptive fields.
    """

    visible = _visible_history(history, as_of_date=as_of_date)
    base = build_daily_features(visible)
    closes = [_required_positive_number(row.get("close_price"), "close_price") for row in visible]
    lows = [_required_positive_number(row.get("low_price"), "low_price") for row in visible]
    volumes = [_number_or_none(row.get("volume")) for row in visible]
    ma_series = {
        window: _moving_average_series(closes, window)
        for window in (5, 10, 20, 30, 60)
    }
    pre_attack_base_features = (
        _pre_attack_base_process_features(visible, closes, ma_series)
        if include_pre_attack_base_features
        else {}
    )
    close_price = _number_or_none(base.get("close_price"))
    high_price = _required_positive_number(base.get("high_price"), "high_price")
    low_price = _required_positive_number(base.get("low_price"), "low_price")
    intraday_midpoint_price = (high_price + low_price) / 2
    ma5 = _number_or_none(base.get("ma5"))
    ma10 = _number_or_none(base.get("ma10"))
    ma20 = _number_or_none(base.get("ma20"))
    ma30 = _number_or_none(base.get("ma30"))
    ma60 = _number_or_none(base.get("ma60"))

    cross_10_20_age = _recent_cross_age(closes, fast_window=10, slow_window=20)
    cross_10_30_age = _recent_cross_age(closes, fast_window=10, slow_window=30)
    cross_20_30_age = _recent_cross_age(closes, fast_window=20, slow_window=30)
    process_cross_10_20_age = _recent_cross_age(
        closes,
        fast_window=10,
        slow_window=20,
        lookback=PROCESS_CROSS_LOOKBACK,
    )
    process_cross_10_30_age = _recent_cross_age(
        closes,
        fast_window=10,
        slow_window=30,
        lookback=PROCESS_CROSS_LOOKBACK,
    )
    cross_10_20_after_long_bear_age = _recent_ma10_ma20_upcross_after_long_bear_age(
        ma_series[10],
        ma_series[20],
        ma_series[30],
        lookback=PROCESS_CROSS_LOOKBACK,
    )
    distance_10_20 = _signed_ma_distance_pct(ma10, ma20, close_price)
    distance_10_30 = _signed_ma_distance_pct(ma10, ma30, close_price)
    distance_20_30 = _signed_ma_distance_pct(ma20, ma30, close_price)
    ma10_ma20_convergence_efficiency_5d = _ma10_ma20_convergence_efficiency_5d(
        closes,
        ma10_series=ma_series[10],
        ma20_series=ma_series[20],
    )
    ma10_ma20_next_close_required_return = (
        _ma10_ma20_next_close_required_return_pct(closes)
    )
    ma10_ma30_next_close_required_return = (
        _ma10_ma30_next_close_required_return_pct(closes)
    )
    midpoint_to_ma5 = _price_to_ma_distance_pct(intraday_midpoint_price, ma5)
    midpoint_to_ma10 = _price_to_ma_distance_pct(intraday_midpoint_price, ma10)
    daily_return = _number_or_none(base.get("daily_return_pct"))
    current_spread = _number_or_none(base.get("ma_cluster_spread_pct"))
    prior_spread = _number_or_none(base.get("ma_cluster_spread_5d_pct"))
    slopes = tuple(
        _number_or_none(base.get(f"ma{window}_slope_5d_pct"))
        for window in (10, 20, 30)
    )
    ma10_slope_5d, ma20_slope_5d, _ = slopes
    slope_values = tuple(value for value in slopes if value is not None)
    trend_bull_alignment = bool(
        ma10 is not None
        and ma20 is not None
        and ma30 is not None
        and ma10 > ma20 > ma30
    )
    trend_all_slopes_up = len(slope_values) == 3 and all(value > 0 for value in slope_values)
    trend_slope_mean = fmean(slope_values) if len(slope_values) == 3 else None
    close_to_ma5 = _number_or_none(base.get("close_to_ma5_pct"))
    close_to_ma10 = _number_or_none(base.get("close_to_ma10_pct"))
    ma5_low_touch = _support_low_touch(
        _number_or_none(base.get("low_to_ma5_pct")),
        close_to_ma5,
    )
    ma10_low_touch = _support_low_touch(
        _number_or_none(base.get("low_to_ma10_pct")),
        close_to_ma10,
    )
    ma5_low_touch_broad = _support_low_touch_broad(
        _number_or_none(base.get("low_to_ma5_pct")),
        close_to_ma5,
    )
    ma5_close_near = _support_close_near(close_to_ma5)
    ma10_close_near = _support_close_near(close_to_ma10)
    ma5_midpoint_near = _support_midpoint_near(midpoint_to_ma5)
    ma10_midpoint_near = _support_midpoint_near(midpoint_to_ma10)
    low_to_ma20 = _price_to_ma_distance_pct(low_price, ma20)
    low_to_ma30 = _price_to_ma_distance_pct(low_price, ma30)
    close_to_ma20 = _price_to_ma_distance_pct(close_price, ma20)
    close_to_ma30 = _price_to_ma_distance_pct(close_price, ma30)
    ma20_low_touch = _support_low_touch(low_to_ma20, close_to_ma20)
    ma30_low_touch = _support_low_touch(low_to_ma30, close_to_ma30)
    turnover_rate = _number_or_none(visible[-1].get("turnover_rate"))
    close_off_low_pct = (
        _round_pct((close_price - low_price) / low_price * 100)
        if close_price is not None and low_price > 0
        else None
    )
    support_close_reaction = bool(
        close_off_low_pct is not None
        and close_off_low_pct >= SUPPORT_CLOSE_REACTION_MIN_PCT
    )
    turnover_rate_low = bool(
        turnover_rate is not None and turnover_rate < TURNOVER_RATE_LOW_MAX_PCT
    )
    # 阳线包裹收敛三线（主人低吸"最好看"形态：三线挤窄带，阳线实体一举跨越 = 收敛到极致的启动信号）
    _open_price = _number_or_none(visible[-1].get("open_price")) if visible else None
    yang_wrap_two_ma = False
    yang_wrap_three_ma = False
    if (
        _open_price is not None
        and ma10 is not None
        and ma20 is not None
        and ma30 is not None
        and close_price is not None
    ):
        _lo2 = min(ma10, ma20)
        _hi2 = max(ma10, ma20)
        yang_wrap_two_ma = bool(
            _open_price < _lo2
            and close_price > _hi2
        )
        _lo3 = min(ma10, ma20, ma30)
        _hi3 = max(ma10, ma20, ma30)
        # 换手≥1.5%（主人："换手率也在1.5%以上"——排除<1%死股式包裹，它们微涨非真低吸）
        yang_wrap_three_ma = bool(
            _open_price < _lo3
            and close_price > _hi3
            and turnover_rate is not None
            and turnover_rate >= 1.5
        )
    yang_wrap_nearest_ma_low_abs_pct: float | None = None
    _wrap_low_distances = [
        _price_to_ma_distance_pct(low_price, moving_average)
        for moving_average in (ma10, ma20, ma30)
    ]
    _known_wrap_low_distances = [
        abs(distance) for distance in _wrap_low_distances if distance is not None
    ]
    if _known_wrap_low_distances:
        yang_wrap_nearest_ma_low_abs_pct = min(_known_wrap_low_distances)
    yang_wrap_volume_end_to_peak_ratio_6d: float | None = None
    _wrap_volumes = volumes[-6:]
    if len(_wrap_volumes) == 6 and all(
        volume is not None and volume > 0 for volume in _wrap_volumes
    ):
        _known_wrap_volumes = [
            float(volume) for volume in _wrap_volumes if volume is not None
        ]
        _wrap_peak_volume = max(_known_wrap_volumes)
        yang_wrap_volume_end_to_peak_ratio_6d = _known_wrap_volumes[-1] / _wrap_peak_volume
    # 梯形缩量（近6日量能逐日递减天数/5，1.0=完美下楼梯地量）
    vol_monotone_6d: float | None = None
    _vols_6 = [v for v in volumes[-6:] if v is not None]
    if len(_vols_6) == 6:
        vol_monotone_6d = sum(1 for i in range(1, 6) if _vols_6[i] < _vols_6[i - 1]) / 5
    yang_wrap_stable_base = bool(
        yang_wrap_three_ma
        and yang_wrap_nearest_ma_low_abs_pct is not None
        and yang_wrap_nearest_ma_low_abs_pct <= YANG_WRAP_STABLE_BASE_LOW_MA_MAX_PCT
        and yang_wrap_volume_end_to_peak_ratio_6d is not None
        and yang_wrap_volume_end_to_peak_ratio_6d
        <= YANG_WRAP_STABLE_BASE_VOLUME_END_TO_PEAK_MAX
        and vol_monotone_6d is not None
        and vol_monotone_6d >= VOLUME_MONOTONE_6D_MIN_RATIO
    )
    # 均线平滑度（M10 近6日逐日变化变异系数，小=匀速平滑收敛）
    ma10_slope_cv_6d: float | None = None
    _m10_ser = ma_series[10]
    if len(_m10_ser) >= 6:
        _m10_6 = _m10_ser[-6:]
        _m10_chg = [
            (_m10_6[i] - _m10_6[i - 1]) / _m10_6[i - 1] * 100
            for i in range(1, 6)
            if _m10_6[i] is not None and _m10_6[i - 1]
        ]
        if len(_m10_chg) == 5:
            _mean_chg = sum(_m10_chg) / 5
            if _mean_chg != 0:
                _var = sum((x - _mean_chg) ** 2 for x in _m10_chg) / 5
                ma10_slope_cv_6d = (_var ** 0.5) / abs(_mean_chg) * 100
    # K线实体均匀度（近6日实体排除最大后仍<2%=回踩过程无大阴大阳抖动）
    body_max_excl_6d: float | None = None
    if len(visible) >= 6:
        _bodies = []
        for _row in visible[-6:]:
            _bo = _number_or_none(_row.get("open_price"))
            _bc = _number_or_none(_row.get("close_price"))
            if _bo and _bc:
                _bodies.append(abs(_bc - _bo) / _bo * 100)
        if len(_bodies) >= 2:
            body_max_excl_6d = sorted(_bodies)[-2]
    # 上穿后守住溢价（主人"涨2次跳水=假突破波折"判据）：
    # 突破日(近15日最大涨幅>3%)前收 vs 突破后最低。溢价>+3%=守住(真突破平滑)，<+1%=回吐(假突破波折)。
    breakout_hold_premium: float | None = None
    if len(closes) >= 16 and len(lows) >= 16:
        _bstart = len(closes) - 15
        _bk, _bchg = None, 0.0
        for _k in range(_bstart, len(closes)):
            if _k > 0:
                _chg = (closes[_k] - closes[_k - 1]) / closes[_k - 1] * 100
                if _chg > _bchg:
                    _bchg, _bk = _chg, _k
        if _bk is not None and _bchg > 3.0 and lows:
            _pre_close = closes[_bk - 1]
            _after_low = min(lows[_bk:])
            breakout_hold_premium = (_after_low - _pre_close) / _pre_close * 100
    capitulation_rebound_tight = bool(
        daily_return is not None
        and daily_return <= -5.0
        and turnover_rate_low
        and close_off_low_pct is not None
        and SUPPORT_CLOSE_REACTION_MIN_PCT <= close_off_low_pct < 1.5
    )
    capitulation_rebound_broad = bool(
        daily_return is not None
        and daily_return <= -5.0
        and turnover_rate is not None
        and turnover_rate < CAPITULATION_TURNOVER_MAX_PCT
        and close_off_low_pct is not None
        and close_off_low_pct >= SUPPORT_CLOSE_REACTION_MIN_PCT
    )
    m10_dual_cross_before_m20_m30 = bool(
        cross_10_20_age is not None
        and cross_10_30_age is not None
        and cross_10_20_age >= cross_10_30_age
        and cross_20_30_age is None
        and ma20 is not None
        and ma30 is not None
        and ma20 < ma30
    )
    ma10_dual_cross_within_15d = bool(
        process_cross_10_20_age is not None
        and process_cross_10_30_age is not None
        and process_cross_10_20_age >= process_cross_10_30_age
    )
    ma10_dual_cross_within_7d = bool(
        ma10_dual_cross_within_15d
        and process_cross_10_20_age is not None
        and process_cross_10_30_age is not None
        and process_cross_10_20_age <= TRANSITION_CROSS_LOOKBACK
        and process_cross_10_30_age <= TRANSITION_CROSS_LOOKBACK
    )
    ma10_above_ma20_and_ma30 = bool(
        ma10 is not None
        and ma20 is not None
        and ma30 is not None
        and ma10 > ma20
        and ma10 > ma30
    )
    ma20_ma30_contact = _ma_contact(distance_20_30)
    transition_ma20_ma30_tight_contact = bool(
        distance_20_30 is not None
        and abs(distance_20_30) <= TRANSITION_MA20_MA30_CONTACT_PCT
    )
    ma10_ma20_slopes_up = bool(
        ma10_slope_5d is not None
        and ma20_slope_5d is not None
        and ma10_slope_5d > 0
        and ma20_slope_5d > 0
    )
    small_positive_candle = bool(
        daily_return is not None and 0 < daily_return <= 3.0
    )
    recent_pullback_from_high_pct = _recent_pullback_from_prior_high_pct(
        closes,
        lookback=OVERSOLD_PROCESS_PULLBACK_LOOKBACK,
    )
    post_cross_pullback = bool(
        recent_pullback_from_high_pct is not None
        and recent_pullback_from_high_pct <= OVERSOLD_PROCESS_PULLBACK_MIN_PCT
    )
    ma10_slope_2d = _series_slope_pct(ma_series[10], lookback=2)
    prior_ma10_slope_2d = _series_slope_pct(
        ma_series[10],
        lookback=2,
        end_offset=2,
    )
    ma10_slope_improvement_2d = _difference_or_none(
        ma10_slope_2d,
        prior_ma10_slope_2d,
    )
    prior_ma10_ma20_distance = _series_ma_distance_pct(
        ma_series[10],
        ma_series[20],
        closes,
        lookback=3,
    )
    ma10_ma20_gap_narrowing_3d = _difference_or_none(
        distance_10_20,
        prior_ma10_ma20_distance,
    )
    prior_ma10_ma30_distance = _series_ma_distance_pct(
        ma_series[10],
        ma_series[30],
        closes,
        lookback=MA10_MA30_CONVERGENCE_LOOKBACK,
    )
    ma10_ma30_gap_narrowing_5d = _difference_or_none(
        distance_10_30,
        prior_ma10_ma30_distance,
    )
    last_volume = _number_or_none(base.get("volume"))
    prior_volume = (
        _number_or_none(visible[-2].get("volume"))
        if len(visible) >= 2
        else None
    )
    last_volume_change_pct = (
        _round_pct(_pct_change(last_volume, prior_volume))
        if last_volume is not None and prior_volume is not None and prior_volume > 0
        else None
    )
    last_volume_to_prior_ratio = (
        _round_pct(last_volume / prior_volume)
        if last_volume is not None and prior_volume is not None and prior_volume > 0
        else None
    )
    prior_attack_open_price = (
        _number_or_none(visible[-2].get("open_price")) if len(visible) >= 2 else None
    )
    prior_attack_close_price = (
        _number_or_none(visible[-2].get("close_price")) if len(visible) >= 2 else None
    )
    prior_attack_high_price = (
        _number_or_none(visible[-2].get("high_price")) if len(visible) >= 2 else None
    )
    prior_positive_body_pct = (
        _round_pct(_pct_change(prior_attack_close_price, prior_attack_open_price))
        if prior_attack_close_price is not None
        and prior_attack_open_price is not None
        else None
    )
    prior_limit_up_touched = bool(
        len(closes) >= 3
        and prior_attack_high_price is not None
        and is_main_board_limit_up_touched(closes[-3], prior_attack_high_price)
    )
    attack_body_low_held = bool(
        prior_attack_open_price is not None and low_price >= prior_attack_open_price
    )
    attack_body_close_held = bool(
        prior_attack_open_price is not None
        and close_price is not None
        and close_price >= prior_attack_open_price
    )
    bull_alignment_days = int(base.get("bull_alignment_days") or 0)
    prior_bear_alignment_days = int(base.get("prior_bear_alignment_days") or 0)
    long_bear_alignment = prior_bear_alignment_days >= LONG_BEAR_ALIGNMENT_MIN_SESSIONS
    trend_transition_preparation_eligible = (
        _is_pre_cross_trend_transition_preparation(
            prior_bear_alignment_days=prior_bear_alignment_days,
            ma10=ma10,
            ma20=ma20,
            close_price=close_price,
            daily_return_pct=daily_return,
            prior_ma10=ma_series[10][-4] if len(ma_series[10]) >= 4 else None,
            prior_ma20=ma_series[20][-4] if len(ma_series[20]) >= 4 else None,
            prior_close_price=closes[-4] if len(closes) >= 4 else None,
        )
    )
    trend_transition_eligible = bool(
        long_bear_alignment
        and ma10_dual_cross_within_7d
        and ma10_above_ma20_and_ma30
        and transition_ma20_ma30_tight_contact
        and ma10_ma20_slopes_up
        and post_cross_pullback
        and small_positive_candle
    )
    trend_bull_history = tuple(
        bool(
            ma_series[10][index] is not None
            and ma_series[20][index] is not None
            and ma_series[30][index] is not None
            and ma_series[60][index] is not None
            and ma_series[10][index] > ma_series[20][index] > ma_series[30][index] > ma_series[60][index]
        )
        for index in range(len(closes))
    )
    bull_regime_start = len(closes) - bull_alignment_days
    prior_regime = trend_bull_history[
        max(0, bull_regime_start - TREND_REBUILD_PRIOR_LOOKBACK) : bull_regime_start
    ]
    prior_disordered_sessions = sum(not value for value in prior_regime)
    prior_ma5 = ma_series[5][-2] if len(ma_series[5]) >= 2 else None
    prior_ma5_close_distance = _price_to_ma_distance_pct(
        closes[-2] if len(closes) >= 2 else None,
        prior_ma5,
    )
    prior_daily_return = (
        _pct_change(closes[-2], closes[-3])
        if len(closes) >= 3
        else None
    )
    prior_ma5_low_touch = _support_low_touch(
        _price_to_ma_distance_pct(
            lows[-2] if len(lows) >= 2 else None,
            prior_ma5,
        ),
        prior_ma5_close_distance,
    )

    # 排名诊断特征：K 线安静度与趋势过伸。
    prev_close_price = closes[-2] if len(closes) >= 2 else None
    signal_day_limit_up_closed = bool(
        prev_close_price is not None
        and close_price is not None
        and is_main_board_limit_up_touched(prev_close_price, close_price)
    )
    candle_range_pct = None
    if prev_close_price is not None and prev_close_price > 0:
        candle_range_pct = _round_pct(
            (high_price - low_price) / prev_close_price * 100
        )
    candle_quiet = bool(
        candle_range_pct is not None
        and candle_range_pct <= TREND_CANDLE_QUIET_RANGE_MAX_PCT
    )
    controlled_attack_body_retest_candle = bool(
        daily_return is not None
        and ATTACK_BODY_HOLD_DAILY_RETURN_MIN_PCT
        <= daily_return
        <= ATTACK_BODY_HOLD_DAILY_RETURN_MAX_PCT
        and candle_quiet
    )
    ma5_ma10_dist_series: list[float | None] = [
        (
            _round_pct((fast / slow - 1) * 100)
            if fast is not None and slow is not None and slow > 0
            else None
        )
        for fast, slow in zip(ma_series[5], ma_series[10])
    ]
    # 过伸段定义：三线完整多头（MA5>MA10>MA20>MA30）+ MA60 跟随向上（不要求 MA60 在排列内）。
    # MA60 仅作大趋势方向确认 —— 跟随向上才启用过伸统计，避免误杀长期下跌刚转势、MA60 仍在下方的启动票。
    full_bull_history = tuple(
        bool(
            ma_series[5][index] is not None
            and ma_series[10][index] is not None
            and ma_series[20][index] is not None
            and ma_series[30][index] is not None
            and ma_series[5][index]
            > ma_series[10][index]
            > ma_series[20][index]
            > ma_series[30][index]
            and index >= 5
            and ma_series[60][index] is not None
            and ma_series[60][index - 5] is not None
            and ma_series[60][index] > ma_series[60][index - 5]
        )
        for index in range(len(closes))
    )
    trend_dist_excess = None
    if full_bull_history and full_bull_history[-1]:
        segment_start = len(closes) - 1
        while segment_start > 0 and full_bull_history[segment_start - 1]:
            segment_start -= 1
        pullback_dists: list[float] = []
        for index in range(segment_start, len(closes) - 1):
            ma5_at_index = ma_series[5][index]
            if ma5_at_index is not None and _support_low_touch(
                _price_to_ma_distance_pct(lows[index], ma5_at_index),
                _price_to_ma_distance_pct(closes[index], ma5_at_index),
            ):
                dist = ma5_ma10_dist_series[index]
                if dist is not None:
                    pullback_dists.append(dist)
        current_dist = ma5_ma10_dist_series[-1]
        if pullback_dists and current_dist is not None:
            trend_dist_excess = _round_pct(current_dist - median(pullback_dists))
    trend_overextended = bool(
        trend_dist_excess is not None
        and trend_dist_excess >= TREND_DIST_EXCESS_MAX_PCT
    )
    trend_first_crack_chase = bool(
        not candle_quiet
        and close_to_ma5 is not None
        and close_to_ma5 >= 0
        and prior_daily_return is not None
        and prior_daily_return > 0
    )

    features = {
        **base,
        **pre_attack_base_features,
        "ma10_ma20_signed_distance_pct": distance_10_20,
        "ma10_ma20_convergence_efficiency_5d": (
            ma10_ma20_convergence_efficiency_5d
        ),
        "ma10_ma20_next_close_required_return_pct": (
            ma10_ma20_next_close_required_return
        ),
        "ma10_ma30_next_close_required_return_pct": (
            ma10_ma30_next_close_required_return
        ),
        "ma10_ma30_signed_distance_pct": distance_10_30,
        "ma20_ma30_signed_distance_pct": distance_20_30,
        "intraday_midpoint_price": intraday_midpoint_price,
        "midpoint_to_ma5_pct": midpoint_to_ma5,
        "midpoint_to_ma10_pct": midpoint_to_ma10,
        "ma10_crossed_ma20_age_sessions": cross_10_20_age,
        "ma10_crossed_ma30_age_sessions": cross_10_30_age,
        "ma20_crossed_ma30_age_sessions": cross_20_30_age,
        "ma10_crossed_ma20_within_5d": cross_10_20_age is not None,
        "ma10_crossed_ma30_within_5d": cross_10_30_age is not None,
        "ma20_crossed_ma30_within_5d": cross_20_30_age is not None,
        "ma10_crossed_ma20_age_sessions_15d": process_cross_10_20_age,
        "ma10_crossed_ma30_age_sessions_15d": process_cross_10_30_age,
        "ma10_crossed_ma20_within_15d": process_cross_10_20_age is not None,
        "ma10_crossed_ma30_within_15d": process_cross_10_30_age is not None,
        "ma10_crossed_ma20_after_long_bear_age_sessions_15d": (
            cross_10_20_after_long_bear_age
        ),
        "ma10_crossed_ma20_after_long_bear_within_15d": (
            cross_10_20_after_long_bear_age is not None
        ),
        "ma10_dual_cross_within_15d": ma10_dual_cross_within_15d,
        "ma10_dual_cross_within_7d": ma10_dual_cross_within_7d,
        "ma10_above_ma20_and_ma30": ma10_above_ma20_and_ma30,
        "ma10_ma20_near_or_recent_cross": _near_or_recent_cross(distance_10_20),
        "ma10_ma20_contact": _ma_contact(distance_10_20),
        "ma10_below_ma20": bool(
            ma10 is not None and ma20 is not None and ma10 < ma20
        ),
        "ma10_above_ma20": bool(
            ma10 is not None and ma20 is not None and ma10 > ma20
        ),
        "ma10_below_ma30": bool(
            ma10 is not None and ma30 is not None and ma10 < ma30
        ),
        "current_full_bear_alignment": bool(
            ma10 is not None
            and ma20 is not None
            and ma30 is not None
            and ma10 < ma20 < ma30
        ),
        "close_below_ma30": bool(
            close_price is not None and ma30 is not None and close_price < ma30
        ),
        "ma10_ma30_near_or_recent_cross": _near_or_recent_cross(distance_10_30),
        "ma20_ma30_near_or_recent_cross": _near_or_recent_cross(distance_20_30),
        "ma10_ma30_contact": _ma_contact(distance_10_30),
        "ma20_ma30_contact": ma20_ma30_contact,
        "transition_ma20_ma30_tight_contact": transition_ma20_ma30_tight_contact,
        "ma_cluster_convergence_speed_5d_pct": _difference_or_none(
            prior_spread,
            current_spread,
        ),
        "ma_cluster_converging_5d": bool(
            current_spread is not None
            and prior_spread is not None
            and current_spread <= prior_spread
        ),
        "volume_shape": _volume_shape(base),
        "price_state": _daily_price_state(daily_return),
        "positive_candle": bool(daily_return is not None and daily_return > 0),
        "small_positive_candle": small_positive_candle,
        "oversold_process_eligible": bool(
            ma10 is not None
            and ma20 is not None
            and ma30 is not None
            and int(base.get("prior_bear_alignment_days") or 0) >= 5
            and daily_return is not None
            and OVERSOLD_PROCESS_DAILY_RETURN_MIN_PCT <= daily_return <= 3.0
        ),
        "long_bear_alignment": long_bear_alignment,
        "recent_pullback_from_high_pct": recent_pullback_from_high_pct,
        "post_cross_pullback": bool(
            post_cross_pullback
        ),
        "aggressive_pullback": bool(
            daily_return is not None and daily_return <= -5.0
        ),
        "staged_m10_first": bool(
            cross_10_20_age is not None
            and cross_20_30_age is None
            and ma20 is not None
            and ma30 is not None
            and ma20 < ma30
        ),
        "m10_dual_cross_before_m20_m30": m10_dual_cross_before_m20_m30,
        "ma10_ma20_slopes_up": ma10_ma20_slopes_up,
        "ma10_slope_2d_pct": ma10_slope_2d,
        "ma10_slope_improvement_2d_pct": ma10_slope_improvement_2d,
        "ma10_ma20_gap_narrowing_3d_pct": ma10_ma20_gap_narrowing_3d,
        "ma10_ma20_gap_narrowing": bool(
            ma10_ma20_gap_narrowing_3d is not None
            and ma10_ma20_gap_narrowing_3d > 0
        ),
        "ma10_ma30_gap_narrowing_5d_pct": ma10_ma30_gap_narrowing_5d,
        "ma10_ma30_gap_converging": bool(
            ma10_ma30_gap_narrowing_5d is not None
            and ma10_ma30_gap_narrowing_5d >= MA10_MA30_CONVERGENCE_MIN_PCT
        ),
        "ma10_ma30_fast_convergence": bool(
            ma10_ma30_gap_narrowing_5d is not None
            and ma10_ma30_gap_narrowing_5d
            >= MA10_MA30_FAST_CONVERGENCE_MIN_PCT
        ),
        "ma10_was_above_ma30_within_15d": _was_ma_above_within(
            closes,
            fast_window=10,
            slow_window=30,
            lookback=PROCESS_CROSS_LOOKBACK,
        ),
        "last_volume_change_pct": last_volume_change_pct,
        "last_volume_to_prior_ratio": last_volume_to_prior_ratio,
        "last_volume_expanded": bool(
            last_volume_change_pct is not None
            and last_volume_change_pct >= PROCESS_VOLUME_CHANGE_PCT
        ),
        "last_volume_shrank": bool(
            last_volume_change_pct is not None
            and last_volume_change_pct <= -PROCESS_VOLUME_CHANGE_PCT
        ),
        "volume_expand_then_shrink": _two_leg_volume_shape(
            volumes,
            first_direction="expand",
            first_length=5,
            second_direction="shrink",
            second_length=5,
        ),
        "volume_shrink_then_expand": _two_leg_volume_shape(
            volumes,
            first_direction="shrink",
            first_length=5,
            second_direction="expand",
            second_length=4,
        ),
        "trend_bull_alignment": trend_bull_alignment,
        "trend_all_slopes_up": trend_all_slopes_up,
        "trend_slope_mean_5d_pct": trend_slope_mean,
        "trend_slope_profile": (
            "gentle"
            if trend_slope_mean is not None and trend_slope_mean <= TREND_GENTLE_SLOPE_MAX_PCT
            else "steep"
            if trend_slope_mean is not None
            else "unavailable"
        ),
        "trend_stable_bull": bool(
            trend_bull_alignment and bull_alignment_days >= 5
        ),
        "early_trend_alignment": bool(
            trend_bull_alignment
            and EARLY_TREND_ALIGNMENT_MIN_SESSIONS
            <= bull_alignment_days
            <= EARLY_TREND_ALIGNMENT_MAX_SESSIONS
        ),
        "trend_rebuilt_recently": bool(
            trend_bull_alignment and 5 <= bull_alignment_days <= 10
        ),
        "trend_rebuilt_from_disorder": bool(
            trend_bull_alignment
            and EARLY_TREND_ALIGNMENT_MIN_SESSIONS
            <= bull_alignment_days
            <= 10
            and len(prior_regime) >= TREND_REBUILD_MIN_DISORDERED_SESSIONS
            and prior_disordered_sessions >= TREND_REBUILD_MIN_DISORDERED_SESSIONS
        ),
        "prior_disordered_sessions_before_trend": prior_disordered_sessions,
        "trend_discovery_eligible": bool(
            trend_bull_alignment
            and trend_all_slopes_up
            and daily_return is not None
            and daily_return <= 3.0
        ),
        "trend_transition_preparation_eligible": (
            trend_transition_preparation_eligible
        ),
        "trend_transition_eligible": trend_transition_eligible,
        "ma5_low_touch": ma5_low_touch,
        "ma5_low_touch_broad": ma5_low_touch_broad,
        "ma10_low_touch": ma10_low_touch,
        "ma5_close_near": ma5_close_near,
        "ma10_close_near": ma10_close_near,
        "ma5_midpoint_near": ma5_midpoint_near,
        "ma10_midpoint_near": ma10_midpoint_near,
        "low_to_ma20_pct": low_to_ma20,
        "low_to_ma10_pct": _number_or_none(base.get("low_to_ma10_pct")),
        "close_to_ma10_pct": close_to_ma10,
        "low_to_ma30_pct": low_to_ma30,
        "close_to_ma20_pct": close_to_ma20,
        "close_to_ma30_pct": close_to_ma30,
        "ma20_low_touch": ma20_low_touch,
        "ma30_low_touch": ma30_low_touch,
        "oversold_low_support": bool(
            ma10_low_touch or ma20_low_touch or ma30_low_touch
        ),
        "close_off_low_pct": close_off_low_pct,
        "support_close_reaction": support_close_reaction,
        "turnover_rate_low": turnover_rate_low,
        "capitulation_rebound_tight": capitulation_rebound_tight,
        "capitulation_rebound_broad": capitulation_rebound_broad,
        "yang_wrap_three_ma": yang_wrap_three_ma,
        "yang_wrap_two_ma": yang_wrap_two_ma,
        "yang_wrap_nearest_ma_low_abs_pct": yang_wrap_nearest_ma_low_abs_pct,
        "yang_wrap_volume_end_to_peak_ratio_6d": yang_wrap_volume_end_to_peak_ratio_6d,
        "yang_wrap_stable_base": yang_wrap_stable_base,
        "ma10_slope_cv_6d": (
            _round_pct(ma10_slope_cv_6d) if ma10_slope_cv_6d is not None else None
        ),
        "vol_monotone_6d": vol_monotone_6d,
        "body_max_excl_6d": (
            _round_pct(body_max_excl_6d) if body_max_excl_6d is not None else None
        ),
        "breakout_hold_premium": (
            _round_pct(breakout_hold_premium) if breakout_hold_premium is not None else None
        ),
        "turnover_rate_pct": turnover_rate,
        "prior_ma5_close_distance_pct": prior_ma5_close_distance,
        "prior_daily_return_pct": (
            _round_pct(prior_daily_return)
            if prior_daily_return is not None
            else None
        ),
        "prior_ma5_close_extension": bool(
            prior_ma5_close_distance is not None
            and prior_ma5_close_distance >= MA5_EXTENSION_MIN_PCT
        ),
        "prior_daily_price_not_up": bool(
            prior_daily_return is not None and prior_daily_return <= 0
        ),
        "prior_ma5_low_touch": prior_ma5_low_touch,
        "close_to_ma5_pct": close_to_ma5,
        "trend_dist_excess_pct": trend_dist_excess,
        "candle_range_pct": candle_range_pct,
        "candle_quiet": candle_quiet,
        "signal_day_not_limit_up_closed": not signal_day_limit_up_closed,
        "prior_attack_open_price": prior_attack_open_price,
        "prior_positive_body_pct": prior_positive_body_pct,
        "prior_limit_up_touched": prior_limit_up_touched,
        "attack_body_low_held": attack_body_low_held,
        "attack_body_close_held": attack_body_close_held,
        "controlled_attack_body_retest_candle": (
            controlled_attack_body_retest_candle
        ),
        "trend_overextended": trend_overextended,
        "trend_first_crack_chase": trend_first_crack_chase,
    }
    return features


def score_extended_factor(
    features: Mapping[str, object],
    setup_type: str,
    *,
    prior_features: Mapping[str, object] | None = None,
) -> dict[str, float]:
    """Score source-derived daily features without consulting future returns.

    The score is a ranking layer on top of a family-specific process signal,
    not an outcome-trained model. Both base scores live on 0..100. The
    transition variant leaves ordinary trend pullback scoring unchanged and
    adds only the post-cross source-defined oversold-to-trend geometry. The earlier
    MA10/20 preparation remains a separately reported source hypothesis until
    it passes the time-split gate.
    """

    daily_return = _number_or_none(features.get("daily_return_pct"))
    if setup_type == "oversold_rebound":
        regime = bool(features.get("long_bear_alignment"))
        transition = any(
            bool(features.get(field))
            for field in (
                "staged_m10_first",
                "ma10_crossed_ma30_within_15d",
            )
        )
        convergence = any(
            bool(features.get(field))
            for field in (
                "ma10_ma30_gap_converging",
                "ma20_ma30_contact",
                "ma10_ma30_contact",
            )
        )
        pullback = bool(
            daily_return is not None
            and -10.0 <= daily_return <= 3.0
            and any(
                bool(features.get(field))
                for field in (
                    "ma10_low_touch",
                    "post_cross_pullback",
                    "aggressive_pullback",
                )
            )
        )
        source_process = _matches_explicit_process_geometry(
            features,
            setup_type,
            prior_features=prior_features,
        )
        base = _round_pct(
            20.0 * sum((regime, transition, convergence, pullback, source_process))
        )
        volume = bool(
            source_process
            and _matches_explicit_process_with_volume(
                features,
                setup_type,
                prior_features=prior_features,
            )
        )
        return {
            "base": base,
            "with_volume": _round_pct(base * 0.8 + (20.0 if volume else 0.0)),
        }

    if setup_type == "trend_pullback":
        regime = bool(
            features.get("trend_bull_alignment")
            and features.get("trend_all_slopes_up")
        )
        maturity = bool(
            features.get("trend_stable_bull")
            or features.get("early_trend_alignment")
        )
        ma5_regular = bool(features.get("ma5_regular"))
        support = bool(
            (ma5_regular and features.get("ma5_low_touch"))
            or (not ma5_regular and features.get("ma10_low_touch"))
            or (
                ma5_regular
                and features.get("ma10_low_touch")
                and features.get("prior_ma5_close_extension")
            )
            or (ma5_regular and features.get("ma5_low_touch_broad"))
        )
        context = bool(
            features.get("trend_rebuilt_from_disorder")
            or features.get("prior_ma5_low_touch")
            or features.get("trend_stable_bull")
        )
        source_process = _matches_explicit_process_geometry(
            features,
            setup_type,
            prior_features=prior_features,
        )
        base = _round_pct(
            20.0 * sum((regime, maturity, support, context, source_process))
        )
        post_cross_transition = bool(features.get("trend_transition_eligible"))
        transition_bonus = 20.0 if post_cross_transition else 0.0
        transition_volume_bonus = 20.0 if (
            post_cross_transition and features.get("volume_expand_then_shrink")
        ) else 0.0
        return {
            "base": base,
            "with_transition_bonus": _round_pct(
                min(100.0, base + transition_bonus + transition_volume_bonus)
            ),
        }

    raise DailyFactorInputError(
        f"unsupported extended score setup type: {setup_type}"
    )


def matching_discovery_rule_keys(
    features: Mapping[str, object],
    setup_type: str,
    *,
    prior_features: Mapping[str, object] | None = None,
) -> tuple[str, ...]:
    """Return declared rules matched by D-and-earlier current/prior snapshots."""

    rules = DISCOVERY_RULES.get(setup_type)
    if rules is None:
        raise DailyFactorInputError(f"unsupported discovery setup type: {setup_type}")
    return tuple(
        rule.key
        for rule in rules
        if _rule_matches(rule, features, prior_features=prior_features)
    )


def summarize_rule_observations(
    observations: Iterable[Mapping[str, object]],
    market_calendar: Sequence[date],
    *,
    rule_manifest: Mapping[str, Sequence[DiscoveryRule]] = DISCOVERY_RULES,
    frozen_rule_keys: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Aggregate a finite manifest with development or explicitly frozen selection."""

    calendar = _strict_calendar(market_calendar)
    split = split_market_calendar(calendar)
    segment_by_date = _segment_dates(split)
    manifest = _normalized_manifest(rule_manifest)
    normalized_frozen_rule_keys = _normalize_frozen_rule_keys(
        frozen_rule_keys,
        manifest,
    )
    accumulators = {
        setup_type: {
            rule.key: {
                "overall": _RuleAccumulator(),
                **{segment: _RuleAccumulator() for segment in SEGMENTS},
            }
            for rule in rules
        }
        for setup_type, rules in manifest.items()
    }
    pre_attack_base_observations: list[Mapping[str, object]] = []
    for observation in observations:
        setup_type = str(observation.get("setup_type") or "")
        rule_key = str(observation.get("rule_key") or "")
        if rule_key == ATTACK_BODY_HOLD_RULE_KEY:
            pre_attack_base_observations.append(observation)
        family = accumulators.get(setup_type)
        if family is None or rule_key not in family:
            continue
        family[rule_key]["overall"].add(observation)
        trade_date = _required_date(observation.get("trade_date"))
        segment = segment_by_date.get(trade_date)
        if segment is not None:
            family[rule_key][segment].add(observation)

    families: dict[str, dict[str, object]] = {}
    for setup_type in SETUP_TYPES:
        rules = manifest[setup_type]
        rendered_rules = [
            {
                "key": rule.key,
                "description": rule.description,
                "overall": _render_rule_aggregate(
                    accumulators[setup_type][rule.key]["overall"]
                ),
                "segments": {
                    segment: {
                        "overall": _render_rule_aggregate(
                            accumulators[setup_type][rule.key][segment]
                        )
                    }
                    for segment in SEGMENTS
                },
            }
            for rule in rules
        ]
        selected = (
            _select_frozen_rule(
                rendered_rules,
                normalized_frozen_rule_keys[setup_type],
            )
            if setup_type in normalized_frozen_rule_keys
            else _select_rule(rendered_rules)
        )
        selected_key = str(selected.get("key") or "")
        if selected_key:
            for rendered_rule in rendered_rules:
                if rendered_rule["key"] == selected_key:
                    rendered_rule["full"] = accumulators[setup_type][selected_key][
                        "overall"
                    ].render()
                    break
        families[setup_type] = {
            "rules": rendered_rules,
            "selected_rule": selected,
        }
    return {
        "time_split": _time_split_payload(split),
        "selection_protocol": {
            "mode": (
                FROZEN_SELECTION_MODE
                if normalized_frozen_rule_keys
                else DEVELOPMENT_SELECTION_MODE
            ),
            "frozen_rule_keys": normalized_frozen_rule_keys,
        },
        "families": families,
        "pre_attack_base_process": summarize_pre_attack_base_process_observations(
            pre_attack_base_observations
        ),
    }


def summarize_pre_attack_base_process_observations(
    observations: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Describe D+1 outcomes by causal base path without selecting a rule."""

    phase_accumulators: dict[str, _ReturnAccumulator] = defaultdict(
        _ReturnAccumulator
    )
    comparable_by_date: dict[date, list[tuple[str, float]]] = defaultdict(list)
    candidate_count = 0
    excluded_price_limit_count = 0
    for observation in observations:
        if str(observation.get("rule_key") or "") != ATTACK_BODY_HOLD_RULE_KEY:
            continue
        candidate_count += 1
        if (
            str(observation.get("d1_label_status") or "available")
            == "label_excluded_main_board_price_limit"
        ):
            excluded_price_limit_count += 1
            continue
        phase = str(observation.get("pre_attack_base_phase") or "insufficient_history")
        trade_date = _required_date(observation.get("trade_date"))
        value = _number_or_none(observation.get("d1_close_return_pct"))
        phase_accumulators[phase].add(trade_date, value)
        if value is not None:
            comparable_by_date[trade_date].append((phase, value))

    excess_values: dict[str, list[float]] = defaultdict(list)
    excess_dates: dict[str, set[date]] = defaultdict(set)
    for trade_date, values in comparable_by_date.items():
        if len(values) < 2:
            continue
        total = sum(value for _, value in values)
        for phase, value in values:
            excess_values[phase].append((value - (total - value) / (len(values) - 1)))
            excess_dates[phase].add(trade_date)

    return {
        "feature_cutoff": "D-2（D-1 攻击实体与 D 信号不参与底盘特征）",
        "candidate_count": candidate_count,
        "label_excluded_main_board_price_limit_count": excluded_price_limit_count,
        "phase_groups": [
            {
                "phase": phase,
                **accumulator.summary(),
                "same_day_excess": _same_day_excess_summary(
                    excess_values[phase],
                    excess_dates[phase],
                ),
            }
            for phase, accumulator in sorted(phase_accumulators.items())
        ],
    }


def _same_day_excess_summary(
    values: Sequence[float],
    dates: set[date],
) -> dict[str, object]:
    return {
        "sample_count": len(values),
        "candidate_days": len(dates),
        "win_rate_pct": _rate_pct(sum(value > 0 for value in values), len(values)),
        "mean_return_pct": _round_pct(fmean(values)) if values else None,
        "median_return_pct": _round_pct(median(values)) if values else None,
    }


def summarize_score_observations(
    observations: Iterable[Mapping[str, object]],
    market_calendar: Sequence[date],
    *,
    source_case_bands: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
) -> dict[str, object]:
    """Select one preregistered factor score range using development only."""

    calendar = _strict_calendar(market_calendar)
    split = split_market_calendar(calendar)
    segment_by_date = _segment_dates(split)
    normalized_source_case_bands = _normalize_source_case_bands(source_case_bands)
    accumulators = {
        setup_type: {
            variant: {
                band: {
                    "overall": _RuleAccumulator(),
                    **{segment: _RuleAccumulator() for segment in SEGMENTS},
                }
                for _, _, band in SCORE_BANDS
            }
            for variant in SCORE_VARIANTS_BY_SETUP[setup_type]
        }
        for setup_type in SETUP_TYPES
    }
    for observation in observations:
        setup_type = str(observation.get("setup_type") or "")
        variant = str(observation.get("score_variant") or "")
        family = accumulators.get(setup_type)
        if family is None or variant not in family:
            continue
        score = _number_or_none(observation.get("score"))
        band = _score_band(score)
        if band is None:
            continue
        family[variant][band]["overall"].add(observation)
        segment = segment_by_date.get(_required_date(observation.get("trade_date")))
        if segment is not None:
            family[variant][band][segment].add(observation)

    families: dict[str, dict[str, object]] = {}
    for setup_type in SETUP_TYPES:
        rendered_variants = []
        for variant in SCORE_VARIANTS_BY_SETUP[setup_type]:
            rendered_bands = [
                {
                    "band": band,
                    "overall": _render_rule_aggregate(
                        accumulators[setup_type][variant][band]["overall"]
                    ),
                    "segments": {
                        segment: {
                            "overall": _render_rule_aggregate(
                                accumulators[setup_type][variant][band][segment]
                            )
                        }
                        for segment in SEGMENTS
                    },
                }
                for _, _, band in SCORE_BANDS
            ]
            rendered_variants.append(
                {
                    "variant": variant,
                    "bands": rendered_bands,
                }
            )
        selected = _select_score_factor(
            rendered_variants,
            source_case_bands=normalized_source_case_bands[setup_type],
        )
        selected_variant = str(selected.get("variant") or "")
        selected_band = str(selected.get("band") or "")
        if selected_variant and selected_band:
            selected_accumulator = accumulators[setup_type][selected_variant][
                selected_band
            ]["overall"]
            for variant in rendered_variants:
                if variant["variant"] != selected_variant:
                    continue
                for band in variant["bands"]:
                    if band["band"] == selected_band:
                        band["full"] = selected_accumulator.render()
                        break
        families[setup_type] = {
            "variants": rendered_variants,
            "selected_score_factor": selected,
            "source_case_bands": {
                variant: list(bands)
                for variant, bands in normalized_source_case_bands[setup_type].items()
            },
        }
    return {
        "time_split": _time_split_payload(split),
        "families": families,
    }


def select_exit_probe(
    exit_rows: Iterable[Mapping[str, object]],
    *,
    market_calendar: Sequence[date],
    require_triggered_coverage: bool = False,
) -> dict[str, object]:
    """Select one declared exit probe from development data only."""

    calendar = _strict_calendar(market_calendar)
    split = split_market_calendar(calendar)
    segment_by_date = _segment_dates(split)
    accumulators: dict[str, dict[str, _ExitAccumulator]] = defaultdict(
        lambda: {
            "overall": _ExitAccumulator(),
            **{segment: _ExitAccumulator() for segment in SEGMENTS},
        }
    )
    for row in exit_rows:
        probe = str(row.get("probe") or "")
        if not probe:
            continue
        accumulators[probe]["overall"].add(row)
        segment = segment_by_date.get(_required_date(row.get("trade_date")))
        if segment is not None:
            accumulators[probe][segment].add(row)

    probes = [
        {
            "probe": probe,
            "overall": values["overall"].summary(),
            "segments": {
                segment: values[segment].summary()
                for segment in SEGMENTS
            },
        }
        for probe, values in sorted(accumulators.items())
    ]
    eligible = [
        row
        for row in probes
        if int(row["segments"]["development"]["sample_count"]) >= MIN_SELECTION_SAMPLES
        and int(
            row["segments"]["development"][
                "triggered_candidate_days"
                if require_triggered_coverage
                else "candidate_days"
            ]
        )
        >= MIN_SELECTION_CANDIDATE_DAYS
    ]
    selected = max(
        eligible,
        key=lambda row: (
            float(row["segments"]["development"]["mean_return_pct"]),
            float(row["segments"]["development"]["win_rate_pct"] or 0),
            int(row["segments"]["development"]["sample_count"]),
            str(row["probe"]),
        ),
    ) if eligible else None
    development = (
        selected["segments"]["development"]
        if selected is not None
        else _empty_exit_summary()
    )
    validation = (
        selected["segments"]["validation"]
        if selected is not None
        else _empty_exit_summary()
    )
    holdout = (
        selected["segments"]["holdout"]
        if selected is not None
        else _empty_exit_summary()
    )
    return {
        "probes": probes,
        "selected_probe": selected["probe"] if selected is not None else None,
        "development": development,
        "validation": validation,
        "holdout": holdout,
        "qualification_gate": _exit_qualification_gate(
            validation,
            holdout,
            selected_probe=selected["probe"] if selected is not None else None,
            require_triggered_coverage=require_triggered_coverage,
        ),
    }


def evaluate_post_limit_up_hold(
    candidate: Mapping[str, object],
    future_bars: Sequence[Mapping[str, object]],
    *,
    holding_sessions: int,
) -> dict[str, object]:
    """Exit N sessions after the first strict limit-up close in the first five days."""

    entry_date = _required_date(candidate.get("entry_date"))
    entry_price = _required_positive_number(candidate.get("entry_price"), "entry_price")
    probe = f"first_limit_up_close_hold_{holding_sessions}"
    base = {
        "probe": probe,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "exit_price_mode": "close",
        "return_basis": "post_limit_up_close_to_exit_close",
        "status": "unavailable",
        "first_limit_up_close_date": None,
        "first_limit_up_close_price": None,
        "exit_date": None,
        "exit_price": None,
        "return_pct": None,
        "entry_to_limit_up_sessions": None,
        "entry_to_exit_return_pct": None,
        "post_limit_up_return_pct": None,
        "holding_sessions": None,
        "exit_reason": None,
    }
    if holding_sessions < 1:
        return {**base, "exit_reason": "invalid_holding_sessions"}
    normalized = tuple(sorted(future_bars, key=lambda row: _required_date(row.get("trade_date"))))
    prior_close = entry_price
    first_limit_up_index: int | None = None
    first_limit_up_date: date | None = None
    first_limit_up_close_price: float | None = None
    for index, row in enumerate(normalized):
        if first_limit_up_index is None and index >= 5:
            break
        if first_limit_up_index is not None and index > first_limit_up_index + holding_sessions:
            break
        trade_date = _required_date(row.get("trade_date"))
        if trade_date <= entry_date:
            return {**base, "exit_reason": "future_bar_not_after_entry"}
        close_price = _number_or_none(row.get("close_price"))
        if close_price is None or close_price <= 0:
            return {**base, "exit_reason": "missing_exit_price"}
        if not is_main_board_close_within_price_limit(prior_close, close_price):
            return {**base, "exit_reason": "raw_price_limit_outlier"}
        if (
            first_limit_up_index is None
            and index < 5
            and is_main_board_limit_up_touched(prior_close, close_price)
        ):
            first_limit_up_index = index
            first_limit_up_date = trade_date
            first_limit_up_close_price = close_price
        prior_close = close_price
    if first_limit_up_index is None:
        if len(normalized) < 5:
            return {
                **base,
                "exit_reason": "missing_limit_up_search_window",
            }
        return {
            **base,
            "status": "not_triggered",
            "exit_reason": "no_limit_up_close_within_5_sessions",
        }
    exit_index = first_limit_up_index + holding_sessions
    if exit_index >= len(normalized):
        return {
            **base,
            "first_limit_up_close_date": first_limit_up_date,
            "exit_reason": "missing_post_limit_up_session",
        }
    exit_row = normalized[exit_index]
    exit_date = _required_date(exit_row.get("trade_date"))
    exit_price = _required_positive_number(exit_row.get("close_price"), "exit_price")
    if first_limit_up_close_price is None:
        raise DailyFactorInputError("first limit-up close price is required")
    entry_to_exit_return_pct = _round_pct(_pct_change(exit_price, entry_price))
    post_limit_up_return_pct = _round_pct(
        _pct_change(exit_price, first_limit_up_close_price)
    )
    return {
        **base,
        "status": "closed",
        "first_limit_up_close_date": first_limit_up_date,
        "first_limit_up_close_price": first_limit_up_close_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "return_pct": post_limit_up_return_pct,
        "entry_to_limit_up_sessions": first_limit_up_index + 1,
        "entry_to_exit_return_pct": entry_to_exit_return_pct,
        "post_limit_up_return_pct": post_limit_up_return_pct,
        "holding_sessions": holding_sessions,
        "exit_reason": "post_limit_up_fixed_horizon",
    }


def run_extended_daily_factor_discovery(
    *,
    bars: Any,
    market_calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
    evidence_level: str,
    blockers: Sequence[str],
    coverage: Mapping[str, object],
    input_sha256: str,
    frozen_rule_keys: Mapping[str, str] | None = None,
    include_exit_evidence: bool = True,
) -> dict[str, object]:
    """Run the preregistered extension without provider calls or database writes."""

    normalized_blockers = tuple(sorted({str(value) for value in blockers if str(value)}))
    report: dict[str, object] = {
        "research_version": "low-suction-daily-factor-extended-discovery-v6",
        "evidence_level": evidence_level,
        "input_sha256": input_sha256,
        "coverage": dict(coverage),
        "blockers": list(normalized_blockers),
        "manifest": {
            setup_type: [
                {
                    "key": rule.key,
                    "description": rule.description,
                }
                for rule in rules
            ]
            for setup_type, rules in DISCOVERY_RULES.items()
        },
        "qualification_thresholds": {
            "minimum_validation_samples": MIN_QUALIFICATION_SAMPLES,
            "minimum_holdout_samples": MIN_QUALIFICATION_SAMPLES,
            "minimum_candidate_days_per_segment": MIN_QUALIFICATION_CANDIDATE_DAYS,
            "validation_and_holdout_d1_mean_return_pct": "> 0",
            "exit_validation_and_holdout_mean_return_pct": "> 0",
        },
        "score_factors": _empty_score_factors(),
        "case_score_membership": {},
        "qualified_score_factors": [],
        "full_history_score_gate": _empty_full_history_score_gate(),
        "pre_attack_base_process": summarize_pre_attack_base_process_observations(
            ()
        ),
    }
    try:
        normalized_frozen_rule_keys = _normalize_frozen_rule_keys(
            frozen_rule_keys,
            _normalized_manifest(DISCOVERY_RULES),
        )
    except DailyFactorInputError as exc:
        report.update(
            {
                "status": "blocked",
                "conclusion": "invalid_frozen_rule_keys",
                "blockers": [*normalized_blockers, str(exc)],
                "time_split": None,
                "selection_protocol": {
                    "mode": "invalid_frozen_rule_keys",
                    "frozen_rule_keys": {},
                },
                "families": _empty_families(),
                "score_factors": _empty_score_factors(),
                "case_score_membership": {},
                "qualified_score_factors": [],
                "full_history_score_gate": _empty_full_history_score_gate(),
                "research_answers": [],
                "qualified_rules": [],
            }
        )
        report["research_answers"] = _research_answers(report)
        return report
    report["selection_protocol"] = {
        "mode": (
            FROZEN_SELECTION_MODE
            if normalized_frozen_rule_keys
            else DEVELOPMENT_SELECTION_MODE
        ),
        "frozen_rule_keys": normalized_frozen_rule_keys,
        "include_exit_evidence": include_exit_evidence,
    }
    if normalized_blockers:
        report.update(
            {
                "status": "blocked",
                "conclusion": "data_blocker",
                "time_split": None,
                "families": _empty_families(),
                "score_factors": _empty_score_factors(),
                "case_score_membership": {},
                "qualified_score_factors": [],
                "full_history_score_gate": _empty_full_history_score_gate(),
                "research_answers": [],
                "qualified_rules": [],
            }
        )
        report["research_answers"] = _research_answers(report)
        return report

    try:
        calendar = _strict_calendar(market_calendar)
        summary = summarize_rule_observations(
            _iter_rule_observations(bars, calendar, security_status),
            calendar,
            frozen_rule_keys=normalized_frozen_rule_keys,
        )
        case_score_profiles = _collect_case_score_profiles(
            bars,
            calendar,
        )
        score_summary = summarize_score_observations(
            _iter_score_observations(bars, calendar, security_status),
            calendar,
            source_case_bands=_source_case_bands(case_score_profiles),
        )
        case_score_membership = _attach_case_score_selection(
            case_score_profiles,
            score_summary["families"],
        )
    except DailyFactorInputError as exc:
        report.update(
            {
                "status": "blocked",
                "conclusion": "data_blocker",
                "blockers": [*normalized_blockers, str(exc)],
                "time_split": None,
                "families": _empty_families(),
                "research_answers": [],
                "qualified_rules": [],
            }
        )
        report["research_answers"] = _research_answers(report)
        return report

    selected_rules = {
        setup_type: str(family["selected_rule"].get("key") or "")
        for setup_type, family in summary["families"].items()
        if isinstance(family, Mapping)
        and isinstance(family.get("selected_rule"), Mapping)
        and family["selected_rule"].get("key")
    }
    exit_evidence = (
        _collect_selected_exit_evidence(
            bars,
            calendar,
            security_status,
            selected_rules,
        )
        if include_exit_evidence
        else {}
    )
    for setup_type, family in summary["families"].items():
        selected = family.get("selected_rule")
        if not isinstance(selected, dict):
            continue
        family_exits = exit_evidence.get(setup_type, {})
        selected["exit_selection"] = family_exits.get("standard", _empty_exit_selection())
        selected["post_limit_up_exit_selection"] = family_exits.get(
            "post_limit_up",
            _empty_exit_selection(),
        )

    candidates = [
        {
            "setup_type": setup_type,
            "rule_key": family["selected_rule"]["key"],
            "validation": family["selected_rule"]["validation"],
            "holdout": family["selected_rule"]["holdout"],
        }
        for setup_type, family in summary["families"].items()
        if isinstance(family.get("selected_rule"), Mapping)
        and family["selected_rule"].get("qualification_gate", {}).get("passed")
    ]
    qualified_score_factors = [
        {
            "setup_type": setup_type,
            "variant": selected.get("variant"),
            "band": selected.get("band"),
            "validation": selected.get("validation"),
            "holdout": selected.get("holdout"),
        }
        for setup_type, family in score_summary["families"].items()
        if isinstance(family, Mapping)
        and isinstance(family.get("selected_score_factor"), Mapping)
        and (selected := family["selected_score_factor"]).get("qualification_gate", {}).get(
            "passed"
        )
    ]
    full_history_score_gate = _score_full_history_gate(score_summary["families"])
    if evidence_level != "strict":
        conclusion, status = "exploratory_only", "exploratory_complete"
        qualified_rules: list[dict[str, object]] = []
    elif candidates:
        conclusion, status = "time_validated_candidate", "complete"
        qualified_rules = candidates
    else:
        conclusion, status = "no_time_validated_candidate", "complete"
        qualified_rules = []

    report.update(
        {
            "status": status,
            "conclusion": conclusion,
            "time_split": summary["time_split"],
            "selection_protocol": {
                **summary["selection_protocol"],
                "include_exit_evidence": include_exit_evidence,
            },
            "families": summary["families"],
            "score_factors": score_summary["families"],
            "case_score_membership": case_score_membership,
            "qualified_score_factors": qualified_score_factors,
            "full_history_score_gate": full_history_score_gate,
            "pre_attack_base_process": summary["pre_attack_base_process"],
            "research_answers": [],
            "qualified_rules": qualified_rules,
        }
    )
    report["research_answers"] = _research_answers(report)
    return report


def render_extended_daily_factor_json(report: Mapping[str, object]) -> str:
    """Render stable machine-readable extended discovery evidence."""

    return json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"


def render_extended_daily_factor_markdown(report: Mapping[str, object]) -> str:
    """Render all preregistered rules without promoting a raw-price finding."""

    lines = [
        "# 日线低吸扩展发现研究",
        "",
        f"- 研究版本：{report.get('research_version', '-')}",
        f"- 输入 SHA256：{report.get('input_sha256', '-')}",
        f"- 证据等级：{report.get('evidence_level', '-')}",
        f"- 结论：{report.get('conclusion', '-')}",
        "- 历史基线案例审计、诊断分数和基础卖点证据保留在综合研究报告；本报告只扩展未覆盖的具体时点假设。",
        "- 日内中心价固定为 (最高价 + 最低价) / 2 的日线范围中点，只用于比较低点、中心价与收盘三种支撑代理，不是分钟 VWAP。",
        "- 原始主板过滤：D+1 与退出路径中严格超过 [-10%, +10%] 的变化全部排除；±10% 保留，约 10.1% 的价格档位端点也按用户口径排除。",
        "- D+1 初始趋势形态仅是事后结果标签：MA10 > MA20 > MA30 且 MA10/MA20 向上；不要求 MA5 或 MA60，也不参与 D 日选股、评分或规则选择。",
    ]
    if report.get("conclusion") == "exploratory_only":
        lines.append("- 当前为不复权原始日线探索，任何发现不能升级为正式策略结论。")
    selection_protocol = report.get("selection_protocol")
    if isinstance(selection_protocol, Mapping):
        selection_mode = selection_protocol.get("mode")
        frozen_rule_keys = selection_protocol.get("frozen_rule_keys")
        if selection_protocol.get("include_exit_evidence") is False:
            lines.append(
                "- 本次仅做近半年入场因子发现，已跳过卖点枚举；只有出现可冻结候选后才单独研究卖点。"
            )
        if selection_mode == FROZEN_SELECTION_MODE and isinstance(
            frozen_rule_keys,
            Mapping,
        ):
            frozen_text = "，".join(
                f"{setup_type}={rule_key}"
                for setup_type, rule_key in sorted(frozen_rule_keys.items())
            )
            lines.append(
                "- 选择协议：半年开发期冻结规则（{rules}）；本窗口只复验，不按全窗口收益更换规则。".format(
                    rules=frozen_text,
                )
            )
        elif selection_mode == DEVELOPMENT_SELECTION_MODE:
            lines.append("- 选择协议：仅由本窗口 development 段选择，validation/holdout 不参与选择。")
    coverage = report.get("coverage")
    if isinstance(coverage, Mapping):
        if coverage.get("price_basis"):
            lines.append(f"- 价格口径：{coverage['price_basis']}")
        raw = coverage.get("raw_unadjusted_prices")
        if isinstance(raw, Mapping) and raw.get("warning"):
            lines.append(f"- 原始日线限制：{raw['warning']}")
    blockers = report.get("blockers")
    if blockers:
        lines.extend(["", "## 数据门禁", ""])
        lines.extend(f"- {value}" for value in blockers)

    split = report.get("time_split")
    if isinstance(split, Mapping):
        lines.extend(
            [
                "",
                "## 时间切分",
                "",
                "- development：{development_start} 至 {development_end}（{development_days} 日）".format(**split),
                "- embargo：{embargo_start} 至 {embargo_end}（{embargo_days} 日）".format(**split),
                "- validation：{validation_start} 至 {validation_end}（{validation_days} 日）".format(**split),
                "- holdout：{holdout_start} 至 {holdout_end}（{holdout_days} 日）".format(**split),
            ]
        )

    lines.extend(["", "## 预登记候选规则", ""])
    lines.append("| 类型 | 规则 | 描述 | 总样本 | 总 D+1 均值 | D+1 初始趋势率 | 验证 D+1 均值 | 留出 D+1 均值 | 严格排除 |")
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    families = report.get("families")
    if isinstance(families, Mapping):
        for setup_type in SETUP_TYPES:
            family = families.get(setup_type)
            if not isinstance(family, Mapping):
                continue
            for rule in family.get("rules", ()):
                if not isinstance(rule, Mapping):
                    continue
                overall = rule.get("overall") if isinstance(rule.get("overall"), Mapping) else {}
                segments = rule.get("segments") if isinstance(rule.get("segments"), Mapping) else {}
                validation = segments.get("validation") if isinstance(segments.get("validation"), Mapping) else {}
                holdout = segments.get("holdout") if isinstance(segments.get("holdout"), Mapping) else {}
                lines.append(
                    "| {setup} | {key} | {description} | {samples} | {overall_mean} | {trend_rate} | {validation_mean} | {holdout_mean} | {excluded} |".format(
                        setup=setup_type,
                        key=rule.get("key", "-"),
                        description=rule.get("description", "-"),
                        samples=overall.get("sample_count", 0),
                        overall_mean=_number_text(overall.get("d1_mean_return_pct")),
                        trend_rate=_number_text(
                            overall.get("d1_initial_short_trend_formed_rate_pct")
                        ),
                        validation_mean=_number_text(validation.get("d1_mean_return_pct")),
                        holdout_mean=_number_text(holdout.get("d1_mean_return_pct")),
                        excluded=overall.get("label_excluded_main_board_price_limit_count", 0),
                    )
                )

        for setup_type in SETUP_TYPES:
            family = families.get(setup_type)
            if not isinstance(family, Mapping):
                continue
            _render_selected_family(lines, setup_type, family)

    _render_pre_attack_base_process(
        lines,
        report.get("pre_attack_base_process"),
    )
    _render_score_factors(
        lines,
        report.get("score_factors"),
        report.get("case_score_membership"),
    )
    full_history_score_gate = report.get("full_history_score_gate")
    if isinstance(full_history_score_gate, Mapping):
        lines.extend(["", "## 全历史前置门禁", ""])
        lines.append(
            "- 两类分数因子近半年时间外验证：{status}。{policy}".format(
                status="通过" if full_history_score_gate.get("passed") else "未通过",
                policy=full_history_score_gate.get("policy", ""),
            )
        )
        reasons = full_history_score_gate.get("reasons")
        if isinstance(reasons, Sequence) and reasons:
            lines.append("- 未通过项：`{reasons}`".format(reasons=", ".join(map(str, reasons))))

    answers = report.get("research_answers")
    if isinstance(answers, Sequence):
        lines.extend(["", "## 研究问题结论", ""])
        lines.append("| 问题 | 状态 | 说明 |")
        lines.append("| --- | --- | --- |")
        for answer in answers:
            if isinstance(answer, Mapping):
                lines.append(
                    "| {question} | {status} | {detail} |".format(
                        question=answer.get("question", "-"),
                        status=answer.get("status", "-"),
                        detail=answer.get("detail", "-"),
                    )
                )
    return "\n".join(lines) + "\n"


def _render_pre_attack_base_process(
    lines: list[str],
    summary: object,
) -> None:
    if not isinstance(summary, Mapping):
        return
    groups = summary.get("phase_groups")
    if not isinstance(groups, Sequence) or not groups:
        return
    lines.extend(["", "## 攻击前底盘过程（观察性）", ""])
    lines.append(
        "- {cutoff}；仅统计攻击实体缩量守住候选，本观察表不参与规则选择、分数或实时推荐；首段两线攻击另有冻结资格门。".format(
            cutoff=summary.get("feature_cutoff", "特征截止 D-2"),
        )
    )
    lines.append(
        "- 候选 {candidates} 个，严格涨跌停标签排除 {excluded} 个。".format(
            candidates=summary.get("candidate_count", 0),
            excluded=summary.get("label_excluded_main_board_price_limit_count", 0),
        )
    )
    lines.append("| 底盘路径 | 样本 | D+1 均值 | 胜率 | 同日超额均值 | 同日样本 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for group in groups:
        if not isinstance(group, Mapping):
            continue
        same_day = group.get("same_day_excess")
        same_day = same_day if isinstance(same_day, Mapping) else {}
        lines.append(
            "| {phase} | {samples} | {mean} | {win_rate} | {excess} | {excess_samples} |".format(
                phase=group.get("phase", "-"),
                samples=group.get("sample_count", 0),
                mean=_number_text(group.get("d1_mean_return_pct")),
                win_rate=_number_text(group.get("win_rate_pct")),
                excess=_number_text(same_day.get("mean_return_pct")),
                excess_samples=same_day.get("sample_count", 0),
            )
        )


def _render_score_factors(
    lines: list[str],
    score_factors: object,
    case_score_membership: object,
) -> None:
    if not isinstance(score_factors, Mapping):
        return
    lines.extend(["", "## 综合分数因子", ""])
    lines.append(
        "| 类型 | 分数版本 | 分数段 | 总样本 | 总 D+1 均值 | 验证 D+1 均值 | 留出 D+1 均值 |"
    )
    lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
    for setup_type in SETUP_TYPES:
        family = score_factors.get(setup_type)
        if not isinstance(family, Mapping):
            continue
        variants = family.get("variants")
        if not isinstance(variants, Sequence):
            continue
        for variant in variants:
            if not isinstance(variant, Mapping):
                continue
            bands = variant.get("bands")
            if not isinstance(bands, Sequence):
                continue
            for band in bands:
                if not isinstance(band, Mapping):
                    continue
                overall = band.get("overall")
                segments = band.get("segments")
                validation = _segment_score_summary(segments, "validation")
                holdout = _segment_score_summary(segments, "holdout")
                lines.append(
                    "| {setup} | {variant} | {band} | {samples} | {overall_mean} | {validation_mean} | {holdout_mean} |".format(
                        setup=setup_type,
                        variant=variant.get("variant", "-"),
                        band=band.get("band", "-"),
                        samples=(
                            overall.get("sample_count", 0)
                            if isinstance(overall, Mapping)
                            else 0
                        ),
                        overall_mean=_number_text(
                            overall.get("d1_mean_return_pct")
                            if isinstance(overall, Mapping)
                            else None
                        ),
                        validation_mean=_number_text(
                            validation.get("d1_mean_return_pct")
                        ),
                        holdout_mean=_number_text(
                            holdout.get("d1_mean_return_pct")
                        ),
                    )
                )
        _render_selected_score_factor(lines, setup_type, family)

    if not isinstance(case_score_membership, Mapping):
        return
    lines.extend(["", "### 个人案例分数归属", ""])
    lines.append("| 案例 | D 日 | 家族 | 分数 | 分数段 | 是否在选中段 | 数据状态 |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for name, row in case_score_membership.items():
        if not isinstance(row, Mapping):
            continue
        scores = row.get("scores")
        score_bands = row.get("score_bands")
        selected = row.get("selected_score_factor")
        lines.append(
            "| {name} | {trade_date} | {setup} | {scores} | {bands} | {matched} | {status} |".format(
                name=name,
                trade_date=row.get("trade_date", "-"),
                setup=row.get("setup_type", "-"),
                scores=_markdown_cell(scores),
                bands=_markdown_cell(score_bands),
                matched=(
                    selected.get("matched", False)
                    if isinstance(selected, Mapping)
                    else "-"
                ),
                status=row.get("data_status", "-"),
            )
        )


def _render_selected_score_factor(
    lines: list[str],
    setup_type: str,
    family: Mapping[str, object],
) -> None:
    selected = family.get("selected_score_factor")
    if not isinstance(selected, Mapping):
        return
    variant = str(selected.get("variant") or "")
    band_name = str(selected.get("band") or "")
    lines.extend(["", f"### {setup_type} 开发期选中分数段", ""])
    if not variant or not band_name:
        lines.append("- 开发期没有达到最小样本/交易日门槛的分数段。")
        return
    gate = selected.get("qualification_gate")
    case_gate = selected.get("case_membership_gate")
    lines.append(
        "- 分数版本 `{variant}`，区间 `{band}`；验证 D+1 {validation}，留出 D+1 {holdout}；因子提取门禁：{gate}。".format(
            variant=variant,
            band=band_name,
            validation=_number_text(
                selected.get("validation", {}).get("d1_mean_return_pct")
                if isinstance(selected.get("validation"), Mapping)
                else None
            ),
            holdout=_number_text(
                selected.get("holdout", {}).get("d1_mean_return_pct")
                if isinstance(selected.get("holdout"), Mapping)
                else None
            ),
            gate="通过" if isinstance(gate, Mapping) and gate.get("passed") else "未通过",
        )
    )
    if isinstance(case_gate, Mapping):
        lines.append(
            "- 个人案例分数门禁：{status}；要求 `{required}`。".format(
                status="通过" if case_gate.get("passed") else "未通过",
                required=_markdown_cell(case_gate.get("required_bands")),
            )
        )
    selected_band = _find_score_band(family.get("variants"), variant, band_name)
    full = selected_band.get("full") if isinstance(selected_band, Mapping) else None
    if not isinstance(full, Mapping):
        return
    daily_outcomes = full.get("daily_outcomes")
    if isinstance(daily_outcomes, Sequence) and daily_outcomes:
        lines.extend(["", "#### 每个交易日", ""])
        lines.append("| 日期 | 候选数 | D+1 样本 | 胜率 | D+1 均值 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for row in daily_outcomes:
            if isinstance(row, Mapping):
                lines.append(
                    "| {trade_date} | {candidate_count} | {sample_count} | {win_rate} | {mean} |".format(
                        trade_date=row.get("trade_date", "-"),
                        candidate_count=row.get("candidate_count", 0),
                        sample_count=row.get("sample_count", 0),
                        win_rate=_number_text(row.get("win_rate_pct")),
                        mean=_number_text(row.get("d1_mean_return_pct")),
                    )
                )
    _render_worst_score_rows(lines, full.get("worst_days"), "最差交易日", "trade_date")
    _render_worst_score_rows(lines, full.get("worst_stocks"), "最差股票", "vt_symbol")


def _render_worst_score_rows(
    lines: list[str],
    rows: object,
    heading: str,
    key: str,
) -> None:
    if not isinstance(rows, Sequence) or not rows:
        return
    lines.extend(["", f"#### {heading}", ""])
    lines.append("| 项目 | 样本 | 胜率 | D+1 均值 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for row in rows[:MAX_MARKDOWN_WORST_ROWS]:
        if isinstance(row, Mapping):
            lines.append(
                "| {name} | {samples} | {win_rate} | {mean} |".format(
                    name=row.get(key, "-"),
                    samples=row.get("sample_count", 0),
                    win_rate=_number_text(row.get("win_rate_pct")),
                    mean=_number_text(row.get("d1_mean_return_pct")),
                )
            )


def _segment_score_summary(segments: object, segment: str) -> Mapping[str, object]:
    if not isinstance(segments, Mapping):
        return {}
    value = segments.get(segment)
    if not isinstance(value, Mapping):
        return {}
    overall = value.get("overall")
    return overall if isinstance(overall, Mapping) else {}


def _find_score_band(
    variants: object,
    selected_variant: str,
    selected_band: str,
) -> Mapping[str, object] | None:
    if not isinstance(variants, Sequence):
        return None
    for variant in variants:
        if not isinstance(variant, Mapping) or variant.get("variant") != selected_variant:
            continue
        bands = variant.get("bands")
        if not isinstance(bands, Sequence):
            continue
        return next(
            (
                band
                for band in bands
                if isinstance(band, Mapping) and band.get("band") == selected_band
            ),
            None,
        )
    return None


def _render_selected_family(
    lines: list[str],
    setup_type: str,
    family: Mapping[str, object],
) -> None:
    selected = family.get("selected_rule")
    if not isinstance(selected, Mapping):
        return
    selection_mode = selected.get("selection_mode")
    heading = (
        f"## {setup_type} 冻结规则全窗口复验"
        if selection_mode == FROZEN_SELECTION_MODE
        else f"## {setup_type} 开发期选择与时间外验证"
    )
    lines.extend(["", heading, ""])
    if not selected.get("key"):
        lines.append("- 开发期没有达到最小样本/交易日门槛的候选规则。")
        return
    gate = selected.get("qualification_gate")
    validation = selected.get("validation") if isinstance(selected.get("validation"), Mapping) else {}
    holdout = selected.get("holdout") if isinstance(selected.get("holdout"), Mapping) else {}
    lines.append(
        "- {selection}：{key}；验证 D+1 {validation}，留出 D+1 {holdout}；因子提取门禁：{gate}。".format(
            selection=(
                "半年开发期冻结"
                if selection_mode == FROZEN_SELECTION_MODE
                else "开发期选定"
            ),
            key=selected.get("key"),
            validation=_number_text(validation.get("d1_mean_return_pct")),
            holdout=_number_text(holdout.get("d1_mean_return_pct")),
            gate="通过" if isinstance(gate, Mapping) and gate.get("passed") else "未通过",
        )
    )
    exit_selection = selected.get("exit_selection")
    if isinstance(exit_selection, Mapping):
        exit_gate = exit_selection.get("qualification_gate")
        lines.extend(["", "### 收盘卖点", ""])
        lines.append(
            "- 开发期选定卖点：{probe}；验证 {validation}，留出 {holdout}；时间外门禁：{gate}。".format(
                probe=exit_selection.get("selected_probe") or "-",
                validation=_number_text(
                    exit_selection.get("validation", {}).get("mean_return_pct")
                    if isinstance(exit_selection.get("validation"), Mapping)
                    else None
                ),
                holdout=_number_text(
                    exit_selection.get("holdout", {}).get("mean_return_pct")
                    if isinstance(exit_selection.get("holdout"), Mapping)
                    else None
                ),
                gate=(
                    "通过"
                    if isinstance(exit_gate, Mapping) and exit_gate.get("passed")
                    else "未通过"
                ),
            )
        )
    post_limit_up = selected.get("post_limit_up_exit_selection")
    if isinstance(post_limit_up, Mapping):
        post_limit_up_gate = post_limit_up.get("qualification_gate")
        lines.append(
            "- 首次严格涨停收盘后持有（不含首次涨停本身）：{probe}；验证 {validation}，留出 {holdout}；时间外门禁：{gate}。".format(
                probe=post_limit_up.get("selected_probe") or "-",
                validation=_number_text(
                    post_limit_up.get("validation", {}).get("mean_return_pct")
                    if isinstance(post_limit_up.get("validation"), Mapping)
                    else None
                ),
                holdout=_number_text(
                    post_limit_up.get("holdout", {}).get("mean_return_pct")
                    if isinstance(post_limit_up.get("holdout"), Mapping)
                    else None
                ),
                gate=(
                    "通过"
                    if isinstance(post_limit_up_gate, Mapping)
                    and post_limit_up_gate.get("passed")
                    else "未通过"
                ),
            )
        )

    rule = next(
        (
            row
            for row in family.get("rules", ())
            if isinstance(row, Mapping) and row.get("key") == selected.get("key")
        ),
        None,
    )
    if not isinstance(rule, Mapping):
        return
    full = rule.get("full")
    if not isinstance(full, Mapping):
        return
    worst_days = full.get("worst_days")
    if isinstance(worst_days, Sequence) and worst_days:
        lines.extend(["", "### 最差交易日（已排除严格边界外样本）", ""])
        lines.append("| 日期 | 样本 | D+1 均值 | 胜率 |")
        lines.append("| --- | ---: | ---: | ---: |")
        for row in worst_days[:MAX_MARKDOWN_WORST_ROWS]:
            if isinstance(row, Mapping):
                lines.append(
                    "| {date} | {samples} | {mean} | {win} |".format(
                        date=row.get("trade_date", "-"),
                        samples=row.get("sample_count", 0),
                        mean=_number_text(row.get("d1_mean_return_pct")),
                        win=_number_text(row.get("win_rate_pct")),
                    )
                )
    worst_stocks = full.get("worst_stocks")
    if isinstance(worst_stocks, Sequence) and worst_stocks:
        lines.extend(["", "### 最差股票（已排除严格边界外样本）", ""])
        lines.append("| 股票 | 样本 | D+1 均值 | 胜率 |")
        lines.append("| --- | ---: | ---: | ---: |")
        for row in worst_stocks[:MAX_MARKDOWN_WORST_ROWS]:
            if isinstance(row, Mapping):
                lines.append(
                    "| {symbol} | {samples} | {mean} | {win} |".format(
                        symbol=row.get("vt_symbol", "-"),
                        samples=row.get("sample_count", 0),
                        mean=_number_text(row.get("d1_mean_return_pct")),
                        win=_number_text(row.get("win_rate_pct")),
                    )
                )


def _iter_rule_observations(
    bars: Any,
    calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
) -> Iterable[dict[str, object]]:
    for snapshot in _iter_candidate_snapshots(
        bars,
        calendar,
        security_status,
        include_d1_initial_short_trend_outcome=True,
        include_pre_attack_base_features=True,
    ):
        for setup_type, rules in DISCOVERY_RULES.items():
            for rule in rules:
                if _rule_matches(
                    rule,
                    snapshot.features,
                    prior_features=snapshot.prior_features,
                ):
                    yield {
                        "setup_type": setup_type,
                        "rule_key": rule.key,
                        "vt_symbol": snapshot.symbol,
                        "trade_date": snapshot.trade_date,
                        "d1_close_return_pct": snapshot.d1_close_return_pct,
                        "d1_label_status": snapshot.d1_label_status,
                        "d1_initial_short_trend_formed": (
                            snapshot.d1_initial_short_trend_formed
                            if rule.key in TRANSITION_RULE_KEYS
                            else None
                        ),
                        "transition_volume_expand_then_shrink": (
                            bool(snapshot.features.get("volume_expand_then_shrink"))
                            if rule.key == OVERSOLD_TO_TREND_RULE_KEY
                            else None
                        ),
                        "pre_attack_base_phase": snapshot.features.get(
                            "pre_attack_base_phase"
                        ),
                        "feature_snapshot": _feature_snapshot(snapshot.features),
                    }


def _iter_score_observations(
    bars: Any,
    calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
) -> Iterable[dict[str, object]]:
    """Yield one D-and-earlier score observation per applicable family variant."""

    for snapshot in _iter_candidate_snapshots(
        bars,
        calendar,
        security_status,
        require_rule_match=False,
    ):
        for setup_type in SETUP_TYPES:
            if not _is_score_candidate(snapshot.features, setup_type):
                continue
            for variant, score in score_extended_factor(
                snapshot.features,
                setup_type,
                prior_features=snapshot.prior_features,
            ).items():
                yield {
                    "setup_type": setup_type,
                    "score_variant": variant,
                    "score": score,
                    "vt_symbol": snapshot.symbol,
                    "trade_date": snapshot.trade_date,
                    "d1_close_return_pct": snapshot.d1_close_return_pct,
                    "d1_label_status": snapshot.d1_label_status,
                    "d1_initial_short_trend_formed": (
                        snapshot.d1_initial_short_trend_formed
                    ),
                    "feature_snapshot": _feature_snapshot(snapshot.features),
                }


def _is_score_candidate(
    features: Mapping[str, object],
    setup_type: str,
) -> bool:
    """Keep scoring on the broad family geometry, not only one exact rule."""

    if setup_type == "oversold_rebound":
        return bool(
            features.get("oversold_process_eligible")
            and any(
                bool(features.get(field))
                for field in (
                    "staged_m10_first",
                    "ma10_crossed_ma30_within_15d",
                )
            )
            and any(
                bool(features.get(field))
                for field in (
                    "ma10_ma30_gap_converging",
                    "ma20_ma30_contact",
                    "ma10_ma30_contact",
                    "ma10_low_touch",
                    "post_cross_pullback",
                    "aggressive_pullback",
                )
            )
        )
    if setup_type == "trend_pullback":
        ordinary_trend_candidate = bool(
            features.get("trend_discovery_eligible")
            and any(
                bool(features.get(field))
                for field in (
                    "ma5_low_touch",
                    "ma5_low_touch_broad",
                    "ma10_low_touch",
                )
            )
        )
        return bool(
            ordinary_trend_candidate
            or features.get("trend_transition_eligible")
        )
    raise DailyFactorInputError(f"unsupported extended score setup type: {setup_type}")


def _collect_case_score_profiles(
    bars: Any,
    calendar: Sequence[date],
) -> dict[str, dict[str, object]]:
    """Calculate source-case scores without letting returns select their range."""

    cases_by_symbol: dict[str, list[object]] = defaultdict(list)
    result: dict[str, dict[str, object]] = {}
    for case in PERSONAL_CASES:
        cases_by_symbol[case.vt_symbol].append(case)
        result[case.name] = {
            "vt_symbol": case.vt_symbol,
            "trade_date": case.trade_date.isoformat(),
            "setup_type": case.expected_setup_type,
            "data_status": "outside_input_range",
            "scores": {},
            "score_bands": {},
        }
    calendar_tuple = _strict_calendar(calendar)
    calendar_set = set(calendar_tuple)
    calendar_positions = {value: index for index, value in enumerate(calendar_tuple)}
    for symbol, history in _iter_symbol_histories(bars):
        cases = cases_by_symbol.get(symbol)
        if not cases:
            continue
        position_by_date = {
            _required_date(row.get("trade_date")): position
            for position, row in enumerate(history)
        }
        for case in cases:
            position = position_by_date.get(case.trade_date)
            if position is None or case.trade_date not in calendar_set:
                continue
            features = build_extended_daily_features(
                history[max(0, position - 79) : position + 1]
            )
            calendar_position = calendar_positions.get(case.trade_date)
            prior_is_previous_market_session = bool(
                position > 0
                and calendar_position is not None
                and calendar_position > 0
                and _required_date(history[position - 1].get("trade_date"))
                == calendar_tuple[calendar_position - 1]
            )
            prior_features = (
                build_extended_daily_features(
                    history[max(0, position - 80) : position]
                )
                if prior_is_previous_market_session
                else None
            )
            scores = score_extended_factor(
                features,
                case.expected_setup_type,
                prior_features=prior_features,
            )
            score_bands = {
                variant: _score_band(score)
                for variant, score in scores.items()
            }
            result[case.name] = {
                "vt_symbol": case.vt_symbol,
                "trade_date": case.trade_date.isoformat(),
                "setup_type": case.expected_setup_type,
                "data_status": "available",
                "scores": scores,
                "score_bands": score_bands,
            }
    return result


def _source_case_bands(
    case_profiles: Mapping[str, Mapping[str, object]],
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Return the score bands occupied by complete named cases in this window."""

    bands: dict[str, dict[str, set[str]]] = {
        setup_type: defaultdict(set) for setup_type in SETUP_TYPES
    }
    for profile in case_profiles.values():
        if profile.get("data_status") != "available":
            continue
        setup_type = str(profile.get("setup_type") or "")
        if setup_type not in bands:
            continue
        score_bands = profile.get("score_bands")
        if not isinstance(score_bands, Mapping):
            continue
        for variant, band in score_bands.items():
            if band is not None:
                bands[setup_type][str(variant)].add(str(band))
    return {
        setup_type: {
            variant: tuple(sorted(values))
            for variant, values in by_variant.items()
        }
        for setup_type, by_variant in bands.items()
    }


def _attach_case_score_selection(
    case_profiles: Mapping[str, Mapping[str, object]],
    score_factors: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Attach the development-selected score band to immutable case profiles."""

    result: dict[str, dict[str, object]] = {}
    for name, profile in case_profiles.items():
        setup_type = str(profile.get("setup_type") or "")
        family = score_factors.get(setup_type)
        selected = (
            family.get("selected_score_factor")
            if isinstance(family, Mapping)
            else None
        )
        selected_variant = (
            str(selected.get("variant") or "")
            if isinstance(selected, Mapping)
            else ""
        )
        selected_band = (
            str(selected.get("band") or "")
            if isinstance(selected, Mapping)
            else ""
        )
        score_bands = profile.get("score_bands")
        result[name] = {
            **profile,
            "selected_score_factor": {
                "variant": selected_variant or None,
                "band": selected_band or None,
                "matched": bool(
                    selected_variant
                    and selected_band
                    and isinstance(score_bands, Mapping)
                    and score_bands.get(selected_variant) == selected_band
                ),
            },
        }
    return result


def _collect_selected_exit_evidence(
    bars: Any,
    calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
    selected_rules: Mapping[str, str],
) -> dict[str, dict[str, object]]:
    rows_by_setup: dict[str, list[dict[str, object]]] = {
        setup_type: [] for setup_type in SETUP_TYPES
    }
    post_limit_up_rows_by_setup: dict[str, list[dict[str, object]]] = {
        setup_type: [] for setup_type in SETUP_TYPES
    }
    lookup = {
        setup_type: {rule.key: rule for rule in rules}
        for setup_type, rules in DISCOVERY_RULES.items()
    }
    for snapshot in _iter_candidate_snapshots(bars, calendar, security_status):
        for setup_type, rule_key in selected_rules.items():
            rule = lookup.get(setup_type, {}).get(rule_key)
            if rule is None or not _rule_matches(
                rule,
                snapshot.features,
                prior_features=snapshot.prior_features,
            ):
                continue
            if snapshot.d1_label_status == "label_excluded_main_board_price_limit":
                continue
            entry_price = _required_positive_number(
                snapshot.features.get("close_price"),
                "close_price",
            )
            future_bars = _future_exit_bars(
                snapshot.history,
                snapshot.dates,
                calendar,
                snapshot.trade_date,
            )
            candidate = {
                "entry_date": snapshot.trade_date,
                "entry_price": entry_price,
                "setup_type": setup_type,
            }
            for probe in EXIT_PROBES[setup_type]:
                outcome = evaluate_close_exit_probe(candidate, future_bars, probe=probe)
                rows_by_setup[setup_type].append(
                    {
                        **outcome,
                        "trade_date": snapshot.trade_date,
                    }
                )
            for holding_sessions in POST_LIMIT_UP_HOLDING_SESSIONS:
                outcome = evaluate_post_limit_up_hold(
                    candidate,
                    future_bars,
                    holding_sessions=holding_sessions,
                )
                post_limit_up_rows_by_setup[setup_type].append(
                    {
                        **outcome,
                        "trade_date": snapshot.trade_date,
                    }
                )
    return {
        setup_type: {
            "standard": select_exit_probe(rows, market_calendar=calendar),
            "post_limit_up": select_exit_probe(
                post_limit_up_rows_by_setup[setup_type],
                market_calendar=calendar,
                require_triggered_coverage=True,
            ),
        }
        for setup_type, rows in rows_by_setup.items()
        if selected_rules.get(setup_type)
    }


def _iter_candidate_snapshots(
    bars: Any,
    calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
    *,
    require_rule_match: bool = True,
    include_d1_initial_short_trend_outcome: bool = False,
    include_pre_attack_base_features: bool = False,
    target_dates: set[date] | None = None,
) -> Iterable[_CandidateSnapshot]:
    """Build snapshots for requested market days without a generic entry gate."""

    calendar_tuple = _strict_calendar(calendar)
    calendar_set = set(calendar_tuple)
    scan_dates = calendar_set if target_dates is None else calendar_set & target_dates
    calendar_positions = {value: index for index, value in enumerate(calendar_tuple)}
    eligible_pairs = _eligible_security_pairs(security_status, calendar_tuple)
    for symbol, history in _iter_symbol_histories(bars):
        dates = tuple(_required_date(row.get("trade_date")) for row in history)
        position_by_date = {
            trade_date: position for position, trade_date in enumerate(dates)
        }
        closes = {
            trade_date: _number_or_none(history[index].get("close_price"))
            for index, trade_date in enumerate(dates)
        }
        feature_cache: dict[int, Mapping[str, object]] = {}

        def _features_at(position: int) -> Mapping[str, object]:
            if position not in feature_cache:
                history_window = history[max(0, position - 79) : position + 1]
                feature_cache[position] = (
                    build_extended_daily_features(
                        history_window,
                        include_pre_attack_base_features=True,
                    )
                    if include_pre_attack_base_features
                    else build_extended_daily_features(history_window)
                )
            return feature_cache[position]

        for position, trade_date in enumerate(dates):
            if trade_date not in scan_dates:
                continue
            if eligible_pairs and (symbol, trade_date) not in eligible_pairs:
                continue
            features = _features_at(position)
            prior_features = _prior_session_features(
                position=position,
                trade_date=trade_date,
                dates=dates,
                calendar=calendar_tuple,
                calendar_positions=calendar_positions,
                feature_at_position=_features_at,
            )
            if require_rule_match and not _matches_any_rule(
                features,
                prior_features=prior_features,
            ):
                continue
            d1_close_return_pct, d1_label_status = _causal_d1_label(
                closes,
                calendar_tuple,
                calendar_positions,
                symbol,
                trade_date,
                eligible_pairs,
            )
            calendar_position = calendar_positions.get(trade_date)
            d1_trade_date = (
                calendar_tuple[calendar_position + 1]
                if calendar_position is not None
                and calendar_position + 1 < len(calendar_tuple)
                else None
            )
            d1_initial_short_trend_formed = (
                _d1_initial_short_trend_shape(
                    history,
                    position=position_by_date.get(d1_trade_date)
                    if d1_label_status == "available"
                    else None,
                )
                if (
                    include_d1_initial_short_trend_outcome
                    and bool(
                        features.get("trend_transition_preparation_eligible")
                        or features.get("trend_transition_eligible")
                    )
                )
                else None
            )
            yield _CandidateSnapshot(
                symbol=symbol,
                trade_date=trade_date,
                position=position,
                history=history,
                dates=dates,
                features=features,
                prior_features=prior_features,
                d1_close_return_pct=d1_close_return_pct,
                d1_label_status=d1_label_status,
                d1_initial_short_trend_formed=d1_initial_short_trend_formed,
            )


def _prior_session_features(
    *,
    position: int,
    trade_date: date,
    dates: Sequence[date],
    calendar: Sequence[date],
    calendar_positions: Mapping[date, int],
    feature_at_position: Callable[[int], Mapping[str, object]],
) -> Mapping[str, object] | None:
    """Return the prior market-session snapshot, never a stale suspended bar."""

    calendar_position = calendar_positions.get(trade_date)
    if position < 1 or calendar_position is None or calendar_position < 1:
        return None
    if dates[position - 1] != calendar[calendar_position - 1]:
        return None
    return feature_at_position(position - 1)


def _is_pre_cross_trend_transition_preparation(
    *,
    prior_bear_alignment_days: int,
    ma10: float | None,
    ma20: float | None,
    close_price: float | None,
    daily_return_pct: float | None,
    prior_ma10: float | None,
    prior_ma20: float | None,
    prior_close_price: float | None,
) -> bool:
    """Recognize the D-day MA10/20 transition preparation without future data."""

    current_distance = _signed_ma_distance_pct(ma10, ma20, close_price)
    prior_distance = _signed_ma_distance_pct(
        prior_ma10,
        prior_ma20,
        prior_close_price,
    )
    return bool(
        prior_bear_alignment_days >= LONG_BEAR_ALIGNMENT_MIN_SESSIONS
        and ma10 is not None
        and ma20 is not None
        and ma10 < ma20
        and _ma_contact(current_distance)
        and current_distance is not None
        and prior_distance is not None
        and current_distance > prior_distance
        and daily_return_pct is not None
        and daily_return_pct > 0
    )


def _prior_stable_three_ma_wrap(
    prior_features: Mapping[str, object] | None,
) -> bool:
    """Check the complete source wrap contract on the immediately prior session."""

    if prior_features is None:
        return False
    return all(
        bool(prior_features.get(field))
        for field in (
            "long_bear_alignment",
            "ma10_crossed_ma20_after_long_bear_within_15d",
            "yang_wrap_three_ma",
            "yang_wrap_stable_base",
        )
    )


def _prior_three_ma_bundle_top(
    prior_features: Mapping[str, object] | None,
) -> float | None:
    if prior_features is None:
        return None
    values = tuple(
        _number_or_none(prior_features.get(field))
        for field in ("ma10", "ma20", "ma30")
    )
    if any(value is None for value in values):
        return None
    return max(float(value) for value in values if value is not None)


def _post_wrap_upper_band_touched(
    features: Mapping[str, object],
    prior_features: Mapping[str, object] | None,
) -> bool:
    """Require the D-day low to retest the prior stable bundle's upper edge."""

    bundle_top = _prior_three_ma_bundle_top(prior_features)
    distance = _price_to_ma_distance_pct(
        _number_or_none(features.get("low_price")),
        bundle_top,
    )
    return bool(
        distance is not None
        and abs(distance) <= POST_WRAP_UPPER_BAND_DISTANCE_MAX_PCT
    )


def _close_above_current_three_ma(features: Mapping[str, object]) -> bool:
    close_price = _number_or_none(features.get("close_price"))
    moving_averages = tuple(
        _number_or_none(features.get(field)) for field in ("ma10", "ma20", "ma30")
    )
    return bool(
        close_price is not None
        and all(value is not None for value in moving_averages)
        and close_price > max(float(value) for value in moving_averages if value is not None)
    )


def _post_wrap_turnover_controlled(features: Mapping[str, object]) -> bool:
    turnover = _number_or_none(features.get("turnover_rate_pct"))
    return bool(
        turnover is not None
        and POST_WRAP_CONFIRMATION_TURNOVER_MIN_PCT <= turnover
        < POST_WRAP_CONFIRMATION_TURNOVER_MAX_PCT
    )


def process_rule_predicates(
    rule_key: str,
    features: Mapping[str, object],
    *,
    prior_features: Mapping[str, object] | None = None,
) -> dict[str, bool]:
    """Return every source-contract predicate for an explicit case rule.

    A case report can therefore show exactly why a claimed source pattern did
    or did not match at the decision cutoff.
    """

    predicates: dict[str, dict[str, bool]] = {
        RESEARCH_THREE_MA_WRAP_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "ma10_crossed_ma20_after_long_bear_within_15d": bool(
                features.get("ma10_crossed_ma20_after_long_bear_within_15d")
            ),
            "yang_wrap_three_ma": bool(features.get("yang_wrap_three_ma")),
            "yang_wrap_stable_base": bool(features.get("yang_wrap_stable_base")),
        },
        POST_WRAP_UPPER_BAND_CONFIRMATION_RULE_KEY: {
            "prior_stable_three_ma_wrap": _prior_stable_three_ma_wrap(
                prior_features
            ),
            "prior_bundle_upper_edge_touch": _post_wrap_upper_band_touched(
                features,
                prior_features,
            ),
            "close_above_current_three_ma": _close_above_current_three_ma(features),
            "small_positive_candle": bool(features.get("small_positive_candle")),
            "candle_quiet": bool(features.get("candle_quiet")),
            "turnover_1_5_to_8_pct": _post_wrap_turnover_controlled(features),
        },
        STAGED_MA10_SUPPORT_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "oversold_process_eligible": bool(
                features.get("oversold_process_eligible")
            ),
            "ma10_crossed_ma20_after_long_bear_within_15d": bool(
                features.get("ma10_crossed_ma20_after_long_bear_within_15d")
            ),
            "ma10_above_ma20": bool(features.get("ma10_above_ma20")),
            "ma10_below_ma30": bool(features.get("ma10_below_ma30")),
            "ma10_low_touch": bool(features.get("ma10_low_touch")),
            "ma10_close_near": bool(features.get("ma10_close_near")),
            "ma10_ma30_fast_convergence": bool(
                features.get("ma10_ma30_fast_convergence")
            ),
            "volume_shape_staircase_shrink": (
                features.get("volume_shape") == "staircase_shrink"
            ),
            "volume_monotone_6d_at_least_0_8": bool(
                (vol_monotone := _number_or_none(features.get("vol_monotone_6d")))
                is not None
                and vol_monotone >= VOLUME_MONOTONE_6D_MIN_RATIO
            ),
        },
        ATTACK_BODY_HOLD_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "oversold_process_eligible": bool(
                features.get("oversold_process_eligible")
            ),
            "ma10_crossed_ma20_after_long_bear_within_15d": bool(
                features.get("ma10_crossed_ma20_after_long_bear_within_15d")
            ),
            "ma10_above_ma20": bool(features.get("ma10_above_ma20")),
            "ma10_below_ma30": bool(features.get("ma10_below_ma30")),
            "ma10_ma30_fast_convergence": bool(
                features.get("ma10_ma30_fast_convergence")
            ),
            "prior_attack_body_at_least_3_pct": (
                (prior_body := _number_or_none(features.get("prior_positive_body_pct")))
                is not None
                and prior_body >= ATTACK_BODY_MIN_PCT
            ),
            "prior_attack_not_limit_up": not bool(
                features.get("prior_limit_up_touched")
            ),
            "controlled_retest_candle": (
                (current_return := _number_or_none(features.get("daily_return_pct")))
                is not None
                and ATTACK_BODY_HOLD_DAILY_RETURN_MIN_PCT
                <= current_return
                <= ATTACK_BODY_HOLD_DAILY_RETURN_MAX_PCT
                and bool(features.get("candle_quiet"))
            ),
            "attack_body_low_held": bool(features.get("attack_body_low_held")),
            "attack_body_close_held": bool(features.get("attack_body_close_held")),
            "volume_shrunk_to_80_pct_or_less": (
                (volume_ratio := _number_or_none(
                    features.get("last_volume_to_prior_ratio")
                ))
                is not None
                and volume_ratio <= ATTACK_BODY_HOLD_VOLUME_MAX_RATIO
            ),
        },
        MA10_MA20_PRE_CROSS_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "current_full_bear_alignment": bool(
                features.get("current_full_bear_alignment")
            ),
            "ma10_below_ma20": bool(features.get("ma10_below_ma20")),
            "ma10_ma20_contact": bool(features.get("ma10_ma20_contact")),
            "ma10_ma20_gap_narrowing": bool(
                features.get("ma10_ma20_gap_narrowing")
            ),
            "positive_candle": bool(features.get("positive_candle")),
            "last_volume_expanded": bool(features.get("last_volume_expanded")),
        },
        FIRST_LEG_TWO_MA_WRAP_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "current_full_bear_alignment": bool(
                features.get("current_full_bear_alignment")
            ),
            "yang_wrap_two_ma": bool(features.get("yang_wrap_two_ma")),
            "close_below_ma30": bool(features.get("close_below_ma30")),
            "signal_day_not_limit_up_closed": bool(
                features.get("signal_day_not_limit_up_closed")
            ),
        },
        OVERSOLD_TO_TREND_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "ma10_dual_cross_within_7d": bool(
                features.get("ma10_dual_cross_within_7d")
            ),
            "ma10_above_ma20_and_ma30": bool(
                features.get("ma10_above_ma20_and_ma30")
            ),
            "ma20_ma30_tight_contact": bool(
                features.get("transition_ma20_ma30_tight_contact")
            ),
            "ma10_ma20_slopes_up": bool(features.get("ma10_ma20_slopes_up")),
            "post_cross_pullback": bool(features.get("post_cross_pullback")),
            "small_positive_candle": bool(
                features.get("small_positive_candle")
            ),
        },
        "ma10_ma30_retest_after_actual_cross_two_leg_volume": {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "oversold_process_eligible": bool(
                features.get("oversold_process_eligible")
            ),
            "ma10_crossed_ma20_within_15d": bool(
                features.get("ma10_crossed_ma20_within_15d")
            ),
            "ma10_was_above_ma30_within_15d": bool(
                features.get("ma10_was_above_ma30_within_15d")
            ),
            "ma10_ma30_contact": bool(features.get("ma10_ma30_contact")),
            "aggressive_pullback": bool(features.get("aggressive_pullback")),
            "volume_shrink_then_expand": bool(
                features.get("volume_shrink_then_expand")
            ),
        },
        "ma10_low_touch_after_ma5_extension": {
            "trend_discovery_eligible": bool(
                features.get("trend_discovery_eligible")
            ),
            "trend_stable_bull": bool(features.get("trend_stable_bull")),
            "ma5_regular": bool(features.get("ma5_regular")),
            "ma10_low_touch": bool(features.get("ma10_low_touch")),
            "prior_ma5_close_extension": bool(
                features.get("prior_ma5_close_extension")
            ),
            "prior_daily_price_not_up": bool(
                features.get("prior_daily_price_not_up")
            ),
        },
        "ma5_low_touch_stable_trend": {
            "trend_discovery_eligible": bool(
                features.get("trend_discovery_eligible")
            ),
            "trend_stable_bull": bool(features.get("trend_stable_bull")),
            "ma5_regular": bool(features.get("ma5_regular")),
            "ma5_low_touch": bool(features.get("ma5_low_touch")),
        },
        "ma5_low_touch_stable_trend_volume_shrink": {
            "trend_discovery_eligible": bool(
                features.get("trend_discovery_eligible")
            ),
            "trend_stable_bull": bool(features.get("trend_stable_bull")),
            "ma5_regular": bool(features.get("ma5_regular")),
            "ma5_low_touch": bool(features.get("ma5_low_touch")),
            "last_volume_shrank": bool(features.get("last_volume_shrank")),
        },
        "ma5_low_touch_after_disordered_trend_rebuild": {
            "trend_discovery_eligible": bool(
                features.get("trend_discovery_eligible")
            ),
            "trend_rebuilt_from_disorder": bool(
                features.get("trend_rebuilt_from_disorder")
            ),
            "ma5_regular": bool(features.get("ma5_regular")),
            "ma5_low_touch_broad": bool(features.get("ma5_low_touch_broad")),
        },
        "ma5_low_touch_early_trend": {
            "early_trend_alignment": bool(features.get("early_trend_alignment")),
            "trend_all_slopes_up": bool(features.get("trend_all_slopes_up")),
            "ma5_regular": bool(features.get("ma5_regular")),
            "ma5_low_touch": bool(features.get("ma5_low_touch")),
        },
        "ma5_low_touch_early_trend_prior_touch": {
            "early_trend_alignment": bool(features.get("early_trend_alignment")),
            "trend_all_slopes_up": bool(features.get("trend_all_slopes_up")),
            "ma5_regular": bool(features.get("ma5_regular")),
            "ma5_low_touch": bool(features.get("ma5_low_touch")),
            "prior_ma5_low_touch": bool(features.get("prior_ma5_low_touch")),
        },
    }
    try:
        return predicates[rule_key]
    except KeyError as exc:
        raise DailyFactorInputError(
            f"unsupported explicit case process rule: {rule_key}"
        ) from exc


def _matches_explicit_process_geometry(
    features: Mapping[str, object],
    setup_type: str,
    *,
    prior_features: Mapping[str, object] | None = None,
) -> bool:
    """Match the non-volume geometry of at least one declared source process."""

    return any(
        all(
            passed
            for name, passed in process_rule_predicates(
                rule.key,
                features,
                prior_features=prior_features,
            ).items()
            if not name.startswith(("volume_", "last_volume_"))
        )
        for rule in DISCOVERY_RULES[setup_type]
        if rule.key in EXPLICIT_CASE_PROCESS_RULE_KEYS
    )


def _matches_explicit_process_with_volume(
    features: Mapping[str, object],
    setup_type: str,
    *,
    prior_features: Mapping[str, object] | None = None,
) -> bool:
    """Match every predicate, including volume, of one source process."""

    return any(
        all(
            process_rule_predicates(
                rule.key,
                features,
                prior_features=prior_features,
            ).values()
        )
        for rule in DISCOVERY_RULES[setup_type]
        if rule.key in EXPLICIT_CASE_PROCESS_RULE_KEYS
    )


def _rule_matches(
    rule: DiscoveryRule,
    features: Mapping[str, object],
    *,
    prior_features: Mapping[str, object] | None = None,
) -> bool:
    return bool(
        rule.key in EXPLICIT_CASE_PROCESS_RULE_KEYS
        and all(
            process_rule_predicates(
                rule.key,
                features,
                prior_features=prior_features,
            ).values()
        )
    )


def _matches_any_rule(
    features: Mapping[str, object],
    *,
    prior_features: Mapping[str, object] | None = None,
) -> bool:
    return any(
        _rule_matches(rule, features, prior_features=prior_features)
        for rules in DISCOVERY_RULES.values()
        for rule in rules
    )


def _normalize_frozen_rule_keys(
    frozen_rule_keys: Mapping[str, str] | None,
    manifest: Mapping[str, Sequence[DiscoveryRule]],
) -> dict[str, str]:
    """Validate a complete externally selected rule set before full-window replay."""

    if frozen_rule_keys is None:
        return {}
    normalized = {
        str(setup_type): str(rule_key).strip()
        for setup_type, rule_key in frozen_rule_keys.items()
    }
    if not normalized:
        return {}
    expected_types = set(manifest)
    if set(normalized) != expected_types:
        missing = sorted(expected_types - set(normalized))
        unknown = sorted(set(normalized) - expected_types)
        details = []
        if missing:
            details.append(f"missing setup types: {', '.join(missing)}")
        if unknown:
            details.append(f"unknown setup types: {', '.join(unknown)}")
        raise DailyFactorInputError(
            "frozen rule selection must declare every setup type; "
            + "; ".join(details)
        )
    for setup_type, rule_key in normalized.items():
        if not rule_key:
            raise DailyFactorInputError(
                f"frozen rule for {setup_type} must not be empty"
            )
        available_keys = {rule.key for rule in manifest[setup_type]}
        if rule_key not in available_keys:
            raise DailyFactorInputError(
                f"frozen rule {rule_key!r} does not belong to {setup_type}"
            )
    return normalized


def _select_rule(rules: Sequence[Mapping[str, object]]) -> dict[str, object]:
    eligible = []
    for rule in rules:
        segments = rule.get("segments")
        if not isinstance(segments, Mapping):
            continue
        development_segment = segments.get("development")
        development = (
            development_segment.get("overall")
            if isinstance(development_segment, Mapping)
            else None
        )
        if not isinstance(development, Mapping):
            continue
        if (
            int(development.get("sample_count") or 0) >= MIN_SELECTION_SAMPLES
            and int(development.get("candidate_days") or 0)
            >= MIN_SELECTION_CANDIDATE_DAYS
            and _number_or_none(development.get("d1_mean_return_pct")) is not None
        ):
            eligible.append(rule)
    selected = max(
        eligible,
        key=lambda rule: (
            float(rule["segments"]["development"]["overall"]["d1_mean_return_pct"]),
            float(rule["segments"]["development"]["overall"]["win_rate_pct"] or 0),
            int(rule["segments"]["development"]["overall"]["sample_count"]),
            str(rule["key"]),
        ),
    ) if eligible else None
    if selected is None:
        return {
            "key": None,
            "description": None,
            "selection_mode": DEVELOPMENT_SELECTION_MODE,
            "development": _empty_return_summary(),
            "validation": _empty_return_summary(),
            "holdout": _empty_return_summary(),
            "qualification_gate": {
                "passed": False,
                "reasons": ["no_development_rule_meets_minimum_coverage"],
            },
        }
    segments = selected["segments"]
    validation = segments["validation"]["overall"]
    holdout = segments["holdout"]["overall"]
    return {
        "key": selected["key"],
        "description": selected["description"],
        "selection_mode": DEVELOPMENT_SELECTION_MODE,
        "development": segments["development"]["overall"],
        "validation": validation,
        "holdout": holdout,
        "qualification_gate": _qualification_gate(validation, holdout),
    }


def _select_score_factor(
    variants: Sequence[Mapping[str, object]],
    *,
    source_case_bands: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    """Choose one score version and range using only its development result."""

    eligible: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
    for variant in variants:
        variant_name = str(variant.get("variant") or "")
        required_bands = tuple(source_case_bands.get(variant_name, ()))
        bands = variant.get("bands")
        if not isinstance(bands, Sequence):
            continue
        for band in bands:
            if not isinstance(band, Mapping):
                continue
            if source_case_bands and (
                len(set(required_bands)) != 1
                or band.get("band") not in set(required_bands)
            ):
                continue
            segments = band.get("segments")
            development = (
                segments.get("development", {}).get("overall")
                if isinstance(segments, Mapping)
                and isinstance(segments.get("development"), Mapping)
                else None
            )
            if not isinstance(development, Mapping):
                continue
            if (
                int(development.get("sample_count") or 0) >= MIN_SELECTION_SAMPLES
                and int(development.get("candidate_days") or 0)
                >= MIN_SELECTION_CANDIDATE_DAYS
                and _number_or_none(development.get("d1_mean_return_pct")) is not None
            ):
                eligible.append((variant, band))
    if not eligible:
        return {
            "variant": None,
            "band": None,
            "selection_mode": DEVELOPMENT_SELECTION_MODE,
            "development": _empty_return_summary(),
            "validation": _empty_return_summary(),
            "holdout": _empty_return_summary(),
            "qualification_gate": {
                "passed": False,
                "reasons": ["no_development_score_band_meets_minimum_coverage"],
            },
            "case_membership_gate": _score_case_membership_gate(
                None,
                None,
                source_case_bands,
            ),
        }
    selected_variant, selected_band = max(
        eligible,
        key=lambda values: (
            float(
                values[1]["segments"]["development"]["overall"][
                    "d1_mean_return_pct"
                ]
            ),
            float(
                values[1]["segments"]["development"]["overall"].get(
                    "win_rate_pct"
                )
                or 0
            ),
            int(values[1]["segments"]["development"]["overall"]["sample_count"]),
            str(values[0]["variant"]),
            str(values[1]["band"]),
        ),
    )
    segments = selected_band["segments"]
    development = segments["development"]["overall"]
    validation = segments["validation"]["overall"]
    holdout = segments["holdout"]["overall"]
    return {
        "variant": selected_variant["variant"],
        "band": selected_band["band"],
        "selection_mode": DEVELOPMENT_SELECTION_MODE,
        "development": development,
        "validation": validation,
        "holdout": holdout,
        "qualification_gate": _qualification_gate(validation, holdout),
        "case_membership_gate": _score_case_membership_gate(
            str(selected_variant["variant"]),
            str(selected_band["band"]),
            source_case_bands,
        ),
    }


def _normalize_source_case_bands(
    source_case_bands: Mapping[str, Mapping[str, Sequence[str]]] | None,
) -> dict[str, dict[str, tuple[str, ...]]]:
    """Validate source-case score membership before any return-based ranking."""

    result = {setup_type: {} for setup_type in SETUP_TYPES}
    if source_case_bands is None:
        return result
    known_bands = {label for _, _, label in SCORE_BANDS}
    for setup_type, variants in source_case_bands.items():
        if setup_type not in result:
            raise DailyFactorInputError(
                f"unsupported source-case score setup type: {setup_type}"
            )
        if not isinstance(variants, Mapping):
            raise DailyFactorInputError(
                f"source-case score bands for {setup_type} must be a mapping"
            )
        available_variants = set(SCORE_VARIANTS_BY_SETUP[setup_type])
        for variant, bands in variants.items():
            if variant not in available_variants:
                raise DailyFactorInputError(
                    f"source-case score variant {variant!r} does not belong to {setup_type}"
                )
            normalized = tuple(sorted({str(band) for band in bands}))
            if any(band not in known_bands for band in normalized):
                raise DailyFactorInputError(
                    f"source-case score bands for {setup_type}/{variant} are invalid"
                )
            result[setup_type][variant] = normalized
    return result


def _score_case_membership_gate(
    variant: str | None,
    band: str | None,
    source_case_bands: Mapping[str, Sequence[str]],
) -> dict[str, object]:
    if not source_case_bands:
        return {
            "passed": True,
            "required_bands": {},
            "reasons": [],
        }
    normalized = {
        name: tuple(sorted(set(values)))
        for name, values in source_case_bands.items()
    }
    required = normalized.get(variant or "", ())
    checks = {
        "selected_variant_has_source_cases": bool(required),
        "all_source_cases_share_one_band": len(required) == 1,
        "selected_band_contains_source_cases": bool(
            band is not None and len(required) == 1 and band == required[0]
        ),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "required_bands": {
            name: list(bands) for name, bands in normalized.items()
        },
        "reasons": [name for name, passed in checks.items() if not passed],
    }


def _select_frozen_rule(
    rules: Sequence[Mapping[str, object]],
    frozen_rule_key: str,
) -> dict[str, object]:
    """Return an externally frozen rule without ranking current-window outcomes."""

    selected = next(
        (rule for rule in rules if str(rule.get("key") or "") == frozen_rule_key),
        None,
    )
    if selected is None:
        raise DailyFactorInputError(
            f"frozen rule {frozen_rule_key!r} is absent from the rendered manifest"
        )
    segments = selected.get("segments")
    if not isinstance(segments, Mapping):
        raise DailyFactorInputError(
            f"frozen rule {frozen_rule_key!r} has no segment summary"
        )
    development = segments.get("development")
    validation = segments.get("validation")
    holdout = segments.get("holdout")
    if not all(
        isinstance(segment, Mapping)
        for segment in (development, validation, holdout)
    ):
        raise DailyFactorInputError(
            f"frozen rule {frozen_rule_key!r} has incomplete segment summaries"
        )
    development_overall = development.get("overall")
    validation_overall = validation.get("overall")
    holdout_overall = holdout.get("overall")
    if not all(
        isinstance(segment, Mapping)
        for segment in (development_overall, validation_overall, holdout_overall)
    ):
        raise DailyFactorInputError(
            f"frozen rule {frozen_rule_key!r} has incomplete return summaries"
        )
    return {
        "key": selected["key"],
        "description": selected["description"],
        "selection_mode": FROZEN_SELECTION_MODE,
        "development": development_overall,
        "validation": validation_overall,
        "holdout": holdout_overall,
        "qualification_gate": _qualification_gate(
            validation_overall,
            holdout_overall,
        ),
    }


def _qualification_gate(
    validation: Mapping[str, object],
    holdout: Mapping[str, object],
) -> dict[str, object]:
    checks = {
        "validation_sample_count": int(validation.get("sample_count") or 0)
        >= MIN_QUALIFICATION_SAMPLES,
        "holdout_sample_count": int(holdout.get("sample_count") or 0)
        >= MIN_QUALIFICATION_SAMPLES,
        "validation_candidate_days": int(validation.get("candidate_days") or 0)
        >= MIN_QUALIFICATION_CANDIDATE_DAYS,
        "holdout_candidate_days": int(holdout.get("candidate_days") or 0)
        >= MIN_QUALIFICATION_CANDIDATE_DAYS,
        "validation_positive_d1_mean": _positive(validation.get("d1_mean_return_pct")),
        "holdout_positive_d1_mean": _positive(holdout.get("d1_mean_return_pct")),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "reasons": [name for name, passed in checks.items() if not passed],
    }


def _exit_qualification_gate(
    validation: Mapping[str, object],
    holdout: Mapping[str, object],
    *,
    selected_probe: str | None,
    require_triggered_coverage: bool,
) -> dict[str, object]:
    coverage_field = (
        "triggered_candidate_days"
        if require_triggered_coverage
        else "candidate_days"
    )
    checks = {
        "selected_probe": bool(selected_probe),
        "validation_sample_count": int(validation.get("sample_count") or 0)
        >= MIN_QUALIFICATION_SAMPLES,
        "holdout_sample_count": int(holdout.get("sample_count") or 0)
        >= MIN_QUALIFICATION_SAMPLES,
        f"validation_{coverage_field}": int(validation.get(coverage_field) or 0)
        >= MIN_QUALIFICATION_CANDIDATE_DAYS,
        f"holdout_{coverage_field}": int(holdout.get(coverage_field) or 0)
        >= MIN_QUALIFICATION_CANDIDATE_DAYS,
        "validation_positive_mean_return": _positive(validation.get("mean_return_pct")),
        "holdout_positive_mean_return": _positive(holdout.get("mean_return_pct")),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "reasons": [name for name, passed in checks.items() if not passed],
    }


def _future_exit_bars(
    history: Sequence[Mapping[str, object]],
    dates: Sequence[date],
    calendar: Sequence[date],
    entry_date: date,
) -> tuple[dict[str, object], ...]:
    position_by_date = {trade_date: index for index, trade_date in enumerate(dates)}
    calendar_position = {trade_date: index for index, trade_date in enumerate(calendar)}
    entry_position = calendar_position.get(entry_date)
    if entry_position is None:
        return ()
    closes = [_required_positive_number(row.get("close_price"), "close_price") for row in history]
    rows: list[dict[str, object]] = []
    for offset in range(1, MAX_EXIT_HOLDING_SESSIONS + 1):
        target_position = entry_position + offset
        if target_position >= len(calendar):
            break
        trade_date = calendar[target_position]
        history_position = position_by_date.get(trade_date)
        if history_position is None:
            rows.append(
                {
                    "trade_date": trade_date,
                    "close_price": None,
                    "ma5": None,
                    "ma10": None,
                }
            )
            continue
        rows.append(
            {
                "trade_date": trade_date,
                "close_price": history[history_position].get("close_price"),
                "ma5": _trailing_average(closes, history_position, 5),
                "ma10": _trailing_average(closes, history_position, 10),
            }
        )
    return tuple(rows)


def _causal_d1_label(
    closes: Mapping[date, float | None],
    calendar: Sequence[date],
    positions: Mapping[date, int],
    symbol: str,
    trade_date: date,
    eligible_pairs: set[tuple[str, date]],
) -> tuple[float | None, str]:
    position = positions.get(trade_date)
    if position is None or position + 1 >= len(calendar):
        return None, "label_unavailable_calendar"
    if eligible_pairs and (symbol, calendar[position + 1]) not in eligible_pairs:
        return None, "label_unavailable_security"
    return d1_close_label_status(closes, calendar, trade_date)


def _d1_initial_short_trend_shape(
    history: Sequence[Mapping[str, object]],
    *,
    position: int | None,
) -> bool | None:
    """Label D+1 only; this outcome never participates in D-day selection."""

    if position is None:
        return None
    d1_features = build_extended_daily_features(
        history[max(0, position - 79) : position + 1]
    )
    return _has_initial_short_trend_shape(d1_features)


def _has_initial_short_trend_shape(features: Mapping[str, object]) -> bool:
    """Recognize the first MA10/20/30 trend form without MA5 or MA60 gates."""

    ma10 = _number_or_none(features.get("ma10"))
    ma20 = _number_or_none(features.get("ma20"))
    ma30 = _number_or_none(features.get("ma30"))
    ma10_slope = _number_or_none(features.get("ma10_slope_5d_pct"))
    ma20_slope = _number_or_none(features.get("ma20_slope_5d_pct"))
    return bool(
        ma10 is not None
        and ma20 is not None
        and ma30 is not None
        and ma10_slope is not None
        and ma20_slope is not None
        and ma10 > ma20 > ma30
        and ma10_slope > 0
        and ma20_slope > 0
    )


def _eligible_security_pairs(
    security_status: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> set[tuple[str, date]]:
    if not security_status:
        return set()
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    eligible: set[tuple[str, date]] = set()
    for row in security_status:
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        trade_date = _required_date(row.get("trade_date"))
        if not symbol or trade_date not in positions:
            continue
        if str(row.get("board") or "").strip().lower() != "main":
            continue
        if str(row.get("status") or "").strip().upper() == "DELISTED":
            continue
        if bool(row.get("suspended")) or bool(row.get("risk_warning")):
            continue
        listed_on = _required_date(row.get("listed_on"))
        first_position = next(
            (index for index, candidate in enumerate(calendar) if candidate >= listed_on),
            len(calendar),
        )
        if positions[trade_date] - first_position < 60:
            continue
        eligible.add((symbol, trade_date))
    return eligible


def _group_histories(
    bars: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    histories: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for index, row in enumerate(bars):
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        if not symbol:
            raise DailyFactorInputError(f"vt_symbol is required at bar row {index}")
        histories[symbol].append(row)
    for history in histories.values():
        _validate_history(history)
    return dict(histories)


def _iter_symbol_histories(
    bars: Any,
) -> Iterable[tuple[str, list[Mapping[str, object]]]]:
    """Yield one symbol at a time for a repository-sorted DataFrame input."""

    if not hasattr(bars, "itertuples") or not hasattr(bars, "columns"):
        yield from _group_histories(bars).items()
        return

    columns = tuple(str(value) for value in bars.columns)
    positions = {column: index for index, column in enumerate(columns)}
    required = (
        "vt_symbol",
        "trade_date",
        "open_price",
        "close_price",
        "high_price",
        "low_price",
    )
    missing = [column for column in required if column not in positions]
    if missing:
        raise DailyFactorInputError(
            "DataFrame input is missing daily-bar columns: " + ", ".join(missing)
        )
    row_fields = tuple(
        field
        for field in (*required, "volume", "turnover", "turnover_rate")
        if field in positions
    )
    current_symbol: str | None = None
    current_history: list[Mapping[str, object]] = []
    completed_symbols: set[str] = set()
    for row_index, values in enumerate(bars.itertuples(index=False, name=None)):
        symbol = str(values[positions["vt_symbol"]] or "").strip().upper()
        if not symbol:
            raise DailyFactorInputError(f"vt_symbol is required at bar row {row_index}")
        if current_symbol is not None and symbol != current_symbol:
            _validate_history(current_history)
            completed_symbols.add(current_symbol)
            yield current_symbol, current_history
            current_history = []
        if symbol in completed_symbols:
            raise DailyFactorInputError(
                "DataFrame daily bars must be ordered by vt_symbol then trade_date"
            )
        current_symbol = symbol
        current_history.append(
            {field: values[positions[field]] for field in row_fields}
        )
    if current_symbol is not None:
        _validate_history(current_history)
        yield current_symbol, current_history


def _validate_history(history: list[Mapping[str, object]]) -> None:
    history.sort(key=lambda row: _required_date(row.get("trade_date")))
    for row in history:
        _required_positive_number(row.get("open_price"), "open_price")
        _required_positive_number(row.get("close_price"), "close_price")
        _required_positive_number(row.get("high_price"), "high_price")
        _required_positive_number(row.get("low_price"), "low_price")


def _visible_history(
    history: Sequence[Mapping[str, object]],
    *,
    as_of_date: date | None,
) -> tuple[Mapping[str, object], ...]:
    sorted_history = tuple(sorted(history, key=lambda row: _required_date(row.get("trade_date"))))
    if as_of_date is None:
        return sorted_history
    visible = tuple(
        row for row in sorted_history if _required_date(row.get("trade_date")) <= as_of_date
    )
    if not visible:
        raise DailyFactorInputError("no bars available at the requested as_of_date")
    return visible


def _moving_average_series(
    values: Sequence[float],
    window: int,
) -> list[float | None]:
    result: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        result.append(total / window if index + 1 >= window else None)
    return result


def _series_slope_pct(
    values: Sequence[float | None],
    *,
    lookback: int,
    end_offset: int = 0,
) -> float | None:
    index = len(values) - 1 - end_offset
    previous_index = index - lookback
    if previous_index < 0:
        return None
    current = values[index]
    previous = values[previous_index]
    if current is None or previous is None or previous <= 0:
        return None
    return _round_pct(_pct_change(current, previous))


def _series_ma_distance_pct(
    first: Sequence[float | None],
    second: Sequence[float | None],
    closes: Sequence[float],
    *,
    lookback: int,
) -> float | None:
    index = len(closes) - 1 - lookback
    if index < 0:
        return None
    return _signed_ma_distance_pct(first[index], second[index], closes[index])


def _recent_cross_age(
    closes: Sequence[float],
    *,
    fast_window: int,
    slow_window: int,
    lookback: int = RECENT_CROSS_LOOKBACK,
) -> int | None:
    final_index = len(closes) - 1
    final_difference = _ma_difference(
        closes,
        final_index,
        fast_window=fast_window,
        slow_window=slow_window,
    )
    if final_difference is None or final_difference < 0:
        return None
    for age in range(lookback):
        index = final_index - age
        if index < 1:
            break
        current = _ma_difference(
            closes,
            index,
            fast_window=fast_window,
            slow_window=slow_window,
        )
        previous = _ma_difference(
            closes,
            index - 1,
            fast_window=fast_window,
            slow_window=slow_window,
        )
        if current is not None and previous is not None and current >= 0 > previous:
            return age
    return None


def _ma10_ma20_next_close_required_return_pct(
    closes: Sequence[float],
) -> float | None:
    """Return the D+1 close return needed for MA10 to reach MA20."""

    return _ma10_next_close_required_return_pct(closes, slow_window=20)


def _ma10_ma20_convergence_efficiency_5d(
    closes: Sequence[float],
    *,
    ma10_series: Sequence[float | None],
    ma20_series: Sequence[float | None],
) -> float | None:
    """Normalize five-session MA10/20 gap closure by observed price churn."""

    if len(closes) < 6 or len(ma10_series) < 6 or len(ma20_series) < 6:
        return None
    ma10_then, ma10_now = ma10_series[-6], ma10_series[-1]
    ma20_then, ma20_now = ma20_series[-6], ma20_series[-1]
    if None in (ma10_then, ma10_now, ma20_then, ma20_now):
        return None
    gap_then = _pct_change(float(ma10_then), float(ma20_then))
    gap_now = _pct_change(float(ma10_now), float(ma20_now))
    churn = sum(
        abs(_pct_change(closes[index], closes[index - 1]))
        for index in range(len(closes) - 5, len(closes))
    )
    return _round_pct((gap_now - gap_then) / churn) if churn else None


def _ma10_ma30_next_close_required_return_pct(
    closes: Sequence[float],
) -> float | None:
    """Return the D+1 close return needed for MA10 to reach MA30."""

    return _ma10_next_close_required_return_pct(closes, slow_window=30)


def _ma10_next_close_required_return_pct(
    closes: Sequence[float],
    *,
    slow_window: int,
) -> float | None:
    """Solve the next-close price at which MA10 reaches one longer average."""

    if len(closes) < slow_window:
        return None
    current_close = closes[-1]
    if current_close <= 0:
        return None

    # At D+1 both averages contain the unknown close x.  Solving
    # (sum9 + x) / 10 = (sum(slow-1) + x) / slow yields this price.
    short_sum = sum(closes[-9:])
    slow_sum = sum(closes[-(slow_window - 1) :])
    required_close = (
        10 * slow_sum - slow_window * short_sum
    ) / (slow_window - 10)
    return _round_pct((required_close - current_close) / current_close * 100)


def _recent_ma10_ma20_upcross_after_long_bear_age(
    ma10_series: Sequence[float | None],
    ma20_series: Sequence[float | None],
    ma30_series: Sequence[float | None],
    *,
    lookback: int,
) -> int | None:
    """Return the age of an MA10/20 upcross preceded by a long bear run."""

    final_index = len(ma10_series) - 1
    for age in range(lookback):
        index = final_index - age
        if index < 1:
            break
        prior_ma10 = ma10_series[index - 1]
        prior_ma20 = ma20_series[index - 1]
        prior_ma30 = ma30_series[index - 1]
        current_ma10 = ma10_series[index]
        current_ma20 = ma20_series[index]
        if not (
            prior_ma10 is not None
            and prior_ma20 is not None
            and prior_ma30 is not None
            and current_ma10 is not None
            and current_ma20 is not None
            and prior_ma10 < prior_ma20 < prior_ma30
            and current_ma10 >= current_ma20
        ):
            continue

        bear_days = 0
        for prior_index in range(index - 1, -1, -1):
            ma10 = ma10_series[prior_index]
            ma20 = ma20_series[prior_index]
            ma30 = ma30_series[prior_index]
            if ma10 is None or ma20 is None or ma30 is None or not ma10 < ma20 < ma30:
                break
            bear_days += 1
        if bear_days >= LONG_BEAR_ALIGNMENT_MIN_SESSIONS:
            return age
    return None


def _was_ma_above_within(
    closes: Sequence[float],
    *,
    fast_window: int,
    slow_window: int,
    lookback: int,
) -> bool:
    """Return whether a completed prior session had fast MA above slow MA."""

    final_index = len(closes) - 1
    for index in range(max(0, final_index - lookback), final_index):
        difference = _ma_difference(
            closes,
            index,
            fast_window=fast_window,
            slow_window=slow_window,
        )
        if difference is not None and difference > 0:
            return True
    return False


def _ma_difference(
    closes: Sequence[float],
    index: int,
    *,
    fast_window: int,
    slow_window: int,
) -> float | None:
    if index < 0 or index + 1 < max(fast_window, slow_window):
        return None
    fast = fmean(closes[index - fast_window + 1 : index + 1])
    slow = fmean(closes[index - slow_window + 1 : index + 1])
    return fast - slow


def _signed_ma_distance_pct(
    first: float | None,
    second: float | None,
    close_price: float | None,
) -> float | None:
    if first is None or second is None or close_price is None or close_price <= 0:
        return None
    return _round_pct((first - second) / close_price * 100)


def _price_to_ma_distance_pct(
    price: float | None,
    moving_average: float | None,
) -> float | None:
    if price is None or moving_average is None or moving_average <= 0:
        return None
    return _round_pct((price - moving_average) / moving_average * 100)


def _near_or_recent_cross(distance_pct: float | None) -> bool:
    return bool(
        distance_pct is not None
        and -NEAR_MA_DISTANCE_PCT <= distance_pct <= RECENT_CROSS_MAX_ABOVE_PCT
    )


def _ma_contact(distance_pct: float | None) -> bool:
    return bool(
        distance_pct is not None and abs(distance_pct) <= MA_CONTACT_DISTANCE_PCT
    )


def _recent_pullback_from_prior_high_pct(
    closes: Sequence[float],
    *,
    lookback: int,
) -> float | None:
    if len(closes) < 2:
        return None
    prior = closes[max(0, len(closes) - lookback) : -1]
    if not prior:
        return None
    return _pct_change(closes[-1], max(prior))


def _two_leg_volume_shape(
    values: Sequence[float | None],
    *,
    first_direction: str,
    first_length: int,
    second_direction: str,
    second_length: int,
) -> bool:
    """Check two adjacent monotonic volume legs ending on D without future bars."""

    required = first_length + second_length
    if len(values) < required:
        return False
    window = values[-required:]
    first = window[:first_length]
    second = window[first_length:]
    return _volume_moves_in_direction(first, first_direction) and _volume_moves_in_direction(
        second,
        second_direction,
    )


def _volume_moves_in_direction(
    values: Sequence[float | None],
    direction: str,
) -> bool:
    if direction not in {"expand", "shrink"}:
        raise DailyFactorInputError(f"unsupported volume direction: {direction}")
    if len(values) < 2 or any(value is None or value <= 0 for value in values):
        return False
    pairs = zip(values, values[1:])
    if direction == "expand":
        return all(current is not None and previous is not None and current > previous for previous, current in pairs)
    return all(current is not None and previous is not None and current < previous for previous, current in pairs)


def _support_low_touch(
    low_distance_pct: float | None,
    close_distance_pct: float | None,
) -> bool:
    return bool(
        low_distance_pct is not None
        and close_distance_pct is not None
        and -4.0 <= low_distance_pct <= 1.5
        and close_distance_pct >= -1.5
    )


def _support_low_touch_broad(
    low_distance_pct: float | None,
    close_distance_pct: float | None,
) -> bool:
    return bool(
        low_distance_pct is not None
        and close_distance_pct is not None
        and SUPPORT_BROAD_LOW_MIN_PCT <= low_distance_pct <= 1.5
        and close_distance_pct >= SUPPORT_BROAD_CLOSE_MIN_PCT
    )


def _support_close_near(close_distance_pct: float | None) -> bool:
    return bool(
        close_distance_pct is not None
        and abs(close_distance_pct) <= 1.5
    )


def _support_midpoint_near(midpoint_distance_pct: float | None) -> bool:
    return bool(
        midpoint_distance_pct is not None
        and abs(midpoint_distance_pct) <= 1.5
    )


def _volume_shape(features: Mapping[str, object]) -> str:
    spearman = _number_or_none(features.get("volume_spearman_5d"))
    down_streak = _integer_or_none(features.get("volume_down_streak")) or 0
    up_streak = _integer_or_none(features.get("volume_up_streak")) or 0
    if spearman is None:
        return "unavailable"
    if spearman <= -0.3 and down_streak >= 3:
        return "staircase_shrink"
    if spearman >= 0.3 and up_streak >= 3:
        return "staircase_expand"
    return "mixed"


def _daily_price_state(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value <= 0:
        return "weak_or_down"
    if value <= 1.5:
        return "small_positive"
    return "large_green"


def _feature_snapshot(features: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "daily_return_pct",
        "pre_attack_base_phase",
        "pre_attack_base_window_sessions",
        "pre_attack_base_pivot_age_sessions",
        "pre_attack_base_release_after_final_pivot",
        "pre_attack_base_settlement_sessions",
        "pre_attack_base_tail_span_to_median_range",
        "pre_attack_base_tail_floor_vs_pivot_pct",
        "pre_attack_base_tail_retested_release",
        "pre_attack_base_ma10_ma20_progress_per_churn",
        "pre_attack_base_tail_floor_vs_release_origin_pct",
        "ma10_ma20_signed_distance_pct",
        "ma10_ma20_convergence_efficiency_5d",
        "ma10_ma20_next_close_required_return_pct",
        "ma10_ma30_signed_distance_pct",
        "ma10_ma30_next_close_required_return_pct",
        "ma20_ma30_signed_distance_pct",
        "intraday_midpoint_price",
        "midpoint_to_ma5_pct",
        "midpoint_to_ma10_pct",
        "ma_cluster_spread_pct",
        "ma_cluster_convergence_speed_5d_pct",
        "ma10_crossed_ma20_age_sessions",
        "ma10_crossed_ma30_age_sessions",
        "ma20_crossed_ma30_age_sessions",
        "ma10_crossed_ma20_age_sessions_15d",
        "ma10_crossed_ma30_age_sessions_15d",
        "ma10_crossed_ma20_after_long_bear_age_sessions_15d",
        "ma10_crossed_ma20_after_long_bear_within_15d",
        "ma10_dual_cross_within_15d",
        "ma10_dual_cross_within_7d",
        "ma10_above_ma20_and_ma30",
        "ma10_above_ma20",
        "ma10_below_ma30",
        "current_full_bear_alignment",
        "close_below_ma30",
        "ma20_ma30_contact",
        "transition_ma20_ma30_tight_contact",
        "m10_dual_cross_before_m20_m30",
        "ma10_ma20_slopes_up",
        "post_cross_pullback",
        "ma10_slope_2d_pct",
        "ma10_slope_improvement_2d_pct",
        "ma10_ma20_gap_narrowing_3d_pct",
        "ma10_ma30_fast_convergence",
        "last_volume_change_pct",
        "volume_shape",
        "vol_monotone_6d",
        "price_state",
        "small_positive_candle",
        "ma5_low_touch",
        "ma10_low_touch",
        "ma5_close_near",
        "ma10_close_near",
        "ma5_midpoint_near",
        "ma10_midpoint_near",
        "low_to_ma20_pct",
        "low_to_ma30_pct",
        "close_to_ma20_pct",
        "close_to_ma30_pct",
        "ma20_low_touch",
        "ma30_low_touch",
        "oversold_low_support",
        "yang_wrap_three_ma",
        "yang_wrap_two_ma",
        "yang_wrap_nearest_ma_low_abs_pct",
        "yang_wrap_volume_end_to_peak_ratio_6d",
        "yang_wrap_stable_base",
        "close_off_low_pct",
        "support_close_reaction",
        "aggressive_pullback",
        "turnover_rate_pct",
        "trend_slope_profile",
        "trend_stable_bull",
        "trend_rebuilt_recently",
        "trend_transition_preparation_eligible",
        "trend_transition_eligible",
        "close_to_ma5_pct",
        "trend_dist_excess_pct",
        "candle_range_pct",
        "candle_quiet",
        "signal_day_not_limit_up_closed",
        "prior_daily_return_pct",
        "prior_ma5_low_touch",
        "trend_overextended",
        "trend_first_crack_chase",
    )
    return {key: features.get(key) for key in keys}


def _research_answers(report: Mapping[str, object]) -> list[dict[str, str]]:
    blocked = bool(report.get("blockers")) or report.get("status") == "blocked"
    if blocked:
        return [
            {
                "question": "扩展低吸发现",
                "status": "insufficient_data",
                "detail": "数据门禁未通过，未运行候选选择或卖点比较。",
            }
        ]
    families = report.get("families")
    if not isinstance(families, Mapping):
        return []
    answers: list[dict[str, str]] = []
    for setup_type, question in (
        ("oversold_rebound", "超跌：MA10/20/30 的贴合、上穿先后和缩量"),
        ("trend_pullback", "趋势：MA5/MA10 支撑、低点/中心价/收盘比较"),
    ):
        family = families.get(setup_type)
        selected = family.get("selected_rule") if isinstance(family, Mapping) else None
        if not isinstance(selected, Mapping) or not selected.get("key"):
            answers.append(
                {
                    "question": question,
                    "status": "insufficient_data",
                    "detail": "开发期没有达到预设覆盖门槛的候选。",
                }
            )
            continue
        validation = selected.get("validation")
        holdout = selected.get("holdout")
        gate = selected.get("qualification_gate")
        answers.append(
            {
                "question": question,
                "status": "supported"
                if isinstance(gate, Mapping) and gate.get("passed")
                else "not_supported",
                "detail": "{key}：验证 D+1 {validation}，留出 D+1 {holdout}。".format(
                    key=selected.get("key"),
                    validation=_number_text(
                        validation.get("d1_mean_return_pct")
                        if isinstance(validation, Mapping)
                        else None
                    ),
                    holdout=_number_text(
                        holdout.get("d1_mean_return_pct")
                        if isinstance(holdout, Mapping)
                        else None
                    ),
                ),
            }
        )
    score_factors = report.get("score_factors")
    if isinstance(score_factors, Mapping):
        for setup_type, question in (
            ("oversold_rebound", "超跌反弹综合分数的最佳范围"),
            ("trend_pullback", "趋势上涨综合分数的最佳范围"),
        ):
            family = score_factors.get(setup_type)
            selected = (
                family.get("selected_score_factor")
                if isinstance(family, Mapping)
                else None
            )
            if not isinstance(selected, Mapping) or not selected.get("band"):
                answers.append(
                    {
                        "question": question,
                        "status": "insufficient_data",
                        "detail": "开发期没有达到预设覆盖门槛的分数范围。",
                    }
                )
                continue
            gate = selected.get("qualification_gate")
            validation = selected.get("validation")
            holdout = selected.get("holdout")
            answers.append(
                {
                    "question": question,
                    "status": "supported"
                    if isinstance(gate, Mapping) and gate.get("passed")
                    else "not_supported",
                    "detail": "{variant} {band}：验证 D+1 {validation}，留出 D+1 {holdout}。".format(
                        variant=selected.get("variant"),
                        band=selected.get("band"),
                        validation=_number_text(
                            validation.get("d1_mean_return_pct")
                            if isinstance(validation, Mapping)
                            else None
                        ),
                        holdout=_number_text(
                            holdout.get("d1_mean_return_pct")
                            if isinstance(holdout, Mapping)
                            else None
                        ),
                    ),
                }
            )
    for setup_type, question in (
        ("oversold_rebound", "超跌反弹的收盘卖点"),
        ("trend_pullback", "趋势低吸的收盘卖点"),
    ):
        family = families.get(setup_type)
        selected = family.get("selected_rule") if isinstance(family, Mapping) else None
        answers.append(
            _research_answer_for_exit(
                question,
                selected,
                selection_key="exit_selection",
                return_basis="D 日收盘至卖点收盘",
            )
        )
    for setup_type, question in (
        ("oversold_rebound", "超跌反弹的首次严格涨停后持有"),
        ("trend_pullback", "趋势低吸的首次严格涨停后持有"),
    ):
        family = families.get(setup_type)
        selected = family.get("selected_rule") if isinstance(family, Mapping) else None
        answers.append(
            _research_answer_for_exit(
                question,
                selected,
                selection_key="post_limit_up_exit_selection",
                return_basis="首次严格涨停收盘至后续收盘（不含首次涨停本身）",
            )
        )
    return answers


def _research_answer_for_exit(
    question: str,
    selected: Mapping[str, object] | None,
    *,
    selection_key: str,
    return_basis: str,
) -> dict[str, str]:
    exits = selected.get(selection_key) if isinstance(selected, Mapping) else None
    if not isinstance(exits, Mapping) or not exits.get("selected_probe"):
        return {
            "question": question,
            "status": "insufficient_data",
            "detail": "没有满足开发期最小覆盖的已选规则卖点。",
        }

    validation = exits.get("validation")
    holdout = exits.get("holdout")
    entry_gate = selected.get("qualification_gate")
    exit_gate = exits.get("qualification_gate")
    entry_passed = isinstance(entry_gate, Mapping) and bool(entry_gate.get("passed"))
    exit_passed = isinstance(exit_gate, Mapping) and bool(exit_gate.get("passed"))
    if entry_passed and exit_passed:
        verdict = "入场规则与卖点均通过时间外门禁。"
    else:
        verdict = "入场规则和卖点未同时通过验证与留出门禁，不能作为卖点。"
    return {
        "question": question,
        "status": "supported" if entry_passed and exit_passed else "not_supported",
        "detail": "{probe}（{basis}）：验证 {validation}，留出 {holdout}；{verdict}".format(
            probe=exits.get("selected_probe"),
            basis=return_basis,
            validation=_number_text(
                validation.get("mean_return_pct")
                if isinstance(validation, Mapping)
                else None
            ),
            holdout=_number_text(
                holdout.get("mean_return_pct")
                if isinstance(holdout, Mapping)
                else None
            ),
            verdict=verdict,
        ),
    }


def _empty_families() -> dict[str, dict[str, object]]:
    return {
        setup_type: {
            "rules": [],
            "selected_rule": {
                "key": None,
                "description": None,
                "development": _empty_return_summary(),
                "validation": _empty_return_summary(),
                "holdout": _empty_return_summary(),
                "qualification_gate": {"passed": False, "reasons": ["data_blocker"]},
                "exit_selection": _empty_exit_selection(),
                "post_limit_up_exit_selection": _empty_exit_selection(),
            },
        }
        for setup_type in SETUP_TYPES
    }


def _empty_score_factors() -> dict[str, dict[str, object]]:
    return {
        setup_type: {
            "variants": [
                {
                    "variant": variant,
                    "bands": [],
                }
                for variant in SCORE_VARIANTS_BY_SETUP[setup_type]
            ],
            "selected_score_factor": {
                "variant": None,
                "band": None,
                "selection_mode": DEVELOPMENT_SELECTION_MODE,
                "development": _empty_return_summary(),
                "validation": _empty_return_summary(),
                "holdout": _empty_return_summary(),
                "qualification_gate": {
                    "passed": False,
                    "reasons": ["data_blocker"],
                },
            },
        }
        for setup_type in SETUP_TYPES
    }


def _score_full_history_gate(
    score_factors: Mapping[str, object],
) -> dict[str, object]:
    checks: dict[str, bool] = {}
    for setup_type in SETUP_TYPES:
        family = score_factors.get(setup_type)
        selected = (
            family.get("selected_score_factor")
            if isinstance(family, Mapping)
            else None
        )
        checks[f"{setup_type}_selection"] = bool(
            isinstance(selected, Mapping)
            and selected.get("variant")
            and selected.get("band")
        )
        checks[f"{setup_type}_qualification"] = bool(
            isinstance(selected, Mapping)
            and isinstance(selected.get("qualification_gate"), Mapping)
            and selected["qualification_gate"].get("passed")
        )
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "reasons": [name for name, passed in checks.items() if not passed],
        "policy": "两类低吸分数因子均须先通过近半年 validation 与 holdout，才可冻结后运行全历史。",
    }


def _empty_full_history_score_gate() -> dict[str, object]:
    return {
        "passed": False,
        "checks": {},
        "reasons": ["data_blocker"],
        "policy": "两类低吸分数因子均须先通过近半年 validation 与 holdout，才可冻结后运行全历史。",
    }


def _empty_return_summary() -> dict[str, object]:
    return {
        "candidate_count": 0,
        "candidate_days": 0,
        "sample_count": 0,
        "label_unavailable_count": 0,
        "label_excluded_main_board_price_limit_count": 0,
        "win_rate_pct": None,
        "negative_count": 0,
        "negative_rate_pct": None,
        "d1_mean_return_pct": None,
        "d1_median_return_pct": None,
        "negative_mean_return_pct": None,
        "daily_candidate_average": 0.0,
    }


def _empty_exit_summary() -> dict[str, object]:
    return {
        "candidate_count": 0,
        "candidate_days": 0,
        "triggered_candidate_count": 0,
        "triggered_candidate_days": 0,
        "closed_count": 0,
        "unavailable_count": 0,
        "not_triggered_count": 0,
        "sample_count": 0,
        "win_rate_pct": None,
        "mean_return_pct": None,
        "median_return_pct": None,
        "mean_holding_sessions": None,
        "exit_reasons": {},
    }


def _empty_exit_selection() -> dict[str, object]:
    return {
        "probes": [],
        "selected_probe": None,
        "development": _empty_exit_summary(),
        "validation": _empty_exit_summary(),
        "holdout": _empty_exit_summary(),
        "qualification_gate": {
            "passed": False,
            "reasons": ["no_development_exit_probe_meets_minimum_coverage"],
        },
    }


def _normalized_manifest(
    rule_manifest: Mapping[str, Sequence[DiscoveryRule]],
) -> dict[str, tuple[DiscoveryRule, ...]]:
    result: dict[str, tuple[DiscoveryRule, ...]] = {}
    for setup_type in SETUP_TYPES:
        rules = tuple(rule_manifest.get(setup_type, ()))
        for rule in rules:
            if rule.setup_type != setup_type:
                raise DailyFactorInputError(
                    f"rule {rule.key} does not belong to {setup_type}"
                )
        result[setup_type] = rules
    return result


def _segment_dates(split) -> dict[date, str]:
    return {
        **{value: "development" for value in split.development_dates},
        **{value: "validation" for value in split.validation_dates},
        **{value: "holdout" for value in split.holdout_dates},
    }


def _time_split_payload(split) -> dict[str, object]:
    return {
        "development_start": split.development_dates[0].isoformat(),
        "development_end": split.development_dates[-1].isoformat(),
        "development_days": len(split.development_dates),
        "embargo_start": split.embargo_dates[0].isoformat(),
        "embargo_end": split.embargo_dates[-1].isoformat(),
        "embargo_days": len(split.embargo_dates),
        "validation_start": split.validation_dates[0].isoformat(),
        "validation_end": split.validation_dates[-1].isoformat(),
        "validation_days": len(split.validation_dates),
        "holdout_start": split.holdout_dates[0].isoformat(),
        "holdout_end": split.holdout_dates[-1].isoformat(),
        "holdout_days": len(split.holdout_dates),
    }


def _strict_calendar(values: Sequence[date]) -> tuple[date, ...]:
    normalized = tuple(sorted(set(values)))
    if not normalized:
        raise DailyFactorInputError("market calendar is required")
    return normalized


def _required_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise DailyFactorInputError("trade_date is required")


def _required_positive_number(value: object, field: str) -> float:
    number = _number_or_none(value)
    if number is None or number <= 0:
        raise DailyFactorInputError(f"{field} must be a positive finite number")
    return number


def _number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer_or_none(value: object) -> int | None:
    number = _number_or_none(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _pct_change(current: float | None, previous: float | None) -> float:
    if current is None or previous is None or previous <= 0:
        raise DailyFactorInputError("percentage change requires positive values")
    return (current / previous - 1) * 100


def _trailing_average(
    values: Sequence[float],
    index: int,
    window: int,
) -> float | None:
    if index + 1 < window:
        return None
    return fmean(values[index - window + 1 : index + 1])


def _difference_or_none(first: object, second: object) -> float | None:
    first_number = _number_or_none(first)
    second_number = _number_or_none(second)
    if first_number is None or second_number is None:
        return None
    return _round_pct(first_number - second_number)


def _rate_pct(numerator: int, denominator: int) -> float | None:
    return _round_pct(numerator / denominator * 100) if denominator else None


def _round_pct(value: float) -> float:
    return round(value, 4)


def _positive(value: object) -> bool:
    number = _number_or_none(value)
    return number is not None and number > 0


def _score_band(score: float | None) -> str | None:
    if score is None:
        return None
    for lower, upper, label in SCORE_BANDS:
        if lower <= score <= upper:
            return label
    return None


def _number_text(value: object) -> str:
    number = _number_or_none(value)
    return "-" if number is None else f"{number:.4f}%"


def _markdown_cell(value: object) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, Mapping):
        return json.dumps(value, ensure_ascii=False, default=str).replace("|", "/")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ", ".join(str(item) for item in value) or "-"
    return str(value).replace("|", "/")
