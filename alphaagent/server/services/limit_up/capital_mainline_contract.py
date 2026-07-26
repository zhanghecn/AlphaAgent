"""Point-in-time contracts for capital-mainline leader-cycle research."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping, Sequence


class EvidenceLevel(StrEnum):
    POINT_IN_TIME = "point_in_time"
    DAILY_CLOSE_OBSERVED = "daily_close_observed"
    TURNOVER_PROXY = "turnover_proxy_only"
    CURRENT_MEMBERSHIP_PROXY = "current_membership_survivorship_proxy"
    UNAVAILABLE = "unavailable"


class MarketCyclePhase(StrEnum):
    ICE = "ice"
    REPAIR = "repair"
    LAUNCH = "launch"
    ACCELERATION = "acceleration"
    DIVERGENCE = "divergence"
    REFLUX = "reflux"
    EBB = "ebb"


class ConceptCyclePhase(StrEnum):
    WATCH = "watch"
    IGNITION = "ignition_candidate"
    CONFIRMATION = "confirmation"
    DIFFUSION = "diffusion"
    ACCELERATION = "acceleration"
    DIVERGENCE = "divergence"
    REFLUX = "reflux"
    EBB = "ebb"
    ENDED = "ended"


class CapitalRole(StrEnum):
    IGNITION_CANDIDATE = "ignition_candidate"
    CONFIRMED_IGNITION_LEADER = "confirmed_ignition_leader"
    LEADER_2 = "leader_2"
    LEADER_3 = "leader_3"
    CONTINUOUS_TWO_TO_THREE = "continuous_two_to_three"
    SHORT_CYCLE_REBOARD_THREE = "short_cycle_reboard_three"
    CAPACITY_CORE = "capacity_core"
    REPLENISHMENT = "replenishment"
    INDEPENDENT_SPACE_LEADER = "independent_space_leader"
    ORDINARY_FOLLOWER = "ordinary_follower"


_FORBIDDEN_ASOF_FIELDS = frozenset(
    {
        "cycle_end_date",
        "d1_return",
        "d1_return_pct",
        "final_board_height",
        "final_role",
        "future_follower_count",
        "future_max_board_height",
        "realized_role",
    }
)
_FORBIDDEN_ASOF_TOKENS = ("future_", "realized_", "final_")


def validate_asof_fields(names: Sequence[str]) -> None:
    """Reject fields that are only known after the decision cutoff."""

    invalid = sorted(
        {
            str(name)
            for name in names
            if str(name) in _FORBIDDEN_ASOF_FIELDS
            or any(token in str(name) for token in _FORBIDDEN_ASOF_TOKENS)
        }
    )
    if invalid:
        raise ValueError(f"future feature is not allowed in as-of fields: {invalid}")


@dataclass(frozen=True, slots=True)
class CapitalRoleRow:
    market_cycle_id: str
    concept_cycle_id: str
    trade_date: date
    vt_symbol: str
    sector_id: str
    role_asof: tuple[CapitalRole, ...]
    role_realized: tuple[CapitalRole, ...]
    membership_evidence_level: EvidenceLevel
    asof_features: Mapping[str, Any]
    realized_labels: Mapping[str, Any]

    def __post_init__(self) -> None:
        validate_asof_fields(tuple(self.asof_features))
        if not self.market_cycle_id or not self.concept_cycle_id:
            raise ValueError("cycle identities are required")
        if not self.vt_symbol or not self.sector_id:
            raise ValueError("symbol and sector identities are required")

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["role_asof"] = [role.value for role in self.role_asof]
        payload["role_realized"] = [role.value for role in self.role_realized]
        payload["membership_evidence_level"] = self.membership_evidence_level.value
        return payload


def capital_evidence_level(
    *,
    has_real_flow: bool,
    flow_known_before_decision: bool,
    has_turnover_proxy: bool,
) -> EvidenceLevel:
    if has_real_flow and flow_known_before_decision:
        return EvidenceLevel.DAILY_CLOSE_OBSERVED
    if has_turnover_proxy:
        return EvidenceLevel.TURNOVER_PROXY
    return EvidenceLevel.UNAVAILABLE
