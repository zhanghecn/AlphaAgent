"""Pure point-in-time calculations for realtime concept resonance."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any

from alphaagent.server.services.limit_up.domain import (
    is_eligible_main_board,
    main_board_limit_price,
)


STYLE_CONCEPT_KEYWORDS = (
    "MSCI",
    "中证",
    "沪深300",
    "上证50",
    "深证100",
    "大盘股",
    "中盘股",
    "小盘股",
    "成长",
    "价值",
    "风格",
    "热股",
    "融资融券",
    "沪股通",
    "深股通",
    "昨日",
    "近期",
    "成份股",
    "成分股",
    "机构重仓",
    "基金重仓",
    "年报",
    "季报",
    "预增",
    "扭亏",
    "高振幅",
    "高换手",
)
CONCEPT_WARMING_MAX_PERCENTILE = 0.05
CONCEPT_LAUNCH_MAX_PERCENTILE = 0.03
CONCEPT_MIN_COVERAGE_RATIO = 0.90
CONCEPT_EBB_FAILED_RATE = 0.35
_CONCEPT_STATES = {"launch": 0, "warming": 1, "observe": 2, "ebb": 3, "unavailable": 4}


def is_execution_concept(name: str) -> bool:
    """Exclude broad-index, style, and after-the-fact labels from execution."""

    value = str(name or "").strip().upper()
    return bool(value) and not any(keyword.upper() in value for keyword in STYLE_CONCEPT_KEYWORDS)


def build_membership_index(
    rows: Sequence[Mapping[str, object]],
    *,
    snapshot_date: object,
) -> dict[str, object]:
    """Build immutable symbol/concept indexes from one prior-day version."""

    by_symbol: dict[str, list[str]] = defaultdict(list)
    by_concept: dict[str, dict[str, object]] = {}
    for row in rows:
        symbol = str(row.get("vt_symbol") or "").strip().upper()
        concept_id = str(row.get("sector_id") or "").strip()
        concept_name = str(row.get("sector_name") or concept_id).strip()
        sector_type = str(row.get("sector_type") or "concept").strip().lower()
        stock_name = str(row.get("stock_name") or "")
        if sector_type not in {"concept", "theme", "industry"}:
            continue
        if not symbol or not concept_id or not is_execution_concept(concept_name):
            continue
        if not is_eligible_main_board(symbol, stock_name):
            continue
        by_symbol[symbol].append(concept_id)
        concept = by_concept.setdefault(
            concept_id,
            {
                "concept_id": concept_id,
                "concept_name": concept_name,
                "sector_type": sector_type,
                "members": set(),
            },
        )
        members = concept["members"]
        if isinstance(members, set):
            members.add(symbol)

    return {
        "snapshot_date": str(snapshot_date)[:10],
        "by_symbol": {
            symbol: sorted(set(concept_ids))
            for symbol, concept_ids in by_symbol.items()
        },
        "by_concept": by_concept,
    }


def aggregate_concept_strength(
    quotes: Sequence[Mapping[str, object]],
    membership: Mapping[str, object],
    *,
    captured_at: datetime,
    history_by_concept: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
) -> list[dict[str, object]]:
    """Aggregate a complete quote frame using only current and earlier data."""

    quote_by_symbol = {
        str(quote.get("vt_symbol") or "").upper(): quote
        for quote in quotes
        if quote.get("vt_symbol") and _optional_float(quote.get("change_pct")) is not None
    }
    concepts = membership.get("by_concept")
    if not isinstance(concepts, Mapping):
        return []
    history = history_by_concept or {}
    rows = [
        _aggregate_one_concept(
            concept,
            quote_by_symbol,
            captured_at=captured_at,
            history=history.get(str(concept_id), ()),
        )
        for concept_id, concept in concepts.items()
        if isinstance(concept, Mapping)
    ]
    return rank_concepts(rows)


def _aggregate_one_concept(
    concept: Mapping[str, object],
    quote_by_symbol: Mapping[str, Mapping[str, object]],
    *,
    captured_at: datetime,
    history: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    members = {str(value).upper() for value in concept.get("members") or set()}
    observed = [quote_by_symbol[symbol] for symbol in members if symbol in quote_by_symbol]
    changes = [_float(quote.get("change_pct")) for quote in observed]
    turnovers = [max(_float(quote.get("turnover")), 0.0) for quote in observed]
    weighted_change = _weighted_change(observed, changes)
    states = [str(quote.get("state") or "").lower() for quote in observed]
    distances = [_distance_to_limit(quote) for quote in observed]
    touched = [
        bool(quote.get("first_limit_time"))
        or state in {"sealed", "resealed", "failed"}
        or (distance is not None and distance <= 0.02)
        for quote, state, distance in zip(observed, states, distances, strict=True)
    ]
    sealed = [
        state in {"sealed", "resealed"}
        or (state != "failed" and distance is not None and distance <= 0.02)
        for state, distance in zip(states, distances, strict=True)
    ]
    failed = [
        state == "failed" or (was_touched and not is_sealed)
        for state, was_touched, is_sealed in zip(states, touched, sealed, strict=True)
    ]
    turnover = sum(turnovers)
    current_median = median(changes) if changes else 0.0
    row: dict[str, object] = {
        "concept_id": str(concept.get("concept_id") or ""),
        "concept_name": str(concept.get("concept_name") or concept.get("concept_id") or ""),
        "sector_type": str(concept.get("sector_type") or "concept"),
        "captured_at": captured_at.isoformat(),
        "member_count": len(members),
        "observed_count": len(observed),
        "coverage_ratio": round(len(observed) / len(members), 6) if members else 0.0,
        "average_change_pct": round(mean(changes), 6) if changes else 0.0,
        "median_change_pct": round(current_median, 6),
        "weighted_change_pct": round(weighted_change, 6),
        "rise_count": sum(change > 0 for change in changes),
        "fall_count": sum(change < 0 for change in changes),
        "flat_count": sum(change == 0 for change in changes),
        "rise_ratio": round(sum(change > 0 for change in changes) / len(changes), 6) if changes else 0.0,
        "strong_3_count": sum(change >= 3 for change in changes),
        "strong_5_count": sum(change >= 5 for change in changes),
        "strong_7_count": sum(change >= 7 for change in changes),
        "near_limit_count": sum(distance is not None and distance <= 1 for distance in distances),
        "touched_count": sum(touched),
        "sealed_count": sum(sealed),
        "failed_count": sum(failed),
        "turnover": round(turnover, 2),
        "radar_symbols": sorted(
            str(quote.get("vt_symbol") or "").upper()
            for quote in observed
            if _float(quote.get("change_pct")) >= 5
        ),
        "near_limit_symbols": sorted(
            str(quote.get("vt_symbol") or "").upper()
            for quote, distance in zip(observed, distances, strict=True)
            if distance is not None and distance <= 1
        ),
    }
    for minutes in (1, 3, 5):
        previous = _history_frame(history, captured_at - timedelta(minutes=minutes))
        row[f"change_acceleration_{minutes}m"] = _delta(
            current_median,
            previous,
            "median_change_pct",
        )
        row[f"diffusion_acceleration_{minutes}m"] = _delta(
            float(row["strong_5_count"]),
            previous,
            "strong_5_count",
        )
        row[f"turnover_acceleration_{minutes}m"] = _delta(
            turnover,
            previous,
            "turnover",
        )
    return row


def rank_concepts(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    """Assign deterministic cross-sectional scores, ranks, and states."""

    ranked_rows = [dict(row) for row in rows]
    if not ranked_rows:
        return []
    components = {
        "median_change_pct": 20.0,
        "weighted_change_pct": 10.0,
        "rise_ratio": 12.0,
        "strong_5_ratio": 16.0,
        "near_limit_ratio": 14.0,
        "change_acceleration_3m": 10.0,
        "turnover_acceleration_3m": 8.0,
        "seal_quality": 10.0,
    }
    for row in ranked_rows:
        observed_count = max(int(row.get("observed_count") or 0), 1)
        touched_count = max(int(row.get("touched_count") or 0), 1)
        row["strong_5_ratio"] = _float(row.get("strong_5_count")) / observed_count
        row["near_limit_ratio"] = _float(row.get("near_limit_count")) / observed_count
        row["seal_quality"] = (
            _float(row.get("sealed_count")) - _float(row.get("failed_count"))
        ) / touched_count

    component_scores = {
        name: _cross_section_scores(ranked_rows, name)
        for name in components
    }
    for index, row in enumerate(ranked_rows):
        score = sum(
            weight * component_scores[name][index]
            for name, weight in components.items()
        )
        if int(row.get("strong_5_count") or 0) <= 1 and int(row.get("observed_count") or 0) >= 5:
            score -= 10.0
        row["strength_score"] = round(min(max(score, 0.0), 100.0), 4)

    ranked_rows.sort(
        key=lambda row: (
            -_float(row.get("strength_score")),
            str(row.get("concept_id") or ""),
        )
    )
    total = len(ranked_rows)
    for rank, row in enumerate(ranked_rows, start=1):
        row["strength_rank"] = rank
        row["strength_percentile"] = round(rank / total, 6)
        row["concept_state"] = concept_state(row)
    return ranked_rows


def concept_state(row: Mapping[str, object]) -> str:
    if _float(row.get("coverage_ratio")) < CONCEPT_MIN_COVERAGE_RATIO:
        return "unavailable"
    touched = int(row.get("touched_count") or 0)
    failed_rate = _float(row.get("failed_count")) / max(touched, 1)
    if touched >= 3 and failed_rate > CONCEPT_EBB_FAILED_RATE:
        return "ebb"
    percentile = _float(row.get("strength_percentile"), default=1.0)
    if (
        percentile <= CONCEPT_LAUNCH_MAX_PERCENTILE
        and int(row.get("strong_5_count") or 0) >= 3
        and (
            int(row.get("near_limit_count") or 0) >= 1
            or int(row.get("strong_7_count") or 0) >= 2
        )
    ):
        return "launch"
    if (
        percentile <= CONCEPT_WARMING_MAX_PERCENTILE
        and int(row.get("strong_5_count") or 0) >= 2
        and _float(row.get("change_acceleration_3m")) > 0
    ):
        return "warming"
    return "observe"


def attach_candidate_concepts(
    candidates: Sequence[dict[str, object]],
    snapshot: Mapping[str, object],
) -> None:
    """Attach the strongest valid concept and point-in-time leader rank."""

    membership = snapshot.get("membership")
    membership = membership if isinstance(membership, Mapping) else {}
    by_symbol = membership.get("by_symbol")
    by_symbol = by_symbol if isinstance(by_symbol, Mapping) else {}
    concepts = snapshot.get("concepts_by_id")
    concepts = concepts if isinstance(concepts, Mapping) else {}
    age_seconds = _snapshot_age(snapshot)
    quality = snapshot.get("data_quality")
    trigger_allowed = (
        isinstance(quality, Mapping) and quality.get("trigger_allowed") is True
    )

    candidates_by_concept: dict[str, list[dict[str, object]]] = defaultdict(list)
    selected_concept_by_symbol: dict[str, str] = {}
    for candidate in candidates:
        symbol = str(candidate.get("vt_symbol") or "").upper()
        concept_ids = by_symbol.get(symbol)
        concept_ids = concept_ids if isinstance(concept_ids, Sequence) and not isinstance(concept_ids, str) else []
        available = [
            concepts[concept_id]
            for concept_id in concept_ids
            if concept_id in concepts and isinstance(concepts[concept_id], Mapping)
        ]
        if not available:
            _attach_unavailable_concept(candidate, age_seconds, trigger_allowed)
            continue
        selected = min(available, key=_concept_selection_key)
        concept_id = str(selected.get("concept_id") or "")
        selected_concept_by_symbol[symbol] = concept_id
        for available_concept in available:
            available_id = str(available_concept.get("concept_id") or "")
            if available_id:
                candidates_by_concept[available_id].append(candidate)
        _copy_concept_evidence(candidate, selected, age_seconds, trigger_allowed)

    leader_ranks: dict[tuple[str, str], int] = {}
    for concept_id, concept_candidates in candidates_by_concept.items():
        ordered = sorted(concept_candidates, key=_leader_sort_key)
        for rank, candidate in enumerate(ordered, start=1):
            symbol = str(candidate.get("vt_symbol") or "").upper()
            leader_ranks[(concept_id, symbol)] = rank
    for candidate in candidates:
        symbol = str(candidate.get("vt_symbol") or "").upper()
        concept_id = selected_concept_by_symbol.get(symbol)
        if concept_id:
            candidate["concept_leader_rank"] = leader_ranks.get((concept_id, symbol))


def replay_radar_concepts(
    frames: Sequence[Mapping[str, object]],
    membership: Mapping[str, object],
    *,
    signal_at: str | datetime,
) -> dict[str, object]:
    """Replay only frames at or before a signal time without filling gaps."""

    cutoff = _as_datetime(signal_at)
    latest_quotes: dict[str, Mapping[str, object]] = {}
    future_frame_count = 0
    for frame in frames:
        captured_at = _as_datetime(frame.get("captured_at"))
        if captured_at > cutoff:
            future_frame_count += 1
            continue
        items = frame.get("items")
        if isinstance(items, Sequence) and not isinstance(items, (str, bytes)):
            rows = [item for item in items if isinstance(item, Mapping)]
        else:
            rows = [frame]
        for quote in rows:
            symbol = str(quote.get("vt_symbol") or "").upper()
            if symbol:
                latest_quotes[symbol] = quote
    concepts = aggregate_concept_strength(
        list(latest_quotes.values()),
        membership,
        captured_at=cutoff,
        history_by_concept={},
    )
    return {
        "membership_snapshot_date": membership.get("snapshot_date"),
        "signal_at": cutoff.isoformat(),
        "future_frame_count": future_frame_count,
        "concepts": {
            str(row["concept_id"]): {
                **row,
                "radar_5_count": row["strong_5_count"],
                "within_1pct_count": row["near_limit_count"],
            }
            for row in concepts
        },
    }


def _weighted_change(
    observed: Sequence[Mapping[str, object]],
    changes: Sequence[float],
) -> float:
    weights = [max(_float(quote.get("float_market_cap")), 0.0) for quote in observed]
    total_weight = sum(weights)
    if total_weight <= 0:
        return mean(changes) if changes else 0.0
    return sum(change * weight for change, weight in zip(changes, weights, strict=True)) / total_weight


def _distance_to_limit(quote: Mapping[str, object]) -> float | None:
    explicit = _optional_float(quote.get("distance_to_limit_pct"))
    if explicit is not None:
        return max(explicit, 0.0)
    last_price = _optional_float(quote.get("last_price"))
    limit_price = _optional_float(quote.get("limit_price"))
    previous_close = _optional_float(quote.get("previous_close"))
    if limit_price is None and previous_close is not None and previous_close > 0:
        limit_price = main_board_limit_price(previous_close)
    if last_price is not None and limit_price is not None and limit_price > 0:
        return max((limit_price - last_price) / limit_price * 100, 0.0)
    change_pct = _optional_float(quote.get("change_pct"))
    return max(10.0 - change_pct, 0.0) if change_pct is not None else None


def _history_frame(
    history: Sequence[Mapping[str, object]],
    target: datetime,
) -> Mapping[str, object] | None:
    eligible = [
        row
        for row in history
        if row.get("captured_at") and _as_datetime(row.get("captured_at")) <= target
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: _as_datetime(row.get("captured_at")))


def _delta(
    current: float,
    previous: Mapping[str, object] | None,
    field: str,
) -> float | None:
    if previous is None or _optional_float(previous.get(field)) is None:
        return None
    return round(current - _float(previous.get(field)), 6)


def _cross_section_scores(
    rows: Sequence[Mapping[str, object]],
    field: str,
) -> list[float]:
    values = [_float(row.get(field)) for row in rows]
    total = len(values)
    return [sum(other <= value for other in values) / total for value in values]


def _concept_selection_key(concept: Mapping[str, object]) -> tuple[object, ...]:
    return (
        _CONCEPT_STATES.get(str(concept.get("concept_state") or "unavailable"), 5),
        int(concept.get("strength_rank") or 1_000_000),
        -_float(concept.get("strength_score")),
        str(concept.get("concept_id") or ""),
    )


def _leader_sort_key(candidate: Mapping[str, object]) -> tuple[object, ...]:
    distance = _optional_float(candidate.get("distance_to_limit_pct"))
    return (
        -_float(candidate.get("change_pct")),
        distance if distance is not None else 100.0,
        -_float(candidate.get("turnover")),
        str(candidate.get("vt_symbol") or ""),
    )


def _copy_concept_evidence(
    candidate: dict[str, object],
    concept: Mapping[str, object],
    age_seconds: float | None,
    trigger_allowed: bool,
) -> None:
    candidate.update(
        {
            "concept_id": concept.get("concept_id"),
            "concept_name": concept.get("concept_name"),
            "concept_state": concept.get("concept_state") or "unavailable",
            "concept_strength_score": concept.get("strength_score"),
            "concept_strength_rank": concept.get("strength_rank"),
            "concept_strength_percentile": concept.get("strength_percentile"),
            "concept_coverage_ratio": concept.get("coverage_ratio"),
            "concept_strong_5_count": concept.get("strong_5_count"),
            "concept_near_limit_count": concept.get("near_limit_count"),
            "concept_sealed_count": concept.get("sealed_count"),
            "concept_failed_count": concept.get("failed_count"),
            "concept_change_acceleration_3m": concept.get("change_acceleration_3m"),
            "concept_turnover_acceleration_3m": concept.get("turnover_acceleration_3m"),
            "concept_snapshot_age_seconds": age_seconds,
            "concept_trigger_allowed": trigger_allowed,
        }
    )


def _attach_unavailable_concept(
    candidate: dict[str, object],
    age_seconds: float | None,
    trigger_allowed: bool,
) -> None:
    candidate.update(
        {
            "concept_id": None,
            "concept_name": None,
            "concept_state": "unavailable",
            "concept_leader_rank": None,
            "concept_coverage_ratio": 0.0,
            "concept_snapshot_age_seconds": age_seconds,
            "concept_trigger_allowed": trigger_allowed,
        }
    )


def _snapshot_age(snapshot: Mapping[str, object]) -> float | None:
    quality = snapshot.get("data_quality")
    if isinstance(quality, Mapping):
        return _optional_float(quality.get("age_seconds"))
    return None


def _as_datetime(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("point-in-time values must include a timezone")
    return parsed


def _optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float(value: object, *, default: float = 0.0) -> float:
    parsed = _optional_float(value)
    return default if parsed is None else parsed
