from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.cli import build_parser
from alphaagent.server.services.low_suction.leader_ma5_close_study import (
    EXECUTION_ASSUMPTION,
    STUDY_VERSION,
    build_close_proxy_trades,
    build_close_study_report,
    render_leader_ma5_close_json,
    render_leader_ma5_close_markdown,
)


DATES = (
    date(2025, 1, 2),
    date(2025, 1, 3),
    date(2025, 1, 6),
    date(2025, 1, 7),
)


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "close-proxy-1",
                "vt_symbol": "600001.SSE",
                "stock_name": "日线龙头",
                "sector_id": "BK0001",
                "concept_name": "测试概念",
                "signal_date": DATES[1],
                "exit_date": DATES[2],
                "causal_rank": 1,
                "reference_peak_price": 11.5,
                "time_block": "block_1",
                "executable_exit_reason": "reference_peak_rebreak",
            }
        ]
    )


def _daily_bars(*, signal_open: float = 9.8, exit_open: float = 10.5) -> pd.DataFrame:
    prices = (
        (10.0, 10.2, 9.8, 10.0),
        (signal_open, 10.6, 9.7, 10.4),
        (exit_open, 11.3, 10.3, 11.2),
        (11.1, 11.4, 10.9, 11.3),
    )
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": trade_date,
                "open_price": open_price,
                "high_price": high_price,
                "low_price": low_price,
                "close_price": close_price,
                "volume": 1_000_000,
                "turnover": 10_000_000,
            }
            for trade_date, (open_price, high_price, low_price, close_price) in zip(
                DATES,
                prices,
                strict=True,
            )
        ]
    )


def test_close_proxy_uses_signal_and_trigger_closes_not_daily_opens() -> None:
    trades = build_close_proxy_trades(_candidates(), _daily_bars())

    assert trades.loc[0, "entry_date"] == DATES[1]
    assert trades.loc[0, "entry_price_raw_override"] == pytest.approx(10.4)
    assert trades.loc[0, "exit_date"] == DATES[2]
    assert trades.loc[0, "exit_price_mode"] == "close"

    changed_opens = _daily_bars(signal_open=10.1, exit_open=10.9)
    changed = build_close_proxy_trades(_candidates(), changed_opens)
    pd.testing.assert_frame_equal(trades, changed)


def test_close_proxy_fails_closed_when_signal_close_is_missing() -> None:
    bars = _daily_bars().loc[
        lambda frame: pd.to_datetime(frame["trade_date"]).dt.date.ne(DATES[1])
    ]

    with pytest.raises(ValueError, match="missing signal-day close"):
        build_close_proxy_trades(_candidates(), bars)


def test_close_report_is_daily_only_and_marks_same_close_as_non_executable() -> None:
    report = build_close_study_report(_candidates(), _daily_bars())

    assert report["study_version"] == STUDY_VERSION
    assert report["formal_strategy"] is False
    assert report["formal_metrics"] is None
    assert report["contract"]["bar_interval"] == "1d"
    assert report["contract"]["fund_cycle_used"] is False
    assert report["contract"]["minute_bars_used"] is False
    assert report["contract"]["entry_execution_assumption"] == EXECUTION_ASSUMPTION
    assert report["contract"]["point_in_time_executable"] is False
    assert report["coverage"]["candidate_rows"] == 1
    assert report["coverage"]["daily_close_entry_rows"] == 1
    assert report["four_position_performance"]["closed_trades"] == 1
    assert report["four_position_performance"]["trade_ledger"][0][
        "entry_price_raw"
    ] == pytest.approx(10.4)
    assert report["four_position_performance"]["trade_ledger"][0][
        "exit_price_raw"
    ] == pytest.approx(11.2)
    assert report["individual_case_ledger"][0]["net_return_pct"] > 0

    encoded = json.loads(render_leader_ma5_close_json(report))
    assert encoded["input_fingerprints"]["daily_bars"]["rows"] == 4
    markdown = render_leader_ma5_close_markdown(report)
    assert "same_close_research_proxy" in markdown
    assert "not a point-in-time executable fill" in markdown


def test_cli_registers_fixed_leader_ma5_close_study() -> None:
    args = build_parser().parse_args(
        ["v2-leader-ma5-close-study", "--format", "json"]
    )

    assert args.command == "v2-leader-ma5-close-study"
    assert args.format == "json"
