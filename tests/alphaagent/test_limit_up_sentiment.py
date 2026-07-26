from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.limit_up.sentiment import (
    SENTIMENT_SCORE_WEIGHTS,
    _sentiment_score,
    calculate_effective_board_streaks,
)


def test_effective_board_streak_resets_when_stock_misses_market_day() -> None:
    market_dates = [
        date(2026, 6, 15),
        date(2026, 6, 16),
        date(2026, 7, 1),
        date(2026, 7, 2),
    ]
    rows = [
        {"vt_symbol": "600001.SSE", "trade_date": market_dates[0], "is_limit_up": 1},
        {"vt_symbol": "600001.SSE", "trade_date": market_dates[2], "is_limit_up": 1},
        {"vt_symbol": "600001.SSE", "trade_date": market_dates[3], "is_limit_up": 1},
    ]

    result = calculate_effective_board_streaks(rows, market_dates)
    by_date = {row["trade_date"]: row for row in result}

    assert by_date[date(2026, 7, 1)]["limit_up_streak"] == 1
    assert by_date[date(2026, 7, 1)]["previous_is_limit_up"] == 0
    assert by_date[date(2026, 7, 2)]["limit_up_streak"] == 2
    assert by_date[date(2026, 7, 2)]["previous_is_limit_up"] == 1


def test_promotion_state_only_uses_previous_market_trade_day() -> None:
    market_dates = [date(2026, 7, day) for day in (1, 2, 3)]
    rows = [
        {"vt_symbol": "600001.SSE", "trade_date": market_dates[0], "is_limit_up": 1},
        {"vt_symbol": "600001.SSE", "trade_date": market_dates[2], "is_limit_up": 1},
        {"vt_symbol": "600002.SSE", "trade_date": market_dates[0], "is_limit_up": 1},
        {"vt_symbol": "600002.SSE", "trade_date": market_dates[1], "is_limit_up": 1},
        {"vt_symbol": "600002.SSE", "trade_date": market_dates[2], "is_limit_up": 0},
    ]

    result = calculate_effective_board_streaks(rows, market_dates)
    by_identity = {
        (row["vt_symbol"], row["trade_date"]): row
        for row in result
    }

    resumed = by_identity[("600001.SSE", date(2026, 7, 3))]
    continuous = by_identity[("600002.SSE", date(2026, 7, 3))]
    assert resumed["previous_is_limit_up"] == 0
    assert resumed["previous_limit_up_streak"] == 0
    assert continuous["previous_is_limit_up"] == 1
    assert continuous["previous_limit_up_streak"] == 2


def test_sentiment_weights_are_frozen_and_sum_to_one() -> None:
    assert SENTIMENT_SCORE_WEIGHTS == {
        "breadth": 0.28,
        "limit_up": 0.22,
        "max_streak": 0.18,
        "promotion": 0.14,
        "seal_quality": 0.10,
        "risk_quality": 0.08,
    }
    assert sum(SENTIMENT_SCORE_WEIGHTS.values()) == pytest.approx(1.0)


def test_sentiment_score_uses_each_weight_once() -> None:
    score = _sentiment_score(
        up_ratio=1.0,
        down_ratio=0.0,
        limit_up_count=100,
        limit_down_count=0,
        max_streak=7,
        failed_rate=0.0,
        promotion_rate=1.0,
    )

    assert score == pytest.approx(100.0)
