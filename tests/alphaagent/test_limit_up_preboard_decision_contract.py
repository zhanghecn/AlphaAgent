from datetime import date

import pytest

from alphaagent.server.services.limit_up.preboard_decision_contract import (
    PREBOARD_DECISION_VERSION,
    HistoricalPrior,
    PreboardExecutionMode,
    PreboardPolicyThresholds,
    PreboardState,
    historical_prior_from_evidence,
    historical_prior_status,
    is_observable_first_board,
    is_strictly_preboard,
)


def test_only_quality_first_board_at_or_above_three_percent_is_observable() -> None:
    eligible = {
        "board_lane": "first_board",
        "quality_gate_passed": True,
        "public_quality_contract_version": "limit-up-core-abc-v2",
        "public_quality_status": "qualified_waiting_trigger",
        "public_quality_preparation_passed": True,
        "quality_win_probability": 0.70,
        "quality_expected_d1_net_return_pct": 1.5,
        "change_pct": 3.0,
    }

    assert is_observable_first_board(eligible)
    assert not is_observable_first_board({**eligible, "change_pct": 2.999})
    assert not is_observable_first_board(
        {
            **eligible,
            "public_quality_preparation_passed": False,
            "change_pct": 9.5,
        }
    )
    assert not is_observable_first_board({**eligible, "board_lane": "two_to_three"})


@pytest.mark.parametrize("state", ["sealed", "resealed", "failed"])
def test_touched_state_is_never_strictly_preboard(state: str) -> None:
    assert not is_strictly_preboard(
        {"state": state, "last_price": 9.8, "limit_price": 10.0}
    )


def test_strictly_preboard_requires_fresh_prices_below_limit() -> None:
    assert is_strictly_preboard(
        {"state": "near_limit", "last_price": 9.99, "limit_price": 10.0}
    )
    assert not is_strictly_preboard(
        {"state": "near_limit", "last_price": 10.0, "limit_price": 10.0}
    )
    assert not is_strictly_preboard(
        {"state": "near_limit", "last_price": None, "limit_price": 10.0}
    )


def test_historical_prior_reuses_existing_evidence_and_normalizes_percentages() -> None:
    prior = historical_prior_from_evidence(
        {
            "average_return_pct": 2.4,
            "smoothed_win_rate": 68.0,
            "seal_success_rate": 75.0,
            "d1_money_effect_win_rate": 64.0,
            "d1_money_effect_average_return_pct": 2.4,
            "effective_sample_count": 81,
            "stock_gene_touch_count": 12,
            "d1_money_effect_sample_count": 7,
            "as_of_date": "2026-07-20",
        }
    )

    assert prior == HistoricalPrior(
        expected_d1_net_return_pct=2.4,
        d1_win_probability=0.64,
        seal_probability_given_touch=0.75,
        d1_win_probability_given_seal=0.64,
        analog_sample_count=81,
        stock_touch_sample_count=12,
        stock_d1_sample_count=7,
        as_of_date=date(2026, 7, 20),
    )
    assert historical_prior_status(prior) == "ready"
    assert prior.touch_seal_probability(0.6) == pytest.approx(0.45)
    assert prior.touch_seal_d1_win_probability(0.6) == pytest.approx(0.288)


def test_missing_historical_prior_field_does_not_turn_into_zero() -> None:
    prior = historical_prior_from_evidence(
        {
            "average_return_pct": 2.4,
            "smoothed_win_rate": 68.0,
            "seal_success_rate": 75.0,
            "d1_money_effect_win_rate": None,
        }
    )

    assert prior.d1_win_probability_given_seal is None
    assert historical_prior_status(prior) == "incomplete"


def test_historical_prior_uses_same_stock_d1_gene_not_path_analogs() -> None:
    prior = historical_prior_from_evidence(
        {
            "as_of_date": "2026-07-20",
            "average_return_pct": -9.0,
            "smoothed_win_rate": 10.0,
            "effective_sample_count": 80,
            "stock_gene_touch_count": 8,
            "seal_success_rate": 75.0,
            "d1_money_effect_sample_count": 15,
            "d1_money_effect_win_rate": 86.67,
            "d1_money_effect_average_return_pct": 4.6403,
        }
    )

    assert prior.expected_d1_net_return_pct == 4.6403
    assert prior.d1_win_probability == 0.8667


def test_probability_contract_rejects_out_of_range_values() -> None:
    prior = historical_prior_from_evidence({"seal_success_rate": 75.0})
    with pytest.raises(ValueError, match="touch_probability"):
        prior.touch_seal_probability(1.01)

    with pytest.raises(ValueError, match="minimum_eventual_touch_probability"):
        PreboardPolicyThresholds(
            minimum_touch_probability_3m=0.5,
            minimum_eventual_touch_probability=-0.1,
            calibrated_dates=(date(2026, 7, 1),),
            fingerprint="sha256:test",
        )


def test_state_contract_has_one_public_action_state() -> None:
    assert tuple(state.value for state in PreboardState) == (
        "observe",
        "prepare",
        "actionable",
        "missed",
        "rejected",
    )


def test_one_decision_version_and_execution_mode_are_explicit() -> None:
    assert PREBOARD_DECISION_VERSION == "limit-up-preboard-decision-v2"
    assert tuple(mode.value for mode in PreboardExecutionMode) == (
        "research_only",
        "shadow",
        "formal",
    )
