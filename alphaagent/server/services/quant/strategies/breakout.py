"""Platform volume breakout confirmation strategy."""

from __future__ import annotations

from datetime import date

from alphaagent.server.services.quant.factors import (
    BREAKOUT_STRATEGY_ID,
    Bar,
    SignalScore,
    clamp_score,
    daily_turnover_yuan,
    max_drawdown,
    moving_average,
    pct_distance,
    period_return,
    risk_level,
    score_breakout_risk,
    score_breakout_strength,
    score_liquidity,
    score_trend_quality,
    score_volume_confirmation,
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
    """Score platform/volume breakout using data visible at ``trade_date``."""

    visible_bars = [bar for bar in bars if bar.trade_date <= trade_date]
    result = SignalScore(vt_symbol=vt_symbol, trade_date=trade_date, signal_type=BREAKOUT_STRATEGY_ID)
    if len(visible_bars) < 80:
        result.evidence = {"status": "insufficient_data", "bars": len(visible_bars), "min_required": 80}
        return result

    closes = [bar.close_price for bar in visible_bars]
    highs = [bar.high_price for bar in visible_bars]
    lows = [bar.low_price for bar in visible_bars]
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
    prior_high60 = max(highs[-61:-1])
    prior_low20 = min(lows[-21:-1])
    base_range_pct = pct_distance(prior_high60, prior_low20)
    close_to_prior_high_pct = pct_distance(latest.close_price, prior_high60)
    ma20_distance_pct = pct_distance(latest.close_price, ma20)
    volume_ratio = volume5 / volume20 if volume5 is not None and volume20 else None

    breakout_strength = score_breakout_strength(close_to_prior_high_pct, return_20d, return_60d)
    volume_confirmation = score_volume_confirmation(volume_ratio, latest.volume, volume20)
    trend_quality = score_trend_quality(closes, ma5, ma20, ma60)
    liquidity = score_liquidity(turnover20)
    risk = score_breakout_risk(max_drawdown_60d, latest.change_pct, ma20_distance_pct, base_range_pct)
    sector = clamp_score(sector_score if sector_score is not None else 50.0)
    financial = clamp_score(financial_score if financial_score is not None else 50.0)
    fund_flow = clamp_score(fund_flow_score if fund_flow_score is not None else 50.0)
    hot_rank = clamp_score(hot_rank_score if hot_rank_score is not None else 50.0)
    lhb = clamp_score(lhb_score if lhb_score is not None else 50.0)
    smart_money = 0.50 * fund_flow + 0.30 * hot_rank + 0.20 * lhb

    total = (
        0.25 * breakout_strength
        + 0.18 * volume_confirmation
        + 0.17 * trend_quality
        + 0.12 * sector
        + 0.08 * financial
        + 0.10 * smart_money
        + 0.10 * liquidity
    )
    entry_signal = (
        total >= 70
        and close_to_prior_high_pct is not None
        and close_to_prior_high_pct >= -1.0
        and volume_ratio is not None
        and volume_ratio >= 1.10
        and trend_quality >= 60
        and liquidity >= 25
        and risk >= 35
    )

    result.total_score = round(total, 4)
    result.relative_strength_score = breakout_strength
    result.washout_score = volume_confirmation
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
        "ma20_distance_pct": ma20_distance_pct,
        "prior_high60": prior_high60,
        "prior_low20": prior_low20,
        "close_to_prior_high_pct": close_to_prior_high_pct,
        "base_range_pct": base_range_pct,
        "volume5": volume5,
        "volume20": volume20,
        "volume_ratio_5d_20d": volume_ratio,
        "turnover20": turnover20,
        "turnover_estimated_from_volume": any(not bar.turnover for bar in visible_bars[-20:]),
        "breakout_strength_score": breakout_strength,
        "volume_confirmation_score": volume_confirmation,
        "smart_money_proxy_score": smart_money,
        "fund_flow_score": fund_flow,
        "hot_rank_score": hot_rank,
        "lhb_score": lhb,
        "smart_money_note": "fund/hot/lhb are observable proxy signals, not proof of main-force intent",
        "selection_rule": "daily_close_visible_signal",
        "entry_setup": "breakout_confirmation",
    }
    return result
