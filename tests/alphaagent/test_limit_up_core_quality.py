import pytest

from alphaagent.server.services.limit_up.core_quality import (
    CORE_QUALITY_CONTRACT_VERSION,
    PUBLIC_QUALITY_CONTRACT_VERSION,
    core_quality_gate,
    filter_core_quality_qualified_orders,
    public_quality_gate,
    recognition_quality_gate,
    quality_tier_priority,
)


def _timed(candidate: dict[str, object], signal_time: str = "10:30:00") -> dict[str, object]:
    return {
        "entry_date": "2026-07-20",
        "signal_time": signal_time,
        "buy_time": signal_time,
        "signal_kind": "first_touch",
        **candidate,
    }


def test_recognition_gate_accepts_two_to_six_and_assigns_priority() -> None:
    a_tier = recognition_quality_gate(
        {
            "prior_limit_count_126": 2,
            "prior_industry_turnover_ratio_5d": 1.0,
        }
    )
    b_tier = recognition_quality_gate(
        {
            "prior_limit_count_126": 6,
            "prior_industry_turnover_ratio_5d": 0.9,
        }
    )

    assert a_tier["recognition_gate_passed"] is True
    assert a_tier["quality_priority_tier"] == "A_industry_expanding"
    assert b_tier["recognition_gate_passed"] is True
    assert b_tier["quality_priority_tier"] == "B_recognition_only"
    assert quality_tier_priority(a_tier) < quality_tier_priority(b_tier)


def test_recognition_gate_rejects_outside_range_and_missing_evidence() -> None:
    below = recognition_quality_gate({"prior_limit_count_126": 1})
    above = recognition_quality_gate({"prior_limit_count_126": 7})
    missing = recognition_quality_gate({})

    assert below["recognition_gate_reason"] == "prior_limit_count_126_below_2"
    assert above["recognition_gate_reason"] == "prior_limit_count_126_above_6"
    assert missing["recognition_gate_reason"] == "prior_limit_count_126_unavailable"
    assert not any(
        decision["recognition_gate_passed"]
        for decision in (below, above, missing)
    )


def test_core_gate_requires_profitability_and_recognition_for_first_board() -> None:
    accepted = core_quality_gate(
        _timed({
            "lane": "first_board",
            "prior_limit_count_126": 3,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 30.0,
        })
    )
    weak_profitability = core_quality_gate(
        _timed({
            "lane": "first_board",
            "prior_limit_count_126": 3,
            "stock_d1_sample_count": 4,
            "stock_gene_combined_win_rate": 80.0,
        })
    )
    overtraded = core_quality_gate(
        _timed({
            "lane": "first_board",
            "prior_limit_count_126": 7,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 80.0,
        })
    )

    assert accepted["core_quality_gate_passed"] is True
    assert weak_profitability["core_quality_gate_passed"] is False
    assert overtraded["core_quality_gate_passed"] is False
    assert accepted["core_quality_contract_version"] == CORE_QUALITY_CONTRACT_VERSION


def test_core_gate_applies_recognition_to_two_to_three_without_profitability() -> None:
    accepted = core_quality_gate(
        _timed({"lane": "two_to_three", "prior_limit_count_126": 4})
    )

    assert accepted["profitability_gate_applies"] is False
    assert accepted["core_quality_gate_passed"] is True


def test_public_quality_uses_abc_prior_and_point_in_time_stock_shrinkage() -> None:
    decision = public_quality_gate(
        _timed(
            {
                "lane": "first_board",
                "prior_limit_count_126": 3,
                "prior_industry_turnover_ratio_5d": 1.1,
                "stock_d1_sample_count": 5,
                "stock_d1_win_rate": 80.0,
                "stock_d1_average_return_pct": 2.0,
                "stock_gene_combined_win_rate": 40.0,
            }
        ),
        trigger_observed=True,
    )

    assert decision["public_quality_contract_version"] == PUBLIC_QUALITY_CONTRACT_VERSION
    assert decision["quality_priority_tier"] == "A_industry_expanding"
    assert decision["quality_tier_prior_sample_count"] == 41
    assert decision["quality_estimate_stock_sample_count"] == 5
    assert decision["quality_win_probability"] == pytest.approx(
        ((35 / 41) * 10 + 0.8 * 5) / 15
    )
    assert decision["quality_expected_d1_net_return_pct"] == pytest.approx(
        (3.0876 * 10 + 2.0 * 5) / 15
    )
    assert decision["public_quality_gate_passed"] is True
    assert decision["public_quality_status"] == "actionable"
    assert decision["public_quality_actionable"] is True


def test_public_quality_becomes_actionable_only_after_real_trigger() -> None:
    candidate = _timed(
        {
            "lane": "two_to_three",
            "prior_limit_count_126": 4,
        }
    )

    untriggered = public_quality_gate(candidate, trigger_observed=False)
    actionable = public_quality_gate(candidate, trigger_observed=True)

    assert untriggered["public_quality_status"] == "rejected"
    assert untriggered["public_quality_reason"] == "trigger_not_observed"
    assert untriggered["public_quality_actionable"] is False
    assert actionable["public_quality_status"] == "actionable"
    assert actionable["public_quality_actionable"] is True
    assert actionable["quality_win_probability"] == pytest.approx(0.60)
    assert actionable["quality_expected_d1_net_return_pct"] == pytest.approx(1.2895)


def test_public_quality_rejects_stock_shrinkage_below_quality_floor() -> None:
    decision = public_quality_gate(
        _timed(
            {
                "lane": "first_board",
                "prior_limit_count_126": 4,
                "stock_d1_sample_count": 10,
                "stock_d1_win_rate": 20.0,
                "stock_d1_average_return_pct": 1.0,
                "stock_gene_combined_win_rate": 40.0,
            }
        ),
        trigger_observed=True,
    )

    assert decision["core_quality_gate_passed"] is True
    assert decision["quality_win_probability"] == pytest.approx(0.40)
    assert decision["public_quality_gate_passed"] is False
    assert decision["public_quality_status"] == "rejected"
    assert decision["public_quality_reason"] == "quality_win_probability_below_50pct"


def test_filter_reports_the_single_core_contract() -> None:
    selected, audit = filter_core_quality_qualified_orders(
        [
            _timed({
                "vt_symbol": "600001.SSE",
                "lane": "two_to_three",
                "prior_limit_count_126": 2,
            }),
            _timed({
                "vt_symbol": "600002.SSE",
                "lane": "two_to_three",
                "prior_limit_count_126": 7,
            }),
        ]
    )

    assert [row["vt_symbol"] for row in selected] == ["600001.SSE"]
    assert selected[0]["quality_priority_tier"] == "B_recognition_only"
    assert audit["contract_version"] == PUBLIC_QUALITY_CONTRACT_VERSION
    assert audit["input_count"] == 2
    assert audit["selected_count"] == 1
    assert audit["reason_counts"] == {
        "qualified": 1,
        "prior_limit_count_126_above_6": 1,
    }


def test_c_rescue_is_first_daily_signal_before_ab_and_ranks_between_a_and_b() -> None:
    c_candidate = _timed(
        {
            "vt_symbol": "600003.SSE",
            "lane": "first_board",
            "prior_limit_count_126": 4,
            "stock_d1_sample_count": 2,
            "stock_gene_combined_win_rate": 20.0,
            "prior_market_phase": "mixed",
            "prior_return_5d_pct": -1.0,
        },
        "10:05:00",
    )
    selected, audit = filter_core_quality_qualified_orders(
        [
            c_candidate,
            {**c_candidate, "vt_symbol": "600004.SSE", "signal_time": "10:06:00", "buy_time": "10:06:00"},
            _timed(
                {
                    "vt_symbol": "600005.SSE",
                    "lane": "first_board",
                    "prior_limit_count_126": 4,
                    "prior_industry_turnover_ratio_5d": 0.8,
                    "stock_d1_sample_count": 5,
                    "stock_gene_combined_win_rate": 40.0,
                }
            ),
        ]
    )

    assert [row["vt_symbol"] for row in selected] == [
        "600003.SSE",
        "600005.SSE",
    ]
    assert selected[0]["quality_priority_tier"] == "C_capital_diffusion_rescue"
    assert audit["tier_counts"] == {
        "B_recognition_only": 1,
        "C_capital_diffusion_rescue": 1,
    }
    assert quality_tier_priority({"quality_priority_tier": "A_industry_expanding"}) < quality_tier_priority(selected[0]) < quality_tier_priority(selected[1])


def test_c_is_rejected_after_a_and_b_first_board_waits_for_1030_or_reseal() -> None:
    a_candidate = _timed(
        {
            "vt_symbol": "600006.SSE",
            "lane": "first_board",
            "prior_limit_count_126": 4,
            "prior_industry_turnover_ratio_5d": 1.1,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 40.0,
        },
        "10:05:00",
    )
    c_candidate = _timed(
        {
            "vt_symbol": "600007.SSE",
            "lane": "first_board",
            "prior_limit_count_126": 4,
            "stock_d1_sample_count": 2,
            "stock_gene_combined_win_rate": 20.0,
            "prior_market_phase": "mixed",
            "prior_return_5d_pct": -1.0,
        },
        "10:10:00",
    )
    early_b = _timed(
        {
            "vt_symbol": "600008.SSE",
            "lane": "first_board",
            "prior_limit_count_126": 4,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 40.0,
        },
        "10:20:00",
    )
    resealed_b = {
        **early_b,
        "vt_symbol": "600009.SSE",
        "event_evidence": {"last_limit_time": "10:35:00", "open_times": 1},
    }

    selected, audit = filter_core_quality_qualified_orders(
        [a_candidate, c_candidate, early_b, resealed_b]
    )

    assert [row["vt_symbol"] for row in selected] == [
        "600006.SSE",
        "600009.SSE",
    ]
    assert selected[1]["buy_time"] == "10:35:00"
    assert selected[1]["signal_kind"] == "reseal"
    assert audit["reason_counts"]["same_stock_d1_samples_below_5"] == 1
    assert audit["reason_counts"]["B_recognition_only_outside_entry_window"] == 1


def test_b_reseal_enters_at_reseal_time_after_an_earlier_c_signal() -> None:
    early_resealed_b = _timed(
        {
            "vt_symbol": "600010.SSE",
            "lane": "first_board",
            "prior_limit_count_126": 4,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 40.0,
            "event_evidence": {"last_limit_time": "10:35:00", "open_times": 1},
        },
        "10:20:00",
    )
    c_candidate = _timed(
        {
            "vt_symbol": "600011.SSE",
            "lane": "first_board",
            "prior_limit_count_126": 4,
            "stock_d1_sample_count": 2,
            "stock_gene_combined_win_rate": 20.0,
            "prior_market_phase": "mixed",
            "prior_return_5d_pct": -1.0,
        }
    )

    selected, _ = filter_core_quality_qualified_orders(
        [early_resealed_b, c_candidate]
    )

    assert [row["vt_symbol"] for row in selected] == [
        "600011.SSE",
        "600010.SSE",
    ]
    assert selected[1]["buy_time"] == "10:35:00"
    assert selected[1]["signal_kind"] == "reseal"


def test_same_second_signals_rank_a_then_c_then_b_without_lookahead() -> None:
    common = {
        "lane": "first_board",
        "prior_limit_count_126": 4,
    }
    a_candidate = _timed(
        {
            **common,
            "vt_symbol": "600012.SSE",
            "prior_industry_turnover_ratio_5d": 1.1,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 40.0,
        }
    )
    c_candidate = _timed(
        {
            **common,
            "vt_symbol": "600013.SSE",
            "stock_d1_sample_count": 2,
            "stock_gene_combined_win_rate": 20.0,
            "prior_market_phase": "mixed",
            "prior_return_5d_pct": -1.0,
        }
    )
    b_candidate = _timed(
        {
            **common,
            "vt_symbol": "600014.SSE",
            "prior_industry_turnover_ratio_5d": 0.8,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 40.0,
        }
    )

    selected, _ = filter_core_quality_qualified_orders(
        [b_candidate, c_candidate, a_candidate]
    )

    assert [row["quality_priority_tier"] for row in selected] == [
        "A_industry_expanding",
        "C_capital_diffusion_rescue",
        "B_recognition_only",
    ]
