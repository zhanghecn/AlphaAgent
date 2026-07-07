from __future__ import annotations

from datetime import date, timedelta

from alphaagent.server.services.backtest.factor_audit import (
    build_daily_candidate_clusters,
    candidate_trade_quality_report_from_results,
    simulate_tail_entry_next_day_candidate_trade,
)
from alphaagent.server.services.backtest.tail_entry_next_day_label import build_tail_entry_next_day_label
from alphaagent.server.services.quant.factors import Bar


def _bar(day: date, close: float, *, open_price: float | None = None, high: float | None = None, low: float | None = None) -> Bar:
    return Bar(
        trade_date=day,
        open_price=open_price if open_price is not None else close,
        high_price=high if high is not None else close,
        low_price=low if low is not None else close,
        close_price=close,
        volume=1_000_000,
        turnover=100_000_000,
        change_pct=0.0,
    )


def _candidate_row(
    vt_symbol: str,
    trade_date: date,
    *,
    rank: int,
    score: float = 90.0,
    setup: str = "dragon_pullback",
    timing_window: str = "after_gold_0_5",
    market_phase: str = "uptrend",
) -> dict:
    return {
        "trade_date": trade_date,
        "vt_symbol": vt_symbol,
        "rank": rank,
        "action": "BUY",
        "total_score": score,
        "reason": {
            "action": "BUY",
            "entry_setup": setup,
            "entry_family": setup,
            "executable_entry_signal": True,
            "timing_window": timing_window,
            "market_phase": market_phase,
        },
    }


def _bars_for_return(signal_date: date, d1_close: float, *, d2_close: float = 10.4, d3_close: float = 10.5) -> list[Bar]:
    return [
        _bar(signal_date, 10.0, open_price=9.8, high=10.2, low=9.7),
        _bar(signal_date + timedelta(days=1), d1_close, open_price=10.1, high=max(d1_close, 10.3), low=min(d1_close, 9.8)),
        _bar(signal_date + timedelta(days=2), d2_close, open_price=d1_close, high=max(d2_close, d1_close) + 0.2, low=min(d2_close, 10.0)),
        _bar(signal_date + timedelta(days=3), d3_close, open_price=d2_close, high=max(d3_close, d2_close) + 0.2, low=min(d3_close, 10.0)),
    ]


def test_tail_entry_next_day_label_uses_signal_close_and_marks_hold_value() -> None:
    signal_date = date(2026, 6, 10)
    label = build_tail_entry_next_day_label(
        signal_date=signal_date,
        vt_symbol="300001.SZSE",
        bars=[
            _bar(signal_date, 10.0),
            _bar(signal_date + timedelta(days=1), 11.9, open_price=10.2, high=11.95, low=10.1),
            _bar(signal_date + timedelta(days=2), 12.1, open_price=11.9, high=12.4, low=10.2),
            _bar(signal_date + timedelta(days=3), 12.0, open_price=12.1, high=12.3, low=10.5),
        ],
    )

    assert label["status"] == "ready"
    assert label["tail_entry_price"] == 10.0
    assert label["d1_open_return_pct"] == 2.0
    assert label["d1_close_return_pct"] == 19.0
    assert label["d1_near_limit_threshold_pct"] == 19.0
    assert label["d1_near_limit_up"] is True
    assert label["d1_limit_up"] is True
    assert label["hold_to_d3_worthwhile"] is True


def test_candidate_quality_report_caps_to_top5_top10_top20_and_uses_d1_close_return() -> None:
    signal_date = date(2026, 1, 2)
    rows = [
        _candidate_row("600001.SSE", signal_date, rank=1),
        _candidate_row("600006.SSE", signal_date, rank=6),
        _candidate_row("600015.SSE", signal_date, rank=15),
        _candidate_row("600025.SSE", signal_date, rank=25),
    ]
    returns = {
        "600001.SSE": 11.0,
        "600006.SSE": 9.8,
        "600015.SSE": 10.4,
        "600025.SSE": 15.0,
    }
    results = [
        simulate_tail_entry_next_day_candidate_trade(cluster, _bars_for_return(signal_date, returns[cluster.vt_symbol]))
        for cluster in build_daily_candidate_clusters(rows)
    ]

    report = candidate_trade_quality_report_from_results(results, rank_limit=100, sample_limit=20)
    rank_limits = {row["rank_limit"]: row for row in report["by_rank_limit"]}

    assert report["rank_limit"] == 20
    assert set(rank_limits) == {5, 10, 20}
    assert report["summary"]["sample_count"] == 3
    assert report["summary"]["win_rate"] == 66.6667
    assert report["summary"]["average_return_pct"] == 4.0
    assert rank_limits[5]["average_return_pct"] == 10.0
    assert rank_limits[10]["sample_count"] == 2
    assert all(item["rank"] <= 20 for item in report["items"])
    setup_matrix = {row["setup_family"]: row for row in report["by_setup_family_rank_limit"]}
    timing_matrix = {row["timing_window"]: row for row in report["by_timing_window_rank_limit"]}
    month_matrix = {row["month"]: row for row in report["by_month_rank_limit"]}
    window_matrix = {row["evaluation_window"]: row for row in report["by_evaluation_window_rank_limit"]}
    assert setup_matrix["dragon_pullback"]["top5"]["sample_count"] == 1
    assert setup_matrix["dragon_pullback"]["top10"]["sample_count"] == 2
    assert setup_matrix["dragon_pullback"]["top20"]["sample_count"] == 3
    assert setup_matrix["dragon_pullback"]["top20"]["average_return_pct"] == 4.0
    assert timing_matrix["after_gold_0_5"]["top20"]["sample_count"] == 3
    assert month_matrix["2026-01"]["top20"]["sample_count"] == 3
    assert window_matrix["full_sample"]["top20"]["sample_count"] == 3
    first = next(item for item in report["items"] if item["rank"] == 1)
    assert first["entry_execute_date"] == signal_date.isoformat()
    assert first["tail_entry_price"] == 10.0
    assert first["d1_close_return_pct"] == 10.0
    assert first["return_pct"] == 10.0


def test_candidate_quality_report_buckets_oversold_timing_month_and_windows() -> None:
    signal_date = date(2026, 3, 13)
    row = _candidate_row(
        "002407.SZSE",
        signal_date,
        rank=3,
        setup="dragon_pullback",
        timing_window="after_silver_6_20",
        market_phase="retreat",
    )
    row["reason"].update(
        {
            "bottom_reclaim": True,
            "rebound_subtype": "bottom_reclaim",
        }
    )
    cluster = build_daily_candidate_clusters([row])[0]
    result = simulate_tail_entry_next_day_candidate_trade(cluster, _bars_for_return(signal_date, 10.5, d2_close=10.7, d3_close=10.8))

    report = candidate_trade_quality_report_from_results([result], rank_limit=20)
    setup_rows = {item["setup_family"]: item for item in report["by_setup_family"]}
    timing_rows = {item["timing_window"]: item for item in report["by_timing_window"]}
    month_rows = {item["month"]: item for item in report["by_month"]}
    setup_timing_rows = {item["setup_timing_bucket"]: item for item in report["by_setup_x_timing"]}
    window_rows = {item["evaluation_window"]: item for item in report["by_evaluation_window"]}

    assert setup_rows["bottom_reclaim"]["sample_count"] == 1
    assert timing_rows["after_silver_6_20"]["win_rate"] == 100.0
    assert month_rows["2026-03"]["average_return_pct"] == 5.0
    assert setup_timing_rows["bottom_reclaim::after_silver_6_20"]["sample_count"] == 1
    assert window_rows["silver_pressure_2026_03_13_03_24"]["sample_count"] == 1
    setup_timing_matrix = {item["setup_timing_bucket"]: item for item in report["by_setup_x_timing_rank_limit"]}
    window_matrix = {item["evaluation_window"]: item for item in report["by_evaluation_window_rank_limit"]}
    month_timing_matrix = {item["month_timing_window"]: item for item in report["by_month_timing_window_rank_limit"]}
    month_timing_phase_matrix = {item["month_timing_phase"]: item for item in report["by_month_timing_phase_rank_limit"]}
    setup_month_timing_phase_matrix = {
        item["setup_month_timing_phase_bucket"]: item
        for item in report["by_setup_month_timing_phase_rank_limit"]
    }
    assert setup_timing_matrix["bottom_reclaim::after_silver_6_20"]["top5"]["win_rate"] == 100.0
    assert month_timing_matrix["2026-03::after_silver_6_20"]["top5"]["average_return_pct"] == 5.0
    assert month_timing_phase_matrix["2026-03::after_silver_6_20::retreat"]["top5"]["win_rate"] == 100.0
    assert setup_month_timing_phase_matrix["bottom_reclaim::2026-03::after_silver_6_20::retreat"]["top5"]["sample_count"] == 1
    assert window_matrix["silver_pressure_2026_03_13_03_24"]["top5"]["average_return_pct"] == 5.0


def test_candidate_quality_report_prefers_explicit_entry_setup_over_broad_family() -> None:
    signal_date = date(2026, 6, 9)
    row = _candidate_row(
        "002407.SZSE",
        signal_date,
        rank=4,
        setup="oversold_rebound_start",
        timing_window="after_silver_6_20",
        market_phase="retreat",
    )
    row["reason"]["entry_family"] = "dragon_pullback"
    cluster = build_daily_candidate_clusters([row])[0]
    result = simulate_tail_entry_next_day_candidate_trade(cluster, _bars_for_return(signal_date, 10.3))

    report = candidate_trade_quality_report_from_results([result], rank_limit=20)
    setup_rows = {item["setup_family"]: item for item in report["by_setup_family_rank_limit"]}

    assert "dragon_pullback" not in setup_rows
    assert setup_rows["oversold_rebound_start"]["top5"]["sample_count"] == 1
