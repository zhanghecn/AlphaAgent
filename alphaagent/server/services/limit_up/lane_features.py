"""Point-in-time features shared by the four limit-up trading lanes."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Mapping, Sequence

import pandas as pd

LIMIT_TOUCH_PCT = 9.7
LIMIT_BREAK_PCT = 9.2


def attach_limit_gene_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach shifted limit-up gene and price-position features.

    Every rolling input is shifted by one trading row.  The signal day's
    final limit-up result therefore cannot enter its own feature values.
    """

    if frame.empty:
        return frame.copy()
    result = frame.copy().sort_values(["vt_symbol", "trade_date"], kind="stable")
    result["sealed"] = result["sealed"].fillna(False).astype(bool)
    result["touched"] = result["touched"].fillna(False).astype(bool)
    if "high_price" not in result:
        result["high_price"] = result["close_price"]
    grouped = result.groupby("vt_symbol", sort=False)

    result["prior_limit_count_126"] = grouped["sealed"].transform(
        lambda values: values.shift(1).rolling(126, min_periods=1).sum()
    ).fillna(0).astype(int)
    result["prior_touch_count_126"] = grouped["touched"].transform(
        lambda values: values.shift(1).rolling(126, min_periods=1).sum()
    ).fillna(0).astype(int)
    result["prior_limit_count_5"] = grouped["sealed"].transform(
        lambda values: values.shift(1).rolling(5, min_periods=1).sum()
    ).fillna(0).astype(int)
    result["prior_limit_count_10"] = grouped["sealed"].transform(
        lambda values: values.shift(1).rolling(10, min_periods=1).sum()
    ).fillna(0).astype(int)
    result["prior_seal_success_rate_126"] = (
        result["prior_limit_count_126"]
        / result["prior_touch_count_126"].replace(0, pd.NA)
    )

    prior_close = grouped["close_price"].shift(1)
    prior_low_120 = grouped["low_price"].transform(
        lambda values: values.shift(1).rolling(120, min_periods=20).min()
    )
    prior_high_120 = grouped["high_price"].transform(
        lambda values: values.shift(1).rolling(120, min_periods=20).max()
    )
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


def intraday_path_times() -> tuple[str, ...]:
    """Return the documented 80-point, three-minute A-share session grid."""

    morning = _time_grid(time(9, 30), 40)
    afternoon = _time_grid(time(13, 0), 40)
    return tuple([*morning, *afternoon])


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


def _parse_time(value: str) -> time:
    try:
        return time.fromisoformat(str(value)[:8])
    except ValueError as exc:
        raise ValueError(f"invalid intraday time: {value}") from exc


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
