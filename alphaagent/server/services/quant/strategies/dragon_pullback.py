"""Mainline dragon pullback state-machine strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from alphaagent.server.services.quant.factors import (
    DRAGON_PULLBACK_STRATEGY_ID,
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


DRAGON_PULLBACK_STRATEGY_VERSION = "0.1.1"


@dataclass(frozen=True)
class DragonFeatures:
    latest: Bar
    closes: list[float]
    highs: list[float]
    lows: list[float]
    volumes: list[float]
    turnovers: list[float]
    return_5d: float | None
    return_20d: float | None
    return_60d: float | None
    max_drawdown_60d: float | None
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    ma5_prev: float | None
    ma10_prev: float | None
    ma5_distance_pct: float | None
    ma10_distance_pct: float | None
    ma20_distance_pct: float | None
    ma5_vs_ma10_pct: float | None
    ma10_vs_ma20_pct: float | None
    ma5_slope_pct: float | None
    volume5: float | None
    volume20: float | None
    volume_ratio: float | None
    turnover20: float | None
    turnover_percentile_60d: float | None
    pivot_high_20d: float
    pivot_high_index_from_end: int
    drawdown_from_pivot_pct: float | None
    pullback_days: int
    close_location_in_range: float | None
    upper_shadow_pct: float | None
    lower_shadow_pct: float | None
    body_pct: float | None
    large_bull_count_20d: int
    near_limit_up_count_20d: int
    latest_change_pct: float | None


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
    """Score a mainline dragon pullback setup using data visible at ``trade_date``."""

    visible_bars = [bar for bar in bars if bar.trade_date <= trade_date]
    result = SignalScore(vt_symbol=vt_symbol, trade_date=trade_date, signal_type=DRAGON_PULLBACK_STRATEGY_ID)
    if len(visible_bars) < 80:
        result.evidence = {"status": "insufficient_data", "bars": len(visible_bars), "min_required": 80}
        return result

    features = _build_features(visible_bars)
    relative_strength = score_relative_strength(
        features.return_20d,
        features.return_60d,
        index_return_20d,
        features.max_drawdown_60d,
    )
    trend_quality = score_trend_quality(features.closes, features.ma5, features.ma20, features.ma60)
    liquidity = score_liquidity(features.turnover20)
    risk = score_risk(features.max_drawdown_60d, features.latest.change_pct)
    sector = clamp_score(sector_score if sector_score is not None else 50.0)
    financial = clamp_score(financial_score if financial_score is not None else 50.0)
    fund_flow = clamp_score(fund_flow_score if fund_flow_score is not None else 50.0)
    hot_rank = clamp_score(hot_rank_score if hot_rank_score is not None else 50.0)
    lhb = clamp_score(lhb_score if lhb_score is not None else 50.0)
    smart_money = 0.45 * fund_flow + 0.35 * hot_rank + 0.20 * lhb

    strong_leg = _score_strong_leg(features, relative_strength, sector)
    pullback = _score_pullback_structure(features)
    support, support_type = _score_support(features)
    reclaim = _score_reclaim(features)
    risk_penalty, risk_flags = _risk_penalty(features)
    failed_rules = _failed_rules(features, strong_leg, pullback, support, reclaim, risk_flags, liquidity, risk)
    state = _dragon_state(features, failed_rules, support_type, reclaim)
    fresh_tail_buy, repeat_days, last_ready_date = _tail_buy_freshness(visible_bars, state)
    if state == "TAIL_BUY_READY" and not fresh_tail_buy:
        failed_rules = [*failed_rules, "repeat_tail_buy_setup"]

    total = (
        0.20 * relative_strength
        + 0.16 * strong_leg
        + 0.18 * pullback
        + 0.16 * support
        + 0.12 * reclaim
        + 0.08 * sector
        + 0.04 * financial
        + 0.06 * smart_money
        + 0.10 * liquidity
        - risk_penalty
    )
    total = clamp_score(total)
    entry_signal = (
        total >= 72
        and state == "TAIL_BUY_READY"
        and fresh_tail_buy
        and liquidity >= 25
        and risk >= 35
        and not failed_rules
    )

    result.total_score = round(total, 4)
    result.relative_strength_score = relative_strength
    result.washout_score = pullback
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
    result.evidence = _evidence(
        features=features,
        index_return_20d=index_return_20d,
        strong_leg=strong_leg,
        pullback=pullback,
        support=support,
        reclaim=reclaim,
        support_type=support_type,
        state=state,
        failed_rules=failed_rules,
        risk_flags=risk_flags,
        risk_penalty=risk_penalty,
        fresh_tail_buy=fresh_tail_buy,
        repeat_days=repeat_days,
        last_ready_date=last_ready_date,
        smart_money=smart_money,
        fund_flow=fund_flow,
        hot_rank=hot_rank,
        lhb=lhb,
    )
    return result


def _build_features(bars: list[Bar]) -> DragonFeatures:
    closes = [bar.close_price for bar in bars]
    highs = [bar.high_price for bar in bars]
    lows = [bar.low_price for bar in bars]
    volumes = [bar.volume or 0 for bar in bars]
    turnovers = [daily_turnover_yuan(bar) for bar in bars]
    latest = bars[-1]
    previous_closes = closes[:-1]

    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    ma5_prev = moving_average(previous_closes, 5)
    ma10_prev = moving_average(previous_closes, 10)
    volume5 = moving_average(volumes, 5)
    volume20 = moving_average(volumes, 20)
    turnover20 = moving_average(turnovers, 20)
    recent_highs = highs[-20:]
    pivot_high = max(recent_highs)
    pivot_high_index = len(recent_highs) - 1 - recent_highs.index(pivot_high)

    derived_changes = _derived_change_pcts(bars)
    latest_change = _bar_change_pct(bars, len(bars) - 1, derived_changes)
    return DragonFeatures(
        latest=latest,
        closes=closes,
        highs=highs,
        lows=lows,
        volumes=volumes,
        turnovers=turnovers,
        return_5d=period_return(closes, 5),
        return_20d=period_return(closes, 20),
        return_60d=period_return(closes, 60),
        max_drawdown_60d=max_drawdown(closes[-60:]),
        ma5=ma5,
        ma10=ma10,
        ma20=ma20,
        ma60=ma60,
        ma5_prev=ma5_prev,
        ma10_prev=ma10_prev,
        ma5_distance_pct=pct_distance(latest.close_price, ma5),
        ma10_distance_pct=pct_distance(latest.close_price, ma10),
        ma20_distance_pct=pct_distance(latest.close_price, ma20),
        ma5_vs_ma10_pct=pct_distance(ma5, ma10),
        ma10_vs_ma20_pct=pct_distance(ma10, ma20),
        ma5_slope_pct=pct_distance(ma5, ma5_prev),
        volume5=volume5,
        volume20=volume20,
        volume_ratio=volume5 / volume20 if volume5 is not None and volume20 else None,
        turnover20=turnover20,
        turnover_percentile_60d=_percentile_rank(turnovers[-60:], latest.turnover or daily_turnover_yuan(latest)),
        pivot_high_20d=pivot_high,
        pivot_high_index_from_end=pivot_high_index,
        drawdown_from_pivot_pct=pct_distance(latest.close_price, pivot_high),
        pullback_days=pivot_high_index,
        close_location_in_range=_close_location(latest),
        upper_shadow_pct=_upper_shadow_pct(latest),
        lower_shadow_pct=_lower_shadow_pct(latest),
        body_pct=_body_pct(latest),
        large_bull_count_20d=sum(
            1 for index in range(max(len(bars) - 20, 0), len(bars)) if (_bar_change_pct(bars, index, derived_changes) or 0) >= 6.0
        ),
        near_limit_up_count_20d=sum(
            1 for index in range(max(len(bars) - 20, 0), len(bars)) if (_bar_change_pct(bars, index, derived_changes) or 0) >= 9.5
        ),
        latest_change_pct=latest_change,
    )


def _score_strong_leg(features: DragonFeatures, relative_strength: float, sector: float) -> float:
    score = 35.0
    if features.return_20d is not None and features.return_20d >= 12:
        score += 18
    if features.return_60d is not None and features.return_60d >= 25:
        score += 14
    if features.large_bull_count_20d >= 1:
        score += 10
    if features.near_limit_up_count_20d >= 1:
        score += 8
    if relative_strength >= 70:
        score += 10
    if sector >= 65:
        score += 8
    if features.turnover20 is not None and features.turnover20 >= 300_000_000:
        score += 7
    return clamp_score(score)


def _score_pullback_structure(features: DragonFeatures) -> float:
    score = 35.0
    drawdown = features.drawdown_from_pivot_pct
    if drawdown is not None:
        if -16 <= drawdown <= -3:
            score += 26
        elif -24 <= drawdown < -16:
            score += 8
        elif -3 < drawdown <= 2:
            score += 6
    if 3 <= features.pullback_days <= 8:
        score += 20
    elif 1 <= features.pullback_days <= 12:
        score += 10
    if features.volume_ratio is not None:
        if features.volume_ratio <= 0.90:
            score += 14
        elif features.volume_ratio <= 1.20:
            score += 6
    if features.ma20_distance_pct is not None and features.ma20_distance_pct >= -3:
        score += 8
    return clamp_score(score)


def _score_support(features: DragonFeatures) -> tuple[float, str]:
    ma5_distance = features.ma5_distance_pct
    ma10_distance = features.ma10_distance_pct
    ma20_distance = features.ma20_distance_pct
    ma5_vs_ma10 = features.ma5_vs_ma10_pct
    score = 35.0
    support_type = "none"

    if ma5_distance is not None and -1.8 <= ma5_distance <= 3.0:
        score += 28
        support_type = "ma5_reclaim"
    elif ma10_distance is not None and -2.5 <= ma10_distance <= 3.0:
        score += 24
        support_type = "ma10_support"
    elif ma20_distance is not None and -2.0 <= ma20_distance <= 4.0:
        score += 14
        support_type = "ma20_support"

    if ma5_vs_ma10 is not None:
        if ma5_vs_ma10 >= 0:
            score += 16
        elif ma5_vs_ma10 >= -2.0 and features.ma5_slope_pct is not None and features.ma5_slope_pct >= 0:
            score += 8
    if features.ma10_vs_ma20_pct is not None and features.ma10_vs_ma20_pct >= -2.0:
        score += 8
    if features.close_location_in_range is not None and features.close_location_in_range >= 0.55:
        score += 5
    return clamp_score(score), support_type


def _score_reclaim(features: DragonFeatures) -> float:
    score = 35.0
    latest_close = features.latest.close_price
    if features.ma5 is not None and latest_close >= features.ma5 * 0.99:
        score += 24
    if features.ma10 is not None and latest_close >= features.ma10:
        score += 14
    if features.ma5_slope_pct is not None and features.ma5_slope_pct >= -0.2:
        score += 10
    if features.close_location_in_range is not None and features.close_location_in_range >= 0.60:
        score += 10
    if features.latest_change_pct is not None and -2.0 <= features.latest_change_pct <= 6.0:
        score += 7
    return clamp_score(score)


def _risk_penalty(features: DragonFeatures) -> tuple[float, list[str]]:
    flags: list[str] = []
    penalty = 0.0
    if _is_distribution_risk(features):
        flags.append("distribution_risk")
        penalty += 35.0
    if _is_weak_rebound_after_breakdown(features):
        flags.append("weak_rebound_ma5_below_ma10")
        penalty += 28.0
    if features.drawdown_from_pivot_pct is not None and features.drawdown_from_pivot_pct < -24:
        flags.append("pullback_too_deep")
        penalty += 12.0
    if features.ma20_distance_pct is not None and features.ma20_distance_pct < -5:
        flags.append("ma20_broken")
        penalty += 14.0
    return penalty, flags


def _failed_rules(
    features: DragonFeatures,
    strong_leg: float,
    pullback: float,
    support: float,
    reclaim: float,
    risk_flags: list[str],
    liquidity: float,
    risk: float,
) -> list[str]:
    failed = list(risk_flags)
    if strong_leg < 55:
        failed.append("strong_leg")
    if pullback < 55:
        failed.append("pullback_structure")
    if support < 62:
        failed.append("support_acceptance")
    if reclaim < 62:
        failed.append("reclaim_confirmation")
    if features.pullback_days < 3:
        failed.append("pullback_too_short")
    if features.pullback_days > 12:
        failed.append("pullback_too_late")
    if liquidity < 25:
        failed.append("liquidity_score")
    if risk < 35:
        failed.append("risk_score")
    if features.latest_change_pct is not None and features.latest_change_pct > 8.5:
        failed.append("overheat")
    return failed


def _dragon_state(
    features: DragonFeatures,
    failed_rules: list[str],
    support_type: str,
    reclaim: float,
) -> str:
    if "distribution_risk" in failed_rules:
        return "DISTRIBUTION_RISK"
    if any(rule in failed_rules for rule in ("weak_rebound_ma5_below_ma10", "ma20_broken", "pullback_too_deep")):
        return "INVALIDATED"
    if support_type != "none" and reclaim >= 62 and not failed_rules:
        return "TAIL_BUY_READY"
    if support_type != "none":
        return "SUPPORT_ACCEPTED"
    if features.pullback_days >= 1:
        return "PULLBACK_OBSERVE"
    return "STRONG_LEG_CONFIRMED"


def _tail_buy_freshness(bars: list[Bar], state: str) -> tuple[bool, int, date | None]:
    """Return whether today's TAIL_BUY_READY is a fresh setup, using only prior bars."""

    if state != "TAIL_BUY_READY" or len(bars) < 2:
        return True, 0, None

    repeat_days = 0
    last_ready_date: date | None = None
    for end_index in range(len(bars) - 1, max(len(bars) - 8, 79), -1):
        previous_features = _build_features(bars[:end_index])
        strong_leg = _score_strong_leg(previous_features, 70.0, 50.0)
        pullback = _score_pullback_structure(previous_features)
        support, support_type = _score_support(previous_features)
        reclaim = _score_reclaim(previous_features)
        risk_penalty, risk_flags = _risk_penalty(previous_features)
        risk = score_risk(previous_features.max_drawdown_60d, previous_features.latest.change_pct)
        liquidity = score_liquidity(previous_features.turnover20)
        failed_rules = _failed_rules(previous_features, strong_leg, pullback, support, reclaim, risk_flags, liquidity, risk)
        previous_state = _dragon_state(previous_features, failed_rules, support_type, reclaim)
        if previous_state != "TAIL_BUY_READY":
            break
        repeat_days += 1
        last_ready_date = previous_features.latest.trade_date

    return repeat_days == 0, repeat_days, last_ready_date


def _is_weak_rebound_after_breakdown(features: DragonFeatures) -> bool:
    if features.ma5_vs_ma10_pct is None or features.ma10_distance_pct is None:
        return False
    return (
        features.ma5_vs_ma10_pct < -2.0
        and features.ma10_distance_pct < 0
        and (features.ma5_slope_pct is None or features.ma5_slope_pct <= 0.3)
    )


def _is_distribution_risk(features: DragonFeatures) -> bool:
    latest = features.latest
    hot_turnover = features.turnover_percentile_60d is not None and features.turnover_percentile_60d >= 0.88
    upper_shadow = features.upper_shadow_pct is not None and features.upper_shadow_pct >= 6.0
    weak_close = features.close_location_in_range is not None and features.close_location_in_range <= 0.45
    recent_surge = features.return_5d is not None and features.return_5d >= 25.0
    high_level = features.ma20_distance_pct is not None and features.ma20_distance_pct >= 18.0
    big_bear = features.latest_change_pct is not None and features.latest_change_pct <= -5.0
    near_limit_down = features.latest_change_pct is not None and features.latest_change_pct <= -9.0
    volume_spike = features.volume_ratio is not None and features.volume_ratio >= 1.55
    extended_surge = features.return_20d is not None and features.return_20d >= 45.0
    high_volume_break = hot_turnover and weak_close and (
        (near_limit_down and extended_surge)
        or (extended_surge and big_bear and volume_spike)
    )
    return bool(high_level and (high_volume_break or (hot_turnover and upper_shadow and weak_close) or (recent_surge and big_bear and volume_spike)))


def _evidence(
    *,
    features: DragonFeatures,
    index_return_20d: float | None,
    strong_leg: float,
    pullback: float,
    support: float,
    reclaim: float,
    support_type: str,
    state: str,
    failed_rules: list[str],
    risk_flags: list[str],
    risk_penalty: float,
    fresh_tail_buy: bool,
    repeat_days: int,
    last_ready_date: date | None,
    smart_money: float,
    fund_flow: float,
    hot_rank: float,
    lhb: float,
) -> dict[str, object]:
    return {
        "status": "ready",
        "return_5d": features.return_5d,
        "return_20d": features.return_20d,
        "return_60d": features.return_60d,
        "index_return_20d": index_return_20d,
        "max_drawdown_60d": features.max_drawdown_60d,
        "ma5": features.ma5,
        "ma10": features.ma10,
        "ma20": features.ma20,
        "ma60": features.ma60,
        "ma5_distance_pct": features.ma5_distance_pct,
        "ma10_distance_pct": features.ma10_distance_pct,
        "ma20_distance_pct": features.ma20_distance_pct,
        "ma5_vs_ma10_pct": features.ma5_vs_ma10_pct,
        "ma10_vs_ma20_pct": features.ma10_vs_ma20_pct,
        "ma5_slope_pct": features.ma5_slope_pct,
        "volume5": features.volume5,
        "volume20": features.volume20,
        "volume_ratio_5d_20d": features.volume_ratio,
        "turnover20": features.turnover20,
        "turnover_percentile_60d": features.turnover_percentile_60d,
        "turnover_estimated_from_volume": False,
        "pivot_high_20d": features.pivot_high_20d,
        "drawdown_from_pivot_pct": features.drawdown_from_pivot_pct,
        "pullback_days": features.pullback_days,
        "close_location_in_range": features.close_location_in_range,
        "upper_shadow_pct": features.upper_shadow_pct,
        "lower_shadow_pct": features.lower_shadow_pct,
        "body_pct": features.body_pct,
        "large_bull_count_20d": features.large_bull_count_20d,
        "near_limit_up_count_20d": features.near_limit_up_count_20d,
        "latest_change_pct": features.latest_change_pct,
        "strong_leg_score": strong_leg,
        "pullback_structure_score": pullback,
        "support_acceptance_score": support,
        "reclaim_confirmation_score": reclaim,
        "support_type": support_type,
        "support_price": _support_price(features, support_type),
        "dragon_state": state,
        "fresh_tail_buy": fresh_tail_buy,
        "tail_buy_repeat_days": repeat_days,
        "last_tail_buy_ready_date": last_ready_date.isoformat() if last_ready_date else None,
        "failed_rules": failed_rules,
        "risk_flags": risk_flags,
        "risk_penalty": risk_penalty,
        "smart_money_proxy_score": smart_money,
        "fund_flow_score": fund_flow,
        "hot_rank_score": hot_rank,
        "lhb_score": lhb,
        "smart_money_note": "fund/hot/lhb are observable proxy signals, not proof of main-force intent",
        "selection_rule": "daily_close_visible_signal",
        "entry_setup": "dragon_pullback",
    }


def _percentile_rank(values: list[float], latest: float | None) -> float | None:
    if latest is None or not values:
        return None
    valid = [float(value) for value in values if value is not None]
    if not valid:
        return None
    return sum(1 for value in valid if value <= latest) / len(valid)


def _support_price(features: DragonFeatures, support_type: str) -> float | None:
    if support_type == "ma10_support":
        return features.ma10
    if support_type == "ma20_support":
        return features.ma20
    return features.ma5


def _close_location(bar: Bar) -> float | None:
    span = bar.high_price - bar.low_price
    if span <= 0:
        return None
    return (bar.close_price - bar.low_price) / span


def _upper_shadow_pct(bar: Bar) -> float | None:
    if bar.close_price <= 0:
        return None
    upper = bar.high_price - max(bar.open_price, bar.close_price)
    return upper / bar.close_price * 100


def _lower_shadow_pct(bar: Bar) -> float | None:
    if bar.close_price <= 0:
        return None
    lower = min(bar.open_price, bar.close_price) - bar.low_price
    return lower / bar.close_price * 100


def _body_pct(bar: Bar) -> float | None:
    if bar.close_price <= 0:
        return None
    return abs(bar.close_price - bar.open_price) / bar.close_price * 100


def _derived_change_pcts(bars: list[Bar]) -> list[float | None]:
    changes: list[float | None] = []
    previous_close: float | None = None
    for bar in bars:
        if bar.change_pct is not None:
            changes.append(float(bar.change_pct))
        elif previous_close:
            changes.append((bar.close_price / previous_close - 1) * 100)
        else:
            changes.append(None)
        previous_close = bar.close_price
    return changes


def _bar_change_pct(bars: list[Bar], index: int, derived_changes: list[float | None]) -> float | None:
    if index < 0 or index >= len(bars):
        return None
    if bars[index].change_pct is not None:
        return float(bars[index].change_pct)
    return derived_changes[index]
