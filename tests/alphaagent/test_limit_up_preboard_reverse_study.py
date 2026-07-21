from __future__ import annotations

from datetime import date

from alphaagent.server.services.limit_up.preboard_reverse_study import (
    build_reverse_report,
    render_reverse_markdown,
)


def test_reverse_report_separates_formal_and_account_identities() -> None:
    dates = ("2026-01-05", "2026-01-06", "2026-01-07")
    prefixes: list[dict[str, object]] = []
    formal_orders: list[dict[str, object]] = []
    filled_orders: list[dict[str, object]] = []
    for index, signal_date in enumerate(dates, start=1):
        positive = f"60000{index}.SSE"
        control = f"60001{index}.SSE"
        prefixes.extend(
            [
                _row(positive, signal_date, gain=8.0, rank=80.0, shared=True),
                _row(control, signal_date, gain=4.0, rank=60.0, shared=True),
            ]
        )
        formal_orders.append(_formal_order(positive, signal_date))
        filled_orders.append(_filled_order(positive, signal_date))
    formal_orders.append(
        {
            "vt_symbol": "600099.SSE",
            "entry_date": dates[0],
            "lane": "two_to_three",
            "buy_time": "10:15:00",
        }
    )
    account_orders = {
        "full": filled_orders,
        "fit": [filled_orders[0]],
        "calibration": [filled_orders[1]],
        "validation": [filled_orders[2]],
    }

    report = build_reverse_report(
        prefixes,
        formal_orders,
        account_orders,
        fit_dates={date(2026, 1, 5)},
        calibration_dates={date(2026, 1, 6)},
        validation_dates={date(2026, 1, 7)},
    )

    assert report["identity_counts"]["formal_first_board_pairs"] == 3
    assert report["identity_counts"]["account_filled_first_board_pairs"] == 3
    account = report["horizons"]["10"]["account"]
    assert account["observed_3pct"]["reachable_count"] == 3
    assert account["shared_eligible"]["top2_capture"]["rank_score"] == 3
    assert report["phases"]["fit"]["identity_counts"][
        "formal_first_board_pairs"
    ] == 1
    assert report["phases"]["viewed_validation"]["identity_counts"][
        "account_filled_first_board_pairs"
    ] == 1
    assert any(
        row["feature"] == "gain_pct"
        and row["direction"] == "higher"
        and row["horizon_minutes"] == 10
        for row in report["registered_feature_directions"]
    )


def test_reverse_report_counts_shared_filter_blockers() -> None:
    signal_date = "2026-01-05"
    positive = _row(
        "600001.SSE",
        signal_date,
        gain=6.0,
        rank=70.0,
        shared=False,
    )
    positive["shared_lane_blockers"] = ["intraday_support_breakdown"]
    positive["current_momentum_gate_passed"] = False
    positive["support_score"] = 40.0

    report = build_reverse_report(
        [positive],
        [_formal_order("600001.SSE", signal_date)],
        {
            "full": [_filled_order("600001.SSE", signal_date)],
            "fit": [_filled_order("600001.SSE", signal_date)],
            "calibration": [],
            "validation": [],
        },
        fit_dates={date(2026, 1, 5)},
        calibration_dates=set(),
        validation_dates=set(),
    )

    account = report["horizons"]["10"]["account"]
    assert account["observed_3pct"]["reachable_count"] == 1
    assert account["shared_eligible"]["reachable_count"] == 0
    assert account["shared_eligible"]["blocker_counts"] == {
        "intraday_support_breakdown": 1,
        "support_below_55": 1,
    }


def test_reverse_markdown_labels_validation_as_viewed_history() -> None:
    report = build_reverse_report(
        [],
        [],
        {"full": [], "fit": [], "calibration": [], "validation": []},
        fit_dates=set(),
        calibration_dates=set(),
        validation_dates=set(),
    )

    markdown = render_reverse_markdown(
        {
            **report,
            "status": "ready_reverse_diagnostic",
            "scope": {
                "date_start": "2026-04-20",
                "date_end": "2026-07-16",
                "session_count": 60,
            },
        }
    )

    assert "已查看历史" in markdown
    assert "反向" in markdown
    assert "不能直接成为实时规则" in markdown


def _formal_order(symbol: str, signal_date: str) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "entry_date": signal_date,
        "lane": "first_board",
        "buy_time": "10:20:00",
        "result_date": "2026-01-08",
    }


def _filled_order(symbol: str, signal_date: str) -> dict[str, object]:
    return {
        **_formal_order(symbol, signal_date),
        "side": "BUY",
        "status": "filled",
    }


def _row(
    symbol: str,
    signal_date: str,
    *,
    gain: float,
    rank: float,
    shared: bool,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "signal_date": signal_date,
        "signal_time": "10:10:00",
        "signal_at": f"{signal_date}T10:10:00",
        "before_first_limit_touch": True,
        "shared_strategy_passed": shared,
        "shared_lane_blockers": [],
        "current_momentum_gate_passed": True,
        "support_score": 60.0,
        "entry_quality_score": 65.0,
        "rank_score": rank,
        "features": {
            "gain_pct": gain,
            "return_30m_pct": gain - 2.0,
            "prior_30m_range_pct": 1.0,
            "prior_30m_floor_pct": 2.0,
            "breakout_margin_pct": gain - 3.0,
            "opening_gap_pct": 1.0,
            "minute_of_window": 10.0,
        },
        "ignition_features": {
            "gain_pct": gain,
            "return_5m_pct": 0.5 + gain / 20,
            "return_15m_pct": 1.0 + gain / 10,
            "acceleration_pct": gain / 20,
            "distance_to_limit_pct": 10.0 - gain,
            "session_drawdown_pct": -0.2,
            "bar_close_location": 0.8,
            "volume_ratio_30m": 1.0 + gain / 20,
            "amount_ratio_30m": 1.1 + gain / 20,
            "amount_acceleration_ratio": 1.0 + gain / 20,
            "support_score": 60.0,
            "entry_quality_score": 65.0,
            "rank_score": rank,
        },
    }
