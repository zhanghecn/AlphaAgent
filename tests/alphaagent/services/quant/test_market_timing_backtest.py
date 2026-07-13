"""大盘择时表现评估的时间对齐守护。"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from alphaagent.server.services.quant.market_timing import backtest as bt
from alphaagent.server.services.quant.market_timing import panel as mt_panel
from alphaagent.server.services.quant.market_timing import signal as sig
from alphaagent.server.services.quant.market_timing.series import CompositeBar


def _bars(closes: list[float]) -> list[CompositeBar]:
    start = date(2026, 1, 5)
    return [
        CompositeBar(
            trade_date=start + timedelta(days=index),
            close=close,
            turnover=1_000_000.0,
            return_pct=0.0,
        )
        for index, close in enumerate(closes)
    ]


def _event(
    trade_date: date,
    status: str,
    confirm_date: date | None,
) -> sig.TimingSignal:
    return sig.TimingSignal(
        trade_date=trade_date,
        direction="GOLD",
        status=status,
        grade="WEAK",
        bull_force=70.0,
        bear_force=40.0,
        phase="warming",
        setup_type=sig.SETUP_REVERSAL_GOLD,
        confirm_date=confirm_date,
        reasons=[],
    )


def test_confirmed_performance_starts_after_confirmation_close() -> None:
    bars = _bars([100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0])
    event = _event(
        trade_date=bars[0].trade_date,
        status=sig.STATUS_CONFIRMED,
        confirm_date=bars[1].trade_date,
    )

    result = bt.evaluate([event], bars)

    confirmed_row = next(row for row in result["rows"] if row["horizon"] == 5)
    assert confirmed_row["candidate_date"] == bars[0].trade_date
    assert confirmed_row["confirm_date"] == bars[1].trade_date
    assert confirmed_row["start_date"] == bars[1].trade_date
    assert confirmed_row["setup_type"] == sig.SETUP_REVERSAL_GOLD
    assert confirmed_row["return"] == pytest.approx(0.0)

    candidate_row = next(
        row for row in result["candidate_rows"] if row["horizon"] == 5
    )
    assert candidate_row["candidate_date"] == bars[0].trade_date
    assert candidate_row["start_date"] == bars[0].trade_date
    assert candidate_row["setup_type"] == sig.SETUP_REVERSAL_GOLD
    assert candidate_row["return"] == pytest.approx(20.0)
    assert result["evaluation_basis"] == {
        "confirmed_start": "confirm_date_close",
        "candidate_start": "candidate_date_close",
        "executable": False,
    }


def test_candidate_performance_keeps_every_candidate_status() -> None:
    bars = _bars([100.0] * 12)
    events = [
        _event(bars[0].trade_date, sig.STATUS_CONFIRMED, bars[1].trade_date),
        _event(bars[2].trade_date, sig.STATUS_INVALIDATED, bars[3].trade_date),
        _event(bars[4].trade_date, sig.STATUS_PENDING, None),
    ]

    result = bt.evaluate(events, bars)

    confirmed_candidates = {row["candidate_date"] for row in result["rows"]}
    all_candidates = {row["candidate_date"] for row in result["candidate_rows"]}
    assert confirmed_candidates == {bars[0].trade_date}
    assert all_candidates == {event.trade_date for event in events}

    five_day_bucket = next(
        bucket
        for bucket in result["candidate_buckets"]
        if bucket.direction == "GOLD"
        and bucket.grade == "WEAK"
        and bucket.horizon == 5
    )
    assert five_day_bucket.count == 3


def test_panel_serializes_both_evaluation_bases() -> None:
    bars = _bars([100.0, 120.0, 120.0, 120.0, 120.0, 120.0, 120.0])
    event = _event(
        trade_date=bars[0].trade_date,
        status=sig.STATUS_CONFIRMED,
        confirm_date=bars[1].trade_date,
    )

    accuracy = mt_panel._build_accuracy(bt.evaluate([event], bars))

    assert accuracy["evaluation_basis"]["confirmed_start"] == "confirm_date_close"
    assert accuracy["candidate_buckets"][0]["direction"] == "GOLD"
    assert accuracy["rows"][0]["start_date"] == bars[1].trade_date.isoformat()
    assert accuracy["rows"][0]["setup_type"] == sig.SETUP_REVERSAL_GOLD
    assert accuracy["candidate_rows"][0]["start_date"] == bars[0].trade_date.isoformat()
