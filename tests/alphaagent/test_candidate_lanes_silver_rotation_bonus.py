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


def test_silver_pressure_fresh_first_lift_bonus_matches_missed_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600186.SSE",
        total_score=88.6257,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "repeated_launch",
            "low_suction_days": 3,
            "pullback_days": 6,
            "latest_change_pct": 2.5397,
            "return_20d": 7.131,
            "close_location_in_range": 0.9091,
            "volume_ratio_5d_20d": 0.8131,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 8.0
    assert "silver_pressure_fresh_first_lift_turn" in keys


def test_silver_pressure_low_suction_bonus_rejects_stale_weak_lift() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600988.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "high_close_launch",
            "low_suction_days": 6,
            "pullback_days": 11,
            "latest_change_pct": 2.0245,
            "return_20d": 10.9842,
            "close_location_in_range": 0.9478,
            "volume_ratio_5d_20d": 0.8523,
        },
    )

    keys = {reason["key"] for reason in candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 0.0
    assert "silver_pressure_fresh_first_lift_turn" not in keys


def test_silver_pressure_fresh_buildup_bonus_requires_frontrow_quality() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000065.SZSE",
        total_score=80.1056,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "low_suction_days": 4,
            "pullback_days": 6,
            "latest_change_pct": 2.5377,
            "return_20d": 9.5763,
            "close_location_in_range": 0.3707,
            "volume_ratio_5d_20d": 0.8643,
            "frontrow_sector_rank_return": 60,
        },
    )
    weak_theme = SimpleNamespace(
        vt_symbol="603906.SSE",
        total_score=77.4737,
        evidence={**candidate.evidence, "frontrow_sector_rank_return": 180},
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 7.0
    assert "silver_pressure_fresh_buildup_turn" in keys
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(weak_theme) == 0.0


def test_oversold_silver_repair_low_turnover_bonus_matches_repair_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603002.SSE",
        total_score=88.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "return_20d": -8.6,
            "ma20_distance_pct": -4.2,
            "latest_change_pct": 1.4,
            "close_location_in_range": 0.58,
            "volume_ratio_5d_20d": 0.96,
            "latest_turnover_ratio_20d": 0.84,
            "near_limit_up_count_20d": 0,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 7.55
    assert "oversold_silver_6_20_retreat" in keys
    assert "oversold_silver_repair_low_turnover" in keys


def test_oversold_silver_repair_low_turnover_rejects_crowded_high_turnover() -> None:
    candidate = SimpleNamespace(
        vt_symbol="RISK.SZSE",
        total_score=88.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "return_20d": -8.6,
            "ma20_distance_pct": -4.2,
            "latest_change_pct": 1.4,
            "close_location_in_range": 0.58,
            "volume_ratio_5d_20d": 0.96,
            "latest_turnover_ratio_20d": 1.46,
            "near_limit_up_count_20d": 2,
        },
    )

    keys = {reason["key"] for reason in candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)}

    assert "oversold_silver_repair_low_turnover" not in keys
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 3.9


def test_low_base_buildup_safe_bonus_matches_controlled_low_suction_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603738.SSE",
        total_score=84.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "low_suction_stage": "buildup",
            "low_suction_days": 4,
            "pullback_days": 6,
            "return_20d": 9.2,
            "ma20_distance_pct": 2.6,
            "volume_ratio_5d_20d": 0.94,
            "latest_turnover_ratio_20d": 0.91,
            "close_location_in_range": 0.62,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 6.7
    assert "low_suction_buildup_silver_6_20_retreat" in keys
    assert "low_base_buildup_safe" in keys
    assert "low_base_buildup_pressure_window" in keys


def test_low_base_buildup_safe_rejects_short_hot_push() -> None:
    candidate = SimpleNamespace(
        vt_symbol="HOT.SZSE",
        total_score=84.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_silver_6_20",
            "market_phase": "retreat",
            "low_suction_stage": "buildup",
            "low_suction_days": 2,
            "pullback_days": 3,
            "return_20d": 19.2,
            "ma20_distance_pct": 7.6,
            "volume_ratio_5d_20d": 1.34,
            "latest_turnover_ratio_20d": 1.42,
            "close_location_in_range": 0.88,
        },
    )

    keys = {reason["key"] for reason in candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)}

    assert "low_base_buildup_safe" not in keys


def test_low_suction_hot_short_push_filter_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002049.SZSE",
        total_score=95.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "high_close_launch",
            "pullback_days": 3,
            "return_5d": 10.79,
            "close_location_in_range": 0.87,
            "latest_turnover_ratio_20d": 1.54,
            "turnover_percentile_60d": 0.88,
        },
    )

    assert candidate_lanes.low_suction_hot_short_push_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "low_suction_hot_short_push_decay"


def test_gold_late_mid_high_close_stretch_filter_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603375.SSE",
        total_score=94.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "return_20d": 24.91,
            "ma20_distance_pct": 8.99,
            "close_location_in_range": 0.74,
            "latest_change_pct": 3.4,
            "latest_turnover_ratio_20d": 0.96,
        },
    )

    assert candidate_lanes.gold_late_mid_high_close_stretch_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_mid_high_close_stretch_decay"


def test_overlap_unconfirmed_fast_push_filter_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="001896.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "low_suction_days": 3,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": 7.63,
            "close_location_in_range": 0.83,
            "return_20d": 23.4,
            "near_limit_up_count_20d": 2,
        },
    )

    assert candidate_lanes.overlap_unconfirmed_fast_push_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "overlap_unconfirmed_fast_push_decay"


def test_gold_late_overheated_dragon_quality_filter_matches_may_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002491.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "retreat",
            "return_20d": 59.6167,
            "ma20_distance_pct": 21.1133,
            "latest_change_pct": 1.942,
            "low_suction_days": 0,
        },
    )

    assert candidate_lanes.gold_late_overheated_dragon_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_overheated_dragon_decay"


def test_gold_late_overheated_dragon_filter_does_not_block_fresh_silver_right_tail() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000725.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_silver_0_5",
            "market_phase": "retreat",
            "return_20d": 33.7321,
            "ma20_distance_pct": 16.5433,
            "latest_change_pct": 3.0,
            "low_suction_days": 0,
        },
    )

    assert candidate_lanes.gold_late_overheated_dragon_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_silver_late_overlap_rotation_decay_matches_march_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603002.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_low_suction_overlap",
            "setup_family": "dragon_low_suction_overlap",
            "timing_window": "after_silver_late",
            "market_phase": "rotation",
            "low_suction_days": 3,
            "pullback_days": 9,
            "return_20d": 17.2,
            "close_location_in_range": 0.72,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
        },
    )

    assert candidate_lanes.silver_late_overlap_rotation_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_overlap_rotation_decay"


def test_silver_late_overlap_rotation_decay_uses_audited_entry_family() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603002.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "entry_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "rotation",
            "low_suction_days": 5,
            "pullback_days": 12,
            "return_20d": 22.8031,
            "close_location_in_range": 0.9245,
            "low_suction_launch_quality_bucket": "late_pullback_launch",
        },
    )

    assert candidate_lanes.silver_late_overlap_rotation_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_overlap_rotation_decay"


def test_silver_late_midclose_ma5_reclaim_decay_matches_march_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002384.SZSE",
        total_score=98.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "support_type": "ma5_reclaim",
            "return_20d": 33.5,
            "ma20_distance_pct": 9.4,
            "ma_convergence_pct": 15.2,
            "close_location_in_range": 0.39,
            "volume_ratio_5d_20d": 0.96,
        },
    )

    assert candidate_lanes.silver_late_midclose_ma5_reclaim_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_midclose_ma5_reclaim_decay"


def test_silver_6_20_exhausted_lowclose_decay_matches_march_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600522.SSE",
        total_score=95.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_silver_6_20",
            "market_phase": "rotation",
            "support_type": "ma5_reclaim",
            "return_20d": 41.0,
            "return_60d": 62.0,
            "ma20_distance_pct": 9.2,
            "close_location_in_range": 0.05,
        },
    )

    assert candidate_lanes.silver_6_20_exhausted_lowclose_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_6_20_exhausted_lowclose_decay"


def test_silver_pressure_filters_keep_active_washout_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603629.SSE",
        total_score=100.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "support_type": "ma5_reclaim",
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 4,
            "latest_change_pct": 6.43,
            "return_5d": -2.01,
            "return_20d": 19.16,
            "ma_convergence_pct": 14.09,
            "ma20_distance_pct": 5.28,
            "drawdown_from_pivot_pct": -6.23,
            "volume_ratio_5d_20d": 0.85,
            "close_location_in_range": 0.94,
        },
    )

    assert candidate_lanes.active_washout_reclaim_confirmation(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_silver_late_overlap_filter_keeps_strong_frontrow_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="601016.SSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_low_suction_overlap",
            "setup_family": "dragon_low_suction_overlap",
            "timing_window": "after_silver_late",
            "market_phase": "rotation",
            "low_suction_days": 3,
            "pullback_days": 9,
            "return_20d": 14.8,
            "close_location_in_range": 0.68,
            "volume_ratio_5d_20d": 1.72,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "frontrow_sector_rank_return": 35,
            "frontrow_sector_heat_score": 72.0,
        },
    )

    assert candidate_lanes.silver_late_overlap_rotation_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_high_close_exhaustion_filter_matches_may_energy_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000791.SZSE",
        total_score=99.4308,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "return_20d": 19.4342,
            "ma20_distance_pct": 9.5504,
            "close_location_in_range": 0.8939,
            "latest_change_pct": 2.8602,
            "low_suction_days": 0,
        },
    )

    assert candidate_lanes.gold_late_high_close_exhaustion_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_high_close_exhaustion_decay"


def test_gold_late_high_close_exhaustion_filter_keeps_mid_close_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603316.SSE",
        total_score=94.5665,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "return_20d": 27.0307,
            "ma20_distance_pct": 10.9654,
            "close_location_in_range": 0.2788,
            "latest_change_pct": 0.7035,
            "low_suction_days": 0,
        },
    )

    assert candidate_lanes.gold_late_high_close_exhaustion_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_wide_ma_volume_churn_filter_matches_single_big_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000767.SZSE",
        total_score=99.8152,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "low_suction_days": 0,
            "return_20d": 32.8982,
            "ma20_distance_pct": 18.4823,
            "volume_ratio_5d_20d": 1.5934,
            "close_location_in_range": 0.5435,
        },
    )

    assert candidate_lanes.gold_late_wide_ma_volume_churn_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_wide_ma_volume_churn_decay"


def test_silver_late_overlap_unconfirmed_midclose_filter_matches_retreat_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002837.SZSE",
        total_score=91.4243,
        evidence={
            "entry_setup": "stealth_low_suction",
            "entry_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "low_suction_days": 5,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "low_suction_launch_confirmed": False,
            "market_warning_level": 2,
            "close_location_in_range": 0.5442,
            "volume_ratio_5d_20d": 0.8913,
        },
    )

    assert candidate_lanes.silver_late_overlap_unconfirmed_midclose_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_overlap_unconfirmed_midclose_decay"


def test_silver_late_overlap_unconfirmed_midclose_filter_keeps_high_close_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603629.SSE",
        total_score=91.0,
        evidence={
            "entry_setup": "dragon_low_suction_overlap",
            "setup_family": "dragon_low_suction_overlap",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "low_suction_days": 3,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "low_suction_launch_confirmed": False,
            "market_warning_level": 3,
            "close_location_in_range": 0.7679,
            "volume_ratio_5d_20d": 0.9746,
        },
    )

    assert candidate_lanes.silver_late_overlap_unconfirmed_midclose_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_silver_late_overlap_unconfirmed_midclose_filter_keeps_low_volume_repair_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="001301.SZSE",
        total_score=91.0,
        evidence={
            "entry_setup": "dragon_low_suction_overlap",
            "setup_family": "dragon_low_suction_overlap",
            "timing_window": "after_silver_late",
            "market_phase": "rotation",
            "low_suction_days": 3,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "low_suction_launch_confirmed": False,
            "market_warning_level": 2,
            "close_location_in_range": 0.0576,
            "volume_ratio_5d_20d": 0.6568,
        },
    )

    assert candidate_lanes.silver_late_overlap_unconfirmed_midclose_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_silver_6_20_lowclose_filter_keeps_deep_washout_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002432.SZSE",
        total_score=94.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_silver_6_20",
            "market_phase": "rotation",
            "support_type": "ma5_reclaim",
            "return_20d": 24.0,
            "return_60d": 32.0,
            "ma20_distance_pct": 5.0,
            "close_location_in_range": 0.04,
            "drawdown_from_pivot_pct": -12.0,
            "volume_ratio_5d_20d": 1.45,
            "near_limit_up_count_20d": 2,
        },
    )

    assert candidate_lanes.silver_6_20_exhausted_lowclose_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_retreat_no_buildup_decay_matches_may_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002183.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "retreat",
            "support_type": "ma5_reclaim",
            "low_suction_days": 0,
            "ma_convergence_pct": 15.3541,
            "close_location_in_range": 0.3548,
            "volume_ratio_5d_20d": 1.1964,
        },
    )

    assert candidate_lanes.gold_late_retreat_no_buildup_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_retreat_no_buildup_decay"


def test_gold_late_retreat_filter_keeps_buildup_repair_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="SAFE.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "entry_family": "low_position_reclaim",
            "timing_window": "after_gold_late",
            "market_phase": "retreat",
            "support_type": "ma5_reclaim",
            "low_suction_days": 4,
            "ma_convergence_pct": 4.5,
            "close_location_in_range": 0.64,
            "volume_ratio_5d_20d": 0.92,
        },
    )

    assert candidate_lanes.gold_late_retreat_no_buildup_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_silver_late_warming_stretched_dragon_decay_matches_october_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002654.SZSE",
        total_score=94.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "warming",
            "support_type": "ma5_reclaim",
            "low_suction_days": 0,
            "return_20d": 25.0585,
            "ma20_distance_pct": 11.277,
            "ma_convergence_pct": 13.0259,
            "volume_ratio_5d_20d": 1.2166,
        },
    )

    assert candidate_lanes.silver_late_warming_stretched_dragon_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_warming_stretched_dragon_decay"


def test_silver_late_warming_filter_keeps_low_suction_overlap_repair_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="LOW.SZSE",
        total_score=91.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_silver_late",
            "market_phase": "warming",
            "support_type": "ma5_reclaim",
            "low_suction_days": 4,
            "return_20d": 18.0,
            "ma20_distance_pct": 5.5,
            "ma_convergence_pct": 7.0,
            "volume_ratio_5d_20d": 0.9,
        },
    )

    assert candidate_lanes.silver_late_warming_stretched_dragon_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


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


def test_gold_late_uptrend_extreme_stretch_decay_matches_big_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002655.SZSE",
        total_score=97.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "low_suction_days": 0,
            "return_20d": 72.3963,
            "return_60d": 196.1995,
            "ma20_distance_pct": 25.9214,
            "near_limit_up_count_20d": 3,
            "recent_limit_up_20d": True,
        },
    )

    assert candidate_lanes.gold_late_uptrend_extreme_stretch_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_uptrend_extreme_stretch_decay"


def test_gold_late_uptrend_extreme_stretch_keeps_moderate_frontrow_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="603316.SSE",
        total_score=94.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "low_suction_days": 0,
            "return_20d": 27.0307,
            "return_60d": 33.8849,
            "ma20_distance_pct": 10.9654,
            "near_limit_up_count_20d": 2,
            "recent_limit_up_20d": True,
        },
    )

    assert candidate_lanes.gold_late_uptrend_extreme_stretch_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_overlap_unconfirmed_highclose_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000859.SZSE",
        total_score=99.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_days": 3,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": 1.3969,
            "close_location_in_range": 0.6596,
            "return_60d": 91.9129,
            "near_limit_up_count_20d": 3,
        },
    )

    assert candidate_lanes.gold_late_overlap_unconfirmed_highclose_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_overlap_unconfirmed_highclose_decay"


def test_gold_late_overlap_unconfirmed_highclose_keeps_washout_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="605123.SSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_days": 3,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": -3.1046,
            "close_location_in_range": 0.157,
            "return_60d": 59.8924,
            "near_limit_up_count_20d": 2,
        },
    )

    assert candidate_lanes.gold_late_overlap_unconfirmed_highclose_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_overlap_late_pullback_highclose_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002222.SZSE",
        total_score=98.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_days": 5,
            "low_suction_launch_quality_bucket": "late_pullback_launch",
            "close_location_in_range": 0.7202,
            "return_20d": 23.3564,
            "return_60d": 58.8327,
        },
    )

    assert candidate_lanes.gold_late_overlap_late_pullback_highclose_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_overlap_late_pullback_highclose_decay"


def test_gold_late_overlap_late_pullback_highclose_keeps_low_base_low_suction_winner() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000404.SZSE",
        total_score=91.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "low_suction_days": 6,
            "low_suction_launch_quality_bucket": "late_pullback_launch",
            "close_location_in_range": 0.6364,
            "return_20d": 20.6799,
            "return_60d": 19.6629,
        },
    )

    assert candidate_lanes.gold_late_overlap_late_pullback_highclose_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_first_lift_other_confirmed_exhaustion_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000690.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "other_confirmed_launch",
            "latest_change_pct": 1.0582,
            "close_location_in_range": 0.7692,
            "return_60d": 30.2273,
        },
    )

    assert candidate_lanes.gold_late_first_lift_other_confirmed_exhaustion_decay(candidate) is True
    assert (
        candidate_lanes.dragon_pullback_quality_filter_reason(candidate)
        == "gold_late_first_lift_other_confirmed_exhaustion_decay"
    )


def test_gold_late_first_lift_other_confirmed_exhaustion_keeps_safe_energy_winners() -> None:
    newji_energy = SimpleNamespace(
        vt_symbol="601918.SSE",
        total_score=91.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "low_suction_days": 5,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "repeated_launch",
            "latest_change_pct": 1.7261,
            "close_location_in_range": 0.7209,
            "return_60d": 23.6364,
        },
    )
    shenghe_resources = SimpleNamespace(
        vt_symbol="600392.SSE",
        total_score=91.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_days": 4,
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "other_confirmed_launch",
            "latest_change_pct": 0.9524,
            "close_location_in_range": 0.7465,
            "return_60d": 7.0707,
        },
    )

    assert candidate_lanes.gold_late_first_lift_other_confirmed_exhaustion_decay(newji_energy) is False
    assert candidate_lanes.gold_late_first_lift_other_confirmed_exhaustion_decay(shenghe_resources) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(newji_energy) is None
    assert candidate_lanes.dragon_pullback_quality_filter_reason(shenghe_resources) is None


def test_gold_late_rotation_highclose_decay_matches_cluster_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002290.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "rotation",
            "latest_change_pct": 4.9507,
            "return_20d": 32.6696,
            "close_location_in_range": 0.7981,
        },
    )

    assert candidate_lanes.gold_late_rotation_highclose_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_rotation_highclose_decay"


def test_gold_late_rotation_highclose_keeps_low_close_washout_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002264.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "rotation",
            "low_suction_days": 4,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": -4.3876,
            "return_20d": 18.4598,
            "close_location_in_range": 0.3125,
        },
    )

    assert candidate_lanes.gold_late_rotation_highclose_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_late_residual_filters_match_remaining_failure_shapes() -> None:
    overlap_short = SimpleNamespace(
        vt_symbol="603799.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_days": 4,
            "pullback_days": 3,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": -2.6746,
            "close_location_in_range": 0.2639,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
        },
    )
    dragon_short = SimpleNamespace(
        vt_symbol="002738.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "pullback_days": 3,
            "latest_change_pct": -1.6399,
            "return_60d": 68.7908,
            "ma20_distance_pct": 6.4174,
            "close_location_in_range": 0.2742,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
        },
    )
    retreat_lowclose = SimpleNamespace(
        vt_symbol="600188.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "retreat",
            "low_suction_days": 6,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "close_location_in_range": 0.038,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
        },
    )

    assert candidate_lanes.dragon_pullback_quality_filter_reason(overlap_short) == "gold_late_overlap_unconfirmed_short_reclaim_decay"
    assert candidate_lanes.dragon_pullback_quality_filter_reason(dragon_short) == "gold_late_dragon_no_active_short_reclaim_decay"
    assert candidate_lanes.dragon_pullback_quality_filter_reason(retreat_lowclose) == "gold_late_overlap_retreat_lowclose_decay"


def test_gold_late_residual_filters_match_rotation_and_first_lift_failures() -> None:
    weak_washout = SimpleNamespace(
        vt_symbol="002945.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "rotation",
            "low_suction_days": 5,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": -4.0719,
            "return_60d": 15.8365,
            "close_location_in_range": 0.2143,
        },
    )
    balanced_push = SimpleNamespace(
        vt_symbol="003031.SZSE",
        total_score=96.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "rotation",
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "balanced_first_lift",
            "latest_change_pct": 3.2035,
            "return_60d": 44.7489,
            "pullback_days": 2,
        },
    )
    no_active_push = SimpleNamespace(
        vt_symbol="600399.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_launch_confirmed": True,
            "low_suction_launch_quality_bucket": "other_confirmed_launch",
            "latest_change_pct": 2.4963,
            "return_60d": 33.2061,
            "close_location_in_range": 0.7719,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
        },
    )

    assert candidate_lanes.dragon_pullback_quality_filter_reason(weak_washout) == "gold_late_overlap_rotation_weak_washout_decay"
    assert candidate_lanes.dragon_pullback_quality_filter_reason(balanced_push) == "gold_late_first_lift_rotation_push_decay"
    assert candidate_lanes.dragon_pullback_quality_filter_reason(no_active_push) == "gold_late_first_lift_no_active_push_decay"


def test_gold_late_uptrend_no_active_long_pullback_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600150.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "pullback_days": 8,
            "return_20d": 22.8788,
            "close_location_in_range": 0.2885,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
        },
    )

    assert candidate_lanes.gold_late_uptrend_no_active_long_pullback_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_late_uptrend_no_active_long_pullback_decay"


def test_gold_late_residual_filters_keep_known_remaining_winner_shapes() -> None:
    low_close_overlap_winner = SimpleNamespace(
        vt_symbol="600399.SSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "warming",
            "low_suction_days": 3,
            "pullback_days": 7,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": -3.267,
            "return_60d": 27.2897,
            "close_location_in_range": 0.20,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
        },
    )
    low_close_rotation_winner = SimpleNamespace(
        vt_symbol="002264.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "entry_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "rotation",
            "low_suction_days": 4,
            "low_suction_launch_quality_bucket": "unconfirmed_buildup",
            "latest_change_pct": -4.3876,
            "return_60d": 43.4842,
            "close_location_in_range": 0.3125,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 2,
        },
    )
    low_base_uptrend_winner = SimpleNamespace(
        vt_symbol="603316.SSE",
        total_score=94.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "timing_window": "after_gold_late",
            "market_phase": "uptrend",
            "pullback_days": 4,
            "return_20d": 27.0307,
            "close_location_in_range": 0.2788,
            "recent_limit_up_20d": True,
            "near_limit_up_count_20d": 2,
        },
    )

    assert candidate_lanes.dragon_pullback_quality_filter_reason(low_close_overlap_winner) is None
    assert candidate_lanes.dragon_pullback_quality_filter_reason(low_close_rotation_winner) is None
    assert candidate_lanes.dragon_pullback_quality_filter_reason(low_base_uptrend_winner) is None


def test_silver_late_oversold_stretched_shrink_body_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002490.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "ma5_distance_pct": 2.0302,
            "body_pct": 5.1777,
            "volume_ratio_5d_20d": 0.7342,
            "close_location_in_range": 0.9659,
        },
    )

    assert candidate_lanes.silver_late_oversold_stretched_shrink_body_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_oversold_stretched_shrink_body_decay"


def test_silver_late_oversold_stretched_filter_keeps_volume_confirmed_winner() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600183.SSE",
        total_score=92.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "ma5_distance_pct": 2.755,
            "body_pct": 3.3333,
            "volume_ratio_5d_20d": 1.0111,
            "close_location_in_range": 0.7358,
        },
    )

    assert candidate_lanes.silver_late_oversold_stretched_shrink_body_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_silver_late_first_lift_stale_active_source_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600988.SSE",
        total_score=96.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "setup_family": "low_suction_first_lift",
            "timing_window": "after_silver_late",
            "nearest_timing_days": 23,
            "recent_limit_up_20d": True,
            "low_suction_launch_confirmed": True,
            "low_suction_days": 6,
        },
    )

    assert candidate_lanes.silver_late_first_lift_stale_active_source_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "silver_late_first_lift_stale_active_source_decay"


def test_silver_late_first_lift_stale_active_source_keeps_fresh_pressure_winner() -> None:
    candidate = SimpleNamespace(
        vt_symbol="600186.SSE",
        total_score=92.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "setup_family": "low_suction_first_lift",
            "timing_window": "after_silver_late",
            "nearest_timing_days": 23,
            "recent_limit_up_20d": True,
            "low_suction_launch_confirmed": True,
            "low_suction_days": 3,
        },
    )

    assert candidate_lanes.silver_late_first_lift_stale_active_source_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_early_first_lift_no_active_source_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="605389.SSE",
        total_score=92.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "setup_family": "low_suction_first_lift",
            "timing_window": "after_gold_0_5",
            "low_suction_launch_confirmed": True,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "large_bull_count_20d": 1,
        },
    )

    assert candidate_lanes.gold_early_first_lift_no_active_source_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_early_first_lift_no_active_source_decay"


def test_gold_early_first_lift_no_active_source_filter_keeps_active_winner_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002202.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "stealth_low_suction",
            "setup_type": "stealth_low_suction",
            "setup_family": "low_suction_first_lift",
            "timing_window": "after_gold_0_5",
            "low_suction_launch_confirmed": True,
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "large_bull_count_20d": 2,
        },
    )

    assert candidate_lanes.gold_early_first_lift_no_active_source_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_gold_early_oversold_no_active_low_close_decay_matches_failure_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002407.SZSE",
        total_score=93.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_type": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "timing_window": "after_gold_0_5",
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "close_location_in_range": 0.2468,
        },
    )

    assert candidate_lanes.gold_early_oversold_no_active_low_close_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "gold_early_oversold_no_active_low_close_decay"


def test_gold_early_oversold_no_active_low_close_keeps_silver_repair_winner() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002407.SZSE",
        total_score=94.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_type": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "timing_window": "after_silver_6_20",
            "recent_limit_up_20d": False,
            "near_limit_up_count_20d": 0,
            "close_location_in_range": 0.7972,
        },
    )

    assert candidate_lanes.gold_early_oversold_no_active_low_close_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None


def test_deep_low_absorption_reversal_gets_unified_opportunity_bonus() -> None:
    candidate = SimpleNamespace(
        vt_symbol="688711.SSE",
        total_score=82.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_type": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "deep_low_absorption_reversal",
            "deep_low_absorption_reversal": True,
            "market_phase": "retreat",
            "latest_volume_ratio_20d": 0.92,
            "latest_turnover_ratio_20d": 1.05,
        },
    )

    reasons = candidate_lanes.dragon_pullback_timing_opportunity_reasons(candidate)
    keys = {reason["key"] for reason in reasons}

    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 8.7
    assert "deep_low_absorption_reversal" in keys
    assert "deep_low_absorption_pressure_window" in keys
    assert "deep_low_absorption_controlled_volume" in keys


def test_deep_low_absorption_early_silver_late_retreat_is_capped() -> None:
    candidate = SimpleNamespace(
        vt_symbol="001270.SZSE",
        total_score=94.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_type": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "deep_low_absorption_reversal",
            "deep_low_absorption_reversal": True,
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "nearest_timing_days": 23,
            "latest_volume_ratio_20d": 0.82,
            "latest_turnover_ratio_20d": 0.78,
        },
    )

    assert candidate_lanes.deep_low_absorption_early_silver_late_retreat_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 0.0
    assert candidate_lanes.dragon_pullback_opportunity_score(candidate) == 82.0


def test_deep_low_absorption_later_silver_late_retreat_keeps_bonus() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002414.SZSE",
        total_score=84.0,
        evidence={
            "entry_setup": "oversold_rebound_start",
            "setup_type": "oversold_rebound_start",
            "setup_family": "oversold_rebound_start",
            "rebound_subtype": "deep_low_absorption_reversal",
            "deep_low_absorption_reversal": True,
            "timing_window": "after_silver_late",
            "market_phase": "retreat",
            "nearest_timing_days": 30,
            "latest_volume_ratio_20d": 0.89,
            "latest_turnover_ratio_20d": 0.84,
        },
    )

    assert candidate_lanes.deep_low_absorption_early_silver_late_retreat_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_timing_opportunity_bonus(candidate) == 8.7
    assert candidate_lanes.dragon_pullback_opportunity_score(candidate) == 92.7


def test_overheated_crowded_high_turnover_decay_matches_d1_big_down_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="000890.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_type": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "return_20d": 86.7,
            "ma20_distance_pct": 27.7,
            "near_limit_up_count_20d": 8,
            "latest_turnover_ratio_20d": 1.55,
            "turnover_percentile_60d": 0.91,
            "volume_ratio_5d_20d": 1.35,
            "turnover20": 1_500_000_000,
            "close_location_in_range": 0.42,
            "latest_change_pct": 6.4,
        },
    )

    assert candidate_lanes.overheated_crowded_high_turnover_decay(candidate) is True
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) == "overheated_crowded_high_turnover_decay"


def test_overheated_crowded_high_turnover_filter_keeps_strong_close_not_crowded_shape() -> None:
    candidate = SimpleNamespace(
        vt_symbol="002409.SZSE",
        total_score=92.0,
        evidence={
            "entry_setup": "dragon_pullback",
            "setup_type": "dragon_pullback",
            "setup_family": "dragon_pullback",
            "return_20d": 18.7,
            "ma20_distance_pct": -1.8,
            "near_limit_up_count_20d": 2,
            "latest_turnover_ratio_20d": 1.35,
            "turnover_percentile_60d": 0.83,
            "volume_ratio_5d_20d": 1.15,
            "turnover20": 800_000_000,
            "close_location_in_range": 0.88,
            "latest_change_pct": 5.5,
        },
    )

    assert candidate_lanes.overheated_crowded_high_turnover_decay(candidate) is False
    assert candidate_lanes.dragon_pullback_quality_filter_reason(candidate) is None
