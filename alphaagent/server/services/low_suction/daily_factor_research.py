"""Pure daily features for the isolated low-suction factor study."""

from __future__ import annotations

import json
import math
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from datetime import date, datetime
from statistics import fmean, median


MA_WINDOWS = (5, 10, 20, 30, 60)
TREND_SLOPE_LOOKBACK = 5
OVERSOLD_PRIOR_BEAR_LOOKBACK = 40
OVERSOLD_RECENT_EXCLUSION = 5
SCORE_BANDS = (
    (0.0, 39.999, "0-39"),
    (40.0, 59.999, "40-59"),
    (60.0, 79.999, "60-79"),
    (80.0, 100.0, "80-100"),
)
MIN_QUALIFICATION_SAMPLES = 30
MIN_QUALIFICATION_CANDIDATE_DAYS = 10
MAIN_BOARD_PRICE_LIMIT_RATE = Decimal("0.10")
PERSONAL_RESEARCH_CASES = (
    ("传智教育 MA10 回踩", "003032.SZSE", date(2026, 7, 22), "oversold_rebound"),
    ("传智教育 三线包裹", "003032.SZSE", date(2026, 7, 23), "oversold_rebound"),
    ("传智教育 MA10 向 MA30 收敛", "003032.SZSE", date(2026, 7, 24), "oversold_rebound"),
    ("一鸣食品 MA10 贴合 MA20", "605179.SSE", date(2026, 7, 15), "oversold_rebound"),
    ("立新能源 MA10 向 MA20 加速收敛", "001258.SZSE", date(2026, 7, 15), "oversold_rebound"),
    ("爱丽家居 MA10 回贴 MA30", "603221.SSE", date(2026, 7, 20), "oversold_rebound"),
    ("百花医药 M10/M20 两线包裹", "600721.SSE", date(2026, 7, 14), "oversold_rebound"),
    ("百花医药 三线包裹", "600721.SSE", date(2026, 7, 31), "oversold_rebound"),
    ("百花医药 向上踩稳", "600721.SSE", date(2026, 8, 3), "oversold_rebound"),
    ("国风新材 攻击实体守住", "000859.SZSE", date(2026, 8, 7), "oversold_rebound"),
    ("秦安股份 MA10 上穿 MA20", "603758.SSE", date(2026, 8, 6), "oversold_rebound"),
    ("京投发展 价格先行攻击", "600683.SSE", date(2026, 8, 7), "oversold_rebound"),
    # 2026-08 趋势族重构：连板后补涨/弱转强 21 个主人案例低吸点（十轮研究定稿）。
    # A 连板回落补涨（8 点）
    ("科森科技 均线蓄势收盘控制", "603626.SSE", date(2024, 10, 28), "trend_pullback"),
    ("伟时电子 五连板后转多头", "605218.SSE", date(2024, 10, 24), "trend_pullback"),
    ("国芳集团 第二波多头确认", "601086.SSE", date(2025, 5, 16), "trend_pullback"),
    ("诺德股份 低开小阳收盘控制", "600110.SSE", date(2025, 8, 4), "trend_pullback"),
    ("九牧王 承接住收盘控制", "601566.SSE", date(2025, 11, 27), "trend_pullback"),
    ("航天发展 尾盘控盘回踩", "000547.SZSE", date(2025, 12, 23), "trend_pullback"),
    ("华电辽能 长横盘后小阳", "600396.SSE", date(2026, 4, 20), "trend_pullback"),
    ("福达合金 第二波首小阳", "603045.SSE", date(2026, 6, 4), "trend_pullback"),
    # B 涨停弱转强（4 点，打板预备）
    ("双成药业 水下拉起收涨停", "002693.SZSE", date(2024, 10, 14), "trend_pullback"),
    ("国芳集团 炸板换手弱转强", "601086.SSE", date(2025, 4, 16), "trend_pullback"),
    ("航天发展 跌停换手拉板", "000547.SZSE", date(2025, 11, 24), "trend_pullback"),
    ("恒尚节能 超预期拉板", "603137.SSE", date(2026, 7, 13), "trend_pullback"),
    # 研究锚点：非涨停弱转强（9 点，全市场负边缘不进推荐、形态对照展示）
    ("兴业股份 炸板次日水下拉起", "603928.SSE", date(2025, 6, 27), "trend_pullback"),
    ("科森科技 承接住大阴预期", "603626.SSE", date(2025, 8, 26), "trend_pullback"),
    ("航天发展 水下拉起多头未破", "000547.SZSE", date(2025, 11, 27), "trend_pullback"),
    ("梦天家居 跌停预期承接", "603216.SSE", date(2025, 11, 26), "trend_pullback"),
    ("安记食品 跌停预期控盘", "603696.SSE", date(2025, 12, 12), "trend_pullback"),
    ("锋龙股份 高换手卡5日线", "002931.SZSE", date(2026, 2, 2), "trend_pullback"),
    ("哈药股份 低开拉回踩MA5", "600664.SSE", date(2026, 7, 20), "trend_pullback"),
    ("传智教育 弱转强卡点", "003032.SZSE", date(2026, 8, 7), "trend_pullback"),
    ("爱丽家居 弱转强停牌", "603221.SSE", date(2026, 8, 7), "trend_pullback"),
)


class DailyFactorInputError(ValueError):
    """Raised when a daily-bar sequence cannot support causal features."""


@dataclass(frozen=True)
class DailyFactorBar:
    trade_date: date
    open_price: float
    close_price: float
    high_price: float
    low_price: float
    volume: float | None
    turnover: float | None


@dataclass(frozen=True)
class MarketTimeSplit:
    development_dates: tuple[date, ...]
    embargo_dates: tuple[date, ...]
    validation_dates: tuple[date, ...]
    holdout_dates: tuple[date, ...]


def build_daily_features(
    history: Sequence[Mapping[str, object]],
    *,
    as_of_date: date | None = None,
) -> dict[str, object]:
    """Build only D-and-earlier features for the final bar before ``as_of_date``."""

    bars = _normalize_history(history, as_of_date=as_of_date)
    closes = [bar.close_price for bar in bars]
    ma_series = {window: _moving_average(closes, window) for window in MA_WINDOWS}
    index = len(bars) - 1
    current_ma = {window: ma_series[window][index] for window in MA_WINDOWS}
    ma5 = current_ma[5]
    ma10 = current_ma[10]
    ma20 = current_ma[20]
    ma30 = current_ma[30]
    ma60 = current_ma[60]
    daily_return_pct = _pct_change(bars[-1].close_price, bars[-1].open_price)
    low_to_close_pct = _pct_change(bars[-1].close_price, bars[-1].low_price)

    bear_alignment = [
        _is_bear_aligned(ma_series[10][position], ma_series[20][position], ma_series[30][position])
        for position in range(len(bars))
    ]
    bull_alignment = [
        _is_bull_aligned(
            ma_series[10][position],
            ma_series[20][position],
            ma_series[30][position],
        )
        for position in range(len(bars))
    ]
    prior_bear_alignment_days = _prior_bear_duration(bear_alignment, index)
    ma_cluster_spread_pct = _ma_cluster_spread_pct(ma10, ma20, ma30, bars[-1].close_price)
    prior_cluster_spread_pct = _ma_cluster_spread_pct(
        ma_series[10][index - TREND_SLOPE_LOOKBACK]
        if index >= TREND_SLOPE_LOOKBACK
        else None,
        ma_series[20][index - TREND_SLOPE_LOOKBACK]
        if index >= TREND_SLOPE_LOOKBACK
        else None,
        ma_series[30][index - TREND_SLOPE_LOOKBACK]
        if index >= TREND_SLOPE_LOOKBACK
        else None,
        bars[index - TREND_SLOPE_LOOKBACK].close_price
        if index >= TREND_SLOPE_LOOKBACK
        else None,
    )
    convergence = _convergence_score(ma_cluster_spread_pct, prior_cluster_spread_pct)
    ma10_ma20_distance_pct = _absolute_distance_pct(ma10, ma20, bars[-1].close_price)
    ma20_ma30_distance_pct = _absolute_distance_pct(ma20, ma30, bars[-1].close_price)
    close_to_ma10_pct = _signed_distance_pct(bars[-1].close_price, ma10)
    volume_features = _volume_features(bars, daily_return_pct)

    oversold_rebound_eligible = _is_oversold_rebound(
        ma10=ma10,
        ma20=ma20,
        ma30=ma30,
        prior_bear_alignment_days=prior_bear_alignment_days,
        ma_cluster_spread_pct=ma_cluster_spread_pct,
        ma10_ma20_distance_pct=ma10_ma20_distance_pct,
        daily_return_pct=daily_return_pct,
        close_to_ma10_pct=close_to_ma10_pct,
    )
    trend_features = _trend_features(
        bar=bars[-1],
        history=bars,
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma30=ma30,
        ma_series=ma_series,
        index=index,
        daily_return_pct=daily_return_pct,
    )

    features: dict[str, object] = {
        "trade_date": bars[-1].trade_date,
        "history_bars": len(bars),
        "open_price": bars[-1].open_price,
        "close_price": bars[-1].close_price,
        "high_price": bars[-1].high_price,
        "low_price": bars[-1].low_price,
        "volume": bars[-1].volume,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma30": ma30,
        "ma60": ma60,
        "daily_return_pct": daily_return_pct,
        "low_to_close_pct": low_to_close_pct,
        "ma10_20_distance_pct": ma10_ma20_distance_pct,
        "ma20_30_distance_pct": ma20_ma30_distance_pct,
        "ma_cluster_spread_pct": ma_cluster_spread_pct,
        "ma_cluster_spread_5d_pct": prior_cluster_spread_pct,
        "low_to_ma5_pct": _signed_distance_pct(bars[-1].low_price, ma5),
        "close_to_ma5_pct": _signed_distance_pct(bars[-1].close_price, ma5),
        "low_to_ma10_pct": _signed_distance_pct(bars[-1].low_price, ma10),
        "close_to_ma10_pct": close_to_ma10_pct,
        "prior_bear_alignment_days": prior_bear_alignment_days,
        "bear_alignment_days": _consecutive_true_count(bear_alignment),
        "bull_alignment_days": _consecutive_true_count(bull_alignment),
        "ma10_slope_5d_pct": _ma_slope_pct(ma_series[10], index),
        "ma20_slope_5d_pct": _ma_slope_pct(ma_series[20], index),
        "ma30_slope_5d_pct": _ma_slope_pct(ma_series[30], index),
        "ma60_slope_5d_pct": _ma_slope_pct(ma_series[60], index),
        "ma5_regular": ma5 is not None and ma10 is not None and ma5 > ma10,
        "oversold_rebound_eligible": oversold_rebound_eligible,
        "bear_duration": _clamp(prior_bear_alignment_days / 20.0),
        "convergence": convergence,
        "cross_phase": _oversold_cross_phase_score(ma10, ma20, ma30, bars[-1].close_price),
        "close_quality": _oversold_close_quality(
            daily_return_pct,
            close_to_ma10_pct,
        ),
        **volume_features,
        **trend_features,
    }
    features["setup_type"] = classify_daily_setup(features)
    features["secondary_setup_type"] = secondary_daily_setup(features)
    return features


def classify_daily_setup(features: Mapping[str, object]) -> str | None:
    """Assign one primary setup type; trend takes precedence when both match."""

    if bool(features.get("trend_pullback_eligible")):
        return "trend_pullback"
    if bool(features.get("oversold_rebound_eligible")):
        return "oversold_rebound"
    return None


def secondary_daily_setup(features: Mapping[str, object]) -> str | None:
    """Keep the non-primary setup type for overlap diagnostics."""

    primary = classify_daily_setup(features)
    if primary == "trend_pullback" and bool(features.get("oversold_rebound_eligible")):
        return "oversold_rebound"
    if primary == "oversold_rebound" and bool(features.get("trend_pullback_eligible")):
        return "trend_pullback"
    return None


def explain_setup_eligibility(
    features: Mapping[str, object],
    setup_type: str,
) -> dict[str, bool]:
    """Return every hard predicate used by one frozen baseline classifier."""

    if setup_type == "oversold_rebound":
        ma10 = _optional_finite_number(features.get("ma10"))
        ma20 = _optional_finite_number(features.get("ma20"))
        ma30 = _optional_finite_number(features.get("ma30"))
        cluster_spread = _optional_finite_number(features.get("ma_cluster_spread_pct"))
        ma10_ma20_distance = _optional_finite_number(features.get("ma10_20_distance_pct"))
        daily_return = _optional_finite_number(features.get("daily_return_pct"))
        close_to_ma10 = _optional_finite_number(features.get("close_to_ma10_pct"))
        return {
            "moving_averages_available": all(
                value is not None for value in (ma10, ma20, ma30)
            ),
            "prior_bear_structure": (
                _optional_finite_number(features.get("prior_bear_alignment_days")) or 0
            ) >= 5,
            "ma_cluster_spread_within_3pct": bool(
                cluster_spread is not None and cluster_spread <= 3.0
            ),
            "ma10_ma20_distance_within_2_5pct": bool(
                ma10_ma20_distance is not None and ma10_ma20_distance <= 2.5
            ),
            "ma10_not_materially_below_ma20": bool(
                ma10 is not None and ma20 is not None and ma10 >= ma20 * 0.985
            ),
            "daily_return_within_minus5_to_3pct": bool(
                daily_return is not None and -5.0 <= daily_return <= 3.0
            ),
            "close_within_4pct_of_ma10": bool(
                close_to_ma10 is not None and abs(close_to_ma10) <= 4.0
            ),
        }

    if setup_type == "trend_pullback":
        low_distance = _optional_finite_number(features.get("trend_low_to_reference_pct"))
        close_distance = _optional_finite_number(features.get("trend_close_to_reference_pct"))
        daily_return = _optional_finite_number(features.get("daily_return_pct"))
        slope_values = tuple(
            _optional_finite_number(features.get(f"ma{window}_slope_5d_pct"))
            for window in (10, 20, 30)
        )
        return {
            "ma10_ma20_ma30_bull": bool(features.get("trend_alignment")),
            "all_ma_slopes_up": bool(
                all(value is not None and value > 0 for value in slope_values)
            ),
            "support_reference_available": str(
                features.get("trend_reference_line") or "none"
            ) in {"ma5", "ma10"},
            "support_low_within_minus4_to_1_5pct": bool(
                low_distance is not None and -4.0 <= low_distance <= 1.5
            ),
            "support_close_recovered_above_minus1_5pct": bool(
                close_distance is not None and close_distance >= -1.5
            ),
            "daily_return_not_above_3pct": bool(
                daily_return is not None and daily_return <= 3.0
            ),
        }

    raise DailyFactorInputError(f"unsupported setup type: {setup_type}")


def label_d1_close_return_pct(
    closes_by_date: Mapping[date, object],
    market_calendar: Sequence[date],
    signal_date: date,
) -> float | None:
    """Return a valid main-board D-to-next-session-close return, or no label."""

    label, _ = d1_close_label_status(closes_by_date, market_calendar, signal_date)
    return label


def d1_close_label_status(
    closes_by_date: Mapping[date, object],
    market_calendar: Sequence[date],
    signal_date: date,
) -> tuple[float | None, str]:
    """Return a D+1 label and an explicit reason when it cannot be used.

    The daily-factor universe is restricted to seasoned, non-ST main-board
    stocks. Their daily close must remain inside the legal +/-10% limit
    corridor, including the exchange's price-tick rounding at the boundary.
    Raw-price discontinuities remain excluded.
    """

    calendar = _strict_calendar(market_calendar)
    try:
        position = calendar.index(signal_date)
    except ValueError:
        return None, "label_unavailable_calendar"
    if position + 1 >= len(calendar):
        return None, "label_unavailable_calendar"

    signal_close = _label_close(closes_by_date.get(signal_date))
    next_close = _label_close(closes_by_date.get(calendar[position + 1]))
    if signal_close is None or next_close is None:
        return None, "label_unavailable_price"
    if not is_main_board_close_within_price_limit(signal_close, next_close):
        return None, "label_excluded_main_board_price_limit"
    return round(_pct_change(next_close, signal_close), 4), "available"


def is_main_board_close_within_price_limit(
    prior_close: float,
    current_close: float,
) -> bool:
    """Return whether a price fits the main-board 10% limit after tick rounding."""

    previous = Decimal(str(prior_close))
    current = Decimal(str(current_close))
    if previous <= 0 or current <= 0:
        return False
    tick = Decimal("0.01")
    lower_limit = (previous * (Decimal("1") - MAIN_BOARD_PRICE_LIMIT_RATE)).quantize(
        tick,
        rounding=ROUND_HALF_UP,
    )
    upper_limit = (previous * (Decimal("1") + MAIN_BOARD_PRICE_LIMIT_RATE)).quantize(
        tick,
        rounding=ROUND_HALF_UP,
    )
    return lower_limit <= current <= upper_limit


def is_main_board_limit_up_touched(
    prior_close: float,
    high_price: float,
) -> bool:
    """Return whether a bar reached the tick-rounded 10% upper limit."""

    previous = Decimal(str(prior_close))
    high = Decimal(str(high_price))
    if previous <= 0:
        return False
    upper_limit = (previous * (Decimal("1") + MAIN_BOARD_PRICE_LIMIT_RATE)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )
    return high >= upper_limit


def score_oversold(
    features: Mapping[str, object],
    *,
    include_volume: bool,
) -> float | None:
    """Score the frozen oversold components with equal weights."""

    components = ["bear_duration", "convergence", "cross_phase", "close_quality"]
    if include_volume:
        components.append("conditional_volume")
    return _equal_weight_score(features, components)


def score_trend(
    features: Mapping[str, object],
    *,
    include_volume: bool,
) -> float | None:
    """Score the frozen trend components; volume remains an ablation only."""

    components = ["trend_alignment", "trend_slope", "trend_support", "trend_pullback"]
    if include_volume:
        components.append("conditional_volume")
    return _equal_weight_score(features, components)


def score_factor_variants(features: Mapping[str, object]) -> dict[str, float | None]:
    """Return both base and volume-ablation scores for one classified setup."""

    setup_type = classify_daily_setup(features)
    if setup_type == "oversold_rebound":
        return {
            "base": score_oversold(features, include_volume=False),
            "with_volume": score_oversold(features, include_volume=True),
        }
    if setup_type == "trend_pullback":
        return {
            "base": score_trend(features, include_volume=False),
            "with_volume": score_trend(features, include_volume=True),
        }
    return {}


def split_market_calendar(
    market_calendar: Sequence[date],
    *,
    embargo_days: int = 5,
) -> MarketTimeSplit:
    """Split usable sessions 60/20/20 with an embargo before validation."""

    calendar = _strict_calendar(market_calendar)
    if embargo_days < 0:
        raise DailyFactorInputError("embargo_days cannot be negative")
    usable_days = len(calendar) - embargo_days
    development_count = int(usable_days * 0.6)
    validation_count = int(usable_days * 0.2)
    holdout_count = usable_days - development_count - validation_count
    if min(development_count, validation_count, holdout_count) < 1:
        raise DailyFactorInputError("market calendar is too short for development/validation/holdout")
    embargo_start = development_count
    validation_start = embargo_start + embargo_days
    validation_end = validation_start + validation_count
    return MarketTimeSplit(
        development_dates=calendar[:development_count],
        embargo_dates=calendar[embargo_start:validation_start],
        validation_dates=calendar[validation_start:validation_end],
        holdout_dates=calendar[validation_end:],
    )


def select_score_band(
    panel: Sequence[Mapping[str, object]],
    development_dates: Sequence[date],
    validation_dates: Sequence[date],
) -> dict[str, object]:
    """Select one score band from development data and report validation only."""

    development_set = set(_strict_calendar(development_dates))
    validation_set = set(_strict_calendar(validation_dates))
    if development_set & validation_set:
        raise DailyFactorInputError("development and validation dates must not overlap")
    normalized = _normalize_scored_panel(panel)
    development_rows = [row for row in normalized if row["trade_date"] in development_set]
    validation_rows = [row for row in normalized if row["trade_date"] in validation_set]
    development_summary = summarize_score_bands(development_rows)
    eligible = [row for row in development_summary if row["d1_mean_return_pct"] is not None]
    if not eligible:
        return {
            "selected_band": None,
            "selection_dates": (),
            "development": None,
            "validation": _outcome_summary((), candidate_dates=()),
        }
    selected = max(
        eligible,
        key=lambda row: (
            float(row["d1_mean_return_pct"]),
            float(row["win_rate_pct"]),
            int(row["sample_count"]),
        ),
    )
    selected_rows = [row for row in validation_rows if _score_band(row["score"]) == selected["band"]]
    selection_dates = tuple(sorted({row["trade_date"] for row in development_rows}))
    return {
        "selected_band": selected["band"],
        "selection_dates": selection_dates,
        "development": selected,
        "validation": _outcome_summary(
            selected_rows,
            candidate_dates={row["trade_date"] for row in selected_rows},
        ),
    }


def summarize_score_bands(
    panel: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Summarize every frozen score bucket, including unlabeled candidates."""

    normalized = _normalize_scored_panel(panel)
    summaries: list[dict[str, object]] = []
    for _, _, band in SCORE_BANDS:
        rows = [row for row in normalized if _score_band(row["score"]) == band]
        summaries.append(
            {
                "band": band,
                **_outcome_summary(
                    rows,
                    candidate_dates={row["trade_date"] for row in rows},
                ),
            }
        )
    return summaries


def summarize_daily_outcomes(
    panel: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Report candidate count and D+1 proxy outcome for every signal date."""

    grouped: dict[date, list[dict[str, object]]] = {}
    for row in _normalize_scored_panel(panel):
        grouped.setdefault(row["trade_date"], []).append(row)
    return [
        {"trade_date": trade_date, **_outcome_summary(rows, candidate_dates={trade_date})}
        for trade_date, rows in sorted(grouped.items())
    ]


def run_daily_factor_study(
    *,
    bars: Sequence[Mapping[str, object]],
    market_calendar: Sequence[date],
    security_status: Sequence[Mapping[str, object]],
    evidence_level: str,
    blockers: Sequence[str],
    coverage: Mapping[str, object],
    input_sha256: str,
) -> dict[str, object]:
    """Run the frozen study protocol without accessing PostgreSQL or a provider."""

    normalized_blockers = tuple(sorted({str(value) for value in blockers if str(value)}))
    report: dict[str, object] = {
        "research_version": "low-suction-daily-factor-v3",
        "evidence_level": evidence_level,
        "input_sha256": input_sha256,
        "coverage": dict(coverage),
        "blockers": list(normalized_blockers),
        "qualification_thresholds": {
            "minimum_validation_samples": MIN_QUALIFICATION_SAMPLES,
            "minimum_holdout_samples": MIN_QUALIFICATION_SAMPLES,
            "minimum_candidate_days_per_segment": MIN_QUALIFICATION_CANDIDATE_DAYS,
            "validation_and_holdout_d1_mean_return_pct": "> 0",
        },
    }
    if normalized_blockers:
        report.update(
            {
                "status": "blocked",
                "conclusion": "data_blocker",
                "time_split": None,
                "feature_diagnostics": _empty_feature_diagnostics(),
                "personal_case_checks": _unavailable_case_checks(),
                "factor_results": _empty_factor_results(),
                "qualified_rules": [],
            }
        )
        return report

    calendar = _strict_calendar(market_calendar)
    try:
        split = split_market_calendar(calendar)
    except DailyFactorInputError as exc:
        report.update(
            {
                "status": "blocked",
                "conclusion": "data_blocker",
                "blockers": [*normalized_blockers, str(exc)],
                "time_split": None,
                "feature_diagnostics": _empty_feature_diagnostics(),
                "personal_case_checks": _unavailable_case_checks(),
                "factor_results": _empty_factor_results(),
                "qualified_rules": [],
            }
        )
        return report

    panels, diagnostics, case_checks = _build_research_panels(
        bars,
        calendar,
        security_status,
    )
    factor_results: dict[str, dict[str, dict[str, object]]] = {}
    qualified_rules: list[dict[str, object]] = []
    for setup_type in ("oversold_rebound", "trend_pullback"):
        variants: dict[str, dict[str, object]] = {}
        for variant in ("base", "with_volume"):
            result = _evaluate_factor_variant(panels[setup_type][variant], split)
            variants[variant] = result
            if bool(result["qualification_gate"]["passed"]):
                qualified_rules.append(
                    {
                        "setup_type": setup_type,
                        "variant": variant,
                        "score_band": result["selection"]["selected_band"],
                        "validation": result["selection"]["validation"],
                        "holdout": result["holdout"],
                    }
                )
        factor_results[setup_type] = variants

    if evidence_level != "strict":
        conclusion, status = "exploratory_only", "exploratory_complete"
    elif qualified_rules:
        conclusion, status = "qualified_research_rule", "complete"
    else:
        conclusion, status = "no_qualified_strategy", "complete"
    report.update(
        {
            "status": status,
            "conclusion": conclusion,
            "time_split": _time_split_payload(split),
            "feature_diagnostics": diagnostics,
            "personal_case_checks": case_checks,
            "factor_results": factor_results,
            "qualified_rules": qualified_rules if evidence_level == "strict" else [],
        }
    )
    return report


def render_daily_factor_json(report: Mapping[str, object]) -> str:
    """Render a stable machine-readable study report."""

    return json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"


def render_daily_factor_markdown(report: Mapping[str, object]) -> str:
    """Render all fixed score buckets without promoting an unqualified rule."""

    lines = [
        "# 日线低吸双因子研究",
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
        if isinstance(raw_prices, Mapping):
            warning = raw_prices.get("warning")
            if warning:
                lines.append(f"- 原始日线限制：`{warning}`")
    blockers = list(report.get("blockers") or [])
    if blockers:
        lines.extend(["", "## 数据门禁", ""])
        lines.extend(f"- `{value}`" for value in blockers)
    split = report.get("time_split")
    if isinstance(split, Mapping):
        lines.extend(
            [
                "",
                "## 时间切分",
                "",
                f"- development：{split['development_start']} 至 {split['development_end']}（{split['development_days']} 日）",
                f"- embargo：{split['embargo_start']} 至 {split['embargo_end']}（{split['embargo_days']} 日）",
                f"- validation：{split['validation_start']} 至 {split['validation_end']}（{split['validation_days']} 日）",
                f"- holdout：{split['holdout_start']} 至 {split['holdout_end']}（{split['holdout_days']} 日）",
            ]
        )
    diagnostics = report.get("feature_diagnostics")
    if isinstance(diagnostics, Mapping):
        lines.extend(
            [
                "",
                "## D+1 标签质量",
                "",
                "- 主板 10% 涨跌停边界外剔除：{count}。".format(
                    count=diagnostics.get(
                        "label_excluded_main_board_price_limit_count",
                        0,
                    )
                ),
            ]
        )
    factors = report.get("factor_results")
    if isinstance(factors, Mapping):
        lines.extend(["", "## 固定分数结果", ""])
        lines.append("| 类型 | 变体 | 分数桶 | 样本 | 胜率 | D+1 均值 | 日均候选 |")
        lines.append("| --- | --- | --- | ---: | ---: | ---: | ---: |")
        for setup_type in ("oversold_rebound", "trend_pullback"):
            variants = factors.get(setup_type)
            if not isinstance(variants, Mapping):
                continue
            for variant in ("base", "with_volume"):
                result = variants.get(variant)
                if not isinstance(result, Mapping):
                    continue
                for band in result.get("score_bands", []):
                    if isinstance(band, Mapping):
                        lines.append(
                            "| {setup} | {variant} | {band} | {samples} | {win} | {mean} | {daily} |".format(
                                setup=setup_type,
                                variant=variant,
                                band=band.get("band", "-"),
                                samples=band.get("sample_count", 0),
                                win=_display_number(band.get("win_rate_pct")),
                                mean=_display_number(band.get("d1_mean_return_pct")),
                                daily=_display_number(band.get("daily_candidate_average")),
                            )
                        )
        lines.extend(["", "## 时间外准入门槛", ""])
        lines.append("| 类型 | 变体 | 开发期选定桶 | 验证 D+1 均值 | 留出 D+1 均值 | 门禁 |")
        lines.append("| --- | --- | --- | ---: | ---: | --- |")
        for setup_type in ("oversold_rebound", "trend_pullback"):
            variants = factors.get(setup_type)
            if not isinstance(variants, Mapping):
                continue
            for variant in ("base", "with_volume"):
                result = variants.get(variant)
                if not isinstance(result, Mapping):
                    continue
                selection = result.get("selection")
                validation = (
                    selection.get("validation") if isinstance(selection, Mapping) else None
                )
                holdout = result.get("holdout")
                gate = result.get("qualification_gate")
                lines.append(
                    "| {setup} | {variant} | {band} | {validation_mean} | "
                    "{holdout_mean} | {gate_status} |".format(
                        setup=setup_type,
                        variant=variant,
                        band=(
                            selection.get("selected_band", "-")
                            if isinstance(selection, Mapping)
                            else "-"
                        ),
                        validation_mean=_display_number(
                            validation.get("d1_mean_return_pct")
                            if isinstance(validation, Mapping)
                            else None
                        ),
                        holdout_mean=_display_number(
                            holdout.get("d1_mean_return_pct")
                            if isinstance(holdout, Mapping)
                            else None
                        ),
                        gate_status=(
                            "通过"
                            if isinstance(gate, Mapping) and bool(gate.get("passed"))
                            else "未通过"
                            if isinstance(gate, Mapping)
                            else "-"
                        ),
                    )
                )
    case_checks = report.get("personal_case_checks")
    if isinstance(case_checks, Sequence):
        lines.extend(["", "## 个人样例核查", ""])
        lines.append("| 样例 | 日期 | 预期类型 | 实际类型 | D+1 | 状态 |")
        lines.append("| --- | --- | --- | --- | ---: | --- |")
        for row in case_checks:
            if isinstance(row, Mapping):
                lines.append(
                    "| {name} | {trade_date} | {expected} | {actual} | {label} | {status} |".format(
                        name=row.get("name", "-"),
                        trade_date=row.get("trade_date", "-"),
                        expected=row.get("expected_setup_type", "-"),
                        actual=row.get("setup_type", "-"),
                        label=_display_number(row.get("d1_close_return_pct")),
                        status=row.get("data_status", "-"),
                    )
                )
    return "\n".join(lines) + "\n"


def _build_research_panels(
    bars: Sequence[Mapping[str, object]],
    calendar: tuple[date, ...],
    security_status: Sequence[Mapping[str, object]],
) -> tuple[
    dict[str, dict[str, list[dict[str, object]]]],
    dict[str, object],
    list[dict[str, object]],
]:
    histories = _group_histories_by_symbol(bars)
    eligible_pairs = _eligible_security_pairs(security_status, calendar)
    calendar_set = set(calendar)
    positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    cases_by_symbol: dict[str, set[date]] = defaultdict(set)
    for _, symbol, trade_date, _ in PERSONAL_RESEARCH_CASES:
        cases_by_symbol[symbol].add(trade_date)
    panels = {
        "oversold_rebound": {"base": [], "with_volume": []},
        "trend_pullback": {"base": [], "with_volume": []},
    }
    diagnostics = {
        **_empty_feature_diagnostics(),
        "input_bars": sum(len(history) for history in histories.values()),
        "input_symbols": len(histories),
        "security_eligible_pair_count": len(eligible_pairs),
    }
    case_results: dict[tuple[str, date], dict[str, object]] = {}
    for symbol, history in histories.items():
        dates = [
            _required_date(_first_value(row, "trade_date", "日期"), index)
            for index, row in enumerate(history)
        ]
        closes = {
            trade_date: _first_value(history[index], "close_price", "close", "收盘")
            for index, trade_date in enumerate(dates)
        }
        candidate_positions = set(_candidate_positions(history))
        requested_case_dates = cases_by_symbol.get(symbol, set())
        for index, trade_date in enumerate(dates):
            if trade_date not in calendar_set:
                continue
            is_case = trade_date in requested_case_dates
            if index not in candidate_positions and not is_case:
                continue
            if eligible_pairs and (symbol, trade_date) not in eligible_pairs and not is_case:
                diagnostics["security_excluded_signal_count"] = int(
                    diagnostics["security_excluded_signal_count"]
                ) + 1
                continue
            features = build_daily_features(_feature_history_window(history, index))
            label, reason = _eligible_d1_label(
                closes,
                calendar,
                positions,
                symbol,
                trade_date,
                eligible_pairs,
            )
            if reason:
                diagnostics[reason] = int(diagnostics[reason]) + 1
            setup_type = classify_daily_setup(features)
            if is_case:
                case_results[(symbol, trade_date)] = {
                    "setup_type": setup_type,
                    "secondary_setup_type": features["secondary_setup_type"],
                    "scores": score_factor_variants(features),
                    "d1_close_return_pct": label,
                    "data_status": reason or "available",
                }
            if reason == "label_excluded_main_board_price_limit_count":
                continue
            if setup_type is None or (eligible_pairs and (symbol, trade_date) not in eligible_pairs):
                continue
            for variant, score in score_factor_variants(features).items():
                if score is None:
                    diagnostics["volume_score_unavailable_count"] = int(
                        diagnostics["volume_score_unavailable_count"]
                    ) + 1
                    continue
                panels[setup_type][variant].append(
                    {
                        "vt_symbol": symbol,
                        "trade_date": trade_date,
                        "score": score,
                        "d1_close_return_pct": label,
                    }
                )
    case_checks = []
    for name, symbol, trade_date, expected in PERSONAL_RESEARCH_CASES:
        case_checks.append(
            {
                "name": name,
                "vt_symbol": symbol,
                "trade_date": trade_date.isoformat(),
                "expected_setup_type": expected,
                **case_results.get(
                    (symbol, trade_date),
                    {
                        "setup_type": None,
                        "secondary_setup_type": None,
                        "scores": {},
                        "d1_close_return_pct": None,
                        "data_status": "qfq_data_unavailable",
                    },
                ),
            }
        )
    return panels, diagnostics, case_checks


def _candidate_positions(history: Sequence[Mapping[str, object]]) -> tuple[int, ...]:
    """Use one rolling pass before the detailed pure feature calculation."""

    normalized = _normalize_history(history, as_of_date=None)
    closes = [bar.close_price for bar in normalized]
    ma_series = {window: _moving_average(closes, window) for window in MA_WINDOWS}
    bear = [
        _is_bear_aligned(ma_series[10][index], ma_series[20][index], ma_series[30][index])
        for index in range(len(normalized))
    ]
    result: list[int] = []
    for index, bar in enumerate(normalized):
        ma5, ma10, ma20, ma30, ma60 = (
            ma_series[5][index],
            ma_series[10][index],
            ma_series[20][index],
            ma_series[30][index],
            ma_series[60][index],
        )
        daily_return = _pct_change(bar.close_price, bar.open_price)
        oversold = _is_oversold_rebound(
            ma10=ma10,
            ma20=ma20,
            ma30=ma30,
            prior_bear_alignment_days=_prior_bear_duration(bear, index),
            ma_cluster_spread_pct=_ma_cluster_spread_pct(ma10, ma20, ma30, bar.close_price),
            ma10_ma20_distance_pct=_absolute_distance_pct(ma10, ma20, bar.close_price),
            daily_return_pct=daily_return,
            close_to_ma10_pct=_signed_distance_pct(bar.close_price, ma10),
        )
        trend = bool(
            _trend_features(
                bar=bar,
                history=normalized,
                ma5=ma5,
                ma10=ma10,
                ma20=ma20,
                ma30=ma30,
                ma_series=ma_series,
                index=index,
                daily_return_pct=daily_return,
            )["trend_pullback_eligible"]
        )
        if oversold or trend:
            result.append(index)
    return tuple(result)


def daily_factor_candidate_positions(
    history: Sequence[Mapping[str, object]],
) -> tuple[int, ...]:
    """Return causal positions eligible for either frozen daily-factor family."""

    return _candidate_positions(history)


def _feature_history_window(
    history: Sequence[Mapping[str, object]],
    position: int,
) -> Sequence[Mapping[str, object]]:
    return history[: position + 1] if position < 80 else history[position - 79 : position + 1]


def daily_factor_history_window(
    history: Sequence[Mapping[str, object]],
    position: int,
) -> Sequence[Mapping[str, object]]:
    """Return the bounded causal window used by the daily feature contract."""

    if position < 0 or position >= len(history):
        raise DailyFactorInputError("daily factor position is outside the history")
    return _feature_history_window(history, position)


def _group_histories_by_symbol(
    bars: Sequence[Mapping[str, object]],
) -> dict[str, list[Mapping[str, object]]]:
    histories: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for index, row in enumerate(bars):
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        if not symbol:
            raise DailyFactorInputError(f"vt_symbol is required at bar row {index}")
        histories[symbol].append(row)
    for history in histories.values():
        history.sort(key=lambda row: _required_date(_first_value(row, "trade_date", "日期"), 0))
        _normalize_history(history, as_of_date=None)
    return dict(histories)


def _eligible_security_pairs(
    security_status: Sequence[Mapping[str, object]],
    calendar: Sequence[date],
) -> set[tuple[str, date]]:
    if not security_status:
        return set()
    calendar_positions = {trade_date: index for index, trade_date in enumerate(calendar)}
    eligible: set[tuple[str, date]] = set()
    for index, row in enumerate(security_status):
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        trade_date = _required_date(row.get("trade_date"), index)
        if not symbol or trade_date not in calendar_positions:
            continue
        if str(row.get("board") or "").strip().lower() != "main":
            continue
        if str(row.get("status") or "").strip().upper() == "DELISTED":
            continue
        if bool(row.get("suspended")) or bool(row.get("risk_warning")):
            continue
        listed_on = _required_date(row.get("listed_on"), index)
        if calendar_positions[trade_date] - bisect_left(calendar, listed_on) < 60:
            continue
        eligible.add((symbol, trade_date))
    return eligible


def _eligible_d1_label(
    closes: Mapping[date, object],
    calendar: Sequence[date],
    positions: Mapping[date, int],
    symbol: str,
    trade_date: date,
    eligible_pairs: set[tuple[str, date]],
) -> tuple[float | None, str | None]:
    position = positions.get(trade_date)
    if position is None or position + 1 >= len(calendar):
        return None, "label_unavailable_calendar_count"
    if eligible_pairs and (symbol, calendar[position + 1]) not in eligible_pairs:
        return None, "label_unavailable_security_count"
    label, status = d1_close_label_status(closes, calendar, trade_date)
    if status == "available":
        return label, None
    if status == "label_excluded_main_board_price_limit":
        return None, "label_excluded_main_board_price_limit_count"
    return None, "label_unavailable_price_count"


def _evaluate_factor_variant(
    panel: Sequence[Mapping[str, object]],
    split: MarketTimeSplit,
) -> dict[str, object]:
    normalized = _normalize_scored_panel(panel)
    development = set(split.development_dates)
    validation = set(split.validation_dates)
    holdout_dates = set(split.holdout_dates)
    selection = select_score_band(normalized, split.development_dates, split.validation_dates)
    selected = selection["selected_band"]
    holdout_rows = [
        row
        for row in normalized
        if row["trade_date"] in holdout_dates
        and (selected is None or _score_band(row["score"]) == selected)
    ]
    holdout = _outcome_summary(
        holdout_rows,
        candidate_dates={row["trade_date"] for row in holdout_rows},
    )
    return {
        "score_bands": summarize_score_bands(normalized),
        "development_score_bands": summarize_score_bands(
            [row for row in normalized if row["trade_date"] in development]
        ),
        "validation_score_bands": summarize_score_bands(
            [row for row in normalized if row["trade_date"] in validation]
        ),
        "holdout_score_bands": summarize_score_bands(
            [row for row in normalized if row["trade_date"] in holdout_dates]
        ),
        "selection": {
            **selection,
            "selection_dates": [value.isoformat() for value in selection["selection_dates"]],
        },
        "holdout": holdout,
        "qualification_gate": _qualification_gate(selection, holdout),
        "daily_outcomes": [
            {**row, "trade_date": row["trade_date"].isoformat()}
            for row in summarize_daily_outcomes(normalized)
        ],
        "bad_days": _bad_days(normalized),
        "bad_stocks": _bad_stocks(panel),
    }


def _qualification_gate(
    selection: Mapping[str, object],
    holdout: Mapping[str, object],
) -> dict[str, object]:
    validation = selection.get("validation")
    if not isinstance(validation, Mapping) or selection.get("selected_band") is None:
        return {"passed": False, "reasons": ["no_development_selected_score_band"]}
    checks = {
        "validation_sample_count": int(validation.get("sample_count") or 0) >= MIN_QUALIFICATION_SAMPLES,
        "holdout_sample_count": int(holdout.get("sample_count") or 0) >= MIN_QUALIFICATION_SAMPLES,
        "validation_candidate_days": int(validation.get("candidate_days") or 0) >= MIN_QUALIFICATION_CANDIDATE_DAYS,
        "holdout_candidate_days": int(holdout.get("candidate_days") or 0) >= MIN_QUALIFICATION_CANDIDATE_DAYS,
        "validation_positive_d1_mean": _positive_number(validation.get("d1_mean_return_pct")),
        "holdout_positive_d1_mean": _positive_number(holdout.get("d1_mean_return_pct")),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "reasons": [name for name, passed in checks.items() if not passed],
    }


def _bad_days(panel: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {**row, "trade_date": row["trade_date"].isoformat()}
        for row in summarize_daily_outcomes(panel)
        if row["d1_mean_return_pct"] is not None and float(row["d1_mean_return_pct"]) < 0
    ]


def _bad_stocks(panel: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    labels: dict[str, list[float]] = defaultdict(list)
    days: dict[str, set[date]] = defaultdict(set)
    unavailable: dict[str, int] = defaultdict(int)
    for row in panel:
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        if not symbol:
            continue
        days[symbol].add(_required_date(row.get("trade_date"), 0))
        value = row.get("d1_close_return_pct")
        if value is None:
            unavailable[symbol] += 1
        else:
            labels[symbol].append(float(value))
    rows = [
        {
            "vt_symbol": symbol,
            "sample_count": len(values),
            "candidate_days": len(days[symbol]),
            "label_unavailable_count": unavailable[symbol],
            "win_rate_pct": round(sum(value > 0 for value in values) / len(values) * 100, 4),
            "d1_mean_return_pct": round(fmean(values), 4),
            "d1_median_return_pct": round(median(values), 4),
        }
        for symbol, values in labels.items()
        if values and fmean(values) < 0
    ]
    return sorted(rows, key=lambda row: (float(row["d1_mean_return_pct"]), str(row["vt_symbol"])))


def _empty_factor_results() -> dict[str, dict[str, dict[str, object]]]:
    empty_summary = summarize_score_bands(())
    return {
        setup_type: {
            variant: {
                "score_bands": empty_summary,
                "development_score_bands": empty_summary,
                "validation_score_bands": empty_summary,
                "holdout_score_bands": empty_summary,
                "selection": {
                    "selected_band": None,
                    "selection_dates": [],
                    "development": None,
                    "validation": _outcome_summary((), candidate_dates=()),
                },
                "holdout": _outcome_summary((), candidate_dates=()),
                "qualification_gate": {"passed": False, "reasons": ["input_blocked"]},
                "daily_outcomes": [],
                "bad_days": [],
                "bad_stocks": [],
            }
            for variant in ("base", "with_volume")
        }
        for setup_type in ("oversold_rebound", "trend_pullback")
    }


def _empty_feature_diagnostics() -> dict[str, object]:
    return {
        "input_bars": 0,
        "input_symbols": 0,
        "security_eligible_pair_count": 0,
        "security_excluded_signal_count": 0,
        "label_unavailable_calendar_count": 0,
        "label_unavailable_security_count": 0,
        "label_unavailable_price_count": 0,
        "label_excluded_main_board_price_limit_count": 0,
        "volume_score_unavailable_count": 0,
    }


def _unavailable_case_checks() -> list[dict[str, object]]:
    return [
        {
            "name": name,
            "vt_symbol": symbol,
            "trade_date": trade_date.isoformat(),
            "expected_setup_type": expected,
            "setup_type": None,
            "secondary_setup_type": None,
            "scores": {},
            "d1_close_return_pct": None,
            "data_status": "input_blocked",
        }
        for name, symbol, trade_date, expected in PERSONAL_RESEARCH_CASES
    ]


def _time_split_payload(split: MarketTimeSplit) -> dict[str, object]:
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


def _positive_number(value: object) -> bool:
    try:
        return not isinstance(value, bool) and value is not None and float(value) > 0
    except (TypeError, ValueError):
        return False


def _display_number(value: object) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.4f}"
    except (TypeError, ValueError):
        return str(value)


def _equal_weight_score(
    features: Mapping[str, object],
    components: Sequence[str],
) -> float | None:
    values: list[float] = []
    for component in components:
        value = features.get(component)
        if value is None:
            return None
        if isinstance(value, bool):
            raise DailyFactorInputError(f"score component {component} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise DailyFactorInputError(f"score component {component} must be numeric") from exc
        if not math.isfinite(number) or not 0.0 <= number <= 1.0:
            raise DailyFactorInputError(f"score component {component} must be within 0..1")
        values.append(number)
    return round(100 * fmean(values), 2)


def _normalize_scored_panel(
    panel: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    for row_index, row in enumerate(panel):
        trade_date = _required_date(row.get("trade_date"), row_index)
        score = _panel_number(row.get("score"), "score", row_index)
        if not 0.0 <= score <= 100.0:
            raise DailyFactorInputError(f"score must be within 0..100 at row {row_index}")
        label_value = row.get("d1_close_return_pct")
        label = None if label_value is None else _panel_number(label_value, "d1 label", row_index)
        normalized.append(
            {
                "trade_date": trade_date,
                "score": score,
                "d1_close_return_pct": label,
            }
        )
    return normalized


def _panel_number(value: object, field: str, row_index: int) -> float:
    if isinstance(value, bool):
        raise DailyFactorInputError(f"{field} must be numeric at row {row_index}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DailyFactorInputError(f"{field} must be numeric at row {row_index}") from exc
    if not math.isfinite(number):
        raise DailyFactorInputError(f"{field} must be finite at row {row_index}")
    return number


def _score_band(score: object) -> str:
    numeric = float(score)
    for lower, upper, band in SCORE_BANDS:
        if lower <= numeric <= upper:
            return band
    raise DailyFactorInputError(f"score is outside frozen bands: {numeric}")


def _outcome_summary(
    rows: Sequence[Mapping[str, object]],
    *,
    candidate_dates: Sequence[date] | set[date],
) -> dict[str, object]:
    labels = [
        float(row["d1_close_return_pct"])
        for row in rows
        if row.get("d1_close_return_pct") is not None
    ]
    candidate_count = len(rows)
    candidate_days = len(set(candidate_dates))
    positive_count = sum(label > 0 for label in labels)
    return {
        "candidate_count": candidate_count,
        "sample_count": len(labels),
        "label_unavailable_count": candidate_count - len(labels),
        "candidate_days": candidate_days,
        "daily_candidate_average": round(candidate_count / candidate_days, 4) if candidate_days else 0.0,
        "win_rate_pct": round(positive_count / len(labels) * 100, 4) if labels else None,
        "d1_mean_return_pct": round(fmean(labels), 4) if labels else None,
        "d1_median_return_pct": round(median(labels), 4) if labels else None,
        "positive_return_ci95_pct": _wilson_interval_pct(positive_count, len(labels)),
    }


def _wilson_interval_pct(successes: int, total: int) -> dict[str, float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z**2 / total
    center = (proportion + z**2 / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z**2 / (4 * total**2)
    ) / denominator
    return {
        "lower": round(max(0.0, center - margin) * 100, 4),
        "upper": round(min(1.0, center + margin) * 100, 4),
    }


def _strict_calendar(values: Sequence[date]) -> tuple[date, ...]:
    calendar = tuple(values)
    if any(type(trade_date) is not date for trade_date in calendar):
        raise DailyFactorInputError("market calendar must contain date values")
    if any(current <= previous for previous, current in zip(calendar, calendar[1:])):
        raise DailyFactorInputError("market calendar must be strictly increasing")
    return calendar


def _label_close(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _optional_finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalize_history(
    history: Sequence[Mapping[str, object]],
    *,
    as_of_date: date | None,
) -> list[DailyFactorBar]:
    scoped_rows = [
        (row, row_index)
        for row_index, row in enumerate(history)
        if as_of_date is None
        or _required_date(_first_value(row, "trade_date", "日期"), row_index)
        <= as_of_date
    ]
    bars = [_normalize_bar(row, row_index) for row, row_index in scoped_rows]
    if not bars:
        raise DailyFactorInputError("daily factor history is empty at the requested cutoff")
    if any(current.trade_date <= previous.trade_date for previous, current in zip(bars, bars[1:])):
        raise DailyFactorInputError("daily factor history must have strictly increasing trade dates")
    return bars


def _normalize_bar(row: Mapping[str, object], row_index: int) -> DailyFactorBar:
    trade_date = _required_date(_first_value(row, "trade_date", "日期"), row_index)
    open_price = _required_positive_float(_first_value(row, "open_price", "open", "开盘"), "open", row_index)
    close_price = _required_positive_float(_first_value(row, "close_price", "close", "收盘"), "close", row_index)
    high_price = _required_positive_float(_first_value(row, "high_price", "high", "最高"), "high", row_index)
    low_price = _required_positive_float(_first_value(row, "low_price", "low", "最低"), "low", row_index)
    if high_price < max(open_price, close_price):
        raise DailyFactorInputError(f"high price is below open or close at row {row_index}")
    if low_price > min(open_price, close_price):
        raise DailyFactorInputError(f"low price is above open or close at row {row_index}")
    return DailyFactorBar(
        trade_date=trade_date,
        open_price=open_price,
        close_price=close_price,
        high_price=high_price,
        low_price=low_price,
        volume=_optional_nonnegative_float(_first_value(row, "volume", "成交量"), "volume", row_index),
        turnover=_optional_nonnegative_float(_first_value(row, "turnover", "成交额"), "turnover", row_index),
    )


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _required_date(value: object, row_index: int) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise DailyFactorInputError(f"invalid trade date at row {row_index}") from exc


def _required_positive_float(value: object, field: str, row_index: int) -> float:
    number = _finite_float(value, field, row_index)
    if number <= 0:
        raise DailyFactorInputError(f"{field} price must be positive at row {row_index}")
    return number


def _optional_nonnegative_float(value: object, field: str, row_index: int) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DailyFactorInputError(f"{field} is not numeric at row {row_index}") from exc
    if math.isnan(number):
        return None
    if not math.isfinite(number):
        raise DailyFactorInputError(f"{field} is not finite at row {row_index}")
    if number < 0:
        raise DailyFactorInputError(f"{field} cannot be negative at row {row_index}")
    return number


def _finite_float(value: object, field: str, row_index: int) -> float:
    if isinstance(value, bool):
        raise DailyFactorInputError(f"{field} is not numeric at row {row_index}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DailyFactorInputError(f"{field} is not numeric at row {row_index}") from exc
    if not math.isfinite(number):
        raise DailyFactorInputError(f"{field} is not finite at row {row_index}")
    return number


def _moving_average(values: Sequence[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    total = 0.0
    for index, value in enumerate(values):
        total += value
        if index >= window:
            total -= values[index - window]
        result.append(total / window if index + 1 >= window else None)
    return result


def _is_bear_aligned(ma10: float | None, ma20: float | None, ma30: float | None) -> bool:
    return ma10 is not None and ma20 is not None and ma30 is not None and ma10 < ma20 < ma30


def _is_bull_aligned(
    ma10: float | None,
    ma20: float | None,
    ma30: float | None,
) -> bool:
    return (
        ma10 is not None
        and ma20 is not None
        and ma30 is not None
        and ma10 > ma20 > ma30
    )


def _prior_bear_duration(bear_alignment: Sequence[bool], index: int) -> int:
    end = max(0, index - OVERSOLD_RECENT_EXCLUSION + 1)
    start = max(0, end - OVERSOLD_PRIOR_BEAR_LOOKBACK)
    return _longest_true_run(bear_alignment[start:end])


def _longest_true_run(values: Sequence[bool]) -> int:
    longest = 0
    current = 0
    for value in values:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _consecutive_true_count(values: Sequence[bool]) -> int:
    count = 0
    for value in reversed(values):
        if not value:
            return count
        count += 1
    return count


def _ma_cluster_spread_pct(
    ma10: float | None,
    ma20: float | None,
    ma30: float | None,
    close_price: float | None,
) -> float | None:
    if ma10 is None or ma20 is None or ma30 is None or close_price is None:
        return None
    return ((abs(ma10 - ma20) + abs(ma20 - ma30)) / 2 / close_price) * 100


def _absolute_distance_pct(
    first: float | None,
    second: float | None,
    close_price: float,
) -> float | None:
    if first is None or second is None:
        return None
    return abs(first - second) / close_price * 100


def _signed_distance_pct(price: float, reference: float | None) -> float | None:
    if reference is None:
        return None
    return _pct_change(price, reference)


def _pct_change(current: float, previous: float) -> float:
    return (current / previous - 1) * 100


def _convergence_score(current: float | None, previous: float | None) -> float:
    if current is None:
        return 0.0
    if previous is None or previous <= 0:
        return _clamp(1 - current / 3.0)
    return _clamp((previous - current) / max(previous, 0.5))


def _oversold_cross_phase_score(
    ma10: float | None,
    ma20: float | None,
    ma30: float | None,
    close_price: float,
) -> float:
    if ma10 is None or ma20 is None or ma30 is None:
        return 0.0
    ma10_near_ma20 = _absolute_distance_pct(ma10, ma20, close_price) or 0.0
    ma20_near_ma30 = _absolute_distance_pct(ma20, ma30, close_price) or 0.0
    score = 0.0
    if ma10 >= ma20:
        score += 0.5
    elif ma10_near_ma20 <= 1.5:
        score += 0.35
    if ma10 >= ma30:
        score += 0.2
    if ma20 >= ma30:
        score += 0.3
    elif ma20_near_ma30 <= 1.5:
        score += 0.15
    return _clamp(score)


def _oversold_close_quality(
    daily_return_pct: float,
    close_to_ma10_pct: float | None,
) -> float:
    if close_to_ma10_pct is None or not -5.0 <= daily_return_pct <= 3.0:
        return 0.0
    return _clamp(1 - abs(close_to_ma10_pct) / 4.0)


def _is_oversold_rebound(
    *,
    ma10: float | None,
    ma20: float | None,
    ma30: float | None,
    prior_bear_alignment_days: int,
    ma_cluster_spread_pct: float | None,
    ma10_ma20_distance_pct: float | None,
    daily_return_pct: float,
    close_to_ma10_pct: float | None,
) -> bool:
    if (
        ma10 is None
        or ma20 is None
        or ma30 is None
        or ma_cluster_spread_pct is None
        or ma10_ma20_distance_pct is None
        or close_to_ma10_pct is None
    ):
        return False
    return (
        prior_bear_alignment_days >= 5
        and ma_cluster_spread_pct <= 3.0
        and ma10_ma20_distance_pct <= 2.5
        and ma10 >= ma20 * 0.985
        and -5.0 <= daily_return_pct <= 3.0
        and abs(close_to_ma10_pct) <= 4.0
    )


def _trend_features(
    *,
    bar: DailyFactorBar,
    history: Sequence[DailyFactorBar],
    ma5: float | None,
    ma10: float | None,
    ma20: float | None,
    ma30: float | None,
    ma_series: Mapping[int, Sequence[float | None]],
    index: int,
    daily_return_pct: float,
) -> dict[str, object]:
    bull_aligned = _is_bull_aligned(ma10, ma20, ma30)
    slopes = tuple(_ma_slope_pct(ma_series[window], index) for window in (10, 20, 30))
    slope_values = tuple(slope for slope in slopes if slope is not None)
    all_slopes_up = len(slope_values) == 3 and all(slope > 0 for slope in slope_values)
    reference_name: str | None = None
    reference: float | None = None
    if bull_aligned and ma10 is not None:
        if ma5 is not None and ma5 > ma10:
            reference_name, reference = "ma5", ma5
        else:
            reference_name, reference = "ma10", ma10

    low_to_reference_pct = _signed_distance_pct(bar.low_price, reference)
    close_to_reference_pct = _signed_distance_pct(bar.close_price, reference)
    touched_support = (
        low_to_reference_pct is not None
        and close_to_reference_pct is not None
        and -4.0 <= low_to_reference_pct <= 1.5
        and close_to_reference_pct >= -1.5
    )
    support_score = (
        _clamp(1 - abs(low_to_reference_pct or 99.0) / 4.0)
        if touched_support
        else 0.0
    )
    recent_high = max(candidate.high_price for candidate in history[-20:])
    pullback_depth_pct = _pct_change(recent_high, bar.low_price)
    return {
        "trend_reference_line": reference_name,
        "trend_low_to_reference_pct": low_to_reference_pct,
        "trend_close_to_reference_pct": close_to_reference_pct,
        "trend_pullback_depth_pct": pullback_depth_pct,
        "trend_pullback_eligible": bool(
            bull_aligned
            and all_slopes_up
            and touched_support
            and daily_return_pct <= 3.0
        ),
        "trend_alignment": 1.0 if bull_aligned else 0.0,
        "trend_slope": _slope_score(slope_values),
        "trend_support": support_score,
        "trend_pullback": _clamp(pullback_depth_pct / 5.0),
    }


def _ma_slope_pct(series: Sequence[float | None], index: int) -> float | None:
    if index < TREND_SLOPE_LOOKBACK:
        return None
    current = series[index]
    previous = series[index - TREND_SLOPE_LOOKBACK]
    if current is None or previous is None:
        return None
    return _pct_change(current, previous)


def _slope_score(slopes: Sequence[float]) -> float:
    if len(slopes) != 3 or any(slope <= 0 for slope in slopes):
        return 0.0
    return _clamp(fmean(slopes) / 2.0)


def _volume_features(
    bars: Sequence[DailyFactorBar],
    daily_return_pct: float,
) -> dict[str, object]:
    volumes = [bar.volume for bar in bars]
    recent5 = volumes[-5:]
    recent10 = volumes[-10:]
    if len(recent5) < 5 or any(value is None for value in recent5):
        return {
            "volume_spearman_5d": None,
            "volume_spearman_10d": None,
            "volume_up_streak": 0,
            "volume_down_streak": 0,
            "conditional_volume": None,
        }
    values5 = [float(value) for value in recent5 if value is not None]
    values10 = [float(value) for value in recent10 if value is not None]
    spearman5 = _spearman_against_time(values5)
    spearman10 = _spearman_against_time(values10) if len(values10) == 10 else None
    if daily_return_pct <= 0 and spearman5 <= -0.3:
        conditional_score = 1.0
    elif daily_return_pct > 0 and spearman5 >= 0.3:
        conditional_score = 0.75
    else:
        conditional_score = 0.25
    return {
        "volume_spearman_5d": spearman5,
        "volume_spearman_10d": spearman10,
        "volume_up_streak": _strict_direction_streak(values5, increasing=True),
        "volume_down_streak": _strict_direction_streak(values5, increasing=False),
        "conditional_volume": conditional_score,
    }


def _spearman_against_time(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    ranks = _average_ranks(values)
    time_ranks = list(range(1, len(values) + 1))
    mean_rank = fmean(ranks)
    mean_time = fmean(time_ranks)
    numerator = sum((rank - mean_rank) * (time - mean_time) for rank, time in zip(ranks, time_ranks))
    rank_variance = sum((rank - mean_rank) ** 2 for rank in ranks)
    time_variance = sum((time - mean_time) ** 2 for time in time_ranks)
    denominator = math.sqrt(rank_variance * time_variance)
    return numerator / denominator if denominator else 0.0


def _average_ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and ordered[end][1] == ordered[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for position in range(start, end):
            ranks[ordered[position][0]] = average_rank
        start = end
    return ranks


def _strict_direction_streak(values: Sequence[float], *, increasing: bool) -> int:
    count = 0
    for previous, current in zip(reversed(values[:-1]), reversed(values[1:])):
        is_directional = current > previous if increasing else current < previous
        if not is_directional:
            break
        count += 1
    return count


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
