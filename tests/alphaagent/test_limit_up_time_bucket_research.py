from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.limit_up.time_bucket_research import (
    build_time_bucket_observations,
    classify_first_limit_time,
    render_markdown_report,
    summarize_time_buckets,
)


@pytest.mark.parametrize(
    ("value", "expected_key"),
    [
        ("09:25:00", "auction_open"),
        ("092959", "auction_open"),
        ("09:30:00", "morning_0930_1000"),
        ("09:59:59", "morning_0930_1000"),
        ("10:00:00", "morning_1000_1100"),
        ("10:59:59", "morning_1000_1100"),
        ("11:00:00", "morning_1100_1130"),
        ("11:30:00", "morning_1100_1130"),
        ("13:00:00", "afternoon_1300_1400"),
        ("13:59:59", "afternoon_1300_1400"),
        ("14:00:00", "afternoon_1400_1500"),
        ("15:00:00", "afternoon_1400_1500"),
        ("11:30:01", None),
        ("12:15:00", None),
        ("15:00:01", None),
        ("bad-time", None),
        (None, None),
    ],
)
def test_classifies_first_limit_time_boundaries(value: object, expected_key: str | None) -> None:
    bucket = classify_first_limit_time(value)

    assert (bucket[0] if bucket else None) == expected_key


def test_seal_rate_and_premium_metrics_use_separate_denominators() -> None:
    signal_date = date(2026, 1, 5)
    outcome_date = date(2026, 1, 6)
    events = [
        _event("600001.SSE", signal_date, "09:35:00", sealed=True, open_times=0),
        _event("600002.SSE", signal_date, "09:45:00", sealed=False, open_times=3),
        _event("600003.SSE", signal_date, "09:55:00", sealed=True, open_times=2),
        _event("600004.SSE", signal_date, "09:50:00", sealed=True, open_times=1),
    ]
    bars = [
        _bar("600001.SSE", signal_date, 10.0),
        _bar("600001.SSE", outcome_date, 10.5, open_price=11.0, high=11.1, low=9.8),
        _bar("600002.SSE", signal_date, 10.0),
        _bar("600002.SSE", outcome_date, 9.5, open_price=9.8, high=10.1, low=9.4),
        _bar("600003.SSE", signal_date, 10.0),
        _bar("600003.SSE", outcome_date, 10.2, open_price=9.9, high=10.4, low=9.6),
        _bar("600004.SSE", signal_date, 10.0),
    ]

    observations = build_time_bucket_observations(events, bars, [signal_date, outcome_date])
    report = summarize_time_buckets(observations, min_rank_samples=1)
    row = _bucket(report, "morning_0930_1000")

    assert row["touch_count"] == 4
    assert row["sealed_count"] == 3
    assert row["seal_success_rate_pct"] == 75.0
    assert row["premium_sample_count"] == 2
    assert row["d1_open_gross_win_rate_pct"] == 50.0
    assert row["d1_open_gross_average_return_pct"] == 4.5
    assert row["d1_open_net_win_rate_pct"] == 50.0
    assert row["d1_open_net_average_return_pct"] == 4.19
    assert row["d1_close_gross_win_rate_pct"] == 100.0
    assert row["d1_close_net_win_rate_pct"] == 100.0
    assert row["d1_close_net_average_return_pct"] == 3.19
    assert row["reseal_proxy_sample_count"] == 1
    assert row["reseal_d1_open_net_average_return_pct"] == -1.31
    assert report["exclusions"]["missing_d1_bar"] == 1

    markdown = render_markdown_report(report)
    header = next(line for line in markdown.splitlines() if line.startswith("| 首次触板"))
    data_row = next(line for line in markdown.splitlines() if line.startswith("| 09:30-10:00"))
    assert header.split("|")[12].strip() == "收盘净胜率"
    assert data_row.split("|")[12].strip() == "100.0000%"


def test_invalid_price_path_keeps_seal_count_but_not_premium_sample() -> None:
    signal_date = date(2026, 1, 5)
    outcome_date = date(2026, 1, 6)
    events = [_event("600001.SSE", signal_date, "14:30:00", sealed=True, open_times=1)]
    bars = [
        _bar("600001.SSE", signal_date, 10.0),
        _bar("600001.SSE", outcome_date, 10.2, open_price=10.1, high=12.0, low=9.8),
    ]

    observations = build_time_bucket_observations(events, bars, [signal_date, outcome_date])
    report = summarize_time_buckets(observations, min_rank_samples=1)
    row = _bucket(report, "afternoon_1400_1500")

    assert row["touch_count"] == 1
    assert row["sealed_count"] == 1
    assert row["premium_sample_count"] == 0
    assert report["exclusions"]["invalid_d1_path"] == 1


def test_d1_prices_cannot_change_time_bucket_or_seal_rate() -> None:
    signal_date = date(2026, 1, 5)
    outcome_date = date(2026, 1, 6)
    events = [_event("600001.SSE", signal_date, "13:15:00", sealed=True, open_times=1)]
    winning_bars = [
        _bar("600001.SSE", signal_date, 10.0),
        _bar("600001.SSE", outcome_date, 10.5, open_price=10.3, high=10.8, low=9.9),
    ]
    losing_bars = [
        _bar("600001.SSE", signal_date, 10.0),
        _bar("600001.SSE", outcome_date, 9.7, open_price=9.8, high=10.1, low=9.5),
    ]

    winning = summarize_time_buckets(
        build_time_bucket_observations(events, winning_bars, [signal_date, outcome_date]),
        min_rank_samples=1,
    )
    losing = summarize_time_buckets(
        build_time_bucket_observations(events, losing_bars, [signal_date, outcome_date]),
        min_rank_samples=1,
    )
    winning_row = _bucket(winning, "afternoon_1300_1400")
    losing_row = _bucket(losing, "afternoon_1300_1400")

    for key in ("touch_count", "sealed_count", "seal_success_rate_pct"):
        assert winning_row[key] == losing_row[key]
    assert winning_row["d1_open_gross_average_return_pct"] == 3.0
    assert losing_row["d1_open_gross_average_return_pct"] == -2.0


def _event(
    vt_symbol: str,
    trade_date: date,
    first_limit_time: str,
    *,
    sealed: bool,
    open_times: int,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "trade_date": trade_date,
        "first_limit_time": first_limit_time,
        "is_sealed": sealed,
        "open_times": open_times,
    }


def _bar(
    vt_symbol: str,
    trade_date: date,
    close_price: float,
    *,
    open_price: float | None = None,
    high: float | None = None,
    low: float | None = None,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": open_price if open_price is not None else close_price,
        "high_price": high if high is not None else close_price,
        "low_price": low if low is not None else close_price,
        "close_price": close_price,
    }


def _bucket(report: dict[str, object], key: str) -> dict[str, object]:
    return next(row for row in report["by_time_bucket"] if row["bucket_key"] == key)
