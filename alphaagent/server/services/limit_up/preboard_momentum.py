"""Causal five-minute features and frozen pre-board momentum rules."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from statistics import median
from alphaagent.server.services.limit_up import scheduled_execution


FEATURE_NAMES = (
    "gain_pct",
    "return_5m_pct",
    "return_15m_pct",
    "return_30m_pct",
    "acceleration_pct",
    "prior_30m_range_pct",
    "prior_30m_floor_pct",
    "breakout_margin_pct",
    "session_drawdown_pct",
    "volume_ratio_30m",
    "bar_close_location",
    "opening_gap_pct",
    "minute_of_window",
)
HISTORY_FEATURE_NAMES = (
    "prior_limit_count_126",
    "prior_touch_count_126",
    "prior_seal_success_rate_pct_126",
    "stock_d1_sample_count",
    "stock_d1_win_rate",
    "stock_d1_average_return_pct",
    "stock_gene_combined_win_rate",
)
SEAL_MODEL_FEATURE_NAMES = (*FEATURE_NAMES, *HISTORY_FEATURE_NAMES)
RULE_ALGORITHMS = (
    "support_3pct",
    "acceleration",
    "compression_breakout",
    "hybrid_rule",
)
ALGORITHMS = (*RULE_ALGORITHMS, "logistic_imminent")


def build_prefix_rows(
    manifest_row: Mapping[str, object],
    bars: Sequence[Mapping[str, object]],
    *,
    bar_minutes: int = 5,
) -> list[dict[str, object]]:
    """Build completed-bar feature rows with a causal next-bar fill quote."""

    _validate_bar_minutes(bar_minutes)
    ordered = sorted(
        (dict(row) for row in bars),
        key=lambda row: _as_datetime(row.get("bar_time")) or datetime.max,
    )
    return _build_ordered_prefix_rows(
        manifest_row,
        ordered,
        bar_minutes=bar_minutes,
    )


def _build_ordered_prefix_rows(
    manifest_row: Mapping[str, object],
    ordered: Sequence[Mapping[str, object]],
    *,
    bar_minutes: int,
) -> list[dict[str, object]]:
    previous_close = _number(manifest_row.get("previous_close"))
    limit_price = _number(manifest_row.get("limit_price"))
    if previous_close is None or previous_close <= 0 or limit_price is None:
        return []
    if len(ordered) < 2:
        return []
    opening_price = _number(ordered[0].get("open_price"))
    opening_gap = _return_pct(previous_close, opening_price)
    prior_features = _prior_recommendation_features(manifest_row)
    bar_times = [_as_datetime(row.get("bar_time")) for row in ordered]
    running_high: float | None = None
    prefix_rows: list[dict[str, object]] = []

    for index, bar in enumerate(ordered[:-1]):
        bar_high = _number(bar.get("high_price"))
        if bar_high is not None:
            running_high = (
                bar_high if running_high is None else max(running_high, bar_high)
            )
        decision_at = bar_times[index]
        next_bar = ordered[index + 1]
        next_close_at = bar_times[index + 1]
        if decision_at is None or next_close_at is None:
            continue
        decision_time = decision_at.strftime("%H:%M:%S")
        entry_at = next_close_at - timedelta(minutes=bar_minutes - 1)
        if not scheduled_execution.is_entry_time(decision_time) or _entry_window_index(
            decision_at
        ) != _entry_window_index(entry_at):
            continue
        features = _prefix_features(
            ordered,
            index,
            previous_close=previous_close,
            opening_gap=opening_gap,
            bar_minutes=bar_minutes,
            session_high=running_high,
        )
        features.update(prior_features)
        signal_price = _number(bar.get("close_price"))
        entry_price = _number(next_bar.get("open_price"))
        prefix_rows.append(
            {
                "vt_symbol": str(manifest_row.get("vt_symbol") or ""),
                "name": str(manifest_row.get("name") or ""),
                "signal_date": str(manifest_row.get("trade_date") or "")[:10],
                "result_date": str(manifest_row.get("result_date") or "")[:10] or None,
                "signal_at": decision_at.isoformat(),
                "signal_time": decision_time,
                "entry_at": entry_at.isoformat(),
                "entry_time": entry_at.strftime("%H:%M:%S"),
                "signal_price": signal_price,
                "entry_price": entry_price,
                "limit_price": limit_price,
                "fillable": bool(
                    entry_price is not None
                    and entry_price > 0
                    and entry_price < limit_price - 0.001
                ),
                "before_first_limit_touch": bool(
                    running_high is not None and running_high < limit_price - 0.001
                ),
                "features": features,
                "touched_limit": bool(manifest_row.get("touched_limit")),
                "sealed_limit": bool(manifest_row.get("sealed_limit")),
                "d1_close_price": _number(manifest_row.get("d1_close_price")),
            }
        )
    return prefix_rows


def first_rule_signal(
    prefix_rows: Sequence[Mapping[str, object]],
    algorithm: str,
) -> dict[str, object] | None:
    """Return the first fillable row passing one frozen deterministic rule."""

    if algorithm not in RULE_ALGORITHMS:
        raise ValueError(f"unsupported rule algorithm: {algorithm}")
    for raw in sorted(prefix_rows, key=lambda row: str(row.get("signal_at") or "")):
        row = dict(raw)
        features = row.get("features")
        features = features if isinstance(features, Mapping) else {}
        if (
            row.get("fillable") is True
            and row.get("before_first_limit_touch") is True
            and _rule_passes(features, algorithm)
        ):
            return {**row, "algorithm": algorithm}
    return None


def _prefix_features(
    bars: Sequence[Mapping[str, object]],
    index: int,
    *,
    previous_close: float,
    opening_gap: float | None,
    bar_minutes: int,
    session_high: float | None,
) -> dict[str, float | None]:
    bar = bars[index]
    close = _number(bar.get("close_price"))
    high = _number(bar.get("high_price"))
    low = _number(bar.get("low_price"))
    if close is None or high is None or low is None:
        return {**{name: None for name in FEATURE_NAMES}, "support_score": None}
    periods_5m = 5 // bar_minutes
    periods_15m = 15 // bar_minutes
    periods_30m = 30 // bar_minutes
    return_5m = _bar_return(bars, index, periods_5m)
    return_15m = _bar_return(bars, index, periods_15m)
    return_30m = _bar_return(bars, index, periods_30m)
    prior_return_5m = (
        _bar_return(bars, index - 1, periods_5m) if index >= periods_5m + 1 else None
    )
    prior_30m = bars[max(0, index - periods_30m) : index]
    prior_highs = _numbers(prior_30m, "high_price")
    prior_lows = _numbers(prior_30m, "low_price")
    prior_volumes = [value for value in _numbers(prior_30m, "volume") if value > 0]
    current_volume = _number(bar.get("volume"))
    decision_at = _as_datetime(bar.get("bar_time"))
    prior_volume_median = (
        median(prior_volumes) if len(prior_volumes) == periods_30m else None
    )
    features: dict[str, float | None] = {
        "gain_pct": _return_pct(previous_close, close),
        "return_5m_pct": return_5m,
        "return_15m_pct": return_15m,
        "return_30m_pct": return_30m,
        "acceleration_pct": (
            return_5m - prior_return_5m
            if return_5m is not None and prior_return_5m is not None
            else None
        ),
        "prior_30m_range_pct": (
            (max(prior_highs) - min(prior_lows)) / previous_close * 100
            if len(prior_highs) == periods_30m and len(prior_lows) == periods_30m
            else None
        ),
        "prior_30m_floor_pct": (
            _return_pct(previous_close, min(prior_lows))
            if len(prior_lows) == periods_30m
            else None
        ),
        "breakout_margin_pct": (
            _return_pct(max(prior_highs), close)
            if len(prior_highs) == periods_30m
            else None
        ),
        "session_drawdown_pct": (
            _return_pct(session_high, close) if session_high is not None else None
        ),
        "volume_ratio_30m": (
            current_volume / prior_volume_median
            if current_volume is not None
            and current_volume > 0
            and prior_volume_median is not None
            and prior_volume_median > 0
            else None
        ),
        "bar_close_location": ((close - low) / (high - low) if high > low else 1.0),
        "opening_gap_pct": opening_gap,
        "minute_of_window": (
            float(_minute_of_window(decision_at)) if decision_at is not None else None
        ),
    }
    features["support_score"] = _support_score(
        bars,
        index,
        previous_close=previous_close,
        bar_minutes=bar_minutes,
    )
    if bar_minutes == 1:
        prior_5m = bars[max(0, index - 5) : index]
        prior_5m_volumes = [
            value for value in _numbers(prior_5m, "volume") if value > 0
        ]
        current_turnover = _number(bar.get("turnover"))
        prior_turnover = _number(bars[index - 1].get("turnover")) if index > 0 else None
        current_volume = _number(bar.get("volume"))
        features.update(
            {
                "return_1m_pct": _bar_return(bars, index, 1),
                "return_3m_pct": _bar_return(bars, index, 3),
                "volume_ratio_5m": (
                    current_volume / median(prior_5m_volumes)
                    if current_volume is not None
                    and current_volume > 0
                    and len(prior_5m_volumes) == 5
                    and median(prior_5m_volumes) > 0
                    else None
                ),
                "turnover_acceleration_1m": (
                    current_turnover / prior_turnover
                    if current_turnover is not None
                    and current_turnover > 0
                    and prior_turnover is not None
                    and prior_turnover > 0
                    else None
                ),
            }
        )
    return {key: _rounded(value) for key, value in features.items()}


def _rule_passes(features: Mapping[str, object], algorithm: str) -> bool:
    gain = _number(features.get("gain_pct"))
    in_gain_range = gain is not None and gain >= 3.0
    support = in_gain_range and _at_least(features, "support_score", 55.0)
    acceleration = bool(
        in_gain_range
        and _at_least(features, "return_5m_pct", 0.8)
        and _at_least(features, "return_15m_pct", 1.5)
        and _at_least(features, "session_drawdown_pct", -0.3)
        and _at_least(features, "volume_ratio_30m", 1.5)
        and _at_least(features, "bar_close_location", 0.7)
    )
    compression = bool(
        in_gain_range
        and _at_most(features, "prior_30m_range_pct", 1.5)
        and _at_least(features, "prior_30m_floor_pct", 2.0)
        and _at_least(features, "breakout_margin_pct", 0.2)
        and _at_least(features, "return_5m_pct", 0.5)
        and _at_least(features, "volume_ratio_30m", 1.5)
        and _at_least(features, "bar_close_location", 0.7)
    )
    return {
        "support_3pct": support,
        "acceleration": acceleration,
        "compression_breakout": compression,
        "hybrid_rule": acceleration or compression,
    }[algorithm]


def _prior_recommendation_features(
    manifest_row: Mapping[str, object],
) -> dict[str, float | None]:
    return {
        "prior_limit_count_126": _number(manifest_row.get("prior_limit_count_126")),
        "prior_touch_count_126": _number(manifest_row.get("prior_touch_count_126")),
        "prior_seal_success_rate_pct_126": _percentage(
            manifest_row.get("prior_seal_success_rate_126")
        ),
        "stock_d1_sample_count": _number(manifest_row.get("stock_d1_sample_count")),
        "stock_d1_win_rate": _percentage(manifest_row.get("stock_d1_win_rate")),
        "stock_d1_average_return_pct": _number(
            manifest_row.get("stock_d1_average_return_pct")
        ),
        "stock_gene_combined_win_rate": _percentage(
            manifest_row.get("stock_gene_combined_win_rate")
        ),
    }


def _support_score(
    bars: Sequence[Mapping[str, object]],
    index: int,
    *,
    previous_close: float,
    bar_minutes: int = 5,
) -> float | None:
    prior_30m_points = 30 // bar_minutes
    recent_15m_points = 15 // bar_minutes + 1
    if index + 1 < prior_30m_points:
        return None
    recent = bars[max(0, index - recent_15m_points + 1) : index + 1]
    changes = [
        value
        for row in recent
        if (value := _return_pct(previous_close, _number(row.get("close_price"))))
        is not None
    ]
    if len(changes) < recent_15m_points:
        return None
    recent_change = changes[-1] - changes[0]
    recent_floor = min(changes)
    recent_drawdown = changes[-1] - max(changes)
    approach = recent_change
    score = 45.0
    score += _clamp(recent_change, -4.0, 6.0) * 4.0
    score += _clamp(recent_floor, -2.0, 6.0) * 2.0
    score += _clamp(approach, -3.0, 4.0) * 3.0
    score -= abs(min(recent_drawdown, 0.0)) * 8.0
    return _clamp(score, 0.0, 100.0)


def _bar_return(
    bars: Sequence[Mapping[str, object]],
    index: int,
    periods: int,
) -> float | None:
    if index < periods or index >= len(bars):
        return None
    baseline = _number(bars[index - periods].get("close_price"))
    current = _number(bars[index].get("close_price"))
    return _return_pct(baseline, current)


def _validate_bar_minutes(value: int) -> None:
    if value not in {1, 5}:
        raise ValueError("bar_minutes must be 1 or 5")


def _entry_window_index(value: datetime) -> int | None:
    time_text = value.strftime("%H:%M:%S")
    return next(
        (
            index
            for index, (start, end) in enumerate(scheduled_execution.ENTRY_WINDOWS)
            if start <= time_text < end
        ),
        None,
    )


def _minute_of_window(value: datetime) -> int:
    local_minute = value.hour * 60 + value.minute
    start = 10 * 60 if value.hour < 12 else 13 * 60
    return local_minute - start


def _numbers(rows: Sequence[Mapping[str, object]], key: str) -> list[float]:
    return [value for row in rows if (value := _number(row.get(key))) is not None]


def _return_pct(baseline: float | None, value: float | None) -> float | None:
    if baseline is None or baseline <= 0 or value is None:
        return None
    return (value / baseline - 1) * 100


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _percentage(value: object) -> float | None:
    parsed = _number(value)
    if parsed is None or parsed < 0:
        return None
    if parsed <= 1:
        return round(parsed * 100, 6)
    return round(parsed, 6) if parsed <= 100 else None


def _as_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _at_least(features: Mapping[str, object], key: str, threshold: float) -> bool:
    value = _number(features.get(key))
    return value is not None and value >= threshold


def _at_most(features: Mapping[str, object], key: str, threshold: float) -> bool:
    value = _number(features.get(key))
    return value is not None and value <= threshold


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None
