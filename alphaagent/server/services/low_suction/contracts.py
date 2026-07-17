"""Immutable contracts shared by low-suction research stages."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

STRICT_MIN_TRADE_DAYS = 720
STRICT_MIN_CALENDAR_DAYS = 1_095
STRICT_MIN_MEMBERSHIP_COVERAGE_PCT = 90.0
STRICT_MIN_CONCEPT_BAR_COVERAGE_PCT = 90.0
STRICT_MIN_CLOSED_TRADES = 300
STRICT_MAX_DRAWDOWN_PCT = 10.0

CONCEPT_SECTOR_TYPES = ("concept", "theme")
EVIDENCE_LEVELS = ("strict", "daily_discovery", "membership_proxy", "invalid")


@dataclass(frozen=True)
class DatasetCoverage:
    """Coverage and provenance for one research input."""

    rows: int
    entities: int
    trade_days: int
    start: date | None
    end: date | None
    coverage_pct: float
    mode: str
    sources: tuple[str, ...] = ()

    @property
    def calendar_span_days(self) -> int:
        if self.start is None or self.end is None:
            return 0
        return max((self.end - self.start).days, 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "rows": self.rows,
            "entities": self.entities,
            "trade_days": self.trade_days,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "calendar_span_days": self.calendar_span_days,
            "coverage_pct": self.coverage_pct,
            "mode": self.mode,
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class PairCoverage:
    """Completeness for event-specific stock/date minute paths."""

    total_pairs: int
    covered_pairs: int

    def __post_init__(self) -> None:
        if self.total_pairs < 0 or self.covered_pairs < 0:
            raise ValueError("pair counts must be non-negative")
        if self.covered_pairs > self.total_pairs:
            raise ValueError("covered pairs cannot exceed total pairs")

    @property
    def coverage_pct(self) -> float:
        if not self.total_pairs:
            return 0.0
        return round(self.covered_pairs / self.total_pairs * 100.0, 4)

    def as_dict(self) -> dict[str, int | float]:
        return {
            "total_pairs": self.total_pairs,
            "covered_pairs": self.covered_pairs,
            "coverage_pct": self.coverage_pct,
        }


@dataclass(frozen=True)
class CoverageSnapshot:
    """Point-in-time inventory used by the strict research gate."""

    as_of_date: date
    stock_daily: DatasetCoverage
    concept_daily: DatasetCoverage
    concept_membership: DatasetCoverage
    security_status: DatasetCoverage
    candidate_minutes: PairCoverage
    market_timing: DatasetCoverage
    supporting: tuple[tuple[str, DatasetCoverage], ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "as_of_date": self.as_of_date.isoformat(),
            "stock_daily": self.stock_daily.as_dict(),
            "concept_daily": self.concept_daily.as_dict(),
            "concept_membership": self.concept_membership.as_dict(),
            "security_status": self.security_status.as_dict(),
            "candidate_minutes": self.candidate_minutes.as_dict(),
            "market_timing": self.market_timing.as_dict(),
            "supporting": {
                name: coverage.as_dict() for name, coverage in self.supporting
            },
        }


@dataclass(frozen=True)
class DataQualityDecision:
    """Fail-closed decision for strict historical research."""

    status: str
    strict_ready: bool
    evidence_level: str
    blocking_gaps: tuple[str, ...]
    formal_metrics: None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "strict_ready": self.strict_ready,
            "evidence_level": self.evidence_level,
            "blocking_gaps": list(self.blocking_gaps),
            "formal_metrics": self.formal_metrics,
        }


@dataclass(frozen=True)
class QualificationDecision:
    """Decision for a fully strict locked-holdout result."""

    status: str
    qualified: bool
    failed_gates: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "qualified": self.qualified,
            "failed_gates": list(self.failed_gates),
        }
