"""Read-only extended discovery for the daily low-suction research brief.

The frozen v3/v4 studies remain the baseline. This module tests a deliberately
small manifest of source-document hypotheses without changing those factors,
fetching data, or writing a strategy/product record.
"""

from __future__ import annotations

import heapq
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
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
OVERSOLD_CLUSTER_MAX_PCT = 5.0
OVERSOLD_PROCESS_DAILY_RETURN_MIN_PCT = -10.0
OVERSOLD_PROCESS_PULLBACK_LOOKBACK = 6
OVERSOLD_PROCESS_PULLBACK_MIN_PCT = -3.0
LONG_BEAR_ALIGNMENT_MIN_SESSIONS = 10
MA_CONTACT_DISTANCE_PCT = 0.5
TRANSITION_MA20_MA30_CONTACT_PCT = 0.25
SUPPORT_BROAD_LOW_MIN_PCT = -5.0
SUPPORT_BROAD_CLOSE_MIN_PCT = -2.0
SUPPORT_CLOSE_REACTION_MIN_PCT = 0.3
TRANSITION_CLOSE_ANCHOR_MIN_PCT = -3.0
TRANSITION_CLOSE_ANCHOR_MAX_PCT = 2.5
TURNOVER_RATE_LOW_MAX_PCT = 3.0
TURNOVER_RATE_GATE_MAX_PCT = 8.0
CAPITULATION_TURNOVER_MAX_PCT = 5.0
TRANSITION_TURNOVER_5D_MAX_PCT = 8.0
TREND_GENTLE_SLOPE_MAX_PCT = 2.0
EARLY_TREND_ALIGNMENT_MIN_SESSIONS = 3
EARLY_TREND_ALIGNMENT_MAX_SESSIONS = 20
MA10_MA30_CONVERGENCE_LOOKBACK = 5
MA10_MA30_CONVERGENCE_MIN_PCT = 0.5
PROCESS_VOLUME_CHANGE_PCT = 10.0
MA5_EXTENSION_MIN_PCT = 1.5
TREND_CANDLE_QUIET_RANGE_MAX_PCT = 5.0
TREND_DIST_EXCESS_MAX_PCT = 2.0
TREND_REBUILD_PRIOR_LOOKBACK = 10
TREND_REBUILD_MIN_DISORDERED_SESSIONS = 3
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
OVERSOLD_TO_TREND_PREPARATION_RULE_KEY = (
    "oversold_to_trend_pre_cross_ma10_ma20_contact"
)
OVERSOLD_TO_TREND_LOW_SUPPORT_RULE_KEY = (
    "oversold_to_trend_dual_cross_low_support"
)
OVERSOLD_TO_TREND_CLOSE_ANCHORED_RULE_KEY = (
    "oversold_to_trend_dual_cross_close_anchored"
)
OVERSOLD_TO_TREND_TURNOVER_CAP_RULE_KEY = (
    "oversold_to_trend_dual_cross_turnover_cap"
)
TRANSITION_RULE_KEYS = frozenset(
    {
        OVERSOLD_TO_TREND_PREPARATION_RULE_KEY,
        OVERSOLD_TO_TREND_RULE_KEY,
    }
)
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
    core_rule_key: str | None = None
    volume_shape: str | None = None


OVERSOLD_CORE_RULES = (
    DiscoveryRule(
        "m10_m20_near_or_crossed_down",
        "oversold_rebound",
        "MA10 贴近或刚上穿 MA20，D 日弱势或下跌",
    ),
    DiscoveryRule(
        "m10_m30_near_or_crossed_down",
        "oversold_rebound",
        "MA10 贴近或刚上穿 MA30，D 日弱势或下跌",
    ),
    DiscoveryRule(
        "m20_m30_near_or_crossed_down",
        "oversold_rebound",
        "MA20 贴近或刚上穿 MA30，D 日弱势或下跌",
    ),
    DiscoveryRule(
        "staged_m10_first_down",
        "oversold_rebound",
        "MA10 先上穿 MA20，MA20 尚未上穿 MA30，D 日弱势或下跌",
    ),
    DiscoveryRule(
        "ma10_low_retest_during_staged_cross",
        "oversold_rebound",
        "MA10 先上穿 MA20、MA20 尚未上穿 MA30，D 日低点回踩 MA10",
    ),
    DiscoveryRule(
        "m5_m10_joint_attack_before_ma20_cross",
        "oversold_rebound",
        "熊市结构后 MA5 转升、MA10 降速并向 MA20 收敛，尚未上穿 MA20",
    ),
    DiscoveryRule(
        "m10_dual_cross_before_m20_m30_down",
        "oversold_rebound",
        "MA10 已依次上穿 MA20、MA30，MA20 尚未上穿 MA30，D 日弱势或下跌",
    ),
    DiscoveryRule(
        "m10_m30_contact_after_m10_cross_aggressive_pullback",
        "oversold_rebound",
        "MA10 上穿 MA20 后，放量或缩量深回撤中 MA10 回贴 MA30",
    ),
    DiscoveryRule(
        "ma10_low_retest_after_long_bear_staged_cross",
        "oversold_rebound",
        "长期空头结构后 MA10 先上穿 MA20、MA20 尚未上穿 MA30，D 日低点回踩 MA10",
    ),
    DiscoveryRule(
        "m5_m10_joint_attack_after_long_bear",
        "oversold_rebound",
        "长期空头结构后 MA5 转升、MA10 降速并向 MA20 收敛，尚未上穿 MA20",
    ),
    DiscoveryRule(
        "m10_m30_contact_after_long_bear_aggressive_pullback",
        "oversold_rebound",
        "长期空头结构后 MA10 上穿 MA20，深回撤中 MA10 回贴 MA30",
    ),
)


OVERSOLD_LOW_SUPPORT_RULES = (
    DiscoveryRule(
        "m10_m30_contact_after_m10_cross_low_support",
        "oversold_rebound",
        "MA10 上穿 MA20 后回贴 MA30，D 日低点在 MA10/20/30 获实际支撑",
    ),
    DiscoveryRule(
        "m10_m30_contact_after_long_bear_low_support",
        "oversold_rebound",
        "长期空头结构后 MA10 上穿 MA20 回贴 MA30，D 日低点在 MA10/20/30 获实际支撑",
    ),
    DiscoveryRule(
        "ma30_low_retest_after_m10_cross",
        "oversold_rebound",
        "MA10 上穿 MA20 后，D 日低点直接回踩 MA30 且收盘守住支撑",
    ),
    DiscoveryRule(
        "ma30_low_retest_after_long_bear_m10_cross",
        "oversold_rebound",
        "长期空头结构后 MA10 上穿 MA20，D 日低点直接回踩 MA30 且收盘守住支撑",
    ),
)


OVERSOLD_V3_RULES = (
    DiscoveryRule(
        "v3_oversold_staged_low_support_turnover_low",
        "oversold_rebound",
        "v3：空头后分阶段上穿过程 + D 日低点获均线支撑 + 换手率 < 3%",
    ),
    DiscoveryRule(
        "v3_oversold_staged_low_support_turnover_gate",
        "oversold_rebound",
        "v3：空头后分阶段上穿过程 + D 日低点获均线支撑 + 换手率 < 8%",
    ),
    DiscoveryRule(
        "v3_oversold_capitulation_rebound_tight",
        "oversold_rebound",
        "v3：MA10 上穿后回贴 MA30 的崩盘日，换手率 < 3% 且收盘脱离低点 0.3~1.5%",
    ),
    DiscoveryRule(
        "v3_oversold_capitulation_rebound_broad",
        "oversold_rebound",
        "v3：MA10 上穿后回贴 MA30 的崩盘日，换手率 < 5% 且收盘脱离低点 >= 0.3%",
    ),
)


EXPLICIT_CASE_OVERSOLD_RULES = (    DiscoveryRule(
        "ma10_low_retest_staged_m30_converging_volume_shrink",
        "oversold_rebound",
        "长期空头后 MA10/20 分阶段上穿，MA10 回踩且向 MA30 收敛，量能缩量",
    ),
    DiscoveryRule(
        "ma10_ma30_converging_after_staged_cross_volume_shrink",
        "oversold_rebound",
        "长期空头后 MA10 已先上穿 MA20、向 MA30 收敛，量能梯形缩量",
    ),
    DiscoveryRule(
        "ma10_ma20_contact_pre_cross_positive_volume_expand",
        "oversold_rebound",
        "长期空头后 MA10 贴合但尚未上穿 MA20，阳线且当日放量",
    ),
    DiscoveryRule(
        "m5_m10_joint_attack_before_ma20_cross_last_volume_expand",
        "oversold_rebound",
        "长期空头后 MA5 转升、MA10 向 MA20 收敛，D 日成交量放大",
    ),
    DiscoveryRule(
        "ma10_ma30_retest_after_actual_cross_two_leg_volume",
        "oversold_rebound",
        "MA10 曾上穿 MA30 后深回撤至 MA30，前段缩量后段放量",
    ),
)


EXPLICIT_CASE_TREND_RULES = (
    DiscoveryRule(
        OVERSOLD_TO_TREND_PREPARATION_RULE_KEY,
        "trend_pullback",
        "长期空头后 MA10 在 MA20 下方贴合且间距收窄，D 日阳线；作为超跌转趋势的早期准备，不要求 MA5 或 MA60",
    ),
    DiscoveryRule(
        OVERSOLD_TO_TREND_RULE_KEY,
        "trend_pullback",
        "长期空头后 MA10 在 7 日内依次上穿 MA20、MA30，回撤后 MA20/30 紧贴且 MA10/20 向上；不要求 MA5 或 MA60",
    ),
    DiscoveryRule(
        OVERSOLD_TO_TREND_LOW_SUPPORT_RULE_KEY,
        "trend_pullback",
        "超跌转趋势双上穿结构，且 D 日低点在 MA10/MA20 获实际支撑、收盘守住",
    ),
    DiscoveryRule(
        OVERSOLD_TO_TREND_CLOSE_ANCHORED_RULE_KEY,
        "trend_pullback",
        "超跌转趋势双上穿结构，D 日收盘锚定 MA20 附近（未向上偏离、未深跌破）",
    ),
    DiscoveryRule(
        OVERSOLD_TO_TREND_TURNOVER_CAP_RULE_KEY,
        "trend_pullback",
        "超跌转趋势双上穿结构，近 5 日平均换手率 < 8%（排除高换手派发）",
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


def _volume_sibling_rules(
    core_rules: Sequence[DiscoveryRule],
) -> tuple[DiscoveryRule, ...]:
    siblings: list[DiscoveryRule] = []
    for core in core_rules:
        for shape, label in (
            ("staircase_shrink", "缩量"),
            ("staircase_expand", "放量"),
        ):
            siblings.append(
                DiscoveryRule(
                    f"{core.key}_volume_{shape.removeprefix('staircase_')}",
                    core.setup_type,
                    f"{core.description} + 梯形{label}",
                    core_rule_key=core.key,
                    volume_shape=shape,
                )
            )
    return tuple(siblings)


DISCOVERY_RULES: dict[str, tuple[DiscoveryRule, ...]] = {
    "oversold_rebound": (
        *OVERSOLD_CORE_RULES,
        *_volume_sibling_rules(OVERSOLD_CORE_RULES),
        *OVERSOLD_LOW_SUPPORT_RULES,
        *_volume_sibling_rules(OVERSOLD_LOW_SUPPORT_RULES),
        *OVERSOLD_V3_RULES,
        *EXPLICIT_CASE_OVERSOLD_RULES,
    ),
    "trend_pullback": (
        DiscoveryRule(
            "ma5_low_touch_down",
            "trend_pullback",
            "稳定多头且 MA5 在 MA10 上方，D 日低点回踩 MA5，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma5_low_touch_small_positive",
            "trend_pullback",
            "稳定多头且 MA5 在 MA10 上方，D 日低点回踩 MA5，D 日小阳",
        ),
        DiscoveryRule(
            "ma5_close_near_down",
            "trend_pullback",
            "稳定多头且 MA5 在 MA10 上方，收盘贴近 MA5 但低点未触及，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma5_close_near_small_positive",
            "trend_pullback",
            "稳定多头且 MA5 在 MA10 上方，收盘贴近 MA5 但低点未触及，D 日小阳",
        ),
        DiscoveryRule(
            "ma5_midpoint_near_down",
            "trend_pullback",
            "稳定多头且 MA5 在 MA10 上方，日内中心价贴近 MA5 但低点未触及，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma5_midpoint_near_small_positive",
            "trend_pullback",
            "稳定多头且 MA5 在 MA10 上方，日内中心价贴近 MA5 但低点未触及，D 日小阳",
        ),
        DiscoveryRule(
            "ma10_low_touch_down",
            "trend_pullback",
            "稳定多头但 MA5 不规律，D 日低点回踩 MA10，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma10_low_touch_small_positive",
            "trend_pullback",
            "稳定多头但 MA5 不规律，D 日低点回踩 MA10，D 日小阳",
        ),
        DiscoveryRule(
            "ma10_close_near_down",
            "trend_pullback",
            "稳定多头但 MA5 不规律，收盘贴近 MA10 但低点未触及，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma10_close_near_small_positive",
            "trend_pullback",
            "稳定多头但 MA5 不规律，收盘贴近 MA10 但低点未触及，D 日小阳",
        ),
        DiscoveryRule(
            "ma10_midpoint_near_down",
            "trend_pullback",
            "稳定多头但 MA5 不规律，日内中心价贴近 MA10 但低点未触及，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma10_midpoint_near_small_positive",
            "trend_pullback",
            "稳定多头但 MA5 不规律，日内中心价贴近 MA10 但低点未触及，D 日小阳",
        ),
        DiscoveryRule(
            "ma5_low_touch_gentle_stable",
            "trend_pullback",
            "MA5 低点回踩，稳定多头且均线温和上行",
        ),
        DiscoveryRule(
            "ma5_low_touch_steep_stable",
            "trend_pullback",
            "MA5 低点回踩，稳定多头且均线陡峭上行",
        ),
        DiscoveryRule(
            "ma10_low_touch_gentle_stable",
            "trend_pullback",
            "MA10 低点回踩，稳定多头且均线温和上行",
        ),
        DiscoveryRule(
            "ma10_low_touch_steep_stable",
            "trend_pullback",
            "MA10 低点回踩，稳定多头且均线陡峭上行",
        ),
        DiscoveryRule(
            "ma10_low_touch_regular_ma5_down",
            "trend_pullback",
            "MA5 位于 MA10 上方但实际低点回踩 MA10，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma5_low_touch_broad_down",
            "trend_pullback",
            "稳定多头的 MA5 宽回踩，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "ma5_low_touch_after_trend_rebuild",
            "trend_pullback",
            "重新恢复多头排列后的早期阶段，D 日低点宽回踩 MA5",
        ),
        DiscoveryRule(
            "ma5_low_touch_any_candle",
            "trend_pullback",
            "多头排列且均线向上时，D 日最低价回踩 MA5，不按当日涨跌幅排除",
        ),
        DiscoveryRule(
            "ma5_low_touch_early_trend_any_candle",
            "trend_pullback",
            "多头排列形成后第 3 至第 20 日，D 日最低价回踩 MA5，不按当日涨跌幅排除",
        ),
        DiscoveryRule(
            "ma10_low_touch_early_trend_regular_ma5_down",
            "trend_pullback",
            "多头排列形成后第 3 至第 20 日，MA5 在 MA10 上方但实际低点回踩 MA10，D 日弱势或下跌",
        ),
        DiscoveryRule(
            "v4_trend_authentic_pullback",
            "trend_pullback",
            "v4：多头排列中低点回踩 MA5/MA10，趋势不过伸（段内相对距离超额 < 2），"
            "且非首阴追高（安静 K 线、或收盘跌回 MA5 下方、或昨日已下跌）",
        ),
        DiscoveryRule(
            "v4_trend_quiet_pullback",
            "trend_pullback",
            "v4：多头排列中安静 K 线（振幅 ≤ 5%）低点回踩 MA5/MA10，趋势不过伸",
        ),
        *EXPLICIT_CASE_TREND_RULES,
    ),
}


@dataclass(frozen=True)
class _CandidateSnapshot:
    symbol: str
    trade_date: date
    position: int
    history: Sequence[Mapping[str, object]]
    dates: tuple[date, ...]
    features: Mapping[str, object]
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


def build_extended_daily_features(
    history: Sequence[Mapping[str, object]],
    *,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Return finite D-and-earlier extensions to the frozen daily feature set."""

    visible = _visible_history(history, as_of_date=as_of_date)
    base = build_daily_features(visible)
    closes = [_required_positive_number(row.get("close_price"), "close_price") for row in visible]
    lows = [_required_positive_number(row.get("low_price"), "low_price") for row in visible]
    volumes = [_number_or_none(row.get("volume")) for row in visible]
    ma_series = {
        window: _moving_average_series(closes, window)
        for window in (5, 10, 20, 30, 60)
    }
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
    distance_10_20 = _signed_ma_distance_pct(ma10, ma20, close_price)
    distance_10_30 = _signed_ma_distance_pct(ma10, ma30, close_price)
    distance_20_30 = _signed_ma_distance_pct(ma20, ma30, close_price)
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
    turnover_rates = [_number_or_none(row.get("turnover_rate")) for row in visible]
    turnover_rate = turnover_rates[-1] if turnover_rates else None
    prior_turnover_rates = [
        value for value in turnover_rates[-6:-1] if value is not None
    ]
    turnover_rate_5d_mean = (
        _round_pct(fmean(prior_turnover_rates))
        if len(prior_turnover_rates) >= 3
        else None
    )
    close_off_low_pct = (
        _round_pct((close_price - low_price) / low_price * 100)
        if close_price is not None and low_price > 0
        else None
    )
    support_close_reaction = bool(
        close_off_low_pct is not None
        and close_off_low_pct >= SUPPORT_CLOSE_REACTION_MIN_PCT
    )
    transition_close_anchored = bool(
        close_to_ma20 is not None
        and TRANSITION_CLOSE_ANCHOR_MIN_PCT
        <= close_to_ma20
        <= TRANSITION_CLOSE_ANCHOR_MAX_PCT
    )
    turnover_rate_low = bool(
        turnover_rate is not None and turnover_rate < TURNOVER_RATE_LOW_MAX_PCT
    )
    turnover_rate_gated = bool(
        turnover_rate is not None and turnover_rate < TURNOVER_RATE_GATE_MAX_PCT
    )
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
    transition_turnover_5d_capped = bool(
        turnover_rate_5d_mean is None
        or turnover_rate_5d_mean < TRANSITION_TURNOVER_5D_MAX_PCT
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
    ma5_slope_2d = _series_slope_pct(ma_series[5], lookback=2)
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
    joint_m5_m10_attack = bool(
        ma5_slope_2d is not None
        and ma5_slope_2d > 0
        and ma10_slope_improvement_2d is not None
        and ma10_slope_improvement_2d > 0
        and ma10 is not None
        and ma20 is not None
        and ma10 < ma20
        and ma10_ma20_gap_narrowing_3d is not None
        and ma10_ma20_gap_narrowing_3d >= 0.5
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

    # --- v4 root factors: candle quietness and trend overextension ---
    prev_close_price = closes[-2] if len(closes) >= 2 else None
    candle_range_pct = None
    if prev_close_price is not None and prev_close_price > 0:
        candle_range_pct = _round_pct(
            (high_price - low_price) / prev_close_price * 100
        )
    candle_quiet = bool(
        candle_range_pct is not None
        and candle_range_pct <= TREND_CANDLE_QUIET_RANGE_MAX_PCT
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
        "ma10_ma20_signed_distance_pct": distance_10_20,
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
        "ma10_dual_cross_within_15d": ma10_dual_cross_within_15d,
        "ma10_dual_cross_within_7d": ma10_dual_cross_within_7d,
        "ma10_above_ma20_and_ma30": ma10_above_ma20_and_ma30,
        "ma10_ma20_near_or_recent_cross": _near_or_recent_cross(distance_10_20),
        "ma10_ma20_contact": _ma_contact(distance_10_20),
        "ma10_below_ma20": bool(
            ma10 is not None and ma20 is not None and ma10 < ma20
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
        "oversold_discovery_eligible": bool(
            ma10 is not None
            and ma20 is not None
            and ma30 is not None
            and current_spread is not None
            and int(base.get("prior_bear_alignment_days") or 0) >= 5
            and current_spread <= OVERSOLD_CLUSTER_MAX_PCT
            and daily_return is not None
            and -5.0 <= daily_return <= 3.0
            and prior_spread is not None
            and current_spread <= prior_spread
        ),
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
        "ma5_slope_2d_pct": ma5_slope_2d,
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
        "ma10_was_above_ma30_within_15d": _was_ma_above_within(
            closes,
            fast_window=10,
            slow_window=30,
            lookback=PROCESS_CROSS_LOOKBACK,
        ),
        "m5_m10_joint_attack_ready": joint_m5_m10_attack,
        "last_volume_change_pct": last_volume_change_pct,
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
        "low_to_ma30_pct": low_to_ma30,
        "close_to_ma20_pct": close_to_ma20,
        "close_to_ma30_pct": close_to_ma30,
        "ma20_low_touch": ma20_low_touch,
        "ma30_low_touch": ma30_low_touch,
        "oversold_low_support": bool(
            ma10_low_touch or ma20_low_touch or ma30_low_touch
        ),
        # 超跌低吸位置语境：M10 必须在「准备上穿 M30」(M10<M30) 或「穿完回贴 M30」(贴近)。
        # 排除 M10 已远穿 M30（上穿过程结束）的横盘票 —— 它们不是"准备上穿处的 M10 回踩"。
        "m10_below_or_contact_ma30": bool(
            ma10 is not None
            and ma30 is not None
            and (ma10 < ma30 or abs((ma10 - ma30) / ma30 * 100) < MA_CONTACT_DISTANCE_PCT)
        ),
        "transition_low_support": bool(ma10_low_touch or ma20_low_touch),
        "close_off_low_pct": close_off_low_pct,
        "support_close_reaction": support_close_reaction,
        "transition_close_anchored": transition_close_anchored,
        "turnover_rate_low": turnover_rate_low,
        "turnover_rate_gated": turnover_rate_gated,
        "capitulation_rebound_tight": capitulation_rebound_tight,
        "capitulation_rebound_broad": capitulation_rebound_broad,
        "transition_turnover_5d_capped": transition_turnover_5d_capped,
        "turnover_rate_pct": turnover_rate,
        "turnover_rate_5d_mean_pct": turnover_rate_5d_mean,
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
        "trend_overextended": trend_overextended,
        "trend_first_crack_chase": trend_first_crack_chase,
    }
    return features


def score_extended_factor(
    features: Mapping[str, object],
    setup_type: str,
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
                "m5_m10_joint_attack_ready",
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
        source_process = _matches_explicit_process_geometry(features, setup_type)
        base = _round_pct(
            20.0 * sum((regime, transition, convergence, pullback, source_process))
        )
        volume = bool(
            source_process
            and _matches_explicit_process_with_volume(features, setup_type)
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
        source_process = _matches_explicit_process_geometry(features, setup_type)
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
) -> tuple[str, ...]:
    """Return declared discovery rules matched by one causal feature snapshot."""

    rules = DISCOVERY_RULES.get(setup_type)
    if rules is None:
        raise DailyFactorInputError(f"unsupported discovery setup type: {setup_type}")
    return tuple(rule.key for rule in rules if _rule_matches(rule, features))


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
    for observation in observations:
        setup_type = str(observation.get("setup_type") or "")
        rule_key = str(observation.get("rule_key") or "")
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
                "core_rule_key": rule.core_rule_key,
                "volume_shape": rule.volume_shape,
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
            "volume_incremental_deltas": _volume_incremental_deltas(rendered_rules),
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
                    "core_rule_key": rule.core_rule_key,
                    "volume_shape": rule.volume_shape,
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
        "- 基线案例审计、固定分数和基础卖点证据仍见 v4 综合报告；本报告只扩展未覆盖的具体时点假设。",
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
    deltas = family.get("volume_incremental_deltas")
    if isinstance(deltas, Sequence) and deltas:
        lines.extend(["", "### 成交量附加因子", ""])
        lines.append("| 量能规则 | 量能形态 | 核心规则 | 区间 | D+1 均值差 | 胜率差 |")
        lines.append("| --- | --- | --- | --- | ---: | ---: |")
        for row in deltas:
            if not isinstance(row, Mapping):
                continue
            for segment, values in row.get("segments", {}).items():
                if isinstance(values, Mapping):
                    lines.append(
                        "| {rule} | {shape} | {core} | {segment} | {mean} | {win} |".format(
                            rule=row.get("rule_key", "-"),
                            shape=row.get("volume_shape", "-"),
                            core=row.get("core_rule_key", "-"),
                            segment=segment,
                            mean=_number_text(values.get("d1_mean_delta_pct")),
                            win=_number_text(values.get("win_rate_delta_pct")),
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
    ):
        for setup_type, rules in DISCOVERY_RULES.items():
            for rule in rules:
                if _rule_matches(rule, snapshot.features):
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
                    "m5_m10_joint_attack_ready",
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
    calendar_set = set(calendar)
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
            scores = score_extended_factor(features, case.expected_setup_type)
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
            if rule is None or not _rule_matches(rule, snapshot.features):
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
) -> Iterable[_CandidateSnapshot]:
    calendar_tuple = _strict_calendar(calendar)
    calendar_set = set(calendar_tuple)
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
        for position in _broad_candidate_positions(
            history,
            candidate_dates=calendar_set,
        ):
            trade_date = dates[position]
            if trade_date not in calendar_set:
                continue
            if eligible_pairs and (symbol, trade_date) not in eligible_pairs:
                continue
            features = build_extended_daily_features(history[max(0, position - 79) : position + 1])
            if require_rule_match and not _matches_any_rule(features):
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
                d1_close_return_pct=d1_close_return_pct,
                d1_label_status=d1_label_status,
                d1_initial_short_trend_formed=d1_initial_short_trend_formed,
            )


def _broad_candidate_positions(
    history: Sequence[Mapping[str, object]],
    *,
    candidate_dates: set[date] | None = None,
) -> tuple[int, ...]:
    """Prescreen requested signal days while retaining earlier bars for MA history."""

    closes = [_required_positive_number(row.get("close_price"), "close_price") for row in history]
    opens = [_required_positive_number(row.get("open_price"), "open_price") for row in history]
    highs = [_required_positive_number(row.get("high_price"), "high_price") for row in history]
    lows = [_required_positive_number(row.get("low_price"), "low_price") for row in history]
    ma_series = {
        window: _moving_average_series(closes, window)
        for window in (5, 10, 20, 30)
    }
    bear = [
        _is_bear_alignment(
            ma_series[10][index],
            ma_series[20][index],
            ma_series[30][index],
        )
        for index in range(len(history))
    ]
    result: list[int] = []
    for index, close_price in enumerate(closes):
        if candidate_dates is not None and _required_date(
            history[index].get("trade_date")
        ) not in candidate_dates:
            continue
        ma5 = ma_series[5][index]
        ma10 = ma_series[10][index]
        ma20 = ma_series[20][index]
        ma30 = ma_series[30][index]
        daily_return = _pct_change(close_price, opens[index])
        prior_bear_days = _prior_bear_duration(bear, index)
        transition_ma20_ma30_distance = _signed_ma_distance_pct(
            ma20,
            ma30,
            close_price,
        )
        oversold = False
        oversold_joint_attack = False
        if ma10 is not None and ma20 is not None and ma30 is not None:
            spread = _cluster_spread_pct(ma10, ma20, ma30, close_price)
            oversold = bool(
                prior_bear_days >= 5
                and spread is not None
                and spread <= OVERSOLD_CLUSTER_MAX_PCT
                and -5.0 <= daily_return <= 3.0
            )
            oversold_process = bool(
                prior_bear_days >= 5
                and OVERSOLD_PROCESS_DAILY_RETURN_MIN_PCT <= daily_return <= 3.0
                and (
                    _ma_contact(_signed_ma_distance_pct(ma10, ma30, close_price))
                    or _ma_contact(_signed_ma_distance_pct(ma20, ma30, close_price))
                )
            )
            if index >= 4:
                ma5_two_days_ago = ma_series[5][index - 2]
                ma10_two_days_ago = ma_series[10][index - 2]
                ma10_four_days_ago = ma_series[10][index - 4]
                ma20_three_days_ago = ma_series[20][index - 3]
                ma10_three_days_ago = ma_series[10][index - 3]
                if all(
                    value is not None
                    for value in (
                        ma5,
                        ma5_two_days_ago,
                        ma10_two_days_ago,
                        ma10_four_days_ago,
                        ma10_three_days_ago,
                        ma20_three_days_ago,
                    )
                ):
                    ma5_slope = _pct_change(ma5, ma5_two_days_ago)
                    ma10_slope = _pct_change(ma10, ma10_two_days_ago)
                    prior_ma10_slope = _pct_change(
                        ma10_two_days_ago,
                        ma10_four_days_ago,
                    )
                    current_gap = _signed_ma_distance_pct(ma10, ma20, close_price)
                    prior_gap = _signed_ma_distance_pct(
                        ma10_three_days_ago,
                        ma20_three_days_ago,
                        closes[index - 3],
                    )
                    gap_narrowing = _difference_or_none(current_gap, prior_gap)
                    oversold_joint_attack = bool(
                        prior_bear_days >= 5
                        and OVERSOLD_PROCESS_DAILY_RETURN_MIN_PCT
                        <= daily_return
                        <= 3.0
                        and ma5_slope > 0
                        and ma10_slope > prior_ma10_slope
                        and ma10 < ma20
                        and gap_narrowing is not None
                        and gap_narrowing >= 0.5
                    )
        else:
            oversold_process = False
        trend = False
        trend_geometry = False
        trend_transition_preparation = False
        trend_transition = False
        if index >= 3:
            trend_transition_preparation = _is_pre_cross_trend_transition_preparation(
                prior_bear_alignment_days=prior_bear_days,
                ma10=ma10,
                ma20=ma20,
                close_price=close_price,
                daily_return_pct=daily_return,
                prior_ma10=ma_series[10][index - 3],
                prior_ma20=ma_series[20][index - 3],
                prior_close_price=closes[index - 3],
            )
        if (
            ma10 is not None
            and ma20 is not None
            and ma30 is not None
            and index >= 5
            and prior_bear_days >= LONG_BEAR_ALIGNMENT_MIN_SESSIONS
            and ma10 > ma20
            and ma10 > ma30
            and transition_ma20_ma30_distance is not None
            and abs(transition_ma20_ma30_distance)
            <= TRANSITION_MA20_MA30_CONTACT_PCT
            and 0 < daily_return <= 3.0
        ):
            ma10_prior = ma_series[10][index - 5]
            ma20_prior = ma_series[20][index - 5]
            ma10_ma20_slopes_up = bool(
                ma10_prior is not None
                and ma20_prior is not None
                and _pct_change(ma10, ma10_prior) > 0
                and _pct_change(ma20, ma20_prior) > 0
            )
            if ma10_ma20_slopes_up:
                visible_closes = closes[: index + 1]
                recent_pullback = _recent_pullback_from_prior_high_pct(
                    visible_closes,
                    lookback=OVERSOLD_PROCESS_PULLBACK_LOOKBACK,
                )
                if (
                    recent_pullback is not None
                    and recent_pullback <= OVERSOLD_PROCESS_PULLBACK_MIN_PCT
                ):
                    cross_10_20_age = _recent_cross_age(
                        visible_closes,
                        fast_window=10,
                        slow_window=20,
                        lookback=TRANSITION_CROSS_LOOKBACK,
                    )
                    cross_10_30_age = _recent_cross_age(
                        visible_closes,
                        fast_window=10,
                        slow_window=30,
                        lookback=TRANSITION_CROSS_LOOKBACK,
                    )
                    trend_transition = bool(
                        cross_10_20_age is not None
                        and cross_10_30_age is not None
                        and cross_10_20_age >= cross_10_30_age
                    )
        if (
            ma5 is not None
            and ma10 is not None
            and ma20 is not None
            and ma30 is not None
            and ma10 > ma20 > ma30
            and index >= 5
        ):
            slopes = tuple(
                _pct_change(ma_series[window][index], ma_series[window][index - 5])
                for window in (10, 20, 30)
                if ma_series[window][index] is not None
                and ma_series[window][index - 5] is not None
            )
            if len(slopes) == 3 and all(value > 0 for value in slopes):
                ma5_distance = _pct_change(lows[index], ma5)
                ma10_distance = _pct_change(lows[index], ma10)
                midpoint_price = (highs[index] + lows[index]) / 2
                midpoint_ma5_distance = _pct_change(midpoint_price, ma5)
                midpoint_ma10_distance = _pct_change(midpoint_price, ma10)
                close_ma5_distance = _pct_change(close_price, ma5)
                close_ma10_distance = _pct_change(close_price, ma10)
                support_seen = bool(
                    _support_low_touch(ma5_distance, close_ma5_distance)
                    or _support_low_touch(ma10_distance, close_ma10_distance)
                    or _support_low_touch_broad(ma5_distance, close_ma5_distance)
                    or _support_midpoint_near(midpoint_ma5_distance)
                    or _support_midpoint_near(midpoint_ma10_distance)
                    or _support_close_near(close_ma5_distance)
                    or _support_close_near(close_ma10_distance)
                )
                trend = bool(daily_return <= 3.0 and support_seen)
                trend_geometry = bool(
                    ma5 > ma10
                    and _support_low_touch(ma5_distance, close_ma5_distance)
                )
        if (
            oversold
            or oversold_process
            or oversold_joint_attack
            or trend
            or trend_geometry
            or trend_transition_preparation
            or trend_transition
        ):
            result.append(index)
    return tuple(result)


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


def process_rule_predicates(
    rule_key: str,
    features: Mapping[str, object],
) -> dict[str, bool]:
    """Return every source-contract predicate for an explicit case rule.

    Generic discovery rules deliberately retain their existing broad matching
    behavior. This function is only for the narrow source-derived branches
    required by the personal-case gate, so a case report can show exactly why
    a claimed chart setup did or did not match.
    """

    predicates: dict[str, dict[str, bool]] = {
        "ma10_low_retest_staged_m30_converging_volume_shrink": {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "oversold_process_eligible": bool(
                features.get("oversold_process_eligible")
            ),
            "staged_m10_first": bool(features.get("staged_m10_first")),
            "ma10_low_touch": bool(features.get("ma10_low_touch")),
            "ma10_ma30_gap_converging": bool(
                features.get("ma10_ma30_gap_converging")
            ),
            "volume_shape_staircase_shrink": (
                features.get("volume_shape") == "staircase_shrink"
            ),
        },
        "ma10_ma30_converging_after_staged_cross_volume_shrink": {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "oversold_process_eligible": bool(
                features.get("oversold_process_eligible")
            ),
            "staged_m10_first": bool(features.get("staged_m10_first")),
            "ma10_ma30_gap_converging": bool(
                features.get("ma10_ma30_gap_converging")
            ),
            "volume_shape_staircase_shrink": (
                features.get("volume_shape") == "staircase_shrink"
            ),
        },
        "ma10_ma20_contact_pre_cross_positive_volume_expand": {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "ma10_below_ma20": bool(features.get("ma10_below_ma20")),
            "ma10_ma20_contact": bool(features.get("ma10_ma20_contact")),
            "ma10_ma20_gap_narrowing": bool(
                features.get("ma10_ma20_gap_narrowing")
            ),
            "positive_candle": bool(features.get("positive_candle")),
            "last_volume_expanded": bool(features.get("last_volume_expanded")),
        },
        OVERSOLD_TO_TREND_PREPARATION_RULE_KEY: {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "ma10_below_ma20": bool(features.get("ma10_below_ma20")),
            "ma10_ma20_contact": bool(features.get("ma10_ma20_contact")),
            "ma10_ma20_gap_narrowing": bool(
                features.get("ma10_ma20_gap_narrowing")
            ),
            "positive_candle": bool(features.get("positive_candle")),
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
        OVERSOLD_TO_TREND_LOW_SUPPORT_RULE_KEY: {
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
            "transition_low_support": bool(
                features.get("transition_low_support")
            ),
        },
        OVERSOLD_TO_TREND_CLOSE_ANCHORED_RULE_KEY: {
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
            "transition_close_anchored": bool(
                features.get("transition_close_anchored")
            ),
        },
        OVERSOLD_TO_TREND_TURNOVER_CAP_RULE_KEY: {
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
            "transition_turnover_5d_capped": bool(
                features.get("transition_turnover_5d_capped")
            ),
        },
        "m5_m10_joint_attack_before_ma20_cross_last_volume_expand": {
            "long_bear_alignment": bool(features.get("long_bear_alignment")),
            "oversold_process_eligible": bool(
                features.get("oversold_process_eligible")
            ),
            "m5_m10_joint_attack_ready": bool(
                features.get("m5_m10_joint_attack_ready")
            ),
            "last_volume_expanded": bool(features.get("last_volume_expanded")),
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
) -> bool:
    """Match the non-volume geometry of at least one declared source process."""

    return any(
        all(
            passed
            for name, passed in process_rule_predicates(rule.key, features).items()
            if not name.startswith(("volume_", "last_volume_"))
        )
        for rule in DISCOVERY_RULES[setup_type]
        if rule.key in EXPLICIT_CASE_PROCESS_RULE_KEYS
    )


def _matches_explicit_process_with_volume(
    features: Mapping[str, object],
    setup_type: str,
) -> bool:
    """Match every predicate, including volume, of one source process."""

    return any(
        all(process_rule_predicates(rule.key, features).values())
        for rule in DISCOVERY_RULES[setup_type]
        if rule.key in EXPLICIT_CASE_PROCESS_RULE_KEYS
    )


def _rule_matches(rule: DiscoveryRule, features: Mapping[str, object]) -> bool:
    if rule.key in EXPLICIT_CASE_PROCESS_RULE_KEYS:
        return all(process_rule_predicates(rule.key, features).values())
    if rule.setup_type == "oversold_rebound":
        long_bear = bool(features.get("long_bear_alignment"))
        process_basic = {
            "ma10_low_retest_during_staged_cross": bool(
                features.get("oversold_process_eligible")
                and features.get("staged_m10_first")
                and features.get("ma10_low_touch")
            ),
            "m5_m10_joint_attack_before_ma20_cross": bool(
                features.get("oversold_process_eligible")
                and features.get("m5_m10_joint_attack_ready")
            ),
            "m10_m30_contact_after_m10_cross_aggressive_pullback": bool(
                features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma10_ma30_contact")
                and features.get("aggressive_pullback")
            ),
            "ma10_low_retest_after_long_bear_staged_cross": bool(
                long_bear
                and features.get("oversold_process_eligible")
                and features.get("staged_m10_first")
                and features.get("ma10_low_touch")
            ),
            "m5_m10_joint_attack_after_long_bear": bool(
                long_bear
                and features.get("oversold_process_eligible")
                and features.get("m5_m10_joint_attack_ready")
            ),
            "m10_m30_contact_after_long_bear_aggressive_pullback": bool(
                long_bear
                and features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma10_ma30_contact")
                and features.get("aggressive_pullback")
            ),
            "m10_m30_contact_after_m10_cross_low_support": bool(
                features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma10_ma30_contact")
                and features.get("oversold_low_support")
                and features.get("m10_below_or_contact_ma30")
                and features.get("low_to_ma10_pct") is not None
                and features.get("low_to_ma10_pct") <= 1.0
                and features.get("support_close_reaction")
            ),
            "m10_m30_contact_after_long_bear_low_support": bool(
                long_bear
                and features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma10_ma30_contact")
                and features.get("oversold_low_support")
                and features.get("m10_below_or_contact_ma30")
                and features.get("low_to_ma10_pct") is not None
                and features.get("low_to_ma10_pct") <= 1.0
                and features.get("support_close_reaction")
            ),
            "ma30_low_retest_after_m10_cross": bool(
                features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma30_low_touch")
                and features.get("support_close_reaction")
            ),
            "ma30_low_retest_after_long_bear_m10_cross": bool(
                long_bear
                and features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma30_low_touch")
                and features.get("support_close_reaction")
            ),
            "v3_oversold_staged_low_support_turnover_low": bool(
                features.get("oversold_process_eligible")
                and features.get("oversold_low_support")
                and features.get("m10_below_or_contact_ma30")
                and features.get("low_to_ma10_pct") is not None
                and features.get("low_to_ma10_pct") <= 1.0
                and features.get("turnover_rate_low")
                and (
                    features.get("staged_m10_first")
                    or features.get("m10_dual_cross_before_m20_m30")
                    or features.get("m5_m10_joint_attack_ready")
                    or features.get("ma10_crossed_ma30_within_15d")
                )
                and (
                    not features.get("aggressive_pullback")
                    or features.get("capitulation_rebound_broad")
                )
            ),
            "v3_oversold_staged_low_support_turnover_gate": bool(
                features.get("oversold_process_eligible")
                and features.get("oversold_low_support")
                and features.get("m10_below_or_contact_ma30")
                and features.get("low_to_ma10_pct") is not None
                and features.get("low_to_ma10_pct") <= 1.0
                and features.get("turnover_rate_gated")
                and (
                    features.get("staged_m10_first")
                    or features.get("m10_dual_cross_before_m20_m30")
                    or features.get("m5_m10_joint_attack_ready")
                    or features.get("ma10_crossed_ma30_within_15d")
                )
                and (
                    not features.get("aggressive_pullback")
                    or features.get("capitulation_rebound_broad")
                )
            ),
            "v3_oversold_capitulation_rebound_tight": bool(
                features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma10_ma30_contact")
                and features.get("capitulation_rebound_tight")
            ),
            "v3_oversold_capitulation_rebound_broad": bool(
                features.get("oversold_process_eligible")
                and features.get("ma10_crossed_ma20_within_15d")
                and features.get("ma10_ma30_contact")
                and features.get("capitulation_rebound_broad")
            ),
        }
        if rule.key in process_basic:
            return process_basic[rule.key]
        if rule.core_rule_key in process_basic:
            return bool(
                process_basic[rule.core_rule_key]
                and features.get("volume_shape") == rule.volume_shape
            )
        if not bool(features.get("oversold_discovery_eligible")):
            return False
        price_state = str(features.get("price_state") or "")
        down = price_state == "weak_or_down"
        basic = {
            "m10_m20_near_or_crossed_down": bool(
                down and features.get("ma10_ma20_near_or_recent_cross")
            ),
            "m10_m30_near_or_crossed_down": bool(
                down and features.get("ma10_ma30_near_or_recent_cross")
            ),
            "m20_m30_near_or_crossed_down": bool(
                down and features.get("ma20_ma30_near_or_recent_cross")
            ),
            "staged_m10_first_down": bool(down and features.get("staged_m10_first")),
            "m10_dual_cross_before_m20_m30_down": bool(
                down and features.get("m10_dual_cross_before_m20_m30")
            ),
        }
        if rule.key in basic:
            return basic[rule.key]
        if rule.core_rule_key is not None:
            return bool(
                basic.get(rule.core_rule_key)
                and features.get("volume_shape") == rule.volume_shape
            )
        return False

    if rule.setup_type == "trend_pullback":
        if rule.key == "v4_trend_authentic_pullback":
            return bool(
                features.get("trend_discovery_eligible")
                and (
                    features.get("ma5_low_touch")
                    or features.get("ma10_low_touch")
                )
                and not features.get("trend_overextended")
                and not features.get("trend_first_crack_chase")
            )
        if rule.key == "v4_trend_quiet_pullback":
            return bool(
                features.get("trend_discovery_eligible")
                and features.get("candle_quiet")
                and (
                    features.get("ma5_low_touch")
                    or features.get("ma10_low_touch")
                )
                and not features.get("trend_overextended")
            )
        if rule.key == "ma5_low_touch_any_candle":
            return bool(
                features.get("trend_bull_alignment")
                and features.get("trend_all_slopes_up")
                and features.get("ma5_regular")
                and features.get("ma5_low_touch")
            )
        if rule.key == "ma5_low_touch_early_trend_any_candle":
            return bool(
                features.get("early_trend_alignment")
                and features.get("trend_all_slopes_up")
                and features.get("ma5_regular")
                and features.get("ma5_low_touch")
            )
        if not bool(features.get("trend_discovery_eligible")):
            return False
        price_state = str(features.get("price_state") or "")
        down = price_state == "weak_or_down"
        small_positive = price_state == "small_positive"
        ma5_regular = bool(features.get("ma5_regular"))
        ma5_low_touch = bool(features.get("ma5_low_touch"))
        ma10_low_touch = bool(features.get("ma10_low_touch"))
        ma5_midpoint_only = bool(features.get("ma5_midpoint_near")) and not ma5_low_touch
        ma10_midpoint_only = bool(features.get("ma10_midpoint_near")) and not ma10_low_touch
        ma5_close_only = bool(features.get("ma5_close_near")) and not ma5_low_touch
        ma10_close_only = bool(features.get("ma10_close_near")) and not ma10_low_touch
        stable = bool(features.get("trend_stable_bull"))
        profile = str(features.get("trend_slope_profile") or "")
        return {
            "ma5_low_touch_down": ma5_regular and ma5_low_touch and down,
            "ma5_low_touch_small_positive": ma5_regular
            and ma5_low_touch
            and small_positive,
            "ma5_close_near_down": ma5_regular and ma5_close_only and down,
            "ma5_close_near_small_positive": ma5_regular
            and ma5_close_only
            and small_positive,
            "ma5_midpoint_near_down": ma5_regular and ma5_midpoint_only and down,
            "ma5_midpoint_near_small_positive": ma5_regular
            and ma5_midpoint_only
            and small_positive,
            "ma10_low_touch_down": not ma5_regular and ma10_low_touch and down,
            "ma10_low_touch_small_positive": not ma5_regular
            and ma10_low_touch
            and small_positive,
            "ma10_close_near_down": not ma5_regular and ma10_close_only and down,
            "ma10_close_near_small_positive": not ma5_regular
            and ma10_close_only
            and small_positive,
            "ma10_midpoint_near_down": not ma5_regular and ma10_midpoint_only and down,
            "ma10_midpoint_near_small_positive": not ma5_regular
            and ma10_midpoint_only
            and small_positive,
            "ma5_low_touch_gentle_stable": ma5_regular
            and ma5_low_touch
            and stable
            and profile == "gentle",
            "ma5_low_touch_steep_stable": ma5_regular
            and ma5_low_touch
            and stable
            and profile == "steep",
            "ma10_low_touch_gentle_stable": not ma5_regular
            and ma10_low_touch
            and stable
            and profile == "gentle",
            "ma10_low_touch_steep_stable": not ma5_regular
            and ma10_low_touch
            and stable
            and profile == "steep",
            "ma10_low_touch_regular_ma5_down": ma5_regular
            and ma10_low_touch
            and stable
            and down,
            "ma5_low_touch_broad_down": ma5_regular
            and bool(features.get("ma5_low_touch_broad"))
            and stable
            and down,
            "ma5_low_touch_after_trend_rebuild": ma5_regular
            and bool(features.get("ma5_low_touch_broad"))
            and stable
            and bool(features.get("trend_rebuilt_recently")),
            "ma10_low_touch_early_trend_regular_ma5_down": ma5_regular
            and ma10_low_touch
            and down
            and bool(features.get("early_trend_alignment")),
        }.get(rule.key, False)
    return False


def _matches_any_rule(features: Mapping[str, object]) -> bool:
    return any(
        _rule_matches(rule, features)
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


def _volume_incremental_deltas(
    rules: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_key = {
        str(rule.get("key")): rule
        for rule in rules
        if isinstance(rule, Mapping)
    }
    rows: list[dict[str, object]] = []
    for rule in rules:
        if not isinstance(rule, Mapping):
            continue
        core_key = rule.get("core_rule_key")
        core = by_key.get(str(core_key)) if core_key else None
        if not isinstance(core, Mapping):
            continue
        deltas: dict[str, dict[str, float | None]] = {}
        rule_segments = rule.get("segments")
        core_segments = core.get("segments")
        if not isinstance(rule_segments, Mapping) or not isinstance(core_segments, Mapping):
            continue
        for segment in ("overall", *SEGMENTS):
            if segment == "overall":
                rule_summary = rule.get("overall")
                core_summary = core.get("overall")
            else:
                rule_part = rule_segments.get(segment)
                core_part = core_segments.get(segment)
                rule_summary = rule_part.get("overall") if isinstance(rule_part, Mapping) else None
                core_summary = core_part.get("overall") if isinstance(core_part, Mapping) else None
            if not isinstance(rule_summary, Mapping) or not isinstance(core_summary, Mapping):
                continue
            deltas[segment] = {
                "d1_mean_delta_pct": _difference_or_none(
                    rule_summary.get("d1_mean_return_pct"),
                    core_summary.get("d1_mean_return_pct"),
                ),
                "win_rate_delta_pct": _difference_or_none(
                    rule_summary.get("win_rate_pct"),
                    core_summary.get("win_rate_pct"),
                ),
                "sample_count_delta": _difference_or_none(
                    rule_summary.get("sample_count"),
                    core_summary.get("sample_count"),
                ),
            }
        rows.append(
            {
                "rule_key": rule.get("key"),
                "core_rule_key": core_key,
                "volume_shape": rule.get("volume_shape"),
                "segments": deltas,
            }
        )
    return rows


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


def _is_bear_alignment(
    ma10: float | None,
    ma20: float | None,
    ma30: float | None,
) -> bool:
    return ma10 is not None and ma20 is not None and ma30 is not None and ma10 < ma20 < ma30


def _prior_bear_duration(bear: Sequence[bool], index: int) -> int:
    end = max(0, index - 4)
    start = max(0, end - 40)
    longest = 0
    current = 0
    for value in bear[start:end]:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _cluster_spread_pct(
    ma10: float,
    ma20: float,
    ma30: float,
    close_price: float,
) -> float | None:
    if close_price <= 0:
        return None
    return (abs(ma10 - ma20) + abs(ma20 - ma30)) / 2 / close_price * 100


def _feature_snapshot(features: Mapping[str, object]) -> dict[str, object]:
    keys = (
        "daily_return_pct",
        "ma10_ma20_signed_distance_pct",
        "ma10_ma30_signed_distance_pct",
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
        "ma10_dual_cross_within_15d",
        "ma10_dual_cross_within_7d",
        "ma10_above_ma20_and_ma30",
        "ma20_ma30_contact",
        "transition_ma20_ma30_tight_contact",
        "m10_dual_cross_before_m20_m30",
        "ma10_ma20_slopes_up",
        "post_cross_pullback",
        "ma5_slope_2d_pct",
        "ma10_slope_2d_pct",
        "ma10_slope_improvement_2d_pct",
        "ma10_ma20_gap_narrowing_3d_pct",
        "m5_m10_joint_attack_ready",
        "last_volume_change_pct",
        "volume_shape",
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
        "transition_low_support",
        "close_off_low_pct",
        "support_close_reaction",
        "transition_close_anchored",
        "aggressive_pullback",
        "turnover_rate_pct",
        "turnover_rate_5d_mean_pct",
        "trend_slope_profile",
        "trend_stable_bull",
        "trend_rebuilt_recently",
        "trend_transition_preparation_eligible",
        "trend_transition_eligible",
        "close_to_ma5_pct",
        "trend_dist_excess_pct",
        "candle_range_pct",
        "candle_quiet",
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
    oversold = families.get("oversold_rebound")
    if isinstance(oversold, Mapping):
        deltas = oversold.get("volume_incremental_deltas")
        holdout_deltas = [
            row.get("segments", {}).get("holdout", {}).get("d1_mean_delta_pct")
            for row in deltas
            if isinstance(row, Mapping)
            and isinstance(row.get("segments"), Mapping)
            and isinstance(row["segments"].get("holdout"), Mapping)
        ] if isinstance(deltas, Sequence) else []
        numeric = [float(value) for value in holdout_deltas if _number_or_none(value) is not None]
        answers.append(
            {
                "question": "成交量附加因子何时有增量",
                "status": "exploratory_observation"
                if numeric
                else "insufficient_data",
                "detail": (
                    "量能子规则（缩量或放量）相对核心规则的留出期 D+1 均值差最大为 {value}；"
                    "这仅是探索性增量观察，不能作为策略因子。"
                ).format(value=_number_text(max(numeric) if numeric else None)),
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
            "volume_incremental_deltas": [],
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
