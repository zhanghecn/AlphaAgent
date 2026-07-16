from __future__ import annotations

from copy import deepcopy

from alphaagent.server.services.limit_up.first_board_blocker_research import (
    build_first_board_blocker_research_report,
)


def test_blocked_top1_is_causal_and_uses_only_first_post_10_group() -> None:
    days = [
        _day(
            "2026-01-02",
            [
                _candidate(
                    "600001.SSE",
                    "10:00:00",
                    decision="eligible",
                    blockers=[],
                    result_date="2026-01-05",
                    return_pct=2.0,
                ),
                _candidate(
                    "600002.SSE",
                    "10:00:00",
                    decision="eligible",
                    blockers=[],
                    result_date="2026-01-05",
                    return_pct=2.0,
                ),
                _candidate(
                    "600003.SSE",
                    "10:00:00",
                    decision="eligible",
                    blockers=[],
                    result_date="2026-01-05",
                    return_pct=2.0,
                ),
            ],
        ),
        _day(
            "2026-01-06",
            [
                _candidate(
                    "600099.SSE",
                    "09:50:00",
                    blockers=["first_touch_too_early"],
                    seal_rate=0.95,
                    return_pct=9.0,
                ),
                _candidate(
                    "600001.SSE",
                    "10:05:00",
                    blockers=["gate_a"],
                    seal_rate=0.60,
                    return_pct=-2.0,
                ),
                _candidate(
                    "600002.SSE",
                    "10:05:00",
                    blockers=["gate_b"],
                    seal_rate=0.80,
                    return_pct=3.0,
                ),
                _candidate(
                    "600003.SSE",
                    "13:10:00",
                    blockers=["gate_c"],
                    seal_rate=0.95,
                    return_pct=8.0,
                ),
            ],
        ),
    ]

    report = build_first_board_blocker_research_report(days)

    first = report["variants"]["first_observation"]["selections"][0]
    executable = report["variants"]["first_post_10_observation"][
        "selections"
    ][0]
    assert first["vt_symbol"] == "600099.SSE"
    assert executable["vt_symbol"] == "600002.SSE"
    assert executable["signal_time"] == "10:05:00"
    assert executable["stock_gene_combined_win_rate"] == 80.0


def test_blocked_top1_selection_does_not_read_current_outcomes() -> None:
    days = _causal_days()
    mutated = deepcopy(days)
    current = mutated[-1]["lane_portfolio"]["candidate_pool"]["first_board"]
    current[0]["outcome"]["next_close_return_pct"] = 9.0
    current[1]["outcome"]["next_close_return_pct"] = -9.0

    original_report = build_first_board_blocker_research_report(days)
    mutated_report = build_first_board_blocker_research_report(mutated)

    assert (
        original_report["variants"]["first_post_10_observation"]["selections"]
        == mutated_report["variants"]["first_post_10_observation"]["selections"]
    )


def test_single_gate_relaxation_excludes_multi_blocked_candidates() -> None:
    days = [
        _day(
            "2026-01-02",
            [
                _candidate(
                    "600001.SSE",
                    "10:00:00",
                    decision="eligible",
                    blockers=[],
                    result_date="2026-01-05",
                    return_pct=2.0,
                )
            ],
        ),
        _day(
            "2026-01-06",
            [
                _candidate(
                    "600010.SSE",
                    "09:55:00",
                    blockers=["gate_c"],
                ),
                _candidate(
                    "600011.SSE",
                    "10:01:00",
                    blockers=["gate_a", "gate_b"],
                ),
                _candidate(
                    "600012.SSE",
                    "10:02:00",
                    blockers=["gate_a"],
                ),
                _candidate(
                    "600013.SSE",
                    "10:03:00",
                    blockers=["gate_b"],
                ),
            ],
        ),
    ]

    report = build_first_board_blocker_research_report(days)

    assert report["blockers"]["candidate_occurrences"] == {
        "gate_a": 2,
        "gate_b": 2,
        "gate_c": 1,
    }
    assert report["blockers"]["top1_occurrences"] == {
        "gate_a": 1,
        "gate_b": 1,
    }
    assert report["blockers"]["exact_candidate_combinations"]["gate_a + gate_b"] == 1
    assert report["variants"]["relax::gate_a"]["selections"][0][
        "vt_symbol"
    ] == "600012.SSE"
    assert report["variants"]["relax::gate_b"]["selections"][0][
        "vt_symbol"
    ] == "600013.SSE"
    assert report["variants"]["relax::gate_c"]["summary"]["trade_count"] == 0


def _causal_days() -> list[dict[str, object]]:
    return [
        _day(
            "2026-01-02",
            [
                _candidate(
                    "600001.SSE",
                    "10:00:00",
                    decision="eligible",
                    blockers=[],
                    result_date="2026-01-05",
                    return_pct=2.0,
                ),
                _candidate(
                    "600002.SSE",
                    "10:00:00",
                    decision="eligible",
                    blockers=[],
                    result_date="2026-01-05",
                    return_pct=2.0,
                ),
            ],
        ),
        _day(
            "2026-01-06",
            [
                _candidate(
                    "600001.SSE",
                    "10:05:00",
                    blockers=["gate_a"],
                    seal_rate=0.60,
                    return_pct=-2.0,
                ),
                _candidate(
                    "600002.SSE",
                    "10:05:00",
                    blockers=["gate_b"],
                    seal_rate=0.80,
                    return_pct=3.0,
                ),
            ],
        ),
    ]


def _day(
    trade_date: str,
    candidates: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "validation_phase": "locked_holdout",
        "lane_portfolio": {"candidate_pool": {"first_board": candidates}},
    }


def _candidate(
    vt_symbol: str,
    signal_time: str,
    *,
    blockers: list[str],
    decision: str = "blocked",
    result_date: str = "2026-01-07",
    seal_rate: float = 0.70,
    return_pct: float = 1.0,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "lane": "first_board",
        "decision": decision,
        "blockers": blockers,
        "signal_date": "2026-01-06",
        "signal_time": signal_time,
        "entry_date": "2026-01-06",
        "result_date": result_date,
        "entry_price": 10.0,
        "limit_price": 10.0,
        "pool_rank": 1,
        "prior_limit_count_126": 7,
        "prior_touch_count_126": 10,
        "prior_seal_success_rate_126": seal_rate,
        "path_prefix": {"last_pct": 9.0},
        "outcome": {
            "touched": True,
            "sealed": True,
            "next_close_return_pct": return_pct,
        },
    }
