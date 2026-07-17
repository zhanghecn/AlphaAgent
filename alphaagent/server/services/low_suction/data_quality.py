"""Pure fail-closed gates for low-suction historical research."""

from __future__ import annotations

from .contracts import (
    STRICT_MIN_CALENDAR_DAYS,
    STRICT_MIN_CONCEPT_BAR_COVERAGE_PCT,
    STRICT_MIN_MEMBERSHIP_COVERAGE_PCT,
    STRICT_MIN_TRADE_DAYS,
    CoverageSnapshot,
    DataQualityDecision,
    DatasetCoverage,
    QualificationDecision,
)
from .research_protocol import ResearchProtocol, default_protocol


def evaluate_data_quality(snapshot: CoverageSnapshot) -> DataQualityDecision:
    """Return whether every input needed for formal research is strict."""

    blocking_gaps: list[str] = []
    if not _has_three_year_history(snapshot.stock_daily):
        blocking_gaps.append("stock_daily_history")
    if not _has_strict_concept_history(snapshot.concept_daily):
        blocking_gaps.append("concept_index_history")
    if not _has_strict_membership_history(snapshot.concept_membership):
        blocking_gaps.append("historical_concept_membership")
    if not _has_strict_security_history(snapshot.security_status):
        blocking_gaps.append("historical_security_status")
    if not _has_complete_candidate_minutes(snapshot):
        blocking_gaps.append("candidate_minute_paths")

    strict_ready = not blocking_gaps
    return DataQualityDecision(
        status=("ready_for_strict_research" if strict_ready else "blocked_by_data_quality"),
        strict_ready=strict_ready,
        evidence_level=_evidence_level(snapshot, strict_ready),
        blocking_gaps=tuple(blocking_gaps),
    )


def evaluate_qualification(
    *,
    closed_trades: int,
    win_rate_pct: float,
    compounded_return_pct: float,
    profit_factor: float | None,
    maximum_drawdown_pct: float,
    double_cost_return_pct: float,
    strict_data_ready: bool = True,
    protocol: ResearchProtocol | None = None,
) -> QualificationDecision:
    """Apply fixed qualification gates to one locked-holdout result."""

    if not strict_data_ready:
        return QualificationDecision(
            status="blocked_by_data_quality",
            qualified=False,
            failed_gates=("strict_data_quality",),
        )
    selected_protocol = protocol or default_protocol()
    if closed_trades < selected_protocol.min_holdout_trades:
        return QualificationDecision(
            status="insufficient_sample",
            qualified=False,
            failed_gates=("closed_trades",),
        )

    failed_gates: list[str] = []
    if win_rate_pct <= selected_protocol.min_holdout_win_rate_pct:
        failed_gates.append("win_rate")
    if (
        compounded_return_pct
        <= selected_protocol.min_holdout_compounded_return_pct
    ):
        failed_gates.append("compounded_return")
    if profit_factor is None or profit_factor <= 1:
        failed_gates.append("profit_factor")
    if not selected_protocol.max_drawdown_pct <= maximum_drawdown_pct <= 0:
        failed_gates.append("maximum_drawdown")
    if double_cost_return_pct <= 0:
        failed_gates.append("double_cost_return")

    qualified = not failed_gates
    return QualificationDecision(
        status=("qualified_research_rule" if qualified else "no_qualified_strategy"),
        qualified=qualified,
        failed_gates=tuple(failed_gates),
    )


def _has_three_year_history(coverage: DatasetCoverage) -> bool:
    return (
        coverage.trade_days >= STRICT_MIN_TRADE_DAYS
        and coverage.calendar_span_days >= STRICT_MIN_CALENDAR_DAYS
    )


def _has_strict_concept_history(coverage: DatasetCoverage) -> bool:
    return (
        coverage.mode == "strict"
        and _has_three_year_history(coverage)
        and coverage.coverage_pct >= STRICT_MIN_CONCEPT_BAR_COVERAGE_PCT
    )


def _has_strict_membership_history(coverage: DatasetCoverage) -> bool:
    return (
        coverage.mode == "strict"
        and _has_three_year_history(coverage)
        and coverage.coverage_pct >= STRICT_MIN_MEMBERSHIP_COVERAGE_PCT
    )


def _has_strict_security_history(coverage: DatasetCoverage) -> bool:
    return (
        coverage.mode == "strict"
        and _has_three_year_history(coverage)
        and coverage.coverage_pct >= STRICT_MIN_MEMBERSHIP_COVERAGE_PCT
    )


def _has_complete_candidate_minutes(snapshot: CoverageSnapshot) -> bool:
    minute_coverage = snapshot.candidate_minutes
    return (
        minute_coverage.total_pairs > 0
        and minute_coverage.covered_pairs == minute_coverage.total_pairs
    )


def _evidence_level(snapshot: CoverageSnapshot, strict_ready: bool) -> str:
    if strict_ready:
        return "strict"
    if snapshot.concept_membership.mode in {"current_proxy", "membership_proxy"}:
        return "membership_proxy"
    return "daily_discovery"
