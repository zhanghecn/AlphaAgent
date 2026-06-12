"""Transparent daily-bar factors for AlphaAgent quant screening."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from math import isfinite
from typing import Any


STRATEGY_ID = "mainline_leader_pullback"
STRATEGY_VERSION = "0.1.1"


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
    """Score one stock using data available at ``trade_date``."""

    visible_bars = [bar for bar in bars if bar.trade_date <= trade_date]
    result = SignalScore(vt_symbol=vt_symbol, trade_date=trade_date)
    if len(visible_bars) < 60:
        result.evidence = {"status": "insufficient_data", "bars": len(visible_bars), "min_required": 60}
        return result

    closes = [bar.close_price for bar in visible_bars]
    volumes = [bar.volume or 0 for bar in visible_bars]
    turnover_values = [bar.turnover if bar.turnover and bar.turnover > 0 else (bar.close_price * (bar.volume or 0)) for bar in visible_bars]
    latest = visible_bars[-1]

    return_20d = period_return(closes, 20)
    return_60d = period_return(closes, 60)
    max_drawdown_60d = max_drawdown(closes[-60:])
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    volume5 = moving_average(volumes, 5)
    volume20 = moving_average(volumes, 20)
    turnover20 = moving_average(turnover_values, 20)

    relative_strength = score_relative_strength(return_20d, return_60d, index_return_20d, max_drawdown_60d)
    washout, washout_evidence = score_washout_setup(closes, volumes, ma5, ma10, ma20, ma60)
    trend_quality = score_trend_quality(closes, ma5, ma20, ma60)
    liquidity = score_liquidity(turnover20)
    risk = score_risk(max_drawdown_60d, latest.change_pct)
    sector = clamp_score(sector_score if sector_score is not None else 50.0)
    financial = clamp_score(financial_score if financial_score is not None else 50.0)
    fund_flow = clamp_score(fund_flow_score if fund_flow_score is not None else 50.0)
    hot_rank = clamp_score(hot_rank_score if hot_rank_score is not None else 50.0)
    lhb = clamp_score(lhb_score if lhb_score is not None else 50.0)
    smart_money = 0.50 * fund_flow + 0.30 * hot_rank + 0.20 * lhb

    total = (
        0.25 * relative_strength
        + 0.20 * washout
        + 0.15 * trend_quality
        + 0.12 * sector
        + 0.10 * financial
        + 0.08 * smart_money
        + 0.10 * liquidity
        + 0.00 * risk
    )
    ma5_distance_pct = pct_distance(latest.close_price, ma5)
    pullback_near_ma = ma5_distance_pct is not None and -1.5 <= ma5_distance_pct <= 2.0
    entry_signal = total >= 68 and pullback_near_ma and risk >= 35 and liquidity >= 25

    result.total_score = round(total, 4)
    result.relative_strength_score = relative_strength
    result.washout_score = washout
    result.trend_quality_score = trend_quality
    result.sector_mainline_score = sector
    result.financial_improvement_score = financial
    result.fund_flow_score = fund_flow
    result.hot_rank_score = hot_rank
    result.lhb_score = lhb
    result.liquidity_score = liquidity
    result.risk_score = risk
    result.entry_signal = entry_signal
    result.risk_level = risk_level(risk)
    result.evidence = {
        "status": "ready",
        "return_20d": return_20d,
        "return_60d": return_60d,
        "index_return_20d": index_return_20d,
        "max_drawdown_60d": max_drawdown_60d,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "ma60": ma60,
        "ma5_distance_pct": ma5_distance_pct,
        "volume5": volume5,
        "volume20": volume20,
        "turnover20": turnover20,
        "turnover_estimated_from_volume": any(not bar.turnover for bar in visible_bars[-20:]),
        "washout": washout_evidence,
        "smart_money_proxy_score": smart_money,
        "fund_flow_score": fund_flow,
        "hot_rank_score": hot_rank,
        "lhb_score": lhb,
        "smart_money_note": "fund/hot/lhb are observable proxy signals, not proof of main-force intent",
        "entry_rule": "daily_close_signal_next_open_execution",
    }
    return result


def moving_average(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


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
