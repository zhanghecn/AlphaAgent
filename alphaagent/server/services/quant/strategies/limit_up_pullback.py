"""Limit-up pullback confirmation strategy."""

from __future__ import annotations

from datetime import date

from alphaagent.server.services.quant.factors import (
    Bar,
    SignalScore,
    clamp_score,
    daily_turnover_yuan,
    max_drawdown,
    moving_average,
    pct_distance,
    period_return,
    risk_level,
    score_liquidity,
    score_relative_strength,
    score_risk,
    score_trend_quality,
)


LIMIT_UP_PULLBACK_STRATEGY_ID = "limit_up_after_pullback"
LIMIT_UP_PULLBACK_STRATEGY_VERSION = "0.1.0"


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
    """Score strong stocks that pull back after a recent limit-up day."""

    visible_bars = [bar for bar in bars if bar.trade_date <= trade_date]
    result = SignalScore(vt_symbol=vt_symbol, trade_date=trade_date, signal_type=LIMIT_UP_PULLBACK_STRATEGY_ID)
    if len(visible_bars) < 80:
        result.evidence = {"status": "insufficient_data", "bars": len(visible_bars), "min_required": 80}
        return result

    closes = [bar.close_price for bar in visible_bars]
    volumes = [bar.volume or 0 for bar in visible_bars]
    turnover_values = [daily_turnover_yuan(bar) for bar in visible_bars]
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
    ma5_distance_pct = pct_distance(latest.close_price, ma5)
    ma10_distance_pct = pct_distance(latest.close_price, ma10)
    ma20_distance_pct = pct_distance(latest.close_price, ma20)

    recent_window = visible_bars[-20:]
    limit_up_indexes = [
        index
        for index, bar in enumerate(recent_window)
        if _is_near_limit_up(bar)
    ]
    days_since_limit_up = len(recent_window) - 1 - limit_up_indexes[-1] if limit_up_indexes else None
    limit_up_count_20d = len(limit_up_indexes)
    latest_change = latest.change_pct
    volume_ratio = volume5 / volume20 if volume5 is not None and volume20 else None

    relative_strength = score_relative_strength(return_20d, return_60d, index_return_20d, max_drawdown_60d)
    pullback_shape = _score_limit_up_pullback_shape(days_since_limit_up, ma5_distance_pct, ma10_distance_pct, ma20_distance_pct, latest_change)
    trend_quality = score_trend_quality(closes, ma5, ma20, ma60)
    liquidity = score_liquidity(turnover20)
    risk = score_risk(max_drawdown_60d, latest_change)
    sector = clamp_score(sector_score if sector_score is not None else 50.0)
    financial = clamp_score(financial_score if financial_score is not None else 50.0)
    fund_flow = clamp_score(fund_flow_score if fund_flow_score is not None else 50.0)
    hot_rank = clamp_score(hot_rank_score if hot_rank_score is not None else 50.0)
    lhb = clamp_score(lhb_score if lhb_score is not None else 50.0)
    smart_money = 0.45 * fund_flow + 0.35 * hot_rank + 0.20 * lhb

    total = (
        0.22 * relative_strength
        + 0.24 * pullback_shape
        + 0.16 * trend_quality
        + 0.12 * sector
        + 0.08 * financial
        + 0.08 * smart_money
        + 0.10 * liquidity
    )
    entry_signal = (
        total >= 72
        and limit_up_count_20d >= 1
        and days_since_limit_up is not None
        and 2 <= days_since_limit_up <= 12
        and ma5_distance_pct is not None
        and -3.0 <= ma5_distance_pct <= 4.0
        and ma20_distance_pct is not None
        and ma20_distance_pct >= -2.0
        and trend_quality >= 60
        and risk >= 35
        and liquidity >= 25
    )

    result.total_score = round(total, 4)
    result.relative_strength_score = relative_strength
    result.washout_score = pullback_shape
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
        "ma10_distance_pct": ma10_distance_pct,
        "ma20_distance_pct": ma20_distance_pct,
        "volume5": volume5,
        "volume20": volume20,
        "volume_ratio_5d_20d": volume_ratio,
        "turnover20": turnover20,
        "turnover_estimated_from_volume": any(not bar.turnover for bar in visible_bars[-20:]),
        "limit_up_count_20d": limit_up_count_20d,
        "days_since_limit_up": days_since_limit_up,
        "latest_change_pct": latest_change,
        "pullback_shape_score": pullback_shape,
        "smart_money_proxy_score": smart_money,
        "fund_flow_score": fund_flow,
        "hot_rank_score": hot_rank,
        "lhb_score": lhb,
        "smart_money_note": "fund/hot/lhb are observable proxy signals, not proof of main-force intent",
        "selection_rule": "daily_close_visible_signal",
        "entry_setup": "limit_up_after_pullback",
    }
    return result


def _is_near_limit_up(bar: Bar) -> bool:
    if bar.change_pct is not None:
        return float(bar.change_pct) >= 9.5
    if bar.open_price:
        return (bar.close_price / bar.open_price - 1.0) * 100 >= 9.5
    return False


def _score_limit_up_pullback_shape(
    days_since_limit_up: int | None,
    ma5_distance_pct: float | None,
    ma10_distance_pct: float | None,
    ma20_distance_pct: float | None,
    latest_change_pct: float | None,
) -> float:
    score = 40.0
    if days_since_limit_up is not None:
        if 2 <= days_since_limit_up <= 8:
            score += 24
        elif 9 <= days_since_limit_up <= 12:
            score += 12
    if ma5_distance_pct is not None and -3.0 <= ma5_distance_pct <= 4.0:
        score += 16
    if ma10_distance_pct is not None and -4.0 <= ma10_distance_pct <= 5.0:
        score += 10
    if ma20_distance_pct is not None and ma20_distance_pct >= -2.0:
        score += 8
    if latest_change_pct is not None and latest_change_pct >= 8.5:
        score -= 18
    return clamp_score(score)
