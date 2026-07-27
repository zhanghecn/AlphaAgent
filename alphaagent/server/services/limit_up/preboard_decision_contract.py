"""Shared causal contract for historical and live pre-board decisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from math import isfinite

from alphaagent.server.services.limit_up import core_quality

PREBOARD_DECISION_VERSION = "limit-up-preboard-decision-v2"
PREBOARD_DIAGNOSTIC_EXECUTION_CHECK_CODES = frozenset(
    {
        "sector_route",
        "sector_expansion",
        "sector_flow",
        "sector_heat",
        "concept_source_quality",
        "concept_freshness",
        "concept_state",
        "concept_diffusion",
        "concept_leader",
        "stock_flow",
        "turnover_rate",
        "seal_retention",
    }
)
PREBOARD_DIAGNOSTIC_ENVIRONMENT_CHECK_CODES = frozenset(
    {
        "market_gate",
        "snapshot_freshness",
        "quote_freshness",
    }
)


class PreboardState(StrEnum):
    OBSERVE = "observe"
    PREPARE = "prepare"
    ACTIONABLE = "actionable"
    MISSED = "missed"
    REJECTED = "rejected"


class PreboardExecutionMode(StrEnum):
    RESEARCH_ONLY = "research_only"
    SHADOW = "shadow"
    FORMAL = "formal"


class PreboardRankingMode(StrEnum):
    CURRENT_D1_FIRST = "current_d1_first"
    PURE_TOUCH_PROBABILITY = "pure_touch_probability"
    COMBINED_OPPORTUNITY_VALUE = "combined_opportunity_value"


@dataclass(frozen=True)
class HistoricalPrior:
    expected_d1_net_return_pct: float | None
    d1_win_probability: float | None
    seal_probability_given_touch: float | None
    d1_win_probability_given_seal: float | None
    analog_sample_count: int
    stock_touch_sample_count: int
    stock_d1_sample_count: int
    as_of_date: date | None

    def touch_seal_probability(self, touch_probability: float) -> float | None:
        _require_probability(touch_probability, "touch_probability")
        if self.seal_probability_given_touch is None:
            return None
        return touch_probability * self.seal_probability_given_touch

    def touch_seal_d1_win_probability(
        self,
        touch_probability: float,
    ) -> float | None:
        touch_seal = self.touch_seal_probability(touch_probability)
        if touch_seal is None or self.d1_win_probability_given_seal is None:
            return None
        return touch_seal * self.d1_win_probability_given_seal


@dataclass(frozen=True)
class PreboardPolicyThresholds:
    minimum_touch_probability_3m: float
    minimum_eventual_touch_probability: float
    calibrated_dates: tuple[date, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        _require_probability(
            self.minimum_touch_probability_3m,
            "minimum_touch_probability_3m",
        )
        _require_probability(
            self.minimum_eventual_touch_probability,
            "minimum_eventual_touch_probability",
        )


@dataclass(frozen=True)
class PreboardOpportunityCalibration:
    touched_unsealed_expected_return_pct: float
    non_touch_expected_return_pct: float
    touched_unsealed_sample_count: int
    non_touch_sample_count: int
    fit_dates: tuple[date, ...]
    fingerprint: str

    def __post_init__(self) -> None:
        values = (
            self.touched_unsealed_expected_return_pct,
            self.non_touch_expected_return_pct,
        )
        if any(not isfinite(value) for value in values):
            raise ValueError("opportunity calibration returns must be finite")
        if self.touched_unsealed_sample_count < 1 or self.non_touch_sample_count < 1:
            raise ValueError("opportunity calibration samples must be positive")
        if not self.fit_dates:
            raise ValueError("opportunity calibration fit dates are required")
        if not self.fingerprint:
            raise ValueError("opportunity calibration fingerprint is required")


def apply_preboard_parity_contract(
    candidate: Mapping[str, object],
) -> dict[str, object]:
    """Mark fields that cannot yet be replayed identically as diagnostics."""

    result = dict(candidate)
    raw_execution = candidate.get("execution_check_parity")
    execution = dict(raw_execution) if isinstance(raw_execution, Mapping) else {}
    execution.update(
        {
            code: "diagnostic"
            for code in PREBOARD_DIAGNOSTIC_EXECUTION_CHECK_CODES
        }
    )
    raw_environment = candidate.get("environment_check_parity")
    environment = (
        dict(raw_environment) if isinstance(raw_environment, Mapping) else {}
    )
    environment.update(
        {
            code: "diagnostic"
            for code in PREBOARD_DIAGNOSTIC_ENVIRONMENT_CHECK_CODES
        }
    )
    result["execution_check_parity"] = execution
    result["environment_check_parity"] = environment
    raw_checks = candidate.get("execution_checks")
    if isinstance(raw_checks, Sequence) and not isinstance(raw_checks, (str, bytes)):
        result["execution_checks"] = [
            {
                **dict(check),
                "parity_status": str(
                    execution.get(str(check.get("code") or ""))
                    or check.get("parity_status")
                    or "shared"
                ),
            }
            for check in raw_checks
            if isinstance(check, Mapping)
        ]
    return result


def preboard_market_gate(
    market_gate: Mapping[str, object],
) -> dict[str, object]:
    """Apply the same market-gate parity semantics to replay and live input."""

    return {**dict(market_gate), "parity_status": "diagnostic"}


def is_observable_first_board(row: Mapping[str, object]) -> bool:
    change_pct = _number(row.get("change_pct"))
    return bool(
        str(row.get("board_lane") or "") == "first_board"
        and core_quality.is_public_quality_prepared(row)
        and change_pct is not None
        and change_pct >= 3.0
    )


def is_strictly_preboard(row: Mapping[str, object]) -> bool:
    if str(row.get("state") or "") in {"sealed", "resealed", "failed"}:
        return False
    last_price = _number(row.get("last_price"))
    limit_price = _number(row.get("limit_price"))
    return bool(
        last_price is not None
        and limit_price is not None
        and last_price < limit_price - 0.001
    )


def historical_prior_from_evidence(
    evidence: Mapping[str, object],
) -> HistoricalPrior:
    return HistoricalPrior(
        expected_d1_net_return_pct=_number(
            evidence.get("d1_money_effect_average_return_pct")
        ),
        d1_win_probability=_percentage_probability(
            evidence.get("d1_money_effect_win_rate")
        ),
        seal_probability_given_touch=_percentage_probability(
            evidence.get("seal_success_rate")
        ),
        d1_win_probability_given_seal=_percentage_probability(
            evidence.get("d1_money_effect_win_rate")
        ),
        analog_sample_count=_count(evidence.get("effective_sample_count")),
        stock_touch_sample_count=_count(evidence.get("stock_gene_touch_count")),
        stock_d1_sample_count=_count(
            evidence.get("d1_money_effect_sample_count")
        ),
        as_of_date=_date(evidence.get("as_of_date")),
    )


def historical_prior_status(prior: HistoricalPrior) -> str:
    required = (
        prior.expected_d1_net_return_pct,
        prior.d1_win_probability,
        prior.seal_probability_given_touch,
        prior.d1_win_probability_given_seal,
    )
    return "ready" if all(value is not None for value in required) else "incomplete"


def _require_probability(value: object, field: str) -> None:
    parsed = _number(value)
    if parsed is None or not 0.0 <= parsed <= 1.0:
        raise ValueError(f"{field} must be between 0 and 1")


def _percentage_probability(value: object) -> float | None:
    parsed = _number(value)
    if parsed is None or not 0.0 <= parsed <= 100.0:
        return None
    return parsed / 100.0


def _count(value: object) -> int:
    parsed = _number(value)
    return max(int(parsed), 0) if parsed is not None else 0


def _date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
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
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if isfinite(parsed) else None
