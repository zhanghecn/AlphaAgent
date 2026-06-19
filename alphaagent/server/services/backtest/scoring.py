"""Scoring helpers for portfolio backtests."""

from __future__ import annotations

from copy import copy
from datetime import date
from typing import Any, Callable

from alphaagent.server.services.backtest.schemas import BacktestParams, ScoreContext
from alphaagent.server.services.quant import screening_payloads
from alphaagent.server.services.quant.low_suction_quality import low_suction_launch_quality_bucket
from alphaagent.server.services.quant.strategy_registry import score_strategy


def score_day(
    session,
    bars_by_symbol: dict[str, list[Any]],
    trade_date: date,
    params: BacktestParams,
    score_cache: dict[date, list[Any]] | None = None,
    score_context: ScoreContext | None = None,
    *,
    score_candidates_for_day: Callable[..., list[Any]] | None = None,
) -> list[Any]:
    """Return sorted buy candidates for one signal date."""

    if score_cache is not None and trade_date in score_cache:
        scores = score_cache[trade_date]
    else:
        scorer = score_candidates_for_day or globals()["score_candidates_for_day"]
        scores = scorer(session, bars_with_signal_date(bars_by_symbol, trade_date), trade_date, params, score_context)
        if score_cache is not None:
            score_cache[trade_date] = scores
    candidates = [score for score in scores if is_buy_candidate(score, params)]
    candidates = [_with_entry_launch_quality_score(score, params) for score in candidates]
    candidates = [_with_entry_launch_risk_penalty(score, params) for score in candidates]
    candidates = [_with_low_suction_market_risk_penalty(score, params) for score in candidates]
    candidates = [_with_market_adaptive_setup_weighting(score, params) for score in candidates]
    candidates = [_with_low_suction_first_lift_bonus(score, params) for score in candidates]
    candidates.sort(key=lambda item: (-item.total_score, item.vt_symbol))
    return candidates


def score_candidates_for_day(
    session,
    bars_by_symbol: dict[str, list[Any]],
    trade_date: date,
    params: BacktestParams,
    score_context: ScoreContext | None,
    *,
    load_index_return_20d,
    load_sector_scores,
    load_financial_scores,
    load_fund_flow_scores,
    load_hot_rank_scores,
    load_lhb_scores,
    financial_scores_from_context,
) -> list[Any]:
    """Score every symbol with data visible at ``trade_date``."""

    vt_symbols = list(bars_by_symbol.keys())
    index_return_20d = load_index_return_20d(session, trade_date)
    sector_scores = load_sector_scores(session, vt_symbols, trade_date)
    financial_scores = (
        financial_scores_from_context(score_context, trade_date)
        if score_context is not None
        else load_financial_scores(session, vt_symbols, trade_date)
    )
    fund_flow_scores = load_fund_flow_scores(session, vt_symbols, trade_date)
    hot_rank_scores = load_hot_rank_scores(session, vt_symbols, trade_date)
    lhb_scores = load_lhb_scores(session, vt_symbols, trade_date)
    scores = []
    for vt_symbol, bars in bars_by_symbol.items():
        score = score_strategy(
            params.strategy,
            vt_symbol,
            bars,
            trade_date,
            index_return_20d=index_return_20d,
            sector_score=sector_scores.get(vt_symbol),
            financial_score=financial_scores.get(vt_symbol),
            fund_flow_score=fund_flow_scores.get(vt_symbol),
            hot_rank_score=hot_rank_scores.get(vt_symbol),
            lhb_score=lhb_scores.get(vt_symbol),
        )
        scores.append(score)
    scores.sort(key=lambda item: (-item.total_score, item.vt_symbol))
    return scores


def bars_with_signal_date(bars_by_symbol: dict[str, list[Any]], trade_date: date) -> dict[str, list[Any]]:
    """Keep symbols whose latest visible bar is exactly the signal date."""

    result = {}
    for vt_symbol, bars in bars_by_symbol.items():
        visible = [bar for bar in bars if bar.trade_date <= trade_date]
        if visible and visible[-1].trade_date == trade_date:
            result[vt_symbol] = visible
    return result


def is_buy_candidate(score, params: BacktestParams) -> bool:
    """Return whether a score is eligible for portfolio buy planning."""

    if score.evidence.get("status") != "ready":
        return False
    if score.risk_score < 35 or score.liquidity_score < 25:
        return False
    if params.strict_entry:
        return _is_executable_entry_signal_for_params(score, params) and _passes_backtest_entry_experiments(score, params)
    if score.total_score < screening_payloads.effective_entry_score_threshold(score, params.min_entry_score):
        return False
    return _passes_backtest_entry_experiments(score, params)


def is_executable_entry_signal(score, min_entry_score: float) -> bool:
    return bool(
        getattr(score, "entry_signal", False)
        and not executable_entry_failed_rules(score, min_entry_score, include_low_suction_launch_gate=False)
    )


def _is_executable_entry_signal_for_params(score, params: BacktestParams) -> bool:
    return bool(
        getattr(score, "entry_signal", False)
        and not executable_entry_failed_rules(
            score,
            params.min_entry_score,
            include_low_suction_launch_gate=params.require_low_suction_launch_confirmation,
        )
    )


def executable_entry_failed_rules(
    score,
    min_entry_score: float,
    *,
    include_low_suction_launch_gate: bool = False,
) -> list[str]:
    return screening_payloads.failed_entry_rules(
        score,
        min_entry_score,
        include_low_suction_launch_gate=include_low_suction_launch_gate,
    )


def _passes_backtest_entry_experiments(score, params: BacktestParams) -> bool:
    evidence = getattr(score, "evidence", {}) or {}
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if params.require_low_suction_launch_confirmation and setup == "stealth_low_suction":
        return bool(evidence.get("low_suction_launch_confirmed"))
    if params.exclude_repeated_dragon_pullback and setup == "dragon_pullback":
        return bool(evidence.get("fresh_tail_buy", True)) and int(float(evidence.get("tail_buy_repeat_days") or 0)) == 0
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    if params.require_low_suction_launch_for_low_suction_context and low_suction_days >= 3:
        return bool(evidence.get("low_suction_launch_confirmed"))
    has_low_suction_context = setup == "stealth_low_suction" or low_suction_days >= 3
    if params.require_balanced_low_suction_launch_quality and has_low_suction_context:
        return low_suction_launch_quality_bucket(evidence) in {
            "balanced_first_lift",
            "high_close_launch",
            "other_confirmed_launch",
        }
    if params.enable_low_suction_false_launch_watch_gate:
        launch_bucket = str(
            evidence.get("low_suction_launch_quality_bucket")
            or low_suction_launch_quality_bucket(evidence)
            or ""
        )
        decision = classify_low_suction_false_launch_watch(
            low_suction_days=low_suction_days,
            launch_quality_bucket=launch_bucket,
            close_location_in_range=_float_or_none(evidence.get("close_location_in_range")),
            volume_ratio_5d_20d=_float_or_none(evidence.get("volume_ratio_5d_20d")),
            market_warning_level=_float_or_none(evidence.get("market_warning_level")),
            market_recovery_level=_market_recovery_level(evidence),
            recent_limit_up_20d=bool(
                evidence.get("recent_limit_up_20d")
                or evidence.get("limit_up_count_20d")
                or evidence.get("near_limit_up_count_20d")
            ),
            theme_alignment=str(evidence.get("stock_theme_alignment") or evidence.get("theme_alignment") or "unknown"),
            min_low_suction_days=params.low_suction_false_launch_min_days,
            min_warning_level=params.low_suction_false_launch_min_warning_level,
            max_recovery_level=params.low_suction_false_launch_max_recovery_level,
        )
        if decision["watch_only"]:
            return False
    return True


def _with_entry_launch_quality_score(score, params: BacktestParams):
    if not params.enable_entry_launch_quality_score:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    adjustment = entry_launch_quality_adjustment(evidence)
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["entry_launch_quality_adjustment"] = round(adjustment, 4)
    adjusted.evidence["entry_launch_quality_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["entry_launch_quality_notes"] = entry_launch_quality_notes(evidence)
    return adjusted


def _with_entry_launch_risk_penalty(score, params: BacktestParams):
    if not params.enable_entry_launch_risk_penalty:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    penalty = entry_launch_risk_penalty_adjustment(evidence)
    if penalty == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + penalty, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["entry_launch_risk_penalty_adjustment"] = round(penalty, 4)
    adjusted.evidence["entry_launch_risk_penalty_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["entry_launch_risk_penalty_notes"] = entry_launch_risk_penalty_notes(evidence)
    return adjusted


def _with_low_suction_market_risk_penalty(score, params: BacktestParams):
    if not params.enable_low_suction_market_risk_penalty:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    penalty = low_suction_market_risk_penalty_adjustment(evidence)
    if penalty == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + penalty, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["low_suction_market_risk_penalty_adjustment"] = round(penalty, 4)
    adjusted.evidence["low_suction_market_risk_penalty_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["low_suction_market_risk_penalty_notes"] = low_suction_market_risk_penalty_notes(evidence)
    return adjusted


def _with_market_adaptive_setup_weighting(score, params: BacktestParams):
    if not params.enable_market_adaptive_setup_weighting:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = market_adaptive_setup_weighting(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["market_adaptive_setup_adjustment"] = round(adjustment, 4)
    adjusted.evidence["market_adaptive_setup_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["market_adaptive_setup_profile"] = decision["profile"]
    adjusted.evidence["market_adaptive_recommended_style"] = decision["recommended_style"]
    adjusted.evidence["market_adaptive_setup_notes"] = decision["notes"]
    return adjusted


def _with_low_suction_first_lift_bonus(score, params: BacktestParams):
    if not params.enable_low_suction_first_lift_bonus:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    adjustment = low_suction_first_lift_bonus_adjustment(evidence)
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["low_suction_first_lift_bonus_adjustment"] = round(adjustment, 4)
    adjusted.evidence["low_suction_first_lift_bonus_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["low_suction_first_lift_bonus_notes"] = low_suction_first_lift_bonus_notes(evidence)
    return adjusted


def entry_launch_quality_adjustment(evidence: dict[str, Any]) -> float:
    """Return a research-only ranking adjustment from entry-day visible factors."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days"))
    pullback_days = _float_or_none(evidence.get("pullback_days"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    tail_repeat = _float_or_none(evidence.get("tail_buy_repeat_days"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))

    adjustment = 0.0
    if close_location is not None:
        if 0.58 <= close_location <= 0.70:
            adjustment += 2.0
        elif close_location >= 0.80:
            adjustment -= 1.2
        elif close_location < 0.45:
            adjustment -= 1.5

    if volume_ratio is not None:
        if 1.2 <= volume_ratio <= 1.8:
            adjustment += 1.8
        elif 0.7 <= volume_ratio < 1.2:
            adjustment += 0.4
        elif volume_ratio < 0.7:
            adjustment -= 2.0
        elif volume_ratio > 2.2:
            adjustment -= 1.5

    if pullback_days is not None:
        if 3 <= pullback_days <= 8:
            adjustment += 0.8
        elif pullback_days >= 12:
            adjustment -= 3.0

    if low_suction_days is not None:
        if setup == "stealth_low_suction":
            if low_suction_days >= 5 and close_location is not None and close_location < 0.58:
                adjustment -= 2.0
            elif 3 <= low_suction_days <= 6 and close_location is not None and 0.58 <= close_location <= 0.70:
                adjustment += 1.2
        elif low_suction_days >= 3:
            adjustment += 0.4

    if ma_convergence is not None and setup == "stealth_low_suction":
        if ma_convergence <= 5.0 and not (close_location is not None and close_location >= 0.58):
            adjustment -= 1.2
        elif 5.0 < ma_convergence <= 8.8 and close_location is not None and close_location >= 0.58:
            adjustment += 0.6

    if tail_repeat is not None and tail_repeat >= 3:
        adjustment -= 1.2
    elif tail_repeat is not None and 1 <= tail_repeat <= 2 and setup == "dragon_pullback":
        adjustment -= 0.4

    if latest_change is not None and ma5_distance is not None:
        if latest_change > 5.5 and ma5_distance > 3.2:
            adjustment -= 1.6
        elif 0.4 <= latest_change <= 3.8 and -0.8 <= ma5_distance <= 2.8:
            adjustment += 0.8

    return max(min(adjustment, 5.0), -6.0)


def low_suction_first_lift_bonus_adjustment(evidence: dict[str, Any]) -> float:
    """Return a narrow bonus for the first clean lift after low-suction buildup."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    if setup != "stealth_low_suction" or low_suction_days < 3:
        return 0.0
    if not evidence.get("low_suction_launch_confirmed"):
        return 0.0

    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    if launch_bucket not in {"balanced_first_lift", "other_confirmed_launch"}:
        return 0.0

    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    return_60d = _float_or_none(evidence.get("return_60d"))

    if close_location is not None and (close_location < 0.52 or close_location > 0.78):
        return 0.0
    if volume_ratio is not None and not (0.75 <= volume_ratio <= 1.35):
        return 0.0
    if ma_convergence is not None and ma_convergence > 7.5:
        return 0.0
    if latest_change is not None and not (0.4 <= latest_change <= 4.8):
        return 0.0
    if ma5_distance is not None and not (-0.8 <= ma5_distance <= 3.2):
        return 0.0
    if ma10_distance is not None and not (-1.2 <= ma10_distance <= 4.5):
        return 0.0
    if return_60d is not None and return_60d >= 90:
        return 0.0
    if evidence.get("high_level_sideways_distribution_risk") or evidence.get("volume_stall_risk"):
        return 0.0

    bonus = 1.0
    if low_suction_days >= 5:
        bonus += 0.5
    if ma_convergence is not None and ma_convergence <= 4.5:
        bonus += 0.4
    if volume_ratio is not None and 0.85 <= volume_ratio <= 1.15:
        bonus += 0.3
    return min(bonus, 2.0)


def entry_launch_risk_penalty_adjustment(evidence: dict[str, Any]) -> float:
    """Return a research-only penalty for the worst visible launch-risk buckets."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days"))
    pullback_days = _float_or_none(evidence.get("pullback_days"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))

    penalty = 0.0
    if pullback_days is not None and pullback_days >= 12:
        penalty -= 2.5
    if volume_ratio is not None and volume_ratio < 0.7:
        penalty -= 2.0
    if setup == "stealth_low_suction" and low_suction_days is not None and low_suction_days >= 5:
        if close_location is not None and close_location < 0.58:
            penalty -= 2.0
    return max(penalty, -5.0)


def low_suction_market_risk_penalty_adjustment(evidence: dict[str, Any]) -> float:
    """Return a research-only penalty for weak low-suction launches in weak markets."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    if setup != "stealth_low_suction" or not evidence.get("low_suction_launch_confirmed"):
        return 0.0

    market_risk = _low_suction_market_risk_score(evidence)
    if market_risk <= 0:
        return 0.0
    launch_risk = _low_suction_launch_risk_score(evidence)
    if launch_risk <= 0:
        return 0.0

    penalty = -2.0 - market_risk - launch_risk
    return max(penalty, -6.0)


def market_adaptive_setup_weighting(evidence: dict[str, Any]) -> dict[str, Any]:
    """Return research-only setup weighting from signal-day visible market context."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    regime = str(evidence.get("dynamic_market_regime") or "")
    recovery_level = _market_recovery_level(evidence)
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    breadth = _float_or_none(evidence.get("market_breadth_score"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    tail_repeat = _float_or_none(evidence.get("tail_buy_repeat_days")) or 0.0
    theme_alignment = str(evidence.get("stock_theme_alignment") or evidence.get("theme_alignment") or "unknown")
    theme_strength = _float_or_none(evidence.get("theme_strength"))
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    has_limit_up_start = bool(
        evidence.get("recent_limit_up_20d")
        or evidence.get("limit_up_count_20d")
        or evidence.get("near_limit_up_count_20d")
    )
    has_start_signal = bool(
        has_limit_up_start
        or (_float_or_none(evidence.get("consecutive_bull_closes")) or 0.0) >= 4
        or evidence.get("upward_gap_in_leg")
        or evidence.get("persistent_volume_expansion")
        or evidence.get("weak_index_strength_confirmation")
    )
    is_low_suction = setup == "stealth_low_suction" or low_suction_days >= 3
    is_low_suction_launch = is_low_suction and launch_confirmed
    is_balanced_launch = launch_bucket in {
        "balanced_first_lift",
        "high_close_launch",
        "other_confirmed_launch",
    }
    is_plain_dragon = setup == "dragon_pullback" and low_suction_days < 3
    is_dragon_overlap = setup == "dragon_pullback" and low_suction_days >= 3
    has_mainline_alignment = theme_alignment in {"aligned", "strong", "mainline_aligned", "leader_theme", "theme_related"} or (
        theme_strength is not None and theme_strength >= 72
    )
    has_high_level_risk = bool(
        evidence.get("early_dragon_pullback_risk")
        or evidence.get("high_level_sideways_distribution_risk")
        or evidence.get("volume_stall_risk")
        or evidence.get("key_support_break_risk")
    )

    profile = _market_adaptive_profile(
        regime=regime,
        warning_level=warning_level,
        recovery_level=recovery_level,
        breadth=breadth,
    )
    adjustment = 0.0
    notes: list[str] = []

    if profile == "weak_defensive":
        recommended_style = "低吸首个有效上拉"
        if is_low_suction_launch and is_balanced_launch and has_start_signal:
            adjustment += 3.0
            notes.append("弱市优先：低吸蓄势后出现首个有效上拉")
        elif is_low_suction_launch and is_balanced_launch:
            adjustment += 1.4
            notes.append("弱市保留：低吸上拉质量较稳")
        elif is_low_suction and not launch_confirmed:
            adjustment -= 2.2
            notes.append("弱市降权：低吸蓄势未确认上拉")
        if is_plain_dragon:
            adjustment -= 2.4
            notes.append("弱市降权：普通龙回头缺少低位蓄势")
        if has_high_level_risk:
            adjustment -= 1.4
            notes.append("弱市降权：存在高位/破位/滞涨风险")
    elif profile == "mainline_active":
        recommended_style = "龙回头回踩"
        if is_plain_dragon and tail_repeat <= 1:
            adjustment += 2.0
            notes.append("主线期优先：新鲜龙回头回踩")
        if is_dragon_overlap and launch_confirmed:
            adjustment += 1.6
            notes.append("主线期加权：龙回头叠加低吸上拉")
        if is_low_suction_launch and not is_dragon_overlap:
            adjustment += 0.6
            notes.append("主线期保留：低吸上拉作为背景确认")
        if is_plain_dragon and tail_repeat >= 3:
            adjustment -= 1.1
            notes.append("主线期降权：龙回头重复过久")
        if has_high_level_risk and not has_mainline_alignment:
            adjustment -= 1.2
            notes.append("主线期降权：缺少主线对齐且风险偏高")
    else:
        recommended_style = "低吸首个有效上拉 / 龙回头叠加"
        if is_low_suction_launch and is_balanced_launch and has_start_signal:
            adjustment += 2.0
            notes.append("震荡期优先：低吸蓄势后首个有效上拉")
        elif is_low_suction_launch and is_balanced_launch:
            adjustment += 1.2
            notes.append("震荡期加权：低吸上拉质量较稳")
        if is_dragon_overlap and launch_confirmed:
            adjustment += 1.0
            notes.append("震荡期加权：龙回头叠加低吸上拉")
        if is_low_suction and not launch_confirmed:
            adjustment -= 1.4
            notes.append("震荡期降权：低吸蓄势未启动")
        if is_plain_dragon and tail_repeat >= 3:
            adjustment -= 1.2
            notes.append("震荡期降权：普通龙回头重复过久")
        if has_high_level_risk:
            adjustment -= 1.0
            notes.append("震荡期降权：存在高位/破位/滞涨风险")

    return {
        "adjustment": max(min(adjustment, 4.0), -4.0),
        "profile": profile,
        "recommended_style": recommended_style,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _market_adaptive_profile(
    *,
    regime: str,
    warning_level: float,
    recovery_level: float,
    breadth: float | None,
) -> str:
    if regime in {"crash", "weak_defensive", "risk_off"} or (warning_level >= 3 and recovery_level <= 1):
        return "weak_defensive"
    if regime in {"strong_broad", "narrow_theme_bull", "mainline_pullback", "narrow_mainline_bull"}:
        return "mainline_active"
    if warning_level <= 1 and breadth is not None and breadth >= 58:
        return "mainline_active"
    return "choppy_rotation"


def _low_suction_market_risk_score(evidence: dict[str, Any]) -> float:
    recovery_state = str(evidence.get("recovery_state") or "")
    regime = str(evidence.get("dynamic_market_regime") or "")
    breadth = _float_or_none(evidence.get("market_breadth_score"))
    warning_level = _float_or_none(evidence.get("market_warning_level"))
    risk = 0.0

    if recovery_state == "none":
        risk += 1.5
    elif recovery_state == "stabilizing":
        risk += 0.4

    if regime in {"crash", "weak_defensive"}:
        risk += 1.5
    elif regime == "false_bull":
        risk += 1.0

    if breadth is not None:
        if breadth < 35:
            risk += 1.4
        elif breadth < 42:
            risk += 0.8

    if warning_level is not None:
        if warning_level >= 3:
            risk += 1.2
        elif warning_level >= 2:
            risk += 0.6

    return min(risk, 3.0)


def _low_suction_launch_risk_score(evidence: dict[str, Any]) -> float:
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    pullback_days = _float_or_none(evidence.get("pullback_days"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days"))
    risk = 0.0

    if volume_ratio is not None and volume_ratio < 0.7:
        risk += 1.2
    if close_location is not None and close_location >= 0.70:
        risk += 0.8
    if pullback_days is not None and pullback_days >= 12:
        risk += 0.8
    if low_suction_days is not None and low_suction_days >= 6 and close_location is not None and close_location < 0.58:
        risk += 0.8

    return min(risk, 2.0)


def entry_launch_quality_notes(evidence: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    adjustment = entry_launch_quality_adjustment(evidence)
    if adjustment > 0:
        notes.append("启动质量加分：中上收盘/温和量能/回踩不过晚")
    elif adjustment < 0:
        notes.append("启动质量扣分：过晚回踩/缩量无承接/位置不佳")
    return notes


def entry_launch_risk_penalty_notes(evidence: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if entry_launch_risk_penalty_adjustment(evidence) < 0:
        notes.append("启动风险扣分：过晚回踩/死量/低吸久但收盘弱")
    return notes


def low_suction_market_risk_penalty_notes(evidence: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if low_suction_market_risk_penalty_adjustment(evidence) < 0:
        notes.append("低吸市场风险扣分：大盘未回暖且个股启动质量偏弱")
    return notes


def low_suction_first_lift_bonus_notes(evidence: dict[str, Any]) -> list[str]:
    if low_suction_first_lift_bonus_adjustment(evidence) <= 0:
        return []
    return ["低吸首启加分：蓄势后出现温和上拉，量价和均线距离不过激"]


def classify_low_suction_false_launch_watch(
    *,
    low_suction_days: float | int | None,
    launch_quality_bucket: str | None,
    close_location_in_range: float | None,
    volume_ratio_5d_20d: float | None,
    market_warning_level: float | int | None,
    market_recovery_level: float | int | None,
    recent_limit_up_20d: bool,
    theme_alignment: str | None,
    min_low_suction_days: int = 3,
    min_warning_level: int = 2,
    max_recovery_level: int = 1,
) -> dict[str, Any]:
    """Classify weak low-suction lifts that should stay WATCH in experiments."""

    days = float(low_suction_days or 0)
    warning = float(market_warning_level or 0)
    recovery = float(market_recovery_level or 0)
    bucket = str(launch_quality_bucket or "")
    alignment = str(theme_alignment or "unknown")
    weak_launch_buckets = {
        "unconfirmed_buildup",
        "weak_volume_launch",
        "late_pullback_launch",
        "repeated_launch",
    }
    weak_close = close_location_in_range is not None and close_location_in_range < 0.58
    weak_volume = volume_ratio_5d_20d is not None and volume_ratio_5d_20d < 0.85
    weak_visible_lift = bucket in weak_launch_buckets or weak_close or weak_volume
    protected_strength = recent_limit_up_20d or alignment in {"aligned", "strong", "mainline_aligned"}

    watch_only = bool(
        days >= min_low_suction_days
        and weak_visible_lift
        and warning >= min_warning_level
        and recovery <= max_recovery_level
        and not protected_strength
    )
    notes: list[str] = []
    if watch_only:
        notes.append("低吸蓄势后上拉偏弱，且大盘未回暖，实验口径降为观察")
    return {
        "watch_only": watch_only,
        "reason": "low_suction_false_launch_watch" if watch_only else None,
        "not_used_for_signal_score": True,
        "notes": notes,
    }


def _market_recovery_level(evidence: dict[str, Any]) -> float:
    direct = _float_or_none(evidence.get("market_recovery_level"))
    if direct is not None:
        return direct
    state = str(evidence.get("recovery_state") or "")
    mapping = {
        "none": 0.0,
        "stabilizing": 1.0,
        "warming": 2.0,
        "warming_confirmed": 3.0,
        "confirmed": 3.0,
        "strong": 4.0,
    }
    return mapping.get(state, 0.0)


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
