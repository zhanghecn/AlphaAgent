"""Unit tests for the low-suction daily composite score (pure functions)."""

from __future__ import annotations

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
    """连板后补涨/弱转强重构版：底盘满 100×0.4 + B 路径组件 30 = 满 70。"""
    features = {
        "limit_up_close_streak_max_60d": 8,
        "days_since_streak_peak_60d": 3,
        "close_off_low_pct": 13.0,
        "volume_to_streak_peak_pct": 8.0,
        "turnover_rate_pct": 30.0,
        "open_to_prev_close_pct": -4.0,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 6)
    score, components = score_trend_candidate(
        features,
        streak,
        weak_to_strong_reclaim_rule_matched=True,
    )
    assert score == 70.0
    base_keys = {
        "limit_up_streak_strength",
        "pullback_timing",
        "close_control",
        "volume_dryness",
        "turnover_activity",
    }
    base_total = sum(c.max_points for c in components if c.key in base_keys)
    assert base_total == 100.0
    assert not any(c.kind == "gate" for c in components)


def test_trend_score_streak_and_timing_gradients() -> None:
    """连板高度 7-9 最甜（22）；距顶甜点 ≤4 满 18，18-24 衰减到 7。"""
    base = {
        "days_since_streak_peak_60d": 2,
        "close_off_low_pct": 1.0,
        "volume_to_streak_peak_pct": 50.0,
        "turnover_rate_pct": 2.0,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    _, comps_mid = score_trend_candidate(
        {**base, "limit_up_close_streak_max_60d": 8}, streak
    )
    _, comps_low = score_trend_candidate(
        {**base, "limit_up_close_streak_max_60d": 5}, streak
    )
    streak_mid = next(c for c in comps_mid if c.key == "limit_up_streak_strength")
    streak_low = next(c for c in comps_low if c.key == "limit_up_streak_strength")
    assert streak_mid.points == 22.0
    assert streak_low.points == 16.0
    _, comps_fresh = score_trend_candidate(
        {**base, "limit_up_close_streak_max_60d": 8, "days_since_streak_peak_60d": 3},
        streak,
    )
    _, comps_late = score_trend_candidate(
        {**base, "limit_up_close_streak_max_60d": 8, "days_since_streak_peak_60d": 20},
        streak,
    )
    timing_fresh = next(c for c in comps_fresh if c.key == "pullback_timing")
    timing_late = next(c for c in comps_late if c.key == "pullback_timing")
    assert timing_fresh.points == 18.0
    assert timing_late.points == 7.0


def test_trend_score_paths_only_award_matched_rule_components() -> None:
    """路径组件互斥：B 命中吃低开/拉板组件，A 命中吃蓄势/情绪/地量组件。"""
    path_keys = {
        "reclaim_open_depth",
        "reclaim_magnitude",
        "reclaim_streak_premium",
        "pullback_ma10_sloping_up",
        "pullback_mood_temperature",
        "pullback_dry_volume",
    }
    features = {
        "limit_up_close_streak_max_60d": 6,
        "days_since_streak_peak_60d": 2,
        "close_off_low_pct": 13.0,
        "volume_to_streak_peak_pct": 15.0,
        "turnover_rate_pct": 25.0,
        "open_to_prev_close_pct": -4.0,
        "ma10_slope_5d_pct": 2.0,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    _, comps_reclaim = score_trend_candidate(
        features, streak, weak_to_strong_reclaim_rule_matched=True
    )
    reclaim_pts = sum(c.points for c in comps_reclaim if c.key in path_keys)
    assert reclaim_pts == 22.0  # 低开10 + 拉板12；streak 6<7 无高连板加成
    _, comps_pullback = score_trend_candidate(
        features,
        streak,
        120,
        limit_up_pullback_rule_matched=True,
    )
    pullback_pts = sum(c.points for c in comps_pullback if c.key in path_keys)
    assert pullback_pts == 30.0  # 蓄势10 + 情绪10 + 地量10
    _, comps_none = score_trend_candidate(features, streak)
    assert sum(c.points for c in comps_none if c.key in path_keys) == 0.0


def test_trend_no_gate_protects_high_turnover_cases() -> None:
    """趋势族无 gate：妖股级换手（30%）不被门禁，仍是换手承接满档。"""
    features = {
        "limit_up_close_streak_max_60d": 6,
        "days_since_streak_peak_60d": 2,
        "close_off_low_pct": 5.0,
        "volume_to_streak_peak_pct": 30.0,
        "turnover_rate_pct": 30.0,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    score, components = score_trend_candidate(features, streak)
    assert not any(c.kind == "gate" for c in components)
    assert score > 0


def test_oversold_p1_score_keeps_only_product_components() -> None:
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
        "ma10_ma30_gap_narrowing_5d_pct": 5.1,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    score, components = score_oversold_candidate(
        features,
        streak,
        vol_ratio=0.7,
        staged_ma30_convergence_rule_matched=True,
    )
    assert score == 50.0
    assert sum(c.max_points for c in components if c.kind == "bonus") == 130.0
    assert sum(1 for c in components if c.kind == "gate") == 1


def test_oversold_three_ma_wrap_quiet_bonus_unscaled() -> None:
    """W 路径安静包裹：振幅 <3% 满 4 / 3~4% 得 2 / ≥4% 不得，不折算。"""

    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "candle_range_pct": 1.2,
        "prior_bear_alignment_days": 25,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    base_score, _ = score_oversold_candidate(features, streak)
    quiet, components = score_oversold_candidate(
        features,
        streak,
        three_ma_wrap_rule_matched=True,
    )
    assert quiet == round(base_score + 4.0, 2)
    wrap_component = next(c for c in components if c.key == "wrap_quiet_package")
    assert wrap_component.points == 4.0
    assert wrap_component.max_points == 4.0

    mid, _ = score_oversold_candidate(
        {**features, "candle_range_pct": 3.5},
        streak,
        three_ma_wrap_rule_matched=True,
    )
    base_mid, _ = score_oversold_candidate(
        {**features, "candle_range_pct": 3.5}, streak
    )
    assert mid == round(base_mid + 2.0, 2)

    loud, _ = score_oversold_candidate(
        {**features, "candle_range_pct": 6.4},
        streak,
        three_ma_wrap_rule_matched=True,
    )
    base_loud, _ = score_oversold_candidate(
        {**features, "candle_range_pct": 6.4}, streak
    )
    assert loud == base_loud


def test_oversold_post_wrap_chain_and_shrink_confirm_unscaled() -> None:
    """Z 路径：链式确认 +6，确认日缩量（5/10 均量比 <0.9）再 +2，满 8。"""

    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 3.6,
        "candle_range_pct": 2.8,
        "prior_bear_alignment_days": 25,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    base_score, _ = score_oversold_candidate(features, streak, vol_ratio=1.0)
    chain_only, components = score_oversold_candidate(
        features,
        streak,
        vol_ratio=1.0,
        post_wrap_confirmation_rule_matched=True,
    )
    assert chain_only == round(base_score + 6.0, 2)
    with_shrink, components = score_oversold_candidate(
        features,
        streak,
        vol_ratio=0.8,
        post_wrap_confirmation_rule_matched=True,
    )
    base_shrink, _ = score_oversold_candidate(features, streak, vol_ratio=0.8)
    assert with_shrink == round(base_shrink + 8.0, 2)
    chain_component = next(
        c for c in components if c.key == "post_wrap_chain_confirm"
    )
    assert chain_component.points == 8.0
    assert chain_component.max_points == 8.0


def test_oversold_attack_votes_add_two_points_each_unscaled() -> None:
    """X/Y 路径攻击强度投票：每票 +2 直加（不经 0.4 折算），满 4 票 +8。"""

    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 2.5,
        "candle_range_pct": 1.2,
        "prior_bear_alignment_days": 25,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    base_score, _ = score_oversold_candidate(features, streak)
    with_votes, components = score_oversold_candidate(
        features,
        streak,
        attack_vote_count=3,
    )
    assert with_votes == round(base_score + 6.0, 2)
    vote_component = next(c for c in components if c.key == "attack_votes")
    assert vote_component.points == 6.0
    assert vote_component.max_points == 8.0
    capped, _ = score_oversold_candidate(features, streak, attack_vote_count=9)
    assert capped == round(base_score + 8.0, 2)


def test_oversold_process_score_ignores_retired_cross_paths() -> None:
    features = {
        "turnover_rate_pct": 2.0,
        "candle_range_pct": 2.0,
        "m10_dual_cross_before_m20_m30": True,
        "ma10_crossed_ma30_within_15d": True,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)

    _, components = score_oversold_candidate(features, streak)

    process = next(item for item in components if item.key == "process_structure")
    assert process.passed is False
    assert process.points == 0.0


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


def test_score_version_bumped_to_v3_2() -> None:
    """评分内容（规则集/分量/分值）变更必须同步升版本——版本门禁靠它
    让旧物化数据失效；并行会话曾只升标签不改内容，造成报告与代码脱节。
    v3.3：A 连板回落去外部门、改段后换手 5-20 承接门槛。"""

    from alphaagent.server.services.low_suction import daily_picks_scoring as module

    assert module.SCORE_VERSION == "low-suction-daily-score-v3.3"
