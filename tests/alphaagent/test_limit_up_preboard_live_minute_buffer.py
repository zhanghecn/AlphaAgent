from __future__ import annotations

from datetime import datetime, timedelta

from alphaagent.server.services.limit_up.preboard_live_minute_buffer import (
    LiveMinuteBuffer,
    live_minute_close,
)


SYMBOL = "600001.SSE"


def test_current_sampled_minute_is_not_completed_at_decision_time() -> None:
    buffer = LiveMinuteBuffer()
    buffer.ingest(
        datetime(2026, 7, 20, 10, 20, 4),
        [_quote(10.00, volume=100.0, turnover=1_000.0)],
    )
    buffer.ingest(
        datetime(2026, 7, 20, 10, 20, 50),
        [_quote(10.20, volume=120.0, turnover=1_204.0)],
    )

    assert live_minute_close(datetime(2026, 7, 20, 10, 20, 4)) == datetime(
        2026, 7, 20, 10, 21
    )
    assert buffer.completed_bars(
        SYMBOL,
        datetime(2026, 7, 20, 10, 20, 4),
    ) == []
    completed = buffer.completed_bars(
        SYMBOL,
        datetime(2026, 7, 20, 10, 21),
    )
    assert len(completed) == 1
    assert completed[0]["bar_time"] == datetime(2026, 7, 20, 10, 21)
    assert completed[0]["open_price"] == 10.0
    assert completed[0]["close_price"] == 10.2


def test_reverse_and_duplicate_samples_do_not_change_completed_bars() -> None:
    samples = [
        (
            datetime(2026, 7, 20, 10, 20, 5),
            _quote(10.00, volume=100.0, turnover=1_000.0),
        ),
        (
            datetime(2026, 7, 20, 10, 20, 25),
            _quote(10.30, volume=110.0, turnover=1_103.0),
        ),
        (
            datetime(2026, 7, 20, 10, 20, 50),
            _quote(10.10, volume=120.0, turnover=1_204.0),
        ),
    ]
    ordered = LiveMinuteBuffer()
    reversed_buffer = LiveMinuteBuffer()
    for captured_at, quote in samples:
        ordered.ingest(captured_at, [quote])
    ordered.ingest(samples[1][0], [samples[1][1]])
    for captured_at, quote in reversed(samples):
        reversed_buffer.ingest(captured_at, [quote])

    cutoff = datetime(2026, 7, 20, 10, 21)
    assert ordered.completed_bars(SYMBOL, cutoff) == (
        reversed_buffer.completed_bars(SYMBOL, cutoff)
    )
    bar = ordered.completed_bars(SYMBOL, cutoff)[0]
    assert (bar["open_price"], bar["high_price"], bar["low_price"], bar["close_price"]) == (
        10.0,
        10.3,
        10.0,
        10.1,
    )


def test_lunch_break_does_not_create_synthetic_minutes() -> None:
    buffer = LiveMinuteBuffer()
    buffer.ingest(
        datetime(2026, 7, 20, 11, 29, 50),
        [_quote(10.0, volume=100.0, turnover=1_000.0)],
    )
    buffer.ingest(
        datetime(2026, 7, 20, 11, 30, 5),
        [_quote(99.0, volume=101.0, turnover=1_099.0)],
    )
    buffer.ingest(
        datetime(2026, 7, 20, 12, 30),
        [_quote(99.0, volume=102.0, turnover=1_198.0)],
    )
    buffer.ingest(
        datetime(2026, 7, 20, 13, 0, 5),
        [_quote(10.1, volume=110.0, turnover=1_101.0)],
    )

    bars = buffer.completed_bars(SYMBOL, datetime(2026, 7, 20, 13, 1))
    assert [bar["bar_time"].time().isoformat(timespec="minutes") for bar in bars] == [
        "11:30",
        "13:01",
    ]
    assert all(bar["close_price"] != 99.0 for bar in bars)


def test_source_quality_requires_eight_completed_labels() -> None:
    buffer = LiveMinuteBuffer()
    start = datetime(2026, 7, 20, 10, 0, 5)
    for index in range(8):
        buffer.ingest(
            start + timedelta(minutes=index),
            [
                _quote(
                    10.0 + index * 0.01,
                    volume=100.0 + index * 10.0,
                    turnover=1_000.0 + index * 100.0,
                )
            ],
        )

    assert buffer.source_quality(SYMBOL, datetime(2026, 7, 20, 10, 7)) == (
        "insufficient_live_prefix"
    )
    assert buffer.source_quality(SYMBOL, datetime(2026, 7, 20, 10, 8)) == (
        "sampled_quote_proxy"
    )
    bars = buffer.completed_bars(SYMBOL, datetime(2026, 7, 20, 10, 8))
    assert len(bars) == 8
    assert all(bar["volume"] is not None for bar in bars[-7:])


def test_quality_pool_snapshots_use_only_completed_minutes() -> None:
    buffer = LiveMinuteBuffer()
    captured_at = datetime(2026, 7, 20, 10, 20, 4)
    buffer.ingest_quality_pool(
        captured_at,
        [{"vt_symbol": SYMBOL, "change_pct": 6.0}],
    )

    assert buffer.completed_quality_pool_snapshots(captured_at) == []
    snapshots = buffer.completed_quality_pool_snapshots(
        datetime(2026, 7, 20, 10, 21)
    )
    assert snapshots == [
        {
            "captured_at": datetime(2026, 7, 20, 10, 21),
            "candidates": [{"vt_symbol": SYMBOL, "change_pct": 6.0}],
        }
    ]


def test_new_trade_date_resets_previous_day_samples() -> None:
    buffer = LiveMinuteBuffer()
    buffer.ingest(
        datetime(2026, 7, 20, 14, 59, 50),
        [_quote(10.0, volume=1_000.0, turnover=10_000.0)],
    )
    buffer.ingest(
        datetime(2026, 7, 21, 9, 30, 5),
        [_quote(10.2, volume=10.0, turnover=102.0)],
    )

    bars = buffer.completed_bars(SYMBOL, datetime(2026, 7, 21, 9, 31))
    assert [bar["bar_time"].date().isoformat() for bar in bars] == ["2026-07-21"]


def _quote(price: float, *, volume: float, turnover: float) -> dict[str, object]:
    return {
        "vt_symbol": SYMBOL,
        "last_price": price,
        "volume": volume,
        "turnover": turnover,
    }
