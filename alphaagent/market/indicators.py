"""Derived indicators from real K-line bars.

These values are display-time indicators. They are computed from the same real
AkShare K-line data used by the chart, so the current display stage does not
need historical bar persistence.
"""

from __future__ import annotations

import math
from statistics import pstdev
from typing import Any


def compute_bar_indicators(vt_symbol: str, bars: list[dict[str, Any]], source: str | None = None) -> dict[str, Any]:
    """Compute common A-share chart indicators from K-line bars."""

    closes = [_as_float(bar.get("close")) for bar in bars]
    highs = [_as_float(bar.get("high")) for bar in bars]
    lows = [_as_float(bar.get("low")) for bar in bars]
    volumes = [_as_float(bar.get("volume")) for bar in bars]
    valid_closes = [value for value in closes if value is not None]
    valid_highs = [value for value in highs if value is not None]
    valid_lows = [value for value in lows if value is not None]

    latest_close = valid_closes[-1] if valid_closes else None
    ma = {f"ma{window}": _moving_average(valid_closes, window) for window in (5, 10, 20, 60)}
    volume_ma = {f"volume_ma{window}": _moving_average([v for v in volumes if v is not None], window) for window in (5, 10, 20)}

    latest_change_pct = _period_return(valid_closes, 1)
    returns = _daily_returns(valid_closes)
    boll = _bollinger(valid_closes, 20, 2)
    macd = _macd(valid_closes)
    kdj = _kdj(valid_highs, valid_lows, valid_closes)
    rsi = {f"rsi{window}": _rsi(valid_closes, window) for window in (6, 12, 24)}

    return {
        "vt_symbol": vt_symbol,
        "status": "ready" if len(valid_closes) >= 5 else "insufficient_data",
        "source": source,
        "sample_size": len(valid_closes),
        "latest_close": latest_close,
        "latest_change_pct": latest_change_pct,
        "moving_average": ma,
        "volume_average": volume_ma,
        "period_return": {
            "return_20d": _period_return(valid_closes, 20),
            "return_60d": _period_return(valid_closes, 60),
        },
        "volatility": {
            "volatility_20d": _annualized_volatility(returns, 20),
            "volatility_60d": _annualized_volatility(returns, 60),
        },
        "drawdown": {
            "max_drawdown_60d": _max_drawdown(valid_closes[-60:]),
        },
        "bollinger": boll,
        "macd": macd,
        "kdj": kdj,
        "rsi": rsi,
        "price_position": {
            "above_ma20": _above(latest_close, ma.get("ma20")),
            "above_ma60": _above(latest_close, ma.get("ma60")),
            "boll_percent_b": _boll_percent_b(latest_close, boll),
        },
    }


def _as_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def _ema_series(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2 / (period + 1)
    result = [values[0]]
    for value in values[1:]:
        result.append(value * alpha + result[-1] * (1 - alpha))
    return result


def _period_return(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    start = values[-window - 1]
    end = values[-1]
    if start == 0:
        return None
    return (end / start - 1) * 100


def _daily_returns(values: list[float]) -> list[float]:
    returns: list[float] = []
    for previous, current in zip(values, values[1:]):
        if previous == 0:
            continue
        returns.append(current / previous - 1)
    return returns


def _bollinger(values: list[float], window: int, multiplier: float) -> dict[str, float | None]:
    if len(values) < window:
        return {"mid": None, "upper": None, "lower": None, "width": None}
    window_values = values[-window:]
    mid = sum(window_values) / window
    std = pstdev(window_values)
    upper = mid + multiplier * std
    lower = mid - multiplier * std
    width = (upper - lower) / mid * 100 if mid else None
    return {"mid": mid, "upper": upper, "lower": lower, "width": width}


def _macd(values: list[float]) -> dict[str, float | None]:
    if len(values) < 35:
        return {"dif": None, "dea": None, "macd": None}
    ema12 = _ema_series(values, 12)
    ema26 = _ema_series(values, 26)
    dif_series = [fast - slow for fast, slow in zip(ema12, ema26)]
    dea_series = _ema_series(dif_series, 9)
    dif = dif_series[-1]
    dea = dea_series[-1]
    return {"dif": dif, "dea": dea, "macd": (dif - dea) * 2}


def _kdj(highs: list[float], lows: list[float], closes: list[float], window: int = 9) -> dict[str, float | None]:
    if len(closes) < window or len(highs) < window or len(lows) < window:
        return {"k": None, "d": None, "j": None}
    k = 50.0
    d = 50.0
    start = window - 1
    for index in range(start, len(closes)):
        high = max(highs[index - window + 1 : index + 1])
        low = min(lows[index - window + 1 : index + 1])
        rsv = 50.0 if high == low else (closes[index] - low) / (high - low) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
    return {"k": k, "d": d, "j": 3 * k - 2 * d}


def _rsi(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    changes = [current - previous for previous, current in zip(values, values[1:])][-window:]
    gains = [max(change, 0) for change in changes]
    losses = [abs(min(change, 0)) for change in changes]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def _annualized_volatility(returns: list[float], window: int) -> float | None:
    if len(returns) < window:
        return None
    return pstdev(returns[-window:]) * math.sqrt(252) * 100


def _max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None

    peak = values[0]
    max_drawdown = 0.0
    for value in values:
        peak = max(peak, value)
        if peak == 0:
            continue
        drawdown = (value / peak - 1) * 100
        max_drawdown = min(max_drawdown, drawdown)
    return max_drawdown


def _above(value: float | None, reference: float | None) -> bool | None:
    if value is None or reference is None:
        return None
    return value >= reference


def _boll_percent_b(value: float | None, boll: dict[str, float | None]) -> float | None:
    upper = boll.get("upper")
    lower = boll.get("lower")
    if value is None or upper is None or lower is None or upper == lower:
        return None
    return (value - lower) / (upper - lower)
