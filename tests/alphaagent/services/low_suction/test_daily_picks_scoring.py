"""Unit tests for the low-suction daily composite score (pure functions)."""

from __future__ import annotations

import pytest

from alphaagent.server.services.low_suction.daily_picks_scoring import (
    quiet_candle_streak,
    score_band,
    score_oversold_candidate,
    score_trend_candidate,
)


def _bar(day_range_pct: float, *, up: bool = True, close: float = 10.0) -> dict[str, float]:
    prev_close = close
    high = prev_close * (1 + day_range_pct / 200)
    low = prev_close * (1 - day_range_pct / 200)
    open_price = prev_close
    close_price = prev_close * (1.001 if up else 0.999)
    return {
        "open_price": open_price,
        "close_price": close_price,
        "high_price": max(high, open_price, close_price),
        "low_price": min(low, open_price, close_price),
    }


def test_quiet_candle_streak_counts_trailing_small_candles() -> None:
    history = [
        _bar(8.0),  # 嘈杂，打断
        _bar(2.0, up=False),
        _bar(3.0, up=True),
        _bar(1.5, up=False),
    ]
    streak = quiet_candle_streak(history)
    assert streak.total == 3
    assert streak.yin == 2
    assert streak.yang == 1
    assert "连续3根" in streak.label


def test_quiet_candle_streak_zero_after_noisy_candle() -> None:
    history = [_bar(2.0), _bar(9.0)]
    streak = quiet_candle_streak(history)
    assert streak.total == 0


def test_score_band_edges() -> None:
    assert score_band(0) == "0-39"
    assert score_band(39.9) == "0-39"
    assert score_band(40) == "40-59"
    assert score_band(60) == "60-79"
    assert score_band(80) == "80-89"
    assert score_band(90) == "90-100"
    assert score_band(100) == "90-100"


def test_trend_score_full_marks() -> None:
    features = {
        "candle_range_pct": 2.1,
        "ma60": 9.0,
        "ma30": 10.0,
        "bull_alignment_days": 7,
        "ma5_low_touch": True,
        "ma10_low_touch": False,
        "turnover_rate_pct": 2.0,
        "trend_dist_excess_pct": -1.5,
        "prior_daily_return_pct": -2.0,
        "close_to_ma5_pct": -0.8,
        "last_volume_shrank": True,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 6)
    score, components = score_trend_candidate(features, streak)
    assert score == 100.0
    assert sum(c.max_points for c in components) == 100.0
    assert not any(c.kind == "gate" for c in components)


def test_trend_context_switches_amplitude_gradient() -> None:
    """语境调节（核心创新）：同振幅 6.5%（5-8 桶），转势 22 / 成熟 4。"""
    base = {
        "candle_range_pct": 6.5,
        "bull_alignment_days": 7,
        "ma5_low_touch": True,
        "turnover_rate_pct": 2.0,
        "trend_dist_excess_pct": -1.0,
        "prior_daily_return_pct": -1.0,
        "close_to_ma5_pct": -0.5,
        "last_volume_shrank": True,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    _, comps_trans = score_trend_candidate(dict(base, ma60=11.0, ma30=10.0), streak)
    _, comps_mature = score_trend_candidate(dict(base, ma60=9.0, ma30=10.0), streak)
    ctx_trans = next(c for c in comps_trans if c.key == "candle_quiet_context")
    ctx_mature = next(c for c in comps_mature if c.key == "candle_quiet_context")
    assert ctx_trans.points == 22.0
    assert ctx_mature.points == 4.0
    assert "转势" in ctx_trans.detail
    assert "成熟" in ctx_mature.detail


def test_trend_age_gradient() -> None:
    """趋势年龄分量：6-10 天最佳（满14），≥21 天衰减（4）。"""
    base = {
        "candle_range_pct": 2.0,
        "ma60": 9.0,
        "ma30": 10.0,
        "ma5_low_touch": True,
        "turnover_rate_pct": 2.0,
        "trend_dist_excess_pct": -1.0,
        "prior_daily_return_pct": -1.0,
        "close_to_ma5_pct": -0.5,
        "last_volume_shrank": True,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    _, comps_best = score_trend_candidate(dict(base, bull_alignment_days=7), streak)
    _, comps_old = score_trend_candidate(dict(base, bull_alignment_days=25), streak)
    age_best = next(c for c in comps_best if c.key == "trend_age")
    age_old = next(c for c in comps_old if c.key == "trend_age")
    assert age_best.points == 14.0
    assert age_old.points == 4.0


def test_trend_no_gate_protects_high_turnover_cases() -> None:
    """趋势族无 gate：华建级（换手 9.20/振幅 7.04/转势）不被门禁，仍能拿分。"""
    features = {
        "candle_range_pct": 7.04,
        "ma60": 11.0,
        "ma30": 10.0,
        "bull_alignment_days": 8,
        "ma5_low_touch": True,
        "turnover_rate_pct": 9.20,
        "trend_dist_excess_pct": 0.5,
        "prior_daily_return_pct": -1.0,
        "close_to_ma5_pct": -0.3,
        "last_volume_shrank": False,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    score, components = score_trend_candidate(features, streak)
    assert not any(c.kind == "gate" for c in components)
    assert score > 0


def test_oversold_score_full_marks() -> None:
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "capitulation_rebound_tight": True,
        "capitulation_rebound_broad": False,
        "close_off_low_pct": 0.9,
        "staged_m10_first": True,
        "support_close_reaction": True,
        "volume_shape": "staircase_shrink",
        "candle_quiet": True,
        "candle_range_pct": 1.2,
        "prior_bear_alignment_days": 25,
        # 最好看形态（阳线包裹+极收敛+极平滑+梯形缩量+实体均匀）
        "yang_wrap_three_ma": True,
        "yang_wrap_stable_base": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma_cluster_spread_pct": 0.0,
        "ma10_slope_cv_6d": 0.0,
        "vol_monotone_6d": 1.0,
        "body_max_excl_6d": 0.0,
        "breakout_hold_premium": 5.0,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    score, components = score_oversold_candidate(
        features,
        streak,
        vol_ratio=0.7,
        stable_three_ma_wrap_rule_matched=True,
    )
    # 基础组件满分100×0.4(=40) + 好看度95 + 稳定地基8 = 143，受总分 140 上限约束。
    assert score == 140.0
    # 15 个 bonus 上限之和 = 基础组件100（展示）+ 好看度95 + 稳定地基8 + 预上穿10 + 快速收敛2 + 活跃承接8 = 223。
    assert sum(c.max_points for c in components if c.kind == "bonus") == 223.0
    assert sum(1 for c in components if c.kind == "gate") == 1


def test_oversold_stable_wrap_rule_unlocks_wrap_points() -> None:
    base = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "candle_range_pct": 3.5,
        "prior_bear_alignment_days": 12,
        "yang_wrap_three_ma": True,
        "ma10_crossed_ma20_after_long_bear_within_15d": True,
        "ma_cluster_spread_pct": 2.0,
        "ma10_slope_cv_6d": 40.0,
        "vol_monotone_6d": 0.6,
        "body_max_excl_6d": 1.5,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)

    baseline_score, baseline_components = score_oversold_candidate(base, streak)
    stable_score, stable_components = score_oversold_candidate(
        {**base, "yang_wrap_stable_base": True},
        streak,
        stable_three_ma_wrap_rule_matched=True,
    )

    stable_component = next(
        component
        for component in stable_components
        if component.key == "yang_wrap_stable_base"
    )
    baseline_component = next(
        component
        for component in baseline_components
        if component.key == "yang_wrap_stable_base"
    )
    assert stable_score > baseline_score + 8.0
    assert next(
        component
        for component in baseline_components
        if component.key == "yang_wrap_pretty"
    ).points == 0.0
    assert stable_component.passed is True
    assert stable_component.points == 8.0
    assert baseline_component.passed is False
    assert baseline_component.points == 0.0


def test_geometric_wrap_without_matched_rule_gets_no_wrap_bonus() -> None:
    base = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "candle_range_pct": 3.5,
        "prior_bear_alignment_days": 12,
        "yang_wrap_three_ma": True,
        "yang_wrap_stable_base": True,
        "ma_cluster_spread_pct": 2.0,
        "ma10_slope_cv_6d": 40.0,
        "vol_monotone_6d": 0.6,
        "body_max_excl_6d": 1.5,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)

    geometric_score, geometric_components = score_oversold_candidate(base, streak)
    qualified_score, qualified_components = score_oversold_candidate(
        {**base, "ma10_crossed_ma20_after_long_bear_within_15d": True},
        streak,
        stable_three_ma_wrap_rule_matched=True,
    )

    geometric_pretty = next(
        component
        for component in geometric_components
        if component.key == "yang_wrap_pretty"
    )
    qualified_pretty = next(
        component
        for component in qualified_components
        if component.key == "yang_wrap_pretty"
    )
    geometric_base = next(
        component
        for component in geometric_components
        if component.key == "yang_wrap_stable_base"
    )
    qualified_base = next(
        component
        for component in qualified_components
        if component.key == "yang_wrap_stable_base"
    )
    assert qualified_score > geometric_score + 48.0
    assert geometric_pretty.points == 0.0
    assert qualified_pretty.points > 40.0
    assert geometric_base.points == 0.0
    assert qualified_base.points == 8.0


def test_pre_cross_controlled_drive_adds_ten_points_only_to_that_path() -> None:
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "candle_range_pct": 3.5,
        "prior_bear_alignment_days": 12,
        "daily_return_pct": 3.0,
        "ma10_ma20_next_close_required_return_pct": 1.5,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)

    baseline_score, _ = score_oversold_candidate(features, streak)
    score, components = score_oversold_candidate(
        features,
        streak,
        pre_cross_rule_matched=True,
    )
    component = next(
        item for item in components if item.key == "pre_cross_controlled_drive"
    )
    assert score == baseline_score + 10.0
    assert component.passed is True
    assert component.points == 10.0

    _, automatic_components = score_oversold_candidate(
        {**features, "ma10_ma20_next_close_required_return_pct": 0.0},
        streak,
        pre_cross_rule_matched=True,
    )
    automatic_component = next(
        item
        for item in automatic_components
        if item.key == "pre_cross_controlled_drive"
    )
    assert automatic_component.points == 0.0


def test_staged_ma30_fast_convergence_adds_two_points_only_to_that_path() -> None:
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 1.0,
        "candle_range_pct": 3.5,
        "prior_bear_alignment_days": 12,
        "ma10_ma30_gap_narrowing_5d_pct": 5.1,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)

    baseline_score, _ = score_oversold_candidate(features, streak)
    score, components = score_oversold_candidate(
        features,
        streak,
        staged_ma30_convergence_rule_matched=True,
    )
    component = next(
        item for item in components if item.key == "staged_ma30_fast_convergence"
    )
    assert score == baseline_score + 2.0
    assert component.passed is True
    assert component.points == 2.0

    _, unrelated_components = score_oversold_candidate(
        features,
        streak,
        staged_ma30_convergence_rule_matched=False,
    )
    unrelated_component = next(
        item
        for item in unrelated_components
        if item.key == "staged_ma30_fast_convergence"
    )
    assert unrelated_component.points == 0.0


def test_staged_ma30_active_participation_ranks_the_verified_path() -> None:
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "candle_range_pct": 3.5,
        "prior_bear_alignment_days": 12,
        "ma10_ma30_gap_narrowing_5d_pct": 5.1,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)

    baseline_score, _ = score_oversold_candidate(features, streak)
    score, components = score_oversold_candidate(
        features,
        streak,
        staged_ma30_convergence_rule_matched=True,
    )
    component = next(
        item for item in components if item.key == "staged_ma30_active_participation"
    )
    assert score == baseline_score + 10.0
    assert component.passed is True
    assert component.points == 8.0

    _, sparse_components = score_oversold_candidate(
        {**features, "turnover_rate_pct": 1.49},
        streak,
        staged_ma30_convergence_rule_matched=True,
    )
    sparse_component = next(
        item
        for item in sparse_components
        if item.key == "staged_ma30_active_participation"
    )
    sparse_turnover = next(
        item for item in sparse_components if item.key == "turnover_gradient"
    )
    assert sparse_component.points == 0.0
    assert sparse_turnover.points == 14.0


def test_oversold_gate_caps_at_39_when_bonus_high() -> None:
    """换手 ≥8% gate 失败，即便其他维度全优，总分硬封顶 39。"""
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 12.0,
        "capitulation_rebound_tight": True,
        "capitulation_rebound_broad": False,
        "close_off_low_pct": 0.9,
        "staged_m10_first": True,
        "support_close_reaction": True,
        "volume_shape": "staircase_shrink",
        "candle_quiet": True,
        "candle_range_pct": 1.2,
        "prior_bear_alignment_days": 25,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    score, components = score_oversold_candidate(features, streak)
    gate = next(c for c in components if c.kind == "gate")
    assert gate.passed is False
    assert score <= 39.0


def test_oversold_gate_passes_case_level_turnover() -> None:
    """案例级换手 5.15%（15 研究票超跌最高）gate 通过，不 cap。"""
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 5.15,
        "capitulation_rebound_tight": True,
        "staged_m10_first": True,
        "support_close_reaction": True,
        "volume_shape": "staircase_shrink",
        "candle_quiet": True,
        "candle_range_pct": 2.0,
        "prior_bear_alignment_days": 20,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    score, components = score_oversold_candidate(features, streak)
    gate = next(c for c in components if c.kind == "gate")
    assert gate.passed is True
    assert score > 30.0  # 死股偏好×0.4后满分≈40，gate通过(不cap)的正常分数


def test_oversold_long_bear_duration_gradient() -> None:
    """空头持续时长分量（修 long_bear 读入未用 bug）。"""
    base = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.0,
        "staged_m10_first": True,
        "support_close_reaction": True,
        "volume_shape": "staircase_shrink",
        "candle_quiet": True,
        "candle_range_pct": 2.0,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    _, comps_long = score_oversold_candidate(dict(base, prior_bear_alignment_days=25), streak)
    _, comps_short = score_oversold_candidate(dict(base, prior_bear_alignment_days=3), streak)
    dur_long = next(c for c in comps_long if c.key == "long_bear_duration")
    dur_short = next(c for c in comps_short if c.key == "long_bear_duration")
    assert dur_long.points == 10.0
    assert dur_short.points == 0.0


def test_oversold_volume_trend_gradient() -> None:
    """量能趋势分量（近5日均量/10日均量）：骤缩满10，骤放0。"""
    base = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.0,
        "staged_m10_first": True,
        "support_close_reaction": True,
        "volume_shape": "staircase_shrink",
        "candle_quiet": True,
        "candle_range_pct": 2.0,
        "prior_bear_alignment_days": 20,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    _, comps_shrink = score_oversold_candidate(base, streak, vol_ratio=0.7)
    _, comps_expand = score_oversold_candidate(base, streak, vol_ratio=1.5)
    vt_shrink = next(c for c in comps_shrink if c.key == "vol_trend")
    vt_expand = next(c for c in comps_expand if c.key == "vol_trend")
    assert vt_shrink.points == 10.0
    assert vt_expand.points == 0.0


def test_score_component_kind_defaults_to_bonus() -> None:
    from alphaagent.server.services.low_suction.daily_picks_scoring import ScoreComponent

    component = ScoreComponent("k", "label", True, 5.0, 10.0, "detail")
    assert component.kind == "bonus"


def test_total_caps_at_gate_failed_cap_when_gate_fails() -> None:
    from alphaagent.server.services.low_suction.daily_picks_scoring import ScoreComponent, _total

    gate_pass = (
        ScoreComponent("g", "gate", True, 10.0, 10.0, "ok", kind="gate"),
        ScoreComponent("b", "bonus", True, 80.0, 80.0, "ok"),
    )
    gate_fail = (
        ScoreComponent("g", "gate", False, 0.0, 10.0, "fail", kind="gate"),
        ScoreComponent("b", "bonus", True, 80.0, 80.0, "ok"),
    )
    assert _total(gate_pass, gate_failed_cap=39.0) == 90.0   # gate 通过不 cap
    assert _total(gate_fail, gate_failed_cap=39.0) == 39.0   # gate 失败 cap 39
    assert _total(gate_fail) == 80.0                          # 无 cap 参数不 cap


def test_post_wrap_confirmation_uses_a_visible_p2_score_floor() -> None:
    from alphaagent.server.services.low_suction.daily_picks_scoring import (
        POST_WRAP_CONFIRMATION_SCORE_FLOOR,
    )

    features = {
        "turnover_rate_pct": 2.0,
        "candle_range_pct": 2.0,
        "prior_bear_alignment_days": 10,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    baseline_score, _ = score_oversold_candidate(features, streak)
    score, components = score_oversold_candidate(
        features,
        streak,
        post_wrap_upper_band_confirmation_rule_matched=True,
    )

    priority = next(
        component
        for component in components
        if component.key == "post_wrap_upper_band_confirmation_priority"
    )
    assert baseline_score < POST_WRAP_CONFIRMATION_SCORE_FLOOR
    assert score == POST_WRAP_CONFIRMATION_SCORE_FLOOR
    assert priority.passed is True
    assert priority.kind == "priority"
    assert priority.points == pytest.approx(score - baseline_score)


def test_attack_retest_base_adds_a_limited_visible_experimental_bonus() -> None:
    from alphaagent.server.services.low_suction.daily_picks_scoring import (
        ATTACK_RETEST_BASE_BONUS_POINTS,
    )

    features = {
        "turnover_rate_pct": 2.0,
        "candle_range_pct": 2.0,
        "prior_bear_alignment_days": 10,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    baseline_score, _ = score_oversold_candidate(features, streak)
    score, components = score_oversold_candidate(
        features,
        streak,
        attack_retest_base_rule_matched=True,
    )

    component = next(
        item for item in components if item.key == "attack_retest_base"
    )
    assert score == baseline_score + ATTACK_RETEST_BASE_BONUS_POINTS
    assert component.passed is True
    assert component.points == ATTACK_RETEST_BASE_BONUS_POINTS


def test_score_version_bumped_to_v2_8() -> None:
    from alphaagent.server.services.low_suction import daily_picks_scoring as module

    assert module.SCORE_VERSION == "low-suction-daily-score-v2.8"
