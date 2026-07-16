"""Transparent profitability evidence and ranking for live first boards."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite


def combined_historical_win_rate(
    d1_money_effect_win_rate: object,
    seal_success_rate: object,
) -> float | None:
    """Return P(seal after touch) * P(D+1 net profit after seal)."""

    d1_rate = _bounded_percentage(d1_money_effect_win_rate)
    seal_rate = _bounded_percentage(seal_success_rate)
    if d1_rate is None or seal_rate is None:
        return None
    return round(d1_rate * seal_rate / 100, 4)


def rank_first_board_signals(
    signals: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Reorder only first-board slots by win rate and current change."""

    copied = [dict(signal) for signal in signals]
    ranked_first_boards = iter(
        sorted(
            (signal for signal in copied if _is_first_board(signal)),
            key=first_board_signal_sort_key,
        )
    )
    return [
        next(ranked_first_boards) if _is_first_board(signal) else signal
        for signal in copied
    ]


def first_board_signal_sort_key(
    signal: Mapping[str, object],
) -> tuple[object, ...]:
    evidence = signal.get("historical_evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    win_rate = _bounded_percentage(evidence.get("historical_win_rate"))
    change_pct = _number(signal.get("change_pct"))
    return (
        win_rate is None,
        -(win_rate or 0.0),
        change_pct is None,
        -(change_pct or 0.0),
        str(signal.get("vt_symbol") or ""),
    )


def build_first_board_profitability_ranking_report(
    days: Sequence[Mapping[str, object]],
    *,
    top_n: int = 2,
    min_analogs: int = 60,
) -> dict[str, object]:
    """Compare equal-size daily first-board selections with prior-only evidence."""

    if top_n <= 0:
        raise ValueError("top_n must be positive")
    if min_analogs <= 0:
        raise ValueError("min_analogs must be positive")

    from alphaagent.server.services.limit_up import history_engine

    ordered_days = sorted(days, key=lambda day: str(day.get("trade_date") or ""))
    baseline_candidates: list[dict[str, object]] = []
    profitability_candidates: list[dict[str, object]] = []
    candidate_count = 0
    candidate_day_count = 0
    fully_scored_day_count = 0
    excluded_incomplete_day_count = 0
    baseline_selections: list[dict[str, object]] = []
    profitability_selections: list[dict[str, object]] = []
    changed_days = 0

    for day in ordered_days:
        signal_date = _date_value(day.get("trade_date"))
        if signal_date is None:
            continue
        candidates = _eligible_first_board_candidates(day)
        if not candidates:
            continue
        candidate_day_count += 1
        candidate_count += len(candidates)
        if any(_candidate_return(candidate) is None for candidate in candidates):
            excluded_incomplete_day_count += 1
            continue

        analog_index = history_engine.build_analog_index(
            ordered_days,
            result_before=signal_date,
        )
        enriched: list[dict[str, object]] = []
        for candidate in candidates:
            analog = history_engine.resolve_analog(
                analog_index,
                candidate,
                min_analogs=min_analogs,
            )
            enriched.append(
                {
                    **candidate,
                    "board_lane": "first_board",
                    "change_pct": _signal_change_pct(candidate),
                    "historical_evidence": analog,
                    "ranking_signal_date": signal_date.isoformat(),
                }
            )
        if all(
            _number(
                _mapping(candidate.get("historical_evidence")).get(
                    "historical_win_rate"
                )
            )
            is not None
            for candidate in enriched
        ):
            fully_scored_day_count += 1

        selection_count = min(top_n, len(enriched))
        baseline = sorted(enriched, key=_baseline_sort_key)[:selection_count]
        profitability = rank_first_board_signals(enriched)[:selection_count]
        baseline_candidates.extend(baseline)
        profitability_candidates.extend(profitability)
        baseline_rows = [_selection_row(candidate) for candidate in baseline]
        profitability_rows = [
            _selection_row(candidate) for candidate in profitability
        ]
        baseline_selections.extend(baseline_rows)
        profitability_selections.extend(profitability_rows)
        if {row["vt_symbol"] for row in baseline_rows} != {
            row["vt_symbol"] for row in profitability_rows
        }:
            changed_days += 1

    baseline_summary = _performance_summary(baseline_candidates)
    profitability_summary = _performance_summary(profitability_candidates)
    return {
        "status": "ready" if baseline_candidates else "insufficient_data",
        "mode": "prior_only_daily_candidate_ranking_proxy",
        "ranking_contract": {
            "primary": "historical_win_rate_desc",
            "secondary": "signal_change_pct_desc",
            "historical_win_rate_formula": (
                "P(seal_after_touch) * P(D+1_close_net_profit_after_seal)"
            ),
            "top_n": top_n,
            "minimum_analogs": min_analogs,
        },
        "baseline": baseline_summary,
        "profitability_ranking": profitability_summary,
        "delta": _summary_delta(baseline_summary, profitability_summary),
        "phase_summaries": {
            "baseline": _phase_summaries(baseline_candidates),
            "profitability_ranking": _phase_summaries(
                profitability_candidates
            ),
        },
        "coverage": {
            "history_day_count": len(ordered_days),
            "candidate_day_count": candidate_day_count,
            "candidate_count": candidate_count,
            "evaluated_day_count": len(
                {
                    str(candidate.get("ranking_signal_date") or "")
                    for candidate in baseline_candidates
                }
            ),
            "fully_scored_day_count": fully_scored_day_count,
            "excluded_incomplete_day_count": excluded_incomplete_day_count,
            "changed_day_count": changed_days,
        },
        "selections": {
            "baseline": baseline_selections,
            "profitability_ranking": profitability_selections,
        },
        "limitations": [
            (
                "历史账本没有过去每15秒的临板候选快照；按全天已触发候选重排是"
                "日候选代理，不是实盘等价回放。"
            ),
            (
                "排序证据只读取结果日早于信号日的成熟样本；D日封板和D+1结果"
                "只用于评价，不进入当日排序。"
            ),
            (
                "D+1赚钱效应和本报告收益使用日收盘净收益代理；正式现金账户"
                "仍按D+1 14:30价格及缺失时收盘代理单独核对。"
            ),
            "涨停价成交缺少Tick/L2排队证据，不能解释为可实盘成交收益。",
        ],
    }


def _eligible_first_board_candidates(
    day: Mapping[str, object],
) -> list[dict[str, object]]:
    portfolio = _mapping(day.get("lane_portfolio"))
    pools = _mapping(portfolio.get("candidate_pool"))
    candidates = pools.get("first_board")
    candidates = candidates if isinstance(candidates, Sequence) else []
    return [
        dict(candidate)
        for candidate in candidates
        if isinstance(candidate, Mapping)
        and str(candidate.get("lane") or "first_board") == "first_board"
        and str(candidate.get("decision") or "") == "eligible"
    ]


def _baseline_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _integer(candidate.get("pool_rank"), 1_000_000),
        str(candidate.get("signal_time") or "99:99:99"),
        str(candidate.get("vt_symbol") or ""),
    )


def _signal_change_pct(candidate: Mapping[str, object]) -> float | None:
    change_pct = _number(candidate.get("change_pct"))
    if change_pct is not None:
        return change_pct
    return _number(_mapping(candidate.get("path_prefix")).get("last_pct"))


def _candidate_return(candidate: Mapping[str, object]) -> float | None:
    outcome = _mapping(candidate.get("outcome"))
    return _number(outcome.get("next_close_return_pct"))


def _selection_row(candidate: Mapping[str, object]) -> dict[str, object]:
    evidence = _mapping(candidate.get("historical_evidence"))
    return {
        "signal_date": str(candidate.get("ranking_signal_date") or ""),
        "vt_symbol": str(candidate.get("vt_symbol") or ""),
        "pool_rank": _integer(candidate.get("pool_rank"), 0),
        "historical_win_rate": _rounded(evidence.get("historical_win_rate")),
        "d1_money_effect_win_rate": _rounded(
            evidence.get("d1_money_effect_win_rate")
        ),
        "seal_success_rate": _rounded(evidence.get("seal_success_rate")),
        "signal_change_pct": _rounded(candidate.get("change_pct")),
    }


def _performance_summary(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    returns = [
        value
        for candidate in candidates
        if (value := _candidate_return(candidate)) is not None
    ]
    sealed = [
        candidate
        for candidate in candidates
        if bool(_mapping(candidate.get("outcome")).get("sealed"))
    ]
    sealed_returns = [
        value
        for candidate in sealed
        if (value := _candidate_return(candidate)) is not None
    ]
    compounded_return, maximum_drawdown = _daily_equity_metrics(candidates)
    return {
        "trade_count": len(returns),
        "signal_day_count": len(
            {
                str(candidate.get("ranking_signal_date") or "")
                for candidate in candidates
            }
        ),
        "win_rate_pct": _rate(sum(value > 0 for value in returns), len(returns)),
        "average_return_pct": _average(returns),
        "compounded_return_pct": compounded_return,
        "max_drawdown_pct": maximum_drawdown,
        "seal_rate_pct": _rate(len(sealed), len(candidates)),
        "sealed_d1_win_rate_pct": _rate(
            sum(value > 0 for value in sealed_returns),
            len(sealed_returns),
        ),
    }


def _daily_equity_metrics(
    candidates: Sequence[Mapping[str, object]],
) -> tuple[float | None, float | None]:
    returns_by_date: dict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        value = _candidate_return(candidate)
        signal_date = str(candidate.get("ranking_signal_date") or "")
        if value is not None and signal_date:
            returns_by_date[signal_date].append(value)
    if not returns_by_date:
        return None, None
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for signal_date in sorted(returns_by_date):
        daily_return = sum(returns_by_date[signal_date]) / len(
            returns_by_date[signal_date]
        )
        equity *= 1 + max(daily_return, -99.0) / 100
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, (equity / peak - 1) * 100)
    return round((equity - 1) * 100, 4), round(maximum_drawdown, 4)


def _phase_summaries(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    phases = sorted(
        {
            str(candidate.get("validation_phase") or "unknown")
            for candidate in candidates
        }
    )
    return {
        phase: _performance_summary(
            [
                candidate
                for candidate in candidates
                if str(candidate.get("validation_phase") or "unknown") == phase
            ]
        )
        for phase in phases
    }


def _summary_delta(
    baseline: Mapping[str, object],
    profitability: Mapping[str, object],
) -> dict[str, object]:
    return {
        "win_rate_pct_points": _difference(
            profitability.get("win_rate_pct"), baseline.get("win_rate_pct")
        ),
        "average_return_pct_points": _difference(
            profitability.get("average_return_pct"),
            baseline.get("average_return_pct"),
        ),
        "compounded_return_pct_points": _difference(
            profitability.get("compounded_return_pct"),
            baseline.get("compounded_return_pct"),
        ),
        "max_drawdown_pct_points": _difference(
            profitability.get("max_drawdown_pct"),
            baseline.get("max_drawdown_pct"),
        ),
        "seal_rate_pct_points": _difference(
            profitability.get("seal_rate_pct"), baseline.get("seal_rate_pct")
        ),
    }


def _difference(left: object, right: object) -> float | None:
    left_number = _number(left)
    right_number = _number(right)
    if left_number is None or right_number is None:
        return None
    return round(left_number - right_number, 4)


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _average(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object, default: int) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _rounded(value: object) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _date_value(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _is_first_board(signal: Mapping[str, object]) -> bool:
    lane = str(signal.get("board_lane") or "")
    if lane:
        return lane == "first_board"
    level = _number(signal.get("board_level"))
    return level is not None and level <= 1


def _bounded_percentage(value: object) -> float | None:
    number = _number(value)
    if number is None or not 0 <= number <= 100:
        return None
    return number


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None
