from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.limit_up.quality_opportunity_reverse import (
    build_opportunity_reverse_frame,
    build_daily_high_return_winner_ledger,
    evaluate_daily_proxy_rescue,
    evaluate_frequency_gate_reverse,
    evaluate_opportunity_reverse,
    frequency_gate_delta_mask,
    frequency_gate_removed_mask,
    opportunity_masks,
)


def test_reverse_frame_joins_closed_trades_and_preserves_gate_reasons() -> None:
    orders = [
        _order("600001.SSE", limit_count=4, sample_count=5, combined_rate=40),
        _order("600002.SSE", limit_count=4, sample_count=4, combined_rate=40),
        _order("600003.SSE", limit_count=4, sample_count=5, combined_rate=20),
        _order("600004.SSE", limit_count=8, sample_count=5, combined_rate=40),
    ]
    trades = [
        _trade("600001.SSE", -1.0),
        _trade("600002.SSE", 6.0),
        _trade("600003.SSE", 2.0),
        _trade("600004.SSE", 8.0),
    ]

    frame = build_opportunity_reverse_frame(orders, trades)

    assert frame["selected_ab"].tolist() == [True, False, False, False]
    assert frame["outcome_group"].tolist() == [
        "selected_loss",
        "excluded_high_return",
        "excluded_positive",
        "excluded_high_return",
    ]
    assert frame.loc[1, "core_quality_gate_reason"] == ("same_stock_d1_samples_below_5")
    assert frame.loc[3, "recognition_gate_reason"] == ("prior_limit_count_126_above_6")


def test_reverse_evaluation_separates_outcome_audit_from_rescue_rule() -> None:
    orders = [
        _order("600001.SSE", limit_count=4, sample_count=5, combined_rate=40),
        _order("600002.SSE", limit_count=8, sample_count=5, combined_rate=40),
        {
            **_order("600003.SSE", limit_count=8, sample_count=5, combined_rate=40),
            "prior_market_phase": "retreat",
        },
    ]
    frame = build_opportunity_reverse_frame(
        orders,
        [
            _trade("600001.SSE", 2.0),
            _trade("600002.SSE", 8.0),
            _trade("600003.SSE", -2.0),
        ],
    )

    masks = opportunity_masks(frame)
    evaluation = evaluate_opportunity_reverse(frame)

    assert masks["profitability_pass_overtraded_market_repair"].tolist() == [
        False,
        True,
        False,
    ]
    assert evaluation["research_rescue"]["incremental"]["closed_count"] == 1
    assert evaluation["research_rescue"]["combined_with_ab"]["closed_count"] == 2
    assert evaluation["coverage"]["selected_trade_days"] == 1


def test_rescue_membership_does_not_change_when_returns_change() -> None:
    orders = [
        _order("600001.SSE", limit_count=8, sample_count=5, combined_rate=40),
        _order("600002.SSE", limit_count=8, sample_count=5, combined_rate=40),
    ]
    original = build_opportunity_reverse_frame(
        orders, [_trade("600001.SSE", 8.0), _trade("600002.SSE", -8.0)]
    )
    reversed_outcomes = build_opportunity_reverse_frame(
        orders, [_trade("600001.SSE", -8.0), _trade("600002.SSE", 8.0)]
    )

    original_mask = opportunity_masks(original)[
        "profitability_pass_overtraded_market_repair"
    ]
    reversed_mask = opportunity_masks(reversed_outcomes)[
        "profitability_pass_overtraded_market_repair"
    ]

    assert original_mask.tolist() == reversed_mask.tolist() == [True, True]


def test_frequency_gate_removed_pool_uses_only_profitability_state() -> None:
    order = _order("600001.SSE", limit_count=8, sample_count=5, combined_rate=40)
    original = build_opportunity_reverse_frame([order], [_trade("600001.SSE", 8.0)])
    changed_outcome = build_opportunity_reverse_frame(
        [order], [_trade("600001.SSE", -8.0)]
    )

    assert frequency_gate_removed_mask(original).tolist() == [True]
    assert frequency_gate_removed_mask(changed_outcome).tolist() == [True]
    assert frequency_gate_delta_mask(original).tolist() == [True]
    assert frequency_gate_delta_mask(changed_outcome).tolist() == [True]


def test_daily_high_return_ledger_keeps_all_same_day_winners() -> None:
    frame = build_opportunity_reverse_frame(
        [
            _order("600001.SSE", limit_count=4, sample_count=5, combined_rate=40),
            _order("600002.SSE", limit_count=8, sample_count=5, combined_rate=40),
        ],
        [_trade("600001.SSE", 6.0), _trade("600002.SSE", 8.0)],
    )

    ledger = build_daily_high_return_winner_ledger(frame)

    assert ledger[
        ["vt_symbol", "frequency_group", "frequency_gate_passed", "daily_high_return_rank", "daily_high_return_count"]
    ].to_dict("records") == [
        {
            "vt_symbol": "600002.SSE",
            "frequency_group": "7-9",
            "frequency_gate_passed": False,
            "daily_high_return_rank": 1,
            "daily_high_return_count": 2,
        },
        {
            "vt_symbol": "600001.SSE",
            "frequency_group": "4-6",
            "frequency_gate_passed": True,
            "daily_high_return_rank": 2,
            "daily_high_return_count": 2,
        },
    ]


def test_frequency_gate_reverse_reports_original_and_removed_gate_by_batch() -> None:
    frame = build_opportunity_reverse_frame(
        [
            _order("600001.SSE", limit_count=4, sample_count=5, combined_rate=40),
            _order("600002.SSE", limit_count=8, sample_count=5, combined_rate=40),
        ],
        [_trade("600001.SSE", 6.0), _trade("600002.SSE", 8.0)],
    )

    result = evaluate_frequency_gate_reverse(frame)
    batch = result["time_batches"]["all"]

    assert result["status"] == "reverse_discovery_only"
    assert result["analysis_layer"] == "ab_base_recognition_gate_only"
    assert batch["original_gate"]["closed_count"] == 1
    assert batch["removed_gate_increment"]["closed_count"] == 1
    assert batch["count_buckets"]["4-6"]["high_return_count"] == 1
    assert batch["count_buckets"]["7-9"]["daily_top_high_return_count"] == 1


def test_reverse_frame_rejects_trade_without_order_evidence() -> None:
    with pytest.raises(ValueError, match="closed trade evidence missing"):
        build_opportunity_reverse_frame(
            [_order("600001.SSE", limit_count=4, sample_count=5, combined_rate=40)],
            [_trade("600002.SSE", 2.0)],
        )


def test_daily_proxy_rescue_reports_earlier_and_observed_periods() -> None:
    frame = pd.DataFrame.from_records(
        [
            _daily_proxy_row(date(2024, 1, 2), 8, "repair", 2.0),
            _daily_proxy_row(date(2026, 7, 1), 9, "repair", -1.0),
            _daily_proxy_row(date(2026, 7, 2), 5, "repair", 3.0),
            _daily_proxy_row(date(2026, 7, 3), 8, "retreat", 4.0),
        ]
    )

    result = evaluate_daily_proxy_rescue(frame)

    assert result["pool"]["closed_count"] == 4
    assert result["incremental"]["closed_count"] == 2
    assert result["before_real_event_coverage"]["closed_count"] == 1
    assert result["observed_event_period"]["closed_count"] == 1


def _order(
    symbol: str,
    *,
    limit_count: int,
    sample_count: int,
    combined_rate: float,
) -> dict[str, object]:
    return {
        "signal_date": "2026-07-01",
        "signal_time": "10:15:00",
        "vt_symbol": symbol,
        "name": symbol,
        "lane": "first_board",
        "prior_limit_count_126": limit_count,
        "stock_d1_sample_count": sample_count,
        "stock_gene_combined_win_rate": combined_rate,
        "prior_industry_turnover_ratio_5d": 1.1,
        "prior_market_phase": "repair",
    }


def _trade(symbol: str, return_pct: float) -> dict[str, object]:
    return {
        "signal_date": "2026-07-01",
        "signal_time": "10:15:00",
        "vt_symbol": symbol,
        "return_pct": return_pct,
    }


def _daily_proxy_row(
    trade_date: date,
    limit_count: int,
    market_phase: str,
    return_pct: float,
) -> dict[str, object]:
    return {
        "trade_date": trade_date,
        "vt_symbol": f"6000{limit_count:02d}.SSE",
        "lane": "first_board",
        "return_pct": return_pct,
        "daily_structural_eligible": True,
        "profitability_gate_passed": True,
        "prior_limit_count_126": limit_count,
        "prior_market_phase": market_phase,
    }
