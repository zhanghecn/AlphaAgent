from datetime import date
from types import SimpleNamespace

import pandas as pd

from alphaagent.server.services.limit_up.quality_no_trade_reverse import (
    attach_intraday_concept_diffusion_proxy,
    causal_reverse_rule_masks,
    evaluate_causal_reverse,
    evaluate_no_trade_reverse,
    no_ab_trade_day_mask,
    no_prior_ab_trade_mask,
    no_trade_reverse_rule_masks,
    select_causal_reverse_signals,
    selected_causal_reverse_ledger,
)


def test_no_trade_pool_excludes_every_candidate_on_an_ab_trade_day() -> None:
    frame = pd.DataFrame.from_records(
        [
            _row(date(2026, 1, 2), "600001.SSE", selected=True),
            _row(date(2026, 1, 2), "600002.SSE", selected=False),
            _row(date(2026, 1, 3), "600003.SSE", selected=False),
        ]
    )

    assert no_ab_trade_day_mask(frame).tolist() == [False, False, True]


def test_no_prior_ab_trade_mask_keeps_only_rows_before_first_ab_signal() -> None:
    rows = [
        {**_row(date(2026, 7, 20), "600001.SSE", selected=False), "signal_time": "10:10:00"},
        {**_row(date(2026, 7, 20), "600002.SSE", selected=True), "signal_time": "10:20:00"},
        {**_row(date(2026, 7, 20), "600003.SSE", selected=False), "signal_time": "10:30:00"},
        {**_row(date(2026, 7, 21), "600004.SSE", selected=False), "signal_time": "10:30:00"},
    ]

    assert no_prior_ab_trade_mask(pd.DataFrame.from_records(rows)).tolist() == [
        True,
        False,
        False,
        True,
    ]


def test_causal_rule_does_not_consult_later_ab_outcome() -> None:
    rows = [
        {
            **_row(date(2026, 7, 20), "600001.SSE", selected=False, return_pct=8.0),
            "signal_time": "10:10:00",
            "core_quality_gate_reason": "same_stock_d1_samples_below_5",
            "prior_market_phase": "mixed",
            "prior_return_5d_pct": -1.0,
        },
        {
            **_row(date(2026, 7, 20), "600002.SSE", selected=True, return_pct=-5.0),
            "signal_time": "10:20:00",
        },
    ]
    frame = pd.DataFrame.from_records(rows)
    reversed_returns = frame.copy()
    reversed_returns["return_pct"] = [-8.0, 5.0]

    assert causal_reverse_rule_masks(frame)["final_rescue"].tolist() == [True, False]
    assert causal_reverse_rule_masks(reversed_returns)["final_rescue"].tolist() == [
        True,
        False,
    ]


def test_causal_industry_override_requires_pullback_during_broad_rise() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                **_row(date(2026, 7, 20), "600001.SSE", selected=False),
                "prior_market_phase": "broad_rise",
                "prior_return_5d_pct": 3.0,
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
            {
                **_row(date(2026, 7, 21), "600002.SSE", selected=False),
                "prior_market_phase": "broad_rise",
                "prior_return_5d_pct": -3.0,
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
        ]
    )

    assert causal_reverse_rule_masks(frame)["static_industry_override"].tolist() == [
        False,
        True,
    ]
    assert no_trade_reverse_rule_masks(frame)["static_industry_override"].tolist() == [
        True,
        True,
    ]


def test_causal_selection_keeps_only_first_rescue_per_day() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                **_row(date(2026, 7, 20), "600001.SSE", selected=False),
                "signal_time": "10:10:00",
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
            {
                **_row(date(2026, 7, 20), "600002.SSE", selected=False),
                "signal_time": "10:20:00",
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
        ]
    )

    assert select_causal_reverse_signals(frame)["vt_symbol"].tolist() == [
        "600001.SSE"
    ]


def test_causal_evaluation_and_ledger_keep_time_split_and_components() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                **_row(date(2026, 2, 20), "600001.SSE", selected=False),
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
            {
                **_row(date(2026, 3, 2), "600002.SSE", selected=False),
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
        ]
    )

    evaluation = evaluate_causal_reverse(frame)
    ledger = selected_causal_reverse_ledger(frame)

    assert evaluation["incremental"]["closed_count"] == 2
    assert evaluation["incremental_discovery"]["closed_count"] == 1
    assert evaluation["incremental_historical_validation"]["closed_count"] == 1
    assert ledger["static_industry_override"].tolist() == [True, True]


def test_intraday_proxy_prefers_specific_concept_diffusion() -> None:
    trade_date = date(2026, 1, 2)
    frame = pd.DataFrame.from_records(
        [_row(trade_date, "600001.SSE", selected=False)]
    )
    context = SimpleNamespace(
        evidence_level=SimpleNamespace(value="current_membership_survivorship_proxy"),
        snapshot_date=None,
        by_symbol={
            "600001.SSE": ("wide", "specific"),
            "600002.SSE": ("wide", "specific"),
            "600003.SSE": ("wide", "specific"),
            "600004.SSE": ("wide",),
            "600005.SSE": ("wide",),
        },
        by_sector={
            "wide": frozenset(f"wide-{index}" for index in range(100)),
            "specific": frozenset(f"specific-{index}" for index in range(20)),
        },
        member_counts={"wide": 100, "specific": 20},
        sector_names={"wide": "宽泛概念", "specific": "细分概念"},
    )
    events = [
        _event(trade_date, "600002.SSE", "10:01:00", board=2),
        _event(trade_date, "600003.SSE", "10:02:00", board=1),
        _event(trade_date, "600004.SSE", "10:03:00", board=3),
        _event(trade_date, "600005.SSE", "10:04:00", board=1),
    ]

    result = attach_intraday_concept_diffusion_proxy(
        frame,
        events,
        {trade_date: context},
    )

    assert result.loc[0, "intraday_concept_id"] == "specific"
    assert result.loc[0, "intraday_concept_prior_sealed_count"] == 2
    assert result.loc[0, "intraday_concept_candidate_rank"] == 3
    assert result.loc[0, "intraday_concept_prior_max_board"] == 2
    assert result.loc[0, "intraday_concept_membership_evidence_level"] == (
        "current_membership_survivorship_proxy"
    )


def test_frozen_reverse_rule_covers_static_and_concept_groups() -> None:
    rows = [
        {
            **_row(date(2026, 1, 2), "600001.SSE", selected=False),
            "core_quality_gate_reason": "same_stock_d1_samples_below_5",
            "prior_market_phase": "mixed",
            "prior_return_5d_pct": -1.0,
        },
        {
            **_row(date(2026, 1, 3), "600002.SSE", selected=False),
            "prior_industry_turnover_ratio_5d": 1.2,
            "stock_gene_combined_win_rate": 20.0,
        },
        {
            **_row(date(2026, 3, 2), "600003.SSE", selected=False),
            "prior_market_phase": "mixed",
            "intraday_concept_prior_sealed_count": 3,
            "intraday_concept_prior_max_board": 2,
        },
        {
            **_row(date(2026, 3, 3), "600004.SSE", selected=False),
            "signal_kind": "reseal",
            "prior_market_phase": "retreat",
            "prior_return_5d_pct": -2.0,
            "intraday_concept_prior_sealed_count": 4,
            "intraday_concept_prior_max_board": 3,
        },
        _row(date(2026, 3, 4), "600005.SSE", selected=False),
    ]
    frame = pd.DataFrame.from_records(rows)

    masks = no_trade_reverse_rule_masks(frame)

    assert masks["static_mixed_pullback"].tolist() == [
        True,
        False,
        False,
        False,
        False,
    ]
    assert masks["static_industry_override"].tolist() == [
        False,
        True,
        False,
        False,
        False,
    ]
    assert masks["concept_mixed_first_touch"].tolist() == [
        False,
        False,
        True,
        False,
        False,
    ]
    assert masks["concept_pullback_diffusion"].tolist() == [
        False,
        False,
        False,
        True,
        False,
    ]
    assert masks["final_rescue"].tolist() == [True, True, True, True, False]


def test_reverse_rule_membership_does_not_change_with_d1_returns() -> None:
    frame = pd.DataFrame.from_records(
        [
            {
                **_row(date(2026, 1, 2), "600001.SSE", selected=False),
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
                "return_pct": 8.0,
            },
            {
                **_row(date(2026, 1, 3), "600002.SSE", selected=False),
                "return_pct": -8.0,
            },
        ]
    )
    reversed_returns = frame.copy()
    reversed_returns["return_pct"] = [-8.0, 8.0]

    original = no_trade_reverse_rule_masks(frame)["final_rescue"]
    reversed_mask = no_trade_reverse_rule_masks(reversed_returns)["final_rescue"]

    assert original.tolist() == reversed_mask.tolist() == [True, False]


def test_reverse_evaluation_uses_only_no_trade_days_as_research_pool() -> None:
    frame = pd.DataFrame.from_records(
        [
            _row(date(2026, 1, 2), "600001.SSE", selected=True, return_pct=2.0),
            _row(date(2026, 1, 2), "600002.SSE", selected=False, return_pct=8.0),
            {
                **_row(
                    date(2026, 1, 3),
                    "600003.SSE",
                    selected=False,
                    return_pct=8.0,
                ),
                "prior_industry_turnover_ratio_5d": 1.2,
                "stock_gene_combined_win_rate": 20.0,
            },
        ]
    )

    evaluation = evaluate_no_trade_reverse(frame)

    assert evaluation["coverage"]["no_ab_trade_days"] == 1
    assert evaluation["coverage"]["no_ab_trade_day_candidate_count"] == 1
    assert evaluation["factors"]["final_rescue"]["full"]["closed_count"] == 1
    assert evaluation["combined"]["closed_count"] == 2


def _row(
    trade_date: date,
    symbol: str,
    *,
    selected: bool,
    return_pct: float = 1.0,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "signal_date": trade_date,
        "signal_time": "10:30:00",
        "signal_kind": "first_touch",
        "pool_rank": 1,
        "vt_symbol": symbol,
        "selected_ab": selected,
        "return_pct": return_pct,
        "core_quality_gate_reason": "prior_limit_count_126_above_6",
        "prior_market_phase": "retreat",
        "prior_return_5d_pct": 1.0,
        "prior_industry_turnover_ratio_5d": 0.8,
        "stock_gene_combined_win_rate": 40.0,
        "intraday_concept_prior_sealed_count": 0,
        "intraday_concept_prior_max_board": 0,
    }


def _event(
    trade_date: date,
    symbol: str,
    event_time: str,
    *,
    board: int,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "vt_symbol": symbol,
        "first_limit_time": event_time,
        "is_limit_up": True,
        "limit_up_streak": board,
    }
