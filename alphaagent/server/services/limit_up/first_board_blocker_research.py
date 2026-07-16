"""Causal research for first-board days with no eligible candidate."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from math import isfinite
from statistics import mean

from alphaagent.server.services.limit_up.first_board_profitability import (
    combined_historical_win_rate,
)
from alphaagent.server.services.limit_up.live_evidence import (
    build_same_stock_first_board_d1_index,
)


def build_first_board_blocker_research_report(
    days: Sequence[Mapping[str, object]],
    *,
    history_window_days: int = 252,
    execution_start_time: str = "10:00:00",
    execution_end_time: str = "14:30:00",
) -> dict[str, object]:
    """Replay observation Top1 and isolated blocker removals in signal order."""

    if history_window_days <= 0:
        raise ValueError("history_window_days must be positive")
    if execution_start_time > execution_end_time:
        raise ValueError("execution_start_time must not exceed execution_end_time")
    ordered_days = sorted(days, key=lambda row: str(row.get("trade_date") or ""))
    research_days: list[dict[str, object]] = []
    candidate_occurrences: Counter[str] = Counter()
    blocker_days: dict[str, set[str]] = defaultdict(set)
    exact_candidate_combinations: Counter[str] = Counter()
    first_board_pool_day_count = 0

    for day in ordered_days:
        signal_date = str(day.get("trade_date") or "")[:10]
        candidates = _first_board_pool(day)
        if not signal_date or not candidates:
            continue
        first_board_pool_day_count += 1
        if any(str(row.get("decision") or "") == "eligible" for row in candidates):
            continue
        blocked = [
            row
            for row in candidates
            if str(row.get("decision") or "") == "blocked"
        ]
        if not blocked:
            continue
        stock_index = build_same_stock_first_board_d1_index(
            list(ordered_days),
            signal_date=_date_from_text(signal_date),
            history_window_days=history_window_days,
        )
        enriched = [
            _with_stock_evidence(
                candidate,
                signal_date=signal_date,
                validation_phase=str(
                    candidate.get("validation_phase")
                    or day.get("validation_phase")
                    or "unknown"
                ),
                stock_d1=stock_index.get(
                    str(candidate.get("vt_symbol") or ""),
                    {},
                ),
            )
            for candidate in blocked
        ]
        for candidate in enriched:
            blockers = _blockers(candidate)
            candidate_occurrences.update(blockers)
            for blocker in blockers:
                blocker_days[blocker].add(signal_date)
            exact_candidate_combinations[_combination_key(blockers)] += 1
        research_days.append(
            {
                "signal_date": signal_date,
                "candidates": enriched,
            }
        )

    selected: dict[str, list[dict[str, object]]] = {
        "first_observation": [],
        "first_post_10_observation": [],
    }
    top1_occurrences: Counter[str] = Counter()
    exact_top1_combinations: Counter[str] = Counter()
    for day in research_days:
        candidates = list(day["candidates"])
        first = _select_first_signal_group(candidates)
        if first is not None:
            selected["first_observation"].append(first)
        executable = _execution_window_candidates(
            candidates,
            execution_start_time,
            execution_end_time,
        )
        top1 = _select_first_signal_group(executable)
        if top1 is not None:
            selected["first_post_10_observation"].append(top1)
            blockers = _blockers(top1)
            top1_occurrences.update(blockers)
            exact_top1_combinations[_combination_key(blockers)] += 1

    blocker_names = sorted(candidate_occurrences)
    for blocker in blocker_names:
        variant_name = f"relax::{blocker}"
        selected[variant_name] = []
        for day in research_days:
            candidates = _execution_window_candidates(
                list(day["candidates"]),
                execution_start_time,
                execution_end_time,
            )
            newly_eligible = [
                candidate
                for candidate in candidates
                if _blockers(candidate)
                and not (set(_blockers(candidate)) - {blocker})
            ]
            selection = _select_first_signal_group(newly_eligible)
            if selection is not None:
                selected[variant_name].append(selection)

    no_eligible_day_count = len(research_days)
    variants = {
        name: {
            "relaxed_blocker": (
                name.removeprefix("relax::")
                if name.startswith("relax::")
                else None
            ),
            "summary": _performance_summary(rows),
            "phase_summaries": _phase_summaries(rows),
            "coverage": {
                "selection_day_count": len(rows),
                "no_selection_day_count": no_eligible_day_count - len(rows),
            },
            "selections": [_selection_row(row) for row in rows],
        }
        for name, rows in selected.items()
    }
    return {
        "status": "ready" if research_days else "insufficient_data",
        "mode": "prior_only_signal_time_causal_blocked_first_board",
        "ranking_contract": {
            "history_window_days": history_window_days,
            "candidate_availability": "signal_time_causal",
            "execution_start_time": execution_start_time,
            "execution_end_time": execution_end_time,
            "same_time_primary": "stock_gene_combined_win_rate_desc",
            "same_time_secondary": "signal_point_change_pct_desc",
            "later_replacement": False,
            "single_gate_relaxation": "remaining_blocker_set_must_be_empty",
        },
        "coverage": {
            "history_day_count": len(ordered_days),
            "first_board_pool_day_count": first_board_pool_day_count,
            "no_eligible_day_count": no_eligible_day_count,
            "post_10_observation_day_count": len(
                selected["first_post_10_observation"]
            ),
            "no_post_10_observation_day_count": no_eligible_day_count
            - len(selected["first_post_10_observation"]),
        },
        "blockers": {
            "candidate_occurrences": dict(sorted(candidate_occurrences.items())),
            "day_occurrences": {
                blocker: len(dates)
                for blocker, dates in sorted(blocker_days.items())
            },
            "top1_occurrences": dict(sorted(top1_occurrences.items())),
            "exact_candidate_combinations": dict(
                sorted(exact_candidate_combinations.items())
            ),
            "exact_top1_combinations": dict(
                sorted(exact_top1_combinations.items())
            ),
        },
        "variants": variants,
    }


def _first_board_pool(day: Mapping[str, object]) -> list[dict[str, object]]:
    portfolio = day.get("lane_portfolio")
    portfolio = portfolio if isinstance(portfolio, Mapping) else {}
    candidate_pool = portfolio.get("candidate_pool")
    candidate_pool = candidate_pool if isinstance(candidate_pool, Mapping) else {}
    rows = candidate_pool.get("first_board")
    rows = rows if isinstance(rows, list) else []
    return [
        dict(row)
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("lane") or "first_board") == "first_board"
    ]


def _with_stock_evidence(
    candidate: Mapping[str, object],
    *,
    signal_date: str,
    validation_phase: str,
    stock_d1: Mapping[str, object],
) -> dict[str, object]:
    touch_count = _integer(candidate.get("prior_touch_count_126"))
    seal_count = _integer(candidate.get("prior_limit_count_126"))
    seal_rate = _fraction_percentage(
        candidate.get("prior_seal_success_rate_126")
    )
    if seal_rate is None and touch_count > 0:
        seal_rate = round(seal_count / touch_count * 100, 4)
    d1_win_rate = _percentage(stock_d1.get("win_rate"))
    return {
        **dict(candidate),
        "ranking_signal_date": signal_date,
        "validation_phase": validation_phase,
        "stock_gene_touch_count": touch_count,
        "stock_gene_seal_count": seal_count,
        "stock_gene_seal_rate": seal_rate,
        "stock_d1_sample_count": _integer(stock_d1.get("sample_count")),
        "stock_d1_win_count": _integer(stock_d1.get("win_count")),
        "stock_d1_win_rate": d1_win_rate,
        "stock_d1_average_return_pct": _number(
            stock_d1.get("average_return_pct")
        ),
        "stock_gene_combined_win_rate": combined_historical_win_rate(
            d1_win_rate,
            seal_rate,
        ),
        "signal_change_pct": _signal_change_pct(candidate),
    }


def _execution_window_candidates(
    candidates: Sequence[Mapping[str, object]],
    start_time: str,
    end_time: str,
) -> list[dict[str, object]]:
    return [
        dict(candidate)
        for candidate in candidates
        if start_time
        <= str(candidate.get("signal_time") or "99:99:99")
        <= end_time
    ]


def _select_first_signal_group(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object] | None:
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda row: (
            str(row.get("signal_time") or "99:99:99"),
            _integer(row.get("pool_rank"), 1_000_000),
            str(row.get("vt_symbol") or ""),
        ),
    )
    if not ordered:
        return None
    first_time = str(ordered[0].get("signal_time") or "99:99:99")
    first_group = [
        row
        for row in ordered
        if str(row.get("signal_time") or "99:99:99") == first_time
    ]
    return min(first_group, key=_same_time_sort_key)


def _same_time_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    combined = _percentage(candidate.get("stock_gene_combined_win_rate"))
    change_pct = _number(candidate.get("signal_change_pct"))
    return (
        combined is None,
        -(combined or 0.0),
        change_pct is None,
        -(change_pct or 0.0),
        _integer(candidate.get("pool_rank"), 1_000_000),
        str(candidate.get("vt_symbol") or ""),
    )


def _selection_row(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "signal_date": str(candidate.get("ranking_signal_date") or ""),
        "signal_time": str(candidate.get("signal_time") or ""),
        "vt_symbol": str(candidate.get("vt_symbol") or ""),
        "name": str(candidate.get("name") or ""),
        "pool_rank": _integer(candidate.get("pool_rank")),
        "validation_phase": str(candidate.get("validation_phase") or "unknown"),
        "blockers": _blockers(candidate),
        "signal_change_pct": _rounded(candidate.get("signal_change_pct")),
        "stock_gene_seal_rate": _rounded(
            candidate.get("stock_gene_seal_rate")
        ),
        "stock_d1_sample_count": _integer(
            candidate.get("stock_d1_sample_count")
        ),
        "stock_d1_win_rate": _rounded(candidate.get("stock_d1_win_rate")),
        "stock_d1_average_return_pct": _rounded(
            candidate.get("stock_d1_average_return_pct")
        ),
        "stock_gene_combined_win_rate": _rounded(
            candidate.get("stock_gene_combined_win_rate")
        ),
    }


def _performance_summary(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    closed = [
        (candidate, value)
        for candidate in candidates
        if (value := _candidate_return(candidate)) is not None
    ]
    returns = [value for _, value in closed]
    positive = sum(value for value in returns if value > 0)
    negative = abs(sum(value for value in returns if value < 0))
    compounded_return, max_drawdown = _equity_metrics(closed)
    return {
        "selection_count": len(candidates),
        "trade_count": len(returns),
        "pending_count": len(candidates) - len(closed),
        "win_rate_pct": _rate(sum(value > 0 for value in returns), len(returns)),
        "average_return_pct": _average(returns),
        "compounded_return_pct": compounded_return,
        "max_drawdown_pct": max_drawdown,
        "seal_rate_pct": _rate(
            sum(
                bool(_mapping(candidate.get("outcome")).get("sealed"))
                for candidate, _ in closed
            ),
            len(closed),
        ),
        "hard_loss_rate_pct": _rate(
            sum(value <= -5 for value in returns),
            len(returns),
        ),
        "profit_factor_proxy": (
            round(positive / negative, 4) if negative > 0 else None
        ),
    }


def _phase_summaries(
    candidates: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    phases = sorted(
        {str(candidate.get("validation_phase") or "unknown") for candidate in candidates}
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


def _equity_metrics(
    closed: Sequence[tuple[Mapping[str, object], float]],
) -> tuple[float | None, float | None]:
    if not closed:
        return None, None
    returns_by_date: dict[str, list[float]] = defaultdict(list)
    for candidate, value in closed:
        returns_by_date[str(candidate.get("ranking_signal_date") or "")].append(value)
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for signal_date in sorted(returns_by_date):
        equity *= 1 + max(mean(returns_by_date[signal_date]), -99.0) / 100
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, (equity / peak - 1) * 100)
    return round((equity - 1) * 100, 4), round(max_drawdown, 4)


def _blockers(candidate: Mapping[str, object]) -> list[str]:
    value = candidate.get("blockers")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return list(dict.fromkeys(str(item) for item in value if str(item)))


def _combination_key(blockers: Sequence[str]) -> str:
    return " + ".join(sorted(blockers)) or "none"


def _signal_change_pct(candidate: Mapping[str, object]) -> float | None:
    value = _number(candidate.get("change_pct"))
    if value is not None:
        return value
    return _number(_mapping(candidate.get("path_prefix")).get("last_pct"))


def _candidate_return(candidate: Mapping[str, object]) -> float | None:
    return _number(_mapping(candidate.get("outcome")).get("next_close_return_pct"))


def _date_from_text(value: str) -> date:
    return date.fromisoformat(value)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _number(value: object) -> float | None:
    try:
        number = float(value) if value not in (None, "", "-") else None
    except (TypeError, ValueError):
        return None
    return number if number is not None and isfinite(number) else None


def _integer(value: object, default: int = 0) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _percentage(value: object) -> float | None:
    number = _number(value)
    return number if number is not None and 0 <= number <= 100 else None


def _fraction_percentage(value: object) -> float | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    if number <= 1:
        return round(number * 100, 4)
    return round(number, 4) if number <= 100 else None


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _average(values: Sequence[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _rounded(value: object) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None
