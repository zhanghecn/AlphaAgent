"""Read-only comprehensive evidence for the daily low-suction research brief.

This module extends the frozen daily-factor study with case auditing, condition
tables, bad-observation evidence, and close-only exit probes.  It deliberately has
no database writes and no market-data provider calls.
"""

from __future__ import annotations

import heapq
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import fmean, median
from typing import Any

from .daily_factor_research import (
    PERSONAL_RESEARCH_CASES,
    DailyFactorInputError,
    build_daily_features,
    classify_daily_setup,
    d1_close_label_status,
    daily_factor_candidate_positions,
    daily_factor_history_window,
    explain_setup_eligibility,
    is_main_board_close_within_price_limit,
    is_main_board_limit_up_touched,
    score_factor_variants,
    split_market_calendar,
)


SETUP_TYPES = ("oversold_rebound", "trend_pullback")
SCORE_VARIANTS = ("base", "with_volume")
SCORE_BANDS = (
    (0.0, 39.999, "0-39"),
    (40.0, 59.999, "40-59"),
    (60.0, 79.999, "60-79"),
    (80.0, 100.0, "80-100"),
)
MAX_WORST_OBSERVATIONS = 50
MAX_WORST_ROWS_IN_MARKDOWN = 30
MAX_WORST_STOCKS_IN_MARKDOWN = 50
MAX_WORST_DAYS_IN_MARKDOWN = 50
NEAR_MA_DISTANCE_PCT = 0.5
SUPPORT_TOUCH_LOW_MIN_PCT = -4.0
SUPPORT_TOUCH_LOW_MAX_PCT = 1.5
SUPPORT_CLOSE_NEAR_PCT = 1.5
INTERACTION_DIMENSIONS: dict[str, tuple[tuple[str, ...], ...]] = {
    "oversold_rebound": (
        ("ma10_ma20_state", "price_state", "volume_shape"),
        ("ma10_ma30_state", "ma20_ma30_state"),
    ),
    "trend_pullback": (
        ("support_line", "support_touch"),
        ("ma5_regular", "support_line", "support_touch"),
    ),
}


@dataclass(frozen=True)
class PersonalResearchCase:
    """One source-document stock/date assertion that must be auditable."""

    name: str
    vt_symbol: str
    trade_date: date
    expected_setup_type: str
    narrative_start_date: date | None = None
    expected_launch_date: date | None = None
    source_anchor: str = "process_only"
    required_process_rule_keys: tuple[str, ...] = ()
    narrative_status: str = "complete"


@dataclass(frozen=True)
class CaseSourceMetadata:
    """Source-specific geometry and causal context for one declared case."""

    narrative_start_date: date | None
    expected_launch_date: date | None
    source_anchor: str
    required_process_rule_keys: tuple[str, ...]
    narrative_status: str = "complete"


@dataclass(frozen=True)
class ExitProbe:
    """A declared D-close entry and later D-close exit proxy."""

    key: str
    max_holding_sessions: int
    break_ma: str | None = None


PERSONAL_CASE_SOURCE_METADATA: dict[str, CaseSourceMetadata] = {
    "传智教育 MA10 回踩": CaseSourceMetadata(
        date(2026, 7, 15),
        date(2026, 7, 23),
        "ma10_low_touch",
        ("staged_ma10_support_before_ma30_convergence_shrink",),
    ),
    "传智教育 三线包裹": CaseSourceMetadata(
        date(2026, 7, 15),
        date(2026, 7, 27),
        "process_only",
        ("research_oversold_three_ma_wrap_stable_base",),
    ),
    "传智教育 MA10 向 MA30 收敛": CaseSourceMetadata(
        date(2026, 7, 15),
        date(2026, 7, 27),
        "process_only",
        ("staged_ma10_support_before_ma30_convergence_shrink",),
    ),
    "一鸣食品 MA10 贴合 MA20": CaseSourceMetadata(
        date(2026, 7, 14),
        None,
        "process_only",
        ("ma10_ma20_contact_pre_cross_positive_volume_expand",),
    ),
    "一鸣食品 超跌转趋势": CaseSourceMetadata(
        date(2026, 7, 14),
        date(2026, 7, 28),
        "process_only",
        ("oversold_to_trend_after_ma10_dual_cross_near_ma20_ma30",),
    ),
    "立新能源 MA10 向 MA20 加速收敛": CaseSourceMetadata(
        date(2026, 7, 14),
        None,
        "process_only",
        (),
        "research_pending",
    ),
    "爱丽家居 MA10 回贴 MA30": CaseSourceMetadata(
        date(2026, 7, 8),
        date(2026, 7, 21),
        "process_only",
        ("ma10_ma30_retest_after_actual_cross_two_leg_volume",),
    ),
    "百花医药 M10/M20 两线包裹": CaseSourceMetadata(
        date(2026, 7, 14),
        None,
        "process_only",
        ("first_leg_two_ma_body_wrap_before_ma30",),
    ),
    "百花医药 三线包裹": CaseSourceMetadata(
        date(2026, 7, 14),
        None,
        "process_only",
        ("research_oversold_three_ma_wrap_stable_base",),
    ),
    "百花医药 向上踩稳": CaseSourceMetadata(
        date(2026, 7, 31),
        date(2026, 8, 4),
        "process_only",
        ("post_wrap_upper_band_reclaim_confirmation",),
    ),
    "国风新材 攻击实体守住": CaseSourceMetadata(
        date(2026, 7, 20),
        date(2026, 8, 10),
        "process_only",
        ("attack_body_hold_after_ma10_ma20_cross_before_ma30",),
    ),
    "秦安股份 MA10 上穿 MA20": CaseSourceMetadata(
        None,
        None,
        "process_only",
        (),
        "research_pending",
    ),
    "京投发展 价格先行攻击": CaseSourceMetadata(
        None,
        None,
        "process_only",
        (),
        "research_pending",
    ),
    "中南文化 MA10 回踩": CaseSourceMetadata(
        date(2026, 2, 10),
        None,
        "ma10_low_touch",
        ("ma10_low_touch_after_ma5_extension",),
    ),
    "华电辽能 MA5 回踩": CaseSourceMetadata(
        date(2026, 2, 6),
        date(2026, 3, 6),
        "ma5_low_touch",
        ("ma5_low_touch_stable_trend",),
    ),
    "华电辽能 MA5 缩量回踩": CaseSourceMetadata(
        date(2026, 2, 6),
        date(2026, 3, 16),
        "ma5_low_touch",
        ("ma5_low_touch_stable_trend_volume_shrink",),
    ),
    "华电辽能 趋势重建 MA5 回踩": CaseSourceMetadata(
        date(2026, 4, 14),
        date(2026, 5, 6),
        "ma5_low_touch_broad",
        ("ma5_low_touch_after_disordered_trend_rebuild",),
    ),
    **{
        f"华建集团 连续 MA5 低吸 {value.isoformat()}": CaseSourceMetadata(
            date(2025, 9, 17),
            date(2025, 9, 25),
            "ma5_low_touch",
            (
                "ma5_low_touch_early_trend"
                if value == date(2025, 9, 18)
                else "ma5_low_touch_early_trend_prior_touch",
            ),
        )
        for value in (
            date(2025, 9, 18),
            date(2025, 9, 19),
            date(2025, 9, 22),
            date(2025, 9, 23),
            date(2025, 9, 24),
        )
    },
}


PERSONAL_CASES = tuple(
    PersonalResearchCase(
        name=name,
        vt_symbol=vt_symbol,
        trade_date=trade_date,
        expected_setup_type=expected_setup_type,
        narrative_start_date=PERSONAL_CASE_SOURCE_METADATA[name].narrative_start_date,
        expected_launch_date=PERSONAL_CASE_SOURCE_METADATA[name].expected_launch_date,
        source_anchor=PERSONAL_CASE_SOURCE_METADATA[name].source_anchor,
        required_process_rule_keys=(
            PERSONAL_CASE_SOURCE_METADATA[name].required_process_rule_keys
        ),
        narrative_status=PERSONAL_CASE_SOURCE_METADATA[name].narrative_status,
    )
    for name, vt_symbol, trade_date, expected_setup_type in PERSONAL_RESEARCH_CASES
)

EXIT_PROBES: dict[str, tuple[ExitProbe, ...]] = {
    "oversold_rebound": (
        ExitProbe("d1_close", 1),
        ExitProbe("d2_close", 2),
        ExitProbe("d3_close", 3),
        ExitProbe("d5_close", 5),
        ExitProbe("ma10_break_or_d5", 5, break_ma="ma10"),
    ),
    "trend_pullback": (
        ExitProbe("d1_close", 1),
        ExitProbe("d3_close", 3),
        ExitProbe("d5_close", 5),
        ExitProbe("ma5_break_or_d10", 10, break_ma="ma5"),
        ExitProbe("ma10_break_or_d10", 10, break_ma="ma10"),
    ),
}
MAX_EXIT_HOLDING_SESSIONS = max(
    probe.max_holding_sessions
    for probes in EXIT_PROBES.values()
    for probe in probes
)


@dataclass
class _OutcomeAccumulator:
    candidate_count: int = 0
    label_unavailable_count: int = 0
    label_excluded_main_board_price_limit_count: int = 0
    d1_limit_up_touch_available_count: int = 0
    d1_limit_up_touch_count: int = 0
    d1_fresh_limit_up_touch_proxy_available_count: int = 0
    d1_fresh_limit_up_touch_proxy_count: int = 0
    d1_limit_up_close_proxy_available_count: int = 0
    d1_limit_up_close_proxy_count: int = 0
    d1_fresh_limit_up_close_proxy_available_count: int = 0
    d1_fresh_limit_up_close_proxy_count: int = 0
    dates: set[date] = field(default_factory=set)
    values: list[float] = field(default_factory=list)

    def add(
        self,
        trade_date: date,
        value: float | None,
        label_status: str = "available",
        *,
        d1_limit_up_touch: bool | None = None,
        d1_fresh_limit_up_touch_proxy: bool | None = None,
        d1_limit_up_close_proxy: bool | None = None,
        d1_fresh_limit_up_close_proxy: bool | None = None,
    ) -> None:
        self.candidate_count += 1
        self.dates.add(trade_date)
        if d1_limit_up_touch is not None:
            self.d1_limit_up_touch_available_count += 1
            self.d1_limit_up_touch_count += int(d1_limit_up_touch)
        if d1_fresh_limit_up_touch_proxy is not None:
            self.d1_fresh_limit_up_touch_proxy_available_count += 1
            self.d1_fresh_limit_up_touch_proxy_count += int(
                d1_fresh_limit_up_touch_proxy
            )
        if d1_limit_up_close_proxy is not None:
            self.d1_limit_up_close_proxy_available_count += 1
            self.d1_limit_up_close_proxy_count += int(d1_limit_up_close_proxy)
        if d1_fresh_limit_up_close_proxy is not None:
            self.d1_fresh_limit_up_close_proxy_available_count += 1
            self.d1_fresh_limit_up_close_proxy_count += int(
                d1_fresh_limit_up_close_proxy
            )
        if value is None:
            self.label_unavailable_count += 1
            if label_status == "label_excluded_main_board_price_limit":
                self.label_excluded_main_board_price_limit_count += 1
            return
        self.values.append(value)

    def summary(self) -> dict[str, object]:
        values = self.values
        negative_values = [value for value in values if value < 0]
        return {
            "candidate_count": self.candidate_count,
            "candidate_days": len(self.dates),
            "sample_count": len(values),
            "label_unavailable_count": self.label_unavailable_count,
            "label_excluded_main_board_price_limit_count": self.label_excluded_main_board_price_limit_count,
            "d1_limit_up_touch_available_count": self.d1_limit_up_touch_available_count,
            "d1_limit_up_touch_count": self.d1_limit_up_touch_count,
            "d1_limit_up_touch_rate_pct": _rate_pct(
                self.d1_limit_up_touch_count,
                self.d1_limit_up_touch_available_count,
            ),
            "d1_fresh_limit_up_touch_proxy_available_count": self.d1_fresh_limit_up_touch_proxy_available_count,
            "d1_fresh_limit_up_touch_proxy_count": self.d1_fresh_limit_up_touch_proxy_count,
            "d1_fresh_limit_up_touch_proxy_rate_pct": _rate_pct(
                self.d1_fresh_limit_up_touch_proxy_count,
                self.d1_fresh_limit_up_touch_proxy_available_count,
            ),
            "d1_limit_up_close_proxy_available_count": self.d1_limit_up_close_proxy_available_count,
            "d1_limit_up_close_proxy_count": self.d1_limit_up_close_proxy_count,
            "d1_limit_up_close_proxy_rate_pct": _rate_pct(
                self.d1_limit_up_close_proxy_count,
                self.d1_limit_up_close_proxy_available_count,
            ),
            "d1_fresh_limit_up_close_proxy_available_count": self.d1_fresh_limit_up_close_proxy_available_count,
            "d1_fresh_limit_up_close_proxy_count": self.d1_fresh_limit_up_close_proxy_count,
            "d1_fresh_limit_up_close_proxy_rate_pct": _rate_pct(
                self.d1_fresh_limit_up_close_proxy_count,
                self.d1_fresh_limit_up_close_proxy_available_count,
            ),
            "win_rate_pct": _round_pct(
                sum(value > 0 for value in values) / len(values) * 100
            )
            if values
            else None,
            "negative_count": len(negative_values),
            "negative_rate_pct": _rate_pct(len(negative_values), len(values)),
            "negative_mean_return_pct": _round_pct(fmean(negative_values))
            if negative_values
            else None,
            "d1_mean_return_pct": _round_pct(fmean(values)) if values else None,
            "d1_median_return_pct": _round_pct(median(values)) if values else None,
            "daily_candidate_average": _round_pct(
                self.candidate_count / len(self.dates)
            )
            if self.dates
            else 0.0,
        }


@dataclass
class _ExitAccumulator:
    candidate_count: int = 0
    closed_count: int = 0
    unavailable_count: int = 0
    returns: list[float] = field(default_factory=list)
    holding_sessions: list[int] = field(default_factory=list)
    reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, outcome: Mapping[str, object]) -> None:
        self.candidate_count += 1
        status = str(outcome.get("status") or "unavailable")
        if status != "closed":
            self.unavailable_count += 1
            self.reasons[str(outcome.get("exit_reason") or status)] += 1
            return
        self.closed_count += 1
        value = _number_or_none(outcome.get("return_pct"))
        holding = _integer_or_none(outcome.get("holding_sessions"))
        if value is not None:
            self.returns.append(value)
        if holding is not None:
            self.holding_sessions.append(holding)
        self.reasons[str(outcome.get("exit_reason") or "fixed_horizon")] += 1

    def summary(self) -> dict[str, object]:
        values = self.returns
        return {
            "candidate_count": self.candidate_count,
            "closed_count": self.closed_count,
            "unavailable_count": self.unavailable_count,
            "sample_count": len(values),
            "win_rate_pct": _round_pct(
                sum(value > 0 for value in values) / len(values) * 100
            )
            if values
            else None,
            "mean_return_pct": _round_pct(fmean(values)) if values else None,
            "median_return_pct": _round_pct(median(values)) if values else None,
            "mean_holding_sessions": _round_pct(fmean(self.holding_sessions))
            if self.holding_sessions
            else None,
            "exit_reasons": dict(sorted(self.reasons.items())),
        }


def classify_oversold_state(features: Mapping[str, object]) -> dict[str, str]:
    """Classify predeclared MA, price, and volume states for oversold research."""

    close_price = _number_or_none(features.get("close_price"))
    return {
        "ma10_ma20_state": _ma_relation(
            features.get("ma10"), features.get("ma20"), close_price
        ),
        "ma10_ma30_state": _ma_relation(
            features.get("ma10"), features.get("ma30"), close_price
        ),
        "ma20_ma30_state": _ma_relation(
            features.get("ma20"), features.get("ma30"), close_price
        ),
        "price_state": _daily_price_state(features.get("daily_return_pct")),
        "volume_shape": _volume_shape(features),
    }


def classify_trend_state(features: Mapping[str, object]) -> dict[str, str]:
    """Classify MA5/MA10 support state using the D-day low before the close."""

    support_line = str(features.get("trend_reference_line") or "none")
    low_distance = _number_or_none(features.get("trend_low_to_reference_pct"))
    close_distance = _number_or_none(features.get("trend_close_to_reference_pct"))
    if support_line == "none" or low_distance is None or close_distance is None:
        support_touch = "unavailable"
    elif SUPPORT_TOUCH_LOW_MIN_PCT <= low_distance <= SUPPORT_TOUCH_LOW_MAX_PCT:
        support_touch = "low_touch"
    elif abs(close_distance) <= SUPPORT_CLOSE_NEAR_PCT:
        support_touch = "close_near"
    else:
        support_touch = "not_near"
    bull_days = _integer_or_none(features.get("bull_alignment_days"))
    return {
        "support_line": support_line,
        "support_touch": support_touch,
        "ma5_regular": _yes_no(features.get("ma5_regular")),
        "regime_state": "stable_bull"
        if bull_days is not None and bull_days >= 5
        else "recent_or_mixed",
        "price_state": _daily_price_state(features.get("daily_return_pct")),
        "volume_shape": _volume_shape(features),
    }


def source_geometry_matches(
    features: Mapping[str, object],
    source_anchor: str,
) -> bool:
    """Match the source-declared intraday support geometry without candle bias."""

    anchors = {
        "process_only": True,
        "ma5_low_touch": bool(features.get("ma5_low_touch")),
        "ma5_low_touch_broad": bool(features.get("ma5_low_touch_broad")),
        "ma10_low_touch": bool(features.get("ma10_low_touch")),
        "ma5_or_ma10_low_touch": bool(
            features.get("ma5_low_touch") or features.get("ma10_low_touch")
        ),
    }
    if source_anchor not in anchors:
        raise DailyFactorInputError(f"unsupported personal-case source anchor: {source_anchor}")
    return anchors[source_anchor]


def audit_personal_cases(
    bars: Sequence[Mapping[str, object]],
    market_calendar: Sequence[date],
    *,
    cases: Sequence[PersonalResearchCase] = PERSONAL_CASES,
) -> list[dict[str, object]]:
    """Audit each declared case from D-and-earlier bars, even when it does not match."""

    calendar = _strict_calendar(market_calendar)
    histories = _group_histories(bars)
    calendar_positions = {value: index for index, value in enumerate(calendar)}
    rows: list[dict[str, object]] = []
    for case in cases:
        history = histories.get(case.vt_symbol)
        if history is None:
            rows.append(_missing_case_row(case, "symbol_bars_unavailable"))
            continue
        position = _history_position(history, case.trade_date)
        if position is None:
            rows.append(_missing_case_row(case, "case_trade_date_unavailable"))
            continue
        features = build_daily_features(daily_factor_history_window(history, position))
        closes = {
            _required_date(row.get("trade_date")): _number_or_none(row.get("close_price"))
            for row in history
        }
        next_trade_date = _next_calendar_date(calendar, calendar_positions, case.trade_date)
        d1_touch_proxy = classify_d1_limit_up_touch_proxy(
            signal_bar=history[position],
            d1_bar=(
                next(
                    (
                        row
                        for row in history
                        if _required_date(row.get("trade_date")) == next_trade_date
                    ),
                    None,
                )
                if next_trade_date is not None
                else None
            ),
            prior_signal_bar=history[position - 1] if position else None,
        )
        label, label_status = d1_close_label_status(
            closes,
            calendar,
            case.trade_date,
        )
        setup_type = classify_daily_setup(features)
        state = (
            classify_oversold_state(features)
            if case.expected_setup_type == "oversold_rebound"
            else classify_trend_state(features)
        )
        narrative_evidence = _case_narrative_evidence(
            history=history,
            signal_position=position,
            case=case,
            market_calendar=calendar,
            calendar_positions=calendar_positions,
        )
        baseline_predicates = explain_setup_eligibility(
            features,
            case.expected_setup_type,
        )
        process_evidence = _case_process_evidence(
            history,
            position,
            case,
            market_calendar=calendar,
            calendar_positions=calendar_positions,
        )
        baseline_matched = setup_type == case.expected_setup_type
        process_matched = bool(process_evidence["process_probe_rule_keys"])
        source_geometry_matched = bool(process_evidence["source_geometry_matched"])
        required_process_matched = bool(process_evidence["required_process_matched"])
        rows.append(
            {
                "name": case.name,
                "vt_symbol": case.vt_symbol,
                "trade_date": case.trade_date,
                "observed_through": case.trade_date,
                "expected_setup_type": case.expected_setup_type,
                "setup_type": setup_type,
                "expected_setup_matched": baseline_matched,
                "process_probe_matched": process_matched,
                "source_anchor": case.source_anchor,
                "source_geometry_matched": source_geometry_matched,
                "required_process_rule_keys": list(case.required_process_rule_keys),
                "required_process_matched": required_process_matched,
                "missing_required_process_rule_keys": process_evidence[
                    "missing_required_process_rule_keys"
                ],
                "case_model_matched": bool(
                    case.narrative_status == "complete"
                    and source_geometry_matched
                    and required_process_matched
                ),
                "case_match_status": _case_match_status(
                    narrative_status=case.narrative_status,
                    source_geometry_matched=source_geometry_matched,
                    required_process_matched=required_process_matched,
                ),
                "narrative_status": case.narrative_status,
                "data_status": _case_data_status(
                    case.trade_date,
                    calendar_positions,
                    label_status,
                ),
                "d1_close_return_pct": label,
                "feature_snapshot": _feature_snapshot(features),
                "state": state,
                "predicate_results": baseline_predicates,
                "failed_predicates": [
                    key for key, passed in baseline_predicates.items() if not passed
                ],
                **process_evidence,
                "scores": score_factor_variants(features),
                **narrative_evidence,
                **d1_touch_proxy,
            }
        )
    return rows


def _case_process_evidence(
    history: Sequence[Mapping[str, object]],
    position: int,
    case: PersonalResearchCase,
    *,
    market_calendar: Sequence[date],
    calendar_positions: Mapping[date, int],
) -> dict[str, object]:
    from .daily_factor_extended_discovery import (
        build_extended_daily_features,
        classify_oversold_attack_stages,
        matching_discovery_rule_keys,
        process_rule_predicates,
    )

    features = build_extended_daily_features(
        daily_factor_history_window(history, position),
        include_pre_attack_base_features=True,
    )
    calendar_position = calendar_positions.get(case.trade_date)
    prior_is_previous_market_session = bool(
        position > 0
        and calendar_position is not None
        and calendar_position > 0
        and _required_date(history[position - 1].get("trade_date"))
        == market_calendar[calendar_position - 1]
    )
    prior_features = (
        build_extended_daily_features(
            daily_factor_history_window(history, position - 1),
            include_pre_attack_base_features=True,
        )
        if prior_is_previous_market_session
        else None
    )
    process_rule_keys = list(
        matching_discovery_rule_keys(
            features,
            case.expected_setup_type,
            prior_features=prior_features,
        )
    )
    required_keys = set(case.required_process_rule_keys)
    missing_required_keys = sorted(required_keys - set(process_rule_keys))
    required_process_predicate_results = {
        rule_key: process_rule_predicates(
            rule_key,
            features,
            prior_features=prior_features,
        )
        for rule_key in case.required_process_rule_keys
    }
    failed_required_process_predicates = {
        rule_key: [
            predicate
            for predicate, matched in predicates.items()
            if not matched
        ]
        for rule_key, predicates in required_process_predicate_results.items()
        if not all(predicates.values())
    }
    source_geometry_matched = source_geometry_matches(features, case.source_anchor)
    close_price = _number_or_none(features.get("close_price"))
    attack_stages = (
        classify_oversold_attack_stages(
            features,
            prior_features=prior_features,
        )
        if case.expected_setup_type == "oversold_rebound"
        else ()
    )
    return {
        "process_probe_rule_keys": process_rule_keys,
        "source_is_oversold_attack_anchor": (
            case.expected_setup_type == "oversold_rebound"
        ),
        "recognized_oversold_attack_stages": list(attack_stages),
        "source_geometry_matched": source_geometry_matched,
        "required_process_matched": bool(
            not missing_required_keys and not failed_required_process_predicates
        ),
        "missing_required_process_rule_keys": missing_required_keys,
        "required_process_predicate_results": required_process_predicate_results,
        "failed_required_process_predicates": failed_required_process_predicates,
        "close_only_backtest_eligible": bool(
            source_geometry_matched and close_price is not None and close_price > 0
        ),
        "close_entry_price": close_price,
        "close_entry_anchor_distance_pct": _source_anchor_close_distance_pct(
            features,
            case.source_anchor,
        ),
        "process_feature_snapshot": {
            field: features.get(field)
            for field in (
                "pre_attack_base_phase",
                "pre_attack_base_pivot_age_sessions",
                "pre_attack_base_release_after_final_pivot",
                "pre_attack_base_settlement_sessions",
                "pre_attack_base_tail_span_to_median_range",
                "pre_attack_base_tail_floor_vs_pivot_pct",
                "pre_attack_base_tail_retested_release",
                "pre_attack_base_ma10_ma20_progress_per_churn",
                "low_to_ma5_pct",
                "close_to_ma5_pct",
                "low_to_ma10_pct",
                "close_to_ma10_pct",
                "ma10_crossed_ma20_age_sessions_15d",
                "ma10_crossed_ma30_age_sessions_15d",
                "ma10_crossed_ma20_within_15d",
                "ma10_crossed_ma30_within_15d",
                "ma10_crossed_ma20_after_long_bear_age_sessions_15d",
                "ma10_crossed_ma20_after_long_bear_within_15d",
                "current_full_bear_alignment",
                "ma10_above_ma20",
                "ma10_below_ma30",
                "ma10_ma30_fast_convergence",
                "ma10_dual_cross_within_15d",
                "ma10_dual_cross_within_7d",
                "ma10_above_ma20_and_ma30",
                "ma10_ma30_contact",
                "ma20_ma30_contact",
                "transition_ma20_ma30_tight_contact",
                "ma10_ma20_slopes_up",
                "small_positive_candle",
                "trend_transition_eligible",
                "ma10_ma30_gap_narrowing_5d_pct",
                "ma10_ma30_gap_converging",
                "ma10_was_above_ma30_within_15d",
                "recent_pullback_from_high_pct",
                "post_cross_pullback",
                "aggressive_pullback",
                "ma5_low_touch",
                "ma5_low_touch_broad",
                "ma10_low_touch",
                "trend_stable_bull",
                "trend_rebuilt_recently",
                "trend_rebuilt_from_disorder",
                "last_volume_change_pct",
                "last_volume_expanded",
                "last_volume_shrank",
                "volume_expand_then_shrink",
                "volume_shrink_then_expand",
                "prior_ma5_close_distance_pct",
                "prior_ma5_close_extension",
                "prior_daily_price_not_up",
                "prior_ma5_low_touch",
            )
        },
    }


def _source_anchor_close_distance_pct(
    features: Mapping[str, object],
    source_anchor: str,
) -> float | None:
    if source_anchor in {"ma5_low_touch", "ma5_low_touch_broad"}:
        return _number_or_none(features.get("close_to_ma5_pct"))
    if source_anchor == "ma10_low_touch":
        return _number_or_none(features.get("close_to_ma10_pct"))
    if source_anchor == "ma5_or_ma10_low_touch":
        distances = [
            _number_or_none(features.get("close_to_ma5_pct")),
            _number_or_none(features.get("close_to_ma10_pct")),
        ]
        usable = [value for value in distances if value is not None]
        return min(usable, key=abs) if usable else None
    return None


def _case_match_status(
    *,
    narrative_status: str,
    source_geometry_matched: bool,
    required_process_matched: bool,
) -> str:
    if narrative_status != "complete":
        return narrative_status
    if source_geometry_matched and required_process_matched:
        return "source_geometry_and_required_process_matched"
    if source_geometry_matched:
        return "source_geometry_matched_required_process_missing"
    if required_process_matched:
        return "source_anchor_unmatched"
    return "source_anchor_and_required_process_unmatched"


def _case_narrative_evidence(
    *,
    history: Sequence[Mapping[str, object]],
    signal_position: int,
    case: PersonalResearchCase,
    market_calendar: Sequence[date],
    calendar_positions: Mapping[date, int],
) -> dict[str, object]:
    launch_observation = _case_launch_observation(
        history,
        case,
        market_calendar,
        calendar_positions,
    )
    if case.narrative_status != "complete":
        return {
            "narrative_timeline_status": case.narrative_status,
            "narrative_timeline": [],
            "narrative_checks": {"timeline_available": False},
            "launch_observation": launch_observation,
        }
    if case.narrative_start_date is None:
        return {
            "narrative_timeline_status": "narrative_start_not_declared",
            "narrative_timeline": [],
            "narrative_checks": {"timeline_available": False},
            "launch_observation": launch_observation,
        }
    start_position = _history_position(history, case.narrative_start_date)
    if start_position is None:
        return {
            "narrative_timeline_status": "narrative_start_date_unavailable",
            "narrative_timeline": [],
            "narrative_checks": {"timeline_available": False},
            "launch_observation": launch_observation,
        }
    if start_position > signal_position:
        return {
            "narrative_timeline_status": "narrative_start_after_signal",
            "narrative_timeline": [],
            "narrative_checks": {"timeline_available": False},
            "launch_observation": launch_observation,
        }
    timeline = [
        _case_timeline_row(
            build_daily_features(daily_factor_history_window(history, position)),
            case.expected_setup_type,
        )
        for position in range(start_position, signal_position + 1)
    ]
    return {
        "narrative_timeline_status": "available",
        "narrative_timeline": timeline,
        "narrative_checks": _case_narrative_checks(
            case.expected_setup_type,
            timeline,
        ),
        "launch_observation": launch_observation,
    }


def _case_timeline_row(
    features: Mapping[str, object],
    expected_setup_type: str,
) -> dict[str, object]:
    state = (
        classify_oversold_state(features)
        if expected_setup_type == "oversold_rebound"
        else classify_trend_state(features)
    )
    close_price = features.get("close_price")
    return {
        "trade_date": features.get("trade_date"),
        "close_price": close_price,
        "volume": features.get("volume"),
        "ma5": features.get("ma5"),
        "ma10": features.get("ma10"),
        "ma20": features.get("ma20"),
        "ma30": features.get("ma30"),
        "ma60": features.get("ma60"),
        "ma5_ma10_state": _ma_relation(
            features.get("ma5"),
            features.get("ma10"),
            close_price,
        ),
        "ma10_ma20_state": _ma_relation(
            features.get("ma10"),
            features.get("ma20"),
            close_price,
        ),
        "ma10_ma30_state": _ma_relation(
            features.get("ma10"),
            features.get("ma30"),
            close_price,
        ),
        "ma20_ma30_state": _ma_relation(
            features.get("ma20"),
            features.get("ma30"),
            close_price,
        ),
        "ma_cluster_spread_pct": features.get("ma_cluster_spread_pct"),
        "daily_return_pct": features.get("daily_return_pct"),
        "price_state": state.get("price_state"),
        "volume_shape": state.get("volume_shape"),
        "prior_bear_alignment_days": features.get("prior_bear_alignment_days"),
        "bull_alignment_days": features.get("bull_alignment_days"),
        "ma5_regular": state.get("ma5_regular"),
        "support_line": state.get("support_line"),
        "support_touch": state.get("support_touch"),
    }


def _case_narrative_checks(
    expected_setup_type: str,
    timeline: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    if not timeline:
        return {"timeline_available": False}
    first = timeline[0]
    signal = timeline[-1]
    near_or_above = {"near_or_crossed", "above"}
    checks: dict[str, object] = {
        "timeline_available": True,
        "ma10_ma20_relation_start": first.get("ma10_ma20_state"),
        "ma10_ma20_relation_signal": signal.get("ma10_ma20_state"),
        "ma20_ma30_relation_start": first.get("ma20_ma30_state"),
        "ma20_ma30_relation_signal": signal.get("ma20_ma30_state"),
        "ma10_ma20_near_or_crossed_seen": any(
            row.get("ma10_ma20_state") in near_or_above for row in timeline
        ),
        "ma20_ma30_near_or_crossed_seen": any(
            row.get("ma20_ma30_state") in near_or_above for row in timeline
        ),
        "ma10_ma30_near_or_crossed_seen": any(
            row.get("ma10_ma30_state") in near_or_above for row in timeline
        ),
        "staircase_shrink_seen": any(
            row.get("volume_shape") == "staircase_shrink" for row in timeline
        ),
        "staircase_expand_seen": any(
            row.get("volume_shape") == "staircase_expand" for row in timeline
        ),
    }
    if expected_setup_type == "oversold_rebound":
        checks["prior_bear_structure_at_start"] = (
            (_integer_or_none(first.get("prior_bear_alignment_days")) or 0) >= 5
        )
    else:
        checks["stable_bull_alignment_at_signal"] = (
            (_integer_or_none(signal.get("bull_alignment_days")) or 0) >= 5
        )
        checks["ma5_regular_at_signal"] = signal.get("ma5_regular") == "yes"
        checks["support_touch_at_signal"] = signal.get("support_touch")
    return checks


def _case_launch_observation(
    history: Sequence[Mapping[str, object]],
    case: PersonalResearchCase,
    market_calendar: Sequence[date],
    calendar_positions: Mapping[date, int],
) -> dict[str, object]:
    expected_launch_date = case.expected_launch_date
    base = {
        "expected_launch_date": expected_launch_date,
        "signal_trade_date": case.trade_date,
        "launch_after_signal": None,
        "required_previous_market_trade_date": None,
        "previous_trade_date": None,
        "raw_close_return_pct": None,
        "raw_high_return_pct": None,
        "strict_limit_up_touch_proxy": None,
        "strict_limit_up_close_proxy": None,
        "strict_limit_up_touch_status": "not_checked",
        "strict_limit_up_close_proxy_status": "not_checked",
    }
    if case.narrative_status != "complete":
        return {**base, "status": case.narrative_status}
    if expected_launch_date is None:
        return {**base, "status": "expected_launch_not_declared"}
    launch_calendar_position = calendar_positions.get(expected_launch_date)
    if launch_calendar_position is None:
        return {**base, "status": "expected_launch_not_in_market_calendar"}
    signal_calendar_position = calendar_positions.get(case.trade_date)
    if signal_calendar_position is None:
        return {**base, "status": "signal_date_not_in_market_calendar"}
    if launch_calendar_position <= signal_calendar_position:
        return {**base, "status": "expected_launch_not_after_signal"}
    bars_by_date = {
        _required_date(row.get("trade_date")): row
        for row in history
    }
    launch_bar = bars_by_date.get(expected_launch_date)
    if launch_bar is None:
        return {**base, "status": "expected_launch_date_unavailable"}
    if launch_calendar_position == 0:
        return {**base, "status": "missing_launch_previous_market_bar"}
    required_previous_date = market_calendar[launch_calendar_position - 1]
    prior_bar = bars_by_date.get(required_previous_date)
    if prior_bar is None:
        return {
            **base,
            "launch_after_signal": True,
            "required_previous_market_trade_date": required_previous_date,
            "status": "missing_launch_previous_market_bar",
        }
    prior_previous_bar = (
        bars_by_date.get(market_calendar[launch_calendar_position - 2])
        if launch_calendar_position >= 2
        else None
    )
    prior_close = _positive_number_or_none(prior_bar.get("close_price"))
    launch_close = _positive_number_or_none(launch_bar.get("close_price"))
    launch_high = _positive_number_or_none(launch_bar.get("high_price"))
    proxy = classify_d1_limit_up_touch_proxy(
        signal_bar=prior_bar,
        d1_bar=launch_bar,
        prior_signal_bar=prior_previous_bar,
    )
    return {
        **base,
        "status": "available",
        "launch_after_signal": True,
        "required_previous_market_trade_date": required_previous_date,
        "previous_trade_date": _required_date(prior_bar.get("trade_date")),
        "raw_close_return_pct": _raw_return_pct(prior_close, launch_close),
        "raw_high_return_pct": _raw_return_pct(prior_close, launch_high),
        "strict_limit_up_touch_proxy": proxy.get("d1_limit_up_touch"),
        "strict_limit_up_close_proxy": proxy.get("d1_limit_up_close_proxy"),
        "strict_limit_up_touch_status": proxy.get("d1_limit_up_touch_status"),
        "strict_limit_up_close_proxy_status": proxy.get(
            "d1_limit_up_close_proxy_status"
        ),
    }


def _raw_return_pct(prior_close: float | None, current_price: float | None) -> float | None:
    if prior_close is None or current_price is None:
        return None
    return _round_pct((current_price / prior_close - 1) * 100)


def evaluate_close_exit_probe(
    candidate: Mapping[str, object],
    future_bars: Sequence[Mapping[str, object]],
    *,
    probe: ExitProbe,
) -> dict[str, object]:
    """Evaluate one declared daily-close exit without skipping missing sessions."""

    entry_date = _required_date(candidate.get("entry_date"))
    entry_price = _required_positive_number(candidate.get("entry_price"), "entry_price")
    normalized = tuple(sorted(future_bars, key=lambda row: _required_date(row.get("trade_date"))))
    base = {
        "probe": probe.key,
        "entry_date": entry_date,
        "entry_price": entry_price,
        "exit_price_mode": "close",
        "status": "unavailable",
        "exit_date": None,
        "exit_price": None,
        "return_pct": None,
        "holding_sessions": None,
        "exit_reason": None,
    }
    if len(normalized) < probe.max_holding_sessions:
        return {**base, "exit_reason": "missing_exit_session"}

    prior_close = entry_price
    for session, row in enumerate(normalized[: probe.max_holding_sessions], start=1):
        trade_date = _required_date(row.get("trade_date"))
        if trade_date <= entry_date:
            return {**base, "exit_reason": "future_bar_not_after_entry"}
        close_price = _number_or_none(row.get("close_price"))
        if close_price is None or close_price <= 0:
            return {**base, "exit_reason": "missing_exit_price"}
        if not is_main_board_close_within_price_limit(prior_close, close_price):
            return {**base, "exit_reason": "raw_price_limit_outlier"}
        if probe.break_ma is not None:
            reference = _number_or_none(row.get(probe.break_ma))
            if reference is None or reference <= 0:
                return {**base, "exit_reason": f"missing_{probe.break_ma}"}
            if close_price < reference:
                return _closed_exit(
                    base,
                    trade_date=trade_date,
                    exit_price=close_price,
                    holding_sessions=session,
                    reason=f"{probe.break_ma}_break",
                )
        prior_close = close_price

    target = normalized[probe.max_holding_sessions - 1]
    close_price = _required_positive_number(target.get("close_price"), "exit_price")
    return _closed_exit(
        base,
        trade_date=_required_date(target.get("trade_date")),
        exit_price=close_price,
        holding_sessions=probe.max_holding_sessions,
        reason="fixed_horizon",
    )


def classify_d1_limit_up_touch_proxy(
    *,
    signal_bar: Mapping[str, object],
    d1_bar: Mapping[str, object] | None,
    prior_signal_bar: Mapping[str, object] | None,
) -> dict[str, object]:
    """Describe a D+1 daily-bar touch without claiming a formal first board.

    The D+1 OHLC must all remain inside the same strict +/-10% raw-price
    contract as the D+1 close label. High-price touch and close-at-limit are
    separate daily-bar proxies. ``fresh`` only compares D+1 with the signal
    day, so it does not establish exchange-level first-board identity or
    execution feasibility.
    """

    unavailable = _unavailable_d1_limit_up_touch_proxy
    signal_close = _positive_number_or_none(signal_bar.get("close_price"))
    if signal_close is None:
        return unavailable("missing_signal_close")
    if d1_bar is None:
        return unavailable("missing_d1_bar")
    d1_prices = {
        field: _positive_number_or_none(d1_bar.get(field))
        for field in ("open_price", "high_price", "low_price", "close_price")
    }
    if any(value is None for value in d1_prices.values()):
        return unavailable("missing_d1_ohlc")
    d1_open = float(d1_prices["open_price"])
    d1_high = float(d1_prices["high_price"])
    d1_low = float(d1_prices["low_price"])
    d1_close = float(d1_prices["close_price"])
    if d1_high < max(d1_open, d1_close) or d1_low > min(d1_open, d1_close):
        return unavailable("invalid_d1_ohlc")
    if not all(
        is_main_board_close_within_price_limit(signal_close, value)
        for value in (d1_open, d1_high, d1_low, d1_close)
    ):
        return unavailable("raw_price_limit_outlier")

    d1_touch = is_main_board_limit_up_touched(signal_close, d1_high)
    d1_close_proxy = is_main_board_limit_up_touched(signal_close, d1_close)
    fresh_touch: bool | None = None
    fresh_status = "missing_prior_signal_bar"
    fresh_close: bool | None = None
    fresh_close_status = "missing_prior_signal_bar"
    if prior_signal_bar is not None:
        prior_close = _positive_number_or_none(prior_signal_bar.get("close_price"))
        signal_high = _positive_number_or_none(signal_bar.get("high_price"))
        if prior_close is None:
            fresh_status = "missing_signal_day_high"
            fresh_close_status = "missing_signal_day_close"
        elif signal_high is None:
            fresh_status = "missing_signal_day_high"
        elif not is_main_board_close_within_price_limit(prior_close, signal_high):
            fresh_status = "signal_day_raw_price_limit_outlier"
        else:
            fresh_touch = d1_touch and not is_main_board_limit_up_touched(
                prior_close,
                signal_high,
            )
            fresh_status = "available"
        if prior_close is not None:
            if not is_main_board_close_within_price_limit(prior_close, signal_close):
                fresh_close_status = "signal_day_raw_price_limit_outlier"
            else:
                fresh_close = d1_close_proxy and not is_main_board_limit_up_touched(
                    prior_close,
                    signal_close,
                )
                fresh_close_status = "available"
    return {
        "d1_limit_up_touch": d1_touch,
        "d1_fresh_limit_up_touch_proxy": fresh_touch,
        "d1_limit_up_close_proxy": d1_close_proxy,
        "d1_fresh_limit_up_close_proxy": fresh_close,
        "d1_limit_up_touch_status": "available",
        "d1_fresh_limit_up_touch_proxy_status": fresh_status,
        "d1_limit_up_close_proxy_status": "available",
        "d1_fresh_limit_up_close_proxy_status": fresh_close_status,
    }


def summarize_comprehensive_observations(
    observations: Iterable[Mapping[str, object]],
    market_calendar: Sequence[date],
) -> dict[str, object]:
    """Aggregate a stream of causal observations without retaining the full panel."""

    calendar = _strict_calendar(market_calendar)
    split = split_market_calendar(calendar)
    segments = _segment_dates(split)
    accumulators = {
        setup_type: _FamilyAccumulator.create() for setup_type in SETUP_TYPES
    }
    for observation in observations:
        setup_type = str(observation.get("setup_type") or "")
        if setup_type not in accumulators:
            continue
        accumulators[setup_type].add(observation, segments)
    return {
        "time_split": _time_split_payload(split),
        "families": {
            setup_type: accumulator.render()
            for setup_type, accumulator in accumulators.items()
        },
    }


def run_comprehensive_daily_factor_study(
    *,
    bars: Sequence[Mapping[str, object]],
    market_calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
    evidence_level: str,
    blockers: Sequence[str],
    coverage: Mapping[str, object],
    input_sha256: str,
) -> dict[str, object]:
    """Run the full low-suction evidence protocol without writing or fetching data."""

    normalized_blockers = tuple(sorted({str(value) for value in blockers if str(value)}))
    report: dict[str, object] = {
        "research_version": "low-suction-daily-factor-comprehensive-v4",
        "evidence_level": evidence_level,
        "input_sha256": input_sha256,
        "coverage": dict(coverage),
        "blockers": list(normalized_blockers),
    }
    if normalized_blockers:
        report.update(
            {
                "status": "blocked",
                "conclusion": "data_blocker",
                "case_audit": [],
                "time_split": None,
                "families": {setup_type: _FamilyAccumulator.create().render() for setup_type in SETUP_TYPES},
                "research_answers": [],
                "qualified_rules": [],
            }
        )
        report["research_answers"] = build_comprehensive_research_answers(report)
        return report

    calendar = _strict_calendar(market_calendar)
    try:
        cases = audit_personal_cases(bars, calendar)
        summary = summarize_comprehensive_observations(
            _iter_observations(bars, calendar, security_status),
            calendar,
        )
    except DailyFactorInputError as exc:
        report.update(
            {
                "status": "blocked",
                "conclusion": "data_blocker",
                "blockers": [*normalized_blockers, str(exc)],
                "case_audit": [],
                "time_split": None,
                "families": {setup_type: _FamilyAccumulator.create().render() for setup_type in SETUP_TYPES},
                "research_answers": [],
                "qualified_rules": [],
            }
        )
        report["research_answers"] = build_comprehensive_research_answers(report)
        return report

    _attach_case_band_membership(cases, summary["families"])
    conclusion, status = (
        ("exploratory_only", "exploratory_complete")
        if evidence_level != "strict"
        else ("no_qualified_strategy", "complete")
    )
    report.update(
        {
            "status": status,
            "conclusion": conclusion,
            "case_audit": cases,
            "time_split": summary["time_split"],
            "families": summary["families"],
            "research_answers": [],
            "qualified_rules": [],
        }
    )
    report["research_answers"] = build_comprehensive_research_answers(report)
    return report


def render_comprehensive_daily_factor_json(report: Mapping[str, object]) -> str:
    """Render stable machine-readable comprehensive evidence."""

    return json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"


def build_comprehensive_research_answers(
    report: Mapping[str, object],
) -> list[dict[str, str]]:
    """Derive bounded research answers from an already-computed report."""

    evidence_level = str(report.get("evidence_level") or "unknown")
    blockers = report.get("blockers")
    blocked = bool(blockers) or str(report.get("status") or "") == "blocked"
    cases = report.get("case_audit")
    families = report.get("families")
    return _research_answers(
        evidence_level,
        blocked=blocked,
        cases=cases if isinstance(cases, Sequence) else (),
        families=families if isinstance(families, Mapping) else {},
    )


def render_comprehensive_daily_factor_markdown(report: Mapping[str, object]) -> str:
    """Render the requested human-readable evidence without promoting a rule."""

    lines = [
        "# 日线低吸综合研究",
        "",
        f"- 研究版本：`{report.get('research_version', '-')}`",
        f"- 输入 SHA256：`{report.get('input_sha256', '-')}`",
        f"- 证据等级：`{report.get('evidence_level', '-')}`",
        f"- 结论：`{report.get('conclusion', '-')}`",
    ]
    if report.get("conclusion") == "exploratory_only":
        lines.append("- 说明：当前数据已完成探索研究，但不复权输入不能升级为正式策略结论。")
    coverage = report.get("coverage")
    if isinstance(coverage, Mapping):
        price_basis = coverage.get("price_basis")
        if price_basis:
            lines.append(f"- 价格口径：`{price_basis}`")
        raw_prices = coverage.get("raw_unadjusted_prices")
        if isinstance(raw_prices, Mapping) and raw_prices.get("warning"):
            lines.append(f"- 原始日线限制：`{raw_prices['warning']}`")
    blockers = report.get("blockers")
    if blockers:
        lines.extend(["", "## 数据门禁", ""])
        lines.extend(f"- `{value}`" for value in blockers)
    _render_case_audit(lines, report.get("case_audit"))
    families = report.get("families")
    if isinstance(families, Mapping):
        for setup_type in SETUP_TYPES:
            family = families.get(setup_type)
            if isinstance(family, Mapping):
                _render_family(lines, setup_type, family)
    answers = report.get("research_answers")
    if isinstance(answers, Sequence):
        lines.extend(["", "## 研究问题结论", ""])
        lines.append("| 问题 | 状态 | 说明 |")
        lines.append("| --- | --- | --- |")
        for answer in answers:
            if isinstance(answer, Mapping):
                lines.append(
                    "| {question} | `{status}` | {detail} |".format(
                        question=answer.get("question", "-"),
                        status=answer.get("status", "-"),
                        detail=answer.get("detail", "-"),
                    )
                )
    return "\n".join(lines) + "\n"


@dataclass
class _FamilyAccumulator:
    overall: _OutcomeAccumulator
    daily: dict[date, _OutcomeAccumulator]
    stocks: dict[str, _OutcomeAccumulator]
    conditions: dict[tuple[str, str], _OutcomeAccumulator]
    interactions: dict[tuple[tuple[str, ...], tuple[str, ...]], _OutcomeAccumulator]
    score_segments: dict[str, dict[str, dict[str, _OutcomeAccumulator]]]
    exits: dict[str, _ExitAccumulator]
    exit_segments: dict[tuple[str, str], _ExitAccumulator]
    exit_conditions: dict[tuple[str, str, str], _ExitAccumulator]
    worst_heap: list[tuple[float, int, dict[str, object]]]
    label_excluded_main_board_price_limit_count: int = 0
    observation_index: int = 0

    @classmethod
    def create(cls) -> _FamilyAccumulator:
        return cls(
            overall=_OutcomeAccumulator(),
            daily=defaultdict(_OutcomeAccumulator),
            stocks=defaultdict(_OutcomeAccumulator),
            conditions=defaultdict(_OutcomeAccumulator),
            interactions=defaultdict(_OutcomeAccumulator),
            score_segments={
                variant: {
                    segment: {band: _OutcomeAccumulator() for _, _, band in SCORE_BANDS}
                    for segment in ("development", "validation", "holdout")
                }
                for variant in SCORE_VARIANTS
            },
            exits=defaultdict(_ExitAccumulator),
            exit_segments=defaultdict(_ExitAccumulator),
            exit_conditions=defaultdict(_ExitAccumulator),
            worst_heap=[],
        )

    def add(
        self,
        observation: Mapping[str, object],
        segments: Mapping[date, str],
    ) -> None:
        trade_date = _required_date(observation.get("trade_date"))
        symbol = str(observation.get("vt_symbol") or "").strip().upper()
        label = _number_or_none(observation.get("d1_close_return_pct"))
        label_status = str(observation.get("d1_label_status") or "available")
        if label_status == "label_excluded_main_board_price_limit":
            self.label_excluded_main_board_price_limit_count += 1
            return
        outcome_kwargs = {
            "d1_limit_up_touch": _boolean_or_none(
                observation.get("d1_limit_up_touch")
            ),
            "d1_fresh_limit_up_touch_proxy": _boolean_or_none(
                observation.get("d1_fresh_limit_up_touch_proxy")
            ),
            "d1_limit_up_close_proxy": _boolean_or_none(
                observation.get("d1_limit_up_close_proxy")
            ),
            "d1_fresh_limit_up_close_proxy": _boolean_or_none(
                observation.get("d1_fresh_limit_up_close_proxy")
            ),
        }
        self.overall.add(trade_date, label, label_status, **outcome_kwargs)
        self.daily[trade_date].add(trade_date, label, label_status, **outcome_kwargs)
        if symbol:
            self.stocks[symbol].add(trade_date, label, label_status, **outcome_kwargs)
        state = observation.get("state")
        if isinstance(state, Mapping):
            for dimension, value in state.items():
                self.conditions[(str(dimension), str(value))].add(
                    trade_date,
                    label,
                    label_status,
                    **outcome_kwargs,
                )
            for dimensions in _interaction_dimensions(state):
                values = tuple(str(state[dimension]) for dimension in dimensions)
                self.interactions[(dimensions, values)].add(
                    trade_date,
                    label,
                    label_status,
                    **outcome_kwargs,
                )
        segment = segments.get(trade_date)
        scores = observation.get("scores")
        if segment is not None and isinstance(scores, Mapping):
            for variant in SCORE_VARIANTS:
                score = _number_or_none(scores.get(variant))
                if score is not None:
                    self.score_segments[variant][segment][_score_band(score)].add(
                        trade_date,
                        label,
                        label_status,
                        **outcome_kwargs,
                    )
        if label is not None:
            self._record_worst(observation, label)
        exits = observation.get("exit_outcomes")
        if isinstance(exits, Sequence):
            condition = _primary_exit_condition(state)
            for outcome in exits:
                if not isinstance(outcome, Mapping):
                    continue
                probe = str(outcome.get("probe") or "")
                if not probe:
                    continue
                self.exits[probe].add(outcome)
                if segment is not None:
                    self.exit_segments[(probe, segment)].add(outcome)
                self.exit_conditions[(probe, *condition)].add(outcome)

    def _record_worst(self, observation: Mapping[str, object], label: float) -> None:
        self.observation_index += 1
        row = {
            "vt_symbol": str(observation.get("vt_symbol") or ""),
            "trade_date": _required_date(observation.get("trade_date")),
            "d1_close_return_pct": label,
            "scores": dict(observation.get("scores") or {}),
            "state": dict(observation.get("state") or {}),
            "feature_snapshot": dict(observation.get("feature_snapshot") or {}),
            "d1_limit_up_touch": _boolean_or_none(
                observation.get("d1_limit_up_touch")
            ),
            "d1_fresh_limit_up_touch_proxy": _boolean_or_none(
                observation.get("d1_fresh_limit_up_touch_proxy")
            ),
            "d1_limit_up_close_proxy": _boolean_or_none(
                observation.get("d1_limit_up_close_proxy")
            ),
            "d1_fresh_limit_up_close_proxy": _boolean_or_none(
                observation.get("d1_fresh_limit_up_close_proxy")
            ),
        }
        item = (-label, self.observation_index, row)
        if len(self.worst_heap) < MAX_WORST_OBSERVATIONS:
            heapq.heappush(self.worst_heap, item)
        elif item[0] > self.worst_heap[0][0]:
            heapq.heapreplace(self.worst_heap, item)

    def render(self) -> dict[str, object]:
        overall = {
            **self.overall.summary(),
            "label_excluded_main_board_price_limit_count": self.label_excluded_main_board_price_limit_count,
        }
        daily = [
            {"trade_date": value.isoformat(), **accumulator.summary()}
            for value, accumulator in sorted(self.daily.items())
        ]
        stocks = [
            {"vt_symbol": symbol, **accumulator.summary()}
            for symbol, accumulator in self.stocks.items()
            if accumulator.values and float(accumulator.summary()["d1_mean_return_pct"] or 0) < 0
        ]
        conditions = [
            {"dimension": dimension, "value": value, **accumulator.summary()}
            for (dimension, value), accumulator in self.conditions.items()
        ]
        interactions = [
            {
                "dimensions": list(dimensions),
                "state": dict(zip(dimensions, values, strict=True)),
                **accumulator.summary(),
            }
            for (dimensions, values), accumulator in self.interactions.items()
        ]
        score_variants = {
            variant: _render_score_variant(segments)
            for variant, segments in self.score_segments.items()
        }
        exits = [
            {"probe": probe, **accumulator.summary()}
            for probe, accumulator in sorted(self.exits.items())
        ]
        exit_by_segment = [
            {"probe": probe, "segment": segment, **accumulator.summary()}
            for (probe, segment), accumulator in sorted(self.exit_segments.items())
        ]
        exit_by_condition = [
            {
                "probe": probe,
                "condition_dimension": dimension,
                "condition_value": value,
                **accumulator.summary(),
            }
            for (probe, dimension, value), accumulator in sorted(self.exit_conditions.items())
        ]
        worst = [item[2] for item in sorted(self.worst_heap, key=lambda item: item[2]["d1_close_return_pct"])]
        return {
            "overall": overall,
            "daily_outcomes": daily,
            "worst_days": [
                row
                for row in daily
                if row["d1_mean_return_pct"] is not None
                and float(row["d1_mean_return_pct"]) < 0
            ],
            "worst_stocks": sorted(
                stocks,
                key=lambda row: (
                    float(row["d1_mean_return_pct"] or 0),
                    str(row["vt_symbol"]),
                ),
            ),
            "condition_outcomes": sorted(
                conditions,
                key=lambda row: (
                    str(row["dimension"]),
                    str(row["value"]),
                ),
            ),
            "interaction_outcomes": sorted(
                interactions,
                key=lambda row: (
                    tuple(str(value) for value in row["dimensions"]),
                    tuple(
                        str(value)
                        for _, value in sorted(
                            dict(row["state"]).items()
                        )
                    ),
                ),
            ),
            "failure_attribution": _failure_attribution_rows(
                self.conditions,
                self.interactions,
                self.overall.summary(),
            ),
            "score_variants": score_variants,
            "negative_observations": worst,
            "exit_probes": exits,
            "exit_by_segment": exit_by_segment,
            "exit_by_condition": exit_by_condition,
        }


def _interaction_dimensions(
    state: Mapping[str, object],
) -> tuple[tuple[str, ...], ...]:
    if "ma10_ma20_state" in state:
        setup_type = "oversold_rebound"
    elif "support_line" in state:
        setup_type = "trend_pullback"
    else:
        return ()
    return tuple(
        dimensions
        for dimensions in INTERACTION_DIMENSIONS[setup_type]
        if all(dimension in state for dimension in dimensions)
    )


def _failure_attribution_rows(
    conditions: Mapping[tuple[str, str], _OutcomeAccumulator],
    interactions: Mapping[
        tuple[tuple[str, ...], tuple[str, ...]],
        _OutcomeAccumulator,
    ],
    family_summary: Mapping[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (dimension, value), accumulator in conditions.items():
        summary = accumulator.summary()
        if not summary["negative_count"]:
            continue
        rows.append(
            _failure_attribution_row(
                source="condition",
                dimensions=(dimension,),
                state={dimension: value},
                summary=summary,
                family_summary=family_summary,
            )
        )
    for (dimensions, values), accumulator in interactions.items():
        summary = accumulator.summary()
        if not summary["negative_count"]:
            continue
        rows.append(
            _failure_attribution_row(
                source="interaction",
                dimensions=dimensions,
                state=dict(zip(dimensions, values, strict=True)),
                summary=summary,
                family_summary=family_summary,
            )
        )
    return sorted(
        rows,
        key=lambda row: (
            -float(row["negative_rate_delta_vs_family_pct"] or 0),
            float(row["d1_mean_delta_vs_family_pct"] or 0),
            -float(row["negative_rate_pct"] or 0),
            -int(row["sample_count"]),
            str(row["source"]),
            tuple(str(value) for value in row["dimensions"]),
        ),
    )


def _failure_attribution_row(
    *,
    source: str,
    dimensions: tuple[str, ...],
    state: dict[str, str],
    summary: Mapping[str, object],
    family_summary: Mapping[str, object],
) -> dict[str, object]:
    sample_count = int(summary["sample_count"] or 0)
    family_sample_count = int(family_summary.get("sample_count") or 0)
    return {
        "source": source,
        "dimensions": list(dimensions),
        "state": state,
        "candidate_count": summary["candidate_count"],
        "sample_count": sample_count,
        "sample_share_pct": _rate_pct(sample_count, family_sample_count),
        "negative_count": summary["negative_count"],
        "negative_rate_pct": summary["negative_rate_pct"],
        "negative_rate_delta_vs_family_pct": _difference_or_none(
            summary["negative_rate_pct"],
            family_summary.get("negative_rate_pct"),
        ),
        "negative_mean_return_pct": summary["negative_mean_return_pct"],
        "d1_mean_return_pct": summary["d1_mean_return_pct"],
        "d1_mean_delta_vs_family_pct": _difference_or_none(
            summary["d1_mean_return_pct"],
            family_summary.get("d1_mean_return_pct"),
        ),
        "win_rate_pct": summary["win_rate_pct"],
    }


def _iter_observations(
    bars: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
) -> Iterable[dict[str, object]]:
    histories = _group_histories(bars)
    calendar_positions = {value: index for index, value in enumerate(calendar)}
    eligible_pairs = _eligible_security_pairs(security_status, calendar)
    for symbol, history in histories.items():
        dates = tuple(_required_date(row.get("trade_date")) for row in history)
        bars_by_date = {
            trade_date: history[index]
            for index, trade_date in enumerate(dates)
        }
        closes = {
            trade_date: _number_or_none(history[index].get("close_price"))
            for index, trade_date in enumerate(dates)
        }
        ma_by_date = _future_ma_by_date(history)
        for position in daily_factor_candidate_positions(history):
            trade_date = dates[position]
            if trade_date not in calendar_positions:
                continue
            if eligible_pairs and (symbol, trade_date) not in eligible_pairs:
                continue
            features = build_daily_features(daily_factor_history_window(history, position))
            setup_type = classify_daily_setup(features)
            if setup_type not in SETUP_TYPES:
                continue
            label, label_status = _causal_d1_label(
                closes,
                calendar,
                calendar_positions,
                symbol,
                trade_date,
                eligible_pairs,
            )
            state = (
                classify_oversold_state(features)
                if setup_type == "oversold_rebound"
                else classify_trend_state(features)
            )
            entry_price = _required_positive_number(features.get("close_price"), "close_price")
            d1_trade_date = _next_calendar_date(
                calendar,
                calendar_positions,
                trade_date,
            )
            d1_touch_proxy = classify_d1_limit_up_touch_proxy(
                signal_bar=history[position],
                d1_bar=bars_by_date.get(d1_trade_date) if d1_trade_date else None,
                prior_signal_bar=history[position - 1] if position else None,
            )
            future = _future_exit_bars(
                bars_by_date=bars_by_date,
                ma_by_date=ma_by_date,
                calendar=calendar,
                calendar_position=calendar_positions[trade_date],
            )
            candidate = {
                "entry_date": trade_date,
                "entry_price": entry_price,
                "setup_type": setup_type,
            }
            exit_outcomes = tuple(
                evaluate_close_exit_probe(candidate, future, probe=probe)
                for probe in EXIT_PROBES[setup_type]
            )
            yield {
                "setup_type": setup_type,
                "vt_symbol": symbol,
                "trade_date": trade_date,
                "entry_date": trade_date,
                "entry_price": entry_price,
                "d1_close_return_pct": label,
                "d1_label_status": label_status,
                "scores": score_factor_variants(features),
                "state": state,
                "feature_snapshot": _feature_snapshot(features),
                "exit_outcomes": exit_outcomes,
                **d1_touch_proxy,
            }


def _render_score_variant(
    segments: Mapping[str, Mapping[str, _OutcomeAccumulator]],
) -> dict[str, object]:
    rendered = {
        segment: [
            {"band": band, **accumulator.summary()}
            for _, _, band in SCORE_BANDS
            for accumulator in (segments[segment][band],)
        ]
        for segment in ("development", "validation", "holdout")
    }
    development = rendered["development"]
    eligible = [row for row in development if row["d1_mean_return_pct"] is not None]
    selected = max(
        eligible,
        key=lambda row: (
            float(row["d1_mean_return_pct"]),
            float(row["win_rate_pct"] or 0),
            int(row["sample_count"]),
        ),
    ) if eligible else None
    selected_band = selected["band"] if selected is not None else None
    return {
        **rendered,
        "selection": {
            "selected_band": selected_band,
            "development": selected,
            "validation": _band_row(rendered["validation"], selected_band),
            "holdout": _band_row(rendered["holdout"], selected_band),
        },
    }


def _band_row(rows: Sequence[Mapping[str, object]], band: object) -> Mapping[str, object] | None:
    return next((row for row in rows if row.get("band") == band), None)


def _future_ma_by_date(history: Sequence[Mapping[str, object]]) -> dict[date, dict[str, float | None]]:
    closes = [_required_positive_number(row.get("close_price"), "close_price") for row in history]
    result: dict[date, dict[str, float | None]] = {}
    for index, row in enumerate(history):
        result[_required_date(row.get("trade_date"))] = {
            "ma5": _trailing_average(closes, index, 5),
            "ma10": _trailing_average(closes, index, 10),
        }
    return result


def _future_exit_bars(
    *,
    bars_by_date: Mapping[date, Mapping[str, object]],
    ma_by_date: Mapping[date, Mapping[str, float | None]],
    calendar: Sequence[date],
    calendar_position: int,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for offset in range(1, MAX_EXIT_HOLDING_SESSIONS + 1):
        target_position = calendar_position + offset
        if target_position >= len(calendar):
            break
        trade_date = calendar[target_position]
        source = bars_by_date.get(trade_date)
        ma = ma_by_date.get(trade_date, {})
        rows.append(
            {
                "trade_date": trade_date,
                "close_price": source.get("close_price") if source else None,
                "ma5": ma.get("ma5"),
                "ma10": ma.get("ma10"),
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
        if str(row.get("board") or "").lower() != "main":
            continue
        if str(row.get("status") or "").upper() == "DELISTED":
            continue
        if bool(row.get("suspended")) or bool(row.get("risk_warning")):
            continue
        listed_on = _required_date(row.get("listed_on"))
        if positions[trade_date] - _calendar_position(calendar, listed_on) < 60:
            continue
        eligible.add((symbol, trade_date))
    return eligible


def _calendar_position(calendar: Sequence[date], value: date) -> int:
    return next((index for index, item in enumerate(calendar) if item >= value), len(calendar))


def _next_calendar_date(
    calendar: Sequence[date],
    positions: Mapping[date, int],
    trade_date: date,
) -> date | None:
    position = positions.get(trade_date)
    if position is None or position + 1 >= len(calendar):
        return None
    return calendar[position + 1]


def _attach_case_band_membership(
    cases: list[dict[str, object]],
    families: Mapping[str, object],
) -> None:
    for case in cases:
        expected = str(case.get("expected_setup_type") or "")
        family = families.get(expected)
        scores = case.get("scores")
        if not isinstance(family, Mapping) or not isinstance(scores, Mapping):
            continue
        variants = family.get("score_variants")
        if not isinstance(variants, Mapping):
            continue
        membership: dict[str, object] = {}
        for variant in SCORE_VARIANTS:
            details = variants.get(variant)
            score = _number_or_none(scores.get(variant))
            selected = details.get("selection", {}).get("selected_band") if isinstance(details, Mapping) else None
            membership[variant] = {
                "score_band": _score_band(score) if score is not None else None,
                "development_selected_band": selected,
                "matches_development_selected_band": (
                    score is not None and _score_band(score) == selected
                ),
            }
        case["score_band_membership"] = membership


def _render_case_audit(lines: list[str], value: object) -> None:
    if not isinstance(value, Sequence):
        return
    lines.extend(["", "## 个人案例核查", ""])
    lines.append(
        "| 样例 | 日期 | 预期 | 源低吸锚点 | 源形态命中 | 必须过程规则/缺失 | 收盘回测代理 | 静态实际 | 案例结果 | 全部过程探针 | D+1 | 状态 | 叙述/时间线 | 形态状态 | 全部硬条件 | 未通过硬条件 | 分数 | 分数桶归属 | D+1 日线触板/新鲜触板代理；收盘涨停/新鲜收盘涨停代理 |"
    )
    lines.append(
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- |"
    )
    for row in value:
        if not isinstance(row, Mapping):
            continue
        lines.append(
            "| {name} | {trade_date} | {expected} | {anchor} | {geometry} | {required_process} | {close_entry} | {actual} | {case_match} | {process_rules} | {d1} | {status} | {narrative} | {state} | {predicates} | {failed_predicates} | {scores} | {membership} | {touch_proxy} |".format(
                name=row.get("name", "-"),
                trade_date=_date_text(row.get("trade_date")),
                expected=row.get("expected_setup_type", "-"),
                anchor=row.get("source_anchor", "-"),
                geometry=row.get("source_geometry_matched", False),
                required_process=_markdown_cell(
                    {
                        "required": row.get("required_process_rule_keys"),
                        "matched": row.get("required_process_matched"),
                        "missing": row.get("missing_required_process_rule_keys"),
                        "failed_predicates": row.get(
                            "failed_required_process_predicates"
                        ),
                    }
                ),
                close_entry=_markdown_cell(
                    {
                        "eligible": row.get("close_only_backtest_eligible"),
                        "price": row.get("close_entry_price"),
                        "distance_to_anchor_pct": row.get(
                            "close_entry_anchor_distance_pct"
                        ),
                    }
                ),
                actual=row.get("setup_type", "-"),
                case_match=row.get("case_match_status", "-"),
                process_rules=_markdown_cell(row.get("process_probe_rule_keys")),
                d1=_number_text(row.get("d1_close_return_pct")),
                status=row.get("data_status", "-"),
                narrative="{source}/{timeline}".format(
                    source=row.get("narrative_status", "-"),
                    timeline=row.get("narrative_timeline_status", "-"),
                ),
                state=_markdown_cell(row.get("state")),
                predicates=_markdown_cell(row.get("predicate_results")),
                failed_predicates=_markdown_cell(row.get("failed_predicates")),
                scores=_markdown_cell(row.get("scores")),
                membership=_markdown_cell(row.get("score_band_membership")),
                touch_proxy=_markdown_cell(
                    {
                        "touch": row.get("d1_limit_up_touch"),
                        "fresh_touch_proxy": row.get(
                            "d1_fresh_limit_up_touch_proxy"
                        ),
                        "touch_status": row.get("d1_limit_up_touch_status"),
                        "close_proxy": row.get("d1_limit_up_close_proxy"),
                        "fresh_close_proxy": row.get(
                            "d1_fresh_limit_up_close_proxy"
                        ),
                        "close_status": row.get(
                            "d1_limit_up_close_proxy_status"
                        ),
                    }
                ),
            )
        )
    _render_case_narrative_evidence(lines, value)


def _render_case_narrative_evidence(lines: list[str], value: Sequence[object]) -> None:
    for row in value:
        if not isinstance(row, Mapping):
            continue
        timeline = row.get("narrative_timeline")
        checks = row.get("narrative_checks")
        launch = row.get("launch_observation")
        if not isinstance(timeline, Sequence) and not isinstance(launch, Mapping):
            continue
        lines.extend(["", f"### {row.get('name', '-')} 因果日线时间线", ""])
        lines.append(
            "- 时间线状态：`{status}`；信号快照只使用至 `{through}`。".format(
                status=row.get("narrative_timeline_status", "-"),
                through=_date_text(row.get("observed_through")),
            )
        )
        lines.append(
            "- 源低吸锚点：`{anchor}`，形态命中：`{geometry}`；收盘回测代理：`{close_eligible}`，收盘价 `{close_price}`，距锚点 `{distance}`%。".format(
                anchor=row.get("source_anchor", "-"),
                geometry=row.get("source_geometry_matched", False),
                close_eligible=row.get("close_only_backtest_eligible", False),
                close_price=_number_text(row.get("close_entry_price")),
                distance=_number_text(row.get("close_entry_anchor_distance_pct")),
            )
        )
        lines.append(
            "- 必须过程规则：{required}；缺失：{missing}。".format(
                required=_markdown_cell(row.get("required_process_rule_keys")),
                missing=_markdown_cell(row.get("missing_required_process_rule_keys")),
            )
        )
        if isinstance(checks, Mapping):
            lines.append(f"- 叙述检查：{_markdown_cell(checks)}")
        process_features = row.get("process_feature_snapshot")
        if isinstance(process_features, Mapping):
            lines.append(
                "- 过程特征：{features}；命中过程探针：{rules}。".format(
                    features=_markdown_cell(process_features),
                    rules=_markdown_cell(row.get("process_probe_rule_keys")),
                )
            )
        if isinstance(launch, Mapping):
            lines.append(
                "- 启动日观察（后验核查，不参与候选或因子评分）：{launch}".format(
                    launch=_markdown_cell(launch),
                )
            )
        if isinstance(timeline, Sequence):
            _render_case_timeline_rows(lines, timeline)


def _render_case_timeline_rows(lines: list[str], timeline: Sequence[object]) -> None:
    rows = [row for row in timeline if isinstance(row, Mapping)]
    if not rows:
        return
    headers = list(rows[0].keys())
    lines.extend(["", "#### 日线明细", ""])
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append(
            "| "
            + " | ".join(_markdown_cell(row.get(header)) for header in headers)
            + " |"
        )


def _render_family(lines: list[str], setup_type: str, family: Mapping[str, object]) -> None:
    overall = family.get("overall")
    lines.extend(["", f"## {setup_type}", ""])
    if isinstance(overall, Mapping):
        lines.append(
            "- 全部候选：{samples} 个标签，胜率 {win}%，D+1 均值 {mean}%，日均候选 {daily}。".format(
                samples=overall.get("sample_count", 0),
                win=_number_text(overall.get("win_rate_pct")),
                mean=_number_text(overall.get("d1_mean_return_pct")),
                daily=_number_text(overall.get("daily_candidate_average")),
            )
        )
        lines.append(
            "- 主板 10% 涨跌停边界外 D+1 标签剔除：{count}。".format(
                count=overall.get(
                    "label_excluded_main_board_price_limit_count",
                    0,
                )
            )
        )
        lines.append(
            "- D+1 日线高价触板代理：{touch_count}/{touch_available}（{touch_rate}%）；"
            "新鲜高价触板代理：{fresh_count}/{fresh_available}（{fresh_rate}%）；"
            "收盘涨停代理：{close_count}/{close_available}（{close_rate}%）；"
            "新鲜收盘涨停代理：{fresh_close_count}/{fresh_close_available}（{fresh_close_rate}%）。"
            "它们是日线描述性代理，不是正式首板或可成交结论。".format(
                touch_count=overall.get("d1_limit_up_touch_count", 0),
                touch_available=overall.get("d1_limit_up_touch_available_count", 0),
                touch_rate=_number_text(overall.get("d1_limit_up_touch_rate_pct")),
                fresh_count=overall.get(
                    "d1_fresh_limit_up_touch_proxy_count",
                    0,
                ),
                fresh_available=overall.get(
                    "d1_fresh_limit_up_touch_proxy_available_count",
                    0,
                ),
                fresh_rate=_number_text(
                    overall.get("d1_fresh_limit_up_touch_proxy_rate_pct")
                ),
                close_count=overall.get("d1_limit_up_close_proxy_count", 0),
                close_available=overall.get(
                    "d1_limit_up_close_proxy_available_count",
                    0,
                ),
                close_rate=_number_text(
                    overall.get("d1_limit_up_close_proxy_rate_pct")
                ),
                fresh_close_count=overall.get(
                    "d1_fresh_limit_up_close_proxy_count",
                    0,
                ),
                fresh_close_available=overall.get(
                    "d1_fresh_limit_up_close_proxy_available_count",
                    0,
                ),
                fresh_close_rate=_number_text(
                    overall.get("d1_fresh_limit_up_close_proxy_rate_pct")
                ),
            )
        )
    variants = family.get("score_variants")
    if isinstance(variants, Mapping):
        lines.extend(["", "### 分数与时间外结果", ""])
        lines.append("| 变体 | 开发期选定桶 | 验证 D+1 | 留出 D+1 |")
        lines.append("| --- | --- | ---: | ---: |")
        for variant in SCORE_VARIANTS:
            details = variants.get(variant)
            selection = details.get("selection") if isinstance(details, Mapping) else None
            validation = selection.get("validation") if isinstance(selection, Mapping) else None
            holdout = selection.get("holdout") if isinstance(selection, Mapping) else None
            lines.append(
                "| {variant} | {band} | {validation} | {holdout} |".format(
                    variant=variant,
                    band=selection.get("selected_band", "-") if isinstance(selection, Mapping) else "-",
                    validation=_number_text(validation.get("d1_mean_return_pct") if isinstance(validation, Mapping) else None),
                    holdout=_number_text(holdout.get("d1_mean_return_pct") if isinstance(holdout, Mapping) else None),
                )
            )
    _render_summary_rows(lines, "条件结果", family.get("condition_outcomes"), limit=None)
    _render_summary_rows(lines, "预登记交叉条件", family.get("interaction_outcomes"), limit=None)
    _render_summary_rows(lines, "逐交易日结果", family.get("daily_outcomes"), limit=None)
    _render_summary_rows(lines, "差的交易日", family.get("worst_days"), limit=MAX_WORST_DAYS_IN_MARKDOWN)
    _render_summary_rows(lines, "差的股票", family.get("worst_stocks"), limit=MAX_WORST_STOCKS_IN_MARKDOWN)
    _render_summary_rows(lines, "失败归因（相对因子总体）", family.get("failure_attribution"), limit=MAX_WORST_STOCKS_IN_MARKDOWN)
    _render_summary_rows(lines, "卖点代理", family.get("exit_probes"), limit=None)
    _render_summary_rows(lines, "卖点代理按时间段", family.get("exit_by_segment"), limit=None)
    _render_summary_rows(lines, "卖点代理按条件", family.get("exit_by_condition"), limit=None)
    _render_summary_rows(lines, "最差个例", family.get("negative_observations"), limit=MAX_WORST_ROWS_IN_MARKDOWN)


def _render_summary_rows(lines: list[str], title: str, value: object, *, limit: int | None) -> None:
    if not isinstance(value, Sequence) or not value:
        return
    rows = [row for row in value if isinstance(row, Mapping)]
    if not rows:
        return
    if limit is not None:
        rows = rows[:limit]
    headers = list(rows[0].keys())
    lines.extend(["", f"### {title}", ""])
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        lines.append(
            "| " + " | ".join(_markdown_cell(row.get(header)) for header in headers) + " |"
        )


def _research_answers(
    evidence_level: str,
    *,
    blocked: bool,
    cases: Sequence[object],
    families: Mapping[str, object],
) -> list[dict[str, str]]:
    questions = (
        "个人样例与均线结论是否成立",
        "最佳分数区间是否成立",
        "超跌：M10贴近M20何时更容易D+1收益或日线触板",
        "超跌：M10/M20与M30贴合的交叉条件",
        "趋势：MA5还是MA10，低点触及还是收盘附近",
        "下跌位置还是小阳线低吸",
        "成交量附加因子何时有效",
        "差的股票和坏情况的归因",
        "两类低吸的卖点",
    )
    if blocked:
        return [
            {
                "question": question,
                "status": "insufficient_data",
                "detail": "输入门禁未满足，不能计算。",
            }
            for question in questions
        ]

    case_rows = [row for row in cases if isinstance(row, Mapping)]
    complete_cases = [
        row for row in case_rows if row.get("narrative_status") == "complete"
    ]
    baseline_matched_cases = [
        row for row in complete_cases if bool(row.get("expected_setup_matched"))
    ]
    case_model_matched_cases = [
        row for row in complete_cases if bool(row.get("case_model_matched"))
    ]
    incomplete_count = len(case_rows) - len(complete_cases)
    unavailable_labels = sum(
        row.get("data_status")
        in {"label_unavailable", "label_excluded_main_board_price_limit"}
        for row in case_rows
    )
    timeline_available_count = sum(
        row.get("narrative_timeline_status") == "available"
        for row in complete_cases
    )
    launch_available_count = sum(
        isinstance(row.get("launch_observation"), Mapping)
        and row["launch_observation"].get("status") == "available"
        for row in complete_cases
    )
    case_detail = (
        f"完整叙述样例中冻结静态类型命中 {len(baseline_matched_cases)}/{len(complete_cases)}，"
        f"加入过程探针后的案例模型命中 {len(case_model_matched_cases)}/{len(complete_cases)}；"
        f"{timeline_available_count}/{len(complete_cases)} 个有信号日前的因果时间线，"
        f"{launch_available_count}/{len(complete_cases)} 个有独立启动日观察；"
        f"{incomplete_count} 个样例叙述不完整，{unavailable_labels} 个没有严格 D+1 标签。"
    )

    oversold = _family_mapping(families, "oversold_rebound")
    trend = _family_mapping(families, "trend_pullback")
    score_detail = (
        "开发期选桶及留出段 D+1："
        f"超跌 base {_selected_band_text(oversold, 'base')}，"
        f"超跌+量 {_selected_band_text(oversold, 'with_volume')}；"
        f"趋势 base {_selected_band_text(trend, 'base')}，"
        f"趋势+量 {_selected_band_text(trend, 'with_volume')}。"
    )
    oversold_m10_m20_detail = (
        "MA10/20 贴合 + 弱势/下跌 + 梯形缩量："
        + _interaction_outcome_text(
            oversold,
            ("ma10_ma20_state", "price_state", "volume_shape"),
            {
                "ma10_ma20_state": "near_or_crossed",
                "price_state": "weak_or_down",
                "volume_shape": "staircase_shrink",
            },
        )
    )
    oversold_m30_detail = (
        "MA10/M30 与 MA20/M30 同时贴合："
        + _interaction_outcome_text(
            oversold,
            ("ma10_ma30_state", "ma20_ma30_state"),
            {
                "ma10_ma30_state": "near_or_crossed",
                "ma20_ma30_state": "near_or_crossed",
            },
        )
    )
    support_detail = (
        "MA5 低点触及："
        + _interaction_outcome_text(
            trend,
            ("support_line", "support_touch"),
            {"support_line": "ma5", "support_touch": "low_touch"},
        )
        + "；MA10 低点触及："
        + _interaction_outcome_text(
            trend,
            ("support_line", "support_touch"),
            {"support_line": "ma10", "support_touch": "low_touch"},
        )
        + "；MA5 收盘附近："
        + _interaction_outcome_text(
            trend,
            ("support_line", "support_touch"),
            {"support_line": "ma5", "support_touch": "close_near"},
        )
    )
    price_detail = (
        "超跌弱势/下跌 D+1 "
        f"{_condition_mean_text(oversold, 'price_state', 'weak_or_down')}%，"
        "小阳 D+1 "
        f"{_condition_mean_text(oversold, 'price_state', 'small_positive')}%。"
    )
    volume_detail = (
        "梯形缩量 D+1 "
        f"{_condition_mean_text(oversold, 'volume_shape', 'staircase_shrink')}%，"
        "梯形放量 D+1 "
        f"{_condition_mean_text(oversold, 'volume_shape', 'staircase_expand')}%，"
        "混合量能 D+1 "
        f"{_condition_mean_text(oversold, 'volume_shape', 'mixed')}%。"
    )
    failure_detail = (
        "按预登记状态/交叉状态聚合的描述性失败归因："
        f"超跌 {_failure_attribution_text(oversold)}；趋势 {_failure_attribution_text(trend)}。"
    )
    exit_detail = (
        "预登记 D5 收盘退出的全样本均值："
        f"超跌 {_exit_mean_text(oversold, 'd5_close')}%，"
        f"趋势 {_exit_mean_text(trend, 'd5_close')}%；"
        "没有按这些结果在留出段选择或接入卖点。"
    )
    limitation = (
        "当前为原始不复权探索，且冻结分数选桶的留出段为负，"
        "所以不支持形成正式交易规则。"
        if evidence_level != "strict"
        else "冻结验证未产生合格规则。"
    )
    details = (
        case_detail,
        score_detail,
        oversold_m10_m20_detail,
        oversold_m30_detail,
        support_detail,
        price_detail,
        volume_detail,
        failure_detail,
        exit_detail,
    )
    return [
        {
            "question": question,
            "status": "not_supported",
            "detail": f"{detail} {limitation}",
        }
        for question, detail in zip(questions, details, strict=True)
    ]


def _family_mapping(
    families: Mapping[str, object],
    setup_type: str,
) -> Mapping[str, object]:
    family = families.get(setup_type)
    return family if isinstance(family, Mapping) else {}


def _selected_band_text(family: Mapping[str, object], variant: str) -> str:
    variants = family.get("score_variants")
    details = variants.get(variant) if isinstance(variants, Mapping) else None
    selection = details.get("selection") if isinstance(details, Mapping) else None
    holdout = selection.get("holdout") if isinstance(selection, Mapping) else None
    band = selection.get("selected_band") if isinstance(selection, Mapping) else None
    mean = holdout.get("d1_mean_return_pct") if isinstance(holdout, Mapping) else None
    return f"{band or '-'} / {_number_text(mean)}%"


def _condition_mean_text(
    family: Mapping[str, object],
    dimension: str,
    value: str,
) -> str:
    rows = family.get("condition_outcomes")
    if not isinstance(rows, Sequence):
        return "-"
    row = next(
        (
            item
            for item in rows
            if isinstance(item, Mapping)
            and item.get("dimension") == dimension
            and item.get("value") == value
        ),
        None,
    )
    return _number_text(row.get("d1_mean_return_pct") if isinstance(row, Mapping) else None)


def _interaction_outcome_text(
    family: Mapping[str, object],
    dimensions: tuple[str, ...],
    state: Mapping[str, str],
) -> str:
    rows = family.get("interaction_outcomes")
    if not isinstance(rows, Sequence):
        return "无可用交叉样本"
    row = next(
        (
            item
            for item in rows
            if isinstance(item, Mapping)
            and list(item.get("dimensions") or []) == list(dimensions)
            and item.get("state") == dict(state)
        ),
        None,
    )
    if not isinstance(row, Mapping):
        return "无可用交叉样本"
    return (
        f"样本 {row.get('sample_count', 0)}，D+1 {_number_text(row.get('d1_mean_return_pct'))}%，"
        f"日线触板 {_number_text(row.get('d1_limit_up_touch_rate_pct'))}%，"
        f"新鲜触板代理 {_number_text(row.get('d1_fresh_limit_up_touch_proxy_rate_pct'))}%，"
        f"收盘涨停代理 {_number_text(row.get('d1_limit_up_close_proxy_rate_pct'))}%，"
        f"新鲜收盘涨停代理 {_number_text(row.get('d1_fresh_limit_up_close_proxy_rate_pct'))}%"
    )


def _failure_attribution_text(family: Mapping[str, object]) -> str:
    rows = family.get("failure_attribution")
    if not isinstance(rows, Sequence):
        return "无负收益归因样本"
    row = next((item for item in rows if isinstance(item, Mapping)), None)
    if not isinstance(row, Mapping):
        return "无负收益归因样本"
    return (
        f"{row.get('source')} {json.dumps(row.get('state'), ensure_ascii=False, sort_keys=True)}，"
        f"样本 {row.get('sample_count', 0)}（总体占比 "
        f"{_number_text(row.get('sample_share_pct'))}%），负收益率 "
        f"{_number_text(row.get('negative_rate_pct'))}%（较总体 "
        f"{_number_text(row.get('negative_rate_delta_vs_family_pct'))}%），D+1 "
        f"{_number_text(row.get('d1_mean_return_pct'))}%（较总体 "
        f"{_number_text(row.get('d1_mean_delta_vs_family_pct'))}%）"
    )


def _exit_mean_text(family: Mapping[str, object], probe: str) -> str:
    rows = family.get("exit_probes")
    if not isinstance(rows, Sequence):
        return "-"
    row = next(
        (
            item
            for item in rows
            if isinstance(item, Mapping) and item.get("probe") == probe
        ),
        None,
    )
    return _number_text(row.get("mean_return_pct") if isinstance(row, Mapping) else None)


def _feature_snapshot(features: Mapping[str, object]) -> dict[str, object]:
    fields = (
        "open_price", "close_price", "high_price", "low_price", "ma5", "ma10",
        "ma20", "ma30", "ma60", "daily_return_pct", "low_to_close_pct",
        "ma10_20_distance_pct", "ma20_30_distance_pct", "ma_cluster_spread_pct",
        "prior_bear_alignment_days", "bull_alignment_days", "trend_reference_line",
        "trend_low_to_reference_pct", "trend_close_to_reference_pct",
        "trend_pullback_depth_pct", "volume_spearman_5d", "volume_spearman_10d",
        "volume_down_streak", "volume_up_streak",
    )
    return {field: features.get(field) for field in fields}


def _case_data_status(
    trade_date: date,
    positions: Mapping[date, int],
    label_status: str,
) -> str:
    if trade_date not in positions:
        return "case_date_not_in_reliable_calendar"
    if label_status == "label_excluded_main_board_price_limit":
        return label_status
    return "available" if label_status == "available" else "label_unavailable"


def _missing_case_row(case: PersonalResearchCase, reason: str) -> dict[str, object]:
    return {
        "name": case.name,
        "vt_symbol": case.vt_symbol,
        "trade_date": case.trade_date,
        "observed_through": case.trade_date,
        "expected_setup_type": case.expected_setup_type,
        "setup_type": None,
        "expected_setup_matched": False,
        "process_probe_matched": False,
        "source_anchor": case.source_anchor,
        "source_geometry_matched": False,
        "required_process_rule_keys": list(case.required_process_rule_keys),
        "required_process_matched": False,
        "missing_required_process_rule_keys": list(case.required_process_rule_keys),
        "required_process_predicate_results": {},
        "failed_required_process_predicates": {
            rule_key: ["case_data_unavailable"]
            for rule_key in case.required_process_rule_keys
        },
        "case_model_matched": False,
        "case_match_status": reason,
        "narrative_status": case.narrative_status,
        "narrative_timeline_status": reason,
        "narrative_timeline": [],
        "narrative_checks": {"timeline_available": False},
        "launch_observation": {
            "expected_launch_date": case.expected_launch_date,
            "status": reason,
        },
        "data_status": reason,
        "d1_close_return_pct": None,
        "feature_snapshot": {},
        "state": {},
        "predicate_results": {},
        "failed_predicates": [],
        "process_probe_rule_keys": [],
        "close_only_backtest_eligible": False,
        "close_entry_price": None,
        "close_entry_anchor_distance_pct": None,
        "process_feature_snapshot": {},
        "scores": {},
        "score_band_membership": {},
        "d1_limit_up_touch": None,
        "d1_fresh_limit_up_touch_proxy": None,
        "d1_limit_up_close_proxy": None,
        "d1_fresh_limit_up_close_proxy": None,
        "d1_limit_up_touch_status": reason,
        "d1_fresh_limit_up_touch_proxy_status": reason,
        "d1_limit_up_close_proxy_status": reason,
        "d1_fresh_limit_up_close_proxy_status": reason,
    }


def _closed_exit(
    base: Mapping[str, object],
    *,
    trade_date: date,
    exit_price: float,
    holding_sessions: int,
    reason: str,
) -> dict[str, object]:
    entry_price = _required_positive_number(base.get("entry_price"), "entry_price")
    return {
        **base,
        "status": "closed",
        "exit_date": trade_date,
        "exit_price": exit_price,
        "return_pct": _round_pct((exit_price / entry_price - 1) * 100),
        "holding_sessions": holding_sessions,
        "exit_reason": reason,
    }


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


def _primary_exit_condition(state: object) -> tuple[str, str]:
    if not isinstance(state, Mapping):
        return "state", "unavailable"
    for key in ("support_line", "ma10_ma20_state", "price_state", "volume_shape"):
        if key in state:
            return key, str(state[key])
    return "state", "unavailable"


def _ma_relation(left: object, right: object, close_price: object) -> str:
    left_value = _number_or_none(left)
    right_value = _number_or_none(right)
    close_value = _number_or_none(close_price)
    if left_value is None or right_value is None or close_value is None or close_value <= 0:
        return "unavailable"
    distance = (left_value - right_value) / close_value * 100
    if abs(distance) <= NEAR_MA_DISTANCE_PCT:
        return "near_or_crossed"
    return "above" if distance > 0 else "below"


def _daily_price_state(value: object) -> str:
    number = _number_or_none(value)
    if number is None:
        return "unavailable"
    if number <= 0:
        return "weak_or_down"
    if number <= 1.5:
        return "small_positive"
    return "large_green"


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


def _yes_no(value: object) -> str:
    if value is None:
        return "unavailable"
    return "yes" if bool(value) else "no"


def _score_band(value: float) -> str:
    for lower, upper, label in SCORE_BANDS:
        if lower <= value <= upper:
            return label
    raise DailyFactorInputError("daily factor score is outside 0..100")


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
        history.sort(key=lambda row: _required_date(row.get("trade_date")))
    return dict(histories)


def _history_position(history: Sequence[Mapping[str, object]], value: date) -> int | None:
    return next(
        (
            index
            for index, row in enumerate(history)
            if _required_date(row.get("trade_date")) == value
        ),
        None,
    )


def _strict_calendar(values: Sequence[date]) -> tuple[date, ...]:
    calendar = tuple(sorted({_required_date(value) for value in values}))
    if len(calendar) < 10:
        raise DailyFactorInputError("market calendar is too short for comprehensive research")
    return calendar


def _trailing_average(values: Sequence[float], index: int, window: int) -> float | None:
    if index + 1 < window:
        return None
    return sum(values[index - window + 1 : index + 1]) / window


def _required_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError as exc:
            raise DailyFactorInputError(f"invalid trade date: {value}") from exc
    raise DailyFactorInputError("trade date is required")


def _required_positive_number(value: object, field: str) -> float:
    number = _number_or_none(value)
    if number is None or number <= 0:
        raise DailyFactorInputError(f"{field} must be a positive number")
    return number


def _number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _positive_number_or_none(value: object) -> float | None:
    number = _number_or_none(value)
    return number if number is not None and number > 0 else None


def _boolean_or_none(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


def _rate_pct(numerator: int, denominator: int) -> float | None:
    return _round_pct(numerator / denominator * 100) if denominator else None


def _difference_or_none(value: object, baseline: object) -> float | None:
    current_number = _number_or_none(value)
    baseline_number = _number_or_none(baseline)
    if current_number is None or baseline_number is None:
        return None
    return _round_pct(current_number - baseline_number)


def _unavailable_d1_limit_up_touch_proxy(reason: str) -> dict[str, object]:
    return {
        "d1_limit_up_touch": None,
        "d1_fresh_limit_up_touch_proxy": None,
        "d1_limit_up_close_proxy": None,
        "d1_fresh_limit_up_close_proxy": None,
        "d1_limit_up_touch_status": reason,
        "d1_fresh_limit_up_touch_proxy_status": reason,
        "d1_limit_up_close_proxy_status": reason,
        "d1_fresh_limit_up_close_proxy_status": reason,
    }


def _integer_or_none(value: object) -> int | None:
    number = _number_or_none(value)
    return int(number) if number is not None else None


def _round_pct(value: float) -> float:
    return round(value, 4)


def _date_text(value: object) -> str:
    return _required_date(value).isoformat() if value is not None else "-"


def _number_text(value: object) -> str:
    number = _number_or_none(value)
    return f"{number:.4f}" if number is not None else "-"


def _markdown_cell(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, Mapping):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).replace("|", "/")
    if isinstance(value, Sequence) and not isinstance(value, str):
        return json.dumps(list(value), ensure_ascii=False, default=str).replace("|", "/")
    return str(value).replace("|", "/") if value is not None else "-"
