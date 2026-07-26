from alphaagent.server.services.limit_up.core_quality import (
    CORE_QUALITY_CONTRACT_VERSION,
    core_quality_gate,
    filter_core_quality_qualified_orders,
    recognition_quality_gate,
    quality_tier_priority,
)


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
        {
            "lane": "first_board",
            "prior_limit_count_126": 3,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 30.0,
        }
    )
    weak_profitability = core_quality_gate(
        {
            "lane": "first_board",
            "prior_limit_count_126": 3,
            "stock_d1_sample_count": 4,
            "stock_gene_combined_win_rate": 80.0,
        }
    )
    overtraded = core_quality_gate(
        {
            "lane": "first_board",
            "prior_limit_count_126": 7,
            "stock_d1_sample_count": 5,
            "stock_gene_combined_win_rate": 80.0,
        }
    )

    assert accepted["core_quality_gate_passed"] is True
    assert weak_profitability["core_quality_gate_passed"] is False
    assert overtraded["core_quality_gate_passed"] is False
    assert accepted["core_quality_contract_version"] == CORE_QUALITY_CONTRACT_VERSION


def test_core_gate_applies_recognition_to_two_to_three_without_profitability() -> None:
    accepted = core_quality_gate(
        {"lane": "two_to_three", "prior_limit_count_126": 4}
    )

    assert accepted["profitability_gate_applies"] is False
    assert accepted["core_quality_gate_passed"] is True


def test_filter_reports_the_single_core_contract() -> None:
    selected, audit = filter_core_quality_qualified_orders(
        [
            {
                "vt_symbol": "600001.SSE",
                "lane": "two_to_three",
                "prior_limit_count_126": 2,
            },
            {
                "vt_symbol": "600002.SSE",
                "lane": "two_to_three",
                "prior_limit_count_126": 7,
            },
        ]
    )

    assert [row["vt_symbol"] for row in selected] == ["600001.SSE"]
    assert selected[0]["quality_priority_tier"] == "B_recognition_only"
    assert audit["contract_version"] == CORE_QUALITY_CONTRACT_VERSION
    assert audit["input_count"] == 2
    assert audit["selected_count"] == 1
    assert audit["reason_counts"] == {
        "qualified": 1,
        "prior_limit_count_126_above_6": 1,
    }
