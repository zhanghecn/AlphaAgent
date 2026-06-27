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
from alphaagent.server.services.quant.low_suction_quality import (
    ensure_entry_family_context,
    low_suction_launch_quality_bucket,
    low_suction_launch_quality_label,
)


DRAGON_PULLBACK_STRATEGY_VERSION = "0.1.21"
LOW_SUCTION_CONFIRMED_LAUNCH_BONUS = 1.2
LOW_SUCTION_BALANCED_FIRST_LIFT_BONUS = 1.6


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
    ma30: float | None
    ma60: float | None
    ma5_prev: float | None
    ma10_prev: float | None
    ma5_distance_pct: float | None
    ma10_distance_pct: float | None
    ma20_distance_pct: float | None
    ma5_vs_ma10_pct: float | None
    ma10_vs_ma20_pct: float | None
    ma20_vs_ma30_pct: float | None
    ma_convergence_pct: float | None
    low_suction_days: int
    support_hold_days: int
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
    consecutive_bull_closes: int
    upward_gap_in_leg: bool
    persistent_volume_expansion: bool
    latest_change_pct: float | None
    weekly_top_fractal_risk: bool
    spiky_churn_risk: bool
    volume_stall_risk: bool
    high_position_volume_stall_risk: bool
    key_support_break_risk: bool
    illiquid_forgotten_risk: bool
    high_level_sideways_days: int
    high_level_sideways_distribution_risk: bool


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
    latest_bar_date = visible_bars[-1].trade_date if visible_bars else None
    if latest_bar_date != trade_date:
        result.evidence = {
            "status": "missing_trade_date_bar",
            "trade_date": trade_date.isoformat(),
            "latest_bar_date": latest_bar_date.isoformat() if latest_bar_date else None,
        }
        return result
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
    repeat_low_suction_days = repeat_days + 1 if repeat_days and _is_low_suction_structure(features) else 0
    effective_low_suction_days = max(features.low_suction_days, repeat_low_suction_days)
    low_suction = _score_low_suction_buildup(features, low_suction_days=effective_low_suction_days)
    if state == "TAIL_BUY_READY" and not fresh_tail_buy and effective_low_suction_days >= 2:
        state = "LOW_SUCTION_BUILDUP"
    stealth_low_suction = _score_stealth_low_suction(
        features,
        support=support,
        reclaim=reclaim,
        low_suction=low_suction,
        low_suction_days=effective_low_suction_days,
        smart_money=smart_money,
    )
    setup_type = _setup_type(features, state, failed_rules, low_suction, stealth_low_suction)
    fresh_stealth_low_suction = _fresh_stealth_low_suction(visible_bars, setup_type, effective_low_suction_days)
    low_suction_launch_bonus = _low_suction_launch_bonus(
        features,
        setup_type=setup_type,
        low_suction_days=effective_low_suction_days,
    )

    dragon_total = (
        0.20 * relative_strength
        + 0.16 * strong_leg
        + 0.15 * pullback
        + 0.14 * support
        + 0.12 * reclaim
        + 0.07 * low_suction
        + 0.08 * sector
        + 0.04 * financial
        + 0.06 * smart_money
        + 0.10 * liquidity
        - risk_penalty
    )
    stealth_total = (
        0.24 * stealth_low_suction
        + 0.18 * support
        + 0.14 * reclaim
        + 0.12 * pullback
        + 0.10 * relative_strength
        + 0.08 * smart_money
        + 0.06 * sector
        + 0.04 * financial
        + 0.08 * liquidity
        - risk_penalty
    )
    total = clamp_score(max(dragon_total, stealth_total) + low_suction_launch_bonus)
    executable_low_suction = _is_executable_low_suction_buildup(features, state, failed_rules, low_suction, setup_type=setup_type)
    evidence_failed_rules = _display_failed_rules(
        failed_rules,
        executable_low_suction=executable_low_suction,
        setup_type=setup_type,
    )
    # 低吸蓄势后启动：低吸≥3天 + 当日温和启动(3~7%, >8.5已overheat) + 放量 + MA20未破。
    # 识别金安6-4类"低吸后爆发启动"买点(脱离MA5无承接，但低吸蓄势充分)。统计验证
    # 这类票后续盈亏不差于承接买入(见 scripts/low_suction_launch_study.py)。
    low_suction_launch = (
        features.latest_change_pct is not None
        and 3.0 <= features.latest_change_pct <= 7.0
        and features.volume_ratio is not None
        and features.volume_ratio >= 1.0
        and features.ma20_distance_pct is not None
        and features.ma20_distance_pct >= -3.2
        and state not in ("INVALIDATED", "DISTRIBUTION_RISK", "TAIL_BUY_READY")
    )
    entry_signal = (
        total >= 72
        and (
            (
                state == "TAIL_BUY_READY"
                and not failed_rules
            )
            or setup_type == "stealth_low_suction"
            or executable_low_suction
            or low_suction_launch
        )
        and liquidity >= 25
        and risk >= 35
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
        relative_strength=relative_strength,
        strong_leg=strong_leg,
        pullback=pullback,
        support=support,
        reclaim=reclaim,
        low_suction=low_suction,
        stealth_low_suction=stealth_low_suction,
        low_suction_days=effective_low_suction_days,
        support_hold_days=features.support_hold_days,
        sector=sector,
        financial=financial,
        liquidity=liquidity,
        support_type=support_type,
        state=state,
        failed_rules=evidence_failed_rules,
        risk_flags=risk_flags,
        risk_penalty=risk_penalty,
        fresh_tail_buy=fresh_tail_buy,
        repeat_days=repeat_days,
        last_ready_date=last_ready_date,
        smart_money=smart_money,
        fund_flow=fund_flow,
        hot_rank=hot_rank,
        lhb=lhb,
        executable_low_suction=executable_low_suction,
        setup_type=setup_type,
        fresh_stealth_low_suction=fresh_stealth_low_suction,
        dragon_total=dragon_total,
        stealth_total=stealth_total,
        low_suction_launch_bonus=low_suction_launch_bonus,
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
    ma30 = moving_average(closes, 30)
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
        ma30=ma30,
        ma60=ma60,
        ma5_prev=ma5_prev,
        ma10_prev=ma10_prev,
        ma5_distance_pct=pct_distance(latest.close_price, ma5),
        ma10_distance_pct=pct_distance(latest.close_price, ma10),
        ma20_distance_pct=pct_distance(latest.close_price, ma20),
        ma5_vs_ma10_pct=pct_distance(ma5, ma10),
        ma10_vs_ma20_pct=pct_distance(ma10, ma20),
        ma20_vs_ma30_pct=pct_distance(ma20, ma30),
        ma_convergence_pct=_ma_convergence_pct(ma5, ma10, ma20, ma30),
        low_suction_days=_low_suction_days(bars),
        support_hold_days=_support_hold_days(bars),
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
        consecutive_bull_closes=_consecutive_bull_closes(bars),
        upward_gap_in_leg=_has_upward_gap_in_leg(bars),
        persistent_volume_expansion=_has_persistent_volume_expansion(bars),
        latest_change_pct=latest_change,
        weekly_top_fractal_risk=_is_weekly_top_fractal_risk(bars),
        spiky_churn_risk=_is_spiky_churn_risk(bars, derived_changes),
        volume_stall_risk=_is_volume_stall_risk(closes, volumes, turnovers),
        high_position_volume_stall_risk=_is_high_position_volume_stall_risk(closes, volumes, turnovers),
        key_support_break_risk=_is_key_support_break_risk(latest.close_price, ma20, ma30),
        illiquid_forgotten_risk=_is_illiquid_forgotten_risk(volumes, turnovers),
        high_level_sideways_days=_high_level_sideways_days(closes),
        high_level_sideways_distribution_risk=_is_high_level_sideways_distribution_risk(closes, volumes, turnovers),
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


def _score_low_suction_buildup(features: DragonFeatures, *, low_suction_days: int | None = None) -> float:
    """Score repeated low-suction acceptance around short MAs."""

    score = 35.0
    days = features.low_suction_days if low_suction_days is None else low_suction_days
    if features.ma_convergence_pct is not None:
        if features.ma_convergence_pct <= 3.0:
            score += 22
        elif features.ma_convergence_pct <= 5.0:
            score += 14
        elif features.ma_convergence_pct <= 8.8:
            score += 6
    if days >= 4:
        score += 22
    elif days >= 3:
        score += 16
    elif days >= 2:
        score += 9
    if features.support_hold_days >= 4:
        score += 14
    elif features.support_hold_days >= 2:
        score += 8
    if features.volume_ratio is not None:
        if features.volume_ratio <= 0.9:
            score += 12
        elif features.volume_ratio <= 1.15:
            score += 6
    if features.latest_change_pct is not None and -2.5 <= features.latest_change_pct <= 5.5:
        score += 8
    if features.ma20_distance_pct is not None and features.ma20_distance_pct >= -2.5:
        score += 7
    return clamp_score(score)


def _is_low_suction_structure(features: DragonFeatures) -> bool:
    convergence_ok = features.ma_convergence_pct is not None and features.ma_convergence_pct <= 8.8
    short_ma_ok = (
        features.ma5_distance_pct is not None
        and -3.2 <= features.ma5_distance_pct <= 4.2
    ) or (
        features.ma10_distance_pct is not None
        and -4.2 <= features.ma10_distance_pct <= 4.5
    )
    ma20_acceptance = features.ma20_distance_pct is not None and -3.2 <= features.ma20_distance_pct <= 4.8
    trend_not_broken = features.ma20_distance_pct is not None and features.ma20_distance_pct >= -3.2
    quiet_volume = features.volume_ratio is not None and features.volume_ratio <= 1.20
    return bool(convergence_ok and (short_ma_ok or ma20_acceptance) and trend_not_broken and quiet_volume)


def _is_wide_ma_without_low_suction(features: DragonFeatures) -> bool:
    """Reject fast, extended pullbacks that are not repeated low-suction setups."""

    if features.ma_convergence_pct is None:
        return False
    if features.low_suction_days >= 2:
        return False
    if features.ma_convergence_pct <= 14.0:
        return False
    if features.close_location_in_range is None or features.close_location_in_range < 0.70:
        return False
    if features.latest_change_pct is None or features.latest_change_pct < 1.5:
        return False
    if features.return_20d is not None and features.return_20d >= 25.0:
        return True
    return features.ma20_distance_pct is not None and features.ma20_distance_pct > 8.0


def _is_executable_low_suction_buildup(
    features: DragonFeatures,
    state: str,
    failed_rules: list[str],
    low_suction: float,
    *,
    setup_type: str,
) -> bool:
    """Allow repeated MA5/MA10 low-suction buildup before full reclaim confirmation."""

    if setup_type == "stealth_low_suction":
        return True
    if state != "LOW_SUCTION_BUILDUP":
        return False
    if low_suction < 90:
        return False
    if features.low_suction_days < 3:
        return False
    if features.ma_convergence_pct is None or features.ma_convergence_pct > 5.0:
        return False
    if features.ma20_distance_pct is None or features.ma20_distance_pct < -3.0:
        return False
    hard_failures = {
        "distribution_risk",
        "weak_rebound_ma5_below_ma10",
        "ma20_broken",
        "pullback_too_deep",
        "pullback_too_short",
        "pullback_too_late",
        "ma_convergence_too_wide_without_low_suction",
        "liquidity_score",
        "risk_score",
        "overheat",
        "key_support_break_risk",
        "volume_stall_risk",
    }
    return not any(rule in hard_failures for rule in failed_rules)


def _score_stealth_low_suction(
    features: DragonFeatures,
    *,
    support: float,
    reclaim: float,
    low_suction: float,
    low_suction_days: int,
    smart_money: float,
) -> float:
    """Score quiet MA5/MA10 absorption as a setup separate from dragon pullback."""

    score = 20.0
    if low_suction_days >= 6:
        score += 24
    elif low_suction_days >= 4:
        score += 20
    elif low_suction_days >= 3:
        score += 14
    if features.ma_convergence_pct is not None:
        if features.ma_convergence_pct <= 3.0:
            score += 20
        elif features.ma_convergence_pct <= 5.0:
            score += 16
        elif features.ma_convergence_pct <= 6.5:
            score += 8
    if features.volume_ratio is not None:
        if 0.55 <= features.volume_ratio <= 0.95:
            score += 16
        elif 0.95 < features.volume_ratio <= 1.20:
            score += 8
    if features.ma20_distance_pct is not None:
        if features.ma20_distance_pct >= 0:
            score += 10
        elif features.ma20_distance_pct >= -2.5:
            score += 6
    if features.ma5_slope_pct is not None and features.ma5_slope_pct >= -0.45:
        score += 8
    if features.latest_change_pct is not None and -3.0 <= features.latest_change_pct <= 4.8:
        score += 8
    if _is_low_suction_launch_confirmed(features, low_suction_days=low_suction_days):
        score += 10
    if support >= 70:
        score += 8
    if reclaim >= 62:
        score += 5
    if low_suction >= 95:
        score += 8
    if smart_money >= 60:
        score += 4
    return clamp_score(score)


def _setup_type(
    features: DragonFeatures,
    state: str,
    failed_rules: list[str],
    low_suction: float,
    stealth_low_suction: float,
) -> str:
    if _is_stealth_low_suction_setup(features, failed_rules, low_suction, stealth_low_suction):
        return "stealth_low_suction"
    if state == "TAIL_BUY_READY" and not failed_rules:
        return "dragon_pullback"
    return state.lower()


def _is_stealth_low_suction_setup(
    features: DragonFeatures,
    failed_rules: list[str],
    low_suction: float,
    stealth_low_suction: float,
) -> bool:
    if stealth_low_suction < 78 or low_suction < 90:
        return False
    if features.low_suction_days < 3:
        return False
    launch_confirmed = _is_low_suction_launch_confirmed(features, low_suction_days=features.low_suction_days)
    strong_launch = _is_low_suction_strong_launch(features, low_suction_days=features.low_suction_days)
    if features.ma_convergence_pct is None:
        return False
    if launch_confirmed:
        if features.ma_convergence_pct > 8.8:
            return False
    elif features.ma_convergence_pct > 5.0:
        return False
    if features.ma20_distance_pct is None or features.ma20_distance_pct < -2.5:
        return False
    if features.volume_ratio is None or (not _stealth_volume_ok(features) and not strong_launch):
        return False
    if features.latest_change_pct is not None and features.latest_change_pct > 6.5 and not strong_launch:
        return False
    hard_failures = {
        "distribution_risk",
        "weak_rebound_ma5_below_ma10",
        "ma20_broken",
        "pullback_too_deep",
        "ma_convergence_too_wide_without_low_suction",
        "liquidity_score",
        "risk_score",
        "overheat",
        "key_support_break_risk",
        "volume_stall_risk",
    }
    if strong_launch:
        hard_failures.discard("support_acceptance")
        hard_failures.discard("overheat")
    return not any(rule in hard_failures for rule in failed_rules)


def _is_low_suction_launch_confirmed(features: DragonFeatures, *, low_suction_days: int) -> bool:
    """Return whether repeated absorption has its first controlled lift."""

    if _is_low_suction_strong_launch(features, low_suction_days=low_suction_days):
        return True
    if low_suction_days < 3:
        return False
    if features.latest_change_pct is None or not (0.8 <= features.latest_change_pct <= 6.2):
        return False
    if features.close_location_in_range is None or features.close_location_in_range < 0.58:
        return False
    if features.volume_ratio is None or features.volume_ratio > 1.55:
        return False
    if features.ma20_distance_pct is None or features.ma20_distance_pct < -2.5:
        return False
    if features.ma_convergence_pct is None or features.ma_convergence_pct > 8.8:
        return False
    near_short_or_medium = (
        (features.ma5_distance_pct is not None and -1.2 <= features.ma5_distance_pct <= 4.2)
        or (features.ma10_distance_pct is not None and -1.5 <= features.ma10_distance_pct <= 4.5)
        or (features.ma20_distance_pct is not None and -1.0 <= features.ma20_distance_pct <= 5.5)
    )
    return bool(near_short_or_medium)


def _is_low_suction_strong_launch(features: DragonFeatures, *, low_suction_days: int) -> bool:
    if low_suction_days < 3:
        return False
    if features.latest_change_pct is None or not (6.2 < features.latest_change_pct <= 10.5):
        return False
    if features.close_location_in_range is None or features.close_location_in_range < 0.88:
        return False
    if features.volume_ratio is None or features.volume_ratio > 1.25:
        return False
    if features.ma_convergence_pct is None or features.ma_convergence_pct > 3.2:
        return False
    if features.ma20_distance_pct is None or features.ma20_distance_pct < -2.5:
        return False
    if features.support_hold_days < 4:
        return False
    return not bool(
        _is_distribution_risk(features)
        or features.key_support_break_risk
        or features.volume_stall_risk
        or features.high_level_sideways_distribution_risk
    )


def _low_suction_launch_bonus(features: DragonFeatures, *, setup_type: str, low_suction_days: int) -> float:
    if setup_type != "stealth_low_suction":
        return 0.0
    if not _is_low_suction_launch_confirmed(features, low_suction_days=low_suction_days):
        return 0.0
    if _low_suction_stage(features, setup_type, low_suction_days) == "balanced_first_lift":
        return LOW_SUCTION_BALANCED_FIRST_LIFT_BONUS
    return LOW_SUCTION_CONFIRMED_LAUNCH_BONUS


def _fresh_stealth_low_suction(bars: list[Bar], setup_type: str, low_suction_days: int) -> bool:
    if setup_type != "stealth_low_suction" or len(bars) < 2:
        return False
    if low_suction_days <= 3:
        return True
    return _low_suction_days(bars[:-1]) < 3


def _stealth_volume_ok(features: DragonFeatures) -> bool:
    if features.volume_ratio is None:
        return False
    if 0.50 <= features.volume_ratio <= 1.25:
        return True
    confirmation_day = (
        features.latest_change_pct is not None
        and 0.8 <= features.latest_change_pct <= 6.2
        and features.close_location_in_range is not None
        and features.close_location_in_range >= 0.58
    )
    return bool(confirmation_day and features.volume_ratio <= 1.55)


def _display_failed_rules(failed_rules: list[str], *, executable_low_suction: bool, setup_type: str) -> list[str]:
    if not executable_low_suction:
        return failed_rules
    if setup_type == "stealth_low_suction":
        setup_specific_rules = {
            "strong_leg",
            "pullback_structure",
            "support_acceptance",
            "reclaim_confirmation",
            "pullback_too_short",
            "pullback_too_late",
            "overheat",
        }
        return [rule for rule in failed_rules if rule not in setup_specific_rules]
    return [rule for rule in failed_rules if rule != "reclaim_confirmation"]


def _risk_penalty(features: DragonFeatures) -> tuple[float, list[str]]:
    flags: list[str] = []
    penalty = 0.0
    if _is_distribution_risk(features):
        flags.append("distribution_risk")
        penalty += 35.0
    if features.weekly_top_fractal_risk:
        flags.append("weekly_top_fractal_risk")
        penalty += 4.0
    if features.spiky_churn_risk:
        flags.append("spiky_churn_risk")
        penalty += 6.0
    if features.volume_stall_risk:
        flags.append("volume_stall_risk")
        penalty += 16.0
    if features.high_position_volume_stall_risk:
        flags.append("high_position_volume_stall_risk")
        penalty += 6.0
    if features.key_support_break_risk:
        flags.append("key_support_break_risk")
        penalty += 18.0
    if features.illiquid_forgotten_risk:
        flags.append("illiquid_forgotten_risk")
        penalty += 4.0
    if features.high_level_sideways_distribution_risk:
        flags.append("high_level_sideways_distribution_risk")
        penalty += 6.0
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
    failed = [
        flag
        for flag in risk_flags
        if flag
        in {
            "distribution_risk",
            "weak_rebound_ma5_below_ma10",
            "pullback_too_deep",
            "ma20_broken",
            "key_support_break_risk",
            "volume_stall_risk",
        }
    ]
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
    if _is_wide_ma_without_low_suction(features):
        failed.append("ma_convergence_too_wide_without_low_suction")
    if features.key_support_break_risk and "key_support_break_risk" not in failed:
        failed.append("key_support_break_risk")
    if features.volume_stall_risk and "volume_stall_risk" not in failed:
        failed.append("volume_stall_risk")
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
    if (
        support_type != "none"
        and features.low_suction_days >= 3
        and features.ma_convergence_pct is not None
        and features.ma_convergence_pct <= 5.0
        and not any(rule in failed_rules for rule in ("distribution_risk", "weak_rebound_ma5_below_ma10", "ma20_broken", "pullback_too_deep", "overheat"))
    ):
        return "LOW_SUCTION_BUILDUP"
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
    if (
        features.low_suction_days >= 3
        and features.support_hold_days >= 2
        and features.ma_convergence_pct is not None
        and features.ma_convergence_pct <= 4.0
        and features.ma20_distance_pct is not None
        and features.ma20_distance_pct >= -2.5
    ):
        return False
    if _has_quiet_low_suction_absorption(features):
        return False
    return (
        features.ma5_vs_ma10_pct < -2.0
        and features.ma10_distance_pct < 0
        and (features.ma5_slope_pct is None or features.ma5_slope_pct <= 0.3)
    )


def _has_quiet_low_suction_absorption(features: DragonFeatures) -> bool:
    if features.low_suction_days < 3:
        return False
    if features.support_hold_days < 2:
        return False
    if features.ma_convergence_pct is None or features.ma_convergence_pct > 13.0:
        return False
    if features.ma20_distance_pct is None or features.ma20_distance_pct < -3.2:
        return False
    if features.volume_ratio is None or features.volume_ratio > 1.15:
        return False
    if features.latest_change_pct is not None and features.latest_change_pct < -4.5:
        return False
    if features.drawdown_from_pivot_pct is not None and features.drawdown_from_pivot_pct < -20.0:
        return False
    return True


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
    relative_strength: float,
    strong_leg: float,
    pullback: float,
    support: float,
    reclaim: float,
    low_suction: float,
    stealth_low_suction: float,
    low_suction_days: int,
    support_hold_days: int,
    sector: float,
    financial: float,
    liquidity: float,
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
    executable_low_suction: bool,
    setup_type: str,
    fresh_stealth_low_suction: bool,
    dragon_total: float,
    stealth_total: float,
    low_suction_launch_bonus: float,
) -> dict[str, object]:
    recent_limit_up = features.near_limit_up_count_20d >= 1
    consecutive_bull = features.consecutive_bull_closes >= 4
    factor_count = sum(
        (
            recent_limit_up,
            consecutive_bull,
            features.upward_gap_in_leg,
            features.persistent_volume_expansion,
        )
    )
    weak_index_strength = bool(
        index_return_20d is not None
        and index_return_20d <= 0
        and consecutive_bull
        and features.return_20d is not None
        and features.return_20d > 0
    )
    low_suction_launch_confirmed = _is_low_suction_launch_confirmed(features, low_suction_days=low_suction_days)
    low_suction_stage = _low_suction_stage(features, setup_type, low_suction_days)
    low_suction_quality = low_suction_launch_quality_bucket(
        {
            "entry_setup": setup_type,
            "low_suction_days": low_suction_days,
            "low_suction_launch_confirmed": low_suction_launch_confirmed,
            "close_location_in_range": features.close_location_in_range,
            "volume_ratio_5d_20d": features.volume_ratio,
            "tail_buy_repeat_days": repeat_days,
            "pullback_days": features.pullback_days,
        }
    )
    payload = {
        "status": "ready",
        "return_5d": features.return_5d,
        "return_20d": features.return_20d,
        "return_60d": features.return_60d,
        "index_return_20d": index_return_20d,
        "max_drawdown_60d": features.max_drawdown_60d,
        "ma5": features.ma5,
        "ma10": features.ma10,
        "ma20": features.ma20,
        "ma30": features.ma30,
        "ma60": features.ma60,
        "ma5_distance_pct": features.ma5_distance_pct,
        "ma10_distance_pct": features.ma10_distance_pct,
        "ma20_distance_pct": features.ma20_distance_pct,
        "ma5_vs_ma10_pct": features.ma5_vs_ma10_pct,
        "ma10_vs_ma20_pct": features.ma10_vs_ma20_pct,
        "ma20_vs_ma30_pct": features.ma20_vs_ma30_pct,
        "ma_convergence_pct": features.ma_convergence_pct,
        "low_suction_days": low_suction_days,
        "support_hold_days": support_hold_days,
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
        "recent_limit_up_20d": recent_limit_up,
        "consecutive_bull_closes": features.consecutive_bull_closes,
        "upward_gap_in_leg": features.upward_gap_in_leg,
        "persistent_volume_expansion": features.persistent_volume_expansion,
        "limit_up_start_factor_count": factor_count,
        "weak_index_strength_confirmation": weak_index_strength,
        "latest_change_pct": features.latest_change_pct,
        "weekly_top_fractal_risk": features.weekly_top_fractal_risk,
        "spiky_churn_risk": features.spiky_churn_risk,
        "volume_stall_risk": features.volume_stall_risk,
        "high_position_volume_stall_risk": features.high_position_volume_stall_risk,
        "early_dragon_pullback_risk": _is_early_dragon_pullback_risk(features, setup_type, low_suction_days),
        "key_support_break_risk": features.key_support_break_risk,
        "illiquid_forgotten_risk": features.illiquid_forgotten_risk,
        "high_level_sideways_days": features.high_level_sideways_days,
        "high_level_sideways_distribution_risk": features.high_level_sideways_distribution_risk,
        "strong_leg_score": strong_leg,
        "pullback_structure_score": pullback,
        "support_acceptance_score": support,
        "reclaim_confirmation_score": reclaim,
        "low_suction_buildup_score": low_suction,
        "stealth_low_suction_score": stealth_low_suction,
        "setup_type": setup_type,
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
        "fresh_stealth_low_suction": fresh_stealth_low_suction,
        "low_suction_launch_confirmed": low_suction_launch_confirmed,
        "low_suction_launch_bonus": low_suction_launch_bonus,
        "low_suction_stage": low_suction_stage,
        "low_suction_stage_label": _low_suction_stage_label(low_suction_stage),
        "low_suction_launch_quality_bucket": low_suction_quality,
        "low_suction_launch_quality_label": low_suction_launch_quality_label(low_suction_quality),
        "score_breakdown": _score_breakdown(
            relative_strength=relative_strength,
            strong_leg=strong_leg,
            pullback=pullback,
            support=support,
            reclaim=reclaim,
            low_suction=low_suction,
            sector=sector,
            financial=financial,
            smart_money=smart_money,
            liquidity=liquidity,
            risk_penalty=risk_penalty,
            low_suction_launch_bonus=low_suction_launch_bonus,
        ),
        "setup_scores": {
            "dragon_pullback": round(clamp_score(dragon_total), 4),
            "stealth_low_suction": round(clamp_score(stealth_total), 4),
        },
        "score_notes": _score_notes(
            features,
            state,
            setup_type,
            support_type,
            low_suction,
            stealth_low_suction,
            failed_rules,
            low_suction_days,
            support_hold_days,
            executable_low_suction,
            fresh_stealth_low_suction,
        ),
        "selection_rule": "daily_close_visible_signal",
        "entry_setup": setup_type,
    }
    ensure_entry_family_context(payload)
    return payload


def _score_breakdown(
    *,
    relative_strength: float | None,
    strong_leg: float,
    pullback: float,
    support: float,
    reclaim: float,
    low_suction: float,
    sector: float | None,
    financial: float | None,
    smart_money: float,
    liquidity: float | None,
    risk_penalty: float,
    low_suction_launch_bonus: float,
) -> list[dict[str, object]]:
    rows = [
        ("相对强度", relative_strength, 0.20),
        ("第一波强度", strong_leg, 0.16),
        ("回踩结构", pullback, 0.15),
        ("均线承接", support, 0.14),
        ("弱转强确认", reclaim, 0.12),
        ("低吸蓄势", low_suction, 0.07),
        ("主线板块", sector, 0.08),
        ("财务改善", financial, 0.04),
        ("资金热度", smart_money, 0.06),
        ("流动性", liquidity, 0.10),
    ]
    if low_suction_launch_bonus:
        rows.append(("低吸启动确认", low_suction_launch_bonus, 1.0))
    breakdown = [
        {
            "name": name,
            "score": score,
            "weight": weight,
            "contribution": round(float(score or 0) * weight, 4),
        }
        for name, score, weight in rows
    ]
    breakdown.append({"name": "风险扣分", "score": -risk_penalty, "weight": 1.0, "contribution": -risk_penalty})
    return breakdown


def _score_notes(
    features: DragonFeatures,
    state: str,
    setup_type: str,
    support_type: str,
    low_suction: float,
    stealth_low_suction: float,
    failed_rules: list[str],
    low_suction_days: int,
    support_hold_days: int,
    executable_low_suction: bool,
    fresh_stealth_low_suction: bool,
) -> list[str]:
    notes = [
        f"状态 {state}",
        f"入口 {setup_type}",
        f"承接 {support_type}",
        f"低吸蓄势 {low_suction_days} 天",
        f"支撑未破 {support_hold_days} 天",
    ]
    if features.ma_convergence_pct is not None:
        notes.append(f"MA5/10/20/30 收敛宽度 {features.ma_convergence_pct:.2f}%")
    notes.append(f"低吸蓄势分 {low_suction:.1f}")
    notes.append(f"低吸洗盘分 {stealth_low_suction:.1f}")
    if fresh_stealth_low_suction:
        notes.append("低吸洗盘新启动")
    if _is_low_suction_launch_confirmed(features, low_suction_days=low_suction_days):
        notes.append("低吸蓄势后首个温和拉升确认")
    if executable_low_suction:
        notes.append("低吸蓄势入口已满足")
    if _is_early_dragon_pullback_risk(features, setup_type, low_suction_days):
        notes.append("经典龙回头偏早：均线发散且缺少低吸蓄势")
    if failed_rules:
        notes.append("扣分/拒绝: " + ", ".join(failed_rules))
    return notes


def _low_suction_stage(features: DragonFeatures, setup_type: str, low_suction_days: int) -> str:
    if setup_type != "stealth_low_suction" and low_suction_days < 3:
        return "not_low_suction"
    if _is_low_suction_launch_confirmed(features, low_suction_days=low_suction_days):
        if features.pullback_days >= 12:
            return "late_confirmed_lift"
        if features.volume_ratio is not None and features.volume_ratio < 0.75:
            return "thin_confirmed_lift"
        if (
            features.close_location_in_range is not None
            and 0.55 <= features.close_location_in_range <= 0.72
            and features.volume_ratio is not None
            and 0.80 <= features.volume_ratio <= 1.40
        ):
            return "balanced_first_lift"
        return "confirmed_lift"
    if low_suction_days >= 6:
        return "mature_buildup_waiting_lift"
    if low_suction_days >= 3:
        return "buildup_waiting_lift"
    return "not_low_suction"


def _low_suction_stage_label(stage: str) -> str:
    labels = {
        "not_low_suction": "非低吸蓄势",
        "buildup_waiting_lift": "低吸蓄势等待上拉",
        "mature_buildup_waiting_lift": "低吸蓄势已久等待上拉",
        "balanced_first_lift": "低吸首个均衡上拉",
        "thin_confirmed_lift": "低吸上拉量能偏弱",
        "late_confirmed_lift": "低吸启动偏晚",
        "confirmed_lift": "低吸上拉确认",
    }
    return labels.get(stage, stage)


def _is_early_dragon_pullback_risk(features: DragonFeatures, setup_type: str, low_suction_days: int) -> bool:
    if setup_type != "dragon_pullback" or low_suction_days > 0:
        return False
    if features.ma_convergence_pct is None or features.ma_convergence_pct < 18.0:
        return False
    if features.latest_change_pct is None or features.latest_change_pct < 1.0:
        return False
    if features.close_location_in_range is None or features.close_location_in_range < 0.55:
        return False
    return True


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


def _ma_convergence_pct(ma5: float | None, ma10: float | None, ma20: float | None, ma30: float | None) -> float | None:
    values = [value for value in (ma5, ma10, ma20, ma30) if value is not None and value > 0]
    if len(values) < 4:
        return None
    base = sum(values) / len(values)
    if base <= 0:
        return None
    return (max(values) - min(values)) / base * 100


def _low_suction_days(bars: list[Bar], lookback: int = 6) -> int:
    days = 0
    start = max(len(bars) - lookback, 0)
    for end_index in range(start + 1, len(bars) + 1):
        if _is_low_suction_day(bars[:end_index]):
            days += 1
    return days


def _is_low_suction_day(bars: list[Bar]) -> bool:
    closes = [bar.close_price for bar in bars]
    highs = [bar.high_price for bar in bars]
    volumes = [bar.volume or 0 for bar in bars]
    if len(closes) < 30:
        return False
    latest = bars[-1]
    ma5 = moving_average(closes, 5)
    ma10 = moving_average(closes, 10)
    ma20 = moving_average(closes, 20)
    ma30 = moving_average(closes, 30)
    ma5_distance = pct_distance(latest.close_price, ma5)
    ma10_distance = pct_distance(latest.close_price, ma10)
    ma20_distance = pct_distance(latest.close_price, ma20)
    convergence = _ma_convergence_pct(ma5, ma10, ma20, ma30)
    previous_convergence = _previous_ma_convergence(closes)
    volume5 = moving_average(volumes, 5)
    volume20 = moving_average(volumes, 20)
    volume_ratio = volume5 / volume20 if volume5 is not None and volume20 else None
    derived_changes = _derived_change_pcts(bars)
    latest_change = _bar_change_pct(bars, len(bars) - 1, derived_changes)
    # 近期涨停：涨停把均线拉发散，conv 暂超 8.8 是正常回踩形态（非低吸失败）
    recent_limit_up = any(
        (c is not None and c >= 9.5) for c in derived_changes[-8:]
    )
    recent_high = max(highs[-20:])
    drawdown = pct_distance(latest.close_price, recent_high)

    near_short_ma = (
        (ma5_distance is not None and -3.2 <= ma5_distance <= 4.2)
        or (ma10_distance is not None and -4.2 <= ma10_distance <= 4.5)
    )
    ma20_acceptance = ma20_distance is not None and -3.2 <= ma20_distance <= 4.8
    trend_not_broken = ma20_distance is not None and ma20_distance >= -3.2
    quiet_volume = volume_ratio is not None and volume_ratio <= 1.15
    controlled_lift = (
        latest_change is not None
        and 0.8 <= latest_change <= 6.2
        and volume_ratio is not None
        and volume_ratio <= 1.55
    )
    convergence_ok = convergence is not None and (
        convergence <= 8.8
        or (
            convergence <= 13.0
            and previous_convergence is not None
            and convergence <= previous_convergence - 0.25
            and quiet_volume
            and ma20_distance is not None
            and ma20_distance >= -2.5
        )
        # 涨停后回踩贴线：涨停拉发散均线使 conv 暂超 8.8，但贴短期均线且趋势未破，
        # 属有效低吸（如5-28涨停后6-01~03贴MA5接货）。统计验证这类票后续收益不差于
        # 正常低吸，故放宽至 conv<=13。见 scripts/convergence_pullback_study.py。
        or (
            recent_limit_up
            and near_short_ma
            and trend_not_broken
            and convergence <= 13.0
        )
    )
    daily_not_broken = latest_change is None or (-4.5 <= latest_change <= 8.5)
    drawdown_controlled = drawdown is None or drawdown >= -20.0
    return bool(
        (near_short_ma or ma20_acceptance)
        and trend_not_broken
        and convergence_ok
        and (quiet_volume or controlled_lift)
        and daily_not_broken
        and drawdown_controlled
    )


def _previous_ma_convergence(closes: list[float]) -> float | None:
    if len(closes) < 31:
        return None
    previous = closes[:-1]
    return _ma_convergence_pct(
        moving_average(previous, 5),
        moving_average(previous, 10),
        moving_average(previous, 20),
        moving_average(previous, 30),
    )


def _support_hold_days(bars: list[Bar], lookback: int = 6) -> int:
    days = 0
    start = max(len(bars) - lookback, 0)
    for end_index in range(start + 1, len(bars) + 1):
        closes = [bar.close_price for bar in bars[:end_index]]
        if len(closes) < 20:
            continue
        latest = bars[end_index - 1]
        ma10 = moving_average(closes, 10)
        ma20 = moving_average(closes, 20)
        ma10_distance = pct_distance(latest.close_price, ma10)
        ma20_distance = pct_distance(latest.close_price, ma20)
        if ma10_distance is not None and ma20_distance is not None and ma10_distance >= -3.2 and ma20_distance >= -3.5:
            days += 1
    return days


def _consecutive_bull_closes(bars: list[Bar], lookback: int = 8) -> int:
    count = 0
    start = max(len(bars) - lookback, 0)
    for index in range(len(bars) - 1, start - 1, -1):
        bar = bars[index]
        previous_close = bars[index - 1].close_price if index > 0 else None
        close_to_close_up = previous_close is not None and bar.close_price > previous_close
        close_above_open = bar.close_price > bar.open_price
        if close_above_open or close_to_close_up:
            count += 1
            continue
        break
    return count


def _has_upward_gap_in_leg(bars: list[Bar], lookback: int = 20) -> bool:
    start = max(len(bars) - lookback, 1)
    for index in range(start, len(bars)):
        previous_close = bars[index - 1].close_price
        if previous_close <= 0:
            continue
        bar = bars[index]
        gap_pct = (bar.open_price / previous_close - 1) * 100
        invalidated = bar.low_price < previous_close * 0.995 and bar.close_price <= previous_close
        if gap_pct >= 1.5 and not invalidated:
            return True
    return False


def _has_persistent_volume_expansion(bars: list[Bar], lookback: int = 20) -> bool:
    if len(bars) < 25:
        return False
    start = max(len(bars) - lookback, 0)
    strong_days = 0
    broad_days = 0
    for index in range(start, len(bars)):
        baseline = moving_average([bar.volume or 0 for bar in bars[:index]], 20)
        volume = bars[index].volume or 0
        if not baseline or baseline <= 0:
            continue
        ratio = volume / baseline
        if ratio >= 1.8:
            strong_days += 1
        if ratio >= 1.4:
            broad_days += 1
    return strong_days >= 2 or broad_days >= 3


def _is_weekly_top_fractal_risk(bars: list[Bar]) -> bool:
    if len(bars) < 45:
        return False
    weekly = _weekly_bars(bars)
    if len(weekly) < 5:
        return False
    left, middle, right = weekly[-3], weekly[-2], weekly[-1]
    top_fractal = middle.high_price > left.high_price and middle.high_price > right.high_price
    reversal = right.close_price < middle.close_price and right.high_price <= middle.high_price * 1.01
    high_location = _series_location([bar.close_price for bar in bars], bars[-1].close_price, 60)
    return bool(top_fractal and reversal and high_location is not None and high_location >= 0.68)


def _weekly_bars(bars: list[Bar]) -> list[Bar]:
    grouped: dict[tuple[int, int], list[Bar]] = {}
    for bar in bars:
        iso_year, iso_week, _ = bar.trade_date.isocalendar()
        grouped.setdefault((iso_year, iso_week), []).append(bar)
    result: list[Bar] = []
    for key in sorted(grouped):
        chunk = sorted(grouped[key], key=lambda item: item.trade_date)
        result.append(
            Bar(
                trade_date=chunk[-1].trade_date,
                open_price=chunk[0].open_price,
                high_price=max(bar.high_price for bar in chunk),
                low_price=min(bar.low_price for bar in chunk),
                close_price=chunk[-1].close_price,
                volume=sum(bar.volume or 0 for bar in chunk),
                turnover=sum(daily_turnover_yuan(bar) for bar in chunk),
                change_pct=None,
            )
        )
    return result


def _is_spiky_churn_risk(bars: list[Bar], derived_changes: list[float | None]) -> bool:
    recent = bars[-20:]
    recent_changes = derived_changes[-20:]
    if len(recent) < 12:
        return False
    long_range_days = sum(1 for bar in recent if _daily_range_pct(bar) >= 12.0)
    large_move_days = sum(1 for value in recent_changes if value is not None and abs(value) >= 4.0)
    alternating_days = 0
    for left, right in zip(recent_changes, recent_changes[1:]):
        if left is None or right is None:
            continue
        if abs(left) >= 3.5 and abs(right) >= 3.5 and left * right < 0:
            alternating_days += 1
    return bool(long_range_days >= 6 and large_move_days >= 8 and alternating_days >= 5)


def _is_volume_stall_risk(closes: list[float], volumes: list[float], turnovers: list[float]) -> bool:
    high_location = _series_location(closes, closes[-1], 60)
    volume_ratio = _recent_ratio(volumes, 5, 20)
    turnover_ratio = _recent_ratio(turnovers, 5, 20)
    return_5d = period_return(closes, 5)
    return bool(
        high_location is not None
        and high_location >= 0.68
        and ((volume_ratio is not None and volume_ratio >= 1.8) or (turnover_ratio is not None and turnover_ratio >= 1.8))
        and return_5d is not None
        and return_5d <= 2.0
    )


def _is_high_position_volume_stall_risk(closes: list[float], volumes: list[float], turnovers: list[float]) -> bool:
    high_location = _series_location(closes, closes[-1], 60)
    volume_ratio = _recent_ratio(volumes, 5, 20)
    turnover_ratio = _recent_ratio(turnovers, 5, 20)
    return_20d = period_return(closes, 20)
    return bool(
        high_location is not None
        and high_location >= 0.70
        and ((volume_ratio is not None and volume_ratio >= 1.35) or (turnover_ratio is not None and turnover_ratio >= 1.35))
        and return_20d is not None
        and -6.0 <= return_20d <= 8.0
    )


def _is_key_support_break_risk(close: float, ma20: float | None, ma30: float | None) -> bool:
    ma20_break = ma20 is not None and close < ma20 * 0.965
    ma30_break = ma30 is not None and close < ma30 * 0.970
    return bool(ma20_break or ma30_break)


def _is_illiquid_forgotten_risk(volumes: list[float], turnovers: list[float]) -> bool:
    if len(volumes) < 60 or len(turnovers) < 60:
        return False
    volume5 = moving_average(volumes, 5)
    volume60 = moving_average(volumes, 60)
    turnover5 = moving_average(turnovers, 5)
    turnover60 = moving_average(turnovers, 60)
    turnover_recent = turnover5 or 0
    volume_ratio = volume5 / volume60 if volume5 is not None and volume60 else None
    turnover_ratio = turnover5 / turnover60 if turnover5 is not None and turnover60 else None
    return bool(
        turnover_recent < 30_000_000
        or (
            volume_ratio is not None
            and turnover_ratio is not None
            and volume_ratio <= 0.16
            and turnover_ratio <= 0.16
        )
    )


def _high_level_sideways_days(closes: list[float], lookback: int = 20) -> int:
    if len(closes) < 60:
        return 0
    recent = closes[-lookback:]
    recent_mid = sum(recent) / len(recent)
    high_location = _series_location(closes, recent_mid, 60)
    if high_location is None or high_location < 0.64:
        return 0
    high = max(recent)
    low = min(recent)
    base = sum(recent) / len(recent)
    if base <= 0:
        return 0
    range_width = (high / low - 1) * 100 if low > 0 else 999.0
    range_return = (recent[-1] / recent[0] - 1) * 100 if recent[0] > 0 else None
    if range_width <= 12.0 and range_return is not None and -6.5 <= range_return <= 8.5:
        return len(recent)
    return 0


def _is_high_level_sideways_distribution_risk(closes: list[float], volumes: list[float], turnovers: list[float]) -> bool:
    days = _high_level_sideways_days(closes)
    if days < 15:
        return False
    volume_ratio = _recent_ratio(volumes, 5, 20)
    turnover_ratio = _recent_ratio(turnovers, 5, 20)
    sustained_volume_ratio = _recent_ratio(volumes, 20, 60)
    sustained_turnover_ratio = _recent_ratio(turnovers, 20, 60)
    return_5d = period_return(closes, 5)
    stale_volume = (
        (volume_ratio is not None and volume_ratio >= 1.25)
        or (turnover_ratio is not None and turnover_ratio >= 1.25)
        or (sustained_volume_ratio is not None and sustained_volume_ratio >= 1.35)
        or (sustained_turnover_ratio is not None and sustained_turnover_ratio >= 1.35)
    )
    weak_progress = return_5d is not None and return_5d <= 1.5
    return bool(stale_volume and weak_progress)


def _series_location(values: list[float], latest: float, lookback: int) -> float | None:
    recent = values[-lookback:]
    if not recent:
        return None
    high = max(recent)
    low = min(recent)
    if high <= low:
        return None
    return (latest - low) / (high - low)


def _recent_ratio(values: list[float], short: int, long: int) -> float | None:
    short_ma = moving_average(values, short)
    long_ma = moving_average(values, long)
    if short_ma is None or long_ma is None or long_ma <= 0:
        return None
    return short_ma / long_ma


def _daily_range_pct(bar: Bar) -> float:
    if bar.close_price <= 0:
        return 0.0
    return (bar.high_price / bar.low_price - 1) * 100 if bar.low_price > 0 else 0.0


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
