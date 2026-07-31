"""Point-in-time features shared by the four limit-up trading lanes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta
from functools import cache

import pandas as pd

LIMIT_TOUCH_PCT = 9.7
LIMIT_BREAK_PCT = 9.2


def attach_limit_gene_features(
    frame: pd.DataFrame,
    *,
    copy_frame: bool = True,
) -> pd.DataFrame:
    """Attach shifted limit-up gene and price-position features.

    Every rolling input is shifted by one trading row.  The signal day's
    final limit-up result therefore cannot enter its own feature values.
    """

    if frame.empty:
        return frame.copy() if copy_frame else frame
    result = frame.copy() if copy_frame else frame
    result.sort_values(["vt_symbol", "trade_date"], kind="stable", inplace=True)
    result["sealed"] = result["sealed"].fillna(False).astype(bool)
    result["touched"] = result["touched"].fillna(False).astype(bool)
    if "high_price" not in result:
        result["high_price"] = result["close_price"]
    grouped = result.groupby("vt_symbol", sort=False)

    sealed_cumulative = grouped["sealed"].cumsum()
    touched_cumulative = grouped["touched"].cumsum()
    result["prior_limit_count_126"] = _prior_group_count(
        sealed_cumulative,
        result["vt_symbol"],
        126,
    )
    result["prior_touch_count_126"] = _prior_group_count(
        touched_cumulative,
        result["vt_symbol"],
        126,
    )
    result["prior_limit_count_5"] = _prior_group_count(
        sealed_cumulative,
        result["vt_symbol"],
        5,
    )
    result["prior_limit_count_10"] = _prior_group_count(
        sealed_cumulative,
        result["vt_symbol"],
        10,
    )
    result["prior_limit_count_42"] = _prior_group_count(
        sealed_cumulative,
        result["vt_symbol"],
        42,
    )
    result["prior_limit_count_63"] = _prior_group_count(
        sealed_cumulative,
        result["vt_symbol"],
        63,
    )
    result["prior_seal_success_rate_126"] = (
        result["prior_limit_count_126"]
        / result["prior_touch_count_126"].replace(0, pd.NA)
    )

    prior_close = grouped["close_price"].shift(1)
    prior_bounds = _prior_price_bounds(
        result[["low_price", "high_price"]],
        result["vt_symbol"],
    )
    prior_low_120 = prior_bounds["low_price"]
    prior_high_120 = prior_bounds["high_price"]
    position_range = (prior_high_120 - prior_low_120).replace(0, pd.NA)
    result["prior_position_120"] = (
        (prior_close - prior_low_120) / position_range
    ).clip(lower=0, upper=1)

    trade_index = grouped.cumcount()
    limit_index = trade_index.where(result["sealed"])
    last_limit_index = limit_index.groupby(result["vt_symbol"], sort=False).ffill()
    last_limit_index = last_limit_index.groupby(result["vt_symbol"], sort=False).shift(1)
    limit_close = result["close_price"].where(result["sealed"])
    last_limit_close = limit_close.groupby(result["vt_symbol"], sort=False).ffill()
    last_limit_close = last_limit_close.groupby(result["vt_symbol"], sort=False).shift(1)
    result["trade_days_since_prior_limit"] = trade_index - last_limit_index
    result["pullback_from_prior_limit_pct"] = (
        (prior_close / last_limit_close - 1) * 100
    )
    result["recent_structure_board_count"] = result["prior_limit_count_5"] + 1
    return result


def _prior_group_count(
    cumulative: pd.Series,
    groups: pd.Series,
    window: int,
) -> pd.Series:
    grouped = cumulative.groupby(groups, sort=False)
    prior_total = grouped.shift(1, fill_value=0)
    before_window = grouped.shift(window + 1, fill_value=0)
    return (prior_total - before_window).fillna(0).astype(int)


def _prior_price_bounds(
    prices: pd.DataFrame,
    groups: pd.Series,
) -> pd.DataFrame:
    valid_groups = groups.notna()
    bounds = pd.DataFrame(index=prices.index, columns=prices.columns, dtype=float)
    if not valid_groups.any():
        return bounds

    shifted = prices.groupby(groups, sort=False).shift(1)
    rolled = (
        shifted.loc[valid_groups]
        .groupby(groups.loc[valid_groups], sort=False)
        .rolling(120, min_periods=20)
        .agg({"low_price": "min", "high_price": "max"})
    )
    positions = valid_groups.to_numpy().nonzero()[0]
    bounds.iloc[positions] = rolled.to_numpy()
    return bounds


@cache
def intraday_path_times() -> tuple[str, ...]:
    """Return the documented 80-point, three-minute A-share session grid."""

    morning = _time_grid(time(9, 30), 40)
    afternoon = _time_grid(time(13, 0), 40)
    return tuple([*morning, *afternoon])


def minute_bars_to_intraday_price_path(
    bars: Sequence[Mapping[str, object]],
) -> list[float | None]:
    """Resample one-minute bars onto the existing 80-point session grid."""

    bars_by_time: dict[time, Mapping[str, object]] = {}
    for bar in bars:
        bar_time = _bar_time(bar.get("bar_time"))
        if bar_time is not None:
            bars_by_time[bar_time] = bar

    session_opens = {
        time(9, 30): time(9, 31),
        time(13, 0): time(13, 1),
    }
    prices: list[float | None] = []
    for point_text in intraday_path_times():
        point_time = _parse_time(point_text)
        if point_time in session_opens:
            bar = bars_by_time.get(session_opens[point_time])
            prices.append(_number(bar.get("open_price")) if bar else None)
            continue
        bar = bars_by_time.get(point_time)
        prices.append(_number(bar.get("close_price")) if bar else None)
    return prices


def price_path_to_return_path(
    prices: Sequence[object],
    *,
    previous_close: object,
) -> list[float | None]:
    """Convert point-in-time prices to percentage changes from D-1 close."""

    baseline = _number(previous_close)
    if baseline is None or baseline <= 0:
        return []
    return [
        round((price / baseline - 1) * 100, 4)
        if (price := _number(raw_price)) is not None and price > 0
        else None
        for raw_price in prices
    ]


def path_prefix_features(
    path: Sequence[object],
    signal_time: str,
    *,
    touch_threshold: float = LIMIT_TOUCH_PCT,
    break_threshold: float = LIMIT_BREAK_PCT,
) -> dict[str, object]:
    """Summarize only completed path points at or before ``signal_time``."""

    cutoff = _parse_time(signal_time)
    values: list[float] = []
    used_times: list[str] = []
    for point_time, raw_value in zip(intraday_path_times(), path, strict=False):
        if _parse_time(point_time) > cutoff:
            break
        value = _number(raw_value)
        if value is None:
            continue
        values.append(value)
        used_times.append(point_time)

    touch_count = 0
    break_count = 0
    reseal_count = 0
    has_touched = False
    is_broken = False
    for value in values:
        if value >= touch_threshold:
            if not has_touched:
                touch_count += 1
                has_touched = True
            elif is_broken:
                touch_count += 1
                reseal_count += 1
            is_broken = False
        elif has_touched and value < break_threshold and not is_broken:
            break_count += 1
            is_broken = True

    recent_15m = values[-6:]
    recent_30m = values[-11:]

    return {
        "signal_time": signal_time,
        "last_point_time": used_times[-1] if used_times else None,
        "point_count": len(values),
        "last_pct": round(values[-1], 4) if values else None,
        "maximum_pct": round(max(values), 4) if values else None,
        "minimum_pct": round(min(values), 4) if values else None,
        "recent_15m_min_pct": _rounded_min(recent_15m),
        "recent_15m_change_pct": _rounded_change(recent_15m),
        "recent_15m_range_pct": _rounded_range(recent_15m),
        "recent_15m_drawdown_pct": _rounded_drawdown(recent_15m),
        "recent_30m_min_pct": _rounded_min(recent_30m),
        "recent_30m_change_pct": _rounded_change(recent_30m),
        "touch_count": touch_count,
        "break_count": break_count,
        "reseal_count": reseal_count,
        "is_at_limit": bool(values and values[-1] >= touch_threshold),
        "approach_3point_pct": (
            round(values[-1] - values[-4], 4) if len(values) >= 4 else None
        ),
    }


def _rounded_min(values: Sequence[float]) -> float | None:
    return round(min(values), 4) if values else None


def _rounded_change(values: Sequence[float]) -> float | None:
    return round(values[-1] - values[0], 4) if len(values) >= 2 else None


def _rounded_range(values: Sequence[float]) -> float | None:
    return round(max(values) - min(values), 4) if values else None


def _rounded_drawdown(values: Sequence[float]) -> float | None:
    return round(values[-1] - max(values), 4) if values else None


def first_reseal_time(
    path: Sequence[object],
    *,
    not_before: str = "10:00:00",
    touch_threshold: float = LIMIT_TOUCH_PCT,
    break_threshold: float = LIMIT_BREAK_PCT,
) -> str | None:
    """Return the first observable reseal time without reading later points."""

    earliest = _parse_time(not_before)
    touched = False
    broken = False
    for point_time, raw_value in zip(intraday_path_times(), path, strict=False):
        value = _number(raw_value)
        if value is None:
            continue
        if value >= touch_threshold:
            if touched and broken and _parse_time(point_time) >= earliest:
                return point_time
            touched = True
            broken = False
        elif touched and value < break_threshold:
            broken = True
    return None


def select_latest_published_report(
    reports: Sequence[Mapping[str, object]],
    signal_date: date,
) -> dict[str, object] | None:
    """Select the latest report that was public by ``signal_date``."""

    available: list[tuple[date, str, Mapping[str, object]]] = []
    for report in reports:
        publish_date = _date_value(report.get("publish_date"))
        if publish_date is None or publish_date > signal_date:
            continue
        available.append(
            (publish_date, str(report.get("report_date") or ""), report)
        )
    if not available:
        return None
    return dict(max(available, key=lambda item: (item[0], item[1]))[2])


def classify_financial_risk(
    report: Mapping[str, object] | None,
) -> dict[str, object]:
    """Classify severe, already-published fundamental deterioration."""

    if not report:
        return {
            "level": "unknown",
            "blocked": False,
            "reasons": ["financial_report_missing"],
            "publish_date": None,
        }
    reasons: list[str] = []
    net_profit = _number(report.get("net_profit"))
    deducted_profit = _number(report.get("deducted_net_profit"))
    if net_profit is not None and deducted_profit is not None and net_profit < 0 and deducted_profit < 0:
        reasons.append("loss_making")
    revenue_yoy = _number(report.get("revenue_yoy"))
    if revenue_yoy is not None and revenue_yoy <= -30:
        reasons.append("revenue_collapse")
    debt_ratio = _number(report.get("debt_asset_ratio"))
    if debt_ratio is not None and debt_ratio >= 85:
        reasons.append("high_leverage")
    cash_quality = _number(report.get("cash_flow_quality"))
    if cash_quality is not None and cash_quality < 0:
        reasons.append("weak_cash_flow")
    blocked = len(reasons) >= 2
    return {
        "level": "blocked" if blocked else "caution" if reasons else "clear",
        "blocked": blocked,
        "reasons": reasons,
        "publish_date": str(report.get("publish_date") or "")[:10] or None,
    }


def _time_grid(start: time, count: int) -> list[str]:
    anchor = datetime.combine(date(2000, 1, 1), start)
    return [(anchor + timedelta(minutes=index * 3)).time().isoformat() for index in range(count)]


@cache
def _parse_time(value: str) -> time:
    try:
        return time.fromisoformat(str(value)[:8])
    except ValueError as exc:
        raise ValueError(f"invalid intraday time: {value}") from exc


def _bar_time(value: object) -> time | None:
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).time().replace(
            microsecond=0
        )
    except ValueError:
        try:
            return time.fromisoformat(text[:8]).replace(microsecond=0)
        except ValueError:
            return None


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        if len(text) >= 8 and text[:8].isdigit():
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
