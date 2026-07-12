from __future__ import annotations

from datetime import date

import pytest

from alphaagent.server.services.backtest import ledger
from alphaagent.server.services.limit_up.cash_backtest import (
    CashBacktestConfig,
    simulate_limit_up_account,
)


def test_default_account_uses_four_positions() -> None:
    assert CashBacktestConfig().initial_cash == 100_000
    assert CashBacktestConfig().max_positions == 4


def test_buy_execution_applies_minimum_commission_transfer_fee_and_limit_cap() -> None:
    fill = ledger.calculate_buy_execution(
        raw_price=10.0,
        cash=10_000,
        target_cash=5_000,
        commission_rate=0.0003,
        slippage_bps=10,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        max_price=10.0,
    )

    assert fill.price == 10.0
    assert fill.volume == 500
    assert fill.amount == 5_000.0
    assert fill.fee == pytest.approx(5.05)
    assert fill.cash_after == pytest.approx(4_994.95)


def test_sell_execution_applies_minimum_commission_transfer_fee_and_floor() -> None:
    fill = ledger.calculate_sell_execution(
        raw_price=9.0,
        volume=500,
        cost_price=10.0,
        commission_rate=0.0003,
        stamp_tax_rate=0.0005,
        slippage_bps=10,
        minimum_commission=5.0,
        transfer_fee_rate=0.00001,
        min_price=9.0,
    )

    assert fill.price == 9.0
    assert fill.amount == 4_500.0
    assert fill.fee == pytest.approx(7.295)
    assert fill.cash_delta == pytest.approx(4_492.705)
    assert fill.pnl == pytest.approx(-507.295)


def test_next_close_position_cash_cannot_fund_next_morning_buy() -> None:
    result = simulate_limit_up_account(
        signals=[
            _signal("600001.SSE", "2026-01-02", "2026-01-05"),
            _signal("600002.SSE", "2026-01-05", "2026-01-06"),
        ],
        bars=[
            _bar("600001.SSE", "2026-01-02", 10.0, 10.0),
            _bar("600001.SSE", "2026-01-05", 11.0, 11.0),
            _bar("600002.SSE", "2026-01-05", 10.0, 10.0),
            _bar("600002.SSE", "2026-01-06", 11.0, 11.0),
        ],
        trade_dates=_dates("2026-01-02", "2026-01-05", "2026-01-06"),
        exit_mode="next_close",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=1),
    )

    assert result["execution_summary"]["buy_count"] == 1
    assert result["execution_summary"]["trade_count"] == 1
    assert _buy_order(result, "600002.SSE")["status"] == "skipped"
    assert _buy_order(result, "600002.SSE")["reason"] == "position_limit"
    assert min(row["cash"] for row in result["equity_curve"]) >= 0


def test_open_sale_releases_slot_for_later_first_board_not_same_auction() -> None:
    old_position = _signal("600001.SSE", "2026-01-02", "2026-01-05")
    auction_candidate = _signal("600002.SSE", "2026-01-05", "2026-01-06")
    intraday_candidate = _signal(
        "600003.SSE",
        "2026-01-05",
        "2026-01-06",
        buy_time="10:08:00",
        lane="first_board",
        signal_kind="first_touch",
        limit_price=10.0,
    )
    result = simulate_limit_up_account(
        signals=[old_position, auction_candidate, intraday_candidate],
        bars=[
            _bar("600001.SSE", "2026-01-02", 10.0, 10.0),
            _bar("600001.SSE", "2026-01-05", 11.0, 11.0),
            _bar("600002.SSE", "2026-01-05", 10.0, 10.0),
            _bar("600002.SSE", "2026-01-06", 11.0, 11.0),
            _bar("600003.SSE", "2026-01-05", 9.8, 10.0),
            _bar("600003.SSE", "2026-01-06", 11.0, 11.0),
        ],
        trade_dates=_dates("2026-01-02", "2026-01-05", "2026-01-06"),
        exit_mode="next_open",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=1),
    )

    assert _buy_order(result, "600002.SSE")["status"] == "skipped"
    assert _buy_order(result, "600003.SSE")["status"] == "filled"
    assert result["execution_summary"]["buy_count"] == 2
    assert result["execution_summary"]["trade_count"] == 2


def test_execution_summary_counts_only_closed_real_trades() -> None:
    result = simulate_limit_up_account(
        signals=[
            _signal("600001.SSE", "2026-01-02", "2026-01-05"),
            _signal("600002.SSE", "2026-01-02", "2026-01-05"),
            _signal("600003.SSE", "2026-01-02", "2026-01-06"),
        ],
        bars=[
            _bar("600001.SSE", "2026-01-02", 10.0, 10.0),
            _bar("600002.SSE", "2026-01-02", 10.0, 10.0),
            _bar("600003.SSE", "2026-01-02", 10.0, 10.0),
            _bar("600001.SSE", "2026-01-05", 11.0, 11.0),
            _bar("600002.SSE", "2026-01-05", 9.0, 9.1),
        ],
        trade_dates=_dates("2026-01-02", "2026-01-05"),
        exit_mode="next_close",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=4),
    )

    summary = result["execution_summary"]
    assert summary["buy_count"] == 3
    assert summary["trade_count"] == 2
    assert summary["open_position_count"] == 1
    assert summary["win_rate"] == 50.0
    assert summary["total_return_pct"] == round(
        (summary["final_equity"] / 100_000 - 1) * 100,
        4,
    )


def test_limit_down_close_defers_exit_until_next_tradeable_open() -> None:
    result = simulate_limit_up_account(
        signals=[_signal("600001.SSE", "2026-01-02", "2026-01-05")],
        bars=[
            _bar("600001.SSE", "2026-01-02", 10.0, 10.0),
            _bar("600001.SSE", "2026-01-05", 9.5, 9.0),
            _bar("600001.SSE", "2026-01-06", 9.5, 9.6),
        ],
        trade_dates=_dates("2026-01-02", "2026-01-05", "2026-01-06"),
        exit_mode="next_close",
        config=CashBacktestConfig(initial_cash=100_000, max_positions=4),
    )

    assert result["execution_summary"]["trade_count"] == 1
    trade = result["executed_trades"][0]
    assert trade["sell_date"] == "2026-01-06"
    assert trade["sell_time"] == "09:30:00"
    assert trade["exit_reason"] == "retry_open"
    assert result["equity_curve"][1]["position_count"] == 1


def test_first_board_buy_slippage_does_not_exceed_limit_price() -> None:
    result = simulate_limit_up_account(
        signals=[
            _signal(
                "600001.SSE",
                "2026-01-02",
                "2026-01-05",
                buy_time="10:08:00",
                lane="first_board",
                signal_kind="first_touch",
                limit_price=10.0,
            )
        ],
        bars=[
            _bar("600001.SSE", "2026-01-02", 9.5, 10.0),
            _bar("600001.SSE", "2026-01-05", 10.5, 10.5),
        ],
        trade_dates=_dates("2026-01-02", "2026-01-05"),
        exit_mode="next_open",
    )

    assert _buy_order(result, "600001.SSE")["price"] == 10.0


def test_latest_signal_without_d1_stays_open_and_out_of_win_rate() -> None:
    signal = _signal("600001.SSE", "2026-01-02", "2026-01-05")
    signal["result_date"] = None

    result = simulate_limit_up_account(
        signals=[signal],
        bars=[_bar("600001.SSE", "2026-01-02", 10.0, 10.0)],
        trade_dates=_dates("2026-01-02"),
        exit_mode="next_close",
    )

    summary = result["execution_summary"]
    assert summary["buy_count"] == 1
    assert summary["trade_count"] == 0
    assert summary["open_position_count"] == 1
    assert summary["win_rate"] is None


def _signal(
    vt_symbol: str,
    entry_date: str,
    result_date: str,
    *,
    buy_time: str = "09:25:00",
    lane: str = "two_to_three",
    signal_kind: str = "auction",
    limit_price: float = 11.0,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "name": vt_symbol,
        "lane": lane,
        "signal_kind": signal_kind,
        "entry_date": entry_date,
        "signal_date": entry_date,
        "result_date": result_date,
        "buy_time": buy_time,
        "entry_price": 10.0,
        "limit_price": limit_price,
        "rank_score": 80.0,
        "lane_rank": 1,
        "outcome": {"entry_day_close_price": 10.0},
    }


def _bar(
    vt_symbol: str,
    trade_date: str,
    open_price: float,
    close_price: float,
) -> dict[str, object]:
    return {
        "vt_symbol": vt_symbol,
        "trade_date": trade_date,
        "open_price": open_price,
        "high_price": max(open_price, close_price),
        "low_price": min(open_price, close_price),
        "close_price": close_price,
    }


def _dates(*values: str) -> list[date]:
    return [date.fromisoformat(value) for value in values]


def _buy_order(result: dict[str, object], vt_symbol: str) -> dict[str, object]:
    orders = result["orders"]
    assert isinstance(orders, list)
    return next(
        order
        for order in orders
        if order["side"] == "BUY" and order["vt_symbol"] == vt_symbol
    )
