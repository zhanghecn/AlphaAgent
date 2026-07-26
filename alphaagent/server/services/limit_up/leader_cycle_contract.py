"""Pure contracts for point-in-time leader-cycle research."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class BoardPattern(StrEnum):
    FIRST_BOARD_IGNITION = "first_board_ignition"
    CONTINUOUS_TWO_TO_THREE = "continuous_two_to_three"
    SHORT_CYCLE_REBOARD_THREE = "short_cycle_reboard_three"
    HIGHER_BOARD_CONTINUATION = "higher_board_continuation"
    FAILED_REBOARD = "failed_reboard"


class LeaderRole(StrEnum):
    THEME_IGNITION_LEADER = "theme_ignition_leader"
    SPACE_LEADER = "space_leader"
    INDEPENDENT_DEMON = "independent_demon"
    CAPACITY_CORE = "capacity_core"
    LEADER_2 = "leader_2"
    LEADER_3 = "leader_3"
    REPLENISHMENT = "replenishment"
    ORDINARY_FOLLOWER = "ordinary_follower"


class CyclePhase(StrEnum):
    IGNITION = "ignition"
    CONFIRMATION = "confirmation"
    DIFFUSION = "diffusion"
    ACCELERATION = "acceleration"
    DIVERGENCE = "divergence"
    REFLUX = "reflux"
    EBB = "ebb"


FUTURE_FEATURE_FIELDS = frozenset(
    {
        "final_role",
        "final_sealed",
        "final_board_height",
        "cycle_end_date",
        "d1_return_pct",
        "d1_won",
    }
)

POINT_IN_TIME_ROLE_FIELDS = (
    "vt_symbol",
    "board_pattern",
    "effective_board_height",
    "relative_theme_strength",
    "distance_to_limit_pct",
    "theme_touch_order",
    "d1_gene_sample_count",
    "d1_gene_win_probability",
)


@dataclass(frozen=True, slots=True)
class BoardDay:
    trade_date: date
    sealed: bool
    touched: bool = False


@dataclass(frozen=True, slots=True)
class RoleAssignment:
    vt_symbol: str
    roles: frozenset[LeaderRole]


@dataclass(frozen=True, slots=True)
class CycleState:
    cycle_id: str
    phase: CyclePhase
    as_of: date


@dataclass(frozen=True, slots=True)
class FeatureFieldContract:
    name: str
    group: str
    source: str
    missing_semantics: str = "unknown_not_zero"


FACTOR_FIELD_CONTRACTS = (
    FeatureFieldContract("market_up_ratio", "E", "sentiment"),
    FeatureFieldContract("limit_up_count", "E", "sentiment"),
    FeatureFieldContract("limit_down_count", "E", "sentiment"),
    FeatureFieldContract("failed_limit_up_rate", "E", "sentiment"),
    FeatureFieldContract("promotion_rate", "E", "sentiment"),
    FeatureFieldContract("effective_max_board", "E", "sentiment"),
    FeatureFieldContract("max_board_change", "E", "sentiment"),
    FeatureFieldContract("board_pattern", "L", "limit_event"),
    FeatureFieldContract("effective_board_height", "L", "limit_event"),
    FeatureFieldContract("relative_theme_strength", "L", "concept_strength"),
    FeatureFieldContract("distance_to_limit_pct", "L", "radar"),
    FeatureFieldContract("price_acceleration_1m", "L", "minute_bars"),
    FeatureFieldContract("price_acceleration_3m", "L", "minute_bars"),
    FeatureFieldContract("price_acceleration_5m", "L", "minute_bars"),
    FeatureFieldContract("turnover_acceleration_1m", "L", "minute_bars"),
    FeatureFieldContract("turnover_acceleration_3m", "L", "minute_bars"),
    FeatureFieldContract("turnover_acceleration_5m", "L", "minute_bars"),
    FeatureFieldContract("theme_touch_order", "L", "limit_event"),
    FeatureFieldContract("opened_board_count", "L", "limit_event"),
    FeatureFieldContract("resealed", "L", "limit_event"),
    FeatureFieldContract("prior_turnover_percentile", "L", "daily_bars"),
    FeatureFieldContract("d1_gene_sample_count", "L", "formal_prior_only_gene"),
    FeatureFieldContract("d1_gene_win_probability", "L", "formal_prior_only_gene"),
    FeatureFieldContract("financial_capacity_quality", "L", "financial_point_in_time"),
    FeatureFieldContract("incremental_propagation_1m", "P", "propagation_panel"),
    FeatureFieldContract("incremental_propagation_3m", "P", "propagation_panel"),
    FeatureFieldContract("incremental_propagation_5m", "P", "propagation_panel"),
    FeatureFieldContract("incremental_propagation_10m", "P", "propagation_panel"),
    FeatureFieldContract("propagation_member_coverage_ratio", "P", "propagation_panel"),
    FeatureFieldContract("is_current_highest_group", "R", "leader_cycle_ledger"),
    FeatureFieldContract("theme_ignition_order", "R", "limit_event"),
    FeatureFieldContract("capacity_rank", "R", "point_in_time_turnover"),
    FeatureFieldContract("response_rank", "R", "leader_cycle_ledger"),
    FeatureFieldContract("existing_leadership_tenure", "R", "leader_cycle_ledger"),
    FeatureFieldContract("old_leader_failed", "H", "limit_event"),
    FeatureFieldContract("old_theme_propagation_decay", "H", "propagation_panel"),
    FeatureFieldContract("fund_height_divergence", "H", "sector_fund_flow"),
    FeatureFieldContract("new_theme_co_ignition", "H", "limit_event"),
    FeatureFieldContract("capacity_core_migration", "H", "point_in_time_turnover"),
    FeatureFieldContract("reflux_recovery", "H", "leader_cycle_ledger"),
)


def classify_board_pattern(
    days: Sequence[BoardDay | Mapping[str, object]],
) -> BoardPattern | None:
    normalized = sorted((_board_day(day) for day in days), key=lambda day: day.trade_date)
    if not normalized:
        return None
    current = normalized[-1]
    previous = normalized[-2] if len(normalized) >= 2 else None
    previous_streak = _trailing_sealed_count(normalized[:-1])
    five_day_sealed = sum(day.sealed for day in normalized[-5:])

    if current.sealed and previous_streak >= 3:
        return BoardPattern.HIGHER_BOARD_CONTINUATION
    if current.sealed and previous_streak == 2:
        return BoardPattern.CONTINUOUS_TWO_TO_THREE
    if current.sealed and previous and not previous.sealed and five_day_sealed == 3:
        return BoardPattern.SHORT_CYCLE_REBOARD_THREE
    if previous_streak == 0 and (current.touched or current.sealed):
        if _is_failed_reboard_watch(normalized):
            return BoardPattern.FAILED_REBOARD
        return BoardPattern.FIRST_BOARD_IGNITION
    if _is_failed_reboard_watch(normalized):
        return BoardPattern.FAILED_REBOARD
    return None


def assign_ex_post_roles(
    candidates: Sequence[Mapping[str, object]],
) -> tuple[RoleAssignment, ...]:
    """Assign research-only labels while retaining ties and multiple roles."""

    maximum_height = max(
        (_integer(candidate.get("board_height")) for candidate in candidates),
        default=0,
    )
    assignments: list[RoleAssignment] = []
    for candidate in candidates:
        symbol = str(candidate.get("vt_symbol") or "")
        if not symbol:
            raise ValueError("role candidates require vt_symbol")
        height = _integer(candidate.get("board_height"))
        highest_days = _integer(candidate.get("highest_group_days"))
        propagation = candidate.get("propagation_confirmed")
        roles: set[LeaderRole] = set()
        if maximum_height > 0 and height == maximum_height:
            roles.add(LeaderRole.SPACE_LEADER)
        if (
            LeaderRole.SPACE_LEADER in roles
            and (height >= 5 or highest_days >= 2)
            and propagation is False
        ):
            roles.add(LeaderRole.INDEPENDENT_DEMON)
        if candidate.get("ignition_contribution") is True and propagation is True:
            roles.add(LeaderRole.THEME_IGNITION_LEADER)
        if candidate.get("capacity_core") is True:
            roles.add(LeaderRole.CAPACITY_CORE)
        response_rank = _integer(candidate.get("response_rank"))
        if response_rank == 2:
            roles.add(LeaderRole.LEADER_2)
        elif response_rank == 3:
            roles.add(LeaderRole.LEADER_3)
        if candidate.get("started_after_confirmation") is True:
            roles.add(LeaderRole.REPLENISHMENT)
        if not roles:
            roles.add(LeaderRole.ORDINARY_FOLLOWER)
        assignments.append(RoleAssignment(symbol, frozenset(roles)))
    return tuple(sorted(assignments, key=lambda assignment: assignment.vt_symbol))


def advance_cycle_state(
    current: CycleState | None,
    next_phase: CyclePhase,
    *,
    as_of: date,
    new_cycle_id: str | None = None,
) -> CycleState:
    if current is None:
        if next_phase is not CyclePhase.IGNITION or not new_cycle_id:
            raise ValueError("a new cycle must start at ignition with a cycle_id")
        return CycleState(new_cycle_id, next_phase, as_of)
    if as_of <= current.as_of:
        raise ValueError("cycle state must advance to a later date")
    if next_phase is current.phase:
        return CycleState(current.cycle_id, next_phase, as_of)
    if current.phase is CyclePhase.EBB and next_phase is CyclePhase.IGNITION:
        if not new_cycle_id or new_cycle_id == current.cycle_id:
            raise ValueError("a new ignition requires a new cycle_id")
        return CycleState(new_cycle_id, next_phase, as_of)
    allowed = {
        CyclePhase.IGNITION: {CyclePhase.CONFIRMATION, CyclePhase.DIFFUSION},
        CyclePhase.CONFIRMATION: {CyclePhase.DIFFUSION, CyclePhase.DIVERGENCE},
        CyclePhase.DIFFUSION: {CyclePhase.ACCELERATION, CyclePhase.DIVERGENCE},
        CyclePhase.ACCELERATION: {CyclePhase.DIVERGENCE},
        CyclePhase.DIVERGENCE: {CyclePhase.REFLUX, CyclePhase.EBB},
        CyclePhase.REFLUX: {
            CyclePhase.DIFFUSION,
            CyclePhase.ACCELERATION,
            CyclePhase.DIVERGENCE,
            CyclePhase.EBB,
        },
        CyclePhase.EBB: set(),
    }
    if next_phase not in allowed[current.phase]:
        raise ValueError(f"illegal cycle transition: {current.phase} -> {next_phase}")
    if new_cycle_id and new_cycle_id != current.cycle_id:
        raise ValueError("cycle_id cannot change before a new ignition")
    return CycleState(current.cycle_id, next_phase, as_of)


def point_in_time_role_features(
    observation: Mapping[str, object],
    *,
    known_at: datetime,
    source: str,
) -> dict[str, object]:
    reject_future_feature_names(observation.keys())
    return {
        field: observation.get(field)
        for field in POINT_IN_TIME_ROLE_FIELDS
    } | {
        "known_at": known_at,
        "source": source,
    }


def reject_future_feature_names(names: Sequence[str]) -> None:
    forbidden = sorted(set(names).intersection(FUTURE_FEATURE_FIELDS))
    if forbidden:
        raise ValueError(f"future leader-cycle features are forbidden: {forbidden}")


def _board_day(value: BoardDay | Mapping[str, object]) -> BoardDay:
    if isinstance(value, BoardDay):
        return value
    trade_date = _date_value(value.get("trade_date"))
    if trade_date is None:
        raise ValueError("board days require trade_date")
    return BoardDay(
        trade_date=trade_date,
        sealed=bool(value.get("sealed")),
        touched=bool(value.get("touched")),
    )


def _is_failed_reboard_watch(days: Sequence[BoardDay]) -> bool:
    if len(days) < 5:
        return False
    current = days[-1]
    previous = days[-2]
    return not current.sealed and not previous.sealed and sum(day.sealed for day in days[-5:-1]) == 2


def _trailing_sealed_count(days: Sequence[BoardDay]) -> int:
    count = 0
    for day in reversed(days):
        if not day.sealed:
            break
        count += 1
    return count


def _date_value(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _integer(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
