from types import SimpleNamespace

from alphaagent.server.services.quant import candidate_lanes


def test_silver_rotation_washout_dragon_bonus_matches_missed_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600777.SSE",
        total_score=88.8466,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_silver_6_20",
            "market_phase": "rotation",
            "latest_change_pct": 0.404,
            "return_5d": 2.8986,
            "return_20d": 21.8137,
            "return_60d": 27.7635,
            "ma20_distance_pct": 10.0897,
            "volume_ratio_5d_20d": 1.5871,
            "close_location_in_range": 0.1667,
            "low_suction_days": 0,
            "frontrow_theme_candidate_rank": 1,
            "frontrow_sector_heat_score": 53.0,
            "frontrow_sector_score": 58.0,
            "frontrow_sector_rank_return": 80,
            "frontrow_sector_leader_score": 65.0,
            "frontrow_sector_breadth_score": 55.0,
            "frontrow_sector_continuity_score": 55.0,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 6.5
    assert "silver_rotation_washout_dragon" in keys
    assert "washout_dragon_frontrow_floor" in keys


def test_silver_rotation_flat_base_low_suction_bonus_matches_missed_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="001256.SZSE",
        total_score=86.6443,
        evidence={
            "entry_setup": "low_suction_buildup",
            "setup_family": "low_suction_buildup",
            "timing_window": "after_silver_6_20",
            "market_phase": "rotation",
            "latest_change_pct": 0.3991,
            "return_5d": -0.0883,
            "return_20d": 2.6292,
            "return_60d": 1.5702,
            "ma20_distance_pct": 0.6043,
            "volume_ratio_5d_20d": 0.8571,
            "close_location_in_range": 0.5098,
            "low_suction_days": 6,
            "frontrow_theme_candidate_rank": 3,
            "frontrow_sector_heat_score": 60.0,
            "frontrow_sector_score": 76.0,
            "frontrow_sector_rank_return": 40,
            "frontrow_sector_leader_score": 70.0,
            "frontrow_sector_breadth_score": 65.0,
            "frontrow_sector_continuity_score": 65.0,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 8.9
    assert "silver_rotation_flat_base_low_suction" in keys
    assert "flat_base_theme_rank_confirm" in keys


def test_silver_rotation_flat_base_rejects_low_close_volume_push_failure() -> None:
    candidate = SimpleNamespace(
        vt_symbol="300649.SZSE",
        total_score=87.7197,
        evidence={
            "entry_setup": "low_suction_buildup",
            "setup_family": "low_suction_buildup",
            "timing_window": "after_silver_6_20",
            "market_phase": "rotation",
            "latest_change_pct": 0.8016,
            "return_5d": 1.7532,
            "return_20d": 0.7343,
            "return_60d": 1.2752,
            "ma20_distance_pct": 0.6201,
            "volume_ratio_5d_20d": 1.1091,
            "close_location_in_range": 0.3519,
            "low_suction_days": 5,
            "frontrow_theme_candidate_rank": 1,
            "frontrow_sector_heat_score": 70.0,
            "frontrow_sector_score": 90.0,
            "frontrow_sector_rank_return": 10,
        },
    )

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 0.0


def test_silver_rotation_bonus_rejects_non_target_timing_phase() -> None:
    candidate = SimpleNamespace(
        vt_symbol="001256.SZSE",
        total_score=86.6443,
        evidence={
            "entry_setup": "low_suction_buildup",
            "setup_family": "low_suction_buildup",
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "latest_change_pct": 0.3991,
            "return_5d": -0.0883,
            "return_20d": 2.6292,
            "return_60d": 1.5702,
            "ma20_distance_pct": 0.6043,
            "volume_ratio_5d_20d": 0.8571,
            "close_location_in_range": 0.5098,
            "low_suction_days": 6,
            "frontrow_theme_candidate_rank": 3,
            "frontrow_sector_heat_score": 60.0,
            "frontrow_sector_score": 76.0,
            "frontrow_sector_rank_return": 40,
            "frontrow_sector_leader_score": 70.0,
            "frontrow_sector_breadth_score": 65.0,
            "frontrow_sector_continuity_score": 65.0,
        },
    )

    keys = {reason["key"] for reason in candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)}

    assert "silver_rotation_flat_base_low_suction" not in keys
    assert "flat_base_theme_rank_confirm" not in keys


def test_gold_late_stealth_first_lift_crawl_bonus_matches_safe_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="300251.SZSE",
        total_score=90.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_launch_confirmed": True,
            "latest_change_pct": 1.0734,
            "return_5d": 5.7329,
            "return_20d": 11.3255,
            "return_60d": 2.5215,
            "ma20_distance_pct": 3.3357,
            "volume_ratio_5d_20d": 0.9142,
            "close_location_in_range": 0.82,
            "low_suction_days": 5,
            "support_hold_days": 6,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 6.8
    assert "gold_late_stealth_first_lift_crawl" in keys


def test_gold_late_stealth_buildup_crawl_bonus_matches_safe_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="301519.SZSE",
        total_score=89.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "latest_change_pct": -0.4781,
            "return_5d": 0.48,
            "return_20d": 8.33,
            "return_60d": 1.04,
            "ma20_distance_pct": 3.49,
            "volume_ratio_5d_20d": 1.06,
            "close_location_in_range": 0.67,
            "low_suction_days": 6,
            "support_hold_days": 6,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 8.6
    assert "gold_late_stealth_buildup_crawl" in keys


def test_gold_late_stealth_crawl_rejects_dragon_lane_and_pushed_first_lift() -> None:
    dragon_lane = SimpleNamespace(
        vt_symbol="603848.SSE",
        total_score=90.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "low_suction_first_lift",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_launch_confirmed": True,
            "latest_change_pct": 1.3867,
            "return_5d": 3.79,
            "return_20d": 6.47,
            "return_60d": -5.1,
            "ma20_distance_pct": 4.58,
            "volume_ratio_5d_20d": 1.099,
            "close_location_in_range": 0.75,
            "low_suction_days": 5,
            "support_hold_days": 6,
        },
    )
    pushed = SimpleNamespace(
        vt_symbol="002501.SZSE",
        total_score=90.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_launch_confirmed": True,
            "latest_change_pct": 2.2989,
            "return_5d": 5.95,
            "return_20d": 8.98,
            "return_60d": 12.18,
            "ma20_distance_pct": 1.0,
            "volume_ratio_5d_20d": 0.83,
            "close_location_in_range": 0.76,
            "low_suction_days": 5,
            "support_hold_days": 6,
        },
    )

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(dragon_lane) == 0.0
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(pushed) == 0.0
