from __future__ import annotations

from datetime import datetime, timedelta

from alphaagent.server.services.limit_up.dynamic_leader_shadow import (
    DynamicLeaderTracker,
)


CAPTURED_AT = datetime.fromisoformat("2026-07-24T10:05:00+08:00")


def test_tracker_locks_first_theme_and_ignores_stronger_alternative() -> None:
    tracker = DynamicLeaderTracker()

    first = tracker.attach(
        [
            _candidate(
                "600001.SSE",
                _concept("A", "存储芯片", state="warming", leader_rank=2),
                _concept("B", "机器人", state="warming", leader_rank=3),
            )
        ],
        captured_at=CAPTURED_AT,
        market_gate_passed=True,
    )
    second = tracker.attach(
        [
            _candidate(
                "600001.SSE",
                _concept("A", "存储芯片", state="warming", leader_rank=4),
                _concept("B", "机器人", state="launch", leader_rank=1),
            )
        ],
        captured_at=CAPTURED_AT + timedelta(seconds=10),
        market_gate_passed=True,
    )

    assert first[0]["dynamic_leader_shadow"]["concept_id"] == "A"
    shadow = second[0]["dynamic_leader_shadow"]
    assert shadow["concept_id"] == "A"
    assert shadow["concept_leader_rank"] == 4
    assert shadow["observed_frames"] == 2
    assert shadow["persistence_ratio"] == 1.0
    assert shadow["components"]["concept_strong_5_ratio"] == 0.25
    assert shadow["components"]["market_theme_observed_concept_count"] == 2
    assert shadow["components"]["market_theme_top10_strong_conversion"] == 0.5


def test_tracker_keeps_observe_theme_during_grace_then_switches() -> None:
    tracker = DynamicLeaderTracker(grace_seconds=60)
    tracker.attach(
        [
            _candidate(
                "600001.SSE",
                _concept("A", "存储芯片", state="launch", leader_rank=1),
                _concept("B", "机器人", state="warming", leader_rank=2),
            )
        ],
        captured_at=CAPTURED_AT,
        market_gate_passed=True,
    )

    cooling = tracker.attach(
        [
            _candidate(
                "600001.SSE",
                _concept("A", "存储芯片", state="observe", leader_rank=1),
                _concept("B", "机器人", state="launch", leader_rank=1),
            )
        ],
        captured_at=CAPTURED_AT + timedelta(seconds=30),
        market_gate_passed=True,
    )[0]["dynamic_leader_shadow"]
    switched = tracker.attach(
        [
            _candidate(
                "600001.SSE",
                _concept("A", "存储芯片", state="observe", leader_rank=1),
                _concept("B", "机器人", state="launch", leader_rank=1),
            )
        ],
        captured_at=CAPTURED_AT + timedelta(seconds=61),
        market_gate_passed=True,
    )[0]["dynamic_leader_shadow"]

    assert cooling["status"] == "cooling"
    assert cooling["concept_id"] == "A"
    assert cooling["current_concept_top5"] is False
    assert switched["status"] == "locked"
    assert switched["concept_id"] == "B"
    assert switched["locked_at"] == (
        CAPTURED_AT + timedelta(seconds=61)
    ).isoformat()


def test_global_top5_follows_d1_order_and_never_changes_actions() -> None:
    tracker = DynamicLeaderTracker()
    rows = [
        {
            **_candidate(
                f"60000{index}.SSE",
                _concept(
                    f"C{index}",
                    f"题材{index}",
                    state="launch",
                    leader_rank=1,
                ),
            ),
            "expected_d1_net_return_pct": 7 - index,
            "action": "buy_now" if index == 1 else "observe",
        }
        for index in range(1, 7)
    ]

    result = tracker.attach(
        rows,
        captured_at=CAPTURED_AT,
        market_gate_passed=False,
    )

    assert [row["vt_symbol"] for row in result] == [
        row["vt_symbol"] for row in rows
    ]
    assert [row["action"] for row in result] == [row["action"] for row in rows]
    assert [
        row["dynamic_leader_shadow"]["global_rank"] for row in result
    ] == [1, 2, 3, 4, 5, 6]
    assert [
        row["dynamic_leader_shadow"]["global_top5"] for row in result
    ] == [True, True, True, True, True, False]
    assert all(
        row["dynamic_leader_shadow"]["market_gate_passed"] is False
        for row in result
    )
    assert all(
        row["dynamic_leader_shadow"]["execution_effect"]
        == "none_research_only"
        for row in result
    )


def _candidate(
    symbol: str,
    *concepts: dict[str, object],
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "concept_trigger_allowed": True,
        "concept_candidates": list(concepts),
    }


def _concept(
    concept_id: str,
    name: str,
    *,
    state: str,
    leader_rank: int,
) -> dict[str, object]:
    return {
        "concept_id": concept_id,
        "concept_name": name,
        "concept_state": state,
        "leader_rank": leader_rank,
        "strength_rank": leader_rank,
        "strength_score": 100 - leader_rank,
        "rise_ratio": 0.5,
        "strong_5_ratio": 0.25,
        "near_limit_ratio": 0.1,
        "change_acceleration_3m": 0.4,
    }
