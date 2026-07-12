from __future__ import annotations

from alphaagent.server.services.limit_up.dynamic_exit import (
    EXIT_MODE_AUCTION,
    EXIT_MODE_TAIL,
    attach_dynamic_exit_decisions,
)


def test_dynamic_exit_defaults_to_tail_when_training_is_insufficient() -> None:
    signals = [
        _signal(
            "600001.SSE",
            result_date="2025-07-01",
            phase="expanding_oos",
            open_return=8.0,
            close_return=2.0,
        )
    ]

    result = attach_dynamic_exit_decisions(signals)

    assert result[0]["dynamic_exit"]["mode"] == EXIT_MODE_TAIL
    assert result[0]["dynamic_exit"]["confidence"] == "insufficient_history"


def test_dynamic_exit_uses_only_results_matured_before_decision_day() -> None:
    training = [
        _signal(
            f"6000{index:02d}.SSE",
            result_date=f"2025-07-{index + 1:02d}",
            phase="expanding_oos",
            open_return=8.0,
            close_return=2.0,
        )
        for index in range(1, 13)
    ]
    current = [
        _signal(
            "601001.SSE",
            result_date="2025-08-01",
            phase="expanding_oos",
            open_return=8.0,
            close_return=-9.0,
        ),
        _signal(
            "601002.SSE",
            result_date="2025-08-01",
            phase="expanding_oos",
            open_return=8.0,
            close_return=20.0,
        ),
    ]

    result = attach_dynamic_exit_decisions([*training, *current])[-2:]

    assert [row["dynamic_exit"]["mode"] for row in result] == [
        EXIT_MODE_AUCTION,
        EXIT_MODE_AUCTION,
    ]
    assert {row["dynamic_exit"]["sample_count"] for row in result} == {12}
    assert {row["dynamic_exit"]["training_cutoff"] for row in result} == {
        "2025-07-13"
    }


def test_locked_holdout_uses_one_policy_frozen_before_holdout() -> None:
    development = [
        _signal(
            f"6001{index:02d}.SSE",
            result_date=f"2025-12-{index + 1:02d}",
            phase="expanding_oos",
            open_return=7.0,
            close_return=1.0,
        )
        for index in range(1, 13)
    ]
    holdout = [
        _signal(
            f"6011{index:02d}.SSE",
            result_date=f"2026-01-{index + 2:02d}",
            phase="locked_holdout",
            open_return=7.0,
            close_return=15.0,
        )
        for index in range(1, 8)
    ]

    result = attach_dynamic_exit_decisions([*development, *holdout])[-7:]

    assert {row["dynamic_exit"]["mode"] for row in result} == {EXIT_MODE_AUCTION}
    assert {row["dynamic_exit"]["sample_count"] for row in result} == {12}
    assert {row["dynamic_exit"]["training_cutoff"] for row in result} == {
        "2025-12-13"
    }


def test_dynamic_exit_does_not_apply_high_board_rule_to_other_lanes() -> None:
    training = [
        _signal(
            f"6002{index:02d}.SSE",
            result_date=f"2025-09-{index + 1:02d}",
            phase="expanding_oos",
            open_return=8.0,
            close_return=1.0,
        )
        for index in range(1, 13)
    ]
    current = _signal(
        "002001.SZSE",
        result_date="2025-10-01",
        phase="expanding_oos",
        open_return=8.0,
        close_return=-3.0,
        lane="two_to_three",
    )

    result = attach_dynamic_exit_decisions([*training, current])[-1]

    assert result["dynamic_exit"]["mode"] == EXIT_MODE_TAIL
    assert result["dynamic_exit"]["reason_code"] == "tail_has_no_validated_auction_edge"


def _signal(
    vt_symbol: str,
    *,
    result_date: str,
    phase: str,
    open_return: float,
    close_return: float,
    lane: str = "high_board",
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "lane": lane,
        "entry_date": "2025-01-02",
        "result_date": result_date,
        "validation_phase": phase,
        "outcome": {
            "next_open_return_pct": open_return,
            "next_close_return_pct": close_return,
        },
    }
