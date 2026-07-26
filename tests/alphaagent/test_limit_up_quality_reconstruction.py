from datetime import date

import pandas as pd

from alphaagent.server.services.limit_up.quality_reconstruction import (
    attach_legacy_audit_identity,
    attach_quality_fields,
    evaluate_quality_reconstruction,
    quality_rule_masks,
    select_coverage_candidates,
    select_quality_candidates,
)


def test_attach_quality_fields_uses_date_and_symbol_identity() -> None:
    formal = pd.DataFrame.from_records(
        [
            _candidate(date(2026, 7, 1), "600001.SSE", 3.0),
            _candidate(date(2026, 7, 2), "600002.SSE", -2.0),
        ]
    )
    orders = [
        {
            "signal_date": "2026-07-02",
            "vt_symbol": "600002.SSE",
            "prior_limit_count_126": 7,
            "prior_industry_turnover_ratio_5d": 1.4,
        },
        {
            "signal_date": "2026-07-01",
            "vt_symbol": "600001.SSE",
            "prior_limit_count_126": 4,
            "prior_industry_turnover_ratio_5d": 1.1,
        },
    ]

    result = attach_quality_fields(formal, orders)

    assert result["prior_limit_count_126"].tolist() == [4, 7]
    assert result["prior_industry_turnover_ratio_5d"].tolist() == [1.1, 1.4]


def test_fixed_quality_rule_keeps_boundaries_and_requires_expansion() -> None:
    frame = pd.DataFrame.from_records(
        [
            _quality_row(1, 1.2),
            _quality_row(2, 1.0),
            _quality_row(6, 1.5),
            _quality_row(7, 1.2),
            _quality_row(4, 0.99),
        ]
    )

    masks = quality_rule_masks(frame)
    selected = select_quality_candidates(frame)

    assert masks["recognition_2_to_6"].tolist() == [False, True, True, False, True]
    assert masks["industry_turnover_expansion"].tolist() == [True, True, True, True, False]
    assert selected["prior_limit_count_126"].tolist() == [2, 6]


def test_coverage_rule_keeps_all_recognition_candidates_and_assigns_tiers() -> None:
    frame = pd.DataFrame.from_records(
        [
            _quality_row(1, 1.2),
            _quality_row(2, 1.0),
            _quality_row(4, 0.8),
            _quality_row(6, 1.5),
            _quality_row(7, 1.2),
        ]
    )

    selected = select_coverage_candidates(frame)

    assert selected["prior_limit_count_126"].tolist() == [2, 4, 6]
    assert selected["quality_priority_tier"].tolist() == [
        "A_industry_expanding",
        "B_recognition_only",
        "A_industry_expanding",
    ]


def test_evaluation_reports_all_rows_time_slices_months_and_lanes() -> None:
    rows = []
    for sequence, (trade_date, lane, result) in enumerate(
        (
            (date(2025, 3, 3), "first_board", 3.0),
            (date(2025, 4, 1), "two_to_three", -2.0),
            (date(2026, 1, 5), "first_board", 2.0),
            (date(2026, 3, 2), "first_board", 4.0),
            (date(2026, 7, 1), "two_to_three", 1.0),
        ),
        start=1,
    ):
        rows.append(
            {
                **_candidate(trade_date, f"6000{sequence:02d}.SSE", result),
                "lane": lane,
                "prior_limit_count_126": 3,
                "prior_industry_turnover_ratio_5d": 1.1,
            }
        )

    evaluation = evaluate_quality_reconstruction(pd.DataFrame.from_records(rows))
    core = evaluation["factors"]["recognition_and_industry_expansion"]

    assert core["full"]["closed_count"] == 5
    assert core["full"]["win_rate_pct"] == 80.0
    assert core["time_slices"]["2025"]["closed_count"] == 2
    assert core["time_slices"]["2026_01_02"]["closed_count"] == 1
    assert core["time_slices"]["2026_03_07"]["closed_count"] == 2
    assert set(core["monthly"]) == {"2025-03", "2025-04", "2026-01", "2026-03", "2026-07"}
    assert core["lanes"]["first_board"]["closed_count"] == 3
    assert core["lanes"]["two_to_three"]["closed_count"] == 2


def test_legacy_identity_is_audit_only_and_cannot_change_rule_selection(
    monkeypatch,
) -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                **_candidate(date(2026, 7, 1), "600001.SSE", 3.0),
                "prior_limit_count_126": 3,
                "prior_industry_turnover_ratio_5d": 1.1,
            },
            {
                **_candidate(date(2026, 7, 2), "600002.SSE", -2.0),
                "prior_limit_count_126": 8,
                "prior_industry_turnover_ratio_5d": 1.2,
            },
        ]
    )
    legacy = pd.DataFrame.from_records(
        [_candidate(date(2026, 7, 2), "600002.SSE", -2.0)]
    )
    monkeypatch.setattr(
        "alphaagent.server.services.limit_up.quality_reconstruction.extract_formal_recommendations",
        lambda *args, **kwargs: legacy,
    )

    audited = attach_legacy_audit_identity(
        frame,
        [{"trade_date": "2026-07-02"}],
    )

    assert audited["legacy_v14_selected_for_audit"].tolist() == [False, True]
    assert audited["legacy_v14_date_covered_for_audit"].tolist() == [False, True]
    assert select_quality_candidates(audited)["vt_symbol"].tolist() == ["600001.SSE"]


def _candidate(trade_date: date, symbol: str, result: float) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "vt_symbol": symbol,
        "name": symbol,
        "lane": "first_board",
        "signal_time": "10:00:00",
        "pool_rank": 1,
        "return_pct": result,
    }


def _quality_row(limit_count: int, turnover_ratio: float) -> dict[str, object]:
    return {
        "prior_limit_count_126": limit_count,
        "prior_industry_turnover_ratio_5d": turnover_ratio,
    }
