"""Transparent daily-bar factors for AlphaAgent quant screening."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Any


DRAGON_PULLBACK_STRATEGY_ID = "mainline_dragon_pullback"
DRAGON_PULLBACK_STRATEGY_VERSION = "0.1.18"
STRATEGY_ID = DRAGON_PULLBACK_STRATEGY_ID
STRATEGY_VERSION = DRAGON_PULLBACK_STRATEGY_VERSION
LEADER_PULLBACK_STRATEGY_ID = "mainline_leader_pullback"
LEADER_PULLBACK_STRATEGY_VERSION = "0.1.1"
BREAKOUT_STRATEGY_ID = "breakout_confirmation"
BREAKOUT_STRATEGY_VERSION = "0.1.0"
LIMIT_UP_PULLBACK_STRATEGY_ID = "limit_up_after_pullback"
LIMIT_UP_PULLBACK_STRATEGY_VERSION = "0.1.0"
TREND_ACCELERATION_STRATEGY_ID = "trend_acceleration"
TREND_ACCELERATION_STRATEGY_VERSION = "0.1.0"


@dataclass(frozen=True)
class Bar:
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float | None = None
    turnover: float | None = None
    change_pct: float | None = None


@dataclass
class SignalScore:
    vt_symbol: str
    trade_date: date
    signal_type: str = STRATEGY_ID
    total_score: float = 0.0
    relative_strength_score: float = 0.0
    washout_score: float = 0.0
    trend_quality_score: float = 0.0
    sector_mainline_score: float = 50.0
    financial_improvement_score: float = 50.0
    fund_flow_score: float = 50.0
    hot_rank_score: float = 50.0
    lhb_score: float = 50.0
    liquidity_score: float = 0.0
    risk_score: float = 50.0
    entry_signal: bool = False
    risk_level: str = "MEDIUM"
    evidence: dict[str, Any] = field(default_factory=dict)


def score_stock(
    vt_symbol: str,
    bars: list[Bar],
    trade_date: date,
    *,
    index_return_20d: float | None = None,
    sector_score: float | None = None,
    financial_score: float | None = None,
    fund_flow_score: float | None = None,
    hot_rank_score: float | None = None,
    lhb_score: float | None = None,
) -> SignalScore:
    """Compatibility wrapper for the mainline pullback strategy."""

    from alphaagent.server.services.quant.strategies.pullback import score_stock as _score_stock

    return _score_stock(
        vt_symbol,
        bars,
        trade_date,
        index_return_20d=index_return_20d,
        sector_score=sector_score,
        financial_score=financial_score,
        fund_flow_score=fund_flow_score,
        hot_rank_score=hot_rank_score,
        lhb_score=lhb_score,
    )


def score_breakout_confirmation(
    vt_symbol: str,
    bars: list[Bar],
    trade_date: date,
    *,
    index_return_20d: float | None = None,
    sector_score: float | None = None,
    financial_score: float | None = None,
    fund_flow_score: float | None = None,
    hot_rank_score: float | None = None,
    lhb_score: float | None = None,
) -> SignalScore:
    """Compatibility wrapper for the breakout confirmation strategy."""

    from alphaagent.server.services.quant.strategies.breakout import (
        score_breakout_confirmation as _score_breakout_confirmation,
    )

    return _score_breakout_confirmation(
        vt_symbol,
        bars,
        trade_date,
        index_return_20d=index_return_20d,
        sector_score=sector_score,
        financial_score=financial_score,
        fund_flow_score=fund_flow_score,
        hot_rank_score=hot_rank_score,
        lhb_score=lhb_score,
    )


def score_dragon_pullback(
    vt_symbol: str,
    bars: list[Bar],
    trade_date: date,
    *,
    index_return_20d: float | None = None,
    sector_score: float | None = None,
    financial_score: float | None = None,
    fund_flow_score: float | None = None,
    hot_rank_score: float | None = None,
    lhb_score: float | None = None,
) -> SignalScore:
    """Compatibility wrapper for the mainline dragon pullback strategy."""

    from alphaagent.server.services.quant.strategies.dragon_pullback import (
        score_dragon_pullback as _score_dragon_pullback,
    )

    return _score_dragon_pullback(
        vt_symbol,
        bars,
        trade_date,
        index_return_20d=index_return_20d,
        sector_score=sector_score,
        financial_score=financial_score,
        fund_flow_score=fund_flow_score,
        hot_rank_score=hot_rank_score,
        lhb_score=lhb_score,
    )


def score_limit_up_after_pullback(
    vt_symbol: str,
    bars: list[Bar],
    trade_date: date,
    *,
    index_return_20d: float | None = None,
    sector_score: float | None = None,
    financial_score: float | None = None,
    fund_flow_score: float | None = None,
    hot_rank_score: float | None = None,
    lhb_score: float | None = None,
) -> SignalScore:
    """Compatibility wrapper for the limit-up pullback strategy."""

    from alphaagent.server.services.quant.strategies.limit_up_pullback import (
        score_limit_up_after_pullback as _score_limit_up_after_pullback,
    )

    return _score_limit_up_after_pullback(
        vt_symbol,
        bars,
        trade_date,
        index_return_20d=index_return_20d,
        sector_score=sector_score,
        financial_score=financial_score,
        fund_flow_score=fund_flow_score,
        hot_rank_score=hot_rank_score,
        lhb_score=lhb_score,
    )


def score_trend_acceleration(
    vt_symbol: str,
    bars: list[Bar],
    trade_date: date,
    *,
    index_return_20d: float | None = None,
    sector_score: float | None = None,
    financial_score: float | None = None,
    fund_flow_score: float | None = None,
    hot_rank_score: float | None = None,
    lhb_score: float | None = None,
) -> SignalScore:
    """Compatibility wrapper for the trend acceleration strategy."""

    from alphaagent.server.services.quant.strategies.trend_acceleration import (
        score_trend_acceleration as _score_trend_acceleration,
    )

    return _score_trend_acceleration(
        vt_symbol,
        bars,
        trade_date,
        index_return_20d=index_return_20d,
        sector_score=sector_score,
        financial_score=financial_score,
        fund_flow_score=fund_flow_score,
        hot_rank_score=hot_rank_score,
        lhb_score=lhb_score,
    )


def moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


def daily_turnover_yuan(bar: Bar) -> float:
    if bar.turnover and bar.turnover > 0:
        return float(bar.turnover)
    return bar.close_price * (bar.volume or 0) * 100


def period_return(values: list[float], window: int) -> float | None:
    if len(values) <= window:
        return None
    start = values[-window - 1]
    end = values[-1]
    if not start:
        return None
    return (end / start - 1) * 100


def max_drawdown(values: list[float]) -> float | None:
    if not values:
        return None
    peak = values[0]
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        if peak:
            worst = min(worst, (value / peak - 1) * 100)
    return worst


def pct_distance(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference == 0:
        return None
    return (value / reference - 1) * 100


def score_relative_strength(
    return_20d: float | None,
    return_60d: float | None,
    index_return_20d: float | None,
    max_drawdown_60d: float | None,
) -> float:
    base = 50.0
    if return_20d is not None:
        base += return_20d * 1.2
    if return_60d is not None:
        base += return_60d * 0.5
    if index_return_20d is not None and return_20d is not None:
        base += (return_20d - index_return_20d) * 1.5
    if max_drawdown_60d is not None:
        base += max_drawdown_60d * 0.8
    return clamp_score(base)


def score_washout_setup(
    closes: list[float],
    volumes: list[float],
    ma5: float | None,
    ma10: float | None,
    ma20: float | None,
    ma60: float | None,
) -> tuple[float, dict[str, Any]]:
    latest = closes[-1]
    high20 = max(closes[-20:])
    drawdown_from_high = (latest / high20 - 1) * 100 if high20 else None
    volume5 = moving_average(volumes, 5)
    volume20 = moving_average(volumes, 20)
    volume_ratio = volume5 / volume20 if volume5 is not None and volume20 else None
    ma5_distance = pct_distance(latest, ma5)
    ma20_distance = pct_distance(latest, ma20)

    score = 45.0
    if drawdown_from_high is not None and -15 <= drawdown_from_high <= -3:
        score += 20
    elif drawdown_from_high is not None and -25 <= drawdown_from_high < -15:
        score += 5
    if volume_ratio is not None and volume_ratio <= 0.85:
        score += 15
    if ma5_distance is not None and -2 <= ma5_distance <= 2.5:
        score += 10
    if ma20_distance is not None and latest >= (ma20 or 0) * 0.97:
        score += 5
    if ma20 is not None and ma60 is not None and ma20 >= ma60 * 0.98:
        score += 5

    return clamp_score(score), {
        "drawdown_from_20d_high": drawdown_from_high,
        "volume_ratio_5d_20d": volume_ratio,
        "ma5_distance_pct": ma5_distance,
        "ma20_distance_pct": ma20_distance,
    }


def score_trend_quality(closes: list[float], ma5: float | None, ma20: float | None, ma60: float | None) -> float:
    latest = closes[-1]
    score = 45.0
    if ma5 is not None and latest >= ma5:
        score += 12
    if ma20 is not None and latest >= ma20:
        score += 15
    if ma60 is not None and latest >= ma60:
        score += 10
    if ma5 is not None and ma20 is not None and ma5 >= ma20:
        score += 8
    if ma20 is not None and ma60 is not None and ma20 >= ma60:
        score += 10
    return clamp_score(score)


def score_liquidity(turnover20: float | None) -> float:
    if turnover20 is None or turnover20 <= 0:
        return 0.0
    if turnover20 >= 1_000_000_000:
        return 100.0
    if turnover20 >= 300_000_000:
        return 80.0
    if turnover20 >= 100_000_000:
        return 60.0
    if turnover20 >= 50_000_000:
        return 40.0
    return 15.0


def score_risk(max_drawdown_60d: float | None, change_pct: float | None) -> float:
    score = 80.0
    if max_drawdown_60d is not None:
        score += max_drawdown_60d * 1.2
    if change_pct is not None and change_pct <= -8:
        score -= 20
    return clamp_score(score)


def score_breakout_strength(
    close_to_prior_high_pct: float | None,
    return_20d: float | None,
    return_60d: float | None,
) -> float:
    score = 50.0
    if close_to_prior_high_pct is not None:
        score += max(min((close_to_prior_high_pct + 2.0) * 10, 30), -20)
    if return_20d is not None:
        score += max(min(return_20d * 0.8, 20), -15)
    if return_60d is not None:
        score += max(min(return_60d * 0.25, 15), -10)
    return clamp_score(score)


def score_volume_confirmation(volume_ratio: float | None, latest_volume: float | None, volume20: float | None) -> float:
    score = 45.0
    if volume_ratio is not None:
        score += max(min((volume_ratio - 1.0) * 35, 35), -15)
    if latest_volume and volume20:
        score += max(min((latest_volume / volume20 - 1.0) * 15, 15), -10)
    return clamp_score(score)


def score_breakout_risk(
    max_drawdown_60d: float | None,
    change_pct: float | None,
    ma20_distance_pct: float | None,
    base_range_pct: float | None,
) -> float:
    score = 75.0
    if max_drawdown_60d is not None:
        score += max(max_drawdown_60d * 0.8, -25)
    if change_pct is not None and change_pct >= 9.8:
        score -= 8
    if ma20_distance_pct is not None and ma20_distance_pct > 30:
        score -= min((ma20_distance_pct - 30) * 1.2, 18)
    if base_range_pct is not None and base_range_pct > 45:
        score -= min((base_range_pct - 45) * 0.5, 12)
    return clamp_score(score)


def score_financial_report(report: dict[str, Any] | None) -> float:
    if not report:
        return 50.0
    score = 50.0
    for key in ("revenue_yoy", "net_profit_yoy", "net_profit_qoq", "operating_cash_flow", "cash_flow_quality"):
        value = to_float(report.get(key))
        if value is None:
            continue
        if key == "operating_cash_flow":
            score += 8 if value > 0 else -8
        elif key == "cash_flow_quality":
            score += max(min(value * 8, 12), -12)
        else:
            score += max(min(value / 5, 12), -12)
    return clamp_score(score)


def clamp_score(value: float | None) -> float:
    if value is None or not isfinite(float(value)):
        return 0.0
    return round(max(0.0, min(100.0, float(value))), 4)


def to_float(value: Any) -> float | None:
    if value in (None, "", "-", "--"):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def risk_level(score: float) -> str:
    if score >= 70:
        return "LOW"
    if score >= 40:
        return "MEDIUM"
    return "HIGH"


EXIT_HOLD: str | None = None
EXIT_REASONS = ("stop_loss", "take_profit", "trailing_stop", "time_stop")


def evaluate_exit(
    *,
    last_price: float,
    stop_loss_price: float | None = None,
    take_profit_price: float | None = None,
    trailing_stop_price: float | None = None,
    entry_date: date | None = None,
    current_day: date | None = None,
    time_stop_days: int = 15,
) -> str | None:
    """Evaluate whether a held position should exit based on absolute price levels.

    Single source of truth for "when to sell" decisions, reused by both the
    backtest engine (``sell_reason_for_position``) and the realtime holdings
    endpoint (``groups.holdings``). Accepts absolute price levels rather than
    coefficients so each caller supplies whichever price source it has — the
    backtest derives levels from params × cost/highest, realtime reads the
    stop_loss_price/take_profit_price/trailing_stop_price stored on the position.

    Priority: stop_loss > take_profit > trailing_stop > time_stop. Returns the
    reason string, or ``None`` (= hold) when no rule is triggered.
    """
    if stop_loss_price is not None and last_price <= stop_loss_price:
        return "stop_loss"
    if take_profit_price is not None and last_price >= take_profit_price:
        return "take_profit"
    if trailing_stop_price is not None and last_price <= trailing_stop_price:
        return "trailing_stop"
    if entry_date is not None and current_day is not None:
        if (current_day - entry_date).days >= time_stop_days * 2:
            return "time_stop"
    return None
