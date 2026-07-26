from __future__ import annotations

from datetime import date, datetime

import pytest

from alphaagent.server.services.limit_up.leader_cycle_contract import (
    FACTOR_FIELD_CONTRACTS,
    BoardDay,
    BoardPattern,
    CyclePhase,
    CycleState,
    LeaderRole,
    advance_cycle_state,
    assign_ex_post_roles,
    classify_board_pattern,
    point_in_time_role_features,
    reject_future_feature_names,
)
from alphaagent.server.services.limit_up.leader_cycle_research import (
    build_point_in_time_factor_row,
    build_switch_risk_features,
)


DATES = [date(2026, 7, day) for day in (1, 2, 3, 6, 7)]


def _days(sealed: list[bool], *, touched_last: bool = True) -> list[BoardDay]:
    return [
        BoardDay(trade_date=trade_date, sealed=is_sealed, touched=touched_last if index == 4 else is_sealed)
        for index, (trade_date, is_sealed) in enumerate(zip(DATES, sealed, strict=True))
    ]


@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (_days([False, False, False, False, True]), BoardPattern.FIRST_BOARD_IGNITION),
        (_days([False, False, True, True, True]), BoardPattern.CONTINUOUS_TWO_TO_THREE),
        (_days([True, False, True, False, True]), BoardPattern.SHORT_CYCLE_REBOARD_THREE),
        (_days([False, True, True, True, True]), BoardPattern.HIGHER_BOARD_CONTINUATION),
        (_days([True, False, True, False, False]), BoardPattern.FAILED_REBOARD),
    ],
)
def test_board_patterns_are_mutually_classified(
    days: list[BoardDay],
    expected: BoardPattern,
) -> None:
    assert classify_board_pattern(days) is expected


def test_roles_retain_highest_board_ties_and_multiple_labels() -> None:
    assignments = assign_ex_post_roles(
        [
            {
                "vt_symbol": "600001.SSE",
                "board_height": 5,
                "highest_group_days": 2,
                "propagation_confirmed": False,
            },
            {
                "vt_symbol": "600002.SSE",
                "board_height": 5,
                "propagation_confirmed": True,
                "ignition_contribution": True,
                "capacity_core": True,
            },
            {"vt_symbol": "600003.SSE", "board_height": 1},
        ]
    )
    by_symbol = {assignment.vt_symbol: assignment.roles for assignment in assignments}

    assert by_symbol["600001.SSE"] == frozenset(
        {LeaderRole.SPACE_LEADER, LeaderRole.INDEPENDENT_DEMON}
    )
    assert by_symbol["600002.SSE"] == frozenset(
        {
            LeaderRole.SPACE_LEADER,
            LeaderRole.THEME_IGNITION_LEADER,
            LeaderRole.CAPACITY_CORE,
        }
    )
    assert by_symbol["600003.SSE"] == frozenset({LeaderRole.ORDINARY_FOLLOWER})


def test_cycle_state_machine_accepts_registered_transitions() -> None:
    state = advance_cycle_state(
        None,
        CyclePhase.IGNITION,
        as_of=date(2026, 7, 1),
        new_cycle_id="power-1",
    )
    state = advance_cycle_state(state, CyclePhase.CONFIRMATION, as_of=date(2026, 7, 2))
    state = advance_cycle_state(state, CyclePhase.DIFFUSION, as_of=date(2026, 7, 3))
    state = advance_cycle_state(state, CyclePhase.ACCELERATION, as_of=date(2026, 7, 6))
    state = advance_cycle_state(state, CyclePhase.DIVERGENCE, as_of=date(2026, 7, 7))
    reflux = advance_cycle_state(state, CyclePhase.REFLUX, as_of=date(2026, 7, 8))

    assert reflux == CycleState("power-1", CyclePhase.REFLUX, date(2026, 7, 8))


def test_cycle_state_machine_rejects_future_rewrite_and_reuses_no_cycle_id() -> None:
    old_state = CycleState("old", CyclePhase.EBB, date(2026, 7, 7))

    with pytest.raises(ValueError, match="later date"):
        advance_cycle_state(old_state, CyclePhase.EBB, as_of=date(2026, 7, 6))
    with pytest.raises(ValueError, match="new cycle_id"):
        advance_cycle_state(
            old_state,
            CyclePhase.IGNITION,
            as_of=date(2026, 7, 8),
            new_cycle_id="old",
        )

    new_state = advance_cycle_state(
        old_state,
        CyclePhase.IGNITION,
        as_of=date(2026, 7, 8),
        new_cycle_id="new",
    )
    assert old_state == CycleState("old", CyclePhase.EBB, date(2026, 7, 7))
    assert new_state.cycle_id == "new"


def test_point_in_time_features_reject_outcomes_and_keep_metadata() -> None:
    known_at = datetime(2026, 7, 20, 10, 3)
    features = point_in_time_role_features(
        {
            "vt_symbol": "600001.SSE",
            "effective_board_height": 1,
            "relative_theme_strength": 0.8,
            "unregistered_diagnostic": 99,
        },
        known_at=known_at,
        source="radar",
    )

    assert features["known_at"] == known_at
    assert features["source"] == "radar"
    assert features["relative_theme_strength"] == 0.8
    assert "unregistered_diagnostic" not in features

    with pytest.raises(ValueError, match="d1_return_pct"):
        point_in_time_role_features(
            {"vt_symbol": "600001.SSE", "d1_return_pct": 8.0},
            known_at=known_at,
            source="radar",
        )


def test_future_feature_guard_lists_all_forbidden_names() -> None:
    with pytest.raises(ValueError, match="final_role.*final_sealed"):
        reject_future_feature_names(["final_sealed", "safe", "final_role"])


def test_factor_contract_has_five_groups_and_field_metadata() -> None:
    assert {contract.group for contract in FACTOR_FIELD_CONTRACTS} == {"E", "L", "P", "R", "H"}
    assert len({contract.name for contract in FACTOR_FIELD_CONTRACTS}) == len(
        FACTOR_FIELD_CONTRACTS
    )
    assert all(contract.source for contract in FACTOR_FIELD_CONTRACTS)
    assert all(contract.missing_semantics == "unknown_not_zero" for contract in FACTOR_FIELD_CONTRACTS)


def test_factor_projection_preserves_unknown_and_rejects_late_evidence() -> None:
    decision_at = datetime(2026, 7, 20, 10, 0)
    factors = build_point_in_time_factor_row(
        {
            "known_at": datetime(2026, 7, 20, 9, 59),
            "market_up_ratio": 0.55,
            "incremental_propagation_3m": None,
        },
        decision_at=decision_at,
    )

    assert factors["market_up_ratio"] == 0.55
    assert factors["market_up_ratio_missing"] is False
    assert factors["incremental_propagation_3m"] is None
    assert factors["incremental_propagation_3m_missing"] is True

    with pytest.raises(ValueError, match="not known at decision time"):
        build_point_in_time_factor_row(
            {
                "market_up_ratio": {
                    "value": 0.8,
                    "known_at": datetime(2026, 7, 20, 15, 1),
                }
            },
            decision_at=decision_at,
        )


def test_switch_risks_remain_separate_and_missing_is_not_false() -> None:
    risks = build_switch_risk_features(
        {
            "old_leader_failed": True,
            "theme_propagation_strength": None,
            "highest_board_theme_id": "BK001",
            "fund_main_theme_id": "BK002",
            "new_theme_co_ignition": 2,
            "capacity_core_symbol": "600002.SSE",
            "theme_stage": "reflux",
        },
        {
            "theme_propagation_strength": 0.7,
            "capacity_core_symbol": "600001.SSE",
        },
    )

    assert risks == {
        "old_leader_failed": True,
        "old_theme_propagation_decay": None,
        "fund_height_divergence": True,
        "new_theme_co_ignition": 2,
        "capacity_core_migration": True,
        "reflux_recovery": True,
    }


def test_cycle_state_machine_supports_observed_divergence_paths() -> None:
    ignition = CycleState("medicine", CyclePhase.IGNITION, date(2026, 7, 10))
    confirmation = advance_cycle_state(
        ignition,
        CyclePhase.CONFIRMATION,
        as_of=date(2026, 7, 14),
    )
    diffusion = advance_cycle_state(
        confirmation,
        CyclePhase.DIFFUSION,
        as_of=date(2026, 7, 15),
    )
    divergence = advance_cycle_state(
        diffusion,
        CyclePhase.DIVERGENCE,
        as_of=date(2026, 7, 16),
    )
    reflux = advance_cycle_state(
        divergence,
        CyclePhase.REFLUX,
        as_of=date(2026, 7, 17),
    )
    ebb = advance_cycle_state(reflux, CyclePhase.EBB, as_of=date(2026, 7, 20))

    assert ebb.phase is CyclePhase.EBB
