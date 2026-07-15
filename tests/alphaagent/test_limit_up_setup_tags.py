from __future__ import annotations

from alphaagent.server.services.limit_up.lane_research import (
    detect_setup_tags,
    evaluate_lane_candidate,
)


def test_detects_sandwich_and_return_board_setups() -> None:
    sandwich = detect_setup_tags(
        {
            "prior_limit_count_5": 1,
            "prior_limit_count_126": 3,
            "trade_days_since_prior_limit": 3,
            "pullback_from_prior_limit_pct": -3.0,
            "prior_amplitude_pct": 3.5,
        },
        setup_type=None,
    )
    return_board = detect_setup_tags(
        {
            "prior_limit_count_5": 0,
            "prior_limit_count_126": 4,
            "trade_days_since_prior_limit": 12,
            "pullback_from_prior_limit_pct": -11.0,
            "prior_position_120": 0.42,
        },
        setup_type=None,
    )

    assert "sandwich_board" in sandwich
    assert "return_board" in return_board


def test_detects_weak_to_strong_dragon_and_anti_nuclear_setups() -> None:
    candidate = {
        "prior_change_pct": -9.1,
        "prior_amplitude_pct": 8.0,
        "auction_gap_pct": 2.0,
        "prior_market_phase": "repair",
        "prior_industry_leader_rank": 1,
        "prior_break_streak": 3,
        "trade_days_since_prior_limit": 2,
    }

    tags = detect_setup_tags(candidate, setup_type="high_board_weak_to_strong")

    assert {
        "weak_to_strong_breakout",
        "dragon_first_negative_relay",
        "dragon_weak_to_strong",
        "anti_nuclear_board",
    }.issubset(tags)


def test_setup_tags_do_not_read_outcome_fields() -> None:
    candidate = {
        "prior_limit_count_5": 0,
        "prior_limit_count_126": 5,
        "trade_days_since_prior_limit": 10,
        "pullback_from_prior_limit_pct": -9.0,
        "prior_position_120": 0.5,
        "prior_change_pct": -2.0,
        "prior_amplitude_pct": 7.0,
        "auction_gap_pct": 1.5,
        "outcome": {"sealed": True, "next_close_return_pct": 20.0},
    }
    changed = {
        **candidate,
        "outcome": {"sealed": False, "next_close_return_pct": -20.0},
    }

    assert detect_setup_tags(candidate, setup_type=None) == detect_setup_tags(
        changed,
        setup_type=None,
    )


def test_weak_market_theme_attack_tag_is_explicit_and_point_in_time() -> None:
    candidate = {
        "outcome": {"sealed": True, "next_close_return_pct": 20.0},
    }
    changed = {
        "outcome": {"sealed": False, "next_close_return_pct": -20.0},
    }

    assert detect_setup_tags(
        candidate,
        setup_type=None,
        first_board_route="weak_market_theme_attack",
    ) == ["weak_market_theme_attack"]
    assert detect_setup_tags(
        changed,
        setup_type=None,
        first_board_route="weak_market_theme_attack",
    ) == ["weak_market_theme_attack"]


def test_setup_tags_reject_values_outside_their_point_in_time_boundaries() -> None:
    assert "sandwich_board" not in detect_setup_tags(
        {
            "prior_limit_count_5": 1,
            "trade_days_since_prior_limit": 5,
            "pullback_from_prior_limit_pct": -3.0,
            "prior_amplitude_pct": 3.5,
        },
        setup_type=None,
    )
    assert "return_board" not in detect_setup_tags(
        {
            "prior_limit_count_126": 1,
            "trade_days_since_prior_limit": 12,
            "pullback_from_prior_limit_pct": -11.0,
            "prior_position_120": 0.42,
        },
        setup_type=None,
    )
    tags = detect_setup_tags(
        {
            "prior_change_pct": 1.0,
            "prior_amplitude_pct": 8.0,
            "auction_gap_pct": -0.1,
            "prior_market_phase": "mixed",
            "prior_industry_leader_rank": 2,
            "prior_break_streak": 1,
            "trade_days_since_prior_limit": 1,
        },
        setup_type=None,
    )
    assert not {
        "weak_to_strong_breakout",
        "dragon_first_negative_relay",
        "dragon_weak_to_strong",
        "anti_nuclear_board",
    }.intersection(tags)


def test_anti_nuclear_tag_does_not_bypass_fundamental_risk_gate() -> None:
    result = evaluate_lane_candidate(
        {
            "prior_change_pct": -8.0,
            "auction_gap_pct": 1.0,
            "prior_market_phase": "repair",
            "financial_risk": {"blocked": True},
        }
    )

    assert "anti_nuclear_board" in result["setup_tags"]
    assert "fundamental_risk" in result["blockers"]
    assert result["decision"] == "blocked"
