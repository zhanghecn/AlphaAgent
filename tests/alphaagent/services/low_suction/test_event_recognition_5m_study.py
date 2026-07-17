from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.event_recognition_5m_study import (
    build_event_5m_state_panel,
    build_event_5m_study_report,
    execute_event_5m_transitions,
    extract_frozen_transitions,
    summarize_event_5m_outcomes,
)
from alphaagent.server.services.low_suction.cli import build_parser


def _candidate() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": 1,
                "source_date": date(2025, 6, 27),
                "entry_date": date(2025, 6, 30),
                "planned_exit_date": date(2025, 7, 1),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "recognition_rank": 1,
                "signal_close": 10.0,
                "active_direction": "SILVER",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
            }
        ]
    )


def _minute_bars(*, future_close: float = 9.9) -> pd.DataFrame:
    morning = [datetime(2025, 6, 30, 9, 35) + timedelta(minutes=5 * index) for index in range(24)]
    afternoon = [datetime(2025, 6, 30, 13, 5) + timedelta(minutes=5 * index) for index in range(24)]
    times = [*morning, *afternoon]
    closes = [9.9, 9.7, 10.05, 10.1, 10.2, *([future_close] * 43)]
    opens = [10.0, 9.9, 9.7, 10.05, 10.1, *closes[5:]]
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 6, 30),
                "bar_time": bar_time,
                "interval": "5m",
                "open_price": open_price,
                "high_price": max(open_price, close_price) + 0.02,
                "low_price": min(open_price, close_price) - 0.02,
                "close_price": close_price,
                "volume": 1_000.0,
                "turnover": close_price * 1_000.0,
                "source": "tdx_public_hq",
            }
            for bar_time, open_price, close_price in zip(times, opens, closes, strict=True)
        ]
    )


def _daily_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 6, 30),
                "open_price": 10.0,
                "high_price": 10.3,
                "low_price": 9.6,
                "close_price": 10.1,
                "volume": 10_000.0,
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 1),
                "open_price": 10.2,
                "high_price": 10.8,
                "low_price": 10.1,
                "close_price": 10.6,
                "volume": 10_000.0,
            },
        ]
    )


def test_state_panel_is_point_in_time_and_future_bars_do_not_change_signal() -> None:
    before = extract_frozen_transitions(
        build_event_5m_state_panel(_candidate(), _minute_bars(future_close=9.9))
    )
    after = extract_frozen_transitions(
        build_event_5m_state_panel(_candidate(), _minute_bars(future_close=20.0))
    )
    identity = ["event_id", "rule", "signal_time", "entry_time", "entry_price_raw"]

    pd.testing.assert_frame_equal(before[identity], after[identity])
    assert before.groupby(["event_id", "rule"]).size().max() == 1


def test_open_reclaim_executes_at_next_five_minute_open() -> None:
    transitions = extract_frozen_transitions(
        build_event_5m_state_panel(_candidate(), _minute_bars())
    )
    open_reclaim = transitions.loc[transitions["rule"].eq("open_reclaim")].iloc[0]

    assert open_reclaim["signal_time"] == datetime(2025, 6, 30, 9, 45)
    assert open_reclaim["entry_time"] == datetime(2025, 6, 30, 9, 50)
    assert open_reclaim["entry_price_raw"] == 10.05


def test_duplicate_or_incomplete_five_minute_day_is_rejected() -> None:
    duplicate = pd.concat([_minute_bars(), _minute_bars().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="unique"):
        build_event_5m_state_panel(_candidate(), duplicate)
    with pytest.raises(ValueError, match="48"):
        build_event_5m_state_panel(_candidate(), _minute_bars().iloc[:-1])


def test_double_cost_never_improves_closed_transition_return() -> None:
    transitions = extract_frozen_transitions(
        build_event_5m_state_panel(_candidate(), _minute_bars())
    )
    normal = execute_event_5m_transitions(
        transitions,
        _daily_bars(),
        trading_dates=(date(2025, 6, 30), date(2025, 7, 1)),
        cost_multiplier=1.0,
    )
    stressed = execute_event_5m_transitions(
        transitions,
        _daily_bars(),
        trading_dates=(date(2025, 6, 30), date(2025, 7, 1)),
        cost_multiplier=2.0,
    )
    joined = normal.merge(stressed, on="transition_id", suffixes=("_normal", "_stressed"))

    assert joined["net_return_pct_stressed"].le(joined["net_return_pct_normal"]).all()


def test_report_keeps_formal_metrics_null() -> None:
    transitions = extract_frozen_transitions(
        build_event_5m_state_panel(_candidate(), _minute_bars())
    )
    normal = execute_event_5m_transitions(
        transitions,
        _daily_bars(),
        trading_dates=(date(2025, 6, 30), date(2025, 7, 1)),
    )
    stressed = execute_event_5m_transitions(
        transitions,
        _daily_bars(),
        trading_dates=(date(2025, 6, 30), date(2025, 7, 1)),
        cost_multiplier=2.0,
    )
    metrics, blocks, regimes = summarize_event_5m_outcomes(normal, stressed)
    report = build_event_5m_study_report(
        coverage={"candidate_pairs": 1, "complete_pairs": 1},
        rule_metrics=metrics,
        block_metrics=blocks,
        regime_metrics=regimes,
        minute_fingerprint="sha256:test",
    )

    assert report["formal_metrics"] is None
    assert report["holdout_price_values_read"] is False
    assert report["formal_rule_selected"] is False


def test_5m_study_cli_exposes_no_rule_or_threshold_flags() -> None:
    args = build_parser().parse_args(["v2-event-5m-study", "--format", "json"])

    assert args.command == "v2-event-5m-study"
    assert not hasattr(args, "rules")
    assert not hasattr(args, "threshold")
