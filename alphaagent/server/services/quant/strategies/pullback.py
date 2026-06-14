"""Mainline leader MA5 pullback strategy."""

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
    score_washout_setup,
)


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
        "selection_rule": "daily_close_visible_signal",
        "entry_setup": "ma5_pullback",
    }
    return result
