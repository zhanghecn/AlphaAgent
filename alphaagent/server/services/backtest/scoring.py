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


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
