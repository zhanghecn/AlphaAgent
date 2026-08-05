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
    features = {
        "candle_range_pct": 2.1,
        "candle_quiet": True,
        "ma5_low_touch": True,
        "ma10_low_touch": False,
        "trend_dist_excess_pct": -1.5,
        "prior_daily_return_pct": -2.0,
        "close_to_ma5_pct": -0.8,
        "last_volume_shrank": True,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 5)
    score, components = score_trend_candidate(features, streak)
    assert score == 100.0
    assert all(c.passed for c in components)


def test_trend_score_noisy_candle_loses_base_points() -> None:
    features = {
        "candle_range_pct": 7.5,
        "candle_quiet": False,
        "ma5_low_touch": False,
        "ma10_low_touch": True,
        "trend_dist_excess_pct": 1.5,
        "prior_daily_return_pct": 3.0,
        "close_to_ma5_pct": 2.0,
        "last_volume_shrank": False,
    }
    streak = quiet_candle_streak([_bar(7.0)])
    score, _ = score_trend_candidate(features, streak)
    # 只拿 ma10 回踩 8 + 距离梯度 6 = 14 分
    assert score == 14.0


def test_oversold_score_full_marks() -> None:
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 1.8,
        "capitulation_rebound_tight": True,
        "capitulation_rebound_broad": True,
        "close_off_low_pct": 0.9,
        "staged_m10_first": True,
        "support_close_reaction": True,
        "volume_shape": "staircase_shrink",
        "candle_quiet": True,
        "candle_range_pct": 1.2,
        "long_bear_alignment": True,
    }
    streak = quiet_candle_streak([_bar(2.0)] * 3)
    score, components = score_oversold_candidate(features, streak)
    assert score == 100.0
    assert all(c.passed for c in components)


def test_oversold_score_high_turnover_penalized() -> None:
    features = {
        "oversold_low_support": True,
        "turnover_rate_pct": 12.0,
        "capitulation_rebound_tight": False,
        "capitulation_rebound_broad": False,
        "close_off_low_pct": -0.5,
        "support_close_reaction": False,
        "volume_shape": "staircase_expand",
        "candle_quiet": False,
        "candle_range_pct": 6.5,
        "long_bear_alignment": False,
    }
    streak = quiet_candle_streak([_bar(6.0)])
    score, _ = score_oversold_candidate(features, streak)
    # 只有低点支撑 20 分
    assert score == 20.0
