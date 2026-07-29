from __future__ import annotations

from alphaagent.server.services.limit_up.all_touch_d1_gate_research import (
    all_touch_profitability_gate,
    select_ab_orders,
)


def test_all_touch_gate_keeps_seal_and_d1_as_separate_requirements() -> None:
    candidate = _candidate(seal_rate=45.0, d1_win_rate=60.0)

    passed = all_touch_profitability_gate(
        candidate,
        minimum_seal_rate=40.0,
        minimum_d1_win_rate=60.0,
    )
    seal_failed = all_touch_profitability_gate(
        candidate,
        minimum_seal_rate=50.0,
        minimum_d1_win_rate=60.0,
    )

    assert passed["all_touch_profitability_gate_passed"] is True
    assert seal_failed["all_touch_profitability_gate_passed"] is False
    assert seal_failed["all_touch_profitability_gate_reason"] == (
        "seal_rate_below_minimum"
    )


def test_all_touch_gate_requires_five_prior_outcomes() -> None:
    candidate = _candidate(seal_rate=80.0, d1_win_rate=100.0)
    candidate["stock_all_touch_d1_sample_count"] = 4

    decision = all_touch_profitability_gate(
        candidate,
        minimum_seal_rate=40.0,
        minimum_d1_win_rate=50.0,
    )

    assert decision["all_touch_profitability_gate_passed"] is False
    assert decision["all_touch_profitability_gate_reason"] == (
        "all_touch_d1_samples_below_minimum"
    )


def test_ab_counterfactual_uses_all_touch_return_estimates() -> None:
    candidate = _candidate(seal_rate=50.0, d1_win_rate=60.0)
    candidate.update(
        {
            "stock_d1_sample_count": 5,
            "stock_d1_win_rate": 20.0,
            "stock_d1_average_return_pct": -5.0,
            "stock_gene_combined_win_rate": 10.0,
        }
    )

    current = select_ab_orders([candidate])
    counterfactual = select_ab_orders(
        [candidate],
        minimum_seal_rate=40.0,
        minimum_d1_win_rate=50.0,
    )

    assert current == []
    assert len(counterfactual) == 1
    assert counterfactual[0]["stock_d1_win_rate"] == 60.0
    assert counterfactual[0]["stock_d1_average_return_pct"] == 2.0
    assert counterfactual[0]["quality_priority_tier"] == "A_industry_expanding"


def _candidate(*, seal_rate: float, d1_win_rate: float) -> dict[str, object]:
    return {
        "signal_date": "2026-07-01",
        "signal_time": "10:15:00",
        "first_limit_time": "10:15:00",
        "signal_kind": "first_touch",
        "vt_symbol": "600001.SSE",
        "lane": "first_board",
        "prior_limit_count_126": 4,
        "prior_industry_turnover_ratio_5d": 1.2,
        "stock_gene_seal_rate": seal_rate,
        "stock_all_touch_d1_sample_count": 10,
        "stock_all_touch_d1_win_rate": d1_win_rate,
        "stock_all_touch_d1_average_return_pct": 2.0,
    }
