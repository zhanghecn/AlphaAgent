from __future__ import annotations

from copy import deepcopy

from alphaagent.server.services.limit_up.first_board_stock_gene_research import (
    attach_prior_all_touch_d1_evidence_to_orders,
    attach_prior_stock_gene_evidence_to_orders,
    build_causal_first_board_recommendation_report,
    build_first_board_stock_gene_ranking_report,
    combined_stock_gene_win_rate,
    rank_stock_gene_candidates,
    select_causal_first_board_candidate,
    select_first_signal_group_candidate,
)


def test_scheduled_orders_receive_only_prior_same_stock_evidence() -> None:
    days = [
        _day(
            "2026-01-02",
            [
                _event("600001.SSE", "2026-01-05", return_pct=2.0),
                _event("600002.SSE", "2026-01-05", return_pct=9.0),
            ],
        ),
        _day(
            "2026-01-03",
            [_event("600001.SSE", "2026-01-05", return_pct=-1.0)],
        ),
        _day(
            "2026-01-05",
            [_event("600001.SSE", "2026-01-06", return_pct=8.0)],
        ),
        _day("2026-01-06", []),
    ]
    orders = [
        {
            "vt_symbol": "600001.SSE",
            "lane": "first_board",
            "signal_date": "2026-01-06",
            "prior_limit_count_126": 8,
            "prior_touch_count_126": 10,
            "prior_seal_success_rate_126": 0.8,
        },
        {
            "vt_symbol": "600099.SSE",
            "lane": "two_to_three",
            "signal_date": "2026-01-06",
        },
    ]

    enriched = attach_prior_stock_gene_evidence_to_orders(days, orders)

    assert [row["vt_symbol"] for row in enriched] == [
        "600001.SSE",
        "600099.SSE",
    ]
    assert enriched[0]["stock_d1_sample_count"] == 2
    assert enriched[0]["stock_d1_win_count"] == 1
    assert enriched[0]["stock_d1_win_rate"] == 50.0
    assert enriched[0]["stock_gene_seal_rate"] == 80.0
    assert enriched[0]["stock_gene_combined_win_rate"] == 40.0
    assert "stock_d1_sample_count" not in enriched[1]


def test_all_touch_d1_evidence_includes_failed_seals() -> None:
    failed = _event("600001.SSE", "2026-01-05", return_pct=-4.0)
    failed["outcome"]["sealed"] = False
    days = [
        _day(
            "2026-01-02",
            [
                _event("600001.SSE", "2026-01-05", return_pct=2.0),
                failed,
            ],
        ),
        _day("2026-01-05", []),
        _day("2026-01-06", []),
    ]
    orders = [
        {
            "vt_symbol": "600001.SSE",
            "lane": "first_board",
            "signal_date": "2026-01-06",
        }
    ]

    sealed_only = attach_prior_stock_gene_evidence_to_orders(days, orders)[0]
    all_touches = attach_prior_all_touch_d1_evidence_to_orders(days, orders)[0]

    assert sealed_only["stock_d1_sample_count"] == 1
    assert sealed_only["stock_d1_win_rate"] == 100.0
    assert all_touches["stock_all_touch_d1_sample_count"] == 2
    assert all_touches["stock_all_touch_d1_win_count"] == 1
    assert all_touches["stock_all_touch_d1_win_rate"] == 50.0
    assert all_touches["stock_all_touch_d1_average_return_pct"] == -1.0


def test_combined_stock_gene_win_rate_multiplies_stock_rates() -> None:
    assert combined_stock_gene_win_rate(70.0, 60.0) == 42.0
    assert combined_stock_gene_win_rate(0.0, 60.0) == 0.0
    assert combined_stock_gene_win_rate(70.0, 0.0) == 0.0
    assert combined_stock_gene_win_rate(None, 60.0) is None
    assert combined_stock_gene_win_rate(70.0, None) is None
    assert combined_stock_gene_win_rate(-0.1, 60.0) is None
    assert combined_stock_gene_win_rate(70.0, 100.1) is None


def test_stock_gene_rank_uses_rate_then_earlier_signal() -> None:
    rows = [
        _candidate("600001.SSE", "10:20:00", combined_rate=48.0),
        _candidate("600002.SSE", "10:10:00", combined_rate=48.0),
        _candidate("600003.SSE", "10:05:00", combined_rate=40.0),
        _candidate("600004.SSE", "10:00:00", combined_rate=None),
    ]

    ranked = rank_stock_gene_candidates(rows)

    assert [row["vt_symbol"] for row in ranked] == [
        "600002.SSE",
        "600001.SSE",
        "600003.SSE",
        "600004.SSE",
    ]


def test_causal_selector_keeps_earlier_passing_candidate() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", combined_rate=52.0, samples=5),
        _scored("600002.SSE", "13:10:00", combined_rate=90.0, samples=20),
    ]

    selected = select_causal_first_board_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert selected is not None
    assert selected["vt_symbol"] == "600001.SSE"


def test_causal_selector_can_skip_earlier_failed_candidate() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", combined_rate=49.0, samples=5),
        _scored("600002.SSE", "13:10:00", combined_rate=60.0, samples=5),
    ]

    selected = select_causal_first_board_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert selected is not None
    assert selected["vt_symbol"] == "600002.SSE"


def test_later_candidate_mutation_cannot_replace_locked_selection() -> None:
    original = [
        _scored("600001.SSE", "10:05:00", combined_rate=52.0, samples=5),
        _scored("600002.SSE", "13:10:00", combined_rate=51.0, samples=5),
    ]
    mutated = deepcopy(original)
    mutated[1]["stock_gene_combined_win_rate"] = 100.0
    mutated.append(
        _scored("600003.SSE", "14:20:00", combined_rate=100.0, samples=30)
    )

    original_selected = select_causal_first_board_candidate(
        original,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )
    mutated_selected = select_causal_first_board_candidate(
        mutated,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert original_selected is not None
    assert mutated_selected is not None
    assert original_selected["vt_symbol"] == "600001.SSE"
    assert mutated_selected["vt_symbol"] == "600001.SSE"


def test_causal_selector_ranks_only_simultaneous_passing_candidates() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", combined_rate=52.0, samples=5),
        _scored("600002.SSE", "10:05:00", combined_rate=60.0, samples=5),
        _scored("600003.SSE", "10:06:00", combined_rate=90.0, samples=10),
    ]

    selected = select_causal_first_board_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert selected is not None
    assert selected["vt_symbol"] == "600002.SSE"


def test_causal_selector_skips_insufficient_history() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", combined_rate=90.0, samples=4),
        _scored("600002.SSE", "10:10:00", combined_rate=55.0, samples=5),
    ]

    selected = select_causal_first_board_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert selected is not None
    assert selected["vt_symbol"] == "600002.SSE"


def test_first_group_gate_does_not_wait_for_later_candidate() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", combined_rate=49.0, samples=5),
        _scored("600002.SSE", "13:10:00", combined_rate=100.0, samples=20),
    ]

    selected = select_first_signal_group_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert selected is None


def test_first_group_gate_ranks_only_rows_at_first_signal_time() -> None:
    rows = [
        _scored("600001.SSE", "10:05:00", combined_rate=52.0, samples=5),
        _scored("600002.SSE", "10:05:00", combined_rate=60.0, samples=5),
        _scored("600003.SSE", "10:06:00", combined_rate=90.0, samples=10),
    ]

    selected = select_first_signal_group_candidate(
        rows,
        min_d1_samples=5,
        min_combined_rate=50.0,
    )

    assert selected is not None
    assert selected["vt_symbol"] == "600002.SSE"


def test_report_uses_only_matured_same_stock_first_board_history() -> None:
    days = [
        _day(
            "2026-01-02",
            [
                _event("600001.SSE", "2026-01-05", return_pct=2.0),
                _event("600002.SSE", "2026-01-05", return_pct=-1.0),
                _event("600099.SSE", "2026-01-05", return_pct=8.0),
                _event("600001.SSE", "2026-01-07", return_pct=9.0),
            ],
        ),
        _day(
            "2026-01-05",
            [_event("600001.SSE", "2026-01-06", return_pct=3.0)],
        ),
        _day(
            "2026-01-07",
            [
                _eligible(
                    "600001.SSE",
                    "10:20:00",
                    result_date="2026-01-08",
                    seal_rate=0.70,
                    return_pct=-5.0,
                    pool_rank=2,
                ),
                _eligible(
                    "600002.SSE",
                    "10:10:00",
                    result_date="2026-01-08",
                    seal_rate=0.90,
                    return_pct=5.0,
                    pool_rank=1,
                ),
            ],
            phase="locked_holdout",
        ),
    ]

    report = build_first_board_stock_gene_ranking_report(
        days,
        history_window_days=252,
        min_d1_samples=1,
        top_n=1,
    )

    selection = report["variants"]["combined"]["selections"][0]
    assert selection["vt_symbol"] == "600001.SSE"
    assert selection["stock_d1_sample_count"] == 2
    assert selection["stock_d1_win_count"] == 2
    assert selection["stock_d1_win_rate"] == 100.0
    assert selection["stock_gene_seal_rate"] == 70.0
    assert selection["stock_gene_combined_win_rate"] == 70.0


def test_current_outcome_cannot_change_stock_history_or_selection() -> None:
    original = _ranking_days()
    mutated = deepcopy(original)
    current = mutated[-1]["lane_portfolio"]["candidate_pool"]["first_board"]
    current[0]["outcome"].update(sealed=False, next_close_return_pct=-9.0)
    current[1]["outcome"].update(sealed=True, next_close_return_pct=9.0)

    original_report = build_first_board_stock_gene_ranking_report(
        original,
        history_window_days=252,
        min_d1_samples=1,
        top_n=1,
    )
    mutated_report = build_first_board_stock_gene_ranking_report(
        mutated,
        history_window_days=252,
        min_d1_samples=1,
        top_n=1,
    )

    assert (
        original_report["variants"]["combined"]["selections"]
        == mutated_report["variants"]["combined"]["selections"]
    )


def test_history_window_and_minimum_sample_are_enforced() -> None:
    days = [
        _day(
            "2026-01-02",
            [_event("600001.SSE", "2026-01-05", return_pct=2.0)],
        ),
        _day("2026-01-05", []),
        _day(
            "2026-01-06",
            [
                _eligible(
                    "600001.SSE",
                    "10:10:00",
                    result_date="2026-01-07",
                    seal_rate=0.70,
                    return_pct=2.0,
                )
            ],
        ),
    ]

    expired = build_first_board_stock_gene_ranking_report(
        days,
        history_window_days=1,
        min_d1_samples=1,
        top_n=1,
    )
    insufficient = build_first_board_stock_gene_ranking_report(
        days,
        history_window_days=2,
        min_d1_samples=2,
        top_n=1,
    )
    ready = build_first_board_stock_gene_ranking_report(
        days,
        history_window_days=2,
        min_d1_samples=1,
        top_n=1,
    )

    assert expired["coverage"]["evaluated_day_count"] == 0
    assert insufficient["coverage"]["sample_qualified_candidate_count"] == 0
    assert ready["coverage"]["evaluated_day_count"] == 1
    assert (
        ready["variants"]["combined"]["selections"][0][
            "stock_d1_sample_count"
        ]
        == 1
    )


def test_report_compares_four_top1_variants_on_the_same_universe() -> None:
    report = build_first_board_stock_gene_ranking_report(
        _two_ranking_days(),
        history_window_days=252,
        min_d1_samples=1,
        top_n=1,
    )

    assert report["status"] == "invalid_for_execution"
    assert report["execution_valid"] is False
    assert report["mode"] == "daily_candidate_availability_lookahead_proxy"
    assert set(report["variants"]) == {
        "baseline",
        "gene_only",
        "d1_only",
        "combined",
    }
    assert {
        payload["summary"]["trade_count"]
        for payload in report["variants"].values()
    } == {2}
    assert report["ranking_contract"]["top_n"] == 1
    assert report["ranking_contract"]["secondary"] == "signal_time_asc"
    assert report["coverage"] == {
        "history_day_count": 3,
        "eligible_candidate_count": 4,
        "sample_qualified_candidate_count": 4,
        "eligible_day_count": 2,
        "evaluated_day_count": 2,
        "no_pick_day_count": 0,
        "combined_rate_distribution": {
            "count": 4,
            "distinct_count": 2,
            "minimum": 0.0,
            "median": 35.0,
            "maximum": 70.0,
        },
        "d1_sample_count_distribution": {
            "count": 4,
            "distinct_count": 1,
            "minimum": 1.0,
            "median": 1.0,
            "maximum": 1.0,
        },
    }
    assert [
        row["vt_symbol"]
        for row in report["variants"]["baseline"]["selections"]
    ] == ["600002.SSE", "600002.SSE"]
    assert [
        row["vt_symbol"]
        for row in report["variants"]["combined"]["selections"]
    ] == ["600001.SSE", "600001.SSE"]


def test_causal_report_builds_frozen_event_time_variants() -> None:
    report = build_causal_first_board_recommendation_report(
        _two_ranking_days(),
        history_window_days=252,
        min_d1_samples=1,
        thresholds=(45.0, 50.0, 55.0),
    )

    assert set(report["variants"]) == {
        "first_eligible",
        "first_sampled",
        "first_combined_45",
        "first_combined_50",
        "first_combined_55",
        "combined_45",
        "combined_50",
        "combined_55",
    }
    assert report["ranking_contract"]["candidate_availability"] == (
        "signal_time_causal"
    )
    assert [
        row["vt_symbol"]
        for row in report["variants"]["first_eligible"]["selections"]
    ] == ["600002.SSE", "600002.SSE"]
    assert [
        row["vt_symbol"]
        for row in report["variants"]["combined_50"]["selections"]
    ] == ["600001.SSE", "600001.SSE"]
    assert report["variants"]["first_combined_50"]["summary"][
        "trade_count"
    ] == 0
    assert report["variants"]["combined_50"]["summary"]["trade_count"] == 2


def test_causal_report_cannot_replace_early_pick_with_later_higher_score() -> None:
    days = [
        _day(
            "2026-01-02",
            [
                _event("600001.SSE", "2026-01-05", return_pct=2.0),
                _event("600002.SSE", "2026-01-05", return_pct=2.0),
            ],
        ),
        _day(
            "2026-01-06",
            [
                _eligible(
                    "600001.SSE",
                    "10:05:00",
                    result_date="2026-01-07",
                    seal_rate=0.60,
                    return_pct=-2.0,
                    pool_rank=1,
                ),
                _eligible(
                    "600002.SSE",
                    "13:10:00",
                    result_date="2026-01-07",
                    seal_rate=0.90,
                    return_pct=9.0,
                    pool_rank=2,
                ),
            ],
        ),
    ]

    report = build_causal_first_board_recommendation_report(
        days,
        history_window_days=252,
        min_d1_samples=1,
        thresholds=(50.0,),
    )

    selection = report["variants"]["combined_50"]["selections"][0]
    assert selection["vt_symbol"] == "600001.SSE"
    assert selection["signal_time"] == "10:05:00"
    assert selection["stock_gene_combined_win_rate"] == 60.0
    first_selection = report["variants"]["first_combined_50"]["selections"][0]
    assert first_selection["vt_symbol"] == "600001.SSE"


def test_causal_report_does_not_require_current_future_outcome() -> None:
    days = [
        _day(
            "2026-01-02",
            [_event("600001.SSE", "2026-01-05", return_pct=2.0)],
        ),
        _day(
            "2026-01-06",
            [
                _eligible(
                    "600001.SSE",
                    "10:05:00",
                    result_date="2026-01-07",
                    seal_rate=0.60,
                    return_pct=None,
                    pool_rank=1,
                ),
                _eligible(
                    "600002.SSE",
                    "13:10:00",
                    result_date="2026-01-07",
                    seal_rate=0.90,
                    return_pct=9.0,
                    pool_rank=2,
                ),
            ],
        ),
    ]

    report = build_causal_first_board_recommendation_report(
        days,
        history_window_days=252,
        min_d1_samples=1,
        thresholds=(50.0,),
    )

    selections = report["variants"]["first_combined_50"]["selections"]
    assert [row["vt_symbol"] for row in selections] == ["600001.SSE"]
    summary = report["variants"]["first_combined_50"]["summary"]
    assert summary["selection_count"] == 1
    assert summary["trade_count"] == 0
    assert summary["pending_count"] == 1


def test_report_rejects_invalid_research_parameters() -> None:
    days = _ranking_days()

    for kwargs in (
        {"history_window_days": 0},
        {"min_d1_samples": 0},
        {"top_n": 0},
    ):
        try:
            build_first_board_stock_gene_ranking_report(days, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {kwargs}")


def _candidate(
    vt_symbol: str,
    signal_time: str,
    *,
    combined_rate: float | None,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "signal_time": signal_time,
        "stock_gene_combined_win_rate": combined_rate,
    }


def _scored(
    vt_symbol: str,
    signal_time: str,
    *,
    combined_rate: float,
    samples: int,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "signal_time": signal_time,
        "stock_gene_combined_win_rate": combined_rate,
        "stock_d1_sample_count": samples,
    }


def _ranking_days() -> list[dict[str, object]]:
    return [
        _day(
            "2026-01-02",
            [
                _event("600001.SSE", "2026-01-05", return_pct=2.0),
                _event("600002.SSE", "2026-01-05", return_pct=-1.0),
            ],
        ),
        _day(
            "2026-01-06",
            [
                _eligible(
                    "600001.SSE",
                    "10:20:00",
                    result_date="2026-01-07",
                    seal_rate=0.70,
                    return_pct=-2.0,
                    pool_rank=2,
                ),
                _eligible(
                    "600002.SSE",
                    "10:10:00",
                    result_date="2026-01-07",
                    seal_rate=0.90,
                    return_pct=2.0,
                    pool_rank=1,
                ),
            ],
        ),
    ]


def _two_ranking_days() -> list[dict[str, object]]:
    return [
        _day(
            "2026-01-02",
            [
                _event("600001.SSE", "2026-01-05", return_pct=2.0),
                _event("600002.SSE", "2026-01-05", return_pct=-1.0),
            ],
        ),
        _day(
            "2026-01-06",
            [
                _eligible(
                    "600001.SSE",
                    "10:20:00",
                    result_date="2026-01-10",
                    seal_rate=0.70,
                    return_pct=-2.0,
                    pool_rank=2,
                ),
                _eligible(
                    "600002.SSE",
                    "10:10:00",
                    result_date="2026-01-10",
                    seal_rate=0.90,
                    return_pct=2.0,
                    pool_rank=1,
                ),
            ],
        ),
        _day(
            "2026-01-07",
            [
                _eligible(
                    "600001.SSE",
                    "10:30:00",
                    result_date="2026-01-10",
                    seal_rate=0.70,
                    return_pct=3.0,
                    pool_rank=2,
                ),
                _eligible(
                    "600002.SSE",
                    "10:05:00",
                    result_date="2026-01-10",
                    seal_rate=0.90,
                    return_pct=-3.0,
                    pool_rank=1,
                ),
            ],
        ),
    ]


def _day(
    trade_date: str,
    candidates: list[dict[str, object]],
    *,
    phase: str = "expanding_oos",
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "validation_phase": phase,
        "lane_portfolio": {
            "candidate_pool": {"first_board": candidates},
        },
    }


def _event(
    vt_symbol: str,
    result_date: str,
    *,
    return_pct: float | None,
    sealed: bool = True,
    touched: bool = True,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "lane": "first_board",
        "decision": "blocked",
        "signal_time": "10:00:00",
        "result_date": result_date,
        "outcome": {
            "touched": touched,
            "sealed": sealed,
            "next_close_return_pct": return_pct,
        },
    }


def _eligible(
    vt_symbol: str,
    signal_time: str,
    *,
    result_date: str,
    seal_rate: float,
    return_pct: float,
    pool_rank: int = 1,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "lane": "first_board",
        "decision": "eligible",
        "signal_time": signal_time,
        "entry_date": result_date,
        "result_date": result_date,
        "entry_price": 10.0,
        "pool_rank": pool_rank,
        "validation_phase": "locked_holdout",
        "prior_limit_count_126": 7,
        "prior_touch_count_126": 10,
        "prior_seal_success_rate_126": seal_rate,
        "outcome": {
            "touched": True,
            "sealed": True,
            "next_close_return_pct": return_pct,
        },
    }
