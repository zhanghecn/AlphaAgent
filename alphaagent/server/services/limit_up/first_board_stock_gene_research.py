"""Prior-only stock-specific first-board gene ranking research."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import groupby
from math import isfinite
from statistics import mean, median


@dataclass(frozen=True)
class _StockD1Event:
    signal_day_index: int
    result_date: str
    won: bool
    return_pct: float


def combined_stock_gene_win_rate(
    seal_gene_rate: object,
    d1_win_rate: object,
) -> float | None:
    """Return stock seal-gene rate times its first-board D+1 win rate."""

    seal_rate = _percentage(seal_gene_rate)
    premium_rate = _percentage(d1_win_rate)
    if seal_rate is None or premium_rate is None:
        return None
    return round(seal_rate * premium_rate / 100, 4)


def attach_prior_stock_gene_evidence_to_orders(
    days: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
    *,
    history_window_days: int = 252,
) -> list[dict[str, object]]:
    """Attach same-stock evidence available strictly before each order date."""

    return _attach_prior_d1_evidence_to_orders(
        days,
        orders,
        history_window_days=history_window_days,
        include_failed_seals=False,
    )


def attach_prior_all_touch_d1_evidence_to_orders(
    days: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
    *,
    history_window_days: int = 252,
) -> list[dict[str, object]]:
    """Attach prior D+1 evidence for every touch, including failed seals."""

    return _attach_prior_d1_evidence_to_orders(
        days,
        orders,
        history_window_days=history_window_days,
        include_failed_seals=True,
    )


def _attach_prior_d1_evidence_to_orders(
    days: Sequence[Mapping[str, object]],
    orders: Sequence[Mapping[str, object]],
    *,
    history_window_days: int,
    include_failed_seals: bool,
) -> list[dict[str, object]]:
    """Attach one causal same-stock D+1 evidence definition to orders."""

    if history_window_days <= 0:
        raise ValueError("history_window_days must be positive")
    ordered_days = sorted(days, key=lambda row: str(row.get("trade_date") or ""))
    enriched = [dict(order) for order in orders]
    first_board_orders: dict[str, list[tuple[int, dict[str, object]]]] = (
        defaultdict(list)
    )
    for index, order in enumerate(enriched):
        lane = str(order.get("lane") or order.get("board_lane") or "")
        signal_date = _date_text(
            order.get("signal_date") or order.get("entry_date")
        )
        if lane == "first_board" and signal_date is not None:
            first_board_orders[signal_date].append((index, order))

    pending = _pending_first_board_events(ordered_days)
    pending_dates = sorted(pending)
    pending_index = 0
    stock_history: dict[str, list[_StockD1Event]] = defaultdict(list)
    processed: set[int] = set()
    for day_index, day in enumerate(ordered_days):
        signal_date = _date_text(day.get("trade_date"))
        if signal_date is None:
            continue
        while (
            pending_index < len(pending_dates)
            and pending_dates[pending_index] < signal_date
        ):
            result_date = pending_dates[pending_index]
            for source_day_index, candidate in pending[result_date]:
                event = _stock_d1_event(
                    candidate,
                    source_day_index=source_day_index,
                    result_date=result_date,
                    include_failed_seals=include_failed_seals,
                )
                symbol = str(candidate.get("vt_symbol") or "")
                if event is not None and symbol:
                    stock_history[symbol].append(event)
            pending_index += 1
        for order_index, order in first_board_orders.get(signal_date, []):
            order.update(
                _d1_evidence(
                    order,
                    stock_history.get(str(order.get("vt_symbol") or ""), []),
                    current_day_index=day_index,
                    history_window_days=history_window_days,
                    include_failed_seals=include_failed_seals,
                )
            )
            processed.add(order_index)

    for order_index, order in enumerate(enriched):
        lane = str(order.get("lane") or order.get("board_lane") or "")
        if lane != "first_board" or order_index in processed:
            continue
        order.update(
            _d1_evidence(
                order,
                [],
                current_day_index=0,
                history_window_days=history_window_days,
                include_failed_seals=include_failed_seals,
            )
        )
    return enriched


def rank_stock_gene_candidates(
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Rank ready stock-specific evidence, retaining earlier signals on ties."""

    return sorted(
        (dict(candidate) for candidate in candidates),
        key=_combined_sort_key,
    )


def select_causal_first_board_candidate(
    candidates: Sequence[Mapping[str, object]],
    *,
    min_d1_samples: int,
    min_combined_rate: float,
) -> dict[str, object] | None:
    """Select the first passing signal-time group without later replacement."""

    if min_d1_samples <= 0:
        raise ValueError("min_d1_samples must be positive")
    threshold = _percentage(min_combined_rate)
    if threshold is None:
        raise ValueError("min_combined_rate must be between 0 and 100")
    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=lambda row: (
            str(row.get("signal_time") or "99:99:99"),
            str(row.get("vt_symbol") or ""),
        ),
    )
    for _, same_time in groupby(
        ordered,
        key=lambda row: str(row.get("signal_time") or "99:99:99"),
    ):
        passing: list[dict[str, object]] = []
        for row in same_time:
            rate = _percentage(row.get("stock_gene_combined_win_rate"))
            if (
                _integer(row.get("stock_d1_sample_count"), 0) >= min_d1_samples
                and rate is not None
                and rate >= threshold
            ):
                passing.append(row)
        if passing:
            return rank_stock_gene_candidates(passing)[0]
    return None


def select_first_signal_group_candidate(
    candidates: Sequence[Mapping[str, object]],
    *,
    min_d1_samples: int,
    min_combined_rate: float,
) -> dict[str, object] | None:
    """Apply the gate only to the first signal-time group of the day."""

    ordered = sorted(
        (dict(candidate) for candidate in candidates),
        key=_causal_arrival_sort_key,
    )
    if not ordered:
        return None
    first_time = str(ordered[0].get("signal_time") or "99:99:99")
    first_group = [
        row
        for row in ordered
        if str(row.get("signal_time") or "99:99:99") == first_time
    ]
    return select_causal_first_board_candidate(
        first_group,
        min_d1_samples=min_d1_samples,
        min_combined_rate=min_combined_rate,
    )


def build_first_board_stock_gene_ranking_report(
    days: Sequence[Mapping[str, object]],
    *,
    history_window_days: int = 252,
    min_d1_samples: int = 5,
    top_n: int = 1,
) -> dict[str, object]:
    """Compare daily TopN ranks using only matured same-stock evidence."""

    if history_window_days <= 0:
        raise ValueError("history_window_days must be positive")
    if min_d1_samples <= 0:
        raise ValueError("min_d1_samples must be positive")
    if top_n <= 0:
        raise ValueError("top_n must be positive")

    ordered_days = sorted(days, key=lambda row: str(row.get("trade_date") or ""))
    pending = _pending_first_board_events(ordered_days)
    pending_dates = sorted(pending)
    pending_index = 0
    stock_history: dict[str, list[_StockD1Event]] = defaultdict(list)
    selected: dict[str, list[dict[str, object]]] = {
        name: [] for name in _variant_sort_keys()
    }
    eligible_candidate_count = 0
    qualified_candidate_count = 0
    qualified_combined_rates: list[float] = []
    qualified_d1_sample_counts: list[float] = []
    eligible_days: set[str] = set()
    evaluated_days: set[str] = set()

    for day_index, day in enumerate(ordered_days):
        signal_date = _date_text(day.get("trade_date"))
        if signal_date is None:
            continue
        while (
            pending_index < len(pending_dates)
            and pending_dates[pending_index] < signal_date
        ):
            result_date = pending_dates[pending_index]
            for source_day_index, candidate in pending[result_date]:
                event = _stock_d1_event(
                    candidate,
                    source_day_index=source_day_index,
                    result_date=result_date,
                )
                symbol = str(candidate.get("vt_symbol") or "")
                if event is not None and symbol:
                    stock_history[symbol].append(event)
            pending_index += 1

        candidates = _eligible_first_board_candidates(day)
        if not candidates:
            continue
        eligible_days.add(signal_date)
        eligible_candidate_count += len(candidates)
        qualified: list[dict[str, object]] = []
        for candidate in candidates:
            evidence = _stock_evidence(
                candidate,
                stock_history.get(str(candidate.get("vt_symbol") or ""), []),
                current_day_index=day_index,
                history_window_days=history_window_days,
                min_d1_samples=min_d1_samples,
            )
            enriched = {
                **candidate,
                **evidence,
                "ranking_signal_date": signal_date,
                "validation_phase": str(
                    candidate.get("validation_phase")
                    or day.get("validation_phase")
                    or "unknown"
                ),
            }
            if evidence["stock_gene_combined_win_rate"] is not None:
                qualified.append(enriched)
                qualified_combined_rates.append(
                    float(evidence["stock_gene_combined_win_rate"])
                )
                qualified_d1_sample_counts.append(
                    float(evidence["stock_d1_sample_count"])
                )
        if not qualified:
            continue
        evaluated_days.add(signal_date)
        qualified_candidate_count += len(qualified)
        selection_count = min(top_n, len(qualified))
        for name, sort_key in _variant_sort_keys().items():
            selected[name].extend(
                sorted(qualified, key=sort_key)[:selection_count]
            )

    variants = {
        name: {
            "summary": _performance_summary(rows),
            "phase_summaries": _phase_summaries(rows),
            "selections": [_selection_row(row) for row in rows],
        }
        for name, rows in selected.items()
    }
    return {
        "status": "invalid_for_execution" if evaluated_days else "insufficient_data",
        "mode": "daily_candidate_availability_lookahead_proxy",
        "execution_valid": False,
        "invalid_reason": (
            "The completed daily candidate set is ranked before buying at an "
            "earlier signal time, so later candidate availability leaks backward."
        ),
        "ranking_contract": {
            "history_window_days": history_window_days,
            "minimum_d1_samples": min_d1_samples,
            "top_n": top_n,
            "primary": "stock_gene_combined_win_rate_desc",
            "secondary": "signal_time_asc",
            "d1_label": "next_close_net_return_gt_zero",
        },
        "coverage": {
            "history_day_count": len(ordered_days),
            "eligible_candidate_count": eligible_candidate_count,
            "sample_qualified_candidate_count": qualified_candidate_count,
            "eligible_day_count": len(eligible_days),
            "evaluated_day_count": len(evaluated_days),
            "no_pick_day_count": len(eligible_days - evaluated_days),
            "combined_rate_distribution": _distribution(
                qualified_combined_rates
            ),
            "d1_sample_count_distribution": _distribution(
                qualified_d1_sample_counts
            ),
        },
        "variants": variants,
    }


def build_causal_first_board_recommendation_report(
    days: Sequence[Mapping[str, object]],
    *,
    history_window_days: int = 252,
    min_d1_samples: int = 5,
    thresholds: Sequence[float] = (45.0, 50.0, 55.0),
) -> dict[str, object]:
    """Replay first-board gates in signal-time order without later replacement."""

    if history_window_days <= 0:
        raise ValueError("history_window_days must be positive")
    if min_d1_samples <= 0:
        raise ValueError("min_d1_samples must be positive")
    threshold_values = tuple(_validated_thresholds(thresholds))
    if not threshold_values:
        raise ValueError("thresholds must not be empty")

    ordered_days = sorted(days, key=lambda row: str(row.get("trade_date") or ""))
    pending = _pending_first_board_events(ordered_days)
    pending_dates = sorted(pending)
    pending_index = 0
    stock_history: dict[str, list[_StockD1Event]] = defaultdict(list)
    variant_names = [
        "first_eligible",
        "first_sampled",
        *[_first_threshold_variant_name(value) for value in threshold_values],
        *[_threshold_variant_name(value) for value in threshold_values],
    ]
    selected: dict[str, list[dict[str, object]]] = {
        name: [] for name in variant_names
    }
    eligible_candidate_count = 0
    eligible_days: set[str] = set()
    sample_qualified_candidate_count = 0

    for day_index, day in enumerate(ordered_days):
        signal_date = _date_text(day.get("trade_date"))
        if signal_date is None:
            continue
        while (
            pending_index < len(pending_dates)
            and pending_dates[pending_index] < signal_date
        ):
            result_date = pending_dates[pending_index]
            for source_day_index, candidate in pending[result_date]:
                event = _stock_d1_event(
                    candidate,
                    source_day_index=source_day_index,
                    result_date=result_date,
                )
                symbol = str(candidate.get("vt_symbol") or "")
                if event is not None and symbol:
                    stock_history[symbol].append(event)
            pending_index += 1

        candidates = _eligible_first_board_candidates(day)
        if not candidates:
            continue
        eligible_days.add(signal_date)
        eligible_candidate_count += len(candidates)
        enriched: list[dict[str, object]] = []
        for candidate in candidates:
            evidence = _stock_evidence(
                candidate,
                stock_history.get(str(candidate.get("vt_symbol") or ""), []),
                current_day_index=day_index,
                history_window_days=history_window_days,
                min_d1_samples=1,
            )
            row = {
                **candidate,
                **evidence,
                "ranking_signal_date": signal_date,
                "validation_phase": str(
                    candidate.get("validation_phase")
                    or day.get("validation_phase")
                    or "unknown"
                ),
            }
            enriched.append(row)
            if evidence["stock_d1_sample_count"] >= min_d1_samples:
                sample_qualified_candidate_count += 1

        first_eligible = sorted(enriched, key=_causal_arrival_sort_key)[0]
        selected["first_eligible"].append(
            _with_recommendation_gate(first_eligible, "first_eligible")
        )
        first_sampled = select_causal_first_board_candidate(
            enriched,
            min_d1_samples=min_d1_samples,
            min_combined_rate=0.0,
        )
        if first_sampled is not None:
            selected["first_sampled"].append(
                _with_recommendation_gate(
                    first_sampled,
                    "first_sampled",
                    min_d1_samples=min_d1_samples,
                )
            )
        for threshold in threshold_values:
            first_variant_name = _first_threshold_variant_name(threshold)
            first_recommendation = select_first_signal_group_candidate(
                enriched,
                min_d1_samples=min_d1_samples,
                min_combined_rate=threshold,
            )
            if first_recommendation is not None:
                selected[first_variant_name].append(
                    _with_recommendation_gate(
                        first_recommendation,
                        first_variant_name,
                        min_d1_samples=min_d1_samples,
                        min_combined_rate=threshold,
                    )
                )
            variant_name = _threshold_variant_name(threshold)
            recommendation = select_causal_first_board_candidate(
                enriched,
                min_d1_samples=min_d1_samples,
                min_combined_rate=threshold,
            )
            if recommendation is not None:
                selected[variant_name].append(
                    _with_recommendation_gate(
                        recommendation,
                        variant_name,
                        min_d1_samples=min_d1_samples,
                        min_combined_rate=threshold,
                    )
                )

    variants = {
        name: {
            "summary": _performance_summary(rows),
            "phase_summaries": _phase_summaries(rows),
            "coverage": {
                "recommendation_day_count": len(rows),
                "no_recommendation_day_count": len(eligible_days) - len(rows),
            },
            "selections": [_selection_row(row) for row in rows],
        }
        for name, rows in selected.items()
    }
    return {
        "status": "ready" if eligible_days else "insufficient_data",
        "mode": "prior_only_signal_time_causal_first_board_gate",
        "ranking_contract": {
            "history_window_days": history_window_days,
            "minimum_d1_samples": min_d1_samples,
            "thresholds": list(threshold_values),
            "candidate_availability": "signal_time_causal",
            "daily_lock": "first_passing_signal_time_group",
            "later_replacement": False,
            "d1_label": "next_close_net_return_gt_zero",
        },
        "coverage": {
            "history_day_count": len(ordered_days),
            "eligible_candidate_count": eligible_candidate_count,
            "sample_qualified_candidate_count": (
                sample_qualified_candidate_count
            ),
            "eligible_day_count": len(eligible_days),
        },
        "variants": variants,
    }


def _combined_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    rate = _percentage(candidate.get("stock_gene_combined_win_rate"))
    return (
        rate is None,
        -(rate or 0.0),
        str(candidate.get("signal_time") or "99:99:99"),
        str(candidate.get("vt_symbol") or ""),
    )


def _causal_arrival_sort_key(
    candidate: Mapping[str, object],
) -> tuple[object, ...]:
    return (
        str(candidate.get("signal_time") or "99:99:99"),
        _integer(candidate.get("pool_rank"), 1_000_000),
        str(candidate.get("vt_symbol") or ""),
    )


def _validated_thresholds(values: Sequence[float]) -> list[float]:
    thresholds: list[float] = []
    for value in values:
        threshold = _percentage(value)
        if threshold is None:
            raise ValueError("thresholds must be between 0 and 100")
        if threshold not in thresholds:
            thresholds.append(threshold)
    return thresholds


def _threshold_variant_name(value: float) -> str:
    label = str(int(value)) if value.is_integer() else str(value).replace(".", "_")
    return f"combined_{label}"


def _first_threshold_variant_name(value: float) -> str:
    label = str(int(value)) if value.is_integer() else str(value).replace(".", "_")
    return f"first_combined_{label}"


def _with_recommendation_gate(
    candidate: Mapping[str, object],
    gate_name: str,
    *,
    min_d1_samples: int | None = None,
    min_combined_rate: float | None = None,
) -> dict[str, object]:
    reasons = ["first_passing_signal_time_group"]
    if min_d1_samples is not None:
        reasons.append(f"stock_d1_samples_gte_{min_d1_samples}")
    if min_combined_rate is not None:
        reasons.append(f"combined_rate_gte_{min_combined_rate:g}")
    return {
        **dict(candidate),
        "recommendation_gate": gate_name,
        "recommendation_reasons": reasons,
        "minimum_d1_samples": min_d1_samples,
        "minimum_combined_rate": min_combined_rate,
    }


def _pending_first_board_events(
    days: Sequence[Mapping[str, object]],
) -> dict[str, list[tuple[int, dict[str, object]]]]:
    pending: dict[str, list[tuple[int, dict[str, object]]]] = defaultdict(list)
    for day_index, day in enumerate(days):
        for candidate in _first_board_pool(day):
            result_date = _date_text(candidate.get("result_date"))
            if result_date is not None:
                pending[result_date].append((day_index, candidate))
    return dict(pending)


def _stock_d1_event(
    candidate: Mapping[str, object],
    *,
    source_day_index: int,
    result_date: str,
    include_failed_seals: bool = False,
) -> _StockD1Event | None:
    outcome = _mapping(candidate.get("outcome"))
    return_pct = _number(outcome.get("next_close_return_pct"))
    if (
        not bool(outcome.get("touched"))
        or (not include_failed_seals and not bool(outcome.get("sealed")))
        or return_pct is None
    ):
        return None
    return _StockD1Event(
        signal_day_index=source_day_index,
        result_date=result_date,
        won=return_pct > 0,
        return_pct=return_pct,
    )


def _d1_evidence(
    candidate: Mapping[str, object],
    events: Sequence[_StockD1Event],
    *,
    current_day_index: int,
    history_window_days: int,
    include_failed_seals: bool,
) -> dict[str, object]:
    if not include_failed_seals:
        return _stock_evidence(
            candidate,
            events,
            current_day_index=current_day_index,
            history_window_days=history_window_days,
            min_d1_samples=1,
        )
    cutoff = current_day_index - history_window_days
    recent = [event for event in events if event.signal_day_index >= cutoff]
    sample_count = len(recent)
    win_count = sum(event.won for event in recent)
    return {
        "stock_all_touch_d1_sample_count": sample_count,
        "stock_all_touch_d1_win_count": win_count,
        "stock_all_touch_d1_win_rate": _rate(win_count, sample_count),
        "stock_all_touch_d1_average_return_pct": _average(
            [event.return_pct for event in recent]
        ),
    }


def _stock_evidence(
    candidate: Mapping[str, object],
    events: Sequence[_StockD1Event],
    *,
    current_day_index: int,
    history_window_days: int,
    min_d1_samples: int,
) -> dict[str, object]:
    cutoff = current_day_index - history_window_days
    recent = [event for event in events if event.signal_day_index >= cutoff]
    sample_count = len(recent)
    win_count = sum(event.won for event in recent)
    d1_win_rate = _rate(win_count, sample_count)
    seal_count = _integer(candidate.get("prior_limit_count_126"), 0)
    touch_count = _integer(candidate.get("prior_touch_count_126"), 0)
    seal_rate = _fraction_percentage(
        candidate.get("prior_seal_success_rate_126")
    )
    if seal_rate is None:
        seal_rate = _rate(seal_count, touch_count)
    combined_rate = (
        combined_stock_gene_win_rate(seal_rate, d1_win_rate)
        if sample_count >= min_d1_samples
        else None
    )
    return {
        "stock_gene_touch_count": touch_count,
        "stock_gene_seal_count": seal_count,
        "stock_gene_seal_rate": seal_rate,
        "stock_d1_sample_count": sample_count,
        "stock_d1_win_count": win_count,
        "stock_d1_win_rate": d1_win_rate,
        "stock_d1_average_return_pct": _average(
            [event.return_pct for event in recent]
        ),
        "stock_gene_combined_win_rate": combined_rate,
    }


def _variant_sort_keys():
    return {
        "baseline": _baseline_sort_key,
        "gene_only": lambda row: _rate_sort_key(row, "stock_gene_seal_rate"),
        "d1_only": lambda row: _rate_sort_key(row, "stock_d1_win_rate"),
        "combined": _combined_sort_key,
    }


def _baseline_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _integer(candidate.get("pool_rank"), 1_000_000),
        str(candidate.get("signal_time") or "99:99:99"),
        str(candidate.get("vt_symbol") or ""),
    )


def _rate_sort_key(
    candidate: Mapping[str, object],
    field: str,
) -> tuple[object, ...]:
    rate = _percentage(candidate.get(field))
    return (
        rate is None,
        -(rate or 0.0),
        str(candidate.get("signal_time") or "99:99:99"),
        str(candidate.get("vt_symbol") or ""),
    )


def _first_board_pool(day: Mapping[str, object]) -> list[dict[str, object]]:
    portfolio = _mapping(day.get("lane_portfolio"))
    candidate_pool = _mapping(portfolio.get("candidate_pool"))
    rows = candidate_pool.get("first_board")
    rows = rows if isinstance(rows, list) else []
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _eligible_first_board_candidates(
    day: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        candidate
        for candidate in _first_board_pool(day)
        if str(candidate.get("lane") or "first_board") == "first_board"
        and str(candidate.get("decision") or "") == "eligible"
    ]


def _selection_row(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "signal_date": str(candidate.get("ranking_signal_date") or ""),
        "vt_symbol": str(candidate.get("vt_symbol") or ""),
        "name": str(candidate.get("name") or ""),
        "signal_time": str(candidate.get("signal_time") or ""),
        "pool_rank": _integer(candidate.get("pool_rank"), 0),
        "validation_phase": str(candidate.get("validation_phase") or "unknown"),
        "recommendation_gate": str(
            candidate.get("recommendation_gate") or ""
        ),
        "recommendation_reasons": list(
            candidate.get("recommendation_reasons") or []
        ),
        "minimum_d1_samples": _integer(
            candidate.get("minimum_d1_samples"), 0
        ),
        "minimum_combined_rate": _rounded(
            candidate.get("minimum_combined_rate")
        ),
        "stock_gene_touch_count": _integer(
            candidate.get("stock_gene_touch_count"), 0
        ),
        "stock_gene_seal_count": _integer(
            candidate.get("stock_gene_seal_count"), 0
        ),
        "stock_gene_seal_rate": _rounded(
            candidate.get("stock_gene_seal_rate")
        ),
        "stock_d1_sample_count": _integer(
            candidate.get("stock_d1_sample_count"), 0
        ),
        "stock_d1_win_count": _integer(candidate.get("stock_d1_win_count"), 0),
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
    closed_candidates = [candidate for candidate, _ in closed]
    positive = sum(value for value in returns if value > 0)
    negative = abs(sum(value for value in returns if value < 0))
    compounded_return, maximum_drawdown = _daily_equity_metrics(
        closed_candidates
    )
    return {
        "selection_count": len(candidates),
        "trade_count": len(returns),
        "pending_count": len(candidates) - len(closed_candidates),
        "signal_day_count": len(
            {
                str(row.get("ranking_signal_date") or "")
                for row in closed_candidates
            }
        ),
        "win_rate_pct": _rate(sum(value > 0 for value in returns), len(returns)),
        "average_return_pct": _average(returns),
        "compounded_return_pct": compounded_return,
        "max_drawdown_pct": maximum_drawdown,
        "seal_rate_pct": _rate(
            sum(
                bool(_mapping(row.get("outcome")).get("sealed"))
                for row in closed_candidates
            ),
            len(closed_candidates),
        ),
        "hard_loss_rate_pct": _rate(
            sum(value <= -5 for value in returns),
            len(returns),
        ),
        "profit_factor_proxy": (
            round(positive / negative, 4)
            if negative > 0
            else None
        ),
    }


def _daily_equity_metrics(
    candidates: Sequence[Mapping[str, object]],
) -> tuple[float | None, float | None]:
    returns_by_date: dict[str, list[float]] = defaultdict(list)
    for candidate in candidates:
        signal_date = str(candidate.get("ranking_signal_date") or "")
        value = _candidate_return(candidate)
        if signal_date and value is not None:
            returns_by_date[signal_date].append(value)
    if not returns_by_date:
        return None, None
    equity = 1.0
    peak = 1.0
    maximum_drawdown = 0.0
    for signal_date in sorted(returns_by_date):
        daily_return = mean(returns_by_date[signal_date])
        equity *= 1 + max(daily_return, -99.0) / 100
        peak = max(peak, equity)
        maximum_drawdown = min(maximum_drawdown, (equity / peak - 1) * 100)
    return round((equity - 1) * 100, 4), round(maximum_drawdown, 4)


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


def _candidate_return(candidate: Mapping[str, object]) -> float | None:
    return _number(_mapping(candidate.get("outcome")).get("next_close_return_pct"))


def _percentage(value: object) -> float | None:
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


def _fraction_percentage(value: object) -> float | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    if number <= 1:
        return round(number * 100, 4)
    return round(number, 4) if number <= 100 else None


def _date_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _integer(value: object, default: int) -> int:
    number = _number(value)
    return int(number) if number is not None else default


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 4) if denominator else None


def _average(values: Sequence[float]) -> float | None:
    return round(mean(values), 4) if values else None


def _rounded(value: object) -> float | None:
    number = _number(value)
    return round(number, 4) if number is not None else None


def _distribution(values: Sequence[float]) -> dict[str, object]:
    if not values:
        return {
            "count": 0,
            "distinct_count": 0,
            "minimum": None,
            "median": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "distinct_count": len(set(values)),
        "minimum": round(min(values), 4),
        "median": round(median(values), 4),
        "maximum": round(max(values), 4),
    }
