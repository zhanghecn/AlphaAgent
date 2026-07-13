"""Point-in-time historical evidence for current live limit-up signals."""

from __future__ import annotations

from datetime import date
from typing import Mapping

from alphaagent.market.cache import TTLCache
from alphaagent.server.services.limit_up import history_engine, history_repository

_ANALOG_CACHE = TTLCache(max_items=8)
_CONFIDENCE_POINTS = {"low": 4.0, "medium": 7.0, "high": 10.0}


def tbox_score(analog: Mapping[str, object]) -> float:
    """Score prior-only board-trade evidence on a transparent 0-100 scale."""

    win_rate = _number(analog.get("smoothed_win_rate"))
    average_return = _number(analog.get("average_return_pct"))
    hard_loss_rate = _number(analog.get("hard_loss_rate"))
    seal_after_touch = _number(analog.get("seal_after_touch_rate"))
    score = sum(
        (
            _scaled_points(win_rate, 40.0, 65.0, 35.0),
            _scaled_points(average_return, -1.0, 3.0, 25.0),
            _scaled_points(
                25.0 - hard_loss_rate if hard_loss_rate is not None else None,
                0.0,
                25.0,
                20.0,
            ),
            _scaled_points(seal_after_touch, 40.0, 80.0, 10.0),
            _CONFIDENCE_POINTS.get(str(analog.get("confidence") or ""), 0.0),
        )
    )
    return round(min(max(score, 0.0), 100.0), 2)


def clear_live_evidence_cache() -> None:
    _ANALOG_CACHE.clear()


def load_history_analog_index(
    signal_date: date,
) -> Mapping[tuple[object, ...], object]:
    coverage = history_repository.history_coverage(history_engine.HISTORY_STRATEGY_VERSION)
    cache_key = ":".join(
        (
            history_engine.HISTORY_STRATEGY_VERSION,
            str(coverage.get("persisted_end") or "empty"),
            str(coverage.get("persisted_days") or 0),
            signal_date.isoformat(),
        )
    )

    def load() -> dict[tuple[object, ...], object]:
        replays = history_repository.load_history_range(
            history_engine.HISTORY_STRATEGY_VERSION,
            None,
            signal_date,
        )
        return history_engine.build_analog_index(
            replays,
            result_before=signal_date,
        )

    return _ANALOG_CACHE.get_or_set(cache_key, 3600, load)


def attach_historical_evidence(
    snapshot: Mapping[str, object],
    *,
    analog_index: Mapping[tuple[object, ...], object] | None = None,
) -> dict[str, object]:
    """Attach prior-only analog statistics to every live recommendation lane."""

    signal_date = _date_value(snapshot.get("trade_date"))
    if signal_date is None:
        return dict(snapshot)
    resolved_index = (
        analog_index
        if analog_index is not None
        else load_history_analog_index(signal_date)
    )
    candidates = snapshot.get("candidates")
    candidates = candidates if isinstance(candidates, list) else []
    by_symbol = {
        str(row.get("vt_symbol") or ""): row
        for row in candidates
        if isinstance(row, Mapping) and row.get("vt_symbol")
    }
    recommendations = snapshot.get("recommendations")
    recommendations = dict(recommendations) if isinstance(recommendations, Mapping) else {}
    lanes = recommendations.get("lanes")
    lanes = lanes if isinstance(lanes, Mapping) else {}
    market_context = snapshot.get("market_context")
    market_context = market_context if isinstance(market_context, Mapping) else {}
    enriched_lanes: dict[str, list[dict[str, object]]] = {}
    for lane, raw_signals in lanes.items():
        signals = raw_signals if isinstance(raw_signals, list) else []
        enriched_lanes[str(lane)] = [
            _with_evidence(
                signal,
                by_symbol.get(str(signal.get("vt_symbol") or ""), {}),
                market_context,
                str(lane),
                signal_date,
                resolved_index,
            )
            for signal in signals
            if isinstance(signal, Mapping)
        ]
    recommendations["lanes"] = enriched_lanes
    return {**dict(snapshot), "recommendations": recommendations}


def _with_evidence(
    signal: Mapping[str, object],
    candidate: Mapping[str, object],
    market_context: Mapping[str, object],
    lane: str,
    signal_date: date,
    analog_index: Mapping[tuple[object, ...], object],
) -> dict[str, object]:
    entry_mode, target_board, feature_scope = _route_context(signal, candidate, lane)
    analog_candidate = {
        "entry_mode": entry_mode,
        "target_board": target_board,
        "known_at_signal": _known_at_signal(candidate, market_context, feature_scope),
    }
    analog = history_engine.resolve_analog(analog_index, analog_candidate)
    effective = int(analog.get("effective_sample_count") or 0)
    veto_reasons = _risk_veto_reasons(analog)
    evidence = {
        "status": "ready" if effective else "insufficient",
        "entry_mode": entry_mode,
        "feature_scope": feature_scope,
        "as_of_date": signal_date.isoformat(),
        "risk_vetoed": bool(veto_reasons),
        "risk_veto_reasons": veto_reasons,
        "tbox_score": tbox_score(analog),
        **analog,
    }
    result = {**dict(signal), "historical_evidence": evidence}
    if veto_reasons and str(result.get("action") or "") in {"buy_now", "next_auction"}:
        result["action"] = "pass"
        result["execution_state"] = "cancelled"
        result["reason"] = "历史证据否决：" + "；".join(veto_reasons)
    return result


def _risk_veto_reasons(analog: Mapping[str, object]) -> list[str]:
    effective = int(_number(analog.get("effective_sample_count")) or 0)
    if effective < 60:
        return []
    reasons: list[str] = []
    average = _number(analog.get("average_return_pct"))
    win_rate = _number(analog.get("smoothed_win_rate"))
    hard_loss = _number(analog.get("hard_loss_rate"))
    if average is not None and average <= 0:
        reasons.append(f"{effective}笔同路径平均净收益{average:.2f}%")
    if win_rate is not None and win_rate < 40:
        reasons.append(f"历史胜率仅{win_rate:.1f}%")
    if hard_loss is not None and hard_loss >= 20:
        reasons.append(f"硬亏损率{hard_loss:.1f}%")
    return reasons


def _route_context(
    signal: Mapping[str, object],
    candidate: Mapping[str, object],
    lane: str,
) -> tuple[str, int, str]:
    board_level = max(int(_number(signal.get("board_level")) or 1), 1)
    if lane == "next_auction":
        return "next_auction", board_level, "next_auction_gap_pending"
    if lane == "tail":
        return "tail", board_level, "point_in_time_match"
    if str(signal.get("entry_kind") or "") == "auction":
        mode = "next_auction" if bool(candidate.get("previous_limit_up")) else "auction"
        return mode, board_level, "point_in_time_match"
    return "sweep", board_level, "point_in_time_match"


def _known_at_signal(
    candidate: Mapping[str, object],
    market_context: Mapping[str, object],
    feature_scope: str,
) -> dict[str, object]:
    sentiment = market_context.get("sentiment")
    sentiment = sentiment if isinstance(sentiment, Mapping) else {}
    auction_gap = None if feature_scope == "next_auction_gap_pending" else _number(
        candidate.get("auction_gap_pct")
    )
    return {
        "auction_gap_pct": auction_gap,
        "prior_change_pct": _number(candidate.get("prior_change_pct")),
        "prior_turnover_rate": _number(candidate.get("prior_turnover_rate")),
        "prior_amount_ratio_5d": _number(candidate.get("prior_amount_ratio_5d")),
        "prior_market_phase": _history_market_phase(str(sentiment.get("phase") or "")),
    }


def _history_market_phase(phase: str) -> str:
    if phase in {"mainrise", "uptrend", "climax"}:
        return "broad_rise"
    if phase == "repair":
        return "repair"
    if phase == "divergence":
        return "mixed"
    if phase in {"ice", "ebb"}:
        return "retreat"
    return "unknown"


def _date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _number(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None


def _scaled_points(
    value: float | None,
    floor: float,
    ceiling: float,
    weight: float,
) -> float:
    if value is None or ceiling <= floor:
        return 0.0
    ratio = (value - floor) / (ceiling - floor)
    return min(max(ratio, 0.0), 1.0) * weight
