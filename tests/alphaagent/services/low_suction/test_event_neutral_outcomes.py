from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd

from alphaagent.server.services.low_suction.event_neutral_outcomes import (
    label_event_neutral_outcomes,
)


def _panel(*, next_open: float = 9.8) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_id": "1:2025-07-02T10:00:00",
                "event_id": 1,
                "source_date": date(2025, 7, 2),
                "entry_date": date(2025, 7, 2),
                "planned_exit_date": date(2025, 7, 3),
                "sector_id": "BK0963",
                "concept_name": "商业航天",
                "cycle_id": "cycle-1",
                "vt_symbol": "600001.SSE",
                "recognition_rank": 1,
                "signal_close": 10.0,
                "active_direction": "SILVER",
                "danger_state": "NORMAL",
                "market_phase": "recovery",
                "observed_at": datetime(2025, 7, 2, 10, 0),
                "next_bar_time": datetime(2025, 7, 2, 10, 5),
                "next_bar_open": next_open,
                "close_price": 9.75,
                "vwap": 9.7,
            }
        ]
    )


def _daily_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 2),
                "open_price": 9.9,
                "high_price": 10.1,
                "low_price": 9.5,
                "close_price": 9.9,
                "volume": 10_000.0,
            },
            {
                "vt_symbol": "600001.SSE",
                "trade_date": date(2025, 7, 3),
                "open_price": 10.0,
                "high_price": 10.7,
                "low_price": 9.9,
                "close_price": 10.5,
                "volume": 10_000.0,
            },
        ]
    )


def test_state_fills_at_next_bar_open_and_exits_d1_close() -> None:
    outcomes = label_event_neutral_outcomes(
        _panel(),
        _daily_bars(),
        trading_dates=(date(2025, 7, 2), date(2025, 7, 3)),
    )
    row = outcomes.iloc[0]

    assert row["observation_id"] == "1:2025-07-02T10:00:00"
    assert row["entry_time"] == datetime(2025, 7, 2, 10, 5)
    assert row["entry_price_raw"] == 9.8
    assert row["entry_price"] > 9.8
    assert row["exit_price_raw"] == 10.5
    assert row["status"] == "closed"


def test_double_cost_never_improves_return() -> None:
    normal = label_event_neutral_outcomes(
        _panel(),
        _daily_bars(),
        trading_dates=(date(2025, 7, 2), date(2025, 7, 3)),
    )
    stressed = label_event_neutral_outcomes(
        _panel(),
        _daily_bars(),
        trading_dates=(date(2025, 7, 2), date(2025, 7, 3)),
        cost_multiplier=2.0,
    )

    assert stressed["net_return_pct"].item() < normal["net_return_pct"].item()


def test_limit_up_next_bar_is_rejected() -> None:
    outcomes = label_event_neutral_outcomes(
        _panel(next_open=11.0),
        _daily_bars(),
        trading_dates=(date(2025, 7, 2), date(2025, 7, 3)),
    )

    assert outcomes["status"].item() == "rejected"
    assert outcomes["reason"].item() == "entry_at_limit_up"


def test_feature_module_does_not_import_outcome_module() -> None:
    panel_path = Path(
        "alphaagent/server/services/low_suction/event_neutral_panel.py"
    )

    assert "event_neutral_outcomes" not in panel_path.read_text(encoding="utf-8")
