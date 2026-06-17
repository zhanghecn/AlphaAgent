"""Scoring helpers for portfolio backtests."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

from alphaagent.server.services.backtest.schemas import BacktestParams, ScoreContext
from alphaagent.server.services.quant import screening_payloads
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
        return is_executable_entry_signal(score, params.min_entry_score)
    if score.total_score < screening_payloads.effective_entry_score_threshold(score, params.min_entry_score):
        return False
    return True


def is_executable_entry_signal(score, min_entry_score: float) -> bool:
    return bool(
        getattr(score, "entry_signal", False)
        and not screening_payloads.failed_entry_rules(score, min_entry_score)
    )
