"""Tests for the leader minute-level backtest buy rules."""

from __future__ import annotations

from alphaagent.server.services.limit_up.cash_backtest import CashBacktestConfig
from alphaagent.server.services.limit_up.leader_minute_backtest import (
    simulate_minute_account,
)

TRADE_DATES = ["2026-07-29", "2026-07-30"]


def _signal(symbol="A", first_limit_time="09:35:00", score=1.0):
    return {
        "vt_symbol": symbol,
        "trade_date": "2026-07-30",
        "score": score,
        "name": symbol,
        "first_limit_time": first_limit_time,
    }


def _daily_bars(prev_close=9.9, open_price=10.0, close_price=10.5, symbol="A"):
    return [
        {"vt_symbol": symbol, "trade_date": "2026-07-29", "open_price": prev_close, "close_price": prev_close},
        {"vt_symbol": symbol, "trade_date": "2026-07-30", "open_price": open_price, "close_price": close_price},
    ]


def _minute_bars(symbol, closes):
    """closes: list of (time_str, close_price) within 09:31-09:40."""
    return {
        (symbol, "2026-07-30"): [
            {"bar_time": t, "close_price": c, "open_price": c, "high_price": c, "low_price": c}
            for t, c in closes
        ]
    }


def _run(signals, minute_bars, daily_bars):
    return simulate_minute_account(
        signals,
        minute_bars,
        daily_bars,
        TRADE_DATES,
        config=CashBacktestConfig(max_positions=3),
    )


def test_buy_on_surge() -> None:
    # 9:31 close=10.0, 9:32 close=10.3 → surge=3% ≥2% 触发；first_limit 09:35 晚于买入 09:32
    result = _run(
        [_signal()],
        _minute_bars("A", [("09:31:00", 10.0), ("09:32:00", 10.3)]),
        _daily_bars(),
    )
    trades = result["closed_trades"]
    assert len(trades) >= 1
    assert abs(trades[0]["buy_price"] - 10.3) < 0.02
    assert trades[0]["buy_time"] == "09:32:00"


def test_skip_fast_board() -> None:
    # 秒板：first_limit 09:30 早于买入 09:32 → 实盘买不到，跳过
    result = _run(
        [_signal(first_limit_time="09:30:00")],
        _minute_bars("A", [("09:31:00", 10.0), ("09:32:00", 10.3)]),
        _daily_bars(),
    )
    assert result["closed_trades"] == []


def test_no_trigger_no_buy() -> None:
    # 窗口内涨幅平稳（surge<2%、cum<7%）→ 不触发买入
    result = _run(
        [_signal()],
        _minute_bars("A", [("09:31:00", 10.0), ("09:32:00", 10.1), ("09:33:00", 10.15)]),
        _daily_bars(),
    )
    assert result["closed_trades"] == []
