from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from alphaagent.server.services.low_suction.outcomes import (
    DAILY_PROXY_EXIT_OFFSETS,
    generate_daily_proxy_outcomes,
)


def _trading_dates() -> tuple[date, ...]:
    start = date(2026, 7, 13)
    return tuple(start + timedelta(days=index) for index in range(8))


def _events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "EVENT_A",
                "vt_symbol": "600000.SSE",
                "trade_date": date(2026, 7, 13),
                "evidence_level": "membership_proxy",
            }
        ]
    )


def _bars() -> pd.DataFrame:
    rows = []
    for index, trade_date in enumerate(_trading_dates()):
        rows.append(
            {
                "vt_symbol": "600000.SSE",
                "trade_date": trade_date,
                "open_price": 10.0 + index * 0.1,
                "close_price": 10.05 + index * 0.1,
                "high_price": 10.1 + index * 0.1,
                "low_price": 9.9 + index * 0.1,
                "limit_up_price": 11.0 + index * 0.1,
                "limit_down_price": 9.0 + index * 0.1,
                "suspended": False,
            }
        )
    return pd.DataFrame(rows)


def test_daily_proxy_exit_offsets_respect_t_plus_one() -> None:
    assert DAILY_PROXY_EXIT_OFFSETS == {
        "entry_plus_1_close": 1,
        "entry_plus_3_close": 3,
        "entry_plus_5_close": 5,
    }
    outcomes = generate_daily_proxy_outcomes(
        _events(),
        _bars(),
        trading_dates=_trading_dates(),
    )
    entry_date = pd.Timestamp("2026-07-14")

    assert set(outcomes["entry_date"]) == {entry_date}
    assert (outcomes["exit_date"] > outcomes["entry_date"]).all()
    assert outcomes.set_index("exit_key").loc[
        "entry_plus_1_close", "exit_date"
    ] == pd.Timestamp("2026-07-15")


def test_cost_adjusted_return_includes_lots_fees_and_slippage() -> None:
    outcomes = generate_daily_proxy_outcomes(
        _events(),
        _bars(),
        trading_dates=_trading_dates(),
    )
    closed = outcomes.loc[outcomes["status"] == "closed"]

    assert not closed.empty
    assert (closed["volume"] % 100 == 0).all()
    assert (closed["total_fees"] > 0).all()
    assert (closed["net_return_pct"] < closed["gross_return_pct"]).all()


def test_double_cost_stress_reduces_net_return() -> None:
    normal = generate_daily_proxy_outcomes(
        _events(),
        _bars(),
        trading_dates=_trading_dates(),
        cost_multiplier=1.0,
    )
    stressed = generate_daily_proxy_outcomes(
        _events(),
        _bars(),
        trading_dates=_trading_dates(),
        cost_multiplier=2.0,
    )

    assert stressed.iloc[0]["net_return_pct"] < normal.iloc[0]["net_return_pct"]


def test_entry_at_limit_up_is_rejected() -> None:
    bars = _bars()
    entry_mask = bars["trade_date"] == date(2026, 7, 14)
    bars.loc[entry_mask, "open_price"] = bars.loc[entry_mask, "limit_up_price"]

    outcomes = generate_daily_proxy_outcomes(
        _events(),
        bars,
        trading_dates=_trading_dates(),
    )

    assert set(outcomes["status"]) == {"rejected"}
    assert set(outcomes["reason"]) == {"entry_at_limit_up"}


def test_missing_entry_bar_is_rejected_not_deferred() -> None:
    bars = _bars()
    bars = bars.loc[bars["trade_date"] != date(2026, 7, 14)]

    outcomes = generate_daily_proxy_outcomes(
        _events(),
        bars,
        trading_dates=_trading_dates(),
    )

    assert set(outcomes["reason"]) == {"missing_entry_bar"}


def test_suspended_entry_is_rejected() -> None:
    bars = _bars()
    entry_mask = bars["trade_date"] == date(2026, 7, 14)
    bars.loc[entry_mask, "suspended"] = True

    outcomes = generate_daily_proxy_outcomes(
        _events(),
        bars,
        trading_dates=_trading_dates(),
    )

    assert set(outcomes["reason"]) == {"entry_suspended"}


def test_one_price_limit_down_exit_remains_unclosed() -> None:
    bars = _bars()
    exit_mask = bars["trade_date"] == date(2026, 7, 15)
    bars.loc[exit_mask, "close_price"] = bars.loc[exit_mask, "limit_down_price"]
    bars.loc[exit_mask, "high_price"] = bars.loc[exit_mask, "limit_down_price"]
    bars.loc[exit_mask, "low_price"] = bars.loc[exit_mask, "limit_down_price"]

    outcomes = generate_daily_proxy_outcomes(
        _events(),
        bars,
        trading_dates=_trading_dates(),
    ).set_index("exit_key")

    assert outcomes.loc["entry_plus_1_close", "status"] == "unclosed"
    assert outcomes.loc["entry_plus_1_close", "reason"] == "exit_at_limit_down"
    assert pd.isna(outcomes.loc["entry_plus_1_close", "net_return_pct"])


def test_missing_required_price_column_is_rejected() -> None:
    with pytest.raises(ValueError, match="close_price"):
        generate_daily_proxy_outcomes(
            _events(),
            _bars().drop(columns=["close_price"]),
            trading_dates=_trading_dates(),
        )
