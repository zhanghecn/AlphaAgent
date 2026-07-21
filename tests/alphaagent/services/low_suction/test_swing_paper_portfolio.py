from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.swing_paper_portfolio import (
    INITIAL_CASH,
    PaperPortfolioInputError,
    detect_exit_triggers,
    plan_entry_fills,
    plan_exit_fills,
)


SHANGHAI = ZoneInfo("Asia/Shanghai")
ENTRY_AT = datetime(2026, 7, 20, 14, 55, 10, tzinfo=SHANGHAI)
OPEN_AT = datetime(2026, 7, 21, 9, 31, tzinfo=SHANGHAI)


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "signal-1",
                "strategy_version": "low-suction-swing-paper-v1",
                "signal_trade_date": date(2026, 7, 20),
                "captured_at": datetime(2026, 7, 20, 14, 50, 20, tzinfo=SHANGHAI),
                "vt_symbol": "000001.SZSE",
                "stock_name": "测试龙头",
                "sector_id": "BK_TEST",
                "sector_name": "测试主升",
                "rank": 1,
                "reference_peak_price": 14.5,
                "recommendation_state": "recommended",
            }
        ]
    )


def _entry_quotes(*, trade_time: datetime = ENTRY_AT - timedelta(seconds=2)) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "trade_time": trade_time,
                "last_price": 14.30,
                "open_price": 14.1,
                "high_price": 14.4,
                "low_price": 13.6,
                "previous_close": 14.4,
                "source": "test.quote",
            }
        ]
    )


def _empty_positions() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "signal_id",
            "vt_symbol",
            "sector_id",
            "status",
            "volume",
            "buy_cash_delta",
        ]
    )


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=["signal_id", "sell_cash_delta"])


def test_1455_entry_uses_only_a_post_signal_quote_and_one_half_equity() -> None:
    decisions = plan_entry_fills(
        _signals(),
        _empty_positions(),
        _empty_trades(),
        _entry_quotes(),
        captured_at=ENTRY_AT,
    )

    assert len(decisions) == 1
    fill = decisions[0]
    assert fill.status == "filled"
    assert fill.raw_price == pytest.approx(14.30)
    assert fill.volume % 100 == 0
    assert fill.entry_amount + fill.buy_fee <= INITIAL_CASH / 2
    assert fill.cash_after >= 0
    assert fill.broker_order_created is False


def test_entry_rejects_a_quote_from_before_1455() -> None:
    before_entry = datetime(2026, 7, 20, 14, 54, 59, tzinfo=SHANGHAI)

    with pytest.raises(PaperPortfolioInputError, match="entry quote before 14:55"):
        plan_entry_fills(
            _signals(),
            _empty_positions(),
            _empty_trades(),
            _entry_quotes(trade_time=before_entry),
            captured_at=ENTRY_AT,
        )


def _open_position() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "signal_id": "signal-1",
                "strategy_version": "low-suction-swing-paper-v1",
                "vt_symbol": "000001.SZSE",
                "stock_name": "测试龙头",
                "sector_id": "BK_TEST",
                "sector_name": "测试主升",
                "status": "open",
                "entry_trade_date": date(2026, 7, 20),
                "entry_at": ENTRY_AT,
                "entry_price": 14.31,
                "entry_amount": 24_000.0,
                "volume": 1_700,
                "buy_fee": 5.0,
                "buy_cash_delta": -24_005.0,
                "reference_peak_price": 14.5,
                "exit_deferred_sessions": 0,
            }
        ]
    )


def _daily_bars() -> pd.DataFrame:
    dates = tuple(timestamp.date() for timestamp in pd.bdate_range(end="2026-07-20", periods=22))
    rows = []
    for index, trade_date in enumerate(dates):
        close = 12.0 + index * 0.1
        high = close + 0.2
        if trade_date == date(2026, 7, 20):
            high = 14.6
            close = 14.4
        rows.append(
            {
                "vt_symbol": "000001.SZSE",
                "trade_date": trade_date,
                "open_price": close - 0.1,
                "high_price": high,
                "low_price": close - 0.2,
                "close_price": close,
                "volume": 10_000_000.0,
            }
        )
    return pd.DataFrame(rows)


def test_structural_trigger_does_not_fabricate_an_exit_fill() -> None:
    triggers = detect_exit_triggers(
        _open_position(),
        _daily_bars(),
        as_of_date=date(2026, 7, 20),
    )

    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger.trigger_date == date(2026, 7, 20)
    assert trigger.trigger_reason == "reference_peak_rebroken"
    assert trigger.exit_price is None


def test_pending_exit_fills_at_the_next_session_open() -> None:
    pending = _open_position().assign(
        status="exit_pending",
        exit_trigger_date=date(2026, 7, 20),
        exit_trigger_reason="reference_peak_rebroken",
        exit_due_after=date(2026, 7, 20),
    )
    quotes = pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "trade_time": OPEN_AT - timedelta(seconds=2),
                "open_price": 14.8,
                "last_price": 14.75,
                "previous_close": 14.4,
                "source": "test.quote",
            }
        ]
    )

    decisions = plan_exit_fills(pending, quotes, captured_at=OPEN_AT)

    assert len(decisions) == 1
    fill = decisions[0]
    assert fill.status == "filled"
    assert fill.exit_trade_date == date(2026, 7, 21)
    assert fill.raw_price == pytest.approx(14.8)
    assert fill.net_pnl is not None
    assert fill.net_return_pct is not None
    assert fill.broker_order_created is False


def test_limit_down_open_defers_the_paper_exit() -> None:
    pending = _open_position().assign(
        status="exit_pending",
        exit_trigger_date=date(2026, 7, 20),
        exit_trigger_reason="two_closes_below_ma20",
        exit_due_after=date(2026, 7, 20),
    )
    quotes = pd.DataFrame(
        [
            {
                "vt_symbol": "000001.SZSE",
                "trade_time": OPEN_AT - timedelta(seconds=2),
                "open_price": 12.96,
                "last_price": 12.96,
                "previous_close": 14.4,
                "source": "test.quote",
            }
        ]
    )

    decisions = plan_exit_fills(pending, quotes, captured_at=OPEN_AT)

    assert decisions[0].status == "deferred"
    assert decisions[0].reason == "limit_down_open"
    assert decisions[0].exit_price is None
