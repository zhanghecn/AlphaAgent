from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.leader_ma5_cash import (
    INITIAL_CASH,
    simulate_capacity_comparison,
    simulate_structural_cash_account,
)


DATES = tuple(pd.bdate_range("2025-01-02", periods=6).date)


def _bar(
    symbol: str,
    trade_date: date,
    *,
    open_price: float,
    high_price: float,
    low_price: float,
    close_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": symbol,
        "trade_date": trade_date,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
    }


def _daily_bars() -> pd.DataFrame:
    rows = []
    for symbol, offset in (("600001.SSE", 0.0), ("000001.SZSE", 5.0)):
        for index, trade_date in enumerate(DATES):
            close = 10.0 + offset + index * 0.2
            rows.append(
                _bar(
                    symbol,
                    trade_date,
                    open_price=close - 0.05,
                    high_price=close + 0.2,
                    low_price=close - 0.2,
                    close_price=close,
                )
            )
    return pd.DataFrame(rows)


def _trades() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "rank-1",
                "vt_symbol": "600001.SSE",
                "sector_id": "BK0001",
                "entry_date": DATES[1],
                "exit_date": DATES[3],
                "causal_rank": 1,
            },
            {
                "signal_id": "rank-2",
                "vt_symbol": "000001.SZSE",
                "sector_id": "BK0002",
                "entry_date": DATES[1],
                "exit_date": DATES[2],
                "causal_rank": 2,
            },
        ]
    )


def test_one_position_uses_cash_lots_fees_and_point_in_time_priority() -> None:
    result = simulate_structural_cash_account(
        _trades(),
        _daily_bars(),
        capacity=1,
    )

    ledger = {row["signal_id"]: row for row in result["trade_ledger"]}
    assert result["initial_cash"] == INITIAL_CASH
    assert result["accepted_entries"] == 1
    assert result["closed_trades"] == 1
    assert result["skipped_entries"] == 1
    assert ledger["rank-1"]["status"] == "closed"
    assert ledger["rank-1"]["volume"] % 100 == 0
    assert ledger["rank-1"]["entry_price"] > ledger["rank-1"]["entry_price_raw"]
    assert ledger["rank-1"]["exit_price"] < ledger["rank-1"]["exit_price_raw"]
    assert ledger["rank-1"]["total_fees"] > 0
    assert ledger["rank-2"]["reason"] == "capacity_full"
    assert result["minimum_cash"] >= 0
    assert result["final_equity"] > INITIAL_CASH
    assert result["compound_return_pct"] > 0


def test_same_concept_cannot_occupy_two_positions() -> None:
    trades = _trades()
    trades.loc[1, "sector_id"] = "BK0001"

    result = simulate_structural_cash_account(
        trades,
        _daily_bars(),
        capacity=2,
    )

    ledger = {row["signal_id"]: row for row in result["trade_ledger"]}
    assert result["accepted_entries"] == 1
    assert ledger["rank-2"]["reason"] == "same_concept_position"


def test_limit_up_entry_is_rejected_without_queue_evidence() -> None:
    bars = _daily_bars()
    entry_mask = (
        bars["vt_symbol"].eq("600001.SSE")
        & pd.to_datetime(bars["trade_date"]).dt.date.eq(DATES[1])
    )
    bars.loc[entry_mask, ["open_price", "high_price", "low_price", "close_price"]] = 11.0

    result = simulate_structural_cash_account(
        _trades().iloc[[0]],
        bars,
        capacity=1,
    )

    row = result["trade_ledger"][0]
    assert row["status"] == "rejected"
    assert row["reason"] == "entry_limit_up_queue_unknown_without_l2"
    assert result["final_equity"] == pytest.approx(INITIAL_CASH)


def test_one_price_limit_down_defers_exit_to_first_executable_close() -> None:
    bars = _daily_bars()
    planned_exit = (
        bars["vt_symbol"].eq("600001.SSE")
        & pd.to_datetime(bars["trade_date"]).dt.date.eq(DATES[3])
    )
    previous_close = float(
        bars.loc[
            bars["vt_symbol"].eq("600001.SSE")
            & pd.to_datetime(bars["trade_date"]).dt.date.eq(DATES[2]),
            "close_price",
        ].iloc[0]
    )
    limit_down = round(previous_close * 0.9, 2)
    bars.loc[
        planned_exit,
        ["open_price", "high_price", "low_price", "close_price"],
    ] = limit_down

    result = simulate_structural_cash_account(
        _trades().iloc[[0]],
        bars,
        capacity=1,
    )

    row = result["trade_ledger"][0]
    assert row["status"] == "closed"
    assert row["planned_exit_date"] == DATES[3]
    assert row["actual_exit_date"] == DATES[4]
    assert row["exit_deferred_sessions"] == 1


def test_suspension_marks_position_at_last_close() -> None:
    bars = _daily_bars()
    suspended = (
        bars["vt_symbol"].eq("600001.SSE")
        & pd.to_datetime(bars["trade_date"]).dt.date.eq(DATES[2])
    )
    bars = bars.loc[~suspended].copy()

    result = simulate_structural_cash_account(
        _trades().iloc[[0]],
        bars,
        capacity=1,
    )

    suspended_equity = next(
        row for row in result["equity_curve"] if row["trade_date"] == DATES[2]
    )
    entry_day_equity = next(
        row for row in result["equity_curve"] if row["trade_date"] == DATES[1]
    )
    assert suspended_equity["equity"] == pytest.approx(entry_day_equity["equity"])
    assert result["closed_trades"] == 1


def test_intraday_entry_override_replaces_daily_open() -> None:
    trades = _trades().iloc[[0]].copy()
    trades["entry_price_raw_override"] = 9.8

    result = simulate_structural_cash_account(
        trades,
        _daily_bars(),
        capacity=1,
    )

    row = result["trade_ledger"][0]
    assert row["entry_price_raw"] == pytest.approx(9.8)
    assert row["entry_price_raw"] < 10.15
    assert row["entry_price"] > row["entry_price_raw"]


def test_causal_structural_exit_uses_next_session_open() -> None:
    trades = _trades().iloc[[0]].copy()
    trades["exit_price_mode"] = "open"

    result = simulate_structural_cash_account(
        trades,
        _daily_bars(),
        capacity=1,
    )

    row = result["trade_ledger"][0]
    assert row["exit_price_mode"] == "open"
    assert row["exit_price_raw"] == pytest.approx(10.55)
    assert row["exit_price_raw"] < 10.6


def test_next_open_limit_down_defers_causal_structural_exit() -> None:
    bars = _daily_bars()
    exit_day = (
        bars["vt_symbol"].eq("600001.SSE")
        & pd.to_datetime(bars["trade_date"]).dt.date.eq(DATES[3])
    )
    previous_close = float(
        bars.loc[
            bars["vt_symbol"].eq("600001.SSE")
            & pd.to_datetime(bars["trade_date"]).dt.date.eq(DATES[2]),
            "close_price",
        ].iloc[0]
    )
    limit_down = round(previous_close * 0.9, 2)
    bars.loc[exit_day, "open_price"] = limit_down
    bars.loc[exit_day, "low_price"] = limit_down
    trades = _trades().iloc[[0]].copy()
    trades["exit_price_mode"] = "open"

    result = simulate_structural_cash_account(trades, bars, capacity=1)

    row = result["trade_ledger"][0]
    assert row["actual_exit_date"] == DATES[4]
    assert row["exit_deferred_sessions"] == 1


def test_capacity_comparison_reports_all_fixed_capacities() -> None:
    comparison = simulate_capacity_comparison(_trades(), _daily_bars())

    assert tuple(comparison) == ("capacity_1", "capacity_2", "capacity_3", "capacity_4")
    assert comparison["capacity_1"]["capacity"] == 1
    assert comparison["capacity_4"]["capacity"] == 4
    assert comparison["capacity_2"]["accepted_entries"] == 2
    assert comparison["capacity_4"]["initial_cash"] == INITIAL_CASH
