"""Scoring helpers for portfolio backtests."""

from __future__ import annotations

from copy import copy
from datetime import date
from typing import Any, Callable

from alphaagent.server.services.backtest.schemas import BacktestParams, ScoreContext
from alphaagent.server.services.backtest.queries import market_phase_setup_family
from alphaagent.server.services.quant import market_context
from alphaagent.server.services.quant import retreat_momentum_source
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

    visible_bars = bars_with_signal_date(bars_by_symbol, trade_date)
    if score_cache is not None and trade_date in score_cache:
        scores = score_cache[trade_date]
    else:
        scorer = score_candidates_for_day or globals()["score_candidates_for_day"]
        scores = scorer(session, visible_bars, trade_date, params, score_context)
        if score_cache is not None:
            score_cache[trade_date] = scores
    if params.strategy == "mainline_dragon_pullback":
        scores = retreat_momentum_source.append_board_survival_pressure_sources(
            scores,
            visible_bars=visible_bars,
            session=session,
        )
    candidates = [score for score in scores if is_buy_candidate(score, params)]
    candidates = [_with_strategy_family_fields(score) for score in candidates]
    candidates = [score for score in candidates if _passes_setup_family_filter(score, params)]
    candidates = [
        adjusted
        for score in candidates
        if (adjusted := _with_phase_aware_setup_selector(score, params)) is not None
    ]
    candidates = [_with_entry_launch_quality_score(score, params) for score in candidates]
    candidates = [_with_entry_launch_risk_penalty(score, params) for score in candidates]
    candidates = [_with_low_suction_market_risk_penalty(score, params) for score in candidates]
    candidates = [_with_market_adaptive_setup_weighting(score, params) for score in candidates]
    candidates = [_with_low_suction_first_lift_bonus(score, params) for score in candidates]
    candidates = [_with_low_suction_lifecycle_ranking(score, params) for score in candidates]
    candidates = [_with_low_suction_buildup_quality_lane(score, params) for score in candidates]
    candidates = [_with_candidate_tail_risk_penalty(score, params) for score in candidates]
    candidates = [_with_mainline_momentum_lane(score, params) for score in candidates]
    candidates = [_with_mainline_momentum_risk_control(score, params) for score in candidates]
    candidates = [_with_surge_quality_lane(score, params) for score in candidates]
    candidates = _with_top20_day_quality_gate(candidates, params)
    candidates = [_with_weekly_top_fractal_relief(score, params) for score in candidates]
    candidates = [_with_pure_loss_weak_bucket_penalty(score, params) for score in candidates]
    candidates = [_with_selective_setup_quality_lane(score, params) for score in candidates]
    candidates = [_with_default_clean_watch_entry_fields(score, params) for score in candidates]
    candidates = [_with_support_divergence_entry_fields(score, params) for score in candidates]
    candidates = [_with_strong_trend_ma_pullback_entry_fields(score, params) for score in candidates]
    candidates = [_with_default_candidate_quality_score(score, params) for score in candidates]
    candidates.sort(key=lambda item: (-item.total_score, item.vt_symbol))
    return candidates


def _with_strategy_family_fields(score):
    evidence = getattr(score, "evidence", {}) or {}
    family = market_phase_setup_family(evidence)
    if evidence.get("setup_family") == family:
        return score
    adjusted = copy(score)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["setup_family"] = family
    adjusted.evidence["setup_family_source"] = "phase_strategy_family"
    return adjusted


def _passes_setup_family_filter(score, params: BacktestParams) -> bool:
    requested = str(params.setup_family_filter or "").strip()
    if not requested:
        return True
    allowed = {item.strip() for item in requested.split(",") if item.strip()}
    if not allowed:
        return True
    family = str((getattr(score, "evidence", {}) or {}).get("setup_family") or "")
    return family in allowed


def _with_phase_aware_setup_selector(score, params: BacktestParams):
    if not params.enable_phase_aware_setup_selector:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = phase_aware_setup_selector_decision(evidence)
    if not decision["allowed"]:
        return None
    if decision["score_adjustment"] == 0 and not decision["notes"]:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + float(decision["score_adjustment"]), 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["phase_aware_setup_selector"] = decision
    adjusted.evidence["phase_aware_setup_score"] = adjusted.total_score
    return adjusted


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
    default_clean_watch_entry = _default_clean_watch_entry_decision(score, params)
    support_divergence_entry = _support_divergence_entry_decision(score, params)
    strong_trend_ma_pullback_entry = _strong_trend_ma_pullback_entry_decision(score, params)
    if score.risk_score < 35:
        return False
    if score.liquidity_score < 25 and not (
        default_clean_watch_entry["eligible"] or support_divergence_entry["eligible"]
    ):
        return False
    if params.strict_entry:
        return (
            (
                _is_executable_entry_signal_for_params(score, params)
                or _is_mainline_momentum_entry_signal(score, params)
                or default_clean_watch_entry["eligible"]
                or support_divergence_entry["eligible"]
                or strong_trend_ma_pullback_entry["eligible"]
            )
            and _passes_backtest_entry_experiments(score, params)
        )
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
    if params.enable_candidate_tail_risk_penalty and _is_candidate_tail_risk_blocked(evidence):
        return False
    if params.enable_mainline_momentum_hard_filter and _mainline_momentum_hard_filter_reason(evidence):
        return False
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


def _with_low_suction_lifecycle_ranking(score, params: BacktestParams):
    if not params.enable_low_suction_lifecycle_ranking:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = low_suction_lifecycle_ranking_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["low_suction_lifecycle_adjustment"] = round(adjustment, 4)
    adjusted.evidence["low_suction_lifecycle_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["low_suction_lifecycle_profile"] = decision["profile"]
    adjusted.evidence["low_suction_lifecycle_notes"] = decision["notes"]
    return adjusted


def _with_low_suction_buildup_quality_lane(score, params: BacktestParams):
    if not params.enable_low_suction_buildup_quality_lane:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = low_suction_buildup_quality_lane_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["low_suction_buildup_quality_adjustment"] = round(adjustment, 4)
    adjusted.evidence["low_suction_buildup_quality_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["low_suction_buildup_quality_profile"] = decision["profile"]
    adjusted.evidence["low_suction_buildup_quality_notes"] = decision["notes"]
    return adjusted


def _with_candidate_tail_risk_penalty(score, params: BacktestParams):
    if not params.enable_candidate_tail_risk_penalty:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = candidate_tail_risk_penalty_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["candidate_tail_risk_adjustment"] = round(adjustment, 4)
    adjusted.evidence["candidate_tail_risk_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["candidate_tail_risk_profile"] = decision["profile"]
    adjusted.evidence["candidate_tail_risk_notes"] = decision["notes"]
    return adjusted


def _with_mainline_momentum_lane(score, params: BacktestParams):
    if not params.enable_mainline_momentum_lane:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = mainline_momentum_lane_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["mainline_momentum_lane_adjustment"] = round(adjustment, 4)
    adjusted.evidence["mainline_momentum_lane_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["mainline_momentum_lane_profile"] = decision["profile"]
    adjusted.evidence["mainline_momentum_lane_notes"] = decision["notes"]
    return adjusted


def _with_mainline_momentum_risk_control(score, params: BacktestParams):
    if not params.enable_mainline_momentum_risk_control:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = mainline_momentum_risk_control_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["mainline_momentum_risk_control_adjustment"] = round(adjustment, 4)
    adjusted.evidence["mainline_momentum_risk_control_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["mainline_momentum_risk_control_profile"] = decision["profile"]
    adjusted.evidence["mainline_momentum_risk_control_notes"] = decision["notes"]
    return adjusted


def _with_surge_quality_lane(score, params: BacktestParams):
    if not params.enable_surge_quality_lane:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = surge_quality_lane_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["surge_quality_lane_adjustment"] = round(adjustment, 4)
    adjusted.evidence["surge_quality_lane_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["surge_quality_lane_profile"] = decision["profile"]
    adjusted.evidence["surge_quality_lane_notes"] = decision["notes"]
    return adjusted


def _with_top20_day_quality_gate(candidates: list[Any], params: BacktestParams) -> list[Any]:
    if not params.enable_top20_day_quality_gate or len(candidates) < 10:
        return candidates
    preselected = sorted(candidates, key=lambda item: (-item.total_score, item.vt_symbol))[:20]
    day_profile = top20_day_quality_profile(preselected)
    if day_profile["profile"] == "neutral_top20_day":
        return candidates
    return [_with_top20_day_quality_score(score, params, day_profile) for score in candidates]


def _with_top20_day_quality_score(score, params: BacktestParams, day_profile: dict[str, Any]):
    decision = top20_day_quality_adjustment(getattr(score, "evidence", {}) or {}, day_profile)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(getattr(score, "evidence", {}) or {})
    adjusted.evidence["top20_day_quality_adjustment"] = round(adjustment, 4)
    adjusted.evidence["top20_day_quality_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["top20_day_quality_profile"] = decision["profile"]
    adjusted.evidence["top20_day_quality_day_profile"] = day_profile
    adjusted.evidence["top20_day_quality_notes"] = decision["notes"]
    return adjusted


def _with_weekly_top_fractal_relief(score, params: BacktestParams):
    if not params.enable_weekly_top_fractal_relief:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = weekly_top_fractal_relief_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["weekly_top_fractal_relief_adjustment"] = round(adjustment, 4)
    adjusted.evidence["weekly_top_fractal_relief_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["weekly_top_fractal_relief_profile"] = decision["profile"]
    adjusted.evidence["weekly_top_fractal_relief_notes"] = decision["notes"]
    return adjusted


def _with_pure_loss_weak_bucket_penalty(score, params: BacktestParams):
    if not params.enable_pure_loss_weak_bucket_penalty:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = pure_loss_weak_bucket_penalty(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["pure_loss_weak_bucket_adjustment"] = round(adjustment, 4)
    adjusted.evidence["pure_loss_weak_bucket_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["pure_loss_weak_bucket_profile"] = decision["profile"]
    adjusted.evidence["pure_loss_weak_bucket_notes"] = decision["notes"]
    return adjusted


def _with_selective_setup_quality_lane(score, params: BacktestParams):
    if not params.enable_selective_setup_quality_lane:
        return score
    evidence = getattr(score, "evidence", {}) or {}
    decision = selective_setup_quality_lane_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["selective_setup_quality_adjustment"] = round(adjustment, 4)
    adjusted.evidence["selective_setup_quality_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["selective_setup_quality_profile"] = decision["profile"]
    adjusted.evidence["selective_setup_quality_notes"] = decision["notes"]
    return adjusted


def _with_default_candidate_quality_score(score, params: BacktestParams):
    """Apply the default candidate-layer quality adjustment before final rank."""

    if params.strategy != "mainline_dragon_pullback":
        return score
    evidence = getattr(score, "evidence", {}) or {}
    if evidence.get("retreat_momentum_board_survival_source"):
        return score
    decision = default_candidate_quality_adjustment(evidence)
    adjustment = float(decision["adjustment"])
    if adjustment == 0:
        return score
    adjusted = copy(score)
    adjusted.total_score = round(float(getattr(score, "total_score", 0) or 0) + adjustment, 4)
    adjusted.evidence = dict(evidence)
    adjusted.evidence["candidate_quality_adjustment"] = round(adjustment, 4)
    adjusted.evidence["candidate_quality_score"] = round(adjusted.total_score, 4)
    adjusted.evidence["candidate_quality_base_score"] = round(float(getattr(score, "total_score", 0) or 0), 4)
    adjusted.evidence["candidate_quality_profile"] = decision["profile"]
    adjusted.evidence["candidate_quality_notes"] = decision["notes"]
    adjusted.evidence["total_score"] = adjusted.total_score
    return adjusted


def _with_default_clean_watch_entry_fields(score, params: BacktestParams):
    decision = _default_clean_watch_entry_decision(score, params)
    if not decision["eligible"]:
        return score
    evidence = dict(getattr(score, "evidence", {}) or {})
    if evidence.get("default_clean_watch_entry_profile") == decision["profile"]:
        return score
    evidence["default_clean_watch_entry_profile"] = decision["profile"]
    evidence["default_clean_watch_entry_notes"] = decision["notes"]
    evidence["default_clean_watch_entry_signal"] = True
    evidence["default_executable_entry_signal"] = True
    evidence["raw_entry_signal"] = bool(getattr(score, "entry_signal", False))
    evidence["executable_entry_signal"] = True
    evidence["key_entry_signal"] = True
    evidence["action"] = "BUY"
    evidence["entry_action"] = "BUY"
    evidence["signal_label"] = _default_clean_watch_entry_label(decision["profile"])
    evidence["signal_role"] = "key_buy"
    adjusted = copy(score)
    adjusted.evidence = evidence
    return adjusted


def _default_clean_watch_entry_decision(score, params: BacktestParams) -> dict[str, Any]:
    if params.strategy != "mainline_dragon_pullback":
        return _default_clean_watch_decision(False, "not_dragon_pullback", [])
    if bool(getattr(score, "entry_signal", False)):
        return _default_clean_watch_decision(False, "raw_entry_signal", [])
    evidence = getattr(score, "evidence", {}) or {}
    if evidence.get("status") != "ready":
        return _default_clean_watch_decision(False, "not_ready", [])
    if float(getattr(score, "risk_score", 0) or 0) < 35:
        return _default_clean_watch_decision(False, "risk_score_too_low", [])
    if evidence.get("key_support_break_risk"):
        return _default_clean_watch_decision(False, "key_support_break_risk", [])
    if evidence.get("distribution_risk") or evidence.get("high_level_sideways_distribution_risk"):
        return _default_clean_watch_decision(False, "distribution_risk", [])

    failed_rules = set(_failed_rule_names(evidence))
    if failed_rules & {"distribution_risk", "ma20_broken", "pullback_too_deep"}:
        return _default_clean_watch_decision(False, "hard_failed_rule", [])

    score_value = float(getattr(score, "total_score", 0) or 0)
    liquidity = float(getattr(score, "liquidity_score", evidence.get("liquidity_score") or 0) or 0)
    low_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    near_limit_count = _float_or_none(evidence.get("near_limit_up_count_20d")) or 0.0
    recent_limit = bool(evidence.get("recent_limit_up_20d")) or near_limit_count > 0
    active_source = recent_limit or large_bull_count >= 1.0
    fresh_lift = bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed"))

    if _default_clean_watch_hot_unconfirmed_after_big_run(
        active_source=active_source,
        recent_limit=recent_limit,
        low_days=low_days,
        fresh_lift=fresh_lift,
        return_60d=return_60d,
    ):
        return _default_clean_watch_decision(False, "hot_unconfirmed_after_big_run", [])

    low_liquidity = liquidity < 25.0
    if low_liquidity:
        if not _default_clean_watch_common_quality(
            ma5_distance=ma5_distance,
            ma10_distance=ma10_distance,
            close_location=close_location,
            volume_ratio=volume_ratio,
            max_close_location=0.82,
        ):
            return _default_clean_watch_decision(False, "not_clean_low_liquidity_ma_support", [])
        return _default_low_liquidity_watch_entry_decision(
            score_value=score_value,
            low_days=low_days,
            fresh_lift=fresh_lift,
            ma_convergence=ma_convergence,
            ma5_slope=ma5_slope,
            close_location=close_location,
            failed_rules=failed_rules,
        )

    if liquidity < 40.0:
        return _default_clean_watch_decision(False, "liquidity_middle_gap", [])
    if not _default_clean_watch_common_quality(
        ma5_distance=ma5_distance,
        ma10_distance=ma10_distance,
        close_location=close_location,
        volume_ratio=volume_ratio,
        max_close_location=0.72,
    ):
        return _default_clean_watch_decision(False, "not_clean_ma_support", [])
    return _default_active_support_watch_entry_decision(
        evidence,
        score_value=score_value,
        active_source=active_source,
        low_days=low_days,
        ma_convergence=ma_convergence,
        latest_change=latest_change,
        close_location=close_location,
        failed_rules=failed_rules,
    )


def _default_clean_watch_common_quality(
    *,
    ma5_distance: float | None,
    ma10_distance: float | None,
    close_location: float | None,
    volume_ratio: float | None,
    max_close_location: float,
) -> bool:
    return bool(
        ma5_distance is not None
        and -2.8 <= ma5_distance <= 3.2
        and ma10_distance is not None
        and -3.2 <= ma10_distance <= 5.5
        and close_location is not None
        and close_location <= max_close_location
        and volume_ratio is not None
        and 0.55 <= volume_ratio <= 1.45
    )


def _default_low_liquidity_watch_entry_decision(
    *,
    score_value: float,
    low_days: float,
    fresh_lift: bool,
    ma_convergence: float | None,
    ma5_slope: float | None,
    close_location: float | None,
    failed_rules: set[str],
) -> dict[str, Any]:
    allowed_failed = {"strong_leg", "liquidity_score", "pullback_too_short", "reclaim_confirmation"}
    if failed_rules and not failed_rules <= allowed_failed:
        return _default_clean_watch_decision(False, "low_liquidity_failed_rule_quality", [])
    if score_value < 58.0 or low_days < 1:
        return _default_clean_watch_decision(False, "low_liquidity_score_or_days", [])
    if ma_convergence is None or ma_convergence > 7.0:
        return _default_clean_watch_decision(False, "low_liquidity_ma_convergence", [])
    if ma5_slope is not None and ma5_slope < -0.95:
        return _default_clean_watch_decision(False, "low_liquidity_ma5_slope", [])
    if close_location is None or close_location > 0.82:
        return _default_clean_watch_decision(False, "low_liquidity_close_location", [])
    if low_days >= 3 and fresh_lift:
        return _default_clean_watch_decision(
            True,
            "clean_low_liquidity_first_lift",
            ["低流动性但 MA5/MA10 承接干净，低吸蓄势后出现首个上拉"],
        )
    return _default_clean_watch_decision(
        True,
        "clean_low_liquidity_accumulation",
        ["低流动性但 MA5/MA10 连续承接，主要被流动性硬门槛挡住"],
    )


def _default_active_support_watch_entry_decision(
    _evidence: dict[str, Any],
    *,
    score_value: float,
    active_source: bool,
    low_days: float,
    ma_convergence: float | None,
    latest_change: float | None,
    close_location: float | None,
    failed_rules: set[str],
) -> dict[str, Any]:
    _ = (score_value, active_source, low_days, ma_convergence, latest_change, close_location, failed_rules)
    return _default_clean_watch_decision(False, "active_support_research_only", [])


def _default_active_support_segment(evidence: dict[str, Any]) -> bool:
    support_type = str(evidence.get("support_type") or "")
    state = str(evidence.get("dragon_state") or "")
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    strong_leg = _float_or_none(evidence.get("strong_leg_score")) or 0.0
    pullback_days = _float_or_none(evidence.get("pullback_days")) or 0.0
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    return bool(
        setup in {"support_accepted", "pullback_observe", "dragon_pullback"}
        and state in {"SUPPORT_ACCEPTED", "PULLBACK_OBSERVE", "TAIL_BUY_READY", ""}
        and strong_leg >= 78.0
        and pullback_days >= 2
        and support_type in {"ma5_reclaim", "ma5_support", "ma10_support", "ma10_reclaim"}
        and ma5_distance is not None
        and -2.8 <= ma5_distance <= 3.2
        and ma10_distance is not None
        and -3.2 <= ma10_distance <= 5.5
        and close_location is not None
        and close_location <= 0.72
        and volume_ratio is not None
        and 0.55 <= volume_ratio <= 1.45
    )


def _default_active_support_wide_ma_quality_ok(
    *,
    ma_convergence: float | None,
    low_days: float,
    latest_change: float | None,
    close_location: float | None,
    evidence: dict[str, Any],
) -> bool:
    if ma_convergence is None:
        return False
    if ma_convergence < 14.0 or low_days >= 3:
        return True
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    return bool(
        close_location is not None
        and close_location <= 0.58
        or latest_change is not None
        and latest_change <= -4.0
        or ma10_distance is not None
        and ma10_distance <= 0.0
    )


def _default_clean_watch_hot_unconfirmed_after_big_run(
    *,
    active_source: bool,
    recent_limit: bool,
    low_days: float,
    fresh_lift: bool,
    return_60d: float | None,
) -> bool:
    return bool(
        active_source
        and recent_limit
        and low_days >= 4
        and not fresh_lift
        and return_60d is not None
        and return_60d >= 55.0
    )


def _default_clean_watch_entry_label(profile: str) -> str:
    if profile == "clean_active_support_divergence":
        return "支撑分歧低吸买点"
    if profile == "clean_low_liquidity_first_lift":
        return "低流动性低吸首启买点"
    if profile == "clean_low_liquidity_accumulation":
        return "低流动性承接低吸买点"
    return "低吸承接买点"


def _default_clean_watch_decision(eligible: bool, profile: str, notes: list[str]) -> dict[str, Any]:
    return {"eligible": eligible, "profile": profile, "notes": notes}


def _support_divergence_entry_decision(score, params: BacktestParams) -> dict[str, Any]:
    if not params.enable_support_divergence_entry_lane:
        return {"eligible": False, "profile": "disabled", "notes": []}
    evidence = getattr(score, "evidence", {}) or {}
    decision = support_divergence_entry_lane_decision(score, evidence, params)
    if not decision["eligible"]:
        return decision
    if evidence.get("support_divergence_entry_profile") == decision["profile"]:
        return decision
    adjusted_evidence = dict(evidence)
    adjusted_evidence["support_divergence_entry_profile"] = decision["profile"]
    adjusted_evidence["support_divergence_entry_notes"] = decision["notes"]
    adjusted_evidence["support_divergence_entry_signal"] = True
    score.evidence = adjusted_evidence
    return decision


def _with_support_divergence_entry_fields(score, params: BacktestParams):
    decision = _support_divergence_entry_decision(score, params)
    if not decision["eligible"]:
        return score
    return _with_research_entry_fields(
        score,
        params,
        label="支撑分歧低吸买点",
        observation_key="support_divergence_entry_observation_only",
    )


def _with_strong_trend_ma_pullback_entry_fields(score, params: BacktestParams):
    decision = _strong_trend_ma_pullback_entry_decision(score, params)
    if not decision["eligible"]:
        return score
    evidence = dict(getattr(score, "evidence", {}) or {})
    if evidence.get("strong_trend_ma_pullback_entry_profile") != decision["profile"]:
        evidence["strong_trend_ma_pullback_entry_profile"] = decision["profile"]
        evidence["strong_trend_ma_pullback_entry_notes"] = decision["notes"]
        evidence["strong_trend_ma_pullback_entry_signal"] = True
    adjusted = copy(score)
    adjusted.evidence = evidence
    return _with_research_entry_fields(
        adjusted,
        params,
        label="强趋势均线回踩研究买点",
        observation_key="strong_trend_ma_pullback_entry_observation_only",
    )


def _with_research_entry_fields(score, params: BacktestParams, *, label: str, observation_key: str):
    evidence = dict(getattr(score, "evidence", {}) or {})
    default_buy_signal = _is_default_buy_candidate_without_research_entry(score, params)
    existing_research_label = str(evidence.get("signal_label") or "") if _has_research_entry_observation(evidence) else ""
    evidence["action"] = "BUY"
    evidence["entry_action"] = "BUY"
    evidence["executable_entry_signal"] = True
    evidence["key_entry_signal"] = True
    evidence["default_executable_entry_signal"] = default_buy_signal
    evidence["raw_entry_signal"] = bool(getattr(score, "entry_signal", False))
    evidence["signal_label"] = existing_research_label or label
    evidence["signal_role"] = "key_buy"
    evidence[observation_key] = not default_buy_signal
    adjusted = copy(score)
    adjusted.evidence = evidence
    return adjusted


def _has_research_entry_observation(evidence: dict[str, Any]) -> bool:
    return bool(
        evidence.get("support_divergence_entry_observation_only")
        or evidence.get("strong_trend_ma_pullback_entry_observation_only")
    )


def _is_buy_candidate_without_support_divergence_entry(score, params: BacktestParams) -> bool:
    return _is_default_buy_candidate_without_research_entry(score, params)


def _is_default_buy_candidate_without_research_entry(score, params: BacktestParams) -> bool:
    evidence = getattr(score, "evidence", {}) or {}
    if evidence.get("status") != "ready":
        return False
    if score.risk_score < 35:
        return False
    if _default_clean_watch_entry_decision(score, params)["eligible"]:
        return True
    if score.liquidity_score < 25:
        return False
    if params.strict_entry:
        return (
            (
                _is_executable_entry_signal_for_params(score, params)
                or _is_mainline_momentum_entry_signal(score, params)
            )
            and _passes_backtest_entry_experiments(score, params)
        )
    if score.total_score < screening_payloads.effective_entry_score_threshold(score, params.min_entry_score):
        return False
    return _passes_backtest_entry_experiments(score, params)


def _strong_trend_ma_pullback_entry_decision(score, params: BacktestParams) -> dict[str, Any]:
    if not params.enable_strong_trend_ma_pullback_entry_lane:
        return _strong_trend_ma_pullback_decision(False, "disabled", [])
    evidence = getattr(score, "evidence", {}) or {}
    total_score = float(getattr(score, "total_score", 0) or 0)
    risk_score = float(getattr(score, "risk_score", 0) or 0)
    liquidity_score = float(getattr(score, "liquidity_score", evidence.get("liquidity_score") or 0) or 0)
    failed_rules = set(_failed_rule_names(evidence))
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    state = str(evidence.get("dragon_state") or "")
    support_type = str(evidence.get("support_type") or "")
    strong_leg = _float_or_none(evidence.get("strong_leg_score")) or 0.0
    pullback_days = _float_or_none(evidence.get("pullback_days")) or 0.0
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    ma5_vs_ma10 = _float_or_none(evidence.get("ma5_vs_ma10_pct"))
    return_20d = _float_or_none(evidence.get("return_20d"))
    return_60d = _float_or_none(evidence.get("return_60d"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    market_regime = str(evidence.get("dynamic_market_regime") or "")
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    active_strength = _mainline_momentum_strength(evidence)

    if risk_score < 35 or liquidity_score < 25:
        return _strong_trend_ma_pullback_decision(False, "below_risk_or_liquidity", [])
    if evidence.get("key_support_break_risk") or evidence.get("volume_stall_risk"):
        return _strong_trend_ma_pullback_decision(False, "hard_risk", [])
    if "distribution_risk" in failed_rules or evidence.get("distribution_risk"):
        return _strong_trend_ma_pullback_decision(False, "distribution_risk", [])
    if risk_penalty >= 20:
        return _strong_trend_ma_pullback_decision(False, "risk_penalty_too_high", [])
    if total_score < 76 or strong_leg < 90:
        return _strong_trend_ma_pullback_decision(False, "below_threshold", [])
    if market_regime in {"crash", "weak_defensive"} or warning_level >= 4:
        return _strong_trend_ma_pullback_decision(False, "market_risk", [])
    if return_20d is not None and return_20d < 25 and active_strength < 3.0:
        return _strong_trend_ma_pullback_decision(False, "trend_not_strong", [])

    allowed_rules = {
        "pullback_too_short",
        "ma_convergence_too_wide_without_low_suction",
        "reclaim_confirmation",
        "support_acceptance",
    }
    if failed_rules and not failed_rules <= allowed_rules:
        return _strong_trend_ma_pullback_decision(False, "failed_rule_quality", [])

    intraday_ma_pullback = (
        setup in {"pullback_observe", "support_accepted"}
        and state in {"PULLBACK_OBSERVE", "SUPPORT_ACCEPTED"}
        and support_type in {"none", "ma5_reclaim", "ma10_support"}
        and 1 <= pullback_days <= 3
        and active_strength >= 2.0
        and latest_change is not None
        and -2.8 <= latest_change <= 2.8
        and close_location is not None
        and 0.55 <= close_location <= 0.88
        and volume_ratio is not None
        and 0.75 <= volume_ratio <= 2.8
        and ma5_distance is not None
        and 3.0 <= ma5_distance <= 7.2
        and ma10_distance is not None
        and 6.0 <= ma10_distance <= 18.0
        and ma_convergence is not None
        and 14.0 <= ma_convergence <= 31.0
        and ma5_slope is not None
        and ma5_slope >= 1.0
        and (ma5_vs_ma10 is None or ma5_vs_ma10 >= 4.0)
        and (ma20_distance is None or ma20_distance >= 15.0)
        and not evidence.get("high_level_sideways_distribution_risk")
        and failed_rules <= {"pullback_too_short"}
    )
    if intraday_ma_pullback:
        return _strong_trend_ma_pullback_decision(
            True,
            "strong_trend_intraday_ma_pullback",
            ["强趋势中日内触及短均线后收回，当前规则主要因回踩天数过短未给正式买点"],
        )

    deep_ma10_dislocation = (
        setup in {"support_accepted", "pullback_observe"}
        and state in {"SUPPORT_ACCEPTED", "PULLBACK_OBSERVE"}
        and support_type in {"ma10_support", "ma5_reclaim"}
        and pullback_days >= 5
        and active_strength >= 3.0
        and total_score >= 88
        and ma5_distance is not None
        and ma5_distance >= -3.2
        and ma10_distance is not None
        and -2.8 <= ma10_distance <= 3.2
        and ma_convergence is not None
        and 18.0 <= ma_convergence <= 30.0
        and volume_ratio is not None
        and 0.65 <= volume_ratio <= 1.6
        and close_location is not None
        and close_location >= 0.45
        and (latest_change is None or latest_change >= -3.5)
        and failed_rules <= {"reclaim_confirmation", "ma_convergence_too_wide_without_low_suction"}
    )
    if deep_ma10_dislocation:
        return _strong_trend_ma_pullback_decision(
            True,
            "deep_trend_ma10_dislocation_observe",
            ["强趋势深分歧后仍在 MA10/MA5 承接区，作为高位回踩研究买点观察"],
        )

    return _strong_trend_ma_pullback_decision(False, "no_match", [])


def _strong_trend_ma_pullback_decision(eligible: bool, profile: str, notes: list[str]) -> dict[str, Any]:
    return {"eligible": eligible, "profile": profile, "notes": notes}


def support_divergence_entry_lane_decision(
    score,
    evidence: dict[str, Any],
    params: BacktestParams,
) -> dict[str, Any]:
    """Default-off entry lane for 003004-style support divergence research."""

    total_score = float(getattr(score, "total_score", 0) or 0)
    risk_score = float(getattr(score, "risk_score", 0) or 0)
    liquidity_score = float(getattr(score, "liquidity_score", 0) or 0)
    failed_rules = set(_failed_rule_names(evidence))
    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    state = str(evidence.get("dragon_state") or "")
    support_type = str(evidence.get("support_type") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    buildup_score = _float_or_none(evidence.get("low_suction_buildup_score")) or 0.0
    suction_score = _float_or_none(evidence.get("stealth_low_suction_score")) or 0.0
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    strong_leg = _float_or_none(evidence.get("strong_leg_score")) or 0.0
    pullback_days = _float_or_none(evidence.get("pullback_days")) or 0.0
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    market_warning = _float_or_none(evidence.get("market_warning_level")) or 0.0
    market_regime = str(evidence.get("dynamic_market_regime") or "")

    if total_score < max(params.min_entry_score, 72.0) or risk_score < 35:
        return _support_divergence_decision(False, "below_threshold", [])
    if evidence.get("key_support_break_risk") or evidence.get("volume_stall_risk"):
        return _support_divergence_decision(False, "hard_risk", [])

    low_liquidity_rules = {"strong_leg", "liquidity_score", "pullback_too_short"}
    mature_low_suction = (
        liquidity_score < 25
        and total_score >= 76
        and low_suction_days >= 3
        and (bool(evidence.get("low_suction_launch_confirmed")) or buildup_score >= 95 or suction_score >= 95)
        and ma_convergence is not None
        and ma_convergence <= 6.2
        and support_type != "none"
        and bool(failed_rules)
        and failed_rules <= low_liquidity_rules
    )
    if mature_low_suction:
        return _support_divergence_decision(
            True,
            "mature_low_suction_launch",
            ["成熟低吸蓄势/启动，主要被流动性或第一波强度硬门槛挡住"],
        )

    support_divergence_rules = {
        "reclaim_confirmation",
        "ma_convergence_too_wide_without_low_suction",
        "pullback_too_short",
    }
    high_level_support_divergence = (
        liquidity_score >= 40
        and total_score >= 89
        and strong_leg >= 90
        and pullback_days >= 3
        and ma_convergence is not None
        and ma_convergence <= 30
        and support_type in {"ma5_reclaim", "ma10_support"}
        and setup in {"support_accepted", "pullback_observe"}
        and state in {"SUPPORT_ACCEPTED", "PULLBACK_OBSERVE"}
        and bool(failed_rules)
        and failed_rules <= support_divergence_rules
        and (latest_change is None or latest_change <= 5.5)
        and _support_divergence_failed_rule_quality_ok(
            failed_rules=failed_rules,
            ma_convergence=ma_convergence,
            latest_change=latest_change,
            close_location=close_location,
            market_warning=market_warning,
            market_regime=market_regime,
            support_type=support_type,
        )
    )
    if high_level_support_divergence:
        return _support_divergence_decision(
            True,
            "high_level_support_divergence",
            ["高位分歧后 MA5/MA10 承接，主要缺弱转强确认或均线收敛"],
        )

    return _support_divergence_decision(False, "no_match", [])


def _support_divergence_decision(eligible: bool, profile: str, notes: list[str]) -> dict[str, Any]:
    return {"eligible": eligible, "profile": profile, "notes": notes}


def _support_divergence_failed_rule_quality_ok(
    *,
    failed_rules: set[str],
    ma_convergence: float | None,
    latest_change: float | None,
    close_location: float | None,
    market_warning: float,
    market_regime: str,
    support_type: str,
) -> bool:
    if "ma_convergence_too_wide_without_low_suction" in failed_rules:
        if ma_convergence is None or latest_change is None:
            return False
        if ma_convergence > 22.5:
            return False
        if latest_change < 2.0:
            return False
        if market_regime == "false_bull" and market_warning >= 2 and support_type != "ma10_support":
            return False
        if close_location is not None and close_location >= 0.90 and market_warning >= 2:
            return False
    if "reclaim_confirmation" in failed_rules:
        if latest_change is not None and latest_change <= -4.5:
            return False
        if close_location is not None and close_location < 0.18:
            return False
    return True


def _failed_rule_names(evidence: dict[str, Any]) -> list[str]:
    rules = evidence.get("failed_rules")
    if not isinstance(rules, list):
        return []
    return [str(rule) for rule in rules if str(rule)]


def default_candidate_quality_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Default no-future score adjustment for the public dragon-pullback rank."""

    clean_watch_profile = str(evidence.get("default_clean_watch_entry_profile") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    ma5_slope = _float_or_none(evidence.get("ma5_slope_pct"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    near_limit_up_count = _float_or_none(evidence.get("near_limit_up_count_20d")) or 0.0
    pullback_days = _float_or_none(evidence.get("pullback_days")) or 0.0
    launch_bucket = str(evidence.get("low_suction_launch_quality_bucket") or "")

    fresh_lift = bool(evidence.get("first_effective_lift") or evidence.get("low_suction_launch_confirmed"))
    recent_limit_source = bool(evidence.get("recent_limit_up_20d")) or near_limit_up_count > 0
    stale_active_weak_decay_pullback = _default_candidate_stale_active_weak_decay_pullback(
        low_suction_days=low_suction_days,
        fresh_lift=fresh_lift,
        recent_limit_source=recent_limit_source,
        close_location=close_location,
        volume_ratio=volume_ratio,
        pullback_days=pullback_days,
        strong_leg=_float_or_none(evidence.get("strong_leg_score")) or 0.0,
    )
    mature_low_suction_lift = _default_candidate_mature_low_suction_lift(
        low_suction_days=low_suction_days,
        fresh_lift=fresh_lift,
        ma5_distance=ma5_distance,
        ma10_distance=ma10_distance,
        ma_convergence=ma_convergence,
        volume_ratio=volume_ratio,
    )
    active_right_tail_source = _default_candidate_active_right_tail_source(
        evidence,
        large_bull_count=large_bull_count,
        ma5_distance=ma5_distance,
        warning_level=warning_level,
        ma5_slope=ma5_slope,
        latest_change=latest_change,
    )

    adjustment = 0.0
    notes: list[str] = []
    if clean_watch_profile == "clean_active_support_divergence":
        adjustment += 2.0
        notes.append("干净支撑分歧低吸默认买点加分")
    elif clean_watch_profile == "clean_low_liquidity_first_lift":
        adjustment += 2.6
        notes.append("低流动性承接首启默认买点加分")
    elif clean_watch_profile == "clean_low_liquidity_accumulation":
        adjustment += 2.2
        notes.append("低流动性连续承接默认买点加分")

    if mature_low_suction_lift:
        adjustment += 1.4
        notes.append("成熟低吸首启加分")
    if active_right_tail_source:
        adjustment += 0.8
        notes.append("近期活跃右尾来源加分")

    if ma5_distance is not None and ma5_distance >= 6.0 and not active_right_tail_source:
        adjustment -= 2.4
        notes.append("偏离5日线过远降权")
    if (
        bool(evidence.get("volume_stall_risk") or evidence.get("high_position_volume_stall_risk"))
        and not mature_low_suction_lift
        and not active_right_tail_source
    ):
        adjustment -= 2.0
        notes.append("放量滞涨降权")
    if low_suction_days >= 3 and not fresh_lift and not active_right_tail_source:
        adjustment -= 1.2
        notes.append("低吸蓄势无首启降权")
    if (
        large_bull_count >= 3
        and not bool(evidence.get("recent_limit_up_20d"))
        and not mature_low_suction_lift
        and close_location is not None
        and close_location > 0.58
    ):
        adjustment -= 1.0
        notes.append("多次大阳但无涨停且收盘偏拥挤降权")
    if (
        warning_level >= 3
        and (ma5_slope is None or ma5_slope < 0.10)
        and close_location is not None
        and close_location > 0.58
        and not mature_low_suction_lift
        and not active_right_tail_source
    ):
        adjustment -= 1.1
        notes.append("弱行情无5日线转强降权")
    if ma20_distance is not None and ma20_distance < -3.0 and not mature_low_suction_lift:
        adjustment -= 0.8
        notes.append("MA20未收回降权")

    tradable_ma5 = ma5_distance is not None and -2.0 <= ma5_distance <= 4.8
    controlled_close = close_location is not None and close_location < 0.78
    high_close = close_location is not None and close_location >= 0.78
    ma5_turn_or_mild_change = (
        (ma5_slope is not None and ma5_slope >= 0.0)
        or (latest_change is not None and latest_change <= 6.2)
    )
    if recent_limit_source and tradable_ma5 and controlled_close and ma5_turn_or_mild_change and low_suction_days <= 5:
        adjustment += 0.35
        notes.append("活跃且可交易低中位轻加分")
    if (
        launch_bucket == "thin_volume_launch"
        and controlled_close
        and volume_ratio is not None
        and volume_ratio <= 1.05
    ):
        adjustment += 0.35
        notes.append("缩量启动收盘可控轻加分")
    if (
        high_close
        and not recent_limit_source
        and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch", "late_pullback_launch"}
    ):
        adjustment -= 1.6
        notes.append("无涨停来源高位启动降权")
    if large_bull_count >= 3 and not recent_limit_source and high_close:
        adjustment -= 1.0
        notes.append("多大阳无涨停高位拥挤降权")
    if low_suction_days >= 6 and not fresh_lift and recent_limit_source:
        adjustment -= 1.7
        notes.append("活跃后低吸陈旧无首启降权")
    if stale_active_weak_decay_pullback:
        adjustment -= 1.1
        notes.append("活跃陈旧弱量强势衰减无首启追加降权")
    if (
        low_suction_days >= 3
        and fresh_lift
        and high_close
        and not recent_limit_source
        and launch_bucket in {"high_close_launch", "repeated_launch", "other_confirmed_launch", "late_pullback_launch"}
    ):
        adjustment -= 0.5
        notes.append("成熟低吸无涨停高位确认不足降权")
    if (
        low_suction_days >= 6
        and fresh_lift
        and high_close
        and launch_bucket in {"high_close_launch", "repeated_launch", "late_pullback_launch"}
    ):
        adjustment -= 1.2
        notes.append("后段高位启动轻降权")
    if (
        low_suction_days >= 6
        and fresh_lift
        and high_close
        and recent_limit_source
        and launch_bucket in {"high_close_launch", "repeated_launch", "late_pullback_launch"}
    ):
        adjustment -= 0.3
        notes.append("活跃后段高位确认降权")
    if ma5_distance is not None and 4.8 <= ma5_distance < 6.0 and recent_limit_source and high_close:
        adjustment -= 0.4
        notes.append("活跃高收盘偏离5日线轻降权")
    if not notes:
        return _default_candidate_quality_decision(0.0, "neutral_candidate_quality", [])
    return _default_candidate_quality_decision(
        max(min(adjustment, 3.0), -4.0),
        "default_candidate_quality",
        notes,
    )


def _default_candidate_stale_active_weak_decay_pullback(
    *,
    low_suction_days: float,
    fresh_lift: bool,
    recent_limit_source: bool,
    close_location: float | None,
    volume_ratio: float | None,
    pullback_days: float,
    strong_leg: float,
) -> bool:
    return bool(
        low_suction_days >= 6.0
        and not fresh_lift
        and recent_limit_source
        and close_location is not None
        and close_location > 0.25
        and volume_ratio is not None
        and volume_ratio <= 1.05
        and (pullback_days >= 6.0 or strong_leg >= 96.0)
    )


def _default_candidate_stale_active_long_weak_pullback(
    *,
    low_suction_days: float,
    fresh_lift: bool,
    recent_limit_source: bool,
    close_location: float | None,
    volume_ratio: float | None,
    pullback_days: float,
) -> bool:
    return _default_candidate_stale_active_weak_decay_pullback(
        low_suction_days=low_suction_days,
        fresh_lift=fresh_lift,
        recent_limit_source=recent_limit_source,
        close_location=close_location,
        volume_ratio=volume_ratio,
        pullback_days=pullback_days,
        strong_leg=0.0,
    )


def _default_candidate_mature_low_suction_lift(
    *,
    low_suction_days: float,
    fresh_lift: bool,
    ma5_distance: float | None,
    ma10_distance: float | None,
    ma_convergence: float | None,
    volume_ratio: float | None,
) -> bool:
    return bool(
        low_suction_days >= 3
        and fresh_lift
        and ma5_distance is not None
        and -1.5 <= ma5_distance <= 3.5
        and ma10_distance is not None
        and -2.0 <= ma10_distance <= 4.8
        and volume_ratio is not None
        and 0.50 <= volume_ratio <= 1.35
        and ma_convergence is not None
        and ma_convergence <= 8.0
    )


def _default_candidate_active_right_tail_source(
    evidence: dict[str, Any],
    *,
    large_bull_count: float,
    ma5_distance: float | None,
    warning_level: float,
    ma5_slope: float | None,
    latest_change: float | None,
) -> bool:
    has_recent_activity = bool(evidence.get("recent_limit_up_20d")) or large_bull_count >= 1
    return bool(
        has_recent_activity
        and ma5_distance is not None
        and ma5_distance <= 4.8
        and warning_level <= 2.0
        and (ma5_slope is not None and ma5_slope >= 0.05 or latest_change is not None and latest_change <= 6.2)
    )


def _default_candidate_quality_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {"adjustment": round(adjustment, 4), "profile": profile, "notes": notes}


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


def low_suction_lifecycle_ranking_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Rank low-suction candidates by visible buildup/launch lifecycle quality."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_type") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    if setup != "stealth_low_suction" and low_suction_days < 3:
        return _low_suction_lifecycle_decision(0.0, "not_low_suction", [])

    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    notes: list[str] = []
    adjustment = 0.0

    if ma_convergence is not None:
        if ma_convergence > 8.8:
            adjustment -= 4.0
            notes.append("低吸降权：均线重新发散")
        elif ma_convergence > 6.5:
            adjustment -= 2.0
            notes.append("低吸降权：均线收敛质量偏弱")

    if launch_confirmed:
        if launch_bucket == "balanced_first_lift" and ma_convergence is not None and ma_convergence <= 5.0:
            adjustment += 1.0
            notes.append("低吸加分：收敛状态下首个均衡上拉确认")
        elif launch_bucket == "other_confirmed_launch" and ma_convergence is not None and ma_convergence < 3.0:
            adjustment += 0.4
            notes.append("低吸加分：极度收敛后出现上拉确认")
        elif launch_bucket == "high_close_launch":
            adjustment -= 2.6
            notes.append("低吸降权：启动收盘位置偏高")
        elif launch_bucket == "repeated_launch":
            adjustment -= 2.8
            notes.append("低吸降权：重复启动未形成有效脱离")
        elif launch_bucket == "thin_volume_launch":
            adjustment -= 1.6
            notes.append("低吸降权：启动量能偏弱")
    else:
        if low_suction_days >= 3 and ma_convergence is not None and ma_convergence > 6.5:
            adjustment -= 1.6
            notes.append("低吸降权：蓄势未确认且均线偏散")

    if volume_ratio is not None:
        if volume_ratio < 0.55:
            adjustment -= 1.6
            notes.append("低吸降权：量能过度萎缩")
        elif launch_confirmed and 0.55 <= volume_ratio <= 1.15 and ma_convergence is not None and ma_convergence < 3.0:
            adjustment += 0.3
            notes.append("低吸加分：启动日量能仍可控")
        elif volume_ratio > 1.55:
            adjustment -= 1.6
            notes.append("低吸降权：放量偏急")

    if close_location is not None and close_location > 0.78:
        adjustment -= 0.8
        notes.append("低吸降权：收盘过高，追涨风险上升")
    if ma5_distance is not None and 3.2 < ma5_distance <= 4.2:
        adjustment -= 1.2
        notes.append("低吸降权：偏离5日线较远")
    if risk_penalty >= 12:
        adjustment -= 1.2
        notes.append("低吸降权：已有明显结构风险")

    if not notes:
        return _low_suction_lifecycle_decision(0.0, "neutral_low_suction", [])
    return _low_suction_lifecycle_decision(
        max(min(adjustment, 1.6), -5.0),
        "low_suction_lifecycle",
        notes,
    )


def low_suction_buildup_quality_lane_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Reward clean low-suction buildup before launch confirmation."""

    quality = _low_suction_buildup_quality(evidence)
    if not quality["eligible"]:
        return _low_suction_buildup_quality_decision(0.0, str(quality["profile"]), list(quality["notes"]))

    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    phase = str(evidence.get("dynamic_market_regime") or "")

    adjustment = 0.35 + float(quality["score"]) * 0.17
    notes = list(quality["notes"])
    notes.append("低吸蓄势加分：蓄势质量独立计分，启动确认不是前置条件")

    if low_suction_days >= 4:
        adjustment += 0.2
        notes.append("低吸蓄势加分：连续低吸天数达到4天以上")
    if low_suction_days >= 6:
        adjustment += 0.15
        notes.append("低吸蓄势加分：蓄势时间更充分")

    if launch_confirmed:
        if launch_bucket == "balanced_first_lift":
            adjustment += 0.55
            notes.append("启动确认加分：低吸后出现均衡首个上拉")
        elif launch_bucket == "other_confirmed_launch":
            adjustment += 0.35
            notes.append("启动确认加分：低吸后出现有效上拉")
        elif launch_bucket == "high_close_launch":
            notes.append("启动确认小加分：已上拉但收盘偏高，控制追涨权重")
    elif launch_bucket == "unconfirmed_buildup":
        notes.append("未确认蓄势：不扣分，只等待启动额外确认")

    if close_location is not None and close_location > 0.72:
        adjustment -= 0.3
        notes.append("低吸蓄势收敛：收盘位置偏高，避免把追涨当低吸")
    if latest_change is not None and latest_change >= 6.0:
        adjustment -= 0.25
        notes.append("低吸蓄势收敛：信号日涨幅偏大")
    if phase in {"false_bull", "weak_defensive", "crash"} or warning_level >= 3:
        adjustment -= 0.25
        notes.append("低吸蓄势收敛：行情风险仍需压低权重")

    relief = _low_suction_buildup_weekly_relief(quality, evidence)
    if relief > 0:
        adjustment += relief
        notes.append("周线顶分型减免：强低吸蓄势仍在均线承接区")

    return _low_suction_buildup_quality_decision(
        max(min(adjustment, 2.4), 0.0),
        "clean_low_suction_buildup",
        notes,
    )


def candidate_tail_risk_penalty_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Penalize visible Top20 buckets that showed poor no-position candidate quality."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_primary") or evidence.get("setup_type") or "")
    family = str(evidence.get("setup_family") or "")
    phase = str(evidence.get("dynamic_market_regime") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    mainline_strength = _mainline_momentum_strength(evidence)

    adjustment = 0.0
    notes: list[str] = []
    is_dragon = setup == "dragon_pullback" or family == "dragon_pullback"
    weak_phase = phase in {"choppy_rotation", "false_bull", "weak_defensive", "crash"}

    if is_dragon and launch_bucket == "high_close_launch":
        adjustment -= 4.2
        notes.append("候选尾部风险降权：龙回头高位收盘启动历史亏损尾部较差")
    if is_dragon and close_location is not None and close_location > 0.75 and volume_ratio is not None and 0.8 <= volume_ratio <= 1.6:
        adjustment -= 2.4
        notes.append("候选尾部风险降权：龙回头高位收盘且量能普通")
    if is_dragon and ma_convergence is not None and 6.0 <= ma_convergence <= 10.0 and close_location is not None and close_location > 0.75:
        adjustment -= 2.2
        notes.append("候选尾部风险降权：龙回头高收盘但均线仍偏发散")
    if weak_phase and launch_bucket in {"unconfirmed_buildup", "thin_volume_launch", "high_close_launch"}:
        adjustment -= 2.4
        notes.append("候选尾部风险降权：震荡/假强势中的未确认或弱量启动")
    if launch_bucket == "unconfirmed_buildup" and ma_convergence is not None and ma_convergence >= 6.0:
        adjustment -= 1.0
        notes.append("候选尾部风险降权：蓄势未确认且均线没有充分收敛")
    if warning_level >= 3 and close_location is not None and close_location > 0.72:
        adjustment -= 1.0
        notes.append("候选尾部风险降权：强风险环境下高位收盘追买")
    if risk_penalty >= 4 and close_location is not None and close_location > 0.75:
        adjustment -= 0.8
        notes.append("候选尾部风险降权：结构风险叠加高位收盘")

    if mainline_strength >= 3.0 and adjustment < 0:
        adjustment += min(abs(adjustment), 1.8)
        notes.append("主线动量保护：近期涨停/大阳活跃，降低尾部风险扣分强度")

    if not notes:
        return _candidate_tail_risk_decision(0.0, "neutral", [])
    return _candidate_tail_risk_decision(max(adjustment, -8.0), "top20_tail_risk", notes)


def mainline_momentum_lane_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Give a default-off ranking bonus to visible mainline/momentum candidates."""

    strength = _mainline_momentum_strength(evidence)
    if strength < 3.5:
        return _mainline_momentum_lane_decision(0.0, "no_mainline_momentum", [])

    phase = str(evidence.get("dynamic_market_regime") or "")
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    liquidity = _float_or_none(evidence.get("liquidity_score"))
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    notes = ["主线动量加分：近期涨停/大阳活跃，属于当前策略漏选的大赢家特征"]
    adjustment = 0.5 + min(strength, 5.0) * 0.35

    if phase in {"strong_broad", "narrow_theme_bull", "mainline_pullback", "choppy_rotation"}:
        adjustment += 0.6
        notes.append("主线动量加分：行情阶段允许强趋势候选竞争")
    elif phase in {"false_bull", "weak_defensive", "crash"}:
        adjustment -= 1.4
        notes.append("主线动量降温：假强势/弱势环境下不放大追高")

    if close_location is not None:
        if 0.4 <= close_location <= 0.82:
            adjustment += 0.4
            notes.append("主线动量加分：收盘位置仍有分歧")
        elif close_location > 0.9:
            adjustment -= 1.4
            notes.append("主线动量降温：收盘过于一致")
    if volume_ratio is not None:
        if 0.75 <= volume_ratio <= 2.3:
            adjustment += 0.3
            notes.append("主线动量加分：量能活跃但未极端失控")
        elif volume_ratio > 3.0:
            adjustment -= 1.4
            notes.append("主线动量降温：放量过猛")
    if ma_convergence is not None:
        if ma_convergence >= 18.0:
            adjustment -= 1.4
            notes.append("主线动量降温：均线极度发散，先控制回撤")
        elif ma_convergence > 12.0:
            adjustment -= 0.7
            notes.append("主线动量降温：均线发散，控制追高幅度")
    if latest_change is not None and latest_change >= 9.5:
        adjustment -= 1.6
        notes.append("主线动量降温：信号日接近涨停，D+1 可买性存疑")
    if warning_level >= 3:
        adjustment -= 1.4
        notes.append("主线动量降温：市场风险等级偏高")
    if risk_penalty >= 8:
        adjustment -= 1.2
        notes.append("主线动量降温：个股结构风险偏高")
    if liquidity is not None and liquidity < 35:
        adjustment = min(adjustment, 0.0)
        notes.append("主线动量过滤：流动性不足")

    return _mainline_momentum_lane_decision(max(min(adjustment, 3.0), 0.0), "mainline_momentum", notes)


def mainline_momentum_risk_control_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Demote overextended momentum candidates while keeping asymmetric pullbacks."""

    strength = _mainline_momentum_strength(evidence)
    lane_adjustment = _float_or_none(evidence.get("mainline_momentum_lane_adjustment")) or 0.0
    if strength < 3.0 and lane_adjustment <= 0:
        return _mainline_momentum_risk_control_decision(0.0, "no_mainline_momentum", [])

    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    phase = str(evidence.get("dynamic_market_regime") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0

    adjustment = 0.0
    notes: list[str] = []

    asymmetric_lower = (
        close_location is not None
        and close_location <= 0.58
        and ma_convergence is not None
        and 3.0 <= ma_convergence <= 14.0
        and (ma5_distance is None or ma5_distance <= 3.5)
    )
    asymmetric_low_wide = (
        close_location is not None
        and close_location < 0.35
        and ma_convergence is not None
        and 6.0 <= ma_convergence <= 18.0
        and (ma5_distance is None or ma5_distance <= 3.5)
    )
    if asymmetric_lower or asymmetric_low_wide:
        adjustment += 0.6
        notes.append("主线风控保留：活跃票仍在低位/中低位分歧承接区")

    if close_location is not None:
        if close_location > 0.88:
            adjustment -= 2.4
            notes.append("主线风控降权：收盘过高，D+1 追买回撤风险大")
        elif close_location > 0.75 and ma_convergence is not None and ma_convergence >= 18.0:
            adjustment -= 2.2
            notes.append("主线风控降权：高收盘叠加均线极度发散")
    if ma_convergence is not None:
        if ma_convergence >= 22.0:
            adjustment -= 2.2
            notes.append("主线风控降权：均线极度发散，尾部回撤过深")
        elif ma_convergence >= 18.0 and not asymmetric_low_wide:
            adjustment -= 1.4
            notes.append("主线风控降权：均线发散已接近尾部风险区")
    if ma5_distance is not None:
        if ma5_distance > 5.5:
            adjustment -= 2.6
            notes.append("主线风控降权：偏离5日线过远")
        elif ma5_distance > 3.5 and close_location is not None and close_location > 0.75:
            adjustment -= 1.8
            notes.append("主线风控降权：高位收盘且偏离5日线")
    if launch_bucket in {"repeated_launch", "thin_volume_launch", "other_confirmed_launch"}:
        adjustment -= 1.2
        notes.append("主线风控降权：弱启动/反复启动的动量候选先控制排名")
    if launch_bucket == "high_close_launch" and close_location is not None and close_location > 0.75:
        adjustment -= 1.0
        notes.append("主线风控降权：高位启动追买性价比不足")
    if phase == "false_bull" and warning_level >= 2 and close_location is not None and close_location > 0.58:
        adjustment -= 1.2
        notes.append("主线风控降权：假强势中不放大中高位动量")
    if volume_ratio is not None and volume_ratio > 3.0:
        adjustment -= 1.2
        notes.append("主线风控降权：放量过猛")
    if latest_change is not None and latest_change >= 8.5:
        adjustment -= 1.1
        notes.append("主线风控降权：信号日涨幅过大")
    if risk_penalty >= 10:
        adjustment -= 0.8
        notes.append("主线风控降权：结构风险偏高")

    if adjustment < 0 and asymmetric_lower and volume_ratio is not None and 0.75 <= volume_ratio <= 2.2:
        relief = min(abs(adjustment), 0.9)
        adjustment += relief
        notes.append("主线风控减免：低位分歧且量能未失控")

    if not notes:
        return _mainline_momentum_risk_control_decision(0.0, "neutral_mainline_momentum", [])
    return _mainline_momentum_risk_control_decision(
        max(min(adjustment, 1.2), -7.0),
        "mainline_momentum_risk_control",
        notes,
    )


def mainline_momentum_hard_filter_reason(evidence: dict[str, Any]) -> str | None:
    """Return a no-future hard-filter reason for extreme momentum tail risk."""

    return _mainline_momentum_hard_filter_reason(evidence)


def surge_quality_lane_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Separate active surge setups from crowded or stale Top20 candidates."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_primary") or evidence.get("setup_type") or "")
    family = str(evidence.get("setup_family") or "")
    phase = str(evidence.get("dynamic_market_regime") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    strength = _mainline_momentum_strength(evidence)

    is_dragon = setup == "dragon_pullback" or family == "dragon_pullback"
    is_low_reclaim = family in {"low_position_reclaim", "low_suction_first_lift", "low_suction_buildup"}
    active_money = strength >= 3.0 or bool(evidence.get("recent_limit_up_20d")) or large_bull_count >= 3
    lower_mid_close = close_location is not None and 0.35 <= close_location <= 0.58
    tradable_close = close_location is not None and 0.20 <= close_location <= 0.75
    balanced_close = close_location is not None and 0.58 <= close_location <= 0.75
    healthy_volume = volume_ratio is None or 0.65 <= volume_ratio <= 2.2
    stale_low_suction = low_suction_days >= 6 and not active_money
    active_wide_trend = active_money and ma_convergence is not None and 10.0 <= ma_convergence <= 18.0

    adjustment = 0.0
    notes: list[str] = []

    if active_wide_trend and tradable_close and healthy_volume:
        adjustment += 0.6 + min(strength, 6.0) * 0.25
        notes.append("猛拉质量加分：近期涨停/大阳活跃且均线趋势已打开")
        if lower_mid_close:
            adjustment += 0.55
            notes.append("猛拉质量加分：收盘在中低位，历史更容易上拉")
        elif balanced_close:
            adjustment += 0.35
            notes.append("猛拉质量加分：收盘在均衡上拉区")
        if large_bull_count >= 3:
            adjustment += 0.35
            notes.append("猛拉质量加分：20日内多次大阳线")
    elif (
        is_low_reclaim
        and launch_bucket in {"balanced_first_lift", "late_pullback_launch", "other_confirmed_launch"}
        and balanced_close
        and healthy_volume
        and warning_level <= 1
    ):
        adjustment += 0.55
        notes.append("低吸质量加分：低吸后已有可见上拉，且收盘位置均衡")

    if is_dragon and launch_bucket == "balanced_first_lift" and balanced_close:
        adjustment += 0.35
        notes.append("猛拉质量加分：龙回头出现均衡首启")
    if is_dragon and launch_bucket == "not_low_suction" and active_money and lower_mid_close:
        adjustment += 0.25
        notes.append("猛拉质量加分：活跃龙回头不依赖低吸确认")

    if launch_bucket == "unconfirmed_buildup" and family == "low_suction_buildup":
        adjustment -= 0.8
        notes.append("弱启动降权：未确认低吸蓄势在当前卖点模型中胜率偏低")
    if launch_bucket == "high_close_launch" and (
        warning_level >= 3
        or (ma5_distance is not None and ma5_distance > 4.5)
        or (close_location is not None and close_location > 0.92 and not active_wide_trend)
    ):
        adjustment -= 1.0
        notes.append("弱启动降权：高位启动叠加风险，D+1追买性价比低")
    if launch_bucket == "thin_volume_launch" and (volume_ratio is None or volume_ratio < 0.75):
        adjustment -= 1.2
        notes.append("弱启动降权：启动量能偏薄，容易先回撤")
    if launch_bucket == "other_confirmed_launch" and is_dragon:
        adjustment -= 1.2
        notes.append("弱启动降权：龙回头非均衡确认后的历史收益偏弱")
    if launch_bucket == "repeated_launch" and close_location is not None and close_location > 0.72:
        adjustment -= 1.2
        notes.append("弱启动降权：重复启动叠加高位收盘")
    if stale_low_suction and launch_bucket not in {"balanced_first_lift", "late_pullback_launch", "other_confirmed_launch"}:
        adjustment -= 1.6
        notes.append("弱启动降权：低吸蓄势超过6天但没有新激活")
    if family == "unknown" and not active_money:
        adjustment -= 1.2
        notes.append("弱启动降权：未知形态且缺少活跃资金证据")
    if close_location is not None and close_location > 0.88:
        adjustment -= 1.1
        notes.append("弱启动降权：收盘过高，D+1 追买性价比差")
    if latest_change is not None and latest_change >= 8.5:
        adjustment -= 0.9
        notes.append("弱启动降权：信号日涨幅过大")
    if ma5_distance is not None and ma5_distance > 4.5:
        adjustment -= 0.8
        notes.append("弱启动降权：偏离5日线过远")
    if ma_convergence is not None and ma_convergence > 22.0 and not lower_mid_close:
        adjustment -= 1.0
        notes.append("弱启动降权：均线过度发散且收盘没有性价比")
    if warning_level >= 3 and close_location is not None and close_location > 0.72:
        adjustment -= 1.0
        notes.append("弱启动降权：行情风险高时不追高位启动")
    if phase in {"weak_defensive", "crash"}:
        adjustment -= 0.8
        notes.append("弱启动降权：弱势/崩盘环境收敛排名")
    if risk_penalty >= 10:
        adjustment -= 0.8
        notes.append("弱启动降权：结构风险偏高")

    if adjustment < 0 and active_money and lower_mid_close and healthy_volume:
        relief = min(abs(adjustment), 1.2)
        adjustment += relief
        notes.append("活跃低位保护：有主线资金且收盘不拥挤，降低扣分强度")

    if not notes:
        return _surge_quality_lane_decision(0.0, "neutral", [])
    return _surge_quality_lane_decision(
        max(min(adjustment, 3.0), -5.5),
        "surge_quality",
        notes,
    )


def weekly_top_fractal_relief_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Partially relax weekly-top-fractal risk only for supported strong trends."""

    if not _has_weekly_top_fractal_risk(evidence):
        return _weekly_top_fractal_relief_decision(0.0, "no_weekly_top_fractal_risk", [])

    setup = str(evidence.get("entry_setup") or evidence.get("setup_primary") or evidence.get("setup_type") or "")
    family = str(evidence.get("setup_family") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    return_20d = _float_or_none(evidence.get("return_20d")) or 0.0
    return_60d = _float_or_none(evidence.get("return_60d")) or 0.0
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    phase = str(evidence.get("dynamic_market_regime") or "")
    support_type = str(evidence.get("support_type") or "")
    notes: list[str] = []

    is_dragon = setup == "dragon_pullback" or family == "dragon_pullback"
    if not is_dragon:
        return _weekly_top_fractal_relief_decision(0.0, "keep_non_dragon_weekly_risk", [])
    if launch_bucket in {"high_close_launch", "thin_volume_launch", "unconfirmed_buildup"}:
        return _weekly_top_fractal_relief_decision(0.0, "keep_weak_launch_weekly_risk", [])
    if evidence.get("high_level_sideways_distribution_risk") or evidence.get("volume_stall_risk"):
        return _weekly_top_fractal_relief_decision(0.0, "keep_distribution_weekly_risk", [])
    if latest_change is not None and latest_change >= 9.5:
        return _weekly_top_fractal_relief_decision(0.0, "keep_limit_like_weekly_risk", [])
    if close_location is not None and close_location > 0.88:
        return _weekly_top_fractal_relief_decision(0.0, "keep_high_close_weekly_risk", [])
    if volume_ratio is not None and volume_ratio > 2.2:
        return _weekly_top_fractal_relief_decision(0.0, "keep_volume_spike_weekly_risk", [])

    support_ok = support_type in {"ma5_reclaim", "ma10_reclaim", "ma20_reclaim"} or (
        ma5_distance is not None and -1.2 <= ma5_distance <= 3.4
    )
    trend_ok = return_20d >= 12.0 or return_60d >= 25.0 or _mainline_momentum_strength(evidence) >= 3.0
    ma_ok = ma_convergence is None or ma_convergence <= 14.0
    if not (support_ok and trend_ok and ma_ok):
        return _weekly_top_fractal_relief_decision(0.0, "keep_unconfirmed_trend_weekly_risk", [])

    adjustment = 2.0
    notes.append("周线顶分型减免：强趋势龙回头仍在均线承接区")
    if ma5_distance is not None and -0.8 <= ma5_distance <= 2.4:
        adjustment += 0.4
        notes.append("周线顶分型减免：贴近5日线承接")
    if ma10_distance is not None and -1.2 <= ma10_distance <= 3.2:
        adjustment += 0.3
        notes.append("周线顶分型减免：10日线距离可控")
    if phase in {"false_bull", "weak_defensive", "crash"} or warning_level >= 4:
        adjustment -= 0.8
        notes.append("周线顶分型减免收敛：行情风险偏高")
    elif phase in {"choppy_rotation", "strong_broad", "narrow_theme_bull"} and warning_level <= 3:
        adjustment += 0.2
        notes.append("周线顶分型减免：行情允许强趋势竞争")

    return _weekly_top_fractal_relief_decision(max(min(adjustment, 3.0), 0.0), "supported_strong_dragon", notes)


def pure_loss_weak_bucket_penalty(evidence: dict[str, Any]) -> dict[str, Any]:
    """Demote signal-day buckets that mostly become pure losses."""

    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    active_strength = _mainline_momentum_strength(evidence)

    high_close = close_location is not None and close_location > 0.75
    mid_high_close = close_location is not None and 0.58 <= close_location <= 0.75
    weak_volume = volume_ratio is not None and volume_ratio < 0.85
    active = active_strength >= 3.0 or bool(evidence.get("recent_limit_up_20d"))

    adjustment = 0.0
    notes: list[str] = []

    if high_close and launch_bucket == "thin_volume_launch":
        adjustment -= 4.0
        notes.append("纯亏弱桶降权：高位薄量启动")
    if mid_high_close and launch_bucket == "other_confirmed_launch":
        adjustment -= 3.2
        notes.append("纯亏弱桶降权：中高位非均衡确认启动")
    if high_close and launch_bucket == "repeated_launch":
        adjustment -= 3.0
        notes.append("纯亏弱桶降权：高位重复启动")
    if high_close and launch_bucket == "unconfirmed_buildup":
        adjustment -= 2.6
        notes.append("纯亏弱桶降权：未确认蓄势但收盘偏高")
    if mid_high_close and launch_bucket == "unconfirmed_buildup":
        adjustment -= 1.6
        notes.append("纯亏弱桶降权：未确认蓄势在中高位")
    if high_close and launch_bucket == "high_close_launch":
        adjustment -= 2.0
        notes.append("纯亏弱桶降权：高收盘启动追买拥挤")
    if low_suction_days >= 6 and not active and launch_bucket not in {"balanced_first_lift", "late_pullback_launch"}:
        adjustment -= 2.0
        notes.append("纯亏弱桶降权：低吸过久但缺少活跃资金")
    if ma_convergence is not None and ma_convergence < 3.0 and not active and launch_bucket in {
        "unconfirmed_buildup",
        "thin_volume_launch",
        "repeated_launch",
    }:
        adjustment -= 1.4
        notes.append("纯亏弱桶降权：均线过紧且未激活")
    if high_close and weak_volume:
        adjustment -= 0.8
        notes.append("纯亏弱桶降权：高位收盘但量能不足")
    if high_close and latest_change is not None and latest_change >= 7.5:
        adjustment -= 0.8
        notes.append("纯亏弱桶降权：信号日高涨幅后追买")
    if high_close and warning_level >= 3:
        adjustment -= 0.8
        notes.append("纯亏弱桶降权：行情风险高时追高")

    if adjustment < 0 and active and close_location is not None and close_location < 0.58 and 3.0 <= (ma_convergence or 99.0) <= 6.0:
        relief = min(abs(adjustment), 1.6)
        adjustment += relief
        notes.append("纯亏弱桶减免：活跃资金在低位/下中位承接")

    if not notes:
        return _pure_loss_weak_bucket_decision(0.0, "neutral", [])
    return _pure_loss_weak_bucket_decision(max(adjustment, -6.0), "pure_loss_weak_bucket", notes)


def selective_setup_quality_lane_adjustment(evidence: dict[str, Any]) -> dict[str, Any]:
    """Default-off score lane from the latest Top20 surge/decline audit."""

    setup = str(evidence.get("entry_setup") or evidence.get("setup_primary") or evidence.get("setup_type") or "")
    family = str(evidence.get("setup_family") or "")
    phase = str(evidence.get("dynamic_market_regime") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    strength = _mainline_momentum_strength(evidence)
    active = strength >= 3.0 or bool(evidence.get("recent_limit_up_20d"))
    strong_active = strength >= 5.0
    healthy_volume = volume_ratio is None or 0.75 <= volume_ratio <= 2.3
    weak_launch = launch_bucket in {
        "high_close_launch",
        "thin_volume_launch",
        "other_confirmed_launch",
        "repeated_launch",
        "unconfirmed_buildup",
    }
    is_low_reclaim = family in {"low_position_reclaim", "low_suction_first_lift", "low_suction_buildup"}
    has_low_suction_context = setup == "stealth_low_suction" or is_low_reclaim or low_suction_days >= 3

    adjustment = 0.0
    notes: list[str] = []

    active_lower_mid = (
        active
        and close_location is not None
        and close_location <= 0.58
        and ma_convergence is not None
        and 3.0 <= ma_convergence <= 18.0
        and (ma5_distance is None or ma5_distance <= 3.5)
        and healthy_volume
    )
    active_mid_high = (
        active
        and close_location is not None
        and 0.58 < close_location <= 0.75
        and ma_convergence is not None
        and 6.0 <= ma_convergence <= 18.0
        and (ma5_distance is None or ma5_distance <= 3.5)
        and healthy_volume
    )
    if active_lower_mid:
        adjustment += 1.9 if strong_active else 1.4
        notes.append("精选质量加分：活跃资金在中低位承接，仍贴近5日线")
    elif active_mid_high:
        adjustment += 0.5
        notes.append("精选质量小加分：活跃资金在趋势区但性价比一般")

    if has_low_suction_context and 3 <= low_suction_days <= 5 and close_location is not None and close_location <= 0.58:
        if ma_convergence is not None and ma_convergence <= 6.0 and healthy_volume and warning_level <= 2:
            adjustment += 0.7
            notes.append("精选质量加分：3-5天低吸蓄势且均线收敛")

    if active and close_location is not None and close_location > 0.88:
        adjustment -= 3.2
        notes.append("精选质量降权：活跃票收盘极高，历史容易先回撤")
    elif active and close_location is not None and close_location > 0.75 and ma_convergence is not None and 3.0 <= ma_convergence <= 10.0:
        adjustment -= 1.4
        notes.append("精选质量降权：活跃票高收盘但趋势结构未充分打开")

    if close_location is not None and close_location > 0.75 and weak_launch:
        adjustment -= 1.8
        notes.append("精选质量降权：高收盘弱启动")
        if warning_level >= 2 or phase in {"strong_broad", "false_bull", "choppy_rotation"}:
            adjustment -= 0.7
            notes.append("精选质量降权：行情/一致性环境下弱启动更容易失败")

    if low_suction_days >= 6 and not active and launch_bucket not in {"balanced_first_lift", "late_pullback_launch"}:
        adjustment -= 2.4
        notes.append("精选质量降权：低吸蓄势过久但缺少新激活")
    if ma_convergence is not None and ma_convergence < 3.0 and not active:
        adjustment -= 1.8
        notes.append("精选质量降权：均线过紧但没有活跃资金")

    if warning_level >= 3 and ma5_distance is not None and ma5_distance > 5.5:
        adjustment -= 2.2
        notes.append("精选质量降权：风险日偏离5日线过远")
    if latest_change is not None and latest_change >= 8.5 and close_location is not None and close_location > 0.75:
        adjustment -= 1.0
        notes.append("精选质量降权：信号日高涨幅后再追高")
    if risk_penalty >= 10:
        adjustment -= 0.8
        notes.append("精选质量降权：结构风险偏高")

    if adjustment < 0 and active_lower_mid:
        relief = min(abs(adjustment), 1.2)
        adjustment += relief
        notes.append("精选质量减免：活跃中低位承接保留右尾机会")

    if not notes:
        return _selective_setup_quality_decision(0.0, "neutral", [])
    return _selective_setup_quality_decision(
        max(min(adjustment, 2.6), -6.0),
        "selective_setup_quality",
        notes,
    )


def top20_day_quality_profile(candidates: list[Any]) -> dict[str, Any]:
    """Classify a signal day's pre-ranked Top20 composition with visible factors only."""

    rows = list(candidates[:20])
    count = len(rows)
    if count < 10:
        return _top20_day_quality_profile(0, "neutral_top20_day", 0.0, 0.0, 0.0, 0.0, 0.0, [])

    active_count = 0
    low_mid_count = 0
    high_count = 0
    weak_launch_count = 0
    active_low_mid_count = 0
    active_high_weak_count = 0
    stale_quiet_count = 0
    for score in rows:
        features = _top20_day_candidate_features(getattr(score, "evidence", {}) or {})
        active_count += int(features["active"])
        low_mid_count += int(features["low_mid_close"])
        high_count += int(features["high_close"])
        weak_launch_count += int(features["weak_launch"])
        active_low_mid_count += int(features["active_low_mid_acceptance"])
        active_high_weak_count += int(features["active_high_weak_launch"])
        stale_quiet_count += int(features["stale_quiet"])

    active_ratio = active_count / count
    low_mid_ratio = low_mid_count / count
    high_ratio = high_count / count
    weak_launch_ratio = weak_launch_count / count
    active_low_mid_ratio = active_low_mid_count / count
    notes: list[str] = []
    quality_score = 0.0

    if active_low_mid_ratio >= 0.30 and low_mid_ratio >= 0.45 and high_ratio <= 0.30 and weak_launch_ratio <= 0.30:
        quality_score += 2.2
        notes.append("候选日加分：Top20 集中在活跃中低位承接")
    elif active_low_mid_ratio >= 0.22 and low_mid_ratio >= 0.35 and high_ratio <= 0.35:
        quality_score += 1.2
        notes.append("候选日加分：Top20 有较多活跃中低位承接")

    if active_ratio >= 0.55 and high_ratio >= 0.50 and weak_launch_ratio >= 0.40:
        quality_score -= 2.6
        notes.append("候选日降权：Top20 活跃但高位弱启动拥挤")
    elif high_ratio >= 0.55 and weak_launch_ratio >= 0.35:
        quality_score -= 1.6
        notes.append("候选日降权：Top20 高位弱启动占比偏高")
    if active_high_weak_count >= 6:
        quality_score -= 0.8
        notes.append("候选日降权：活跃高位弱启动数量过多")
    if stale_quiet_count >= 5 and active_low_mid_ratio < 0.25:
        quality_score -= 0.8
        notes.append("候选日降权：低吸过久但未激活的安静结构偏多")

    if not notes:
        return _top20_day_quality_profile(
            count,
            "neutral_top20_day",
            round(active_ratio, 4),
            round(low_mid_ratio, 4),
            round(high_ratio, 4),
            round(weak_launch_ratio, 4),
            round(active_low_mid_ratio, 4),
            [],
        )
    return _top20_day_quality_profile(
        count,
        "strong_top20_day" if quality_score > 0 else "weak_top20_day",
        round(active_ratio, 4),
        round(low_mid_ratio, 4),
        round(high_ratio, 4),
        round(weak_launch_ratio, 4),
        round(active_low_mid_ratio, 4),
        notes,
        quality_score=max(min(quality_score, 3.0), -3.0),
    )


def top20_day_quality_adjustment(evidence: dict[str, Any], day_profile: dict[str, Any]) -> dict[str, Any]:
    """Return candidate score adjustment from same-day Top20 composition."""

    profile = str(day_profile.get("profile") or "neutral_top20_day")
    day_score = _float_or_none(day_profile.get("quality_score")) or 0.0
    if profile == "neutral_top20_day" or day_score == 0:
        return _top20_day_quality_decision(0.0, profile, [])

    features = _top20_day_candidate_features(evidence)
    adjustment = 0.0
    notes: list[str] = list(day_profile.get("notes") or [])

    if day_score > 0:
        if features["active_low_mid_acceptance"]:
            adjustment += min(1.8, 0.75 + day_score * 0.35)
            notes.append("候选日个股加分：活跃资金在中低位承接且贴近5日线")
        elif features["active"] and features["low_mid_close"] and not features["weak_launch"]:
            adjustment += min(0.7, 0.25 + day_score * 0.15)
            notes.append("候选日个股小加分：收盘仍有分歧且弱启动风险不高")
        if features["high_close"] and features["weak_launch"]:
            adjustment -= 0.8
            notes.append("候选日个股降权：好日中仍属于高位弱启动")
    else:
        if features["active_low_mid_acceptance"]:
            adjustment += 0.5
            notes.append("候选日个股保护：坏日中仍保留活跃中低位承接")
        elif features["active"] and features["low_mid_close"] and not features["weak_launch"]:
            adjustment += 0.2
            notes.append("候选日个股保护：活跃但未拥挤")
        elif features["high_close"] and features["weak_launch"]:
            adjustment -= min(2.4, 0.8 + abs(day_score) * 0.45)
            notes.append("候选日个股降权：弱日高位弱启动容易先回撤")
        elif features["stale_quiet"]:
            adjustment -= min(1.8, 0.6 + abs(day_score) * 0.35)
            notes.append("候选日个股降权：弱日低吸过久但缺少激活")
        elif features["high_close"]:
            adjustment -= 0.6
            notes.append("候选日个股降权：弱日高位收盘性价比不足")

    if adjustment == 0:
        return _top20_day_quality_decision(0.0, profile, [])
    return _top20_day_quality_decision(max(min(adjustment, 2.0), -3.0), profile, notes)


def phase_aware_setup_selector_decision(evidence: dict[str, Any]) -> dict[str, Any]:
    """Default-off selector combining market phase with strategy family.

    This uses only signal-day visible evidence attached to the candidate. Future
    outcomes remain audit-only and are not used here.
    """

    family = str(evidence.get("setup_family") or market_phase_setup_family(evidence))
    phase = str(market_context.classify_trading_market_phase(evidence).get("phase") or "unknown")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    launch_confirmed = bool(evidence.get("low_suction_launch_confirmed"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    tail_repeat = _float_or_none(evidence.get("tail_buy_repeat_days")) or 0.0
    score_adjustment = 0.0
    allowed = True
    notes: list[str] = []

    if family == "low_suction_buildup":
        allowed = False
        notes.append("行情选择器：低吸蓄势只观察，不作为组合可买点")
    elif phase == "retreat":
        if family == "low_suction_first_lift" and launch_confirmed and launch_bucket in {"balanced_first_lift", "other_confirmed_launch"}:
            score_adjustment += 1.2
            notes.append("退潮期只保留低吸首启中的强承接候选")
        elif family == "dragon_low_suction_overlap" and launch_confirmed and launch_bucket == "balanced_first_lift":
            score_adjustment += 0.6
            notes.append("退潮期保留低吸和龙回头重叠的均衡首启")
        elif family == "dragon_pullback":
            allowed = False
            notes.append("退潮期过滤普通龙回头，避免行情下行时抢回踩")
        else:
            allowed = False
            notes.append("退潮期过滤非强承接候选")
    elif phase == "warming":
        if family == "low_suction_first_lift":
            score_adjustment += 1.0
            notes.append("回暖期优先低吸首启")
        elif family == "dragon_low_suction_overlap":
            score_adjustment += 0.6
            notes.append("回暖期保留低吸和龙回头重叠")
        elif family == "dragon_pullback" and tail_repeat >= 2:
            score_adjustment -= 1.2
            notes.append("回暖期降低重复龙回头")
    elif phase == "uptrend":
        if family == "dragon_pullback" and tail_repeat <= 1:
            score_adjustment += 1.2
            notes.append("主升期优先新鲜龙回头")
        elif family == "dragon_low_suction_overlap" and launch_confirmed:
            score_adjustment += 0.8
            notes.append("主升期保留龙回头叠加低吸确认")
        elif family == "low_suction_first_lift" and low_suction_days >= 3:
            score_adjustment += 0.4
            notes.append("主升期低吸首启只作小幅优先")
        elif family == "dragon_pullback" and tail_repeat >= 3:
            score_adjustment -= 1.2
            notes.append("主升期降低重复龙回头")
    elif phase == "rotation":
        if family == "low_suction_first_lift":
            score_adjustment += 0.8
            notes.append("震荡期优先低吸首启")
        elif family == "dragon_low_suction_overlap":
            score_adjustment += 0.4
            notes.append("震荡期保留低吸和龙回头重叠")
        elif family == "dragon_pullback" and tail_repeat >= 3:
            score_adjustment -= 1.0
            notes.append("震荡期降低重复龙回头")

    if evidence.get("early_dragon_pullback_risk") and phase in {"retreat", "rotation"}:
        score_adjustment -= 1.4
        notes.append("行情选择器：弱行情下经典龙回头偏早")
    if evidence.get("high_level_sideways_distribution_risk") or evidence.get("volume_stall_risk"):
        score_adjustment -= 1.0
        notes.append("行情选择器：高位横盘/放量滞涨风险")

    return {
        "allowed": allowed,
        "phase": phase,
        "setup_family": family,
        "score_adjustment": max(min(score_adjustment, 2.0), -2.0),
        "notes": notes,
        "audit_only": False,
        "no_future_data": True,
    }


def _low_suction_lifecycle_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _low_suction_buildup_quality_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _candidate_tail_risk_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _mainline_momentum_lane_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _mainline_momentum_risk_control_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _surge_quality_lane_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _weekly_top_fractal_relief_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _pure_loss_weak_bucket_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _selective_setup_quality_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _top20_day_quality_decision(adjustment: float, profile: str, notes: list[str]) -> dict[str, Any]:
    return {
        "adjustment": adjustment,
        "profile": profile,
        "notes": notes,
        "not_used_for_signal_score": False,
    }


def _is_mainline_momentum_entry_signal(score, params: BacktestParams) -> bool:
    if not params.enable_mainline_momentum_lane:
        return False
    evidence = getattr(score, "evidence", {}) or {}
    if _mainline_momentum_strength(evidence) < 4.0:
        return False
    if float(getattr(score, "total_score", 0) or 0) < max(params.min_entry_score, 82.0):
        return False
    if evidence.get("key_support_break_risk") or evidence.get("illiquid_forgotten_risk"):
        return False
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    if latest_change is not None and latest_change >= 9.5:
        return False
    liquidity = _float_or_none(evidence.get("liquidity_score"))
    if liquidity is not None and liquidity < 35:
        return False
    return True


def _mainline_momentum_hard_filter_reason(evidence: dict[str, Any]) -> str | None:
    if not (evidence.get("mainline_momentum_lane_adjustment") or _mainline_momentum_strength(evidence) >= 3.0):
        return None
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    warning_level = _float_or_none(evidence.get("market_warning_level")) or 0.0
    phase = str(evidence.get("dynamic_market_regime") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    active = _mainline_momentum_strength(evidence) >= 3.5 or bool(evidence.get("recent_limit_up_20d"))

    if close_location is not None and close_location > 0.75 and launch_bucket in {
        "repeated_launch",
        "thin_volume_launch",
        "other_confirmed_launch",
    }:
        return "high_close_weak_launch"
    if ma5_distance is not None and ma5_distance > 5.5 and ma_convergence is not None and ma_convergence >= 14.0:
        return "ma5_overextended_wide_ma"
    if close_location is not None and close_location > 0.88 and ma5_distance is not None and ma5_distance > 3.5:
        return "extreme_high_far_ma5"
    if close_location is not None and close_location > 0.88 and launch_bucket in {"high_close_launch", "late_pullback_launch"}:
        return "extreme_high_failed_launch"
    if ma_convergence is not None and ma_convergence >= 18.0 and ma5_distance is not None and ma5_distance > 3.5:
        return "extreme_ma_far_ma5"
    if phase == "false_bull" and warning_level >= 2 and ma_convergence is not None and ma_convergence >= 18.0:
        return "false_bull_extreme_ma"
    if warning_level >= 3 and ma5_distance is not None and ma5_distance > 8.0:
        return "risk_day_extreme_ma5_distance"
    if ma5_distance is not None and ma5_distance > 3.5 and launch_bucket == "unconfirmed_buildup" and not active:
        return "stale_unconfirmed_far_ma5"
    return None


def _is_candidate_tail_risk_blocked(evidence: dict[str, Any]) -> bool:
    setup = str(evidence.get("entry_setup") or evidence.get("setup_primary") or evidence.get("setup_type") or "")
    family = str(evidence.get("setup_family") or "")
    phase = str(evidence.get("dynamic_market_regime") or "")
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    is_dragon = setup == "dragon_pullback" or family == "dragon_pullback"
    if _mainline_momentum_strength(evidence) >= 4.0:
        return False
    if is_dragon and launch_bucket == "high_close_launch" and phase in {"choppy_rotation", "false_bull"}:
        return True
    if (
        is_dragon
        and phase in {"choppy_rotation", "false_bull"}
        and close_location is not None
        and close_location > 0.82
        and volume_ratio is not None
        and 0.8 <= volume_ratio <= 1.6
        and ma_convergence is not None
        and ma_convergence >= 6.0
    ):
        return True
    return False


def _mainline_momentum_strength(evidence: dict[str, Any]) -> float:
    recent_limit_up = bool(
        evidence.get("recent_limit_up_20d")
        or evidence.get("limit_up_count_20d")
        or evidence.get("near_limit_up_count_20d")
    )
    large_bull_count = _float_or_none(evidence.get("large_bull_count_20d")) or 0.0
    near_limit_up_count = _float_or_none(evidence.get("near_limit_up_count_20d")) or 0.0
    consecutive_bull_closes = _float_or_none(evidence.get("consecutive_bull_closes")) or 0.0
    theme_strength = _float_or_none(evidence.get("theme_strength"))
    liquidity = _float_or_none(evidence.get("liquidity_score"))
    score = 0.0
    if recent_limit_up:
        score += 1.6
    score += min(large_bull_count, 6.0) * 0.55
    score += min(near_limit_up_count, 5.0) * 0.25
    if consecutive_bull_closes >= 4:
        score += 0.8
    if evidence.get("persistent_volume_expansion") or evidence.get("upward_gap_in_leg"):
        score += 0.5
    if theme_strength is not None and theme_strength >= 70:
        score += 0.6
    if liquidity is not None and liquidity >= 70:
        score += 0.4
    return score


def _has_weekly_top_fractal_risk(evidence: dict[str, Any]) -> bool:
    if bool(evidence.get("weekly_top_fractal_risk")):
        return True
    flags = evidence.get("risk_flags")
    if isinstance(flags, list):
        return "weekly_top_fractal_risk" in flags
    return "weekly_top_fractal_risk" in str(flags or "")


def _top20_day_candidate_features(evidence: dict[str, Any]) -> dict[str, bool]:
    launch_bucket = str(
        evidence.get("low_suction_launch_quality_bucket")
        or low_suction_launch_quality_bucket(evidence)
        or ""
    )
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    active = _mainline_momentum_strength(evidence) >= 3.0 or bool(evidence.get("recent_limit_up_20d"))
    low_mid_close = close_location is not None and close_location < 0.58
    high_close = close_location is not None and close_location > 0.75
    weak_launch = launch_bucket in {
        "high_close_launch",
        "thin_volume_launch",
        "other_confirmed_launch",
        "repeated_launch",
        "unconfirmed_buildup",
    }
    healthy_volume = volume_ratio is None or 0.65 <= volume_ratio <= 2.3
    active_low_mid_acceptance = bool(
        active
        and low_mid_close
        and ma_convergence is not None
        and 3.0 <= ma_convergence <= 18.0
        and (ma5_distance is None or ma5_distance <= 3.5)
        and healthy_volume
    )
    active_high_weak_launch = bool(active and high_close and weak_launch)
    stale_quiet = bool(
        low_suction_days >= 6
        and not active
        and launch_bucket not in {"balanced_first_lift", "late_pullback_launch", "other_confirmed_launch"}
    )
    return {
        "active": active,
        "low_mid_close": low_mid_close,
        "high_close": high_close,
        "weak_launch": weak_launch,
        "active_low_mid_acceptance": active_low_mid_acceptance,
        "active_high_weak_launch": active_high_weak_launch,
        "stale_quiet": stale_quiet,
    }


def _top20_day_quality_profile(
    count: int,
    profile: str,
    active_ratio: float,
    low_mid_ratio: float,
    high_ratio: float,
    weak_launch_ratio: float,
    active_low_mid_ratio: float,
    notes: list[str],
    *,
    quality_score: float = 0.0,
) -> dict[str, Any]:
    return {
        "count": count,
        "profile": profile,
        "quality_score": round(quality_score, 4),
        "active_ratio": active_ratio,
        "low_mid_ratio": low_mid_ratio,
        "high_ratio": high_ratio,
        "weak_launch_ratio": weak_launch_ratio,
        "active_low_mid_ratio": active_low_mid_ratio,
        "notes": notes,
        "no_future_data": True,
    }


def _low_suction_buildup_quality(evidence: dict[str, Any]) -> dict[str, Any]:
    setup = str(evidence.get("entry_setup") or evidence.get("setup_primary") or evidence.get("setup_type") or "")
    family = str(evidence.get("setup_family") or "")
    low_suction_days = _float_or_none(evidence.get("low_suction_days")) or 0.0
    has_low_suction_context = (
        setup == "stealth_low_suction"
        or family in {"low_suction_buildup", "low_suction_first_lift", "dragon_low_suction_overlap"}
        or low_suction_days >= 3
    )
    if not has_low_suction_context:
        return {"eligible": False, "score": 0.0, "profile": "not_low_suction", "notes": []}

    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    ma5_distance = _float_or_none(evidence.get("ma5_distance_pct"))
    ma10_distance = _float_or_none(evidence.get("ma10_distance_pct"))
    ma20_distance = _float_or_none(evidence.get("ma20_distance_pct"))
    latest_change = _float_or_none(evidence.get("latest_change_pct"))
    risk_penalty = _float_or_none(evidence.get("risk_penalty")) or 0.0
    notes: list[str] = []
    score = 0.0

    if low_suction_days < 3:
        notes.append("低吸蓄势不足：连续低吸天数少于3天")
        return {"eligible": False, "score": 0.0, "profile": "insufficient_buildup_days", "notes": notes}
    if low_suction_days <= 5:
        score += 1.4
        notes.append("低吸蓄势质量：3-5天蓄势不过久")
    elif low_suction_days <= 7:
        score += 0.9
        notes.append("低吸蓄势质量：蓄势较充分")
    else:
        score += 0.2
        notes.append("低吸蓄势收敛：蓄势过久，权重降低")

    if ma_convergence is not None:
        if ma_convergence <= 2.5:
            score += 1.6
            notes.append("低吸蓄势质量：均线高度收敛")
        elif ma_convergence <= 4.0:
            score += 1.1
            notes.append("低吸蓄势质量：均线收敛良好")
        elif ma_convergence <= 5.5:
            score += 0.4
            notes.append("低吸蓄势质量：均线收敛可接受")
        else:
            notes.append("低吸蓄势不足：均线仍偏发散")
            return {"eligible": False, "score": 0.0, "profile": "loose_moving_averages", "notes": notes}

    distance_score = _low_suction_ma_distance_score(ma5_distance, ma10_distance, ma20_distance)
    if distance_score <= 0:
        notes.append("低吸蓄势不足：价格没有贴近关键均线承接")
        return {"eligible": False, "score": 0.0, "profile": "away_from_support_ma", "notes": notes}
    score += distance_score
    notes.append("低吸蓄势质量：价格贴近5/10/20日均线承接")

    if volume_ratio is not None:
        if 0.65 <= volume_ratio <= 1.15:
            score += 1.0
            notes.append("低吸蓄势质量：量能温和可控")
        elif 0.55 <= volume_ratio < 0.65 or 1.15 < volume_ratio <= 1.35:
            score += 0.3
            notes.append("低吸蓄势质量：量能基本可接受")
        else:
            notes.append("低吸蓄势不足：量能过弱或放量偏急")
            return {"eligible": False, "score": 0.0, "profile": "poor_buildup_volume", "notes": notes}

    if close_location is not None:
        if close_location <= 0.45:
            score += 0.5
            notes.append("低吸蓄势质量：收盘仍有分歧，不追高")
        elif close_location <= 0.68:
            score += 0.3
            notes.append("低吸蓄势质量：收盘位置不过热")
        elif close_location > 0.80:
            notes.append("低吸蓄势不足：收盘过高，容易变成追涨")
            return {"eligible": False, "score": 0.0, "profile": "high_close_not_buildup", "notes": notes}

    if latest_change is not None:
        if -1.5 <= latest_change <= 4.5:
            score += 0.4
            notes.append("低吸蓄势质量：当日涨跌幅仍在可低吸区")
        elif latest_change > 6.5:
            notes.append("低吸蓄势不足：当日涨幅过大")
            return {"eligible": False, "score": 0.0, "profile": "overheated_signal_day", "notes": notes}

    if evidence.get("key_support_break_risk") or evidence.get("volume_stall_risk"):
        notes.append("低吸蓄势不足：存在破位或放量滞涨风险")
        return {"eligible": False, "score": 0.0, "profile": "blocked_by_structure_risk", "notes": notes}
    if evidence.get("high_level_sideways_distribution_risk") and risk_penalty >= 8:
        notes.append("低吸蓄势不足：高位横盘派发风险较重")
        return {"eligible": False, "score": 0.0, "profile": "blocked_by_distribution_risk", "notes": notes}

    return {"eligible": True, "score": min(score, 6.0), "profile": "clean_low_suction_buildup", "notes": notes}


def _low_suction_ma_distance_score(
    ma5_distance: float | None,
    ma10_distance: float | None,
    ma20_distance: float | None,
) -> float:
    score = 0.0
    if ma5_distance is not None and -1.2 <= ma5_distance <= 2.8:
        score += 0.7
    if ma10_distance is not None and -1.5 <= ma10_distance <= 3.2:
        score += 0.6
    if ma20_distance is not None and -2.0 <= ma20_distance <= 4.0:
        score += 0.6
    return min(score, 1.5)


def _low_suction_buildup_weekly_relief(quality: dict[str, Any], evidence: dict[str, Any]) -> float:
    if not _has_weekly_top_fractal_risk(evidence):
        return 0.0
    if not quality["eligible"] or float(quality["score"]) < 4.2:
        return 0.0
    if evidence.get("key_support_break_risk") or evidence.get("volume_stall_risk"):
        return 0.0
    close_location = _float_or_none(evidence.get("close_location_in_range"))
    volume_ratio = _float_or_none(evidence.get("volume_ratio_5d_20d"))
    ma_convergence = _float_or_none(evidence.get("ma_convergence_pct"))
    if close_location is not None and close_location > 0.72:
        return 0.0
    if volume_ratio is not None and not (0.55 <= volume_ratio <= 1.25):
        return 0.0
    if ma_convergence is not None and ma_convergence > 4.5:
        return 0.0
    return 0.4


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
