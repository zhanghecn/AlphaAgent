"""Dynamic completeness rules for canonical concept-index history."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

CANONICAL_CONCEPT_INDEX_SOURCE = "eastmoney.board_kline"
MIN_ACTIVE_CONCEPTS = 300
MIN_COVERAGE_PCT = 90.0


@dataclass(frozen=True)
class ConceptDateCoverage:
    """Canonical concept-index completeness for one trading date."""

    trade_date: date
    actual_concepts: int
    expected_active_concepts: int
    coverage_pct: float
    qualifies: bool


def build_dynamic_concept_coverage(
    trading_dates: Sequence[date],
    count_rows: Sequence[tuple[date, int]],
    bounds: Sequence[tuple[str, date, date]],
    *,
    minimum_active_concepts: int = MIN_ACTIVE_CONCEPTS,
    minimum_coverage_pct: float = MIN_COVERAGE_PCT,
) -> tuple[ConceptDateCoverage, ...]:
    """Measure each date against concepts whose canonical series was then active."""

    _validate_thresholds(minimum_active_concepts, minimum_coverage_pct)
    actual_by_date = _index_daily_counts(count_rows)
    concept_bounds = _validate_concept_bounds(bounds)

    results = []
    for trade_date in sorted(set(trading_dates)):
        expected = sum(
            first_date <= trade_date <= last_date
            for first_date, last_date in concept_bounds.values()
        )
        actual = actual_by_date.get(trade_date, 0)
        if actual > expected:
            raise ValueError(
                "actual concept count exceeds expected active concepts "
                f"on {trade_date.isoformat()}: {actual} > {expected}"
            )
        coverage_pct = round(actual / expected * 100.0, 4) if expected else 0.0
        results.append(
            ConceptDateCoverage(
                trade_date=trade_date,
                actual_concepts=actual,
                expected_active_concepts=expected,
                coverage_pct=coverage_pct,
                qualifies=(
                    expected >= minimum_active_concepts
                    and coverage_pct >= minimum_coverage_pct
                ),
            )
        )
    return tuple(results)


def _validate_thresholds(
    minimum_active_concepts: int,
    minimum_coverage_pct: float,
) -> None:
    if minimum_active_concepts < 1:
        raise ValueError("minimum_active_concepts must be positive")
    if not 0.0 <= minimum_coverage_pct <= 100.0:
        raise ValueError("minimum_coverage_pct must be between 0 and 100")


def _index_daily_counts(
    count_rows: Sequence[tuple[date, int]],
) -> dict[date, int]:
    indexed: dict[date, int] = {}
    for trade_date, raw_count in count_rows:
        if trade_date in indexed:
            raise ValueError(f"duplicate count row for {trade_date.isoformat()}")
        count = int(raw_count)
        if count < 0:
            raise ValueError("actual concept count cannot be negative")
        indexed[trade_date] = count
    return indexed


def _validate_concept_bounds(
    bounds: Sequence[tuple[str, date, date]],
) -> dict[str, tuple[date, date]]:
    indexed: dict[str, tuple[date, date]] = {}
    for raw_sector_id, first_date, last_date in bounds:
        sector_id = str(raw_sector_id).strip()
        if not sector_id:
            raise ValueError("concept bound sector_id cannot be empty")
        if sector_id in indexed:
            raise ValueError(f"duplicate concept bound for {sector_id}")
        if first_date > last_date:
            raise ValueError(f"invalid concept bound for {sector_id}")
        indexed[sector_id] = (first_date, last_date)
    return indexed
